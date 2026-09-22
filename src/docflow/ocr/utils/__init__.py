"""OCR utilities: engine-independent helpers shared inside the processor.

Nothing here reaches Docling directly — a utility that needs the engine calls the
matching :mod:`docflow.ocr.primitives` function. Deterministic ordering and bounding-box
normalization live here, so two runs over the same input produce identical output. Phase
1 populates this package as the primitives land.
"""
