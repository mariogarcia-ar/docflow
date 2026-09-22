"""Tests for the split/extract primitives (``PDF-04``).

The fixture is the committed three-page document, so the assertions are about real bytes
rather than about a mock's behaviour. Its identity is asserted before and after the run:
the input-immutability invariant is the one this task is named for, and a test that only
checked the outputs would pass even if the source had been rewritten.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from docflow.pdf.primitives.engine import (
    PopplerCommand,
    PopplerExecutionError,
    PopplerOutputMissingError,
    run_engine_command,
)
from docflow.pdf.primitives.split import extract_page, merge_pdfs, split_pdf

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
THREE_PAGE_PDF = FIXTURES / "matrix" / "three-invoices.pdf"

PAGE_COUNT = 3


def sha256(path: Path) -> str:
    """Return the hex digest of a file's bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def page_text(path: Path) -> str:
    """Return the native text of a one-page PDF, for order assertions."""
    return run_engine_command(PopplerCommand.PDFTOTEXT, [str(path), "-"])


@pytest.fixture(name="source_pdf")
def source_pdf_fixture() -> Path:
    """Return the committed three-page fixture, asserting its shape."""
    assert THREE_PAGE_PDF.exists(), f"missing fixture: {THREE_PAGE_PDF}"
    return THREE_PAGE_PDF


def test_split_pdf_writes_one_file_per_page_in_order(
    source_pdf: Path, tmp_path: Path
) -> None:
    """A three-page document yields three one-page PDFs, named and ordered by page."""
    written = split_pdf(source_pdf, tmp_path / "pages")

    assert [path.name for path in written] == [
        f"page_{index:03d}.pdf" for index in range(1, PAGE_COUNT + 1)
    ]
    assert all(path.exists() for path in written)
    assert all(path.stat().st_size > 0 for path in written)


def test_each_split_page_carries_exactly_its_own_page(
    source_pdf: Path, tmp_path: Path
) -> None:
    """The split is aligned: page 1 of the output is page 1 of the document.

    Checked by content, not by file count. A renumbering mistake would still produce three
    files; only reading them shows whether they are in the right order.
    """
    written = split_pdf(source_pdf, tmp_path / "pages")

    for index, path in enumerate(written, start=1):
        # Each page of the fixture announces its own number in its text layer, which makes
        # the ordering observable without reading the PDF with a second library.
        assert f"page {index} of {PAGE_COUNT}" in page_text(path)


def test_extract_page_writes_the_requested_page(
    source_pdf: Path, tmp_path: Path
) -> None:
    """One page can be extracted to an explicit path, and it is the page asked for."""
    target = tmp_path / "page_001" / "source" / "page.pdf"

    returned = extract_page(source_pdf, 2, target)

    assert returned == target
    assert target.exists()
    assert "page 2 of 3" in page_text(target)


def test_extract_page_creates_the_output_directory(
    source_pdf: Path, tmp_path: Path
) -> None:
    """The engine does not create directories, so the primitive has to."""
    target = tmp_path / "deep" / "page_001" / "source" / "page.pdf"

    extract_page(source_pdf, 1, target)

    assert target.exists()


def test_extract_page_rejects_a_page_number_below_one(
    source_pdf: Path, tmp_path: Path
) -> None:
    """Page 0 is refused instead of being interpreted as 'no range'.

    With a ``%d`` template, ``pdfseparate -f 0 -l 0`` is *accepted* by Poppler: the zero
    bound reads as the absence of a range and the engine splits the whole document. The
    first implementation therefore returned page 1 — renumbered to ``page_001`` — for a
    request for page 0, delivering a wrong page as a success.

    Mutation that breaks it: remove ``_require_positive_pages`` from **both**
    ``extract_page`` and ``_split_range_to_directory``, and return to the template
    invocation. Removing only one is not enough to make this test fail, because the two
    defences are deliberately independent: the explicit guard rejects the bound, and the
    file output path makes the engine refuse it. Both were verified by mutation.
    """
    for invalid in (0, -1):
        with pytest.raises(ValueError, match="1-based"):
            extract_page(source_pdf, invalid, tmp_path / f"bad{invalid}.pdf")


def test_page_zero_never_yields_page_one(source_pdf: Path, tmp_path: Path) -> None:
    """The failure mode above, stated as what it must never produce.

    Kept separate from the raises-check so the *consequence* is pinned, not only the
    exception: no artifact may exist for a page number the document does not have.
    """
    target = tmp_path / "page_000.pdf"

    with pytest.raises(ValueError):
        extract_page(source_pdf, 0, target)

    assert not target.exists()


def test_the_engine_really_does_read_a_zero_bound_as_no_range(
    source_pdf: Path, tmp_path: Path
) -> None:
    """The hazard the two defences exist for, demonstrated against the engine itself.

    The claim is not taken on trust: the template invocation is run directly, bypassing the
    library, and its output is shown to be the whole document rather than nothing. If a
    future Poppler starts rejecting a zero bound, this test fails and the documentation
    around it becomes wrong — which is the point, because the comment above
    ``_require_positive_pages`` justifies a guard by referring to this behaviour.
    """
    template = str(tmp_path / "page_%03d.pdf")

    run_engine_command(
        PopplerCommand.PDFSEPARATE,
        ["-f", "0", "-l", "0", str(source_pdf), template],
    )

    written = sorted(tmp_path.glob("page_*.pdf"))
    assert len(written) == PAGE_COUNT, (
        "a zero bound no longer means 'no range'; the guard's justification in "
        "split.py must be re-checked"
    )


def test_extract_page_reports_an_out_of_range_page(
    source_pdf: Path, tmp_path: Path
) -> None:
    """A page the document does not have is the engine's own error, not a guess."""
    with pytest.raises(PopplerExecutionError) as failure:
        extract_page(source_pdf, PAGE_COUNT + 1, tmp_path / "oob.pdf")

    assert failure.value.returncode is not None
    assert failure.value.returncode != 0


def test_the_input_pdf_is_byte_identical_after_a_run(
    source_pdf: Path, tmp_path: Path
) -> None:
    """The source is read-only: its digest is the same before and after.

    This is invariant 2 of ``subplan-procesador-pdf.md`` §6. Mutation that breaks it: make
    ``extract_page`` write to ``pdf_path`` instead of the caller's ``output_path``. The
    digest comparison fails, and the processor has destroyed the caller's document.
    """
    before = sha256(source_pdf)

    split_pdf(source_pdf, tmp_path / "pages")
    extract_page(source_pdf, 1, tmp_path / "one" / "page.pdf")

    assert sha256(source_pdf) == before


def test_merge_reassembles_the_pages_in_order(source_pdf: Path, tmp_path: Path) -> None:
    """The generic utility is exercised off the happy path, so it does not rot."""
    pages = split_pdf(source_pdf, tmp_path / "pages")

    merged = merge_pdfs(pages, tmp_path / "merged.pdf")

    assert merged.exists()
    assert merged.stat().st_size > 0

    text = page_text(merged)
    for index in range(1, PAGE_COUNT + 1):
        assert f"page {index} of {PAGE_COUNT}" in text


def test_merge_rejects_an_empty_input_list(tmp_path: Path) -> None:
    """Merging nothing is a caller error, not an empty document to publish."""
    with pytest.raises(ValueError, match="at least one"):
        merge_pdfs([], tmp_path / "merged.pdf")


def test_a_successful_page_never_points_at_a_missing_file(
    source_pdf: Path, tmp_path: Path
) -> None:
    """The post-condition the primitives check is the one that matters downstream.

    ``PDF-09`` will record the returned path in a ``PDFPageResult``; a path that does not
    exist would be published as a successful page. The guard exists for that reason, and
    this asserts the returned path is real rather than merely non-empty.
    """
    declared = extract_page(source_pdf, 1, tmp_path / "p" / "page.pdf")

    assert declared.exists()
    assert declared.is_file()


def test_the_output_missing_error_is_typed_and_names_its_target() -> None:
    """The guard's error carries the engine and the path, so a log is actionable."""
    expected = Path("/tmp/never-written.pdf")
    error = PopplerOutputMissingError(PopplerCommand.PDFSEPARATE, expected)

    assert error.command is PopplerCommand.PDFSEPARATE
    assert error.expected_path == expected
    assert str(expected) in str(error)
