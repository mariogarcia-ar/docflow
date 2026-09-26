"""The orchestrator's request/result contract: ``DocumentRequest → DocumentResult``.

This module is vocabulary only — no I/O, no processor import, no decision logic.

Phase 0 freezes the **spine** of both types: the three identities, the input, the overall
status and the failure list. The payloads that Phase 2 fills in are deliberately left
untyped here, and each is a named follow-up rather than a placeholder:

* ``pages`` — the consolidated per-page results, typed by ``ORC-17``.
* ``execution_summary`` — the per-stage outcome summary, produced by ``ORC-17``.
* ``decisions`` / ``errors`` — the tracing records, typed by ``ORC-18``.
* ``final_result`` — the consolidated inference output, typed by ``ORC-17``.

``DocumentContext`` / ``PageContext`` / ``StageExecution`` / ``ExecutionPolicy`` were
published by ``ORC-01`` (Phase 2), next to the request/result pair.

``policies`` and ``execution`` are separate fields on purpose: document policies say what
the document *allows*, execution policy says what this run *does*. Mixing them would let
an operational switch silently change what a document permits.

**Stage status is the shared nine-member vocabulary.** ``StageExecution.status`` and
``PageContext.status`` are typed :class:`~docflow.states.StageState`, which
``docs/plan/README.md`` §9.6 closes at nine members and ``docflow.states`` owns. The two
extra words the orchestrator needs — ``PARTIAL`` and ``REVIEW_REQUIRED`` — are
**document** statuses (:data:`DocumentStatus`) and are recorded there, so a stage that
could not fully succeed is ``FAILED`` while the document it belongs to says
``REVIEW_REQUIRED``. That keeps one closed vocabulary for stages instead of a second enum
spelling the same nine words.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from docflow.states import StageState

DocumentInputType = Literal["PDF", "IMAGE", "auto"]

DocumentStatus = Literal[
    "SUCCESS",
    "PARTIAL",
    "FAILED",
    "PAUSED",
    "REVIEW_REQUIRED",
]

#: The four stages of the documental workflow. Workflow coordinates, not processor names.
StageName = Literal["PDF", "IMAGE", "OCR", "LLM"]

#: What the plan resolves a stage to. ``WAIT`` is declared for the dependency evaluation
#: and produced when a stage's predecessors have not finished yet; ``BLOCKED`` when a
#: stage's input can never become available in this run.
StageAction = Literal["EXECUTE", "REUSE", "SKIP", "FORCE", "WAIT", "BLOCKED"]

#: What ``detect_input_type`` answers. ``UNSUPPORTED`` is a stated outcome, never a guess.
DetectedInputType = Literal["PDF", "IMAGE", "UNSUPPORTED"]

#: Documentary source a page offers the LLM. Literal and closed, exactly as §3.7 fixes it.
SourceKind = Literal[
    "NATIVE_TEXT",
    "OCR_TEXT",
    "IMAGE",
    "NATIVE_TEXT + IMAGE",
    "OCR_TEXT + IMAGE",
]

#: Extraction strategy derived from the selected source.
ExtractionStrategy = Literal[
    "TEXT_ONLY",
    "OCR_ONLY",
    "VLM_ONLY",
    "TEXT_PLUS_VLM",
    "OCR_PLUS_VLM",
]

#: The two error outcomes the PoC implements and advertises. The richer fallbacks of §3.8
#: are deferred, so this literal is deliberately two values wide.
ErrorOutcome = Literal["retry processor", "REVIEW_REQUIRED"]

#: The page artifact keys ``PageContext.artifacts`` may carry. Every key is present on a
#: page context, holding ``None`` until the artifact exists: absence is stated.
#:
#: ``ocr_ready_image`` and ``vlm_ready_image`` are the two purpose-specific variants the
#: image processor publishes and the OCR and LLM stages consume. Naming them after what
#: consumes them is the point: the general ``normalized_image`` is a third representation
#: and reusing its key for either variant would misname the artifact.
PageArtifactKey = Literal[
    "page_pdf",
    "page_image",
    "native_text",
    "normalized_image",
    "ocr_ready_image",
    "vlm_ready_image",
    "ocr_text",
    "ocr_markdown",
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
    pages: list[PageResult]
    status: DocumentStatus
    execution_summary: dict[str, Any]
    decisions: list[dict[str, Any]]
    errors: list[dict[str, Any]]
    metadata: dict[str, Any]
    final_result: Any


@dataclass
class StageExecution:
    """The atomic control unit of the workflow: one stage of one page, or of the document.

    Mutable on purpose: a stage is claimed, run and finished, so its ``status`` changes
    across the run while its identity does not. ``StageState.SKIPPED`` and
    ``StageState.REUSED`` mean different things and are never interchanged.

    Attributes:
        stage_id: Stable identifier of this unit of work, e.g. ``OCR:2``.
        stage: Which workflow stage this is.
        processor: Name of the processor that owns the stage.
        processor_version: Version of that processor, part of the processing key.
        status: Lifecycle state, from the shared vocabulary.
        processing_key: Key of the result this stage would produce.
        input_artifacts: Artifacts the stage consumes.
        output_artifacts: Artifacts the stage published.
        options_hash: Digest of the normalized options that were in force.
        attempts: How many times the stage has been attempted.
        started_at: ISO timestamp of the last claim, or ``None`` before the first.
        finished_at: ISO timestamp of the last outcome, or ``None`` while unfinished.
        skip_reason: Why the stage was deliberately not run, or ``None``.
        force_reason: Why the stage was forced, or ``None``.
        error: The error record that ended the stage, or ``None``.
        metadata: Anything else worth tracing, e.g. the owner of a claim.
    """

    stage_id: str
    stage: StageName
    processor: str
    processor_version: str
    status: StageState
    processing_key: str
    input_artifacts: list[Path]
    output_artifacts: list[Path]
    options_hash: str
    attempts: int
    started_at: str | None
    finished_at: str | None
    skip_reason: str | None
    force_reason: str | None
    error: dict[str, Any] | None
    metadata: dict[str, Any]


@dataclass
class PageContext:
    """Durable state of one logical page — the unit of parallelism, recovery and reprocessing.

    Every page owns its own ``StageExecution`` records and artifacts, so a page that failed
    is reprocessed alone and a page that succeeded is never re-run.

    Attributes:
        page_number: Logical page number, 1-based.
        artifacts: The page's artifacts by key, each ``None`` until it exists.
        results: Processor results by name (``pdf_result``, ``image_result``, …).
        stages: Stage executions by stage name.
        selected_source: The documentary source chosen for this page, or ``None``.
        extraction_strategy: The strategy chosen for this page, or ``None``.
        decisions: Routing decisions recorded for this page.
        errors: Failures recorded for this page.
        status: Lifecycle state of the page, from the shared vocabulary.
    """

    page_number: int
    artifacts: dict[str, Path | None]
    results: dict[str, Any]
    stages: dict[str, StageExecution]
    selected_source: SourceKind | None
    extraction_strategy: ExtractionStrategy | None
    decisions: list[dict[str, Any]]
    errors: list[dict[str, Any]]
    status: StageState


@dataclass
class DocumentContext:
    """Durable state of one document, owned only by the orchestrator.

    Attributes:
        document_id: Identity carried from the request.
        workflow_run_id: Identity of the run that created this context.
        input: The input that was processed.
        input_hash: Digest of the input, part of every stage's processing key.
        input_type: The detected input type.
        workflow: Workflow identifier, data rather than code.
        policies: Document policies in force.
        execution_policy: Operational policy of the run.
        pages: The document's pages, in logical order.
        stages: Document-level stage executions by stage name.
        decisions: Routing decisions recorded for the document.
        errors: Failures recorded for the document.
        status: Overall status of the document.
        final_result: The consolidated inference output, or ``None`` before consolidation.
    """

    document_id: str
    workflow_run_id: str
    input: Path
    input_hash: str
    input_type: DetectedInputType
    workflow: str
    policies: dict[str, Any]
    execution_policy: ExecutionPolicy
    pages: list[PageContext]
    stages: dict[str, StageExecution]
    decisions: list[dict[str, Any]]
    errors: list[dict[str, Any]]
    status: DocumentStatus
    final_result: Any


@dataclass
class PageResult:
    """Consolidated result of one page, as it appears inside :class:`DocumentResult`.

    Attributes:
        page_number: Logical page number, 1-based.
        status: Lifecycle state of the page.
        selected_source: The documentary source chosen for this page, or ``None``.
        extraction_strategy: The strategy chosen for this page, or ``None``.
        results: Processors' results, preserved as the processors returned them.
        decisions: Routing decisions recorded for this page.
        errors: Failures recorded for this page.
        artifacts: The page's artifacts by key.
    """

    page_number: int
    status: StageState
    selected_source: SourceKind | None
    extraction_strategy: ExtractionStrategy | None
    results: dict[str, Any]
    decisions: list[dict[str, Any]]
    errors: list[dict[str, Any]]
    artifacts: dict[str, Path | None]


@dataclass
class StageResolution:
    """One stage's resolved action and the reason it was resolved that way.

    Attributes:
        stage: The stage that was resolved.
        action: What the run will do with it.
        reason: Why, as a stable token (``explicit_skip``, ``native_text_present``, …).
        processing_key: The key the current configuration computes for the stage.
    """

    stage: StageName
    action: StageAction
    reason: str
    processing_key: str


@dataclass
class PlannedStage:
    """One entry of an execution plan: a stage, its page, and the resolved action.

    Attributes:
        stage: The stage the entry is about.
        page_number: The page it belongs to, or ``None`` for a document-level stage.
        action: What the plan resolved it to.
        reason: Why.
        processing_key: The computed key; a plan entry never exists without one.
    """

    stage: StageName
    page_number: int | None
    action: StageAction
    reason: str
    processing_key: str


@dataclass
class ExecutionPlan:
    """The full plan of a run, before any processor is invoked.

    Attributes:
        document_id: Identity of the document.
        workflow_run_id: Identity of the planning run.
        dry_run: Whether the plan was built for inspection only.
        stages: Every planned stage, document-level first, then page by page.
    """

    document_id: str
    workflow_run_id: str
    dry_run: bool
    stages: list[PlannedStage]
