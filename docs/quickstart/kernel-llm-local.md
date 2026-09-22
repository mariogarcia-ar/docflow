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
ollama pull deepseek-r1:8b   # the default local model
```

**`deepseek-r1:8b` is the default.** The model *family* holds the slot for a reason
measured on the **1.5B** tag: on the 1 589-byte `chicos/22f0e9af-…-p1.txt`,
`smollm2:latest` **intermittently runs away** into an unbounded repetition loop (1 in
5 calls with no token ceiling); because a batch driver is sequential and the adapter's
per-call ceiling is 600 s, one runaway stalls a whole run with no output between files.
`deepseek-r1:1.5b` answered **10 of 10** calls on that same file in 4–11 s each. It also
**refuses** an oversized prompt with `HTTP 400 exceed_context_size_error` instead of
dropping it past the window silently — see *The silent cut* below for why that matters.

The tag is **8b** rather than 1.5B, and that too is measured. On
`tests/fixtures-txt/casos/66cd35e9-…txt` the 1.5B model read `fecha_emision` — an
`alta`-severity field with no stronger reader to outvote it — as `"2026"`, and
took `nro_comprobante` from the prompt's own rule-1 example (`"99-9"`); with that
example removed it answered correctly. **8b returns the printed date 3 of 3 runs**
at ~26 s a call, deterministically (666 completion tokens on every run).

What the larger tag does **not** fix is `tipo_comprobante`: this fixture prints
**`A`** in the header, and the model answers `"null"` on 3 of 3 runs. The `A` is
legible in the extracted text, so that is a reading failure rather than an OCR one —
`gemma3:4b` answers `"001"` on the same document and the same prompt.

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
| `judge(model, rubric, samples, produced_by, schema)` | Grade samples against a rubric, in the shape the caller declares |

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
                   #  are ['deepseek-r1:8b', 'granite3.1-moe:1b', ...]; no default
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

**The cut is a property of the model, not of the runtime alone.** Measured on the
`deepseek-r1` family (on its 1.5B tag): it **refuses** an oversized prompt outright, with
`HTTP 400 exceed_context_size_error` —
`request (5004 tokens) exceeds the available context size (4096 tokens)` — naming both
`n_prompt_tokens` and `n_ctx`. The same 15 000-character prompt handed to
`smollm2:latest` came back `done_reason: 'stop'` with a plausible value and
`prompt_eval_count: 2050`. So the silent input cut documented in the table above
belongs to **`smollm2`**; the default now fails loudly, and a caller switching between
the two is switching between a loud refusal and a quiet one.

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
r = engine.judge('smollm2:latest', rubric, samples, produced_by='smollm2', schema=grade)
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

## The same operations from `docflow-kernel`

Four of K5's seven commands are `now`; the other three (`ps`, `pull`, `generate`) are
`MVP` and exit `4`. Unlike K2 and K3 there is no operation here that the CLI cannot
reach at all — every `now` operation has a command:

| Operation | Command | Flags |
|---|---|---|
| `capabilities` | `llm.local capabilities` | `--model` |
| `warm` | `llm.local warm` | `--model` |
| `structured` | `llm.local structured` | `--model`, `--prompt-file`, `--schema-file` |
| `vision` | `llm.local vision` | `--model`, `--prompt-file`, `--image`, `--schema-file` |
| `ps`, `pull`, `generate` | — | `MVP` — exit `4` |

**`--model` is required on every one of them and there is no default**, which is
`kernel-cli.md` §8 taking effect rather than a gap. The three files the `now` commands
take are ordinary files on disk: `--prompt-file` and `--schema-file` for the prompt and
the JSON Schema, `--image` for the picture `vision` reads. All the examples below used
`/tmp/p.txt`, `/tmp/s.json` and a fixture image.

Every block is a real invocation quoted verbatim, trimmed at `...` only where the
envelope repeats `value` inside `evidence`. These calls reach a **live Ollama** and are
`sampled`, so the *text* a model returns will differ between runs; what is stable, and
what these blocks are chosen to show, is the **shape** — the keys, the digest, and the
exit code.

### `llm.local capabilities --model <tag>`

```console
$ docflow-kernel llm.local capabilities --model granite3.1-moe:1b
# value.terms:    { "model": "granite3.1-moe:1b",
#                   "model_revision": "3269ce3e31ea68da5ddb7926628b5bb1d25146d4..." }
# value.observed: { "model": "granite3.1-moe:1b",
#                   "model_revision": "3269ce3e...",
#                   "first_seen_revision": "3269ce3e...",
#                   "revision_changed": false,
#                   "num_ctx": null, "params": {},
#                   "tag_is_moving": true,
#                   "family": "granitemoe", "parameter_size": "1.3B",
#                   "quantization": "Q8_0",
#                   "capabilities": ["completion", "tools"],
#                   "supports_vision": false }
# exit 0
```

Three fields here are the kernel's whole reason for existing, and all three are
visible above:

- **`model_revision` is a digest, not the tag.** `granite3.1-moe:1b` is a moving
  label; the digest is the identity, and it is what goes into the cache key.
- **`first_seen_revision` and `revision_changed`** are the comparison. The second
  reports `false` because this is the first time the workspace has seen this model. An
  operator who runs `ollama pull granite3.1-moe:1b` and re-asks gets `true` — the tag
  now points at different bytes, and a stage marked `done` against the old digest is
  no longer the same work.
- **`tag_is_moving: true`** says the tag is a tag (not a digest), so a caller can see
  *why* the revision is worth recording.

`num_ctx` is the **loaded** window rather than the declared one, and `null` means *not
currently loaded*. It is read from Ollama's `/api/ps`, which reports only loaded
models, and the declared window in the model's metadata is deliberately **not**
substituted for it — a model whose card says 8192 can load under a 4096 window, and
reporting the declared number would report a figure nothing used. So `capabilities`,
which loads nothing, reads `null`; the window becomes visible on the commands that
actually *use* the model, and the `structured` block below reports `num_ctx: 4096`.

**`warm` does not fill this field in**, despite the name suggesting it loads the
model: measured here, `capabilities` *after* a `warm` still reported `num_ctx: null`.
It is a generation that fills it, and the helper is called after the generation on
purpose — a pre-call read would report the *previous* call's window.

### `llm.local warm --model <tag>`

```console
$ docflow-kernel llm.local warm --model granite3.1-moe:1b
# value.observed.warm: true
# value.terms.adapter_revision: "ollama 0.31.1"
# value.measurements: { "warm_latency_ms": 1366.552 }
# exit 0
```

`warm` asks the runtime to load the model **without asking it a question**, so the
first real question later is not paying for the load. `measurements` carries one
number, and it is labelled `warm_latency_ms` rather than being an unqualified
`latency_ms` — conflating a load with a generation would make the two
indistinguishable in a trace.

### `llm.local structured`

```console
$ docflow-kernel llm.local structured --model smollm2:latest \
    --prompt-file /tmp/p.txt --schema-file /tmp/s.json
# value: { "total": "1500" }
# evidence.measurements: { "prompt_tokens": 44.0, "prompt_characters": 34.0,
#                          "completion_tokens": 10.0, "total_duration_ms": 1776.807 }
# evidence.observed:     { "model_revision": "cef4a1e0...",
#                          "adapter_revision": "ollama 0.31.1",
#                          "num_ctx": 4096, "params": {},
#                          "done_reason": "stop",
#                          "raw_completion": "{\"total\": \"1500\"}",
#                          "vision": false, "attempts": 1 }
# exit 0
```

**`value` is the parsed object; `raw_completion` is the text it was parsed from.** Both
are reported, and the second is not a debugging nicety: it is the difference between
*the model said `"1500"`* and *something produced `1500`*. Without it, a parse that
quietly coerced a type would look like a model that answered correctly.

`done_reason: "stop"` is the field to look at when a value is missing. It says the
model finished on its own rather than being cut, which is why this call has `value`
and no `reason`.

**The digest is in `terms`, and the token counts are in `measurements`** — the split
is the boundary's: an identity is a term (it feeds the cache key), a count is a
measurement (it describes the work). `call_record` is `null` on a local model, because
there is no provider request to bill and no `request_id` to record — that field is K6's.

#### Truncation is a refusal, and the message names the cause

```console
$ DOCFLOW_OLLAMA_NUM_PREDICT=8 docflow-kernel llm.local structured \
    --model smollm2:latest --prompt-file /tmp/p.txt --schema-file /tmp/s.json
# value: null
# reason.code: "truncated_output"
# reason.message: "the generation was cut by the context window or the token
#   ceiling (done_reason='length'), so the answer is incomplete. It is reported as
#   truncated rather than parsed: a cut that lands after the last complete field
#   parses cleanly, which is how a partial answer is mistaken for a whole one."
# evidence.observed.done_reason: "length"
# exit 2
```

Exit **2** is the document's answer, not a usage error: the request was well formed,
and what the model produced cannot be used. **The whole point is that a cut answer is
never parsed as if it were complete**, and the message says why that is not
pedantry: *"a cut that lands after the last complete field parses cleanly, which is
how a partial answer is mistaken for a whole one."* `{ "total": "15` would fail to
parse and be noticed; a cut two fields later would parse perfectly and be published
as an answer the model never gave. The evidence still carries `done_reason: "length"`,
so the cause stays visible on the refusal.

`DOCFLOW_OLLAMA_NUM_PREDICT` is the environment knob used to *provoke* this for the
docs; it is not a product setting.

### `llm.local vision`

```console
$ docflow-kernel llm.local vision --model qwen2.5vl:3b \
    --prompt-file /tmp/vp.txt --image tests/fixtures/expected-extraction/dbc07b17-....jpg \
    --schema-file /tmp/vs.json
# value: { "description": "Un recibo de un cliente que muestra detalles como el
#                         número de cuenta, fecha y hora del pago." }
# evidence.observed.vision: true
# evidence.observed.model_revision: "fb90415c...e71a1"
# exit 0
```

The same envelope as `structured`, with one flag changed (`--image` instead of none)
and one field flipped: **`vision: true`**. That field is why the two commands are not
the same command: a multimodal model and a text model take different paths through
the adapter, and a caller reading a trace can see which one produced the answer.

Note the answer itself is in Spanish, because the prompt was — the kernel passes the
prompt through and does not translate it.

### A model that is not there

```console
$ docflow-kernel llm.local capabilities --model no-such-model:latest
# value: null
# reason.code: "model_not_pulled"
# reason.message: "the model 'no-such-model:latest' is not present in this Ollama
#   runtime. Pull it first: `ollama pull no-such-model:latest`. The available
#   models are ['granite3.1-moe:1b', ...]"
# exit 3
```

Exit **3**, and the message carries its own remedy — including the exact `ollama pull`
line to run. This is the difference between *the call could not be made* (`3`) and *the
document answered no* (`2`): nothing was asked of the model, because there was nothing
to ask.

### The exit codes, in one table

| Exit | Meaning | Where K5 produces it |
|---|---|---|
| `0` | A value was produced | all four `now` commands |
| `2` | The document's answer | `truncated_output`; `unsupported_format` |
| `3` | The call could not legitimately be made | `model_not_pulled`; `model_unknown`; `role_conflict`; `engine_unavailable` when Ollama is not running |
| `4` | Usage: bad flag, `MVP` | `llm.local ps`, `pull`, `generate` |

The schema on `--schema-file` is passed to the runtime's `format` field as a schema
**object**, so it constrains generation — and there is deliberately **no check after
the fact**. A model can satisfy a schema structurally and still be useless: asked for
`{"total": string, "cuit": string, "fecha": string}` with
`additionalProperties: false`, `smollm2:latest` answered
`{"total": 1500, "cuit": "", "fecha": ""}` with **exit `0`** — a conforming
shape and an empty answer. That is reported as-is. The adapter's job is not to make a
small model correct; it is to report what the model said and which bytes said it.

And the missing-parameter case, which is a **precondition** rather than a bug. Because
`--model` is genuinely required and has no default, omitting it answers exit `3` with a
typed `Reason` — the call could not legitimately be made:

```console
$ docflow-kernel llm.local capabilities
# reason.code: "asset_missing"
# reason.message: "--model is required: a model has to be named, because ..."
# evidence.observed.blocked_by: "missing_parameter"
# exit 3
```

### Running all seven at once

`scripts/kernel/kernel-llm.sh` drives **both model kernels** — this one and K6 — since
they share two of their four operations. It generates the prompt and the schema it
needs into its output directory rather than committing them: they are the driver's
inputs, not the project's assets. `-v` (or `--verbose`) prints the command behind every
line, as it does for all eight drivers (`lab-cli.md`):

```console
$ scripts/kernel/kernel-llm.sh

  local model      deepseek-r1:8b  (default)
  vision model     qwen2.5vl:3b  (default)
  frontier model   anthropic:claude-sonnet-4-6  (default)
  image            tests/fixtures/matrix/page.png

K5 llm.local - 'now' commands (needs Ollama; sampled)
  capabilities               exit 0  observed: family, model, model_revision, ...
  warm                       exit 0  observed: adapter_revision, model, warm
  structured                 exit 0  observed: attempts, done_reason, model, ...
  vision                     exit 0  observed: attempts, done_reason, model, ...

K5 llm.local - the refusals worth seeing
  capabilities(no model)     exit 3  reason asset_missing
  capabilities(bad tag)      exit 3  reason model_not_pulled
```

**The three models are named with where each came from**, because a model is this
driver's one parameter that changes what every line below it measures — and because
`(default)` and `(--model)` are different claims about the run. All three are
overridable: `--model`, `--frontier-model`, or `KERNEL_LLM_MODEL` /
`KERNEL_LLM_VISION_MODEL` / `KERNEL_FRONTIER_MODEL`.

**The default local model is chosen for a measured defect, not for size.**
`deepseek-r1:1.5b` replaced `smollm2:latest` because `smollm2` intermittently runs
away on a small real document and stalls a sequential driver for the adapter's full
600 s ceiling; `deepseek-r1:1.5b` did not, across 10 consecutive calls, and it refuses
an oversized prompt with `HTTP 400` instead of dropping it in silence. The tag has
since moved to **7b** and then to **8b**, neither of which runs away on the file
above. The reason is
recorded at the declaration in `scripts/kernel/kernel-llm.sh` and in
`llm_local.TEXT_MODEL`, so it is not re-litigated by preference later. The vision
default (`qwen2.5vl:3b`) is unchanged: vision is a different requirement from text
and no defect was measured there.

**K5 is `sampled`** (`kernel-cli.md` §7), so what it reports is what each call
*measured* — the digest, the token counts, the `done_reason` — and never the value,
which is not comparable between runs by definition.

**This was a real defect until recently.** The handler raised a `ValueError`, so the
dispatcher's catch-all reported exit `1` with a traceback — telling a caller *"this
build is broken"* about a flag they simply did not type. `kernel-cli.md` §5 gives the
precondition its own code, and a missing flag is exactly that: the flag is legal and
the command is spelled correctly. The surface now returns a typed refusal instead, the
same reading `store ls` already made for an absent `--root`.

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
| K1 `orchestrator` | `orchestrator …` | **Landed** — the closing flow |
| K2 `pdf` | `pdf probe` / `classify` / `render` / `split` | landed |
| K3 `image` | `image info` / `legibility` / `crop` / `rescale` | landed |
| K4 `kernel.ocr` | `ocr read` | landed (Docling) |
| K6 `kernel.llm.frontier` | `llm.frontier …` | **landed, but unreachable here** — its probe needs a provider key this workspace does not have |
| K7 `store` | `store put` / `get` / `verify` / `ls` | landed |
| K8 `registry` | `registry validate` / `show` / `ls` | landed |

Seven of the eight can serve a call in this workspace — **K6 is the exception**, and
`docflow-kernel --list` reports it `available: false` with the reason. (There is no
`inventory` subcommand — `--list` is the flag.)
