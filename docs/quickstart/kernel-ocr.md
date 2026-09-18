# Quickstart — what K4 (`kernel.ocr`) can do today

**Status: honest, and partial.** Five of the eight kernels have landed; this page
covers the OCR one. Everything below has been run and its output is quoted from a
real invocation.

`docflow-kernel` now dispatches this kernel's operations — see `lab-cli.md` for the
bench. This page drives the **library**, called from Python, which is where the
detail lives. That is
the intended shape: `sad.md` ADR-008 makes the library first and the CLI one caller
of it.

---

## Setup

```bash
pip install -e ".[dev]"      # pytest, ruff, pylint
pip install docling          # the OCR engine
```

Docling is resolved lazily and is **not** a declared dependency yet
(`pyproject.toml` has `dependencies = []` until the adapters are tallied). A missing
one is a typed `Reason` — never a substitute engine, because `ADR-001` fixes the
engine and a second one would be a matrix of behaviours under one name.

## Where K4's code lives

K4 is a **kernel** — it has its own row in `sad.md` §3, its determinism class
(`sampled`) and its resource slot (`gpu`). Its code sits in two files rather than in
`kernels/`:

| File | What it holds | Landed by |
|---|---|---|
| `docflow/ports/ocr.py` | the `OcrEngine` interface, `ReadResult`, `PageStatus` | `E04-01` (`S1-T11`) |
| `docflow/adapters/docling.py` | the engine itself, behind the port | `E04-04` (`S1-T14`) |

That split is the architecture, not an accident: K2 and K3 live in `kernels/`
because their engines are not behind a swap-able vendor boundary, while K4, K5 and
K6 live in `adapters/` because theirs are. The dependency arrow still points down —
the port is imported by the adapter, never the reverse.

```python
from pathlib import Path
from docflow.adapters.docling import DoclingEngine
from docflow.ports import OcrEngine, PageStatus

engine = DoclingEngine()
isinstance(engine, OcrEngine)      # True
```

## The whole surface

Three operations, all returning `KernelResult` — a value with evidence, or no value
with a `Reason`.

| Operation | Question it answers |
|---|---|
| `capabilities` | What can this engine do? |
| `engine_info` | Which revision answered, for the cache key? |
| `read` | Give me the text on these pages, with positions |

## 1. `capabilities` — what can this engine do?

```python
result = engine.capabilities()
result.value.observed
# {'engine': 'docling', 'ocr_engine': 'rapidocr-onnxruntime', 'granularity': 'block',
#  'reports_confidence': False,
#  'accepts_image_suffixes': ['.bmp', '.jpeg', '.jpg', '.png', '.tif', '.tiff', '.webp']}
```

Two of those fields exist to stop a caller assuming something that is not true:

- **`reports_confidence: False`** — see §3. The engine produces no confidence at
  all, so a caller must not plan around one.
- **`granularity: 'block'`** — see §4. Docling reports one item per text *block*,
  not per word.

## 2. `engine_info` — which revision answered?

```python
result = engine.engine_info()
result.value.observed
# {'engine': 'docling', 'engine_version': '2.126.0'}
result.value.terms
# {'engine': 'docling', 'engine_version': '2.126.0'}
```

`terms` is the part that matters: those two strings feed the **cache key**
(`sad.md` §5). A different engine build reading the same bytes is different work,
and without this term a stage would be marked `done` while no longer being correct.

## 3. `read` — the text, with positions

```python
result = engine.read(Path("legible.png"), pages=[1], dpi=72, lang="es")
result.value.tokens
# (Token(text='FACTURA TOTAL 15400.00', page=1,
#        bbox=Box(x=37.0, y=117.0, width=127.7, height=16.7),
#        confidence=None, role='text'),)
```

### `confidence` is always `None`, and that is a fact about the engine

Docling's document model has **no confidence field anywhere** — `ProvenanceItem`
carries `bbox`, `charspan` and `page_no` and nothing else. So the adapter does not
have a missing value it declines to coerce; there is no such value to begin with.

`None` is still the right value rather than `1.0` or `0.0`: `1.0` would be a claim of
perfect confidence nobody made, and `0.0` a claim of total failure. The absence is
the honest answer, and `capabilities` says so up front.

### The boxes are in source page coordinates, at the DPI you asked for

Two conversions happen at the boundary, and both matter to anyone comparing a token's
box against a rendered page:

| Conversion | Why |
|---|---|
| **Origin flips** | Docling reports boxes with a **bottom-left** origin, where `t` is the *greater* y. Source page coordinates grow downward from the top |
| **Units scale** | The engine reports points at 72 DPI; the box you receive is at the resolution you requested (`dpi / 72`) |

The flip needs the page's height, which the box does not carry. It comes from
`document.pages[n].size.height` — and if a page's height cannot be read, the box is
**dropped rather than guessed**. A coordinate derived from a guess is worse than a
missing one, because it looks precise.

Measured on the fixture above: the engine reports `t=183` on a 300-point page, and
the token's `y` comes back as **117.0** (`300 − 183`). Deriving the height from the
box instead (`t + b`) gives `349.3` — wrong, and it was measured before this
function was written.

### Per-page status, and what it distinguishes

```python
result.value.page_status          # {1: <PageStatus.READ: 'read'>}
result.value.pages_requested      # (1,)
result.value.pages_read           # (1,)   <- derived from the statuses
```

| Status | Means |
|---|---|
| `read` | The engine read the page. The item list may legitimately be empty |
| `blank` | The engine produced nothing for this page |
| `unreadable` | **Never produced by this adapter** — see below |

**`blank` is a statement, not an absence.** A white page reports `blank`, never
`read` with an invented item list — which is what makes *the engine read this page
and it held nothing* distinguishable from *the engine could not read it*.

```python
blank = engine.read(Path("blanca.png"), pages=[1], dpi=72, lang="es")
blank.value.page_status[1] is PageStatus.BLANK     # True
blank.value.tokens                                 # ()
```

**`unreadable` is declared by the port and not produced here.** Docling reports on
the *document*, not per page: a page it cannot read fails the whole conversion,
which the adapter reports as one typed `Reason` for the call rather than as a status
on a page that was never separately assessed. The status exists in the vocabulary
because the port must be able to express it; this engine cannot.

### `pages_requested` vs `pages_read`

Both are reported, so a difference between them is visible rather than inferred:

```python
result.value.pages_requested          # (1, 2, 3)
result.value.pages_read               # (1, 2, 3)
result.evidence.observed["pages_read"]  # [1, 2, 3]
```

`pages_read` is **derived** from `page_status`, so the accounting cannot drift from
what the engine actually reported.

## 4. The limitation a caller will meet

**Docling reports one item per text *block*, not one per word.** The line above came
back as a single token whose text spans the whole line and whose box covers it.

The adapter returns the engine's actual granularity rather than splitting blocks on
whitespace to look finer. Splitting would give every word in a line **the line's
box** — a position no one measured, attached to a word no one located. A fabricated
position is worse than a coarse one, because it survives review.

The evidence says so at the boundary instead of leaving it to be inferred:

```python
result.evidence.observed["granularity"]      # 'block'
result.evidence.observed["layout_dropped"]   # True
result.evidence.observed["reading_order"]    # 'not_resolved'
```

## 5. What the boundary deliberately drops

Docling returns a full document model — sections, reading order, item nesting, table
structure, layout regions. **None of it leaves the adapter.** What leaves is text
with a box and the engine's label as the token's `role`.

An order resolved here would be a domain-level interpretation performed by a kernel,
and ordering is the Reconstructor's job at Stage 2 (`S2-T07`). The engine's own item
order is preserved exactly as produced and never re-sorted: imposing an order is a
decision, and this is not the layer that takes it.

---

## Reading a result

```python
if result.reason is None:
    use(result.value, result.evidence)
else:
    match result.reason.code:
        case "engine_unavailable": ...
        case "unsupported_format": ...
```

| Code | What it means |
|---|---|
| `engine_unavailable` | Docling is not installed, or its converter could not be started |
| `unsupported_format` | The file is absent, or the engine could not read it |

Three things raise `ValueError` instead, because they are mistakes in the request
rather than answers about the document: an empty page selection, a page outside the
document, and a non-positive DPI.

## There is no engine setting

`ADR-001` and `prd.md` FR-16: the engine is Docling and **only** Docling. There is no
`engine` parameter, no environment variable, and no `--engine` flag anywhere — a
per-corpus choice would make the OCR path a matrix of behaviours and put a second
adapter revision into the cache key for nothing.

The constructor takes an `engine=` argument, and it is worth being precise about
what that is: an **injected converter**, so tests can exercise the boundary without
the engine's model downloads. It is not a setting — passing one does not select a
different engine, it supplies a different instance of the same one.

## What K4 does *not* do yet

| Not available | Where it lands |
|---|---|
| `docflow-kernel ocr capabilities  engine-info  read` | **Now available** — see `lab-cli.md`. The `MVP` operations of §9 still exit `4` |
| Word-level granularity | Not available from this engine; see §4 |
| An OCR correction pass | `# TODO: [MVP]` — `--correct` gates the corrected artifact only, and the raw tokens are always retained |
| A second engine, an engine setting | **Never** (`ADR-001`, `prd.md` FR-16) |
| Reading order, layout, table structure | **Never** at this boundary (`S2-T07` owns ordering) |
| A confidence score or an aggregate | **Never** — the engine reports none, and `kernel-cli.md` §3 forbids aggregating measurements here |
| Per-page `unreadable` | Not producible by this engine; see §3 |

## The other seven kernels

| Kernel | State |
|---|---|
| K2 `pdf` | **Landed** — see `kernel-pdf.md` |
| K3 `image` | **Landed** — see `kernel-image.md` |
| K7 `store` | **Landed** — content-addressed put/get/verify + the ledger write path |
| K8 `registry` | **Landed** — load, schema-validate, fail fast, `registry_hash` |
| K5 `llm.local`, K6 `llm.frontier` | Not yet (`E04-05`, `E04-06`) |
| K1 `orchestrator` | **Landed** — the closing flow |
