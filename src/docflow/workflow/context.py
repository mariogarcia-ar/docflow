"""Create, load and save the orchestrator's durable state (``ORC-03``).

The document context is the memory of a workflow: which run is in flight, what each page
has produced, how far each stage got and why. Everything the orchestrator decides is
decided against it, and everything ``resume`` depends on is read back out of it.

Two rules shape this module:

* **a page context is created empty and filled, never invented.** All six artifact keys
  exist from the start, each ``None`` until its artifact is published, so "there is no
  ``ocr_text``" and "``ocr_text`` is at this path" are different answers;
* **the serialized shape is the real one.** The PoC store is a JSON file, tagged as the
  MVP gate's business, but the payload it writes is derived from the context's own fields
  rather than from a hand-copied list.

**What the payload does not carry.** ``PageContext.results`` holds live processor result
objects; those are not serialized. A resumed run re-derives what it needs from the
artifacts on disk and from the decisions already recorded — which is the only reason the
resume mapping can be ``SUCCESS → REUSE`` without re-running the processor.

# TODO: [MVP] durable, cross-process storage behind the same payload; process result objects
# are re-derived from artifacts rather than persisted.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from typing import Any, get_args

from docflow.states import StageState
from docflow.workflow import configuration, identity
from docflow.workflow.contracts import (
    DetectedInputType,
    DocumentContext,
    DocumentRequest,
    ExecutionPolicy,
    PageArtifactKey,
    PageContext,
    StageExecution,
    StageName,
)
from docflow.workflow.persistence import read_json, write_json_atomic
from docflow.workflow.stages import create_stage

#: The artifact keys every page context carries, each ``None`` until it exists. Derived
#: from the contract's own literal so the vocabulary is written once.
PAGE_ARTIFACT_KEYS: tuple[str, ...] = get_args(PageArtifactKey)


def _plain(value: Any) -> Any:
    """Return a JSON-writable form of ``value``, keeping its structure.

    Args:
        value: Any value the durable state may hold.

    Returns:
        The same structure with paths and enums rendered as text.
    """
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def create_document_context(
    request: DocumentRequest,
    *,
    input_type: DetectedInputType,
    workflow_run_id: str,
) -> DocumentContext:
    """Create the durable context of a new run.

    Args:
        request: The document request the run is serving.
        input_type: The type ``detect_input_type`` settled on.
        workflow_run_id: The identity minted for this run.

    Returns:
        The context, with no pages and no stage executions: a context that already owned
        pages would claim a document structure nobody has read yet. Its status is
        ``PAUSED``, which is the honest description of a document that has not run and can
        be resumed.
    """
    return DocumentContext(
        document_id=request.document_id,
        workflow_run_id=workflow_run_id,
        input=request.input_path,
        input_hash=identity.input_hash(request.input_path),
        input_type=input_type,
        workflow=request.workflow,
        policies=dict(request.policies),
        execution_policy=request.execution,
        pages=[],
        stages={},
        decisions=[],
        errors=[],
        status="PAUSED",
        final_result=None,
    )


def create_page_context(page_number: int) -> PageContext:
    """Create one page's durable state, with every artifact key present and unset.

    Args:
        page_number: Logical page number, 1-based.

    Returns:
        The page context, ``NOT_STARTED``.
    """
    return PageContext(
        page_number=page_number,
        artifacts=dict.fromkeys(PAGE_ARTIFACT_KEYS),
        results={},
        stages={},
        selected_source=None,
        extraction_strategy=None,
        decisions=[],
        errors=[],
        status=StageState.NOT_STARTED,
    )


def get_page_context(context: DocumentContext, page_number: int) -> PageContext:
    """Return one page's state.

    Args:
        context: The document context to read.
        page_number: Logical page number, 1-based.

    Returns:
        The page context.

    Raises:
        LookupError: When the document has no such page. Returning an empty page instead
            would let a caller act on a page the document never contained.
    """
    for page in context.pages:
        if page.page_number == page_number:
            return page
    raise LookupError(
        f"{context.document_id} has no page {page_number}; "
        f"it has {len(context.pages)} page(s)"
    )


def add_stage(
    context: DocumentContext,
    or_page: PageContext | None,
    stage: StageExecution,
) -> StageExecution:
    """Register a stage execution on a document or on one of its pages.

    Args:
        context: The document context; unused when ``or_page`` is given.
        or_page: The page the stage belongs to, or ``None`` for a document-level stage.
        stage: The stage execution to register.

    Returns:
        The registered stage, so a caller can keep working with it.
    """
    if or_page is None:
        context.stages[stage.stage] = stage
    else:
        or_page.stages[stage.stage] = stage
    return stage


def new_stage(
    stage: StageName,
    *,
    processor: str,
    processor_version: str,
    processing_key: str,
    options_hash: str,
    input_artifacts: tuple[Path, ...],
    page_number: int | None,
) -> StageExecution:
    """Create a stage execution with the orchestrator's own bookkeeping filled in.

    Args:
        stage: Which stage of the workflow.
        processor: The processor that owns it.
        processor_version: That processor's version.
        processing_key: The key its result will belong to.
        options_hash: Digest of the normalized options in force.
        input_artifacts: What the stage consumes.
        page_number: The page it belongs to, or ``None`` for a document-level stage.

    Returns:
        A ``NOT_STARTED`` stage execution, ready to be resolved and claimed.
    """
    return create_stage(
        stage,
        processor=processor,
        processor_version=processor_version,
        processing_key=processing_key,
        options_hash=options_hash,
        input_artifacts=input_artifacts,
        page_number=page_number,
    )


def document_context_payload(context: DocumentContext) -> dict[str, Any]:
    """Return the JSON-writable payload of a document context.

    Args:
        context: The context to serialize.

    Returns:
        A mapping whose keys mirror the context's own fields.
    """
    policy = context.execution_policy
    return {
        "document_id": context.document_id,
        "workflow_run_id": context.workflow_run_id,
        "input": str(context.input),
        "input_hash": context.input_hash,
        "input_type": context.input_type,
        "workflow": context.workflow,
        "policies": _plain(context.policies),
        "execution_policy": configuration.execution_policy_payload(policy),
        "pages": [_page_payload(page) for page in context.pages],
        "stages": {
            name: _stage_payload(stage) for name, stage in context.stages.items()
        },
        "decisions": _plain(context.decisions),
        "errors": _plain(context.errors),
        "status": context.status,
        "final_result": _plain(context.final_result),
    }


def document_context_from_payload(payload: Mapping[str, Any]) -> DocumentContext:
    """Rebuild a document context from :func:`document_context_payload`'s output.

    Args:
        payload: The stored payload.

    Returns:
        The context it describes. ``results`` is empty, as documented at the top of this
        module: processor result objects are not part of the durable record.
    """
    policy = payload["execution_policy"]
    return DocumentContext(
        document_id=payload["document_id"],
        workflow_run_id=payload["workflow_run_id"],
        input=Path(payload["input"]),
        input_hash=payload["input_hash"],
        input_type=payload["input_type"],
        workflow=payload["workflow"],
        policies=dict(payload["policies"]),
        execution_policy=ExecutionPolicy(
            resume=policy["resume"],
            reuse_successful=policy["reuse_successful"],
            retry_failed=policy["retry_failed"],
            skip_stages=list(policy["skip_stages"]),
            force_stages=list(policy["force_stages"]),
            stop_after_stage=policy["stop_after_stage"],
            start_from_stage=policy["start_from_stage"],
            invalidate_downstream=policy["invalidate_downstream"],
            dry_run=policy["dry_run"],
            parallel_pages=policy["parallel_pages"],
        ),
        pages=[_page_from_payload(page) for page in payload["pages"]],
        stages={
            name: _stage_from_payload(stage)
            for name, stage in payload["stages"].items()
        },
        decisions=[dict(record) for record in payload["decisions"]],
        errors=[dict(record) for record in payload["errors"]],
        status=payload["status"],
        final_result=payload["final_result"],
    )


def save_document_context(context: DocumentContext, path: Path) -> Path:
    """Persist a document context atomically.

    Args:
        context: The context to save.
        path: Where the record belongs.

    Returns:
        ``path``, once it is complete.
    """
    return write_json_atomic(path, document_context_payload(context))


def load_document_context(path: Path) -> DocumentContext:
    """Read a document context back.

    Args:
        path: The record to read.

    Returns:
        The context it describes.
    """
    return document_context_from_payload(read_json(path))


def _stage_payload(stage: StageExecution) -> dict[str, Any]:
    """Return the JSON-writable payload of one stage execution."""
    return {
        "stage_id": stage.stage_id,
        "stage": stage.stage,
        "processor": stage.processor,
        "processor_version": stage.processor_version,
        "status": stage.status.value,
        "processing_key": stage.processing_key,
        "input_artifacts": [str(path) for path in stage.input_artifacts],
        "output_artifacts": [str(path) for path in stage.output_artifacts],
        "options_hash": stage.options_hash,
        "attempts": stage.attempts,
        "started_at": stage.started_at,
        "finished_at": stage.finished_at,
        "skip_reason": stage.skip_reason,
        "force_reason": stage.force_reason,
        "error": _plain(stage.error),
        "metadata": _plain(stage.metadata),
    }


def _stage_from_payload(payload: Mapping[str, Any]) -> StageExecution:
    """Rebuild one stage execution from its payload."""
    stage = StageExecution(
        stage_id=payload["stage_id"],
        stage=payload["stage"],
        processor=payload["processor"],
        processor_version=payload["processor_version"],
        status=StageState(payload["status"]),
        processing_key=payload["processing_key"],
        input_artifacts=[Path(path) for path in payload["input_artifacts"]],
        output_artifacts=[Path(path) for path in payload["output_artifacts"]],
        options_hash=payload["options_hash"],
        attempts=payload["attempts"],
        started_at=payload["started_at"],
        finished_at=payload["finished_at"],
        skip_reason=payload["skip_reason"],
        force_reason=payload["force_reason"],
        error=payload["error"],
        metadata=dict(payload["metadata"]),
    )
    return stage


def _page_payload(page: PageContext) -> dict[str, Any]:
    """Return the JSON-writable payload of one page context."""
    return {
        "page_number": page.page_number,
        "artifacts": _plain(page.artifacts),
        "stages": {name: _stage_payload(stage) for name, stage in page.stages.items()},
        "selected_source": page.selected_source,
        "extraction_strategy": page.extraction_strategy,
        "decisions": _plain(page.decisions),
        "errors": _plain(page.errors),
        "status": page.status.value,
    }


def _page_from_payload(payload: Mapping[str, Any]) -> PageContext:
    """Rebuild one page context from its payload."""
    return PageContext(
        page_number=payload["page_number"],
        artifacts={
            key: None if value is None else Path(value)
            for key, value in payload["artifacts"].items()
        },
        results={},
        stages={
            name: _stage_from_payload(stage)
            for name, stage in payload["stages"].items()
        },
        selected_source=payload["selected_source"],
        extraction_strategy=payload["extraction_strategy"],
        decisions=[dict(record) for record in payload["decisions"]],
        errors=[dict(record) for record in payload["errors"]],
        status=StageState(payload["status"]),
    )
