# Pillow — dossier

> Kind: Python library (`PIL`)
> Processor / seam: `docflow.image.primitives` (fallback engine)
> Status: collecting (2026-09-24)

## A. Identity and provenance

| Field | Value |
|---|---|
| `engine` value in metadata | `pillow` (only if it ever becomes the engine in use — today OpenCV is primary) |
| Kind | **Python library**, imported at call time inside the primitive |
| Upstream | <https://python-pillow.org>; docs <https://pillow.readthedocs.io> |
| Context7 ID | `TBD` |
| Maintainer / cadence | Pillow maintainers (Tidelift-backed); monthly releases |
| Version this page was read against | local **12.3.0**; docs read at 12.3.0 (stable) |

## B. Install, pin and version discovery

- **Install shape:** pip wheel (`Pillow`).
- **Pin home:** `pyproject.toml` (`GEN-05`); pin `TBD` — the plan documents Pillow as the image **fallback**, so decide at `IMG-02` whether it is a real dependency or only an option.
- **Version at runtime:** `PIL.__version__` (or `importlib.metadata.version("Pillow")`).
- **Absent / present check:** import inside the primitive; `import docflow.image.primitives` must succeed with Pillow absent.
- **Suite without it:** the same `cv2` double covers the tests; a Pillow path would need its own double, which is a reason to keep Pillow out of the happy path.

## C. Licence and distribution posture

- Pillow is **MIT-CMU** — `TBD`: confirm against the installed `LICENSE`. It is the permissive sibling of the same code that Poppler ships under GPL, which matters only if a binary is ever redistributed.

## D. Interface contract — the methods we need

| Primitive | Pillow calls |
|---|---|
| `load_image` | `Image.open(path)` — raises `UnidentifiedImageError` / `OSError` (unlike `cv2.imread`'s silent `None`) |
| `save_image` | `img.save(path, format=..., quality=..., optimize=..., dpi=...)` |
| `get_image_metadata` / `get_image_dimensions` | `img.size`, `img.mode`, `img.format`, `img.info["dpi"]`, `img.getexif()` |
| `convert_image_format` / `convert_to_grayscale` | `img.convert("L" \| "RGB" \| "1" \| "CMYK")`, `ImageOps.grayscale(img)` |
| `resize_image` | `img.resize((w, h), resample=Image.Resampling.LANCZOS \| BICUBIC)` |
| `compress_image` | `img.save(..., quality=q, optimize=True)` (JPEG), `compress_level` (PNG) |
| `normalize_contrast` | `ImageOps.autocontrast(img, cutoff=...)`, `ImageOps.equalize` |
| `normalize_brightness` | `ImageEnhance.Brightness(img).enhance(factor)` |
| `denoise_image` | `img.filter(ImageFilter.MedianFilter(size))`, `ImageFilter.GaussianBlur(radius)` |
| `sharpen_image` | `ImageEnhance.Sharpness(img).enhance(factor)`, `ImageFilter.UnsharpMask(radius, percent, threshold)` |
| `binarize_image` | `img.convert("L").point(lambda p: 255 if p > t else 0)` — the threshold is **ours** |
| `rotate_image` / `deskew_image` | `img.rotate(angle, resample=..., expand=True, fillcolor="white")` |
| `detect_orientation` | `img.getexif().get(ExifTags.Base.Orientation)`; `ImageOps.exif_transpose(img)` applies it and **removes the tag** |
| `calculate_*_score` | `ImageStat.Stat(img).mean` / `.stddev` / `.var` / `.median` / `.rms` / `.extrema` (per band, so grayscale first) |
| `detect_text_regions` | **no equivalent** — a swap would have to be redefined or re-drawn on `ImageFilter`/morphology |

**ImageEnhance semantics** (they are the named constants a caller must not guess): contrast `0.0` = solid gray, `1.0` = original; brightness `0.0` = black, `1.0` = original; sharpness `0.0` = blurred, `1.0` = original, `2.0` = sharpened. `ImageStat.Stat.extrema` is documented as unreliable for non-8-bit modes — use `getextrema()` there.

**EXIF trap:** `exif_transpose` applies the orientation to the pixels **and deletes the tag**; a rotation performed with `img.rotate()` does **not** update EXIF. Mixing the two double-rotates an image. Our `rotate_image` must therefore be defined as "post-transpose" and the metadata we write must not re-state an orientation we already applied.

## E. Inputs, outputs and artifact naming

| Field | Value |
|---|---|
| Inputs | PNG/JPEG/TIFF/BMP/WEBP images |
| Outputs | `Image` objects, plus files when a variant is written |
| Our naming | ours (`normalized/`, `ocr_ready/`, `vlm_ready/`); Pillow never names our files |
| Ordering | `ImageStat` bands are ordered by mode (`L` → 1 band, `RGB` → 3) — read a grayscale image for a single scalar score |
| Encoding | `img.info` carries the source's `dpi`/`jfif`; `img.format` is `None` for a constructed image |

## F. Determinism levers

| Lever | Enters `processing_key`? |
|---|---|
| Resampling filter, quality/compress level, enhancement factors, blur radius, thresholds | yes |
| Pillow version (encoder tables change between releases) | yes — recorded as `engine_version` |
| EXIF handling policy (apply vs. preserve) | yes — it changes the pixels |

## G. Failure modes and our error mapping

| Engine signal | Our `ImageErrorType` |
|---|---|
| `PIL.UnidentifiedImageError` (unsupported/corrupt file) | `UNSUPPORTED_FORMAT` / `DECODE_ERROR` |
| `OSError` on open/read (missing or unreadable file) | `IO_ERROR` / `INVALID_INPUT` |
| `OSError` on `save` (unwritable path, unsupported format) | `WRITE_ERROR` |
| `ValueError` (bad mode, bad parameter) | `TRANSFORMATION_ERROR` |
| `DecompressionBombWarning` / `DecompressionBombError` (very large image) | `INVALID_INPUT` — a guard, not a crash; the limit is ours to state |
| anything else | `INTERNAL_ERROR` |

`ImageErrorType` as declared in `src/docflow/image/contracts.py`: `INVALID_INPUT`, `UNSUPPORTED_FORMAT`, `DECODE_ERROR`, `TRANSFORMATION_ERROR`, `WRITE_ERROR`, `IO_ERROR`, `INTERNAL_ERROR`.

## H. Seam ownership and the double

| Field | Value |
|---|---|
| Owning module | `docflow.image.primitives` |
| Injection point | the same seam as OpenCV (`docflow.image.primitives.<symbol>`); if Pillow ever becomes the engine in use, the patched attribute becomes `...image.primitives.Image` and the fake must return `Image`-shaped values |
| What "native-shaped" means | Pillow `Image` objects / `ImageStat` tuples — never our `ImageResult` |
| Shared helper | `missing_from_double(seam, "cv2", fake)` covers the OpenCV namespace only; a Pillow namespace needs its own entry once it exists |
| Other processors | none may reach Pillow |

## I. Cost, latency and limits

- Pillow is generally faster than OpenCV for decode/encode and resample on common formats, and slower for dense pixel math; the median filter is the expensive one here.
- `Image.MAX_IMAGE_PIXELS` (default ~89 M pixels) is Pillow's built-in decompression-bomb guard; a value we rely on must be stated explicitly rather than inherited.

## J. Alternatives and swap story

- Pillow is the **documented alternative** to OpenCV in the plan, so the swap story is the reverse of `opencv.md`: what cannot be swapped is CLAHE, adaptive threshold, NlMeans denoise, `warpAffine` deskew and text-region contour detection.
- A swap touches `image/primitives/` only, and changes the double's shape (namespace vs. class).

## K. Open questions and drift log

- [ ] Is Pillow a real dependency of the PoC, or only the documented alternative? The `# TODO: [MVP]` tag on a fallback path is the honest answer if it is never exercised.
- [ ] Context7 ID to cite for Pillow method answers.
- [ ] The binarize threshold and the `MAX_IMAGE_PIXELS` policy are decisions, not library defaults.
- [ ] Drift log: (2026-09-24) Pillow 12.3.0 installed; docs read at 12.3.0. No seam change observed.
