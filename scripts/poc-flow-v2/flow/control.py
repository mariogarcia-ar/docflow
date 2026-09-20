"""Pause / resume / stop: the run's control state, as a file.

`control.json` carries one of three states, and is written **between stages
only** — never mid-artifact — so whatever state it names, the journal still
describes a run the next invocation can resume from (`plan/README.md`):

- `running` — the default, written when a run starts;
- `paused` — the run stops after the current stage completes, journal intact;
- `stopped` — the run was stopped forcibly, journal still consistent.

A paused or stopped run is not an error: it is a state a later `run` reads and
continues from. The file exists so the decision *why we stopped* survives the
process, instead of being inferred from the journal.
"""

from __future__ import annotations

import json
import pathlib
from typing import Final

from .stages import CONTROL_NAME, CONTROL_PAUSED, CONTROL_RUNNING, CONTROL_STOPPED

__all__: list[str] = ["read_control", "write_control"]

#: The three states a run may be in. A run state is *why we stopped*; it is not
#: which stage is next — the journal owns that.
VALID_STATES: Final[frozenset[str]] = frozenset(
    {CONTROL_RUNNING, CONTROL_PAUSED, CONTROL_STOPPED}
)


def _encode(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def write_control(root: pathlib.Path, state: str) -> pathlib.Path:
    """Write the control state, atomically, and return its path.

    Args:
        root: The work root.
        state: One of the three states. An unknown state is a programming
            error — a silent stand-in state is the failure this project forbids.

    Raises:
        ValueError: If ``state`` is not one of the three names.

    """
    if state not in VALID_STATES:
        raise ValueError(f"unknown run state {state!r}")
    path = root / CONTROL_NAME
    staging = path.with_name(path.name + ".tmp")
    staging.write_bytes(_encode({"state": state}))
    staging.replace(path)
    return path


def read_control(root: pathlib.Path) -> str:
    """The last recorded state, or `running` when no file exists.

    A missing file is *a fresh run*, not an error — the default state is the
    honest reading of "nothing was recorded".
    """
    path = root / CONTROL_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return CONTROL_RUNNING
    state = data.get("state")
    if state not in VALID_STATES:
        return CONTROL_RUNNING
    return state
