"""Durable context primitives (``ORC-03``)."""

from __future__ import annotations

from pathlib import Path

import pytest

from docflow.states import StageState
from docflow.workflow.context import (
    PAGE_ARTIFACT_KEYS,
    create_document_context,
    create_page_context,
    document_context_payload,
    get_page_context,
    load_document_context,
    save_document_context,
)
from docflow.workflow.contracts import DocumentContext
from docflow.workflow.persistence import WorkflowPersistenceError
from tests.workflow.samples import (
    artifact,
    decision_record,
    document_request,
    error_record,
)
from tests.workflow.samples import stage as build_stage


def _populated_context(tmp_path: Path) -> DocumentContext:
    """Return a context with one page, one stage, one decision and one error."""
    request = document_request(tmp_path)
    context = create_document_context(
        request, input_type="PDF", workflow_run_id="run-1"
    )
    page = create_page_context(1)
    native_text = artifact(tmp_path, "text.txt", b"some text")
    page.artifacts["native_text"] = native_text
    page.selected_source = "NATIVE_TEXT"
    page.extraction_strategy = "TEXT_ONLY"
    page.status = StageState.SUCCESS
    page.stages["OCR"] = build_stage(
        "OCR",
        status=StageState.SKIPPED,
        reason="native_text_present",
        input_artifacts=(native_text,),
    )
    page.decisions.append(decision_record("OCR", "SKIP", "native_text_present"))
    page.errors.append(error_record("OCR", "IO_ERROR", message="no"))
    context.pages.append(page)
    context.decisions.append(
        decision_record("SOURCE", "NATIVE_TEXT", "native_text_present")
    )
    context.status = "PAUSED"
    context.final_result = {"pages": []}
    return context


def test_a_page_context_states_every_absent_artifact() -> None:
    """Absence is stated once per artifact key, never inferred from a missing key."""
    page = create_page_context(1)

    assert tuple(page.artifacts) == PAGE_ARTIFACT_KEYS
    assert all(value is None for value in page.artifacts.values())


def test_a_new_document_context_has_no_pages() -> None:
    """A context does not claim a structure nobody read."""
    context = create_document_context(
        document_request(Path("/tmp")), input_type="PDF", workflow_run_id="run-1"
    )

    assert not context.pages
    assert context.status == "PAUSED"


def test_a_context_round_trips_exactly(tmp_path: Path) -> None:
    """Identity, pages, stages, decisions and errors survive a save and a load."""
    context = _populated_context(tmp_path)

    path = save_document_context(context, tmp_path / "state.json")
    loaded = load_document_context(path)

    assert document_context_payload(loaded) == document_context_payload(context)


def test_an_interrupted_write_leaves_nothing_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Neither a partial record nor a ``.tmp`` residue survives a failed save."""
    context = _populated_context(tmp_path)
    destination = tmp_path / "state.json"

    def refuse_replace(source: Path, target: Path) -> None:
        raise OSError("interrupted")

    monkeypatch.setattr("docflow.workflow.persistence.os.replace", refuse_replace)

    with pytest.raises(WorkflowPersistenceError):
        save_document_context(context, destination)

    assert not destination.exists()
    assert not list(tmp_path.glob("*.tmp"))


def test_a_missing_record_cannot_be_loaded(tmp_path: Path) -> None:
    """Reading a record that is not there is an error, not an empty context."""
    with pytest.raises(WorkflowPersistenceError):
        load_document_context(tmp_path / "absent.json")


def test_a_document_has_no_page_it_never_read(tmp_path: Path) -> None:
    """Looking up an unknown page is an error, never an empty page."""
    context = create_document_context(
        document_request(tmp_path), input_type="PDF", workflow_run_id="run-1"
    )

    with pytest.raises(LookupError):
        get_page_context(context, 3)
