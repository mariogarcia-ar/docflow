"""The dependency graph and downstream invalidation (``ORC-09``)."""

from __future__ import annotations

from pathlib import Path

from docflow.states import StageState
from docflow.workflow import dependencies
from docflow.workflow.context import create_document_context, create_page_context
from docflow.workflow.contracts import DocumentContext, StageExecution, StageName
from docflow.workflow.stages import set_stage_status
from tests.workflow.samples import artifact, document_request
from tests.workflow.samples import stage as build_stage


def _succeeded(
    tmp_path: Path, stage_name: StageName, page_number: int
) -> StageExecution:
    """Return a succeeded stage that published one artifact."""
    return build_stage(
        stage_name,
        page_number=page_number,
        status=StageState.SUCCESS,
        output=(artifact(tmp_path, f"{stage_name}-{page_number}.txt"),),
    )


def _context(tmp_path: Path) -> DocumentContext:
    """Return a context with one page whose OCR and LLM stages succeeded."""
    context = create_document_context(
        document_request(tmp_path), input_type="PDF", workflow_run_id="run-1"
    )
    page = create_page_context(1)
    page.stages["OCR"] = _succeeded(tmp_path, "OCR", 1)
    page.stages["LLM"] = _succeeded(tmp_path, "LLM", 1)
    context.pages.append(page)
    return context


def test_the_graph_is_data() -> None:
    """The dependency table is what the closure is derived from."""
    assert dependencies.dependencies_of("OCR") == ("IMAGE",)
    assert dependencies.downstream_of("OCR") == ("LLM",)
    assert set(dependencies.downstream_of("PDF")) == {"IMAGE", "OCR", "LLM"}
    assert not dependencies.downstream_of("LLM")


def test_invalidation_marks_the_dependents_and_records_the_cause(
    tmp_path: Path,
) -> None:
    """A dependent's result goes stale, and the record says why."""
    context = _context(tmp_path)

    invalidated = dependencies.invalidate_downstream(
        context, "OCR", cause="forced_upstream_OCR"
    )

    assert [execution.stage for execution in invalidated] == ["LLM"]
    llm = context.pages[0].stages["LLM"]
    assert llm.status is StageState.INVALIDATED
    assert llm.metadata["invalidated_by"] == "OCR"
    decisions = [
        record for record in context.pages[0].decisions if record.get("stage") == "LLM"
    ]
    assert decisions[0]["action"] == "INVALIDATED"
    assert decisions[0]["reason"] == "forced_upstream_OCR"


def test_invalidation_preserves_the_historical_artifacts(tmp_path: Path) -> None:
    """The previous attempt's output stays on disk; it is only never reused."""
    context = _context(tmp_path)
    llm = context.pages[0].stages["LLM"]

    dependencies.invalidate_downstream(context, "OCR", cause="forced_upstream_OCR")

    assert all(artifact.is_file() for artifact in llm.output_artifacts)


def test_a_stage_that_holds_no_result_is_not_invalidated(tmp_path: Path) -> None:
    """A skip is persistent, and a stage that never ran has nothing to lose."""
    context = _context(tmp_path)
    page = context.pages[0]
    skipped = _succeeded(tmp_path, "IMAGE", 1)
    set_stage_status(skipped, StageState.SKIPPED, reason="explicit_skip")
    page.stages["IMAGE"] = skipped

    invalidated = dependencies.invalidate_downstream(
        context, "PDF", cause="forced_upstream_PDF"
    )

    assert [execution.stage for execution in invalidated] == ["OCR", "LLM"]
    assert page.stages["IMAGE"].status is StageState.SKIPPED
    assert page.stages["OCR"].status is StageState.INVALIDATED
