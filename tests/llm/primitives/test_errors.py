"""Tests for the typed failure vocabulary and the retryability of each kind.

The table is a decision, not a detail: a kind that is retryable buys another *paid* call, and a
kind that is not must never do so. Both halves are asserted, so a kind moved from one set to the
other has to be a deliberate edit to a test rather than a silent edit to a constant.
"""

from __future__ import annotations

import pytest

from docflow.llm.contracts import LLMError
from docflow.llm.primitives import (
    NON_RETRYABLE_KINDS,
    PRIMITIVE_NAMES,
    PROVIDER_KINDS,
    RETRYABLE_KINDS,
    LLMPrimitiveError,
    is_retryable,
    typed_failure,
)
from docflow.llm.primitives.errors import RETRYABLE_KINDS as SAME_SET


def test_a_typed_failure_carries_a_kind_a_message_and_a_recoverability_flag() -> None:
    """The kind is the classification; the message is only how a human reads it."""
    failure = typed_failure(
        "TIMEOUT", "the provider did not answer", metadata={"timeout": 3.0}
    )

    assert isinstance(failure, LLMPrimitiveError)
    assert failure.error.type == "TIMEOUT"
    assert failure.error.message == "the provider did not answer"
    assert failure.error.recoverable is True
    assert failure.error.metadata == {"timeout": 3.0}
    assert str(failure) == "the provider did not answer"


def test_the_retryable_kinds_are_the_ones_another_call_could_fix() -> None:
    """The set is stated here as well as in the module, so moving a kind is visible."""
    assert RETRYABLE_KINDS == SAME_SET
    assert {
        "PROVIDER_ERROR",
        "TIMEOUT",
        "INVALID_RESPONSE",
        "INVALID_JSON",
        "SCHEMA_ERROR",
    } == RETRYABLE_KINDS


@pytest.mark.parametrize(
    "kind",
    ["MODEL_UNAVAILABLE", "CONTEXT_OVERFLOW", "DEPENDENCY_ERROR", "INTERNAL_ERROR"],
)
def test_a_failure_the_provider_cannot_fix_is_never_retried(kind: str) -> None:
    """Asking a missing model again, immediately, is a second paid call with one answer."""
    assert kind in NON_RETRYABLE_KINDS
    assert not is_retryable(typed_failure(kind, "no").error)  # type: ignore[arg-type]


def test_an_unclassified_kind_is_never_retried() -> None:
    """An unknown failure has not earned a second call."""
    unknown = LLMError(
        type="SOMETHING_NEW",  # type: ignore[arg-type]  # the point is that it is not in the set
        message="x",
        recoverable=True,
        metadata={},
    )

    assert not is_retryable(unknown)


def test_the_provider_names_map_to_a_transport_and_never_to_a_default() -> None:
    """A provider the seam does not know is absent from the map, not mapped to something."""
    assert PROVIDER_KINDS["ollama"] == "ollama"
    assert PROVIDER_KINDS["vllm"] == "openai_compatible"
    assert PROVIDER_KINDS["openai"] == "openai_compatible"
    assert "something-else" not in PROVIDER_KINDS


def test_the_surface_is_the_seven_primitives_the_wbs_names() -> None:
    """LLM-09's deliverable is a closed list; a sixth generator would be scope."""
    assert PRIMITIVE_NAMES == (
        "generate_text",
        "generate_multimodal",
        "generate_structured",
        "list_models",
        "check_model_available",
        "get_context_window",
        "get_model_info",
    )
