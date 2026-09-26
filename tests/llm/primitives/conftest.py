"""Shared fixtures of the LLM primitives' tests.

The seam resolves its HTTP client lazily, so a test that wants a client installs one in
``sys.modules`` — which is what :mod:`tests.llm.primitives.http_stub` is for. The fixture lives
here rather than in the test module so that the module that *uses* it does not also define it:
a fixture and a parameter of the same name in one module is the pytest idiom Pylint reports as a
redefinition, and the conftest is the place the other processor suites put theirs.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Any

import pytest

from tests.llm.primitives.http_stub import StubClient


@pytest.fixture
def http(monkeypatch: pytest.MonkeyPatch) -> Callable[..., StubClient]:
    """Return a factory that installs a stub HTTP client, for every test in this package.

    Args:
        monkeypatch: pytest's patcher, which removes the client from ``sys.modules`` afterwards.

    Returns:
        A factory taking the stub's own knobs and returning the installed client.
    """

    def install(**settings: Any) -> StubClient:
        """Install a stub client at ``httpx`` and return it.

        Args:
            settings: The stub's own knobs — the body, the status and an exception to raise.
        """
        client = StubClient(**settings)
        monkeypatch.setitem(sys.modules, "httpx", client)
        return client

    return install
