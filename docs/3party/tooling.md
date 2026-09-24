# Tooling — dossier

> Kind: developer tooling (not an engine)
> Processor / seam: **none** — no processor imports it, no artifact records a version of it
> Status: collecting (2026-09-24)

## 0. Why this page is not an engine page

`pytest`, `ruff`, `pylint` and `coverage` never run inside a processor: there is no seam, no
`engine`, no `engine_version` and no test double. They are documented here only because
`GEN-05` makes `pyproject.toml` their single configuration home, and because the four QA
gates are the definition of `done` for every task in the plan. Nothing in this page may be
cited as an engine fact.

## A. Identity and provenance

| Tool | Role | Upstream |
|---|---|---|
| `pytest` | the gate: runs the suite, needs no engine installed | <https://docs.pytest.org> |
| `pytest-cov` / `coverage` | coverage measurement and reporting | <https://coverage.readthedocs.io> |
| `ruff` | linter (incl. import order `I`) **and** formatter | <https://docs.astral.sh/ruff> |
| `pylint` | second linter; `fixme` disabled on purpose | <https://pylint.readthedocs.io> |

## B. Install, pin and version discovery

- **Install shape:** the `dev` extra — `pip install -e ".[dev]"`.
- **Pins as declared in `pyproject.toml`** (floors, not exact pins today):

  | Package | Declared |
  |---|---|
  | `pytest` | `>=8.0` |
  | `pytest-cov` | `>=5.0` |
  | `ruff` | `>=0.6.0` |
  | `pylint` | `>=3.2.0` |

- **Installed in this venv (2026-09-24):** `pytest 9.1.1`, `pytest-cov 7.1.0`,
  `coverage 7.16.0`, `ruff 0.16.7`, `pylint 4.0.8`. Every one is **above** its declared floor,
  which is the gap a floor-only pin leaves open: the suite must stay green on the floor too,
  or the floor is a lie. `TBD`: decide whether these become exact pins.
- **Version at runtime:** `--version` for each tool; not recorded in any artifact.
- **Absent / present check:** running `pytest` needs **no install of `docflow`** (the
  `pythonpath = ["src"]` setting does that) and **no engine** (`GEN-21`).

## C. Licence and distribution posture

- All four are permissively licensed (MIT/BSD/Apache family — `TBD`: confirm per package).
- They are **development-only** dependencies: the `dev` extra must never leak into the
  runtime dependency set of a shipped artifact.

## D. Configuration contract (what the four tools read)

All of it lives in `pyproject.toml` (`GEN-05`); a second `setup.cfg`, `tox.ini` or `pylintrc`
is a defect.

| Section | What it fixes |
|---|---|
| `[tool.pytest.ini_options]` | `minversion = "8.0"`, `testpaths = ["tests"]`, `pythonpath = ["src"]`, `addopts = "-ra --strict-config --strict-markers"` — so `pytest` means *everything*, with no marker and no second tier |
| `[tool.ruff]` | `line-length = 88`, `target-version = "py311"`, `exclude = ["docs", ".venv"]` |
| `[tool.ruff.lint]` | `select = ["E","F","W","I","UP","B","C4","SIM","RUF"]`, `ignore = ["E501"]` — the formatter owns line length |
| `[tool.ruff.format]` | `quote-style = "double"`, `docstring-code-format = false` |
| `[tool.pylint.main]` | `py-version = "3.11"`, `ignore-paths = ["^docs/"]` |
| `[tool.pylint.messages_control]` | `disable = ["fixme"]` — the `# TODO: [MVP]` / `[RELEASE]` markers are the deliverable, not the debt |
| `[tool.pylint.design]` | wide contracts tolerated (`max-attributes`, `max-args`, `max-positional-arguments` = 20) |
| `[tool.pylint.format]` | `max-line-length = 100` |
| `[tool.coverage.*]` | `TBD` — declared as the single home but no coverage options are set yet |

## E. The four gates

```bash
pytest                  # tests green, no engine installed, no install step
ruff check .            # linter, includes import order (I)
ruff format --check .   # formatter, the authority on line length
pylint src tests        # fixme disabled; the rest clean
```

- `docs/` is excluded from Ruff and Pylint on purpose: the specification contains Python code
  blocks, and a formatter that rewrites a frozen artifact is worse than one that skips it.
- A suppression must be **inline with a stated reason** (`# pylint: disable=<rule>` plus a
  comment, or a `per-file-ignores` entry) — a silent config-wide disable is not acceptable.
- A `# type: ignore[...]` must name the error code; a bare one is rejected.
- Docs-only changes run the four gates anyway, as a regression check (this page included).

## F. Failure modes and our error mapping

Not applicable in the engine sense — but the equivalent rule matters: **a gate that passes
without exercising anything proves nothing.** The plan's answer is the mutation-evidence
record (`README.md` §7): every invariant test leaves *Invariant / Mutation / Observed failure
/ Restored green*, and a record whose mutation did not turn its test red is a defect of the
test. `GEN-16` audits the set.

## G. Seam ownership and the double

- None. No processor imports a test tool, and nothing under `src/docflow/` imports `tests/`
  (guarded by `test_no_module_under_src_imports_the_test_tree`).
- The engine doubles live under `tests/fakes/engines/`; the test tooling only *runs* them.

## H. Cost, latency and limits

- The suite is intentionally cheap: it never invokes an engine, and `pytest` completes in
  seconds locally (last observed: 68 tests). Cost is the reason the "no third-party in the
  suite" decision exists (`docs/feedback/test-suite-cost.md`).
- The real cost moves to CI, where the whole suite must run on a machine with **no engine
  installed** (`GEN-21`).

## I. Alternatives and swap story

- Out of scope for a PoC: swapping `pylint` for another linter is a plan revision, not a
  seam change, and `ruff` already covers most of what `pylint` does. The two exist because
  the plan says so.

## J. Open questions and drift log

- [ ] Floors vs. exact pins: the installed versions are well above the declared floors on every tool.
- [ ] `[tool.coverage.*]` is named as a config home but is empty — decide whether coverage is a gate or a report.
- [ ] Drift log: (2026-09-24) recorded installed versions above; the four gates pass with 68 tests.
