"""PDF utilities: engine-independent helpers shared inside the processor.

Nothing here reaches an engine directly — a utility that needs Poppler calls the matching
:mod:`docflow.pdf.primitives` function. Phase 1 populates this package as the primitives
land.
"""
