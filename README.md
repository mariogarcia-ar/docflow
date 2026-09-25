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

## Status: Phase 1 — the PDF processor is implemented

Contracts, the stage-state vocabulary, the three identities and the tooling exist, and
**`docflow.pdf` is complete** (`PDF-01`…`PDF-14`): it turns a `PDFRequest` into a
`PDFResult` with one self-contained unit per page, publishes the artifact tree atomically,
and runs its whole suite on an in-memory Poppler double — no engine is installed or reached.

The other three processors are still typed signatures whose bodies raise:

```python
>>> import docflow.image as image
>>> image.process_image(request)
NotImplementedError: process_image is implemented in Phase 1 by IMG-12
```

That is deliberate. A stub that raised is honest; a stub that returned an empty `ImageResult`
would be a silent stand-in, which this project forbids at every stage.

| Phase | What | Owner |
|---|---|---|
| **0 — contracts & skeleton** | ✅ **done** | `GEN-01`…`GEN-06` |
| 1 — processors, independently | ✅ `pdf` (`PDF-01`…`PDF-14`) · `image`, `ocr`, `llm` | `IMG-01`…`IMG-14`, `OCR-01`…`OCR-13`, `LLM-01`…`LLM-15` |
| 2 — orchestrator | state, reuse, resume | `ORC-01`…`ORC-19` |
| 3 — integration | source selection, end to end | `GEN-07`…`GEN-10` |
| 4 — hardening | idempotency, atomicity, close-out | `GEN-11`…`GEN-20` || 5 — lab tools | one operator CLI per processor | `GEN-21`, `PDF-14`, `IMG-15`, `OCR-14`, `LLM-16`, `ORC-20` |
---

## Requirements

- **Python ≥ 3.11** (the shared vocabulary uses `enum.StrEnum`). Verified on 3.13.9.
- No engine is required to run anything in this repository. Poppler is the PDF processor's
  engine in production, reachable only from `pdf/primitives/`, and the suite drives it through
  an in-memory double instead of installing it.

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
convention is in [`docs/plan/README.md` §4.1](docs/plan/README.md); the short version:

```bash
python scripts/tools/pdf.py split mi.pdf          # → var/tools/pdf/mi-<hash>/page_001/…
python scripts/tools/pdf.py inspect mi.pdf
python scripts/tools/workflow.py plan mi.pdf --dry-run
```

Input is an argument; output goes to `var/tools/<tool>/`, never beside the input and never
into `out/`. Override with `--out`.

**A tool is a caller, not a component.** Three boundaries hold, and `GEN-21` asserts them:

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
| `pdf.py` | `PDF-14` | `inspect`, `split`, `render`, `text`, `blocks`, `images`, `classify`, `run` |
| `image.py` | `IMG-15` | `info`, `metrics`, `normalize`, `ocr-ready`, `vlm-ready`, `classify`, `run`, `crop` |
| `ocr.py` | `OCR-14` | `run`, `text`, `md`, `json`, `tables`, `blocks`, `metrics`, `diff` |
| `llm.py` | `LLM-16` | `call`, `node`, `graph`, `resume`, `status`, `models`, `tokens`, `fake` |
| `workflow.py` | `ORC-20` | `run`, `plan`, `status`, `resume`, `force`, `skip`, `stop`, `context` |

None of these exist yet: each is built after its processor's own acceptance evidence is
green. Two design notes worth knowing before they are written — `ocr.py` has **no** `--engine`
flag, because Docling is fixed and never user-selectable; and `llm.py` requires `--provider`
and `--model` on every inference subcommand, because a default model is exactly the silent
stand-in this project forbids. Its `fake` subcommand is first-class, not a hidden test flag:
the deterministic fake provider is what makes the graph and resume paths demonstrable without
a model or a spent token.

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

The stage-state vocabulary and the three identities are the shared seam; `docflow.pdf` is the
first processor implemented end to end against it.

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
pytest                     # 143 passed
ruff check .               # linter, includes import order
ruff format --check .      # formatter — this owns line length, not E501
pylint src tests           # 10.00/10
```

The whole suite runs with **no engine installed and no engine reached**: Poppler, OpenCV,
Docling and the provider SDKs are touched only in production, and every processor's tests
drive an in-memory double injected at the engine call. The PDF processor's evidence for that
is reproducible — with the binaries off the `PATH`, the suite is still green:

```bash
env -i PATH=/usr/bin:/bin "$(which python)" -m pytest -q   # 143 passed
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

8. **The README's phase table still lists three of the engine doubles as lab tools.**
   `docs/feedback/no-tests-on-third-parties.md` repurposed `PDF-14`, `IMG-15` and `OCR-14` as
   the in-memory doubles of `pdf`, `image` and `ocr`; the Phase 5 row above still names them as
   operator CLIs. Left verbatim here rather than guessed at — the IDs of the replacement lab
   tools are a plan revision.

---

## Next step

Phase 1 continues with the three processors still to build, independently and in parallel
against the frozen contracts: `image` (`IMG-01`…`IMG-14`), `ocr` (`OCR-01`…`OCR-13`) and `llm`
(`LLM-01`…`LLM-15`). Each needs a green happy-path test proving `Request → Result` with real
bytes from a small committed fixture, an in-memory engine double injected at its own
`primitives/` seam, and no import of another processor.

`pdf` is the worked example: `src/docflow/pdf/` for the layout, `tests/pdf/` for the test shape
(one module per source module, the double wired in `conftest.py`, the invariants mutation-
falsified), and `tests/fakes/engines/fake_poppler.py` for a double that models the engine's
native surface rather than our types.
