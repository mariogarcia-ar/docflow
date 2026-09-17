"""K7 `ArtifactStore` - the port over content-addressed bytes and the ledger.

An exact, stateless mirror of ``docflow/kernels/store.py`` (`E02`, `S1-T02`/`S1-T03`).
Every method here has the same parameter list as the module-level function it
stands for, and ``root`` is a parameter rather than a constructor argument: the
adapter is then genuinely thin, and `S1-T21`'s flag/port contract test compares a
command's flag set against this signature without having to account for state the
port carries somewhere else (`kernel-cli.md` §3, guardrail 1).

The two capabilities are one port
---------------------------------

``put``/``get``/``verify`` own the bytes. ``begin``/``commit``/``fail``/
``read_ledger``/``write_ledger`` own the record of unit stage states. They belong
to one interface because the rule that joins them is the one this port exists to
protect: **a ledger's ``done`` is a statement about an artifact that already
exists**, so the operation that writes the bytes and the operation that makes the
statement must be reachable through the same contract (`plans/README.md` §2
non-negotiable 1, `prd.md` FR-04).

Two distinctions a caller must be able to rely on
--------------------------------------------------

**A failed verification is a value, not a reason.** ``verify`` answers a
question, so ``False`` is an answer: it comes back as the value with no reason.
A ``Reason`` from ``verify`` means the question could not be *asked* — the root is
unreachable — never that the answer was "no". Collapsing the two would make *"this
artifact is corrupt"* indistinguishable from *"I could not look"*.

**``get`` on a miss is a typed reason, never an empty value.** ``artifact_missing``
exists as a code because the artifact a ledger claims can be absent, and that is a
different fact from an artifact whose content is empty. A port may not return an
empty buffer in its place.

Deliberately absent
-------------------

- **No verification on ledger read.** Checking a ``done`` stage against the
  filesystem on every read, with no flag, is `E05-05` (`S1-T10`, ADR-006). This
  port exposes the read path and adds no check to it.
- **No manifest semantics.** ``rebuild_manifest`` delegates to K1's
  ``rebuild_index()``: K7 owns the bytes and the ledger files, K1 owns what a run
  means (`sad.md` §3).
- **No ledger-trust ``verify``.** ``verify`` checks one artifact's bytes against
  its hash and says nothing about ledger trust. There is no ``verify`` subcommand
  for the ledger path and no ``--verify`` flag — **Never** (`prd.md` §10).
- **No domain noun.** **Never** (`kernel-cli.md` §10).
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Protocol, runtime_checkable

from docflow.kernels.store import Ledger
from docflow.kernels.types import Artifact, KernelResult, Reason

__all__ = ["ArtifactStore"]


@runtime_checkable
class ArtifactStore(Protocol):
    """Content-addressed bytes plus the per-unit ledger, named by capability.

    The filesystem adapter binds this to ``docflow/kernels/store.py``; a
    component test satisfies it with its own fake and imports no adapter
    (`plan-01-kernels.md` §13, Track 3).
    """

    # --- The bytes ----------------------------------------------------------

    def put(self, root: Path, data: bytes, media_type: str) -> KernelResult[Artifact]:
        """Store bytes under their own content hash and return the descriptor.

        Args:
            root: The store root.
            data: The bytes to store.
            media_type: The media type describing them.

        Returns:
            The artifact descriptor, returned only after the rename that put the
            bytes in place has returned — which is what makes a later ``commit``
            safe to write. ``put`` is the only producer of an ``Artifact``, so no
            caller can hand ``commit`` an argument that means *"the bytes are
            somewhere"*.

        """

    def get(self, root: Path, sha256: str) -> KernelResult[bytes]:
        """Read an artifact's bytes back.

        Args:
            root: The store root.
            sha256: The artifact's content hash. The identity is the hash alone:
                a media type is descriptor metadata and the by-hash caller has no
                descriptor to hand.

        Returns:
            The bytes, or no value and ``artifact_missing``. It is never an empty
            buffer: an empty result would be indistinguishable from a stored
            empty file, and the absence of a claimed artifact is a fact worth
            acting on.

        """

    def verify(self, root: Path, sha256: str) -> KernelResult[bool]:
        """Check an artifact's bytes against the hash that names them.

        Args:
            root: The store root.
            sha256: The hash to verify against.

        Returns:
            ``True`` or ``False`` as the **value** — a failed verification is an
            answer, so it is not a failure of the call and carries no reason. A
            ``Reason`` here means the question could not be asked at all.

        """

    # --- The ledger ---------------------------------------------------------

    def begin(self, unit_dir: Path, stage: str) -> KernelResult[Ledger]:
        """Mark a stage ``running`` before its work starts.

        Args:
            unit_dir: The unit's directory.
            stage: The stage's name.

        Returns:
            The ledger with the stage ``running``, or no value and a typed
            ``Reason`` for a stage outside the declared set. Writing ``running``
            before the work is what distinguishes *never began* from *began and
            was cut off*; a scheduler that wrote state only on completion would
            report a killed stage as never having run (`sad.md` §7.1).

        """

    def commit(
        self, unit_dir: Path, stage: str, artifact: Artifact
    ) -> KernelResult[Ledger]:
        """Mark a stage ``done`` against the artifact that now exists.

        Args:
            unit_dir: The unit's directory.
            stage: The stage's name.
            artifact: The stored artifact, as returned by ``put``. The parameter
                type is the ordering rule: only ``put`` produces one, and it
                returns after the rename.

        Returns:
            The ledger with the stage ``done``, or no value and a typed
            ``Reason``. There is no path that writes ``done`` about work that did
            not produce a durable artifact — **the single rule that never bends**
            (`sad.md` §7.1).

        """

    def fail(self, unit_dir: Path, stage: str, reason: Reason) -> KernelResult[Ledger]:
        """Mark a stage ``failed`` with the reason it produced.

        Args:
            unit_dir: The unit's directory.
            stage: The stage's name.
            reason: Why the stage produced no value. Failure is a result, not an
                absence, which is why it carries a reason code rather than a
                message alone.

        Returns:
            The ledger with the stage ``failed``, or no value and a typed
            ``Reason``.

        """

    def read_ledger(self, unit_dir: Path) -> KernelResult[Ledger]:
        """Read a unit's ledger.

        Args:
            unit_dir: The unit's directory.

        Returns:
            The ledger, or no value and a typed ``Reason``. A unit with no ledger
            is an error rather than an empty ledger, because an empty ledger
            would be indistinguishable from a unit that ran nothing.

        """

    def write_ledger(self, unit_dir: Path, ledger: Ledger) -> KernelResult[Ledger]:
        """Write a unit's ledger, creating the tree's first ledger file.

        Args:
            unit_dir: The unit's directory.
            ledger: The ledger to write, as ``new_ledger`` built it.

        Returns:
            The ledger as written, or no value and a typed ``Reason``. This is
            the bootstrap operation of a ledger tree; every later mutation goes
            through ``begin``/``commit``/``fail`` so that the ordering rule is
            enforced rather than remembered.

        """

    # --- The derived summary ------------------------------------------------

    def rebuild_manifest(self, out_dir: Path) -> KernelResult[Mapping[str, object]]:
        """Rebuild the run summary from the ledgers alone.

        Args:
            out_dir: The run's output directory.

        Returns:
            The rebuilt manifest, or no value and a typed ``Reason``. One
            operation, one authority: this **delegates to K1's**
            ``rebuild_index()`` and returns what it returned. K7 owns the bytes
            and the ledger files, not the meaning of a run (`sad.md` §3), and a
            manifest no one can rebuild is a manifest that has become
            authoritative and will therefore drift.

        """
