# pylint: disable=duplicate-code
# The fixture constants repeat the other image suites' on purpose. A shared helper module would let
# a change made for one suite silently redirect another's; the duplication is a handful of
# lines per suite and the independence is worth the noise.
"""Tests for the normalization pipeline and its artifact (``IMG-07``).

The WBS names two acceptance criteria: with ``normalize=true`` the artifact exists and
``transformations`` lists every applied operation, and with ``normalize=false`` nothing is produced
and nothing is raised. Both are here.

The rest of the module tests the property that makes those two criteria meaningful: **every
transformation is justified**. The plan's risk table names "over-eager enhancement degrades
information - binarization destroying colour" and prescribes "apply transformations only when
justified by metrics + explicit options". So the tests below check all four combinations of
"flag set" and "correction needed": each correction fires only when both are true, and nothing is
applied to a page that is already fine.

Two limits are pinned deliberately rather than hidden, because both are properties of the problem:

* the **direction** of a quarter-turn correction is not decidable without reading the page's
  content, which is out of bounds here, so only the magnitude is corrected;
* the contrast stretch **recovers very little** on a genuinely washed-out page, so the pipeline
  records it as applied rather than as successful.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from docflow.image.contracts import ArtifactRef, ImageOptions
from docflow.image.primitives.analysis import (
    calculate_brightness_score,
    calculate_contrast_score,
    detect_orientation,
    detect_skew_angle,
)
from docflow.image.primitives.analyze import analyze_image
from docflow.image.primitives.engine import EngineChoice
from docflow.image.primitives.load import get_image_metadata, load_image
from docflow.image.primitives.normalize import (
    MIN_ACCEPTABLE_BRIGHTNESS,
    MIN_ACCEPTABLE_CONTRAST,
    NORMALIZED_ARTIFACT_KIND,
    NORMALIZED_FILE_NAME,
    TARGET_BRIGHTNESS,
    TRANSFORMATION_BRIGHTNESS,
    TRANSFORMATION_CONTRAST,
    TRANSFORMATION_DESKEW,
    TRANSFORMATION_ORIENTATION,
    normalize_image,
    prepare_normalized_image,
)
from docflow.image.primitives.transform import turn_quarter

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "image"
COLOR_LAYOUT = FIXTURES / "color_layout.png"
SKEWED_TEXT = FIXTURES / "skewed_text.png"

ENGINE = EngineChoice.OPENCV

UNDEREXPOSED_SCALE = 0.3
"""Multiplier that puts a page's mean luminance below the brightness threshold.

Measured: the fixture spread means of 55 at this scale, against a threshold of 100.
"""

WASHED_OUT_SCALE = 0.4
WASHED_OUT_FLOOR = 200
"""Scale-and-lift that compresses a page's range without darkening its mean.

Produces a spread of 39 against a threshold of 45, which the mean alone would not reveal.
"""

FLIP_SCALE = 0.02
FLIP_FLOOR = 91
"""Scale-and-lift that puts a page just under the brightness threshold with almost no contrast.

Measured: brightness 95.22 and contrast 1.81, so both corrections look justified from the snapshot -
but the contrast stretch alone lifts the mean to 103.69, past the threshold of 100, which is what
makes the re-measurement observable. A wider window does not work: the stretch only moves the mean a
few points, so a page comfortably below the threshold stays below it either way.
"""


def options(**overrides: bool) -> ImageOptions:
    """Return a fully specified option set with normalization on by default."""
    settings = {
        "normalize": True,
        "prepare_for_ocr": False,
        "prepare_for_vlm": False,
        "correct_orientation": True,
        "deskew": True,
    }
    settings.update(overrides)
    return ImageOptions(**settings)


def digest(path: Path) -> str:
    """Return a hash of a file's bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def underexposed(image: np.ndarray) -> np.ndarray:
    """Return a page whose exposure is below the threshold."""
    return np.clip(image.astype(np.float64) * UNDEREXPOSED_SCALE, 0, 255).astype(
        np.uint8
    )


def washed_out(image: np.ndarray) -> np.ndarray:
    """Return a page whose range is compressed while its mean stays high."""
    lifted = image.astype(np.float64) * WASHED_OUT_SCALE + WASHED_OUT_FLOOR * (
        1 - WASHED_OUT_SCALE
    )
    return np.clip(lifted, 0, 255).astype(np.uint8)


def analyze(image: np.ndarray) -> object:
    """Return the metrics snapshot for an in-memory page.

    The file is written to a temporary path beside a real fixture so ``analyze_image`` has facts to
    read; the metrics it returns come from the array, which is what the pipeline decides on.
    """
    return analyze_image(image, COLOR_LAYOUT, ENGINE)


def test_normalizing_a_valid_png_publishes_the_artifact(tmp_path: Path) -> None:
    """The first WBS acceptance criterion, stated as the scenario it describes."""
    image = load_image(COLOR_LAYOUT, ENGINE)
    metrics = analyze_image(image, COLOR_LAYOUT, ENGINE)
    output_dir = tmp_path / "image"

    normalized, transformations = normalize_image(image, metrics, options(), ENGINE)
    reference = prepare_normalized_image(
        normalized, output_dir, options(), transformations, ENGINE
    )

    assert (output_dir / NORMALIZED_FILE_NAME).is_file()
    assert reference is not None
    assert reference.path == output_dir / NORMALIZED_FILE_NAME


def test_the_recorded_transformations_are_the_ones_that_ran() -> None:
    """The second half of that criterion: the list is not decorative.

    Cross-checked against the pixels, not against another call to the pipeline. A skewed page must
    report the deskew and must come out measurably straighter; if the record named a transformation
    the pixels do not show, this fails.
    """
    image = load_image(SKEWED_TEXT, ENGINE)
    metrics = analyze_image(image, SKEWED_TEXT, ENGINE)

    normalized, transformations = normalize_image(image, metrics, options(), ENGINE)

    assert TRANSFORMATION_DESKEW in transformations
    assert abs(detect_skew_angle(normalized, ENGINE)) < 0.5
    assert abs(detect_skew_angle(image, ENGINE)) > 3.0, (
        "the fixture is supposed to be skewed"
    )


def test_normalize_false_produces_nothing_and_raises_nothing(tmp_path: Path) -> None:
    """The second WBS acceptance criterion, including the "no error" half."""
    image = load_image(COLOR_LAYOUT, ENGINE)
    metrics = analyze_image(image, COLOR_LAYOUT, ENGINE)
    output_dir = tmp_path / "image"
    off = options(normalize=False)

    normalized, transformations = normalize_image(image, metrics, off, ENGINE)
    reference = prepare_normalized_image(
        normalized, output_dir, off, transformations, ENGINE
    )

    assert reference is None
    # Explicit rather than `not transformations`: the claim is that the tuple is empty, not that
    # it is falsey.
    assert transformations == ()  # pylint: disable=use-implicit-booleaness-not-comparison
    assert not output_dir.exists(), (
        "a directory was created for an artifact nobody asked for"
    )


def test_normalize_false_leaves_the_pixels_untouched() -> None:
    """A disabled pipeline returns its input, not a copy that quietly differs."""
    image = load_image(SKEWED_TEXT, ENGINE)
    metrics = analyze_image(image, SKEWED_TEXT, ENGINE)

    normalized, _ = normalize_image(image, metrics, options(normalize=False), ENGINE)

    assert normalized is image


def test_a_page_that_needs_nothing_is_not_transformed() -> None:
    """The other side of "justified": a fine page must not be "improved"."""
    for fixture in (COLOR_LAYOUT, FIXTURES / "embedded_logo.png"):
        image = load_image(fixture, ENGINE)
        metrics = analyze_image(image, fixture, ENGINE)

        normalized, transformations = normalize_image(image, metrics, options(), ENGINE)

        # Explicit for the same reason as above: an empty tuple is the claim.
        assert (
            transformations == ()  # pylint: disable=use-implicit-booleaness-not-comparison
        ), f"{fixture.name} was transformed unexpectedly"
        assert np.array_equal(normalized, image)


def test_a_skewed_page_is_only_deskewed_when_the_option_is_set() -> None:
    """The flag is a gate, not a hint."""
    image = load_image(SKEWED_TEXT, ENGINE)
    metrics = analyze_image(image, SKEWED_TEXT, ENGINE)

    _, with_flag = normalize_image(image, metrics, options(), ENGINE)
    _, without_flag = normalize_image(image, metrics, options(deskew=False), ENGINE)

    assert TRANSFORMATION_DESKEW in with_flag
    assert TRANSFORMATION_DESKEW not in without_flag


def test_orientation_is_only_corrected_when_the_option_is_set() -> None:
    """And the same for the quarter-turn correction, on a page that needs one."""
    upright = load_image(COLOR_LAYOUT, ENGINE)
    turned = turn_quarter(upright, 1)
    metrics = analyze_image(turned, COLOR_LAYOUT, ENGINE)
    assert metrics.orientation == 90, (
        "the detector should see this page as quarter-turned"
    )

    _, with_flag = normalize_image(turned, metrics, options(), ENGINE)
    _, without_flag = normalize_image(
        turned, metrics, options(correct_orientation=False), ENGINE
    )

    assert TRANSFORMATION_ORIENTATION in with_flag
    assert TRANSFORMATION_ORIENTATION not in without_flag


def test_the_orientation_correction_restores_the_page_shape() -> None:
    """It must exchange width and height, which is what ``rotate_image`` cannot do."""
    upright = load_image(COLOR_LAYOUT, ENGINE)
    turned = turn_quarter(upright, 1)
    assert turned.shape[:2] == upright.shape[:2][::-1]

    metrics = analyze_image(turned, COLOR_LAYOUT, ENGINE)
    normalized, transformations = normalize_image(turned, metrics, options(), ENGINE)

    assert TRANSFORMATION_ORIENTATION in transformations
    assert normalized.shape == upright.shape


def test_an_underexposed_page_is_lifted_towards_the_target() -> None:
    """The correction fires on the measurement and moves the measurement."""
    dark = underexposed(load_image(COLOR_LAYOUT, ENGINE))
    assert calculate_brightness_score(dark, ENGINE) < MIN_ACCEPTABLE_BRIGHTNESS

    metrics = analyze_image(dark, COLOR_LAYOUT, ENGINE)
    normalized, transformations = normalize_image(dark, metrics, options(), ENGINE)

    assert TRANSFORMATION_BRIGHTNESS in transformations
    assert (
        abs(calculate_brightness_score(normalized, ENGINE) - TARGET_BRIGHTNESS) < 10.0
    )


def test_a_bright_page_is_not_darkened() -> None:
    """Brightness is a one-sided correction, and this is the case that would tempt a two-sided one.

    A document's mean is high because most of it is paper. Pulling that towards the midpoint would
    turn paper grey and cost contrast for nothing.
    """
    image = load_image(COLOR_LAYOUT, ENGINE)
    assert calculate_brightness_score(image, ENGINE) > MIN_ACCEPTABLE_BRIGHTNESS

    metrics = analyze_image(image, COLOR_LAYOUT, ENGINE)
    normalized, transformations = normalize_image(image, metrics, options(), ENGINE)

    assert TRANSFORMATION_BRIGHTNESS not in transformations
    assert np.array_equal(normalized, image)


def test_a_washed_out_page_is_treated_as_a_contrast_problem() -> None:
    """The case the mean cannot see: bright *and* flat.

    Its mean is above the brightness threshold, so only the contrast measure catches
    it. Without this
    test a pipeline that read brightness alone would look correct and would silently pass a
    washed-out scan through untouched.
    """
    washed = washed_out(load_image(COLOR_LAYOUT, ENGINE))
    assert calculate_brightness_score(washed, ENGINE) > MIN_ACCEPTABLE_BRIGHTNESS
    assert calculate_contrast_score(washed, ENGINE) < MIN_ACCEPTABLE_CONTRAST

    metrics = analyze_image(washed, COLOR_LAYOUT, ENGINE)
    _, transformations = normalize_image(washed, metrics, options(), ENGINE)

    assert TRANSFORMATION_CONTRAST in transformations


def test_the_contrast_correction_does_not_claim_to_have_fixed_the_page() -> None:
    """Pins the honest limit: it is applied, and the page barely improves.

    Recorded as a test so the limitation is a known property rather than a surprise. The pipeline
    says "applied", never "repaired", and nothing downstream should read the transformation list as
    a quality guarantee.
    """
    washed = washed_out(load_image(COLOR_LAYOUT, ENGINE))
    metrics = analyze_image(washed, COLOR_LAYOUT, ENGINE)

    normalized, transformations = normalize_image(washed, metrics, options(), ENGINE)

    assert TRANSFORMATION_CONTRAST in transformations
    assert calculate_contrast_score(normalized, ENGINE) > calculate_contrast_score(
        washed, ENGINE
    ), "the stretch must not make things worse"
    assert calculate_contrast_score(normalized, ENGINE) < MIN_ACCEPTABLE_CONTRAST, (
        "if this ever passes, the stretch became genuinely effective and this test should say so"
    )


def test_brightness_is_decided_on_the_corrected_pixels_not_the_stale_snapshot() -> None:
    """A contrast stretch lifts the mean a little, and the offset must not then be applied anyway.

    The page is built to sit just below the brightness threshold with almost no contrast, so the
    stretch alone carries it over the line. Measured: brightness 95.22 before the stretch and 103.69
    after, against a threshold of 100.

    This is a narrow window - the stretch only lifts the mean by a few points - and a mutation
    that read the stale snapshot instead of re-measuring survived the whole suite until this
    test existed. The window is the reason: on any ordinary page both readings agree, so only a
    constructed one distinguishes them.
    """
    page = np.clip(
        load_image(SKEWED_TEXT, ENGINE).astype(np.float64) * FLIP_SCALE + FLIP_FLOOR,
        0,
        255,
    ).astype(np.uint8)
    metrics = analyze_image(page, SKEWED_TEXT, ENGINE)
    assert metrics.quality.contrast < MIN_ACCEPTABLE_CONTRAST, (
        "the stretch must be justified"
    )
    assert metrics.quality.brightness < MIN_ACCEPTABLE_BRIGHTNESS, (
        "the offset must look needed"
    )

    _, transformations = normalize_image(page, metrics, options(), ENGINE)

    assert TRANSFORMATION_CONTRAST in transformations
    assert TRANSFORMATION_BRIGHTNESS not in transformations, (
        "the stretch already cleared the brightness threshold, so the offset is not justified"
    )
    assert transformations == (TRANSFORMATION_CONTRAST,), (
        "the contrast correction and nothing else should be reported"
    )


def test_the_artifact_is_described_by_its_own_measurements(tmp_path: Path) -> None:
    """``ArtifactRef`` is built from the written file, not from the request."""
    image = load_image(COLOR_LAYOUT, ENGINE)
    metrics = analyze_image(image, COLOR_LAYOUT, ENGINE)
    output_dir = tmp_path / "image"
    normalized, transformations = normalize_image(image, metrics, options(), ENGINE)

    reference = prepare_normalized_image(
        normalized, output_dir, options(), transformations, ENGINE
    )

    assert isinstance(reference, ArtifactRef)
    assert reference.kind == NORMALIZED_ARTIFACT_KIND
    assert reference.width == image.shape[1]
    assert reference.height == image.shape[0]
    assert reference.format == "PNG"
    assert reference.size == (output_dir / NORMALIZED_FILE_NAME).stat().st_size


def test_the_published_artifact_reloads_to_the_normalized_pixels(
    tmp_path: Path,
) -> None:
    """The file has to contain what the pipeline decided, not something adjacent to it.

    Also the end-to-end check on channel order: a swap introduced anywhere between the
    transformation
    and the encode would show up here rather than in a shape assertion.
    """
    image = load_image(SKEWED_TEXT, ENGINE)
    metrics = analyze_image(image, SKEWED_TEXT, ENGINE)
    output_dir = tmp_path / "image"
    normalized, transformations = normalize_image(image, metrics, options(), ENGINE)

    reference = prepare_normalized_image(
        normalized, output_dir, options(), transformations, ENGINE
    )

    assert np.array_equal(load_image(reference.path, ENGINE), normalized)


def test_the_published_artifact_declares_no_resolution(tmp_path: Path) -> None:
    """Documented consequence of the encoder: a PNG written here carries no ``pHYs``.

    Worth pinning because ``metadata.json`` will report ``resolution: null`` for the artifact while
    the input may have declared one, and that difference should be a known property rather than a
    later surprise.
    """
    image = load_image(COLOR_LAYOUT, ENGINE)
    metrics = analyze_image(image, COLOR_LAYOUT, ENGINE)
    output_dir = tmp_path / "image"
    normalized, transformations = normalize_image(image, metrics, options(), ENGINE)

    reference = prepare_normalized_image(
        normalized, output_dir, options(), transformations, ENGINE
    )

    assert get_image_metadata(reference.path, ENGINE).resolution is None


def test_a_second_run_replaces_the_previous_artifact(tmp_path: Path) -> None:
    """Re-running a processor is normal, and a stale artifact must not block it.

    ``save_image`` refuses an occupied destination, so the pipeline removes the previous artifact
    explicitly rather than relying on an overwrite. This is the behaviour ``IMG-11`` will replace
    with staged writes and a rename.
    """
    image = load_image(COLOR_LAYOUT, ENGINE)
    metrics = analyze_image(image, COLOR_LAYOUT, ENGINE)
    output_dir = tmp_path / "image"
    normalized, transformations = normalize_image(image, metrics, options(), ENGINE)

    first = prepare_normalized_image(
        normalized, output_dir, options(), transformations, ENGINE
    )
    second = prepare_normalized_image(
        normalized, output_dir, options(), transformations, ENGINE
    )

    assert first == second


def test_the_source_file_is_never_written(tmp_path: Path) -> None:
    """The plan requires that a processor leaves its input untouched."""
    before = digest(SKEWED_TEXT)
    image = load_image(SKEWED_TEXT, ENGINE)
    metrics = analyze_image(image, SKEWED_TEXT, ENGINE)
    output_dir = tmp_path / "image"

    normalized, transformations = normalize_image(image, metrics, options(), ENGINE)
    prepare_normalized_image(normalized, output_dir, options(), transformations, ENGINE)

    assert digest(SKEWED_TEXT) == before


def test_source_directories_are_never_named() -> None:
    """A structural guard: the module has no knowledge of the other processors' namespaces."""
    module = (
        Path(__file__).resolve().parents[3]
        / "src/docflow/image/primitives/normalize.py"
    )
    source = module.read_text(encoding="utf-8")

    for forbidden in ("source", "render", "native_text", "ocr/", "llm/", "var/tools"):
        assert forbidden not in source, (
            f"normalize.py reached outside its namespace: {forbidden}"
        )


def test_the_artifact_lands_inside_the_directory_it_was_given(tmp_path: Path) -> None:
    """The module never chooses its own output root; ownership stays with the caller."""
    output_dir = tmp_path / "elsewhere" / "image"
    image = load_image(COLOR_LAYOUT, ENGINE)
    metrics = analyze_image(image, COLOR_LAYOUT, ENGINE)
    normalized, transformations = normalize_image(image, metrics, options(), ENGINE)

    reference = prepare_normalized_image(
        normalized, output_dir, options(), transformations, ENGINE
    )

    assert reference is not None
    assert reference.path.parent == output_dir


def test_a_reading_the_detector_cannot_produce_is_refused() -> None:
    """A 45-degree orientation is not one of the detector's values, and guessing would be worse."""
    image = load_image(COLOR_LAYOUT, ENGINE)
    metrics = analyze_image(image, COLOR_LAYOUT, ENGINE)
    impossible = replace(metrics, orientation=45)

    with pytest.raises(ValueError, match="not one of its values"):
        normalize_image(image, impossible, options(), ENGINE)


def test_the_orientation_direction_is_not_guessed() -> None:
    """Pins a documented limit: the magnitude is corrected, the direction is not decided.

    A quarter-turn reading says the page is turned but not which way - turning it either way leaves
    the ink projecting along the rows, which is all the detector can see. Resolving the direction
    needs the page's content, and reading it would mean OCR or a classifier, both out of bounds for
    this processor. The correction is therefore applied in one fixed direction and the result is
    reported as a quarter turn of the *shape*, not as an upright page.
    """
    upright = load_image(COLOR_LAYOUT, ENGINE)
    turned = turn_quarter(upright, 3)
    metrics = analyze_image(turned, COLOR_LAYOUT, ENGINE)

    normalized, transformations = normalize_image(turned, metrics, options(), ENGINE)

    assert TRANSFORMATION_ORIENTATION in transformations
    assert normalized.shape == upright.shape
    # Either one or three quarter turns leaves an odd-turn page with the right dimensions, so the
    # only honest assertion is on the shape - which is exactly what this test records.
    assert detect_orientation(normalized, ENGINE) == 0
