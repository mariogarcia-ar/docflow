"""Make `scripts/poc-flow-v2` importable for the Fase A tests, and keep the
sampling environment they mutate from leaking into the rest of the suite.

The tree lives beside the code it exercises and is not on `sys.path`; `pytest`
only puts `src/` there. One insertion here, stated once, so every test imports
`from flow import …` without repeating the path juggling.

The isolation fixture below is here for a measured reason, not for tidiness.
`flow.extract._engine` loads `.env` into ``os.environ`` (before it declares the
window), because that is what makes a client like `myllmlocal.py` honour the
file. `test_sampling.py` calls that function, so the variables land in the
**test process** — and `tests/adapters/test_ollama.py` asserts the window it
*measured*, so it fails when a run has already set one:

    pytest tests/poc_flow_v2/test_sampling.py tests/adapters/test_ollama.py
    -> assert 8192 == 4096

Alphabetically `tests/adapters/` comes first and the two never meet, which is
why the default run stayed green while the ordering was load-bearing. The
fixture removes that coincidence: every test in this tree starts from an
environment with no `DOCFLOW_OLLAMA_*` variable, whatever ran before it.
"""

from __future__ import annotations

import os
import pathlib
import sys
from collections.abc import Iterator

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_FLOW_V2 = _ROOT / "scripts" / "poc-flow-v2"

if str(_FLOW_V2) not in sys.path:
    sys.path.insert(0, str(_FLOW_V2))

#: The prefix the flow and the adapter share for sampling options. Named here
#: rather than imported from `flow.sampling`, so this fixture still works when the
#: module under test fails to import — the case where a leaked variable is hardest
#: to diagnose.
PREFIX = "DOCFLOW_OLLAMA_"


@pytest.fixture(autouse=True)
def _no_leaked_sampling_environment() -> Iterator[None]:
    """Start and end every test in this tree with no sampling variables set.

    `monkeypatch` cannot be used here: it records the *current* values and restores
    exactly those, so it neither clears a variable that arrived from a previous
    test nor reports one that the test itself added to the real environment.
    """
    saved = {k: v for k, v in os.environ.items() if k.startswith(PREFIX)}
    for name in saved:
        del os.environ[name]
    try:
        yield
    finally:
        for name in [k for k in os.environ if k.startswith(PREFIX)]:
            del os.environ[name]
        os.environ.update(saved)

