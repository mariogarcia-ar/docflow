"""Low-level provider primitives — the only place that knows a provider SDK.

Every provider symbol of the LLM processor lives in this package: the HTTP calls to an
Ollama daemon, a vLLM server or a hosted API are reached from here and from nowhere else.
Neither the orchestrator nor another processor may import this package; both go through
:func:`docflow.llm.process_llm_request`.

Phase 0 creates the package. Phase 1 fills it in:

* ``LLM-02`` — the provider seam and its result/error types.
* ``LLM-09`` — ``generate_text``, ``generate_multimodal``, ``generate_structured``,
  ``list_models``, ``check_model_available``, ``get_context_window``, plus the in-memory
  fake provider of ``LLM-03``.
"""
