"""The derived run record: where the run went, written to `run.json`.

`run.json` is the trace of one run as data — every step with `ran` or `reused`,
the artifacts it wrote, and the notes. It is **derived**, never authoritative:
the journal and the stage artifacts are the source, and this record is rebuilt
from them (`my_flow.md` B.15, `plan/README.md`). A derived record that drifts
is re-derivable; an authoritative one drifts and stays wrong.

The live step trace lives in `progress.py`; this module turns it into the
persisted record and reads it back, so the report and the next run see the same
path.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

from .progress import StepTrace
from .stages import RUN_NAME

__all__: list[str] = ["RUN_NAME", "RunRecord", "read_run", "write_run"]


def _step_to_dict(step: StepTrace) -> dict[str, object]:
    return {
        "name": step.name,
        "action": step.action,
        "detail": step.detail,
        "artifacts": list(step.artifacts),
    }


def _step_from_dict(data: dict[str, Any]) -> StepTrace:
    raw_artifacts = data.get("artifacts")
    artifacts = tuple(raw_artifacts) if isinstance(raw_artifacts, list) else ()
    return StepTrace(
        name=str(data["name"]),
        action=str(data["action"]),
        detail=str(data["detail"]),
        artifacts=artifacts,
    )


def _encode(payload: object) -> bytes:
    """Serialise the record: UTF-8, non-ASCII as-is, indented (`B.6`)."""
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


# `too-few-public-methods`: `RunRecord` is a record the process hands between
# stages — its fields, not its methods, are the contract (`my_flow.md` B.15).
# pylint: disable=too-few-public-methods
class RunRecord:
    """A run's trace plus the input it was made under.

    Attributes:
        document: The document's file name.
        digest: The document's fingerprint, so a record is traceable to its
            bytes.
        signature: The settings fingerprint.
        steps: The steps in order, each with its action and artifacts.

    """

    def __init__(
        self,
        document: str,
        digest: str,
        signature: str,
        steps: list[StepTrace],
    ) -> None:
        self.document = document
        self.digest = digest
        self.signature = signature
        self.steps = steps

    def to_dict(self) -> dict[str, object]:
        """The JSON-able form, kept so `write_run` and callers share one shape."""
        return {
            "document": self.document,
            "digest": self.digest,
            "signature": self.signature,
            "steps": [_step_to_dict(step) for step in self.steps],
        }


def write_run(root: pathlib.Path, record: RunRecord) -> pathlib.Path:
    """Write the derived record, atomically, and return its path."""
    path = root / RUN_NAME
    staging = path.with_name(path.name + ".tmp")
    staging.write_bytes(_encode(record.to_dict()))
    staging.replace(path)
    return path


def read_run(root: pathlib.Path) -> RunRecord | None:
    """Read a previous record, or ``None`` when absent or unreadable."""
    path = root / RUN_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list):
        return None
    steps = [_step_from_dict(step) for step in raw_steps if isinstance(step, dict)]
    return RunRecord(
        document=str(data.get("document", "")),
        digest=str(data.get("digest", "")),
        signature=str(data.get("signature", "")),
        steps=steps,
    )
