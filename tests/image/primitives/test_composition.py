"""Tests for the measured facts, the thresholds and the derived names (``IMG-06``, ``IMG-09``).

Every case here is a rule of **ours** over a metrics record we construct. Nothing is decoded,
no engine is reached, and no case claims a value is the "right" blur or contrast: those are the
engine's readings, and the engine is not the deliverable. The OCR preparation profiles
(``IMG-08``) are a rule of the same kind: they read a metrics record and name a profile.
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
    BRIGHTNESS_TARGET,
    CONTRAST_MIN,
    NOISE_MAX,
    OCR_BLUR_LOW,
    OCR_BRIGHTNESS_HIGH,
    OCR_CONTRAST_LOW,
    OCR_NOISE_HIGH,
    OCR_PROFILES,
    OCR_SCALE_MAX,
    SHARPNESS_MIN,
    TEXT_COVERAGE_MIN,
    TEXT_DOMINANT_COVERAGE,
    brightness_shift,
    build_text_regions,
    calculate_text_coverage,
    choose_ocr_profile,
    classify_image,
    glyph_height,
    is_low_quality,
    ocr_upscale_factor,
)


def build_metrics(
    *,
    text_coverage: float = 0.0,
    blur: float = OCR_BLUR_LOW * 2,
    sharpness: float = SHARPNESS_MIN * 4,
    contrast: float = CONTRAST_MIN * 4,
    brightness: float = 128.0,
    noise: float = OCR_NOISE_HIGH / 2.0,
    skew: float | None = 0.0,
    dimensions: ImageDimensions | None = None,
    regions: list[TextRegion] | None = None,
) -> ImageMetrics:
    """Build a complete metrics record with every reading inside the usable bands.

    Every default is inside both bands a reading is judged by: the ``LOW_QUALITY`` floors of
    :func:`is_low_quality` and the wider bands :func:`choose_ocr_profile` selects on. A case
    that wants the other side of a boundary overrides the one reading it is about.
    """
    return ImageMetrics(
        dimensions=ImageDimensions(width=200, height=100)
        if dimensions is None
        else dimensions,
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
        skew=skew,
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


def test_a_page_above_the_band_is_reported_and_never_darkened() -> None:
    """The correction is one-sided on purpose: a white page's paper is not an over-exposure.

    The reading is the page's *mean*, and on a sparse white document the mean is mostly ink
    coverage — the paper is exactly the white a reader wants. Mutation that must break this:
    return ``BRIGHTNESS_TARGET - brightness`` for a page above the ceiling too, which repaints
    that paper mid-grey (measured on the corpus: contrast 45.81 -> 17.04 for 3.98 levels).
    """
    dark = BRIGHTNESS_MIN - 5.0

    assert brightness_shift(BRIGHTNESS_MAX + 4.0) is None
    assert brightness_shift(BRIGHTNESS_MAX) is None
    assert brightness_shift(BRIGHTNESS_TARGET) is None
    assert brightness_shift(dark) == BRIGHTNESS_TARGET - dark


@pytest.mark.parametrize(
    ("readings", "expected"),
    [
        ({}, "clean"),
        ({"noise": OCR_NOISE_HIGH}, "noisy"),
        (
            {"brightness": OCR_BRIGHTNESS_HIGH, "contrast": OCR_CONTRAST_LOW - 1.0},
            "washed_out",
        ),
        ({"contrast": OCR_CONTRAST_LOW - 1.0}, "uneven_or_skewed"),
        ({"skew": 1.0}, "uneven_or_skewed"),
        # Both sides of the two boundaries the order depends on: a reading one tenth of a
        # unit inside the band loses to the next test down, and noise outranks them all.
        (
            {
                "noise": OCR_NOISE_HIGH - 0.1,
                "brightness": OCR_BRIGHTNESS_HIGH - 0.1,
                "contrast": OCR_CONTRAST_LOW,
            },
            "clean",
        ),
        (
            {
                "noise": OCR_NOISE_HIGH,
                "brightness": OCR_BRIGHTNESS_HIGH,
                "contrast": 0.0,
            },
            "noisy",
        ),
    ],
)
def test_the_profile_is_selected_by_the_readings_and_nothing_else(
    readings: dict[str, float], expected: str
) -> None:
    """One case per boundary: the rule is the constants, and the test walks both sides."""
    assert choose_ocr_profile(build_metrics(**readings)) == OCR_PROFILES[expected]


def test_the_plain_profile_is_still_a_profile() -> None:
    """A page inside every band is not left alone: it still gets the frozen binarization."""
    plain = choose_ocr_profile(build_metrics())

    assert plain.name == "clean"
    assert not plain.denoise
    assert not plain.equalize_contrast
    assert not plain.flatten_illumination
    assert plain.binarize_block_size % 2 == 1


def test_the_engines_axis_aligned_reading_is_not_a_skew() -> None:
    """OpenCV 5 reports an upright ink box as ``-90``: that is no skew, not a large one.

    The corpus the batch tool wrote carries ``-90`` on three quarters of its pages (measured
    in ``var/batch_image``), so a rule that read the field raw would send most of them to the
    flattening profile. Mutation that must break this test: drop ``OCR_SKEW_MAX`` from the
    comparison, which selects ``uneven_or_skewed`` for a page whose ink is axis-aligned.
    """
    upright = build_metrics(skew=-89.96, contrast=45.81, brightness=243.98, noise=2.49)

    assert choose_ocr_profile(upright).name == "clean"
    assert choose_ocr_profile(replace(upright, skew=-5.01)).name == "uneven_or_skewed"
    assert choose_ocr_profile(replace(upright, skew=None)).name == "clean"


def test_only_the_regions_that_measure_a_letter_are_counted() -> None:
    """A border, a rule and a paragraph's box are not letters, and the median is of the rest."""
    metrics = build_metrics(
        dimensions=ImageDimensions(width=1000, height=800),
        regions=[
            # Glued to the frame's top and right edges: the detector traced the page, not a line.
            TextRegion(
                region_id="region_001",
                bbox=(0.0, 0.0, 1000.0, 1.0),
                text_coverage=1.0,
            ),
            # One pixel tall: a rule.
            TextRegion(
                region_id="region_002", bbox=(10.0, 10.0, 60.0, 11.0), text_coverage=1.0
            ),
            # Four hundred pixels tall: a paragraph's box, not a letter.
            TextRegion(
                region_id="region_003",
                bbox=(10.0, 20.0, 600.0, 420.0),
                text_coverage=1.0,
            ),
            TextRegion(
                region_id="region_004",
                bbox=(10.0, 500.0, 60.0, 512.0),
                text_coverage=1.0,
            ),
            TextRegion(
                region_id="region_005",
                bbox=(10.0, 540.0, 60.0, 558.0),
                text_coverage=1.0,
            ),
        ],
    )

    assert glyph_height(metrics) == pytest.approx(15.0)
    assert glyph_height(build_metrics()) is None


def test_the_upscale_is_bounded_by_the_letter_and_by_the_page() -> None:
    """The factor answers to the letters, then to what the page can pay for."""

    def page(width: int, height: int, letter: float) -> ImageMetrics:
        """Return a page whose only region is a line ``letter`` pixels tall."""
        return build_metrics(
            dimensions=ImageDimensions(width=width, height=height),
            regions=[
                TextRegion(
                    region_id="region_001",
                    bbox=(10.0, 10.0, 60.0, 10.0 + letter),
                    text_coverage=1.0,
                )
            ],
        )

    # 30/12 = 2.5, held back to 2.0 by a 2000-pixel side against OCR_MAX_SIDE.
    assert ocr_upscale_factor(page(1000, 2000, 12.0)) == pytest.approx(2.0)
    assert ocr_upscale_factor(page(500, 500, 12.0)) == pytest.approx(2.5)
    # 30/6 = 5, capped by the factor ceiling.
    assert ocr_upscale_factor(page(100, 100, 6.0)) == pytest.approx(OCR_SCALE_MAX)
    # A letter at or above the floor needs no upscale, and a 3% one is a resample for nothing.
    assert ocr_upscale_factor(page(1000, 2000, 30.0)) is None
    assert ocr_upscale_factor(page(1000, 2000, 29.0)) is None
    # No letter measured is not a letter of size zero.
    assert ocr_upscale_factor(build_metrics()) is None
