"""Round-trip test for the PDF contract (``GEN-06``).

Proves the Phase 0 exit for this contract: ``PDFRequest → PDFResult`` round-trips an
in-memory fake end to end *before* any real engine exists. The fake reads nothing and
writes nothing; it replaces ``process_pdf`` so the contract itself is what is under test.

The failure vocabulary is guarded here too: it is the list the subplan fixes, and the
primitive layer's error mapping is written against it.
"""

from __future__ import annotations

from pathlib import Path
from typing import get_args

import pytest

from docflow.pdf import (
    EmbeddedImage,
    PDFContext,
    PDFErrorType,
    PDFMetadata,
    PDFPageMetadata,
    PDFPageMetrics,
    PDFPageResult,
    PDFPageValidation,
    PDFRequest,
    PDFResult,
    PDFValidation,
    TextBlock,
)
from tests.factories import (
    build_pdf_options,
    build_pdf_request,
    incomplete_call,
)


def build_page_result(context: PDFContext) -> PDFPageResult:
    """Build a complete in-memory page result; no file is written."""
    metrics = PDFPageMetrics(
        characters=42,
        words=7,
        text_blocks=1,
        images=1,
        text_coverage=0.3,
        image_coverage=0.4,
        largest_image_coverage=0.4,
    )
    return PDFPageResult(
        page_number=1,
        page_pdf=Path("page_001/source/page.pdf"),
        page_image=Path("page_001/render/page.png"),
        native_text=Path("page_001/native_text/text.txt"),
        text_blocks=[
            TextBlock(
                block_id="block_001",
                text="A native text block.",
                bbox=(0.0, 0.0, 10.0, 10.0),
                page_number=1,
            )
        ],
        embedded_images=[
            EmbeddedImage(
                image_id="image_001",
                path=Path("page_001/embedded_images/image_001.png"),
                bbox=(1.0, 1.0, 5.0, 5.0),
                width=64,
                height=64,
                format="png",
                metadata={},
            )
        ],
        metrics=metrics,
        classification="MIXED",
        artifacts=[Path("page_001/metadata.json")],
        validation=PDFPageValidation(status="VALID", errors=[], missing_artifacts=[]),
        metadata=PDFPageMetadata(
            processor="pdf",
            processor_version="0.0.0",
            engine="poppler",
            engine_version="test",
            context=context,
            timing={"total": 0.1},
        ),
        status="success",
    )


def fake_process_pdf(request: PDFRequest) -> PDFResult:
    """Stand-in processor: builds a result from the request and nothing else."""
    page = build_page_result(request.context)
    return PDFResult(
        source_path=request.pdf_path,
        metadata=PDFMetadata(
            processor="pdf",
            processor_version="0.0.0",
            engine="poppler",
            engine_version="test",
            page_count=1,
            context=request.context,
            timing={"total": 0.1},
        ),
        pages=[page],
        metrics=page.metrics,
        artifacts=[Path("metadata.json")],
        validation=PDFValidation(status="VALID", errors=[], missing_artifacts=[]),
        status="success",
    )


def test_the_fake_returns_the_matching_result_type(tmp_path: Path) -> None:
    """A valid request produces a ``PDFResult`` and not some other shape."""
    result = fake_process_pdf(build_pdf_request(tmp_path))

    assert isinstance(result, PDFResult)


def test_the_request_identity_is_preserved_in_the_result(tmp_path: Path) -> None:
    """``document_id`` and ``workflow_run_id`` survive the round trip unchanged."""
    request = build_pdf_request(tmp_path)

    result = fake_process_pdf(request)

    assert result.metadata.context == request.context
    assert result.pages[0].metadata.context == request.context


def test_the_page_carries_measurements_and_a_descriptive_classification(
    tmp_path: Path,
) -> None:
    """Classification is data the caller can read, not a decision already taken."""
    result = fake_process_pdf(build_pdf_request(tmp_path))
    page = result.pages[0]

    assert page.classification in {"TEXT", "IMAGE", "MIXED"}
    assert page.metrics.characters == 42


def test_a_missing_required_option_is_rejected_instead_of_defaulted() -> None:
    """A missing capability is a missing capability, not a silent default."""
    complete = build_pdf_options()
    incomplete = {
        "extract_pages": True,
        "render": True,
        "extract_text": True,
        "extract_images": True,
        "layout": True,
    }

    with pytest.raises(TypeError):
        incomplete_call(type(complete), incomplete)


def test_a_result_without_a_page_is_not_produced_by_the_fake(tmp_path: Path) -> None:
    """The contract forbids an empty document standing in for a processed one."""
    result = fake_process_pdf(build_pdf_request(tmp_path))

    assert len(result.pages) == result.metadata.page_count
    assert result.pages


def test_the_failure_kinds_are_exactly_the_documented_ten() -> None:
    """``PDF-01``: the failed-run vocabulary, and nothing else.

    The expected list is restated here on purpose: deriving it from ``PDFErrorType`` would
    make the assertion tautological, and the restatement is what lets the test fail when a
    kind drifts away from the subplan. That restatement is also why the lines resemble the
    source literal, so ``duplicate-code`` does not apply to this function.
    """
    # pylint: disable=duplicate-code
    assert get_args(PDFErrorType) == (
        "INVALID_INPUT",
        "UNSUPPORTED_PDF",
        "ENCRYPTED_PDF",
        "CORRUPTED_PDF",
        "PAGE_EXTRACTION_ERROR",
        "RENDER_ERROR",
        "TEXT_EXTRACTION_ERROR",
        "IMAGE_EXTRACTION_ERROR",
        "IO_ERROR",
        "INTERNAL_ERROR",
    )
