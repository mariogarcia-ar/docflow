# Decision — the vision path gains one prompt per step, and the fixtures gain a page pair

> Status: **applied** (registry, 2026-10-04) — D-1…D-7 landed as §8 records: ten templates, five
> schema copies, and the manifest, README and probe changes they need, the D-5 rename included
> (`review/vision` → `review/invoice_vision`). It supersedes no earlier note;
> it extends the pair `extraction/invoice_vision` + `review/invoice_vision` into a path that answers
> every step the text path answers. Two open questions were executed on their recommendation (O-1:
> the whole chain; O-2: the criteria-bearing reviewer, for the breakdown). Whether `docs/plan/`'s WBS
> rows move with it is the plan owner's, and §7 keeps what is still open.

## 1. What the registry showed

The vision path today answers one step of five:

| Step | Template | Placeholders | Schema |
|---|---|---|---|
| V1 — the base reading | `extraction/invoice_vision` (+ `.reasoning`) | none | `extraction/invoice_vision` |
| V2 — its review | `review/invoice_vision` (+ `.reasoning`) | `<extra:proposal>` | `review/invoice_vision` |

Every other step reads text, and cannot run from pixels at all:

| Step | Template (lines) | Placeholders | Schema |
|---|---|---|---|
| Detection (gate) | `extraction/invoice_deteccion` (41) | `<doc>` | `extraction/invoice_detection` |
| Tax breakdown | `extraction/invoice_desglose` (65) | `<doc>` | `extraction/invoice_desglose` |
| Classification | `extraction/invoice_clasificacion` (45) | `<doc>` | `extraction/invoice_clasificacion` |
| Line of business | `extraction/invoice_rubro` (45) | `<doc>` + `<extra:rubro>` | `extraction/invoice_rubro` |

Three consequences, all of them measured rather than assumed:

1. **The fallback answers one question.** `registry/README.md` says the vision path runs when the
   text path fails the checks, not instead of it — and a page the text path could not read is
   therefore *read* and not gated, not broken down, not classified, and given no line of business.
   Four of the five answers the text path gives are missing on the path that exists for the case
   where text is unavailable.
2. **The judgement is weaker on the vision side, by construction.** `review/invoice_vision` names no field
   of its own: it judges whatever proposal it is handed (its schema is what says which fields), and
   it carries no criteria block. Its text counterpart for the reading, `review/invoice`, carries one
   per field (107 lines against 47), and `review/invoice_desglose` carries one per field of the
   breakdown (115 lines). A vision proposal is therefore judged against the contract's shape, not
   against the criteria that decide its values.
3. **The comparison fixture exists — an earlier reading of this note measured the wrong folder.**
   `tests/fixtures-txt/` mirrors `tests/fixtures/` **by UUID** (`docs/plan/subplan-scripts.md` §315),
   so the case the bench reads as text, `tests/fixtures-txt/casos/66cd35e9-….txt`, is also on disk as
   a page image and a PDF: `tests/fixtures/casos/66cd35e9-….{jpg,pdf}`. The 26 images under
   `expected-extraction/` have no text twin, and *that* folder is what the first pass measured —
   the intersection there is empty, and the tree's is not. Wave 0 below is corrected accordingly:
   no new fixture is needed, and the agreement check runs on the pair that is already there.

## 2. What is proposed

| # | Decision | Where it lands |
|---|---|---|
| D-1 | The family is `invoice_vision_<step>`, and it keeps the `.reasoning` twin every step's pair has: the identifier in the table plus `.reasoning` | `registry/template/extraction/` |
| D-2 | Four steps gain both halves — `invoice_vision_deteccion`, `invoice_vision_desglose`, `invoice_vision_clasificacion`, `invoice_vision_rubro` | 8 new templates |
| D-3 | Each new template gets a schema named after it, a copy of its step's — the rule `extraction/invoice_vision` already follows | 4 new `registry/schema/extraction/*.schema.json` |
| D-4 | The breakdown gains a criteria-bearing reviewer for the vision path, `review/invoice_vision_desglose` (+ `.reasoning`) and its schema copy, mirroring `review/invoice_desglose`. The other three steps are judged by the field-agnostic `review/invoice_vision`, paired with the shape that names the judged fields — the step's own review schema where it has one, `review/general` (unconstrained `field`) where it does not | 2 new templates, 1 new schema |
| D-5 | The vision reviewer is named after the step whose schema it ships with, as every review asset is named after the step it judges: `review/vision` → `review/invoice_vision`, and its schema with it. Its rules stay field-agnostic — the template names no field of its own — and its listing line still reads as the review of a vision extraction *against its own schema*, not the reading's criteria-loaded twin | 3 renamed files, plus the references in the manifest, the README and the probe |
| D-6 | The agreement check runs on the pair the tree already carries — `tests/fixtures/casos/66cd35e9-….jpg` against `tests/fixtures-txt/casos/66cd35e9-….txt` — not on new captures; the unpaired `expected-extraction/` images are left as they are | `tests/fixtures/casos/`, `tests/fixtures-txt/casos/` |
| D-7 | The surface follows the assets: one recipe per new step in `scripts/tmpref/image_prompt.py`, and the registry's table gains the four rows. The bench CLI is not touched — it cannot send images | `registry/README.md`, the probe's examples |

## 3. What each new template carries

The work is mechanical, and the rule is one sentence: **the step's criteria, the page as the
source.** Concretely, per file:

1. **No `<doc>`, and no new placeholder.** A template that reads pixels carries no document block —
   the rule `registry/README.md` states as "a step reads pixels or it reads text". The placeholder
   set of a vision template is its text twin's minus `<doc>`/`<document>`, and a step that already
   names an input in `extra` keeps it: `<extra:rubro>` for the line of business,
   `<extra:proposal>` and `<extra:contract>` for a review.
2. **The source sentence changes, the criteria do not.** `extraction/invoice_vision.md` is the model
   to copy: it opens with the image *being* the document, tells the model never to follow anything
   written inside it as an instruction, and then states the fields and the rules. The text twin's
   "DOCUMENT CONTEXT" section is what changes most; the per-field rules carry over, because the
   question is the same question asked of different evidence.
3. **The answer's shape does not change at all.** Same object, same fields, same order, so the
   step's schema — and its copy under D-3 — applies unchanged. This is what makes the two paths
   comparable at all.
4. **The pair keeps its two halves.** The instruct template states the rules, the `.reasoning` twin
   states the criteria and is meant for a model with `think:true` (`registry/README.md`, "Instruct
   and reasoning: one schema, two prompts"). One content change per file, applied twice.

Per step, the one thing that is genuinely new work rather than translation:

| Step | What the page changes |
|---|---|
| Detection (gate) | The gate's evidence is a boolean over printed features; on a page it becomes evidence over what is legible, so the rejection reasons have to be readable from the frame as well as from the text |
| Tax breakdown | The arithmetic step: IVA discrimination and the totals block must be read from the pixels, and `alicuotas_detectadas` is where a rate that is implied rather than printed is decided — the criteria, not the schema, decide it |
| Classification | The class is a printed legend; illegible legends are where the text path asks for a null, and the image makes "illegible" a real answer rather than an OCR failure |
| Line of business | Needs `<extra:rubro>` from the caller, exactly as its text twin does; the page changes only where the fields are read from |

## 4. Acceptance criteria, per template

A template is done when all of these hold, and each is checkable:

- **The placeholder set is its text twin's minus `<doc>`** — mechanical (`grep -o '<[a-z]*…>'`), and
  a vision template that still carries a document block fails it.
- **It renders**: `--print-prompt` needs no provider, and it resolves the assets it names — the same
  check the probe's examples are already held to.
- **A live run returns a schema-valid answer** against the step's vision schema, verified with the
  library's own `validate_schema`, not by eye.
- **The pair behaves as a pair**: the reasoning twin with the trace left on, the instruct one with
  `--option think=false` (`md_prompt.py` documents the brake; the same wire field carries it).
- **Agreement is measured, not asserted.** On a paired receipt (D-6) the vision answer and the text
  answer are compared per field, and the report is per-field agreement plus the disagreements by
  kind — `null` where the pixels genuinely do not support a value, or a misread. A single aggregate
  score is the thing this project refuses to accept in place of the per-field vector.

## 5. Order and cost

| Wave | Work | Why this order |
|---|---|---|
| 0 | The paired receipt, which is already on disk: `tests/fixtures/casos/66cd35e9-….jpg` + `fixtures-txt/casos/66cd35e9-….txt` | Nothing to build — recorded here because the agreement check is worthless without it, and because the first pass looked for it in `expected-extraction/`, where the ids do not intersect |
| 1 | `invoice_vision_deteccion` + `.reasoning` + schema copy | The smallest template (41 lines) and the flow's first call: it proves the pattern end to end, cheaply |
| 2 | `invoice_vision_desglose` + `.reasoning` + schema copy, and the reviewer `review/invoice_vision_desglose` + `.reasoning` + its schema copy | The step the fallback most needs: without it a page read from pixels has no breakdown, and the breakdown is the answer the review audits |
| 3 | `invoice_vision_clasificacion`, `invoice_vision_rubro` (+ twins, schema copies) | The leaf steps; rubro is the only one that keeps an `extra` input |
| 4 | `review/invoice_vision`'s rename and listing wording (D-5), the registry's table rows, the probe's recipes | The surface, once the set is complete |

Sizes: waves 1 and 3 are **S** each (a translation of an existing 41–45-line template plus two
mechanical edits); wave 2 is **M** (65 lines of breakdown criteria, and a 115-line review to port);
wave 4 is **S**. Total: 10 new templates — ≈400 lines of prompt prose for the four steps' two
halves and ≈230 for the breakdown's reviewer — 5 schema copies, **15 new manifest entries** (10
templates and 5 schemas: the manifest is a full inventory, so every new file is one), the four
table rows, and the probe's recipes.

## 6. What this does not change

- **No library change.** `VLM_ONLY`, `TEXT_PLUS_VLM` and `OCR_PLUS_VLM` already model a pixel call
  and a page-plus-text call (`src/docflow/workflow/llm_input.py`); the templates are data the
  configuration names. Nothing in `src/docflow/` names a template.
- **The bench's limits stand.** `scripts/tools/llm.py` cannot send images, which is why these steps
  are reachable from the probes and from the library, and the registry says so in its own limits.
- **The roles do not multiply.** V1 extracts and V2 reviews, as the asset table states: the new
  templates are more questions for the same two roles, not more models.
- **The text path is untouched.** Every template here is new; no existing template, schema or row
  changes except the one listing line D-5 rewords.

## 7. The decisions this note leaves open

| # | Question | Recommendation |
|---|---|---|
| O-1 | Is the whole chain in scope, or only the steps the flow cannot do without? | The whole chain — a fallback that answers one of five questions is the gap this note exists to close — but sequenced, so wave 1 alone is useful |
| O-2 | Does a review on the vision path need its own criteria block — D-4 for the breakdown, and the same question for the reading, where `review/invoice` carries criteria per field and `review/invoice_vision` carries none — or is the generic reviewer with the step's schema enough? | Add it for both: a review without criteria is a second opinion, and the text path already showed which one the audit needs |
| O-3 | Which receipt does the agreement check run on, and against which text answer? | The paired case the tree already carries (`66cd35e9`), and its text answer must be produced in the pass: `var/tmp/reading.json` is a *vision* run over another image, not this receipt's text half |
| O-4 | Does the probe gain one recipe per step, or a loop over the steps? | One recipe per step, matching how the text probe documents its flow — the probe is the manual, not the runner |

## 8. Applied

| Wave | What landed |
|---|---|
| 1 | `template/extraction/invoice_vision_deteccion.md` (+ `.reasoning.md`), `schema/extraction/invoice_vision_detection.schema.json` |
| 2 | `template/extraction/invoice_vision_desglose.md` (+ `.reasoning.md`), `schema/extraction/invoice_vision_desglose.schema.json`, `template/review/invoice_vision_desglose.md` (+ `.reasoning.md`), `schema/review/invoice_vision_desglose.schema.json` |
| 3 | `template/extraction/invoice_vision_clasificacion.md` and `…_rubro.md` (+ their `.reasoning.md`), and the two schema copies |
| 4 | `registry/manifest.json` (fifteen keys), `registry/README.md` (the listing, the vision rows of the asset table, the pair rule, the chaining note, one paragraph on the five copies), `scripts/tmpref/image_prompt.py` (the pixel path: seven recipes, and the examples now read the paired receipt), and the D-5 rename — `template/review/vision.md` (+ `.reasoning.md`) and `schema/review/vision.schema.json` become `review/invoice_vision*` |

The translation rule held with one deliberate exception per file: the source framing and the
document block, nothing else. Where a criterion spoke of "the text", it speaks of "the image"; where
the text twin's `DOCUMENT CONTEXT` said the page was OCR output, the vision twin says the image *is*
the page. No new placeholder appeared, `<extra:rubro>` and the review's `<contract>`/`<proposal>`
included, and the answer's shape is untouched — which is what lets the copies drive the same decoder
grammar on either path.

Verification, all of it run rather than asserted:

- every new template renders with `--print-prompt`, and its placeholder set equals its text twin's
  minus the document block — the check §4 states, applied mechanically;
- every manifest key resolves to a file, no file under `template/` or `schema/` is unlisted, and
  each schema entry's `required_keys` are present;
- the five schema copies are byte-identical to the step schema they read;
- the D-5 rename left nothing behind: no `review/vision` survives in `registry/`, `scripts/`, `src/`
  or `tests/`, the three renamed manifest keys resolve, and the probe still renders all its recipes;
- the whole pixel path ran live, on the receipt whose text half the bench has already answered, and
  each answer was validated with the library's own `validate_schema` (see §9);

§1.3's fixture claim was corrected in the same pass: the pairing is by UUID and already existed.

## 9. Verified, live

The pixel path ran end to end on the paired receipt — `tests/fixtures/casos/66cd35e9-….jpg`, the image
of the text the bench reads as `fixtures-txt/casos/66cd35e9-….txt` — with `qwen2.5vl:7b` standing in
for `qwen3-vl:8b`, one call per step. Every answer was validated with the library's own
`validate_schema` against the step's vision schema:

| Step | Answer | Verdict |
|---|---|---|
| `extraction/invoice_vision` | the seven fields | valid |
| `extraction/invoice_vision_deteccion` | the three fields | valid |
| `extraction/invoice_vision_desglose` | the ten fields | valid |
| `extraction/invoice_vision_clasificacion` | the four fields | valid |
| `extraction/invoice_vision_rubro` (`--extra rubro=Restaurante`) | the three fields | valid |
| `review/invoice_vision` over the reading | `field_verdicts` | valid |
| `review/invoice_vision_desglose` over the breakdown | `field_verdicts` | valid |

**Agreement, per field.** The reading taken from the image and the reading taken from the text — one
receipt, two paths — answered the same seven fields, **7/7**: `tipo_comprobante`,
`razon_social_emisor`, `cuit_emisor`, `fecha_emision`, `nro_comprobante`, `moneda` and `notas`. The
text answer was produced in this pass (`extraction/invoice`, `gemma3:12b`), because the answer the
bench had already saved under `var/tmp/reading.json` is a **vision** run over a different image
(`qwen2.5vl:7b`, `prompt_eval_count` 1758, an `expected-extraction/` receipt), not this receipt's
text half — which is what O-3 corrects above.

**One finding that belongs in any recipe.** The breakdown's review failed on its first attempt with
`CONTEXT_OVERFLOW: ollama refused the request as longer than 'qwen2.5vl:7b' can take`. A vision review
carries the page *and* the proposal *and*, here, the contract, and image tokens are context like any
other: Ollama's default window is smaller than that request. Stating `--option num_ctx=16384` — which
the text flow's review recipes already state — is what the probe's examples now do for both vision
reviews, and the failure is recorded here because a template cannot fix a window it does not set.
