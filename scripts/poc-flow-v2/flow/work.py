"""The work tree: one document's artifacts, journal and control state.

A work root holds the stage artifacts, the journal (which stages are `done`),
the derived `run.json` and the `control.json` state. This module is the single
place a caller reads or writes any of them, so the file names exist once
(`my_flow.md` B.2, B.15).

Fase A persists the stubs' plain values; Fase B replaces the payloads with the
real types behind the same file names — the tree itself does not change.
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import Callable, Mapping

from .control import read_control, write_control
from .fields import Extraction, FieldResult
from .journal import Journal, document_digest, run_signature
from .material import Material
from .record import RunRecord, read_run, write_run
from .serial import (
    encode,
    extraction_from_dict,
    extraction_to_dict,
    material_from_dict,
    material_to_dict,
    pending_from_dict,
    pending_to_dict,
    result_from_dict,
    result_to_dict,
)
from .stages import (
    STAGE_ARTIFACTS,
    STAGE_DECIDE,
    STAGE_EXTRACT,
    STAGE_HITL,
    STAGE_READ,
    stage_artifact,
)

__all__: list[str] = [
    "WorkTree",
    "stage_artifact",
]

#: The extra files the `hitl` stage may write, beside its queue. Named here so
#: nothing spells them twice (`my_flow.md` B.15).
HITL_EXTRAS: tuple[str, ...] = ("resolution.json", "confirmed.json")


def _write_atomic(path: pathlib.Path, payload: bytes) -> None:
    """Write bytes via a temp name then rename, so a kill cannot truncate."""
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(path.name + ".tmp")
    staging.write_bytes(payload)
    staging.replace(path)


def _to_dict(stage: str, payload: object) -> object:
    """The plain object a stage's payload serialises as.

    The shape of each artifact is owned by `serial.py`; this is the single
    dispatch that maps a stage to its contract, so `save_artifact` and
    `load_artifact` never special-case a type inline.
    """
    if stage == STAGE_DECIDE and isinstance(payload, FieldResult):
        return result_to_dict(payload)
    if stage == STAGE_EXTRACT and isinstance(payload, Extraction):
        return extraction_to_dict(payload)
    if stage == STAGE_HITL and isinstance(payload, list):
        return pending_to_dict(payload)
    if stage == STAGE_READ and isinstance(payload, Material):
        return material_to_dict(payload)
    return payload


#: The reader that rebuilds each contract-typed stage's artifact. A stage not
#: in this table stores a plain object and is read back as-is.
_LOADERS: dict[str, Callable[[Mapping[str, object]], object]] = {
    STAGE_READ: material_from_dict,
    STAGE_DECIDE: result_from_dict,
    STAGE_EXTRACT: extraction_from_dict,
    STAGE_HITL: pending_from_dict,
}


def _load_data(path: pathlib.Path) -> object | None:
    """Read one artifact file as JSON, or ``None`` when absent/unreadable."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


class WorkTree:
    """The artifacts and record for one document's run.

    Attributes:
        root: The work root directory.
        journal: The stage marks.
        document_name: The document's file name, for the record.

    """

    def __init__(
        self, root: pathlib.Path, journal: Journal, document_name: str
    ) -> None:
        self.root = root
        self.journal = journal
        self.document_name = document_name

    def save_artifact(self, stage: str, payload: object) -> tuple[pathlib.Path, ...]:
        """Write a stage's primary artifact and return the paths written.

        A dataclass contract is serialised through the single owner of the
        shape (`serial.py`); any other value passes through as-is.
        """
        encoded = _to_dict(stage, payload)
        written: list[pathlib.Path] = []
        for name in STAGE_ARTIFACTS.get(stage, ()):
            path = self.root / name
            _write_atomic(path, encode(encoded))
            written.append(path)
        return tuple(written)

    def load_artifact(self, stage: str) -> object | None:
        """Read a stage's primary artifact back, or ``None`` when absent.

        The contract-typed stages are rebuilt as their dataclasses; every other
        stage returns the plain object that was written.
        """
        names = STAGE_ARTIFACTS.get(stage, ())
        if not names:
            return None
        data = _load_data(self.root / names[0])
        if data is None:
            return None
        loader = _LOADERS.get(stage)
        if loader is not None and isinstance(data, Mapping):
            return loader(data)
        return data

    # --- record and control ----------------------------------------------

    def save_record(self, record: RunRecord) -> pathlib.Path:
        """Write the derived run record."""
        return write_run(self.root, record)

    def load_record(self) -> RunRecord | None:
        """Read the derived run record, if there is one."""
        return read_run(self.root)

    def write_control(self, state: str) -> pathlib.Path:
        """Write the control state."""
        return write_control(self.root, state)

    def read_control(self) -> str:
        """Read the control state."""
        return read_control(self.root)

    # --- convenience -----------------------------------------------------

    @classmethod
    def open(
        cls,
        root: pathlib.Path,
        document: pathlib.Path,
        settings: Mapping[str, object],
    ) -> WorkTree:
        """Open the work tree for a document, loading or starting a journal.

        Args:
            root: The work root.
            document: The document being processed.
            settings: The run's dials, for the signature.

        Returns:
            A tree whose journal already reflects any previous run, and whose
            ``stale`` flag the caller announces.

        """
        journal = Journal(root, run_signature(settings), document_digest(document))
        return cls(root, journal, document.name)
