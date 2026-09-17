"""K7 store - content-addressed artifacts and the ledger write path.

The Stage 1 substrate that makes every later claim checkable (`E02-01` /
`S1-T02` and `E02-02` / `S1-T03`): bytes named by their own hash and never
visible half-written, and a per-unit ledger whose ``done`` is written only after
the rename that put those bytes in place has returned.

Two capabilities, one file
--------------------------

``put`` / ``get`` / ``verify`` own the bytes. ``begin`` / ``commit`` / ``fail`` /
``read_ledger`` / ``write_ledger`` own the record of unit stage states. They live
in one file because the ordering they enforce runs *between* them: a ledger's
``done`` is a statement about an artifact, so the code that writes the artifact
and the code that makes the statement are one unit of review
(`plans/README.md` §2 non-negotiable 1, `prd.md` FR-04, `sad.md` §7.1).

The ordering, and why it is structural
--------------------------------------

``put`` runs **write -> flush -> fsync -> rename -> fsync(directory)** and returns
only after the rename has returned. ``commit`` takes an
:class:`~docflow.kernels.types.Artifact`, and ``put`` is the only producer of one,
so a caller cannot pass an argument that means *"I have the bytes somewhere"*.
The ordering is enforced by the signatures rather than asked of the caller's
memory, and :class:`StageRecord` closes the same path a second time by refusing to
*construct* ``done`` without an artifact hash - the constructibility style
``KernelResult`` already uses for its two states.

``_replace`` exists as a one-line seam on the rename boundary so that the crash
this invariant is about can be injected at a precise point, instead of being
simulated by hand (`plan-01-kernels.md` §7b row 2).

What the ledger records besides the state, and why
--------------------------------------------------

:class:`StageRecord` carries two things that make the record usable rather than
merely descriptive, and both are the *minimum* the record can hold rather than a
convenience:

- the **artifact hash** a terminal stage produced, so ``done`` is a claim about
  named bytes rather than about work; and
- the **cache key** the stage ran under, so a reader can tell *a stage that
  completed* from *a stage that completed under the settings now in force*.

Without the second one `sad.md` §5 is not implementable: the design says an
improved prompt changes the registry hash and the ledger's completion claims
become *visibly stale* instead of quietly wrong - and they can only be *visibly*
anything if the key that produced them is on disk. `prd.md` FR-08 states it
outright: *"every stage result is keyed by the full cache key"*. Recording the
key is also what lets `E05-01`'s dispatch answer *"is this stage already
terminal **for this key**?"* instead of *"has it ever run?"*.

The key is therefore **required for a terminal outcome** (``done``, ``failed``)
and permitted - not required - for the states on the way there, because a stage
that has not been dispatched under a key yet has none to record. Which key a
dispatch *computes*, and when it decides to skip, is K1's (`E05-01` / `S1-T06`).
Forced invalidation and marking downstream stages ``pending`` are Plan 3's
(`S3-T08`); this module records the term, it does not act on it.

The seven durable states
------------------------

:data:`DURABLE_STATE_ORDER` is the closed set, in the order `sad.md` §7.1 declares
it. ``StageRecord`` refuses to construct any value outside it, so an eighth state
is not writable. ``begin`` writes ``running`` **before** a stage's work starts,
which is what distinguishes *never began* from *began and was cut off*; the
scheduler that calls it, and the policy for re-running a stage that is already
``done``, are K1's (`E05-02` / `S1-T07`), not this module's.

Deliberately out of scope
-------------------------

- **No verification on ledger read.** Checking a ``done`` stage against the
  filesystem on every read, with no flag, is `E05-05` (`S1-T10`, ADR-006). This
  module provides the read path; it adds no check to it.
- **No manifest.** ``run.json`` and ``rebuild_index()`` are K1's (`E05-01` /
  `S1-T06`). K7 owns the bytes and the ledger *files*; the meaning of a run is
  K1's. The sufficiency checked here is only that a manifest is *reconstructible*
  from the ledger tree (`kernel-cli.md` §11 row 16).
- **No ledger-trust ``verify`` and no flag.** ``verify`` checks one artifact's
  bytes against its hash; it says nothing about ledger trust (`kernel-cli.md`
  §9). There is no ``verify`` subcommand for the ledger path and no ``--verify``
  flag - **Never** (`prd.md` §10, ADR-006).
- **No stage-set semantics.** Which stages exist, what ``not_applicable`` means
  and the per-code stage set are Plan 3's (`S3-T03`). The stage set is declared
  once by the caller and a stage outside it is an error, not a new stage.
- **No domain noun** in any name here. **Never**.

PoC stage
---------

The lifecycle stage is **PoC**: close the flow, keep the shortcuts visible. Each
deliberate shortcut below carries a marker naming what must replace it.

"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
from collections.abc import Iterable, Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Final

from docflow.kernels.types import Artifact, Reason

__all__: list[str] = [
    "DURABLE_STATE_ORDER",
    "Ledger",
    "StageRecord",
    "begin",
    "commit",
    "fail",
    "get",
    "ledger_path",
    "new_ledger",
    "put",
    "read_ledger",
    "verify",
    "write_ledger",
]

#: The seven durable ledger states, in the order `sad.md` §7.1 declares them. The
#: *set* is frozen by `plans/README.md` §3 (Plan 1 row) and owned by `E05-02`;
#: this module owns only the write path that can never write an eighth value.
DURABLE_STATE_ORDER: Final[tuple[str, ...]] = (
    "running",
    "done",
    "failed",
    "pending",
    "blocked",
    "stale",
    "skipped",
)

#: The same seven values as a membership set. Derived, so the two cannot drift.
_DURABLE_STATES: Final[frozenset[str]] = frozenset(DURABLE_STATE_ORDER)

#: The states that are a *result*, as opposed to a position on the way to one.
#: A terminal outcome must carry the cache key it ran under (`prd.md` FR-08);
#: the other five cannot, because the stage has not run under a key yet.
_TERMINAL_OUTCOME_STATES: Final[frozenset[str]] = frozenset({"done", "failed"})

#: The artifact directory under a store root. Content addressing means the file
#: name is the hash, so no extension is appended: the name must stay the identity.
_ARTIFACT_DIRECTORY: Final[str] = "artifacts"

#: The ledger file suffix, fixed by `prd.md` FR-29 (``<name>.ledger.json``). The
#: surrounding layout - where a unit directory sits relative to ``run.json`` - is
#: `S3-T07`'s (Plan 3) and is not decided here.
_LEDGER_SUFFIX: Final[str] = ".ledger.json"


@dataclasses.dataclass(frozen=True, slots=True)
class StageRecord:
    """One stage of one unit, as the ledger records it.

    Three fields, and each carries a state the reader can act on: what happened,
    which artifact it produced, and why it produced none. The record is the
    manifest's input, so it states outcomes rather than summarizing them.

    Three of the plan's rules are enforced by *construction* here, in the same
    style ``KernelResult`` uses, because a rule a caller can violate is a rule
    that will be violated under pressure:

    - ``done`` requires an artifact hash. This is *never ``done`` about
      non-durable bytes* (`plans/README.md` §2 non-negotiable 1) stated as a
      constructibility rule.
    - ``failed`` requires a reason code. Failure is a result, not an absence
      (`sad.md` §7.1), and an unexplained failure is indistinguishable from a
      silent one.
    - a **terminal outcome** (``done``, ``failed``) requires the cache key the
      stage ran under. Without it the record says a stage finished but not
      *what it was*, and `sad.md` §5's promise that completion claims go
      *visibly stale* when the registry changes has nothing to compare against.

    The hash is a *claim*, not a proof: verifying it against the filesystem on
    every ledger read is `E05-05` (`S1-T10`) and is deliberately absent here.

    Attributes:
        state: One of the seven values in :data:`DURABLE_STATE_ORDER`.
        artifact_sha256: The artifact this stage produced, or None when it
            produced none. Required for ``done``; never the empty string, which
            is a stand-in rather than a hash.
        reason_code: The machine-readable reason for a ``failed`` stage, or None.
            Required for ``failed``. The human-readable message is deliberately
            not recorded: the ledger is read by a machine and a message string is
            not an assertion target (`kernel-cli.md` §5).
        cache_key: The key the stage ran under, as
            :func:`docflow.kernels.cache_key.cache_key` composed it, or None
            while the stage has not been dispatched. Required for ``done`` and
            ``failed``; never the empty string, which would read as *keyed* to
            an empty key (`prd.md` FR-08).

    Raises:
        ValueError: If ``state`` is outside the seven durable states; if
            ``artifact_sha256``, ``reason_code`` or ``cache_key`` is the empty
            string; if ``state`` is ``done`` and no artifact hash is given; if
            ``state`` is ``failed`` and no reason code is given; or if ``state``
            is a terminal outcome and no cache key is given.

    """

    state: str
    artifact_sha256: str | None
    reason_code: str | None
    cache_key: str | None

    def __post_init__(self) -> None:
        """Reject every record outside the seven states and the stated pairings.

        Called by the generated ``__init__``, and still reachable on a frozen
        slotted dataclass: the fields are already set, so raising here means no
        illegal record ever escapes construction.

        Raises:
            ValueError: On an unknown state, an empty-string stand-in, a ``done``
                without an artifact hash, a ``failed`` without a reason code, or
                a terminal outcome without the cache key it ran under.

        """
        if self.state not in _DURABLE_STATES:
            raise ValueError(
                f"{self.state!r} is not one of the seven durable ledger states. "
                "The closed set is DURABLE_STATE_ORDER; a value outside it is an "
                "eighth state, which no code path may write."
            )

        if self.artifact_sha256 == "":
            raise ValueError(
                "artifact_sha256 must be a real hash or None: the empty string "
                "is the shape a silent failure takes, not an artifact."
            )

        if self.reason_code == "":
            raise ValueError(
                "reason_code must be a real code or None: the empty string is "
                "the shape a silent failure takes, not a reason."
            )

        if self.cache_key == "":
            raise ValueError(
                "cache_key must be a real key or None: the empty string would "
                "read as a stage keyed to nothing, and a result that records no "
                "key cannot be told from one produced under other settings."
            )

        if self.state in _TERMINAL_OUTCOME_STATES and self.cache_key is None:
            raise ValueError(
                f"A {self.state} stage must name the cache key it ran under: a "
                "result with no key cannot be compared against the settings now "
                "in force, so a stage that is done and no longer correct is "
                "indistinguishable from one that is (FR-08, sad.md §5)."
            )

        if self.state == "done" and self.artifact_sha256 is None:
            raise ValueError(
                "A done stage must name the artifact it produced: done is a "
                "claim about bytes that exist, and a claim about no bytes at all "
                "is the ordering this store exists to prevent."
            )

        if self.state == "failed" and self.reason_code is None:
            raise ValueError(
                "A failed stage must carry a reason code: failure is a result, "
                "not an absence, and a failure without a code cannot be asserted."
            )


@dataclasses.dataclass(frozen=True, slots=True)
class Ledger:
    """A unit's durable record of stage states.

    The unit, and every stage of it. **Every** declared stage is present from the
    moment the ledger is written, so a stage that never started is recorded as
    ``pending`` rather than missing: an absent stage reads as a gap in the graph,
    while ``pending`` reads as work not yet done, and only the second one is true.

    The unit is recorded inside the file, not inferred from the path, because a
    manifest is rebuilt from the ledger *tree* alone (`kernel-cli.md` §11 row 16)
    and the tree does not carry the unit's identity.

    Attributes:
        unit: The unit this ledger belongs to, as the caller named it.
        stages: Stage name to :class:`StageRecord`, in declaration order. Order is
            preserved by the JSON writer, so reporting is deterministic.

    """

    unit: str
    stages: Mapping[str, StageRecord]


def new_ledger(unit: str, stages: Iterable[str]) -> Ledger:
    """Declare a unit's stage set, every stage ``pending``.

    The declaration is the mechanism behind one acceptance criterion: a stage
    that never started must still be *readable*, and ``pending`` is the state
    that says so.

    Args:
        unit: The unit's name, recorded in the ledger.
        stages: The unit's stage names, in the order they should be reported.

    Returns:
        A ledger with every given stage at ``pending`` and no artifact claimed.

    """
    pending = StageRecord(
        state="pending", artifact_sha256=None, reason_code=None, cache_key=None
    )
    return Ledger(
        unit=unit,
        stages=MappingProxyType(dict.fromkeys(stages, pending)),
    )


def ledger_path(unit_dir: Path) -> Path:
    """Return the ledger file for a unit directory.

    Args:
        unit_dir: The unit's directory; the file is named after it.

    Returns:
        ``<unit_dir>/<unit_dir.name>.ledger.json``, the suffix rule fixed by
        `prd.md` FR-29.

    """
    return unit_dir / f"{unit_dir.name}{_LEDGER_SUFFIX}"


def write_ledger(unit_dir: Path, ledger: Ledger) -> None:
    """Write a unit's ledger, atomically.

    A half-written ledger is the same class of defect as a half-written artifact,
    so the file goes through the same atomic write. The caller is handed back no
    value: it already holds what it asked to be written.

    Args:
        unit_dir: The unit's directory, created if it does not exist.
        ledger: The ledger to write, whole.

    """
    _atomic_write(ledger_path(unit_dir), _ledger_to_json(ledger).encode("utf-8"))


def read_ledger(unit_dir: Path) -> Ledger:
    """Read a unit's ledger, including the stages that never started.

    Args:
        unit_dir: The unit's directory.

    Returns:
        The ledger, with an entry for every declared stage.

    Raises:
        FileNotFoundError: If the unit has no ledger. A missing ledger is not an
            empty one: reporting an empty ledger would be indistinguishable from
            a unit that has run nothing, which is the silent stand-in this module
            refuses everywhere.

    """
    path = ledger_path(unit_dir)
    if not path.is_file():
        raise FileNotFoundError(
            f"No ledger at {path}: a unit that has not run has no states to "
            "report, and an empty ledger would claim otherwise."
        )
    return _ledger_from_json(path.read_text(encoding="utf-8"))


def begin(unit_dir: Path, stage: str, cache_key: str | None) -> Ledger:
    """Record that a stage has started, **before** its work begins.

    This is the operation the scheduler calls first. Its position - written when
    the stage starts, not when it finishes - is the whole crash-recovery design:
    a scheduler that wrote state only on completion would report a killed stage
    as never having run, and then resume it as if nothing had happened
    (`sad.md` §7.1). *When* it is called is `E05-02`'s (`S1-T07`); providing it is
    this module's.

    Recording ``running`` withdraws any previous artifact claim for the stage: the
    stage is no longer known to have produced anything.

    Args:
        unit_dir: The unit's directory, whose ledger must already exist.
        stage: The declared stage that is starting.
        cache_key: The key the stage is about to run under, when the caller has
            already composed it. ``running`` is not a terminal outcome, so it is
            permitted rather than required: a caller that begins a stage before
            resolving its key passes ``None`` and says so, rather than relying on
            a default to say it for them.

    Returns:
        The updated ledger.

    Raises:
        ValueError: If the stage is not declared in the unit's ledger.

    """
    return _with_state(unit_dir, stage, "running", None, None, cache_key)


def commit(unit_dir: Path, stage: str, artifact: Artifact, cache_key: str) -> Ledger:
    """Record a stage as ``done``, over an artifact that already exists.

    The ordering rule of `plans/README.md` §2 lives in this signature. The
    parameter is an :class:`~docflow.kernels.types.Artifact`, and the only code in
    this module that produces one is :func:`put`, which returns after its rename
    has returned and its directory has been fsynced. A bare hash is therefore
    refused, so there is no call a caller can make that writes ``done`` before the
    bytes were durable - not because a caller is asked to be careful, but because
    there is nothing to pass. The ``isinstance`` guard is what makes the signature
    binding at run time: an annotation is documentation until it is checked, and a
    string with the bytes *somewhere* is the exact argument a caller would reach
    for.

    Args:
        unit_dir: The unit's directory, whose ledger must already exist.
        stage: The declared stage that finished.
        artifact: The stored artifact this stage produced, as :func:`put`
            returned it. Its hash is what the ledger records.
        cache_key: The key the stage ran under. It is required and has no
            default: a terminal outcome that cannot be told from one produced
            under other settings is exactly the record `sad.md` §5 says must go
            *visibly* stale rather than quietly wrong.

    Returns:
        The updated ledger.

    Raises:
        TypeError: If ``artifact`` is not an
            :class:`~docflow.kernels.types.Artifact`. A hash string, a path or a
            mapping is refused before any record is built.
        ValueError: If the stage is not declared in the unit's ledger.

    """
    if not isinstance(artifact, Artifact):
        raise TypeError(
            "commit requires the Artifact that put returned, not a hash, a path "
            f"or a description of where the bytes are (got {artifact!r}). done is "
            "a claim about bytes that exist, so it can only be written over a "
            "descriptor produced by a completed write."
        )
    return _with_state(unit_dir, stage, "done", artifact.sha256, None, cache_key)


def fail(unit_dir: Path, stage: str, reason: Reason, cache_key: str) -> Ledger:
    """Record a stage as ``failed``, with the reason it produced.

    Only the reason's ``code`` is recorded. The ledger is read by scripts and
    assertions target the code, never the message (`kernel-cli.md` §5).

    Args:
        unit_dir: The unit's directory, whose ledger must already exist.
        stage: The declared stage that failed.
        reason: The typed reason the stage produced.
        cache_key: The key the stage was running under. Required, for the same
            reason it is required on ``commit``: a failure is a result, and a
            result produced under an unrecorded key is one nothing can compare
            against the settings now in force.

    Returns:
        The updated ledger.

    Raises:
        ValueError: If the stage is not declared in the unit's ledger.

    """
    return _with_state(unit_dir, stage, "failed", None, reason.code, cache_key)


def put(root: Path, data: bytes, media_type: str) -> Artifact:
    """Store bytes under their own hash and return their descriptor.

    The bytes become visible at their final name in one step or not at all:
    write to a staging name, flush, fsync, rename, then fsync the directory so
    the rename itself is durable. A crash anywhere before the rename leaves the
    final name untouched, so no reader can ever see a partial artifact where a
    complete one belongs.

    Storing the same bytes twice yields one artifact on disk: an already intact
    file is left alone. A file whose bytes do not hash to its own name is
    replaced, so ``put`` always leaves the artifact intact - which is what lets a
    stage interrupted mid-write be re-run instead of deadlocking on its own
    leftovers. The replacement is not reported; telemetry is a Release concern.

    Args:
        root: The store root. Its artifact directory is created if absent.
        data: The bytes to store, exactly as produced.
        media_type: The media type describing the bytes, e.g. "image/png". It is
            carried on the descriptor; the store's identity for the bytes is the
            hash alone, so bytes stored under one media type are the same
            artifact as the same bytes stored under another.

    Returns:
        The artifact's descriptor, whose hash is the hash of ``data``.

    """
    sha256 = _sha256(data)
    target = _artifact_path(root, sha256)

    if not _is_intact(target, sha256):
        _atomic_write(target, data)

    return Artifact(
        sha256=sha256,
        size_bytes=len(data),
        media_type=media_type,
        path=str(target.relative_to(root)),
    )


def get(root: Path, sha256: str) -> bytes:
    """Return the bytes stored under a hash.

    The parameter is the hash string rather than an
    :class:`~docflow.kernels.types.Artifact`, because the caller reaching a store
    by hash - ``store get <sha256>`` - has no descriptor in hand, and building one
    to satisfy a signature would mean inventing a media type and a size. The
    descriptor belongs to callers that stored the bytes.

    Args:
        root: The store root.
        sha256: The lowercase hexadecimal SHA-256 digest to read.

    Returns:
        The stored bytes, exactly as written.

    Raises:
        FileNotFoundError: If nothing is stored under that hash. It never returns
            empty bytes, ``b""`` or a placeholder for a miss (`prd.md` FR-11): an
            empty buffer is a legal artifact, so returning one for a miss would
            make "not stored" and "stored, empty" the same answer.

    """
    target = _artifact_path(root, sha256)
    if not target.is_file():
        raise FileNotFoundError(
            f"No artifact under {target}: a miss raises here rather than "
            "returning empty bytes, which would read as a stored empty artifact."
        )
    return target.read_bytes()


def verify(root: Path, sha256: str) -> bool:
    """Report whether the bytes stored under a hash still hash to it.

    A boolean *value*, so a failed verification is a successful call: the
    question was answered, and the answer is no (`kernel-cli.md` §9 - exit ``0``
    with ``value: false``, not exit ``2``). A missing artifact answers the same
    question the same way.

    This checks one artifact's bytes. It says nothing about ledger trust, and
    there is no ``--verify`` flag anywhere: verification of a ``done`` stage
    against the filesystem happens on every ledger read, with no flag, and that is
    `E05-05`'s (`S1-T10`).

    Args:
        root: The store root.
        sha256: The digest the stored bytes are supposed to have.

    Returns:
        True when the stored bytes hash to ``sha256``; False when they are
        truncated, altered, or absent.

    """
    return _is_intact(_artifact_path(root, sha256), sha256)


# Six parameters, and the count is the record's: four of them are the fields
# `StageRecord` carries, one is the stage to update and one is the directory. Packing
# them into a value object would move the fields' names away from the call site that
# has to get them right, which is the opposite of what this helper needs.
# pylint: disable=too-many-arguments,too-many-positional-arguments
def _with_state(
    unit_dir: Path,
    stage: str,
    state: str,
    artifact_sha256: str | None,
    reason_code: str | None,
    cache_key: str | None,
) -> Ledger:
    """Read the unit's ledger, replace one stage's record, write it back.

    Args:
        unit_dir: The unit's directory.
        stage: The stage to update.
        state: The new durable state.
        artifact_sha256: The artifact to claim, or None.
        reason_code: The reason code to record, or None.
        cache_key: The key the stage ran under, or None while it has not been
            dispatched.

    Returns:
        The updated ledger.

    Raises:
        ValueError: If the stage is not declared in the unit's ledger.

    """
    ledger = read_ledger(unit_dir)
    if stage not in ledger.stages:
        raise ValueError(
            f"Stage {stage!r} is not declared in the ledger for unit "
            f"{ledger.unit!r}. The stage set is declared once by the caller; a "
            "stage outside it is a mistake in the caller, not a new stage."
        )

    record = StageRecord(
        state=state,
        artifact_sha256=artifact_sha256,
        reason_code=reason_code,
        cache_key=cache_key,
    )
    updated = Ledger(
        unit=ledger.unit,
        stages=MappingProxyType({**ledger.stages, stage: record}),
    )
    write_ledger(unit_dir, updated)
    return updated


def _sha256(data: bytes) -> str:
    """Return the lowercase hexadecimal SHA-256 digest of a buffer.

    Args:
        data: The bytes to digest.

    Returns:
        The digest as 64 hexadecimal characters.

    """
    return hashlib.sha256(data).hexdigest()


def _artifact_path(root: Path, sha256: str) -> Path:
    """Return the path an artifact's bytes live at.

    Args:
        root: The store root.
        sha256: The artifact's digest.

    Returns:
        The path under the store root's artifact directory.

    """
    return root / _ARTIFACT_DIRECTORY / sha256


def _is_intact(target: Path, sha256: str) -> bool:
    """Report whether the file at a path exists and hashes to a digest.

    Args:
        target: The path to read.
        sha256: The digest the bytes must hash to.

    Returns:
        True only when the file exists and its bytes hash to ``sha256``.

    """
    if not target.is_file():
        return False
    return _sha256(target.read_bytes()) == sha256


def _replace(source: Path, target: Path) -> None:
    """Rename a staging file onto its final name.

    The write/rename boundary, isolated so the crash this module's ordering is
    about can be injected at a precise point (`plan-01-kernels.md` §7b row 2)
    rather than approximated. It is the last step that may be interrupted.

    Args:
        source: The staging path that holds the complete, fsynced bytes.
        target: The final name those bytes belong under.

    """
    os.replace(source, target)


def _atomic_write(target: Path, data: bytes) -> None:
    """Make a buffer appear at a path in one step, or not at all.

    The sequence is the contract: write to a staging name, flush, fsync, rename,
    then fsync the directory. The directory sync is part of the durability step
    rather than an extra: without it the rename itself can be lost, and the stage
    that recorded ``done`` would be claiming bytes that did not survive.

    The staging file is deliberately left behind when the rename never returns.
    It is invisible under the final name - which is what the invariant requires -
    and leaving it lets an operator see that a write was interrupted and where.
    Collecting it is a Release concern.

    Args:
        target: The final path the bytes belong at. Parent directories are
            created.
        data: The bytes to write.

    """
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(f".{target.name}.{os.getpid()}.tmp")

    with staging.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())

    _replace(staging, target)
    _sync_directory(target.parent)


def _sync_directory(directory: Path) -> None:
    """Flush a directory's own entries to stable storage.

    Args:
        directory: The directory whose entries must survive a crash.

    """
    # TODO: [RELEASE] Concurrent writers are not coordinated: the staging name is
    # per-process, so two threads would collide. PoC runs one writer per store.
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _ledger_to_json(ledger: Ledger) -> str:
    """Encode a ledger as the text stored on disk.

    The shape carries exactly what a manifest rebuild needs from the ledger tree
    alone: the unit, and every stage's state with its terminal outcome. Stage
    declaration order is preserved, so a reader sees the same order the caller
    declared.

    Args:
        ledger: The ledger to encode.

    Returns:
        The ledger as indented JSON text ending in a newline.

    """
    payload = {
        "unit": ledger.unit,
        "stages": {
            name: {
                "state": record.state,
                "artifact_sha256": record.artifact_sha256,
                "reason_code": record.reason_code,
                "cache_key": record.cache_key,
            }
            for name, record in ledger.stages.items()
        },
    }
    return json.dumps(payload, indent=2) + "\n"


def _ledger_from_json(text: str) -> Ledger:
    """Decode a ledger from the text stored on disk.

    Every record is rebuilt through :class:`StageRecord`, so a ledger edited by
    hand into an eighth state, or into a ``done`` with no artifact, is rejected on
    read instead of being believed.

    Args:
        text: The ledger file's contents.

    Returns:
        The decoded ledger.

    Raises:
        ValueError: If the text carries a record the seven states do not allow.
        KeyError: If the text is missing a field the format requires.

    """
    payload = json.loads(text)
    stages = {
        name: StageRecord(
            state=entry["state"],
            artifact_sha256=entry["artifact_sha256"],
            reason_code=entry["reason_code"],
            cache_key=entry["cache_key"],
        )
        for name, entry in payload["stages"].items()
    }
    return Ledger(unit=payload["unit"], stages=MappingProxyType(stages))
    # TODO: [MVP] The ledger's on-disk shape is validated by construction, not
    # against a schema: a missing field raises KeyError from this function. The
    # schema-and-layout task (S3-T07) owns a declared format and a typed error.
