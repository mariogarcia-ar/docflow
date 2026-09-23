"""Entry point of the OCR processor.

The signature is frozen by ``docs/plan/README.md`` §4 (the idea's §"Naming"): ``ocr``
exposes ``process_ocr_image()``.

``OCR-11`` fills it in. The composition lives in
:mod:`docflow.ocr.primitives.composition`; this function is the published surface over it and
adds nothing of its own. It holds no engine access and makes no workflow decision — the plan's
out-of-bounds list for this task names both — so a caller can read the processor's entire
promise in one delegation.

Unlike the image processor's, this signature needs no required keyword beside the request.
``OCR-11``'s out-of-bounds list rules out a *default engine or threshold*, and there is no
engine choice to name: §9's resolved decision 1 fixed Docling as the only engine, so the
question the image processor has to keep open is already answered here.
"""

from __future__ import annotations

from docflow.ocr.contracts import OCRRequest, OCRResult
from docflow.ocr.primitives.composition import process_ocr_result


def process_ocr_image(
    request: OCRRequest,
    *,
    processing_key: str | None = None,
) -> OCRResult:
    """Extract text, structure and tables from a prepared image.

    Args:
        request: The prepared image to read and the OCR options to use.
        processing_key: The reuse key, when the orchestrator has computed one. ``None`` records
            that it has not been computed, which is not the same as the key being absent.

    Returns:
        The extraction result and the paths of the artifacts published under ``ocr/``. On the
        happy path ``status`` is ``"success"``; a failure is reported as a typed
        :class:`~docflow.ocr.contracts.OCRError` inside the result, never as an exception across
        the contract.
    """
    return process_ocr_result(request, processing_key=processing_key)
