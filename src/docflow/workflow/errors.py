"""Containing a failed stage (``ORC-16``).

A processor failure is **reported, never propagated**: the stage is recorded ``FAILED``,
an error record is written on the page and on the document, and the run decides between the
two outcomes the PoC implements — and advertises only those two:

``retry processor``
    the whole processor is attempted again, when policy allows and the stage has attempts
    left. This is a retry of a *stage*, which is a different thing from the LLM processor's
    own retries inside one inference; the two levels never mix.

``REVIEW_REQUIRED``
    the run cannot decide by itself. The stage stays ``FAILED`` and the document says a
    human is needed; the page is not silently dropped.

The richer fallbacks — ``fallback``, ``continue partial``, ``stop page``, ``pause
document`` — are deferred to the MVP gate and are deliberately absent from the vocabulary,
because advertising an outcome nothing implements is worse than not offering it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from docflow.states import StageState
from docflow.workflow.contracts import (
    DocumentContext,
    ErrorOutcome,
    PageContext,
    StageExecution,
)
from docflow.workflow.stages import set_stage_status
from docflow.workflow.tracing import register_error

#: The PoC's fixed ceiling on attempts for one stage.
#:
#: It is a named PoC value rather than a configuration key, and it is tagged: a caller
#: cannot currently ask for a different ceiling, and an unstated default would be a silent
#: answer to a question the policy does not pose.
# TODO: [MVP] make the ceiling a configuration key with a documented rationale per stage.
MAX_STAGE_ATTEMPTS: Final[int] = 2


def handle_processor_error(
    context: DocumentContext,
    page: PageContext | None,
    stage: StageExecution,
    *,
    failure: Mapping[str, Any],
) -> ErrorOutcome:
    """Record a stage failure and decide what the run does about it.

    Args:
        context: The document context the run is operating on.
        page: The page the stage belongs to, or ``None`` for a document-level stage.
        stage: The stage that failed; it is moved to ``FAILED``.
        failure: The typed failure record the processor reported.

    Returns:
        ``"retry processor"`` when policy allows and the stage has attempts left,
        ``"REVIEW_REQUIRED"`` otherwise. The document is left ``REVIEW_REQUIRED`` in that
        second case, so a human-facing outcome is visible in the result and not only in the
        error list.
    """
    retry_allowed = (
        context.execution_policy.retry_failed and stage.attempts < MAX_STAGE_ATTEMPTS
    )
    outcome: ErrorOutcome = "retry processor" if retry_allowed else "REVIEW_REQUIRED"

    record = {
        "type": str(failure.get("type", "INTERNAL_ERROR")),
        "message": str(failure.get("message", "")),
        "recoverable": bool(failure.get("recoverable", False)),
        "metadata": dict(failure.get("metadata", {})),
    }
    set_stage_status(stage, StageState.FAILED, error=record)
    page_number = None if page is None else page.page_number
    register_error(
        context,
        stage=stage.stage,
        error_type=record["type"],
        message=record["message"],
        recoverable=record["recoverable"],
        outcome=outcome,
        page_number=page_number,
        metadata=record["metadata"],
    )
    if page is not None:
        register_error(
            page,
            stage=stage.stage,
            error_type=record["type"],
            message=record["message"],
            recoverable=record["recoverable"],
            outcome=outcome,
            page_number=page_number,
            metadata=record["metadata"],
        )
        if outcome == "REVIEW_REQUIRED":
            page.status = StageState.FAILED
    if outcome == "REVIEW_REQUIRED":
        context.status = "REVIEW_REQUIRED"
    return outcome
