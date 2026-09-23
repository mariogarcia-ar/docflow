"""Deterministic geometry and reading order (``OCR-05``).

The subplan's determinism posture is "same image + same engine version + same normalized options
⇒ same **logical output structure**", and this module delivers the second half of it. Two jobs,
and they answer different failure modes:

* **One coordinate convention.** The engine reports boxes in pixels against a ``BOTTOMLEFT``
  origin; a consumer downstream should never have to know that. Everything here maps into a
  ``(0.0, 1.0)`` reference frame with a **``TOPLEFT``** origin, so a bbox in the artifact means
  exactly one thing without the reader having to look up which engine produced it.
* **A reading order that does not inherit the engine's iteration order.** The engine's order was
  *measured* to be stable for a fixed build — three identical conversions produced byte-identical
  block order — but "stable for this build" is not the guarantee the plan asks for. The tie-break
  has to be a **rule**, so the same blocks sort the same way whatever order they arrive in, and a
  test proves it by shuffling the input.

The five names here are §3.4's *Layout* group, name for name. ``count_tables`` and
``normalize_table`` are in that document too, but under *Tables*: they belong to ``OCR-07`` and
live in :mod:`docflow.ocr.primitives.rendering`, where ``OCR-02`` declared them. The scope line
"tie-break by normalized `bbox`" is delivered by ordering and normalizing in one step, so no
block-level normalizer had to be invented.
"""

from __future__ import annotations

from typing import Final

from docflow.ocr.contracts import BlockResult, LayoutResult, TableResult

COORDINATE_REFERENCE: Final[str] = "TOPLEFT"
"""The origin the normalized boxes are expressed against.

A constant, and written into the artifact's metadata: a normalized box without its origin is
ambiguous, and the engine's own origin is the *other* one.
"""

ENGINE_COORDINATE_ORIGIN: Final[str] = "BOTTOMLEFT"
"""The origin the engine's boxes arrive in — a **measured** fact, not a setting.

The plan fixes Docling as the only engine, and a probe of the fixture's extraction showed every
``bbox`` reported as ``(left, top, right, bottom)`` in pixels against a bottom-left origin. So the
conversion is not parameterized: an ``origin`` argument would imply a choice that does not exist
and could only be passed the wrong value, and its wrong value is invisible — a ``TOPLEFT`` box
flipped anyway lands in the same place on a square page or a box spanning the full height.
"""

COORDINATE_RANGE: Final[tuple[float, float]] = (0.0, 1.0)
"""The reference frame's bounds, inclusive of both ends.

``0.0`` is the page's left or top edge and ``1.0`` its right or bottom, so a box covering the whole
page is ``(0.0, 0.0, 1.0, 1.0)``. Values are not clamped; see :func:`normalize_bbox`.
"""

UNPOSITIONED_SORT_PREFIX: Final[float] = 1.0
"""The leading key element used for an item with no box.

Every normalized coordinate is at most ``1.0``, so a prefix of ``1.0`` alone would tie with a box
touching the page's bottom edge. The *pair* ``(1.0, 0.0)`` cannot: the next key element of a
positioned item is its normalized top, which for a box touching the bottom edge is exactly
``1.0``, and the comparison then continues into left and bottom coordinates that are not all zero
for any real box. The two groups are separated, which is what keeping an unlocatable block *after*
the page's title depends on.
"""


def _sort_key(box: tuple[float, float, float, float], identifier: str) -> tuple:
    """Return the key a positioned item is ordered by.

    ``(0.0, top, left, bottom, right, identifier)``. Top before left because reading order is
    line-major: two blocks on one line are ordered left to right, and a block on a lower line comes
    after both whatever their horizontal positions. Ordering by ``left`` first would interleave
    lines on a two-column page, which is the classic reading-order defect.

    The identifier is last so the order is **total**, and it is the *only* tie-break. Without it,
    two items with identical geometry would be ordered by arrival — and arrival is the engine's
    iteration order, which is precisely what must not reach the artifact. The identifiers are
    zero-padded when minted (``block_007``, ``table_012``) so they compare in numeric order as
    strings, which is what makes a single string element sufficient.

    Args:
        box: The normalized ``(left, top, right, bottom)`` box.
        identifier: The item's identifier, as the tie-break of last resort.

    Returns:
        The sort key.
    """
    left, top, right, bottom = box
    return (0.0, top, left, bottom, right, identifier)


def normalize_bbox(
    bbox: tuple[float, float, float, float],
    page_width: float,
    page_height: float,
) -> tuple[float, float, float, float]:
    """Map one bounding box into the normalized ``TOPLEFT`` reference frame.

    The engine reports ``(left, top, right, bottom)`` in **pixels** against a ``BOTTOMLEFT``
    origin, so the vertical axis is measured from the page's bottom and ``top`` is the *larger*
    value. The normalized frame measures from the top, so::

        normalized_top    = (page_height - bbox_top) / page_height
        normalized_bottom = (page_height - bbox_bottom) / page_height

    which yields ``top <= bottom``, the convention everything downstream expects.

    **Values are not clamped.** A box that leaves the page passes through as computed, because
    clamping would silently move content to the edge and a reader could not tell a tall block from
    a clipped one. The engine's boxes are inside the page; if one is not, that is a fact about the
    extraction worth keeping.

    Args:
        bbox: The engine's ``(left, top, right, bottom)`` in pixels.
        page_width: Page width in pixels, from the engine.
        page_height: Page height in pixels, from the engine.

    Returns:
        The box in the normalized frame.

    Raises:
        ValueError: The page has no area, so no scale exists. Refused rather than returning
            zeroes: ``0.0`` is a legitimate coordinate, so every block would land in the page's
            corner and look measured.
    """
    if page_width <= 0 or page_height <= 0:
        raise ValueError(
            f"cannot normalize against a page of {page_width}x{page_height}: a page with no "
            "area has no scale, and returning zeroes would place every box at the origin"
        )

    left, top, right, bottom = bbox
    top, bottom = page_height - top, page_height - bottom

    return (
        min(left, right) / page_width,
        min(top, bottom) / page_height,
        max(left, right) / page_width,
        max(top, bottom) / page_height,
    )


def normalize_layout(layout: LayoutResult) -> LayoutResult:
    """Normalize a whole layout into the ``TOPLEFT`` reference frame.

    The page dimensions become ``1.0`` on each axis: they are the scale the boxes are now expressed
    against, so keeping the pixel size beside them would invite a reader to apply it twice.

    Args:
        layout: The layout as the engine reported it.

    Returns:
        The layout in the normalized frame.

    Raises:
        ValueError: The page has no area, so no box can be normalized.
    """
    regions = [
        normalize_bbox(box, layout.page_width, layout.page_height)
        for box in layout.region_bboxes
    ]
    return LayoutResult(page_width=1.0, page_height=1.0, region_bboxes=regions)


def preserve_reading_order(
    blocks: list[BlockResult],
    tables: list[TableResult],
    page_width: float,
    page_height: float,
) -> tuple[list[BlockResult], list[TableResult], list[str]]:
    """Normalize every box and order the items into one deterministic reading order.

    Normalizing and ordering are one step rather than two because the order is *defined* on
    normalized geometry: ordering pixel boxes and normalizing afterwards would sort by a frame the
    artifact does not use, and the two would disagree the moment a page was not square.

    Blocks and tables are merged into a single sequence because a reader does not experience them
    as two streams: a table between two paragraphs is between them on the page.

    An item with **no box** is kept, sorts **last**, and keeps ``None``. Substituting a zero box
    would turn "no geometry was extracted" into "this block sits at the top-left corner" — the
    silent stand-in the project forbids, and exactly the conflation ``None`` exists to prevent.
    Sorting it last rather than first keeps an unlocatable block from being pushed above the
    page's title.

    Args:
        blocks: The blocks to order. Read, never modified.
        tables: The tables to order. Read, never modified.
        page_width: Page width in pixels, from the engine.
        page_height: Page height in pixels, from the engine.

    Returns:
        The ordered, normalized blocks; the ordered, normalized tables; and the identifiers in
        reading order. Every input item appears in exactly one of the two lists — none dropped,
        none invented.

    Raises:
        ValueError: The page has no area.
    """
    items: list[
        tuple[BlockResult | TableResult, tuple[float, float, float, float] | None]
    ] = []
    for block in blocks:
        items.append(
            (
                block,
                None
                if block.bbox is None
                else normalize_bbox(block.bbox, page_width, page_height),
            )
        )
    for table in tables:
        items.append(
            (
                table,
                None
                if table.bbox is None
                else normalize_bbox(table.bbox, page_width, page_height),
            )
        )

    def key(
        item: tuple[
            BlockResult | TableResult, tuple[float, float, float, float] | None
        ],
    ) -> tuple:
        record, box = item
        identifier = (
            record.block_id if isinstance(record, BlockResult) else record.table_id
        )
        if box is None:
            return (
                UNPOSITIONED_SORT_PREFIX,
                0.0,
                0.0,
                0.0,
                0.0,
                identifier,
            )
        return _sort_key(box, identifier)

    ordered = sorted(items, key=key)
    ordered_blocks = [
        _with_box(record, box)
        for record, box in ordered
        if isinstance(record, BlockResult)
    ]
    ordered_tables = [
        _with_box(record, box)
        for record, box in ordered
        if isinstance(record, TableResult)
    ]
    identifiers = [
        record.block_id if isinstance(record, BlockResult) else record.table_id
        for record, _ in ordered
    ]
    return ordered_blocks, ordered_tables, identifiers  # type: ignore[return-value]


def _with_box(
    record: BlockResult | TableResult,
    box: tuple[float, float, float, float] | None,
) -> BlockResult | TableResult:
    """Return a copy of a record carrying a given box.

    A new record rather than a field assignment: the contract's records are frozen, and mutating
    one would edit the caller's list while appearing to return a new one.

    A table's cells are carried over **by reference**. They are read-only in practice — ``OCR-07``
    builds them once and nothing writes to them — and copying a large grid per run would be a cost
    with no guarantee behind it.

    ``# TODO: [RELEASE]`` a defensive copy of the cells if a consumer ever mutates one in place.

    Args:
        record: The block or table to copy.
        box: The normalized box to attach, or ``None``.

    Returns:
        The copy.
    """
    if isinstance(record, BlockResult):
        return BlockResult(
            block_id=record.block_id,
            type=record.type,
            text=record.text,
            bbox=box,
            level=record.level,
        )
    return TableResult(
        table_id=record.table_id,
        index=record.index,
        markdown=record.markdown,
        bbox=box,
        cells=record.cells,
    )


def count_blocks(blocks: list[BlockResult]) -> int:
    """Count the blocks.

    Args:
        blocks: The blocks to count.

    Returns:
        The number of blocks.
    """
    return len(blocks)


def calculate_ocr_text_density(
    characters: int, page_width: float, page_height: float
) -> float:
    """Characters per unit of page area.

    The area is taken in whichever frame the caller is working in — normalized, after
    :func:`normalize_layout`, or pixels before it — and the figure is only comparable between runs
    of the same pipeline, which is what the plan asks of it. Recorded against a normalized page the
    area is ``1.0`` and the density equals the character count, which is a legitimate reading;
    refusing to divide instead would drop a metric ``OCR-08`` needs.

    Args:
        characters: Extracted characters.
        page_width: Page width, in whatever frame the caller is working in.
        page_height: Page height, in the same frame.

    Returns:
        The density, or ``0.0`` when the page has no area. ``0.0`` rather than an error because a
        page with no area has a density of zero for any positive character count, and the caller
        is ``OCR-08``, which reports metrics rather than validating geometry.
    """
    if page_width <= 0 or page_height <= 0:
        return 0.0
    return characters / (page_width * page_height)


__all__ = [
    "COORDINATE_RANGE",
    "COORDINATE_REFERENCE",
    "ENGINE_COORDINATE_ORIGIN",
    "UNPOSITIONED_SORT_PREFIX",
    "calculate_ocr_text_density",
    "count_blocks",
    "normalize_bbox",
    "normalize_layout",
    "preserve_reading_order",
]
