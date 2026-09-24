"""The engine doubles, one per processor, and the shape check that keeps them honest.

The doubles themselves land with their own task — ``PDF-14`` (Poppler, injected at the
``subprocess.run`` call), ``IMG-15`` (OpenCV, injected at the ``image/primitives/``
functions), ``OCR-14`` (Docling, injected at ``convert_image_with_docling``) and ``LLM-03``
(the scripted provider fake) — each under the name its plan row fixes
(``fake_poppler.py``, ``fake_opencv.py``, ``fake_docling.py``, ``fake_provider.py``).

:mod:`tests.fakes.engines.convention` is what each of those tasks calls to prove the double
has not drifted from the seam it stands in for.
"""
