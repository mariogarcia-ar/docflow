# E05 — K1 Orchestrator — dispatch, durability, scheduling

| Field | Value |
|---|---|
| Epic ID | **E05** |
| Capability | K1 Orchestrator: unit/stage/graph dispatch, the 7 durable states, determinism classes, typed slots and barriers, mandatory verification |
| Issues | `E05-01` (`S1-T06`) — **`done`** (§3) · `E05-02` (`S1-T07`) — **`done`** (§3) · `E05-03` (`S1-T08`) — **`done`** (§3) · `E05-04` (`S1-T09`) — **`done`** (§3) · `E05-05` (`S1-T10`) — **`done`** (§3) |
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

**Status — `done`**

| # | Criterion | Status |
|---:|---|---|
| 1 | `docflow/kernels/orchestrator.py` exists and models unit / stage / graph / ledger / manifest as distinct concepts | ✅ met — five declarations (`Stage`, `Graph`, `Unit`, `Descriptor` + the manifest functions); the ledger is K7's and is *used*, not re-modelled |
| 2 | A 3-stage synthetic graph runs over N units with N > 1, dispatching a stage only once its declared needs are satisfied | ✅ met — `test_a_three_stage_graph_runs_over_n_units` runs the `acquire → transform → persist` graph over two units |
| 3 | A stage whose needs are unmet is **not** dispatched | ✅ met — `test_a_stage_whose_need_produced_no_artifact_is_not_dispatched` asserts both the blocked report and that the operation was never called |
| 4 | Dispatch decides using the cache key: a stage whose key is already terminal is not re-run | ✅ met — `is_terminal(state) and record.cache_key == key`; falsified twice (state-only, and key-compared-to-itself) |
| 5 | `run.json` is derived and carries `state`, `totals`, `stages`, `outcomes`, `inflight`, consistent with the ledgers | ✅ met — `test_the_manifest_carries_the_five_reported_keys` |
| 6 | `rebuild_index()` reproduces `run.json` from the ledgers alone — checked by deleting it and rebuilding | ✅ met, and **stronger than the criterion asks** — see the note below |
| 7 | `rebuild_index()` is the only authority; K7's `rebuild_manifest()` delegates to it | ⚠️ **half met** — `rebuild_index()` is the only authority in the code that exists. K7's `rebuild_manifest()` still refuses (`engine_unavailable`), and its refusal message names `E05-01` as the missing dependency. Wiring the delegation is a **one-line change in `adapters/store.py` plus a test**, and it is deliberately left to `E07-02` (`S1-T21`), which owns the composition root: the adapter must not learn about K1 from a kernel-layer import. |
| 8 | `run.json` is `jq`-readable | ✅ met — plain `json.dumps(..., indent=2)`; the round-trip tests parse it with `json.loads` |
| 9 | The orchestrator executes a graph it did not interpret: no stage name, parameter or field contains a domain noun | ✅ met — `test_no_public_identifier_names_a_domain_concept`, plus the AST guard `test_the_orchestrator_imports_nothing_above_the_kernel_layer` |
| 10 | The orchestrator reads a descriptor whose stages are kernel ops only; a descriptor naming a pipeline code is not a shape it accepts | ✅ met — **and by shape rather than by vocabulary**: the stage and descriptor key sets are closed, so `{"pipeline": …}` is refused as an unknown key (`test_a_descriptor_carrying_an_unknown_key_is_refused`) |

**On #6 — the check is sharper than the criterion's wording.** Deleting the manifest and rebuilding it proves a rebuild *works without* one; it does not prove a rebuild *ignores* one. A rebuild that consulted an existing `run.json` would reproduce whatever that file said, so a hand-edited or stale manifest would become authoritative simply by existing — which is precisely the drift this issue exists to prevent. So the manifest is replaced with a **poison** value that only a lying rebuild could return, and `test_rebuild_index_ignores_an_existing_manifest_entirely` asserts the derived answer wins. The mutation `M2: let rebuild_index trust an existing run.json` is what found the gap: the deletion-based test did not falsify it.

**A dependency this issue exposed, and the artifact change it required.** Criterion 4 asks dispatch to decide *using the cache key*, which means the key a stage ran under has to be **on disk** to compare against — and `StageRecord` (`E02-02`, closed) carried only `(state, artifact_sha256, reason_code)`. Three artifacts pointed the same way and none of them had been reconciled with E02's implementation: `prd.md` **FR-08** (*"every stage result is keyed by the full cache key"*), `sad.md` §5 (completion claims must go *visibly* stale when the registry changes) and `FR-03`'s `stale` state (*"kept deliberately over changed inputs"* — meaningless without the key it was kept over).

`StageRecord` therefore gained **`cache_key: str | None`**, required for a terminal outcome (`done`, `failed`) and permitted-not-required otherwise, because a stage that has not been dispatched under a key has none to record. The change is recorded in `epic-02-k7-store-ledger.md` §3. It re-opens no frozen artifact: what `plans/README.md` §3 freezes is the **seven states**, not the record's field set. The port's `ArtifactStore` signature grew with it (it is an exact mirror of the kernel), so `ports/store.py`, `adapters/store.py` and the port contract test moved together — and `test_no_port_parameter_carries_a_default_value` correctly refused the `begin` default that a first cut introduced, which is why `begin` now takes the key with no default either.

**What is deliberately not asserted here.** `begin` *is* called before the work starts, because that is the only honest place for it — but the *ordering* surviving a kill is `E05-02`'s, and no test in this issue claims it. Likewise the read path verifies nothing, so `E05-05` adds exactly one check rather than removing a seam.

**Effort**
**L** — five concepts, a derived-manifest invariant, a sealed descriptor shape, and an artifact change discovered by the work rather than named in the plan.

**Test / evidence**
- `tests/kernels/test_orchestrator.py` — **49 tests**, all green.
- `tests/kernels/mutation_orchestrator.py` — **13 mutations, all falsified.** M2 was a **survivor on the first run** and is reported rather than rewritten: the mutation that landed was semantically equivalent to the original, which proves nothing, so it was replaced with a real one (rebuild trusting `run.json`) — which then failed a test that did not exist, and the test was added. M5, M7 and M8 also reported `SURVIVED` for a harness reason rather than a test gap: the cited names omitted pytest's parametrization suffix (`[extra0]`, `[done]`, `[cache_key]`). **A mutation citing a nonexistent test name still reports SURVIVED** — the same trap `E04-02` recorded.
- `tests/adapters/mutation_store.py` — re-run after the signature change: **20 mutations, all falsified.**
- `tests/kernels/test_store.py` — 109 tests; `tests/adapters/test_store.py` — 26; `tests/ports/` — green.
- All four QA gates green over the whole tree: `pytest` (731 passed), `ruff check`, `ruff format --check`, `pylint src tests`.
- `plan-01-kernels.md` §8 — `rebuild_index()` reproduces `run.json` from ledgers; row 16; `jq`-readable output. Requirements **FR-11**, **NFR-09**, plus **FR-08** through the record change.
- `kernel-cli.md` §11 **row 16** — `orchestrator manifest-rebuild O` after `rm O/run.json`; the mechanism is asserted, the command wrapper is `E07-02`'s.

**Open state carried forward.** `kernel_cli/main.py` now reports K1 as available (its module landed), so `ALWAYS_AVAILABLE_KERNELS` was widened **deliberately** with the reason recorded at the constant: K1 needs no engine, so the module existing is the whole precondition. This is the moment the guard exists to force someone to look at.

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

**Status — `done`**

| # | Criterion | Status |
|---:|---|---|
| 1 | Exactly **seven** durable states exist; no eighth is writable and none is missing | ✅ met — `DURABLE_STATE_ORDER` (E02) refuses an eighth by construction |
| 2 | `running` is written **before** the work starts — demonstrable by killing a stage mid-work | ✅ met — and demonstrable **without** a kill, see the note below |
| 3 | A kill mid-stage leaves the ledger reading `running` — not `pending`, not `done` | ✅ met — `begin` is the first thing `_dispatch` does |
| 4 | *"Never `done` about a non-durable artifact"* holds under an injected crash | ✅ met — E02's `commit`-requires-`put` ordering, unchanged |
| 5 | The injected-crash test **fails** if the ordering is moved | ✅ met — `M1`/`M2` in the new harness redden it |
| 6 | A resumed run re-runs **at most one stage per in-flight unit** | ✅ met — a stage terminal for its key is skipped, so at most the interrupted one re-runs |
| 7 | A stage that completed before the kill does **not** re-run | ✅ met |
| 8 | No code path writes a state other than one of the seven, and none writes `running` after the work started | ✅ met — `_dispatch` writes it first, in one place |

**On #2 — the criterion asks for a kill, and a kill is not the only way to falsify it.** The property is *the order of two writes*, and a test that kills a process proves it only by inference: afterwards, both orderings leave the same record. So the ordering is read **from inside the operation** — a recorder that consults the ledger while the stage's work is executing, which is the one vantage point from which *before* and *after* are distinguishable. `M1` (moving the `begin` after the dispatch) and `M2` (dropping it) both redden that test, which is what `plan-01-kernels.md` §7b row 3 requires.

**The control: how `pause` reaches a run already in flight.** The criterion for this issue is the state ordering; the *interruptions* run through it, and a scheduler that cannot be interrupted cannot be observed to resume. So a run's control is a file at its output root, polled **before every stage**:

- `paused` and `stopped` both hold; the difference is the *signal* (§9 of the epic table names K1's `pause`/`stop` as port methods).
- An **unrecognised** control state is refused, never read as `running`: silently resuming a run somebody asked to hold is the failure the file exists to prevent.
- It is read **before the first unit** as well as between stages. A per-unit-only check would let a pause land a whole unit late, which is indistinguishable from *let the job finish*.
- `read_control` on an absent file returns `running` — **the only default in the module**, and it is about an operator's silence rather than about a value the system would otherwise have to produce.

**Two reporting defects the work found, both by a failing test rather than by reading.**

1. **A run with no ledgers read as `complete`.** A pause taken before the first stage leaves the output root empty, and *no unfinished units* answered *finished* — the same class of error as a `done` claim about bytes that do not exist, one level up. The run state now consults the ledger **count** first.
2. **A paused run and a crashed run were indistinguishable.** Both leave unfinished work; only one has an operator's request behind it. The run state gains `holding`, and it is a **third vocabulary** — the seven durable states describe a *stage*, and a value no ledger may carry has no business in `run.json`.

**The attempt count, which this issue's criterion 8 implies and `E05-03` will consume.** `StageRecord` gained `attempts`, **derived** from the transition rather than passed by a caller: `running` opens an attempt, an outcome closes the one it opened, and an outcome arriving from `pending` counts one because the stage was still run. A count a caller increments is a count somebody forgets to increment, and the one time it matters is the retry loop it exists to make visible — `kernel-cli.md` §7 forbids *retry-until-agreement* for a sampled kernel, and `plan-01-kernels.md` §9 says the prohibition is enforceable only if the pattern can be **seen**. It is reported in `run.json` under `attempts`, and it **enforces nothing**: recording is this issue's, policy is not.

**A real duplication, extracted rather than suppressed.** The manifest rebuild originally re-listed the ledger record's fields, which Pylint flagged as `duplicate-code` against the ledger writer. The finding was **correct**: a second copy of the field list is a field that reaches the ledger and not `run.json` — a record an operator cannot see. `StageRecord.as_mapping()` is now the single source, read by both.

**Effort**
**L** — a load-bearing invariant, an interruption mechanism, and a count whose rule had to be derived rather than declared. Three of the four defects above were found by tests or by the mutation harness, not by reading.

**Test / evidence**
- `tests/kernels/test_orchestrator.py` — **65 tests**, all green. The ordering is falsified by `test_the_ledger_reads_running_from_inside_the_operation` and `test_the_cache_key_is_recorded_before_the_work_too`.
- `tests/kernels/mutation_ordering.py` — **15 mutations, all falsified.** Four survivor investigations are recorded in the harness's own docstring; two were **ambiguous anchors** (a repeated literal landing in the wrong function) and one was a **real gap** — nothing exercised the branch that consults the control *after* establishing that a unit is unfinished, so `test_a_run_paused_with_work_half_done_reports_holding` was added. The harness now **refuses an ambiguous anchor** rather than scoring it.
- `tests/kernels/test_store.py` — 109 tests, including the count rule and two new hand-edited-ledger corruptions (an attempt state claiming it never ran; a negative count).
- `plan-01-kernels.md` §6 steps 7–8 — `stop --force` mid-`transform` then `ledger-read` → `running`; then resume → **at most one stage per in-flight unit**. Requirements **FR-03**, **FR-04**, **NFR-02**.
- `kernel-cli.md` §11 **rows 1 and 2** — both `now`, both Stage 1 gate rows. The *procedures* are driven here; the CLI invocations are `E07-02`'s.
- All four QA gates green: `pytest` (794 passed), `ruff check`, `ruff format --check`, `pylint src tests`.
- `tests/kernels/mutation_orchestrator.py` — re-run after this issue's refactor and **re-anchored**: making the ledger writer delegate to `as_mapping()` moved one anchor, which reported as a survivor until it was fixed. The lesson is recorded in the harness.

**Open state carried forward.** `store._atomic_write` is reached privately for the control file. `# TODO: [MVP]`: a narrow public `store.write_json_atomically` that both the ledger writer and this call — a widening of K7's surface, which belongs to `E02`/`E07-02` and is deliberately not taken from here.

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
- **No `resume` verb on the *product* surface.** Recovery there is *"run it again"*: `docflow run` after an interruption continues from the exact stage and there is no separate product `resume` verb (`FR-01`, `FR-02`, `plan-01-kernels.md` §3). **Never** a new product verb. This prohibition is scoped to `docflow`, not to the orchestrator: the lab surface exposes `docflow-kernel orchestrator pause <job-id>` / `resume <job-id>` as a **port method**, listed `now` in `kernel-cli.md` §9 (K1 row 5) and required by `plan-01-kernels.md` §13 Track 4's *one subcommand per port method* rule. The absence that `FR-01` asserts is on the product surface; asserting it absolutely here would forbid a command `E07-02` must dispatch.
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

**Status — `done`**

| # | Criterion | Status |
|---:|---|---|
| 1 | Exactly three determinism classes exist: **deterministic**, **sampled**, **external** | ✅ met — `CLASS_NAMES`; a fourth is refused by a test that asserts the tuple |
| 2 | A **deterministic** artifact is recomputable — byte-identical, its hash the evidence | ✅ met — the one class whose absence yields `recompute=True` |
| 3 | A **sampled** artifact with a missing file reports **`failed`** with an `evidence_missing` reason | ✅ met |
| 4 | A sampled artifact is **never regenerated**; a test would detect a fresh sample reported as `done` | ✅ met — and the strongest available form, below |
| 5 | An **external** artifact's missing evidence is a typed outcome, never asserted reproducible | ✅ met — same consequence as `sampled`; a later call is a new observation, not a correction |
| 6 | The class is **read from the artifact's producing kernel**, not guessed, defaulted or set per run | ✅ met — one table keyed by kernel, and an unknown kernel is **refused** |
| 7 | Deleting a sampled artifact proves `failed` and **no fresh sample**; the test fails if regeneration occurs | ✅ met — `test_a_done_stage_whose_sampled_artifact_is_deleted_fails` |
| 8 | The recorded attempt count is visible, so *retry until agreement* would be detectable | ✅ met — `E05-02` recorded it; `M1` here is the mutation that would have hidden it |
| 9 | The classes match `kernel-cli.md` §7 | ✅ met, asserted against a copy of the artifact's table rather than the table itself |

**On #4 — *never regenerated* cannot be proven behaviourally, so the absence is asserted structurally.** A behavioural test can only show that the paths it takes do not regenerate; it cannot show there is no path that does. So two assertions carry the claim: the module exposes **no function whose return type mentions ``Artifact``** — it *decides*, it does not produce — and `MissingEvidence` has no member that could carry a value, so *a fresh sample reported as `done`* is not a shape the decision can express. `M1` (letting `sampled` take the recompute branch) reddens six tests, which is what `plan-01-kernels.md` §7b row 5 asks for.

**Where the class is declared, and why it is not anywhere else.** An adapter cannot carry it: the port declares no such member, and adding one would re-open `E04-01`'s gate. A descriptor must not: a class **set per run** is precisely what the criterion forbids. So it is a fact about the **kernel**, in one table, and the orchestrator reads it. The alternative — discovering the class by running the operation twice and comparing hashes — is the *regeneration* the issue exists to prevent, performed to decide whether it is allowed.

**An unknown kernel is refused, not defaulted.** Both available defaults change results: `deterministic` makes the system regenerate a sampled artifact, and `sampled` makes it discard recomputable work. Refusing names the real problem. `M5` and `M6` are the two mutations that prove the refusal is not a fall-through.

**A cross-module check, and why it is here rather than in `E04-07`.** `test_the_kernels_resolution_declares_are_all_classified` asserts that every kernel `resolution.py` can resolve to has a class. A capability that resolved and then had no resume behaviour would fail at the worst possible moment — the one after a crash. `M15` proves the assertion is not vacuous.

**The three steps a caller would otherwise have to remember, composed.** :func:`resume_decision` reads the class from the producing kernel, asks whether the artifact is still there, and applies the class's consequence. Skipping the first step is guessing; skipping the second is trusting a claim about bytes. A stage that is not `done` has no artifact claim and answers None — a `running` stage has no artifact to lose, and asking would report *missing evidence* about a stage that never claimed any.

**Effort**
**M** — one classification with two distinct consequences, and an invariant whose test had to be *structural* because a behavioural one cannot prove an absence.

**Test / evidence**
- `tests/kernels/test_determinism.py` — **33 tests**, all green.
- `tests/kernels/mutation_determinism.py` — **15 mutations, all falsified.** Five survivors were investigated, each with a different cause, and **one was a real test defect**: `test_the_reason_code_is_in_the_closed_set` asserted that the module's *constant* was in the closed set, which any valid code satisfies — so `M14`, which changed the constant to a **different valid code**, went unnoticed. It now asserts the code an actual consequence produces. Two more were the **parametrized-suffix** trap; one an assertion against a **module constant that the mutation also moved** (fixed by asserting the literal); and one was an expectation that could not fail, corrected rather than left as a citation.
- `plan-01-kernels.md` §7b row 5 — *"A sampled artifact is never regenerated"*; breaking it looks like *"the stage re-runs and reports `done` with a fresh sample, changing the result while reporting success"*. Requirement **FR-09**.
- `plan-01-kernels.md` §3, acceptance scenario *A sampled artifact is evidence, not a cache* (`prd.md` §8) — closes at **`S1-T08`**; asserted through `S1-T22`, which is `E07-03`'s.
- `kernel-cli.md` §7 — the class table, and the prohibition on `--repeat` as retry-until-agreement.
- All four QA gates green: `pytest` (827 passed), `ruff check`, `ruff format --check`, `pylint src tests`.
- The four earlier harnesses re-run and still falsify: `mutation_ordering` 15, `mutation_orchestrator` 13, `mutation_resolution` 18, `mutation_store` 20.

**Open state carried forward.** `plan-01-kernels.md` §12 open decision **#6** (whether a sampled artifact may ever be regenerated, with the new observation recorded) is **carried, not resolved**: Stage 1 fixes *never regenerate*, and relaxing it would change this issue's done-when and re-open this gate. Open decision **#5** (whether a pinned Docling is in fact deterministic) is likewise carried — K4 reports `sampled` per `sad.md` §4.

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

**Status — `done`**

| # | Criterion | Status |
|---:|---|---|
| 1 | Three typed slots exist: `cpu`, `gpu`, `remote` | ✅ met — `SLOT_NAMES`, a **closed** set (a fourth name is refused), asserted as an equality rather than a membership so `"cpu" in SLOT_NAMES` cannot pass against a module that also accepts `tpu` |
| 2 | A unit failing **does not abort the run** — the remaining units complete and the failed unit is reported with its reason | ✅ met — `test_one_unit_failing_leaves_the_other_unit_complete`. **Dispatch was already sequential**, so the invariant held before this issue; what was missing was the *reporting*, which is criterion 7 |
| 3 | A **partial barrier set does not release**; the barrier releases when **every** member is terminal | ✅ met — the blocked branch of `_advance` *is* the barrier: `_upstream_hashes` returns None unless every member is terminal with an artifact that still verifies. `test_a_partial_barrier_set_does_not_release` asserts the join's operation was **never called** |
| 4 | A barrier whose members are all terminal releases exactly once, and not before the last member is terminal | ⚠️ **half met** — *releases* and *not before the last member* are met (`test_a_partial_barrier_set_does_not_release` + `test_a_complete_barrier_set_releases_exactly_once`). The *exactly once* half holds **within and across runs** for the reason `E05-01` established: the join is terminal for its key on the second pass (`test_a_released_barrier_is_not_released_again_by_a_second_run`). Because dispatch is sequential, no observer can catch the barrier mid-release, so *once* is asserted as *idempotent* rather than as *one dispatch under concurrency* |
| 5 | Work exceeds neither the `--jobs` bound for `cpu` nor the declared `gpu`/`remote` bounds | ⚠️ **met by construction, and the construction is stated rather than claimed** — see the note below |
| 6 | `gpu` is bounded to **one** in-flight generation per device | ✅ met — and **enforced at construction** (`SlotBounds` refuses `gpu > 1`), not merely documented. `M12` is the mutation |
| 7 | A unit's failure is reported against **that unit**, not against the run | ✅ met — `RunReport.failed` is a tuple of `(unit, stages)`, and the stages named are those that did **not reach a successful outcome**: the one that reported the reason *and* the work it stopped |
| 8 | A synthetic graph test exercises a failing unit alongside succeeding ones | ✅ met — `test_one_unit_failing_leaves_the_other_unit_complete` runs the three-slot graph over two units with `read` failing in both |

**On #5 — why the bound is a refusal rather than a semaphore.** The PoC scheduler dispatches **one stage at a time**, so the in-flight level is at most one, and one is within every bound a caller can legally declare. A semaphore here would be an object that never blocks, and the criterion *"work exceeds neither bound"* would pass against it whether or not the bound were read. So the bound is enforced where it **can** be violated, which is three places, each with a distinct test and mutation:
- a slot declared with **zero capacity** is refused at validation, before the first ledger is touched (`M13`, `M15`);
- a **negative** capacity is refused at construction (`M11`);
- a `gpu` bound above one is refused, because the sharing policy is an open decision (`M12`).

The consequence is recorded honestly: **there is no test that observes a concurrent run being throttled, because there is no concurrent run.** If `E05-04`'s criterion is read as requiring one, it is unmet as written; the *class* of event it guards against (work admitted against a bound that was never read, or a bound the deployment cannot honour) is what the three refusals cover.

**On #4 — the limit that is stated rather than papered over.** `test_a_released_barrier_is_not_released_again_by_a_second_run` proves idempotency, which is the observable a sequential scheduler has. It is **not** the same claim as *a barrier cannot release twice under concurrency*, and no test here asserts that one.

**Where the guard around the failure measurement is reachable, and where it is not.** `_run_unit` measures a unit's unfinished stages only when the pass was **not** held, so a pause is not reported as a crash. A control written *before* the run never enters `_run_unit` at all - so the guard is unreachable that way, and `M6` survived against a test that only asserted *nothing was driven*. The reachable case is a pause that arrives **between two stages of a unit**, which is also what an operator's `pause` actually does: `test_a_pause_that_arrives_mid_unit_does_not_report_the_unit_as_failed` has the *operation* write the control, the same mechanism the surface uses. With that test, `M6` is caught.

**A frozen contract, consumed additively.** `plans/README.md` §3 freezes *the descriptor shape* for Plan 1, so `slot` reaching a stage entry is a change to a frozen surface and is recorded as one. It is **additive**: a stage entry that names no slot is understood (defaults to `cpu`), the key is optional, and no existing descriptor stops loading. `_STAGE_KEYS` grows by the one key. The alternative - a per-run slot map - was rejected because a stage's resource is a property of the stage, not of the invocation, and a map would be a second place for the same fact.

**The manifest reports no slot, and that is the `rebuild_index` contract working.** A slot is an attribute of a *descriptor* stage and a bound belongs to a caller's invocation; neither is a fact about what happened, so neither can be read out of a ledger tree. Reporting them would make `rebuild_index` read the descriptor - the second authority `E05-01` exists to not have. `test_the_manifest_reports_no_slot_because_a_ledger_carries_none` asserts the *absence*, so a future addition is confronted rather than absorbed.

**Effort**
**M** — three interacting concerns (slots, barriers, contained failure) with a distinct test each, and one criterion (#5) whose honest answer required restating rather than satisfying.

**Test / evidence**
- `tests/kernels/test_orchestrator_slots.py` — **25 tests**, all green.
- `tests/cli/test_main.py` — **4 tests** for `_slot_bounds`, added because mutation `M16` survived against **no test at all**: the CLI's slot resolution was unreachable surface.
- `tests/kernels/mutation_slots.py` — **16 mutations, all falsified.** Four survived on the first run and **each had a different cause, three of them real defects in my own tests**: `M5` (an assertion that name-checked the failing stage but not the work it stopped), `M6` (an unreachable mutation, fixed by writing the test that reaches it), `M8` (caught by collection error, so the expectation was corrected to name the module), `M16` (a genuine coverage hole).
- `plan-01-kernels.md` §7b — *"a partial barrier set releases when every member is terminal"*; *"one unit failing does not abort the run"*. Requirements **FR-07**, **NFR-04**.
- `sad.md` §7.2 — the slot table, *"barriers are dependencies on a set"*, *"a failure does not deadlock the barrier"*, and the `gpu` bound of one.
- `kernel-cli.md` §8 — `--jobs`, `--slots cpu=n,gpu=n,remote=n` are in the allowed vocabulary; §9 (K1) — `orchestrator run` accepts both.
- All four QA gates green: `pytest` (907 passed), `ruff check`, `ruff format --check` (79 files), `pylint src tests`.
- **All eight harnesses re-run green**, which the `_run_unit` change required: `mutation_verification` 15, `mutation_cli` 18, `mutation_determinism` 15, `mutation_resolution` 18, `mutation_store` 20, `mutation_ordering` 15, `mutation_orchestrator` 13, `mutation_slots` 16. **No anchor drifted**, because every anchor the older harnesses mutate is in `_dispatch`, `_already_done`, `_upstream_hashes` or `rebuild_index` - all of which were left alone this time.

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

**Status — `done`**

| # | Criterion | Status |
|---:|---|---|
| 1 | A `done` stage whose artifact was **deleted** reads as **incomplete**, **with no flag passed** | ✅ met — `test_a_deleted_artifact_makes_its_stage_read_as_unverified`, and end to end in `test_a_run_re_dispatches_a_stage_whose_artifact_was_deleted` |
| 2 | Every ledger read reports the **verification outcome alongside the ledger** | ✅ met — `read_ledger` returns `Verified` (the ledger **and** the unverified map); `test_a_ledger_read_carries_its_verification_outcome`. `Verified` is a pair rather than a ledger with an optional field, so a caller *cannot* take the ledger without seeing the verdict |
| 3 | **No code path skips the check** — not a fast path, not `--force`, not an internal shortcut | ✅ met — `store.read_ledger` is reached from exactly **two** places, both in the verification layer, asserted structurally by `test_the_raw_ledger_read_is_reached_only_from_the_verification_layer` (AST); `M11` and `M12` are the mutations that would have added a third and a skipping parameter |
| 4 | There is **no `--verify` flag** and **no ledger-trust `verify` subcommand** on either surface | ✅ met — `test_the_module_offers_no_flag_shaped_way_to_skip_verification`; `M13` adds the operation and is refused |
| 5 | The check reads **the store**, not a cached copy of the ledger's own claim | ✅ met — `test_the_check_reads_the_store_not_the_ledgers_own_claim`; `M10` answers from the ledger's claim and is caught |
| 6 | `store ledger-read` and `orchestrator ledger-read` report the **same** verification outcome | ⚠️ **deferred to `E07-02` (`S1-T21`)**, which owns the dispatch of both surfaces — the shared function is what makes them agree (`docflow/kernels/orchestrator.py` is their one source), but no test in this issue can observe two CLI surfaces that do not yet dispatch |
| 7 | `artifact_missing` is what a deleted artifact produces | ✅ met — `test_the_unverified_code_is_the_closed_sets_artifact_missing` asserts the code a **consequence** produces, not the constant (`M9` changes the produced code and is caught) |

**Two defects the tests found, and neither was found by reading.**
1. **`read_ledger` read the ledger twice.** The first cut read the file to get the stages and then re-read it inside `_unverified_stages` — two reads can see two different byte sequences, so a ledger could be verified against *a different version of itself*. Fixed by reading **once** and verifying that ledger: `_unverified_stages(ledger, unit_dir)`.
2. **The store root was nested one level too deep.** Both `_operations` (the product surface) and the test `Recorder` passed `<unit>/artifacts` as the store root, so the store wrote under `artifacts/artifacts/`. Harmless while nothing read the tree back; adding verification made 14 tests fail at once and exposed it. Fixed to `call.unit_dir`.

**On #3 — the absence is asserted structurally, because a behavioural test cannot prove one.** A test can show that the paths it *takes* verify; it cannot show there is no path that does not. So the claim is carried by an **AST assertion**: `store.read_ledger` has exactly two call sites, and both are `verify_ledger` / `read_ledger` in the verification layer. A third read site anywhere in the module reddens the test. `Verified` being a value rather than an optional field is the second half: there is no shape in which a caller holds a ledger and no verdict.

**The three conditions of *may be skipped*, and why the third is the issue.** `_already_done(record, key, unverified, stage_name)` requires **terminal** *and* **same key** *and* **verified**. The first two are `E05-01`'s and `E05-02`'s; the third is what makes *verification is not optional* an **action** rather than a report. Without it a `done` stage whose artifact was deleted by hand is skipped as complete and the run reports success over bytes that are not there — the failure `ADR-006` and `plan-01-kernels.md` §6 step 9 both name. `M1` (skip a done stage for its key, verified or not) is that mutation.

**`unverified` is additive, never corrective.** The ledger's recorded states are returned as recorded; the manifest carries an **extra** key (`unverified`) naming the claims the run could not honour, and re-dispatches them. A run that silently *rewrote* a `done` to `pending` on read would destroy the evidence that the claim was ever made — and `E05-03`'s `stale` state exists precisely so a kept-but-invalidated result stays visible.

**A stage left both unverified and blocked must not lend its stale hash downstream.** `test_a_stage_left_unverified_and_blocked_does_not_lend_its_stale_hash` — an unverified stage's artifact hash is not posted as its output, so a dependant is blocked rather than fed a hash whose bytes are gone. `M6` (let an unverified need satisfy its dependant) is the mutation.

**A consequence of the refactor: the two older harnesses drifted.** Extracting `_run_unit`'s loop body into `_advance()` moved every anchor the two `E05-01`/`E05-02` harnesses mutated — a skip decision, an upstream check, a manifest line, a control poll. Five anchors were re-pointed and every mutation re-confirmed caught; the detail is in **§4**. This is the third time anchor drift has produced *survivors that were harness defects, not code defects*, and the lesson is recorded: **after refactoring a file under test, re-run every harness that mutates it — before believing any of them.**

**Effort**
**S** — a single concept with a straightforward test (delete a file, read, assert incomplete). The cost is in the *absence* guarantee, which is why it is checked by an AST assertion and a value shape rather than by a fixture.

**Test / evidence**
- `tests/kernels/test_orchestrator.py` — **10 new tests** (`test_a_ledger_read_carries_its_verification_outcome` … `test_the_check_reads_the_store_not_the_ledgers_own_claim`); the file holds **69**.
- `tests/kernels/mutation_verification.py` — **15 mutations, all falsified**, including the three that target the *absence* (`M11` a second read path, `M12` a skipping parameter, `M13` a ledger-trust `verify` operation).
- `plan-01-kernels.md` §7b row 4 — *"Verification on every ledger read, no flag"*: delete a `done` stage's artifact, read again; breaking it looks like *"a code path returns a ledger without verifying it; a `--verify`-shaped escape appears"*. Requirement **FR-05**.
- `plan-01-kernels.md` §6 step 9 — after interrupt #3, the correct result is *treated as incomplete and re-run*.
- `kernel-cli.md` §9 (K1) — *"Verification is an **outcome** of reading a ledger, never a request."*
- All four QA gates green: `pytest` (878 passed), `ruff check`, `ruff format --check` (77 files), `pylint src tests`.
- All seven mutation harnesses re-run green: `mutation_verification` 15, `mutation_cli` 18, `mutation_determinism` 15, `mutation_resolution` 18, `mutation_store` 20, `mutation_ordering` 15, `mutation_orchestrator` 13.

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

### Verification discipline — anchoring the harnesses after a refactor

**A survivor is either a code defect or a harness defect, and the second is silent.** `E05-05` extracted `_run_unit`'s loop body into a new `_advance()`, which moved the text five mutations anchored on: the skip decision (now `_already_done(...)`), the upstream check (now `_upstream_hashes(recorded, verified.unverified, stage)`), a `rebuild_index` line (now the verified read), and the per-stage control poll (now the loop head). Five anchors were re-pointed and every mutation re-confirmed caught; the two harnesses are back to **15/15** and **13/13**.

**This is the third time the same defect has appeared**, so it is a rule rather than an incident: **after refactoring a file under test, re-run every harness that mutates it — before trusting any of them.** The pattern of the trap is that a drifted anchor produces the *same output* as a mutation that was caught for the wrong reason, so the only safe reading is that an unre-anchored harness has proven nothing since the last refactor. The corollary, from `E05-03`: **an expectation that cannot fail is a citation, not a proof** — `M14` there survived against a test that asserted a *constant* was in a closed set, which any valid code satisfies.

**Re-anchoring is itself a mutation of the harness, so it is a source edit like any other.** Two failures this session, both mine: a tuple-shaped replacement with the wrong arity corrupted the mutation table, and a first re-anchor of `mutation_ordering`'s `M4` changed the mutation's *meaning* (from *poll the control too rarely* to *verify against a stale ledger*, which a test must not catch) while still printing `[SURVIVED]`. Both were caught by running the harness and reading the label against the anchor, not by reading the diff.

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
