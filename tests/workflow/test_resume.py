"""Resuming a document (``ORC-15``)."""

from __future__ import annotations

from pathlib import Path

from docflow.states import StageState
from docflow.workflow.context import create_document_context, create_page_context
from docflow.workflow.contracts import StageExecution
from docflow.workflow.resume import load_resumable_context, recover_running_stages
from tests.workflow.samples import document_request
from tests.workflow.samples import stage as build_stage


def _running_stage(page_number: int) -> StageExecution:
    """Return a stage left ``RUNNING`` by an interrupted run, with its claim still on it."""
    stage = build_stage("OCR", page_number=page_number, status=StageState.RUNNING)
    stage.metadata["owner"] = "a-process-that-is-gone"
    return stage


def test_an_interrupted_stage_is_recovered_to_ready(tmp_path: Path) -> None:
    """A stage left ``RUNNING`` by a dead process becomes claimable again."""
    request = document_request(tmp_path)
    context = create_document_context(
        request, input_type="PDF", workflow_run_id="run-1"
    )
    page = create_page_context(1)
    page.stages["OCR"] = _running_stage(1)
    context.pages.append(page)

    recovered = recover_running_stages(context)

    assert [stage.stage_id for stage in recovered] == ["OCR:1"]
    assert page.stages["OCR"].status is StageState.READY
    assert "owner" not in page.stages["OCR"].metadata
    assert any(
        record.get("reason") == "recovered_interrupted_running"
        for record in page.decisions
    )


def test_a_stage_that_is_not_running_is_left_alone(tmp_path: Path) -> None:
    """Only an interruption is repaired; a decision already taken is not revisited."""
    request = document_request(tmp_path)
    context = create_document_context(
        request, input_type="PDF", workflow_run_id="run-1"
    )
    stage = _running_stage(1)
    stage.status = StageState.SUCCESS
    page = create_page_context(1)
    page.stages["OCR"] = stage
    context.pages.append(page)

    recovered = recover_running_stages(context)

    assert not recovered
    assert page.stages["OCR"].status is StageState.SUCCESS


def test_a_document_that_never_ran_has_nothing_to_resume(tmp_path: Path) -> None:
    """A resume of a document with no record is a first run, stated as such."""
    assert load_resumable_context(tmp_path / "absent.json") is None
