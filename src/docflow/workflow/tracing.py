"""Decision and error tracing records (``ORC-18``).

Every routing decision and every failure is written down as a structured record, because
after a run the only honest answer to "why did this page skip OCR?" is the record the run
wrote while it decided — not a reconstruction from the final state.

The three writers exist because there are three shapes of record, and they are the only
writers of ``DocumentContext.decisions`` / ``.errors`` and ``PageContext.decisions`` /
``.errors``:

* :func:`register_decision` — a stage, an action and a *required* reason;
* :func:`register_error` — a failure, its typed kind and the outcome the run chose;
* :func:`append_workflow_trace` — a record that is neither (a stop, a dry run).

A reason is required rather than optional on purpose: a decision nobody can explain is not
a trace, it is a claim.

# TODO: [RELEASE] structured traces are not exported to any telemetry or log sink; they
# live in the durable context only.
"""

from __future__ import annotations

from typing import Any

from docflow.workflow.contracts import (
    DocumentContext,
    ErrorOutcome,
    PageContext,
    StageAction,
    StageName,
)

#: A routing decision: which stage, which action, and why.
DecisionRecord = dict[str, Any]

#: A failure: which stage, which typed kind, and which outcome the run chose.
ErrorRecord = dict[str, Any]

#: Either durable state that can carry records.
TraceTarget = DocumentContext | PageContext


def register_decision(
    target: TraceTarget,
    *,
    stage: StageName | str,
    action: StageAction | str,
    reason: str,
    page_number: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> DecisionRecord:
    """Append a routing decision to ``target``'s decision list and return it.

    Args:
        target: The document or page context the decision belongs to.
        stage: The stage the decision is about, or ``"DOCUMENT"`` for a run-level one.
        action: What was decided.
        reason: Why. Required: a decision without a reason cannot be audited.
        page_number: The page, when the decision is page-scoped.
        metadata: Anything else worth tracing, e.g. the cause of an invalidation.

    Returns:
        The record, as it was appended.
    """
    record: DecisionRecord = {
        "stage": stage,
        "action": action,
        "reason": reason,
        "page_number": page_number,
        "metadata": {} if metadata is None else dict(metadata),
    }
    target.decisions.append(record)
    return record


def register_error(
    target: TraceTarget,
    *,
    stage: StageName | str,
    error_type: str,
    message: str,
    recoverable: bool,
    outcome: ErrorOutcome,
    page_number: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> ErrorRecord:
    """Append an error record to ``target``'s error list and return it.

    Args:
        target: The document or page context the failure belongs to.
        stage: The stage that failed.
        error_type: The typed kind the processor reported; never free text.
        message: Human-readable detail, beside the type and never instead of it.
        recoverable: Whether the run could continue without the artifact.
        outcome: What the orchestrator decided to do about it — one of the two the PoC
            implements.
        page_number: The page, when the failure is page-scoped.
        metadata: Diagnostic context.

    Returns:
        The record, as it was appended.
    """
    record: ErrorRecord = {
        "stage": stage,
        "type": error_type,
        "message": message,
        "recoverable": recoverable,
        "outcome": outcome,
        "page_number": page_number,
        "metadata": {} if metadata is None else dict(metadata),
    }
    target.errors.append(record)
    return record


def append_workflow_trace(
    target: TraceTarget,
    *,
    kind: str,
    reason: str,
    metadata: dict[str, Any] | None = None,
) -> DecisionRecord:
    """Append a run-level trace record — a stop, a dry run — and return it.

    Args:
        target: The context the record belongs to.
        kind: Which run-level event this is.
        reason: Why it happened.
        metadata: Anything else worth tracing.

    Returns:
        The record, as it was appended.
    """
    record: DecisionRecord = {
        "kind": kind,
        "reason": reason,
        "metadata": {} if metadata is None else dict(metadata),
    }
    target.decisions.append(record)
    return record
