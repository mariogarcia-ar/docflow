"""The stage contract: names, order, and what each stage writes.

This is the single table the plan freezes in Ola A0 (`plan/README.md`). Nothing
here imports an adapter or a domain model — a stage is a name, a dependency set
and an artifact, and that is all the run process needs to drive it.

Two rules from `my_flow.md` Anexo B live here rather than as notes:

- **B.2** the dependency table and the artifact table exist **once**; a run
  process, a report and a journal that each carried their own list would
  eventually name a file that is called something else.
- **B.15** the artifact name is a single owner; `stage_artifact` derives the
  paths from this table, and no caller builds a path by hand.

`run.json`, `journal.json` and `control.json` are the run record, not stage
artifacts; their names are declared here so every writer spells them once.
"""

from __future__ import annotations

import pathlib
from typing import Final

__all__: list[str] = [
    "CONTROL_NAME",
    "CONTROL_PAUSED",
    "CONTROL_RUNNING",
    "CONTROL_STOPPED",
    "JOURNAL_NAME",
    "RUN_NAME",
    "STAGES",
    "STAGE_ARTIFACTS",
    "STAGE_DECIDE",
    "STAGE_DEPENDENCIES",
    "STAGE_EXTRACT",
    "STAGE_HITL",
    "STAGE_READ",
    "stage_artifact",
]

#: The four stages in the order they run (`my_flow.md` §1).
STAGE_READ: Final[str] = "read"
STAGE_EXTRACT: Final[str] = "extract"
STAGE_DECIDE: Final[str] = "decide"
STAGE_HITL: Final[str] = "hitl"
STAGES: Final[tuple[str, ...]] = (STAGE_READ, STAGE_EXTRACT, STAGE_DECIDE, STAGE_HITL)

#: What each stage needs before it can run (`my_flow.md` §1: each stage's inputs
#: are the previous stage's artifacts).
STAGE_DEPENDENCIES: Final[dict[str, tuple[str, ...]]] = {
    STAGE_READ: (),
    STAGE_EXTRACT: (STAGE_READ,),
    STAGE_DECIDE: (STAGE_EXTRACT,),
    STAGE_HITL: (STAGE_DECIDE,),
}

#: The artifact each stage writes. `hitl` writes its queue and, when there is
#: something to resolve or settle, the files beside it.
STAGE_ARTIFACTS: Final[dict[str, tuple[str, ...]]] = {
    STAGE_READ: ("material.json",),
    STAGE_EXTRACT: ("extraction.json",),
    STAGE_DECIDE: ("decision.json",),
    STAGE_HITL: ("pending.json",),
}

#: The run record, written beside the stage artifacts. `journal.json` says which
#: stages are `done`; `run.json` is the derived trace; `control.json` carries the
#: pause/resume/stop state.
JOURNAL_NAME: Final[str] = "journal.json"
RUN_NAME: Final[str] = "run.json"
CONTROL_NAME: Final[str] = "control.json"

#: The run states a `control.json` carries. A stage marks itself `paused` or
#: `stopped` only *between* stages — never mid-artifact — so the journal always
#: names a state the next run can resume from.
CONTROL_RUNNING: Final[str] = "running"
CONTROL_PAUSED: Final[str] = "paused"
CONTROL_STOPPED: Final[str] = "stopped"


def stage_artifact(root: pathlib.Path, stage: str) -> tuple[pathlib.Path, ...]:
    """The files a stage writes, inside a work root.

    Args:
        root: The work root.
        stage: One of the four stage names.

    Returns:
        The artifact paths, in the order the stage writes them. An unknown stage
        yields none rather than a guessed path.

    """
    return tuple(root / name for name in STAGE_ARTIFACTS.get(stage, ()))
