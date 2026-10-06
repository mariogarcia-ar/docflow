# Decision — a stated quality factor, and an exposure correction that never darkens a page

> Status: **applied**. Supersedes no earlier note; it records a contract revision applied to
> `docs/plan/subplan-procesador-image.md` and `docs/plan/issues/wbs-procesador-image.md` in the
> same pass (as the plan convention requires), and to `src/docflow/image/`.
>
> Five decisions, one of which is a defect fix rather than a decision. Two of the five change
> the processor's contract; the defect keeps every name and signature it had.

## 1. What the corpus showed

Two signals, both measured with the processor's own primitives over the committed `casos/`
pages, and neither one what it first looked like:

| Signal | Measurement |
|---|---|
| The VLM payload is inline base64, and the artifact is lossless PNG by name | one page: `normalized.png` **3,122,841 B** → **4,163,788 B** of base64 in the request body |
| A published artifact read `contrast 17.04` against a source reading of `45.81` | the container was not the cause (PNG 17.04, JPEG q85 17.12, q75 17.21); `normalize_brightness` was |

The second signal decomposed into two independent causes, and each earned its own decision:

1. **The operator folded the tone scale.** `normalize_brightness` called
   `cv2.convertScaleAbs(alpha=1.0, beta=delta)`, which answers **`|value + delta|`**. A
   negative shift therefore *mirrored* every value below `|delta|` around zero — on that page
   source grey `0` came back as `114` and `113` as `1`, so the darkest ink came out lighter
   than the paper and the scale was no longer monotone. Its own docstring claimed "saturated
   to the 8-bit range". A positive shift was correct all along (`|x + β| = x + β` for
   `β ≥ 0`), which is why nothing had noticed.
2. **The policy darkened a white page.** The correction shifted every page outside the
   brightness band to `BRIGHTNESS_TARGET` — the *middle* of the band, 130. The reading is the
   page's **mean**, and on a document the mean is mostly ink coverage: a clean, sparse, white
   invoice reads as washed out while its paper is exactly the white a reader wants. That page
   was **3.98 grey levels** above the ceiling and was shifted by **−113.98**, repainting its
   paper mid-grey.

Three of the six committed corpus pages sat above the ceiling, so the rule fired on precisely
the cleanest pages in the corpus.

## 2. What was decided

| # | Decision | Where it lands |
|---|---|---|
| D-1 | `ImageOptions.quality: int \| None` — a **required** field, no default. `None` publishes a lossless `.png`; `1..100` publishes a lossy `.jpg` for the representations that keep the page's tone (`normalized`, `vlm_ready`). `ocr_ready` is always lossless: its pipeline binarizes, and a lossy encoder rings around every glyph edge | contract, both pipelines, the bench's `--quality` |
| D-2 | The **container follows the factor**, and one function owns the rule: `representation_suffix(kind, quality)`. Every artifact name is composed from it, so no caller picks a container of its own | `contracts.py`, `entrypoints._artifact_name`, the bench layer |
| D-3 | A factor outside `QUALITY_MIN..QUALITY_MAX` is **refused, never clamped** — an encoder pulls it into its own range without saying so, and the artifact would then not be the one the options named | `validate_image_options` → `TRANSFORMATION_ERROR` |
| D-4 | The exposure correction **never darkens**: only a page below `BRIGHTNESS_MIN` is lifted to `BRIGHTNESS_TARGET`; a page above `BRIGHTNESS_MAX` is left alone | new `composition.brightness_shift` |
| D-5 | The brightness shift **saturates and preserves the tone order** | `normalize_brightness` → `cv2.add` / `cv2.subtract` |

**D-5 is a defect fix, not a decision.** The primitive keeps its name, its signature and its
stated purpose; only its arithmetic stops folding. D-1…D-4 are contract revisions.

**What the factor buys, and what it does not.** Bytes, not tokens. On one corpus page:
3,122,841 B (PNG) → 287,523 B (JPEG q85), i.e. 4,163,788 B → 383,364 B of base64. Image
**tokens** are decided by the model's patch grid over the pixel dimensions, so a smaller
container does not shrink the context: `VLM_MAX_DIMENSION` is that lever and it is unchanged
here. The `mime` a consumer derives already follows the artifact's suffix
(`llm/primitives._image_parts`), so no transport changed.

## 3. What did not change

- **The atomic publication rule** (`.tmp` → validate → rename). What changed is the *writer*:
  it asks the engine to encode bytes for a stated format instead of handing it a path, so the
  engine can no longer write a file at all. `publication.py` and its rule are untouched.
- **The `ocr_ready` container**: always `.png`.
- **The `is_low_quality` band**: still two-sided. Report, don't damage — a page above the
  ceiling is still *reported* as washed out while its artifact keeps its contrast.
- **Primitive names and signatures.** `compress_image` gains its first caller and loses its
  `# TODO: [MVP]`, but it is the same writer with one engine parameter.

## 4. Divergences deliberately created

- `subplan-procesador-image.md` §3.1 and §3.3 named `normalized.png` / `vlm_ready.png`
  unconditionally. The name now follows the factor, so a run that states one publishes
  `normalized.jpg` / `vlm_ready.jpg`. Recorded for `GEN-17`'s reconciliation list.
- The **flag and the correction diverge on purpose**: `BRIGHTNESS_MAX` still marks a page for
  `LOW_QUALITY` while no longer triggering a darkening. A reading worth *reporting* is not
  the same thing as an artifact worth *damaging*, and that distinction is the decision.
- A corpus page at brightness `254.53` / contrast `8.02` (below `CONTRAST_MIN = 12`) is now
  preserved as-is and reported rather than "corrected". A real contrast improvement is a
  different rule: `normalize_contrast` exists and is composed only by the OCR pipeline.

## 5. Verification

```bash
pytest                      # 737 passed (734 + 3 new guards)
ruff check .                # All checks passed!
ruff format --check .       # 181 files already formatted
pylint src tests            # one pre-existing finding, unchanged by this pass:
                            #   src/docflow/pdf/entrypoints.py:475 R0912 (verified red at HEAD)
```

**Mutation records** (each guard was proven to fail under its mutation, then restored green):

| Invariant broken | Guard | Observed |
|---|---|---|
| the seam ignores the quality factor | `test_a_stated_quality_is_the_encoder_parameter_and_the_container` | 1 red |
| the suffix ignores the quality factor | the container guards (contract, entry point, bench) | 3 red |
| the processing key drops the factor | `test_the_processing_key_follows_the_stated_quality` | 1 red |
| the shift folds again (`convertScaleAbs`) | `test_the_brightness_shift_keeps_the_tone_order_and_saturates` | 1 red |
| the correction darkens a white page again | `test_a_page_above_the_band_is_reported_and_never_darkened`, `test_a_white_page_is_left_alone_and_a_dark_one_is_lifted` | 2 red |

**Real-engine observations** (the double cannot produce a JPEG, so these are observations and
not gates):

```bash
python scripts/tools/batch_image.py tests/fixtures/image normalize --quality 85
#   -> real JPEGs: magic ffd8ff…ffd9, decodes back 120x160x3, format "jpg" in the record
python scripts/tools/batch_image.py --out var/... tests/fixtures/casos normalize --quality 85
#   -> the page that read 17.04 now publishes 45.81, brightness 243.98 (paper still white),
#      transformations [] — nothing was applied, because nothing should be
```

Two sweeps, so no passage still claims a container the rule no longer fixes:

```bash
grep -rn 'normalized\.png\|ocr_ready\.png\|vlm_ready\.png' docs/plan/ scripts/tools/
grep -rn 'BRIGHTNESS_TARGET\|BRIGHTNESS_MAX' docs/plan/ src/docflow/
```

A hit is expected where a passage states the **default** container (`quality` absent), names
the binarized variant, or describes the band as a *flag*; a hit that still reads as "the
artifact is always `.png`" is a defect of this revision.
