# `scripts/poc/` — direct-to-adapter probes

One Python driver per kernel, one method per requirement in `my_kernel_flow.md`,
plus an aggregator. **They call the adapters directly**, by Python, without going
through `docflow-kernel`.

## Why this exists, next to `scripts/kernel/*.sh`

The shell drivers drive the **CLI**. These call the **adapter**. When a command
misbehaves, the CLI cannot say whether the defect is in the adapter or in the
surface above it — swallowed flags, delivery names, exit-code translation all live
there. A probe that reaches the adapter isolates the layer.

The two are complementary, not redundant: `scripts/kernel/pdf.sh` proves
`docflow-kernel pdf split` works; `scripts/poc/pdf.py` proves `PdfEngine.split`
works.

## Running

```bash
python scripts/poc/run_all.py              # every driver
python scripts/poc/run_all.py --fast       # skip ocr and llm_local
python scripts/poc/run_all.py --only pdf   # one driver
python scripts/poc/pdf.py --out /tmp/x     # one driver, custom output root
```

`--fast` skips `ocr` (reloads ONNX models on every call, ~10 s each, no warm path
across processes) and `llm_local` (real generations). A full run is a couple of
minutes; `--fast` is about ten seconds.

Generated files land in `var/poc/`, which `.gitignore` already covers.

## The reporting contract

Four buckets, mirroring `scripts/kernel/_lib.sh`:

| Bucket | Means | CLI exit it corresponds to |
|---|---|---|
| `ok` | A value was produced | `0` |
| `reason` | The document's answer — `illegible`, `blank_page`, `truncated_output` | `2` |
| `precondition` | The call could not legitimately be made — `engine_unavailable`, `model_not_pulled`, `provider_unavailable` | `3` |
| `usage` | The request was malformed — a page outside the document | `4` |
| `defect` | An exception came out of the adapter | `1` |

**Exit codes are reported, not judged.** A reason is an *answer*. Only `defect`
means something is broken.

Each probe declares the bucket it expects (`expect=`), so `run_all.py` can tell
`PASS` from `DIVERGENT`. Without that, a driver is an expensive `print`.

## Two constraints the drivers respect, both deliberate

- **The envelope is never serialised.** `Evidence` carries `MappingProxyType`, which
  `json.dumps` refuses, and encoding is `S1-T20`'s job. A probe that grew its own
  encoder would be a second source of truth. The reporter *describes* a value.
- **No threshold is ever hardcoded.** Corpus policy is read from
  `registry/policies/thresholds.json` via `_lib.policy()`. `ADR-009` gives policy no
  override, so a constant here would make the probes disagree with every other
  caller while reporting success.

## The drivers

| Driver | Covers | Notes |
|---|---|---|
| `pdf.py` | `my_kernel_flow.md` §1 | cut, classify, `layout_text`, render, plus the routing that spans two operations |
| `image.py` | §2 | resize by DPI, crop, legibility; **reports that "resize by size" has no operation** |
| `ocr.py` | §3 | `read` vs `layout`, side by side — the second is what "preserve the layout" means |
| `llm_local.py` | §4 | `structured` (text) and `vision` (pixels), plus truncation and the payload types |
| `llm_frontier.py` | §5 | `vision` and `judge`; reports the gate chain when there is no credential |
| `batch.py` | §6 | folder in, **mirrored tree out**; reuses the drivers' methods rather than re-implementing them |
| `batch_pdf.py` | §1 | **PDF-only** batch: per page, `.txt` for text and `.png` for scans, plus a page census |
| `batch_image.py` | §2 | **image-only** batch: size, `legibility`, the rescale to the floor, and any `--region` crop |
| `batch_ocr.py` | §3 | **OCR-only** batch: per-page status census plus the ordered text, with the engine's stdout captured |
| `batch_llm_local.py` | §4 | **fields from text**: one generation per document, with the prompt window reported |
| `batch_llm_frontier.py` | §5 | **contrast**: pairs `llm.local`'s fields with the document and asks a different model |
| `hitl.py` | §7 | finds the extractions, pairs them by relative path, contrasts them, writes `review.json` |

`_lib.py` is the reporting contract and `_mirror.py` is the folder-in/mirrored-tree-out
plumbing the three batch drivers share (the walk, the skip records, `verify_mirror` for
a whole tree and `verify_mirror_for` for a scope-limited one). Neither is a driver, and
neither is probed by `run_all.py`.

`run_all.py` aggregates the five **probe** drivers. `batch.py`, `batch_pdf.py`,
`batch_image.py`, `batch_ocr.py` and `hitl.py` are run explicitly, because they take
a folder rather than probing fixtures.

### `llm_frontier.py` asks for the same fields three ways

`FIELDS.json` is a **probe contract, not the pipeline's schema.** It is the file
`batch_llm_local.py` takes as `--schema`, so the K6 probes answer about a *caller's*
fields rather than about a fixture the driver carries — and a caller's schema is
deliberately small and therefore comparable across the three input shapes. The pipeline's
own schema is now `registry/schemas/extraction/invoice.json` (23 fields); the two share no
property names, on purpose, and neither stands in for the other.

Its `total: {"type": "integer"}` is the very declaration measured wrong on the pipeline
path (see *the extraction prompt and schema are registry artifacts* below). It is left as
it stands because the probes are showing what a caller *gets handed*, and a probe that
quietly substituted a better schema would hide that. All three are handed **one** document,
read twice by K2:

| Probe | Operation | Sent |
|---|---|---|
| text only | `structured` | the page's text in the prompt |
| image only | `vision` | the page's pixels on the message |
| text and image | `vision` | both, on one call |

**The pair is derived, never committed as a pair.** Nothing in the corpus is a
text/image pair — `casos/*.pdf` are born as PDFs and their readings are produced on
demand — and two unrelated fixtures would make a disagreement between the three answers
unattributable to the input. So `layout_text` and `render` both run on the same page,
and the render is capped by the page's own measured resolution because the adapter
**refuses to upscale** (asking the fixture's 149.69-DPI page for 150 yields no image at
all, not a bigger one).

**"Text and image" is a caller-side composition, and that is forced.** The frozen port
has no combined operation: `vision` is the only method with an `images` parameter, and
`structured` always passes `images=()`. The probe names the limitation instead of
hiding it — assuming a combined operation existed would mean inventing a port member,
which re-opens `E04-01`.

```bash
python scripts/poc/batch.py       <input-dir> --out <out-dir>
python scripts/poc/batch_pdf.py   <input-dir> --out <out-dir> [--pages 1-3] [--no-save]
python scripts/poc/batch_image.py <input-dir> --out <out-dir> [--target-dpi 150] [--assumed-dpi 96] [--region x,y,w,h]
python scripts/poc/batch_ocr.py   <input-dir> --out <out-dir> [--pages 1-3] [--lang es]
python scripts/poc/batch_llm_local.py <input-dir> --schema FIELDS.json [--out <out-dir>] [--mode structured|vision]
python scripts/poc/batch_llm_frontier.py <input-dir> --fields <local-out-dir> [--out <out-dir>] [--mode judge|vision]
python scripts/poc/hitl.py        <input-dir> --out <out-dir>
```

### `batch_llm_local.py` extracts fields, and reports a silence

The runtime **cuts a prompt that does not fit its window and reports nothing**: the
answer arrives with `done_reason: 'stop'` and a plausible value. Measured on
`smollm2` at `num_ctx=4096`, prompts of 34 000, 128 020, 144 020 and 153 000
characters all evaluate exactly **2 050** tokens - and the last two are repetitive
text and *random noise*, so the number is the window's edge and not tokenization.

The prompt's share of `num_ctx` is about half, `prompt + completion` lands just
inside the window, and everything past that share is dropped. So a document with long
text is answered **from its beginning** and nothing says so. The driver names every
file that happened to:

```
truncated          1

1 document(s) had their prompt TRUNCATED without a word. num_ctx=4096, so the
prompt's share is 2048 tokens; these reached it, and everything past it was dropped
while `done_reason` stayed 'stop':
  largo.txt (128071.0 chars -> 2050.0 tokens) - its fields describe the start of the document
```

Two earlier attempts at detecting this failed in the same direction and are recorded
in the code: looking for `truncated_output` (which fires on `done_reason: 'length'`,
never produced by a dropped prompt), and comparing files against each other (a single
cut file has no peer, so a three-file run named none). The mechanism is per call.

**The default local model changed to `deepseek-r1:1.5b` because `smollm2` stalls a
run.** On `chicos/22f0e9af-…-p1.txt` (1 589 bytes) `smollm2` intermittently enters an
unbounded repetition loop — measured once in 5 calls with no token ceiling — and a
sequential driver with a 600 s per-call ceiling stalls on it with no output between
files. `deepseek-r1:1.5b` answered 10 of 10 on that file in 4–11 s.

**And on the new default the silent cut above does not arise**, because
`deepseek-r1:1.5b` refuses an oversized prompt with `HTTP 400
exceed_context_size_error` naming `n_prompt_tokens` and `n_ctx`, where `smollm2` drops
it past the window and answers `done_reason: 'stop'`. `PROMPT_WINDOW_SHARE`
accordingly still fires only for `smollm2` — which stays selectable with
`--model smollm2:latest` — and its measurement is labelled as that model's.

### `batch_llm_frontier.py` is the contrast step

Two independent reads that disagree are the only detector of a silent error, and a
single confident answer is not evidence of correctness. This driver pairs each
document with what `batch_llm_local.py` answered for it and asks a **different**
model to assess it.

**It runs with no credential, and that is deliberate.** Every request refuses, and
the driver still does the part that is mechanical - the pairing, the gate chain, the
mirror - so a credential-less run is a dry run with a real report rather than a
driver that prints nothing. It exits non-zero, because a run that assessed nothing is
not a clean run.

`judge` **cannot see the image**: introspected, its signature has no `images`
parameter and it delegates to `structured`. It grades a transcript. `--mode vision` is
the branch that reads pixels.

### `batch_ocr.py` isolates the expensive, non-deterministic step

`batch.py` reaches K4 only for the pages `pdf.route_page` sent it and then goes on to
a model; `batch_pdf.py` stops before OCR entirely. Neither answers *what does this
folder of scans read as, page by page* — and OCR is the step whose cost (~1.5 s per
call warm, ~10 s for the first call in a process) and determinism class make it worth
inspecting on its own.

**Both `read` and `layout` run, and that is a decision.** `layout` answers §3 — the
text with its rows — but it **names no page**: measured, `layout 1-3` on the fixture
whose page 2 is blank returns 680 characters and says nothing about page 2, because
`blank_page` is raised only when *every* page in the selection is blank. `read`
reports `page_status` per page and is the only operation that can account for one. A
census built on `layout` alone would silently drop blank pages — precisely the loss
this project exists to make visible.

One `.txt` per document, not per page: `layout` returns a single string and names no
page inside it, so a per-page split would be a guess. (`ocr.SEPARATOR` is the **row**
separator `" | "`, so splitting on it would cut rows.) The per-page facts live in
`<stem>.ocr.json`, built from `read`.

A blank page gets **no** `.txt`: an empty file is indistinguishable from a read that
produced nothing. It gets a record instead, and the run reports the count:

```
page status    pages
blank              1
read               5
written            5
```

See `/memories/repo/build-and-test.md` for the measured finding that one committed
scan fixture reads as `blank` at every DPI despite holding ink.

### `batch_image.py` runs §2 over a folder

`batch.py` runs the legibility gate and goes straight to OCR; `batch_pdf.py` never
touches K3. Neither answers *what does this folder of images look like* — how many are
legible, what resolution they hold, which ones an OCR pass would be wasting its time
on. That answer costs one `info` and one `legibility` per image and needs no engine
downstream of K3, which is what makes it usable where `batch.py` is not.

The unit is the **file**: an image has no sub-units, so there is no equivalent of
`batch_pdf.py`'s per-page routing.

| Step | Operation | Output at the mirrored path |
|---|---|---|
| measured | `info` | nothing; size, format and orientation are recorded |
| gated | `legibility` | nothing; the reading and the verdict are recorded |
| brought to the floor | `rescale` | `<stem>-dpiN.png`, when the floor is reachable |
| cropped | `crop` | `<stem>-crop-rX-Y-W-H.png`, when `--region` is given |

**`illegible` is a report, not a filter.** It is a legitimate answer about a document
(matrix row 7), so the driver records it and still measures everything else. A batch
that silently dropped every blurred image would answer its cut of the corpus without
saying what it had thrown away.

**The resolution comes from a sidecar first, and from the caller second.** `rescale`
requires `source_dpi` and K3 reports no DPI at all (`info` gives `width`, `height`,
`mode`, `format`, EXIF orientation — nothing else), so this step used to depend
entirely on `--assumed-dpi`. But a number the caller *asserts* is an assumption, and
`batch_pdf.py` **measures** exactly that number to cap its render — it was simply
thrown away.

So `batch_pdf.py` now records two resolutions per page in `<stem>.pages.json`, and
`batch_image.py` reads them back:

| Field | What it is |
|---|---|
| `measured_dpi` | what the page's original pixels hold — a fact about the PDF |
| `rendered_dpi` | what the artifact was written at — a fact about the bytes on disk |

`read_source_dpi` consults **the sidecar first, `--assumed-dpi` second**, and that is
the reverse of the usual flag precedence on purpose: a flag describes what the caller
*believes*, and a recorded measurement is knowledge. Letting a belief override a
measurement is how a rescale gets refused for being below a floor it actually clears.
It reads **`rendered_dpi`**, because that describes the file the next stage holds; the
two coincide while the render is capped by the page and diverge the moment the floor
is raised.

Faithfulness of the search order is visible in the message:

```
before:  not rescaled: no --assumed-dpi, and K3 cannot measure the DPI
now:     below the floor: 100 < 150 declared readable, and upscaling is refused
```

The first is a **non-event** — the driver did not look. The second is a **finding
about the corpus**: this image is below what the corpus calls readable, and no rescale
will change that. `diagnosis.min_dpi` is a *minimum readable* resolution, so a 100-DPI
image against a 150 floor cannot be brought up to it; the adapter refuses to upscale,
and that refusal is right, because resampling cannot put information into pixels that
were never sampled. Reporting it as a bare absence of a file is the silent failure
this bench exists to catch. (It is also why `image rescale` cannot succeed from the
CLI —
see `image.py` FINDING D in `/memories/repo/build-and-test.md`.)

### `batch_pdf.py` is `batch.py` with K3 onward taken out

`batch.py` asks *what fields does this corpus hold*, and its answer costs an ONNX load
and a generation **per document**. `batch_pdf.py` asks *what is this corpus made of* — how
many pages are text, how many are scans, how many are blank — and its answer costs one
`classify` **per page**. Running the first to get the second is minutes of work to obtain
a page tally, and it is unusable on the 11k-document corpus (`prd.md`) for that reason.

The unit is the **page**, not the document, and that is not cosmetic: the large fixture
has 59 pages of which 2 report `blank_page` while the rest carry text, so a per-document
decision would route those two to the renderer and export pageless bitmaps. Measured: a
range *containing* a blank page is not refused by either operation — `layout_text 1-3`
returns 1263 characters and `render 1-3` returns 208 761 bytes — so a range operation
cannot be asked "is this range text or image" and the granularity has to be the page.

| Shape | Route | Output at the mirrored path |
|---|---|---|
| `text`, `mixed` | `layout_text` | `<stem>-pN.txt` |
| `image` | `render` | `<stem>-pN.png`, for K4 |
| `blank` | none | nothing; recorded in `<stem>.pages.json` |
| refused | none | nothing; recorded, and the run says so |

A `blank` page is **not** exported: the kernel's own statement that it holds neither
usable text nor an image, so a render would write a bitmap of nothing and hand it to OCR
to read nothing. It is *accounted for* rather than silently dropped — `<stem>.pages.json`
records every page's shape and route, so the census is a file a pipeline can read instead
of a console line that scrolls away.

**The export resolution is a target, not a demand.** The registry's `diagnosis.min_dpi`
(150) is capped by each page's own measured resolution, because the adapter refuses to
upscale and that refusal is correct — an upscaled page is larger and no more legible.
Measured on the committed scan fixture: `render @120` returns 165 960 bytes and
`render @150` is refused `insufficient_effective_resolution`. Asking for the floor
blindly would leave the one page that most needs exporting with no file at all.

### `batch.py` is not K1

K1 (`kernels/orchestrator.py`) drives a stage graph over units with a ledger, a
cache key per stage, `pause`/`resume`/`stop` and a manifest derived from the
ledgers. `batch.py` has **none of that** and cannot resume: re-running re-does the
work. It composes the **adapters** the way §6 describes, for one walk of a folder —
which is the piece no single-kernel probe can cover.

The mirror is the deliverable, so `batch.py` **asserts** it rather than printing it:
every input file gets an output at the same relative path, and every input directory
exists in the output **including the empty ones** (`FR-28`, `S3-T06`). A file that is
refused or invalid gets `<stem>.skipped.json` — never `<stem>.json`, because that
name means *these are the extracted fields*, and reading a skip record as an empty
extraction is the collapse this project exists to prevent.

#### The §6 steps, and the two that are deliberately not here

§6 reads: classify → **validate by kind** (legibility for an image, password for a
PDF) → produce text → **validate the content** → extract fields → mirror. The two
validation steps used to be missing; what they became is worth stating because one of
them is *half* the flow's sentence:

- **a PDF is probed before anything is extracted from it.** K2 answers a protected
  document with a **typed refusal** — measured on a real AES-256 file, `probe`
  returns `value: None` and `reason.code: 'encrypted'` — so the guard is the refusal
  branch rather than a flag read. **Nothing is ever decrypted**: a password would
  have to arrive as an argument, and `NFR-05` keeps credentials out of parameters.
  The flow asks *is this protected*, so *protected, skipped, said so* is the answer.
- **the content validation is a refusal, not a judgement.** §6 asks whether the text
  *"corresponds to the expected document type"*, and deciding that requires knowing
  the expected type — a **later stage's** question. What runs is the one check that
  needs no expectation, `reader.min_chars` from the registry, the same floor K2 uses.
  A richer check would be this driver inventing a rule it cannot ground.

#### Two defects the fixtures found

**The render resolution was fixed at 200 DPI, and the registry says 150.** Measured
on the committed scan fixture, which holds **120 DPI**: `render @200` returns
`insufficient_effective_resolution` and produces **no bitmap at all** — for exactly
the page being rendered *because* it has no text layer. The registry floor is a
**target**, capped by what the page holds; `_render_dpi` takes the smaller of the two,
the same shape as `batch_pdf.py::_export_dpi`. Verified after the fix: the scan
renders at 120 and the file is written.

**The OCR call passed `[1]` where `layout_rows` takes `"1"`.** All three page-taking
drivers take the selection **as a caller writes it** — the text `--pages` accepts —
and expand it themselves through `parse_pages`. A list reached that expansion as a
list, so the batch died with `UsageError: page '[1]' is not a number or a range` on
the first image it met. This is the same boundary `pdf.py` and `ocr.py` document, and
it is why the batch is worth running rather than reading.

**`skipped` and `failed` are now counted apart.** They used to be one number, which
made a clean run over unprocessable inputs — a protected PDF, an illegible scan, a
`.md` file — report as broken. A skip is the flow working (it asked, the document
said no, the output says why); a failure is a file in scope that produced nothing.

#### The extraction prompt and schema are registry artifacts, and the reading rules are the fix

The extraction step used to carry a **one-line prompt** (`"Extract the fields from this
document's text."`) and a two-field schema with `total` declared as an `integer`. Both
were the defect. On `casos/66cd35e9-…`, whose text prints `$ 17.898,30`, the same model
returned `1789830`, `1789830` then `17898` over three runs: the schema told the model the
answer was a number, so a decimal separator it could plainly read had to go. Nothing
errored — a wrong number is a valid number.

Both now live in `registry/`, as **two artifacts answering two questions**:

| Artifact | Key | Says |
|---|---|---|
| `registry/prompts/extraction/invoice.txt` | `prompts/extraction/invoice.txt` | *what to look for, and how to read it* |
| `registry/schemas/extraction/invoice.json` | `schemas/extraction/invoice.json` | *what shape the answer must have* |

They are separate files because they change for different reasons and on different
schedules — a prompt is edited when the reader gets something wrong, a schema when the
downstream contract moves — and a single file forces the two edits into one diff. The
cost of that split is drift, paid for by a test: `tests/kernels/test_committed_registry.py`
compares the schema's `required` against the prompt's own text, in both directions. It
earned its place immediately, by catching **a defect in the prompt as first written**:
16 fields were required by the schema and named nowhere in the instructions, so the model
was constrained to answer with keys it had never been told about.

The prompt's substance comes from `legacy/prompts/11-extraction_key_value_invoice_prompt.yaml`:
22 fiscal fields, the printed format of each, a `comprobante_valido`/`motivo_rechazo` pair
so the model can **refuse a non-receipt instead of inventing fields**, and the rule that
settles the CUIT (cut at the first character that is not a digit or the number's own
hyphen). Rule 4 is the load-bearing one for the defect above: **an amount is returned as
printed, as text** — `17.898,30` returns `"17.898,30"`. Verified against the schema too:
`string` keeps `17898.30`, whereas a `number` gives back `17898.3` and silently loses the
trailing zero.

Measured with the registry pair, three runs each:

| model | returned as printed |
|---|---|
| `deepseek:deepseek-v4-pro` (API) | **3/3** |
| `deepseek-r1:1.5b` (local — what this driver calls) | **1/3** observed: `17.898,30`, `$17.898,30`, `17,898,30` |

So the prompt fixes the **format** and the model fixes the **reliability** — and that is
the honest reading of the original defect: it was *prompt **and** model capacity*, not
prompt alone. A 1.5B model also mis-echoes key names (`improve_total_facturao`,
`cuit_copiano`), which no prompt can repair. `batch_llm_frontier.py` is the contrast step
that makes the gap visible, and the artifacts are read through **K8** (`load_registry`)
rather than by path, so the manifest stays the one authority on what exists.

#### A document is read per page, and capped at three — and the cap is announced

Every page is classified and decided **on its own**, then joined with a form feed.
The decision has to be per page: one PDF mixes text pages, image pages and `blank`
ones, and reading only page 1 — which this driver used to do — reported a cover as
the document's text on the 59-page fixture (1 page of 59).

**`MAX_PAGES = 3` is this version's limit, not a policy.** Measured: three pages of
the large fixture are 1 262 characters against a prompt budget of roughly 8 000 for
`num_ctx: 4096`, while the whole document is 167 035 — an oversize prompt is an HTTP
400, not a shorter answer. Chunking is what actually solves it, and it needs a
tokenizer plus a merge rule for fields two chunks disagree about.

**What ships is the announcement, not the number.** A document read in part and
reported as read is the same failure class as a prompt cut by `num_ctx`: the answer
looks whole and nothing says what is missing. So a capped read returns a sentence
naming what it dropped, and that sentence reaches the console, the skip record and
the exit code:

```
  ~ MetodoCITRA17-APL.pdf   pdf   layout_text -> …txt + …json
      PARTIAL: read the first 3 of 59 pages — this version caps a document at 3
      (MAX_PAGES); the text below is NOT the whole document; p2: the page holds
      neither usable text nor an image
```

`~` is the third state, and it exists because the other two would each be a lie:
`ok` would omit the truncation, and `..` would hide that an extraction happened.
Verified: a 3-page document reports `ok` / `partial 0`; 59 pages reports the banner
and **exit 1**. Muting the field leaves the banner absent *and* the exit code back at
0 — which is how the announcement was falsified rather than assumed.

This is also why the run got fast: 2 m 40 s → **14 s** on the large fixture, with the
limit stated instead of silently applied.

### `hitl.py` and the three limits it reports

1. **`judge` cannot see the page.** §7 asks to send *"el resultado de `llm.local`
   junto con la imagen original"*, but
   `judge(model, rubric, samples, produced_by)` has **no `images` parameter** — its
   body builds the prompt from the rubric, a sentence asking for a JSON object, and
   `json.dumps(samples)`, and calls `self.structured(...)`, which passes `images=()`.
   So it grades a *transcript*. The comparison that sees the page is **`vision`**, and
   `hitl.py` runs both so the difference is a measurement rather than a claim.
2. **The grade has no shape, and it shows.** `judge` carries no schema on the port, so
   the adapter sends `{"type": "object"}` and nothing tells the model what a grade
   looks like. Measured against the local runtime, it **echoes the samples back** —
   `{"total": "1789830", "cuit": "20-12345678-9"}` — which parses as an object, so the
   call reports a *value*: the grade is the thing being graded, and nothing can fail,
   because all a parser can check is that the answer is an object. Measured one
   variable at a time on the same model: with a result-shaped schema the answer becomes
   `{"fields": [{"name": "total", "supported": true}, …]}`. So the schema is the fix,
   and `judge` cannot be handed one. `GRADE_SCHEMA` in `hitl.py` is that shape, kept
   beside the call as the *evidence* of the gap because there is nowhere to pass it —
   the port change is the `TODO`.
3. **`Reviewer` is `S2-T15` and `src/docflow/components/` does not exist.** So there
   is no queue, no `correct` and no `promote`. What `hitl.py` does is the mechanical
   half: find the extractions, pair them by relative path, contrast them, and write
   `review.json` where a person should look. **The decision is still a human's.**

A missing second reading is reported as **`NOT CONTRASTED`**, not as a divergence:
*the readings disagree* is a finding about the document; *nobody read it twice* is
an absence of evidence, and counting the second as the first makes an uncalled check
look like a detected problem.

## What the probes found

Full detail in `/memories/repo/build-and-test.md`; the headlines:

- **`blank_page` on every image file.** `page_facts` takes `image_count` from
  `page.get_images()` (**0** for an image) while `largest_image_fraction` comes from
  `page.get_image_info()` (**1**). Two APIs of one engine disagree inside a single
  measurement, so a scan is reported as a page with *"no text and no image"* —
  contradicting `PageFacts.is_blank`'s own docstring.
- **`image rescale` is unreachable from the CLI.** The command's `_measured_dpi`
  lookup finds none of `dpi`/`effective_dpi`/`source_dpi`, because `ImageMeta`
  carries only `(format, exif_orientation)` — while 10 of 76 fixtures declare a DPI
  that is being discarded. The adapter is correct; nothing measures the value.
- **"resize by size" has no operation.** `RasterEngine` exposes exactly `crop`,
  `info`, `legibility`, `load`, `rescale`, `vendor`, and none takes a target size.
- **"preserve the layout" is `layout`, not `read`.** `read` reports
  `reading_order: 'not_resolved'` by design; `layout` returns ordered rows and is
  adapter-only.
- **A `Path` passed to `vision` silently encodes the file name.** `_encode_image`'s
  docstring promises *"a `Bytes` value, or a path, or bytes"*; a `str` path raises
  `TypeError` and a `Path` object is accepted as `bytes(path)` — 136 base64 chars of
  the filename where 340,932 of pixels were expected. No error, plausible answer.
- **`skew_estimate` saturates at ±5°.** A real 0.25°-step sweep, so `±5.0` means
  "at least 5", not a measurement.
