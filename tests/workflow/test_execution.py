"""The per-page execution path (``ORC-11``).

A page is the unit of isolation, so what these tests check is that one page's stage is
resolved without touching the processor when a valid result exists, and that a page whose
input is missing is blocked rather than failing the pages that are fine.
"""

from __future__ import annotations

from pathlib import Path

from docflow.states import StageState
from docflow.workflow.context import create_document_context, create_page_context
from docflow.workflow.contracts import PageContext
from docflow.workflow.execution import process_page_context
from docflow.workflow.keys import stage_key
from tests.fakes.processors import ProcessorDoubles
from tests.workflow.samples import artifact, document_request
from tests.workflow.samples import stage as build_stage


def _reusable_image_page(tmp_path: Path) -> PageContext:
    """Return a page whose image and native text artifacts exist."""
    page = create_page_context(1)
    page.artifacts["page_image"] = artifact(tmp_path, "page.png", b"\x89PNG\r\n\x1a\n")
    page.artifacts["native_text"] = artifact(tmp_path, "text.txt", b"native")
    return page


def test_a_reusable_stage_is_not_given_to_the_processor(
    tmp_path: Path, processors: ProcessorDoubles
) -> None:
    """``REUSED`` means the processor is not called, and the state says so."""
    request = document_request(tmp_path)
    context = create_document_context(
        request, input_type="PDF", workflow_run_id="run-1"
    )
    page = _reusable_image_page(tmp_path)
    context.pages.append(page)
    key = stage_key(context, request, "IMAGE", page)
    page.stages["IMAGE"] = build_stage(
        "IMAGE",
        processing_key=key,
        status=StageState.SUCCESS,
        input_artifacts=(page.artifacts["page_image"],),
        output=(page.artifacts["page_image"],),
    )

    process_page_context(context, page, request)

    assert page.stages["IMAGE"].status is StageState.REUSED
    assert processors.image.calls == 0


def test_a_page_whose_input_is_missing_is_blocked_alone(
    tmp_path: Path, processors: ProcessorDoubles
) -> None:
    """A page that cannot run does not drag a runnable page down with it."""
    request = document_request(tmp_path, input_type="IMAGE")
    context = create_document_context(
        request, input_type="IMAGE", workflow_run_id="run-1"
    )
    broken = create_page_context(1)
    broken.artifacts["page_image"] = tmp_path / "absent.png"
    context.pages.append(broken)

    process_page_context(context, broken, request)

    assert broken.stages["IMAGE"].status is not StageState.SUCCESS
    assert processors.image.calls == 0
    assert any(record.get("action") == "BLOCKED" for record in broken.decisions)


def test_the_pages_keep_their_logical_order(
    tmp_path: Path, processors: ProcessorDoubles
) -> None:
    """Processing never reorders the document."""
    request = document_request(tmp_path)
    context = create_document_context(
        request, input_type="PDF", workflow_run_id="run-1"
    )
    for number in (1, 2):
        page = create_page_context(number)
        image = tmp_path / f"page{number}.png"
        image.write_bytes(b"\x89PNG\r\n\x1a\n")
        page.artifacts["page_image"] = image
        text = tmp_path / f"text{number}.txt"
        text.write_text("native", encoding="utf-8")
        page.artifacts["native_text"] = text
        context.pages.append(page)

    for page in list(context.pages):
        process_page_context(context, page, request)

    assert [page.page_number for page in context.pages] == [1, 2]
    assert processors.calls()["image"] == 2
