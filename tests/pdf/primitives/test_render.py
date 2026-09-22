"""Tests for the render primitive (``PDF-05``).

The fixture is a committed three-page document with a known page size (612 x 792 pt), so
the rendered pixel dimensions are a real prediction — ``points / 72 * dpi`` — rather than a
restatement of whatever the engine happened to produce.
"""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path

import pytest

from docflow.pdf.primitives.engine import (
    PopplerCommand,
    PopplerOutputMissingError,
    run_engine_command,
)
from docflow.pdf.primitives.failures import PDFPrimitiveError
from docflow.pdf.primitives.render import (
    MIN_RENDER_DPI,
    RENDER_FORMAT,
    render_page_to_image,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
THREE_PAGE_PDF = FIXTURES / "matrix" / "three-invoices.pdf"

PAGE_COUNT = 3
PAGE_WIDTH_POINTS = 612.0
PAGE_HEIGHT_POINTS = 792.0
DEFAULT_DPI = 200


@pytest.fixture(name="source_pdf")
def source_pdf_fixture() -> Path:
    """Return the committed three-page fixture, asserting its shape."""
    assert THREE_PAGE_PDF.exists(), f"missing fixture: {THREE_PAGE_PDF}"
    return THREE_PAGE_PDF


def png_dimensions(path: Path) -> tuple[int, int]:
    """Return a PNG's ``(width, height)`` from its IHDR header.

    Read from the file rather than through an image library: the point is to verify the
    artifact the engine wrote, and pulling in a decoder to do it would make the test depend
    on something the processor does not.
    """
    header = path.read_bytes()[:24]
    assert header[:8] == b"\x89PNG\r\n\x1a\n", f"{path} is not a PNG"
    return struct.unpack(">II", header[16:24])


def expected_pixels(dpi: int) -> tuple[int, int]:
    """Return the pixel size a page of the fixture must render to at ``dpi``."""
    return (
        round(PAGE_WIDTH_POINTS / 72 * dpi),
        round(PAGE_HEIGHT_POINTS / 72 * dpi),
    )


def test_render_writes_a_decodable_png_at_the_requested_size(
    source_pdf: Path, tmp_path: Path
) -> None:
    """A PNG appears at the caller's path, and its pixels match the page at that DPI."""
    target = tmp_path / "page_001" / "render" / "page.png"

    returned = render_page_to_image(source_pdf, 1, target, dpi=DEFAULT_DPI)

    assert returned == target
    assert target.exists()
    assert png_dimensions(target) == expected_pixels(DEFAULT_DPI)


@pytest.mark.parametrize("dpi", [72, 150, 300])
def test_the_image_scales_with_the_requested_dpi(
    source_pdf: Path, tmp_path: Path, dpi: int
) -> None:
    """Resolution is honoured, not substituted.

    Mutation that breaks it: drop the ``-r`` argument from the engine call. The engine then
    renders at its own default of 150 DPI, and the 72 and 300 cases fail while the 150 case
    still passes — which is exactly the kind of silent substitution the plan forbids.
    """
    target = tmp_path / f"page-{dpi}.png"

    render_page_to_image(source_pdf, 1, target, dpi=dpi)

    assert png_dimensions(target) == expected_pixels(dpi)


def test_render_is_the_page_that_was_asked_for(
    source_pdf: Path, tmp_path: Path
) -> None:
    """Two different pages render to different images.

    A renderer that ignored ``-f``/``-l`` would return page 1 for every request while still
    producing a correctly sized PNG, so the size check alone would not catch it.
    """
    first = render_page_to_image(source_pdf, 1, tmp_path / "one.png")
    second = render_page_to_image(source_pdf, 2, tmp_path / "two.png")

    assert first.read_bytes() != second.read_bytes()


def test_render_creates_the_output_directory(source_pdf: Path, tmp_path: Path) -> None:
    """The engine does not create directories, so the primitive has to."""
    target = tmp_path / "deep" / "page_001" / "render" / "page.png"

    render_page_to_image(source_pdf, 1, target)

    assert target.exists()


def test_render_publishes_under_the_exact_name_the_caller_gave(
    source_pdf: Path, tmp_path: Path
) -> None:
    """No engine suffix survives into the published artifact.

    ``pdftoppm`` appends its own suffix to the prefix it is given, so ``page.png`` as a
    prefix yields ``page.png.png``. The published path must be the caller's, and nothing
    else may be left behind for a later stage to mistake for an artifact.

    Mutation that breaks it: hand the engine ``output_path`` directly instead of a staged
    prefix. ``page.png`` is then missing and ``page.png.png`` is present, so both assertions
    fail.
    """
    target = tmp_path / "render" / "page.png"

    render_page_to_image(source_pdf, 1, target)

    assert target.exists()
    assert sorted(path.name for path in target.parent.iterdir()) == ["page.png"]


def test_no_staged_file_survives_a_successful_render(
    source_pdf: Path, tmp_path: Path
) -> None:
    """The staging name is an implementation detail, never a residue."""
    render_page_to_image(source_pdf, 1, tmp_path / "render" / "page.png")

    leftovers = [path.name for path in tmp_path.rglob("*staged*")]

    assert not leftovers, f"a staged file was published: {leftovers}"


def test_render_rejects_a_page_number_below_one(
    source_pdf: Path, tmp_path: Path
) -> None:
    """Page 0 is refused rather than silently rendered as page 1.

    ``pdftoppm -singlefile -f 0 -l 0`` exits 0 and writes a render byte-identical to page 1,
    so a forwarded zero would be indistinguishable from a correct result downstream. Unlike
    the split primitive, there is no second defence here: the engine offers no ``%d``
    template that would make it refuse the bound, so this guard is the only thing standing
    between a caller error and a plausible wrong image.

    Mutation that breaks it: remove the ``require_positive_page_range`` call. The
    ``pytest.raises`` blocks fail, and the test below demonstrates the wrong image that
    follows.
    """
    for invalid in (0, -1):
        with pytest.raises(ValueError, match="1-based"):
            render_page_to_image(source_pdf, invalid, tmp_path / f"bad{invalid}.png")


def test_page_zero_never_yields_the_page_one_render(
    source_pdf: Path, tmp_path: Path
) -> None:
    """The failure mode, stated as the artifact it must never produce.

    Pinned separately from the raises-check so the *consequence* is what is asserted: no
    file, rather than a file that happens to be page 1.
    """
    target = tmp_path / "page_000.png"

    with pytest.raises(ValueError):
        render_page_to_image(source_pdf, 0, target)

    assert not target.exists()


def test_the_engine_really_does_render_page_one_for_a_zero_bound(
    source_pdf: Path, tmp_path: Path
) -> None:
    """The hazard the guard exists for, demonstrated against the engine itself.

    Run directly, bypassing the library, so the claim is not taken on trust: a zero bound is
    accepted, exits 0, and produces a file identical to the page-1 render. If a future
    Poppler changes this, the test fails and the justification recorded in ``render.py``
    becomes wrong — which is the point of pinning it.
    """
    zero_bound = tmp_path / "zero.png"
    page_one = tmp_path / "one.png"

    run_engine_command(
        PopplerCommand.PDFTOPPM,
        [
            "-singlefile",
            "-f",
            "0",
            "-l",
            "0",
            f"-{RENDER_FORMAT}",
            "-r",
            str(DEFAULT_DPI),
            str(source_pdf),
            str(tmp_path / "zero"),
        ],
    )
    (tmp_path / "zero.png").replace(zero_bound)

    render_page_to_image(source_pdf, 1, page_one, dpi=DEFAULT_DPI)

    assert hashlib.sha256(zero_bound.read_bytes()).hexdigest() == (
        hashlib.sha256(page_one.read_bytes()).hexdigest()
    ), "a zero bound no longer renders page 1; re-check the guard's justification"


def test_render_rejects_a_dpi_the_engine_would_silently_replace(
    source_pdf: Path, tmp_path: Path
) -> None:
    """A zero resolution is refused, because the engine accepts it as "use my default".

    ``pdftoppm -r 0`` exits 0 and renders at 150 DPI. Forwarding it would put the requested
    DPI in ``metadata.json`` while the image on disk has a different one, which is a
    provenance field that lies.

    Mutation that breaks it: delete the ``MIN_RENDER_DPI`` check. The raises block fails,
    and the render silently lands at 150 DPI.
    """
    for invalid in (0, -1):
        with pytest.raises(ValueError, match="dpi must be at least"):
            render_page_to_image(
                source_pdf, 1, tmp_path / f"dpi{invalid}.png", dpi=invalid
            )

    assert MIN_RENDER_DPI >= 1


def test_render_reports_a_page_past_the_end_of_the_document(
    source_pdf: Path, tmp_path: Path
) -> None:
    """A page the document does not have is reported as out of range, and typed.

    ``PDF-11`` unified the error model: every primitive classifies the engine's failure into
    the contract's own vocabulary, so a caller gets ``PAGE_OUT_OF_RANGE`` rather than an exit
    code it would have to interpret. The render was the last primitive still handing back a
    raw ``PopplerExecutionError`` while its four siblings were typed.
    """
    with pytest.raises(PDFPrimitiveError) as failure:
        render_page_to_image(source_pdf, PAGE_COUNT + 1, tmp_path / "oob.png")

    assert failure.value.error_type == "PAGE_OUT_OF_RANGE"
    assert failure.value.page_number == PAGE_COUNT + 1


def test_render_never_modifies_the_source_pdf(source_pdf: Path, tmp_path: Path) -> None:
    """The renderer reads the document and writes only where it was told."""
    before = hashlib.sha256(source_pdf.read_bytes()).hexdigest()

    render_page_to_image(source_pdf, 1, tmp_path / "page.png")

    assert hashlib.sha256(source_pdf.read_bytes()).hexdigest() == before


def test_a_successful_render_never_declares_a_missing_file(
    source_pdf: Path, tmp_path: Path
) -> None:
    """The returned path is a real, non-empty file, which is what ``PDF-09`` will record."""
    declared = render_page_to_image(source_pdf, 1, tmp_path / "page.png")

    assert declared.is_file()
    assert declared.stat().st_size > 0


def test_an_engine_that_writes_nothing_is_reported_not_published(
    source_pdf: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A success claim with no artifact behind it becomes a typed error.

    ``run_engine_command`` is replaced with a no-op, which is the only way to reach this
    branch: every failure Poppler 25.02.0 actually produces, it also reports with a
    non-zero status. The guard is a post-condition, so it is exercised directly rather than
    left as an untested promise — this is the branch ``PDF-09`` relies on when it records
    the returned path in a page result.

    Mutation that breaks it: delete the existence check in ``render_page_to_image``. The
    ``pytest.raises`` block fails, and ``render_page_to_image`` returns a path to a file
    that does not exist, which is the silent stand-in the plan forbids.
    """
    # Patched at the seam wrapper the primitive now calls, not at `run_engine_command`:
    # `PDF-11` moved the classification into `run_classified` and the primitive no longer
    # reaches the raw runner, so the older patch target stopped intercepting anything.
    monkeypatch.setattr(
        "docflow.pdf.primitives.render.run_classified", lambda *a, **k: ""
    )

    with pytest.raises(PopplerOutputMissingError) as failure:
        render_page_to_image(source_pdf, 1, tmp_path / "never-written.png")

    assert failure.value.command is PopplerCommand.PDFTOPPM
    assert failure.value.expected_path == tmp_path / "never-written.png"
