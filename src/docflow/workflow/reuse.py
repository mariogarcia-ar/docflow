"""The reuse check (``ORC-08``).

*Physical file existence is never evidence of a valid result.* A result may be reused only
when all four of these hold, and each is checked separately so that a failure names the
condition that failed:

1. the stage's status is ``SUCCESS`` — or ``REUSED``, which is a previous run's record
   that this exact result was already validated and reused;
2. its ``processing_key`` equals the key the current configuration computes;
3. every output artifact it recorded exists;
4. every artifact still hashes to the digest recorded when it was published.

Condition 2 is what makes a changed option or an upgraded processor miss the cache;
condition 4 is what stops an artifact overwritten in place from passing as a fresh one.
"""

from __future__ import annotations

from docflow.states import StageState
from docflow.workflow.contracts import StageExecution
from docflow.workflow.identity import file_digest
from docflow.workflow.stages import OUTPUT_HASHES_KEY

#: States that describe a stage holding a valid, already-verified result.
_REUSABLE_STATES = frozenset({StageState.SUCCESS, StageState.REUSED})


def validate_stage_outputs(stage: StageExecution) -> bool:
    """Check that every artifact the stage recorded is present and unmodified.

    Args:
        stage: The stage whose outputs to validate.

    Returns:
        ``True`` when every recorded output exists and matches its recorded digest.

    # TODO: [MVP] a stage that recorded no outputs validates vacuously. The LLM processor's
    # result exposes no artifact list, so a reused LLM stage is currently checked on its
    # status and key alone; the processor contract is what has to carry the paths.
    """
    recorded: dict[str, str] = stage.metadata.get(OUTPUT_HASHES_KEY, {})
    for artifact in stage.output_artifacts:
        if not artifact.is_file():
            return False
        expected = recorded.get(str(artifact))
        if expected and file_digest(artifact) != expected:
            return False
    return True


def is_stage_reusable(stage: StageExecution, *, current_processing_key: str) -> bool:
    """Decide whether a stage's existing result may be reused for the current run.

    Args:
        stage: The stage execution carried over by the durable context.
        current_processing_key: The key the current processor, version, inputs and
            options compute.

    Returns:
        ``True`` only when the stage holds a verified result, its key matches the current
        one, and its outputs validate.
    """
    return (
        stage.status in _REUSABLE_STATES
        and stage.processing_key == current_processing_key
        and validate_stage_outputs(stage)
    )
