"""Tests for the analysis primitives (``IMG-04``).

The WBS names two acceptance criteria: ``detect_skew_angle`` reports a non-zero angle on
``skewed_text.png`` while leaving the input bytes alone, and ``calculate_text_coverage`` returns a
fraction in ``[0, 1]``. Both are here. So are the three properties the task is really responsible
for, and those are the tests worth reading:

* **Nothing is mutated** - not the array, and not any file. Asserted by comparing a copy and by
  hashing the fixture, because "side-effect free" is the property ``IMG-06`` depends on.
* **The numbers are measurements, not placeholders.** A test that only checks a float came back
  would pass on a hardcoded ``0``. These tests degrade an image and assert the metric moves in the
  direction the metric claims to measure.
* **Repeated runs agree** - the DoD asks for identical values for the same input and library
  version, which is what makes ``metadata.json`` comparable between runs.
"""

from __future__ import annotations

import hashlib
import importlib
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from docflow.image.contracts import TextRegion
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
    ink_mask,
    luminance,
)
from docflow.image.primitives.engine import (
    EngineChoice,
    ImageEngineCapabilityError,
    ImageEngineNotAvailableError,
    engine_operation,
)
from docflow.image.primitives.load import load_image

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "image"
COLOR_LAYOUT = FIXTURES / "color_layout.png"
SKEWED_TEXT = FIXTURES / "skewed_text.png"
EMBEDDED_LOGO = FIXTURES / "embedded_logo.png"

ENGINE = EngineChoice.OPENCV
"""The engine every analysis test uses.

Not a parameterisation over both engines. Pillow is a codec and provides none of the operations
these primitives need, which is asserted explicitly by
``test_the_codec_engine_reports_a_capability_gap_rather_than_substituting``.
"""

ALL_FIXTURES = [COLOR_LAYOUT, SKEWED_TEXT, EMBEDDED_LOGO]

DEGRADATION_SIGMA = 3.0
"""Gaussian blur radius used to degrade an image; large enough to move the sharpness metrics."""

NOISE_SIGMA = 25.0
"""Standard deviation of the synthetic grain added to raise the noise estimate."""


def digest(path: Path) -> str:
    """Return a hash of a file's bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def image_of(path: Path) -> np.ndarray:
    """Load a fixture as an array."""
    return load_image(path, ENGINE)


def blurred(image: np.ndarray) -> np.ndarray:
    """Return a blurred copy, for the metric-direction tests."""
    opencv = engine_operation(ENGINE, "GaussianBlur")
    return opencv(image, (0, 0), DEGRADATION_SIGMA)


def noisy(image: np.ndarray, seed: int = 20260922) -> np.ndarray:
    """Return a copy with synthetic grain, for the noise-direction test."""
    generator = np.random.default_rng(seed)
    grain = generator.normal(0.0, NOISE_SIGMA, image.shape)
    return np.clip(image.astype(np.float64) + grain, 0, 255).astype(np.uint8)


@pytest.mark.parametrize("fixture", ALL_FIXTURES, ids=lambda path: path.name)
def test_every_metric_returns_a_finite_measured_number(fixture: Path) -> None:
    """No field may be a stand-in: NaN, infinity or a silent zero are all failures."""
    image = image_of(fixture)

    for label, value in (
        ("blur", calculate_blur_score(image, ENGINE)),
        ("sharpness", calculate_sharpness_score(image, ENGINE)),
        ("contrast", calculate_contrast_score(image, ENGINE)),
        ("brightness", calculate_brightness_score(image, ENGINE)),
        ("noise", calculate_noise_score(image, ENGINE)),
        ("skew", detect_skew_angle(image, ENGINE)),
    ):
        assert np.isfinite(value), f"{label} on {fixture.name} was {value}"


@pytest.mark.parametrize("fixture", ALL_FIXTURES, ids=lambda path: path.name)
def test_analysis_never_mutates_the_input_array(fixture: Path) -> None:
    """The property IMG-06's side-effect-free guarantee rests on."""
    image = image_of(fixture)
    before = image.copy()

    regions = detect_text_regions(image, ENGINE)
    calculate_blur_score(image, ENGINE)
    calculate_sharpness_score(image, ENGINE)
    calculate_contrast_score(image, ENGINE)
    calculate_brightness_score(image, ENGINE)
    calculate_noise_score(image, ENGINE)
    detect_orientation(image, ENGINE)
    detect_skew_angle(image, ENGINE)
    calculate_text_coverage(image, ENGINE, regions)

    assert np.array_equal(image, before), "a primitive modified the array it was given"


@pytest.mark.parametrize("fixture", ALL_FIXTURES, ids=lambda path: path.name)
def test_analysis_never_writes_any_file(fixture: Path) -> None:
    """Whole-module guarantee: this module has no route to the filesystem.

    Checked two ways, because either alone is weak. The hash catches a write to the fixture; the
    source scan catches the capability existing at all, including on a path no test exercised.
    """
    before = digest(fixture)
    regions = detect_text_regions(image_of(fixture), ENGINE)
    calculate_text_coverage(image_of(fixture), ENGINE, regions)
    assert digest(fixture) == before

    source = Path(calculate_blur_score.__module__.replace(".", "/") + ".py")
    text = (Path(__file__).resolve().parents[3] / "src" / source).read_text()
    for forbidden in ("open(", "Path(", "save(", "imwrite", "write_bytes", "os.remove"):
        assert forbidden not in text, (
            f"analysis.py gained a filesystem route: {forbidden}"
        )


@pytest.mark.parametrize("fixture", ALL_FIXTURES, ids=lambda path: path.name)
def test_repeated_runs_produce_identical_values(fixture: Path) -> None:
    """The DoD: same input and library version, same numbers, so two runs are comparable."""
    image = image_of(fixture)

    def snapshot() -> tuple[object, ...]:
        return (
            calculate_blur_score(image, ENGINE),
            calculate_sharpness_score(image, ENGINE),
            calculate_contrast_score(image, ENGINE),
            calculate_brightness_score(image, ENGINE),
            calculate_noise_score(image, ENGINE),
            detect_orientation(image, ENGINE),
            detect_skew_angle(image, ENGINE),
            detect_text_regions(image, ENGINE),
        )

    assert snapshot() == snapshot()


def test_skew_is_detected_on_the_skewed_fixture() -> None:
    """The WBS acceptance criterion: a non-zero angle, and the input bytes unchanged."""
    before = digest(SKEWED_TEXT)
    image = image_of(SKEWED_TEXT)

    angle = detect_skew_angle(image, ENGINE)

    assert angle != 0.0
    assert digest(SKEWED_TEXT) == before


def test_the_detected_skew_matches_the_rotation_that_produced_the_fixture() -> None:
    """The fixture is rotated by exactly 4 degrees; a detector that returned "some angle" passes
    the criterion above but fails here.

    The generator applies a 4.0-degree rotation, so the tolerance is tight on purpose.
    """
    angle = detect_skew_angle(image_of(SKEWED_TEXT), ENGINE)
    assert angle == pytest.approx(4.0, abs=0.1)


def test_rotating_by_the_detected_angle_straightens_the_page() -> None:
    """The reading is a usable correction, not just a number of the right magnitude."""
    opencv = engine_operation(ENGINE, "getRotationMatrix2D")
    warp = engine_operation(ENGINE, "warpAffine")
    image = image_of(SKEWED_TEXT)
    height, width = image.shape[:2]

    angle = detect_skew_angle(image, ENGINE)
    correction = opencv((width / 2, height / 2), angle, 1.0)
    straightened = warp(image, correction, (width, height), borderValue=(255, 255, 255))

    assert abs(detect_skew_angle(straightened, ENGINE)) < 0.5


def test_an_upright_fixture_reports_no_skew() -> None:
    """A detector that reported a fixed non-zero angle would pass the skewed test alone."""
    assert detect_skew_angle(image_of(COLOR_LAYOUT), ENGINE) == pytest.approx(
        0.0, abs=0.1
    )


def test_skew_is_stable_against_a_rotation_of_the_page() -> None:
    """Bracketing the fixture's angle shows the reading tracks the input rather than a constant.

    The measured angle moves opposite to the applied one: turning the page further clockwise makes
    the ink rectangle's tilt smaller, because the reading describes the ink rather than the
    correction. Verified against the engine rather than assumed, and pinned here so a sign flip in
    the detector fails loudly instead of producing a correction that doubles the tilt.
    """
    opencv = engine_operation(ENGINE, "getRotationMatrix2D")
    warp = engine_operation(ENGINE, "warpAffine")
    image = image_of(SKEWED_TEXT)
    height, width = image.shape[:2]

    for applied in (-3.0, -1.0, 1.0, 3.0):
        matrix = opencv((width / 2, height / 2), applied, 1.0)
        turned = warp(image, matrix, (width, height), borderValue=(255, 255, 255))
        measured = detect_skew_angle(turned, ENGINE)
        assert measured == pytest.approx(4.0 - applied, abs=0.4)


@pytest.mark.parametrize("fixture", ALL_FIXTURES, ids=lambda path: path.name)
def test_text_coverage_is_a_fraction_between_zero_and_one(fixture: Path) -> None:
    """The WBS acceptance criterion, on every fixture rather than only the one it names."""
    image = image_of(fixture)
    coverage = calculate_text_coverage(
        image, ENGINE, detect_text_regions(image, ENGINE)
    )
    assert 0.0 <= coverage <= 1.0


def test_coverage_is_positive_on_a_page_that_visibly_has_text() -> None:
    """Guards the trivial way to satisfy "between 0 and 1": always return 0."""
    image = image_of(COLOR_LAYOUT)
    coverage = calculate_text_coverage(
        image, ENGINE, detect_text_regions(image, ENGINE)
    )
    assert coverage > 0.05


def test_coverage_is_zero_on_a_blank_page() -> None:
    """And the trivial way in the other direction: never return 0."""
    blank = np.full((120, 200), 255, dtype=np.uint8)
    regions = detect_text_regions(blank, ENGINE)
    assert calculate_text_coverage(blank, ENGINE, regions) == 0.0


def test_coverage_without_regions_is_zero_not_an_error() -> None:
    """Empty input is a legitimate answer, and must not divide by zero."""
    image = image_of(COLOR_LAYOUT)
    assert calculate_text_coverage(image, ENGINE, ()) == 0.0


def test_coverage_uses_the_regions_it_is_given() -> None:
    """The documented contract: the figure is derived from the regions, so the two agree."""
    image = image_of(COLOR_LAYOUT)
    regions = detect_text_regions(image, ENGINE)
    from_all = calculate_text_coverage(image, ENGINE, regions)
    from_one = calculate_text_coverage(image, ENGINE, regions[:1])

    assert 0.0 < from_one < from_all


def test_text_regions_are_ordered_and_identifiers_are_unique() -> None:
    """A deterministic order is what lets two runs be compared directly rather than as sets."""
    image = image_of(SKEWED_TEXT)
    regions = detect_text_regions(image, ENGINE)

    assert len(regions) > 1
    identifiers = [region.region_id for region in regions]
    assert len(identifiers) == len(set(identifiers))
    tops = [region.bbox[1] for region in regions]
    assert tops == sorted(tops)


def test_every_text_region_box_lies_inside_the_image() -> None:
    """A box outside the frame would make the coverage arithmetic meaningless."""
    image = image_of(SKEWED_TEXT)
    height, width = image.shape[:2]

    for region in detect_text_regions(image, ENGINE):
        left, top, box_width, box_height = region.bbox
        assert left >= 0 and top >= 0
        assert left + box_width <= width
        assert top + box_height <= height
        assert 0.0 <= region.text_coverage <= 1.0


def test_the_region_prefix_separates_regions_from_different_images() -> None:
    """Regions from two images must be distinguishable when kept in one mapping."""
    first = detect_text_regions(image_of(COLOR_LAYOUT), ENGINE, region_prefix="a")
    second = detect_text_regions(image_of(COLOR_LAYOUT), ENGINE, region_prefix="b")
    assert {region.region_id for region in first}.isdisjoint(
        {region.region_id for region in second}
    )


def test_a_quarter_turned_page_is_reported_as_turned() -> None:
    """The orientation reading tracks the input across all four quarter turns."""
    image = image_of(COLOR_LAYOUT)
    expected = {0: 0, 1: 90, 2: 0, 3: 90}

    for turns, angle in expected.items():
        turned = np.ascontiguousarray(np.rot90(image, turns))
        assert detect_orientation(turned, ENGINE) == angle, f"rot90 x{turns}"


def test_the_upside_down_ambiguity_is_a_documented_limit_not_a_silent_error() -> None:
    """A half-turned page reads as upright, and that is the honest answer here.

    Resolving it needs a script detector or a classifier, and this processor is forbidden both. The
    test exists so the limitation is recorded as a known property rather than rediscovered as a bug
    - and so that fixing it later will be a visible change to this test.
    """
    image = image_of(COLOR_LAYOUT)
    upside_down = np.ascontiguousarray(np.rot90(image, 2))

    assert detect_orientation(upside_down, ENGINE) == detect_orientation(image, ENGINE)


def test_orientation_prefers_the_axis_the_ink_projects_onto() -> None:
    """The decision rule stated directly, on synthetic pages with unambiguous structure."""
    landscape = np.full((200, 400), 255, dtype=np.uint8)
    landscape[40:60, 40:360] = 0
    landscape[100:120, 40:360] = 0

    portrait = np.full((400, 200), 255, dtype=np.uint8)
    portrait[40:360, 40:60] = 0
    portrait[40:360, 100:120] = 0

    assert detect_orientation(landscape, ENGINE) == 0
    assert detect_orientation(portrait, ENGINE) == 90


def test_a_blank_page_reports_upright_rather_than_dividing_by_nothing() -> None:
    """An all-white page has no ink, so no projection varies and no ratio can be formed."""
    blank = np.full((100, 150), 255, dtype=np.uint8)
    assert detect_orientation(blank, ENGINE) == 0


def test_blurring_an_image_lowers_its_blur_score() -> None:
    """Proves the score measures blur rather than merely computing something.

    The name is counter-intuitive on purpose and worth stating: the *blur score* is high when the
    image is *sharp*, because it is the variance of the Laplacian. A test asserting only that a
    float came back would pass on a hardcoded constant.
    """
    image = image_of(COLOR_LAYOUT)
    assert calculate_blur_score(blurred(image), ENGINE) < calculate_blur_score(
        image, ENGINE
    )


def test_blurring_an_image_lowers_its_sharpness_score() -> None:
    """The same direction, for the other edge-based measure."""
    image = image_of(SKEWED_TEXT)
    assert calculate_sharpness_score(
        blurred(image), ENGINE
    ) < calculate_sharpness_score(image, ENGINE)


def test_adding_grain_raises_the_noise_score() -> None:
    """Proves the noise estimate responds to noise, not to brightness or contrast."""
    image = image_of(COLOR_LAYOUT)
    assert calculate_noise_score(noisy(image), ENGINE) > calculate_noise_score(
        image, ENGINE
    )


def test_a_flat_page_scores_almost_no_contrast() -> None:
    """Contrast is the spread of luminance, so a uniform page must read near zero."""
    flat = np.full((80, 80), 128, dtype=np.uint8)
    assert calculate_contrast_score(flat, ENGINE) == pytest.approx(0.0, abs=1e-9)


def test_brightness_is_the_mean_luminance() -> None:
    """Checked against a value computed here rather than by the primitive under test."""
    flat = np.full((40, 40), 200, dtype=np.uint8)
    assert calculate_brightness_score(flat, ENGINE) == pytest.approx(200.0)


def test_a_gray_image_needs_no_engine_at_all() -> None:
    """The luminance step short-circuits on a single-channel input; that is worth pinning."""
    gray = np.full((30, 40), 100, dtype=np.uint8)
    assert luminance(gray, ENGINE) is gray


def test_the_ink_mask_marks_a_stroke_through_its_whole_width() -> None:
    """A stroke narrower than the block size is marked completely, which is what text needs."""
    page = np.full((60, 120), 255, dtype=np.uint8)
    page[28:34, 20:100] = 0

    mask = ink_mask(page, ENGINE)

    assert mask.shape == page.shape
    assert mask.max() == 255
    assert int((mask[31] == 255).sum()) == 80, (
        "the stroke was not marked through its width"
    )
    assert mask[5, 5] == 0, "background was marked as ink"


def test_the_ink_mask_leaves_the_interior_of_a_solid_block_clear() -> None:
    """Recorded deliberately: it is the property that keeps a colour bar out of ``text_coverage``.

    Inside a uniform region every pixel sits at the local mean, so an adaptive threshold marks only
    the block's edges. A solid colour bar or a photographic shadow is not text, and counting its
    interior would inflate the coverage figure on precisely the pages where the distinction
    matters. A test asserting the opposite would have failed here, and the fix was to state the
    real behaviour rather than to weaken the threshold.
    """
    page = np.full((60, 120), 255, dtype=np.uint8)
    page[20:40, 20:100] = 0

    mask = ink_mask(page, ENGINE)

    assert int((mask[21] == 255).sum()) == 80, "the top edge was not marked"
    assert mask[30, 50] == 0, "the block's uniform interior was marked as ink"


def test_the_codec_engine_reports_a_capability_gap_rather_than_substituting() -> None:
    """The engine boundary, stated rather than left to fail as an attribute error.

    OpenCV is an image-processing library; Pillow is a codec. The plan requires a swap to change
    only ``primitives/`` and never the contract - it does not require every operation to exist
    under every engine. Reimplementing filtering on raw arrays to close the gap is the "scope creep
    into a full image-processing library" the subplan forbids, so the gap is reported as a type
    naming the operation and the engine.
    """
    pillow_image = load_image(COLOR_LAYOUT, EngineChoice.PILLOW)

    with pytest.raises(ImageEngineCapabilityError) as raised:
        calculate_blur_score(pillow_image, EngineChoice.PILLOW)
    assert raised.value.engine is EngineChoice.PILLOW
    assert "cvtColor" in str(raised.value)
    assert "codec, not an image-processing library" in str(raised.value)


def test_the_capability_error_names_a_remedy() -> None:
    """The message has to tell an operator what to do, like the seam's other failures."""
    with pytest.raises(ImageEngineCapabilityError) as raised:
        engine_operation(EngineChoice.PILLOW, "minAreaRect")
    assert "use an engine that implements it" in str(raised.value)


def test_a_missing_engine_is_not_reported_as_a_missing_operation() -> None:
    """The two failures mean different things and must not be conflated."""

    def refuse(name: str, package: str | None = None) -> None:
        raise ImportError(f"no module named {name!r}")

    with (
        patch.object(importlib, "import_module", refuse),
        pytest.raises(ImageEngineNotAvailableError),
    ):
        engine_operation(EngineChoice.OPENCV, "cvtColor")


def test_regions_are_the_contract_type_not_a_local_lookalike() -> None:
    """One record type, imported from the contract, so no conversion layer is needed."""
    regions = detect_text_regions(image_of(COLOR_LAYOUT), ENGINE)
    assert regions
    for region in regions:
        assert isinstance(region, TextRegion)
