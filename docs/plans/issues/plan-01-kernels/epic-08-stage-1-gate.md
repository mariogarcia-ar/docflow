# E08 — The Stage 1 gate

| Field | Value |
|---|---|
| Epic ID | **E08** |
| Capability | The Stage 1 closing flow: a synthetic 3-stage graph that runs, is interrupted, resumes, and is inspected from a shell |
| Issues | `E08-01` (`S1-T19`) — **`done`** (§3) |
| Issue count | **1** |
| Owner layer | **Kernels** (`wbs.md` §8) — integration test + demo script, over `descriptors/` and `fixtures/` |
| Wave span | **W7** — the last wave |
| Effort total | **1 × L** |
| Source plan | [`../../plan-01-kernels.md`](../../plan-01-kernels.md) §3 (the closing criterion), §5 (`S1-T19`), §6 (the runbook), §7a/§7c, §8, §11 |
| Depends on other epics | **E05** (orchestrator) · **E06** (product CLI shell) · **E07** (kernel lab CLI & suite) |

---

## §1 Objective

E08 delivers the **gate**: Stage 1 does not exist as *"done"* without it (`wbs.md` §1, §3). Its capability is not a component and not a feature — it is a **closed flow**: a trivial three-stage graph over a synthetic unit set completes; a person can kill it mid-stage and prove *from the outside* that the ledger told the truth about what had been written; `pause` then `run` continues from the exact stage; and a deleted artifact is detected without any flag.

It is a **separate epic with one issue** because it is a **distinct deliverable class** — the stage's closing criterion, not a capability inside it. Everything else in Stage 1 is built behind a boundary; this issue is the demonstration that the boundary holds under interruption. It is also the **join of two chains**: `S1-T19` is the only task whose dependency set contains issues from three different epics (E05, E06, E07), and it is #10 on the critical path of the whole PoC — Stage 2 does not start until this tick.

The flow is **synthetic on purpose**. The descriptor executes kernel ops only, which keeps the lab surface domain-free (`kernel-cli.md` §9, open decision #1) and makes Track 1 cheap enough to close early. That is what makes E07's suite load-bearing instead: the fakes the flow closes over are exactly what the matrix has to evict (`plan-01-kernels.md` §13).

---

## §2 Issues in this epic

| Issue | `wbs.md` task | Title | Wave | Depends on | Effort | PoC markers |
|---|---||---|---|:---:|---|:---:|---|
| `E08-01` | `S1-T19` | **Stage 1 closing flow (synthetic)** | **W7** | `S1-T09`, `S1-T10` → **E05** · `S1-T18` → **E06** · **`S1-T22`** → **E07** (all inter-epic) | L | — (**the gate; not deferrable**) |

No intra-epic edges exist: E08 has a single issue. It is the only issue in the plan with **three** distinct inter-epic dependencies, and the only one that is **not deferrable** under any marker.

---

## §3 Issue detail

### `E08-01` — implements `S1-T19`

**Title**
**Stage 1 closing flow (synthetic)**

**Status — `done`**

| # | Criterion | Status |
|---:|---|---|
| 1 | `descriptors/synthetic-3stage.yaml` is committed, three stages, kernel operations only, no domain noun | ✅ met — `acquire` / `transform` / `persist` on `store put` and `pdf probe`, with `slot` declared; asserted by reading the committed file for a forbidden vocabulary |
| 2 | A synthetic unit set exists | ✅ met — `U-0001` and `U-0002`, so dispatch is exercised across units and not only across stages |
| 3 | `orchestrator plan` exits `0`, writes no artifact, dispatches no stage | ✅ met — and `test_step_3` asserts the output tree **does not exist** afterwards |
| 4 | `orchestrator run` exits `0` | ✅ met, from a shell, through the installed entry point |
| 5 | Every stage of every unit is terminal, `done` **and** verifying | ✅ met |
| 6 | `run.json` carries the five keys and is consistent with the ledgers | ✅ met — plus `control`, `attempts` and `unverified`, which are additive |
| 7 | `ledger-read` reports state **and** the verification outcome | ✅ met — through K1's door and through K7's, and both agree |
| 8 | `pause` then a plain `run` continues from the exact stage; nothing `done` re-runs | ✅ met — the resumed pass reports `dispatched == []` |
| 9 | `stop --force` mid-`transform` leaves the stage **`running`** | ✅ met with a **real `SIGKILL`** in a subprocess — see below |
| 10 | The next `run` re-runs **at most one stage per in-flight unit** | ✅ met |
| 11 | No separate product `resume` verb | ✅ met — `docflow` has no `resume`; the lab surface's `orchestrator pause`/`resume` are K1's port methods and are how the interruption is driven |
| 12 | A deleted `done` artifact reads **incomplete**, no flag passed | ✅ met — `unverified == {"transform": "artifact_missing"}` while the recorded state stays `done` |
| 13 | A crash at the atomic-write boundary leaves `done` absent and `running` present | ✅ met |
| 14 | `rm O/run.json` then rebuild reproduces it **byte-identically** | ✅ met |
| 15 | `store manifest-rebuild` returns the **same** result | ✅ met — and now also **writes**, so both doors leave the same bytes |
| 16 | All five exit codes reachable; JSON on `0`/`2`/`3`; stderr carries nothing a script parses | ✅ met |
| 17 | A **sampled** artifact's deleted evidence reports `failed` with `evidence_missing`, and no fresh sample | ✅ met — with a correction recorded below |
| 18 | Invocable as the documented command from a clean checkout | ✅ met — asserted with `subprocess` against the installed `docflow-kernel`, not only through `dispatch` |
| 19 | Not deferrable, and carries no `# TODO` marker | ✅ met — asserted over the module's code |

**The kill is a real `SIGKILL`, and that is the difference that matters.** `tests/kernel_cli/_kill_harness.py` runs the flow in a **subprocess** and sends itself the signal from *inside* the interrupted stage's own operation — after `store.begin` wrote `running`, before the operation produced anything. An injected exception at the same point would leave the same ledger, so a simulated kill and a real one are different evidence, and the gate asks for the real one. Observed:

```
  7. a real SIGKILL           exit=137
  7. after the kill            {'acquire': 'done', 'transform': 'running', 'persist': 'pending'}
```

**The three scenarios Stage 1 owns close here.** *Resume after a forced kill* on steps 7-10; *Verification is not optional* on step 9, with no flag passed; *A sampled artifact is evidence, not a cache* through `E07-03`'s suite.

**One criterion was restated rather than satisfied, and the restatement is recorded.**
- **#17's mechanism.** `resume_decision` answers `None` for a stage that is not `done`, because a stage that never claimed an artifact — `running`, `pending`, `failed` — has nothing to lose. So the scenario is asserted by committing a `done` claim under a **sampled** kernel and asking the decision about it, which is `E05-03`'s consequence reached through the surface. Asserting it by deleting a *failed* stage's artifact would have been asserting about a stage with no claim, and it would have passed for the wrong reason — which is exactly what the first attempt did.

**Two production defects the gate's own tests found.**
1. **`store manifest-rebuild` derived without writing.** §6 step 11 expects *"both doors return what `rebuild_index()` returned"* and the file to be reproducible; a door that answered with a value while leaving the tree empty satisfied the letter and not the task. It now writes through `write_index`, the same call K1's door makes, so both leave byte-identical bytes.
2. **`store ledger-read` did not report the verification outcome.** `kernel-cli.md` §9 says it must report *"the same verification outcome as K1's"*, and it reported none. It now asks K1's `verify_ledger` rather than reimplementing the check — one definition of *the bytes are there*, reported by both doors.

**A structural finding about the kill, recorded rather than worked around.** `_ensure_ledger` declares a unit's stage set when the unit is **opened**, so a unit the scheduler never reached has **no ledger at all** — not a ledger of `pending` stages. That absence is the correct record, and the first version of the test asserted a `pending` ledger that could not exist. The assertion now states the absence.

**Effort**
**L** — thirteen runbook steps, a subprocess kill harness, and a demonstration that spans every issue before it.

**Test / evidence**
- `tests/kernel_cli/test_gate.py` — **18 tests**, all green; each names its runbook step, and `test_every_step_of_the_runbook_has_an_assertion` fails if a step loses its test.
- `tests/kernel_cli/_kill_harness.py` — the subprocess that dies by signal.
- `plan-01-kernels.md` §7a — *"the only test whose passing is the gate"*; §6 steps 1-13; §3's eight-row evidence table; §7c's three scenarios.
- `kernel-cli.md` §11 rows 1, 2 and 16 — the gate rows this issue drives end to end.
- All four QA gates green; the eight mutation harnesses green.
- **Verified from a shell**, not only in process: `--list`, `plan`, `run`, `ledger-read`, `manifest-rebuild` through both doors, an `MVP` command, and the kill.

**Context**
Four claims about the system are only worth what an operator can observe: that a killed stage is distinguishable from one that never ran; that `done` is only ever written about durable bytes; that a ledger is verified against the filesystem every time it is read; and that a stage can be interrupted and resumed without redoing the work before it. Each of those is asserted individually by an earlier issue — and none of them is *demonstrated* until they hold **together, across a kill**. This issue is that demonstration. It is the one test whose passing is the gate; every other test in the plan exists to make a failure of this one attributable (`plan-01-kernels.md` §7a).

**Deliverable**
Integration test + demo script

**Depends on**
- `S1-T09` — **inter-epic** (E05 → E08)
- `S1-T10` — **inter-epic** (E05 → E08)
- `S1-T18` — **inter-epic** (E06 → E08)
- **`S1-T22`** — **inter-epic** (E07 → E08) — a **hard predecessor** (`wbs.md` §3, §6.2)

**Acceptance criteria**

*The happy path — `plan-01-kernels.md` §6 steps 1–5*
- [ ] `descriptors/synthetic-3stage.yaml` is committed and defines three stages — `acquire` / `transform` / `persist` — whose `kernel`/`op` values reference kernel operations only, with **no domain noun**, no document type and no pipeline code.
- [ ] A synthetic unit set exists for the descriptor.
- [ ] `docflow-kernel orchestrator plan descriptors/synthetic-3stage.yaml --out O` exits `0`, writes **no** artifact and dispatches **no** stage.
- [ ] `docflow-kernel orchestrator run descriptors/synthetic-3stage.yaml --out O` exits `0`.
- [ ] Every stage of every unit is terminal in the ledger, with `done` **and** verification passed.
- [ ] `O/run.json` carries `state`, `totals`, `stages`, `outcomes` and `inflight`, and is consistent with the ledgers.
- [ ] `docflow-kernel orchestrator ledger-read O` reports the per-unit, per-stage state **and** the verification outcome alongside it.

*Interruption and recovery — steps 6–10*
- [ ] `docflow pause <job>` while units are in flight lets the in-flight work finish and leaves the ledger consistent; a subsequent plain `run` continues from the **exact** stage, and nothing already `done` re-runs.
- [ ] `docflow stop --force` mid-`transform` leaves the interrupted stage reading **`running`** — not `pending` and not `done`.
- [ ] The next `run` after that kill re-runs **at most one stage per in-flight unit**; everything before it is preserved and nothing after it had started.
- [ ] There is **no separate product `resume` verb** — continuing is *"run it again"*. Recovery is driven on the lab surface as `docflow-kernel orchestrator pause <job-id>` / `resume <job-id>`, which are port methods (`kernel-cli.md` §9, K1 row 5) and the surface this gate is observed on.
- [ ] Deleting one `done` stage's artifact by hand and reading the ledger again marks that stage **incomplete**, with **no flag passed**.
- [ ] A crash injected at the atomic-write boundary leaves `done` **absent** and `running` **present**.

*The derived manifest — step 11*
- [ ] `rm O/run.json` followed by `orchestrator manifest-rebuild O` reproduces it **from the ledgers alone**, byte-identical to the deleted one.
- [ ] `store manifest-rebuild O` returns the **same** result — both doors return what `rebuild_index()` returned.

*The exit contract — step 12*
- [ ] All five exit codes are reachable: `0`, `2`, `3`, `4`, `1`.
- [ ] stdout is valid JSON on exits `0`, `2` and `3`, and the envelope is the same shape on all three.
- [ ] stderr carries nothing a script parses.

*The a sampled artifact is evidence — the third scenario, per `plan-01-kernels.md` §7c*
- [ ] Deleting a **sampled** artifact's evidence reports the stage `failed` with an evidence-missing reason, and **no fresh sample is produced**.

*Non-deferrable*
- [ ] The flow is invocable as `docflow-kernel orchestrator run descriptors/synthetic-3stage.yaml --out O`, and its recovery is observable via `docflow-kernel orchestrator ledger-read O` — **from a clean checkout**, before any domain component exists.
- [ ] This issue is **not deferrable** and carries **no** `# TODO` marker: it is the gate.

**Test / evidence**
- `plan-01-kernels.md` §7a — the happy-path test that must pass to close the flow: build the 3-stage synthetic graph over N units, run it to completion, assert every stage terminal with a verifying artifact, assert `rebuild_index()` reproduces `run.json` from the ledgers alone, and assert the same flow is invocable as `docflow-kernel orchestrator run descriptors/synthetic-3stage.yaml --out O`. **This is the only test whose passing is the gate.**
- `plan-01-kernels.md` §3 — the closing criterion, the two acceptance commands, and the supporting command table (proves: the 8 kernels with determinism class and adapter availability; pause + run continues from the exact stage with no separate *product* `resume` verb — the lab surface's `orchestrator pause`/`resume` are port methods and are how the interruption is driven; `stop --force` + `ledger-read` → interrupted stage reads `running`; `manifest-rebuild` after `rm O/run.json`; `store ledger-read` reports the same verification outcome as K1's; `pytest tests/kernel_cli/` → 16 of the 17 rows).
- `plan-01-kernels.md` §3, observable evidence table — the eight rows this issue must reproduce: per-stage terminal states; a consistent `run.json`; the interrupted stage `running` after `stop --force`; at-most-one-stage re-run on the second run (`NFR-02`); a `run.json` rebuilt byte-for-byte; a deleted `done` artifact treated as incomplete with no flag (`ADR-006`, AC *Verification is not optional*); exit codes `0`/`2`/`3`/`4`/`1` reachable with valid JSON on the emitting exits; and a sampled kernel's deleted artifact reported `failed` with an evidence-missing reason (`FR-09`, AC *A sampled artifact is evidence, not a cache*).
- `plan-01-kernels.md` §6 — the full 14-step runbook; steps 1–5 are the happy path, 6–10 the required interruptions, 11–13 the manifest, the exit contract and the suite, and step 14 is ticking §11's exit checklist. **This issue's acceptance criteria are steps 1–13.**
- `kernel-cli.md` §11 **row 1** (a killed stage reported as never started, then resumed) and **row 2** (a stage marked `done` whose artifact is partial) — both `now`, both Stage 1 gate rows, both fixture `synthetic-3stage.yaml`, and both *procedures* that this issue's integration test drives end to end.
- `kernel-cli.md` §11 **row 16** (a manifest reporting a finished run that is not finished) — `rm O/run.json` between two invocations, asserted through **both** doors.
- `kernel-cli.md` §12 — `synthetic-3stage.yaml` is the fixture for rows 1 and 2 **and** for the Stage 1 closing flow.
- `plan-01-kernels.md` §8 — the Stage 1 integration test itself. Requirements **FR-01**, **FR-02**, **FR-05**, **FR-09**, **NFR-02**, and **NFR-01** (the synthetic half).
- `plan-01-kernels.md` §7c — **the three acceptance scenarios that close at Stage 1**:
  | Scenario | Where | Closes at |
  |---|---|---|
  | *Resume after a forced kill* | `prd.md` §8 | **`S1-T19`** (+ `S1-T18`, `S1-T07`) |
  | *A sampled artifact is evidence, not a cache* | `prd.md` §8 | `S1-T08`, **asserted through `S1-T22`** |
  | *Verification is not optional* | `prd.md` §8 | `S1-T10`, **asserted through `S1-T19` step 9** |
  If they slip to Stage 2, the invariants they assert are tested inside a domain component — the misattribution `kernel-cli.md` §1 exists to prevent.
- `traceability.md` §6 — *"The AC-to-stage split matters more than the count. Three of the six scenarios close at Stage 1."*
- `plans/README.md` §4 — the harness chain *"cannot slip **past** `S1-T19`"*; both chains converge here.

**Out of scope for this issue**
- **No domain noun in the descriptor.** No field, no document type, no pipeline code — the flow is synthetic **by construction**, and a descriptor naming a pipeline code is the drift this guards against (`kernel-cli.md` §9, `plan-01-kernels.md` §6 step 1). **Never** in Stage 1.
- **No real document, no real model, no real engine.** Track 1 closes over `S1-T11`'s **faked ports** — not Docling, not Ollama, not a provider (`plan-01-kernels.md` §13, Track 1). The real adapters land in parallel and are **not** on this flow's path.
- **No second `resume` verb** — no product `resume` verb and no resume flag on `docflow`. Continuing is *"run it again"*. **Never** on the product surface. The lab surface's `orchestrator resume` is a port method (`kernel-cli.md` §9) and **is** part of this gate's observation path.
- **No `--verify` flag and no ledger-trust `verify` subcommand.** Verification is an outcome of reading, and step 9 passes **no flag** (`ADR-006`). **Never**.
- **No `--rebuild-index` flag.** `rebuild_index()` is a library call in the PoC; step 11 is a command, not a flag (`prd.md` §7). `# TODO: [MVP]`.
- **No `--no-validate`.** **Never** (ADR-002).
- **A faked adapter may not soften an invariant.** A test double must still return a typed `Reason` on failure and still honour its determinism class, or the crash-recovery assertions prove nothing (`plan-01-kernels.md` §13, Track 1).
- **No Stage 2 work.** The Segmenter, Diagnosis, the canonical chain and the `ErpVR` contrast case all belong to Plan 2. This issue closes Stage 1 and nothing else.
- **Not deferrable.** This issue carries **no** `# TODO` marker and cannot be moved to a later stage — it **is** the stage close (`wbs.md` §1, `plan-01-kernels.md` §5).

**Effort**
**L** — the widest integration surface in the plan: a graph, a ledger read across two doors, three deliberate interruptions, an injected crash, a byte-identical rebuild and the exit-code contract, all observed **from outside the process** and reproducible from a clean checkout (`wbs.md` §7).

**Owner**
**Kernels** — the integration test and demo script over `descriptors/` and `fixtures/`, which `wbs.md` §8 assigns to the Kernels layer. (The **Surface** layer's contribution to this flow is `S1-T18`'s verbs, delivered by E06.)

**Frozen contract touched**
**Publishes** `plans/README.md` §3, Plan 1 row: the gate is where the whole row — the boundary types, the port interfaces, the 7-term cache key, the 7 durable ledger states, the determinism classes, the `KernelResult` JSON envelope and the 5 exit codes, the closed `reason.code` set, and the descriptor shape — becomes frozen and is named in Plan 2's §4. A change to any item in that row **re-opens this gate** (`plan-01-kernels.md` §4, entry condition 4).

---

## §4 Epic close condition

E08 is **`done`** when:

1. `E08-01` is `done`, and
2. the capability is **demonstrable from a clean checkout**: the two acceptance commands run, and the recovery is observable through the ledger rather than through logs.

**The epic's close condition *is* the stage's close condition.** `plan-01-kernels.md` §11's exit checklist is what an operator ticks to declare Plan 1 closed, and **Plan 2's §4 entry condition is that list and nothing else**.

**Does E08 gate `S1-T19`?** It **is** `S1-T19`. There is no epic above it inside Stage 1, and the gate it gates is the next plan's entry — Gate 1 in `plans/README.md` §2, whose close is *"pause / resume / stop --force recover correctly"*.

**Two conditions must hold for this epic to close legitimately, and both are risks rather than dependencies:**

| Condition | Why | Where enforced |
|---|---|---|
| `E07-03` (`S1-T22`) is `done` **before** this issue | `S1-T22` is a **hard predecessor** of `S1-T19`. Closing the gate without the silent-failure rows means Stage 1's three scenarios are proven only through the integration path and rows 1–2 stay prose | `wbs.md` §3, §6.2; `plan-01-kernels.md` §9, execution risk 2 |
| `E07-02` (`S1-T21`) has actually **completed**, not merely opened | An `S1-T21` that opened in W5 and never got its W3 adapter signatures makes the contract test pass vacuously — a green suite that proves nothing | `plan-01-kernels.md` §9, execution risk 1; `S1-T21`'s partial-completion status |

The wave map is not a preference: **Waves 5 and 6 exist so that the harness chain and the serial kernel chain converge here with both chains complete** (`plan-01-kernels.md` §9).

---

## §5 Traceability

| Issue | `wbs.md` task | FR / NFR (`traceability.md` §4) | Gap? | Evidence of the mapping |
|---|---|:---:|---|
| `E08-01` | `S1-T19` | **FR-01**, **FR-02**, **FR-05**, **FR-09**, **NFR-02**, **NFR-01** (the synthetic half) | no | The Stage 1 integration test itself |

No gap. `E08-01` carries the **richest** mapping in the plan — six requirements across both tables — which is the expected shape for a closing criterion: it is where the plan's claims stop being per-task criteria and become one observable flow.

The reverse check (`traceability.md` §5) places `S1-T19` in the orchestrator/store/ledger spine group (*"FR-03…FR-11, NFR-02, NFR-03 — the orchestrator/store/ledger spine"*) and against NFR-01 (`11k files, one command, survives interruption`), of which this issue proves **the synthetic half** — the corpus half is `S3-T09`/`S3-T14`, Plan 3.

**The three acceptance scenarios and their stage-1 attribution** (`plan-01-kernels.md` §7c, `traceability.md` §6) — all three are closed by or asserted through issues in this plan, and one of them closes here:

| Scenario | Closes at | This issue's part |
|---|---|---|
| *Resume after a forced kill* | **`S1-T19`** (+ `S1-T18`, `S1-T07`) | the scenario's flow is this issue's integration test |
| *A sampled artifact is evidence, not a cache* | `S1-T08`, asserted through `S1-T22` | the sampled-artifact acceptance criterion is asserted here as part of the closing run |
| *Verification is not optional* | `S1-T10`, **asserted through `S1-T19` step 9** | the deleted-artifact step, with **no flag passed** |

---

## §6 Risks

From `plan-01-kernels.md` §9 only:

| Risk | L | I | Why it touches E08 | Mitigation carried by this epic |
|---|:---:|:---:|---|---|
| **Sampled artifact regenerated on resume**, silently changing the result | M | H | The regeneration would be observed first at the gate: a killed-and-resumed run that silently re-samples reports `done` over a different answer. | An acceptance criterion asserts the deleted-sampled-evidence case reports `failed` with an evidence-missing reason and **no fresh sample is produced**. Proven by AC *A sampled artifact is evidence, not a cache*. |
| **Manifest drift** — `run.json` disagreeing with the ledgers | M | M | Step 11 is where drift is either absent or visible: the manifest is deleted and must be reproducible from the ledgers **alone**, through both doors. | Acceptance criteria require the byte-identical rebuild via `orchestrator manifest-rebuild` **and** `store manifest-rebuild`, both returning what `rebuild_index()` returned. |

**The plan's second named execution risk is *about* this issue** (`plan-01-kernels.md` §9):

> *Closing `S1-T19` before `S1-T22`. `S1-T19` is the gate, and `S1-T22` is a **hard predecessor** of it (`wbs.md` §3). Closing the gate without the silent-failure rows means the three scenarios Stage 1 owns are proven only through the integration path, and rows 1–2 of the matrix stay prose — so the first time a kernel fails silently it is inside a domain component, attributed to the wrong layer.*

The mitigation is structural and is already drawn as a direct inter-epic edge: **E07 → E08**, on the strength of `S1-T22`.

**One register row is deliberately *not* attached to this epic, stated rather than implied:** *"The 11k-file scale on the first full run"* (H/H, `wbs.md` §9) is owned by stage 3 and touches the corpus close (`S3-T14`), not this gate. Its mitigation chain passes *through* Stage 1 — *"Stage 1 proves resume on a synthetic flow"* — which is the contribution this issue makes to it; the risk itself is Plan 3's.

**Open decisions carried, not resolved:** none of the seven in `plan-01-kernels.md` §12 is resolved by this issue. Two of them shape what it can demonstrate:

| `plan-01-kernels.md` §12 | Question | Effect on what this issue can show |
|---:|---|---|
| **#1** | Whether the kernel CLI may execute a descriptor whose stages are domain components | The flow stays **synthetic by construction** — which is the intent — but the same command cannot debug a real pipeline graph. Resolving it "yes" would let a domain noun into the lab surface, which `kernel-cli.md` §10's forbidden vocabulary refuses |
| **#3** | Whether the 17-row matrix runs in CI at all stages, or only at Stage 1 | This issue's §3 evidence cites `pytest tests/kernel_cli/` as proof that 16 of 17 rows assert; if the suite is later split into fast/gated subsets, the composition of that command changes while the gate's criterion does not |

Open decisions **#2** (`--save` and an explicit `--root`) touches `S1-T20`/`S1-T22` (E07); **#4** touches `S1-T04`/`S1-T05` (E03); **#5** touches `S1-T14` (E04) and `S1-T08` (E05); **#6** and **#7** touch `S1-T08` and `S1-T09` (E05).
