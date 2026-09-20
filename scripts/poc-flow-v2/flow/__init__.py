"""The v2 flow library: the run process over a frozen stage contract.

Fase A ships the process — stages, journal, resume, pause/stop, trace, report —
driven over stubs. Fase B replaces the stubs with the real decision engine and
adapters behind the same contract.

The public surface is small on purpose: :func:`run` is the entry point,
:func:`render_report` and :func:`trace` are the operator's view, and the stage
names are re-exported so a caller can speak them without reaching into
submodules.
"""

from __future__ import annotations

from .fields import FieldResult
from .progress import StepTrace, trace
from .report import render as render_report
from .run import (
    STAGE_DECIDE,
    STAGE_EXTRACT,
    STAGE_HITL,
    STAGE_READ,
    RunOutcome,
    run,
)
from .stages import STAGE_ARTIFACTS, STAGE_DEPENDENCIES, STAGES, stage_artifact

# `duplicate-code`: this facade re-exports the stage surface so callers import
# one name (`flow`) instead of reaching into submodules. The repetition is the
# contract, not an accident.
# pylint: disable=duplicate-code

__all__: list[str] = [
    "STAGES",
    "STAGE_ARTIFACTS",
    "STAGE_DECIDE",
    "STAGE_DEPENDENCIES",
    "STAGE_EXTRACT",
    "STAGE_HITL",
    "STAGE_READ",
    "FieldResult",
    "RunOutcome",
    "StepTrace",
    "render_report",
    "run",
    "stage_artifact",
    "trace",
]
