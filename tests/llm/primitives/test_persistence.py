"""Tests for the two-artifact round trip (``LLM-11``).

The round trip is the whole point: a run that was interrupted is resumed from these two files,
so everything a reuse decision reads — the node keys, the attempts, the validation verdicts —
has to come back exactly as it went in.
"""

from __future__ import annotations

from pathlib import Path

import pytest

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
from docflow.llm.primitives import LLMPrimitiveError
from docflow.llm.primitives.persistence import (
    RESULT_NAME,
    STATE_NAME,
    load_graph_state,
    load_result,
    result_from_payload,
    result_to_payload,
    save_graph_state,
    save_result,
    state_from_payload,
    state_to_payload,
)
from docflow.states import StageState
from tests.llm.samples import measured_usage

USAGE = measured_usage()
TIMING = Timing(queue_time=None, load_time=0.1, inference_time=0.4, total_time=0.5)
ERROR = LLMError(
    type="INVALID_JSON",
    message="the provider answered something that is not JSON",
    recoverable=True,
    metadata={"json_error": "Expecting value"},
)
ATTEMPT = LLMAttempt(
    attempt_id="classify-attempt-001",
    node_id="classify",
    request_key="key-1",
    provider="ollama",
    model="test-model",
    request_metadata={"messages": 1, "images": 0, "schema": True, "prompt_tokens": 40},
    raw_response='{"summary": "…"}',
    parsed_response={"summary": "…"},
    validation="VALID",
    usage=USAGE,
    timing=TIMING,
    error=None,
    status="success",
)
FAILED_ATTEMPT = LLMAttempt(
    attempt_id="extract_b-attempt-001",
    node_id="extract_b",
    request_key="key-2",
    provider="ollama",
    model="test-model",
    request_metadata={"messages": 1},
    raw_response=None,
    parsed_response=None,
    validation="INVALID",
    usage=Usage(None, None, None, None, {}, None),
    timing=TIMING,
    error=ERROR,
    status="failed",
)
NODE = LLMNodeResult(
    node_id="classify",
    request_key="key-1",
    status=StageState.SUCCESS,
    result={"summary": "…"},
    attempts=[ATTEMPT],
    validation={"status": "VALID", "retryable": False},
    errors=[],
    usage=USAGE,
    timing=TIMING,
    metadata={"request_key": "key-1"},
)
FAILED_NODE = LLMNodeResult(
    node_id="extract_b",
    request_key="key-2",
    status=StageState.FAILED,
    result=None,
    attempts=[FAILED_ATTEMPT],
    validation={"status": "INVALID", "retryable": False},
    errors=[ERROR],
    usage=Usage(None, None, None, None, {}, None),
    timing=TIMING,
    metadata={},
)
COMPARISON = ComparisonResult(
    matches={"summary": "…"},
    conflicts={"page_count": {"left": 3, "right": 4}},
    agreement={"summary": 1.0, "page_count": 0.0},
    metadata={"left_node": "extract_a", "right_node": "extract_b", "fields": 2},
)
RESULT = LLMResult(
    run_id="run-1",
    task="extract_fields",
    provider="ollama",
    model="test-model",
    graph_id="default_inference",
    node_results={"classify": NODE, "extract_b": FAILED_NODE},
    raw_response='{"summary": "…"}',
    parsed_response={"summary": "…"},
    schema_valid=False,
    validation_errors=["the answer does not satisfy the schema"],
    errors=[ERROR],
    attempts=[ATTEMPT, FAILED_ATTEMPT],
    comparisons={"compare:extract_a~extract_b": COMPARISON},
    usage=USAGE,
    timing=TIMING,
    status=StageState.FAILED,
    metadata={"node_actions": {"classify": "EXECUTE", "extract_b": "EXECUTE"}},
)
STATE = LLMGraphState(
    run_id="run-1",
    graph_id="default_inference",
    graph_version="1",
    status=StageState.FAILED,
    current_nodes=[],
    node_states={"classify": StageState.SUCCESS, "extract_b": StageState.FAILED},
    node_results={"classify": NODE, "extract_b": FAILED_NODE},
    attempts={"classify": [ATTEMPT], "extract_b": [FAILED_ATTEMPT]},
    comparisons={"compare:extract_a~extract_b": COMPARISON},
    errors=["the provider answered something that is not JSON"],
    usage=USAGE,
    stop_requested=False,
    final_result=RESULT,
)


def test_a_result_round_trips_through_its_payload() -> None:
    """Every field a reader relies on survives, including the typed failure and the verdict."""
    restored = result_from_payload(result_to_payload(RESULT))

    assert restored == RESULT


def test_a_graph_state_round_trips_through_its_payload() -> None:
    """The node keys, the attempts and the comparisons come back exactly as they went in."""
    restored = state_from_payload(state_to_payload(STATE))

    assert restored == STATE


def test_a_state_that_was_never_saved_is_not_an_error(tmp_path: Path) -> None:
    """A first run and a deliberately discarded state mean the same thing: execute the chain."""
    assert load_graph_state(tmp_path) is None
    assert load_result(tmp_path) is None


def test_a_saved_state_and_result_land_under_the_names_the_plan_fixes(
    tmp_path: Path,
) -> None:
    """``llm/run_001/{state.json, final_result.json}``, and nothing else."""
    save_graph_state(tmp_path, STATE)
    save_result(tmp_path, RESULT)

    assert sorted(path.name for path in tmp_path.iterdir()) == [
        RESULT_NAME.name,
        STATE_NAME.name,
    ]
    assert load_graph_state(tmp_path) == STATE
    assert load_result(tmp_path) == RESULT


def test_a_state_file_this_processor_cannot_read_is_reported(tmp_path: Path) -> None:
    """A half-read state would silently re-run paid calls, so it is a failure instead."""
    (tmp_path / STATE_NAME).write_text("{not json", encoding="utf-8")

    with pytest.raises(LLMPrimitiveError) as raised:
        load_graph_state(tmp_path)

    assert raised.value.error.type == "INTERNAL_ERROR"
    assert raised.value.error.recoverable is False


def test_a_state_file_holding_something_other_than_an_object_is_reported(
    tmp_path: Path,
) -> None:
    """A list where a result belongs describes no result at all."""
    (tmp_path / RESULT_NAME).write_text("[1, 2]", encoding="utf-8")

    with pytest.raises(LLMPrimitiveError) as raised:
        load_result(tmp_path)

    assert raised.value.error.type == "INTERNAL_ERROR"
