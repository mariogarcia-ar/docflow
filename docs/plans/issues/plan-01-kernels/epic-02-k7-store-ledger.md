# E02 — K7 Store — artifacts & ledger

| Field | Value |
|---|---|
| Epic ID | **E02** |
| Capability | K7 Store — durable, content-addressed artifacts & the ledger write path |
| Issues | `E02-01` (`S1-T02`) — `todo` · `E02-02` (`S1-T03`) — `todo` |
| Issue count | **2** |
| Owner layer | **Kernels** (`wbs.md` §8) — `docflow/kernels/` |
| Wave span | **W2 → W3** |
| Effort total | **2 × L** |
| Source plan | [`../../plan-01-kernels.md`](../../plan-01-kernels.md) §2, §5 (`S1-T02`, `S1-T03`), §6 steps 10–11, §7b, §8 |
| Depends on other epics | **E01** (boundary types) |

---

## §1 Objective

E02 delivers the substrate that makes every later claim in the plan checkable: **bytes that are durable, named by their own hash, and never partially visible** — and a **ledger whose `done` is written only after the bytes are durable**. One artifact store and one write path, shared by every kernel and by the harness.

It is a separate deliverable because it is where the plan's first non-negotiable is enforced mechanically. `plans/README.md` §2 non-negotiable 1 — *never write `done` about non-durable bytes* — is not a rule about K1's scheduler; it is a rule about the **order of two operations that live in this epic**: write → flush → fsync → rename → `done` (`prd.md` FR-04, `sad.md` §7.1). K7 owns the bytes and the ledger files; K1 (`E05`) owns their meaning (`sad.md` §3). That split is why this epic exists separately from the orchestrator: a store that is correct in isolation is what lets the orchestrator's ordering be *checked* rather than *assumed*.

---

## §2 Issues in this epic

| Issue | Title | Wave | Depends on | Effort | PoC markers |
|---|---|:---:|---|:---:|---|
| `E02-01` | K7 store: content-addressed put/get, atomic write, `verify`, never-empty `get` | W2 | `S1-T01` → **E01** (inter-epic) | L | — |
| `E02-02` | K7 ledger write path: `begin`/`commit`/`fail`, `read_ledger`, `write_ledger` | W3 | `S1-T02` → **E02** (intra-epic) | L | — |

Intra-epic edge: `E02-02` → `E02-01` (the ledger write path is built on the atomic write). Not drawn as an epic edge.

---

## §3 Issue detail

### `E02-01` — implements `S1-T02`

**Title**
K7 store: content-addressed put/get, atomic write (flush → fsync → rename), `verify`, never-empty `get`.

**Context**
Resume, idempotency and the whole crash-recovery design rest on one property: a reader must never see half a file. If a killed write can leave a partial artifact where a complete one belongs, then a `done` stage can point at bytes that are truncated — and the system will report success over them. This issue makes the artifact appear atomically, or not at all.

**Deliverable**
`docflow/kernels/store.py`

**Depends on**
`S1-T01` — **inter-epic** (E01 → E02). The store exchanges `Bytes`/`Artifact`; it does not define them.

**Acceptance criteria**
- [ ] `docflow/kernels/store.py` exists and exposes put/get keyed by content hash.
- [ ] Putting identical bytes twice results in **one** stored artifact; the second put does not create a second copy.
- [ ] An artifact is addressed by the hash of its own content, and the hash returned by put equals the hash the bytes actually have.
- [ ] A killed write leaves **no partial artifact visible** under its final name — the write sequence is write → flush → fsync → rename.
- [ ] `get` on a missing hash **raises**; it never returns empty bytes, `b""`, or a placeholder.
- [ ] `verify` detects a truncated file — a stored artifact whose bytes were shortened fails verification.
- [ ] `verify` returns a value (a boolean), so a **failed** verification is a successful call: the question was answered (`kernel-cli.md` §9, K7).
- [ ] No call path returns `""`, `0`, `[]` or `None` as a stand-in for a failure.

**Test / evidence**
- `plan-01-kernels.md` §8 — store unit tests; the atomic-write test; the `get`-raises test; `verify` on a truncated file (requirement **FR-11**).
- `plan-01-kernels.md` §6 step 10 — *"Crash between write and rename"*: inject the crash at the atomic-write boundary (row 2's procedure) and read the ledger; the correct result is `done` **absent** and `running` **present**. Step 10 is the procedure; its row assignment (`S1-T03`, `S1-T07`) is why E02-01 supplies it and `E02-02` asserts on it.
- `kernel-cli.md` §9 (K7) — `store put` / `store get` / `store verify` are `now` commands; `verify` returning `false` is exit `0`, not exit `2`.
- Matrix rows that consume this issue's bytes: row 2 (`done` with a partial artifact), row 16 (manifest). Both `now`, both Stage 1 gate rows (`kernel-cli.md` §11).

**Out of scope for this issue**
- **No ledger.** `begin`/`commit`/`fail` are `E02-02`. Until then a killer write can be demonstrated but not written down.
- **No manifest meaning.** K7 owns the bytes and the ledger *files*, not the meaning of a run (`sad.md` §3). `rebuild_manifest()` is a delegation to K1's `rebuild_index()` and belongs to `E05-01`.
- **No ledger-trust verification.** `store verify <sha256>` checks one artifact's bytes against its hash; it says nothing about ledger trust (`kernel-cli.md` §9). There is **no `--verify` flag** and no ledger-trust `verify` subcommand — **Never**.
- **No object-storage or database backend.** The filesystem is the PoC backend. `# TODO: [RELEASE]`.
- **No caching layer, no GC, no dedup reporting.** `# TODO: [RELEASE]`.
- **No domain noun** in any method name or parameter. **Never**.

**Effort**
**L** — a load-bearing invariant (the atomic write) plus a heavyweight verification requirement: the criterion is not that put/get work, but that a **killed** write is invisible and a **truncated** file is detected, which needs a crash-injection test rather than a happy-path unit test (`wbs.md` §7).

**Owner**
**Kernels** — `docflow/kernels/store.py` (`wbs.md` §8).

**Frozen contract touched**
**Consumes** `plans/README.md` §3, Plan 1 row: `Bytes`/`Artifact` from `docflow/kernels/types.py`. Adds no new kernel-boundary type.

---

### `E02-02` — implements `S1-T03`

**Title**
K7 ledger write path: `begin` / `commit` / `fail`, `read_ledger`, `write_ledger`.

**Context**
A ledger that can record `done` before the bytes exist turns resume into a lie: the next run skips work that was never completed, and the result is a document that looks processed and is not. This issue is the write path where that ordering is either respected or lost — `commit` writes `done` **only after** the rename has returned.

**Deliverable**
`docflow/kernels/store.py` (continuation of `E02-01`'s file)

**Depends on**
`S1-T02` — **intra-epic** (E02 → E02). Externally: none beyond E01.

**Acceptance criteria**
- [ ] `begin`, `commit`, `fail`, `read_ledger` and `write_ledger` exist in `docflow/kernels/store.py`.
- [ ] `commit` writes `done` **only after** the rename returns — demonstrable with a crash injected between the write and the rename: `done` is **absent** and `running` is **present**.
- [ ] A forced kill between write and rename leaves the stage `running`, **not** `done`.
- [ ] There is no code path that writes `done` before the artifact's rename has returned.
- [ ] `read_ledger` returns the recorded state for every stage of the unit, including stages that never started.
- [ ] `write_ledger` and `read_ledger` round-trip: what `write_ledger` wrote is what `read_ledger` reports.
- [ ] The recorded state is one of the plan's seven durable states; no eighth value is writable.
- [ ] The ledger file format permits K1 to rebuild the manifest from the ledger tree **alone**, without `run.json` (`kernel-cli.md` §11 row 16).

**Test / evidence**
- `plan-01-kernels.md` §7b row 2 — *"Never `done` about non-durable bytes"*, test *"Crash injected between write and rename"*, breaking it looks like *"`done` is written before the rename returns; the ordering is moved 'for convenience'"*. Task cell: `S1-T03`, `S1-T07`.
- `plan-01-kernels.md` §6 step 10 — the procedure, and its two expected states.
- `kernel-cli.md` §11 row 2 (K1, stage marked `done` whose artifact is partial) — `now`, Stage 1 CI gate; the crash is injected via `orchestrator run`.
- `kernel-cli.md` §9 (K7) — `store ledger-read`, `store ledger-begin`/`ledger-commit`/`ledger-fail` are `now`.
- `plan-01-kernels.md` §8 — row 2 procedure; the `commit`-after-rename test (requirements **FR-04**, **NFR-03**).

**Out of scope for this issue**
- **No verification on read.** Verifying a ledger against the filesystem on **every** read, with no flag, is `E05-05` (`S1-T10`, ADR-006). This issue provides the read path; it does not add the mandatory check.
- **No `running`-before-work ordering.** The scheduler writes `running` before the work starts; that is `E05-02` (`S1-T07`). This issue provides `begin` as the mechanism it calls.
- **No stage-set semantics.** Which stages exist, what `not_applicable` means and the per-code stage set are Plan 3's (`S3-T03`) and/or the descriptor's. **Not here.**
- **No `verify` subcommand or `--verify` flag** on the ledger path — **Never**.
- **No distributed ledger, no DB-backed ledger.** `# TODO: [RELEASE]`.

**Effort**
**L** — a load-bearing invariant whose test must *fail* when the invariant is broken, which requires crash injection at a precise point in the write sequence rather than a functional test. `wbs.md` §7's `L` is explicitly "a load-bearing invariant or a heavyweight external dependency; needs an integration or crash-injection test".

**Owner**
**Kernels** — `docflow/kernels/store.py` (`wbs.md` §8).

**Frozen contract touched**
**Consumes** the Plan 1 frozen row `plans/README.md` §3 — the seven durable ledger states, whose *set* is fixed by `E05-02`; this issue fixes the **write path** that can only ever write one of them.

---

## §4 Epic close condition

E02 is **`done`** when:

1. `E02-01` and `E02-02` are `done`, and
2. the capability is **demonstrable**: from outside the process, a forced kill at the write/rename boundary leaves the stage readable as `running` with `done` absent, and a truncated artifact fails verification — demonstrated by the runbook, not by reading the store's code.

**Does E02 gate `S1-T19`?** **Yes, transitively.** No entry in `S1-T19`'s dependency set names `S1-T02` or `S1-T03`; the edge is E02 → E05 (`S1-T06` depends on `S1-T03`) and then E05 → E08. `S1-T03` is link 3 of the 9-link serial spine. The gate's *Resume after a forced kill* scenario cannot be closed without this epic.

---

## §5 Traceability

| Issue | FR / NFR (`traceability.md` §4) | Gap? | Evidence of the mapping |
|---|---|:---:|---|
| `E02-01` | **FR-11** ("K7 content-addressed, atomic, `get` raises") | no | store unit tests; atomic-write test; `get`-raises test; `verify` on a truncated file |
| `E02-02` | **FR-04** ("Never `done` about non-durable bytes") · **NFR-03** ("Restart cost bounded") | no | `S1-T22` row 2 procedure; `commit`-after-rename test |

No issue in E02 has an empty mapping. The reverse check (`traceability.md` §5) places `S1-T02` and `S1-T03` in the orchestrator/store/ledger spine group.

---

## §6 Risks

From `plan-01-kernels.md` §9 only:

| Risk | L | I | Why it touches E02 | Mitigation carried by this epic |
|---|:---:|:---:|---|---|
| **Sampled artifact regenerated on resume**, silently changing the result | M | H | The regeneration decision is made by reading the ledger this epic writes; the ledger is what carries the determinism-class consequence and the `evidence_missing` outcome (`kernel-cli.md` §5). | Ledger write path records state and terminal outcome durably, so a missing sampled artifact is readable as `failed` rather than as absent. The consequence itself is `E05-03`'s. |
| **Manifest drift** — `run.json` disagreeing with the ledgers | M | M | Drift is only meaningful because the ledgers are the authority; this epic produces the artifact `rebuild_index()` reads. | The ledger tree is written to be sufficient on its own: the manifest can be reconstructed from ledgers **alone** (`kernel-cli.md` §11 row 16). The mechanism is `E05-01`'s; the sufficiency is this epic's acceptance criterion. |

Two §9 rows — *model resolved by capability* and *the CLI lab surface drifts* — are owned by `E04-07` and `E07-02` respectively and do not touch E02.
