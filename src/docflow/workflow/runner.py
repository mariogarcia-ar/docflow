"""The shared stage lifecycle: resolve, claim, invoke, record.

Both execution paths — the document-level PDF stage and the per-page stages — move through
the same six steps, and this module is where that sequence exists exactly once:

1. **resolve** the stage against the reuse rule and the policy (``ORC-07``, ``ORC-08``);
2. **record** the decision, with its reason, before acting on it;
3. **skip**, **block** or **reuse** without calling anything, when that is the resolution;
4. **claim** the stage for this run, which is what makes a second claimer fail;
5. **invoke** the processor, and treat its typed failure as an outcome rather than an
   exception (``ORC-16``);
6. **retry** the whole processor when policy allows, up to the documented ceiling.

The owner is this run's identity plus the stage's, so a claim records who holds the stage
and a release can only be done by its holder.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docflow.states import StageState
from docflow.workflow import configuration, keys
from docflow.workflow.contracts import (
    DocumentContext,
    DocumentRequest,
    PageContext,
    StageAction,
    StageExecution,
    StageName,
)
from docflow.workflow.errors import handle_processor_error
from docflow.workflow.invocation import describe_failure, result_succeeded
from docflow.workflow.resolution import resolve_stage
from docflow.workflow.reuse import is_stage_reusable
from docflow.workflow.stages import (
    OWNER_KEY,
    claim_stage,
    create_stage,
    set_stage_status,
)
from docflow.workflow.tracing import register_decision

#: Actions that mean the processor is not called.
_PASSIVE: frozenset[StageAction] = frozenset({"SKIP", "REUSE", "BLOCKED", "WAIT"})


@dataclass
class StageOutcome:
    """What happened to one stage.

    Attributes:
        execution: The stage execution, carrying its final status.
        action: The action the resolution chose.
        reason: Why it was chosen.
        result: The processor's typed result, or ``None`` when no processor ran.
    """

    execution: StageExecution
    action: StageAction
    reason: str
    result: Any


def owner_for(context: DocumentContext, execution: StageExecution) -> str:
    """Return the claim owner of one stage: this run, for this stage.

    Args:
        context: The document context.
        execution: The stage being claimed.

    Returns:
        An identifier unique to (run, stage).
    """
    return f"{context.workflow_run_id}:{execution.stage_id}"


def stage_execution(
    context: DocumentContext,
    page: PageContext | None,
    request: DocumentRequest,
    stage: StageName,
) -> StageExecution:
    """Return the stage execution for a stage, creating it if the run never had one.

    An execution carried over from a durable context is returned **as it was stored**,
    key included: the reuse rule compares the stored key against the one the current
    configuration computes, so overwriting the stored value with the current one here
    would make every stage look reusable.

    Args:
        context: The document context.
        page: The page the stage belongs to, or ``None`` for a document-level stage.
        request: The request being served.
        stage: Which stage.

    Returns:
        The stage execution, registered on the document or on the page.
    """
    owner: DocumentContext | PageContext = context if page is None else page
    existing = owner.stages.get(stage)
    if existing is not None:
        return existing
    processor, version = configuration.PROCESSOR_IDENTITIES[stage]
    inputs = tuple(
        item
        for item in keys.stage_inputs(context, page, stage)
        if isinstance(item, Path)
    )
    created = create_stage(
        stage,
        processor=processor,
        processor_version=version,
        processing_key=keys.stage_key(context, request, stage, page),
        options_hash=keys.stage_options_hash(request, stage),
        input_artifacts=inputs,
        page_number=None if page is None else page.page_number,
    )
    owner.stages[stage] = created
    return created


def run_stage(
    context: DocumentContext,
    page: PageContext | None,
    request: DocumentRequest,
    execution: StageExecution,
    *,
    invoke: Callable[[StageExecution], Any],
    skip_reason: str | None = None,
    input_available: bool = True,
) -> StageOutcome:
    """Resolve one stage and carry it out, reporting rather than raising a failure.

    Args:
        context: The document context.
        page: The page the stage belongs to, or ``None`` for a document-level stage.
        request: The request being served.
        execution: The stage execution to run.
        invoke: The processor call, taking the stage so it can register its artifacts.
        skip_reason: A routing reason to skip the stage, when the run has one.
        input_available: Whether the stage's input exists.

    Returns:
        The outcome: the action taken, the reason, and the processor's result when one ran.
    """
    current_key = keys.stage_key(context, request, execution.stage, page)
    reusable = is_stage_reusable(execution, current_processing_key=current_key)
    resolution = resolve_stage(
        execution.stage,
        policy=request.execution,
        processing_key=current_key,
        reusable=reusable,
        input_available=input_available,
        skip_reason=skip_reason,
        prior_status=execution.status,
    )
    register_decision(
        context if page is None else page,
        stage=execution.stage,
        action=resolution.action,
        reason=resolution.reason,
        page_number=None if page is None else page.page_number,
    )
    if resolution.action in _PASSIVE:
        return _passive_outcome(execution, resolution.action, resolution.reason)

    if resolution.action == "FORCE":
        execution.force_reason = resolution.reason
    execution.processing_key = current_key
    execution.options_hash = keys.stage_options_hash(request, execution.stage)
    return _invoke_until_settled(
        context, page, execution, invoke, reason=resolution.reason
    )


def _passive_outcome(
    execution: StageExecution, action: StageAction, reason: str
) -> StageOutcome:
    """Record a stage that no processor ran for, and return its outcome."""
    if action == "SKIP":
        set_stage_status(execution, StageState.SKIPPED, reason=reason)
    elif action == "REUSE":
        set_stage_status(execution, StageState.REUSED, reason=reason)
    return StageOutcome(execution=execution, action=action, reason=reason, result=None)


def _invoke_until_settled(
    context: DocumentContext,
    page: PageContext | None,
    execution: StageExecution,
    invoke: Callable[[StageExecution], Any],
    *,
    reason: str,
) -> StageOutcome:
    """Claim and invoke a stage, retrying the whole processor while policy allows.

    A stage that cannot be claimed is reported as ``WAIT`` rather than forced: another
    owner holds it, and running it anyway is exactly the double execution the claim exists
    to prevent.
    """
    owner = owner_for(context, execution)
    while True:
        _ready_for_claim(execution)
        if not claim_stage(execution, owner):
            return StageOutcome(
                execution=execution,
                action="WAIT",
                reason="stage_held_by_another_owner",
                result=None,
            )
        result = invoke(execution)
        if result_succeeded(result):
            set_stage_status(execution, StageState.SUCCESS)
            return StageOutcome(
                execution=execution, action="EXECUTE", reason=reason, result=result
            )
        outcome = handle_processor_error(
            context,
            page,
            execution,
            failure=describe_failure(result),
        )
        if outcome != "retry processor":
            return StageOutcome(
                execution=execution, action="EXECUTE", reason=reason, result=result
            )


def _ready_for_claim(execution: StageExecution) -> None:
    """Make a stage claimable by this run, recovering one left held by an interrupted run."""
    execution.metadata.pop(OWNER_KEY, None)
    set_stage_status(execution, StageState.READY)
