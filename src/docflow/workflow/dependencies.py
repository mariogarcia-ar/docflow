"""The stage dependency graph and downstream invalidation (``ORC-09``).

The graph is data, not a hardcoded chain: :data:`STAGE_DEPENDENCIES` says which stages
*consume* which, and everything else — the transitive closure, the invalidation set — is
derived from it. That is what keeps a change of route from being a change of code.

**Invalidation preserves artifacts.** A stage whose result went stale is marked
``INVALIDATED`` and its outputs stay on disk: they are the audit trail of what the previous
attempt produced, and deleting them would destroy the evidence the reuse rule exists to
reason about. Invalidated artifacts are simply never reused.

Only a stage that *holds a valid result* can be invalidated — ``SUCCESS`` or ``REUSED``.
A stage that is ``NOT_STARTED``, ``SKIPPED``, ``FAILED`` or already ``INVALIDATED`` has no
fresh result to lose, and a skip is persistent by §3.5, so it stays a skip.
"""

from __future__ import annotations

from docflow.states import StageState
from docflow.workflow.context import get_page_context
from docflow.workflow.contracts import (
    DocumentContext,
    PageContext,
    StageExecution,
    StageName,
)
from docflow.workflow.stages import set_stage_status
from docflow.workflow.tracing import register_decision

#: Which stages consume which. Read as "the key's result feeds the values".
STAGE_DEPENDENCIES: dict[StageName, tuple[StageName, ...]] = {
    "PDF": (),
    "IMAGE": ("PDF",),
    "OCR": ("IMAGE",),
    "LLM": ("PDF", "IMAGE", "OCR"),
}

#: States that hold a result worth invalidating.
_INVALIDATABLE = frozenset({StageState.SUCCESS, StageState.REUSED})


def dependencies_of(stage: StageName) -> tuple[StageName, ...]:
    """Return the stages whose results directly feed ``stage``.

    Args:
        stage: The stage to look up.

    Returns:
        Its direct predecessors.
    """
    return STAGE_DEPENDENCIES[stage]


def downstream_of(stage: StageName) -> tuple[StageName, ...]:
    """Return every stage transitively fed by ``stage``, nearest first.

    Args:
        stage: The stage to look up.

    Returns:
        The transitive dependents of ``stage``, excluding itself.
    """
    found: list[StageName] = []
    for candidate in STAGE_DEPENDENCIES:
        if stage in _ancestors(candidate) and candidate not in found:
            found.append(candidate)
    return tuple(found)


def _ancestors(stage: StageName) -> tuple[StageName, ...]:
    """Return every stage ``stage`` transitively consumes, excluding itself."""
    collected: list[StageName] = []
    pending = list(STAGE_DEPENDENCIES[stage])
    while pending:
        current = pending.pop()
        if current in collected:
            continue
        collected.append(current)
        pending.extend(STAGE_DEPENDENCIES[current])
    return tuple(collected)


def invalidate_downstream(
    context: DocumentContext,
    stage: StageName,
    *,
    cause: str,
    page_number: int | None = None,
) -> list[StageExecution]:
    """Invalidate every stage fed by ``stage``, recording the cause on each.

    Args:
        context: The document context to update.
        stage: The stage whose result changed; a document-level ``"PDF"`` reaches every
            page, and a page-level stage reaches the pages the run has.
        cause: Why the dependents went stale, recorded as the decision's reason.
        page_number: Restrict the invalidation to one page, or ``None`` for every page.

    Returns:
        The stage executions that were invalidated, so the caller can plan them.
    """
    pages = (
        context.pages
        if page_number is None
        else [get_page_context(context, page_number)]
    )
    dependents = downstream_of(stage)
    invalidated: list[StageExecution] = []
    for page in pages:
        for dependent in dependents:
            execution = page.stages.get(dependent)
            if execution is None or execution.status not in _INVALIDATABLE:
                continue
            _mark_invalidated(page, execution, stage, cause)
            invalidated.append(execution)
    return invalidated


def _mark_invalidated(
    page: PageContext,
    execution: StageExecution,
    cause_stage: StageName,
    cause: str,
) -> None:
    """Mark one stage stale, on a page, and record why."""
    set_stage_status(execution, StageState.INVALIDATED, reason=cause)
    execution.metadata["invalidated_by"] = cause_stage
    register_decision(
        page,
        stage=execution.stage,
        action="INVALIDATED",
        reason=cause,
        page_number=page.page_number,
        metadata={"cause_stage": cause_stage},
    )
