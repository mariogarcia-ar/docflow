"""Entry point of the OCR processor.

The signature is frozen by ``docs/plan/README.md`` §4 (the idea's §"Naming"): ``ocr``
exposes ``process_ocr_image()``. Phase 0 ships the signature only; the body raises rather
than returning a placeholder.

Phase 1 fills this in: ``OCR-11`` implements :func:`process_ocr_image`.
"""

from __future__ import annotations

from docflow.ocr.contracts import OCRRequest, OCRResult


def process_ocr_image(request: OCRRequest) -> OCRResult:
    """Extract text, structure and tables from a prepared image.

    Args:
        request: The prepared image to read and the OCR options to use.

    Returns:
        The extraction result and the paths of the artifacts published under ``ocr/``.

    Raises:
        NotImplementedError: Phase 0 ships the signature only.

    # TODO: [MVP] chain validate → configure → run engine → extract → build outputs →
    # metrics → validate → atomic persist (OCR-11).
    """
    raise NotImplementedError("process_ocr_image is implemented in Phase 1 by OCR-11")
