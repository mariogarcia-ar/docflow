# E01 — Segmentation & document identity

| Field | Value |
|---|---|
| Epic ID | **E01** |
| Capability | Cutting a file into documents that never merge across a real boundary, and naming each one with a type plus the evidence that produced it |
| Issues | `E01-01` (`S2-T01`) · `E01-02` (`S2-T02`) · `E01-03` (`S2-T03`) — all `todo` |
| Issue count | **3** |
| Owner layer | **Domain** (`wbs.md` §8) — `docflow/components/` |
| Wave span | **W1 → W3** (W1: 1 · W2: 1 · W3: 1) |
| Effort total | **2 × L · 1 × M** |
| Source plan | [`../../plan-02-components.md`](../../plan-02-components.md) §2, §4 entry conditions 6–7, §5 (`S2-T01`–`S2-T03`), §7b, §8, §9 execution risk 1, §12 open decision 1 (adjacent), §13 Track 2 |
| Depends on other epics | **none** — E01 is a root. Its only predecessor is `S1-T19`, which is a *Stage 1* task (`wbs.md` §4), so the edge crosses the gate rather than this graph |

---

## §1 Objective

E01 delivers the first thing the system does with a file: **decide where one document ends and another begins, and say what each one is** — with the reason attached. Its capability is not "a splitter and a classifier": it is that the file is cut **without merging two documents that were never one**, and that a type is emitted as *type plus evidence*, so a misclassification is explainable without re-running the extraction that consumed it.

It is a separate deliverable because it is the head of the one branch whose failure is **invisible to every other component**. A merged document contaminates fields across a boundary that no longer exists: shape passes, type passes, content passes, arithmetic closes — and the values belong to two different invoices. Nothing downstream can see it (`plan-02-components.md` §7b, row 1; §13 Track 2). That is why this capability carries the plan's only *residual accepted* risk (`plan-02-components.md` §9), and why over-segmenting on doubt is a fixed decision (ADR-007, `prd.md` FR-13) rather than a tuning choice: splitting a document that was whole is recoverable and visible; merging two is neither.

The re-segmentation loop (`E01-03`) belongs to the same capability because it is the *only* repair action segmentation is allowed, and its value is a **bound**: one pass. A loop without a cap is not a better Segmenter; it is a component that can silently iterate until it finds a split it likes.

**Position on the critical path — read this before scheduling.** E01 is **mandatory but is not the schedule driver.** Its chain is 3 links (`S2-T01 → T02 → T03`) against the longest chain's **9** (`plan-02-components.md` §5, `wbs.md` §6.2). Two consequences follow, and the plan names the first as **execution risk 1**:

- It *can* start later than `S2-T04` and still not delay the close.
- It **cannot be skipped, and it cannot slip past `S2-T17`** — `S2-T03` is a direct dependency of the gate (`wbs.md` §6.2). Starting the Segmenter in Wave 7 "because branch A is not the schedule driver" leaves the gate waiting on a three-link chain that was **available since Wave 1** (`plan-02-components.md` §9 risk 1). *Not the driver* is not *not required*.

The broader warning that produced `traceability.md` §7.3 defect 16 applies with full force here: *no pipeline invokes the Segmenter over the corpus* is true and is the declared permanent limitation; *the Segmenter does not gate Stage 2* is false. This epic exists to keep those two claims apart.

---

## §2 Issues in this epic

| Issue | `wbs.md` task | Title | Wave | Depends on | Effort | PoC markers |
|---|---||---|---|:---:|---|:---:|---|
| `E01-01` | `S2-T01` | Segmenter: cut detection (restarted numbering, new header, table continuity) + confidence per cut | W1 | `S1-T19` → **Stage 1** (cross-gate) | L | `# TODO: [MVP]`: real 3-invoice corpus fixture |
| `E01-02` | `S2-T02` | Identifier: type by text / by shapes / mixed, returning type **plus evidence**; low confidence routes to review | W2 | `S2-T01` → **E01** (intra) | L | `# TODO: [MVP]`: document-type catalog in K8 is minimal |
| `E01-03` | `S2-T03` | Re-segmentation loop with its **single** pass and page reuse | W3 | `S2-T02` → **E01** (intra) | M | — |

Intra-epic edges (not drawn as epic edges): `E01-02` → `E01-01`; `E01-03` → `E01-02` — **2 edges**.

E01 produces **exactly one inter-epic edge**: `E01 → E09` (`S2-T17` depends on `S2-T03`), which is drawn in the index README §3. There is deliberately **no `E01 → E03` edge**: the Segmenter feeds Diagnosis through the *file the demo walks*, not through a task dependency — `S2-T04` depends only on `S1-T12`/`S1-T13` (`wbs.md` §4). Anyone reading a stage chain into the epic graph should read §3 of the index README, where that is stated.

---

## §3 Issue detail

### `E01-01` — implements `S2-T01`

**Title**
Segmenter: cut detection (restarted numbering, new header, table continuity) + confidence per cut.

**Context**
The Segmenter's failure is the only one in Stage 2 that **nothing downstream detects**. If two documents are read as one, every field of the second document is extracted into the first: the shape check passes because each field is well-formed, the type check passes because the document type is plausible, the content check passes because the digits exist, and the arithmetic closes because each document's subtotal and taxes are internally consistent. The result is an answer that is wrong and **defensible**. `plan-02-components.md` §7b states what breaking the over-segmentation invariant looks like: *"a doubtful cut is merged; a `--no-oversegment`-shaped flag appears"*. This issue exists to make the doubtful case fall on the side that is *recoverable* — a spurious document is visible and can be merged back; a merged document is silent.

**Deliverable**
`docflow/components/segmenter.py`

**Depends on**
`S1-T19` — **cross-gate** (Plan 1 → Plan 2). The Segmenter is the first Stage 2 task and consumes a closed Stage 1: the frozen boundary types, the ports, and a synthetic flow that runs, is interrupted and resumes (`plan-02-components.md` §4 entry conditions 1–3). Intra-epic: none — this is the epic's root. Inter-epic: **none** (E01 → E09 appears only downstream of `E01-03`).

**Acceptance criteria**
- [ ] `docflow/components/segmenter.py` exists and emits cuts with a **confidence per cut**.
- [ ] Three cut signals are detected: **restarted numbering**, a **new header**, and **table continuity** across the boundary.
- [ ] A **doubtful cut over-segments** — a fixture whose cut is borderline produces a **split**, not a merge.
- [ ] There is **no flag to disable over-segmentation**; the contract test asserts the absence (`FR-13`, ADR-007).
- [ ] Every cut decision is recorded as **evidence**: the signal that fired, the confidence, and the page range — so a spurious split is explainable without re-reading the file.
- [ ] No threshold is a constant in this component: the cut confidence is `CUT_CONFIDENCE` from `registry/policies/` (`ADR-009`, `prd.md` NFR-06a).
- [ ] **No CLI flag and no environment variable** can set the cut confidence — asserted by a test that fails if one exists.
- [ ] The component imports **ports only**; it imports no adapter, and the import-isolation check `S1-T11` established passes over `docflow/components/segmenter.py`.
- [ ] No kernel API gained a domain noun to make this possible: the segmentation vocabulary lives here, not in K2/K3/K4.

**Test / evidence**
- `plan-02-components.md` §7b row 1 — *"The Segmenter over-segments when in doubt"*: test is a doubtful-cut fixture asserting a split, not a merge; **breaking it looks like "a doubtful cut is merged; a `--no-oversegment`-shaped flag appears"**; task cell `S2-T01` (`ADR-007`). This test must **fail** when the invariant is broken — a test that passes on both outcomes proves nothing.
- `plan-02-components.md` §5, `S2-T01`'s verifiable cell — *"A doubtful cut **over-segments**; there is no flag to disable it; cut decisions are recorded as evidence"*: the three acceptance criteria above are that sentence expanded.
- `plan-02-components.md` §8 — **FR-13**; proof is *"ADR-007 test: a doubtful cut is not merged; over-segmentation flag-absence test"*.
- `plan-02-components.md` §13, Track 2 — the *"Over-segment on doubt"* golden artifact is *"a file holding more than one document"*, and it **must fail** when broken, producing *"one merged document, whose fields contaminate each other — **silent, and no downstream check sees it**"*.
- `plan-02-components.md` §4 entry condition 7 — a corpus to close on is chosen (one text PDF, one image PDF) with the real 3-invoice fixture deferred.
- `plan-02-components.md` §11 — exit checklist item *"The Segmenter over-segments a doubtful cut; no flag exists to disable it"*.

**Out of scope for this issue**
- **No re-segmentation loop.** The single repair pass is `E01-03`; this issue emits the first cut set and nothing else.
- **No document typing.** What each segment *is* — by text, by shapes, mixed — is `E01-02`. A Segmenter that names a document type is a component doing two jobs.
- **No merged-document detection.** **Never** — no pipeline closes it (`wbs.md` §10, `plan-02-components.md` §2). Over-segmentation *mitigates*; the plan explicitly declares the gap, never claims it solved (`plan-02-components.md` §9, *"Residual risk accepted"*).
- **No `--no-oversegment`, `--cut-confidence` or any policy flag.** **Never** (ADR-007, ADR-009).
- **No threshold as a component constant.** **Never** (`prd.md` NFR-06a).
- **No adapter import.** **Never** (`sad.md` §1, `plan-02-components.md` §4 entry condition 6).
- **No real 3-invoice corpus fixture.** A synthetic one closes the flow. `# TODO: [MVP]`.
- **No page rendering or reading.** The Segmenter decides *where* to cut from the material it is given; the Reader (`E02-02`) produces tokens.

**Effort**
**L** — a load-bearing invariant whose failure is silent (`wbs.md` §7), three distinct cut signals that each need a fixture, plus an evidence record that must survive without re-running. Interacting concerns over a fixture-backed test rather than a heavyweight dependency.

**Owner**
**Domain** — `docflow/components/segmenter.py` (`wbs.md` §8).

**Frozen contract touched**
**Consumes** `plans/README.md` §3, Plan 1 row — the boundary types, the port interfaces and the descriptor shape — and adds **no new kernel-boundary type** (`plan-02-components.md` §4 entry condition 2). **Contributes to** the Plan 2 row's *component artifact chain*: `.<step>.json` — this issue produces the first artifact in the documented chain, `work/<name>.segments.json` (`sad.md` §9.1, `plan-02-components.md` §3).

---

### `E01-02` — implements `S2-T02`

**Title**
Identifier: type by text / by shapes / mixed, returning type **plus evidence**; low confidence routes to review.

**Context**
A misclassified document is not merely wrong — it is *unexaminable*. If the type is emitted as a bare label, then the only way to find out why a document was read as the wrong thing is to re-run the extraction, and by then the artifact that produced the decision is gone. `plan-02-components.md` §5 states the criterion as *"a misclassified document is explainable without re-running"*, which is the whole content of this issue: the decision carries **which words or which shapes triggered it**, and a confidence low enough to matter **routes to review instead of being resolved by the component**. The plan records this task's mapping as indirect rather than inventing an FR for it (§8's gap note) — the evidence requirement is what makes `FR-23`'s verdict vector explicable, and it is the guard for `wbs.md` §9's *"unknown wording variants"* risk, which becomes real at corpus scale.

**Deliverable**
`docflow/components/identifier.py`

**Depends on**
`S2-T01` — **intra-epic**. Externally: Plan 1's frozen row, via the chain E01 → (root) `S1-T19`.

**Acceptance criteria**
- [ ] `docflow/components/identifier.py` exists and returns a document **type** together with its **evidence**.
- [ ] Three typing routes exist — **by text**, **by shapes**, **mixed** — and the route used is recorded in the evidence.
- [ ] Evidence exposes **which words or which shapes** triggered the decision, not only a score or a label.
- [ ] An **`other` route exists**: a document the catalog cannot type is routed as `other`, never forced into the nearest known type.
- [ ] **Low confidence routes to review** rather than being resolved by the component.
- [ ] A misclassified document is **explainable without re-running**: the emitted evidence names the trigger.
- [ ] The document-type catalog is read from **K8**, not held as a constant in this file (`registry/`, `plan-02-components.md` §2's `# TODO: [MVP]`).
- [ ] The component imports **ports only**; the import-isolation check passes.
- [ ] No type name, no trigger word and no shape pattern is hardcoded in a way that would survive a registry edit — the registry hash must change when the catalog changes (`E03-02`'s term).

**Test / evidence**
- `plan-02-components.md` §5, `S2-T02`'s verifiable cell — *"Evidence exposes which words or shapes triggered the decision; an 'other' route exists; a misclassified document is explainable without re-running"*.
- `plan-02-components.md` §8 — **no FR of its own; see §5's gap subsection below.** *"`FR-23` in part (type evidence recorded)"*; proof is *"Evidence-exposes-trigger test; `other`-route test; explain-without-re-running test"*.
- `plan-02-components.md` §8, gap note — the mapping is **indirect** and *"indirect is recorded here rather than upgraded to direct"*. This issue does not upgrade it.
- `plan-02-components.md` §2, out of scope — *"A minimal document-type catalog in K8 (the Identifier ships with a minimal one)"*, marked `# TODO: [MVP]`.
- `wbs.md` §9 — *"Unknown wording variants in the corpus"* (H/H, owner stage 3): the mitigation chain runs through the Identifier's evidence, and the Reviewer's promotion path (`E07-01`) turns repeats into registry data.
- `plan-02-components.md` §11 — exit checklist item *"The 10 components each run standalone from the previous component's artefact"* is `E08-01`'s; this issue's artifact is the second link of that chain, `work/<name>.identity.json`.

**Out of scope for this issue**
- **No re-segmentation.** A segment that carries **two** types is `E01-03`'s signal and `E01-03`'s repair; this issue reports the type it found.
- **No extraction.** Typing a document is not reading fields from it; the Reader is `E02-02`.
- **No document-type catalog in K8 beyond the minimal one.** `# TODO: [MVP]` — the *catalog* is deferred, the *lookup* is not.
- **No confidence as a single score emitted to a consumer.** Verdicts are per-field and separate (`ADR-005`, `FR-23`); a component-level confidence score would be the very collapse ADR-005 forbids. **Never**.
- **No adapter import and no kernel-API change.** **Never** (`sad.md` §1).
- **No threshold as a component constant.** The confidence floor is registry data (ADR-009). **Never** as a constant or a flag.

**Effort**
**L** — three typing routes with distinct evidence, an `other` route, and an evidence record that must be sufficient to explain a wrong answer without re-running; needs fixtures per route (`wbs.md` §7).

**Owner**
**Domain** — `docflow/components/identifier.py` (`wbs.md` §8).

**Frozen contract touched**
**Consumes** `plans/README.md` §3, Plan 1 row — the ports and the boundary types. **Contributes to** the Plan 2 row's *per-field trace shape* at its origin: the evidence this issue emits is what a field's `extractor` and provenance ultimately derive from. It freezes nothing new.

---

### `E01-03` — implements `S2-T03`

**Title**
Re-segmentation loop with its **single** pass and page reuse.

**Context**
Re-segmentation is the repair the Segmenter's over-segmentation policy purchases, and it is only safe if it is **bounded**. A loop that re-cuts whenever it is unhappy can iterate until it finds a split it likes — and the intervening passes produce intermediate documents that were never the input, on a run that reports success. Two further properties matter as much as the cap: the second pass must **reuse pages already read** (otherwise the repair costs a full re-read of the file, and the artifact chain silently disagrees with itself), and a second pass that *still* returns two types must **route to review** rather than guess (`FR-14`). `plan-02-components.md` §7b states what breaking the cap looks like: *"a third pass exists; or the loop re-reads pages it already had"*.

**Deliverable**
`docflow/components/identifier.py` + `segmenter.py` — a **two-file** deliverable, which is why its owner layer is stated once and its close is conditional on both (`wbs.md` §4).

**Depends on**
`S2-T02` — **intra-epic**. Externally: Plan 1's frozen row via E01's root.

**Acceptance criteria**
- [ ] A segment carrying **two types** triggers exactly **one** re-segmentation pass.
- [ ] That pass **reuses pages already read** — the page reads are not repeated, and the reuse is assertable.
- [ ] A **second** pass that still returns two types **routes to review**; it does not guess and does not loop.
- [ ] **There is no third pass** — no loop without a cap exists in the code, asserted by a test that would detect one.
- [ ] The loop's single pass is **visible in the ledger/evidence** as one attempt, not as an implementation detail.
- [ ] `E01-01`'s over-segmentation invariant still holds after the repair: the loop may split further, never merge.
- [ ] Both files — `identifier.py` and `segmenter.py` — are exercised by the tests; the deliverable is not complete with one of the two untouched.
- [ ] No threshold introduced here is a constant: the "two types" signal is a comparison against registry policy, not a hardcoded rule.

**Test / evidence**
- `plan-02-components.md` §7b row 2 — *"Re-segmentation runs **once only**"*: test is a *"second pass still returning two types"*; **breaking it looks like "a third pass exists; or the loop re-reads pages it already had"**; task cell `S2-T03` (`FR-14`).
- `plan-02-components.md` §5, `S2-T03`'s verifiable cell — *"Two types in one segment → re-segment **once**, reusing pages already read; a second pass returning two types routes to review; there is no third pass"*.
- `plan-02-components.md` §8 — **FR-14**; proof is *"Second pass returning two types routes to review; page-reuse test"*.
- `plan-02-components.md` §13, Track 2 — the *"One pass of re-segmentation"* golden artifact is *"a segment containing two document types"*, and it **must fail** when broken: *"a third pass runs, or a loop without a cap"*.
- `plan-02-components.md` §11 — exit checklist item *"the re-segmentation loop runs exactly once and reuses pages already read"*.

**Out of scope for this issue**
- **No second repair mechanism.** One pass, then review. A third pass is not deferred — it is the failure the invariant names. **Never**.
- **No merged-document detection.** The loop splits; it never merges. Merging two documents the Segmenter separated is not a remedy the system has, and merged-document detection is **Never** (`wbs.md` §10).
- **No re-reading.** A pass that re-reads pages it already had is the second half of the invariant's failure mode. **Never**.
- **No unbounded loop, no retry until the types agree.** **Never** — the same prohibition shape as Plan 1's *"retry until two answers agree"* (`kernel-cli.md` §7).
- **No review UI.** Routing to review means *emitting a case*; the queue is `E07-01`'s, and the workflow UI is `# TODO: [MVP]` (`plan-02-components.md` §2).

**Effort**
**M** — a bounded loop with three testable properties (the cap, the page reuse, the review route), one of which is an invariant whose test must fail when broken; spans two files, with no heavyweight dependency (`wbs.md` §7).

**Owner**
**Domain** — `docflow/components/identifier.py` and `docflow/components/segmenter.py` (`wbs.md` §8).

**Frozen contract touched**
**Consumes** `plans/README.md` §3, Plan 1 row — the ports, the determinism classes (the segmenter's work is `deterministic`; a re-read of an OCR page is not) and the 7 durable ledger states. **Contributes to** the Plan 2 row's *component artifact chain*: the second pass rewrites `.<step>.json` rather than appending a new step, so Plan 3's ledger sees one `segmenter` stage, not two (`S3-T03`).

---

## §4 Epic close condition

E01 is **`done`** when:

1. all three issues are `done` — including `E01-03`, whose deliverable spans `identifier.py` **and** `segmenter.py`, so a green suite touching only one file does not close it;
2. the capability is **demonstrable**, and checked by running it: a **doubtful cut splits** on a fixture where the naive answer merges; the contract test **fails** if a `--no-oversegment`-shaped flag or a cut-confidence policy flag exists; a two-type segment produces **exactly one** re-segmentation pass with the page reads reused; and a second pass that still returns two types lands in review rather than in a third pass.

**Does E01 gate `S2-T17`?** **Yes, directly, and it is the branch the plan warns about.** `S2-T03` is named in `S2-T17`'s dependency set (`wbs.md` §4), making **E01 → E09** a direct inter-epic edge — the only edge E01 produces. It is also the **shortest** of the five branches (3 links against 9), which is exactly why `plan-02-components.md` §9 registers *"building branch A late"* as execution risk 1: the gate waits on it regardless of its length, and it has been available since Wave 1.

**Does E01 gate anything else?** **No.** E01 produces no other inter-epic edge and shares no epic with the working chain: there is no `E01 → E02` and no `E01 → E03`. The Segmenter's output reaches Diagnosis through the *file*, not through a dependency — and reading a stage chain into this graph is the error `traceability.md` §7.3 defect 16 records.

---

## §5 Traceability

| Issue | `wbs.md` task | FR / NFR (`traceability.md` §4) | Gap? | Evidence of the mapping |
|---|---|:---:|---|
| `E01-01` | `S2-T01` | **FR-13** ("Segmenter over-segments on doubt") | no | ADR-007 test: a doubtful cut is not merged; over-segmentation flag-absence test |
| `E01-02` | `S2-T02` | *(no FR — gap flagged below)*; **FR-23** in part | **gap** | Evidence-exposes-trigger test; `other`-route test; explain-without-re-running test |
| `E01-03` | `S2-T03` | **FR-14** ("Re-segmentation once only") | no | Second pass returning two types routes to review; page-reuse test |

### Gap flagged — `E01-02` (`S2-T02`) has no FR, and the gap is *recorded, not filled*

`plan-02-components.md` §8 records this as the **gap note**, and this issue does not close it, because closing it would change `prd.md` — an artifact change, out of scope for a plan and out of scope for this directory. Restated precisely, in the plan's own terms:

- **What is missing:** `traceability.md` §4.1 has **no row naming the Identifier's evidence**. Nothing in FR-01 … FR-33 names it.
- **What it does trace to:** *"its evidence requirement is what makes FR-23's verdict vector explicable"* — the mapping is **indirect**, and the plan's instruction is explicit: *"indirect is recorded here rather than upgraded to direct."*
- **Why it is not orphan work:** `traceability.md` §5 traces `S2-T01`–`S2-T15` to `FR-12…FR-24` as a group, and the Identifier sits inside that block. It is also the guard for `wbs.md` §9's *"unknown wording variants"* risk, whose owner stage is 3 — a stated need, not an invented one.
- **What closing it would cost:** adding an FR for *"a classification is explanatory from its own artifact"* — a change to `prd.md`.
- **Do not fill it by inventing a number.** `E01-02` is a **flag**, not a hole. `traceability.md` §8's rule — *a new task without an FR is a finding* — is satisfied because the finding is already recorded in `plan-02-components.md` §8.

No other issue in E01 has an empty mapping.

---

## §6 Risks

From `plan-02-components.md` §9 only — the rows whose mitigation is carried by this epic:

| Risk | L | I | Why it touches E01 | Mitigation carried by this epic |
|---|:---:|:---:|---|---|
| **Segmenter merged-document gap that no pipeline closes** | M | H | `S2-T01` **is** this row in the register. The failure mode is a merged document whose fields contaminate each other, silent to every downstream check. | Over-segmentation on doubt (ADR-007, `FR-13`); the primary acceptance criterion is that a doubtful cut **splits**; **no flag exists to disable it**; cut decisions recorded as evidence. The residual gap is **declared, never claimed solved** (`wbs.md` §9, *"Residual risk accepted"*) — and *no pipeline closes it* is a Stage 3 statement, not a Stage 2 excuse |

**The plan's first named execution risk is *about* this epic** (`plan-02-components.md` §9):

> *Building branch A late. `S2-T03` is a direct dependency of `S2-T17`. Starting the Segmenter in Wave 7 because branch A "is not the schedule driver" leaves the gate waiting on a three-link chain that was available since Wave 1. `wbs.md` §6.2 is explicit that not the driver is not not required.*

The mitigation is structural and is already drawn as a direct inter-epic edge: **E01 → E09**, on the strength of `S2-T03`. Wave 1 is where this epic starts, and nothing in the plan relaxes that.

**Register rows whose *Owner stage* is 2 that do not touch E01, stated rather than implied.** `plan-02-components.md` §9 keeps the rows whose owner stage includes 2; four of them materialise elsewhere and are named in the epics that carry them: **Docling install/portability**, **`pdftotext` as a poppler binary** and **GPU availability for local models** land in `E02`; **Frontier LLM cost per token** and **Sampled artifact regenerated** land in `E03`/`E06`/`E09` and in §7 below. None of them touches a segmentation or typing task.

**Open decisions carried, not resolved:**

| `plan-02-components.md` §12 | Question | Touches in E01 | Effect if deferred past Stage 2 |
|---:|---|---|---|
| **#3** | What defines a "critical field" | Not this epic's to define, but `E01-01`'s cut confidence and the Identifier's type evidence are the **cheapest** inputs anyone could use to derive it | Load-bearing and reviewed **before `S2-T11` starts**. Carried here only so that a reader does not assume the Segmenter may decide it: the critical-field set is policy data (`S3-T04`), never a component constant |

Open decisions **#1** (`S2-T12` vs `S2-T17`), **#2** (M0 escalation), **#3** (critical field), **#4** (OCR correction inside the Reader), **#5** (`r` vs `p` tie-break), **#6** (Reviewer aggregation) and **#7** (`pdftotext` fallback) touch `E02`, `E03`, `E04`, `E05`, `E06`, `E07` and `E09` — listed here only to confirm that **none of the seven touches E01**, which makes E01 the only epic in Stage 2 about which that can be said.
