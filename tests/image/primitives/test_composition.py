"""Tests for the measured facts, the thresholds and the derived names (``IMG-06``, ``IMG-09``).

Every case here is a rule of **ours** over a metrics record we construct. Nothing is decoded,
no engine is reached, and no case claims a value is the "right" blur or contrast: those are the
engine's readings, and the engine is not the deliverable.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from docflow.image import (
    ImageDimensions,
    ImageMetrics,
    ImageQualityMetrics,
    TextRegion,
)
from docflow.image.primitives.composition import (
    BLUR_MIN,
    BRIGHTNESS_MAX,
    BRIGHTNESS_MIN,
    CONTRAST_MIN,
    NOISE_MAX,
    SHARPNESS_MIN,
    TEXT_COVERAGE_MIN,
    TEXT_DOMINANT_COVERAGE,
    build_text_regions,
    calculate_text_coverage,
    classify_image,
    is_low_quality,
)


def build_metrics(
    *,
    text_coverage: float = 0.0,
    blur: float = BLUR_MIN * 4,
    sharpness: float = SHARPNESS_MIN * 4,
    contrast: float = CONTRAST_MIN * 4,
    brightness: float = 128.0,
    noise: float = NOISE_MAX / 4,
    regions: list[TextRegion] | None = None,
) -> ImageMetrics:
    """Build a complete metrics record with every reading inside the usable bands."""
    return ImageMetrics(
        dimensions=ImageDimensions(width=200, height=100),
        resolution=None,
        format="png",
        size=1024,
        quality=ImageQualityMetrics(
            blur=blur,
            sharpness=sharpness,
            contrast=contrast,
            brightness=brightness,
            noise=noise,
        ),
        orientation=0,
        skew=0.0,
        text_regions=[] if regions is None else regions,
        text_coverage=text_coverage,
    )


def test_regions_are_named_and_ordered_in_reading_order() -> None:
    """Reading order is ours: top to bottom, and left to right within a band."""
    measured = [
        ((80.0, 40.0, 100.0, 50.0), 0.5),
        ((10.0, 5.0, 40.0, 20.0), 0.25),
        ((10.0, 40.0, 60.0, 60.0), 0.75),
    ]

    regions = build_text_regions(measured)

    assert [region.region_id for region in regions] == [
        "region_001",
        "region_002",
        "region_003",
    ]
    assert [region.bbox for region in regions] == [
        (10.0, 5.0, 40.0, 20.0),
        (10.0, 40.0, 60.0, 60.0),
        (80.0, 40.0, 100.0, 50.0),
    ]
    assert [region.text_coverage for region in regions] == [0.25, 0.75, 0.5]


def test_the_coverage_is_a_share_of_the_image_and_is_clamped() -> None:
    """A measurement, never above the whole image, and never a division by zero."""
    half = [
        TextRegion(
            region_id="region_001", bbox=(0.0, 0.0, 100.0, 50.0), text_coverage=1.0
        )
    ]
    whole_twice = [
        TextRegion(
            region_id="region_001", bbox=(0.0, 0.0, 200.0, 100.0), text_coverage=1.0
        ),
        TextRegion(
            region_id="region_002", bbox=(0.0, 0.0, 200.0, 100.0), text_coverage=1.0
        ),
    ]

    assert calculate_text_coverage(half, 200, 100) == pytest.approx(0.25)
    assert calculate_text_coverage(whole_twice, 200, 100) == 1.0
    assert calculate_text_coverage([], 200, 100) == 0.0
    assert calculate_text_coverage(whole_twice, 0, 0) == 0.0


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"text_coverage": 0.0}, "VISUAL_IMAGE"),
        ({"text_coverage": TEXT_COVERAGE_MIN}, "MIXED_IMAGE"),
        ({"text_coverage": TEXT_COVERAGE_MIN * 5}, "MIXED_IMAGE"),
        ({"text_coverage": TEXT_DOMINANT_COVERAGE}, "TEXT_IMAGE"),
        ({"blur": BLUR_MIN - 1.0}, "LOW_QUALITY"),
        ({"sharpness": SHARPNESS_MIN - 1.0}, "LOW_QUALITY"),
        ({"contrast": CONTRAST_MIN - 1.0}, "LOW_QUALITY"),
        ({"noise": NOISE_MAX + 1.0}, "LOW_QUALITY"),
        ({"brightness": BRIGHTNESS_MIN - 1.0}, "LOW_QUALITY"),
        ({"brightness": BRIGHTNESS_MAX + 1.0}, "LOW_QUALITY"),
    ],
)
def test_the_classification_flips_exactly_at_the_documented_thresholds(
    overrides: dict[str, Any], expected: str
) -> None:
    """One case per boundary: the rule is the thresholds, and the test walks both sides."""
    settings: dict[str, Any] = {"text_coverage": TEXT_DOMINANT_COVERAGE, **overrides}

    assert classify_image(build_metrics(**settings)) == expected


def test_a_degraded_image_is_not_described_as_text_or_as_picture() -> None:
    """``LOW_QUALITY`` takes precedence: a blurred page is not usefully called a text image."""
    plenty_of_text = build_metrics(text_coverage=TEXT_DOMINANT_COVERAGE * 2)
    degraded = replace(
        plenty_of_text,
        quality=replace(plenty_of_text.quality, noise=NOISE_MAX + 1.0),
    )

    assert classify_image(plenty_of_text) == "TEXT_IMAGE"
    assert classify_image(degraded) == "LOW_QUALITY"


def test_the_vocabulary_is_closed_and_comes_from_the_metrics_alone() -> None:
    """Four literals, no argument but the metrics, and no workflow flag in the rule."""
    distinct = {
        classify_image(build_metrics(text_coverage=coverage))
        for coverage in (0.0, TEXT_COVERAGE_MIN, TEXT_DOMINANT_COVERAGE)
    }
    distinct.add(classify_image(build_metrics(blur=0.0)))

    assert distinct == {"TEXT_IMAGE", "MIXED_IMAGE", "VISUAL_IMAGE", "LOW_QUALITY"}


def test_the_quality_rule_reads_the_blur_reading_as_a_floor() -> None:
    """The field keeps the contract's name; the rule's direction is stated and asserted.

    The variance of the Laplacian *falls* as an image blurs, so a low reading is the bad one.
    A rule that read it as a ceiling would pass every blurred page and fail every sharp one.
    """
    assert is_low_quality(build_metrics(blur=BLUR_MIN - 1.0)) is True
    assert is_low_quality(build_metrics(blur=BLUR_MIN)) is False
    assert is_low_quality(build_metrics()) is False
