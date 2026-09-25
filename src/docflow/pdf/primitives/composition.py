"""What one page contributed, the metrics measured from it, and its classification.

The two records here are the seam's data shapes: :class:`PDFDocumentInfo` is what one
inspection of a document reports, :class:`PDFPageData` is everything a single page
contributed before it is analysed. Neither is part of the processor's contract — the
contract types live in :mod:`docflow.pdf.contracts`.

The metrics measure; the classification only names what the measurements say. Neither
function reads ``context``, neither knows the engine, and neither decides what should
happen to the page next: the orchestrator owns every routing decision.
"""

from __future__ import annotations

from dataclasses import dataclass

from docflow.pdf.contracts import (
    EmbeddedImage,
    PDFPageClassification,
    PDFPageMetrics,
    TextBlock,
)

#: Characters below which a page has no usable native text layer.
#: A page whose only text is a page number or a stray glyph is not a text page.
#: TODO: [MVP] provisional PoC value; revisit against the corpus before the MVP gate.
TEXT_CHAR_MIN = 20

#: Text coverage below which the native text layer is too sparse to carry the page.
#: Coverage is the share of the page area its text blocks occupy, in PDF points.
TEXT_COVERAGE_MIN = 0.02

#: Coverage at or above which one image dominates the page.
#: Dominance is measured on the largest single image, not on their sum: three stamps in a
#: corner do not make a scanned page.
IMAGE_COVERAGE_MIN = 0.30


@dataclass(frozen=True)
class PDFDocumentInfo:
    """What one inspection of a PDF reports.

    Attributes:
        page_count: Pages the engine reported for the document.
        page_dimensions: Width and height per page, in PDF points, in page order. One
            entry per page, so the count and the geometry cannot describe two different
            documents.
        engine_metadata: The engine's document-level key/value report, verbatim.
    """

    page_count: int
    page_dimensions: list[tuple[float, float]]
    engine_metadata: dict[str, str]


@dataclass(frozen=True)
class PDFPageData:
    """Everything one page contributed, as the composition functions need it.

    Attributes:
        page_number: Page index, 1-based.
        page_width: Page width in PDF points.
        page_height: Page height in PDF points.
        text: The page's native text, as extracted.
        text_blocks: Native text blocks in reading order.
        embedded_images: Images embedded in the page, in scan order.
    """

    page_number: int
    page_width: float
    page_height: float
    text: str
    text_blocks: list[TextBlock]
    embedded_images: list[EmbeddedImage]


def _bbox_area(bbox: tuple[float, float, float, float] | None) -> float:
    """Return the area of ``bbox``, or ``0.0`` when there is no box to measure."""
    if bbox is None:
        return 0.0
    left, top, right, bottom = bbox
    return max(0.0, right - left) * max(0.0, bottom - top)


def _coverage(area: float, page_area: float) -> float:
    """Return ``area`` as a share of the page, never above the whole page."""
    if page_area <= 0.0:
        return 0.0
    return min(1.0, area / page_area)


def analyze_pdf_page(page_data: PDFPageData) -> PDFPageMetrics:
    """Measure the composition of one page.

    Args:
        page_data: The page's text, blocks, images and geometry.

    Returns:
        The measurements. Counts are sums over what the page carries; coverages are shares
        of the page area.

    Note:
        The image coverages stay ``0.0`` while the engine reports no placement for an
        embedded image, because an unmeasured area is not a measured zero. The
        classification therefore rests on the native text layer for the Poppler engine.
        TODO: [MVP] measure image coverage once a reader that reports placement is behind
        the seam (``PDF-07``: unusual colour spaces and masks are unhandled for the same
        reason).
    """
    page_area = page_data.page_width * page_data.page_height
    text_area = sum(_bbox_area(block.bbox) for block in page_data.text_blocks)
    image_areas = [_bbox_area(image.bbox) for image in page_data.embedded_images]
    visible_text = page_data.text.replace("\n", "").replace("\r", "")

    return PDFPageMetrics(
        characters=len(visible_text),
        words=len(page_data.text.split()),
        text_blocks=len(page_data.text_blocks),
        images=len(page_data.embedded_images),
        text_coverage=_coverage(text_area, page_area),
        image_coverage=_coverage(sum(image_areas), page_area),
        largest_image_coverage=_coverage(max(image_areas, default=0.0), page_area),
    )


def classify_pdf_page(metrics: PDFPageMetrics) -> PDFPageClassification:
    """Name the documentary source a page natively offers.

    The classification is descriptive data in the page result. It is derived from the
    metrics alone — never from ``context``, a workflow flag or a caller's instruction —
    and it is the orchestrator, not this function, that turns it into a decision.

    Args:
        metrics: The page's measured composition.

    Returns:
        ``"MIXED"`` when the page carries both a native text layer and a dominant image,
        ``"TEXT"`` when it carries a native text layer and no dominant image, ``"IMAGE"``
        when it carries neither: a page with no native text has only its visual
        representation to offer.
    """
    text_layer = (
        metrics.characters >= TEXT_CHAR_MIN
        or metrics.text_coverage >= TEXT_COVERAGE_MIN
    )
    dominant_image = (
        metrics.largest_image_coverage >= IMAGE_COVERAGE_MIN
        or metrics.image_coverage >= IMAGE_COVERAGE_MIN
    )

    if text_layer and dominant_image:
        return "MIXED"
    if dominant_image:
        return "IMAGE"
    if text_layer:
        return "TEXT"
    return "IMAGE"
