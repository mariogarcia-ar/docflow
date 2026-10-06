"""Building the execution plan, and the dry run that inspects it (``ORC-06``).

The plan is the run's intentions written down before anything costly happens: for every
stage the run has, which action it resolved to and why. Building it invokes no processor —
that is the whole point of ``dry_run``, and it is also why the plan is useful without it.

Two things are computed here rather than later, because both are *decisions* and not
side effects:

* **downstream invalidation.** A forced stage makes its dependents stale before the plan is
  drawn, so the plan shows what the run will actually do rather than the world as it was;
* **availability.** A stage whose input will be produced earlier in this same plan is
  available; one whose producer was skipped or blocked is ``BLOCKED``, which is the honest
  distinction between "not yet" and "never".

Every entry carries a computed processing key. A plan entry without one would be a promise
the reuse rule cannot check.
"""

from __future__ import annotations

from typing import cast

from docflow.workflow import runner
from docflow.workflow.contracts import (
    DocumentContext,
    DocumentRequest,
    ExecutionPlan,
    PageContext,
    PlannedStage,
    StageAction,
    StageExecution,
    StageName,
    StageResolution,
)
from docflow.workflow.dependencies import invalidate_downstream
from docflow.workflow.keys import (
    STAGE_OUTPUT_KEYS,
    document_text,
    image_source,
    ocr_source,
    stage_key,
    vlm_source,
)
from docflow.workflow.resolution import STAGE_ORDER, resolve_stage
from docflow.workflow.reuse import is_stage_reusable
from docflow.workflow.selection import (
    ARTIFACT_NATIVE_TEXT,
    ARTIFACT_OCR_TEXT,
    ocr_skip_reason,
    readable,
)

#: Page stages, in the order the plan walks them.
PAGE_STAGES: tuple[StageName, ...] = ("IMAGE", "OCR", "LLM")

#: Actions that mean "this stage will produce its outputs in this run".
_PRODUCING: frozenset[StageAction] = frozenset({"EXECUTE", "FORCE", "REUSE"})


def apply_forces(
    context: DocumentContext, request: DocumentRequest
) -> list[StageExecution]:
    """Invalidate the dependents of every forced stage, before planning.

    Args:
        context: The document context.
        request: The request whose execution policy names the forced stages.

    Returns:
        The stage executions that were invalidated.

    Raises:
        WorkflowConfigurationError: When a forced stage is not a stage of this workflow.
    """
    invalidated: list[StageExecution] = []
    for stage in request.execution.force_stages:
        if stage not in STAGE_ORDER:
            raise ValueError(
                f"{stage!r} is not a stage of this workflow; "
                f"expected one of {list(STAGE_ORDER)}"
            )
        invalidated.extend(
            invalidate_downstream(
                context, cast(StageName, stage), cause=f"forced_upstream_{stage}"
            )
        )
    return invalidated


def _input_available(
    context: DocumentContext,
    page: PageContext | None,
    stage: StageName,
    provided: frozenset[str],
) -> bool:
    """Return whether a stage's input exists, or will exist once the plan is followed."""
    if stage == "PDF":
        return context.input.is_file()
    if page is None:
        return True
    if stage == "IMAGE":
        source = image_source(context, page)
        return readable(source) or "page_image" in provided
    if stage == "OCR":
        source = ocr_source(page)
        return readable(source) or bool(
            {"ocr_ready_image", "normalized_image", "page_image"} & provided
        )
    return (
        document_text(page) is not None
        or vlm_source(page) is not None
        or bool({ARTIFACT_NATIVE_TEXT, ARTIFACT_OCR_TEXT} & provided)
    )


def _plan_stage(
    context: DocumentContext,
    request: DocumentRequest,
    execution: StageExecution,
    *,
    page: PageContext | None,
    provided: frozenset[str],
    skip_reason: str | None,
) -> tuple[PlannedStage, StageResolution]:
    """Resolve one stage and turn it into a plan entry."""
    stage = execution.stage
    key = stage_key(context, request, stage, page)
    reusable = is_stage_reusable(execution, current_processing_key=key)
    resolution = resolve_stage(
        stage,
        policy=request.execution,
        processing_key=key,
        reusable=reusable,
        input_available=_input_available(context, page, stage, provided),
        skip_reason=skip_reason,
        prior_status=execution.status,
    )
    entry = PlannedStage(
        stage=stage,
        page_number=None if page is None else page.page_number,
        action=resolution.action,
        reason=resolution.reason,
        processing_key=key,
    )
    return entry, resolution


def build_execution_plan(
    context: DocumentContext, request: DocumentRequest
) -> ExecutionPlan:
    """Resolve every stage of the run and return the plan, executing nothing.

    Args:
        context: The document context to plan against.
        request: The request being served.

    Returns:
        The plan: document-level stages first, then each page's stages in workflow order.
    """
    apply_forces(context, request)
    provided: frozenset[str] = frozenset()
    entries: list[PlannedStage] = []

    for stage in STAGE_ORDER:
        if stage == "PDF":
            execution = context.stages.get(stage)
            if execution is None:
                continue
            entry, resolution = _plan_stage(
                context,
                request,
                execution,
                page=None,
                provided=provided,
                skip_reason=None,
            )
            entries.append(entry)
            if resolution.action in _PRODUCING:
                provided = provided | frozenset(STAGE_OUTPUT_KEYS[stage])

    for page in context.pages:
        page_provided = provided
        for stage in PAGE_STAGES:
            execution = runner.stage_execution(context, page, request, stage)
            entry, resolution = _plan_stage(
                context,
                request,
                execution,
                page=page,
                provided=page_provided,
                skip_reason=(
                    ocr_skip_reason(page, context.policies) if stage == "OCR" else None
                ),
            )
            entries.append(entry)
            if resolution.action in _PRODUCING:
                page_provided = page_provided | frozenset(STAGE_OUTPUT_KEYS[stage])

    return ExecutionPlan(
        document_id=context.document_id,
        workflow_run_id=context.workflow_run_id,
        dry_run=request.execution.dry_run,
        stages=entries,
    )
