"""Entry points of the PDF processor.

The signatures are frozen by ``docs/plan/README.md`` §4 (the idea's §"Naming"): ``pdf``
exposes ``process_pdf()`` and ``process_pdf_page()``. Phase 0 ships the signatures only;
the bodies raise rather than returning a placeholder, so a caller can never mistake a
stub for a processed document.

Phase 1 fills these in: ``PDF-09`` implements :func:`process_pdf_page` and ``PDF-10``
implements :func:`process_pdf`.
"""

from __future__ import annotations

from pathlib import Path

from docflow.pdf.contracts import PDFPageResult, PDFRequest, PDFResult


def process_pdf(request: PDFRequest) -> PDFResult:
    """Process every page of a PDF and return the consolidated document result.

    Args:
        request: The document to process, its requested capabilities and its
            correlation context.

    Returns:
        The document result, with one :class:`~docflow.pdf.contracts.PDFPageResult` per
        page in page order and an aggregate
        :class:`~docflow.pdf.contracts.PDFPageMetrics`.

    Raises:
        NotImplementedError: Phase 0 ships the signature only.

    # TODO: [MVP] implement the page loop and the aggregate consolidation (PDF-10).
    """
    raise NotImplementedError("process_pdf is implemented in Phase 1 by PDF-10")


def process_pdf_page(
    request: PDFRequest,
    page_number: int,
    output_dir: Path,
) -> PDFPageResult:
    """Process exactly one page of a PDF.

    Args:
        request: The document the page belongs to; its ``options`` decide which
            capabilities run.
        page_number: Page index, 1-based.
        output_dir: Directory for this page's artifacts (``page_NNN/``).

    Returns:
        The page result. When one capability fails while others succeed, the status is
        ``partial`` and the valid artifacts are preserved.

    Raises:
        NotImplementedError: Phase 0 ships the signature only.

    # TODO: [MVP] chain extract → render → text → blocks → images → analyze →
    # classify (PDF-09).
    """
    raise NotImplementedError("process_pdf_page is implemented in Phase 1 by PDF-09")
