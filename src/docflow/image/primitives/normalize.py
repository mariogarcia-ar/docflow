"""The baseline normalization pipeline, and the publication of its artifact.

This is the first module in the image processor that writes a file. Two properties shape it, and
both come from the plan's risk table:

* **Only justified transformations.** "Over-eager enhancement degrades information" - binarization
  destroying colour is the example the plan gives - and the answer it prescribes is "apply
  transformations only when justified by metrics + explicit options". So every decision here reads a
  measured number or an explicit flag. Nothing is applied because it might help.
* **Every application is recorded.** :func:`normalize_image` returns the pixels *and* the ordered
  names of what it did, so ``ImageResult.transformations`` is produced by the same pass that made
  the changes rather than reconstructed afterwards from what someone remembers applying.

The pipeline is deliberately short: orientation, deskew, exposure. Denoising and sharpening are
quality operations whose benefit depends on a judgement this processor is not entitled to make yet,
and applying them unrequested is exactly the over-enhancement the plan names. They remain available
as primitives for a caller that asks.

The split between the two public functions is *decide* and *publish*. :func:`normalize_image` is
pure and returns arrays; :func:`prepare_normalized_image` is the only thing that touches the
filesystem. That keeps the decision testable without a temporary directory and keeps the write in
one place for ``IMG-11`` to replace with atomic staging.
"""

from __future__ import annotations

from pathlib import Path

from docflow.image.contracts import ArtifactRef, ImageMetrics, ImageOptions
from docflow.image.primitives.analysis import (
    calculate_brightness_score,
    calculate_contrast_score,
)
from docflow.image.primitives.engine import EngineChoice, ImageArray
from docflow.image.primitives.failures import ImagePrimitiveError
from docflow.image.primitives.load import get_image_dimensions, save_image
from docflow.image.primitives.transform import (
    deskew_image,
    normalize_brightness,
    normalize_contrast,
    turn_quarter,
)

NORMALIZED_FILE_NAME = "normalized.png"
"""Name of the baseline artifact inside the ``image/`` namespace."""

NORMALIZED_ARTIFACT_KIND = "normalized"
"""Artifact kind recorded for it, one of the contract's ``ImageArtifactKind`` values."""

MIN_ACCEPTABLE_BRIGHTNESS = 100.0
"""Mean luminance below which a page is too dark to be an ordinary document.

Set from measurement rather than from taste. A document is mostly white paper, so its mean is
naturally high: the three committed fixtures measure 183, 220 and 212. Scaling one down simulates an
underexposed scan and gives 146, 110, 91, 73, 55, 37 for factors of 0.8 down to 0.2. A cut at 100
leaves every ordinary page alone and intervenes from roughly half exposure downwards.

# TODO: [MVP] provisional - set from the fixtures, not from a labelled corpus.
"""

TARGET_BRIGHTNESS = 128.0
"""Mean luminance an underexposed page is lifted towards, on the 0-255 scale."""

MIN_ACCEPTABLE_CONTRAST = 45.0
"""Luminance spread below which text and paper are too close to separate comfortably.

Also taken from measurement: the fixtures spread 78 to 98, an underexposed page at half exposure
spreads 49, and a washed-out page - one scaled down and lifted against a bright floor
- spreads 39 however bright that floor is. A cut at 45 sits between the two groups with
room on both sides.

# TODO: [MVP] provisional - see :data:`MIN_ACCEPTABLE_BRIGHTNESS`.
"""

TRANSFORMATION_ORIENTATION = "turn_quarter"
TRANSFORMATION_DESKEW = "deskew_image"
TRANSFORMATION_CONTRAST = "normalize_contrast"
TRANSFORMATION_BRIGHTNESS = "normalize_brightness"
"""Names recorded in ``ImageResult.transformations``.

They are the primitive names, so the record points at the code that ran. A caller reading
``"normalize_brightness"`` can find the function that did it without a translation table.
"""


def normalize_image(
    image: ImageArray,
    metrics: ImageMetrics,
    options: ImageOptions,
    engine: EngineChoice,
) -> tuple[ImageArray, tuple[str, ...]]:
    """Apply the baseline normalization a set of measurements and flags justifies.

    The corrections run in a fixed order, and the order is load-bearing:

    1. **Orientation.** A quarter turn first, because skew is measured relative to the page's own
       axes - correcting a tilt before turning the page would leave the tilt re-introduced by the
       turn.
    2. **Skew.** Then the residual tilt.
    3. **Exposure.** Contrast, then brightness. Contrast first so the stretch is computed on the
       pixel range the page actually has, rather than on one an offset has already shifted.

    Args:
        image: The decoded pixels, in RGB order or grayscale. Not modified.
        metrics: The snapshot from ``analyze_image``, used to decide and never re-measured.
        options: The caller's explicit request. ``normalize`` gates the whole pipeline;
            ``correct_orientation`` and ``deskew`` gate their individual corrections.
        engine: The engine to transform with.

    Returns:
        The normalized pixels and the names of the transformations applied, in the order they ran.
        Empty when ``normalize`` is false, in which case the image is returned unchanged.

    Raises:
        ImageEngineNotAvailableError: The engine or array library is missing.
        ImageEngineCapabilityError: The engine lacks a required operation.
        ImagePrimitiveError: A correction cannot be applied.
    """
    if not options.normalize:
        return image, ()

    working = image
    applied: list[str] = []

    if options.correct_orientation and metrics.orientation:
        working = turn_quarter(working, _quarter_turns_for(metrics.orientation))
        applied.append(TRANSFORMATION_ORIENTATION)

    if options.deskew and metrics.skew:
        working = deskew_image(working, metrics.skew, engine)
        applied.append(TRANSFORMATION_DESKEW)

    working, used = _correct_exposure(working, metrics, engine)
    applied.extend(used)

    return working, tuple(applied)


def prepare_normalized_image(
    image: ImageArray,
    output_dir: Path,
    options: ImageOptions,
    transformations: tuple[str, ...],
    engine: EngineChoice,
) -> ArtifactRef | None:
    """Publish the normalized image into the ``image/`` namespace.

    Writes nothing when ``normalize`` is false: the WBS requires that a run which did not
    ask for the artifact produces no artifact **and raises no error**, so the absent thing is
    reported as ``None`` rather than as a failure. That is the convention ``ImageVariants``
    uses, where ``None`` means "not requested" and never "requested and missing".

    Args:
        image: The normalized pixels, from :func:`normalize_image`.
        output_dir: The ``image/`` directory to write into. This module never chooses it, so
            ownership of the namespace stays with the caller.
        options: The caller's explicit request.
        transformations: What :func:`normalize_image` applied, for context in the failure path.
        engine: The engine to encode with.

    Returns:
        A reference to the written file, or ``None`` when normalization was not requested.

    Raises:
        ImageEngineNotAvailableError: The engine is missing.
        ImagePrimitiveError: The write fails, with the transformations this run had applied carried
            into the failure's context so it points at the run that produced it.

    # TODO: [MVP] writes in place; ``IMG-11`` routes this through ``image/.tmp/`` and a rename, so a
    # failure part-way leaves no artifact under its final name.
    """
    if not options.normalize:
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / NORMALIZED_FILE_NAME
    if destination.exists():
        # A previous run's artifact. Removed explicitly rather than overwritten silently, because
        # `save_image` refuses an occupied destination and that refusal is a real safety property.
        destination.unlink()

    try:
        save_image(image, destination, engine)
    except ImagePrimitiveError as failure:
        failure.detail["transformations"] = list(transformations)
        raise
    dimensions = get_image_dimensions(image, engine)
    return ArtifactRef(
        path=destination,
        kind=NORMALIZED_ARTIFACT_KIND,
        width=dimensions.width,
        height=dimensions.height,
        format=destination.suffix.lstrip(".").upper(),
        size=destination.stat().st_size,
    )


def _quarter_turns_for(orientation: int) -> int:
    """Return the quarter turns that undo a detected orientation.

    Only the magnitude is decided here, and deliberately so. A reading of 90 says the page is
    quarter-turned but cannot say *which way*: turning it one way or the other both leave a page
    whose ink projects along the rows, and the detector - which resolves orientation from the ink
    projection and nothing else - cannot tell the two apart. Distinguishing them is the same
    180-degree ambiguity its own documentation records, and it would take a script detector or a
    classifier, both out of bounds for this processor. The turn is applied in the direction that
    needs no such knowledge.

    Args:
        orientation: The reading from ``detect_orientation``, in degrees.

    Returns:
        Quarter turns to apply.

    Raises:
        ValueError: The reading is not a quarter turn the detector can produce.
    """
    if orientation == 0:
        return 0
    if orientation == 90:
        return 1
    raise ValueError(
        f"detect_orientation reported {orientation!r}, which is not one of its values; "
        "a reading outside them means the detector and this pipeline disagree"
    )


def _correct_exposure(
    image: ImageArray, metrics: ImageMetrics, engine: EngineChoice
) -> tuple[ImageArray, list[str]]:
    """Correct a page whose exposure the measurements say is poor.

    Corrects **underexposure only**. A page whose mean luminance is high is bright because most
    of it is white paper, which is what a document looks like; pulling such a page down towards the
    midpoint would turn paper grey and cost contrast for nothing. The washed-out case - a page that
    is bright *and* flat, with the mean held up by a raised floor rather than by
    paper - is caught by the contrast measure instead, which is why the two corrections are
    separate and why neither reads the other's threshold.

    A caveat worth stating, because the contrast correction looks more effective than it
    is: on a genuinely washed-out page, where the information was compressed at capture,
    the contrast-limited stretch recovers almost nothing. Measured, a page lifted against a
    bright floor spreads 39.05 before and 39.70 after. The transformation is applied
    because the measurement says the page needs it and because it costs nothing; it is
    recorded as applied rather than as successful, and no field claims the page got better.

    Args:
        image: The pixels to correct.
        metrics: The snapshot from ``analyze_image``.
        engine: The engine to transform with.

    Returns:
        The corrected pixels and the names of the transformations applied, in order.
    """
    working = image
    applied: list[str] = []

    # Contrast first: stretching the range the page already has, before an offset moves it.
    if metrics.quality.contrast < MIN_ACCEPTABLE_CONTRAST:
        working = normalize_contrast(working, engine)
        applied.append(TRANSFORMATION_CONTRAST)

    # Re-measured on the corrected pixels rather than read from the stale snapshot, so a contrast
    # stretch that already lifted the mean does not then get an offset it no longer needs.
    brightness = calculate_brightness_score(working, engine)
    if brightness < MIN_ACCEPTABLE_BRIGHTNESS:
        working = normalize_brightness(working, engine, TARGET_BRIGHTNESS)
        applied.append(TRANSFORMATION_BRIGHTNESS)

    return working, applied


def measure_normalized(image: ImageArray, engine: EngineChoice) -> dict[str, float]:
    """Return the exposure figures the pipeline decides on, for a test or a metadata record.

    Args:
        image: The pixels to measure.
        engine: The engine to measure with.

    Returns:
        Brightness and contrast, keyed by name. Both are measurements; neither is a verdict.
    """
    return {
        "brightness": calculate_brightness_score(image, engine),
        "contrast": calculate_contrast_score(image, engine),
    }


__all__ = [
    "MIN_ACCEPTABLE_BRIGHTNESS",
    "MIN_ACCEPTABLE_CONTRAST",
    "NORMALIZED_ARTIFACT_KIND",
    "NORMALIZED_FILE_NAME",
    "TARGET_BRIGHTNESS",
    "TRANSFORMATION_BRIGHTNESS",
    "TRANSFORMATION_CONTRAST",
    "TRANSFORMATION_DESKEW",
    "TRANSFORMATION_ORIENTATION",
    "measure_normalized",
    "normalize_image",
    "prepare_normalized_image",
]
