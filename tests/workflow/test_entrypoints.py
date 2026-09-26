"""End-to-end scenarios of the orchestrator (``ORC-19``).

The four acceptance scenarios of ``subplan-orquestador.md`` §5 plus the failure paths that
prove a failure is *reported* rather than raised. Every test runs the real
``process_document`` against the four contract-level fakes, so what is exercised is the
whole orchestrator and not a part of it.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from docflow.states import StageState
from docflow.workflow import (
    ExecutionPlan,
    process_document,
    resume_document,
)
from tests.fakes.processors import ProcessorDoubles
from tests.workflow.samples import (
    SAMPLE_IMAGE,
    UNSUPPORTED_FILE,
    document_request,
    execution_policy,
    run_options,
    state_file,
)


def test_the_happy_path_runs_a_pdf_with_native_text_end_to_end(
    tmp_path: Path, processors: ProcessorDoubles
) -> None:
    """``PDF → IMAGE → (OCR skipped) → SOURCE SELECTION → LLM`` produces ``SUCCESS``."""
    result = process_document(document_request(tmp_path))

    assert result.status == "SUCCESS"
    summary = result.execution_summary
    assert summary["PDF"] is StageState.SUCCESS
    assert summary["IMAGE"] is StageState.SUCCESS
    assert summary["LLM"] is StageState.SUCCESS
    assert summary["OCR"] is StageState.SKIPPED
    assert summary["skipped"] == ["OCR"]
    assert [page.page_number for page in result.pages] == [1]
    assert result.pages[0].selected_source == "NATIVE_TEXT"
    assert result.pages[0].extraction_strategy == "TEXT_ONLY"
    assert result.final_result["pages"][0]["result"] == {"fields": {"total": "42.00"}}
    assert processors.calls() == {"pdf": 1, "image": 1, "ocr": 0, "llm": 1}


def test_the_skipped_stage_records_its_reason(
    tmp_path: Path, processors: ProcessorDoubles
) -> None:
    """A stage that did not run says why, and the decision is in the summary."""
    result = process_document(document_request(tmp_path))

    decisions = [record for record in result.decisions if record.get("stage") == "OCR"]
    assert any(
        record["action"] == "SKIP" and record["reason"] == "native_text_present"
        for record in decisions
    )
    assert result.execution_summary["decisions"]
    assert processors.ocr.calls == 0


def test_resume_does_not_re_run_completed_stages(
    tmp_path: Path, processors: ProcessorDoubles
) -> None:
    """Invariant 1: a completed stage is reused, never re-executed, on a resume."""
    processors.pdf.text = ""
    first = document_request(
        tmp_path, execution=execution_policy(stop_after_stage="OCR")
    )
    first_result = process_document(first)
    assert first_result.status == "PAUSED"
    before = processors.calls()
    assert before == {"pdf": 1, "image": 1, "ocr": 1, "llm": 0}
    assert state_file(tmp_path).is_file()

    second = replace(
        first,
        execution=replace(first.execution, resume=True, stop_after_stage=None),
    )
    result = resume_document(second)

    assert result.status == "SUCCESS"
    summary = result.execution_summary
    assert summary["PDF"] is StageState.REUSED
    assert summary["IMAGE"] is StageState.REUSED
    assert summary["OCR"] is StageState.REUSED
    assert summary["LLM"] is StageState.SUCCESS
    after = processors.calls()
    assert after["pdf"] == before["pdf"]
    assert after["image"] == before["image"]
    assert after["ocr"] == before["ocr"]
    assert after["llm"] == before["llm"] + 1


def test_forcing_a_stage_invalidates_its_downstream_dependents(
    tmp_path: Path, processors: ProcessorDoubles
) -> None:
    """Invariant 2: forcing OCR makes the LLM stage stale, and it runs again."""
    processors.pdf.text = ""
    first = document_request(tmp_path)
    first_result = process_document(first)
    assert first_result.execution_summary["OCR"] is StageState.SUCCESS
    assert first_result.execution_summary["LLM"] is StageState.SUCCESS
    before = processors.calls()

    forced = replace(
        first, execution=execution_policy(resume=True, force_stages=["OCR"])
    )
    result = process_document(forced)

    summary = result.execution_summary
    assert summary["PDF"] is StageState.REUSED
    assert summary["IMAGE"] is StageState.REUSED
    assert summary["OCR"] is StageState.SUCCESS
    assert [
        record
        for record in result.decisions
        if record.get("stage") == "LLM" and record.get("action") == "INVALIDATED"
    ]
    after = processors.calls()
    assert after["ocr"] == before["ocr"] + 1
    assert after["llm"] == before["llm"] + 1


def test_reuse_requires_a_processing_key_match_not_mere_file_existence(
    tmp_path: Path, processors: ProcessorDoubles
) -> None:
    """Invariant 3: an option change misses the cache even though the files are there."""
    first = document_request(tmp_path)
    process_document(first)
    before = processors.calls()

    changed = run_options(tmp_path)
    changed["image"]["deskew"] = False
    second = replace(first, options=changed, execution=execution_policy(resume=True))
    result = process_document(second)

    assert processors.calls()["image"] == before["image"] + 1
    assert [
        record
        for record in result.decisions
        if record.get("stage") == "IMAGE" and record.get("action") == "EXECUTE"
    ]
    assert result.execution_summary["IMAGE"] is StageState.SUCCESS


def test_a_dry_run_returns_the_plan_and_invokes_no_processor(
    tmp_path: Path, processors: ProcessorDoubles
) -> None:
    """Scenario 4: the plan is returned for inspection, and nothing costly runs."""
    first = document_request(tmp_path)
    process_document(first)
    before = processors.calls()

    dry = replace(
        first,
        execution=execution_policy(resume=True, dry_run=True, force_stages=["IMAGE"]),
    )
    result = process_document(dry)

    plan = result.final_result
    assert isinstance(plan, ExecutionPlan)
    assert plan.dry_run is True
    assert result.metadata["dry_run"] is True
    actions = {entry.action for entry in plan.stages}
    assert actions <= {"EXECUTE", "REUSE", "SKIP", "FORCE", "WAIT", "BLOCKED"}
    assert {"REUSE", "SKIP", "FORCE"} <= actions
    assert all(entry.processing_key for entry in plan.stages)
    assert processors.calls() == before


def test_a_stage_whose_input_never_appears_is_blocked(
    tmp_path: Path, processors: ProcessorDoubles
) -> None:
    """A plan entry says ``BLOCKED`` when its input can never arrive."""
    missing = tmp_path / "page.png"
    request = document_request(
        tmp_path,
        input_path=missing,
        input_type="IMAGE",
        execution=execution_policy(dry_run=True),
    )

    result = process_document(request)

    plan = result.final_result
    assert isinstance(plan, ExecutionPlan)
    assert {entry.action for entry in plan.stages} == {"BLOCKED"}
    assert {entry.reason for entry in plan.stages} == {"input_unavailable"}
    assert processors.calls() == {"pdf": 0, "image": 0, "ocr": 0, "llm": 0}


def test_an_image_input_runs_without_a_pdf_stage(
    tmp_path: Path, processors: ProcessorDoubles
) -> None:
    """A direct image becomes one logical page, and no PDF stage pretends to have run."""
    request = document_request(tmp_path, input_path=SAMPLE_IMAGE, input_type="IMAGE")

    result = process_document(request)

    assert result.status == "SUCCESS"
    assert "PDF" not in result.execution_summary
    assert result.execution_summary["IMAGE"] is StageState.SUCCESS
    assert result.execution_summary["OCR"] is StageState.SUCCESS
    assert result.pages[0].extraction_strategy == "OCR_ONLY"
    assert processors.pdf.calls == 0
    assert [
        record
        for record in result.decisions
        if record.get("stage") == "PDF" and record.get("reason") == "direct_image_input"
    ]


def test_an_unsupported_input_is_reported_rather_than_guessed(
    tmp_path: Path, processors: ProcessorDoubles
) -> None:
    """An unrecognized file fails the run instead of being processed as something."""
    request = document_request(tmp_path, input_path=UNSUPPORTED_FILE, input_type="auto")

    result = process_document(request)

    assert result.status == "FAILED"
    assert result.errors[0]["type"] == "UNSUPPORTED_INPUT"
    assert processors.calls() == {"pdf": 0, "image": 0, "ocr": 0, "llm": 0}


def test_a_missing_option_is_refused_by_name(
    tmp_path: Path, processors: ProcessorDoubles
) -> None:
    """A missing configuration value is named, never defaulted."""
    options = run_options(tmp_path)
    del options["llm"]
    request = document_request(tmp_path, options=options)

    result = process_document(request)

    assert result.status == "FAILED"
    assert result.errors[0]["type"] == "CONFIGURATION_ERROR"
    assert result.errors[0]["metadata"]["key"] == "llm"
    assert processors.calls()["llm"] == 0


def test_a_missing_policy_flag_is_refused_by_name(
    tmp_path: Path, processors: ProcessorDoubles
) -> None:
    """A policy the document never stated is not inherited from anywhere."""
    request = document_request(tmp_path, policies={"allow_vlm": False})

    result = process_document(request)

    assert result.status == "FAILED"
    assert result.errors[0]["metadata"]["key"] == "allow_ocr"
    assert processors.calls() == {"pdf": 1, "image": 0, "ocr": 0, "llm": 0}


def test_stopping_after_a_stage_leaves_the_document_paused_and_resumable(
    tmp_path: Path, processors: ProcessorDoubles
) -> None:
    """A declared stop finishes the stage, starts no new one, and persists the state."""
    request = document_request(
        tmp_path, execution=execution_policy(stop_after_stage="OCR")
    )

    result = process_document(request)

    assert result.status == "PAUSED"
    assert result.execution_summary["LLM"] is StageState.NOT_STARTED
    assert processors.llm.calls == 0
    assert state_file(tmp_path).is_file()


def test_a_processor_failure_is_reported_not_propagated(
    tmp_path: Path, processors: ProcessorDoubles
) -> None:
    """ORC-16: no exception escapes where a typed result is the contract."""
    processors.image.fail = True

    result = process_document(document_request(tmp_path))

    assert result.status == "REVIEW_REQUIRED"
    image_errors = [record for record in result.errors if record["stage"] == "IMAGE"]
    assert image_errors[0]["type"] == "DECODE_ERROR"
    assert image_errors[-1]["outcome"] == "REVIEW_REQUIRED"
    assert result.execution_summary["IMAGE"] is StageState.FAILED


def test_a_failed_stage_is_retried_when_the_policy_allows_it(
    tmp_path: Path, processors: ProcessorDoubles
) -> None:
    """The whole processor is attempted again, up to the documented ceiling."""
    processors.image.fail = True

    result = process_document(
        document_request(tmp_path, execution=execution_policy(retry_failed=True))
    )

    assert len(processors.image.requests) == 2
    assert result.execution_summary["IMAGE"] is StageState.FAILED


def test_a_failed_stage_is_not_retried_when_the_policy_forbids_it(
    tmp_path: Path, processors: ProcessorDoubles
) -> None:
    """A policy that forbids retries is honoured on the first failure."""
    processors.image.fail = True

    result = process_document(
        document_request(tmp_path, execution=execution_policy(retry_failed=False))
    )

    assert len(processors.image.requests) == 1
    assert result.status == "REVIEW_REQUIRED"
