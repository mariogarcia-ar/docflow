"""Embedded image primitives — the pictures physically stored inside a page.

Owned by ``PDF-07``. A page with no embedded images is valid data, not a failure: many
text-dominant pages contain none, and reporting that as an error would make the processor
lie about the document.

Identifiers are zero-padded and assigned in the engine's own order, so a re-run over the
same bytes publishes the same names in the same order — the determinism class
``subplan-procesador-pdf.md`` §3 declares for this processor.
"""

from __future__ import annotations

from pathlib import Path

from docflow.pdf.contracts import EmbeddedImage


def extract_images_from_page(
    pdf_path: Path,
    page_number: int,
    output_dir: Path,
) -> list[EmbeddedImage]:
    """Write every image embedded in one page, with stable zero-padded names.

    Args:
        pdf_path: Source PDF. Read only.
        page_number: Page index, 1-based.
        output_dir: Directory for the extracted images (``embedded_images/``).

    Returns:
        One record per extracted image, in a stable order, each pointing at
        ``image_001.png``, ``image_002.png``, … Returns an empty list when the page embeds
        no image — a measurement, not a failure.

    Raises:
        NotImplementedError: Phase 1 declares the signature only.

    # TODO: [MVP] drive pdfimages and map its output onto EmbeddedImage records; unusual
    # colour spaces and masks are deferred for the PoC (PDF-07).
    """
    raise NotImplementedError(
        "extract_images_from_page is implemented in Phase 1 by PDF-07"
    )


def get_image_blocks(pdf_path: Path, page_number: int) -> list[EmbeddedImage]:
    """Report where each embedded image sits on the page, without extracting it.

    Args:
        pdf_path: Source PDF. Read only.
        page_number: Page index, 1-based.

    Returns:
        One record per embedded image, carrying its placement. Empty when the page embeds
        no image.

    Raises:
        NotImplementedError: Phase 1 declares the signature only.

    # TODO: [MVP] read placement from the engine's image list (PDF-07).
    """
    raise NotImplementedError("get_image_blocks is implemented in Phase 1 by PDF-07")
