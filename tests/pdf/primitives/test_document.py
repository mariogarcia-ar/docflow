"""Tests for the document primitives (``PDF-03``).

The fixture is a committed three-page document whose page size is known (612 x 792 pt,
US Letter), so the dimensions are a real prediction rather than a restatement of what the
engine printed.

The error fixtures are committed alongside it: ``pdf_corrupt.pdf`` is a genuine truncation —
it keeps the ``%PDF-`` header and fails later, which is what distinguishes a corrupt document
from a file that was never a PDF — and ``pdf_encrypted.pdf`` is encrypted with a real user
password via ``pdftk``.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from docflow.pdf.primitives.document import (
    PDFDocumentInfo,
    get_page_count,
    get_page_dimensions,
    get_pdf_metadata,
    inspect_pdf,
)
from docflow.pdf.primitives.failures import PDFPrimitiveError

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "matrix"
THREE_PAGE_PDF = FIXTURES / "three-invoices.pdf"
CORRUPT_PDF = FIXTURES / "pdf_corrupt.pdf"
ENCRYPTED_PDF = FIXTURES / "pdf_encrypted.pdf"

PAGE_COUNT = 3
PAGE_WIDTH_POINTS = 612.0
PAGE_HEIGHT_POINTS = 792.0


@pytest.fixture(name="source_pdf")
def source_pdf_fixture() -> Path:
    """Return the committed three-page fixture, asserting its shape."""
    assert THREE_PAGE_PDF.exists(), f"missing fixture: {THREE_PAGE_PDF}"
    return THREE_PAGE_PDF


def test_the_page_count_is_the_documents_own(source_pdf: Path) -> None:
    """The count comes from the engine, not from a bound the caller guessed."""
    assert get_page_count(source_pdf) == PAGE_COUNT


def test_inspect_reports_the_page_count_and_every_page_size(source_pdf: Path) -> None:
    """One pass yields the count and one size per page, in page order."""
    info = inspect_pdf(source_pdf)

    assert isinstance(info, PDFDocumentInfo)
    assert info.page_count == PAGE_COUNT
    assert (
        info.page_dimensions == [(PAGE_WIDTH_POINTS, PAGE_HEIGHT_POINTS)] * PAGE_COUNT
    )


def test_a_count_beyond_the_document_does_not_inflate_the_answer(
    source_pdf: Path,
) -> None:
    """``-f 1 -l 99999`` is accepted by the engine and truncated to the real pages.

    The engine's answer is the authority. Mutation that breaks it: derive the page count
    from the requested bound instead of from the parsed output — the count becomes 99999 and
    the per-page pass then fails the cross-check, which is the failure this guards.
    """
    assert get_page_count(source_pdf) == PAGE_COUNT


def test_inspect_agrees_with_the_page_count_and_the_page_dimensions(
    source_pdf: Path,
) -> None:
    """The three functions are one story, not three independent readings."""
    info = inspect_pdf(source_pdf)

    assert len(info.page_dimensions) == get_page_count(source_pdf)
    for page_number, expected in enumerate(info.page_dimensions, start=1):
        assert get_page_dimensions(source_pdf, page_number) == expected


def test_one_page_can_be_measured_on_its_own(source_pdf: Path) -> None:
    """A page-scoped call returns that page's size, at the right page."""
    assert get_page_dimensions(source_pdf, 3) == (PAGE_WIDTH_POINTS, PAGE_HEIGHT_POINTS)


def test_page_dimensions_are_located_by_page_number_not_by_position(
    source_pdf: Path,
) -> None:
    """The page number the engine prints is what selects the line.

    A zero or shifted range would move the lines under a positional read, so position is not
    a reliable key. Mutating the loop to take the first parsed line instead of the matching
    one would still pass on this uniform fixture, which is why the guard that matters is the
    range check below — a shifted read cannot happen when the bound cannot be zero.
    """
    for page_number in range(1, PAGE_COUNT + 1):
        assert get_page_dimensions(source_pdf, page_number) == (
            PAGE_WIDTH_POINTS,
            PAGE_HEIGHT_POINTS,
        )


def test_metadata_excludes_the_per_page_lines(source_pdf: Path) -> None:
    """Per-page lines are not document metadata.

    ``pdfinfo`` prints both in one stream, and a naive ``key: value`` parse would put
    ``Page 1 size`` into the document's metadata. Mutation that breaks it: drop the
    ``_SIZE_LINE_MARKER`` filter. The second assertion fails and the metadata acquires keys
    that vary per page.
    """
    metadata = get_pdf_metadata(source_pdf)

    assert metadata["Pages"] == str(PAGE_COUNT)
    assert not [key for key in metadata if key.startswith("Page ")]


def test_metadata_reports_the_engine_own_values(source_pdf: Path) -> None:
    """Values are the engine's strings, uninterpreted for now."""
    metadata = get_pdf_metadata(source_pdf)

    assert metadata["Encrypted"] == "no"
    assert metadata["PDF version"]


def test_a_page_below_one_is_refused(source_pdf: Path) -> None:
    """Page 0 never reaches the engine, because the engine reads it as 'no range'.

    ``pdfinfo -f 0 -l 0`` is accepted and reports pages 1 **and 2** — neither the whole
    document nor nothing — so a forwarded zero would produce a plausible, wrong measurement
    rather than an error. This is the third tool in this package with that hazard, which is
    why the guard is shared in the seam.

    Mutation that breaks it: remove the ``require_positive_page_range`` call. The
    ``pytest.raises`` block fails.
    """
    for invalid in (0, -1):
        with pytest.raises(ValueError, match="1-based"):
            get_page_dimensions(source_pdf, invalid)


def test_a_page_past_the_end_is_reported_as_such(source_pdf: Path) -> None:
    """A page the document does not have is typed, and not mistaken for corruption."""
    with pytest.raises(PDFPrimitiveError) as failure:
        get_page_dimensions(source_pdf, PAGE_COUNT + 1)

    assert failure.value.error_type == "PAGE_OUT_OF_RANGE"
    assert failure.value.page_number == PAGE_COUNT + 1


def test_a_missing_file_is_a_typed_failure(tmp_path: Path) -> None:
    """An absent file is named as absent, not as corrupt."""
    with pytest.raises(PDFPrimitiveError) as failure:
        inspect_pdf(tmp_path / "nope.pdf")

    assert failure.value.error_type == "MISSING_FILE"
    assert failure.value.recoverable is False


def test_a_truncated_document_is_reported_as_corrupt() -> None:
    """A real truncation is classified as corruption, not as a missing file.

    The fixture keeps its ``%PDF-`` header and fails in the trailer, so the header check
    passes and the failure has to come from the engine call. This is the case the acceptance
    criterion names: ``CORRUPTED_PDF``, with no exception escaping as anything else.
    """
    assert CORRUPT_PDF.exists(), f"missing fixture: {CORRUPT_PDF}"

    with pytest.raises(PDFPrimitiveError) as failure:
        inspect_pdf(CORRUPT_PDF)

    assert failure.value.error_type == "CORRUPTED_PDF"
    assert failure.value.recoverable is False


def test_a_corrupt_document_keeps_its_header_so_the_causes_stay_distinct() -> None:
    """The fixture is truncated, not replaced by junk.

    Without this, ``test_a_truncated_document_is_reported_as_corrupt`` could be passing for
    the wrong reason — the header check rather than the engine's parse failure — and the two
    causes would be indistinguishable.
    """
    assert CORRUPT_PDF.read_bytes().startswith(b"%PDF-")


def test_a_file_that_is_not_a_pdf_is_corrupt(tmp_path: Path) -> None:
    """A file with no PDF header is refused before the engine is asked."""
    impostor = tmp_path / "not-a.pdf"
    impostor.write_text("this is plainly not a PDF\n")

    with pytest.raises(PDFPrimitiveError) as failure:
        inspect_pdf(impostor)

    assert failure.value.error_type == "CORRUPTED_PDF"


def test_an_encrypted_document_is_reported_rather_than_guessed_at() -> None:
    """An encrypted PDF fails fast with a password-free explanation.

    The engine exits **1** for this — the same status a truncated file gives — so the cause
    is separated by the document's own ``/Encrypt`` marker rather than by matching the
    engine's English message. Mutation that breaks it: drop the
    ``declares_encryption`` check. The type degrades to ``CORRUPTED_PDF``, which is a worse
    answer: it tells the operator to replace a file that is merely password-protected.
    """
    assert ENCRYPTED_PDF.exists(), f"missing fixture: {ENCRYPTED_PDF}"

    with pytest.raises(PDFPrimitiveError) as failure:
        inspect_pdf(ENCRYPTED_PDF)

    assert failure.value.error_type == "ENCRYPTED_PDF"
    assert failure.value.recoverable is False
    assert "/Encrypt" in ENCRYPTED_PDF.read_bytes().decode("latin-1")


def test_a_readable_document_is_not_reported_as_encrypted(source_pdf: Path) -> None:
    """The encrypted flag comes from the engine's field, and is false when readable."""
    assert inspect_pdf(source_pdf).encrypted is False


def test_inspecting_never_modifies_the_source(source_pdf: Path) -> None:
    """Inspection is read-only, which the immutable-input invariant depends on."""
    before = hashlib.sha256(source_pdf.read_bytes()).hexdigest()

    inspect_pdf(source_pdf)
    get_pdf_metadata(source_pdf)
    get_page_dimensions(source_pdf, 1)

    assert hashlib.sha256(source_pdf.read_bytes()).hexdigest() == before
