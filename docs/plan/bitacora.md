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
