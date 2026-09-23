"""Running Docling over one image, and reading its output into this processor's vocabulary.

Two modules rather than one, because the two halves have different reasons to change. *Running*
the engine is about Docling's execution API; *extracting* is about Docling's result structure,
and that is the part §8's risk table names — "Docling schema changes between versions" — with
this layer as the mitigation. Keeping them apart means a schema change touches the extraction
functions and leaves the execution path alone.

Every body raises :class:`NotImplementedError`. ``OCR-04`` implements all of these.
"""

from __future__ import annotations

from pathlib import Path

from docflow.ocr.contracts import BlockResult, LayoutResult, TableResult


def convert_image_with_docling(image_path: Path, pipeline: object) -> object:
    """Run the engine over one prepared image.

    Args:
        image_path: The prepared image, already normalized or ``ocr_ready``.
        pipeline: The configured pipeline.

    Returns:
        The engine's conversion result, still in Docling's own structure.

    Raises:
        NotImplementedError: ``OCR-04`` implements this.

    # TODO: [MVP] implement (OCR-04).
    """
    raise NotImplementedError("convert_image_with_docling is implemented by OCR-04")


def extract_docling_text(result: object) -> str:
    """Read the plain text the engine produced.

    Args:
        result: The engine's conversion result.

    Returns:
        The text in the engine's reading order.

    Raises:
        NotImplementedError: ``OCR-04`` implements this.

    # TODO: [MVP] implement (OCR-04).
    """
    raise NotImplementedError("extract_docling_text is implemented by OCR-04")


def extract_docling_markdown(result: object) -> str:
    """Read the Markdown the engine produced.

    Args:
        result: The engine's conversion result.

    Returns:
        The Markdown as the engine rendered it.

    Raises:
        NotImplementedError: ``OCR-04`` implements this.

    # TODO: [MVP] implement (OCR-04).
    """
    raise NotImplementedError("extract_docling_markdown is implemented by OCR-04")


def extract_docling_blocks(result: object) -> list[BlockResult]:
    """Read the content blocks.

    Args:
        result: The engine's conversion result.

    Returns:
        The blocks, in the engine's order.

    Raises:
        NotImplementedError: ``OCR-04`` implements this.

    # TODO: [MVP] implement (OCR-04).
    """
    raise NotImplementedError("extract_docling_blocks is implemented by OCR-04")


def extract_docling_tables(result: object) -> list[TableResult]:
    """Read the detected tables.

    Args:
        result: The engine's conversion result.

    Returns:
        The tables, in the engine's order.

    Raises:
        NotImplementedError: ``OCR-04`` implements this.

    # TODO: [MVP] implement (OCR-04).
    """
    raise NotImplementedError("extract_docling_tables is implemented by OCR-04")


def extract_docling_layout(result: object) -> LayoutResult:
    """Read the layout information.

    Args:
        result: The engine's conversion result.

    Returns:
        The layout in the engine's coordinate convention, not yet normalized.

    Raises:
        NotImplementedError: ``OCR-04`` implements this.

    # TODO: [MVP] implement (OCR-04).
    """
    raise NotImplementedError("extract_docling_layout is implemented by OCR-04")


def extract_docling_metadata(result: object) -> dict[str, object]:
    """Read the engine's own metadata.

    Args:
        result: The engine's conversion result.

    Returns:
        Engine-reported metadata, kept as the engine wrote it.

    Raises:
        NotImplementedError: ``OCR-04`` implements this.

    # TODO: [MVP] implement (OCR-04).
    """
    raise NotImplementedError("extract_docling_metadata is implemented by OCR-04")


__all__ = [
    "convert_image_with_docling",
    "extract_docling_blocks",
    "extract_docling_layout",
    "extract_docling_markdown",
    "extract_docling_metadata",
    "extract_docling_tables",
    "extract_docling_text",
]
