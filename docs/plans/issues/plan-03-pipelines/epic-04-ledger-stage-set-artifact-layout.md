# E04 — Ledger stage set & the artefact layout

| Field | Value |
|---|---|
| Epic ID | **E04** |
| Capability | Ledger stage set & the artefact layout — the ledger records the stages the primitive implies and lists the rest in `not_applicable`; the three artefacts are distinguishable by suffix; the manifest is derived and rebuildable, never authoritative |
| Issues | `E04-01` (`S3-T03`) — status `todo` · `E04-02` (`S3-T07`) — status `todo` · `E04-03` (`S3-T10`) — status `todo` |
| Issue count | **3** |
| Owner layer | **Data** + **Surface** (`wbs.md` §8) — `S3-T03` on the ledger schema and writer (Data); `S3-T07`/`S3-T10` on the result/ledger/work layout (`docflow/cli.py`, Surface) |
| Wave span | **W3 → W4 → W5** |
| Effort total | **2 × M · 1 × S** |
| Source plan | [`../../plan-03-pipelines.md`](../../plan-03-pipelines.md) §2, §5 (`S3-T03`, `S3-T07`, `S3-T10`), §3 (the ledger, suffix and `run.json` evidence rows), §6 steps 7, 11, 13, §7b (the derived-manifest and suffix rows), §8, §12 #9, #10, §13 Track 3 |
| Depends on other epics | **E01** (`S3-T02` → `S3-T03`) · **E05** (`S3-T06` → `S3-T07`); entered from `S1-T03` and `S1-T06` (external) |

---

## §1 Objective

E04 delivers **the record of what happened and where it lives**. Three questions that look separate and are the same one: *which stages does this pipeline have* (`S3-T03` — the ledger stage set derived from the primitive, with everything else listed in `not_applicable` as a **fact** rather than an absence); *where do the three artefacts sit and what are they called* (`S3-T07` — `<name>.json` / `<name>.ledger.json` / `<name>.work/`, distinguishable by suffix alone, plus `run.json`'s shape and location); and *is `run.json` allowed to be believed* (`S3-T10` — presented as derived and rebuildable, never authoritative). The capability is the consumer's: a system integrating against `out/` must be able to tell a result from bookkeeping by name, and must be able to rebuild the run's summary from the ledgers alone when the manifest disagrees with them.

The reason the three are one epic and not three: they are the **filesystem affordances the other system integrates against** (`plan-03-pipelines.md` §13, Track 3 — *"The output layout … the last thing frozen in the PoC"*). The suffix rule is only unambiguous if the ledger's content is the ledger's business and not the result's; the manifest is only rebuildable if the ledger states enough to rebuild from; and the `not_applicable` list is what makes an absent stage distinguishable from a stage that never ran.

**The epic spans two owner layers**, and that is stated rather than smoothed: `S3-T03` is **Data** (ledger schema and writer, alongside the descriptors it derives from), while `S3-T07` and `S3-T10` are **Surface** (the output layout under `docflow/cli.py`). One task can span owners only by crossing a file, and a file has one owner (`wbs.md` §8).

**What E04 is not.** It is not the manifest *mechanism* — `rebuild_index()` is `S1-T06` and Stage 3 adds no rebuild engine (`traceability.md` §3.4 **D7**: `S1-T06` owns the mechanism; `S3-T07` owns the manifest's **shape and location**). It is not where the tree comes from (`S3-T06` walks it; this epic decides what sits inside). And it is not the invalidation semantics (`S3-T08` re-pends stages; this epic defines the artefact states those stages write).

---

## §2 Issues in this epic

| Issue | `wbs.md` task | Title | Wave | Depends on | Effort | PoC markers |
|---|---||---|---|:---:|---|:---:|---|
| `E04-01` | `S3-T03` | Ledger stage set derived from the primitive (`acquire` / `extract.r` / `extract.p` / `validate` / `report`) + `not_applicable` list | W3 | `S3-T02` → **E01** (inter) · `S1-T03` (external) | M | — |
| `E04-02` | `S3-T07` | Output layout + `run.json` + suffix rule | W4 | `S3-T06` → **E05** (inter) · `S1-T06` (external) | M | `# TODO: [MVP]`: `--rebuild-index` as a flag |
| `E04-03` | `S3-T10` | `run.json` presented as derived and rebuildable, never authoritative | W5 | `S3-T07` → **E04** (intra) | S | — |

Intra-epic edge (not drawn as an epic edge): `E04-03` → `E04-02`. It is the epic's own internal order: the manifest's shape must exist before it can be claimed rebuildable, and `S3-T10` is the issue that makes the claim checkable rather than asserted. `E04-01` has **no** intra-epic edge — the ledger stage set does not wait on the layout, and the layout does not wait on the stage set; they are the same capability approached from two sides, one in W3 and one in W4.

**E04 is the epic that spans the most waves** (W3 → W4 → W5, index README §5), and the reason it does so is visible in the table: `E04-01` waits on the descriptor schema (E01, W2), `E04-02` waits on batch knowing what tree it walks (E05, W3), and `E04-03` waits on the manifest's shape (W4). **No epic is a wave**: E04's three issues are separated in the wave order by E05's batch work, which sits between them.

---

## §3 Issue detail

### `E04-01` — implements `S3-T03`

**Title**
Ledger stage set derived from the primitive (`acquire` / `extract.r` / `extract.p` / `validate` / `report`) + `not_applicable` list.

**Context**
A ledger that lists only the stages that ran leaves an ambiguity that only shows up later: *"no `segmenter` entry"* could mean the pipeline does not run a Segmenter, or that the run has not reached it, or that it was dropped. `sad.md` §7.1 gives `skipped` the job of *"records absence as a fact, not as a gap"*, and this issue extends the same discipline to the stages a pipeline never had: they are listed in `not_applicable`. Two examples the plan fixes as the criterion: `M1-ErpVR` records no `segmenter`/`identifier`/`reconstructor`/`catalog` stage but **lists them in `not_applicable`**; `M4-EpVR` has a **single** `extract` and **no** `acquire` — because with pixels only there is nothing to acquire. The failure this prevents is stages recorded for work that never happened, or absence left ambiguous.

**Deliverable**
Ledger schema + writer.

**Depends on**
- `S3-T02` — **inter-epic** (E01 → E04): the stage set is *derived from the primitive*, and the primitive is declared in the descriptors.
- `S1-T03` — **external entry edge**: K7's ledger write path (`begin`/`commit`/`fail`, `read_ledger`, `write_ledger`) is where a stage state is actually written.

**Acceptance criteria**
- [ ] The ledger's stage set is **derived from the pipeline's primitive**, not hard-coded per code: `acquire` / `extract.r` / `extract.p` / `validate` / `report`.
- [ ] Every stage the primitive implies appears in the ledger for that code, with its state; every stage it does not imply appears in the **`not_applicable`** list.
- [ ] `M1-ErpVR` records **no** `segmenter`, `identifier`, `reconstructor` or `catalog` stage — and **lists all four in `not_applicable`**.
- [ ] `M4-EpVR` has a **single** `extract` stage and **no** `acquire` stage, and `acquire` appears in `not_applicable` as a fact.
- [ ] A `not_applicable` entry is never an empty list and never absent: absence of the list is itself a defect.
- [ ] The stage states written are the 7 durable states of `S1-T07` — this issue adds no eighth state.
- [ ] `validate` is present as a stage for **every** code, with no code able to express a stage set without it (`prd.md` FR-18, ADR-002).
- [ ] The writer routes through K7 (`S1-T03`), so `done` is only ever written after the artefact is durable.
- [ ] No new kernel-boundary type is introduced; the ledger's shape is the Plan 2 freeze consumed, not redefined (`plan-03-pipelines.md` §10, Task DoD).

**Test / evidence**
- `plan-03-pipelines.md` §5 row `S3-T03` — the verifiable criterion: *"`M1-ErpVR` records no `segmenter`/`identifier`/`reconstructor`/`catalog` stage but lists them in `not_applicable`; `M4-EpVR` has a single `extract` and no `acquire`."*
- `plan-03-pipelines.md` §8 — *"**FR-29** (the ledger is one of the three artefacts), **FR-33** indirectly"*, proof *"`M1-ErpVR` lists `segmenter`/`identifier`/`reconstructor`/`catalog` in `not_applicable`; `M4-EpVR` has one `extract` and no `acquire`."*
- `plan-03-pipelines.md` §3, observable evidence — the ledger-stage-set row: *"`M1-ErpVR` records no `segmenter`/`identifier`/`reconstructor`/`catalog` stage but lists them in `not_applicable`; `M4-EpVR` has a single `extract` and no `acquire`"*, guarding against *"stages recorded for work that never happened, or absence left ambiguous."*
- `plan-03-pipelines.md` §7b — *"The ledger stage set follows the primitive"*: `M1-ErpVR` and `M4-EpVR` ledger inspection. What breaking it looks like: *"stages recorded for work that never happened; `not_applicable` empty or absent."*
- `plan-03-pipelines.md` §11 — *"The ledger for each code records the stages the primitive implies and lists the rest in `not_applicable` as facts."*
- `plan-03-pipelines.md` §6 steps 7–8 — a ledger must show **where** the run is, not only how many files: `jq '.stages'` and the interrupted stage reading `running` are only readable against a stage set that matches the primitive.
- `sad.md` §7 — the stage vocabulary (`acquire`, `extract.r`, `validate`, `report`) and the table defining unit / stage / graph / ledger / manifest; §7.1 — the 7 durable states, `skipped` = *"this pipeline does not run this stage"*, and `not_applicable`'s role in making absence a fact.
- `plans/README.md` §3, Plan 2 row — the `not_applicable` list emitted by the ledger writer is a **Plan 2 freeze** that Plan 3 consumes and may not change; `plan-03-pipelines.md` §4 entry condition 3.
- `kernel-cli.md` §11 **row 1** — a killed stage reported as never started, then resumed: the matrix row the stage set must not break, exercised here over 11k documents (`plan-03-pipelines.md` §7c).

**Out of scope for this issue**
- **The descriptors themselves.** `S3-T02` (E01) declares the 13 codes and their primitives; this issue derives the stage set from them.
- **The artefact layout.** Which files sit beside the ledger, and their suffix rule, is `E04-02` (`S3-T07`).
- **`run.json`.** The manifest's shape and location are `E04-02`; that it is derived and rebuildable is `E04-03`.
- **Whether `S2-T12` (Catalog) is a dependency of `S2-T17`.** Carried **open** (`plan-03-pipelines.md` §12 **#3**): the `not_applicable` list is where `catalog` sits, and if `not_run` was defined as a literal rather than as the Catalog's value, the reason vocabulary is a constant in the Contract and the first real `source_unavailable` will need a change in the wrong layer. Recorded, not resolved.
- **An eighth state.** The 7 are frozen by Plan 1 (`S1-T07`, `sad.md` §7.1). **Never**.
- **A `--stage` reporting flag for the ledger.** `# TODO: [MVP]`.
- **A ledger per corpus rather than per document.** The per-document ledger is the only home at 11k documents (`plan-03-pipelines.md` §12 #9); an aggregate is the manifest, and the manifest is derived. **Never** authoritative.
- **Overwriting a ledger's history.** Ledgers record terminal facts; a re-run under `--force` re-pends states through the orchestrator, it does not rewrite the past. **Never**.

**Effort**
**M** — one schema and one writer, but the verification is per-code: the derivation has to hold for the `ErpVR` codes, the single-`extract` case and the no-`acquire` case, and `not_applicable` has to be populated rather than omitted for every one of the 13. Multiple interacting concerns (derivation, the closed set of stages, the 7 states, the K7 write path) with a dependency on a landed schema (`wbs.md` §7).

**Owner**
**Data** — `plan-03-pipelines.md`'s owner table assigns `S3-T01`–`S3-T04` and `S3-T13` to the **Data** layer (`wbs.md` §8), and `S3-T03` is in that set: the ledger schema and writer sit with the registry data that declares the primitive it is derived from. The write path itself is K7's mechanism, frozen by Plan 1.

**Frozen contract touched**
**Consumes** `plans/README.md` §3, Plan 2 row — the `not_applicable` list emitted by the ledger writer — and the Plan 1 row's 7 durable ledger states. Freezes nothing new: this issue is where a Plan 2 freeze is first exercised at the pipeline layer.

---

### `E04-02` — implements `S3-T07`

**Title**
Output layout + `run.json` + suffix rule.

**Context**
The consumer's first question about `out/` is *which of these files is the answer* — and the requirement is that it be answerable **by name alone** (`FR-29`), because a consumer that has to open a file to learn whether it is a result has no stable integration. `S3-T07` fixes the three artefacts beside each other: `<name>.json` for the result, `<name>.ledger.json` for progress, `<name>.work/` for intermediates. It also fixes `run.json`, which is what makes a run pollable: `state`, `totals`, `stages`, `outcomes`, `inflight`, readable with `jq` without the tool installed (`NFR-09`). The split of authority is fixed by `traceability.md` §3.4 **D7**: the **mechanism** is `S1-T06`'s `rebuild_index()`; **this task owns the manifest's shape and location only**.

**Deliverable**
Result/ledger/work layout — the three artefacts' placement and naming, plus `run.json`'s shape and location.

**Depends on**
- `S3-T06` — **inter-epic** (E05 → E04): the layout cannot be defined before batch knows what tree it walks.
- `S1-T06` — **external entry edge**: K1's `rebuild_index()` is the **only** authority for a manifest, and K7's `rebuild_manifest()` delegates to it (`kernel-cli.md` §9).

**Acceptance criteria**
- [ ] Every document writes **three** artefacts beside each other: `<name>.json` (result), `<name>.ledger.json` (progress), `<name>.work/` (intermediates).
- [ ] The three are **distinguishable by suffix alone** — no file needs to be opened, and no ledger is matched by a glob for results.
- [ ] `<name>.json` vs `<name>.ledger.json` vs `<name>.work/` is asserted from the consumer's side, with a glob that returns every result, no ledger, and no work directory (`plan-03-pipelines.md` §6 step 11).
- [ ] A single `run.json` sits at the output root and carries **`state`, `totals`, `stages`, `outcomes`, `inflight`**.
- [ ] `stages` shows **where** the run is, not only how many files: the counters advance per stage, and `inflight` is populated while documents are in flight.
- [ ] `run.json` is readable with `jq` alone, **without the tool installed** (`NFR-09`) — `jq '.totals' out/run.json` and `jq '.stages' out/run.json` both return.
- [ ] **The mechanism is `S1-T06`'s `rebuild_index()`; this issue owns the manifest's shape and location only** (`traceability.md` §3.4 **D7**). K7's `rebuild_manifest()` delegates; both doors return what `rebuild_index()` returned.
- [ ] `run.json` is written **progressively**, not once at the end: it exists with `state: running` early in a run, so a crash does not lose the run's progress record.
- [ ] No new kernel-boundary type is introduced, and no new manifest mechanism is added (`plan-03-pipelines.md` §10, Task DoD).

**Test / evidence**
- `plan-03-pipelines.md` §5 row `S3-T07` — the verifiable criterion, including *"The **mechanism** is `S1-T06`'s `rebuild_index()`; this task owns the manifest's **shape and location**. No `--rebuild-index` flag exists in the PoC — the rebuild is a library call."*
- `plan-03-pipelines.md` §8 — *"**FR-29**, **NFR-09**"*, proof *"Suffix rule unambiguous; `run.json` carries `state`/`totals`/`stages`/`outcomes`/`inflight`; `jq`-readable."*
- `plan-03-pipelines.md` §3, observable evidence — the two rows this issue owns: *"`<name>.json` / `<name>.ledger.json` / `<name>.work/`, distinguishable by suffix alone (`FR-29`)"* guarding against *"a result a consumer cannot tell from bookkeeping by name"*; and *"`run.json` carries `state`, `totals`, `stages`, `outcomes`, `inflight`; rebuilt from the ledgers alone reproduces it"* guarding against *"a manifest that is authoritative and therefore drifts."*
- `plan-03-pipelines.md` §6 step 6 — *"Start the first full run"*: a job id reported and `run.json` present with `state: running`, `totals.discovered` matching the measured count, `stages` counters advancing, `inflight` populated. The wrong result: *"a `run.json` that is written once at the end — then a crash loses the whole run's progress record."*
- `plan-03-pipelines.md` §6 step 7 — *"Poll without the tool installed"*: `jq '.totals'` and `jq '.stages'`; *"`stages` shows **where** the run is, not just how many files"*, guarding against *"a manifest that answers 'how many' but not 'at which stage' (`NFR-09`)."*
- `plan-03-pipelines.md` §6 step 11 — *"Check the suffix rule from the consumer's side"*: `find out -name '*.json' ! -name '*.ledger.json'`; every result matched, no ledger matched, every `<name>.work/` excluded.
- `plan-03-pipelines.md` §7b — *"Results, ledgers and work directories are distinguishable by suffix"* (glob test from the consumer's perspective; breaking it looks like *"a ledger a consumer parses as a result"*) and *"`run.json` is derived, never authoritative"* (delete it and rebuild; delete an artifact and read).
- `plan-03-pipelines.md` §13, Track 2 — *"Suffixes are unambiguous"* and *"The manifest is derived"*: the two golden artifacts, with the failure each must catch.
- `kernel-cli.md` §9 (K1 and K7) — `orchestrator manifest-rebuild <out-dir>` → `rebuild_index()`, `store manifest-rebuild <out-dir>` → `rebuild_manifest()` which **delegates**; *"Rebuilding the manifest is `K1`'s operation — `rebuild_index()` — because it reads every ledger and knows what a manifest is."*
- `traceability.md` §3.4 **D7** and §4.1 **FR-29**, §4.2 **NFR-09**.
- `sad.md` §7 — the manifest is the *"derived whole-run summary"*; §7.2 — verification on every ledger read, which is what makes a deleted artefact visible without a flag.
- `plan-03-pipelines.md` §12 **#9** — where the Reviewer's cases live once the run is over; at 11k documents the per-document ledger is the only home, which is why this issue's layout is load-bearing beyond this stage (carried open).

**Out of scope for this issue**
- **`--rebuild-index` as a flag.** `rebuild_index()` is a library call from Plan 1; there is no flag in the PoC (`traceability.md` §3.4 **D6**; `prd.md` §7). `# TODO: [MVP]`.
- **The rebuild mechanism.** `S1-T06` owns it; this issue owns the manifest's shape and location (`traceability.md` §3.4 **D7**). Reimplementing it here would violate the one-authority rule.
- **The layout's content.** What a stage state *means* is `E04-01`; what the manifest *means* is `rebuild_index()`'s.
- **The `run.json` rebuild claim as a demonstrated capability.** `E04-03` (`S3-T10`) is where "derived and rebuildable, never authoritative" is proven and documented.
- **Object storage.** Content addressing survives the move; colocation of ledger and result is a filesystem property and object storage has no equivalent of *"beside"*. Carried open (`plan-03-pipelines.md` §12 **#10**, touching `S3-T06` and `S3-T07`). `# TODO: [RELEASE]`.
- **A per-run aggregate ledger.** The manifest is derived; the ledgers are authoritative. **Never** an aggregate that is written and trusted.
- **`--format`, `--schema`, `--failed`, `--state` reporting.** `# TODO: [MVP]` (`plan-03-pipelines.md` §2).
- **A Reviewer queue over the 11k ledgers.** Carried open (`plan-03-pipelines.md` §12 #9); the per-document ledger is the only home. `# TODO: [MVP]`.

**Effort**
**M** — three artefacts' naming, one manifest shape and one progressive-write requirement, each with a check written from the **consumer's** side rather than the producer's. The implementation is small; the verification is where the cost is, because a suffix rule and a `jq` contract both fail silently if they are asserted from the wrong direction (`wbs.md` §7).

**Owner**
**Surface** — the result/ledger/work layout and `run.json`'s location sit with the output surface (`wbs.md` §8: Surface owns `docflow/cli.py`). The manifest **mechanism** it consumes is Kernels' (`S1-T06`).

**Frozen contract touched**
**Publishes** part of the Plan 3 row of `plans/README.md` §3: *"the mirrored-tree and the three-artifact layout; `run.json`'s shape and location"* — *"Nothing follows in the PoC. A shape change here is a shape change for the consuming system."* **Consumes** the Plan 1 row's manifest/`rebuild_index()` authority and the Plan 2 row's component artefact chain.

---

### `E04-03` — implements `S3-T10`

**Title**
`run.json` presented as derived and rebuildable, never authoritative.

**Context**
A manifest that cannot be rebuilt is authoritative, and an authoritative manifest drifts (`wbs.md` §9, *"Manifest drift — `run.json` disagreeing with the ledgers"*, owner stage 1, mitigation *"the manifest is derived and rebuildable"*). At 11k documents the drift is invisible in a **count**: a manifest reporting a finished run that is not finished looks exactly like a finished run (`kernel-cli.md` §11 **row 16**). `E04-02` ships the shape; this issue makes the claim checkable and states it where a reader will meet it — delete `run.json`, rebuild from the ledger tree alone, and it is reproduced; delete one `done` artefact by hand, read the ledger again, and the stage is incomplete **with no flag passed** (`ADR-006`).

**Deliverable**
Docs + a `rebuild_index()` test.

**Depends on**
`S3-T07` — **intra-epic**. No inter-epic dependency: this is the claim about the shape `E04-02` just defined.

**Acceptance criteria**
- [ ] `run.json` is **presented as derived and rebuildable, never authoritative** wherever it is documented — the documentation names the ledgers as the authority.
- [ ] **Deleting `run.json` and rebuilding reproduces it from the ledger tree alone** — asserted by a test, not by inspection.
- [ ] The rebuild reaches the **same** result through both doors — `orchestrator manifest-rebuild` and `store manifest-rebuild` — because K7's `rebuild_manifest()` delegates to `rebuild_index()` (`kernel-cli.md` §9).
- [ ] **A hand-deleted artefact shows up as incomplete on the next read**, with **no flag passed** (`ADR-006`, `prd.md` FR-05).
- [ ] The verification outcome is reported **alongside** the ledger state, never instead of it: a stage that is `done` and whose artefact is missing is reported incomplete.
- [ ] There is **no `--verify` flag and no ledger-trust `verify` subcommand** on any surface (`ADR-006`, `kernel-cli.md` §9). `store verify <sha256>` is a different operation and stays distinct.
- [ ] The test **fails when the invariant is broken** — if the rebuild stops reproducing the deleted manifest, or if verification stops running on read, the test goes red rather than quietly passing (`wbs.md` §8 Stage DoD).
- [ ] No new kernel-boundary type is introduced (`plan-03-pipelines.md` §10, Task DoD).

**Test / evidence**
- `plan-03-pipelines.md` §5 row `S3-T10` — the verifiable criterion: *"Deleting `run.json` and rebuilding reproduces it from the ledger tree; a hand-deleted artifact shows up as incomplete on the next read."*
- `plan-03-pipelines.md` §8 — *"**FR-11**, **NFR-09**"*, proof *"Delete `run.json` and rebuild from the ledger tree; a hand-deleted artifact shows as incomplete."*
- `plan-03-pipelines.md` §6 step 13 — *"Prove the manifest is derived."* `rm out/run.json`, then rebuild through the **library call**; then delete one `done` artefact and read again. The wrong result this step guards against: *"a manifest that cannot be rebuilt, i.e. one that is authoritative and therefore drifts."*
- `plan-03-pipelines.md` §7b — *"`run.json` is derived, never authoritative"*: delete it and rebuild; delete an artifact and read. What breaking it looks like: *"a manifest that cannot be rebuilt from the ledgers alone."*
- `kernel-cli.md` §11 **row 16** — a manifest reporting a finished run that is not finished: `orchestrator manifest-rebuild O` after `rm O/run.json`. `plan-03-pipelines.md` §7c carries it as a row Stage 3 **must not break at corpus scale**, *"where the drift would be invisible in a count."*
- `kernel-cli.md` §9 (K1) — *"There is no `verify` subcommand and no `--verify` flag. Verification is an outcome of reading a ledger, never a request."* And the explicit contrast: *"`store verify <sha256>` is different and legitimate … Keeping both, and naming them differently, is what prevents the two concepts from being conflated."*
- `prd.md` §8, *Verification is not optional* — given a ledger claiming a stage `done` whose artifact was deleted, when any run reads that ledger, then the stage is treated as incomplete **and no flag was required to trigger the check**.
- `prd.md` §8, *Resume after a forced kill* — *"every stage recorded `done` whose artifact verifies is skipped"*: the same verification outcome, exercised on the resume path.
- `plans/README.md` §2, non-negotiable 2 — verification is an outcome of every ledger read, no flag, *"in any stage, on any surface"*; fixed decisions row: *"The manifest (`run.json`) is derived, rebuildable and never authoritative — the ledgers are."*
- `traceability.md` §3.4 **D7**, §4.1 **FR-11**, §4.2 **NFR-09**.
- `wbs.md` §9 — *"Manifest drift — `run.json` disagreeing with the ledgers"*, mitigation *"the manifest is derived and rebuildable; ledgers are authoritative; verification on every read."*

**Out of scope for this issue**
- **The manifest's shape and location.** `E04-02` (`S3-T07`) owns them; this issue asserts the claim about what it is.
- **The rebuild mechanism.** `S1-T06`'s `rebuild_index()` (`traceability.md` §3.4 **D7**).
- **`--rebuild-index` as a flag.** **Never** in the PoC — the rebuild is a library call. `# TODO: [MVP]`.
- **`--verify`.** **Never** (ADR-006) — a flag that turns verification on would reintroduce exactly the gap the design closes.
- **A repair operation** that re-derives a deleted artefact. A missing artefact makes the stage incomplete; regenerating it is `S3-T09`'s decision, and for a sampled artefact the answer is **never** (`prd.md` FR-09).
- **A schema or format for the manifest beyond `E04-02`'s.** This issue adds no field.
- **Documentation of the policy/setting split or the slot policy.** Those are E02's and E03's.
- **Telemetry on manifest rebuilds.** `# TODO: [RELEASE]`.

**Effort**
**S** — one documentation statement and one test, but the test is the deliverable and it must be written to fail when the invariant breaks rather than to pass when it holds. Single concept, straightforward verification, no external dependency (`wbs.md` §7).

**Owner**
**Surface** — the documentation and the `rebuild_index()` test sit with the output surface this issue describes (`wbs.md` §8).

**Frozen contract touched**
**Consumes** `plans/README.md` §3, Plan 2 row (the component artefact chain a `done` claim is checked against) and the Plan 1 row's manifest authority. **Re-publishes** the Plan 3 row item it shares with `E04-02`: `run.json`'s shape and location — with the addition this issue exists for, that the shape is *derived*. Freezes nothing new.

---

## §4 Epic close condition

E04 is **`done`** when:

1. all three issues are `done`, and
2. the capability is **demonstrable from the consumer's side**: the ledger for `M1-ErpVR` lists `segmenter`/`identifier`/`reconstructor`/`catalog` in `not_applicable` while recording none of them as stages; `M4-EpVR` shows a single `extract` and no `acquire`; a glob over `out/` separates results from ledgers and work directories by suffix alone; `run.json` is present with `state` in flight and readable with `jq`; and `rm out/run.json` followed by the library rebuild reproduces it **from the ledger tree alone**, while a hand-deleted artefact reads back as incomplete **with no flag passed**.
3. **Plan 3 DoD, per epic:** no new kernel, no new component, no new kernel-boundary type — this epic adds configuration and data (`plan-03-pipelines.md` §10, Task DoD).

**Does E04 gate `S3-T14`?** **Transitively, through E06, and through a single path.** No entry in `S3-T14`'s dependency set names `S3-T03`, `S3-T07` or `S3-T10`. The path is `S3-T07` → `S3-T08` → `S3-T09` → `S3-T14`: E04 → E06 → E08. `S3-T03` reaches the gate from further away still, through the ledger the resume path reads. The consequence is worth stating: **this epic's evidence is what makes the resume assertions mean anything.** A run killed at 4,821 of 11,034 resumes correctly only if the ledger records the stages the primitive implies; and the gate's claim that completed documents were skipped *without re-reading* rests on `E04-03`'s verification-on-every-read holding at corpus scale.

---

## §5 Traceability

| Issue | FR / NFR (`traceability.md` §4) | Gap? | Evidence of the mapping |
|---|---|:---:|---|
| `E04-01` | **FR-29** (the ledger is one of the three artefacts), **FR-33** indirectly | no | `M1-ErpVR` lists `segmenter`/`identifier`/`reconstructor`/`catalog` in `not_applicable`; `M4-EpVR` has one `extract` and no `acquire` |
| `E04-02` | **FR-29**, **NFR-09** | no | Suffix rule unambiguous from the consumer's side; `run.json` carries `state`/`totals`/`stages`/`outcomes`/`inflight` and is `jq`-readable |
| `E04-03` | **FR-11**, **NFR-09** | no | Delete `run.json` and rebuild from the ledger tree; a hand-deleted artefact shows as incomplete with no flag |

No issue in E04 has an empty mapping, and the two `indirectly` notations are the plan's own: `plan-03-pipelines.md` §8 marks `S3-T03`'s second requirement as *"**FR-33** indirectly"* because the ledger's `not_applicable` list is part of what must be shape-identical across the 13, while the shape assertion itself is `E07-01`'s.

**Open decisions this epic carries, unresolved:**

| `plan-03-pipelines.md` §12 | Question | Touches | Why it stays open |
|---:|---|---|---|
| **#9** | Where the Reviewer's cases live once the run is over, and whether anything aggregates them | `E04-02` (`S3-T07` — the ledger's shape and location) | At 11k documents the per-document ledger is the only home, and a Reviewer working from 11k ledgers has no queue. The PoC declares this; it is the first thing an MVP has to answer, because the return loop is what makes the system improve |
| **#10** | Whether the mirrored tree survives the move to object storage | `E04-02` — and `E05-02` (`S3-T06`) | Content addressing does; colocation of ledger and result is a filesystem property, and object storage has no equivalent of *"beside"*. Recorded because `S3-T06`/`S3-T07` are the two tasks that would change **shape**, not merely backend, if this is ever revisited — the suffix rule and the mirrored tree are both filesystem affordances |
| **#3** | Whether `S2-T12` (Catalog) is a dependency of `S2-T17` | `E04-01` (the `not_applicable` list, where `catalog` sits) and `E07-01` (`catalog` present with reason `not_run` on all 13) | If `not_run` was defined as a literal rather than as the Catalog's value, then the reason vocabulary is a constant in the Contract and the first real `source_unavailable` will need a change in the wrong layer. Carried from Plan 2 unresolved |

None is resolved here.

---

## §6 Risks

From `plan-03-pipelines.md` §9 only:

| Risk | L | I | Why it touches E04 | Mitigation carried by this epic |
|---|:---:|:---:|---|---|
| *(none of the six §9 rows names `S3-T03`, `S3-T07` or `S3-T10`.)* | — | — | — | — |

**Stated rather than implied:** none of the six risk rows in `plan-03-pipelines.md` §9 names this epic's tasks, and none of the plan's three named execution risks lands on them either. The row that *would* have landed here is registered at a different owner stage: **manifest drift** (`wbs.md` §9, owner stage 1 — *"`run.json` disagreeing with the ledgers"*, mitigation *"the manifest is derived and rebuildable; ledgers are authoritative; verification on every read"*). It is excluded from this plan's §9 by the owner-stage filter, and it is carried anyway, because **E04 is the epic that makes the mitigation true at corpus scale**: `E04-02` fixes the shape, `E04-03` makes the rebuild claim a test, and `E04-01` supplies the stage set the manifest is an aggregate of.

Two further facts supply what the register does not:

- **`kernel-cli.md` §11 row 16 is this epic's row whether or not it is in the plan's §9.** *"A manifest reporting a finished run that is not finished"* — the matrix row Stage 3 must not break, carried by `plan-03-pipelines.md` §7c and exercised at the scale *"where the drift would be invisible in a count."* Non-negotiable 2 is asserted here more than anywhere else in the plan, and §7 of the index README records it that way.
- **The plan's `S3-T06`/`S3-T07` slip permission does not extend to `S3-T10`'s claim.** `plans/README.md` §4 and `wbs.md` §6.2 list `S3-T06`/`S3-T07`/`S3-T10` as tasks that *"can slip without delaying a stage close"*. That is a scheduling statement, not an invariant waiver: they may land late, but the gate cannot close while the manifest's derivedness is unproven, because the resume assertions in §3 of the plan name verification-on-read as their precondition.

---

