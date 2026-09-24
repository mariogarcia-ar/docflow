# Docling — dossier

> Kind: Python library (`docling`)
> Processor / seam: `docflow.ocr.primitives`
> Status: collecting (2026-09-24)

## A. Identity and provenance

| Field | Value |
|---|---|
| `engine` value in metadata | `docling` — recorded in metadata, **not** a user-selectable engine option |
| Kind | **Python library** (with a `docling` CLI that we do not use); model inference behind a pipeline |
| Upstream | <https://docling-project.github.io/docling> — repo `docling-project/docling` |
| Context7 IDs | `/websites/docling-project_github_io_docling` (general docs — queried 2026-09-24), `/websites/docling-project_github_io_docling_reference_document_converter` (API reference), `/docling-project/docling` (repo) |
| Maintainer / cadence | IBM Research / docling-project; frequent releases (2.x) |
| Version this page was read against | local **2.126.0** (`docling-core` 2.95.0, `docling-ibm-models` 4.0.2); docs read at the 2.x line |

## B. Install, pin and version discovery

- **Install shape:** pip (`docling`), plus model artifacts that are downloaded on first use unless `artifacts_path` points at a local copy.
- **Pin home:** `pyproject.toml` (`OCR-02` pins `docling`) — pin `TBD`, today `dependencies = []`.
- **Version at runtime — three versions, not one:** `docling.__version__` → `2.126.0` (verified); the CLI prints a fuller set:

  ```
  Docling version: 2.126.0
  Docling Core version: 2.95.0
  Docling IBM Models version: 4.0.2
  ```

  Decision for `get_engine_version` (`OCR-02`): record the `docling` version (importlib metadata / `__version__`), and note that the core + models versions are the ones that actually change output — open question (K).
- **Absent / present check:** the Docling import happens **inside** `convert_image_with_docling`, never at module import, so `import docflow.ocr.primitives` succeeds with Docling absent (and so does the whole suite, which never touches it).
- **Environment facts (2026-09-24):** `docling` CLI on PATH; `tesseract` present (needed by `TesseractCliOcrOptions`); no GPU assumed.

## C. Licence and distribution posture

- Docling is released under the **MIT** licence — `TBD`: confirm against the installed package metadata.
- **Model licenses are a separate question from the library licence**: the layout/table/OCR weights are downloaded at runtime. A packaged distribution must know which models it ships or fetches, and under what terms. Open question (K).
- `enable_remote_services` defaults to **`False`** — the documented default, and the one we keep: flipping it would send documents to an external API. Any remote picture-description option requires it explicitly.

## D. Interface contract — the methods we need

Mapped to `subplan-procesador-ocr.md` §3.4 (the closed 25-name surface).

| Primitive | Docling API |
|---|---|
| `load_docling_pipeline` | `DocumentConverter(format_options={InputFormat.IMAGE: ImageFormatOption(pipeline_options=...), InputFormat.PDF: PdfFormatOption(...)})` |
| `configure_image_pipeline` | `PdfPipelineOptions` attributes: `do_ocr`, `do_table_structure`, `table_structure_options = TableStructureOptions(do_cell_matching=True)`, `ocr_options`, `generate_page_images`, `images_scale`, `artifacts_path`, `accelerator_options` |
| — OCR backend choice | `ocr_options` ∈ `EasyOcrOptions`, `TesseractOcrOptions`, `TesseractCliOcrOptions`, `OcrMacOptions` (macOS only), `RapidOcrOptions`; each supports `force_full_page_ocr` (slower; use when layout extraction is unreliable or the page is scanned) |
| — hardware | `AcceleratorOptions(num_threads=4, device="auto", cuda_use_flash_attention2=False)` |
| `normalize_docling_options` | fold the six option flags into the pipeline config **inline** — no `enable_*` / `should_enable_*` predicate per flag |
| `convert_image_with_docling` | `converter.convert(path)` → `ConversionResult` (the **engine call** and the double's injection point) |
| `extract_docling_text` / `_markdown` | `result.document.export_to_text()` / `export_to_markdown()` |
| `extract_docling_tables` | `result.document.tables` → `normalize_table` → `table_to_markdown` |
| `extract_docling_blocks` | `result.document.iterate_items()` (reading order) |
| `extract_docling_layout` | page/block geometry on `result.document.pages` (72 points per inch; `normalize_bbox` converts) |
| `get_engine_version` | `docling.__version__` (see B) |
| `build_ocr_metadata` | plus `result.status`, `result.errors`, `result.input` |
| `validate_ocr_*`, `write_*_atomic`, `ensure_directory` | ours — no Docling call |

**Verified imports** (Context7, `/websites/docling-project_github_io_docling`) — the names and their homes, so the seam does not guess a module path:

```python
from docling.document_converter import DocumentConverter, ImageFormatOption, PdfFormatOption
from docling.datamodel.base_models import ConversionStatus, DocumentStream, InputFormat
from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions, TesseractOcrOptions
```

- **Image input is a first-class format, not a PDF with one page:**
  `DocumentConverter(format_options={InputFormat.IMAGE: ImageFormatOption(pipeline_cls=..., pipeline_options=...)})`, where `ImageFormatOption` exposes `backend`, `backend_options`, `pipeline_cls`, `pipeline_options`.
- **There is an in-memory input path:** `DocumentStream(name="doc_0.tiff", stream=buf)` converts bytes without a file on disk. Our contract publishes artifacts, so the image is already a file when the OCR processor gets it — but this is the escape hatch if a future caller hands us bytes.
- **Batch sizes are throughput knobs, not output knobs:** `PdfPipelineOptions(ocr_options=..., ocr_batch_size=..., layout_batch_size=..., table_batch_size=...)`. They belong in `AcceleratorOptions`-style metadata, never in `processing_key`.
- **`enable_remote_services=True` is required for a remote inference service** (e.g. a VLM served over HTTP) — i.e. the `False` default is a real guard, not a no-op.

**Input formats:** `InputFormat` includes `IMAGE` alongside `PDF`, `DOCX`, `PPTX`, `HTML`, `MD`, `CSV`, `XLSX` — verified locally (first 12 members). The OCR processor is fed a prepared **image**, so `InputFormat.IMAGE` is the path we use; `PDF` is Docling's own option, not ours.

**Status vocabulary:** `ConversionStatus.SUCCESS` / `PARTIAL_SUCCESS` / `FAILURE` — note the collision with our own `PARTIAL`: Docling's `PARTIAL_SUCCESS` maps to our per-page partial semantics, and the mapping must be written once, explicitly.

## E. Inputs, outputs and artifact naming

| Field | Value |
|---|---|
| Inputs | a prepared image file (`ocr_ready` variant) — and only that; the processor never reads a PDF |
| Outputs | a `DoclingDocument` in memory (`export_to_markdown` / `export_to_text` / `export_to_dict` / `export_to_html`), plus image references if `generate_page_images` is on |
| Our naming | `text.txt`, `document.md`, `document.json` are produced by `OCR-06` — the single producer; Docling writes nothing into our artifact tree |
| Ordering | reading order comes from the document model and is preserved by `preserve_reading_order`; our output ordering is ours to guarantee |
| Encoding | text is Python `str`; the atomic writers fix UTF-8 |

## F. Determinism levers

| Lever | Enters `processing_key`? |
|---|---|
| The six option flags (OCR on/off, table structure, backend, force-full-page, images, scale) | yes |
| OCR backend and its language/config | yes |
| `images_scale`, `generate_page_images` | yes (they change artifacts) |
| `AcceleratorOptions.device` / `num_threads` | **no** — throughput, not output; record it in metadata, keep it out of the key |
| Docling, docling-core and model versions | yes — the recorded `engine_version` |
| Model weights (downloaded vs. `artifacts_path`) | yes in effect — pin or vendor them before claiming determinism |

## G. Failure modes and our error mapping

Docling's failures arrive in two shapes: a raised Python exception, and a `ConversionResult` whose `status` is `FAILURE` **with a populated `errors` list** (the conversion returns rather than raises).

| Engine signal | Our `OCRErrorType` |
|---|---|
| `status == FAILURE`, generic conversion failure | `OCR_ERROR` |
| `status == PARTIAL_SUCCESS` | not an error — page status `PARTIAL`, errors preserved per item |
| exception while building layout/structure | `LAYOUT_ERROR` |
| exception during table structure / cell matching | `TABLE_EXTRACTION_ERROR` |
| model missing, download failure, backend not installed (e.g. Tesseract absent) | `ENGINE_ERROR` |
| export (`export_to_markdown` / `_dict`) raising or producing nothing | `EXPORT_ERROR` |
| unreadable input image / bad extension | `UNSUPPORTED_IMAGE` / `INVALID_INPUT` |
| I/O on our own writers | `IO_ERROR` |
| anything else | `INTERNAL_ERROR` |

`OCRErrorType` as declared in `src/docflow/ocr/contracts.py` (verified, matches the subplan's nine): `INVALID_INPUT`, `UNSUPPORTED_IMAGE`, `ENGINE_ERROR`, `OCR_ERROR`, `LAYOUT_ERROR`, `TABLE_EXTRACTION_ERROR`, `EXPORT_ERROR`, `IO_ERROR`, `INTERNAL_ERROR`.

**The trap to avoid:** an empty `text.txt` from a `SUCCESS` conversion of a blank or unreadable page must be a reported failure, not a successful empty artifact (no silent stand-in).

## H. Seam ownership and the double

| Field | Value |
|---|---|
| Owning module | `docflow.ocr.primitives` — the only place that knows Docling |
| Injection point | `monkeypatch.setattr("docflow.ocr.primitives.convert_image_with_docling", fake_docling)` — **never** at `extract_docling_*`, which is the half of the module the fake must exercise |
| What "native-shaped" means | Docling's own values (`ConversionResult`-shaped: document, status, errors) — never our `OCRDocument` |
| Shared helper | `missing_from_double(...)` does **not** apply here: the seam replaces a symbol of ours, not an engine namespace |
| Other processors | none may reach Docling; `"docling"` is recorded, not selected |

## I. Cost, latency and limits

- The dominant cost is **model inference** (layout model + table former + OCR model) per page; `force_full_page_ocr` is documented as often slower than hybrid detection.
- First run pays the model download; `artifacts_path` removes it (and is the only honest way to claim offline operation).
- `device="auto"` picks GPU when available; CPU-only is the safe assumption for the PoC and for CI.
- No documented hard limits on input size in what was read; the practical limit is memory for page images at `images_scale=2.0`.

## J. Alternatives and swap story

- Docling is the **only** OCR engine (`README.md` §9.3) — there is no second engine to swap to inside this processor, and the plan says so deliberately.
- Swapping it would touch `ocr/primitives/` and replace the double's shape; the `OCRDocument` intermediate representation is the thing that survives a swap, which is why nothing downstream sees a Docling type.

## K. Open questions and drift log

- [x] The reading path for `get_engine_version` — **answered**: `docling.__version__` (`2.126.0`), with the CLI printing core + models versions too.
- [x] Which module a Docling symbol lives in — **answered** by the verified imports in §D (the reference and the general docs agree).
- [ ] Which version string is `engine_version` when three are installed (`docling`, `docling-core`, `docling-ibm-models`)? The models version is the one that changes output.
- [ ] Which OCR backend does `configure_image_pipeline` select, and is `tesseract` (present locally) or `RapidOcrOptions`/EasyOCR the intent? A backend that is not installed must be an `ENGINE_ERROR`, not a silent fallback to another one.
- [ ] Are model weights vendored, pinned or downloaded? Determinism and licensing both depend on the answer.
- [ ] The exact `ConversionStatus.PARTIAL_SUCCESS` → our `PARTIAL` mapping, written once where both sides are visible.
- [ ] `images_scale` / `generate_page_images`: does the OCR processor ever emit an image artifact, or are they always off?
- [ ] Drift log: (2026-09-24) docling 2.126.0 / core 2.95.0 / ibm-models 4.0.2 installed; `InputFormat.IMAGE` and `ImageFormatOption` confirmed; `enable_remote_services` left at its `False` default; the `DocumentConverter` reference page also documents a `ConversionResult.pages` accessor in the image-parquet example — that accessor is **not** used by us (`result.document` is). No seam change observed.
