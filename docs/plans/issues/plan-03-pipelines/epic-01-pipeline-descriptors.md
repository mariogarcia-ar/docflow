# E01 — Pipeline descriptors & code resolution

| Field | Value |
|---|---|
| Epic ID | **E01** |
| Capability | Pipeline descriptors & code resolution — a code resolves to a declared descriptor, and an invalid code is an error rather than a silent conversion |
| Issues | `E01-01` (`S3-T01`) — status `todo` · `E01-02` (`S3-T02`) — status `todo` |
| Issue count | **2** |
| Owner layer | **Data** (`wbs.md` §8) — `registry/pipelines/*.yaml` |
| Wave span | **W1 → W2** |
| Effort total | **2 × M** |
| Source plan | [`../../plan-03-pipelines.md`](../../plan-03-pipelines.md) §2, §5 (`S3-T01`, `S3-T02`), §3 (the gate's code table), §6 steps 1–2, §7b rows 1, §8, §12 #2, §13 |
| Depends on other epics | **none** — E01 is the graph's head, entered from Plan 2's closing flow (`S2-T17`) |

---

## §1 Objective

E01 delivers the two things a pipeline code needs to mean anything: **a schema that says what a descriptor is**, and **the 13 descriptors themselves**. Its capability is that `docflow run --pipeline <CODE>` resolves a code to a declared stage set over the `EVR` primitive, and that an invalid code — `M4-ErVR`, `M4-ErpVR`, `M0-*` pointed at a PDF, or an unknown string — is an **error, never a silent conversion**. `FR-25` asks for 13 reachable codes; `FR-31` asks that M0 refuse a PDF instead of quietly reading it as M1. Both are properties of this epic and of nothing else.

The epic is **configuration and data, not new code** (`wbs.md` §5). `sad.md` §8 and §14 say the same thing from the architecture side: pipelines are the one layer where Stage 3 adds descriptors to K8 and reuses the Stage 2 chain unchanged. The reason this is a separate deliverable is that it is the **graph's head**: `S3-T02`'s output is consumed by `S3-T03`, `S3-T05`, `S3-T06`, `S3-T08`'s chain and `S3-T13`, which is why four of the ten inter-epic edges leave E01.

**What E01 is not.** It is not the ledger's stage set (`S3-T03` reads the primitive out of these descriptors and records the consequence; E01 declares the primitive and no ledger state), it is not the material selector (that is `S3-T05`, which consumes these codes as its alternative form), and it is not the shape guarantee across the 13 (`S3-T13` asserts it; E01 only makes the codes exist to be asserted on). Above all it is not a `Pipeline` class, an engine registry, or a dispatch table in code — an issue that needed one would mean a gate was closed early (`plan-03-pipelines.md` §10, Task DoD).

---

## §2 Issues in this epic

| Issue | `wbs.md` task | Title | Wave | Depends on | Effort | PoC markers |
|---|---||---|---|:---:|---|:---:|---|
| `E01-01` | `S3-T01` | Pipeline descriptor schema in K8 (material prefix → extractor → validate → report) | W1 | `S2-T17` → **Plan 2's closing flow** (external entry) | M | `# TODO: [MVP]`: descriptor authoring aids |
| `E01-02` | `S3-T02` | The 13 descriptors: `M0-ErVR` … `M4-EpVR` | W2 | `S3-T01` → **E01** (intra) | M | — |

Intra-epic edge (not drawn as an epic edge): `E01-02` → `E01-01`. It is the epic's own internal order: the 13 descriptors cannot be authored before the schema that validates them exists, and the schema is worth nothing before there are descriptors to validate. Nothing else in the directory depends on `S3-T01` — every downstream edge originates at `S3-T02`.

---

## §3 Issue detail

### `E01-01` — implements `S3-T01`

**Title**
Pipeline descriptor schema in K8 (material prefix → extractor → validate → report).

**Context**
A pipeline code is a name for a stage graph over the `EVR` primitive, and the whole point of Stage 3 is that the 13 codes are a matrix rather than 13 designs (`prd.md` §4.1; `sad.md` §8). That only holds if a code resolves **declaratively** — through a descriptor that states its material prefix, its extractor mode and its stage set — rather than through branching in code. The failure this issue guards against is not a crash: it is a descriptor that expresses something the primitive cannot (`ErVR` with a stage that was never declared), which would then run to completion and produce output whose provenance nothing recorded.

**Deliverable**
`registry/pipelines/*.yaml` — the descriptor schema, loaded and schema-validated by K8 (`S1-T04`).

**Depends on**
`S2-T17` — external entry edge into Plan 3: the canonical chain must traverse and emit before a code can be declared over it (`plan-03-pipelines.md` §4 entry condition 4). Intra-epic: n/a. Inter-epic: none — E01 is a head.

**Acceptance criteria**
- [ ] A descriptor in `registry/pipelines/*.yaml` expresses the `EVR` primitive: **E**xtractor → **V**alidate → **R**eport, with the mode (`r` / `p` / `rp`) written inside the primitive as `ErVR`, `EpVR` or `ErpVR`.
- [ ] A descriptor expresses its **material prefix** (`M0` … `M4`) as data, not as a branch in code.
- [ ] The descriptor's stage set is derived from the primitive: `acquire` where the material requires it, `extract.r` and/or `extract.p` per the mode, `validate`, `report`.
- [ ] **A descriptor failing its own schema stops the run** — `registry validate` exits non-zero naming the offending asset, and no run starts against it.
- [ ] A descriptor is loaded through K8 (`S1-T04`): no descriptor is read from a path outside the registry root, and no descriptor is defaulted when absent.
- [ ] A descriptor that declares a code outside the 13 (an `ErVR`-shaped variant, a missing `V`, a code with no material prefix) **fails validation**.
- [ ] The schema is versioned data, so a descriptor change is a registry-hash change — and therefore visible as the thing that invalidates the affected stages (`sad.md` §5.1, ADR-009).
- [ ] No new kernel-boundary type is introduced: the descriptor is registry data in the K8 asset vocabulary (`plans/README.md` §3, Plan 1 row; `plan-03-pipelines.md` §10, Task DoD).

**Test / evidence**
- `plan-03-pipelines.md` §5 row `S3-T01` — the verifiable criterion: *"The descriptor expresses the `EVR` primitive and the stage set; a descriptor failing its own schema stops the run."*
- `plan-03-pipelines.md` §7b row 1 — *"The 13 codes are the only codes, and invalid ones error"*: the resolution test is `S3-T02`'s, but it can only fail correctly if the schema refuses an out-of-range descriptor — which is this issue's assertion.
- `plan-03-pipelines.md` §6 step 3 — *"Confirm the registry is the sole source of policy"*: `docflow-kernel registry validate` then `registry hash`; a correct result is that assets validate and the hash prints.
- `kernel-cli.md` §9 (K8) — `registry validate` (load + schema-validate), `registry hash`, and the fail-fast rule: *"A malformed asset stops the run. A missing asset is never defaulted."* `asset_invalid` / `asset_missing` are the reason codes (`kernel-cli.md` §5), and `kernel-cli.md` §11 **row 17** is the matrix row this issue's fail-fast assertion shares.
- `kernel-cli.md` §11 **row 17** — *"A missing asset defaulted, producing a run that extracts nothing"*: `registry validate --root R` with one asset removed → exit `3` naming the missing asset. This task must not break that row.
- `sad.md` §14 — the Stage 3 column for K8: *"13 pipeline descriptors"*.
- `traceability.md` §4.1 FR-25 — the descriptor is what a code resolves to.

**Out of scope for this issue**
- **No descriptors.** The 13 are `E01-02`. This issue ships the schema and one fixture proving the schema refuses an invalid descriptor.
- **No descriptor authoring aids.** Scaffolding, a `registry new-pipeline` helper and generator templates are convenience over a 13-row file. `# TODO: [MVP]`.
- **No ledger stage set.** Which stages are recorded, and which are listed in `not_applicable`, is `S3-T03` (E04). This issue declares the primitive; the ledger records its consequence.
- **No `--pipeline` flag resolution in the CLI.** Resolution of a code to a descriptor is exercised through `S3-T02`; the CLI's `--extractor` alternative is `S3-T05`.
- **No per-corpus OCR engine choice.** The engine is Docling and only Docling; a descriptor may not name one. **Never** (ADR-001, `prd.md` FR-16).
- **No way to declare a pipeline without `validate`.** `V` is invariant in all 13 codes; a descriptor expressing a stage set with no `validate` is schema-invalid, not schema-optional. **Never** (ADR-002, `prd.md` FR-18, `traceability.md` §3.3 route 2).
- **No new code layer.** No `Pipeline` class, no engine registry, no dispatch table — the descriptor is data and Stage 3 adds configuration. A new kernel-boundary type here means a gate was closed early (`plan-03-pipelines.md` §10).

**Effort**
**M** — the schema is one concept, but its verification is the whole cost: it must accept the 13 legal shapes, reject the out-of-range ones, and do so through K8's existing validate/hash path rather than a bespoke loader. Multiple interacting concerns (material prefix, mode-inside-primitive, stage set, fail-fast) with no external dependency (`wbs.md` §7).

**Owner**
**Data** — the artifact path `registry/pipelines/*.yaml` is owned by the Data layer (`wbs.md` §8).

**Frozen contract touched**
**Consumes** `plans/README.md` §3, Plan 1 row — the descriptor shape (`descriptors/synthetic-3stage.yaml`) and K8's load/validate/hash contract. Freezes nothing new at Plan 1's level; the Plan 3 descriptor vocabulary it introduces is part of the Plan 3 row published by E08.

---

### `E01-02` — implements `S3-T02`

**Title**
The 13 descriptors: `M0-ErVR` … `M4-EpVR`.

**Context**
`FR-25` asks for 13 reachable codes and `FR-31` asks that M0 refuse a PDF rather than read it as M1. The second is the load-bearing half. A code that resolves but silently converts produces output that looks correct, carries verdicts, and describes a document the caller never declared — the exact class of silent failure the architecture is built to refuse, arriving through the newest surface. This issue is where the 13-code matrix becomes reachable *and* where the three invalid forms become errors: `M4-ErVR` and `M4-ErpVR` (M4 has pixels only, so only `EpVR` exists — `traceability.md` §3.1 route 10), `M0-*` pointed at a PDF (`FR-31`), and an unknown code.

**Deliverable**
13 pipeline descriptors — `M0-ErVR`, `M0-EpVR`, `M0-ErpVR`, `M1-ErVR`, `M1-EpVR`, `M1-ErpVR`, `M2-ErVR`, `M2-EpVR`, `M2-ErpVR`, `M3-ErVR`, `M3-EpVR`, `M3-ErpVR`, `M4-EpVR`.

**Depends on**
`S3-T01` — **intra-epic**. No inter-epic dependency: `S3-T02` depends on nothing outside this plan (`plan-03-pipelines.md` §5), which is why W2 opens immediately at the gate.

**Acceptance criteria**
- [ ] Exactly **13** descriptors exist, one per code, and the count is asserted: `M0-ErVR`, `M0-EpVR`, `M0-ErpVR`, `M1-ErVR`, `M1-EpVR`, `M1-ErpVR`, `M2-ErVR`, `M2-EpVR`, `M2-ErpVR`, `M3-ErVR`, `M3-EpVR`, `M3-ErpVR`, `M4-EpVR` (`prd.md` FR-25, `plan-03-pipelines.md` §11).
- [ ] `docflow run --pipeline <CODE>` **resolves all 13** against a single file per code, each exiting `0`.
- [ ] `M4-ErVR` and `M4-ErpVR` are **errors, not silent conversions** — no such code exists, and the run exits with a typed reason rather than falling back to `M4-EpVR`.
- [ ] **`M0-*` pointed at a PDF is an error** (`FR-31`): M0 accepts text directly — a file, Markdown, or `-` for stdin — and refuses a PDF instead of reading it as M1.
- [ ] An **unknown code** (e.g. `M1-ErpVRX`) is an error naming the code, with **no default pipeline substituted**.
- [ ] The 13 codes and their `V` presence match `traceability.md` §3: every one of the 13 carries a `V`, including `M1-ErVR`, which is the **one** route the artifacts changed from the origin by adding it (`traceability.md` §3.3, deviation **D1**).
- [ ] Each descriptor resolves through K8, so each code's stages come from data; no code is special-cased in code.
- [ ] No new kernel-boundary type is introduced (`plan-03-pipelines.md` §10, Task DoD).

**Test / evidence**
- `plan-03-pipelines.md` §5 row `S3-T02` — the verifiable criterion: *"`docflow run --pipeline <CODE>` resolves all 13; `M4-ErVR`, `M4-ErpVR`, `M0-*` at a PDF, and unknown codes are all **errors**, not silent conversions."*
- `plan-03-pipelines.md` §3 — the acceptance commands, steps 2 and 4: the 13 single-file commands, then *"the errors that must NOT be silent conversions"* (`M0-ErVR` at `documentos/factura.pdf`; `M4-ErVR` at `documentos/foto.jpg`; `M1-ErpVRX`).
- `plan-03-pipelines.md` §3, observable evidence — the first row: *"all 13 resolve and produce output"*, guarding against *"`M4-ErVR`, `M4-ErpVR`, `M0-*` at a PDF, or an unknown code **silently converting** instead of erroring (`FR-25`, `FR-31`, `S3-T02`)"*.
- `plan-03-pipelines.md` §7b row 1 — *"The 13 codes are the only codes, and invalid ones error"*: a resolution test over all 13 plus `M4-ErVR`, `M4-ErpVR`, `M0-*` at a PDF, and an unknown code. What breaking it looks like: *"an invalid code silently converting — the substitution the whole design forbids."*
- `plan-03-pipelines.md` §6 step 2 — *"Confirm every code resolves before spending a corpus run."* This is the runbook step this issue exists to make pass.
- `kernel-cli.md` §5 — `model_unknown` and `provider_unknown` are the precedent for making *"there is no fallback"* assertable: the failure path exists, it is typed, and a test can reach it.
- `plan-03-pipelines.md` §13, Track 2 — *"Invalid codes are errors"*: golden artifact = `M4-ErVR`, `M4-ErpVR`, `M0-*` at a PDF, unknown codes; must fail when broken by a code **silently converting**; task `S3-T02`.
- `traceability.md` §3.1/§3.2, §4.1 **FR-25**, **FR-31**.

**Out of scope for this issue**
- **No ledger stage set.** `M1-ErpVR` recording no `segmenter`/`identifier`/`reconstructor`/`catalog` stage, and listing them in `not_applicable`, is `S3-T03` (E04).
- **No shape assertion across the 13.** That all 13 emit one field/verdict/trace shape is `S3-T13` (E07); this issue makes the codes exist to be compared.
- **No `--extractor` selector.** The alternative form — material chosen per file by Diagnosis — is `S3-T05` (E05).
- **No `--dry-run`** to inspect resolution without running. `# TODO: [MVP]` (`plan-03-pipelines.md` §2, deferred).
- **No setting or flag that changes a code's behaviour.** Corpus policy is registry data with no override; a code's thresholds may not come from the environment or a flag. **Never** (ADR-009, `prd.md` NFR-06a).
- **No `M-vRpVR` / embedding-based codes.** Perception is delegated to the model, not the application. **Never**.
- **No per-corpus engine choice, no `--no-validate`, no `--verify`.** **Never** (`prd.md` §10, ADR-001, ADR-002, ADR-006).
- **No new descriptor beyond the 13.** There is no `S3-T15`, and no fourteenth code exists (`plan-03-pipelines.md` §11: the 13 are enumerated).

**Effort**
**M** — thirteen files is not the cost; the cost is that three of the thirteen must **error** rather than run, that `M0-*`'s PDF refusal is a positive check rather than an absence, and that the set is verified as a set (count, `V` presence, no code outside the range) rather than one file at a time (`wbs.md` §7).

**Owner**
**Data** — the 13 descriptors live under `registry/pipelines/` (`wbs.md` §8).

**Frozen contract touched**
**Consumes** the Plan 2 row of `plans/README.md` §3 (the verdict-vector shape the codes must eventually emit unchanged — asserted by E07) and the Plan 1 row's descriptor shape. **Publishes the Plan 3 headline item**: *"The 13 descriptors and their stage sets"*, consumed by nothing that follows in the PoC.

---

## §4 Epic close condition

E01 is **`done`** when:

1. `E01-01` and `E01-02` are `done`, and
2. the capability is **demonstrable**: the count of descriptors is 13 and asserted; all 13 codes resolve to exit `0` against a single file; and the three invalid forms — `M4-ErVR`, `M4-ErpVR`, `M0-*` at a PDF and an unknown code — each produce a typed error, checked by running the commands, **not by reading the descriptors**.
3. **Plan 3 DoD, per epic:** no new kernel, no new component, no new kernel-boundary type — this epic adds configuration and data (`plan-03-pipelines.md` §10, Task DoD). A schema change that needed a new boundary type would mean a gate was closed early.

**Does E01 gate `S3-T14`?** **Transitively, and through the widest fan-out in the plan.** No entry in `S3-T14`'s dependency set names `S3-T01` or `S3-T02`. But four of the ten inter-epic edges leave E01 (`→ E04`, `→ E05` twice, `→ E07`), and each of those epics feeds the gate: E04 through `S3-T07`→`S3-T08`, E05 directly through `S3-T05`, E07 directly through `S3-T13`. So E01 reaches `S3-T14` through three different paths, and a regression here does not fail the gate's test — it changes what the gate's test is measuring.

---

## §5 Traceability

| Issue | FR / NFR (`traceability.md` §4) | Gap? | Evidence of the mapping |
|---|---|:---:|---|
| `E01-01` | **FR-25** (the descriptor is what a code resolves to) | no | Descriptor-schema failure stops the run; a malformed descriptor exits non-zero through `registry validate` |
| `E01-02` | **FR-25**, **FR-31** | no | All 13 resolve; `M4-ErVR`/`M4-ErpVR`/`M0-*` at a PDF/unknown codes all error |

No issue in E01 has an empty mapping, and no number was invented to make a row look complete. `traceability.md` §5 places `S3-T01`–`S3-T13` under `FR-25`…`FR-33`; E01 sits at the head of that range. This is the Plan 3-specific fact the index README states in §6: **no gap and no orphan task** at this stage.

**Question the epic file must ask and E01 does not close it:** #2 of `plan-03-pipelines.md` §12 — *what M0's targeted escalation means* — touches `E01-02` (the `M0-*` descriptors) and `E07-01` (`S3-T13`). It is carried **open**: `M0-*` is three of thirteen codes, and discovering here that M0 breaks an assumption the other ten materials share would invalidate the shape-identity test rather than one pipeline (`traceability.md` §7.2 recommends settling it before Stage 2; it is carried forward unresolved). E01 does not resolve it and must not be read as having done so.

---

## §6 Risks

From `plan-03-pipelines.md` §9 only:

| Risk | L | I | Why it touches E01 | Mitigation carried by this epic |
|---|:---:|:---:|---|---|
| *(none of the six §9 rows names `S3-T01` or `S3-T02`.)* | — | — | — | — |

**Stated rather than implied:** none of the six risk rows in `plan-03-pipelines.md` §9 names this epic's tasks. The plan's own *plan-specific execution risk* also does not land here — its three ways concern starting the corpus before `S3-T12`, running it before `S3-T08`'s invalidation is proven, and closing the gate without `S3-T13`. E01 is upstream of all three.

Two structural facts supply what the register does not, and they are why E01 is two issues wide and closes first:

- **Open decision #2 rides on `E01-02`.** The `M0-*` descriptors are where an unresolved escalation semantics question becomes data. Resolving it *badly* here — by giving M0 a render path it cannot have, since there are no pages and no image — would put a fiction in the registry that the shape-identity test would then certify. Carried open (`plan-03-pipelines.md` §12 #2).
- **`FR-31` is the register's real entry for this epic.** `traceability.md` §7.1 records that *"FR-31's M0 text input is covered by `S3-T02` only at Stage 3"* and that this is *"the reason `M0-*` is not on the critical path"*. The dependency is declared, not hidden, and it means `M0-*`'s three codes are the last three of the 13 to become exercisable — which is exactly why they are the codes an invalid-code test is most likely to catch converting silently.

---

