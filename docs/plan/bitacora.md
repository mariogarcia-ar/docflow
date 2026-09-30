# Bitácora — execution log

> Status: **living**. Append-only, one entry per work session.
>
> The file name is Spanish, like the `procesador-*` titles in `docs/idea/`; the content is
> English, like every other document in this repository.

## What this file is

A chronological record of **execution**: which tasks ran, what the gates said, which
decisions were taken in code, and what was left stale. It is the place to record progress so
that a frozen artifact does not have to be edited to say "this is done".

## What this file is not

- **Not a plan artifact.** `docs/plan/README.md`, the subplans and the WBS are the decisions;
  where this log and one of them disagree, **the plan wins** and the disagreement is a defect
  of this file.
- **Not a decision document.** A decision that changes the plan is a plan revision
  (subplan + WBS in the same pass) or a note in `docs/feedback/`.
- **Not referenced from `docs/plan/README.md`.** Adding a row to that index is a plan
  revision; until one lands, this file is discovered by name and nothing depends on it.
- **Not a task tracker.** Task IDs, titles, effort and dependencies live in
  `docs/plan/issues/wbs-*.md`; an entry here reports their **status**, which the WBS files do
  not carry.

## How to append an entry

Copy the template, put the newest entry **last**, and keep every claim checkable: a command
with its output beats a sentence saying it worked.

```markdown
## YYYY-MM-DD — <phase> · <processor or task range>

**Delivered.** What now exists, by file.
**Tasks.** `ID` → done/partial, with what is missing.
**Gate evidence.** The four gates, as run, with their counts.
**Invariant evidence.** Which invariants were mutation-falsified, and where the four-field
record lives. A record whose mutation did not turn its test red is a defect.
**Decisions taken in code.** What a code decision had to settle, why, and which plan or
document it touches.
**Left stale (owner).** Documents this session did not edit and that now disagree with the
code, each with the owner who can fix it.
**Next.** The first thing the next session should pick up.
```

---

## 2026-09-25 — Phase 1 · `procesador-pdf` (`PDF-01` … `PDF-14`)

**Delivered.**

| File | What it is |
|---|---|
| `src/docflow/pdf/contracts.py` | request/result vocabulary; the failure kinds and the `None`-able engine version described below |
| `src/docflow/pdf/primitives/__init__.py` | the Poppler seam: the only module in the tree that calls `subprocess.run`, plus `inspect_pdf`, `extract_page`, `split_pdf`, `merge_pdfs`, `render_page_to_image`, `extract_text_from_page`, `extract_images_from_page` |
| `src/docflow/pdf/primitives/errors.py` | the typed failure a primitive raises and the entry points convert — the only exception this processor throws |
| `src/docflow/pdf/primitives/composition.py` | `PDFDocumentInfo`, `PDFPageData`, the named classification thresholds, `analyze_pdf_page`, `classify_pdf_page` |
| `src/docflow/pdf/primitives/publication.py` | atomic publication: `.tmp` → validate → rename, with cleanup on failure |
| `src/docflow/pdf/primitives/validation.py` | `validate_pdf` fail-fast, `validate_pdf_page_result`, `validate_pdf_result` |
| `src/docflow/pdf/entrypoints.py` | `process_pdf` and `process_pdf_page`, the page loop, the artifact tree, `metadata.json` payloads |
| `tests/fixtures/pdf/pdf_sample_{text,image,mixed}.pdf`, `pdf_corrupt.pdf` | the committed samples, built deterministically by `build_samples.py` (standard library only) |
| `tests/fakes/engines/fake_poppler.py` | the in-memory Poppler double, native-shaped and injected at the seam |
| `tests/pdf/**` | one test module per source module, the happy path, the invariants, the failure paths |

`utils/` and `helpers/` stay empty, as resolved decision 5 of the subplan requires.

**Tasks.** All fourteen are done, in the subplan's waves:

| Wave | Tasks | Status |
|---|---|---|
| 1 — Foundations | `PDF-01`, `PDF-02` | done |
| 2 — Primitives | `PDF-03` … `PDF-08`, `PDF-14` | done |
| 3 — Composition | `PDF-09`, `PDF-10` | done |
| 4 — Hardening | `PDF-11`, `PDF-12`, `PDF-13` | done |

`merge_pdfs` (`PDF-04`) is implemented and tested but composed nowhere: the subplan defers it
off the happy path, so it carries a `# TODO: [MVP]`.

**Gate evidence.**

```
pytest                     143 passed
ruff check .               All checks passed!
ruff format --check .      68 files already formatted
pylint src tests           10.00/10
```

The phase exit is owned by `PDF-13`, and it includes the no-engine rule. With the binaries off
the `PATH`, the whole suite is still green — the measurement is the subprocess's own
environment, so the double is the only thing that answered:

```
env -i PATH=/usr/bin:/bin "$(which python)" -m pytest -q    143 passed
command -v pdfinfo                                          not reachable
```

**Invariant evidence.** Four invariants were mutation-falsified this session — page
completeness, immutable input, classification vocabulary & purity, and no-silent-failure. Each
was mutated, observed red, restored, and observed green, in the four-field shape
`docs/plan/README.md` §7 fixes. **The canonical records live in the root `README.md`** (the
table under "Rules that will bite you"), because that is where `GEN-16` audits them; this
entry does not restate them, so there is one copy and not two.

**Decisions taken in code.**

1. **`PDFErrorType` follows the subplan's ten names.** The code had drifted to eleven
   (`MISSING_FILE`, `PAGE_OUT_OF_RANGE`, `WRITE_ERROR`); `PDF-01` aligns it, mirroring the
   `OCRErrorType` decision, and a guard test restates the list so a drift turns red. Out of
   range lands on `INVALID_INPUT` when it is decided before the engine call and on
   `PAGE_EXTRACTION_ERROR` when the engine rejects the range; a write failure is `IO_ERROR`.
2. **`engine_version` is `str | None`.** A pre-engine failure (missing, unsupported, encrypted
   or corrupt document) reaches no engine call, so there is no version; `None` states that
   instead of a placeholder that reads like one.
3. **A page's failures live in `PDFPageValidation.errors`.** No `errors` field was added to
   `PDFPageResult`: a stage failure is precisely what the page's validation reports, and the
   record already carries the typed kind and the `recoverable` flag.
4. **`process_pdf_page` inspects the document once for the page's geometry.** The entry-point
   signature is frozen and cannot carry it, and the page has to work standalone. Inside a
   document run that is one extra `pdfinfo` per page, tagged `# TODO: [MVP]` to be replaced
   once the contract can pass the inspected document down.
5. **`processing_key` is computed by the processor** from the documented formula, because
   every artifact `metadata.json` must record it (`docflow.identities`) while its owner
   `ORC-02` is Phase 2. Tagged `# TODO: [MVP]` to reconcile the two at Phase 2.
6. **The fixtures live in `tests/fixtures/pdf/`, with their builder committed.** The subplan
   writes `fixtures/pdf_sample_*.pdf`; the repository's fixture root is `tests/fixtures/`, so
   the samples sit one level down. `build_samples.py` is standard library only and
   deterministic, so a fixture can be regenerated and reviewed as a diff.
7. **`tests/test_skeleton.py`'s Phase-0 stub check now covers the processors still stubbed.**
   `pdf` no longer raises, so the check points at `workflow`, `image`, `ocr` and `llm`; it
   stays a check rather than being deleted.

**Left stale (owner).** No pre-existing file under `docs/plan/`, `docs/idea/` or
`docs/feedback/` was edited — this log is the only thing added. These now disagree with the
code and need their owner:

| Document | What is stale | Owner |
|---|---|---|
| `docs/3party/poppler.md` §G (and its drift log §K) | the engine-signal table's right-hand column uses the eleven old names, and its "divergence to report" note no longer applies | dossier owner |
| `tests/fixtures/manifest.json` | does not know the `pdf/` folder or its four files; there is no builder in the tree to re-run | fixture owner |
| `docs/plan/issues/wbs-procesador-pdf.md` | header and §2 still say `NOT_STARTED` for all fourteen tasks; a WBS is a frozen artifact, so flipping it is a plan revision, not a code edit | plan owner |
| `README.md`, phase table | the Phase 5 row still lists `PDF-14` / `IMG-15` / `OCR-14` as lab tools; `docs/feedback/no-tests-on-third-parties.md` repurposed them as the engine doubles | plan owner |

**Next.** Phase 1 continues with `image` (`IMG-01`…`IMG-14`), then `ocr` and `llm`. `pdf` is
the worked example to copy: `src/docflow/pdf/` for the layout, `tests/pdf/` for the test shape,
and `tests/fakes/engines/fake_poppler.py` for a double that models the engine's native surface
rather than our types. The three follow-ups tagged in code — the per-page re-inspection, the
processor-local `processing_key`, and the double's re-check on a pin bump — are the first
things Phase 2 and the Release gate will want.

---

## 2026-09-25 — Phase 1 · `procesador-image` (`IMG-01` … `IMG-15`)

**Delivered.**

| File | What it is |
|---|---|
| `src/docflow/image/contracts.py` | the request/result vocabulary, with the "absence is stated" typing described below |
| `src/docflow/image/primitives/__init__.py` | the OpenCV seam: the only module that reaches the engine, plus the whole primitive surface (load/store, convert, enhance, quality, orientation, text regions) and the two preparation pipelines |
| `src/docflow/image/primitives/composition.py` | `ImageFileFacts`, every named threshold, the deterministic region naming and the descriptive classification |
| `src/docflow/image/primitives/errors.py` | the typed failure a primitive raises and the entry points convert |
| `src/docflow/image/primitives/publication.py` | atomic publication: `.tmp` → validate → rename, with cleanup on failure |
| `src/docflow/image/primitives/validation.py` | `validate_image_input` fail-fast and the structural result validation |
| `src/docflow/image/entrypoints.py` | `process_image` and `process_image_from_page`, the representation table, the artifact namespace, `metadata.json` |
| `tests/fixtures/image/{color_layout,skewed_text,embedded_logo,corrupt}.png` | the committed samples, built deterministically by `build_samples.py` (standard library only) |
| `tests/fakes/engines/fake_opencv.py` | the in-memory OpenCV double, native-shaped and injected at the seam |
| `tests/image/**` | one test module per source module, the happy path, the three invariants, the failure paths |
| `tests/support.py` | the two filesystem assertions the pdf and image suites both need, extracted instead of copied |

`utils/` and `helpers/` stay empty, as resolved decision 3 of the subplan requires.

**Tasks.** All fifteen are done, in the subplan's waves:

| Wave | Tasks | Status |
|---|---|---|
| 1 — Contracts & seam | `IMG-01`, `IMG-02`, `IMG-03` | done |
| 2 — Analysis | `IMG-04`, `IMG-05`, `IMG-06`, `IMG-15` | done |
| 3 — Outputs | `IMG-07`, `IMG-08`, `IMG-09`, `IMG-10` | done |
| 4 — Publish | `IMG-11`, `IMG-12` | done |
| 5 — Verify | `IMG-13`, `IMG-14` | done |

`sharpen_image` (`IMG-05`) and `compress_image` (`IMG-05`) are implemented and tested but composed
nowhere: no option asks for them and both variants are lossless PNG, so each carries a
`# TODO: [MVP]`, exactly as `merge_pdfs` does in `pdf`.

**Gate evidence.**

```
pytest                     228 passed
ruff check .               All checks passed!
ruff format --check .      84 files already formatted
pylint src tests           10.00/10
```

The phase exit is owned by `IMG-14`, and it includes the no-engine rule. With the Poppler
binaries off the `PATH` the whole suite is still green, and the image suite loads no engine at
all: importing the seam must succeed with OpenCV absent, which
`tests/test_skeleton.py::test_importing_the_primitive_seams_pulls_in_no_engine` measures in a
clean interpreter.

```
env -i PATH=/usr/bin:/bin "$(which python)" -m pytest -q    228 passed
```

Acceptance scenario 5 of the subplan ("no test reaches OpenCV") measured directly — the whole
image suite, in one process, and the engine never even imported:

```
python -c "import sys, pytest; pytest.main(['tests/image','-q']); print('cv2' in sys.modules)"
91 passed
False
```

The mechanism that makes that structural rather than lucky: `tests/image/conftest.py` installs
the double in an **autouse** fixture, so a test that forgot to ask for it cannot reach the
library on the machine.

**Invariant evidence.** The three invariants of subplan §6 were mutation-falsified this session —
immutable input, OCR variant ≠ VLM variant, namespace ownership. Each was mutated, observed red,
restored with `git checkout --`, and observed green. **The canonical four-field records live in
the root `README.md`** (the table under "Rules that will bite you"), where `GEN-16` audits them.
One of them paid a dividend: the immutable-input mutation overwrote the committed
`color_layout.png`, and re-running `build_samples.py` reproduced `d0023a05f4f0…` byte for byte,
which is the fixture builder's determinism proven rather than asserted.

**Decisions taken in code.**

1. **Absence is stated, never faked — five contract fields widened to `X | None`.**
   `ImageSourceRef.width`/`height`/`size`, `ImageMetadata.engine_version`,
   `ImageMetadata.input_metrics`/`output_metrics` and `ImageResult.metrics`/`classification`.
   A run can fail before anything is measured (absent file, unsupported container, refused
   decode), and in that case there is no geometry, no version, no reading and no classification:
   a `0`, a default engine or a default classification would read as an answer nobody observed,
   which the no-silent-stand-in rule forbids. This is the same decision `pdf` took for
   `engine_version`, applied to every field that can be unmeasured. No field gained a default, so
   `None` is always passed deliberately.
2. **`detect_orientation` is relative to the page frame.** A decoded array carries no rotation
   metadata, so the only signal the pixels hold is "the ink's box contradicts the page's aspect",
   which is what it reports (0 or 90). Both normal cases — portrait text on a portrait page,
   landscape text on a landscape page — report 0 and no correction is applied.
   `# TODO: [MVP]`: the authoritative source is the container's own tag (JPEG EXIF, a PDF page's
   `/Rotate`), which the PDF processor or a container reader has to supply.
3. **A region's ink share is measured on the raw mask, not the closed one.** The closing exists to
   join a glyph into a blob, so it fills the gaps by construction: a reading taken from the closed
   mask reports a filled box for every region and carries no information.
4. **Each pipeline returns what it produced, its transformations and its own measurements**
   (`PreparedImage`). That is how a variant's readings reach `metadata.json` without a second
   execution of the pipeline, and it is why the per-variant transformation lists are recorded
   independently.
5. **`metadata.json` is not an entry in `result.artifacts`.** Every entry there is an image and
   `ImageArtifactKind` has no kind for a JSON record; a kind invented for it would be a
   mislabelled artifact. Its publication is still attempted and still recorded: a failure to
   write it fails the run.
6. **The double decodes the container's geometry and synthesizes the pixel values.** The width and
   height come from the file's own header; the values are a banded grey pattern whose phase comes
   from the file's first bytes. That is what a double is, and it is documented in the module.
   `corrupt.png` is handled the way the engine handles it: `imread` answers `None`, and the seam
   types that as `DECODE_ERROR`. The subplan §6 failure-fixture row says "the double raises
   `DECODE_ERROR`"; the subplan's own §3 native-shape rule (the fake returns what the engine
   returns, never our translated type) is the stronger one and the one the code follows.
7. **The fixtures are small on purpose** (160×120). The double produces pixels per-pixel in
   Python, so the sample size sets the suite's runtime, not the fidelity of anything; the same
   trade `pdf` made when it wrote three synthetic pages.
8. **`tests/support.py` is new, and `tests/pdf/test_entrypoints.py` now imports from it.** Pylint
   found the digest/list helpers copied between the two suites; the fix was to remove the
   duplication rather than suppress the finding. Two *source* modules may not share it, which is
   why the sibling duplication in `docflow.image.primitives.publication` and
   `docflow.image.entrypoints` is suppressed inline with that reason instead.
9. **Suppressions, each inline and each with its reason.** `duplicate-code` in
   `image/primitives/publication.py` and `image/entrypoints.py` (a processor may not import
   another processor's internals, so the short rule is written twice on purpose);
   `too-many-lines` in `image/primitives/__init__.py` (the frozen patch path and the static
   convention check both read that one module, so a call moved into a sibling would escape both);
   `invalid-name`/`redefined-builtin` in `tests/fakes/engines/fake_opencv.py` (the double mirrors
   the engine's own names — `cvtColor`, `clipLimit`, `type` are keywords of the interface it
   stands in for).
10. **The engine is pinned in `pyproject.toml`** as `opencv-python-headless>=5.0,<6`: the
    server-side wheel, because nothing here opens a window. The version actually used is stamped
    into every artifact's metadata; the wheel question the dossier left open is settled there.
11. **The thresholds in `composition.py` are PoC values, named and tagged `# TODO: [MVP]`.** They
    were fixed now, as resolved decision 4 of the subplan requires, and chosen so that a clean
    text-like page is not reported as `LOW_QUALITY`; they are revisited against the corpus at the
    MVP gate.

**Left stale (owner).** No pre-existing file under `docs/plan/` or `docs/idea/` was edited. The
root `README.md` was updated (it is the developer quickstart, not a plan artifact), and
`pyproject.toml` gained the pin. These now disagree with the code and need their owner:

| Document | What is stale | Owner |
|---|---|---|
| `docs/plan/issues/wbs-procesador-image.md` | header and §2 still say `NOT_STARTED` for all fifteen tasks; flipping it is a plan revision, not a code edit | plan owner |
| `docs/3party/opencv.md` §B | says "the pin is `TBD` (`dependencies = []` until `IMG-02`)"; the pin landed as `opencv-python-headless` | dossier owner |
| `docs/3party/opencv.md` §D | still tabulates `crop_region`'s neighbours without noting that the subplan defers `crop_region` and `image/regions/`; §K's "which primitives have no Phase 1 caller" is now answered (`sharpen_image`, `compress_image`) | dossier owner |
| `docs/plan/subplan-procesador-image.md` §6 | the failure-fixture row says the double "raises `DECODE_ERROR`"; the code follows the subplan's own native-shape rule, so the engine's silent `None` is what is doubled | plan owner |
| `tests/fixtures/manifest.json` | does not know `tests/fixtures/image/` or its four files, and still has no builder in the tree to re-run | fixture owner |
| `README.md`, phase table | the Phase 5 row still lists `IMG-15` as a lab tool; `docs/feedback/no-tests-on-third-parties.md` repurposed it as the engine double (also true of `PDF-14`, already flagged) | plan owner |

**Next.** Phase 1 continues with `ocr` (`OCR-01`…`OCR-13`), then `llm`. `image` adds two things to
the worked example: the engine is a **library**, so the seam resolves it with
`importlib.import_module` at call time and the double is a namespace of methods rather than a
subprocess runner; and a processor's failure posture has to cover "nothing was measured", which
is why its contract fields for measurements are optional and its failed result is a typed error
with every unmeasured field at `None`.

---

## 2026-09-25 — Phase 1 · `procesador-ocr` (`OCR-01` … `OCR-14`)

**Delivered.**

| File | What it is |
|---|---|
| `src/docflow/ocr/contracts.py` | the request/result vocabulary; the nine failure kinds stayed as `OCR-01` froze them, and the result's product fields are now optional (see decision 1) |
| `src/docflow/ocr/primitives/__init__.py` | the Docling seam: the engine call (`convert_image_with_docling`), the five `extract_docling_*` translators, `conversion_failure`, the option/config pair, the two normalizers, `process_tables`, the metadata and document builders |
| `src/docflow/ocr/primitives/composition.py` | engine-independent composition: `LayoutGeometry`, `ExtractedBlock`, `ExtractedTable`, `OrderedDocument`, the reading-order key, `normalize_bbox`, `normalize_layout`, `merge_ocr_blocks`, `preserve_reading_order`, `normalize_table`, `table_to_markdown`, `analyze_ocr_result` |
| `src/docflow/ocr/primitives/errors.py` | the typed failure a primitive raises and the entry points convert — the only exception this processor throws |
| `src/docflow/ocr/primitives/publication.py` | `ensure_directory`, `write_text_atomic`, `write_json_atomic`: `.tmp` → validate → rename, with cleanup on failure |
| `src/docflow/ocr/primitives/validation.py` | `validate_ocr_input` fail-fast, `validate_output_artifacts`, `validate_ocr_result` and the state map |
| `src/docflow/ocr/entrypoints.py` | `process_ocr_image` and the deferred `process_ocr_from_page`, the artifact namespace, the `metadata.json` payload |
| `tests/fakes/engines/fake_docling.py` | the in-memory Docling double, native-shaped, adversarial-ordered, with the two failure knobs |
| `tests/fixtures/ocr/ocr_prepared_text_and_table.png`, `ocr_blank.png` | the committed samples, built deterministically by `build_samples.py` (standard library only) |
| `tests/ocr/**` | one test module per source module, mirroring `src/docflow/ocr/` |

`utils/` and `helpers/` stay empty, as resolved decision 6 of the subplan requires.

**Tasks.** All fourteen are done, in the subplan's waves:

| Wave | Tasks | Status |
|---|---|---|
| 1 — Foundations | `OCR-01`, `OCR-02` | done |
| 2 — Engine + extraction | `OCR-03`, `OCR-04`, `OCR-05`, `OCR-14` | done |
| 3 — Outputs | `OCR-06`, `OCR-07`, `OCR-08`, `OCR-09` | done |
| 4 — Publish + entry points | `OCR-10`, `OCR-11` | done |
| 5 — Verification | `OCR-12`, `OCR-13` | done |

`process_ocr_from_page` (`OCR-11`) is implemented and tested but composed nowhere: the subplan §9
defers it to the Phase 3 integration, so it carries a `# TODO: [MVP]`, exactly as `merge_pdfs` and
`sharpen_image` do in their processors.

**Gate evidence.**

```
pytest                     339 passed          (117 of them in tests/ocr: 110 new + the 7 contract tests)
ruff check .               All checks passed!
ruff format --check .      99 files already formatted
pylint src tests           10.00/10
```

The phase exit is owned by `OCR-13`, and it includes the no-engine rule. With the Poppler binaries
off the `PATH` the whole suite is still green, and the OCR suite loads no engine at all — Docling is
not even imported by the tests:

```
env -i PATH=/usr/bin:/bin "$(which python)" -m pytest -q    339 passed
python -c "import sys, pytest; pytest.main(['tests/ocr','-q']); print('docling' in sys.modules)"
117 passed
False
```

**Invariant evidence.** The three invariants of subplan §6 were mutation-falsified this session —
deterministic ordering, no run-time stamps in functional content, and atomic publication. Each was
mutated, observed red, restored by re-applying the inverse edit (the files were new in this same
session, so `git checkout --` had nothing to restore from), and observed green again. **The
canonical four-field records live in the root `README.md`**, where `GEN-16` audits them.

**Decisions taken in code.**

1. **Absence is stated in the typing — ten `OCRResult` fields are `X | None`.** `text`, `markdown`,
   `structured_document`, `tables`, `blocks`, `layout`, `reading_order`, `metrics`, `artifacts` and
   `metadata` are all optional, and the module docstring states the rule they carry: ``None`` means
   *this was never produced*, an empty value means *produced and empty*. A blank page legitimately
   extracts the empty text; a run that failed before the engine was reached has no text at all. The
   subplan §3.1 does not carry this, and it is the `image` decision applied to a whole result
   rather than to the fields that happened to need it there.
2. **`conversion_failure` owns the half of Docling's failure surface that does not raise.** The
   dossier (§K, defect 5) recorded that Docling *returns* `ConversionResult(status=FAILURE,
   errors=…)` as well as raising, and that neither the plan nor a double modelled it. A returned
   `failure` is an unrecoverable `OCR_ERROR` and ends the run; `partial_success` is recorded as a
   **recoverable** `OCR_ERROR` — the artifacts stand and the validation reports `INCOMPLETE`,
   because the subplan calls a partial result data rather than an error; a status the seam does not
   model is an `ENGINE_ERROR`, never a success.
3. **The engine call is reached through the module, not through a name bound at import.** The
   frozen injection point is the attribute `docflow.ocr.primitives.convert_image_with_docling`, so
   `_convert` calls `primitives.convert_image_with_docling(...)`. Binding it in the entry point's
   namespace made the patch a no-op — observed: the suite reached the real Docling and took 39.59 s
   instead of 0.2 s — which is exactly the drift `README.md` §9.7 warns about, caught by writing
   the double before the tests.
4. **Two names are patched, one of them for the version.** `convert_image_with_docling` is the
   engine call; `docflow.ocr.primitives.docling` is the engine namespace `get_engine_version` reads
   `__version__` from. Without the second, recording a version would require the engine to be
   installed, which the DoD forbids. It is the image seam's lazy-resolution rule applied to the one
   other thing this processor reads off the engine.
5. **A run's status is decided by lost artifacts, not by every recorded failure.** A partial
   conversion records a failure and the run still succeeds with `INCOMPLETE`; an artifact that
   could not be published fails the run. Collapsing the two would have made a partial result a
   `failed` run, contradicting the subplan's "not an error".
6. **Reading order is geometry, and the engine's own sequence is the last tie-break.** Sort by
   (page, top, left, engine position); mint the identifiers *after* the sort, so a name and a
   position never disagree; join a run of consecutive body-text items into one `paragraph`, with
   the box measured as the union of the ones it joined. The double hands its items over in
   adversarial order (caption, table, second line, first line, heading) precisely so a broken sort
   is falsifiable — and it is: deleting the sort key turns three tests red.
7. **The option flags decide what is *claimed*, not what the engine computed.** `tables: false`
   claims no table even when one arrived; `layout: false` claims no box on any block or table;
   `reading_order: false` keeps the engine's sequence instead of deriving one, so the paragraph
   merge joins only what the engine placed next to each other and a paragraph can legitimately
   arrive split. The page *size* is reported in every case, because `text_density` divides by it —
   and a document with no page area is a `LAYOUT_ERROR` rather than a density of `0.0`, which would
   be a measurement nobody took.
8. **Validation reports on the result's own error list instead of copying it.** The entry point
   shares one list between the stages and the validation, so a failure recorded *after*
   `validate_ocr_result` ran — the `metadata.json` that could not be published — still reaches the
   record. The synthesized "this artifact was not published" failures are appended idempotently, so
   validating twice reports one gap twice rather than four times.
9. **An empty artifact is publishable; a write that did not happen is not.** A blank page's
   `text.txt` is zero bytes and that is the measurement, stated by `OCRMetrics.empty` and the
   `EMPTY` status; the writer therefore checks that the write *happened* (the file exists after the
   temporary write) rather than that it produced content. Conversely a filesystem that refuses the
   rename, and a payload JSON cannot represent, are both typed (`IO_ERROR`, `EXPORT_ERROR`) instead
   of escaping as an `OSError` or a `TypeError` through `_attempt`, which catches one type.
10. **The double reads the page frame from the file and synthesizes the content.** Like
    `fake_opencv`, it takes the geometry from the PNG's own header so the page it reports is the
    page that was handed over, and it invents the *content* — which it says so in its docstring.
    The fixtures are 240x120 stdlib-built PNGs for the same reason the image ones are small: the
    suite's runtime, not the fidelity, is what the size buys.
11. **`tests/support.py` gained `imported_modules(path)`, and `tests/ocr/samples.py` gained
    `OPTION_VALUES` and `build_block`.** Pylint's `duplicate-code` found the same AST walk in
    `test_skeleton.py` and the double's compliance test, and the same block/option literals in two
    of this processor's own test modules; the fix was to remove the duplication rather than
    suppress it. The cross-*processor* duplications are suppressed inline with their reason: a
    processor may not import another processor's internals, and each suite proves the fixtures and
    the wrapper it owns.
12. **The engine is pinned in `pyproject.toml`** as `docling>=2.126,<3`: the version the seam was
    written against. The version recorded in every artifact is the one Docling itself reports, and
    a bump is a re-check of the double against the engine's shapes (`# TODO: [RELEASE]` on
    `fake_docling.py`).
13. **Three names exist beyond the subplan §3.4 list, and each is required by a row of the WBS.**
    `process_tables` (`OCR-07`), `analyze_ocr_result` (`OCR-08`) and `build_ocr_document` (the
    assembler of `OCR-04`'s document from the five extractors). `conversion_failure` is a fourth,
    and it exists because decision 2 needs an owner. No predicate layer, no second export path and
    no `count_*` helper were added, and a test asserts exactly that.

**Left stale (owner).** No pre-existing file under `docs/plan/` or `docs/idea/` was edited. The
root `README.md` was updated (it is the developer quickstart, not a plan artifact), and
`pyproject.toml` gained the pin. These now disagree with the code and need their owner:

| Document | What is stale | Owner |
|---|---|---|
| `docs/plan/issues/wbs-procesador-ocr.md` | header and §2 still say `NOT_STARTED` for all fourteen tasks; flipping it is a plan revision, not a code edit | plan owner |
| `docs/plan/subplan-procesador-ocr.md` §3.4 | the closed list stops at 25 names; `process_tables`, `analyze_ocr_result`, `build_ocr_document` and `conversion_failure` are required by `OCR-04`, `OCR-07` and `OCR-08` and exist in the code | plan owner |
| `docs/idea/procesador-ocr.md` | still names the 53-primitive surface; the divergence is deliberate (§9 decision 7) and is what `GEN-17` reconciles | plan owner |
| `docs/3party/docling.md` §B | says the pin is `TBD`; it landed as `docling>=2.126,<3` | dossier owner |
| `docs/3party/docling.md` §D, §K | the `generate_page_images` question is answered in code (`False`) and the returned-failure shape is now modelled, but neither is written back; the OCR *backend* question is still open in both places — the seam folds `ocr_language` in and leaves the backend at Docling's default, which is a choice the dossier should record | dossier owner |
| `docs/plan/README.md` §9.7 | states the injection point as `convert_image_with_docling` only; the seam also patches the engine namespace for the version (decision 4) | plan owner |
| `tests/fixtures/manifest.json` | still knows neither `pdf/`, `image/` nor `ocr/`, and has no builder in the tree to re-run | fixture owner |
| `README.md`, phase table | the Phase 5 row still lists `OCR-14` as a lab tool; `docs/feedback/no-tests-on-third-parties.md` repurposed it as the engine double (also true of `PDF-14` and `IMG-15`) | plan owner |

**Next.** Phase 1 closes with `llm` (`LLM-01`…`LLM-16`). It is the one processor whose fake is
**scripted** rather than content-shaped (`LLM-03`): a model's answer is not deterministic for a
fixed input, and `LLM-08` needs a scripted sequence — invalid JSON on attempt one, valid on attempt
two. What `ocr` adds to the worked example: an engine whose structures are rich and must be
translated, whose failure arrives twice (raised *and* returned, decision 2), and whose double hands
its items back in an adversarial order so that the ordering invariant is falsifiable rather than
decorative. The follow-ups tagged in code are the first things Phase 2 and the Release gate will
want: `process_ocr_from_page` composed nowhere, the PoC threshold in `composition.py`, spanned
cells in `_table_grid`, the processor-local `processing_key` (`ORC-02`), publication `fsync`
(`RELEASE`), and the double's re-check on a pin bump.

---

## 2026-09-26 — Phase 1 · `procesador-llm-call` (`LLM-01` … `LLM-15`)

**Delivered.**

| File | What it is |
|---|---|
| `src/docflow/llm/contracts.py` | the request/result vocabulary, plus the two Phase-1 additions described in decision 1 |
| `src/docflow/llm/primitives/__init__.py` | the provider seam: the only module in the tree that reaches a provider, with the seven primitives, the two transports (Ollama and the OpenAI-compatible dialect) and the response translation |
| `src/docflow/llm/primitives/errors.py` | the typed failure a primitive raises, and the retryability of every kind |
| `src/docflow/llm/primitives/composition.py` | engine-independent logic: template render, prompt build, `request_key`, JSON parsing, per-field comparison, token estimation, the descriptor→plan compiler and the reuse rule |
| `src/docflow/llm/primitives/validation.py` | the request check, the asset loaders, the enforced JSON-Schema subset and the result self-check |
| `src/docflow/llm/primitives/publication.py` | atomic publication: `.tmp` → validate → rename, with cleanup on failure |
| `src/docflow/llm/primitives/persistence.py` | the two-artifact round trip: `state.json` and `final_result.json` |
| `src/docflow/llm/entrypoints.py` | `process_llm_request`, `process_llm_node`, `retry_llm_request`, `execute_llm_graph` and `model_query_for` |
| `tests/fixtures/llm/template/simple_extract.md`, `tests/fixtures/llm/schema/simple.schema.json` | the two committed assets, used verbatim by the happy path |
| `tests/fakes/engines/fake_provider.py` | the **scripted** in-memory provider, native-shaped for both dialects, with a call counter |
| `tests/llm/primitives/http_stub.py` + `conftest.py` | the stub HTTP client the seam's payload shapes and error mapping are proven against, and the fixture that installs it |
| `tests/llm/**` | one test module per source module, the happy path, the two invariants, the failure paths |

`utils/` and `helpers/` stay empty, as the subplan's resolved decisions require.

**Tasks.** All fifteen are done, in the subplan's waves:

| Wave | Tasks | Status |
|---|---|---|
| 1 — Contracts & primitives | `LLM-01`, `LLM-02`, `LLM-03`, `LLM-04`, `LLM-05` | done |
| 2 — Single call | `LLM-06` … `LLM-09`, `LLM-15` | done |
| 3 — Linear chain | `LLM-10` … `LLM-14` | done |

`check_model_available` (`LLM-09`) is implemented and unit-tested but composed nowhere: a run
learns that a model is missing from the provider's own 404, which is the same answer without a
second call. It carries that note in its docstring rather than a `# TODO`, because the primitive
is complete — it is simply not on the inference path.

**Gate evidence.**

```
pytest                     511 passed
ruff check .               All checks passed!
ruff format --check .      119 files already formatted
pylint src tests           10.00/10
```

The phase exit includes the no-engine and no-provider rule; with the Poppler binaries off the
`PATH`, the whole suite is still green and no client library is loaded:

```
env -i PATH=/usr/bin:/bin "$(which python)" -m pytest -q    511 passed
```

**Invariant evidence.** Two invariants were mutation-falsified this session — no re-execution of
a valid call on restart, and `request_key` determinism and independence from run identity. Each
was mutated, observed red, restored (verified with `git diff` against the staged file), and
observed green, in the four-field shape `docs/plan/README.md` §7 fixes. **The canonical records
live in the root `README.md`** (the table under "Rules that will bite you"), because that is where
`GEN-16` audits them. Invariant 3 (downstream invalidation on force) is deferred with the chain's
dynamic machinery (§9.6) and is not claimed.

**Decisions taken in code.**

1. **The nine failure kinds are in the contract, and the attempt carries the typed one.**
   `LLMErrorType` and `LLMError` were added to `contracts.py`; `LLMAttempt.error` is an `LLMError`
   rather than a bare message; `LLMResult` and `LLMNodeResult` gained `errors`. The subplan §3
   states the nine kinds and their retryability but its §3.1 field lists carry no error record, so
   this is a Phase-1 addition in the `OCRResult.error` and `PDFPageValidation.errors` tradition —
   recorded rather than silent. `validation_errors` keeps its own meaning: *why the answer did not
   satisfy the schema*, which is a different question from what went wrong.
2. **`LLMAttempt.raw_response` is `str | None`.** An attempt that ended before the provider
   answered has no raw response, and an empty string would read as an answer that was empty.
3. **The retry layer has one owner: this processor.** The dossier's §K defect 6 (an SDK
   `max_retries` default of 2 beside `LLM-08`'s own attempts, with no stated owner) is settled in
   code: the seam does not configure a client-level retry, and `options["max_attempts"]` — default
   two attempts, recorded in `normalized_options` and therefore in the key — is the only policy.
   A retry keeps every prior attempt, and a non-retryable kind never buys another paid call.
4. **`get_context_window` answers `None` for the OpenAI-compatible dialect** (dossier §K defect 7:
   it is unimplementable for a hosted provider). `None` means *unknown*, and
   `is_context_limit_exceeded` treats unknown as "not an overflow" — an unmeasured ceiling is not
   evidence, and claiming one would refuse a call that would have worked.
5. **An LLM run makes exactly one provider call per inference.** `get_model_info` and
   `get_context_window` are implemented and reachable through `process_llm_request`'s companion
   `model_query_for`, but a run does not probe them: a probe that failed would have to be either
   swallowed or turned into a failure of a call that could have succeeded. `model_version` comes
   from `metadata["model_version"]` (subplan §9 decision 5's fallback) and the window from
   `options["context_window"]`. Tagged `# TODO: [MVP]` to probe once per model and cache it.
6. **Three inputs the contract cannot carry live in `metadata`, with no defaults.** `output_dir`
   names the run's `llm/` namespace, `assets_dir` the template/schema root, `run_id` the identity a
   resume pins. A request that states none of them is a typed `DEPENDENCY_ERROR`, and a run with no
   namespace writes nothing rather than to a guessed place. Reconciling this with the orchestrator
   is `ORC-02`'s.
7. **`DEPENDENCY_ERROR` owns "an input this run declared does not resolve"**, because the nine
   kinds have no `INVALID_INPUT`: an unnamed provider, a missing template or schema asset, an
   unreadable image and a descriptor that cannot be executed all land there, and the seam's mapping
   table says so in one place.
8. **A descriptor key the processor does not model is refused by name.** Routing, parallel
   branches and per-node `SKIP` / `FORCE` / `INVALIDATE` are deferred (§9.6), so a node carrying
   `when` fails with `DEPENDENCY_ERROR` naming the key instead of being executed as if it were a
   plain node — a graph that silently ran every node would be a different graph from the declared
   one. The same reasoning refuses a schema keyword the validator does not enforce (`SCHEMA_ERROR`)
   rather than validating under a rule it never applied.
9. **The schema subset is stated, and other keywords are refused.** `type`, `required`,
   `properties`, `additionalProperties`, `items` and `enum` are enforced, `title`/`description`/
   `default` are annotations, and everything else is reported by name. No JSON-Schema library is
   added for the PoC; `# TODO: [MVP]` names the replacement.
10. **The rendered prompt is the one that is hashed, and the identity is absent from the key.**
    `calculate_request_key` has no parameter for `run_id`, `graph_id`, `node_id` or `attempt_id` —
    that is *how* the formula excludes them — and the credential is dropped from
    `normalized_options` before anything is hashed or written, because a key is persisted in
    `final_result.json`.
11. **Node reuse and the run's outcome are two different fields.** On a resumed chain the *action*
    is `REUSED` (in `LLMGraphState.node_states` and the result's `node_actions`) while the node's
    own `LLMNodeResult.status` stays `SUCCESS`: "we did not have to pay" and "the answer was good"
    are different statements, which is the distinction `StageState` exists for.
12. **A node whose planning fails carries an empty `request_key`.** The frozen field is a `str` and
    there is no key to mint, so `""` states *no key was minted* — and `validate_cached_result`
    refuses to reuse it, which is the only property that matters. Documented on the entry point.
13. **`composition.py` carries an inline `too-many-lines` suppression.** The module is the
    engine-independent half of the processor and its functions share one vocabulary and one
    another's inputs (the rendered prompt is what the key hashes; the parsed answer is what the
    comparison reads); splitting it would separate a rule from the value it applies to. The
    suppression carries its reason, as the project's rule requires, and `pylint src tests` is
    10.00/10 with it.
14. **`httpx` is a declared dependency.** The transport is real code, so the client it needs is in
    `pyproject.toml`; it is imported *inside* the call that needs it, so the suite still runs with
    no client installed and the "no engine loaded" guard still holds.
15. **One pre-existing Pylint finding was closed on the way.** `tests/ocr/primitives/test_publication.py`
    had a `NotJson` helper class that Pylint rates `too-few-public-methods` (0/2) with no
    suppression, so the four-gate run was not clean before this session either. It now carries an
    inline suppression with its reason, the way `fake_docling.py` does for the same shape.

**Left stale (owner).** No pre-existing file under `docs/plan/` or `docs/idea/` was edited. The
root `README.md` was updated (developer quickstart, not a plan artifact) and `pyproject.toml`
gained a dependency. These now disagree with the code and need their owner:

| Document | What is stale | Owner |
|---|---|---|
| `docs/plan/issues/wbs-procesador-llm-call.md` | header and §2 still say `NOT_STARTED` for all fifteen tasks; flipping it is a plan revision, not a code edit | plan owner |
| `docs/plan/subplan-procesador-llm-call.md` §3.1 | the field lists carry no error record; `LLMError`, `LLMErrorType`, `LLMAttempt.error` and the `errors` field on both results exist in the code (decision 1) | plan owner |
| `docs/plan/subplan-procesador-llm-call.md` §9.5 | says `model_version` comes from `get_model_info` "when available"; the run does not probe it (decision 5), and the plan never says where the output directory or the asset root come from (decision 6) | plan owner |
| `docs/3party/provider-sdk.md` | the transport question (HTTP client vs SDK), the timeout owner (`options["timeout"]`, default 30 s) and the retry-layer question are answered in code but not written back; the pin is `httpx>=0.28,<1`, not the provider SDK | dossier owner |
| `docs/3party/ollama.md`, `docs/3party/vllm.md` | the two request/response shapes the transports were written against are not recorded there; `num_ctx` is read from `/api/show`'s `parameters` string, and no OpenAI-compatible endpoint states a window | dossier owner |
| `tests/fixtures/manifest.json` | still knows none of `pdf/`, `image/`, `ocr/` or `llm/`, and has no builder in the tree to re-run | fixture owner |
| `README.md`, phase table | the Phase 5 row still lists `LLM-16` as a lab tool; the engine-double convention repurposed `PDF-14`, `IMG-15` and `OCR-14`, and `LLM-03` was always a double rather than a CLI | plan owner |

**Next.** Phase 1 is complete; Phase 2 (the orchestrator, `ORC-01`…`ORC-19`) starts against
`docs/plan/subplan-orquestador.md`. The first reconciliations it owns: the processor-local
`processing_key` computed inside all four processors, the `LLMInput` inputs that currently ride in
`metadata` (decision 6) and the two-level reuse rule the LLM subplan §3 says must stay two rules.
The follow-ups tagged in code are its first candidates: the per-node artifact tree and
`claim_node` / *parallel branches* / per-node `SKIP`–`FORCE`–`INVALIDATE` / `calculate_consensus`
(`# TODO: [MVP]`), the provider inventory probe (decision 5), a real JSON-Schema engine
(decision 9), publication `fsync` (`# TODO: [RELEASE]`) and the double's re-check on a pin bump.

---

## 2026-09-26 — Phase 2 · `procesador-orquestador` (`ORC-01` … `ORC-19`)

**Delivered.**

| File | What it is |
|---|---|
| `src/docflow/workflow/contracts.py` | `ORC-01`: the request/result pair from Phase 0, plus `DocumentContext`, `PageContext`, `PageResult`, `StageExecution`, `StageResolution`, `PlannedStage`, `ExecutionPlan` and the five literals (`StageName`, `StageAction`, `SourceKind`, `ExtractionStrategy`, `ErrorOutcome`) |
| `src/docflow/workflow/identity.py` | `ORC-02`: `input_hash`, `options_hash`, `processing_key`, `build_workflow_run_id`, and the normalizer that makes two spellings of one option set hash alike |
| `src/docflow/workflow/context.py`, `persistence.py` | `ORC-03`: create / load / save `DocumentContext`, create / get `PageContext`, the payload that mirrors the context's own fields, and atomic `.tmp` → validate → rename |
| `src/docflow/workflow/stages.py` | `ORC-04`: `create_stage`, `set_stage_status`, `claim_stage`, `release_stage`, `register_stage_outputs` |
| `src/docflow/workflow/detection.py` | `ORC-05`: `detect_input_type` (PDF / IMAGE / UNSUPPORTED) |
| `src/docflow/workflow/planning.py` | `ORC-06`: `build_execution_plan` and `apply_forces` |
| `src/docflow/workflow/resolution.py` | `ORC-07`: `resolve_stage`, the fixed decision order |
| `src/docflow/workflow/reuse.py` | `ORC-08`: `is_stage_reusable`, `validate_stage_outputs` |
| `src/docflow/workflow/dependencies.py` | `ORC-09`: `STAGE_DEPENDENCIES`, `dependencies_of`, `downstream_of`, `invalidate_downstream` |
| `src/docflow/workflow/preparation.py` | `ORC-10`: `prepare_document`, `prepare_pdf_document`, `prepare_image_document` |
| `src/docflow/workflow/execution.py` | `ORC-11`: `process_pages`, `process_page_context`, `stop_boundary` |
| `src/docflow/workflow/selection.py` | `ORC-12`: `select_source`, `select_extraction_strategy`, `ocr_skip_reason`, `readable`, the artifact key vocabulary |
| `src/docflow/workflow/llm_input.py` | `ORC-13`: `build_llm_input` |
| `src/docflow/workflow/invocation.py` | `ORC-14`: `run_pdf`, `run_image_processing`, `run_ocr`, `run_llm`, `result_succeeded`, `describe_failure` |
| `src/docflow/workflow/resume.py` | `ORC-15`: `load_resumable_context`, `recover_running_stages` |
| `src/docflow/workflow/errors.py` | `ORC-16`: `handle_processor_error`, `MAX_STAGE_ATTEMPTS` |
| `src/docflow/workflow/consolidation.py` | `ORC-17`: `consolidate_page_result`, `build_document_result`, `execution_summary`, `workflow_decisions`, `workflow_errors`, `document_status` |
| `src/docflow/workflow/tracing.py` | `ORC-18`: `register_decision`, `register_error`, `append_workflow_trace` |
| `src/docflow/workflow/runner.py` | the shared stage lifecycle: resolve → record → claim → invoke → retry, used by both execution levels |
| `src/docflow/workflow/configuration.py` | the one place the run's configuration is read, and the one place a missing key is refused by name |
| `src/docflow/workflow/keys.py` | what each stage consumes, and the key that follows from it |
| `src/docflow/workflow/entrypoints.py` | `ORC-19`: `process_document`, `process_page`, `resume_document` |
| `tests/fakes/processors/__init__.py` | the four **contract-level** fakes: whole processors, installed at their public entry points, counting their calls and writing real artifacts |
| `tests/workflow/**` | one module per task, 110 tests: the four acceptance scenarios, the three invariants, and a unit test per primitive |

`tests/fakes/processors/` is a new sibling of `tests/fakes/engines/`, and the two levels are
deliberately separate: the engine doubles replace an engine call *inside* a real processor, these
replace a whole processor at its contract. `README.md` §9.7 is what says neither may stand in for
the other.

**Tasks.** All nineteen are done, in the subplan's waves:

| Wave | Tasks | Status |
|---|---|---|
| 1 — Foundation | `ORC-01` … `ORC-05` | done |
| 2 — Decision core | `ORC-06` … `ORC-09` | done |
| 3 — Execution path | `ORC-10` … `ORC-14` | done |
| 4 — Resilience | `ORC-15`, `ORC-16` | done |
| 5 — Consolidation & QA | `ORC-17` … `ORC-19` | done |

**Gate evidence.**

```
pytest                     613 passed
ruff check .               All checks passed!
ruff format --check .      161 files already formatted
pylint src tests           10.00/10
```

`ORC-19` also owns the no-engine rule at this level. The whole suite, orchestrator included, is
green with the Poppler binaries off the `PATH` — and the orchestrator reaches no engine at all: it
calls the four processors through their **public entry points**, which is what the fakes replace.

```
env -i PATH=/usr/bin:/bin "$(which python)" -m pytest -q    613 passed
command -v pdfinfo                                          not reachable
```

**Invariant evidence.** The three invariants of subplan §6 were mutation-falsified this session —
resume reuses / force invalidates downstream / reuse needs a key match. Each was mutated, observed
red, restored by re-applying the exact inverse edit (`git diff` on the file empty afterwards), and
observed green. **The canonical four-field records live in the root `README.md`** (the table under
"Rules that will bite you"), where `GEN-16` audits them; this entry points at them rather than
copying them.

**Decisions taken in code.**

1. **Stage status stays the shared nine.** `StageExecution.status` and `PageContext.status` are
   `docflow.states.StageState`; the two extra words the orchestrator needs — `PARTIAL` and
   `REVIEW_REQUIRED` — are **document** statuses (`DocumentStatus`), so a stage that could not
   fully succeed is `FAILED` while the document it belongs to says `REVIEW_REQUIRED`. That keeps
   one closed vocabulary for stages instead of a second enum spelling the same nine words.
2. **`PageContext.artifacts` gained two keys beyond §3.1's list**: `ocr_ready_image` and
   `vlm_ready_image`. The image processor publishes three representations and the orchestrator has
   to tell them apart; reusing `normalized_image` for the VLM variant would misname the artifact
   the LLM stage consumes. `PAGE_ARTIFACT_KEYS` is derived from the contract's `PageArtifactKey`
   literal with `typing.get_args`, so the vocabulary is written once.
3. **A dry run returns a `DocumentResult` whose `final_result` is the plan and whose `status` is
   `PAUSED`** — nothing ran, and the document is still resumable. Preparation also skips the PDF
   stage under `dry_run`: knowing the page count would require running the very stage the run is
   inspecting, so a fresh dry run plans the stages it can know about, and a resumed one plans
   every page.
4. **`is_stage_reusable` accepts `SUCCESS` *or* `REUSED`.** A run records a reused stage as
   `REUSED` (that is what invariant 1 asserts), so the next resume must still see a valid result;
   `SUCCESS`-only would make the second resume re-run everything.
5. **The request configures all four stages, plus the two policy flags, or it is refused by
   name.** `options["output_dir"|"pdf"|"image"|"ocr"|"llm"]` and `policies["allow_ocr"|"allow_vlm"]`
   are read in `configuration.py`; a missing key raises `WorkflowConfigurationError`, which
   `process_document` converts into a `FAILED` `DocumentResult` with a `CONFIGURATION_ERROR`
   record. No default DPI, model, schema or engine is substituted anywhere.
6. **A direct image input creates no PDF stage at all** — a decision records
   `direct_image_input` — so nothing in the summary has to be read as "the PDF stage ran and
   silently did nothing".
7. **`execution_summary` is stage → `StageState` plus `reused`, `skipped` and `decisions`**, and
   `DocumentResult.decisions` / `.errors` carry the page-level records too. "Every decision taken"
   is what that field promises, and the acceptance criterion asks for both places.
8. **`PageContext.results` is not serialized.** A resumed run re-derives what it needs from the
   artifacts on disk and the decisions already recorded — which is exactly why the resume mapping
   can be `SUCCESS → REUSE` without re-running the processor. Tagged `# TODO: [MVP]`.
9. **The LLM stage registers no artifacts.** `LLMResult` exposes no artifact list, so its reuse
   rests on status and key alone; tagged `# TODO: [MVP]` in `reuse.validate_stage_outputs` and
   `invocation.run_llm` — the processor contract is what has to carry the paths.
10. **`MAX_STAGE_ATTEMPTS = 2`**, a named PoC constant with its `# TODO: [MVP]` to become a
    configuration key, following the `image` thresholds precedent.
11. **`tests/test_skeleton.py`'s stub check was inverted, not deleted.** No *documented entry
    point* may ship `raise NotImplementedError` any more; the abstract methods of the LLM
    provider base class are deliberately out of scope, because the check is about the published
    surface.
12. **Pylint's `duplicate-code` was removed by extraction, not suppression** — with one
    exception. `tests/workflow/samples.py` now builds each stage's options from that processor's
    own sample builder, `decision_record` / `error_record` are produced by the production writers
    (`register_decision` / `register_error`) rather than by a copy of their shape, and
    `tests/llm/samples.py::build_result` is the single `LLMResult` builder (used by
    `tests/llm/test_contracts.py`, `tests/llm/primitives/test_validation.py` and the orchestrator's
    fake). The exception is `tests/fakes/processors/__init__.py`, which suppresses `duplicate-code`
    inline with its reason: a test double may not import the production seam it stands beside,
    because nothing under `src/` may import anything under `tests/`.

**Left stale (owner).** No pre-existing file under `docs/plan/` or `docs/idea/` was edited; the
root `README.md` gained the mutation records (it is the developer quickstart, not a plan artifact).
These now disagree with the code and need their owner:

| Document | What is stale | Owner |
|---|---|---|
| `docs/plan/issues/wbs-orquestador.md` | header and §2 still say `NOT_STARTED` for all nineteen tasks; flipping it is a plan revision, not a code edit | plan owner |
| `docs/plan/subplan-orquestador.md` §3.1 | "Stage states" lists eleven members (`PARTIAL`, `REVIEW_REQUIRED` included), where `README.md` §9.6 closes the shared set at nine; the code keeps nine stage states and carries those two as document statuses (decision 1) | plan owner |
| `docs/plan/subplan-orquestador.md` §3.1 | the `PageContext` artifact list does not mention `ocr_ready_image` / `vlm_ready_image` (decision 2) | plan owner |
| `docs/plan/subplan-orquestador.md` §3.1, `DocumentRequest` | lists `input_path`, `input_type`, `workflow`, `policies`, `execution`, `options`, `metadata` and omits `document_id`, which Phase 0 froze on the request and the result | plan owner |
| `docs/plan/README.md` §5 | the Phase 2 and Phase 3 exit criteria are met by this pass (`pytest` 613 green, invariants falsified); the phase tables still describe the work as pending | plan owner |
| `tests/fixtures/manifest.json` | still knows none of `pdf/`, `image/`, `ocr/` or `llm/`, and has no builder in the tree to re-run (already flagged) | fixture owner |
| `README.md`, phase table | the Phase 5 row still lists the lab tools the engine-double convention repurposed (already flagged) | plan owner |

**Next.** Phase 2 and Phase 3 are closed for the orchestrator. Phase 4 (hardening) inherits the
tagged follow-ups, and the most load-bearing of them is decision 9: the LLM processor's result
should expose the paths it published, so its stage can be validated like the other three. The
others are `parallel_pages` (the per-page state and `claim_stage` are already what a worker pool
needs), `request_stop` and its `stop_requested` field, the durable cross-process store behind the
same payload, and the processor-local `processing_key` the Phase 1 log flagged — which the
orchestrator now owns outright (`ORC-02`), so the reconciliation is to have the four processors
read it from `docflow.workflow.identity` instead of computing their own.

---

## 2026-09-27 — Phase 5 · lab tools (`SCR-01` … `SCR-10`)

**Delivered.** `scripts/` is a real bench now: shared plumbing plus five thin operator CLIs,
each invoked by path and each a caller, never a component.

| File | What it is |
|---|---|
| `scripts/tools/_cli.py` | the shared plumbing: `output_root`, `resolve_fixture`, `resolve_input`, `identity_for`, `print_header`, `print_result`, `print_error`, `exit_code_for`. Imports no contract and no engine; nothing under `src/` imports it |
| `scripts/tools/pdf.py` | `inspect`, `split`, `render`, `text`, `blocks`, `images`, `classify`, `run` — its own processor's primitives plus the contract |
| `scripts/tools/image.py` | `info`, `metrics`, `normalize`, `ocr-ready`, `vlm-ready`, `classify`, `run` |
| `scripts/tools/ocr.py` | `run`, `text`, `md`, `json`, `tables`, `blocks`, `metrics` — no `--engine` flag |
| `scripts/tools/llm.py` | `call`, `node`, `graph`, `resume`, `status`, `models`, `tokens`, `fake` — `--provider`/`--model` required on every inference subcommand |
| `scripts/tools/workflow.py` | `run`, `plan`, `status`, `resume`, `force`, `skip`, `stop`, `context` plus `--fake-llm`; imports no `docflow.*.primitives` module |
| `tests/test_lab_tools.py` | six structural guards, the parser/`--help` surface, the `_cli` unit tests, and one glue test per `run` path over the doubles the processors already ship |
| `tests/conftest.py` | the scripted-provider fixture, moved out of the test module so Pylint's `redefined-outer-name` has nothing to report |

**Tasks.** All ten are done, in the subplan's waves:

| Wave | Tasks | Status |
|---|---|---|
| 1 — Bench plumbing | `SCR-01` | done |
| 2 — Five tools | `SCR-02`, `SCR-03`, `SCR-04`, `SCR-05`, `SCR-06` | done |
| 3 — Verify | `SCR-07`, `SCR-08` | done |
| 4 — Close | `SCR-09`, `SCR-10` | done |

**Gate evidence.**

```
pytest                     653 passed
ruff check .               All checks passed!
ruff format --check .      169 files already formatted
pylint src tests           10.00/10
```

`653` is the Phase 2 exit's `613` plus the forty tests this pass added. The two Ruff gates read
the whole tree, so `scripts/tools/` is inside them; `pylint src tests` does not reach it, which is
decision 10 of the subplan and is stated rather than widened.

**Invariant evidence.** Four invariants were mutation-falsified this session — a tool adds no
behaviour, the library never imports a tool, `workflow.py` carries the orchestrator's frontier,
and no default model. Each was mutated, observed red, restored by the inverse edit, and observed
green, in the four-field shape `docs/plan/README.md` §7 fixes. **The canonical records live in the
root `README.md`** (the table `GEN-16` audits); this entry points at them and does not restate
them.

**Hand run (`SCR-07`), with the engines that are actually on this bench.** Poppler 25.02.0,
`opencv-python-headless` 5.0.0 and Docling 2.126.0 are installed; no model is served locally.

```
python scripts/tools/pdf.py inspect tests/fixtures/pdf/pdf_sample_mixed.pdf
  page_count: 1 · page_dimensions: [[612.0, 792.0]]                          exit 0
python scripts/tools/pdf.py classify tests/fixtures/pdf/pdf_sample_mixed.pdf --page 1
  metrics: {characters: 35, words: 6, text_blocks: 1, images: 1, text_coverage: 0.0047,
            image_coverage: 0.0, largest_image_coverage: 0.0} · classification: TEXT   exit 0
python scripts/tools/pdf.py render tests/fixtures/pdf/pdf_sample_text.pdf --page 1 --dpi 150
  output: var/tools/pdf/pdf_sample_text-3cf04b08/page_001_150dpi.png           exit 0
python scripts/tools/pdf.py inspect tests/fixtures/pdf/pdf_corrupt.pdf
  ERROR CORRUPTED_PDF: pdfinfo reported a syntax error
    {"exit_code": 1, "stderr": "Syntax Error: Couldn't find trailer dictionary …"}   exit 1

python scripts/tools/image.py info    tests/fixtures/image/skewed_text.png
  160x120, 3 channels, format png, size 417, resolution null                  exit 0
python scripts/tools/image.py metrics tests/fixtures/image/skewed_text.png
  quality {blur 8957.81, sharpness 122.06, contrast 83.17, brightness 204.09, noise 0.77},
  orientation 0, skew -86.58, text_regions 5, text_coverage 0.427               exit 0
python scripts/tools/image.py classify tests/fixtures/image/skewed_text.png
  classification: TEXT_IMAGE                                                  exit 0
python scripts/tools/image.py metrics tests/fixtures/image/corrupt.png
  ERROR DECODE_ERROR: the engine could not decode …/corrupt.png               exit 1
python scripts/tools/image.py ocr-ready tests/fixtures/image/skewed_text.png --deskew
  ERROR WRITE_ERROR: the engine could not encode …/ocr_ready.png
    {"engine_error": "cv2.error … could not find a writer for the specified extension"}   exit 1

python scripts/tools/ocr.py run tests/fixtures/ocr/ocr_prepared_text_and_table.png \
    --layout --tables --reading-order
  text "" · markdown "<!-- image -->" ×4 · tables 0 · blocks 0 · metrics.empty true
  validation EMPTY · artifacts text/document.md/document.json/tables/metadata   exit 0
python scripts/tools/ocr.py text tests/fixtures/ocr/ocr_blank.png
  text: ""                                                                    exit 0

python scripts/tools/llm.py --fixture casos/66cd35e9-….txt tokens \
    --provider ollama --model llama3.1 --context-window 4096
  tokens: 624 · context_window: 4096 · window_source: caller                    exit 0
python scripts/tools/llm.py --fixture casos/66cd35e9-….txt tokens \
    --provider ollama --model llama3.1
  ERROR MODEL_UNAVAILABLE: ollama does not offer the model 'llama3.1' {"status": 404}  exit 1
python scripts/tools/llm.py --fixture casos/66cd35e9-….txt --out var/tools/llm/lab-fake \
    --run-id lab-fake-run fake --provider ollama --model llama3.1 \
    --task extract --template simple_extract --schema simple
  first : {classify: EXECUTE, extract_a: EXECUTE, …, consolidate: EXECUTE}
  second: {classify: REUSE,   extract_a: REUSE,   …, consolidate: REUSE}        exit 0
python scripts/tools/llm.py --out var/tools/llm/lab-fake status
  run_dir …/lab-fake · state graph default_inference · final_result status SUCCESS
  node states {classify: REUSED, …, consolidate: REUSED}                        exit 0

python scripts/tools/workflow.py <globals> plan tests/fixtures/pdf/pdf_sample_text.pdf
  status: PAUSED · plan [PDF EXECUTE no_valid_result] · no processor invoked     exit 0
python scripts/tools/workflow.py <globals> stop tests/fixtures/pdf/pdf_sample_text.pdf --after PDF
  status: PAUSED · PDF SUCCESS (3 pages) · IMAGE/OCR/LLM NOT_STARTED            exit 0
python scripts/tools/workflow.py <no --pdf options> run tests/fixtures/pdf/pdf_sample_text.pdf
  status: FAILED · errors [{"stage":"DOCUMENT","type":"CONFIGURATION_ERROR",
    "message":"the PDF stage requires options['pdf']; no default is substituted"}] exit 1
```

Inputs untouched across the whole run: the nine fixture SHA-256s recorded before and after are
identical (e.g. `3cf04b0804518207…` for `pdf_sample_text.pdf`, `ca59523f4d49d3e0…` for
`skewed_text.png`, `c06a828f76fa3535…` for the `casos/` text). Output landed under
`var/tools/<tool>/<stem>-<hash8>/`; `git status --short` shows only the intended source, test and
docs changes, and `git check-ignore -v var/tools/pdf` answers `.gitignore:15:/var/`.

**Decisions taken in code.**

1. **Global flags before the subcommand, subcommand flags after it.** `--fixture`, `--fixtures-root`, `--json`, `--out`, `--document-id`, `--run-id` belong to the tool; `--page`, `--dpi`, `--provider`, `--model`, `--template`, `--schema`, `--context-window`, `--option` belong to the subcommand. That is the two spellings the runbook quotes (`pdf.py inspect <path>` and `pdf.py --fixture <name> render --page 2 --dpi 300`), and the positional therefore sits on the subparser while `--fixture` sits on the root.
2. **The provider/model requirement is an explicit check, not `required=True`.** `_require()` calls `parser.error` after parsing, so injecting a `default=` is *observable*: invariant 4 mutates exactly that and the test goes red. `required=True` would have made the mutation a no-op and the invariant unfalsifiable.
3. **The tools put the repository on `sys.path` themselves.** They are invoked by path and this checkout is not installed, so each tool inserts the repo root, `src/` and its own directory before importing the library (`# noqa: E402`, with the reason on the line). It is plumbing, not a seam: no contract, no engine.
4. **`image.py info` decodes.** The subplan §3.4 note says "no pixels decoded", but the symbols the same row names — `get_image_metadata` and `get_image_dimensions` — both take a decoded array. The map wins over the note; the deviation is registered below.
5. **`workflow.py --fake-llm` reaches the seam dynamically.** It installs the scripted provider with `importlib.import_module("docflow.llm.primitives")`, never a static import, so guard 4 holds while the patch still lands on the provider's own seam — below the orchestrator's frontier.
6. **The OCR tool composes its own processor's primitives.** `text`/`md` call one translator over one conversion; `json`/`tables`/`blocks`/`metrics` assemble the document the way §3.4's rows name. That is bench plumbing over the exception §3.2 grants (`ocr.py` may drive its own `primitives/`), and it transforms nothing itself.
7. **One library fix, forced by the bench.** `image/primitives/_write_image` now catches the engine's own exception and types it as `WRITE_ERROR`; before, it escaped the contract as a raw traceback. A failure the seam can name must never reach the operator as a crash.

**Found by the bench (the point of the exercise).**

| Finding | Evidence | Owner |
|---|---|---|
| **The image processor cannot publish any image artifact with its real engine.** `publish_artifact` writes through `normalized.png.tmp`, and the engine infers its encoder from the extension, so `imwrite` refuses it. Every one of `normalize`, `ocr-ready`, `vlm-ready` and any document run that prepares an image fails | `ERROR WRITE_ERROR … could not find a writer for the specified extension in function 'imwrite_'` | `IMG-*` — a processor fix plus the test update it needs. **Not fixed here**: the temp name is frozen by `tests/image/primitives/test_publication.py` ("normalized.png.tmp") and modelled by `tests/fakes/engines/fake_opencv.py`, so the fix is a processor change, and this subplan's §7 puts it out of scope for `SCR-07` |
| The engine's OCR backend logs INFO lines to **stdout**, so they interleave with a tool's payload (and would sit beside a `--json` body) | `[INFO] … [RapidOCR] base.py:23: Using engine_name: onnxruntime` before the payload | `OCR-*` |
| With default options the committed 240×120 OCR fixtures extract as `EMPTY`; a blank page is data, so the run reports `success` + `EMPTY` rather than a failure | `text "" · metrics.empty true · validation EMPTY` | observation, no owner |
| Poppler reports no placement for an embedded image, so `classify` cannot measure image dominance: `images: 1` still yields `classification: TEXT` | `image_coverage 0.0` with `images 1` | already tagged `# TODO: [MVP]` in `pdf/primitives/composition.py` |
| No model is served on this bench, so `llm call`/`graph`/`resume`/`models`/`tokens`-without-a-window return a typed `MODEL_UNAVAILABLE`; the scripted `fake` path is what demonstrates the chain and its resume | `ERROR MODEL_UNAVAILABLE … {"status": 404}` | observation, no owner |

**Left stale (owner).** No pre-existing plan artifact was edited. These now disagree with the code:

| Document | What is stale | Owner |
|---|---|---|
| `docs/plan/issues/wbs-scripts.md` | header and §2 still say `NOT_STARTED` for all ten tasks; flipping it is a plan revision, not a code edit | plan owner |
| `docs/plan/README.md` §5 | the Phase 5 exit criterion is met by this pass; the phase text still reads as pending | plan owner |
| `docs/plan/subplan-scripts.md` §3.4 | the `image.py info` row's "no pixels decoded" note (decision 4), and the `ocr.py` representation rows read as if one primitive were enough where the run must first convert | plan owner |
| `.github/copilot-instructions.md` | `SCR-10` pointed the layout and the "two entry points" bullet at `scripts/tools/`; its Project Identity still cites `docs/artifacts/` (`prd.md`, `sad.md`, `wbs.md`, `kernel-cli.md`, `traceability.md`), which no longer exists | plan owner |
| `tests/fixtures/manifest.json` | still knows none of `pdf/`, `image/`, `ocr/` or `llm/` (already flagged) | fixture owner |
| `docs/plan/bitacora.md` (this file, earlier entries) | four historical rows describe the README's Phase 5 row as borrowing `PDF-14`/`IMG-15`/`OCR-14`/`LLM-16`; the planning pass has since reconciled the README, so the rows are history rather than live claims — the `SCR-10` sweep is expected to hit them and nothing else | plan owner |
| `docs/plan/README.md` §4.1 versus `subplan-scripts.md` §3.1 | §4.1 lists `context` last in `workflow.py`'s subcommands while §3.1 and the root README put it after `resume`; cosmetic, the set is identical | plan owner |

**`SCR-10` sweep, as run.** The six borrowed ids must not appear near "lab tool"/"scripts/tools"
outside the historical bitácora rows above:

```
grep -rniE 'lab tool|scripts/tools' docs/plan docs/idea .github README.md \
  | grep -E 'GEN-21|PDF-14|IMG-15|OCR-14|LLM-16|ORC-20'
docs/plan/bitacora.md:142,297,457,613   ← the four historical rows, nothing else
grep -n 'SCR-' docs/plan/issues/wbs-general.md
28:  | 5 | Lab tools, one operator CLI per processor | — | `SCR-01`…`SCR-10` … |
634: - **Issues:** `SCR-01`…`SCR-10` (delegated to `wbs-scripts.md` …)
```

**Next.** Phase 5 is closed; the programme's remaining work is the image processor's publication
defect above (the one finding that blocks a working bench from end to end), the double drift it
exposes — `fake_opencv.imwrite` accepts the `.tmp` name the real engine rejects — and, after that,
the `GEN-17` re-read of the four doubles on the next engine pin bump. Nothing else in the tools is
waiting on a plan decision.

---

## 2026-09-27 — Phase 5 · lab tools (`scripts/tools/`) refactor — one shared library

**Delivered.** The five tools carried the same frame five times. It now lives once, in
`_cli.py`, which becomes the bench's **common library**; each tool is what is actually its own —
its subcommands, its flags and its handlers.

| File | What changed |
|---|---|
| `scripts/tools/_cli.py` | grew from five helpers into the library: `bootstrap()`, `build_parser()`, `add_subcommand()`, `run_tool()`, `required()`, `key_values()`, `optional_path()`, `report_result()` and the `Handler` alias, beside the existing `output_root` / `resolve_fixture` / `resolve_input` / `identity_for` / `print_header` / `print_result` / `print_error` / `exit_code_for` |
| `scripts/tools/pdf.py` | lost its `sys.path` prelude, its `Handler` alias, its `main()` frame, its `--page`/`--dpi` refusals, its `_optional_path` and its `print + exit code` tails |
| `scripts/tools/image.py` | the same, plus the two repeated correction flags folded into one `_add_corrections` |
| `scripts/tools/ocr.py` | the same, plus its hand-rolled `KEY=VALUE` reader |
| `scripts/tools/llm.py` | the same, plus its `--provider`/`--model` check and its `status`-reads-`--out` special case, now the dispatcher's `out_only` |
| `scripts/tools/workflow.py` | the same, plus its `KEY=VALUE` reader and its `--fake-llm` install, now the dispatcher's `prepare` hook |
| `tests/conftest.py` | puts `scripts/tools/` on `sys.path` once, so `import _cli` resolves when a test imports a tool as `scripts.tools.<name>` |

```
git diff --numstat   (against 9a23dd5, the commit that landed the tools)
scripts/tools/_cli.py    +204 -12        the library growing
scripts/tools/pdf.py      +41 -76  ┐
scripts/tools/image.py    +29 -62  │
scripts/tools/ocr.py      +24 -53  ├─ −185 lines of frame removed from the five tools
scripts/tools/llm.py      +57 -108 │
scripts/tools/workflow.py +36 -73  ┘
tests/conftest.py         +13  -0        the one path line the tests need
```

**Decisions taken in code.**

1. **The library is still `_cli.py`, not a new package.** `subplan-scripts.md` §3.1 fixes the layout as `_cli.py` plus the five tools and `SCR-08`'s guard 1 asserts exactly that set, so a `scripts/tools/_lib/` package would be a plan revision with no behaviour to show for it. "A library for the common tasks" is a property of `_cli.py`, which is why it keeps the name the plan froze.
2. **`_cli` bootstraps `sys.path` at import; the tools carry no prelude.** The library inserts the repository root and `src/`, so a tool's `import docflow` works with no `pip install`. The tools' own directory is a *test-side* concern: a tool invoked by path already has it on `sys.path`, and only a test imports one as a module, so `tests/conftest.py` adds it once.
3. **`build_parser`/`add_subcommand` are the parser surface; the argument helpers went private.** A tool no longer sees `add_common_arguments`/`add_input_argument` — it registers subcommands and adds the flags that are its own.
4. **The `--provider`/`--model` check stayed a post-parse `required()` call.** Making it `required=True` at the argument level would hide an injected `default=` behind identical behaviour and make the "no default model" invariant unfalsifiable.
5. **`run_tool` grew exactly two hooks, each for one real case.** `out_only=("status",)` for the LLM tool, which reads a run directory with `--out` alone; `prepare=` for the workflow tool, whose `--fake-llm` patches the provider seam before the handler runs. Nothing else was generalised speculatively.

**Gate evidence.**

```
pytest                     653 passed
ruff check .               All checks passed!
ruff format --check .      169 files already formatted
pylint src tests           10.00/10
```

No test changed except the three lines `tests/conftest.py` gained; the six structural guards and
every glue test are the same assertions as before. The hand run was re-smoked by hand after the
refactor — `pdf.py inspect`, `image.py info`, `ocr.py text`, `llm.py --out … status`,
`workflow.py plan`, `workflow.py --fake-llm plan` and `llm.py call` without `--model` (usage
error, exit 2) — and each behaves as the `SCR-07` entry records.

**Left stale (owner).** `docs/plan/README.md` §4.1 and `subplan-scripts.md` §3.1 describe
`_cli.py` as "shared plumbing — not a tool; holds no contract and reaches no engine". That is
still exactly true of it, and the layout, the tool set and the guard are unchanged, so no artifact
needs editing and no plan revision is owed: the entry above is the record that the module is now
read as a library rather than as five helpers.

**Next.** Unchanged from the entry above: the image processor's publication defect is still the one
thing standing between the bench and an end-to-end run.

---

## 2026-09-27 — Phase 5 · bench readme (`scripts/tools/readme.md`)

**Delivered.** The bench is documented where a person starts reading it, not only in the plan.

| File | What it is |
|---|---|
| `scripts/tools/readme.md` | what the bench is for (and why a bench rather than a test); the layout; invocation by path with no console script; `--help`; **where flags go** (global before the subcommand, subcommand flags after, the positional input on the subcommand); the common flags; the fixture roots and the `var/tools/<tool>/<stem>-<hash8>/` output root; the exit-code table; one subcommand → symbol table per tool; the three boundaries and the lab-bench exception, with `workflow.py`'s exclusion; how to work with no engine or no model; the gates' scope over `scripts/`; and the one known limitation |

**Decisions taken in code.**

1. **The readme is documentation, not a tool.** The *module* set of `scripts/tools/` is unchanged — `_cli.py` plus the five tools — so guard 1 still holds and the plan's layout is untouched. Only the guard's docstring was tightened, from "and nothing else" to **"and no other module"**, so the assertion (which globs `*.py`) and the prose agree about what the guard is about.
2. **The known limitation is stated in the readme, with its owner.** `image.py normalize` / `ocr-ready` / `vlm-ready` and any image-preparing `workflow.py` run cannot publish with the real engine (the entry above records the defect and its owner). Documenting the gap is better than a readme that lists the subcommands as if they worked; the failure itself is a typed `WRITE_ERROR` and exit `1`, so nothing crashes.
3. **The flag placement is documented explicitly** because the subplan's examples show `--fixture` before the subcommand and `--provider` after it, and that split is the first thing a new user trips over. The readme is now the place that says so, instead of the behaviour being inferred from a stack of `parser.error` calls.

**Gate evidence.**

```
pytest                     653 passed
ruff check .               All checks passed!
ruff format --check .      170 files already formatted
pylint src tests           10.00/10
```

**Left stale (owner).** None: the readme is new, it describes the committed tools, and it points at
`subplan-scripts.md`, `wbs-scripts.md` and this log rather than restating a decision that could
drift from them. Every claim in it was read off the code or the `SCR-07` hand run.

---

## 2026-09-27 — Phase 5 · the readme's examples, run as written

**Delivered.** The bench readme's examples now run: the two that did not were fixed at their cause,
not by rewording.

| File | Change |
|---|---|
| `scripts/tools/_cli.py` | `resolve_fixture` gained its documented bare-name rule: after a path and a `<root>/<name>` spelling both miss, the roots are searched for a file of that name at any depth; exactly one match resolves, two are refused by name instead of guessed |
| `tests/test_lab_tools.py` | two tests: a bare name resolves to the nested fixture the plan's scenario names, and an ambiguous bare name is reported with both candidates |
| `scripts/tools/readme.md` | the invocation block runs as printed; `--fixture`'s row states the depth rule; "where flags go" now names `workflow.py`'s global flags, `--dry-run` and `--fake-llm` included, and its subcommand-only `--stages`/`--after` |

**What the run found.** Three defects, two of them the readme's and one the code's:

1. **`--fixture pdf_sample_mixed.pdf` did not resolve.** The resolver only tried `<root>/<name>`, so
   a bare name whose file lives one level down (`tests/fixtures/pdf/`) was a usage error, exit `2`.
   This is a **code defect**: `subplan-scripts.md` decision 5 freezes "`--fixture` resolves a bare
   name", and §5's scenario is literally *Given `--fixture pdf_sample_mixed.pdf` … Then the run
   header prints the resolved absolute path under "tests/fixtures/"*. A bare name that matches two
   files (`a6d79e19-….png` is committed under both `casos/` and `chicos/`) is refused with both
   paths printed — the tree has real collisions, so "search" without that rule would be a guess.
2. **`render --page 2` cannot exist.** `pdf_sample_mixed.pdf` is the one-page mixed sample
   (`tests/fixtures/pdf/build_samples.py`: "one page with both a text layer and an embedded image").
   The library already behaved correctly — typed `PAGE_EXTRACTION_ERROR`, exit `1`, no traceback —
   so the example, not the tool, was wrong; it now renders page 1 at the same 300 dpi.
3. **`workflow.py plan <input> --dry-run` was unspellable.** `--dry-run` is a **global** flag (root
   parser), so after the subcommand argparse exits `2`; and `plan` already implies it
   (`dry_run=args.subcommand == "plan" or bool(args.dry_run)`), so the flag was redundant as well as
   misplaced. The same sketch carried no request options, so even a correctly placed `--dry-run`
   would have met the library's own refusal — `options["pdf"|"image"|"ocr"|"llm"]` and both policy
   keys are required, refused by name. The example is now a **complete** request with no `--dry-run`.

The fourth example's `casos/<uuid>.txt` placeholder is now the committed UUID the plan's own §3.3
line uses, so the block is copy-pasteable.

**Hand run, all four examples as the readme now prints them.**

```
python scripts/tools/pdf.py inspect tests/fixtures/pdf/pdf_sample_mixed.pdf
  page_count: 1 · exit 0
python scripts/tools/pdf.py --fixture pdf_sample_mixed.pdf render --page 1 --dpi 300
  input: …/tests/fixtures/pdf/pdf_sample_mixed.pdf · output: …/page_001_300dpi.png · exit 0
python scripts/tools/workflow.py --allow-ocr --no-allow-vlm --pdf-dpi 150 --image-normalize \
    --ocr --task extract --provider ollama --model llama3.1 --template simple_extract \
    plan tests/fixtures/pdf/pdf_sample_text.pdf
  status: PAUSED · decision dry_run "planned_stages": 1 · no processor invoked · exit 0
python scripts/tools/llm.py --fixture casos/66cd35e9-….txt call --provider ollama \
    --model llama3.1 --task extract --template simple_extract --schema simple
  status: FAILED · MODEL_UNAVAILABLE ollama does not offer the model 'llama3.1' {"status": 404}
  exit 1 — the documented failure, no model is served here
python scripts/tools/ocr.py --help                              exit 0
python scripts/tools/ocr.py run --help                          exit 0
python scripts/tools/pdf.py --json inspect …/pdf_sample_mixed.pdf
  stdout parses as JSON; the run header sits on stderr   exit 0
```

**Mutation evidence (Invariant / Mutation / Observed failure / Restored green).**

```
Invariant     a bare fixture name resolves to the one file of that name under a root
Mutation      _cli.resolve_fixture: replace the root search with an empty list
Observed      test_resolve_fixture_finds_a_bare_name_in_a_nested_root  FAILED
              test_resolve_fixture_refuses_an_ambiguous_bare_name      FAILED
              (2 failed, 2 passed with -k resolve_fixture — the ambiguity case falls back to
              "not found", so the assertion on the message is what carries it)
Restored      the inverse edit; 4 passed with -k resolve_fixture
```

**Gate evidence.**

```
pytest                     655 passed
ruff check .               All checks passed!
ruff format --check .      170 files already formatted
pylint src tests           10.00/10
```

**Left stale (owner).** `subplan-scripts.md` §3.3 keeps both bad example lines (`--page 2` on the
one-page mixed sample, and `--dry-run` after `plan`). The frozen artifact is **not** edited: a
copied example is not a decision, and changing one is a plan revision (subplan + WBS in one pass)
for no behaviour. The readme and this entry carry the corrected form; whoever next revises
`subplan-scripts.md` should lift it from there. Owner: bench owner.

**Next.** Unchanged: the image processor's publication defect is still the one thing standing
between the bench and an end-to-end run.

---

## 2026-09-27 — Phase 5 · `pdf.py inspect`, run as written

**Delivered.** The bench's human output no longer states its input twice.

| File | Change |
|---|---|
| `scripts/tools/_cli.py` | `HEADER_STATED_KEYS = {"input"}`: `print_result`'s human branch skips a key the run header already stated; the `--json` body keeps it |
| `tests/test_lab_tools.py` | two tests over the inspect path: the human summary states the resolved input once (in the header, never on stdout), and the JSON body still names it |
| `scripts/tools/readme.md` | the stderr-split paragraph now says the header is the run's *one* statement of its input, and why the two renderings differ |
| `README.md` | the front page's lab-tools sketch loses `plan mi.pdf --dry-run` (unspellable: `--dry-run` is global, and `plan` already implies it) for a comment that says so |

**What the run found.** `python scripts/tools/pdf.py inspect tests/fixtures/pdf/pdf_sample_mixed.pdf`
exits `0` and its payload is exactly `PDFDocumentInfo` — `page_count`, `page_dimensions`,
`engine_metadata`, the three fields `pdf/primitives/composition.py` defines and the readme's row
promises — so the handler was already conformant, and the *engine report* is the `pdfinfo`
key/value dump, which is why "Encrypted: no" and "PDF version: 1.7" arrive inside it. What was
wrong was the rendering: the run header states the resolved input (`input:  <path>`, stderr), and
every primitive-driving payload stated it again (`input: <path>`, stdout, one space), so a terminal
showed the same path twice with different alignment — an output that reads like the command ran
twice. `render` is worse still: its payload's `output` is the published PNG while the header's
`output` is the run root, two different facts under one word.

**Fix.** The header is the run's one statement of its input. It is also the *only* statement of it
when the run ends in a typed failure and no payload is printed at all, which is why the rule is
"the human summary does not repeat it" rather than "the payload does not carry it": a `--json` body
read on its own still has to name the file it describes, so it keeps the key.

**Mutation evidence (Invariant / Mutation / Observed failure / Restored green).**

```
Invariant 1   the human summary does not repeat a key the header stated
Mutation      _cli.print_result: stop skipping HEADER_STATED_KEYS in the human branch
Observed      test_pdf_inspect_states_its_input_once  FAILED  (1 failed, 1 passed)
Restored      the inverse edit; 2 passed with -k "states_its_input_once or keeps_the_input"
Invariant 2   the --json body keeps the input the header states
Mutation      _cli.print_result: drop HEADER_STATED_KEYS from the JSON branch too
Observed      test_json_keeps_the_input_the_header_states  FAILED  KeyError: 'input'
Restored      the inverse edit; 2 passed with the same -k
```

**Gate evidence.**

```
pytest                     657 passed
ruff check .               All checks passed!
ruff format --check .      170 files already formatted
pylint src tests           10.00/10
```

**Left stale (owner).**

- `_cli.identity_for`'s docstring says the document and run identities are "both printed in the run
  header", and they are not: `print_header` prints `input`, `output` and whatever `header_extra`
  adds (`llm.py`'s `assets_dir`). The flags are recorded in the request, which is what the readme
  says and what the subplan freezes; the docstring overstates it. Also worth a decision: the four
  primitive-driving subcommands accept `--document-id`/`--run-id` and can only ignore them, since
  no request is built on those paths — a global flag that a subcommand silently drops is the
  "dead flag" the subplan's §8 risk table names. Owner: bench owner.
- The `output` collision above (run root vs published artifact) is left as found: renaming either
  is a change to what a hand run prints, and no plan or readme text fixes the payload's key set.

**Next.** Unchanged: the image processor's publication defect is still the one thing standing
between the bench and an end-to-end run.

---

## 2026-09-27 — Phase 5 · what the run header claims about output

**Delivered.** The header no longer names an output root for a subcommand that publishes no file.

| File | Change |
|---|---|
| `scripts/tools/_cli.py` | `print_header(..., publishes=)`; a report-only run prints `output: (none — this subcommand publishes no file)`. `run_tool` takes `report_only=` and passes `publishes=subcommand not in report_only` |
| the five tools | a `REPORT_ONLY` tuple declares which subcommands report on stdout and write nothing |
| `tests/test_lab_tools.py` | Guard 7 pins each tool's declaration; a glue test drives the three report-only `pdf.py` subcommands and asserts the filesystem stayed empty; a `_cli` unit test and a `pdf.py` glue test tie `publishes` to the line actually printed |
| `scripts/tools/readme.md` | "Output root" now says that only a publishing subcommand creates the directory, and that nineteen of the thirty-eight do not |

**Why.** `pdf.py inspect` printed `output: /…/var/tools/pdf/pdf_sample_mixed-9ed17407`, and no run
creates that directory: `inspect`, `text` and `blocks` report on stdout and publish nothing — and so
do sixteen more subcommands across the other four tools, nineteen of the thirty-eight. The line
promised a file the run never writes, which is the statement this project forbids everywhere else
("absence is stated, never faked"). What the header states now is its own truth: this is the run
root, or there is none.

**The sets, and how they were established.** Read off each handler's calls, then confirmed by hand
where the engines allow it:

```
pdf       inspect, text, blocks     files published after each: 0, 0, 0
          classify, images, split, render do write — classify because measuring image dominance
          extracts the page's embedded images
image     info, metrics, classify   read and measure only; the preparation pipelines and the
                                    contract write
ocr       text, md, json, tables, blocks, metrics    only ``run`` publishes its document
llm       node, status, models, tokens   node builds its request with no output directory on
                                         purpose; the inference subcommands persist state
workflow  plan, status, context     plan is a dry run and invokes no processor; the other five
                                    write through process_document
```

The header line itself was run once per tool: `image.py info`, `ocr.py text`, `llm.py tokens` and
`workflow.py plan` print `(none — …)`, `pdf.py render` prints the root; `workflow.py plan` from an
empty `var/` left no directory at all.

**Mutation evidence (Invariant / Mutation / Observed failure / Restored green).**

```
Invariant 1   what the run frame reports is what the header states
Mutation      _cli.run_tool: pass publishes=True instead of consulting report_only
Observed      test_the_pdf_header_states_whether_the_subcommand_publishes  FAILED  (2 failed)
Restored      the inverse edit; 10 passed with -k "publishes or declares"
Invariant 2   the declared sets are the ones the tools actually have
Mutation      pdf.py: REPORT_ONLY gains "classify" (which does publish)
Observed      test_every_tool_declares_the_subcommands_that_publish_nothing[pdf]  FAILED
Restored      the inverse edit; green with the same -k
Invariant 3   a subcommand the header calls report-only writes nothing
Mutation      pdf.py: _cmd_inspect writes report.json under the run root
Observed      test_a_report_only_pdf_subcommand_publishes_nothing[inspect-flags0]  FAILED
Restored      the inverse edit; 54 passed in tests/test_lab_tools.py
```

**Gate evidence.**

```
pytest                     667 passed
ruff check .               All checks passed!
ruff format --check .      170 files already formatted
pylint src tests           10.00/10
```

**Left stale (owner).**

- `--out` on a report-only subcommand is accepted and has nothing to redirect. The header and the
  readme now say so, but the flag is still not refused: refusing it would be a usage error the
  subplan does not list, so it stays a stated inert flag rather than an invented refusal.
- `pdf.py classify` publishes the page's embedded images as a side effect of measuring image
  dominance — `extract_images_from_page` publishes what it extracts — so a subcommand documented as
  "the `TEXT`/`IMAGE`/`MIXED` verdict" leaves files. Registered, not changed: suppressing that would
  mean a tool deleting what a primitive published, which is behaviour the library does not have.
- The `output` collision from the entry above (run root vs published artifact) is unchanged; with
  `output:` absent from a report-only header it is now visible only on a publishing subcommand,
  where `render` prints the root and then the PNG.

**Next.** Unchanged: the image processor's publication defect is still the one thing standing
between the bench and an end-to-end run.

---

## 2026-09-27 — Phase 5 · a directory where a file is expected

**Question answered.** Passing a **directory** — `pdf.py inspect tests/fixtures/pdf`, or the bare
name `pdf` — never reaches the library and never reaches an engine: `resolve_input` refuses it, and
the process exits `2`, which is the documented usage-error code. What was wrong was *why* it said
so. The message was `fixture 'tests/fixtures/pdf' was not found under …`, which is false twice over:
the path the caller gave is right there, and the bare name `pdf` even names a directory *inside* one
of the roots the message lists.

**Delivered.**

| File | Change |
|---|---|
| `scripts/tools/_cli.py` | a name that names a directory is refused **as one** — `fixture 'pdf' is a directory, not a file: /…/tests/fixtures/pdf` — for a path given outright and for a name looked up under a root; the nested-root fallback now keeps directories, so a name that is a directory deeper in the tree is refused the same way; an **empty or whitespace** name is refused as missing instead of being looked up as the working directory (`Path("")` is `.`) |
| `tests/test_lab_tools.py` | a directory is refused as a directory (bare name and path), and an empty name is a usage error that names the missing input |
| `scripts/tools/readme.md` | the fixture-roots paragraph states both refusals, and why a directory is not searched for a file |

The four observed runs, before and after:

```
pdf.py inspect tests/fixtures/pdf    ->  exit 2  "fixture 'tests/fixtures/pdf' was not found under …"
pdf.py inspect pdf                   ->  exit 2  "fixture 'pdf' was not found under …"
pdf.py inspect src                   ->  exit 2  "fixture 'src' was not found under …"
pdf.py inspect ""                    ->  exit 2  "fixture '' was not found under …"  (Path("") is ".")

after:
pdf.py inspect tests/fixtures/pdf    ->  exit 2  "… is a directory, not a file: /…/tests/fixtures/pdf"
pdf.py inspect pdf                   ->  exit 2  "… is a directory, not a file: /…/tests/fixtures/pdf"
pdf.py inspect src                   ->  exit 2  "… is a directory, not a file: /…/src"
pdf.py inspect ""                    ->  exit 2  "an input is required: pass a path or --fixture NAME"
pdf.py inspect …/pdf_sample_mixed.pdf ->  exit 0  (unchanged)
```

**Mutation evidence (Invariant / Mutation / Observed failure / Restored green).**

```
Invariant 1   a directory is refused as a directory, not reported missing
Mutation      _cli._directory_refusal: return "was not found" instead of naming the directory
Observed      test_resolve_fixture_refuses_a_directory[pdf]  FAILED
              test_resolve_fixture_refuses_a_directory[/…/tests/fixtures/pdf]  FAILED  (3 failed)
Restored      the inverse edit; 57 passed in tests/test_lab_tools.py
Invariant 2   an empty name is a missing input, not a lookup of the working directory
Mutation      _cli.resolve_input: drop the strip() check, keep `name is None`
Observed      test_an_empty_input_name_is_a_usage_error  FAILED  (the same 3-failure run)
Restored      the inverse edit; 57 passed
```

**Gate evidence.**

```
pytest                     670 passed
ruff check .               All checks passed!
ruff format --check .      170 files already formatted
pylint src tests           10.00/10
```

**Left stale (owner).** Not established: what the *library* does when a directory reaches a
contract, because the bench refuses one before any primitive is called, and the orchestrator builds
its own `DocumentRequest` from a path it is handed. A processor-side answer would be a contract
question, and `subplan-procesador-pdf.md` does not carry one; registered as unverified rather than
asserted. `docs/plan/subplan-scripts.md` §3.3's exit-code paragraph ("`2` a usage error … an
unresolvable input") already covers this case and needed no change.

**Next.** Unchanged: the image processor's publication defect is still the one thing standing
between the bench and an end-to-end run.

---

## 2026-09-27 — Phase 5 · the PDF bench over a folder (`SCR-11`, `SCR-12`)

**Requested.** A batch driver, `scripts/tools/batch_pdf.py`, that takes a folder, walks it
recursively and mirrors it under `var/` (`unacarpeta/sub1/a.pdf` → `var/batch_pdf/unacarpeta/sub1/…`),
plus a refactor so the batch reuses the PDF tool's methods instead of copying them.

**Delivered.**

| File | Change |
|---|---|
| `scripts/tools/_pdf.py` | **new**, `SCR-11`: the eight PDF methods, their payloads, their flag registration (`build_subcommands`) and the refusals for `--page`/`--dpi`. Not a tool — no `main`, no printing, no catch: a method returns a payload and raises the processor's typed failure |
| `scripts/tools/batch_pdf.py` | **new**, `SCR-12`: walks a folder, runs one command per PDF through `_pdf`, mirrors the tree under `var/batch_pdf/<folder>/` (or `--out`), writes each input's payload to `result.json` in that input's own directory, prints one line per input and a summary, and exits `1` if any input failed |
| `scripts/tools/pdf.py` | now a CLI over `_pdf`: parser, one handler factory, `main`. Its eight methods, their payload builders and `_run_options` moved, unchanged, into `_pdf` — the 57 lab-tool tests (including every pdf glue test) passed before and after, which is the evidence the move changed no behaviour |
| `scripts/tools/_cli.py` | four small additions the two callers needed: `BATCH_OUTPUT_ROOT` (`var/batch_pdf/…`), `write_payload` (the file half of `print_result`), `build_parser(positional=, subcommand_required=)` and `add_subcommand(input_argument=)` |
| `tests/test_lab_tools.py` | guard 1's set, guard 3 over `_pdf` too, `DOCUMENTED_SUBCOMMANDS["batch_pdf"]`, `REPORT_ONLY["batch_pdf"] = ()`, and five new tests: the mirrored tree, the stated default, the failure count, the folder refusal, `write_payload` |
| `scripts/tools/readme.md` | the layout table, the invocation block, and a `batch_pdf.py` section: the mirror, the record per input, the default command, the exit codes |

**Two things the request could not have as stated, and what was done instead.**

1. **`scripts/tools/pdf/library.py` cannot exist.** A package and a module of the same name in one
   directory are resolved to the *package*: `import pdf` beside `pdf/` returns `pdf/__init__.py`
   (verified: `import pdf -> /private/tmp/shadow/pdf/__init__.py`, `is_package: True`), which would
   break `tool_module("pdf")` and every tool's `import pdf`. The shared layer is therefore
   `scripts/tools/_pdf.py` — the leading underscore the subplan's own naming convention reserves
   for "a module that is not a tool".
2. **The command is the caller's, not the tool's.** `batch_pdf.py` runs the subcommand stated, with
   the flags `_pdf` registered for it; with none stated it runs `inspect` — the one method that
   needs no further flag — and the run header says `command: inspect (default, none stated)` rather
   than leaving the choice silent. So `batch_pdf.py unacarpeta` is a complete command, and
   `batch_pdf.py unacarpeta run --dpi 200 --extract-text` is the contract over the same tree.

**Hand run** (the shape the request described, then the readme's own line):

```
mkdir -p /tmp/unacarpeta/sub{1,2}
cp …/pdf_sample_text.pdf  /tmp/unacarpeta/sub1/
cp …/pdf_sample_mixed.pdf /tmp/unacarpeta/sub2/ ; cp …/pdf_corrupt.pdf /tmp/unacarpeta/sub2/
python scripts/tools/batch_pdf.py /tmp/unacarpeta
  == batch_pdf.py inspect ==  input /private/tmp/unacarpeta  output …/var/batch_pdf/unacarpeta
  command: inspect (default, none stated)
  pdf_sample_text.pdf:  ok     -> …/unacarpeta/sub1/pdf_sample_text
  pdf_corrupt.pdf:      FAILED -> …/unacarpeta/sub2/pdf_corrupt   ERROR CORRUPTED_PDF: …
  pdf_sample_mixed.pdf: ok     -> …/unacarpeta/sub2/pdf_sample_mixed
  files: 3 · succeeded: 2 · failed: 1                                          exit 1
var/batch_pdf/unacarpeta/sub1/pdf_sample_text/result.json
var/batch_pdf/unacarpeta/sub2/pdf_sample_mixed/result.json

python scripts/tools/batch_pdf.py tests/fixtures/pdf
  files: 4 · succeeded: 3 · failed: 1   (pdf_corrupt.pdf)                      exit 1
var/batch_pdf/pdf/{pdf_sample_image,pdf_sample_mixed,pdf_sample_text}/result.json
```

**Mutation evidence (Invariant / Mutation / Observed failure / Restored green).**

```
Invariant   a batch does not stop at the first bad file
Mutation    batch_pdf.main: break out of the loop when a record carries an error
Observed    test_batch_pdf_counts_every_failure_and_exits_one  FAILED  (1 failed, 66 deselected;
            one `ERROR CORRUPTED_PDF` instead of two)
Restored    the inverse edit; 680 passed
```

**Gate evidence.**

```
pytest                     680 passed
ruff check .               All checks passed!
ruff format --check .      172 files already formatted
pylint src tests           10.00/10
```

**Owed — the plan revision (`SCR-11`, `SCR-12`).** The code is in and gated; the frozen artifacts
still describe six modules and list batch runs as out of scope, so this is a plan revision and not
done yet. `subplan-scripts.md` §3.1 (the module set), §3.4 (the batch row and the shared layer),
§4 (the `SCR-11`/`SCR-12` rows, waves and critical path), §6 (guard 1's set) and §9 (**the
"batch corpus runs over `documentos/` and mirrored output trees" bullet is the decision this pass
reverses**); `issues/wbs-scripts.md` §1/§2/§3 (two issues, the ID range, the Depends/Blocks edges —
the subplan and its WBS move in one pass); `docs/plan/README.md` §4.1 and root `README.md`'s tool
table for the citation; and a `docs/feedback/` note that declares the reversal and is the winner
over the deleted bullet. Owner: this pass's author, next pass.

**Next.** That revision, before any further work on the bench: until it lands, `docs/plan/` and
`scripts/tools/` disagree about the module set. The image processor's publication defect is still
the one thing standing between the bench and an end-to-end run.

---

## 2026-09-27 — Phase 5 · the batch examples, on the real fixture folders

**Delivered.** `scripts/tools/readme.md`'s `batch_pdf.py` section no longer runs on a placeholder
folder. Its four examples name folders that exist in the tree — `tests/fixtures/pdf`, the whole
`tests/fixtures`, `tests/fixtures/chicos`, `tests/fixtures/matrix` — and the observed mirror is
shown for one of them, plus the rule that `--out` does not repeat the walked folder's name.

**Hand run, one command per example, all four as printed.**

```
batch_pdf.py tests/fixtures/pdf        files: 4  · ok 3  · failed 1 (pdf_corrupt.pdf)   exit 1
batch_pdf.py tests/fixtures            files: 31 · ok 30 · failed 1                     exit 1
  → var/batch_pdf/fixtures/{casos,chicos,matrix,negativos,pdf,pdf_aptos_layout,
    pdf_escaneados,pdf_large}/<stem>/result.json
batch_pdf.py tests/fixtures/chicos run --dpi 200 --extract-text
                                       files: 6  · ok 6  · failed 0                     exit 0  (0.38 s)
  → each input's directory holds source/, page_001/, result.json
batch_pdf.py --no-recursive --out var/x tests/fixtures/matrix split
                                       files: 3  · ok 3  · failed 0                     exit 0
  → var/x/{scan-hidden-layer,scan150,three-invoices}/result.json
```

**One wording the run corrected.** The section said "every input gets a record"; the run showed a
failed input leaves no directory at all — there is no payload to file. It now says what happens:
a payload is filed as `result.json`, a failure is printed as the library's typed record and
counted, and no directory is created for it.

**Gate evidence.**

```
pytest                     680 passed
ruff check .               All checks passed!
ruff format --check .      172 files already formatted
pylint src tests           10.00/10
```

**Next.** Unchanged, and owed: the `SCR-11`/`SCR-12` plan revision named in the entry above.

---

## 2026-09-27 — Phase 5 · batch mode across the processors: the plan

**Delivered.** `docs/feedback/batch-mode-across-processors.md` — a decision note that plans the
batch pattern for image, OCR and LLM, and declares itself the winner over `subplan-scripts.md` §9's
"batch corpus runs over `documentos/` and mirrored output trees" bullet.

**What it settles.** Four tools, four layers, one frame: `_batch.py` (the folder frame — walk,
mirror, per-input record, summary, exit code — extracted from `batch_pdf.py`), `_image.py`,
`_ocr.py` and `_llm.py` on the `_pdf.py` precedent, and `batch_image.py`, `batch_ocr.py`,
`batch_llm.py`. Defaults `info` (image) and `text` (OCR) — the flag-free methods that publish
nothing — and **none** for LLM, where `--provider`/`--model` are required so a bare run cannot be
honest. `batch_llm`'s subset is `call`, `graph`, `node`, `tokens` plus a `--fake` flag; `status`
(reads one run directory), `models` (one inventory, not a per-input question) and `fake` (a two-run
demonstration under one pinned `--run-id`) are not per-input methods. `batch_workflow.py` is out of
scope: the orchestrator's frontier plus a product feature, not a bench observation. The note also
fixes the input suffix sets, the guards to widen (1: the module set; 3: no engine named, over every
module; 7: the `REPORT_ONLY` pin per tool) and the risks (Docling's cost per image, the image
publication defect, no model served).

**Sequencing it prescribes.** 1) the plan revision — subplan §3.1/§3.4/§4/§5/§6/§9 and
`issues/wbs-scripts.md` §1/§2/§3 in one pass, `SCR-11`…`SCR-18`, with the shipped PDF pair recorded
as **done** and the bitacora as its evidence; plus the `docs/plan/README.md` §4.1/§6 and root
`README.md` citations. 2) `_batch.py`, and `batch_pdf.py` refactored onto it (behaviour-preserving;
the existing guards and glue tests are the evidence). 3) image. 4) OCR. 5) LLM. 6) the hand run of
the four batch tools over real fixture folders, recorded here, and the four QA gates.

**Gate evidence.**

```
pytest                     680 passed
ruff check .               All checks passed!
ruff format --check .      172 files already formatted
pylint src tests           10.00/10
```

**Owed.** The revision and the three implementations above, in that order. This pass changed no
code, no test and no frozen artifact — it is the plan those steps will be applied against.

---

## 2026-09-28 — Phase 5 · the batch plan applied: the frame and image (`SCR-11`…`SCR-13`)

**Delivered.** Steps 2 and 3 of `docs/feedback/batch-mode-across-processors.md`, each gated.

| File | Change |
|---|---|
| `scripts/tools/_batch.py` | **new**: the folder frame every batch tool runs on — `build_parser` (the folder positional and `--recursive`, no fixture flags), the walk (`inputs_under`), the mirror, the per-input record, the summary and the exit code |
| `scripts/tools/batch_pdf.py` | refactored onto `_batch`: it keeps what is its own — the suffix set, the default command, the layer, the error type it catches — and nothing else |
| `scripts/tools/_image.py` | **new**: the image bench's seven methods, moved from `image.py` with the payloads and flags, the pipelines still named where they run |
| `scripts/tools/image.py` | a CLI over `_image`: parser, one handler factory, `main` |
| `scripts/tools/batch_image.py` | **new**: the seven methods over a folder, the image suffixes, `info` as the bare run |
| `scripts/tools/_cli.py` | `fixtures=False`, for a tool that resolves no fixture; the batch's default root is now `_batch.default_root(tool)` |
| `tests/test_lab_tools.py` | guard 1's module set, guard 3 over `_batch` and `_image`, `batch_image`'s documented commands and its empty `REPORT_ONLY` pin, plus two glue tests (the mirrored tree, and `image.py` reading through the layer) |
| `scripts/tools/readme.md` | the layout table, the shared-frame paragraph and a `batch_image.py` section |

**A defect found on the way, and fixed.** The frame counted *exceptions* as failures only, so a
contract run that **returns** a failed status was counted as a success — a corpus in which every
input failed would have exited `0`. `_batch._failed` now asks `_cli.exit_code_for`, so one place
owns what "failed" means: a returned failure is counted, reported in the summary, and sets the exit
code. `batch_pdf.py`'s behaviour on `run` over a bad corpus changes with it, which is the fix.

**Hand runs.**

```
batch_pdf.py tests/fixtures/pdf      files: 4 · ok 3 · failed 1 (pdf_corrupt.pdf)   exit 1
image.py info …/color_layout.png     format png · 335 bytes · 160x120 · 3 channels   exit 0
batch_image.py tests/fixtures/image  files: 4 · ok 3 · failed 1 (DECODE_ERROR)       exit 1
  → var/batch_image/image/{color_layout,embedded_logo,skewed_text}/result.json
```

The `batch_pdf.py` run is byte-for-byte what the pre-refactor entry recorded, which is the evidence
the frame move changed no behaviour.

**Gate evidence.**

```
pytest                     688 passed
ruff check .               All checks passed!
ruff format --check .      175 files already formatted
pylint src tests           10.00/10
```

**Still owed, in the plan's order.** `_ocr.py` + `batch_ocr.py` (step 4), `_llm.py` +
`batch_llm.py` (step 5), the hand run of all four batch tools (step 6), and the **plan revision**
(step 1): `subplan-scripts.md` §3.1/§3.4/§4/§5/§6/§9 plus `issues/wbs-scripts.md` in one pass,
`SCR-11`…`SCR-18`, with §9's out-of-scope bullet reversed and
`docs/feedback/batch-mode-across-processors.md` as the winning decision.

**Next.** `_ocr.py` + `batch_ocr.py`, then the LLM pair, then the revision.

---

## 2026-09-28 — Phase 5 · OCR on the same two layers (`SCR-14`)

**Delivered.** Step 4 of `docs/feedback/batch-mode-across-processors.md`, gated.

| File | Change |
|---|---|
| `scripts/tools/_ocr.py` | **new**: the OCR bench's seven methods, moved from `ocr.py` with the payloads and flags, plus `SUFFIXES` — the inputs a processor takes are that processor's own fact |
| `scripts/tools/ocr.py` | a CLI over `_ocr`: parser, one handler factory, `main` (230 lines lighter) |
| `scripts/tools/batch_ocr.py` | **new**: the seven methods over a folder, `text` as the bare run, `run` the only method that publishes |
| `scripts/tools/_image.py` | `SUFFIXES` moved here from `batch_image.py`, so each layer states its processor's inputs |
| `tests/test_lab_tools.py` | `_ocr` in guard 3, `batch_ocr` in the documented commands and the `REPORT_ONLY` pin, plus three glue tests |
| `scripts/tools/readme.md` | the layout table and a `batch_ocr.py` section |

**Two defects found on the way, and fixed.**

1. **A bare run did not parse the command it made.** `_batch` inferred the default from
   `args.subcommand is None` after *not* parsing a subcommand — so the default's own flags were
   never registered, and `batch_ocr.py <folder>` died with `AttributeError: 'Namespace' object has
   no attribute 'ocr'`. `batch_pdf.py` and `batch_image.py` had the same hole, hidden only because
   `inspect` and `info` read no flag. The frame now **appends the default command to the arguments
   and parses it as a subcommand** (`_batch.resolve_command`), and takes `default` as an explicit
   argument instead of reading it back off the namespace: after that parse the two runs are
   indistinguishable there, and the header still has to say which one happened.
2. **An engine throw ended the corpus run.** `_conversion` called the engine call directly, so a
   file the engine refuses escaped as a traceback rather than as a typed failure — the run's first
   bad input killed a batch that promises one bad file does not. It is now typed the way the
   processor's own entrypoint types it (`ENGINE_ERROR`, `recoverable=False`), because the engine's
   exception class is not nameable without importing the engine.

**Mutation evidence** (each mutation applied, observed red, reverted, green again).

| Invariant | Mutation | Observed failure |
|---|---|---|
| An input the engine refuses is one input's failure, not the run's | the `try/except` typing removed from `_ocr._conversion` | `test_batch_ocr_types_an_engine_throw_and_keeps_going` red: the engine's `ValueError` escaped the batch |
| A default command is stated in the header, never silent | `default=default` → `default=False` in `batch_ocr.py` | `test_batch_ocr_mirrors_the_folder_it_walked` red: no `command: text (default, none stated)` |

**Hand runs** (the real Docling engine, installed locally).

```
ocr.py text …/ocr_prepared_text_and_table.png   text: (empty — the synthetic fixture has no glyphs)   14.1s
batch_ocr.py tests/fixtures/ocr                 files: 2 · succeeded: 2 · failed: 0                    exit 0
  → var/batch_ocr/ocr/{ocr_blank,ocr_prepared_text_and_table}/result.json
batch_pdf.py tests/fixtures/pdf                 files: 4 · succeeded: 3 · failed: 1                   exit 1
```

The `batch_pdf.py` line is again byte-for-byte what the previous entry recorded, which is the
evidence `resolve_command` changed no observable behaviour for the tools that already had a default.

**Gate evidence.**

```
pytest                     696 passed
ruff check .               All checks passed!
ruff format --check .      177 files already formatted
pylint src tests           10.00/10
```

**Still owed, in the plan's order.** `_llm.py` + `batch_llm.py` (step 5), the hand run of the LLM
pair (step 6), and the **plan revision** (step 1) — `subplan-scripts.md` §3.1/§3.4/§4/§5/§6/§9 plus
`issues/wbs-scripts.md` in one pass, `SCR-11`…`SCR-18`, with §9's out-of-scope bullet reversed.

**Next.** The LLM pair, then the revision.

---

## 2026-09-28 — Phase 5 · LLM on the same two layers (`SCR-15`), and a frame defect fixed

**Delivered.** Step 5 of `docs/feedback/batch-mode-across-processors.md`, gated.

| File | Change |
|---|---|
| `scripts/tools/_llm.py` | **new**: the LLM bench's eight methods, moved from `llm.py` with the payloads, the flags, `DEFAULT_ASSETS_DIR`, `SUFFIXES` and `install_fake` (the seam the three tools share) |
| `scripts/tools/llm.py` | a CLI over `_llm`: parser, one handler factory, `main` (390 lines lighter) |
| `scripts/tools/batch_llm.py` | **new**: four of the eight commands over a folder (`call`, `graph`, `node`, `tokens`), a **required** subcommand, `--fake` |
| `scripts/tools/_batch.py` | `header_extra`, so a batch states what its single-input twin states (the asset root) |
| `scripts/tools/batch_pdf.py` `batch_image.py` `batch_ocr.py` | `resolve_command` and the explicit `default` |
| `tests/test_lab_tools.py` | `_llm` in guard 3, `batch_llm`'s four documented commands and its `REPORT_ONLY` pin, guard 6 now names the folder for the four batch tools, six new tests |
| `scripts/tools/readme.md` | the layout table and a `batch_llm.py` section |

**Three defects found on the way, and fixed.** The first two were recorded in the Phase C entry;
this pass found the third.

3. **A returned failure was printed as `ok`.** The frame counted a contract's returned `FAILED`
   status as a failure (the Phase A fix) but still printed `name: ok -> …` for it, so a corpus in
   which *every* input failed printed three `ok` lines above `succeeded: 0 · failed: 3`. The line
   is now derived from the same `_failed` the summary uses, and the typed failure the payload
   itself states — under `error` for `run`, under `errors` for the LLM chain — is printed, since
   no exception carried it. Both shapes are read by `_batch._payload_failures`.

**Mutation evidence** (each mutation applied, observed red, reverted, green again).

| Invariant | Mutation | Observed failure |
|---|---|---|
| A returned failure is not reported as `ok` | the line forced back to `ok` | `test_batch_ocr_reports_a_returned_failure_as_a_failure` red: `': FAILED ->' not in 'a.png: ok -> …'` |
| A returned failure's own record is shown | `_cli.print_error(failures)` dropped | same test red: no `ERROR OCR_ERROR:` line |

**Hand runs.**

```
batch_llm.py --fake tests/fixtures-txt/casos call …   files: 3 · succeeded: 3 · failed: 0   exit 0
batch_llm.py tests/fixtures-txt/casos call …          files: 3 · succeeded: 0 · failed: 3   exit 1
  each input: `…: FAILED -> var/batch_llm/casos/<stem>` + `ERROR MODEL_UNAVAILABLE: ollama does not offer the model 'llama3.1'`
llm.py tokens --context-window 4096 …                 624 tokens, window_source: caller        exit 0
batch_ocr.py tests/fixtures/ocr                       files: 2 · succeeded: 2 · failed: 0      exit 0
```

The last line re-verifies the OCR batch after the frame change, and the `--fake`/no-model pair is
the same three inputs answered two ways — which is what the scripted provider is for.

**Gate evidence.**

```
pytest                     708 passed
ruff check .               All checks passed!
ruff format --check .      179 files already formatted
pylint src tests           10.00/10
```

**Still owed, in the plan's order.** The hand run of all four batch tools in one place (step 6 —
done piecemeal above), and the **plan revision** (step 1): `subplan-scripts.md`
§3.1/§3.4/§4/§5/§6/§9 plus `issues/wbs-scripts.md` in one pass, `SCR-11`…`SCR-18`, with §9's
out-of-scope bullet reversed and `docs/feedback/batch-mode-across-processors.md` as the winning
decision.

**Next.** The plan revision — the one thing standing between `docs/plan/` and `scripts/tools/`.

---

## 2026-09-28 — Phase 5 · the batch revision (`SCR-18`)

**Delivered.** Step 1 of `docs/feedback/batch-mode-across-processors.md` — the pass that makes
`docs/plan/` agree with `scripts/tools/`. Documentation only; no code, no test and no frozen
*decision* changed, only what the artifacts say the bench contains.

| Document | Change |
|---|---|
| `subplan-scripts.md` §3.1 | the fifteen-module layout, plus the layer split (`SCR-11`, `13`, `14`, `15`) and `_batch.py` (`SCR-12`) stated as design, not as an accident of the tree |
| `subplan-scripts.md` §3.2 | the lab-bench exception moved from the tools to the **layers** — after the split a single-file tool imports only `_cli` and its layer, so it no longer names a primitive either |
| `subplan-scripts.md` §3.3 | the batch output root (`var/batch_<processor>/<folder>/`), why a batch takes no `--fixture`, and the corpus exit code — `1` when any input failed, including one whose contract *returned* the failure |
| `subplan-scripts.md` §3.4 | a table of the four batch tools (layer, suffix set, default command, excluded commands) and the four rules they share |
| `subplan-scripts.md` §3.5 | the demonstration folders `SCR-17` records |
| `subplan-scripts.md` §4 | `SCR-11`…`SCR-18`, wave 5, and the extended critical path |
| `subplan-scripts.md` §5/§6/§7 | three batch scenarios, guards 1/3/6/7 rewritten to the real set, and four new invariants with their mutations |
| `subplan-scripts.md` §9 | the **reversal** of the out-of-scope bullet, a `batch_workflow.py` exclusion and the serial-walk decision, four new resolved decisions, and the stale-citation table |
| `issues/wbs-scripts.md` | the range, the summary, eighteen index rows with their Depends/Blocks edges, the eight new issues, the graph, wave 5, the critical path, the traceability rows and §11's reversal |
| `docs/plan/README.md`, `issues/wbs-general.md`, root `README.md` | every Phase 5 citation widened to `SCR-01`…`SCR-18`; the root readme's tool table gains the four batch tools, and its invariant table gains wave 5's four records |

**Nothing was renumbered.** `SCR-11`…`SCR-18` are appended; the wave-5 leg of the critical path is
`SCR-11 → SCR-12 → SCR-15 → SCR-17 → SCR-18`, and each of the eight has a row in the subplan's §4,
a row in the WBS index and a section in its detailed issues — verified by counting the three lists
(18 each), which is what the revision's acceptance criterion asks for.

**The reversal, recorded.** *"Batch corpus runs over `documentos/` and mirrored output trees"* is no
longer out of scope. `docs/feedback/batch-mode-across-processors.md` is the winning decision; the
reversal is scoped to the four processors' own folders — the committed fixture roots and any folder a
caller names — and does **not** reintroduce `documentos/`, which stays ignored, like the
`var/batch_<processor>/` trees a batch writes.

**Gate evidence** (unchanged by this pass — documentation only, and the gates were re-run to say so
rather than to assume it):

```
pytest                     708 passed
ruff check .               All checks passed!
ruff format --check .      179 files already formatted
pylint src tests           10.00/10
```

**Status.** With this entry the plan's six steps are closed: the layer and frame (`SCR-11`,
`SCR-12`), the three remaining pairs (`SCR-13`…`SCR-15`), the bench readme (`SCR-16`), the hand runs
(`SCR-17`) and the revision (`SCR-18`). `SCR-10` — the sweep of `wbs-general.md` and
`.github/copilot-instructions.md` — was already satisfied by the planning pass; its remaining
targets are named in `subplan-scripts.md` §9 and none of them is a batch citation.

---

## 2026-09-28 — Phase 5 · `_pdf.py` brought to the same shape as the other three layers

**Found by reading the tree, not by a failing test.** `SUFFIXES` was stated by `_image.py`,
`_ocr.py` and `_llm.py`, and read by their batch tools — but `_pdf.py` had no such declaration and
`batch_pdf.py` still carried its own `(".pdf",)` literal. The asymmetry is a leftover from the
order the work was done in: the image set had to move into a layer because `batch_ocr.py` needed a
source for it, and the PDF tool was already written and passing when that happened. The wrong
suffixes in one place and the right ones in another is exactly the drift the whole layer split
exists to prevent, so `_pdf.py` now states `(".pdf",)` and `batch_pdf.py` reads `_pdf.SUFFIXES`,
like the other three.

**Mutation evidence.**

| Invariant | Mutation | Observed failure |
|---|---|---|
| A layer states its processor's inputs, and both of its tools read that one statement | `_pdf.SUFFIXES` widened to `(".pdf", ".txt")` | `test_batch_pdf_mirrors_the_folder_it_walked` red: `assert ['notes', 'sub1/a', 'sub2/deeper/b'] == ['sub1/a', 'sub2/deeper/b']` — the run walked a file its processor cannot read |

The record is in the root `README.md`, beside wave 5's other four.

**Hand run.** `batch_pdf.py --out var/check tests/fixtures/pdf` → `files: 4 · succeeded: 3 ·
failed: 1`, exit `1`, and only the three readable PDFs got a mirrored directory — byte-for-byte what
the earlier entries recorded, which is the evidence the wiring change altered no behaviour.

**Gate evidence.**

```
pytest                     708 passed
ruff check .               All checks passed!
ruff format --check .      179 files already formatted
pylint src tests           10.00/10
```

---

## 2026-09-28 — Phase 5 · the bench readme restructured: one file, or one folder

**Delivered.** `scripts/tools/readme.md` — the command documentation is now grouped by **mode**
instead of by tool, which is the question an operator actually has ("do I point this at a file or
at a folder?"):

| Section | What is in it |
|---|---|
| `## Commands over one file` | the five single-input tools — `pdf.py`, `image.py`, `ocr.py`, `llm.py`, `workflow.py` — each with its subcommand → symbol table, and what is deliberately *not* there (`image.py crop`, `ocr.py diff`, `--engine`) |
| `## Commands over a folder (batch)` | the four batch tools, after **The shape of a batch run** — the mirror, the record per input, the stated default, the `FAILED`/`ok` line, the exit codes — which is stated **once**, because it is `_batch.py`'s and not any one tool's |

The two batch sections that duplicated those rules per tool (`batch_image.py`, `batch_ocr.py`,
`batch_llm.py` each saying "the mirror, the `--out` rule and the exit codes are the ones the
`batch_pdf.py` section above states") now say only what is theirs: their inputs, their default, what
their methods publish, and their demonstration folder. `## Invocation` frames the two modes side by
side, and the stale counts went with it — the report-only set is nineteen of **sixty-four**
subcommands (it said thirty-eight, which predates the batch tools), and a batch tool's set is empty
on purpose.

**Every documented command was run, not reasoned about.** All of them behave exactly as the readme
says: `pdf.py inspect` `0`; `llm.py call` `1` with a typed `MODEL_UNAVAILABLE`; `workflow.py plan`
`0` with a complete request; `batch_pdf.py tests/fixtures/pdf` `1`; `batch_pdf.py tests/fixtures`
`files: 31`; `batch_image.py tests/fixtures/image` `1`; `batch_ocr.py tests/fixtures/ocr` `0`;
`batch_llm.py --fake … call` `0` and the same command without `--fake` `1`; both `--help` lines `0`;
and the three bare runs (`batch_pdf` default `inspect` `0`, `batch_image` default `info` `1`,
`batch_ocr` default `text` `0`) plus `--no-recursive … split` `0`.

**Also touched:** the root `README.md` signposts the two modes and names the two sections, and its
"Lab tools" block gained the batch line it was missing; the bench readme's *Working without an engine
or a model* section now lists `batch_llm.py --fake` beside the other two scripted-provider switches,
and *Known limitation* states that the image publication defect applies per input in a batch, so the
rest of a corpus still runs.

**Gate evidence.**

```
pytest                     708 passed
ruff check .               All checks passed!
ruff format --check .      179 files already formatted
pylint src tests           10.00/10
```

---

## 2026-09-28 — Phase 5 · lab benches (`SCR-11`, `SCR-12`)

**Delivered.**

| File | What it is |
|---|---|
| `scripts/tools/_cli.py` | the `Validate` alias and `run_tool(..., validate=)`: a tool's check that the parsed subcommand's flags can run at all, made after parsing and before anything else the run does |
| `scripts/tools/_batch.py` | `run_batch(..., validate=)`: the same check, made once after the folder resolves and before the header — once per run, not once per input |
| `scripts/tools/_pdf.py` | `PAGE_COMMANDS`, `PAGE_FLAG_COMMANDS`, `DPI_COMMANDS` and `validate_flags`, so the flag registration and the refusal read the same name sets |
| `scripts/tools/pdf.py`, `scripts/tools/batch_pdf.py` | each passes `_pdf.validate_flags` as that hook |
| `tests/test_lab_tools.py` | two parametrized guards: a batch refuses each of the six flag-needing commands before it walks, over an **empty** folder; `pdf.py` refuses `--page`/`--dpi` before its header |
| `scripts/tools/readme.md` | one rule added to the `_batch.py` block: a required flag is refused once, before the walk |

**What the run found.** Two observations from a hand run of
`python scripts/tools/batch_pdf.py tests/fixtures/pdf classify`, which exits `2`:

1. **Not a defect: the refusal itself.** `classify`, `text`, `blocks` and `images` read one page, so
   `--page` is required and the batch substitutes no default — §3.3 already pins exit `2` for a
   missing required flag, and the readme's `batch_pdf.py` table already prints `--page 1` in the
   invocation. Run as `… classify --page 1`: `files: 4 · succeeded: 3 · failed: 1`, exit `1` — the
   corrupt committed sample, exactly the readme's demonstration.
2. **A code defect: the refusal was per input.** `_cli.required` is a post-parse check on purpose
   (`required=True` would hide an injected `default=`, and a default makes the run *proceed*, which
   is what keeps the "no default" guard falsifiable), so the check fired inside the method, when the
   first input called it. Two consequences, both reproduced by hand:
   - the run header was printed for a run that then refused to start;
   - `batch_pdf.py /tmp/empty classify` reported `files: 0 · succeeded: 0 · failed: 0` and exited
     **`0`** — an empty folder calls no method, so the gap went unnoticed entirely. That exit code
     contradicts §3.3's "missing required flag → `2`": the tool against its own contract.

**Decisions taken in code.**

- **The hook sits on the frame, the declaration on the layer.** `_cli.run_tool` and `_batch.run_batch`
  take an optional `validate`; the layer passes it, because `_pdf.py` knows which of its flags are
  required and `_batch.py` knows when a run starts. Neither learns what a page is.
- **One name set, not two.** `build_subcommands` registers `--page` from `PAGE_FLAG_COMMANDS` and
  `--dpi` from `DPI_COMMANDS`; `validate_flags` refuses from `PAGE_COMMANDS` and `DPI_COMMANDS`.
  `PAGE_FLAG_COMMANDS` is `(*PAGE_COMMANDS, "run")` deliberately: `run` **takes** `--page` and does
  not **require** it, the one place the sets differ. A first attempt collapsed them into one set and
  dropped `--page` from `run` altogether — the suite caught it as an `AttributeError` on
  `args.page`, which is why the two sets are named.
- **The refusal is not restated.** `validate_flags` calls the same `page()` and `dpi()` the methods
  call, so "no page number is defaulted" has one author.
- **No plan edit.** What is now enforced is what `subplan-scripts.md` §3.3 already states; the frozen
  artifact is unchanged.

**Invariant evidence.**

*Invariant: a batch refuses a missing required flag before it walks, even when it holds no input.*
Mutation — removing `validate=_pdf.validate_flags` from `batch_pdf.py` turned the new guards **red**:
6 of the 8 parametrizations failed with `DID NOT RAISE SystemExit`, and the captured output showed
`files: 0`, `succeeded: 0`, `failed: 0` and a printed header — the defect reproduced. The 2 that
stayed green are the `pdf.py` parametrizations, which go through `_cli.run_tool` and are not reached
by that mutation. Argument restored, re-run: **green** (103 passed in the module).

**Gate evidence.**

```
pytest                     716 passed
ruff check .               All checks passed!
ruff format --check .      180 files already formatted
pylint src tests           10.00/10
```

`pylint` still reports `too-many-lines` on `tests/test_lab_tools.py` (1292/1000) and
`use-implicit-booleaness-not-comparison` at line 707. Both are **pre-existing**: `pylint
--from-stdin` over `git show HEAD:tests/test_lab_tools.py` reports the same two (1234/1000, line
649), and neither moves the rating off 10.00.

**Left stale (plan owner).** `docs/plan/issues/wbs-scripts.md` describes `run_batch(...)` as taking
`suffixes=`, `default=`, `header_extra=`, and `_pdf.py` as holding `SUBCOMMANDS`,
`build_subcommands`, the eight methods and `COMMANDS`. Both now under-describe the code: the frame
takes `validate=` and the layer holds three name sets and `validate_flags`. A WBS is frozen, so
correcting the description is a plan revision (`SCR-11`, `SCR-12`) and not this entry.

**Next.** `_llm.py` has the same shape — `provider`, `model`, `task`, `template` and `run_id` are
required per subcommand and refused inside the method — so `batch_llm.py <empty-folder> call` exits
`0` for the same reason. The hook now exists; wiring it is a per-command table over eight
subcommands. `_ocr.py` takes no required flag and needs nothing.

---

## 2026-09-28 — Phase 5 revision · page scope in the PDF bench (`PAG-01` … `PAG-07`)

**The rule.** A page-addressed command of `pdf.py` / `batch_pdf.py` that is given no `--page`
reads **every page of the document**, in page order; a one-page document is simply a scope of one.
The scope a run resolved to is stated back in the payload, so an omitted flag is never silent, and
the payload's shape follows the scope that was asked for: one page keeps its own keys, every page
reports a `pages` list with a `status` and its `errors`.

**Delivered.**

| File | What changed |
|---|---|
| `scripts/tools/_pdf.py` | `PageScope` + `page_scope`, `_pages`, `_scope_status`, `_scope_payload`, `_images_dir`, and one per-page builder per command; `validate_flags` reduced to `--dpi`; `page()` deleted |
| `tests/test_lab_tools.py` | 4 refusal parametrizations retired, 1 swapped for `run`/`--dpi`; 9 tests added |
| `docs/plan/subplan-paginas.md`, `docs/plan/issues/wbs-paginas.md` | the subplan and its WBS — written, applied and closed in this pass |
| `scripts/tools/readme.md`, `scripts/tools/quickstart.md` | the page-scope section, the `Needs` cells, the examples, and the corrected `classify` note |
| `docs/plan/subplan-scripts.md` | §3.3's page-scope bullet and the `render --page 1` example, §3.4's five `Notes` cells, §9 decision 18 |
| `docs/plan/README.md`, `docs/plan/issues/wbs-general.md` | this subplan's row and §4.1 pointer; §1's Phase 5 revision row, §4.6, and the totals they move to 22 own / 102 child / 124 tasks / 42-68-14 |
| root `README.md` | the two four-field mutation records below |

**Tasks.** All seven are done:

| Wave | Tasks | Status |
|---|---|---|
| 1 — The rule | `PAG-01`, `PAG-02` | done |
| 2 — Prove it | `PAG-03`, `PAG-04`, `PAG-05` | done |
| 3 — Close | `PAG-06`, `PAG-07` | done |

**Gate evidence.**

```
pytest                     722 passed
ruff check .               All checks passed!
ruff format --check .      181 files already formatted
pylint src tests           10.00/10
```

`722` is the previous `717` plus five: four parametrizations retired and nine tests added. The two
Ruff gates read the whole tree, so `scripts/tools/_pdf.py` is inside them; `pylint src tests` does
not reach it, which is `subplan-scripts.md` §9 decision 10 and stays stated rather than widened.

**Invariant evidence.** Two invariants were mutation-falsified this session. **The canonical
records live in the root `README.md`** (the table `GEN-16` audits); the summary is:

- *An omitted `--page` resolves to every page.* Mutating `page_scope`'s all-pages branch to
  `pages=[1]` turned **5 tests red** (scope, collision, partial and both batch runs) while `label`
  still read `all pages (3)` — a run that said one thing and did another. The one that stayed green
  was the one-page case, where a scope of one *is* the mutation.
- *Two pages never share an artifact directory.* Pointing `_images_dir` back at `root / "images"`
  turned the collision test red with `assert ['images/image_001.png'] == ['page_001/images/…',
  'page_002/images/…']` — the second page overwriting the first, exactly as the processor's
  per-call naming predicts.

**Hand run (`PAG-04`), on the engines actually installed here** (Poppler 25.02.0):

```
python scripts/tools/pdf.py --json classify tests/fixtures/pdf/pdf_sample_text.pdf
  scope: all pages (3) · status: success · errors: 0 · [(1,TEXT), (2,TEXT), (3,TEXT)]      exit 0
python scripts/tools/pdf.py --json classify tests/fixtures/pdf/pdf_sample_mixed.pdf
  scope: all pages (1) · status: success · errors: 0 · [(1,TEXT)]                          exit 0
python scripts/tools/pdf.py --out … images tests/fixtures/pdf_aptos_layout/9073693b-….pdf
  page_001/images/image_001..006.png (6) · page_002/images/image_001..005.png (5)          exit 0
python scripts/tools/pdf.py --out … images <the same input> --page 1
  images/image_001..006.png (6)      ← a stated page keeps its flat directory              exit 0
python scripts/tools/pdf.py --out … render <the same input> --dpi 72
  2 PNGs from a command that named no page                                                 exit 0
python scripts/tools/pdf.py --out … classify tests/fixtures/pdf/pdf_corrupt.pdf
  ERROR CORRUPTED_PDF: pdfinfo reported a syntax error · no payload                        exit 1
python scripts/tools/pdf.py --out … --json classify tests/fixtures/pdf_large/MetodoCITRA17-APL.pdf
  scope: all pages (59) · status: success · errors: 0 · {TEXT: 57, IMAGE: 2} · 3.0 s        exit 0

python scripts/tools/batch_pdf.py tests/fixtures/pdf classify
  files: 4 · succeeded: 3 · failed: 1 · the corrupt sample is the one failure               exit 1
python scripts/tools/batch_pdf.py tests/fixtures/matrix render --dpi 150
  files: 3 · succeeded: 3 · failed: 0                                                       exit 0
```

**Decisions taken in code.**

1. **The scope travels as a payload key, so the frame did not change at all.** `_cli.py` and
   `_batch.py` have no new line: `print_result` already prints every key, `run_one` already files
   the payload, and `_failed`/`_payload_failures` already read `status` and `error`/`errors`. That
   is why the change is one file.
2. **`page()` was deleted, not kept.** It wrapped `_cli.required`, which can only refuse a
   *missing* value; with "absent" now meaningful, the call could never fire, and a guard that
   cannot fail is worse than none. The flag stays default-free because
   `test_a_page_command_reads_every_page_when_no_page_is_stated` goes red the moment a `default=`
   is injected — falsifiable in the behaviour rather than in a refusal.
3. **Only the looping form writes `page_NNN/images/`.** A stated page keeps the flat `images/`
   directory it has always had, because the sub-directory exists to stop N pages colliding and one
   page has nothing to collide with. The alternative — always `page_NNN/` — was rejected: it would
   break a recorded layout for no benefit.
4. **A failure before the loop still raises; a failure inside it is collected.** `page_scope`
   inspects before the first page, so an uninspectable document keeps today's behaviour exactly:
   the typed record is printed, nothing is filed, exit `1`. Inside the loop a failed page becomes a
   page-scoped record in `errors` and the other pages are still reported — one bad page must not
   cost a caller the other twenty-nine.
5. **`PageScope.document` carries the inspection the scope already made.** Without it, `classify`
   — the only method that needs the geometry — would call `pdfinfo` once per page on top of the one
   the scope made: 60 calls for a 59-page document instead of one. On a stated page the field is
   `None` and `classify` inspects exactly as it did before, which is what keeps that path's engine
   count unchanged.
6. **No flat `artifacts` key.** The all-pages entries name the files they published, so a
   document-level list would be a second copy of the same paths; `run` carries one only because the
   *contract* returns it.
7. **Three of this subplan's own claims did not survive implementation, and the plan was corrected
   rather than the code.** (a) It declared that it superseded §5 and §6 of `subplan-scripts.md`;
   neither mentions the page flag, and neither needed an edit — the refusal had been pinned by
   tests alone, which is a finding about the frozen artifact, not an omission. (b) It drafted a
   flat `artifacts` key (decision 6). (c) It said `page()` would be unchanged (decision 2). All
   three corrections are in the subplan's §3.1, §3.4 and §9, which is where a plan and its code
   are supposed to agree.

**Found by the bench (the point of the exercise).**

| Finding | Evidence | Owner |
|---|---|---|
| **The shared-`images/` collision was real, not hypothetical.** The two-page layout fixture carries 6 images on page 1 and 5 on page 2, and the processor names each page's images from its own per-call index — so both pages produce `image_001.png`. The flat directory would have silently destroyed five files on the second page | `page_001/images/image_001..006.png` (6) beside `page_002/images/image_001..005.png` (5) | the reason invariant 10 exists |
| The 59-page scale fixture reads **57 `TEXT`, 2 `IMAGE`, and no `MIXED`** — the `MIXED` branch is unreachable while the engine reports no image placement | `verdict counts {'TEXT': 57, 'IMAGE': 2}` · 3.0 s for the whole document | already tagged `# TODO: [MVP]` in `pdf/primitives/composition.py` |
| `pdf_sample_mixed.pdf` reads `TEXT` for **two** reasons, not one: its image is drawn 96×96 pt on a 612×792 page, about **1.9%** coverage, so even a placement-aware reader would still call it `TEXT` | coverage `0.0190` against `IMAGE_COVERAGE_MIN = 0.30` | the quickstart's `Reading classify` note says so now — the fixture named "mixed" cannot demonstrate `MIXED` without a much larger image |
| An omitted `--page` multiplies the work silently: 2 PNGs where one was asked for on a 2-page document, 59 pages read where 1 was | the `render`/`classify` runs above | accepted cost of the rule; stated in the payload and in the readme |

**Left stale (owner).** Three owed revisions predate this pass and were **not** taken here, to keep
this change's footprint on page scope:

| Document | What is stale | Owner |
|---|---|---|
| `docs/plan/issues/wbs-scripts.md` | `run_batch(...)` still lists three keywords where the frame takes four — `validate=` was added on 2026-09-28 | plan owner |
| `docs/plan/subplan-scripts.md` §3.1/§3.3/§5, `docs/feedback/batch-mode-across-processors.md` | still say the per-input record is `result.json`; it has been `<command>.json` since the 2026-09-28 rename | plan owner |
| `docs/plan/subplan-scripts.md` §3.3 | the `workflow.py plan … --dry-run` example puts a **global** flag after the subcommand, so it is a usage error if copied verbatim. This pass touched §3.3 for the page flag and deliberately did not widen to it — the same discipline that left the two rows above | plan owner |

**Next.** Unchanged from the entry above: wiring `_llm.validate_flags` is the remaining bench defect
of that shape, and the image processor's publication defect is still the one thing standing between
the bench and an end-to-end run. Nothing in this revision is waiting on a plan decision.

---

## 2026-09-29 — Phase 5 · `text` publishes its page files (`pdf.py`, `batch_pdf.py`)

**Asked for at the bench.** `batch_pdf.py tests/fixtures/pdf text` reported each page's native text
inside the payload and the `text.json` record, and wrote nothing a caller could hand to another
tool; `render` had always left its PNGs beside the record. `text` now publishes each page's native
text as `page_NNN.txt` under the run root — the naming rule `render` already uses, so the scope
decides **how many** files a run writes and never what one is called. `blocks` is deliberately
unchanged: it stays report-only, and `inspect` with it.

**No new seam.** The write reuses the processor's own `pdf.primitives.publish_text`, so the artifact
goes through the same `.tmp` → validate → rename as every other one, and an empty page still
publishes an empty file rather than a missing one. The tool composes; it invents no writer, no
suffix and no contract. `pdf.py`'s `REPORT_ONLY` loses `text` (six subcommands write, two report),
and the payload gains one key, `output`, exactly as `render`'s carries it.

**Mutation evidence** (the new test must fail when the invariant is broken).

| Mutation | Observed failure | Restored |
|---|---|---|
| `_pdf._text_page`: drop the `publish_text` call and the `output` key | `test_pdf_text_publishes_one_file_per_page` red (`.../run/page_001.txt`.is_file() `False`) and `test_a_stated_page_keeps_its_payload_shape` red (`KeyError: 'output'`) — 2 failed, 107 deselected | inverse edit, then 109 passed in `tests/test_lab_tools.py` |

**Hand run (real engine).** `batch_pdf.py tests/fixtures/pdf text` → `files: 4 · succeeded: 3 ·
failed: 1`, exit `1`, with `page_001.txt` … `page_003.txt` beside `text.json` in the three readable
inputs (the corrupt sample files nothing, as before); `pdf.py text` over the three-page sample →
three files and a payload whose `scope` is `all pages (3)`.

**Gate evidence.**

```
pytest                     722 passed
ruff check .               All checks passed!
ruff format --check .      181 files already formatted
pylint src tests           10.00/10
```

**Left stale (owner).** Which artifacts a subcommand publishes is a plan decision, so a **plan
revision is owed** — not taken here, because a frozen plan moves in its own pass together with its
WBS file:

| Document | What is stale | Owner |
|---|---|---|
| `docs/plan/subplan-paginas.md` §3.3 | the `text` row's *Published per page* cell says "nothing"; it publishes `page_NNN.txt` | plan owner |
| `docs/plan/subplan-paginas.md` §3.4 | the `text` payload examples, and the claim that `scope` is "the only change to the single-page payload" — `output` is now a second addition | plan owner |
| `docs/plan/issues/wbs-paginas.md` | the paired WBS file must move in the same pass as §3.3/§3.4 | plan owner |

---

## 2026-09-29 — PDF · a second text artifact: the engine's own `-layout` rendering

**Asked for after reading the two outputs side by side.** `text.txt` is a *reconstruction*: it is
joined from the word rows of `pdftotext -tsv`, so it reads in order and loses the page's columns.
The engine's `-layout` rendering is the other half of the same page — it keeps every word's column.
Neither is a superset of the other, so both are published now:

| Artifact | Read | Read it when |
|---|---|---|
| `native_text/text.txt` | `pdftotext -tsv`, rebuilt row by row | you want the page as text: a line-by-line consumer, the LLM stage |
| `native_text/text_layout.txt` | `pdftotext -layout` | the page's arrangement is the information: tables, forms, invoice headers |

The bench mirrors it: `pdf.py text` / `batch_pdf.py … text` write `page_NNN.txt` **and**
`page_NNN_layout.txt`, named per page the way `render` names its PNG.

**The cost is a second engine call per page, and it is opt-in.** Gated on the existing
`PDFOptions.layout` — no new option, no contract field — so `run --layout` and `pdf.py text` pay
for it and `layout=False` makes neither the call nor the file. `text.txt` and `blocks.json` still
come from **one** read; the layout artifact is added *beside* them, never instead of them, so the
pair that must agree about reading order still does.

**Measured, not asserted.** With the real engine our `page_001_layout.txt` is byte-identical to
`pdftotext -layout` apart from the page separator and the final newline, which the seam strips
(`diff` on the 69-line ticket shows one line, the `\ No newline at end of file` marker). The
usefulness argument comes from the two `casos` fixtures: in the ticket's two-column footer the
reconstruction keeps each column contiguous where `-layout` interleaves them line by line
(`o no, deberán cumplimentar…` above `El boleto es válido…`), and in the same ticket's header
`-layout` keeps `Boleto:SUV-255671438-0` glued and `Boleto:`/`Butaca:`/`Salida:` on one visual
line, which the reconstruction splits. On a fixture with no columns the two agree word for word.

**Mutation evidence.**

| Mutation | Observed failure | Restored |
|---|---|---|
| `entrypoints`: the layout block never runs (`if False:`) | 3 red — `test_the_happy_path_processes_every_page_and_publishes_its_namespace` (`'native_text/text_layout.txt'` extra in the expected set), `test_the_layout_text_is_the_engines_own_rendering_beside_the_reconstruction`, `test_one_failing_stage_yields_a_partial_page_that_keeps_its_artifacts` | inverse edit; `tests/pdf` 84 passed |
| `_pdf._text_page`: the layout read stubbed to `""` | `test_pdf_text_publishes_two_files_per_page` red — the published file no longer holds the same words as the reconstruction | inverse edit; 109 passed in `tests/test_lab_tools.py` |

**New tests.** The engine seam gained `test_the_layout_read_is_a_second_call_on_purpose` (the call
is `-layout`, one of them, to stdout) and `test_a_page_without_a_text_layer_has_an_empty_layout_text`;
the entry point gained the opt-in pair — the artifact is the engine's own rendering beside the
reconstruction, and it is absent (with the call) when `layout=False`.

**Gate evidence.**

```
pytest                     726 passed
ruff check .               All checks passed!
ruff format --check .      181 files already formatted
pylint src tests           10.00/10
```

**Left stale (owner).** This deliberately adds a **second reader for one engine call**, which the
plan forbade by name, so a **plan revision is owed** — not taken here, for the same reason as the
entry above (a frozen plan moves in its own pass, subplan and WBS together):

| Document | What is stale | Owner |
|---|---|---|
| `docs/plan/subplan-procesador-pdf.md` §9, decision 7 | "one reader per concern … two paths to the same engine call is how a page count starts disagreeing with itself" — the design now has `extract_text_from_page` (`-tsv`) and `extract_layout_text_from_page` (`-layout`), and the rationale that survives is narrower: the two reads are *different outputs*, not two paths to one, and `text.txt`/`blocks.json` still come from one call | plan owner |
| `docs/plan/subplan-procesador-pdf.md` §3 | the primitive list and the native-text bullet do not mention the layout read | plan owner |
| `docs/plan/issues/wbs-procesador-pdf.md` §PDF-06 | the objective says "from one read" and the scope names one primitive; the paired WBS must move with §3/§9 | plan owner |
| `docs/plan/issues/wbs-procesador-pdf.md` §PDF-05 / PDF-03 range | no task owns the new artifact; whether it is PDF-06's or a new row is the revision's call | plan owner |

---

## 2026-09-30 — Phase 5 · the OCR bench's `text` publishes what it reports (`ocr.py`, `batch_ocr.py`)

**Asked for at the bench, the day after the PDF twin.** `batch_pdf.py <folder> text` publishes
`page_NNN.txt` per page; `batch_ocr.py <folder>` — whose default **is** `text` — wrote `text.json`
and nothing else, so parsing a record was the only way to read an extraction back. `text` now
publishes `text.txt` in that input's run root, and `ocr.py`'s `REPORT_ONLY` loses it: six
subcommands write, five report.

**No new seam, no new writer.** The write goes through the processor's own
`ocr.primitives.write_text_atomic` (`.tmp` → rename), so the publication rule is the one every other
artifact follows — and an empty text is still a legitimate artifact: a blank page publishes a
zero-byte `text.txt` and is reported `EMPTY`. The layer states the name (`TEXT_NAME = "text.txt"`)
the way it states `SUFFIXES`: what a processor calls what it publishes is that processor's own fact.
`_batch.py` and `_cli.py` needed **no line**: the frame files `<command>.json` and the method
publishes beside it, and `text.txt` cannot collide with `text.json`.

**One name, one reading.** The bytes are the **normalized** text, which is the form
`ocr/entrypoints.py` gives `text.txt` — so a `text` run and a `run` of the same image write the same
file, and the payload states the same string the file holds. Publishing the engine's raw export
instead would have made `text.txt` mean one thing when `text` wrote it and another when `run` did.

**The default changed its *rule*, not its command.** Decision 15 said the default is "the flag-free
method that publishes nothing". `text` is that default and it now publishes one small file per
input — the reading its own record states, with nothing derived from it. The rule was reworded
rather than the default moved: answering a bare corpus run with metrics where the operator's first
question is "what does this page say?" would be a worse default than one text file per input.

**Mutation evidence** (both applied to `scripts/tools/_ocr.py`, both restored by the inverse edit).

| Mutation | Observed failure | Restored |
|---|---|---|
| `_ocr._text`: drop the `write_text_atomic` call and the `output` key | `test_ocr_text_publishes_the_reading_run_gives_the_same_name` and `test_ocr_reads_through_the_shared_layer` red — 2 failed, `FileNotFoundError` on `text.txt` | inverse edit; 111 passed in `tests/test_lab_tools.py` |
| `_ocr._text`: publish the engine's raw export while reporting the normalized one | `test_ocr_text_publishes_the_reading_run_gives_the_same_name` red — `assert 'Quarterly re...ledger   \n\n' == 'Quarterly re...ternal ledger'`: the file kept the trailing whitespace `run` strips | inverse edit; 111 passed |

**Hand run (real engine).** `batch_ocr.py tests/fixtures/ocr` → `files: 2 · succeeded: 2 ·
failed: 0`, exit `0`, each mirror holding `text.json` **and** `text.txt` (both zero bytes — the
240×120 synthetic fixtures extract `EMPTY` with the real engine, as recorded above). On a real
scan, `ocr.py text tests/fixtures/chicos/243a8b81-….png` published a 29-byte `text.txt`
(`GASTOS VARIOS, FALTA FACTURA.%`) whose bytes are **identical** to the `text.txt` of `ocr.py run`
over the same image (`cmp` reports no difference).

**Gate evidence.**

```
pytest                     758 passed
ruff check .               All checks passed!
ruff format --check .      181 files already formatted
pylint src tests           10.00/10 — one message, the pre-existing
                           src/docflow/pdf/entrypoints.py:475 R0912 (15/12),
                           untouched by this change and left as it is
```

**Plan revision applied in the same pass** (`docs/feedback/ocr-text-artifact.md`, D-1…D-4), as the
convention requires — subplan and WBS together: `subplan-scripts.md` §3.4 (the `ocr.py` `text` row,
the batch-table row, rule 1), §5 (the new scenario), §6 (invariant 9), §9 (decision 19) and
`wbs-scripts.md` §SCR-04, §SCR-14 and the risk table. Two owed corrections were closed in the same
two files because they sit in the sections being edited: the per-input record is `<command>.json`
(subplan §3.1/§3.3/§5/§9, WBS §SCR-12/§SCR-18) and `run_batch(...)`'s keyword list gained
`validate=` (WBS §SCR-12).

**Left stale (owner).**

| Document | What is stale | Owner |
|---|---|---|
| `docs/feedback/batch-mode-across-processors.md` | still says the per-input record is `result.json` | plan owner |
| `docs/plan/subplan-paginas.md` §3.3/§3.4, `docs/plan/issues/wbs-paginas.md` | the PDF `text` row still says *Published per page*: "nothing" — owed since 2026-09-29 and deliberately untouched here | plan owner |

**Not taken.** `md` publishing `document.md` is the same question, and a second published
representation is its own decision.

---

## 2026-09-30 — Phase 5 · the OCR bench's `tables` asks for the detection it reports (`_ocr.py`)

**Asked for at the bench.** `python scripts/tools/batch_ocr.py <folder> tables` was read as "the
tables of these images" and answered `"tables": []` for a real invoice photo whose table Docling
finds in three rows and eight columns. The command was what lied: `--tables` was `store_true`,
default `False`, and `_ocr._document` builds its table list **only when the option claims tables**
(`if normalized.tables else []`), so on the `tables` subcommand the answer was structurally always
empty. Detection is engine work (`do_table_structure` in `configure_image_pipeline`), and a run
that never asked for it is not a run that found none.

**Checked against the engine first, outside the bench** (the question was "is it Docling?").
Docling 2.126.0 over `tests/fixtures/casos/66cd35e9-….jpg`: `do_table_structure=False` → 1 table,
1×1, empty — the degenerate item the engine emits with the structure model off; `do_table_structure
=True` → 1 table, **3×8**, cells read. Identical in `TableFormerMode.ACCURATE` with
`do_cell_matching=True`, so the mode changes nothing on this image and no option was touched. The
library was right; the bench never asked.

**The fix is one default on one subcommand.** `_ocr._add_ocr_options(subparser, *,
tables_by_default=False)`; `build_subcommands` passes `tables_by_default=name == "tables"`, so
`--tables` is on for `tables` and off for the other six — the same shape as `--ocr` being on
because OCR is the processor's purpose, and the same shape as `_pdf.py`'s `blocks`, which calls
`extract_text_from_page(..., True)` and has no flag of its own. `--tables` became a
`BooleanOptionalAction`, so `--no-tables` still states the opposite and the flags still decide what
is *claimed* (decision 7, 2026-09-25). One line fixes both tools: `ocr.py` and `batch_ocr.py` share
`_ocr.py`. `_cli.py`, `_batch.py` and `src/`: **no line**.

**Mutation evidence** (applied to `scripts/tools/_ocr.py`, restored by the inverse edit).

| Mutation | Observed failure | Restored |
|---|---|---|
| `build_subcommands`: `tables_by_default=False` (the old behaviour) | `test_ocr_tables_asks_for_the_detection_it_reports` red — `AssertionError: assert [] == [[['Region', 'Revenue'], ['North', '120']]]` | inverse edit; `pytest -q` 759 passed |

**Hand run (real engine).** `batch_ocr.py tests/fixtures/casos tables` → `files: 6 · succeeded: 6 ·
failed: 0`, exit `0`; `66cd35e9-….jpg` files `table_001`, 3×8 —
`Código · Detalle · Cant. · Pr.Lista · %1 · % 2 Precio · % IVA · Total`. The other five inputs
report `0` tables, measured rather than assumed. Note the shape of the trap: before and after, the
summary was **identical** (`succeeded: 6`, exit `0`), so only the payload distinguished "no table"
from "never asked".

**Gate evidence.**

```
pytest                     759 passed
ruff check .               All checks passed!
ruff format --check .      181 files already formatted
pylint src tests           10.00/10 — one message, the pre-existing
                           src/docflow/pdf/entrypoints.py:475 R0912 (15/12);
                           `git diff --name-only -- src` is empty
```

**Docs updated (bench documentation, not a frozen artifact).** `scripts/tools/quickstart.md`: the
`ocr.py tables` example lost `--tables` and the sentence that said the flag is what asks for the
detection now says the command asks for it itself. `scripts/tools/readme.md`: the `tables` row
notes the default. **No plan revision is owed** — `subplan-scripts.md` §3.4's `tables` row names
the symbol and the representation, never the flag, and the only document that stated the
requirement was the quickstart.

**Not taken.** `json` and `metrics` still default `--tables` off, so `json` carries no table and
`metrics.tables` reads `0` unless the caller states the flag. That is the documented claim rule
rather than a defect — but it is the same papercut one command over, and the defaults of the three
document-building commands are worth deciding together.

---

## 2026-09-30 — Phase 5 · the OCR bench's `mixed`: the reading with its tables (`_ocr.py`)

**Asked for at the bench, and the premise was false.** The request was a `mixed` command that would
"put the text and, where the `<table>` mark is, the Markdown of the extracted table". Measured
before anything was designed, on `tests/fixtures/casos/66cd35e9-….jpg` with docling 2.126.0:
`document.export_to_text()` writes **no** placeholder — with `do_table_structure=True` it writes the
real Markdown table where it was read, and with it off a degenerate single-row pseudo-table; the
only angle-bracket marker this engine emits is `<!-- image -->`, and only in
`export_to_markdown()`. A sweep of the whole `var/` tree found no `<table>` anywhere either. A
substitution step would have been code that can never fire — the silent stand-in this project
forbids.

**So `mixed` is a claim, not a renderer.** `_ocr.TABLES_COMMANDS = ("tables", "mixed")`: the
`--tables` default the previous entry gave `tables` now covers both commands whose answer needs the
detection, and `COMMANDS["mixed"]` is `_text` — one method under two names, because what separates
them is the *request* and not a rendering. `TEXT_NAME` and its normalization are untouched, so "one
name, one reading" survives: `mixed` and `text --tables` write byte-identical bytes (`cmp` on the
invoice), while `text` without the flag differs from char 623 (line 41) — that is the degenerate
pseudo-row the reading would otherwise carry.

**Rejected: a renderer of ours** (`composition.render_mixed_text` over the ordered document,
splicing `table_to_markdown`). It would agree byte-for-byte with `document.json`, but it re-renders
the *reading*: `merge_ocr_blocks` joins the engine's consecutive text items into one paragraph with
spaces, so an invoice's per-line fields (`Punto de Venta: …`, `CUIT: …`) would land on one line. The
bench's operator chose fidelity over consistency.

**Mutation evidence** (both applied to `scripts/tools/_ocr.py`, restored by the inverse edit).

| Mutation | Observed failure | Restored |
|---|---|---|
| `TABLES_COMMANDS = ("tables",)` | `test_only_the_two_table_commands_claim_the_detection[mixed]` red — `assert False is ('mixed' in {'mixed', 'tables'})`; the other seven cases green | inverse edit |
| `_text` publishes to `root / "reading.txt"` | `test_ocr_mixed_publishes_the_reading_under_the_text_name` **and** `test_ocr_text_publishes_the_reading_run_gives_the_same_name` red (2) — the file name is the invariant the two share | inverse edit |

**Hand run (real engine).** `batch_ocr.py tests/fixtures/casos mixed` → `files: 6 · succeeded: 6 ·
failed: 0`, exit `0`; the invoice's `text.txt` carries the table in place at line 41
(`| Código   | Detalle …`, `| KL04181 …`).

**Gate evidence.**

```
pytest                     768 passed
ruff check .               All checks passed!
ruff format --check .      181 files already formatted
pylint src tests           10.00/10 — one message, the pre-existing
                           src/docflow/pdf/entrypoints.py:475 R0912 (15/12);
                           `git diff --name-only -- src` is empty
```

**Plan revision applied in the same pass** (`SCR-04`, `SCR-14`), subplan and WBS together:
`subplan-scripts.md` §2 (the module table), §3.4 (the new `mixed` row), §5 (a new scenario — the
reading carries its tables and no placeholder is substituted), §6 (invariant 10) and §9
(**decision 20**, which records the engine measurement that killed the substitution premise);
`wbs-scripts.md` §SCR-04 (objective, scope, one acceptance criterion) and §SCR-14 (objective, scope,
out-of-bounds). Bench docs: `scripts/tools/quickstart.md` (the table, both example blocks, the
prose), `scripts/tools/readme.md` (the layer row, the batch row, the OCR table, the publication
paragraph, and the report-only count 64 → **66**), root `README.md`'s tool table and
`docs/plan/README.md` §4.1.

**Left as it is.** `json` and `metrics` still default `--tables` off — the claim rule, not a defect;
the note at the end of the previous entry stands.

---

## 2026-09-30 — Phase 5 · the OCR reading by rows (`mixed`, `_engine_box`, `render_reading`)

**The previous entry's `mixed` is superseded by this one.** The operator reported what the text
actually gets wrong, with the region: the customer block reads

```
Cliente:
Domicilio:
CVC S.A. (63)
CUIT:30-58221570-3
CIRCUNVALACION 1245 BIS - ROSARIO (2000) - Santa Fe I.V.A.: Responsable Inscripto
```

five lines where the page sets three side-by-side pairs. `mixed` was "`text` with the tables
claimed", and no claim repairs that: the engine states **one region per line**, so a label and its
value arrive as two regions and its export puts them one under the other. `mixed` is now a
*rendering* — `composition.render_reading` — and publishes `mixed.txt`, a name of its own.

**Row rendering.** Items whose vertical spans overlap are one line, ordered left to right; the rows
run top to bottom; a table is a block that is never merged into a line and is carried as its
Markdown where the reading reaches it; nothing is joined across rows. Measured on the invoice: the
five lines become the two the page states (`Cliente:   CVC S.A. (63)   CUIT:30-58221570-3`), the
header's two columns pair up, and the totals block becomes its labels row and its values row. The
command claims `--tables` and `--layout` (`_ocr.CLAIMS`) because the rendering reads both, and
claims no reading order: the rows come from the boxes whatever the document's order was set to. A
run that claims no layout has no boxes and is rendered verbatim, in the engine's sequence.

**A defect found on the way: the engine's box origin was ignored — one conversion, four symptoms.**
Docling reports the pages this processor converts in `CoordOrigin.BOTTOMLEFT` (measured:
`prov[0].bbox.coord_origin`, the logo at `t=734…807` on a `595.68 × 841.92` page, `ORIGINAL` at
`t=814…826` — the *largest* `t` is the *top*). `normalize_bbox` read those numbers as top-down, so
every `bbox` in `document.json` had its top and its bottom swapped **and**
`preserve_reading_order(by_geometry=True)` read the page from the bottom up: measured on the
invoice, 39 extracted blocks came back as **3**, one of them an 816-character paragraph joining the
whole form, ordered from `0,00 0,00 … Percep. Imp. Int.%` up to `ORIGINAL`. `_engine_box` now makes
the conversion once, with the engine's own `to_top_left_origin(page_height)`, reached only when the
box states `BOTTOMLEFT` — so blocks, tables and layout regions all reach the document in the one
convention `composition` documents.

**The double was hiding it, and now models it.** `FakeBoundingBox` reports `BOTTOMLEFT` and hands
over `(l, b, r, t)`; the fixtures stay readable through `for_top_down_rect(page_height, …)`, which
converts their top-down rectangles once. The double's own evidence (`docs/plan/bitacora.md`
2026-09-25, §"the shapes are the engine's own") said "a bounding box is reached through
`prov[0].bbox.as_tuple()`" — true, and incomplete: it never said *which way up*. With the origin
modelled, every fake-driven conversion exercises the conversion, and disabling it turns four tests
red instead of none.

**Mutation evidence** (three rows, each applied to the source and restored by the inverse edit).

| Mutation | Observed failure | Restored |
|---|---|---|
| `_engine_box`: skip the origin conversion (`if False and …`) | 4 red — `test_the_layout_is_read_from_the_documents_own_page`, `test_the_extraction_translates_the_engines_structures_into_ours`, `test_the_two_runs_of_the_same_input_produce_the_same_functional_content`, `test_ocr_mixed_renders_the_pages_rows_and_publishes_them` | inverse edit; 240 passed in `tests/ocr tests/test_lab_tools.py` |
| `_visual_rows`: never join an item to an existing row (`row = None`) | 3 red — the row-pairing, the left-to-right order and the table-in-place cases | inverse edit |
| `_visual_rows`: let a table's row take neighbours (`if True and …`) | 1 red — `test_a_table_is_never_merged_into_a_row_that_shares_its_band`; the label and its value vanish, because a table row renders its first member | inverse edit |

The third mutation found a **defect in the test it was meant to falsify**: the case overlapped by
exactly half the shorter extent (`0.45–0.55` against `0.40–0.50`), which sits on the rule's
boundary, so relaxing the rule changed nothing. The boxes were moved inside the band and the case
went red as it should.

**Hand run (real engine).** `ocr.py --out … mixed tests/fixtures/casos/66cd35e9-….jpg` publishes
`mixed.txt` with the customer block as the two lines the page states, the header's columns paired,
the table as Markdown in place, and the totals as their labels row and their values row.

**Gate evidence.**

```
pytest                     774 passed
ruff check .               All checks passed!
ruff format --check .      181 files already formatted
pylint src tests           10.00/10 — one message, the pre-existing
                           src/docflow/pdf/entrypoints.py:475 R0912 (15/12)
```

**Plan revision applied in the same pass** (`SCR-04`, `SCR-14`), subplan and WBS together:
`subplan-scripts.md` §3.4 (the `mixed` row names `composition.render_reading` and `mixed.txt`), §5
(the scenario rewritten for the row rendering), §6 (invariant 10 rewritten for the rendering and
the origin) and §9 (**decision 20 superseded and rewritten**, plus **decision 21** for the origin
conversion); `wbs-scripts.md` §SCR-04 (one acceptance criterion) and §SCR-14 (out-of-bounds and one
acceptance criterion). Bench docs: `scripts/tools/quickstart.md` (table, prose and the publication
paragraph), `scripts/tools/readme.md` (the OCR table, the publication paragraph, the batch list),
`scripts/tools/ocr.py` and `scripts/tools/batch_ocr.py` docstrings. Root `README.md` and
`docs/plan/README.md` §4.1 name the subcommand set, which did not change.

**Left stale (owner).**

| Document | What is stale | Owner |
|---|---|---|
| `docs/3party/docling.md` §D/§K | the box origin (`CoordOrigin.BOTTOMLEFT` for image input, `as_tuple()` → `(l, b, r, t)`), the default backend (`OcrAutoOptions` → RapidOCR with `_RAPIDOCR_DEFAULT_LANGUAGE = "ch"`, an ISO-639 tag now resolving to `es`/`latin`), `export_to_text()` being a real plain-text serializer in docling-core 2.95 (it keeps `\|` on purpose — docling-core #245 is stale), and the upstream language defect (#2887 / #2927) | dossier owner |
| `docs/plan/subplan-scripts.md` §3.3 | still carries the two example lines the 2026-09-27 entry registered as stale (a copied example, not a decision) | plan owner |

**Still open, not fixed here — found while answering the same question.** `--language` and every
`--engine-option` never reach the engine: `configure_image_pipeline` folds `ocr_language` and the
passthrough keys into the config, and `load_docling_pipeline` hands `PdfPipelineOptions` only
`do_ocr`, `do_table_structure` and `generate_page_images`. `--language es --engine-option
force_full_page_ocr=true` produce byte-identical output to a plain run (`cmp`), `ocr_language` is
not a Docling field at all, and the *other* ~30 fields (`ocr_options`, `layout_options`,
`table_structure_options`, `images_scale`, …) are unreachable — so the only knobs that could
influence the OCR model (including the `ch` default upstream #2887 measures at ~3× the CER of the
English model) are inert. The fix is a library change with its own revision.

---

## 2026-09-30 — Phase 1 · the OCR document is read whole, footer included (`CONTENT_LAYERS`)

**A missing `CAE`, and the OCR was never the problem.** The operator asked why
`var/batch_ocr/…/mixed.txt` does not show the fiscal block the invoice prints at its foot
(`Saldo Cta Cte …`, `-1.522,34`, `CAE N°: 86327284406071`, `Venc. de CAE: 17/08/2026`, `Pág.1/1`).
Traced end to end, on `tests/fixtures/casos/66cd35e9-….jpg` (docling 2.126.0):

| Layer | Observation |
|---|---|
| Pixels | **RapidOCR alone reads the band** (cropped at y ≥ 0.86): all five lines, at 1×, 2× and 3× |
| Layout | The layout model files the band as `page_footer` ×4 plus `Pág.1/1`, with a `picture` for the QR — the totals band above it is `key_value_region` + `text` |
| OCR | The page's **75 `textline_cells` include all five lines**: the engine read them |
| Document | The engine files `page_footer` items in the **`furniture` content layer**, and `iterate_items()`, `export_to_text()` and `export_to_markdown()` traverse the **`body` alone** unless told otherwise — **43 items by default against 48** with the layer stated. `doc.furniture` (the group) is empty; the items are ordinary ones carrying `content_layer = FURNITURE` |
| Our seam | `_items()` was `document.iterate_items()` and `_export()` called the export with no arguments, so those five lines reached **no** artifact — not `document.json`, not `blocks`, not `layout.region_bboxes`, not `text.txt`, not `mixed.txt` |

**The fix is the seam reading the page whole.** `primitives.CONTENT_LAYERS = frozenset({"body",
"furniture"})` is asked for by `_items()` and by `_export()` — the traversal *and* both exports, so an
artifact cannot hold a footer the block list beside it dropped. Plain layer names are enough: the
engine's own `ContentLayer` is a `str` enum, so the set compares and hashes by value and the seam
needs no `docling_core` import. No flag and no option: this is the page's content, not a capability
the caller claims, and the *block's own type* (`page_header`/`page_footer` → `"other"`) is what still
distinguishes a margin from the body (`subplan-procesador-ocr.md` §9, **decision 8**).

**Hand run (real engine).** `ocr.py --out … mixed <invoice>` now ends
`… 17.898,30` / `Saldo Cta Cte ...   -1.522,34   CAE N°: 86327284406071` / `Venc. de CAE:
17/08/2026` / `Pág.1/1` — and the first of those rows is the row rendering doing its job: the three
cells share a band of the page. `ocr.py text <invoice>` carries the same lines, so the two readings
agree about what the page says.

**The double models the layer rule**, or the fix would be untestable: items carry a `content_layer`,
`iterate_items()`/`export_to_text()`/`export_to_markdown()` honour the requested set and default to
`body`, and a new factory (`footer_document`) holds a `page_footer` line the body does not. Three new
guards: the double's own layer rule, the seam's reading of the footer, and the bench rendering it.

**Mutation evidence** (two rows, each applied to `src/docflow/ocr/primitives/__init__.py` and restored
by the inverse edit).

| Mutation | Observed failure | Restored |
|---|---|---|
| `_items`: drop `included_content_layers=CONTENT_LAYERS` | 2 red — `test_a_page_footer_is_read_instead_of_being_left_in_its_own_layer` and `test_ocr_mixed_renders_a_page_footer_instead_of_dropping_it` | inverse edit |
| `_export`: call the export with no arguments | 2 red — the same pair, this time on the exported text rather than the blocks | inverse edit; `pytest -q` 777 passed |

**Gate evidence.**

```
pytest                     777 passed
ruff check .               All checks passed!
ruff format --check .      181 files already formatted
pylint src tests           10.00/10 — one message, the pre-existing
                           src/docflow/pdf/entrypoints.py:475 R0912 (15/12)
```

**Plan revision applied in the same pass** — this one belongs to the *processor*, not the bench:
`subplan-procesador-ocr.md` §9 gained **decision 8** (the whole-document read, with the measurement),
and `wbs-procesador-ocr.md` §OCR-04 gained the layer rule in its scope and an acceptance criterion,
§OCR-14 the double's obligation to model it. `docs/3party/docling.md` §D records the engine evidence:
the two `extract_docling_*` rows now name `included_content_layers`, and a note carries the
measurement (75 cells, 43 vs 48 items, `doc.furniture` empty). `scripts/tools/readme.md` gained the
one-line rule.

**Cost, stated.** A running head or a page number now enters `blocks`, `text.txt` and the metrics of
every page that carries one, typed `"other"`. That is the trade: on an invoice the footer is legally
required content, and a consumer that wants the body alone filters by type rather than losing the
line by default.
