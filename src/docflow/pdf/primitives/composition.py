"""Composition and classification — measurements first, and one descriptive label.

Owned by ``PDF-08``. Two separate jobs, in this order:

1. :func:`analyze_pdf_page` measures what the page contains.
2. :func:`classify_pdf_page` maps those measurements onto ``TEXT`` / ``IMAGE`` / ``MIXED``.

The classification is **data, not routing**. ``subplan-procesador-pdf.md`` §2 is explicit:
the value is recorded in the page result and the orchestrator is the only component that
turns it into a decision. This module therefore reads no workflow flag, imports nothing from
``docflow.workflow`` and depends on nothing but its argument.

The thresholds are named module constants rather than literals at the comparison site, so
the boundaries are reviewable in one place. Their *values* are provisional for the PoC and
tagged as such; their *existence* is not, because a bare number in a comparison is exactly
the silent default ``docs/plan/README.md`` §7 forbids.

Coverage is measured in square PDF points and divided by the page area. Text coverage comes
from the blocks' bounding boxes; image coverage from each image's pixel dimensions and the
resolution the engine reports for it — the derivation that closed the gap left by
``pdfimages`` exposing no rectangle. A page whose usable area is zero cannot have a coverage
computed, and that is reported as ``0.0`` for a page with nothing on it and raised about
otherwise, because reporting a fraction of nothing would be a number with no meaning.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from docflow.pdf.contracts import (
    EmbeddedImage,
    PDFPageClassification,
    PDFPageMetrics,
    TextBlock,
)

TEXT_CHAR_MIN = 100
"""Characters below which a page carries too little native text to be called ``TEXT``."""

WORD_MIN = 20
"""Words below which the same judgement applies, catching text made of long tokens."""

TEXT_COVERAGE_MIN = 0.02
"""Fraction of the page that native text must cover to be called ``TEXT``."""

IMAGE_COVERAGE_MIN = 0.50
"""Fraction of the page an image must cover before the page counts as visual."""

DOMINANT_IMAGE_COVERAGE_MIN = 0.80
"""Fraction covered by a *single* image for the page to be called ``IMAGE`` outright."""

POINTS_PER_INCH = 72.0
"""PDF points in an inch, for the pixel-to-point conversion."""


@dataclass(frozen=True)
class PageContent:
    """Raw page content, handed to the measurement step.

    The primitives produce this and :func:`analyze_pdf_page` measures it, which keeps the
    arithmetic testable without a PDF on disk and keeps the PDF-reading code out of the
    metrics.

    Attributes:
        page_number: Page index, 1-based.
        text: The page's native text.
        text_blocks: The page's native text blocks.
        embedded_images: The page's embedded images.
        page_dimensions: The page's ``(width, height)`` in PDF points.
    """

    page_number: int
    text: str
    text_blocks: list[TextBlock]
    embedded_images: list[EmbeddedImage]
    page_dimensions: tuple[float, float]


def _rect_area(bbox: tuple[float, float, float, float]) -> float:
    """Return the area of a bounding box, or ``0.0`` when it is degenerate.

    Args:
        bbox: ``(x_min, y_min, x_max, y_max)`` in PDF points.

    Returns:
        The area in square points. An inverted box contributes nothing rather than a
        negative area, which would subtract from the total.
    """
    x_min, y_min, x_max, y_max = bbox
    return max(0.0, x_max - x_min) * max(0.0, y_max - y_min)


def _image_area(image: EmbeddedImage) -> float:
    """Return an image's drawn area in square PDF points.

    Args:
        image: The embedded image.

    Returns:
        The area, derived from the image's pixel size and the resolution the engine reported.
        An image whose resolution is missing falls back to its pixel count — an approximation
        that is documented rather than a division by zero.
    """
    try:
        x_ppi = float(image.metadata.get("x_ppi", "0"))
        y_ppi = float(image.metadata.get("y_ppi", "0"))
    except ValueError:
        x_ppi = y_ppi = 0.0

    if x_ppi <= 0 or y_ppi <= 0:
        return float(image.width) * float(image.height)
    return (image.width / x_ppi * POINTS_PER_INCH) * (
        image.height / y_ppi * POINTS_PER_INCH
    )


def _coverage(area: float, page_area: float, page_number: int) -> float:
    """Return ``area / page_area``, refusing to divide by nothing.

    Args:
        area: The measured area in square points.
        page_area: The page's area in square points.
        page_number: Page index, for the error message.

    Returns:
        The fraction of the page covered, or ``0.0`` when there is nothing to cover.

    Raises:
        ValueError: The page has an area of zero while something claims to sit on it. A
            fraction of an empty page is not a number worth reporting, and inventing one
            would put a fabricated measurement into ``PDFPageMetrics``.
    """
    if page_area <= 0:
        if area <= 0:
            return 0.0
        raise ValueError(
            f"page {page_number} reports no area, so a coverage fraction cannot be "
            "computed for content that claims to be on it"
        )
    return area / page_area


def analyze_pdf_page(page_data: PageContent) -> PDFPageMetrics:
    """Measure a page's composition.

    Args:
        page_data: The page's raw content.

    Returns:
        The page's metrics. A page with no text and no images measures as zeroes and is not
        an error: the measurement is honest about an empty page.

    Raises:
        ValueError: The page reports no area while carrying content.
    """
    text = page_data.text
    page_width, page_height = page_data.page_dimensions
    page_area = page_width * page_height

    text_area = sum(
        _rect_area(block.bbox)
        for block in page_data.text_blocks
        if block.bbox is not None
    )
    image_areas = [_image_area(image) for image in page_data.embedded_images]

    return PDFPageMetrics(
        characters=len(text),
        words=len(text.split()),
        text_blocks=len(page_data.text_blocks),
        images=len(page_data.embedded_images),
        text_coverage=_coverage(text_area, page_area, page_data.page_number),
        image_coverage=_coverage(sum(image_areas), page_area, page_data.page_number),
        largest_image_coverage=_coverage(
            max(image_areas, default=0.0), page_area, page_data.page_number
        ),
    )


def aggregate_page_metrics(pages: list[PDFPageMetrics]) -> PDFPageMetrics:
    """Sum per-page metrics into the document's aggregate.

    **The sum includes pages that failed, because a failed page genuinely contains nothing
    measurable** — its metrics are the honest zeroes of a page that produced no artifacts,
    not a gap being papered over. The aggregate therefore describes what the document
    yielded, not what it could have yielded, and the per-page ``status`` and ``validation``
    are the authority on whether the sum is complete. ``PDFResult.errors`` carries the
    reasons.

    The alternative — summing only the pages that succeeded — would produce a document whose
    totals silently exclude real pages, which is the kind of plausible-but-wrong number
    ``docs/plan/README.md`` §7 exists to prevent.

    Args:
        pages: The per-page measurements, in page order.

    Returns:
        The aggregate. An empty document sums to zeroes rather than raising: a PDF with no
        pages is an empty document, not an error.
    """
    return PDFPageMetrics(
        characters=sum(page.characters for page in pages),
        words=sum(page.words for page in pages),
        text_blocks=sum(page.text_blocks for page in pages),
        images=sum(page.images for page in pages),
        # Coverage is a fraction of a page, so summing would be meaningless. The document's
        # coverage is the mean over its pages: the fraction of a typical page that carries
        # text, which is the comparison a caller actually wants across documents.
        text_coverage=_mean(page.text_coverage for page in pages),
        image_coverage=_mean(page.image_coverage for page in pages),
        largest_image_coverage=max(
            (page.largest_image_coverage for page in pages), default=0.0
        ),
    )


def _mean(values: Iterable[float]) -> float:
    """Return the mean of a sequence of floats, or ``0.0`` when it is empty.

    Args:
        values: The numbers to average.

    Returns:
        The arithmetic mean. An empty sequence has no mean, and ``0.0`` is the honest answer
        for a document with no pages rather than a division by zero.
    """
    numbers = list(values)
    if not numbers:
        return 0.0
    return sum(numbers) / len(numbers)


def classify_pdf_page(metrics: PDFPageMetrics) -> PDFPageClassification:
    """Classify a page descriptively from its measurements alone.

    Args:
        metrics: The page's composition metrics. The only input: this function reads no
            workflow flag, no context and no option.

    Returns:
        Exactly one of ``"TEXT"``, ``"IMAGE"`` or ``"MIXED"``.

    The order of the tests is what makes the answer deterministic, and it is chosen so that
    the clearest evidence wins:

    1. A single image covering most of the page is ``IMAGE`` whatever text sits on top of it,
       because that is what the page is.
    2. A page with essentially no text — by characters, words and coverage together — is
       ``IMAGE`` if it carries images at all, and ``MIXED`` if it does not, since a page with
       neither is not a text page.
    3. A page with real text and negligible image area is ``TEXT``.
    4. Anything else is ``MIXED``.
    """
    has_text = (
        metrics.characters >= TEXT_CHAR_MIN
        and metrics.words >= WORD_MIN
        and metrics.text_coverage >= TEXT_COVERAGE_MIN
    )
    has_visual = metrics.image_coverage >= IMAGE_COVERAGE_MIN

    if metrics.largest_image_coverage >= DOMINANT_IMAGE_COVERAGE_MIN:
        return "IMAGE"
    if not has_text:
        return "IMAGE" if metrics.images > 0 else "MIXED"
    if not has_visual:
        return "TEXT"
    return "MIXED"


__all__ = [
    "DOMINANT_IMAGE_COVERAGE_MIN",
    "IMAGE_COVERAGE_MIN",
    "POINTS_PER_INCH",
    "TEXT_CHAR_MIN",
    "TEXT_COVERAGE_MIN",
    "WORD_MIN",
    "PageContent",
    "aggregate_page_metrics",
    "analyze_pdf_page",
    "classify_pdf_page",
]
