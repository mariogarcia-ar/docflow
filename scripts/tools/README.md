# Lab tools

Operator command-line tools for exercising a processor by hand: without writing throwaway
Python, and without going through the orchestrator.

**These are not part of the library.** Nothing under `src/docflow/` imports anything here, so
deleting this directory leaves the library and its tests untouched. The convention that makes
that true is `docs/plan/README.md` §4.1 and the cross-cutting task `GEN-21`; this file is the
*operator's* view of it.

| Tool | Task | Status |
|---|---|---|
| [`pdf.py`](pdf.py) | `PDF-14` | ✅ available |
| [`image.py`](image.py) | `IMG-15` | ✅ available |
| `image_fixtures.py` | `IMG-03` | ✅ available — rebuilds the committed image fixtures |
| `ocr.py` | `OCR-14` | not started |
| `llm.py` | `LLM-16` | not started |
| `workflow.py` | `ORC-20` | not started |

Each tool is built **after** its processor's acceptance evidence is green, so a missing tool
means a missing processor rather than unfinished packaging.

---

## `pdf.py`

### Requirements

Poppler on `PATH` — `pdfinfo`, `pdftotext`, `pdfimages`, `pdfseparate`, `pdftoppm`,
`pdfunite`. Verified against **Poppler 25.02.0**.

```bash
brew install poppler            # macOS
apt-get install poppler-utils   # Debian/Ubuntu
```

No install step and no virtualenv activation is needed: the tool puts `src/` on the path
itself, so `python scripts/tools/pdf.py` works from a clean checkout.

### Usage

```bash
python scripts/tools/pdf.py <subcommand> <pdf> [options]
```

Every subcommand takes the document as its first argument, and writes nothing beside it.

| Subcommand | What it does | Writes |
|---|---|---|
| `inspect <pdf>` | what the document reports about itself: version, page count, per-page size | nothing |
| `split <pdf>` | one self-contained PDF per page | `page_NNN/source/page.pdf` |
| `render <pdf> --page N [--dpi D]` | render one page to a PNG (default 200 dpi) | `page_NNN/render/page.png` |
| `text <pdf> --page N` | print the page's native text to stdout | nothing |
| `blocks <pdf> --page N` | print the page's text blocks with their bounding boxes | nothing |
| `images <pdf> --page N` | extract the page's embedded images | `page_NNN/embedded_images/image_NNN.png` |
| `classify <pdf>` | per-page metrics and the `TEXT` / `IMAGE` / `MIXED` classification | nothing |
| `run <pdf> [--dpi D]` | the whole processor: every page, then a result summary | the full `page_NNN/` tree, `source/document.pdf`, `metadata.json` |

Global flags, accepted **before or after** the subcommand:

| Flag | Default | Meaning |
|---|---|---|
| `--out <dir>` | `var/tools/pdf/` | where the run tree goes |
| `--json` | off | machine-readable output instead of the human summary |

### Examples

```bash
# What is in this document?
python scripts/tools/pdf.py inspect mi.pdf
# mi.pdf  (3 page(s))
#   PDF version   : 1.7
#   Encrypted     : no
#   page sizes   :
#     page_001: 612.0 x 792.0 pt
#     …

# One PDF per page.
python scripts/tools/pdf.py split mi.pdf
# var/tools/pdf/mi-a1b2c3d4/page_001/source/page.pdf
# …

# Read a page's text layer.
python scripts/tools/pdf.py text mi.pdf --page 2

# Where does the text sit? Bounding boxes in PDF points.
python scripts/tools/pdf.py blocks mi.pdf --page 1
# block_001  [72.0, 192.102, 127.044, 202.277]  page 1 of 3

# Which pages are text and which are pictures?
python scripts/tools/pdf.py classify mi.pdf
# page 1: TEXT     154 chars  0 img  text_cov=0.0265 image_cov=0.0000

# Render at a resolution no document run would use — the reason a tool may
# reach a processor's primitives directly.
python scripts/tools/pdf.py render mi.pdf --page 1 --dpi 400

# Full run, then read what it produced.
python scripts/tools/pdf.py run mi.pdf
# mi.pdf -> success (VALID)
#   3 page(s), 13 artifact(s)

# Machine-readable, for a script.
python scripts/tools/pdf.py --json run mi.pdf | jq '.pages[].classification'
```

### Output layout

```text
var/tools/pdf/mi-a1b2c3d4/
├── source/document.pdf          # `run` only: the immutable reference copy
├── metadata.json                # `run` only
├── page_001/
│   ├── source/page.pdf          # `split`, `run`
│   ├── render/page.png          # `render`, `run`
│   ├── native_text/             # `run`
│   │   ├── text.txt
│   │   └── blocks.json
│   ├── embedded_images/         # `images`, `run` (absent when the page has none)
│   │   └── image_001.png
│   └── metadata.json            # `run` only
└── page_002/ …
```

The directory name is the input's **stem plus a short hash of its bytes**, so two runs over
the same file land in the same tree — which is what makes a manual experiment reproducible
and lets an `inspect` after a `run` read what the run wrote. Copying a file under a new name
with identical bytes shares the hash, not the stem.

`var/` is git-ignored. Nothing is ever written beside the input document.

### Exit codes

| Code | Meaning |
|---|---|
| `0` | success |
| `1` | the document could not be processed — the typed cause is printed, e.g. `PDFPrimitiveError: … is encrypted; passwords are not handled yet` |
| `2` | the arguments were wrong: no such file, unknown subcommand |

A failure prints a cause, never a traceback. The library's typed classification
(`ENCRYPTED_PDF`, `CORRUPTED_PDF`, `MISSING_FILE`, `PAGE_OUT_OF_RANGE`, …) reaches you
through this path, which is the only place a human sees it.

### Notes worth knowing

- **`text` on an image-only page prints nothing.** An empty text layer is a measurement, not
  an error. The tool does not fall back to OCR — that decision belongs to the orchestrator,
  and `pdf.py` never makes workflow decisions.
- **`classify` writes no files.** It reads the image *listing* rather than extracting, so
  measuring a document leaves no residue.
- **`images` publishes only images.** Soft and hard masks are extracted by the engine as
  separate files but are pieces of another image; they are excluded, and the files for them
  are removed so the directory holds exactly the artifacts the tool reports.
- **`split` arranges, it does not reimplement.** The extraction is `split_pdf`; the tool puts
  the flat output into the `page_NNN/source/` layout.

### Boundaries

A tool is a caller. Three rules hold, and each is asserted by tests in
`tests/tools/test_pdf_tool.py`:

- **Calls, never reimplements.** `split` calls `split_pdf`; it never shells out to
  `pdfseparate`. `classify` calls `classify_pdf_page`; it never re-derives the thresholds.
- **The library never imports a tool.** Verified by reading the import graph, and by
  importing `docflow.pdf` in a fresh interpreter that never sees this directory.
- **Adds no seam.** No new contract, no new options type, no behaviour the library lacks. A
  missing operation belongs in the *processor* — fix it there, not in its tool.

One deliberate asymmetry: **a tool may reach a processor's `primitives/` directly.** That is
the point of a lab bench — `render --page 1 --dpi 400` drives `render_page_to_image` without
a whole document run, which the orchestrator is forbidden to do (`GEN-19`). A tool sits
outside both frontiers. **`workflow.py` will be the exception**, bound by the same
prohibition the orchestrator is, because it composes the four processors rather than driving
one.

---

## `image.py`

### Requirements

None beyond the library's own dependencies: OpenCV, numpy and Pillow, all declared in
`pyproject.toml` and installed by `pip install -e .`.

### Usage

```text
python scripts/tools/image.py info      page.png                    # format, size, resolution
python scripts/tools/image.py metrics   page.png                    # full ImageMetrics
python scripts/tools/image.py normalize page.png                    # → normalized.png
python scripts/tools/image.py ocr-ready page.png                    # → ocr_ready.png
python scripts/tools/image.py vlm-ready page.png                    # → vlm_ready.png
python scripts/tools/image.py classify  page.png                    # one of the four values
python scripts/tools/image.py run       page.png --ocr-ready --vlm-ready
python scripts/tools/image.py crop      page.png --box 10,20,300,400
```

Global flags: `--out <dir>` (default `var/tools/image/`), `--json`.

### Output layout

```text
var/tools/image/page-81f28fc2/
├── normalized.png
├── ocr_ready.png           # only when requested
├── vlm_ready.png           # only when requested
├── regions/region_001.png  # only for an explicit crop
├── metadata.json           # the processor's own record
└── tool-run.json           # which command produced this directory
```

### Exit codes

| Code | Meaning |
|---|---|
| `0` | success |
| `1` | the image could not be processed — the typed cause is printed, e.g. `ImagePrimitiveError: TRANSFORMATION_ERROR: the region (0, 0, 99999, 99999) leaves the 400x300 image` |
| `2` | the arguments were wrong: no such file, unknown subcommand |

A failure prints a cause, never a traceback.

### Notes worth knowing

- **`ocr-ready` and `vlm-ready` are separate subcommands.** They are not interchangeable: OCR
  wants one channel, deskewed, denoised and binarized, while a VLM needs the colour and layout
  intact. A single `prepare` command with a flag would teach the opposite — which is why the
  split is a property of the tool's *surface*, not of its documentation.
- **`metrics` and `classify` write no image.** They read and print; measuring leaves no residue.
  The output directory is still created, because that is where the next command in the same
  experiment writes.
- **`crop` refuses a box it cannot honour.** A region that is degenerate or leaves the image is
  a typed `TRANSFORMATION_ERROR`, never a silently clipped one: a clipped crop is a *different
  region* than the one asked for, with nothing to tell you so. Write a negative coordinate as
  `--box=-5,0,10,10`; argparse reads a bare `-5,...` as another option.
- **There is no `--engine` flag.** The engine seam is not an operator preference: a flag would
  let you produce a directory whose provenance the command line does not record. OpenCV is
  compiled in, and that is what the lab exercises.
- **`tool-run.json` is the tool's record, `metadata.json` is the processor's.** The tool writes
  its own file rather than adding fields to the processor's, because that file is the
  orchestrator's contract and a tool must not extend it from outside the library.

---

## `image_fixtures.py`

Rebuilds the committed fixtures under `tests/fixtures/image/`. Unlike the other tools this one
belongs to no product task's command surface — it exists because `IMG-03` needs image bytes that
are *in the repository*, so a failing test points at a file rather than at whatever a `conftest`
happened to synthesise that run.

```bash
python scripts/tools/image_fixtures.py            # write the fixtures
python scripts/tools/image_fixtures.py --check    # report drift without writing
```

It is idempotent: running it twice leaves the tree identical, so `--check` is a cheap way to
confirm the committed files still match their source.

**Requirements:** `numpy`. The PNG encoder is hand-rolled on `zlib`, and the skew rotation is
hand-written nearest-neighbour, so the fixture bytes do not shift when an image library is
upgraded. The script deliberately does **not** import `docflow.image.primitives`: a generator built
on the code under test could not tell "the fixture is wrong" from "the reader is wrong".

| Fixture | What it is for |
|---|---|
| `color_layout.png` | Colour that carries information: three pure-primary bars and dark red "text". A pipeline that dropped colour could not tell the bars apart, so this is what proves a VLM variant kept it. |
| `skewed_text.png` | A text-like page rotated by 4°, for the deskew path. |
| `embedded_logo.png` | A small logo-like mark, standing in for a logo lifted out of a PDF. |
| `corrupt.png` | Keeps its PNG signature and a valid header, then has a damaged `IDAT` stream. This is the file that distinguishes `DECODE_ERROR` from `UNSUPPORTED_FORMAT`: it is *recognised* as a PNG and then fails to decode. |

---

## Where the decisions live

- [`docs/plan/README.md`](../../docs/plan/README.md) §4.1 — the lab-tool convention, the
  `var/tools/<tool>/` output root, and the three boundaries.
- [`docs/plan/subplan-procesador-pdf.md`](../../docs/plan/subplan-procesador-pdf.md) §10 —
  `pdf.py`'s command surface and acceptance criteria.
- [`docs/plan/issues/wbs-general.md`](../../docs/plan/issues/wbs-general.md) `GEN-21` — the
  convention as a cross-cutting task.
- [`tests/tools/test_pdf_tool.py`](../../tests/tools/test_pdf_tool.py) — the boundaries above
  as executable checks, including the two acceptance scenarios.
