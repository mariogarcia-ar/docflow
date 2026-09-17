# E04 — Ports & the acquisition/generation adapters (K2–K6)

| Field | Value |
|---|---|
| Epic ID | **E04** |
| Capability | The five port interfaces plus the thin acquisition (K2/K3) and generation (K4/K5/K6) adapters, and resolution by capability |
| Issues | `E04-01` (`S1-T11`) — status `done` · `E04-02` (`S1-T12`) — **`in progress`**, 1 criterion unmet (§3) · `E04-03` (`S1-T13`) — **`in progress`**, 1 criterion unmet (§3) · `E04-04` (`S1-T14`) · `E04-05` (`S1-T15`) · `E04-06` (`S1-T16`) · `E04-07` (`S1-T17`) — `todo` |
| Issue count | **7** |
| Owner layer | **Kernels** (`wbs.md` §8) — `docflow/ports/`, `docflow/adapters/`, `docflow/kernels/` |
| Wave span | **W2 → W4** (W2: 1 · W3: 5 · W4: 1) |
| Effort total | **4 × L · 2 × M · 1 × S** |
| Source plan | [`../../plan-01-kernels.md`](../../plan-01-kernels.md) §2, §5 (`S1-T11`–`S1-T17`), §7a–§7d, §8, §12 open decisions 3, 5, 6 |
| Depends on other epics | **E01** (boundary types) |

---

## §1 Objective

E04 delivers the layer that touches the outside world: **five port interfaces** (`PdfSource`, `OcrEngine`, `LlmEngine`, `ArtifactStore`, `Registry`) and **thin adapters behind them** — Poppler-backed PDF, a raster library, Docling for OCR, Ollama for local generation, one frontier provider — plus **resolution by capability, with fail-fast and no fallback**.

It is a separate deliverable because the whole reuse claim of the project rests on it. `ADR-004` requires kernels usable beyond this project, and the property that makes that true is structural, not stylistic: **no adapter may be imported from a port**, so the dependency arrow only ever points down. Reusability here is *tested, not asserted* — the import-isolation check plus a fake adapter satisfying each port (`plan-01-kernels.md` §13, Track 3).

E04 also carries the layer's worst failure. *"A silent fallback to a default model is the worst failure this layer can have"* (`kernel-cli.md` §3) — so `E04-07` exists to make *there is no fallback* an **assertable fact** with typed, reachable failure paths (`model_unknown`, `provider_unknown`) rather than a stated intention.

**One operation was added during implementation, and it is not part of the contract.** `E04-02` gained `kernel.pdf.layout_text`, which returns the reader's own character grid (`pdftotext -layout`). It is deliberately **kernel-only**: `plans/README.md` §3 freezes the port interfaces, so an operation added to `PdfSource` would re-open `E04-01`'s gate. It is not wired into any flow, nothing depends on it, and it is recorded here rather than silently absorbed. Its relationship to `extract_tokens` is measured, not asserted — see §3 `E04-02`.

**Position on the critical path — read this before scheduling.** E04 is **not** on the serial kernel spine: `wbs.md` §6.2 lists `S1-T11`, `S1-T12`, `S1-T13` and `S1-T16` as *able to slip without delaying a stage close*, and the plan's Track 1 closes over **faked ports**, not these adapters (`plan-01-kernels.md` §13). But **E07's suite needs them**: the matrix rows for K2–K6 are `now` rows, so `E07-02` (`S1-T21`) cannot complete and `E07-03` (`S1-T22`) cannot assert rows 3–14 until these adapters are terminal and `E04-07` has resolved them. E04 is therefore off the spine and **unconditionally required by the arm that converges on the gate anyway**.

---

## §2 Issues in this epic

| Issue | `wbs.md` task | Title | Wave | Depends on | Effort | PoC markers |
|---|---||---|---|:---:|---|:---:|---|
| `E04-01` | `S1-T11` | Ports: `PdfSource`, `OcrEngine`, `LlmEngine`, `ArtifactStore`, `Registry` | W2 | `S1-T01` → **E01** (inter) | M | — |
| `E04-02` | `S1-T12` | K2 `kernel.pdf` thin: `probe`, `classify`, `effective_dpi`, `extract_tokens`, `render`, `split` (+ `layout_text`, kernel-only) | W3 | `S1-T11` → **E04** (intra) | L | `# TODO: [MVP]`: full `page_facts`, `images`, `merge` |
| `E04-03` | `S1-T13` | K3 `kernel.image` thin: `load` (EXIF applied), `legibility`, `rescale`, `crop` (inverse map returned) | W3 | `S1-T11` → **E04** (intra) | M | `# TODO: [MVP]`: deskew, denoise, tile, phash |
| `E04-04` | `S1-T14` | K4 `kernel.ocr` port + Docling adapter: `capabilities`, `read`, `engine_info` | W3 | `S1-T11` → **E04** (intra) | L | `# TODO: [MVP]`: OCR correction pass |
| `E04-05` | `S1-T15` | K5 `kernel.llm.local` port + Ollama adapter: `structured`, `vision`, `warm`, `capabilities` | W3 | `S1-T11` → **E04** (intra) | L | `# TODO: [MVP]`: `ps`, `pull`, `generate` |
| `E04-06` | `S1-T16` | K6 `kernel.llm.frontier` port + one provider adapter: `structured`, `vision`, `judge`, `CallRecord` | W3 | `S1-T11` → **E04** (intra) | L | `# TODO: [MVP]`: second provider, batch API, token counting |
| `E04-07` | `S1-T17` | Resolution by capability + fail fast on unknown provider/model | W4 | `S1-T15`, `S1-T16` → **E04** (intra) | S | — |

Intra-epic edges (not drawn as epic edges): `E04-02` … `E04-06` → `E04-01`; `E04-07` → `E04-05`, `E04-06`.

---

## §3 Issue detail

### `E04-01` — implements `S1-T11`

**Title**
Ports: `PdfSource`, `OcrEngine`, `LlmEngine`, `ArtifactStore`, `Registry`.

**Context**
Everything above Stage 1 must be able to run without Poppler, without Docling, without Ollama and without a provider — and that is only possible if the thing a caller depends on is an **interface**, not a package. This issue defines the five interfaces and the isolation rule that keeps them honest: an adapter may import a port, never the reverse.

**Deliverable**
`docflow/ports/`

**Depends on**
`S1-T01` — **inter-epic** (E01 → E04). The ports exchange the boundary types; they do not define them.

**Acceptance criteria**
- [ ] `docflow/ports/` exists and defines exactly five interfaces: `PdfSource`, `OcrEngine`, `LlmEngine`, `ArtifactStore`, `Registry`.
- [ ] **No adapter is importable from a port** — an import check proves that importing any module under `docflow/ports/` does not import any module under `docflow/adapters/`.
- [ ] A **fake adapter satisfies each of the five ports** in tests, with no import of a real adapter.
- [ ] Every port method is fully type-hinted, with no `Any` in its signature and no untyped return.
- [ ] **No port method name, parameter or return type contains a domain noun** — no `--field`, `--invoice`, `--cuit`, `--total`, `--document-type`, `--pipeline`, `--validator`, `--extractor`, `--golden` and no domain equivalent (`kernel-cli.md` §10, forbidden vocabulary).
- [ ] No port method returns a bare value where the boundary requires a `Reason` on failure — a port can express "no value, and why".
- [ ] No port exposes a *decision*: no score, no verdict, no routing outcome. Ports report observations (`kernel-cli.md` §3, guardrail 2).
- [ ] The dependency arrows point down only: ports depend on `kernels/types.py`, adapters depend on ports, nothing depends on adapters except the composition root.

**Test / evidence**
- `plan-01-kernels.md` §7b — *"Adapter isolation"*: test is the import check plus a fake adapter satisfying each port; breaking it looks like *"an adapter is imported from a port; the arrow stops pointing down"*.
- `plan-01-kernels.md` §8 — import-isolation test; fake adapter satisfies each port. **Gap flagged:** `S1-T11` carries **no FR**; see §5.
- `plan-01-kernels.md` §13, Track 3 — the consumer test is that Plan 2 satisfies a port with a fake in its own tests, **without importing an adapter**.
- `kernel-cli.md` §13 — the three guardrails (one command = one port method; never emit a verdict; no silent fallback) are the same constraints restated at the CLI boundary; the port layer is where they originate.

**Out of scope for this issue**
- **No adapter.** The five adapters are `E04-02` … `E04-06`. This issue is interfaces and the isolation test.
- **No fake adapter shipped as production code.** A fake exists to satisfy the port *in tests*; shipping one as a default implementation would be a silent fallback in disguise. **Never**.
- **No concrete engine, model, threshold or default as a port member.** No default or fallback model, engine or threshold exists anywhere (`plans/README.md` §2). **Never**.
- **No domain noun.** **Never** (`kernel-cli.md` §10).
- **No second product surface or stable public API promise.** Ports exist for reuse by Plan 2, not as a supported external API. `# TODO: [RELEASE]`.

**Effort**
**M** — five small interfaces, but the verification is structural and must be automated: the import-isolation check and a per-port fake are what make the claim testable, and both are interacting concerns rather than a single assertion (`wbs.md` §7).

**Owner**
**Kernels** — `docflow/ports/` (`wbs.md` §8).

**Frozen contract touched**
**Freezes** `plans/README.md` §3, Plan 1 row: *the port interfaces `PdfSource`/`OcrEngine`/`LlmEngine`/`ArtifactStore`/`Registry`*. Plan 2 satisfies these with fakes and may not change them.

---

### `E04-02` — implements `S1-T12`

**Title**
K2 `kernel.pdf` thin: `probe`, `classify`, `effective_dpi`, `extract_tokens`, `render`, `split` — plus `layout_text`, which is **not** part of the port contract (`E04-01` carries the five frozen interfaces, and a sixth operation on `PdfSource` would re-open that gate).

**Status — `in progress`, 1 criterion unmet**

Recorded rather than implied, because a ticked box that is not true is the failure mode this project exists to prevent.

| # | Criterion | Status |
|---:|---|---|
| 1 | `classify` returns `text`/`image`/`mixed`/`blank` | ✅ met |
| 2 | `classify` detects invisible text and reports it as evidence | ✅ met, and stronger than the row requires — see below |
| 3 | `classify` reports contradicting producer metadata in `evidence` | ✅ met — asserted on a declared scanner whose page carries text, with a non-capture producer as the control so the flag is shown to carry information |
| 4 | `render` never upscales, no larger file produced | ✅ met, and verified against all 5 committed scans |
| 5 | Effective DPI measured from embedded pixels | ✅ met |
| 6 | `probe`, `extract_tokens` and `split` dispatch and return typed results | ✅ met |
| 7 | `split` preserves page count and boxes; mapping recorded | ✅ met |
| 8 | **The adapter is reachable only through `PdfSource`** | ❌ **NOT MET** — `docflow/adapters/` holds only `__init__.py`; there is no Poppler adapter |
| 9 | No threshold constant inside the module | ✅ met, guarded over public and private constants |

**Resolution of #8 — a scoping question, not a defect.** `E04-02`'s deliverable is `docflow/kernels/pdf.py` alone, while a thin adapter behind `PdfSource` is what the criterion asks for. That adapter sits naturally with `E04-03`…`E04-06`, whose deliverables *are* the `docflow/adapters/` modules. Either the criterion moves to the issue that owns the adapters, or `E04-02` grows a deliverable. **The decision is not taken here** — the criterion is recorded as unmet so that nobody ticks it by reading the kernel and assuming the adapter came with it.

> **The same question recurs one issue later, and that makes it a pattern rather than an accident.** `E04-03` carries the identical split: its deliverable is `docflow/kernels/image.py`, and its criterion 8 is *"The adapter is reachable only through `RasterImage`"* — an adapter that no issue in this epic names as a deliverable. Two consecutive issues asking for an artefact neither owns is a gap in the epic's cut, not two oversights. It is recorded in both places so that resolving it happens once, deliberately, rather than twice by improvisation.

**On #2, one thing the row does not ask for.** The page's shape is measured with invisible text **excluded**: a scan with a stale hidden layer reports `image`, not `mixed`. Counting those characters would name the page a text page, the document would never be converted, and the content a person can see would never be read — which is the silent failure the row exists to prevent. The check was built against a real `Tr 3` no-draw layer because the naive one is fooled: the engine's own text extraction returns invisible text as ordinary text.

**Context**
Two silent failures start here. A scan with a stale invisible OCR layer behind it reads as a *text* PDF, so the document is never converted and the text on the page is never seen. And a 150-DPI scan rendered at 300 is reported as satisfying the resolution the caller asked for — larger and no more legible. This issue makes both of them statements about the bytes: the classification is a measurement, and a render that cannot honour the requested DPI says so instead.

**Deliverable**
`docflow/kernels/pdf.py`

**Depends on**
`S1-T11` — **intra-epic**. Externally: `S1-T01` via E01.

**Acceptance criteria**
- [ ] `classify` returns one of `text` / `image` / `mixed` / **`blank`** — four outcomes, `blank` included.
- [ ] `classify` **detects invisible text** and reports it as evidence (`invisible_text: true`), so a stale hidden layer cannot be read as a text PDF.
- [ ] `classify` reports contradicting producer metadata in `evidence` rather than resolving it silently.
- [ ] `render` **never upscales**: a request for 300 DPI on a 150 DPI scan exits `2` with `reason.code: insufficient_effective_resolution` and **no larger file is produced**.
- [ ] Effective DPI is **measured from embedded pixels**, not taken from the request or from metadata.
- [ ] `probe`, `extract_tokens` and `split` dispatch and return typed results.
- [ ] `split` preserves page count and page boxes for the requested range; the mapping to the source range is recorded in the descriptor.
- [ ] The adapter is reachable only through `PdfSource`; the kernel module imports no Poppler-specific detail outside the adapter boundary.
- [ ] No threshold constant lives inside this module: what counts as illegible or too low-resolution is the **caller's** value, not a kernel constant (`prd.md` FR-15, `kernel-cli.md` §3).

**Test / evidence**
- `kernel-cli.md` §11 **row 3** (stale invisible OCR layer read as a text PDF): command `pdf classify scan-hidden-layer.pdf --page 1`; assertion `value` is `image`, with `invisible_text: true` and contradicting producer metadata in `evidence`. Status `now` — Stage 1 CI gate. Fixture `scan-hidden-layer.pdf` (`kernel-cli.md` §12).
- `kernel-cli.md` §11 **row 4** (150 DPI scan rendered at 300 and reported as 300): command `pdf render scan150.pdf --page 1 --dpi 300`; assertion exit `2`, `reason.code: insufficient_effective_resolution`, no larger file produced. Status `now` — Stage 1 CI gate. Fixture `scan150.pdf`.
- `kernel-cli.md` §11 **row 5** (a split that separates a document from its pages): split then `pdf probe` on the output; page count and page boxes match the source range. Status `now` — Stage 1 CI gate. Fixture `three-invoices.pdf`.
- `plan-01-kernels.md` §7b — *"`render` never upscales"*: test is `pdf render` at 300 on a 150 DPI fixture, assigned to `S1-T12` (row 4).
- `plan-01-kernels.md` §8 — rows 3, 4, 5. Requirement **FR-15** (the measurements the Diagnosis gate consumes).
- `kernel-cli.md` §9 (K2) — `pdf probe`, `pdf classify`, `pdf tokens`, `pdf render`, `pdf split` are `now`; `pdf facts` and `pdf images` are `MVP` and exit `4`.
- **`layout_text` has no matrix row and no command in §9**, which is consistent: the matrix is the silent-failure suite, and the text path's failures are already asserted through rows 3–5. What it has instead is a **measured** relationship to `extract_tokens`: reconstructing the grid from token boxes matches the reader's own output on **0 of 68 lines** of `casos/9dfc597f`, because the reader holds the font metrics and emits the soft hyphen it broke a word on, and a token box has neither. The two operations are therefore **not interchangeable** — one carries provenance, the other carries the text as a person reads it — and that is asserted by a test rather than left as a comment.
- **Equivalence with the previous system is asserted, not assumed.** `layout_text(path, [1])` is byte-identical to `pdftotext -layout -enc UTF-8 -q -f 1 -l 1 <file> -`, and a non-contiguous selection is byte-identical to the concatenation of its per-page reads. The encoding is passed explicitly because the default follows the host locale, and two machines would otherwise disagree on the bytes without disagreeing on the document.

**Out of scope for this issue**
- **No full `page_facts`.** Beyond classification. `# TODO: [MVP]` — `pdf facts` stays `MVP` and exits `4`.
- **No `embedded_images`.** `# TODO: [MVP]` — `pdf images` stays `MVP` and exits `4`.
- **No `merge`.** Merged-document detection is **Never** — no pipeline closes it (`wbs.md` §10).
- **No decision.** `classify` returns a measurement, not a routing outcome (`kernel-cli.md` §3, guardrail 2). Routing a stale-layer page *away from conversion* is Diagnosis's decision, `S2-T04`.
- **No threshold as a kernel constant.** **Never** (FR-15).
- **No `--engine`-shaped flag** and no fallback reader: a missing `pdftotext` binary is a typed `Reason`, never a substitute reader (`wbs.md` §9, owner stage 2). `# TODO: [MVP]` for pinning the binary version.
- **No `layout_text` anywhere in the frozen contract.** It is not on `PdfSource`, not a command in `kernel-cli.md` §9, and not part of any flow. Moving it onto the port is a contract decision that re-opens `E04-01`, not a convenience to be taken while editing a kernel.

**Effort**
**L** — a heavyweight external dependency (`pdftotext`/Poppler) plus three distinct silent-failure rows to make assertable, each needing a committed fixture that provokes the failure rather than a happy-path call (`wbs.md` §7).

**Owner**
**Kernels** — `docflow/kernels/pdf.py` (`wbs.md` §8).

**Frozen contract touched**
**Consumes** `plans/README.md` §3, Plan 1 row — `PdfSource` from `docflow/ports/` and the closed `reason.code` set (`insufficient_effective_resolution`, `blank_page`, `encrypted`, `unsupported_format`, `kernel-cli.md` §5).

**It adds nothing to that set.** `layout_text` reports an empty text layer as `blank_page` and a missing binary as `engine_unavailable`, both already in the closed vocabulary; a non-contiguous page selection is served by composing per-page reads — measured byte-identical to a contiguous one — rather than by introducing a code for *"the reader cannot express this selection"*.

**It touches no boundary type.** `layout_text` returns the frozen `str`. A geometry-bearing result would have needed a new type, which `E01-01` forbids — and that is the reason the operation returns text rather than a structure.

---

### `E04-03` — implements `S1-T13`

**Title**
K3 `kernel.image` thin: `load` (EXIF applied), `legibility` (measurement + reason, never a boolean), `rescale`, `crop` (inverse map returned).

**Status — `in progress`, 1 criterion unmet**

Recorded rather than implied, for the same reason as `E04-02`: a ticked box that is not true is the failure mode this project exists to prevent.

| # | Criterion | Status |
|---:|---|---|
| 1 | `load` applies EXIF orientation before the bitmap leaves | ✅ met — asserted by decoding the returned bytes, so the stored shape coming back fails the test |
| 2 | `load`/`info` reports the orientation found **and** applied | ✅ met — two fields, because a rotation nobody recorded is indistinguishable from a file that needed none |
| 3 | `legibility` returns a measurement plus a `Reason`, never a boolean | ✅ met — the measurements are present **on the failure**, which is what distinguishes a reason from a boolean |
| 4 | An illegible bitmap produces `illegible` with the measurements alongside | ✅ met |
| 5 | `crop` returns the crop together with its inverse map | ✅ met — `InverseMap` travels with the bytes in one value |
| 6 | A crop's local coordinates are never returned as a page region | ✅ met — this is `NFR-07`, and the assertion names the failure explicitly |
| 7 | `rescale` reports the target honoured, never silently satisfying | ✅ met — an unreachable target is refused with the measured source resolution |
| 8 | **The adapter is reachable only through `RasterImage`** | ❌ **NOT MET**, and the port it names does not exist — see the note under `E04-02` criterion 8: K3 has no port, and the `docflow/adapters/` module this would need is not any issue's deliverable |
| 9 | No threshold constant inside the module | ✅ met — the threshold is a required parameter, and a test changes it on an **unchanged** image to prove it is the caller's |

**One thing the criteria do not ask for, and it matters.** `rescale` takes `source_dpi` as a parameter because `Box` carries no DPI. A kernel that measured or assumed the source resolution would be reporting a number nobody supplied, so the caller states it — and the refusal is then a comparison of two values the caller can see, rather than a hidden judgement.

**Context**
A photo read sideways loses a whole page and reports no error; a blurred bitmap that reaches OCR produces invented text; and a crop whose local coordinates are reported as page coordinates makes the downstream trace point at the wrong pixels while remaining valid JSON — so nothing else notices. This issue fixes all three by making the kernel report what it *observed* and by making coordinates leave the kernel in the coordinate system the caller can use.

**Deliverable**
`docflow/kernels/image.py`

**Depends on**
`S1-T11` — **intra-epic**. Externally: `S1-T01` via E01.

**Acceptance criteria**
- [ ] `load` applies **EXIF orientation**; a photo read sideways is impossible because the rotation is applied before the bitmap leaves the kernel.
- [ ] `load`/`info` **reports the EXIF orientation it found and that it applied it** (`evidence.exif_orientation`).
- [ ] `legibility` returns a **measurement plus a `Reason`**, never a bare boolean — the measured quantities (`laplacian_variance`, `contrast`, `skew_estimate`) are present in the result.
- [ ] An illegible bitmap produces a typed `Reason` (`illegible`, exit `2`) with the measurements alongside it, on a blurred fixture.
- [ ] `crop` returns the crop **together with its inverse map**, and `evidence.inverse_map` maps the crop's local coordinates **back to source page coordinates** before they leave the kernel.
- [ ] A crop's local coordinates are **never** returned as a page region.
- [ ] `rescale` reports the target it honoured and does not silently satisfy a resolution it cannot reach.
- [ ] No threshold is a constant inside this module: the value the legibility measurement is compared against is supplied by the caller (`prd.md` FR-15, `kernel-cli.md` §3).

**Test / evidence**
- `kernel-cli.md` §11 **row 6** (a photo read sideways): `image info rotated.jpg`; assertion `evidence.exif_orientation` is reported **and applied**. Status `now` — Stage 1 CI gate. Fixture `rotated.jpg` (EXIF orientation 6).
- `kernel-cli.md` §11 **row 7** (a blurred image passed to OCR): `image legibility blurry.jpg`; assertion exit `2` with a `Reason`, plus measurements — never a bare boolean. Status `now`. Fixture `blurry.jpg`.
- `kernel-cli.md` §11 **row 8** (a crop's local coordinates reported as a page region): `image crop page.png --region 100,200,300,80`; assertion `evidence.inverse_map` is present and maps back to source coordinates. Status `now`. Fixture `page.png`.
- `plan-01-kernels.md` §7b — *"Coordinates leave a kernel in source page coordinates"*: the crop inverse-map test; breaking it looks like *"a crop's local coordinates are reported as a page region; both boxes are valid JSON, so nothing else notices"*; task cell `S1-T13` (row 8).
- `plan-01-kernels.md` §8 — rows 6, 7, 8; requirements **NFR-07** and **FR-15** (legibility measurement). The inverse-map assertion **is** NFR-07.
- `kernel-cli.md` §9 (K3) — `image info`, `image legibility`, `image rescale`, `image crop` are `now`; `image deskew`, `image phash`, `image tile` are `MVP` and exit `4`.
- `plan-01-kernels.md` §13, Track 2 — the *coordinate honesty* golden artifact is a crop fixture with a known source box, and it must fail when a crop's local box is reported as a page region.

**Out of scope for this issue**
- **No deskew, no denoise, no binarize, no auto-contrast.** `# TODO: [MVP]` — `image deskew` stays `MVP` and exits `4`.
- **No `phash`, no `tile`.** `# TODO: [MVP]` — both stay `MVP` and exit `4`.
- **No legibility *decision*.** The kernel reports the measurement and the reason; the gate decision is Diagnosis's, taken against registry policy, never a constant in K3 (`kernel-cli.md` §3, `prd.md` FR-15).
- **No confidence score, no quality score.** A score that aggregates measurements is forbidden (`kernel-cli.md` §3, guardrail 2). **Never**.
- **No upscale-and-report-satisfied.** **Never** (`kernel-cli.md` §14).

**Effort**
**M** — three independent measurement/coordinate behaviours, each with a committed fixture and two of them being invariants rather than features; interacting concerns without a heavyweight dependency (`wbs.md` §7).

**Owner**
**Kernels** — `docflow/kernels/image.py` (`wbs.md` §8).

**Frozen contract touched**
**Consumes** the Plan 1 row of `plans/README.md` §3 — the port interfaces, and the closed `reason.code` set (`illegible`, `unsupported_format`).

---

### `E04-04` — implements `S1-T14`

**Title**
K4 `kernel.ocr` port + Docling adapter: `capabilities`, `read`, `engine_info`.

**Context**
OCR output is the one place where the system cannot re-derive what it saw: a sampled artifact is evidence and is never regenerated (`plans/README.md` §2 non-negotiable 3), so a lost OCR result makes that document permanently unreproducible. Two things follow. The engine must be **fixed** — Docling and only Docling — so the OCR path is not a matrix of behaviours. And the boundary must **drop what it does not contract for**: positioned tokens leave, Docling's layout and reading order do not, because a reading order injected here would be a domain-level interpretation performed by a kernel.

**Deliverable**
`docflow/ports/ocr.py`, `docflow/adapters/docling.py`

**Depends on**
`S1-T11` — **intra-epic**. Externally: `S1-T01` via E01.

**Acceptance criteria**
- [ ] `docflow/ports/ocr.py` and `docflow/adapters/docling.py` exist; the adapter is reachable only through the port.
- [ ] `read` returns **positioned tokens with no reading order resolved** — tokens carry boxes; no order field, no sorted sequence is produced by the kernel.
- [ ] Docling's **layout output is dropped at the boundary**; table structure and layout regions do not leave the kernel.
- [ ] `read` returns a **per-page status** distinguishing `read` (with a possibly empty token list) from `blank` from `unreadable`.
- [ ] A blank page reports status `blank`, **never** `read` with invented tokens.
- [ ] Token confidence is `float | null`, and **`null` is never coerced to `1.0`** — missing confidence stays missing.
- [ ] `pages_requested` and `pages_read` are both reported, so a truncated page is distinguishable from a page with no text.
- [ ] There is **no `--engine` flag** and **no engine setting** anywhere — asserted by the `E07-02` contract test, which fails if an engine flag exists.
- [ ] `engine_info` is populated and is the value that feeds the cache key.
- [ ] The adapter is importable from the composition root and **not** importable from `docflow/ports/ocr.py`.

**Test / evidence**
- `kernel-cli.md` §11 **row 9** (a blank page returning invented text): `ocr read blank.png`; assertion per-page status is `blank`, not `read` with tokens. Status `now` — Stage 1 CI gate. Fixture `blank.png`.
- `kernel-cli.md` §11 **row 10** (missing confidence read as perfect): `ocr read x.png | jq '.value.tokens[] | select(.confidence == null)'`; assertion `null` is preserved and is not coerced to `1.0`. Status `now`. Fixture `lowconf.png`.
- `kernel-cli.md` §11 **row 11** (a truncated page read as a page with no text): `ocr read big.pdf --pages 1-200`; assertion `pages_requested` vs `pages_read` differ and the difference is declared. Status `now`. Fixture `large.pdf`.
- `plan-01-kernels.md` §7b — the truncation and blank-page invariants are asserted through these row assignments; `plan-01-kernels.md` §8 maps rows 9, 10, 11 to requirements **FR-16**, **FR-17**, and the contract test asserts **no `--engine` flag exists**.
- `kernel-cli.md` §9 (K4) — `ocr capabilities`, `ocr engine-info`, `ocr read` are `now`. The absence of `--engine` is stated there and enforced by `E07-02`.
- `plan-01-kernels.md` §13, Track 1 — Docling is deliberately **faked** behind `OcrEngine` for the fast flow; the port, not the engine, is what Stage 1 fixes (`wbs.md` §9), and rows 9–11 are the payback.

**Out of scope for this issue**
- **No OCR correction pass.** `# TODO: [MVP]` — `--correct` gates the corrected artifact only and the raw tokens are always retained (`kernel-cli.md` §9, K4).
- **No second OCR engine and no OCR engine setting.** **Never** (ADR-001, `prd.md` FR-16).
- **No reading order, no layout, no table structure.** Dropped at the boundary; ordering is the Reconstructor's job at Stage 2 (`S2-T07`).
- **No confidence score aggregation** and no "usable / route to OCR" style output. **Never** (`kernel-cli.md` §3, guardrail 2).
- **No threshold inside the kernel.** **Never** (FR-15).
- **No determinism-class decision.** This adapter **reports** `sampled`; what `sampled` means for resume is `E05-03`'s.

**Effort**
**L** — a heavyweight, platform-specific external dependency (Docling) whose output must be *narrowed* at the boundary rather than passed through, plus three fixture-backed silent-failure rows (`wbs.md` §7).

**Owner**
**Kernels** — `docflow/ports/ocr.py`, `docflow/adapters/docling.py` (`wbs.md` §8).

**Frozen contract touched**
**Consumes** the Plan 1 row of `plans/README.md` §3 — `OcrEngine` from the ports row, and the closed `reason.code` set (`blank_page`, `engine_unavailable`). **Contributes to** the *determinism classes* row by reporting K4 as `sampled`; the class set itself is frozen at `E05-03`.

---

### `E04-05` — implements `S1-T15`

**Title**
K5 `kernel.llm.local` port + Ollama adapter: `structured`, `vision`, `warm`, `capabilities`.

**Context**
A local model is identified by a **digest**, not a tag: `qwen2.5` is a moving tag, so a model pulled mid-run silently changes the thing that produced every later value. And a completion cut by `num_ctx` that happens to be cut after the last complete field parses cleanly — producing a truncated answer reported as complete. This issue makes the identity of the model observable for the whole run and makes truncation a typed failure rather than a parse that happens to succeed.

**Deliverable**
`docflow/adapters/ollama.py`

**Depends on**
`S1-T11` — **intra-epic**. Externally: `S1-T01` via E01.

**Acceptance criteria**
- [ ] The adapter is reachable only through `LlmEngine`; it is not importable from a port.
- [ ] The **digest** is recorded at first use and **compared for the remainder of the run** — a mid-run model swap is visible as a difference in that comparison.
- [ ] `capabilities` reports the digest, never the tag alone.
- [ ] A **missing model** raises a typed error naming `ollama pull <model>` (`reason.code: model_not_pulled`, exit `3`).
- [ ] **Truncation maps to a typed error** (`reason.code: truncated_output`, exit `2`) and is **never parsed as complete** — an oversized prompt against `num_ctx` yields the typed failure, not a partial value.
- [ ] The raw completion is preserved so that a truncated one is distinguishable from a complete one without re-invoking the model.
- [ ] `structured`, `vision` and `warm` dispatch and return typed results.
- [ ] `evidence` carries the terms a test may assert on: model digest, `num_ctx`, sampling parameters, adapter revision. A sampled kernel's value is **not** assertable — the evidence is (`kernel-cli.md` §7).
- [ ] No `--api-key`-shaped flag and no secret in a flag; secrets come from the environment only where the provider requires one.
- [ ] No default or fallback model exists in the adapter: an unknown name never resolves to a working model.

**Test / evidence**
- `kernel-cli.md` §11 **row 12** (output cut by `num_ctx`, parsed as complete): `llm.local structured --model ollama:qwen2.5 --schema-file s.json` with an oversized prompt; assertion exit `2`, `reason.code: truncated_output`, never a parsed partial. Status `now` — Stage 1 CI gate. Fixture `oversized-prompt.txt`.
- `kernel-cli.md` §11 **row 13** (a model swapped under a moving tag mid-run): `llm.local capabilities --model ollama:qwen2.5` twice across a `pull`; assertion the digest differs and the change is visible in `evidence`. Status `now`. Fixture `model-swap.md` — a **recipe**, not a document: `capabilities`, pull, `capabilities` again, comparing digests.
- `plan-01-kernels.md` §7b — *"Truncation is never parsed as complete"*: oversized prompt against `num_ctx`; breaking it looks like *"a cut completion parses cleanly because the cut landed after the last complete field"*; task cell `S1-T15` (row 12).
- `plan-01-kernels.md` §8 — rows 12, 13; unknown-model exit `3` with `model_unknown`; typed-error test on a missing model. Requirements **FR-27**, **NFR-08**, **NFR-10**.
- `kernel-cli.md` §7 — the determinism class of K5 is `sampled`: a test may **not** assert the value, only the evidence. `--repeat` demonstrates non-reproducibility and is **never** a retry-until-agreement.
- `kernel-cli.md` §9 (K5) — `llm.local capabilities`, `llm.local warm`, `llm.local structured`, `llm.local vision` are `now`; `ps`, `pull`, `generate` are `MVP` and exit `4`.

**Out of scope for this issue**
- **No `ps`, no `pull`, no `generate` as Stage 1 commands.** `# TODO: [MVP]` — all three stay `MVP` and exit `4`. The `pull` in row 13's recipe is performed by the operator, not by the CLI.
- **No OCR correction pass** and no post-processing of tokens: correction is `# TODO: [MVP]` (see `E04-04`).
- **No token counting** on the local path and no batch API. `# TODO: [MVP]`.
- **No fallback model, no default model, no environment variable that substitutes a model.** **Never** (`kernel-cli.md` §8, `plans/README.md` §2).
- **No retry until two answers agree.** **Never** (`kernel-cli.md` §7). The orchestrator records an attempt count so the pattern is visible.
- **No determinism-class consequence.** `E05-03` decides what `sampled` means on resume; this adapter reports the class and the evidence.
- **No GPU slot policy.** `gpu = 1` is `E05-04`'s declared simplification; `plan-01-kernels.md` §12 open decision **#7** carries the question of how many slots exist. Not resolved here.

**Effort**
**L** — a heavyweight external dependency (Ollama) plus two silent failures whose tests require a *recipe* across two invocations (row 13) and an adversarial prompt (row 12); the digest discipline is a load-bearing invariant (`wbs.md` §7).

**Owner**
**Kernels** — `docflow/adapters/ollama.py` (`wbs.md` §8).

**Frozen contract touched**
**Consumes** the Plan 1 row of `plans/README.md` §3 — `LlmEngine` from the ports row; the closed `reason.code` set (`model_not_pulled`, `model_unknown`, `truncated_output`). **Contributes to** the *determinism classes* and *model revision as a cache-key term* rows.

---

### `E04-06` — implements `S1-T16`

**Title**
K6 `kernel.llm.frontier` port + one provider adapter: `structured`, `vision`, `judge`, `CallRecord`.

**Context**
Two things go wrong when a remote model is involved. The raw completion gets coerced before it is persisted, so a parse bug becomes indistinguishable from a model that returned nothing. And a rate limit or an outage is collapsed into a rejection, so *"the provider was down"* reads as *"this field is invalid"*. This issue keeps the raw bytes as the artifact of record and keeps absence, `null` and a default three different things.

**Deliverable**
`docflow/adapters/frontier.py`

**Depends on**
`S1-T11` — **intra-epic**. Externally: `S1-T01` via E01.

**Acceptance criteria**
- [ ] The adapter is reachable only through `LlmEngine`; it is not importable from a port.
- [ ] The **raw completion is persisted before any parse** — with `--save`, the raw bytes are what land in the store, and the parsed structure is a second, derived artifact.
- [ ] **`429` honours `retry-after` verbatim** — the imposed delay is used as given, not reinterpreted.
- [ ] **Sustained unavailability degrades to `unverified`, never to rejection** (`reason.code: provider_unavailable`).
- [ ] The model's **absence, `null` and a present value stay three distinguishable outcomes** and are never collapsed into one.
- [ ] `call_record` is **always populated**: provider, model revision, tokens, cost, latency, request id.
- [ ] **Secrets come from the environment only** — there is no `--api-key` flag, asserted by the contract test.
- [ ] An unknown provider prefix fails with `provider_unknown`, exit `3`; **no default provider is substituted**.
- [ ] `judge` exists as an operation and its **`role_conflict`** path is implemented: grading samples the same model produced exits `3` with `reason.code: role_conflict`.
- [ ] `structured` and `vision` dispatch and return typed results.

**Test / evidence**
- `kernel-cli.md` §11 **row 14** (the model's absence, `null` and a default collapsed into one): `llm.frontier structured … --save O`; assertion the raw completion is saved **before** the parse, and absent / `null` / present stay distinguishable. Status `now` — Stage 1 CI gate. **No committed fixture:** the row needs an **unreachable provider** (point the host setting at a closed port), and the absence/`null`/present distinction is asserted with a live provider for the first two (`kernel-cli.md` §12).
- `kernel-cli.md` §11 **row 15** (a golden set graded by the model that produced it): command `llm.frontier judge` with the **governor model** and a golden file; assertion exit `3`, `reason.code: role_conflict`. **Status: declared and gated** — the command is `MVP` in `kernel-cli.md` §9, so the row is **not a Stage 1 gate**; it asserts on `role_conflict` **the moment `judge` lands**. It is described that way, **not as dropped** (`kernel-cli.md` §11; `plan-01-kernels.md` §7c).
- `plan-01-kernels.md` §8 — row 14; `call_record` populated; contract test asserts **no `--api-key` flag exists**. Requirements **FR-27**, **NFR-05**, **NFR-08**, **NFR-10**.
- `kernel-cli.md` §7 — K6's determinism class is `external`: a test may assert **`call_record`** and the typed failure paths (`429`, timeout, circuit breaker), **not** the value.
- `kernel-cli.md` §9 (K6) — `capabilities`, `structured`, `vision` are `now`; `count-tokens` and `judge` are `MVP` and exit `4`.

**Out of scope for this issue**
- **No second provider.** `# TODO: [MVP]` — one provider adapter only.
- **No batch API, no `count_tokens`.** `# TODO: [MVP]` — `llm.frontier count-tokens` stays `MVP` and exits `4`.
- **No `judge` execution.** `judge` is `MVP` in Stage 1: the command exits `4`, and **row 15 is declared and gated**, asserting the moment `judge` lands (`kernel-cli.md` §11). The `role_conflict` path is implemented so that row 15 has a code to assert on — it is not exercised by a Stage 1 CI row.
- **No `--api-key` flag**, no key on the command line, no key in a descriptor. Secrets from the environment only. **Never** (`kernel-cli.md` §9, K6).
- **No fallback provider or default model.** **Never** (`kernel-cli.md` §8).
- **No K6 dependency in the fast flow.** `S1-T16` is explicitly stubbable by a test double until escalation needs it (`wbs.md` §6.2); the paid-back point is `S2-T09`/`S2-T11`, Plan 2. `# TODO: [MVP]`.
- **No cost/token budget policy.** "Contrast scoped to critical fields only; `count_tokens` before spending" is a Stage 2/3 mitigation (`wbs.md` §9, owner stage 2, 3). Not here.

**Effort**
**L** — a heavyweight external dependency with non-deterministic failure modes (`429`, timeout, outage) that must be *typed* rather than caught generically, plus the persist-before-parse ordering which is an invariant; two of the matrix rows assert a difference between two invocations (`wbs.md` §7).

**Owner**
**Kernels** — `docflow/adapters/frontier.py` (`wbs.md` §8).

**Frozen contract touched**
**Consumes** the Plan 1 row of `plans/README.md` §3 — `LlmEngine` from the ports row, `CallRecord` from the types row, and the closed `reason.code` set (`truncated_output`, `provider_unknown`, `provider_unavailable`, `model_unknown`, `role_conflict`). **Contributes to** the *determinism classes* row by reporting K6 as `external`.

---

### `E04-07` — implements `S1-T17`

**Title**
Resolution by capability + fail fast on unknown provider/model.

**Context**
The single most expensive silent failure in the layer is a model that resolves to *something* instead of failing: every value downstream is then produced by a model nobody chose, and nothing in the output says so. This issue exists to make *"there is no fallback"* a fact a test can reach — the failure path is typed, it names the name that failed, and a default does not exist in the code to be found.

**Deliverable**
`docflow/kernels/resolution.py`

**Depends on**
`S1-T15`, `S1-T16` — **intra-epic**. Externally: `S1-T01` via E01.

**Acceptance criteria**
- [ ] `docflow/kernels/resolution.py` exists and resolves a capability to a concrete adapter plus its revision and parameters.
- [ ] `ollama:qwen2.5` **resolves**, and a frontier name (`anthropic:…`) **resolves** — both through the same capability-based path.
- [ ] An **unknown name fails with a reason naming it** — `model_unknown` for a model, `provider_unknown` for a prefix, exit `3`, with the unknown name present in the reason.
- [ ] **No fallback default exists anywhere** — no default model, no default provider, no default engine, no default threshold constant, and no environment variable that substitutes any of them. This is **asserted**, not merely asserted-about (`plan-01-kernels.md` §8).
- [ ] Resolution is reported **before execution**: `--resolve-only` returns the adapter, `model_revision`, `adapter_revision`, `params` and `cache_key_terms` and executes nothing.
- [ ] The resolved model revision and registry hash appear in `cache_key_terms`, matching `E03-02`'s key.
- [ ] Resolution performs no network call and no model invocation.

**Test / evidence**
- `plan-01-kernels.md` §7b — *"No fallback model, engine or threshold"*: test is a resolution test on an unknown name; breaking it looks like *"an unknown model resolves to something instead of failing, or a default appears in the code"*.
- `plan-01-kernels.md` §8 — resolution test on a known and an unknown name; **the absence of any default is asserted, not asserted-about**. Requirement **FR-27**.
- `kernel-cli.md` §8 — the worked example: `--resolve-only` on a known model returns the resolution envelope; on `ollama:nope` it returns exit `3` with `reason.code: model_unknown` and the message naming the unknown model and the available ones. *"There is no `--fallback`, no `--default-model`, and no environment variable that substitutes a model."*
- `kernel-cli.md` §11 **row 13** is the nearest Stage 1 CI row (model swapped under a moving tag): it asserts the digest discipline on which resolution's `model_revision` term depends.
- `kernel-cli.md` §9 (K5/K6) — `--resolve-only` applies to K2–K6 (`kernel-cli.md` §10, global flags).

**Out of scope for this issue**
- **No execution.** Resolution decides *which* adapter and *which* revision; it runs nothing (`--resolve-only` "executes nothing", `kernel-cli.md` §8).
- **No `--fallback` and no `--default-model` flag.** **Never** (`kernel-cli.md` §8/§14).
- **No default engine** for OCR: the engine is Docling only and never a setting. **Never** (ADR-001, `prd.md` FR-16).
- **No default threshold.** A threshold is the caller's value; resolution never supplies one. **Never** (`prd.md` FR-15).
- **No circuit-breaker or escalation policy.** *"Sustained unavailability degrades to `unverified`"* is the adapter's typed outcome (`E04-06`); the escalation ladder that consumes it is `S2-T09`'s, Plan 2.
- **No capability routing across multiple providers.** One provider adapter exists in Stage 1; multi-provider capability selection is `# TODO: [MVP]`.

**Effort**
**S** — a single concept with a straightforward test: resolve a known name, fail an unknown one, and assert the absence of a default. No fixture and no external call, because `--resolve-only` is designed to be free (`wbs.md` §7).

**Owner**
**Kernels** — `docflow/kernels/resolution.py` (`wbs.md` §8).

**Frozen contract touched**
**Consumes** the fixed decisions table of `plans/README.md` §2 — *no default or fallback model, engine or threshold exists anywhere* — and the closed `reason.code` set (`model_unknown`, `provider_unknown`).

---

## §4 Epic close condition

E04 is **`done`** when:

1. all seven issues are `done`, and
2. the capability is **demonstrable**: a fake adapter satisfies each of the five ports with no adapter import; a known model and provider resolve while an unknown one fails with a reason naming it; and the K2–K6 matrix rows (`kernel-cli.md` §11 rows 3–14) each assert a `reason.code` against a committed fixture. Rows 3–14 are `now` rows and are Stage 1 gate rows; **row 15 is a K6 row but is *declared and gated* on `judge` landing** and is not part of this epic's close.

**Does E04 gate `S1-T19`?** **Not by dependency** — no entry in `S1-T19`'s dependency set names `S1-T11` … `S1-T17`. It gates it **through E07**: `S1-T21` depends on each of `S1-T12`–`S1-T17` as it completes, and `S1-T22` (a **hard predecessor** of `S1-T19`, `wbs.md` §6.2) cannot assert rows 3–14 without them. So the gate cannot close over prose rows, and E04 is the epic that turns those rows into assertions.

**The dependency this creates is real but short.** E04's adapters are *not on the serial spine* (`wbs.md` §6.2) and K6 is stubbable by a test double — but the harness chain that converges on the gate is only 3 links long, which is exactly why it is the chain that must not slip (`plans/README.md` §4).

---

## §5 Traceability

| Issue | `wbs.md` task | FR / NFR (`traceability.md` §4) | Gap? | Evidence of the mapping |
|---|---|:---:|---|
| `E04-01` | `S1-T11` | *(none — gap flagged below, traced to ADR-004)* | **gap** | Import-isolation test; fake adapter satisfies each port |
| `E04-02` | `S1-T12` | **FR-15** (the measurements the Diagnosis gate consumes) | no | rows 3, 4, 5 |
| `E04-03` | `S1-T13` | **NFR-07**, **FR-15** (legibility measurement) | no | rows 6, 7, 8 — the inverse-map assertion is NFR-07 |
| `E04-04` | `S1-T14` | **FR-16**, **FR-17** | no | rows 9, 10, 11; contract test asserts no `--engine` flag exists |
| `E04-05` | `S1-T15` | **FR-27**, **NFR-08**, **NFR-10** | no | rows 12, 13; unknown-model exit `3` with `model_unknown`; typed-error test on a missing model |
| `E04-06` | `S1-T16` | **FR-27**, **NFR-05**, **NFR-08**, **NFR-10** | no | row 14; `call_record` populated; contract test asserts no `--api-key` flag exists |
| `E04-07` | `S1-T17` | **FR-27** | no | resolution test on a known and an unknown name; the absence of any default is asserted |

### Gap flagged — `E04-01` (`S1-T11`) has no FR

`plan-01-kernels.md` §8 records this as the **gap note** and this issue does not fill it, because filling it would change `prd.md` — an artifact change, out of scope for a plan. Restated precisely:

- **What is missing:** `S1-T11` (the ports) has **no functional requirement** in `traceability.md` §4.1. Nothing in FR-01 … FR-33 names the port interfaces.
- **Why this is a requirement gap and not orphan work:** `traceability.md` §5 traces `S1-T11`–`S1-T17` to a **stated user requirement** rather than to an FR — the ports exist because **ADR-004** requires a kernel layer reusable beyond this project. A requirement exists; it is simply not numbered.
- **What closing it would cost:** adding an FR for *"the kernel layer is reusable and independently testable"* — a change to `prd.md`, which is not this directory's to make.
- **Do not fill it by inventing a number.** `E04-01` is a **flag**, not a hole.

No other issue in E04 has an empty mapping.

---

## §6 Risks

From `plan-01-kernels.md` §9 only:

| Risk | L | I | Why it touches E04 | Mitigation carried by this epic |
|---|:---:|:---:|---|---|
| **Model resolved by capability, not name** — a silent fallback changes every downstream value | L | H | `S1-T17` **is** this row. The failure mode is a value produced by a model nobody chose, silently. | `E04-07` fails fast with a reason naming the model; **no default exists in the code**. Proven by the resolution test and by row 13. |
| **Sampled artifact regenerated on resume**, silently changing the result | M | H | The sampled artifacts are **K4's and K5's** — the classes this epic's adapters declare. The consequence is `E05-03`'s, but the class and the evidence that make a test able to assert *"this one is not reproducible"* are produced here. | `E04-04`/`E04-05` report the class and populate `evidence` with the digest, `num_ctx`, sampling params and adapter revision — the only thing a test may assert on a sampled kernel (`kernel-cli.md` §7). |

**The plan-specific execution risk (`plan-01-kernels.md` §9) also touches E04 — as its first failure mode:**

> *Opening `S1-T21` before `S1-T12`–`S1-T17` are terminal. The contract test compares a command's flag set against its port signature. With no adapter landed there is no signature to compare against, so the test passes **vacuously** — a green suite that proves nothing.*

That risk is registered against `S1-T21`, but its **cause is the state of E04**. `E07-02` is therefore a **partial-completion issue**, and `E04-07` is the last of its inputs. Mitigation in this epic: E04's acceptance criteria are written so that *"the adapter landed"* means *"the port signature exists and a fake satisfies it"* — not merely *"a file exists"*.

**Risks excluded by the plan, stated rather than implied.** Three `wbs.md` §9 rows whose *Owner stage* is 2 are excluded from `plan-01-kernels.md` §9 by construction but materialise **in this epic** because this is where the external dependencies are touched: **Docling install/portability** (M/H — mitigated by keeping it behind the K4 port with a test double, pinning the adapter revision into the cache key and recording `engine_info` in evidence), **`pdftotext` is a poppler external binary** (M/M — a missing binary is a typed `Reason`, never a fallback reader), and **GPU availability for local models** (M/H — typed error naming the remedy; never a silent fallback model). They are named here with their `wbs.md` §9 mitigations so that the epic that carries them does not read as risk-free; they are **not** restated as new risks.

**Open decisions carried, not resolved:**

| `plan-01-kernels.md` §12 | Question | Touches in E04 | Effect if deferred past Stage 1 |
|---:|---|---|---|
| **#3** | Whether the 17-row matrix runs in CI at all stages, or only at Stage 1 | `S1-T22`'s suite structure — which asserts this epic's rows 3–14 | Rows for K4–K6 need GPU, tokens and provider availability. Unsplit, the suite becomes flaky and then ignored. `# TODO: [MVP]`: fast subset vs gated subset |
| **#5** | What Docling's determinism class actually is | `S1-T14` (reports `sampled`), `S1-T08` | Treated as `sampled`, so a lost OCR artifact makes a document permanently unreproducible. If a pinned Docling + pinned backend + pinned language pack is in fact deterministic on identical bytes, the OCR cache becomes a deterministic cache and the design gets simpler — **but `S1-T08`'s consequence is already built either way** |

Open decisions **#1**, **#2**, **#4**, **#6** and **#7** touch `S1-T20`/`S1-T21` (E07), `S1-T04`/`S1-T05` (E03), `S1-T08` (E05) and `S1-T09` (E05) and are carried there.
