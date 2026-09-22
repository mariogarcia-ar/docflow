"""Low-level image primitives — the only place that knows OpenCV (or Pillow).

Every engine symbol of the image processor lives in this package. Neither the orchestrator nor
another processor may import it; both go through :func:`docflow.image.process_image`.

The modules are sorted by what they are allowed to do:

* :mod:`docflow.image.primitives.engine` — **the seam.** OpenCV is the engine this processor is
  built on, Pillow the documented drop-in alternative; the choice is explicit, the version is
  read for ``metadata.json``, and a missing engine raises rather than quietly using the other.
  It is the only module that loads a library, and it loads it lazily so that importing this
  package pulls in no engine at all.
* :mod:`docflow.image.primitives.failures` — engine failures translated into the contract's
  error vocabulary.
* :mod:`docflow.image.primitives.load` — reading an image and its technical facts. Never
  writes back to the source path.
* :mod:`docflow.image.primitives.analysis` — measuring. Returns numbers, mutates nothing.
* :mod:`docflow.image.primitives.transform` — changing pixels. Returns a new image, mutates
  nothing.

``IMG-02`` created the seam and declared the signatures; ``IMG-03`` … ``IMG-05`` fill them in.
"""
