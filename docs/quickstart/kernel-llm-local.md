# Quickstart — what K5 (`kernel.llm.local`) can do today

**Status: honest, and partial.** Five of the eight kernels have landed; this page
covers the local-generation one. Everything below has been run against a live Ollama
runtime and its output is quoted from a real invocation.

`docflow-kernel` now dispatches this kernel's operations — see `lab-cli.md` for the
bench. This page drives the **library**, called from Python, which is where the
detail lives. That is
the intended shape: `sad.md` ADR-008 makes the library first and the CLI one caller
of it.

---

## Setup

```bash
pip install -e ".[dev]"      # pytest, ruff, pylint
pip install httpx            # the transport
ollama serve                 # the runtime, if it is not already running
ollama pull smollm2          # a small model to try this on
```

The adapter speaks Ollama's **HTTP API directly** through `httpx`, not the `ollama`
Python package. The package is one option; speaking the API keeps the response
fields this kernel depends on — `done_reason` above all — visible at the boundary
instead of behind a client library's abstraction.

The default address is `http://127.0.0.1:11434`. Override it with
`DOCFLOW_OLLAMA_HOST` (see *There is no model setting* below for what may and may not
be configured).

## Where K5's code lives

K5 is a **kernel** — it has its own row in `sad.md` §3, its determinism class
(`sampled`) and its resource slot (`gpu`). Its code sits in two files rather than in
`kernels/`:

| File | What it holds | Landed by |
|---|---|---|
| `docflow/ports/llm.py` | the `LlmEngine` interface | `E04-01` (`S1-T11`) |
| `docflow/adapters/ollama.py` | the engine itself, behind the port | `E04-05` (`S1-T15`) |

That split is the architecture, not an accident: K2 and K3 live in `kernels/`
because their engines are not behind a swap-able vendor boundary, while K4, K5 and
K6 live in `adapters/` because theirs are. The dependency arrow still points down —
the port is imported by the adapter, never the reverse.

## The whole surface

```python
from docflow.adapters.ollama import OllamaEngine

engine = OllamaEngine()          # the address is defaulted; no model ever is
```

| Operation | Answers |
|---|---|
| `capabilities(model)` | Which bytes is this model, and under what window? |
| `warm(model)` | Load it, so the first real call is not the slow one |
| `structured(model, prompt, schema)` | A JSON answer satisfying a schema |
| `vision(model, prompt, images, schema)` | The same, about images |
| `judge(model, rubric, samples, produced_by)` | Grade samples against a rubric |

A `KernelResult` carries one of two things: a `value`, or a `reason`. It never
carries a stand-in for a missing answer.

---

## 1. `capabilities` — which bytes is this model?

```python
r = engine.capabilities('smollm2:latest')
r.value.observed
```

```python
{
  'model': 'smollm2:latest',
  'model_revision': 'cef4a1e09247f018ca0c482ad4c2ce1474aba5e87f245dacf97f07948d05d8b4',
  'first_seen_revision': 'cef4a1e09247f018ca0c482ad4c2ce1474aba5e87f245dacf97f07948d05d8b4',
  'revision_changed': False,
  'num_ctx': 4096,
  'params': {},
  'tag_is_moving': True,
  'family': 'llama',
  'parameter_size': '1.7B',
  'quantization': 'Q8_0',
  'capabilities': ['completion', 'tools'],
  'supports_vision': False,
}
```

### The digest, not the tag — and why it is the whole point

`smollm2:latest` is a **moving tag**. Pull it again and the name resolves to
different bytes; every later value was then produced by a model nobody chose, and
nothing in the output would say so. The digest is the identity, and it is read from
`/api/tags` — the one endpoint that carries it (`/api/show` does not, despite
describing a single model in more detail).

`tag_is_moving: True` states the trap rather than leaving it to be remembered.

### `revision_changed` — the comparison, for the whole run

The digest is recorded the **first** time a model is seen in this adapter's lifetime
and compared on every later resolution. A `pull` under a moving tag mid-run then
surfaces as a **difference** rather than a surprise:

```python
engine.capabilities('qwen2.5').value.observed['revision_changed']   # False
# ... an operator runs `ollama pull qwen2.5` ...
engine.capabilities('qwen2.5').value.observed['revision_changed']   # True
```

That is `kernel-cli.md` §11 row 13. The fixture for it (`model-swap.md`) is a
**recipe, not a document**: call `capabilities`, pull, call again, compare.

### `num_ctx` is the *loaded* window, not the declared one

They differ. Measured on this machine: `smollm2` declares `context_length: 8192` in
its metadata but loads under a **4096** window when no `num_ctx` is named. Reporting
the declared figure would report a number nothing used — the same class of error as
keying on a moving tag.

So the value comes from `/api/ps`, which reports what is actually loaded, and is read
**after** the generation: the call is what loads the model, and a pre-call read
reports the *previous* call's window. When the model is not loaded, `num_ctx` is
`None` — *not loaded* — rather than the declared number, because the two answer
different questions.

### A model that is not there

```python
r = engine.capabilities('no-existe:9b')
```

```python
r.value            # None
r.reason.code      # 'model_not_pulled'
r.reason.message   # "the model 'no-existe:9b' is not present in this Ollama runtime.
                   #  Pull it first: `ollama pull no-existe:9b`. The available models
                   #  are ['deepseek-r1:1.5b', 'granite3.1-moe:1b', ...]; no default
                   #  is substituted."
r.evidence.observed['available']   # every model the runtime does hold, sorted
```

The remedy is **in the message**, and the alternatives are **in the evidence**, so an
operator reading only the code can act without guessing.

---

## 2. `structured` — a JSON answer against a schema

```python
r = engine.structured(
    'smollm2:latest',
    'Devuelve el total 1500 como JSON.',
    {'type': 'object', 'properties': {'total': {'type': 'string'}}, 'required': ['total']},
)
dict(r.value)     # {'total': "{{'1500': True}}"}
```

The schema is passed to the runtime's `format` field as a schema **object**, not the
string `"json"`, so the constraint is applied during generation rather than checked
afterwards.

**Note what came back.** A 1.7B model produced `"{{'1500': True}}"` for a field the
schema said was a string. It is a *valid* answer to the schema — a string is a string
— and it is nonsense. That is the honest output, quoted from a real call, and it is
the reason this project exists: **the adapter's job is not to make a small model
correct.** It is to report what the model said, which bytes said it, and whether the
answer was cut, so that a *later* layer can compare two reads and notice they disagree.
A page that showed `'1500'` here would be a page that had tidied the evidence.

### Truncation is a failure, never a value

A generation cut by the context window is reported, not parsed:

```python
# with DOCFLOW_OLLAMA_NUM_PREDICT=8
r.value                                        # None
r.reason.code                                  # 'truncated_output'
r.evidence.observed['done_reason']             # 'length'
r.evidence.observed['raw_completion']          # '{\n   "c" : "[{"' — a partial object, kept
```

The exact characters of `raw_completion` differ between calls — K5 is a `sampled`
kernel (`kernel-cli.md` §7), so the text is not reproducible and this page does not
pretend to quote it twice. What **is** reproducible, and what the assertions target,
is the shape: a `Reason` with the code `truncated_output`, the `done_reason` that
produced it, and a `raw_completion` that is visibly **not** a complete object.

This is the failure `kernel-cli.md` §11 row 12 exists for, and it is subtle: a cut
that lands **after** the last complete field parses cleanly. An adapter that parses
first and checks afterwards returns a value — which is how a partial answer gets
reported as a whole one. Here the cut is detected from `done_reason` **before** any
parse, and the raw completion is kept on the evidence either way, so a truncated call
and a complete one stay distinguishable without invoking the model again.

### A third, quieter cut — the input

While verifying row 12 against a live runtime, a **second** silent failure surfaced
that the row does not name: the runtime truncates an **oversized prompt** and reports
nothing.

| Prompt sent | `num_ctx` | Tokens evaluated | `done_reason` | Value returned |
|---|--:|--:|---|---|
| ~2,429 tokens | 256 | **130** | `stop` | **yes** |
| ~2,429 tokens | 512 | 258 | `stop` | **yes** |
| ~2,429 tokens | 1024 | 514 | `length` | no |

At `num_ctx: 256` most of the question was discarded, the runtime said `stop`, and the
model answered confidently. At `1024` the same prompt reports `length` — so **whether
the cut surfaces at all depends on the window**, which is what makes it silent.

The adapter **cannot decide this without a tokenizer**, and a characters-per-token
constant would be this kernel choosing a threshold — which `prd.md` FR-15 forbids. It
therefore records **both** sides:

```python
r.evidence.measurements['prompt_characters']   # 6400.0  what was sent
r.evidence.measurements['prompt_tokens']       # 130.0   what was read
```

A caller comparing the two can see they disagree. The adapter does not smooth the
difference into a confidence it does not have.

---

## 3. `vision` — the same, about images

```python
engine.capabilities('qwen2.5vl:3b').value.observed['supports_vision']   # True
```

```python
r = engine.vision('qwen2.5vl:3b', '¿Qué dice este comprobante?', [image], schema)
```

`capabilities` reports `supports_vision` from the model's declared capabilities
(`qwen2.5vl:3b` declares `['completion', 'vision']`), so a caller can check before
sending images rather than discovering it from a bad answer.

---

## 4. `warm` — load the model, not to answer

```python
engine.warm('smollm2:latest')
```

```python
{'model': 'smollm2:latest',
 'model_revision': 'cef4a1e09247f018ca0c482ad4c2ce1474aba5e87f245dacf97f07948d05d8b4',
 'adapter_revision': 'ollama 0.31.1',
 'warm': True}
# measurements: {'warm_latency_ms': 69.592}
```

`warm` sends the **same options a real call will send** — and that matters more than
it looks. Warming with a different window loads the model only to have the first real
call reload it under the right one, which is exactly the cold start warming exists to
avoid. The only difference is `num_predict: 1`, because the question is *is it
resident*, not *what does it say*.

---

## 5. `judge` — and the self-grading refusal

```python
r = engine.judge('smollm2:latest', rubric, samples, produced_by='smollm2')
r.reason.code    # 'role_conflict'
```

A model grading samples **it produced** measures its own habits rather than the
answer's correctness, so the call is refused. The comparison ignores the tag:
`smollm2` grading `smollm2:latest` is still self-grading, and a guard that compared
raw strings would be defeated by a tag — the same mistake as treating a tag as an
identity.

The prohibition is `kernel-cli.md` §11 row 15, whose assertion belongs to the frontier
adapter (`E04-06`). The guard is implemented on **both** paths because the call can be
made on both.

---

## Reading a result

```python
if r.value is None:
    print(r.reason.code, r.reason.message)      # a fact, and a remedy
else:
    print(dict(r.value))
```

Three layers of `evidence`, consumed differently:

| Layer | Holds | For |
|---|---|---|
| `terms` | `model`, `model_revision`, `adapter_revision` | the cache key |
| `measurements` | `prompt_tokens`, `prompt_characters`, `completion_tokens`, `total_duration_ms` | comparison against your own policy |
| `observed` | `done_reason`, `raw_completion`, `num_ctx`, `params`, `revision_changed`, `supports_vision`… | everything else that is a fact about this call |

### A sampled kernel's value is not assertable — its evidence is

K5's determinism class is **`sampled`** (`kernel-cli.md` §7). Two identical calls may
return different text, so a test may not assert the value. What it *can* assert is the
evidence: the digest, `num_ctx`, the sampling parameters and the adapter revision.
That is why those four are recorded on every call — not decoration, but the entire
assertion surface of the class.

Two consequences, both deliberate:

- **There is no retry-until-agreement.** The attempt count is recorded (`attempts: 1`)
  so the pattern is visible rather than forbidden by hope.
- **There is no aggregate confidence score.** A single number over a sampled kernel's
  output is a decision wearing a number's clothes (`prd.md`).

---

## There is no model setting

The **address** is configurable; a **model** never is. That asymmetry is the whole
design:

| Setting | Read from | Why |
|---|---|---|
| `DOCFLOW_OLLAMA_HOST` | environment | the runtime's address is an operational setting |
| `DOCFLOW_OLLAMA_TEMPERATURE`, `TOP_P`, `TOP_K`, `SEED`, `NUM_PREDICT`, `NUM_CTX` | environment | sampling parameters, forwarded verbatim |

There is **no** default model, **no** fallback model, and **no** environment variable
that substitutes one. A wrong address fails loudly and immediately; a substituted
model would not. This is `kernel-cli.md` §8, and it is asserted by test rather than
merely stated in a docstring.

A malformed sampling value is ignored rather than fatal — a typo in an optional
tuning value should not make the runtime unusable. That is safe precisely because a
sampling parameter is not a model, an engine or a threshold.

---

## What K5 does *not* do yet

- **No `ps`, no `pull`, no `generate` as commands.** `# TODO: [MVP]` — all three stay
  `MVP` and exit `4`. The `pull` in row 13's recipe is performed by *the operator*,
  never by this code: a kernel that pulls models would be changing the very identity
  it exists to observe.
- **No token counting** on the local path and no batch API. `# TODO: [MVP]`.
- **No OCR correction pass** and no post-processing of tokens. `# TODO: [MVP]`.
- **No retry until two answers agree**, and no default model — **never**.
- **No GPU slot policy.** `gpu = 1` is `E05-04`'s declared simplification; how many
  slots exist is an open decision (`plan-01-kernels.md` §12 #7).
- **No determinism-class consequence.** `E05-03` decides what `sampled` means on
  resume; this adapter reports the class and the evidence.

---

## The other seven kernels

| Kernel | Command | State |
|---|---|---|
| K2 `pdf` | `pdf probe` / `classify` / `render` / `split` | landed |
| K3 `image` | `image info` / `legibility` / `crop` / `rescale` | landed |
| K4 `kernel.ocr` | `ocr read` | landed (Docling) |
| K5 `kernel.llm.local` | this page | landed (Ollama) |
| K6 `kernel.llm.frontier` | `llm.frontier …` | `E04-06` |
| K7 `store` | — | landed |
| K8 `registry` | — | landed |
| K1 `orchestrator` | **Landed** — the closing flow |

Seven of eight are available to `docflow-kernel --list` today: every kernel but
K6, which needs a provider key. (There is no `inventory` subcommand — `--list` is
the flag.)
