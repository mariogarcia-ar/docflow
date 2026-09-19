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

`FIELDS.json` is the pipeline's own schema — the file `batch_llm_local.py` takes as
`--schema` — so the K6 probes answer about the caller's fields and not about a fixture
the driver carries. All three are handed **one** document, read twice by K2:

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
python scripts/poc/batch_image.py <input-dir> --out <out-dir> [--assumed-dpi 96] [--region x,y,w,h]
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

**The resolution is the one thing that cannot be measured.** `rescale` requires
`source_dpi` and `K3` reports no DPI at all (`info` gives `width`, `height`, `mode`,
`format`, EXIF orientation — nothing else), so `--assumed-dpi` supplies it and there is
**no default**: an invented source resolution decides whether the target is reachable.
Without it the rescale is **skipped and the skip is printed**, never silent.

Two skips are worth telling apart, and the driver names each:

```
not rescaled: no --assumed-dpi, and K3 cannot measure the DPI
below the floor: 96 < 150 declared readable, and upscaling is refused
```

The second is the interesting one. `diagnosis.min_dpi` is a **minimum readable**
resolution, so a 96-DPI image against a 150 floor cannot be brought *up* to it: the
adapter refuses to upscale, and that refusal is right — resampling cannot put
information into pixels that were never sampled. That is a finding about the corpus,
not a failure, and reporting it as a bare absence of a file is the silent failure this
bench exists to catch. (It is also why `image rescale` cannot succeed from the CLI —
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

### `hitl.py` and the two limits it reports

1. **`judge` cannot see the page.** §7 asks to send *"el resultado de `llm.local`
   junto con la imagen original"*, but
   `judge(model, rubric, samples, produced_by)` has **no `images` parameter** — its
   body builds `f"{rubric}\n\n" + json.dumps(samples)` and calls
   `self.structured(...)`, which passes `images=()`. So it grades a *transcript*.
   The comparison that sees the page is **`vision`**, and `hitl.py` runs both so the
   difference is a measurement rather than a claim.
2. **`Reviewer` is `S2-T15` and `src/docflow/components/` does not exist.** So there
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
