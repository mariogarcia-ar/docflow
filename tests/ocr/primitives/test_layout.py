"""Tests for deterministic normalization and reading order (``OCR-05``).

The two acceptance criteria are the spine of this module:

* normalization is **stable across runs** — the same image and options give identical blocks and
  reading order;
* the sorted output is **stable for equal tie-breaks**, given blocks in arbitrary order.

The second is the one that carries the weight, and it cannot be demonstrated by running the engine
twice: two conversions of a fixed build happen to agree (which was measured), so a two-run test
would pass even if the ordering depended entirely on the engine's iteration order. The tests that
prove the guarantee therefore **shuffle the input** and assert the output is unchanged.

The geometry tests are unit tests over hand-built boxes, because the conversion being asserted —
a ``BOTTOMLEFT`` pixel frame to a ``TOPLEFT`` unit frame — is arithmetic that a real extraction
only exercises at the corners it happens to have.
"""

from __future__ import annotations

import random

import pytest

from docflow.ocr.contracts import BlockResult, LayoutResult, TableResult
from docflow.ocr.primitives import layout
from tests.ocr.primitives.engine_corpus import convert, extracted_document

PAGE_WIDTH = 840.0
PAGE_HEIGHT = 1036.0


def block(
    identifier: str, box: tuple[float, float, float, float] | None
) -> BlockResult:
    """Return a hand-built block with a given box.

    Args:
        identifier: The block's identifier.
        box: Its box in the engine's pixel frame, or ``None``.

    Returns:
        The block.
    """
    return BlockResult(block_id=identifier, type="text", text="x", bbox=box, level=None)


def table(
    identifier: str, box: tuple[float, float, float, float] | None
) -> TableResult:
    """Return a hand-built table with a given box.

    Args:
        identifier: The table's identifier.
        box: Its box in the engine's pixel frame, or ``None``.

    Returns:
        The table.
    """
    return TableResult(
        table_id=identifier, index=1, markdown="", bbox=box, cells=[["a"]]
    )


# ======================================================================================
# Acceptance criterion 1 - normalization is stable across runs
# ======================================================================================


def test_two_runs_produce_identical_normalized_blocks_and_reading_order() -> None:
    """The acceptance criterion, stated directly.

    Both runs go through the whole pipeline — conversion included — rather than normalizing one
    extraction twice, because the criterion is about the *run* being reproducible, not about the
    normalizer being a pure function. It is the coarser claim and the one the plan makes.
    """
    first = convert()
    second = convert()

    blocks_a, tables_a, order_a = layout.preserve_reading_order(
        first.blocks, first.tables, first.layout.page_width, first.layout.page_height
    )
    blocks_b, tables_b, order_b = layout.preserve_reading_order(
        second.blocks,
        second.tables,
        second.layout.page_width,
        second.layout.page_height,
    )

    assert order_a == order_b
    assert [(b.block_id, b.type, b.text, b.bbox) for b in blocks_a] == [
        (b.block_id, b.type, b.text, b.bbox) for b in blocks_b
    ]
    assert [t.table_id for t in tables_a] == [t.table_id for t in tables_b]


def test_normalizing_the_same_extraction_twice_is_identical() -> None:
    """The narrower claim: the normalizer itself introduces no variation."""
    document = extracted_document()

    first = layout.preserve_reading_order(
        document.blocks, document.tables, PAGE_WIDTH, PAGE_HEIGHT
    )
    second = layout.preserve_reading_order(
        document.blocks, document.tables, PAGE_WIDTH, PAGE_HEIGHT
    )

    assert first == second


def test_normalizing_does_not_reach_into_the_engine_to_re_measure() -> None:
    """The normalizer is pure: same input records in, same records out, no second conversion.

    A normalizer that re-read a metric would be a second source of truth for it, and the artifact
    and the engine's own report could disagree.
    """
    document = extracted_document()
    blocks = list(document.blocks)
    tables = list(document.tables)

    layout.preserve_reading_order(blocks, tables, PAGE_WIDTH, PAGE_HEIGHT)

    assert blocks == document.blocks, "the input list was modified"
    assert tables == document.tables
    assert all(
        b.bbox == original.bbox
        for b, original in zip(blocks, document.blocks, strict=True)
    )


# ======================================================================================
# Acceptance criterion 2 - the order is a rule, not the engine's iteration order
# ======================================================================================


def test_shuffling_the_input_does_not_change_the_order() -> None:
    """The criterion's real content: the sort is a *rule*, not a stabilizer for one input order.

    Two conversions of a fixed build happen to agree — that was measured — so a two-run test would
    pass even if the ordering were nothing but the engine's iteration order. Shuffling the input is
    what distinguishes the two, and the seed is fixed so a failure is reproducible.
    """
    document = extracted_document()
    reference, _, reference_order = layout.preserve_reading_order(
        document.blocks, document.tables, PAGE_WIDTH, PAGE_HEIGHT
    )

    generator = random.Random(20260923)
    for _attempt in range(5):
        shuffled_blocks = list(document.blocks)
        shuffled_tables = list(document.tables)
        generator.shuffle(shuffled_blocks)
        generator.shuffle(shuffled_tables)

        ordered, _, order = layout.preserve_reading_order(
            shuffled_blocks, shuffled_tables, PAGE_WIDTH, PAGE_HEIGHT
        )

        assert order == reference_order
        assert ordered == reference


def test_equal_boxes_are_ordered_by_identifier_so_the_order_is_total() -> None:
    """The tie-break of last resort, on two items with *identical* geometry.

    Python's sort is stable, so without the identifier these two would keep whichever order they
    arrived in — which is the engine's iteration order, the one thing that must not reach the
    artifact.

    The identifiers differ in the **letter** part, not the number, and that is deliberate: a first
    version of this test used ``block_001`` and ``block_002``, whose numeric suffixes broke the tie
    by themselves, so deleting the identifier from the sort key left the test green. Identifiers
    this processor mints are ``block_001``-style and always differ numerically, but a name from
    outside — a caller's own label, a future engine's reference — need not, and *that* is the input
    the identifier has to order. ``block_alpha``/``block_beta`` are the honest shapes for it.
    """
    same = (100.0, 900.0, 200.0, 880.0)
    forward = [block("block_beta", same), block("block_alpha", same)]
    backward = [block("block_alpha", same), block("block_beta", same)]

    _, _, first_order = layout.preserve_reading_order(
        forward, [], PAGE_WIDTH, PAGE_HEIGHT
    )
    _, _, second_order = layout.preserve_reading_order(
        backward, [], PAGE_WIDTH, PAGE_HEIGHT
    )

    assert first_order == second_order == ["block_alpha", "block_beta"]


def test_the_order_is_line_major_not_column_major() -> None:
    """A block on a lower line comes after both blocks on the line above, whatever their x.

    Ordering by ``left`` first would produce ``left, right, below`` on a two-column page: the
    classic reading-order defect. This is the assertion that keeps the key's first element the
    *top* coordinate.
    """
    left_top = block("block_001", (10.0, 900.0, 100.0, 880.0))
    right_top = block("block_002", (500.0, 900.0, 600.0, 880.0))
    below = block("block_003", (300.0, 800.0, 400.0, 780.0))

    _, _, order = layout.preserve_reading_order(
        [below, right_top, left_top], [], PAGE_WIDTH, PAGE_HEIGHT
    )

    assert order == ["block_001", "block_002", "block_003"]


def test_blocks_and_tables_are_ordered_as_one_sequence() -> None:
    """A table between two paragraphs is between them in the order.

    Two separate streams would lose that, and a consumer reconstructing the page from
    ``reading_order`` would place the table last.
    """
    top = block("block_001", (10.0, 950.0, 100.0, 930.0))
    middle_table = table("table_001", (10.0, 900.0, 300.0, 850.0))
    bottom = block("block_002", (10.0, 800.0, 100.0, 780.0))

    blocks, tables, order = layout.preserve_reading_order(
        [bottom, top], [middle_table], PAGE_WIDTH, PAGE_HEIGHT
    )

    assert order == ["block_001", "table_001", "block_002"]
    assert [b.block_id for b in blocks] == ["block_001", "block_002"]
    assert [t.table_id for t in tables] == ["table_001"]


def test_an_item_with_no_box_is_kept_and_sorts_last() -> None:
    """An unlocatable block stays in the output, after everything that has a position.

    Dropping it would be silent loss; sorting it first would push it above the page's title. It
    also keeps ``None``, because a zero box would read as "this block is at the top-left corner".
    """
    positioned = block("block_001", (10.0, 950.0, 100.0, 930.0))
    unpositioned = block("block_002", None)

    blocks, _, order = layout.preserve_reading_order(
        [unpositioned, positioned], [], PAGE_WIDTH, PAGE_HEIGHT
    )

    assert order == ["block_001", "block_002"]
    assert blocks[1].bbox is None, "the missing box was replaced with a substitute"


def test_a_box_touching_the_bottom_edge_still_sorts_before_an_unpositioned_item() -> (
    None
):
    """The boundary the sort prefix has to get right.

    A normalized top of exactly ``1.0`` — a box on the page's bottom edge — must not tie with an
    item that has no box at all. Both are reachable, and a prefix of ``1.0`` alone would leave
    them ordered by arrival.
    """
    edge = block("block_001", (10.0, 0.0, 100.0, 0.0))
    unpositioned = block("block_002", None)
    also_edge = block("block_003", (200.0, 0.0, 300.0, 0.0))

    blocks, _, order = layout.preserve_reading_order(
        [unpositioned, also_edge, edge], [], PAGE_WIDTH, PAGE_HEIGHT
    )

    assert order == ["block_001", "block_003", "block_002"]
    assert blocks[-1].bbox is None


def test_every_input_item_appears_exactly_once_in_the_output() -> None:
    """Reordering is not filtering: nothing is dropped and nothing is invented."""
    document = extracted_document()

    blocks, tables, order = layout.preserve_reading_order(
        document.blocks, document.tables, PAGE_WIDTH, PAGE_HEIGHT
    )

    assert len(blocks) == len(document.blocks)
    assert len(tables) == len(document.tables)
    assert len(order) == len(document.blocks) + len(document.tables)
    assert sorted(order) == sorted(
        [b.block_id for b in document.blocks] + [t.table_id for t in document.tables]
    )


# ======================================================================================
# The coordinate conversion
# ======================================================================================


def test_a_box_is_normalized_into_the_unit_frame() -> None:
    """Pixels become fractions of the page, on both axes."""
    assert layout.normalize_bbox(
        (84.0, 1036.0, 420.0, 518.0), PAGE_WIDTH, PAGE_HEIGHT
    ) == (
        0.1,
        0.0,
        0.5,
        0.5,
    )


def test_the_vertical_axis_is_flipped_because_the_engine_measures_from_the_bottom() -> (
    None
):
    """``BOTTOMLEFT`` in, ``TOPLEFT`` out — and the flip is observable.

    A box at the *top* of the page has a large ``top`` in the engine's frame and a small
    normalized ``top``. Skipping the flip is the mistake this test exists for, and it is invisible
    on a square page or a box that spans the whole height — which is why the page here is taller
    than it is wide.
    """
    engine_top_of_page = (0.0, 1000.0, 100.0, 950.0)
    engine_bottom_of_page = (0.0, 100.0, 100.0, 50.0)

    top = layout.normalize_bbox(engine_top_of_page, PAGE_WIDTH, PAGE_HEIGHT)
    bottom = layout.normalize_bbox(engine_bottom_of_page, PAGE_WIDTH, PAGE_HEIGHT)

    assert top[1] < bottom[1], "the vertical axis was not flipped"
    # A normalized box is `(left, top, right, bottom)`. The engine's `top` is the *upper* pixel row
    # measured from the bottom, so it is the larger of its two vertical values and becomes the
    # smaller normalized one: 1000 -> 36 and 950 -> 86 on a 1036-tall page.
    assert top[1] == pytest.approx((PAGE_HEIGHT - 1000.0) / PAGE_HEIGHT)
    assert top[3] == pytest.approx((PAGE_HEIGHT - 950.0) / PAGE_HEIGHT)
    assert bottom[1] == pytest.approx((PAGE_HEIGHT - 100.0) / PAGE_HEIGHT)
    assert bottom[3] == pytest.approx((PAGE_HEIGHT - 50.0) / PAGE_HEIGHT)


def test_the_result_always_has_top_above_bottom_and_left_before_right() -> None:
    """Regardless of how the engine ordered the corners.

    The engine reports ``top`` as the larger value, so an implementation that returned the
    coordinates in the order it received them would produce ``top > bottom`` — a box no consumer
    could compare or draw.
    """
    normalized = layout.normalize_bbox(
        (500.0, 900.0, 100.0, 800.0), PAGE_WIDTH, PAGE_HEIGHT
    )

    left, top, right, bottom = normalized
    assert left <= right
    assert top <= bottom


def test_normalizing_against_a_page_with_no_area_is_refused() -> None:
    """Refused rather than answered with zeroes.

    ``0.0`` is a legitimate coordinate, so returning it for every box would put every block in the
    page's corner *and look measured* — the plausible-wrong-value the image processor's crop
    primitive refuses for the same reason.
    """
    with pytest.raises(ValueError, match="no area"):
        layout.normalize_bbox((0.0, 10.0, 10.0, 0.0), 0.0, PAGE_HEIGHT)


def test_a_box_that_leaves_the_page_is_passed_through_not_clamped() -> None:
    """A tall block is not a clipped one, and clamping would erase the difference.

    The engine's boxes are inside the page; if one is not, that is a fact worth keeping rather than
    a value to quietly correct.
    """
    oversized = layout.normalize_bbox(
        (-100.0, 1200.0, 900.0, -50.0), PAGE_WIDTH, PAGE_HEIGHT
    )

    assert oversized[0] < 0.0
    assert oversized[2] > 1.0


def test_the_layout_becomes_a_unit_page_with_every_region_normalized() -> None:
    """The page becomes the unit square, so the pixel size is not applied twice.

    ``normalize_layout`` reports the frame the boxes are now in.
    """
    engine_layout = LayoutResult(
        page_width=PAGE_WIDTH,
        page_height=PAGE_HEIGHT,
        region_bboxes=[(0.0, 1036.0, 840.0, 0.0), (84.0, 518.0, 420.0, 259.0)],
    )

    normalized = layout.normalize_layout(engine_layout)

    assert (normalized.page_width, normalized.page_height) == (1.0, 1.0)
    assert normalized.region_bboxes[0] == (0.0, 0.0, 1.0, 1.0)
    assert normalized.region_bboxes[1] == pytest.approx((0.1, 0.5, 0.5, 0.75))


def test_normalize_layout_keeps_every_region_in_order_and_count() -> None:
    """The regions are mapped, not filtered or reordered."""
    engine_layout = LayoutResult(
        page_width=PAGE_WIDTH,
        page_height=PAGE_HEIGHT,
        region_bboxes=[(10.0, 100.0, 20.0, 90.0), (30.0, 200.0, 40.0, 190.0)],
    )

    normalized = layout.normalize_layout(engine_layout)

    assert len(normalized.region_bboxes) == 2
    assert normalized.region_bboxes[0][0] < normalized.region_bboxes[1][0]


def test_the_real_extraction_normalizes_into_the_unit_frame() -> None:
    """The conversion's arithmetic, on the boxes a real page produced.

    The unit tests above prove the formula; this one proves it against the numbers the engine
    actually emits, which is where an origin the documentation got wrong would show up.
    """
    document = extracted_document()

    normalized = layout.normalize_layout(document.layout)

    assert (normalized.page_width, normalized.page_height) == (1.0, 1.0)
    assert normalized.region_bboxes
    for left, top, right, bottom in normalized.region_bboxes:
        assert 0.0 <= left <= 1.0, (left, top, right, bottom)
        assert 0.0 <= top <= 1.0
        assert 0.0 <= right <= 1.0
        assert 0.0 <= bottom <= 1.0
        assert top <= bottom


def test_the_real_reading_order_puts_the_heading_first() -> None:
    """The fixture's own title is the topmost block, so it leads the order.

    A sanity check with teeth: an ordering that ignored the vertical axis would put whichever
    block happened to be furthest left first, and on this page that is not the heading.
    """
    document = extracted_document()

    blocks, _, order = layout.preserve_reading_order(
        document.blocks, document.tables, PAGE_WIDTH, PAGE_HEIGHT
    )

    titles = [b.block_id for b in blocks if b.type == "title"]
    assert titles, "the fixture produced no title"
    assert order[0] == titles[0]


# ======================================================================================
# The helpers
# ======================================================================================


def test_count_blocks_counts_what_it_is_given() -> None:
    """Including zero, which is what an empty extraction has."""
    assert layout.count_blocks([]) == 0
    assert layout.count_blocks([block("block_001", None)]) == 1


def test_text_density_is_characters_per_unit_of_area() -> None:
    """Against a normalized page the area is 1.0, so the density is the character count."""
    assert layout.calculate_ocr_text_density(500, 1.0, 1.0) == 500.0
    assert layout.calculate_ocr_text_density(840, 840.0, 1036.0) == pytest.approx(
        1 / 1036.0
    )


def test_text_density_against_a_page_with_no_area_is_zero_not_an_error() -> None:
    """``0.0`` rather than a refusal: the caller is ``OCR-08``, which reports rather than validates.

    And zero is the true answer — a page with no area holds zero characters per unit area — so this
    is a measurement rather than a stand-in.
    """
    assert layout.calculate_ocr_text_density(100, 0.0, 1036.0) == 0.0
    assert layout.calculate_ocr_text_density(100, 840.0, 0.0) == 0.0


def test_the_module_declares_the_frame_it_normalizes_into() -> None:
    """The convention is published, not implied.

    A normalized box without its origin is ambiguous, and the engine's origin is the other one, so
    a consumer reading ``document.json`` has to be able to find out which frame it is in.
    """
    assert layout.COORDINATE_REFERENCE == "TOPLEFT"
    assert layout.COORDINATE_RANGE == (0.0, 1.0)
