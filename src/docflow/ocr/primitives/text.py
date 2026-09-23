"""Text measurement, cleaning and canonicalization (``OCR-02`` surface).

Measurements and canonicalization only: nothing here decides that text is good, missing or worth
keeping. :func:`normalize_ocr_text` exists so two runs that differ only in trailing whitespace
produce the same artifact, which is what makes the determinism claim checkable rather than merely
asserted.

Every body raises :class:`NotImplementedError`. ``OCR-05`` implements these, except
:func:`is_ocr_empty`, which ``OCR-08`` owns because it feeds the metrics.
"""

from __future__ import annotations


def count_ocr_characters(text: str) -> int:
    """Count the characters.

    Args:
        text: The text to measure.

    Returns:
        The character count.

    Raises:
        NotImplementedError: ``OCR-05`` implements this.

    # TODO: [MVP] implement (OCR-05).
    """
    raise NotImplementedError("count_ocr_characters is implemented by OCR-05")


def count_ocr_words(text: str) -> int:
    """Count the words.

    Args:
        text: The text to measure.

    Returns:
        The word count.

    Raises:
        NotImplementedError: ``OCR-05`` implements this.

    # TODO: [MVP] implement (OCR-05).
    """
    raise NotImplementedError("count_ocr_words is implemented by OCR-05")


def clean_ocr_text(text: str) -> str:
    """Strip the artifacts an OCR pass leaves behind.

    Args:
        text: The raw text.

    Returns:
        The cleaned text.

    Raises:
        NotImplementedError: ``OCR-05`` implements this.

    # TODO: [MVP] implement (OCR-05).
    """
    raise NotImplementedError("clean_ocr_text is implemented by OCR-05")


def normalize_ocr_text(text: str) -> str:
    """Put text into its canonical form.

    Args:
        text: The text to canonicalize.

    Returns:
        The canonical form.

    Raises:
        NotImplementedError: ``OCR-05`` implements this.

    # TODO: [MVP] implement (OCR-05).
    """
    raise NotImplementedError("normalize_ocr_text is implemented by OCR-05")


def is_ocr_empty(text: str) -> bool:
    """Report whether an extraction produced no content.

    Args:
        text: The text to test.

    Returns:
        ``True`` when the text holds nothing but whitespace.

    Raises:
        NotImplementedError: ``OCR-08`` implements this.

    # TODO: [MVP] implement (OCR-08).
    """
    raise NotImplementedError("is_ocr_empty is implemented by OCR-08")


__all__ = [
    "clean_ocr_text",
    "count_ocr_characters",
    "count_ocr_words",
    "is_ocr_empty",
    "normalize_ocr_text",
]
