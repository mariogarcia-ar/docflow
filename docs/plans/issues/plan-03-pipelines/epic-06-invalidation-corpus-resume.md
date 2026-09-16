# E06 — Invalidation & corpus-scale resume

| Field | Value |
|---|---|
| Epic ID | **E06** |
| Capability | Invalidation & corpus-scale resume — a forced reprocess invalidates everything downstream, and an 11k-file run resumes from the exact stage of the in-flight document without re-reading completed work |
| Issues | `E06-01` (`S3-T08`) — status `todo` · `E06-02` (`S3-T09`) — status `todo` |
| Issue count | **2** |
| Owner layer | **Surface** (`wbs.md` §8) — `docflow/cli.py` |
| Wave span | **W5 → W6** |
| Effort total | **1 × L · 1 × M** |
| Source plan | [`../../plan-03-pipelines.md`](../../plan-03-pipelines.md) §1, §2, §5 (`S3-T08`, `S3-T09`), §3 (the forced-`extract.p` and interruption evidence rows), §6 steps 8–9 and 12, §7b rows (downstream invalidation, environment non-settability, resume), §8, §9 execution risk 2, §11, §12 #5, §13 Track 2 |
| Depends on other epics | **E04** (`S3-T07` → `S3-T08`); entered from `S1-T05` (external) |

---

## §1 Objective

E06 delivers the two claims that make a corpus run **safe to start and safe to interrupt**. The first is that reprocessing a stage **invalidates everything downstream**: a forced `extract.p` marks `validate`/`consistency`/`report` `pending`, and **a stage left `done` over new fields is impossible**. The second is that a run killed at **4,821 of 11,034** documents resumes from the **exact stage of the in-flight document**, re-running at most that one stage, with completed documents skipped **without re-reading**.

The two belong in one epic because they are the same claim seen from two sides. Both rest on the ledger's `done` meaning what it says: `plan-03-pipelines.md` §10 names the stage's riskiest invariant as *"reprocessing a stage invalidates everything downstream, and completed work is never repeated on resume."* Invalidation without resume gives you a run you must restart; resume without invalidation gives you a run whose completed work is wrong. `plan-03-pipelines.md` §5 says the sequencing explicitly: resume **cannot be verified before downstream invalidation exists, because the two share the same ledger claims** — which is why `S3-T09` waits for `S3-T08` and not the other way round.

It is a separate deliverable because it is the **orchestrator's contract exposed through the CLI**: `--force` / `--stage` / `--only` are precision tools over K1's dispatch and the 7-term cache key, neither of which this plan owns. It is also the epic where non-negotiables 1 and 3 are charged at scale (index README §7): never `done` about non-durable bytes, and a sampled artefact is evidence and is never regenerated — at 11k documents a single regeneration policy applied at scale changes results across the whole corpus (`plan-03-pipelines.md` §9).

**What E06 is not.** It is not the resume *mechanism* — the durable states and `running`-before-work are Plan 1's (`S1-T07`, `sad.md` §7.1) and Stage 3 adds no state. It is not a `resume` verb: **there is no `resume` verb** — resume is the same `run` (`FR-01`, `plan-03-pipelines.md` §13 Track 4). It is not the ledger's stage set (`E04-01`) nor the manifest (`E04-03`), though it reads both.

---

## §2 Issues in this epic

| Issue | `wbs.md` task | Title | Wave | Depends on | Effort | PoC markers |
|---|---||---|---|:---:|---|:---:|---|
| `E06-01` | `S3-T08` | `--force`, `--stage`, `--only` with downstream invalidation | W5 | `S3-T07` → **E04** (inter) · `S1-T05` (external — the 7-term cache key) | L | `# TODO: [MVP]`: `--isolate`; `--keep-artifacts` |
| `E06-02` | `S3-T09` | Resume at corpus scale: per-document granularity, stage-level granularity | W6 | `S3-T08` → **E06** (intra) | M | `# TODO: [MVP]`: resume telemetry; `--state` reporting |

Intra-epic edge (not drawn as an epic edge): `E06-02` → `E06-01`. It is the epic's own internal order and the plan states the reason: *"`S3-T09` needs `S3-T08` — resume at corpus scale cannot be verified before downstream invalidation exists, because the two share the same ledger claims"* (`plan-03-pipelines.md` §5, Wave 6). Note also that `S3-T09` is one of only four tasks in the plan with **no external entry edge** — every one of its dependencies is inside Stage 3.

---

## §3 Issue detail

### `E06-01` — implements `S3-T08`

**Title**
`--force`, `--stage`, `--only` with downstream invalidation.

**Context**
`FR-30` fixes `--force` as *"the single override"* meaning *"do not trust the ledger"*, `--stage` as the floor for a forced reprocess, and `--only failed` as a run scope — with the consequence that **reprocessing a stage invalidates everything downstream**. The failure this issue exists to prevent is the nastiest one in the plan, and `plan-03-pipelines.md` §9 names it at both scales: *"A forced `extract.p` that does not re-pend `validate`/`consistency`/`report` produces fields that are new with verdicts that describe the old ones. At one document this is a bug; at 11k it is a corpus of output that looks complete and is inconsistent, with every stage `done` and every artifact verifying."* Nothing flags it, because every individual artefact is intact. The second half of the requirement is equally load-bearing: `--force`, `--stage` and `--only` are **never settable by environment** (`NFR-06`), because a persisted default would reprocess done work on every run or silently narrow every later run.

**Deliverable**
CLI + orchestrator invalidation — `docflow run … --force [--stage <stage>] [--only <scope>]`.

**Depends on**
- `S3-T07` — **inter-epic** (E04 → E06): invalidation is expressed in the ledger's states and the downstream stages are only meaningful once the layout and the manifest exist.
- `S1-T05` — **external entry edge**: the 7-term cache key is what makes precise invalidation possible, and `--force`'s *"do not trust the ledger"* is a statement about the key's terms.

**Acceptance criteria**
- [ ] `--force` means **"do not trust the ledger"** and is the single override; a forced run reprocesses the selected stage.
- [ ] `--stage` sets the **floor** for a forced reprocess, and `--only <scope>` scopes a run (`--only failed` re-runs failures).
- [ ] **A forced `extract.p` marks `validate`/`consistency`/`report` as `pending`** — asserted on the ledger before and after, not inferred.
- [ ] **A stage left `done` over new fields is impossible**: the test enumerates every downstream stage of the forced one and asserts none remains `done`.
- [ ] The `--force` report states **what is skipped and what re-runs**, so the operator can read the consequence rather than deduce it.
- [ ] **`--force`, `--stage` and `--only` are never settable by environment**: `DOCFLOW_FORCE=1`, `DOCFLOW_STAGE=validate` and `DOCFLOW_ONLY=failed` have no effect, and a persisted default cannot reprocess done work or silently narrow a later run (`NFR-06`).
- [ ] Invalidation is **precise**: a stage is invalidated because its key term changed, not because a flag was passed — so a forced stage whose inputs are genuinely unchanged is the caller's decision, while a **changed registry hash** invalidates exactly the stages that read it (`sad.md` §5.1, `S1-T05`).
- [ ] A forced stage writes `running` **before** its work starts and `done` only after the artefact is durable — the forced path uses the same write order as any other (`prd.md` FR-04, `sad.md` §7.1).
- [ ] No new kernel-boundary type and no new durable state are introduced (`plan-03-pipelines.md` §10, Task DoD).

**Test / evidence**
- `plan-03-pipelines.md` §5 row `S3-T08` — the verifiable criterion: *"A forced `extract.p` marks `validate`/`consistency`/`report` as `pending`; a stage left `done` over new fields is impossible; `--force`, `--stage` and `--only` are never settable by environment."*
- `plan-03-pipelines.md` §8 — *"**FR-30**, **NFR-06**"*, proof *"Forced `extract.p` re-pends downstream; `--force`/`--stage`/`--only` not settable by environment."*
- `plan-03-pipelines.md` §3, observable evidence — the forced-`extract.p` row: *"`validate`/`consistency`/`report` marked `pending`; a stage left `done` over new fields is impossible"*, guarding against *"stale verdicts describing the previous values, with every stage `done` and every artifact verifying (`FR-30`)."*
- `plan-03-pipelines.md` §6 step 12 — *"Force one stage and watch downstream re-pend."* `docflow run --pipeline M1-ErpVR documentos/ --out out/ --force --stage extract.p --only failed`; look at the ledger before and after and the `--force` report. The wrong result this step guards against is the corpus-scale one: *"fields re-extracted with verdicts describing the **previous** values — every stage `done`, every artifact verifying, the output inconsistent and nothing flagging it."*
- `plan-03-pipelines.md` §7b — *"Reprocessing a stage invalidates everything downstream"*: forced `extract.p`; inspect `validate`/`consistency`/`report`. What breaking it looks like: *"downstream stages stay `done` over new fields — a silent inconsistency where every artifact verifies."* And *"`--force`, `--stage`, `--only` are never settable by environment"*: set `DOCFLOW_FORCE=1`, `DOCFLOW_STAGE=validate`, `DOCFLOW_ONLY=failed` and observe.
- `plan-03-pipelines.md` §11 — *"A forced `extract.p` marks `validate`/`consistency`/`report` `pending`; no stage can remain `done` over new fields"* and *"`--force`, `--stage` and `--only` are never settable by an environment variable."*
- `plan-03-pipelines.md` §13, Track 2 — *"Forced stages re-pend downstream"*: golden artifact = a forced `extract.p`; must fail when broken by *"`validate`/`consistency`/`report` stay `done` over **new** fields — every stage done, every artifact verifying, the output inconsistent."*
- `plan-03-pipelines.md` §13, Track 4 — the command table: *"`--force` / `--stage` / `--only` — Precise invalidation — Never settable by environment (`S3-T08`, `NFR-06`)."*
- `plan-03-pipelines.md` §9, execution risk 2 — the full statement of the risk this issue closes.
- `prd.md` §5.3 **FR-30**, §6 **NFR-06**; `traceability.md` §4.1 FR-30, §4.2 NFR-06.
- `sad.md` §5 (the cache-key terms) and §5.1 (*"A threshold change invalidates exactly the stages that read it, which is what makes the ledger's `done` claims verifiable rather than merely recorded"*).
- `kernel-cli.md` §11 **row 16** — a manifest reporting a finished run that is not finished; the forced path is a second way to reach the same drift, which is why the ledger, not the manifest, is read before and after.

**Out of scope for this issue**
- **`--isolate` and `--keep-artifacts`.** Named as this task's own deferrals (`wbs.md` §5, `plan-03-pipelines.md` §2). `# TODO: [MVP]`.
- **`--retry-queue`, `--retry`, `--rebuild`, `--rule`, `--new-type`, `--value`.** `# TODO: [MVP]`.
- **Resume at corpus scale.** `E06-02` (`S3-T09`) is the second half; this issue establishes the invalidation the resume asserts against.
- **A `resume` verb.** There is **no `resume` verb** — continuing is *"run it again"* (`FR-01`). **Never**.
- **A `--verify` flag.** Verification is an outcome of reading; it is not a request, and the forced path gains no exception (`ADR-006`). **Never**.
- **A `--no-validate` flag.** `V` is invariant in all 13 pipelines; a forced reprocess may not skip validation (`ADR-002`, `prd.md` FR-18). **Never**.
- **Environment-settable coercion flags.** `--force`, `--stage`, `--only` never persist from the environment (`NFR-06`). **Never**.
- **Cross-document or cross-run invalidation.** Invalidation is per-unit, per-stage (`sad.md` §7.2, failure contained to the unit); one unit's forced stage never invalidates another's.
- **A new durable state for "invalidated".** `pending` is the state (`sad.md` §7.1: *"not dispatched, or invalidated by a key change"*). **Never** a new state.

**Effort**
**L** — three flags over one invalidation rule, where the rule is the plan's riskiest invariant and its verification is a **before/after ledger inspection across every downstream stage** plus an environment-non-settability check. The impl is moderate; the cost is a load-bearing invariant that has to be asserted in the direction that fails visibly rather than inferring it from a green run (`wbs.md` §7 — *"a load-bearing invariant or a heavyweight external dependency; needs an integration test"*).

**Owner**
**Surface** — `--force`/`--stage`/`--only` and the forced-run report are the CLI's (`wbs.md` §8: Surface owns `docflow/cli.py`). The dispatch and the states it re-pends are K1's Plan 1 mechanism.

**Frozen contract touched**
**Consumes** `plans/README.md` §3, Plan 1 row — *the 7-term cache key* and *the 7 durable ledger states* — and the Plan 2 row's component artefact chain (the downstream stages it invalidates). Freezes nothing new at Plan 1's level; the invalidation contract is part of the Plan 3 row E08 publishes.

---

### `E06-02` — implements `S3-T09`

**Title**
Resume at corpus scale: per-document granularity, stage-level granularity.

**Context**
`NFR-01` is the PoC's primary target: a run over 11k files completes as one command and survives interruption. `NFR-02` bounds what recovery may cost — **at most one stage re-run per in-flight document** — and `NFR-03` bounds the restart cost: a killed run must not repeat completed work. Stage 1 proved this on a synthetic flow (`S1-T19`); Stage 3 is where it is exercised at the only scale that matters, and `plan-03-pipelines.md` §1 states why it is a product requirement rather than an engineering one: *"a batch that cannot be interrupted safely is a batch nobody will run over the real corpus."* The third non-negotiable arrives here too: at 4,821 in-flight documents, a resume that regenerated a sampled artefact would silently change results across the corpus, so missing evidence yields `failed` and **never** a fresh sample (`prd.md` FR-09).

**Deliverable**
Verified resume path — the corpus-scale kill-and-resume evidence, not new mechanism.

**Depends on**
`S3-T08` — **intra-epic**. No inter-epic dependency and no external entry edge: this is one of only four tasks in the plan that depend entirely on Stage 3 work.

**Acceptance criteria**
- [ ] `docflow stop --force` while documents are in flight reports the runs, **distinguishes a finishing run from an active one**, and reports how many documents were left in flight.
- [ ] Every **interrupted stage reads `running`** in its ledger — not `pending` and not `done` (`sad.md` §7.1, `S1-T07`).
- [ ] A run killed at **4,821 of 11,034** documents **resumes from the exact stage of the in-flight document**.
- [ ] The resumed run re-runs **at most one stage** for that document; everything before it is preserved and nothing after it had started.
- [ ] **Completed documents are skipped without re-reading** — asserted by observing that their artefacts are not re-read, not merely that their results are unchanged.
- [ ] **There is no separate `resume` verb**: the resume is the same command re-run verbatim (`FR-01`; `plan-03-pipelines.md` §6 step 9 — *"Re-run step 6 verbatim"*).
- [ ] Resume granularity is **both** per-document and stage-level: the run's progress is measured in documents, and progress within a document is measured in stages.
- [ ] A **sampled** artefact whose evidence is missing on resume reports the stage `failed` with an evidence-missing reason, and **no fresh sample is produced** (`prd.md` FR-09; `kernel-cli.md` §5 `evidence_missing`).
- [ ] Verification runs on **every** ledger read during resume, with no flag passed: a `done` stage whose artefact was hand-deleted is treated as incomplete (`ADR-006`, `prd.md` FR-05).
- [ ] Failure remains **contained to the unit**: one document failing during the resumed portion does not abort the run (`sad.md` §7.2).
- [ ] No new kernel-boundary type, no new state and no new resume mechanism are introduced (`plan-03-pipelines.md` §10, Task DoD).

**Test / evidence**
- `plan-03-pipelines.md` §5 row `S3-T09` — the verifiable criterion: *"A run killed at 4,821 of 11,034 documents resumes from the exact stage of the in-flight document; completed documents are skipped without re-reading."*
- `plan-03-pipelines.md` §8 — *"**NFR-01**, **NFR-02**, **NFR-03**"*, proof *"The kill-and-resume at corpus scale; completed documents skipped without re-reading."*
- `plan-03-pipelines.md` §3, observable evidence — the interruption row: *"the interrupted stage reads `running`; the next `run` resumes from **the exact stage of the in-flight document**; completed documents are skipped without re-reading"*, guarding against *"restarting the batch, or re-reading documents already done (`NFR-01`, `NFR-02`, `NFR-03`)."*
- `plan-03-pipelines.md` §6 step 8 — *"Interrupt mid-corpus."* `docflow stop --force` while documents are in flight; look at the stop report and then **every ledger of an in-flight document**. The wrong result: *"a kill that leaves no record of what was in flight, so the next run cannot tell interrupted from never-started."*
- `plan-03-pipelines.md` §6 step 9 — *"Resume with the same command."* Re-run step 6 **verbatim**; watch which documents are skipped and which continue, and read the ledger of the previously in-flight document. The wrong results: *"re-reading documents that were `done`; or restarting the in-flight document from acquisition."*
- `plan-03-pipelines.md` §7b — *"Resume skips completed work and re-runs at most one stage per in-flight document"*: kill at ~4,821 of 11,034 and resume. What breaking it looks like: *"documents already `done` are re-read, or the in-flight document restarts from acquisition."*
- `plan-03-pipelines.md` §7c — `kernel-cli.md` §11 **row 1** (*"a killed stage reported as never started, then resumed"*) exercised *"over 11k documents rather than a synthetic unit set"* through §6 steps 8–9; and **row 4** (*"a 150 DPI scan rendered at 300 and reported as 300"*) through the M2/M3 codes over real scans.
- `plan-03-pipelines.md` §13, Track 2 — *"Resume skips completed work"*: golden artifact = a kill at ~4,821 of ~11,034 documents; must fail when broken by *"a completed document is re-read, or the in-flight one restarts at acquisition."* Track 1 rung 3 — the corpus, *"interrupted mid-run and resumed"*.
- `plan-03-pipelines.md` §11 — the exit-checklist item: *"The run was interrupted mid-corpus and resumed successfully: completed documents skipped without re-reading, the in-flight document resumed at its exact stage, at most one stage re-run for it."*
- `plan-03-pipelines.md` §9 — the sampled-artefact row: *"At 11k documents this is the risk with the largest blast radius, because a single regeneration policy applied at scale changes results across the whole corpus."* And the 11k-file-scale row, whose mitigation is *"Stage 1 proved resume on a synthetic flow; slot and disk policy settled at `S3-T11` before the corpus run; the first run is interruptible by design."*
- `prd.md` §8, *Resume after a forced kill* — the acceptance scenario this issue closes; §6 **NFR-01**, **NFR-02**, **NFR-03**; §10 — *no document may claim these are solved* (the limitation table this issue does not touch).
- `sad.md` §7.1 — the 7 states and `running` as *"the whole crash-recovery design"*; §7.2 — *"Failure is contained to the unit"* and verification on every read.
- `plans/README.md` §2 non-negotiable 3 — *"A sampled artifact is evidence and is never regenerated. A missing sampled artifact produces `failed` with an evidence-missing reason, never a fresh sample."*

**Out of scope for this issue**
- **Resume telemetry** and **`--state` reporting**. Named as this task's own deferrals (`wbs.md` §5, `plan-03-pipelines.md` §2). `# TODO: [MVP]`.
- **The invalidation rule.** `E06-01` (`S3-T08`); this issue resumes *against* it.
- **A `resume` verb, a `--resume` flag or a resume subcommand.** **Never** — resume is the same `run` (`FR-01`).
- **A `--verify` flag.** No flag is passed to make verification happen, including on the resume path (`ADR-006`). **Never**.
- **Regenerating a sampled artefact to make a resume "complete".** Missing evidence → `failed` (`prd.md` FR-09). **Never**, and this is the corpus-scale instance of non-negotiable 3.
- **Whether a sampled artefact may ever be regenerated with the new observation recorded.** Carried **open** (`plan-03-pipelines.md` §12 **#5**, touching `S3-T09` and `S3-T14`); the PoC answer stays *never regenerate*, and the operator's remedy is a re-run with a new observation — which the PoC does not express as a first-class outcome.
- **Distributed or multi-host resume.** `# TODO: [RELEASE]`.
- **A resume that re-reads a document to confirm it is still correct.** Completed documents are skipped **without re-reading** (`NFR-03`). **Never**.
- **Retry-until-agreement.** Forbidden: retrying to obtain agreement is not a resume strategy, and the attempt count is recorded so the pattern is visible (`sad.md` §9; `kernel-cli.md` §7). **Never**.
- **Latency or throughput targets for the resumed portion.** `NFR-11`: the baseline is recorded, no target asserted. `# TODO: [MVP]`.

**Effort**
**M** — little to build and a great deal to observe: a kill at a specific document count, a per-ledger reading of every in-flight document, a re-run verbatim, and an assertion that completed work was skipped **without being re-read**. The verification is an integration procedure over a corpus-sized input rather than a unit assertion (`wbs.md` §7).

**Owner**
**Surface** — the resume path is exercised through `docflow run` (`wbs.md` §8). The states, the determinism classes and the barriers it relies on are Plan 1 mechanisms.

**Frozen contract touched**
**Consumes** `plans/README.md` §3, Plan 1 row — *the 7 durable ledger states*, *the determinism classes* and *the 5 exit codes* — and, from the Plan 2 row, the escalation policy's single ownership, which bounds what a resumed document may do. Freezes nothing new; it is the strongest consumer of Plan 1's resume contract at the PoC's real scale.

---

## §4 Epic close condition

E06 is **`done`** when:

1. `E06-01` and `E06-02` are `done`, and
2. the capability is **demonstrable at corpus scale**: a forced `extract.p` leaves no downstream stage `done`, read from the ledger before and after; `DOCFLOW_FORCE=1`, `DOCFLOW_STAGE=validate` and `DOCFLOW_ONLY=failed` have no effect; a run killed mid-corpus leaves each interrupted stage reading `running` with the count of in-flight documents reported; and the same command re-run resumes from the **exact stage of the in-flight document**, skipping completed documents without re-reading them.
3. **Plan 3 DoD, per epic:** no new kernel, no new component, no new kernel-boundary type — this epic adds configuration and data (`plan-03-pipelines.md` §10, Task DoD). It closes the stage's **riskiest invariant**, and that invariant has a test that **fails when broken** (`plan-03-pipelines.md` §10, Stage DoD).

**Does E06 gate `S3-T14`?** **Yes, directly and decisively.** `S3-T14`'s dependency set names `S3-T09` (index README §3, row 11), and `S3-T14`'s own verifiable criterion requires that *"the first full run over the corpus completes and is interrupted and resumed successfully."* So the gate cannot close without this epic's capability, not merely without its artefacts. E06 is the only epic whose subject is a **condition inside the gate's acceptance test** rather than an input to it: a corpus run that cannot be interrupted safely is not a run the gate may report as passing, and `S3-T09` is where that is proved.

---

## §5 Traceability

| Issue | FR / NFR (`traceability.md` §4) | Gap? | Evidence of the mapping |
|---|---|:---:|---|
| `E06-01` | **FR-30** (`--force`/`--stage`/`--only` + downstream invalidation), **NFR-06** (never settable by environment) | no | A forced `extract.p` re-pends `validate`/`consistency`/`report`; the two environment attempts fail |
| `E06-02` | **NFR-01** (11k files, one command, survives interruption), **NFR-02** (at most one stage re-run per in-flight document), **NFR-03** (restart cost bounded) | no | The kill-and-resume at corpus scale; completed documents skipped without re-reading |

No issue in E06 has an empty mapping. `plan-03-pipelines.md` §8 assigns `S3-T08` exactly `FR-30`/`NFR-06` and `S3-T09` exactly `NFR-01`/`NFR-02`/`NFR-03`; `traceability.md` §4.2 additionally carries `NFR-02` back to Stage 1 (`S1-T07`, `S1-T19`) and `NFR-03` to `S1-T03`/`S1-T05`, which is why this epic resumes against mechanisms it does not own.

**Open decision this epic carries, unresolved:**

| `plan-03-pipelines.md` §12 | Question | Touches | Why it stays open |
|---:|---|---|---|
| **#5** | Whether a sampled artefact may ever be regenerated, with the new observation recorded | `E06-02` (`S3-T09`) and `E08-01` (`S3-T14`) | The PoC answer is **never regenerate** — missing evidence → `failed`. At corpus scale the consequence is concrete: a lost OCR or model artefact makes that document permanently unreproducible **within the run**, and the operator's remedy is a re-run with a new observation, which the PoC does not express as a first-class outcome. Carried forward unresolved; the acceptance criteria above assert the *never* and do not answer the *ever* |

`plan-03-pipelines.md` §12 **#5** is the only one of the ten that this epic carries, and it is the one the index README §7 names as having the largest blast radius in the plan.

---

## §6 Risks

From `plan-03-pipelines.md` §9 only, keeping the rows that name this epic's tasks:

| Risk | L | I | Why it touches E06 | Mitigation carried by this epic |
|---|:---:|:---:|---|---|
| **The 11k-file scale on the first full run** — disk, memory for full-page bitmaps, wall time | H | H | `E06-02` **is** the task at that scale: the run it interrupts is 11k documents long, and the resume is the property that makes the run survivable. The register's mitigation names it by stage — *"the first run is interruptible by design."* | Stage 1 proved resume on a synthetic flow; slot and disk policy settled at `S3-T11` **before** the corpus run (E03); the first run is interruptible by design — which the acceptance criteria here make observable rather than assumed |
| **Sampled artefact regenerated on resume**, silently changing the result | M | H | `E06-02` is where the regeneration *would* happen: a resume is exactly the moment at which re-obtaining a sampled artefact is tempting. The register's own words: *"At 11k documents this is the risk with the largest blast radius, because a single regeneration policy applied at scale changes results across the whole corpus."* | The orchestrator reads the determinism class; **missing evidence → `failed`**; retrying to agreement is forbidden and attempts are counted. Carried here as an explicit acceptance criterion and as the third non-negotiable (index README §7) |

**The plan-specific execution risk that lands on this epic** (`plan-03-pipelines.md` §9, way 2):

> **Running the corpus before `S3-T08`'s invalidation is proven.** A forced `extract.p` that does not re-pend `validate`/`consistency`/`report` produces fields that are new with verdicts that describe the old ones. At one document this is a bug; at 11k it is a corpus of output that looks complete and is inconsistent, with every stage `done` and every artifact verifying.

E06's wave order is the fix, and it is not a preference: `S3-T09` waits for `S3-T08` precisely because both read the same ledger claims, so a resume proven before invalidation would be proving the wrong thing (index README §5, Wave 6).

**The plan names this epic's invariant as the stage's riskiest** (`plan-03-pipelines.md` §10, Stage DoD): *"for Stage 3 that invariant is **reprocessing a stage invalidates everything downstream, and completed work is never repeated on resume**."* Both halves live here, and both tests are written to fail when the invariant breaks.

---

