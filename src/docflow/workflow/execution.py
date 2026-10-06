"""Processing pages: the per-page unit of the workflow (``ORC-11``).

Each page is self-contained: it owns its stages, its artifacts and its decisions, so a page
that succeeded is never re-run when a later page fails, and a page that failed can be
re-processed alone. Page order in the context is the document's logical order, which is
why the loop appends nothing and never sorts.

The stages run in the workflow's order — ``IMAGE``, then ``OCR`` (or the reason it is
skipped), then source selection, then ``LLM`` — and every one of them goes through
:func:`docflow.workflow.runner.run_stage`, so reuse, skipping and failure containment are
the same code at page level as at document level.

**Sequential by construction.** ``parallel_pages`` is declared in the policy and read
nowhere: the PoC runs pages one at a time, and the flag says so rather than implying a
concurrency the implementation has not built.

# TODO: [MVP] true parallel page execution behind ``parallel_pages``; the per-page state
# is already isolated, and ``claim_stage`` already refuses a double claim, which is what a
# worker pool would need.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from docflow.image import ImageContext, ImageRequest, ImageResult
from docflow.ocr import OCRContext, OCRRequest, OCRResult
from docflow.states import StageState
from docflow.workflow import configuration, invocation, keys, runner, selection
from docflow.workflow.contracts import (
    DocumentContext,
    DocumentRequest,
    PageContext,
    StageExecution,
    StageName,
)
from docflow.workflow.llm_input import build_llm_input
from docflow.workflow.resolution import STAGE_ORDER
from docflow.workflow.runner import StageOutcome
from docflow.workflow.tracing import register_decision


def process_pages(
    context: DocumentContext, request: DocumentRequest
) -> DocumentContext:
    """Process every page of the document, in logical order.

    Args:
        context: The document context, with its pages already created.
        request: The request being served.

    Returns:
        The same context, with every page's stages resolved and recorded.
    """
    boundary = stop_boundary(request)
    for page in context.pages:
        process_page_context(context, page, request, boundary=boundary)
    return context


def process_page_context(
    context: DocumentContext,
    page: PageContext,
    request: DocumentRequest,
    *,
    boundary: StageName | None = None,
) -> PageContext:
    """Route and process exactly one page.

    Args:
        context: The document context the page belongs to.
        page: The page to process.
        request: The request being served.
        boundary: The last stage this run may start, from ``stop_after_stage``.

    Returns:
        The same page, with its stages resolved and its status updated.
    """
    image_outcome = _run_page_stage(
        context,
        page,
        request,
        "IMAGE",
        invoke=lambda stage: invocation.run_image_processing(
            _image_request(context, page, request), stage
        ),
        input_available=selection.readable(keys.image_source(context, page)),
        boundary=boundary,
    )
    if isinstance(image_outcome.result, ImageResult):
        page.results[selection.RESULT_IMAGE] = image_outcome.result
        _record_image_artifacts(page, image_outcome.result)

    ocr_outcome = _run_page_stage(
        context,
        page,
        request,
        "OCR",
        invoke=lambda stage: invocation.run_ocr(
            _ocr_request(context, page, request), stage
        ),
        input_available=selection.readable(keys.ocr_source(page)),
        skip_reason=selection.ocr_skip_reason(page, context.policies),
        boundary=boundary,
    )
    if isinstance(ocr_outcome.result, OCRResult):
        page.results[selection.RESULT_OCR] = ocr_outcome.result
        _record_ocr_artifacts(page, ocr_outcome.result)

    if not _allowed("LLM", boundary):
        # The stage never starts, so nothing is decided about it — but the record of a
        # stage that did not start is what makes a stopped run's state legible.
        runner.stage_execution(context, page, request, "LLM")
        page.status = _page_status(page)
        return page

    choice = selection.select_source(page, context.policies)
    strategy = selection.select_extraction_strategy(choice)
    page.selected_source = choice.source
    page.extraction_strategy = strategy.strategy
    register_decision(
        page,
        stage="SOURCE",
        action=choice.source if choice.source is not None else "BLOCKED",
        reason=choice.reason,
        page_number=page.page_number,
        metadata={"extraction_strategy": strategy.strategy},
    )

    if strategy.strategy is None:
        blocked = runner.stage_execution(context, page, request, "LLM")
        blocked.metadata["blocked_reason"] = choice.reason
        register_decision(
            page,
            stage="LLM",
            action="BLOCKED",
            reason=choice.reason,
            page_number=page.page_number,
        )
    else:
        llm_outcome = _run_page_stage(
            context,
            page,
            request,
            "LLM",
            invoke=lambda stage: invocation.run_llm(
                build_llm_input(context, page, request), stage
            ),
            input_available=_llm_input_available(page),
            boundary=boundary,
        )
        if llm_outcome.result is not None:
            page.results[selection.RESULT_LLM] = llm_outcome.result

    page.status = _page_status(page)
    return page


def stop_boundary(request: DocumentRequest) -> StageName | None:
    """Return the declared stop boundary, validated against the workflow's stages.

    Args:
        request: The request being served.

    Returns:
        The named stage, or ``None`` when the run is not stopping early.

    Raises:
        ValueError: When the named stage is not a stage of this workflow.
    """
    boundary = request.execution.stop_after_stage
    if boundary is None:
        return None
    if boundary not in STAGE_ORDER:
        raise ValueError(
            f"{boundary!r} is not a stage of this workflow; "
            f"expected one of {list(STAGE_ORDER)}"
        )
    return next(stage for stage in STAGE_ORDER if stage == boundary)


def _run_page_stage(
    context: DocumentContext,
    page: PageContext,
    request: DocumentRequest,
    stage: StageName,
    *,
    invoke: Callable[[StageExecution], Any],
    input_available: bool,
    skip_reason: str | None = None,
    boundary: StageName | None = None,
) -> StageOutcome:
    """Resolve and run one page-level stage, when the boundary allows it.

    A stage the boundary excludes is returned untouched — ``NOT_STARTED``, no decision —
    so a run that stopped early never claims it considered a stage it did not reach.
    """
    if not _allowed(stage, boundary):
        return StageOutcome(
            execution=runner.stage_execution(context, page, request, stage),
            action="WAIT",
            reason="after_stop_boundary",
            result=None,
        )
    execution = runner.stage_execution(context, page, request, stage)
    return runner.run_stage(
        context,
        page,
        request,
        execution,
        invoke=invoke,
        skip_reason=skip_reason,
        input_available=input_available,
    )


def _allowed(stage: StageName, boundary: StageName | None) -> bool:
    """Return whether ``stage`` may start, given the declared stop boundary."""
    if boundary is None:
        return True
    return STAGE_ORDER.index(stage) <= STAGE_ORDER.index(boundary)


def _llm_input_available(page: PageContext) -> bool:
    """Return whether the page can compose an inference input."""
    return keys.document_text(page) is not None or selection.readable(
        keys.vlm_source(page)
    )


def _record_image_artifacts(page: PageContext, result: ImageResult) -> None:
    """Record the representations the image processor published."""
    if result.normalized is not None:
        page.artifacts["normalized_image"] = result.normalized.path
    if result.variants.ocr_ready is not None:
        page.artifacts["ocr_ready_image"] = result.variants.ocr_ready.path
    if result.variants.vlm_ready is not None:
        page.artifacts["vlm_ready_image"] = result.variants.vlm_ready.path


def _record_ocr_artifacts(page: PageContext, result: OCRResult) -> None:
    """Record the text representations the OCR processor published."""
    if result.artifacts is not None:
        page.artifacts["ocr_text"] = result.artifacts.text
        page.artifacts["ocr_markdown"] = result.artifacts.markdown


def _image_request(
    context: DocumentContext, page: PageContext, request: DocumentRequest
) -> ImageRequest:
    """Build the image request for one page."""
    source = keys.image_source(context, page)
    if source is None:
        raise ValueError(f"page {page.page_number} has no image to process")
    return ImageRequest(
        image_path=source,
        output_dir=(
            configuration.work_root(request) / "image" / f"page_{page.page_number:03d}"
        ),
        options=configuration.image_options(request),
        context=ImageContext(
            document_id=context.document_id,
            workflow_run_id=context.workflow_run_id,
            page_number=page.page_number,
        ),
    )


def _ocr_request(
    context: DocumentContext, page: PageContext, request: DocumentRequest
) -> OCRRequest:
    """Build the OCR request for one page."""
    source = keys.ocr_source(page)
    if source is None:
        raise ValueError(f"page {page.page_number} has no prepared image for OCR")
    return OCRRequest(
        image_path=source,
        output_dir=(
            configuration.work_root(request) / "ocr" / f"page_{page.page_number:03d}"
        ),
        options=configuration.ocr_options(request),
        context=OCRContext(
            document_id=context.document_id,
            workflow_run_id=context.workflow_run_id,
            page_number=page.page_number,
        ),
    )


def _page_status(page: PageContext) -> StageState:
    """Derive a page's status from the stages it ran."""
    statuses = [execution.status for execution in page.stages.values()]
    if any(status is StageState.FAILED for status in statuses):
        return StageState.FAILED
    if any(status in (StageState.SUCCESS, StageState.REUSED) for status in statuses):
        return StageState.SUCCESS
    if statuses and all(status is StageState.SKIPPED for status in statuses):
        return StageState.SKIPPED
    return page.status
