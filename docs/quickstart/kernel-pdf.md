# Quickstart — what K2 (`kernel.pdf`) can do today

**Status: honest, and complete for Stage 1.** Every kernel has landed, and seven
of the eight are reachable in this workspace — K6 needs a provider key;
this page covers the PDF one, whose kernel **and** adapter have landed and whose split
between them is now part of the design. Everything below has been run and its output is
quoted from a real invocation.

`docflow-kernel` now dispatches this kernel's operations — see `lab-cli.md` for the
bench. This page drives the **library**, called from Python, which is where the
detail lives. That is
the intended shape: `sad.md` ADR-008 makes the library first and the CLI one caller
of it.

---

## Setup

```bash
pip install -e ".[dev]"      # pytest, ruff, pylint
```

Two engines are needed at runtime, and **neither is a declared dependency yet**
(`pyproject.toml` has `dependencies = []` until the adapters are tallied):

```bash
pip install pymupdf          # the page engine
brew install poppler         # provides the `pdftotext` binary
```

Both are resolved lazily, by the adapter. A missing one is a typed `Reason` with a
remedy in the message — never a substitute engine, because a different engine reading
the same bytes is a different measurement wearing this one's name.

## Where the code lives — three files, and the direction matters

| File | What it holds |
|---|---|
| `docflow/ports/pdf.py` | `PdfSource` — what a **caller above Stage 1** depends on |
| `docflow/adapters/pdf.py` | `PdfEngine` (implements the port) and `PyMuPdfVendor` (owns `pymupdf` + `pdftotext`) |
| `docflow/kernels/pdf_vendor.py` | `PdfVendor` — what the **analysis** asks a reader through |
| `docflow/kernels/pdf.py` | the analysis: shapes, invisible text, producer contradictions |

The direction is the opposite of the obvious one:

```text
ports/pdf.py            PdfSource        the caller's contract
      ^
adapters/pdf.py         PdfEngine        implements it; owns the vendors
      |
      v  calls
kernels/pdf.py          analysis         shapes, invisible text — no vendor
      |
      v  asks through
kernels/pdf_vendor.py   PdfVendor        the seam the analysis declares
      ^
adapters/pdf.py         PyMuPdfVendor    the implementation over the two vendors
```

**A kernel may not import an adapter** — the arrow points down, and the layer is
guarded by a test. So the vendor arrives as an *argument*, the same inversion
`PdfSource` uses one level up. `kernels/pdf.py` imports only `__future__`,
`collections`, `contextlib`, `pathlib`, `re`, `types`, `typing` and `docflow` — **no
PDF library at all.** It was 1689 lines when the vendors were inside it; it is 983.

## The whole surface

```python
from docflow.adapters.pdf import PdfEngine   # the adapter
from docflow.ports import PdfSource          # the contract

engine = PdfEngine(min_chars=10)             # required, never defaulted
isinstance(engine, PdfSource)                # True
```

Five operations make up the port — `probe`, `classify`, `tokens`, `render`, `split`.
The adapter also exposes `effective_dpi` and `layout_text`, which are **not** on
`PdfSource`: the port is frozen by `plans/README.md` §3, so a sixth member would
re-open `E04-01`'s gate. They are reachable because a caller needs them, and
`kernel-cli.md` §9 already lists `pdf facts` as an `MVP` target.

All of them return `KernelResult`, which has exactly two states: a value with
evidence, or no value with a `Reason`. There is no third state and no exception for
an expected negative outcome.

The kernel's own functions take `vendor=` as a keyword-only argument and have **no
default** — a default would have to name a concrete reader, which is the import the
split exists to avoid. Call the adapter instead; reach for the kernel directly only
when you are writing the reader.

## 1. `probe` — what is this file?

```python
result = engine.probe(Path("documento.pdf"))
result.value.observed
# {'file': 'documento.pdf', 'page_sizes': [[612.0, 792.0]], 'producer': '...',
#  'creator': '...', 'format': 'PDF 1.7', 'encrypted': False}
```

Page count, page sizes, declared metadata, encryption state. An unopenable file
returns `unsupported_format` or `encrypted` — **never** an empty observation set
standing in for a successful probe.

## 2. `classify` — what shape is this page?

**`min_chars` is required, and it is on the constructor.** It is the caller's
threshold, not the kernel's — and it is not a port member either, so it enters at the
adapter: what
counts as enough text to judge is a policy value (`prd.md` FR-15), and a kernel
holding its own constant has made a routing decision whether or not it prints one.

```python
result = engine.classify(Path("documento.pdf"), page=1)
result.value.observed["shape"]        # 'text' | 'image' | 'mixed' | 'blank'
result.value.observed["invisible_text"]
# False
```

Four shapes, and `blank` is one of them — a page with no content at all, which is
not the same statement as *a page with no text*. A blank page returns
`blank_page`; the measurements still come back on `result.evidence`.

`invisible_text` is the interesting one. A scan with a stale OCR layer behind it
carries text that **draws nothing**, and PyMuPDF's `get_text()` returns that text as
ordinary text — so a classifier built on character counts reports a text page and
is wrong. The layer is detected as what it is, a `Tr 3` no-draw instruction in the
content stream, and **invisible text does not count as text** when naming the
shape: such a page is `image`.

## 3. `effective_dpi` — how many real pixels does it hold?

The measurement comes from the **embedded pixels** divided by the area they are
placed in. Never from the request, never from metadata: metadata records what
someone intended.

```python
result = engine.effective_dpi(Path("escaneo.pdf"), page=1)
result.value.measurements
# {'effective_dpi': 100.07, 'image_count': 1.0}
```

Real output from a fixture: **100.07 DPI**. That is what this corpus looks like —
see `docs/findings/01-corpus-resolution-budget.md`, where four of five scans
measure under 300 DPI.

`effective_dpi` returns a page with **no image** as a typed reason rather than a
`0.0`: a page with no embedded pixels has no effective resolution to report, and a
zero would read as a measurement that was actually taken.

A text page that *does* embed a picture is measurable, and its number is the
picture's rather than the page's — one fixture here reports 95.96 DPI from two
embedded images. The shape stays `mixed`; the resolution is about the pixels, not
about the document's kind.

## 4. `render` — a page as a bitmap, and it never upscales

```python
result = engine.render(Path("escaneo.pdf"), pages=[1], dpi=600)
result.value                # None
result.reason.code          # 'insufficient_effective_resolution'
result.evidence.observed["files_written"]   # 0
```

**This is the function to know about.** Ask for a resolution the source cannot
supply and it refuses, with the measured number in the evidence and **no file
produced**. It does not enlarge the page and report the request as met — "larger
and no more legible" is the failure row 4 of the silent-failure matrix is named
for, and the legacy PoC committed it on four of these five fixtures.

The threshold is the *measured* resolution, not a constant, so whether a request
succeeds depends on the document rather than on the number you passed. On the
five committed scans, all at `--dpi 200`:

| Fixture | Measured | At 200 DPI | At 600 DPI |
|---|---:|---|---|
| `3ac5a2ec…` | 120.0 | refused | refused |
| `68623f4b…` | 100.07 | refused | refused |
| `722106ec…` | 271.43 | **renders** | refused |
| `9b7a423c…` | 100.07 | refused | refused |
| `bddb529d…` | 294.35 | **renders** | refused |

Vector pages have no pixels to fall short of, so a text PDF renders at any
resolution asked.

Several pages are stacked vertically into one PNG, because `Bytes` is one buffer
and inventing a container format here would be a second contract.

## 5. `tokens` — positioned words from the text layer

Read by the `pdftotext` binary in its `-bbox` mode, converted to **source page
coordinates at the DPI you asked for** — so a token's box means the same thing as
the box `render` produces.

```python
result = engine.tokens(Path("documento.pdf"), pages=[1], dpi=300)
[(t.text, round(t.bbox.x, 1), round(t.bbox.width, 1), t.confidence) for t in result.value][:2]
# [('FACTURA', 1423.0, 239.6, None), ('0138-00000236-A', 1703.0, 405.1, None)]
```

**`confidence` is always `None`.** A text layer is not a recogniser and reports no
confidence at all; `None` is never coerced to `1.0`, because a perfect score would
be a claim nobody made.

Boxes scale with the requested DPI, so the same word at 144 DPI has a box twice
the size of the one at 72:

```python
at_72  = engine.tokens(path, [1], dpi=72).value[0].bbox.x
at_144 = engine.tokens(path, [1], dpi=144).value[0].bbox.x
round(at_144 / at_72, 2)   # 2.0
```

## 6. `split` — cut a page range out as a new document
```python
result = engine.split(Path("documento.pdf"), pages=[1])
result.value.media_type                       # 'application/pdf'
result.evidence.observed["source_pages"]
# [{'source_page': 1, 'width': 595.0, 'height': 842.0}]
```

The **requested order is honoured** — reordering pages is a legitimate request, and
sorting it would make the output not match the selection. Page boxes are preserved,
and the mapping back to the source range travels in the evidence, because a split
that separates a document from its pages is a silent failure: the output is a
perfectly valid PDF of the wrong thing.

A repeated page is refused rather than silently duplicated.

---

## 7. `layout_text` — the reader's own character grid

> **Not part of the port contract, and not wired into any flow.** This operation
> exists for callers that need the layout as *text*. It is deliberately absent
> from `docflow/ports/pdf.py`, because `plans/README.md` §3 freezes the port
> interfaces and Plan 2 may not change them. It is under consideration as an
> optimisation for the text path; nothing depends on it today.

```python
result = engine.layout_text(Path("boleto.pdf"), pages=[1])
result.value
# 'Boleto:SUV-255671438-0                          Butaca: 56\n...'
```

`pdftotext -layout` renders each page as a fixed grid of characters, so columns,
aligned fields and tables survive as the whitespace they occupy on the page. It is
the cheapest useful read of a PDF that already carries text.

**On material whose meaning depends on what sits beside what, it is the better
read.** A two-column ticket flattened into one column is not a different rendering
of the same facts, it is a different set of facts. From the committed fixture
`casos/9dfc597f` — the document that motivated this in the previous system:

```
Se anuncia a: VENADOTUERTO                       Arribo Estimado: 28/08/2026 18:23
```

The left column's "where it departs from" stays paired with the right column's
"when it arrives", because the gap between them is preserved.

### Byte-identical to the previous system's command

```python
engine.layout_text(path, [1]).value == legacy_output_1_to_1   # True
```

Verified against `pdftotext -layout -enc UTF-8 -q -f 1 -l 1 <file> -`. The encoding
is passed explicitly because the default follows the host locale, and two machines
would otherwise disagree on the bytes without disagreeing on the document.

### Page selections

`pages` must be **strictly ascending**. A non-contiguous selection such as `[1, 3]`
is served by reading each page and joining the results — the binary has no way to
name a disjoint range — and that composition is byte-identical to a contiguous
read. The tests assert the equivalence rather than trusting it.

A reordered selection raises rather than being sorted, because the result is the
reader's own concatenation: honouring `[3, 1]` would return the file in an order
the caller did not ask for.

### What it is **not**

It does **not** replace `extract_tokens`, and the two are not interchangeable:

| | `extract_tokens` | `layout_text` |
|---|---|---|
| Returns | positioned boxes in source page coordinates | a character grid |
| Carries coordinates | yes | **no** |
| A trace can point at a pixel | yes | no |
| Preserves columns | derivable from the boxes | preserved as whitespace |
| Byte-identical to `pdftotext -layout` | no | yes |

And a caller **cannot** reproduce the reader's grid from the token boxes. Measured
on `casos/9dfc597f`: **0 of 68 lines** of a token-derived reconstruction match the
reader's own output. The reader has the font metrics and emits the soft hyphen it
broke a word on; a token box has neither. The coordinates carry the *structure* —
which column a word sits in — and they do not carry the grid.

That distinction is why both operations exist. Use `tokens` when you need
provenance; use `layout_text` when you need the text as a person reads it.

Failure paths: a page that is genuinely empty — neither text nor image — reports
`blank_page`, and a missing binary reports `engine_unavailable` rather than falling
back to another reader. A *scan* is not that case: it yields no text, but it has
pixels, so it reports `shape: "image"`.

---

## The same operations from `docflow-kernel`

The sections above drive the **library**. Six of the seven operations have a command
on the lab surface; `effective_dpi` is the one that does not, and it is reachable
anyway:

| Operation | Command | State in §9 |
|---|---|---|
| `probe` | `pdf probe <file>` | `now` |
| `classify` | `pdf classify <file> --page N` | `now` |
| `tokens` | `pdf tokens <file> --pages 1-3` | `now` |
| `layout_text` | `pdf layout <file> --pages 1-3` | `now` |
| `render` | `pdf render <file> --page N --dpi D` | `now` |
| `split` | `pdf split <file> --pages 1,2` | `now` |
| `effective_dpi` | — | **library only**; folded into `classify`'s measurements |
| — | `pdf facts <file>` | `MVP` — exits `4` |
| — | `pdf images <file>` | `MVP` — exits `4` |

`effective_dpi` is reachable from the CLI without a command of its own because
`classify` already reports it as a measurement — the number is in the envelope, under
a different name.

**`pdf layout` is the one command whose operation is not on the port.** `layout_text` is
kernel-only by `E04-02`: `plans/README.md` §3 freezes `PdfSource`'s five operations, so
a sixth would re-open `E04-01`'s gate. The adapter exposes it, and the command reaches it
there — which is how the library-only gap in this page was closed without touching the
frozen contract.

Every block below is a real invocation quoted verbatim, trimmed at `...` only where
the envelope repeats `value` inside `evidence`.

### `pdf probe <file>`

```console
$ docflow-kernel pdf probe tests/fixtures/pdf_aptos_layout/242823d2-afd3-4107-a49c-ce382592c6a5.pdf
{
  "value": {
    "terms": {
      "engine": "pymupdf", "engine_version": "1.28.2",
      "reader": "pdftotext", "reader_revision": "pdftotext version 25.02.0"
    },
    "measurements": { "page_count": 1.0 },
    "observed": {
      "file": "242823d2-afd3-4107-a49c-ce382592c6a5.pdf",
      "page_sizes": [[595.0, 842.0]],
      "producer": "GPL Ghostscript 9.52",
      "creator": "PDFCreator Free 4.4.2",
      "format": "PDF 1.4",
      "encrypted": false
    }
  },
  "evidence": { ... the same three keys ... },
  "reason": null,
  "call_record": null
}
```

Exit `0`. Two details a script will trip over if it guesses: the key is
**`page_count`**, not `pages` — there is no `pages` key, because `pages` is a
*request* grammar (`--pages`) and this is a measurement. And measurements are floats
(`1.0`), so compare against `1.0` rather than `1`.

The `terms` block names **two** pieces of software under two different keys, and that
is the split showing through: `engine`/`engine_version` is the library that reads the
bytes (`pymupdf`), `reader`/`reader_revision` is the process that supplies the text
grid (`pdftotext version 25.02.0`). `classify`'s measurements come from them
differently, and a provenance record that collapsed the two into one field could not
say which.

### `pdf classify <file> --page N`

```console
$ docflow-kernel pdf classify tests/fixtures/pdf_aptos_layout/242823d2-afd3-4107-a49c-ce382592c6a5.pdf --page 1
# value.measurements:
#   { "char_count": 1060.0, "image_count": 2.0,
#     "largest_image_fraction": 0.034754, "effective_dpi": 95.96 }
# value.observed:
#   { "file": "...", "page": 1, "page_size": [595.0, 842.0],
#     "shape": "mixed", "invisible_text": false,
#     "min_chars_applied": 40 }
# exit 0
```

The classification is `shape: "mixed"` — some text, some image — and the three
numbers that decide it are all in the envelope next to it, which is the point: the
verdict is auditable rather than asserted.

`min_chars_applied: 40` is the policy value from
`registry/policies/thresholds.json` (`reader.min_chars`), quoted into the evidence.
The threshold is **not** a constant of the surface, so a reader of the envelope can
see which value produced this `shape`.

This is also where `effective_dpi` is reachable from the CLI (`95.96` above, on a page
whose embedded image does not fill it), even though the operation that names it has
no command.

`--page` is optional and defaults to page 1; on the scan below it reports what a scan
actually is:

```console
$ docflow-kernel pdf classify tests/fixtures/pdf_escaneados/3ac5a2ec-d129-47c0-947a-4680c7e25f06.pdf --page 1
# value.observed.shape: "image"     value.observed.invisible_text: false
# value.measurements.char_count: 0.0
# exit 0
```

Zero characters and an image: `shape: "image"`, not `blank_page`. The two are not
interchangeable — `blank_page` means a page that is *genuinely empty*, neither a
usable text layer nor an image, so a scan is never blank (it has pixels). Both
`classify` and `layout_text` can report it, for the same reason and from the same
decision (`_shape_of`), which is why `classify`'s `shape` is read back rather than
re-derived: two independent tests for one fact is how they come to disagree.

### `pdf tokens <file> --pages 1-3`

```console
$ docflow-kernel pdf tokens tests/fixtures/pdf_aptos_layout/242823d2-afd3-4107-a49c-ce382592c6a5.pdf
# value is a list; the first two entries:
# {
#   "text": "FACTURA", "page": 1,
#   "bbox": { "x": 341.519863, "y": 23.964327,
#             "width": 57.49883, "height": 11.243996 },
#   "confidence": null, "role": "text"
# }
# { "text": "0138-00000236-A", "page": 1, "bbox": { ... }, ... }
# exit 0
```

`value` is a **list**, unlike `probe`/`classify` where it is an observation record:
this operation's answer is the tokens themselves. Each carries its own `page`, so a
range read is still attributable to a page.

`confidence: null` is not a missing value to be filled in — a PDF text layer has no
per-word confidence, and writing `1.0` there would invent a number the document does
not contain.

Over a range, the pages are reported per token, not grouped:

```console
$ docflow-kernel pdf tokens tests/fixtures/pdf_aptos_layout/9073693b-f8bf-4f9b-88e0-1008de266c0e.pdf --pages 1-2
# value is a list of 136 tokens
# pages present: [1, 2]
# exit 0
```

### `pdf render <file> --page N --dpi D [--save <dir>]`

```console
$ docflow-kernel pdf render tests/fixtures/pdf_aptos_layout/242823d2-afd3-4107-a49c-ce382592c6a5.pdf --page 1 --dpi 72 --save /tmp/out
# value: { "sha256": "6e739084...", "size_bytes": 77070,
#          "media_type": "image/png",
#          "path": "artifacts/6e739084af5058d68004ed5b51c3a64e8b27335d6ca64ecbcc4ecf1dee3fc75d",
#          "delivery_name": "6e739084af5058d68004ed5b51c3a64e8b27335d6ca64ecbcc4ecf1dee3fc75d.png" }
# value.measurements: { "pages_rendered": 1.0, "dpi_applied": 72.0, "bytes": 77070.0 }
# exit 0
```

The bytes are **out of band**: stdout carries the descriptor, and the image itself
goes to the store. `path` is `null` without `--save`; with it, the artifact is written
and the location reported — a path *relative to the save root*, not to your working
directory.

**`path` keeps no suffix, and the delivered copy is what carries it.** That is not an
oversight: a store is content-addressed, so the file's name *is* its identity and
`get`/`verify` have only the hash to reach it by (`FR-11`). Appending `.png` there would
give one artifact two names to look under. So `--save` writes **two files with the same
bytes**: the artifact of record, and a delivery copy whose name carries the extension a
consumer selects a reader by.

```console
$ ls /tmp/out
# 6e739084af5058d68004ed5b51c3a64e8b27335d6ca64ecbcc4ecf1dee3fc75d.png   <- delivered
# artifacts                                                              <- the store
$ file /tmp/out/*.png
# PNG image data, 595 x 842, 8-bit/color RGB, non-interlaced
```

The suffixed copy sits **directly under the save root**, and `delivery_name` in the
descriptor is its name — so the envelope tells you the file exists and what it is called,
without reading the directory. A media type this surface does not know — the
`application/octet-stream` that `store get` reads bytes back as — yields the bare digest
and **no delivery copy**, because a name nobody measured is the kind of stand-in this
code refuses everywhere else.

Now the matrix row. `kernel-cli.md` §12 row 4 is *"a 150 DPI scan rendered at 300 and
reported as 300"*, and the answer is a refusal:

```console
$ docflow-kernel pdf render tests/fixtures/pdf_escaneados/3ac5a2ec-d129-47c0-947a-4680c7e25f06.pdf --page 1 --dpi 300
# value: null
# reason.code: "insufficient_effective_resolution"
# reason.message: "page 1 holds 120.0 DPI of embedded pixels, so a 300 DPI render
#   cannot be produced from it. The requested resolution is refused rather than
#   met by enlarging ..."
# exit 2
```

**The refusal names the number it measured.** `120.0 DPI` is read from the page's own
embedded pixels, so the caller can see the comparison rather than being told *no*.
Exit `2` is the document's answer, which is why it is not a usage error: the request
was well formed and the answer is that this page cannot meet it.

The same fixture at a **reachable** DPI succeeds, which is what proves the limit is
the pixels rather than the flag. The boundary is exactly where the message says it is:

```console
$ docflow-kernel pdf render <the same scan> --page 1 --dpi 120
# value.measurements.dpi_applied: 120.0        <- reachable: exit 0

$ docflow-kernel pdf render <the same scan> --page 1 --dpi 121
# reason.code: "insufficient_effective_resolution"
# exit 2
```

`120.0` is a ceiling and not a rounding: asking for exactly what the page holds is
granted, and one more DPI is refused.

### `pdf layout <file> --pages 1-3`

The command the library-only gap used to be about. It prints the reader's own character
grid, which is a different reading from `pdf tokens` and not derivable from it: measured
on `casos/9dfc597f`, **0 of 68 lines** of a token-derived reconstruction match the
reader's output.

```console
$ docflow-kernel pdf layout tests/fixtures/pdf_aptos_layout/242823d2-afd3-4107-a49c-ce382592c6a5.pdf --pages 1
# value: "                                                              A         FACTURA 0138-00000236-A\n
#                         CODIGO        Fecha: 07/07/2026\n …"
# evidence.measurements: { "pages_read": 1.0, "characters": 3442.0, "lines": 42.0 }
# evidence.observed: { "file": "...", "pages_requested": [1],
#                      "page_separator": "\\f", "reader_flag": "-layout" }
# exit 0
```

`reader_flag: "-layout"` is the provenance: this is `pdftotext -layout`'s output, byte
for byte, and `pages_requested` says which pages produced these characters. The string
value is the text itself — no coordinates, unlike `tokens`.

A **reordered** selection is refused rather than sorted, and it is a usage error:

```console
$ docflow-kernel pdf layout <the same file> --pages 2,1
pages must be strictly ascending, got [2, 1]. The result is the reader's own
concatenation, so a reordered selection would return a document the caller did not
ask for rather than the order it asked for.
# exit 4
```

Sorting would hide the mistake, and returning the reader's page order would be a silent
substitution — so the command refuses and names the reason. Exit `4` rather than `1`
because this is the caller's text, not a defect in the build.

A page with pixels and no text layer reports `blank_page` with the measurements attached,
the same statement `classify` makes and from the same decision:

```console
$ docflow-kernel pdf layout tests/fixtures/pdf_escaneados/3ac5a2ec-d129-47c0-947a-4680c7e25f06.pdf --pages 1
# value: null
# reason.code: "blank_page"
# exit 2
```

### `pdf split <file> --pages 1,2 [--save <dir>]`

```console
$ docflow-kernel pdf split tests/fixtures/pdf_aptos_layout/9073693b-f8bf-4f9b-88e0-1008de266c0e.pdf --pages 1,2
# value: { "sha256": "...", "size_bytes": 305700,
#          "media_type": "application/pdf", "path": null,
#          "delivery_name": "<sha256>.pdf" }
# evidence.measurements: { "pages_extracted": 2.0, "bytes": 305700.0 }
# evidence.observed.pages_requested: [1, 2]
# exit 0
```

A new PDF, not a crop: `media_type` is `application/pdf` and the pages are copied
into a document of their own. `pages_requested` (what you asked for) and
`pages_extracted` (what came out) are both reported — a split that silently dropped a
page would show up as a disagreement between the two rather than as a short file.

### The `MVP` two

```console
$ docflow-kernel pdf facts <file>
pdf facts is not implemented in Stage 1 (kernel-cli.md §9 marks it `MVP`). It does
not dispatch and does not run partially.
# exit 4
```

`facts` and `images` both behave this way. §9 lists them, neither runs, and each
exits `4` naming itself — which is exit `4` on *this* message, not on `unknown flag`.
The distinction matters: an operation that has not landed stays distinguishable from
one that does not exist.

One thing worth knowing before you look for a listing: **`--list` reports kernels,
not operations.** Its eight entries carry `kernel`, `code`, `determinism`, `adapter`
and `available` — nothing per operation — and there is no `docflow-kernel pdf --list`
form (`--list takes no other argument`, exit `4`). So there is no discovery command
for an operation's status: §9's tables are the authority, `lab-cli.md` enumerates the
nine `MVP` commands, and an `MVP` operation announces itself when you run it. Exit `4`
with *"is not implemented in Stage 1"* means **not yet**; exit `4` with *"unknown
kernel"* would mean **no such thing**.

### The exit codes, and one that is wrong

| Exit | Meaning | Where K2 produces it |
|---|---|---|
| `0` | A value was produced | all five commands above, including `classify` on a scan |
| `2` | The document's answer | `insufficient_effective_resolution`; `blank_page`; `encrypted`; `unsupported_format`; `engine_unavailable` |
| `4` | Usage: bad flag, `MVP`, missing argument, malformed range | `pdf facts`; `pdf probe` with no file argument (`pdf probe needs the file argument`) |

A page range that names a page outside the document is exit `4`, per §5's
*"malformed range"*:

```console
$ docflow-kernel pdf split <a 2-page pdf> --pages 9
page(s) [9] are outside the document, which has 2 page(s).
# exit 4
```

The same holds for K3's out-of-image region and K4's page range, so a caller matching
on exit codes can treat `4` alike for all three: the request was malformed and the
caller can restate it. **This was a real defect** — the parsers raised a plain
`ValueError`, the dispatcher's catch-all turned it into exit `1`, and the exit table's
distinction between *"a malformed range"* and *"a bug"* was erased for those three
cases. The surface now raises `UsageError`, and `_invoke` catches it before the
catch-all so it reaches `4`.
a bad range.

---

## The split, and what it buys

`kernels/pdf.py` used to call `pymupdf` and the `pdftotext` binary itself. `sad.md` §1
lists ``pdftotext`` among the **adapters**, so a vendor was living inside a kernel —
and a pass-through shim would have satisfied the criterion while changing nothing.

Measured on the split:

| | before | after |
|---|--:|--:|
| `kernels/pdf.py` | 1689 lines | 983 |
| vendor modules it imports | `pymupdf`, `subprocess`, `shutil`, `tempfile`, `xml.etree` | **none** |
| `adapters/pdf.py` | did not exist | 947 lines |
| the seam | did not exist | 363 lines |

**What it buys, concretely.** The analysis — which shape a page has, whether its text
is invisible, whether a producer contradicts its measurements — is now testable with a
stub reader and no PDF library installed. And a different PDF library becomes possible
without touching a single judgement: implement `PdfVendor` and pass it in.

**What it does not buy.** It does not make the analysis *pure*: the shapes are still
decided from measurements a vendor took, so a vendor that measures wrongly still
misleads it. The split buys *replaceability and testability*, not correctness.

**Verified by mutation.** Twelve mutations of the kernel and the adapter each break one
guarded property and each fail the test that guards it — including three that exist
because of this split: a missing reader must not fall back to a substitute; a missing
reader must not be reported as a successful empty extraction; and the `min_chars`
threshold must not be defaulted. Harness: `tests/adapters/mutation_pdf.py`.

---

## Reading a result

Every call has the same shape, and the two legal states are the whole of it:

```python
if result.reason is None:
    use(result.value, result.evidence)      # a value, with what was observed
else:
    match result.reason.code:               # no value, and why
        case "insufficient_effective_resolution": ...
        case "blank_page": ...
        case "engine_unavailable": ...
```

The codes this kernel can raise, all from the closed set of `kernel-cli.md` §5:

| Code | What it means |
|---|---|
| `insufficient_effective_resolution` | The requested DPI exceeds the embedded pixels; nothing was produced |
| `blank_page` | The page carries neither usable text nor image — from `classify` and `layout_text`, both reading the one `_shape_of` decision |
| `encrypted` | Refuses to open without a password |
| `unsupported_format` | Not a PDF this engine accepts; also the "does not exist" case |
| `engine_unavailable` | PyMuPDF or the `pdftotext` binary is missing |

For `probe`, `classify` and `effective_dpi` the value **is** the observation
record, and `result.evidence` is the same object — every call reports what it
observed, and for these three that report is the answer.

Three things are refused as **usage errors** rather than answered, because they are
mistakes in the request rather than answers about the document: a page number outside
the document, an empty page selection, and a non-positive DPI.

**From a shell those three reach you as exit `4`**, the exit §5 assigns to a malformed
range — see the exit-code table in the CLI section above. It is a property of the
dispatcher rather than of this kernel, and `image crop`'s out-of-image region now
exits `4` the same way.

## Verifying it against the fixture set

```bash
python tests/fixtures/verify_k2.py          # human-readable
python tests/fixtures/verify_k2.py --json   # machine-readable
```

Three passes over the 22 PDFs in `tests/fixtures/`: `classify` versus the
manifest's independently-produced labels, `render` refusing on every scan, and a
search for real invisible text layers. Exits non-zero on a defect.

## What K2 does *not* do yet

| Not available | Where it lands |
|---|---|
| `docflow-kernel pdf probe  classify  tokens  render  split` | **Now available** — see the CLI section above and `lab-cli.md`. The `MVP` operations of §9 still exit `4` |
| `effective_dpi` as a command of its own | **No command** — but the number is reachable from `classify`'s measurements, so nothing is blocked on it |
| `layout_text` from the CLI | **Now available** as `pdf layout <file> --pages …`; kernel-only, so it is not on `PdfSource` |
| Page facts beyond classification | `# TODO: [MVP]` — documented target, not Stage 1 scope |
| Embedded-image extraction, `merge` | `# TODO: [MVP]`; merge is **Never**, no pipeline closes it |
| A second reader, an engine setting | **Never** — `ADR-001`, `wbs.md` §9 |
| Any threshold of its own | **Never** — every threshold is the caller's (`prd.md` FR-15) |

## The other seven kernels

| Kernel | State |
|---|---|
| K3 `image` | **Landed** — `info`, `legibility`, `crop`, `rescale` (`E04-03`) |
| K4 `kernel.ocr` | **Landed** — Docling behind `OcrEngine` (`E04-04`) |
| K5 `kernel.llm.local` | **Landed** — Ollama behind `LlmEngine` (`E04-05`) |
| K6 `kernel.llm.frontier` | **Landed** — one provider behind `LlmEngine` (`E04-06`) |
| K7 `store` | **Landed** — content-addressed put/get/verify + the ledger write path |
| K8 `registry` | **Landed** — load, schema-validate, fail fast, `registry_hash` |
| K1 `orchestrator` | **Landed** — the closing flow |

Seven of the eight can serve a call in this workspace. **K6 is the exception among the
landed ones**: its adapter exists, but its probe also requires a provider key and this
workspace has none, so `docflow-kernel --list` correctly reports it unavailable —
*available* would be a claim that a paid call could be made.
