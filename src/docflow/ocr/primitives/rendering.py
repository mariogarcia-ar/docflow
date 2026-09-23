"""Markdown and table rendering (``OCR-02`` surface).

Markdown is assembled from the extracted blocks rather than taken from the engine's own renderer,
because that renderer is free to change between Docling versions while ``document.md`` is part of
this processor's contract. The same reasoning applies to tables: one normalized representation
feeds the cells, the Markdown and the JSON, so the three cannot disagree about the same table.

Every body raises :class:`NotImplementedError`. ``OCR-06`` implements the Markdown half and
``OCR-07`` the tables; ``count_tables`` belongs to ``OCR-08`` because it feeds the metrics.
"""

from __future__ import annotations

from docflow.ocr.contracts import BlockResult, TableResult


def normalize_markdown(markdown: str) -> str:
    """Put Markdown into its canonical form.

    Args:
        markdown: The Markdown to canonicalize.

    Returns:
        The canonical form.

    Raises:
        NotImplementedError: ``OCR-06`` implements this.

    # TODO: [MVP] implement (OCR-06).
    """
    raise NotImplementedError("normalize_markdown is implemented by OCR-06")


def merge_ocr_blocks(blocks: list[BlockResult]) -> str:
    """Render ordered blocks as Markdown.

    Args:
        blocks: The blocks, in reading order.

    Returns:
        The Markdown rendering.

    Raises:
        NotImplementedError: ``OCR-06`` implements this.

    # TODO: [MVP] implement (OCR-06).
    """
    raise NotImplementedError("merge_ocr_blocks is implemented by OCR-06")


def count_tables(tables: list[TableResult]) -> int:
    """Count the tables.

    Args:
        tables: The tables to count.

    Returns:
        The number of tables.

    Raises:
        NotImplementedError: ``OCR-08`` implements this.

    # TODO: [MVP] implement (OCR-08).
    """
    raise NotImplementedError("count_tables is implemented by OCR-08")


def normalize_table(table: TableResult) -> TableResult:
    """Canonicalize a table's cells and identifiers.

    Args:
        table: The table as the engine reported it.

    Returns:
        The canonical table.

    Raises:
        NotImplementedError: ``OCR-07`` implements this.

    # TODO: [MVP] implement (OCR-07).
    """
    raise NotImplementedError("normalize_table is implemented by OCR-07")


def table_to_markdown(table: TableResult) -> str:
    """Render a table as Markdown.

    Args:
        table: The table to render.

    Returns:
        The Markdown rendering.

    Raises:
        NotImplementedError: ``OCR-07`` implements this.

    # TODO: [MVP] implement (OCR-07).
    """
    raise NotImplementedError("table_to_markdown is implemented by OCR-07")


def table_to_json(table: TableResult) -> dict[str, object]:
    """Render a table as a JSON object.

    Args:
        table: The table to render.

    Returns:
        The JSON representation, with canonical key order.

    Raises:
        NotImplementedError: ``OCR-07`` implements this.

    # TODO: [MVP] implement (OCR-07).
    """
    raise NotImplementedError("table_to_json is implemented by OCR-07")


__all__ = [
    "count_tables",
    "merge_ocr_blocks",
    "normalize_markdown",
    "normalize_table",
    "table_to_json",
    "table_to_markdown",
]
