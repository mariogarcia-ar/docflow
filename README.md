# docflow — quickstart

> This file is the *developer* quickstart. The *programme* README — architecture, phases,
> acceptance criteria — is [`docs/plan/README.md`](docs/plan/README.md). When the two
> disagree, `docs/plan/` wins; this file is a summary and can lag.

A modular document-processing pipeline. One orchestrator composes four single-responsibility
processors, each behind its own typed contract:

```
INPUT → ORCHESTRATOR → PDF/IMAGE → IMAGE PREP → OCR (when applicable)
      → SOURCE SELECTION → LLM/VLM → VALIDATION → RESULT
```

Three properties are non-negotiable, and most of the rules below exist to protect them:

1. Each processor has a single responsibility and returns one result.
2. Only the orchestrator knows the whole workflow.
3. Valid, expensive work is never repeated needlessly.

---

## Status: Phase 1 complete — all four processors are implemented

Contracts, the stage-state vocabulary, the three identities and the tooling exist, and all four
processors are complete:

- **`docflow.pdf`** (`PDF-01`…`PDF-14`) turns a `PDFRequest` into a `PDFResult` with one
  self-contained unit per page and a per-page artifact tree, published atomically;
- **`docflow.image`** (`IMG-01`…`IMG-15`) turns an `ImageRequest` into an `ImageResult` with a
  `normalized.png` plus independent `ocr_ready.png` / `vlm_ready.png` variants, a measured
  `metadata.json` and a typed failure instead of a partial artifact;
- **`docflow.ocr`** (`OCR-01`…`OCR-14`) turns an `OCRRequest` into an `OCRResult` with
  `text.txt`, `document.md`, a versioned `document.json`, `tables/table_NNN.md`, a measured
  `metadata.json` and a descriptive extraction status, published atomically;
- **`docflow.llm`** (`LLM-01`…`LLM-15`) turns an `LLMInput` into an `LLMResult` — one inference,
  or the fixed linear inference chain — with schema validation, retries that keep every attempt,
  `state.json` + `final_result.json` under the run's namespace, node reuse on restart and per-field
  comparisons.

All four run their whole suites on in-memory doubles — no engine is installed, imported or
reached, and no provider is contacted.

What is left is the orchestrator, whose typed signature still raises:

```python
>>> import docflow.workflow as workflow
>>> workflow.process_document(document_request)
NotImplementedError: process_document is implemented in Phase 2 by ORC-11 and ORC-17
```

That is deliberate. A stub that raised is honest; a stub that returned an empty `DocumentResult`
would be a silent stand-in, which this project forbids at every stage.

| Phase | What | Owner |
|---|---|---|
| **0 — contracts & skeleton** | ✅ **done** | `GEN-01`…`GEN-06` |
| 1 — processors, independently | ✅ `pdf` (`PDF-01`…`PDF-14`) · `image` (`IMG-01`…`IMG-15`) · `ocr` (`OCR-01`…`OCR-14`) · `llm` (`LLM-01`…`LLM-15`) | `LLM-01`…`LLM-15` |
| 2 — orchestrator | state, reuse, resume | `ORC-01`…`ORC-19` |
| 3 — integration | source selection, end to end | `GEN-07`…`GEN-10` |
| 4 — hardening | idempotency, atomicity, close-out | `GEN-11`…`GEN-20` |
| 5 — lab tools | one operator CLI per processor, and a folder twin for each | `SCR-01`…`SCR-18` |

---

## Requirements

- **Python ≥ 3.11** (the shared vocabulary uses `enum.StrEnum`). Verified on 3.13.9.
- No engine and no provider is required to run anything in this repository. Poppler is the PDF
  processor's engine in production, OpenCV the image processor's, Docling the OCR processor's and
  an HTTP provider (Ollama, vLLM or a hosted API) the LLM processor's — each reachable only from
  its own `primitives/` — and every suite drives an in-memory double instead of installing one.

## Setup

```bash
git clone <repo> && cd ibm-docling-ref

python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"        # pytest, pytest-cov, ruff, pylint
```

`pip install` is optional for the gates: `pyproject.toml` puts `src/` on the path, so
`pytest` runs from a clean checkout. Install it when you want to import `docflow` from
anywhere.

Run the test suite:

```bash
pytest
```

## Layout

```
src/docflow/           the library — import name is `docflow`, never `src.docflow`
├── pdf/               procesador-pdf          Poppler, reachable only from pdf/primitives/
├── image/             procesador-image        OpenCV/Pillow, reachable only from image/primitives/
├── ocr/               procesador-ocr          Docling, reachable only from ocr/primitives/
├── llm/               procesador-llm-call     Ollama/vLLM/API, reachable only from llm/primitives/
├── workflow/          procesador-orquestador  the only workflow-aware component
├── states.py          the shared stage-state vocabulary (import this, not docflow.workflow)
└── identities.py      the three identities + the artifact metadata key set

scripts/tools/         operator tools — NOT part of the library, never imported by src/
                       (var/batch_<processor>/ holds a folder run's mirrored tree)
var/                   tool run output (var/tools/<tool>/) — never committed
tests/                 mirrors src/docflow/, one test module per source module
docs/                  the specification. `docs/idea/` explores; `docs/plan/` decides.
```

Every processor sub-package holds `primitives/`, `utils/` and `helpers/`. The `primitives/`
directory is the *only* place an engine may be reached — that is what makes an engine
swappable without touching a contract.

---

## Lab tools (`scripts/tools/`)

Each processor's subplan ends with a thin command-line tool for exercising it by hand. The
convention is in [`docs/plan/README.md` §4.1](docs/plan/README.md) and the design is
[`docs/plan/subplan-scripts.md`](docs/plan/subplan-scripts.md); the short version:

```bash
python scripts/tools/pdf.py split mi.pdf          # → var/tools/pdf/mi-<hash>/page_001/…
python scripts/tools/pdf.py inspect mi.pdf
python scripts/tools/batch_pdf.py cartas/         # → var/batch_pdf/cartas/<stem>/result.json
python scripts/tools/workflow.py plan mi.pdf      # "--dry-run" is what "plan" means
```

There are **two ways to run the bench**, and they take the same commands: **over one file**, where
the input positional names a file and the run writes under `var/tools/<tool>/<stem>-<hash8>/`, or
**over a folder**, where it names a folder and every matching file below it is an input. Both are
written up command by command in
[`scripts/tools/readme.md`](scripts/tools/readme.md) — *Commands over one file* and *Commands over
a folder (batch)* — and the second is not a second implementation of the first: each processor's
two tools call the same methods through one shared layer.

Input is an argument; output goes to `var/tools/<tool>/`, never beside the input and never
into `out/`. Override with `--out`. The **batch** tools take a folder instead of a file, mirror
the tree they walked under `var/batch_<processor>/<folder>/<relative folders>/<stem>/`, file each
input's payload as `result.json` beside whatever the method published, and exit `1` when any input
failed — one bad file does not end the corpus.

**A tool is a caller, not a component.** Three boundaries hold, and the guard test
(`SCR-08`) asserts them, so the CI gate that runs `pytest` enforces them too:

- **Calls, never reimplements.** `split` calls `split_pdf`; it does not shell out to
  `pdfseparate`. Printing a result is a tool's job; producing it is not.
- **The library never imports a tool.** Nothing under `src/docflow/` references `scripts/`
  or `var/`. Deleting `scripts/` leaves the library and its tests untouched.
- **No new seam.** A tool adds no contract, no options type and no behaviour the library
  lacks. A missing operation is a gap in the *processor* — fix it there, not in its tool.

One deliberate asymmetry: **a tool may reach a processor's `primitives/` directly.** That is
the point of a lab bench — `render --dpi 400` drives `render_page_to_image` without a whole
document run, which the orchestrator is forbidden to do (`GEN-19`). A tool is outside both
frontiers. **Except `workflow.py`**, which is bound by the same prohibition the orchestrator
is: it reaches the four processors only through their public contracts.

| Tool | Task | Exposes |
|---|---|---|
| `pdf.py` | `SCR-02` | `inspect`, `split`, `render`, `text`, `blocks`, `images`, `classify`, `run` |
| `batch_pdf.py` | `SCR-12` | the same eight commands over every PDF below a folder (`inspect` when none is stated) |
| `image.py` | `SCR-03` | `info`, `metrics`, `normalize`, `ocr-ready`, `vlm-ready`, `classify`, `run` |
| `batch_image.py` | `SCR-13` | the same seven over every image below a folder (`info` when none is stated) |
| `ocr.py` | `SCR-04` | `run`, `text`, `md`, `json`, `tables`, `blocks`, `metrics` |
| `batch_ocr.py` | `SCR-14` | the same seven over every image below a folder (`text` when none is stated) |
| `llm.py` | `SCR-05` | `call`, `node`, `graph`, `resume`, `status`, `models`, `tokens`, `fake` |
| `batch_llm.py` | `SCR-15` | `call`, `graph`, `node`, `tokens` over every text below a folder — a command is **required**, and `--fake` installs the scripted provider |
| `workflow.py` | `SCR-06` | `run`, `plan`, `status`, `resume`, `force`, `skip`, `stop`, `context` |

Each processor's two tools call one shared layer (`_pdf.py`, `_image.py`, `_ocr.py`, `_llm.py`)
and the four batch tools share the folder frame `_batch.py`, so the batch adds a suffix set, a layer
and a command and nothing else.

All nine now exist under `scripts/tools/`, each built after its processor's own acceptance
evidence went green. Two design notes worth knowing — `ocr.py` has **no** `--engine`
flag, because Docling is fixed and never user-selectable; and `llm.py` requires `--provider`
and `--model` on every inference subcommand, because a default model is exactly the silent
stand-in this project forbids. Its `fake` subcommand is first-class, not a hidden test flag:
the deterministic fake provider is what makes the graph and resume paths demonstrable without
a model or a spent token.

Two subcommands that were drafted here are **dropped**: `image.py crop` has no `crop_region`
to call (`subplan-procesador-image.md` §9.6 defers it) and `ocr.py diff` would compare two
extractions inside the tool, which is a second implementation of the thing under test. A tool
adds no behaviour the library lacks, so neither can exist until the library does.

---

## The contracts

Each processor is `Request → Processor → Result`. Nothing crosses that boundary except the
contract object.

```python
from pathlib import Path

import docflow.pdf as pdf
from docflow.pdf import PDFContext, PDFOptions, PDFRequest

request = PDFRequest(
    pdf_path=Path("documentos/invoice.pdf"),
    output_dir=Path("out/invoice"),
    options=PDFOptions(
        extract_pages=True,
        render=True,
        extract_text=True,
        extract_images=True,
        layout=True,
        dpi=200,
    ),
    context=PDFContext(document_id="invoice-001", workflow_run_id="run-2026-09-22"),
)

result = pdf.process_pdf(request)  # implemented since PDF-01…PDF-14
```

Two conventions hold across all five contracts:

- **Inputs are frozen.** `*Request`, `*Options`, `*Context` and `*Input` are frozen
  dataclasses: a request cannot be mutated after it is built. `*Result` and the
  orchestrator's durable state are mutable, because they are assembled across a run.
- **No field carries a default.** A required field is required. Omitting `dpi` raises
  `TypeError`; it does not silently become 300. The single exception in the whole tree is
  `PDFResult.errors`, and it is registered with its reason in
  `tests/test_skeleton.py::ALLOWED_DEFAULTS`.

| Contract | Processor | Entry points |
|---|---|---|
| `PDFRequest → PDFResult` (+ `PDFPageResult`) | `docflow.pdf` | `process_pdf`, `process_pdf_page` |
| `ImageRequest → ImageResult` | `docflow.image` | `process_image`, `process_image_from_page` |
| `OCRRequest → OCRResult` | `docflow.ocr` | `process_ocr_image` |
| `LLMInput → LLMResult` (+ `LLMNodeResult`) | `docflow.llm` | `process_llm_request`, `process_llm_node` |
| `DocumentRequest → DocumentResult` | `docflow.workflow` | `process_document`, `process_page` |

`process_document` and `process_page` are **reserved for the orchestrator**. No processor may
define them, and there is a test that enforces it.

---

## What works today

The stage-state vocabulary and the three identities are the shared seam; all four processors are
implemented end to end against it.

### The image processor

Analyses one image, measures its quality, normalizes it and prepares the two representations
later stages may request. OpenCV is reached only from `image/primitives/`, and it is reached
through one seam — the module attribute `docflow.image.primitives.cv2`, which the tests patch:

```python
from docflow.image import ImageRequest
from docflow.image.entrypoints import process_image

result = process_image(request)  # ImageRequest → ImageResult, one per image
result.status  # 'success' | 'failed'
result.classification  # 'TEXT_IMAGE' | 'VISUAL_IMAGE' | 'MIXED_IMAGE' | 'LOW_QUALITY'
```

* `request.output_dir` *is* the `image/` namespace: `normalized.png`, the requested variants and
  `metadata.json`. Nothing is written outside it, and an input is never written to.
* **OCR and VLM are never assumed equal.** `prepare_image_for_ocr` produces a single-channel,
  binarized representation; `prepare_image_for_vlm` keeps colour and layout. Each pipeline
  records the transformations it applied, per variant, in `metadata.json`.
* **Absence is stated, never faked.** A decode that fails has no geometry, no readings and no
  classification, so those fields are `None` — never a `0`, a default engine or a default
  classification standing in for an answer nobody observed.
* The engine's two silent habits are the seam's job: `imread` returning `None` becomes a typed
  `DECODE_ERROR`, and `imwrite` returning `False` becomes `WRITE_ERROR`.

### The PDF processor

Inspects, splits and extracts what a PDF natively contains — one self-contained unit per
page — and classifies each page descriptively. Poppler is reached only from
`pdf/primitives/`, and it is reached through one seam:

```python
from docflow.pdf import PDFRequest
from docflow.pdf.entrypoints import process_pdf

result = process_pdf(request)  # PDFRequest → PDFResult, one per page
result.status  # 'success' | 'partial' | 'failed'
result.pages[0].classification  # 'TEXT' | 'IMAGE' | 'MIXED'
```

The classification is data on the page result; turning it into a routing decision is the
orchestrator's job, not this processor's.

* `request.output_dir` is the document directory: `source/document.pdf`, `metadata.json` and
  one `page_NNN/` per page, each with `source/`, `render/`, `native_text/`,
  `embedded_images/` and its own `metadata.json`.
* Every artifact is published through `publish_file` / `publish_text` / `publish_json`:
  `.tmp` → validate → rename, so a reader never sees a half-written file and an interrupted
  run leaves neither a final-named artifact nor a leftover `.tmp`.
* A stage that fails is described, not raised: the page keeps the artifacts that succeeded,
  reports `status = "partial"` and carries the typed failure in `validation.errors`.
* The input PDF is never written to; the reference copy under `source/` is the only copy the
  processor makes.

### The OCR processor

Reads one already-prepared image and returns its textual and structured content. Docling is the
only OCR engine, reached only from `ocr/primitives/`, and it is reached through two seam names
the tests patch — the engine call `docflow.ocr.primitives.convert_image_with_docling` and the
engine namespace `docflow.ocr.primitives.docling`, which is where the version is read:

```python
from docflow.ocr import OCRRequest
from docflow.ocr.entrypoints import process_ocr_image

result = process_ocr_image(request)  # OCRRequest → OCRResult, one per image
result.status  # 'success' | 'failed'
result.validation.status  # 'VALID' | 'EMPTY' | 'LOW_CONTENT' | 'INCOMPLETE' | 'PARSE_ERROR' | 'ERROR'
```

* `request.output_dir` *is* the `ocr/` namespace: `text.txt`, `document.md`, a versioned
  `document.json`, `tables/table_NNN.md` and `metadata.json`. Nothing is written outside it,
  every artifact goes through `.tmp` → rename, and the input image is never written to.
* **Structure is ours, the engine's is not.** Docling's document model is translated into an
  engine-independent `OCRDocument` inside the seam; the blocks are then ordered top-to-bottom and
  left-to-right (the engine's own sequence is the last tie-break), named `block_001`… in that
  order, and merged so a run of body-text items becomes one paragraph.
* **A partial conversion is not a failure.** Docling reports failure twice — by raising and by
  returning a `failure` status — and both are typed: the returned `failure` becomes an
  `OCR_ERROR` and the run stops, while `partial_success` is recorded, the artifacts stand and
  the validation reports `INCOMPLETE`.
* **The option flags decide what is claimed.** `tables: false` claims no table, `layout: false`
  claims no box, `reading_order: false` keeps the engine's sequence instead of deriving one — and
  the page size is always measured, because everything is measured against it.
* **Absence is stated, never faked.** Every product field of `OCRResult` is `None` when the run
  never got that far, while an *empty* extraction reports an empty `text` and `EMPTY` — the
  difference between "never looked" and "looked and found nothing".

```bash
python tests/fixtures/ocr/build_samples.py   # regenerates the two committed fixtures
```

### The LLM processor

Prepares, executes, validates and persists one inference — or the fixed linear inference chain
(`classify → extract_a → extract_b → compare → validate → consolidate`). Ollama, vLLM and any
hosted OpenAI-compatible API are reached only from `llm/primitives/`, and only through seven
primitives the tests replace:

```python
from docflow.llm import process_llm_request

result = process_llm_request(llm_input)  # LLMInput → LLMResult, one call or one chain
result.status  # 'SUCCESS' | 'FAILED'
result.schema_valid  # was the answer what the schema asked for?
result.metadata["request_key"]  # the identity a restart reuses instead of paying again
```

* **The prompt is the one that is hashed.** `calculate_request_key` is
  `hash(provider + model + model_version + rendered_prompt + input_hashes + schema_hash +
  normalized_options)`, and `run_id` / `graph_id` / `node_id` / `attempt_id` are deliberately
  **not parameters of it** — a restart over unchanged inputs reproduces the key, which is what
  makes reuse possible at all.
* **A valid node is never paid for twice.** A node is reused when the key matches, the status is
  `SUCCESS` and the persisted result is valid; the resumed chain below re-ran **four** nodes and
  called the provider for none of the other two.
* **Absence is stated.** `LLMAttempt.raw_response` is `None` when the attempt ended before the
  provider answered, `model_version` is `None` when the caller stated none, and a context window
  nobody stated is *unknown* rather than an overflow.
* **Errors are classified, never swallowed.** Nine kinds, each marked retryable or not; a failed
  attempt and a failed node are typed records inside the result, never exceptions across the
  contract.
* **One provider call per inference.** A run generates and does nothing else: `get_model_info`
  and `get_context_window` are implemented and reachable through `model_query_for`, but a run
  does not probe them, because a probe that failed would have to be swallowed or would fail a
  call that could have worked.
* **The output directory is stated, not guessed.** `LLMInput` carries none, so
  `metadata["output_dir"]` names the `llm/` namespace — `state.json` and `final_result.json`,
  published `.tmp` → rename — and a run given none writes nothing. The asset root
  (`template/` + `schema/`) is stated the same way in `metadata["assets_dir"]`, with no default
  either.

### The stage-state vocabulary

Nine states, one closed set, `str`-serializable. `SKIPPED` and `REUSED` are distinct on
purpose — "we chose not to pay" is not "we did not have to pay", and the reuse rule depends
on telling them apart.

```python
import json

from docflow.states import StageState

StageState.REUSED == "REUSED"  # True — it is a str subclass
json.dumps(StageState.REUSED)  # '"REUSED"'

set(StageState) == {
    "NOT_STARTED",
    "READY",
    "RUNNING",
    "SUCCESS",
    "FAILED",
    "SKIPPED",
    "REUSED",
    "INVALIDATED",
    "PAUSED",
}
```

A processor that only needs to *report* a state imports `docflow.states` and nothing else. It
must never import `docflow.workflow` — deciding what a state means is the orchestrator's job,
and a test enforces the separation.

### The three identities

Reuse, resume and idempotency are only expressible if a run, a document and a unit of work
each have a stable name.

```python
from docflow.identities import ARTIFACT_METADATA_KEYS, PROCESSING_KEY_FORMULA

PROCESSING_KEY_FORMULA
# 'hash(processor + processor_version + input_hashes + normalized_options)'

ARTIFACT_METADATA_KEYS
# ('processor', 'processor_version', 'engine', 'engine_version',
#  'document_id', 'workflow_run_id', 'processing_key')
```

| Identity | Means | Who mints it |
|---|---|---|
| `document_id` | Which document this is. **Never derived from a path** — same bytes, one document. | the caller |
| `workflow_run_id` | Which run this is. | the orchestrator |
| `processing_key` | Which unit of work a cached result belongs to. | `ORC-02` |

The run identity is **absent** from the key formula deliberately: a new run over unchanged
inputs must reproduce the same key, or reuse would never fire. The hashing itself lands in
`ORC-02` (document level) and `LLM-05` (inference node level).

---

## The four QA gates

All four must pass before any task is `done`. Config lives entirely in `pyproject.toml` — do
not add a second `setup.cfg`, `tox.ini` or `pylintrc`.

```bash
pytest                     # 511 passed
ruff check .               # linter, includes import order
ruff format --check .      # formatter — this owns line length, not E501
pylint src tests           # 10.00/10
```

The whole suite runs with **no engine installed and no engine reached**: Poppler, OpenCV,
Docling and the provider SDKs are touched only in production, and every processor's tests drive
an in-memory double injected at the engine call. The evidence is reproducible — with the
binaries off the `PATH` (which is the PDF processor's engine gone), the suite is still green:

```bash
env -i PATH=/usr/bin:/bin "$(which python)" -m pytest -q   # 511 passed
```

Two of those carry an intentional carve-out, each with its reason recorded in
`pyproject.toml`:

- **`docs/` is excluded from Ruff.** It holds the frozen specification, whose fenced Python
  blocks are not source. A formatter that rewrites a frozen artifact is worse than one that
  skips it.
- **`fixme` is disabled in Pylint.** It flags the `# TODO: [MVP]` / `# TODO: [RELEASE]`
  markers this project requires. The markers are the deliverable, not the debt.

---

## Rules that will bite you

These are the ones that fail loudly in review, and most have a test behind them.

**A test that guards an invariant must fail when the invariant is broken.** Prove it by
mutating the source, observing the red, restoring, and reporting both observations. A test
that only passes when the code is correct proves nothing. The Phase 0 mutations:

| Mutation | Observed failure |
|---|---|
| Append a tenth state to `StageState` | `test_vocabulary_has_exactly_the_documented_members` |
| Alias `SKIPPED = "REUSED"` | 5 tests, incl. `test_a_skipped_stage_is_not_reported_as_reused` |
| `docflow/pdf/__init__.py` imports `docflow.workflow` | `test_importing_one_processor_does_not_import_another` |
| `docflow/image/__init__.py` imports `PIL` | `test_the_five_sub_packages_import_in_a_clean_interpreter` |

And the Phase 1 PDF invariants, in the four-field shape `docs/plan/README.md` §7 fixes
(`GEN-16` audits the set):

| Invariant | Mutation | Observed failure | Restored green |
|---|---|---|---|
| Page completeness — every page yields one result and one directory (`test_every_page_yields_exactly_one_result_and_one_directory`) | `process_pdf`: `range(1, document.page_count + 1)` → `range(1, document.page_count)` (`src/docflow/pdf/entrypoints.py`) | `pytest tests/pdf/test_entrypoints.py::test_every_page_yields_exactly_one_result_and_one_directory` → 1 failed: `E assert [1, 2] == [1, 2, 3]` | `pytest tests/pdf` → 79 passed |
| Immutable input — the input PDF's SHA-256 is unchanged (`test_the_input_document_is_never_modified`) | `extract_page`: publish to `pdf_path` instead of `output_path` (`src/docflow/pdf/primitives/__init__.py`) | `pytest tests/pdf/test_entrypoints.py::test_the_input_document_is_never_modified` → 1 failed: `E AssertionError: assert '890131db9f9c…' == '3cf04b080451…'` | builder re-run reproduces the fixture byte for byte (`3cf04b0804518207…`), then `pytest tests/pdf` → 79 passed |
| Classification vocabulary & purity — three literals, from the metrics alone (`test_the_vocabulary_is_closed_and_depends_on_the_metrics_alone`) | (a) `classify_pdf_page` returns `"OCR"`; (b) the signature grows a `force_text` flag (`src/docflow/pdf/primitives/composition.py`) | (a) 1 failed: `E assert ['IMAGE', 'IM…', 'OCR', 'IMAGE'] == ['IMAGE', 'IM…', 'MIXED', 'IMAGE']`; (b) 1 failed: `E assert ['metrics', 'force_text'] == ['metrics']` | `pytest tests/pdf` → 79 passed after each restore |
| No silent failure — a stage that cannot publish is reported (`test_a_page_metadata_that_cannot_be_published_is_reported`) | `_build_page_result`: hand the validation record `list(failures)` instead of the live list, dropping the metadata publication failure (`src/docflow/pdf/entrypoints.py`) | `pytest tests/pdf/test_entrypoints.py::test_a_page_metadata_that_cannot_be_published_is_reported` → 1 failed: `E AssertionError: assert 'success' == 'partial'` — the page claimed success while its `metadata.json` was never published | `pytest tests/pdf` → 80 passed |

And the Phase 1 image invariants, same four-field shape (`IMG-13`):

| Invariant | Mutation | Observed failure | Restored green |
|---|---|---|---|
| Immutable input — the source image's SHA-256 and mtime are unchanged (`tests/image/test_entrypoints.py::test_the_input_image_is_never_modified`) | `_prepare_representations`: send the normalized pipeline to `request.image_path` instead of `request.output_dir / name` (`src/docflow/image/entrypoints.py`) | `pytest tests/image/test_entrypoints.py::test_the_input_image_is_never_modified` → 1 failed: `E AssertionError: assert 'ef0a84c550e6…' == 'd0023a05f4f0…'` — the run had overwritten its own input | `git checkout -- src/docflow/image/entrypoints.py tests/fixtures/image/color_layout.png`, then `pytest tests/image` → 91 passed; re-running `python tests/fixtures/image/build_samples.py` reproduced `d0023a05f4f0…` byte for byte |
| OCR variant ≠ VLM variant — two files, two pipelines, two recorded transformation lists (`tests/image/test_entrypoints.py::test_the_ocr_and_vlm_variants_are_never_one_artifact`) | `_prepare_representations`: pass `OCR_READY_NAME` as the VLM pipeline's destination (`src/docflow/image/entrypoints.py`) | `pytest tests/image/test_entrypoints.py::test_the_ocr_and_vlm_variants_are_never_one_artifact` → 1 failed: `E AssertionError: assert 'ocr_ready.png' == 'vlm_ready.png'` — one artifact stood in for both representations | `git checkout -- src/docflow/image/entrypoints.py`, then `pytest tests/image/test_entrypoints.py` → 19 passed |
| Namespace ownership — every artifact, `metadata.json` included, resolves under `image/` (`tests/image/test_entrypoints.py::test_every_artifact_the_result_declares_lives_under_the_image_namespace`) | `_publish_metadata`: publish to `request.output_dir.parent / METADATA_NAME` (`src/docflow/image/entrypoints.py`) | `pytest tests/image/test_entrypoints.py::test_every_artifact_the_result_declares_lives_under_the_image_namespace` → 1 failed: `E AssertionError: assert {…normalized.png, ocr_ready.png, vlm_ready.png} == {…, metadata.json}` | `git checkout -- src/docflow/image/entrypoints.py`, then `pytest -q` → 228 passed |

And the Phase 1 OCR invariants, same four-field shape (`OCR-13`). The mutations were applied to
files that were brand new in the same session, so each was restored by re-applying the exact
inverse edit rather than by `git checkout`, and the restore was re-measured:

| Invariant | Mutation | Observed failure | Restored green |
|---|---|---|---|
| Deterministic ordering — blocks are sorted into reading order and named after the sort (`tests/ocr/test_entrypoints.py::test_the_two_runs_of_the_same_input_produce_the_same_functional_content`) | `preserve_reading_order`: `merge_ocr_blocks(sorted(blocks, key=…))` → `merge_ocr_blocks(list(blocks))`, i.e. the engine's own iteration order (`src/docflow/ocr/primitives/composition.py`) | `pytest tests/ocr/test_entrypoints.py -q` → 3 failed: the invariant test with `E AssertionError: assert ['block_003', …, 'block_001'] == ['block_001', …, 'block_003']` — the adversarial double's order survived unsorted | inverse edit, then `pytest tests/ocr` → 116 passed |
| No run-time stamps in functional content — `text.txt`, `document.md`, `document.json` and `tables/*` hold none (`tests/ocr/test_entrypoints.py::test_no_functional_artifact_carries_a_run_time_stamp`) | `process_ocr_image`: `structured = asdict(extraction.document)` → `{**asdict(…), "built_at": datetime.now().isoformat()}` (`src/docflow/ocr/entrypoints.py`) | `pytest tests/ocr/test_entrypoints.py -q` → 2 failed: the invariant test with `E AssertionError: PosixPath('…/ocr/document.json')` (the stamp was found in the file), and the determinism test because two runs then differ | inverse edit, then `pytest tests/ocr` → 117 passed |
| Atomic publication — a failed publish leaves neither a `.tmp` file nor a final-named artifact (`tests/ocr/test_entrypoints.py::test_a_publication_that_fails_leaves_neither_a_tmp_file_nor_an_artifact`) | `_publish`: write straight to `destination` instead of the `.tmp` sibling followed by `os.replace` (`src/docflow/ocr/primitives/publication.py`) | `pytest tests/ocr -q` → 2 failed: the invariant test with `E AssertionError: assert 'success' == 'failed'` (nothing was refused, so the run claimed success), and the publication unit test | inverse edit, then `pytest -q` → 339 passed |

And the Phase 1 LLM invariants, same four-field shape (`LLM-13`). The mutations were applied to
files that were brand new in the same session, so each was restored by re-applying the exact
inverse edit (verified with `git diff` showing no difference from the staged file) and the restore
was re-measured:

| Invariant | Mutation | Observed failure | Restored green |
|---|---|---|---|
| No re-execution of a valid call on restart — a `SUCCESS` node under a matching `request_key` is reused (`tests/llm/test_entrypoints.py::test_a_resumed_chain_reuses_every_valid_node_and_calls_the_provider_for_none`) | `is_node_reusable`: `return validate_cached_result(node_result) and node_result.request_key == request_key` → `return False` (`src/docflow/llm/primitives/composition.py`) | `pytest tests/llm/test_entrypoints.py -q -k "resumed_chain_reuses or interrupted_by_a_failed_node"` → 2 failed: the first with `E AssertionError: assert {'classify': 'EXECUTE', …} == {'classify': 'REUSE', …}`, and the second with `{'classify': 'EXECUTE'} != {'classify': 'REUSE'}`, `{'extract_a': 'EXECUTE'} != {'extract_a': 'REUSE'}` — the provider was called again for nodes that were already paid for | inverse edit, then `pytest tests/llm` → 180 passed |
| `request_key` determinism and independence from run identity — two runs differing only in `run_id` and output directory share one key (`tests/llm/test_entrypoints.py::test_the_same_logical_request_keys_the_same_across_two_runs`) | the run identity put into the key material: `_plan_call`, `options=options` → `options={**options, "run_identity": str(request.metadata.get("run_id"))}` (`src/docflow/llm/entrypoints.py`) | `pytest tests/llm/test_entrypoints.py::test_the_same_logical_request_keys_the_same_across_two_runs -q` → 1 failed: `E AssertionError: assert '81757c69c3c2…a06a23e8' == 'e7ca86507fa7…3aa3959c'` — the two runs produced different keys, so nothing could ever be reused | inverse edit, then `pytest tests/llm/test_entrypoints.py::test_the_same_logical_request_keys_the_same_across_two_runs -q` → 1 passed |

And the Phase 2 orchestrator invariants, same four-field shape (`ORC-19`). The mutations were
applied to files that were brand new in the same session, so each was restored by re-applying the
exact inverse edit; `git diff` on the mutated file was empty after every restore, and the restore
was re-measured:

| Invariant | Mutation | Observed failure | Restored green |
|---|---|---|---|
| Resume reuses, never re-runs, a completed stage (`tests/workflow/test_entrypoints.py::test_resume_does_not_re_run_completed_stages`) | `resolve_stage`'s reuse branch returns the action `"EXECUTE"` instead of `"REUSE"` (`src/docflow/workflow/resolution.py`) | `pytest tests/workflow/test_entrypoints.py::test_resume_does_not_re_run_completed_stages -q` → 1 failed: `E AssertionError: assert <StageState.SUCCESS: 'SUCCESS'> is <StageState.REUSED: 'REUSED'>` — the resumed run paid for a stage that was already done | inverse edit (`git diff` empty), then `pytest tests/workflow/test_entrypoints.py` → 15 passed |
| Force invalidates its downstream dependents (`tests/workflow/test_entrypoints.py::test_forcing_a_stage_invalidates_its_downstream_dependents`) | `apply_forces`: `invalidated.extend(invalidate_downstream(…))` → `invalidated.extend(())` (`src/docflow/workflow/planning.py`) | `pytest tests/workflow/test_entrypoints.py::test_forcing_a_stage_invalidates_its_downstream_dependents -q` → 1 failed: `E assert []` — forcing OCR left the LLM stage holding its stale result and no `INVALIDATED` decision was recorded | inverse edit, then `pytest tests/workflow/test_entrypoints.py` → 15 passed |
| Reuse needs a `processing_key` match, not mere file existence (`tests/workflow/test_entrypoints.py::test_reuse_requires_a_processing_key_match_not_mere_file_existence`) | `is_stage_reusable`: `return stage.status in _REUSABLE_STATES and stage.processing_key == current_processing_key and validate_stage_outputs(stage)` → `return validate_stage_outputs(stage)` (`src/docflow/workflow/reuse.py`) | `pytest tests/workflow/test_entrypoints.py::test_reuse_requires_a_processing_key_match_not_mere_file_existence -q` → 1 failed: `E assert 0 == (0 + 1)` — with the artifacts still on disk, a changed image option reused the old result | inverse edit, then `pytest tests/workflow/test_entrypoints.py` → 15 passed |

And the Phase 5 lab-tool invariants, same four-field shape (`SCR-08`). The mutations were applied
to files that were brand new in the same session, so each was restored by re-applying the exact
inverse edit, and the restore was re-measured:

| Invariant | Mutation | Observed failure | Restored green |
|---|---|---|---|
| A tool adds no behaviour — it calls a processor, it never reimplements one (`tests/test_lab_tools.py::test_no_tool_names_an_engine_or_a_provider_sdk[pdf]`) | `pdf.py`'s `_cmd_render` shelled out to the engine's own binary with `subprocess.run(["pdftoppm", …])` instead of calling `render_page_to_image` (`scripts/tools/pdf.py`) | `pytest "tests/test_lab_tools.py::test_no_tool_names_an_engine_or_a_provider_sdk[pdf]" -q` → 1 failed: `E AssertionError: pdf.py names an engine or an SDK: ['pdftoppm', 'subprocess']` | inverse edit, then `pytest tests/test_lab_tools.py` → 40 passed |
| The library never imports a tool (`tests/test_lab_tools.py::test_no_module_under_src_mentions_the_tools_or_their_output`) | `import scripts.tools._cli` added to `src/docflow/pdf/entrypoints.py` | `pytest tests/test_lab_tools.py::test_no_module_under_src_mentions_the_tools_or_their_output -q` → 1 failed: `E AssertionError: a source module reached for the bench: ['src/docflow/pdf/entrypoints.py']` | inverse edit, then `pytest tests/test_lab_tools.py` → 40 passed |
| `workflow.py` carries the orchestrator's frontier — it reaches no `primitives/` module (`tests/test_lab_tools.py::test_workflow_tool_imports_no_primitives_module`) | `from docflow.ocr.primitives import convert_image_with_docling` added to `scripts/tools/workflow.py` | `pytest tests/test_lab_tools.py::test_workflow_tool_imports_no_primitives_module -q` → 1 failed: `E AssertionError: workflow.py reached a processor's internals: ['line 41: docflow.ocr.primitives']` | inverse edit, then `pytest tests/test_lab_tools.py` → 40 passed |
| No default model — a default is the silent stand-in the project forbids (`tests/test_lab_tools.py::test_llm_call_without_a_model_is_a_usage_error`) | `llm.py`'s `--model` given `default="llama3.1"` (`scripts/tools/llm.py`) | `pytest tests/test_lab_tools.py::test_llm_call_without_a_model_is_a_usage_error -q` → 1 failed: `Failed: DID NOT RAISE SystemExit`, with the captured run showing `model: llama3.1` — the request was built from a model nobody stated | inverse edit, then `pytest tests/test_lab_tools.py` → 40 passed |

Wave 5's four records, same shape (`SCR-12`…`SCR-15`). The two frame invariants were the two
mutations that found real defects: the first was applied to `_batch.run_one`, and the second to
`_ocr._conversion`, each after the defect had been fixed and before the fix was kept:

| Invariant | Mutation | Observed failure | Restored green |
|---|---|---|---|
| A contract that *returned* a failed status is reported as `FAILED`, not as `ok` (`tests/test_lab_tools.py::test_batch_ocr_reports_a_returned_failure_as_a_failure`) | the frame's per-input line forced back to `print(f"{input_path.name}: ok -> {root}")` (`scripts/tools/_batch.py`) | `pytest tests/test_lab_tools.py -q -k returned_failure` → 1 failed: `E assert ': FAILED ->' in 'a.png: ok -> …'` — the run printed `ok` above `succeeded: 0 · failed: 1` | inverse edit, then `pytest tests/test_lab_tools.py` → 95 passed |
| A returned failure's own typed record is shown, not left in `result.json` (`tests/test_lab_tools.py::test_batch_ocr_reports_a_returned_failure_as_a_failure`) | `if failed and failures: _cli.print_error(failures)` dropped from `run_one` (`scripts/tools/_batch.py`) | `pytest tests/test_lab_tools.py -q -k returned_failure` → 1 failed: `E assert 'ERROR OCR_ERROR:' in 'a.png: FAILED -> …'` — no exception had carried the record, so nothing named the failure | inverse edit, then `pytest tests/test_lab_tools.py` → 95 passed |
| A default command is stated in the header, never silent (`tests/test_lab_tools.py::test_batch_ocr_mirrors_the_folder_it_walked`) | `default=default` → `default=False` in `batch_ocr.py` | `pytest tests/test_lab_tools.py -q -k batch_ocr` → 1 failed: no `command: text (default, none stated)` in the header | inverse edit, then `pytest tests/test_lab_tools.py` → 95 passed |
| An input the engine refuses is one input's failure, not the run's (`tests/test_lab_tools.py::test_batch_ocr_types_an_engine_throw_and_keeps_going`) | the `try/except` typing removed from `_ocr._conversion`, calling the engine call directly (`scripts/tools/_ocr.py`) | `pytest tests/test_lab_tools.py -q -k engine_throw` → 1 failed: the engine's own `ValueError` escaped the batch and ended the corpus at the first bad input | inverse edit, then `pytest tests/test_lab_tools.py` → 95 passed |
| A layer states its processor's inputs, and both of its tools read that one statement (`tests/test_lab_tools.py::test_batch_pdf_mirrors_the_folder_it_walked`) | `_pdf.SUFFIXES` widened to `(".pdf", ".txt")` — the same edit as a second, drifting copy of the set in the tool (`scripts/tools/_pdf.py`) | `pytest tests/test_lab_tools.py -q -k batch_pdf_mirrors` → 1 failed: `E assert ['notes', 'sub1/a', 'sub2/deeper/b'] == ['sub1/a', 'sub2/deeper/b']` — the run walked a file its processor cannot read | inverse edit, then `pytest tests/test_lab_tools.py` → 95 passed |

**Never a silent stand-in.** No empty string, no `0`, no `[]`, no `None`-without-reason, and no
default engine or threshold used in place of a real answer.
**No processor imports another processor.** The orchestrator is the only component that
composes them, and only through contracts.

**No adapter reached from a port — there is no `ports/` / `adapters/` layer at all.** §9.1 of
the plan removes it. Engines are replaceable *implementations* behind each processor's public
contract, encapsulated in that processor's `primitives/`. Swapping Poppler for another PDF
reader, or OpenCV for Pillow, or Ollama for vLLM, changes only `primitives/` — never the
contract, never the workflow.

**No `primitives/` reached from the orchestrator.** A concrete engine is touched from its own
processor's `primitives/` and nowhere else.

**No domain noun in a processor API.** No invoice, field, verdict or pipeline code. A
`TEXT`/`IMAGE`/`MIXED` classification is *data*; only the orchestrator turns it into a decision.

**No aggregate confidence score** in place of the per-field verdict vector.

**Language.** Everything — code, comments, docstrings, logs, exceptions, docs — is English,
regardless of the input language. The Spanish `procesador-*` names survive only as titles of
`docs/idea/` documents.

**Never commit:** the corpus (`documentos/`), run output (`out/`, `var/`, `work/`), `.env`, and
coverage/cache/build directories. `.gitignore` is the authority.

---

## Where the specification lives

`docs/plan/` decides; `docs/idea/` is the exploration that led there. **Where they disagree,
`docs/plan/` wins.** Both are read-only for code tasks — a change to a frozen artifact
re-opens the gate that froze it.

| File | Read it for |
|---|---|
| `docs/plan/README.md` | the general plan: architecture, package layout, phases, quality gates |
| `docs/plan/subplan-*.md` | one per processor: contracts, design, acceptance criteria, test plan |
| `docs/plan/issues/wbs-*.md` | task-level decomposition with effort and dependencies |
| `docs/plan/issues/wbs-general.md` | the programme view, critical path, phase map |
| `docs/idea/*.md` | the original exploration. Names and layout come from here |

Start with `docs/plan/README.md` §5 (phases) and §7 (gates), then the subplan for the
processor you are touching.

---

## Two known divergences from the plan

Recorded here so the first `GEN-17` reconciliation does not have to rediscover them.

1. **The stage-state set is contradictory in the artifacts.** `docs/plan/README.md` §5 and §9.6
   fix **nine** states and call the list closed; `subplan-orquestador.md` §3.1 lists **twelve**
   (adding `PARTIAL`, `CANCELLED`, `REVIEW_REQUIRED`) and `ORC-01` repeats them. Phase 0 ships
   the nine. `ORC-01` will need the other three — that is a plan revision, not something to
   settle in code.

2. **`.gitignore` has no owning issue.** It is not in the scope of `GEN-01` or `GEN-05`; only
   `.github/copilot-instructions.md` mentions it. Following the WBS literally would leave the
   first `git add .` picking up `.DS_Store` and the cache directories.

3. **Two output conventions now overlap.** `.gitignore` and `.github/copilot-instructions.md`
   designate `out/` (product) and `work/` (lab bench). The lab tools introduce `var/`, which is
   the same idea under a different name. `var/` is now the documented default for
   `scripts/tools/`; `work/` is left in `.gitignore` as legacy rather than silently deleted,
   and the reconciliation of the three belongs to `GEN-17`.

Three smaller ones were resolved while writing the contracts, each noted in the module
docstring where it lives: `DocumentResult.processing_key` (required by `GEN-04` but absent from
`ORC-01`'s field list), `PDFResult.errors` (needed for the documental `PARTIAL` case), and the
OCR type names (`OCRContext` and `OCRDocument` are canonical; the subplan's `Context` and
`context.document` are aliases).

4. **The PDF failure vocabulary now follows the subplan, so the engine dossier is stale.**
   `PDFErrorType` carried eleven names of its own (`MISSING_FILE`, `PAGE_OUT_OF_RANGE`,
   `WRITE_ERROR`); `PDF-01` aligned it to the subplan's ten. The dossier's engine-signal table
   (`docs/3party/poppler.md` §G) is written against the old right-hand column and its
   "divergence to report" note no longer applies: out-of-range and write failures now land on
   `INVALID_INPUT` and `IO_ERROR`. The left column — the signals themselves — is unchanged.

5. **Contract changes Phase 1 needed.** `PDFMetadata.engine_version` and
   `PDFPageMetadata.engine_version` are `str | None`: a pre-engine failure (a missing,
   unsupported, encrypted or corrupt document) reaches no engine call, so there is no version
   to record and `None` says exactly that. `PDFError` gained no new kind, and the per-page
   failures live in `PDFPageValidation.errors` — the page result has no `errors` field of its
   own, on purpose: a stage failure is what the page's validation reports.

6. **Recorded in the code as `# TODO: [MVP]`, to be reconciled when their owner lands.**
   `process_pdf_page` re-inspects the document for the page's geometry, because the frozen
   entry-point signature cannot carry it and a page has to work standalone (one extra
   `pdfinfo` call per page inside a document run). `processing_key` is computed by the
   processor from the documented formula, because every artifact `metadata.json` must record
   it while its owner `ORC-02` is Phase 2. `merge_pdfs` is implemented and tested but composed
   nowhere, as the plan defers it.

7. **The PDF fixtures are committed under `tests/fixtures/pdf/`, with their builder.**
   The subplan writes `fixtures/pdf_sample_*.pdf`; the repository's fixture root is
   `tests/fixtures/`, so the samples live one level down and
   `tests/fixtures/pdf/build_samples.py` (standard library only, deterministic) regenerates
   them byte for byte. `tests/fixtures/manifest.json` predates them and is now stale — it has
   no builder in the tree to re-run, so it needs its owner rather than a hand edit.

8. **The Phase 5 lab tools now have their own ID range — resolved.** `docs/feedback/no-tests-on-third-parties.md`
   repurposed `PDF-14`, `IMG-15` and `OCR-14` as the in-memory doubles of `pdf`, `image` and
   `ocr`, and `GEN-21` is the CI gate, so the Phase 5 row's four borrowed IDs were stale.
   [`docs/plan/subplan-scripts.md`](docs/plan/subplan-scripts.md) allocates `SCR-01`…`SCR-10`
   and the row above now cites them; no ID was renumbered. The batch revision of the same
   subplan appends `SCR-11`…`SCR-18` (`_pdf.py`, `_batch.py`, the three remaining pairs, the
   bench readme, the hand run and the revision itself), again without renumbering.

9. **The OCR result states absence in its typing, not in empty values.**
   `OCRResult`'s nine product fields — `text`, `markdown`, `structured_document`, `tables`,
   `blocks`, `layout`, `reading_order`, `metrics`, `artifacts` — and `metadata` are `X | None`.
   The rule the typing carries: `None` means *the run never produced it*, an empty value means
   *produced and empty*. A blank page legitimately extracts empty text and reports `EMPTY`,
   while a run that failed before the engine was reached has no text at all; without the
   distinction, a `0` or an `""` would read as a measured answer. This is the `image` decision
   (`IMG-01`) applied to the whole result, and the subplan's §3.1 field list does not carry it.

10. **Two OCR primitives are named by the WBS but absent from the subplan's closed §3.4 list.**
    `OCR-07` and `OCR-08` name `process_tables` and `analyze_ocr_result`, and assembling the
    `OCRDocument` from the five `extract_docling_*` outputs needs a sixth name, `build_ocr_document`
    — the §3.4 list stops at 25 entries (three pipeline/config, one engine call, five extractors,
    four text/Markdown, two table, two layout, two metadata, three validation, three file). Nothing
    was added beyond what those rows require: no `enable_*` / `should_enable_*` predicate, no second
    export path beside the `OCR-06` builders and no `count_*` helper beside `OCRMetrics` exist. The
    same pass added `conversion_failure`, which owns the half of Docling's failure surface that
    *returns* a `failure` status instead of raising (dossier §K, defect 5) — without it a refused
    conversion would read as a successful extraction of an empty page.

11. **The OCR seam patches two names, not one.** The plan fixes the injection point as
    `convert_image_with_docling`; the version also has to be readable with no engine installed, so
    the double installs itself at `docflow.ocr.primitives.docling` as well and the seam reads
    `__version__` from there. It is the same lazy-resolution rule the image seam follows for `cv2`
    (`README.md` §9.7 of the plan), applied to the one other thing this processor reads off the
    engine.

12. **The LLM failure vocabulary and the attempt record are Phase 1 additions.**
    `subplan-procesador-llm-call.md` §3 states nine failure kinds and marks each retryable or not,
    but its §3.1 field lists carry no error record. `LLMErrorType` (the nine kinds, guarded by a
    test that restates them) and `LLMError` were therefore added to `contracts.py`, `LLMAttempt`
    gained `error: LLMError | None` instead of a bare message, and both `LLMResult` and
    `LLMNodeResult` gained `errors: list[LLMError]`. Nothing was *removed*: `validation_errors`
    stays what it was — why the answer did not satisfy the schema — which is a different question
    from what went wrong.

13. **`LLMMetadata`'s three missing inputs live in `metadata`.** `LLMInput` has no output
    directory, no asset root and no run identity, and none of the three may be guessed: the run
    directory is `metadata["output_dir"]`, the template/schema root is `metadata["assets_dir"]`,
    the run identity is `metadata["run_id"]` and the model version fallback is
    `metadata["model_version"]`. A request that states none of them is reported as a
    `DEPENDENCY_ERROR`, and a run with no output directory writes nothing — rather than to a
    guessed place. Reconciling this with the orchestrator's own identity scheme is `ORC-02`'s.

14. **An LLM run makes exactly one provider call per inference.** Subplan §9 decision 5 says
    `model_version` comes from the provider's `get_model_info` "when available". A run does not
    *probe* for it: the inventory primitives are implemented and reachable through
    `docflow.llm.model_query_for`, but the version comes from `metadata["model_version"]` and the
    context window from `options["context_window"]`, because a probe that failed would have to be
    either swallowed or turned into a failure of a call that could have succeeded. Tagged
    `# TODO: [MVP]` in the entry point.

15. **`LLMAttempt.raw_response` is `str | None`.** An attempt that ended before the provider
    answered has no raw response, and an empty string would read as an answer that was empty.
    This is the `image`/`ocr` "absence is stated" decision applied to the attempt record, which
    the subplan's §3.1 does not spell out.

---

## Next step

Phase 1 is complete: `pdf`, `image`, `ocr` and `llm` each run their own suite with no engine
installed and no provider reached. Phase 2 (the orchestrator, `ORC-01`…`ORC-19`) starts next,
against `docs/plan/subplan-orquestador.md`, with `docflow.workflow` as the only workflow-aware
component.

What the orchestrator inherits, and what it must not re-invent:

- **The processors are callable and typed.** `process_pdf`, `process_image`, `process_ocr_image`
  and `process_llm_request` each take one request and return one result;
  `process_llm_node(node_config, state)` and `execute_llm_graph(request)` are the chain entry
  points, and per-node artifacts are deferred to the MVP gate (`# TODO: [MVP]`).
- **The identity work is half done.** `processing_key` is computed *inside* `pdf`, `image`, `ocr`
  and `llm` from the documented formula, tagged `# TODO: [MVP]`, because every artifact
  `metadata.json` must carry it while its owner `ORC-02` is Phase 2. That is the first
  reconciliation.
- **The reuse rule now exists twice, deliberately.** The orchestrator's is a hash check at stage
  level; the LLM processor's is a schema-and-artifact check at node level. The subplan §3 says in
  as many words why they must stay separate, and `LLMPrimitiveError` is *not* a vocabulary the
  orchestrator should catch: it never crosses a contract.
- **Four processors, four doubles, one convention.** `tests/fakes/engines/` holds the Poppler,
  OpenCV, Docling and provider doubles; `fake_provider.py` is the only *scripted* one, and
  `tests/fakes/engines/convention.py` checks the two seams that reach an engine namespace.

`pdf` remains the worked example for layout and tests, `ocr` for translating a rich engine and
for a double that hands its items back in an adversarial order, and `llm` adds two: a **scripted**
fake, and a chain whose resume path is proven by a provider call counter that stays at zero.
