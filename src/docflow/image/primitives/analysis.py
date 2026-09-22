"""Analysis primitives - reading technical facts off an image without changing it.

**Nothing in this module mutates its input.** Every function takes an array and returns numbers;
the transformations live in :mod:`docflow.image.primitives.transform`. That split is what lets
``IMG-06``'s ``analyze_image`` be side-effect free, which the WBS states as a property of that task
rather than a hope. The module imports no file-writing API at all, so "side-effect free" is
enforced by what it can reach, not only by what it chooses to do.

The numbers are measurements, not verdicts. Whether a blur score means "poor" is decided by the
classification stage, so a threshold that later needs tuning does not drag the measurement with it.

The array library is imported normally while the engine is not. That asymmetry is deliberate: numpy
is the vocabulary the primitives are written in - every metric here is arithmetic on an array that
could not have been produced without it - whereas the engine is a swappable choice that must stay
unloaded until something actually needs it. Importing this module therefore loads numpy, and the
package-level invariant that ``GEN-01`` guards is about engines, not about arrays.

Two limits are worth stating plainly, because they are properties of the problem rather than of
this implementation:

* **Orientation is coarse.** :func:`detect_orientation` distinguishes an upright page from a
  quarter-turned one by which axis the ink projects onto. It cannot tell a page from the same page
  upside down, because the ink projection of a 180-degree turn is identical. Resolving that needs a
  script detector or a classifier; both are out of bounds here (no OCR, no LLM), so the ambiguity is
  reported as the narrower answer rather than guessed at.
* **Skew is bounded.** :func:`detect_skew_angle` reports the tilt of the ink rectangle, so it is
  meaningful for the small residual rotations a scanner produces and not for arbitrary angles. It is
  folded into ``(-45, 45]`` for that reason.
"""

from __future__ import annotations

import numpy as np

from docflow.image.contracts import TextRegion
from docflow.image.primitives.engine import (
    EngineChoice,
    ImageArray,
    engine_operation,
)

INK_BLOCK_SIZE = 15
"""Neighbourhood, in pixels, used to decide whether a pixel is ink.

Passed to the engine's adaptive threshold. Adaptive rather than a single global cut because these
metrics are also computed on photographs and screenshots where the background brightness varies
across the frame.
"""

INK_CONSTANT = 9
"""Subtracted from the local mean when deciding ink, per the engine's convention."""

TEXT_REGION_KERNEL = (25, 9)
"""Closing kernel that merges individual strokes into word and line blocks.

Wide and short: strokes merge along a line of text but not between adjacent lines, so a paragraph
becomes one region per line rather than one region for the whole page.
"""

MORPH_RECT = "MORPH_RECT"
"""Name of the rectangular structuring element in the engine's namespace."""

MORPH_CLOSE = "MORPH_CLOSE"
"""Name of the closing operation in the engine's namespace.

Resolved by name rather than by literal because the two are integers in the engine's API and a
hand-copied value would be another `IMREAD_GRAYSCALE`-style mistake waiting to happen.
"""

MIN_TEXT_REGION_AREA = 64
"""Smallest blob counted as a text region, in pixels.

Below roughly an 8x8 block a blob is a speck, not a run of characters, and counting specks would
make ``text_coverage`` a measure of noise.

# TODO: [MVP] provisional - set from the fixtures, not from a labelled corpus.
"""

MIN_TEXT_REGION_FILL = 0.05
"""Smallest share of a candidate box that must be ink for it to count as text.

A region that is almost entirely background is a rectangle the closing step happened to produce
around scattered strokes, not a line of text.

# TODO: [MVP] provisional - see :data:`MIN_TEXT_REGION_AREA`.
"""

MIN_REGION_COVERAGE = 0.01
"""Regions covering less ink than this are dropped as noise.

Rounds the per-region coverage so an image with no text reports no regions rather than a handful of
one-pixel artefacts.

# TODO: [MVP] provisional.
"""

MIN_ORIENTATION_INEQUALITY = 1.5
"""How much larger one projection's variance must be before the page counts as turned.

A square-ish page whose ink happens to be balanced projects almost equally onto both axes, and
picking the larger of two nearly equal numbers would report an orientation decided by noise.

# TODO: [MVP] provisional.
"""

MIN_SKEW_LINE_LENGTH = 30
"""Shortest edge segment considered when estimating skew from line segments, in pixels.

Not read by :func:`detect_skew_angle`, which measures the ink rectangle instead because a line
finder can return a different subset of segments when anything upstream changes. Kept as the
documented value for the comparison, so a future change to line-based detection starts from the
number the subplan names rather than from a guess.

# TODO: [MVP] provisional.
"""

SKEW_FOLD_DEGREES = 90.0
"""Period of the skew measurement; an ink rectangle's tilt is only known within a quarter turn."""

SKEW_MAX_DEGREES = 45.0
"""Half of :data:`SKEW_FOLD_DEGREES`; readings beyond it fold back into the known range."""


def calculate_blur_score(image: ImageArray, engine: EngineChoice) -> float:
    """Measure how blurry an image is.

    The variance of the Laplacian: a sharp image has strong second derivatives at its edges, so the
    variance is high, and blurring suppresses them together.

    Args:
        image: The decoded pixels, RGB or grayscale.
        engine: The engine to measure with.

    Returns:
        The score. Zero means no detectable edge structure at all; higher means sharper. Same
        scale as :func:`calculate_sharpness_score` but not the same number.
    """
    gray = luminance(image, engine)
    return float(engine_operation(engine, "Laplacian")(gray, -1).var())


def calculate_sharpness_score(image: ImageArray, engine: EngineChoice) -> float:
    """Measure how sharp an image is.

    The mean squared gradient magnitude (Tenengrad). Related to :func:`calculate_blur_score` but
    dominated by the strongest edges rather than by their spread, so the two disagree on images with
    one high-contrast element and little else - which is why both are reported.

    Args:
        image: The decoded pixels, RGB or grayscale.
        engine: The engine to measure with.

    Returns:
        The score. Higher means sharper.
    """
    sobel = engine_operation(engine, "Sobel")
    gray = luminance(image, engine).astype(np.float32)
    horizontal = sobel(gray, -1, 1, 0, ksize=3)
    vertical = sobel(gray, -1, 0, 1, ksize=3)
    return float(np.mean(horizontal**2 + vertical**2))


def calculate_contrast_score(image: ImageArray, engine: EngineChoice) -> float:
    """Measure an image's global contrast.

    The standard deviation of luminance. A flat page of uniform colour scores near zero; a page of
    black text on white paper scores high.

    Args:
        image: The decoded pixels, RGB or grayscale.
        engine: The engine to measure with.

    Returns:
        The standard deviation, on the 0-255 luminance scale.
    """
    return float(luminance(image, engine).std())


def calculate_brightness_score(image: ImageArray, engine: EngineChoice) -> float:
    """Measure an image's mean luminance.

    Args:
        image: The decoded pixels, RGB or grayscale.
        engine: The engine to measure with.

    Returns:
        The mean, on the 0-255 luminance scale.
    """
    return float(luminance(image, engine).mean())


def calculate_noise_score(image: ImageArray, engine: EngineChoice) -> float:
    """Estimate how noisy an image is.

    A Laplacian-style mask whose weights sum to zero, so a smoothly varying region cancels out and
    what remains is the high-frequency component - sensor grain and compression artefacts. The
    estimate is deliberately independent of the mean brightness, so a dark scan is not reported as
    noisy for being dark.

    Args:
        image: The decoded pixels, RGB or grayscale.
        engine: The engine to measure with.

    Returns:
        The estimate. Zero means no high-frequency component was found; higher means noisier.
    """
    filter2d = engine_operation(engine, "filter2D")
    gray = luminance(image, engine).astype(np.float64)
    mask = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], dtype=np.float64)
    response = filter2d(gray, -1, mask)
    # Two border pixels are lost on each axis by the 3x3 pass; a fully degraded image is reported
    # as 0 rather than dividing by a non-positive area.
    interior = (gray.shape[1] - 2) * (gray.shape[0] - 2)
    if interior <= 0:
        return 0.0
    return float(np.sqrt(np.pi / 2) * np.abs(response).sum() / (6 * interior))


def detect_orientation(image: ImageArray, engine: EngineChoice) -> int:
    """Estimate how far a page is turned from upright.

    Compares how strongly the ink projects onto each axis: an upright page of text forms dark rows
    separated by light ones, so its row projection varies a great deal, whereas a quarter-turned
    page has that structure along the columns instead.

    Only the quarter-turn is resolved. A page and the same page upside down project identically, so
    reading the difference would take a script detector or a classifier and both are out of bounds
    for this processor. The narrower answer is reported rather than a guess.

    Args:
        image: The decoded pixels, RGB or grayscale.
        engine: The engine to measure with.

    Returns:
        ``0`` when the page reads as upright, ``90`` when it reads as quarter-turned. The value is
        the rotation already applied to the page, so it is the angle that *describes* the input
        rather than a correction to apply.
    """
    mask = ink_mask(image, engine)
    row_variance = float(np.var(mask.sum(axis=1, dtype=np.float64)))
    column_variance = float(np.var(mask.sum(axis=0, dtype=np.float64)))
    if row_variance <= 0.0 and column_variance <= 0.0:
        return 0
    larger, smaller = (
        max(row_variance, column_variance),
        min(row_variance, column_variance),
    )
    if smaller <= 0.0 or larger / smaller >= MIN_ORIENTATION_INEQUALITY:
        return 0 if row_variance >= column_variance else 90
    return 0


def detect_skew_angle(image: ImageArray, engine: EngineChoice) -> float:
    """Measure how far a page has tilted from horizontal.

    The tilt of the smallest rotated rectangle that encloses the ink. The reading is a property of
    the ink's own bounding shape, so it is stable across repeated runs on the same bytes - unlike a
    line-finder, which can return a different subset of segments when anything upstream changes.

    Args:
        image: The decoded pixels, RGB or grayscale.
        engine: The engine to measure with.

    Returns:
        The tilt in degrees, folded into ``(-45, 45]``. The sign matches the rotation that corrects
        it - rotating by the *returned* value straightens the page, established by measuring the
        engine rather than by reasoning about the sign. Zero means no measurable tilt, including on
        an image with no ink at all.
    """
    min_area_rect = engine_operation(engine, "minAreaRect")
    rows, columns = np.nonzero(ink_mask(image, engine))
    if columns.size == 0:
        return 0.0
    points = np.column_stack([columns, rows]).astype(np.float32)
    _, _, angle = min_area_rect(points)
    return _fold_skew(float(angle))


def detect_text_regions(
    image: ImageArray, engine: EngineChoice, *, region_prefix: str = "r"
) -> tuple[TextRegion, ...]:
    """Locate the rectangles that appear to hold text.

    Individual strokes are merged into word and line blocks, then each block becomes a region.
    Results are ordered top-to-bottom then left-to-right, so the tuple is stable for the same input
    and two runs can be compared directly rather than as sets.

    Args:
        image: The decoded pixels, RGB or grayscale.
        engine: The engine to detect with.
        region_prefix: Prefix for the generated region identifiers, so a caller can tell regions
            from different images apart when it keeps them in one mapping.

    Returns:
        The regions, ordered by position. Empty when the image carries no ink worth reporting.

    # TODO: [MVP] provisional thresholds; see MIN_TEXT_REGION_AREA and its neighbours.
    """
    blocks = _text_blocks(image, engine)
    candidates = _text_candidates(blocks, ink_mask(image, engine), engine)

    return tuple(
        TextRegion(
            region_id=f"{region_prefix}{order}",
            bbox=(float(left), float(top), float(width), float(height)),
            text_coverage=coverage,
        )
        for order, (top, left, width, height, coverage) in enumerate(candidates)
    )


def _text_blocks(image: ImageArray, engine: EngineChoice) -> ImageArray:
    """Merge individual strokes into word and line blocks.

    Args:
        image: The decoded pixels, RGB or grayscale.
        engine: The engine to process with.

    Returns:
        A binary array of merged blocks.
    """
    structuring = engine_operation(engine, "getStructuringElement")
    morphology = engine_operation(engine, "morphologyEx")
    kernel = structuring(engine_operation(engine, MORPH_RECT), TEXT_REGION_KERNEL)
    return morphology(
        ink_mask(image, engine), engine_operation(engine, MORPH_CLOSE), kernel
    )


def _text_candidates(
    blocks: ImageArray, mask: ImageArray, engine: EngineChoice
) -> list[tuple[int, int, int, int, float]]:
    """Return the blocks that look like text, ordered by position.

    Each entry is ``(top, left, width, height, coverage)``.

    Args:
        blocks: The merged blocks from :func:`_text_blocks`.
        mask: The unmerged ink mask, for measuring how much of a block is really ink.
        engine: The engine to measure with.

    Returns:
        The accepted candidates, sorted top-to-bottom then left-to-right.
    """
    connected = engine_operation(engine, "connectedComponentsWithStats")
    count, _, stats, _ = connected(blocks, connectivity=8)

    candidates: list[tuple[int, int, int, int, float]] = []
    for index in range(1, count):
        left, top, width, height, area = (int(value) for value in stats[index])
        if area < MIN_TEXT_REGION_AREA:
            continue
        coverage = _region_coverage(mask, left, top, width, height)
        if coverage < MIN_TEXT_REGION_FILL or coverage < MIN_REGION_COVERAGE:
            continue
        candidates.append((top, left, width, height, coverage))
    candidates.sort()
    return candidates


def calculate_text_coverage(
    image: ImageArray, engine: EngineChoice, regions: tuple[TextRegion, ...]
) -> float:
    """Measure how much of an image is text.

    Takes the regions rather than recomputing them, so one detection pass serves both the
    ``text_regions`` record and this figure, and the two agree by construction instead of by two
    independent measurements happening to match.

    Args:
        image: The decoded pixels, RGB or grayscale.
        engine: The engine to measure with.
        regions: The regions from :func:`detect_text_regions`.

    Returns:
        Ink pixels over total pixels in the reported regions, 0.0 to 1.0 inclusive. Image-wide ink
        that fell outside every region is excluded, because this figure answers "how much text is
        here", not "how many dark pixels are here".
    """
    _ = engine
    if not regions:
        return 0.0
    height, width = image.shape[0], image.shape[1]
    total = height * width
    if total <= 0:
        return 0.0
    covered = sum(
        region.text_coverage * region.bbox[2] * region.bbox[3] for region in regions
    )
    return float(min(1.0, max(0.0, covered / total)))


def luminance(image: ImageArray, engine: EngineChoice) -> ImageArray:
    """Reduce an image to a single luminance channel.

    Every quality score in this module is defined on luminance, so they share this one conversion
    and cannot disagree about what "the image" means for a colour input.

    Args:
        image: The decoded pixels, RGB or grayscale.
        engine: The engine to convert with.

    Returns:
        A single-channel array; an already-grayscale input is returned unchanged.
    """
    if image.ndim == 2:
        return image
    convert = engine_operation(engine, "cvtColor")
    return convert(image, engine_operation(engine, "COLOR_RGB2GRAY"))


def ink_mask(image: ImageArray, engine: EngineChoice) -> ImageArray:
    """Mark the pixels that look like ink.

    An adaptive threshold against the local mean, so a page that is dark on one side and light on
    the other is measured by its local contrast rather than by one global cut.

    One consequence is worth stating because it surprises people reading the result: a **solid dark
    block only has its edges marked**. Inside a large uniform region every pixel sits at the local
    mean, so no pixel is *more* than the mean subtracted by :data:`INK_CONSTANT` and the interior is
    left clear. A thin stroke - text, a line, a rule - is narrower than the block size and so is
    marked through its whole width.

    That is the property this module wants. Text detection cares about strokes; a solid colour bar
    or a photographic shadow is not text, and counting its interior as ink would inflate
    ``text_coverage`` on exactly the pages where the distinction matters.

    Args:
        image: The decoded pixels, RGB or grayscale.
        engine: The engine to threshold with.

    Returns:
        A binary array: 255 where ink was found, 0 elsewhere.
    """
    threshold = engine_operation(engine, "adaptiveThreshold")
    return threshold(
        luminance(image, engine),
        255,
        engine_operation(engine, "ADAPTIVE_THRESH_MEAN_C"),
        engine_operation(engine, "THRESH_BINARY_INV"),
        INK_BLOCK_SIZE,
        INK_CONSTANT,
    )


def _region_coverage(
    mask: ImageArray, left: int, top: int, width: int, height: int
) -> float:
    """Return the share of a rectangle that is ink.

    Args:
        mask: The binary ink mask.
        left: Rectangle origin on the x axis.
        top: Rectangle origin on the y axis.
        width: Rectangle width in pixels.
        height: Rectangle height in pixels.

    Returns:
        Ink pixels over box pixels, 0.0 to 1.0.
    """
    box = mask[top : top + height, left : left + width]
    return float(np.count_nonzero(box) / box.size) if box.size else 0.0


def _fold_skew(angle: float) -> float:
    """Fold a rectangle tilt into ``(-45, 45]``.

    Args:
        angle: The tilt as the engine reports it, in ``(0, 90]``.

    Returns:
        The equivalent tilt within a quarter turn, signed.
    """
    folded = angle % SKEW_FOLD_DEGREES
    if folded > SKEW_MAX_DEGREES:
        folded -= SKEW_FOLD_DEGREES
    return float(folded)


__all__ = [
    "INK_BLOCK_SIZE",
    "INK_CONSTANT",
    "MIN_ORIENTATION_INEQUALITY",
    "MIN_REGION_COVERAGE",
    "MIN_SKEW_LINE_LENGTH",
    "MIN_TEXT_REGION_AREA",
    "MIN_TEXT_REGION_FILL",
    "TEXT_REGION_KERNEL",
    "calculate_blur_score",
    "calculate_brightness_score",
    "calculate_contrast_score",
    "calculate_noise_score",
    "calculate_sharpness_score",
    "calculate_text_coverage",
    "detect_orientation",
    "detect_skew_angle",
    "detect_text_regions",
    "ink_mask",
    "luminance",
]
