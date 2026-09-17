# Quickstart — what K3 (`kernel.image`) can do today

**Status: honest, and complete for Stage 1.** Six of the eight kernels can serve a call;
this page covers the image one, whose kernel **and** adapter have landed and whose split
between them is part of the design now. Everything below has been run and its output is
quoted from a real invocation.

There is **no command line for kernels yet** (`S1-T20`/`S1-T21` build
`docflow-kernel`). Everything here is the **library**, called from Python. That is
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
| `docflow-kernel image ...` as a command | `S1-T20`/`S1-T21` — no kernel has a CLI yet |
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
| K2 `pdf` | **Landed** — see `quickstart-kernel-pdf.md` |
| K4 `kernel.ocr` | **Landed** — Docling behind `OcrEngine` (`E04-04`) |
| K5 `kernel.llm.local` | **Landed** — Ollama behind `LlmEngine` (`E04-05`) |
| K6 `kernel.llm.frontier` | **Landed** — one provider behind `LlmEngine` (`E04-06`) |
| K7 `store` | **Landed** — content-addressed put/get/verify + the ledger write path |
| K8 `registry` | **Landed** — load, schema-validate, fail fast, `registry_hash` |
| K1 `orchestrator` | Not yet (`E05-01`) |

Six of the eight can serve a call in this workspace. **K6 is the exception among the
landed ones**: its adapter exists, but its probe also requires a provider key and this
workspace has none, so `docflow-kernel --list` correctly reports it unavailable —
*available* would be a claim that a paid call could be made.
