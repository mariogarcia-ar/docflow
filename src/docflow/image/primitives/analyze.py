"""Aggregation of the analysis primitives into one ``ImageMetrics`` snapshot.

``analyze_image`` is the single entry point the rest of the processor uses to learn what an image
is: classification, the normalisation pipeline's decisions and validation all read its result rather
than calling the measuring primitives themselves. Keeping that funnel narrow is what lets the
measurements change without every consumer changing with them.

It sits above :mod:`docflow.image.primitives.analysis` rather than inside it because it is the first
primitive whose job is *assembly* rather than measurement, and it is the first that needs both the
pixels and the file. The measurements stay in ``analysis``; this module decides which of them the
contract wants and in what shape.

Like the layer beneath it, nothing here writes anything. The only file access is a read of the
technical facts, which :func:`docflow.image.primitives.load.get_image_metadata` performs and which
this module does not repeat.
"""

from __future__ import annotations

from pathlib import Path

from docflow.image.contracts import ImageMetrics, ImageQualityMetrics
from docflow.image.primitives.analysis import (
    calculate_blur_score,
    calculate_brightness_score,
    calculate_contrast_score,
    calculate_noise_score,
    calculate_sharpness_score,
    calculate_text_coverage,
    detect_orientation,
    detect_skew_angle,
    detect_text_regions,
)
from docflow.image.primitives.engine import EngineChoice, ImageArray
from docflow.image.primitives.load import get_image_dimensions, get_image_metadata


def analyze_image(image: ImageArray, path: Path, engine: EngineChoice) -> ImageMetrics:
    """Measure an image and return a complete :class:`ImageMetrics` snapshot.

    Every field carries a measurement. ``resolution`` and ``orientation`` are the two that can
    legitimately be ``None`` or zero by contract: a format that declares no resolution has none to
    report, and ``None`` is how the contract distinguishes that from a measured zero. Nothing is
    filled in with a placeholder - the plan's ``Out of bounds`` for this task says so directly, and
    each field here traces to a primitive that returned it.

    Args:
        image: The decoded pixels, in RGB order or grayscale.
        path: The file the pixels came from. Read for its technical facts, never written.
        engine: The engine that decoded the image and will measure it.

    Returns:
        The measured snapshot.

    Raises:
        ImageEngineNotAvailableError: The engine or array library is missing.
        ImageEngineCapabilityError: The engine lacks a required operation.
        ImagePrimitiveError: The file cannot be read, or the pixels cannot be measured.
    """
    facts = get_image_metadata(path, engine)
    dimensions = get_image_dimensions(image, engine)
    regions = detect_text_regions(image, engine)

    return ImageMetrics(
        dimensions=dimensions,
        resolution=facts.resolution,
        format=facts.format,
        size=facts.size,
        quality=ImageQualityMetrics(
            blur=calculate_blur_score(image, engine),
            sharpness=calculate_sharpness_score(image, engine),
            contrast=calculate_contrast_score(image, engine),
            brightness=calculate_brightness_score(image, engine),
            noise=calculate_noise_score(image, engine),
        ),
        orientation=detect_orientation(image, engine),
        skew=detect_skew_angle(image, engine),
        # A list, because the contract declares one; the detector returns a tuple so it is stable.
        text_regions=list(regions),
        text_coverage=calculate_text_coverage(image, engine, regions),
    )


__all__ = [
    "analyze_image",
]
