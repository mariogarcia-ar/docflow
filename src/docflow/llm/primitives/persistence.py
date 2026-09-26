"""Round-tripping the chain state and the final result through their two JSON artifacts.

The LLM processor's persistence is deliberately two files under the run's ``llm/`` namespace —
``state.json`` and ``final_result.json`` — because those are the two things a reader of a run
needs: what happened node by node, and what the run concluded. The per-node artifact tree of
§9.6 is deferred rather than half-invented: a directory schema nothing reads is worse than one
file that is complete.

The round trip is explicit rather than reflective. ``asdict`` alone would serialize the records
but leave nothing that can rebuild them — a dataclass is not a schema — and the two states a
resumed run must reproduce exactly (the node keys and the attempts) are precisely the ones a
generic reader would drop.

A state file this processor cannot read is an ``INTERNAL_ERROR``: the file *is* this processor's
own artifact, so a broken one is a failure of this processor's record, not of the run's input.

# TODO: [MVP] a durable file-backed store and the per-node artifact tree replace these two files;
# Phase 1 keeps the whole state in memory first and writes it once per run.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any, Final

from docflow.llm.contracts import (
    ComparisonResult,
    LLMAttempt,
    LLMError,
    LLMGraphState,
    LLMNodeResult,
    LLMResult,
    Timing,
    Usage,
)
from docflow.llm.primitives.errors import typed_failure
from docflow.llm.primitives.publication import write_json_atomic
from docflow.states import StageState

#: The two artifacts of a run, named once.
STATE_NAME: Final[Path] = Path("state.json")
RESULT_NAME: Final[Path] = Path("final_result.json")


def _usage_to_payload(usage: Usage) -> dict[str, Any]:
    """Return a usage record as a plain mapping."""
    return asdict(usage)


def _timing_to_payload(timing: Timing) -> dict[str, Any]:
    """Return a timing record as a plain mapping."""
    return asdict(timing)


def _error_to_payload(error: LLMError | None) -> dict[str, Any] | None:
    """Return a typed failure as a plain mapping, or ``None``."""
    return None if error is None else asdict(error)


def _attempt_to_payload(attempt: LLMAttempt) -> dict[str, Any]:
    """Return one attempt as a plain mapping."""
    return {
        "attempt_id": attempt.attempt_id,
        "node_id": attempt.node_id,
        "request_key": attempt.request_key,
        "provider": attempt.provider,
        "model": attempt.model,
        "request_metadata": attempt.request_metadata,
        "raw_response": attempt.raw_response,
        "parsed_response": attempt.parsed_response,
        "validation": attempt.validation,
        "usage": _usage_to_payload(attempt.usage),
        "timing": _timing_to_payload(attempt.timing),
        "error": _error_to_payload(attempt.error),
        "status": attempt.status,
    }


def _node_to_payload(node_result: LLMNodeResult) -> dict[str, Any]:
    """Return one node result as a plain mapping."""
    return {
        "node_id": node_result.node_id,
        "request_key": node_result.request_key,
        "status": str(node_result.status),
        "result": node_result.result,
        "attempts": [_attempt_to_payload(attempt) for attempt in node_result.attempts],
        "validation": node_result.validation,
        "errors": [asdict(error) for error in node_result.errors],
        "usage": _usage_to_payload(node_result.usage),
        "timing": _timing_to_payload(node_result.timing),
        "metadata": node_result.metadata,
    }


def _comparison_to_payload(comparison: ComparisonResult) -> dict[str, Any]:
    """Return one comparison as a plain mapping."""
    return asdict(comparison)


def result_to_payload(result: LLMResult) -> dict[str, Any]:
    """Return an ``LLMResult`` as a JSON-representable mapping.

    Args:
        result: The result to serialize.

    Returns:
        The payload; ``final_result.json`` is exactly this mapping.
    """
    return {
        "run_id": result.run_id,
        "task": result.task,
        "provider": result.provider,
        "model": result.model,
        "graph_id": result.graph_id,
        "node_results": {
            node_id: _node_to_payload(node_result)
            for node_id, node_result in result.node_results.items()
        },
        "raw_response": result.raw_response,
        "parsed_response": result.parsed_response,
        "schema_valid": result.schema_valid,
        "validation_errors": list(result.validation_errors),
        "errors": [asdict(error) for error in result.errors],
        "attempts": [_attempt_to_payload(attempt) for attempt in result.attempts],
        "comparisons": {
            name: _comparison_to_payload(comparison)
            for name, comparison in result.comparisons.items()
        },
        "usage": _usage_to_payload(result.usage),
        "timing": _timing_to_payload(result.timing),
        "status": str(result.status),
        "metadata": result.metadata,
    }


def state_to_payload(state: LLMGraphState) -> dict[str, Any]:
    """Return an ``LLMGraphState`` as a JSON-representable mapping.

    Args:
        state: The chain state to serialize.

    Returns:
        The payload; ``state.json`` is exactly this mapping.
    """
    return {
        "run_id": state.run_id,
        "graph_id": state.graph_id,
        "graph_version": state.graph_version,
        "status": str(state.status),
        "current_nodes": list(state.current_nodes),
        "node_states": {
            node_id: str(node_state)
            for node_id, node_state in state.node_states.items()
        },
        "node_results": {
            node_id: _node_to_payload(node_result)
            for node_id, node_result in state.node_results.items()
        },
        "attempts": {
            node_id: [_attempt_to_payload(attempt) for attempt in attempts]
            for node_id, attempts in state.attempts.items()
        },
        "comparisons": {
            name: _comparison_to_payload(comparison)
            for name, comparison in state.comparisons.items()
        },
        "errors": list(state.errors),
        "usage": _usage_to_payload(state.usage),
        "stop_requested": state.stop_requested,
        "final_result": (
            None
            if state.final_result is None
            else result_to_payload(state.final_result)
        ),
    }


def _usage_from_payload(payload: Mapping[str, Any]) -> Usage:
    """Rebuild a usage record from its mapping."""
    return Usage(
        input_tokens=payload["input_tokens"],
        output_tokens=payload["output_tokens"],
        total_tokens=payload["total_tokens"],
        cached_tokens=payload["cached_tokens"],
        provider_usage=dict(payload["provider_usage"]),
        estimated_cost=payload["estimated_cost"],
    )


def _timing_from_payload(payload: Mapping[str, Any]) -> Timing:
    """Rebuild a timing record from its mapping."""
    return Timing(
        queue_time=payload["queue_time"],
        load_time=payload["load_time"],
        inference_time=payload["inference_time"],
        total_time=payload["total_time"],
    )


def _error_from_payload(payload: Mapping[str, Any] | None) -> LLMError | None:
    """Rebuild a typed failure from its mapping, or ``None``."""
    if payload is None:
        return None
    return LLMError(
        type=payload["type"],
        message=payload["message"],
        recoverable=payload["recoverable"],
        metadata=dict(payload["metadata"]),
    )


def _attempt_from_payload(payload: Mapping[str, Any]) -> LLMAttempt:
    """Rebuild one attempt from its mapping."""
    return LLMAttempt(
        attempt_id=payload["attempt_id"],
        node_id=payload["node_id"],
        request_key=payload["request_key"],
        provider=payload["provider"],
        model=payload["model"],
        request_metadata=dict(payload["request_metadata"]),
        raw_response=payload["raw_response"],
        parsed_response=payload["parsed_response"],
        validation=payload["validation"],
        usage=_usage_from_payload(payload["usage"]),
        timing=_timing_from_payload(payload["timing"]),
        error=_error_from_payload(payload["error"]),
        status=payload["status"],
    )


def _node_from_payload(payload: Mapping[str, Any]) -> LLMNodeResult:
    """Rebuild one node result from its mapping."""
    return LLMNodeResult(
        node_id=payload["node_id"],
        request_key=payload["request_key"],
        status=StageState(payload["status"]),
        result=payload["result"],
        attempts=[_attempt_from_payload(entry) for entry in payload["attempts"]],
        validation=dict(payload["validation"]),
        errors=[
            error
            for error in (_error_from_payload(entry) for entry in payload["errors"])
            if error is not None
        ],
        usage=_usage_from_payload(payload["usage"]),
        timing=_timing_from_payload(payload["timing"]),
        metadata=dict(payload["metadata"]),
    )


def _comparison_from_payload(payload: Mapping[str, Any]) -> ComparisonResult:
    """Rebuild one comparison from its mapping."""
    return ComparisonResult(
        matches=dict(payload["matches"]),
        conflicts=dict(payload["conflicts"]),
        agreement=dict(payload["agreement"]),
        metadata=dict(payload["metadata"]),
    )


def result_from_payload(payload: Mapping[str, Any]) -> LLMResult:
    """Rebuild an ``LLMResult`` from its payload."""
    return LLMResult(
        run_id=payload["run_id"],
        task=payload["task"],
        provider=payload["provider"],
        model=payload["model"],
        graph_id=payload["graph_id"],
        node_results={
            node_id: _node_from_payload(entry)
            for node_id, entry in payload["node_results"].items()
        },
        raw_response=payload["raw_response"],
        parsed_response=payload["parsed_response"],
        schema_valid=payload["schema_valid"],
        validation_errors=list(payload["validation_errors"]),
        errors=[
            error
            for error in (_error_from_payload(entry) for entry in payload["errors"])
            if error is not None
        ],
        attempts=[_attempt_from_payload(entry) for entry in payload["attempts"]],
        comparisons={
            name: _comparison_from_payload(entry)
            for name, entry in payload["comparisons"].items()
        },
        usage=_usage_from_payload(payload["usage"]),
        timing=_timing_from_payload(payload["timing"]),
        status=StageState(payload["status"]),
        metadata=dict(payload["metadata"]),
    )


def state_from_payload(payload: Mapping[str, Any]) -> LLMGraphState:
    """Rebuild an ``LLMGraphState`` from its payload."""
    final_result = payload["final_result"]
    return LLMGraphState(
        run_id=payload["run_id"],
        graph_id=payload["graph_id"],
        graph_version=payload["graph_version"],
        status=StageState(payload["status"]),
        current_nodes=list(payload["current_nodes"]),
        node_states={
            node_id: StageState(state)
            for node_id, state in payload["node_states"].items()
        },
        node_results={
            node_id: _node_from_payload(entry)
            for node_id, entry in payload["node_results"].items()
        },
        attempts={
            node_id: [_attempt_from_payload(entry) for entry in entries]
            for node_id, entries in payload["attempts"].items()
        },
        comparisons={
            name: _comparison_from_payload(entry)
            for name, entry in payload["comparisons"].items()
        },
        errors=list(payload["errors"]),
        usage=_usage_from_payload(payload["usage"]),
        stop_requested=payload["stop_requested"],
        final_result=(
            None if final_result is None else result_from_payload(final_result)
        ),
    )


def save_graph_state(output_dir: Path, state: LLMGraphState) -> Path:
    """Publish the chain state as ``state.json``, atomically.

    Args:
        output_dir: The run's ``llm/`` namespace.
        state: The chain state to record.

    Returns:
        The published path.
    """
    return write_json_atomic(output_dir / STATE_NAME, state_to_payload(state))


def save_result(output_dir: Path, result: LLMResult) -> Path:
    """Publish the run's result as ``final_result.json``, atomically.

    Args:
        output_dir: The run's ``llm/`` namespace.
        result: The result to record.

    Returns:
        The published path.
    """
    return write_json_atomic(output_dir / RESULT_NAME, result_to_payload(result))


def load_graph_state(output_dir: Path) -> LLMGraphState | None:
    """Return the chain state saved under ``output_dir``, or ``None`` when there is none.

    Args:
        output_dir: The run's ``llm/`` namespace.

    Returns:
        The state to resume from, or ``None`` when no state was ever saved — a first run and a
        run whose state was deliberately discarded look the same to this function, and both mean
        "execute the chain".

    Raises:
        LLMPrimitiveError: With ``INTERNAL_ERROR`` when the state file exists but cannot be read
            or rebuilt. Resuming from a half-read state would silently re-run paid calls.
    """
    path = output_dir / STATE_NAME
    if not path.is_file():
        return None
    return state_from_payload(_read_payload(path))


def load_result(output_dir: Path) -> LLMResult | None:
    """Return the result saved under ``output_dir``, or ``None`` when there is none.

    Args:
        output_dir: The run's ``llm/`` namespace.

    Returns:
        The saved result, or ``None``.

    Raises:
        LLMPrimitiveError: With ``INTERNAL_ERROR`` when the file exists but cannot be rebuilt.
    """
    path = output_dir / RESULT_NAME
    if not path.is_file():
        return None
    return result_from_payload(_read_payload(path))


def _read_payload(path: Path) -> dict[str, Any]:
    """Return the JSON object ``path`` holds, or fail naming the file."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as unreadable:
        raise typed_failure(
            "INTERNAL_ERROR",
            f"{path.name} could not be read",
            recoverable=False,
            metadata={"path": str(path), "error": str(unreadable)},
        ) from unreadable
    if not isinstance(payload, dict):
        raise typed_failure(
            "INTERNAL_ERROR",
            f"{path.name} does not hold a JSON object",
            recoverable=False,
            metadata={"path": str(path)},
        )
    return payload
