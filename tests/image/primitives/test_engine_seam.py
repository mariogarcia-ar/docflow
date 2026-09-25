"""Tests for the OpenCV seam and the primitives that reach it (``IMG-02`` … ``IMG-08``).

Every assertion here is about **our** translation: the facts we collect, the failures we type,
the pipelines we compose and the artifacts we name. Nothing asserts what OpenCV computes — the
double answers with arrays of its own (`README.md` §9.7), and where a reading is asserted it is
over a synthetic array whose arithmetic a reader can check by hand.

The double is installed for every test by the package's autouse fixture, so no case here can
reach the library on the machine.
"""

from __future__ import annotations

import struct
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from docflow.image import (
    ArtifactRef,
    ImageMetrics,
    ImageOptions,
    ImageQualityMetrics,
)
from docflow.image.primitives import (
    CONTRAST_MIN,
    NOISE_MAX,
    ImagePrimitiveError,
    analyze_image,
    calculate_blur_score,
    calculate_brightness_score,
    calculate_contrast_score,
    calculate_noise_score,
    calculate_sharpness_score,
    calculate_text_coverage,
    classify_image,
    compress_image,
    convert_image_format,
    convert_to_grayscale,
    denoise_image,
    deskew_image,
    detect_orientation,
    detect_skew_angle,
    detect_text_regions,
    get_image_channels,
    get_image_dimensions,
    get_image_metadata,
    image_engine_version,
    load_image,
    normalize_contrast,
    prepare_image_for_ocr,
    prepare_image_for_vlm,
    resize_image,
    rotate_image,
    save_image,
    sharpen_image,
)
from tests.factories import build_image_options
from tests.fakes.engines.fake_opencv import (
    FAKE_ENGINE_VERSION,
    FakeCVError,
    FakeImage,
    FakeOpenCV,
)
from tests.image.samples import COLOR_LAYOUT, CORRUPT, EMBEDDED_LOGO

PAPER = 240.0
INK = 30.0


def uniform(width: int, height: int, level: float) -> FakeImage:
    """Return a single-channel image of one grey level."""
    return FakeImage([level] * (width * height), width, height, 1)


def bars(
    width: int,
    height: int,
    boxes: Sequence[tuple[int, int, int, int]],
    *,
    slope: float = 0.0,
) -> FakeImage:
    """Return a single-channel image with dark bars drawn on a light ground.

    Args:
        width: Image width in pixels.
        height: Image height in pixels.
        boxes: One ``(left, top, width, height)`` box per bar.
        slope: Pixels the bar descends per column, which is what gives it a skew.
    """
    values = [PAPER] * (width * height)
    for left, top, bar_width, bar_height in boxes:
        for x in range(left, left + bar_width):
            for y in range(top, top + bar_height):
                shifted = round(y + (x - left) * slope)
                if 0 <= x < width and 0 <= shifted < height:
                    values[shifted * width + x] = INK
    return FakeImage(values, width, height, 1)


def png_geometry(path: Path) -> tuple[int, int]:
    """Return the width and height a PNG's own header declares."""
    data = path.read_bytes()
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def test_the_engine_is_named_and_its_version_comes_from_the_engine() -> None:
    """The seam reads the version rather than defaulting one."""
    assert image_engine_version() == FAKE_ENGINE_VERSION


def test_an_absent_engine_is_reported_and_not_substituted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing library is an ``IO_ERROR``: the Pillow alternative is a swap, not a fallback.

    The seam is pointed at a module that does not exist, which is what "the library is not
    installed" looks like from inside it — and the double is removed, so the answer cannot come
    from a patch either.
    """
    monkeypatch.setattr("docflow.image.primitives.cv2", None)
    monkeypatch.setattr(
        "docflow.image.primitives.ENGINE_MODULE", "docflow_absent_engine"
    )

    with pytest.raises(ImagePrimitiveError) as failure:
        image_engine_version()

    assert failure.value.error.type == "IO_ERROR"
    assert failure.value.error.recoverable is False
    assert failure.value.error.metadata["module"] == "docflow_absent_engine"


def test_a_file_the_engine_cannot_decode_is_a_decode_error() -> None:
    """``imread`` answers ``None`` instead of raising; that is refused, never passed on."""
    with pytest.raises(ImagePrimitiveError) as failure:
        load_image(CORRUPT)

    assert failure.value.error.type == "DECODE_ERROR"
    assert failure.value.error.recoverable is False


def test_the_facts_come_from_the_file_and_the_decoded_array() -> None:
    """Width and height are the ones the file declares; the size is the file's own."""
    pixels = load_image(COLOR_LAYOUT)

    facts = get_image_metadata(COLOR_LAYOUT, pixels)

    assert (facts.width, facts.height) == png_geometry(COLOR_LAYOUT)
    assert facts.channels == 3
    assert facts.format == "png"
    assert facts.size == COLOR_LAYOUT.stat().st_size
    assert facts.resolution is None


def test_the_dimensions_follow_the_engine_convention_and_not_ours() -> None:
    """``shape`` is ``(height, width)``; the seam is the one place that is translated."""
    colour = FakeImage([0.0] * (40 * 30 * 3), 40, 30, 3)
    grey = FakeImage([0.0] * (40 * 30), 40, 30, 1)

    assert get_image_dimensions(colour) == (40, 30)
    assert get_image_channels(colour) == 3
    assert get_image_dimensions(grey) == (40, 30)
    assert get_image_channels(grey) == 1


def test_a_write_the_engine_refuses_is_a_write_error(
    opencv: Callable[..., FakeOpenCV], tmp_path: Path
) -> None:
    """``imwrite`` answers ``False`` instead of raising; that is refused too."""
    opencv(write_failures={"normalized.png"})

    with pytest.raises(ImagePrimitiveError) as failure:
        save_image(uniform(8, 8, PAPER), tmp_path / "image" / "normalized.png")

    assert failure.value.error.type == "WRITE_ERROR"
    assert not (tmp_path / "image" / "normalized.png").exists()
    assert not list(tmp_path.rglob("*.tmp"))


def test_the_engine_exception_maps_to_a_transformation_error(
    opencv: Callable[..., FakeOpenCV],
) -> None:
    """``cv2.error`` is the one signal that carries a message, and it is kept."""
    opencv(raises={"cvtColor": FakeCVError("bad depth")})

    with pytest.raises(ImagePrimitiveError) as failure:
        convert_to_grayscale(FakeImage([1.0] * (4 * 4 * 3), 4, 4, 3))

    assert failure.value.error.type == "TRANSFORMATION_ERROR"
    assert failure.value.error.metadata["engine_error"] == "bad depth"


def test_a_target_size_that_is_not_a_size_is_refused() -> None:
    """A zero-sized resize target is a caller error, not something to guess at."""
    with pytest.raises(ImagePrimitiveError) as failure:
        resize_image(uniform(8, 8, PAPER), 0, 8)

    assert failure.value.error.type == "INVALID_INPUT"
    assert failure.value.error.recoverable is False


@pytest.mark.parametrize(
    ("reader", "expected"),
    [
        (calculate_blur_score, 0.0),
        (calculate_sharpness_score, 0.0),
        (calculate_contrast_score, 0.0),
        (calculate_noise_score, 0.0),
        (calculate_brightness_score, 100.0),
    ],
)
def test_the_readings_are_arithmetic_over_the_decoded_array(
    reader: Callable[[FakeImage], float], expected: float
) -> None:
    """A flat image has no detail, no variation and no noise — arithmetic, not an opinion."""
    assert reader(uniform(12, 12, 100.0)) == pytest.approx(expected)


def test_a_detected_region_reports_the_ink_share_inside_its_own_box() -> None:
    """The per-region reading is ours: inked pixels over the box's own area.

    Two thin rules one line apart close into one region whose box also holds the paper between
    them, so a reading that assumed a filled box would report a constant one, not a fraction.
    """
    canvas = bars(80, 40, [(20, 10, 40, 1), (20, 12, 40, 1)])

    regions = detect_text_regions(canvas)

    assert len(regions) == 1
    assert regions[0].region_id == "region_001"
    assert regions[0].text_coverage == pytest.approx(2 / 3, abs=0.1)


def test_regions_come_back_in_reading_order() -> None:
    """Top to bottom, then left to right: the order is ours, not the engine's."""
    canvas = bars(120, 60, [(70, 30, 30, 8), (20, 5, 30, 8), (20, 30, 30, 8)])

    regions = detect_text_regions(canvas)

    assert [region.bbox[1] for region in regions] == sorted(
        region.bbox[1] for region in regions
    )
    assert [region.region_id for region in regions] == [
        f"region_{index:03d}" for index in range(1, len(regions) + 1)
    ]
    assert regions[1].bbox[0] < regions[2].bbox[0]


def test_the_coverage_is_the_share_of_the_image_the_regions_occupy() -> None:
    """The overall reading adds the detected boxes up, and clamps to the page."""
    regions = detect_text_regions(bars(100, 50, [(10, 10, 40, 10)]))

    coverage = calculate_text_coverage(regions, 100, 50)

    assert 0.0 < coverage < 1.0
    assert calculate_text_coverage([], 100, 50) == 0.0


def test_an_image_with_no_ink_reports_no_orientation_and_no_skew() -> None:
    """Absence is reported as absence: ``0`` would read as a measurement."""
    blank = uniform(60, 40, PAPER)

    assert detect_orientation(blank, 60, 40) is None
    assert detect_skew_angle(blank) is None


def test_content_that_contradicts_the_page_frame_needs_turning() -> None:
    """The rotation is ours: content whose box contradicts the page's aspect was scanned sideways.

    A portrait page whose ink is wide has been turned; a portrait page whose ink runs down the
    page has not.
    """
    sideways = bars(40, 60, [(0, 20, 40, 8)])
    upright = bars(40, 60, [(5, 5, 30, 40)])

    assert detect_orientation(sideways, 40, 60) == 90
    assert detect_orientation(upright, 40, 60) == 0


def test_a_measured_skew_is_folded_into_a_signed_angle() -> None:
    """The engine's ``0..90`` box angle becomes ``-45..45``; the convention is stated here."""
    skewed = bars(160, 60, [(20, 10, 120, 4)], slope=0.2)

    skew = detect_skew_angle(skewed)

    assert skew is not None
    assert 0.0 < skew <= 45.0


def test_deskewing_turns_the_ink_without_resizing_the_frame() -> None:
    """A correction is a real transformation, and the page's geometry is preserved."""
    skewed = bars(160, 60, [(20, 10, 120, 4)], slope=0.2)
    skew = detect_skew_angle(skewed)

    corrected = deskew_image(skewed, skew or 0.0)

    assert corrected.shape == skewed.shape
    assert corrected.values != skewed.values


def test_rotating_keeps_the_source_size_and_fills_with_paper() -> None:
    """The engine's black border default is not ours: a page is white."""
    corrected = rotate_image(uniform(20, 10, INK), 90.0)

    assert corrected.shape == (10, 20)
    assert max(corrected.values) == pytest.approx(255.0)


def test_the_two_channel_layouts_convert_both_ways() -> None:
    """Grey to colour and colour to grey, with no conversion reported when it already fits."""
    colour = FakeImage([10.0, 20.0, 30.0] * (4 * 4), 4, 4, 3)
    grey = convert_to_grayscale(colour)

    assert grey.shape == (4, 4)
    assert get_image_channels(convert_image_format(grey, "BGR")) == 3
    assert convert_image_format(grey, "GRAY") is grey
    assert convert_image_format(colour, "BGR") is colour


def test_compression_names_the_quality_factor_it_asked_for(
    opencv: Callable[..., FakeOpenCV], tmp_path: Path
) -> None:
    """The quality is a caller's decision, handed to the encoder rather than defaulted."""
    fake = opencv()
    destination = tmp_path / "image" / "variant.jpg"

    published = compress_image(uniform(8, 8, PAPER), destination, quality=71)

    assert published.is_file()
    assert fake.writes == [("variant.jpg", [FakeOpenCV.IMWRITE_JPEG_QUALITY, 71])]


def test_every_transformation_still_produces_an_image() -> None:
    """The enhance primitives are ours to call; each returns a usable image."""
    grey = bars(60, 40, [(10, 10, 40, 6)])

    for transformed in (
        normalize_contrast(grey),
        denoise_image(grey),
        sharpen_image(grey),
        convert_to_grayscale(grey),
    ):
        assert transformed.shape == grey.shape


def test_the_analysis_measures_the_image_without_mutating_it() -> None:
    """``analyze_image`` is side-effect free: it reads the array and changes nothing."""
    pixels = load_image(COLOR_LAYOUT)
    before = list(pixels.values)
    facts = get_image_metadata(COLOR_LAYOUT, pixels)

    metrics = analyze_image(pixels, facts)

    assert metrics.dimensions.width == facts.width
    assert metrics.format == "png"
    assert metrics.size == facts.size
    assert metrics.resolution is None
    assert metrics.text_regions
    assert pixels.values == before


def test_the_ocr_pipeline_binarizes_and_the_vlm_pipeline_keeps_the_colour(
    tmp_path: Path,
) -> None:
    """The two variants are different representations, not one representation twice."""
    pixels = load_image(COLOR_LAYOUT)
    facts = get_image_metadata(COLOR_LAYOUT, pixels)
    metrics = analyze_image(pixels, facts)
    options = build_image_options()

    ocr = prepare_image_for_ocr(pixels, metrics, options, tmp_path / "ocr_ready.png")
    vlm = prepare_image_for_vlm(pixels, metrics, options, tmp_path / "vlm_ready.png")

    assert ocr.artifact.path != vlm.artifact.path
    assert ocr.artifact.path.read_bytes() != vlm.artifact.path.read_bytes()
    assert ocr.transformations.count("binarize") == 1
    assert "binarize" not in vlm.transformations
    assert "convert_to_grayscale" in ocr.transformations


def test_a_pipeline_applies_only_what_the_measurements_justify(tmp_path: Path) -> None:
    """A contrast and noise reading inside the bands buys no enhancement."""
    pixels = load_image(COLOR_LAYOUT)
    facts = get_image_metadata(COLOR_LAYOUT, pixels)
    healthy = analyze_image(pixels, facts)
    metrics = ImageMetrics(
        dimensions=healthy.dimensions,
        resolution=healthy.resolution,
        format=healthy.format,
        size=healthy.size,
        quality=ImageQualityMetrics(
            blur=healthy.quality.blur,
            sharpness=healthy.quality.sharpness,
            contrast=CONTRAST_MIN * 4,
            brightness=healthy.quality.brightness,
            noise=NOISE_MAX / 4,
        ),
        orientation=0,
        skew=0.0,
        text_regions=healthy.text_regions,
        text_coverage=healthy.text_coverage,
    )
    options = ImageOptions(
        normalize=True,
        prepare_for_ocr=True,
        prepare_for_vlm=True,
        correct_orientation=False,
        deskew=False,
    )

    ocr = prepare_image_for_ocr(pixels, metrics, options, tmp_path / "ocr_ready.png")
    vlm = prepare_image_for_vlm(pixels, metrics, options, tmp_path / "vlm_ready.png")

    assert ocr.transformations == ["convert_to_grayscale", "binarize"]
    assert not vlm.transformations


def test_a_published_variant_carries_its_own_measurements(tmp_path: Path) -> None:
    """What was published is measured, so the artifact's own readings are on record."""
    pixels = load_image(COLOR_LAYOUT)
    facts = get_image_metadata(COLOR_LAYOUT, pixels)
    metrics = analyze_image(pixels, facts)

    ocr = prepare_image_for_ocr(
        pixels, metrics, build_image_options(), tmp_path / "ocr_ready.png"
    )

    assert isinstance(ocr.artifact, ArtifactRef)
    assert ocr.artifact.kind == "ocr_ready"
    assert ocr.artifact.size == ocr.artifact.path.stat().st_size
    assert ocr.metrics.format == "png"


def test_the_published_artifacts_are_real_decodable_files(
    opencv: Callable[..., FakeOpenCV], tmp_path: Path
) -> None:
    """Whatever the engine wrote is what a reader gets: no mangle on the way to the name."""
    fake = opencv()
    destination = tmp_path / "image" / "normalized.png"

    published = save_image(load_image(EMBEDDED_LOGO), destination)

    assert published.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert "imwrite" in fake.calls
    assert not list(tmp_path.rglob("*.tmp"))


def test_the_classification_of_a_measured_image_is_one_of_the_four() -> None:
    """The end of the measurement chain, on a real fixture."""
    pixels = load_image(COLOR_LAYOUT)

    classification = classify_image(
        analyze_image(pixels, get_image_metadata(COLOR_LAYOUT, pixels))
    )

    assert classification in {
        "TEXT_IMAGE",
        "VISUAL_IMAGE",
        "MIXED_IMAGE",
        "LOW_QUALITY",
    }
