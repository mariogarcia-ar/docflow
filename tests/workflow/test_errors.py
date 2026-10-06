"""Containing a failed stage (``ORC-16``)."""

from __future__ import annotations

from pathlib import Path

from docflow.states import StageState
from docflow.workflow.context import create_document_context, create_page_context
from docflow.workflow.contracts import StageExecution
from docflow.workflow.errors import MAX_STAGE_ATTEMPTS, handle_processor_error
from tests.workflow.samples import document_request, execution_policy
from tests.workflow.samples import stage as build_stage

FAILURE = {
    "type": "DECODE_ERROR",
    "message": "the engine refused",
    "recoverable": False,
    "metadata": {"engine": "opencv"},
}


def _running_stage(attempts: int) -> StageExecution:
    """Return a stage that has already been attempted ``attempts`` times."""
    return build_stage("IMAGE", attempts=attempts, status=StageState.RUNNING)


def test_a_failure_is_recorded_with_its_typed_kind(tmp_path: Path) -> None:
    """The record names the stage, the typed kind and the outcome."""
    request = document_request(tmp_path)
    context = create_document_context(
        request, input_type="PDF", workflow_run_id="run-1"
    )
    page = create_page_context(1)
    stage = _running_stage(MAX_STAGE_ATTEMPTS)

    outcome = handle_processor_error(context, page, stage, failure=FAILURE)

    assert outcome == "REVIEW_REQUIRED"
    assert stage.status is StageState.FAILED
    assert stage.error["type"] == "DECODE_ERROR"
    assert page.errors[-1]["type"] == "DECODE_ERROR"
    assert page.errors[-1]["outcome"] == "REVIEW_REQUIRED"
    assert context.errors[-1]["stage"] == "IMAGE"


def test_a_needs_review_outcome_reaches_the_document(tmp_path: Path) -> None:
    """An outcome a human has to act on is visible in the document's status."""
    request = document_request(tmp_path, execution=execution_policy(retry_failed=False))
    context = create_document_context(
        request, input_type="PDF", workflow_run_id="run-1"
    )
    page = create_page_context(1)

    handle_processor_error(context, page, _running_stage(1), failure=FAILURE)

    assert context.status == "REVIEW_REQUIRED"
    assert page.status is StageState.FAILED


def test_a_retryable_failure_asks_for_a_retry(tmp_path: Path) -> None:
    """A whole-processor retry is offered while the ceiling allows it."""
    request = document_request(tmp_path)
    context = create_document_context(
        request, input_type="PDF", workflow_run_id="run-1"
    )
    page = create_page_context(1)

    outcome = handle_processor_error(context, page, _running_stage(1), failure=FAILURE)

    assert outcome == "retry processor"
    assert context.status == "PAUSED"


def test_the_ceiling_is_what_ends_the_retries(tmp_path: Path) -> None:
    """Past the ceiling the run stops asking for retries and says so."""
    request = document_request(tmp_path)
    context = create_document_context(
        request, input_type="PDF", workflow_run_id="run-1"
    )

    assert (
        handle_processor_error(
            context,
            None,
            _running_stage(MAX_STAGE_ATTEMPTS),
            failure=FAILURE,
        )
        == "REVIEW_REQUIRED"
    )
