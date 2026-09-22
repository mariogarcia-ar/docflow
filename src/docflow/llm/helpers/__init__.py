"""LLM helpers: composition glue of the processor's own stages.

Helpers sequence the render → call → parse → validate steps, build the graph's node
payloads and assemble results; they never reach a provider and never decide anything
belonging to the orchestrator. Phase 1 populates this package as the entry points are
composed.
"""
