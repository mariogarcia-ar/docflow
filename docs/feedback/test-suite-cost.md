# Test cost — how we fix it

> Status: **proposed**. Solution-first: what the problem is, how we solve it, what it costs,
> and what still needs a decision. Measurements are in the git history of this file; the
> long analysis that preceded this revision was superseded — its conformance-test framing is
> replaced by the recording mechanism in §3.

## 1. The problem, briefly

`pdf`, `image` and `ocr` have **no test double**. Every test — including the invariants for
ordering, timestamps, atomic publication and validation — runs the real engine just to get
data. The plan already gave a double to `llm` (`LLM-03`) and to the orchestrator (contract
fakes); it never copied the pattern to the other three.

Today that is invisible: 61 tests, 0.23 s, no engine imported. It arrives with `PDF-13`,
`IMG-13` and `OCR-12`. On `release1` it had already arrived: 31 test modules drive an engine,
the OCR module pays for roughly 10–16 Docling conversions, and a 70 MiB corpus sits committed
inside `tests/fixtures/` that no test reads.

## 2. What we actually test

We do **not** test Docling, Poppler or OpenCV. They work. We test our own code:

| Our code | Covered by |
|---|---|
| Contracts (`contracts.py`) | tests with no engine at all — already done |
| Composition and builders: ordering, naming, tables, Markdown/JSON, validation, atomic publish, classification, metadata | tests on **data we control** |
| The adapter lines in `primitives/`: which flags, which options, decoding stdout, exit codes | only the **real engine** exercises these |
| Our assumptions about the *shape* the engine returns | needs **real engine data as input** — not a live engine |

## 3. The solution

### 3.1 The principle

> The real engine runs **once per processor** (the phase-exit happy path). Everything else
> runs on a **recorded real response**, replayed through our real code.

### 3.2 Record once, replay always

```
real engine, once ──► tests/fixtures/engines/<engine>/<version>/…
                             │
                             ▼
                  replay loader (the test double)
                             │
                             ▼
   our translation → our builders → our validation → our publish → entry point
              (the entire fast tier runs real code on real-shaped data)
```

The double is not a fake we invent. It is **a recording of what the engine really returned**,
fed in at the lowest possible point — the engine call itself — so everything above it runs
for real.

### 3.3 Recording formats, per engine

The three engines do not hand back the same kind of thing, so the recording and the injection
point differ per processor. A single generic mechanism would not work.

| Engine | What it hands back | What we record | Where the replay is injected |
|---|---|---|---|
| **Docling** (OCR) | a Python object (`DoclingDocument`), not JSON | the **native** values Docling returns — text, markdown, tables, blocks, layout, metadata — as JSON with `schema_version` and `engine_version` keys. **Not** our translated `OCRDocument`, and never substituted at `extract_docling_*`: that would delete the translation layer's coverage | the engine call `convert_image_with_docling` |
| **Poppler** (PDF) | **files** (`page.pdf`, `page.png`, `text.txt`, embedded images) plus exit code and stderr — no return value | the artifacts copied verbatim, plus a `sidecar.json` with exit code and stderr | the **`subprocess.run` call** |
| **OpenCV** (Image) | NumPy pixel arrays, not JSON-serialisable | the output image as PNG plus a `metrics.json`; raw arrays (`.npy`) only where a test needs them | the `image/primitives/` functions (`load_image`, the transformations) |

```
tests/fixtures/engines/docling/<engine_version>/<fixture-stem>.json
tests/fixtures/engines/poppler/<engine_version>/<fixture-stem>/{artifacts…, sidecar.json}
tests/fixtures/engines/opencv/<library_version>/<fixture-stem>/{image.png, metrics.json}
```

Two consequences:

- the **PDF replay is a different mechanism** from the OCR/Image ones — it intercepts a
  subprocess, not a function call — so it cannot share the same helper;
- the OCR recording is defined by *what our translation consumes*. A field we do not read is
  not recorded, and a field we start reading needs a re-record. That is deliberate: the
  recording is an interface, not an archive.

### 3.4 Two kinds of failure, two mechanisms

| Failure | Example | Mechanism |
|---|---|---|
| **Recordable** — the real engine fails deterministically on a real bad input | truncated PDF → `CORRUPTED_PDF`; corrupt PNG → `DECODE_ERROR` | one live run against `pdf_corrupt.pdf` / `corrupt.png`, recorded like any other input. The tier stays fast. |
| **Injected** — the engine itself breaks | internal exception, timeout, `ENGINE_ERROR`; the subplans demand a test where the engine raises mid-conversion (`OCR-04`) | a **monkeypatch that forces the exception**. Not recordable: no real input guarantees the same explosion twice. |

Both are required. They must not be confused, because the second cannot be made reproducible
by recording.

### 3.5 Three tiers

| Tier | Runs | What it proves | Cost |
|---|---|---|---|
| **fast** — `pytest -m "not engine"` | every commit | all of our logic, on recorded real-shaped data | seconds, works with no engine installed |
| **real** — `pytest -m engine` | the gate | our adapter lines, and that the recording is still valid | 1 test per processor |
| **record** — `python -m tests.record_engine` | when the engine pin changes | refreshes the recording; the diff *is* the drift evidence | manual, reviewed |

**The version must match, loudly.** The replay loader reads the engine version pinned in
`pyproject.toml` and **fails explicitly** if it does not match the recording directory it is
about to use. Without that check the mechanism inherits exactly the silent-staleness failure
already observed with the stale `manifest.json` (99 files recorded, 105 present): a bumped pin
plus a forgotten re-record would leave the fast tier green, proving a reality that no longer
exists.

**An absent engine skips, it does not fail.** If the engine is not installed in the
environment, the real tier skips with an explicit reason. A clone without the heavy
dependencies must still be able to run the fast tier and the other three gates.

### 3.6 Why a recording instead of a hand-written fake

- It **cannot drift from reality** — it *is* reality, at the recorded version.
- Our translation is exercised against real engine structures, not against our guesses.
- Refreshing it is a deliberate act whose diff a reviewer can read.

**What we deliberately give up.** Dropping the structural fake-vs-real conformance test means
the single real test could, in principle, pass its invariants while a Docling shape change
breaks our parsing on a branch that test does not exercise. That is a conscious PoC trade-off:
the recording plus the version check catch most drift, and the residual risk is named as a
resolved decision in `GEN-17` instead of being presented as covered.

### 3.7 What does not move: `LLM-03`

Record/replay applies to `pdf`, `image` and `ocr` **only**. `llm` keeps its scripted fake on
purpose: LLM responses are not deterministic for a fixed input, and `LLM-08` needs a scripted
*sequence* (invalid JSON on attempt 1, valid on attempt 2). Unifying the two patterns later
would be a mistake; the plan should say so explicitly.

## 4. How we carry it out, in order

1. **Record, per engine**, in the formats of §3.3. Docling and OpenCV produce payloads;
   Poppler produces artifacts, so its recording also captures exit code and stderr.
2. **Build the replay loaders.** One per engine — the Poppler one intercepts `subprocess.run`
   and cannot share code with the other two. Each loader asserts that the pinned version
   matches its recording directory and fails loudly otherwise.
3. **Fast tier.** Every invariant, builder, table, validation, atomicity and classification
   test runs on the replay. The awkward cases (unsorted blocks, empty text, bbox outside the
   unit range) are extra recordings or edited replays — inputs we choose, which is the point.
4. **Both failure mechanisms** (§3.4): recorded for bad real inputs, monkeypatched for engine
   breakage.
5. **One real test per processor**, asserting **our** invariants on live output — block count
   > 0, every bbox normalised 0–1, `engine_version` non-empty, artifact set exactly matching
   the namespace, input hash unchanged — never a claim about engine quality. Skips if the
   engine is absent.
6. **Drift check on pin bump.** Bumping the pin means re-recording and re-running step 5. No
   nightly job, no conformance suite: those were testing the third party.
7. **Gate unchanged.** `pytest` with no flags keeps meaning *everything*, including the real
   tier. `pytest -m "not engine"` is only a local-loop shortcut.

## 5. What changes in the plan

IDs reuse the slots freed by the lab-tool removal, so every range stays contiguous.

| Where | Change |
|---|---|
| `README.md` §9 | new resolved decision: test tiers, the recording, the version check, `LLM-03` unchanged, skip-when-absent |
| `README.md` §7 | one sentence: `pytest` = everything; `-m "not engine"` is a local shortcut, not a gate |
| `subplan-procesador-{pdf,image,ocr}.md` | the replay task per processor, §6 split into fast / real tiers, and that processor's recording format from §3.3 |
| `subplan-procesador-llm-call.md` §6 | one line: `LLM-03` stays a scripted fake, deliberately (§3.7) |
| `subplan-orquestador.md` §6 | one sentence separating its contract-level fakes from these primitives-level replays |
| `pyproject.toml` (`GEN-05`) | register the `engine` marker — **mandatory**, `--strict-markers` is already on |
| `wbs-general.md` (`GEN-19`) | assertion: no module under `src/docflow/` imports anything under `tests/` |
| `wbs-general.md` (`GEN-17`) | record the trade-off in §3.6 as a resolved decision, not as a non-issue |
| `tests/fixtures/` | delete the 70 MiB corpus; add the three minimal fixtures the subplans name, with a per-processor size ceiling |

**Two new cross-cutting tasks**, in the same format as every other WBS row:

| ID | Task | Effort | Depends on | Acceptance |
|---|---|---|---|---|
| `GEN-21` | CI gate workflow, `.github/workflows/gates.yml`: all four gates, `pytest` unfiltered, plus the weekly `pytest -m engine` run | S | `GEN-05` | a PR whose fast tier is green and whose real tier fails is blocked; a skipped real tier in CI fails the job instead of passing |
| `GEN-22` | Recording convention stated once (formats, paths, version check), compliance verified across the three processors, and the residual risk recorded in `GEN-17` | S | `PDF-14`, `IMG-15`, `OCR-14` | the three loaders obey one version rule, and every recording declares its provenance |

> The per-processor decomposition and this numbering were corrected in
> [`plan-update-test-tiers.md`](plan-update-test-tiers.md) §1.2 (C1): the recorder is **local**
> to each processor, not a cross-cutting prerequisite, so the three tracks stay parallel. That
> section is the single source of the `GEN-*` numbering; if this table ever disagrees with it,
> the work order wins.

**Per-processor:** `PDF-14`, `IMG-15`, `OCR-14` — the recording, the replay loader and the
version check for that engine, **local to that processor** and depending only on its
`primitives/` seam. Each also owns that engine's path in the shared `tests/record_engine.py`,
so the task cannot close with a fixture authored by hand instead of a real recording. They gate
the tasks whose tests need engine data, and they do **not** depend on each other.

**Acceptance scenarios** are written once, in the work order, so the two documents cannot
drift: [`plan-update-test-tiers.md`](plan-update-test-tiers.md) §3.1 carries the per-processor
template parameterised by `<engine>`, and §6.3 the scenarios for `GEN-21` (the gate) and
`GEN-22` (cross-compliance).

## 6. What we get

| | Before | After |
|---|---|---|
| OCR module | ~10–16 real Docling conversions | 1 test, 2 conversions |
| PDF / Image | every primitive test hits the engine | 1 happy path each |
| Mutation cycles (`GEN-16`) | 2 full suites per invariant, engine-paid | fast tier — free |
| Inner loop | minutes, engines required | seconds, no engine installed |
| CI | none — the gate is a habit | every PR, unfiltered, plus a weekly real-tier run |
| Fixture tree | 70 MiB, unreferenced | a few small files |

## 7. Decisions taken, and what is still open

**Taken by this revision**

- CI is part of this initiative (`GEN-21`), not an orphan item.
- `LLM-03` does not migrate to record/replay (§3.7).
- An absent engine skips rather than fails (§3.5).
- IDs reuse the freed slots: `PDF-14`, `IMG-15`, `OCR-14` per processor, plus `GEN-21` (CI) and
  `GEN-22` (compliance) cross-cutting. **The numbering's single source is
  [`plan-update-test-tiers.md`](plan-update-test-tiers.md) §1.2**, which supersedes the
  assignment this section first carried. *The per-processor slot reuse needs your yes; the
  alternative is to append new numbers and record the gaps.*
- Dropping the structural conformance test is a named trade-off, recorded in `GEN-17` (§3.6).

**Still open**

- Where the recorder lives: `tests/record_engine.py` (my preference — dev tooling, not
  library code) or a re-introduced `scripts/` directory.
