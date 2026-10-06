"""Stage primitives (``ORC-04``)."""

from __future__ import annotations

from pathlib import Path

import pytest

from docflow.states import StageState
from docflow.workflow.contracts import StageExecution
from docflow.workflow.stages import (
    claim_stage,
    create_stage,
    register_stage_outputs,
    release_stage,
    set_stage_status,
    stage_id_for,
)
from tests.workflow.samples import stage as build_stage


def _stage(tmp_path: Path) -> StageExecution:
    """Return a fresh stage execution for a page-level stage."""
    return build_stage("OCR", page_number=2, input_artifacts=(tmp_path / "page.png",))


def test_a_stage_starts_not_started() -> None:
    """A stage that has not been resolved is not assumed ready."""
    stage = create_stage(
        "OCR",
        processor="ocr",
        processor_version="0.0.0",
        processing_key="key",
        options_hash="digest",
        input_artifacts=[],
        page_number=None,
    )

    assert stage.status is StageState.NOT_STARTED
    assert stage.attempts == 0
    assert stage.stage_id == "OCR:document"


def test_the_stage_id_names_the_page(tmp_path: Path) -> None:
    """A stage is identifiable by stage and page."""
    assert stage_id_for("OCR", 2) == "OCR:2"
    assert _stage(tmp_path).stage_id == "OCR:2"


def test_only_the_first_claim_succeeds(tmp_path: Path) -> None:
    """Two owners cannot both believe they hold the stage."""
    stage = _stage(tmp_path)
    stage.status = StageState.READY

    assert claim_stage(stage, "owner-a") is True
    assert stage.status is StageState.RUNNING
    assert stage.attempts == 1
    assert claim_stage(stage, "owner-b") is False


def test_releasing_returns_the_stage_to_ready(tmp_path: Path) -> None:
    """A released stage can be claimed again."""
    stage = _stage(tmp_path)
    stage.status = StageState.READY
    claim_stage(stage, "owner-a")

    assert release_stage(stage, "owner-b") is False
    assert release_stage(stage, "owner-a") is True
    assert stage.status is StageState.READY
    assert claim_stage(stage, "owner-b") is True


def test_a_deliberate_outcome_must_state_its_reason(tmp_path: Path) -> None:
    """A skip with no reason is not a trace, so it is refused."""
    stage = _stage(tmp_path)

    with pytest.raises(ValueError, match="must state why"):
        set_stage_status(stage, StageState.SKIPPED)

    set_stage_status(stage, StageState.SKIPPED, reason="native_text_present")
    assert stage.skip_reason == "native_text_present"
    assert stage.finished_at is not None


def test_a_reused_stage_is_not_recorded_as_a_skip(tmp_path: Path) -> None:
    """The two outcomes stay distinguishable in the record."""
    stage = _stage(tmp_path)
    set_stage_status(stage, StageState.REUSED, reason="valid_result_reused")

    assert stage.status is StageState.REUSED
    assert stage.skip_reason is None


def test_published_artifacts_are_recorded_with_their_digests(tmp_path: Path) -> None:
    """The digest is what a later run compares, so it is recorded at publication."""
    artifact = tmp_path / "text.txt"
    artifact.write_text("extracted", encoding="utf-8")
    stage = _stage(tmp_path)

    register_stage_outputs(stage, [artifact])

    assert stage.output_artifacts == [artifact]
    assert stage.metadata["output_hashes"][str(artifact)]
