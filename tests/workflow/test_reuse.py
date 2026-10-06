"""The reuse check (``ORC-08``).

Each of the rule's four conditions is violated in turn; the file that exists on disk is
never evidence on its own.
"""

from __future__ import annotations

from pathlib import Path

from docflow.states import StageState
from docflow.workflow.contracts import StageExecution
from docflow.workflow.reuse import is_stage_reusable, validate_stage_outputs
from docflow.workflow.stages import set_stage_status
from tests.workflow.samples import artifact
from tests.workflow.samples import stage as build_stage


def _succeeded_stage(tmp_path: Path) -> StageExecution:
    """Return a stage that succeeded and published one artifact."""
    return build_stage(
        "OCR",
        status=StageState.SUCCESS,
        output=(artifact(tmp_path, "text.txt", b"extracted"),),
    )


def test_a_successful_stage_with_a_matching_key_is_reusable(tmp_path: Path) -> None:
    """All four conditions hold."""
    stage = _succeeded_stage(tmp_path)

    assert is_stage_reusable(stage, current_processing_key="key") is True


def test_a_stage_that_never_succeeded_is_not_reusable(tmp_path: Path) -> None:
    """A status that is not a success is not a result."""
    stage = _succeeded_stage(tmp_path)
    stage.status = StageState.NOT_STARTED

    assert is_stage_reusable(stage, current_processing_key="key") is False


def test_a_different_processing_key_is_not_reusable(tmp_path: Path) -> None:
    """An option change misses the cache even though the artifact is still there."""
    stage = _succeeded_stage(tmp_path)

    assert stage.output_artifacts[0].is_file()
    assert is_stage_reusable(stage, current_processing_key="other") is False


def test_a_missing_artifact_is_not_reusable(tmp_path: Path) -> None:
    """A published artifact that is gone is not a valid output."""
    stage = _succeeded_stage(tmp_path)
    stage.output_artifacts[0].unlink()

    assert validate_stage_outputs(stage) is False
    assert is_stage_reusable(stage, current_processing_key="key") is False


def test_a_modified_artifact_is_not_reusable(tmp_path: Path) -> None:
    """An artifact rewritten in place is not the one this stage produced."""
    stage = _succeeded_stage(tmp_path)
    stage.output_artifacts[0].write_text("something else", encoding="utf-8")

    assert validate_stage_outputs(stage) is False
    assert is_stage_reusable(stage, current_processing_key="key") is False


def test_a_reused_stage_stays_reusable(tmp_path: Path) -> None:
    """A stage a previous run already recorded as reused still holds its result."""
    stage = _succeeded_stage(tmp_path)
    set_stage_status(stage, StageState.REUSED, reason="valid_result_reused")

    assert is_stage_reusable(stage, current_processing_key="key") is True
