"""Analysis primitives - reading quality facts off an image without changing it.

**Nothing in this module mutates its input.** Every function takes an image and returns
numbers; the transformations live in :mod:`docflow.image.primitives.transform`. That split is
what lets ``IMG-06``'s ``analyze_image`` be side-effect free, which the WBS states as a
property of that task rather than a hope.

The scores are the engine's, computed with the named constants below. They are threshold
inputs, not verdicts: whether a score means "poor" is decided in the classification stage, so
a threshold that later needs tuning does not drag the measurement with it.
"""

from __future__ import annotations

# pylint: disable=duplicate-code
# IMG-02's deliverable IS a skeleton: the measuring and transforming primitives share one
# docstring shape and one `raise NotImplementedError` body, by design - a surface whose every
# entry reads the same is reviewable in a single pass. The real bodies have nothing in common (a
# blur score and a rotation share no logic), so there is no helper to extract yet; IMG-04 and
# IMG-05 replace each body with distinct code and this disable goes with the last of them. Scoped
# to the three skeleton modules rather than to the config, so the rule still guards every other
# module in the project.
from dataclasses import dataclass
from types import ModuleType

from docflow.image.primitives.engine import EngineChoice

BINARIZATION_THRESHOLD = 128
"""Luminance cut for binarization, on the engine's 0-255 scale.

A named constant because ``IMG-08`` documents the numeric thresholds before coding starts and
an unnamed literal in the middle of a call is not documentable.
"""

ORIENTATION_METHOD = "osd"
"""How orientation is decided when a printed page is the input.

``osd`` is "orientation and script detection", the engine's own detector. Named so the method
travels with the angle into ``ImageMetrics.orientation`` rather than being implied.
"""

LAPLACIAN_KERNEL_SIZE = 3
"""Kernel edge for the Laplacian used as the blur measure.

Must be odd and positive; the engine rejects an even one, so the constant is odd by
construction rather than by comment.
"""


@dataclass(frozen=True)
class TextRegion:
    """A rectangle the analyzer believes holds text.

    Attributes:
        region_id: Stable identifier, unique within one image.
        bbox: Bounding box as ``(x, y, width, height)`` in pixels.
        text_coverage: Share of the box the analyzer judged to be text, 0.0-1.0.
    """

    region_id: str
    bbox: tuple[int, int, int, int]
    text_coverage: float


@dataclass(frozen=True)
class OrientationReading:
    """A page orientation reading and the method that produced it.

    Attributes:
        angle: Degrees to rotate by to correct the page; 0 means upright.
        method: The detector used, e.g. :data:`ORIENTATION_METHOD`.
    """

    angle: int
    method: str


def calculate_blur_score(image: ModuleType, engine: EngineChoice) -> float:
    """Measure how blurry an image is.

    Args:
        image: The engine-native image.
        engine: The engine that produced it.

    Returns:
        The variance of the Laplacian: lower means blurrier.

    # TODO: [MVP] compute for real; the skeleton raises.
    """
    raise NotImplementedError


def calculate_sharpness_score(image: ModuleType, engine: EngineChoice) -> float:
    """Measure how sharp an image is.

    Args:
        image: The engine-native image.
        engine: The engine that produced it.

    Returns:
        The sharpness measure, on the same scale as :func:`calculate_blur_score`.

    # TODO: [MVP] compute for real; the skeleton raises.
    """
    raise NotImplementedError


def calculate_contrast_score(image: ModuleType, engine: EngineChoice) -> float:
    """Measure an image's global contrast.

    Args:
        image: The engine-native image.
        engine: The engine that produced it.

    Returns:
        The standard deviation of luminance.

    # TODO: [MVP] compute for real; the skeleton raises.
    """
    raise NotImplementedError


def calculate_brightness_score(image: ModuleType, engine: EngineChoice) -> float:
    """Measure an image's mean luminance.

    Args:
        image: The engine-native image.
        engine: The engine that produced it.

    Returns:
        The mean luminance on the engine's 0-255 scale.

    # TODO: [MVP] compute for real; the skeleton raises.
    """
    raise NotImplementedError


def calculate_noise_score(image: ModuleType, engine: EngineChoice) -> float:
    """Measure how noisy an image is.

    Args:
        image: The engine-native image.
        engine: The engine that produced it.

    Returns:
        The noise estimate: higher means noisier.

    # TODO: [MVP] compute for real; the skeleton raises.
    """
    raise NotImplementedError


def detect_orientation(image: ModuleType, engine: EngineChoice) -> OrientationReading:
    """Decide how far a page is rotated from upright.

    Args:
        image: The engine-native image.
        engine: The engine that produced it.

    Returns:
        The correction angle and the method that produced it.

    # TODO: [MVP] detect for real; the skeleton raises.
    """
    raise NotImplementedError


def detect_skew_angle(image: ModuleType, engine: EngineChoice) -> float:
    """Measure a small rotation from horizontal, in degrees.

    Distinct from :func:`detect_orientation`: skew is the residue after orientation is
    corrected, and is expected to be a fraction of a degree to a few degrees.

    Args:
        image: The engine-native image.
        engine: The engine that produced it.

    Returns:
        The skew in degrees; positive is clockwise.

    # TODO: [MVP] detect for real; the skeleton raises.
    """
    raise NotImplementedError


def detect_text_regions(
    image: ModuleType, engine: EngineChoice
) -> tuple[TextRegion, ...]:
    """Locate the rectangles that appear to hold text.

    Args:
        image: The engine-native image.
        engine: The engine that produced it.

    Returns:
        The regions, in top-to-bottom, left-to-right order for a stable record.

    # TODO: [MVP] detect for real; the skeleton raises.
    """
    raise NotImplementedError


def calculate_text_coverage(
    image: ModuleType, engine: EngineChoice, regions: tuple[TextRegion, ...]
) -> float:
    """Measure how much of an image is text.

    Takes the regions rather than recomputing them so one detection pass serves both the
    ``text_regions`` record and this coverage figure, which must agree with it by construction.

    Args:
        image: The engine-native image.
        engine: The engine that produced it.
        regions: The regions from :func:`detect_text_regions`.

    Returns:
        Text pixels over total pixels, 0.0-1.0.

    # TODO: [MVP] compute for real; the skeleton raises.
    """
    raise NotImplementedError


__all__ = [
    "BINARIZATION_THRESHOLD",
    "LAPLACIAN_KERNEL_SIZE",
    "ORIENTATION_METHOD",
    "OrientationReading",
    "TextRegion",
    "calculate_blur_score",
    "calculate_brightness_score",
    "calculate_contrast_score",
    "calculate_noise_score",
    "calculate_sharpness_score",
    "calculate_text_coverage",
    "detect_orientation",
    "detect_skew_angle",
    "detect_text_regions",
]
