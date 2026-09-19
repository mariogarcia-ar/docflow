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
