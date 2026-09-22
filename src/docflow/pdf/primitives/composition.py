"""Composition and classification — measurements first, and one descriptive label.

Owned by ``PDF-08``. Two separate jobs, in this order:

1. :func:`analyze_pdf_page` measures what the page contains.
2. :func:`classify_pdf_page` maps those measurements onto ``TEXT`` / ``IMAGE`` / ``MIXED``.

The classification is **data, not routing**. ``subplan-procesador-pdf.md`` §2 is explicit:
the value is recorded in the page result and the orchestrator is the only component that
turns it into a decision. This module therefore reads no workflow flag, imports nothing
from ``docflow.workflow`` and depends on nothing but its argument.

The thresholds are named module constants rather than literals at the comparison site, so
the boundaries are reviewable in one place. Their *values* are provisional for the PoC and
tagged as such; their *existence* is not, because a bare number in a comparison is exactly
the silent default ``docs/plan/README.md`` §7 forbids.
"""

from __future__ import annotations

from dataclasses import dataclass

from docflow.pdf.contracts import (
    EmbeddedImage,
    PDFPageClassification,
    PDFPageMetrics,
    TextBlock,
)

# Provisional thresholds (PDF-08). Named so the boundary is reviewable, and typed as
# floats because every coverage measurement is a fraction of the page area.
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
        image_placements: Placement of each embedded image, when known.
    """

    page_number: int
    text: str
    text_blocks: list[TextBlock]
    embedded_images: list[EmbeddedImage]
    page_dimensions: tuple[float, float]
    image_placements: list[tuple[float, float, float, float]]


def analyze_pdf_page(page_data: PageContent) -> PDFPageMetrics:
    """Measure a page's composition.

    Args:
        page_data: The page's raw content.

    Returns:
        The page's metrics. A page with no text and no images measures as zeroes and is not
        an error: the measurement is honest about an empty page.

    Raises:
        NotImplementedError: Phase 1 declares the signature only.

    # TODO: [MVP] compute the seven measurements; the layout-aware coverage is derived from
    # the page area and the blocks' bounding boxes (PDF-08).
    """
    raise NotImplementedError("analyze_pdf_page is implemented in Phase 1 by PDF-08")


def classify_pdf_page(metrics: PDFPageMetrics) -> PDFPageClassification:
    """Classify a page descriptively from its measurements alone.

    Args:
        metrics: The page's composition metrics. The only input: this function reads no
            workflow flag, no context and no option.

    Returns:
        Exactly one of ``"TEXT"``, ``"IMAGE"`` or ``"MIXED"``.

    Raises:
        NotImplementedError: Phase 1 declares the signature only.

    # TODO: [MVP] apply the named thresholds above; their values are provisional until the
    # fixtures are measured (PDF-08).
    """
    raise NotImplementedError("classify_pdf_page is implemented in Phase 1 by PDF-08")
