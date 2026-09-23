# docflow — General Implementation Plan

> Status: **proposed**. This is the *general* execution plan for the document-processing
> pipeline described in `docs/idea/`. It is deliberately high-altitude: it fixes phases,
> modules, contracts and acceptance criteria, and leaves task-level decomposition (WBS,
> per-task issues) to later plan documents.
>
> Source of truth for *what to build*: `docs/idea/readme.md` + the five
> `procesador-*.md` files. Where this plan and the idea disagree, this plan must be
> reconciled back to the idea.

## Subplans

One subplan per processor, each following the same section structure (Objective /
Context (BA) / Design (SA) / Execution plan (PM) / Acceptance criteria / Test plan /
DoR-DoD / Risks / Out of scope & resolved decisions):

| Subplan | Processor / component | Phase |
|---|---|---|
| [`subplan-procesador-pdf.md`](subplan-procesador-pdf.md) | `procesador-pdf` | 1 |
| [`subplan-procesador-image.md`](subplan-procesador-image.md) | `procesador-image` | 1 |
| [`subplan-procesador-ocr.md`](subplan-procesador-ocr.md) | `procesador-ocr` | 1 |
| [`subplan-procesador-llm-call.md`](subplan-procesador-llm-call.md) | `procesador-llm-call` | 1 |
| [`subplan-orquestador.md`](subplan-orquestador.md) | `procesador-orquestador` | 2 |

---

## 1. Objective

Implement a **modular pipeline** that processes PDF and image documents by composing five
single-responsibility processors under one orchestrator:

```
INPUT → ORCHESTRATOR → PDF/IMAGE → IMAGE PREP → OCR (when applicable)
      → SOURCE SELECTION → LLM/VLM → VALIDATION → RESULT
```

The deliverable is a working end-to-end loop with three hard properties, taken verbatim
from the idea:

1. **Each processor has a single responsibility** and returns one result.
2. **Only the orchestrator knows the whole workflow.**
3. **Valid, expensive work is never repeated needlessly.**

This plan covers the *happy path* first (PoC posture): hardcode/mock/in-memory where it
closes the loop faster, tag every shortcut with `# TODO: [MVP]` (real DB/API/validation)
or `# TODO: [RELEASE]` (telemetry/caching/HA/security).

---

## 2. Scope

### In scope (this plan)

| Component | Responsibility (from `docs/idea/`) |
|---|---|
| `procesador-pdf` | Inspect, split and extract native PDF artifacts (pages, render, native text, embedded images, metrics, classification). |
| `procesador-image` | Analyse, normalize and prepare images; produce `normalized` / `ocr_ready` / `vlm_ready` variants. |
| `procesador-ocr` | Extract structured text/layout from a prepared image (Docling as the OCR engine). |
| `procesador-llm-call` | Prepare, execute, validate and persist LLM/VLM inference (single call or an internal inference graph). |
| `procesador-orquestador` | Coordinate the workflow, persist state, decide skip/reuse/force/resume, consolidate pages and document. |

### Out of scope (first iteration)

- Multi-document corpus batching and distributed execution (revisited at the Release gate).
- A labelled golden set (deferred; see §8 risks).
- Real retry queues and GPU-competition policy (revisited at the Release gate).
- Parallel page execution: the PoC runs pages sequentially and only declares
  `parallel_pages`, tagged `# TODO: [MVP]` (see `subplan-orquestador.md` §9.3).
- Durable cross-process workflow state: the PoC keeps an in-memory `DocumentContext`
  serialised to JSON, tagged `# TODO: [MVP]` (see `subplan-orquestador.md` §9.2).
- Domain-specific extraction rules (invoice fields, verdicts) — the pipeline is generic;
  the prompt/schema assets are data, not code.

---

## 3. Architecture

### 3.1 Component view

```mermaid
flowchart TB
    IN["DocumentRequest"] --> ORCH["docflow.workflow<br/>(procesador-orquestador)"]
    ORCH --> PDF["docflow.pdf<br/>(procesador-pdf)"]
    ORCH --> IMG["docflow.image<br/>(procesador-image)"]
    ORCH --> OCR["docflow.ocr<br/>(procesador-ocr)"]
    ORCH --> LLM["docflow.llm<br/>(procesador-llm-call)"]

    PDF -- "PDFResult" --> ORCH
    IMG -- "ImageResult" --> ORCH
    OCR -- "OCRResult" --> ORCH
    LLM -- "LLMResult" --> ORCH
    ORCH --> OUT["DocumentResult"]
```

The arrows in one direction are **requests**, in the other **results**. A processor never
calls another processor; the orchestrator is the only component that composes them.

### 3.2 Document workflow

```mermaid
flowchart TD
    A[INPUT] --> B[detect_input_type]
    B -->|PDF| C["docflow.pdf"]
    B -->|IMAGE| D[logical page]
    C --> E["docflow.image"]
    D --> E
    E --> F{requires OCR?}
    F -->|yes| G["docflow.ocr"]
    F -->|no| H[select_source]
    G --> H
    H --> I[build_llm_input]
    I --> J["docflow.llm"]
    J --> K[consolidate]
    K --> L[DocumentResult]
```

All processor nodes above are `docflow.*` sub-packages under `src/docflow/`; the free
labels (`detect_input_type`, `select_source`, `build_llm_input`, `consolidate`) are
functions of `docflow.workflow`.

Two workflow levels exist and **must not mix**:

- **Documental** (owned by the orchestrator): `PDF → IMAGE → OCR → SOURCE SELECTION → LLM`.
- **Inference** (owned *inside* `procesador-llm-call`): `classify → extract_a/extract_b → compare → validate → consolidate`.

---

## 4. Proposed package layout

The library is a **`src/` layout** whose import name is **`docflow`** (never `src.docflow`):
the package lives at `src/docflow/`, tests mirror it in `tests/`, and the import is always
`docflow.…`. On top of that, `docs/idea/readme.md` §"Estructura del proyecto" fixes the
internal shape: one sub-package per processor, each holding `primitives`, `utils` and
`helpers`, plus a `workflow/` sub-package that is the orchestrator. The same document's
§"Naming" fixes the entry-point names. Both are adopted verbatim, nested under the
`docflow` package:

```
src/docflow/
├── pdf/                 # procesador-pdf
│   ├── primitives/      # low-level PDF ops (Poppler encapsulated here)
│   ├── utils/
│   └── helpers/
├── image/               # procesador-image
│   ├── primitives/      # low-level image ops (OpenCV / Pillow encapsulated here)
│   ├── utils/
│   └── helpers/
├── ocr/                 # procesador-ocr
│   ├── primitives/      # low-level Docling ops (the only OCR engine)
│   ├── utils/
│   └── helpers/
├── llm/                 # procesador-llm-call
│   ├── primitives/      # low-level provider ops (Ollama / vLLM / API)
│   ├── utils/
│   └── helpers/
└── workflow/            # procesador-orquestador — the only workflow-aware component
    └── (public symbols, not files: process_document, process_page, resolve_stage,
         select_source, select_extraction_strategy, build_llm_input,
         invalidate_downstream, resume_document, execute_document_workflow)
tests/                   # mirrors src/docflow, one test module per source module
    fakes/engines/       # in-memory engine doubles, one per processor (§9.7)
```

The `workflow/` block lists **symbols the orchestrator exposes**, not a file tree: they are
functions of the `docflow.workflow` sub-package, distributed across its own modules as the
orchestrator's own layout decides. The same reading applies to `primitives/`, `utils/` and
`helpers/`, which are directories.

Entry-point names (from the idea, `readme.md` §"Naming"):

```text
process_document()  process_page()        → docflow.workflow (orchestrator; reserved names)
process_pdf()       process_pdf_page()    → docflow.pdf
process_image()     process_image_from_page() → docflow.image
process_ocr_image()                       → docflow.ocr
process_llm_request()  process_llm_node() → docflow.llm
```

There is no separate `ports/` / `adapters/` layer in the idea: engines are replaceable
*implementations* behind each processor's public contract (`Request → Processor → Result`),
encapsulated inside that processor's `primitives/`. Swapping an engine (Poppler ↔ another
PDF reader, OpenCV ↔ Pillow, Ollama ↔ vLLM ↔ a hosted API) never changes the contract or
the workflow.

**Contract discipline** (from the idea, `readme.md` §"Contratos entre módulos"):

```text
PDFRequest → procesador-pdf → PDFResult
ImageRequest → procesador-image → ImageResult
OCRRequest → procesador-ocr → OCRResult
LLMInput → procesador-llm-call → LLMResult
DocumentRequest → procesador-orquestador → DocumentResult
```

Each processor writes only inside its own artifact namespace:

```text
PDF   → source/ render/ native_text/ embedded_images/
IMAGE → image/
OCR   → ocr/
LLM   → llm/
```

Inputs are immutable; outputs are published atomically (`.tmp` → validate → `rename`).

---

## 5. Implementation phases

Each phase has entry conditions, deliverables and an exit criterion. Phases run in order;
within a phase, independent processors may proceed in parallel.

### Phase 0 — Foundations: contracts and skeleton

**Entry:** none.

**Deliverables**

- Package skeleton under `src/docflow/` — five sub-packages (`pdf/`, `image/`, `ocr/`,
  `llm/`, `workflow/`), each with `primitives/`, `utils/`, `helpers/`, and the entry-point
  signatures fixed by the idea's §"Naming". Import name is `docflow`; never `src.docflow`.
- The Request/Result contract types, one per processor, as typed dataclasses with no
  defaults on required fields:

  | Request | Result |
  |---|---|
  | `PDFRequest` | `PDFResult` + `PDFPageResult` |
  | `ImageRequest` | `ImageResult` |
  | `OCRRequest` | `OCRResult` |
  | `LLMInput` | `LLMResult` + `LLMNodeResult` |
  | `DocumentRequest` | `DocumentResult` |

- The stage-state vocabulary (`NOT_STARTED`, `READY`, `RUNNING`, `SUCCESS`, `FAILED`,
  `SKIPPED`, `REUSED`, `INVALIDATED`, `PAUSED`) — that list is **closed**: exactly those
  nine states, with no further member added without an explicit plan revision — and the
  three identities: `document_id`, `workflow_run_id`, `processing_key`.
- Tooling: `pyproject.toml` as the single config home for `pytest`, `ruff`, `pylint`,
  `coverage`.
- The **engine-double convention** (§9.7): the path `tests/fakes/engines/`, the rule that
  each processor's in-memory engine fake is injected at the engine call inside its own
  `primitives/` and nowhere higher, and the rule that the fake hands back **native-shaped**
  values (what the engine would return), never our translated type. The convention and the
  directory layout are stated here; the fakes themselves are Phase 1 deliverables
  (`PDF-14`, `IMG-15`, `OCR-14`).

**Exit:** skeleton imports cleanly; one happy-path test per contract round-trips an
in-memory fake end to end; the four QA gates (§7) pass on the skeleton.

---

### Phase 1 — Processors, independently (parallel)

**Entry:** Phase 0 exit met.

**Deliverables** — each processor implemented in isolation behind its own contract, with
its primitives (no workflow decisions inside any of them):

- `procesador-pdf` — split pages, render, extract native text/blocks/images, per-page
  metrics and `TEXT`/`IMAGE`/`MIXED` classification. Engine: **Poppler**, encapsulated in
  `pdf/primitives/`.
- `procesador-image` — load, analyse (dimensions, blur, sharpness, orientation, skew,
  contrast, text coverage), normalize, prepare `ocr_ready`/`vlm_ready` variants.
  Engine: **OpenCV / Pillow**, encapsulated in `image/primitives/`.
- `procesador-ocr` — **Docling** (the only OCR engine), encapsulated in `ocr/primitives/`:
  text, markdown, JSON, tables, layout, reading order; stable intermediate representation;
  deterministic output ordering.
- `procesador-llm-call` — `process_llm_request` for one call: template render, prompt
  build, `request_key`, provider call, parse, schema validation; the internal graph is a
  follow-up inside this same phase.

Each of `pdf`, `image` and `ocr` also ships an **in-memory engine double** (`PDF-14`,
`IMG-15`, `OCR-14`) injected at the engine call inside its own `primitives/`. No test — in
any tier — invokes, imports or asserts the engine itself (§9.7).

**Exit:** each processor has a green happy-path test proving `Request → Result` with real
bytes from a small committed fixture, **with no engine installed**; no processor imports
another processor's module; four QA gates pass.

---

### Phase 2 — Orchestrator: state, reuse, resume

**Entry:** Phase 1 exit met.

**Deliverables**

- `detect_input_type`, `build_execution_plan`, per-stage resolution
  (`EXECUTE` / `REUSE` / `SKIP` / `FORCE` / `WAIT` / `BLOCKED`).
- `processing_key = hash(processor + version + input hashes + normalized options)` and
  the reuse rule: same key + `SUCCESS` + valid artifacts → `REUSE`.
- Durable state: `DocumentContext`, `PageContext`, `StageExecution`; per-page units as
  the self-contained unit of parallelism/recovery.
- `skip` / `force` (with downstream invalidation) / `stop` / `resume` / dry-run.
- Ownership enforcement: each stage writes only its namespace; atomic persistence.

**Exit:** a run interrupted mid-pipeline resumes without re-running completed stages
(proved by a test that observes stage states after a resume); forcing a stage invalidates
its downstream dependents; four QA gates pass.

---

### Phase 3 — Integration: source selection and end-to-end result

**Entry:** Phase 2 exit met.

**Deliverables**

- `select_source()` across `NATIVE_TEXT`, `OCR_TEXT`, `IMAGE`, and their combinations,
  driven by the orchestrator (never by a processor).
- `build_llm_input()` composition and `consolidate_page_result` /
  `consolidate_document_result` (the canonical names — `consolidate_page` /
  `consolidate_document` are accepted aliases of the same seam, not a second
  implementation; see `subplan-orquestador.md` §9.6).
- End-to-end run: a real PDF and a real image each produce a `DocumentResult` through the
  full flow, with the orchestrator as the only component calling processors.

**Exit:** one end-to-end happy-path test per input type (PDF with native text; scanned
image → OCR → LLM) produces a `DocumentResult`; four QA gates pass.

---

### Phase 4 — Hardening

**Entry:** Phase 3 exit met.

**Deliverables**

- Idempotency at both levels (documental + inference subgraph).
- Determinism classes per processor (deterministic / sampled / external) and resume
  decisions based on them.
- Error containment: a failed stage is reported, not propagated as an exception where a
  typed result is the contract.
- Atomic persistence everywhere an artifact is published.
- Full four-gate hygiene and a mutation-falsified invariant test for each non-obvious
  guarantee (see §7).
- The **frontier assertion** that no module under `src/docflow/` imports anything under
  `tests/` (`GEN-19`), and the **engine-double compliance check**: one injection rule across
  the three processors, and a native-shaped fake on every engine seam (`GEN-22`).

**Exit:** all phases' acceptance evidence re-run green; every shortcut carries an explicit
`# TODO: [MVP]` / `# TODO: [RELEASE]` tag.

---

## 6. Task dependency map (summary)

```mermaid
flowchart LR
    P0[Phase 0 contracts/skeleton] --> P1[Phase 1 processors]
    P1 --> P2[Phase 2 orchestrator]
    P2 --> P3[Phase 3 integration]
    P3 --> P4[Phase 4 hardening]
```

| Phase | Modules (`src/docflow/`) |
|---|---|
| 0 | skeleton of all five sub-packages + contracts |
| 1 | `pdf/`, `image/`, `ocr/`, `llm/` (independent, parallel) |
| 2 | `workflow/` (orchestrator) |
| 3 | `workflow/` source selection + end-to-end result |
| 4 | all — hardening |

Within Phase 1 the four processors are independent and parallel; the orchestrator (Phase
2) depends on all of them only through their contracts, not their internals.

---

## 7. Quality gates and Definition of Done

### The four QA gates (all must pass before a task is `done`)

```bash
pytest                  # tests green (src/ on the path via pyproject)
ruff check .            # linter, includes import order
ruff format --check .   # formatter
pylint src tests        # fixme disabled; the rest clean
```

`pytest` with no flags means everything, and everything runs with **no third-party engine
installed**: no test invokes, imports or asserts Poppler, OpenCV, Docling, Ollama or a
provider SDK. The engines are reached only from a processor's own `primitives/`, and only in
production; tests exercise our code through the in-memory engine doubles of §9.7. There is
no marker and no second tier — `pytest` is the gate.

### Rules carried into implementation

- Sorted imports (stdlib → third-party → local). No unused imports. Type hints on all
  signatures. Google-style docstrings. English identifiers, docstrings and comments.
- `ruff format` owns line length; `E501` is ignored.
- A test that guards an invariant **must fail when the invariant is broken** — prove it by
  mutating the source, observing the failure, then restoring green; report both
  observations.
- No silent stand-in (no empty string, `0`, `[]`, or default model/engine/threshold used
  in place of a real answer).
- No domain noun (invoice, field, verdict, pipeline code) in a processor API.
- A concrete engine/library is reached only from a processor's own `primitives/` — never
  from the orchestrator and never across processors.
- No processor imports another processor: the orchestrator is the only component that
  composes them.
- Every exit criterion has an owning task: Phase 0's fake round-trip per contract and
  Phase 4's TODO-tag audit are deliverables, not side effects.
- Naming drift between this plan and a subplan is resolved by recording the canonical name
  in the subplan and the alias here; two names for one seam is a defect.

---

## 8. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Engine/library drift (Poppler, Docling, Pillow, Ollama versions) | Silent output differences | Pin versions; record engine + version in every artifact's metadata; deterministic output ordering. |
| An in-memory engine fake drifts from the engine's real shape | Our translation breaks in production while the suite stays green | Named as an accepted PoC trade-off, not as covered (§9.7, `GEN-17`); the seam is one small module per processor, so a shape change is local and reviewed on the pin bump. |
| Repeating expensive LLM/OCR work | Cost, latency | `processing_key` + reuse rule owned by the orchestrator; resume without re-running. |
| Silent failures (truncated prompt, plausible wrong value) | Wrong result reported as correct | Validation is structural and mandatory; a processor reports, never guesses; no aggregate confidence in place of per-field evidence. |
| Golden set unavailable (circular labelling) | Cannot prove extraction quality | Defer the labelled set; substitute invariant/mutation tests and independent-reader checks (e.g. arithmetic on line items). |
| Scope creep into a full ETL platform | Over-engineering in PoC | Happy path only; tag shortcuts; revisit at MVP/Release gates. |

---

## 9. Resolved decisions

Each was open; each is now **resolved from `docs/idea/`** (the source of truth) plus the
`src/` layout with import name **`docflow`**.

1. **Package layout / layer mapping — RESOLVED.** `src/` layout, import name `docflow`
   (never `src.docflow`); the five processors are sub-packages of `docflow`
   (`docflow.pdf`, `docflow.image`, `docflow.ocr`, `docflow.llm`, `docflow.workflow`),
   and `tests/` mirrors `src/docflow/`. The orchestrator is `docflow/workflow/`. There is
   no `kernels` / `ports` / `adapters` layer.
2. **Package vs. flat modules — RESOLVED.** Each processor is a **sub-package** with
   `primitives/`, `utils/`, `helpers/`, exactly as the idea lists it.
3. **Concrete engines — RESOLVED** by the idea's §"Implementaciones reemplazables":
   PDF → **Poppler**; Image → **OpenCV / Pillow**; OCR → **Docling** (only); LLM →
   **Ollama / vLLM / API**. The first implementation uses one engine per contract; each is
   swappable behind `Request → Processor → Result` without touching the contract.
4. **Language / naming — RESOLVED.** Directories, modules and entry points use the English
   names the idea itself uses (`docflow.pdf`, `docflow.workflow`, `process_document`,
   `process_pdf`, …). The Spanish `procesador-*` names remain only as titles of the
   `docs/idea/` documents.
5. **Consolidation naming — RESOLVED.** Canonical names are
   `consolidate_page_result` / `consolidate_document_result` (as `ORC-17` and
   `subplan-orquestador.md` §9.6 use); the `consolidate_page` / `consolidate_document`
   forms this plan used are accepted aliases of the same seam. §5 above has been
   reconciled to the canonical names.
6. **Stage-state vocabulary — RESOLVED.** The nine states listed in §5 Phase 0
   (`NOT_STARTED`, `READY`, `RUNNING`, `SUCCESS`, `FAILED`, `SKIPPED`, `REUSED`,
   `INVALIDATED`, `PAUSED`) are the closed set; no open ellipsis, no silent alias.
7. **No test crosses into a third party — RESOLVED.** We do not test Poppler, OpenCV,
   Docling or a provider. No test invokes, imports or asserts a third-party engine: its output
   values, its determinism and its version behaviour are its business, not evidence about
   ours. The suite proves **our** code — contracts, translation, builders, validation,
   classification, atomic publication and workflow decisions — and runs whole with no engine
   installed, so `pytest` is the gate and there is no second tier, no marker and no engine
   skip rule.

   **The double, stated once and cited everywhere.** Each of `pdf`, `image` and `ocr` ships an
   **in-memory engine fake**, injected at the engine call inside its own `primitives/` and
   nowhere higher: for `pdf` at the `subprocess.run` call (the fake hands back native
   artifacts plus an exit code and stderr, because Poppler returns no value), for `image` at
   the `image/primitives/` functions (native pixels plus raw score values), for `ocr` at
   `convert_image_with_docling` (Docling's native values) — never at `extract_docling_*`,
   `extract_text_from_page`, `analyze_image` or any other translation seam, because that is
   the half of the module the fake must **exercise** rather than replace. The fake is
   **native-shaped**: it returns what the engine would return, never our translated type. It
   lives under `tests/fakes/engines/`, there is no `if engine is None: use_fake` fallback, and
   nothing under `src/docflow/` imports `tests/`, so a double can never become a production
   fallback. Each processor owns its own engine's fake (`PDF-14`, `IMG-15`, `OCR-14`); only
   *compliance* with this convention is a cross-cutting task (`GEN-22`).

   **What this gives up.** A hand-written fake can drift from the real engine's shape with
   nothing turning red: a shape change on a branch the fake does not model would break
   translation in production while the suite stays green. That is a named, accepted PoC
   trade-off, recorded as a resolved decision in `GEN-17` — not presented as covered.

   `llm` keeps its **scripted** fake (`LLM-03`) deliberately: LLM responses are not
   deterministic for a fixed input, and `LLM-08` needs a scripted sequence (invalid JSON on
   attempt 1, valid on attempt 2).
