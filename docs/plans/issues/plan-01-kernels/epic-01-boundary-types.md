# E01 — Boundary types & contracts

| Field | Value |
|---|---|
| Epic ID | **E01** |
| Capability | Boundary types & contracts |
| Issues | `E01-01` (`S1-T01`) — status `todo` |
| Issue count | **1** |
| Owner layer | **Kernels** (`wbs.md` §8) — `docflow/kernels/` |
| Wave span | **W1** |
| Effort total | **1 × M** |
| Source plan | [`../../plan-01-kernels.md`](../../plan-01-kernels.md) §2, §5 (`S1-T01`), §7b, §8 |
| Depends on other epics | **none** — E01 is the graph's root |

---

## §1 Objective

E01 delivers the one interface that every kernel, port, adapter and (at Stage 2) every domain component exchanges. Its capability is **not** "some dataclasses exist": it is that the system's boundary **cannot express a third state**. A kernel either returns a value with evidence, or returns no value and a reason — and there is no way to write a value without evidence or a `None` without a reason, so a silent stand-in is not merely forbidden by convention but unrepresentable.

It is a separate deliverable because it is the **only** artifact in Stage 1 with no dependency and every other artifact as a consumer. `wbs.md` §1 states the rule — contracts must be fixed before they are multiplied — and `plan-01-kernels.md` §4 entry condition 4 makes the consequence explicit: a change to these types after this plan re-opens the gate. The other seven epics are work *behind* this boundary; E01 is the boundary.

---

## §2 Issues in this epic

| Issue | Title | Wave | Depends on | Effort | PoC markers |
|---|---|:---:|---|:---:|---|
| `E01-01` | Freeze kernel boundary types | W1 | **—** (none) | M | — |

No intra-epic edges exist: E01 has a single issue.

---

## §3 Issue detail

### `E01-01` — implements `S1-T01`

**Title**
Freeze kernel boundary types: `Token`, `KernelResult`, `Evidence`, `Reason`, `CallRecord`, `Bytes`, `Artifact`.

**Context**
Every kernel in the system returns its answer through one shape, and until that shape exists there is no vocabulary in which a kernel can say *"no value, and here is why"*. Without it, the cheapest way to satisfy a caller is to return an empty string, a `0`, an empty list, or a default model — and each of those is a silent failure that looks like a successful answer. This issue makes that class of error impossible to write down rather than merely discouraged.

**Deliverable**
`docflow/kernels/types.py`

**Depends on**
None. Intra-epic: n/a. Inter-epic: n/a. This is the graph's only sourceless node.

**Acceptance criteria**
- [ ] `docflow/kernels/types.py` exists and defines exactly the seven named types — `Token`, `KernelResult`, `Evidence`, `Reason`, `CallRecord`, `Bytes`, `Artifact` — as **frozen** dataclasses.
- [ ] Mutating an instance of any of the seven types raises rather than succeeding.
- [ ] A `KernelResult` carrying a non-`None` `value` **cannot be constructed** with empty or absent `evidence`.
- [ ] A `KernelResult` carrying `value=None` **cannot be constructed** without a populated `reason`.
- [ ] The only two constructible states of `KernelResult` are *(value + evidence + `reason: None`)* and *(`value: None` + `reason`)*; a test enumerates the constructible states and asserts no third one exists.
- [ ] **The Track 3 consumer test**: an import-isolation test asserts that `docflow/kernels/types.py` is importable by a module that imports **no adapter** — the property `plan-01-kernels.md` §13 Track 3 states as *"Plan 2 builds every component against these types and adds **no new kernel-boundary type**"*. This is a **static assertion over the module's imports**, not a prose claim: it passes today (Plan 2 does not exist) and **fails** the moment a component redefines one of the seven types or reaches through a port for an adapter.
- [ ] `Reason` carries a machine-readable `code` member, not only a human message.
- [ ] No type, field or member name contains a domain noun — not `invoice`, not `field`, not `verdict`, not a document type, not a pipeline code.
- [ ] Every type carries an explicit type hint on every field.

**Test / evidence**
- `plan-01-kernels.md` §7b row 1 — *"No third state at a kernel boundary"*: the unit test asserts `KernelResult` cannot express a value without evidence or a `None` without a reason. The wrong result it guards against is recorded there: someone returns `""`, `0`, `[]` or a default model as a stand-in *and the test still passes*.
- `plan-01-kernels.md` §8 — proof is the unit test asserting no third state exists (requirements **FR-06**).
- Downstream consumption: this file is the head of `plans/README.md` §3's Plan 1 frozen row; Plan 2's consumer test is that a component constructs these types **without redefining them**, i.e. **adds no new kernel-boundary type** — two statements of one criterion, and the criterion is asserted by this issue's import-isolation acceptance box rather than left as prose (`plan-01-kernels.md` §13 Track 3).

**Out of scope for this issue**
- **No behaviour.** No store, no ledger, no ports, no orchestrator — this issue is types and their constructibility only.
- **No serialization format decision.** The `KernelResult` JSON envelope is `E07-01`'s (`S1-T20`, `kernel-cli.md` §6); E01-01 fixes the in-process shape, not its encoding. `# TODO: [MVP]`.
- **No `reason.code` vocabulary.** The closed set lives in `kernel-cli.md` §5 and is consumed by the epics that raise codes; E01-01 fixes that a `code` exists, not which values are legal.
- **No third state, ever.** Not a `"unknown"` variant, not an optional evidence field, not a `Union` with a bare value arm. **Never**, per `prd.md` FR-06 / `sad.md`.
- **No domain noun.** A kernel API with a domain noun in it is a component wearing the wrong name (`kernel-cli.md` §14). **Never**.

**Effort**
**M** — a single concept, but the verification is the whole point: the constructibility constraints must be enforced by the type system *and* asserted by a test that fails if a third state becomes expressible. Multiple interacting concerns (`frozen` semantics, evidence-required-with-value, reason-required-without-value) with no external dependency.

**Owner**
**Kernels** — the artifact path `docflow/kernels/types.py` is owned by the Kernels layer (`wbs.md` §8).

**Frozen contract touched**
**Freezes** `plans/README.md` §3, Plan 1 row: `Token` · `KernelResult` · `Evidence` · `Reason` · `CallRecord` · `Bytes`/`Artifact` (`docflow/kernels/types.py`). Consumed by Plan 2, which may not change them and may add no new kernel-boundary type.

---

## §4 Epic close condition

E01 is **`done`** when:

1. `E01-01` is `done`, and
2. the capability is **demonstrable**: an enumerating test shows that the only constructible states of `KernelResult` are value-with-evidence and no-value-with-reason, and that constructing a stand-in fails — checked by running the test, not by reading `types.py`.

**Does E01 gate `S1-T19`?** **Not directly.** No entry in `S1-T19`'s dependency set names `S1-T01`. It gates it **transitively and unconditionally**: every inter-epic edge into E08 originates in an epic that consumes E01, and `S1-T01` is link 1 of the 9-link serial spine (`wbs.md` §6.2). A regression here does not fail the gate's test — it invalidates what the gate's test means.

---

## §5 Traceability

| Issue | FR / NFR (`traceability.md` §4) | Gap? | Evidence of the mapping |
|---|---|:---:|---|
| `E01-01` | **FR-06** ("No third state at any boundary") | no | unit test asserting `KernelResult` cannot express it |

No issue in E01 has an empty mapping. FR-06 is satisfied by this issue alone (`traceability.md` §4.1), and the reverse check (`traceability.md` §5) places `S1-T01` inside the orchestrator/store/ledger spine group — no orphan task.

**Frozen contract, per `plans/README.md` §3:** the artifact this epic freezes is the Plan 1 row's first item; Plan 2's gate test is that its first component constructs these types without redefining them.

---

## §6 Risks

From `plan-01-kernels.md` §9 only:

| Risk | L | I | Why it touches E01 | Mitigation carried by this epic |
|---|:---:|:---:|---|---|
| *(none of the six §9 rows names `S1-T01`.)* | — | — | — | — |

**Stated rather than implied:** none of the six risk rows in `plan-01-kernels.md` §9 names `S1-T01`, and the plan's own *plan-specific execution risk* concerns the wave order of `S1-T21` and `S1-T19`, not this task. The risk that does attach to E01 is structural and comes from `plan-01-kernels.md` §4 entry condition 4 and `wbs.md` §1 instead: **a change to the boundary types after W1 re-opens the gate.** That is not a register row; it is the reason this epic is one issue wide and closes first.

Three risks recorded in `wbs.md` §9 whose *Owner stage* is 2 — Docling install/portability, `pdftotext` as a poppler binary, GPU availability — materialise in E04, not here, and are excluded from `plan-01-kernels.md` §9 by construction.
