"""Tests for K3 ``kernel.image`` (``E04-03`` / ``S1-T13``).

Fixtures are **generated**, not committed: `kernel-cli.md` §12 asks for synthetic
fixtures, and `plan-01-kernels.md` §13 marks a fixture generator as the
``# TODO: [MVP]`` that replaces committed ones. Each is named for the failure it
provokes.

The load-bearing tests are the one per silent-failure row:

- ``test_info_reports_the_orientation_it_applied`` and its companion on ``load`` —
  row 6. The pair matters: reporting the tag without applying it passes a naive
  check while leaving the photo sideways in the bytes.
- ``test_legibility_reports_a_measurement_and_a_reason`` — row 7. The assertion
  that the measurements are present **on the failure** is the one that distinguishes
  a reason from a boolean.
- ``test_crop_maps_local_coordinates_back_to_the_source`` — row 8, and the
  coordinate-honesty golden artifact of ``plan-01-kernels.md`` §13 Track 2.

Two further tests exist to keep the above from being satisfiable vacuously: the
threshold is shown to be the caller's by changing it and watching the verdict
change on an **unchanged** image, and every negative case has a positive control.

Pylint relaxations are declared for the reasons the other suites state: a contract
test restates the names it checks (``duplicate-code``), one test per behaviour costs
file length (``too-many-lines``), and a pytest fixture is injected by name, so a
test parameter necessarily shadows the fixture function it asks for.
"""

# pylint: disable=duplicate-code
# pylint: disable=redefined-outer-name
# pylint: disable=too-many-lines

from __future__ import annotations

import io
import pathlib

import pytest
from PIL import Image, ImageFilter

from docflow.kernels import image
from docflow.kernels.types import Box

# --- Fixture construction ----------------------------------------------------

#: The EXIF tag carrying the orientation, and the value meaning *rotate 90° CW*.
_ORIENTATION_TAG = 274
_ROTATE_90_CW = 6

#: The stored shape of the rotated fixture: landscape. After the orientation is
#: applied it must come back portrait, which is what makes the rotation observable
#: from the returned bytes alone.
_STORED_SIZE = (80, 40)

#: The sharpness a blurred fixture measures below, and a sharp one measures above.
#: Far apart on purpose: the test asserts separability, not a tuned value.
_BLUR_THRESHOLD = 100.0


def _rotated_jpeg(path: pathlib.Path) -> pathlib.Path:
    """Write a landscape JPEG declaring EXIF orientation 6.

    Args:
        path: Where to write the file.

    Returns:
        The written path.

    """
    picture = Image.new("RGB", _STORED_SIZE, "white")
    exif = picture.getexif()
    exif[_ORIENTATION_TAG] = _ROTATE_90_CW
    picture.save(path, exif=exif)

    return path


def _sharp_png(path: pathlib.Path) -> pathlib.Path:
    """Write a high-contrast image with fine detail.

    Args:
        path: Where to write the file.

    Returns:
        The written path.

    """
    picture = Image.new("L", (200, 200), 0)
    for offset in range(0, 200, 4):
        picture.putpixel((offset, offset), 255)
    picture.convert("RGB").save(path)

    return path


def _blurred_png(path: pathlib.Path) -> pathlib.Path:
    """Write the same image with its detail destroyed.

    Args:
        path: Where to write the file.

    Returns:
        The written path.

    """
    sharp = Image.new("L", (200, 200), 0)
    for offset in range(0, 200, 4):
        sharp.putpixel((offset, offset), 255)
    sharp.filter(ImageFilter.GaussianBlur(12)).convert("RGB").save(path)

    return path


def _blank_png(path: pathlib.Path, size: tuple[int, int] = (600, 400)) -> pathlib.Path:
    """Write a featureless white image.

    Args:
        path: Where to write the file.
        size: The image's dimensions.

    Returns:
        The written path.

    """
    Image.new("RGB", size, "white").save(path)

    return path


# --- Fixtures ----------------------------------------------------------------


@pytest.fixture
def rotated_jpeg(tmp_path: pathlib.Path) -> pathlib.Path:
    """A photo carrying EXIF orientation 6."""
    return _rotated_jpeg(tmp_path / "rotated.jpg")


@pytest.fixture
def sharp_png(tmp_path: pathlib.Path) -> pathlib.Path:
    """A sharp image."""
    return _sharp_png(tmp_path / "sharp.png")


@pytest.fixture
def blurred_png(tmp_path: pathlib.Path) -> pathlib.Path:
    """A blurred image."""
    return _blurred_png(tmp_path / "blurry.jpg")


@pytest.fixture
def page_png(tmp_path: pathlib.Path) -> pathlib.Path:
    """A large blank page, for cropping."""
    return _blank_png(tmp_path / "page.png")


# --- The surface -------------------------------------------------------------


def test_module_exports_the_four_operations_plus_the_inverse_map() -> None:
    """``__all__`` is the declared surface, sorted for the linter.

    ``InverseMap`` is exported because it is the value a caller receives and has to
    call ``to_source`` on; the private helpers are not, because reaching for one
    would be reaching past the kernel's contract.
    """
    exported: list[str] = list(image.__all__)

    assert exported == sorted(exported), "__all__ must stay alphabetically sorted"
    assert set(exported) == {
        "InverseMap",
        "crop",
        "info",
        "legibility",
        "load",
        "rescale",
    }
    for name in exported:
        assert hasattr(image, name), f"{name} is exported but not defined"


# --- Row 6: a photo read sideways -------------------------------------------


def test_info_reports_the_orientation_it_found(rotated_jpeg: pathlib.Path) -> None:
    """``info`` reports the EXIF tag the file declares."""

    result = image.info(rotated_jpeg)

    assert result.value is not None
    assert result.value.observed["exif_orientation"] == _ROTATE_90_CW
    assert result.value.observed["exif_orientation_applied"] is True


def test_info_reports_no_orientation_on_an_upright_image(
    sharp_png: pathlib.Path,
) -> None:
    """An image declaring no orientation reports the absence, not a zero.

    The pair with the test above is what proves the field carries information: an
    implementation that always reported ``6`` would satisfy that assertion while
    telling the caller nothing about the file.
    """
    result = image.info(sharp_png)

    assert result.value is not None
    assert result.value.observed["exif_orientation"] is None
    assert result.value.observed["exif_orientation_applied"] is False


def test_load_applies_the_orientation_before_the_bytes_leave(
    rotated_jpeg: pathlib.Path,
) -> None:
    """The returned bytes are the **rotated** image, not the stored one.

    This is the half of row 6 that a naive implementation fails: reading the tag and
    reporting it is easy, and leaves the photo sideways in the value every later
    stage consumes. The fixture is stored landscape and declares rotate-90, so the
    decoded result must be portrait.
    """
    stored = Image.open(rotated_jpeg)
    assert stored.size == _STORED_SIZE, "the fixture must be stored landscape"

    result = image.load(rotated_jpeg)

    assert result.value is not None
    decoded = Image.open(io.BytesIO(result.value.data))

    assert decoded.size == (_STORED_SIZE[1], _STORED_SIZE[0]), (
        "a landscape file declaring rotate-90 must decode portrait; the stored "
        "shape coming back means the orientation was read and not applied"
    )


def test_load_reports_the_orientation_it_applied(
    rotated_jpeg: pathlib.Path,
) -> None:
    """``load`` says a rotation happened, so the caller can undo it if it must."""
    result = image.load(rotated_jpeg)

    assert result.value is not None
    assert result.evidence.observed["exif_orientation"] == _ROTATE_90_CW
    assert result.evidence.observed["exif_orientation_applied"] is True


def test_load_does_not_rotate_an_image_that_declares_nothing(
    sharp_png: pathlib.Path,
) -> None:
    """No declared orientation means no rotation, and the bytes are unchanged.

    Without this, an implementation that rotated unconditionally would satisfy the
    row's assertions while corrupting every upright image.
    """
    result = image.load(sharp_png)

    assert result.value is not None
    decoded = Image.open(io.BytesIO(result.value.data))

    assert decoded.size == (200, 200)
    assert result.evidence.observed["exif_orientation_applied"] is False


# --- Row 7: a blurred image passed to OCR -----------------------------------


def test_legibility_reports_a_measurement_and_a_reason(
    blurred_png: pathlib.Path,
) -> None:
    """A blurred image fails with a typed reason **and keeps its measurements**.

    The measurements being present on the *failure* is the whole point: a boolean
    would tell the caller that something is wrong without telling it what was
    measured, and the threshold that decision was taken against is policy the
    caller owns.
    """
    result = image.legibility(blurred_png, threshold=_BLUR_THRESHOLD)

    assert result.value is None
    assert result.reason is not None
    assert result.reason.code == "illegible"
    assert result.evidence.measurements["laplacian_variance"] < _BLUR_THRESHOLD
    assert result.evidence.measurements["contrast"] >= 0.0
    assert "skew_estimate" in result.evidence.measurements
    assert result.evidence.measurements["threshold_applied"] == _BLUR_THRESHOLD


def test_legibility_returns_a_value_for_a_sharp_image(
    sharp_png: pathlib.Path,
) -> None:
    """A sharp image against the same threshold produces a value.

    The pair with the test above proves the refusal is about the measurement rather
    than a blanket refusal of images.
    """
    result = image.legibility(sharp_png, threshold=_BLUR_THRESHOLD)

    assert result.reason is None
    assert result.value is not None
    assert result.value.measurements["laplacian_variance"] > _BLUR_THRESHOLD


def test_the_threshold_is_the_callers_by_changing_it_on_an_unchanged_image(
    sharp_png: pathlib.Path,
) -> None:
    """The same image flips verdict when only the threshold moves.

    This is `prd.md` FR-15 as a test. A kernel holding its own constant would
    return the same answer twice and this assertion would fail — which is why the
    threshold is a required parameter with no default.
    """
    permissive = image.legibility(sharp_png, threshold=1.0)
    strict = image.legibility(sharp_png, threshold=10**9)

    assert permissive.value is not None
    assert strict.value is None
    assert strict.reason is not None
    assert strict.reason.code == "illegible"


def test_legibility_never_returns_a_bare_boolean(
    blurred_png: pathlib.Path,
) -> None:
    """The value is never ``True``/``False`` — it is a measurement record.

    Asserted structurally, because the failure this guards against is someone
    "simplifying" the result to a boolean, which the row forbids explicitly.
    """
    failed = image.legibility(blurred_png, threshold=_BLUR_THRESHOLD)
    passed = image.legibility(blurred_png, threshold=0.0)

    assert not isinstance(failed.value, bool)
    assert not isinstance(passed.value, bool)
    assert passed.value is not None
    assert "laplacian_variance" in passed.value.measurements


def test_legibility_emits_no_aggregate_grade(blurred_png: pathlib.Path) -> None:
    """No ``score``, ``quality`` or ``confidence`` appears anywhere in the result.

    A number that aggregates the measurements is a decision wearing a number's
    clothes, and `kernel-cli.md` §3 forbids it at a kernel boundary.
    """
    result = image.legibility(blurred_png, threshold=_BLUR_THRESHOLD)
    forbidden = {"score", "quality", "confidence", "grade"}

    assert not forbidden & set(result.evidence.measurements)
    assert not forbidden & set(result.evidence.observed)


# --- Row 8: a crop's local coordinates reported as a page region ------------


def test_crop_maps_local_coordinates_back_to_the_source(
    page_png: pathlib.Path,
) -> None:
    """The inverse map takes the crop's local frame back to source coordinates.

    This is the coordinate-honesty assertion of ``plan-01-kernels.md`` §13 Track 2,
    and it is `NFR-07`. The failure it prevents is silent: a crop whose local
    coordinates are reported as a page region points the trace at the wrong pixels,
    and both boxes are valid JSON.
    """
    region = Box(100.0, 200.0, 300.0, 80.0)

    result = image.crop(page_png, region)

    assert result.value is not None
    inverse = result.value.observed["inverse_map"]
    assert isinstance(inverse, image.InverseMap)

    assert inverse.to_source(0.0, 0.0) == (100.0, 200.0), (
        "the crop's own origin must map to the region's origin in the source"
    )
    assert inverse.to_source(300.0, 80.0) == (400.0, 280.0), (
        "the crop's far corner must map to the region's far corner in the source"
    )


def test_crop_never_reports_local_coordinates_as_the_source_region(
    page_png: pathlib.Path,
) -> None:
    """The reported source box is in page coordinates, not in the crop's frame.

    The distinction is what makes the failure silent: a crop taken at ``(100, 200)``
    whose box is reported as ``(0, 0, 300, 80)`` is a valid, wrong answer.
    """
    result = image.crop(page_png, Box(100.0, 200.0, 300.0, 80.0))

    assert result.value is not None
    source_box = result.value.observed["source_box"]

    assert source_box == [100.0, 200.0, 400.0, 280.0]
    assert source_box[:2] != [0.0, 0.0], (
        "reporting the local origin as the source region is exactly the silent "
        "failure this assertion exists to catch"
    )
    assert result.value.observed["coordinate_space"] == "source_page"


def test_crop_returns_bytes_with_its_map(page_png: pathlib.Path) -> None:
    """The bytes travel with the map, in one value.

    Separating them would make the map a step the caller has to remember, which is
    the design that produced the failure in the first place.
    """
    result = image.crop(page_png, Box(10.0, 20.0, 50.0, 60.0))

    assert result.value is not None
    payload = result.value.observed["image"]
    assert payload.media_type == "image/png"

    decoded = Image.open(io.BytesIO(payload.data))
    assert decoded.size == (50, 60)


def test_crop_refuses_a_region_outside_the_image(page_png: pathlib.Path) -> None:
    """A region larger than the page is a usage error, not a silent clamp.

    Clamping would return a crop of a different size than the one asked for, with
    an inverse map that still looked right.
    """
    with pytest.raises(ValueError, match="falls outside the image"):
        image.crop(page_png, Box(500.0, 300.0, 300.0, 300.0))


def test_crop_refuses_a_degenerate_region(page_png: pathlib.Path) -> None:
    """A zero-width or zero-height region is a usage error."""
    with pytest.raises(ValueError, match="positive extent"):
        image.crop(page_png, Box(10.0, 10.0, 0.0, 50.0))


# --- rescale -----------------------------------------------------------------


def test_rescale_reports_the_target_it_honoured(page_png: pathlib.Path) -> None:
    """A reachable target is honoured and named in the evidence."""
    result = image.rescale(page_png, target_dpi=100, source_dpi=200)

    assert result.value is not None
    assert result.evidence.measurements["dpi_honoured"] == 100.0
    assert result.evidence.observed["upscaled"] is False

    decoded = Image.open(io.BytesIO(result.value.data))
    assert decoded.size == (300, 200), "the pixels must shrink by the ratio asked"


def test_rescale_refuses_a_target_the_source_cannot_reach(
    page_png: pathlib.Path,
) -> None:
    """Asking for more resolution than the source holds is refused.

    The refusal exists because the alternative is a larger file that is no more
    legible while reporting the request as met — the same failure `render` refuses
    in K2, and deliberately the same reason code so a caller matching on it does
    not have to know which kernel declined.
    """
    result = image.rescale(page_png, target_dpi=400, source_dpi=200)

    assert result.value is None
    assert result.reason is not None
    assert result.reason.code == "insufficient_effective_resolution"
    assert result.evidence.measurements["source_dpi"] == 200.0
    assert result.evidence.observed["files_written"] == 0


def test_rescale_accepts_the_source_resolution_as_satisfiable(
    page_png: pathlib.Path,
) -> None:
    """A target equal to the source is not refused — nothing would change.

    The boundary case matters: refusing it would make the operation unusable for a
    caller that simply passes through whatever it measured.
    """
    result = image.rescale(page_png, target_dpi=200, source_dpi=200)

    assert result.value is not None
    assert result.evidence.measurements["dpi_honoured"] == 200.0


def test_rescale_refuses_a_non_positive_resolution(
    page_png: pathlib.Path,
) -> None:
    """Zero or negative resolutions are usage errors."""
    with pytest.raises(ValueError, match="target_dpi must be positive"):
        image.rescale(page_png, target_dpi=0, source_dpi=200)

    with pytest.raises(ValueError, match="source_dpi must be positive"):
        image.rescale(page_png, target_dpi=100, source_dpi=0)


# --- Typed failure paths -----------------------------------------------------


def test_a_missing_file_is_a_typed_reason(tmp_path: pathlib.Path) -> None:
    """An absent file reports ``unsupported_format``, never an empty bitmap."""
    for operation in (
        lambda: image.load(tmp_path / "no.png"),
        lambda: image.info(tmp_path / "no.png"),
        lambda: image.legibility(tmp_path / "no.png", threshold=1.0),
        lambda: image.rescale(tmp_path / "no.png", target_dpi=10, source_dpi=10),
        lambda: image.crop(tmp_path / "no.png", Box(0.0, 0.0, 10.0, 10.0)),
    ):
        result = operation()
        assert result.value is None
        assert result.reason is not None
        assert result.reason.code == "unsupported_format"


def test_bytes_that_are_not_an_image_are_a_typed_reason(
    tmp_path: pathlib.Path,
) -> None:
    """A file that is not an image reports why instead of raising."""
    impostor = tmp_path / "not-an-image.png"
    impostor.write_bytes(b"this is not a PNG, however it is named")

    result = image.info(impostor)

    assert result.value is None
    assert result.reason is not None
    assert result.reason.code == "unsupported_format"


def test_a_missing_engine_is_a_typed_reason_and_not_a_substitute(
    sharp_png: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without the engine the call reports why, and decodes nothing.

    ``wbs.md`` §9: a missing engine is a typed ``Reason``, never a substitute.
    """
    monkeypatch.setattr(
        image, "_engine", lambda: (None, image.Reason("engine_unavailable", "missing"))
    )

    result = image.load(sharp_png)

    assert result.value is None
    assert result.reason is not None
    assert result.reason.code == "engine_unavailable"


# --- The reason vocabulary ---------------------------------------------------


def test_every_reason_code_raised_here_is_in_the_closed_set() -> None:
    """The codes this module can raise are the ones `kernel-cli.md` §5 declares.

    A code outside that set would be unassertable by the silent-failure suite,
    because the suite targets codes and a novel one would have no row behind it.
    """
    closed_set = {
        "illegible",
        "unsupported_format",
        "engine_unavailable",
        "insufficient_effective_resolution",
    }
    declared = {
        value for name, value in vars(image).items() if name.startswith("_CODE_")
    }

    assert declared, "the module declares reason codes, so this is not vacuous"
    assert declared <= closed_set, (
        f"codes outside the closed set: {declared - closed_set}"
    )


def test_no_threshold_or_grade_constant_lives_in_the_module() -> None:
    """No constant named like a policy value, public or private.

    Checked as a forbidden vocabulary rather than an allow-list, because an
    allow-list would fail on every legitimate rename — and a guard that cries wolf
    gets loosened. What matters is that nothing here reads as a value the caller
    should be deciding.
    """
    forbidden = ("threshold", "min_score", "quality", "limit", "umbral")
    declared = [name for name in vars(image) if name.isupper()]

    assert declared, "the module declares constants, so this check is not vacuous"

    for name in sorted(declared):
        lowered = name.lower()
        for part in forbidden:
            assert part not in lowered, (
                f"{name!r} reads like a policy value ({part!r}); a threshold "
                "belongs to the caller, not to this module"
            )
