"""Split/extract primitives — one self-contained PDF per page, source untouched.

Owned by ``PDF-04``. Output lands under ``page_NNN/source/page.pdf``; the input file is
read-only, and the input-immutability invariant of ``PDF-13`` guards exactly that.
"""

from __future__ import annotations

from pathlib import Path


def extract_page(pdf_path: Path, page_number: int, output_path: Path) -> Path:
    """Write one page of a PDF as a self-contained one-page PDF.

    Args:
        pdf_path: Source PDF. Read only: never written to.
        page_number: Page index, 1-based.
        output_path: Where the one-page PDF is written.

    Returns:
        ``output_path``, once the file exists.

    Raises:
        NotImplementedError: Phase 1 declares the signature only.

    # TODO: [MVP] drive pdfseparate for the requested page (PDF-04).
    """
    raise NotImplementedError("extract_page is implemented in Phase 1 by PDF-04")


def split_pdf(pdf_path: Path, output_dir: Path) -> list[Path]:
    """Write every page of a PDF as its own one-page PDF.

    Args:
        pdf_path: Source PDF. Read only.
        output_dir: Directory to write the one-page PDFs into.

    Returns:
        The written files, in page order.

    Raises:
        NotImplementedError: Phase 1 declares the signature only.

    # TODO: [MVP] drive pdfseparate over the whole document (PDF-04).
    """
    raise NotImplementedError("split_pdf is implemented in Phase 1 by PDF-04")


def merge_pdfs(pdf_paths: list[Path], output_path: Path) -> Path:
    """Concatenate PDFs into one file.

    A generic utility, deliberately off the happy path: nothing in the document workflow
    merges pages back together.

    Args:
        pdf_paths: Files to concatenate, in the order they should appear.
        output_path: Where the combined PDF is written.

    Returns:
        ``output_path``, once the file exists.

    Raises:
        NotImplementedError: Phase 1 declares the signature only.

    # TODO: [MVP] implement with pdfunite; deferred because no workflow stage needs it.
    """
    raise NotImplementedError("merge_pdfs is implemented in Phase 1 by PDF-04")
