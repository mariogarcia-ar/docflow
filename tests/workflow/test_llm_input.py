"""Composing the LLM input from the selected source and strategy (``ORC-13``)."""

from __future__ import annotations

from pathlib import Path

import pytest

from docflow.workflow.context import create_document_context, create_page_context
from docflow.workflow.contracts import DocumentContext, PageContext
from docflow.workflow.llm_input import build_llm_input
from tests.workflow.samples import document_request


def _page_with_text(tmp_path: Path) -> PageContext:
    """Return a page with native text and both prepared variants."""
    page = create_page_context(1)
    native_text = tmp_path / "text.txt"
    native_text.write_text("native text", encoding="utf-8")
    page.artifacts["native_text"] = native_text
    ocr_ready = tmp_path / "ocr_ready.png"
    ocr_ready.write_bytes(b"\x89PNG\r\n\x1a\n")
    page.artifacts["ocr_ready_image"] = ocr_ready
    vlm_ready = tmp_path / "vlm_ready.png"
    vlm_ready.write_bytes(b"\x89PNG\r\n\x1a\n")
    page.artifacts["vlm_ready_image"] = vlm_ready
    return page


def _context(tmp_path: Path) -> DocumentContext:
    """Return the document context a page belongs to."""
    return create_document_context(
        document_request(tmp_path), input_type="PDF", workflow_run_id="run-1"
    )


def test_a_text_only_strategy_attaches_no_image(tmp_path: Path) -> None:
    """The strategy decides the payload, and text-only carries no image."""
    context = _context(tmp_path)
    page = _page_with_text(tmp_path)
    page.extraction_strategy = "TEXT_ONLY"

    request = build_llm_input(context, page, document_request(tmp_path))

    assert request.document == "native text"
    assert not request.images
    assert request.task == "extract_fields"
    assert request.provider == "ollama"
    assert request.model == "test-model"
    assert request.schema == "simple"
    assert request.graph is None


def test_a_vision_strategy_attaches_the_prepared_image(tmp_path: Path) -> None:
    """An image strategy sends the image *and* the text it was selected with."""
    context = _context(tmp_path)
    page = _page_with_text(tmp_path)
    page.extraction_strategy = "OCR_PLUS_VLM"

    request = build_llm_input(context, page, document_request(tmp_path))

    assert request.document == "native text"
    assert request.images == [str(page.artifacts["vlm_ready_image"])]


def test_the_input_is_written_under_the_run_s_working_root(tmp_path: Path) -> None:
    """The processor is told where its artifacts belong."""
    context = _context(tmp_path)
    page = _page_with_text(tmp_path)
    page.extraction_strategy = "TEXT_ONLY"
    request = document_request(tmp_path)

    composed = build_llm_input(context, page, request)

    assert composed.metadata["output_dir"].startswith(
        str(request.options["output_dir"])
    )
    assert composed.metadata["page_number"] == 1


def test_a_page_with_no_strategy_is_refused(tmp_path: Path) -> None:
    """An inference the routing never asked for is not run on a default."""
    context = _context(tmp_path)
    page = _page_with_text(tmp_path)
    page.extraction_strategy = None

    with pytest.raises(ValueError, match="no extraction strategy"):
        build_llm_input(context, page, document_request(tmp_path))
