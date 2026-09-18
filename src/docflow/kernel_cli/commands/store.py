"""K7's commands - `store` (`E07-02` / `S1-T21`).

Six commands, six port methods, and the mapping is the whole content of this module:
`put`, `get`, `verify`, the ledger write path, and the manifest. Each one constructs
the adapter, calls exactly one method, and returns the `Call`. No logic lives here -
`kernel-cli.md` §3's first guardrail is *"one command = one port method with zero
logic in the CLI"*, and this module is where that is easiest to violate, because
`store ls` needs an index the port does not expose and the temptation is to walk the
directory tree here.

`rebuild_manifest` is the one command that reaches *through* K7 rather than around
it. The port requires the adapter to delegate to K1's `rebuild_index()`, and it does;
`store manifest-rebuild` and `orchestrator manifest-rebuild` are therefore the same
operation reached from two sides (`kernel-cli.md` §9, *one operation, one
authority*).
"""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType
from typing import Final

from docflow.adapters.store import FilesystemStore
from docflow.kernel_cli.commands.refusals import answered
from docflow.kernel_cli.main import Call, Handler
from docflow.kernels import orchestrator
from docflow.kernels.types import Evidence, KernelResult


def _store() -> FilesystemStore:
    """Build the filesystem adapter.

    Built per call rather than held: it carries no state (the root is a parameter of
    every operation, not a field of the adapter), so holding one would suggest a
    connection that does not exist.

    Returns:
        The adapter.

    """
    return FilesystemStore()


def put(
    *,
    file: str,
    media_type: str,
    root: str,
    **_: object,
) -> Call:
    """Store a file's bytes and report the artifact.

    Args:
        file: The file to store.
        media_type: The media type to record with it.
        root: The store root.
        **_: Accepted so an unknown flag reaches the dispatcher's refusal rather
            than being silently ignored here.

    Returns:
        The call, carrying the artifact.

    """
    data = Path(file).read_bytes()
    return Call(result=_store().put(Path(root), data, media_type))


def get(*, sha256: str, root: str, **_: object) -> Call:
    """Read an artifact's bytes back.

    A miss is a typed reason, never empty bytes: the port says `get` raises rather
    than returning nothing, because *"I have no content"* and *"the content is
    empty"* are different answers and only one of them is an answer.

    Args:
        sha256: The artifact's hash.
        root: The store root.
        **_: See :func:`put`.

    Returns:
        The call, carrying the bytes.

    """
    return Call(result=_store().get(Path(root), sha256))


def verify(*, sha256: str, root: str, **_: object) -> Call:
    """Check one artifact's bytes against its hash.

    A **bool as a value**, so a failed verification is exit `0` with `value: false`
    and not exit `2`: the question was answered, and the answer was *no*. This is
    deliberately not the ledger-trust check - that is never a request
    (`kernel-cli.md` §9), and keeping the two names apart is what stops them being
    confused.

    Args:
        sha256: The artifact's hash.
        root: The store root.
        **_: See :func:`put`.

    Returns:
        The call, whose value is the boolean.

    """
    return Call(result=_store().verify(Path(root), sha256))


def ls(*, root: str, prefix: object = None, **_: object) -> Call:
    """List the artifacts a store root holds.

    `kernel-cli.md` §9 marks this as an *index* rather than a port method, because the
    port has no `list` operation: a store is content-addressed, so the set of things in
    it is whatever the ledger tree says has been written. That is what this reads - the
    artifact directory under each unit - rather than walking the tree for files that
    look like hashes, which would list bytes nobody claimed.

    Args:
        root: The store root.
        prefix: An optional hash prefix to filter by.
        **_: Accepted, so an unknown flag reaches the dispatcher.

    Returns:
        The call, whose value is the artifact hashes found, sorted.

    """
    found: list[str] = []
    for ledger_path in sorted(Path(root).glob("**/*.ledger.json")):
        artifacts = ledger_path.parent / "artifacts"
        if not artifacts.is_dir():
            continue
        found.extend(
            entry.name for entry in sorted(artifacts.iterdir()) if entry.is_file()
        )
    if prefix is not None:
        wanted = str(prefix)
        found = [name for name in found if name.startswith(wanted)]
    return Call(
        result=answered(
            found,
            terms={"root": root, "indexed_from": "ledgers"},
            measurements={"artifacts": float(len(found))},
        )
    )


def ledger_read(*, unit: str, root: str, **_: object) -> Call:
    """Read a unit's ledger.

    The value is a **description** of the ledger, not the `Ledger` object: the envelope
    carries the seven boundary types, mappings and sequences, and `Ledger` is a
    kernel-layer value that is not on that list - `E01-01`'s encoder refuses an unknown
    type rather than stringifying it, which is what keeps a stand-in off the wire. The
    description is also the more useful answer here: a caller wants the per-stage states
    and the hash claims, which is what this reports.

    Args:
        unit: The unit directory holding the ledger.
        root: The store root. K7 reads a ledger *file*, so the unit directory is what
            is read; the flag is accepted because `kernel-cli.md` section 10 scopes
            `--root` to K7.
        **_: Accepted, so an unknown flag reaches the dispatcher.

    Returns:
        The call, carrying the ledger's unit, stages and stage set.

    """
    del root
    ledger = _store().read_ledger(Path(unit))
    if ledger.reason is not None or ledger.value is None:
        return Call(result=ledger)

    record = ledger.value
    # And the verification outcome travels **with** the read, which is the whole claim
    # `kernel-cli.md` §9 makes for this command: *"`store ledger-read` reports the same
    # verification outcome as K1's"*. The check is K1's, so it is asked rather than
    # reimplemented - one definition of *the bytes are there*, reported by both doors.
    verdict = orchestrator.verify_ledger(Path(unit))
    return Call(
        result=KernelResult(
            value={
                "unit": record.unit,
                "stages": {
                    name: dict(stage.as_mapping())
                    for name, stage in record.stages.items()
                },
                "unverified": dict(verdict),
            },
            evidence=Evidence(
                terms=MappingProxyType({"unit_dir": unit}),
                measurements=MappingProxyType({"stages": float(len(record.stages))}),
                observed=MappingProxyType({"trustworthy": str(not verdict).lower()}),
            ),
            reason=None,
        )
    )


def manifest_rebuild(*, out: str, **_: object) -> Call:
    """Rebuild the manifest through K7's delegating method, and **write** it.

    Two steps, and both are K1's authority. The adapter's `rebuild_manifest`
    **delegates** to `orchestrator.rebuild_index` - K7 owns the bytes and the ledger
    files, K1 owns what a run means, so the derivation is not this layer's. The write
    then goes through `orchestrator.write_index`, which derives again by calling
    `rebuild_index` and writes what that returned.

    Writing here rather than only deriving is what makes this door the **same**
    operation as `orchestrator manifest-rebuild`. `plan-01-kernels.md` §6 step 11
    deletes `run.json` and expects *"both doors return what `rebuild_index()`
    returned"*: a door that answered with a value while leaving the tree empty would
    satisfy the letter of *return the same* and not the task.

    Args:
        out: The run's output root.
        **_: Accepted, so an unknown flag reaches the dispatcher.

    Returns:
        The call, carrying the manifest K7's method returned.

    """
    derived = _store().rebuild_manifest(Path(out))
    if derived.reason is not None or derived.value is None:
        return Call(result=derived)

    # The same call K1's own command makes, so the file on disk is derived rather than
    # assembled (`E05-01`) and both doors leave byte-identical bytes.
    orchestrator.write_index(Path(out))
    return Call(
        result=KernelResult(
            value=dict(derived.value),
            evidence=Evidence(
                terms=MappingProxyType({"out": out}),
                measurements=MappingProxyType({}),
                observed=MappingProxyType(
                    {"delegated_to": "orchestrator.rebuild_index", "written": "true"}
                ),
            ),
            reason=None,
        )
    )


#: What this module registers, as data. Each entry is
#: ``(operation, handler, positional, flags)``:
#:
#: - ``positional`` is the argument a bare token binds to, because §9 names a
#:   command's subject as an argument rather than a flag (``store put <file>``);
#: - ``flags`` are the port parameters the command reads, which is the half of the
#:   1:1 contract the contract test compares against the port signature.
COMMANDS: Final[tuple[tuple[str, Handler, str | None, tuple[str, ...]], ...]] = (
    ("put", put, "file", ("--media-type", "--root")),
    ("get", get, "sha256", ("--save", "--root")),
    ("verify", verify, "sha256", ("--root",)),
    ("ls", ls, "", ("--prefix", "--root")),
    ("ledger-read", ledger_read, "unit", ("--root",)),
    ("manifest-rebuild", manifest_rebuild, "out", ()),
)
