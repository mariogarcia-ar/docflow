# E07 — Shape identity across the 13 codes

| Field | Value |
|---|---|
| Epic ID | **E07** |
| Capability | Shape identity across the 13 codes — all 13 emit the same field/verdict/trace shape, and `consistency` is non-null **exactly** on the four `ErpVR` codes |
| Issues | `E07-01` (`S3-T13`) — status `todo` |
| Issue count | **1** |
| Owner layer | **Data** (`wbs.md` §8) — the contract test |
| Wave span | **W3** |
| Effort total | **1 × M** |
| Source plan | [`../../plan-03-pipelines.md`](../../plan-03-pipelines.md) §1, §2, §5 (`S3-T13`), §3 (the shape, `consistency` and `catalog` evidence rows), §6 step 14, §7b rows 11–12, §7c, §8, §11, §12 #1–#3, §13 Track 2 |
| Depends on other epics | **E01** (`S3-T02` → `S3-T13`); entered from `S2-T14` (external) |

---

## §1 Objective

E07 delivers the guarantee the consumer actually integrates against: **all 13 codes emit the same field/verdict/trace shape**, so the consumer writes **one** integration (`FR-33`). The plan's §1 states why this is the stage's obligation rather than a nicety: *"the system's obligation is to make the *difference* between 'verified and matching' and 'nobody cross-checked this' visible in the output rather than to guess which difference matters, so every one of the 13 codes must emit the same shape and the consumer must write one integration."* Two sub-claims are inseparable from it and are asserted by the same test: `consistency` is non-null **exactly** on the four `ErpVR` codes (`M0-ErpVR`, `M1-ErpVR`, `M2-ErpVR`, `M3-ErpVR`), and `catalog` is present **with a reason** on every field of every code.

It is a single-issue epic because it is a **different deliverable class from the configuration it verifies**. `E01-02` declares the 13 codes; E07 asserts that they are substitutable. That distinction is not bookkeeping: a shape assertion co-located with the code that produces the shapes can be relaxed to match whatever was produced — which is precisely the failure `FR-33` exists to prevent (`plan-03-pipelines.md` §13, Track 2: *"A shape is compared against a documented shape, not scored by a model"*). The owner is the **Data** layer, because the test is registry-driven: it walks the 13 descriptors and compares the emitted shapes against the documented one.

**What E07 is not.** It is not a golden set — a golden set grades *values*, and value-level gold is deferred because it needs the labeller role (`plans/README.md` §6, `# TODO: [MVP]`). It is not the code resolution test (E01's `M4-ErVR` / `M4-ErpVR` / unknown-code errors); this epic asserts shape among the codes that *do* resolve. And it is not the corpus run, though a green `S3-T13` is a **precondition** of `S3-T14`, not a sibling of it (`plan-03-pipelines.md` §7a, §9 execution risk 3).

---

## §2 Issues in this epic

| Issue | `wbs.md` task | Title | Wave | Depends on | Effort | PoC markers |
|---|---||---|---|:---:|---|:---:|---|
| `E07-01` | `S3-T13` | Shape-identity verification across all 13 codes | W3 | `S3-T02` → **E01** (inter) · `S2-T14` (external — the Contract that emits the shape) | M | — |

No intra-epic edges exist: E07 is a single-issue epic. It sits in W3 because it needs two things that are first-satisfied there — the 13 resolved codes (`S3-T02`, W2) and the Contract (`S2-T14`, frozen by Plan 2's gate).

---

## §3 Issue detail

### `E07-01` — implements `S3-T13`

**Title**
Shape-identity verification across all 13 codes.

**Context**
Thirteen codes can all be reachable while emitting subtly different shapes, and that failure is invisible until a consumer writes their second integration — by which time the substitution property the whole matrix rests on is gone. `FR-33` is the requirement that closes it, and `plan-03-pipelines.md` §9 names it as the third way the plan's execution risk bites: *"`S3-T13` is a precondition of `S3-T14`, not a sibling of it."* The test's second assertion is the one that keeps the verdict vector honest: `consistency` exists **only where both reads ran**, so a non-null `consistency` on a single-read code would be an invented cross-check, and a `null` on an `ErpVR` code would be a lost one. The third is `catalog`: present on **every** field even though no pipeline runs the Catalog, carrying its reason — which keeps *"never attempted"* distinguishable from *"the source was down"* (`FR-23`, `sad.md` §11, deviation D8).

**Deliverable**
Contract test — a test that walks the 13 codes and compares the emitted shape against the documented one.

**Depends on**
- `S3-T02` — **inter-epic** (E01 → E07): the 13 resolved codes are the test's input set.
- `S2-T14` — **external entry edge**: the Contract emits the field/verdict/trace shape this issue verifies. **This is a Plan 2 freeze: Plan 3 wires the 13 codes onto that chain and emits the shape unchanged for all 13** (`plans/README.md` §3, Plan 2 row).

**Acceptance criteria**
- [ ] All **13** codes are exercised by the test, one document each, and the count of codes covered is asserted to be 13.
- [ ] **All 13 emit the same field shape** — the same member set on every field, with no member present on one code and absent on another.
- [ ] **All 13 emit the same verdict shape** — the verdict vector per field, never a single confidence score (`ADR-005`, `prd.md` FR-23).
- [ ] **All 13 emit the same trace shape** — the per-field `(page, extractor)` trace, with the same structure (`FR-23`).
- [ ] **`consistency` is non-null exactly on the four `ErpVR` codes**: `M0-ErpVR`, `M1-ErpVR`, `M2-ErpVR`, `M3-ErpVR` — and is `null` on all nine others.
- [ ] **`catalog` is present with a reason on every field of every code** — `unverified` with the reason recorded (`not_run` \| `source_unavailable` \| `pending_retry`), so *"never attempted"* is distinguishable from *"the source was down"* (`FR-23`, `sad.md` §11).
- [ ] The comparison is against a **documented shape**, not against the first code's output: a per-code difference fails the test rather than defining the baseline.
- [ ] **The test fails when the invariant is broken** — remove one member from one code's output and the test goes red (`wbs.md` §8, Stage DoD).
- [ ] The test runs against the **`ErpVR` contrast-bearing codes as well as the single-read ones**, so the `consistency` assertion is exercised in both directions.
- [ ] No new kernel-boundary type is introduced, and no new output type is defined by the test (`plan-03-pipelines.md` §10, Task DoD; `plans/README.md` §3, Plan 2 row: Plan 3 emits the Plan 2 shape **unchanged**).

**Test / evidence**
- `plan-03-pipelines.md` §5 row `S3-T13` — the verifiable criterion: *"All 13 codes emit the same field/verdict/trace shape; `consistency` is non-null **exactly** on the four `ErpVR` codes."*
- `plan-03-pipelines.md` §8 — *"**FR-33**, **FR-23**"*, proof *"The contract test across 13 codes; `consistency` non-null exactly on the four `ErpVR` codes."*
- `plan-03-pipelines.md` §3, observable evidence — three rows this issue owns: *"identical field/verdict/trace shape for all 13 (`FR-33`)"* guarding against *"a per-pipeline shape, forcing the consumer to write 13 integrations"*; *"`consistency` … non-null **exactly** on the four `ErpVR` codes"* guarding against *"`consistency: ok` on a single-read code, or `null` on an `ErpVR` one"*; and *"`catalog` across the 13 — `unverified` **with a reason** on every field of every code"* guarding against *"a missing member, or `unverified` whose reason is lost."*
- `plan-03-pipelines.md` §6 step 14 — *"Check the 13 shapes side by side."* Compare the emitted JSON of one document per code: field set, verdict set, trace shape. The wrong result: *"a per-code shape difference that forces the consumer to write 13 integrations (`FR-33`)."*
- `plan-03-pipelines.md` §7a — the happy-path test that must pass to close the flow is the corpus run, and *"a green `S3-T13` shape-identity contract test is a precondition of it, not a substitute."*
- `plan-03-pipelines.md` §7b rows 11–12 — *"All 13 codes emit one shape"*: the `S3-T13` contract test; breaking it looks like *"a member present on one code and absent on another."* And *"`consistency` is non-null exactly on the four `ErpVR` codes"*: the same contract test; breaking it looks like *"`null` invented on an `ErpVR` code, or `ok` invented on a single-read one."*
- `plan-03-pipelines.md` §7c — one of the six acceptance scenarios closes at Stage 3: *"The merged-document limitation is declared, not hidden"*, where the output is *"shape-valid with every field carrying its verdicts, and the limitation still declared and unsolved"* — closing at `S3-T13` (shape-valid across the 13) **and** `S3-T14` (the corpus run). `plan-03-pipelines.md` §7d makes it explicit that merged-document detection is **Never** — asserted as *declared*, not as solved.
- `plan-03-pipelines.md` §11 — *"All 13 codes emit the **same** field/verdict/trace shape; `consistency` is non-null **exactly** on the four `ErpVR` codes; `catalog` is present with a reason on every field of every code."*
- `plan-03-pipelines.md` §13, Track 2 — three rows: *"One shape across all 13 codes"* (*"invisible until a consumer writes their second integration"*, *"`FR-33`'s whole purpose"*), *"`consistency` exactly where both reads ran"*, and *"`catalog` present with a reason on every field"* (*"collapsing *never attempted* with *the source was down*"*).
- `plans/README.md` §6 — *"Plan 3 … The shape-identity contract test over all 13 codes, plus the first full run's recorded baseline — a shape is compared against a documented shape, not scored by a model."*
- `traceability.md` §4.1 **FR-33** (task `S3-T13`) and **FR-23** (tasks `S2-T13`, `S2-T14`, `S2-T12`); §4.2 — the shape is the Plan 2 freeze this plan re-emits.
- `sad.md` §11 (the output contract) and §8 (the 13-pipeline matrix) — the two documented shapes the test compares against; `sad.md` §12 ADR-005 — *"Emission is a verdict vector, not a score."*

**Out of scope for this issue**
- **Resolving the codes.** `E01-02` (`S3-T02`) makes the 13 reachable; this issue asserts shape among those that resolve.
- **The invalid-code errors.** `M4-ErVR`, `M4-ErpVR`, `M0-*` at a PDF and unknown codes are `E01-02`'s test, not this one's.
- **Value-level gold.** A golden set graded by the model that produced it is circular; `--golden` and the labeller role are deferred. `# TODO: [MVP]` (`prd.md` §7, `traceability.md` §3.4 **D4**).
- **The corpus run.** `E08-01` (`S3-T14`); this test is its precondition, not a substitute for it (`plan-03-pipelines.md` §7a).
- **What defines a "critical field".** Carried **open** (`plan-03-pipelines.md` §12 **#1**, touching `S3-T04` and `S3-T13`): *"the shape is unaffected, but which fields carry contrast is."*
- **What M0's targeted escalation means.** Carried **open** (`plan-03-pipelines.md` §12 **#2**, touching `S3-T02` and `S3-T13`): `M0-*` is three of thirteen codes, and *"discovering here that M0 breaks an assumption the other ten materials share would invalidate the shape-identity test (`FR-33`) rather than one pipeline."*
- **Whether `S2-T12` (Catalog) is a dependency of `S2-T17`.** Carried **open** (`plan-03-pipelines.md` §12 **#3**, touching `S3-T03` and `S3-T13`): at corpus scale, *"if `not_run` was defined as a literal rather than as the Catalog's value, then the reason vocabulary is a constant in the Contract and the first real `source_unavailable` will need a change in the wrong layer."*
- **Merged-document detection.** No pipeline closes it. **Never** — asserted as *declared*, not as solved (`prd.md` §10, `plan-03-pipelines.md` §7d).
- **A single confidence score.** The output is a per-field verdict vector plus trace. **Never** (ADR-005, `prd.md` FR-23).
- **A second, weaker schema for a subset of codes.** Shape identity is the point; a per-code schema would reintroduce the 13 integrations. **Never**.
- **A live Catalog source.** No pipeline runs the Catalog; every field reads `not_run`. `# TODO: [MVP]`.

**Effort**
**M** — one test, but it must be written from the **consumer's** direction (compare against the documented shape) rather than the producer's, run across 13 codes on two different axes (single-read vs contrast-bearing), and fail visibly when a member moves. No external dependency, several interacting assertions (`wbs.md` §7).

**Owner**
**Data** — `wbs.md` §8 assigns `S3-T13` to the Data layer, alongside the registry assets and descriptors it walks; the shape it compares against is the Plan 2 freeze consumed, not produced here.

**Frozen contract touched**
**Consumes** `plans/README.md` §3, Plan 2 row — *"the verdict-vector shape and the per-field trace shape (`sad.md` §11, `prd.md` FR-23); the `catalog` reason vocabulary (`not_run` \| `source_unavailable` \| `pending_retry`)"* — and asserts that Plan 3 re-emits it **unchanged for all 13 codes**. This issue is where that row's consumption clause (`FR-33`, `S3-T13`) is enforced. **Publishes** nothing new: a change to the shape would be a change to the Plan 2 freeze, which re-opens Gate 2, not a Plan 3 deliverable.

---

## §4 Epic close condition

E07 is **`done`** when:

1. `E07-01` is `done`, and
2. the capability is **demonstrable**: the contract test runs all 13 codes, passes against the documented shape, and **fails** when one member is removed from one code's output; `consistency` is non-null on exactly the four `ErpVR` codes; and `catalog` is present with a reason on every field — checked by running the test in both directions, not by reading it.
3. **Plan 3 DoD, per epic:** no new kernel, no new component, no new kernel-boundary type — this epic adds configuration and data, and the strongest evidence that it did is that the shape it asserts is Plan 2's, unchanged (`plan-03-pipelines.md` §10, Task DoD).

**Does E07 gate `S3-T14`?** **Yes, directly — and it is the plan's third named execution risk.** `S3-T14`'s dependency set names `S3-T13`, so E07 → E08 is a direct gate edge. `plan-03-pipelines.md` §9 names the violation: *"**Close the gate on the 13 codes without `S3-T13`.** All 13 can be reachable while emitting subtly different shapes — that is precisely the failure `FR-33` exists to prevent, and it is invisible until a consumer writes their second integration. `S3-T13` is a precondition of `S3-T14`, not a sibling of it."* The `M` effort is misleading: this is the cheapest issue in the plan relative to what its absence costs, because the failure it prevents is not detectable by any other test in the suite — every code works, every artefact verifies, and the output is not substitutable.

---

## §5 Traceability

| Issue | FR / NFR (`traceability.md` §4) | Gap? | Evidence of the mapping |
|---|---|:---:|---|
| `E07-01` | **FR-33** (all 13 produce the same shape), **FR-23** (verdict vector per field + trace; `consistency` set only where both reads ran; `catalog` carries a reason) | no | The contract test across 13 codes; `consistency` non-null exactly on the four `ErpVR` codes; `catalog` present with a reason on every field |

No gap and no orphan. `traceability.md` §4.1 places **FR-33** at stage 3 with task `S3-T13` alone, and **FR-23** at stage 2 with `S2-T13`, `S2-T14`, `S2-T12` — this issue is the **consumer-side assertion** of a requirement Plan 2 implemented, which is why it carries both numbers and owns neither. The Plan 3-specific fact restated here: this stage has **no gap and no orphan task**; the one deliberately uncovered requirement is `NFR-12` (deployment), recorded in `traceability.md` §7.1 as having no task by design (`# TODO: [RELEASE]`).

**Three open decisions touch this issue, and all three arrive here rather than starting here.** They are carried **open** and are not resolved by this epic:

| `plan-03-pipelines.md` §12 | Question | Why it lands on E07 |
|---:|---|---|
| **#1** | What defines a "critical field" | The shape is unaffected, but **which fields carry contrast** is. If unresolved, contrast is either paid everywhere or scoped by a guess — and the test certifies whichever was chosen |
| **#2** | What M0's targeted escalation means | `M0-*` is three of thirteen codes. *"Discovering here that M0 breaks an assumption the other ten materials share would invalidate the shape-identity test (`FR-33`) rather than one pipeline"* — which is why `traceability.md` §7.2 recommends settling it **before** Stage 2 |
| **#3** | Whether `S2-T12` (Catalog) is a dependency of `S2-T17` | `catalog` present with reason `not_run` on all 13. If `not_run` was defined as a literal rather than as the Catalog's value, the reason vocabulary is a constant in the Contract and the first real `source_unavailable` needs a change in the wrong layer |

`plan-03-pipelines.md` §12 **#1** and **#2** are the two items the plan itself flags as reviewed before `S3-T04` and `S3-T13` start, and §4 entry condition 9 repeats it.

---

## §6 Risks

From `plan-03-pipelines.md` §9 only, keeping the rows that name `S3-T13`:

| Risk | L | I | Why it touches E07 | Mitigation carried by this epic |
|---|:---:|:---:|---|---|
| **Unknown wording variants in the corpus** — at 11k files the variants cannot be enumerated up front | H | H | Shape identity is what keeps a variant-handling change local: the `EpVR` modes tolerate variation, and as long as all 13 emit one shape, adding a pattern is a registry change. If the 13 diverged, a variant fix would become a per-code fix. | `EpVR` tolerates variation; patterns are registry data, so adding a variant is a hash change rather than a deployment; the Reviewer promotes repeats into rules. The first clause is only *true at the consumer's boundary* because this issue asserts the shape |
| **Segmenter merged-document gap that no pipeline closes** | M | H | The Stage 3 acceptance scenario that closes here is *"The merged-document limitation is declared, not hidden"*: a file holding three logical documents, a pipeline that runs no Segmenter, and output that is **shape-valid with every field carrying its verdicts** — with the limitation still declared and unsolved. `S3-T13` is the "shape-valid" half. | Declared, never claimed solved; over-segmentation mitigates. **Residual risk accepted**, and asserted as *declared* by this issue (shape-valid) and `E08-01` (the corpus run); the declaration itself is `wbs.md` §10 and `prd.md` §10 |

**The plan-specific execution risk that lands here** (`plan-03-pipelines.md` §9, way 3) is quoted in full in §4 above, because it *is* this epic: closing the gate without `S3-T13` is the only way this epic's absence becomes the gate's failure.

**One risk row is excluded by the plan's own filter and is worth naming anyway:** *"Golden set graded by the model that produced it (circularity)"* (`wbs.md` §9, owner stage 3) appears in `plan-03-pipelines.md` §9 with the note *"Not exercised in this plan, kept because the corpus run is what would expose it."* It touches E07 in one specific way: **the shape test must not substitute for a golden set**. `plans/README.md` §6 states the distinction — Plan 3's golden evidence *"cannot be self-graded"* because *"a shape is compared against a documented shape, not scored by a model"* — and this epic is the reason that sentence is true.

---

