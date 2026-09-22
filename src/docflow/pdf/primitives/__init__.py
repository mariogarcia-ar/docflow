"""Low-level PDF primitives — the only place that knows Poppler.

Every engine symbol of the PDF processor lives in this package: ``pdftotext``,
``pdfimages`` and ``pdfseparate`` are reached from here and from nowhere else. Neither
the orchestrator nor another processor may import this package; both go through
:func:`docflow.pdf.process_pdf` / :func:`docflow.pdf.process_pdf_page`.

Phase 0 creates the package. Phase 1 fills it in:

* ``PDF-02`` — the engine seam: a named engine (never a silent fallback), its version
  surfaced for ``metadata.json``, and a typed failure path when the binary is absent.
* ``PDF-03`` … ``PDF-08`` — document inspection, split/extract, render, native text,
  embedded images, composition and classification.
"""
