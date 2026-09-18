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

## The same operations from `docflow-kernel`

All three operations have a command, and all three are `now` in §9 — so unlike K2 and
K3 there is no gap between the library surface and the bench here:

| Operation | Command | Flags |
|---|---|---|
| `capabilities` | `ocr capabilities` | — |
| `engine_info` | `ocr engine-info` | — |
| `read` | `ocr read <file>` | `--pages`, `--dpi`, `--lang`, `--correct` |

Every block below is a real invocation with its output quoted verbatim, trimmed at
`...` only where the envelope repeats `value` inside `evidence`.

Two things about running these that a caller will meet immediately:
`ocr engine-info`/`capabilities` are instant, while `ocr read` **loads ONNX models and
takes ~11 s on the first call** in this workspace. And the engine logs to **stderr**,
so stdout stays a single parseable JSON document — `docflow-kernel ocr read f.png | jq`
works, and the *"[INFO] RapidOCR ..."* lines do not corrupt it.

### `ocr capabilities`

```console
$ docflow-kernel ocr capabilities
{
  "value": {
    "terms": { "engine": "docling", "engine_version": "2.126.0" },
    "measurements": {},
    "observed": {
      "engine": "docling",
      "ocr_engine": "rapidocr-onnxruntime",
      "granularity": "block",
      "reports_confidence": false,
      "accepts_image_suffixes": [".bmp", ".jpeg", ".jpg", ".png",
                                 ".tif", ".tiff", ".webp"]
    }
  },
  "evidence": { ... the same three keys ... },
  "reason": null,
  "call_record": null
}
```

Exit `0`, and **no positional and no flag** — this command takes no arguments at all.
Note `measurements: {}` is empty rather than omitted: a call made nothing *measured*,
and an empty mapping says that without inventing a number.

`reports_confidence: false` is the field worth querying first if you are building a
threshold on confidence — §3 explains why it is always `false` here, and this is the
command that tells you before you write the code rather than after.

### `ocr engine-info`

```console
$ docflow-kernel ocr engine-info
# value.terms:    { "engine": "docling", "engine_version": "2.126.0" }
# value.observed: { "engine": "docling", "engine_version": "2.126.0" }
# exit 0
```

`terms` and `observed` carry the same two strings here, and that repetition is
deliberate: `terms` is the half that feeds the **cache key** (`sad.md` §5), so a
change of engine build re-runs a stage instead of leaving it `done` and wrong.

### `ocr read <file>`

```console
$ docflow-kernel ocr read tests/fixtures/expected-extraction/dbc07b17-2538-4611-9e51-7e161aaf7ba5.jpg --pages 1
# value.pages_requested: [1]
# value.pages_read:      [1]
# value.page_status:     { "1": "read" }
# value.tokens:          54 tokens; the first is
#   { "text": "ción 124", "page": 1,
#     "bbox": { "x": 0.0, "y": 5.216733932495117,
#               "width": 109.5018310546875, "height": 22.431955337524414 },
#     "confidence": null, "role": "text" }
# exit 0
```

Four keys, and each answers a matrix row. `page_status` is a **mapping** and its keys
are strings (`"1"`, not `1`) because a JSON object's keys are strings — the per-page
status survives the door rather than being flattened into a list. `confidence` stays
`null` (§3), and `text` is the engine's own block, not a word.

`--pages` is optional and defaults to page 1; `--dpi` defaults to 72 and sets the
**units of every `bbox`** (`dpi / 72`), so a box compared against a differently-rendered
page will not line up unless you pass the same `--dpi`.

`--lang` defaults to `en`; it is a *hint* to the recogniser, not a filter — passing
`es` does not restrict output to Spanish.

A file that is not there is a typed refusal rather than a crash:

```console
$ docflow-kernel ocr read /tmp/nope.png
# reason.code: "unsupported_format"
# reason.message: "'nope.png' does not exist at /tmp/nope.png"
# exit 2
```

### `--correct` is declared and refuses

```console
$ docflow-kernel ocr read <file> --correct true
# value: null
# reason.code: "engine_unavailable"
# reason.message: "--correct is declared but not implemented in Stage 1: it gates
#   the corrected artifact, which needs `reader.correct` from the registry
#   (ADR-009) and a second output the engine does not produce yet. Refusing rather
#   than returning uncorrected tokens as if they were corrected."
# exit 3
```

Exit **3**, not `2`: the call could not legitimately be made, because the command
refuses rather than answering with something it cannot produce. Silently returning the
uncorrected tokens would be the failure this refusal exists to prevent — the two are
indistinguishable in the result.

`--correct` is a **value** flag, not a boolean one, so the bare form is a usage error
rather than a synonym for `true`:

```console
$ docflow-kernel ocr read <file> --correct
--correct requires a value
# exit 4
```

### The exit codes, in one table

| Exit | Meaning | Where K4 produces it |
|---|---|---|
| `0` | A value was produced | all three commands, including `read` on a blank page |
| `2` | The document's answer | `unsupported_format` — the file is absent or unreadable; `engine_unavailable` when Docling itself is missing |
| `3` | The call could not legitimately be made | `--correct true` |
| `4` | Usage: bad flag, missing argument, `--correct` with no value | `ocr read` with no file (`ocr read needs the file argument`) |

Confidence is `float | null` and `null` is **never** reported as `1.0` — that is row 10
of `kernel-cli.md` §12, and it is visible in every token above.

### Running all five at once

`scripts/kernel/kernel-ocr.sh` drives the whole surface — the three commands plus the
two shapes of the `--correct` gate — against one raster:

```console
$ scripts/kernel/kernel-ocr.sh

image: tests/fixtures/matrix/page.png

  selection        engine default  (no --pages, --dpi or --lang given)

K4 - the engine
  capabilities               exit 0  observed: accepts_image_suffixes, engine, ...
  engine-info                exit 0  observed: engine, engine_version

K4 - reading
  (the first read loads ONNX models: ~10s)
  read                       exit 0  observed: dpi_applied, file, granularity, ...

K4 - the correction gate
  read --correct (bare)      exit 4  --correct requires a value
  read --correct true        exit 3  reason engine_unavailable
```

**The parameters are listed only when they were given.** `--pages`, `--dpi` and
`--lang` reach the `read` call when you pass them and are **absent** from the
invocation when you do not, so an unset one prints nothing rather than printing an
empty value — and the single `selection` line above is what a run with none of the
three looks like:

The image is a parameter and defaults to a committed fixture; `--pages`, `--dpi` and
`--lang` reach the `read` call when you give them, and are **absent** rather than
empty when you do not.

**The first `read` takes about ten seconds** while ONNX loads the models, and nothing
after it does. One caution measured in practice: running several of these drivers
*at once* makes that call abort with `SIGABRT` (exit `134`) — memory contention while
the models load, not a defect in the surface. Eight consecutive runs with nothing else
in flight all exit `0`, so if you see `134` here, run it alone before suspecting the
build.

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

Three things are refused as **usage errors** rather than answered, because they are
mistakes in the request rather than answers about the document: an empty page
selection, a page outside the document, and a non-positive DPI.

**From a shell those three reach you as exit `4`**, the exit §5 assigns to a malformed
range — see the exit-code table in the CLI section above. The same holds for
`pdf split --pages 9` and `image crop`'s out-of-image region. A caller matching on
exit codes can treat `4` alike for all three: the request was malformed and can be
restated. **This was a real defect** — the parsers raised a plain `ValueError`, the
dispatcher's catch-all turned it into exit `1`, and a caller's typo read as a broken
build. The surface now raises `UsageError`, which the dispatcher catches ahead of the
catch-all.

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
| `docflow-kernel ocr capabilities  engine-info  read` | **Now available** — see the CLI section above and `lab-cli.md` |
| `--correct true` | **Declared, refused today** — exit `3`, because the corrected artifact needs `reader.correct` from the registry and a second engine output |
| Word-level granularity | Not available from this engine; see §4 |
| An OCR correction pass | `# TODO: [MVP]` — `--correct` gates the corrected artifact only, and the raw tokens are always retained |
| A second engine, an engine setting | **Never** (`ADR-001`, `prd.md` FR-16) |
| Reading order, layout, table structure | **Never** at this boundary (`S2-T07` owns ordering) |
| A confidence score or an aggregate | **Never** — the engine reports none, and `kernel-cli.md` §3 forbids aggregating measurements here |
| Per-page `unreadable` | Not producible by this engine; see §3 |

## The other seven kernels

| Kernel | State |
|---|---|
| K1 `orchestrator` | **Landed** — the closing flow |
| K2 `pdf` | **Landed** — see `kernel-pdf.md` |
| K3 `image` | **Landed** — see `kernel-image.md` |
| K5 `kernel.llm.local` | **Landed** — Ollama behind `LlmEngine` (`E04-05`) |
| K6 `kernel.llm.frontier` | **Landed, but unreachable here** — its probe needs a provider key this workspace does not have, so `--list` reports it unavailable |
| K7 `store` | **Landed** — content-addressed put/get/verify + the ledger write path |
| K8 `registry` | **Landed** — load, schema-validate, fail fast, `registry_hash` |

Seven of the eight can serve a call in this workspace. **K6 is the exception**: its
adapter exists, but its probe also requires a provider key, and *available* would be a
claim that a paid call could be made.
