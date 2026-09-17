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
from typing import Final

from docflow.adapters.store import FilesystemStore
from docflow.kernel_cli.commands.refusals import answered
from docflow.kernel_cli.main import Call, Handler


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

    Args:
        unit: The unit directory holding the ledger.
        root: The store root. K7 reads a ledger *file*, so the unit directory is
            what it is given; the root is accepted because §10 scopes it to K7.
        **_: See :func:`put`.

    Returns:
        The call, carrying the ledger.

    """
    del root
    return Call(result=_store().read_ledger(Path(unit)))


def manifest_rebuild(*, out: str, **_: object) -> Call:
    """Rebuild the manifest, through K7's delegating method.

    Args:
        out: The run's output root.
        **_: See :func:`put`.

    Returns:
        The call, carrying what K1's `rebuild_index()` returned.

    """
    return Call(result=_store().rebuild_manifest(Path(out)))


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
