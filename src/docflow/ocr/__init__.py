"""OCR processor: ``OCRRequest → OCRResult``.

Turns an already-prepared image into a textual and structured representation: plain text,
Markdown, a stable ``document.json``, blocks, tables, normalized layout, reading order,
metrics and a descriptive extraction status, all published atomically under ``ocr/``.

Engine: Docling, the only OCR engine, reached only from :mod:`docflow.ocr.primitives`.
The engine is fixed and never exposed as a user-selectable option. The processor imports
no other processor and decides nothing about what should happen next.

Entry point: :func:`process_ocr_image`.

Symbols are re-exported here, but only :mod:`docflow.ocr.primitives` may import them.
"""

from __future__ import annotations

from docflow.ocr.contracts import (
    ArtifactPaths,
    BlockResult,
    LayoutResult,
    NormalizedOCROptions,
    OCRBlockType,
    OCRContext,
    OCRDocument,
    OCRError,
    OCRErrorType,
    OCRMetadata,
    OCRMetrics,
    OCROptions,
    OCRRequest,
    OCRResult,
    OCRStatus,
    OCRValidation,
    OCRValidationState,
    TableResult,
)
from docflow.ocr.entrypoints import process_ocr_image

__all__ = [
    "ArtifactPaths",
    "BlockResult",
    "LayoutResult",
    "NormalizedOCROptions",
    "OCRBlockType",
    "OCRContext",
    "OCRDocument",
    "OCRError",
    "OCRErrorType",
    "OCRMetadata",
    "OCRMetrics",
    "OCROptions",
    "OCRRequest",
    "OCRResult",
    "OCRStatus",
    "OCRValidation",
    "OCRValidationState",
    "TableResult",
    "process_ocr_image",
]
