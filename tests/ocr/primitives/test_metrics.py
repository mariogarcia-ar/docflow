"""Tests for the content metrics (``OCR-08``).

The two acceptance criteria are the spine of this module:

* given ``fixtures/ocr_blank.png``, ``empty`` is true and ``characters == 0`` from a **real
  measurement**;
* given the prepared text-and-table fixture, ``structure_detected`` is true and ``blocks > 0``.

Both run the engine for real over the committed fixtures, because "from a real measurement" is the
criterion's own wording — a hand-built empty document would assert that ``is_ocr_empty("")`` is
true, which is ``OCR-06``'s test and not this one. What the engine does with a blank page was
measured before anything was written against it: Docling returns an *empty document* rather than
raising, so the zeroes below come from a conversion that ran and found nothing.

A third group is the unit-level one: a hand-built document exercises the fields the two fixtures
cannot distinguish between, such as the difference between a paragraph block and a structural one.
"""

from __future__ import annotations

import typing

import pytest

from docflow.ocr.contracts import (
    BlockResult,
    LayoutResult,
    OCRBlockType,
    OCRDocument,
)
from docflow.ocr.primitives import analyze
from tests.ocr.primitives.engine_corpus import blank_document, extracted_document

PAGE_WIDTH = 840.0
PAGE_HEIGHT = 1036.0


def document(
    text: str = "",
    blocks: list[BlockResult] | None = None,
    paragraphs: list[str] | None = None,
    tables: list[object] | None = None,
) -> OCRDocument:
    """Return a hand-built document.

    Every field is named at the call site rather than defaulted invisibly, so a test that means "a
    document with one title block and nothing else" says so.

    Args:
        text: The document's text.
        blocks: Its blocks.
        paragraphs: Its paragraph texts.
        tables: Its tables.

    Returns:
        The document.
    """
    return OCRDocument(
        text=text,
        paragraphs=paragraphs if paragraphs is not None else [],
        titles=[],
        blocks=blocks if blocks is not None else [],
        tables=tables if tables is not None else [],
        layout=LayoutResult(
            page_width=PAGE_WIDTH, page_height=PAGE_HEIGHT, region_bboxes=[]
        ),
        reading_order=[],
        metadata={},
    )


def block(identifier: str, block_type: str, text: str = "x") -> BlockResult:
    """Return a hand-built block.

    Args:
        identifier: The block's identifier.
        block_type: Its structural role.
        text: Its text.

    Returns:
        The block.
    """
    return BlockResult(
        block_id=identifier, type=block_type, text=text, bbox=None, level=None
    )


# ======================================================================================
# Criterion 1 - the blank fixture measures zero, from a real conversion
# ======================================================================================


def test_a_blank_page_reports_empty_with_zero_characters() -> None:
    """The criterion, against a real conversion of ``ocr_blank.png``.

    Docling returns an empty document for a pure white page rather than raising, which is what
    makes this a measurement: the engine ran, read the page, and found nothing.
    """
    metrics = analyze.analyze_ocr_result(blank_document())

    assert metrics.empty is True
    assert metrics.characters == 0


def test_a_blank_page_reports_every_count_as_zero() -> None:
    """No field is filled in with a plausible non-zero value.

    ``text_density`` is the one worth naming: ``0 / area`` is ``0.0``, and a function that guarded
    against division instead of dividing would have to invent an answer for a page that has one.
    """
    metrics = analyze.analyze_ocr_result(blank_document())

    assert metrics.words == 0
    assert metrics.blocks == 0
    assert metrics.tables == 0
    assert metrics.paragraphs == 0
    assert metrics.text_density == 0.0


def test_a_blank_page_has_no_structure_to_report() -> None:
    """The other side of criterion 2: nothing was recognised because there was nothing to recognise.

    A function that reported ``structure_detected`` from "did the pipeline run" rather than "was an
    element found" would say ``True`` here, and the flag would stop meaning anything.
    """
    assert analyze.analyze_ocr_result(blank_document()).structure_detected is False


def test_the_blank_fixture_really_is_blank_at_the_engine() -> None:
    """The measurement the criterion rests on, pinned separately.

    If Docling ever returned text for this page — a watermark, a form label, an artefact — then
    ``empty`` would be ``False`` and the failure should point here rather than at the metrics.
    """
    document_under_test = blank_document()

    assert document_under_test.text.strip() == ""
    assert not document_under_test.blocks
    assert not document_under_test.tables
    assert not document_under_test.reading_order


# ======================================================================================
# Criterion 2 - the prepared fixture reports structure and a block count
# ======================================================================================


def test_the_prepared_fixture_reports_structure_and_blocks() -> None:
    """The criterion, verbatim."""
    metrics = analyze.analyze_ocr_result(extracted_document())

    assert metrics.structure_detected is True
    assert metrics.blocks > 0


def test_the_prepared_fixture_is_not_empty_and_counts_its_text() -> None:
    """``empty`` must be ``False`` here for the flag to carry information.

    A function that always answered ``empty=True`` would pass criterion 1 and be useless.
    """
    metrics = analyze.analyze_ocr_result(extracted_document())

    assert metrics.empty is False
    assert metrics.characters > 0
    assert metrics.words > 0


def test_the_fixture_is_measured_against_its_own_size() -> None:
    """The density's denominator, from the page the engine reported.

    Asserted rather than left implicit because the fixture path is the only place the two fixtures'
    page sizes agreeing is observable — a blank page of a different size would make the two density
    figures incomparable for a reason that has nothing to do with content.
    """
    content = extracted_document()
    metrics = analyze.analyze_ocr_result(content)

    assert content.layout.page_width == PAGE_WIDTH
    assert content.layout.page_height == PAGE_HEIGHT
    assert metrics.text_density == pytest.approx(
        metrics.characters / (PAGE_WIDTH * PAGE_HEIGHT)
    )


# ======================================================================================
# The fields the two fixtures cannot separate
# ======================================================================================


def test_the_counts_come_from_the_document_they_are_handed() -> None:
    """Each count traces to its own field, so a function reading the wrong one is visible.

    The fields are given deliberately different values, which the fixtures do not: on the real
    document the block count (19) and the paragraph count (15) differ, but ``tables`` is 1 and a
    swapped field could still be 0 here and 1 there.
    """
    metrics = analyze.analyze_ocr_result(
        document(
            text="one two three",
            blocks=[
                block("block_001", "text"),
                block("block_002", "text"),
                block("block_003", "text"),
            ],
            paragraphs=["one", "two"],
        )
    )

    assert metrics.characters == 13
    assert metrics.words == 3
    assert metrics.blocks == 3
    assert metrics.paragraphs == 2
    assert metrics.tables == 0


def test_characters_count_the_whole_text_including_whitespace() -> None:
    """``count_ocr_characters`` is a length, not a count of visible glyphs."""
    metrics = analyze.analyze_ocr_result(document(text="a b\nc"))

    assert metrics.characters == 5
    assert metrics.words == 3


def test_whitespace_only_text_is_empty_but_still_counted() -> None:
    """``empty`` and ``characters`` answer different questions and must both be reported.

    ``characters > 0`` with ``empty is True`` is a real state — a page whose engine returned spaces
    — and a function that zeroed the count to agree with the flag would be hiding the measurement.
    """
    metrics = analyze.analyze_ocr_result(document(text="   \n\t "))

    assert metrics.empty is True
    # 3 spaces, a newline, a tab, a space: six characters, and every one of them is whitespace.
    assert metrics.characters == 6


@pytest.mark.parametrize("block_type", ["title", "list", "caption", "figure", "table"])
def test_a_structural_block_type_sets_structure_detected(block_type: str) -> None:
    """Every type that claims how the document is organised counts as recognised structure."""
    metrics = analyze.analyze_ocr_result(
        document(blocks=[block("block_001", block_type)])
    )

    assert metrics.structure_detected is True


@pytest.mark.parametrize("block_type", ["text", "paragraph", "other", ""])
def test_a_non_structural_block_type_does_not_set_structure_detected(
    block_type: str,
) -> None:
    """Plain prose is not structure, and neither is an unmapped label.

    ``other`` is the case that matters: it is what the label mapping produces for a label it does
    not know, so treating it as structure would report a recognised element everywhere the
    processor understood *less* than usual. The empty string is not a contract value and is
    included so an unknown type fails toward "not structure" rather than raising.
    """
    metrics = analyze.analyze_ocr_result(
        document(text="some words", blocks=[block("block_001", block_type)])
    )

    assert metrics.structure_detected is False


def test_a_detected_table_alone_is_enough_structure() -> None:
    """A table's identifier lists it in ``reading_order`` rather than in ``blocks``.

    So a document whose only structural element is a table has no block to inspect, and a function
    that looked only at block types would report ``False`` for a page with a grid on it.
    """
    metrics = analyze.analyze_ocr_result(
        document(
            text="word",
            blocks=[block("block_001", "text")],
            tables=[object()],
        )
    )

    assert metrics.structure_detected is True
    assert metrics.tables == 1


def test_text_with_no_blocks_reports_no_structure() -> None:
    """Text alone is a run of characters, not an organisation claim."""
    metrics = analyze.analyze_ocr_result(document(text="just some words here"))

    assert metrics.structure_detected is False


def test_the_metrics_are_computed_in_the_frame_the_layout_arrives_in() -> None:
    """The density's frame is the layout's, and today that is the engine's pixels.

    ``OCR-05`` built the primitives that normalize geometry and ``OCR-11`` is the task that runs
    them, so until then the page area is in pixels. The figure is a true measurement — comparable
    between runs of this pipeline — and this test records *which* frame it is in so the number
    cannot be read as comparable to a normalized one.
    """
    page = document(text="abcd")

    metrics = analyze.analyze_ocr_result(page)

    assert page.layout.page_width > 1.0, "the layout is no longer in pixels"
    assert metrics.text_density == pytest.approx(4 / (PAGE_WIDTH * PAGE_HEIGHT))
    assert metrics.text_density < 1.0


def test_analyzing_does_not_modify_the_document() -> None:
    """The metrics are a snapshot; nothing about the extraction changes to produce them."""
    content = extracted_document()
    before = (
        content.text,
        len(content.blocks),
        len(content.tables),
        list(content.reading_order),
    )

    analyze.analyze_ocr_result(content)

    after = (
        content.text,
        len(content.blocks),
        len(content.tables),
        list(content.reading_order),
    )
    assert before == after


def test_analyzing_is_deterministic() -> None:
    """One document, one answer: the metrics are not a sample of anything."""
    content = extracted_document()

    assert analyze.analyze_ocr_result(content) == analyze.analyze_ocr_result(content)


def test_the_structural_types_are_the_contracts_own() -> None:
    """Every type in the set is a value the contract declares.

    A typo in the set would silently make a real structural block count as prose, and nothing else
    in the suite would notice: the parametrized tests above assert the types they name, not that the
    set contains only those.
    """
    declared = set(typing.get_args(OCRBlockType))

    assert declared >= analyze.STRUCTURAL_BLOCK_TYPES
