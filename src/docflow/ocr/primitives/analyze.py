"""Computing the content metrics of an extraction (``OCR-08``).

One function, and it *composes* rather than measures. Every number it returns comes from a primitive
that already exists — :mod:`~docflow.ocr.primitives.text` for the character and word counts,
:mod:`~docflow.ocr.primitives.layout` for the block count and the density,
:mod:`~docflow.ocr.primitives.rendering` for the table count — so there is exactly one place that
knows how to count a block or compute a density, and this module owns none of them. Re-implementing
a count here would be a second answer to a question that already has one.

The metrics are **descriptive evidence**, never a verdict. Nothing here decides that an extraction
is good, poor, or worth retrying: ``LOW_CONTENT → use the VLM`` is the orchestrator's call, and this
module does not know the VLM exists. It reports what the page yielded so that something else can
decide what to do about it.

The module is not one of §3.4's groups, and that is worth stating rather than hiding. §3.4 lists the
*measurements* — ``count_ocr_characters``, ``is_ocr_empty``, ``count_blocks``,
``calculate_ocr_text_density``, ``count_tables`` — spread across the groups that own their subjects,
and ``analyze_ocr_result`` appears in the plan as the task's deliverable (``OCR-08``'s scope, and
§3.3's flow) rather than in that palette. It gets its own module for the reason the *image*
processor's ``analyze.py`` records: an aggregator that composes five primitives from three modules
belongs to none of them, and putting it in any one would make that module depend on the other two
for no reason.
"""

from __future__ import annotations

from docflow.ocr.contracts import OCRDocument, OCRMetrics
from docflow.ocr.primitives.layout import (
    calculate_ocr_text_density,
    count_blocks,
)
from docflow.ocr.primitives.rendering import count_tables
from docflow.ocr.primitives.text import (
    count_ocr_characters,
    count_ocr_words,
    is_ocr_empty,
)

STRUCTURAL_BLOCK_TYPES: frozenset[str] = frozenset(
    {"title", "list", "caption", "figure", "table"}
)
"""The block types that count as recognised structure.

A page of plain prose has no structure to recognise: it is a run of characters, and its blocks being
paragraphs says nothing about the *page*. A heading, a list, a caption, a figure or a table is a
claim about how the document is organised, and any one of them making
:attr:`OCRMetrics.structure_detected` true is what "whether any structural element was recognized"
means.

``text``, ``paragraph`` and ``other`` are deliberately absent. ``other`` least of all: it is what
the label mapping produces for a label it does not know, so treating it as structure would report a
recognised element everywhere the processor understood *less* than usual.

A set rather than a tuple or a chain of comparisons because the question is membership, and because
a second reader of it gets the same answer without re-deriving the rule.
"""


def analyze_ocr_result(document: OCRDocument) -> OCRMetrics:
    """Measure an extraction and return a complete :class:`OCRMetrics` snapshot.

    Every field is a measurement of the document as it stands. ``characters`` and ``words`` count
    the document's own text; ``blocks``, ``tables`` and ``paragraphs`` count what was extracted;
    ``text_density`` divides the first of those by the page area; ``empty`` is true exactly when
    there is no text to speak of; and ``structure_detected`` is true when at least one element
    claims how the document is organised.

    **The density is computed in the frame the layout arrives in**, which today is the engine's
    pixels — ``OCR-05`` built the primitives that normalize geometry and ``OCR-11`` is the task that
    runs them, so until then the page area is in pixels and the figure is characters per square
    pixel. That is a true measurement rather than a placeholder, and it is comparable between runs
    of this pipeline, which is the property ``calculate_ocr_text_density`` documents. It is *not*
    comparable across frames, so nothing here records a threshold against it — that is
    ``OCR-09``'s business and it should read the frame before it does.

    Nothing is filled in with a value the document does not support. An extraction that yielded
    nothing reports zeroes and ``empty`` true because that is what was measured, not because a
    default was substituted — the distinction ``OCR-09`` needs in order to tell ``EMPTY`` from a
    failure.

    Args:
        document: The extraction to measure.

    Returns:
        The measured metrics.
    """
    characters = count_ocr_characters(document.text)
    layout = document.layout

    return OCRMetrics(
        characters=characters,
        words=count_ocr_words(document.text),
        blocks=count_blocks(document.blocks),
        tables=count_tables(document.tables),
        # No `count_paragraphs` primitive exists: paragraphs are a field of the document rather
        # than something this processor groups, so its length is the measurement. The other counts
        # go through primitives because the plan declares them, not because `len` would be wrong.
        paragraphs=len(document.paragraphs),
        text_density=calculate_ocr_text_density(
            characters, layout.page_width, layout.page_height
        ),
        empty=is_ocr_empty(document.text),
        structure_detected=_has_structure(document),
    )


def _has_structure(document: OCRDocument) -> bool:
    """Report whether any element claims how the document is organised.

    A table counts even though a table whose cells were all empty is not a structural claim worth
    much: the presence of a *detected table* is the engine recognising a grid on the page, and that
    recognition is the fact being reported. Judging the table's usefulness is not this module's.

    Args:
        document: The extraction to inspect.

    Returns:
        ``True`` when at least one table was found or one block carries a structural type.
    """
    if document.tables:
        return True
    return any(block.type in STRUCTURAL_BLOCK_TYPES for block in document.blocks)


__all__ = [
    "STRUCTURAL_BLOCK_TYPES",
    "analyze_ocr_result",
]
