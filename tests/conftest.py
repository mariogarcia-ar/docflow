"""Fixtures shared by the whole suite.

The lab tools' glue tests need the scripted provider installed at the provider seam, and a
fixture and a test parameter of the same name in one module trip Pylint's
``redefined-outer-name``. The fixture therefore lives here, beside the tests, rather than in
the module that consumes it.

Nothing here reaches an engine: the provider double is the one the LLM processor's own suite
ships, installed at ``docflow.llm.primitives``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from docflow.llm import primitives as llm_primitives
from tests.fakes.engines.fake_provider import FakeProvider


@pytest.fixture
def providers(monkeypatch: pytest.MonkeyPatch) -> Callable[..., FakeProvider]:
    """Return a factory that installs the scripted provider at every provider primitive.

    Args:
        monkeypatch: pytest's patcher, which restores the seam afterwards.

    Returns:
        A factory taking the double's own knobs and returning the installed double.
    """

    def install(**settings: Any) -> FakeProvider:
        """Install a double at every provider primitive and return it."""
        fake = FakeProvider(**settings)
        for name in llm_primitives.PRIMITIVE_NAMES:
            monkeypatch.setattr(f"docflow.llm.primitives.{name}", getattr(fake, name))
        return fake

    return install
