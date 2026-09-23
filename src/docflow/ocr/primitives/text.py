"""Text measurement, cleaning and canonicalization (``OCR-06``).

Measurements and canonicalization only: nothing here decides that text is good, missing or worth
keeping. Two jobs, and they answer different failure modes:

* **Measurement.** ``count_ocr_characters`` and ``count_ocr_words`` are pure counts, so ``OCR-08``
  can report a figure that came from the text rather than from a guess. Neither cleans its input:
  a metric that silently repaired the text it measured would report a number for content the
  artifact does not hold.
* **Canonicalization.** ``clean_ocr_text`` strips what an OCR pass leaves behind and
  ``normalize_ocr_text`` puts the result into one fixed form, so two runs over the same page
  produce byte-identical artifacts. That is what makes the determinism claim checkable rather than
  merely asserted - a difference between two ``text.txt`` files then means a difference in the
  extraction, never in the engine's trailing whitespace.

The five names are §3.4's *Text* group, name for name. ``is_ocr_empty`` is the one the stub
skeleton attributed to ``OCR-08``; ``OCR-06``'s scope names it, and it is implemented here because
``OCR-08`` *reads* it while computing ``OCRMetrics.empty`` rather than owning it.
"""

from __future__ import annotations

import re
import unicodedata

_CONTROL_CATEGORY = "C"
"""The Unicode category prefix of a control, format or surrogate character.

Everything in this category is invisible to a reader, so keeping it would put bytes in the artifact
no consumer can account for. Tab and newline belong to the category and are kept explicitly,
because they are the two an OCR pass uses for layout.
"""

_BLANK_LINE_RUN = re.compile(r"\n{3,}")
"""Three or more newlines in a row, collapsed to one blank line.

One newline ends a line and two separate blocks. Beyond that the space is the engine's own layout
bookkeeping rather than a break the page contains, and it would make two runs of the same page
differ in whitespace alone.
"""


def count_ocr_characters(text: str) -> int:
    """Count the characters.

    Args:
        text: The text to measure.

    Returns:
        The character count. ``0`` for empty text, which is a true measurement rather than a
        stand-in: a page that yielded nothing holds zero characters.
    """
    return len(text)


def count_ocr_words(text: str) -> int:
    """Count the words.

    Split on any whitespace run, so that a paragraph the engine wrapped at a column counts the same
    as the same paragraph on one line. Counting ``" "`` occurrences instead would inflate the
    figure with every newline the engine inserted.

    Args:
        text: The text to measure.

    Returns:
        The word count.
    """
    return len(text.split())


def clean_ocr_text(text: str) -> str:
    """Strip the artifacts an OCR pass leaves behind.

    Four steps, in this order, because each one exposes the next: the line endings are canonicalized
    first (a ``\\r\\n`` pair would otherwise reach the split as one ending plus one stray control
    character), then the invisible characters go, then the whitespace the engine left at the end of
    each line, then the runs of blank lines that are left over.

    **Leading indentation is kept.** It is part of what the page looks like and a consumer may want
    it; the only claim here is that a line carries no invisible padding at its end.

    Args:
        text: The raw text.

    Returns:
        The cleaned text, with no leading or trailing newline. The terminator a file needs is the
        writer's, so a caller joining fragments does not have to reason about one it did not ask
        for.
    """
    canonical = text.replace("\r\n", "\n").replace("\r", "\n")
    visible = "".join(
        character
        for character in canonical
        if character in "\n\t"
        or unicodedata.category(character)[0] != _CONTROL_CATEGORY
    )
    trimmed = "\n".join(line.rstrip() for line in visible.split("\n"))
    return _BLANK_LINE_RUN.sub("\n\n", trimmed).strip("\n")


def normalize_ocr_text(text: str) -> str:
    """Put text into its canonical form.

    Cleaning first, then Unicode NFC, and the order is why this composes instead of reimplementing:
    cleaning *removes* characters, and dropping a combining mark can leave a sequence that
    normalizes to a different code point than the raw text would have. Normalizing first would
    produce a "canonical" form a second pass could still change.

    Args:
        text: The text to canonicalize.

    Returns:
        The canonical form, with no leading or trailing newline.
    """
    return unicodedata.normalize("NFC", clean_ocr_text(text))


def is_ocr_empty(text: str) -> bool:
    """Report whether an extraction produced no content.

    Whitespace-only counts as empty: a page the engine answered with a blank line yielded nothing,
    and calling that content would make ``OCR-09``'s ``EMPTY`` status unreachable for exactly the
    input it exists to describe.

    Args:
        text: The text to test.

    Returns:
        ``True`` when the text holds nothing but whitespace.
    """
    return not text.strip()


__all__ = [
    "clean_ocr_text",
    "count_ocr_characters",
    "count_ocr_words",
    "is_ocr_empty",
    "normalize_ocr_text",
]
