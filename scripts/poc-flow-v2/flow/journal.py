"""The resume journal: which stages are done, and how to tell them apart.

Fase A's own journal, not `_mirror.Resume` — `_mirror` journals a **walk of
files** (one entry per input), where the process journal must mark a **run of
stages** (one entry per stage). The rules are the same ones `_mirror` proved
(`my_flow.md` B.5, B.14), applied to stages instead of files:

- **A stage is `done` only when its artifact is written.** A refusal or an
  exception leaves no mark, so a transient failure is retried.
- **A changed input re-does the work** — the journal carries the document's
  sha256.
- **A changed setting discards the journal** — the signature covers the run's
  settings, so a different signature is a different run.
- **Invalidating is not deleting.** Re-running a stage marks that stage and
  every later one not-done, but leaves the artifacts; the journal simply stops
  trusting them.
- **Writes are atomic** — temp name then rename.

The journal is the *source*; `run.json` is derived from it and the artifacts,
never the other way round (`my_flow.md` B.15).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import pathlib
import sys
from collections.abc import Mapping
from typing import Any

from .stages import JOURNAL_NAME, STAGE_HITL, STAGES

__all__: list[str] = [
    "JOURNAL_NAME",
    "STAGES",
    "Journal",
    "document_digest",
    "run_signature",
]


def document_digest(path: pathlib.Path) -> str:
    """Fingerprint a document's bytes, so an edited input is reprocessed.

    An empty digest is **never** treated as done: an unsignable file is
    attempted, not assumed unchanged.
    """
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
    except OSError:
        return ""
    return digest.hexdigest()


def _jsonable(value: object) -> object:
    """Normalise a value for JSON: sets sort, tuples and frozensets become
    lists, Paths their string form, dataclasses their dict.

    Sets are **sorted** before conversion: their iteration order depends on hash
    randomisation, and a signature built from an unsorted set would differ
    between runs and discard the journal every time (`my_flow.md` B.5).
    """
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {key: _jsonable(val) for key, val in dataclasses.asdict(value).items()}
    if isinstance(value, (frozenset, set)):
        return [_jsonable(item) for item in sorted(value, key=repr)]
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, pathlib.Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _jsonable(val) for key, val in value.items()}
    return value


def run_signature(settings: Mapping[str, object]) -> str:
    """Fingerprint everything a run's output depends on.

    The journal is only sound if a changed setting is a different run; otherwise
    a stage keyed only by the document path would be reused after the settings
    changed. The parts are canonicalised (`sort_keys`) so adding a setting
    cannot accidentally reorder anything.
    """
    canonical = json.dumps(_jsonable(settings), sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _write_atomic(path: pathlib.Path, payload: bytes) -> None:
    """Write bytes via a temp name then rename, so a kill cannot truncate."""
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(path.name + ".tmp")
    staging.write_bytes(payload)
    staging.replace(path)


def _encode(payload: object) -> bytes:
    """Serialise an artifact: UTF-8, non-ASCII left as-is, indented (`B.6`)."""
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


@dataclasses.dataclass
class Journal:
    """The stage marks for one document's run, persisted in a work root.

    Attributes:
        root: The work root directory.
        signature: This run's settings fingerprint.
        digest: The document's own fingerprint.
        stale: Whether a journal existed and was discarded for a different
            signature or digest.

    """

    root: pathlib.Path
    signature: str
    digest: str

    def __init__(self, root: pathlib.Path, signature: str, digest: str) -> None:
        self.root = root
        self.signature = signature
        self.digest = digest
        self.stale = False
        self._done: dict[str, bool] = dict.fromkeys(STAGES, False)
        self._load()

    @property
    def path(self) -> pathlib.Path:
        """Where the journal lives."""
        return self.root / JOURNAL_NAME

    def _load(self) -> None:
        """Read a previous journal, trusting it only if signature and digest
        match. A mismatch sets ``stale`` and starts empty — never half-trusted.
        """
        try:
            stored = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if (
            stored.get("signature") != self.signature
            or stored.get("digest") != self.digest
        ):
            self.stale = True
            return
        marks = stored.get("stages")
        if not isinstance(marks, Mapping):
            self.stale = True
            return
        for stage, entry in marks.items():
            if isinstance(entry, Mapping) and entry.get("done") is True:
                self._done[stage] = True

    def done(self, stage: str) -> bool:
        """Whether a previous run already produced this stage's artifact."""
        return self._done.get(stage, False)

    def mark(self, stage: str) -> None:
        """Record one stage as done and persist the journal atomically."""
        self._done[stage] = True
        self._write()

    def clear_from(self, stage: str) -> None:
        """Mark a stage and every later one as not done.

        The artifacts are not deleted — the journal simply stops trusting them,
        so a crash after clearing still resumes safely rather than reading
        half-invalidated state (`my_flow.md` B.5).
        """
        start = STAGES.index(stage)
        for later in STAGES[start:]:
            self._done[later] = False
        self._write()

    def first_unfinished(self) -> str | None:
        """The first stage with no done mark, in run order; ``None`` when all
        four are done."""
        for stage in STAGES:
            if not self._done[stage]:
                return stage
        return None

    def resume_from(self) -> str:
        """The stage a new run should start at: the first unfinished one, or
        `hitl` when everything is done (a no-op tail)."""
        return self.first_unfinished() or STAGE_HITL

    def _write(self) -> None:
        """Persist the stage marks, atomically, without changing them."""
        payload: dict[str, Any] = {
            "signature": self.signature,
            "digest": self.digest,
            "stages": {stage: {"done": done} for stage, done in self._done.items()},
        }
        _write_atomic(self.path, _encode(payload))

    def announce(self) -> None:
        """Report a discarded journal to stderr — never stdout, which is the
        report's surface. A run that silently ignored its previous result looks
        identical to a run that had nothing to resume."""
        if self.stale:
            print(
                "previous run used different settings or input: "
                "nothing will be resumed",
                file=sys.stderr,
            )
