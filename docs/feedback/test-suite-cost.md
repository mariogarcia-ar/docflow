# Test cost — how we fix it

> Status: **proposed**. This is the short, solution-first version. The measurements, the
> option analysis and the per-document review notes live in
> [`test-suite-cost-full.md`](test-suite-cost-full.md).

## 1. The problem, briefly

`pdf`, `image` and `ocr` have **no test double**. Every test — including the invariants for
ordering, timestamps, atomic publication and validation — has to run the real engine just to
get data. The plan already gave a double to `llm` (`LLM-03`) and to the orchestrator
(contract fakes); it simply never copied the pattern to the other three.

Today this is invisible: 61 tests, 0.23 s, no engine imported. It arrives with `PDF-13`,
`IMG-13` and `OCR-12`. On `release1` it had already arrived: 31 test modules drive an engine,
the OCR module pays for roughly 10–16 Docling conversions, and a 70 MiB corpus sits
committed inside `tests/fixtures/` that no test reads.

## 2. What we actually test

We do **not** test Docling, Poppler or OpenCV. They work. What we test is our own code:

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
real engine, once ──► tests/fixtures/engines/<engine>/<version>/<fixture>.json
                             │
                             ▼
                  replay loader (the test double)
                             │
                             ▼
   our translation → our builders → our validation → our publish → entry point
              (the entire fast tier runs real code on real-shaped data)
```

The double is not a fake we invent. It is **a recording of what the engine really returned**,
fed into the lowest possible point — the engine call itself — so that everything above it
runs for real.

### 3.3 Three tiers

| Tier | Runs | What it proves | Cost |
|---|---|---|---|
| **fast** — `pytest -m "not engine"` | every commit | all of our logic, on recorded real-shaped data | seconds, works with no engine installed |
| **real** — `pytest -m engine` | the gate | our adapter lines, and that the recording is still valid | 1 test per processor |
| **record** — `python -m tests.record_engine` | when the engine pin changes | refreshes the recording; the diff *is* the drift evidence | manual, reviewed |

### 3.4 Why a recording instead of a hand-written fake

- It **cannot drift from reality** — it *is* reality, at the recorded version.
- Our translation is exercised against real engine structures, not against my guesses.
- Refreshing it is a deliberate act whose diff a reviewer can read.

## 4. How we carry it out, in order

1. **Record.** For each processor, capture the engine's raw output once, into
   `tests/fixtures/engines/<engine>/<version>/`. Docling and OpenCV produce payloads; Poppler
   produces artifacts, so its recording also captures exit code and stderr.
2. **Replay.** `tests/fakes/engines/fake_<engine>.py` becomes a *loader* of that recording,
   injected at the engine call (`convert_image_with_docling`, `render_page_to_image`,
   `load_image`) — never higher, or the real coverage is lost.
3. **Fast tier.** Every invariant, builder, table, validation, atomicity and classification
   test runs on the replay. The awkward cases (unsorted blocks, empty text, bbox outside the
   unit range) become extra recordings or edited replays — inputs we choose, which is the
   point.
4. **One real test per processor.** It asserts **our** invariants on live output — block
   count > 0, every bbox normalised 0–1, `engine_version` non-empty, artifact set exactly
   matching the namespace, input hash unchanged — never a claim about engine quality.
5. **Drift check on pin bump.** Bumping the pin means re-recording and re-running step 4. No
   nightly job, no parametrized fake-vs-real conformance suite: those were testing the third
   party, which is not our job.
6. **Gate unchanged.** `pytest` with no flags keeps meaning *everything*, including the real
   tier. `pytest -m "not engine"` is only a local-loop shortcut.

## 5. What changes in the plan

| Where | Change |
|---|---|
| `README.md` §9 | new resolved decision: test tiers, the recording, the double is test-only and never a fallback |
| `README.md` §7 | one sentence: `pytest` = everything; `-m "not engine"` is a local shortcut, not a gate |
| `subplan-procesador-{pdf,image,ocr}.md` | a double task behind `primitives/`, and §6 split into fast / real tiers |
| `subplan-orquestador.md` §6 | one sentence separating its contract-level fakes from these primitives-level doubles |
| `pyproject.toml` (`GEN-05`) | register the `engine` marker — **mandatory**, `--strict-markers` is already on |
| `wbs-general.md` (`GEN-19`) | assertion: no module under `src/docflow/` imports anything under `tests/` |
| `tests/fixtures/` | delete the 70 MiB corpus; add the three minimal fixtures the subplans name, with a size ceiling |

## 6. What we get

| | Before | After |
|---|---|---|
| OCR module | ~10–16 real Docling conversions | 1 test, 2 conversions |
| PDF / Image | every primitive test hits the engine | 1 happy path each |
| Mutation cycles (`GEN-16`) | 2 full suites per invariant, engine-paid | fast tier — free |
| Inner loop | minutes, engines required | seconds, no engine installed |
| Fixture tree | 70 MiB, unreferenced | a few small files |

## 7. Still to decide

1. **IDs.** Reuse the slots freed by the lab-tool removal (`PDF-14`, `IMG-15`, `OCR-14`,
   `GEN-21`) or append new ones and record the gaps.
2. **CI.** The repo has no pipeline today. Either create `.github/workflows/gates.yml` or say
   plainly in the plan that the real tier is a manual checklist item.
3. **Recorder location.** `tests/record_engine.py` (my preference — it is dev tooling, not
   library code) or a `scripts/` directory.
