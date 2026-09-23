"""Tests for Markdown canonicalization and block merging (``OCR-06``).

``normalize_markdown`` is the same claim ``normalize_ocr_text`` makes one level up: two runs over
one page must produce a byte-identical ``document.md``, so a difference between two artifacts means
a difference in the extraction rather than in how a renderer spaced its blocks. The tests therefore
attack the specific ways Markdown output can differ without meaning anything different.

``merge_ocr_blocks`` is checked against hand-built blocks, because the question it answers — does a
heading render as a heading, does an empty block contribute anything — is about the mapping and not
about the engine. The fixture-based checks live in the export suite, where a real document exists.
"""

from __future__ import annotations

import pytest

from docflow.ocr.contracts import BlockResult
from docflow.ocr.primitives import rendering


def block(
    identifier: str,
    block_type: str,
    content: str,
    level: int | None = None,
) -> BlockResult:
    """Return a hand-built block.

    Args:
        identifier: The block's identifier.
        block_type: Its structural role.
        content: Its text.
        level: Its heading depth, for a title.

    Returns:
        The block.
    """
    return BlockResult(
        block_id=identifier, type=block_type, text=content, bbox=None, level=level
    )


# ======================================================================================
# normalize_markdown
# ======================================================================================


def test_trailing_whitespace_is_removed_from_each_line() -> None:
    """Only *two* trailing spaces mean a hard line break in Markdown.

    A renderer that emitted them by accident would be asserting a break the page does not have, and
    one that emitted a single one would produce a file diffing against an otherwise identical run.
    """
    assert rendering.normalize_markdown("a   \nb\t\n") == "a\nb"


def test_runs_of_blank_lines_collapse_to_one() -> None:
    """How many blank lines sit between blocks is the renderer's business, not the page's."""
    assert rendering.normalize_markdown("a\n\n\n\nb") == "a\n\nb"
    assert rendering.normalize_markdown("a\n\nb") == "a\n\nb"


def test_leading_indentation_is_kept_because_markdown_reads_it() -> None:
    """Four spaces make a code block, so stripping them would change what the document says."""
    assert rendering.normalize_markdown("    code") == "    code"
    assert rendering.normalize_markdown("text\n\n    code") == "text\n\n    code"


def test_the_result_carries_no_leading_or_trailing_newline() -> None:
    """The newline a file needs belongs to the writer."""
    assert rendering.normalize_markdown("\n\n# H\n\n") == "# H"


def test_tab_indentation_is_kept_too() -> None:
    """A tab is also Markdown indentation, and a sweep written for spaces alone would miss it."""
    assert rendering.normalize_markdown("\tcode") == "\tcode"


def test_invisible_characters_are_removed_from_markdown_as_well() -> None:
    """One path canonicalizes the characters in both artifacts, which is the point of composing."""
    assert rendering.normalize_markdown("a\x00b") == "ab"
    assert rendering.normalize_markdown("e\u0301") == "\u00e9"


def test_normalizing_markdown_is_idempotent() -> None:
    """A canonical form is a fixed point."""
    once = rendering.normalize_markdown("# H   \n\n\n\npara e\u0301  ")

    assert rendering.normalize_markdown(once) == once


def test_markdown_that_has_meaning_beyond_whitespace_is_untouched() -> None:
    """The canonicalizer must not rewrite the document, only its spacing.

    Pipes, quotes, list markers and emphasis all have meaning; a normalizer that "tidied" them
    would be a different document. This is the boundary that keeps the function a canonicalizer.
    """
    meaningful = (
        "| a | b |\n| --- | --- |\n| 1 | 2 |\n\n> quote\n\n- item *emph* **bold**"
    )

    assert rendering.normalize_markdown(meaningful) == meaningful


def test_normalizing_an_empty_string_yields_an_empty_string() -> None:
    """The empty artifact path, with no heading or placeholder invented for it."""
    assert rendering.normalize_markdown("") == ""
    assert rendering.normalize_markdown("\n\n   \n") == ""


# ======================================================================================
# merge_ocr_blocks
# ======================================================================================


def test_a_title_renders_as_a_heading_of_its_own_level() -> None:
    """The level comes from the block's own field, not from the text's leading hashes.

    Reading the text back to decide the rendering would make an extraction whose title happened to
    start with ``#`` render as a different heading than the same title without it.
    """
    assert (
        rendering.merge_ocr_blocks([block("b1", "title", "Heading", 2)]) == "## Heading"
    )
    assert (
        rendering.merge_ocr_blocks([block("b1", "title", "Heading", 1)]) == "# Heading"
    )


def test_a_title_with_no_level_renders_at_the_shallowest_heading() -> None:
    """``None`` means the engine did not report one, and level 1 is the honest reading of that.

    A missing depth is not a depth of zero, and ``"#".repeat(None)`` is not a heading at all.
    """
    assert (
        rendering.merge_ocr_blocks([block("b1", "title", "Heading", None)])
        == "# Heading"
    )


def test_a_heading_deeper_than_markdown_allows_is_clamped() -> None:
    """There is no seventh level, so ``#######`` would render as a paragraph with a stray ``#``."""
    assert (
        rendering.merge_ocr_blocks([block("b1", "title", "Deep", 9)]) == "###### Deep"
    )
    assert rendering.merge_ocr_blocks([block("b1", "title", "Zero", 0)]) == "# Zero"


def test_a_list_block_renders_as_a_list_item() -> None:
    """The marker matches the block's declared type rather than its text."""
    assert rendering.merge_ocr_blocks([block("b1", "list", "one")]) == "- one"


def test_a_paragraph_renders_as_plain_text() -> None:
    """No marker invented for the most common block type."""
    assert (
        rendering.merge_ocr_blocks([block("b1", "paragraph", "just text")])
        == "just text"
    )
    assert rendering.merge_ocr_blocks([block("b1", "text", "just text")]) == "just text"


def test_blocks_are_rendered_in_the_order_given_and_not_resorted() -> None:
    """Reading order is ``preserve_reading_order``'s result and the caller already has it.

    A second sort here would be a second definition of the order, and the two would disagree the
    moment either changed. These blocks are deliberately out of any geometric order.
    """
    blocks = [
        block("b2", "text", "second"),
        block("b1", "text", "first"),
        block("b3", "text", "third"),
    ]

    assert rendering.merge_ocr_blocks(blocks) == "second\n\nfirst\n\nthird"


def test_a_block_with_no_text_contributes_nothing() -> None:
    """Not an empty line and not a placeholder: a block with nothing to say says nothing."""
    blocks = [
        block("b1", "text", "before"),
        block("b2", "paragraph", "   "),
        block("b3", "text", "after"),
    ]

    assert rendering.merge_ocr_blocks(blocks) == "before\n\nafter"


def test_an_empty_block_list_renders_as_an_empty_string() -> None:
    """An extraction with no blocks is data, not a failure, and ``""`` is the truthful rendering."""
    assert rendering.merge_ocr_blocks([]) == ""
    assert rendering.merge_ocr_blocks([block("b1", "text", "")]) == ""


def test_blocks_are_separated_by_exactly_one_blank_line() -> None:
    """The separator, pinned: one newline would join two paragraphs into one."""
    assert (
        rendering.merge_ocr_blocks(
            [block("b1", "text", "one"), block("b2", "text", "two")]
        )
        == "one\n\ntwo"
    )


def test_a_block_whose_text_carries_its_own_blank_lines_is_canonicalized() -> None:
    """A block is not a license to bypass the canonical form: the whole rendering goes
    through it.
    """
    blocks = [block("b1", "text", "one\r\n\r\n\r\n\r\ntwo")]

    assert rendering.merge_ocr_blocks(blocks) == "one\n\ntwo"


def test_merging_is_idempotent_through_the_canonical_form() -> None:
    """Re-rendering the output's own blocks yields the same string, so a round trip is stable."""
    blocks = [block("b1", "title", "H", 2), block("b2", "text", "body")]

    first = rendering.merge_ocr_blocks(blocks)

    assert rendering.normalize_markdown(first) == first


@pytest.mark.parametrize(
    "block_type",
    ["text", "title", "paragraph", "list", "caption", "figure", "other"],
)
def test_every_block_type_the_contract_declares_renders_something(
    block_type: str,
) -> None:
    """No declared type may fall through to an empty rendering.

    ``table`` is excluded because a table's Markdown comes from its cells rather than from a text
    field; the other seven all carry text, and a type that silently rendered nothing would drop
    content from the artifact.
    """
    rendered = rendering.merge_ocr_blocks([block("b1", block_type, "content")])

    assert rendered.strip(), f"{block_type} rendered nothing"
    assert "content" in rendered
