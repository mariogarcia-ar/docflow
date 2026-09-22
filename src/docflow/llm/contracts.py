"""Contract types of the LLM processor: ``LLMInput → LLMResult``.

This module is vocabulary only. It performs no I/O, imports no provider SDK and contains
no processing logic; Ollama, vLLM and any hosted API are reached exclusively from
:mod:`docflow.llm.primitives`.

The processor owns two levels and they must not be confused with the orchestrator's
documental level. Here, ``LLMGraphState`` tracks the *inference* subgraph
(``classify → extract_a/extract_b → compare → validate → consolidate``). It never
replaces the orchestrator's ``DocumentContext`` / ``PageContext`` / ``StageExecution``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from docflow.states import StageState

LLMStatus = Literal["success", "failed"]

# Node-level states of the inference subgraph. This is the *same* vocabulary the
# orchestrator and the processors use — ``LLM-01`` requires the node states to be
# "aligned with the orchestrator vocabulary" and the idea's §"Estados de nodo" lists
# exactly the nine shared states. A separate enum would be a second set of words for one
# concept; the two *levels* stay separate (node state never replaces a stage state),
# which is a different thing from inventing different words for the same idea.
LLMNodeState = StageState

# Validation verdicts of one inference result.
LLMValidationState = Literal["VALID", "INVALID", "RETRYABLE"]


@dataclass(frozen=True)
class Usage:
    """Token accounting for one inference, as reported by the provider.

    Attributes:
        input_tokens: Tokens sent, or ``None`` when the provider omits it.
        output_tokens: Tokens generated, or ``None`` when the provider omits it.
        total_tokens: Total tokens, or ``None`` when the provider omits it.
        cached_tokens: Tokens served from a provider cache, or ``None``.
        provider_usage: The provider's raw usage payload, unmodified.
        estimated_cost: Estimated cost in the provider's currency, or ``None`` when it
            cannot be estimated.
    """

    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    cached_tokens: int | None
    provider_usage: dict[str, Any]
    estimated_cost: float | None


@dataclass(frozen=True)
class Timing:
    """Wall-clock durations of one inference.

    Attributes:
        queue_time: Time spent waiting for the provider, or ``None`` when unmeasured.
        load_time: Time spent loading the model, or ``None`` when unmeasured.
        inference_time: Time spent generating, or ``None`` when unmeasured.
        total_time: Total elapsed time.
    """

    queue_time: float | None
    load_time: float | None
    inference_time: float | None
    total_time: float


@dataclass(frozen=True)
class ComparisonResult:
    """Comparison of two or more inference outputs.

    Attributes:
        matches: Fields whose values agree.
        conflicts: Fields whose values disagree.
        agreement: Agreement ratio per field.
        metadata: Additional comparison context.
    """

    matches: dict[str, Any]
    conflicts: dict[str, Any]
    agreement: dict[str, float]
    metadata: dict[str, Any]


@dataclass(frozen=True)
class LLMAttempt:
    """One provider attempt. Earlier attempts are never discarded on a retry.

    Attributes:
        attempt_id: Identifier of this attempt, distinct per attempt.
        node_id: Node the attempt belongs to, or ``None`` for a single call.
        request_key: The request identity this attempt was made under.
        provider: Provider name.
        model: Model name.
        request_metadata: What was sent, minus secrets.
        raw_response: The provider's raw response.
        parsed_response: The parsed response, or ``None`` when parsing failed.
        validation: The validation verdict for this attempt.
        usage: Token accounting.
        timing: Durations.
        error: The failure that ended the attempt, or ``None`` if it succeeded.
        status: Outcome of the attempt.
    """

    attempt_id: str
    node_id: str | None
    request_key: str
    provider: str
    model: str
    request_metadata: dict[str, Any]
    raw_response: str
    parsed_response: Any
    validation: LLMValidationState
    usage: Usage
    timing: Timing
    error: str | None
    status: LLMStatus


@dataclass(frozen=True)
class LLMInput:
    """Input contract of the LLM processor.

    A missing source is a missing source: ``document`` and ``schema`` are ``None`` when
    absent, never an empty string standing in for them.

    Attributes:
        task: The task to perform.
        provider: Provider name.
        model: Model name.
        template: Template identifier to render.
        document: The document text, or ``None`` when the task takes no document.
        images: Images to send, in order.
        extra_context: Additional values available to the template.
        schema: Schema identifier to validate the response against, or ``None``.
        options: Provider and decoding options.
        graph: The inference graph to execute, or ``None`` for a single call.
        metadata: Correlation metadata.
    """

    task: str
    provider: str
    model: str
    template: str
    document: str | None
    images: list[str]
    extra_context: dict[str, Any]
    schema: str | None
    options: dict[str, Any]
    graph: dict[str, Any] | None
    metadata: dict[str, Any]


@dataclass
class LLMNodeResult:
    """Result of one node of the inference subgraph.

    Attributes:
        node_id: The node's identifier.
        request_key: The request identity this node ran under; the reuse key at node
            level.
        status: Outcome of the node, from the shared stage-state vocabulary.
        result: The node's parsed result.
        attempts: Every attempt made, in order.
        validation: The node's validation record.
        usage: Accumulated token accounting.
        timing: Accumulated durations.
        metadata: Additional node metadata.
    """

    node_id: str
    request_key: str
    status: StageState
    result: Any
    attempts: list[LLMAttempt]
    validation: dict[str, Any]
    usage: Usage
    timing: Timing
    metadata: dict[str, Any]


@dataclass
class LLMResult:
    """Output contract of the LLM processor.

    Attributes:
        run_id: Identity of this inference run.
        task: The task that was performed.
        provider: Provider name.
        model: Model name.
        graph_id: The graph that ran, or ``None`` for a single call.
        node_results: Results by node identifier.
        raw_response: The provider's raw response for a single call, or ``None``.
        parsed_response: The parsed response for a single call.
        schema_valid: Whether the response satisfied the schema.
        validation_errors: Why it did not, when it did not.
        attempts: Every attempt made for a single call, in order.
        comparisons: Output comparisons by comparison identifier.
        usage: Accumulated token accounting.
        timing: Accumulated durations.
        status: Outcome of the run, from the shared stage-state vocabulary.
        metadata: Additional run metadata.
    """

    run_id: str
    task: str
    provider: str
    model: str
    graph_id: str | None
    node_results: dict[str, LLMNodeResult]
    raw_response: str | None
    parsed_response: Any
    schema_valid: bool
    validation_errors: list[str]
    attempts: list[LLMAttempt]
    comparisons: dict[str, ComparisonResult]
    usage: Usage
    timing: Timing
    status: StageState
    metadata: dict[str, Any]


@dataclass
class LLMGraphState:
    """Durable state of the inference subgraph.

    Internal to this processor: it is persisted under ``llm/`` and never replaces the
    orchestrator's document state.

    Attributes:
        run_id: Identity of this inference run.
        graph_id: The graph being executed.
        graph_version: Version of the graph definition.
        status: Outcome of the run so far, from the shared stage-state vocabulary.
        current_nodes: Nodes currently running.
        node_states: State by node identifier.
        node_results: Results by node identifier.
        attempts: Attempts by node identifier.
        comparisons: Comparisons by comparison identifier.
        errors: Failures recorded during the run.
        usage: Accumulated token accounting.
        stop_requested: Whether a stop was requested.
        final_result: The consolidated result, once the graph completes.
    """

    run_id: str
    graph_id: str
    graph_version: str
    status: StageState
    current_nodes: list[str]
    node_states: dict[str, StageState]
    node_results: dict[str, LLMNodeResult]
    attempts: dict[str, list[LLMAttempt]]
    comparisons: dict[str, ComparisonResult]
    errors: list[str]
    usage: Usage
    stop_requested: bool
    final_result: LLMResult | None
