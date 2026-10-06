"""Shared fixtures of the image processor's tests.

The only double this processor has is the in-memory OpenCV fake, installed at the engine seam
inside ``docflow.image.primitives`` and nowhere higher (`README.md` §9.7). There is one tier and
one gate: ``pytest`` runs whole, with no engine installed and no marker.

Importing the seam never needs OpenCV, which is what makes the patch below possible: the
module attribute ``docflow.image.primitives.cv2`` is ``None`` until the fixture replaces it, and
no test ever imports ``cv2``.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from tests.fakes.engines.fake_opencv import FakeOpenCV

#: The engine itself: the seam resolves ``cv2`` at call time, so the double replaces that
#: attribute and every line of our translation stays under test.
PATCH_TARGET = "docflow.image.primitives.cv2"


@pytest.fixture(autouse=True)
def opencv(monkeypatch: pytest.MonkeyPatch) -> Callable[..., FakeOpenCV]:
    """Return a factory that installs an OpenCV double, for every test in this package.

    The fixture is autouse on purpose: a test that forgot it would reach the library installed
    on a developer's machine, which is exactly the accident the double exists to prevent. A
    test that needs the double scripted calls the returned factory; a test that needs the
    engine *absent* patches the seam to ``None`` itself, after this fixture has run.

    Args:
        monkeypatch: pytest's patcher, which restores the seam afterwards.

    Returns:
        A factory taking the double's own failure knobs and returning the installed double.
    """

    def install(*, double: FakeOpenCV | None = None, **settings: object) -> FakeOpenCV:
        """Install a double and return it.

        Args:
            double: A pre-built double, for a test that scripts one of the engine's own
                answers rather than its failures.
            settings: The double's own failure knobs.
        """
        fake = double if double is not None else FakeOpenCV(**settings)
        monkeypatch.setattr(PATCH_TARGET, fake)
        return fake

    install()
    return install
