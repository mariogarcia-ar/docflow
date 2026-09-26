"""Consolidating a page and a document (``ORC-17``)."""

from __future__ import annotations

from pathlib import Path

from docflow.states import StageState
from docflow.workflow.consolidation import (
    consolidate_document_result,
    consolidate_page_result,
    execution_summary,
)
from docflow.workflow.context import create_document_context, create_page_context
from docflow.workflow.contracts import DocumentContext, PageContext
from docflow.workflow.stages import set_stage_status
from tests.workflow.samples import (
    document_request,
    execution_policy,
)
from tests.workflow.samples import stage as build_stage


def _page(number: int, statuses: dict[str, StageState]) -> PageContext:
    """Return a page with the given stages in the given states."""
    page = create_page_context(number)
    for name, status in statuses.items():
        execution = build_stage(name, page_number=number)  # type: ignore[arg-type]
        set_stage_status(execution, status, reason="a reason")
        page.stages[name] = execution
    return page


def _context(tmp_path: Path, pages: list[PageContext]) -> DocumentContext:
    """Return a context holding ``pages``."""
    context = create_document_context(
        document_request(tmp_path), input_type="PDF", workflow_run_id="run-1"
    )
    context.pages.extend(pages)
    return context


def test_a_page_result_preserves_the_processor_results() -> None:
    """A result object is carried through, not summarised or re-derived."""
    sentinel = {"content": "as the processor returned it"}
    page = create_page_context(1)
    page.results["image_result"] = sentinel
    page.selected_source = "NATIVE_TEXT"
    page.extraction_strategy = "TEXT_ONLY"
    page.status = StageState.SUCCESS

    result = consolidate_page_result(page)

    assert result.results["image_result"] is sentinel
    assert result.page_number == 1
    assert result.selected_source == "NATIVE_TEXT"


def test_the_summary_lists_reused_and_skipped_stages(tmp_path: Path) -> None:
    """Which stage ended where is readable from the summary alone."""
    page = _page(
        1,
        {
            "IMAGE": StageState.SUCCESS,
            "OCR": StageState.SKIPPED,
            "LLM": StageState.REUSED,
        },
    )
    page.decisions.append(
        {
            "stage": "OCR",
            "action": "SKIP",
            "reason": "native_text_present",
            "page_number": 1,
            "metadata": {},
        }
    )
    context = _context(tmp_path, [page])

    summary = execution_summary(context)

    assert summary["IMAGE"] is StageState.SUCCESS
    assert summary["OCR"] is StageState.SKIPPED
    assert summary["LLM"] is StageState.REUSED
    assert summary["skipped"] == ["OCR"]
    assert summary["reused"] == ["LLM"]
    assert [record["stage"] for record in summary["decisions"]] == ["OCR"]


def test_the_document_status_follows_the_pages(tmp_path: Path) -> None:
    """A document is only as successful as the pages it produced."""
    request = document_request(tmp_path)
    first = _page(1, {"IMAGE": StageState.SUCCESS})
    second = _page(2, {"IMAGE": StageState.SUCCESS})
    first.status = StageState.SUCCESS
    second.status = StageState.SUCCESS
    context = _context(tmp_path, [first, second])

    assert consolidate_document_result(context, request).status == "SUCCESS"

    second.status = StageState.FAILED
    assert consolidate_document_result(context, request).status == "PARTIAL"


def test_a_document_that_produced_nothing_failed(tmp_path: Path) -> None:
    """No pages and no status of its own means the run has nothing to report."""
    request = document_request(tmp_path)
    context = _context(tmp_path, [])

    assert consolidate_document_result(context, request).status == "FAILED"


def test_a_declared_stop_leaves_the_document_paused(tmp_path: Path) -> None:
    """A run that stopped before its last stage is resumable, not finished."""
    request = document_request(
        tmp_path, execution=execution_policy(stop_after_stage="OCR")
    )
    context = create_document_context(
        request, input_type="PDF", workflow_run_id="run-1"
    )
    page = _page(1, {"IMAGE": StageState.SUCCESS})
    page.status = StageState.SUCCESS
    context.pages.append(page)

    assert consolidate_document_result(context, request).status == "PAUSED"


def test_the_result_carries_every_page_decision_and_error(tmp_path: Path) -> None:
    """A caller reading the result sees the page-level records too."""
    request = document_request(tmp_path)
    page = _page(1, {"IMAGE": StageState.SUCCESS})
    page.decisions.append(
        {
            "stage": "OCR",
            "action": "SKIP",
            "reason": "native_text_present",
            "page_number": 1,
            "metadata": {},
        }
    )
    page.errors.append(
        {
            "stage": "LLM",
            "type": "PROVIDER_ERROR",
            "message": "down",
            "recoverable": False,
            "outcome": "REVIEW_REQUIRED",
            "page_number": 1,
            "metadata": {},
        }
    )
    context = _context(tmp_path, [page])

    result = consolidate_document_result(context, request)

    assert [record["stage"] for record in result.decisions] == ["OCR"]
    assert [record["stage"] for record in result.errors] == ["LLM"]
    assert result.processing_key
    assert [page_result.page_number for page_result in result.pages] == [1]
