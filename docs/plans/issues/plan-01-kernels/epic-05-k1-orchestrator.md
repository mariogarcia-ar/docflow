# E05 — K1 Orchestrator — dispatch, durability, scheduling

| Field | Value |
|---|---|
| Epic ID | **E05** |
| Capability | K1 Orchestrator: unit/stage/graph dispatch, the 7 durable states, determinism classes, typed slots and barriers, mandatory verification |
| Issues | `E05-01` (`S1-T06`) · `E05-02` (`S1-T07`) · `E05-03` (`S1-T08`) · `E05-04` (`S1-T09`) · `E05-05` (`S1-T10`) — all `todo` |
| Issue count | **5** |
| Owner layer | **Kernels** (`wbs.md` §8) — `docflow/kernels/` |
| Wave span | **W4 → W6** (W4: 1 · W5: 2 · W6: 2) |
| Effort total | **2 × L · 2 × M · 1 × S** |
| Source plan | [`../../plan-01-kernels.md`](../../plan-01-kernels.md) §2, §5 (`S1-T06`–`S1-T10`), §6, §7a–§7b, §8, §12 open decisions 6, 7 |
| Depends on other epics | **E02** (K7 store & ledger) · **E03** (K8 registry & the cache key) |

---

## §1 Objective

E05 delivers the thing the whole plan exists to make provable: **a graph of stages over units, driven to completion, with states that tell the truth under interruption**. Four properties, all of them invariants rather than features:

1. `running` is written **before** the work starts, so a killed stage is never misread as one that never began.
2. `done` is never written about bytes that are not durable (the ordering itself lives in E02; the scheduler that calls it is here).
3. A **sampled** artifact is evidence: a missing one produces `failed` with an evidence-missing reason and is **never** regenerated.
4. Verification is an **outcome of every ledger read**, with no flag and no code path that skips it.

It is a separate deliverable because it is the layer where the plan's riskiest invariants are either true or false, and because it is the head of the longest serial chain in Stage 1. K1 executes graphs it did not write (`kernel-cli.md` §9): it does not interpret a stage, does not know a domain concept, and does not own the meaning of a run — K7 owns the bytes, K1 owns what they mean (`sad.md` §3). That division is why `rebuild_index()` is K1's operation and the **only** authority for a manifest, with K7's `rebuild_manifest()` delegating to it (`traceability.md` §7.3 defect 10).

---

## §2 Issues in this epic

| Issue | `wbs.md` task | Title | Wave | Depends on | Effort | PoC markers |
|---|---||---|---|:---:|---|:---:|---|
| `E05-01` | `S1-T06` | K1 orchestrator core: unit / stage / graph / ledger / manifest, dependency dispatch | W4 | `S1-T03` → **E02**, `S1-T05` → **E03** (both inter) | L | `# TODO: [MVP]`: no `--rebuild-index` flag |
| `E05-02` | `S1-T07` | K1 durable states: the 7 states, `running` written **before** the work starts | W5 | `S1-T06` → **E05** (intra) | L | — |
| `E05-03` | `S1-T08` | Determinism classes + resume consequence | W5 | `S1-T06` → **E05** (intra) | M | — |
| `E05-04` | `S1-T09` | Typed slots (`cpu`/`gpu`/`remote`) + barriers + unit-contained failure | W6 | `S1-T07` → **E05** (intra) | M | `# TODO: [MVP]`: per-device slot policy beyond `gpu=1` |
| `E05-05` | `S1-T10` | Mandatory verification on every ledger read, with **no flag** | W6 | `S1-T07` → **E05** (intra) | S | — |

Intra-epic edges (not drawn as epic edges): `E05-02`/`E05-03` → `E05-01`; `E05-04`/`E05-05` → `E05-02`.

This is the only epic with an edge from **two** other epics (E02 and E03), because `S1-T06` waits on both the ledger write path and the cache key. It is also the epic that produces **two** inter-epic edges outward (E05 → E06, E05 → E08).

---

## §3 Issue detail

### `E05-01` — implements `S1-T06`

**Title**
K1 orchestrator core: unit / stage / graph / ledger / manifest, dependency dispatch.

**Context**
Nothing above the store can run until something reads a graph, decides what is ready, dispatches it, and writes down what happened. This issue builds that — and, because a manifest that is authoritative drifts, it builds the manifest as a **derived** artifact: `rebuild_index()` reproduces `run.json` from the ledgers alone, and K7's `rebuild_manifest()` delegates to it rather than reimplementing it.

**Deliverable**
`docflow/kernels/orchestrator.py`

**Depends on**
`S1-T03` — **inter-epic** (E02 → E05) · `S1-T05` — **inter-epic** (E03 → E05). It needs the ledger write path and the cache key; it defines neither.

**Acceptance criteria**
- [ ] `docflow/kernels/orchestrator.py` exists and models unit / stage / graph / ledger / manifest as distinct concepts.
- [ ] A **3-stage synthetic graph runs over N units** with N > 1, dispatching a stage only once its declared needs are satisfied.
- [ ] A stage whose needs are unmet is **not** dispatched.
- [ ] Dispatch decides using the cache key: a stage whose key is already terminal is not re-run.
- [ ] `run.json` is **derived** and carries `state`, `totals`, `stages`, `outcomes`, `inflight`, consistent with the ledgers (`plan-01-kernels.md` §3, evidence table).
- [ ] `rebuild_index()` **reproduces `run.json` from the ledgers alone** — the byte-identical claim is checked by deleting `run.json` and rebuilding it.
- [ ] `rebuild_index()` is the **only authority** for a manifest; K7's `rebuild_manifest()` delegates to it and both doors return what `rebuild_index()` returned (`kernel-cli.md` §9).
- [ ] `run.json` is `jq`-readable (`NFR-09`).
- [ ] The orchestrator **executes a graph it did not interpret**: a descriptor's stages reference kernel operations, and no stage name, parameter or field in the orchestrator contains a domain noun.
- [ ] The orchestrator reads a descriptor whose stages are kernel ops only; a descriptor naming a pipeline code is not a shape it accepts (`kernel-cli.md` §9).

**Test / evidence**
- `plan-01-kernels.md` §8 — `rebuild_index()` reproduces `run.json` from ledgers; row 16; `jq`-readable output. Requirements **FR-11**, **NFR-09**.
- `kernel-cli.md` §11 **row 16** (K7 — a manifest reporting a finished run that is not finished): `orchestrator manifest-rebuild O` after `rm O/run.json`; assertion the manifest is reconstructed from ledgers alone. Status `now` — Stage 1 CI gate. **No fixture:** row 16 is `rm O/run.json` between two invocations (`kernel-cli.md` §12).
- `plan-01-kernels.md` §6 steps 3–5 and 11 — `orchestrator plan` validates without executing (step 3); `run` produces a consistent `run.json` (step 4); `ledger-read` reports state *and* verification (step 5); step 11 deletes `run.json` and rebuilds it through **both** doors, asserting byte-identical output and that `store manifest-rebuild` returns the same.
- `plan-01-kernels.md` §7a — §7a's happy-path test is the gate's (`E08-01`); this issue's criterion is the mechanism it will assert.
- `kernel-cli.md` §9 (K1) — `orchestrator plan`, `run`, `status`, `jobs`, `pause`/`resume`, `stop`, `ledger-read`, `manifest-rebuild` are all `now`.
- `plan-01-kernels.md` §13, Track 1 — the fast flow is driven through orchestrator + store + ledger with **faked ports**; this issue is what makes that possible before any adapter exists.

**Out of scope for this issue**
- **No durable-state ordering.** That `running` is written *before* the work starts is `E05-02`; the 7-state set is `E05-02`'s to fix. This issue provides the dispatch and the ledger interaction.
- **No determinism classes.** `E05-03`.
- **No slots, barriers or unit-contained failure.** `E05-04`.
- **No mandatory verification on read.** `E05-05`.
- **No `--rebuild-index` flag.** `rebuild_index()` is a **library call** in Stage 1; the flag stays deferred. `# TODO: [MVP]` (`prd.md` §7, `traceability.md` §7.3 defect 2).
- **No distributed orchestration, no object-storage backend, no HA.** `# TODO: [RELEASE]`.
- **No domain noun and no pipeline code.** **Never** (`kernel-cli.md` §9/§10).

**Effort**
**L** — the largest single module in the plan: five concepts, a derived-manifest invariant, and a byte-identical rebuild that must be verified against the ledger tree alone (`wbs.md` §7).

**Owner**
**Kernels** — `docflow/kernels/orchestrator.py` (`wbs.md` §8).

**Frozen contract touched**
**Consumes** the Plan 1 row of `plans/README.md` §3 — the 7-term cache key (E03-02), the port interfaces (E04-01) and `KernelResult`. **Contributes to** the *descriptor shape* named in that row: `descriptors/synthetic-3stage.yaml`.

---

### `E05-02` — implements `S1-T07`

**Title**
K1 durable states: the 7 states, with `running` written **before** the work starts.

**Context**
The difference between a resume that is correct and one that silently skips work is *when* the state is written. If `running` is written only on completion, a killed stage reads as one that never began — so the resume path treats it as fresh work and the next run does something different from what the ledger claimed. This issue is the ordering itself, and the plan calls it *"the whole crash-recovery design"* (`wbs.md` §6.1).

**Deliverable**
`docflow/kernels/orchestrator.py` (continuation of `E05-01`'s file)

**Depends on**
`S1-T06` — **intra-epic**. Externally: E02 (via `E05-01`) and E03 (via `E05-01`).

**Acceptance criteria**
- [ ] Exactly **seven** durable states exist; no eighth value is writable and none is missing.
- [ ] `running` is written **before** the work of a stage starts — demonstrable by killing a stage mid-work and reading `running`.
- [ ] A **kill mid-stage** leaves the ledger reading `running` — **not** `pending` and **not** `done`.
- [ ] The invariant *"never `done` about a non-durable artifact"* **holds under an injected crash** between the write and the rename.
- [ ] The injected-crash test **fails** if the ordering is moved: with `done` written before the rename returns, the test must go red (the invariant test must fail when the invariant is broken, `plan-01-kernels.md` §7b).
- [ ] A resumed run re-runs **at most one stage per in-flight unit** (`NFR-02`), and everything before it is preserved.
- [ ] A stage that had completed before the kill does **not** re-run on resume.
- [ ] No code path writes a state other than one of the seven, and no path writes `running` after the work has started.

**Test / evidence**
- `kernel-cli.md` §11 **row 1** (a killed stage reported as never started, then resumed): `orchestrator run <d> --out O`, kill mid-stage, then `orchestrator ledger-read O`; assertion the ledger reads `running` for the killed stage. Status `now` — Stage 1 CI gate. Fixture `synthetic-3stage.yaml`.
- `kernel-cli.md` §11 **row 2** (a stage marked `done` whose artifact is partial): `orchestrator run` with a crash injected between write and rename; assertion `done` is **absent** and `running` is **present**. Status `now` — Stage 1 CI gate. Fixture `synthetic-3stage.yaml`.
- `plan-01-kernels.md` §7b row 3 — *"`running` is written **before** the work starts"*: kill mid-stage, then read; breaking it looks like *"the scheduler writes state only on completion and a killed stage reports as never having run"*.
- `plan-01-kernels.md` §7b row 2 — *"Never `done` about non-durable bytes"*, task cell `S1-T03`, `S1-T07`.
- `plan-01-kernels.md` §6 steps 7–8 — `docflow stop --force` mid-`transform` then `ledger-read` → `running`; then resume → **at most one stage per in-flight unit** re-runs (`NFR-02`), nothing after it had started.
- `plan-01-kernels.md` §8 — rows 1; injected-crash invariant test; `S1-T19`'s at-most-one-stage assertion. Requirements **FR-03**, **FR-04**, **NFR-02**.
- `plan-01-kernels.md` §3, acceptance scenario *Resume after a forced kill* (`prd.md` §8) — closes at `S1-T19` (+ `S1-T18`, `S1-T07`).

**Out of scope for this issue**
- **No verification on read.** `E05-05`.
- **No determinism-class handling.** `E05-03` — this issue guarantees the *state* is truthful; what a truthful state implies for a sampled artifact is the next issue's.
- **No slot or barrier scheduling.** `E05-04`.
- **No `resume` verb.** Recovery is *"run it again"*: there is no separate `resume` verb (`FR-01`, `FR-02`, `plan-01-kernels.md` §3). **Never** a new verb.
- **No `--verify` flag**, no ledger-trust `verify` subcommand, no `--force`-shaped escape on the read path. **Never** (`kernel-cli.md` §9).
- **No distributed state store.** The states live on the filesystem. `# TODO: [RELEASE]`.

**Effort**
**L** — a load-bearing invariant requiring a crash-injection test that must fail when the ordering is broken, plus the resume-cost assertion. The verification is the work (`wbs.md` §7).

**Owner**
**Kernels** — `docflow/kernels/orchestrator.py` (`wbs.md` §8).

**Frozen contract touched**
**Freezes** `plans/README.md` §3, Plan 1 row: *the 7 durable ledger states*. Plan 2's ledger writer emits the `not_applicable` list against this set and may not change it.

---

### `E05-03` — implements `S1-T08`

**Title**
Determinism classes + resume consequence.

**Context**
Some artifacts can be recomputed and some cannot — and the difference decides what the system is allowed to do when one goes missing. Recomputing a **deterministic** artifact is free and correct. Recomputing a **sampled** one produces a different answer, reported as `done`, so the run silently changes its result while claiming success. This issue makes the class an input to the resume decision rather than a documentation note.

**Deliverable**
`docflow/kernels/determinism.py`

**Depends on**
`S1-T06` — **intra-epic**. Externally: E02 and E03, via `E05-01`.

**Acceptance criteria**
- [ ] Exactly three determinism classes exist: **deterministic**, **sampled**, **external**.
- [ ] A **deterministic** artifact is recomputable — a missing one is recomputed and the result is byte-identical (its hash is the evidence).
- [ ] A **sampled** artifact with a missing file reports **`failed`** with an **evidence-missing** reason (`reason.code: evidence_missing`, exit `2`).
- [ ] A sampled artifact is **never regenerated** — no code path re-samples to fill a gap. This is asserted by a test that would detect a fresh sample reported as `done`.
- [ ] An **external** artifact's missing evidence is reported as a typed outcome, and its value is never asserted as reproducible.
- [ ] The class is **read from the artifact's producing kernel**, not guessed, defaulted or set per run.
- [ ] A test that deletes a sampled artifact and reads the ledger proves the stage reports `failed` and **does not** produce a fresh sample. The test **fails** if regeneration occurs.
- [ ] The recorded attempt count is visible, so *"retry until agreement"* would be detectable (`kernel-cli.md` §7, `plan-01-kernels.md` §9).
- [ ] The classes match `kernel-cli.md` §7: K1, K2, K3, K7, K8 deterministic; K4, K5 sampled (K4 mapped by `sad.md` §4); K6 external.

**Test / evidence**
- `plan-01-kernels.md` §7b row 5 — *"A sampled artifact is never regenerated"*: delete a sampled artifact, read the ledger; breaking it looks like *"the stage re-runs and reports `done` with a fresh sample, changing the result while reporting success"*.
- `plan-01-kernels.md` §8 — AC *A sampled artifact is evidence, not a cache*. Requirement **FR-09**.
- `plan-01-kernels.md` §3, acceptance scenario *A sampled artifact is evidence, not a cache* (`prd.md` §8) — closes at **`S1-T08`**, asserted through `S1-T22` (`plan-01-kernels.md` §7c).
- `plan-01-kernels.md` §3, evidence table — *"A sampled kernel's artifact deleted → the stage reports `failed` with an evidence-missing reason; the wrong result it guards against: a fresh sample silently substituted"*.
- `kernel-cli.md` §7 — the effective-difference of each class; `--repeat` is the *demonstration* of non-reproducibility, and must **never** be used to retry until two answers agree.
- `plan-01-kernels.md` §13, Track 2 — *"Sampling discipline"*: `--repeat` over the same input; the golden evidence must fail when sequential hashes **differ** for a deterministic kernel, or are **identical** for a sampled one.

**Out of scope for this issue**
- **No regeneration policy change.** Stage 1 fixes *"never regenerate"*. Relaxing it later is a **policy** decision that would change this issue's done-when and therefore re-open this gate — it cannot be done from Plan 2. `plan-01-kernels.md` §12 open decision **#6**; carried here, **not resolved**.
- **No reclassification of Docling.** K4 reports `sampled`; whether a pinned Docling is in fact deterministic is `plan-01-kernels.md` §12 open decision **#5**, carried here and in `E04-04`, **not resolved**.
- **No retry policy.** Retrying to obtain agreement is **forbidden**; the attempt count is recorded so the pattern is visible. **Never** (`kernel-cli.md` §7).
- **No escalation ladder.** "Could not" escalation belongs to the Validator, `S2-T09` (Plan 2).
- **No verification on read.** The *outcome* of a missing artifact is `E05-05`'s check; the *consequence per class* is this issue's.

**Effort**
**M** — one classification with two distinct consequences, one of which (`never regenerate`) is an invariant whose test must fail when broken; needs a fixture that carries a sampled artifact rather than a plain unit test (`wbs.md` §7).

**Owner**
**Kernels** — `docflow/kernels/determinism.py` (`wbs.md` §8).

**Frozen contract touched**
**Freezes** `plans/README.md` §3, Plan 1 row: *the determinism classes*. Plan 2's escalation ladder is expressed entirely in these terms.

---

### `E05-04` — implements `S1-T09`

**Title**
Typed slots (`cpu`/`gpu`/`remote`) + barriers (dependency on a set) + unit-contained failure.

**Context**
Two failure modes at scale: one bad unit aborting an 11k-file run, and a stage whose result is only meaningful once *several* predecessors completed starting too early. This issue adds the scheduling vocabulary that makes both expressible — and it keeps the failure *contained*, so a run continues and reports the failing unit rather than dying and losing the accounting.

**Deliverable**
`docflow/kernels/orchestrator.py` (continuation of `E05-01`'s file)

**Depends on**
`S1-T07` — **intra-epic**. Externally: E02, E03 via `E05-01`.

**Acceptance criteria**
- [ ] Three typed slots exist: `cpu`, `gpu`, `remote`.
- [ ] A unit failing **does not abort the run** — the remaining units complete and the failed unit is reported with its reason.
- [ ] A **partial barrier set does not release**; the barrier releases when **every** member is terminal.
- [ ] A barrier whose members are all terminal releases exactly once, and not before the last member is terminal.
- [ ] Work exceeds neither the `--jobs` bound for `cpu` nor the declared `gpu`/`remote` bounds.
- [ ] `gpu` is bounded to **one** in-flight generation per device — the declared simplification, not a discovered limit.
- [ ] A unit's failure is reported against **that unit**, not against the run.
- [ ] A synthetic graph test exercises a failing unit alongside succeeding ones.

**Test / evidence**
- `plan-01-kernels.md` §8 — synthetic graph test; partial-barrier release test; unit-contained-failure test. Requirements **FR-07**, **NFR-04**.
- `kernel-cli.md` §9 (K1) — `orchestrator run` accepts `--jobs` and `--slots cpu=n,gpu=n,remote=n`; both are `now`.
- `plan-01-kernels.md` §6 step 4 — the happy path must show every stage of every unit terminal in `run.json`; a stage silently absent from `stages` is the wrong result this guards against.
- `wbs.md` §6.1 — `S1-T09` is on the serial spine because *"the corpus run is impossible without them"*.
- Plan 3 consumption: `S3-T11` (*"Slot and resource policy for the corpus"*) depends on `S1-T09` and `S1-T15`.

**Out of scope for this issue**
- **No GPU competition policy.** `gpu = 1` is a **declared simplification**: concurrent OCR and generation compete for VRAM on one device and the competition policy is undefined. `plan-01-kernels.md` §12 open decision **#7** — carried here, **not resolved**. It becomes load-bearing at Plan 3's corpus run, so the answer is needed before `S3-T11`, **not** before `S1-T19`. `# TODO: [MVP]`: per-device slot policy beyond `gpu=1`.
- **No corpus-scale policy.** `DOCFLOW_JOBS`, disk policy and `keep_alive` are `S3-T11`/`S3-T12` (Plan 3).
- **No distributed execution.** `remote` is a typed slot, not a scheduler across machines. `# TODO: [RELEASE]`.
- **No retry queue inside the orchestrator.** The Catalog's retry queue is `S2-T12` (Plan 2); `--retry-queue`/`--retry` stay deferred. `# TODO: [MVP]`.

**Effort**
**M** — three interacting concerns (slots, barriers, contained failure) each with a distinct test, one of which (partial-barrier release) is an ordering assertion rather than a value check (`wbs.md` §7).

**Owner**
**Kernels** — `docflow/kernels/orchestrator.py` (`wbs.md` §8).

**Frozen contract touched**
**Consumes** `plans/README.md` §3, Plan 1 row — the descriptor shape and the 7 durable states. Adds no new kernel-boundary type: a slot and a barrier are scheduling attributes, not boundary types.

---

### `E05-05` — implements `S1-T10`

**Title**
Mandatory verification on every ledger read, with **no flag**.

**Context**
A `done` stage whose artifact was deleted by hand is not done. If verification has to be *requested*, then the one time it matters — the time nobody remembered to ask — it does not happen, and the stage is skipped as complete. This issue makes the check an **outcome of reading**, so there is no code path that returns a ledger without it.

**Deliverable**
`docflow/kernels/orchestrator.py` (continuation of `E05-01`'s file)

**Depends on**
`S1-T07` — **intra-epic**. Externally: E02, E03 via `E05-01`.

**Acceptance criteria**
- [ ] A `done` stage whose artifact was **deleted** is treated as **incomplete** on the next read — **with no flag passed**.
- [ ] Every ledger read reports the **verification outcome alongside the ledger**; a ledger is never returned without a verification result.
- [ ] **No code path exists that skips the check** — not a fast path, not a `--force` path, not an internal caller's shortcut.
- [ ] There is **no `--verify` flag** and **no ledger-trust `verify` subcommand**, on either surface, in any stage — asserted by the `E07-02` contract test.
- [ ] The check reads the store, not a cached copy of the ledger's own claim.
- [ ] `store ledger-read` and `orchestrator ledger-read` report the **same** verification outcome (`kernel-cli.md` §9).
- [ ] The `artifact_missing` code is what a deleted artifact produces (exit `2`, `kernel-cli.md` §5).

**Test / evidence**
- `plan-01-kernels.md` §7b row 4 — *"Verification on every ledger read, no flag"*: delete a `done` stage's artifact, read again; breaking it looks like *"a code path returns a ledger without verifying it; a `--verify`-shaped escape appears"*.
- `plan-01-kernels.md` §8 — AC *Verification is not optional*; AC *Resume after a forced kill*. Requirement **FR-05**.
- `plan-01-kernels.md` §3, acceptance scenario *Verification is not optional* (`prd.md` §8) — closes at **`S1-T10`**, asserted through `S1-T19` step 9 (`plan-01-kernels.md` §7c).
- `plan-01-kernels.md` §6 step 9 — *"Interrupt #3 — delete a done artifact"*: remove one `done` stage's artifact by hand and read the ledger again; the correct result is *treated as incomplete and re-run*; the wrong result is *skipped as complete — AC Verification is not optional fails silently if this passes*.
- `plan-01-kernels.md` §3, evidence table — *"A `done` stage whose artifact was deleted by hand → treated as incomplete on the next read, **with no flag passed**"*; guarded against: skipped as complete (`ADR-006`).
- `kernel-cli.md` §9 (K1) — *"There is no `verify` subcommand and no `--verify` flag. Verification is an **outcome** of reading a ledger, never a request."* `ledger-read` therefore always reports the verification outcome. **`store verify <sha256>` is different and legitimate** — it checks one artifact's bytes against its hash and says nothing about ledger trust.
- `plan-01-kernels.md` §13, Track 2 — the *"Mandatory verification"* golden artifact is a deleted `done` artifact, and it must fail when the stage is skipped as complete with no flag passed.

**Out of scope for this issue**
- **No `--verify` flag and no ledger-trust `verify` subcommand.** **Never** (ADR-006, `kernel-cli.md` §9/§14, `plans/README.md` §2 non-negotiable 2).
- **No `--no-validate` and no skippable validation.** **Never** (ADR-002, `prd.md` FR-18).
- **No sampling/spot-check optimisation.** The check runs on **every** read. A cheaper probabilistic check is a decision that cannot be taken here. `# TODO: [RELEASE]`.
- **No artifact-verification semantics.** K7's `verify(artifact) -> bool` — one artifact's bytes against its hash — is `E02-01`'s and is a different concept, deliberately named differently (`kernel-cli.md` §9, K7).
- **No evidence-missing consequence.** A missing *sampled artifact* reports `failed` with an evidence-missing reason; that consequence is `E05-03`'s. This issue supplies the check that detects the absence.

**Effort**
**S** — a single concept with a straightforward test (delete a file, read, assert incomplete). The cost is in the *absence* guarantee — no code path may skip it — which is checked by the contract test rather than by a fixture (`wbs.md` §7).

**Owner**
**Kernels** — `docflow/kernels/orchestrator.py` (`wbs.md` §8).

**Frozen contract touched**
**Consumes** `plans/README.md` §2 non-negotiable 2 and the fixed-decisions row *"There is no `--verify` flag and no `--no-validate` flag, in any stage, on either surface"*. Also consumes the closed `reason.code` set (`artifact_missing`, `evidence_missing`).

---

## §4 Epic close condition

E05 is **`done`** when:

1. all five issues are `done`, and
2. the capability is **demonstrable**, from outside the process: a 3-stage synthetic graph runs over N units; `rm run.json` followed by `manifest-rebuild` reproduces it from the ledgers alone through **both** doors; a kill mid-stage leaves `running`; a crash injected between write and rename leaves `done` absent; a deleted `done` artifact is treated as incomplete with no flag; and a deleted sampled artifact reports `failed` without producing a fresh sample.

**Does E05 gate `S1-T19`?** **Yes, directly and heavily.** Two of its issues are named in `S1-T19`'s dependency set — `S1-T09` and `S1-T10` — making E05 → E08 a **direct inter-epic edge**. Indirectly, `S1-T06` and `S1-T07` are links 6 and 7 of the 9-link serial spine and `S1-T18`/`S1-T19` sit behind them. E05 owns the largest share of the gate's riskiest assertions.

---

## §5 Traceability

| Issue | `wbs.md` task | FR / NFR (`traceability.md` §4) | Gap? | Evidence of the mapping |
|---|---|:---:|---|
| `E05-01` | `S1-T06` | **FR-11**, **NFR-09** | no | `rebuild_index()` reproduces `run.json` from ledgers; row 16; `jq`-readable output |
| `E05-02` | `S1-T07` | **FR-03**, **FR-04**, **NFR-02** | no | row 1; injected-crash invariant test; `S1-T19`'s at-most-one-stage assertion |
| `E05-03` | `S1-T08` | **FR-09** | no | AC *A sampled artifact is evidence, not a cache* |
| `E05-04` | `S1-T09` | **FR-07**, **NFR-04** | no | synthetic graph test; partial-barrier release test; unit-contained-failure test |
| `E05-05` | `S1-T10` | **FR-05** | no | AC *Verification is not optional*; AC *Resume after a forced kill* |

No issue in E05 has an empty mapping. `traceability.md` §5 places `S1-T01`–`S1-T10` in the orchestrator/store/ledger spine group.

---

## §6 Risks

From `plan-01-kernels.md` §9 only:

| Risk | L | I | Why it touches E05 | Mitigation carried by this epic |
|---|:---:|:---:|---|---|
| **Sampled artifact regenerated on resume**, silently changing the result | M | H | `S1-T08` **is** this row, and the resume decision is taken by the scheduler this epic builds. | The orchestrator reads the determinism class; missing evidence → `failed`; retrying to agreement is forbidden and attempts are counted. Proven by AC *A sampled artifact is evidence, not a cache*. |
| **Manifest drift** — `run.json` disagreeing with the ledgers | M | M | `S1-T06` **owns the mechanism**. A manifest that is authoritative drifts by construction. | The manifest is derived and rebuildable; ledgers are authoritative; verification on every read. (`S3-T07`, Plan 3, owns the shape and location — deviation D7.) |
| **`--repeat` used as retry-until-agreement** in the harness | L | H | The prohibition is enforced by the orchestrator recording an **attempt count** — which is this epic's mechanism, consumed by the harness suite. | Documented prohibition (`kernel-cli.md` §7); the attempt count makes the pattern **visible** if it happens. `S1-T22` asserts the *prohibition*, not merely the outcome. |

**Explicitly excluded from this epic, stated rather than implied.** The §9 rows *model resolved by capability* (`E04-07`), *the CLI lab surface drifts* (`E07-02`) and *lab fixtures drift* (`E07-03`) do not touch E05's issues.

**Open decisions carried, not resolved:**

| `plan-01-kernels.md` §12 | Question | Touches in E05 | Effect if deferred past Stage 1 |
|---:|---|---|---|
| **#6** | Whether a sampled artifact may ever be regenerated, with the new observation recorded | `S1-T08`, the gate's AC *A sampled artifact is evidence, not a cache* | Stage 1 fixes *"never regenerate"*. Relaxing it later is a **policy** decision that would change `S1-T08`'s done-when and therefore re-open this gate — it cannot be done from Plan 2 |
| **#7** | How many GPU slots exist, and whether the slot model is enough | `S1-T09` (`gpu` bounded to 1 per device) | `gpu = 1` is a declared simplification. It becomes load-bearing at Plan 3's corpus run, so the answer is needed before `S3-T11`, not before `S1-T19` |

Open decisions **#5** (Docling's determinism class) touches `S1-T14` and `S1-T08` together: it is carried in `E04-04` for the adapter and here for the consequence, and it is not resolved anywhere. **#1**, **#2**, **#3** touch `S1-T20`/`S1-T21`/`S1-T22` (`E07`); **#4** touches `S1-T04`/`S1-T05` (`E03`).
