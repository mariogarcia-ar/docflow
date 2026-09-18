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

Failure paths: a page that yields no text reports `blank_page` (that is what a scan
looks like — pixels, not a text layer), and a missing binary reports
`engine_unavailable` rather than falling back to another reader.

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
| `blank_page` | The page carries neither text nor image; from `layout_text`, the requested pages yielded no text at all |
| `encrypted` | Refuses to open without a password |
| `unsupported_format` | Not a PDF this engine accepts; also the "does not exist" case |
| `engine_unavailable` | PyMuPDF or the `pdftotext` binary is missing |

For `probe`, `classify` and `effective_dpi` the value **is** the observation
record, and `result.evidence` is the same object — every call reports what it
observed, and for these three that report is the answer.

Three things raise `ValueError` instead, because they are mistakes in the request
rather than answers about the document: a page number outside the document, an
empty page selection, and a non-positive DPI.

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
| `docflow-kernel pdf probe  classify  tokens  render  split` | **Now available** — see `lab-cli.md`. The `MVP` operations of §9 still exit `4` |
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
