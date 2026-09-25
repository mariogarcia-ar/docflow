"""Measured facts, the thresholds that judge them, and the descriptive names derived.

Three jobs, all of them ours and none of them the engine's:

* :class:`ImageFileFacts` is what one decode and the file itself report — the data shape the
  seam hands to :func:`docflow.image.primitives.analyze_image`.
* the thresholds are the *decisions* about what counts as usable: a blur floor, a contrast
  floor, a text-coverage floor and the OCR/VLM tuning values. They are named constants, never
  a library default and never a value smuggled in from a caller.
* :func:`build_text_regions`, :func:`calculate_text_coverage`, :func:`is_low_quality` and
  :func:`classify_image` derive names and shares from measurements alone. They read no
  ``context``, touch no engine and decide nothing about what should happen next: the
  orchestrator owns every routing decision.

Every quality score is in the engine's own 8-bit pixel units (0..255), so one set of
thresholds is comparable across the five readings. ``blur`` is the variance of the Laplacian,
which **falls** when an image is blurred — the field keeps the contract's name and the rule
below reads it as a floor.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from docflow.image.contracts import ImageClassification, ImageMetrics, TextRegion

#: A bounding box: ``(left, top, right, bottom)``, in pixels.
BBox = tuple[float, float, float, float]

# --- Quality floors and ceilings ---------------------------------------------------
# TODO: [MVP] provisional PoC values, fixed so that a clean text-like page is not reported
# as LOW_QUALITY. They are decisions about legibility, so they are revisited against the
# corpus at the MVP gate; a library default standing in for one would be a silent stand-in.

#: Minimum variance of the Laplacian. Below this the image carries too little detail.
BLUR_MIN: Final[float] = 5.0

#: Minimum mean gradient magnitude — the Tenengrad-style sharpness floor.
SHARPNESS_MIN: Final[float] = 1.0

#: Minimum standard deviation of the grey image: below this there is no usable contrast.
CONTRAST_MIN: Final[float] = 12.0

#: Maximum mean deviation from the local median: above this the image is too noisy.
NOISE_MAX: Final[float] = 40.0

#: Brightness band, in grey levels. Outside it the page is underexposed or washed out.
BRIGHTNESS_MIN: Final[float] = 20.0
BRIGHTNESS_MAX: Final[float] = 240.0

#: The brightness the normalization aims at when the band is missed.
BRIGHTNESS_TARGET: Final[float] = (BRIGHTNESS_MIN + BRIGHTNESS_MAX) / 2.0

# --- Text detection ----------------------------------------------------------------

#: Kernel size of the closing that joins a word's glyphs into one region, in pixels. Three is
#: the smallest size that closes a gap; a wider kernel merges neighbouring lines.
TEXT_REGION_KERNEL: Final[int] = 3

#: Region area below which a detection is speckle rather than text, in square pixels.
MIN_REGION_AREA: Final[int] = 40

#: Grey level below which a pixel counts as ink, not background.
INK_THRESHOLD: Final[float] = 160.0

#: The value every ink or binary mask is written with.
INK_MAX_VALUE: Final[float] = 255.0

#: Text coverage at or above which the text layer is too sparse to be worth reading.
TEXT_COVERAGE_MIN: Final[float] = 0.02

#: Coverage at or above which the text layer carries the image by itself.
TEXT_DOMINANT_COVERAGE: Final[float] = 0.15

# --- Transformation tuning ---------------------------------------------------------

#: Skew below which deskewing is not justified: rotating by a fraction of a degree costs a
#: resample and buys nothing.
DESKEW_MIN_ANGLE: Final[float] = 0.5

#: Grey the deskewed page is filled with — a page is white, not black (the engine's own
#: border default would leave black wedges).
DESKEW_BORDER_VALUE: Final[tuple[int, int, int]] = (255, 255, 255)

#: CLAHE parameters for the contrast normalization of a grey page.
CONTRAST_CLIP_LIMIT: Final[float] = 2.0
CONTRAST_TILE_GRID_SIZE: Final[tuple[int, int]] = (8, 8)

#: Non-local-means denoising parameters.
DENOISE_STRENGTH: Final[float] = 8.0
DENOISE_TEMPLATE_WINDOW: Final[int] = 7
DENOISE_SEARCH_WINDOW: Final[int] = 21

#: Unsharp-mask parameters: kernel, sigma and the weight of the subtracted blur.
SHARPEN_KERNEL: Final[int] = 3
SHARPEN_SIGMA: Final[float] = 1.5
SHARPEN_AMOUNT: Final[float] = 0.6

#: Window of the median filter the noise score is measured against.
NOISE_MEDIAN_KERNEL: Final[int] = 3

#: Adaptive binarization parameters for the OCR variant. Explicit, because an engine-computed
#: threshold (Otsu) is a value nobody recorded.
OCR_BINARIZE_BLOCK_SIZE: Final[int] = 35
OCR_BINARIZE_C: Final[float] = 15.0

#: Longest edge a VLM variant keeps. A larger image is resized to fit: the VLM's context is
#: bounded, and downscaling is the only correction that buys anything there.
VLM_MAX_DIMENSION: Final[int] = 2000


@dataclass(frozen=True)
class ImageFileFacts:
    """What the file and the engine's decode report about one image.

    Attributes:
        path: Where the source image is.
        format: Container format, taken from the file's suffix, lower-case and without the
            dot.
        size: Size in bytes.
        width: Width in pixels, as the decoded array reports it.
        height: Height in pixels.
        channels: Channel count of the decoded array.
        resolution: Resolution in DPI, or ``None`` when it cannot be read. The engine
            decodes pixels and reports no density, so this is ``None`` for OpenCV: ``None``
            states "not measured" where a default 300 would be an invented answer.
    """

    path: Path
    format: str
    size: int
    width: int
    height: int
    channels: int
    resolution: int | None


def build_text_regions(measured: Sequence[tuple[BBox, float]]) -> list[TextRegion]:
    """Name the detected text regions in reading order.

    Reading order is ours, not OpenCV's: the regions are sorted top to bottom and, within a
    line's band, left to right, and each is given an index-derived identifier, so two runs
    over the same image produce the same names in the same order.

    Args:
        measured: One ``(bbox, coverage)`` pair per detected region, in whatever order the
            engine returned its contours.

    Returns:
        The regions, ordered and named deterministically.
    """
    ordered = sorted(measured, key=lambda item: (item[0][1], item[0][0]))
    return [
        TextRegion(region_id=f"region_{index:03d}", bbox=box, text_coverage=coverage)
        for index, (box, coverage) in enumerate(ordered, start=1)
    ]


def calculate_text_coverage(
    regions: Sequence[TextRegion], width: int, height: int
) -> float:
    """Return the share of the image the detected text regions occupy.

    The measure is ours and it is an *upper bound*: the areas are summed rather than
    unioned, so overlapping regions count twice, and the total is clamped to the whole
    image. Measuring the true union would need rectangle intersection for no decision that
    depends on the difference.

    Args:
        regions: The detected regions.
        width: Image width in pixels.
        height: Image height in pixels.

    Returns:
        A share in ``0.0..1.0``; ``0.0`` when nothing was detected or the image has no area.
    """
    if width <= 0 or height <= 0:
        return 0.0
    page_area = float(width) * float(height)
    covered = sum(
        max(0.0, region.bbox[2] - region.bbox[0])
        * max(0.0, region.bbox[3] - region.bbox[1])
        for region in regions
    )
    return min(1.0, covered / page_area)


def is_low_quality(metrics: ImageMetrics) -> bool:
    """Return whether the readings fall outside the usable bands.

    Args:
        metrics: The image's measured quality.

    Returns:
        ``True`` when a floor is missed or a ceiling is exceeded. The reading only names a
        technical state; the orchestrator decides what to do with it.
    """
    quality = metrics.quality
    return (
        quality.blur < BLUR_MIN
        or quality.sharpness < SHARPNESS_MIN
        or quality.contrast < CONTRAST_MIN
        or quality.noise > NOISE_MAX
        or not BRIGHTNESS_MIN <= quality.brightness <= BRIGHTNESS_MAX
    )


def classify_image(metrics: ImageMetrics) -> ImageClassification:
    """Name what the measurements say about the image.

    The classification is descriptive data in the result. It is derived from the metrics
    alone — never from ``context``, a workflow flag or a caller's instruction — and it is the
    orchestrator, not this function, that turns it into a decision.

    Args:
        metrics: The image's measured composition.

    Returns:
        ``"LOW_QUALITY"`` when a quality floor is missed, which takes precedence: a degraded
        image is not usefully described as text or as a picture. Otherwise ``"TEXT_IMAGE"``,
        ``"MIXED_IMAGE"`` or ``"VISUAL_IMAGE"``, by how much of the image the detected text
        occupies.
    """
    if is_low_quality(metrics):
        return "LOW_QUALITY"
    if metrics.text_coverage >= TEXT_DOMINANT_COVERAGE:
        return "TEXT_IMAGE"
    if metrics.text_coverage >= TEXT_COVERAGE_MIN:
        return "MIXED_IMAGE"
    return "VISUAL_IMAGE"
