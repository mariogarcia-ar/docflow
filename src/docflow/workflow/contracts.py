"""The orchestrator's request/result contract: ``DocumentRequest → DocumentResult``.

This module is vocabulary only — no I/O, no processor import, no decision logic.

Phase 0 freezes the **spine** of both types: the three identities, the input, the overall
status and the failure list. The payloads that Phase 2 fills in are deliberately left
untyped here, and each is a named follow-up rather than a placeholder:

* ``pages`` — the consolidated per-page results, typed by ``ORC-17``.
* ``execution_summary`` — the per-stage outcome summary, produced by ``ORC-17``.
* ``decisions`` / ``errors`` — the tracing records, typed by ``ORC-18``.
* ``final_result`` — the consolidated inference output, typed by ``ORC-17``.

``DocumentContext`` / ``PageContext`` / ``StageExecution`` / ``ExecutionPolicy`` belong to
``ORC-01`` (Phase 2); :class:`ExecutionPolicy` ships here because
:class:`DocumentRequest` cannot be built without it.

``policies`` and ``execution`` are separate fields on purpose: document policies say what
the document *allows*, execution policy says what this run *does*. Mixing them would let
an operational switch silently change what a document permits.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

DocumentInputType = Literal["PDF", "IMAGE", "auto"]

DocumentStatus = Literal[
    "SUCCESS",
    "PARTIAL",
    "FAILED",
    "PAUSED",
    "REVIEW_REQUIRED",
]


@dataclass(frozen=True)
class ExecutionPolicy:
    """Operational decisions for one run.

    Every field is required: the caller states its intent rather than inheriting a
    default. A missing resume flag is not the same as a false one, and the difference
    between reusing expensive work and paying for it again is too large to leave to an
    implicit default.

    Attributes:
        resume: Continue a previous run of the same document instead of starting over.
        reuse_successful: Reuse a stage whose result is valid and whose key matches.
        retry_failed: Retry a stage that failed in a previous run.
        skip_stages: Stages to leave unrun.
        force_stages: Stages to run even though a valid result exists.
        stop_after_stage: Stop once this stage finishes, or ``None`` to run to the end.
        start_from_stage: Start here, leaving earlier stages to the reuse rule, or
            ``None`` to start at the beginning.
        invalidate_downstream: Invalidate the dependents of every forced stage.
        dry_run: Build and return the plan without executing any processor.
        parallel_pages: Process pages concurrently.
    """

    resume: bool
    reuse_successful: bool
    retry_failed: bool
    skip_stages: list[str]
    force_stages: list[str]
    stop_after_stage: str | None
    start_from_stage: str | None
    invalidate_downstream: bool
    dry_run: bool
    parallel_pages: bool


@dataclass(frozen=True)
class DocumentRequest:
    """Input contract of the orchestrator.

    Attributes:
        document_id: Which document this is. Preserved into the result. Never derived
            from ``input_path``: the same bytes reached by two paths are one document.
        input_path: The PDF or image to process.
        input_type: Declared input type, or ``"auto"`` to let the orchestrator detect it.
        workflow: Workflow identifier. Data, not code.
        policies: Document policies — what this document permits, e.g. ``allow_ocr``.
        execution: Operational decisions for this run.
        options: Free-form run options.
        metadata: Correlation metadata.
    """

    document_id: str
    input_path: Path
    input_type: DocumentInputType
    workflow: str
    policies: dict[str, Any]
    execution: ExecutionPolicy
    options: dict[str, Any]
    metadata: dict[str, Any]


@dataclass
class DocumentResult:
    """Output contract of the orchestrator.

    ``document_id`` is the one the request carried; ``workflow_run_id`` and
    ``processing_key`` are minted by the orchestrator. ``processing_key`` is required and
    non-empty: a result that cannot say which unit of work it belongs to cannot be reused,
    and a dry run produces a plan rather than a result.

    Attributes:
        document_id: Identity carried over from the request.
        workflow_run_id: Identity of the run that produced this result.
        processing_key: The document-level processing key this result belongs to.
        input: The input that was processed.
        pages: Consolidated per-page results, in page order.
        status: Overall outcome.
        execution_summary: Per-stage outcome summary.
        decisions: Tracing records for every decision taken.
        errors: Failures reported instead of propagated.
        metadata: Additional run metadata.
        final_result: The consolidated final output.
    """

    document_id: str
    workflow_run_id: str
    processing_key: str
    input: Path
    pages: list[Any]
    status: DocumentStatus
    execution_summary: dict[str, Any]
    decisions: list[dict[str, Any]]
    errors: list[dict[str, Any]]
    metadata: dict[str, Any]
    final_result: Any
