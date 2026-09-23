"""Tests for table processing (``OCR-07``).

The two acceptance criteria are the spine of this module, and the second one is the one that is
easy to get wrong by inventing something: an image with no table produces **no** ``tables/``
artifact and **no** error, because an empty table list is data rather than a failure.

Most of the tests are unit tests over hand-built tables. The fixture's own table is a real invoice
grid — five rows by four columns, with empty cells — and it is used for the criterion itself and for
one check the hand-built tables cannot make: that the stored Markdown is a faithful rendering of the
cells beside it.
"""

from __future__ import annotations

import pytest

from docflow.ocr.contracts import TableResult
from docflow.ocr.primitives import rendering
from tests.ocr.primitives.engine_corpus import extracted_document


def table(cells: list[list[str]], identifier: str = "table_001") -> TableResult:
    """Return a hand-built table with a given grid.

    Args:
        cells: The cell contents, by row then by column.
        identifier: The table's identifier.

    Returns:
        The table.
    """
    return TableResult(
        table_id=identifier, index=1, markdown="", bbox=None, cells=cells
    )


def rows_of(markdown: str) -> list[str]:
    """Return a Markdown table's lines.

    Args:
        markdown: The rendered table.

    Returns:
        Its lines.
    """
    return markdown.rstrip("\n").splitlines()


# ======================================================================================
# Criterion 1 - a table becomes table_001.md preserving its cell values
# ======================================================================================


def test_process_tables_names_the_first_table_table_001_md() -> None:
    """The criterion's file name, and the zero-padding that makes it sort."""
    pairs = rendering.process_tables([table([["a", "b"], ["c", "d"]])])

    assert len(pairs) == 1
    name, content = pairs[0]
    assert name == "table_001.md"
    assert content


def test_process_tables_preserves_every_cell_value_in_reading_order() -> None:
    """The criterion's other half: the values survive, row by row and column by column.

    Asserted by position rather than by membership, because "the values appear somewhere" would pass
    for a grid whose rows had been transposed — which is the defect an OCR table export most often
    has.
    """
    grid = [["Canti", "Descripcion", "Importe"], ["1", "MILANESA", "15500,00"]]

    name, content = rendering.process_tables([table(grid)])[0]

    assert name == "table_001.md"
    lines = rows_of(content)
    header, _divider, *body = lines
    assert [cell.strip() for cell in header.strip("|").split("|")] == grid[0]
    assert [cell.strip() for cell in body[0].strip("|").split("|")] == grid[1]


def test_process_tables_emits_one_file_per_table_with_padded_names() -> None:
    """Ten tables sort on disk the way they read, which is what the padding is for."""
    tables = [table([["a"]], identifier=f"table_{index:03d}") for index in range(1, 12)]

    names = [name for name, _ in rendering.process_tables(tables)]

    assert names[0] == "table_001.md"
    assert names[9] == "table_010.md"
    assert names == sorted(names), "the names do not sort in reading order"


def test_process_tables_does_not_re_order_the_tables_it_is_given() -> None:
    """Reading order is ``preserve_reading_order``'s result and the caller already has it.

    A second sort here would be a second definition of the order. These identifiers are deliberately
    the reverse of the list order, so a sort by name would be visible.
    """
    tables = [
        table([["first"]], identifier="table_003"),
        table([["second"]], identifier="table_001"),
        table([["third"]], identifier="table_002"),
    ]

    names = [name for name, _ in rendering.process_tables(tables)]

    assert names == ["table_003.md", "table_001.md", "table_002.md"]


def test_process_tables_returns_contents_that_are_newline_terminated() -> None:
    """The file is a file, so its text ends in a newline."""
    _name, content = rendering.process_tables([table([["a", "b"]])])[0]

    assert content.endswith("\n")
    assert not content.endswith("\n\n")


def test_the_real_table_is_exported_with_its_cells_in_order() -> None:
    """The criterion against the committed fixture, cell by cell.

    The fixture's table is five rows by four columns. Both figures are asserted because a 1x1
    mis-detection satisfies "a table exists" while carrying almost none of the page's content.
    """
    document = extracted_document()
    assert document.tables, "the fixture produced no table"

    pairs = rendering.process_tables(document.tables)

    assert len(pairs) == len(document.tables)
    name, content = pairs[0]
    assert name == "table_001.md"
    assert len(rows_of(content)) >= 3, "the table has no body"
    for cell in document.tables[0].cells:
        for value in cell:
            if value.strip():
                assert value.strip() in content, f"{value!r} was dropped"


# ======================================================================================
# Criterion 2 - no table means no artifact and no error
# ======================================================================================


def test_an_empty_table_list_produces_no_pairs_and_no_error() -> None:
    """The criterion, and the no-silent-stand-in rule.

    No ``tables/`` directory is required, and nothing is invented to fill one. An empty list is
    data; a function that raised here would turn "this page has no table" into a failure.
    """
    assert rendering.process_tables([]) == []


def test_count_tables_reports_zero_for_an_image_with_no_table() -> None:
    """``0`` is a measurement, not a placeholder, and ``OCR-09`` reads it rather than treating it
    as an error."""
    assert rendering.count_tables([]) == 0


def test_count_tables_counts_what_it_is_given() -> None:
    """A table is one table however many rows it has.

    The grids are deliberately multi-row: an earlier version of this test used single-row tables,
    where ``len(tables)`` and ``sum(len(table.cells))`` agree and a mutation that swapped one for
    the other survived.
    """
    one = table([["a"], ["b"], ["c"]])
    other = table([["d"], ["e"]])

    assert rendering.count_tables([one]) == 1
    assert rendering.count_tables([one, other]) == 2
    assert rendering.count_tables([one]) != len(one.cells)


def test_a_table_with_no_cells_is_not_exported_as_an_empty_table() -> None:
    """A table object with no grid produces no file rather than a headerless pipe row.

    No committed fixture reaches this, and a renderer that emitted a divider for it would be
    publishing a table the page does not have.
    """
    assert rendering.process_tables([table([])]) == []


def test_a_table_with_no_rows_renders_nothing() -> None:
    """The same edge one level down, where the empty rendering is produced."""
    assert rendering.table_to_markdown(table([])) == ""


# ======================================================================================
# normalize_table - the cells are canonical, the Markdown is a rendering of them
# ======================================================================================


def test_normalize_table_re_renders_the_markdown_from_the_cells() -> None:
    """Otherwise the record holds two representations of one table that can disagree.

    ``TableResult.markdown`` is the *engine's* rendering, captured by ``OCR-04`` and read by no
    artifact. Trusting it would mean a consumer reading ``table_001.md`` and a consumer reading the
    JSON ``cells`` could see different tables.
    """
    engine_markdown = "| a | b |\n|---|---|\n| 1 | 2 |"
    original = TableResult(
        table_id="table_001",
        index=1,
        markdown=engine_markdown,
        bbox=None,
        cells=[["a", "b"], ["1", "2"]],
    )

    normalized = rendering.normalize_table(original)

    assert normalized.markdown != engine_markdown, "the engine's rendering was kept"
    assert normalized.markdown == rendering.table_to_markdown(original).rstrip("\n")


def test_normalize_table_leaves_a_clean_grid_untouched() -> None:
    """The repair must not rewrite content that needs no repair.

    A canonicalizer that "tidied" the values would be a different table, which is the boundary that
    keeps this a canonicalization rather than a transformation.
    """
    grid = [["Canti", "Importe"], ["1", "15500,00"], ["", "13469,50"]]

    normalized = rendering.normalize_table(table(grid))

    assert normalized.cells == grid


def test_normalize_table_canonicalizes_every_cell() -> None:
    """A control character or a combining mark in a cell is repaired like anywhere else.

    ``document.json``'s ``cells`` is a list of lists that never passes through the document-wide
    canonicalization, so this is the only step that can repair a cell before it reaches the
    structured artifact. Measured: a ``\\x00`` survived into ``document.json`` without it.
    """
    normalized = rendering.normalize_table(table([["a\x00b", "e\u0301"]]))

    assert normalized.cells == [["ab", "\u00e9"]]


def test_normalize_table_collapses_a_cell_line_break_to_a_space() -> None:
    """Markdown cannot break a line inside a cell, so a kept newline corrupts the grid.

    Measuring this is what set the rule: a cell holding ``"1\\r\\n2"`` rendered verbatim produced
    ``| 1`` on one line and ``2 | 3 |`` on the next, which silently turned a two-row table into a
    three-row one with a broken column count.
    """
    normalized = rendering.normalize_table(table([["head", "x"], ["1\r\n2", "3"]]))

    assert normalized.cells[1][0] == "1 2"


def test_normalize_table_strips_a_cells_own_padding() -> None:
    """A cell's leading and trailing whitespace is padding, not content.

    It matters because the JSON artifact publishes the cell verbatim: ``"  a"`` and ``"a"`` are
    two different values to a consumer, and Markdown renders them as the same cell. The indentation
    a *line* of block text may legitimately carry is not the same claim — inside a table cell there
    is no indentation to preserve.
    """
    normalized = rendering.normalize_table(table([["  padded  ", "x"]]))

    assert normalized.cells[0][0] == "padded"


def test_table_to_markdown_canonicalizes_a_raw_table_it_is_handed() -> None:
    """Called directly, it must repair the grid rather than rely on its caller having done so.

    Adding the line-break rule to :func:`process_tables` alone would have left this path open: a
    caller with a raw engine record would get a rendering whose row count had changed. The mutation
    that removed the internal normalization survived an earlier version of this suite, because
    every test reached this function through ``process_tables``, which normalizes first.
    """
    raw = table([["head", "x"], ["1\r\n2", "3"]])

    lines = rows_of(rendering.table_to_markdown(raw))

    assert len(lines) == 3, f"the row count changed: {lines}"
    assert len({line.count("|") for line in lines}) == 1, f"ragged: {lines}"
    assert raw.cells[1][0] == "1\r\n2", "the input was mutated"


def test_a_cell_line_break_cannot_change_the_row_count() -> None:
    """The consequence of the rule above, asserted on the rendering rather than the cell.

    Every line of a Markdown table has the same number of pipes. A cell that split its row would
    break that, and a reader counting columns would see a table that does not exist.
    """
    name, content = rendering.process_tables([table([["head", "x"], ["1\r\n2", "3"]])])[
        0
    ]

    assert name == "table_001.md"
    lines = rows_of(content)
    assert len(lines) == 3, f"the row count changed: {lines}"
    assert len({line.count("|") for line in lines}) == 1, f"ragged: {lines}"


def test_normalize_table_is_idempotent() -> None:
    """A canonical form is a fixed point, which is what makes it canonical."""
    once = rendering.normalize_table(table([["a\x00b", "1\r\n2"]]))

    assert rendering.normalize_table(once) == once


def test_normalize_table_does_not_mutate_its_input() -> None:
    """The record is frozen, so this is about not editing the caller's list in place."""
    original = table([["a\x00b"]])
    before = [list(row) for row in original.cells]

    rendering.normalize_table(original)

    assert original.cells == before


def test_normalize_table_keeps_the_identifier_index_and_bbox() -> None:
    """Canonicalization is about the content, not the provenance."""
    original = TableResult(
        table_id="table_007",
        index=7,
        markdown="",
        bbox=(1.0, 2.0, 3.0, 4.0),
        cells=[["a"]],
    )

    normalized = rendering.normalize_table(original)

    assert normalized.table_id == "table_007"
    assert normalized.index == 7
    assert normalized.bbox == (1.0, 2.0, 3.0, 4.0)


# ======================================================================================
# table_to_markdown / table_to_json
# ======================================================================================


def test_markdown_pads_a_ragged_grid_to_its_widest_row() -> None:
    """A Markdown table needs a rectangular body; a short row breaks every renderer."""
    rendered = rendering.table_to_markdown(table([["a", "b", "c"], ["d"], ["e", "f"]]))

    widths = {line.count("|") for line in rows_of(rendered)}

    assert len(widths) == 1, f"ragged rendering: {rendered!r}"


def test_markdown_carries_a_divider_row_after_the_header() -> None:
    """Without it the first row is not a header and the table is not a table."""
    lines = rows_of(rendering.table_to_markdown(table([["a", "b"], ["1", "2"]])))

    assert set(lines[1].replace("|", "").replace(" ", "")) == {"-"}


def test_table_to_json_names_every_field_explicitly() -> None:
    """The object is a schema other tools read, so its keys are pinned rather than expanded."""
    payload = rendering.table_to_json(table([["a", "b"]]))

    assert set(payload) == {"table_id", "index", "bbox", "cells"}
    assert payload["table_id"] == "table_001"
    assert payload["cells"] == [["a", "b"]]


def test_table_to_json_serializes_the_canonical_cells_not_the_raw_ones() -> None:
    """The function hands out the repaired grid, so a JSON writer cannot publish the raw one."""
    payload = rendering.table_to_json(table([["a\x00b", "1\r\n2"]]))

    assert payload["cells"] == [["ab", "1 2"]]


def test_table_to_json_reports_a_missing_box_as_none_not_as_a_zero_box() -> None:
    """``None`` is the contract's "not extracted"; a zero box is a real location."""
    assert rendering.table_to_json(table([["a"]]))["bbox"] is None


@pytest.mark.parametrize("size", [1, 2, 5])
def test_a_square_grid_renders_n_rows_plus_a_divider(size: int) -> None:
    """The row arithmetic, over the sizes the criterion and the fixture use."""
    grid = [[f"c{r}{c}" for c in range(size)] for r in range(size)]

    lines = rows_of(rendering.table_to_markdown(table(grid)))

    assert len(lines) == size + 1, f"{size}x{size} rendered {len(lines)} lines"
