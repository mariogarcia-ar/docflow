# Subplan — procesador-ocr

> Phase: **1 (processors, independently)** of the general plan (`docs/plan/README.md`).
> Module: `ocr` → `docflow.ocr` (physical path `src/docflow/ocr/`).
> Source of truth: `docs/idea/procesador-ocr.md` + `docs/idea/readme.md`. Where they
> disagree, reconcile back to the idea. All output and identifiers in English.

## 1. Objective

Implement the `ocr` processor as a single-responsibility processor that receives a prepared
image and returns a textual and structured representation of it, using **Docling as the
only OCR/document-analysis engine** (Docling is fixed — never a configurable setting). The
processor produces plain text, structured Markdown, JSON, blocks, tables, layout, reading
order, metrics, technical metadata, and an extraction status, through the
`OCRRequest → OCRResult` contract, and writes artifacts only inside its own `ocr/`
namespace. It is Phase 1 of the general plan and must be implementable in isolation: it
never imports another processor and never makes a workflow decision.

## 2. Context (BA)

### Responsibility

`ocr` answers a single question about an already-prepared image:

> **"Given this prepared image and this configuration, what textual and structural
> content can I extract from it?"**

It answers **that**, not any of the workflow questions around it:

> "Should OCR run on this page?" · "Should I use this OCR or the native text?" · "Should
> I send this to an LLM/VLM?"

### Explicit "does NOT" list

The module **does NOT**:

- process PDFs, render pages, or select pages (that is `pdf`);
- normalize, deskew, binarize, or prepare images (that is `image`);
- decide whether OCR must run, or select the final document source (that is the orchestrator);
- call an LLM/VLM or build an LLM context;
- compare OCR output against native text, VLM output, or any other source;
- own workflow state, idempotency, `REUSE`/`SKIP`/`FORCE`/`RESUME`, stop/resume, or full-stage retry (all orchestrator);
- write outside its `ocr/` namespace (`source/`, `native_text/`, `image/`, `llm/` are untouchable);
- interpret metrics or validation results (e.g. `LOW_CONTENT → use VLM`). It reports; the orchestrator decides.

### Principle line

> The `ocr` processor **produces information**; the **orchestrator decides what to do with
> it**. It answers "what content is in this image", not "what should happen next".

## 3. Design (SA)

### 3.1 Contract types

**Input — `OCRRequest`**

| Field | Type | Meaning |
|---|---|---|
| `image_path` | `str` | Path to the prepared image (already normalized/`ocr_ready`). |
| `output_dir` | `str` | Exclusive output directory (the `ocr/` namespace root). |
| `options` | `OCROptions` | Raw OCR/engine options; normalized internally. |
| `context` | `Context` | Correlation metadata only (`document_id`, `page_number`, `workflow_run_id`). Never used to mutate global state. |

`OCROptions` is normalized into a stable `NormalizedOCROptions`:

```
NormalizedOCROptions
├── ocr: bool
├── layout: bool
├── tables: bool
├── reading_order: bool
├── language: str | None
└── engine_options: dict
```

**Output — `OCRResult`**

| Field | Type | Meaning |
|---|---|---|
| `text` | `str` | Plain text (logical reading order). |
| `markdown` | `str` | Structured Markdown. |
| `structured_document` | `dict` | Engine-independent `OCRDocument` representation. |
| `tables` | `list[TableResult]` | Detected tables in preserved order. |
| `blocks` | `list[BlockResult]` | Deterministically ordered blocks. |
| `layout` | `LayoutResult` | Normalized bounding boxes, page dimensions, regions. |
| `reading_order` | `list[str]` | Ordered block/table identifiers. |
| `metrics` | `OCRMetrics` | `characters, words, blocks, tables, paragraphs, text_density, empty, structure_detected`. |
| `artifacts` | `ArtifactPaths` | Paths to `text.txt`, `document.md`, `document.json`, `tables/*`, `metadata.json`. |
| `validation` | `OCRValidation` | Status: `VALID | EMPTY | LOW_CONTENT | INCOMPLETE | PARSE_ERROR | ERROR`. |
| `metadata` | `OCRMetadata` | `engine, engine_version, processor_version, options, input, metrics, validation, timing, transformations, context`. |
| `status` | `str` | `success` or `failed` (typed failure is preferred over an exception). |

`OCRMetadata` always records `engine: "docling"` and a concrete `engine_version` (e.g.
`"x.y.z"`). The orchestrator can later derive a `processing_key` from this metadata.

**Intermediate representation — `OCRDocument`** (engine-independent; the rest of the
system never touches Docling's native structures):

```
OCRDocument
├── text
├── paragraphs[]
├── titles[]
├── blocks[]
├── tables[]
├── layout
├── reading_order[]
└── metadata
```

### 3.2 Artifact namespace

The processor writes **only** inside its assigned `output_dir` (the `ocr/` namespace):

```text
ocr/
├── text.txt
├── document.md
├── document.json
├── tables/
│   ├── table_001.md      # zero-padded, in reading order
│   └── table_002.md
└── metadata.json
```

`table_NNN.json` is optional in this phase (see §9 resolved decisions). Every artifact is
published atomically: write to `ocr/.tmp/`, validate, then rename into place, so no
partial artifact is ever visible as valid.

### 3.3 Internal flow

```mermaid
flowchart TD
    R[OCRRequest] --> V1[validate_ocr_input]
    V1 --> N[normalize_docling_options -> NormalizedOCROptions]
    N --> C[configure_image_pipeline]
    C --> P[convert_image_with_docling]
    P --> E[extract_docling_* -> OCRDocument]
    E --> T[build text.txt]
    E --> M[build document.md]
    E --> J[build document.json]
    E --> TB[process_tables -> tables/]
    T --> A[analyze_ocr_result -> OCRMetrics]
    M --> A
    J --> A
    TB --> A
    A --> V3[validate_ocr_result -> OCRValidation]
    V3 --> S[atomic persist + metadata.json]
    S --> O[OCRResult]
```

### 3.4 Primitives

Thin functions that are the **only** place that knows Docling; the rest of the module works
on the engine-independent `OCRDocument`. The list below is the processor's whole surface — a
name that is not here does not exist, so no predicate layer, no second export path and no
second measurement can appear later without a plan revision.

- **Pipeline/config:** `load_docling_pipeline`, `configure_image_pipeline`,
  `normalize_docling_options`. Enablement is a decision, not an engine call: the option
  flags are turned into the pipeline configuration inline, so no `enable_*` /
  `should_enable_*` predicate exists for each of the six flags.
- **Execution:** `convert_image_with_docling` — the engine call, and the injection point of
  the double.
- **Extraction:** `extract_docling_text`, `extract_docling_markdown`, `extract_docling_tables`,
  `extract_docling_blocks`, `extract_docling_layout` — these are what turn Docling's native
  structures into the engine-independent `OCRDocument`; nothing downstream sees the engine.
- **Text/Markdown:** `normalize_ocr_text`, `normalize_markdown`, `merge_ocr_blocks`,
  `preserve_reading_order` — one normalizer per representation, not two.
- **Tables:** `normalize_table`, `table_to_markdown`.
- **Layout:** `normalize_bbox`, `normalize_layout`.
- **Metadata:** `build_ocr_metadata`, `get_engine_version`.
- **Validation:** `validate_ocr_input`, `validate_ocr_result`, `validate_output_artifacts`.
- **Files:** `ensure_directory`, `write_text_atomic`, `write_json_atomic`.

`OCRMetrics` (`OCR-08`) is the single place that counts characters, words, blocks, tables and
paragraphs — hence no `count_*` helper; `OCR-06` is the single producer of `text.txt`,
`document.md` and `document.json` — hence no `export_docling_*` path. Fifty-three names for
one conversion is the wrapper-for-its-own-sake the PoC posture forbids.

Entry points: `process_ocr_image(request) -> OCRResult` (the main function), and an optional
thin `process_ocr_from_page(...)` wrapper that only builds an `OCRRequest` and delegates to
`process_ocr_image` — it never reads a PDF or selects a page image itself.

### 3.5 Docling encapsulation

Docling is the **only** engine and is accessed **only** from `ocr/primitives/` — no other
processor, and never the orchestrator, touches Docling directly. The value `"docling"` is
recorded in metadata, not exposed as a user-selectable engine option. The processor's
public contract (`OCRRequest → procesador-ocr → OCRResult`) is engine-agnostic, and the
rest of the module works on the engine-independent `OCRDocument`.

### 3.5.1 Engine double (the test double)

The only test double for Docling is an **in-memory fake injected at
`convert_image_with_docling`** (`README.md` §9.7). We do not test Docling: no test invokes,
imports or asserts it, and no test claims the engine is deterministic, correct or complete —
our own ordering and format guarantees are what the suite proves.

| | |
|---|---|
| **What the fake returns** | Docling's **native** values — text, markdown, tables, blocks, layout, metadata — as Python objects or plain dicts. **Not** our translated `OCRDocument`/`OCRResult`. |
| **Location** | `tests/fakes/engines/fake_docling.py` — in memory, no fixtures on disk. |
| **Injection point** | the engine call **`convert_image_with_docling`** — never at `extract_docling_*`, which is the half of the module the fake must exercise rather than replace. |
| **Failure modes** | the fake can raise during conversion, so the `ENGINE_ERROR` path is reachable with no engine installed. |

Two consequences specific to this engine:

- The fake returns blocks in **adversarial (unsorted) order**, so invariant 1
  (deterministic ordering) actually discriminates: a fake that handed back already-sorted
  blocks would let a broken sort pass.
- If a cached corpus helper is reused, its **cache key must include which engine** produced
  the result; otherwise a fake written for one engine is served for another.

### 3.6 Determinism posture

Same image + same engine version + same normalized options ⇒ same **logical output
structure**. Achieved by:

- normalizing options to a fixed, ordered `NormalizedOCROptions`;
- a stable, versioned `document.json` schema;
- deterministic block ordering (sort by reading order, tie-break by normalized `bbox`);
- preserving table order (`table_NNN`, zero-padded, in reading order);
- excluding timestamps from functional content (`text.txt`, `document.md`, `document.json`,
  `tables/*`) — timing lives only in `metadata.json`;
- recording `engine` + `engine_version` in `metadata.json` so reproducibility is auditable.

### 3.7 Error-handling posture

Errors are **classified, not swallowed, and not thrown as bare exceptions** where a typed
result is the contract:

- `OCRError { type, message, recoverable, metadata }` with types `INVALID_INPUT`,
  `UNSUPPORTED_IMAGE`, `ENGINE_ERROR`, `OCR_ERROR`, `LAYOUT_ERROR`,
  `TABLE_EXTRACTION_ERROR`, `EXPORT_ERROR`, `IO_ERROR`, `INTERNAL_ERROR`.
- Failure surfaces as `OCRResult(status="failed", error=…)`; the orchestrator owns the
  document-level retry/fallback decision.
- Only transparent, engine-level operations may retry internally; the processor never
  builds a second OCR workflow on its own.
- Atomic publication (`.tmp/` → validate → rename) guarantees no partially written artifact
  is ever considered valid.

## 4. Execution plan (PM)

### 4.1 WBS

| ID | Task | Effort | Depends on |
|---|---|---|---|
| OCR-01 | Skeleton sub-package `src/docflow/ocr/` + contract dataclasses (`OCRRequest`, `OCRResult`, `NormalizedOCROptions`, `OCRMetrics`, `OCRMetadata`, `OCRValidation`, `OCRError`, `ArtifactPaths`) with type hints and no silent defaults. | S | — |
| OCR-02 | Docling seam in `ocr/primitives/` (`load_docling_pipeline`, `configure_image_pipeline`, `normalize_docling_options`, `convert_image_with_docling`, `get_engine_version`); pin `docling` in `pyproject.toml`; record `engine`/`engine_version`. | S | OCR-01 |
| OCR-03 | Pipeline configuration: `load_docling_pipeline` + `configure_image_pipeline`, with the option flags folded into the pipeline configuration inline (no `enable_*` / `should_enable_*` predicate layer). | M | OCR-02 |
| OCR-04 | Execution + extraction primitives: `convert_image_with_docling`, `extract_docling_*`, building the engine-independent `OCRDocument`. | M | OCR-03 |
| OCR-05 | Deterministic normalization: block ordering, `normalize_bbox`, `normalize_layout`, `preserve_reading_order`. | M | OCR-04 |
| OCR-06 | Output builders: `build text.txt`, `build document.md`, `build document.json` (versioned schema). | M | OCR-05 |
| OCR-07 | Table processing: `process_tables`, `normalize_table`, `table_to_markdown`, export `tables/table_NNN.md` in order. | M | OCR-06 |
| OCR-08 | Metrics: `analyze_ocr_result` → `OCRMetrics`. | S | OCR-05 |
| OCR-09 | Technical validation: `validate_ocr_result` + `validate_output_artifacts`, statuses `VALID/EMPTY/LOW_CONTENT/…`. | S | OCR-06, OCR-08 |
| OCR-10 | Atomic persistence + `metadata.json` + publish (`ocr/.tmp/` → rename). | M | OCR-07, OCR-09 |
| OCR-11 | Entry points: `process_ocr_image` orchestration + optional `process_ocr_from_page` wrapper. | M | OCR-10 |
| OCR-12 | Tests: happy path + invariant tests + committed image fixtures. | M | OCR-11, OCR-14 |
| OCR-13 | Four QA gates green; mutation-falsify each invariant test and document observations. | S | OCR-12 |
| OCR-14 | In-memory Docling double (native shape, adversarial order) | S | OCR-02 |

`process_ocr_from_page` is declared in OCR-11 but deferred to Phase 3 integration by §9 resolved decision 5; Phase 1 ships only `process_ocr_image` and the wrapper carries an inline `# TODO: [MVP]`.

### 4.2 Order / waves

- **Wave 1 — Foundations:** OCR-01, OCR-02 (contracts and the Docling seam first).
- **Wave 2 — Engine + extraction:** OCR-03, OCR-04, OCR-05 (all Docling access isolated here) — plus OCR-14 (the Docling double, which lets the whole processor be tested with no engine installed).
- **Wave 3 — Outputs:** OCR-06 ∥ OCR-08 (both after OCR-05), then OCR-07 and OCR-09 (representations; metrics computed in parallel with the output builders; tables and validation close the wave).
- **Wave 4 — Publish + entry points:** OCR-10, OCR-11 (atomic write, `process_ocr_image`).
- **Wave 5 — Verification:** OCR-12, OCR-13 (tests, fixtures, QA gates).

Waves are strictly sequential; tasks within a wave that share no dependency may proceed in
parallel (Wave 3 is the only wave with genuine parallelism in this subplan).

## 5. Acceptance criteria

**Scenario: happy-path extraction from a prepared image**

```gherkin
Given a prepared image at "image/normalized.png"
  And options enabling OCR, layout, tables, and reading order
When process_ocr_image is called with a valid OCRRequest
Then OCRResult.status is "success"
  And OCRResult.validation.status is "VALID"
  And the ocr/ namespace contains text.txt, document.md, document.json, and metadata.json
  And metadata.json records engine "docling" and a non-empty engine_version
```

**Scenario: deterministic functional content**

```gherkin
Given the same prepared image and the same normalized options
  And the in-memory Docling double feeding the same native values
When process_ocr_image runs twice into two different output directories
Then the functional content of document.json is identical across both runs
  And metadata.json differs only in timing fields
```

The scenario asserts **our** stable ordering and format on a fixed input — never that
the engine would return the same thing twice (`README.md` §9.7).

**Scenario: empty input is reported, not thrown**

```gherkin
Given a prepared image that contains no text
When process_ocr_image is called
Then OCRResult.validation.status is "EMPTY"
  And no exception escapes the call
  And no partial artifact is published under ocr/
```

**Scenario: engine failure is contained**

```gherkin
Given a prepared image and a Docling engine that raises during conversion
When process_ocr_image is called
Then OCRResult.status is "failed"
  And OCRResult.error.type is "ENGINE_ERROR"
  And no .tmp files remain in the ocr/ directory
```

**Scenario: no test reaches Docling**

```gherkin
Given the in-memory Docling double
When the whole suite runs
Then every test of this processor passes with zero Docling conversions
  And no test imports or asserts the engine
```

## 6. Test plan

### One tier, no engine

Every test of this module — the happy path, the three invariants, metrics, validation and the
atomic-publication failure path — runs on the in-memory Docling double (placement and
injection point in §3.5.1) and never reaches Docling. The suite must pass with no engine
installed; there is no real tier, no marker and no skip rule (`README.md` §7, §9.7).

**Happy-path test** — `test_process_ocr_image_happy_path`: feed a small committed prepared
image through `process_ocr_image` with the engine call doubled, assert `status == "success"`,
validation `VALID`, non-empty `text`, and that `text.txt`, `document.md`, `document.json`,
`metadata.json` exist with `engine == "docling"`. Our determinism guarantee is proved by
invariant 1 below, on the double — never by asserting that the engine behaves the same way
twice.

**Invariant tests** (each must fail when the invariant is broken — mutation listed):

1. **Deterministic ordering + stable format.** Assert two runs produce byte-identical
   functional content of `document.json`.
   *Mutation that breaks it:* dropping the stable sort key (e.g. changing
   `sorted(blocks, key=reading_order_key)` to `list(blocks)` in engine iteration order), or
   adding a timestamp into `document.json`.
2. **No timestamps in functional content.** Assert `text.txt`/`document.md`/`document.json`/
   `tables/*` contain no run-time timestamps.
   *Mutation that breaks it:* injecting `datetime.now().isoformat()` into the JSON or Markdown
   builder.
3. **Atomic publication — no partial artifacts on failure.** Force a failure after
   conversion, assert `ocr/` contains no `.tmp` files and no final-named artifacts.
   *Mutation that breaks it:* writing directly to the final path instead of to
   `ocr/.tmp/` followed by rename (publish-before-validate).

**Fixtures needed:**

- `fixtures/ocr_prepared_text_and_table.png` — a prepared image with a known heading, one
  paragraph, and a 2×2 table (provokes real structure extraction, ordering, and table export).
- `fixtures/ocr_blank.png` — an image with no text (provokes the `EMPTY` validation path).

### Failure paths, two buckets

Every failure path is classified explicitly, because the bucket decides the test mechanism:

| Fixture / path | Bucket | Test mechanism |
|---|---|---|
| `ocr_blank.png` → `EMPTY` | **Data, not failure** — the conversion succeeds on this input; the emptiness is *data* | the double returns empty native values, so the `EMPTY` path is exercised with no live run |
| `OCR-04`'s "engine raises during conversion" | **Injected** — the engine breaks in a way no input reproduces | the double raises; never a live call and never a claim about how the engine reports it |

## 7. Definition of Ready / Definition of Done

### Definition of Ready

- Contract types and `NormalizedOCROptions` fields agreed with `docs/idea/procesador-ocr.md`.
- `ocr/primitives/` skeleton + Docling pin agreed; Docling pinned in `pyproject.toml`.
- Output schemas (`text.txt`, `document.md`, `document.json`) frozen for this phase.
- Committed image fixtures in `fixtures/`.
- The Docling double of §3.5.1 (`tests/fakes/engines/fake_docling.py`, native values, injected at `convert_image_with_docling`) is agreed; `OCR-14` is a row in §4.1.
- No unresolved dependency on any other processor (fully independent, per Phase 1).

### Definition of Done

- `process_ocr_image` (and optional `process_ocr_from_page`) implemented with Docling
  reached only through `ocr/primitives/`.
- The **no-engine rule** holds: the whole suite passes with Docling absent, no test invokes,
  imports or asserts the engine, and the double is never reachable as a fallback (nothing
  under `src/docflow/` imports `tests/`).
- Happy-path test green using real bytes from a committed fixture, with the engine call
  doubled.
- Every invariant test passes **and** has been mutation-falsified (mutation applied → test
  fails → mutation reverted → test green), with both observations reported.
- All artifacts written atomically and only inside the `ocr/` namespace.
- The surface is exactly the one in §3.4: no `enable_*` / `should_enable_*` predicate layer, no `export_docling_*` path beside the builders of `OCR-06`, no `count_*` helper beside `OCRMetrics`.
- `engine` + `engine_version` recorded in `metadata.json`.
- Every shortcut tagged inline with `# TODO: [MVP]` or `# TODO: [RELEASE]`.
- The four QA gates pass:

```bash
pytest                                    # tests green
ruff check .                              # linter, includes import order (rule `I`)
ruff format --check .                     # formatter
pylint src tests                          # fixme disabled; the rest clean
```

## 8. Risks & mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Docling version drift changes output | Silent output differences across runs | Pin Docling and surface `engine_version` in metadata; deterministic-ordering tests catch our side of the regression. The engine is not tested (`README.md` §9.7). |
| Docling residual non-determinism on identical input | A determinism claim we cannot keep | We never assert that the engine is deterministic: the invariants test **our** normalized structure on the double, and the determinism class is recorded instead of assumed. |
| Docling schema changes between versions | Extraction primitives break | Isolate all Docling access in `ocr/primitives/`; everything downstream uses `OCRDocument`. |
| Silent empty/partial extraction | Empty result reported as correct | Mandatory structural validation with `EMPTY`/`LOW_CONTENT` statuses; blank-image fixture test. |
| Interrupted publish leaves corrupt artifacts | Downstream reads invalid files | Atomic `.tmp/` → validate → rename; invariant test on failure paths. |
| Large images / many tables (2 MB item, memory) | Slow or memory-heavy runs | PoC on small fixture; tag resource caps with `# TODO: [RELEASE]`. |
| Over-engineering (generic abstraction layers) | PoC bloat, slow delivery | Thin primitives with a closed list (§3.4): a name that is not there does not exist — one seam, one measurement (`OCRMetrics`), one producer per artifact (`OCR-06`), single entry point, `# TODO` markers for deferred complexity. |

## 9. Out of scope & resolved decisions

### Out of scope (owned by other processors / the orchestrator)

- PDF splitting, rendering, page selection (`procesador-pdf`).
- Image normalization and `ocr_ready`/`vlm_ready` preparation (`procesador-image`).
- Deciding whether OCR must run; source selection; comparing OCR vs. native text or VLM;
  `build_llm_context_from_ocr` (`procesador-orquestador`).
- LLM/VLM inference (`procesador-llm-call`).
- Workflow state, idempotency, `stop/resume`, `skip/force`, full-stage retry, concurrency
  control (orchestrator).
- Domain-specific extraction rules (invoice fields, verdicts) — the pipeline is generic.
- A second OCR engine or a user-selectable engine setting (Docling is fixed).

### Resolved decisions

1. `document.json` schema versioning policy — **RESOLVED:** a stable, versioned schema;
   fields are additive-only within a version.
2. `tables/table_NNN.json` — **RESOLVED:** markdown only in this phase; the JSON table
   export is deferred (`# TODO: [MVP]`).
3. Determinism assertion strength — **RESOLVED:** byte-identical *functional* content;
   `metadata.json` may differ in timing fields.
4. `bbox` normalization reference — **RESOLVED:** normalized 0–1 coordinates (the
   engine-independent target).
5. `process_ocr_from_page` wrapper — **RESOLVED:** deferred to Phase 3 integration; Phase 1
   ships only `process_ocr_image`.
6. Physical layout — **RESOLVED:** sub-package `docflow.ocr` (path `src/docflow/ocr/`) with
   `primitives/` / `utils/` / `helpers/`, per the idea's §"Estructura del proyecto";
   `utils/` and `helpers/` are reserved and stay empty in Phase 1, since a symbol belongs
   there only when it has more than one caller.
7. **Primitive surface — RESOLVED for PoC:** only the names listed in §3.4 are built. The
   enablement predicates, the second export path and the `count_*` helpers are dropped rather
   than tagged, because each one duplicates a decision (`configure_image_pipeline`), a
   producer (`OCR-06`) or a measurement (`OCRMetrics`) that already exists. The list in
   `docs/idea/procesador-ocr.md` names more primitives; that divergence is deliberate and is
   recorded for `GEN-17`.
