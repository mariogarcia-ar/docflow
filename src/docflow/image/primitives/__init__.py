"""Low-level image primitives — the only place that knows OpenCV (or Pillow).

Every engine symbol of the image processor lives in this package. Neither the
orchestrator nor another processor may import it; both go through
:func:`docflow.image.process_image`.

Phase 0 creates the package. Phase 1 fills it in:

* ``IMG-02`` — the engine seam: OpenCV as the explicit named engine, Pillow as the
  documented drop-in alternative, engine and library versions surfaced for
  ``metadata.json``, and a typed failure path when the engine is unavailable. The
  alternative is never activated implicitly.
* ``IMG-03`` … ``IMG-05`` — load/store, analysis and transformation primitives.
"""
