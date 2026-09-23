"""Exporting the engine's output in this processor's own vocabulary (``OCR-04``).

``subplan-procesador-ocr.md`` §3.4 groups four exporters separately from the extractors, and the
distinction is real rather than cosmetic: an **extractor** turns a Docling item into a contract
record, while an **exporter** turns the whole document into a *serializable* artifact — the text,
the Markdown, the JSON that ``ocr/text.txt``, ``ocr/document.md`` and ``ocr/document.json`` will
hold.

Keeping them apart matters because the exporters are the boundary the ``DoclingDocument`` must not
cross. ``export_to_dict`` would be the shortest path to ``document.json`` and it would write
Docling's own schema into an artifact this project versions itself; ``OCR-05``'s determinism
posture says ``document.json`` is "a stable, versioned schema", which means *this* processor's.

The four functions produce values. Writing them to disk is ``OCR-10``'s atomic publication, and
doing it here would put a filesystem dependency in a module whose whole job is serialization.
"""

from __future__ import annotations

import json
from typing import Any

from docflow.ocr.contracts import BlockResult, LayoutResult, OCRDocument, TableResult

#: The schema version of ``ocr/document.json``.
#:
#: This processor's own version, not Docling's, and not the package's. The plan requires the
#: structured document to be "stable and versioned" so a consumer can read an artifact produced by
#: an earlier build; tying that number to the engine's would make a Docling upgrade look like a
#: schema change to every downstream reader.
DOCUMENT_SCHEMA_VERSION: str = "1.0.0"


def _block_payload(block: BlockResult) -> dict[str, Any]:
    """Expand a block into a JSON object.

    Field by field rather than ``dataclasses.asdict``, for the reason the image processor's
    metadata payload records: the file is a schema other tools read, so a record gaining a field
    should be a visible edit here rather than a silent addition to the output.

    Args:
        block: The block to expand.

    Returns:
        The block as a JSON object.
    """
    return {
        "block_id": block.block_id,
        "type": block.type,
        "text": block.text,
        "bbox": list(block.bbox) if block.bbox is not None else None,
        "level": block.level,
    }


def _table_payload(table: TableResult) -> dict[str, Any]:
    """Expand a table into a JSON object.

    Args:
        table: The table to expand.

    Returns:
        The table as a JSON object. The cells are included and the Markdown is not: the Markdown
        is a *rendering* of the cells, and holding both in one artifact invites a reader to use
        the copy that was not regenerated after an edit.
    """
    return {
        "table_id": table.table_id,
        "index": table.index,
        "bbox": list(table.bbox) if table.bbox is not None else None,
        "cells": [list(row) for row in table.cells],
    }


def _layout_payload(layout: LayoutResult) -> dict[str, Any]:
    """Expand a layout into a JSON object.

    Args:
        layout: The layout to expand.

    Returns:
        The layout as a JSON object.
    """
    return {
        "page_width": layout.page_width,
        "page_height": layout.page_height,
        "region_bboxes": [list(box) for box in layout.region_bboxes],
    }


def export_docling_json(document: OCRDocument) -> dict[str, Any]:
    """Serialize the engine-independent document into the ``document.json`` payload.

    The engine's own ``export_to_dict`` is deliberately not used. It would be fewer lines and it
    would publish Docling's schema as this processor's artifact, so a Docling upgrade could change
    the meaning of a file a consumer already reads.

    Args:
        document: The document to serialize.

    Returns:
        The payload, ready to be written by ``OCR-10``.
    """
    return {
        "schema_version": DOCUMENT_SCHEMA_VERSION,
        "text": document.text,
        "paragraphs": list(document.paragraphs),
        "titles": list(document.titles),
        "blocks": [_block_payload(block) for block in document.blocks],
        "tables": [_table_payload(table) for table in document.tables],
        "layout": _layout_payload(document.layout),
        "reading_order": list(document.reading_order),
        "metadata": dict(document.metadata),
    }


def export_docling_text(document: OCRDocument) -> str:
    """Return the plain text ``ocr/text.txt`` will hold.

    A function rather than a passthrough of ``document.text`` so the artifact has one producer. A
    caller that read the field directly would be a second one, and the two could drift the moment
    either grew a normalization step.

    Args:
        document: The document to export.

    Returns:
        The text, with a single trailing newline so the file is a well-formed line-oriented text
        file rather than a blob without a terminator.
    """
    text = document.text.rstrip("\n")
    return f"{text}\n" if text else ""


def export_docling_markdown(document: OCRDocument) -> str:
    """Return the Markdown ``ocr/document.md`` will hold.

    Built from the document's own blocks and tables rather than from the engine's Markdown
    export, because the artifact has to be reproducible from the artifact's *own* inputs: the
    engine's renderer is free to change between versions, and a consumer comparing two runs would
    then see a difference produced by the renderer rather than by the page.

    Args:
        document: The document to export.

    Returns:
        The Markdown rendering.

    # TODO: [MVP] `OCR-06` owns Markdown canonicalization and block merging; this renders the
    # structure faithfully and leaves the canonical form to it.
    """
    blocks = {block.block_id: block for block in document.blocks}
    tables = {table.table_id: table for table in document.tables}
    lines: list[str] = []

    for identifier in document.reading_order:
        block = blocks.get(identifier)
        if block is not None:
            lines.append(_render_block(block))
            continue
        table = tables.get(identifier)
        if table is not None:
            lines.append(_render_table(table))

    return "\n\n".join(part for part in lines if part).rstrip("\n") + "\n"


def _render_block(block: BlockResult) -> str:
    """Render one block as Markdown.

    Args:
        block: The block to render.

    Returns:
        The Markdown fragment, or ``""`` for a block with no text. An empty string rather than a
        placeholder: the join above drops it, so a block with nothing to say contributes nothing.
    """
    text = block.text.strip()
    if not text:
        return ""
    if block.type == "title":
        depth = min(max(block.level or 1, 1), 6)
        return f"{'#' * depth} {text}"
    if block.type == "list":
        return f"- {text}"
    return text


def _render_table(table: TableResult) -> str:
    """Render one table as a Markdown pipe table.

    Args:
        table: The table to render.

    Returns:
        The Markdown table, or ``""`` for a table with no rows.
    """
    if not table.cells:
        return ""
    width = max(len(row) for row in table.cells)
    rows = [
        "| " + " | ".join(list(row) + [""] * (width - len(row))) + " |"
        for row in table.cells
    ]
    header, *body = rows
    divider = "| " + " | ".join("---" for _ in range(width)) + " |"
    return "\n".join([header, divider, *body])


def export_docling_tables(document: OCRDocument) -> list[tuple[str, str]]:
    """Return each table's file name and Markdown, for ``ocr/tables/``.

    Names rather than paths: the directory is ``OCR-10``'s to choose, and a table exporter that
    invented a path would be the second place that knows the namespace layout.

    Args:
        document: The document to export.

    Returns:
        ``(file name, markdown)`` pairs, in the document's table order.
    """
    return [
        (f"{table.table_id}.md", _render_table(table) + "\n")
        for table in document.tables
    ]


def serialize_document_json(payload: dict[str, Any]) -> str:
    """Render a ``document.json`` payload as text.

    Keys are sorted and the indent is fixed, so two runs over the same content produce
    byte-identical files. The determinism posture depends on it: a diff between two artifacts from
    the same page must show a real difference or nothing at all.

    Args:
        payload: The payload from :func:`export_docling_json`.

    Returns:
        The serialized text, newline-terminated.
    """
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


__all__ = [
    "DOCUMENT_SCHEMA_VERSION",
    "export_docling_json",
    "export_docling_markdown",
    "export_docling_tables",
    "export_docling_text",
    "serialize_document_json",
]
