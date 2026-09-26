"""Resuming a document without repeating completed work (``ORC-15``).

A resume is not a rerun. It loads the durable context, repairs it, and lets the normal
resolution rules rediscover what still has to happen:

| prior state | what the resume does |
|---|---|
| ``SUCCESS`` / ``REUSED`` | reuse, when the key still matches and the artifacts validate |
| ``SKIPPED`` | stays skipped — an explicit skip is persistent |
| ``INVALIDATED`` | execute |
| ``FAILED`` | retry, when the policy allows it |
| ``NOT_STARTED`` | execute |
| ``RUNNING`` | recovered to ``READY`` first, then resolved per policy |

Only two of those need code here, because the other five fall out of the reuse rule and the
resolution order: ``SKIPPED`` and ``FAILED`` are states nothing that ran in this process
produced, so they arrive from the durable record and must be read, not recomputed.

The stop side is declarative (``stop_after_stage``), so there is no imperative stop to
honour and no ``stop_requested`` field to carry one.

# TODO: [MVP] an imperative mid-run ``request_stop`` and its ``stop_requested`` field.
# TODO: [RELEASE] recovery after an external kill, and cross-process locking: a stage whose
# owner died mid-write is recovered here only because this process re-reads the record.
"""

from __future__ import annotations

from pathlib import Path

from docflow.states import StageState
from docflow.workflow.context import load_document_context
from docflow.workflow.contracts import DocumentContext, StageExecution
from docflow.workflow.tracing import TraceTarget, register_decision

#: The one state a crash can leave behind that no live run produces.
_INTERRUPTED = StageState.RUNNING


def load_resumable_context(path: Path) -> DocumentContext | None:
    """Load a document's durable context when there is one to resume.

    Args:
        path: Where the record lives.

    Returns:
        The context, or ``None`` when no record exists — a resume of a document that never
        ran is a first run, and saying so is better than inventing an empty record.
    """
    if not path.is_file():
        return None
    return load_document_context(path)


def recover_running_stages(context: DocumentContext) -> list[StageExecution]:
    """Return every stage left ``RUNNING`` by an interrupted run to ``READY``.

    A stage is left ``RUNNING`` only when the process that held it stopped existing: the
    claim is in-process, so no live owner can be holding it. Recovering it makes it
    claimable again, and the resolution that follows decides whether it is reused.

    Args:
        context: The document context to repair.

    Returns:
        The stages that were recovered.
    """
    recovered: list[StageExecution] = []
    for target, stages, page_number in _stage_maps(context):
        for execution in stages.values():
            if execution.status is not _INTERRUPTED:
                continue
            execution.metadata.pop("owner", None)
            execution.status = StageState.READY
            recovered.append(execution)
            register_decision(
                target,
                stage=execution.stage,
                action="READY",
                reason="recovered_interrupted_running",
                page_number=page_number,
            )
    return recovered


def _stage_maps(
    context: DocumentContext,
) -> list[tuple[TraceTarget, dict[str, StageExecution], int | None]]:
    """Return the document's and every page's stage maps, with the page they belong to."""
    targets: list[tuple[TraceTarget, dict[str, StageExecution], int | None]] = [
        (context, context.stages, None)
    ]
    targets.extend((page, page.stages, page.page_number) for page in context.pages)
    return targets
