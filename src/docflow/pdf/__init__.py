"""PDF processor: ``PDFRequest → PDFResult``.

Inspects, splits and extracts what a PDF natively contains — pages, render, native text,
text blocks, embedded images and per-page composition metrics — and classifies each page
descriptively as ``TEXT`` / ``IMAGE`` / ``MIXED``.

The entry points are :func:`process_pdf` and :func:`process_pdf_page`. The module never
decides whether work may be reused: a request is executed, and ``REUSE`` / ``SKIP`` /
``FORCE`` / ``RESUME`` belong to the orchestrator.

Engine: Poppler (``pdftotext``, ``pdfimages``, ``pdfseparate``), reached only from
:mod:`docflow.pdf.primitives`. The processor imports no other processor.

Symbols are re-exported here, but only :mod:`docflow.pdf.primitives` may import them.
"""

from __future__ import annotations

from docflow.pdf.contracts import (
    EmbeddedImage,
    PDFContext,
    PDFError,
    PDFErrorType,
    PDFMetadata,
    PDFOptions,
    PDFPageClassification,
    PDFPageMetadata,
    PDFPageMetrics,
    PDFPageResult,
    PDFPageValidation,
    PDFPageValidationState,
    PDFRequest,
    PDFResult,
    PDFStatus,
    PDFValidation,
    PDFValidationState,
    TextBlock,
)
from docflow.pdf.entrypoints import process_pdf, process_pdf_page

__all__ = [
    "EmbeddedImage",
    "PDFContext",
    "PDFError",
    "PDFErrorType",
    "PDFMetadata",
    "PDFOptions",
    "PDFPageClassification",
    "PDFPageMetadata",
    "PDFPageMetrics",
    "PDFPageResult",
    "PDFPageValidation",
    "PDFPageValidationState",
    "PDFRequest",
    "PDFResult",
    "PDFStatus",
    "PDFValidation",
    "PDFValidationState",
    "TextBlock",
    "process_pdf",
    "process_pdf_page",
]
