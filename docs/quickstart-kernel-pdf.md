# Quickstart — what K2 (`kernel.pdf`) can do today

**Status: honest, and partial.** Three of the eight kernels have landed; this page
covers the PDF one, which is the most complete. Everything below has been run and
its output is quoted from a real invocation.

There is **no command line for kernels yet** (`S1-T20`/`S1-T21` build
`docflow-kernel`). Everything here is the **library**, called from Python. That is
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

Both are resolved lazily. A missing one is a typed `Reason` with a remedy in the
message — never a substitute engine, because a different engine reading the same
bytes is a different measurement wearing this one's name.

## The whole surface

Six module-level functions in `docflow.kernels.pdf`. All six return
`KernelResult`, which has exactly two states: a value with evidence, or no value
with a `Reason`. There is no third state and no exception for an expected negative
outcome.

```python
from pathlib import Path
from docflow.kernels import pdf
```

## 1. `probe` — what is this file?

```python
result = pdf.probe(Path("documento.pdf"))
result.value.observed
# {'file': 'documento.pdf', 'page_sizes': [[612.0, 792.0]], 'producer': '...',
#  'creator': '...', 'format': 'PDF 1.7', 'encrypted': False}
```

Page count, page sizes, declared metadata, encryption state. An unopenable file
returns `unsupported_format` or `encrypted` — **never** an empty observation set
standing in for a successful probe.

## 2. `classify` — what shape is this page?

**`min_chars` is required.** It is the caller's threshold, not the kernel's: what
counts as enough text to judge is a policy value (`prd.md` FR-15), and a kernel
holding its own constant has made a routing decision whether or not it prints one.

```python
result = pdf.classify(Path("documento.pdf"), page=1, min_chars=40)
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
result = pdf.effective_dpi(Path("escaneo.pdf"), page=1)
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
result = pdf.render(Path("escaneo.pdf"), pages=[1], dpi=600)
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

## 5. `extract_tokens` — positioned words from the text layer

Read by the `pdftotext` binary in its `-bbox` mode, converted to **source page
coordinates at the DPI you asked for** — so a token's box means the same thing as
the box `render` produces.

```python
result = pdf.extract_tokens(Path("documento.pdf"), pages=[1], dpi=300)
[(t.text, round(t.bbox.x, 1), round(t.bbox.width, 1), t.confidence) for t in result.value][:2]
# [('FACTURA', 1423.0, 239.6, None), ('0138-00000236-A', 1703.0, 405.1, None)]
```

**`confidence` is always `None`.** A text layer is not a recogniser and reports no
confidence at all; `None` is never coerced to `1.0`, because a perfect score would
be a claim nobody made.

Boxes scale with the requested DPI, so the same word at 144 DPI has a box twice
the size of the one at 72:

```python
at_72  = pdf.extract_tokens(path, [1], dpi=72).value[0].bbox.x
at_144 = pdf.extract_tokens(path, [1], dpi=144).value[0].bbox.x
round(at_144 / at_72, 2)   # 2.0
```

## 6. `split` — cut a page range out as a new document

```python
result = pdf.split(Path("documento.pdf"), pages=[1])
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
| `blank_page` | The page carries neither text nor image |
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
| `docflow-kernel pdf ...` as a command | `S1-T20`/`S1-T21` — no kernel has a CLI yet |
| Page facts beyond classification | `# TODO: [MVP]` — documented target, not Stage 1 scope |
| Embedded-image extraction, `merge` | `# TODO: [MVP]`; merge is **Never**, no pipeline closes it |
| A second reader, an engine setting | **Never** — `ADR-001`, `wbs.md` §9 |
| Any threshold of its own | **Never** — every threshold is the caller's (`prd.md` FR-15) |

## The other seven kernels

| Kernel | State |
|---|---|
| K7 `store` | **Landed** — content-addressed put/get/verify + the ledger write path |
| K8 `registry` | **Landed** — load, schema-validate, fail fast, `registry_hash` |
| K3 `image` | Not yet (`E04-03`) |
| K4 `ocr`, K5 `llm.local`, K6 `llm.frontier` | Not yet (`E04-04` … `E04-06`) |
| K1 `orchestrator` | Not yet (`E05`) |
