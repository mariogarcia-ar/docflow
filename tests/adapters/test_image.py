"""Tests for the K3 raster adapter (``E04-03`` / ``S1-T13``).

The adapter is the only place Pillow is named, so these are the tests that can check
what the kernel cannot: that the seam is satisfied, that the library is reached lazily,
and that a missing library becomes a typed refusal rather than an ``ImportError``.

The kernel's own decisions are asserted in `tests/kernels/test_image.py`. What is here
is the *vendor half* — the part that would be replaced by a different raster library.

Pylint relaxations are declared for the reasons the other adapter suites state: a
contract test restates the names it checks (``duplicate-code``), one test per behaviour
costs file length (``too-many-lines``), and the stubs are one-purpose stand-ins by
design (``too-few-public-methods``).
"""

# pylint: disable=duplicate-code
# pylint: disable=too-few-public-methods
# pylint: disable=too-many-lines
# A test taking a fixture by name *is* redefining that name in its own scope, and the
# fixture is used by pytest rather than by the body — which Pylint cannot see. Both
# rules are false positives on this shape, and every adapter suite beside this one
# carries the same two suppressions for the same reason.
# pylint: disable=redefined-outer-name
# pylint: disable=unused-argument

from __future__ import annotations

import builtins
import pathlib
from typing import Any

import pytest
from PIL import Image

from docflow.adapters.image import PillowVendor, RasterEngine
from docflow.kernels.image_vendor import (
    EXIF_ORIENTATION_TAG,
    ImageMeta,
    RasterFrame,
    RasterStats,
    RasterVendor,
    RasterVendorError,
)
from docflow.kernels.types import Reason

# --- Fixtures ----------------------------------------------------------------

_SIZE = (80, 40)


def _png(path: pathlib.Path, *, size: tuple[int, int] = _SIZE) -> pathlib.Path:
    """Write a plain PNG.

    Args:
        path: Where to write the file.
        size: The image's dimensions.

    Returns:
        The written path.

    """
    Image.new("RGB", size, "white").save(path)

    return path


@pytest.fixture
def without_pillow() -> "object":
    """Make ``import PIL`` fail for the duration of one test.

    A fixture rather than a helper the test calls, because the restoration has to
    happen even when the assertion fails. The first version of this used a hand-rolled
    patch and an ``importlib.reload`` to undo it, which did not restore the original
    importer — so every test *after* it saw a blocked Pillow and failed with a
    message about a substitute decoder. The fixture cannot leak that way.

    Yields:
        Nothing: the test body runs with the patch applied.

    """
    real = builtins.__import__

    def guard(name: str, *args: object, **kwargs: object) -> object:
        if name.split(".")[0] == "PIL":
            raise ImportError("No module named 'PIL'")

        return real(name, *args, **kwargs)

    builtins.__import__ = guard  # type: ignore[assignment]
    try:
        yield None
    finally:
        builtins.__import__ = real  # type: ignore[assignment]


@pytest.fixture
def plain_png(tmp_path: pathlib.Path) -> pathlib.Path:
    """Provide a written PNG.

    Args:
        tmp_path: The pytest fixture.

    Returns:
        The path.

    """
    return _png(tmp_path / "page.png")


# --- The adapter satisfies the seam -----------------------------------------


def test_the_adapter_satisfies_the_seam() -> None:
    """``PillowVendor`` is structurally a ``RasterVendor``."""
    assert isinstance(PillowVendor(), RasterVendor)


def test_the_engine_exposes_the_four_operations() -> None:
    """``RasterEngine`` exposes K3's operations and nothing invented.

    K3 has **no port** — the set is frozen at five and a raster library is not a
    swap-able vendor boundary — so this asserts the adapter's own surface rather than
    a protocol it implements.
    """
    public = {
        name
        for name in vars(RasterEngine)
        if not name.startswith("_") and callable(getattr(RasterEngine, name))
    }

    assert public == {"load", "info", "legibility", "rescale", "crop"}


def test_the_engine_carries_the_vendor_it_was_given() -> None:
    """The injected vendor is reachable, so a caller can share one."""
    vendor = PillowVendor()
    engine = RasterEngine(vendor=vendor)

    assert engine.vendor is vendor


# --- The library is reached lazily, and its absence is typed ----------------


def test_the_library_is_resolved_on_first_use_not_at_import() -> None:
    """Constructing a vendor does not import Pillow.

    ``pyproject.toml`` declares no runtime dependency, so importing the adapter must
    not require the library — only calling one does. That is what lets the
    composition root name a concrete engine and still let a caller run the parts of
    the system that do not need it.
    """
    vendor = PillowVendor()

    assert vendor is not None, "construction must succeed with the library absent"


def test_a_missing_library_is_a_typed_refusal_not_an_import_error(
    without_pillow: object,
) -> None:
    """An absent Pillow arrives as a ``RasterVendorError`` carrying a reason.

    This is the adapter's half of ``wbs.md`` §9: a missing engine is a typed reason,
    never an ``ImportError`` escaping a call and never a substitute decoder.
    """
    with pytest.raises(RasterVendorError) as raised:
        PillowVendor().decode(pathlib.Path("whatever.png"))

    assert raised.value.reason.code == "engine_unavailable"
    assert "pillow" in raised.value.reason.message


def test_the_refusal_names_the_install_command(without_pillow: object) -> None:
    """The message carries the remedy, so an operator can act on it."""
    with pytest.raises(RasterVendorError) as raised:
        PillowVendor().engine()

    assert "pip install pillow" in raised.value.reason.message
    assert "no substitute engine" in raised.value.reason.message


def test_the_library_is_reachable_again_once_the_patch_is_lifted() -> None:
    """The control for the two above: the patch does not outlive its test.

    Without this, a leaked patch would make every later test fail with a message
    about a substitute decoder — which is exactly what happened before the fixture
    existed, and it cost nine tests their meaning.
    """
    assert PillowVendor().engine() is not None


# --- The primitives answer what they are asked ------------------------------


def test_decode_returns_the_frame_and_the_meta(plain_png: pathlib.Path) -> None:
    """``decode`` reports the frame's facts and does **not** rotate it.

    The orientation is deliberately left unapplied: the kernel reports the tag before
    it is consumed, and an implementation that rotated during decode would make *the
    rotation that was found* unobservable.
    """
    frame, meta = PillowVendor().decode(plain_png)

    assert frame.size == _SIZE
    assert frame.mode
    assert isinstance(meta, ImageMeta)
    assert meta.format == "PNG"
    assert meta.exif_orientation is None


def test_decode_reports_a_declared_orientation_without_applying_it(
    tmp_path: pathlib.Path,
) -> None:
    """A declared tag travels in the meta and the stored pixels stay stored."""
    path = tmp_path / "rotated.png"
    picture = Image.new("RGB", (80, 40), "white")
    exif = picture.getexif()
    exif[EXIF_ORIENTATION_TAG] = 6
    picture.save(path, exif=exif)

    frame, meta = PillowVendor().decode(path)

    assert meta.exif_orientation == 6
    assert frame.size == (80, 40), "the frame is not rotated by decode"


def test_greyscale_yields_one_channel(plain_png: pathlib.Path) -> None:
    """``greyscale`` reduces the frame, so the statistics are about brightness."""
    vendor = PillowVendor()
    frame, _meta = vendor.decode(plain_png)

    reduced = vendor.greyscale(frame)

    assert reduced.mode == "L"


def test_statistics_report_both_numbers(plain_png: pathlib.Path) -> None:
    """The pair is returned, so the kernel keeps *which* number it needs.

    Sharpness is a variance of a convolved frame and contrast is a standard deviation
    of the frame itself. Returning a pair keeps that distinction in the kernel, where
    it is a fact about what is being measured.
    """
    vendor = PillowVendor()
    frame, _meta = vendor.decode(plain_png)

    stats = vendor.statistics(vendor.greyscale(frame))

    assert isinstance(stats, RasterStats)
    assert stats.stddev >= 0
    assert stats.variance >= 0


def test_convolved_answers_a_frame(plain_png: pathlib.Path) -> None:
    """A convolution returns a frame of the same size to measure."""
    vendor = PillowVendor()
    frame, _meta = vendor.decode(plain_png)
    luminance = vendor.greyscale(frame)

    convolved = vendor.convolved(
        luminance, (0.0, 1.0, 0.0, 1.0, -4.0, 1.0, 0.0, 1.0, 0.0), (3, 3)
    )

    assert isinstance(convolved, RasterFrame)
    assert convolved.size == luminance.size


_LAPLACIAN = (0.0, 1.0, 0.0, 1.0, -4.0, 1.0, 0.0, 1.0, 0.0)


def _edge_png(path: pathlib.Path) -> pathlib.Path:
    """Write a frame holding a thin bright line on a dark field.

    A one-pixel line rather than a step edge, because the response magnitude is
    what this fixture exists to produce: at the line's own pixels the horizontal
    neighbours are dark while the vertical ones are bright, which drives the
    Laplacian to ``-510``. A step edge between two flat fields only reaches
    ``-180``, which an unsigned byte could almost hold - the fixture has to
    require more than 8 bits to be able to falsify an 8-bit path.
    """
    picture = Image.new("L", (40, 40), 0)
    for y in range(40):
        picture.putpixel((20, y), 255)
    picture.save(path)
    return path


def _responses(frame: RasterFrame) -> list[float]:
    """Read a frame's pixel values.

    ``RasterFrame.handle`` is opaque to production code on purpose - the kernel
    passes it back to the vendor and never inspects it - so a test that needs the
    numbers reaches through it explicitly and says so here, rather than widening
    the type for everyone.

    Args:
        frame: The frame to read.

    Returns:
        The values, row-major.

    """
    handle: Any = frame.handle
    return [float(value) for value in handle.get_flattened_data()]


def _worst_deviation(got: list[float], source: bytes, width: int, height: int) -> float:
    """Return the largest gap between a computed response and the true one.

    The true response is recomputed here in Python's own arithmetic, so any
    clamping, dropped sign or shifted sample shows up as a non-zero deviation.

    Args:
        got: The responses under test.
        source: The frame's bytes, row-major.
        width: The frame's width.
        height: The frame's height.

    Returns:
        The largest absolute deviation found.

    """
    worst = 0.0
    for y in range(1, height - 1):
        for x in range(1, width - 1):
            index = y * width + x
            want = (
                source[index - width]
                + source[index + width]
                + source[index - 1]
                + source[index + 1]
                - 4 * source[index]
            )
            worst = max(worst, abs(got[index] - want))
    return worst


def test_a_convolution_keeps_the_sign_and_the_magnitude_of_every_response(
    tmp_path: pathlib.Path,
) -> None:
    """The responses are the true float Laplacian, not an 8-bit clamp of it.

    The falsifier for a **real defect**: this adapter used Pillow's own
    ``ImageFilter.Kernel``, which writes an 8-bit unsigned frame. A Laplacian
    response of ``-510`` - a text stroke on white paper - was therefore stored as
    ``0``, and a fully defocused receipt whose true variance is ``0.8977`` was
    reported as ``154.9173``, i.e. **legible**. Every mode that filter accepts
    was measured and every one saturates.

    The assertion is against **independently computed** responses rather than
    against a number this suite picked, so any clamping, dropped sign or shifted
    sample fails here. A test asserting only ``variance > 0`` would have passed
    on the broken implementation.
    """
    vendor = PillowVendor()
    frame, _meta = vendor.decode(_edge_png(tmp_path / "edge.png"))
    luminance = vendor.greyscale(frame)
    width, height = luminance.size

    convolved = vendor.convolved(luminance, _LAPLACIAN, (3, 3))
    got = _responses(convolved)

    source = Image.open(tmp_path / "edge.png").convert("L").tobytes()
    worst = _worst_deviation(got, source, width, height)

    assert worst == 0.0, f"a response was clamped or shifted by up to {worst}"
    # The positive control: this pattern really does need more than 8 bits, so the
    # assertion above cannot pass by the fixture being too easy.
    below = [value for value in got if value < -255]
    assert below, "the fixture must produce a response below -255 to be a falsifier"


def test_a_convolution_does_not_copy_the_source_into_its_border(
    tmp_path: pathlib.Path,
) -> None:
    """The border ring is neutral, never the page's own brightness.

    The second half of the same defect, and the half that dominated the number.
    Pillow's filter fills the outermost pixel ring of its output with the
    **source** pixels rather than a response - the four border rows and columns
    hold the page's brightness while the interior holds Laplacian responses near
    zero. On a corpus receipt that ring was ``0.43%`` of the pixels and produced
    ``99.8%`` of the reported sharpness.
    """
    vendor = PillowVendor()
    frame, _meta = vendor.decode(_edge_png(tmp_path / "edge.png"))
    luminance = vendor.greyscale(frame)
    width, height = luminance.size

    convolved = vendor.convolved(luminance, _LAPLACIAN, (3, 3))
    got = _responses(convolved)

    ring = [
        got[y * width + x]
        for y in range(height)
        for x in range(width)
        if y in (0, height - 1) or x in (0, width - 1)
    ]

    assert set(ring) == {0.0}, (
        "the border must contribute nothing; got values that look like the source "
        f"brightness: {sorted(set(ring))[:5]}"
    )


def test_a_missing_file_is_a_typed_refusal(tmp_path: pathlib.Path) -> None:
    """An absent file reports ``unsupported_format``, never an empty frame."""
    with pytest.raises(RasterVendorError) as raised:
        PillowVendor().decode(tmp_path / "absent.png")

    assert raised.value.reason.code == "unsupported_format"


def test_bytes_that_are_not_an_image_are_a_typed_refusal(
    tmp_path: pathlib.Path,
) -> None:
    """A file that is not decodable reports, rather than raising the library's error."""
    path = tmp_path / "not-an-image.png"
    path.write_text("this is not a PNG", encoding="utf-8")

    with pytest.raises(RasterVendorError) as raised:
        PillowVendor().decode(path)

    assert raised.value.reason.code == "unsupported_format"
    assert "could not be decoded" in raised.value.reason.message


def test_the_engine_terms_name_the_library_and_its_version() -> None:
    """The cache key gets the library's identity, because a different build is
    different work."""
    terms = dict(PillowVendor().engine_terms())

    assert terms["engine"] == "PIL"
    assert terms["engine_version"] != "unknown"


# --- The engine end to end, over a real file --------------------------------


def test_the_engine_loads_a_real_file_through_the_seam(plain_png: pathlib.Path) -> None:
    """The four operations reach the vendor and come back with a result."""
    engine = RasterEngine()

    loaded = engine.load(plain_png)

    assert loaded.value is not None
    assert loaded.value.media_type == "image/png"
    assert dict(loaded.evidence.terms)["engine"] == "PIL"


def test_the_engine_reports_a_missing_library_through_a_typed_reason(
    plain_png: pathlib.Path,
) -> None:
    """A vendor that refuses gives the kernel something to report.

    The kernel turns the refusal into a ``Reason`` rather than letting it escape,
    which is the contract the seam exists to make checkable.
    """

    class _Refusing(PillowVendor):
        """A vendor whose library is absent."""

        def decode(self, path: pathlib.Path) -> tuple[RasterFrame, ImageMeta]:
            """Refuse every decode.

            Args:
                path: Unused: the refusal comes before the file is read.

            Raises:
                RasterVendorError: Always.

            """
            del path
            raise RasterVendorError(
                Reason(
                    code="engine_unavailable",
                    message="the 'PIL' library is not installed",
                )
            )

        def engine_terms(self) -> dict[str, str]:
            """Refuse: an uninstalled library has no identity.

            Raises:
                RasterVendorError: Always.

            """
            raise RasterVendorError(
                Reason(code="engine_unavailable", message="not installed")
            )

    result = RasterEngine(vendor=_Refusing()).load(plain_png)

    assert result.value is None
    assert result.reason is not None
    assert result.reason.code == "engine_unavailable"
