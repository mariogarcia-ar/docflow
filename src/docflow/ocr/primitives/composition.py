"""Engine-independent composition of an extraction: ordering, identifiers and measurements.

Everything here works on the values :mod:`docflow.ocr.primitives` extracted from the engine's
native structures and on our own contract types — no Docling type reaches this module, and this
module reaches no engine. That is what lets the ordering, the identifier minting, the table
rendering and the metrics be asserted without a conversion ever happening.

The rules this module fixes, once each:

* **one coordinate convention** — a bounding box is ``(left, top, right, bottom)`` normalized to
  ``0..1`` against the page the engine reported (:func:`normalize_bbox`);
* **one ordering rule** — reading order is top-to-bottom, then left-to-right, with the engine's
  own item order as the last tie-break, so two blocks the engine placed at the same spot keep
  the relative order it gave them (:func:`preserve_reading_order`);
* **one identifier rule** — ``block_001`` / ``table_001``, zero-padded, minted *after* the
  ordering, so a position in the list and a name never disagree;
* **one measurement** — :func:`analyze_ocr_result` is the only place an extraction is counted.
* **one rendering of the reading** — :func:`render_reading` is the only place a page is turned
  into lines: a row of the page is one line, and a table is a block where the reading reaches it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

from docflow.ocr.contracts import (
    BlockResult,
    LayoutResult,
    OCRBlockType,
    OCRDocument,
    OCRMetrics,
    TableResult,
)
from docflow.ocr.primitives.errors import typed_failure

#: Version of the ``document.json`` schema. Fields are additive-only within a version, so a
#: consumer may read a newer document with an older reader and must refuse a different major.
DOCUMENT_SCHEMA_VERSION: Final[str] = "1"

#: A normalized bounding box: ``(left, top, right, bottom)``, each in ``0..1``.
Box = tuple[float, float, float, float]

#: Docling's own item labels → the block roles of our vocabulary. A label that is not here is
#: ``"other"``: the engine recognizing something we have no role for is data, not a failure.
DOCLING_LABEL_TO_BLOCK_TYPE: Final[dict[str, OCRBlockType]] = {
    "text": "text",
    "title": "title",
    "section_header": "title",
    "list_item": "list",
    "caption": "caption",
    "picture": "figure",
    "page_header": "other",
    "page_footer": "other",
}

#: The block roles that make an extraction *structured* rather than a flat run of text.
STRUCTURAL_BLOCK_TYPES: Final[frozenset[OCRBlockType]] = frozenset(
    {"title", "paragraph", "list", "table", "caption", "figure"}
)

#: Below this many characters a non-empty extraction is reported ``LOW_CONTENT``.
#: TODO: [MVP] a PoC value, revisited against the corpus at the MVP gate.
LOW_CONTENT_MIN_CHARACTERS: Final[int] = 8

#: Decimals a bounding box is rounded to before it is used as an ordering key. Two boxes the
#: engine reports at the same place have to compare equal, and a float that differs in its last
#: bit would otherwise order them arbitrarily.
_BOX_PRECISION: Final[int] = 6


@dataclass(frozen=True)
class LayoutGeometry:
    """The page geometry the engine reported, in the engine's own units.

    This is the last value in the pipeline that carries the engine's units: every bounding box
    is normalized against :attr:`width` / :attr:`height` before it enters the document.

    Attributes:
        width: Page width, in the engine's units.
        height: Page height, in the engine's units.
        region_bboxes: Every detected region, in the engine's units, in engine order.
    """

    width: float
    height: float
    region_bboxes: list[Box]


@dataclass(frozen=True)
class ExtractedBlock:
    """One block as extracted, before it is ordered or named.

    ``BlockResult`` deliberately carries no order field — its position in the list *is* the
    order — so the ordering needs a carrier for the engine's own sequence and the page the item
    came from. This is that carrier, and it never leaves ``primitives/``.

    Attributes:
        order: The item's position in the engine's own iteration.
        page: 1-based page the item was found on.
        type: The block role, already translated from the engine's label.
        text: The item's text.
        bbox: Normalized bounding box, or ``None`` when the engine reported none.
        level: Heading depth for a title, or ``None``.
    """

    order: int
    page: int
    type: OCRBlockType
    text: str
    bbox: Box | None
    level: int | None


@dataclass(frozen=True)
class ExtractedTable:
    """One table as extracted, before it is ordered or named.

    Attributes:
        order: The table's position in the engine's own iteration.
        bbox: Normalized bounding box, or ``None`` when the engine reported none.
        cells: The cell grid by row, then by column, already normalized to a rectangle.
    """

    order: int
    bbox: Box | None
    cells: list[list[str]]


@dataclass(frozen=True)
class OrderedDocument:
    """Blocks, tables and their shared reading order, named and in place.

    Attributes:
        blocks: Every block, in reading order.
        tables: Every table, in reading order.
        reading_order: Block and table identifiers, interleaved in reading order.
    """

    blocks: list[BlockResult]
    tables: list[TableResult]
    reading_order: list[str]


def normalize_bbox(box: Box, width: float, height: float) -> Box:
    """Normalize an engine bounding box against the page it was measured on.

    Args:
        box: ``(left, top, right, bottom)`` in the engine's units.
        width: Page width in the same units.
        height: Page height in the same units.

    Returns:
        The same box in the ``0..1`` convention. Coordinates are clamped, so a box the engine
        reported slightly outside its own page still describes a readable rectangle rather than
        a value no consumer can use.
    """
    left, top, right, bottom = box
    return (
        min(max(left / width, 0.0), 1.0),
        min(max(top / height, 0.0), 1.0),
        min(max(right / width, 0.0), 1.0),
        min(max(bottom / height, 0.0), 1.0),
    )


def normalize_layout(geometry: LayoutGeometry, *, with_regions: bool) -> LayoutResult:
    """Turn the engine's page geometry into the normalized layout of the document.

    Args:
        geometry: The page size and the detected regions, in the engine's units.
        with_regions: Whether a layout was asked for. The page's own size is always reported —
            without it there is no unit to measure a text density against, and the engine measured
            it either way — but the region boxes are claimed only when they were requested.

    Returns:
        The layout with every region box in the ``0..1`` convention. The page dimensions are
        reported as measured, so a consumer can denormalize a box; they are not rewritten to
        ``1.0``.
    """
    width, height = geometry.width, geometry.height
    regions = geometry.region_bboxes if with_regions else []
    return LayoutResult(
        page_width=width,
        page_height=height,
        region_bboxes=[normalize_bbox(box, width, height) for box in regions],
    )


def reading_order_key(page: int, bbox: Box | None, order: int) -> tuple[Any, ...]:
    """Return the sort key that puts one item where it is read.

    Top-to-bottom, then left-to-right, then the engine's own sequence. An item with no box
    (layout was not extracted) contributes no geometry, so the engine's sequence alone decides
    its place — which is the order the engine read it in, and the best answer available.

    Args:
        page: 1-based page the item was found on.
        bbox: Normalized bounding box, or ``None``.
        order: The item's position in the engine's own iteration.

    Returns:
        A total, comparable key.
    """
    if bbox is None:
        return (page, 0.0, 0.0, order)
    left, top, _, _ = bbox
    return (page, round(top, _BOX_PRECISION), round(left, _BOX_PRECISION), order)


def merge_ocr_blocks(blocks: Sequence[ExtractedBlock]) -> list[ExtractedBlock]:
    """Join consecutive body-text items into one paragraph block.

    The engine emits body text as a run of items; a run is one paragraph of ours. A title, a
    list item, a caption or a figure ends the run, so nothing is joined across a structural
    boundary. The merged block keeps the run's first position and geometry, and its box is the
    union of the boxes it joined — the paragraph's own extent, measured rather than guessed.

    Args:
        blocks: The extracted blocks, already in reading order.

    Returns:
        The blocks with every body-text run replaced by one paragraph.
    """
    merged: list[ExtractedBlock] = []
    run: list[ExtractedBlock] = []

    def flush() -> None:
        """Emit the accumulated body-text run as one paragraph."""
        if not run:
            return
        merged.append(
            ExtractedBlock(
                order=run[0].order,
                page=run[0].page,
                type="paragraph",
                text=" ".join(block.text for block in run if block.text),
                bbox=_union_box([block.bbox for block in run]),
                level=None,
            )
        )
        run.clear()

    for block in blocks:
        if block.type == "text":
            run.append(block)
        else:
            flush()
            merged.append(block)
    flush()
    return merged


def _union_box(boxes: Sequence[Box | None]) -> Box | None:
    """Return the box that contains every given box, or ``None`` when none was reported."""
    present = [box for box in boxes if box is not None]
    if not present:
        return None
    return (
        min(box[0] for box in present),
        min(box[1] for box in present),
        max(box[2] for box in present),
        max(box[3] for box in present),
    )


def normalize_table(cells: Sequence[Sequence[str]]) -> list[list[str]]:
    """Normalize an extracted cell grid into the shape a table can be rendered from.

    Each cell's text is stripped, and a row shorter than the widest row is padded with empty
    cells. The pad is a requirement of the *format* — a Markdown table has no ragged rows — and
    not a value invented for a cell: the grid arrives from the engine's own row/column offsets,
    and a hole in it is a hole the engine left.

    TODO: [MVP] spanned cells are placed at their start offset and their span is not repeated.

    Args:
        cells: The grid as extracted, by row and then by column.

    Returns:
        A rectangular grid of stripped cell texts; ``[]`` for a table with no rows.
    """
    if not cells:
        return []
    width = max(len(row) for row in cells)
    return [
        [str(cell).strip() for cell in row] + [""] * (width - len(row)) for row in cells
    ]


def table_to_markdown(cells: Sequence[Sequence[str]]) -> str:
    """Render a normalized cell grid as a Markdown table.

    Args:
        cells: The normalized grid, by row and then by column.

    Returns:
        The table in Markdown, with the first row as its header; an empty string when there are
        no rows, because a table with no rows has nothing to render.
    """
    if not cells:
        return ""
    header, *body = cells
    lines = [
        f"| {' | '.join(header)} |",
        f"| {' | '.join('---' for _ in header)} |",
    ]
    lines.extend(f"| {' | '.join(row)} |" for row in body)
    return "\n".join(lines)


def _numbered(prefix: str, position: int) -> str:
    """Return the deterministic identifier of the item at ``position``, 1-based."""
    return f"{prefix}_{position:03d}"


def preserve_reading_order(
    blocks: Sequence[ExtractedBlock],
    tables: Sequence[ExtractedTable],
    *,
    by_geometry: bool,
) -> OrderedDocument:
    """Put the extracted blocks and tables in reading order and name them, once.

    Ordering and naming happen in the same pass on purpose: an identifier minted before the sort
    would name the engine's order rather than the reading order, and the contract says a position
    in the list *is* the order.

    Args:
        blocks: The extracted blocks, in whatever order the engine handed them over.
        tables: The extracted tables, in the same condition.
        by_geometry: Whether reading order is decided by the boxes. When the caller asked for no
            reading order, the engine's own sequence is kept: it is the order the engine read in,
            and re-deriving one from geometry nobody requested would be a claim the run did not ask
            for.

    Returns:
        The blocks and tables in reading order, each named, and the interleaved list of their
        identifiers. The sort is stable and total, so the same input always yields the same
        document — which is the determinism this processor promises.
    """
    ordered_blocks = merge_ocr_blocks(
        sorted(blocks, key=lambda block: _block_key(block, by_geometry))
    )
    named_blocks = [
        BlockResult(
            block_id=_numbered("block", position),
            type=block.type,
            text=block.text,
            bbox=block.bbox,
            level=block.level,
        )
        for position, block in enumerate(ordered_blocks, start=1)
    ]

    ordered_tables = sorted(tables, key=lambda table: _table_key(table, by_geometry))
    named_tables = [
        TableResult(
            table_id=_numbered("table", position),
            index=position,
            markdown=table_to_markdown(table.cells),
            bbox=table.bbox,
            cells=table.cells,
        )
        for position, table in enumerate(ordered_tables, start=1)
    ]

    entries = [
        (_geometry_key(block.bbox if by_geometry else None, position), block.block_id)
        for position, block in enumerate(named_blocks)
    ] + [
        (_geometry_key(table.bbox if by_geometry else None, position), table.table_id)
        for position, table in enumerate(named_tables)
    ]
    reading_order = [identifier for _, identifier in sorted(entries, key=_entry_key)]
    return OrderedDocument(
        blocks=named_blocks, tables=named_tables, reading_order=reading_order
    )


@dataclass(frozen=True)
class _ReadingItem:
    """One item of the reading, with everything rendering it as a row needs.

    Attributes:
        order: The item's position in the engine's own iteration.
        bbox: Normalized box, or ``None`` when the run claimed no layout.
        text: The item's own text — a table's Markdown.
        block: Whether the item is a table, which is a block rather than a line.
    """

    order: int
    bbox: Box | None
    text: str
    block: bool


@dataclass
class _Row:
    """One visual row of the page: the items that share a line.

    Attributes:
        span: The row's vertical extent, grown as items join it.
        members: The items on it.
        whole: Whether the row is a block of its own, which is what a table is.
    """

    span: tuple[float, float]
    members: list[_ReadingItem]
    whole: bool = False


def _reading_items(
    blocks: Sequence[ExtractedBlock], tables: Sequence[ExtractedTable]
) -> list[_ReadingItem]:
    """Return every extracted item as one reading item, with a table's Markdown as its text."""
    items = [
        _ReadingItem(order=block.order, bbox=block.bbox, text=block.text, block=False)
        for block in blocks
        if block.text
    ]
    items.extend(
        _ReadingItem(
            order=table.order,
            bbox=table.bbox,
            text=table_to_markdown(table.cells),
            block=True,
        )
        for table in tables
        if table.cells
    )
    return items


def _shares_a_line(span: tuple[float, float], box: Box) -> bool:
    """Whether a box sits on a row's line, by half the shorter of the two vertical extents."""
    overlap = min(span[1], box[3]) - max(span[0], box[1])
    shorter = min(span[1] - span[0], box[3] - box[1])
    return shorter > 0 and overlap > shorter / 2


def _visual_rows(items: Sequence[_ReadingItem]) -> list[_Row]:
    """Group items into the rows of the page, top to bottom.

    Every item has to carry a box: a row is geometry, and the caller is the one that decides what
    to do when a run claimed none.
    """
    rows: list[_Row] = []
    for item in sorted(
        items, key=lambda item: (item.bbox[1], item.bbox[0], item.order)
    ):
        if item.block:
            rows.append(
                _Row(span=(item.bbox[1], item.bbox[3]), members=[item], whole=True)
            )
            continue
        row = next(
            (
                candidate
                for candidate in rows
                if not candidate.whole and _shares_a_line(candidate.span, item.bbox)
            ),
            None,
        )
        if row is None:
            rows.append(_Row(span=(item.bbox[1], item.bbox[3]), members=[item]))
            continue
        row.span = (min(row.span[0], item.bbox[1]), max(row.span[1], item.bbox[3]))
        row.members.append(item)
    rows.sort(key=lambda row: (row.span[0], row.members[0].bbox[0]))
    return rows


def _render_row(row: _Row, separator: str) -> str:
    """Render one row: a table as the block it is, a line as its items left to right."""
    if row.whole:
        return row.members[0].text
    ordered = sorted(row.members, key=lambda item: (item.bbox[0], item.order))
    return separator.join(item.text for item in ordered)


def render_reading(
    blocks: Sequence[ExtractedBlock],
    tables: Sequence[ExtractedTable],
    *,
    separator: str = "   ",
) -> str:
    """Render an extraction as one text: a row of the page per line, a table as its Markdown.

    The engine reports one region per text line, so a form's label and its value arrive as two
    items that sit side by side — and the engine's own export puts them one under the other, which
    loses the pairing the page itself states. This renders the **rows** instead: items whose
    vertical spans overlap are one line, ordered left to right, and the rows run top to bottom. A
    table is never merged into a line — it is a block, and it is rendered where the reading
    reaches it. Nothing is joined *across* rows: the page's arrangement decides where a line ends,
    which is the one thing a flat text cannot state.

    Args:
        blocks: The extracted blocks, in whatever order the engine handed them over.
        tables: The extracted tables, in the same condition.
        separator: What separates two items that share a row.

    Returns:
        The rendering, one row per line with a blank line between rows, and an empty string when
        there is nothing to read. The boxes are the whole point of this rendering, so a run that
        claimed no layout — where every box is ``None`` — is rendered verbatim in the engine's own
        sequence instead: grouping is a claim about where things are, and a run that reported no
        geometry never made it.
    """
    items = _reading_items(blocks, tables)
    if not items:
        return ""
    if any(item.bbox is None for item in items):
        return "\n\n".join(
            item.text for item in sorted(items, key=lambda item: item.order)
        )
    return "\n\n".join(_render_row(row, separator) for row in _visual_rows(items))


def _geometry_key(bbox: Box | None, position: int) -> tuple[Any, ...]:
    """Return the ordering key of a named item, whose engine sequence is its list position."""
    if bbox is None:
        return (0.0, 0.0, position)
    left, top, _, _ = bbox
    return (round(top, _BOX_PRECISION), round(left, _BOX_PRECISION), position)


def _entry_key(entry: tuple[tuple[Any, ...], str]) -> tuple[Any, ...]:
    """Order two identifiers by their geometry; the identifiers never decide the order."""
    return entry[0]


def _block_key(block: ExtractedBlock, by_geometry: bool) -> tuple[Any, ...]:
    """Return the ordering key of one extracted block."""
    return reading_order_key(
        block.page, block.bbox if by_geometry else None, block.order
    )


def _table_key(table: ExtractedTable, by_geometry: bool) -> tuple[Any, ...]:
    """Return the ordering key of one extracted table."""
    return reading_order_key(0, table.bbox if by_geometry else None, table.order)


def analyze_ocr_result(document: OCRDocument) -> OCRMetrics:
    """Measure an extraction. Measurements, not judgements.

    This is the single place an extraction is counted: no ``count_*`` helper exists beside it,
    and no metric is invented for a value that was not observed.

    Args:
        document: The engine-independent document, already ordered.

    Returns:
        The measurements. ``text_density`` is characters per unit of page area, computed from
        the area the engine reported with the layout; ``empty`` says the extraction produced no
        text at all — which is data about the input, not a failure of the run.

    Raises:
        OCRPrimitiveError: With ``LAYOUT_ERROR`` when the document carries no page area, because
            there is then no unit to measure the density against and a ``0.0`` would read as a
            measurement nobody took.
    """
    text = document.text
    characters = len(text)
    area = document.layout.page_width * document.layout.page_height
    if area <= 0:
        raise typed_failure(
            "LAYOUT_ERROR",
            "the document carries no page area to measure the text density against",
            recoverable=False,
            metadata={
                "page_width": document.layout.page_width,
                "page_height": document.layout.page_height,
            },
        )
    return OCRMetrics(
        characters=characters,
        words=len(text.split()),
        blocks=len(document.blocks),
        tables=len(document.tables),
        paragraphs=sum(1 for block in document.blocks if block.type == "paragraph"),
        text_density=characters / area,
        empty=not text.strip(),
        structure_detected=bool(document.tables)
        or any(block.type in STRUCTURAL_BLOCK_TYPES for block in document.blocks),
    )
