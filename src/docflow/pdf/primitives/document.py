"""Document primitives — what a PDF reports about itself, before any extraction.

Owned by ``PDF-03``. These functions read the document's own properties: its metadata, its
page count and each page's size. They extract nothing, render nothing and classify nothing.

Engine access goes through :mod:`docflow.pdf.primitives.engine` rather than a direct
``subprocess`` invocation, so the engine stays swappable inside this package.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PDFDocumentInfo:
    """What a PDF reports about itself, gathered in one pass.

    Attributes:
        metadata: The document's own metadata, as the engine reports it (title, producer,
            creation date, …). Values are strings because that is how they are read.
        page_count: Number of pages.
        page_dimensions: Page size in PDF points, per page, in page order.
        encrypted: Whether the document is encrypted.
    """

    metadata: dict[str, str]
    page_count: int
    page_dimensions: list[tuple[float, float]]
    encrypted: bool


def get_pdf_metadata(pdf_path: Path) -> dict[str, str]:
    """Read the document's own metadata.

    Args:
        pdf_path: PDF to inspect. Never written to.

    Returns:
        The metadata as key/value pairs, exactly as the engine reports it.

    Raises:
        NotImplementedError: Phase 1 declares the signature only.

    # TODO: [MVP] parse `pdfinfo` output; real per-key typing (dates, page sizes) is
    # deferred and every value is exposed as the engine's own string.
    """
    raise NotImplementedError("get_pdf_metadata is implemented in Phase 1 by PDF-03")


def get_page_count(pdf_path: Path) -> int:
    """Count the pages of a PDF.

    Args:
        pdf_path: PDF to inspect.

    Returns:
        The number of pages.

    Raises:
        NotImplementedError: Phase 1 declares the signature only.

    # TODO: [MVP] read the count from the engine (PDF-03).
    """
    raise NotImplementedError("get_page_count is implemented in Phase 1 by PDF-03")


def get_page_dimensions(pdf_path: Path, page_number: int) -> tuple[float, float]:
    """Measure one page.

    Args:
        pdf_path: PDF to inspect.
        page_number: Page index, 1-based.

    Returns:
        The page's ``(width, height)`` in PDF points.

    Raises:
        NotImplementedError: Phase 1 declares the signature only.

    # TODO: [MVP] read the page size from the engine (PDF-03).
    """
    raise NotImplementedError("get_page_dimensions is implemented in Phase 1 by PDF-03")


def inspect_pdf(pdf_path: Path) -> PDFDocumentInfo:
    """Summarise a document in one call.

    Args:
        pdf_path: PDF to inspect.

    Returns:
        The document's metadata, page count and per-page dimensions.

    Raises:
        NotImplementedError: Phase 1 declares the signature only.

    # TODO: [MVP] compose the three calls above into one engine pass (PDF-03).
    """
    raise NotImplementedError("inspect_pdf is implemented in Phase 1 by PDF-03")


__all__ = [
    "PDFDocumentInfo",
    "get_page_count",
    "get_page_dimensions",
    "get_pdf_metadata",
    "inspect_pdf",
]
