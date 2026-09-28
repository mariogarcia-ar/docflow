# Quickstart — the lab tools

The commands you actually type, one section per processor: first over **one file**, then the same
command over **a folder**. [`readme.md`](readme.md) is the full reference — every flag, every
payload key, the boundary rules and the known limitations. This page is the short way in.

Nine tools, two modes. Each processor's two tools call the **same** methods, so a subcommand
behaves the same way in both and the batch adds a folder, a mirror and a summary — never a second
implementation.

| Processor | One file | A folder |
|---|---|---|
| PDF | `pdf.py` | `batch_pdf.py` |
| Image | `image.py` | `batch_image.py` |
| OCR | `ocr.py` | `batch_ocr.py` |
| LLM / VLM | `llm.py` | `batch_llm.py` |
| Workflow (orchestrator) | `workflow.py` | — no folder twin: a document request is not a folder of files |

## Before you start

- **No install.** Every tool is invoked **by path**; it puts the repository root and `src/` on
  `sys.path` itself.
- **Global flags go before the subcommand; the subcommand's flags go after it.** The input
  positional belongs to the subcommand. `--json` is the one that catches people:

  ```bash
  python scripts/tools/pdf.py --json render tests/fixtures/pdf/pdf_sample_mixed.pdf --page 1 --dpi 200
  python scripts/tools/pdf.py render tests/fixtures/pdf/pdf_sample_mixed.pdf --page 1 --dpi 200 --json
  ```

  The first line runs; the second is a usage error (`2`), because `--json` is global and the
  subparser does not know it. The same holds for `--out`, `--fixture` and `--run-id`.
- **Fixtures.** `tests/fixtures/` is the root, plus `tests/fixtures-txt/` for text inputs.
  `--fixture NAME` resolves a bare name at any depth, so `--fixture pdf_sample_mixed.pdf` finds
  `tests/fixtures/pdf/pdf_sample_mixed.pdf`. A name that matches two files is refused, never
  guessed.
- **Output.** One file writes under `var/tools/<tool>/<stem>-<hash8>/`; a folder writes under
  `var/batch_<processor>/<folder>/…`, mirroring the tree it walked. A subcommand whose report *is*
  the stdout summary writes no file and says so in its header.
- **Exit codes.** `0` the run produced a result (`partial` and `PAUSED` are results); `1` the
  library returned a typed failure — printed as a record, never a traceback; `2` a usage error.
- **`--json`** prints the machine-readable payload on stdout; the run header always goes to stderr,
  so the payload stays clean.

Every tool and every subcommand answers `--help`.

---

## PDF — `pdf.py` · `batch_pdf.py`

Inputs: `.pdf`. Code says `—` where a subcommand needs no flag.

| Subcommand | Needs | What it gives you |
|---|---|---|
| `inspect` | — | page count, per-page geometry, engine report |
| `split` | — | one self-contained PDF per page |
| `render` | `--page` `--dpi` | one page as a PNG |
| `text` | `--page` | the page's native text |
| `blocks` | `--page` | the same read, block view (reading order, boxes) |
| `images` | `--page` | the page's embedded images |
| `classify` | `--page` | metrics plus the `TEXT` / `IMAGE` / `MIXED` verdict |
| `run` | `--dpi` | the processor's contract; `--page` switches to the page-level one |

### One file

```bash
python scripts/tools/pdf.py inspect tests/fixtures/pdf/pdf_sample_mixed.pdf
python scripts/tools/pdf.py --json classify tests/fixtures/pdf/pdf_sample_mixed.pdf --page 1
python scripts/tools/pdf.py render tests/fixtures/pdf/pdf_sample_text.pdf --page 1 --dpi 200
python scripts/tools/pdf.py run tests/fixtures/pdf/pdf_sample_text.pdf \
    --dpi 200 --extract-text --extract-images
```

`inspect`, `text` and `blocks` publish nothing: their report is the stdout summary.

### A folder

```bash
python scripts/tools/batch_pdf.py tests/fixtures/pdf              # inspect — the default command
python scripts/tools/batch_pdf.py tests/fixtures/pdf classify --page 1
python scripts/tools/batch_pdf.py --no-recursive --out var/x tests/fixtures/matrix split
```

With no subcommand the run makes `inspect` and says so in its header
(`command: inspect (default, none stated)`). `tests/fixtures/pdf` is four inputs, three written and
one the corrupt sample: `files: 4 · succeeded: 3 · failed: 1`, exit `1`.

**Reading `classify`.** Poppler reports no placement for an embedded image, so
`image_coverage` and `largest_image_coverage` stay `0.0` and the verdict rests on the native text
layer alone. A scanned page carrying a hidden OCR layer therefore reads `TEXT`, not `IMAGE` —
the `MIXED` branch cannot fire until a reader that reports image placement is behind the seam.

---

## Image — `image.py` · `batch_image.py`

Inputs: `.png` `.jpg` `.jpeg` `.tif` `.tiff` `.bmp`. No subcommand requires a flag.

| Subcommand | Needs | What it gives you |
|---|---|---|
| `info` | — | file and pixel facts, read without measuring quality |
| `metrics` | — | quality, orientation, skew, regions |
| `normalize` | — | writes `normalized.png` |
| `ocr-ready` | — | writes `ocr_ready.png`, through its own pipeline |
| `vlm-ready` | — | writes `vlm_ready.png`, colour and layout preserved |
| `classify` | — | the technical classification, over the metrics above |
| `run` | — | the processor's contract |

`normalize`, `ocr-ready`, `vlm-ready` and `run` accept `--correct-orientation` and `--deskew`; no
correction is ever applied because a measurement suggested it and nobody asked. `run` additionally
takes `--from-page`, `--page` (default `1`), `--normalize`, `--prepare-for-ocr` and
`--prepare-for-vlm`.

### One file

```bash
python scripts/tools/image.py info tests/fixtures/image/color_layout.png
python scripts/tools/image.py --json metrics tests/fixtures/image/skewed_text.png
python scripts/tools/image.py classify tests/fixtures/image/color_layout.png
python scripts/tools/image.py normalize tests/fixtures/image/skewed_text.png --deskew
python scripts/tools/image.py run tests/fixtures/image/color_layout.png \
    --normalize --prepare-for-ocr
```

`info`, `metrics` and `classify` publish nothing.

### A folder

```bash
python scripts/tools/batch_image.py tests/fixtures/image              # info — the default command
python scripts/tools/batch_image.py tests/fixtures/image classify
```

**Known limitation.** With the real engine, no image artifact can be published: atomic publication
writes through a `.tmp` sibling and OpenCV infers its encoder from the extension, so it refuses
that name. The run reports a typed `WRITE_ERROR` and exits `1` — per input in a batch, so the rest
of the corpus still runs. That is a processor defect, registered in
[`docs/plan/bitacora.md`](../../docs/plan/bitacora.md).

---

## OCR — `ocr.py` · `batch_ocr.py`

Inputs: the image set — the OCR input *is* an image. No subcommand requires a flag, and there is
no `--engine` flag: the engine is fixed.

**Every** subcommand takes the same options: `--ocr` / `--no-ocr` (on by default, because OCR is
the processor's purpose), `--layout`, `--tables`, `--reading-order`, `--language` and a repeatable
`--engine-option KEY=VALUE`.

| Subcommand | Needs | What it gives you |
|---|---|---|
| `text` | — | the extraction's plain text |
| `md` | — | the extraction's Markdown |
| `json` | — | the structured document, serialized |
| `tables` | — | detected tables, in reading order |
| `blocks` | — | ordered blocks, in reading order |
| `metrics` | — | content metrics, over the built document |
| `run` | — | the processor's contract; `--page` (default `1`) |

Only `run` publishes a file.

### One file

```bash
python scripts/tools/ocr.py text tests/fixtures/ocr/ocr_prepared_text_and_table.png
python scripts/tools/ocr.py tables tests/fixtures/ocr/ocr_prepared_text_and_table.png --tables
python scripts/tools/ocr.py --json run tests/fixtures/ocr/ocr_prepared_text_and_table.png \
    --layout --tables --reading-order
```

The engine writes its own INFO lines to **stdout**, so they can appear ahead of the payload.

### A folder

```bash
python scripts/tools/batch_ocr.py tests/fixtures/ocr              # text — the default command
python scripts/tools/batch_ocr.py tests/fixtures/ocr metrics
```

---

## LLM / VLM — `llm.py` · `batch_llm.py`

Inputs: `.txt` `.md`. `--assets-dir` is global and defaults to `tests/fixtures/llm/` (templates
under `template/`, schemas under `schema/`); the resolved value is printed with every run. There is
**no default provider and no default model** — omitting either is a usage error (`2`), never a
substituted stand-in.

| Subcommand | Needs | What it gives you |
|---|---|---|
| `call` | `--provider` `--model` `--task` `--template` | one inference |
| `node` | the same | one node, against a fresh chain state |
| `graph` | the same | the fixed linear chain |
| `resume` | the same, plus the same `--run-id` and `--out` | re-invocation *is* the resume |
| `status` | `--out` alone | the per-node states of a previous run |
| `models` | `--provider` `--model` | inventory only, no generation |
| `tokens` | `--provider` `--model` | offline count; the window comes from `--context-window` |
| `fake` | `--provider` `--model` `--task` `--template` `--run-id` | the chain under the scripted provider, twice under one pinned identity |

`--schema`, `--context-window` and a repeatable `--option KEY=VALUE` are optional on every
inference subcommand. `--run-id` is how a run is pinned — it is what makes `resume` a resume
rather than a fresh call, and it is required by `fake`, whose whole point is showing a graph and
its resume under one identity.

### One file

```bash
python scripts/tools/llm.py --run-id demo \
    fake tests/fixtures-txt/casos/66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.txt \
    --provider ollama --model llama3.1 --task extract --template simple_extract --schema simple
```

Then the real thing, which is the honest failure this bench exists for — no model is served here,
so it prints a typed `MODEL_UNAVAILABLE` (`status: 404`) and exits `1`:

```bash
python scripts/tools/llm.py --fixture casos/66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.txt \
    call --provider ollama --model llama3.1 --task extract \
    --template simple_extract --schema simple
```

`node`, `status`, `models` and `tokens` publish nothing.

### A folder

```bash
python scripts/tools/batch_llm.py --fake tests/fixtures-txt/casos call \
    --provider ollama --model llama3.1 --task extract --template simple_extract --schema simple
python scripts/tools/batch_llm.py --fake tests/fixtures-txt/casos tokens \
    --provider ollama --model llama3.1 --context-window 4096
```

This is the one batch tool with **no default command** — a command is required (`2` without one) —
and it offers only `call`, `graph`, `node` and `tokens`. `status`, `models`, `fake` and `resume`
are per-file concerns; on `batch_llm.py` the scripted provider is the global `--fake` flag.

---

## Workflow — `workflow.py`

The orchestrator. It has **no batch twin**, and it reaches the four processors only through their
public contracts: it imports no `docflow.*.primitives` module.

Every flag that describes the request or the run is **global** — before the subcommand:
`--workflow`, `--input-type`, the policies (`--allow-ocr` / `--allow-vlm`), the per-processor
options (`--pdf-*`, `--image-*`, `--ocr*`), the LLM stage (`--task`, `--provider`, `--model`,
`--template`, `--schema`, `--llm-option`) and the execution switches (`--reuse`,
`--retry-failed`, `--start-from`, `--parallel-pages`, `--dry-run`, `--fake-llm`). Only `--stages`
(`force`, `skip`) and `--after` (`stop`) go after the subcommand.

| Subcommand | What it does |
|---|---|
| `run` | the whole documental workflow |
| `plan` | the execution plan; invokes no processor, and needs no `--dry-run` — planning *is* the dry run |
| `status` | the per-stage states of the last run |
| `context` | the durable `document_context.json` |
| `resume` | continue a run without repeating completed work |
| `force` | run the given stages even though a valid result exists (`--stages PDF,OCR`) |
| `skip` | leave the given stages unrun (the same flag) |
| `stop` | stop once a stage finishes (`--after PDF`) |

The request must be **complete**: the library refuses a missing option or policy key **by name**
(`CONFIGURATION_ERROR`, printed, exit `1`). The tool leaves a key you did not state absent and
never fills the gap — so `--pdf-dpi` and both policies are not optional in practice.

```bash
python scripts/tools/workflow.py --allow-ocr --no-allow-vlm \
    --pdf-dpi 150 --image-normalize --ocr \
    --task extract --provider ollama --model llama3.1 --template simple_extract \
    plan tests/fixtures/pdf/pdf_sample_text.pdf
```

`plan`, `status` and `context` publish nothing. Add `--fake-llm` to install the scripted provider
below the orchestrator's frontier, which is what lets a whole document run be demonstrated with no
model and no token spent.
