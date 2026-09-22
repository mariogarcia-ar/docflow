"""Render primitive — one faithful PNG per page, at an explicit resolution.

Owned by ``PDF-05``. The render is what this processor publishes; making it *prettier* is
``procesador-image``'s job, and this module does not deskew, denoise, binarize or enhance.
"""

from __future__ import annotations

from pathlib import Path

RENDER_FORMAT = "png"
"""The only render format in Phase 1. A constant, so no caller can silently pick another."""


def render_page_to_image(
    pdf_path: Path,
    page_number: int,
    output_path: Path,
    dpi: int = 200,
) -> Path:
    """Render one page to a PNG image.

    Args:
        pdf_path: Source PDF. Read only.
        page_number: Page index, 1-based.
        output_path: Where the PNG is written.
        dpi: Render resolution. The default is the value the frozen signature of
            ``subplan-procesador-pdf.md`` §3 documents; a caller always passes the
            resolution from ``PDFOptions.dpi``, so it stands in for no measurement.

    Returns:
        ``output_path``, once the file exists.

    Raises:
        NotImplementedError: Phase 1 declares the signature only.

    # TODO: [MVP] drive pdftoppm with the requested DPI and format (PDF-05).
    """
    raise NotImplementedError(
        "render_page_to_image is implemented in Phase 1 by PDF-05"
    )
