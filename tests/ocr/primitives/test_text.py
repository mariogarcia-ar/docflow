"""Tests for text measurement and canonicalization (``OCR-06``).

The two halves are asserted separately because they answer different failure modes. The
measurements are arithmetic and are checked against strings whose counts are obvious by
inspection. The canonicalization is checked against the *specific* artifacts an OCR pass leaves
behind — a stray carriage return, an invisible control character, a line's trailing padding — since
each of those is a way two runs over one page could differ in bytes while agreeing about content.

``is_ocr_empty`` lives here although the stub skeleton attributed it to ``OCR-08``: ``OCR-06``'s
scope names it, and ``OCR-08`` reads it rather than owning it.
"""

from __future__ import annotations

import unicodedata

import pytest

from docflow.ocr.primitives import text

# ======================================================================================
# Measurement
# ======================================================================================


def test_character_count_is_the_length_of_the_text() -> None:
    """Including whitespace, which is content in a text artifact."""
    assert text.count_ocr_characters("") == 0
    assert text.count_ocr_characters("abc") == 3
    assert text.count_ocr_characters("a b\n") == 4


def test_character_count_is_zero_for_an_empty_extraction_not_a_substitute() -> None:
    """``0`` here is measured, not a placeholder.

    A page that yielded nothing holds zero characters, so the figure ``OCR-08`` reports came from
    the text rather than standing in for a missing one.
    """
    assert text.count_ocr_characters("") == 0
    assert text.count_ocr_characters(" ") == 1


def test_word_count_splits_on_whitespace_runs() -> None:
    """Consecutive spaces and tabs are one separator, not several."""
    assert text.count_ocr_words("") == 0
    assert text.count_ocr_words("one") == 1
    assert text.count_ocr_words("one two") == 2
    assert text.count_ocr_words("one   two\t\tthree") == 3


def test_a_wrapped_paragraph_counts_the_same_as_an_unwrapped_one() -> None:
    """The reason the split is on whitespace runs rather than on spaces.

    An engine that wraps at a column inserts a newline per line. Counting spaces would make the
    same paragraph measure differently depending on the page width it happened to be wrapped to.
    """
    wrapped = "the quick brown\nfox jumps over"
    unwrapped = "the quick brown fox jumps over"

    assert text.count_ocr_words(wrapped) == text.count_ocr_words(unwrapped) == 6


def test_leading_and_trailing_whitespace_does_not_add_words() -> None:
    """``str.split`` drops empty tokens, so padding is not counted as content."""
    assert text.count_ocr_words("  one two  ") == 2
    assert text.count_ocr_words("\n\n") == 0


def test_measuring_does_not_modify_what_it_measures() -> None:
    """A metric that repaired its input would report a figure for text the artifact does
    not hold.
    """
    raw = "  padded \r\n text  "

    assert text.count_ocr_characters(raw) == len(raw)
    # Two words, not three: the `\r\n` pair is one whitespace run, so it separates rather than
    # adding a token of its own.
    assert text.count_ocr_words(raw) == 2


# ======================================================================================
# Cleaning
# ======================================================================================


def test_carriage_returns_become_newlines() -> None:
    """One line ending in the artifact, not two characters depending on the engine's platform."""
    assert text.clean_ocr_text("a\r\nb") == "a\nb"
    assert text.clean_ocr_text("a\rb") == "a\nb"


def test_invisible_control_characters_are_removed() -> None:
    """They are bytes no consumer can account for and no reader can see.

    ``\\x00`` is a control character and ``\\u200b`` a zero-width space; both reach an artifact from
    an engine's own layout bookkeeping rather than from the page.
    """
    assert text.clean_ocr_text("a\x00b") == "ab"
    assert text.clean_ocr_text("a\u200bb") == "ab"
    assert text.clean_ocr_text("\ufeffa") == "a"


def test_tab_and_newline_survive_the_control_character_sweep() -> None:
    """The two the engine uses for layout, and the reason the sweep exempts them explicitly.

    Both are in Unicode's control category, so a filter written on the category alone would delete
    every line break in the document.
    """
    assert text.clean_ocr_text("a\tb") == "a\tb"
    assert text.clean_ocr_text("a\nb") == "a\nb"


def test_trailing_whitespace_is_removed_from_each_line() -> None:
    """A line's invisible padding is the difference two runs could show."""
    assert text.clean_ocr_text("a   \nb\t\n") == "a\nb"


def test_leading_indentation_is_kept() -> None:
    """It is part of what the page looks like, and Markdown reads it.

    Four leading spaces make a code block, so stripping indentation would change what the document
    says — that is a transformation, not a canonicalization.
    """
    assert text.clean_ocr_text("    indented") == "    indented"
    assert text.clean_ocr_text("plain\n    indented") == "plain\n    indented"


def test_runs_of_blank_lines_collapse_to_one() -> None:
    """One newline ends a line and two separate blocks; beyond that the space is the
    engine's own.
    """
    assert text.clean_ocr_text("a\n\n\n\nb") == "a\n\nb"
    assert text.clean_ocr_text("a\n\nb") == "a\n\nb"


def test_the_result_carries_no_leading_or_trailing_newline() -> None:
    """The terminator a file needs belongs to the writer, not to the text.

    A cleaned string that kept one would make a caller joining two fragments reason about a
    separator it never asked for, and the artifact builder's own newline would then be a second
    one.
    """
    assert text.clean_ocr_text("\n\na\n\n") == "a"
    assert text.clean_ocr_text("\n") == ""


def test_cleaning_an_empty_string_yields_an_empty_string() -> None:
    """No stand-in, and no newline invented for a document with no content."""
    assert text.clean_ocr_text("") == ""
    assert text.clean_ocr_text("   \n\t ") == ""


# ======================================================================================
# Canonicalization
# ======================================================================================


def test_normalizing_composes_to_unicode_nfc() -> None:
    """The reason the two spellings of one accented character stop being two spellings.

    ``e`` followed by a combining acute and the precomposed ``é`` look identical and compare
    unequal, so an artifact could differ from another in bytes alone.
    """
    decomposed = "e\u0301"
    assert decomposed != "\u00e9"

    assert text.normalize_ocr_text(decomposed) == "\u00e9"
    assert unicodedata.is_normalized("NFC", text.normalize_ocr_text(decomposed))


def test_normalizing_cleans_first() -> None:
    """The order is load-bearing, and this is the case that shows it.

    Cleaning *removes* characters, and a removed combining mark can leave a sequence that
    normalizes differently than the raw text would have. Normalizing first would produce a form a
    second pass could still change.
    """
    raw = "e\x00\u0301"

    assert text.normalize_ocr_text(raw) == "\u00e9"


def test_normalizing_is_idempotent() -> None:
    """A canonical form is a fixed point, which is what makes it canonical."""
    once = text.normalize_ocr_text("  A\r\n\r\n\r\nB e\u0301  ")

    assert text.normalize_ocr_text(once) == once


def test_normalizing_an_empty_string_yields_an_empty_string() -> None:
    """The empty artifact path, which ``OCR-09`` reads to decide between ``EMPTY`` and ``VALID``."""
    assert text.normalize_ocr_text("") == ""
    assert text.normalize_ocr_text("\x00 \r\n") == ""


# ======================================================================================
# Emptiness
# ======================================================================================


def test_whitespace_only_text_is_empty() -> None:
    """Calling a blank page content would make ``OCR-09``'s ``EMPTY`` status unreachable for
    exactly the input it exists to describe."""
    assert text.is_ocr_empty("")
    assert text.is_ocr_empty("   ")
    assert text.is_ocr_empty("\n\t\r\n")


def test_a_single_visible_character_is_not_empty() -> None:
    """The boundary the other way: one character is content, however little of it there is."""
    assert not text.is_ocr_empty("a")
    assert not text.is_ocr_empty("  . ")
    assert not text.is_ocr_empty("\n1\n")


@pytest.mark.parametrize("character", ["\u00a0", "\u2007", "\u202f"])
def test_unicode_spaces_do_not_make_text_look_non_empty(character: str) -> None:
    """A no-break space and its relatives are whitespace to ``str.split`` and to a reader.

    An engine emitting one for a blank page would otherwise produce an artifact that reads as
    content while holding nothing.
    """
    assert text.is_ocr_empty(character)
    assert text.count_ocr_words(character) == 0
