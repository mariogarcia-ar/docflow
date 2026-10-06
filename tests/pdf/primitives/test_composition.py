"""Tests for the page composition and the descriptive classification (``PDF-08``)."""

from __future__ import annotations

from inspect import signature
from pathlib import Path
from typing import get_args

from docflow.pdf.contracts import (
    EmbeddedImage,
    PDFPageClassification,
    PDFPageMetrics,
    TextBlock,
)
from docflow.pdf.primitives import analyze_pdf_page, classify_pdf_page
from docflow.pdf.primitives.composition import (
    IMAGE_COVERAGE_MIN,
    TEXT_CHAR_MIN,
    TEXT_COVERAGE_MIN,
    PDFPageData,
)


def page_data(**overrides: object) -> PDFPageData:
    """Return a page's data, with any field overridden."""
    values: dict[str, object] = {
        "page_number": 1,
        "page_width": 100.0,
        "page_height": 100.0,
        "text": "",
        "text_blocks": [],
        "embedded_images": [],
    }
    values.update(overrides)
    return PDFPageData(**values)  # type: ignore[arg-type]


def metrics(**overrides: object) -> PDFPageMetrics:
    """Return a metrics record, with any field overridden."""
    values: dict[str, object] = {
        "characters": 0,
        "words": 0,
        "text_blocks": 0,
        "images": 0,
        "text_coverage": 0.0,
        "image_coverage": 0.0,
        "largest_image_coverage": 0.0,
    }
    values.update(overrides)
    return PDFPageMetrics(**values)  # type: ignore[arg-type]


def block(text: str, bbox: tuple[float, float, float, float] | None) -> TextBlock:
    """Return one text block."""
    return TextBlock(block_id="block_001", text=text, bbox=bbox, page_number=1)


def image(bbox: tuple[float, float, float, float] | None) -> EmbeddedImage:
    """Return one embedded image record."""
    return EmbeddedImage(
        image_id="image_001",
        path=Path("embedded_images/image_001.png"),
        bbox=bbox,
        width=10,
        height=10,
        format="png",
        metadata={},
    )


def test_counts_are_sums_and_coverages_are_shares() -> None:
    """The metrics measure the page: what it carries, and what share of it that is."""
    measured = analyze_pdf_page(
        page_data(
            text="one two three",
            text_blocks=[block("one two three", (0.0, 0.0, 100.0, 50.0))],
            embedded_images=[image((0.0, 0.0, 50.0, 50.0))],
        )
    )

    assert measured.characters == 13
    assert measured.words == 3
    assert measured.text_blocks == 1
    assert measured.images == 1
    assert measured.text_coverage == 0.5
    assert measured.image_coverage == 0.25
    assert measured.largest_image_coverage == 0.25


def test_a_box_that_runs_past_the_page_is_clamped() -> None:
    """A share of the page cannot exceed the page."""
    measured = analyze_pdf_page(
        page_data(text_blocks=[block("text", (0.0, 0.0, 400.0, 400.0))])
    )

    assert measured.text_coverage == 1.0


def test_an_unmeasured_area_is_not_a_measured_zero() -> None:
    """This engine reports no placement, so the image count is what carries the signal."""
    measured = analyze_pdf_page(page_data(embedded_images=[image(None)]))

    assert measured.images == 1
    assert measured.image_coverage == 0.0
    assert measured.largest_image_coverage == 0.0
    assert classify_pdf_page(measured) == "IMAGE"


def test_the_classification_flips_exactly_at_the_documented_thresholds() -> None:
    """The thresholds are named constants, and these are the boundaries they name."""
    assert classify_pdf_page(metrics(characters=TEXT_CHAR_MIN - 1)) == "IMAGE"
    assert classify_pdf_page(metrics(characters=TEXT_CHAR_MIN)) == "TEXT"
    assert classify_pdf_page(metrics(text_coverage=TEXT_COVERAGE_MIN)) == "TEXT"
    assert (
        classify_pdf_page(
            metrics(
                characters=TEXT_CHAR_MIN,
                largest_image_coverage=IMAGE_COVERAGE_MIN,
            )
        )
        == "MIXED"
    )
    assert (
        classify_pdf_page(
            metrics(
                characters=TEXT_CHAR_MIN,
                largest_image_coverage=IMAGE_COVERAGE_MIN - 0.001,
            )
        )
        == "TEXT"
    )


def test_the_vocabulary_is_closed_and_depends_on_the_metrics_alone() -> None:
    """Invariant 3: the classification is one of three literals, from nothing but metrics.

    The mutation that must break this test is either returning a value outside the
    documented vocabulary (``"OCR"``) or letting the decision read something other than the
    metrics (a ``force_ocr`` flag), which the signature assertion catches.
    """
    assert get_args(PDFPageClassification) == ("TEXT", "IMAGE", "MIXED")
    assert list(signature(classify_pdf_page).parameters) == ["metrics"]

    vectors = [
        metrics(),
        metrics(characters=TEXT_CHAR_MIN - 1),
        metrics(characters=TEXT_CHAR_MIN),
        metrics(characters=TEXT_CHAR_MIN, largest_image_coverage=IMAGE_COVERAGE_MIN),
        metrics(largest_image_coverage=1.0),
    ]
    assert [classify_pdf_page(vector) for vector in vectors] == [
        "IMAGE",
        "IMAGE",
        "TEXT",
        "MIXED",
        "IMAGE",
    ]


def test_a_page_with_no_native_text_is_described_as_an_image() -> None:
    """A page with nothing native to read has only its visual representation to offer."""
    assert classify_pdf_page(metrics()) == "IMAGE"
    assert classify_pdf_page(metrics(images=2)) == "IMAGE"
