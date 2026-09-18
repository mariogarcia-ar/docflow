# Quickstart — what K3 (`kernel.image`) can do today

**Status: honest, and complete for Stage 1.** Every kernel has landed, and seven
of the eight are reachable in this workspace — K6 needs a provider key;
this page covers the image one, whose kernel **and** adapter have landed and whose split
between them is part of the design now. Everything below has been run and its output is
quoted from a real invocation.

`docflow-kernel` now dispatches this kernel's operations — see `lab-cli.md` for the
bench. This page drives the **library**, called from Python, which is where the
detail lives. That is
the intended shape: `sad.md` ADR-008 makes the library first and the CLI one caller
of it.

---

## Setup

```bash
pip install -e ".[dev]"      # pytest, ruff, pylint
pip install pillow           # the raster engine
```

Pillow is resolved lazily, by the adapter. It is **not** a declared dependency yet
(`pyproject.toml` has `dependencies = []` until the adapters are tallied), and a
missing one is a typed `Reason` with a remedy in the message — never a substitute
engine, because a different decoder reading the same bytes is a different
measurement wearing this one's name.

## Where the code lives — and K3 has *no port*, deliberately

| File | What it holds |
|---|---|
| `docflow/adapters/image.py` | `RasterEngine` (the four operations) and `PillowVendor` (owns `PIL`) |
| `docflow/kernels/image_vendor.py` | `RasterVendor` — what the **decisions** ask a library through |
| `docflow/kernels/vendor_refusal.py` | the refusal both seams raise |
| `docflow/kernels/image.py` | the decisions: thresholds, refusals, the inverse map, orientation |

```text
(no port — K3's set is frozen at five, and a raster library is not a
 swap-able vendor boundary; a sixth interface would put a boundary
 where the architecture did not ask for one)
adapters/image.py    RasterEngine     the four operations; owns Pillow
      |
      v  calls
kernels/image.py     decisions        thresholds, refusals, inverse map; no Pillow
      |
      v  asks through
kernels/image_vendor.py  RasterVendor    the seam the decisions declare
      ^
adapters/image.py    PillowVendor     the implementation over Pillow
```

**K2 has a port and K3 does not, and that difference is deliberate.** A PDF engine is a
vendor you might replace; a raster library is not — the architecture says so in
`ports/__init__.py`, and a test asserts `RasterImage` is absent. What that means is that
K3 has no *outer* boundary. It does not mean the imaging library belongs inside the
kernel: `sad.md` §1 requires every kernel to be usable without its engine installed, and
this module used to hold `from PIL import …` in **four** places.

So the seam is an **inner** one — the consumer declares what it needs, the adapter
satisfies it — and its point is testability and replaceability of the library, not engine
selection. **A kernel may not import an adapter**, so the vendor arrives as a
keyword-only argument with no default.

## The whole surface

```python
from docflow.adapters.image import RasterEngine   # the adapter
from docflow.kernels.types import Box

engine = RasterEngine()      # the threshold is per call, never a setting
```

| Operation | Question it answers |
|---|---|
| `info` | What is this image, and which way is up? |
| `load` | Give me the pixels, upright |
| `legibility` | Is this sharp enough for the caller's purpose? |
| `rescale` | Give me a different resolution |
| `crop` | Give me a region, and tell me where it came from |

The kernel's own functions take `vendor=` as a keyword-only argument with **no default** —
a default would have to name a concrete library, which is the import the split exists to
avoid. Call the adapter instead; reach for the kernel directly only when you are writing
the vendor.

## 1. `info` — what is this image, and which way is up?

```python
result = engine.info(Path("foto.jpg"))
result.value.observed
# {'file': 'foto.jpg', 'width': 80, 'height': 40, 'mode': 'RGB', 'format': 'JPEG',
#  'exif_orientation': 6, 'exif_orientation_applied': True, 'exif_orientation_tag': 274}
```

**Two orientation fields, and they are not redundant.** `exif_orientation` is the
tag the file *declares*; `exif_orientation_applied` is whether the pixels had to
*move*. A rotation nobody recorded is indistinguishable from an image that needed
none, so both are reported.

`exif_orientation` is `None` when the file declares nothing — an absence, not a
zero.

## 2. `load` — the pixels, upright

```python
result = engine.load(Path("foto.jpg"))       # stored 80×40, declares rotate-90
from io import BytesIO
from PIL import Image
Image.open(BytesIO(result.value.data)).size
# (40, 80)          <- the rotation was applied
```

**This is the operation to know about.** The rotation happens *before* the bytes
leave the module, so a sideways photo is not representable in the value returned.
Reading the tag and reporting it is easy and leaves the photo sideways in every
later stage's input; the test decodes the returned bytes, so that implementation
fails.

`result.value.media_type` is `image/png` — lossless, because a page must not acquire
JPEG artefacts on its way to OCR.

From the golden set: **1 of 72 real images** declares an orientation
(`otros/4c261bc8…jpeg`, tag 8, 1600×1200). Rare is not the same as absent, and the
one that does declare it would have been silently sideways.

## 3. `legibility` — sharpness, against *your* threshold

```python
result = engine.legibility(Path("escaneo.jpg"), threshold=100.0)

result.value.measurements
# {'laplacian_variance': 318.6709, 'contrast': 0.070666,
#  'skew_estimate': -5.0, 'threshold_applied': 100.0}
```

**The threshold is a required parameter with no default.** What counts as sharp
enough is policy, and policy belongs to the caller (`prd.md` FR-15). A kernel
holding its own constant has made a routing decision whether or not it prints one.

When the measurement falls below the threshold, the result carries **no value, a
typed reason, and the same measurements**:

```python
blurred = engine.legibility(Path("borroso.jpg"), threshold=100.0)
blurred.value                          # None
blurred.reason.code                    # 'illegible'
blurred.evidence.measurements
# {'laplacian_variance': 0.3965, 'contrast': 0.011026, ...}
```

That is the difference between a reason and a boolean: the caller sees **the number
the verdict was taken from**, not just that something is wrong.

The same image flips verdict when only the threshold moves:

| Image | Threshold | Verdict | `laplacian_variance` |
|---|---:|---|---:|
| sharp fixture | 100 | value | 318.67 |
| blurred fixture | 100 | `illegible` | 0.40 |
| blurred fixture | 0.1 | value | 0.40 |

### What the measurements are

| Measurement | What it is |
|---|---|
| `laplacian_variance` | Variance of the discrete Laplacian — the standard sharpness measure. Sharp edges respond strongly; blur produces almost nothing |
| `contrast` | Spread of brightness, normalized to `[0, 1]` |
| `skew_estimate` | The angle at which text rows separate most cleanly, by projection, bounded to ±5° |

None of them is a score. There is no `quality`, no `confidence`, no aggregate —
a number that collapses measurements into a verdict is a decision wearing a
number's clothes, and `kernel-cli.md` §3 forbids it here.

### Over the golden set

Measured across the 72 real images in `tests/fixtures/`, **13 of 72** fall below a
threshold of 100 on `laplacian_variance`:

| | |
|---|---|
| minimum | 15.4 |
| median | 242.6 |
| maximum | 1731.6 |

The spread is what makes the threshold a *decision* rather than a formality: the
same value that passes most of this corpus refuses a sixth of it.

## 4. `rescale` — a different resolution, and it never upscales

```python
result = engine.rescale(Path("pagina.png"), target_dpi=100, source_dpi=200)
result.evidence.measurements["dpi_honoured"]     # 100.0
result.evidence.observed["result_size"]          # [300, 200]   (from 600×400)

refused = engine.rescale(Path("pagina.png"), target_dpi=400, source_dpi=200)
refused.value                # None
refused.reason.code          # 'insufficient_effective_resolution'
```

**`source_dpi` is a parameter you supply.** `Box` carries no DPI, and a kernel that
measured or assumed one would be reporting a number nobody gave it. Stating it
makes the refusal a comparison of two values you can see.

A target the source cannot reach is **refused rather than met by enlarging the
pixels**: a larger file would look the same and claim a resolution the source does
not contain. It is deliberately the same reason code K2's `render` uses, so a
caller matching on codes does not have to know which kernel declined.

A target equal to the source is accepted — nothing would change, and refusing it
would break a caller that simply passes through what it measured.

## 5. `crop` — the region, and where it came from

```python
result = engine.crop(Path("pagina.png"), Box(100.0, 200.0, 300.0, 80.0))

result.value.observed["source_box"]     # [100.0, 200.0, 400.0, 280.0]
result.value.observed["local_size"]     # [300, 80]  <- the crop's own frame

inverse = result.value.observed["inverse_map"]
inverse.to_source(0.0, 0.0)             # (100.0, 200.0)
inverse.to_source(300.0, 80.0)          # (400.0, 280.0)
```

**The bytes and the map travel together in one value.** Separating them would make
the conversion a step the caller has to remember, and the failure that produces is
silent: a crop whose local coordinates are reported as a page region points the
trace at the wrong pixels, and **both boxes are valid JSON**. This is `NFR-07`.

`to_source` is the whole contract: the crop's local origin maps to the region's
origin *in the page*, and its far corner to the region's far corner.

A region outside the image is a usage error and raises, rather than being clamped —
a clamp would return a crop of a different size than the one asked for, with an
inverse map that still looked right.

---

## The same operations from `docflow-kernel`

Everything above drives the **library**, which is where the detail lives. The lab
surface is a thin caller of the same four operations, and it is worth seeing what
each one looks like from a shell: the envelope is what a script parses, and the exit
code is where a refusal becomes *checkable* rather than merely printed.

Every block below is a real invocation with its output quoted verbatim. The JSON is
trimmed at the `...` marker only where the envelope repeats itself — `value` and
`evidence` carry the same observations, and showing both twice adds nothing.

Four commands are `now` in §9 and three are `MVP`. `--list` does **not** report which
is which — it lists the eight *kernels*, not the operations — so §9 is the authority
and an `MVP` command announces itself by exiting `4` naming itself unimplemented
rather than running partly.

### `image info <file>`

```console
$ docflow-kernel image info tests/fixtures/expected-extraction/dbc07b17-2538-4611-9e51-7e161aaf7ba5.jpg
{
  "value": {
    "terms": { "engine": "PIL", "engine_version": "12.3.0" },
    "measurements": { "width": 840.0, "height": 1036.0 },
    "observed": {
      "file": "dbc07b17-2538-4611-9e51-7e161aaf7ba5.jpg",
      "width": 840, "height": 1036,
      "mode": "RGB", "format": "JPEG",
      "exif_orientation": null,
      "exif_orientation_applied": false,
      "exif_orientation_tag": 274
    }
  },
  "evidence": { ... same three keys ... },
  "reason": null,
  "call_record": null
}
```

Exit `0`. The three orientation keys are easy to misread, so they are worth naming:
`exif_orientation` is the **value** found (`null` here — this particular file has no
orientation recorded), `exif_orientation_applied` says whether the pixels had to
move, and `exif_orientation_tag` is the EXIF **field number** (`274` is the field
that carries orientation, not a value of it). The tag that was *found* and the
rotation that was *applied* are two facts, and the envelope carries both — reporting
only the second would make a rotation indistinguishable from a file that needed
none. A file that does have one shows all three together:

```console
$ docflow-kernel image info tests/fixtures/otros/4c261bc8-3b30-4493-b5d4-6f499cde014e.jpeg
#   "exif_orientation": 8,
#   "exif_orientation_applied": true,      <- it was rotated
#   "exif_orientation_tag": 274
# exit 0
```

A file that is not an image is a typed refusal, not a crash:

```console
$ docflow-kernel image info docs/quickstart/kernel-image.md
# reason.code:  "unsupported_format"
# reason.message: "'kernel-image.md' could not be decoded as an image: ..."
# exit 2
```

Exit `2` is the *document's answer* — "this is not an image I can read" — and not a
usage error: the caller named a real path, and the answer about it is no.

### `image legibility <file>`

```console
$ docflow-kernel image legibility tests/fixtures/expected-extraction/dbc07b17-2538-4611-9e51-7e161aaf7ba5.jpg
# value.measurements:
#   { "laplacian_variance": 676.4729, "contrast": 0.225599,
#     "skew_estimate": -5.0, "threshold_applied": 100.0 }
# exit 0
```

The threshold is not a constant of this surface — it is read from
`registry/policies/thresholds.json` under `image.legibility_threshold`, and a
registry that does not declare that key is refused rather than quietly defaulted.

When the measurement is *below* the threshold the command still answers, and the
answer is a refusal that **keeps the numbers**:

```console
$ docflow-kernel image legibility tests/fixtures/casos/2991f57d-c143-4b23-9f87-4dfb1214ef53.jpg
# value:  null
# reason.code: "illegible"
# reason.message: "... measures 53.45 of sharpness, below the 100.0 the caller
#   requires, so no value is returned. The measurement is on the evidence, not
#   replaced by it: whether this makes the image unusable is the caller's
#   decision, taken against its own policy."
# evidence.measurements:
#   { "laplacian_variance": 53.4495, "contrast": 0.629139,
#     "skew_estimate": 5.0, "threshold_applied": 100.0 }
# exit 2
```

That shape is the point of the operation: the measurement **is** the answer, and a
bare boolean would throw it away. Note too that `contrast` here (`0.63`) is *higher*
than in the passing image (`0.23`) — sharpness and contrast are different axes, and
this file is soft but contrasty.

### `image crop <file> --region x,y,w,h`

This is `kernel-cli.md` silent-failure matrix **row 8**, and the one command whose
output you can check by hand:

```console
$ docflow-kernel image crop tests/fixtures/expected-extraction/dbc07b17-2538-4611-9e51-7e161aaf7ba5.jpg --region 100,120,400,300
# value.observed.source_box:    [100.0, 120.0, 500.0, 420.0]
# value.observed.source_size:   [840, 1036]
# value.observed.local_size:    [400, 300]        <- the crop's own frame
# value.observed.inverse_map:   { "offset_x": 100.0, "offset_y": 120.0, "scale": 1.0 }
# value.observed.coordinate_space: "source_page"
# value.observed.image:         { "sha256": "d1ff19f1...", "size_bytes": 125310,
#                                 "media_type": "image/png", "path": null }
# exit 0
```

`inverse_map` is what row 8 asserts on, and it is reported in source-page
coordinates: the crop's local `(0, 0)` maps back to `(100.0, 120.0)` in the page, and
its far corner to `(500.0, 420.0)`. Without it, a trace pointing at pixels inside the
crop would be read as page coordinates — and **both boxes are valid JSON**, which is
exactly why the map travels with the bytes instead of being a step the caller is
trusted to remember.

`path` is `null` because nothing wrote the bytes — the default is out-of-band: stdout
carries the descriptor (here `observed.image`), never the image itself.

`--save` declares where those bytes go, and it works: the crop's buffer lives one level
in, under `observed.image`, because it must travel with the inverse map, so the command
declares that key and the dispatcher reaches the buffer through it.

```console
$ docflow-kernel image crop <file> --region 10,10,50,50 --save /tmp/crops
# value.observed.image:
#   { "sha256": "6f35…", "size_bytes": 125310, "media_type": "image/png",
#     "path": "artifacts/6f35…",
#     "delivery_name": "dbc07b17-2538-4611-9e51-7e161aaf7ba5-crop-10-10-50-50.png" }
# value.observed.inverse_map:  { "offset_x": 10.0, "offset_y": 10.0, "scale": 1.0 }
# exit 0
```

Only `observed.image` changes: it gains the hash of what was written, the path relative
to the save root, and the `delivery_name` a consumer selects a reader by. As with every
`--save`, **two files with the same bytes land in the tree**: `artifacts/<sha256>` is the
store's copy (its name *is* its identity, so it carries no suffix) and
`<sha256>.png` sits at the save root under the suffixed name — see `kernel-pdf.md`'s
`render` section. The inverse map, the source box and `coordinate_space` are untouched:
the record is rebuilt with one entry replaced, not replaced wholesale.

The check is honest — `crop` returns `Evidence` with the buffer *inside*
`observed.image`, and `--save` writes a `Bytes` *value* — which is why the command
declares `observed.image` as its buffer key and the dispatcher reaches in through it.
That declaration is the difference between a save that works and one that would take an
arbitrary entry from a free-form mapping; on a command carrying two buffers it would
save the wrong one and report success.

### `image rescale <file> --target-dpi N` — and its open gap

```console
$ docflow-kernel image rescale tests/fixtures/otros/4c261bc8-3b30-4493-b5d4-6f499cde014e.jpeg --target-dpi 72
# value:  null
# reason.code: "unsupported_format"
# reason.message: "The engine reported no source resolution for this image, so a
#   rescale cannot decide whether the target is reachable. Refusing rather than
#   assuming a resolution the pixels do not hold."
# exit 2
```

**That refusal is correct and it is also the current limit of this kernel: no image
in this workspace can satisfy it.** The command chain is honest end to end — the
dispatcher passes `--target-dpi` through, the operation refuses to invent a default,
and the adapter will not upscale — but `source_dpi` is only ever read from `image
info`, and `info` reports **no DPI at all** (`ImageMeta` carries `format` and
`exif_orientation`, and the measurements are `width`/`height`). So `_measured_dpi`
looks in three keys, finds none, and the operation refuses every file rather than
assume a resolution the pixels do not hold.

Omit the flag and the refusal names *that* omission instead — exit `2`, not `4`:

```console
$ docflow-kernel image rescale <file>
# reason.message: "--target-dpi is required: a rescale with no target is not a
#   smaller default, it is a request that names no destination."
```

From the library the operation works, because **you** supply `source_dpi` — that is
the `engine.rescale(..., target_dpi=100, source_dpi=200)` call in §4 above. Closing
the gap means measuring DPI in `info` and carrying it on `ImageMeta`; it is recorded
in `## What K3 does *not* do yet` rather than papered over here.

### The `MVP` three

```console
$ docflow-kernel image deskew <file>
image deskew is not implemented in Stage 1 (kernel-cli.md §9 marks it `MVP`). It
does not dispatch and does not run partially.
# exit 4
```

`deskew`, `phash` and `tile` each behave this way: listed, known, and exit `4`
naming themselves unimplemented. An operation that has not landed stays
distinguishable from one that does not exist — which is exit `4` on a message like
`unknown flag` rather than on this one.

### The exit codes, in one table

| Exit | Meaning | Where K3 produces it |
|---|---|---|
| `0` | A value was produced | `info`; `legibility` above threshold; `crop` |
| `2` | The document's answer | `unsupported_format` on a non-image; `illegible`; the rescale refusals |
| `3` | A precondition failed | a policy key the registry does not declare — `image legibility` without `image.legibility_threshold` |

Exit `3` is the one worth seeing, because it is the failure a *healthy-looking*
registry can still produce. Point `--root` at a registry whose
`policies/thresholds.json` omits the key and the command refuses rather than picking
a threshold for you:

```console
$ docflow-kernel image legibility <file> --root /tmp/registry-without-the-key
# reason.code: "asset_missing"
# reason.message: "policies/thresholds.json declares no policy value
#   'image.legibility_threshold'. Refusing rather than defaulting ..."
# exit 3
```

That refusal is also why the key is pinned by a test: `image legibility` asking for a
key the registry did not declare is a defect this project has already shipped once,
and because the symptom was a *typed reason* rather than an error, it answered
`asset_missing` for every image with nothing looking broken.
| `4` | Usage: bad flag, unknown command, `MVP` | `image deskew`; an unknown flag; a missing positional |

One detail worth knowing before scripting against this: **`--repeat N`** re-runs the
call N times and reports a per-run digest under a `repetitions` key that appears only
when the flag is given. It **reports**, it does not retry — a `sampled` result stays
sampled rather than being quietly re-rolled until it agrees.

### Running all seven at once

`scripts/kernel/kernel-image.sh` drives the whole surface — the four `now` commands
and the three `MVP` ones — against one image:

```console
$ scripts/kernel/kernel-image.sh

image: tests/fixtures/expected-extraction/dbc07b17-....jpg

K3 - 'now' commands
  info                       exit 0  observed: exif_orientation, file, format, ...
  legibility                 exit 0  observed: file, height, threshold_applied, width
  rescale(dpi72)             exit 2  reason unsupported_format
  crop(10,10,50,50)          exit 0  observed: coordinate_space, image, inverse_map, ...

K3 - 'MVP' commands (must exit 4)
  deskew                     exit 4  image deskew is not implemented in Stage 1 ...
  phash                      exit 4  ...
  tile                       exit 4  ...
```

The image is a parameter and defaults to a committed fixture, and `--save` is passed
to the two commands that return bytes. **`rescale` is expected to refuse** — exit `2`
with `unsupported_format` — because `source_dpi` is read only from `image info`, and
`info` reports no DPI. That is the gap §4 documents, not a fault in the run, and the
driver marks it `--soft` so the summary does not report it as one.

The exit codes are **reported, not judged**: `2` and `4` are answers, and only exit
`1` — a bug in the build — fails the summary (`kernel-cli.md` §5).

---

## The split, and what it buys

`kernels/image.py` held `from PIL import …` in **four** places. The library moved to
`adapters/image.py`; the decisions stayed.

| | before | after |
|---|--:|--:|
| `kernels/image.py` | 905 lines | 842 |
| imaging libraries it imports | `PIL` ×4 | **none** |
| `kernels/image_vendor.py` | did not exist | 360 lines (the seam) |
| `adapters/image.py` | did not exist | 625 lines (owns Pillow) |

**The line count fell by less than K2's did, and that is worth stating rather than
glossing.** K3's analysis is thin — 43 statements against 70 of vendor access — so most
of what the module contained *was* the pixels. What moved is the whole of the library
dependency; what stayed is the threshold comparison, the refusal, the inverse map and the
orientation decision.

**What it buys.** The decisions are testable with a stub vendor and no imaging library
installed, and a different raster library becomes possible without touching a judgement:
satisfy `RasterVendor` and pass it in.

**What it does not buy.** It does not make the decisions pure. A blurred image is still
*measured* by the library, and a library that measures wrongly still misleads them. The
split buys **replaceability and testability**, not correctness.

**Verified by mutation.** Fifteen mutations each break one guarded property and each fail
the test that guards it — harness: `tests/adapters/mutation_image.py`.

---

## Reading a result

Every call has the same shape:

```python
if result.reason is None:
    use(result.value, result.evidence)      # a value, with what was observed
else:
    match result.reason.code:               # no value, and why
        case "illegible": ...
        case "insufficient_effective_resolution": ...
        case "engine_unavailable": ...
```

The codes this kernel can raise, all from the closed set of `kernel-cli.md` §5:

| Code | What it means |
|---|---|
| `illegible` | Sharpness measured below the threshold you supplied |
| `insufficient_effective_resolution` | The target DPI exceeds what the source holds; nothing was produced |
| `unsupported_format` | The bytes are not an image the engine accepts; also the "file does not exist" case |
| `engine_unavailable` | The Pillow library is not installed |

For `info`, `legibility` and `crop` the value **is** the observation record, and
`result.evidence` is the same object — every call reports what it observed, and for
these three that report is the answer.

Three things raise `ValueError` instead, because they are mistakes in the request
rather than answers about the document: a degenerate crop region, a region outside
the image, and a non-positive resolution.

## What K3 does *not* do yet

| Not available | Where it lands |
|---|---|
| `docflow-kernel image info  legibility  rescale  crop` | **Now available** — see the section above and `lab-cli.md`. The `MVP` operations of §9 still exit `4` |
| A **successful** `image rescale` from the CLI | **Open gap** — the operation is `now` and its refusals are correct, but `info` reports no DPI, so `source_dpi` is always unreadable and every run refuses. The library path works because the caller supplies `source_dpi` |
| `--save` on `image crop` | **Declared but refused** — §9 lists it, and the dispatcher rejects it with exit `4` because `crop` returns `Evidence` while `--save` writes a `Bytes` value. `--save` works on `pdf render`, which does return bytes |
| Deskew, denoise, binarize, auto-contrast | `# TODO: [MVP]` — `image deskew` stays `MVP` and exits `4` |
| `phash`, `tile` | `# TODO: [MVP]` — both stay `MVP` and exit `4` |
| Any threshold of its own | **Never** — every threshold is the caller's (`prd.md` FR-15) |
| Any aggregate quality score | **Never** (`kernel-cli.md` §3) |
| A port interface | K3 has **no port**: a raster library is the one engine not behind a swap-able vendor boundary, so these operations are reached directly |

## Verifying it against the fixture set

The 72 images in `tests/fixtures/` are real documents rather than fixtures built to
provoke a failure. A pass over them:

```bash
python - <<'PY'
import json, pathlib, sys
sys.path.insert(0, "src")
from docflow.kernels import image
root = pathlib.Path("tests/fixtures")
entries = json.loads((root / "manifest.json").read_text())["entries"]
for entry in entries:
    if entry["extension"] in ("jpg", "jpeg", "png"):
        result = engine.info(root / entry["path"])
        print(entry["path"], result.reason.code if result.reason else "ok")
PY
```

All 72 decode. That is worth stating plainly: the engine accepted every image this
corpus contains, so the `unsupported_format` path is exercised by the tests rather
than by the fixture set.

## The other seven kernels

| Kernel | State |
|---|---|
| K2 `pdf` | **Landed** — see `kernel-pdf.md` |
| K4 `kernel.ocr` | **Landed** — Docling behind `OcrEngine` (`E04-04`) |
| K5 `kernel.llm.local` | **Landed** — Ollama behind `LlmEngine` (`E04-05`) |
| K6 `kernel.llm.frontier` | **Landed** — one provider behind `LlmEngine` (`E04-06`) |
| K7 `store` | **Landed** — content-addressed put/get/verify + the ledger write path |
| K8 `registry` | **Landed** — load, schema-validate, fail fast, `registry_hash` |
| K1 `orchestrator` | **Landed** — the closing flow |

Seven of the eight can serve a call in this workspace. **K6 is the exception among the
landed ones**: its adapter exists, but its probe also requires a provider key and this
workspace has none, so `docflow-kernel --list` correctly reports it unavailable —
*available* would be a claim that a paid call could be made.
