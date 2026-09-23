"""Markdown and table rendering (``OCR-02`` surface).

Markdown is assembled from the extracted blocks rather than taken from the engine's own renderer,
because that renderer is free to change between Docling versions while ``document.md`` is part of
this processor's contract. The same reasoning applies to tables: one normalized representation
feeds the cells, the Markdown and the JSON, so the three cannot disagree about the same table.

``OCR-06`` implements ``normalize_markdown`` and ``merge_ocr_blocks``, the two names §3.4's
*Markdown* group lists that belong to the output builders. ``preserve_reading_order`` is in that
group too but lives in :mod:`docflow.ocr.primitives.layout`, because the order it computes is
defined on normalized geometry and it calls ``normalize_bbox`` for every item - placing it here
would make the module that owns the coordinate frame depend on this one. The remaining names are
the tables': ``normalize_table`` and ``table_to_markdown``/``table_to_json`` are ``OCR-07``'s, and
``count_tables`` is ``OCR-08``'s because it feeds the metrics.
"""

from __future__ import annotations

from docflow.ocr.contracts import BlockResult, TableResult
from docflow.ocr.primitives.text import normalize_ocr_text

_HEADING_PREFIX = "#"
_MAX_HEADING_DEPTH = 6
"""Markdown's own limit: a seventh level does not exist, so a deeper block is clamped rather than
emitting ``#######``, which every renderer reads as a paragraph with a stray character."""


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
        The number of tables.

    Raises:
        NotImplementedError: ``OCR-08`` implements this, because it feeds the metrics.
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
