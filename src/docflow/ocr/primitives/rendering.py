"""Markdown and table rendering (``OCR-02`` surface).

Markdown is assembled from the extracted blocks rather than taken from the engine's own renderer,
because that renderer is free to change between Docling versions while ``document.md`` is part of
this processor's contract. The same reasoning applies to tables: one normalized representation
feeds the cells, the Markdown and the JSON, so the three cannot disagree about the same table.

``OCR-06`` implements ``normalize_markdown`` and ``merge_ocr_blocks``, the two names §3.4's
*Markdown* group lists that belong to the output builders. ``preserve_reading_order`` is in that
group too but lives in :mod:`docflow.ocr.primitives.layout`, because the order it computes is
defined on normalized geometry and it calls ``normalize_bbox`` for every item - placing it here
would make the module that owns the coordinate frame depend on this one. ``OCR-07`` implements the
*Tables* group - ``normalize_table``, ``table_to_markdown``, ``table_to_json`` and ``count_tables``
- plus ``process_tables``, which its own scope names and §3.4 does not.
"""

from __future__ import annotations

import re
from dataclasses import replace

from docflow.ocr.contracts import BlockResult, TableResult
from docflow.ocr.primitives.text import normalize_ocr_text

_HEADING_PREFIX = "#"
_MAX_HEADING_DEPTH = 6
"""Markdown's own limit: a seventh level does not exist, so a deeper block is clamped rather than
emitting ``#######``, which every renderer reads as a paragraph with a stray character."""

_CELL_LINE_BREAK = re.compile(r"\s*\n\s*")
"""An internal line break in a cell, and the whitespace around it.

Collapsed to a single space rather than kept: Markdown has no way to break a line inside a table
cell, so a cell holding one splits its row across two lines and silently corrupts the grid.
"""


def normalize_markdown(markdown: str) -> str:
    """Put Markdown into its canonical form.

    This processor's Markdown canonical form **is** the text canonical form, so this delegates
    rather than holding a second whitespace sweep of its own. A first draft did hold one - a
    trailing-whitespace regex and a blank-line collapse beside :func:`normalize_ocr_text`'s - and
    both were unreachable, because ``clean_ocr_text`` already strips each line's trailing padding
    and already collapses blank runs. Dead guards are worse than absent ones: they read as
    protection while a mutation that removes them survives. One owner, one canonical form.

    What the two names buy is *locality of meaning*, not two behaviours — ``document.md`` is
    canonicalized where Markdown is understood, so a future Markdown-specific rule has an obvious
    home. The claim is the one :func:`normalize_ocr_text` makes, one artifact up: two runs over the
    same page produce a byte-identical ``document.md``, so a difference between two artifacts means
    a difference in the extraction rather than in how a renderer spaced its blocks.

    **Markdown indentation is not touched.** Four leading spaces make a code block, so stripping
    them would change what the document says — a transformation, not a canonicalization.

    Args:
        markdown: The Markdown to canonicalize.

    Returns:
        The canonical form, with no leading or trailing newline.
    """
    return normalize_ocr_text(markdown)


def merge_ocr_blocks(blocks: list[BlockResult]) -> str:
    """Render ordered blocks as Markdown.

    Blocks are taken in the order given and not re-sorted. Reading order is
    :func:`docflow.ocr.primitives.layout.preserve_reading_order`'s result and the caller already
    has it; a second sort here would be a second definition of the order, and the two would
    disagree the moment either changed.

    A block with no text contributes nothing rather than an empty line or a placeholder. The text
    of a heading is rendered as a heading because the block's *type* says it is one - deriving the
    level from the text's leading hashes would be reading the rendering back to decide the
    rendering.

    Args:
        blocks: The blocks, in reading order.

    Returns:
        The Markdown rendering, with no leading or trailing newline, or ``""`` when no block has
        text.
    """
    rendered = [fragment for fragment in map(_render_block, blocks) if fragment]
    return normalize_markdown("\n\n".join(rendered))


def _render_block(block: BlockResult) -> str:
    """Render one block as Markdown.

    Args:
        block: The block to render.

    Returns:
        The Markdown fragment, or ``""`` for a block with no text. An empty string rather than a
        placeholder so :func:`merge_ocr_blocks` can drop it: a block with nothing to say
        contributes nothing.
    """
    text = block.text.strip()
    if not text:
        return ""
    if block.type == "title":
        depth = min(
            max(block.level if block.level is not None else 1, 1), _MAX_HEADING_DEPTH
        )
        return f"{_HEADING_PREFIX * depth} {text}"
    if block.type == "list":
        return f"- {text}"
    return text


def count_tables(tables: list[TableResult]) -> int:
    """Count the tables.

    Args:
        tables: The tables to count.

    Returns:
        The number of tables. ``0`` is the truthful answer for an image with no table, which is
        data rather than a failure — ``OCR-09`` reads the figure, it does not treat it as an error.
    """
    return len(tables)


def normalize_table(table: TableResult) -> TableResult:
    """Canonicalize a table's cells and reconcile the Markdown it carries.

    Two jobs, and the second is the one that matters:

    * **Every cell is canonicalized** with :func:`docflow.ocr.primitives.text.normalize_ocr_text`,
      so the same text in a cell and in a block compare equal. This is the defence the JSON
      artifact needs: ``document.json``'s ``cells`` is a list of lists that never passes through
      the document-wide canonicalization, so a control character the engine left in a cell would
      reach the structured artifact raw. Measured rather than assumed — a ``\\x00`` in a cell
      survived into ``document.json`` before this step existed.
    * **The stored Markdown is re-rendered from the cells, not trusted.** ``TableResult.markdown``
      is the *engine's* rendering, captured by ``OCR-04`` and never read by any artifact. Since the
      cells are the canonical content and the Markdown is a rendering of them, keeping the engine's
      copy would put two representations of one table in the record and let them disagree. This
      function is what makes the record self-consistent.

    A cell's internal newline is replaced by a **space**, not kept. Markdown has no way to put a
    line break inside a table cell, so a cell like ``"a\\rb\\n"`` rendered verbatim splits its row
    across two lines and silently corrupts the grid — measured: the row became ``| a`` / ``b | c
    |``. A space is the one substitution that cannot change the row count.

    Args:
        table: The table as the engine reported it.

    Returns:
        The canonical table, with its Markdown re-rendered from its canonical cells.
    """
    cells = [[_canonical_cell(cell) for cell in row] for row in table.cells]
    canonical = replace(table, cells=cells)
    return replace(canonical, markdown=_render_table_markdown(canonical))


def _canonical_cell(cell: str) -> str:
    """Return one cell value in its canonical, single-line form.

    Args:
        cell: The raw cell text.

    Returns:
        The canonical text, with any internal line break collapsed to a space.
    """
    canonical = normalize_ocr_text(cell)
    return _CELL_LINE_BREAK.sub(" ", canonical).strip()


def _render_table_markdown(table: TableResult) -> str:
    """Render a table's cells as a Markdown pipe table.

    Rows are padded to the widest before rendering, because a ragged grid produces a table whose
    column count changes between rows and every Markdown renderer disagrees about what that means.

    Args:
        table: The table to render.

    Returns:
        The Markdown table, or ``""`` for a table with no rows.
    """
    if not table.cells:
        return ""
    width = max(len(row) for row in table.cells)
    rows = [
        "| " + " | ".join([*row, *([""] * (width - len(row)))]) + " |"
        for row in table.cells
    ]
    header, *body = rows
    divider = "| " + " | ".join("---" for _ in range(width)) + " |"
    return "\n".join([header, divider, *body])


def table_to_markdown(table: TableResult) -> str:
    """Render a table as Markdown.

    Normalizes first, so a caller handed a raw engine record gets the same grid
    :func:`normalize_table` would produce rather than a rendering of unrepaired cells.

    Args:
        table: The table to render.

    Returns:
        The Markdown table, newline-terminated, or ``""`` for a table with no rows. An empty table
        is data — :func:`process_tables` emits no artifact for it rather than an empty grid.
    """
    rendered = _render_table_markdown(normalize_table(table))
    return f"{rendered}\n" if rendered else ""


def table_to_json(table: TableResult) -> dict[str, object]:
    """Render a table as a JSON object.

    Every field is named explicitly rather than expanded with ``dataclasses.asdict``, for the reason
    the block payload records: this object is a schema other tools read, so a record gaining a field
    should be a visible edit here rather than a silent addition to the output.

    Args:
        table: The table to render.

    Returns:
        The JSON representation, with canonical key order.
    """
    canonical = normalize_table(table)
    return {
        "table_id": canonical.table_id,
        "index": canonical.index,
        "bbox": list(canonical.bbox) if canonical.bbox is not None else None,
        "cells": [list(row) for row in canonical.cells],
    }


def process_tables(
    tables: list[TableResult],
) -> list[tuple[str, str]]:
    """Prepare each table for ``ocr/tables/``, in the order given.

    Returns ``(file name, contents)`` pairs rather than writing them. Persistence is ``OCR-10``'s
    atomic publication, and a function that wrote here would put a filesystem dependency in a module
    whose whole job is rendering.

    The names come from each table's own identifier, which ``OCR-04`` minted zero-padded
    (``table_001``). That is what makes the order on disk sort the way the order in the document
    reads: ``table_010`` would sort before ``table_002`` without the padding.

    **The list is not re-ordered.** Reading order is
    :func:`docflow.ocr.primitives.layout.preserve_reading_order`'s result and the caller already has
    it; sorting here would be a second definition of the order. An empty list is data rather than a
    failure, and produces no pairs — ``OCR-10`` then writes no ``tables/`` directory, which is the
    documented behaviour for an image with no table.

    ``# TODO: [MVP]`` the deferred ``tables/table_NNN.json`` export (§9 decision 2). It is *not*
    emitted by calling :func:`table_to_json`: that function has no caller in this phase, and
    writing a file nobody reads would be worse than leaving the function unexercised.

    Args:
        tables: The tables, in reading order.

    Returns:
        ``(file name, markdown)`` pairs, in the order given.
    """
    return [
        (f"{normalized.table_id}.md", table_to_markdown(normalized))
        for normalized in map(normalize_table, tables)
        if normalized.cells
    ]


__all__ = [
    "count_tables",
    "merge_ocr_blocks",
    "normalize_markdown",
    "normalize_table",
    "process_tables",
    "table_to_json",
    "table_to_markdown",
]
