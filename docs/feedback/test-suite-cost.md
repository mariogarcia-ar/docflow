# Test-suite cost — engine doubles and test tiers

> Status: **proposed**. This is an analysis report, not a plan artifact. It measures the
> test-cost problem, locates its cause in the plan text, and proposes one change; it does
> **not** modify `docs/plan/` (a change there re-opens the gate that froze it).
> **Annex A** expands §10 into a document-by-document edit spec; **Annex B** closes the
> drift risk this report names. Both record feedback received in Spanish after the first
> draft, restated here in English with every task ID, path and literal string preserved.
> Items marked **⚠ review note** are corrections flagged before the edit is applied.
>
> Branch analysed: `release2` (HEAD `f953e97`). Cross-checked: `release1`, `main`.
> Measurements taken 2026-09-23 on the development machine below.
> Sources (read-only): `docs/plan/README.md`, the five `subplan-procesador-*.md`, the six
> `wbs-*.md`, `pyproject.toml`, the `tests/` trees of the three branches.

## 1. Finding

The complaint was *"the tests were built against real engines and took extremely long"*.
It is confirmed, but not on the branch being worked on:

- **On `release2` the suite is fast** — 61 tests, 0.23 s, and no module imports an engine.
  The problem is **latent**: it arrives with `PDF-13`, `IMG-13` and `OCR-12`.
- **On `release1` and `main` it already materialised** — 31 and 38 test modules
  respectively drive a real engine, `release1` has **no `conftest.py` at all**, and a
  70 MiB corpus is committed inside `tests/fixtures/`.
- **The root cause is in the plan, and it is asymmetric.** The plan deliberately gave a
  test double to `llm-call` (`LLM-03`) and to the orchestrator (`FakePdf/FakeImage/
  FakeOcr/FakeLlm`), and gave none to `pdf`, `image` and `ocr` — so every invariant of
  those three processors ends up paying for a real Docling / OpenCV / Poppler run.
- **The fix is to replicate the pattern the plan already blessed, not to invent one.**
  The engine double lives behind `primitives/`; the real engine runs once per processor as
  the phase-exit evidence.
- **One decision was open** (§7) and is now **resolved — Option A** (Annex B §3): `pytest`
  keeps meaning "everything", and `pytest -m "not engine"` is a documented local-loop
  shortcut that never replaces the gate. It mattered more than expected: this repository has
  **no CI configuration at all** (Annex B §3), so a default that deselects the real tier
  would leave nothing running it.

## 2. Evidence (measured)

| Observation | Value | How it was measured |
|---|---|---|
| `release2` suite | **61 tests, 0.23 s** | `python -m pytest -q --durations=10` |
| Engine imports in `src/` + `tests/` on `release2` | **0 modules** | `grep -rln -E '(^|[^a-z])(import\|from) +(docling\|cv2\|PIL)' src tests` |
| Sole engine mention on `release2` | `tests/test_skeleton.py` names 10 engines as **strings** to assert they are *not* imported | `tests/test_skeleton.py`, `ENGINE_MODULES` |
| Declared dependencies | `dependencies = []`; dev = `pytest`, `pytest-cov`, `ruff`, `pylint` | `pyproject.toml` |
| Markers | **not defined**; `addopts = "-ra --strict-config --strict-markers"` | `pyproject.toml` `[tool.pytest.ini_options]` |
| Engines present in the dev env anyway | `docling`, `cv2`, `PIL`, `fitz` **installed**; `ollama` missing; Poppler CLIs (`pdftotext`, `pdfseparate`, `pdfimages`, `pdftoppm`) at `/opt/homebrew/bin` | `importlib.util.find_spec`, `command -v` |
| Engine import cost | `cv2` **0.62 s**, `fitz` 0.13 s, `PIL.Image` 0.05 s, `import docling` 0.02 s | timed imports |
| `release1` test tree | **64** `.py` under `tests/`, **31** matching an engine regex | `git ls-tree -r` / `git grep -l` |
| `main` test tree | **58** `.py`, **38** matching an engine regex | idem |
| `conftest.py` | `release1`: **none**. `main`: one, and only at `tests/poc_flow_v2/conftest.py` | `git ls-tree -r -- '*conftest.py'` |
| Fixtures on disk (`release2`) | **106 files, 71,936 KiB** — 105 fixture files + `manifest.json` | `find` / `du -k` |
| `tests/fixtures/manifest.json` | records `99` files / `73,193,814` bytes → **stale** against the tree | `cat` |
| Fixture weight by folder | `grandes/` 44 MiB · `otros/` 14 MiB · `casos/` 6.1 MiB · `expected-extraction/` 2.4 MiB · `pdf_escaneados/` 2.2 MiB | `du -sh tests/fixtures/*/` |
| Do any tests on `release2` read that corpus? | **No** — no test module references `fixtures/` | `grep -rn 'fixtures' tests --include='*.py'` |
| Fixtures the subplans name | **absent on `release2`** — there is no `tests/fixtures/pdf/`, `.../image/`, `.../ocr/` | `ls` |
| Same fixture on `release1` | `ocr/ocr_prepared_text_and_table.png` = **347,458 bytes** — a real scan, not the synthetic minimal page `OCR-12` describes | `git cat-file -s` |
| Plan citations of `pytest` | **28 occurrences across 12 plan documents** | `grep -rn 'pytest' docs/plan --include='*.md'` |
| Existing half-measure on `release1` | `tests/ocr/primitives/engine_corpus.py` caches one conversion per process (`lru_cache`), introduced because per-module copies *"paid for two conversions of one image"* | file docstring |

**Correction to figures stated earlier in this conversation.** I reported "74 test modules"
for `release1`/`main`. The exact counts, measured above, are **64** and **58**.

## 3. Where the cost is — and where it is not

| Branch | Architecture | Test modules | Files driving an engine | Gate cost today |
|---|---|---|---|---|
| `release2` (current) | one sub-package per processor, Phase 0 only: contracts, `states.py`, `identities.py`, `entrypoints.py` stubs | 15 | 0 (3 files match a broad regex; none import an engine) | 0.23 s |
| `release1` | same architecture, Phase 1 primitives implemented (`tests/{pdf,image,ocr}/primitives/*`, `tests/tools/*`) | 64 | 31 | minutes |
| `main` | a different design entirely: `kernels/`, `ports/`, `adapters/`, `kernel_cli/`, `poc_flow_v2/` | 58 | 38 | minutes |

The plan in `docs/plan/` governs `release2`/`release1`. `main` implements the other
specification (`.github/copilot-instructions.md`: K1–K8 kernels, ports, adapters,
`docflow-kernel`). They are not the same codebase and the fix below is aimed at the
`release*` line.

## 4. Root cause in the plan

### 4.1 The double was planned for two components and not for three

| Component | Test double planned? | Where the plan says it |
|---|---|---|
| `llm` | ✅ | `subplan-procesador-llm-call.md` §4, `LLM-03`: *"In-memory fake provider … so the whole processor can be tested without a real model"* |
| `orchestrator` | ✅ | `subplan-orquestador.md` §6: *"`FakePdf`, `FakeImage`, `FakeOcr`, `FakeLlm` … the fakes stand in for the real processors"* |
| `pdf` | ❌ | `subplan-procesador-pdf.md` §6 — happy path is real Poppler |
| `image` | ❌ | `subplan-procesador-image.md` §6 — happy path is real OpenCV |
| `ocr` | ❌ | `subplan-procesador-ocr.md` §6 — happy path is real Docling |

That asymmetry is the defect: the plan budgeted the test cost of two processors out of
five, and the three it skipped are exactly the three whose engines are heavy.

### 4.2 "Real bytes" was read as "real engine"

The recurring DoD sentence — *"a green happy-path test proving `Request → Result` with real
bytes from a small committed fixture"* (`README.md` §5, Phase 1 exit) — is about the
**input**: not `b""`, not a synthetic stub. The plan itself separates the two ideas
everywhere else:

- `README.md` §4: *"engines are replaceable **implementations** behind each processor's
  public contract … encapsulated inside that processor's `primitives/`"*.
- `README.md` §9.3: each engine *"is swappable behind `Request → Processor → Result`
  without touching the contract"*.
- `OCR-02`/`IMG-02`/`PDF-02` already plan a mockable `primitives/` skeleton —
  `PDF-02`'s scope reads *"the low-level function signatures of PDF-03 … PDF-08 declared
  and mocked"*.

So the seam for a double **already exists in the WBS**. What is missing is the double, and
the tiering of the tests — not a new design.

### 4.3 The plan also mandates a multiplier

`GEN-16` requires every non-obvious guarantee to be *mutation-falsified*: mutate → observe
failure → restore → re-run green. `subplan-procesador-ocr.md` §6 lists three invariants,
each with a documented mutation. Read as whole-suite runs, that is two extra full suites
per invariant — on top of the four acceptance scenarios, one of which (determinism)
converts twice by construction. That is the arithmetic behind "extremely long".

## 5. Cause audit

Causes raised in the working diagnosis, checked against the evidence above:

| # | Cause | Verdict |
|---|---|---|
| 1 | Model loaded per test, not per session | **Confirmed, and worse than stated.** `release1` has **no `conftest.py`**, so nothing session-scoped exists. The only reuse is `lru_cache` in `tests/ocr/primitives/engine_corpus.py` — process-wide, therefore cold in each of the **11 `subprocess`-driving test files**. Enabler already in the plan: `OCR-03` splits `load_docling_pipeline` from `configure_image_pipeline`, so a session-scoped *load* plus per-test *configure* is directly supported. |
| 2 | Fixtures larger than needed | **Confirmed twice.** (a) The named OCR fixture is 347 KB, a real scan. (b) A 70 MiB corpus sits inside `tests/fixtures/` (`grandes/` 44 MiB), which is corpus, not fixtures — and nothing on `release2` reads it. |
| 3 | The determinism test runs the engine twice | **Confirmed, by design** — but it is 2 of ~10–16 conversions in that module, not the main multiplier. |
| 4 | `dpi = 200` in the PDF render | **Real but second-order.** `subplan-procesador-pdf.md` §9.3 freezes 200 as the production *default*; a test may pass a smaller value without touching it, and `PDF-02` already declares the primitive mocked. |
| 5 | No separation of primitive-unit vs real-engine tests | **Confirmed, structural.** No task in `GEN-01…GEN-20` or in the three processors' WBS assigns a test tier. |
| 6 | *(not listed)* `GEN-16` multiplies engine work | **Confirmed.** The rule only needs the **guarded test** re-run, not the suite — but as written it reads as a suite re-run, ×2 per invariant. |
| 7 | *(not listed)* `subprocess`-driven tests | **Confirmed.** `release1`: 11 test files use `subprocess`; each re-pays imports (`cv2` alone is 0.62 s) and, for tool-level tests, a model load. |

## 6. The proposed fix

### 6.1 Principle

> The real engine runs **once per processor** — the acceptance test *"`Request → Result`
> with real bytes"* — not once per invariant. Everything else (normalization, deterministic
> ordering, tables, validation, atomic publication, classification, error handling) is
> proven against a **double that implements the same `primitives/` surface**.

### 6.2 Per processor

| Processor | Double | Real-engine tier keeps |
|---|---|---|
| `ocr` | `FakeDoclingEngine` returning a synthetic but realistic `OCRDocument` (blocks, a 2×2 table, text) built in memory, no model load | the happy path, **and** the two properties only the engine can show (see §8) |
| `pdf` | `FakePopplerEngine` behind `extract_page`, `render_page_to_image`, `extract_text_from_page`, `get_text_blocks`, `extract_images_from_page` | the happy path; the fakes make input-immutability and atomic publication testable without shelling out |
| `image` | `FakeImageEngine` behind `load/store`, `analysis`, `transformation` | the happy path, **asserting concrete metric values with a tolerance** (see §8) |

### 6.3 Injection point — the one design constraint

The double **must not** arrive as a parameter on the public entry point. `OCRRequest`,
`PDFRequest` and `ImageRequest` are frozen Phase 0 contracts (`GEN-02`), and the plan takes
an explicit position: *"**The engine is not a flag.** There is no `--engine` option, because
Docling is fixed and never a user-selectable setting"* (`subplan-procesador-ocr.md` §10).
An `engine=` parameter is the same knob through another door.

Two consequences:

1. The double is a **module-level** double (same function names), not a class implementing
   a Protocol — unlike `LLMProvider`, where an interface type exists. Injection is by
   replacing what the private primitive layer resolves.
2. That shape **already exists in this repository**: `release1` has
   `src/docflow/ocr/primitives/engine.py` exposing `docling_module()`,
   `converter_module()`, `is_engine_available()`, `engine_provenance()`,
   `loaded_engines()`, and `tests/ocr/primitives/test_engine.py` already patches them —
   including a `with_engine_absent` context manager. Adopt that shape; do not invent a new
   one.

### 6.4 Guards the change needs

- **No fallback in the library.** No `if engine is None: use_fake` anywhere under `src/`.
  The double is a *test* double; a fake selected by the library would violate the plan's
  "no silent stand-in" rule.
- **New frontier assertion:** no module under `src/docflow/` imports anything under
  `tests/`. This replaces the assertion that used to live in the removed lab-tool section
  and belongs beside `GEN-18`/`GEN-19`.
- **`GEN-01` must stay green:** `tests/test_skeleton.py` asserts that importing the
  skeleton pulls in none of `docling`, `cv2`, `PIL`, `fitz`, `pypdfium2`, `pdf2image`,
  `openai`, `ollama`, `anthropic`, `httpx`. Keeping the doubles in `tests/` satisfies it.
- **Naming.** The orchestrator already plans **contract-level** fakes (`FakePdf`,
  `FakeImage`, `FakeOcr`, `FakeLlm`, `subplan-orquestador.md` §6). These are
  **primitives-level** doubles. Name them apart (`tests/fakes/engines/fake_docling.py`,
  `FakeDoclingEngine`) and say in the orchestrator subplan that its fakes stand in for the
  *processor*, not the engine — otherwise a later reader will reuse one for the other.

## 7. What does `pytest` mean?

> **Resolved — Option A**, per the feedback in Annex B §3: `pytest` without flags keeps
> meaning *everything*, including the one real-engine test per processor;
> `pytest -m "not engine"` is a documented local-loop shortcut that never replaces the
> gate. The A/B analysis below is kept as the record of why.

The rejected alternative was flipping the default with `addopts = "-m 'not engine'"`,
expecting `pytest -m engine` to reach the real tier. **Verified** in a scratch project in
`/tmp`:

```
addopts = "-m 'not engine'"
markers = ["engine: hits a real third-party engine"]

python -m pytest -v            → test_fast          PASSED   (1 passed, 1 deselected)
python -m pytest -v -m engine  → test_real_engine   PASSED   (1 passed, 1 deselected)
```

A command-line `-m` **does** override the `addopts` one (last wins), so the mechanism
works. The objection is policy: `pytest` currently **is** the gate, in 28 statements across
12 plan documents. If it silently deselects the engine test:

- a task can be closed "DoD met" with the real happy path never executed;
- the Phase 1 exit — *"each processor has a green happy-path test proving
  `Request → Result` with real bytes"* — stops being proven by the gate command;
- a test deselected by default rots silently the day it breaks.

| Option | Change | Cost |
|---|---|---|
| **A (recommended).** `pytest` stays "everything"; add one documented inner-loop command `pytest -m "not engine"` as a convenience, explicitly *not* a gate | `README.md` §7, one sentence | 1 edit; gate integrity intact |
| **B.** Flip the default; the fast gate becomes `pytest -m "not engine"` and `pytest -m engine` becomes a mandatory close-out step | re-word the gate in all 12 documents that state it | ~20 edits; every "four gates" phrase becomes a two-command ritual |

The choice is about where the speed should be *by default*, not about what is technically
possible. Option B is defensible for a PoC if applied everywhere; it must not be applied
only in `pyproject.toml`, or the plan will contradict itself.

## 8. Per-processor caveats — where "once per processor" is too strong

| Processor | Caveat |
|---|---|
| `pdf` | No caveat on the fake, but note the cost model: Poppler is reached through **CLI subprocesses**, so the cost is per *call*, not per session — a session fixture buys nothing here. The win is the double plus minuscule fixtures. |
| `ocr` | Two things must stay real. (a) `subplan-procesador-ocr.md` §8 flags *"Docling residual non-determinism"* and *"Docling schema changes between versions"* as risks, and the fake's `OCRDocument` is **our** schema — so the conformance test is the only detector of a Docling shape change. (b) Determinism *of the engine* needs two conversions. Resolution: **one real test, two conversions**, folded into the happy path — one test, not one conversion. |
| `image` | The feedback's example (force an exact blur score to test the `LOW_QUALITY` threshold) is right but does not need an engine double: `IMG-09` already plans a unit test over crafted `ImageMetrics`. The real risk is the opposite: the whole metric computation lives inside `image/primitives/`, i.e. exactly what the double replaces. If only one happy-path test touches OpenCV, **OpenCV version drift becomes invisible**. The real tier must assert 2–3 concrete metric values with a tolerance, not merely `status == "success"`. |
| `ocr` (cache hazard) | The `lru_cache` corpus pattern on `release1` must not be shared across tiers: a cache key that does not include *which engine* produced the document will serve a real `OCRDocument` to a fast-tier test. |

A note in the double's favour: a fake that returns blocks in **adversarial (unsorted)
order** makes the determinism mutation *detectable*, whereas the real engine's incidental
ordering can make the test pass for the wrong reason. For the three OCR invariants the fake
tier is not a downgrade — it is a stronger test.

## 9. Test-data hygiene (separate, but blocking the same goal)

1. The corpus inside `tests/fixtures/` (70 MiB, `grandes/` 44 MiB, `pdf_large/`) is
   **unreferenced on `release2`** and is corpus material, not fixtures. It belongs outside
   the test tree. Deleting it also removes 70 MiB from the repository.
2. The three fixtures the subplans actually name do **not exist** on `release2`; on
   `release1` the OCR one is a 347 KB scan. Create them as genuinely minimal artifacts
   (one page, short text, one small table).
3. `manifest.json` disagrees with the tree (99 files recorded vs 105 present). Either
   regenerate it or drop it — a stale manifest is worse than none.
4. `expected-extraction/` (26 files, 2.4 MiB) should be classified explicitly: if it is
   golden data, the plan defers goldens to after the MVP gate (`README.md` §2) and it must
   not enter Phase 1 tests.

## 10. Plan edits this report proposes (not applied)

**Annex A restates this list document by document, with the literal text to insert, and
flags the points that still need a decision; Annex B adds the mechanisms that stop the
real-engine tier from rotting in silence.**

1. `docs/plan/README.md` §9 — a new resolved decision: **test tiers**, the `engine`
   marker, the double lives behind `primitives/` and is a test double only, never a
   fallback; the real-engine happy path remains the phase-exit evidence.
2. `docs/plan/README.md` §7 — the chosen **Option A** wording (Annex A §A.1).
3. `docs/plan/issues/wbs-general.md` — one cross-cutting issue (the `GEN-21` slot freed by
   the lab-tool removal reads naturally as *engine doubles and test tiers*); extend
   `GEN-05` with the `markers = [...]` registration (required, because
   `--strict-markers` is on); add the frontier assertion *"`src/docflow/` never imports
   `tests/`"* beside `GEN-19`.
4. `subplan-procesador-{pdf,image,ocr}.md` §6/§7 — one line each, carrying that
   processor's caveat from §8.
5. `subplan-orquestador.md` §6 — one sentence distinguishing its contract-level fakes from
   the primitives-level doubles.
6. Test-tree hygiene, per §9.

## 11. Trade-offs, honestly

| Gained | Cost |
|---|---|
| Real-engine work per processor drops from ~10–16 conversions to 1 (OCR: 1 test, 2 conversions) | The double can drift from the engine's real behaviour as Docling changes its output structure between versions — which is why the conformance test is **reduced, never removed** |
| `GEN-16`'s mutation multiplier disappears (the mutated code is in the fast tier) | The fast tier proves *our* logic, not *the engine's*; engine-level properties are covered by exactly one test per processor, so a regression there is caught late |
| The inner loop runs in seconds and on a machine **without** Docling installed | A fast default (Option B) weakens the single-command gate unless the plan text is updated in all 12 documents |
| 70 MiB and 105 files leave the test tree | Someone must re-create the three minimal fixtures deliberately |

## 12. Not measured / open questions

- **Docling's real conversion time** on this machine was *not* measured: building
  `DocumentConverter` loads models and may fetch them. The report therefore quantifies the
  problem by *counts of engine invocations* and *import costs*, not by wall-clock seconds
  per conversion.
- Whether Docling is safe under `pytest-xdist` (concurrent model use, memory) is unverified
  — so xdist is deliberately **not** part of this proposal. It reduces wall-clock only, and
  multiplies model loads by worker count; it should be considered last, once the per-test
  cost is bounded.
- The `release1`/`main` numbers were measured on their committed trees, not by running their
  suites (that is the very cost under discussion).
- `main` implements a different specification (kernels/ports/adapters). Whether the same
  tiering applies there is out of scope for this report.

---

# Annex A — Plan edits, document by document

The principle this annex fixes:

> The real engine runs once per processor, as the phase-exit evidence (the happy path of
> `PDF-13` / `IMG-13` / `OCR-12`). Everything else in `pdf`, `image` and `ocr` runs against
> a **module-level double** that implements the same `primitives/` surface — the same
> pattern the plan already applied to `llm` (`LLM-03`) and to the orchestrator (contract
> fakes, `subplan-orquestador.md` §6). The double lives only in `tests/`, is never
> importable from `src/`, and is **not** a fallback: there is no
> `if engine is None: use_fake`.

## A.1 `docs/plan/README.md`

**§9 Resolved decisions — new entry #7.** Text to insert:

> **Test tiers and engine doubles — RESOLVED.** The real engine runs exactly once per
> processor, as phase-exit evidence (the happy path of `PDF-13` / `IMG-13` / `OCR-12`).
> Everything else in `pdf`, `image` and `ocr` runs against a module-level double
> implementing the same `primitives/` surface — the same pattern the plan already applied
> to `llm` (`LLM-03`) and to the orchestrator (contract fakes,
> `subplan-orquestador.md` §6). The double lives only in `tests/`, is never importable
> from `src/`, and is not a fallback: no `if engine is None: use_fake`.

**§7 Quality gates — what `pytest` means.** Text to insert:

> `pytest` (no flags) still means "everything", including the single real-engine test per
> processor. `pytest -m "not engine"` is a documented inner-loop shortcut, never a gate.

Without this the README reads as if `pdf`/`image`/`ocr` sat at the same test-cost level as
`llm` — they do not, and that asymmetry is the root cause.

⚠ **Review note.** §9 currently ends at item #6, so #7 is correct; but the `README.md` §7
block is the *third* place this appears (after §9.7 and Annex B §3). Write it once and
cross-reference, or the three copies will drift.

## A.2 `subplan-procesador-pdf.md`

- **§3 Engine encapsulation** — add an explicit double: `FakePopplerEngine` behind
  `extract_page`, `render_page_to_image`, `extract_text_from_page`, `get_text_blocks`,
  `extract_images_from_page`, returning deterministic synthetic data. Note: Poppler is
  invoked per CLI call, so there is no in-session model to amortise — **a session-scoped
  fixture buys nothing here**; the saving comes from the double alone.
- **§6 Test plan** — split into two tiers explicitly: *fast* (invariants 1–3, `PDF-08`
  classification, `PDF-11` validation, `PDF-12` atomic publication → all against the fake)
  and *real* (`PDF-13` happy path only, one Poppler invocation).
- **§4 WBS** — new task, e.g. `PDF-14` *"Engine double `FakePopplerEngine` + `engine`
  marker registration"* (Effort S, depends on `PDF-02`, blocks `PDF-13`). Update the WBS
  header's ID range accordingly.

⚠ **Review note — the free ID.** `PDF-14` was the *lab tool*, removed earlier today, so the
range is now `PDF-01 … PDF-13` and **`PDF-14` is free**. Using it (rather than the
proposed `PDF-15`) keeps the range contiguous, which is what `wbs-general.md` §7 requires
("their ID ranges are unique and non-overlapping"). It also removes one edit from every
document that cites the range. Same argument for `IMG-15` and `OCR-14` in A.3/A.4.

⚠ **Review note — the fake's surface is incomplete.** The list above omits `PDF-03`'s
engine calls (`get_pdf_metadata`, `get_page_count`, `get_page_dimensions`, `inspect_pdf`),
which are engine-bound and must be on the double's surface. Conversely `analyze_pdf_page`
and `classify_pdf_page` (`PDF-08`) must stay **real code** — they are our composition, not
the engine, and `PDF-08`'s test over crafted metric vectors already covers them.

## A.3 `subplan-procesador-image.md`

- Same pattern: `FakeImageEngine` behind load/store, analysis and transformation.
- **Caveat to state explicitly**, or the fix introduces a new risk: the single test that
  touches real OpenCV must assert **2–3 concrete metric values (blur / sharpness /
  contrast) with a tolerance**, not merely `status == "success"`. `IMG-09` already covers
  the `LOW_QUALITY` threshold with crafted `ImageMetrics` against the fake, so if the only
  real contact point checks success alone, an OpenCV version drift becomes invisible.
- New task `IMG-15` *"Engine double + marker"* (depends `IMG-02`, blocks `IMG-13`); ID
  range → `IMG-01 … IMG-15`.

## A.4 `subplan-procesador-ocr.md`

- `FakeDoclingEngine` behind `convert_image_with_docling`, returning a synthetic
  `OCRDocument` — deliberately with its blocks in **adversarial (unsorted) order**, so that
  invariant 1 (deterministic ordering) actually discriminates. With the real engine,
  incidental ordering can make the test pass for the wrong reason.
- Resolve the `GEN-16` multiplier explicitly: the *engine-determinism* property (run twice,
  compare `document.json`) is **folded into the same real test in `OCR-12`** — one test,
  two conversions — instead of being a separate suite run.
- Cache-risk note: if the `lru_cache` pattern from `engine_corpus.py` (seen on `release1`)
  is reused, the cache key must include **which engine** (real vs. fake) produced the
  result, or the fast tier can end up serving real output and vice versa.
- New task `OCR-14` *"Engine double + marker"* (depends `OCR-02`, blocks `OCR-06…OCR-09`
  and `OCR-12`); ID range → `OCR-01 … OCR-14`.

⚠ **Review note — the block list is too narrow.** The double must gate every task whose
tests need a converted document: `OCR-05` (deterministic normalization — the very target of
invariant 1), `OCR-10` (atomic persistence) and `OCR-11` (entry points) are missing from
the proposed list. Recommend "blocks `OCR-05`…`OCR-12`".

## A.5 `subplan-orquestador.md`

- **§6** — one missing sentence: `FakePdf`/`FakeImage`/`FakeOcr`/`FakeLlm` are fakes at the
  **processor-contract** level (they replace `process_pdf`/`process_image`/… wholesale),
  whereas the new `FakePopplerEngine`/`FakeImageEngine`/`FakeDoclingEngine` are at the
  **primitives** level (they replace only the engine inside a real processor). Without this
  line a future reader will try to reuse one for the other.

## A.6 `wbs-general.md`

- **Extend `GEN-01`** (Scope / Deliverables): the skeleton import check also asserts that no
  module under `tests/fakes/` is imported from `src/docflow/` — the same spirit as its
  existing 10 `ENGINE_MODULES` list.
- **Extend `GEN-05`**: register
  `markers = ["engine: hits a real third-party engine (Poppler/OpenCV/Docling); slow"]` in
  `pyproject.toml` — **mandatory**, because `--strict-markers` is already on.
- **New task `GEN-22`** *"Engine doubles and test tiers"* (Phase 4, tooling, M): fixes the
  principle once (real engine = phase-exit evidence, everything else against a double), the
  naming convention (`tests/fakes/engines/fake_<engine>.py`), and the injection shape
  (module-level functions patched in tests — **not** an `engine=` parameter on the contract,
  **not** a `Protocol`; `PDFRequest`/`ImageRequest`/`OCRRequest` are frozen by `GEN-02` and
  the plan explicitly forbids an engine flag).
- **Extend `GEN-19`**: add the assertion "no module under `src/docflow/` imports anything
  under `tests/`", beside the existing `primitives/` assertion.
- This changes §1's totals table (Phase 4 grows) — see the review note below.

⚠ **Review note — `GEN-01` alone is not enough.** Verified on this machine: the
clean-interpreter harness uses `cwd = REPO_ROOT` and `PYTHONPATH=src`, and `python -c` puts
`''` (the cwd) on `sys.path` — so `tests.fakes` *is* importable there, and the proposed
check is not vacuous. But it only observes `sys.modules` after importing the skeleton, so it
catches **eager** (module-level) imports only; a function-level `from tests.fakes import …`
slips past. Keep the `GEN-01` extension (cheap, catches the obvious case) **and** make the
static assertion in `GEN-19` the load-bearing guard.

⚠ **Review note — phase placement.** `GEN-22` is specified for Phase 4, but the double is
needed *before* the first Phase 1 processor test is written, and `GEN-05` (Phase 0, Wave
0.3) already owns the `markers` registration. Recommend moving `GEN-22` to **Phase 0** as
the convention/scaffolding task (create `tests/fakes/engines/`, state the naming and
injection rules), leaving only the verification to Phase 4.

⚠ **Review note — ID hygiene, and the totals table.** After the lab-tool removal the free
slots are `GEN-21`, `PDF-14`, `IMG-15`, `OCR-14`, `LLM-16`, `ORC-20`. The feedback proposes
`GEN-22`/`GEN-23`, which leaves `GEN-21` dangling and makes Phase 4 read
`GEN-11`…`GEN-20` *plus* `GEN-22`. Recommend reusing the freed slots instead:
`GEN-21` = doubles/tiers, `GEN-22` = real-tier safety net (Annex B §7). That makes Phase 4
`GEN-11`…`GEN-22`, contiguous.

While you are in that table: the totals row was **already arithmetically wrong** before any
of this (the phase rows summed to 95 against a stated 100; after the lab-tool removal, 94
against 99). It needs a recomputation, not another subtraction. With the edits above it
would be:

| Phase | Tasks | S / M / L |
|---|---|---|
| 0 — Foundations | 6 | 3 / 3 / 0 |
| 1 — Processors | 58 (+3 doubles) | 22 / 32 / 4 |
| 2 — Orchestrator | 19 | 3 / 13 / 3 |
| 3 — Integration | 4 | 0 / 3 / 1 |
| 4 — Hardening + close-out | 12 (+2) | 5 / 5 / 2 |
| **Total** | **99** | **33 / 56 / 10** |

## A.7 The three `wbs-procesador-{pdf,image,ocr}.md`

Each needs, mirroring its subplan:

- a new row in "Task issue index" plus its "Detailed issue" in the existing format, with
  acceptance criteria of the shape: *"Given the fake engine, when the invariant tests run,
  then zero calls reach the real engine; given `pytest -m engine`, then exactly one test per
  processor executes."*
- updated Summary (`# tasks`, effort distribution), dependency graph and waves, inserting
  the task in Wave 1/2 — after the `primitives/` skeleton and before the waves that
  currently pay the cost (Wave 3/4 in OCR, Wave 4 in PDF/IMG).

⚠ **Review note.** The per-processor ID ranges are cited in at least five places each
(WBS header, WBS §1 summary, `wbs-general.md` §1 Phase 1 child ranges, §4.2 "Issues", and
the subplan's WBS table). Grep the range string after editing; a half-updated range is how
the lab-tool removal went wrong twice.

## A.8 Not only prose — a fixture size ceiling

The fixtures the subplans name either **do not exist** (`release2` has no
`tests/fixtures/{pdf,image,ocr}/`) or are **too large** (on `release1`,
`ocr_prepared_text_and_table.png` is 347 KB — not "a minimal image with a heading, a
paragraph and a 2×2 table" as `OCR-12` says). Each subplan should fix an explicit ceiling
for its fixtures, e.g. *"< 20 KB; any larger file is corpus, not a fixture, and does not
belong in `fixtures/`"*.

⚠ **Review note.** A single 20 KB ceiling is risky for PDF: a fixture with an embedded
image easily exceeds it. Phrase it per processor, and add the structural rule that makes
the ceiling achievable — *"PDF fixtures carry no embedded raster images except the one
fixture whose purpose is embedded-image extraction"*.

---

# Annex B — The real-tier safety net (closing the drift risk)

§11 of this report names the risk — *"the double can drift from the engine's real behaviour
as Docling changes its output structure between versions"* — and explicitly leaves it open:
*"the conformance test is reduced, never removed"*. This annex supplies the mechanism.

## B.0 The principle

> **The double reduces the cost of iteration, not the scope of verification.** The full
> run — with the real engine — remains the only thing that proves the system actually
> works, so it must sit at a **non-optional** point of the flow, not "whenever someone
> remembers".

Option A (§7) covers part of this: `pytest` unfiltered still means everything. That alone
is not enough. Four more mechanisms follow.

## B.1 The double must live as low in the stack as possible

This is a **design** constraint, not a testing one. If `FakeDoclingEngine` replaces only
`convert_image_with_docling` (the raw engine call) while everything else stays real code
(`extract_docling_text`, `normalize_bbox`, the `document.json` builder,
`validate_ocr_result`, the atomic publish), then:

- ~90 % of the processor's code executes **identically** in both tiers;
- the real engine can only fail at one narrow point: the conversion itself;
- a regression in *our* logic is caught in the fast tier exactly as in the real one.

`OCR-04` already separates `convert_image_with_docling` from `extract_docling_*`, so this is
implicit in the design; make it an explicit rule: **the injection point is the SDK/CLI call,
never higher.** Mocking `process_ocr_image` wholesale forfeits all the real coverage.

## B.2 A structural conformance test, parametrized over both engines

Not "the fake returns something similar" — a test that runs **the same assertion battery
over both implementations**. Sketch, as received:

```python
@pytest.mark.parametrize("engine", [fake_docling_engine, real_docling_engine])
def test_engine_conformance(engine):
    doc = engine.convert(FIXTURE_PATH)
    assert isinstance(doc, OCRDocument)
    assert hasattr(doc, "blocks") and isinstance(doc.blocks, list)
    assert all(hasattr(b, "bbox") for b in doc.blocks)
    # ... the exact shape the rest of the module assumes
```

The real one runs under the `engine` marker (once); the fake runs always. When Docling
changes its output schema, this test breaks — not the whole invariant suite — and it breaks
**in the right place**: the translation layer into `OCRDocument`, which `OCR-04` already
identifies as the only code that knows Docling's native structures.

⚠ **Review note — the marker must be on the parameter, not on the test.** Verified in
`/tmp` with `pytest.param(..., marks=pytest.mark.engine)`:

```
pytest -m 'not engine'  → test_conformance[fake] PASSED   (1 passed, 1 deselected)
pytest -m engine        → test_conformance[real] PASSED   (1 passed, 1 deselected)
```

The naive form — `@pytest.mark.engine` on the test function with a plain
`@pytest.mark.parametrize` — deselects **both** parameters in the fast tier
(`2 deselected / 0 selected`), silently deleting the fake half of the contract. The mark
goes on the `pytest.param` for the real engine.

⚠ **Review note — the sketch implies an interface the plan does not define.** There is no
`engine.convert()` object: `primitives/` is a module of functions, and the plan forbids a
`Protocol`/flag. The harness must therefore be "patch the engine accessor, then call the
same primitive in both cases" (`convert_image_with_docling`), or the real tier would need a
wrapper class that nothing else uses.

⚠ **Review note — `isinstance`/`hasattr` assertions are weak.** They cannot fail for the
fake (it constructs our own type), and for the real engine they only prove the translation
produced the right type. The load-bearing assertions are **content** properties — ≥ 1 block,
each `bbox` normalised to 0–1, the 2×2 table with its expected cell text — which is also
what B.6 demands.

## B.3 The merge gate runs everything, always

The practical application of Option A: `pytest -m "not engine"` is for the local loop; the
pipeline that decides whether something merges runs `pytest` unfiltered. Nothing is closed
as "done" without having passed through the real engine at least once per PR. Policy text
to add to **`README.md` §7**:

> The CI pipeline that acts as the merge gate runs `pytest` with no `-m`. The
> `-m 'not engine'` command exists exclusively for the local development loop and never
> replaces the gate.

⚠ **Review note — there is no CI to enforce this.** Verified: `.github/` holds only
`agents/` and `copilot-instructions.md`; there is no workflow, no hook, no script. So B.3,
B.4's bump trigger and B.5's nightly job are all **aspirational** until a workflow exists.
Either the deliverable includes creating it (e.g. `.github/workflows/gates.yml`, with the
trigger and the commands named), or the plan must say plainly that the PoC has no CI and
this is a human checklist item. Note the interaction with §7: with no CI, *the only*
mechanical thing that runs the real tier is the default of `pytest` — which is exactly why
Option A was the right call here.

## B.4 Pinned engine version + a mandatory trigger on dependency bumps

If `docling` / `opencv` / `poppler` move, the double does not notice. Therefore:

- exact pin in `pyproject.toml` (already `GEN-05`'s job);
- any PR touching that pin **must** run the full `engine` tier as a merge requirement
  (B.3 already implies it, but the bump PR's own checklist should say so — that is the
  moment of highest drift risk);
- the `engine_version` that `OCR-10` / `IMG-11` / `PDF-10` already record in
  `metadata.json` is *after-the-fact* traceability, not prevention. Prevention is the
  previous bullet.

## B.5 A scheduled run, independent of code changes

This covers what no PR triggers: **the environment changing while the code does not**
(someone reinstalls dependencies, a CI base image moves, Docling ships a silent patch). A
scheduled job running `pytest -m engine` against `main`/`release*` weekly catches that drift
before a user does. It is not part of the PR gate; it is a separate safety net.

## B.6 The real tier must assert concrete values, not "it did not explode"

Already flagged for `image`, but it holds for all three: if the only contact point with the
real engine checks that the pipeline raised nothing, a silent behaviour change (Docling
ordering differently now, Poppler rendering one pixel off) passes unnoticed. The rule:

> The real-engine happy path asserts **concrete values or structures known from the
> fixture** — block count, the exact expected text, image dimensions, a table with specific
> cells — never the status alone.

## B.7 `GEN-22` — "Real-tier safety net"

*(Renumbered from the received `GEN-23`; see A.6's ID note.)*

- **Phase:** 4 · **Type:** tooling · **Effort:** S
- **Depends on:** `GEN-21` (the doubles/tiers task)
- **Deliverables:** the parametrized fake/real conformance test per processor; the gate
  policy documented in `README.md` §7 (B.3); the weekly scheduled job (outside pytest, at
  CI-config level); the dependency-bump checklist that names the `engine` tier.
- **Acceptance:** *"Given a change in the schema the fake returns, when the conformance
  test runs against the real engine, then it detects the divergence before it reaches
  production."*

⚠ **Review note — the dependency runs the wrong way.** `GEN-22` depends on `GEN-21`, and
`GEN-21` is proposed for Phase 4 while the per-processor doubles must land in Phase 1. That
is another argument for the Phase 0 placement in A.6: the convention has to exist before the
first processor test consumes it, otherwise three processors invent three local variants of
`tests/fakes/engines/`.

## B.8 Open items this annex raises

| # | Item | Recommendation |
|---|---|---|
| 1 | Marker placement in the conformance test | Per-parameter (`pytest.param(..., marks=…)`), verified — not on the test function |
| 2 | Conformance harness shape | Patch the engine accessor, call the same module-level primitive; no object interface, no `Protocol` |
| 3 | `GEN-01` import check | Keep, but the static assertion in `GEN-19` is the load-bearing one (runtime check sees eager imports only) |
| 4 | `GEN-21`/`GEN-22` phase | Phase 0 for the convention + `tests/fakes/engines/` scaffolding; Phase 4 verifies |
| 5 | ID allocation | Reuse the freed slots (`GEN-21`, `GEN-22`, `PDF-14`, `IMG-15`, `OCR-14`) to keep ranges contiguous |
| 6 | §1 totals table | Recompute (the row was already wrong); the numbers in A.6 are the recomputation |
| 7 | CI | Decide: create `.github/workflows/gates.yml`, or state in the plan that the PoC has no CI and the gate is manual |
| 8 | Fixture ceiling | Per-processor numeric ceiling, not one global 20 KB |
| 9 | `OCR-14` block list | `OCR-05`…`OCR-12`, not `OCR-06…OCR-09` + `OCR-12` |
| 10 | `PDF-14` fake surface | Include `PDF-03`'s primitives; keep `PDF-08` composition real |
