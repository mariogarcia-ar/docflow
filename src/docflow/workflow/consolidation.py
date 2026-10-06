"""Consolidating a page and a document (``ORC-17``).

Consolidation is assembly, not interpretation: it orders the pages, preserves every
processor's result exactly as the processor returned it, and writes the summary the
caller reads the run through. Nothing is recomputed and nothing is decided here — by the
time this module runs, every decision has already been taken and recorded, and this is the
report of them.

The summary answers three questions in one place: which state each stage ended in, which
stages were reused or skipped, and every decision the run recorded. A filter of the stage
states is enough to answer the first; the second and third are why the summary is a mapping
with named keys rather than a bare stage-to-state table.
"""

from __future__ import annotations

from typing import Any

from docflow.states import StageState
from docflow.workflow import configuration
from docflow.workflow.contracts import (
    DocumentContext,
    DocumentRequest,
    DocumentResult,
    DocumentStatus,
    PageContext,
    PageResult,
)
from docflow.workflow.selection import RESULT_LLM

#: Priority used to fold several pages' states into one document-level state. Earlier wins.
_STATE_PRIORITY: tuple[StageState, ...] = (
    StageState.FAILED,
    StageState.INVALIDATED,
    StageState.RUNNING,
    StageState.SUCCESS,
    StageState.REUSED,
    StageState.READY,
    StageState.NOT_STARTED,
    StageState.SKIPPED,
    StageState.PAUSED,
)


def consolidate_page_result(page: PageContext) -> PageResult:
    """Build the consolidated result of one page.

    Args:
        page: The page to consolidate.

    Returns:
        The page's result: its status, the source and strategy it resolved to, every
        processor result it holds, its decisions, its errors and its artifacts — in the
        page's own order, which is never re-sorted.
    """
    return PageResult(
        page_number=page.page_number,
        status=page.status,
        selected_source=page.selected_source,
        extraction_strategy=page.extraction_strategy,
        results=dict(page.results),
        decisions=list(page.decisions),
        errors=list(page.errors),
        artifacts=dict(page.artifacts),
    )


def execution_summary(context: DocumentContext) -> dict[str, Any]:
    """Build the run's per-stage summary.

    Args:
        context: The document context at the end of the run.

    Returns:
        A mapping with one key per stage, holding that stage's aggregated state, plus
        ``reused``, ``skipped`` and ``decisions``: every stage outcome and every decision
        of the run, which is what makes the summary auditable rather than decorative.
    """
    stages: dict[str, StageState] = {
        name: execution.status for name, execution in context.stages.items()
    }
    for page in context.pages:
        for name, execution in page.stages.items():
            current = stages.get(name)
            stages[name] = (
                execution.status
                if current is None
                else _fold(current, execution.status)
            )
    decisions = workflow_decisions(context)
    return {
        **stages,
        "reused": _named(stages, StageState.REUSED),
        "skipped": _named(stages, StageState.SKIPPED),
        "decisions": decisions,
    }


def workflow_decisions(context: DocumentContext) -> list[dict[str, Any]]:
    """Return every routing decision of the run, document-level first.

    Args:
        context: The document context at the end of the run.

    Returns:
        The decisions, in the order they were taken: the document's, then each page's.
    """
    return [
        *context.decisions,
        *(record for page in context.pages for record in page.decisions),
    ]


def workflow_errors(context: DocumentContext) -> list[dict[str, Any]]:
    """Return every failure the run recorded, document-level first.

    Args:
        context: The document context at the end of the run.

    Returns:
        The error records, in the order they were reported.
    """
    return [
        *context.errors,
        *(record for page in context.pages for record in page.errors),
    ]


def consolidate_document_result(
    context: DocumentContext, request: DocumentRequest
) -> DocumentResult:
    """Build the document-level result of a run.

    Args:
        context: The document context at the end of the run.
        request: The request that was served.

    Returns:
        The consolidated result: ordered pages, the document's status, the execution
        summary, every decision and error, and the per-page inference output.
    """
    return build_document_result(
        context,
        request,
        status=document_status(context, request),
        final_result=_final_result(context),
        metadata={
            "workflow": context.workflow,
            "input_type": context.input_type,
            "execution_policy": configuration.execution_policy_payload(
                context.execution_policy
            ),
        },
    )


def build_document_result(
    context: DocumentContext,
    request: DocumentRequest,
    *,
    status: DocumentStatus,
    final_result: Any,
    metadata: dict[str, Any],
) -> DocumentResult:
    """Assemble a document result from a context, whatever the run did with it.

    Every result of this component is built here — a completed run, a dry run, a refused
    request — so the shape the caller reads is one shape and the status is the only thing
    that varies with the outcome.

    Args:
        context: The document context the result reports on.
        request: The request that was served.
        status: The document's status.
        final_result: The consolidated output, or the plan for a dry run.
        metadata: Run metadata.

    Returns:
        The document result, with its pages consolidated and its summary built.
    """
    context.status = status
    return DocumentResult(
        document_id=context.document_id,
        workflow_run_id=context.workflow_run_id,
        processing_key=configuration.document_processing_key(context, request),
        input=context.input,
        pages=[consolidate_page_result(page) for page in context.pages],
        status=status,
        execution_summary=execution_summary(context),
        decisions=workflow_decisions(context),
        errors=workflow_errors(context),
        metadata=metadata,
        final_result=final_result,
    )


def document_status(
    context: DocumentContext, request: DocumentRequest
) -> DocumentStatus:
    """Derive the document's final status.

    Args:
        context: The document context.
        request: The request that was served.

    Returns:
        ``REVIEW_REQUIRED`` when a failure put the run in a human's hands, ``PAUSED`` when
        the run stopped by declaration before the last stage, ``FAILED`` when there is
        nothing usable, ``PARTIAL`` when some pages succeeded and some did not, and
        ``SUCCESS`` when every page did.
    """
    if context.status == "REVIEW_REQUIRED":
        return "REVIEW_REQUIRED"
    if not context.pages:
        return "FAILED"
    if request.execution.stop_after_stage not in (None, "LLM"):
        return "PAUSED"
    statuses = [page.status for page in context.pages]
    if any(status is StageState.FAILED for status in statuses):
        if any(status is StageState.SUCCESS for status in statuses):
            return "PARTIAL"
        return "FAILED"
    return "SUCCESS"


def _fold(current: StageState, incoming: StageState) -> StageState:
    """Fold two pages' states for one stage into the stage's document-level state."""
    return min((current, incoming), key=_STATE_PRIORITY.index)


def _named(stages: dict[str, StageState], state: StageState) -> list[str]:
    """Return the stages whose aggregated state is ``state``, in name order."""
    return sorted(name for name, value in stages.items() if value is state)


def _final_result(context: DocumentContext) -> dict[str, Any]:
    """Return the consolidated inference output, page by page."""
    return {
        "pages": [
            {
                "page_number": page.page_number,
                "selected_source": page.selected_source,
                "extraction_strategy": page.extraction_strategy,
                "result": _parsed_response(page),
            }
            for page in context.pages
        ]
    }


def _parsed_response(page: PageContext) -> Any:
    """Return the page's inference output, or ``None`` when no inference produced one."""
    result = page.results.get(RESULT_LLM)
    return None if result is None else result.parsed_response
