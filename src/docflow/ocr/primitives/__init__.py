"""Low-level OCR primitives — the only place that knows Docling.

Docling is the single OCR engine of this project: it is never a user-selectable option
and it is never silently substituted. Neither the orchestrator nor another processor may
import this package; both go through :func:`docflow.ocr.process_ocr_image`.

Phase 0 creates the package. Phase 1 fills it in:

* ``OCR-02`` — the seam: the thin signatures, ``docling`` pinned in ``pyproject.toml``,
  and ``get_engine_version()`` feeding ``metadata.json``.
* ``OCR-03`` … ``OCR-05`` — pipeline configuration, execution and extraction
  (``convert_image_with_docling``, ``extract_docling_*``) and the deterministic
  normalization that produces the engine-independent
  :class:`~docflow.ocr.contracts.OCRDocument`.
"""
