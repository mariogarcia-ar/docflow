"""Atomic persistence of the orchestrator's durable state (``ORC-03``).

The orchestrator's context is the one thing a stopped run must not lose, so it is written
the same way every other artifact in this project is: a ``.tmp`` sibling, validated, then
one rename. A reader therefore never observes a half-written context, and an interrupted
write leaves no residue — which is exactly what makes ``resume`` safe to attempt.

The store is transient in the PoC (a JSON file under the run's working directory), but the
shape it writes is the real one, so replacing the store at the MVP gate changes where the
bytes go and not what they are.

# TODO: [RELEASE] filesystem-level crash safety (``fsync`` of the file and its directory
# before the rename) is not claimed here; the guarantee is atomic visibility, not durability
# across a power loss.
"""

# pylint: disable=duplicate-code
# Reason: this module is a deliberate sibling of the processors' ``publication`` modules.
# The orchestrator may not import a processor's internals (``README.md`` §7), so the
# ``.tmp`` → validate → rename rule is written once more here on purpose.
from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

#: Suffix of the temporary file a publication writes before it renames into place.
TEMP_SUFFIX = ".tmp"


class WorkflowPersistenceError(Exception):
    """A durable context could not be written or read.

    Attributes:
        destination: The path the operation was about, when it had one.
    """

    def __init__(self, message: str, *, destination: Path | None = None) -> None:
        super().__init__(message)
        self.destination = destination


def write_json_atomic(destination: Path, payload: Mapping[str, Any]) -> Path:
    """Write ``payload`` through a ``.tmp`` sibling, validate it, then rename it into place.

    Args:
        destination: Final path of the record.
        payload: The complete content.

    Returns:
        ``destination``, once it is complete.

    Raises:
        WorkflowPersistenceError: When the temporary file could not be written or does not
            parse back. The temporary file is removed first, so a failed save leaves the
            previous record — if any — untouched and no residue behind.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + TEMP_SUFFIX)
    try:
        temporary.write_text(
            json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8"
        )
        json.loads(temporary.read_text(encoding="utf-8"))
        os.replace(temporary, destination)
    except BaseException as failure:
        temporary.unlink(missing_ok=True)
        raise WorkflowPersistenceError(
            f"{destination} could not be written: {failure}", destination=destination
        ) from failure
    return destination


def read_json(path: Path) -> Any:
    """Read a durable record back.

    Args:
        path: The record to read.

    Returns:
        Its parsed content.

    Raises:
        WorkflowPersistenceError: When the record is missing or does not parse.
    """
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as failure:
        raise WorkflowPersistenceError(
            f"{path} could not be read: {failure}", destination=path
        ) from failure
