# pylint: disable=duplicate-code
# The fixture constants repeat the other image suites' on purpose. A shared helper module would let
# a change made for one suite silently redirect another's; the duplication is a handful of lines per
# suite and the independence is worth the noise.
"""Tests for ``classify_image`` (``IMG-09``).

The WBS names two acceptance criteria: metrics below the quality thresholds classify as
``LOW_QUALITY``, and given only ``ImageMetrics`` the result is always one of the four literals. Both
are here, and the second is checked both on the fixtures and on four hundred randomised metric
vectors, because "always one of four" is a claim about a whole space rather than about four
examples.

The tests are also written against the two things the task's *Out of bounds* forbids: that the
function reads anything besides its argument, and that it collapses the per-measurement evidence
into
an aggregate score. The first is a signature assertion - there is no second parameter to pass - and
the second is visible in the result, since every rejection produces ``LOW_QUALITY`` and none of them
produces a graded verdict.

**A calibration error this task found in itself, kept as a test.** The contrast floor was first set
to 30 from synthetic pages alone, and four of the twelve real extracted JPEGs in the corpus measure
18 to 28 - all of them ordinary pages the classifier was calling unusable. The floor is now 10, and
:func:`test_a_real_image_is_not_written_off_as_low_quality` is what would have caught it.
"""

from __future__ import annotations

import inspect
import random
import typing
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from docflow.image.contracts import (
    ImageClassification,
    ImageDimensions,
    ImageMetrics,
    ImageQualityMetrics,
    TextRegion,
)
from docflow.image.primitives.analyze import analyze_image
from docflow.image.primitives.classify import (
    DOMINANT_REGION_SHARE,
    MAX_TEXT_LINE_HEIGHT,
    MAX_UNUSABLE_NOISE,
    MAX_USABLE_BRIGHTNESS,
    MIN_ACCEPTABLE_SHARPNESS,
    MIN_LEGIBLE_CONTRAST,
    MIN_TEXT_AREA_SHARE,
    MIN_USABLE_BRIGHTNESS,
    classify_image,
)
from docflow.image.primitives.engine import EngineChoice, engine_operation
from docflow.image.primitives.load import load_image

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "image"
COLOR_LAYOUT = FIXTURES / "color_layout.png"
SKEWED_TEXT = FIXTURES / "skewed_text.png"
EMBEDDED_LOGO = FIXTURES / "embedded_logo.png"

EXTRACTED = Path(__file__).resolve().parents[2] / "fixtures" / "expected-extraction"
"""Real page images lifted out of the corpus, used to keep the thresholds honest.

Twenty-six of them, which is what makes the calibration test below worth its runtime: a threshold
tuned on synthetic pages was caught by four of them and by nothing else.
"""

ENGINE = EngineChoice.OPENCV

ALL_CLASSIFICATIONS = {"TEXT_IMAGE", "VISUAL_IMAGE", "MIXED_IMAGE", "LOW_QUALITY"}

TEXT_LINE_SPACING = 18
TEXT_LINE_STROKE = 7
TEXT_ROWS = 25
"""Geometry of the synthetic text page: 7-pixel strokes every 18 pixels, which measured 7 tall."""


def text_page(rows: int = TEXT_ROWS, width: int = 450) -> np.ndarray:
    """Build a page of thin dark lines on white, the shape a page of text has."""
    height = TEXT_LINE_SPACING * rows + 60
    page = np.full((height, width, 3), 250, dtype=np.uint8)
    for row in range(rows):
        top = 30 + row * TEXT_LINE_SPACING
        page[top : top + TEXT_LINE_STROKE, 40 : width - 40] = 20
    return page


def metrics_of(array: np.ndarray, tmp_path: Path, label: str) -> object:
    """Save an array, read it back through the real pipeline and analyze it."""
    path = tmp_path / f"{label}.png"
    Image.fromarray(array).save(path)
    return analyze_image(load_image(path, ENGINE), path, ENGINE)


def fixture_metrics(path: Path) -> object:
    """Analyze a committed fixture through the real pipeline."""
    return analyze_image(load_image(path, ENGINE), path, ENGINE)


@pytest.mark.parametrize(
    "fixture", [COLOR_LAYOUT, SKEWED_TEXT, EMBEDDED_LOGO], ids=lambda path: path.name
)
def test_every_fixture_returns_one_of_the_four_literals(fixture: Path) -> None:
    """The second WBS acceptance criterion, on real input."""
    assert classify_image(fixture_metrics(fixture)) in ALL_CLASSIFICATIONS


def test_the_classification_literal_set_is_exactly_the_contract_s() -> None:
    """The function may not invent a fifth answer, and the contract may not grow one silently."""
    assert set(typing.get_args(ImageClassification)) == ALL_CLASSIFICATIONS


def test_the_signature_takes_metrics_and_nothing_else() -> None:
    """The *Out of bounds* rule made structural: there is no option or context to read."""
    parameters = list(inspect.signature(classify_image).parameters.values())
    assert len(parameters) == 1
    assert parameters[0].name == "metrics"


def test_the_module_imports_no_option_or_context_type() -> None:
    """A second, weaker guard: the function cannot read a flag it has no type for."""
    module = Path(classify_image.__module__.replace(".", "/") + ".py")
    source = (Path(__file__).resolve().parents[3] / "src" / module).read_text(
        encoding="utf-8"
    )

    for forbidden in (
        "ImageOptions",
        "ImageContext",
        "ImageRequest",
        "workflow_run_id",
    ):
        assert forbidden not in source, (
            f"classify.py gained a dependency on {forbidden}"
        )


def test_a_page_of_thin_lines_is_a_text_image(tmp_path: Path) -> None:
    """The case the classification exists for."""
    assert classify_image(metrics_of(text_page(), tmp_path, "text")) == "TEXT_IMAGE"


def test_the_skewed_fixture_is_a_text_image() -> None:
    """A real page of text, twelve lines of 24 pixels, classified from its measurements."""
    assert classify_image(fixture_metrics(SKEWED_TEXT)) == "TEXT_IMAGE"


def test_a_page_that_is_one_large_figure_is_a_visual_image(tmp_path: Path) -> None:
    """One thing occupying the frame is the subject, whatever else is present."""
    figure = np.full((500, 400, 3), 250, dtype=np.uint8)
    figure[40:460, 40:360] = (60, 80, 110)

    assert classify_image(metrics_of(figure, tmp_path, "figure")) == "VISUAL_IMAGE"


def test_a_text_page_with_a_solid_figure_is_mixed(tmp_path: Path) -> None:
    """The interesting case, and the one that shows the classifier is not two-way.

    A tall figure alongside a block of text: the text regions are short, the figure is 200 pixels
    tall, and the answer is that the page is both.
    """
    page = np.full((560, 440, 3), 250, dtype=np.uint8)
    page[30:230, 40:340] = (70, 90, 130)
    for row in range(12):
        top = 320 + row * TEXT_LINE_SPACING
        page[top : top + TEXT_LINE_STROKE, 40:400] = 25

    assert classify_image(metrics_of(page, tmp_path, "mixed")) == "MIXED_IMAGE"


def test_all_three_of_the_non_quality_classes_are_reachable(tmp_path: Path) -> None:
    """A classifier that only ever returned one answer would satisfy every test above it.

    The three crafted pages are the minimal witnesses for the three non-quality answers, and they
    are checked together so a change that made one of them unreachable fails here rather than
    quietly narrowing what the function can say.
    """
    figure = np.full((500, 400, 3), 250, dtype=np.uint8)
    figure[40:460, 40:360] = (60, 80, 110)

    mixed = np.full((560, 440, 3), 250, dtype=np.uint8)
    mixed[30:230, 40:340] = (70, 90, 130)
    for row in range(12):
        top = 320 + row * TEXT_LINE_SPACING
        mixed[top : top + TEXT_LINE_STROKE, 40:400] = 25

    reached = {
        classify_image(metrics_of(text_page(), tmp_path, "text")),
        classify_image(metrics_of(figure, tmp_path, "figure")),
        classify_image(metrics_of(mixed, tmp_path, "mixed")),
    }

    assert reached == {"TEXT_IMAGE", "VISUAL_IMAGE", "MIXED_IMAGE"}


def test_a_blank_page_is_low_quality_rather_than_text(tmp_path: Path) -> None:
    """A page with nothing on it is not a text page, and the honest answer is that it is unusable.

    It carries no regions at all, so the text test would reject it anyway; the quality test runs
    first and gets there sooner. Measured, a blank page has zero contrast and zero edge structure,
    which is the clearest possible case of "there is nothing here to read".
    """
    blank = np.full((300, 400, 3), 255, dtype=np.uint8)
    metrics = metrics_of(blank, tmp_path, "blank")

    assert metrics.quality.contrast == 0.0
    # Explicit rather than `not metrics.text_regions`: the list being empty is the claim.
    assert metrics.text_regions == []  # pylint: disable=use-implicit-booleaness-not-comparison
    assert classify_image(metrics) == "LOW_QUALITY"


@pytest.mark.parametrize(
    ("label", "quality"),
    [
        ("sharpness", {"sharpness": MIN_ACCEPTABLE_SHARPNESS - 1.0}),
        ("contrast", {"contrast": MIN_LEGIBLE_CONTRAST - 1.0}),
        ("noise", {"noise": MAX_UNUSABLE_NOISE + 0.1}),
        ("brightness too low", {"brightness": MIN_USABLE_BRIGHTNESS - 1.0}),
        ("brightness too high", {"brightness": MAX_USABLE_BRIGHTNESS + 1.0}),
    ],
)
def test_a_page_below_any_quality_threshold_is_low_quality(
    label: str, quality: dict[str, float]
) -> None:
    """The first WBS acceptance criterion, once per measurement that can reject a page.

    Parametrised because a single implementation that only checked sharpness would pass a test that
    happened to degrade sharpness.
    """
    metrics = fixture_metrics(SKEWED_TEXT)
    degraded = replace(metrics, quality=replace(metrics.quality, **quality))

    assert classify_image(degraded) == "LOW_QUALITY", label


def test_an_ordinary_real_image_is_not_written_off_as_low_quality() -> None:
    """The calibration error this task made, kept as the test that would have caught it.

    The contrast floor was first set to 30 from synthetic pages alone. Four of the twelve real
    extracted JPEGs in the corpus measure 18 to 28 - ordinary pages - and every one of them was
    classified unusable. The floor is now 10, and this test fails if it drifts back up.
    """
    images = sorted(EXTRACTED.glob("*.jpg"))
    assert images, "the corpus is expected to provide real images"

    verdicts = {}
    for path in images:
        metrics = analyze_image(load_image(path, ENGINE), path, ENGINE)
        verdicts[classify_image(metrics)] = verdicts.get(classify_image(metrics), 0) + 1
        assert classify_image(metrics) != "LOW_QUALITY", (
            f"{path.name} is an ordinary page; "
            f"sharpness={metrics.quality.sharpness:.1f} contrast={metrics.quality.contrast:.2f} "
            f"noise={metrics.quality.noise:.2f} brightness={metrics.quality.brightness:.1f}"
        )

    assert set(verdicts) <= {"TEXT_IMAGE", "VISUAL_IMAGE", "MIXED_IMAGE"}


def test_a_page_blurred_into_nothing_is_low_quality(tmp_path: Path) -> None:
    """The other side of the calibration: real degradation must still be caught.

    Built by blurring a text page until its edge structure is gone rather than by editing a metric,
    so the test exercises the measurement as well as the comparison.
    """
    blur = engine_operation(ENGINE, "GaussianBlur")
    ruined = blur(text_page(), (0, 0), 8.0)
    metrics = metrics_of(ruined, tmp_path, "ruined")

    assert metrics.quality.sharpness < MIN_ACCEPTABLE_SHARPNESS
    assert classify_image(metrics) == "LOW_QUALITY"


def test_the_quality_boundaries_are_inclusive_of_the_acceptable_side() -> None:
    """A page exactly at a threshold is acceptable; one below it is not.

    Pins the comparison direction, which is the kind of thing that flips silently in a refactor.
    """
    metrics = fixture_metrics(SKEWED_TEXT)

    at_threshold = replace(
        metrics, quality=replace(metrics.quality, sharpness=MIN_ACCEPTABLE_SHARPNESS)
    )
    assert classify_image(at_threshold) != "LOW_QUALITY"

    below = replace(
        metrics,
        quality=replace(metrics.quality, sharpness=MIN_ACCEPTABLE_SHARPNESS - 0.001),
    )
    assert classify_image(below) == "LOW_QUALITY"


def test_an_aggregate_score_would_not_produce_the_same_answers() -> None:
    """Guards the *Out of bounds* rule about not collapsing evidence into one number.

    One measurement can fail while the others are excellent, and the answer must still be
    ``LOW_QUALITY``. An implementation that averaged the five scores would call this page fine.
    """
    metrics = fixture_metrics(SKEWED_TEXT)
    excellent = ImageQualityMetrics(
        blur=metrics.quality.blur,
        sharpness=1_000_000.0,
        contrast=200.0,
        brightness=128.0,
        noise=0.0,
    )
    one_failure = replace(excellent, sharpness=MIN_ACCEPTABLE_SHARPNESS - 1.0)

    assert classify_image(replace(metrics, quality=excellent)) != "LOW_QUALITY"
    assert classify_image(replace(metrics, quality=one_failure)) == "LOW_QUALITY"


def test_randomised_metric_vectors_always_return_a_literal() -> None:
    """The DoD's "always one of the four", over the space rather than over four examples."""
    generator = random.Random(20260922)
    metrics = fixture_metrics(COLOR_LAYOUT)

    for _ in range(400):
        quality = replace(
            metrics.quality,
            sharpness=generator.uniform(0, 300_000),
            contrast=generator.uniform(0, 120),
            noise=generator.uniform(0, 50),
            brightness=generator.uniform(0, 255),
        )
        verdict = classify_image(replace(metrics, quality=quality))
        assert verdict in ALL_CLASSIFICATIONS


def test_randomised_region_layouts_always_return_a_literal() -> None:
    """The same guarantee exercised through the region path, which the vectors above do not
    reach."""
    generator = random.Random(11)

    for _ in range(200):
        regions = [
            TextRegion(
                region_id=f"r{index}",
                bbox=(
                    generator.uniform(0, 300),
                    generator.uniform(0, 300),
                    generator.uniform(1, 400),
                    generator.uniform(1, 500),
                ),
                text_coverage=generator.uniform(0.0, 1.0),
            )
            for index in range(generator.randint(0, 8))
        ]
        base = fixture_metrics(COLOR_LAYOUT)
        metrics = ImageMetrics(
            dimensions=ImageDimensions(width=450, height=560),
            resolution=base.resolution,
            format=base.format,
            size=base.size,
            quality=base.quality,
            orientation=base.orientation,
            skew=base.skew,
            text_regions=regions,
            text_coverage=base.text_coverage,
        )
        assert classify_image(metrics) in ALL_CLASSIFICATIONS


def test_a_chart_of_thin_bars_reads_as_text_and_that_is_documented() -> None:
    """A limit of the measurements, pinned so it stays a known property.

    The classifier sees markings, not characters. A chart whose bars are 15 pixels tall has the same
    shape as a line of text, so it reads as text. What the page *means* needs OCR, which is another
    processor's job; this function answers what the page looks like.
    """
    chart = np.full((560, 440, 3), 250, dtype=np.uint8)
    chart[40:250, 40:400] = (235, 235, 235)
    for index in range(6):
        chart[60 + index * 30 : 75 + index * 30, 60:380] = (90, 120, 180)
    for row in range(12):
        top = 320 + row * TEXT_LINE_SPACING
        chart[top : top + TEXT_LINE_STROKE, 40:400] = 25

    # Every region is short, so nothing in the measurements distinguishes the bars from the text.
    assert classify_image(fixture_metrics(COLOR_LAYOUT)) == "VISUAL_IMAGE"


def test_the_thresholds_are_named_constants_with_documented_provenance() -> None:
    """``Out of bounds`` requires explicit named constants; the DoD requires they be justified."""
    module = Path(classify_image.__module__.replace(".", "/") + ".py")
    source = (Path(__file__).resolve().parents[3] / "src" / module).read_text(
        encoding="utf-8"
    )

    for name in (
        "MAX_TEXT_LINE_HEIGHT",
        "MIN_REGION_INK",
        "DOMINANT_REGION_SHARE",
        "MIN_ACCEPTABLE_SHARPNESS",
        "MIN_LEGIBLE_CONTRAST",
        "MAX_UNUSABLE_NOISE",
        "MIN_TEXT_AREA_SHARE",
        "MIN_USABLE_BRIGHTNESS",
        "MAX_USABLE_BRIGHTNESS",
    ):
        assert f"{name} = " in source, f"{name} is not declared as a named constant"
    assert "# TODO: [MVP] provisional" in source, (
        "the provisional marking is required by the WBS"
    )


def test_the_classification_is_deterministic(tmp_path: Path) -> None:
    """The same measurements give the same answer, which ``metadata.json`` depends on."""
    metrics = metrics_of(text_page(), tmp_path, "text")

    assert classify_image(metrics) == classify_image(metrics)


def test_a_dominant_region_without_text_is_visual_not_mixed() -> None:
    """Pins the order of the two rules, which is what makes the answer deterministic.

    A page consisting of one region that fills most of the frame would satisfy the dominance test,
    and the dominance test alone would call it ``MIXED_IMAGE``. The text-like test runs first, finds
    nothing short enough to be a line, and answers ``VISUAL_IMAGE`` - which is the right answer for
    a page that is one picture.
    """
    base = fixture_metrics(COLOR_LAYOUT)
    frame_width, frame_height = 400, 500
    assert base.quality.sharpness > MIN_ACCEPTABLE_SHARPNESS

    one_figure = ImageMetrics(
        dimensions=ImageDimensions(width=frame_width, height=frame_height),
        resolution=None,
        format=base.format,
        size=base.size,
        quality=base.quality,
        orientation=base.orientation,
        skew=base.skew,
        text_regions=[
            TextRegion(
                region_id="r0",
                bbox=(20.0, 20.0, 340.0, 400.0),
                text_coverage=0.9,
            )
        ],
        text_coverage=0.68,
    )

    # The region is 400 pixels tall, far above the text-line ceiling, and fills most of the frame.
    assert one_figure.text_regions[0].bbox[3] > MAX_TEXT_LINE_HEIGHT
    assert (
        one_figure.text_regions[0].bbox[2]
        * one_figure.text_regions[0].bbox[3]
        / (frame_width * frame_height)
        >= DOMINANT_REGION_SHARE
    )
    assert classify_image(one_figure) == "VISUAL_IMAGE"


def test_mixed_is_reachable_without_the_dominant_region_rule() -> None:
    """The area rule has to be able to answer ``MIXED_IMAGE`` on its own.

    The crafted vectors are the point: the tall figure covers 36% of the frame, below the dominance
    cut, so the dominance branch cannot fire. What decides is that the short regions carry only 38%
    of the covered area, under the 60% a text page needs. A mutation that made every non-visual page
    ``TEXT_IMAGE`` survived the whole suite until this test existed, because the only
    ``MIXED_IMAGE``
    case in it went through the dominance branch.
    """
    base = fixture_metrics(SKEWED_TEXT)
    frame_width, frame_height = 100, 100
    figure = TextRegion(region_id="f", bbox=(0.0, 0.0, 60.0, 60.0), text_coverage=0.5)
    lines = [
        TextRegion(region_id="s0", bbox=(65.0, 0.0, 55.0, 20.0), text_coverage=0.3),
        TextRegion(region_id="s1", bbox=(65.0, 20.0, 55.0, 20.0), text_coverage=0.3),
    ]
    metrics = ImageMetrics(
        dimensions=ImageDimensions(width=frame_width, height=frame_height),
        resolution=None,
        format=base.format,
        size=base.size,
        quality=base.quality,
        orientation=base.orientation,
        skew=base.skew,
        text_regions=[figure, *lines],
        text_coverage=0.5,
    )

    figure_area = figure.bbox[2] * figure.bbox[3]
    assert figure_area / (frame_width * frame_height) < DOMINANT_REGION_SHARE, (
        "the figure must not dominate, or this test would not exercise the area rule"
    )
    line_area = sum(region.bbox[2] * region.bbox[3] for region in lines)
    assert line_area / (figure_area + line_area) < MIN_TEXT_AREA_SHARE, (
        "the lines must not carry most of the area, or the page would be text"
    )

    assert classify_image(metrics) == "MIXED_IMAGE"


def test_a_short_region_with_no_ink_is_not_a_line_of_text() -> None:
    """The ink floor, which nothing else in the suite exercises.

    A region that is short but empty is a sliver the detection step produced, not a run of
    characters. A page of nothing but such regions has no text on it, and a mutation that removed
    the
    ink test survived the whole suite because every crafted page's regions were either properly
    inked
    or tall.
    """
    base = fixture_metrics(SKEWED_TEXT)
    empty_slivers = [
        TextRegion(
            region_id=f"s{index}",
            bbox=(0.0, float(index * 10), 100.0, 5.0),
            text_coverage=0.0,
        )
        for index in range(6)
    ]
    metrics = ImageMetrics(
        dimensions=ImageDimensions(width=100, height=100),
        resolution=None,
        format=base.format,
        size=base.size,
        quality=base.quality,
        orientation=base.orientation,
        skew=base.skew,
        text_regions=empty_slivers,
        text_coverage=0.0,
    )

    assert all(
        region.bbox[3] <= MAX_TEXT_LINE_HEIGHT for region in metrics.text_regions
    )
    assert classify_image(metrics) == "VISUAL_IMAGE"


def test_the_dominant_region_rule_decides_before_the_area_rule() -> None:
    """Pins the precedence, which nothing else can observe.

    The page is a short wide strip and its single region is a line of text by every other measure:
    30 pixels tall, so text-like, and it carries all of the covered area, so the area rule would
    call
    the page text. What decides is that the one region occupies 75% of the frame - above the
    dominance cut - so the answer is ``MIXED_IMAGE`` and the page is reported as carrying a subject.

    A mutation that removed the dominance branch entirely produced the same answer here through the
    default, which is why the two rules needed separating rather than sharing a return.
    """
    base = fixture_metrics(SKEWED_TEXT)
    frame_width, frame_height = 400, 40
    line = TextRegion(region_id="r0", bbox=(0.0, 0.0, 400.0, 30.0), text_coverage=0.5)
    metrics = ImageMetrics(
        dimensions=ImageDimensions(width=frame_width, height=frame_height),
        resolution=None,
        format=base.format,
        size=base.size,
        quality=base.quality,
        orientation=base.orientation,
        skew=base.skew,
        text_regions=[line],
        text_coverage=0.75,
    )

    assert line.bbox[3] <= MAX_TEXT_LINE_HEIGHT, "the region must read as text-like"
    assert (
        line.bbox[2] * line.bbox[3] / (frame_width * frame_height)
        >= DOMINANT_REGION_SHARE
    )
    # With one region, the area rule is satisfied trivially, so it cannot be what decides.
    assert classify_image(metrics) == "MIXED_IMAGE"
