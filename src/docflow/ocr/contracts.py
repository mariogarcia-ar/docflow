"""Contract types of the OCR processor: ``OCRRequest → OCRResult``.

This module is vocabulary only. It performs no I/O, imports no engine and contains no
processing logic; Docling — the only OCR engine — is reached exclusively from
:mod:`docflow.ocr.primitives`.

The names below are engine-independent. Docling's native structures never cross this
boundary: the processor converts them into :class:`OCRDocument` and the rest of the
system works on that.

``context`` is correlation and tracing data. It is never read to alter behaviour, and it
never carries workflow state.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

OCRStatus = Literal["success", "failed"]

# Extraction states. Descriptive: the processor reports, the orchestrator decides.
OCRValidationState = Literal[
    "VALID",
    "EMPTY",
    "LOW_CONTENT",
    "INCOMPLETE",
    "PARSE_ERROR",
    "ERROR",
]

# Typed failure classification, exactly as `subplan-procesador-ocr.md` §3.7 and `OCR-09`
# fix it: every failure carries one of these kinds, never a free-text reason.
OCRErrorType = Literal[
    "INVALID_INPUT",
    "UNSUPPORTED_IMAGE",
    "ENGINE_ERROR",
    "OCR_ERROR",
    "LAYOUT_ERROR",
    "TABLE_EXTRACTION_ERROR",
    "EXPORT_ERROR",
    "IO_ERROR",
    "INTERNAL_ERROR",
]

# Structural role of a block. Deliberately generic: no domain vocabulary.
OCRBlockType = Literal[
    "text",
    "title",
    "paragraph",
    "list",
    "table",
    "caption",
    "figure",
    "other",
]


@dataclass(frozen=True)
class OCROptions:
    """Raw OCR options as requested. Normalized internally into
    :class:`NormalizedOCROptions`, which is what a processing key is computed from.

    Attributes:
        ocr: Run OCR on the input image.
        layout: Extract layout information.
        tables: Detect and extract tables.
        reading_order: Preserve reading order.
        language: Expected language, or ``None`` to leave it to the engine.
        engine_options: Engine-specific passthrough options.
    """

    ocr: bool
    layout: bool
    tables: bool
    reading_order: bool
    language: str | None
    engine_options: dict[str, Any]


@dataclass(frozen=True)
class NormalizedOCROptions:
    """Stable, canonical form of :class:`OCROptions`.

    Options are normalized so that two equivalent requests produce the same
    ``options_hash`` and therefore the same processing key: keys are ordered and values
    are cast to their canonical type.

    Attributes:
        ocr: Run OCR on the input image.
        layout: Extract layout information.
        tables: Detect and extract tables.
        reading_order: Preserve reading order.
        language: Canonical language tag, or ``None``.
        engine_options: Passthrough options with canonical key order.
    """

    ocr: bool
    layout: bool
    tables: bool
    reading_order: bool
    language: str | None
    engine_options: dict[str, Any]


@dataclass(frozen=True)
class OCRContext:
    """Correlation metadata for tracing. Never workflow state.

    Alias note: the subplan writes this type as ``Context``; ``OCRContext`` is the
    canonical name, adopted here to match ``PDFContext`` and ``ImageContext``.

    Attributes:
        document_id: Identity of the document this request belongs to.
        page_number: Logical page the image belongs to, 1-based.
        workflow_run_id: Identity of the run that issued the request.
    """

    document_id: str
    page_number: int
    workflow_run_id: str


@dataclass(frozen=True)
class OCRRequest:
    """Input contract of the OCR processor.

    Attributes:
        image_path: Prepared image, already normalized or ``ocr_ready``.
        output_dir: Exclusive root of the ``ocr/`` artifact namespace.
        options: Raw OCR options.
        context: Correlation metadata.
    """

    image_path: Path
    output_dir: Path
    options: OCROptions
    context: OCRContext


@dataclass(frozen=True)
class OCRError:
    """A typed failure, returned inside the result rather than thrown.

    Attributes:
        type: Failure classification.
        message: Human-readable description.
        recoverable: Whether the run can continue without this artifact.
        metadata: Additional diagnostic context.
    """

    type: OCRErrorType
    message: str
    recoverable: bool
    metadata: dict[str, Any]


@dataclass(frozen=True)
class TableResult:
    """One detected table, in preserved reading order.

    Attributes:
        table_id: Deterministic identifier within the document.
        index: Position of the table in reading order, 1-based.
        markdown: The table rendered as Markdown.
        bbox: Bounding box of the table, or ``None`` when layout was not extracted.
        cells: Cell contents by row, then by column.
    """

    table_id: str
    index: int
    markdown: str
    bbox: tuple[float, float, float, float] | None
    cells: list[list[str]]


@dataclass(frozen=True)
class BlockResult:
    """One block of extracted content.

    Blocks are held in reading order by the owning list, so no separate order field
    exists: position in :attr:`OCRResult.blocks` *is* the order.

    Attributes:
        block_id: Deterministic identifier within the document.
        type: Structural role of the block.
        text: The block's text.
        bbox: Normalized bounding box, or ``None`` when layout was not extracted.
        level: Heading depth for titles, or ``None``.
    """

    block_id: str
    type: OCRBlockType
    text: str
    bbox: tuple[float, float, float, float] | None
    level: int | None


@dataclass(frozen=True)
class LayoutResult:
    """Normalized layout of the page.

    Bounding boxes are normalized into a single coordinate convention so a caller never
    has to know the engine's convention.

    Attributes:
        page_width: Page width in the normalized convention.
        page_height: Page height in the normalized convention.
        region_bboxes: Bounding boxes of every detected region.
    """

    page_width: float
    page_height: float
    region_bboxes: list[tuple[float, float, float, float]]


@dataclass(frozen=True)
class OCRMetrics:
    """Content metrics of an extraction. Measurements, not judgements.

    Attributes:
        characters: Extracted characters.
        words: Extracted words.
        blocks: Number of blocks.
        tables: Number of tables.
        paragraphs: Number of paragraphs.
        text_density: Characters per unit of page area.
        empty: Whether the extraction produced no content.
        structure_detected: Whether any structural element was recognized.
    """

    characters: int
    words: int
    blocks: int
    tables: int
    paragraphs: int
    text_density: float
    empty: bool
    structure_detected: bool


@dataclass(frozen=True)
class ArtifactPaths:
    """Paths of the artifacts the processor published under ``ocr/``.

    Attributes:
        text: Path to ``ocr/text.txt``.
        markdown: Path to ``ocr/document.md``.
        structured_document: Path to ``ocr/document.json``.
        tables_dir: Path to ``ocr/tables/``.
        metadata: Path to ``ocr/metadata.json``.
    """

    text: Path
    markdown: Path
    structured_document: Path
    tables_dir: Path
    metadata: Path


@dataclass(frozen=True)
class OCRValidation:
    """Structural validation of the extraction.

    Attributes:
        status: Validation state.
        errors: Failures found while validating.
        missing_artifacts: Artifacts the validation expected and did not find.
    """

    status: OCRValidationState
    errors: list[OCRError]
    missing_artifacts: list[Path]


@dataclass(frozen=True)
class OCRMetadata:
    """Provenance of the extraction.

    ``engine`` is always ``"docling"`` and ``engine_version`` is always a concrete
    version: the engine is fixed and is never presented as a selectable option.

    Attributes:
        engine: Engine name.
        engine_version: Engine version.
        processor_version: Processor version.
        options: The normalized options that were used.
        input: The image that was read.
        metrics: Content metrics.
        validation: The validation outcome recorded at publish time.
        timing: Wall-clock durations by stage.
        transformations: Every transformation actually applied, in order.
        context: Correlation metadata echoed from the request.
    """

    engine: str
    engine_version: str
    processor_version: str
    options: NormalizedOCROptions
    input: Path
    metrics: OCRMetrics
    validation: OCRValidation
    timing: dict[str, float]
    transformations: list[str]
    context: OCRContext


@dataclass(frozen=True)
class OCRDocument:
    """Engine-independent structured representation of an extraction.

    This is the in-process shape. :attr:`OCRResult.structured_document` is the same
    representation serialized to JSON, which is what ``ocr/document.json`` holds and
    what a downstream consumer reads. Docling's own structures never appear here.

    Attributes:
        text: Plain text in reading order.
        paragraphs: Paragraph texts in reading order.
        titles: Title texts in reading order.
        blocks: Every block, in reading order.
        tables: Every table, in reading order.
        layout: Normalized layout.
        reading_order: Identifiers of blocks and tables, in reading order.
        metadata: Engine-independent metadata.
    """

    text: str
    paragraphs: list[str]
    titles: list[str]
    blocks: list[BlockResult]
    tables: list[TableResult]
    layout: LayoutResult
    reading_order: list[str]
    metadata: dict[str, Any]


@dataclass
class OCRResult:
    """Output contract of the OCR processor, one per extraction.

    Attributes:
        text: Plain text in logical reading order.
        markdown: Structured Markdown.
        structured_document: The serialized :class:`OCRDocument`.
        tables: Detected tables in preserved order.
        blocks: Deterministically ordered blocks.
        layout: Normalized layout.
        reading_order: Ordered block and table identifiers.
        metrics: Content metrics.
        artifacts: Paths to everything this processor published.
        validation: Structural validation of the extraction.
        metadata: Provenance of the extraction.
        status: Outcome of the run.
        error: The typed failure when ``status`` is ``failed``.
    """

    text: str
    markdown: str
    structured_document: dict[str, Any]
    tables: list[TableResult]
    blocks: list[BlockResult]
    layout: LayoutResult
    reading_order: list[str]
    metrics: OCRMetrics
    artifacts: ArtifactPaths
    validation: OCRValidation
    metadata: OCRMetadata
    status: OCRStatus
    error: OCRError | None
