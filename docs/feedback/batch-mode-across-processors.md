# Decision — batch mode across the processors (work order)

> Status: **decided, not yet applied**. Supersedes the `subplan-scripts.md` §9 bullet *"Batch
> corpus runs over `documentos/` and mirrored output trees"*, which this note reverses; the plan
> revision in §5 step 1 performs that edit, and until it runs this note is the winning decision.
>
> This note is the plan. It changes no code and no frozen artifact by itself: it fixes the shape
> (which tools, which defaults, which commands each one exposes), the sequencing, the acceptance
> criteria and the risks, so the work can be applied and reviewed in that order.

## 1. The decision

Extend the bench's batch pattern from PDF to **image**, **OCR** and **LLM**: one shared folder
frame, one shared command layer per processor, one batch tool per processor. Four tools, four
layers, one frame:

| Processor | Shared layer | Batch tool | Bare run (no subcommand) | Inputs it walks |
|---|---|---|---|---|
| PDF | `_pdf.py` — **shipped** | `batch_pdf.py` — **shipped** | `inspect` | `.pdf` |
| image | `_image.py` — to extract | `batch_image.py` | `info` | `.png` `.jpg` `.jpeg` `.tif` `.tiff` `.bmp` |
| OCR | `_ocr.py` — to extract | `batch_ocr.py` | `text` | the same image set |
| LLM | `_llm.py` — to extract | `batch_llm.py` | **none: the subcommand is required** | `.txt` `.md` |

**`batch_workflow.py` is out of scope, deliberately.** `workflow.py` carries the orchestrator's
frontier — it may not reach a `primitives/` module — and a documental workflow over a corpus is a
product feature, not a bench observation. The three processors are the ones with a per-input
method to run.

## 2. Why this shape

**The frame is one thing, not four.** `batch_pdf.py` already holds the whole folder contract in
itself: the walk, the mirror, the per-input record, the summary and the exit code. Four copies of
that would be the duplication the PDF refactor just removed. So the frame moves into
`scripts/tools/_batch.py` — a module that is not a tool, exactly as `_cli.py` is not — and
`batch_pdf.py` is refactored onto it **before** the second batch tool exists. That refactor is
behaviour-preserving, and its evidence is the guards and glue tests that already exist.

**The per-processor layer.** Each batch tool needs the same methods its single-file tool has, with
the same payloads and the same flags. That is what `_pdf.py` demonstrated: extract the methods,
let both tools dispatch through one dictionary, and neither owns a second copy of a payload.
`image.py`, `ocr.py` and `llm.py` each get the same treatment.

**Why those defaults.** A bare run must be safe, complete and stated:

- `inspect` (pdf), `info` (image) and `text` (OCR) are the **flag-free methods that publish
  nothing** — a bare run can only report, and it cannot fill the tree. Every other flag-free
  method (`split`; `normalize`, `ocr-ready`, `vlm-ready`; `run`) writes, so defaulting to one would
  make an accidental bare run publish files.
- The header prints the command it made (`command: inspect (default, none stated)`), so the default
  is never silent.
- **LLM has no default at all.** `--provider` and `--model` are required on every inference
  subcommand — a default model is precisely the silent stand-in this project forbids — so a bare
  `batch_llm.py <folder>` could not run honestly. Its subcommand is therefore required, and that
  asymmetry is the point, not an oversight.

## 3. The per-tool command subsets

The image and OCR batch tools expose their processor's full set (`info`, `metrics`, `normalize`,
`ocr-ready`, `vlm-ready`, `classify`, `run`; `run`, `text`, `md`, `json`, `tables`, `blocks`,
`metrics`). The LLM one does **not**, because three of its subcommands are not per-input questions:

- `status` reads one run directory, not a folder of inputs.
- `models` answers the same inventory for every input; it is a provider question, asked once.
- `fake` is a two-run demonstration of the chain (a graph and its resume) under one pinned
  `--run-id`, not a method to apply per file.

So `batch_llm.py` runs `call`, `graph`, `node` and `tokens`, and takes a **`--fake` flag** that
installs the committed scripted provider at the provider seam for the whole run — the shape
`workflow.py --fake-llm` already uses, which is what makes a batch demonstrable with no model
served.

## 4. Facts this plan rests on (verified 2026-09-27)

- `pdf.py`, `image.py` and `ocr.py` may drive one named primitive of their own processor
  (`subplan-scripts.md` §3.2, the lab-bench exception); `workflow.py` may not. A batch tool that
  drives them is the same exception, one directory up.
- `image.py`'s seven subcommands take **no required flag** (`info`, `metrics` and `classify` take
  none; the three preparation pipelines and `run` take only optional correction/option flags,
  `--page` defaulting to 1).
- `ocr.py`'s six representation subcommands take no flags either; only `run` has options, and all
  of them are optional.
- `llm.py` requires `--provider` and `--model` on every inference subcommand and on `models` and
  `tokens`; `node` builds its request with no output directory on purpose.
- Real inputs exist for every walk: `tests/fixtures/image/` (4 PNGs), `tests/fixtures/casos/`
  (PDFs *and* PNGs — the extension filter is what separates them), `tests/fixtures-txt/casos/`
  (3 text files).

## 5. Sequencing (each step lands gated)

1. **The plan revision.** `subplan-scripts.md` §3.1 (the module set), §3.4 (the batch tools and the
   shared layers), §4 (the `SCR-11`…`SCR-18` rows, waves, critical path), §5 (a batch acceptance
   scenario), §6 (guard 1's set) and §9 (the *reversal* of "batch corpus runs over `documentos/`
   and mirrored output trees — out of scope"); `issues/wbs-scripts.md` §1/§2/§3 with the same tasks
   and their `Depends on:`/`Blocks:` edges; `docs/plan/README.md` §4.1 and §6, and the root
   `README.md`'s tool table, for the citations. `SCR-11`/`SCR-12` (the PDF pair) are recorded as
   **done** with the bitacora as their evidence — they shipped outside the plan, which is the drift
   this revision closes.
2. **`_batch.py` + `batch_pdf.py` refactored onto it.** No behaviour change; the existing glue
   tests and guards are the evidence.
3. **Image:** `_image.py`, `batch_image.py`, tests, guards, readme.
4. **OCR:** `_ocr.py`, `batch_ocr.py`, tests, guards, readme.
5. **LLM:** `_llm.py`, `batch_llm.py`, tests, guards, readme.
6. **Verify:** the hand run of the four batch tools over real fixture folders, recorded in
   `docs/plan/bitacora.md` with the counts and the exit codes, and the four QA gates.

## 6. Acceptance criteria (checked per batch tool)

- Given a folder, when the tool runs, then the mirror is `<root>/<relative folders>/<stem>/` and
  `<root>` is `var/<tool>/<folder>/` or the `--out` directory.
- Given an input that produced a payload, then `<stem>/result.json` holds it; given an input that
  failed, then its typed record is printed and counted and no directory is created for it.
- Given no subcommand and a tool whose default is stated, then the header names the default and the
  run proceeds; given `batch_llm.py` with no subcommand, then it is a usage error.
- Given a folder holding one bad file among good ones, then every input is attempted, the summary
  counts them separately, and the exit code is `1`; given none failed, `0`; given a bad folder,
  `2`.
- Given any batch tool, then its source names no engine binary, engine module or provider SDK, and
  imports no other tool.

## 7. Risks, stated rather than hidden

- **Docling is slow** (about a second per small image, much more for a dense page): an OCR batch
  over a corpus is minutes, not seconds. The readme states it; the guards never execute it.
- **The image processor cannot publish with the real engine** (the `.tmp` sibling meets an encoder
  that reads the extension): `batch_image.py normalize`, `ocr-ready` and `vlm-ready` therefore
  report a typed `WRITE_ERROR` per input. Already registered with an owner in the bitacora; the
  batch reports it, it does not hide it.
- **No model is served here**: a real `batch_llm.py` reports `MODEL_UNAVAILABLE` per input, which
  is the honest observation; `--fake` is the way to demonstrate the chain.
- **Nine tools and five layers is a lot of surface**: the guards are what keep it honest, so the
  revision widens guard 1 (the module set), guard 3 (no engine named, over every module) and guard
  7 (the `REPORT_ONLY` pin per tool) in the same pass as the code that makes them necessary.
