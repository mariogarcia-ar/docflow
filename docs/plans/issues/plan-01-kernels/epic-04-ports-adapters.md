# E04 — Ports & the acquisition/generation adapters (K2–K6)

| Field | Value |
|---|---|
| Epic ID | **E04** |
| Capability | The five port interfaces plus the thin acquisition (K2/K3) and generation (K4/K5/K6) adapters, and resolution by capability |
| Issues | `E04-01` (`S1-T11`) — status `done` · `E04-02` (`S1-T12`) — **`in progress`**, 0 criteria unmet (§3) · `E04-03` (`S1-T13`) — **`in progress`**, 0 criteria unmet, criterion 8 restated (§3) · `E04-04` (`S1-T14`) — **`in progress`**, 2 criteria unmet (§3) · `E04-05` (`S1-T15`) — **`in progress`**, 0 criteria unmet, 3 documented deltas (§3) · `E04-06` (`S1-T16`) — **`in progress`**, 0 criteria unmet, 2 documented deltas (§3) · `E04-07` (`S1-T17`) — `todo` |
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
- **No adapter.** The five ports are `PdfSource`, `OcrEngine`, `LlmEngine`, `ArtifactStore`
  and `Registry`; the five adapter-or-kernel modules are `E04-02` … `E04-06`. The two sets are
  **not** the same five, and reading them as one is a mistake this line used to invite: `E04-02`
  delivers `kernels/pdf.py` **and** `adapters/pdf.py` behind `PdfSource`; `E04-03` delivers
  `kernels/image.py`, which is behind **no** port by design; and `LlmEngine` is covered by
  **two** of them (`ollama.py`, `frontier.py`). `ArtifactStore` and `Registry` are satisfied by
  K7's and K8's own kernels, which *are* the capability rather than wrappers over a vendor.
  This issue is interfaces and the isolation test.
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

**Status — `in progress`, 0 criteria unmet**

| # | Criterion | Status |
|---:|---|---|
| 1 | `classify` returns `text`/`image`/`mixed`/`blank` | ✅ met |
| 2 | `classify` detects invisible text and reports it as evidence | ✅ met, and stronger than the row requires — see below |
| 3 | `classify` reports contradicting producer metadata in `evidence` | ✅ met — asserted on a declared scanner whose page carries text, with a non-capture producer as the control so the flag is shown to carry information |
| 4 | `render` never upscales, no larger file produced | ✅ met, and verified against all 5 committed scans |
| 5 | Effective DPI measured from embedded pixels | ✅ met |
| 6 | `probe`, `extract_tokens` and `split` dispatch and return typed results | ✅ met |
| 7 | `split` preserves page count and boxes; mapping recorded | ✅ met |
| 8 | **The adapter is reachable only through `PdfSource`** | ✅ **met** — `docflow/adapters/pdf.py` |
| 9 | No threshold constant inside the module | ✅ met, guarded over public and private constants |

**Resolution of #8 — the criterion was right and the deliverable was incomplete, and the
work was larger than "a one-line deliverable change".** The previous reading recorded here
said the adapter was missing. Measuring it showed the sharper problem: `kernels/pdf.py`
**called the vendors itself** — `pymupdf` at line 233 and the `pdftotext` binary
(`_READER_BINARY`) — and `sad.md` §1 lists ``pdftotext`` among the **adapters**. So the
adapter was not merely absent; its work was fused into the kernel, and a pass-through shim
would have satisfied the criterion while changing nothing that mattered.

**What was done.** The split follows `ADR-004`'s arrow, and the direction is worth stating
because it is the opposite of the obvious one — a kernel may not import an adapter, which
`tests/kernels/test_store.py` enforces for the layer:

```text
ports/pdf.py            PdfSource        what a CALLER above Stage 1 depends on
      ^
adapters/pdf.py         PdfEngine        implements PdfSource; owns pymupdf + pdftotext
      |
      v  calls
kernels/pdf.py          the analysis     shapes, invisible text, contradictions; no vendor
      |
      v  asks through
kernels/pdf_vendor.py   PdfVendor        the seam the analysis declares
      ^
adapters/pdf.py         PyMuPdfVendor    the implementation over the two vendors
```

The consumer declares the interface and the implementer satisfies it — the same inversion
`PdfSource` uses one level up. `docflow/ports/` is **untouched**, so `E04-01`'s gate stays
closed: the page-fact surface the analysis needs is deliberately *not* a port member, and
`kernel-cli.md` §9 already lists `pdf facts` as an `MVP` target rather than Stage 1 scope.

**Measured outcome.** `isinstance(PdfEngine(min_chars=1), PdfSource)` is `True`, and all five
signatures match the port parameter for parameter. `kernels/pdf.py` imports only
`__future__`, `collections`, `contextlib`, `pathlib`, `re`, `types`, `typing` and
`docflow` — **no vendor module at all**, checked with an AST walk. The kernel went from 1689
to 983 lines; the vendor access it gave up is 947 lines in `adapters/pdf.py` plus the
363-line seam.

**`min_chars` is a required constructor argument, with no default.** `E04-02`'s criterion 9
forbids a threshold constant in the kernel, `ADR-009` makes the value corpus policy with no
override, and the port declares no threshold member — so the value enters at the adapter and
is threaded to `classify`. Constructing `PdfEngine()` raises `TypeError`, which is the point:
a default would be a routing decision taken by whichever layer happened to be constructed
first. Stage 3 reads it from `registry/policies/thresholds.yaml`, which does not exist yet.

**Two test defects were found by the mutation harness, not by reading the tests:**

- **The coordinate-conversion test was relative, so a constant factor passed it.** It
  compared a 72 DPI call against a 144 DPI one and asserted the ratio — which `scale = 1.0`
  satisfies, because both calls then scale by the same wrong factor. The units would have been
  wrong on every call while the suite stayed green. Fixed with an **absolute** anchor: at
  72 DPI the conversion is the identity, so a box must equal the reader's own `xMin`, read
  independently from `pdftotext -bbox` rather than from the kernel itself.
- **The harness cited seven test names that do not exist.** A mutation whose expected-failure
  set names a nonexistent test still reports `SURVIVED`, so the harness would have been
  reporting on a fiction. Every name is now verified against the suite.

**Verification.** **12 of 12 mutations falsified** (harness: `tests/adapters/mutation_pdf.py`),
628 tests green, four QA gates green, and the golden-set verifier re-run over the real corpus
with unchanged results — 5 scans refused, 0 files written while refusing, 0 invisible layers
in 23 inspected pages.

> **The same question recurs one issue later, and `E04-04` answers it by contrast.** `E04-03` carries the identical split: its deliverable is `docflow/kernels/image.py`, and its criterion asks for an adapter no issue in this epic names. But `E04-04`'s deliverable is *explicitly* `docflow/ports/ocr.py` **and** `docflow/adapters/docling.py` — and when the issue names the adapter as a deliverable, the criterion becomes satisfiable and was satisfied.
>
> That is the whole answer: **the gap is in `E04-02`'s and `E04-03`'s `Deliverable` lines, not in their criteria.** `E04-04` through `E04-06` name their adapters (`docling.py`, `ollama.py`, `frontier.py`) because those engines need a module of their own. `E04-02` and `E04-03` were written as kernel-only issues, so their adapter criterion asks for something nobody was assigned — the criterion is right and the deliverable is incomplete. Recorded here with that reading; **the fix is a one-line deliverable change on each**, and it is not made in this pass because it moves work between issues and that decision is the plan owner's.

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

**Status — `in progress`, 0 criteria unmet, with criterion 8 restated**

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
| 8 | **The engine is reachable only through the adapter** | ✅ **met, restated** — `docflow/adapters/image.py`; see below |
| 9 | No threshold constant inside the module | ✅ met — the threshold is a required parameter, and a test changes it on an **unchanged** image to prove it is the caller's |

**Criterion 8, restated — and why the original wording could not be satisfied.** It asked that "the adapter be reachable only through `RasterImage`". Three artifacts disagree on whether that port should exist:

- `kernel-cli.md` §4 lists `<raster lib> 11.1.0` in K3's **adapter** column, so an adapter is expected;
- `docflow/ports/__init__.py` states K3 has **no port**, deliberately — a raster library is the one engine that is not a vendor service behind a swap-able boundary — and `tests/ports/test_ports.py` asserts `not hasattr(get_ports_package(), "RasterImage")`;
- `RasterImage` appears in **no** frozen artifact (`plans/README.md`, `sad.md`, `plan-01-kernels.md`).

So satisfying the criterion literally would have meant adding a sixth port that a frozen document set at five, a module documents as unwanted, and a **green test asserts is absent**. The criterion's *substance* — the engine is reached through the adapter rather than living in the kernel — was deliverable, and was delivered. The wording is restated to name the adapter, and the epic's own reference to `RasterImage` is what moved.

**What the split did, measured.** `kernels/image.py` held `from PIL import …` in **four** places. The vendors moved to `adapters/image.py` (625 lines) and the decisions stayed:

| | before | after |
|---|--:|--:|
| `kernels/image.py` | 905 lines | 842 |
| imaging libraries it imports | `PIL` ×4 | **none** |
| `kernels/image_vendor.py` | did not exist | 360 lines (the seam) |
| `kernels/vendor_refusal.py` | did not exist | 64 lines (shared by both seams) |
| `adapters/image.py` | did not exist | 625 lines (owns Pillow) |

The line count fell by less than K2's did, and that is honest rather than disappointing: K3's analysis is *thinner* — 43 statements against 70 of vendor access — so most of what the module contained **was** the pixels. What moved is the whole of the library dependency; what stayed is the threshold comparison, the refusal, the inverse map and the orientation decision.

**This is the same inversion K2 uses, one level down.** A kernel may not import an adapter, so the vendor arrives as a keyword-only argument with no default, and the decisions ask through `RasterVendor` — a seam the *consumer* declares and the adapter satisfies. `docflow/ports/` is untouched.

**Three defects were found while doing this, and each was found by a check rather than by reading:**

- **A test defect that made three assertions meaningless.** The coordinate-conversion test compared a 72 DPI call against a 144 DPI one and asserted the *ratio* — which `scale = 1.0` satisfies, because both calls then scale by the same wrong factor. Fixed with an absolute anchor read independently from the reader.
- **A leaky test patch.** The adapter suite's "library absent" test patched `builtins.__import__` and undid it with `importlib.reload`, which does **not** restore the original importer. Every test after it saw a blocked Pillow and failed with a message about a substitute decoder — **nine tests lost their meaning while the suite still reported failures that looked like real ones.** Replaced with a fixture that restores in a `finally`.
- **An untested case the mutation harness exposed.** The tag *present and equal to 1* — a file declaring itself already upright — had no test. An implementation rotating on "a tag is present" would have passed both neighbouring tests while turning image after image by zero degrees and reporting that it had moved them.

**Verification.** **15 of 15 mutations falsified** (harness: `tests/adapters/mutation_image.py`), 646 tests green, four QA gates green. Three of the mutations had to be rewritten before they were falsifiable: the first version of M1 inserted a `return` after a `raise` and was unreachable, M10's anchor matched a case where the local and source boxes coincide, and M14 re-labelled a code the tests do not distinguish. **A mutation that cannot fail reports `SURVIVED`, so all three would have looked like test gaps.**

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

**Status — `in progress`, 2 criteria unmet**

| # | Criterion | Status |
|---:|---|---|
| 1 | The port and the adapter exist; the adapter is reachable only through the port | ✅ met — `isinstance(DoclingEngine(), OcrEngine)` holds, and `ports/ocr.py` imports no adapter (asserted over its syntax tree) |
| 2 | `read` returns positioned items with **no reading order resolved** | ✅ met — the engine's own order is preserved and never re-sorted; `reading_order: not_resolved` is in the evidence |
| 3 | Docling's layout output is dropped at the boundary | ✅ met — only text-bearing items with provenance leave; `layout_dropped: true` is asserted, and no layout or order field exists on the result |
| 4 | `read` returns a per-page status distinguishing `read` / `blank` / `unreadable` | ⚠️ **partially met** — `read` and `blank` are produced; **`unreadable` is never produced**, because Docling reports on the document rather than per page: a page it cannot read fails the whole conversion, which this adapter reports as one typed reason for the call |
| 5 | A blank page reports `blank`, never `read` with invented tokens | ✅ met |
| 6 | Token confidence is `float \| null`, and `null` is never coerced to `1.0` | ✅ met, and stronger than the row assumes — see below |
| 7 | `pages_requested` and `pages_read` are both reported | ✅ met, on the value and in the evidence |
| 8 | **No `--engine` flag and no engine setting anywhere** | ⚠️ **not verifiable here** — no CLI exists yet (`S1-T20`/`S1-T21`). The adapter exposes no engine selection, and a test asserts the constructor's `engine` argument is an injected converter rather than a setting; the flag-level assertion is `E07-02`'s and cannot run before its command does |
| 9 | `engine_info` is populated and feeds the cache key | ✅ met — `terms` carry `engine` and `engine_version` |
| 10 | Importable from the composition root, **not** from `docflow/ports/ocr.py` | ✅ met, both halves asserted |

**On #6 — the engine reports no confidence at all.** This is not a value that could have been coerced; `ProvenanceItem` carries `bbox`, `charspan` and `page_no` and nothing else, and no class in Docling's document model has a confidence or score field. So `Token.confidence` is `None` throughout. `capabilities` reports `reports_confidence: false` so that no caller reads a value the engine never produced, and row 10's assertion holds trivially and honestly rather than by a guard.

**A limitation a caller will meet, stated rather than discovered.** Docling reports **one item per text block, not one per word**. The command surface names its operation `read` and describes tokens; this adapter returns the engine's actual granularity. Splitting blocks on whitespace to look finer would give every word the *line's* box — a fabricated position, which is worse than a coarse one because it looks precise. The evidence carries `granularity: block` so the difference is visible at the boundary rather than inferred from short token counts.

**Two coordinate conversions happen, and one of them was nearly guessed.** Docling boxes use a **bottom-left** origin, where `t` is the greater y; source page coordinates grow downward from the top. The flip needs the page's height, which the box does not carry — and it has to come from `document.pages[n].size.height`, because deriving it from the box (`t + b`) measures **349.3** against a real height of **300.0** on the first fixture tried. A box whose page height is unknown is therefore **dropped**, not guessed: a coordinate computed from a guess is worse than a missing one. The units also scale by `dpi / 72`, because the engine reports points and the caller asked for a resolution.

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

**Status — `in progress`, 0 criteria unmet; 3 documented deltas**

| # | Criterion | Status |
|--:|---|:---:|
| 1 | Reachable only through `LlmEngine`; not importable from a port | met |
| 2 | The digest is recorded at first use and **compared for the remainder of the run** | met |
| 3 | `capabilities` reports the digest, never the tag alone | met |
| 4 | A missing model raises a typed error naming `ollama pull <model>` (`model_not_pulled`, exit `3`) | met |
| 5 | Truncation maps to a typed error (`truncated_output`, exit `2`) and is never parsed as complete | met |
| 6 | The raw completion is preserved so a truncated one is distinguishable without re-invoking | met |
| 7 | `structured`, `vision` and `warm` dispatch and return typed results | met |
| 8 | `evidence` carries model digest, `num_ctx`, sampling parameters, adapter revision | met |
| 9 | No `--api-key`-shaped flag and no secret in a flag | met |
| 10 | No default or fallback model: an unknown name never resolves to a working model | met |

**Verification performed.** Every row above is backed by a mutation that breaks it and a
test that catches it — **12 of 12 mutations falsified**, with each failure attributed to
the test named in its row (harness: `tests/adapters/mutation_ollama.py`). The four QA
gates are green on the whole workspace (578 tests). Two measurements shaped the
implementation and are **not** taken from the specification, because the specification
states the *requirement* rather than the runtime's behaviour:

- **`num_ctx` is the *loaded* window, not the declared one.** Measured on the live
  runtime: `smollm2` declares `context_length: 8192` in `model_info` but loads under a
  **4096** window when no `num_ctx` is named, and `/api/ps` reports the loaded value.
  Reporting the declared figure would report a number nothing used, which is the same
  class of error as keying on a moving tag. The adapter reads `/api/ps` and reports
  `None` — *not loaded* — rather than falling back to the declared value, since the two
  answer different questions.
- **`adapter_revision` comes from `/api/version`** (`ollama 0.31.1` in this workspace).
  When it cannot be read the term is `"ollama unknown"`, never a plausible-looking build:
  a fabricated revision would enter the cache key and let two different engines share one.

**Documented delta 1 — `model_unknown` is unreachable from `capabilities` on this path.**
The closed set attributes **both** `model_not_pulled` and `model_unknown` to K5
(`kernel-cli.md` §5), and the two are distinguished by *how* the name fails: absent
locally → `model_not_pulled` with the `ollama pull` remedy; resolving to no known model →
`model_unknown` with no default substituted. Against the real Ollama HTTP API **only the
first is reachable**: `/api/tags` is a local catalogue, so a name that is not in it is
absent, full stop — there is no registry lookup that could return *unknown* rather than
*absent*. The adapter raises `model_unknown` on a **non-200 `/api/chat` response**, which
is the one path where the catalogue and the runtime disagree, and the criterion's
substance (*an unknown name never resolves to a working model*) is asserted through
`model_not_pulled`. `E04-07`'s `--resolve-only` is where `model_unknown` becomes the
primary outcome, because resolution there spans a provider prefix as well as a model name.

**Documented delta 2 — the truncation assertion is made with `num_predict`, not a fixture.**
Row 12's committed fixture is `oversized-prompt.txt`, and a prompt long enough to overflow
`num_ctx` on a **128k** model is an impractical committed artifact. The test therefore cuts
the generation with a small `num_predict` and asserts `done_reason: length` →
`truncated_output`. This is the *same* signal (`done_reason`) and therefore the same code
path; what the fixture would add is the *cause* of the cut, not a different branch. Recorded
as a delta rather than presented as the fixture the row names.

**A third silent failure was found while verifying row 12, and it is not the one the row names.**
Row 12 is about the **output** being cut. Driving the real scenario against the live runtime
surfaced a second cut with no signal at all: the runtime **truncates an oversized prompt**
and reports nothing. Measured, one prompt of ~2,429 tokens with room left to answer came back
evaluated at **130** tokens under `num_ctx: 256` with `done_reason: "stop"` — no failure, no
`Reason`, and a confident answer to a question most of which had been discarded. At
`num_ctx: 1024` the same prompt evaluated at 514 tokens and reported `length`, so **whether
the cut surfaces at all depends on the window** — which is what makes it silent rather than
merely unhandled.

The adapter **cannot decide this without a tokenizer**, and a characters-per-token constant
would be this kernel choosing a threshold (`prd.md` FR-15). It therefore records **both**
sides — `prompt_characters` sent and `prompt_tokens` evaluated — so a caller can see the two
disagree, rather than smoothing the difference into a confidence the adapter does not have.
This is recorded as a **finding**, not presented as a satisfied criterion: row 12's assertion
(`truncated_output`, never a parsed partial) is satisfied for the case the row names, and the
input-side cut is a separate, previously unrecorded failure mode. **It belongs in
`kernel-cli.md` §11 as a row of its own**, and that artifact is frozen, so the observation is
recorded here for the plan owner rather than edited there.

**Documented delta 3 — `judge` is implemented here, and its row is not this issue's to satisfy.**
The epic lists K5's operations as `structured`, `vision`, `warm`, `capabilities` — and the
port declares a fifth, `judge`. An adapter that omitted it would not satisfy `LlmEngine`,
so the guard is implemented and the **role prohibition is enforced on this path too**: a
model asked to grade samples it produced is refused with `role_conflict`, compared
**tag-insensitively** so `smollm2` grading `smollm2:latest` is caught. Row 15's assertion
still belongs to `E04-06`, whose command is `MVP` and exits `4`; nothing here ticks it.

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

**Status — `in progress`, 0 criteria unmet; 2 documented deltas**

| # | Criterion | Status |
|--:|---|:---:|
| 1 | Reachable only through `LlmEngine`; not importable from a port | met |
| 2 | The raw completion is persisted before any parse | met |
| 3 | `429` honours `retry-after` verbatim | met |
| 4 | Sustained unavailability degrades to `provider_unavailable`, never to rejection | met |
| 5 | Absence, `null` and a present value stay three distinguishable outcomes | met |
| 6 | `call_record` is always populated: provider, revision, tokens, cost, latency, request id | met |
| 7 | Secrets come from the environment only; no `--api-key` flag | met |
| 8 | An unknown provider prefix fails with `provider_unknown`, exit `3`; no default provider | met |
| 9 | `judge` exists and its `role_conflict` path is implemented | met |
| 10 | `structured` and `vision` dispatch and return typed results | met |

**Verification performed.** Every row above is backed by a mutation that breaks it and a
test that catches it — **14 of 14 mutations falsified**, each attributed to the test
named in its row (harness: `tests/adapters/mutation_frontier.py`). `tests/adapters/test_frontier.py`
holds **45** tests; the workspace is at **628**, with all four QA gates green. No provider
key exists in this workspace and the tests need none: the transport is stubbed, which is
also what satisfies row 14's *"no committed fixture — the row needs an **unreachable
provider**"* (`kernel-cli.md` §12) directly rather than by pointing a host setting at a
closed port.

**Two defects were found by the mutation harness, not by reading the code.** Both are
recorded because each is an instance of the exact failure class this issue exists for:

- **A `200` whose body is not JSON crashed the adapter.** `response.json()` was called
  unguarded, so an intercepting proxy, a captive portal or a truncated response raised
  `ValueError` straight out of the caller's stack. That is an *unhandled* failure where
  the whole point is a *typed* one, and it also read as a failure of the document rather
  than of the provider's response. Now guarded, reported as `unsupported_format` with
  `body_is_json: false` in the evidence.
- **The suite's stub answered `{}` where a real client raises.** The first version of the
  stub returned an empty mapping for an unparseable body, so the test above passed against
  a client that cannot exist — the *"a suite green for the wrong reason"* pattern. The stub
  now raises, which is what made the mutation falsifiable.

**Documented delta 1 — row 14's raw bytes and the `CallRecord` cannot ride on `KernelResult`.**
`kernel-cli.md` §9 says *"the raw completion and the parsed structure are returned
separately"* and *"`call_record` is always populated"*, while E01 froze `KernelResult` at
three fields. The adapter therefore exposes both as **properties** — `last_raw_completion`
and `last_call_record` — rather than growing the frozen type or adding a method to the port
(which would re-open `E04-01`'s gate). `E07-02` composes the envelope and already carries a
`CallRecord` field on its own `Call` type for exactly this reason. The two properties are
deliberately **not** counted among the port's operations, and
`test_the_adapter_exposes_the_ports_five_operations_and_no_more` asserts that.

**Documented delta 2 — `model_revision` is `"unresolved"` on the paths that never reached the provider.**
A rate limit, an outage and a rejected credential all happen before the provider says which
revision answered, so no revision exists. The term says `"unresolved"` with the requested
name beside it as `model_name`, because substituting the *name* for the revision would be
the same class of mistake as keying a cache on a moving tag — a hosted model is updated
under a fixed name. On success the term is the provider's own revision, and
`test_a_resolved_call_reports_the_providers_revision_not_its_name` asserts the difference.
`cost_usd` is likewise `None` on every path: the price is a billing fact this adapter does
not look up, and a hardcoded rate card would be a number that silently goes stale
(`# TODO: [MVP]`).

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

### Contradiction flagged — who binds `ArtifactStore`, and to what

`E04-01`'s out-of-scope note says `ArtifactStore` and `Registry` *"are satisfied by K7's and
K8's own kernels, which **are** the capability rather than wrappers over a vendor."*
`ports/store.py` says the opposite in its own class docstring: *"The filesystem adapter binds
this to ``docflow/kernels/store.py``."* Both sentences are in the specification, and until
`docflow/adapters/store.py` was written, **no issue in this epic owned the module the port
names.** `E04-07` is resolution of a *provider/model* by capability; it is not artifact
storage, and no other issue in E04 or E07 names the file.

- **Why the port's sentence won, for the store path.** The two claims are not equally
  testable. *"The kernel is the capability"* is a statement about intent; *"a caller can
  depend on `ArtifactStore`"* is a statement about the dependency arrow, and it was
  **false**: `kernel_cli/main.py` imported `docflow.kernels.store` and never the port, so
  the kernel had become the interface in fact regardless of what the port declared, and
  `sad.md` §1's promise — *"moving from local files to object storage is a change at the
  bottom and invisible above it"* — did not hold. `docflow/adapters/store.py` is that seam.
  It hides no vendor (K7 imports only the standard library); what moves is the filesystem.
- **What the adapter had to *not* do, and the contradiction this exposed.** It cannot
  implement `rebuild_manifest`, because the port requires it to delegate to K1's
  `rebuild_index()` and K1 does not exist yet (`E05-01`, `S1-T06`). It returns a typed
  `engine_unavailable` naming the missing dependency rather than deriving a summary from a
  rule of the store's own — a manifest K7 assembled would be the store claiming to know what
  a run means, which `sad.md` §3 assigns to K1.
- **A second defect the port's own wording forced out.** `verify` must answer `False` only
  when the answer is *no*, and must carry a `Reason` when the question could not be **asked**.
  `kernels/store.py` reduces it to `is_file()`, which answers `False` for *"no such file"* and
  for *"I cannot look here"* alike — so an unreadable root came back as *"the artifact is
  corrupt"*, which is precisely the collapse `ports/store.py` says it exists to prevent. The
  distinction is drawn in the adapter, from the path parts, because `Path.exists()` discards
  `ENOTDIR` along with `ENOENT` and cannot draw it at all.
- **What this does *not* resolve, and is owed to the `Registry` path.** The epic's sentence
  names `ArtifactStore` **and** `Registry`. K8 has the same shape as K7 — a kernel that is the
  capability, with no vendor behind it — so if the port's sentence is right for the store it
  is right for `Registry`, and if the epic's sentence is right for `Registry` the two rows of
  the same sentence disagree. `ports/registry.py` has **not** been changed and no adapter for
  it has been written. **This is a decision for the user**, not for the plan: the epic's
  sentence and the port's sentence must end up saying the same thing, and which one moves is
  a specification change.

**Evidence for the store path** (recorded, not asserted): `docflow/adapters/store.py`;
`tests/adapters/test_store.py` — 24 tests, including a signature-by-signature comparison
against the port, since `runtime_checkable` asserts only that a member *exists* and an
implementation taking an extra required argument would satisfy it while being uncallable as
the port declares; `tests/adapters/mutation_store.py` — 20 mutations, all falsified, the
harness **refusing to score a mutation whose anchor is absent** so that a missed anchor cannot
report a pass.

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
