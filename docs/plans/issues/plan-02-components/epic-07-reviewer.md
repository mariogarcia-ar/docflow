# E07 — Reviewer — the return loop

| Field | Value |
|---|---|
| Epic ID | **E07** |
| Capability | Landing cases beside their document with provenance, and promoting a correction into registry data that invalidates the affected cache keys |
| Issues | `E07-01` (`S2-T15`) — status `todo` |
| Issue count | **1** |
| Owner layer | **Domain** (`wbs.md` §8) — `docflow/components/reviewer.py` |
| Wave span | **W8** |
| Effort total | **1 × M** |
| Source plan | [`../../plan-02-components.md`](../../plan-02-components.md) §2, §5 (`S2-T15`), §7b row 10 (adjacent), §8 gap note, §11, §12 open decision 6, §13 (no track names it) |
| Depends on other epics | **E06** (emission — the Contract & the verdict vector) |

---

## §1 Objective

E07 delivers the system's only mechanism for **getting better**: a case that reaches a human, a correction that is recorded, and a promotion that turns that correction into data the pipeline reads next time. Its capability is not "a work queue with three verbs" — it is that **the loop closes**: `plan-02-components.md` §5 states the criterion as *"Cases land beside their document with provenance; a promoted rule becomes registry data in K8 and invalidates the affected cache keys"*, and `plans/README.md` §2's framing of the whole problem carries the same idea — *"without a return loop, the system does not improve."*

It is a separate deliverable because it is the one component that makes the system **stateful across runs in a way that changes its behaviour**. Everything else in Stage 2 answers the same question about the same bytes. The Reviewer is the only place where a value produced in one run becomes a **registry change** that changes what a future run keys on — which is precisely why it must not be allowed to change the cache key silently, and why its promotion path is required to *invalidate* the affected keys rather than to assume they will notice.

**Position on the critical path — read this before scheduling.** E07 is **explicitly not a gate dependency.** `wbs.md` §6.2 lists `S2-T15` (Reviewer) among the tasks *"that can slip without delaying a stage close"*, and `plan-02-components.md` §5 draws it with the note *"parallel · not a gate dependency"*. `S2-T17`'s dependency set does not name it, which is why the index README's graph draws **`E06 → E07` but no `E07 → E09`** (§3 of that file). E07 may slip past the stage close; **`E07-01` may not slip past Wave 8 without `E06-01` being terminal**, since `S2-T15` depends on `S2-T13`.

**One structural fact this epic records rather than hides.** `plan-02-components.md` §13's four tracks name `S2-T17` (Track 1), `S2-T11`/`S2-T14` (Track 2), `S2-T13`/`S2-T14` (Track 3) and `S2-T16` (Track 4). **The Reviewer appears in none of them** — the same absence as its FR gap in the plan's §8. E07 is therefore the one epic in this decomposition with no lane in the epic map (`README.md` §2 says *(none)* rather than inventing an assignment), and this file states why rather than letting a reader infer that the omission was an oversight.

---

## §2 Issues in this epic

| Issue | `wbs.md` task | Title | Wave | Depends on | Effort | PoC markers |
|---|---||---|---|:---:|---|:---:|---|
| `E07-01` | `S2-T15` | Reviewer: `queue`, `correct`, `promote` (corrected datum / new rule / new type) | W8 | `S2-T13` → **E06** (inter) | M | `# TODO: [MVP]`: workflow UI, promotion controls |

No intra-epic edges exist: E07 has a single issue.

This epic produces **one** incoming inter-epic edge — `E06 → E07` — and **no outgoing edge**. It depends on the Contract's artifact and on nothing else, and nothing depends on it: it is a leaf both of the epic graph and of the plan's own dependency table. `wbs.md` §6.2's slip list and the absence of an `E07 → E09` edge are two statements of the same fact, and the index README's §9 counts E07 among the two epics that may slip.

---

## §3 Issue detail

### `E07-01` — implements `S2-T15`

**Title**
Reviewer: `queue`, `correct`, `promote` (corrected datum / new rule / new type).

**Context**
A correction that is not recorded is a correction the system learns nothing from, and a promotion that does not invalidate assume the next run will notice a change it has no way to see. `plan-02-components.md` §5's criterion names the second precisely: *"a promoted rule becomes registry data in K8 and invalidates the affected cache keys"* — which is a statement about `E03-02`'s 7-term key, not about a file write. Promoting a rule changes the **registry hash**, and the registry hash is a mandatory cache-key term, so the affected entries go stale **by construction** rather than by anyone remembering to clear them. That is the mechanism this issue has to exercise, and it is the only part of the Reviewer that a test can hold to a standard.

The second failure is provenance loss. *"Cases land beside their document with provenance"* — a case without provenance is a field value in a queue, and the person resolving it cannot see which page, which extractor or which verdict produced it. The plan's §7b row 10 (the escalation-ownership row) is the adjacent invariant: escalation is decided in **one** place, and the Reviewer is where escalation's *output* arrives — so a case that arrives without the escalating verdict in hand is unusable for exactly the reason that row exists.

**Deliverable**
`docflow/components/reviewer.py`

**Depends on**
`S2-T13` — **inter-epic** (E06 → E07). The Reviewer's input is emitted output; a case cannot be raised against a field that has not been emitted, and the provenance it carries is the trace `E06-01` writes. Intra-epic: n/a. Inter-epic: this is the epic's only edge.

**Acceptance criteria**
- [ ] `docflow/components/reviewer.py` exists and exposes exactly **three** operations: `queue`, `correct`, `promote`.
- [ ] **Cases land beside their document with provenance** — the case's location is the document's, not a separate store, and the provenance is the emitted per-field trace.
- [ ] `queue` emits a case for a field whose verdict routes to review, and for **no** field that does not.
- [ ] `correct` records a corrected datum with **provenance intact** — the case is not rewritten to look like it was right the first time.
- [ ] `promote` supports the **three** documented targets: a **corrected datum**, a **new rule**, and a **new type**.
- [ ] A **promoted rule becomes registry data in K8** — written through the registry port, validated, and readable on the next load.
- [ ] A promoted rule **invalidates the affected cache keys**: the `registry_hash` term changes and the affected entries are no longer terminal. Asserted by computing keys before and after, not by inspecting a file.
- [ ] A promoted rule that is **schema-invalid fails fast**, exactly as any other registry asset does (`FR-10`, `E03`'s registry port) — the Reviewer does not gain a bypass.
- [ ] The component imports **ports only**: `Registry` and `ArtifactStore` from `docflow/ports/`, never `docflow/kernels/registry.py` or an adapter.
- [ ] No case, correction or promotion is written **inside** `docflow/components/` at run time: cases live beside the document, registry data lives in `registry/`.

**Test / evidence**
- `plan-02-components.md` §5, `S2-T15`'s verifiable cell — *"Cases land beside their document with provenance; a promoted rule becomes registry data in K8 and invalidates the affected cache keys"*. Both clauses are criteria; the second is the one that can be asserted mechanically.
- `plan-02-components.md` §8 — **no FR of its own; see §5's gap subsection below.** Proof is *"A promoted rule becomes K8 data and invalidates the affected cache keys"*.
- `plan-02-components.md` §8, gap note — the Reviewer *"is a genuine gap of the same shape `README.md` calls out"*: *"without a return loop, the system does not improve"* **is an invariant, not an FR**. The task is justified by `wbs.md` §4 and `02-components.md`, and by `traceability.md` §5's "no orphan task" check, which traces it to `FR-12…FR-24` **as a group**.
- `plan-02-components.md` §7b row 10 — *"'Could not' is defined in exactly one place"* (`S2-T09`, `FR-19`): the Reviewer **receives** escalation's output, and the invariant it depends on is that the case arrives carrying the escalating verdict rather than a re-derived one.
- `wbs.md` §9 — *"Unknown wording variants in the corpus"* (H/H, owner stage 3): the mitigation chain is *"patterns are registry data, so adding a variant is a hash change rather than a deployment; **Reviewer promotes repeats into rules**"*. This issue **is** the last link of that mitigation.
- `plan-02-components.md` §11 — exit checklist item *"All 17 tasks `S2-T01`–`S2-T17` are `done`, each with its verifiable criterion passing"* applies; the Reviewer is not named in any other checklist item, and §13's four tracks do not tick it — stated rather than implied.
- `plans/README.md` §4 — *"Can slip without delaying a stage close: … `S2-T15` (Reviewer)"*; no `E07 → E09` edge exists in the index README's §3 for the same reason.

**Out of scope for this issue**
- **No workflow UI and no promotion controls beyond the three operations.** `# TODO: [MVP]` (`plan-02-components.md` §2, §5) — *"`queue`/`correct`/`promote` are enough to close the loop"*.
- **No case aggregation after the run.** Whether anything aggregates the per-document cases is open decision **#6**; *"`S2-T15` closes the loop at the per-document level, which is enough for the gate. Aggregation is a workflow feature, not a PoC requirement."* Carried in §6; **not resolved**.
- **No second escalation owner.** The ladder is `E03-03`'s; the Reviewer stores and promotes its output (`FR-19`). **Never** a second decision point.
- **No rule promotion that bypasses registry validation.** A promoted asset is validated like any other; a malformed promotion stops rather than defaulting. **Never** the latter (ADR-009's family of guarantees, `FR-10`).
- **No direct cache manipulation.** Invalidation is a *consequence* of the registry hash changing, not a clearance call — a component that deleted cache entries would be reaching around the key.
- **No `--rule`, `--new-type` or `--value` flags.** All three are in the deferred list (`wbs.md` §10, `plan-02-components.md` §2). `# TODO: [MVP]`.
- **No feedback into the golden set.** The golden-set labeller is `# TODO: [MVP]` and, when it lands, *"the labeller runs offline and never shares a run with the governor"* (`plan-02-components.md` §13 Track 2). **Never** in the same run.
- **No adapter import.** **Never** (`sad.md` §1).

**Effort**
**M** — three operations and a promotion path whose acceptance criterion is a *cache-key consequence* rather than a file write, plus provenance preservation and the absence of a validation bypass; interacting concerns with no heavyweight dependency, but requiring a before/after key comparison (`wbs.md` §7).

**Owner**
**Domain** — `docflow/components/reviewer.py` (`wbs.md` §8).

**Frozen contract touched**
**Consumes** `plans/README.md` §3, Plan 2 row — the *`catalog` reason vocabulary* (a queued field is a **pending** field, not a missing one) and the *per-field trace shape* (the provenance a case carries is that trace). **Contributes to** the Plan 1 row indirectly and only through the registry: a promoted rule changes the `registry_hash` term of the 7-term cache key, so this issue exercises a Plan 1 frozen artifact without altering it. It freezes nothing new — and the plan's own note is that this task is a **gap** in the mapping rather than an extension of the contract.

---

## §4 Epic close condition

E07 is **`done`** when:

1. `E07-01` is `done`, and
2. the capability is **demonstrable**, and checked by running it: `queue` emits a case **beside the document** for a field that routed to review and for no other; the case carries the field's provenance as emitted; `correct` records a corrected datum without erasing the original; and `promote` turns a rule into registry data whose **hash change invalidates the affected cache keys** — shown by computing the key before and after, not by reading `reviewer.py`.

**Does E07 gate `S2-T17`?** **No — and this must be stated plainly rather than left to inference.** `S2-T15` does **not** appear in `S2-T17`'s dependency set (`wbs.md` §4). `wbs.md` §6.2 lists it among the tasks that can slip past a stage close, and `plan-02-components.md` §5 draws it with *"parallel · not a gate dependency"*. The index README's §3 graph therefore draws `E06 → E07` and **no `E07 → E09`**; that absence is a derived fact, not an omission.

**Does E07 gate anything else?** **No.** Nothing in Stage 2 or Stage 3 depends on `S2-T15` (`wbs.md` §4's `Depends on` column contains no reference to it). It is doubly terminal: it gates nothing, and it is gated only by `E06-01`.

**What that means in practice, stated so it is not misread as low value.** E07 may slip past the stage close, and the plan says so. What may **not** slip is the promotion path's *correctness*: a promoted rule that does not change the registry hash would leave every affected cache entry terminal, and the system would serve values computed under the old rule while reporting success. That is a silent failure inside the one component whose entire purpose is to make the system better — which is why the acceptance criterion is written as a key comparison rather than a file assertion.

---

## §5 Traceability

| Issue | `wbs.md` task | FR / NFR (`traceability.md` §4) | Gap? | Evidence of the mapping |
|---|---|:---:|---|
| `E07-01` | `S2-T15` | *(no FR — gap flagged below)*; traces to `FR-12…FR-24` **as a group** via `traceability.md` §5 | **gap** | A promoted rule becomes K8 data and invalidates the affected cache keys |

### Gap flagged — `E07-01` (`S2-T15`) has no FR, and the plan calls it *"a genuine gap"*

`plan-02-components.md` §8 records this as the **gap note**, and this issue does not close it, because closing it would change `prd.md` — an artifact change, out of scope for a plan and out of scope for this directory. The plan's own words, restated without softening:

- **What is missing:** `traceability.md` §4.1 has **no row naming the Reviewer's promotion path**. Nothing in FR-01 … FR-33 names it. The FRs that touch the Reviewer (FR-12, FR-23) *"cover their surface, not their behaviour"*.
- **The plan calls it, verbatim:** *"`S2-T15` (Reviewer) is a genuine gap of the same shape `README.md` calls out — `'without a return loop, the system does not improve'` is an **invariant, not an FR**."*
- **Why it is not orphan work:** the task *"is justified by `wbs.md` §4 and `02-components.md`, and by `traceability.md` §5's 'no orphan task' check, which traces it to `FR-12…FR-24` as a group."* It is also the last link of `wbs.md` §9's *"unknown wording variants"* mitigation chain, whose owner stage is 3 — a stated need with an owner, just not a numbered one.
- **What closing it would cost:** *"adding an FR for 'corrections return into the pipeline as registry data', which changes `prd.md`"*.
- **Do not fill it by inventing a number.** `E07-01` is a **flag**, not a hole. This epic also records the *shape* of the gap extending one step further than the FR: **no track in `plan-02-components.md` §13 names the Reviewer either** — so the epic map's *(none)* lane and this table's *gap* row are the same fact, reported twice so that neither reads as an accident.

No other issue in E07 exists to have a mapping.

---

## §6 Risks

From `plan-02-components.md` §9 only — the rows whose mitigation is carried by this epic:

| Risk | L | I | Why it touches E07 | Mitigation carried by this epic |
|---|:---:|:---:|---|---|
| **Unknown wording variants in the corpus** — at 11k files the variants cannot be enumerated up front | H | H | The row's owner stages are **3**, but its mitigation chain ends in a Stage 2 component: *"patterns are registry data, so adding a variant is a hash change rather than a deployment; **Reviewer promotes repeats into rules**"*. `E07-01` is that last link, and a promotion path that does not change the hash breaks the chain at its end. | `promote` writes **registry data validated through the registry port**, and the acceptance criterion is that the **`registry_hash` term changes** so the affected cache keys are no longer terminal — asserted by a before/after key comparison. The corpus-scale half (the variants themselves) remains Plan 3's |

**Rows with owner stage 2 that do *not* touch E07, stated rather than implied.** Of `plan-02-components.md` §9's six rows, five touch other epics: **Docling install/portability**, **`pdftotext` as a poppler binary**, **GPU availability** (`E02`, consumed onward), **Frontier LLM cost per token** (`E04`, `E06`) and **Segmenter merged-document gap** (`E01`). The **Sampled artifact regenerated** row touches `E03`, `E06` and `E09`. E07 carries the corpus-variants row above and nothing else — which is consistent with its being the one Stage 2 component with no external dependency and no gate obligation.

**The plan's four named execution risks, checked against this epic.** None of them is *about* E07:

| # | The violation (`plan-02-components.md` §9) | Does it touch E07? |
|---:|---|---|
| 1 | Building branch A late | No — `E01` |
| 2 | Treating `S2-T08` as a place to defer | No — `E03` |
| 3 | Slipping `S2-T12` into the gate without deciding it | No — `E04`, `E05`, `E06` |
| 4 | Closing the gate on a single-read primitive | No — `E09` |

Stated because an epic with no named risk is the easiest place for an unstated one to hide. The risk that **does** attach to E07 is not a register row: **a promotion path that writes registry data without changing the hash leaves every affected entry terminal, and the system silently serves values computed under the previous rule.** That is why the close condition is a key comparison and not a file assertion.

**Open decisions carried, not resolved:**

| `plan-02-components.md` §12 | Question | Touches in E07 | Effect if deferred past Stage 2 |
|---:|---|---|---|
| **#6** | **Whether the Reviewer's cases are aggregated after the run.** `03-cli.md` puts them in the per-document ledger; whether anything aggregates them into something the Reviewer can work from is undefined | `S2-T15` — **the plan names this question against this task alone** | **PoC answer, and it is not a gap:** *"`S2-T15` closes the loop at the per-document level, which is enough for the gate. Aggregation is a workflow feature, not a PoC requirement."* Carried here; **not resolved** |
| **#3** | **What defines a "critical field"** | Indirect: which cases reach the Reviewer depends on what routes to review, which depends on the verdicts — but the *set* is policy data (`S3-T04`) | **Load-bearing, reviewed before `S2-T11` starts** — i.e. before this issue's dependency (`S2-T13`) is built. Carried in `E04`/`E06`; named here because the Reviewer receives the consequence |

Open decisions **#1** (Catalog vs gate), **#2** (M0 escalation), **#4** (OCR correction), **#5** (`r` vs `p` tie-break) and **#7** (`pdftotext` fallback) touch `E02`, `E03`, `E04`, `E05` and `E06`; none is resolved here.
