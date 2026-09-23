"""Reading Docling's output into this processor's own vocabulary (``OCR-04``).

``subplan-procesador-ocr.md`` puts one requirement on this module above all others: **Docling's
native structures must not leak past ``ocr/primitives/``**. That rules out the easy version of
every function here. It would have been shorter to hand back Docling's ``TextItem`` and let
``OCR-05`` read ``item.label``, and it would have put the engine's vocabulary into the contract —
so every mapping below goes one way, into the types the contract declares.

Three mappings are worth stating, because each one is a decision rather than a mechanical copy:

* **Labels.** Docling has thirty item labels. The contract has eight block types. The mapping is a
  table rather than a chain of conditions, so an unmapped label is visible and lands in ``other``
  rather than being silently dropped or mislabelled.
* **Identifiers.** A block is named ``block_NNN`` in the engine's own iteration order. Docling's
  ``self_ref`` (``#/texts/0``) would be a deterministic identifier too, and it would be Docling's
  spelling crossing the boundary. *Making* the order reading order rather than engine order is
  ``OCR-05``'s work; this module records the order it was handed.
* **Geometry.** Bounding boxes are passed through as the engine reports them, including their
  coordinate origin. Normalizing them into one convention is ``OCR-05``'s ``normalize_bbox`` and
  ``normalize_layout``, and doing it here would make two modules responsible for one guarantee.

The ``OCRDocument`` builder is here as well, because it is the same act: assembling this
processor's types out of the engine's.
"""

from __future__ import annotations

from typing import Any

from docflow.ocr.contracts import (
    BlockResult,
    LayoutResult,
    OCRBlockType,
    OCRDocument,
    TableResult,
)
from docflow.ocr.primitives.engine import OCREngineExecutionError

#: Docling's item label to this processor's block type.
#:
#: A table rather than a chain of conditions so an unmapped label is *visible*: anything absent
#: lands in ``other``, which says "the engine produced something this processor has no vocabulary
#: for" instead of guessing a category. The values were read off the installed engine rather than
#: recalled — Docling 2.126.0 defines thirty labels, and only these nine have an unambiguous
#: counterpart in the contract's eight block types.
DOCLING_LABEL_TO_BLOCK_TYPE: dict[str, OCRBlockType] = {
    "section_header": "title",
    "title": "title",
    "text": "text",
    "paragraph": "paragraph",
    "list_item": "list",
    "table": "table",
    "caption": "caption",
    "picture": "figure",
    "chart": "figure",
}

TEXT_LABELS: tuple[str, ...] = ("text", "paragraph")
"""Labels whose items count as paragraph text, for the document's ``paragraphs`` list."""

TABLE_ID_PADDING: int = 3
"""Digits in a minted table identifier, so ``table_001`` sorts before ``table_010``."""

BLOCK_ID_PADDING: int = 3
"""Digits in a minted block identifier."""


def _label_value(item: Any) -> str:
    """Return an item's label as a plain string.

    Docling's label is an enum member whose ``str()`` is not its value, so this unwraps it once
    rather than at each call site.

    Args:
        item: A Docling document item.

    Returns:
        The label's string value, or ``""`` for an item that has none.
    """
    label = getattr(item, "label", None)
    if label is None:
        return ""
    return str(getattr(label, "value", label))


def _bbox_of(item: Any) -> tuple[float, float, float, float] | None:
    """Return an item's bounding box as a plain tuple, or ``None``.

    The values and their coordinate origin are passed through untouched. Converting them is
    ``OCR-05``'s ``normalize_bbox``, and doing it here would leave two modules responsible for one
    guarantee.

    Args:
        item: A Docling document item.

    Returns:
        ``(left, top, right, bottom)`` in the engine's convention, or ``None`` when the item
        carries no provenance. ``None`` is the contract's "not extracted" and never a zero box:
        a zero box is a real location, and conflating the two would make a missing measurement
        look like a point in the corner.
    """
    prov = getattr(item, "prov", None)
    if not prov:
        return None
    bbox = getattr(prov[0], "bbox", None)
    if bbox is None:
        return None
    return (
        float(bbox.l),
        float(bbox.t),
        float(bbox.r),
        float(bbox.b),
    )


def extract_docling_text(result: Any) -> str:
    """Read the plain text the engine produced.

    Taken from the document's own text export rather than assembled from the items, so the text
    and the block list cannot disagree about what the engine read while still being two different
    views: the export is the engine's reading of the page, the blocks are its structure.

    Args:
        result: The engine's conversion result.

    Returns:
        The text in the engine's reading order.

    Raises:
        OCREngineExecutionError: The result carries no document.
    """
    document = getattr(result, "document", None)
    if (
        document is None
    ):  # pragma: no cover - `convert_image_with_docling` refuses this first
        raise OCREngineExecutionError(
            "extract_docling_text", "the result carries no document"
        )
    return str(document.export_to_text())


def extract_docling_markdown(result: Any) -> str:
    """Read the Markdown the engine produced.

    Args:
        result: The engine's conversion result.

    Returns:
        The Markdown as the engine rendered it. ``OCR-06`` canonicalizes it; this function does
        not, because a canonicalization applied in two places is a canonicalization that can
        disagree with itself.

    Raises:
        OCREngineExecutionError: The result carries no document.
    """
    document = getattr(result, "document", None)
    if (
        document is None
    ):  # pragma: no cover - `convert_image_with_docling` refuses this first
        raise OCREngineExecutionError(
            "extract_docling_markdown", "the result carries no document"
        )
    return str(document.export_to_markdown())


def _iter_items(result: Any) -> list[tuple[Any, int]]:
    """Return the engine's items in the order it produced them.

    A helper rather than a primitive: it exists so the four extractors below share one read of
    ``iterate_items`` instead of each walking the tree, which is both slower and a chance for two
    of them to disagree about the traversal.

    Args:
        result: The engine's conversion result.

    Returns:
        ``(item, level)`` pairs, in the engine's order.
    """
    document = result.document
    return [(item, int(level)) for item, level in document.iterate_items()]


def extract_docling_blocks(result: Any) -> list[BlockResult]:
    """Read the content blocks.

    Identifiers are minted in the engine's iteration order and use this processor's own spelling.
    Ordering them into *reading* order is ``OCR-05``'s work, and so is the tie-break that makes
    that order stable.

    Args:
        result: The engine's conversion result.

    Returns:
        The blocks, in the order the engine produced them.
    """
    blocks: list[BlockResult] = []
    for item, level in _iter_items(result):
        label = _label_value(item)
        text = str(getattr(item, "text", "") or "")
        if label not in DOCLING_LABEL_TO_BLOCK_TYPE:
            # An unmapped label is not an error: the engine recognises more kinds of content than
            # the contract names, and `other` is the honest place for them. Dropped entirely
            # would be the silent loss this processor is built to avoid.
            block_type: OCRBlockType = "other"
        else:
            block_type = DOCLING_LABEL_TO_BLOCK_TYPE[label]

        blocks.append(
            BlockResult(
                block_id=f"block_{len(blocks) + 1:0{BLOCK_ID_PADDING}d}",
                type=block_type,
                text=text,
                bbox=_bbox_of(item),
                level=level if block_type == "title" else None,
            )
        )
    return blocks


def extract_docling_tables(result: Any) -> list[TableResult]:
    """Read the detected tables.

    Cell text comes from the engine's own grid, which is what makes the cells, the Markdown and
    the JSON representations of one table agree: ``OCR-07`` renders all three from this record
    rather than asking the engine for each.

    Args:
        result: The engine's conversion result.

    Returns:
        The tables, in the order the engine produced them.

    Raises:
        OCREngineExecutionError: A table carries no readable grid.
    """
    tables: list[TableResult] = []
    for index, item in enumerate(result.document.tables, start=1):
        data = getattr(item, "data", None)
        grid = getattr(data, "grid", None) if data is not None else None
        if grid is None:
            raise OCREngineExecutionError(
                "extract_docling_tables",
                f"table {index} carries no cell grid, so its cells cannot be read",
            )
        tables.append(
            TableResult(
                table_id=f"table_{index:0{TABLE_ID_PADDING}d}",
                index=index,
                markdown=str(item.export_to_markdown(result.document)),
                bbox=_bbox_of(item),
                cells=[[str(cell.text) for cell in row] for row in grid],
            )
        )
    return tables


def extract_docling_layout(result: Any) -> LayoutResult:
    """Read the layout information.

    The page dimensions are the engine's, and the region boxes are the blocks' own boxes. Nothing
    is normalized: ``OCR-05``'s ``normalize_layout`` is what puts them into one convention, and
    applying a scale here as well would mean two places could change the geometry of the same
    record.

    Args:
        result: The engine's conversion result.

    Returns:
        The layout in the engine's coordinate convention.

    Raises:
        OCREngineExecutionError: The document reports no pages, so no geometry can be read.
    """
    pages = getattr(result.document, "pages", None)
    if not pages:
        raise OCREngineExecutionError(
            "extract_docling_layout",
            "the document reports no pages, so it has no layout",
        )

    first = next(iter(pages.values()))
    size = getattr(first, "size", None)
    regions = [
        box for box in (_bbox_of(item) for item, _ in _iter_items(result)) if box
    ]

    return LayoutResult(
        page_width=float(getattr(size, "width", 0.0)),
        page_height=float(getattr(size, "height", 0.0)),
        region_bboxes=regions,
    )


def extract_docling_metadata(result: Any) -> dict[str, object]:
    """Read the engine's own metadata.

    Kept as the engine wrote it, keyed by names this processor chose. The engine's own key names
    are its business and can move between versions; a consumer reading ``ocr/metadata.json``
    should not have to track that.

    Args:
        result: The engine's conversion result.

    Returns:
        The engine-reported facts, in this processor's spelling.
    """
    document = result.document
    pages = getattr(document, "pages", None) or {}
    first = next(iter(pages.values()), None)
    size = getattr(first, "size", None)

    return {
        "schema_name": str(getattr(document, "schema_name", "") or ""),
        "schema_version": str(getattr(document, "version", "") or ""),
        "page_count": len(pages),
        "page_width": float(getattr(size, "width", 0.0)),
        "page_height": float(getattr(size, "height", 0.0)),
        "text_items": sum(
            1 for item, _ in _iter_items(result) if _label_value(item) in TEXT_LABELS
        ),
    }


def build_ocr_document(result: Any) -> OCRDocument:
    """Assemble the engine-independent document every later stage reads.

    This is the boundary the subplan cares about: after this call nothing downstream needs
    Docling, and ``result`` itself is not carried any further. The ``reading_order`` it fills in
    is the engine's order, and ``OCR-05`` is what turns that into a *stable* reading order —
    which is why this function does not attempt the sort.

    Args:
        result: The engine's conversion result.

    Returns:
        The document, in this processor's vocabulary.
    """
    blocks = extract_docling_blocks(result)
    tables = extract_docling_tables(result)

    return OCRDocument(
        text=extract_docling_text(result),
        paragraphs=[
            block.text for block in blocks if block.type in ("text", "paragraph")
        ],
        titles=[block.text for block in blocks if block.type == "title"],
        blocks=blocks,
        tables=tables,
        layout=extract_docling_layout(result),
        reading_order=[block.block_id for block in blocks]
        + [table.table_id for table in tables],
        metadata=extract_docling_metadata(result),
    )


__all__ = [
    "BLOCK_ID_PADDING",
    "DOCLING_LABEL_TO_BLOCK_TYPE",
    "TABLE_ID_PADDING",
    "TEXT_LABELS",
    "build_ocr_document",
    "extract_docling_blocks",
    "extract_docling_layout",
    "extract_docling_markdown",
    "extract_docling_metadata",
    "extract_docling_tables",
    "extract_docling_text",
]
