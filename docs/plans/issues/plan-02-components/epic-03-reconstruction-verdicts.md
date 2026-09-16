# E03 — Reconstruction & the validity verdicts

| Field | Value |
|---|---|
| Epic ID | **E03** |
| Capability | Turning positioned tokens into a document with a reading order, then judging it with four independent checks whose "could not" has exactly one owner |
| Issues | `E03-01` (`S2-T07`) · `E03-02` (`S2-T08`) · `E03-03` (`S2-T09`) — all `todo` |
| Issue count | **3** |
| Owner layer | **Domain** (`wbs.md` §8) — `docflow/components/` |
| Wave span | **W3 → W5** (W3: 1 · W4: 1 · W5: 1) |
| Effort total | **2 × L · 1 × M** |
| Source plan | [`../../plan-02-components.md`](../../plan-02-components.md) §2, §4 entry condition 6, §5 (`S2-T07`–`S2-T09`), §6 steps 7–8, §7b, §8, §9 execution risks 2–3, §12 open decisions 1–3, §13 Tracks 2–3 |
| Depends on other epics | **E02** (acquisition routing) |

---

## §1 Objective

E03 delivers the middle of the chain: the **Reconstructor** gives the tokens a layout and an order, and the **Validator** turns that document into the first verdicts the system issues. Two capabilities, one epic, because they share a single load-bearing property — *the document that is judged is the document that was reconstructed, and no code path judges a partial one*.

Three things define the capability:

1. **Reading order is produced here, not absorbed upstream.** `plan-02-components.md` §7b's row targets `S2-T05` **and** `S2-T07` together: if the Reader resolves order, the Reconstructor loses its reason to exist. `FR-17`'s criterion is asserted at the reader boundary and this epic is where the order is actually produced.
2. **The four checks are independent, not chained.** A chained implementation lets a shape failure *suppress* the content verdict — so a field that fails two ways is reported as failing one. `plan-02-components.md` §7b states the failure as *"a chained implementation where a shape failure suppresses the content verdict"*, and the remedy is the plan's own phrasing: **most-severe-failure governs**, which is only meaningful if all four verdicts were issued.
3. **"Could not" is defined in exactly one place.** The escalation ladder lives in the Validator and nowhere else — *"assert the Identifier and Diagnosis contain no escalation decision"*, because the alternative is that *"the policy spreads back across three components, none aware of the others"* (`FR-19`). This is what makes the ladder auditable rather than habitual.

It is a separate deliverable because it owns the **one** place in Stage 2 where the system is allowed to say *"I cannot decide this"* — and because the `not_applicable` half of the plan's frozen contract is emitted from here: the ledger shows which stages this pipeline ran, and the Validator's two escalation cases are the difference between a stage that ran and a stage that was *unable* to.

**Position on the critical path — read this before scheduling.** **`S2-T08` is the busiest node in the plan.** Branches **C, D and E all pass through it** (`plan-02-components.md` §5, `wbs.md` §6.2): it is the fourth link of `E03`'s own reconstruction chain, the first link of the contrast chain (`E04`), and a precondition of the emission chain (`E06`). It is **alone in its wave** (W4) — the plan's own word for that picture is *"the honest picture: three branches are waiting on it"*.

`plan-02-components.md` §9 registers the consequence as **execution risk 2**: *treating `S2-T08` as a place to defer.* Deferring its `# TODO: [MVP]` (the six business-rule categories) is correct; deferring **the four universal checks** *"to unblock branch D blocks three branches at once and removes the only thing that makes escalation meaningful."*

---

## §2 Issues in this epic

| Issue | `wbs.md` task | Title | Wave | Depends on | Effort | PoC markers |
|---|---||---|---|:---:|---|:---:|---|
| `E03-01` | `S2-T07` | Reconstructor: minimal layout + cross-page continuity + reading order | W3 | `S2-T05` → **E02** (inter) | L | `# TODO: [MVP]`: full table reconstruction; `--continuity-only` |
| `E03-02` | `S2-T08` | Validator: 4 **independent** checks issuing independent verdicts; most-severe-failure governs | W4 | `S2-T07` → **E03** (intra) | L | `# TODO: [MVP]`: the 6 pending business-rule categories |
| `E03-03` | `S2-T09` | Validator owns "could not": the escalation ladder and the two cases | W5 | `S2-T08` → **E03** (intra) · `S1-T13` → **Stage 1** (cross-gate) | M | `# TODO: [MVP]`: escalation budget/ceiling |

Intra-epic edges (not drawn as epic edges): `E03-02` → `E03-01`; `E03-03` → `E03-02` — **2 edges**.

This epic produces two outgoing inter-epic edges: **`E03 → E04`** (`S2-T10` depends on `S2-T08`) and **`E03 → E09`** (`S2-T17` depends on `S2-T09`). It is the epic whose `S2-T08` carries the largest fan-out in the plan, and the epic whose `S2-T09` is the Stage 2 carrier of non-negotiable 3 (index README §7).

---

## §3 Issue detail

### `E03-01` — implements `S2-T07`

**Title**
Reconstructor: minimal layout + cross-page continuity + reading order.

**Context**
Two silent failures live on the page boundary. A table whose header is on one page and whose rows continue on the next is **split into two half-tables**, both of which are well-formed — so every later check passes and the association between a column and its meaning is gone. And a header repeated at the top of every page is **kept once per page**, so the same field appears as many times as there are pages, and the extraction downstream sees a document with more columns than it has. `plan-02-components.md` §5 states this issue's criterion as the two associations that must survive: *"a table whose header is on one page and whose rows continue on the next keeps the association; a header repeated across pages is collapsed once"*. And the whole reason the Reader refuses to order tokens is that **this** is where order is decided — `plan-02-components.md` §7b's row is joint, targeting `S2-T05`, `S2-T07`.

**Deliverable**
`docflow/components/reconstructor.py`

**Depends on**
`S2-T05` — **inter-epic** (E02 → E03). It consumes positioned tokens and no order; it defines the order. Externally: Plan 1's frozen row via E02's root.

**Acceptance criteria**
- [ ] `docflow/components/reconstructor.py` exists and produces a **document** with a reading order from positioned tokens.
- [ ] **I/O separation holds:** the component consumes tokens and **mutates no token**; all outputs are new objects, so the artifact this step read is recoverable and re-running the step does not corrupt its input.
- [ ] A table whose **header is on one page and rows continue on the next keeps the association** — the criterion is a maintained relationship, not a value.
- [ ] A **header repeated across pages is collapsed once**, and the collapse is recorded as evidence.
- [ ] A **minimal layout** is produced — the PoC surface — and the component does not attempt full table reconstruction.
- [ ] The reading order is produced **here**, and a test asserts the reader boundary still resolves none (`FR-17`'s other half, shared with `E02-02`).
- [ ] No threshold is a constant: any continuity or layout tolerance is registry data (ADR-009).
- [ ] The component imports **ports only**; the import-isolation check passes over `docflow/components/reconstructor.py`.
- [ ] The output is the documented artifact of the chain — `work/<name>.document.json` — and no earlier step's artifact is rewritten.

**Test / evidence**
- `plan-02-components.md` §7b row 6 — *"The Reader returns tokens, not ordered text"*: the same invariant from the other side. **Breaking it looks like "ordered text, which would absorb part of the Reconstructor and remove its reason to exist"**; task cells `S2-T05`, `S2-T07` (`FR-17`). This issue's test is the *positive* half: the order **is** produced here.
- `plan-02-components.md` §5, `S2-T07`'s verifiable cell — *"A table whose header is on one page and whose rows continue on the next keeps the association; a header repeated across pages is collapsed once"*.
- `plan-02-components.md` §8 — this task's mapping is explicitly conditional: *"Stage 2's criterion requires the reading order it produces (`traceability.md` §7.3 defect 16)"*; it **contributes to FR-24**. Proof is *"Cross-page header/rows association test; repeated-header collapse test"*. **No FR number is invented for it — see §5.**
- `plan-02-components.md` §13 — Track 1's chain includes this step, and the *"Which components the closing flow walks, against which the pipelines run, are different questions"* note names `S2-T07` as on the path **because the demo walks the canonical chain**, not because a pipeline runs it. `traceability.md` §7.3 defect 16 is the record of that distinction being lost once already.
- `plan-02-components.md` §11 — exit checklist item *"The 10 components each run standalone from the previous component's artefact"* (shared with `E08-01`).

**Out of scope for this issue**
- **No full table reconstruction.** `# TODO: [MVP]` (`wbs.md` §4, `prd.md` §4.2, `plan-02-components.md` §2) — minimal layout + continuity is the PoC surface.
- **No `--continuity-only` flag.** `# TODO: [MVP]` — it stays in the deferred list (`plan-02-components.md` §5).
- **No re-reading of pages.** Ordering is derived from the tokens it was given; a component that re-renders or re-OCRs to improve continuity has re-entered the Reader's job.
- **No field extraction.** Turning a document into fields is the `p`-path's job; this issue produces the document.
- **No validity verdict.** Judging the document is `E03-02`.
- **No token mutation.** The artifact the previous step produced is the record; rewriting it breaks the artifact chain `sad.md` §9.1 documents (`plan-02-components.md` §3, *"a component that re-runs its predecessors, or an intermediate that is not the previous component's artefact"*).
- **No threshold as a component constant.** **Never** (ADR-009).
- **No adapter import.** **Never** (`sad.md` §1).

**Effort**
**L** — two continuity behaviours that are *relationships* rather than values (so they cannot be asserted by equality), a minimal layout, and an ordering responsibility that must not leak back upstream; needs multi-page fixtures (`wbs.md` §7).

**Owner**
**Domain** — `docflow/components/reconstructor.py` (`wbs.md` §8).

**Frozen contract touched**
**Consumes** `plans/README.md` §3, Plan 1 row — the ports, the boundary types and the determinism classes. **Contributes to** the Plan 2 row's *component artifact chain*: `work/<name>.document.json` (`sad.md` §9.1) — the artifact `E03-02` reads and the artifact whose shape Plan 3's ledger derives stages from (`S3-T03`). It freezes nothing new.

---

### `E03-02` — implements `S2-T08`

**Title**
Validator: 4 **independent** checks issuing independent verdicts; most-severe-failure governs; no code path skips validation.

**Context**
This is the busiest node in the plan, and it is where the system's answer stops being a measurement and becomes a **judgement**. Two silent failures are possible and both are cheap to introduce:

- **Chaining.** If the checks run in a pipeline, a shape failure returns early and the content verdict is never issued — so a field that is *both* malformed and contradictory is reported as failing one thing, and the consumer is told less than the system knows. `plan-02-components.md` §7b's row states it exactly: *"a chained implementation where a shape failure suppresses the content verdict"*.
- **An escape hatch.** `plan-02-components.md` §7b's ninth row is an *absence* assertion — *"Contract test asserting no `--no-validate` exists, on either surface"* — because a validation-free variant *"would emit fields with no verdicts, needing two shapes downstream"* (`ADR-002`, `FR-18`).

The design the plan fixes is small and specific: **four independent checks**, each issuing its own verdict, with **most-severe-failure governing** the route. That last clause is only meaningful because the verdicts are independent — governing implies a comparison among verdicts that all exist.

**Deliverable**
`docflow/components/validator.py`

**Depends on**
`S2-T07` — **intra-epic**. Externally: Plan 1's frozen row via the chain through E02. Inter-epic: **none inward**; `E03 → E04` and `E03 → E09` are its outgoing edges.

**Acceptance criteria**
- [ ] `docflow/components/validator.py` exists and issues **four independent verdicts** per field: **shape**, **type**, **content**, **digit**.
- [ ] A field can **pass shape and type, fail content, and route to review** — the plan's own criterion, asserted as one test.
- [ ] The **check digit can reject while the rest pass**, and the rejection routes without suppressing the other three verdicts.
- [ ] **Most-severe-failure governs** the route, and the governing verdict is identifiable in the output.
- [ ] **No code path skips validation** — no fast path, no internal caller's shortcut, no rules-only mode.
- [ ] There is **no `--no-validate` flag on either surface**, asserted by a contract test (`ADR-002`, `FR-18`).
- [ ] A test **enumerates the four verdicts** and asserts each is present on every validated field — a field emitted with fewer than four is a failure, not a partial success.
- [ ] The four checks are **independent in the implementation**, not merely in the output: a test that makes shape fail must still observe a content verdict.
- [ ] No threshold, tolerance or rule is a constant in this file: field schemas and tolerances are registry data (`registry/schemas/`, `registry/policies/`, ADR-009).
- [ ] The component imports **ports only**; the import-isolation check passes over `docflow/components/validator.py`.

**Test / evidence**
- `plan-02-components.md` §7b row 8 — *"The four Validator checks are independent"*: test is *"A field passing shape and type, failing content"*; **breaking it looks like "a chained implementation where a shape failure suppresses the content verdict"**; task cell `S2-T08` (`FR-18`).
- `plan-02-components.md` §7b row 9 — *"No code path skips validation"*: test is *"Contract test asserting no `--no-validate` exists, on either surface"*; **breaking it looks like "an escape hatch for rules-only pipelines appears"**; task cell `S2-T08` (`FR-18`, `ADR-002`).
- `plan-02-components.md` §5, `S2-T08`'s verifiable cell — *"A field can pass shape and type, fail content, and route to review; the check digit can reject while the rest pass; no code path skips validation"*.
- `plan-02-components.md` §8 — **FR-18**; proof is *"A field passes shape + type, fails content, routes to review; check digit rejects while the rest pass"*.
- `plan-02-components.md` §7c — matrix row the components must not break: **row 10** (*missing confidence read as perfect*) exercised through *"`S2-T08`/`S2-T14` verdict emission"*, and **row 12** (*a truncated generation parsed as complete*) through *"`S2-T05`/`S2-T08` on the `p` path; contrast must not rescue a truncated read"*.
- `plan-02-components.md` §6 step 8 — *"Prove partial failure"*: the correct result is *"the illegible page is marked as such, the remaining fields are emitted with verdicts and traces, and the absence is declared"*; the wrong results are *"the whole document discarded"* and *"the illegible page reaching OCR and returning invented text indistinguishable from a real read — the outcome `FR-15` calls invalid"*.
- `plan-02-components.md` §11 — exit checklist items *"The four Validator checks issue independent verdicts and the most severe failure governs; no code path anywhere skips validation"* and *"No component imports an adapter; no threshold is a constant inside a component or a kernel"*.
- `plans/README.md` §2 — fixed decision row *"Validation is never skippable — no `--no-validate`"* (`ADR-002`, `prd.md` FR-18); and non-negotiable 2, which this issue mirrors inside the component (index README §7).

**Out of scope for this issue**
- **No escalation ladder.** *Which* re-read a failure triggers, and its two cases, is `E03-03`. This issue issues verdicts and routes on severity; it does not decide *how to find out*.
- **No `--no-validate`, and no validation-free variant on any surface.** **Never** (`ADR-002`, `FR-18`).
- **No single confidence score.** The verdicts stay separate (`ADR-005`, `FR-23`); a score that aggregates them is forbidden. **Never**.
- **No rules-only mode.** Deferred business-rule categories remain `# TODO: [MVP]` — but the four universal checks are **not** deferrable, and that distinction is `plan-02-components.md` §9 risk 2.
- **No verdict vocabulary invented here.** The six emitted verdicts (`shape`/`type`/`content`/`digit`/`consistency`/`catalog`) are the frozen shape; this issue produces four of them, `E04` produces `consistency`, `E05` produces `catalog`.
- **No threshold, tolerance or schema as a constant.** **Never** (ADR-009).
- **No adapter import.** **Never** (`sad.md` §1).
- **The 6 pending business-rule categories** — range, relations between fields, conditional, structural, domain-specific, cross-document. `# TODO: [MVP]` (`plan-02-components.md` §2).

**Effort**
**L** — four checks whose independence is the invariant (so the test must fail when they are chained), an absence assertion on two surfaces, and a routing rule that compares verdicts; the work is the verification, and it is the highest-fan-out task in the plan (`wbs.md` §7).

**Owner**
**Domain** — `docflow/components/validator.py` (`wbs.md` §8).

**Frozen contract touched**
**Consumes** `plans/README.md` §3, Plan 1 row — the ports, the boundary types and the closed `reason.code` set (a validation failure that is *callable but impossible* is a `Reason`, not an exception). **Contributes to** the Plan 2 row's *verdict-vector shape* — it produces four of the six members — and to the Plan 2 row's *component artifact chain*: `work/<name>.validated.json` (`sad.md` §9.1). Freezes nothing new: the vector's shape is frozen by `E06-02`.

---

### `E03-03` — implements `S2-T09`

**Title**
Validator owns "could not": the escalation ladder and its two cases.

**Context**
When the system cannot decide a field, it has exactly three options: guess, drop the field, or **go and look again**. The third is the only one that improves the answer, and it is also the one that can quietly destroy the record — because a re-read of a **sampled** artifact produces a *different* value reported as success (non-negotiable 3, `plans/README.md` §2). The plan's answer is a ladder with two cases whose *difference is visible in the ledger*: *"an invalid field renders **only** its region and contrasts against the existing value; a missing field re-reads the whole document with **no saving**"*. Two things follow and both are this issue's real content:

- **The ladder is defined in exactly one place.** `plan-02-components.md` §7b's row is an absence assertion — *"Assert the Identifier and Diagnosis contain no escalation decision"* — because *"the policy spreads back across three components, none aware of the others"* is how a ladder becomes a habit.
- **The escalation re-read is traced back to the right pixels.** `NFR-07`'s row targets `S2-T09` and `S2-T13` jointly: *"a crop's local coordinates reach the Contract; both boxes are valid JSON so nothing else notices"*. The invalid-field case renders a region, and that region's coordinates must survive to the per-field trace.

**Deliverable**
`docflow/components/validator.py` (continuation of `E03-02`'s file)

**Depends on**
`S2-T08` — **intra-epic**. `S1-T13` — **cross-gate**: the invalid-field case renders a region through K3's `crop`, whose inverse map is frozen at Gate 1 (`NFR-07`, row 8 of the matrix). Inter-epic: **none inward**.

**Acceptance criteria**
- [ ] `docflow/components/validator.py` contains the escalation ladder, and it is the **only** place in Stage 2 where an escalation decision is made.
- [ ] The **invalid-field case renders only its region** and contrasts against the **existing** value — it does not re-read the page.
- [ ] The **missing-field case re-reads the whole document with no saving**, and that difference is **visible in the ledger**.
- [ ] The two cases behave **differently** and the difference is assertable — not a single "re-read" path with a parameter.
- [ ] A test asserts the **Identifier and Diagnosis contain no escalation decision** (`plan-02-components.md` §7b row 10).
- [ ] The escalation's crop is **traced back to source page coordinates**: `evidence.inverse_map` is honoured, and a crop's local coordinates **never** reach the Contract as a page region (`NFR-07`).
- [ ] Escalation **does not re-sample a sampled artifact to fill a gap** — the ladder escalates against the existing value; a missing sampled artifact is reported `failed`, never regenerated (non-negotiable 3, index README §7).
- [ ] The escalation decision is recorded in the **ledger**, so *which case fired* is a fact rather than an inference.
- [ ] No escalation budget or ceiling is a constant — it is `# TODO: [MVP]` and, when it lands, registry data.
- [ ] The component imports **ports only**; the import-isolation check still passes over the file it now extends.

**Test / evidence**
- `plan-02-components.md` §7b row 10 — *"'Could not' is defined in exactly one place"*: test is *"Assert the Identifier and Diagnosis contain no escalation decision"*; **breaking it looks like "the policy spreads back across three components, none aware of the others"**; task cell `S2-T09` (`FR-19`).
- `plan-02-components.md` §7b row 19 — *"The trace points at the right pixels"*: test is *"Escalation crop traced back to the source page"*; **breaking it looks like "a crop's local coordinates reach the Contract; both boxes are valid JSON so nothing else notices"**; task cells `S2-T09`, `S2-T13` (`NFR-07`).
- `plan-02-components.md` §7c — matrix row the components must not break: **row 8** (*a crop's local coordinates as a page region*) exercised through *"`S2-T09` → `S2-T13` trace"*.
- `plan-02-components.md` §5, `S2-T09`'s verifiable cell — *"An invalid field renders **only** its region and contrasts against the existing value; a missing field re-reads the whole document with **no saving**, and this is visible in the ledger"*.
- `plan-02-components.md` §8 — **FR-19**, **NFR-07**; proof is *"Invalid → region only; missing → whole document with no saving, visible in the ledger"*.
- `plan-02-components.md` §13, Track 2 — the *"Validator owns 'could not'"* golden artifact is *"an invalid field and a missing field"*, and it **must fail** when broken: *"escalation is decided in two places, so the ladder becomes a habit"*.
- `plan-02-components.md` §9 — the row *"Sampled artifact regenerated on resume"* (M/H) states where the invariant is exercised in Stage 2: *"exercised through a component in §6 step 10"*. `E03-03` is the component that would be tempted to re-sample.
- `plan-02-components.md` §11 — exit checklist item *"The escalation ladder's two cases behave differently and the difference is visible in the ledger: invalid → region only; missing → whole document, no saving"*.
- `plan-02-components.md` §12 open decision **#2** — what M0's targeted escalation means, *"with no page and no image, 'render the region' is meaningless"*. Carried in §6; **not resolved**.

**Out of scope for this issue**
- **No escalation in the Identifier or Diagnosis.** **Never** — one owner, asserted by the absence test.
- **No re-sampling to fill a gap.** The ladder never regenerates a missing sampled artifact; the consequence is `failed` with an evidence-missing reason (non-negotiable 3, Plan 1's `E05-03`). **Never**.
- **No escalation budget or ceiling.** `# TODO: [MVP]` — and the plan carries it as a marked shortcut rather than a design gap.
- **No OCR correction.** Whether correction is inside the OCR step is open decision **#4** (`E02`); this issue does not correct, it re-reads *or* contrasts.
- **No M0 escalation semantics.** What "render the region" means with no page and no image is open decision **#2** — *"it should be settled before Stage 2"* per `traceability.md` §7.2. This issue builds the ladder; the M0 case is **carried, not decided**.
- **No review UI.** Routing to review emits a case; the queue and its workflow are `E07-01` and `# TODO: [MVP]`.
- **No coordinate arithmetic inside the Contract.** The inverse map must be honoured **here**, before the trace leaves the component (`NFR-07`).
- **No threshold or budget as a constant.** **Never** (ADR-009).
- **No adapter import.** **Never** (`sad.md` §1).

**Effort**
**M** — two cases that must behave differently and be distinguishable in the ledger, plus two absence assertions (no escalation elsewhere; no regenerated sample) and the inverse-map obligation; interacting concerns against fixtures rather than a heavyweight dependency (`wbs.md` §7).

**Owner**
**Domain** — `docflow/components/validator.py` (`wbs.md` §8).

**Frozen contract touched**
**Freezes** `plans/README.md` §3, Plan 2 row: *the escalation policy's single ownership (Validator)* — this issue is the item's sole author, and Plan 3 consumes the ladder unchanged. **Consumes** the Plan 1 row's `PdfSource`/K3 `crop` inverse map (`NFR-07`, row 8) and the determinism classes. **Contributes to** the Plan 2 row's *per-field trace shape*: the region an escalation rendered is what `trace.page` must reconcile.

---

## §4 Epic close condition

E03 is **`done`** when:

1. all three issues are `done` — including `E03-03`, whose deliverable is a continuation of `E03-02`'s file and whose criterion is partially an *absence* (no escalation decision in two other components);
2. the capability is **demonstrable**, and checked by running it: a multi-page table's header-to-rows association survives; a repeated header is collapsed once; a field that passes shape and type but fails content still carries **four** verdicts and routes to review; a test **fails** if a `--no-validate`-shaped flag exists; the invalid-field case renders **only** its region with no page re-read; and the missing-field case re-reads the whole document **with no saving**, visible in the ledger.

**Does E03 gate `S2-T17`?** **Yes, directly — and it is the plan's busiest nexus.** `S2-T09` is named in `S2-T17`'s dependency set (`wbs.md` §4), making **E03 → E09** a direct inter-epic edge. It also produces **E03 → E04** (`S2-T10` depends on `S2-T08`). So `S2-T08` — alone in Wave 4 — sits on the path to the gate **through two different branches**, which is what makes it the busiest node: branches C, D and E all pass through it (`plan-02-components.md` §5).

**Consequence for scheduling, stated rather than implied.** An epic that is a direct gate dependency **and** the nexus of three branches cannot be closed late without moving the stage close. `plan-02-components.md` §9 risk 2 names the specific way it is lost: deferring *"the four universal checks"* to unblock branch D, which *"blocks three branches at once and removes the only thing that makes escalation meaningful"*. The `# TODO: [MVP]` on the six business-rule categories is the deferral that **is** correct; the four checks are not part of it.

---

## §5 Traceability

| Issue | `wbs.md` task | FR / NFR (`traceability.md` §4) | Gap? | Evidence of the mapping |
|---|---|:---:|---|
| `E03-01` | `S2-T07` | *(no FR of its own)* — **required by Stage 2's criterion** (`traceability.md` §7.3 defect 16); **contributes to FR-24** | **gap** | Cross-page header/rows association test; repeated-header collapse test |
| `E03-02` | `S2-T08` | **FR-18** ("4 independent checks; no `--no-validate`") | no | A field passes shape + type, fails content, routes to review; check digit rejects while the rest pass |
| `E03-03` | `S2-T09` | **FR-19** ("Validator owns 'could not' and the ladder") · **NFR-07** ("Trace points at the right pixels") | no | Invalid → region only; missing → whole document with no saving, visible in the ledger |

### Gap flagged — `E03-01` (`S2-T07`) has no FR, and the gap is a *conditional* one

`plan-02-components.md` §8 records this task's mapping in the conditional form, and this issue preserves that form rather than flattening it into an FR number:

- **What is missing:** `traceability.md` §4.1 has **no row naming the Reconstructor**. Nothing in FR-01 … FR-33 names layout, continuity or reading order as its own requirement. Its §4 row in the plan reads *"Stage 2's criterion requires the reading order it produces (`traceability.md` §7.3 defect 16); contributes to **FR-24**."*
- **What it traces to:** **defect 16** — the record of exactly this confusion. `traceability.md` §7.3 defect 16 found that the Segmenter and Identifier *"were listed as non-critical while `S2-T17` depended on `S2-T03`"*, and while fixing it, *"two further instances of the same collapse were found and fixed while verifying: `S2-T07` (Reconstructor — Stage 2's criterion requires the reading order it produces) and `S2-T12` (Catalog — now recorded as an open decision)"*. So the task is **justified by the closing criterion**, and the record of why is in the defect register rather than in an FR.
- **Why it is not orphan work:** `traceability.md` §5 traces `S2-T01`–`S2-T15` to `FR-12…FR-24` as a group; and `FR-17` (positioned tokens, no reading order) is only a *requirement* if something downstream produces the order — which is this task and only this task. It also contributes to **FR-24** (partial failure), because a partial document is only marked correctly if continuity is understood.
- **What closing it would cost:** adding an FR for *"the reading order is produced by a component, and the reader does not produce it"* — a change to `prd.md`.
- **Do not fill it by inventing a number.** `E03-01` is a **flag**, not a hole — and the plan's own instruction is to record it, because the collapse it guards against (branch membership vs. gate dependency) is the class of error the plan set exists to prevent.

No other issue in E03 has an empty mapping.

---

## §6 Risks

From `plan-02-components.md` §9 only — the rows whose mitigation is carried by this epic:

| Risk | L | I | Why it touches E03 | Mitigation carried by this epic |
|---|:---:|:---:|---|---|
| **Sampled artifact regenerated on resume**, silently changing the result | M | H | `E03-03` is the component that would be *tempted* to re-sample: the escalation ladder exists precisely to "go and look again", and the invalid-field case re-reads a region. A ladder that re-reads a missing **sampled** artifact turns an evidence gap into a fresh, different answer reported as success. | The ladder escalates **against the existing value** (invalid → region only, contrasting with what is there); a missing sampled artifact reports `failed` with an evidence-missing reason and is **never regenerated** — carried as an acceptance criterion here, and exercised through a component at `plan-02-components.md` §6 step 10 (`E09-01`) |

**The second and third named execution risks are *about* this epic** (`plan-02-components.md` §9):

> *2. Treating `S2-T08` as a place to defer.* It is the busiest node — branches C, D and E pass through it. Deferring its `# TODO: [MVP]` (the 6 business-rule categories) is correct; deferring **the four universal checks** to unblock branch D blocks three branches at once and removes the only thing that makes escalation meaningful.
>
> *3. Slipping `S2-T12` into the gate without deciding it.* The `catalog` reason vocabulary (`not_run`) is defined by `S2-T12`, yet `FR-23` obliges the **Contract** (`S2-T13`) to emit a `catalog` verdict with that reason on every field. Building `S2-T13` before the `not_run` value is pinned produces either a missing verdict or an invented one. This is §12 #1 and it is why it is reviewed **before `S2-T11` starts**, not at the gate.

Risk 2 is mitigated structurally and is drawn in the wave map: W4 contains **only** `S2-T08`, so the deferral cannot be hidden inside a wave that looks busy. Risk 3 does not land on an E03 issue — it lands on `E04-02` (`S2-T11`) and `E06-01` (`S2-T13`) — but it is **triggered by this epic's timing**, because `S2-T11` cannot start until `S2-T08` and `S2-T10` are done. It is therefore named here as a hand-off, not restated as an E03 risk.

**Register rows whose *Owner stage* is 2 that do not materialise here, stated rather than implied.** Four of `plan-02-components.md` §9's rows touch other epics: **Docling install/portability** and **`pdftotext` as a poppler binary** (`E02`), **GPU availability** (`E02`, consumed onward), and **Frontier LLM cost per token during validation** (`E03`'s validator *consumes* the frontier path only through the `p` extractor, whose cost mitigation is scoped at `S3-T04` — `count_tokens` is `# TODO: [MVP]`). Naming them prevents this epic from reading as risk-free by omission.

**Open decisions carried, not resolved:**

| `plan-02-components.md` §12 | Question | Touches in E03 | Effect if deferred past Stage 2 |
|---:|---|---|---|
| **#2** | **What M0's targeted escalation means.** With no page and no image, "render the region" is meaningless. Either it becomes "re-read a span of the supplied string", or M0 escalates only to the cascade | `S2-T09` (builds the ladder) | **Load-bearing.** `traceability.md` §7.2 names it *"the one item that should be settled before Stage 2"*: `M0-*` is three of the thirteen codes, and discovering at `S3-T13` that M0 breaks an assumption the other ten materials share *"would invalidate the shape-identity test (`FR-33`) rather than one pipeline"*. The ladder is built so that either answer **can** be implemented; the answer itself is **not chosen here** |
| **#3** | **What defines a "critical field"** | `S2-T09`'s escalation target depends on it (the plan: *"Both the contrast policy and the target of escalation depend on it"*) | **Load-bearing, reviewed before `S2-T11` starts.** Today it *"exists as an expression in `02-components.md` and nowhere as data"*; its home is `S3-T04`. Carried here so that no component constant is created to stand in for it. `# TODO: [MVP]` |
| **#1** | Whether `S2-T12` (Catalog) becomes a dependency of `S2-T17`, or `not_run` is defined where the Contract can reach it | Not an E03 issue, but `E06-01` (`S2-T13`) builds **after** this epic and depends on the answer | **Live in this plan.** Reviewed **before `S2-T11` starts** — which is inside `E04`, after `S2-T08` completes. Named here because the deadline is set by this epic's completion |

Open decisions **#4** (OCR correction inside the step) and **#7** (`pdftotext` fallback) both touch `E02`; **#5** (`r` vs `p` tie-break) touches `E04`; **#6** (Reviewer aggregation) touches `E07`. None is resolved here.
