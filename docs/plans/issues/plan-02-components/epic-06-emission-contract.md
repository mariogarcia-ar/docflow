# E06 — Emission — the Contract & the verdict vector

| Field | Value |
|---|---|
| Epic ID | **E06** |
| Capability | Emitting only once every page is resolved, and emitting six independent verdicts plus a per-field trace — never a score |
| Issues | `E06-01` (`S2-T13`) · `E06-02` (`S2-T14`) — all `todo` |
| Issue count | **2** |
| Owner layer | **Domain** (`wbs.md` §8) — `docflow/components/` · **Surface** for its consumer `S2-T16` (`E08`) |
| Wave span | **W7 → W8** (W7: 1 · W8: 1) |
| Effort total | **1 × L · 1 × M** |
| Source plan | [`../../plan-02-components.md`](../../plan-02-components.md) §3, §5 (`S2-T13`, `S2-T14`), §6 steps 6, 8–9, §7b, §7c, §8, §9 execution risk 3, §11, §12 open decisions 1, 3, §13 Tracks 2–3 |
| Depends on other epics | **E04** (cross-read consistency) |

---

## §1 Objective

E06 delivers the artifact the whole project exists to produce: **the verdict vector and its trace, per field**. It is the epics that Plan 3 *may not change* — `plans/README.md` §3 names this shape as the Plan 2 frozen row's first item, and §13 Track 3 calls it *"the thing a consumer integrates against"*.

Two capabilities, one epic, because they are one deliverable split at the point where the risk changes:

1. **The barrier** (`E06-01`) decides **when** emission is legal. A field may only be emitted once every page it depends on is resolved — otherwise a document is emitted while one of its pages is still being read, and the missing value is indistinguishable from an absent one. This issue also emits **heterogeneous provenance**: a document with some fields offset-traced and others bbox-traced must carry both correctly, and *"a single assumed origin — with per-field escalation, provenance stops being single"* is the wrong result it guards against.
2. **The vector** (`E06-02`) decides **what** is emitted. Six verdicts — `shape`, `type`, `content`, `digit`, `consistency`, `catalog` — **kept separate**, and `consistency` set **only where both reads ran**. `plan-02-components.md` §7b's row 16 is an absence assertion: *"Assert no derived single number exists in the output"*, because *"a `confidence` field appears and a field nobody cross-checked becomes indistinguishable from one that survived contrast"*.

It is a separate deliverable because it is where **two** of the plan's non-negotiables converge: non-negotiable 3 (a sampled artifact is evidence and is never regenerated — the barrier refuses to emit over a gap) and `ADR-005` (no single confidence score exists anywhere, on any surface, in any stage). A score emitted here would be consumed by someone who does not know what it averages — `plan-02-components.md` §13 Track 3 states the reason plainly: the threshold that decides *what to do about* a verdict *"belongs to the consumer, who knows their use case"*.

**Position on the critical path — read this before scheduling.** E06 is the **tail of branch E** and sits on the nine-link chain: `S2-T13` is link 7 and `S2-T14` is link 8, immediately before the gate. It is also the **only epic that produces two outgoing inter-epic edges into the two epics the gate does not wait on** — `E06 → E07` (Reviewer) and `E06 → E08` (per-component CLI) — plus `E06 → E09` for the gate itself.

And it carries the plan's **third** named execution risk on its own start — *building `S2-T13` before the `not_run` value is pinned produces either a missing verdict or an invented one* (`plan-02-components.md` §9 risk 3). The Contract must emit a `catalog` verdict on **every** field, with a reason defined by `E05-01`. `plan-02-components.md` §12 reviews open decision **#1** **before `S2-T11` starts** precisely so that this epic does not begin with an undefined vocabulary.

---

## §2 Issues in this epic

| Issue | `wbs.md` task | Title | Wave | Depends on | Effort | PoC markers |
|---|---||---|---|:---:|---|:---:|---|
| `E06-01` | `S2-T13` | Contract: barrier, heterogeneous provenance, per-field `(page, extractor)` trace | W7 | `S2-T11` → **E04** (inter) | L | `# TODO: [MVP]`: `--format md\|html` |
| `E06-02` | `S2-T14` | Contract: the verdict vector, with `consistency` set only where both reads ran | W8 | `S2-T13` → **E06** (intra) | M | — |

Intra-epic edge (not drawn as an epic edge): `E06-02` → `E06-01` — **1 edge**.

This epic produces **three** outgoing inter-epic edges — `E06 → E07` (`S2-T15` depends on `S2-T13`), `E06 → E08` (`S2-T16` depends on `S2-T14`) and `E06 → E09` (`S2-T17` depends on `S2-T14`) — and it is where the Plan 2 frozen row's first three items are authored: the verdict-vector shape, the per-field trace shape, and the consumption of the `catalog` reason vocabulary.

---

## §3 Issue detail

### `E06-01` — implements `S2-T13`

**Title**
Contract: barrier, heterogeneous provenance, per-field `(page, extractor)` trace.

**Context**
Three silent failures are prevented by the same component, and the first two are about **when** to say something.

- **Emitting early.** A document is written out while one of its pages is still unresolved, so a field that will exist is absent — and an absent-but-that-will-exist verdict reads exactly like a field the document does not contain. The barrier exists to make emission wait for a resolved page set.
- **Discarding the document on one bad page.** The opposite failure, and `FR-24`'s: §7b's row 18 states it as *"the document is discarded instead of emitted with the absence declared"*, and the plan's criterion is *"an illegible page is marked and the rest still emitted"* — the Gherkin scenario *"Partial failure marks one page"* (`prd.md` §8) closes here.
- **A single assumed origin for the trace.** With per-field escalation (`E03-03`), provenance **stops being single**: some fields are offset-traced from the `r` read and others are bbox-traced from a region the escalation rendered. `plan-02-components.md` §3's evidence table names the wrong result exactly: *"a single assumed origin — with per-field escalation, provenance stops being single"*. And `NFR-07`'s row names the concrete version: *"a crop's local coordinates reach the Contract; both boxes are valid JSON so nothing else notices"*.

**Deliverable**
`docflow/components/contract.py`

**Depends on**
`S2-T11` — **inter-epic** (E04 → E06). The Contract emits the results of a consistency pass; emitting before contrast ran would freeze a value that later changes. Intra-epic: none — this is the epic's root. Inter-epic: this is one of the epic's three outgoing edges' sources.

**Acceptance criteria**
- [ ] `docflow/components/contract.py` exists and **emits the barrier only when all pages are resolved**.
- [ ] A document with **one illegible page of ten** emits the **nine** with verdicts and traces, **marks the illegible one**, and **declares the absence** — the document is **not** discarded (`FR-24`).
- [ ] The barrier **does not release** while any page is unresolved; a partial resolved set produces **no** emission of the unresolved page's fields.
- [ ] A document with **`r` offset-traced fields** beside **`p` bbox-traced fields** emits **both correctly** — asserted per field, not per document.
- [ ] **Every field carries `trace.page` and `trace.extractor`** — the per-field pair, not a document-level one.
- [ ] A crop's **local coordinates never reach the Contract as a page region**: the inverse map is honoured before the trace is written (`NFR-07`, matrix row 8, joint with `E03-03`).
- [ ] **Every field carries its `catalog` verdict with a reason**, including where the Catalog never ran (`not_run`) — `FR-23`'s obligation on this component.
- [ ] The output is written through the artifact chain as `work/<name>.document.json` → the emitted result, so **no intermediate is re-derived**: the Contract does not re-run its predecessors.
- [ ] The component imports **ports only**; the import-isolation check passes over `docflow/components/contract.py`.

**Test / evidence**
- `plan-02-components.md` §7b row 18 — *"Failure is partial"*: test is *"Ten pages, one illegible"*; **breaking it looks like "the document is discarded instead of emitted with the absence declared"**; task cell `S2-T13` (`FR-24`, AC below).
- `plan-02-components.md` §7b row 19 — *"The trace points at the right pixels"*: test is *"Escalation crop traced back to the source page"*; **breaking it looks like "a crop's local coordinates reach the Contract; both boxes are valid JSON so nothing else notices"**; task cells `S2-T09`, `S2-T13` (`NFR-07`).
- `plan-02-components.md` §7c — **the Gherkin scenario this issue closes**: *"Partial failure marks one page"* (`prd.md` §8) — *"Closes at `S2-T13`, asserted by `S2-T17`"*. One of only two scenarios Stage 2 owns (`traceability.md` §6).
- `plan-02-components.md` §7c — matrix rows the components must not break: **row 8** (*a crop's local coordinates as a page region*) exercised through *"`S2-T09` → `S2-T13` trace"* and **row 11** (*a truncated page read as a page with no text*) through *"`S2-T05` reader path, partial-failure emission"*.
- `plan-02-components.md` §6 step 8 — *"Prove partial failure"*: *"the illegible page is marked as such, the remaining fields are emitted with verdicts and traces, and the absence is declared"*; wrong results are *"the whole document discarded"* and the illegible page reaching OCR with invented text.
- `plan-02-components.md` §6 step 9 — *"Prove the Catalog's absence is a fact, not a gap"*: `verdicts.catalog` and its reason on **every** field; correct is `unverified` with reason `not_run`; wrong is *"`catalog` absent, or `unverified` with no reason"*.
- `plan-02-components.md` §8 — **FR-23**, **FR-24**, **NFR-07**; proof is *"AC *Partial failure marks one page*; the barrier release test; heterogeneous-provenance test; `catalog` present with a reason on every field"*.
- `plan-02-components.md` §11 — exit checklist items *"A document with one illegible page and nine readable ones emits the nine with verdicts and traces and marks the illegible one — the document is not discarded"* and *"Every field in the output carries `value`, `extractor`, `trace`, and **all six** verdicts kept separate"* (shared with `E06-02`).
- `plan-02-components.md` §3, evidence table — the rows for `trace.page`/`trace.extractor` per field, the partial-failure row, and the `catalog` row.

**Out of scope for this issue**
- **No verdict decision on the six members' *values*.** This issue emits them; `E06-02` fixes the vector's shape and the `consistency`-null rule; `E03`/`E04`/`E05` produce the values.
- **No single score.** **Never** (`ADR-005`, `FR-23`) — the vector's members stay separate, and an aggregation is the shape a consumer would threshold on and be wrong.
- **No `--format md|html`.** `# TODO: [MVP]` (`plan-02-components.md` §2, §5).
- **No `--show-evidence` flag.** `# TODO: [MVP]` — evidence is in the artifact, not behind a flag.
- **No critical-field definition.** The `catalog` scope and the contrast scope both trace to open decision **#3** (`S3-T04`); this issue emits a verdict for **every** field regardless of whether it is critical.
- **No `catalog` reason vocabulary invented or extended.** The three values are `E05-01`'s closed set; a fourth would change the frozen row (`plans/README.md` §3). **Never**.
- **No regeneration of a missing sampled artifact to fill the barrier.** The barrier waits; it does not re-sample. **Never** (index README §7, non-negotiable 3).
- **No adapter import.** **Never** (`sad.md` §1).
- **No stage added to the artifact chain.** `--format` and presentation are Plan 3's; the chain is fixed by `sad.md` §9.1.

**Effort**
**L** — an emission barrier whose release condition is an *absence* assertion, partial-failure handling that must both mark and emit, per-field heterogeneous provenance with an inverse-map obligation, and a `catalog` obligation on every field; the verification requires ten-page fixtures with one bad page and a mixed-provenance document (`wbs.md` §7).

**Owner**
**Domain** — `docflow/components/contract.py` (`wbs.md` §8).

**Frozen contract touched**
**Freezes** `plans/README.md` §3, Plan 2 row: *the component artifact chain `.<step>.json`* (this issue is the last component write before the emitted result) and the *`not_applicable` list emitted by the ledger writer* (the barrier is what makes a stage's absence a fact rather than an ambiguity). **Contributes to** the row's *per-field trace shape* and *verdict-vector shape*, both finalised in `E06-02`. **Consumes** the Plan 1 row — the ports, the 7 durable ledger states, and the determinism classes (a barrier over a sampled page's artifact must treat a missing one as `failed`, not as an unfinished page).

---

### `E06-02` — implements `S2-T14`

**Title**
Contract: the verdict vector, with `consistency` set only where both reads ran.

**Context**
This issue fixes the **shape** the consuming system integrates against, and its most important content is a distinction that is easy to erase: `consistency: null` is **information**, not a gap. A field that was read once was never cross-checked — and if that absence is emitted as `ok`, a field nobody verified becomes indistinguishable from one that survived contrast. `plan-02-components.md` §3's evidence table states both directions: on an `ErpVR` run `consistency` is *"set, because both reads ran"* and `null` there means *"contrast silently absent where it was paid for"*; on a single-read run it is *"`null` — and `null` is information, not a gap"* and the wrong result is *"`ok` invented for a field nobody cross-checked"*.

`plan-02-components.md` §7b's sixteenth row is the second half of the capability, and it is an absence assertion about the *whole* output: **`"Emission is a verdict vector, never a score"`** — *"Assert no derived single number exists in the output"*, breaking as *"a `confidence` field appears and a field nobody cross-checked becomes indistinguishable from one that survived contrast"*. That is `ADR-005`, and it is the one design prohibition that a helpful addition would violate.

**Deliverable**
`docflow/components/contract.py` (continuation of `E06-01`'s file)

**Depends on**
`S2-T13` — **intra-epic**. Externally: Plan 1's frozen row via E06's root. Inter-epic: **none inward**; it is the source of `E06 → E08` and `E06 → E09`.

**Acceptance criteria**
- [ ] `work/<name>.json` (the emitted result) matches the **documented JSON shape**: per field, `value`, `extractor`, `trace`, and `verdicts` with **all six** members — `shape`, `type`, `content`, `digit`, `consistency`, `catalog` — present and **separate**.
- [ ] `consistency` is **set** on an `ErpVR` run and **`null` on a single-read run** — asserted in both directions.
- [ ] A test **fails** if `consistency: ok` is emitted for a field with no second read — the negative half, which is the one that gets lost.
- [ ] **No derived single score exists anywhere in the output** — no `confidence`, no aggregate, no contradiction count. Asserted by a test over the emitted bytes.
- [ ] All six members are present on **every** field, including `catalog` with its reason and `consistency` with `null` where applicable.
- [ ] The trace is present **per field** in the emitted output, with both `trace.page` and `trace.extractor` (continuity with `E06-01`).
- [ ] The threshold that decides *what to do about* a verdict is **not** in the output: no default, no recommendation, no action field.
- [ ] The emitted shape is **stable for a re-run** on the same inputs — a deterministic emission (the vector is not a sampled artifact).
- [ ] **The Track 3 consumer test**: a module imports the frozen verdict-vector shape and the per-field trace shape **without defining a parallel type of its own** — `plans/README.md` §6 Track 3's *"a consumer imports it and adds **no new type**"*, and `plan-03-pipelines.md` §13 Track 3's *"configuration and data, no new code"*. Asserted as an **absence**: the shape has one definition, in `docflow/components/contract.py`, and a test fails if a second one appears.
- [ ] Emitting a result **does not re-run any predecessor**: the Contract reads `work/<name>.consistency.json` (via `E05`) and writes its own artifact; the chain is not re-walked (`FR-12`'s property, asserted here at the artifact level).
- [ ] The component imports **ports only**; the import-isolation check passes over the file it now extends.

**Test / evidence**
- `plan-02-components.md` §7b row 16 — *"Emission is a verdict vector, never a score"*: test is *"Assert no derived single number exists in the output"*; **breaking it looks like "a `confidence` field appears and a field nobody cross-checked becomes indistinguishable from one that survived contrast"**; task cell `S2-T14` (`ADR-005`, `FR-23`).
- `plan-02-components.md` §7b row 17 — *"`consistency: null` on single reads"*: test is *"Run an `ErVR` and an `EpVR` code"*; **breaking it looks like "`consistency` invented as `ok` for a field with no second read"**; task cell `S2-T14` (`FR-23`).
- `plan-02-components.md` §13, Track 2 — the *"Verdicts stay separate"* golden artifact is *"Any emitted field"*, and it **must fail** when broken: *"A single derived score appears — the shape a consumer would threshold on and be wrong"* (`S2-T14`, ADR-005).
- `plan-02-components.md` §3, evidence table — the first row (`out/<name>.json` shape), the second and third rows (`consistency` on `ErpVR` vs single read), and the fourth row (`catalog` on every field with a reason). The evidence table **is** this issue's acceptance criterion set, unexpanded.
- `plan-02-components.md` §6 step 6 — *"Read the emitted field shape"*: correct is *"every field: `value`, `extractor`, `trace` (`page` + `offset` or bbox), `verdicts` with all six members separate"*; wrong is *"a collapsed score; a missing `catalog`; a trace without a page or without an extractor"*.
- `plan-02-components.md` §8 — **FR-23**; proof is *"Output matches the documented shape; `consistency: null` on single-read runs; no derived score exists"*. `traceability.md` §4.1 assigns **FR-23** jointly to `S2-T13`, `S2-T14` and `S2-T12`.
- `plan-02-components.md` §11 — exit checklist items *"Every field in the output carries `value`, `extractor`, `trace`, and **all six** verdicts kept separate"*, *"**No** derived single score exists anywhere in the output"*, and *"`consistency` is **set** on the `ErpVR` closing run and `null` on a single-read run"*.
- `plan-02-components.md` §13, Track 3 — *"The code that gets reused"*: the frozen verdict vector is *"Per field: `value`, `extractor`, `trace`, and `verdicts` with `shape`/`type`/`content`/`digit`/`consistency`/`catalog` — kept separate"*, consumed by *"The other system (`FR-33`), and Plan 3's 13 codes"*.
- `plans/README.md` §2 — fixed-decision row *"Emission is a per-field verdict vector … plus a trace, **never** a single confidence score"* (`ADR-005`, `prd.md` FR-23, `sad.md` §11).

**Out of scope for this issue**
- **No single confidence score.** **Never** (`ADR-005`, `FR-23`) — and the test is written against the emitted bytes so that adding one fails the suite.
- **No `consistency: ok` where only one read ran.** **Never** — `null` is the information; inventing `ok` deletes it.
- **No threshold, recommendation or action field in the output.** The threshold *"belongs to the consumer, who knows their use case — which is why no score is emitted (`ADR-005`)"* (`plan-02-components.md` §13 Track 3). **Never**.
- **No `--format md|html` or `--schema`.** `# TODO: [MVP]` (`plan-02-components.md` §2).
- **No `run.json` shape change.** The manifest's shape and location are Plan 3's (`S3-T07`); this issue emits the per-document result and the chain's intermediates.
- **No stage-set derivation.** The ledger's stage set and `not_applicable` list are derived from the primitive at `S3-T03`; this issue's contribution is that an absent stage is a **fact**, and the list itself is Plan 3's.
- **No golden-set comparison.** `--golden` is `# TODO: [MVP]` and needs a golden set to exist first (`plan-02-components.md` §7d).
- **No adapter import.** **Never** (`sad.md` §1).

**Effort**
**M** — a shape to fix, two directional assertions about `consistency` (one of which is the negative that gets lost), an absence assertion over the whole output, and stability across re-runs; interacting concerns against an emitted-bytes check rather than a heavyweight dependency (`wbs.md` §7).

**Owner**
**Domain** — `docflow/components/contract.py` (`wbs.md` §8).

**Frozen contract touched**
**Freezes** `plans/README.md` §3, Plan 2 row: *the verdict-vector shape and the per-field trace shape (`sad.md` §11, `prd.md` FR-23)* — the row's first item, and the artifact Plan 3 *"emits … unchanged for all 13 (`FR-33`, `S3-T13`)"*. **Consumes** the *`catalog` reason vocabulary* (frozen at `E05-01`) and the Plan 1 row's boundary types and ports. It freezes **nothing** from the Plan 1 row: the components add no new kernel-boundary type.

---

## §4 Epic close condition

E06 is **`done`** when:

1. both issues are `done` — and `E06-02` is not closed by `E06-01` passing, because its criteria are the *shape* and the *absences*;
2. the capability is **demonstrable**, and checked by running it: a ten-page document with one illegible page emits **nine** fields with verdicts and traces, **marks** the tenth, and is **not** discarded; a document with `r`- and `p`-traced fields emits both correctly with `trace.page` and `trace.extractor` on every field; `consistency` is **set** on an `ErpVR` run and **`null`** on a single-read run; and two tests **fail** if a derived score appears or if `consistency: ok` is invented.

**Does E06 gate `S2-T17`?** **Yes, directly.** `S2-T14` is named in `S2-T17`'s dependency set (`wbs.md` §4), making **E06 → E09** a direct inter-epic edge, and `S2-T13`/`S2-T14` are links **7 and 8** of the nine-link longest chain (`plan-02-components.md` §5). It is the last epic before the gate.

**And it is the epic whose output the gate's decisive evidence is read from.** `plan-02-components.md` §3's evidence table is almost entirely about bytes this epic emits, and §7c's scenario *Partial failure marks one page* closes at `S2-T13` and is asserted by `S2-T17`. E06 also opens the two epics the gate does **not** wait on — `E07` and `E08` — which is why Wave 8 contains one gate-dependent and one non-gate task in the same wave.

**Third execution risk, restated because its deadline is this epic's start** (`plan-02-components.md` §9):

> *Slipping `S2-T12` into the gate without deciding it. The `catalog` reason vocabulary (`not_run`) is defined by `S2-T12`, yet `FR-23` obliges the **Contract** (`S2-T13`) to emit a `catalog` verdict with that reason on every field. Building `S2-T13` before the `not_run` value is pinned produces either a missing verdict or an invented one.*

The mitigation the plan chose is a **review deadline**, not a dependency edge: open decision **#1** is reviewed **before `S2-T11` starts** — i.e. one wave before `E06-01` opens, so that this epic begins with the vocabulary already pinned or explicitly deferred. The plan's own recommendation is *"to settle at Wave 7"* — which is this epic's opening wave.

---

## §5 Traceability

| Issue | `wbs.md` task | FR / NFR (`traceability.md` §4) | Gap? | Evidence of the mapping |
|---|---|:---:|---|
| `E06-01` | `S2-T13` | **FR-23** ("Verdict vector per field + trace") · **FR-24** ("Partial failure") · **NFR-07** ("Trace points at the right pixels") | no | AC *Partial failure marks one page*; the barrier release test; heterogeneous-provenance test; `catalog` present with a reason on every field |
| `E06-02` | `S2-T14` | **FR-23** ("Verdict vector per field + trace") | no | Output matches the documented shape; `consistency: null` on single-read runs; no derived score exists |

No issue in E06 has an empty mapping. This is the **richest mapping in Stage 2** — three requirements on one issue, one requirement shared across both — which is the expected shape for the artifact the Plan 2 row freezes: it is where the stage's claims stop being per-component criteria and become **one shape a consumer can read**.

**One attribution to read carefully.** `traceability.md` §4.1 assigns **FR-23** to **three** tasks — `S2-T13`, `S2-T14` **and** `S2-T12` — the widest joint assignment in the plan, and it is the requirement that binds this epic to `E05` without a dependency edge. `NFR-07` is likewise joint (`S2-T09`, `S2-T13`), which is why the inverse-map obligation appears in both epics' issue details rather than being split in half.

---

## §6 Risks

From `plan-02-components.md` §9 only — the rows whose mitigation is carried by this epic:

| Risk | L | I | Why it touches E06 | Mitigation carried by this epic |
|---|:---:|:---:|---|---|
| **Sampled artifact regenerated on resume**, silently changing the result | M | H | The Contract is the **last** place the temptation appears and the first place it would become visible in output: a barrier that waits for a resolved page set is exactly where "just re-read the page" is the cheapest way to unblock. | The barrier **waits**; it does not re-sample. A missing sampled artifact reports `failed` with an evidence-missing reason and is **never regenerated** — carried as an out-of-scope **Never** here, and exercised through a component at §6 step 10 (`E09-01`) |
| **Frontier LLM cost per token during validation** | H | M | Indirect but real: the more verdicts the vector carries, the more each field *appears* to have cost — and the honest answer (six separate members, some of them `null` or `not_run`) is the cheaper one to defend. | The six members are emitted **separately including their absences** — `consistency: null`, `catalog: not_run` — so a field nobody cross-checked is not presented as verified. Scope control itself is `E04-02`'s (contrast scoped to critical fields) |

**Register rows whose *Owner stage* is 2 that do not materialise here, stated rather than implied.** Four of `plan-02-components.md` §9's rows touch other epics: **Docling install/portability**, **`pdftotext` as a poppler binary** and **GPU availability** (`E02`, consumed onward) and **Segmenter merged-document gap** (`E01`). Naming them prevents this epic from reading as risk-free by omission.

**The plan's third named execution risk lands on this epic's opening** (`plan-02-components.md` §9, quoted in §4). Its mitigation is a decision deadline rather than a structural guard, and it is the **only** place in this decomposition where an open decision's resolution would change the epic graph (§3 of the index README states that no `E05 → E09` edge exists today).

**Open decisions carried, not resolved:**

| `plan-02-components.md` §12 | Question | Touches in E06 | Effect if deferred past Stage 2 |
|---:|---|---|---|
| **#1** | **Whether `S2-T12` (Catalog) becomes a dependency of `S2-T17`**, or `not_run` is defined where the Contract can reach it without the Catalog existing | `S2-T13`, `S2-T14` — **both** are among the four tasks the plan names | **Live in this plan, and this epic is where it bites.** *"Building `S2-T13` before pinning `not_run` produces either a missing verdict or an invented one."* Reviewed **before `S2-T11` starts**; *"Recommendation to settle at Wave 7, not at the gate"* — Wave 7 is `E06-01`'s own wave. **Recorded as open, not resolved** |
| **#3** | **What defines a "critical field"** | `S2-T13` (which fields' verdicts are contrast-bearing) and, through it, what the vector's `consistency` member *means* per field | **Load-bearing, reviewed before `S2-T11` starts**; *"an undefined critical-field set means either contrast over everything (expensive) or over a guess (unreliable)"*. It also decides *"what `S3-T04` must ship"*. Carried to Plan 3 §12 if unresolved here |
| **#4** | **Whether OCR correction is inside the OCR step** | Not an E06 issue, but resolving it the other way *"would add a stage to the M2/M3 prefix, i.e. a ledger stage that `S3-T03` would have to derive"* — and the artifact chain this epic's output sits in is derived from the stage set | PoC answer is *"correction is deferred"*, which is consistent and closes the flow. Carried in `E02`'s §6 |
| **#6** | **Whether the Reviewer's cases are aggregated after the run** | Not this epic's, but the emitted result is *"beside … the per-document ledger"* where `03-cli.md` puts the Reviewer's cases | **PoC answer, not a gap:** closure at the per-document level *"is enough for the gate"*. Carried in `E07`'s §6 |

Open decisions **#2** (M0 escalation), **#5** (`r` vs `p` tie-break) and **#7** (`pdftotext` fallback) touch `E03`, `E04` and `E02`; none is resolved here.
