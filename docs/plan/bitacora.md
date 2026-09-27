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
