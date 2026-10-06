"""Resolving one stage to an action, in a fixed and auditable order (``ORC-07``).

The order is the contract, and it is short enough to state in full:

1. a stage named in ``skip_stages`` is **skipped** — the caller said so, and that wins;
2. a stage named in ``force_stages`` is **forced** — paying again is the point;
3. a routing reason ("the native text is present, OCR is not needed") is a **skip**;
4. a stage whose result validates and whose key matches is **reused**;
5. a stage whose input can never appear is **blocked**;
6. everything else **executes**.

Steps 1 and 2 are the caller's words and outrank what the run could deduce; step 3 is what
the run deduced and must not outrank a force, or forcing OCR on a page with native text
would be impossible. Whichever branch wins, the **reason travels with the decision**: a
stage is never resolved to something the record cannot explain.
"""

from __future__ import annotations

from docflow.states import StageState
from docflow.workflow.contracts import (
    ExecutionPolicy,
    StageAction,
    StageName,
    StageResolution,
)

#: The workflow's stage order. Used to decide whether a stage precedes ``start_from_stage``.
STAGE_ORDER: tuple[StageName, ...] = ("PDF", "IMAGE", "OCR", "LLM")


def _precedes(stage: StageName, boundary: str | None) -> bool:
    """Return whether ``stage`` comes before ``boundary`` in the workflow order."""
    if boundary is None or boundary not in STAGE_ORDER:
        return False
    return STAGE_ORDER.index(stage) < STAGE_ORDER.index(boundary)


def resolve_stage(  # pylint: disable=too-many-return-statements
    stage: StageName,
    *,
    policy: ExecutionPolicy,
    processing_key: str,
    reusable: bool,
    input_available: bool = True,
    skip_reason: str | None = None,
    prior_status: StageState | None = None,
) -> StageResolution:
    """Decide what the run does with one stage.

    # Reason for the suppression above: one return per step of the decision order is the
    # contract itself (``ORC-07``); folding two steps into one branch would hide the order.

    Args:
        stage: The stage being resolved.
        policy: The operational policy in force.
        processing_key: The key the current configuration computes for this stage.
        reusable: Whether an existing result passes the reuse rule.
        input_available: Whether the stage's input exists or will exist in this run.
        skip_reason: A routing reason to skip, e.g. ``native_text_present``.
        prior_status: The state the durable record left the stage in, when it had one.
            ``FAILED`` is the only value that changes the outcome: a stage that failed in
            a previous run is retried only when the policy allows it.

    Returns:
        The action and the reason it was chosen.
    """

    def resolution(action: StageAction, reason: str) -> StageResolution:
        return StageResolution(
            stage=stage,
            action=action,
            reason=reason,
            processing_key=processing_key,
        )

    if stage in policy.skip_stages:
        return resolution("SKIP", "explicit_skip")
    if stage in policy.force_stages:
        return resolution("FORCE", "forced_by_policy")
    if skip_reason is not None:
        return resolution("SKIP", skip_reason)
    if prior_status is StageState.FAILED and not policy.retry_failed:
        return resolution("BLOCKED", "failed_and_retry_disabled")
    if not input_available:
        return resolution("BLOCKED", "input_unavailable")
    if reusable and policy.reuse_successful:
        return resolution("REUSE", "valid_result_reused")
    if _precedes(stage, policy.start_from_stage):
        # The caller started the run later in the workflow, so nothing before that point
        # may execute; without a reusable result the run cannot proceed coherently.
        return resolution("BLOCKED", "before_start_stage_without_result")
    return resolution("EXECUTE", "no_valid_result")
