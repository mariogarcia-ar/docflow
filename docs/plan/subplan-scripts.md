# Subplan — lab tools (`scripts/tools/`)

## 1. Objective

Ship **five thin operator CLIs**, one per processor plus the orchestrator, that exercise the
finished library by hand against the committed fixtures under `tests/fixtures/` and
`tests/fixtures-txt/`:

| Tool | Task | Exposes |
|---|---|---|
| `scripts/tools/pdf.py` | `SCR-02` | `inspect`, `split`, `render`, `text`, `blocks`, `images`, `classify`, `run` |
| `scripts/tools/image.py` | `SCR-03` | `info`, `metrics`, `normalize`, `ocr-ready`, `vlm-ready`, `classify`, `run` |
| `scripts/tools/ocr.py` | `SCR-04` | `run`, `text`, `mixed`, `md`, `json`, `tables`, `blocks`, `metrics` |
| `scripts/tools/llm.py` | `SCR-05` | `call`, `node`, `graph`, `resume`, `status`, `models`, `tokens`, `fake` |
| `scripts/tools/workflow.py` | `SCR-06` | `run`, `plan`, `status`, `resume`, `force`, `skip`, `stop`, `context` |

The deliverable is a **caller**, not a component: each tool parses arguments, builds a real
contract object, calls the library's public entry point (or one named primitive, on the lab
bench) and prints what came back. It adds **no** contract, no option type, no transformation
and no default. Deleting `scripts/` leaves the library and its tests untouched — that is the
property `SCR-08` asserts, and it is the whole reason these files may import a processor's
internals at all.

**Why a tool and not a test.** The suite proves *our* code against in-memory doubles and, by
rule, never reaches an engine (`docs/plan/README.md` §9.7). A tool is the only surface where a
human runs the **real** seam — Poppler on a real PDF, OpenCV on a real scan, Docling on a real
page, a provider on a real prompt — and sees whether the engine's actual shape still matches
what our translation expects. That is a bench observation, not evidence, and it is never
recorded as a gate.

## 2. Context (BA)

**Who runs them.** The developer at the bench, following a runbook, while a processor is
being built or after an engine pin bump. Also the person who needs one artifact — a page
render at `--dpi 400`, a page's blocks, one OCR pass — without driving a whole document run.

**What a tool may do**

- read the fixture trees and resolve a bare fixture name to a path;
- build any contract object the library exposes, from explicit flags;
- call one public entry point per invocation;
- call a named primitive **of its own processor** (the lab-bench asymmetry, §3.2);
- print results and paths, and write under `var/tools/`;
- report a typed failure and exit non-zero.

**What a tool must NOT do**

- implement a transformation, a validation, a retry, a cache or a fallback — a missing
  operation is a gap in the **processor**, fixed there (`SCR-08` asserts the boundary);
- substitute a default engine, provider, model, DPI or threshold for a flag the caller did
  not pass — `llm.py` and `workflow.py` **require** `--provider` and `--model`;
- become a second product surface: there is no `docflow` product CLI in this plan, the tools
  are not packaged, and no console script is added (`resolve-decision` 11);
- be imported by anything under `src/docflow/` — the frontier is one-directional and is
  asserted, not promised.

**Boundary with `.github/copilot-instructions.md`.** That file describes a `docflow-kernel`
console entry point and a `src/docflow/kernel_cli/` package. `docs/plan/README.md` §9.1
resolved the layout as five processors with no `kernels`/`ports`/`adapters`, so the
"lab bench" it describes **is** `scripts/tools/`, invoked as `python scripts/tools/<name>.py`.
The instruction file is stale on that point and is registered in §9.

## 3. Design (SA)

### 3.1 Layout

```
scripts/tools/
├── _cli.py         shared plumbing: NOT a tool, holds no contract and reaches no engine
├── _batch.py       the folder frame every batch tool runs on (SCR-12) — also not a tool
├── _pdf.py         the PDF bench's command layer, shared by pdf.py and batch_pdf.py (SCR-11)
├── _image.py       the image bench's command layer (SCR-13)
├── _ocr.py         the OCR bench's command layer (SCR-14)
├── _llm.py         the LLM bench's command layer (SCR-15)
├── pdf.py          SCR-02
├── batch_pdf.py    SCR-12
├── image.py        SCR-03
├── batch_image.py  SCR-13
├── ocr.py          SCR-04
├── batch_ocr.py    SCR-14
├── llm.py          SCR-05
├── batch_llm.py    SCR-15
└── workflow.py     SCR-06
```

`_cli.py` is justified by the five callers rule this repository already applies to
`utils/`/`helpers/`: a symbol belongs in a shared module only when more than one caller needs
it, and here every tool does. It holds **only** the plumbing that would otherwise be
copy-pasted fifteen times — output-root resolution, fixture resolution, the `--json` printer,
the human printer, and the exit-code mapping. It is not a seam: it imports no engine, no
provider and no contract, and nothing under `src/` may import it.

**The layer split (`SCR-11`, `SCR-13`, `SCR-14`, `SCR-15`).** Each of the four processors is
served by *two* tools — one file, one folder — and both call the same methods. The methods
therefore live in a `_`-prefixed layer beside them: `_pdf.py`'s eight, `_image.py`'s, `_ocr.py`'s
and `_llm.py`'s. A layer registers the flags (`build_subcommands`) and holds the methods
(`COMMANDS`); it has no `main`, prints nothing, is never invoked, and raises the processor's typed
failures rather than printing them. This is the five-callers rule one step further: the same eight
methods have two callers, and the alternative — the batch tool importing its single-file twin, or
a second copy of every payload in it — is exactly the drift the guards exist to catch.

**`_batch.py` (`SCR-12`)** is the folder frame, shared by all four batch tools: the walk, the
mirror (`<root>/<relative folders>/<stem>/`), the per-input `<command>.json`, the line each input
prints, the summary and the exit code. It names no processor, so a sixth batch tool is a suffix
set, a layer and a command — and nothing else.

Filename convention: a tool is `<name>.py` with a lowercase name; a leading underscore marks
a module that is not a tool. The guard test enumerates the set, so a sixteenth module is a plan
revision and not a surprise.

### 3.2 The three boundaries (and the one deliberate exception)

1. **Calls, never reimplements.** `pdf.py split` calls `split_pdf`; it does not shell out to
   `pdfseparate`. Printing a result is a tool's job; producing it is not.
2. **The library never imports a tool.** Nothing under `src/docflow/` references `scripts/`
   or `var/`. Asserted by AST, not by habit.
3. **No new seam.** A tool adds no contract, no options type and no behaviour the library
   lacks. If a subcommand needs something the processor cannot do, the tool is wrong, or the
   processor has a gap.

**The exception — the lab bench.** `_pdf.py`, `_image.py`, `_ocr.py` and `_llm.py` **may** import
their own processor's `primitives/` and drive one named primitive. That is what a bench is for:
`render --dpi 400` drives `render_page_to_image` without a document run, which the orchestrator is
forbidden to do. The exception sits on the **layer**, not on the tool: after `SCR-11`…`SCR-15` each
single-file tool imports only `_cli` and its own layer, so the tool's source names no primitive
either — a stronger position than the one this subplan was frozen with, and the same one, since the
layer is what does the driving. **`workflow.py` is excluded from the exception**: it is bound by the
same prohibition the orchestrator is, and reaches the four processors only through their public
contracts. `_batch.py` and `_cli.py` are not covered by the exception at all: neither reaches a
primitive, and neither may.

### 3.3 Invocation, output and exit codes

```bash
python scripts/tools/pdf.py inspect tests/fixtures/pdf/pdf_sample_mixed.pdf
python scripts/tools/pdf.py --fixture pdf_sample_mixed.pdf render --page 1 --dpi 300
python scripts/tools/batch_pdf.py tests/fixtures/pdf            # inspect, over every PDF below it
python scripts/tools/batch_llm.py --fake tests/fixtures-txt/casos call \
    --provider ollama --model llama3.1 --task extract --template simple_extract --schema simple
python scripts/tools/workflow.py plan tests/fixtures/pdf/pdf_sample_text.pdf --dry-run
python scripts/tools/llm.py --fixture casos/66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.txt \
    call --provider ollama --model llama3.1 --task extract \
    --template simple_extract --schema simple
```

- **Output root:** `var/tools/<tool>/<input-stem>-<hash8>/`, where `hash8` is the first eight
  characters of the input's SHA-256. The same input therefore lands in the same directory —
  a run can be repeated and compared, and no two inputs collide. `--out <dir>` replaces the
  root; output is **never** written beside the input and never into `out/`. `/var/` is
  already in `.gitignore`.
- **Batch output root (`SCR-12`):** `var/batch_<processor>/<walked-folder>/`, mirrored folder for
  folder plus one directory per input, so two PDFs in one folder cannot collide. The walk skips
the run's own root, so a second run over the same tree does not pick up what the first one wrote.
- **Fixture roots:** `tests/fixtures/` and `tests/fixtures-txt/` (the second for text inputs).
  `--fixture <name>` resolves a bare name or a name with a subdirectory; a **path** is taken
  as given. The resolved absolute path is printed in the run header, so a resolved fixture is
  never silent, and `--fixtures-root` relocates the search when the tree moves. A batch tool
  takes no `--fixture`: its input is the folder positional, and a folder that is not one is a
  usage error.
- **Page scope (`PAG-01`…`PAG-07`):** `render`, `text`, `blocks`, `images` and `classify` are
  page-addressed. A stated `--page` reads that page; **omitting it reads every page of the
  document**, in order, and a one-page document needs no branch. The scope a run resolved to is
  stated in the payload (`scope`, plus `pages` when every page was read), so an omitted flag is
  never silent and the payload's shape follows the scope that was asked for. A page that fails
  does not end the document: its typed record joins `errors` and the other pages are still
  reported. `run` is not in that set — its `--page` switches to the page-level contract and its
  absence runs the whole document. The full design is [`subplan-paginas.md`](subplan-paginas.md).
- **stdout** carries the human summary; `--json` prints the machine-readable payload instead
  (built from the result's own fields, not a second serialization of the library's state).
- **Exit codes:** `0` the run produced a result and its `status` is a success; `1` the library
  returned a typed failure (`status != success`, or `DocumentResult.status == FAILED`) — the
  typed error records are printed, the tool does not raise; `2` a usage error (unknown
  subcommand, missing required flag, unresolvable input), which is `argparse`'s own code.
  Nothing else, and never a traceback for a failure the library already typed. A **batch** run
  exits `1` when *any* input failed and `0` when none did: one bad file does not end the corpus,
  and an input whose failure the contract *returned* rather than raised is counted, printed and
  filed with its own status instead of being reported as `ok`.

### 3.4 Subcommand → symbol map (the whole contract of each tool)

Every row names a symbol that exists today. A row with no symbol would not be a subcommand.

**`pdf.py`** — public entry points plus the processor's own primitives:

| Subcommand | Calls | Notes |
|---|---|---|
| `inspect` | `pdf.primitives.inspect_pdf` | pages, geometry, encryption |
| `split` | `pdf.primitives.split_pdf` | one file per page |
| `render` | `pdf.primitives.render_page_to_image` | `--dpi`; `--page` picks one page, its absence every page |
| `text` | `pdf.primitives.extract_text_from_page` | the page's native text, or every page's |
| `blocks` | `pdf.primitives.extract_text_from_page` | same call, `--blocks` view; text and blocks come from **one** read |
| `images` | `pdf.primitives.extract_images_from_page` | embedded images; one page writes `images/`, every page writes `page_NNN/images/` |
| `classify` | `pdf.primitives.composition.analyze_pdf_page` + `classify_pdf_page` | the page's `TEXT`/`IMAGE`/`MIXED` verdict, or every page's |
| `run` | `pdf.process_pdf` | the contract; `--page` adds `process_pdf_page` |

**`image.py`** — same shape; `crop` is **not** here (§9, decision 8):

| Subcommand | Calls | Notes |
|---|---|---|
| `info` | `image.primitives.get_image_metadata` + `get_image_dimensions` | no pixels decoded |
| `metrics` | `image.primitives.load_image` + `analyze_image` | the technical analysis |
| `normalize` | `image.primitives.prepare_normalized_image` | `normalized.png`, or `normalized.jpg` with `--quality` |
| `ocr-ready` | `image.primitives.prepare_image_for_ocr` | its own pipeline; always lossless |
| `vlm-ready` | `image.primitives.prepare_image_for_vlm` | distinct from `ocr-ready`, never an alias; `--quality` publishes it lossy |
| `classify` | `image.primitives.composition.classify_image` | over the metrics above |
| `run` | `image.process_image` | the contract; `--from-page` adds `process_image_from_page` |

**`ocr.py`** — no `--engine` flag: Docling is fixed and never user-selectable:

| Subcommand | Calls | Notes |
|---|---|---|
| `run` | `ocr.process_ocr_image` | the contract |
| `text` | `ocr.primitives.extract_docling_text` + `normalize_ocr_text` | one representation, **published** as `text.txt` (§9, decision 19) |
| `mixed` | `ocr.primitives.composition.render_reading` | the page's **rows**: items that share a line are one line, a table carried as its Markdown in place, nothing joined across rows; **published** as `mixed.txt` (§9, decision 20) |
| `md` / `json` | `ocr.primitives.extract_docling_markdown` / `build_ocr_document` | one representation each, no artifact |
| `tables` | `ocr.primitives.extract_docling_tables` | table markdown and cells |
| `blocks` | `ocr.primitives.extract_docling_blocks` + `ocr.primitives.composition.preserve_reading_order` | in reading order |
| `metrics` | `ocr.primitives.composition.analyze_ocr_result` | over the built document |

**`llm.py`** — `--provider` and `--model` are **required on every inference subcommand**; a
default model is the silent stand-in this project forbids:

| Subcommand | Calls | Notes |
|---|---|---|
| `call` | `llm.process_llm_request` | one inference |
| `node` | `llm.process_llm_node` | one node of the graph |
| `graph` | `llm.process_llm_request` with `graph` set, or `execute_llm_graph` | the linear chain |
| `resume` | `llm.process_llm_request` again, same `--run-id` and `--out` | the processor reuses a node whose `request_key` matches; re-invocation **is** the resume — there is no `resume_llm_graph` symbol to call |
| `status` | `llm.primitives.load_graph_state` / `load_result` | reads `state.json` / `final_result.json` |
| `models` | `llm.primitives.list_models`, `get_model_info`, `check_model_available` | inventory only, no generation |
| `tokens` | `llm.primitives.count_tokens`, `get_context_window` | offline count; the window from the caller's `options["context_window"]` or the provider |
| `fake` | installs `tests/fakes/engines/fake_provider.py` at `docflow.llm.primitives` | first-class, not a hidden test flag: the scripted provider is what makes the graph and resume paths demonstrable with no model and no spent token |

`--assets-dir` defaults to the fixture asset root `tests/fixtures/llm/` (templates and
schemas) and the resolved value is printed; the library itself has **no** default for
`metadata["assets_dir"]` and this tool does not invent one for the library, it states the
bench's own root.

`--stream` is a *control option* on every inference subcommand, the batch tool included: it joins
`options`, the processor reads it into the call, and the deltas are echoed to stderr under a
`[thinking]` / `[content]` header while stdout stays the payload. The body the run records is the
one a waiting call would have received, so the switch stays out of `request_key`. `call` also files
the two step artifacts — `<stem>.json`, the answer alone, and `<stem>_full.json`, the whole run —
named after the schema's last path component or `--name`, and published through the library's
atomic writer.

*(The streaming switch and the two step artifacts were added in the second pass of 2026-10-03:
`docs/plan/issues/wbs-procesador-llm-call.md` §12.)*

**`workflow.py`** — reaches the four processors only through their public contracts:

| Subcommand | Calls | Notes |
|---|---|---|
| `run` | `workflow.process_document` | the whole documental workflow |
| `plan` | `workflow.process_document` with `dry_run=True` | the `ExecutionPlan`; invokes no processor |
| `status` | `workflow.resume.load_resumable_context` | per-stage states of the last run |
| `context` | `workflow.persistence.read_json` on `workflow.configuration.state_path` | the durable `document_context.json` |
| `resume` | `workflow.resume_document` | `resume=True`, `reuse_successful=True` |
| `force` | `workflow.process_document` with `force_stages` | `--stages PDF,OCR` |
| `skip` | `workflow.process_document` with `skip_stages` | same flag |
| `stop` | `workflow.process_document` with `stop_after_stage` | `--after PDF` |
| `--fake-llm` | installs the scripted provider at `docflow.llm.primitives` | lets a full document run be demonstrated with no model; it patches the **processor's own seam**, below the orchestrator's frontier, so the tool still never touches a `primitives/` module |

`run` must build a complete `DocumentRequest`: `options["output_dir"|"pdf"|"image"|"ocr"|"llm"]`
and `policies["allow_ocr"|"allow_vlm"]` are all required by the library, which refuses a
missing key **by name**. The tool surfaces that refusal as a printed
`CONFIGURATION_ERROR` and exit `1`; it does not fill the gap.

**The four batch tools (`SCR-12`…`SCR-15`)** — the same commands over every matching file below a
folder, dispatching through the same layers:

| Tool | Layer | Inputs it takes | Command when none is stated | Commands it does **not** offer |
|---|---|---|---|---|
| `batch_pdf.py` | `_pdf.py` | `.pdf` | `inspect` — flag-free, publishes nothing | — |
| `batch_image.py` | `_image.py` | `.png .jpg .jpeg .tif .tiff .bmp` | `info` — flag-free, publishes nothing | — |
| `batch_ocr.py` | `_ocr.py` | the image set, because the OCR processor's input *is* an image | `text` — flag-free, publishes the reading it reports as `text.txt` | — |
| `batch_llm.py` | `_llm.py` | `.txt .md` | **none** — a subcommand is required | `status`, `models`, `fake`, `resume` |

The four rules the batch tools share:

1. **A default is stated, never silent.** `inspect`, `info` and `text` are the flag-free methods a
   batch tool makes when it has one; the header says `command: <name> (default, none stated)`. A
   bare run publishes at most the reading it reports — `text` writes one `text.txt` per input, the
   text its own record states, normalized the way the processor publishes it — and never a render,
   a split, an extracted image or a contract's document; `inspect` and `info` publish nothing at
   all. The frame takes that fact from the tool rather than reading it back off the parsed
   arguments, and the default command is *parsed as a subcommand*, so a bare run and a stated one
   are the same run — its flags included.
2. **`batch_llm.py` has no default**, because it has no flag-free command to make: `--provider`
   and `--model` are required on every one of its commands, exactly as on `llm.py`. A bare run is
   refused with exit `2`.
3. **The subset is a decision, not an omission.** `status` asks about a *run directory*, `models`
   asks about a *model* and never reads the input, `fake` is a single-input demonstration, and
   `resume` pins one run identity — which a corpus cannot give one input without giving it to all
   of them. The four that remain are the ones whose answer is a property of the input. A command
   left out is not registered, so naming it is a usage error rather than a silent no-op.
4. **`--fake` on `batch_llm.py`** installs the same committed scripted provider as `llm.py fake`
   and `workflow.py --fake-llm`, so a whole corpus of chains is demonstrable with no model served
   and no token spent. It patches the provider seam and nothing above it.

A batch tool does not re-declare a payload, a flag or an artifact path: a method's payload lives in
its layer, and the frame files it as `<command>.json` beside whatever the method published.

### 3.5 The fixture map (what the bench actually runs on)

| Tool | Roots and cases |
|---|---|
| `pdf.py` | `tests/fixtures/pdf/pdf_sample_{text,image,mixed}.pdf` (the three classifications); `tests/fixtures/pdf/pdf_corrupt.pdf` (typed failure); `tests/fixtures/pdf_aptos_layout/*.pdf` (real layout); `tests/fixtures/pdf_escaneados/*.pdf` (no text layer); `tests/fixtures/pdf_large/MetodoCITRA17-APL.pdf` (scale) |
| `image.py` | `tests/fixtures/image/{color_layout,skewed_text,embedded_logo}.png`; `tests/fixtures/image/corrupt.png` (typed failure); the real scans in `tests/fixtures/{casos,chicos,negativos,otros,grandes,blur}/` |
| `ocr.py` | `tests/fixtures/ocr/ocr_prepared_text_and_table.png`; `tests/fixtures/ocr/ocr_blank.png` (a blank page is data: `text=""`, `EMPTY`) |
| `llm.py` | `tests/fixtures/llm/template/simple_extract.md`, `tests/fixtures/llm/schema/simple.schema.json`; the text inputs in `tests/fixtures-txt/**` (`casos/`, `chicos/`, `negativos/`, `pdf_aptos_layout/`) |
| `workflow.py` | `tests/fixtures/pdf/pdf_sample_text.pdf` (native text, OCR skipped); `tests/fixtures/matrix/{page.png,scan150.pdf,three-invoices.pdf}` (multi-page, scanned, mixed); `tests/fixtures/negativos/*.pdf` (documents that legitimately produce no usable extraction) |

`tests/fixtures-txt/` mirrors `tests/fixtures/` by **UUID**: `casos/<uuid>.pdf` and
`casos/<uuid>.jpg` sit next to `fixtures-txt/casos/<uuid>.txt`, which is the same case's
extracted text. The pairing is the bench's Rosetta stone — an operator picks the `.pdf` for a
documental run and the `.txt` for a prompt, and can compare them by eye. The tools do **not**
diff the two: comparing is a reading, and a tool that compares would be a second
implementation of the extraction it is trying to check.

The **batch** tools' demonstration folders are the ones `SCR-17` records: `tests/fixtures/pdf`
(four PDFs, one of them corrupt: `files: 4 · succeeded: 3 · failed: 1`), `tests/fixtures/image`
(four images, one of them corrupt: the same three-and-one), `tests/fixtures/ocr` (two images, both
converted) and `tests/fixtures-txt/casos` (three texts, answered two ways: `--fake` for
`SUCCESS`, and no model served for a typed `MODEL_UNAVAILABLE` on every input).

## 4. Execution plan (PM)

### 4.1 WBS

| ID | Task | Effort | Depends on |
|---|---|---|---|
| SCR-01 | Tool convention and shared plumbing: `scripts/tools/_cli.py` (output root, fixture resolution, printers, exit codes) | M | — |
| SCR-02 | `scripts/tools/pdf.py` | M | SCR-01 |
| SCR-03 | `scripts/tools/image.py` | M | SCR-01 |
| SCR-04 | `scripts/tools/ocr.py` | M | SCR-01 |
| SCR-05 | `scripts/tools/llm.py` | L | SCR-01 |
| SCR-06 | `scripts/tools/workflow.py` | L | SCR-01 |
| SCR-07 | Committed lab run over the fixture roots, with the evidence recorded | M | SCR-02, SCR-03, SCR-04, SCR-05, SCR-06 |
| SCR-08 | Structural guard test + tool-glue tests over the existing doubles | M | SCR-02, SCR-03, SCR-04, SCR-05, SCR-06 |
| SCR-09 | The four QA gates clean on the whole tree | S | SCR-07, SCR-08 |
| SCR-10 | Reconcile the stale lab-tool citations named in §9 | S | SCR-09 |
| SCR-11 | `scripts/tools/_pdf.py` — the PDF bench's command layer, and `pdf.py` rewritten onto it | M | SCR-09 |
| SCR-12 | `scripts/tools/_batch.py` — the shared folder frame — and `batch_pdf.py` | L | SCR-11 |
| SCR-13 | `scripts/tools/_image.py` and `batch_image.py` | M | SCR-12 |
| SCR-14 | `scripts/tools/_ocr.py` and `batch_ocr.py` | M | SCR-12 |
| SCR-15 | `scripts/tools/_llm.py` and `batch_llm.py` (`--fake`, no default command) | L | SCR-12 |
| SCR-16 | The batch sections of `scripts/tools/readme.md`: pairing, mirror, defaults, exit codes | S | SCR-12 |
| SCR-17 | Hand run of the four batch tools over the fixture folders, recorded in the bitacora | M | SCR-13, SCR-14, SCR-15 |
| SCR-18 | This revision: §3.1/§3.4/§4/§5/§6/§9, the WBS issue file, and the root `README.md` table | S | SCR-17 |

### 4.2 Order / waves

- **Wave 1 — Bench plumbing:** `SCR-01` (the parts every tool shares, so five tools are not
  five copies of the same ten lines).
- **Wave 2 — The five tools, in parallel:** `SCR-02` ∥ `SCR-03` ∥ `SCR-04` ∥ `SCR-05` ∥
  `SCR-06`. They depend on `SCR-01` and on nothing else; no tool imports another.
- **Wave 3 — Verify:** `SCR-07` ∥ `SCR-08`. The hand run and the machine guard are two
  different questions and neither substitutes for the other.
- **Wave 4 — Close:** `SCR-09` → `SCR-10`.
- **Wave 5 — Batch mode, one processor at a time:** `SCR-11` (the PDF layer, which proves the
  split on the processor with the widest surface) → `SCR-12` (the shared frame, extracted once
  there is a second tool to share it with) → `SCR-13` ∥ `SCR-14` ∥ `SCR-15` (image, OCR and LLM,
  each against the frame already in place) → `SCR-16` (the readme) ∥ `SCR-17` (the hand run) →
  `SCR-18` (this revision).

**Critical path:** `SCR-01 → SCR-06 → SCR-07 → SCR-09 → SCR-10 → SCR-11 → SCR-12 → SCR-15 →
SCR-17 → SCR-18`.

**Entry condition (wave 5):** `SCR-10` closed, so the five tools and the convention are settled — a
layer extracted before `SCR-09` would be a layer over moving code. No layer precedes the tool it
serves, because the layer is *found* by the second caller: `SCR-11` exists only because
`SCR-12` was about to copy `pdf.py`.

**Entry condition:** Phases 1–3 are closed (they are: `pdf`, `image`, `ocr`, `llm` and the
orchestrator all have their acceptance evidence green), so every symbol in §3.4 exists.
A tool is **not** built ahead of its processor — a tool whose library half is a stub would
have to invent the behaviour it was supposed to expose.

## 5. Acceptance criteria

```gherkin
Scenario: A tool calls the library instead of reimplementing it
  Given "scripts/tools/pdf.py" and a request to split a PDF
  When the "split" subcommand runs
  Then it calls "split_pdf" and prints the paths it returned
  And the tool's source names no Poppler binary, no engine module and no provider SDK
  And deleting "scripts/" leaves src/ and tests/ green

Scenario: The library never reaches back into the tools
  Given the whole tree
  When a static check reads every module under "src/docflow/"
  Then no module under "src/docflow/" mentions "scripts" or "var"
  And no module under "src/docflow/" imports anything under "tests/"

Scenario: Output lands on the bench
  Given any tool run with a fixture input and no "--out"
  When the run finishes
  Then every artifact is under "var/tools/<tool>/<stem>-<hash8>/"
  And the input file's bytes and mtime are unchanged
  And nothing was written beside the input and nothing under "out/"

Scenario: No inference without a stated provider and model
  Given "scripts/tools/llm.py call" with no "--provider" or no "--model"
  When the command runs
  Then it exits with a usage error
  And no request is built and no provider is contacted

Scenario: A typed failure is reported, not raised
  Given "tests/fixtures/pdf/pdf_corrupt.pdf"
  When "scripts/tools/pdf.py inspect" runs
  Then the typed error record is printed
  And the exit code is 1 and no traceback is shown

Scenario: The fixture name is resolved out loud
  Given "--fixture pdf_sample_mixed.pdf"
  When any tool runs
  Then the run header prints the resolved absolute path under "tests/fixtures/"

Scenario: "workflow.py" is bound by the orchestrator's frontier
  Given the source of "scripts/tools/workflow.py"
  When its imports are read
  Then it imports "docflow.pdf", "docflow.image", "docflow.ocr" and "docflow.llm" entry points
  And it imports no "docflow.*.primitives" module

Scenario: A batch runs a whole folder and does not stop at the first bad file
  Given "tests/fixtures/pdf", which holds three readable PDFs and one corrupt one
  When "scripts/tools/batch_pdf.py tests/fixtures/pdf" runs
  Then every readable PDF has a mirror directory under "var/batch_pdf/pdf/<stem>/"
  And each of those holds the "<command>.json" of the method that ran
  And the corrupt one is printed as "pdf_corrupt.pdf: FAILED" with its typed record and files nothing
  And the summary reads "files: 4 · succeeded: 3 · failed: 1"
  And the exit code is 1

Scenario: A batch states the command it made instead of assuming one
  Given "scripts/tools/batch_image.py tests/fixtures/image" with no subcommand
  When the run starts
  Then the header says "command: info (default, none stated)"
  And "info" is the flag-free method that publishes nothing
  And the same run with a stated command prints "command: <name>" with no such note

Scenario: A bare OCR batch writes the text it reports, and one name means one reading
  Given "scripts/tools/batch_ocr.py tests/fixtures/ocr" with no subcommand
  When the run finishes
  Then each input's mirror directory holds "text.txt" beside its "text.json"
  And that file holds exactly the text the record states
  And "scripts/tools/ocr.py text" writes byte-identical bytes to the "text.txt" a "run"
      of the same image writes
  And no other artifact is written by that default

Scenario: The OCR reading is rendered row by row, and the tables keep their place
  Given "scripts/tools/ocr.py mixed" over a page whose form sets a label beside its value
  When the run finishes
  Then "mixed.txt" holds one line per row of the page, the label and its value on that one line
  And every detected table is carried as its Markdown where the reading reaches it
  And the boxes and the tables it reads were claimed by the command, never asked for by the caller
  And no placeholder is substituted and no export is post-processed: the engine writes the table
      where it read it, and the rendering composes the page's rows

Scenario: The batch frame is one implementation, not four
  Given "_batch.py" and the four batch tools
  When their sources are read
  Then no batch tool contains a walk, a mirror, a summary or an exit-code computation of its own
  And no batch tool declares a payload, a flag or an artifact path that its layer does not
```

## 6. Test plan

### One tier, no engine

The tools are **not** run against an engine in the suite. `pytest` must stay green with no
engine installed, and a tool that reached Poppler, OpenCV, Docling or a provider from a test
would break exactly the guarantee this programme is built on. What the suite can check without
an engine is the tool's **shape** and its **glue**, and that is what it checks.

**Structural guards (`SCR-08`), AST over the tree — no execution:**

1. The tool set is exactly `_cli.py`, `_batch.py`, the four processor layers (`_pdf.py`,
   `_image.py`, `_ocr.py`, `_llm.py`) and the nine tools; nothing else lives in `scripts/tools/`.
2. No module under `src/docflow/` mentions `scripts` or `var` (the frontier), and none imports
   `tests/` (the existing `test_skeleton.py` assertion, re-run over the new files).
3. No tool's source names an engine binary (`pdftoppm`, `pdftotext`, `pdfimages`,
   `pdfseparate`, `pdfinfo`, `pdfunite`, `pdftocairo`), an engine module (`cv2`, `PIL`,
   `docling`, `subprocess`) or a provider SDK (`httpx`, `openai`, `ollama`, `anthropic`). A tool
   that calls the library cannot need any of them; one that names them has started reimplementing.
   Run over the layers too (`SCR-11`…`SCR-15`): a layer may drive a primitive but still may not
   name the engine the primitive reaches.
4. `workflow.py` imports no `docflow.*.primitives` module.
5. No module under `src/docflow/` calls `sys.exit`.
6. Every tool exposes a parser builder and its documented subcommands parse; `--help` exits
   `0`. This is the cheapest possible coverage of the surface, and it is the surface the
   runbook quotes. For a batch tool the probe passes the folder *and* the command: a probe that
   passed only one of the two would have proved nothing about the other.
7. The tool declares which of its subcommands publish no file, and the set matches the reader's
   expectation — `REPORT_ONLY` per tool, restated in the test so a subcommand that moves between
   the two sets reddens it. A batch tool's set is empty on purpose: the frame files a record for
   every input that produced a payload.

**Glue tests with the existing doubles (no engine, no provider):** the suite already owns the
machinery — `tests/fakes/processors/` replaces whole processors at the contract level, the
engine doubles replace the engine call inside `primitives/`, and `fake_provider.py` scripts the
provider seam. Each tool's `run` path is driven once through its `main()` with `sys.argv`
patched and a double installed, asserting that the tool built the request the flags describe,
called the entry point once, and printed the result's paths. The tools are not given a fake of
their own; they consume the ones the processors already ship.

**Invariant tests (each with the mutation that must break it):**

1. **A tool adds no behaviour.** *Mutation:* give `pdf.py` its own `render` implementation by
   shelling out to `pdftoppm` instead of calling `render_page_to_image`. *Observed:* guard 3
   fails on the binary name, and the glue test observes the double's call counter at zero.
2. **The library never imports a tool.** *Mutation:* add `import scripts.tools._cli` to
   `src/docflow/pdf/entrypoints.py`. *Observed:* guard 2 fails on the `scripts` mention.
3. **`workflow.py` respects the orchestrator's frontier.** *Mutation:* change `workflow.py`'s
   `run` to call `docflow.ocr.primitives.convert_image_with_docling` directly. *Observed:*
   guard 4 fails on the `primitives` import.
4. **No default model.** *Mutation:* give `llm.py`'s `--model` a default of `"llama3.1"`.
   *Observed:* the "no inference without a stated provider and model" test fails, because the
   command now succeeds with no `--model`.
5. **A returned failure is not reported as `ok`.** *Mutation:* force the frame's per-input line
   back to `ok` instead of deriving it from `_failed`. *Observed:* the returned-failure test fails
   on `': FAILED ->' not in 'a.png: ok -> …'` — and with the frame's own record-printing dropped,
   on the missing `ERROR …:` line. Both mutations are recorded in `docs/plan/bitacora.md`.
6. **A default command is stated, never silent.** *Mutation:* pass `default=False` from
   `batch_ocr.py`. *Observed:* the batch test fails: no
   `command: text (default, none stated)` in the header.
7. **A method's engine throw is a typed failure, not a crash.** *Mutation:* remove the typing from
   `_ocr._conversion` and call the engine call directly. *Observed:* the corpus test fails — the
   engine's own exception escapes the batch and ends the run at the first bad input.
8. **The batch frame is one implementation.** *Mutation:* give a batch tool its own mirror
   computation, or a payload its layer does not hold. *Observed:* the frame's tests fail (the
   mirrored paths stop matching) and `SCR-12`'s guard on the layer/tool split fails on the
   duplicate symbol.
9. **The OCR bench's `text` publishes the reading it reports, and one name means one reading.**
   *Mutation, in two steps:* first drop the `write_text_atomic` call from `_ocr._text`, then
   publish the engine's raw export while reporting the normalized one. *Observed:* the first
   leaves `text.txt` missing (2 red, `FileNotFoundError`); the second leaves the file carrying the
   trailing whitespace the processor's `run` strips, so the artifact and the record of one reading
   disagree (1 red). Both restored by the inverse edit.
10. **A rendered row is geometry, and the engine's origin decides which way is up.**
   *Mutation, in two steps:* first drop `mixed` from `_ocr.CLAIMS`, then stop converting the box
   origin in `primitives._engine_box`. *Observed:* the first renders a page with no rows in it (the
   parse guard and the rendering test both red); the second inverts every box the document
   states — the double's own provenance test red, and the geometry-ordering tests red, because the
   double now reports the engine's `BOTTOMLEFT` instead of hiding it. Both restored by the inverse
   edit.

Each invariant leaves the four-field record `docs/plan/README.md` §7 fixes (Invariant /
Mutation / Observed failure / Restored green) in the root `README.md`, where `GEN-16` audits
the set. A record whose mutation did not turn its test red is a defect of the test.

**Failure fixtures.** `tests/fixtures/pdf/pdf_corrupt.pdf` and
`tests/fixtures/image/corrupt.png` are the two committed inputs whose typed failure path the
glue tests exercise; the real negatives (`tests/fixtures/negativos/**`) are for the hand run
of `SCR-07`, where a document that legitimately yields nothing is the interesting observation —
not an assertion.

**The batch tests (`SCR-12`…`SCR-15`)** build their own corpus in `tmp_path` rather than walking a
committed folder, so a fixture that gains a file cannot change what they assert. Two of them need a
double that is not the engine: `batch_ocr.py`'s returned-failure test scripts the Docling double's
*status* (a refused conversion), and `batch_llm.py`'s reads its tokens with the window stated by the
caller, which is the one LLM command that reaches no provider at all. The `--fake` flag's own test
patches the installer **by name** (`_llm.install_fake`), because a tool invoked by path imports its
siblings as top-level modules while a test imports them as `scripts.tools.*` — two module objects,
and patching the wrong one would leave the tool's own copy in place and pass either way.

## 7. Definition of Ready / Definition of Done

**Definition of Ready**

- Phases 1–3 closed, so every symbol in §3.4 exists and no tool is written against a stub.
- The convention in `docs/plan/README.md` §4.1 is in place and agrees with this subplan and
  the root `README.md` table, subcommand for subcommand.
- The fixture map of §3.5 names only committed files.
- `SCR-08`'s guard is drafted before the first tool, so the boundary is checked from the first
  commit rather than retrofitted.

**Definition of Done**

- The fifteen modules of §3.1 exist at the paths it fixes, and the tool set is exactly those
  fifteen: `_cli.py`, `_batch.py`, the four processor layers, and the nine tools.
- Every subcommand in §3.4 calls the symbol the table names; no tool contains a transformation,
  a retry, a cache, a fallback or a default engine/provider/model/DPI/threshold. A batch tool
  additionally contains no walk, mirror, summary or exit-code computation of its own: those are
  `_batch.py`'s, and the tool supplies only its suffix set, its layer and its command.
- Output lands under `var/tools/<tool>/<stem>-<hash8>/`, and a batch's under
  `var/batch_<processor>/<walked-folder>/<relative folders>/<stem>/`; the input is untouched;
  nothing is written into `out/`.
- `--fixture` resolution and the resolved path are printed.
- Typed failures print and exit `1`; usage errors exit `2`; nothing else.
- The guard test is proven to fail under each documented mutation and restored green.
- `SCR-07`'s hand run against `tests/fixtures/**` and `tests/fixtures-txt/**` is recorded in
  `docs/plan/bitacora.md` with the commands and their real output, including the runs where an
  engine is absent, because "the engine is not installed here" is a fact the bench should
  state rather than hide.
- The four QA gates pass:
  - `pytest`
  - `ruff check .`
  - `ruff format --check .`
  - `pylint src tests`

## 8. Risks & mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| A tool drifts into a second implementation of its processor | Two behaviours to keep in sync; the tool passes where the library fails | Guard 3: the tool's source may not name an engine binary, an engine module or a provider SDK; the glue tests assert the double was called |
| A tool becomes a de-facto API and something under `src/` imports it | The library depends on a bench artefact; deleting `scripts/` stops being safe | Guard 2 asserts the frontier both ways; nothing under `src/` may mention `scripts` |
| A default sneaks in (`--model`, `--dpi`, `--engine`) | The exact silent stand-in this project forbids, on the surface a human trusts most | Required flags for provider and model; invariant 4 mutates a default into place and must go red |
| The tools bit-rot because no CI job runs them | A runbook that no longer works, discovered by a human in a hurry | `SCR-08`'s guards run in `pytest` and are part of `GEN-21`'s gate; the hand run is re-recorded on every engine pin bump. A CI job that *executes* the tools is deliberately out of scope (decision 13) |
| A tool's output tree is committed by accident | Repository churn, fixture confusion | `var/` is in `.gitignore`; output never defaults outside it |
| The engine is not installed on the bench | The tool fails and a human reads it as a bug in our code | The typed error record is printed with exit `1`; `SCR-07` records what each tool does with the engine absent as a first-class observation |
| Six files of argparse nobody re-reads | Dead flags that lie about what the library does | Guard 6 parses every documented subcommand; §3.4 is the mapping the WBS cites, so a flag that disappears from the code fails the runbook's own check |

## 9. Out of scope & resolved decisions

**Out of scope (this subplan)**

- The product CLI (`docflow`): there is no product surface in this plan, and the tools are not
  packaged — no console script, no `[project.scripts]` entry, no `pip install` (decision 11).
- The `docflow-kernel` console entry point and `src/docflow/kernel_cli/` named in
  `.github/copilot-instructions.md`: superseded by `docs/plan/README.md` §9.1.
- Executing the tools in CI (`GEN-21` runs the four gates, not the bench).
- Interactive/watch modes, shell completion, and any tool-local cache.
- A comparison/diff tool: comparing two extractions is a *reading*, and a tool that compared
them would be a second implementation of the thing under test.
- A `batch_workflow.py`: the orchestrator's input is a *document request*, not a folder of files,
  and a corpus of documental runs is a different feature with its own cost model. `SCR-12`'s frame
  is written so that adding it would be a suffix set, a layer and a command — when a plan asks
  for it.
- Parallelism inside a batch: the four batch tools walk and run **serially**, in sorted order, so
  two runs over one tree print the same lines in the same sequence. Concurrency is a cost decision
  nobody has asked for yet (`# TODO: [RELEASE]` when one does).

**Reversed by this revision.** The bullet that read *"Batch corpus runs over `documentos/` and
mirrored output trees"* was in force while the bench served one file at a time. It is now
**in scope**, by the decision recorded in `docs/feedback/batch-mode-across-processors.md`: an
operator with a corpus either runs the tool in a loop and re-assembles the summary by hand, or the
bench does it once for everyone. The reversal is scoped to the four processors' own folders — the
committed fixture roots and any folder a caller names — and does **not** reintroduce
`documentos/`: the corpus stays out of the repository (`.gitignore`), and a batch run over it writes
to `var/batch_<processor>/<folder>/`, which is ignored too.
   §"Lab tools" and the `/var/` ignore rule; `_`-prefixed modules are not tools.
2. **A tool is a caller, not a component — RESOLVED:** the three boundaries of §3.2 hold, and
   `SCR-08` asserts them rather than promising them.
3. **One deliberate exception — RESOLVED:** `pdf.py`, `image.py` and `ocr.py` may reach their
   own `primitives/`; `workflow.py` may not, because it carries the orchestrator's own
   prohibition.
4. **Output root — RESOLVED:** `var/tools/<tool>/<stem>-<hash8>/`, `--out` to override;
   `/var/` is already ignored. The hash prefix makes a repeated run comparable and two inputs
   distinct.
5. **Fixture roots — RESOLVED:** `tests/fixtures/` and `tests/fixtures-txt/`; `--fixture`
   resolves a bare name and the resolved path is printed; `--fixtures-root` relocates the
   search. The UUID pairing between the two trees is documented in §3.5 and used by the
   runbook, not by a diff.
6. **Exit codes — RESOLVED:** `0` success, `1` typed failure printed, `2` usage error. A
   failure the library already typed never reaches the user as a traceback.
7. **No default model, provider or engine — RESOLVED:** `--provider` and `--model` are
   required on every inference subcommand; `ocr.py` has no engine flag because Docling is
   fixed; no tool has an engine flag at all.
8. **`image.py crop` and `ocr.py diff` are dropped — RESOLVED.** `crop_region` and the
   `image/regions/` namespace were deferred by `subplan-procesador-image.md` §9.6, so a `crop`
   subcommand would have nothing to call; and `ocr.py diff` would compare two extractions in
   the tool. The root `README.md` table rows for both are corrected in this same pass, and
   `SCR-10` sweeps the remaining citations listed at the end of this section.
9. **The one permitted `scripts/ → tests/` import — RESOLVED:** `llm.py` (and
   `workflow.py --fake-llm`) installs `tests/fakes/engines/fake_provider.py` at
   `docflow.llm.primitives`, which is the seam the project already patches in tests. The
   frontier is one-directional — `src/` must not import `tests/` — and a lab tool is not
   `src/`. The `fake` subcommand is first-class precisely because a graph or a resume path
   must be demonstrable without a model and without spending a token.
10. **Gate coverage — RESOLVED, and deliberately asymmetric:** `scripts/` is covered by
    `ruff check .` and `ruff format --check .`, which read the whole tree; `pylint src tests`
    does not cover it, and the four gate commands stay verbatim. Pylint's scope is the library
    and its tests; a tool is a disposable caller, and widening the gate would be a change to
    `docs/plan/README.md` §7, the root `README.md` and `GEN-21`'s workflow. The bound is
    stated here rather than papered over; widening it is a plan revision.
11. **Not a product surface — RESOLVED:** no `[project.scripts]` entry, no packaging, no
    `docflow` CLI. The tools are invoked by path.
12. **Tests never execute a tool that reaches an engine — RESOLVED:** the suite checks the
    tools' shape and their glue through the existing doubles; the real seam is exercised by
    hand (`SCR-07`), by a human, and recorded as an observation rather than a gate.
13. **No CI execution of the tools — RESOLVED for the PoC:** `GEN-21` runs the four gates. A
    bench that executes real engines on every pull request is a cost this stage does not take;
    the guards keep the tools honest in the meantime.
14. **Two tools per processor, one layer under them — RESOLVED (`SCR-11`…`SCR-15`):** the
    single-file tool and the folder tool call the same methods, so the methods live in a shared
    `_`-prefixed layer. The alternative — the batch importing its twin — would make one tool's
    private helper another tool's API, and a second copy of every payload would drift.
15. **The batch's command is the caller's, and a default is stated — RESOLVED, and its second
    clause is reworded by decision 19:** a batch tool with a flag-free method makes it, and says so
    in the header; the default publishes at most the reading it reports (§3.4, rule 1). A tool with
    no such method (`batch_llm.py`, whose every command requires a provider and a model) makes
    **none** and requires the caller to state one. A default is never silent, and never invented to
    make a bare run succeed.
16. **The batch's command subset is a decision — RESOLVED (`SCR-15`):** the four commands whose
    answer is a property of the input. `status`, `models`, `fake` and `resume` are not registered
    on `batch_llm.py` at all, so naming one is a usage error rather than a silent no-op.
17. **One mirror, one record, one exit code — RESOLVED (`SCR-12`):** every batch tool writes
    `<root>/<relative folders>/<stem>/<command>.json`, publishes the method's artifacts beside it,
    and exits `1` when any input failed. The record is named after its command, so two commands
    over one input keep both records instead of the second overwriting the first. The walk skips
    the run's own root. The frame lives in `_batch.py`, so the fifth batch tool is a suffix set, a
    layer and a command.
18. **The page flag is optional, and its absence means every page — RESOLVED, and the question is
    owned by [`subplan-paginas.md`](subplan-paginas.md) (`PAG-01`…`PAG-07`).** This subplan is
    stale on exactly three of its clauses, all now corrected above: §3.3's page-scope bullet (which
    replaces the old "a missing `--page` is a usage error") and its `render --page 1` example,
    §3.4's five `Notes` cells for `render`/`text`/`blocks`/`images`/`classify`. **§5 and §6 need no
    correction** — no acceptance scenario and no guard in either ever named the page flag, which is
    itself the finding: the refusal was pinned by tests alone, so it moved without a scenario to
    contradict.
19. **The OCR bench's `text` publishes the text it reports — RESOLVED (`SCR-04`, `SCR-14`), and it
    revises the wording of decision 15.** `ocr.py text` and `batch_ocr.py … text` write `text.txt`
    in that input's run root: normalized the way `ocr/entrypoints.py` normalizes it, so the bytes
    are the ones a `run` of the same image writes under the same name, and the file holds exactly
    what the payload states. A bare `batch_ocr.py <folder>` therefore fills each mirror directory
    with one small text file — the reading it reports — which is why decision 15's rule now reads
    "the default publishes at most the reading it reports" rather than "publishes nothing". `md`,
    `json`, `tables`, `blocks` and `metrics` still publish nothing, and `text` derives nothing from
    the text it reads: no render, no table directory, no document.
20. **The OCR bench's `mixed` renders the page's rows — RESOLVED (`SCR-04`, `SCR-14`), and it
    supersedes the shape this decision first took the same day.** The operator asked for one text
    artifact holding the text *and* the detected tables, and imagined a `<table>` placeholder to
    substitute. Docling writes none: measured on `tests/fixtures/casos/66cd35e9-….jpg`
    (docling 2.126.0), `export_to_text()` writes the table as Markdown where it was read when
    `do_table_structure` is on, and a degenerate single-row pseudo-table when it is off — never a
    `<table>` marker, and no `<image>` either (that one appears in `export_to_markdown()` only). The
    operator then reported what the text really gets wrong, with the region: the customer block
    reads `Cliente:` / `Domicilio:` / `CVC S.A. (63)` / `CUIT:…` / `CIRCUNVALACION …` — five lines
    where the page sets three side-by-side pairs — because the engine states one region per line
    and its export puts them one under the other. No joining of newlines repairs that, and doing it
    costs the table: measured, the advised regex (`(?<!\n)\n(?!\n)`) removes exactly the three
    newlines *inside* the Markdown table and leaves the block untouched. So `mixed` is a rendering
    of ours — `composition.render_reading`, the single owner of the rule: items whose vertical
    spans overlap are one line, ordered left to right; the rows run top to bottom; a table is a
    block carried as its Markdown where the reading reaches it; nothing is joined across rows. It
    publishes `mixed.txt` and not `text.txt`, because the bytes are not the engine's export
    (decision 19) and one name may not mean two readings. The command claims `--tables` and
    `--layout` (`_ocr.CLAIMS`) because the rendering reads both, and claims no reading order: its
    rows come from the boxes whatever the document's own order was set to. Measured on the invoice,
    the five lines become the two the page states and the totals block becomes its labels row and
    its values row.
21. **The engine's box origin is honoured at the seam — one conversion, four symptoms.** Docling
    reports the pages this processor converts in `CoordOrigin.BOTTOMLEFT`, so the item *highest* on
    the page carries the *largest* `t`. `normalize_bbox` read those numbers as top-down, so every
    `bbox` in `document.json` had its top and its bottom swapped, and
    `preserve_reading_order(by_geometry=True)` read the page from the bottom up — measured on the
    invoice: 39 extracted blocks came back as **3**, one of them an 816-character paragraph joining
    the whole form, ordered from the totals up to `ORIGINAL`. The conversion is the engine's own
    (`to_top_left_origin(page_height)`, reached only when the box states `BOTTOMLEFT`), made once in
    `_engine_box`, so blocks, tables and layout regions all reach the document in the one convention
    `composition` documents. The double now models the origin it was hiding: `FakeBoundingBox`
    reports `BOTTOMLEFT` and hands over `(l, b, r, t)`, with the fixtures still written top-down
    through `for_top_down_rect` — a double reporting top-down numbers is what let an inverted
    document pass every test.

**Stale documents this subplan creates or leaves (owner in parentheses)**

The planning pass that produced this subplan reconciled the root `README.md` already: the
"Lab tools" table loses `image.py crop` and `ocr.py diff` and names `SCR-02`…`SCR-06`, the
phase table's Phase 5 row cites `SCR-01`…`SCR-10`, and the divergence note that called the
borrowed IDs an open plan revision now records them as resolved. What remains is:

| Document | What is stale | Owner |
|---|---|---|
| `docs/plan/issues/wbs-scripts.md` | §1/§2/§3 carry `SCR-01`…`SCR-10` only; `SCR-11`…`SCR-18` and their Depends/Blocks edges are added by this revision | `SCR-18` |
| `docs/plan/README.md` §4.1 and §6 | the module set and the wave table name the six original modules | `SCR-18` |
| root `README.md` | the "Lab tools" table names the six original modules and `SCR-02`…`SCR-06`; it gains the batch tools | `SCR-18` |
| `docs/plan/issues/wbs-general.md` | §1 and §4 name no Phase 5 range at all; the `SCR-*` range exists only in this subplan and its WBS | `SCR-10` |
| `.github/copilot-instructions.md` | describes `docflow-kernel` + `src/docflow/kernel_cli/` as the lab surface; `docs/plan/README.md` §9.1 resolved the layout without a kernel layer, and §4.1 here names the replacement | `SCR-10` |
| `docs/plan/bitacora.md` | has no entry for this pass until `SCR-07` writes one | `SCR-07` |
| `docs/plan/subplan-procesador-image.md` §9.6 and root `README.md` | both record `crop_region` as deferred (`# TODO: [MVP]`); nothing to fix, cited here so `SCR-10`'s sweep does not re-open a closed decision | — |
