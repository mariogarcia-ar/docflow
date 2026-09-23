"""Low-level OCR primitives - the only place that knows Docling.

Docling is the single OCR engine of this project: it is never a user-selectable option and it is
never silently substituted. Neither the orchestrator nor another processor may import this
package; both go through :func:`docflow.ocr.process_ocr_image`.

``OCR-02`` created the seam (:mod:`~docflow.ocr.primitives.engine`) and declared the signatures
the later tasks fill in. Each module below is a group from ``subplan-procesador-ocr.md`` §3.4, so
the surface can be checked against the plan without translating between two taxonomies:

* :mod:`~docflow.ocr.primitives.pipeline` - ``OCR-03``. Building and configuring a converter.
* :mod:`~docflow.ocr.primitives.execution` - ``OCR-04``. Running the engine and reading its
  result.
* :mod:`~docflow.ocr.primitives.layout` - ``OCR-05``. Geometry and reading order.
* :mod:`~docflow.ocr.primitives.text` - ``OCR-05`` / ``OCR-08``. Measuring and canonicalizing.
* :mod:`~docflow.ocr.primitives.rendering` - ``OCR-06`` / ``OCR-07``. Markdown and tables.
* :mod:`~docflow.ocr.primitives.persistence` - ``OCR-09`` / ``OCR-10``. Validation and writes.
* :mod:`~docflow.ocr.primitives.metadata` - ``OCR-10``. The provenance record.

Nothing here is functional yet; every declared body raises :class:`NotImplementedError`, which is
the honest place for a skeleton to stop. A stub returning a plausible zero would put a
measured-looking ``0`` into :class:`~docflow.ocr.contracts.OCRMetrics` and let a caller mistake
"not implemented" for "this page has no text" - the silent stand-in the project forbids.
"""

from __future__ import annotations

from docflow.ocr.primitives import (
    engine,
    execution,
    export,
    extraction,
    layout,
    metadata,
    persistence,
    pipeline,
    rendering,
    text,
)

__all__ = [
    "engine",
    "execution",
    "export",
    "extraction",
    "layout",
    "metadata",
    "persistence",
    "pipeline",
    "rendering",
    "text",
]
