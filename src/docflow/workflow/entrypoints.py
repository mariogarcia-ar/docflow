"""Entry points of the orchestrator.

These two names are **reserved for the orchestrator** by ``docs/plan/README.md`` §4: no
processor may define them, and ``process_document`` is the single call a caller makes to
run the whole pipeline. Phase 0 ships the signatures only; the bodies raise rather than
returning a placeholder.

``process_page`` shields its page state behind ``object`` for now: ``PageContext`` is
``ORC-01``'s to publish in Phase 2 and ``ORC-11``'s to consume, and a locally invented type
would be a second definition of the same seam.
"""

from __future__ import annotations

from docflow.workflow.contracts import DocumentRequest, DocumentResult


def process_document(request: DocumentRequest) -> DocumentResult:
    """Run a document end to end through the whole workflow.

    Args:
        request: The document to process, its policies and the execution policy for this
            run.

    Returns:
        The consolidated document result. A stage that fails is reported inside the
        result with a failure state; it is never propagated as an exception across this
        contract.

    Raises:
        NotImplementedError: Phase 0 ships the signature only.

    # TODO: [MVP] chain initialize/resume → build_execution_plan → prepare_pages →
    # process_pages → consolidate_document_result (ORC-11, ORC-17).
    """
    raise NotImplementedError(
        "process_document is implemented in Phase 2 by ORC-11 and ORC-17"
    )


def process_page(
    page_context: object,
    workflow: dict[str, object],
    policies: dict[str, object],
) -> object:
    """Run the documental routing for exactly one page.

    The central routing function: it inspects the page's artifacts, evaluates its state
    and resolves each stage in order. It returns a page result; the type is the
    orchestrator's ``PageContext`` / page result from ``ORC-01``, published in Phase 2.

    Args:
        page_context: The page's state and artifacts.
        workflow: The workflow definition being executed.
        policies: The policies in force for this run.

    Returns:
        The consolidated page result.

    Raises:
        NotImplementedError: Phase 0 ships the signature only.

    # TODO: [MVP] chain inspect_page → resolve_stage(IMAGE) → resolve_stage(OCR) →
    # select_source → select_extraction_strategy → resolve_stage(LLM) →
    # consolidate_page_result (ORC-11, ORC-12, ORC-17).
    """
    raise NotImplementedError(
        "process_page is implemented in Phase 2 by ORC-11, ORC-12 and ORC-17"
    )
