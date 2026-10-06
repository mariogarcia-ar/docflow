"""Request builders shared by the orchestrator's tests.

A valid :class:`~docflow.workflow.contracts.DocumentRequest` needs four processors'
options, two policy flags and a working root, and every test that runs the workflow needs
the same ones. Building them here keeps the literals out of every test and keeps the
"no default is substituted" rule visible: a test that wants a missing option omits a key
rather than mutating a default.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from docflow.states import StageState
from docflow.workflow import (
    DocumentRequest,
    ErrorOutcome,
    ExecutionPolicy,
    StageExecution,
    StageName,
)
from docflow.workflow.context import create_page_context
from docflow.workflow.stages import (
    create_stage,
    register_stage_outputs,
    set_stage_status,
)
from docflow.workflow.tracing import register_decision, register_error
from tests.factories import build_llm_input
from tests.image.samples import build_options as build_image_options
from tests.ocr.samples import build_options as build_ocr_options
from tests.pdf.samples import build_options as build_pdf_options

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

#: A three-page PDF with a native text layer — the happy path's input.
SAMPLE_PDF = FIXTURES / "pdf" / "pdf_sample_text.pdf"

#: A committed PNG — the direct-image happy path's input.
SAMPLE_IMAGE = FIXTURES / "image" / "color_layout.png"

#: A committed file that is neither a PDF nor an image.
UNSUPPORTED_FILE = FIXTURES / "pdf" / "build_samples.py"

#: The document policies a run starts from.
DEFAULT_POLICIES: dict[str, Any] = {"allow_ocr": True, "allow_vlm": False}


def execution_policy(**overrides: Any) -> ExecutionPolicy:
    """Return an execution policy with any subset overridden.

    Args:
        **overrides: The fields to change.

    Returns:
        The policy.
    """
    base: dict[str, Any] = {
        "resume": False,
        "reuse_successful": True,
        "retry_failed": True,
        "skip_stages": [],
        "force_stages": [],
        "stop_after_stage": None,
        "start_from_stage": None,
        "invalidate_downstream": True,
        "dry_run": False,
        "parallel_pages": False,
    }
    base.update(overrides)
    return ExecutionPolicy(**base)


def run_options(tmp_path: Path) -> dict[str, Any]:
    """Return a complete option set rooted in ``tmp_path``.

    Each processor's options come from that processor's own sample builder, so the
    workflow's tests cannot drift from the option sets the Phase 1 suites exercise.

    Args:
        tmp_path: The test's temporary directory.

    Returns:
        One entry per stage, every field stated.
    """
    invocation = asdict(build_llm_input())
    return {
        "output_dir": str(tmp_path / "work"),
        "pdf": asdict(build_pdf_options()),
        "image": asdict(build_image_options()),
        "ocr": asdict(build_ocr_options()),
        "llm": {
            "task": invocation["task"],
            "provider": invocation["provider"],
            "model": invocation["model"],
            "template": invocation["template"],
            "schema": invocation["schema"],
            "options": invocation["options"],
        },
    }


def document_request(
    tmp_path: Path,
    *,
    input_path: Path | None = None,
    input_type: str = "PDF",
    policies: dict[str, Any] | None = None,
    execution: ExecutionPolicy | None = None,
    options: dict[str, Any] | None = None,
    document_id: str = "doc-1",
) -> DocumentRequest:
    """Return a valid document request rooted in ``tmp_path``.

    Args:
        tmp_path: The test's temporary directory.
        input_path: The input to process; the committed PDF sample by default.
        input_type: The declared input type.
        policies: Document policies; the defaults when omitted.
        execution: Execution policy; a permissive one when omitted.
        options: Run options; a complete set when omitted.
        document_id: The document identity.

    Returns:
        The request.
    """
    return DocumentRequest(
        document_id=document_id,
        input_path=SAMPLE_PDF if input_path is None else input_path,
        input_type=input_type,  # type: ignore[arg-type]
        workflow="default",
        policies=dict(DEFAULT_POLICIES if policies is None else policies),
        execution=execution_policy() if execution is None else execution,
        options=run_options(tmp_path) if options is None else options,
        metadata={"correlation": document_id},
    )


def work_dir(tmp_path: Path) -> Path:
    """Return the working root a request built here uses."""
    return tmp_path / "work"


def state_file(tmp_path: Path) -> Path:
    """Return the durable context path a request built here uses."""
    return work_dir(tmp_path) / "document_context.json"


def artifact(tmp_path: Path, name: str, content: bytes = b"content") -> Path:
    """Write a small artifact and return its path.

    Args:
        tmp_path: The test's temporary directory.
        name: The artifact's name, relative to ``tmp_path``.
        content: Its bytes.

    Returns:
        The artifact's path.
    """
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def stage(
    name: StageName,
    *,
    page_number: int | None = 1,
    status: StageState | None = None,
    reason: str = "a reason",
    processing_key: str = "key",
    output: tuple[Path, ...] = (),
    input_artifacts: tuple[Path, ...] = (),
    attempts: int = 0,
) -> StageExecution:
    """Return a stage execution in the state a test needs it in.

    The processor identity is derived from the stage name, so a test never states it; the
    key is a literal because a unit test is about what a *given* key decides, not about
    how a key is computed (``ORC-02``'s tests cover that).

    Args:
        name: Which stage.
        page_number: The page it belongs to, or ``None`` for a document-level stage.
        status: The state to leave it in, or ``None`` for ``NOT_STARTED``.
        reason: The reason a deliberate outcome records.
        processing_key: The stored key.
        output: Artifacts to register as published.
        input_artifacts: Artifacts to register as consumed.
        attempts: How many attempts it has already made.

    Returns:
        The stage execution.
    """
    execution = create_stage(
        name,
        processor=name.lower(),
        processor_version="0.0.0",
        processing_key=processing_key,
        options_hash="digest",
        input_artifacts=input_artifacts,
        page_number=page_number,
    )
    execution.attempts = attempts
    if output:
        register_stage_outputs(execution, output)
    if status is not None:
        set_stage_status(execution, status, reason=reason)
    return execution


def decision_record(
    stage_name: str,
    action: str,
    reason: str,
    *,
    page_number: int | None = 1,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a routing decision, as the production writer records it.

    The record is produced by :func:`docflow.workflow.tracing.register_decision` against a
    throwaway page, so a test that asserts on the shape asserts on the shape production
    writes rather than on a copy of it that can drift.
    """
    return register_decision(
        create_page_context(0),
        stage=stage_name,
        action=action,
        reason=reason,
        page_number=page_number,
        metadata=metadata,
    )


def error_record(
    stage_name: str,
    error_type: str,
    *,
    outcome: ErrorOutcome = "REVIEW_REQUIRED",
    page_number: int | None = 1,
    message: str = "the processor reported a failure",
    recoverable: bool = False,
) -> dict[str, Any]:
    """Return an error record, as the production writer records it."""
    return register_error(
        create_page_context(0),
        stage=stage_name,
        error_type=error_type,
        message=message,
        recoverable=recoverable,
        outcome=outcome,
        page_number=page_number,
    )
