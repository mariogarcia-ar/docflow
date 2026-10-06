"""Fixtures shared by the whole suite.

The lab tools' glue tests need the scripted provider installed at the provider seam, and a
fixture and a test parameter of the same name in one module trip Pylint's
``redefined-outer-name``. The fixture therefore lives here, beside the tests, rather than in
the module that consumes it.

Nothing here reaches an engine: the provider double is the one the LLM processor's own suite
ships, installed at ``docflow.llm.primitives``.

This module also puts ``scripts/tools/`` on ``sys.path``, once. A tool is written to be
invoked by path — ``python scripts/tools/pdf.py`` — where the interpreter already does that,
and its ``import _cli`` is a plain import because of it. A test imports the same module as
``scripts.tools.pdf``, so the directory has to be reachable for that import to resolve.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from docflow.llm import primitives as llm_primitives
from tests.fakes.engines.fake_provider import FakeProvider

#: Where the lab tools live; the tools import their shared library by its bare name.
TOOLS_DIR = Path(__file__).resolve().parents[1] / "scripts" / "tools"

if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from scripts.tools import _cli  # noqa: E402  # pylint: disable=wrong-import-position


@pytest.fixture(autouse=True)
def isolated_bench_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep a developer's own `.env` out of the suite.

    The bench reads ``<repo root>/.env`` — a file git ignores — for its optional settings, so
    without this every run of the suite would answer to whoever is running it. Pointing the
    variable at a path that does not exist restores the flags-only bench these tests were written
    against; a test that wants a configuration file states its own, under ``tmp_path``.
    """
    monkeypatch.setenv(_cli.ENV_FILE_VARIABLE, str(tmp_path / "absent.env"))


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
