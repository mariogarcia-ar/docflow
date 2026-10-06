"""Turning a detected input into the document skeleton (``ORC-10``).

Before any page exists, the run has to answer one question: does the input become pages
through the PDF processor, or is the input itself the page? This module answers it and
builds the skeleton either way.

For a PDF, the PDF stage is resolved first — reused when a previous run's result validates,
executed otherwise — and only after it succeeds are the page contexts created from its
per-page results. A run therefore never has a page it did not read.

For an image, exactly one logical page is created and the PDF stage is **not** run at all:
a decision records `direct_image_input`, so the trace says why there is no PDF result
instead of leaving a stage that silently never happened.
"""

from __future__ import annotations

from docflow.pdf import PDFContext, PDFRequest, PDFResult
from docflow.states import StageState
from docflow.workflow import configuration, invocation, runner
from docflow.workflow.context import create_page_context
from docflow.workflow.contracts import (
    DocumentContext,
    DocumentRequest,
    StageName,
)
from docflow.workflow.selection import RESULT_PDF
from docflow.workflow.tracing import register_decision, register_error

#: Stage whose result is a whole document rather than one page.
DOCUMENT_STAGE: StageName = "PDF"


def prepare_document(
    context: DocumentContext, request: DocumentRequest
) -> DocumentContext:
    """Build the document skeleton: a direct image page, or the PDF's pages.

    Args:
        context: The document context, freshly created.
        request: The request being served.

    Returns:
        The same context, with its pages created when the run can read them. A document
        that cannot be prepared keeps a status saying so; nothing is raised.
    """
    if context.input_type == "PDF":
        if request.execution.dry_run:
            # A dry run plans the stages it can know about; knowing the page count would
            # require running the very stage the run is inspecting.
            runner.stage_execution(context, None, request, DOCUMENT_STAGE)
            return context
        return prepare_pdf_document(context, request)
    if context.input_type == "IMAGE":
        return prepare_image_document(context, request)
    register_error(
        context,
        stage="DOCUMENT",
        error_type="UNSUPPORTED_INPUT",
        message=f"{context.input} is not a PDF or an image this pipeline reads",
        recoverable=False,
        outcome="REVIEW_REQUIRED",
    )
    context.status = "FAILED"
    return context


def prepare_pdf_document(
    context: DocumentContext, request: DocumentRequest
) -> DocumentContext:
    """Resolve the PDF stage and create one page context per page it produced.

    Args:
        context: The document context.
        request: The request being served.

    Returns:
        The same context, with its pages when the PDF stage succeeded or was reused.
    """
    execution = runner.stage_execution(context, None, request, DOCUMENT_STAGE)
    outcome = runner.run_stage(
        context,
        None,
        request,
        execution,
        invoke=lambda stage: invocation.run_pdf(_pdf_request(context, request), stage),
        input_available=context.input.is_file(),
    )
    if outcome.execution.status is StageState.FAILED:
        context.status = (
            "REVIEW_REQUIRED" if outcome.execution.error is not None else "FAILED"
        )
        return context
    if outcome.action in ("SKIP", "BLOCKED", "WAIT"):
        return context
    if outcome.result is not None:
        _build_pages(context, outcome.result)
    elif not context.pages:
        register_error(
            context,
            stage=DOCUMENT_STAGE,
            error_type="STATE_INCOMPLETE",
            message="the PDF stage is reusable but the durable context has no pages",
            recoverable=False,
            outcome="REVIEW_REQUIRED",
        )
        context.status = "FAILED"
    return context


def prepare_image_document(
    context: DocumentContext,
    request: DocumentRequest,  # pylint: disable=unused-argument
) -> DocumentContext:
    """Create the single logical page a direct image input becomes.

    # Reason for the suppression above: the two preparation paths share one signature — the
    # dispatcher calls whichever fits without knowing which — and an image input needs no
    # configuration the request could carry.

    Args:
        context: The document context.
        request: The request being served.

    Returns:
        The same context, with one page whose image is the input itself.
    """
    page = create_page_context(1)
    page.artifacts["page_image"] = context.input
    page.status = StageState.READY
    context.pages.append(page)
    register_decision(
        context,
        stage=DOCUMENT_STAGE,
        action="SKIP",
        reason="direct_image_input",
    )
    return context


def _build_pages(context: DocumentContext, result: PDFResult) -> None:
    """Create one page context per page the PDF processor reported."""
    for page_result in result.pages:
        page = create_page_context(page_result.page_number)
        page.artifacts["page_pdf"] = page_result.page_pdf
        page.artifacts["page_image"] = page_result.page_image
        page.artifacts["native_text"] = page_result.native_text
        page.results[RESULT_PDF] = page_result
        page.status = (
            StageState.READY if page_result.status == "success" else StageState.FAILED
        )
        if page_result.status != "success":
            for failure in page_result.validation.errors:
                register_error(
                    page,
                    stage=DOCUMENT_STAGE,
                    error_type=failure.type,
                    message=failure.message,
                    recoverable=failure.recoverable,
                    outcome="REVIEW_REQUIRED",
                    page_number=page.page_number,
                )
        context.pages.append(page)


def _pdf_request(context: DocumentContext, request: DocumentRequest) -> PDFRequest:
    """Build the PDF request this run issues."""
    return PDFRequest(
        pdf_path=context.input,
        output_dir=configuration.work_root(request) / "pdf",
        options=configuration.pdf_options(request),
        context=PDFContext(
            document_id=context.document_id,
            workflow_run_id=context.workflow_run_id,
        ),
    )
