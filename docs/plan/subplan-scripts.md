# Subplan — lab tools (`scripts/tools/`)

## 1. Objective

Ship **five thin operator CLIs**, one per processor plus the orchestrator, that exercise the
finished library by hand against the committed fixtures under `tests/fixtures/` and
`tests/fixtures-txt/`:

| Tool | Task | Exposes |
|---|---|---|
| `scripts/tools/pdf.py` | `SCR-02` | `inspect`, `split`, `render`, `text`, `blocks`, `images`, `classify`, `run` |
| `scripts/tools/image.py` | `SCR-03` | `info`, `metrics`, `normalize`, `ocr-ready`, `vlm-ready`, `classify`, `run` |
| `scripts/tools/ocr.py` | `SCR-04` | `run`, `text`, `md`, `json`, `tables`, `blocks`, `metrics` |
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
├── pdf.py
├── image.py
├── ocr.py
├── llm.py
└── workflow.py
```

`_cli.py` is justified by the five callers rule this repository already applies to
`utils/`/`helpers/`: a symbol belongs in a shared module only when more than one caller needs
it, and here five do. It holds **only** the plumbing that would otherwise be copy-pasted five
times — output-root resolution, fixture resolution, the `--json` printer, the human printer,
and the exit-code mapping. It is not a seam: it imports no engine, no provider and no
contract, and nothing under `src/` may import it.

Filename convention: a tool is `<name>.py` with a lowercase name; a leading underscore marks
a module that is not a tool. The guard test enumerates the set, so a sixth tool is a plan
revision and not a surprise.

### 3.2 The three boundaries (and the one deliberate exception)

1. **Calls, never reimplements.** `pdf.py split` calls `split_pdf`; it does not shell out to
   `pdfseparate`. Printing a result is a tool's job; producing it is not.
2. **The library never imports a tool.** Nothing under `src/docflow/` references `scripts/`
   or `var/`. Asserted by AST, not by habit.
3. **No new seam.** A tool adds no contract, no options type and no behaviour the library
   lacks. If a subcommand needs something the processor cannot do, the tool is wrong, or the
   processor has a gap.

**The exception — the lab bench.** `pdf.py`, `image.py` and `ocr.py` **may** import their own
processor's `primitives/` and drive one named primitive. That is what a bench is for: `render
--dpi 400` drives `render_page_to_image` without a document run, which the orchestrator is
forbidden to do. **`workflow.py` is excluded from the exception**: it is bound by the same
prohibition the orchestrator is, and reaches the four processors only through their public
contracts.

### 3.3 Invocation, output and exit codes

```bash
python scripts/tools/pdf.py inspect tests/fixtures/pdf/pdf_sample_mixed.pdf
python scripts/tools/pdf.py --fixture pdf_sample_mixed.pdf render --page 2 --dpi 300
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
- **Fixture roots:** `tests/fixtures/` and `tests/fixtures-txt/` (the second for text inputs).
  `--fixture <name>` resolves a bare name or a name with a subdirectory; a **path** is taken
  as given. The resolved absolute path is printed in the run header, so a resolved fixture is
  never silent, and `--fixtures-root` relocates the search when the tree moves.
- **stdout** carries the human summary; `--json` prints the machine-readable payload instead
  (built from the result's own fields, not a second serialization of the library's state).
- **Exit codes:** `0` the run produced a result and its `status` is a success; `1` the library
  returned a typed failure (`status != success`, or `DocumentResult.status == FAILED`) — the
  typed error records are printed, the tool does not raise; `2` a usage error (unknown
  subcommand, missing required flag, unresolvable input), which is `argparse`'s own code.
  Nothing else, and never a traceback for a failure the library already typed.

### 3.4 Subcommand → symbol map (the whole contract of each tool)

Every row names a symbol that exists today. A row with no symbol would not be a subcommand.

**`pdf.py`** — public entry points plus the processor's own primitives:

| Subcommand | Calls | Notes |
|---|---|---|
| `inspect` | `pdf.primitives.inspect_pdf` | pages, geometry, encryption |
| `split` | `pdf.primitives.split_pdf` | one file per page |
| `render` | `pdf.primitives.render_page_to_image` | `--page`, `--dpi` |
| `text` | `pdf.primitives.extract_text_from_page` | the page's native text |
| `blocks` | `pdf.primitives.extract_text_from_page` | same call, `--blocks` view; text and blocks come from **one** read |
| `images` | `pdf.primitives.extract_images_from_page` | embedded images |
| `classify` | `pdf.primitives.composition.analyze_pdf_page` + `classify_pdf_page` | the page's `TEXT`/`IMAGE`/`MIXED` verdict |
| `run` | `pdf.process_pdf` | the contract; `--page` adds `process_pdf_page` |

**`image.py`** — same shape; `crop` is **not** here (§9, decision 8):

| Subcommand | Calls | Notes |
|---|---|---|
| `info` | `image.primitives.get_image_metadata` + `get_image_dimensions` | no pixels decoded |
| `metrics` | `image.primitives.load_image` + `analyze_image` | the technical analysis |
| `normalize` | `image.primitives.prepare_normalized_image` | `normalized.png` |
| `ocr-ready` | `image.primitives.prepare_image_for_ocr` | its own pipeline |
| `vlm-ready` | `image.primitives.prepare_image_for_vlm` | distinct from `ocr-ready`, never an alias |
| `classify` | `image.primitives.composition.classify_image` | over the metrics above |
| `run` | `image.process_image` | the contract; `--from-page` adds `process_image_from_page` |

**`ocr.py`** — no `--engine` flag: Docling is fixed and never user-selectable:

| Subcommand | Calls | Notes |
|---|---|---|
| `run` | `ocr.process_ocr_image` | the contract |
| `text` / `md` / `json` | `ocr.primitives.extract_docling_text` / `extract_docling_markdown` / `build_ocr_document` | one representation each |
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

### 4.2 Order / waves

- **Wave 1 — Bench plumbing:** `SCR-01` (the parts every tool shares, so five tools are not
  five copies of the same ten lines).
- **Wave 2 — The five tools, in parallel:** `SCR-02` ∥ `SCR-03` ∥ `SCR-04` ∥ `SCR-05` ∥
  `SCR-06`. They depend on `SCR-01` and on nothing else; no tool imports another.
- **Wave 3 — Verify:** `SCR-07` ∥ `SCR-08`. The hand run and the machine guard are two
  different questions and neither substitutes for the other.
- **Wave 4 — Close:** `SCR-09` → `SCR-10`.

**Critical path:** `SCR-01 → SCR-06 → SCR-07 → SCR-09 → SCR-10`.

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
```

## 6. Test plan

### One tier, no engine

The tools are **not** run against an engine in the suite. `pytest` must stay green with no
engine installed, and a tool that reached Poppler, OpenCV, Docling or a provider from a test
would break exactly the guarantee this programme is built on. What the suite can check without
an engine is the tool's **shape** and its **glue**, and that is what it checks.

**Structural guards (`SCR-08`), AST over the tree — no execution:**

1. The tool set is exactly `_cli.py` + the five tools; nothing else lives in `scripts/tools/`.
2. No module under `src/docflow/` mentions `scripts` or `var` (the frontier), and none imports
   `tests/` (the existing `test_skeleton.py` assertion, re-run over the new files).
3. No tool's source names an engine binary (`pdftoppm`, `pdftotext`, `pdfimages`,
   `pdfseparate`, `pdfinfo`, `pdfunite`, `pdftocairo`), an engine module (`cv2`, `PIL`,
   `docling`, `subprocess`) or a provider SDK (`httpx`, `openai`, `ollama`). A tool that calls
   the library cannot need any of them; one that names them has started reimplementing.
4. `workflow.py` imports no `docflow.*.primitives` module.
5. No module under `src/docflow/` calls `sys.exit`.
6. Every tool exposes a parser builder and its documented subcommands parse; `--help` exits
   `0`. This is the cheapest possible coverage of the surface, and it is the surface the
   runbook quotes.

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

Each invariant leaves the four-field record `docs/plan/README.md` §7 fixes (Invariant /
Mutation / Observed failure / Restored green) in the root `README.md`, where `GEN-16` audits
the set. A record whose mutation did not turn its test red is a defect of the test.

**Failure fixtures.** `tests/fixtures/pdf/pdf_corrupt.pdf` and
`tests/fixtures/image/corrupt.png` are the two committed inputs whose typed failure path the
glue tests exercise; the real negatives (`tests/fixtures/negativos/**`) are for the hand run
of `SCR-07`, where a document that legitimately yields nothing is the interesting observation —
not an assertion.

## 7. Definition of Ready / Definition of Done

**Definition of Ready**

- Phases 1–3 closed, so every symbol in §3.4 exists and no tool is written against a stub.
- The convention in `docs/plan/README.md` §4.1 is in place and agrees with this subplan and
  the root `README.md` table, subcommand for subcommand.
- The fixture map of §3.5 names only committed files.
- `SCR-08`'s guard is drafted before the first tool, so the boundary is checked from the first
  commit rather than retrofitted.

**Definition of Done**

- The five tools and `_cli.py` exist at the paths §3.1 fixes, and the tool set is exactly
  those six files.
- Every subcommand in §3.4 calls the symbol the table names; no tool contains a transformation,
  a retry, a cache, a fallback or a default engine/provider/model/DPI/threshold.
- Output lands under `var/tools/<tool>/<stem>-<hash8>/`; the input is untouched; nothing is
  written into `out/`.
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
- Batch corpus runs over `documentos/` and mirrored output trees.
- Executing the tools in CI (`GEN-21` runs the four gates, not the bench).
- Interactive/watch modes, shell completion, and any tool-local cache.
- A comparison/diff tool: comparing two extractions is a *reading*, and a tool that compared
  them would be a second implementation of the thing under test.

**Resolved decisions**

1. **Location and names — RESOLVED:** `scripts/tools/<name>.py`, matching the root `README.md`
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

**Stale documents this subplan creates or leaves (owner in parentheses)**

The planning pass that produced this subplan reconciled the root `README.md` already: the
"Lab tools" table loses `image.py crop` and `ocr.py diff` and names `SCR-02`…`SCR-06`, the
phase table's Phase 5 row cites `SCR-01`…`SCR-10`, and the divergence note that called the
borrowed IDs an open plan revision now records them as resolved. What remains is:

| Document | What is stale | Owner |
|---|---|---|
| `docs/plan/issues/wbs-general.md` | §1 and §4 name no Phase 5 range at all; the `SCR-*` range exists only in this subplan and its WBS | `SCR-10` |
| `.github/copilot-instructions.md` | describes `docflow-kernel` + `src/docflow/kernel_cli/` as the lab surface; `docs/plan/README.md` §9.1 resolved the layout without a kernel layer, and §4.1 here names the replacement | `SCR-10` |
| `docs/plan/bitacora.md` | has no entry for this pass until `SCR-07` writes one | `SCR-07` |
| `docs/plan/subplan-procesador-image.md` §9.6 and root `README.md` | both record `crop_region` as deferred (`# TODO: [MVP]`); nothing to fix, cited here so `SCR-10`'s sweep does not re-open a closed decision | — |
