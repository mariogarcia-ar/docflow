"""K7 ``ArtifactStore`` port adapter over the **filesystem**.

The one place where the filesystem is named for the store path. It implements
``ArtifactStore`` by delegating to `docflow/kernels/store.py`, which carries the
ordering rule the whole layer depends on.

Why a separate adapter, when the kernel already exists
-------------------------------------------------------

`ports/store.py` states it plainly: *"The filesystem adapter binds this to
``docflow/kernels/store.py``"*. Until this module existed, nothing did — the CLI
imported the **kernel** and never the port, so the arrow `sad.md` §1 draws

    domain → ports → adapters

was being short-circuited one layer up. A caller that reaches a kernel directly has
made the kernel interface in fact, whatever the port declares, and `sad.md` §1's own
claim — *"moving from local files to object storage is a change at the bottom and
invisible above it"* — stops being true.

**What this adapter is not.** It is not a vendor seam like
`docflow/adapters/pdf.py::PyMuPdfVendor` or `docflow/adapters/image.py::PillowVendor`.
There is no third-party library to hide: `kernels/store.py` imports only the standard
library, and `sad.md` §3 records K7's resource as *"n/a — it **is** the cache"*. What
moves here is the **filesystem**, and the point is not engine selection — it is that
the port becomes the thing a caller depends on, as the architecture says it already
is.

Two translations, and why each is not optional
---------------------------------------------

**Exceptions become ``Reason``s.** The kernel raises — ``FileNotFoundError`` for a
missing artifact or ledger, ``ValueError`` for a stage outside the declared set,
``TypeError`` for a ``commit`` handed something that is not an ``Artifact`` — because
inside a kernel an exception is the cheapest way to refuse. The port returns
``KernelResult``, and `kernel-cli.md` §5 closes the vocabulary. The adapter is where
the two meet.

**A failed verification stays a value.** ``verify`` answers a question, so ``False``
comes back as the *value* with no reason. A ``Reason`` from ``verify`` means the
question could not be **asked** — never that the answer was "no". Collapsing the two
would make *"this artifact is corrupt"* indistinguishable from *"I could not look"*,
which is the distinction `ports/store.py` exists to protect.

What is deliberately absent
---------------------------

- **No ``rebuild_manifest``.** The port declares it, and it must *delegate to K1's
  ``rebuild_index()``* — which does not exist yet (`E05-01`, `S1-T06`). Implementing it
  here would mean K7 inventing the meaning of a run, which `sad.md` §3 assigns to K1.
  A caller that reaches it gets a typed ``engine_unavailable`` naming the missing
  dependency, rather than a manifest assembled from a fallback rule.
- **No state of its own.** Every method takes ``root`` or ``unit_dir`` as the port
  specifies, so the adapter is stateless and a caller can point it at any tree.
- **No default root.** A default would make a run's location a decision this layer took
  (`plan-01-kernels.md` §12 open decision #2).
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from docflow.kernels import store as kernel
from docflow.kernels.types import Artifact, Evidence, KernelResult, Reason

# The kernel's refusal shape and the port's result shape are two spellings of the same
# boundary rule, so the translation below is word-for-word the one in the other
# adapters. Stated here rather than at each site.
# pylint: disable=duplicate-code

__all__: list[str] = ["FilesystemStore"]

# --- Reason codes, from the closed set of `kernel-cli.md` §5 -----------------

#: The artifact a ledger claims does not exist. Used for ``get`` on a miss.
_CODE_ARTIFACT_MISSING: Final[str] = "artifact_missing"

#: A call that could not legitimately be made: a stage outside the declared set, a
#: ``commit`` handed something that is not an ``Artifact``, or a unit with no ledger.
#: It is not ``artifact_missing``, because nothing is missing — the request named
#: something the store does not have.
_CODE_UNSUPPORTED_FORMAT: Final[str] = "unsupported_format"

#: The operation's dependency is not built yet. ``rebuild_manifest`` is the only one,
#: and it waits on K1.
_CODE_ENGINE_UNAVAILABLE: Final[str] = "engine_unavailable"


class FilesystemStore:
    """``ArtifactStore`` over a filesystem tree, delegating to `kernels/store.py`.

    Reachable only through the port. The composition root imports this class; no
    module under ``docflow/ports/`` does (`ADR-004`).
    """

    # --- The bytes ----------------------------------------------------------

    def put(self, root: Path, data: bytes, media_type: str) -> KernelResult[Artifact]:
        """Store bytes under their own content hash and return the descriptor.

        Args:
            root: The store root.
            data: The bytes to store.
            media_type: The media type describing them.

        Returns:
            The artifact descriptor, returned only after the rename that put the bytes
            in place has returned — which is what makes a later ``commit`` safe to
            write. ``put`` is the only producer of an ``Artifact``, so no caller can
            hand ``commit`` an argument that means *"the bytes are somewhere"*.

        """
        try:
            artifact = kernel.put(root, data, media_type)
        except (OSError, ValueError) as refused:
            return _refused(_CODE_UNSUPPORTED_FORMAT, refused)

        return KernelResult(
            value=artifact,
            evidence=_evidence({"artifact_sha256": artifact.sha256}),
            reason=None,
        )

    def get(self, root: Path, sha256: str) -> KernelResult[bytes]:
        """Read an artifact's bytes back.

        Args:
            root: The store root.
            sha256: The artifact's content hash.

        Returns:
            The bytes, or no value and ``artifact_missing``. Never an empty buffer: an
            empty result would be indistinguishable from a stored empty file, and the
            absence of a claimed artifact is a fact worth acting on.

        """
        try:
            payload = kernel.get(root, sha256)
        except FileNotFoundError as refused:
            return _refused(_CODE_ARTIFACT_MISSING, refused)
        except (OSError, ValueError) as refused:
            return _refused(_CODE_UNSUPPORTED_FORMAT, refused)

        return KernelResult(
            value=payload,
            evidence=_evidence(
                {"artifact_sha256": sha256, "bytes": float(len(payload))}
            ),
            reason=None,
        )

    def verify(self, root: Path, sha256: str) -> KernelResult[bool]:
        """Check an artifact's bytes against the hash that names them.

        Args:
            root: The store root.
            sha256: The hash to verify against.

        Returns:
            ``True`` or ``False`` as the **value** — a failed verification is an
            answer, so it is not a failure of the call and carries no reason. A
            ``Reason`` here means the question could not be asked at all, which is why
            the translation below maps **no** exception to ``False``.

        The guard below is the distinction, and the kernel cannot draw it: asked about
        a root that is not a store at all, ``kernel.verify`` reduces the question to
        ``_artifact_path(...).is_file()``, which answers ``False`` for *"there is no
        such file"* and for *"I cannot read this"* alike. So an unreadable root would
        come back as *"the artifact is corrupt"*, which is the collapse
        `ports/store.py` says this port exists to prevent. A root that is merely
        absent can still be looked in, and is answered; a root with a file standing
        in its path cannot.

        """
        if _a_file_stands_in_the_way(root):
            return _refused(
                _CODE_UNSUPPORTED_FORMAT,
                NotADirectoryError(
                    f"{root} cannot be looked in: a file stands in its path, so "
                    f"whether {sha256} is intact could not be asked"
                ),
            )

        try:
            intact = kernel.verify(root, sha256)
        except (OSError, ValueError) as refused:
            return _refused(_CODE_UNSUPPORTED_FORMAT, refused)

        return KernelResult(
            value=intact,
            evidence=_evidence({"artifact_sha256": sha256, "intact": intact}),
            reason=None,
        )

    # --- The ledger ---------------------------------------------------------

    def begin(self, unit_dir: Path, stage: str) -> KernelResult[Any]:
        """Mark a stage ``running`` before its work starts.

        Args:
            unit_dir: The unit's directory.
            stage: The stage's name.

        Returns:
            The ledger with the stage ``running``, or no value and a typed ``Reason``
            for a stage outside the declared set.

        """
        return self._ledger_call(kernel.begin, unit_dir, stage, "begin")

    def commit(
        self, unit_dir: Path, stage: str, artifact: Artifact
    ) -> KernelResult[Any]:
        """Mark a stage ``done`` against the artifact that now exists.

        Args:
            unit_dir: The unit's directory.
            stage: The stage's name.
            artifact: The stored artifact, as returned by ``put``.

        Returns:
            The ledger with the stage ``done``, or no value and a typed ``Reason``.
            There is no path that writes ``done`` about work that did not produce a
            durable artifact — the single rule that never bends (`sad.md` §7.1).

        """
        try:
            ledger = kernel.commit(unit_dir, stage, artifact)
        except TypeError as refused:
            # `commit` refuses anything that is not the `Artifact` `put` returned. The
            # type is the ordering rule, so this is a usage error rather than a missing
            # artifact — and it must not be reported as one.
            return _refused(_CODE_UNSUPPORTED_FORMAT, refused)
        except FileNotFoundError as refused:
            return _refused(_CODE_ARTIFACT_MISSING, refused)
        except (OSError, ValueError) as refused:
            return _refused(_CODE_UNSUPPORTED_FORMAT, refused)

        return _ledger_result(ledger, artifact.sha256)

    def fail(self, unit_dir: Path, stage: str, reason: Reason) -> KernelResult[Any]:
        """Mark a stage ``failed`` with the reason it produced.

        Args:
            unit_dir: The unit's directory.
            stage: The stage's name.
            reason: Why the stage produced no value.

        Returns:
            The ledger with the stage ``failed``, or no value and a typed ``Reason``.
            The stage's own reason is **recorded** in the ledger and is not the
            adapter's reason for failing: this call succeeded at recording a failure,
            and the two must not be confused.

        """
        try:
            ledger = kernel.fail(unit_dir, stage, reason)
        except (OSError, ValueError) as refused:
            return _refused(_CODE_UNSUPPORTED_FORMAT, refused)

        return _ledger_result(ledger, None, stage=stage)

    def read_ledger(self, unit_dir: Path) -> KernelResult[Any]:
        """Read a unit's ledger.

        Args:
            unit_dir: The unit's directory.

        Returns:
            The ledger, or no value and a typed ``Reason``. A unit with no ledger is an
            error rather than an empty ledger, because an empty ledger would be
            indistinguishable from a unit that ran nothing.

        """
        try:
            ledger = kernel.read_ledger(unit_dir)
        except FileNotFoundError as refused:
            return _refused(_CODE_ARTIFACT_MISSING, refused)
        except (OSError, ValueError) as refused:
            return _refused(_CODE_UNSUPPORTED_FORMAT, refused)

        return _ledger_result(ledger, None)

    def write_ledger(self, unit_dir: Path, ledger: Any) -> KernelResult[Any]:
        """Write a unit's ledger, creating the tree's first ledger file.

        Args:
            unit_dir: The unit's directory.
            ledger: The ledger to write, as ``new_ledger`` built it.

        Returns:
            The ledger as written, or no value and a typed ``Reason``. This is the
            bootstrap operation of a ledger tree; every later mutation goes through
            ``begin``/``commit``/``fail`` so that the ordering rule is enforced rather
            than remembered.

        """
        # The kernel takes a ``Ledger`` and calls ``.unit`` on it, so anything else
        # raises ``AttributeError`` — a miss on an *attribute*, which says nothing to
        # the caller beyond "that object was not what this operation takes". The guard
        # is stated here for the same reason the kernel states its ``isinstance`` on
        # ``commit``: the refusal should name the misuse rather than report a missing
        # attribute.
        if not isinstance(ledger, kernel.Ledger):
            return _refused(
                _CODE_UNSUPPORTED_FORMAT,
                TypeError(
                    f"`write_ledger` takes a Ledger, not {type(ledger).__name__}: "
                    "build one with `new_ledger`"
                ),
            )

        try:
            kernel.write_ledger(unit_dir, ledger)
        except (OSError, ValueError, TypeError) as refused:
            return _refused(_CODE_UNSUPPORTED_FORMAT, refused)

        return _ledger_result(ledger, None)

    # --- The derived summary ------------------------------------------------

    def rebuild_manifest(self, out_dir: Path) -> KernelResult[Mapping[str, object]]:
        """Rebuild the run summary from the ledgers alone — **not yet available**.

        The port declares this operation and requires it to **delegate to K1's**
        ``rebuild_index()``: K7 owns the bytes and the ledger files, K1 owns what a run
        means (`sad.md` §3). K1 does not exist yet (`E05-01`, `S1-T06`), so there is
        nothing to delegate to.

        **This refuses rather than substituting.** Assembling a manifest here from a
        rule of the store's own would make K7 the authority on what a run means, which
        is precisely the split the port describes — and a manifest nobody can rebuild
        is a manifest that becomes authoritative and drifts.

        Args:
            out_dir: The run's output directory.

        Returns:
            No value and ``engine_unavailable``, naming the missing dependency.

        """
        return KernelResult(
            value=None,
            evidence=_evidence(
                {},
                {"out_dir": out_dir.name, "awaits": "kernels/orchestrator.py"},
            ),
            reason=Reason(
                code=_CODE_ENGINE_UNAVAILABLE,
                message=(
                    "`rebuild_manifest` delegates to K1's `rebuild_index()`, which "
                    "does not exist yet (`E05-01` / `S1-T06`). It is not assembled "
                    "from a rule of this adapter's own: K7 owns the bytes and the "
                    "ledger files, K1 owns what a run means, and a manifest this "
                    "layer derived would be the store claiming to know. `# TODO: "
                    "[MVP]`"
                ),
            ),
        )

    # --- Helpers ------------------------------------------------------------

    def _ledger_call(
        self, operation: Any, unit_dir: Path, stage: str, name: str
    ) -> KernelResult[Any]:
        """Run one stage-mutating kernel call and translate its refusals.

        Args:
            operation: The kernel function to call.
            unit_dir: The unit's directory.
            stage: The stage's name.
            name: The operation's name, for the refusal's message.

        Returns:
            The ledger, or no value and a typed ``Reason`` for a stage outside the
            declared set or an unreadable tree.

        """
        try:
            ledger = operation(unit_dir, stage)
        except FileNotFoundError as refused:
            return _refused(_CODE_ARTIFACT_MISSING, refused)
        except (OSError, ValueError) as refused:
            return _refused(_CODE_UNSUPPORTED_FORMAT, refused)

        return _ledger_result(ledger, None, stage=stage, operation=name)


def _ledger_result(
    ledger: Any,
    artifact_sha256: str | None,
    *,
    stage: str | None = None,
    operation: str | None = None,
) -> KernelResult[Any]:
    """Build a successful ledger result with the state it recorded.

    Args:
        ledger: The ledger the kernel returned.
        artifact_sha256: The artifact's hash, when the call was about one, or ``None``.
        stage: The stage the call concerned, or ``None``.
        operation: The operation's name, or ``None``.

    Returns:
        The result, carrying the unit and the states as observations.

    """
    observed: dict[str, object] = {
        "unit": ledger.unit,
        "stages": {
            name: record.state for name, record in sorted(ledger.stages.items())
        },
    }
    if stage is not None:
        observed["stage"] = stage
    if operation is not None:
        observed["operation"] = operation
    if artifact_sha256 is not None:
        observed["artifact_sha256"] = artifact_sha256

    return KernelResult(
        value=ledger,
        evidence=_evidence(
            {
                "stages": float(len(ledger.stages)),
                "done": float(
                    sum(1 for r in ledger.stages.values() if r.state == "done")
                ),
            },
            observed,
        ),
        reason=None,
    )


def _a_file_stands_in_the_way(root: Path) -> bool:
    """Report whether ``root`` or one of its ancestors is a file.

    ``Path.exists()`` cannot answer this, and that is the reason for the walk:
    `pathlib` discards ``ENOTDIR`` along with ``ENOENT``, so a path whose *ancestor* is
    a file reports the same ``False`` as a path that is simply absent. Those two are
    exactly what must not be confused — an absent store is an ordinary miss, a store
    with a file standing in its path is a question that cannot be put.

    Args:
        root: The path to check.

    Returns:
        True when ``root`` or one of its ancestors is a file.

    """
    return any(part.is_file() for part in (root, *root.parents))


def _evidence(
    measurements: Mapping[str, float], observed: Mapping[str, object] | None = None
) -> Evidence:
    """Build an evidence record for this adapter's results.

    Args:
        measurements: The numeric measurements.
        observed: The remaining observations.

    Returns:
        The assembled ``Evidence``.

    """
    return Evidence(
        terms=MappingProxyType({}),
        measurements=MappingProxyType(dict(measurements)),
        observed=MappingProxyType(dict(observed or {})),
    )


def _refused(code: str, refused: Exception) -> KernelResult[Any]:
    """Turn a kernel exception into a typed result.

    Args:
        code: A code from the closed set of `kernel-cli.md` §5.
        refused: The exception the kernel raised.

    Returns:
        A ``KernelResult`` with no value, the reason, and the message the kernel wrote.

    """
    return KernelResult(
        value=None,
        evidence=_evidence({}),
        reason=Reason(
            code=code,
            message=f"{type(refused).__name__}: {refused}",
        ),
    )
