# E07 — Kernel lab CLI (`docflow-kernel`) & the silent-failure suite

| Field | Value |
|---|---|
| Epic ID | **E07** |
| Capability | `docflow-kernel` as a lab surface — entry point, exit-code contract, JSON envelope, one command per port method — and the 17-row silent-failure suite that asserts each kernel's characteristic failure on its own |
| Issues | `E07-01` (`S1-T20`) — `todo` · `E07-02` (`S1-T21`) — `todo` (partial completion) · `E07-03` (`S1-T22`) — `todo` |
| Issue count | **3** |
| Owner layer | **Kernels** (`wbs.md` §8) — `docflow/kernel_cli/`, `tests/kernel_cli/`, `fixtures/` |
| Wave span | **W2 → W5 → W6** (W2: 1 · W5: 1, opening · W6: 1) |
| Effort total | **2 × L · 1 × M** |
| Source plan | [`../../plan-01-kernels.md`](../../plan-01-kernels.md) §2, §3, §5 (`S1-T20`–`S1-T22`), §6 step 13, §7b–§7c, §8, §9 execution risk, §12 open decisions 1, 2, 3, §13 Track 2/4 |
| Depends on other epics | **E01** (boundary types) · **E04** (ports & adapters) |

---

## §1 Objective

E07 delivers the **Stage 1 acceptance harness**. Its capability is not "there is a CLI": it is that **each kernel's characteristic silent failure becomes an invocable, CI-asserted command**, runnable before any domain component exists. `kernel-cli.md` §1 states the motivation in the user's own terms: *the kernels are a cornerstone of the project, so they must be tested independently before the domain layer is built on top of them.* Without this epic, the 17-row matrix exists only as prose, and the first time a kernel fails silently is inside a domain component — where the failure is attributed to the wrong layer.

It is a separate deliverable because it is a **different audience on a different surface**. `docflow-kernel` is a bench, not the product: it may change freely, nothing downstream may depend on it, and `docflow run` never invokes it (`kernel-cli.md` §2). It is also the **shorter chain** — `S1-T20 → S1-T21 → S1-T22`, 3 links against the serial spine's 9 — which runs in parallel with the kernel chain, covers a different scoped area, and converges with it on the gate. That is exactly why it must not be folded into E04 or E05: the harness and the kernels it exercises are built concurrently, and a single epic would force a sequence that `wbs.md` §6.2 deliberately avoids.

---

## §2 Issues in this epic

| Issue | `wbs.md` task | Title | Wave | Depends on | Effort | PoC markers |
|---|---||---|---|:---:|---|:---:|---|
| `E07-01` | `S1-T20` | `docflow-kernel` entry point: dispatch, `--list`, exit codes, JSON envelope, `--save` via K7 | W2 | `S1-T01` → **E01** (inter) | M | `# TODO: [MVP]`: `[dev]` extra; `--format yaml` |
| `E07-02` | `S1-T21` | Per-kernel subcommands, 1:1 with port methods | W5 (**opens**) · completes only when W3's adapters are terminal and `S1-T17` resolved them | `S1-T20` → **E07** (intra) · `S1-T12`…`S1-T17` → **E04** (inter) | L | `# TODO: [MVP]`: cover newly landed `MVP` commands as they arrive |
| `E07-03` | `S1-T22` | Silent-failure suite: one assertion per row of the 17-row matrix | W6 | `S1-T21` → **E07** (intra) | L | `# TODO: [MVP]`: fixture generator; fast vs gated subset for K4–K6 |

Intra-epic edges (not drawn as epic edges): `E07-02` → `E07-01`; `E07-03` → `E07-02`.

**This epic carries the plan's two named execution risks internally** (`plan-01-kernels.md` §9): opening `E07-02` before E04's adapters are terminal makes the contract test pass *vacuously*; and closing `E08-01` before `E07-03` leaves the matrix as prose. See §6.

---

## §3 Issue detail

### `E07-01` — implements `S1-T20`

**Title**
`docflow-kernel` entry point: subcommand dispatch, `--list`, the exit-code contract (`0`/`2`/`3`/`4`/`1`), the `KernelResult` JSON envelope, `--save` routed through K7.

**Context**
A kernel that fails silently is discovered late and blamed on whatever consumed it. The cheapest structural defence is to make the *process* encode the kernel contract: exit `0` = a value with evidence, exit `2` = no value with a typed reason, exit `3` = the call could not legitimately be made, exit `4` = usage, exit `1` = a bug. Once that exists, a shell can distinguish *the document's answer* from *the call's precondition* from *a broken build* — and every downstream assertion in this epic becomes a one-line check rather than a code review.

**Deliverable**
`docflow/kernel_cli/__init__.py`, `docflow/kernel_cli/main.py` — a **package**, never a `kernel_cli.py` module beside it.

**Depends on**
`S1-T01` — **inter-epic** (E01 → E07). It consumes the boundary types and defines no new one.

**Acceptance criteria**
- [ ] `docflow/kernel_cli/` is a **package** with `__init__.py` and `main.py`; there is **no** `docflow/kernel_cli.py` module beside it.
- [ ] The `[project.scripts]` entry point `docflow-kernel = "docflow.kernel_cli:main"` resolves and runs.
- [ ] **All five exit codes are reachable and unit-tested**: `0`, `2`, `3`, `4`, `1`.
- [ ] **stdout is valid JSON on every path that emits a `KernelResult`** — exits `0`, `2` and `3` — and the envelope is the same shape on all three, differing only in the code.
- [ ] Exits `4` and `1` emit **no** `KernelResult`.
- [ ] **stderr carries nothing a script parses** — it is the human log, and `docflow-kernel … | jq` is safe.
- [ ] `--list` reports **the 8 kernels** with determinism class and adapter availability, and an unavailable adapter reports `no`, **never silently replaced**.
- [ ] `--list` is at the kernel level and does not conflate adapter availability with per-command status (`kernel-cli.md` §4).
- [ ] `--save` routes bytes **through K7**, so the recorded hash is the real content hash of what was written; without `--save`, stdout carries a descriptor and the bytes stay out of band.
- [ ] Exit `2` is reserved for a typed `Reason` from the port: an unexpected exception is reported as `1`, never as `2`.
- [ ] The exit-code contract itself is asserted by unit tests, so *"`2` used for a genuine error"* is a red test.

**Test / evidence**
- `plan-01-kernels.md` §8 — five exit codes unit-tested; envelope validity on `0`/`2`/`3`. Requirements **FR-06** (process-level encoding of no-third-state) and *(no FR — see the gap note in §5)*.
- `plan-01-kernels.md` §7b — *"Exit `2` is reserved for a typed `Reason`"*: exit-code unit tests; breaking it looks like *"an unexpected exception is reported as `2`, collapsing expected negative into broken"*.
- `plan-01-kernels.md` §6 step 12 — *"Exercise the exit contract"*: reach `0`, `2`, `3`, `4` and `1` deliberately; validate stdout with `jq` on each of `0`/`2`/`3`; the envelope is the same JSON on all three emitting exits, `4` and `1` emit no `KernelResult`, and stderr never carries anything a script parses.
- `plan-01-kernels.md` §6 step 2 — *"Confirm the inventory"*: `docflow-kernel --list` shows all 8 rows, `available` reflects reality, K4/K5 read `sampled`, K6 `external`, K1/K2/K3/K7/K8 `deterministic`; the wrong result is an unavailable adapter reported `yes` — a silent fallback in the one place it is most expensive.
- `kernel-cli.md` §5 — the full exit table and the reason it distinguishes `2` from `3` from `1`.
- `kernel-cli.md` §6 — the output contract: stdout is a single JSON document in the existing `KernelResult[T]` shape, **no new type introduced**; `call_record` populated for K5/K6 only; `--save` writes `<dir>/<sha256>.png` plus the descriptor.
- `plan-01-kernels.md` §3, evidence table — *"Exit codes across the harness"*: `0`, `2`, `3`, `4`, `1` all reachable and unit-tested; stdout valid JSON on exits `0`, `2`, `3`. The wrong result: a script that cannot distinguish the document's answer from the call's precondition from a bug.

**Out of scope for this issue**
- **No per-kernel subcommands.** `E07-02` fills them in as adapters land. This issue delivers the dispatcher, the contract and `--list`.
- **No assertions about kernel behaviour.** The suite is `E07-03`.
- **No `--fallback` / `--default-model` flag.** **Never** — the worst failure this layer can have (`kernel-cli.md` §8).
- **No `--verify` flag and no ledger-trust `verify` subcommand.** **Never** (`kernel-cli.md` §9).
- **No `--engine` flag** for OCR. **Never** (ADR-001).
- **No verdict, score or routing decision on stdout.** The CLI prints the raw `KernelResult` (`kernel-cli.md` §3, guardrail 2). **Never**.
- **No `--format yaml`.** `--format json` is default and only. `# TODO: [MVP]`.
- **No `[dev]` extra.** `docflow-kernel` is still installed with the release package. `# TODO: [MVP]` — move it into a `[dev]` extra so nothing downstream can depend on it.
- **No stability promise.** This surface may change freely; nothing downstream may depend on it. **Never** a public API.

**Effort**
**M** — one dispatcher plus a contract with five reachable paths and a stdout/stderr split, all of which must be unit-tested rather than exercised by hand; no external dependency, but the `--list` honesty check and the `--save`-through-K7 routing are separate concerns (`wbs.md` §7).

**Owner**
**Kernels** — `docflow/kernel_cli/` (`wbs.md` §8).

**Frozen contract touched**
**Freezes** `plans/README.md` §3, Plan 1 row: *the `KernelResult` JSON envelope and the 5 exit codes*. It also freezes the *closed set of `reason.code` values* in the sense that the envelope must carry a code on exits `2` and `3` — the vocabulary itself is `kernel-cli.md` §5.

---

### `E07-02` — implements `S1-T21`

**Title**
Per-kernel subcommands, 1:1 with port methods, filled in as each adapter lands.

**Context**
A command surface added after the fact is a surface with no contract test, and a lab CLI that grows a convenience flag becomes a second API maintained in parallel — at which point the dependency arrow stops pointing down and the kernel layer loses the reuse property that justifies it. This issue exists to keep the surface **1:1 with the ports**: every command is one port method, every flag is a port parameter, and a flag with no counterpart fails the suite.

**Deliverable**
`docflow/kernel_cli/{orchestrator,store,registry,pdf,image,ocr,llm}.py`

**Depends on**
`S1-T20` — **intra-epic** · and **each of `S1-T12`–`S1-T17` as it completes** — **inter-epic** (E04 → E07). This is the plan's **partial-completion issue**: it *opens* in W5 when `S1-T20` lands, and it **completes only when W3's adapters are terminal and `S1-T17` has resolved them**.

**Acceptance criteria**
- [ ] The subcommand modules exist under `docflow/kernel_cli/`: `orchestrator`, `store`, `registry`, `pdf`, `image`, `ocr`, `llm`.
- [ ] **Every `now` command in `kernel-cli.md` §9 dispatches.**
- [ ] **Every `MVP` command exits `4`** naming the operation as unavailable — never a silent partial run.
- [ ] The **flag/port contract test** compares each dispatched command's flag set against its port signature and **fails on any flag with no counterpart**.
- [ ] The contract test **also fails on forbidden vocabulary**: no `--field`, `--invoice`, `--cuit`, `--total`, `--document-type`, `--pipeline`, `--validator`, `--extractor`, `--golden` appears on the lab surface.
- [ ] No `--engine` flag exists (guards `FR-16`); no `--no-validate`-shaped flag exists (guards `FR-18`); no `--api-key` flag exists (guards `NFR-05`).
- [ ] `--out` and `--root` are not conflated: K1 receives `--out` (where a run's artifacts go), K7/K8 receive `--root` (which store or registry a kernel reads).
- [ ] The contract test does **not pass vacuously**: it is scoped to the `now` set and re-checked as each adapter lands, so a command whose adapter has not landed has no port signature to be compared against and is not counted as a pass.
- [ ] **Partial completion is explicit:** this issue stays `open` (not `done`) while any of `S1-T12`–`S1-T17` is unfinished, and its status records which inputs are missing.
- [ ] `docflow run` never invokes `docflow-kernel`, and no command on this surface names a document concept.

**Test / evidence**
- `plan-01-kernels.md` §7b — *"One command = one port method"*: the `S1-T21` flag/port contract test; breaking it looks like *"a convenience flag appears with no port counterpart and the CLI becomes a second API"*. And *"No flag names a document concept"*: the same test, forbidden vocabulary.
- `plan-01-kernels.md` §8 — the flag/port contract test; it guards **FR-16**, **FR-18** and **NFR-05**. *(**No FR of its own — see the gap note in §5.**)*
- `kernel-cli.md` §3 — the three guardrails: one command = one port method with zero logic in the CLI; never emit a verdict, a score or a routing decision; no silent fallback.
- `kernel-cli.md` §9 — the per-kernel tables with a `now`/`MVP` status per command, and the statement that `S1-T21`'s done-when asserts on the `now` set only.
- `kernel-cli.md` §10 — the allowed flag vocabulary and the forbidden flag vocabulary; the `--out` vs `--root` boundary.
- `kernel-cli.md` §15 — *"Flag drift"* and *"The lab surface becomes the real API"*, both mitigated by this contract test.
- `plan-01-kernels.md` §9, execution risk 1 — **the named failure mode of this issue**: *"Opening `S1-T21` before `S1-T12`–`S1-T17` are terminal. … With no adapter landed there is no signature to compare against, so the test passes **vacuously** — a green suite that proves nothing, and the first flag drift appears later, at the kernels' real consumer."* Mitigation: the done-when is scoped to the `now` set and re-checked as each adapter lands.
- `plan-01-kernels.md` §13, Track 4 — `docflow-kernel`, a **package**, with one subcommand per port method and the 5-exit-code contract; and the property table: 1:1 with the ports; no domain noun; `MVP` commands exit `4`; not a product surface.

**Out of scope for this issue**
- **No dispatch mechanics.** Argument parsing, the exit-code contract, the JSON envelope and `--list` are `E07-01`.
- **No assertions.** The silent-failure suite is `E07-03`.
- **No `MVP` command implementation.** An `MVP` command exits `4` naming the operation as unavailable; implementing one is out of Stage 1 scope. `# TODO: [MVP]`: cover newly landed `MVP` commands as they arrive.
- **No `--verify`, no `--engine`, no `--fallback`/`--default-model`, no `--api-key`, no `--no-validate`.** **Never** (`kernel-cli.md` §14).
- **No domain noun in any command, flag or parameter.** **Never** (`kernel-cli.md` §10).
- **No product-surface behaviour and no invocation from `docflow`.** **Never** (`kernel-cli.md` §2/§15).
- **No `[dev]` extra** and no `--format yaml`. `# TODO: [MVP]` — carried by `E07-01`.

**Effort**
**L** — seven command modules across eight kernels, plus a contract test that must introspect port signatures and compare flag sets, and a completion condition that depends on six other tasks. The verification is structural and spans the epic boundary (`wbs.md` §7).

**Owner**
**Kernels** — `docflow/kernel_cli/*` (`wbs.md` §8).

**Frozen contract touched**
**Consumes** the Plan 1 row of `plans/README.md` §3 — the port interfaces (its flag sets *are* the port signatures) and the 5 exit codes. It enforces the §2 fixed decisions *"the OCR engine is Docling, only, and is never a setting"*, *"validation is never skippable"* and *"no default or fallback model, engine or threshold exists anywhere"* by making each a testable absence.

---

### `E07-03` — implements `S1-T22`

**Title**
Silent-failure suite: one assertion per row of the 17-row matrix, with the committed fixtures.

**Context**
A green suite that asserts on message text, or on a value a sampled kernel cannot promise, proves nothing and hides regressions. This issue turns each of the matrix's rows into an assertion on a **machine-checkable `reason.code`** against a committed fixture — so a row is closed when its assertion runs in CI, and a failure names the failure rather than a sentence. Sixteen rows are the Stage 1 gate; row 15's command is `MVP`, so it is **declared and gated**, asserting the moment `judge` lands.

**Deliverable**
`tests/kernel_cli/`, `fixtures/`

**Depends on**
`S1-T21` — **intra-epic**. Externally: E01, E04 via the chain E01 → E07 → E04 → E07.

**Acceptance criteria**
- [ ] `tests/kernel_cli/` and `fixtures/` exist, and each fixture is **named for the failure it provokes** (`kernel-cli.md` §12).
- [ ] The **16** rows whose commands are `now` run in CI against a committed fixture: rows 1–14, 16 and 17.
- [ ] Every assertion targets a **`reason.code`** from the closed set — **never a message string**.
- [ ] **Row 15 is declared and gated**, not dropped: it is present in the suite as a declared, gated assertion that fires the moment `judge` lands, and its `MVP` command exits `4` until then.
- [ ] `--repeat` proves **identical hashes** for the deterministic kernels (K1, K2, K3, K7, K8) and **differing hashes** for the sampled ones (K4, K5).
- [ ] `--repeat` is **never** used to retry until two answers agree — the prohibition is documented and the attempt count makes the pattern visible.
- [ ] The suite **fails** when a fixture's provoking condition is removed, i.e. each row asserts the negative outcome rather than merely producing output.
- [ ] Rows whose assertion is a **difference between two invocations** (14, 16) drive the CLI twice; they cannot be expressed by `--repeat` (`kernel-cli.md` §12).
- [ ] Row 14's unreachable-provider variant is expressed by pointing the host setting at a **closed port**, with the absence/`null`/present distinction asserted for the first two against a live provider.

**Test / evidence**
- `kernel-cli.md` §11 — the 17-row matrix, each row with its command and its assertion; the statement that **sixteen of the seventeen rows are in the Stage 1 CI gate** and that a row is closed when its assertion runs in CI against a committed fixture.
- `kernel-cli.md` §12 — the fixture list, one per row: `synthetic-3stage.yaml`, `scan-hidden-layer.pdf`, `scan150.pdf`, `three-invoices.pdf`, `rotated.jpg`, `blurry.jpg`, `page.png`, `blank.png`, `lowconf.png`, `large.pdf`, `oversized-prompt.txt`, `model-swap.md`, `golden-samples.json` + governor model, `registry-broken/`; and the four rows needing no committed document (13, 14, 16 and rows 1–2's generator) because they are **procedures** over artifacts other rows produce.
- `plan-01-kernels.md` §7b — *"`--repeat` is not retry-until-agreement"*: documented prohibition plus the recorded attempt count; breaking it looks like *"a test loops `--repeat` until two hashes agree — manufacturing contrast"*.
- `plan-01-kernels.md` §6 step 13 — *"Run the suite"*: `pytest tests/kernel_cli/` and `pytest tests/`; 16 rows green, row 15 declared, the Stage 1 integration test green; every assertion targets a `reason.code`; `--repeat` shows identical hashes for deterministic kernels and differing hashes for sampled ones. The wrong result: a green suite asserting on message strings or on values a sampled kernel cannot promise.
- `plan-01-kernels.md` §3 — `pytest tests/kernel_cli/` is named as proof that 16 of the 17 matrix rows assert against a committed fixture and target a `reason.code`.
- `plan-01-kernels.md` §7c — the matrix table by row and status: rows 1–14, 16, 17 are `now` — Stage 1 gate; **row 15 is `Declared and gated`** — *"its command `llm.frontier judge` is `MVP` in `kernel-cli.md` §9, so the row asserts on `role_conflict` the moment `judge` lands. Not a Stage 1 gate and not silently dropped."*
- `plan-01-kernels.md` §8 — 16 rows assert in CI; row 15 declared and gated. *(**No FR of its own — see the gap note in §5.**)* Carries **NFR-02**/**NFR-03** evidence through rows 1, 2 and 16.
- `plan-01-kernels.md` §7c — the three acceptance scenarios: *Resume after a forced kill* (`S1-T19` + `S1-T18` + `S1-T07`), ***A sampled artifact is evidence, not a cache*** — which closes at **`S1-T08`**, **asserted through `S1-T22`** — and *Verification is not optional* (`S1-T10`, asserted through `S1-T19` step 9).
- `plan-01-kernels.md` §13, Track 2 — the 17 committed fixtures, each named for the failure it provokes and each asserting a `reason.code`, never a message string; and the *"Sampling discipline"* golden evidence.
- `plans/README.md` §4 — the harness chain *"cannot slip **past** `S1-T19`"*: without `S1-T22`, the 17-row matrix exists only as prose.

**Out of scope for this issue**
- **No row 15 assertion in the Stage 1 gate.** `judge` is `MVP`; the row is **declared and gated**, and this issue must describe it that way — **not as dropped** (`kernel-cli.md` §11, `plan-01-kernels.md` §7c).
- **No message-string assertions.** **Never** — assertions target a `reason.code` from the closed set (`kernel-cli.md` §5).
- **No value assertions on a sampled or external kernel.** A test may assert on `evidence` (K4/K5) and on `call_record` (K6). **Never** on the value (`kernel-cli.md` §7).
- **No retry-until-agreement.** **Never** (`kernel-cli.md` §7).
- **No golden set proper.** The labeller role and the comparator are deferred (`D4`, `traceability.md` §3.4). What Stage 1 has instead is an assertion per row targeting a machine-checkable code, so it cannot be self-graded (`plans/README.md` §6). `# TODO: [MVP]`.
- **No fixture generator.** The fixtures are committed. `# TODO: [MVP]` — generate them synthetically where possible rather than committing real documents.
- **No fast/gated split.** The K4–K6 rows need GPU, tokens and provider availability; the suite is not yet split, which is `plan-01-kernels.md` §12 open decision **#3**. `# TODO: [MVP]`: fast subset vs gated subset.
- **No domain behaviour tested.** Any field, verdict, document type or pipeline route is out of Stage 1 by construction (`plan-01-kernels.md` §7d). The 13 pipeline codes are `S3-T02`. Merged-document detection is **Never**.

**Effort**
**L** — seventeen rows, each needing a fixture or a two-invocation procedure and an assertion on a machine-checkable code, plus the two determinism-class demonstrations and the declared/gated row. The cost is breadth of verification, not implementation size (`wbs.md` §7).

**Owner**
**Kernels** — `tests/kernel_cli/`, `fixtures/` (`wbs.md` §8).

**Frozen contract touched**
**Consumes** the Plan 1 row of `plans/README.md` §3 — the *closed set of `reason.code` values* (this issue is what makes the set load-bearing) and the 5 exit codes. Freezes nothing new.

---

## §4 Epic close condition

E07 is **`done`** when:

1. all three issues are `done` — including `E07-02`, which by construction cannot close before W3's adapters are terminal and `S1-T17` has resolved them;
2. the capability is **demonstrable**: `docflow-kernel --list` is honest about the 8 kernels; every `now` command dispatches and every `MVP` command exits `4`; the flag/port contract test passes with no orphan flag and no forbidden vocabulary; and **16 of the 17 matrix rows assert in CI** against committed fixtures targeting a `reason.code`, with **row 15 declared and gated on `judge`**.

**Does E07 gate `S1-T19`?** **Yes, and it is the chain the plan singles out.** `S1-T22` is a **hard predecessor** of `S1-T19` (`wbs.md` §3, §6.2), making E07 → E08 a direct inter-epic edge. The harness chain is **3 links** (`T20 → T21 → T22`) against the serial spine's **9**, so it does not *lengthen* the critical path — but it **cannot slip past `S1-T19`** (`plans/README.md` §4, `wbs.md` §6.2), and because it is shorter it is the chain that must not slip: closing the gate without these rows means the three scenarios Stage 1 owns are proven only through the integration path, and rows 1–2 stay prose.

---

## §5 Traceability

| Issue | `wbs.md` task | FR / NFR (`traceability.md` §4) | Gap? | Evidence of the mapping |
|---|---|:---:|:---:|---|
| `E07-01` | `S1-T20` | **FR-06** (process-level encoding of no-third-state) — **and no FR of its own** | **partial gap** | Five exit codes unit-tested; envelope validity on `0`/`2`/`3` |
| `E07-02` | `S1-T21` | *(no FR of its own)* — **guards** FR-16 (no engine setting), FR-18 (no `--no-validate`), **NFR-05** (no key flag) | **gap** | The flag/port contract test |
| `E07-03` | `S1-T22` | *(no FR of its own)* — **carries** **NFR-02**/**NFR-03** evidence through rows 1, 2 and 16 | **gap** | 16 rows assert in CI; row 15 declared and gated |

### Gap flagged — E07's three issues have no FR, and one of them is a *requirement gap, not an orphan task*

`plan-01-kernels.md` §8 states this as the **gap note**, and this epic preserves it rather than filling it:

- **What is missing:** `S1-T20`, `S1-T21` and `S1-T22` — the kernel CLI harness — have **no functional requirement** in `traceability.md` §4.1. Nothing in FR-01 … FR-33 names the lab surface.
- **Why this is not orphan work:** `traceability.md` §5 traces the harness to a **stated user requirement**, not to an FR: the harness exists because the user required that *the kernels be a cornerstone of the project, so they must be tested independently before the domain layer is built on top of them* (`kernel-cli.md` §1). **ADR-004** is the architectural form of the same requirement (a kernel layer reusable beyond this project). A requirement exists; it is simply not numbered in §4.1.
- **What closing it would cost:** adding an FR for *"the kernel layer is reusable and independently testable"* — which changes `prd.md`. That is an artifact change, out of scope for a plan, and **out of scope for this directory**.
- **Do not fill the gap by inventing a number.** `traceability.md` §8 rule 2 applies at every stage close: *a new task without an FR is a finding* — and this finding is already recorded.
- **Note `E07-01`'s partial mapping:** it carries one genuine FR, **FR-06** (*"No third state at any boundary"*), as a **process-level** encoding of the same invariant the types encode in-process. The rest of `S1-T20` is unnumbered, which is why the row reads *partial gap*.

No issue in E07 has a mapping that was invented to make it look complete.

---

## §6 Risks

From `plan-01-kernels.md` §9 only:

| Risk | L | I | Why it touches E07 | Mitigation carried by this epic |
|---|:---:|:---:|---|---|
| **The kernel CLI lab surface drifts into a second product API** | M | M | `E07-02` **is** the surface at risk, and `E07-01` is the dispatcher that could grow a convenience flag. | `docflow run` never invokes `docflow-kernel`; the `S1-T21` contract test fails on any flag with no port counterpart; `# TODO: [MVP]` a `[dev]` extra. All three carry into acceptance criteria here. |
| **`--repeat` used as retry-until-agreement** in the harness | L | H | The harness is where `--repeat` is *used*; the attempt count that makes the pattern visible is `E05`'s mechanism, asserted here. | Documented prohibition (`kernel-cli.md` §7); the orchestrator records an attempt count, so the pattern is visible if it happens. Carried as an explicit acceptance criterion of `E07-03`. |
| **Lab fixtures drift from the kernel behaviour they assert** | M | M | `E07-03` owns the fixtures. A fixture that no longer provokes its failure yields a green suite that proves nothing. | Each fixture is named for the failure it provokes; `S1-T22` asserts a `reason.code`, never a message string; and the suite must **fail** when the provoking condition is removed. |

**Both of the plan's named execution risks are inside this epic** (`plan-01-kernels.md` §9 — *"Plan-specific execution risk — the one that bites if the wave order is violated"*):

| # | The violation | Which issue it lands on | Mitigation carried here |
|---:|---|---|---|
| 1 | **Opening `E07-02` before `S1-T12`–`S1-T17` are terminal.** With no adapter landed there is no port signature to compare against, so the contract test passes **vacuously** — a green suite that proves nothing, and the first flag drift appears later, at the kernels' real consumer. | `E07-02` | Its done-when is scoped to the `now` set and **re-checked as each adapter lands**; its status is explicitly *partial* while any of `S1-T12`–`S1-T17` is unfinished. |
| 2 | **Closing `E08-01` before `E07-03`.** The gate would close with rows 1–2 as prose, and the first silent kernel failure would be attributed to the wrong layer. | `E08-01` (guarded by `E07-03`) | `S1-T22` is a **hard predecessor** of `S1-T19`; E07 → E08 is drawn as a direct edge in the index README. |

The wave map is therefore not a preference: Waves 5 and 6 exist so that the harness chain and the serial kernel chain converge on the gate with both chains complete.

**Open decisions carried, not resolved:**

| `plan-01-kernels.md` §12 | Question | Touches in E07 | Effect if deferred past Stage 1 |
|---:|---|---|---|
| **#1** | Whether the kernel CLI may execute a descriptor whose stages are domain components | `S1-T20`, `S1-T21`, and `S1-T19`'s descriptor shape | Stage 1's flow stays **synthetic by construction** — the intent — but the same command cannot debug a real pipeline graph. Resolving it "yes" would let a domain noun into the lab surface, which `kernel-cli.md` §10's forbidden vocabulary refuses |
| **#2** | Whether `--save` needs an explicit `--root` | `S1-T20` (`--save` routed through K7), `S1-T22`'s fixture assertions | A default temp root makes a hash real but the artifact disposable, so a test can pass over bytes already gone — a green assertion with nothing behind it |
| **#3** | Whether the 17-row matrix runs in CI at all stages, or only at Stage 1 | `S1-T22`'s suite structure | Rows for K4–K6 need GPU, tokens and provider availability. Unsplit, the suite becomes flaky and then ignored — which is how an acceptance harness dies. `# TODO: [MVP]`: fast subset vs gated subset |

Open decisions **#4** (`registry hash` per-asset) touches `S1-T04`/`S1-T05` (E03); **#5** (Docling's determinism class) touches `S1-T14` (E04) and `S1-T08` (E05); **#6** (regeneration policy) and **#7** (GPU slots) touch `S1-T08` and `S1-T09` (E05). None is resolved anywhere in this directory.
