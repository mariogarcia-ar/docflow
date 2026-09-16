# E08 — The Stage 3 gate (corpus)

| Field | Value |
|---|---|
| Epic ID | **E08** |
| Capability | The Stage 3 closing flow (corpus) — all 13 codes reachable, every document a result or a **declared** partial failure, the first full run completed and interrupted-and-resumed successfully, and the baseline throughput **recorded with no target asserted** |
| Issues | `E08-01` (`S3-T14`) — status `todo` |
| Issue count | **1** |
| Owner layer | **Data** + **Surface** (`wbs.md` §8) — the gate is an integration test plus a baseline report over both layers' artefacts |
| Wave span | **W7** — the last wave |
| Effort total | **1 × L** |
| Source plan | [`../../plan-03-pipelines.md`](../../plan-03-pipelines.md) §1, §3 (the closing criterion, the acceptance commands, the evidence table), §5 (`S3-T14`), §6 (the runbook, steps 1–16), §7a–§7d, §8, §9 (all three execution risks), §10 (Stage DoD), §11 (the exit checklist), §13 Track 1 |
| Depends on other epics | **E02** (`S3-T04`, `S3-T12` — two edges) · **E05** (`S3-T05`) · **E06** (`S3-T09`) · **E07** (`S3-T13`) |

---

## §1 Objective

E08 delivers the **gate**: Stage 3 does not exist as *"done"* without it, and neither does the PoC. Its capability is not a component and not a feature — it is a **closed flow at the scale the problem actually has**: `docflow run --pipeline M1-ErpVR documentos/ --out out/ --jobs 8` over **eleven thousand documents**, mirroring the tree, interrupted mid-run and resumed with the same command, with every document producing a result or a **declared** partial failure and the baseline throughput recorded.

It is a **separate epic with one issue** because it is a **distinct deliverable class** — the stage's closing criterion, not a capability inside it (`plan-03-pipelines.md` §3; `wbs.md` §1: *"a stage is `done` only when its flow closes"*). Everything else in Stage 3 is built behind the descriptors and the layout; this issue is the demonstration that they hold **together, across a kill, at 11k files**. It is also the plan's **join**: `S3-T14` is the only task in the plan whose dependency set contains issues from **four** different epics (E02 twice, E05, E06, E07), and it is #15 — the last link — on the PoC's critical path (`wbs.md` §6.1).

**The flow is the corpus on purpose, and only the last of three rungs.** `plan-03-pipelines.md` §13 sequences Track 1 as: one file per code (13 commands), then a small folder with **nested and empty** subdirectories, then the corpus interrupted and resumed. Only rung 3 is the gate, and *"the corpus is not what teaches you the pipeline is wrong — a small folder is."* **Rung 3 is where the deferrals get charged**, and faking is not available at this layer: `--jobs 8` over 11k files is the only thing that exercises the slot model, and the first full run is the only thing that produces a baseline (`NFR-11` — recorded, **no target asserted**).

---

## §2 Issues in this epic

| Issue | `wbs.md` task | Title | Wave | Depends on | Effort | PoC markers |
|---|---||---|---|:---:|---|:---:|---|
| `E08-01` | `S3-T14` | **Stage 3 closing flow (corpus)** | **W7** | `S3-T04` → **E02** · `S3-T05` → **E05** · `S3-T09` → **E06** · `S3-T12` → **E02** · `S3-T13` → **E07** (all inter-epic — **five** predecessors, **four** distinct epics) | L | `# TODO: [MVP]`: latency and throughput targets |

No intra-epic edges exist: E08 is a single-issue epic. It is the only issue in the plan with **five** predecessors, and the only one whose dependencies span four different epics. It is also one of only four tasks in the plan with **no external entry edge** — every one of its dependencies is a Stage 3 task, which is why the gate is reachable entirely from inside the stage once Plan 1 and Plan 2 have closed (index README §3).

---

## §3 Issue detail

### `E08-01` — implements `S3-T14`

**Title**
**Stage 3 closing flow (corpus)**

**Context**
Four claims about the system are only worth what an operator can observe at scale: that all 13 codes are reachable; that every document in a corpus of 11k produces a result or a **declared** partial failure rather than a silent absence; that a run of that size can be interrupted and resumed without repeating completed work; and that the system's performance is stated as a **recorded baseline** rather than a claim. Each is asserted individually by an earlier issue — and none is *demonstrated* until they hold **together, over the real corpus, across a kill**. This issue is that demonstration. It is the one test whose passing is the stage gate; every other test in the plan exists to make a failure of this one attributable (`plan-03-pipelines.md` §7a).

Two properties of the gate deserve to be stated in its own words. **It is the PoC's last gate** — §11's checklist closes not only Plan 3 but the whole PoC. And it is where the **merged-document limitation** is finally asserted as *declared, not hidden*: `prd.md` §8's scenario belongs to this stage *"because it is a statement about what a *pipeline* run over the corpus does and does not close"* — and the honest position is that no pipeline closes it.

**Deliverable**
First full run + report.

**Depends on**
- `S3-T04` — **inter-epic** (E02 → E08): the registry assets, including the critical-field policy that scopes contrast.
- `S3-T12` — **inter-epic** (E02 → E08): the policy/setting boundary. Without it the run's output was produced under settings that never entered the registry hash.
- `S3-T05` — **inter-epic** (E05 → E08): the material selector, because the corpus's material mix is not uniform.
- `S3-T09` — **inter-epic** (E06 → E08): resume at corpus scale, which the gate's acceptance test exercises by interrupting the run.
- `S3-T13` — **inter-epic** (E07 → E08): shape identity — a **precondition** of this issue, not a sibling of it (`plan-03-pipelines.md` §9).

**Acceptance criteria**

*The corpus flow — `plan-03-pipelines.md` §3, §6 steps 5–6, 15*
- [ ] All **13 codes are reachable** — the 13 single-file commands from §3 step 2 each exit `0`, **before** the corpus run is spent.
- [ ] The input tree is **measured before it is walked**: the document count and the directory count, **including empty ones**, are documented and are the numbers `run.json` is later checked against.
- [ ] The first full run starts as `docflow run --pipeline M1-ErpVR documentos/ --out out/ --jobs 8` and reports a job id.
- [ ] `run.json` appears early with `state: running`, `totals.discovered` matching the measured count, `stages` counters advancing and `inflight` populated.
- [ ] The run completes with `state: finished`, and **every document produces a result or a declared partial failure** — no silent absence (`FR-24`, `NFR-01`).
- [ ] `to_review`, `escalated` and `partial` counts are recorded in `outcomes`.
- [ ] The **baseline throughput is recorded** — wall time and per-stage timings — with **no target asserted** against it (`NFR-11`).

*Interruption and resume — §6 steps 8–9, §11*
- [ ] `docflow stop --force` mid-corpus reports the runs, distinguishes a finishing run from an active one, and reports how many documents were left in flight.
- [ ] Every interrupted stage reads **`running`** in its ledger.
- [ ] Re-running step 6 **verbatim** — **no `resume` verb** — completes the corpus.
- [ ] The in-flight document resumes from its **exact stage**, re-running **at most that one stage**.
- [ ] Completed documents are skipped **without re-reading**.

*The tree, the suffixes and the manifest — §6 steps 10–11, 13*
- [ ] `documentos/2024/enero/factura-001.pdf` → `out/2024/enero/factura-001.json`, and a structural diff of the input tree against `out/` reports no difference, **empty directories included**.
- [ ] `find out -name '*.json' ! -name '*.ledger.json'` returns every result, no ledger, and excludes every `<name>.work/`.
- [ ] `rm out/run.json` followed by the **library** rebuild reproduces it from the ledger tree alone; a hand-deleted artefact reads back as incomplete **with no flag passed**.

*The 13 shapes side by side — §6 step 14, §7a*
- [ ] One document per code, compared side by side: one field set, one verdict set, one trace shape across all 13.
- [ ] `consistency` is non-null **exactly** on the four `ErpVR` codes; `catalog` is present with a reason on every field of every code.
- [ ] A green shape-identity test is treated as a **precondition** of this issue, not as a substitute for it (`plan-03-pipelines.md` §7a).

*The declared limitation — `prd.md` §8, `plan-03-pipelines.md` §3, §7d*
- [ ] The merged-document limitation is **asserted as declared, never claimed solved**: the output is shape-valid with every field carrying its verdicts, and the limitation remains declared in `README.md`, `prd.md` and `wbs.md` §10.
- [ ] No part of this issue's report claims merged-document detection.

*Non-deferrable*
- [ ] The flow is reproducible **from a clean checkout** with the documented command, and the riskiest invariant introduced at this stage has a test that **fails when the invariant is broken** — reprocessing a stage invalidates everything downstream, and completed work is never repeated on resume (`plan-03-pipelines.md` §10, Stage DoD).
- [ ] This issue is **not deferrable**: it is the gate, and the only marker it carries is the one on the *targets* it must not assert.

**Test / evidence**
- `plan-03-pipelines.md` §3 — **the closing criterion**: *"all 13 codes are reachable and produce shape-identical output; a batch over the corpus runs, mirrors the tree, and resumes after an interruption"* (`wbs.md` §5). Plus the acceptance commands (all five blocks) and the twelve-row **observable evidence** table: the 13 codes; output shape across the 13; `consistency` across the 13; `catalog` across the 13; the mirrored tree; the three artefacts by suffix; `run.json`; the ledger after interruption at ~4,821 of 11,034; a forced `extract.p`; the ledger stage set per code; `.env.example`; and baseline throughput. Every row names *"the wrong result it guards against"*.
- `plan-03-pipelines.md` §5 row `S3-T14` — the verifiable criterion: *"All 13 codes are reachable; every document produces a result or a declared partial failure; the first full run over the corpus completes and is interrupted and resumed successfully; the baseline throughput is recorded."*
- `plan-03-pipelines.md` §6 — the **16-step runbook**. Steps 1–5 are the pre-run checks (*"the corpus run is the point of no return for the plan"*), 6–15 are the flow including the interruption and the manifest proof, and step 16 is ticking §11. **This issue's acceptance criteria are steps 5–15**, and each names the wrong result it guards against.
- `plan-03-pipelines.md` §7a — the happy-path test that must pass to close the flow: *"The batch is the test — the corpus is the fixture, and a green `S3-T13` shape-identity contract test is a precondition of it, not a substitute."*
- `plan-03-pipelines.md` §7c — the acceptance scenario that closes at Stage 3: *"The merged-document limitation is declared, not hidden"* (`prd.md` §8), closing at **`S3-T13`** (shape-valid across the 13) **and `S3-T14`** (the corpus run), with *"the declaration itself … `wbs.md` §10 and `prd.md` §10."* Plus the four `kernel-cli.md` §11 rows Stage 3 must not break **at corpus scale**: **row 1** (a killed stage reported as never started, then resumed — *over 11k documents rather than a synthetic unit set*); **row 4** (a 150 DPI scan rendered at 300 and reported as 300 — the M2/M3 codes over real scans); **row 11** (a truncated page read as a page with no text — the document's partial failure must be declared, not dropped); **row 16** (a manifest reporting a finished run that is not finished — *at corpus scale where the drift would be invisible in a count*).
- `plan-03-pipelines.md` §7d — what is explicitly **not** tested at this stage, each with its marker: golden-set comparison (`# TODO: [MVP]`); latency/throughput/availability targets (`# TODO: [MVP]`, `NFR-11`); symlink and permission edge cases (`# TODO: [MVP]`); merged-document detection (**Never** — asserted as *declared*); distributed execution, object storage, HA, multi-region, telemetry (`# TODO: [RELEASE]`); the 6 Validator business-rule categories (`# TODO: [MVP]`); a live Catalog source at corpus scale (`# TODO: [MVP]`).
- `plan-03-pipelines.md` §8 — *"**NFR-01**, **NFR-11**, **FR-24** (declared partial failures at corpus scale)"*, proof *"The first full run: all 13 reachable, every document a result or a declared partial failure, interrupt + resume, baseline recorded."*
- `plan-03-pipelines.md` §10, **Stage DoD (Plan 3)** — every one of the 14 tasks `done`; the corpus flow closes from a clean checkout with the documented command; the stage's riskiest invariant has a test that **fails when broken**; and `prd.md`/`sad.md`/`wbs.md`/`traceability.md` still agree with what was built, *"in particular `sad.md` §8's 13-code matrix and `§11`'s output shape must match what the 13 codes emit, and `wbs.md` §6.2's dependency table must match the dependencies that actually gated the close."*
- `plan-03-pipelines.md` §11 — the **exit checklist**, which closes the PoC. Its items are this issue's acceptance criteria plus the stage DoD and the doc-sync item; §11 also ticks the **four tracks separately** (Track 1's three rungs; Track 2's shape identity, error cases and recorded baseline; Track 3's *"the layer added **no code**"*; Track 4's *"no `resume` verb"*).
- `plan-03-pipelines.md` §13, Track 1 — the gate is rung 3: *"The corpus, interrupted mid-run and resumed — scale: slots, disk, per-document resume"* — and *"Rung 3 is where the deferrals get charged."*
- `wbs.md` §6.1 — `S3-T14` is **#15, the last link** on the critical path: *"The PoC's ultimate target."*
- `plans/README.md` §2 — Gate 3: *"corpus closes"* → *"13 codes reachable, tree mirrored, interruption resumed"* → **PoC closed**. And §6: *"Plan 3's Track 2 can start while Plan 2's Track 4 is still filling in … no lane crosses a gate ahead of its own layer's Track 1."*

**Out of scope for this issue**
- **Latency, throughput and availability targets.** The first full run **sets** the baseline; no target is asserted against a baseline that does not exist yet (`NFR-11`). `# TODO: [MVP]`.
- **Golden-set comparison and pipeline-vs-pipeline scoring.** Needs a golden set to exist first; `--golden` is deferred and the labeller role with it. `# TODO: [MVP]` (`traceability.md` §3.4 **D4**).
- **Symlink, permission and exotic-path edge cases** in the mirrored tree. Declared PoC limitation. `# TODO: [MVP]`.
- **Merged-document detection.** No pipeline closes it. **Never** — asserted as *declared*, not as solved.
- **Attribute-and-merge.** Merging is what defeats contrast; over-segmenting is the accepted alternative. **Never**.
- **A `resume` verb or a `--resume` flag.** Resume is the same `run` (`FR-01`). **Never**.
- **A `--verify` flag or a ledger-trust `verify` subcommand.** Verification is an outcome of every ledger read. **Never** (`ADR-006`).
- **A `--no-validate` flag.** `V` is invariant in all 13 pipelines. **Never** (`ADR-002`, `prd.md` FR-18).
- **A single confidence score.** The output is a per-field verdict vector plus trace. **Never** (ADR-005, `prd.md` FR-23).
- **A per-corpus OCR engine choice, and any default or fallback model, engine or threshold.** **Never** (ADR-001, `prd.md` §10).
- **A corpus policy value settable from a flag or the environment.** `.env.example` names the five only to say they cannot be set. **Never** (ADR-009, `NFR-06a`).
- **Distributed execution, object storage, HA, multi-region, telemetry and dashboards.** `# TODO: [RELEASE]`.
- **The 6 Validator business-rule categories.** Deferred from Plan 2. `# TODO: [MVP]`.
- **A live Catalog source.** No pipeline runs the Catalog; every field reads `not_run`. `# TODO: [MVP]`.
- **Deleting or regenerating a document's failed artefact to make the corpus "complete".** A declared partial failure is a result; a missing sampled artefact is `failed`, never a fresh sample (`prd.md` FR-09). **Never**.
- **Whether a sampled artefact may ever be regenerated with the new observation recorded.** Carried **open** (`plan-03-pipelines.md` §12 **#5**, touching `S3-T09` and `S3-T14`), with the PoC answer **never** — and this gate is where the omission would become a corpus-wide consequence.
- **Whether the 17-row suite runs at all stages, and whether it is split.** Carried **open** (`plan-03-pipelines.md` §12 **#8**, touching this issue indirectly): an unsplit suite makes CI flaky, *"and a flaky gate is ignored."* The corpus run is where this costs most, *"because it is the stage where a red CI would be blamed on scale rather than on the kernel."*

**Effort**
**L** — the widest integration surface in the plan: 11k documents, three Track 1 rungs, five inter-epic predecessors, a deliberate interruption and resume, a structural tree diff, a manifest rebuild, a 13-shape comparison and a recorded baseline — all observed **from outside the process**, reproducible from a clean checkout, over a corpus rather than a fixture (`wbs.md` §7: *"a load-bearing invariant or a heavyweight external dependency; needs an integration or crash-injection test"*).

**Owner**
**Data** + **Surface** — the gate is an integration test plus a baseline report over both layers' artefacts (`wbs.md` §8). `wbs.md` §8's owner column enumerates `S3-T01`–`S3-T04`, `S3-T13` (Data) and `S3-T05`–`S3-T12` (Surface) and **does not enumerate `S3-T14`**; the gate crosses both layers by construction, and that is stated here rather than assigned to one of them.

**Frozen contract touched**
**Publishes** the whole of `plans/README.md` §3, Plan 3 row: *"The 13 descriptors and their stage sets; the registry assets (patterns, prompts, schemas, policies); `.env.example` and the policy/setting split; the mirrored-tree and the three-artifact layout; `run.json`'s shape and location"* — *"Nothing follows in the PoC. A shape change here is a shape change for the consuming system."* **Consumes** the Plan 1 row (boundary types, ports, the 7-term cache key, the 7 durable states, the determinism classes, the exit codes) and the Plan 2 row (the verdict-vector and trace shapes, the `catalog` reason vocabulary, the component artefact chain, the escalation policy's single ownership) — and asserts that **neither changed**, which is the stage DoD's whole content: *"no new kernel, no new component, no new kernel-boundary type: this stage adds configuration and data."*

---

## §4 Epic close condition

E08 is **`done`** when:

1. `E08-01` is `done`, and
2. the capability is **demonstrable from a clean checkout**: the corpus run closes with every document a result or a declared partial failure; the run is interrupted mid-corpus and resumed with the same command, skipping completed documents without re-reading; the tree is structurally identical including empty directories; the manifest is rebuilt from the ledgers alone after deletion; the 13 shapes compare equal; and the baseline is recorded with **no target asserted**.
3. **Plan 3 DoD, per epic:** no new kernel, no new component, no new kernel-boundary type — this stage adds configuration and data (`plan-03-pipelines.md` §10, Task DoD).

**The epic's close condition *is* the stage's close condition.** `plan-03-pipelines.md` §11's exit checklist is what an operator ticks to declare Plan 3 — and the PoC — closed. It is the last gate in the set: `plans/README.md` §2's Gate 3, *"corpus closes"*, whose passage is *"13 codes reachable, tree mirrored, interruption resumed"* → **PoC closed**.

**Does E08 gate `S3-T14`?** It **is** `S3-T14`. There is no epic above it inside Stage 3.

**E08 is the join, and the arithmetic is worth restating at the gate.** Its five predecessors span **five** inter-epic edges from **four** distinct epics — E02 twice (`S3-T04`, `S3-T12`), E05 (`S3-T05`), E06 (`S3-T09`), E07 (`S3-T13`). E01 and E03 reach it only transitively, and that asymmetry has an operational reading: **the two direct edges that look cheapest carry the two failures nothing else catches.** `S3-T12` is `S` effort and prevents a corpus whose `done` claims were produced under settings nothing recorded; `S3-T13` is `M` effort and prevents 13 codes that all work and are not substitutable. Both are named as plan-specific execution risks (§9 ways 1 and 3), and both would pass the gate's other checks if omitted.

**Three conditions must hold for this epic to close legitimately, and all three are risks rather than dependencies:**

| Condition | Why | Where enforced |
|---|---|---|
| `E02-02` (`S3-T12`) is `done` **before** the corpus run starts | Otherwise the run's output was produced under settings that never entered the registry hash, so every ledger's `done` is a claim nobody can check — and the results are neither reproducible nor precisely invalidatable | `plan-03-pipelines.md` §9 execution risk 1; §6 step 3 (a pre-run check); E02's close condition |
| `E06-01` (`S3-T08`) is `done` and `E06-02` proves the resume | Otherwise a forced `extract.p` leaves verdicts describing previous values — at 11k, a corpus that looks complete and is inconsistent, with every stage `done` and every artifact verifying | `plan-03-pipelines.md` §9 execution risk 2; §5 Wave 6 (*"the two share the same ledger claims"*); E06's close condition |
| `E07-01` (`S3-T13`) is `done` from the start | All 13 can be reachable while emitting subtly different shapes — invisible until a consumer writes their second integration, and precisely `FR-33`'s subject | `plan-03-pipelines.md` §9 execution risk 3; §7a (*"a precondition … not a substitute"*); §3's acceptance-commands step 2 |

The wave map is not a preference: **Waves 1–6 exist so that W7 opens with all five predecessors complete** (`plan-03-pipelines.md` §5). And one further condition is not a dependency at all but a discipline: `S3-T14` is **not deferrable**, carries no marker on the flow itself, and the only `# TODO: [MVP]` attached to it is on the targets it must not assert.

---

## §5 Traceability

| Issue | FR / NFR (`traceability.md` §4) | Gap? | Evidence of the mapping |
|---|---|:---:|---|
| `E08-01` | **NFR-01** (11k files, one command, survives interruption), **NFR-11** (no latency targets in the PoC; the first run sets the baseline), **FR-24** (declared partial failure at corpus scale) | no | The first full run: all 13 reachable, every document a result or a declared partial failure, interrupt + resume, baseline recorded |

No gap and no orphan. `traceability.md` §5 places `S3-T14` alone under *"NFR-01, NFR-11 — the corpus close"*, and §4.1 carries **FR-24** at stage 2 with task `S2-T13` — this issue is where that requirement is exercised at corpus scale, which is why the plan groups it here. The Plan 3-specific fact, restated: **no gap and no orphan task** at this stage; the one deliberately uncovered requirement is `NFR-12` (deployment), which `traceability.md` §7.1 records as having no task by design (`# TODO: [RELEASE]`), and which this gate does **not** fill — §11's doc-sync item re-checks §5 *"so the PoC close produces no orphan task and no requirement with no task beyond the ones `§7.1` already declares."*

**Open decisions this epic carries, unresolved.** Four of the ten touch the gate, and the gate is where each would become visible at scale:

| `plan-03-pipelines.md` §12 | Question | Why it lands on E08 |
|---:|---|---|
| **#5** | Whether a sampled artefact may ever be regenerated, with the new observation recorded | The PoC answer is **never regenerate** — missing evidence → `failed`. At corpus scale the consequence is concrete: a lost OCR or model artefact makes that document permanently unreproducible within the run, and the operator's remedy is a re-run with a new observation, which the PoC does not express as a first-class outcome. The gate's *"every document produces a result or a declared partial failure"* is what makes the consequence auditable |
| **#8** | Whether the 17-row silent-failure suite runs at all stages or only at Stage 1, and whether it is split | Touches this issue **indirectly**: *"an unsplit suite makes CI flaky, and a flaky gate is ignored."* The corpus run is where a flaky suite costs most, *"because it is the stage where a red CI would be blamed on scale rather than on the kernel"* |
| **#6** | What is in the per-document cost ceiling | The gate is the first run whose `CallRecord` data would let a ceiling be set. Without one, escalation decides how much a document may cost and `--only failed` re-runs are unbounded in the same way — *"which is the honest PoC position"* |
| **#1**, **#2**, **#3** | Critical field · M0 escalation · whether the Catalog is a dependency of `S2-T17` | Each reaches the gate through E01, E02 and E07. #2 in particular is the one `traceability.md` §7.2 recommends settling before Stage 2, and its arrival here would invalidate the shape-identity test rather than one pipeline |

None of the ten is resolved anywhere in this directory.

---

## §6 Risks

From `plan-03-pipelines.md` §9 only, keeping the rows that name `S3-T14`:

| Risk | L | I | Why it touches E08 | Mitigation carried by this epic |
|---|:---:|:---:|---|---|
| **The 11k-file scale on the first full run** — disk, memory for full-page bitmaps, wall time | H | H | The gate **is** the first full run. The register names it as the plan's defining risk, and its mitigation lands here as the flow itself. | Stage 1 proved resume on a synthetic flow; slot and disk policy settled at `S3-T11` **before** the corpus run; **the first run is interruptible by design** — which the acceptance criteria make observable rather than assumed |
| **Frontier LLM cost per token during validation** | H | M | The corpus run is where contrast is paid 11k times, and the cost is scoped by the critical-field policy (`S3-T04`) the gate consumes. | Contrast scoped to critical fields only (registry policy); `count_tokens` before spending; the circuit breaker degrades to `unverified`, never to rejection; `# TODO: [MVP]` a per-document cost ceiling — carried here as §12 **#6**, unresolved |
| **Segmenter merged-document gap that no pipeline closes** | M | H | The Stage 3 acceptance scenario closes here: a file holding three logical documents, output that is **shape-valid with every field carrying its verdicts**, and *"the merged-document limitation remains declared and unsolved."* | Declared, never claimed solved; over-segmentation mitigates. **Residual risk accepted**, and asserted as *declared* — the gate's own criterion states it that way |
| **Golden set graded by the model that produced it** (circularity) | M | M | The register keeps this row with the note *"Not exercised in this plan, kept because the corpus run is what would expose it."* | The labeller role runs offline and writes read-only artefacts; it must not share a run with the governor role. The gate carries no labeller and asserts no value-level gold — only shape identity and a recorded baseline |
| **Sampled artefact regenerated on resume**, silently changing the result | M | H | The interruption is **part of the gate's acceptance test**, so this is the moment at which a regeneration policy would apply at scale — *"a single regeneration policy applied at scale changes results across the whole corpus."* | The orchestrator reads the determinism class; missing evidence → `failed`; retrying to agreement is forbidden and attempts are counted. Exercised through `E06-02` inside the gate's own flow |
| **Unknown wording variants in the corpus** — at 11k files the variants cannot be enumerated up front | H | H | The gate is the run in which the variants are met. The register's mitigation is that a variant is a **hash change rather than a deployment** — which the gate consumes from `S3-T04`. | `EpVR` tolerates variation; patterns are registry data; the Reviewer promotes repeats into rules. The gate records what the first run met rather than pretending to have covered it |

**All three of the plan's named execution risks land on this epic**, and each is a way the gate can be closed on evidence that looks sufficient (`plan-03-pipelines.md` §9):

1. **Starting the corpus run before `S3-T12` settles the policy/setting split** — the run's output was produced under settings that never entered the registry hash, so every ledger's `done` is a claim nobody can check.
2. **Running the corpus before `S3-T08`'s invalidation is proven** — at one document a bug; at 11k a corpus that looks complete and is inconsistent, with every stage `done` and every artifact verifying.
3. **Closing the gate on the 13 codes without `S3-T13`** — all 13 reachable while emitting subtly different shapes, invisible until a consumer writes their second integration.

**The gate's real risk is therefore not scale — it is a gate closed on four-of-five predecessors.** Each omitted predecessor leaves every other check green. That is why §4 above lists the three conditions as conditions and not as notes.

---

