"""Image helpers: composition glue of the processor's own stages.

Helpers sequence primitives and utilities; they never reach an engine and never decide
whether a later stage should use the OCR or the VLM variant. Phase 1 populates this
package as the entry point is composed.
"""
