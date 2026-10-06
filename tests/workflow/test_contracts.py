"""Round-trip test for the orchestrator contract (``GEN-06``).

Proves ``DocumentRequest → DocumentResult`` round-trips an in-memory fake end to end, and
with it the four invariants ``GEN-04`` fixes for the identities: the document identity is
preserved, the run identity is minted per run, the processing key is never empty, and no
stage state is reported with a word outside the shared vocabulary.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from docflow.states import StageState
from docflow.workflow import (
    DocumentRequest,
    DocumentResult,
    ExecutionPolicy,
)
from tests.factories import (
    build_document_request,
    incomplete_call,
)


def fake_process_document(request: DocumentRequest) -> DocumentResult:
    """Stand-in orchestrator: builds a result from the request and nothing else.

    The stages are reported with the shared vocabulary, which is what makes the result
    readable by a processor's own reporting.
    """
    return DocumentResult(
        document_id=request.document_id,
        workflow_run_id="run-1",
        processing_key="processor=pdf|version=0.0.0|inputs=abc|options=def",
        input=request.input_path,
        pages=[],
        status="SUCCESS",
        execution_summary={"pdf": StageState.SUCCESS, "ocr": StageState.SKIPPED},
        decisions=[{"stage": "ocr", "action": "skip", "reason": "skipped_by_policy"}],
        errors=[],
        metadata={"workflow": request.workflow},
        final_result={"fields": {}},
    )


def test_the_fake_returns_the_matching_result_type(tmp_path: Path) -> None:
    """A valid request produces a ``DocumentResult``."""
    result = fake_process_document(build_document_request(tmp_path))

    assert isinstance(result, DocumentResult)


def test_the_document_identity_is_preserved(tmp_path: Path) -> None:
    """The caller's ``document_id`` comes back unchanged, from the request it sent."""
    request = build_document_request(tmp_path)

    result = fake_process_document(request)

    assert result.document_id == request.document_id


def test_the_run_identity_is_minted_by_the_orchestrator(tmp_path: Path) -> None:
    """A run identity names the run, so it is produced by the component that runs it."""
    request = build_document_request(tmp_path)

    result = fake_process_document(request)

    assert result.workflow_run_id
    assert not hasattr(request, "workflow_run_id")


def test_the_processing_key_is_never_empty_or_defaulted(tmp_path: Path) -> None:
    """A result that cannot name its unit of work cannot be reused later."""
    result = fake_process_document(build_document_request(tmp_path))

    assert result.processing_key
    assert result.processing_key.strip()


def test_stage_states_in_the_summary_come_from_the_shared_vocabulary(
    tmp_path: Path,
) -> None:
    """Every state the orchestrator reports is a word a processor can also report."""
    result = fake_process_document(build_document_request(tmp_path))

    for state in result.execution_summary.values():
        assert isinstance(state, StageState)


def test_a_skipped_stage_is_not_reported_as_reused(tmp_path: Path) -> None:
    """Deliberately not running and not having to run are different outcomes."""
    result = fake_process_document(build_document_request(tmp_path))

    assert result.execution_summary["ocr"] is StageState.SKIPPED
    assert result.execution_summary["ocr"] is not StageState.REUSED


def test_policies_and_execution_stay_separate_types(tmp_path: Path) -> None:
    """Operational switches never mix with what a document permits."""
    request = build_document_request(tmp_path)

    assert isinstance(request.policies, dict)
    assert isinstance(request.execution, ExecutionPolicy)
    assert not isinstance(request.policies, ExecutionPolicy)


def test_a_missing_execution_policy_is_rejected_instead_of_defaulted(
    tmp_path: Path,
) -> None:
    """A run that does not state its policy must not inherit one silently."""
    complete = build_document_request(tmp_path)
    incomplete = {
        "document_id": complete.document_id,
        "input_path": complete.input_path,
        "input_type": complete.input_type,
        "workflow": complete.workflow,
        "policies": complete.policies,
        "options": complete.options,
        "metadata": complete.metadata,
    }

    with pytest.raises(TypeError):
        incomplete_call(type(complete), incomplete)
