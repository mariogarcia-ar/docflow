# OpenCV — dossier

> Kind: Python library (`cv2`)
> Processor / seam: `docflow.image.primitives`
> Status: collecting (2026-09-24)

## A. Identity and provenance

| Field | Value |
|---|---|
| `engine` value in metadata | `opencv` |
| Kind | **Python library**, imported at call time inside the primitive (never at module import) |
| Upstream | <https://opencv.org>; wheels `opencv-python` / `opencv-python-headless` |
| Context7 IDs | `/websites/opencv_5_0` (**matches the installed 5.0.0.93**, queried 2026-09-24), `/opencv/opencv-python` (wheel packaging, not methods), `/opencv/opencv` (repo) |
| Maintainer / cadence | OpenCV.org; quarterly-ish minor releases |
| Version this page was read against | local wheels **5.0.0.93** (both `opencv-python` and `opencv-python-headless` are installed in this venv) |

## B. Install, pin and version discovery

- **Install shape:** pip wheel — a real dependency, unlike Poppler.
- **Pin home:** `pyproject.toml` (`GEN-05`); the pin is `TBD` (`dependencies = []` until `IMG-02`).
- **Which wheel:** `opencv-python` vs `opencv-python-headless` — the venv has **both at 5.0.0.93**, which is exactly the ambiguity the single-pin rule exists to remove. Decision: `TBD` (headless is the usual choice for a server-side, no-GUI pipeline).
- **Version at runtime:** `cv2.__version__` — the primitive reads it for `engine_version`.
- **Absent / present check:** a module-level `import cv2` is **forbidden** (it fails `test_importing_the_primitive_seams_pulls_in_no_engine`); the import happens inside the primitive, and `import docflow.image.primitives` must succeed with OpenCV absent.
- **Suite without it:** the whole suite runs on the in-memory double.

## C. Licence and distribution posture

- OpenCV is **Apache-2.0** — `TBD`: confirm against the `LICENSE` shipped in the installed wheel (some contrib modules are patent-encumbered, but we use core only).
- We import it in-process; nothing is redistributed beyond the pip dependency itself.

## D. Interface contract — the methods we need

One row per primitive of `subplan-procesador-image.md` §3.4. `img` is a `numpy.ndarray` in **BGR** order (OpenCV's convention — a grayscale/RGB mix-up is a silent defect).

| Primitive | OpenCV calls |
|---|---|
| `load_image` | `cv2.imread(path, cv2.IMREAD_COLOR \| IMREAD_GRAYSCALE \| IMREAD_UNCHANGED)` — **returns `None` on failure, raises nothing** |
| `save_image` | `cv2.imwrite(path, img, params)` — **returns `bool`**, `False` on failure |
| `get_image_dimensions` | `img.shape` → `(h, w, c)` / `(h, w)` |
| `get_image_metadata` | `img.dtype`, `img.shape`, plus the file-level read |
| `convert_image_format` | `cv2.imwrite` with format from the extension; `cv2.imencode(ext, img, params)` when bytes are needed |
| `compress_image` | `cv2.imwrite` params: `[cv2.IMWRITE_JPEG_QUALITY, q]`, `[cv2.IMWRITE_PNG_COMPRESSION, 0..9]` |
| `resize_image` | `cv2.resize(img, dsize, interpolation=cv2.INTER_AREA \| INTER_CUBIC \| INTER_LANCZOS4)` |
| `convert_to_grayscale` | `cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)` |
| `normalize_contrast` | `cv2.normalize` / `cv2.convertScaleAbs(img, alpha, beta)` / `cv2.createCLAHE(clipLimit, tileGridSize).apply(gray)` |
| `normalize_brightness` | `cv2.convertScaleAbs(img, alpha=1.0, beta=delta)` |
| `denoise_image` | `cv2.fastNlMeansDenoising(gray, h, templateWindowSize, searchWindowSize)` / `fastNlMeansDenoisingColored` / `cv2.medianBlur(img, k)` |
| `sharpen_image` | unsharp mask: `cv2.GaussianBlur` + `cv2.addWeighted(img, 1+a, blurred, -a, 0)` |
| `binarize_image` | `cv2.threshold(gray, t, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)` or `cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, blockSize, C)` |
| `calculate_blur_score` | variance of Laplacian: `cv2.Laplacian(gray, cv2.CV_64F).var()` |
| `calculate_sharpness_score` | Tenengrad-style `cv2.Sobel(gray, cv2.CV_64F, 1, 0)` / `(0, 1)` gradient magnitude mean |
| `calculate_contrast_score` | `gray.std()` (or `max-min` over the histogram) |
| `calculate_brightness_score` | `gray.mean()` |
| `calculate_noise_score` | deviation from `cv2.medianBlur(gray, k)` |
| `detect_orientation` | `cv2.findContours` + `cv2.minAreaRect` aspect ratio; portrait/landscape decision is **ours** |
| `detect_skew_angle` | `cv2.findNonZero`/`findContours` → `cv2.minAreaRect` → angle, with a median filter over candidate angles |
| `rotate_image` | `cv2.getRotationMatrix2D(center, angle, scale)` + `cv2.warpAffine(img, M, (w, h), flags, borderMode, borderValue)` |
| `deskew_image` | same pair, angle from `detect_skew_angle`, `borderValue=(255, 255, 255)` on a white page |
| `detect_text_regions` | `cv2.morphologyEx(..., cv2.MORPH_CLOSE, kernel)` over a gradient/threshold image → `cv2.findContours` |
| `calculate_text_coverage` | **ours**: union area of the detected regions ÷ page area |

**Verified signatures** (Context7, `/websites/opencv_5_0`):

```python
cv.fastNlMeansDenoising(src[, dst[, h[, templateWindowSize[, searchWindowSize]]]]) -> dst
cv.fastNlMeansDenoising(src, h[, dst[, templateWindowSize[, searchWindowSize[, normType]]]]) -> dst
# rotation + affine, as in the official geometric-transformations tutorial:
M = cv.getRotationMatrix2D(center, angle, scale)
dst = cv.warpAffine(img, M, (w, h))
```

- `fastNlMeansDenoising` lives in the **photo** module — if a build lacks it, the primitive must report `TRANSFORMATION_ERROR` rather than skip the step.
- `cv.warpAffine(img, M, (cols, rows))`: **the dsize argument is `(width, height)`**, in that order, and `np.float32` for `M` in the translation case.
- `cv.ImreadModes` includes `IMREAD_GRAYSCALE`, `IMREAD_UNCHANGED`, `IMREAD_IGNORE_ORIENTATION` and the 2×/4×/8× reduced-resolution flags (`IMREAD_REDUCED_GRAYSCALE_2`, …). Reduced reads are a real cost lever and therefore a **determinism lever**: a silent half-scale decode changes every downstream score.
- `cvtColor(img, COLOR_BGR2GRAY)` for grayscale; `convertTo` (or a NumPy cast) when a score needs `float32/float64` instead of `uint8`.
- **Docs gotcha:** the official Python examples write `cv.` (`import cv2 as cv`), while our code must use `cv2.`. Same bindings, different spelling — do not "fix" a doc snippet into `cv.`.
- **The docs' own idiom corroborates the silent-`None` trap:** the tutorial reads an image and immediately asserts it (`assert img is not None, "file could not be read"`). `cv2` never raises for a missing or undecodable file.

**Required to be explicit:** every threshold, kernel size, `clipLimit`, `blockSize`, `C`, DPI and quality factor is a named parameter with a documented value — never `cv2`'s or our own silent default (`no silent stand-in`). `cv2.warpAffine`'s `borderMode`/`borderValue` especially: the default (`BORDER_CONSTANT` with black) leaves black wedges on a deskewed white page.

## E. Inputs, outputs and artifact naming

| Field | Value |
|---|---|
| Inputs | PNG/JPEG/TIFF/BMP images read from disk (from `pdf/render/` or the caller) |
| Outputs | **in-memory arrays**, plus files when a variant is written (`normalized`, `ocr_ready`, `vlm_ready`) |
| Our naming | the `image/` artifact namespace; OpenCV never names our files |
| Ordering | text regions are ordered by us (reading order is not an OpenCV concept) |
| Encoding | no text output; pixel depth/`dtype` (`uint8` vs `float64` after a score) is the thing to keep explicit |

## F. Determinism levers

| Lever | Enters `processing_key`? |
|---|---|
| Interpolation flags, kernel sizes, thresholds, `blockSize`/`C`, `clipLimit`, quality factors | yes |
| Target size for `resize_image` | yes |
| OpenCV version, and the `opencv-python` vs `-headless` wheel | yes — recorded as `engine_version` |
| NumPy version (array semantics) | recorded, not a lever |

## G. Failure modes and our error mapping

| Engine signal | Our `ImageErrorType` | Note |
|---|---|---|
| `cv2.imread` returns `None` | `MISSING_FILE`… no: `INVALID_INPUT` / `DECODE_ERROR` | **the dangerous one** — no exception, just `None`. Treating `None` as "empty image" would violate the no-silent-stand-in rule |
| `cv2.imwrite` returns `False` | `WRITE_ERROR` | also silent — check the boolean |
| `cv2.error` (bad dtype, bad kernel size, unsupported depth) | `TRANSFORMATION_ERROR` | the only exception type that carries a real message |
| file extension unsupported / not decodable | `UNSUPPORTED_FORMAT` / `DECODE_ERROR` | decided partly by us before the call |
| `FileNotFoundError` / `ImportError` | `IO_ERROR` | binary/wheel absent |
| anything else | `INTERNAL_ERROR` | |

`ImageErrorType` as declared in `src/docflow/image/contracts.py`: `INVALID_INPUT`, `UNSUPPORTED_FORMAT`, `DECODE_ERROR`, `TRANSFORMATION_ERROR`, `WRITE_ERROR`, `IO_ERROR`, `INTERNAL_ERROR`.

## H. Seam ownership and the double

| Field | Value |
|---|---|
| Owning module | `docflow.image.primitives` |
| Injection point | `monkeypatch.setattr("docflow.image.primitives.cv2", fake_opencv)` — the fake is a **plain namespace** exposing only the attributes the seam uses (`imread`, `imwrite`, `cvtColor`, …), so no test imports `cv2` |
| What "native-shaped" means | decoded **pixels** (a small synthetic array) and **raw score values** (`blur`, `sharpness`, `contrast`, …) — never our `ImageResult`, never the output of `analyze_image` / `normalize_image` |
| Shared helper | `missing_from_double(seam, "cv2", fake)` **applies** |
| Other processors | none may reach OpenCV |

## I. Cost, latency and limits

- Most operations are O(pixels); `fastNlMeansDenoising` is the expensive one and is the reason to keep it out of the happy path.
- Memory is `h × w × channels` bytes per copy; a 200-DPI A4 page is roughly 1654 × 2339 px.
- No documented hard limits for the functions above; the practical limits are memory and the denoise cost.

## J. Alternatives and swap story

- **Pillow** is the documented fallback (`image/primitives/` is the only place that changes), and it is a genuine fallback: `ImageOps.autocontrast`, `ImageEnhance`, `ImageFilter` cover normalize/enhance/denoise/sharpen.
- Pillow has **no** equivalent for `createCLAHE`, `adaptiveThreshold`, `fastNlMeansDenoising` and `warpAffine` — a swap would redefine those primitives, not just re-implement them. Record the primitive-by-primitive verdict when the swap is actually attempted.
- `pypdfium2` / `PyMuPDF` are installed but belong to the PDF processor, not here.

## K. Open questions and drift log

- [x] Context7 ID to cite for OpenCV method answers — **answered**: `/websites/opencv_5_0`, the docs line that matches the installed 5.0.0.93.
- [ ] `opencv-python` vs `opencv-python-headless` as the pin (both installed at 5.0.0.93 today).
- [ ] OpenCV **5.x** API differences against the 4.x tutorials most material is written for — check every call in §D against the installed 5.0.0.93 signature rather than a blog post.
- [ ] Which primitives are OpenCV-only (CLAHE, adaptive threshold, NlMeans) — that list decides how honest the "Pillow fallback" claim is.
- [ ] The named threshold values for `calculate_blur_score` / `detect_skew_angle` limits (a threshold is a decision, and belongs to `IMG-08`, not to a library default).
- [ ] Do we ever read at reduced resolution (`IMREAD_REDUCED_*`), and if so is the factor recorded as an option? A silent factor is a silent default.
- [ ] Drift log: (2026-09-24) wheels 5.0.0.93, NumPy 2.3.5; signatures above checked against the 5.0 docs. No seam change observed.
