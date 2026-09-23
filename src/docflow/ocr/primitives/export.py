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
from docflow.ocr.primitives.rendering import (
    merge_ocr_blocks,
    normalize_markdown,
    process_tables,
    table_to_markdown,
)
from docflow.ocr.primitives.text import normalize_ocr_text

#: The schema version of ``ocr/document.json``.
#:
#: This processor's own version, not Docling's, and not the package's. The plan requires the
#: structured document to be "stable and versioned" so a consumer can read an artifact produced by
#: an earlier build; tying that number to the engine's would make a Docling upgrade look like a
#: schema change to every downstream reader.
DOCUMENT_SCHEMA_VERSION: str = "1.0.0"


def _canonical_text(value: str) -> str:
    """Return one text value in this processor's canonical form.

    Every text-bearing field of every artifact goes through here, and that is deliberate: a builder
    that canonicalized ``text.txt`` but left ``document.json``'s ``text`` as the engine wrote it
    would make two artifacts of one extraction disagree, and a consumer comparing them would see a
    difference the page does not have. A first draft did exactly that, and the test that compared
    the two artifacts is what caught it.

    Args:
        value: The raw text.

    Returns:
        The canonical text.
    """
    return normalize_ocr_text(value)


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
        "text": _canonical_text(block.text),
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
        "text": _canonical_text(document.text),
        "paragraphs": [_canonical_text(value) for value in document.paragraphs],
        "titles": [_canonical_text(value) for value in document.titles],
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

    The text is canonicalized with :func:`docflow.ocr.primitives.text.normalize_ocr_text`, so two
    runs that differ only in the whitespace the engine emitted produce the same file. That is the
    claim the determinism posture makes, and it is what makes the trailing newline below an
    addition rather than a repair.

    Args:
        document: The document to export.

    Returns:
        The canonical text, with a single trailing newline so the file is a well-formed
        line-oriented text file rather than a blob without a terminator, or ``""`` when the
        extraction produced nothing. An empty file for an empty extraction, not a file holding a
        bare newline: the second would be content, and ``OCR-09`` reads this artifact to decide
        between ``EMPTY`` and ``VALID``.
    """
    text = _canonical_text(document.text)
    return f"{text}\n" if text else ""


def export_docling_markdown(document: OCRDocument) -> str:
    """Return the Markdown ``ocr/document.md`` will hold.

    Built from the document's own blocks and tables rather than from the engine's Markdown
    export, because the artifact has to be reproducible from the artifact's *own* inputs: the
    engine's renderer is free to change between versions, and a consumer comparing two runs would
    then see a difference produced by the renderer rather than by the page.

    The walk over ``reading_order`` is what keeps a table between the two paragraphs it sits
    between. Consecutive blocks are handed to
    :func:`docflow.ocr.primitives.rendering.merge_ocr_blocks` as a run and the table's own Markdown
    is spliced in as the run boundary is crossed — so the block rendering has one owner
    (``OCR-06``'s module) and this function owns only the interleaving.

    Args:
        document: The document to export.

    Returns:
        The canonicalized Markdown, newline-terminated because the file is one.
    """
    blocks = {block.block_id: block for block in document.blocks}
    tables = {table.table_id: table for table in document.tables}
    fragments: list[str] = []
    run: list[BlockResult] = []

    def flush() -> None:
        """Render the accumulated block run, if any."""
        if run:
            merged = merge_ocr_blocks(run)
            if merged:
                fragments.append(merged)
            run.clear()

    for identifier in document.reading_order:
        block = blocks.get(identifier)
        if block is not None:
            run.append(block)
            continue
        table = tables.get(identifier)
        if table is not None:
            flush()
            rendered = table_to_markdown(table).rstrip("\n")
            if rendered:
                fragments.append(rendered)

    flush()
    markdown = normalize_markdown("\n\n".join(fragments))
    return f"{markdown}\n" if markdown else ""


def export_docling_tables(document: OCRDocument) -> list[tuple[str, str]]:
    """Return each table's file name and Markdown, for ``ocr/tables/``.

    Delegates to :func:`docflow.ocr.primitives.rendering.process_tables` rather than rendering the
    grids itself. There was briefly a private renderer here as well, and two renderers for one grid
    is two answers to the same question: the copy that is not edited keeps producing a file the
    other one would not. The table module owns tables; this function owns only the document-to-table
    handoff.

    Names rather than paths: the directory is ``OCR-10``'s to choose, and a table exporter that
    invented a path would be the second place that knows the namespace layout.

    Args:
        document: The document to export.

    Returns:
        ``(file name, markdown)`` pairs, in the document's table order.
    """
    return process_tables(document.tables)


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
