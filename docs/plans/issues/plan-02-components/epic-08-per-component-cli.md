# E08 — Per-component CLI — the probe surface (`docflow`)

| Field | Value |
|---|---|
| Epic ID | **E08** |
| Capability | Running any one of the 10 components from the previous component's artifact to its own, without repeating the ones before it |
| Issues | `E08-01` (`S2-T16`) — status `todo` |
| Issue count | **1** |
| Owner layer | **Surface** (`wbs.md` §8) — `docflow/cli.py` |
| Wave span | **W9** |
| Effort total | **1 × M** |
| Source plan | [`../../plan-02-components.md`](../../plan-02-components.md) §2, §3, §5 (`S2-T16`), §6 step 4, §7b row 20, §8, §11, §12 open decision 6 (adjacent), §13 Track 4 |
| Depends on other epics | **E06** (emission — the Contract & the verdict vector) |

---

## §1 Objective

E08 delivers the **probe surface**: each of the 10 components invocable on its own, reading the previous component's artifact and writing its own, along the chain `sad.md` §9.1 documents. `plan-02-components.md` §13 Track 4 names the requirement in the user's own terms — this surface *"is what `my_prompt.md` asked for **by name**: `"docflow segmentador"`, `"docflow identificador"`"* — and gives the operational reason alongside it: it is *"the only practical way to debug a verdict: re-run `docflow consistency` alone over an existing artifact instead of re-walking the chain."*

It is a **separate epic with one issue** because it owns a different deliverable surface from everything else in Stage 2. `wbs.md` §8 assigns `docflow/cli.py` to the **Surface** layer; every other Stage 2 task belongs to **Domain** (`docflow/components/`). **This is the same structural fact that gave Plan 1's `S1-T18` its own single-issue epic**, and Plan 1's `epic-06` §1 states the reason: a table that folded the Surface task into a Domain epic *"would put two different owner layers inside one epic"*. `S2-T16` is the exact analogue, and the index README's §2 records that this distinction is why Stage 2 has **9** epics rather than 8.

Three properties define the capability, and two of them are absences:

1. **One component, one step.** *"Each of the 10 components runs standalone from the previous component's artifact to its own; re-running one stage does not repeat the ones before it"* (`FR-12`). The failure it prevents is named in the plan's §7b: *"upstream stages re-execute, defeating the point of a per-component surface"*.
2. **No shortcut around validation.** *"No `--no-validate` on any surface"* — a validation-free variant *"would emit fields with no verdicts, needing two shapes downstream"* (`FR-18`, ADR-002). This is the component-level instance of index README §7's non-negotiable 2, and the Surface is where the *absence* is assertable across the whole product.
3. **No policy flag.** *"No `--min-dpi`, `--cut-confidence`, `--min-chars`, `--tolerance-amounts`"*, because *"Policy is registry data; a flag would change output without entering the cache key (ADR-009, `NFR-06a`)"*.

It also carries the *separation* obligation that Plan 1's `E06-01` established on the other surface: **`docflow run --pipeline` belongs to Plan 3; these 10 belong to the components** — *"Two surfaces, one operation layer beneath both."*

**Position on the critical path — read this before scheduling.** E08 is **not a gate dependency**. `wbs.md` §6.2 lists `S2-T16` among the tasks *"that can slip without delaying a stage close"*, and `plan-02-components.md` §5 draws it with *"parallel · not a gate dependency"*. `S2-T17`'s dependency set does not name it, which is why the index README's graph draws **`E06 → E08` and no `E08 → E09`**.

**But the timing of this epic is constrained by Plan 1's own lesson.** `plans/README.md` §6 states it as a rule for all three layers: *"**Track 4 opens in the same wave as the operation it exposes**, never later. A command surface added after the fact is a surface with no contract test, and `S1-T21`'s flag/port test only means something while the port signature is still in hand."* `S2-T16` depends on `S2-T14`, so it is first-satisfied at Wave 8 and lands in Wave 9 — immediately after the vector is frozen, and before the gate closes. It may slip **past** the close; it may not be *bolted on afterwards*.

---

## §2 Issues in this epic

| Issue | `wbs.md` task | Title | Wave | Depends on | Effort | PoC markers |
|---|---||---|---|:---:|---|:---:|---|
| `E08-01` | `S2-T16` | Per-component CLI subcommands with the documented read/write artifact chain | W9 | `S2-T14` → **E06** (inter) | M | `# TODO: [MVP]`: `--show-evidence`, `--schema` |

No intra-epic edges exist: E08 has a single issue.

This epic produces **one** incoming inter-epic edge — `E06 → E08` — and **no outgoing edge**. It is a leaf of the epic graph, and the **only** epic in Stage 2 whose owner layer is not Domain.

---

## §3 Issue detail

### `E08-01` — implements `S2-T16`

**Title**
Per-component CLI subcommands with the documented read/write artifact chain.

**Context**
Two failures are prevented by the same surface, and they pull in opposite directions.

- **Re-walking the chain.** If invoking one component re-runs its predecessors, then the per-component surface is a convenience wrapper rather than a probe: debugging a verdict re-acquires the document, re-reads its pages and re-validates them, which both costs and *changes the artifact under inspection*. `plan-02-components.md` §7b's twentieth row states the failure as *"upstream stages re-execute, defeating the point of a per-component surface"*, and §3's evidence table gives the artifact-level version: *"a component that re-runs its predecessors, or an intermediate that is not the previous component's artefact"*.
- **A shortcut around validation.** A `--no-validate`-shaped flag on this surface would emit fields with no verdicts — *"needing two shapes downstream"*, i.e. every consumer would have to handle a document whose fields may or may not be judged. The plan's §7b row for it is an **absence assertion**, and Track 4 lists it as the property *"No shortcut around validation"*.

The third constraint is that this surface stays a **surface**: `plan-02-components.md` §13 Track 4's last row is *"The pipeline surface stays separate"* — `docflow run --pipeline` is Plan 3's, and the 10 component subcommands are the components'. A flag here that selected a pipeline would put a route on a component surface, which is the same class of error Plan 1 forbade when it insisted `docflow run` never invokes `docflow-kernel`.

**Deliverable**
`docflow/cli.py` (continuation of the file `S1-T18` created)

**Depends on**
`S2-T14` — **inter-epic** (E06 → E08). The subcommands dispatch to component operations whose output shape is frozen by the Contract; a surface added before the vector exists would be a surface with nothing stable to expose, which is exactly what `plans/README.md` §6 warns against. Intra-epic: n/a. Inter-epic: this is the epic's only edge.

**Acceptance criteria**
- [ ] `docflow/cli.py` exposes **10** per-component subcommands, one per component, forming the read/write artifact chain of `sad.md` §9.1.
- [ ] Each subcommand runs **from the previous component's artifact to its own**: `docflow segmenter documentos/escaneo.pdf --out work/` → `work/escaneo.segments.json`, `docflow identifier work/escaneo.segments.json --out work/` → `work/escaneo.identity.json`, and so on through `.diagnosis.json`, `.tokens.json`, `.document.json`, `.validated.json`, `.consistency.json`, `.catalog.json` (`plan-02-components.md` §3's command block).
- [ ] **Re-running one stage does not repeat the ones before it** — asserted by running `docflow validator` alone over an existing artifact and observing that no upstream stage re-executes (`FR-12`).
- [ ] The consumed artifact **is the previous component's artifact**: a component that re-derives its input, or that reads an artifact named differently from the documented chain, fails the test.
- [ ] **There is no `--no-validate` flag on this surface** — asserted by a contract test over the whole command set (`FR-18`, `ADR-002`).
- [ ] **No policy flag exists**: no `--min-dpi`, `--cut-confidence`, `--min-chars`, `--tolerance-amounts`, and no environment variable substitutes one (`ADR-009`, `NFR-06a`).
- [ ] **No `--pipeline` flag and no `--extractor` flag** on this surface: the pipeline surface belongs to Plan 3, and a route flag here would put a route on a component surface.
- [ ] `docflow run` still **never invokes** the kernel lab surface, and this epic adds no invocation of it (`kernel-cli.md` §2, Plan 1's `E06-01` criterion carried forward).
- [ ] The 10 subcommands are **1:1 with component operations** — no flag exists without a counterpart, and no subcommand performs a decision of its own.
- [ ] `--show-evidence` and `--schema` do **not** exist in the PoC: evidence is in the artifact, not behind a flag.

**Test / evidence**
- `plan-02-components.md` §7b row 20 — *"Per-component invocation does not repeat predecessors"*: test is *"Re-run `validator` alone"*; **breaking it looks like "upstream stages re-execute, defeating the point of a per-component surface"**; task cell `S2-T16` (`FR-12`).
- `plan-02-components.md` §7b row 9 — *"No code path skips validation"*, whose test is *"Contract test asserting no `--no-validate` exists, **on either surface**"*; the task cell is `S2-T08` (`FR-18`, `ADR-002`), and **this surface is the second of the two** — carried here as an explicit acceptance criterion.
- `plan-02-components.md` §13, Track 4 — the property table for this surface: *"One component, one step"*; *"Standalone debugging: `docflow consistency work/<name>.validated.json`"*; *"No shortcut around validation — no `--no-validate` on any surface"*; *"No policy flag"*; *"The pipeline surface stays separate"*. And the closing line: *"The chain of artifacts is the contract — which is why the subcommands and the code share a freeze, not just a release."*
- `plan-02-components.md` §3, acceptance commands — the ten standalone commands in order, which **are** this issue's acceptance test as written:
  `docflow segmenter documentos/escaneo.pdf --out work/` · `identifier` · `diagnosis` · `reader` · `reconstructor` · `validator` · `consistency` · `catalog` · `contract` · `reviewer queue --out work/`.
- `plan-02-components.md` §3, evidence table — the `work/` intermediates row: correct is *"the documented chain: `.segments.json` → `.identity.json` → … → `.catalog.json` → result"*; wrong is *"a component that re-runs its predecessors, or an intermediate that is not the previous component's artefact"*.
- `plan-02-components.md` §6 step 4 — *"Walk the chain standalone (the ten commands in §3). Run each component against the previous one's artefact"*: correct is *"each artefact is the documented one …, and each step reads the previous one"*; wrong is *"a component that silently re-runs its predecessors, or an artefact named differently in the docs than on disk"*. This step is a **runbook step**, and the correct result is exactly what this issue must make true.
- `plan-02-components.md` §8 — **FR-12**; proof is *"Each component runs from the previous artefact; re-running one stage does not repeat the earlier ones"*.
- `plan-02-components.md` §11 — exit checklist items *"The 10 components each run standalone from the previous component's artefact, and re-running one does not repeat the ones before it"* and *"**Doc-sync:** `prd.md`, `sad.md`, `wbs.md`, `traceability.md` still agree with what was built"* — the artefact *names* are checked against `sad.md` §9.1, which is why a mismatch between the docs and the disk fails this issue rather than a documentation review.
- `plan-02-components.md` §13, Track 4's opening — *"This surface is what `my_prompt.md` asked for **by name**"* (`FR-12`, `S2-T16`).
- `plans/README.md` §6 — *"Track 4 opens in the same wave as the operation it exposes, never later"*; the six-layer rule that makes Wave 9 the right slot rather than "after the gate".
- `wbs.md` §8 — the ownership table: **Surface** owns `docflow/cli.py`; the Domain layer owns `docflow/components/`. This issue is the only Stage 2 task under Surface.

**Out of scope for this issue**
- **No `--no-validate` on any surface.** **Never** (`ADR-002`, `FR-18`) — and the contract test is written across the command set, not per-command.
- **No policy flag and no policy environment variable.** **Never** (ADR-009, `NFR-06a`) — *"a flag would change output without entering the cache key"*.
- **No `--pipeline`, `--extractor`, `--force`, `--stage`, `--only`.** The pipeline surface and its flags are Plan 3's (`S3-T02`, `S3-T05`, `S3-T08`). A route on a component surface is not deferred work; it is the wrong surface. `# TODO: [MVP]` for the flags themselves, **Never** for their presence *here*.
- **No `--show-evidence`, `--schema`, `--format md|html`, `--keep-artifacts`, `--isolate`.** `# TODO: [MVP]` (`plan-02-components.md` §2, §5).
- **No `--verify` flag.** Verification is an outcome of reading a ledger, never a request — on any surface, in any stage (`ADR-006`, `kernel-cli.md` §9). **Never**.
- **No batch or mirrored-tree behaviour.** `docflow/batch.py` is `S3-T06` (Plan 3), and the mirrored tree is `S3-T06`'s.
- **No invocation of `docflow-kernel`.** **Never** (`kernel-cli.md` §2/§15; Plan 1's `E06-01` criterion carried forward).
- **No component decision made in the CLI.** A subcommand dispatches to an operation; a CLI that re-judges a route or widens contrast has become a second implementation. **Never** (`kernel-cli.md` §3's guardrails, applied to the product surface).
- **No stability promise to a third party.** This is a PoC surface; its flags may change. `# TODO: [RELEASE]`.

**Effort**
**M** — ten subcommands over an artifact chain, with two *absence* assertions across the whole command set (no validation shortcut, no policy flag) and one *non-repetition* assertion that requires running a late stage alone and observing that nothing upstream re-executed; interacting concerns without a heavyweight dependency (`wbs.md` §7).

**Owner**
**Surface** — `docflow/cli.py` (`wbs.md` §8). **This is the only issue in Stage 2 whose owner is not the Domain layer**, which is precisely why this epic is cut on its own (index README §2).

**Frozen contract touched**
**Consumes** `plans/README.md` §3, Plan 2 row — *the component artifact chain `.<step>.json`* (the filenames **are** this surface's interface) and *the verdict-vector shape* (what the terminal subcommands read and write). **Consumes** the Plan 1 row's `KernelResult` JSON envelope and 5 exit codes, inherited through `S1-T18`'s file. **Consumes** the fixed decisions of §2: *"there is no `--verify` flag and no `--no-validate` flag, in any stage, on either surface"* and *"corpus policy lives in the registry (K8) with no CLI flag and no environment variable"*. It freezes nothing new — but it is where those two absences become **testable across the product**.

---

## §4 Epic close condition

E08 is **`done`** when:

1. `E08-01` is `done`, and
2. the capability is **demonstrable, from a shell**: the ten standalone commands of `plan-02-components.md` §3 run in order, each reading the previous component's artifact and writing its own with the documented name; `docflow validator` re-run alone over an existing `work/<name>.document.json` produces its own artifact with **no upstream stage re-executing**; and a contract test over the whole command set **fails** if a `--no-validate`-shaped flag or any policy flag (`--min-dpi`, `--cut-confidence`, `--min-chars`, `--tolerance-amounts`) exists.

**Does E08 gate `S2-T17`?** **No — and this must be stated plainly rather than left to inference.** `S2-T16` does **not** appear in `S2-T17`'s dependency set (`wbs.md` §4). `wbs.md` §6.2 lists it among the tasks that can slip past a stage close, and `plan-02-components.md` §5 draws it with *"parallel · not a gate dependency"*. The index README's §3 graph therefore draws `E06 → E08` and **no `E08 → E09`**; that absence is a derived fact, not an omission.

**Does E08 gate anything else?** **No.** Nothing in Stage 2 or Stage 3 depends on `S2-T16` (`wbs.md` §4's `Depends on` column contains no reference to it). It is doubly terminal, exactly as `E07` is.

**Why Track 4's timing rule still applies.** `plans/README.md` §6: *"Track 4 opens in the same wave as the operation it exposes, never later. A command surface added after the fact is a surface with no contract test."* `S2-T16` depends on `S2-T14`, so its earliest satisfaction is Wave 8 and its slot is Wave 9 — the *same wave* as the gate, and immediately behind the freeze it exposes. Slip is permitted **past** the close; being added after the fact is not, because the artifact chain this surface exposes is the thing `sad.md` §9.1 and the Plan 2 frozen row describe, and a surface built against a moved chain would document the wrong interface.

---

## §5 Traceability

| Issue | `wbs.md` task | FR / NFR (`traceability.md` §4) | Gap? | Evidence of the mapping |
|---|---|:---:|---|
| `E08-01` | `S2-T16` | **FR-12** ("10 components standalone via CLI") | no | Each component runs from the previous artifact; re-running one stage does not repeat the earlier ones |

No gap: `traceability.md` §4.1 assigns **FR-12** to `S2-T16` alone, and the reverse check (`traceability.md` §5) traces *"`S2-T16`, `S2-T17` → FR-12, FR-21, FR-24 — the per-component surface and the Stage 2 close"*. This issue is the per-component surface half of that pair, and it is one of only three Stage 2 issues with a **single-task, single-FR** assignment (with `E01-01`'s FR-13 and `E01-03`'s FR-14).

**The deliberate asymmetry worth recording.** `FR-12` covers *"10 components standalone via CLI"* — and the traceability table gives it **two** tasks: `S2-T16` (the surface) and `S2-T17` (whose demo *"walks the standalone chain"*, `plan-02-components.md` §8's `S2-T17` row). So the requirement is satisfied twice over: once by the surface existing, once by the gate exercising it. This epic owns the first; `E09` owns the second. Neither alone closes `FR-12`, which is why the plan lists FR-12 in both rows rather than choosing.

---

## §6 Risks

From `plan-02-components.md` §9 only — the rows whose mitigation is carried by this epic:

| Risk | L | I | Why it touches E08 | Mitigation carried by this epic |
|---|:---:|:---:|---|---|
| *(none of the six §9 rows names `S2-T16`.)* | — | — | — | — |

**Stated rather than implied:** none of the six risk rows in `plan-02-components.md` §9 names `S2-T16`. This epic is one of only two in Stage 2 about which that can be said (with `E07`), and the reason is structural: this task has no external dependency, no sampled artifact, no cost implication and no gate obligation.

**The risk that *does* attach to E08 is not a register row, and it comes from `wbs.md` §9 instead.** The row **"The kernel CLI lab surface drifts into a second product API"** (`wbs.md` §9, owner stage 1) is a risk about the *other* surface, and its mitigation names the direction that touches this epic: **`docflow run` never invokes `docflow-kernel`**. Plan 1 carried that prohibition as a criterion of `E06-01`; this issue carries it forward on the same file, so the separation is asserted at both ends. It is **not restated as a second risk**.

**The second non-register risk is the one this epic's timing exists to prevent**, and `plans/README.md` §6 names it: *"A command surface added after the fact is a surface with no contract test."* Plan 1 learned it against `S1-T21` (the flag/port contract test that *"only means something while the port signature is still in hand"*). Stage 2's version is milder — the artifact chain is documented in `sad.md` §9.1 rather than held in a signature — but the wave rule is the same, which is why the slot is Wave 9 and not "after the gate".

**Register rows whose *Owner stage* is 2 that do not touch E08, stated rather than implied.** All six of `plan-02-components.md` §9's rows touch other epics: **Docling install/portability**, **`pdftotext` as a poppler binary**, **GPU availability** (`E02`, consumed onward), **Frontier LLM cost per token** (`E04`, `E06`), **Segmenter merged-document gap** (`E01`) and **Sampled artifact regenerated** (`E03`, `E06`, `E09`). Naming them prevents this epic from reading as unexamined by omission.

**The plan's four named execution risks, checked against this epic.** None is *about* E08 — they land on `E01` (branch A late), `E03` (`S2-T08` deferred), `E04`/`E05`/`E06` (`S2-T12` undecided) and `E09` (single-read primitive). The third has one consequence this epic inherits rather than causes: if open decision **#1** is resolved by moving the Catalog onto the critical path, the artifact chain's *ordering* is unchanged — `catalog` already sits between `consistency` and `contract` in `plan-02-components.md` §3's command block — but the **stage set** the ledger derives changes at `S3-T03`. This surface is unaffected, and saying so is cheaper than leaving it to be re-derived.

**Open decisions carried, not resolved:**

| `plan-02-components.md` §12 | Question | Touches in E08 | Effect if deferred past Stage 2 |
|---:|---|---|---|
| **#6** | **Whether the Reviewer's cases are aggregated after the run** | Indirect: `docflow reviewer queue --out work/` is one of the ten commands, and what it writes is the per-document case set | **PoC answer, not a gap:** per-document closure *"is enough for the gate"*; aggregation is a workflow feature. This surface exposes the per-document verb and nothing more |
| **#3** | **What defines a "critical field"** | Indirect: no command here may take a policy value, so the critical-field set cannot be passed through this surface at all | **Load-bearing, reviewed before `S2-T11` starts**; it decides *"what `S3-T04` must ship"*. Carried in `E04`/`E06` |

Open decisions **#1** (Catalog vs gate), **#2** (M0 escalation), **#4** (OCR correction), **#5** (`r` vs `p` tie-break) and **#7** (`pdftotext` fallback) touch `E02`, `E03`, `E04`, `E05` and `E06`; none is resolved here. **#4**'s alternative resolution *"would add a stage to the M2/M3 prefix"* — which would change the artifact chain this surface exposes; the surface would then gain a step, not a flag, and that is recorded here as the one open decision with a direct consequence for this issue's deliverable list.
