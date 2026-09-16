# E04 — Cross-read consistency — normalization & contrast

| Field | Value |
|---|---|
| Epic ID | **E04** |
| Capability | Comparing **values** rather than spellings, and letting a second, differently-failing read contradict the first — with arithmetic breaking the tie |
| Issues | `E04-01` (`S2-T10`) · `E04-02` (`S2-T11`) — all `todo` |
| Issue count | **2** |
| Owner layer | **Domain** (`wbs.md` §8) — `docflow/components/` |
| Wave span | **W5 → W6** (W5: 1 · W6: 1) |
| Effort total | **1 × L · 1 × M** |
| Source plan | [`../../plan-02-components.md`](../../plan-02-components.md) §1, §3, §5 (`S2-T10`, `S2-T11`), §6 steps 3 & 7, §7b, §7c, §8, §9 execution risks 3–4, §10 Stage DoD, §12 open decisions 1–3, §13 Tracks 1–2 |
| Depends on other epics | **E03** (reconstruction & the validity verdicts) |

---

## §1 Objective

E04 delivers **the one claim Stage 2 exists to prove**: that a value which passes every first-order check can still be caught, because a second, differently-failing reader disagrees. `plan-02-components.md` §10 names it as the stage's riskiest invariant in one sentence — **contrast is the only detector of the plausible-but-false value, and its absence is visible as `consistency: null` rather than invented as `ok`** — and §1 states the case the architecture was built around: a total of `15400.00` that was really `1540.00`, which passes shape, type and content, has no check digit, and is caught *only* by disagreement.

Two capabilities, one epic, because they are the two halves of a single comparison:

1. **Normalization** (`E04-01`) makes the comparison about *values*. Without it the raw strings are compared and *"the review queue fills with spelling differences"* — `1.540,00` and `1540.00` are the same amount. With it, tolerance becomes type-dependent: amounts within cents, identifiers and dates exact.
2. **Contrast** (`E04-02`) makes the comparison exist at all. `ErpVR` runs both extractors; the two reads are *designed to fail differently* — the `r` path reads an offset trace, the `p` path reads a bounding box — and where they disagree, **arithmetic breaks the tie** before a human is involved.

It is a separate deliverable because it is the epic where the project's central trade-off is made concrete: **no single reader can manufacture its own check**. `plans/README.md` §6 states the value of the golden evidence in this layer — *"Caught by two independent readers disagreeing, which no single reader can manufacture for itself"* — and `plan-02-components.md` §13 Track 2 adds the negative half: the contrast case *"must fail when broken"* by emitting `consistency: ok` *"because shape, type and content all passed"*.

**Position on the critical path — read this before scheduling.** E04 is the **tail of Branch D** and it gates **two** things at once: branch E's entry (`E06`, via `S2-T13`'s dependency on `S2-T11`) and the gate itself (`E09`, via `S2-T17`'s dependency on `S2-T11`). `S2-T11` is **alone in Wave 6** — `plan-02-components.md` §5 calls it *"the contrast task — the one the whole architecture exists for"* and notes it *"gates branches D and E simultaneously"*.

E04 also carries the **deadline for the plan's load-bearing open decisions**: `plan-02-components.md` §12 reviews **#1 and #3 before `S2-T11` starts**, not at the gate, and #1's failure mode is registered as **execution risk 3** — *slipping `S2-T12` into the gate without deciding it*. Wave 6 is therefore not only a build slot; it is a decision point.

---

## §2 Issues in this epic

| Issue | `wbs.md` task | Title | Wave | Depends on | Effort | PoC markers |
|---|---||---|---|:---:|---|:---:|---|
| `E04-01` | `S2-T10` | Consistency: normalize before comparing; tolerance by field type | W5 | `S2-T08` → **E03** (inter) | M | `# TODO: [MVP]`: more field-type tolerances as types are defined |
| `E04-02` | `S2-T11` | Consistency across extractors — **contrast** — plus arithmetic tie-break | W6 | `S2-T10` → **E04** (intra) | L | `# TODO: [MVP]`: contrast scope beyond critical fields |

Intra-epic edge (not drawn as an epic edge): `E04-02` → `E04-01` — **1 edge**.

This epic produces **three** outgoing inter-epic edges — **`E04 → E05`** (`S2-T12` depends on `S2-T11`), **`E04 → E06`** (`S2-T13` depends on `S2-T11`) and **`E04 → E09`** (`S2-T17` depends on `S2-T11`). It is the only epic that feeds the gate *and* opens two other epics.

---

## §3 Issue detail

### `E04-01` — implements `S2-T10`

**Title**
Consistency: normalize before comparing; tolerance by field type.

**Context**
Comparison is where an implementation choice quietly decides what the system can see. Compare the **raw values** and `1.540,00` differs from `1540.00`, so a formatting difference between two readers is reported as a contradiction — and the review queue fills with documents that are correct. `plan-02-components.md` §7b states the failure in exactly those terms: *"the raw values are compared, so the review queue fills with spelling differences"*. The mirror-image failure is just as bad and is the second row of that table: a **cents tolerance applied to an identifier** *"hiding a genuinely different digit"*. This issue exists to make normalization happen **before** the comparison and to make the tolerance a property of the **field type** — amounts tolerant to cents, identifiers and dates exact — so that neither failure is reachable by accident.

**Deliverable**
`docflow/components/consistency.py`

**Depends on**
`S2-T08` — **inter-epic** (E03 → E04). Consistency compares values the Validator has already judged; it consumes verdicts and does not re-derive them. **Note the dependency is on `S2-T08`, not on `S2-T09`**: the escalation ladder is not a precondition of comparing two reads. Intra-epic: none — this is the epic's root.

**Acceptance criteria**
- [ ] `docflow/components/consistency.py` exists and **normalizes before comparing** — normalization is a step in the comparator, not a helper called by some callers.
- [ ] `1.540,00` and `1540.00` compare **equal** for the same field.
- [ ] A **spaced vs unspaced identifier** compares equal — the plan's second normalization instance.
- [ ] **Amounts use cents tolerance; identifiers and dates are exact** — the tolerance is selected **by field type**, and a test asserts both directions.
- [ ] The **raw values are not what is compared**: a test that would pass if raw comparison occurred must **fail**.
- [ ] Tolerance is **registry data**, not a constant — and there is **no `--tolerance-amounts` flag** and **no environment variable** for it (ADR-009, `NFR-06a`, §13 Track 4).
- [ ] A comparison result is **evidence-carrying**: the normalized forms and the tolerance applied are recorded, so a disagreement is explainable without re-deriving it.
- [ ] The component imports **ports only**; the import-isolation check passes over `docflow/components/consistency.py`.

**Test / evidence**
- `plan-02-components.md` §7b row 11 — *"Normalize **before** comparing"*: test is *"`1.540,00` vs `1540.00`; a spaced vs unspaced identifier"*; **breaking it looks like "the raw values are compared, so the review queue fills with spelling differences"**; task cell `S2-T10` (`FR-20`).
- `plan-02-components.md` §7b row 12 — *"Tolerance by field type"*: test is *"Amounts within cents; identifiers and dates exact"*; **breaking it looks like "cents tolerance applied to an identifier, hiding a genuinely different digit"**; task cell `S2-T10` (`FR-20`).
- `plan-02-components.md` §13, Track 2 — the *"Normalize before comparing"* golden artifact is *"`1.540,00` vs `1540.00` for the same field"*, and it **must fail** when broken: *"They compare **unequal**, i.e. format is measured instead of value"*.
- `plan-02-components.md` §5, `S2-T10`'s verifiable cell — *"`1.540,00` and `1540.00` compare equal; amounts use cents tolerance while identifiers and dates are exact; the raw values are **not** what is compared"*.
- `plan-02-components.md` §8 — **FR-20**; proof is *"`1.540,00` == `1540.00`; identifiers exact; raw values are not what is compared"*.
- `plan-02-components.md` §11 — exit checklist item *"Consistency normalizes before comparing; amounts tolerate cents, identifiers and dates are exact"*.
- `plan-02-components.md` §13, Track 4 — the policy-flag property table: *"No policy flag: No `--min-dpi`, `--cut-confidence`, `--min-chars`, `--tolerance-amounts`"*, with the reason stated — *"Policy is registry data; a flag would change output without entering the cache key (ADR-009, `NFR-06a`)"*.

**Out of scope for this issue**
- **No contrast between extractors.** Comparing two *reads* of the same field is `E04-02`; this issue compares two *values* of the same field.
- **No arithmetic tie-break.** `subtotal + taxes` is `E04-02`'s, and it is a *resolution* of a contrast disagreement, not a comparison rule.
- **No threshold, tolerance or normalization rule as a constant.** **Never** (ADR-009).
- **No `--tolerance-amounts` flag and no environment variable.** **Never** (`NFR-06a`, §13 Track 4).
- **No verdict re-derivation.** The `shape`/`type`/`content`/`digit` verdicts are `E03-02`'s; this component produces the comparison, not the judgement of a single read.
- **No field-type system invented here.** Field types and their tolerances are registry assets; more of them arrive as types are defined. `# TODO: [MVP]`.
- **No date parsing framework beyond what the cycle needs.** Locale-aware parsing at corpus scale is `# TODO: [MVP]`.
- **No adapter import.** **Never** (`sad.md` §1).

**Effort**
**M** — two independent behaviours (normalize-first; tolerance by type) where each has a *negative* assertion (raw comparison must not occur; a tolerance must not be applied to an identifier), plus an evidence record that survives without re-derivation; needs paired fixtures rather than a single input (`wbs.md` §7).

**Owner**
**Domain** — `docflow/components/consistency.py` (`wbs.md` §8).

**Frozen contract touched**
**Consumes** `plans/README.md` §3, Plan 1 row — the ports, the boundary types, and the registry (the tolerance assets arrive through K8 with `E03`'s registry hash as a cache-key term). **Contributes to** the Plan 2 row's *verdict-vector shape* by producing the `consistency` member's inputs, and to the *component artifact chain*: `work/<name>.consistency.json` (`sad.md` §9.1).

---

### `E04-02` — implements `S2-T11`

**Title**
Consistency across extractors — **contrast** — plus arithmetic tie-break.

**Context**
This is the task the whole architecture exists for. Every other check in the system inspects **one** read and asks whether it is *well-formed*; contrast is the only check that asks whether it is *true*, and it can only ask that because the `r` and `p` extractors **fail differently** — one reads by offset, one by bounding box, and their mistakes are therefore uncorrelated. The case is stated in `plan-02-components.md` §1: a total of `15400.00` that was really `1540.00` *"passes shape, type and content, has no check digit, and is caught **only** because a second, differently-failing reader contradicts it"*.

Three failure modes are guarded here, and each is a way to have the machinery and not the property:

- **No disagreement is produced** — the case is emitted as `ok` because every internal check passed. `plan-02-components.md` §7b's row 13: *"the disagreement verdict is not produced"*.
- **`consistency` is invented** — emitted as `ok` when only one read ran, so a field nobody cross-checked becomes indistinguishable from one that survived contrast. Row 13's second half: *"or `consistency` is emitted `ok` when only one read ran"*.
- **The ambiguity reaches a human when arithmetic could have resolved it.** `plan-02-components.md` §13 Track 2: *"The ambiguity reaches the Reviewer when arithmetic could have resolved it"*.

And the constraint that makes the second one structural rather than a matter of discipline: **contrast is scoped to critical fields** (the cost mitigation for the frontier LLM, `plan-02-components.md` §9), which means the *set* of fields contrast covers is itself defined elsewhere — open decision **#3**, load-bearing, reviewed **before this issue starts** (`plan-02-components.md` §12).

**Deliverable**
`docflow/components/consistency.py` (continuation of `E04-01`'s file)

**Depends on**
`S2-T10` — **intra-epic**. Externally: Plan 1's frozen row via E04's root, and the `EpVR` primitive's two reads (`ADR-003`). Inter-epic: **none inward**; it is the source of `E04 → E05`, `E04 → E06` and `E04 → E09`.

**Acceptance criteria**
- [ ] On the `ErpVR` chain, the `1540`/`15400` case produces a **`consistency: disagreement`** verdict on `total`.
- [ ] **Arithmetic is checked first**: where **exactly one** value closes with `subtotal + taxes`, the disagreement is **resolved without a human**.
- [ ] Where **neither** value closes arithmetically, the case **routes to review with all verdicts intact** — no verdict is dropped to make the route easier.
- [ ] An **identifier** disagreement with no arithmetic relation routes to review — the plan's explicit criterion (`§5`), and open decision **#5**'s PoC answer.
- [ ] `consistency` is **set** where both reads ran and **`null` where only one read ran** — never invented as `ok` (`plan-02-components.md` §3's evidence table).
- [ ] A test **fails** if `consistency: ok` is emitted on a single-read run — the negative half of the invariant.
- [ ] Contrast's **scope** is read from policy (the critical-field set), not hardcoded, and there is **no flag** that widens or narrows it at run time.
- [ ] The resolution is **evidence-carrying**: which value was chosen, on what relation, and the normalized forms of both.
- [ ] The component imports **ports only**; the import-isolation check passes over the file it now extends.

**Test / evidence**
- `plan-02-components.md` §7b row 13 — *"Contrast exists and is the only detector of the class"*: test is *"The 1540/15400 case"*; **breaking it looks like "the disagreement verdict is not produced; or `consistency` is emitted `ok` when only one read ran"**; task cell `S2-T11` (`FR-21`).
- `plan-02-components.md` §7c — **the Gherkin scenario this issue closes**: *"The 15400 vs 1540 contrast case"* (`prd.md` §8) — *"Closes at `S2-T11`, asserted end to end by `S2-T17`"*. It is one of only two scenarios Stage 2 owns (`traceability.md` §6).
- `plan-02-components.md` §13, Track 2 — two golden artifacts: *"Contrast catches what internal checks cannot"* (*"A document whose `total` is `15400.00` and whose true value is `1540.00`"*, which **must fail** when *"`consistency: ok` is emitted because shape, type and content all passed"*) and *"Arithmetic breaks the tie"* (*"A document where only one value closes `subtotal + taxes`"*, which **must fail** when *"The ambiguity reaches the Reviewer when arithmetic could have resolved it"*). Both are task `S2-T11`, and the first is described as **the gate's own case**.
- `plan-02-components.md` §6 step 3 — *"Confirm the mode is contrast-capable. The closing chain is `M1-ErpVR` (ADR-003): `rp`, not `r` and not `p`"*; the correct result is `extract.r` **and** `extract.p` both present, *"`consistency` will therefore be set"*; the wrong result is *"closing on `M1-ErVR` or `M1-EpVR`, where `consistency` is `null` by construction and the contrast case cannot be reproduced"*.
- `plan-02-components.md` §6 step 7 — *"Reproduce the contrast case end to end"*: the correct result is *"`consistency: disagreement`; arithmetic checked **first**; if exactly one value closes with `subtotal + taxes`, resolved without a human; if neither closes, routed to review with its verdicts intact"*; the wrong result is *"`content: ok` and everything `ok` because no internal check can see it — the failure the whole architecture exists to catch"*.
- `plan-02-components.md` §8 — **FR-21**; proof is *"AC *The 15400 vs 1540 contrast case*"*.
- `plan-02-components.md` §10, Stage DoD — the riskiest invariant introduced at this stage is *"contrast is the only detector of the plausible-but-false value, and its absence is visible as `consistency: null` rather than invented as `ok`"*, and it must have *"a test that **fails when the invariant is broken**"*.
- `plan-02-components.md` §11 — exit checklist items *"`consistency` is **set** on the `ErpVR` closing run and `null` on a single-read run; the contrast case (1540 vs 15400) is reproduced end to end and arithmetic breaks the tie where it can"*.
- `plan-02-components.md` §9 — the row *"Frontier LLM cost per token during validation"* (H/M, owner stages 2 and 3), whose mitigation is *"Contrast scoped to critical fields only"* — i.e. this issue's scope rule.

**Out of scope for this issue**
- **No `consistency: ok` on a single-read run.** **Never** — the plan's evidence table names that exact wrong result, and `null` is *"information, not a gap"* (`plan-02-components.md` §3).
- **No handling of a single read's validity by defaulting the other.** A missing second read is reported, never simulated. **Never**.
- **No retry until two answers agree.** The same prohibition Plan 1 records for `--repeat` (`kernel-cli.md` §7): manufacturing contrast is worse than missing it, because it looks like evidence. **Never**.
- **No critical-field definition invented here.** The set is policy data (`S3-T04`); today it *"exists as an expression in `02-components.md` and nowhere as data"* — open decision **#3**, load-bearing, reviewed **before this issue starts**. Carried, not resolved.
- **No tie-breaker for a disagreement with no arithmetic relation beyond routing to review.** That route *"is a correct terminal state, not a gap"* (open decision **#5**); the Consistency-arbiter *role* named in `02-arch-components.md` *"has no definition yet"* and is **not** defined here.
- **No contrast beyond critical fields.** `# TODO: [MVP]` — and widening it is a cost decision, not a correctness one.
- **No single confidence score, and no aggregated contradiction count.** The verdicts stay separate (`ADR-005`, `FR-23`). **Never**.
- **No `--tolerance-amounts` or scope flag.** **Never** (ADR-009, `NFR-06a`).
- **No adapter import.** **Never** (`sad.md` §1).

**Effort**
**L** — the plan's riskiest invariant, with a negative assertion (no invented `ok`), a resolution rule (arithmetic first, with a review fallback), a scope dependency on policy, and a Gherkin scenario that closes here; the verification requires an arranged read (the fixture is *the document plus the read*, `§6` step 7) rather than a value comparison (`wbs.md` §7).

**Owner**
**Domain** — `docflow/components/consistency.py` (`wbs.md` §8).

**Frozen contract touched**
**Contributes to** `plans/README.md` §3, Plan 2 row: *the verdict-vector shape* — it produces the `consistency` member, whose "set only where both reads ran" rule is a property Plan 3's shape-identity test depends on (`S3-T13` asserts *"`consistency` is non-null exactly on the four `ErpVR` codes"*). **Consumes** the Plan 1 row's port interface and the fixed decisions of §2 — *no fallback model, engine or threshold* and *emission is a per-field verdict vector, never a single confidence score*. It freezes nothing new; the vector is frozen at `E06-02`.

---

## §4 Epic close condition

E04 is **`done`** when:

1. both issues are `done` — and `E04-02` is not done by proxy: its criterion is a *verdict*, not a code path;
2. the capability is **demonstrable**, and checked by running it: `1.540,00` and `1540.00` compare equal for the same field while identifiers are compared exactly; the `1540`/`15400` document emits **`consistency: disagreement`** on `total`; arithmetic resolves it where exactly one value closes `subtotal + taxes`, and routes to review where neither does; and a test **fails** if `consistency: ok` appears on a run where only one read happened.

**Does E04 gate `S2-T17`?** **Yes, directly.** `S2-T11` is named in `S2-T17`'s dependency set (`wbs.md` §4), making **E04 → E09** a direct inter-epic edge. It also opens **two** other epics — `E05` (`S2-T12` depends on `S2-T11`) and `E06` (`S2-T13` depends on `S2-T11`) — which is why Wave 7 contains two tasks from two different epics.

**The gate's own case lives here.** `plan-02-components.md` §7c lists *"The 15400 vs 1540 contrast case"* as closing at `S2-T11` **and** being asserted end to end by `S2-T17`. So E04 is not merely on the path to the gate; the gate's decisive assertion is a claim this epic makes and `E09` reproduces.

**And the plan's fourth named execution risk is about the gate that closes here** (`plan-02-components.md` §9): *closing the gate on a single-read primitive* — `M1-ErVR`/`M1-EpVR` *"traverse the chain and emit a defensible shape — with `consistency: null` everywhere. The gate would pass while the one claim Stage 2 exists to prove … was never exercised."* The mitigation is that `ADR-003` fixes `ErpVR` as the closing primitive, which is a constraint on `E09-01`'s run — and the reason this epic's acceptance criteria assert `null`-vs-set explicitly rather than only asserting the disagreement.

---

## §5 Traceability

| Issue | `wbs.md` task | FR / NFR (`traceability.md` §4) | Gap? | Evidence of the mapping |
|---|---|:---:|---|
| `E04-01` | `S2-T10` | **FR-20** ("Normalize before comparing; tolerance by type") | no | `1.540,00` == `1540.00`; identifiers exact; raw values are not what is compared |
| `E04-02` | `S2-T11` | **FR-21** ("Contrast across extractors") | no | AC *The 15400 vs 1540 contrast case* |

No issue in E04 has an empty mapping, and no gap is flagged in this epic — the only epic in this decomposition of which that can be said besides `E02`. Both FRs are single-task: `traceability.md` §4.1 assigns FR-20 to `S2-T10` alone and FR-21 to `S2-T11` alone, which is why the reverse check (`traceability.md` §5, `S2-T01`–`S2-T15` → `FR-12…FR-24`) finds no orphan here.

**One attribution worth reading carefully.** `FR-21`'s *proof* is `S2-T11`, but the plan assigns the **assertion** to `S2-T17` (`plan-02-components.md` §7c: *"Closes at `S2-T11`, asserted end to end by `S2-T17`"*), and the frozen shape it produces is verified for all 13 codes by `S3-T13` (Plan 3). Three tasks, one requirement: the component that makes the claim, the gate that reproduces it, and the contract test that generalises it. This issue owns the first.

---

## §6 Risks

From `plan-02-components.md` §9 only — the rows whose mitigation is carried by this epic:

| Risk | L | I | Why it touches E04 | Mitigation carried by this epic |
|---|:---:|:---:|---|---|
| **Frontier LLM cost per token during validation** | H | M | `S2-T11` is the task that *spends*: contrast is the only place in Stage 2 where two reads of the same field are paid for, and the `p` read is a frontier or local generation. | **Contrast scoped to critical fields only (registry policy, ADR-009)** — carried as an acceptance criterion: the scope is read from policy, there is no flag that widens it at run time, and it is not hardcoded. `count_tokens` before spending remains `# TODO: [MVP]` *(Plan 3's `S3-T04` ships the policy asset)* |
| **Sampled artifact regenerated on resume**, silently changing the result | M | H | A contrast disagreement *invites* a third read — and a third read of a sampled extractor is a fresh sample reported as `success` in the docflow sense. The temptation is structural here, not incidental. | **Retry-until-agreement is forbidden** and contrast is never manufactured: where neither value closes arithmetically the case **routes to review with all verdicts intact** rather than re-reading. Carried as an explicit out-of-scope **Never** |

**The plan's third and fourth named execution risks are triggered at this epic's boundary** (`plan-02-components.md` §9):

> *3. Slipping `S2-T12` into the gate without deciding it.* The `catalog` reason vocabulary (`not_run`) is defined by `S2-T12`, yet `FR-23` obliges the **Contract** (`S2-T13`) to emit a `catalog` verdict with that reason on every field. … **This is §12 #1 and it is why it is reviewed before `S2-T11` starts**, not at the gate.
>
> *4. Closing the gate on a single-read primitive.* `M1-ErVR`/`M1-EpVR` traverse the chain and emit a defensible shape — with `consistency: null` everywhere. The gate would pass while the one claim Stage 2 exists to prove … was never exercised.

Risk 3's deadline is set by this epic's start, and it is the reason Wave 6 carries a decision as well as a build. Risk 4 is a constraint on `E09-01`'s chosen primitive; the mitigation is `ADR-003` plus this epic's acceptance criteria, which assert the **`null` vs set** distinction rather than only the disagreement — so a single-read run cannot pass as a contrast run.

**Register rows whose *Owner stage* is 2 that do not materialise here, stated rather than implied.** Three of `plan-02-components.md` §9's rows touch other epics: **Docling install/portability**, **`pdftotext` as a poppler binary** and **GPU availability** (`E02`, consumed onward through the reader), and **Segmenter merged-document gap** (`E01`). Naming them prevents this epic from reading as risk-free by omission — and the frontier-cost row above is the one that *does* land here.

**Open decisions carried, not resolved:**

| `plan-02-components.md` §12 | Question | Touches in E04 | Effect if deferred past Stage 2 |
|---:|---|---|---|
| **#1** | **Whether `S2-T12` (Catalog) becomes a dependency of `S2-T17`.** `FR-23` obliges the Contract (`S2-T13`) to emit a `catalog` verdict with the reason `not_run` on **every** field, and that value is the Catalog's to define — yet the dependency diagram marks the Catalog unreachable | Not an E04 issue, but **reviewed before `S2-T11` starts** (`plan-02-components.md` §12), i.e. inside this epic's window | **Live in this plan.** *"Building `S2-T13` before pinning `not_run` produces either a missing verdict or an invented one. The choice also changes the dependency table, which is the thing `wbs.md` §6.2 is derived from."* Recorded as open, **not resolved** — and if it resolves toward a dependency, it adds an edge `E05 → E09` that this README does not currently draw |
| **#3** | **What defines a "critical field".** *"Both the contrast policy and the target of escalation depend on it; today it exists as an expression in `02-components.md` and nowhere as data"* | `S2-T11` **directly** — contrast is scoped to critical fields | **Load-bearing, reviewed before `S2-T11` starts.** *"Contrast cost is the reason for the scoping, so an undefined critical-field set means either contrast over everything (expensive) or over a guess (unreliable). It also decides what `S3-T04` must ship."* Carried to Plan 3 §12 if unresolved here |
| **#5** | **What decides `r` vs `p` inside `ErpVR` when both run and disagree.** Arithmetic breaks the tie only for fields with an arithmetic relation; for an identifier there is no tie-breaker | `S2-T11` | **PoC answer, and it is not a gap:** *"Handled for the PoC by the documented rule — disagreement with no arithmetic relation routes to **review**, which is a correct terminal state, not a gap. Carried as open because the Consistency-arbiter role named in `02-arch-components.md` has no definition yet."* This issue implements the documented rule; it does **not** define the arbiter role |
| **#2** | What M0's targeted escalation means | Not this epic's — `E03-03` builds the ladder | Load-bearing per `traceability.md` §7.2 (*"settled before Stage 2"*); carried in `E03`'s §6 |

Open decisions **#4** (OCR correction inside the step), **#6** (Reviewer aggregation) and **#7** (`pdftotext` fallback) touch `E02` and `E07`; none is resolved here. **#6** pairs with **#1** in timing — both concern the return loop's boundaries.
