# Plan — add a `deepseek` provider kind to `subplan-procesador-llm-call.md`

> Status: **applied** (2026-10-06). Landed as `LLM-16`…`LLM-19` in
> `docs/plan/issues/wbs-procesador-llm-call.md` §14, with one correction the implementation forced —
> §12 records it.
>
> What reopens: `subplan-procesador-llm-call.md` §3 (provider encapsulation and the option
> classes), §4 (WBS) and §9 (resolved decisions) gain rows; the two registries' READMEs gain
> the invocation. The bench — `scripts/tools/_llm.py`, `scripts/tools/llm.py`,
> `scripts/tools/batch_llm.py` — changes **nothing**: the tools already carry any provider
> through `process_llm_request`, and the point of this plan is to keep it that way.
>
> What drove it: the frontier probe `scripts/tmpref/frontier_prompt.py` reaches DeepSeek by
> driving `docflow.llm.primitives` directly, with the schema **inlined into the prompt** and
> `response_format={"type": "json_object"}`. The bench reaches the same provider through the
> processor, which sends `response_format={"type": "json_schema", "strict": true}`. §1 records
> the baseline gap; §3 gives the edit each gap needs.
>
> Landing it edits frozen artifacts. This plan changes plan text —
> `docs/plan/subplan-procesador-llm-call.md` and `docs/plan/issues/wbs-procesador-llm-call.md` —
> which is the plan owner's call, not a code task's. The code the revision records lands as new
> WBS rows (§4).
>
> Scope: `src/docflow/llm/primitives/__init__.py`, `src/docflow/llm/primitives/composition.py`,
> `src/docflow/llm/entrypoints.py`, `registry/llm-local/README.md`,
> `registry/llm-frontier/README.md`, and the two plan artifacts. Out of scope:
> `scripts/tools/**` (no edit), `docs/idea/` (read-only), every other processor.

## 0. Rules that constrain this revision

- **The tools stay provider-agnostic.** No provider name, endpoint or wire field may appear
  under `scripts/tools/**`. Every edit below is in `src/docflow/llm`, so `llm.py` and
  `batch_llm.py` inherit DeepSeek with zero lines changed. A tool that special-cased
  `deepseek` would be the frontier violation `docs/plan/README.md` §4.1 forbids.
- **No ID changes.** `LLM-01`…`LLM-15` are neither re-scoped nor renumbered; this pass
  **appends** `LLM-16`…`LLM-19`, so the range citations in `wbs-general.md` §1/§4 stay valid.
- **The `request_key` formula is not changed.** The inlined schema enters it through the
  existing `rendered_prompt` term — no new term, no new exclusion (§3.3). The formula's four
  lines in subplan §3 are cited, not rewritten.
- **A provider's wire capability is a statement, not a guess.** `deepseek` speaks
  `json_object`; `openai` and `vllm` keep `json_schema`. Where the repository cannot verify a
  capability it says so in §7 rather than assuming it in §3.
- **One decision this pass must not move.** Which of the three generators a call resolves to
  is `resolve_generator`'s (`composition.py`), and it already states that a schema outranks
  images. This pass does not touch that resolution; `generate_structured` stays the generator a
  DeepSeek call with a schema resolves to.
- **Gates after every phase**, as the plan requires: `pytest`, `ruff check .`,
  `ruff format --check .`, `pylint src tests`. For the docs phases the gates are a regression
  check rather than a lint of the new prose.
- **Every phase ends with a grep, not a look** — the half-updated-range habit
  `plan-update-test-tiers.md` §0 records.

## 1. The baseline (what the three tools do today)

| # | Measured | Where |
|---|---|---|
| E1 | A **text** call to DeepSeek works *today* with `--provider openai_compatible`/`openai` + `base_url` + `api_key`; the tools never inspect the provider. `--provider`, `--model` flow into `LLMInput`. | `_llm._request` (`_llm.py:543`), `_llm.COMMANDS` (`_llm.py:966`) |
| E2 | The endpoint and the credential reach the transport only through `--option base_url=…` / `--option api_key=…`, `DOCFLOW_LLM_BASE_URL`, `DOCFLOW_LLM_API_KEY`, or `.env`. There is **no `--base-url` flag**. | `ENVIRONMENT_OPTIONS` (`_llm.py:129`), `_options` (`_llm.py:415`) |
| E3 | `--schema` becomes `response_format={"type":"json_schema","strict":true,"schema":…}` for the whole OpenAI-compatible class, which is `openai`, `vllm` **and** every hosted endpoint. | `OpenAICompatibleProvider._generate` (`primitives/__init__.py:996`) |
| E4 | There is **no provider name `deepseek`**: a call must spell the transport, not the product. | `PROVIDER_KINDS` (`primitives/__init__.py:156`) |
| E5 | The endpoint default is one constant for the whole class, so a hosted call without `base_url` is sent to `http://localhost:8000/v1`. | `OPENAI_COMPATIBLE_BASE_URL` (`primitives/__init__.py:166`) |
| E6 | `think`, `keep_alive`, `num_ctx` are lifted out of the body for Ollama alone; for the OpenAI-compatible class **every option is spread verbatim**, so an Ollama-only option reaches a hosted endpoint as an undefined field. | `_OLLAMA_REQUEST_FIELDS` (`primitives/__init__.py:191`), `_generate` (`primitives/__init__.py:978`) |
| E7 | The probe's DeepSeek path inlines the schema and asks for `json_object`; the two mechanisms the bench uses instead are the prompt `<schema>` placeholder (absent from the registry templates) and the provider-native `json_schema`. | `frontier_prompt._inline_schema` (`frontier_prompt.py:369`), `SCHEMA_PLACEHOLDER` (`composition.py:95`), `load_template`/`load_schema` |

## 2. Verdict per gap

| Gap | Verdict | Edit |
|---|---|---|
| E4, E5 | **Add a first-class kind.** `deepseek` is the same wire as `openai`/`vllm`, so it is a `PROVIDER_KINDS` row plus a default endpoint — exactly the shape `openai` already has. | §3.1 |
| E3 | **Make the structured field a per-dialect capability.** DeepSeek wants `json_object`; the translation already exists in the probe. | §3.2 |
| E7 | **Inline the schema for the `json_object` dialect**, in the processor, so no template changes and `openai`/`ollama` stay byte-for-byte. | §3.3 |
| E6 | **Keep Ollama-only options out of the hosted body.** | §3.4 |
| E1, E2 | **No change.** The tools already do this; §3.5 documents the invocation only. | §3.5 |

## 3. The revision, section by section

### 3.1 `primitives/__init__.py` — the provider name and its endpoint

```python
PROVIDER_KINDS: Final[dict[str, str]] = {
    "ollama": "ollama",
    "openai_compatible": "openai_compatible",
    "openai": "openai_compatible",
    "vllm": "openai_compatible",
    "deepseek": "openai_compatible",   # NEW
}

DEEPSEEK_BASE_URL: Final[str] = "https://api.deepseek.com"   # NEW
```

and `OpenAICompatibleProvider._base_url` picks the default by `subject.provider`:
`"deepseek"` → `DEEPSEEK_BASE_URL`, otherwise `OPENAI_COMPATIBLE_BASE_URL`. A `base_url`
stated by the request still wins, unchanged.

*Effect:* `--provider deepseek --model deepseek-flash` resolves with no `--option base_url`;
`--provider openai_compatible` keeps working; the existing
`test_a_provider_this_seam_does_not_reach_is_refused_by_name` (`test_engine_seam.py:93`) stays
green because an unknown name is still refused.

### 3.2 `primitives/composition.py` + `primitives/__init__.py` — structured mode per dialect

Define the capability where `composition` can read it without a cycle
(`structured_mode` is re-exported from `primitives` alongside `resolve_generator`):

```python
STRUCTURED_MODES: Final[dict[str, str]] = {"deepseek": "json_object"}

def structured_mode(provider: str) -> str:
    """Return how the provider is asked for a structure: json_schema, or json_object."""
    return STRUCTURED_MODES.get(provider, "json_schema")
```

`OpenAICompatibleProvider._generate` branches on it: a `json_object` dialect receives
`body["response_format"] = {"type": "json_object"}`; every other kind keeps the current
`json_schema`/`strict` body verbatim. The existing
`test_an_openai_compatible_call_posts_a_constrained_response_format` (`test_engine_seam.py:174`)
is the regression guard for the unchanged half.

### 3.3 `primitives/composition.py` — the schema travels in the prompt for `json_object`

`process_prompt` (`composition.py:635`) inlines the schema block **after `process_template`
and before it measures**, so the measured and truncated text is the text that is sent:

```python
rendered = process_template(...)
if schema is not None and structured_mode(request.provider) == "json_object":
    rendered = inline_schema_block(rendered, schema)
```

`inline_schema_block` mirrors the probe: a canonical block placed above the template's closing
instruction (the registry's own `Answer with the JSON object only.`), so the last thing read is
still the instruction. `canonical_json` makes it byte-stable.

- **`request_key`.** The block changes `RenderedPrompt.text`, which is the existing
  `rendered_prompt` term of the formula — the key changes when the schema changes, with no new
  term and no new exclusion.
- **Offline validation is retained.** `ProviderCall.schema` still carries the schema, so
  `planned.schema` and `validate_schema` are unchanged; only the *wire* field differs by mode.
- **No prompt placeholder is required.** The registry templates keep no `<schema>`; a template
  that *does* carry one still resolves it as today.

### 3.4 `entrypoints.py` — keep Ollama-only options out of the hosted body

`_provider_options` (`entrypoints.py:136`) drops, for the OpenAI-compatible family, the keys
that are a local dialect's own — `think`, `keep_alive`, `num_ctx`, `min_p`, `repeat_penalty` —
so `DOCFLOW_LLM_THINK`, `DOCFLOW_LLM_MIN_P`, `DOCFLOW_LLM_REPEAT_PENALTY` and
`--option num_ctx=…` can no longer be spread into a DeepSeek body. `temperature`, `top_p`,
`seed`, `max_tokens` and the rest pass through. Ollama keeps the keys it reads.

### 3.5 `subplan-procesador-llm-call.md` — the decision text

- §3 *Provider encapsulation* gains `deepseek` in the provider list and states the structured
  capability (`json_object` inlined; `json_schema` otherwise).
- §3 *The option classes* records that a local dialect's options are filtered out of a hosted
  body.
- §9 gains one resolved decision: **DeepSeek is a provider kind of the OpenAI-compatible
  transport; its structure is asked for as `json_object` with the schema inlined into the
  prompt.**
- §4 gains `LLM-16`…`LLM-19` (§4 below).

### 3.6 The registries — the invocation

- `registry/llm-local/README.md` → *Remote*: the DeepSeek recipe becomes
  `--provider deepseek --model deepseek-flash` (the `--option base_url` line goes away; the
  `--option api_key` line may stay or move to `DOCFLOW_LLM_API_KEY`).
- `registry/llm-frontier/README.md` → *Limits*: state the per-provider structured mode beside
  the existing "structured output is the provider's promise" note
  (`registry/llm-frontier/README.md:175`).
- The stale *"`llm.py` cannot send images"* bullet in `llm-local/README.md` is corrected in the
  same pass: `_llm._images` (`_llm.py:513`) attaches an image input and `--image` adds more.

## 4. WBS rows (`wbs-procesador-llm-call.md`, appended as §13)

| ID | Task | Effort | Depends on |
|---|---|---|---|
| LLM-16 | Provider kind `deepseek`: `PROVIDER_KINDS` row + `DEEPSEEK_BASE_URL` + per-provider default endpoint | S | LLM-09 |
| LLM-17 | Structured mode per dialect: `STRUCTURED_MODES` + `structured_mode()`; `_generate` emits `json_object` for that kind and `json_schema` otherwise | S | LLM-16 |
| LLM-18 | Inline the schema for the `json_object` dialect inside `process_prompt`; it enters `request_key` through `rendered_prompt`; offline `validate_schema` retained | S | LLM-17, LLM-04 |
| LLM-19 | Hosted-body option hygiene: filter the local dialect's options out of the OpenAI-compatible body | S | LLM-09 |

Docs and registry are folded into LLM-16…LLM-19's evidence, so no separate docs row.

## 5. Waves

- **Wave A (`LLM-16`, `LLM-19`)** — independent of each other; both touch only
  `primitives/__init__.py` / `entrypoints.py`.
- **Wave B (`LLM-17`)** — after `LLM-16`.
- **Wave C (`LLM-18`)** — after `LLM-17`; the schema inlining.
- **Wave D (docs + registry)** — after Wave C, when the behaviour is fixed.

## 6. Acceptance criteria and tests

- **A1 — the name resolves.** `transport_for("deepseek")` returns `OpenAICompatibleProvider`,
  and a DeepSeek call that states no `base_url` is sent to `https://api.deepseek.com`.
- **A2 — the structured field is per dialect.** A DeepSeek call with a schema sends
  `response_format == {"type": "json_object"}`; an `openai` call with a schema still sends
  `json_schema`/`strict` (the existing test at `test_engine_seam.py:174` is the guard).
- **A3 — the schema is in the prompt, and it keys the call.** A DeepSeek request's rendered
  prompt contains the canonical schema block, and two requests that differ only in the schema
  produce different `request_key`s.
- **A4 — the local dialect's options stay local.** `think`/`num_ctx` are present in an Ollama
  body and absent from a DeepSeek body.
- **A5 — the tools need no edit.** `llm.py … call --provider deepseek --model deepseek-flash`
  and `batch_llm.py <folder> call … --provider deepseek …` run; `prompt` renders the inlined
  text; `models` reads the inventory.
- **Invariant with a mutation.** A3's test must fail if `structured_mode("deepseek")` is
  changed to return `"json_schema"` — prove it by mutating, observing the failure, restoring
  and re-running green, and report both observations.

## 7. Open questions for the plan owner

| # | Question | Recommendation |
|---|---|---|
| Q1 | Where the schema text is inlined: in the processor for `json_object` dialects, or as a `<schema>` placeholder every registry template must carry? | **Processor (§3.3).** Templates stay data-unchanged and a template cannot silently omit the schema. |
| Q2 | Is `deepseek` first-class, or a documented `openai_compatible` recipe? | **First-class (§3.1).** It is one map row + one constant, and it names the product rather than the wire. |
| Q3 | `models` runs `check_model_available` (exact-string) and `get_model_info` (`GET /models/{id}`). If the endpoint does not serve the per-id path, should `get_model_info` degrade to the list entry? | Decide after a live `models` run against DeepSeek; do not guess in §3. |

## 8. Deliberately not in this pass

- **Anthropic / any other dialect.** `anthropic` stays absent from `PROVIDER_KINDS`; the plan
  adds exactly one row.
- **Streaming.** `_consume_stream` already reads `choices[0].delta` and `reasoning_content`;
  DeepSeek's reasoning stream needs no change.
- **Vision capability.** Whether `deepseek-flash` reads `image_url` parts is the model's
  promise, not the transport's; the wiring already attaches them.
- **Any `scripts/tools/**` edit.** That is the claim of the plan, and it is tested by A5.
- **The context window.** `get_context_window` returns `None` off Ollama by design; a DeepSeek
  run keeps stating `--context-window`, unchanged.

## 9. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| DeepSeek silently accepts `json_object` but answers prose | Invalid output reported as correct | `validate_schema` stays in force offline; the typed violation is recorded, never smoothed over |
| A hosted endpoint the kind claims is not verified live | A false capability shipped | Q3 and A2 are the gate; a live `models`/`prompt` run is evidence before the row is `done` |
| The inlined block drifts from the probe's wording | Two "schema in prompt" spellings | `inline_schema_block` is the single implementation; the probe keeps its own and the two are compared in the evidence |

## 10. Evidence and gates

- Per phase: `pytest`, `ruff check .`, `ruff format --check .`, `pylint src tests`.
- The gate for the tools claim: `git diff --stat` shows **no** file under `scripts/tools/**`.
- The gate for the `openai` regression: `test_engine_seam.py:174` green after every phase.
- A live `llm.py prompt … --provider deepseek` render is the pre-token evidence for A3.

## 11. Rollback

Every row is additive: removing the `"deepseek"` row of `PROVIDER_KINDS` and the
`STRUCTURED_MODES` entry restores the exact prior behaviour (`openai`/`vllm` were never on the
new path). No template, no tool and no frozen formula changes, so rollback is a revert of the
`src/docflow/llm` diff alone.

## 12. Applied (2026-10-06)

Landed as `LLM-16`…`LLM-19` in `docs/plan/issues/wbs-procesador-llm-call.md` §14. The first landing
changed **no** `scripts/tools/**` line, and the live run forced one follow-up (WBS §14.1) — a
provider-scoped credential fallback in `_llm._options`.

Two corrections the implementation forced:

- **§3.4 is narrower than written.** The plan listed five options to filter (`think`, `keep_alive`,
  `num_ctx`, `min_p`, `repeat_penalty`); the code filters three
  (`LOCAL_ONLY_OPTIONS = {"think", "keep_alive", "num_ctx"}`). `min_p` and `repeat_penalty` are
  deliberately kept: an OpenAI-compatible server (vLLM among them) may accept them as sampling
  parameters, and dropping a stated option would be its own silent stand-in. The subplan §3 option
  table was updated to match.
- **§3.5's "the bench is untouched" was too strong.** The first live call returned `HTTP 401` because
  `.env` held the provider-scoped `DEEPSEEK_API_KEY` and the bench read only the neutral
  `DOCFLOW_LLM_API_KEY`. `primitives.PROVIDER_CREDENTIAL_ENV` (`deepseek` → `DEEPSEEK_API_KEY`) plus a
  fallback in `_llm._options` fixed it; the tool still names no provider, so the bench's
  provider-agnostic shape holds.

**Evidence.** `pytest` green over `tests/llm` and `tests/test_lab_tools.py` (10 + 2 new cases) ·
`ruff check .` · `ruff format --check .` · `pylint src tests`. Two mutations falsified (mutate →
observe red → restore → observe green): `STRUCTURED_MODES = {}` turns `structured_mode("deepseek")`
back to `json_schema` and four tests go red; disabling the credential fallback turns the new
credential test red. A live `call` on `deepseek`/`deepseek-flash` returned `SUCCESS`,
`schema_valid: true` and 5 940 tokens.

**Not claimed.** `deepseek-flash`'s presence in the endpoint's `GET /models` is unverified, and a
per-id `get_model_info` on an endpoint that serves none is the plan's Q3.
