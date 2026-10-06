"""Building the execution plan (``ORC-06``)."""

from __future__ import annotations

from pathlib import Path

from docflow.states import StageState
from docflow.workflow.context import create_document_context, create_page_context
from docflow.workflow.contracts import DocumentContext, DocumentRequest
from docflow.workflow.entrypoints import process_document
from docflow.workflow.planning import build_execution_plan
from docflow.workflow.resume import load_resumable_context
from tests.fakes.processors import ProcessorDoubles
from tests.workflow.samples import document_request, execution_policy, state_file

ACTIONS = {"EXECUTE", "REUSE", "SKIP", "FORCE", "WAIT", "BLOCKED"}


def _context_with_one_page(tmp_path: Path, request: DocumentRequest) -> DocumentContext:
    """Return a context with a page whose image and native text exist."""
    context = create_document_context(
        request, input_type="PDF", workflow_run_id="run-1"
    )
    page = create_page_context(1)
    image = tmp_path / "page.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    page.artifacts["page_image"] = image
    text = tmp_path / "text.txt"
    text.write_text("native", encoding="utf-8")
    page.artifacts["native_text"] = text
    context.pages.append(page)
    return context


def test_every_plan_entry_carries_a_computed_key(tmp_path: Path) -> None:
    """A plan entry without a key is a promise the reuse rule cannot check."""
    request = document_request(tmp_path)
    context = _context_with_one_page(tmp_path, request)

    plan = build_execution_plan(context, request)

    assert [entry.stage for entry in plan.stages] == ["IMAGE", "OCR", "LLM"]
    assert all(entry.processing_key for entry in plan.stages)
    assert {entry.action for entry in plan.stages} <= ACTIONS
    assert plan.dry_run is False


def test_the_native_text_skips_ocr_and_records_the_reason(tmp_path: Path) -> None:
    """The plan already knows OCR is not needed, and says why."""
    request = document_request(tmp_path)
    context = _context_with_one_page(tmp_path, request)

    plan = build_execution_plan(context, request)

    ocr = next(entry for entry in plan.stages if entry.stage == "OCR")
    assert ocr.action == "SKIP"
    assert ocr.reason == "native_text_present"


def test_an_explicit_skip_reaches_the_plan(tmp_path: Path) -> None:
    """The caller's stated skip is resolved, not deferred to the execution path."""
    request = document_request(
        tmp_path, execution=execution_policy(skip_stages=["IMAGE"])
    )
    context = _context_with_one_page(tmp_path, request)

    plan = build_execution_plan(context, request)

    image = next(entry for entry in plan.stages if entry.stage == "IMAGE")
    assert image.action == "SKIP"
    assert image.reason == "explicit_skip"


def test_a_forced_stage_is_planned_as_forced(tmp_path: Path) -> None:
    """A force is visible in the plan before anything runs."""
    request = document_request(
        tmp_path, execution=execution_policy(force_stages=["OCR"])
    )
    context = _context_with_one_page(tmp_path, request)

    plan = build_execution_plan(context, request)

    ocr = next(entry for entry in plan.stages if entry.stage == "OCR")
    assert ocr.action == "FORCE"
    assert ocr.reason == "forced_by_policy"


def test_planning_invokes_no_processor(tmp_path: Path) -> None:
    """The plan is built from the durable state and the request, and from nothing else."""
    doubles = ProcessorDoubles()
    request = document_request(tmp_path)
    context = _context_with_one_page(tmp_path, request)

    build_execution_plan(context, request)

    assert doubles.calls() == {"pdf": 0, "image": 0, "ocr": 0, "llm": 0}


def test_a_reused_stage_is_planned_as_reused(
    tmp_path: Path, processors: ProcessorDoubles
) -> None:
    """The plan of a resumed run reads the durable result."""
    processors.pdf.text = ""
    first = document_request(
        tmp_path, execution=execution_policy(stop_after_stage="OCR")
    )
    process_document(first)
    assert state_file(tmp_path).is_file()

    loaded = load_resumable_context(state_file(tmp_path))
    assert loaded is not None
    resumed = document_request(tmp_path, execution=execution_policy(resume=True))

    plan = build_execution_plan(loaded, resumed)

    assert next(entry for entry in plan.stages if entry.stage == "PDF").action in {
        "REUSE",
        "SKIP",
    }
    assert loaded.stages["PDF"].status is StageState.SUCCESS
