"""LLM processor: ``LLMInput → LLMResult``.

Prepares, executes, validates and persists one LLM/VLM inference, either as a single call
or as an internal inference graph (``classify → extract_a/extract_b → compare → validate
→ consolidate``).

Providers: Ollama, vLLM or a hosted API, reached only from :mod:`docflow.llm.primitives`.
One provider per call, named explicitly and never silently substituted. The processor
imports no other processor.

Entry points: :func:`process_llm_request` for one call and :func:`process_llm_node` for
one node of the graph.

The inference graph's ``LLMGraphState`` lives inside this processor. It never replaces the
orchestrator's ``DocumentContext`` / ``PageContext`` / ``StageExecution``, and the two
levels of retry — node-level here, whole-processor in the orchestrator — never mix. The
node *states*, however, are the shared vocabulary of :mod:`docflow.states`: the two levels
are distinct, but they do not speak two different languages.

Symbols are re-exported here, but only :mod:`docflow.llm.primitives` may import them.
"""

from __future__ import annotations

from docflow.llm.contracts import (
    ComparisonResult,
    LLMAttempt,
    LLMGraphState,
    LLMInput,
    LLMNodeResult,
    LLMNodeState,
    LLMResult,
    LLMStatus,
    LLMValidationState,
    Timing,
    Usage,
)
from docflow.llm.entrypoints import process_llm_node, process_llm_request

__all__ = [
    "ComparisonResult",
    "LLMAttempt",
    "LLMGraphState",
    "LLMInput",
    "LLMNodeResult",
    "LLMNodeState",
    "LLMResult",
    "LLMStatus",
    "LLMValidationState",
    "Timing",
    "Usage",
    "process_llm_node",
    "process_llm_request",
]
