# Plan — apply the test-tier decision to `docs/plan/`

> Status: **superseded.** Derived from `test-suite-cost.md` §5.
>
> ⚠️ **This work order was applied and then partially reverted:** the plan no longer records
> engine responses, runs no real-engine tier and registers no `engine` marker. See
> [`no-tests-on-third-parties.md`](no-tests-on-third-parties.md), which wins over this
> document. What survives is the *shape* of the revision — one double per processor, no
> fallback, nothing under `src/docflow/` importing `tests/`, mutation-falsified invariants —
> now delivered as in-memory engine doubles instead of recordings.
> **Documents only.** This plan changes plan text. The code deliverables it records
> (`GEN-21`, `GEN-22`, `PDF-14`, `IMG-15`, `OCR-14`) become WBS rows — nothing is
> implemented, no test is written, no recorder is built here.
>
> Scope: `docs/plan/*.md` (6 files) and `docs/plan/issues/*.md` (6 files).
> Out of scope: `docs/idea/` (read-only), `src/`, `tests/`, `.github/`. The `pyproject.toml`
> marker registration is a WBS row (`GEN-05`), not an edit in this plan.

## 0. Rules that constrain this update

- These are frozen artifacts: this is a **plan revision**, and each edited file's
  `Status: proposed` header stays as it is.
- IDs stay unique and non-overlapping (`wbs-general.md` §7), and ranges stay legible: an ID
  range is cited in **5+ places per processor** (subplan WBS table, WBS header, WBS §1
  summary, `wbs-general.md` §1 child ranges, `wbs-general.md` §4 "Issues").
- **A half-updated range has already happened twice in this repository** (the lab-tool
  removal). Every phase below ends with a grep sweep, not a visual check.
- The four QA gates run after every phase: `pytest`, `ruff check .`, `ruff format --check .`,
  `pylint src tests`. `docs/` is excluded from Ruff and Pylint, so the gates are a regression
  check, not a lint of the new prose.
- No new config file; no second source of truth. The decision lives once in
  `README.md` §9 and is cited elsewhere.

## 1. Before touching anything

### 1.1 Three decisions to close

| # | Decision | Recommendation |
|---|---|---|
| 1 | **Per-processor task IDs** — each processor has exactly **one** free slot (`PDF-14`, `IMG-15`, `OCR-14`), so there is no general choice: use them, or renumber the whole range. At `GEN-*` there is no choice either — **one** slot was freed (`GEN-21`) and **two** cross-cutting tasks are needed, so by construction one is reused and the other appended | **Use the free slots.** Contiguous ranges, one fewer edit per citing document |
| 2 | **Recorder location** — `tests/record_engine.py` or a re-introduced `scripts/` | **`tests/record_engine.py`**: dev tooling, not library code, and it keeps `src/` clean of anything test-shaped |
| 3 | **CI** — create `.github/workflows/` as part of this initiative, or state the gate is manual | **Create it** — `GEN-21`, per the C1 table below. Verified: the repository has no pipeline today, so "the gate runs everything" is currently a habit, not a mechanism |

> The `GEN-*` numbering is **not** decided here: §1.2's C1 table is its single source, and
> `test-suite-cost.md` §5 has been corrected to match it. An earlier draft of this document
> assigned the CI to `GEN-22` in §1.1 and to `GEN-21` in §1.2 — the same half-updated-range
> defect this plan warns about, produced by the plan itself. Hence the numbering grep in §6.1,
> run **before** Phase A.

### 1.2 Corrections to §5 of `test-suite-cost.md`, to apply while landing it

**C1 — dependency inversion (material).** As first drafted, the recorder was a single
cross-cutting task depending on **all three** primitives seams, while the three per-processor
tasks *consumed* it. That serialises three parallel tracks behind one task and makes every
processor's test task wait for its two siblings. (`test-suite-cost.md` §5 has since been
corrected to match what follows.) Decompose instead:

| Task | Scope | Depends on | Phase |
|---|---|---|---|
| `PDF-14`, `IMG-15`, `OCR-14` | **local**: the recording for that engine, its replay loader, its version check | that processor's seam only (`PDF-02` / `IMG-02` / `OCR-02`) | the processor's own phase |
| `GEN-21` | **cross-cutting**: the CI gate workflow | `GEN-05` | 4 (close-out) |
| `GEN-22` | **cross-cutting**: the recording convention stated once + compliance verified across the three processors + the residual-risk entry in `GEN-17` | `PDF-14`, `IMG-15`, `OCR-14` | 4 (close-out) |

This keeps the three tracks parallel, gives both cross-cutting rows the shape the plan already
uses for `GEN-18`/`GEN-19`/`GEN-20` (verification of others' work), and keeps Phase 4's range
contiguous as `GEN-11`…`GEN-22`.

> **This table is the single source of the `GEN-*` numbering.** `test-suite-cost.md` §5 has
> been corrected to match it — it previously gave the recorder to `GEN-21` and the CI to
> `GEN-22`, which the decomposition above replaces. If the two documents ever disagree again,
> this table wins and the other document is fixed.

**C2 — the convention is a decision, not a task.** The naming/layout/format rules belong in
`README.md` §9.7 (Phase A below), so a Phase 1 author can cite them. Only *compliance* is a
task (`GEN-22`).

**C3 — the §1 totals table needs recomputation, not subtraction.** It was already wrong
before this revision (phase rows summed to 95 against a stated 100). Compute it **last**,
from the final rows, in Phase D.

### 1.3 Snapshot

Commit the current state (or note the SHA) before editing, so the revision is revertible and
the diff is reviewable in isolation.

## 2. Phase A — `docs/plan/README.md` (the anchor; everything else cites it)

| # | Edit | Where |
|---|---|---|
| A1 | New resolved decision **#7** | §9 |
| A2 | What `pytest` means | §7 |
| A3 | Phase 0 deliverables: the recordings convention and the `tests/fixtures/engines/` layout | §5, Phase 0 |
| A4 | Phase 4 deliverables: the frontier assertion and the compliance check | §5, Phase 4 |
| A5 | Package-layout tree: add `tests/fixtures/engines/` | §4 — *optional; decide, don't leave it implicit* |

**A1 — literal text to insert as decision #7:**

> **Test tiers and engine recordings — RESOLVED.** The real engine runs exactly once per
> processor, as phase-exit evidence (the happy path of `PDF-13` / `IMG-13` / `OCR-12`). Every
> other test in `pdf`, `image` and `ocr` runs on a **recorded engine response** replayed
> through the real code, injected at the engine call and nowhere higher — the same pattern the
> plan already applied to `llm` (`LLM-03`) and to the orchestrator (contract fakes,
> `subplan-orquestador.md` §6). A replay is never a fallback: there is no
> `if engine is None: use_fake`, and nothing under `src/docflow/` imports `tests/`. The replay
> loader fails loudly when the recorded version does not match the pin in `pyproject.toml`,
> and the real tier skips with an explicit reason when the engine is absent. `llm` keeps its
> scripted fake (`LLM-03`) deliberately: LLM responses are not deterministic for a fixed
> input, and `LLM-08` needs a scripted sequence.

**A2 — literal text to insert in §7:**

> `pytest` with no flags still means "everything", including the single real-engine test per
> processor. `pytest -m "not engine"` is a documented inner-loop shortcut and never a gate;
> `pytest -m engine` runs the real tier. When the engine is not installed, the real tier
> **skips with an explicit reason** instead of failing.

**Verification:** `grep -n 'engine' docs/plan/README.md`; the four gates.

## 3. Phase B — the three processors (three independent tracks)

One track per processor. Each track is a **pair** of documents that must be edited in the same
pass, or the subplan and its WBS disagree.

| # | File | Edit |
|---|---|---|
| B.1 | `subplan-procesador-<x>.md` | §3 Design: the recording for this engine, its format, its injection point (from the §3.3 table of `test-suite-cost.md`), and **which layer is recorded** — the engine's **native** output, substituted at the engine call. Never our translated type, and never at `extract_docling_*`: recording the translated result would delete the translation layer's coverage, which is half the reason the replay exists |
| B.2 | `subplan-procesador-<x>.md` | §4 WBS: new row — `PDF-14` / `IMG-15` / `OCR-14`, Effort S, depends on the processor's primitives seam, blocks the tasks whose tests need engine data. **Deliverables include that engine's path in `tests/record_engine.py`** (see the template below) |
| B.3 | `subplan-procesador-<x>.md` | §6 Test plan: split into **fast** (invariants, classification, validation, atomic publication → replay) and **real** (the one happy path → real engine) |
| B.4 | `subplan-procesador-<x>.md` | §6/§7 Error paths: classify **every existing failure fixture** of this processor into the three buckets below, and state explicitly whether the real engine runs on that path |
| B.5 | `subplan-procesador-<x>.md` | §7 DoD: the tier requirement, the version check, the skip-when-absent rule, and this processor's acceptance scenarios — the template in §3.1 below, parameterised by `<engine>` |
| B.6 | `issues/wbs-procesador-<x>.md` | header ID range, §1 summary (`# tasks`, effort distribution), §2 index row, §3 detailed issue + Gherkin, §4 dependency graph, §5 waves |

**Per-processor specifics — do not generalise these away:**

| Processor | What its §6/§3 must say |
|---|---|
| `pdf` | Poppler is reached through **CLI subprocesses**: the recording is artifacts plus a `sidecar.json` (exit code, stderr) and the replay intercepts `subprocess.run`, not a return value. A session-scoped fixture buys nothing here. `dpi` is not a lever on the fake — it is a per-test option. |
| `image` | The one real test must assert **2–3 concrete metric values with a tolerance** (blur / sharpness / contrast), not `status == "success"`: the whole metric computation lives inside the primitives the replay replaces, so OpenCV drift would otherwise be invisible. `IMG-09`'s `LOW_QUALITY` threshold stays a unit test over crafted `ImageMetrics`. |
| `ocr` | The recording captures Docling's **native** output and the substitution happens at `convert_image_with_docling` — never at `extract_docling_*`, which is the half of the module the replay must exercise rather than replace. The replay returns blocks in **adversarial (unsorted) order** so invariant 1 discriminates. The engine-determinism check (two conversions, compare `document.json`) is **folded into the same real test** — one test, two conversions — not a separate suite run. If a cached corpus helper is reused, the cache key must include **which engine** produced the result. |

### 3.1 Phase B.4 — the error paths, in three buckets

Every failure fixture that already exists in the plan must be classified explicitly, because
the answer decides whether the real engine runs on that path at all:

| Bucket | Test mechanism | Where it applies |
|---|---|---|
| **Pre-engine** — **our** code decides before any engine call | an ordinary unit test: no engine, no recording | `pdf_corrupt.pdf`, *if* `validate_pdf`'s fail-fast returns `CORRUPTED_PDF` before Poppler is invoked |
| **Recordable** — the engine call fails deterministically on a real bad input | the failing call is recorded once, and the replay raises what was recorded | `corrupt.png` → `DECODE_ERROR` from the decode call |
| **Injected** — the engine breaks in a way no input reproduces | `monkeypatch` forces the exception; never a recording | `OCR-04`'s "engine raises during conversion" |

The rule that keeps the "once per processor" promise intact: **the `record` step covers every
input the tests use, good and bad**, so a recorded failure costs no live run at test time.
Which bucket a case falls into is a *finding* of this edit, not an assumption — and the
`pdf_corrupt.pdf` row is the one to check first, since a fail-fast validation may mean that
case needs no recording at all.

**Phase B.5 — acceptance template, per processor, parameterised by `<engine>`:**

```gherkin
Scenario: The replay refuses a stale recording
  Given a <engine> recording made for version A
  And a pin in pyproject.toml for version B
  When the fast tier runs
  Then the replay loader fails loudly, naming both versions
  And it does not serve the stale recording

Scenario: The real tier skips when the engine is absent
  Given an environment without <engine> installed
  When the real tier runs
  Then the <engine> tests are skipped with an explicit reason
  And the gate does not fail

Scenario: The fast tier never reaches <engine>
  Given the recorded fixtures and the replay loader
  When "pytest -m 'not engine'" runs
  Then every test of this processor passes with zero <engine> invocations
  And no <engine> module or binary is touched
```

**New WBS row template** — note the deliverables: the recording, the replay loader, **and that
engine's entry point in the shared recorder**. Without the third one the task can close with a
fixture authored by hand instead of a real recording — exactly the risk this design exists to
remove:

```
| PDF-14 | Engine recording + replay loader for Poppler | S | 2 — Primitives | PDF-02 | `tests/record_engine.py` (Poppler path), `tests/fixtures/engines/poppler/`, `tests/fakes/engines/replay_poppler.py` | this file §PDF-14 | NOT_STARTED |
```

**Verification per track:** `grep -n 'PDF-01\|PDF-13\|PDF-14' docs/plan/subplan-procesador-pdf.md docs/plan/issues/wbs-procesador-pdf.md docs/plan/issues/wbs-general.md` — every range citation updated, none half-updated. Then the four gates.

## 4. Phase C — the two neighbours (one line each)

| # | File | Edit |
|---|---|---|
| C1 | `subplan-procesador-llm-call.md` §6 | `LLM-03` stays a **scripted fake**, deliberately: record/replay does not apply to `llm` because responses are not deterministic for a fixed input and `LLM-08` needs a scripted sequence. Without this line someone will "unify" the two patterns later |
| C2 | `subplan-orquestador.md` §6 | One sentence: its `FakePdf`/`FakeImage`/`FakeOcr`/`FakeLlm` are **contract-level** fakes (they replace whole processors), while the new replays are **primitives-level** (they replace only the engine inside a real processor). Without it a reader will reuse one for the other |
| C3 | `issues/wbs-procesador-llm-call.md`, `issues/wbs-orquestador.md` | Mirror C1/C2 in the corresponding WBS — one line each, or explicitly note that the WBS inherits it from the subplan |

## 5. Phase D — `docs/plan/issues/wbs-general.md`

| # | Edit | Where |
|---|---|---|
| D1 | Phase 1 child ranges gain the three new local tasks; Phase 1 task count grows by 3 | §1 summary |
| D2 | Phase 4 range becomes `GEN-11`…`GEN-22` (12 tasks) | §1 summary |
| D3 | **Recompute the totals row from the rows** (C3). Do it after D1/D2, never before | §1 summary |
| D4 | Two new issue blocks with the full format: `GEN-21` (CI gate workflow, S) and `GEN-22` (recording convention + compliance, S/M), each with objective, scope, out-of-bounds, evidence/DoD, tags and Gherkin | §2 |
| D5 | Phase 0 and Phase 4 deliverable/issues lines | §4.1, §4.5 |
| D6 | Critical path: add the close-out rows if the chain lengthens | §5 |
| D7 | New risk row: a bumped engine pin with a stale recording leaves the fast tier green proving a reality that no longer exists | §6 |
| D8 | DoR/DoD: the tier requirement, the version check, the skip-when-absent rule | §7, §8 |
| D9 | Resolved-decisions index: point at `README.md` §9.7 | §10 |

**Gherkin: which scenario belongs to which task.** The three per-loader scenarios (stale
recording, absent engine, fast tier reaches no engine) exercise **one** loader, so per §1.2 C1
they are the per-processor DoD template in Phase B.5 — already written there, parameterised by
`<engine>`. Hanging them off `GEN-22` would re-specify each loader inside a cross-cutting task,
which is the inverted dependency C1 exists to undo. `GEN-21` and `GEN-22` get their own,
genuinely cross-cutting scenarios:

```gherkin
# GEN-21 — the gate
Scenario: The gate blocks a fast-only green pull request
  Given a pull request whose fast tier is green and whose real tier fails
  When the CI workflow runs
  Then the check fails and the pull request is blocked

Scenario: A skipped real tier in CI is a failure
  Given a CI environment without the engine installed
  When the workflow runs the real tier
  Then the job fails instead of reporting a skip
  And the missing engine is named in the failure

# GEN-22 — cross-compliance
Scenario: The three loaders agree on the version rule
  Given the three replay loaders of pdf, image and ocr
  When each is handed a recording whose version differs from the pin
  Then all three fail loudly, naming the two versions
  And none serves the stale recording

Scenario: Every recording declares its provenance
  Given the recordings under tests/fixtures/engines/
  When they are audited
  Then each carries the engine version and the schema version it was made from
  And no recording is a hand-authored fixture without provenance
```

## 6. Phase E — sweep, evidence, commit

### 6.1 Sweep (both have bitten before)

Run the **first** block before Phase A; the rest after Phase E.

```bash
# 1. the two documents agree on the GEN-* numbering — this is how §1.1 and §1.2
#    of this very work order contradicted each other, each text valid on its own
grep -n 'GEN-2[12]' docs/feedback/plan-update-test-tiers.md docs/feedback/test-suite-cost.md

# 2. no half-updated ranges anywhere
grep -rn 'PDF-01.*PDF-1[34]\|IMG-01.*IMG-1[56]\|OCR-01.*OCR-1[45]' docs/plan/
# 3. the new IDs appear in every place that must cite them
grep -rn 'GEN-21\|GEN-22\|PDF-14\|IMG-15\|OCR-14' docs/plan/ | wc -l
# 4. no dangling reference to a removed task or a superseded section
grep -rn 'conformance\|nightly' docs/plan/
# 5. the decision is stated once and cited, not restated
grep -c 'recorded engine response' docs/plan/README.md
```

### 6.2 Gates

`pytest` · `ruff check .` · `ruff format --check .` · `pylint src tests` — all four, on the
whole tree.

### 6.3 Evidence to capture

The sweep output, the four gate outputs, the recomputed totals row, and the diff of the
totals row before/after (it changes numbers a reader may have memorised).

## 7. What this plan deliberately does not do

- **No renumbering** of existing IDs. Reuse the freed slots or append; never renumber, because
  renumbering rewrites every citation in six documents and the phase gates that froze them.
- **No edits to `docs/idea/`** — it is exploration, read-only for this change.
- **No implementation.** `GEN-21`/`GEN-22`/`PDF-14`/`IMG-15`/`OCR-14` are rows; building the
  recorder, the loaders, the CI workflow and the fixtures is separate work that starts from
  `NOT_STARTED`.
- **No fixture deletion in this plan.** Removing the 70 MiB corpus touches `tests/`, which is
  outside a documentation update; it is recorded as a deliverable of `GEN-22` and executed
  with the code work.
- **No second phrasing of the decision.** It is written once in `README.md` §9.7; every other
  document cites it.

## 8. Definition of Done for this update

- The decision, the `pytest` semantics and the recordings convention are in `README.md` §9/§7/§5.
- Each of `pdf`, `image`, `ocr` has: a recording + replay task in its WBS row **including its
  path in `tests/record_engine.py`**, a fast/real split in §6, its per-engine recording format
  with the recorded layer named (native output, not our translated type), its own caveat
  (subprocess / metric tolerance / adversarial order), and **its failure fixtures classified**
  into the three buckets of §3.1.
- `llm-call` and `orquestador` carry their one-line clarifications.
- `wbs-general.md`: both new issues exist in full format with their own scenarios, all ranges
  are consistent, and the totals row is **recomputed from the rows**.
- The sweep in §6.1 is clean and the four gates pass.
- Every change traces to a numbered item in this plan; nothing extra was added.

## 9. Risks specific to this update

| Risk | Why it is real here | Mitigation |
|---|---|---|
| A half-updated ID range | It has already happened twice (lab-tool removal) | The grep sweep at the end of every phase (§6.1), not a visual check |
| The totals row stays wrong | It was wrong before this change | D3 computes it from the rows, last |
| The dependency inversion ships | §5 of the feedback doc, read literally, serialises the three tracks | Correction C1 in §1.2, applied before Phase B |
| Two phrasings of the decision drift | Three documents could each restate it | §7: written once in `README.md` §9.7, cited elsewhere |
| **These two documents contradict each other on an ID** | It has already happened once *inside* this work order (§1.1 said `GEN-22` for the CI, §1.2 said `GEN-21`), and each text is valid on its own, so no range sweep catches it | The numbering grep in §6.1, run **before** Phase A; §1.2's C1 table is the single source |
| A cross-cutting task re-specifies a loader | The per-loader scenarios were initially drafted under `GEN-22` | §3 and §6.3: loader scenarios live in Phase B.5; `GEN-21`/`GEN-22` have their own |
| The task closes with a hand-authored fixture | The recorder was not a deliverable in the first template | The WBS row template in §3 carries `tests/record_engine.py`, and the `GEN-22` compliance scenario audits provenance |
| The skip rule masks a missing engine in CI | `skip` is silent by nature | The `GEN-21` scenario "a skipped real tier in CI is a failure" |

## 10. Rollback

The revision is confined to plan text: `git revert` of the update commit restores the frozen
state exactly, and no code, test or fixture depends on it. If a phase is landed alone, revert
that phase's commit — which is why §1.3 wants the snapshot taken before Phase A and each phase
committed on its own.
