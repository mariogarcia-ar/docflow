"""Tests for the transformation primitives (``IMG-05``).

The WBS names two acceptance criteria: ``convert_to_grayscale`` yields a single channel with the
source file unchanged, and ``deskew_image`` with the detected angle writes to a distinct path. Both
are here. So are the two properties the task is really responsible for:

* **Nothing is mutated in place.** Every transform returns a new array and leaves its argument
  alone. ``IMG-07`` records each transformation it applies, and a function that edited its input
  would make that record describe a side effect rather than a returned value.
* **Each operation moves its metric the way it claims.** Rotating by the detected skew straightens
  the page, denoising lowers the noise estimate, sharpening raises the blur score, and a lossless
  round-trip returns identical pixels. A test that only checked a shape came back would pass on a
  function that returned its own input.

The channel-order tests are the ones worth reading first. They exist because a real defect was found
during development: the seam normalises every image to RGB, OpenCV's encoders expect BGR, and
``imdecode`` hands back BGR again - so encoding converted the channels and decoding did not convert
them back. Every file written through a round-trip had red and blue swapped. A per-operation test
would not have caught it, because each operation was individually correct.
"""

# pylint: disable=duplicate-code
# The fixture constants repeat `test_analysis.py`'s on purpose. A shared helper module would let a
# change to one suite's fixtures silently redirect the other's assertions; the duplication is two
# lines per suite and the noise is worth the independence. `TRANSFORMS` below is this module's own
# list, not a copy, so a new primitive cannot be forgotten from the mutation guard.
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest

from docflow.image.primitives import transform
from docflow.image.primitives.analysis import (
    calculate_blur_score,
    calculate_brightness_score,
    calculate_contrast_score,
    calculate_noise_score,
    detect_skew_angle,
)
from docflow.image.primitives.engine import (
    EngineChoice,
    ImageEngineCapabilityError,
)
from docflow.image.primitives.failures import ImagePrimitiveError
from docflow.image.primitives.load import load_image

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "image"
COLOR_LAYOUT = FIXTURES / "color_layout.png"
SKEWED_TEXT = FIXTURES / "skewed_text.png"

ENGINE = EngineChoice.OPENCV
"""The engine every transformation test uses.

Not parameterised over both engines. Pillow is a codec and provides neither ``warpAffine``,
``cvtColor`` nor ``resize``, which
``test_the_codec_engine_reports_a_capability_gap_rather_than_substituting`` asserts explicitly.
"""

BAR_ROW = 40
"""A row inside ``color_layout.png``'s three colour bars, where a channel swap is unmissable."""

NOISE_SIGMA = 22.0
"""Synthetic grain used to give the denoiser something to remove."""

TRANSFORMS = (
    "rotate_image",
    "deskew_image",
    "resize_image",
    "convert_to_grayscale",
    "binarize_image",
    "denoise_image",
    "sharpen_image",
    "normalize_contrast",
    "normalize_brightness",
    "convert_image_format",
    "compress_image",
)
"""Every public primitive, so the "does not mutate" guard cannot omit one by accident."""


def digest(path: Path) -> str:
    """Return a hash of a file's bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def call_transform(name: str, image: np.ndarray, *extra: object) -> np.ndarray:
    """Call a transform by name with the extra arguments that particular one needs."""
    function = getattr(transform, name)
    if name in {"rotate_image", "deskew_image"}:
        return function(image, *(extra or (4.0,)), ENGINE)
    if name == "resize_image":
        return function(image, *(extra or (120, 80)), ENGINE)
    if name == "convert_image_format":
        return function(image, *(extra or ("png",)), ENGINE)
    if name == "compress_image":
        return function(image, *(extra or (60,)), ENGINE)
    return function(image, *extra, ENGINE)


@pytest.mark.parametrize("name", TRANSFORMS)
def test_every_transform_returns_a_new_array_and_leaves_the_input_alone(
    name: str,
) -> None:
    """The guarantee IMG-07's transformation record depends on."""
    image = load_image(COLOR_LAYOUT, ENGINE)
    before = image.copy()

    result = call_transform(name, image)

    assert result is not image, f"{name} returned its own argument"
    assert np.array_equal(image, before), f"{name} modified the array it was given"


@pytest.mark.parametrize("name", TRANSFORMS)
def test_every_transform_leaves_the_source_file_untouched(name: str) -> None:
    """The plan requires transforms to operate on arrays; the file must not be an outlet.

    Also checked structurally, by asserting the module has no route to a path at all, so the
    guarantee does not rest on a test having covered the right branch.
    """
    before = digest(COLOR_LAYOUT)
    call_transform(name, load_image(COLOR_LAYOUT, ENGINE))
    assert digest(COLOR_LAYOUT) == before

    module = Path(transform.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "open(",
        "imwrite",
        "write_bytes",
        "Path(",
        "os.remove",
        "shutil",
    ):
        assert forbidden not in module, (
            f"transform.py gained a filesystem route: {forbidden}"
        )


@pytest.mark.parametrize("name", TRANSFORMS)
def test_every_transform_preserves_the_uint8_dtype_and_a_sane_shape(name: str) -> None:
    """A transform that silently rescaled to floats would break every consumer downstream."""
    result = call_transform(name, load_image(COLOR_LAYOUT, ENGINE))

    assert result.dtype == np.uint8
    assert result.ndim in {2, 3}
    assert result.shape[0] > 0 and result.shape[1] > 0


def test_rotation_keeps_the_input_dimensions() -> None:
    """The documented choice: the frame stays the same size and the corners are cropped."""
    image = load_image(COLOR_LAYOUT, ENGINE)
    assert transform.rotate_image(image, 12.0, ENGINE).shape == image.shape


def test_a_full_turn_returns_the_image_to_itself() -> None:
    """A rotation of 360 degrees must be the identity, which pins the direction convention too."""
    image = load_image(COLOR_LAYOUT, ENGINE)
    restored = transform.rotate_image(image, 360.0, ENGINE)
    assert np.abs(restored.astype(int) - image.astype(int)).mean() < 1.0


def test_rotation_actually_rotates() -> None:
    """Guards a function that returns its input unchanged, which every shape test would accept."""
    image = load_image(COLOR_LAYOUT, ENGINE)
    turned = transform.rotate_image(image, 30.0, ENGINE)
    assert not np.array_equal(turned, image)


def test_deskew_with_the_detected_angle_straightens_the_page() -> None:
    """The WBS acceptance criterion, stated as the correction rather than as a non-zero reading.

    The detector and the corrector must agree on the sign. Passing the detected angle through
    unchanged is what the engine requires; inverting it would double the tilt, and this test is what
    would fail if someone "fixed" the sign by reasoning about it instead of measuring.
    """
    image = load_image(SKEWED_TEXT, ENGINE)
    detected = detect_skew_angle(image, ENGINE)
    assert detected != 0.0, "the fixture is supposed to be skewed"

    straightened = transform.deskew_image(image, detected, ENGINE)

    assert abs(detect_skew_angle(straightened, ENGINE)) < 0.5


def test_deskew_does_not_touch_the_input_file() -> None:
    """The WBS criterion mentions a distinct path; here nothing is written at all."""
    before = digest(SKEWED_TEXT)
    image = load_image(SKEWED_TEXT, ENGINE)
    transform.deskew_image(image, detect_skew_angle(image, ENGINE), ENGINE)
    assert digest(SKEWED_TEXT) == before


def test_resize_produces_exactly_the_requested_size() -> None:
    """Exact, not approximately: the metrics downstream are computed on these dimensions."""
    image = load_image(COLOR_LAYOUT, ENGINE)
    for width, height in ((100, 50), (480, 320), (240, 160)):
        assert transform.resize_image(image, width, height, ENGINE).shape[:2] == (
            height,
            width,
        )


def test_resize_refuses_a_dimension_that_cannot_form_an_image() -> None:
    """Zero and negative sizes are refused, not clamped to one pixel."""
    image = load_image(COLOR_LAYOUT, ENGINE)
    for width, height in ((0, 10), (10, 0), (-5, 10)):
        with pytest.raises(ImagePrimitiveError) as raised:
            transform.resize_image(image, width, height, ENGINE)
        assert raised.value.error_type == "TRANSFORMATION_ERROR"


def test_grayscale_has_a_single_channel_and_keeps_the_dimensions() -> None:
    """The WBS acceptance criterion."""
    image = load_image(COLOR_LAYOUT, ENGINE)
    gray = transform.convert_to_grayscale(image, ENGINE)
    assert gray.ndim == 2
    assert gray.shape == image.shape[:2]


def test_grayscale_of_an_already_gray_image_is_not_a_second_conversion() -> None:
    """Applying it twice must not crash or change the shape."""
    once = transform.convert_to_grayscale(load_image(COLOR_LAYOUT, ENGINE), ENGINE)
    twice = transform.convert_to_grayscale(once, ENGINE)
    assert twice.shape == once.shape


def test_binarization_leaves_exactly_two_levels() -> None:
    """Whatever the threshold, the result is two tones and nothing between them."""
    image = load_image(COLOR_LAYOUT, ENGINE)
    for threshold in (0, 128, 255, None):
        levels = np.unique(transform.binarize_image(image, ENGINE, threshold))
        assert set(levels.tolist()) <= {0, 255}


def test_an_explicit_threshold_is_the_one_used() -> None:
    """Two different cuts must produce two different images, or the argument is being ignored."""
    image = load_image(COLOR_LAYOUT, ENGINE)
    low = transform.binarize_image(image, ENGINE, 40)
    high = transform.binarize_image(image, ENGINE, 220)
    assert not np.array_equal(low, high)


def test_a_threshold_outside_the_luminance_range_is_refused() -> None:
    """300 is not a luminance; clamping it to 255 would be a silent stand-in."""
    image = load_image(COLOR_LAYOUT, ENGINE)
    for threshold in (-1, 256, 1000):
        with pytest.raises(ImagePrimitiveError) as raised:
            transform.binarize_image(image, ENGINE, threshold)
        assert raised.value.error_type == "TRANSFORMATION_ERROR"


def test_binarization_discards_colour_for_good() -> None:
    """The destructive property the plan's risk table names, asserted rather than assumed.

    It is the reason ``IMG-07`` only binarizes when a metric justifies it, so the loss is pinned
    here where the primitive is tested rather than discovered later.
    """
    image = load_image(COLOR_LAYOUT, ENGINE)
    binarized = transform.binarize_image(image, ENGINE, 128)
    assert binarized.ndim == 2, "a binarized image cannot still carry colour"
    assert len(np.unique(binarized)) <= 2


def test_denoising_lowers_the_noise_estimate() -> None:
    """The metric the operation claims to improve, measured rather than assumed."""
    image = load_image(COLOR_LAYOUT, ENGINE)
    generator = np.random.default_rng(20260922)
    grain = generator.normal(0.0, NOISE_SIGMA, image.shape)
    noisy = np.clip(image.astype(np.float64) + grain, 0, 255).astype(np.uint8)

    assert calculate_noise_score(transform.denoise_image(noisy, ENGINE), ENGINE) < (
        calculate_noise_score(noisy, ENGINE)
    )


def test_denoising_keeps_the_channel_structure() -> None:
    """Colour stays colour and grayscale stays single-channel."""
    colour = load_image(COLOR_LAYOUT, ENGINE)
    assert transform.denoise_image(colour, ENGINE).ndim == 3
    assert (
        transform.denoise_image(
            transform.convert_to_grayscale(colour, ENGINE), ENGINE
        ).ndim
        == 2
    )


def test_sharpening_raises_the_blur_score_after_the_image_was_softened() -> None:
    """Sharpening must move the metric the measurement actually reads.

    The image is softened first, because unsharp masking on an already-sharp fixture barely moves
    the Laplacian variance - and a test that passes on a no-op is not a test.
    """
    softened = transform.rotate_image(load_image(COLOR_LAYOUT, ENGINE), 7.0, ENGINE)
    sharpened = transform.sharpen_image(softened, ENGINE)

    assert calculate_blur_score(sharpened, ENGINE) > calculate_blur_score(
        softened, ENGINE
    )


def test_sharpening_does_not_wrap_bright_edges_to_black() -> None:
    """An unclamped offset would turn white paper black at every strong edge."""
    page = np.zeros((40, 40, 3), dtype=np.uint8)
    page[10:30, 10:30] = 255

    sharpened = transform.sharpen_image(page, ENGINE)

    assert sharpened.max() <= 255
    assert sharpened.min() >= 0, "an offset wrapped the range and produced black"
    assert sharpened[20, 20].tolist() == [255, 255, 255], (
        "a flat white region was pulled down"
    )


def test_brightness_normalisation_moves_the_mean_towards_the_target() -> None:
    """The metric it claims to change, in the direction asked for."""
    image = load_image(COLOR_LAYOUT, ENGINE)
    before = calculate_brightness_score(image, ENGINE)

    for target in (90.0, 200.0):
        shifted = transform.normalize_brightness(image, ENGINE, target=target)
        after = calculate_brightness_score(shifted, ENGINE)
        assert abs(after - target) < abs(before - target)


def test_a_target_outside_the_luminance_range_is_refused() -> None:
    """999 is not a luminance level, and clamping it would be a silent stand-in."""
    image = load_image(COLOR_LAYOUT, ENGINE)
    with pytest.raises(ImagePrimitiveError):
        transform.normalize_brightness(image, ENGINE, target=999.0)


def test_brightness_normalisation_does_not_wrap_around() -> None:
    """Adding to a bright page without clamping turns it black."""
    bright = np.full((30, 30, 3), 250, dtype=np.uint8)

    shifted = transform.normalize_brightness(bright, ENGINE, target=255.0)

    assert shifted.min() >= 250, "an offset wrapped the range and produced black"


def test_contrast_normalisation_raises_contrast_on_a_low_contrast_image() -> None:
    """The operation's own claim, on an image with almost nothing to stretch."""
    flat = np.full((80, 120, 3), 128, dtype=np.uint8)
    flat[20:40, 20:100] = 134

    stretched = transform.normalize_contrast(flat, ENGINE)

    assert calculate_contrast_score(stretched, ENGINE) > calculate_contrast_score(
        flat, ENGINE
    )


def test_contrast_normalisation_does_not_recolour_a_page() -> None:
    """Stretching the channels independently would shift the hue, which is why CIELAB is used."""
    image = load_image(COLOR_LAYOUT, ENGINE)
    stretched = transform.normalize_contrast(image, ENGINE)

    # The bars are pure green, red and blue; a hue shift would make them impure.
    bar_width = image.shape[1] // 3
    for column, expected_channel in (
        (bar_width // 2, 1),
        (bar_width + bar_width // 2, 0),
        (2 * bar_width + bar_width // 2, 2),
    ):
        pixel = stretched[BAR_ROW, column]
        dominant = int(np.argmax(pixel))
        assert dominant == expected_channel, (
            f"hue shifted at column {column}: {pixel.tolist()}"
        )


def test_a_lossless_round_trip_returns_identical_pixels() -> None:
    """PNG carries the pixels exactly, so anything but equality is a defect.

    This is the test that caught the channel-order asymmetry: encoding converted RGB to BGR and
    decoding did not convert it back, so every written file had red and blue swapped. Each operation
    was individually correct, which is why no per-operation test found it.
    """
    image = load_image(COLOR_LAYOUT, ENGINE)
    assert np.array_equal(transform.convert_image_format(image, "png", ENGINE), image)


def test_a_lossy_round_trip_preserves_the_channel_order() -> None:
    """JPEG loses detail, but it must not lose which channel is which."""
    image = load_image(COLOR_LAYOUT, ENGINE)

    restored = transform.convert_image_format(image, "jpg", ENGINE)

    green, red, blue = (
        restored[BAR_ROW, image.shape[1] // 6],
        restored[BAR_ROW, image.shape[1] // 2],
        restored[BAR_ROW, 5 * image.shape[1] // 6],
    )
    assert int(np.argmax(green)) == 1, f"green bar is not green: {green.tolist()}"
    assert int(np.argmax(red)) == 0, f"red bar is not red: {red.tolist()}"
    assert int(np.argmax(blue)) == 2, f"blue bar is not blue: {blue.tolist()}"


def test_an_unknown_container_is_refused_before_the_engine_sees_it() -> None:
    """The engine's answer for an unknown extension is a native exception, not a value."""
    image = load_image(COLOR_LAYOUT, ENGINE)

    with pytest.raises(ImagePrimitiveError) as raised:
        transform.convert_image_format(image, "xyz", ENGINE)
    assert raised.value.error_type == "TRANSFORMATION_ERROR"
    assert "no encoder" in str(raised.value)


def test_lower_compression_quality_loses_more_detail() -> None:
    """The knob has to do something, and a lower quality has to lose more."""
    image = load_image(SKEWED_TEXT, ENGINE)

    high = transform.compress_image(image, 95, ENGINE)
    low = transform.compress_image(image, 20, ENGINE)

    high_error = np.abs(high.astype(int) - image.astype(int)).mean()
    low_error = np.abs(low.astype(int) - image.astype(int)).mean()
    assert low_error > high_error


def test_compression_quality_outside_the_codec_range_is_refused() -> None:
    """Clamping to 1 or 100 would substitute a quality the caller never asked for."""
    image = load_image(COLOR_LAYOUT, ENGINE)
    for quality in (0, -5, 101):
        with pytest.raises(ImagePrimitiveError) as raised:
            transform.compress_image(image, quality, ENGINE)
        assert raised.value.error_type == "TRANSFORMATION_ERROR"


def test_a_grayscale_image_round_trips_through_a_container() -> None:
    """The single-channel path must not be promoted to three channels by an encode."""
    gray = transform.convert_to_grayscale(load_image(COLOR_LAYOUT, ENGINE), ENGINE)
    assert transform.convert_image_format(gray, "png", ENGINE).ndim == 2


def test_the_codec_engine_reports_a_capability_gap_rather_than_substituting() -> None:
    """The engine boundary, stated rather than left to fail as an attribute error.

    OpenCV is an image-processing library and Pillow is a codec, so Pillow provides none of the
    operations these primitives are built on. The plan requires a swap to change only
    ``primitives/`` and never the contract; it does not require every operation under every engine,
    and reimplementing warping on raw arrays is the scope creep the subplan forbids.
    """
    pillow_image = load_image(COLOR_LAYOUT, EngineChoice.PILLOW)

    with pytest.raises(ImageEngineCapabilityError) as raised:
        transform.rotate_image(pillow_image, 5.0, EngineChoice.PILLOW)
    assert raised.value.engine is EngineChoice.PILLOW
    assert "warpAffine" in str(raised.value)
    assert "codec, not an image-processing library" in str(raised.value)


def test_the_private_helpers_stay_private() -> None:
    """The public surface is the WBS list and the named thresholds, nothing else."""
    exported = set(transform.__all__)
    for name in TRANSFORMS:
        assert name in exported
    assert "BINARIZATION_THRESHOLD" in exported
    assert not [name for name in exported if name.startswith("_")]
