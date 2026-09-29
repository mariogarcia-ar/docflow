# Subplan — page scope in the PDF bench (`--page` omitted = every page)

> Status: **proposed — decided, not yet applied.** This subplan is the authority for the
> **page scope** of the five page-addressed commands of the PDF bench
> (`render`, `text`, `blocks`, `images`, `classify`). On that question only it **supersedes**
> `subplan-scripts.md`: §3.3 (a missing `--page` is a usage error), §3.4 (the `Notes` of the
> five `pdf.py` rows), §5 (the refusal scenarios), §6 (the refusal cases of the glue tests and
> the invariant list) and §9 (which gains the decision this file records). It also supersedes
> the 2026-09-28 "pre-walk flag validation" decision for those five commands and nothing else:
> `--dpi` on `render` and `run` is still required and still refused before the header.
>
> Until `PAG-06` performs that edit, this file is the winning decision and `subplan-scripts.md`
> is stale on exactly those clauses — the same discipline
> `docs/feedback/batch-mode-across-processors.md` used for its reversal. This file is
> **unregistered** in `docs/plan/README.md`'s subplans table and §4.1 until `PAG-06` adds it,
> and it introduces **no new phase**: it is a revision of Phase 5's bench, not a phase of the
> library.
>
> Task IDs use a **new, contiguous range `PAG-01`…`PAG-07`** — one prefix per subplan, as
> `PDF-*`, `IMG-*`, `OCR-*`, `LLM-*`, `ORC-*` and `SCR-*` already are. `SCR-01`…`SCR-18` are
> never renumbered and never re-scoped by this file.

## 1. Objective

Make the **page axis of the PDF bench optional**: a page-addressed command that is given no
`--page` processes **every page of the document**, in page order — which for a one-page
document is that page, with no special case.

```bash
python scripts/tools/pdf.py --json classify tests/fixtures/pdf/pdf_sample_text.pdf   # 3 pages, 3 verdicts
python scripts/tools/pdf.py --json classify tests/fixtures/pdf/pdf_sample_mixed.pdf  # 1 page, 1 verdict
```

The deliverable is a **change to the bench's command layer**, `scripts/tools/_pdf.py`, plus the
tests and the plan text that describe it. It is deliberately the smallest change that satisfies
the rule:

| Property | Why it is required |
|---|---|
| **One module changes** | `_pdf.py` owns the flags (`build_subcommands`), the refusal (`validate_flags`) and the five methods. `pdf.py` and `batch_pdf.py` dispatch through it, so neither tool is edited. |
| **`_cli.py` and `_batch.py` do not change** | The frame already prints every payload key (`print_result`), already files the payload (`run_one`), and already reads `status`/`errors` (`_failed`, `_payload_failures`). The resolved scope therefore travels as a **payload key**, not as a new frame hook. |
| **The five `--page` names keep working** | `--page 1` must behave exactly as it does today: same engine calls, same payload keys, same artifacts. This is an **additive** change to the single-page form. |
| **No new flag** | The rule is "absent means every page"; there is no `--all-pages` and no `--page all`. |

**Why this is a subplan and not a note.** The change is small in code and wide in consequences:
it reverses a decision frozen two days earlier, it adds a second payload shape to five
commands, it makes two of them write per-page directories, and it retires five of the seven
cases that pin the current refusal. Those are the properties a plan exists to fix before the
code moves.

## 2. Context (BA)

**Who asks for it.** The developer at the bench who wants the document's answer, not one
page's: "which pages of this PDF are scanned?", "does this document's text layer hold on page 4
too?" Today that person either types the page numbers one at a time, reading the count off
`inspect` first, or drives the whole contract with `run` — which needs a `--dpi` and publishes
an artifact tree for every page. The gap is a **report** over every page with no artifact tree.

**The rule, stated once.**

- A page-addressed command with `--page N` reads **page N**, exactly as today.
- A page-addressed command with no `--page` reads **pages `1..page_count`**, in order. A
  one-page document therefore reads page 1 — the rule needs no branch for it.
- The resolved scope is **stated in the payload** and is therefore never silent: a caller who
  omitted the flag can see what the run resolved to without reading the header.
- `inspect_pdf` is the only source of `page_count`. A document that cannot be inspected fails
  **before** any page is read, with the same typed record it produces today.

**What the change must not become.**

- **Not a second implementation of `process_pdf`.** The library's document run stays the
  implementation of "the whole document": it owns the page loop, the aggregation and the
  publication. The bench loops its own primitives; it aggregates nothing and publishes only
  what the page-addressed command already published.
- **Not a new default in the prohibited sense.** The project forbids substituting a *value* for
  an answer the caller did not give — an engine, a provider, a model, a DPI, a threshold. "Every
  page" substitutes no value: it is the *scope of the question*, and it is stated back.
- **Not a change to the other processors.** `image.py` and `ocr.py` take `--page` with
  `default=1` because their input **is one image**; a page there is a logical label, not an
  axis. This subplan does not touch them (§9, decision 5).

## 3. Design (SA)

### 3.1 The whole change lives in `_pdf.py`

| Symbol | Today | After |
|---|---|---|
| `PAGE_COMMANDS` | the five whose `--page` is required, used by `validate_flags` | the five that are **page-scoped**: `--page` selects one, its absence selects all. Repurposed, not deleted |
| `PAGE_FLAG_COMMANDS` | `(*PAGE_COMMANDS, "run")` — the flag registrations | unchanged |
| `DPI_COMMANDS` | `("render", "run")` | unchanged |
| `build_subcommands` | registers `--page` on `PAGE_FLAG_COMMANDS` | unchanged |
| `page()` | `required(...)` — refuses a missing `--page` | unchanged: it is still how a **stated** page is read |
| `validate_flags` | refuses a missing `--page` on `PAGE_COMMANDS`, then `--dpi` | refuses only `--dpi` (on `render`/`run`). The `--page` branch is deleted |
| `_render`, `_text`, `_blocks`, `_images`, `_classify` | one page each | each resolves its scope, then runs its own per-page work once per page |

`validate_flags` keeps its reason to exist — `render` and `run` still cannot run without a
`--dpi`, and an empty folder must still refuse **once, before the walk** rather than per input.
What it loses is the `--page` refusal, because a command that can run without the flag is not a
command that "could never have run".

### 3.2 The scope resolver

One new private helper in `_pdf.py`, used by all five methods:

```python
def page_scope(
    args: argparse.Namespace, parser: argparse.ArgumentParser, input_path: Path
) -> tuple[list[int], str]:
    """Return the pages this run covers and the scope to state, inspecting only when needed."""
```

- `--page N` stated → `([N], "page N")`, and **no inspection** — the single-page path keeps
  today's engine-call count exactly.
- No `--page` → one `inspect_pdf(input_path)` for `page_count`, then
  `(list(range(1, page_count + 1)), "all pages (N)")`.

The helper raises the primitive's typed failure unchanged, so a corrupt document fails at the
same point, with the same record and the same exit code as today.

`for_page` (the PDF processor's own helper) stamps a page number onto a primitive failure. The
bench uses it to make a per-page failure page-scoped — it is a call to the processor's own
public primitive surface, not a reimplementation.

### 3.3 What "every page" means per command

| Command | Per-page work | Published per page |
|---|---|---|
| `render` | `render_page_to_image(input, n, root / f"page_{n:03d}_{dpi}dpi.png", dpi)` | the PNG — its name already carries the page, so nothing collides |
| `text` | `extract_text_from_page(input, n, True)` | nothing |
| `blocks` | the same read, block view | nothing |
| `images` | `extract_images_from_page(input, n, root / f"page_{n:03d}" / "images")` | the embedded images, **under the page's own directory** |
| `classify` | the four-primitive composition the method already performs, per page | the embedded images, under the page's own directory |

**The directory change is the one real design cost.** `extract_images_from_page` mints
`image_001.png`, `image_002.png`, … from a **per-call** index, so two pages writing into one
`images/` directory would have page 2 overwrite page 1. The all-pages form therefore writes
`page_NNN/images/`, mirroring the layout `process_pdf` already uses.

**The single-page form keeps `images/`.** The sub-directory exists only to keep N pages from
colliding; one page has nothing to collide with, and changing its layout would be a second
break for no benefit (the alternative is recorded in §9, decision 3).

### 3.4 The payload: one shape per scope

The payload key mirrors the scope the caller asked for, and the single-page keys are unchanged.

`text --page 2` (today `{input, page, text}`):

```json
{ "input": "…", "scope": "page 2", "page": 2, "text": "…" }
```

`text` with no `--page`, over a three-page document:

```json
{
  "input": "…",
  "scope": "all pages (3)",
  "pages": [{"page": 1, "text": "…"}, {"page": 2, "text": "…"}, {"page": 3, "text": "…"}],
  "status": "success",
  "errors": []
}
```

- `scope` is **added to both forms** — that is the only change to the single-page payload. A
  reader sees it in the human summary, in `--json`, and in the batch's `<command>.json`.
- The all-pages form carries `pages`, `status` and `errors`; `images` and `classify` also carry
  `artifacts`, the files the run published (mirroring `_run`'s document payload).
- A reader discriminates the two on `pages` vs `page`. The **uniform alternative** — always
  `pages`, even for one page — is recorded and rejected in §9, decision 2.
- **No new contract.** These are payload dict keys built from what the primitives returned; the
  library's types, the processor's contract and the batch frame's record shape are untouched.

### 3.5 Failures, status and exit codes

A page that fails **does not end the run**: its typed record is appended to `errors` with its
page number, and the other pages still produce their result.

| `status` | Meaning | Exit (single file) |
|---|---|---|
| `success` | every page produced a result | `0` |
| `partial` | at least one page produced a result, and at least one failed | `0` — a partial result is a result |
| `failed` | no page produced a result | `1` |

- The vocabulary is the processor's own (`_page_status` / `_document_status` use the same
  three), so the bench invents no enum and adds no contract.
- A failure that happens **before** the loop — an uninspectable document — still **raises** out
  of the method, so the tool prints the typed record and exits `1` exactly as today.
- The frame needs no change: `_batch.run_one` derives the per-input line and the exit code from
  the payload's own `status` and from `_payload_failures`, which reads the `error` and `errors`
  keys that `_failed` decides on. A batch run over a document with one bad page therefore prints
  `FAILED`, prints the records and exits `1`. That is the frame's existing rule — "a
  payload-recorded error is a failure" — and this subplan does not change it, including the
  pre-existing divergence between the single-file exit code (derived from `status`, so
  `partial` → `0`) and the batch's (any recorded error → `1`), which already applies to `run`
  today (§9, decision 6).

### 3.6 What is deliberately not changing

- **`run`.** Without `--page` it is the contract's document run (`process_pdf`): every page,
  the aggregation, the whole artifact tree, `--dpi` required. `run --page N` stays the
  page-level contract. The bench now has two ways to say "every page" and they are not equal —
  `run` is the library's, the page commands are the bench's, and §3.3 of the subplan that
  fixes the tool→symbol map is unchanged on that point.
- **`split`.** It is already whole-document and takes no `--page`.
- **`image.py` / `ocr.py`.** Their `--page` keeps `default=1`.
- **`inspect`.** It already reports every page's geometry and still takes no `--page`.
- **The three boundaries.** No engine binary, module or SDK is named (guard 3); no `src/` module
  learns about `scripts/` (guard 2); no contract, options type or workflow decision is added.
  The one lab-bench exception, `_pdf.py` driving its own `primitives/`, is unchanged and is
  still what makes this change possible without a `PDFOptions.dpi`.

### 3.7 The constraint that shapes the design

`PDFOptions.dpi` is a required field with no default, so **every** `process_pdf` call must state
a dpi, even with `render=False`. "Every page, no dpi, no artifact tree" therefore has **no route
through the contract**: the alternative to looping the primitives is inventing a dpi (forbidden)
or calling `run` (which is a different question). This is why the change is a bench-local loop,
and why it is registered here as a deliberate, bounded duplication — of the *composition the
five methods already perform for one page*, not of `process_pdf`.

## 4. Execution plan (PM)

### 4.1 WBS

| ID | Task | Effort | Depends on |
|---|---|---|---|
| PAG-01 | `_pdf.py`: the scope resolver, the optional `--page`, and the per-page artifact directories | M | — |
| PAG-02 | `_pdf.py`: the all-pages payload, per-page failure collection and `status` | M | PAG-01 |
| PAG-03 | `tests/test_lab_tools.py`: retire the five refusal cases, add the scope, collision, partial and corrupt cases | M | PAG-02 |
| PAG-04 | Hand run of the five commands over the multi-page fixtures, with the evidence recorded | S | PAG-03 |
| PAG-05 | `scripts/tools/readme.md` and `scripts/tools/quickstart.md`: the rule, the flag columns and the examples | S | PAG-03 |
| PAG-06 | Reconcile the frozen plan: `subplan-scripts.md`, `docs/plan/README.md`, root `README.md` | S | PAG-04 |
| PAG-07 | The four QA gates and the two mutation records | S | PAG-05, PAG-06 |

### 4.2 Order / waves

- **Wave 1 — The rule:** `PAG-01` → `PAG-02`. One file, two passes: the scope first (the flag
  becomes optional, the directories stop colliding), then the payload that reports it.
- **Wave 2 — Prove it:** `PAG-03`, then `PAG-04` ∥ `PAG-05`. The suite and the hand run answer
  different questions: the suite proves the shape with the double, the hand run shows what the
  real engine says about a real multi-page document.
- **Wave 3 — Close:** `PAG-06` → `PAG-07`.

**Critical path:** `PAG-01 → PAG-02 → PAG-03 → PAG-04 → PAG-06 → PAG-07`.

**Entry condition:** Phase 5 is closed (`SCR-10` is the only `NOT_STARTED` row, and it owns
citations this subplan does not touch — `PAG-06` reconciles them in the same pass if they
overlap). `_pdf.py` is the module `SCR-11` produced, and the 2026-09-28 `validate_flags` hook is
in place in both tools.

## 5. Acceptance criteria

```gherkin
Scenario: A page command with no --page covers every page
  Given "tests/fixtures/pdf/pdf_sample_text.pdf", which has three pages
  When "scripts/tools/pdf.py --json classify <input>" runs with no "--page"
  Then the payload's "scope" is "all pages (3)"
  And the payload's "pages" holds three entries, for pages 1, 2 and 3, in order
  And every entry carries its own classification

Scenario: A one-page document needs no special case
  Given "tests/fixtures/pdf/pdf_sample_mixed.pdf", which has one page
  When "scripts/tools/pdf.py --json classify <input>" runs with no "--page"
  Then the payload's "scope" is "all pages (1)"
  And the payload's "pages" holds exactly the page that "--page 1" would have read

Scenario: A stated --page behaves exactly as before
  Given any page-addressed command with "--page 2"
  When it runs
  Then "page" is "2" and no "pages" key exists
  And the payload it prints is today's payload plus the "scope" key
  And no document inspection happens that did not happen today

Scenario: Two pages do not overwrite each other's artifacts
  Given a two-page document whose pages each carry an embedded image
  When "scripts/tools/pdf.py images <input>" runs with no "--page"
  Then each page's images are written under that page's own directory
  And no file is written into a shared "images/" directory

Scenario: One bad page does not end the document
  Given a document whose second page fails while the others succeed
  When a page-addressed command runs with no "--page"
  Then "status" is "partial" and "errors" holds the second page's typed record
  And the pages that succeeded still appear in the payload in page order
  And the exit code is "0", because a partial result is a result

Scenario: A document that cannot be inspected fails as it does today
  Given "tests/fixtures/pdf/pdf_corrupt.pdf"
  When a page-addressed command runs with no "--page"
  Then the typed record is printed and the exit code is "1"
  And no payload is printed and no per-page record is filed

Scenario: The refusal that remains is the one that is still real
  Given "scripts/tools/pdf.py render <input>" with no "--dpi"
  When it runs
  Then it exits with a usage error and no header is printed
  And "classify" with no "--page" is no longer a usage error
```

## 6. Test plan

**One tier, no engine.** Unchanged: the tools are still never executed against an engine in
`pytest`; the scope is proved with `tests/fakes/engines/fake_poppler.py`, whose recorded
`calls` are the assertion where a written file would be weaker.

**Cases retired (`SCR-08`'s, now stale).**

| Test | Case(s) retired | Why |
|---|---|---|
| `test_a_batch_refuses_a_missing_required_flag_before_it_walks` | `("classify", (), "--page")`, `("text", (), "--page")`, `("blocks", (), "--page")`, `("images", (), "--page")` | Four of five cases assert a refusal the rule removes. `("render", ("--page","1"), "--dpi")` stays |
| `test_pdf_refuses_a_missing_required_flag_before_its_header` | `("classify", (), "--page")` | Same. `("render", ("--page","1"), "--dpi")` stays |

These two tests are the evidence for the 2026-09-28 pre-walk validation; the subplan that
records that decision is superseded **on this clause only**, and `PAG-06` updates it.

**Cases added.**

1. **Scope is stated** — a one-page and a three-page document, `--json`, asserting the `scope`
   string and the number of entries in `pages`.
2. **The single-page form is additive** — `--page 1` on the same fixture, asserting `page`,
   the absence of `pages`, and that the rest of the payload is what it was.
3. **No inspection on the single-page path** — the double's call log shows no `pdfinfo` for a
   stated `--page`; this is what keeps "same engine calls as today" true rather than asserted.
4. **Two pages, two directories** — a two-page document; `images` with no `--page`; the double's
   `pdfimages` calls name `page_001/images` and `page_002/images`, in that order.
5. **One bad page, one partial run** — the double fails page 2; `status` is `partial`, `errors`
   is non-empty and page-scoped, and the batch prints `FAILED` while filing the payload.
6. **Corrupt input unchanged** — `pdf_corrupt.pdf` through the double's failure knob, and the
   refusal cases of `test_a_batch_refuses_a_missing_required_flag_before_it_walks` keep
   `render`/`--dpi` green so the hook is still exercised.

**Invariants and their mutations** (each leaves the four-field record in the root `README.md`,
where `GEN-16` audits the set):

| # | Invariant | Mutation that must go red |
|---|---|---|
| 9 | An omitted `--page` resolves to every page | Make `page_scope` return `[1]` for the absent case — cases 1 and 5 must fail |
| 10 | Two pages never share an artifact directory | Point `_images` and `_classify` back at `root / "images"` — case 4 must fail |

**Fixtures.** No new fixture is required for the gate: the partial-run and collision cases are
driven by `fake_poppler`, which is where the suite is allowed to be synthetic. The **hand run**
(`PAG-04`) uses real multi-page inputs that already exist — `tests/fixtures/pdf/pdf_large/MetodoCITRA17-APL.pdf`
(scale) and `tests/fixtures/pdf_aptos_layout/*.pdf` — because a page loop that only ever saw
three pages of one synthetic document is not evidence about a corpus.

## 7. Definition of Ready / Definition of Done

**Definition of Ready**

- Phase 5 is closed and `_pdf.py` is the module `SCR-11` produced; `validate_flags` is wired into
  both tools.
- `fake_poppler`'s `calls` log and its per-binary knobs are read, not assumed, so the collision
  and partial cases are written against what the double actually records.
- The two `SCR-08` tests named in §6 are opened and their exact parametrization is known, so
  "retired" means a named case and not a guess.
- The supersession list of this file's header is read before any edit to `subplan-scripts.md`.

**Definition of Done**

- `PAGE_COMMANDS` is repurposed, `validate_flags` refuses only `--dpi`, and no method of `_pdf.py`
  refuses a missing `--page`.
- Every one of the five commands, with no `--page`, reports `scope`, `pages`, `status` and
  `errors`, and writes a one-page document's artifacts exactly where it wrote them before.
- `images` and `classify` never write two pages' images into one directory.
- `pdf.py` and `batch_pdf.py` contain **no new line** for this feature: the change is `_pdf.py`'s.
- `_cli.py` and `_batch.py` are unchanged, and the frame files and exits the all-pages payload
  correctly without knowing what "pages" means.
- The five retired cases are replaced by the six listed in §6, and both invariants are
  mutation-falsified with their records in the root `README.md`.
- `scripts/tools/readme.md` and `quickstart.md` state the rule, the `Needs` columns and the
  examples; the corpus-wide `classify` example in the quickstart is the one that shows three
  pages.
- The supersession is applied: `subplan-scripts.md` §3.3/§3.4/§5/§6/§9, `docs/plan/README.md`'s
  subplans table (this file's row, Phase 5 revision) and §4.1, and the root `README.md` tool
  table agree with the tree.
- The four QA gates pass — `pytest`, `ruff check .`, `ruff format --check .`,
  `pylint src tests` — with the recorded asymmetry that `scripts/` is covered by the two Ruff
  gates only.

## 8. Risks & mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| The all-pages loop drifts into a second `process_pdf` | Two behaviours to keep in step; the bench passes where the library fails | The loop calls the same primitives the single-page method already calls, aggregates nothing, and publishes nothing new; `run` stays the only document-level path (§3.6) |
| An omitted flag silently makes an expensive run | 300 PNGs from a render nobody scoped | The scope is in the payload and in the header-adjacent summary; the hand run records the cost on the scale fixture (`PAG-04`) |
| Two payload shapes for one command confuse a reader | A consumer reads `page` where the run produced `pages` | `scope` is always present and names the resolved scope; the human summary prints it; `readme.md` documents the discrimination rule |
| A partial run is mistaken for a clean one | A page's failure is lost in a 300-entry list | `errors` is top-level and page-scoped; the batch already prints records for a payload-recorded error; the exit code follows `status` |
| The retired refusal cases are deleted without replacement | The usage-error path loses its only coverage | §6 keeps the `render`/`--dpi` cases in both tests, so the hook stays falsifiable |
| Two subplans describe one module | Drift between `subplan-scripts.md` and this file | The supersession list is in the header, `PAG-06` performs the edit, and the DoD forbids closing without it |

## 9. Out of scope & resolved decisions

1. **Omitted `--page` means every page — RESOLVED.** A one-page document needs no branch: the
   range is `1..page_count`.
2. **The payload key mirrors the scope — RESOLVED.** One page keeps `page`; every page uses
   `pages`. *Rejected:* the uniform shape (always `pages`), because it breaks every existing
   single-page read and record for no gain the `scope` key does not already give. *Rejected:*
   keeping the single-page payload free of `scope`, because then an omitted flag is silent.
3. **Per-page artifact directories only in the all-pages form — RESOLVED.** `images`/`classify`
   write `page_NNN/images/` when looping and keep `images/` for a stated page; the sub-directory
   exists only to stop a collision. *Rejected:* always `page_NNN/images/`, which would break the
   recorded single-page layout for no benefit.
4. **Failure collection, not fail-fast — RESOLVED.** `success` / `partial` / `failed`, using the
   processor's own vocabulary; a pre-loop failure still raises. A `partial` run exits `0` from
   the single-file tool and is counted `FAILED` by the batch frame, exactly as `run` already is.
5. **`image.py` and `ocr.py` are untouched — RESOLVED.** Their input is one image and their
   `--page` is a logical label with `default=1`. The cross-processor difference is accepted and
   documented rather than removed.
6. **The exit-code divergence is recorded, not fixed — RESOLVED.** Making the single-file exit
   code consider a payload's recorded errors is a change to `run`'s behaviour too; it is a
   separate decision with its own evidence.
7. **No new flag — RESOLVED.** There is no `--all-pages` and no `--page all`; a second way to
   say the same thing is a second thing to keep in step.
8. **`run`'s semantics are unchanged — RESOLVED.** `run` with no `--page` is still the contract's
   document run; the two "all pages" paths are stated side by side in §3.6.
9. **Gate scope is unchanged — RESOLVED.** `scripts/` stays covered by the two Ruff gates;
   `pylint src tests` does not reach it (`subplan-scripts.md` §9, decision 10).

**Stale documents this subplan creates or leaves (owner in parentheses)**

| Document | What is stale | Owner |
|---|---|---|
| `subplan-scripts.md` §3.3, §3.4, §5, §6, §9 | the five page commands' required flag, the five `Notes` cells, the refusal scenarios, the refused-flag cases, and the decision list | `PAG-06` |
| `docs/plan/README.md` subplans table and §4.1 | this subplan is unregistered and the module/subcommand text still implies a required `--page` | `PAG-06` |
| root `README.md` | the Lab tools table's `Needs` column and the invariant table (two new records) | `PAG-06`, `PAG-07` |
| `scripts/tools/readme.md`, `scripts/tools/quickstart.md` | the five `Needs` cells, the "missing required flag is refused once" bullet, and every page example | `PAG-05` |
| `docs/plan/issues/wbs-scripts.md` | cites `SCR-08`'s refusal cases as the evidence for the pre-walk hook; four of them no longer exist | `PAG-06` |
| `docs/plan/issues/wbs-general.md` §1 | the Phase 5 totals name no `PAG-*` range | `PAG-06` |
| `docs/plan/bitacora.md` | has no entry for this change until the hand run writes one | `PAG-04` |
