"""Shared fixtures of the PDF processor's tests.

The only double this processor has is the in-memory Poppler fake, installed at the engine
call inside ``docflow.pdf.primitives`` and nowhere higher (`README.md` §9.7). There is one
tier and one gate: ``pytest`` runs whole, with no engine installed and no marker.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import pytest

from tests.fakes.engines.fake_poppler import FakePage, FakePoppler

#: The engine call itself: the seam resolves ``subprocess`` at call time, so the double
#: replaces that call and every line of our translation stays under test.
PATCH_TARGET = "docflow.pdf.primitives.subprocess.run"


@pytest.fixture
def poppler(monkeypatch: pytest.MonkeyPatch) -> Callable[..., FakePoppler]:
    """Return a factory that installs a Poppler double for the duration of a test.

    Args:
        monkeypatch: pytest's patcher, which restores the real call afterwards.

    Returns:
        A factory taking the document the engine should report, plus the double's own
        failure knobs, and returning the installed double.
    """

    def install(
        pages: Sequence[FakePage] | None = None,
        *,
        double: FakePoppler | None = None,
        **settings: object,
    ) -> FakePoppler:
        """Install a double and return it.

        Args:
            pages: The document the engine should report, when the default double is used.
            double: A pre-built double, for a test that scripts one of the engine's own
                reports rather than its failures.
            settings: The double's own failure knobs.
        """
        fake = (
            double
            if double is not None
            else FakePoppler(pages if pages is not None else (FakePage(),), **settings)
        )
        monkeypatch.setattr(PATCH_TARGET, fake.run)
        return fake

    return install
