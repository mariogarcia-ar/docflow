"""Shared fixtures of the orchestrator's tests.

The orchestrator is exercised through the four processors' public contracts, so the only
doubles here are the contract-level fakes of ``tests/fakes/processors``: each replaces a
whole processor at its own entry point. No test reaches an engine or a provider — the
engine doubles of ``tests/fakes/engines/`` belong to the processors' own suites and sit one
level lower (``README.md`` §9.7).
"""

from __future__ import annotations

import pytest

from tests.fakes.processors import ProcessorDoubles


@pytest.fixture
def processors(monkeypatch: pytest.MonkeyPatch) -> ProcessorDoubles:
    """Install the four fake processors at their public entry points.

    The doubles are installed for the whole test, so a test that runs the workflow twice —
    a first run and a resume — keeps one set of call counters across both and can assert
    what the second run did *not* do.

    Args:
        monkeypatch: pytest's patcher, which restores the real entry points afterwards.

    Returns:
        The installed doubles.
    """
    return ProcessorDoubles().install(monkeypatch)
