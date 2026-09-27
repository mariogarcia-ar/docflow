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
| `_pdf.py` | the PDF bench's **command layer**: the eight methods, their payloads and their flags. Not a tool — `pdf.py` and `batch_pdf.py` both call it, so neither owns a second copy |
| `pdf.py` | `SCR-02` — the PDF processor's primitives and its contract, one file per run |
| `batch_pdf.py` | `SCR-12` — the same eight methods over every PDF below a folder, one record per input |
| `image.py` | `SCR-03` — the image processor's pipelines and its contract |
| `ocr.py` | `SCR-04` — the OCR processor's representations and its contract |
| `llm.py` | `SCR-05` — one inference, the chain, the inventory and the scripted provider |
| `workflow.py` | `SCR-06` — the orchestrator: plan, run, resume, force, skip, stop |

A tool owns its subcommands, its flags and one handler per subcommand. Everything else — where a
run writes, how an input resolves, the header, the printers, the exit code — comes from `_cli`,
and the PDF bench's eight methods come from `_pdf`. Adding a tool for a sixth processor means
writing its parser and its handlers, and nothing else.

The set of **modules** here is asserted by `tests/test_lab_tools.py` guard 1: `_cli.py`, `_pdf.py`
and the six tools, and no other `.py` file. `subplan-scripts.md` §3.1 fixed it at `_cli.py` plus
five tools; `batch_pdf.py` and the shared layer that keeps it from duplicating `pdf.py` are the
`SCR-11`/`SCR-12` plan revision that followed, and a seventh tool is the next one, not a surprise.

---

## Invocation

```bash
python scripts/tools/pdf.py inspect tests/fixtures/pdf/pdf_sample_mixed.pdf
python scripts/tools/pdf.py --fixture pdf_sample_mixed.pdf render --page 1 --dpi 300
python scripts/tools/batch_pdf.py tests/fixtures/pdf     # inspect, over every PDF below the folder
python scripts/tools/workflow.py --allow-ocr --no-allow-vlm \
    --pdf-dpi 150 --image-normalize --ocr \
    --task extract --provider ollama --model llama3.1 --template simple_extract \
    plan tests/fixtures/pdf/pdf_sample_text.pdf
python scripts/tools/llm.py --fixture casos/66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.txt \
    call --provider ollama --model llama3.1 --task extract \
    --template simple_extract --schema simple
```

Every line above runs as written against the committed fixtures. The `render` line shows the two
spellings at once — `--fixture` before the subcommand, `--page`/`--dpi` after it — and the batch
line is `tests/fixtures/pdf`'s four PDFs, three written and one reported as the corrupt file it
is (exit `1`). The `plan` line carries a **complete** workflow request,
because the library refuses a missing option key by name; `plan` needs no `--dry-run`, since
planning *is* the dry run. The `call` line is the honest failure the bench exists for: no model is
served on this machine, so it prints a typed `MODEL_UNAVAILABLE` and exits `1`.

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
`.gitignore`. `--out` replaces the root entirely.

Only a subcommand that **publishes** creates that directory. When the report *is* the stdout
summary — `pdf.py inspect`, `ocr.py text`, `workflow.py plan` and their peers, nineteen of the
thirty-eight subcommands — the run writes no file at all, and its header states
`output: (none — this subcommand publishes no file)` instead of naming a directory no run creates.
That line is declared per tool (`REPORT_ONLY`) and checked twice: the glue test drives the
report-only subcommands and asserts the filesystem stayed empty, and `tests/test_lab_tools.py`
pins the declaration so a subcommand cannot move between the two sets unnoticed.

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

## What each tool exposes

Every subcommand calls a symbol that exists in the library. Nothing here reimplements anything:
printing a result is a tool's job, producing it is not.

### `pdf.py` — `SCR-02`

| Subcommand | Calls | Notes |
|---|---|---|
| `inspect` | `primitives.inspect_pdf` | page count, per-page geometry, engine report |
| `split` | `primitives.split_pdf` | one self-contained PDF per page |
| `render` | `primitives.render_page_to_image` | requires `--page` and `--dpi` |
| `text` | `primitives.extract_text_from_page` | the page's native text |
| `blocks` | `primitives.extract_text_from_page` | the same read, block view |
| `images` | `primitives.extract_images_from_page` | embedded images |
| `classify` | `primitives.composition.analyze_pdf_page` + `classify_pdf_page` | the `TEXT`/`IMAGE`/`MIXED` verdict |
| `run` | `process_pdf`, or `process_pdf_page` with `--page` | the contract; `--dpi` required |

### `batch_pdf.py` — `SCR-12`

`pdf.py` over a corpus: the same eight methods, run over every PDF under a folder, with the tree
mirrored under `var/batch_pdf/<folder>/`. Both tools dispatch through `_pdf`, so a method, its
payload and its flags live in exactly one place and the batch adds no behaviour of its own.

```bash
python scripts/tools/batch_pdf.py tests/fixtures/pdf        # the four committed samples
python scripts/tools/batch_pdf.py tests/fixtures            # the whole tree: 31 PDFs, eight folders
python scripts/tools/batch_pdf.py tests/fixtures/chicos run --dpi 200 --extract-text
python scripts/tools/batch_pdf.py --no-recursive --out var/x tests/fixtures/matrix split
```

The batch command is `pdf.py`'s command with a folder where the file was. The subcommand is
optional — the run makes `inspect` when none is stated, and says so — and the flags after it are
the ones `pdf.py` registered for it:

```bash
python scripts/tools/pdf.py inspect tests/fixtures/matrix/scan150.pdf   # one input
python scripts/tools/batch_pdf.py tests/fixtures/matrix                 # every PDF below it
python scripts/tools/pdf.py split tests/fixtures/matrix/scan150.pdf
python scripts/tools/batch_pdf.py tests/fixtures/matrix split           # the stated command, per input
```

The mirror is the walk, folder for folder, plus one directory per input. The second command above,
over `tests/fixtures`, lands like this:

```text
tests/fixtures/pdf/pdf_sample_text.pdf  ->  var/batch_pdf/fixtures/pdf/pdf_sample_text/result.json
tests/fixtures/chicos/<uuid>.pdf        ->  var/batch_pdf/fixtures/chicos/<uuid>/result.json
tests/fixtures/matrix/scan150.pdf       ->  var/batch_pdf/fixtures/matrix/scan150/result.json
```

With `--out var/x` the walked folder is not repeated: `var/x/scan150/…`.

| Subcommand | What it does |
|---|---|
| the eight of `pdf.py` | the same method, once per input, in the order the inputs were found |

- **The folder is walked recursively by default** (`--no-recursive` for the top level only), and
  only `.pdf` files are inputs, matched case-insensitively. The walk **skips the run's own output
  root**, so a second run over the same tree does not pick up the pages the first one wrote.
- **Every input gets its own directory**: `<root>/<the input's folder relative to the walked
  folder>/<the input's stem>/`, which is what keeps two PDFs in one folder from colliding.
- **Every input that produced a payload gets a record**: it is written to `result.json` in that
  directory, beside whatever the method published. So `inspect` — which publishes no artifact at
  all (`pdf.py`'s report-only set) — still leaves something to read, which is the point of running
  it over a corpus. A failed input has no payload and is reported, not filed: its typed record is
  printed and counted, and its directory is never created.
- **The command is stated, never guessed.** With no subcommand the run makes `inspect`, the one
  method that needs no further flag, and the header says `command: inspect (default, none
  stated)`.
- **One bad file does not end the batch.** Each failure is printed as the library's typed record
  and counted, and the run keeps going: the exit code is `1` when any input failed, `0` when none
  did, and `2` for a usage error. `tests/fixtures/pdf` is that demonstration in one line — four
  inputs, one of them the corrupt sample: `files: 4 · succeeded: 3 · failed: 1`, exit `1`.
- **`--out DIR`** replaces `var/batch_pdf/<folder>/` entirely; the mirror is then `DIR/<relative
  folders>/<stem>/`. `--recursive`, `--out` and `--json` are the tool's global flags and belong
  before the subcommand, as everywhere else.

### `image.py` — `SCR-03`

| Subcommand | Calls | Notes |
|---|---|---|
| `info` | `primitives.load_image` + `get_image_metadata` + `get_image_dimensions` | file and pixel facts |
| `metrics` | `load_image` + `get_image_metadata` + `analyze_image` | quality, orientation, skew, regions |
| `normalize` | `primitives.prepare_normalized_image` | writes `normalized.png` |
| `ocr-ready` | `primitives.prepare_image_for_ocr` | its own pipeline; never an alias of the next |
| `vlm-ready` | `primitives.prepare_image_for_vlm` | colour and layout preserved |
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
- **Neither, but you still want to see the chain** → `llm.py fake` and `workflow.py --fake-llm`
  install the committed scripted provider, so a graph, its node reuse and a resume are
  demonstrable with no network and no token spent.

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

`image.py normalize`, `image.py ocr-ready`, `image.py vlm-ready` and any `workflow.py` run that
prepares an image **cannot publish an artifact with the real engine**: the processor's atomic
publication writes through a `.tmp` sibling, and OpenCV infers its encoder from the file
extension, so it refuses that name. The run reports a typed `WRITE_ERROR` and exits `1` instead of
crashing. The defect is in the processor, is registered with an owner in
[`docs/plan/bitacora.md`](../../docs/plan/bitacora.md) (2026-09-27), and is deliberately not
patched from here.

---

The design and its decisions are [`docs/plan/subplan-scripts.md`](../../docs/plan/subplan-scripts.md);
the task-level decomposition is [`docs/plan/issues/wbs-scripts.md`](../../docs/plan/issues/wbs-scripts.md);
the commands run by hand and what they printed are in
[`docs/plan/bitacora.md`](../../docs/plan/bitacora.md).
