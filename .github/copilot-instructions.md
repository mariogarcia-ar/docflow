# Python Standards (PoC mode)

## Project Identity

- **Solution name:** `docflow`. Library-first: the library is the deliverable, the CLI is one caller of it.
- **Import name is `docflow`.** The package lives under `src/`, so the *path* is `src/docflow/` but the *import* is always `docflow.…` — never `src.docflow`. A `src/` layout is used so tests exercise the packaged code and not an accidental working-directory copy.
- **The specification is in `docs/artifacts/`.** `prd.md`, `sad.md`, `wbs.md`, `kernel-cli.md`, `traceability.md` are the decisions; `docs/idea/` is the exploration that led to them. Where they disagree, **the artifact wins**.
- **Frozen contract:** `docs/plans/README.md` §3 lists what each plan freezes. Do not change a frozen artifact; a change re-opens the gate that froze it.

## Workspace Layout

```
src/docflow/          the library (import name: `docflow`)
  kernels/            K1-K8: orchestrator, pdf, image, ocr, llm.local, llm.frontier, store, registry
  ports/              the five port interfaces (PdfSource, OcrEngine, LlmEngine, ArtifactStore, Registry)
  adapters/           thin adapters behind the ports (Docling, pdftotext, Ollama, a provider SDK)
  components/         the ten domain components (Stage 2)
  kernel_cli/         the `docflow-kernel` lab surface — a package, never a kernel_cli.py module
  cli.py              the `docflow` product surface
  batch.py            batch input / mirrored output tree
tests/                mirrors the `src/docflow` tree, one test module per source module
docs/                 the specification and the plans (read-only for code tasks)
registry/             corpus assets: patterns, prompts, schemas, policies (Stage 3)
descriptors/          pipeline descriptors (Stage 3)
fixtures/             committed test fixtures, each named for the failure it provokes
pyproject.toml        packaging, entry points, and all tool config (Ruff, Pylint, pytest, coverage)
```

- **Package layout and tool config are owned by the Data layer** (`wbs.md` §8): `pyproject.toml`. If a task needs a new tool or dependency, add it there rather than creating a second config file.
- **The artifacts name the module path, not the physical path.** Where a document writes `docflow/kernels/store.py`, the file lives at `src/docflow/kernels/store.py`. The `src/` prefix is the physical location and is not repeated in the docs.
- **Installing:** `pip install -e ".[dev]"` for development. Running `pytest` needs no install — `pyproject.toml` puts `src` on the path.
- **Two entry points, two audiences, never crossed:** `docflow` (product) and `docflow-kernel` (lab bench). `docflow run` never invokes `docflow-kernel`.
- **Never commit:** the corpus (`documentos/`), run output (`out/`, `work/`), `.env`, and coverage/cache/build directories. `.gitignore` is the authority — read it before adding a file that looks like output.

## Language
- Output, code, and docs: 100% English, regardless of input language (understand Spanish, respond in English).
- Identifiers, docstrings, comments, logs, exceptions: English, PEP8 naming.

## Code Quality
- Ruff + Pylint clean. Sorted imports (stdlib → third-party → local). No unused imports.
- Type hints on all function signatures. Google-style docstrings. No redundant comments.
- DRY: no copy-paste logic blocks.

### The four QA gates (all must pass before a task is `done`)

```bash
pytest                                    # tests green (no install needed; pyproject puts src on the path)
ruff check .                              # linter, includes import order (rule `I`)
ruff format --check .                     # formatter
pylint src tests                          # `fixme` is disabled; the rest must be clean
```

- Config lives in `pyproject.toml` — do not create a second `setup.cfg` / `tox.ini` / `pylintrc`. All four tools read it: `[tool.ruff.*]`, `[tool.pylint.*]`, `[tool.pytest.ini_options]`, `[tool.coverage.*]`.
- **`ruff format` owns line length, not `E501`.** A long test name that the formatter cannot split is not a defect; `E501` is ignored and the formatter is the authority.
- **`docs/` is excluded from Ruff on purpose:** it contains Python code blocks in the specification, and a formatter that rewrites a frozen artifact is worse than one that skips it.
- **`fixme` is disabled on purpose:** it flags the `# TODO: [MVP]` markers this file *requires*. The markers are the deliverable, not the debt.
- **Prefer an inline suppression with a stated reason over a config change.** A `# pylint: disable=<rule>` next to the offending line, or a `per-file-ignores` entry, must carry a comment saying why the rule does not apply. A silent config-wide disable is not acceptable.
- **A `# type: ignore[...]` must name the specific error code.** A bare `# type: ignore` is rejected.
- **A test that guards an invariant must FAIL when the invariant is broken.** Prove it by mutating the source, observing the failure, then restoring and re-running green — and report both observations. A test that only passes when the code is correct proves nothing.

## Current Stage: PoC — close flows fast
- Happy path only. Hardcode/mock/in-memory OK if it closes the loop faster.
- No abstractions, no generic wrappers, no deep nesting (low McCabe complexity).
- If a stdlib/SDK call closes it in 5 lines, don't wrap it in a class.
- Mark all shortcuts inline: `# TODO: [MVP]` (real DB/API/validation) or `# TODO: [RELEASE]` (telemetry/caching/HA/security). These tags are the *expected* way to defer complexity — not a violation of the no-abstraction rule above.

### Never, at any stage
- No silent stand-in: no empty string, `0`, `[]`, `None`-without-reason, and no default model, engine or threshold used in place of a real answer.
- No domain noun (invoice, field, verdict, pipeline code) in a kernel API.
- No adapter imported from a port.
- No aggregate confidence score in place of the per-field verdict vector.

## Workflow for new features (in order)
1. Skeleton: typed function/class signatures, `pass`/mock returns — full pipeline shape first.
2. Tag debt: `# TODO: [MVP|RELEASE]` on every shortcut in the skeleton.
3. One `pytest` happy-path test proving data flows end-to-end (no edge cases).
4. Implement minimum logic to pass that test, Ruff/Pylint clean.
5. Run the four QA gates, and prove any invariant test fails when the invariant is broken.
