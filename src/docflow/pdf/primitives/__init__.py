"""Low-level PDF primitives — the only place that knows Poppler.

Every engine symbol of the PDF processor lives in this package: ``pdfinfo``,
``pdftotext``, ``pdfimages``, ``pdfseparate``, ``pdftoppm`` and ``pdfunite`` are reached
from here and from nowhere else. Neither the orchestrator nor another processor may import
this package; both go through :func:`docflow.pdf.process_pdf` /
:func:`docflow.pdf.process_pdf_page`.

The engine dependency is funnelled through one module,
:mod:`~docflow.pdf.primitives.engine`, so swapping Poppler means editing that module and
nothing else. Each remaining module holds one capability, filled in by its own task:

* :mod:`~docflow.pdf.primitives.engine` — ``PDF-02``: the named engine, its version, and
  the single place a Poppler process is spawned.
* :mod:`~docflow.pdf.primitives.document` — ``PDF-03``: metadata, page count, page size.
* :mod:`~docflow.pdf.primitives.split` — ``PDF-04``: one self-contained PDF per page.
* :mod:`~docflow.pdf.primitives.render` — ``PDF-05``: a page rendered to PNG.
* :mod:`~docflow.pdf.primitives.text` — ``PDF-06``: the native text layer and its blocks.
* :mod:`~docflow.pdf.primitives.images` — ``PDF-07``: images embedded in a page.
* :mod:`~docflow.pdf.primitives.composition` — ``PDF-08``: metrics and classification.
"""
