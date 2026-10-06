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
| `render` | `--dpi` | one page as a PNG, or every page |
| `text` | — | the page's native text, or every page's; writes `page_NNN.txt` and `page_NNN_layout.txt` |
| `blocks` | — | the same read, block view (reading order, boxes) |
| `images` | — | the page's embedded images, or every page's |
| `classify` | — | metrics plus the `TEXT` / `IMAGE` / `MIXED` verdict, per page |
| `run` | `--dpi` | the processor's contract; `--page` switches to the page-level one |

The five page-addressed commands (`render`, `text`, `blocks`, `images`, `classify`) take `--page`
to read **one** page and read **every** page when it is omitted — there is no second spelling for
a whole document, and one page is simply a scope of one. The payload says which scope it read
(`scope`), and a run over every page reports a `pages` list, a `status` and its `errors`.

### One file

```bash
python scripts/tools/pdf.py inspect tests/fixtures/pdf/pdf_sample_mixed.pdf
python scripts/tools/pdf.py split tests/fixtures/pdf/pdf_sample_text.pdf
python scripts/tools/pdf.py render tests/fixtures/pdf/pdf_sample_text.pdf --page 1 --dpi 200
python scripts/tools/pdf.py text tests/fixtures/pdf/pdf_sample_mixed.pdf
python scripts/tools/pdf.py blocks tests/fixtures/pdf/pdf_sample_mixed.pdf --page 1
python scripts/tools/pdf.py images tests/fixtures/pdf/pdf_sample_image.pdf
python scripts/tools/pdf.py --json classify tests/fixtures/pdf/pdf_sample_mixed.pdf --page 1
python scripts/tools/pdf.py --json classify tests/fixtures/pdf/pdf_sample_text.pdf   # all 3 pages
python scripts/tools/pdf.py run tests/fixtures/pdf/pdf_sample_text.pdf \
    --dpi 200 --extract-text --extract-images
```

That is all eight subcommands, one line each. `text` and `blocks` are the same read in two views;
`images` reads the sample whose one page is nothing but an embedded image; and `classify` is shown
both ways — one page and all three. `text` publishes **two** files per page, named after the page
the way `render` names its PNG: `page_NNN.txt`, the text rebuilt in reading order, and
`page_NNN_layout.txt`, the engine's own `-layout` rendering, which keeps the page's columns. Read
the first to read the page; reach for the second when *where* a value sits is the information — in
the two-column footer of a ticket the first stays readable and the second interleaves the two
texts. `inspect` and `blocks` publish nothing, their report being the stdout summary.

### A folder

```bash
python scripts/tools/batch_pdf.py tests/fixtures/pdf              # inspect — the default command
python scripts/tools/batch_pdf.py tests/fixtures/pdf split
python scripts/tools/batch_pdf.py tests/fixtures/pdf render --dpi 150
python scripts/tools/batch_pdf.py tests/fixtures/pdf text
python scripts/tools/batch_pdf.py tests/fixtures/pdf blocks
python scripts/tools/batch_pdf.py tests/fixtures/pdf images
python scripts/tools/batch_pdf.py tests/fixtures/pdf classify     # every page of every PDF
python scripts/tools/batch_pdf.py tests/fixtures/pdf classify --page 1   # just the first page
python scripts/tools/batch_pdf.py tests/fixtures/pdf run --dpi 200 --extract-text
python scripts/tools/batch_pdf.py --no-recursive --out var/x tests/fixtures/matrix split
```

The same eight subcommands as `pdf.py`, with the folder in place of the file.

With no subcommand the run makes `inspect` and says so in its header
(`command: inspect (default, none stated)`). `tests/fixtures/pdf` is four inputs, three written and
one the corrupt sample: `files: 4 · succeeded: 3 · failed: 1`, exit `1`.

**Reading `classify`.** Poppler reports no placement for an embedded image, so
`image_coverage` and `largest_image_coverage` stay `0.0` and the verdict rests on the native text
layer alone: a scanned page carrying a hidden OCR layer therefore reads `TEXT`, not `IMAGE`.

That is why `pdf_sample_mixed.pdf` reads `TEXT` — but it is not the whole reason, and the two are
worth telling apart. The sample's image is drawn 96×96 pt on a 612×792 page, so it covers about
**1.9%**, far under the 30% a dominant image needs: even a reader that reported placement would
still call that page `TEXT`. The missing placement explains the `0.0`; the `TEXT` would survive
its return. `IMAGE` needs a page with no native text at all, and `MIXED` an image that really does
dominate — which is what reading all 59 pages of `tests/fixtures/pdf_large/MetodoCITRA17-APL.pdf`
shows: 57 `TEXT`, 2 `IMAGE`, no `MIXED`.

---

## Image — `image.py` · `batch_image.py`

Inputs: `.png` `.jpg` `.jpeg` `.tif` `.tiff` `.bmp`. No subcommand requires a flag.

| Subcommand | Needs | What it gives you |
|---|---|---|
| `info` | — | file and pixel facts, read without measuring quality |
| `metrics` | — | quality, orientation, skew, regions |
| `normalize` | — | writes `normalized.png`, or `normalized.jpg` with `--quality` |
| `ocr-ready` | — | writes `ocr_ready.png`, through its own pipeline |
| `vlm-ready` | — | writes `vlm_ready.png`, or `vlm_ready.jpg` with `--quality` |
| `classify` | — | the technical classification, over the metrics above |
| `run` | — | the processor's contract |

`normalize`, `ocr-ready`, `vlm-ready` and `run` accept `--correct-orientation` and `--deskew`; no
correction is ever applied because a measurement suggested it and nobody asked. `normalize`,
`vlm-ready` and `run` additionally take `--quality N`: the representation is published as a lossy
JPEG at that factor instead of a lossless PNG, which is what a VLM's base64 payload wants.
`ocr-ready` has no such flag on purpose — its pipeline binarizes the page, and a lossy encoder
rings around every glyph edge. `run` additionally takes `--from-page`, `--page` (default `1`),
`--normalize`, `--prepare-for-ocr` and `--prepare-for-vlm`.

### One file

```bash
python scripts/tools/image.py info tests/fixtures/image/color_layout.png
python scripts/tools/image.py --json metrics tests/fixtures/image/skewed_text.png
python scripts/tools/image.py classify tests/fixtures/image/color_layout.png
python scripts/tools/image.py normalize tests/fixtures/image/skewed_text.png --deskew
python scripts/tools/image.py normalize tests/fixtures/image/color_layout.png --quality 85
python scripts/tools/image.py ocr-ready tests/fixtures/image/skewed_text.png
python scripts/tools/image.py vlm-ready tests/fixtures/image/color_layout.png
python scripts/tools/image.py run tests/fixtures/image/color_layout.png \
    --normalize --prepare-for-ocr
```

That is all seven subcommands: `normalize`, `ocr-ready` and `vlm-ready` are three separate
pipelines, never aliases of one another. `info`, `metrics` and `classify` publish nothing; the four
that do publish end in the typed `WRITE_ERROR` the limitation below describes.

### A folder

```bash
python scripts/tools/batch_image.py tests/fixtures/image              # info — the default command
python scripts/tools/batch_image.py tests/fixtures/image metrics
python scripts/tools/batch_image.py tests/fixtures/image classify
python scripts/tools/batch_image.py tests/fixtures/image normalize
python scripts/tools/batch_image.py tests/fixtures/image ocr-ready
python scripts/tools/batch_image.py tests/fixtures/image vlm-ready
python scripts/tools/batch_image.py tests/fixtures/image run
```

The same seven subcommands as `image.py`, with the folder in place of the file. `tests/fixtures/image`
is four inputs, one of them the committed corrupt sample, so **every** command listed reports
`files: 4 · succeeded: 3 · failed: 1` and exits `1` — the four that publish adding the
`WRITE_ERROR` below on top of the one `DECODE_ERROR`, and the walk still reaches the end.

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
| `text` | — | the extraction's plain text; writes `text.txt` |
| `mixed` | — | the page's rows, with detected tables as Markdown; writes `mixed.txt` |
| `md` | — | the extraction's Markdown |
| `json` | — | the structured document, serialized |
| `tables` | — | detected tables, in reading order |
| `blocks` | — | ordered blocks, in reading order |
| `metrics` | — | content metrics, over the built document |
| `run` | — | the processor's contract; `--page` (default `1`) |

`run` publishes the contract's document; `text` publishes the engine's own text as `text.txt`, and
`mixed` publishes the page's rows as `mixed.txt`; the other five write nothing but their report.

### One file

```bash
python scripts/tools/ocr.py text tests/fixtures/ocr/ocr_prepared_text_and_table.png
python scripts/tools/ocr.py mixed tests/fixtures/ocr/ocr_prepared_text_and_table.png
python scripts/tools/ocr.py md tests/fixtures/ocr/ocr_prepared_text_and_table.png
python scripts/tools/ocr.py json tests/fixtures/ocr/ocr_prepared_text_and_table.png
python scripts/tools/ocr.py tables tests/fixtures/ocr/ocr_prepared_text_and_table.png
python scripts/tools/ocr.py blocks tests/fixtures/ocr/ocr_prepared_text_and_table.png
python scripts/tools/ocr.py metrics tests/fixtures/ocr/ocr_prepared_text_and_table.png
python scripts/tools/ocr.py --json run tests/fixtures/ocr/ocr_prepared_text_and_table.png \
    --layout --tables --reading-order
```

That is all eight subcommands. `text` and `md` are one conversion in two representations, `json`
is the built document, `tables` and `blocks` are its ordered views, and `metrics` measures the
document the others build. `mixed` renders the page the way the page is set: items that share a
line of it are one line, so a form's label and its value come back together, and every detected
table is carried as its Markdown where the reading reaches it. `tables` and `mixed` ask for the
detection themselves — and `mixed` for the boxes too — because a run that never asked could only
report the empty list or a text with no rows in it. `--no-tables` and `--no-layout` still state
the opposite; a rendering with no boxes falls back to the engine's own sequence, one item per line.

`text` and `mixed` publish what they report — `text.txt`, the engine's own text normalized the way
the processor publishes it, and `mixed.txt`, the row rendering — so a page whose engine text
carries trailing whitespace loses exactly that and nothing else.

The engine writes its own INFO lines to **stdout**, so they can appear ahead of the payload.

### A folder

```bash
python scripts/tools/batch_ocr.py tests/fixtures/ocr              # text — the default command
python scripts/tools/batch_ocr.py tests/fixtures/ocr mixed
python scripts/tools/batch_ocr.py tests/fixtures/ocr md
python scripts/tools/batch_ocr.py tests/fixtures/ocr json
python scripts/tools/batch_ocr.py tests/fixtures/ocr tables
python scripts/tools/batch_ocr.py tests/fixtures/ocr blocks
python scripts/tools/batch_ocr.py tests/fixtures/ocr metrics
python scripts/tools/batch_ocr.py tests/fixtures/ocr run
```

The same eight subcommands as `ocr.py`, with the folder in place of the file. `tests/fixtures/ocr` is
two images, both converted, so every command reports `files: 2 · succeeded: 2 · failed: 0` and
exits `0`. The bare run makes `text` and files a `text.txt` beside each input's record, so the
default is a corpus of readable text files rather than a corpus of JSON.

---

## LLM / VLM — `llm.py` · `batch_llm.py`

Inputs: `.txt` `.md`, or a page image. `--assets-dir` is global and defaults to
`tests/fixtures/llm/` (templates under `template/`, schemas under `schema/`); the resolved value is
printed with every run. There is **no default provider and no default model** — omitting either is a
usage error (`2`), never a substituted stand-in.

**The input is the document, or the page.** A text input is read into `<doc>`; an input that is an
image **is** the document — the call attaches the pixels and states no text, which is how the
registry's vision steps (`extraction/invoice_vision*`, `review/invoice_vision*`) are driven. Nothing
flags the difference: the input's own kind decides, so the same commands run both flows. `--image`
attaches further pages *beside* the input, repeatable and in the order written, and `--image-tokens`
states what one of them costs. A template that quotes a document the run does not carry is refused
by the library rather than handed the image's bytes. `tokens` is the one text-only command: a page
has no offline count, so it is refused (`2`) rather than counted as something it is not.

| Subcommand | Needs | What it gives you |
|---|---|---|
| `call` | `--provider` `--model` `--task` `--template` | one inference, and the two step artifacts below |
| `prompt` | the same | the prompt a `call` would send, rendered — nothing is sent, nothing is written |
| `node` | the same | one node, against a fresh chain state |
| `graph` | the same | the fixed linear chain |
| `resume` | the same, plus the same `--run-id` and `--out` | re-invocation *is* the resume |
| `status` | `--out` alone | the per-node states of a previous run |
| `models` | `--provider` `--model` | inventory only, no generation |
| `tokens` | `--provider` `--model` | offline count of a text input — a page is refused; the window comes from `--context-window` |
| `fake` | `--provider` `--model` `--task` `--template` `--run-id` | the chain under the scripted provider, twice under one pinned identity |

`--schema`, `--context-window`, `--image-tokens` and the repeatable `--option KEY=VALUE`,
`--extra KEY=VALUE` and `--image FILE` flags are optional on every inference subcommand. An
`--option` value is read as JSON, so
`temperature=0` reaches the provider as the number `0` (a string is refused). `--extra` fills a
template's `<extra:KEY>` placeholder, and `KEY=@FILE` reads the value from a file — how one step's
saved answer reaches the next. A **review** fills two of them: the proposal it audits and the
reviewed step's own schema as `contract`
(`--extra contract=@registry/llm-local/schema/extraction/invoice.schema.json`), so each verdict is measured
against that step's rules rather than against what looks plausible. `--run-id` is how a run is
pinned — it is what makes `resume` a resume rather than a fresh call, and it is required by `fake`,
whose whole point is showing a graph and its resume under one identity. `--image` and
`--image-tokens` belong to the pixel flow, one section below.

**`prompt` is the ask, not the answer.** It states the same request `call` does — the same template,
schema, extras, images and asset root — and stops before the provider, printing the prompt a `call`
would have sent, the pages it would attach, its token count, and the processor's own verdict on that
ask: `fits`, `exceeds`, or `unmeasured` (`context_verdict`, with `overflows` the `exceeds` case).
Read it the way the processor reads it: `unmeasured` is not *it fits* — a prompt with no stated
window, or a request carrying images whose cost nobody stated, is reported as unmeasured rather than
blessed. Nothing is sent and nothing is written, so `--provider` and `--model` are stated only because
every inference command states them; the window is what a render reads them for. It is the cheap check
before a reasoning review: that prompt is minutes of a 12B model, and a window too small for it comes
back as an empty answer rather than as an error. `--json` with `jq -r .prompt` gives the bare text:

```bash
python scripts/tools/llm.py --json --assets-dir registry/llm-local \
    prompt tests/fixtures-txt/casos/66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.txt \
    --provider ollama --model gemma3:12b --task detection \
    --template extraction/invoice_deteccion --schema extraction/invoice_detection \
    --context-window 16384 | jq -r .prompt
```

**`--stream`** reads an answer as it is written instead of waiting for the whole of it: a reasoning
review takes minutes, and this is what shows whether it is thinking or stuck. The model's trace and
its answer go to stderr under a `[thinking]` / `[content]` header, so stdout — and the files — stay
the finished answer.

**`--name`** (on `call`) is the base name of the two step artifacts a `call` files: `<name>.json` is
the answer alone — the object a later step reads back through `--extra KEY=@FILE` — and
`<name>_full.json` is the whole run. Without `--name` the step is keyed by the schema's last path
component, so `--name review` is how two steps that share a schema name (`extraction/invoice` and
`review/invoice`) stop overwriting each other.

**Or state them once in `.env`.** `<repo root>/.env` — `cp .env.example .env` — supplies
`DOCFLOW_ASSETS_DIR`, the endpoint, the credential, the timeout and the decoding options, so
`--option num_ctx=16384 --option timeout=600` stops being retyped on every command. A real
environment variable beats the file and `--option` beats both; the run prints a `config:` line
naming what it took. `--provider` and `--model` are not read from it — they stay required flags.

**The window has one spelling that matters.** `--context-window` is it: the processor compares the
prompt's cost against that number *and* asks the provider for it (the Ollama transport sends it as
`num_ctx`). `--option num_ctx=…` still reaches the provider, because it is a decoding option it
understands — but only `--context-window` is what the pre-flight and `prompt`'s `overflows` field
measure against. State it once; `.env` is the place.

### A hosted provider

`--provider` names the transport, and four names are one wire — `openai`, `openai_compatible`,
`vllm` and `deepseek` all speak OpenAI chat-completions. `deepseek` is a named kind of it with its
own endpoint, so a hosted run states the product rather than the URL:

```bash
python scripts/tools/llm.py --assets-dir registry/llm-frontier \
    call tests/fixtures-txt/casos/66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.txt \
    --provider deepseek --model deepseek-flash --task extract \
    --template extraction/invoice --schema extraction/invoice \
    --context-window 64000 --option timeout=300 \
    --option api_key="$DEEPSEEK_API_KEY"
```

`deepseek` reaches `https://api.deepseek.com` with **no** `--option base_url`; state one only to
reach another endpoint (`--provider openai_compatible --option base_url=…`). Three things differ from
an Ollama run and are worth reading before the first paying call:

- **Structured output is per dialect.** `deepseek` is asked for a bare `json_object` and the schema
  travels **inlined in the prompt** (`prompt` shows it there); `openai`/`vllm` keep
  `response_format: json_schema`. Same `--schema`, different wire.
- **The window is unknown off Ollama.** `get_context_window` answers `None` for every hosted kind, so
  state `--context-window`; with none, `prompt` reports `unmeasured`, never `fits`.
- **A reasoning tag needs a longer wait.** `deepseek-flash` thinks before it answers, so state
  `--option timeout=300` (or more). The local daemon's own keys — `think`, `keep_alive`, `num_ctx` —
  are dropped from a hosted body, so they cannot be handed over by mistake.

The same commands run under `batch_llm.py`, one command over a folder:

```bash
python scripts/tools/batch_llm.py tests/fixtures-txt/casos --assets-dir registry/llm-frontier \
    prompt --provider deepseek --model deepseek-flash --task extract \
    --template extraction/invoice --schema extraction/invoice --context-window 64000
```

### One file

Three of the eight answer with no provider at all — the scripted chain, the state it leaves behind,
and the offline token count:

```bash
python scripts/tools/llm.py --run-id demo --out var/demo \
    fake tests/fixtures-txt/casos/66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.txt \
    --provider ollama --model llama3.1 --task extract --template simple_extract --schema simple
python scripts/tools/llm.py --out var/demo status
python scripts/tools/llm.py tokens tests/fixtures-txt/casos/66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.txt \
    --provider ollama --model llama3.1 --context-window 4096
```

`fake` runs the chain twice under the pinned `--run-id demo`, writing it under `--out var/demo`.
`status` then reads that run and takes `--out` alone — the question is about the *run directory*,
not about an input — and `tokens` counts offline, taking its window from `--context-window`.

Then the ones that reach a provider, which is the honest failure this bench exists for. How it
fails is typed, and either way it exits `1`: `PROVIDER_ERROR` (`ollama could not be reached`,
`[Errno 61] Connection refused`) when nothing is listening, or `MODEL_UNAVAILABLE` when the
endpoint answers but does not offer the model — the latter carries the HTTP `status: 404` in its
error metadata, not in the payload's own `status` field:

```bash
python scripts/tools/llm.py --fixture casos/66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.txt \
    call --provider ollama --model llama3.1 --task extract \
    --template simple_extract --schema simple
python scripts/tools/llm.py node tests/fixtures-txt/casos/66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.txt \
    --provider ollama --model llama3.1 --task extract --template simple_extract --schema simple
python scripts/tools/llm.py graph tests/fixtures-txt/casos/66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.txt \
    --provider ollama --model llama3.1 --task extract --template simple_extract --schema simple
python scripts/tools/llm.py models tests/fixtures-txt/casos/66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.txt \
    --provider ollama --model llama3.1
```

`call` is one inference, `node` one node against a fresh chain state, `graph` the fixed linear
chain, and `models` the inventory alone — it never generates, which is why it needs no task and no
template. `resume` is the eighth: re-run under the same `--run-id demo` and `--out var/demo` as the
`fake` line above, it finds that run's stored nodes and returns them (`REUSE` on each) without
reaching a provider at all:

```bash
python scripts/tools/llm.py --run-id demo --out var/demo \
    resume tests/fixtures-txt/casos/66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.txt \
    --provider ollama --model llama3.1 --task extract --template simple_extract --schema simple
```

`node`, `status`, `models` and `tokens` publish nothing.

`call` on a real model, watched as it answers — the deltas on stderr, stdout and the two files
unchanged:

```bash
python scripts/tools/llm.py call tests/fixtures-txt/casos/66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.txt \
    --provider ollama --model deepseek-r1:8b --task review --template review/invoice \
    --schema review/invoice --stream --name review \
    --extra proposal=@var/run/reading/invoice.json \
    --option temperature=0.6 --option num_ctx=16384 --timeout 300
```

That writes `review.json` (the answer alone) and `review_full.json` (the run) beside the run's own
`state.json` and `final_result.json`, whatever the schema was called.

### The layered extraction, one command per step

The registry's templates are a flow, not a prompt: five extraction calls and the reviews that audit
them, each step its own artifact and its own schema. [`registry/llm-local/README.md`](../../registry/llm-local/README.md)
states the roles and the criteria — why the reviewer is handed the reviewed step's schema as a
`contract`, why two models review, what the reasoning variant of a template pair is for. What follows
is the same flow as commands.

`--task` is a label: it is recorded in the run and never reaches the model. `--template` and
`--schema` are what select the step, and both are identifiers under `--assets-dir` — the bench
resolves `extraction/invoice` itself, so the `.md` and `.schema.json` suffixes are never typed.

```bash
REG=registry/llm-local
DOC=tests/fixtures-txt/casos/66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.txt
T1=gemma3:12b       # extracts
T2=deepseek-r1:8b   # reviews
T3=qwen3.5:9b       # reviews again, so the two verdicts can be compared

# what the gate asks, without sending anything: the rendered prompt, its size, and whether that
# size is known to exceed the window stated. No provider is reached.
python scripts/tools/llm.py --assets-dir $REG prompt $DOC \
    --provider ollama --model $T1 --task detection \
    --template extraction/invoice_deteccion --schema extraction/invoice_detection \
    --context-window 16384

# 0 — the gate: a receipt, or something else? Run it first and refuse cheaply.
python scripts/tools/llm.py --assets-dir $REG --out var/run/detection call $DOC \
    --provider ollama --model $T1 --task detection \
    --template extraction/invoice_deteccion --schema extraction/invoice_detection

# 1 — the base reading the rest of the flow refines, and the one the review judges. It takes its
#     own `--out`, because the review below files under the same schema stem and would otherwise
#     overwrite the very answer it audits.
python scripts/tools/llm.py --assets-dir $REG --out var/run/reading call $DOC \
    --provider ollama --model $T1 --task extract \
    --template extraction/invoice --schema extraction/invoice

# 2 — the breakdown of items and amounts
python scripts/tools/llm.py --assets-dir $REG --out var/run/desglose call $DOC \
    --provider ollama --model $T1 --task desglose \
    --template extraction/invoice_desglose --schema extraction/invoice_desglose

# 3 — the receipt class, and 4 — the line of business the caller states
python scripts/tools/llm.py --assets-dir $REG --out var/run/clasificacion call $DOC \
    --provider ollama --model $T1 --task clasificacion \
    --template extraction/invoice_clasificacion --schema extraction/invoice_clasificacion

python scripts/tools/llm.py --assets-dir $REG --out var/run/rubro call $DOC \
    --provider ollama --model $T1 --task rubro \
    --template extraction/invoice_rubro --schema extraction/invoice_rubro \
    --extra rubro=Restaurante

# 5 — the review reads step 1's answer: the answer alone, never the run's envelope. T2 is a
#     reasoning model, so it is asked the reasoning variant of the pair — the same schema, the
#     criteria instead of the rules — and its thinking is braked here. The brake is the model's,
#     not the house's: see the breakdown review below, where the same brake on the same model
#     empties the answer instead of shortening it.
python scripts/tools/llm.py --assets-dir $REG --out var/run/review call $DOC \
    --provider ollama --model $T2 --task review \
    --template review/invoice.reasoning --schema review/invoice \
    --extra proposal=@var/run/reading/invoice.json \
    --extra contract=@registry/llm-local/schema/extraction/invoice.schema.json \
    --option think=false --option temperature=0.6 --option top_p=0.95 \
    --option repeat_penalty=1.0 --option num_ctx=16384 --option num_predict=4096 \
    --option timeout=600

# 6 — step 5 again on T3, with the thinking braked the way that model's card wants
python scripts/tools/llm.py --assets-dir $REG --out var/run/review-qwen call $DOC \
    --provider ollama --model $T3 --task review \
    --template review/invoice --schema review/invoice \
    --extra proposal=@var/run/reading/invoice.json \
    --extra contract=@registry/llm-local/schema/extraction/invoice.schema.json \
    --option think=false --option temperature=0.2 --option min_p=0.05 \
    --option num_ctx=16384 --option timeout=600

# The breakdown of step 2 is reviewed the same way, against its own step schema. This is the one
# prompt where the brake above does the opposite of its job: T2 with `think=false` returned no
# content at all here — twice, an empty answer the processor types as INVALID_JSON and retries —
# and answered once its thinking was left free and given room. So this pair runs unbraked, and T3
# carries the braked variant. Which side of a pair needs the brake is a thing a run tells you.
python scripts/tools/llm.py --assets-dir $REG --out var/run/review-desglose call $DOC \
    --provider ollama --model $T2 --task review \
    --template review/invoice_desglose.reasoning --schema review/invoice_desglose \
    --extra proposal=@var/run/desglose/invoice_desglose.json \
    --extra contract=@registry/llm-local/schema/extraction/invoice_desglose.schema.json \
    --option temperature=0.6 --option top_p=0.95 --option repeat_penalty=1.0 \
    --option num_ctx=16384 --option num_predict=8192 --option timeout=900

python scripts/tools/llm.py --assets-dir $REG --out var/run/review-desglose-qwen call $DOC \
    --provider ollama --model $T3 --task review \
    --template review/invoice_desglose --schema review/invoice_desglose \
    --extra proposal=@var/run/desglose/invoice_desglose.json \
    --extra contract=@registry/llm-local/schema/extraction/invoice_desglose.schema.json \
    --option think=false --option temperature=0.2 --option min_p=0.05 \
    --option num_ctx=16384 --option timeout=600
```

Those nine commands, run against a daemon serving those three tags, all came back `SUCCESS` with
`schema_valid: true` — five extraction steps and four reviews. A review that returns *nothing* is
not a refusal: it is a typed `INVALID_JSON` over an empty answer, and the remedy is an option, not a
retry.

Every line above is the same `call`: what differs is the template, the schema and the extras. Each
step writes two files beside the run's own — `<step>.json`, the answer alone, and `<step>_full.json`,
the whole run — under the `--out` that step was given, named after `--name` or after the schema's
last component. Watching a review happen instead of reading what it left is one more flag: add
`--stream` to any of them and its thinking and its answer arrive on stderr while stdout and the two
files stay the finished answer.

### The same flow from the pixels

The nine commands above read *text*. The registry ships a **vision twin of every step** — a template
that reads the page itself instead of the document (`extraction/invoice_vision*`,
`review/invoice_vision*`, five steps and their reviewers) — and the same commands drive it: the input
is the page image, so the call attaches the pixels and states no text, and a template carrying no
`<doc>` resolves exactly as it does here. Nothing states the difference: the input's own kind decides.

What changes is the identifiers and the window. A step's schema still compiles the answer's shape
into the decoder's grammar, and a review still carries the proposal it audits — but a page costs
thousands of prompt tokens no text measurement sees, so `--image-tokens` states what one image costs.
Without it the pre-flight reports the call `unmeasured` instead of blessing a number it knows is too
small; with it, `--context-window` is the window the check compares the total against **and** the one
the call asks the provider for. The receipt is the one the text flow reads as
`fixtures-txt/casos/<same id>.txt`, so the two paths answer about the same paper.

```bash
IMG=tests/fixtures/casos/66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.jpg
R=registry/llm-local
V1=qwen3-vl:8b      # reads the page image
V2=ministral-3:8b   # reviews the vision reading

# what the flow asks, without sending anything and without encoding the image: the rendered prompt,
# the page it would attach, and the processor's own verdict on the fit
python scripts/tools/llm.py --assets-dir $R --json prompt $IMG \
    --provider ollama --model $V1 --task extract \
    --template extraction/invoice_vision --schema extraction/invoice_vision \
    --context-window 16384 --image-tokens 2800 | jq '{images, prompt_tokens, context_verdict}'

# 1 — the base reading, straight from the pixels: no document is stated, because the image is the
#     document and the template carries no <doc>. The step's own schema compiles the answer's shape
#     into the decoder's grammar, exactly as the text path's does.
python scripts/tools/llm.py --assets-dir $R --out var/run/reading-vision call $IMG \
    --provider ollama --model $V1 --task extract --name reading \
    --template extraction/invoice_vision --schema extraction/invoice_vision \
    --context-window 16384 --image-tokens 2800

# 0 — the gate, 2 — the breakdown, 3 — the class, 4 — the line of business: same shapes, one page
python scripts/tools/llm.py --assets-dir $R --out var/run/detection-vision call $IMG \
    --provider ollama --model $V1 --task detection \
    --template extraction/invoice_vision_deteccion --schema extraction/invoice_vision_detection \
    --context-window 16384 --image-tokens 2800

python scripts/tools/llm.py --assets-dir $R --out var/run/desglose-vision call $IMG \
    --provider ollama --model $V1 --task desglose \
    --template extraction/invoice_vision_desglose --schema extraction/invoice_vision_desglose \
    --context-window 16384 --image-tokens 2800

python scripts/tools/llm.py --assets-dir $R --out var/run/clasificacion-vision call $IMG \
    --provider ollama --model $V1 --task clasificacion \
    --template extraction/invoice_vision_clasificacion \
    --schema extraction/invoice_vision_clasificacion \
    --context-window 16384 --image-tokens 2800

python scripts/tools/llm.py --assets-dir $R --out var/run/rubro-vision call $IMG \
    --provider ollama --model $V1 --task rubro \
    --template extraction/invoice_vision_rubro --schema extraction/invoice_vision_rubro \
    --extra rubro=Restaurante --context-window 16384 --image-tokens 2800

# 5 — the review of step 1's answer, against the same page. The template names the proposal alone,
#     so the schema is what says which fields are judged. A review carries the page, the proposal
#     and the contract, so its ask is the flow's largest.
python scripts/tools/llm.py --assets-dir $R --out var/run/review-vision call $IMG \
    --provider ollama --model $V2 --task review --name review \
    --template review/invoice_vision --schema review/invoice_vision \
    --extra proposal=@var/run/reading-vision/reading.json \
    --extra contract=@registry/llm-local/schema/extraction/invoice_vision.schema.json \
    --context-window 16384 --image-tokens 2800 \
    --option temperature=0.2 --option min_p=0.05

# 6 — the breakdown of step 2, judged from the pixels by the criteria-bearing reviewer
python scripts/tools/llm.py --assets-dir $R --out var/run/review-desglose-vision call $IMG \
    --provider ollama --model $V2 --task review --name review-desglose \
    --template review/invoice_vision_desglose --schema review/invoice_vision_desglose \
    --extra proposal=@var/run/desglose-vision/invoice_vision_desglose.json \
    --extra contract=@registry/llm-local/schema/extraction/invoice_vision_desglose.schema.json \
    --context-window 16384 --image-tokens 2800 \
    --option temperature=0.2 --option min_p=0.05
```

Every line is the same `call` the text block above runs, with the page in place of the document: the
`<step>.json` / `<step>_full.json` pair lands under that step's `--out`, `--extra proposal=@…` reads
the answer alone the step before wrote, and `--stream` watches any of them happen.

The other half of the surface is the same flags. A page carried **beside** its text — the strategy
the library calls `TEXT_PLUS_VLM` — is a text input with `--image` added; a document of several pages
is one `--image` per page, in reading order, and `--image-tokens` then states what one page costs
rather than what the set does. `batch_llm.py` walks `.txt`, `.md` **and** the image suffixes, so a
folder of pages is one command over a corpus exactly as a folder of texts is. The library form —
`LLMInput` with its `images` and the two `metadata` keys — is `registry/llm-local/README.md` → *Chaining the
steps*.

### A folder

```bash
python scripts/tools/batch_llm.py --fake tests/fixtures-txt/casos call \
    --provider ollama --model llama3.1 --task extract --template simple_extract --schema simple
python scripts/tools/batch_llm.py --fake tests/fixtures-txt/casos graph \
    --provider ollama --model llama3.1 --task extract --template simple_extract --schema simple
python scripts/tools/batch_llm.py --fake tests/fixtures-txt/casos node \
    --provider ollama --model llama3.1 --task extract --template simple_extract --schema simple
python scripts/tools/batch_llm.py --fake tests/fixtures-txt/casos tokens \
    --provider ollama --model llama3.1 --context-window 4096
python scripts/tools/batch_llm.py tests/fixtures-txt/casos prompt \
    --provider ollama --model llama3.1 --task extract --template simple_extract --schema simple
# the same command over a folder of pages: each walked image is its own input's document. The
# fixture template stands in for the registry's, because the scripted provider answers the simple
# schema — against the registry, drop --fake and serve the vision model instead.
python scripts/tools/batch_llm.py --fake --assets-dir tests/fixtures/llm tests/fixtures/image call \
    --provider ollama --model qwen3-vl:8b --task read \
    --template simple_read_pixels --schema simple
```

Those are all five commands this tool offers. The walk takes `.txt`, `.md` **and** the image
suffixes, so a folder of pages runs a command exactly as a folder of texts does; `tokens` is the one
exception, because a page has no offline count — state `--image-tokens` and let `call`'s pre-flight
weigh it instead.

This is the one batch tool with **no default command** — a command is required (`2` without one) —
and it offers only `call`, `graph`, `node`, `tokens` and `prompt`. `status`, `models`, `fake` and
`resume` are per-file concerns; on `batch_llm.py` the scripted provider is the global `--fake` flag.
`prompt` is the one of the five that reaches no provider and writes nothing but its record: a corpus
of rendered prompts, one per input, is a reading of the corpus rather than a run over it — and the
record the frame files for an input is where that input's prompt lands.

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

The request must be **complete**: the tool leaves a key you did not state absent and never fills the
gap, and a subcommand that executes the workflow is refused **by name** (`CONFIGURATION_ERROR`,
printed, exit `1`) when an option or policy key is missing. So `--pdf-dpi`, the option keys and both
policies are not optional in practice, and every line below carries the same complete request
before it — only `--stages` (`force`, `skip`) and `--after` (`stop`) go after the subcommand:

```bash
python scripts/tools/workflow.py --allow-ocr --no-allow-vlm --pdf-dpi 150 \
    --image-normalize --ocr --task extract --provider ollama --model llama3.1 \
    --template simple_extract --fake-llm run tests/fixtures/pdf/pdf_sample_text.pdf
python scripts/tools/workflow.py --allow-ocr --no-allow-vlm --pdf-dpi 150 \
    --image-normalize --ocr --task extract --provider ollama --model llama3.1 \
    --template simple_extract plan tests/fixtures/pdf/pdf_sample_text.pdf
python scripts/tools/workflow.py --allow-ocr --no-allow-vlm --pdf-dpi 150 \
    --image-normalize --ocr --task extract --provider ollama --model llama3.1 \
    --template simple_extract status tests/fixtures/pdf/pdf_sample_text.pdf
python scripts/tools/workflow.py --allow-ocr --no-allow-vlm --pdf-dpi 150 \
    --image-normalize --ocr --task extract --provider ollama --model llama3.1 \
    --template simple_extract context tests/fixtures/pdf/pdf_sample_text.pdf
python scripts/tools/workflow.py --allow-ocr --no-allow-vlm --pdf-dpi 150 \
    --image-normalize --ocr --task extract --provider ollama --model llama3.1 \
    --template simple_extract --fake-llm resume tests/fixtures/pdf/pdf_sample_text.pdf
python scripts/tools/workflow.py --allow-ocr --no-allow-vlm --pdf-dpi 150 \
    --image-normalize --ocr --task extract --provider ollama --model llama3.1 \
    --template simple_extract --fake-llm force tests/fixtures/pdf/pdf_sample_text.pdf \
    --stages PDF
python scripts/tools/workflow.py --allow-ocr --no-allow-vlm --pdf-dpi 150 \
    --image-normalize --ocr --task extract --provider ollama --model llama3.1 \
    --template simple_extract --fake-llm skip tests/fixtures/pdf/pdf_sample_text.pdf \
    --stages OCR
python scripts/tools/workflow.py --allow-ocr --no-allow-vlm --pdf-dpi 150 \
    --image-normalize --ocr --task extract --provider ollama --model llama3.1 \
    --template simple_extract --fake-llm stop tests/fixtures/pdf/pdf_sample_text.pdf \
    --after PDF
```

`run` is the whole workflow; `plan` builds the execution plan and invokes no processor, needing no
`--dry-run` because planning *is* the dry run; `status` and `context` read what the run left (the
per-stage states and the durable `document_context.json`); `resume` continues a run without
repeating completed work; `force` and `skip` name their stages through `--stages`; and `stop` takes
its boundary through `--after`.

`plan`, `status` and `context` publish nothing. Add `--fake-llm` to install the scripted provider
below the orchestrator's frontier, which is what lets a whole document run be demonstrated with no
model and no token spent.
