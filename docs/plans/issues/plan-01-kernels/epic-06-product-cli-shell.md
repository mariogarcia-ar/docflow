# E06 — Product CLI shell (`docflow`)

| Field | Value |
|---|---|
| Epic ID | **E06** |
| Capability | The product surface `docflow`: the five verbs that make resume observable |
| Issues | `E06-01` (`S1-T18`) — status `todo` |
| Issue count | **1** |
| Owner layer | **Surface** (`wbs.md` §8) — `docflow/cli.py` |
| Wave span | **W5** |
| Effort total | **1 × M** |
| Source plan | [`../../plan-01-kernels.md`](../../plan-01-kernels.md) §2, §3, §5 (`S1-T18`), §6 steps 6–8, §8 |
| Depends on other epics | **E05** (K1 orchestrator core) |

---

## §1 Objective

E06 delivers the **product** surface: `run`, `status`, `jobs`, `pause` and `stop [--force]`. It is not a thin wrapper — it is the surface the closing criterion is observed through: `stop --force` is what produces the interrupted stage the gate reads, and a second `run` is what proves the resume continued from the exact stage rather than from acquisition.

It is a **separate epic with one issue** because it owns a different deliverable surface from everything else in Stage 1. `wbs.md` §8 assigns `docflow/cli.py` to the **Surface** layer; every other Stage 1 task belongs to **Kernels** (`docflow/kernels/`, `docflow/ports/`, `docflow/adapters/`, `docflow/kernel_cli/`, `descriptors/`, `fixtures/`). A table that folded this task into E05 would put two different owner layers inside one epic and would hide the one place where the product surface and the lab surface could be confused. That confusion is the risk `kernel-cli.md` §2 exists to prevent: **`docflow run` never invokes `docflow-kernel`** — two entry points, two audiences.

There is also exactly **one** verb-set to build here and no capability to grow: five verbs, no `resume` verb *on this surface*, no flag that skips a stage. A single issue is the honest cut. The absence is this surface's own — the lab surface (`docflow-kernel`) exposes `pause`/`resume` as port methods (`kernel-cli.md` §9, K1 row 5), and the two facts do not contradict: `FR-01` forbids a second recovery verb in the product, not the port operation.

---

## §2 Issues in this epic

| Issue | `wbs.md` task | Title | Wave | Depends on | Effort | PoC markers |
|---|---||---|---|:---:|---|:---:|---|
| `E06-01` | `S1-T18` | CLI shell: `run` (idempotent), `status`, `jobs`, `pause`, `stop [--force]` | W5 | `S1-T06` → **E05** (inter-epic) | M | `# TODO: [MVP]`: `--failed`, `--state`, `--dry-run` |

No intra-epic edges exist: E06 has a single issue.

---

## §3 Issue detail

### `E06-01` — implements `S1-T18`

**Title**
CLI shell: `run` (idempotent), `status`, `jobs`, `pause`, `stop [--force]`.

**Context**
Crash recovery is only meaningful if a person can interrupt a run from a shell and then ask what happened. Without that surface, *"the ledger tells the truth about what was written"* is a claim about an internal test rather than something an operator can observe — and the two interruptions the closing criterion requires (pause, and a forced stop mid-stage) are not reachable at all. This issue is the surface that makes interruption an ordinary operation.

**Deliverable**
`docflow/cli.py`

**Depends on**
`S1-T06` — **inter-epic** (E05 → E06). The five verbs drive the orchestrator; they do not implement it.

**Acceptance criteria**
- [ ] `docflow/cli.py` exists and exposes exactly the five verbs: `run`, `status`, `jobs`, `pause`, `stop [--force]`.
- [ ] **`run` is idempotent**: repeating `run` **skips completed work** and starts nothing already terminal.
- [ ] A **second `run` after a kill continues** — it does not restart from acquisition.
- [ ] `pause` lets in-flight work finish and leaves the ledger consistent; a subsequent plain `run` continues from the **exact** stage.
- [ ] **There is no `resume` verb on `docflow`.** Continuing is *"run it again"* (`FR-01`, `FR-02`). **Never** a new product verb. (The lab surface's `docflow-kernel orchestrator resume` is a port method, not a product verb — `kernel-cli.md` §9.)
- [ ] `stop` **with no arguments discovers and reports** instead of killing — it never kills by default.
- [ ] `stop --force` performs the forced stop, and the interrupted stage reads `running` in the ledger afterwards.
- [ ] `status` and `jobs` report run and job state without modifying it.
- [ ] **`--force` is not settable by environment** — precedence is CLI → environment → `.env` → default, and it governs paths, slots, model and host only (`NFR-06`, ADR-009).
- [ ] `docflow run` **never invokes `docflow-kernel`** — the two entry points stay separate (`kernel-cli.md` §2, §15).
- [ ] No verb and no flag names a document concept (no `--pipeline` on this surface at Stage 1, no `--field`, no `--extractor`).

**Test / evidence**
- `plan-01-kernels.md` §6 step 6 — *"Interrupt #1 — pause"*: `docflow pause <job>` while units are in flight, then run the happy-path command again; the correct result is that in-flight work finishes, the resumed run continues from the exact stage, and nothing already `done` re-runs. The wrong result this guards against: a pause that leaves the ledger inconsistent, or a resume that restarts acquisition.
- `plan-01-kernels.md` §6 step 7 — *"Interrupt #2 — kill mid-stage"*: `docflow stop --force` while a unit is in `transform`, then `orchestrator ledger-read O`; the interrupted stage must read `running`. The wrong results: `pending` (reads as *never began*) or `done` (a claim about bytes that may be partial).
- `plan-01-kernels.md` §6 step 8 — *"Resume after the kill"*: run again, then read every ledger; **at most one stage per in-flight unit** re-runs (`NFR-02`); nothing after it had started.
- `plan-01-kernels.md` §8 — AC *Resume after a forced kill*; `stop` discovery test; precedence test; `--force` not settable by environment. Requirements **FR-01**, **FR-02**, **NFR-06**.
- `plan-01-kernels.md` §3 — the acceptance commands table: `docflow pause <job>` then `docflow run …` **continues from the exact stage; no separate `resume` verb** (`FR-01`, `FR-02`). And `docflow stop --force` then `docflow-kernel orchestrator ledger-read O` → the interrupted stage reads `running`, not `pending` and not `done`.
- `plan-01-kernels.md` §3, acceptance scenario *Resume after a forced kill* (`prd.md` §8) — closes at `S1-T19` (+ **`S1-T18`**, `S1-T07`).
- `kernel-cli.md` §4 — the two entry points: `docflow = "docflow.cli:main"` (product) and `docflow-kernel = "docflow.kernel_cli:main"` (lab); `docflow run` never invokes the lab surface.
- `traceability.md` §4.1 FR-01/FR-02 — the proof named there is `S1-T19`: *repeat `run` skips; after a kill it continues*.

**Out of scope for this issue**
- **No `resume` verb on this surface.** **Never** the product verb (`plan-01-kernels.md` §3, §11 checklist). The lab surface's `orchestrator resume` is `now` in `kernel-cli.md` §9 and is `E07-02`'s, not this issue's.
- **No per-component subcommands.** The 10 per-component subcommands are `S2-T16` (Plan 2). This issue is the shell only.
- **No batch or mirrored-tree behaviour.** `docflow/batch.py` is `S3-T06` (Plan 3).
- **No `--pipeline <CODE>`.** The 13 pipeline codes are descriptors, `S3-T02` (Plan 3). A descriptor is not a pipeline code (`kernel-cli.md` §9).
- **No `--failed`, `--state`, `--dry-run`, `--format`, `--schema`, `--golden`, `--isolate`, `--keep-artifacts`, `--show-evidence`, `--continuity-only`, `--source`, `--retry-queue`, `--retry`, `--rebuild`, `--rule`, `--new-type`, `--value`.** Every one is in the `03-cli.md` deferred list. `# TODO: [MVP]` (`prd.md` §7).
- **No `--no-validate`.** **Never** (ADR-002, `prd.md` FR-18).
- **No `--verify`.** Verification is an outcome of reading a ledger; there is no flag for it on any surface. **Never** (ADR-006, `kernel-cli.md` §9).
- **No `--rebuild-index` flag.** `rebuild_index()` stays a library call in the PoC. `# TODO: [MVP]` (`prd.md` §7).
- **No invocation of `docflow-kernel`.** **Never** (`kernel-cli.md` §2/§15).

**Effort**
**M** — five verbs, but the verification is what costs: idempotency across two invocations, a discovery-vs-kill `stop` distinction, a resume that must not restart acquisition, and a precedence rule for `--force` that must be checked against the environment. Interacting concerns rather than one heavyweight invariant (`wbs.md` §7).

**Owner**
**Surface** — `docflow/cli.py` (`wbs.md` §8). **This is the only issue in Stage 1 whose owner is not the Kernels layer**, which is precisely why this epic is cut on its own.

**Frozen contract touched**
**Consumes** the Plan 1 row of `plans/README.md` §3 — *the `KernelResult` JSON envelope and the 5 exit codes* (via E07-01) and the descriptor shape — plus the fixed-decisions row of §2: *operational settings use CLI → env → `.env` → default* and *there is no `--verify` flag and no `--no-validate` flag, in any stage, on either surface*.

---

## §4 Epic close condition

E06 is **`done`** when:

1. `E06-01` is `done`, and
2. the capability is **demonstrable from a shell**: `pause` followed by a plain `run` continues from the exact stage with no product `resume` verb existing; `stop` with no arguments discovers and reports without killing; and `stop --force` mid-stage leaves `running` in the ledger.

**Does E06 gate `S1-T19`?** **Yes, directly.** `S1-T18` is named in `S1-T19`'s dependency set, making E06 → E08 a **direct inter-epic edge**; and `S1-T18` is link 9 of the 9-link serial spine (`wbs.md` §6.2). The gate's *Resume after a forced kill* scenario is closed by this epic's surface plus `E05-02`'s ordering — `plan-01-kernels.md` §7c records the scenario's close as **`S1-T19`** (+ `S1-T18`, `S1-T07`).

---

## §5 Traceability

| Issue | `wbs.md` task | FR / NFR (`traceability.md` §4) | Gap? | Evidence of the mapping |
|---|---|:---:|---|
| `E06-01` | `S1-T18` | **FR-01**, **FR-02**, **NFR-06** | no | AC *Resume after a forced kill*; `stop` discovery test; precedence test; `--force` not settable by environment |

No gap: `traceability.md` §4.1 assigns FR-01 (*run single, idempotent verb*) and FR-02 (*pause / resume / stop [--force]*) to `S1-T18`, both with `S1-T19` as the proof. §4.2 assigns NFR-06 (precedence for **operational** settings) to `S1-T18` and `S3-T12`. The reverse check (`traceability.md` §5) adds FR-28 to this task's trace group, tracing it forward from Stage 3 — `S1-T18` is a named dependency of `S3-T06`, which is why the batch task's FR appears in this task's reverse row.

Note the deliberate asymmetry: **NFR-06a** (corpus policy is registry data, **not** configuration) is `S2-T04`/`S3-T12`, **not** this issue. This epic implements precedence for *operational* settings only; it does not implement policy assets, and no policy value may be set from the environment (ADR-009).

---

## §6 Risks

From `plan-01-kernels.md` §9 only:

| Risk | L | I | Why it touches E06 | Mitigation carried by this epic |
|---|:---:|:---:|---|---|
| *(none of the six §9 rows names `S1-T18`.)* | — | — | — | — |

**Stated rather than implied:** none of the six risk rows in `plan-01-kernels.md` §9 names `S1-T18`. The nearest register row in `wbs.md` §9 — *the kernel CLI lab surface drifts into a second product API* — is a risk about the **lab** surface, whose owner is `E07-02`, and its mitigation includes the direction that touches this epic: **`docflow run` never invokes `docflow-kernel`**. That prohibition is carried as an acceptance criterion of `E06-01` so that the mitigation is checkable here as well as asserted there. It is not restated as a second risk.

**No open decision from `plan-01-kernels.md` §12 names `S1-T18`.** The decisions that touch this surface's *precedence* behaviour — #2 (`--save` and an explicit `--root`) and #4 (per-asset registry hashing) — are carried by `E07-01` and `E03-01` respectively, not here.
