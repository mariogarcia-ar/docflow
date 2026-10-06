"""Source selection and extraction strategy (``ORC-12``)."""

from __future__ import annotations

from pathlib import Path

from docflow.workflow.context import create_page_context
from docflow.workflow.contracts import PageContext
from docflow.workflow.selection import (
    ocr_skip_reason,
    select_extraction_strategy,
    select_source,
)

POLICIES = {"allow_ocr": True, "allow_vlm": False}
VLM_POLICIES = {"allow_ocr": True, "allow_vlm": True}


def _page_with_native_text(tmp_path: Path) -> PageContext:
    """Return a page whose native text artifact holds text."""
    page = create_page_context(1)
    native_text = tmp_path / "text.txt"
    native_text.write_text("native", encoding="utf-8")
    page.artifacts["native_text"] = native_text
    page.artifacts["page_image"] = _image(tmp_path, "page.png")
    return page


def _image(tmp_path: Path, name: str) -> Path:
    """Return a readable image artifact."""
    path = tmp_path / name
    path.write_bytes(b"\x89PNG\r\n\x1a\n")
    return path


def test_native_text_selects_native_text(
    tmp_path: Path,
) -> None:
    """Text already extracted is the source, and the reason says which one was enough."""
    page = _page_with_native_text(tmp_path)

    choice = select_source(page, POLICIES)

    assert choice.source == "NATIVE_TEXT"
    assert choice.reason == "native_text_present"
    assert select_extraction_strategy(choice).strategy == "TEXT_ONLY"


def test_native_text_and_a_vision_image_select_both(tmp_path: Path) -> None:
    """Vision adds the image to the text rather than replacing it."""
    page = _page_with_native_text(tmp_path)
    page.artifacts["vlm_ready_image"] = _image(tmp_path, "vlm.png")

    choice = select_source(page, VLM_POLICIES)

    assert choice.source == "NATIVE_TEXT + IMAGE"
    assert select_extraction_strategy(choice).strategy == "TEXT_PLUS_VLM"


def test_ocr_text_is_selected_when_the_native_text_is_empty(
    tmp_path: Path,
) -> None:
    """An empty text layer falls through to what OCR produced."""
    page = create_page_context(1)
    page.artifacts["page_image"] = _image(tmp_path, "page.png")
    ocr_text = tmp_path / "ocr.txt"
    ocr_text.write_text("read by ocr", encoding="utf-8")
    page.artifacts["ocr_text"] = ocr_text

    choice = select_source(page, POLICIES)

    assert choice.source == "OCR_TEXT"
    assert choice.reason == "native_text_empty"
    assert select_extraction_strategy(choice).strategy == "OCR_ONLY"


def test_an_image_alone_selects_vision(tmp_path: Path) -> None:
    """A page with no text at all offers its image."""
    page = create_page_context(1)
    page.artifacts["page_image"] = _image(tmp_path, "page.png")

    choice = select_source(page, POLICIES)

    assert choice.source == "IMAGE"
    assert select_extraction_strategy(choice).strategy == "VLM_ONLY"


def test_a_page_with_nothing_readable_has_no_source() -> None:
    """No source is stated, never defaulted to an image that is not there."""
    page = create_page_context(1)

    choice = select_source(page, POLICIES)

    assert choice.source is None
    assert choice.reason == "no_source_available"
    assert select_extraction_strategy(choice).strategy is None


def test_ocr_is_skipped_when_the_document_forbids_it(tmp_path: Path) -> None:
    """A policy skip is named as such."""
    page = create_page_context(1)
    page.artifacts["page_image"] = _image(tmp_path, "page.png")

    assert ocr_skip_reason(page, {"allow_ocr": False, "allow_vlm": False}) == (
        "skipped_by_policy"
    )


def test_ocr_is_skipped_when_the_native_text_is_present(tmp_path: Path) -> None:
    """The routing reason is the one the happy path records."""
    page = _page_with_native_text(tmp_path)

    assert ocr_skip_reason(page, POLICIES) == "native_text_present"


def test_ocr_is_needed_when_there_is_no_text(tmp_path: Path) -> None:
    """Nothing to read natively means OCR runs."""
    page = create_page_context(1)
    page.artifacts["page_image"] = _image(tmp_path, "page.png")

    assert ocr_skip_reason(page, POLICIES) is None
