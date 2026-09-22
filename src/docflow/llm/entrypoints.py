"""Entry points of the LLM processor.

The signatures are frozen by ``docs/plan/README.md`` §4 (the idea's §"Naming"): ``llm``
exposes ``process_llm_request()`` and ``process_llm_node()``. Phase 0 ships the signatures
only; the bodies raise rather than returning a placeholder.

Phase 1 fills these in: ``LLM-06`` implements :func:`process_llm_request` and ``LLM-10``
implements :func:`process_llm_node`.
"""

from __future__ import annotations

from typing import Any

from docflow.llm.contracts import LLMGraphState, LLMInput, LLMNodeResult, LLMResult


def process_llm_request(request: LLMInput) -> LLMResult:
    """Execute one LLM/VLM inference: render, call, parse and validate.

    Args:
        request: The inference to perform, its provider and model, its template and the
            schema the response is validated against.

    Returns:
        The result, carrying every attempt made, the validation outcome and the token
        accounting.

    Raises:
        NotImplementedError: Phase 0 ships the signature only.

    # TODO: [MVP] chain template → prompt → request_key → messages → payload →
    # provider → parse → validate (LLM-06).
    """
    raise NotImplementedError("process_llm_request is implemented in Phase 1 by LLM-06")


def process_llm_node(
    node_config: dict[str, Any],
    state: LLMGraphState,
) -> LLMNodeResult:
    """Execute one node of the inference graph.

    Args:
        node_config: The node's definition — its task, template, schema and
            dependencies.
        state: The graph state to read the node's dependencies from and record the
            node's outcome into.

    Returns:
        The node result. A node failure is reported as a typed failed result, never as
        an exception that would corrupt the graph state.

    Raises:
        NotImplementedError: Phase 0 ships the signature only.

    # TODO: [MVP] claim the node, resolve its dependencies, delegate to
    # process_llm_request and record the transition (LLM-10).
    """
    raise NotImplementedError("process_llm_node is implemented in Phase 1 by LLM-10")
