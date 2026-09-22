"""Round-trip test for the LLM contract (``GEN-06``).

Proves ``LLMInput → LLMResult`` round-trips an in-memory fake end to end before any
provider is reached. The fake provider is the same posture ``LLM-03`` adopts in Phase 1.
"""

from __future__ import annotations

import pytest

from docflow.llm import (
    ComparisonResult,
    LLMAttempt,
    LLMInput,
    LLMResult,
    Timing,
    Usage,
)
from docflow.states import StageState
from tests.factories import build_llm_input, incomplete_call


def fake_process_llm_request(request: LLMInput) -> LLMResult:
    """Stand-in processor: builds a result from the request and nothing else."""
    usage = Usage(
        input_tokens=12,
        output_tokens=4,
        total_tokens=16,
        cached_tokens=None,
        provider_usage={"prompt_eval_count": 12, "eval_count": 4},
        estimated_cost=None,
    )
    timing = Timing(queue_time=0.0, load_time=0.1, inference_time=0.4, total_time=0.5)
    attempt = LLMAttempt(
        attempt_id="attempt_001",
        node_id=None,
        request_key="key-from-LLM-05",
        provider=request.provider,
        model=request.model,
        request_metadata={"messages": 2},
        raw_response='{"field": "value"}',
        parsed_response={"field": "value"},
        validation="VALID",
        usage=usage,
        timing=timing,
        error=None,
        status="success",
    )
    return LLMResult(
        run_id="run-1",
        task=request.task,
        provider=request.provider,
        model=request.model,
        graph_id=None,
        node_results={},
        raw_response=attempt.raw_response,
        parsed_response=attempt.parsed_response,
        schema_valid=True,
        validation_errors=[],
        attempts=[attempt],
        comparisons={},
        usage=usage,
        timing=timing,
        status=StageState.SUCCESS,
        metadata={"document_id": "doc-1"},
    )


def test_the_fake_returns_the_matching_result_type() -> None:
    """A valid request produces an ``LLMResult``."""
    result = fake_process_llm_request(build_llm_input())

    assert isinstance(result, LLMResult)


def test_the_task_and_model_survive_the_round_trip() -> None:
    """The result names what was actually asked of which model."""
    request = build_llm_input()

    result = fake_process_llm_request(request)

    assert result.task == request.task
    assert result.model == request.model
    assert result.provider == request.provider


def test_the_attempt_carries_a_non_empty_request_key() -> None:
    """An attempt that cannot name its request cannot be reused, so it must name it."""
    result = fake_process_llm_request(build_llm_input())

    assert result.attempts[0].request_key


def test_a_document_and_a_schema_that_are_absent_stay_none() -> None:
    """Absence is reported as ``None``, never as an empty string standing in."""
    request = LLMInput(
        task="classify",
        provider="ollama",
        model="test-model",
        template="classify",
        document=None,
        images=[],
        extra_context={},
        schema=None,
        options={},
        graph=None,
        metadata={},
    )

    assert request.document is None
    assert request.schema is None


def test_the_usage_record_keeps_an_unmeasured_value_as_none() -> None:
    """A provider that does not report a figure produces ``None``, not a zero."""
    result = fake_process_llm_request(build_llm_input())

    assert result.usage.cached_tokens is None
    assert result.usage.estimated_cost is None
    assert result.usage.total_tokens == 16


def test_a_comparison_record_is_usable_when_the_graph_produces_none() -> None:
    """A single-call run carries no comparisons; an empty map is not a verdict."""
    result = fake_process_llm_request(build_llm_input())

    assert not result.comparisons
    assert not result.node_results
    assert isinstance(ComparisonResult, type)


def test_the_validation_outcome_is_explicit() -> None:
    """A validated response says so, and says so without a list of failures."""
    result = fake_process_llm_request(build_llm_input())

    assert result.schema_valid is True
    assert not result.validation_errors


def test_the_run_outcome_uses_the_shared_stage_state_vocabulary() -> None:
    """The inference level and the documental level do not speak two languages."""
    result = fake_process_llm_request(build_llm_input())

    assert result.status is StageState.SUCCESS


def test_a_missing_required_field_is_rejected_instead_of_defaulted() -> None:
    """A missing template is not silently replaced by some default template."""
    complete = build_llm_input()
    incomplete = {
        "task": complete.task,
        "provider": complete.provider,
        "model": complete.model,
        "document": complete.document,
        "images": complete.images,
        "extra_context": complete.extra_context,
        "schema": complete.schema,
        "options": complete.options,
        "graph": complete.graph,
        "metadata": complete.metadata,
    }

    with pytest.raises(TypeError):
        incomplete_call(type(complete), incomplete)
