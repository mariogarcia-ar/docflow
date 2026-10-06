"""Decision and error tracing records (``ORC-18``)."""

from __future__ import annotations

from pathlib import Path

from docflow.workflow.context import create_document_context, create_page_context
from docflow.workflow.tracing import (
    append_workflow_trace,
    register_decision,
    register_error,
)
from tests.workflow.samples import decision_record, document_request


def test_a_decision_records_stage_action_and_reason() -> None:
    """A skip is inspectable afterwards, with the reason that explains it."""
    page = create_page_context(1)

    record = register_decision(
        page,
        stage="OCR",
        action="SKIP",
        reason="native_text_present",
        page_number=1,
    )

    assert record == decision_record("OCR", "SKIP", "native_text_present")
    assert page.decisions == [record]


def test_an_error_records_the_stage_and_the_typed_kind(tmp_path: Path) -> None:
    """A failure carries its classification and the outcome the run chose."""
    context = create_document_context(
        document_request(tmp_path), input_type="PDF", workflow_run_id="run-1"
    )

    record = register_error(
        context,
        stage="IMAGE",
        error_type="DECODE_ERROR",
        message="the engine refused",
        recoverable=False,
        outcome="REVIEW_REQUIRED",
        page_number=1,
    )

    assert record["stage"] == "IMAGE"
    assert record["type"] == "DECODE_ERROR"
    assert record["outcome"] == "REVIEW_REQUIRED"
    assert context.errors == [record]


def test_a_workflow_trace_records_the_run_level_event(tmp_path: Path) -> None:
    """A dry run and a stop are recorded where the decisions are."""
    context = create_document_context(
        document_request(tmp_path), input_type="PDF", workflow_run_id="run-1"
    )

    record = append_workflow_trace(context, kind="dry_run", reason="dry_run_requested")

    assert record["kind"] == "dry_run"
    assert context.decisions == [record]
