"""Normalizing the engine's geometry and ordering into one convention (``OCR-02`` surface).

A caller must never have to know which coordinate convention the engine used. Everything here maps
the engine's geometry into a single normalized frame, and the determinism posture depends on it:
two runs over the same image must order blocks the same way, which they cannot do if the tie-break
reads an engine-specific box.

Every body raises :class:`NotImplementedError`. ``OCR-05`` implements all of these.
"""

from __future__ import annotations

from docflow.ocr.contracts import BlockResult, LayoutResult, TableResult


def normalize_bbox(
    bbox: object, page_width: float, page_height: float
) -> tuple[float, float, float, float]:
    """Map one bounding box into the normalized convention.

    Args:
        bbox: The engine's box.
        page_width: Page width in the engine's convention.
        page_height: Page height in the engine's convention.

    Returns:
        The box in the normalized convention.

    Raises:
        NotImplementedError: ``OCR-05`` implements this.

    # TODO: [MVP] implement (OCR-05).
    """
    raise NotImplementedError("normalize_bbox is implemented by OCR-05")


def normalize_layout(layout: LayoutResult) -> LayoutResult:
    """Normalize a whole layout.

    Args:
        layout: The layout as the engine reported it.

    Returns:
        The layout in the normalized convention.

    Raises:
        NotImplementedError: ``OCR-05`` implements this.

    # TODO: [MVP] implement (OCR-05).
    """
    raise NotImplementedError("normalize_layout is implemented by OCR-05")


def preserve_reading_order(
    blocks: list[BlockResult], tables: list[TableResult]
) -> list[str]:
    """Order blocks and tables into a stable reading order.

    Args:
        blocks: The blocks to order.
        tables: The tables to order.

    Returns:
        The identifiers, in reading order.

    Raises:
        NotImplementedError: ``OCR-05`` implements this.

    # TODO: [MVP] implement (OCR-05).
    """
    raise NotImplementedError("preserve_reading_order is implemented by OCR-05")


def count_blocks(blocks: list[BlockResult]) -> int:
    """Count the blocks.

    Args:
        blocks: The blocks to count.

    Returns:
        The number of blocks.

    Raises:
        NotImplementedError: ``OCR-05`` implements this.

    # TODO: [MVP] implement (OCR-05).
    """
    raise NotImplementedError("count_blocks is implemented by OCR-05")


def calculate_ocr_text_density(
    characters: int, page_width: float, page_height: float
) -> float:
    """Characters per unit of page area.

    Args:
        characters: Extracted characters.
        page_width: Page width.
        page_height: Page height.

    Returns:
        The density, or ``0.0`` for a page with no area.

    Raises:
        NotImplementedError: ``OCR-05`` implements this.

    # TODO: [MVP] implement (OCR-05).
    """
    raise NotImplementedError("calculate_ocr_text_density is implemented by OCR-05")


__all__ = [
    "calculate_ocr_text_density",
    "count_blocks",
    "normalize_bbox",
    "normalize_layout",
    "preserve_reading_order",
]
