"""Make `scripts/poc-flow-v2` importable for the Fase A tests.

The tree lives beside the code it exercises and is not on `sys.path`; `pytest`
only puts `src/` there. One insertion here, stated once, so every test imports
`from flow import …` without repeating the path juggling.
"""

from __future__ import annotations

import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_FLOW_V2 = _ROOT / "scripts" / "poc-flow-v2"

if str(_FLOW_V2) not in sys.path:
    sys.path.insert(0, str(_FLOW_V2))
