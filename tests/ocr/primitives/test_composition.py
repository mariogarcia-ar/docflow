"""Tests for the engine-independent composition (``OCR-05``, ``OCR-07``, ``OCR-08``).

Nothing here needs an engine: the inputs are values our own seam produces, and every assertion is
about the ordering rule, the identifier rule, the table rendering or the measurement. Where a
number is asserted it is one a reader can check by hand from the boxes the test wrote.
"""

from __future__ import annotations

from typing import Any

import pytest

from docflow.ocr.contracts import LayoutResult, OCRDocument
from docflow.ocr.primitives import OCRPrimitiveError
from docflow.ocr.primitives.composition import (
    LOW_CONTENT_MIN_CHARACTERS,
    ExtractedBlock,
    ExtractedTable,
    LayoutGeometry,
    analyze_ocr_result,
    merge_ocr_blocks,
    normalize_bbox,
    normalize_layout,
    normalize_table,
    preserve_reading_order,
    render_reading,
    table_to_markdown,
)


def block(
    order: int,
    text: str,
    box: tuple[float, float, float, float] | None,
    *,
    type_: str = "text",
    page: int = 1,
    level: int | None = None,
) -> ExtractedBlock:
    """Return one extracted block, for the cases below."""
    return ExtractedBlock(
        order=order,
        page=page,
        type=type_,
        text=text,
        bbox=box,
        level=level,  # type: ignore[arg-type]
    )


def table(
    order: int, cells: list[list[str]], box: tuple[float, float, float, float] | None
) -> ExtractedTable:
    """Return one extracted table, for the cases below."""
    return ExtractedTable(order=order, bbox=box, cells=cells)


def document(
    *,
    text: str,
    blocks: list[Any] | None = None,
    tables: list[Any] | None = None,
    layout: LayoutResult | None = None,
) -> OCRDocument:
    """Return a document as the assembly step would build it."""
    return OCRDocument(
        text=text,
        paragraphs=[],
        titles=[],
        blocks=blocks or [],
        tables=tables or [],
        layout=layout
        or LayoutResult(page_width=100.0, page_height=200.0, region_bboxes=[]),
        reading_order=[],
        metadata={},
    )


def test_a_box_is_normalized_against_the_page_it_was_measured_on() -> None:
    """The convention is ours, ``0..1``, and it is applied once."""
    assert normalize_bbox((25.0, 50.0, 75.0, 100.0), 100.0, 200.0) == (
        0.25,
        0.25,
        0.75,
        0.5,
    )


def test_a_box_outside_the_page_is_clamped_rather_than_dropped() -> None:
    """A box the engine measured slightly off the page still describes a usable rectangle."""
    assert normalize_bbox((-10.0, -10.0, 200.0, 400.0), 100.0, 200.0) == (
        0.0,
        0.0,
        1.0,
        1.0,
    )


def test_the_layout_reports_the_page_as_measured_and_the_regions_normalized() -> None:
    """A consumer can denormalize a box, because the page size it was divided by is recorded."""
    layout = normalize_layout(
        LayoutGeometry(
            width=200.0, height=100.0, region_bboxes=[(20.0, 10.0, 60.0, 30.0)]
        ),
        with_regions=True,
    )

    assert (layout.page_width, layout.page_height) == (200.0, 100.0)
    assert layout.region_bboxes == [(0.1, 0.1, 0.3, 0.3)]


def test_a_layout_that_was_not_asked_for_claims_no_region_but_keeps_the_page() -> None:
    """The page size is what everything else is measured against; the boxes are a claim."""
    layout = normalize_layout(
        LayoutGeometry(
            width=200.0, height=100.0, region_bboxes=[(20.0, 10.0, 60.0, 30.0)]
        ),
        with_regions=False,
    )

    assert not layout.region_bboxes
    assert layout.page_width == 200.0


def test_the_reading_order_goes_top_to_bottom_then_left_to_right() -> None:
    """Geometry decides the order, not the sequence the engine handed the items over in."""
    blocks = [
        block(0, "second", (0.1, 0.5, 0.5, 0.6), type_="caption"),
        block(1, "first", (0.1, 0.1, 0.5, 0.2), type_="caption"),
        block(2, "left", (0.05, 0.5, 0.2, 0.6), type_="caption"),
    ]

    ordered = preserve_reading_order(blocks, [], by_geometry=True)

    assert [result.text for result in ordered.blocks] == ["first", "left", "second"]
    assert [result.block_id for result in ordered.blocks] == [
        "block_001",
        "block_002",
        "block_003",
    ]


def test_two_items_at_the_same_spot_keep_the_engines_relative_order() -> None:
    """The last tie-break is the engine's own sequence, so a tie is still deterministic."""
    blocks = [
        block(7, "later", (0.1, 0.1, 0.5, 0.2), type_="caption"),
        block(3, "earlier", (0.1, 0.1, 0.5, 0.2), type_="caption"),
    ]

    ordered = preserve_reading_order(blocks, [], by_geometry=True)

    assert [result.text for result in ordered.blocks] == ["earlier", "later"]


def test_an_item_with_no_box_falls_back_to_the_engines_sequence() -> None:
    """Without geometry there is no reading order to derive, and the engine's own is kept."""
    blocks = [
        block(0, "third", None, type_="caption"),
        block(1, "first", None, type_="caption"),
        block(2, "second", None, type_="caption"),
    ]

    ordered = preserve_reading_order(blocks, [], by_geometry=True)

    assert [result.text for result in ordered.blocks] == ["third", "first", "second"]


def test_consecutive_body_text_items_become_one_paragraph() -> None:
    """A run of body text is one paragraph of ours, joined in the order it was read."""
    merged = merge_ocr_blocks(
        [
            block(0, "Revenue grew by twelve percent", (0.1, 0.1, 0.9, 0.2)),
            block(1, "across every region.", (0.1, 0.2, 0.9, 0.3)),
        ]
    )

    assert len(merged) == 1
    assert merged[0].type == "paragraph"
    assert merged[0].text == "Revenue grew by twelve percent across every region."


def test_a_merged_paragraph_keeps_the_union_of_its_boxes() -> None:
    """The paragraph's extent is measured from what it joined, not guessed."""
    merged = merge_ocr_blocks(
        [
            block(0, "one", (0.1, 0.1, 0.5, 0.2)),
            block(1, "two", (0.2, 0.2, 0.9, 0.3)),
        ]
    )

    assert merged[0].bbox == (0.1, 0.1, 0.9, 0.3)


def test_a_title_ends_a_body_text_run() -> None:
    """Nothing is joined across a structural boundary."""
    merged = merge_ocr_blocks(
        [
            block(0, "before", (0.1, 0.1, 0.9, 0.2)),
            block(1, "A heading", (0.1, 0.3, 0.9, 0.4), type_="title", level=1),
            block(2, "after", (0.1, 0.5, 0.9, 0.6)),
        ]
    )

    assert [item.type for item in merged] == ["paragraph", "title", "paragraph"]
    assert merged[1].level == 1


def test_an_identifier_names_the_reading_position_and_not_the_engine_position() -> None:
    """A block the engine handed over first is ``block_002`` when it is read second."""
    ordered = preserve_reading_order(
        [
            block(0, "second", (0.1, 0.5, 0.9, 0.6), type_="caption"),
            block(1, "first", (0.1, 0.1, 0.9, 0.2), type_="caption"),
        ],
        [],
        by_geometry=True,
    )

    assert [(item.block_id, item.text) for item in ordered.blocks] == [
        ("block_001", "first"),
        ("block_002", "second"),
    ]


def test_the_reading_order_interleaves_blocks_and_tables() -> None:
    """The list is the document's reading order, and it names every block and every table once."""
    ordered = preserve_reading_order(
        [
            block(0, "after the table", (0.1, 0.8, 0.9, 0.9), type_="caption"),
            block(1, "before the table", (0.1, 0.1, 0.9, 0.2), type_="caption"),
        ],
        [table(0, [["a"]], (0.1, 0.4, 0.9, 0.6))],
        by_geometry=True,
    )

    assert ordered.reading_order == ["block_001", "table_001", "block_002"]
    assert ordered.tables[0].index == 1
    assert set(ordered.reading_order) == {item.block_id for item in ordered.blocks} | {
        item.table_id for item in ordered.tables
    }


def test_without_geometry_the_engine_sequence_decides_and_nothing_is_sorted() -> None:
    """``by_geometry=False`` is the option's meaning: keep what the engine read."""
    ordered = preserve_reading_order(
        [
            block(0, "engine first", (0.1, 0.8, 0.9, 0.9), type_="caption"),
            block(1, "engine second", (0.1, 0.1, 0.9, 0.2), type_="caption"),
        ],
        [],
        by_geometry=False,
    )

    assert [item.text for item in ordered.blocks] == ["engine first", "engine second"]


def test_a_row_of_the_page_is_one_line_and_the_rows_run_top_to_bottom() -> None:
    """A label and its value share a row, so they share a line — the engine's sequence cannot.

    The engine hands the value over before the label it belongs to, because they are two regions;
    the boxes are what puts them back together, and the rows are rendered top to bottom whatever
    order they arrived in. This is the reading the engine's own text export cannot state.
    """
    rendered = render_reading(
        [
            block(0, "CVC S.A. (63)", (0.5, 0.30, 0.9, 0.32)),
            block(1, "Domicilio:", (0.05, 0.36, 0.3, 0.38)),
            block(2, "Cliente:", (0.05, 0.30, 0.2, 0.32)),
            block(3, "CIRCUNVALACION 1245", (0.5, 0.36, 0.9, 0.38)),
        ],
        [],
    )

    assert rendered == "Cliente:   CVC S.A. (63)\n\nDomicilio:   CIRCUNVALACION 1245"


def test_a_row_is_ordered_left_to_right_whatever_order_it_arrived_in() -> None:
    """Three items on one line: the x of their boxes decides, not the engine's sequence."""
    rendered = render_reading(
        [
            block(0, "third", (0.8, 0.10, 0.9, 0.12)),
            block(1, "first", (0.1, 0.10, 0.2, 0.12)),
            block(2, "second", (0.4, 0.10, 0.5, 0.12)),
        ],
        [],
    )

    assert rendered == "first   second   third"


def test_a_table_is_a_block_of_its_own_and_keeps_its_place_in_the_reading() -> None:
    """The table is carried as its Markdown, between the rows the page puts around it."""
    rendered = render_reading(
        [
            block(0, "TOTAL", (0.05, 0.70, 0.2, 0.72)),
            block(1, "Contado", (0.05, 0.20, 0.2, 0.22)),
        ],
        [table(1, [["Region", "Revenue"], ["North", "120"]], (0.05, 0.40, 0.9, 0.60))],
    )

    assert rendered == (
        "Contado\n\n| Region | Revenue |\n| --- | --- |\n| North | 120 |\n\nTOTAL"
    )


def test_a_table_is_never_merged_into_a_row_that_shares_its_band() -> None:
    """A label beside a table keeps a row of its own: a table is a block, not a line.

    The boxes overlap by more than half the shorter extent, so a grouping that let a table's row
    take neighbours would swallow the label and its value — the row renders its first member, which
    is the table. The rule is what keeps both.
    """
    rendered = render_reading(
        [
            block(0, "cliente:", (0.05, 0.44, 0.3, 0.48)),
            block(1, "value", (0.5, 0.44, 0.9, 0.48)),
        ],
        [table(2, [["a", "b"]], (0.05, 0.40, 0.9, 0.50))],
    )

    assert rendered == "| a | b |\n| --- | --- |\n\ncliente:   value"


def test_without_boxes_the_engine_sequence_is_rendered_verbatim() -> None:
    """A row is geometry, so a run that claimed none is rendered as the engine read it.

    Grouping is a claim about where things are; a run that reported no geometry never made it, and
    inventing a row from nothing would be exactly that claim.
    """
    rendered = render_reading(
        [block(0, "value", None), block(2, "label:", None)],
        [table(1, [["a", "b"]], None)],
    )

    assert rendered == "value\n\n| a | b |\n| --- | --- |\n\nlabel:"


def test_an_extraction_with_nothing_in_it_renders_as_nothing() -> None:
    """Nothing read is nothing to render — not a blank line."""
    assert render_reading([], []) == ""


def test_a_ragged_row_is_padded_to_the_widest_one() -> None:
    """A Markdown table has no ragged rows; the pad is the format's requirement, not a value."""
    assert normalize_table([["a", "b"], ["c"]]) == [["a", "b"], ["c", ""]]


def test_the_cells_are_stripped_of_the_engines_whitespace() -> None:
    """Normalization is one pass over the grid, so nothing downstream re-trims a cell."""
    assert normalize_table([[" a ", "\nb\n"]]) == [["a", "b"]]


def test_a_table_with_no_rows_renders_as_nothing() -> None:
    """A table with no rows has nothing to render; it is not rendered as an empty pipe."""
    assert normalize_table([]) == []
    assert table_to_markdown([]) == ""


def test_the_markdown_table_has_a_header_and_a_separator() -> None:
    """The first row is the header, which is the shape every Markdown reader expects."""
    assert table_to_markdown([["Region", "Revenue"], ["North", "120"]]) == (
        "| Region | Revenue |\n| --- | --- |\n| North | 120 |"
    )


def test_the_metrics_are_measured_from_the_document() -> None:
    """Every count comes from the document; nothing is estimated."""
    ordered = preserve_reading_order(
        [
            block(0, "A heading", (0.1, 0.1, 0.9, 0.2), type_="title", level=1),
            block(1, "one", (0.1, 0.3, 0.9, 0.4)),
            block(2, "two", (0.1, 0.4, 0.9, 0.5)),
        ],
        [table(0, [["a", "b"]], (0.1, 0.6, 0.9, 0.7))],
        by_geometry=True,
    )
    composed = document(
        text="A heading\n\none two",
        blocks=ordered.blocks,
        tables=ordered.tables,
        layout=LayoutResult(page_width=100.0, page_height=200.0, region_bboxes=[]),
    )

    metrics = analyze_ocr_result(composed)

    assert metrics.characters == len("A heading\n\none two")
    assert metrics.words == 4
    assert metrics.blocks == 2
    assert metrics.tables == 1
    assert metrics.paragraphs == 1
    assert metrics.text_density == len("A heading\n\none two") / 20_000.0
    assert metrics.empty is False
    assert metrics.structure_detected is True


def test_an_extraction_with_no_text_is_empty_rather_than_short() -> None:
    """``empty`` is a measurement of the text, not a judgement about the page."""
    metrics = analyze_ocr_result(document(text=""))

    assert metrics.characters == 0
    assert metrics.words == 0
    assert metrics.empty is True
    assert metrics.structure_detected is False


def test_an_extraction_shorter_than_the_usable_floor_is_still_measured() -> None:
    """The metric reports what it counted; deciding that a page is short is not its job."""
    metrics = analyze_ocr_result(document(text="ab"))

    assert metrics.characters == 2
    assert metrics.empty is False
    assert metrics.characters < LOW_CONTENT_MIN_CHARACTERS


def test_a_document_with_no_page_area_cannot_be_measured() -> None:
    """There is no unit to measure a density against, so a ``0.0`` would be an invented answer."""
    unmeasurable = document(
        text="text",
        layout=LayoutResult(page_width=0.0, page_height=0.0, region_bboxes=[]),
    )

    with pytest.raises(OCRPrimitiveError) as failure:
        analyze_ocr_result(unmeasurable)

    assert failure.value.error.type == "LAYOUT_ERROR"
