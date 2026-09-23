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

## Status: Phase 1 — the PDF engine seam has landed

Phase 0 is closed, and Phase 1 has started with `procesador-pdf`. Its engine seam — the
single module that knows Poppler — is implemented and tested, and the signatures of
`PDF-03`…`PDF-08` are in place. **No processor entry point is implemented yet**, so every
one of them is still a typed signature whose body raises:

```python
>>> import docflow.pdf as pdf
>>> pdf.process_pdf(request)
NotImplementedError: process_pdf is implemented in Phase 1 by PDF-10
```

That is deliberate. A stub that raised is honest; a stub that returned an empty `PDFResult`
would be a silent stand-in, which this project forbids at every stage.

| Phase | What | Owner |
|---|---|---|
| **0 — contracts & skeleton** | ✅ **done** | `GEN-01`…`GEN-06` |
| **1 — processors, independently** | ✅ `pdf` **complete** (`PDF-01`…`PDF-14`, Waves 1–5). ✅ `image` **complete** (`IMG-01`…`IMG-15`, Waves 0–6). 🔄 `ocr` started (`OCR-01`…`OCR-02` done). ⏳ `llm`: not started | `PDF-01`…`PDF-13`, `IMG-01`…`IMG-14`, `OCR-01`…`OCR-13`, `LLM-01`…`LLM-15` |
| 2 — orchestrator | state, reuse, resume | `ORC-01`…`ORC-19` |
| 3 — integration | source selection, end to end | `GEN-07`…`GEN-10` |
| 4 — hardening | idempotency, atomicity, close-out | `GEN-11`…`GEN-20` |
| 5 — lab tools | one operator CLI per processor | `GEN-21`, `PDF-14`, `IMG-15`, `OCR-14`, `LLM-16`, `ORC-20` |

Per-task status is authoritative in [`docs/plan/issues/wbs-procesador-pdf.md`](docs/plan/issues/wbs-procesador-pdf.md)
(`DONE` / `SIGNATURE_ONLY` / `NOT_STARTED`).

---

## Requirements

- **Python ≥ 3.11** (the shared vocabulary uses `enum.StrEnum`). Verified on 3.13.9.
- **`procesador-pdf` needs Poppler on `PATH`** — `pdfinfo`, `pdftotext`, `pdfimages`,
  `pdfseparate`, `pdftoppm`, `pdfunite`. Verified against Poppler 25.02.0.
  ```bash
  brew install poppler        # macOS
  apt-get install poppler-utils   # Debian/Ubuntu
  ```
  The engine is explicit: if a binary is missing the processor raises a typed
  `PopplerNotAvailableError` rather than substituting another reader.
  Poppler is a **system binary**, not a Python distribution, so it is not in
  `pyproject.toml` — `pip` cannot install it.
- **`procesador-image` needs OpenCV, numpy and Pillow.** These *are* Python distributions, so
  `pip install -e .` brings them in; they are declared in `pyproject.toml`.
  - `opencv-python-headless` is the declared build, not `opencv-python`: the standard build links
    the GUI libraries and cannot install on a server without a display, and nothing here opens a
    window.
  - Pillow is a first-class engine (the documented alternative to OpenCV), not an optional extra.
    `ImageEngineNotAvailableError` names a *missing* library, never one the project never claimed
    to need.
  - `tests/test_packaging.py` asserts that every module the engine seam loads is provided by a
    declared dependency, so a new engine cannot be added without its pin.

`ocr` needs Docling, which is declared in `pyproject.toml` and installed by `pip install -e .`. It
is a large dependency: it pulls the model stack, and a first run downloads models. `llm` needs no
engine yet — its backends land with their own phase.

**Docling is pinned with a compatible-release specifier** (`docling~=2.126.0`), not a bare `>=`.
The OCR subplan's determinism posture is "same image + same engine version + same normalized
options ⇒ same logical output structure", and its risk table names Docling schema changes between
versions: a major bump could move that schema while the recorded `engine_version` remained the
only clue that a re-run's structure changed for a reason other than its input.


## Setup

```bash
git clone <repo> && cd ibm-docling-ref

python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"        # the library's engines + pytest, pytest-cov, ruff, pylint
```

`pip install` is optional for the gates: `pyproject.toml` puts `src/` on the path, so
`pytest` runs from a clean checkout. Install it when you want to import `docflow` from
anywhere, or when you want the engine dependencies resolved rather than assumed — the four
gates pass either way, which is exactly how the undeclared dependencies went unnoticed.

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
python scripts/tools/image.py run page.png --ocr-ready --vlm-ready
python scripts/tools/image.py metrics page.png
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
| `pdf.py` | `PDF-14` | ✅ `inspect`, `split`, `render`, `text`, `blocks`, `images`, `classify`, `run` |
| `image.py` | `IMG-15` | ✅ `info`, `metrics`, `normalize`, `ocr-ready`, `vlm-ready`, `classify`, `run`, `crop` |
| `ocr.py` | `OCR-14` | `run`, `text`, `md`, `json`, `tables`, `blocks`, `metrics`, `diff` |
| `llm.py` | `LLM-16` | `call`, `node`, `graph`, `resume`, `status`, `models`, `tokens`, `fake` |
| `workflow.py` | `ORC-20` | `run`, `plan`, `status`, `resume`, `force`, `skip`, `stop`, `context` |

**`pdf.py` and `image.py` exist so far** — see [`scripts/tools/README.md`](scripts/tools/README.md)
for their command surfaces, output layout, exit codes and worked examples, and for the
boundaries every tool must respect. The other three are built once their processor's own
acceptance evidence is green, so a missing tool means a missing processor rather than
unfinished packaging.

`image.py` exposes **separate `ocr-ready` and `vlm-ready` subcommands** on purpose. The two
variants are not interchangeable — OCR wants one channel, deskewed and binarized, while a VLM
needs the colour and layout intact — and a single `prepare` command would teach the opposite
to the next person reading the tool.

Two design notes worth knowing before they are written — `ocr.py` has **no** `--engine`
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

result = pdf.process_pdf(request)  # Phase 1 — raises today
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

Two modules are real code rather than signatures, and they are the seam every processor and
the orchestrator will speak through.

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
pytest                     # 61 passed
ruff check .               # linter, includes import order
ruff format --check .      # formatter — this owns line length, not E501
pylint src tests           # 10.00/10
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

## Known divergences from the plan

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

4. **`GEN-05`'s out-of-bounds cites a `README.md` §9.3 that no longer exists.** The constraint is
   "adding a dependency that is not implied by `README.md` §9.3". This README has no §9 section —
   the numbered sections stop earlier — so the authority for what a dependency must be implied by
   is unverifiable as written. Handled by reading the *current* README as the intent: the
   Requirements section names every engine, and a dependency is admissible when that section says
   the processor needs it. Recorded because the next task that adds a dependency faces the same
   dead reference, and should not have to guess whether the constraint is still live.

5. **`GEN-05`'s engine pins landed with `IMG-11`, not in Wave 0.3.** The scope says the pins land
   "as they land in Phase 1", which the wave plan read as Wave 0.3. In practice the manifest was
   left at `dependencies = []` while `IMG-02`…`IMG-11` built twelve modules that need numpy,
   OpenCV and Pillow — and every gate stayed green, because the development environment had them
   installed. The pins are now in place and `tests/test_packaging.py` guards them, so the drift
   cannot recur silently. The ordering lesson belongs to `GEN-17`: an engine seam that resolves its
   libraries through `importlib` is invisible to every static check this repo runs.

6. **`subplan-procesador-ocr.md` gives two different failure vocabularies.** §3.1 (*Contract
   types*, the authoritative table) names `MISSING_FILE`, `UNSUPPORTED_FORMAT`, `DECODE_ERROR`,
   `ENGINE_ERROR`, `PARSE_ERROR`, `WRITE_ERROR`, `IO_ERROR`, `INTERNAL_ERROR`. §3.7 (*Error-handling
   posture*) names `INVALID_INPUT`, `UNSUPPORTED_IMAGE`, `OCR_ERROR`, `LAYOUT_ERROR`,
   `TABLE_EXTRACTION_ERROR`, `EXPORT_ERROR`, `IO_ERROR`, `INTERNAL_ERROR`. The two share two
   values. `OCR-01` ships §3.1's set, because that is the section that presents a contract and
   `OCR-01`'s acceptance criterion says "exactly the values named in the subplan" — the divergence
   is recorded in `ocr/contracts.py` beside the literal. `GEN-17` owns the reconciliation.

7. **`crop_region` was named by the image subplan and delivered by no task.** §3.2 lists it among
   the visual-analysis primitives and §10's `crop` subcommand drives it, but neither `IMG-04`'s
   nor `IMG-05`'s deliverable list includes a crop, so it fell between them. `IMG-15` supplies it
   in `image/primitives/transform.py` rather than shipping a `crop` command with nothing behind it.
   The same class of gap is worth watching as the remaining processors land: a primitive named in
   design prose and absent from every task's deliverables is invisible until something tries to
   call it.

Three smaller ones were resolved while writing the contracts, each noted in the module
docstring where it lives: `DocumentResult.processing_key` (required by `GEN-04` but absent from
`ORC-01`'s field list), `PDFResult.errors` (needed for the documental `PARTIAL` case), and the
OCR type names (`OCRContext` and `OCRDocument` are canonical; the subplan's `Context` and
`context.document` are aliases).

---

## Next step

Phase 1 is four independent processors, buildable in parallel against the frozen contracts.
Each needs a green happy-path test proving `Request → Result` with real bytes from a small
committed fixture, and no processor may import another. Start with `PDF-01` (contract types are
already stubbed in `pdf/contracts.py`) and `PDF-02` (the Poppler seam in `pdf/primitives/`).
