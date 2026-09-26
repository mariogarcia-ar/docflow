# pylint: disable=too-many-lines,duplicate-code
# Reason: the three entry points of this processor are one workflow in three shapes — one call,
# one node of the chain, and the chain itself — and the planning they share is what makes the
# ``request_key`` identical whether a call was reached directly or through the chain. Splitting
# them would put the same planning and the same recording in two modules and let the two drift.
# The duplication against ``docflow.ocr.entrypoints`` is the processor-sibling duplication
# ``README.md`` §7 requires: no processor imports another processor's internals.
"""Entry points of the LLM processor.

Three shapes of one workflow:

* :func:`process_llm_request` — one inference: render, key, call, parse, validate, and retry while
  the failure is retryable. A request carrying a ``graph`` descriptor runs the chain instead, so a
  caller has one entry point for either shape;
* :func:`process_llm_node` — one node of the chain, reported through the shared stage vocabulary
  and recorded into the graph state;
* :func:`execute_llm_graph` — the fixed linear chain, node by node, reusing what a previous run
  already paid for and consolidating the nodes into one result.

Nothing here decides anything documental: which document to process, whether OCR runs, which
source wins and whether the LLM stage runs at all belong to the orchestrator, and this processor
reaches no other processor to ask.

**Where the run directory comes from.** ``LLMInput`` carries no output directory, so
``metadata["output_dir"]`` names the ``llm/`` namespace and a run that is not given one writes
nothing — it does not write to a guessed place. The asset root is stated the same way, in
``metadata["assets_dir"]``, and with no default either.

**One provider call per inference.** A run calls the provider to generate and for nothing else:
the two inventory primitives (:func:`docflow.llm.primitives.get_model_info` and
:func:`docflow.llm.primitives.get_context_window`) are implemented and reachable through
:func:`model_query_for`, but a run does not probe them, because a probe that failed would have to
be either swallowed or turned into a failure of a call that could have succeeded.

# TODO: [MVP] the per-node artifact tree, ``claim_node`` and multi-worker claims, parallel
# branches, per-node ``SKIP`` / ``FORCE`` / ``INVALIDATE``, ``request_graph_stop``,
# ``resume_llm_graph``, ``invalidate_downstream_nodes`` and ``calculate_consensus``. Each is named
# where it would have gone, and none of them is stubbed.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path
from time import perf_counter
from typing import Any, Final

from docflow.llm import primitives
from docflow.llm.contracts import (
    LLMAttempt,
    LLMError,
    LLMGraphState,
    LLMInput,
    LLMNodeResult,
    LLMResult,
    Timing,
    Usage,
)
from docflow.llm.primitives import (
    API_KEY_OPTION,
    ModelQuery,
    ProviderCall,
    build_inference_plan,
)
from docflow.states import StageState

#: Name recorded as ``processor`` in the run's metadata.
PROCESSOR_NAME: Final[str] = "llm"

#: Version recorded as ``processor_version`` in the run's metadata. A test asserts it matches
#: ``pyproject.toml``: the provenance a result carries has to name the code that produced it.
PROCESSOR_VERSION: Final[str] = "0.0.0"

#: Option keys this processor consumes itself; everything else in ``options`` is passed through to
#: the provider as a decoding option.
CONTROL_OPTIONS: Final[frozenset[str]] = frozenset(
    {
        API_KEY_OPTION,
        "base_url",
        "timeout",
        "max_attempts",
        "context_window",
        "max_prompt_tokens",
    }
)

#: A run that was never asked to persist anything records this in its metadata, so "no files"
#: reads as a decision rather than as a missing record.
NOT_PERSISTED: Final[str] = "not-requested"


@dataclass(frozen=True)
class PlannedCall:
    """Everything one inference needs, computed once and before any provider call.

    Planning is deliberately separable: it is what the chain uses to decide whether a node has to
    run at all, and doing it without calling the provider is what makes that decision free.

    Attributes:
        node_id: The node this call belongs to, or ``None`` for a single call.
        request_key: The identity of the logical request.
        provider_call: The provider-neutral call description.
        schema: The loaded schema, or ``None``.
        attempt_limit: How many attempts the policy allows.
        metadata: What was measured while planning, for the result's metadata.
    """

    node_id: str | None
    request_key: str
    provider_call: ProviderCall
    schema: dict[str, Any] | None
    attempt_limit: int
    metadata: dict[str, Any] = field(default_factory=dict)


def _mint_run_id() -> str:
    """Return a fresh run identity.

    Minted only when the caller pinned none. A run that may be resumed pins its identity in
    ``metadata["run_id"]``; a run that may not, does not have to.
    """
    return f"llm-run-{uuid.uuid4().hex[:12]}"


def _provider_options(request: LLMInput) -> dict[str, Any]:
    """Return the decoding options to pass through to the provider, our own keys removed."""
    return {
        key: value
        for key, value in request.options.items()
        if key not in CONTROL_OPTIONS
    }


def _plan_call(request: LLMInput, node_id: str | None) -> PlannedCall:
    """Render, measure and key one inference, without reaching a provider.

    Args:
        request: The request to plan.
        node_id: The node it belongs to, or ``None``.

    Returns:
        The plan.

    Raises:
        LLMPrimitiveError: With the typed failure the planning stage produced — a missing asset, a
            placeholder the request cannot fill, a schema this processor cannot enforce, a context
            overflow, or a dependency that does not resolve.
    """
    primitives.validate_llm_input(request)
    assets_dir = primitives.assets_dir_for(request)
    template = primitives.load_template(request.template, assets_dir)
    schema = primitives.load_schema(request.schema, assets_dir)
    prompt = primitives.process_prompt(request, template, schema)
    window = primitives.stated_context_window(request)
    if primitives.is_context_limit_exceeded(prompt.tokens, window):
        raise primitives.typed_failure(
            "CONTEXT_OVERFLOW",
            f"the prompt needs about {prompt.tokens} tokens and the stated window is {window}",
            recoverable=False,
            metadata={"prompt_tokens": prompt.tokens, "context_window": window},
        )
    hashes = primitives.input_hashes(
        request.document, [Path(image) for image in request.images]
    )
    model_version = primitives.stated_model_version(request)
    options = primitives.normalize_llm_options(request.options)
    request_key = primitives.calculate_request_key(
        provider=request.provider,
        model=request.model,
        model_version=model_version,
        rendered_prompt=prompt.text,
        hashes=hashes,
        schema_hash=primitives.schema_digest(schema),
        options=options,
    )
    messages = primitives.build_messages(prompt.text)
    return PlannedCall(
        node_id=node_id,
        request_key=request_key,
        provider_call=ProviderCall(
            provider=request.provider,
            base_url=request.options.get("base_url"),
            api_key=request.options.get(API_KEY_OPTION),
            model=request.model,
            messages=messages,
            images=list(request.images),
            options=_provider_options(request),
            schema=schema,
            timeout=primitives.request_timeout(request.options),
        ),
        schema=schema,
        attempt_limit=primitives.max_attempts(request.options),
        metadata={
            "request_key": request_key,
            "model_version": model_version,
            "context_window": window,
            "prompt_tokens": prompt.tokens,
            "prompt_tokens_estimated": prompt.estimated,
            "prompt_truncated": prompt.truncated,
            "attempt_limit": primitives.max_attempts(request.options),
            "provider_timeout": primitives.request_timeout(request.options),
            "base_url": request.options.get("base_url"),
            "normalized_options": options,
        },
    )


@dataclass(frozen=True)
class _Answer:
    """What one provider attempt produced: an answer, or the typed failure that ended it.

    Attributes:
        raw_response: The answer text, or ``None`` when the attempt ended before one arrived.
        parsed_response: The parsed answer, or ``None``.
        usage: The provider's token figures, or an unmeasured record.
        timing: The durations the provider reported, in seconds.
        finish_reason: Why generation stopped, or ``None``.
        error: The typed failure, or ``None`` when the attempt succeeded.
    """

    raw_response: str | None
    parsed_response: Any
    usage: Usage
    timing: dict[str, float]
    finish_reason: str | None
    error: LLMError | None


def _call_provider(call: ProviderCall, planned: PlannedCall) -> _Answer:
    """Resolve the provider primitive, call it, and read what it answered.

    The primitive is resolved through the *module* at call time: that is the frozen injection
    point, so a double installed there is the one that answers. Binding the name at import time
    would make the patch a no-op and the suite would reach a real provider.

    Args:
        call: The provider-neutral call description.
        planned: The plan, read for its schema and its resolved generator.

    Returns:
        The answer, or the typed failure that ended the attempt. Nothing is raised: an attempt is
        evidence, and evidence is not thrown away. An answer that violates the schema is kept
        *with* the violation, because it is the thing the violation is about.
    """
    try:
        generator = getattr(
            primitives,
            primitives.resolve_generator(
                structured=planned.schema is not None, multimodal=bool(call.images)
            ),
        )
        body = generator(call)
        response = primitives.translate_provider_response(call.provider, body)
        parsed = primitives.parse_json_response(response.text)
        violations = (
            primitives.validate_schema(parsed, planned.schema)
            if planned.schema is not None
            else []
        )
    except primitives.LLMPrimitiveError as failure:
        return _Answer(None, None, _empty_usage(), {}, None, failure.error)
    except Exception as unclassified:  # pylint: disable=broad-exception-caught
        # Reason: the seam classifies everything it can, so an exception that arrives here is a
        # defect of this processor rather than a provider signal. It is typed and recorded instead
        # of escaping, because a node failure must never corrupt the chain state — and a defect
        # that is typed is a defect that can be reported.
        return _Answer(
            None,
            None,
            _empty_usage(),
            {},
            None,
            primitives.typed_failure(
                "INTERNAL_ERROR",
                "the provider seam raised something it did not classify",
                recoverable=False,
                metadata={"error": str(unclassified)},
            ).error,
        )
    answer = _Answer(
        raw_response=response.text,
        parsed_response=parsed,
        usage=primitives.usage_of(call.provider, response.usage),
        timing=dict(response.timing),
        finish_reason=response.finish_reason,
        error=None,
    )
    if not violations:
        return answer
    return replace(
        answer,
        error=primitives.typed_failure(
            "SCHEMA_ERROR",
            "the answer does not satisfy the schema",
            metadata={"violations": violations},
        ).error,
    )


def _run_attempt(planned: PlannedCall, attempt_index: int) -> LLMAttempt:
    """Make one provider attempt and keep whatever happened.

    Args:
        planned: The plan this attempt belongs to.
        attempt_index: The attempt's 1-based index.

    Returns:
        The attempt record, carrying the typed error when the attempt failed.
    """
    call = planned.provider_call
    started = perf_counter()
    answer = _call_provider(call, planned)
    elapsed = perf_counter() - started
    return LLMAttempt(
        attempt_id=primitives.mint_attempt_id(planned.node_id, attempt_index),
        node_id=planned.node_id,
        request_key=planned.request_key,
        provider=call.provider,
        model=call.model,
        request_metadata={
            "messages": len(call.messages),
            "images": len(call.images),
            "schema": planned.schema is not None,
            "prompt_tokens": planned.metadata["prompt_tokens"],
            "finish_reason": answer.finish_reason,
        },
        raw_response=answer.raw_response,
        parsed_response=answer.parsed_response,
        validation=primitives.attempt_validation_state(answer.error),
        usage=answer.usage,
        timing=Timing(
            queue_time=None,
            load_time=answer.timing.get("load_time"),
            inference_time=answer.timing.get("inference_time"),
            total_time=elapsed,
        ),
        error=answer.error,
        status="success" if answer.error is None else "failed",
    )


def retry_llm_request(planned: PlannedCall) -> list[LLMAttempt]:
    """Call the provider until it answers validly or the policy's attempts run out.

    Every attempt is kept, in order: a retry that discarded its predecessor would hide what the
    provider actually answered, and the prior attempts are what makes a failure diagnosable.

    Args:
        planned: The plan to execute.

    Returns:
        The attempts, at least one. The last one is the outcome: it carries no error when the call
        succeeded.
    """
    attempts: list[LLMAttempt] = []
    index = 1
    while True:
        attempt = _run_attempt(planned, index)
        attempts.append(attempt)
        if attempt.error is None:
            break
        if not primitives.should_retry(
            retryable=primitives.is_retryable(attempt.error),
            attempt_index=index,
            attempt_limit=planned.attempt_limit,
        ):
            break
        index = primitives.increment_attempt(index)
    return attempts


def _empty_usage() -> Usage:
    """Return a usage record in which nothing was measured."""
    return Usage(
        input_tokens=None,
        output_tokens=None,
        total_tokens=None,
        cached_tokens=None,
        provider_usage={},
        estimated_cost=None,
    )


def _failed_result(
    request: LLMInput,
    run_id: str,
    error: LLMError,
    *,
    graph_id: str | None = None,
    elapsed: float = 0.0,
) -> LLMResult:
    """Return the result of a run that failed before it produced an answer.

    Every product field is ``None`` or empty and the typed failure explains why: a run that never
    reached a provider has no raw response, no parsed response and no usage, and a zero or an empty
    string would read as something that was measured.

    Args:
        request: The request that failed.
        run_id: The run's identity.
        error: The typed failure that ended the run.
        graph_id: The graph, when the run was a chain.
        elapsed: How long the run took before failing.

    Returns:
        The failed result.
    """
    return LLMResult(
        run_id=run_id,
        task=request.task,
        provider=request.provider,
        model=request.model,
        graph_id=graph_id,
        node_results={},
        raw_response=None,
        parsed_response=None,
        schema_valid=False,
        validation_errors=[error.message],
        errors=[error],
        attempts=[],
        comparisons={},
        usage=_empty_usage(),
        timing=Timing(
            queue_time=None, load_time=None, inference_time=None, total_time=elapsed
        ),
        status=StageState.FAILED,
        metadata={
            "processor": PROCESSOR_NAME,
            "processor_version": PROCESSOR_VERSION,
            "document_id": request.metadata.get("document_id"),
            "workflow_run_id": request.metadata.get("workflow_run_id"),
            "persisted": NOT_PERSISTED,
        },
    )


def _result_metadata(
    request: LLMInput, planned: PlannedCall, *, persisted: str
) -> dict[str, Any]:
    """Return a single call's metadata: what it was for, what was measured, what was written."""
    return {
        "processor": PROCESSOR_NAME,
        "processor_version": PROCESSOR_VERSION,
        "document_id": request.metadata.get("document_id"),
        "workflow_run_id": request.metadata.get("workflow_run_id"),
        "persisted": persisted,
        **planned.metadata,
    }


def _publish_result(output_dir: Path | None, result: LLMResult) -> LLMError | None:
    """Persist ``final_result.json`` when a namespace was requested.

    Args:
        output_dir: The run's ``llm/`` namespace, or ``None`` when nothing was requested.
        result: The result to record.

    Returns:
        The typed failure when the record could not be written, else ``None``. A run never claims a
        success whose record is missing from disk.
    """
    if output_dir is None:
        return None
    try:
        primitives.save_result(output_dir, result)
    except primitives.LLMPrimitiveError as failure:
        return failure.error
    return None


def process_llm_request(request: LLMInput) -> LLMResult:
    """Execute one LLM/VLM inference, or the inference chain when the request declares one.

    Args:
        request: The inference to perform, its provider and model, its template and the schema the
            response is validated against. A request carrying a ``graph`` descriptor runs the fixed
            linear chain instead of one call.

    Returns:
        The result, carrying every attempt made, the validation outcome and the token accounting.
        On the happy path ``status`` is ``SUCCESS`` and ``schema_valid`` is ``True``. A failure of
        any kind is reported as a typed :class:`~docflow.llm.contracts.LLMError` inside the result
        and is never raised across the contract.
    """
    if request.graph is not None:
        return execute_llm_graph(request)
    return _single_call(request)


def _single_call(request: LLMInput) -> LLMResult:
    """Execute one inference, with retries, and persist its result when asked to."""
    started = perf_counter()
    run_id = primitives.pinned_run_id(request) or _mint_run_id()
    output_dir = primitives.output_dir_for(request)
    try:
        planned = _plan_call(request, None)
    except primitives.LLMPrimitiveError as failure:
        return _failed_result(
            request, run_id, failure.error, elapsed=perf_counter() - started
        )

    attempts = retry_llm_request(planned)
    last = attempts[-1]
    errors = [] if last.error is None else [last.error]
    violations = (
        list(last.error.metadata.get("violations", []))
        if last.error is not None and last.error.type == "SCHEMA_ERROR"
        else []
    )
    result = LLMResult(
        run_id=run_id,
        task=request.task,
        provider=request.provider,
        model=request.model,
        graph_id=None,
        node_results={},
        raw_response=last.raw_response,
        parsed_response=last.parsed_response,
        schema_valid=last.error is None,
        validation_errors=violations
        if violations
        else [error.message for error in errors],
        errors=errors,
        attempts=attempts,
        comparisons={},
        usage=primitives.merge_usage(attempt.usage for attempt in attempts),
        timing=primitives.merge_timing(attempt.timing for attempt in attempts),
        status=StageState.SUCCESS if last.error is None else StageState.FAILED,
        metadata=_result_metadata(
            request,
            planned,
            persisted=NOT_PERSISTED if output_dir is None else str(output_dir),
        ),
    )

    publication = _publish_result(output_dir, result)
    if publication is not None:
        # The failure is recorded in ``errors`` and nowhere else: ``validation_errors`` is the
        # *schema* verdict, and the answer did satisfy the schema.
        result.errors.append(publication)
        result.status = StageState.FAILED
    primitives.validate_llm_result(result)
    return result


def _node_request(node_config: dict[str, Any], state: LLMGraphState) -> LLMInput:
    """Return the request one node runs, with its dependencies' results injected.

    A node consumes what it declared in ``depends_on``, under ``extra_context["node_results"]``,
    which is what an ``<extra>`` placeholder renders. The injection is deterministic — the same
    upstream results produce the same prompt — which is what lets a resumed run recompute the same
    ``request_key`` and reuse the node instead of paying for it again.

    Args:
        node_config: The node's definition and the graph's own request.
        state: The chain state the dependencies are read from.

    Returns:
        The node's request. It carries no ``output_dir``: per-node artifacts are deferred, so a
        node writes nothing and the run's two files stay the run's.
    """
    base: LLMInput = node_config["request"]
    results = {
        node_id: state.node_results[node_id].result
        for node_id in node_config.get("depends_on", [])
        if node_id in state.node_results
    }
    metadata = {
        key: value
        for key, value in base.metadata.items()
        if key != primitives.OUTPUT_DIR_KEY
    }
    return LLMInput(
        task=node_config.get("task") or base.task,
        provider=base.provider,
        model=base.model,
        template=node_config["template"],
        document=base.document,
        images=list(base.images),
        extra_context={**base.extra_context, "node_results": results},
        schema=node_config.get("schema"),
        options=dict(base.options),
        graph=None,
        metadata=metadata,
    )


def process_llm_node(
    node_config: dict[str, Any],
    state: LLMGraphState,
) -> LLMNodeResult:
    """Execute one node of the inference graph and record it into the chain state.

    The node moves through the shared vocabulary — ``READY`` once its dependencies are resolved,
    ``RUNNING`` while the provider is answering, then ``SUCCESS`` or ``FAILED`` — and a failure is
    reported as a typed failed result, never as an exception that would leave the state corrupt.

    Args:
        node_config: The node's definition — its ``node_id``, ``task``, ``template``, ``schema``,
            ``depends_on`` — and the graph's own ``request``.
        state: The graph state to read the node's dependencies from and record the node's outcome
            into.

    Returns:
        The node result. Its ``request_key`` is the one the call recorded; a node that failed
        before a key could be computed carries an empty key, which is exactly why
        :func:`docflow.llm.primitives.validate_cached_result` refuses to reuse it.
    """
    node_id = str(node_config["node_id"])
    request = _node_request(node_config, state)
    state.node_states[node_id] = StageState.READY
    state.node_states[node_id] = StageState.RUNNING
    state.current_nodes = [node_id]
    try:
        planned = _plan_call(request, node_id)
    except primitives.LLMPrimitiveError as failure:
        state.current_nodes = []
        return _record_node(state, node_id, "", failure.error)
    result = _single_call(request)
    state.current_nodes = []
    if result.status == StageState.FAILED:
        return _record_node(
            state, node_id, result.metadata["request_key"], result.errors[0]
        )
    return _record_node(state, node_id, planned.request_key, None, result)


def _record_node(
    state: LLMGraphState,
    node_id: str,
    request_key: str,
    error: LLMError | None,
    result: LLMResult | None = None,
) -> LLMNodeResult:
    """Record one node's outcome in the chain state and return it as a node result.

    Args:
        state: The chain state to record into.
        node_id: The node being recorded.
        request_key: The key the node ran under, or ``""`` when none could be computed.
        error: The failure that ended the node, or ``None``.
        result: The run's result, when the node produced one.

    Returns:
        The node result, already stored in ``state.node_results``.
    """
    attempts = [] if result is None else list(result.attempts)
    node_result = LLMNodeResult(
        node_id=node_id,
        request_key=request_key,
        status=StageState.SUCCESS if error is None else StageState.FAILED,
        result=None if result is None else result.parsed_response,
        attempts=attempts,
        validation=primitives.attempt_validation_record(
            primitives.attempt_validation_state(error), retryable=False
        ),
        errors=[] if error is None else [error],
        usage=_empty_usage() if result is None else result.usage,
        timing=(
            Timing(queue_time=None, load_time=None, inference_time=None, total_time=0.0)
            if result is None
            else result.timing
        ),
        metadata={} if result is None else dict(result.metadata),
    )
    state.node_states[node_id] = node_result.status
    state.node_results[node_id] = node_result
    state.attempts[node_id] = attempts
    if error is not None:
        state.errors.append(error.message)
    return node_result


def _new_state(run_id: str, plan: Any) -> LLMGraphState:
    """Return a chain state that has not started, with every declared node pending."""
    return LLMGraphState(
        run_id=run_id,
        graph_id=plan.graph_id,
        graph_version=plan.graph_version,
        status=StageState.RUNNING,
        current_nodes=[],
        node_states={node.node_id: StageState.NOT_STARTED for node in plan.nodes},
        node_results={},
        attempts={},
        comparisons={},
        errors=[],
        usage=_empty_usage(),
        stop_requested=False,
        final_result=None,
    )


def _comparisons_for(plan: Any, state: LLMGraphState) -> dict[str, Any]:
    """Return the per-field comparisons the chain's declared dependencies imply.

    A node that declared two or more dependencies is a node whose inputs have to be compared, so
    the pairs are read from the descriptor rather than from a hardcoded list of node names. Each
    pair is compared in the order the node declared it, and disagreement is reported as data.

    Args:
        plan: The compiled inference plan.
        state: The chain state whose node results are compared.

    Returns:
        The comparisons by identifier, and nothing when no node declared two dependencies.
    """
    comparisons: dict[str, Any] = {}
    for node in plan.nodes:
        for left, right in zip(node.depends_on, node.depends_on[1:], strict=False):
            if left not in state.node_results or right not in state.node_results:
                continue
            comparisons[f"{node.node_id}:{left}~{right}"] = primitives.compare_outputs(
                state.node_results[left].result,
                state.node_results[right].result,
                left_node=left,
                right_node=right,
            )
    return comparisons


def execute_llm_graph(request: LLMInput) -> LLMResult:
    """Run the request's inference chain, reusing the nodes it may and consolidating the rest.

    The chain runs in the order the descriptor declares, which is the order that satisfies every
    ``depends_on``. A node a previous run already answered validly, under the same
    ``request_key``, is marked ``REUSED`` and the provider is not called for it; everything else
    is executed. When a node fails, the nodes that depend on it are not run — their inputs do not
    exist — and the run is reported as failed, with the chain state persisted so a later call can
    resume it.

    Args:
        request: The request, carrying the graph descriptor in ``graph`` and the run's namespace in
            ``metadata["output_dir"]``.

    Returns:
        The consolidated result: one node result per node that ran or was reused, the run's
        per-field comparisons, and the last node's answer as the run's answer.
    """
    started = perf_counter()
    run_id = primitives.pinned_run_id(request) or _mint_run_id()
    output_dir = primitives.output_dir_for(request)
    try:
        plan = build_inference_plan(request.graph)
        state = _resumed_state(output_dir, run_id, plan)
    except primitives.LLMPrimitiveError as failure:
        return _failed_result(
            request, run_id, failure.error, elapsed=perf_counter() - started
        )

    node_actions: dict[str, str] = {}
    for node in plan.nodes:
        node_config = {
            "node_id": node.node_id,
            "depends_on": list(node.depends_on),
            "task": node.task,
            "template": node.template,
            "schema": node.schema,
            "request": request,
        }
        action, node_result = _resolve_node(node_config, state)
        node_actions[node.node_id] = action
        if node_result.status == StageState.FAILED:
            break

    state.comparisons = _comparisons_for(plan, state)
    state.usage = primitives.merge_usage(
        node_result.usage for node_result in state.node_results.values()
    )
    result = _consolidate(request, plan, state, run_id, node_actions, started)
    state.final_result = result
    state.status = result.status
    _persist_graph(output_dir, state, result)
    primitives.validate_llm_result(result)
    return result


def _resumed_state(output_dir: Path | None, run_id: str, plan: Any) -> LLMGraphState:
    """Return the chain state to continue: the saved one when it belongs to this graph, else new.

    Args:
        output_dir: The run's namespace, or ``None`` when nothing is persisted.
        run_id: The run's identity.
        plan: The compiled plan.

    Returns:
        The state. A saved state for a *different* graph is not resumed: it describes something
        else, and continuing it would reuse results that answered another question.

    Raises:
        LLMPrimitiveError: With ``DEPENDENCY_ERROR`` when the saved state belongs to another graph.
    """
    if output_dir is None:
        return _new_state(run_id, plan)
    saved = primitives.load_graph_state(output_dir)
    if saved is None:
        return _new_state(run_id, plan)
    if saved.graph_id != plan.graph_id or saved.graph_version != plan.graph_version:
        raise primitives.typed_failure(
            "DEPENDENCY_ERROR",
            "the saved chain state belongs to another graph",
            recoverable=False,
            metadata={
                "saved": [saved.graph_id, saved.graph_version],
                "requested": [plan.graph_id, plan.graph_version],
                "output_dir": str(output_dir),
            },
        )
    for node_id in plan.node_ids:
        saved.node_states.setdefault(node_id, StageState.NOT_STARTED)
    saved.run_id = run_id
    saved.status = StageState.RUNNING
    saved.current_nodes = []
    return saved


def _resolve_node(
    node_config: dict[str, Any], state: LLMGraphState
) -> tuple[str, LLMNodeResult]:
    """Return ``(action, node_result)`` for one node: reuse it, or execute it.

    Args:
        node_config: The node's definition and the graph's request.
        state: The chain state.

    Returns:
        ``("REUSE", result)`` when a valid result under the same key already exists, and
        ``("EXECUTE", result)`` otherwise.
    """
    node_id = str(node_config["node_id"])
    try:
        planned = _plan_call(_node_request(node_config, state), node_id)
    except primitives.LLMPrimitiveError:
        # The node cannot even be planned, so there is no key to look a reuse up under; executing
        # it is what turns that into a typed FAILED node result.
        return "EXECUTE", process_llm_node(node_config, state)

    reusable = primitives.find_reusable_node_result(state, node_id, planned.request_key)
    if reusable is not None:
        state.node_states[node_id] = StageState.REUSED
        return "REUSE", reusable
    return "EXECUTE", process_llm_node(node_config, state)


def _consolidate(
    request: LLMInput,
    plan: Any,
    state: LLMGraphState,
    run_id: str,
    node_actions: dict[str, str],
    started: float,
) -> LLMResult:
    """Return the chain's result, consolidated from its nodes."""
    final = state.node_results.get(plan.nodes[-1].node_id)
    failed = [
        node_result
        for node_result in state.node_results.values()
        if node_result.status == StageState.FAILED
    ]
    errors = [error for node_result in failed for error in node_result.errors]
    raw_response = None
    if final is not None and final.attempts:
        raw_response = final.attempts[-1].raw_response
    return LLMResult(
        run_id=run_id,
        task=request.task,
        provider=request.provider,
        model=request.model,
        graph_id=plan.graph_id,
        node_results=dict(state.node_results),
        raw_response=raw_response,
        parsed_response=None if final is None else final.result,
        schema_valid=not failed,
        validation_errors=[error.message for error in errors],
        errors=errors,
        attempts=[
            attempt
            for node_result in state.node_results.values()
            for attempt in node_result.attempts
        ],
        comparisons=dict(state.comparisons),
        usage=state.usage,
        timing=primitives.merge_timing(
            [node_result.timing for node_result in state.node_results.values()]
            + [
                Timing(
                    queue_time=None,
                    load_time=None,
                    inference_time=None,
                    total_time=perf_counter() - started,
                )
            ]
        ),
        status=StageState.SUCCESS if not failed else StageState.FAILED,
        metadata={
            "processor": PROCESSOR_NAME,
            "processor_version": PROCESSOR_VERSION,
            "document_id": request.metadata.get("document_id"),
            "workflow_run_id": request.metadata.get("workflow_run_id"),
            "graph_id": plan.graph_id,
            "graph_version": plan.graph_version,
            "node_actions": dict(node_actions),
            "attempt_limit": primitives.max_attempts(request.options),
            "persisted": (
                NOT_PERSISTED
                if primitives.output_dir_for(request) is None
                else str(primitives.output_dir_for(request))
            ),
        },
    )


def _persist_graph(
    output_dir: Path | None, state: LLMGraphState, result: LLMResult
) -> None:
    """Persist the chain state and the run's result, when a namespace was requested.

    A failure to record the run is reported in the result rather than raised: the answer exists,
    but the run must not claim a success whose record is missing from disk.

    Args:
        output_dir: The run's namespace, or ``None``.
        state: The chain state to save.
        result: The consolidated result, updated in place when its record cannot be written.
    """
    if output_dir is None:
        return
    try:
        primitives.save_graph_state(output_dir, state)
        primitives.save_result(output_dir, result)
    except primitives.LLMPrimitiveError as failure:
        result.errors.append(failure.error)
        result.status = StageState.FAILED
        state.status = StageState.FAILED


def model_query_for(request: LLMInput) -> ModelQuery:
    """Return the model query a caller needs to probe the inventory primitives.

    It is what makes :func:`docflow.llm.primitives.get_model_info` and
    :func:`docflow.llm.primitives.get_context_window` reachable without the caller importing the
    provider seam: the request already names the provider, the model and the endpoint, and this
    turns them into the question.
    """
    return ModelQuery(
        provider=request.provider,
        model=request.model,
        base_url=request.options.get("base_url"),
        api_key=request.options.get(API_KEY_OPTION),
        timeout=primitives.request_timeout(request.options),
    )
