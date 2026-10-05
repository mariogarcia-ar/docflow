# Plan — reopen `subplan-procesador-llm-call.md` for the pixel half

> Status: **proposed.** A revision of a frozen artifact is the plan owner's to land, so this note
> is a work order: it changes no plan text itself.
>
> What reopens it: the probe `scripts/tmpref/image_prompt.py` ran every vision step the registry
> ships against live models, and then took the path the probe itself never took — one vision call
> through `process_llm_request`. §1 records what that measured: five facts the subplan's frozen text
> does not state, and one reading it invites that the code does not take. §2 gives a verdict per
> frozen statement, §3 the edit each verdict needs.
>
> **Documents only.** This plan changes plan text — `docs/plan/subplan-procesador-llm-call.md` and
> `docs/plan/issues/wbs-procesador-llm-call.md`. The code the revision records becomes rows of the
> WBS second pass (§4); nothing under `src/`, `tests/` or `scripts/` is edited here.
>
> Scope: subplan §3, §4, §5, §6, §7, §9, and its WBS §12 → a new §13. Out of scope: `registry/`
> (its README owns the vision assets; §3.5 records the one row the registry owes), the bench
> (`wbs-scripts.md`), `docs/plan/README.md` (no row of it moves), `docs/idea/` (read-only).

## 0. Rules that constrain this revision

- **The precedent is the same file's second pass.** `wbs-procesador-llm-call.md` §12 reopened this
  artifact on 2026-10-03 for the streaming seam, and it is the shape this pass follows: a numbered
  section, a row-level table, the evidence, and what is *not* claimed. The subplan itself recorded
  that pass with a pointer to the WBS section, not by rewriting rows — the habit
  `subplan-scripts.md` also follows for its own second pass.
- **No ID changes.** The pass is over rows that already exist: `LLM-04`, `LLM-06`, `LLM-07`,
  `LLM-09`, `LLM-14`, `LLM-15` are re-scoped, never renumbered, so the range citations in
  `wbs-general.md` §1/§4, the WBS header, the WBS §1 summary and the traceability table stay
  valid. Effort stays as estimated; a re-estimation is a separate pass (subplan §9, decision 6).
- **Two classes of claim, and no third.** *Measured* — a command and a number, in §1. *Decided* —
  something only the plan owner can settle, listed in §7 and never assumed in §3. A sentence that
  is neither does not belong in the revision.
- **One decision this pass must not move.** What to *attach* — text, pixels, or both — is
  `ORC-13`'s (`src/docflow/workflow/llm_input.py`, the `ExtractionStrategy` vocabulary). This
  processor receives a resolved `document`/`images` pair and decides nothing about it; §3.1 freezes
  what the pair *means*, never who chose it.
- **Gates after every phase**, as the plan requires: `pytest`, `ruff check .`,
  `ruff format --check .`, `pylint src tests`. `docs/` is excluded from Ruff and Pylint, so for
  phases 1 and 3 the gates are a regression check rather than a lint of the new prose.
- **Every phase ends with a grep, not a look.** `plan-update-test-tiers.md` §0 records that a
  half-updated range has already happened twice in this repository.

## 1. What the probe measured

| # | Measured | How |
|---|---|---|
| E1 | **A vision call works through the processor path, and the image's cost is invisible to the pre-flight.** `status=SUCCESS`, `schema_valid=True`, `finish_reason=stop`, all seven fields — with the library estimating `prompt_tokens=615` where the provider counted `input_tokens=3420`. The provider's own counter is what proves the page travelled: ≈2 800 tokens arrived that the estimate never saw, **5.6× the number the guard compares** | `process_llm_request(LLMInput(document=None, images=[66cd35e9….jpg], template="extraction/invoice_vision", schema="extraction/invoice_vision"))` against Ollama `qwen2.5vl:7b`. The mechanism is `OllamaProvider.generate_structured` → `_generate(call, multimodal=bool(call.images))`, and the live answer is corroboration of it — invariant 4 (§3.8) is what would make it a guarantee |
| E2 | **The generator that carries images is not the one the plan names for it.** `resolve_generator(structured=True, multimodal=True) == "generate_structured"`, and `"generate_multimodal"` needs `structured=False`. Every vision step the registry ships declares a schema, so **every real vision call resolves to `generate_structured`** and `generate_multimodal` is unreachable from the registry | `primitives.resolve_generator`; `tests/llm/primitives/test_composition.py:625` already asserts the resolution |
| E3 | **A review that drops fields validates clean.** `validate_schema` returns `[]` for a verdict vector with 7 of 7 fields *and* for one with 2 of 7 | `primitives.validate_schema(answer, schema/review/invoice_vision.schema.json)` |
| E4 | **The option classes are not uniform.** `stream` and `api_key` are dropped before keying; `timeout`, `max_attempts` and `context_window` are the processor's own keys *and* enter `request_key`; `think` is neither a control option nor a decoding option — the primitive lifts it to the top of the Ollama body | `primitives.normalize_llm_options` + `calculate_request_key`, one option at a time |
| E5 | **"The window" has two spellings and only one of them takes effect.** `context_window` is a control option: it is read by the pre-flight and *never sent to the provider*. `num_ctx` is a decoding option: it is sent, and it is what actually resizes the window | `stated_context_window`, `entrypoints.CONTROL_OPTIONS`, and the live overflow below |

**The live failure behind E5.** The breakdown review — image + proposal + contract — overflowed
until `num_ctx=16384` was stated (`registry/README.md` carries the recipe). With `context_window`
absent, `is_context_limit_exceeded(tokens, None)` returns `False` by design ("an unmeasured ceiling
is not evidence of an overflow"), so the pre-flight blessed a call whose real cost it had never
measured. Both halves of that sentence are deliberate; together they are a silent stand-in.

**The observation that prompted E3** (measured earlier in this session, not re-measured here):
`deepseek-r1:8b` on the breakdown review, four identical runs, two answers carrying 8 and 9 of the
10 verdicts, `done_reason=stop`, well under `num_predict` — the schema reported no violation.

## 2. Verdict per frozen statement

| Frozen statement | Verdict | Evidence |
|---|---|---|
| §3 contract types: `images: list[str]` | **Silent.** What an image *is* (a path the seam reads), and what `document`/`images` together mean, are stated nowhere | E1; `input_hashes` hashes image **bytes** (`file_digest`), so the frozen formula is satisfied — the meaning is what is missing |
| §3 provider encapsulation: "the primitives expose the minimal surface needed: `generate_text`, `generate_multimodal`, `generate_structured`, …" | **Misleading.** It reads as three peers a caller chooses between; the resolver chooses, and the pixel case is the structured one — which attaches the images | E2; `OllamaProvider.generate_structured` calls `_generate(call, multimodal=bool(call.images))` |
| §3 request_key formula: `input_hashes  # document text + image bytes, hashed` | **Correct — do not reopen.** The implementation hashes the image's bytes, in order, and distinguishes an absent document from an empty one | `composition.input_hashes` |
| §3 error posture: `CONTEXT_OVERFLOW` typed, `RETRYABLE`/`NON_RETRYABLE` | **Correct — do not reopen.** The live overflow arrived typed, with `prompt_tokens`/`context_window` in its metadata | E5's run |
| §3 `options: dict[str, Any]` | **Silent.** The three classes (transport, decoding, request-level) and which of them belong to the request's identity are enumerated nowhere, so E4's split is neither stated nor uniform | E4 |
| §4 `LLM-04`: `<doc>` / `<extra>` / `<extra:key>` / `<schema>` resolution in a single pass | **Correct — do not reopen.** A vision template carries no `<doc>` and renders anyway; a review gets `<extra:proposal>`, and a non-string extra renders as canonical JSON | the ten vision templates; the probe's 21 recipes |
| §4 `LLM-07`: `load_schema`, `validate_schema`, `parse_json_response`, `validate_llm_result` | **Silent.** "Validation" means "fits the schema", and a schema with a closed vocabulary but no cardinality bound cannot see a dropped field | E3 |
| §4 `LLM-09`: "Provider primitives: Ollama local + OpenAI-compatible" | **Correct — do not reopen.** A real image call answered through it | E1 |
| §4 `LLM-15`: `count_tokens`, `truncate_to_token_limit`, `is_context_limit_exceeded` | **Silent.** Token *text* is measured; the image is not, so the guard compares a number it knows is smaller than the request | E1, E5 |
| §3 flow diagram: `PREP["prepare inputs (doc, images, schema)"]` | **Silent.** The step exists as a box; no row owns it, and no test drives it | §3.6 |
| §5 acceptance criteria | **Silent.** Three scenarios, none with pixels | §1, §3.5 |
| §6 test plan and invariants | **Silent.** No invariant reaches an image; both request fixtures state `images=[]` | `tests/llm/test_contracts.py:91`, `tests/llm/test_engine_double.py:53` |
| §6 "No test reaches a provider" | **Correct, and this pass keeps it.** E1 was run by hand as evidence and becomes an invariant over the fake, never a test over Ollama | `no-tests-on-third-parties.md` |
| §9 out of scope: source selection and OCR/VLM routing → orchestrator | **Correct — do not reopen, and cite it.** The payload is composed by `ORC-13`, which is why the revision freezes meaning and not choice | `workflow/llm_input.py` |
| §9 metadata key set (`assets_dir`, `output_dir`, `run_id`) | **Silent in the plan, load-bearing in the code.** The asset root is mandatory — a request without it fails `DEPENDENCY_ERROR` — and it is named in no plan document | `assets_dir_for`; `subplan-scripts.md` already argues the bench must state its own root rather than invent one for the library |

## 3. The revision, section by section

### 3.1 §3 — the contract types gain the meaning of the two input fields

Add one paragraph under the `LLMInput` block, in the vocabulary the orchestrator already uses
(`ExtractionStrategy`), without naming a strategy as *this* processor's:

> `document` and `images` are a resolved payload, not a choice: the caller states which it sent.
> Four shapes are possible — text alone, pixels alone, both, and neither — and the code already
> answers each one honestly, which is what this paragraph freezes: a template that carries `<doc>`
> with a request that carries no document fails with a typed `DEPENDENCY_ERROR` ("the template asks
> for a document and the request carries none"); an absent document is not an empty one (`document=""`
> renders the placeholder empty, `None` does not render it at all); and a template that reads pixels
> renders with no document, because the placeholder is not there to fill. Choosing the shape is
> `ORC-13`'s; this processor never widens or narrows it.

And freeze the metadata keys the request's own resolution depends on: `metadata["assets_dir"]` (no
default — a template that silently resolved against a working directory would make one request
mean two things), `metadata["output_dir"]` (`None` writes nothing), `metadata["run_id"]` (pinned, or
minted). Each is today a docstring; each is what a reproducible request needs.

### 3.2 §3 — the generator resolution is a rule, not a menu

Replace the reading of "expose the minimal surface needed" with the rule the code implements:

> The primitive a call resolves to is stated, not inferred at the call site:
> `resolve_generator(structured=…, multimodal=…)` — a schema wins over images, images win over
> neither, and **a structured call is what carries the images** (`generate_structured` attaches them
> whenever the call carries any). `generate_multimodal` is therefore the text-free, schema-free
> generator, not "the vision one": every step the registry ships declares a schema, so the
> registry's pixel path is `generate_structured`. The provider primitive list stays as it is; what
> changes is that its three names are no longer presented as the caller's options.

### 3.3 §3 — the three option classes

Freeze the enumeration (the formula's *shape* does not move — only which keys "options" means):

| Class | Keys | Reaches the provider | Enters `request_key` |
|---|---|---|---|
| Transport | `api_key`, `timeout`, `max_attempts` | never | `api_key` no (credential); `timeout`, `max_attempts` — **recommended no**: they bound an attempt, they cannot change an answer, and an attempt that ends by timeout is a failure with no result to reuse (§7, O-2) |
| Request-level | `think`, `keep_alive` | yes — lifted to the top of the Ollama body, not into `options` | **yes**: `think` changes what the model answers |
| Decoding | everything else (`temperature`, `min_p`, `num_ctx`, …) | yes, inside `options` | yes |
| Read by the processor, never sent | `context_window`, `max_prompt_tokens` | see §3.4 | `max_prompt_tokens` yes (it changes the prompt); `context_window` per §3.4 |

`stream` keeps the standing §12 exception: read by the processor, absent from the key, because a
streamed answer is the same answer.

### 3.4 §3 and §4 `LLM-15` — one spelling of the window, and an honest pre-flight

Two sentences and one rule:

- **One spelling — the window the call asks for.** Three sources exist and only one of them takes
  effect: the caller's `context_window` (a control option, never sent), the provider's own
  `get_context_window()` (Ollama reads `num_ctx` from `/api/show`; every other dialect answers
  `None`), and the `num_ctx` the call actually sends. The pre-flight should compare against the last
  of those — the window the request asks for — falling back to the provider's answer when the caller
  stated none, and to *cannot tell* when neither did. The caller's `context_window` then either maps
  onto the provider's field (recommended) or is documented as a claim that does not resize anything
  (§7, O-1).
- **An unmeasured cost is not a fit.** A request that carries images whose cost the caller has not
  stated must not be reported as fitting: `count_tokens` measures text, and a page image measured
  ≈2 800 tokens on `qwen2.5vl:7b` (E1) and ≈2 800 again on a second, independent run. The caller
  states the per-image cost (a number the model's own measurement produced) or the check reports
  *unmeasured* rather than *fits*. No constant is invented for a model — a default here would be
  exactly the "default model, engine or threshold used in place of a real answer" the project
  forbids.

### 3.5 The registry's one owed row (not this subplan's edit)

The measured completeness failure (E3) is closed by *data*, not by code: every review schema
enumerates `field` (`review/invoice.schema.json` 7 names, `review/invoice_desglose.schema.json` 10)
and declares **no `minItems`**, so the vocabulary is closed while the count is open. A `minItems`
equal to the step's own field count — data the schema already carries twice — makes `validate_schema`
catch it, and the library change is nothing. `review/general.schema.json` is the exception: its
`field` is unconstrained, so it can state no count. The row belongs to `registry/README.md`; the
subplan's part is one sentence in §9 saying where a review's completeness is enforced. Note that no
test in the suite reads `registry/`, so this row's only proof is a run: a real review answer that
drops a field must stop validating once the bound is there.

### 3.6 §4 WBS — the row scope

| Row | What the revision adds to the row's scope |
|---|---|
| `LLM-04` | The asset root and the two resolution rules (`template/<id>.md`, `schema/<id>.schema.json`); `document=None` renders a template with no `<doc>`, and a template that asks for one without it is a typed failure |
| `LLM-06` | The planned call carries the request's images — asserted, not assumed; the four payload shapes |
| `LLM-07` | Where a review's completeness is enforced (the schema's bound, §3.5) and what `validate_llm_result` still cannot see |
| `LLM-09` | The generator resolution rule (§3.2): `generate_structured` carries images when a schema is stated |
| `LLM-14` | The per-field vector is compared and consolidated field by field — never as one score |
| `LLM-15` | The image's cost in the pre-flight, and one spelling of the window (§3.4) |

### 3.7 §5 — one acceptance scenario

```gherkin
Scenario: A vision call sends the image, and the answer is validated against the schema
  Given an LLMInput with document=None, one image, a template that carries no <doc> and a schema
  When process_llm_request is invoked against the fake provider
  Then the call the fake receives carries that image,
    the resolved generator is generate_structured,
    the image's bytes are part of the request_key, and
    the result is SUCCESS with schema_valid true
```

### 3.8 §6 — two invariants, numbered so the existing citations stay resolvable

4. **The image reaches the provider.** *Mutation that breaks it:* drop `images=` from the planned
   call — the class of defect §12 found for `stream`, and the reason a probe reaching the seam is
   not evidence that the processor can.
5. **The pre-flight does not bless what it cannot measure.** *Mutation that breaks it:* restore the
   text-only estimate — a request carrying an image whose stated cost exceeds the window is then
   reported as fitting.

Both run against the scripted fake; neither reaches a provider.

### 3.9 §9 — decisions the revision adds

7. **The window — RESOLVED:** one spelling, mapped to the provider's field; the pre-flight may
   refuse, never silently bless (O-1).
8. **A review's completeness — RESOLVED:** enforced by the review schema's own bound, because a
   kernel API may not name a field or a verdict (no domain noun in `llm/`); the registry owns the
   data (O-3).
9. **The asset root — RESOLVED:** `metadata["assets_dir"]`, no default, `DEPENDENCY_ERROR`
   otherwise. It enters the request's identity only through what it resolves — the template's text
   lands in `rendered_prompt` and the schema's content in `schema_hash`, so a different asset root
   with the same identifier is a different request exactly when the assets differ.

### 3.10 The subplan's own pointer

Record the pass the way `subplan-scripts.md` records its own — a short italic parenthetical
next to §4's waves, pointing at the WBS section:

> *(The pixel half — the meaning of `document`/`images`, the generator resolution, the option
> classes, and the window — was reopened in the second pass of 2026-10-04:
> `docs/plan/issues/wbs-procesador-llm-call.md` §13.)*

## 4. The WBS second pass — a new §13

`docs/plan/issues/wbs-procesador-llm-call.md` gains a `## 13. Second pass — the pixel half
(LLM-04, LLM-06, LLM-07, LLM-09, LLM-14, LLM-15)`, in §12's shape: how it was reopened, what the
probes were, the row-level table of §3.6, the evidence (the four gates plus the mutation-falsified
invariants 4 and 5), and a **Not claimed** paragraph. The header's `Status` line gains the second
reopening date, and §2's index keeps `DONE` per task — this pass is over rows that already exist.

The header's own `Status` sentence is the one place the two passes meet, so it is written once:

> `LLM-01` … `LLM-15` **DONE** (delivered 2026-09-26); **reopened 2026-10-03** — the streaming seam,
> §12; **reopened 2026-10-04** — the pixel half, §13.

## 5. Waves

| Wave | Content | Ends with |
|---|---|---|
| 1 — the code the rows carry | `LLM-15` (the image's cost, one spelling of the window), `LLM-06`/`LLM-09` (the image in the planned call, asserted), `LLM-07` (the completeness sentence) | The four gates, invariants 4 and 5 mutation-falsified, and E1 re-run live as evidence — not as a test |
| 2 — the plan text | §3.1–§3.9 in the subplan, §4's new §13 in the WBS, the §3.10 pointer | A grep sweep for the six row IDs and for `generate_multimodal` across `docs/plan/` |
| 3 — the registry row | `minItems` on the step-shaped review schemas (§3.5) | A re-run of the probe's own check — one real review answer validated against each edited schema — because **no test in the suite reads `registry/`**: its schemas are data, and the only thing that has ever validated an answer against them is a run like the one §9 records |

Wave 1 is the only wave that can fail on evidence; waves 2 and 3 are one-sitting edits whose risk
is a half-updated citation.

## 6. Acceptance criteria for this revision

- The subplan and the WBS both name the pixel half, and neither contradicts the other: the six row
  scopes appear once in the subplan's table and once in §13, with the same wording.
- Invariants 4 and 5 exist, and each was proven to fail under its documented mutation before being
  restored green.
- E1 reproduces: a vision call through `process_llm_request` returns `SUCCESS` with a valid answer,
  and the provider's `input_tokens` is greater than the library's `prompt_tokens` by the image's
  cost — the measurement the fix must make visible.
- No row ID changed, no range citation broke: the six IDs still resolve in `wbs-general.md` §1, §4,
  the WBS header, the WBS §1 summary and the traceability table.
- The four gates pass on the code wave.

## 7. Open questions for the plan owner

| # | Question | Recommendation |
|---|---|---|
| O-1 | One spelling of the window (the processor maps `context_window` onto the provider's field), or two, with the plan stating which wins? | One spelling, and the source is the window the call asks for — the provider's own `get_context_window()` as the fallback. Two spellings is how the live overflow happened |
| O-2 | Do `timeout` and `max_attempts` belong to the request's identity? Today they enter `request_key`, so an answer earned under one timeout is not reusable under another | No. They bound an attempt, not the request; an attempt that ends by timeout carries no result to reuse |
| O-3 | Is a review's completeness the schema's business (`minItems`, no kernel change) or the processor's (a check that names `field_verdicts`, which the project's own rule forbids in a kernel API)? | The schema's. The measured failure is cardinality, and the count is data the schema already half-carries |
| O-4 | Does the per-image cost live in `metadata` (the caller measures it) or in the provider primitive (the model's own `prompt_eval_count` after the fact)? | `metadata`, stated before the call: a cost discovered after the call cannot prevent the overflow it caused |

## 8. Deliberately not in this pass

- **Any change to `registry/`'s assets or names.** The registry's README owns them; §3.5 records
  the one row it owes.
- **The bench.** `scripts/tools/_llm.py` states `images=[]` (line 473), so the vision steps are
  reachable from the library and not from the CLI. That is a `wbs-scripts.md` row, named here and
  not moved.
- **What to attach.** `ORC-13`'s decision, cited and not absorbed.
- **A real-engine test tier.** `no-tests-on-third-parties.md` wins; E1 is evidence in this note,
  and the invariant runs over the scripted fake.
- **`generate_multimodal`'s fate.** Whether a text-free, schema-free image call is a shape the
  project needs at all is a question for the plan owner, not for this revision: it exists, it is
  tested at the seam, and the pass only stops presenting it as the vision path.
- **Re-estimating effort.** The rows keep their estimates (subplan §9, decision 6).

## 9. Evidence

Run from the repository root, with Ollama serving `qwen2.5vl:7b`:

```bash
# E1 — one vision call through the processor path, and the two token counts side by side
# (the library is reached from the checkout, the way the probes bootstrap it)
python - <<'PY'
import sys
sys.path.insert(0, "src")

from docflow.llm.contracts import LLMInput
from docflow.llm.entrypoints import process_llm_request
request = LLMInput(
    task="vision-reading", provider="ollama", model="qwen2.5vl:7b",
    template="extraction/invoice_vision", document=None,
    images=["tests/fixtures/casos/66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.jpg"],
    extra_context={}, schema="extraction/invoice_vision", options={"timeout": 240},
    graph=None,
    metadata={"run_id": "evidence", "assets_dir": "registry", "output_dir": "/tmp/evidence"},
)
result = process_llm_request(request)
attempt = result.attempts[0]
print(result.status, result.schema_valid, attempt.request_metadata["finish_reason"])
print(attempt.request_metadata["prompt_tokens"], attempt.usage.input_tokens)
PY
```

E2–E5 are the same one-liners the §1 table names (`resolve_generator`, `validate_schema`,
`normalize_llm_options` + `calculate_request_key`, `stated_context_window` + `CONTROL_OPTIONS`),
and each is a function the library already exposes — which is why the evidence needed no probe of
its own, only a caller.

The two live numbers to compare against are the ones §1 records: **615 estimated against 3 420
counted** for the reading, and **3 316 counted** for the review whose prompt was 2 108 characters —
the second run agreeing with the first about what one page image costs.
