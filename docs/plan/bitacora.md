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
