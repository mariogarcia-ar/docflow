# E09 — The Stage 2 gate

| Field | Value |
|---|---|
| Epic ID | **E09** |
| Capability | The Stage 2 closing flow: a **real** document traverses the canonical chain through an `ErpVR` code and emits a verdict vector + trace per field, with the contrast case reproduced end to end |
| Issues | `E09-01` (`S2-T17`) — status `todo` |
| Issue count | **1** |
| Owner layer | **Domain** (`wbs.md` §8) — integration test + documented demo, over `docflow/components/` |
| Wave span | **W9** — the last wave, shared with `E08-01` |
| Effort total | **1 × L** |
| Source plan | [`../../plan-02-components.md`](../../plan-02-components.md) §3 (the closing criterion), §5 (`S2-T17`), §6 (the runbook), §7a/§7c, §8, §9 execution risk 4, §10 Stage DoD, §11, §12 open decision 1 |
| Depends on other epics | **E01** (segmentation) · **E02** (acquisition routing) · **E03** (reconstruction & validity) · **E04** (cross-read consistency) · **E06** (emission) |

---

## §1 Objective

E09 delivers the **gate**: Stage 2 does not exist as *"done"* without it (`wbs.md` §1). Its capability is not a component — it is a **closed flow on real material**: a real document walks `File → Segmenter → Identifier → Diagnosis → Reader → Reconstructor → Validator → Consistency → Catalog → Contract` through an `ErpVR` code, emits a verdict vector with a trace per field, and reproduces the contrast case that no internal check can see.

It is a **separate epic with one issue** because it is a **distinct deliverable class** — the stage's closing criterion, not a capability inside it. `plan-02-components.md` §3 states the criterion and immediately adds the distinction that `traceability.md` §7.3 defect 16 exists to protect: *"'The canonical chain' is the closing criterion, **not the production route.** Stage 2 must build that whole chain because the closing demo walks it."*

**This is the gate where "real" stops being optional.** Plan 1 was allowed to close over faked ports; **this one is not** (`plan-02-components.md` §13, Track 1: *"Plan 1 was allowed to close over faked ports. **This one is not** … Nothing here is stubbed."*). Four external dependencies must be genuinely present: `pdftotext` pinned, Docling installed, an Ollama model pulled with its digest recorded, and a frontier provider key in the environment (`§4` entry condition 4; §13's table names the consequence of each being absent — a missing Ollama model means *"`EpVR` reads do not exist, so **no contrast** — and `ErpVR` is the gate"*).

It is also the **join of five chains**. `S2-T17` is the only task in the plan whose dependency set contains issues from **five** distinct epics (`wbs.md` §6.2), and it is #11 on the PoC's critical path (`wbs.md` §6.1) — Stage 3 does not start until this tick. The gate's chosen primitive is `M1-ErpVR` because **contrast is what the stage exists to prove**, and `M1` because *"a text PDF makes the acquisition path the cheap one — so the run fails for field reasons, not material reasons"* (`plan-02-components.md` §13).

---

## §2 Issues in this epic

| Issue | `wbs.md` task | Title | Wave | Depends on | Effort | PoC markers |
|---|---||---|---|:---:|---|:---:|---|
| `E09-01` | `S2-T17` | **Stage 2 closing flow (real document)** | **W9** | `S2-T03` → **E01** · `S2-T06` → **E02** · `S2-T09` → **E03** · `S2-T11` → **E04** · `S2-T14` → **E06** (all inter-epic) | L | — (**the gate; not deferrable**) |

No intra-epic edges exist: E09 has a single issue. It is the only issue in Stage 2 with **five** distinct inter-epic dependencies — one per branch — and the only one that is **not deferrable** under any marker.

---

## §3 Issue detail

### `E09-01` — implements `S2-T17`

**Title**
**Stage 2 closing flow (real document)**

**Context**
Five claims about Stage 2 are only worth what a demonstrable run can show: that a **real** document walks the canonical chain on **real** adapters; that every field carries six verdicts kept separate and a `(page, extractor)` trace; that the **contrast case** — a total of `15400` that was really `1540`, passing shape, type and content, with no check digit — is caught **only** by a second, differently-failing read, and that arithmetic resolves it where exactly one value closes; that partial failure **marks one page** and emits the rest; and that the Catalog's absence is a **fact with a reason**, not a gap. Each of those is asserted individually by an earlier issue — and none of them is *demonstrated* until they hold **together, in one run, on material nobody arranged to be easy**. This issue is that demonstration. It is the one test whose passing is the gate; every other test in the plan exists to make a failure of this one attributable (`plan-02-components.md` §7a).

**Deliverable**
Integration test + documented demo

**Depends on**
- `S2-T03` — **inter-epic** (E01 → E09) — branch **A**, segmentation, 3 links
- `S2-T06` — **inter-epic** (E02 → E09) — branch **B**, acquisition, 3 links
- `S2-T09` — **inter-epic** (E03 → E09) — branch **C**, reconstruction, 4 links
- `S2-T11` — **inter-epic** (E04 → E09) — branch **D**, contrast, 3 links
- `S2-T14` — **inter-epic** (E06 → E09) — branch **E**, emission, 3 links

The lead time is the **longest** chain, not the sum: **9 links**, `S2-T04 → T05 → T07 → T08 → T10 → T11 → T13 → T14 → S2-T17` (`plan-02-components.md` §5, `wbs.md` §6.2).

**Acceptance criteria**

*The input — steps 1–3*
- [ ] A **real text PDF** is the fixture: one with a text layer that is *"usable but **not** trivially clean"* layout — `documentos/factura.pdf` in the documented command. **Nothing synthetic is accepted for the gate**: Stage 1 already proved the synthetic path (`§6` step 1).
- [ ] A **real image PDF or image** is available for the second reader path, so a single chain can exercise both (`§4` entry condition 7). `# TODO: [MVP]`: replace with the real 3-invoice corpus fixture.
- [ ] The text fixture is **not** a PDF with a stale invisible OCR layer used as the "text" case — that would route to conversion and drag old OCR errors along (`§6` step 1's named wrong result).
- [ ] `pdf classify` on the fixture reads `text`, with `invisible_text: false` and producer metadata consistent — *"quality, not presence"* (`§6` step 2, `FR-15`).
- [ ] The chosen code is **`M1-ErpVR`** (`ADR-003`): `rp`, not `r` and not `p`. The ledger shows `extract.r` **and** `extract.p`, so `consistency` will be set (`§6` step 3).

*The chain, standalone — step 4*
- [ ] The **ten per-component commands** run in order, each reading the previous component's artifact: `.segments.json` → `.identity.json` → `.diagnosis.json` → `.tokens.json` → `.document.json` → `.validated.json` → `.consistency.json` → `.catalog.json` → result.
- [ ] Each step reads the **previous** artifact; **no component re-runs its predecessors**, and no intermediate is named differently on disk than in the docs.

*The flow, as one command — steps 5–6*
- [ ] `docflow run --pipeline M1-ErpVR documentos/factura.pdf --model ollama:qwen2.5 --out out/` exits `0` and produces **one result, one ledger beside it, one `work/` of intermediates**.
- [ ] Every field in `out/<name>.json` carries `value`, `extractor`, `trace` (`page` + `offset` or bbox), and `verdicts` with **all six** members separate: `shape`, `type`, `content`, `digit`, `consistency`, `catalog`.
- [ ] The ledger lists the stages **this pipeline runs** and puts `segmenter`/`identifier`/`reconstructor`/`catalog` in `not_applicable` as **facts**, not as gaps.

*The contrast case — step 7, the gate's own case*
- [ ] The fixture is **the document plus the read**: a document whose `total` is `1540`, arranged so the extraction reads `15400`.
- [ ] `verdicts.consistency` on `total` is **`disagreement`** — not `ok`, and not `null`.
- [ ] **Arithmetic is checked first**: where **exactly one** value closes with `subtotal + taxes`, the case is **resolved without a human**.
- [ ] Where **neither** value closes, the case is routed **to review with all verdicts intact**.
- [ ] `consistency` is **set** on this run *because both reads ran* — and the criterion is stated in both directions, so a single-read `null` cannot be confused with this run's `set` (`§3`'s evidence table).

*Partial failure — step 8*
- [ ] A document with **one illegible page and nine readable ones** emits the **nine** with verdicts and traces, **marks** the illegible one, and **declares the absence**.
- [ ] The document is **not discarded** — *"failure is partial"* (`FR-24`, `plan-02-components.md` §3).
- [ ] The illegible page does **not** reach OCR and return invented text indistinguishable from a real read — the outcome `FR-15` calls invalid.

*The Catalog's absence — step 9*
- [ ] `verdicts.catalog` is present on **every** field, `unverified`, **with a reason**.
- [ ] The reason is **`not_run`** on every field, because no pipeline runs the Catalog in the PoC — and the three reasons (`not_run` \| `source_unavailable` \| `pending_retry`) remain distinguishable.
- [ ] `catalog` is **never absent** and never `unverified` without a reason.

*Interruption and the sampled-artifact invariant — step 10*
- [ ] Killing the run mid-`extract.p` and re-running step 5 reuses `extract.r`'s artifact *"(it is still there and verifies)"*, and **at most one stage per in-flight document re-runs**.
- [ ] A **sampled** `extract.p` artifact that is *missing* reports **`failed`** rather than being re-sampled — *"Plan 1's invariant, now exercised through a domain component"*. **No fresh sample is produced.**
- [ ] The invariant's test **fails** if regeneration occurs: re-sampling the missing artifact and reporting success must turn the suite red.

*No score, anywhere*
- [ ] **No** derived single score exists anywhere in the output: no `confidence`, no aggregate, no contradiction count, no recommendation, no action field (`ADR-005`, `FR-23`).

*Non-deferrable*
- [ ] The flow is reproducible **from a clean checkout** with the documented command, on an `ErpVR` code, with **no stub, no fake and no test double** anywhere on its path.
- [ ] This issue is **not deferrable** and carries **no** `# TODO` marker: it is the gate. The only marked deferrals it inherits are the ones its dependencies declare.
- [ ] Every one of §11's checklist items holds, **including doc-sync**: `prd.md`, `sad.md`, `wbs.md` and `traceability.md` still agree with what was built, and `traceability.md` §5 is re-checked so the stage close produces no orphan task.

**Test / evidence**
- `plan-02-components.md` §7a — the happy-path test that must pass to close the flow: *"`S2-T17`'s integration test, driving a real document through the canonical chain on an `ErpVR` code and asserting: the result matches the documented JSON shape; every field carries all six verdicts and a `(page, extractor)` trace; `consistency` is set (both reads ran); the contrast case reproduces end to end; partial failure marks one page and emits the rest. **This is the gate**; the other tests exist to make a failure of this one attributable."*
- `plan-02-components.md` §3 — the closing criterion (*"a real document traverses the canonical chain and emits a verdict vector + trace, with an `ErpVR` chain demonstrating contrast"*), the two acceptance command blocks (the ten standalone commands, and the single `docflow run --pipeline M1-ErpVR …` command), and the **observable evidence table** — the eight rows this issue must reproduce.
- `plan-02-components.md` §6 — the **eleven-step runbook**; steps 1–3 establish the input, 4–6 walk the chain, 7–9 are the specific claims the gate must prove, 10 is recovery, 11 is the tick. **This issue's acceptance criteria are steps 1–11**, and each step's "wrong result this step guards against" is restated above where it applies.
- `plan-02-components.md` §7c — **the two Gherkin scenarios that close at Stage 2** (`traceability.md` §6):
  | Scenario | Where | Closes at |
  |---|---|---|
  | *The 15400 vs 1540 contrast case* | `prd.md` §8 | `S2-T11`, **asserted end to end by `S2-T17`** |
  | *Partial failure marks one page* | `prd.md` §8 | `S2-T13`, **asserted by `S2-T17`** |
  Both are asserted here, and one of them (`S2-T11`) is the gate's own case.
- `plan-02-components.md` §7c — the **matrix rows the components must not break**, all of which this flow exercises through components rather than only through the lab surface: rows **3** (`S2-T04` routing decision), **7** (`S2-T04` route-aside), **8** (`S2-T09` → `S2-T13` trace), **10** (`S2-T08`/`S2-T14` verdict emission), **11** (`S2-T05` reader path, partial-failure emission) and **12** (`S2-T05`/`S2-T08` on the `p` path — *"contrast must not rescue a truncated read"*). *"These rows still assert at the kernel layer (`S1-T22`); what Stage 2 adds is the proof that the component wiring preserves them."*
- `plan-02-components.md` §8 — the Stage 2 integration test itself. Requirements **FR-21**, **FR-24**, **FR-12** (the demo walks the standalone chain).
- `plan-02-components.md` §13, Track 1 — the four dependencies that must be **real**, and the consequence of each being absent: `pdftotext` (*"A typed `Reason`, never a fallback reader"*), Docling (*"The M2/M3 paths and OCR tokens are unproven"*), Ollama (*"`EpVR` reads do not exist, so **no contrast** — and `ErpVR` is the gate"*), frontier provider (*"The Validator has no governor"*).
- `plan-02-components.md` §10, Stage DoD — *"The real-document flow closes — §3's criterion, run from a clean checkout with the documented command, on an `ErpVR` code"*, and the requirement that the stage's riskiest invariant has *"a test that **fails when the invariant is broken**"*.
- `plan-02-components.md` §11 — the exit checklist, which **is** this issue's close condition: 17 items including the verdict-vector shape, `consistency` set/null, the `catalog` reason on every field, partial failure, over-segmentation and its flag-absence, the stale-invisible-layer routing, Docling only on the OCR path, the four independent checks, the escalation ladder's two cases, normalization, the standalone chain, the `not_applicable` list, no adapter import and no threshold constant, the frozen artefacts named for Plan 3, and **doc-sync**. Plus §13's four tracks, ticked separately.
- `plans/README.md` §2 and §3 — Gate 2 closes *"verdict vector + trace per field, ErpVR contrast reproduced"*, and the Plan 2 frozen row is what this gate **publishes**: the verdict-vector shape and the per-field trace shape, the `catalog` reason vocabulary, the component artifact chain, the escalation policy's single ownership, and the `not_applicable` list.
- `plans/README.md` §4 — *"`S2-T17` and all five of its dependency branches"* are in the **cannot slip** column; only `S2-T15` and `S2-T16` may slip.

**Out of scope for this issue**
- **No synthetic material.** *"Nothing synthetic is accepted for the gate — Stage 1 already proved the synthetic path"* (`§6` step 1). **Never** for this flow.
- **No fake, stub or test double on the path.** `§13` Track 1: *"Plan 1 was allowed to close over faked ports. **This one is not.** … Nothing here is stubbed."* **Never**.
- **No single-read primitive.** Closing on `M1-ErVR`/`M1-EpVR` would *"pass while the one claim Stage 2 exists to prove … was never exercised"* — `ADR-003` fixes `ErpVR` for exactly this reason. **Never** (`§9` risk 4).
- **No `--no-validate`, no `--verify`, no policy flag.** **Never** (`ADR-002`, `ADR-006`, `ADR-009`) — on either surface, in any stage.
- **No derived score.** **Never** (`ADR-005`, `FR-23`).
- **No 13-code coverage.** The stage exercises **one** canonical `ErpVR` code; the thirteen routes are `S3-T02`, and shape identity across them is `S3-T13`. `§7d` states it: *"Stage 3 owns the routes."*
- **No corpus scale, throughput or latency.** *"The first full run sets the baseline"* — `# TODO: [MVP]` (`NFR-11`), and `§7d` excludes it explicitly.
- **No full table reconstruction, no 6 business-rule categories, no live Catalog source, no Reviewer workflow, no `--format`/`--schema`/`--golden`/`--keep-artifacts`/`--isolate`.** All `# TODO: [MVP]` (`§2`, `§7d`).
- **No merged-document detection and no golden-set comparison.** Merged-document detection is **Never**; the golden set is `# TODO: [MVP]` and needs a set to exist first.
- **No Stage 3 work.** The 13 descriptors, `--extractor`, batch, the mirrored tree and `run.json`'s shape are Plan 3's; this issue closes Stage 2 and nothing else.
- **Not deferrable.** This issue carries **no** `# TODO` marker and cannot be moved to a later stage — it **is** the stage close (`wbs.md` §1).

**Effort**
**L** — the widest integration surface in the plan: a ten-command standalone walk, a single-command run, an arranged contrast read, a ten-page partial-failure document, a killed-and-resumed `extract.p`, and the independence of four heavyweight external dependencies — all observed **from outside the process** and reproducible from a clean checkout (`wbs.md` §7).

**Owner**
**Domain** — the integration test and documented demo over `docflow/components/`, which `wbs.md` §8 assigns to the Domain layer. (The **Surface** layer's contribution to this flow is `S1-T18`'s verbs and `S2-T16`'s ten subcommands, delivered by `E08` and **not** a gate dependency.)

**Frozen contract touched**
**Publishes** `plans/README.md` §3, Plan 2 row: the gate is where the whole row — *the verdict-vector shape and the per-field trace shape*, the *`catalog` reason vocabulary*, *the component artifact chain `.<step>.json`*, *the escalation policy's single ownership (Validator)* and *the `not_applicable` list* — becomes frozen and is named in Plan 3's §4. Plan 3 *"wires the 13 codes onto this chain and emits this shape unchanged for all 13 (`FR-33`, `S3-T13`)"*. A change to any item in that row **re-opens this gate** (`plan-02-components.md` §4 entry condition 2, §11's frozen-artefacts item).

---

## §4 Epic close condition

E09 is **`done`** when:

1. `E09-01` is `done`, and
2. the capability is **demonstrable from a clean checkout**: the documented command runs on a real document through `M1-ErpVR` on real adapters; the emitted result carries six separate verdicts and a per-field trace on every field; the contrast case is reproduced end to end and arithmetic breaks the tie where it can; one illegible page of ten is marked while the other nine are emitted; and a missing sampled `extract.p` artifact reports `failed` rather than being re-sampled.

**The epic's close condition *is* the stage's close condition.** `plan-02-components.md` §11's exit checklist is what an operator ticks to declare Plan 2 closed, and **Plan 3's §4 entry condition is that list and nothing else** (`plans/README.md` §2).

**Does E09 gate `S2-T17`?** It **is** `S2-T17`. There is no epic above it inside Stage 2, and the gate it gates is the next plan's entry — **Gate 2** in `plans/README.md` §2, whose close is *"verdict vector + trace per field, ErpVR contrast reproduced"*.

**The five branches and what may slip** (`plans/README.md` §4, `wbs.md` §6.2, `plan-02-components.md` §5):

| Branch | Chain | Links | Head | May slip past the close? |
|---|---|:---:|---|:---:|
| **A — segmentation** | `S2-T01 → T02 → T03` | 3 | `E01-03` | **No** — `S2-T03` is in the gate's dependency set |
| **B — acquisition** | `S2-T04 → T05 → T06` | 3 | `E02-03` | **No** — `S2-T06` is in it |
| **C — reconstruction** | `S2-T05 → T07 → T08 → T09` | 4 | `E03-03` | **No** — `S2-T09` is in it |
| **D — contrast** | `S2-T08 → T10 → T11` | 3 | `E04-02` | **No** — `S2-T11` is in it, and it is the gate's own case |
| **E — emission** | `S2-T11 → T13 → T14` | 3 | `E06-02` | **No** — `S2-T14` is in it |
| *(none)* | `S2-T15` (Reviewer) | — | `E07-01` | **Yes** — not in the dependency set (`wbs.md` §6.2) |
| *(none)* | `S2-T16` (per-component CLI) | — | `E08-01` | **Yes** — not in the dependency set (`wbs.md` §6.2) |

**Two conditions must hold for this epic to close legitimately, and both are risks rather than dependencies:**

| Condition | Why | Where enforced |
|---|---|---|
| **The Catalog's reason vocabulary is pinned before `S2-T13` was built** | `FR-23` obliges the Contract to emit `catalog` with the reason `not_run` on every field, and that value is `S2-T12`'s to define — yet no dependency edge records the obligation. Building `S2-T13` first yields *"either a missing verdict or an invented one"* | `plan-02-components.md` §9 risk 3; §12 open decision **#1**, reviewed **before `S2-T11` starts**. If it resolved toward a dependency, the epic graph would gain `E05 → E09` — stated in the index README §9 and in `E05`'s §6 |
| **The closing primitive is `ErpVR`, not `ErVR` or `EpVR`** | `ErVR`/`EpVR` traverse the chain and emit a defensible shape **with `consistency: null` everywhere** — the gate would pass while the one claim Stage 2 exists to prove was never exercised | `plan-02-components.md` §9 risk 4; `ADR-003`; §6 step 3's named wrong result; and this issue's acceptance criteria, which assert `set` **and** `null` in both directions |

The wave map is not a preference: **Waves 5 through 9 exist so that the five branches converge here with all five complete** (`plan-02-components.md` §5). W4 — one task, `S2-T08` — is the wave that makes the convergence possible, because branches C, D and E all pass through it.

---

## §5 Traceability

| Issue | `wbs.md` task | FR / NFR (`traceability.md` §4) | Gap? | Evidence of the mapping |
|---|---|:---:|---|
| `E09-01` | `S2-T17` | **FR-21** ("Contrast across extractors") · **FR-24** ("Partial failure") · **FR-12** ("10 components standalone via CLI" — **the demo walks the standalone chain**) | no | The Stage 2 integration test itself |

No gap. `E09-01` carries one of the **richest** mappings in Stage 2 — three requirements, all of them single-task elsewhere and re-asserted here — which is the expected shape for a closing criterion: it is where the plan's claims stop being per-task criteria and become **one observable flow**.

The reverse check (`traceability.md` §5) names this task explicitly: *"`S2-T16`, `S2-T17` → FR-12, FR-21, FR-24 — the per-component surface and the Stage 2 close"*. Two tasks, three requirements, both halves of the pair required — which is why `FR-12` is satisfied **twice** in Stage 2 (the surface exists at `S2-T16`, the gate exercises it at `S2-T17`) and neither task alone closes it.

**The two acceptance scenarios and their Stage 2 attribution** (`plan-02-components.md` §7c, `traceability.md` §6) — *"Two of the six Gherkin scenarios close at Stage 2"*:

| Scenario | Closes at | This issue's part |
|---|---|---|
| *The 15400 vs 1540 contrast case* | `S2-T11` | **asserted end to end here** — and it is the gate's own case |
| *Partial failure marks one page* | `S2-T13` | **asserted here** — the ten-page, one-illegible fixture |

The other four scenarios close elsewhere: three at Stage 1 (`S1-T19`, `S1-T08`/`S1-T22`, `S1-T10`) and one at Stage 3.

**One attribution to read carefully.** `S2-T17` is the **assertion** site for both scenarios and the **owner** of neither: `S2-T11` produces the disagreement verdict and `S2-T13` produces the partial emission. The gate reproduces them, which is why `plan-02-components.md` §7c's table has a "Closes at" column and a separate sentence naming `S2-T17` as the assertion — the same split `traceability.md` §4.1 encodes when it gives a requirement one task for the proof and another for the behaviour.

---

## §6 Risks

From `plan-02-components.md` §9 only — the rows whose mitigation is carried by this epic:

| Risk | L | I | Why it touches E09 | Mitigation carried by this epic |
|---|:---:|:---:|---|---|
| **Sampled artifact regenerated on resume**, silently changing the result | M | H | Step 10 is where the invariant is *"exercised through a component"* for the first time, and where a failure is finally visible as **output**: a missing `extract.p` re-sampled *"chang[es] the result while reporting success"*. | An acceptance criterion requires that a missing sampled `extract.p` artifact reports **`failed`** rather than being re-sampled, that `extract.r`'s artifact is **reused**, and that the test **`fails` if regeneration occurs**. §6 step 10's named wrong result is exactly this case |
| **Frontier LLM cost per token during validation** | H | M | The closing run spends real tokens: `M1-ErpVR` runs the `p` path over a real document on a real provider. | The cost mitigation is `E04-02`'s (contrast scoped to critical fields, policy-driven); what this issue adds is the **honest accounting**: six separate verdicts with their absences emitted (`consistency: null`, `catalog: not_run`) rather than a score that hides what was and was not paid for |

**The plan's fourth named execution risk is *about* this issue** (`plan-02-components.md` §9):

> *Closing the gate on a single-read primitive. `M1-ErVR`/`M1-EpVR` traverse the chain and emit a defensible shape — with `consistency: null` everywhere. The gate would pass while the one claim Stage 2 exists to prove (contrast detects the plausible-but-false value) was never exercised. ADR-003 fixes `ErpVR` as the closing primitive for exactly this reason.*

The mitigation is structural and is drawn in the acceptance criteria: the chosen code is `M1-ErpVR`, §6 step 3's wrong result is named, and the `consistency` criterion is written in **both** directions — `set` on this run and `null` on a single-read run — so that a run which never exercised contrast cannot pass by looking correct.

**The plan's first and second execution risks reach this epic as ready-or-not conditions** even though they land on other epics: **branch A built late** (`E01`) would leave the gate waiting on a three-link chain available since Wave 1, and **`S2-T08` deferred** (`E03`) would block three branches at once. Both are structural facts about *when* the gate can close, stated here because this is the issue that closes it.

**Register rows whose *Owner stage* is 2 that do not materialise here, stated rather than implied.** Three of `plan-02-components.md` §9's rows touch other epics and reach this flow only as prerequisites: **Docling install/portability**, **`pdftotext` as a poppler binary** and **GPU availability for local models** — all `E02`'s mitigation, all named in §13 Track 1's consequence table for this flow. **Segmenter merged-document gap** (`E01`) is a residual accepted risk that this gate does **not** close and must not claim to. Naming them prevents this epic from reading as risk-free by omission.

**Two conditions named as risks rather than dependencies** (restated from §4 because they are this file's most valuable content):

| `plan-02-components.md` §9 | Condition | Enforced at |
|---|---|---|
| Risk 3 | The Catalog's `not_run` value pinned before `S2-T13` was built — no dependency edge records it | §12 open decision **#1**, reviewed before `S2-T11` starts; carried in `E05`'s §6 and `E06`'s §6 |
| Risk 4 | The closing primitive is `ErpVR` on real adapters, not a single-read code and not a stub | `ADR-003`, §6 step 3, and this issue's both-directions `consistency` criterion |

**Open decisions carried, not resolved:**

| `plan-02-components.md` §12 | Question | Effect on what this issue can show |
|---:|---|---|
| **#1** | Whether `S2-T12` (Catalog) becomes a dependency of `S2-T17`, or `not_run` is defined where the Contract can reach it | The gate emits a `catalog` verdict with a reason on **every** field either way — but *which epic owns that value* changes, and so does the dependency table `wbs.md` §6.2 is derived from. §6 step 9 asserts `not_run` **today**; a resolution toward the dependency would move `E05` onto the critical path **without changing this issue's criteria**. Recorded as open, not resolved |
| **#2** | What M0's targeted escalation means | Not shown by this flow: the closing code is `M1-ErpVR`, and `M0-*` is three of the thirteen codes, all Plan 3's. `traceability.md` §7.2 calls it *"the one item that should be settled before Stage 2"*; this issue neither depends on it nor demonstrates it |
| **#3** | What defines a "critical field" | Constrains the **scope** of the contrast this issue reproduces: an undefined set means *"either contrast over everything (expensive) or over a guess (unreliable)"*. The gate reproduces the case on `total`; the set itself is policy data (`S3-T04`) |
| **#4** | Whether OCR correction is inside the OCR step | The PoC answer (*"correction is deferred"*) is what makes the chain's stage set stable. Resolving the other way *"would add a stage to the M2/M3 prefix, i.e. a ledger stage that `S3-T03` would have to derive"*, which would change the Plan 2 frozen row this gate publishes |
| **#5** | What decides `r` vs `p` inside `ErpVR` when both run and disagree | This issue **reproduces the documented rule**: arithmetic breaks the tie where it can, and a disagreement with no arithmetic relation **routes to review** — *"which is a correct terminal state, not a gap"*. The Consistency-arbiter role has no definition and is **not** defined here |
| **#6** | Whether the Reviewer's cases are aggregated after the run | Not shown: `S2-T15` is **not** a gate dependency and is not exercised by this flow. Per-document cases — visible in the ledger and the emitted result — are what the gate observes |
| **#7** | Whether `pdftotext`'s dependency needs a stated fallback | **Resolved by refusal** for the PoC, and the refusal is a condition of this flow: a missing `pdftotext` is a typed `Reason` and never a fallback reader. What is *not* settled is *"the question of an operator-facing remedy message"* — so the gate's behaviour is fixed and its wording is not |
