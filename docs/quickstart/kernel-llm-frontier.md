# Quickstart — what K6 (`kernel.llm.frontier`) can do today

**Status: honest, and partial.** Every kernel has landed, and this page
covers the hosted-generation one. Everything below has been run, and where a number
is quoted it came from a real invocation.

`docflow-kernel` now dispatches this kernel's operations — see `lab-cli.md` for the
bench. This page drives the **library**, called from Python, which is where the
detail lives. That is
the intended shape: `sad.md` ADR-008 makes the library first and the CLI one caller
of it.

**This page made live calls, and they changed it.** An earlier version said *no
frontier call is made on this page* because the workspace had no credential. It has
one now and the calls above were run — three facts below exist only because of that.

---

## Setup

```bash
pip install -e ".[dev]"      # pytest, ruff, pylint
pip install httpx            # the transport
export DOCFLOW_FRONTIER_MAX_TOKENS=16384
export DOCFLOW_FRONTIER_DEEPSEEK_KEY=…   # or ANTHROPIC_KEY / OPENAI_KEY, or the shared KEY
```

Settings come from the environment, and none of them is a model:

| Setting | Why it is a setting |
|---|---|
| `DOCFLOW_FRONTIER_<PROVIDER>_KEY` | a credential — and it is never a parameter, so no call can take one from a command line or a descriptor |
| `DOCFLOW_FRONTIER_KEY` | the **shared** credential, consulted when the provider's own is absent. One name covers the ordinary single-provider setup; the per-provider names exist so two frontier keys can be held at once, which `judge` needs — the grader must not be the producer |
| `DOCFLOW_FRONTIER_MAX_TOKENS` | how much answer the caller is buying — a policy value this kernel refuses to default |
| `DOCFLOW_FRONTIER_<PROVIDER>_HOST` | the provider's address; each provider has a correct default |
| `DOCFLOW_FRONTIER_TEMPERATURE`, `TOP_P`, `TOP_K`, `SEED`, `NUM_PREDICT` | sampling parameters, forwarded verbatim |

Precedence is `provider-specific → shared → no key`. `DOCFLOW_FRONTIER_MAX_TOKENS`
has **no default on purpose**: a default would be this kernel deciding how much answer
to buy, which is a threshold, and thresholds belong to the caller (`prd.md` FR-15).

**Size the ceiling for the provider's reasoning, not for the answer.** Measured:
`deepseek-v4-pro` spent **7 743 completion tokens** emitting a two-field object from
one invoice page, because it reasons before it answers. A ceiling of 2 048 truncates
that call — reported as `truncated_output`, never parsed — and 8 192 is marginal.

## The providers, and what each one actually does

The model name carries its provider: `<provider>:<model>`, with a colon. Adding a
provider is one entry in `frontier_providers.PROVIDERS`.

| Provider | Dialect | Vision | Can pin the tool choice |
|---|---|---|---|
| `anthropic` | Anthropic Messages | yes | yes |
| `deepseek` | Anthropic Messages, at `/anthropic` | **no** | **no** |
| `openai` | OpenAI chat-completions | yes | yes |

Three of those cells are **measured** rather than read off a vendor's page, and each
one is a trap:

**DeepSeek speaks the Anthropic dialect, but only at `/anthropic`.** Its own API root
serves the OpenAI dialect; `api.deepseek.com/v1/messages` is a **404** while
`api.deepseek.com/anthropic/v1/messages` answers 200 with a Messages-shaped body. The
suffix in its default host is load-bearing, not decoration.

**A pinned tool choice is refused by DeepSeek — on both endpoints it exposes.**
`{"type": "tool", …}`, `{"type": "function", …}` and `"required"` all return **HTTP
400**: *"Thinking mode does not support this tool_choice"*. `{"type": "any"}`,
`"auto"` and omitting the field all answer 200 with a correct `tool_use`. So a provider
declares `pins_tool_choice`, the dialect sends the **weakest** form the provider
accepts, and `observed["pins_tool_choice"]` records what was actually sent —
*enforced* and *requested* are different facts, and only one of them is a guarantee.

**DeepSeek cannot see images, and it does not say so.** Handed the invoice fixture it
answered `"NO IMAGE"` as a **value**, with `stop_reason: end_turn` — no error, no
refusal, and nothing downstream able to tell it from a real reading. That is exactly
the failure this project exists to catch, so the adapter refuses **before the call**:

```python
engine.vision("deepseek:deepseek-v4-pro", "Read the total.", [invoice], schema)
# reason.code: unsupported_format
# "'deepseek' cannot be asked about images. Sending one would not fail: …"
```

## Where K6's code lives

K6 is a **kernel** — its own row in `sad.md` §3, determinism class `external`, a cost
it incurs per call. Its code sits in three files rather than in `kernels/`:

| File | What it holds | Landed by |
|---|---|---|
| `docflow/ports/llm.py` | the `LlmEngine` interface | `E04-01` (`S1-T11`) |
| `docflow/adapters/frontier.py` | the adapter, behind the port | `E04-06` (`S1-T16`) |
| `docflow/adapters/frontier_providers.py` | the provider table and the two wire dialects it delegates to | multi-provider work |

K5 and K6 share the port and not the transport: `ollama.py` speaks `/api/chat`,
`frontier.py` speaks `/v1/messages`. That is the whole reason `ADR-004` keeps them as
two kernels — one is `sampled` and free, the other `external` and metered.

## The whole surface

```python
from docflow.adapters.frontier import FrontierEngine

engine = FrontierEngine()        # the address is defaulted; no model ever is
```

| Operation | Answers |
|---|---|
| `capabilities(model)` | Which provider, which model, which adapter revision? |
| `warm(model)` | Is the name valid and the credential present? |
| `structured(model, prompt, schema)` | A JSON answer satisfying a schema |
| `vision(model, prompt, images, schema)` | The same, about images |
| `judge(model, rubric, samples, produced_by, schema)` | Grade samples against a rubric, in the shape the caller declares |

Two properties carry what a `KernelResult` cannot:

| Property | Holds |
|---|---|
| `last_raw_completion` | the last completion's bytes, exactly as they arrived |
| `last_call_record` | a `CallRecord`: provider, revision, tokens, cost, latency, request id |

---

## 1. `capabilities` — which provider, which model?

```python
r = engine.capabilities('anthropic:claude-sonnet-4-6')
r.value.observed
```

```python
{
  'model': 'anthropic:claude-sonnet-4-6',
  'provider': 'anthropic',
  'adapter_revision': 'anthropic 2023-06-01',
  'revision_is_resolved_on_call': True,
  'supports_vision': True,
  'capabilities': ['completion', 'vision'],
}
```

### `revision_is_resolved_on_call: True` — and why that is not a dodge

A **local** model's digest is readable before a call: `ollama` publishes it in
`/api/tags`, so K5 records and compares it (see the K5 quickstart).

A **hosted** model's revision is not readable without asking, and asking would spend a
call the caller did not request. So K6 states plainly that the revision will be
resolved **on the call**, and reports it afterwards — in `last_call_record.model_revision`
and in `evidence.terms['model_revision']`. What it must never do is invent one, and
the `capabilities` answer is shaped so it has nothing to invent: the flag says the
value is not yet known rather than putting a plausible string where a revision goes.

### A name whose prefix is not configured

```python
r = engine.capabilities('openai:gpt-4o')
```

```python
r.value                            # None
r.reason.code                      # 'provider_unknown'
r.evidence.observed['known_providers']   # ['anthropic']
```

### A name with no prefix at all

```python
r = engine.capabilities('claude-sonnet-4-6')
r.reason.code                      # 'model_unknown'
```

Two different codes for two different mistakes, and **neither resolves to a working
model**. That is the criterion this pair exists for: *there is no fallback* is a fact
a test can reach, not an intention in a docstring.

---

## 2. `structured` — the raw bytes come first

This is the invariant the whole adapter is ordered around, and it is one line of
sequencing:

```python
self._last_raw_completion = _raw_bytes(response)   # off the wire, unparsed
parsed_body = response.json()                      # only then
```

### Why the order matters more here than anywhere else

A parse bug and a model that returned nothing produce the **same final state** — no
value. Once the text is gone, the two are indistinguishable, and the run cannot say
which happened. So the bytes are held whole and are reported whether the parse
succeeds, fails, or is never attempted.

```python
engine.last_raw_completion      # b'{"id": "msg_01ABC", ...}' — always, until the next call
```

### Absence, `null` and a value are three outcomes

`kernel-cli.md` §11 row 14 names the collapse — *"the model's absence, `null` and a
default collapsed into one"*. The three are kept apart in **two** independent places,
so an implementation that merged any pair fails on at least one assertion:

| Response | `evidence.observed['outcome']` | `value` | `parse_attempted` |
|---|---|---|---|
| no content blocks | `absent` | `None`, with a `Reason` | `False` |
| a `null` payload | `null` | `{"value": None}`, **no** `Reason` | `False` |
| a real payload | `value` | the parsed mapping | `True` |

The `null` row is the one that gets collapsed in practice. A `null` is *a value the
model gave*; reporting it as an absence throws away the fact that the model answered
at all. And `parse_attempted` exists because *the model said nothing* versus *the
model said something that would not parse* differ, in the old version, only inside a
sentence — and `kernel-cli.md` §5 forbids asserting on prose.

### When the provider answers 200 with a body that is not JSON

A captive portal, an intercepting proxy, a truncated response. The status says success
and the body is not an answer:

```python
r.reason.code                             # 'unsupported_format'
r.evidence.observed['body_is_json']       # False
engine.last_raw_completion                # b'<html>not an answer</html>'
```

**This crashed the adapter before it was guarded** — `response.json()` raised
`ValueError` straight out of the caller's stack. The mutation harness found it, not a
reading of the code. An unhandled exception is the same defect as a silent one wearing
a stack trace: the caller still cannot tell *the provider misbehaved* from *the
document is invalid*.

---

## 3. Rate limits and outages are facts about the provider

```python
r = engine.structured('anthropic:m', 'p', schema)   # → HTTP 429, retry-after: 30
```

```python
r.value                                  # None
r.reason.code                            # 'provider_unavailable'
r.evidence.observed['retry_after']       # '30'  — verbatim
r.evidence.observed['http_status']       # 429
```

### `retry-after` is recorded, never reinterpreted

Reinterpreting it — into a backoff, a default, or seconds-versus-milliseconds — is the
silent failure: the caller then waits a different time than the provider asked for,
and nothing says so. When the header is **absent**, `retry_after` is `None` and no
default is invented, because a default number would be a policy value that *looks* like
something the provider sent.

### An outage is never a rejection

The distinction the issue exists for: *"the provider was down"* collapsing into
*"this field is invalid"*.

| Situation | Code | Reads as |
|---|---|---|
| transport down | `provider_unavailable` | a fact about the provider |
| HTTP 5xx | `provider_unavailable` | a fact about the provider |
| HTTP 429 | `provider_unavailable` | a fact about the provider |
| HTTP 404 | `model_unknown` | a fact about the name |
| valid JSON, wrong shape | `unsupported_format` | a fact about the answer |

**Whether to wait and retry is policy, and policy is not this kernel's.** The adapter
records the imposed delay and returns; the retry decision is the orchestrator's, made
once and visibly (`kernel-cli.md` §7 — *never* retry until two answers agree).

---

## 4. `last_call_record` — always populated

`kernel-cli.md` §7 makes this the assertion surface for an `external` kernel: the
value is not assertable, the record is.

```python
engine.last_call_record
```

```python
CallRecord(
    provider='anthropic',
    model='m',
    model_revision='claude-sonnet-4-6-20260101',   # the provider's, not the name
    prompt_tokens=120, completion_tokens=18, total_tokens=138,
    cost_usd=None,
    latency_ms=…,          # the measured wall-clock, rounded to 3 decimals
    request_id='req_123',
)
```

`latency_ms` is deliberately shown as `…` rather than a number: it is a *measurement*
of the call, so any figure written here would be one this page made up. The other
fields are the shape and come from a real response.

**Populated on failure too.** A rate-limited call still spent latency and still reached
a revision; reporting no record would make *the call failed* indistinguishable from
*no call was made*.

**A field the provider did not report is `None`, never `0`.** `0` would read as *the
provider said zero tokens* — a claim the provider never made.

**`cost_usd` is `None` on every path.** The price is a billing fact this adapter does
not look up; a rate card hardcoded here would be a number that silently goes stale
(`# TODO: [MVP]`).

### `model_revision` is `'unresolved'` when no answer arrived

A 429, an outage and a rejected credential all happen **before** the provider says
which revision answered. So the term says so:

```python
r.evidence.terms['model_revision']    # 'unresolved'
r.evidence.terms['model_name']        # 'm'   — what was asked for
r.evidence.terms['adapter_revision']  # 'anthropic 2023-06-01'
```

Substituting the model's *name* for its revision would be the same class of mistake as
keying a cache on a moving tag: a hosted model is updated under a fixed name. On
success the term is the provider's own revision —
`test_a_resolved_call_reports_the_providers_revision_not_its_name` asserts the
difference.

---

## 5. `judge` — and the self-grading refusal

```python
r = engine.judge('anthropic:m', rubric, samples, produced_by='anthropic:m', schema=grade)
r.reason.code     # 'role_conflict'
```

A model grading samples **it produced** measures its own habits rather than the
answer's correctness. The comparison ignores the provider prefix, so `anthropic:m`
grading `m` is still self-grading — a guard comparing raw strings would be defeated by
a prefix.

Row 15's assertion is `MVP` in Stage 1 (`judge` is not a Stage 1 command), so the row
is **declared and gated**, not dropped. The code path exists so the row has a
`reason.code` to assert on the moment it runs.

---

## The same operations from `docflow-kernel`

**Read this section differently from the other kernels' quickstarts.** K5, K3 and K2
could be measured end to end in this workspace; K6 cannot, because it has **no
provider key** — you can reach every *precondition* refusal here, and none of the
successes. So the blocks below are real invocations and real output, and what they
show is the **gate chain** rather than an answer.

The registered surface and §9 do not fully agree, and that is the headline:

| Operation | Command | §9 | Registered |
|---|---|---|---|
| `capabilities` | `llm.frontier capabilities` | `now` | dispatches |
| `warm` | `llm.frontier warm` | `now` | dispatches |
| `structured` | `llm.frontier structured` | `now` | dispatches |
| `vision` | `llm.frontier vision` | `now` | dispatches |
| `count-tokens` | `llm.frontier count-tokens` | `MVP` | exits `4` |
| `judge` | `llm.frontier judge` | `MVP` | exits `4` |

**`llm.frontier warm` was once a command the spec did not sanction, and the fix is
worth recording.** `warm` appears in §9's **K5** table, and the implementation
registered it for K6 as well, so it dispatched while the document did not list it.
That was a real divergence, and the mechanism that let it through was a **one-way
contract test**: `test_every_now_command_from_section_9_is_registered` asserts
§9 ⊆ registered, which passes happily on a surface carrying *extra* commands. The
reverse direction was not asserted at all.

Two things changed. §9's K6 table now carries the row — the operation is legitimate
and is the only way to confirm a provider credential before a batch, since
`capabilities` describes the adapter's *configuration* and therefore answers without
one. And `test_every_registered_command_appears_in_section_9` closes the direction
that was open, so the next command to arrive unsanctioned fails the suite instead of
drifting in silently.

### Provider and model naming is `<provider>:<model>`

```console
$ docflow-kernel llm.frontier capabilities --model anthropic/claude-sonnet-4-6
# value: null
# reason.code: "model_unknown"
# reason.message: "the model name 'anthropic/claude-sonnet-4-6' carries no provider
#   prefix. A frontier model is named `<provider>:<model>`, e.g.
#   anthropic:claude-sonnet-4-6; no default provider is substituted."
# exit 3
```

The separator is a **colon**, and a slash is refused rather than guessed at. An
unknown prefix is refused with the configured set quoted back:

```console
$ docflow-kernel llm.frontier capabilities --model nope:gpt
# reason.code: "provider_unknown"
# reason.message: "the provider prefix 'nope' names no configured provider. This
#   build speaks to 'anthropic'; no fallback ..."
# exit 3
```

That second message is worth reading as a design statement: the build speaks to
**one** provider, and the refusal says so instead of silently trying another.

### `llm.frontier capabilities` — a success that needs no credential

```console
$ docflow-kernel llm.frontier capabilities --model anthropic:claude-sonnet-4-6
# value.terms: { "provider": "anthropic", "model": "claude-sonnet-4-6",
#                "adapter_revision": "anthropic 2023-06-01",
#                "model_revision": "claude-sonnet-4-6" }
# value.observed: { "model": "anthropic:claude-sonnet-4-6", "provider": "anthropic",
#                   "adapter_revision": "anthropic 2023-06-01",
#                   "revision_is_resolved_on_call": true,
#                   "supports_vision": true,
#                   "capabilities": ["completion", "vision"] }
# exit 0
```

Exit `0` **with no provider key set** — an answer this command can give because it
describes the *adapter's* configuration rather than the provider's state. `terms`
carries a `model_revision`, and it is the model **name**, not a digest: see
`revision_is_resolved_on_call` in §1 above, which is exactly why this field cannot be
a revealed revision yet.

**This is why `docflow-kernel --list` reporting K6 `available: false` needs reading
carefully.** `available` answers *"could a paid call be made"*, and the honest answer
is no. It does not mean *"every K6 command fails"* — `capabilities` succeeds, and it
is the probe in §"There is no key in this workspace" that is unavailable, not the
whole kernel.

### `llm.frontier structured` — the gate chain, in order

With no environment prepared, the first refusal is not about credentials at all:

```console
$ docflow-kernel llm.frontier structured --model anthropic:claude-sonnet-4-6 \
    --prompt-file /tmp/p.txt --schema-file /tmp/s.json
# value: null
# reason.code: "provider_unavailable"
# reason.message: "DOCFLOW_FRONTIER_MAX_TOKENS is not set. The response ceiling is a
#   policy decision, and this kernel does not supply one: a default here would ..."
# exit 3
```

The response ceiling is **policy**, so it is an environment value rather than a flag
or a constant. Set it, and the next gate appears:

```console
$ DOCFLOW_FRONTIER_MAX_TOKENS=1024 docflow-kernel llm.frontier structured ...
# reason.code: "provider_unavailable"
# reason.message: "no provider key is configured. Set DOCFLOW_FRONTIER_KEY in the
#   environment; it is deliberately not a parameter, so it cannot arrive on a
#   command line or in a ..."
# exit 3
```

Both refusals are exit **3** — the call could not legitimately be made — and each
names its own remedy, so the chain is walkable without reading the source. The
environment variables this build reads are `DOCFLOW_FRONTIER_KEY`,
`DOCFLOW_FRONTIER_HOST` (the address is defaulted to `https://api.anthropic.com`; the
*model* never is) and `DOCFLOW_FRONTIER_MAX_TOKENS`.

One consequence worth stating: **`call_record` is `null` on these refusals.** The
documentation promises it is *"always populated"* for K6, and that is true of a **call
that happened** — a refusal reached before the request leaves reports no provider
response, because there was none to report. `null` here is the honest value, not a
missing field.

### What `--save` does here, and why it does not today

§9's K6 prose says *"the raw completion is persisted before anything coerces it"*, and
that is the promise `last_raw_completion` exists to keep. It is not reachable from this
surface today:

```console
$ docflow-kernel llm.frontier capabilities --model anthropic:claude-sonnet-4-6 --save /tmp/fs
--save applies to a command that returns bytes; this one returned Evidence
# exit 4
```

`--save` is **not a declared flag on any K6 command** — not on `structured`, not on
`vision` — so the dispatcher answers its generic refusal before the provider is ever
reached. Given no credential, a call would refuse at the gate chain above anyway, so
this is invisible in this workspace rather than a second failure layered on the first.
It is recorded here because a reader of §9 would otherwise expect a persisted raw
completion that no command can currently produce.

### The exit codes, in one table

| Exit | Meaning | Where K6 produces it |
|---|---|---|
| `0` | A value was produced | `capabilities` — and nothing else, without a key |
| `2` | The document's answer | the provider answered: a rate limit, an outage, a 200 whose body is not JSON (§3) |
| `3` | The call could not legitimately be made | `model_unknown`, `provider_unknown`, `provider_unavailable` (ceiling, key), `role_conflict`; and a missing `--model`, as a typed `asset_missing` refusal |
| `4` | Usage: bad flag, `MVP` | `count-tokens`, `judge`; `--save` on any K6 command |

A missing `--model` is exit `3` and not `4`: the flag is legal and the command is
spelled correctly, so what failed is the *precondition*. The refusal carries a typed
`Reason` and an envelope, so a caller can branch on the code:

```console
$ docflow-kernel llm.frontier capabilities
# reason.code: "asset_missing"
# evidence.observed.blocked_by: "missing_parameter"
# exit 3
```

**This was a real defect.** The handler raised a `ValueError`, so the dispatcher's
catch-all reported exit `1` with a traceback — reporting a caller's omission as a
broken build, which is the collapse the exit table exists to prevent.

### Running all six at once

`scripts/kernel/kernel-llm.sh` drives **both model kernels** — this one and K5 — since
they share two of their four operations. `-v` (or `--verbose`) prints the command
behind every line; all eight drivers share the flag (`lab-cli.md`):

```console
$ scripts/kernel/kernel-llm.sh

  local model      deepseek-r1:7b  (default)
  vision model     qwen2.5vl:3b  (default)
  frontier model   anthropic:claude-sonnet-4-6  (default)
  image            tests/fixtures/matrix/page.png

K6 llm.frontier - 'now' commands (needs a provider key; external)
  capabilities               exit 0  observed: adapter_revision, provider, ...
  warm                       exit 3  reason provider_unavailable
  structured                 exit 3  reason provider_unavailable
  vision                     exit 3  reason provider_unavailable

K6 llm.frontier - the naming and credential refusals
  capabilities(slash)        exit 3  reason model_unknown
  capabilities(no provider)  exit 3  reason provider_unknown
```

**The refusals are the point of that output, and this is the workspace to see them
in.** `capabilities` answers with no credential because it describes the adapter's own
configuration; everything past it refuses *before* making a call, each exit `3` naming
its own remedy — the gate chain §4 documents. The model is a parameter
(`--frontier-model`) and defaults to a `<provider>:<model>` pair with the **colon** the
naming convention requires, so the `model_unknown` and `provider_unknown` refusals
below it show what the wrong spelling answers.

**K6 is `external`** (`kernel-cli.md` §7), so there is no value to compare between runs
even with a key: what is stable is the `call_record` and the typed failure paths, and
that is what a test may assert on.

---

## Secrets

No operation takes a credential:

```python
inspect.signature(FrontierEngine.structured)   # (model, prompt, schema) — no key
```

Nothing in `capabilities`, `warm`, `structured`, `vision` or `judge` accepts a key,
token, secret, credential or password, and `test_no_operation_takes_a_credential`
asserts that at the adapter level. The key is read from the environment at the moment
of the call, so **no call path can take one from a command line or a descriptor** —
which is what makes *"no `--api-key` flag"* a property of the design rather than a
promise about a flag parser. The parser exists now (`docflow-kernel`, `E07-01`), and
it refuses `--api-key` as a **forbidden** flag rather than merely an unknown one — so
the refusal is asserted against a surface that runs, not against one that does not.

---

## There is no key in this workspace, and that is fine

```python
engine.warm('anthropic:claude-sonnet-4-6')
```

```python
r.value            # None
r.reason.code      # 'provider_unavailable'
```

This is the same code an outage produces, deliberately: *the call could not
legitimately be made* is one outcome, and its remedy is in the message. It is also why
`docflow-kernel --list` reports K6 as **unavailable** in this workspace even though its
adapter has landed — the probe checks the module *and* the credential, and reporting a
provider as callable when it cannot be would be the most expensive silent fallback on
the surface.

---

## What K6 does *not* do yet

- **No second provider.** `# TODO: [MVP]` — one provider adapter in Stage 1.
- **No batch API and no `count_tokens`.** `# TODO: [MVP]` — `llm.frontier count-tokens`
  stays `MVP` and exits `4`.
- **No cost accounting.** `cost_usd` is `None`; the rate card is not read here.
  `# TODO: [MVP]`.
- **No retry, no circuit breaker, no escalation policy.** *Sustained unavailability
  degrades to `unverified`* is this adapter's typed outcome; the ladder that consumes
  it is `S2-T09`'s, Plan 2.
- **No `--api-key` flag**, no key in a descriptor, no key on a command line. **Never.**
- **No fallback provider or default model.** **Never** (`kernel-cli.md` §8).
- **No value assertions.** K6 is `external`: a test asserts `call_record` and the typed
  failure paths, never the value (`kernel-cli.md` §7).

---

## The other seven kernels

| Kernel | Command | State |
|---|---|---|
| K2 `pdf` | `pdf probe` / `classify` / `render` / `split` | landed |
| K3 `image` | `image info` / `legibility` / `crop` / `rescale` | landed |
| K4 `kernel.ocr` | `ocr read` | landed (Docling) |
| K5 `kernel.llm.local` | `llm.local …` | landed (Ollama) |
| K6 `kernel.llm.frontier` | this page | landed (one provider) |
| K7 `store` | `store put` / `get` / `verify` / `ls` | landed |
| K8 `registry` | `registry validate` / `show` / `ls` | landed |
| K1 `orchestrator` | **Landed** — the closing flow |

Seven of the eight are `available` to `docflow-kernel --list`; **this kernel is the
exception**, and the `detail` field says why (`no provider key in the environment`).
That distinction is one `inventory()`'s docstring states outright — *"this is the
kernel level, and deliberately not the command level"* — and it applies here:
`available: false` is a statement about the **adapter**, not about every command.
`llm.frontier capabilities` answers without a credential; only the operations that
would actually *call* the provider are blocked.
