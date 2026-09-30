# Lab tools (`scripts/tools/`)

Five thin operator CLIs — one per processor plus the orchestrator — that exercise the finished
library by hand against the committed fixtures.

This directory is the **lab bench**, not the library. It is not packaged, it registers no
console script, and nothing under `src/docflow/` imports it. Deleting `scripts/` leaves the
library and its tests untouched; `tests/test_lab_tools.py` asserts that.

**Why a bench and not a test.** The suite proves *our* code against in-memory doubles and, by
rule, never reaches an engine (`docs/plan/README.md` §9.7). A tool is the only surface where a
human runs the **real** seam — Poppler on a real PDF, OpenCV on a real scan, Docling on a real
page, a provider on a real prompt — and sees whether the engine's actual shape still matches
what our translation expects. That is a bench observation, not evidence, and it is never
recorded as a gate.

---

## Layout

| File | What it is |
|---|---|
| `_cli.py` | the shared **library**: the run frame, fixture resolution, the output root, the printers, the exit-code mapping. Not a tool — it holds no contract and reaches no engine |
| `_batch.py` | the shared **folder frame**: the walk, the mirror, the record per input, the summary, the exit codes. Not a tool — every batch tool runs on it |
| `_pdf.py` | the PDF bench's **command layer**: the eight methods, their payloads and their flags. Not a tool — `pdf.py` and `batch_pdf.py` both call it |
| `_image.py` | the image bench's **command layer**: the seven methods. Not a tool — `image.py` and `batch_image.py` both call it |
| `_ocr.py` | the OCR bench's **command layer**: the seven methods. Not a tool — `ocr.py` and `batch_ocr.py` both call it |
| `_llm.py` | the LLM bench's **command layer**: the eight methods. Not a tool — `llm.py` and `batch_llm.py` both call it |
| `pdf.py` | `SCR-02` — the PDF processor's primitives and its contract, one file per run |
| `batch_pdf.py` | `SCR-12` — the same eight methods over every PDF below a folder, one record per input |
| `image.py` | `SCR-03` — the image processor's pipelines and its contract, one file per run |
| `batch_image.py` | `SCR-13` — the same seven methods over every image below a folder |
| `ocr.py` | `SCR-04` — the OCR processor's representations and its contract |
| `batch_ocr.py` | `SCR-14` — the same seven methods over every image below a folder |
| `llm.py` | `SCR-05` — one inference, the chain, the inventory and the scripted provider |
| `batch_llm.py` | `SCR-15` — four of the same eight commands over every text below a folder |
| `workflow.py` | `SCR-06` — the orchestrator: plan, run, resume, force, skip, stop |

A tool owns its subcommands, its flags and one handler per subcommand. Everything else — where a
run writes, how an input resolves, the header, the printers, the exit code — comes from `_cli`,
its processor's methods come from that processor's layer, and a batch tool's walk and mirror come
from `_batch`. Adding a tool for a sixth processor means writing its parser and its handlers, and
nothing else.

The set of **modules** here is asserted by `tests/test_lab_tools.py` guard 1: `_cli.py`, `_batch.py`, the per-processor layers and the tools, and no other `.py` file. `subplan-scripts.md` §3.1 fixed the original set at `_cli.py` plus five tools; the batch tools, the shared folder frame and the layers that keep them from duplicating their single-file twins are the `SCR-11`…`SCR-18` plan revision that followed, and a module beyond that is the next one, not a surprise.

---

## Invocation

There are **two ways to run the bench**, and they take the same commands:

```bash
# one file: the input positional names a file
python scripts/tools/pdf.py inspect tests/fixtures/pdf/pdf_sample_mixed.pdf
python scripts/tools/llm.py --fixture casos/66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.txt \
    call --provider ollama --model llama3.1 --task extract \
    --template simple_extract --schema simple
python scripts/tools/workflow.py --allow-ocr --no-allow-vlm \
    --pdf-dpi 150 --image-normalize --ocr \
    --task extract --provider ollama --model llama3.1 --template simple_extract \
    plan tests/fixtures/pdf/pdf_sample_text.pdf

# one folder: the folder positional names a folder, and every matching file below it is an input
python scripts/tools/batch_pdf.py tests/fixtures/pdf                 # inspect, over every PDF below it
python scripts/tools/batch_llm.py --fake tests/fixtures-txt/casos tokens \
    --provider ollama --model llama3.1 --context-window 4096
```

Every line above runs as written against the committed fixtures. Each mode has its own section
below — [**Commands over one file**](#commands-over-one-file) and
[**Commands over a folder (batch)**](#commands-over-a-folder-batch) — and the second is not a
second implementation of the first: each processor's two tools call the same methods, so a
subcommand behaves the same way in both and the batch adds a folder, a mirror and a summary.

The `plan` line carries a **complete** workflow request, because the library refuses a missing
option key by name, and it needs no `--dry-run` — planning *is* the dry run. The `llm.py` line is
the honest failure the bench exists for: no model is served on this machine, so it prints a typed
`MODEL_UNAVAILABLE` and exits `1`. The `batch_pdf.py` line is `tests/fixtures/pdf`'s four PDFs,
three written and one reported as the corrupt file it is (exit `1`).

Each tool is invoked **by path**. No `pip install` is needed: the tools put the repository root
and `src/` on `sys.path` themselves, which is what `_cli.bootstrap()` does.

Every tool answers `--help`, and so does every subcommand:

```bash
python scripts/tools/ocr.py --help
python scripts/tools/ocr.py run --help
```

### Where flags go

This matters, and it is the one thing that surprises people:

- **Global flags go before the subcommand.** `--fixture`, `--fixtures-root`, `--json`, `--out`,
  and (on every tool but `workflow.py`) `--document-id` / `--run-id`. On `workflow.py` the same
  holds for every flag that describes the request or the run: `--pdf-*`, `--image-*`, `--ocr` and
  `--ocr-*`, `--task`/`--provider`/`--model`/`--template`/`--schema`, the policy switches
  (`--allow-ocr`, `--allow-vlm`), the execution switches (`--reuse`, `--retry-failed`,
  `--start-from`, `--parallel-pages`, `--dry-run`) and `--fake-llm`.
- **Subcommand flags go after it.** `--page`, `--dpi`, `--provider`, `--model`, `--task`,
  `--template`, `--schema`, `--context-window`, `--option`, and each tool's own — on
  `workflow.py` that is `--stages` (`force`, `skip`) and `--after` (`stop`).
- **The input positional belongs to the subcommand**: `pdf.py inspect <input>`, while
  `--fixture <name>` is the global spelling of the same thing. Either works; if both are given,
  `--fixture` wins.

### Common flags

| Flag | Meaning |
|---|---|
| `--fixture NAME` | Resolve a name under the fixture roots: a **bare** name is searched for at any depth (`pdf_sample_mixed.pdf` finds `tests/fixtures/pdf/…`), while a name with a subdirectory (e.g. `casos/<uuid>.txt`) is looked up directly. A bare name that matches two files is a usage error, never a guess |
| `--fixtures-root DIR` | Replace both fixture roots for this run |
| `--json` | Print the machine-readable payload instead of the human summary |
| `--out DIR` | Replace the whole output root for this run — for a subcommand that publishes nothing there is nothing to redirect |
| `--document-id ID` | Correlation identity recorded in the request; defaults to the input's file name |
| `--run-id ID` | Run identity recorded in the request; defaults to a tool-derived identity. On `llm.py` it also **pins** the run, which is what makes `resume` a resume |

---

## Input and output

**Fixture roots.** `tests/fixtures/` and `tests/fixtures-txt/` — the second one first for a text
input (`llm.py`). A name that is a real path is taken as given. A **directory** is refused by name
(`fixture 'pdf' is a directory, not a file: …`) and never searched for a file inside it — picking
one would be a silent choice — and an empty name is refused as a missing input rather than looked up
as the working directory. The **resolved absolute path** is printed in the run header, so a resolved
fixture is never silent. `tests/fixtures-txt/` mirrors `tests/fixtures/` by UUID:
`casos/<uuid>.pdf` sits next to `fixtures-txt/casos/<uuid>.txt`, the same case's extracted text.
The tools do **not** diff the two — comparing is a reading.

**Output root.** `var/tools/<tool>/<stem>-<hash8>/`, where `hash8` is the first eight characters
of the input's SHA-256. The same input therefore lands in the same directory and two inputs never
collide. Output is **never** written beside the input and never into `out/`; `/var/` is in
`.gitignore`. `--out` replaces the root entirely. A **batch** writes one level up instead —
`var/batch_<processor>/<walked folder>/…`, mirroring the tree it walked — in the shape
[Commands over a folder (batch)](#commands-over-a-folder-batch) describes.

Only a subcommand that **publishes** creates that directory. When the report *is* the stdout
summary — `pdf.py inspect`, `ocr.py text`, `workflow.py plan` and their peers, eighteen of the
sixty-four subcommands — the run writes no file at all, and its header states
`output: (none — this subcommand publishes no file)` instead of naming a directory no run creates.
That line is declared per tool (`REPORT_ONLY`) and checked twice: the glue test drives the
report-only subcommands and asserts the filesystem stayed empty, and `tests/test_lab_tools.py`
pins the declaration so a subcommand cannot move between the two sets unnoticed. A **batch tool's**
set is empty on purpose: the frame files a record for every input that produced a payload, so a
batch's run root always holds something.

**stdout** carries the human summary, or the `--json` payload. The run header goes to **stderr**
on purpose, so a `--json` body stays clean while the resolved input is still stated. The header
is the run's **one** statement of that input — it is also the only statement of it when the run
ends in a typed failure and no payload is printed at all — so the human summary does not repeat
it. The `--json` body keeps it, because a payload read on its own still has to name the file it
describes.

**The input is never modified.** That is a property the library tests guard and the hand run
re-checks by hashing every fixture before and after.

### Exit codes

| Code | When |
|---|---|
| `0` | The run produced a result. `partial`, `partial_success` and `PAUSED` are results |
| `1` | The library returned a typed failure — the record is printed, a traceback never is |
| `2` | A usage error: unknown subcommand, missing required flag, unresolvable input. `argparse`'s own code |

Nothing else. A failure the library already typed never reaches the operator as a crash.

---

## Commands over one file

One input per run: the input positional names a file (or `--fixture` names one), the run writes
under `var/tools/<tool>/<stem>-<hash8>/`, and the summary goes to stdout. Every subcommand calls a
symbol that exists in the library — nothing here reimplements anything: printing a result is a
tool's job, producing it is not.

### `pdf.py` — `SCR-02`

| Subcommand | Calls | Notes |
|---|---|---|
| `inspect` | `primitives.inspect_pdf` | page count, per-page geometry, engine report |
| `split` | `primitives.split_pdf` | one self-contained PDF per page |
| `render` | `primitives.render_page_to_image` | requires `--dpi`; `--page` picks one page |
| `text` | `primitives.extract_text_from_page` + `extract_layout_text_from_page` + `publish_text` | the page's native text, or every page's; publishes `page_NNN.txt` **and** `page_NNN_layout.txt` |
| `blocks` | `primitives.extract_text_from_page` | the same read, block view |
| `images` | `primitives.extract_images_from_page` | embedded images, under the page's own directory |
| `classify` | `primitives.composition.analyze_pdf_page` + `classify_pdf_page` | the `TEXT`/`IMAGE`/`MIXED` verdict, per page |
| `run` | `process_pdf`, or `process_pdf_page` with `--page` | the contract; `--dpi` required |

**Page scope.** `render`, `text`, `blocks`, `images` and `classify` are page-addressed: `--page N`
reads page N, and **omitting it reads every page of the document**, in order. A one-page document
is a scope of one — there is no second spelling for it, and no `--all-pages` flag. The scope a run
resolved to is stated in the payload, so an omitted flag is never silent, and the payload's shape
follows the scope that was asked for:

```json
{"input": "…", "scope": "page 2", "page": 2, "text": "…", "output": "…/page_002.txt",
 "layout_output": "…/page_002_layout.txt"}
{"input": "…", "scope": "all pages (3)", "pages": [{"page": 1, "text": "…", "output": "…"}, …],
 "status": "success", "errors": []}
```

`pages` is present exactly when the run covered every page, and a reader discriminates the two
shapes on `pages` versus `page`. A page that fails does not end the document: its typed record
joins `errors` with its page number, the pages that succeeded are still reported, and `status` is
`success`, `partial` or `failed`. `run` is not in that set — its `--page` switches to the
page-level contract, and its absence runs the whole document, which aggregates and publishes.

#### Why `text` publishes two files

Each page gets **two** text artifacts, because the two reads answer different questions and
neither is a superset of the other:

| Artifact (tool / `run`) | Read | Shape | Read it when |
|---|---|---|---|
| `page_NNN.txt` / `native_text/text.txt` | `pdftotext -tsv`, rebuilt word row by word row | reading order, one logical line per line, single spaces between words | you want the page *as text*: a consumer that walks it line by line, and the LLM stage |
| `page_NNN_layout.txt` / `native_text/text_layout.txt` | `pdftotext -layout` | the engine's own rendering: columns and horizontal spacing preserved | the page's **arrangement** is the information — tables, forms, label/value grids, invoice headers |

Both are named after the page, the way `render` names its PNG, so a scope of many pages never
collides. Measured on `tests/fixtures/casos/`: in the two-column footer of a bus ticket the
reconstruction keeps each column contiguous while `-layout` interleaves them line by line
(`o no, deberán cumplimentar…` printed above `El boleto es válido…`); in the same ticket's header
`-layout` keeps `Boleto:SUV-255671438-0` glued as the PDF has it and puts `Boleto:`, `Butaca:` and
`Salida:` on one visual line, which the reconstruction splits. On a fixture with no columns the two
are identical, down to the words.

**The second read is opt-in.** `layout=True` — the `run --layout` switch, and what `pdf.py text`
asks for — pays for the `-layout` call per page; `layout=False` makes neither the call nor the file
(a test asserts both). `text.txt` and `blocks.json` still come from **one** read: the layout
artifact is an addition *beside* them, never a replacement, so the pair that must agree about
reading order still does.

### `image.py` — `SCR-03`

| Subcommand | Calls | Notes |
|---|---|---|
| `info` | `primitives.load_image` + `get_image_metadata` + `get_image_dimensions` | file and pixel facts |
| `metrics` | `load_image` + `get_image_metadata` + `analyze_image` | quality, orientation, skew, regions |
| `normalize` | `primitives.prepare_normalized_image` | writes `normalized.png`, or `normalized.jpg` with `--quality` |
| `ocr-ready` | `primitives.prepare_image_for_ocr` | its own pipeline; never an alias of the next, and always lossless |
| `vlm-ready` | `primitives.prepare_image_for_vlm` | colour and layout preserved; `--quality` publishes it lossy |
| `classify` | `primitives.composition.classify_image` | over the metrics above |
| `run` | `process_image`, or `process_image_from_page` with `--from-page` | the contract |

There is **no `crop` subcommand**: the library has no `crop_region`
(`subplan-procesador-image.md` §9.6 defers it), and a tool may not invent one.

### `ocr.py` — `SCR-04`

| Subcommand | Calls | Notes |
|---|---|---|
| `run` | `process_ocr_image` | the contract |
| `text` | `primitives.extract_docling_text` | one conversion, one representation |
| `md` | `primitives.extract_docling_markdown` | as above |
| `json` | `primitives.build_ocr_document` | the structured document, serialized |
| `tables` | `primitives.extract_docling_tables` | in reading order |
| `blocks` | `primitives.extract_docling_blocks` + `composition.preserve_reading_order` | in reading order |
| `metrics` | `composition.analyze_ocr_result` | over the built document |

There is **no `--engine` flag**. The engine is fixed and never presented as a selectable option.
There is **no `diff` subcommand** either: comparing two extractions is a reading, and a tool that
compared them would be a second implementation of the thing under test.

### `llm.py` — `SCR-05`

`--provider` and `--model` are **required on every inference subcommand** (`call`, `node`,
`graph`, `resume`, `fake`; `models` and `tokens` need them too). A default model is exactly the
silent stand-in this project forbids — the check is a post-parse refusal, which is what makes the
"no default model" guard falsifiable.

| Subcommand | Calls | Notes |
|---|---|---|
| `call` | `process_llm_request` | one inference |
| `node` | `process_llm_node` | one node, against a fresh chain state |
| `graph` | `process_llm_request` with `default_inference_graph()` | the linear chain |
| `resume` | the same call again, with the same `--run-id` and `--out` | re-invocation **is** the resume; there is no `resume_llm_graph` symbol |
| `status` | `primitives.load_graph_state` / `load_result` | reads `state.json` and `final_result.json`; accepts `--out` alone |
| `models` | `primitives.list_models`, `get_model_info`, `check_model_available` | inventory only, no generation |
| `tokens` | `primitives.count_tokens`, `get_context_window` | offline count; the window comes from `--context-window` or the provider |
| `fake` | installs `tests/fakes/engines/fake_provider.py` at the provider seam | runs the chain twice under one pinned `--run-id`, so a graph and a resume are demonstrable with no model and no spent token |

`--assets-dir` defaults to the fixture asset root `tests/fixtures/llm/` (templates under
`template/`, schemas under `schema/`) and the resolved value is printed. The library itself has
**no** default for `metadata["assets_dir"]`.

### `workflow.py` — `SCR-06`

This tool is bound by the orchestrator's own frontier: it reaches the four processors only through
their public contracts and **imports no `docflow.*.primitives` module**.

| Subcommand | Calls | Notes |
|---|---|---|
| `run` | `process_document` | the whole documental workflow |
| `plan` | `process_document` with `dry_run` | returns the `ExecutionPlan`; invokes no processor, and needs no `--dry-run` (planning *is* the dry run) |
| `status` | `resume.load_resumable_context` | per-stage states of the last run |
| `context` | `persistence.read_json` on `configuration.state_path` | the durable `document_context.json` |
| `resume` | `resume_document` | `resume=True`, `reuse_successful=True` |
| `force` | `process_document` with `force_stages` | `--stages PDF,OCR` |
| `skip` | `process_document` with `skip_stages` | the same flag |
| `stop` | `process_document` with `stop_after_stage` | `--after PDF` |

The request must be **complete**: `options["output_dir"|"pdf"|"image"|"ocr"|"llm"]` and
`policies["allow_ocr"|"allow_vlm"]` are all required by the library, which refuses a missing key
**by name**. The tool supplies each from a flag and leaves a key the caller did not state
**absent** — so omitting `--pdf-dpi` (or `--allow-ocr`) produces the library's own
`CONFIGURATION_ERROR`, printed, with exit `1`. The tool never fills the gap.

`--fake-llm` installs the scripted provider at the LLM processor's seam, reached dynamically
(`importlib`), below the orchestrator's frontier — which is what lets a whole document run be
demonstrated with no model.

---

## Commands over a folder (batch)

The same commands over a corpus: the folder positional names a folder, and every file below it
that matches the tool's suffixes is an input. There are four of them, one per processor — the
orchestrator has no folder twin, because a document request is not a folder of files — and each is
the *same* method the per-file tool calls, dispatched through the same layer.

```bash
python scripts/tools/batch_pdf.py tests/fixtures/pdf        # the four committed samples
python scripts/tools/batch_pdf.py tests/fixtures            # the whole tree: 31 PDFs, eight folders
python scripts/tools/batch_image.py tests/fixtures/image    # four images, one of them corrupt
python scripts/tools/batch_ocr.py tests/fixtures/ocr        # two images, both converted
python scripts/tools/batch_llm.py --fake tests/fixtures-txt/casos call \
    --provider ollama --model llama3.1 --task extract --template simple_extract --schema simple
python scripts/tools/batch_pdf.py --no-recursive --out var/x tests/fixtures/matrix split
```

| Tool | Layer it dispatches through | Inputs it takes | Command with none stated | Commands it does not offer |
|---|---|---|---|---|
| `batch_pdf.py` `SCR-12` | `_pdf.py` | `.pdf` | `inspect` | — |
| `batch_image.py` `SCR-13` | `_image.py` | `.png .jpg .jpeg .tif .tiff .bmp` | `info` | — |
| `batch_ocr.py` `SCR-14` | `_ocr.py` | the image set: the OCR input *is* an image | `text` | — |
| `batch_llm.py` `SCR-15` | `_llm.py` | `.txt .md` | **none** — a command is required | `status`, `models`, `fake`, `resume` |

### The shape of a batch run

A batch command is the per-file command with a folder where the file was. The subcommand is
optional on three of the four tools — the run makes that tool's own default and **says so** — and
the flags after it are the ones the per-file tool registered for it, unchanged:

```bash
python scripts/tools/pdf.py inspect tests/fixtures/matrix/scan150.pdf   # one input
python scripts/tools/batch_pdf.py tests/fixtures/matrix                 # every PDF below it
python scripts/tools/pdf.py split tests/fixtures/matrix/scan150.pdf
python scripts/tools/batch_pdf.py tests/fixtures/matrix split           # the stated command, per input
```

The mirror is the walk, folder for folder, plus one directory per input. The second command above,
over `tests/fixtures`, lands like this:

```text
tests/fixtures/pdf/pdf_sample_text.pdf  ->  var/batch_pdf/fixtures/pdf/pdf_sample_text/inspect.json
tests/fixtures/chicos/<uuid>.pdf        ->  var/batch_pdf/fixtures/chicos/<uuid>/inspect.json
tests/fixtures/matrix/scan150.pdf       ->  var/batch_pdf/fixtures/matrix/scan150/inspect.json
```

Every rule below belongs to `_batch.py` — the folder frame all four tools run on — and not to one
tool:

- **The folder is walked recursively by default** (`--no-recursive` for the top level only), and
  only the tool's own suffixes are inputs, matched case-insensitively. The walk **skips the run's
  own output root**, so a second run over the same tree does not pick up what the first one wrote.
- **Every input gets its own directory**: `var/batch_<processor>/<walked folder>/<the input's
  folder relative to it>/<the input's stem>/`, which is what keeps two files of one folder from
  colliding. `--out DIR` replaces that root entirely; the walked folder is then not repeated.
- **Every input that produced a payload gets a record, named after its command**: `<command>.json`
  in that directory, beside whatever the method published. Two commands over one input keep both
  records — `inspect.json` beside `classify.json` — instead of the second overwriting the first.
  A page-addressed command's record holds one page's keys when `--page` was stated and a `pages`
  list when it was not. And a method that publishes no artifact at all — `inspect`, `info`, `text`,
  `tokens` — still leaves something to read, which is the point of running it over a corpus. An
  input whose failure **raised** has no payload and is reported, not filed: its typed record is
  printed and counted, and its directory is never created.
- **A default command is stated, never silent.** With no subcommand the run makes the tool's own
  flag-free method — the one that publishes nothing, so a bare run cannot fill the tree — and the
  header says `command: inspect (default, none stated)`. A tool whose every command needs a flag
  has no such method and requires the command instead (`batch_llm.py`).
- **The line and the summary agree.** An input whose failure **raised** is printed as
  `name: FAILED`, with the library's typed record, and files nothing. An input whose contract
  *returned* a failed status — `run` contains its failures rather than raising them — is printed as
  `name: FAILED` too, files the payload it produced, and its own typed record is shown: reporting
  it as `ok` while the summary counts it as failed would be the run contradicting itself.
- **One bad file does not end the batch.** Each failure is printed and counted, and the run keeps
  going: the exit code is `1` when any input failed, `0` when none did, and `2` for a usage error.
- **A missing required flag is refused once, before the walk.** The frame takes the check from the
  layer, so `_pdf.py`'s `--dpi` — required by `render` and `run` — is a usage error (`2`) raised
  before the run states its header, not per input. A method only meets its own gap when there is an
  input to run it on, so an empty folder used to report `files: 0` and exit `0` for a command that
  could never have run. `--page` is no longer one of those: a page command that states none reads
  every page, so there is no gap to refuse. `_llm.py`'s inference flags are still refused per input
  (see `docs/plan/bitacora.md`).
- **A batch takes no `--fixture` and no identity flags**: its input is the folder positional, and
  something that is not a folder is refused by name (`'x.txt' is not a folder: …`). `--recursive`,
  `--out` and `--json` are the tool's global flags and belong before the subcommand, as
  everywhere else.

### `batch_pdf.py` — `SCR-12`

`pdf.py` over a corpus: the same eight methods, mirrored under `var/batch_pdf/<folder>/`. Both
tools dispatch through `_pdf`, so a method, its payload and its flags live in exactly one place and
the batch adds no behaviour of its own. The subcommand is optional and the flags after it are
`pdf.py`'s own — the batch adds the folder and nothing else: no new option and no default for one.

| Subcommand | Needs | Batch invocation |
|---|---|---|
| `inspect` | nothing | `batch_pdf.py tests/fixtures/matrix` (the default) |
| `split` | nothing | `batch_pdf.py tests/fixtures/matrix split` |
| `render` | `--dpi` | `batch_pdf.py tests/fixtures/matrix render --dpi 150` |
| `text`, `blocks`, `images`, `classify` | nothing | `batch_pdf.py tests/fixtures/matrix classify` |
| `run` | `--dpi`, plus the capabilities | `batch_pdf.py tests/fixtures/matrix run --dpi 200 --extract-text` |

A page-addressed command given no `--page` reads every page of every input, and the scope each
input resolved to is in that input's record (`scope`, and `pages` when it read them all).

What lands in the input's directory is that method's output, so `split` files its pages, `render`
its PNG and `run` the whole artifact tree, next to the `<command>.json` record every method
leaves. The bare
run makes `inspect` — the flag-free method that only reports; the other flag-free method, `split`,
writes, so it is never the thing a bare run does. `tests/fixtures/pdf` is the demonstration in one
line: four inputs, one of them the corrupt sample, `files: 4 · succeeded: 3 · failed: 1`, exit `1`.

### `batch_image.py` — `SCR-13`

`image.py` over a folder: the same seven methods, mirrored under `var/batch_image/<folder>/`, over
the image suffixes — `.png`, `.jpg`, `.jpeg`, `.tif`, `.tiff`, `.bmp`, matched
case-insensitively — so a folder holding PDFs beside images gives up only its images.

```bash
python scripts/tools/image.py info tests/fixtures/image/color_layout.png   # one input
python scripts/tools/batch_image.py tests/fixtures/image                   # every image below it
python scripts/tools/image.py classify tests/fixtures/image/skewed_text.png
python scripts/tools/batch_image.py tests/fixtures/image classify          # the stated method, per input
python scripts/tools/batch_image.py tests/fixtures/image normalize --quality 85   # lossy, at the factor stated
```

- **The bare run makes `info`**, the flag-free method that publishes nothing. Every other method
  here writes: `normalize`, `ocr-ready`, `vlm-ready` and `run` all publish, so none of them is a
  safe default.
- **`--quality N` publishes a lossy JPEG instead of a lossless PNG**, and the mirror then holds
  `normalized.jpg` / `vlm_ready.jpg`. `ocr-ready` has no such flag: that pipeline binarizes the
  page, and the binarized representation is always lossless. Without the flag nothing changes —
  the container is the caller's decision, and its absence is a decision too.
- **A record is filed per input that produced a payload**, beside whatever the method published:
  `classify` files a record and no artifact, `normalize` files both, and a failed input files
  nothing — its typed record is printed and counted.
- `tests/fixtures/image` is that demonstration in one line: four images, one of them the committed
  corrupt sample, so `files: 4 · succeeded: 3 · failed: 1` with a typed `DECODE_ERROR`, exit `1`.

### `batch_ocr.py` — `SCR-14`

`ocr.py` over a folder: the same seven methods, mirrored under `var/batch_ocr/<folder>/`. Its
inputs are the image suffixes, because the OCR processor's input *is* an image.

```bash
python scripts/tools/ocr.py text tests/fixtures/ocr/ocr_prepared_text_and_table.png  # one input
python scripts/tools/batch_ocr.py tests/fixtures/ocr                                # every image below it
python scripts/tools/ocr.py metrics tests/fixtures/ocr/ocr_blank.png
python scripts/tools/batch_ocr.py tests/fixtures/ocr metrics                        # the stated method, per input
```

- **The bare run makes `text`** — the flag-free method that publishes nothing. Only `run`
  publishes artifacts here; the other six methods leave a `<command>.json` and nothing else.
- **It is not cheap.** Every input is converted once by the engine, so a corpus of images costs
  what the engine costs; the default is safe for the output tree, not for the clock.
- **An input the engine refuses fails its own record and the walk continues** — that is the whole
  point of a corpus run. The typed failure is printed, counted and reflected in the exit code, and
  `text`, `md`, `json`, `tables`, `blocks` and `metrics` type the engine's own throw rather than
  letting it end the run at the first bad file.
- `tests/fixtures/ocr` is that demonstration in one line: two images, both converted,
  `files: 2 · succeeded: 2 · failed: 0`, exit `0`.

### `batch_llm.py` — `SCR-15`

`llm.py` over a folder: the same commands, mirrored under `var/batch_llm/<folder>/`, over `.txt`
and `.md` inputs.

```bash
python scripts/tools/batch_llm.py tests/fixtures-txt/casos tokens \
    --provider ollama --model llama3.1 --context-window 4096
python scripts/tools/batch_llm.py --fake tests/fixtures-txt/casos call \
    --provider ollama --model llama3.1 --task extract --template simple_extract --schema simple
python scripts/tools/batch_llm.py tests/fixtures-txt/casos call \
    --provider ollama --model llama3.1 --task extract --template simple_extract --schema simple
```

- **Four of the eight commands**, and precisely the four whose answer is a property of the input:
  `call`, `graph`, `node`, `tokens`. `status` asks about a *run directory*, `models` asks about a
  *model* and never reads the input, `fake` is a single-input demonstration, and `resume` pins one
  run identity — which a corpus can only give one input by giving it to all of them. Naming any of
  the four here is a usage error, not a silent no-op.
- **No default command.** The other batch tools make a flag-free method when the caller states
  none; this one has none to make, because `--provider` and `--model` are required on every command
  here as on `llm.py`. A bare run is refused, exit `2`.
- **`--fake` installs the committed scripted provider** — the same seam `llm.py fake` and
  `workflow.py --fake-llm` install — so a whole corpus of chains runs with no model served and no
  token spent. The refusal on a missing `--provider`/`--model` stands either way.
- **`--assets-dir`** is the same flag with the same default as `llm.py`, and the resolved value is
  stated in the run header, exactly as `llm.py` states it.
- The third command is the honest failure the bench exists for: nothing is served on this machine,
  so **every** input returns a typed `MODEL_UNAVAILABLE` — each printed as `name: FAILED` with its
  own record, `files: 3 · succeeded: 0 · failed: 3`, exit `1`. The second, with `--fake`, is the
  same three inputs and `SUCCESS`.

---

## The boundaries

Three hold for every tool, and `tests/test_lab_tools.py` asserts them rather than trusting them:

1. **Calls, never reimplements.** `pdf.py split` calls `split_pdf`; it does not shell out to a
   PDF binary. A tool's source may not name an engine binary, an engine module or a provider SDK.
2. **The library never imports a tool.** Nothing under `src/docflow/` mentions `scripts` or `var`,
   and nothing there imports `tests/`.
3. **No new seam.** A tool adds no contract, no options type and no behaviour the library lacks —
   and no default engine, provider, model, DPI or threshold. A missing operation is a gap in the
   *processor*, fixed there.

One deliberate exception: **`pdf.py`, `image.py` and `ocr.py` may drive one named primitive of
their own processor.** That is what a bench is for — `render --dpi 400` drives
`render_page_to_image` without a whole document run, which the orchestrator is forbidden to do.
**`workflow.py` is excluded**: it carries the orchestrator's own prohibition.

## Working without an engine or a model

The bench is most useful when something is missing, and a missing engine is a recorded fact, not
a defect:

- **No engine installed** → the library returns a typed failure, the tool prints it and exits `1`.
- **No model served** → `llm.py` returns a typed `MODEL_UNAVAILABLE` (the local endpoint answering
  `404`), and `workflow.py` reports its stage as failed.
- **Neither, but you still want to see the chain** → `llm.py fake`, `workflow.py --fake-llm` and
  `batch_llm.py --fake` install the committed scripted provider, so a graph, its node reuse, a
  resume, and a whole corpus of chains are demonstrable with no network and no token spent. The
  three install the same seam, and the refusal on a missing `--provider`/`--model` stands either
  way.

## Gates

`scripts/` is covered by the two Ruff gates, which read the whole tree:

```bash
ruff check .              # lint, import order included
ruff format --check .     # formatting
```

It is deliberately **outside** `pylint src tests`, whose scope stays the library and its tests: a
tool is a disposable caller, and widening the gate is a plan revision rather than a config edit.

The structural guards and the glue tests live in `tests/test_lab_tools.py` and run inside
`pytest`, so the boundaries above are enforced by the same gate as the library.

## Known limitation

`image.py normalize`, `image.py ocr-ready`, `image.py vlm-ready`, their `batch_image.py` peers and
any `workflow.py` run that prepares an image **cannot publish an artifact with the real engine**:
the processor's atomic publication writes through a `.tmp` sibling, and OpenCV infers its encoder
from the file extension, so it refuses that name. The run reports a typed `WRITE_ERROR` and exits
`1` instead of crashing — per input, for a batch, so the rest of the corpus still runs. The defect
is in the processor, is registered with an owner in
[`docs/plan/bitacora.md`](../../docs/plan/bitacora.md) (2026-09-27), and is deliberately not
patched from here.

---

The design and its decisions are [`docs/plan/subplan-scripts.md`](../../docs/plan/subplan-scripts.md);
the task-level decomposition is [`docs/plan/issues/wbs-scripts.md`](../../docs/plan/issues/wbs-scripts.md);
the commands run by hand and what they printed are in
[`docs/plan/bitacora.md`](../../docs/plan/bitacora.md).
