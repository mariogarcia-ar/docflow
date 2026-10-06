"""Entry points of the orchestrator: ``process_document`` and ``process_page``.

``process_document`` is the one call a caller makes to run a whole document, and it is also
the only place the run's parts are put in order:

1. detect the input type;
2. create or — when resuming — load the durable context;
3. prepare the document skeleton (the PDF stage, or one logical page for an image);
4. build the execution plan, which also applies every forced stage's invalidation;
5. stop here if the run is a dry run;
6. process the pages;
7. persist the context, then consolidate the result.

Nothing here catches a *processor* failure, because none reaches here: the processors report
them as typed results and the run records them. What is caught is the caller's own
misconfiguration — a missing option, an unreadable durable record, a stage name that does
not exist — and it becomes a failed ``DocumentResult`` rather than an exception, because a
typed result is the contract at this level too.

The two names are **reserved for the orchestrator** by ``docs/plan/README.md`` §4: no
processor may define them, and ``process_page`` is the per-page half of the same routing.
"""

from __future__ import annotations

from dataclasses import replace

from docflow.workflow import execution, identity, planning, preparation
from docflow.workflow.configuration import WorkflowConfigurationError, state_path
from docflow.workflow.consolidation import (
    build_document_result,
    consolidate_document_result,
    consolidate_page_result,
)
from docflow.workflow.context import create_document_context, save_document_context
from docflow.workflow.contracts import (
    DocumentContext,
    DocumentRequest,
    DocumentResult,
    ExecutionPlan,
    PageContext,
    PageResult,
)
from docflow.workflow.detection import detect_input_type
from docflow.workflow.persistence import WorkflowPersistenceError
from docflow.workflow.resume import load_resumable_context, recover_running_stages
from docflow.workflow.tracing import append_workflow_trace, register_error


def process_document(request: DocumentRequest) -> DocumentResult:
    """Run a document end to end through the whole workflow.

    Args:
        request: The document to process, its policies and the execution policy for this
            run.

    Returns:
        The consolidated document result. A stage that fails is reported inside the result
        with a failure state; it is never propagated as an exception across this contract.
        A dry run returns a result whose ``final_result`` is the execution plan and whose
        status is ``PAUSED``, because nothing ran and the document is still resumable.
    """
    try:
        return _run_document(request)
    except (
        WorkflowConfigurationError,
        WorkflowPersistenceError,
        ValueError,
    ) as failure:
        return _refused_result(request, failure)


def process_page(
    context: DocumentContext,
    page: PageContext,
    request: DocumentRequest,
) -> PageResult:
    """Run the documental routing for exactly one page.

    The central routing function: it inspects the page's artifacts, evaluates its state and
    resolves each stage in order — image, then OCR (or the reason it is skipped), then
    source selection, then inference.

    Args:
        context: The document the page belongs to.
        page: The page to process.
        request: The request being served.

    Returns:
        The consolidated page result.
    """
    execution.process_page_context(context, page, request)
    return consolidate_page_result(page)


def resume_document(request: DocumentRequest) -> DocumentResult:
    """Continue a previous run of the same document, without repeating completed work.

    Args:
        request: The document to continue; every other field is honoured as stated.

    Returns:
        The consolidated result of the continued run.
    """
    return process_document(
        replace(request, execution=replace(request.execution, resume=True))
    )


def _run_document(request: DocumentRequest) -> DocumentResult:
    """Run the workflow, on a fresh context or on the durable one a resume loads."""
    context = _open_context(request)
    if context.status == "FAILED":
        return consolidate_document_result(context, request)
    preparation.prepare_document(context, request)
    plan = planning.build_execution_plan(context, request)
    if request.execution.dry_run:
        append_workflow_trace(
            context,
            kind="dry_run",
            reason="dry_run_requested",
            metadata={"planned_stages": len(plan.stages)},
        )
        return _dry_run_result(context, request, plan)
    if context.status != "FAILED":
        execution.process_pages(context, request)
        save_document_context(context, state_path(request))
    return consolidate_document_result(context, request)


def _open_context(request: DocumentRequest) -> DocumentContext:
    """Create a fresh context, or load the resumable one the request asks for."""
    fresh = create_document_context(
        request,
        input_type=detect_input_type(request.input_path, request.input_type),
        workflow_run_id=identity.build_workflow_run_id(),
    )
    if not request.execution.resume:
        return fresh
    loaded = load_resumable_context(state_path(request))
    if loaded is None:
        return fresh
    if loaded.document_id != request.document_id:
        register_error(
            fresh,
            stage="DOCUMENT",
            error_type="STATE_MISMATCH",
            message=(
                f"the durable record belongs to {loaded.document_id}, "
                f"not to {request.document_id}"
            ),
            recoverable=False,
            outcome="REVIEW_REQUIRED",
        )
        fresh.status = "FAILED"
        return fresh
    loaded.workflow_run_id = fresh.workflow_run_id
    loaded.input_hash = fresh.input_hash
    recover_running_stages(loaded)
    return loaded


def _dry_run_result(
    context: DocumentContext,
    request: DocumentRequest,
    plan: ExecutionPlan,
) -> DocumentResult:
    """Return the inspection result of a dry run: the plan, and nothing executed."""
    return build_document_result(
        context,
        request,
        status="PAUSED",
        final_result=plan,
        metadata={"dry_run": True},
    )


def _refused_result(request: DocumentRequest, failure: BaseException) -> DocumentResult:
    """Return a failed result for a request the run cannot even start on.

    The refusal is built as a document context and consolidated like any other run, so a
    refused request produces the same result shape — and the same summary — as one that
    ran and failed.
    """
    context = create_document_context(
        request,
        input_type="UNSUPPORTED",
        workflow_run_id=identity.build_workflow_run_id(),
    )
    register_error(
        context,
        stage="DOCUMENT",
        error_type="CONFIGURATION_ERROR",
        message=str(failure),
        recoverable=False,
        outcome="REVIEW_REQUIRED",
        metadata={"key": getattr(failure, "key", None)},
    )
    context.status = "FAILED"
    return consolidate_document_result(context, request)
