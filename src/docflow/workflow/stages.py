"""Stage primitives: the atomic control unit of the workflow (``ORC-04``).

A stage is the smallest thing the orchestrator can decide about, so it is also the smallest
thing it can hand to one owner. The transitions here are the whole lifecycle:

``NOT_STARTED`` → ``READY`` → ``RUNNING`` → ``SUCCESS`` / ``FAILED``

plus the deliberate outcomes ``SKIPPED`` (not run on purpose), ``REUSED`` (a valid result
already existed) and ``INVALIDATED`` (a predecessor changed), and ``PAUSED`` for a stage the
declared stop leaves untouched.

**Claiming is the concurrency primitive.** ``claim_stage`` moves a stage from ``READY`` to
``RUNNING`` only when no other owner holds it, and ``release_stage`` returns it to ``READY``
only for the owner that holds it. The PoC runs pages sequentially, so no two threads race
today; the transition rule exists so that turning ``parallel_pages`` on does not require
re-deciding who may run what.

# TODO: [MVP] the claim is an in-process transition, not a lock: a second process holding
# the same document would not be refused. Cross-process coordination is a Phase-4 concern.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from docflow.states import StageState
from docflow.workflow.contracts import StageExecution, StageName
from docflow.workflow.identity import file_digest

#: Key under which a claim records its owner inside ``StageExecution.metadata``.
OWNER_KEY = "owner"

#: Key under which published artifacts record their digests, for the reuse check.
OUTPUT_HASHES_KEY = "output_hashes"

#: States a stage reaches when it is finished with, whatever the outcome.
TERMINAL_STATES = frozenset(
    {
        StageState.SUCCESS,
        StageState.FAILED,
        StageState.SKIPPED,
        StageState.REUSED,
        StageState.INVALIDATED,
    }
)


def now() -> str:
    """Return the current UTC timestamp in ISO form.

    Returns:
        The timestamp, so a stage records when it ran.
    """
    return datetime.now(UTC).isoformat()


def stage_id_for(stage: StageName, page_number: int | None) -> str:
    """Return the identifier of one stage of one page, or of the document.

    Args:
        stage: The stage.
        page_number: The page, or ``None`` for a document-level stage.

    Returns:
        A stable identifier such as ``OCR:2`` or ``PDF:document``.
    """
    return f"{stage}:{page_number}" if page_number is not None else f"{stage}:document"


def create_stage(
    stage: StageName,
    *,
    processor: str,
    processor_version: str,
    processing_key: str,
    options_hash: str,
    input_artifacts: Iterable[Path],
    page_number: int | None,
    metadata: dict[str, Any] | None = None,
) -> StageExecution:
    """Create a stage execution in ``NOT_STARTED``.

    Args:
        stage: Which stage of the workflow.
        processor: The processor that owns it.
        processor_version: That processor's version.
        processing_key: The key its result will belong to.
        options_hash: Digest of the normalized options in force.
        input_artifacts: What the stage consumes.
        page_number: The page it belongs to, or ``None`` for a document-level stage.
        metadata: Anything else worth tracing.

    Returns:
        The new stage execution. It is ``NOT_STARTED``, never ``READY``: a stage becomes
        ready when its dependencies are satisfied, and assuming it here would claim a
        precondition nobody checked.
    """
    return StageExecution(
        stage_id=stage_id_for(stage, page_number),
        stage=stage,
        processor=processor,
        processor_version=processor_version,
        status=StageState.NOT_STARTED,
        processing_key=processing_key,
        input_artifacts=list(input_artifacts),
        output_artifacts=[],
        options_hash=options_hash,
        attempts=0,
        started_at=None,
        finished_at=None,
        skip_reason=None,
        force_reason=None,
        error=None,
        metadata={} if metadata is None else dict(metadata),
    )


def set_stage_status(
    stage: StageExecution,
    status: StageState,
    *,
    reason: str | None = None,
    error: dict[str, Any] | None = None,
) -> StageExecution:
    """Move a stage to ``status`` and record why it moved.

    Args:
        stage: The stage to transition.
        status: The state it reaches.
        reason: Why, for ``SKIPPED`` and ``REUSED``. Stating it is required for those two,
            because "we chose not to pay" and "we did not have to pay" are only
            distinguishable by the reason they carry.
        error: The error record, when the status is ``FAILED``.

    Returns:
        The same stage, mutated.

    Raises:
        ValueError: When a deliberate outcome is recorded without its reason.
    """
    if status in (StageState.SKIPPED, StageState.REUSED) and not reason:
        raise ValueError(f"a {status} stage must state why it did not run")
    stage.status = status
    if status is StageState.SKIPPED:
        stage.skip_reason = reason
    if status is StageState.FAILED:
        stage.error = error
    if status in TERMINAL_STATES:
        stage.finished_at = now()
    return stage


def claim_stage(stage: StageExecution, owner: str) -> bool:
    """Claim a ready stage for ``owner``, moving it to ``RUNNING``.

    Args:
        stage: The stage to claim.
        owner: Identifier of the claimer.

    Returns:
        ``True`` when this call took the stage, ``False`` when it was not claimable —
        because it is not ``READY``, or because another owner already holds it. A second
        claim never succeeds, so two callers cannot both believe they own the stage.
    """
    if stage.status is not StageState.READY:
        return False
    held = stage.metadata.get(OWNER_KEY)
    if held is not None and held != owner:
        return False
    stage.metadata[OWNER_KEY] = owner
    stage.status = StageState.RUNNING
    stage.started_at = now()
    stage.attempts += 1
    return True


def release_stage(stage: StageExecution, owner: str) -> bool:
    """Release a ``RUNNING`` stage back to ``READY``, for the owner that holds it.

    Args:
        stage: The stage to release.
        owner: Identifier of the claimer asking to release.

    Returns:
        ``True`` when the stage was released and can be claimed again, ``False`` when the
        caller does not hold it or it is not ``RUNNING``.
    """
    if stage.status is not StageState.RUNNING:
        return False
    if stage.metadata.get(OWNER_KEY) != owner:
        return False
    del stage.metadata[OWNER_KEY]
    stage.status = StageState.READY
    return True


def register_stage_outputs(
    stage: StageExecution, artifacts: Iterable[Path]
) -> StageExecution:
    """Record the artifacts a stage published, with the digest of each.

    The digests are what ``validate_stage_outputs`` compares on a later run, so an artifact
    that was overwritten in place between two runs is not mistaken for the one this stage
    produced.

    Args:
        stage: The stage that published them.
        artifacts: The paths it published.

    Returns:
        The same stage, mutated.
    """
    hashes: dict[str, str] = stage.metadata.setdefault(OUTPUT_HASHES_KEY, {})
    for artifact in artifacts:
        if artifact not in stage.output_artifacts:
            stage.output_artifacts.append(artifact)
        hashes[str(artifact)] = file_digest(artifact) if artifact.is_file() else ""
    return stage
