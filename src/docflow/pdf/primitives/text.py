"""Native text primitives — the text layer the PDF already carries.

Owned by ``PDF-06``. An empty text layer is **data**, not a defect to fix: this module has
no OCR fallback, because "nothing was found" and "nothing could be read" are different
answers and only the orchestrator may decide what to do about the second one.
"""

from __future__ import annotations

from pathlib import Path

from docflow.pdf.contracts import TextBlock


def extract_text_from_page(
    pdf_path: Path,
    page_number: int,
    layout: bool = True,
) -> str:
    """Read the native text of one page.

    Args:
        pdf_path: Source PDF. Read only.
        page_number: Page index, 1-based.
        layout: Preserve the page's physical layout in the text. The default follows the
            frozen signature of ``subplan-procesador-pdf.md`` §3; the caller passes
            ``PDFOptions.layout``.

    Returns:
        The page's native text. Empty when the page has no text layer — a measurement,
        never an error and never a prompt to substitute another engine.

    Raises:
        NotImplementedError: Phase 1 declares the signature only.

    # TODO: [MVP] drive pdftotext for the requested page (PDF-06).
    """
    raise NotImplementedError(
        "extract_text_from_page is implemented in Phase 1 by PDF-06"
    )


def get_text_blocks(pdf_path: Path, page_number: int) -> list[TextBlock]:
    """Read the native text of one page as ordered blocks with their placement.

    Args:
        pdf_path: Source PDF. Read only.
        page_number: Page index, 1-based.

    Returns:
        The page's text blocks in reading order. Empty when the page has no text layer.

    Raises:
        NotImplementedError: Phase 1 declares the signature only.

    # TODO: [MVP] reconstruct layout-aware blocks from the engine's bounding boxes
    # (PDF-06).
    """
    raise NotImplementedError("get_text_blocks is implemented in Phase 1 by PDF-06")
