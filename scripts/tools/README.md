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
| `image.py` | `IMG-15` | not started — `procesador-image` has no implementation yet |
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

## Where the decisions live

- [`docs/plan/README.md`](../../docs/plan/README.md) §4.1 — the lab-tool convention, the
  `var/tools/<tool>/` output root, and the three boundaries.
- [`docs/plan/subplan-procesador-pdf.md`](../../docs/plan/subplan-procesador-pdf.md) §10 —
  `pdf.py`'s command surface and acceptance criteria.
- [`docs/plan/issues/wbs-general.md`](../../docs/plan/issues/wbs-general.md) `GEN-21` — the
  convention as a cross-cutting task.
- [`tests/tools/test_pdf_tool.py`](../../tests/tools/test_pdf_tool.py) — the boundaries above
  as executable checks, including the two acceptance scenarios.
