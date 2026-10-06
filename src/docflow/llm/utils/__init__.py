"""LLM utilities: engine-independent helpers shared inside the processor.

Nothing here reaches a provider directly — a utility that needs one calls the matching
:mod:`docflow.llm.primitives` function. Template rendering, prompt building, request-key
calculation and token counting live here. Phase 1 populates this package as the
primitives land.
"""
