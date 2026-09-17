# Quickstart — what K6 (`kernel.llm.frontier`) can do today

**Status: honest, and partial.** Six of the eight kernels have landed; this page
covers the hosted-generation one. Everything below has been run, and where a number
is quoted it came from a real invocation.

There is **no command line for kernels yet** (`S1-T20`/`S1-T21` build
`docflow-kernel`). Everything here is the **library**, called from Python. That is
the intended shape: `sad.md` ADR-008 makes the library first and the CLI one caller
of it.

**No frontier call is made on this page.** No provider key exists in this workspace,
and the adapter is designed so that is a *typed outcome* rather than an obstacle —
see the last section. The outputs below are the ones a stubbed transport produces,
which is also how row 14 of the silent-failure matrix is satisfied without a fixture.

---

## Setup

```bash
pip install -e ".[dev]"      # pytest, ruff, pylint
pip install httpx            # the transport
export DOCFLOW_FRONTIER_KEY=…        # from the provider's console
export DOCFLOW_FRONTIER_MAX_TOKENS=4096
```

Two settings, both from the environment, and neither is a model:

| Setting | Why it is a setting |
|---|---|
| `DOCFLOW_FRONTIER_KEY` | a credential — and it is never a parameter, so no call can take one from a command line or a descriptor |
| `DOCFLOW_FRONTIER_MAX_TOKENS` | how much answer the caller is buying — a policy value this kernel refuses to default |
| `DOCFLOW_FRONTIER_HOST` | the provider's address; defaults to `https://api.anthropic.com` |
| `DOCFLOW_FRONTIER_TEMPERATURE`, `TOP_P`, `TOP_K` | sampling parameters, forwarded verbatim |

`DOCFLOW_FRONTIER_MAX_TOKENS` has **no default on purpose**. A default would be this
kernel deciding how much answer to buy, which is a threshold — and thresholds belong
to the caller (`prd.md` FR-15). Leaving it unset is reported, not guessed.

## Where K6's code lives

K6 is a **kernel** — its own row in `sad.md` §3, determinism class `external`, a cost
it incurs per call. Its code sits in two files rather than in `kernels/`:

| File | What it holds | Landed by |
|---|---|---|
| `docflow/ports/llm.py` | the `LlmEngine` interface | `E04-01` (`S1-T11`) |
| `docflow/adapters/frontier.py` | the provider adapter, behind the port | `E04-06` (`S1-T16`) |

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
| `judge(model, rubric, samples, produced_by)` | Grade samples against a rubric |

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
r = engine.judge('anthropic:m', rubric, samples, produced_by='anthropic:m')
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
promise about a flag parser that does not exist yet.

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
| K7 `store` | — | landed |
| K8 `registry` | — | landed |
| K1 `orchestrator` | — | `E05-01` |

Six of eight kernels can serve a call in this workspace; K6 is the seventh, and needs a
credential to be callable rather than an adapter to be written.
