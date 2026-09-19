# E02 — Acquisition routing — Diagnosis & Reader

| Field | Value |
|---|---|
| Epic ID | **E02** |
| Capability | Routing each **page** to conversion or OCR on the basis of **quality**, and handing forward positioned tokens with no reading order resolved |
| Issues | `E02-01` (`S2-T04`) · `E02-02` (`S2-T05`) · `E02-03` (`S2-T06`) — all `todo` |
| Issue count | **3** |
| Owner layer | **Domain** (`wbs.md` §8) — `docflow/components/` |
| Wave span | **W1 → W3** (W1: 1 · W2: 1 · W3: 1) |
| Effort total | **2 × L · 1 × M** |
| Source plan | [`../../plan-02-components.md`](../../plan-02-components.md) §2, §4 entry conditions 4–6, §5 (`S2-T04`–`S2-T06`), §6 steps 1–2, §7a–§7b, §8, §9, §12 open decisions 4, 7, §13 Tracks 1–2 |
| Depends on other epics | **none** — E02 is a root of the Stage 2 graph and the head of the longest chain. It consumes `S1-T12`, `S1-T13`, `S1-T14` and `S1-T11` across the gate |

---

## §1 Objective

E02 delivers the decision layer that stands between a file and its text: **Diagnosis** decides, per page, *how* that page will be read — and **Reader** executes the decision along two paths that must never be confused. Two properties define the capability, and both are written as absences that a test can reach:

1. **Quality, not presence.** A page is routed to conversion because its text layer is *usable*, not because a text layer exists. `plan-02-components.md` §7b's row says it in four words — *the gate is quality, not presence* (`FR-15`) — and the failure it prevents is stated as what breaking it looks like: *"the page routes to conversion and the old OCR errors are dragged along **uncorrected**"*. A scan with a stale invisible OCR layer behind it reads as a *text* PDF to every naive probe.
2. **No engine setting, ever.** Docling is the OCR engine and only Docling, and there is **no engine flag**, on either surface (`ADR-001`, `prd.md` FR-16). Two reader paths, one engine decision — and the OCR path is reached by *routing*, never by a setting.

It is a separate deliverable because it is where the layer's most expensive mistake is *structural* rather than incremental: an illegible page that reaches OCR returns invented text that is indistinguishable from a real read. `plan-02-components.md` §7b names that outcome under *"a blurred image passed to OCR"* and `FR-15` calls it invalid — so the routing decision, not the reading, is the thing that has to be right.

**Position on the critical path — read this before scheduling.** E02 is the **head of the longest chain**. `S2-T04` is link 1 of the **nine-link** path `S2-T04 → T05 → T07 → T08 → T10 → T11 → T13 → T14 → S2-T17` (`plan-02-components.md` §5, `wbs.md` §6.2) — the chain whose lead time *is* the stage's lead time. Unlike `E01`, this epic cannot start late; it is also the epic that must not close early over a stub, because Track 1 for this layer is explicitly **on real adapters** (`plan-02-components.md` §13: *"Nothing here is stubbed"*, entry condition 4).

E02 produces **two** outgoing inter-epic edges — `E02 → E03` (from `S2-T07`) and `E02 → E09` (from `S2-T06`, a direct gate dependency) — and is the head of the longest chain in the plan.

---

## §2 Issues in this epic

| Issue | `wbs.md` task | Title | Wave | Depends on | Effort | PoC markers |
|---|---||---|---|:---:|---|:---:|---|
| `E02-01` | `S2-T04` | Diagnosis: quality-not-presence gate, three outcomes, adaptation | W1 | `S1-T12`, `S1-T13` → **Stage 1** (cross-gate) | L | `# TODO: [MVP]`: policy tuning UI; real legibility fixtures |
| `E02-02` | `S2-T05` | Reader: conversion path (`pdftotext`) and OCR path (Docling), routed **per page** | W2 | `S2-T04` → **E02** (intra) · `S1-T14` → **Stage 1** (cross-gate) | L | `# TODO: [MVP]`: OCR correction policy surface |
| `E02-03` | `S2-T06` | M2/M3 shared implementation with the rasterization switch at the front | W3 | `S2-T05` → **E02** (intra) | M | — |

Intra-epic edges (not drawn as epic edges): `E02-02` → `E02-01`; `E02-03` → `E02-02` — **2 edges**.

**This epic carries two register rows whose *Owner stage* is 2** — `pdftotext` as a poppler external binary and Docling install/portability — and it is where the `--engine`-shaped temptation is largest (`kernel-cli.md` §9, K4). It is also the epic whose `S2-T05` is the **`extract.r`** half of the closing chain and whose `S2-T06` closes **Branch B** for the gate.

---

## §3 Issue detail

### `E02-01` — implements `S2-T04`

**Title**
Diagnosis: quality-not-presence gate, three outcomes, adaptation.

**Context**
Three silent failures are decided here, and all three are the same mistake in different clothes: treating *the existence of something* as *the usability of it*. A page with a stale invisible OCR layer behind it *has* a text layer, so it routes to conversion and the old OCR errors are dragged along **uncorrected** — the page looks processed and is wrong. An illegible bitmap *has* pixels, so it reaches OCR and returns invented text indistinguishable from a real read (`FR-15` calls that outcome invalid). And a threshold that lives in a kernel is a threshold nobody can audit: `plan-02-components.md` §7b's fourth row states what breaking it looks like — *"`MIN_CHARS`/`MIN_DPI` hardcoded in a kernel; or settable from the environment (ADR-009)"*. This issue exists to make the routing decision an explicit, evidence-carrying verdict taken against **registry** policy, with the kernel reporting a measurement and taking no decision.

**Deliverable**
`docflow/components/diagnosis.py`

**Depends on**
`S1-T12`, `S1-T13` — **cross-gate** (Plan 1 → Plan 2). Diagnosis consumes K2's classification and `render` measurements and K3's `legibility` measurement; both are frozen at Gate 1 (`plan-02-components.md` §4 entry conditions 2–4). Intra-epic: none — this is the epic's root. Inter-epic: **none inward**; outward, `E02 → E09` arises from `E02-03`.

**Acceptance criteria**
- [ ] `docflow/components/diagnosis.py` exists and emits **three** outcomes: route to conversion, route to OCR, **route aside with a reason**.
- [ ] A page with a **stale invisible OCR layer is not routed to conversion** — the same fixture `kernel-cli.md` §11 row 3 uses (`scan-hidden-layer.pdf`), exercised through the component.
- [ ] An **illegible image routes aside with a reason** and **does not reach OCR** — the component-level counterpart of row 7 (`blurry.jpg`).
- [ ] `MIN_CHARS` and `MIN_DPI` are read from **K8** (`registry/policies/`) with **no CLI flag and no environment variable** (`ADR-009`, `prd.md` NFR-06a).
- [ ] A test asserts **no policy value can be set from the environment**; a test asserts **no `--min-chars`, `--min-dpi`, `--cut-confidence` or `--tolerance-amounts` flag exists** (§13 Track 4).
- [ ] **No threshold is a constant inside K3 or K4** — enforced by a grep-based test *and* by a test that changes the registry policy and observes the route change (`plan-02-components.md` §7b).
- [ ] The kernel reports the **measurement**; Diagnosis takes the **decision**. The component consumes `evidence` from K2/K3 and never re-measures by re-rendering.
- [ ] Routing is **per page**, not per document: a mixed PDF must be able to take both routes in one run — the precondition for `E02-02`'s per-page routing.
- [ ] Each routing outcome is recorded as **evidence**, so *why this page went to OCR* is answerable from the artifact.
- [ ] The component imports **ports only**; the import-isolation check passes over `docflow/components/diagnosis.py`.

**Test / evidence**
- `plan-02-components.md` §7b row 3 — *"Diagnosis gates on **quality**, not presence"*: test is *"a stale invisible OCR layer fixture"*; **breaking it looks like "the page routes to conversion and the old OCR errors are dragged along uncorrected"**; task cell `S2-T04` (`FR-15`).
- `plan-02-components.md` §7b row 4 — *"No threshold is a constant inside K3 or K4"*: test is *"grep + a test that changes the registry policy and observes the route change"*; **breaking it looks like "`MIN_CHARS`/`MIN_DPI` hardcoded in a kernel; or settable from the environment (ADR-009)"**; task cell `S2-T04` (`NFR-06a`).
- `plan-02-components.md` §13, Track 2 — the *"Quality, not presence"* golden artifact is *"a PDF with a stale invisible OCR layer"*, and it **must fail** when broken: *"it routes to conversion and drags the old OCR errors along"*.
- `plan-02-components.md` §7c — matrix rows the components must not break: **row 3** (*a stale invisible layer read as a text PDF*) exercised through *"`S2-T04` routing decision"*, and **row 7** (*a blurred image passed to OCR*) through *"`S2-T04` route-aside decision"*. Both still assert at the kernel layer (`S1-T22`); what this issue adds is the proof that the **wiring preserves them**.
- `plan-02-components.md` §6 steps 1–2 — the fixture is prepared and *"confirm the mode"*: `docflow-kernel pdf classify documentos/factura.pdf --page 1` must read `text`, with `invisible_text: false` and producer metadata consistent. The step's stated wrong result — *"`text` because a text layer exists rather than because it is usable — the gate is quality, not presence (`FR-15`)"* — is this issue's criterion.
- `plan-02-components.md` §8 — **FR-15**, **NFR-06a**; proof is *"Stale-invisible-layer not routed to conversion; illegible → route aside with a reason; the 'no policy value settable from the environment' test"*.
- `plan-02-components.md` §4 entry condition 5 — the registry **contains** the Stage 2 policy assets this issue consumes (`CUT_CONFIDENCE`, `MIN_CHARS`, `MIN_DPI` in `registry/policies/`) and no flag or variable exists for any of them.
- `plan-02-components.md` §11 — exit checklist items *"A page with a stale invisible OCR layer is **not** routed to conversion; an illegible image routes aside with a reason and does not reach OCR"* and *"No component imports an adapter; no threshold is a constant inside a component or a kernel"*.

**Out of scope for this issue**
- **No reading.** Diagnosis decides the route; it does not produce tokens. The Reader is `E02-02`.
- **No OCR correction.** Whether correction sits inside the OCR step is open decision **#4**, and its PoC answer is *"deferred"* (`S1-T14` marks the correction pass `# TODO: [MVP]`). This component does not implement it and does not depend on it. `# TODO: [MVP]`.
- **No `--min-chars`, `--min-dpi`, `--cut-confidence`, `--tolerance-amounts` or any policy flag.** **Never** (ADR-009, `NFR-06a`, §13 Track 4).
- **No policy value settable from the environment.** **Never** — the *operational*-settings precedence (CLI → env → `.env` → default, `NFR-06`) governs paths, slots, model and host only.
- **No threshold as a component or kernel constant.** **Never**.
- **No `--engine` setting and no second OCR engine.** **Never** (`ADR-001`, `FR-16`).
- **No legibility *decision* taken by the kernel.** The kernel reports the measurement and the reason; the decision is this component's (`plan-01-kernels.md`'s `E04-03` guardrail, reaffirmed in `plan-02-components.md` §5).
- **No policy tuning UI; no real legibility fixtures.** `# TODO: [MVP]`.
- **No adapter import.** **Never** (`sad.md` §1).
- **No merged-document or material-detection branching beyond the three outcomes** — multi-material routing over a folder is `S3-T05` (Plan 3).

**Effort**
**L** — two invariants whose tests must fail when broken (quality-not-presence; no-threshold-constant), three routing outcomes, per-page granularity, and a registry-policy dependency that has to be *changed* in a test to prove the constant is absent; fixture-backed, against a policy root (`wbs.md` §7).

**Owner**
**Domain** — `docflow/components/diagnosis.py` (`wbs.md` §8).

**Frozen contract touched**
**Consumes** `plans/README.md` §3, Plan 1 row — the port interfaces, the boundary types, the `KernelResult` evidence shape (the measurement it reads) and the closed `reason.code` set. **Contributes to** the Plan 2 row's *component artifact chain*: `work/<name>.diagnosis.json` (`sad.md` §9.1). It also consumes the §2 fixed-decision rows *"corpus policy lives in the registry (K8) with no CLI flag and no environment variable"* and *"no default or fallback model, engine or threshold exists anywhere"*.

---

### `E02-02` — implements `S2-T05`

**Title**
Reader: conversion path (`pdftotext`) and OCR path (Docling), routed **per page**.

**Context**
The Reader is where two silent failures become possible at once. The first is a *degrading* re-read: a page whose text layer is fine gets pushed through OCR anyway, and clean text comes back worse — `plan-02-components.md` §7b states it as *"a page with a usable text layer is re-read through OCR, degrading clean text"*. The second is an *absorbed* responsibility: if the Reader resolves reading order, it silently takes over part of the Reconstructor and removes that component's reason to exist — the plan's wording is *"ordered text, which would absorb part of the Reconstructor and remove its reason to exist"* (`FR-17`, row 6). This issue exists to keep the reader a **positioned-token producer with no order resolved** and to make the per-page routing assertable: the engine called on each page of a mixed PDF is a fact the test can read.

**Deliverable**
`docflow/components/reader.py`

**Depends on**
`S2-T04` — **intra-epic**. `S1-T14` — **cross-gate**: the Reader consumes the K4 `OcrEngine` port, frozen at Gate 1. The routing decision it executes is Diagnosis's; it makes none of its own. Inter-epic: **none**.

**Acceptance criteria**
- [ ] `docflow/components/reader.py` exists and routes **per page**, exposing the route taken for each page.
- [ ] A **mixed PDF combines both paths and joins at the end** — the documented criterion in `plan-02-components.md` §5.
- [ ] **Docling is never used on the conversion path** — asserted by a test that reads the engine called per page on a mixed PDF.
- [ ] The conversion path uses **`pdftotext`**, pinned; a missing binary produces a **typed `Reason`**, never a substitute reader.
- [ ] Output is **positioned tokens**, not ordered text: tokens carry boxes and the reader resolves **no reading order** — asserted at the reader boundary.
- [ ] **No `--engine` flag exists** on either surface — the contract test's assertion, carried into this issue's evidence (`FR-16`).
- [ ] No OCR engine setting and no fallback reader exists anywhere in the component. **No fallback reader** is the register row's mitigation, stated as an acceptance criterion rather than a convention.
- [ ] `entity`-level truncation and blank-page signals from K4 **survive** the reader: a truncated page does not become a page with no text (`kernel-cli.md` §11 row 11, `plan-02-components.md` §7c).
- [ ] The component imports **ports only**: the `OcrEngine` and `PdfSource` ports, never `docflow/adapters/docling.py` or a `pdftotext` runner from a component.
- [ ] Token confidence that is missing stays **missing** — no coercion to `1.0`, per K4's boundary and row 10 of the matrix.

**Test / evidence**
- `plan-02-components.md` §7b row 5 — *"The Reader never uses Docling on the conversion path"*: test is *"Assert the engine called per page on a mixed PDF"*; **breaking it looks like "a page with a usable text layer is re-read through OCR, degrading clean text"**; task cell `S2-T05` (`FR-16`).
- `plan-02-components.md` §7b row 6 — *"The Reader returns tokens, not ordered text"*: test is *"Assert no reading order is resolved at the reader boundary"*; **breaking it looks like "ordered text, which would absorb part of the Reconstructor and remove its reason to exist"**; task cells `S2-T05`, `S2-T07` (`FR-17`).
- `plan-02-components.md` §7c — matrix rows the components must not break: **row 11** (*a truncated page read as a page with no text*) exercised through *"`S2-T05` reader path, partial-failure emission"*, and **row 12** (*a truncated generation parsed as complete*) through *"`S2-T05`/`S2-T08` on the `p` path; contrast must not rescue a truncated read"*.
- `plan-02-components.md` §8 — **FR-16**, **FR-17**; proof is *"Mixed PDF joins two paths; Docling never on the conversion path; tokens carry boxes; contract test for the absent `--engine`"*.
- `plan-02-components.md` §11 — exit checklist items *"Docling is used **only** on the OCR path; the conversion path uses `pdftotext`; no engine setting exists on either surface"* and *"output is positioned tokens"* (the latter shared with `E03-01`, which consumes it).
- `plan-02-components.md` §13, Track 1 — the closing run requires `pdftotext` (a pinned binary) and Docling (adapter installed) to be **real**: *"The M2/M3 paths and OCR tokens are unproven"* if Docling is not.
- `wbs.md` §9 — *"`pdftotext` is a poppler external binary"* (M/M, owner stage 2): mitigation is *"Pin a version; a missing binary is a typed `Reason`, never a fallback reader (`S2-T05` must not invent a reader)"*. This issue **is** that mitigation.
- `plan-02-components.md` §4 entry condition 4 — `pdftotext` pinned, Docling installed, for the closing flow.

**Out of scope for this issue**
- **No M2/M3 switch.** The shared implementation with the rasterization switch at the front is `E02-03`.
- **No routing decision.** Per-page routing is *executed* here and *decided* in `E02-01`; a Reader that re-judges quality duplicates the gate.
- **No reading order and no layout.** Ordering is `E03-01`'s; the boundary refuses it here **and the Reconstructor's reason to exist depends on that refusal**. A table's **cells** may cross (opt-in, `read(tables=True)`, `E04-04`'s amendment) and its **structure** never does — which leaves this component exactly the work it had: cells at known positions are material, and a grid is a reconstruction.
- **No OCR correction.** `# TODO: [MVP]` — and whether it belongs inside the OCR step is open decision **#4**, carried in §6 below, not resolved.
- **No `--engine` flag, no second engine, no engine setting.** **Never** (`ADR-001`, `FR-16`).
- **No fallback reader when `pdftotext` is absent.** **Never** (`wbs.md` §9) — the temptation to "just use OCR instead" is exactly the silent substitution the architecture forbids.
- **No adapter import.** **Never** (`sad.md` §1).
- **No OCR correction policy surface.** `# TODO: [MVP]`.
- **No token ordering, sorting or sequence field** anywhere on the output.

**Effort**
**L** — two reader paths over two different external binaries, a per-page routing assertion, a boundary that must *refuse* to do work (ordering) rather than do it, and two invariants that must fail when broken; heavyweight external dependencies (`wbs.md` §7).

**Owner**
**Domain** — `docflow/components/reader.py` (`wbs.md` §8).

**Frozen contract touched**
**Consumes** `plans/README.md` §3, Plan 1 row — `OcrEngine` and `PdfSource` from the port row, `Token`/`Evidence`/`Reason` from the types row, and the determinism classes (the conversion path is `deterministic`, the OCR path is `sampled` — which is why the artifact it produces is evidence and not a cache). **Contributes to** the Plan 2 row's *component artifact chain*: `work/<name>.tokens.json` (`sad.md` §9.1).

---

### `E02-03` — implements `S2-T06`

**Title**
M2/M3 shared implementation with the rasterization switch at the front.

**Context**
`M2` and `M3` are two of the thirteen codes, and their only difference is whether the input is rasterized before it is read: the same OCR path, one step earlier. Implemented twice, the two prefixes drift — and the plan states the consequence precisely: *"two code paths drift, making six of the thirteen 'three designs with a prefix' an accident"* (`FR-32`). That sentence is the whole issue. The thirteen codes are supposed to be **three designs with a material prefix**; the moment `M2` and `M3` are two implementations rather than one plus a switch, the shape-identity claim `S3-T13` must verify becomes an accident of two codebases that happen to agree today.

**Deliverable**
`docflow/components/reader.py` (continuation of `E02-02`'s file)

**Depends on**
`S2-T05` — **intra-epic**. Externally: Plan 1's frozen row via E02's root. Inter-epic: **none inward**.

**Acceptance criteria**
- [ ] `M2` and `M3` are served by **one code path**; the difference is the `K2.render` step at the **front**, and nothing else.
- [ ] A test **asserts the switch**: with the rasterization step disabled the path is `M3`'s, with it enabled the path is `M2`'s, and **no other branch exists** between them.
- [ ] The test **fails** if a second code path is introduced — i.e. it observes the switch rather than the two labels.
- [ ] The rasterization step is `K2.render` reached through the **`PdfSource` port**, never through an adapter import.
- [ ] The switch is not a CLI setting: material selection per file is `S3-T05` (Plan 3), and `--extractor r|p|rp` is `S3-T05`'s flag. This issue implements the *shared* code path, not the selection surface.
- [ ] Neither `M2` nor `M3` exists as a pipeline descriptor here: the thirteen descriptors are `S3-T02`. This issue proves the two codes *can* be one implementation.
- [ ] No threshold, no engine and no model is introduced by the switch.

**Test / evidence**
- `plan-02-components.md` §7b row 7 — *"M2 and M3 share one implementation"*: test is *"Assert `K2.render` is the only difference"*; **breaking it looks like "two code paths drift, making six of the thirteen 'three designs with a prefix' an accident"**; task cell `S2-T06` (`FR-32`).
- `plan-02-components.md` §5, `S2-T06`'s verifiable cell — *"`M2` and `M3` differ **only** by the `K2.render` step; one code path, verified by a test that asserts the switch"*.
- `plan-02-components.md` §8 — **FR-32**; proof is *"A test asserting the rasterization switch is the only difference between M2 and M3"*.
- Downstream consumption: `S3-T02` (Plan 3) builds the 13 descriptors on this shape, and `S3-T13` asserts shape identity across all 13 (`FR-33`). `plan-02-components.md` §13, Track 3 — *"Plan 3 can wire the 13 codes onto this chain and emit the frozen verdict-vector and trace shapes unchanged for all 13"*. **A drifting `M2`/`M3` is the way that claim fails.**
- `plan-02-components.md` §7d — *"The 13 pipeline codes … Stage 3 owns the routes; Stage 2 exercises **one** canonical `ErpVR` code"*: this issue does not add a route, it removes a duplication.
- `plan-02-components.md` §11 — exit checklist item *"The 10 components each run standalone from the previous component's artefact"* covers this file; the closing run (`E09-01`) uses `M1-ErpVR`, so this issue is proven by test, not by the gate.

**Out of scope for this issue**
- **No `--extractor` or `--pipeline` flag.** Both are `S3-T05`/`S3-T02` (Plan 3); a flag here would put a route on a component surface.
- **No pipeline descriptors.** The thirteen are `S3-T02`.
- **No `M0`/`M4` behaviour.** `M0` accepts text and errors on a PDF (`FR-31`, `S3-T02`); `M4` is `S3-T02`'s. This issue is about one switch, not four prefixes.
- **No second OCR engine.** The shared path uses K4/Docling, and there is **no engine setting** on it. **Never** (`ADR-001`).
- **No shape change to the token artifact.** The same `.<step>.json` chain (`work/<name>.tokens.json`) is produced regardless of prefix — which is what Track 3 requires.
- **No new stage.** The switch is *inside* the reader step; the plan's open decision **#4** notes that resolving OCR correction the other way *"would add a stage to the M2/M3 prefix, i.e. a ledger stage that `S3-T03` would have to derive"* — the same reasoning applies here and this issue adds no stage.

**Effort**
**M** — one switch, but the verification is a *negative* structural claim (no second path exists) that must be written against the implementation rather than a value, plus the interaction with the rasterization step reached through a port. A fixture alone cannot express it (`wbs.md` §7).

**Owner**
**Domain** — `docflow/components/reader.py` (`wbs.md` §8).

**Frozen contract touched**
**Consumes** `plans/README.md` §3, Plan 1 row — `PdfSource` (the `render` operation) and the boundary types; **consumes** the Plan 2 row's *component artifact chain* by producing the same `.<step>.json` output for both prefixes. Freezes nothing new — but it is the structural precondition for the Plan 2 row's *verdict-vector shape* being emitted unchanged for all 13 codes (`FR-33`).

---

## §4 Epic close condition

E02 is **`done`** when:

1. all three issues are `done` — including `E02-03`, whose deliverable is a continuation of `E02-02`'s file and whose criterion is a structural assertion about *absence*;
2. the capability is **demonstrable**, and checked by running it: a stale-invisible-layer fixture is routed **away from** conversion; a blurred image is routed **aside with a reason** and never reaches OCR; a test **changes a registry policy value and observes the route change**; a mixed PDF takes both reader paths page by page and the engine called on each page is asserted; and the reader emits **no ordered text**.

**Does E02 gate `S2-T17`?** **Yes, twice and directly.** `S2-T06` is named in `S2-T17`'s dependency set (`wbs.md` §4), making **E02 → E09** a direct inter-epic edge — and `S2-T06` is the tail of **Branch B**. `E02 → E03` is also direct, from `S2-T07`'s dependency on `S2-T05`. Both chains that leave this epic converge on the gate.

**And it is the chain that cannot slip.** `S2-T04` is **link 1 of the nine-link longest chain** (`plan-02-components.md` §5, `wbs.md` §6.2). Unlike Branch A, a late start here is a late close, because every later link waits on it. The plan's Track 1 note is explicit about the consequence: the closing run must be **on real adapters** — *"Plan 1 was allowed to close over faked ports. **This one is not**"* (`plan-02-components.md` §13).

---

## §5 Traceability

| Issue | `wbs.md` task | FR / NFR (`traceability.md` §4) | Gap? | Evidence of the mapping |
|---|---|:---:|---|
| `E02-01` | `S2-T04` | **FR-15** ("Diagnosis: quality, not presence") · **NFR-06a** ("policy is registry data, not configuration") | no | Stale-invisible-layer not routed to conversion; illegible → route aside with a reason; the "no policy value settable from the environment" test |
| `E02-02` | `S2-T05` | **FR-16** ("Docling fixed; correction never digits") · **FR-17** ("Positioned tokens, no reading order") | no | Mixed PDF joins two paths; Docling never on the conversion path; tokens carry boxes; contract test for the absent `--engine` |
| `E02-03` | `S2-T06` | **FR-32** ("M2/M3 one implementation, switch at front") | no | A test asserting the rasterization switch is the only difference between M2 and M3 |

No issue in E02 has an empty mapping. `traceability.md` §5 traces `S2-T01`–`S2-T15` to `FR-12…FR-24` as a group, which places this epic's three tasks inside a stated requirement block rather than leaving them orphaned.

Note the deliberate attribution inside **FR-16**: `traceability.md` §4.1 assigns it to `S2-T05` **and** `S1-T14` — the component and the kernel adapter, both — because the fix is fixed at both layers and the `--engine`-absence test covers both. **FR-17** does the same for the tokens boundary.

---

## §6 Risks

From `plan-02-components.md` §9 only — the rows whose mitigation is carried by this epic:

| Risk | L | I | Why it touches E02 | Mitigation carried by this epic |
|---|:---:|:---:|---|---|
| **`pdftotext` is a poppler external binary** | M | M | `S2-T05` **is** this row's mitigation target: the conversion path is the one that would be silently substituted. | `E02-02` requires a **pinned** version, and a **missing binary produces a typed `Reason`, never a fallback reader** — carried as an acceptance criterion, not a convention (`wbs.md` §9: *"`S2-T05` must not invent a reader"*) |
| **Docling install / portability** — heavy dependency, platform-specific backend, GPU variant differences | M | H | The OCR path is `E02-02`'s; if Docling is not real, *"the M2/M3 paths and OCR tokens are unproven"* (`§13` Track 1). | Docling is bound behind the K4 port (Plan 1), reached from this component **through the port only**; the adapter revision is pinned into the cache key and `engine_info` is recorded in evidence (`wbs.md` §9). `E02-03`'s shared path is what keeps the portability exposure to **one** OCR implementation rather than two |
| **GPU availability for local models** (Ollama) | M | H | Not this epic's adapter, but the `p`-path reads that follow the reader are `EpVR`'s second read, and the closing run needs a model pulled with its digest recorded (`plan-02-components.md` §4 entry condition 4). | The register's mitigation — *"Typed error naming the remedy; `gpu` slot bounded to one generation per device; **never** a silent fallback model"* — is Plan 1's mechanism (`S1-T09`, `E04-05`) and is **consumed** here: this epic must not paper over a missing model with a substitute read. Stated so the exposure is visible in the epic that first needs the model |

**Register rows excluded by the plan's own filter, stated rather than implied.** `plan-02-components.md` §9 keeps only rows whose *Owner stage* includes 2. Four such rows do **not** materialise here: **Frontier LLM cost per token** (`E03`, `E06`, `E09`), **Segmenter merged-document gap** (`E01`), **Sampled artifact regenerated** (`E03`, `E06`, `E09`) and **Unknown wording variants** (owner stage 3, §1's register). Naming them here prevents this epic from reading as risk-free by omission.

**Open decisions carried, not resolved:**

| `plan-02-components.md` §12 | Question | Touches in E02 | Effect if deferred past Stage 2 |
|---:|---|---|---|
| **#4** | **Whether OCR correction is inside the OCR step.** `02-components.md` has the Reader correcting OCR output (characters and spacing, never digits, raw retained); the M2/M3 prefixes are written as a single `OCR` step, so correction is either inside it or absent | `S2-T05`, `S2-T06` | The PoC answer is *"correction is deferred"* (`S1-T14` marks the pass `# TODO: [MVP]`), *"which is consistent and closes the flow"*. Resolving it the other way *"would add a stage to the M2/M3 prefix, i.e. a ledger stage that `S3-T03` would have to derive"* — which would change the Plan 2 row's *component artifact chain*. **Carried here as `# TODO: [MVP]`; not resolved** |
| **#7** | **Whether `pdftotext`'s dependency needs a stated fallback.** Today a missing binary is a typed `Reason` and never a fallback reader — *"which is the correct PoC answer"* | `S2-T05` | *"Resolved by refusal"* for the PoC: a fallback reader *"would reintroduce exactly the silent substitution the architecture forbids"*. Listed as open because *"the question of an operator-facing remedy message is not settled"* — so the **message** may change; the **absence of a fallback** may not |

Open decisions **#1** (`S2-T12` vs `S2-T17`), **#2** (M0 escalation), **#3** (critical field), **#5** (`r` vs `p` tie-break) and **#6** (Reviewer aggregation) touch `E03`, `E04`, `E05`, `E06`, `E07` and `E09`. **#3** is load-bearing and reviewed **before `S2-T11` starts** (`plan-02-components.md` §12); **#2** is named by `traceability.md` §7.2 as *"the one item that should be settled before Stage 2"* — both are carried in the epics that act on them, and neither is resolved here.
