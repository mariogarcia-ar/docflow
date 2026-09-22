"""Tests for ``analyze_image`` (``IMG-06``).

The WBS names two acceptance criteria: every ``ImageMetrics`` field carries a measured value, and
two runs on the same image with the same library versions produce identical metrics. Both are here,
and so is the DoD's "absence of filesystem writes".

The field-by-field test is worth more than it looks. "Every field carries a measured value" is the
easiest criterion in the project to satisfy dishonestly - a dataclass full of zeroes satisfies
"every field is populated" - so the assertions below name the value each field must have or the
range it must fall in, and two of them are checked against numbers computed here rather than by the
code under test.
"""

# pylint: disable=duplicate-code
# The fixture constants repeat the other image suites' on purpose. A shared helper module would let
# a change made for one suite silently redirect another's assertions; the duplication is a handful
# of lines per suite and the independence is worth the noise. `EXPECTED_DIMENSIONS` below is this
# module's own, taken from the generator rather than from a run of the code under test.
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import asdict, fields
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from docflow.image.contracts import ImageDimensions, ImageMetrics, TextRegion
from docflow.image.primitives.analyze import analyze_image
from docflow.image.primitives.engine import EngineChoice, ImageEngineCapabilityError
from docflow.image.primitives.failures import ImagePrimitiveError
from docflow.image.primitives.load import load_image
from docflow.image.primitives.transform import rotate_image, to_grayscale

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "image"
COLOR_LAYOUT = FIXTURES / "color_layout.png"
SKEWED_TEXT = FIXTURES / "skewed_text.png"
EMBEDDED_LOGO = FIXTURES / "embedded_logo.png"

ENGINE = EngineChoice.OPENCV
ALL_FIXTURES = [COLOR_LAYOUT, SKEWED_TEXT, EMBEDDED_LOGO]

EXPECTED_DIMENSIONS = {
    "color_layout.png": (240, 160),
    "skewed_text.png": (400, 300),
    "embedded_logo.png": (96, 64),
}
"""The fixtures' real sizes, taken from the generator rather than from a run of the code."""


def digest(path: Path) -> str:
    """Return a hash of a file's bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metrics_for(path: Path) -> ImageMetrics:
    """Analyze a fixture through the real pipeline."""
    return analyze_image(load_image(path, ENGINE), path, ENGINE)


@pytest.mark.parametrize("fixture", ALL_FIXTURES, ids=lambda path: path.name)
def test_every_metrics_field_carries_a_measured_value(fixture: Path) -> None:
    """The first WBS acceptance criterion, field by field rather than field by field's existence.

    Each assertion states the value or range the field must hold, so a snapshot of zeroes fails
    here. ``resolution`` is the one field allowed to be ``None``, because it means "the file
    declares none" - which the fixtures genuinely do.
    """
    metrics = metrics_for(fixture)
    width, height = EXPECTED_DIMENSIONS[fixture.name]

    assert metrics.dimensions.width == width
    assert metrics.dimensions.height == height
    assert metrics.resolution is None, "the fixtures declare no resolution"
    assert metrics.format == "PNG"
    assert metrics.size == fixture.stat().st_size

    assert metrics.quality.blur > 0.0
    assert metrics.quality.sharpness > 0.0
    assert metrics.quality.contrast > 0.0
    assert metrics.quality.brightness > 0.0
    # Strictly positive, not "
    # at least zero". Every fixture's noise estimate is small but real, so a
    # placeholder of 0.0 would slip past a `>= 0.0` assertion - which is exactly what a mutation
    # proved before this line was tightened.
    assert metrics.quality.noise > 0.0

    assert metrics.orientation in {0, 90}
    assert metrics.skew is not None
    assert metrics.text_regions, "a page with visible text reported no regions"
    assert 0.0 < metrics.text_coverage <= 1.0


@pytest.mark.parametrize("fixture", ALL_FIXTURES, ids=lambda path: path.name)
def test_every_field_is_a_real_measurement_not_a_default(fixture: Path) -> None:
    """No field may be the dataclass's zero.

    Distinct from the test above: that one checks each field is in range, this one checks that the
    fields differ *between images*. A snapshot that hardcoded one image's numbers would pass the
    first test on that image and fail here.
    """
    first = metrics_for(ALL_FIXTURES[0])
    other = metrics_for(fixture)

    assert isinstance(first.quality.blur, float)
    if fixture is not ALL_FIXTURES[0]:
        assert (other.quality.blur, other.quality.sharpness) != (
            first.quality.blur,
            first.quality.sharpness,
        ), f"{fixture.name} reports the same quality scores as {ALL_FIXTURES[0].name}"


def test_dimensions_come_from_the_pixels_and_match_the_file() -> None:
    """Cross-checked against the decoder rather than against another call to analyze_image."""
    image = load_image(COLOR_LAYOUT, ENGINE)
    metrics = analyze_image(image, COLOR_LAYOUT, ENGINE)

    assert metrics.dimensions == ImageDimensions(
        width=image.shape[1], height=image.shape[0]
    )


def test_resolution_is_reported_when_the_file_declares_one(tmp_path: Path) -> None:
    """The field is ``None`` on the fixtures because they declare nothing, not because it is unused.

    Without this test, an implementation that always returned ``None`` would satisfy every other
    assertion in this module.
    """
    declared = tmp_path / "dpi300.png"
    Image.fromarray(load_image(COLOR_LAYOUT, ENGINE)).save(declared, dpi=(300, 300))

    metrics = analyze_image(load_image(declared, ENGINE), declared, ENGINE)

    assert metrics.resolution == 300


def test_resolution_uses_the_declared_value_after_a_lossy_round_trip(
    tmp_path: Path,
) -> None:
    """JPEG states its resolution through a different header structure than PNG."""
    declared = tmp_path / "dpi200.jpg"
    Image.fromarray(load_image(COLOR_LAYOUT, ENGINE)).save(
        declared, dpi=(200, 200), quality=90
    )

    metrics = analyze_image(load_image(declared, ENGINE), declared, ENGINE)

    assert metrics.resolution == 200
    assert metrics.format == "JPEG"


def test_a_resolution_declared_per_centimetre_is_converted(tmp_path: Path) -> None:
    """JFIF's unit flag has two meanings and the second one needs arithmetic.

    No writer available here emits centimetres, so the segment is built by hand: a JFIF APP0 with
    unit 2 and a density of 100, which is 254 dots per inch. Without this test the conversion branch
    is dead code - a mutation that skipped it survived the whole suite.
    """
    path = tmp_path / "per_cm.jpg"
    Image.fromarray(load_image(COLOR_LAYOUT, ENGINE)).save(path, quality=90)
    raw = bytearray(path.read_bytes())
    segment = raw.find(b"JFIF\x00")
    assert segment > 0, "the writer did not emit a JFIF segment"

    raw[segment + 7] = 2  # units: dots per centimetre
    raw[segment + 8 : segment + 10] = (100).to_bytes(2, "big")
    raw[segment + 10 : segment + 12] = (100).to_bytes(2, "big")
    path.write_bytes(bytes(raw))

    assert analyze_image(load_image(path, ENGINE), path, ENGINE).resolution == 254


def test_a_png_resolution_in_another_unit_is_not_read_as_dots_per_inch(
    tmp_path: Path,
) -> None:
    """PNG's ``pHYs`` unit flag of 0 means "unknown", and its numbers are then not dots per inch.

    Reading them anyway would report a fabricated resolution. Built by hand because the writer
    refuses to emit the unit-less form, which leaves the guard untested otherwise - and a mutation
    that removed it survived the suite.
    """
    path = tmp_path / "unitless.png"
    Image.fromarray(load_image(COLOR_LAYOUT, ENGINE)).save(path)
    raw = bytearray(path.read_bytes())
    assert raw.find(b"pHYs") < 0, "the writer already emitted a resolution to overwrite"

    # Insert a pHYs chunk directly after IHDR, with unit 0 and a plausible per-metre figure.
    insertion = 8 + 25
    payload = (11811).to_bytes(4, "big") * 2 + b"\x00"
    body = b"pHYs" + payload
    raw[insertion:insertion] = (
        len(payload).to_bytes(4, "big") + body + b"\x00\x00\x00\x00"
    )
    path.write_bytes(bytes(raw))

    assert analyze_image(load_image(path, ENGINE), path, ENGINE).resolution is None


def test_a_non_square_resolution_is_reported_as_not_determined(tmp_path: Path) -> None:
    """The contract carries one integer, so an anisotropic file has no honest single answer.

    Returning either axis would silently assert the image is square-pixeled when the file says it is
    not. A mutation that returned the horizontal axis survived the suite until this test existed.
    """
    path = tmp_path / "anisotropic.png"
    Image.fromarray(load_image(COLOR_LAYOUT, ENGINE)).save(path, dpi=(300, 150))

    assert analyze_image(load_image(path, ENGINE), path, ENGINE).resolution is None


@pytest.mark.parametrize("fixture", ALL_FIXTURES, ids=lambda path: path.name)
def test_two_runs_produce_identical_metrics(fixture: Path) -> None:
    """The second WBS acceptance criterion."""
    image = load_image(fixture, ENGINE)

    assert analyze_image(image, fixture, ENGINE) == analyze_image(
        image, fixture, ENGINE
    )


def test_two_runs_are_identical_across_separate_decodes() -> None:
    """The DoD says "same image and library versions", which a re-read also satisfies."""
    assert metrics_for(SKEWED_TEXT) == metrics_for(SKEWED_TEXT)


def test_a_fresh_process_reports_the_same_metrics() -> None:
    """Determinism across processes, which is what makes two runs of the tool comparable.

    Run in a subprocess because an in-process repeat shares whatever mutable state an earlier test
    left behind, and the property being claimed is about a clean run.
    """
    workspace = Path(__file__).resolve().parents[3]
    program = (
        "import sys, json;"
        f"sys.path.insert(0, {str(workspace / 'src')!r});"
        "from pathlib import Path;"
        "from dataclasses import asdict;"
        "from docflow.image.primitives.analyze import analyze_image;"
        "from docflow.image.primitives.engine import EngineChoice;"
        "from docflow.image.primitives.load import load_image;"
        f"p = Path({str(SKEWED_TEXT)!r});"
        "print(json.dumps(asdict(analyze_image(load_image(p, EngineChoice.OPENCV), p,"
        " EngineChoice.OPENCV)), default=str))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", program], capture_output=True, text=True, check=True
    )

    assert json.loads(completed.stdout) == json.loads(
        json.dumps(asdict(metrics_for(SKEWED_TEXT)), default=str)
    )


@pytest.mark.parametrize("fixture", ALL_FIXTURES, ids=lambda path: path.name)
def test_analysis_writes_no_file(fixture: Path) -> None:
    """The DoD asks for this explicitly, as a property of the entry point rather than of a path."""
    before = digest(fixture)
    metrics_for(fixture)
    assert digest(fixture) == before


def test_the_module_has_no_route_to_the_filesystem_beyond_reading_facts() -> None:
    """Structural, so the guarantee does not rest on a test having exercised the right branch."""
    module = (
        Path(__file__).resolve().parents[3] / "src/docflow/image/primitives/analyze.py"
    )
    source = module.read_text(encoding="utf-8")

    for forbidden in (
        "imwrite",
        "write_bytes",
        "write_text",
        "save(",
        "os.remove",
        "mkdir",
    ):
        assert forbidden not in source, f"analyze.py gained a write route: {forbidden}"


def test_the_input_array_is_never_mutated() -> None:
    """``IMG-06`` is described as side-effect-free with respect to the image itself."""
    image = load_image(SKEWED_TEXT, ENGINE)
    before = image.copy()

    analyze_image(image, SKEWED_TEXT, ENGINE)

    assert np.array_equal(image, before)


def test_the_snapshot_records_the_skew_it_measured() -> None:
    """The aggregation must pass the reading through, not lose it to a default."""
    metrics = metrics_for(SKEWED_TEXT)

    assert metrics.skew == pytest.approx(4.0, abs=0.1)
    assert metrics_for(COLOR_LAYOUT).skew == pytest.approx(0.0, abs=0.1)


def test_text_regions_are_the_contract_type_and_agree_with_the_coverage() -> None:
    """The snapshot's regions and its coverage come from one detection pass, so they agree."""
    metrics = metrics_for(COLOR_LAYOUT)

    assert all(isinstance(region, TextRegion) for region in metrics.text_regions)
    assert isinstance(metrics.text_regions, list), "the contract declares a list"
    assert metrics.text_coverage > 0.0


def test_a_blank_page_reports_zeroes_honestly_rather_than_failing(
    tmp_path: Path,
) -> None:
    """An empty page is a measurement of nothing, not an error."""
    blank = tmp_path / "blank.png"
    Image.fromarray(np.full((100, 150, 3), 255, dtype=np.uint8)).save(blank)

    metrics = analyze_image(load_image(blank, ENGINE), blank, ENGINE)

    # Written as an explicit comparison rather than `not metrics.text_regions`, because the point is
    # that the list is empty rather than that it is falsey.
    assert metrics.text_regions == []  # pylint: disable=use-implicit-booleaness-not-comparison
    assert metrics.text_coverage == 0.0
    assert metrics.quality.contrast == pytest.approx(0.0, abs=1e-9)
    assert metrics.quality.brightness == pytest.approx(255.0)


def test_a_grayscale_input_is_accepted() -> None:
    """The contract does not require colour, and the metrics are defined on luminance."""
    image = load_image(COLOR_LAYOUT, ENGINE)

    metrics = analyze_image(to_grayscale(image, ENGINE), COLOR_LAYOUT, ENGINE)

    assert metrics.dimensions.width == EXPECTED_DIMENSIONS["color_layout.png"][0]
    assert metrics.quality.blur > 0.0


def test_metrics_differ_between_a_sharp_and_a_blurred_page() -> None:
    """The snapshot has to reflect the image it was given, not the file name."""
    image = load_image(COLOR_LAYOUT, ENGINE)
    softened = rotate_image(image, 8.0, ENGINE)

    sharp_metrics = analyze_image(image, COLOR_LAYOUT, ENGINE)
    soft_metrics = analyze_image(softened, COLOR_LAYOUT, ENGINE)

    assert soft_metrics.quality.blur < sharp_metrics.quality.blur


def test_a_missing_file_is_reported_and_not_silently_measured(tmp_path: Path) -> None:
    """The facts read is a real read; a path that does not exist must fail rather than default."""
    image = load_image(COLOR_LAYOUT, ENGINE)

    with pytest.raises(ImagePrimitiveError):
        analyze_image(image, tmp_path / "gone.png", ENGINE)


def test_the_codec_engine_reports_a_capability_gap_rather_than_substituting() -> None:
    """The engine boundary again, at the aggregation level rather than at one primitive."""
    pillow_image = load_image(COLOR_LAYOUT, EngineChoice.PILLOW)

    with pytest.raises(ImageEngineCapabilityError):
        analyze_image(pillow_image, COLOR_LAYOUT, EngineChoice.PILLOW)


def test_every_contract_field_is_populated() -> None:
    """Guards against the contract growing a field that the aggregation forgets to fill.

    Constructing ``ImageMetrics`` would already fail on a missing argument, so this catches the other
    shape of the problem: a field added with a default, which would slip through construction and
    reach ``metadata.json`` as an unfilled value.
    """
    metrics = metrics_for(COLOR_LAYOUT)
    declared = {field.name for field in fields(ImageMetrics)}
    assert declared == {
        "dimensions",
        "resolution",
        "format",
        "size",
        "quality",
        "orientation",
        "skew",
        "text_regions",
        "text_coverage",
    }
    for name in declared:
        assert hasattr(metrics, name)
