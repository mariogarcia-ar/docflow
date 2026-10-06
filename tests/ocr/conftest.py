"""Shared fixtures of the OCR processor's tests.

The only double this processor has is the in-memory Docling fake, installed inside
``docflow.ocr.primitives`` and nowhere higher (`README.md` §9.7). There is one tier and one gate:
``pytest`` runs whole, with no engine installed and no marker.

Two names are patched, and both are inside the seam:

* ``docflow.ocr.primitives.convert_image_with_docling`` — the engine call, which is the frozen
  injection point the plan fixes. Replacing it is what keeps ``extract_docling_*`` — the half of
  the module that does the translating — under test;
* ``docflow.ocr.primitives.docling`` — the engine namespace, which is where the seam reads the
  engine's *version*. It is patched for the same reason the image suite patches
  ``docflow.image.primitives.cv2``: without it, recording a version would need the engine
  installed, and the whole point of the double is that the suite runs without it.

Importing the seam never needs Docling, which is what makes the patch below possible: the module
attribute is ``None`` until the fixture replaces it, and no test ever imports ``docling``.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from tests.fakes.engines.fake_docling import FakeDocling

#: The engine call: the plan's frozen injection point.
PATCH_TARGET = "docflow.ocr.primitives.convert_image_with_docling"

#: The engine namespace, read for the engine's version.
ENGINE_TARGET = "docflow.ocr.primitives.docling"


@pytest.fixture(autouse=True)
def docling(monkeypatch: pytest.MonkeyPatch) -> Callable[..., FakeDocling]:
    """Return a factory that installs a Docling double, for every test in this package.

    The fixture is autouse on purpose: a test that forgot it would reach the library installed on a
    developer's machine, which is exactly the accident the double exists to prevent. A test that
    needs the double scripted calls the returned factory; a test that needs the engine *absent*
    patches the seam to ``None`` itself, after this fixture has run.

    Args:
        monkeypatch: pytest's patcher, which restores the seam afterwards.

    Returns:
        A factory taking the double's own knobs and returning the installed double.
    """

    def install(
        *, double: FakeDocling | None = None, **settings: object
    ) -> FakeDocling:
        """Install a double at both seam names and return it.

        Args:
            double: A pre-built double, for a test that scripts one of the engine's own answers
                rather than its failures.
            settings: The double's own knobs.
        """
        fake = double if double is not None else FakeDocling(**settings)
        monkeypatch.setattr(PATCH_TARGET, fake)
        monkeypatch.setattr(ENGINE_TARGET, fake)
        return fake

    install()
    return install
