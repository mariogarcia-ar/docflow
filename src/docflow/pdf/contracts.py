"""Contract types of the PDF processor: ``PDFRequest → PDFResult``.

This module is vocabulary only. It performs no I/O, imports no engine and contains no
processing logic; Poppler is reached exclusively from :mod:`docflow.pdf.primitives`.

Two rules apply to every name here:

* ``context`` is correlation and tracing data. It is never read to alter behaviour.
* No field carries a domain noun. A ``TEXT`` / ``IMAGE`` / ``MIXED`` classification is
  data; only the orchestrator turns it into a decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

PDFStatus = Literal["success", "partial", "failed"]

# Document-level validation states (`PDF-11`).
PDFValidationState = Literal["VALID", "PARTIAL", "INVALID", "ERROR"]

# Per-page additions to the document-level states (`PDF-01`).
PDFPageValidationState = Literal[
    "VALID",
    "PARTIAL",
    "INVALID",
    "ERROR",
    "RENDER_ERROR",
    "TEXT_EXTRACTION_ERROR",
    "IMAGE_EXTRACTION_ERROR",
]

# Descriptive only: it describes what the page natively contains. It never routes.
PDFPageClassification = Literal["TEXT", "IMAGE", "MIXED"]

# Typed failure classification (`PDF-03`, `PDF-11`): never an exception across the
# contract, never a silent substitute.
PDFErrorType = Literal[
    "MISSING_FILE",
    "ENCRYPTED_PDF",
    "CORRUPTED_PDF",
    "UNSUPPORTED_PDF",
    "PAGE_OUT_OF_RANGE",
    "RENDER_ERROR",
    "TEXT_EXTRACTION_ERROR",
    "IMAGE_EXTRACTION_ERROR",
    "WRITE_ERROR",
    "IO_ERROR",
    "INTERNAL_ERROR",
]


@dataclass(frozen=True)
class PDFOptions:
    """Requested capabilities; the processor runs exactly what is requested.

    Attributes:
        extract_pages: Produce a self-contained one-page PDF per page.
        render: Render each page to PNG.
        extract_text: Extract native text and its blocks.
        extract_images: Extract embedded images.
        layout: Preserve layout information in the extracted blocks.
        dpi: Render resolution. Explicit: never a silent default substituted for a
            missing value.
    """

    extract_pages: bool
    render: bool
    extract_text: bool
    extract_images: bool
    layout: bool
    dpi: int


@dataclass(frozen=True)
class PDFContext:
    """Correlation metadata for tracing. Never read to alter behaviour.

    Attributes:
        document_id: Identity of the document this request belongs to.
        workflow_run_id: Identity of the run that issued the request.
    """

    document_id: str
    workflow_run_id: str


@dataclass(frozen=True)
class PDFRequest:
    """Input contract of the PDF processor.

    Attributes:
        pdf_path: PDF to read. Treated as immutable: never written to.
        output_dir: Exclusive root of this processor's artifact namespaces.
        options: Requested capabilities.
        context: Correlation metadata.
    """

    pdf_path: Path
    output_dir: Path
    options: PDFOptions
    context: PDFContext


@dataclass(frozen=True)
class TextBlock:
    """One block of native text and where it sits on the page.

    Attributes:
        block_id: Deterministic identifier within the page.
        text: The block's text.
        bbox: Bounding box on the page, or ``None`` when layout was not requested.
        page_number: Page the block belongs to.
    """

    block_id: str
    text: str
    bbox: tuple[float, float, float, float] | None
    page_number: int


@dataclass(frozen=True)
class EmbeddedImage:
    """One image embedded in a PDF page.

    Attributes:
        image_id: Deterministic identifier within the page.
        path: Path to the extracted image file.
        bbox: Bounding box of the image on the page, or ``None`` when unknown.
        width: Image width in pixels.
        height: Image height in pixels.
        format: Image format as reported by the engine.
        metadata: Additional engine-reported attributes.
    """

    image_id: str
    path: Path
    bbox: tuple[float, float, float, float] | None
    width: int
    height: int
    format: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class PDFPageMetrics:
    """Per-page composition metrics. Measurements, not judgements.

    Attributes:
        characters: Native characters on the page.
        words: Native words on the page.
        text_blocks: Number of native text blocks.
        images: Number of embedded images.
        text_coverage: Fraction of the page covered by text.
        image_coverage: Fraction of the page covered by images.
        largest_image_coverage: Fraction covered by the largest image.
    """

    characters: int
    words: int
    text_blocks: int
    images: int
    text_coverage: float
    image_coverage: float
    largest_image_coverage: float


@dataclass(frozen=True)
class PDFError:
    """A typed failure, reported rather than thrown.

    Attributes:
        type: Failure classification.
        page_number: Page the failure belongs to, or ``None`` for the document.
        message: Human-readable description.
        recoverable: Whether the run can continue without this artifact.
        metadata: Additional diagnostic context.
    """

    type: PDFErrorType
    page_number: int | None
    message: str
    recoverable: bool
    metadata: dict[str, Any]


@dataclass(frozen=True)
class PDFPageValidation:
    """Structural validation of one page's result.

    Attributes:
        status: Validation state.
        errors: Failures found while validating.
        missing_artifacts: Artifacts the validation expected and did not find.
    """

    status: PDFPageValidationState
    errors: list[PDFError]
    missing_artifacts: list[Path]


@dataclass(frozen=True)
class PDFPageMetadata:
    """Provenance of one page's processing.

    Attributes:
        processor: Processor name.
        processor_version: Processor version.
        engine: Named engine; never a silent substitute.
        engine_version: Engine version.
        context: Correlation metadata echoed from the request.
        timing: Wall-clock durations by stage.
    """

    processor: str
    processor_version: str
    engine: str
    engine_version: str
    context: PDFContext
    timing: dict[str, float]


@dataclass
class PDFPageResult:
    """Result of processing exactly one page.

    Attributes:
        page_number: Page index, 1-based.
        page_pdf: Path to the one-page PDF, or ``None`` when not requested.
        page_image: Path to the rendered PNG, or ``None`` when not requested.
        native_text: Path to the native text file, or ``None`` when not requested.
        text_blocks: Native text blocks in reading order.
        embedded_images: Embedded images in reading order.
        metrics: Per-page composition metrics.
        classification: Descriptive composition class. Never a routing decision.
        artifacts: Every file this page published.
        validation: Structural validation of this page.
        metadata: Provenance of this page's processing.
        status: Outcome of this page.
    """

    page_number: int
    page_pdf: Path | None
    page_image: Path | None
    native_text: Path | None
    text_blocks: list[TextBlock]
    embedded_images: list[EmbeddedImage]
    metrics: PDFPageMetrics
    classification: PDFPageClassification
    artifacts: list[Path]
    validation: PDFPageValidation
    metadata: PDFPageMetadata
    status: PDFStatus


@dataclass(frozen=True)
class PDFValidation:
    """Structural validation of the document result.

    Attributes:
        status: Validation state.
        errors: Failures found while validating.
        missing_artifacts: Artifacts expected at document level and not found.
    """

    status: PDFValidationState
    errors: list[PDFError]
    missing_artifacts: list[Path]


@dataclass(frozen=True)
class PDFMetadata:
    """Provenance of the document-level processing.

    Attributes:
        processor: Processor name.
        processor_version: Processor version.
        engine: Named engine.
        engine_version: Engine version.
        page_count: Pages the engine reported for the document.
        context: Correlation metadata echoed from the request.
        timing: Wall-clock durations by stage.
    """

    processor: str
    processor_version: str
    engine: str
    engine_version: str
    page_count: int
    context: PDFContext
    timing: dict[str, float]


@dataclass
class PDFResult:
    """Output contract of the PDF processor, one per document.

    Attributes:
        source_path: The PDF that was read.
        metadata: Document-level provenance.
        pages: One entry per page, in page order.
        metrics: Aggregate metrics over all pages.
        artifacts: Every file this processor published.
        validation: Structural validation of the result.
        status: Outcome of the document run.
        errors: Failures reported during the run.
    """

    source_path: Path
    metadata: PDFMetadata
    pages: list[PDFPageResult]
    metrics: PDFPageMetrics
    artifacts: list[Path]
    validation: PDFValidation
    status: PDFStatus
    errors: list[PDFError] = field(default_factory=list)
