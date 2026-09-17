"""Build ``manifest.json``: a basic inventory of the committed fixture files.

Basic data only — path, folder, name, extension, size and content hash, all read
from the filesystem with the standard library. Nothing here measures what a file
*contains*: that needs PyMuPDF and Pillow, and a manifest that costs more to
regenerate than to read is a manifest nobody regenerates.

Two kinds of file are left out, and the difference matters:

- **Deliberate non-fixtures** — the Python sources in this folder: this script
  and its test — are *recorded* in ``excluded``, so the inventory plus the
  exclusion list accounts for the whole folder.
- **Debris** — cache directories, hidden/OS entries, and this script's own
  output — is *skipped without a record*. It appears and disappears on its own,
  so recording it would make the manifest differ between two runs and between a
  macOS and a Linux checkout. A manifest that flickers is not a check.

The output is deterministic: the same fixtures produce a byte-identical file.
Nothing that changes on its own — a timestamp, a tool version, an mtime, a
directory-iteration order — is recorded, so regenerate-and-diff is a usable
check, which is what ``test_manifest.py`` does.

Anything left over in the folder is a fixture by definition. If that is wrong,
the folder has the wrong thing in it, and the manifest is where it shows up.

This is an **inventory, not a golden set**: it records no expected content.
``docs/plans/README.md`` §6 defers the labelled golden set over deviation D4 (a
set labelled by the model that produced it is circular), so this file is
verified material and nothing more.

Run from the repository root::

    python tests/fixtures/build_manifest.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
from typing import TypedDict

#: Suffixes left out of the inventory, mapped to the reason recorded for them.
#: Excluding by *rule* rather than by name: a list of names is forgotten the
#: moment a new generator is dropped next to the fixtures it produces.
EXCLUDED_SUFFIXES: dict[str, str] = {".py": "python_source"}

#: Directory names skipped whole, and the reason. Skipped, not recorded: a cache
#: is not a claim about the fixtures.
EXCLUDED_DIRECTORIES: dict[str, str] = {"__pycache__": "cache"}

#: Bytes read per chunk while hashing. The fixtures include 4 MB photographs, so
#: the digest is computed in chunks rather than by reading whole files.
_CHUNK_BYTES = 1 << 20

_HERE = pathlib.Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[1]


class FixtureRecord(TypedDict):
    """One inventoried fixture file."""

    path: str
    folder: str
    name: str
    extension: str
    bytes: int
    sha256: str


class ExcludedPath(TypedDict):
    """One deliberate non-fixture left out of the inventory."""

    path: str
    reason: str


class Manifest(TypedDict):
    """The inventory written to ``manifest.json``."""

    root: str
    files: int
    bytes: int
    by_folder: dict[str, dict[str, int]]
    excluded: list[ExcludedPath]
    entries: list[FixtureRecord]


def _exclusion_reason(path: pathlib.Path, root: pathlib.Path) -> str | None:
    """Return why ``path`` is not a fixture, or ``None`` if it is one.

    The order is load-bearing. Containment in a cache directory is decided
    before the suffix rule, because the two rules overlap: a Python file inside
    ``__pycache__`` matches both, and answering ``python_source`` would be a
    claim about what the file *is*, made about a file in a cache directory.
    Hidden entries are judged on any path part, not only on the file name, so a
    dot-directory is skipped along with its contents.

    Args:
        path: Candidate file, inside ``root``.
        root: Directory being inventoried.

    Returns:
        The reason, or ``None`` when the file is a fixture.
    """
    parts = path.relative_to(root).parts
    for part in parts:
        if part in EXCLUDED_DIRECTORIES:
            return EXCLUDED_DIRECTORIES[part]
    if any(part.startswith(".") for part in parts):
        return "hidden"
    return EXCLUDED_SUFFIXES.get(path.suffix.lower())


def _sha256(path: pathlib.Path) -> str:
    """Return the hexadecimal SHA-256 of ``path``, read in chunks.

    Args:
        path: File to hash.

    Returns:
        Sixty-four hexadecimal characters.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _record(path: pathlib.Path, root: pathlib.Path) -> FixtureRecord:
    """Return the inventory record for one fixture file.

    Args:
        path: Fixture file, inside ``root``.
        root: Directory being inventoried.

    Returns:
        The record, with ``path`` and ``folder`` relative to ``root``.
    """
    relative = path.relative_to(root)
    return {
        "path": relative.as_posix(),
        "folder": relative.parent.as_posix(),
        "name": path.stem,
        "extension": path.suffix.lower().lstrip("."),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _scan(
    root: pathlib.Path, output: pathlib.Path
) -> tuple[list[FixtureRecord], list[ExcludedPath]]:
    """Split ``root`` into inventoried records and recorded exclusions.

    Args:
        root: Directory being inventoried.
        output: The manifest's own path, resolved; skipped without a record.

    Returns:
        The records and the exclusions, both in path order.
    """
    entries: list[FixtureRecord] = []
    excluded: list[ExcludedPath] = []
    for path in sorted(root.rglob("*")):
        if path.is_dir() or path.resolve() == output:
            continue
        reason = _exclusion_reason(path, root)
        if reason is None:
            entries.append(_record(path, root))
        elif reason in EXCLUDED_SUFFIXES.values():
            excluded.append(
                {"path": path.relative_to(root).as_posix(), "reason": reason}
            )
    return entries, excluded


def _by_folder(entries: list[FixtureRecord]) -> dict[str, dict[str, int]]:
    """Return the file count and byte total of each fixture folder.

    Args:
        entries: The inventoried records.

    Returns:
        One ``{"files": ..., "bytes": ...}`` bucket per folder, folder-sorted.
    """
    folders: dict[str, list[FixtureRecord]] = {}
    for entry in entries:
        folders.setdefault(entry["folder"], []).append(entry)
    return {
        folder: {
            "files": len(group),
            "bytes": sum(item["bytes"] for item in group),
        }
        for folder, group in sorted(folders.items())
    }


def build(root: pathlib.Path, output: pathlib.Path) -> Manifest:
    """Return the inventory of ``root``, leaving ``output`` out of it.

    Args:
        root: Directory holding the fixture files.
        output: Path the manifest is written to; skipped, so the inventory never
            lists its own output.

    Returns:
        The manifest, with every count and total derived from ``entries``.
    """
    entries, excluded = _scan(root, output.resolve())
    return {
        "root": pathlib.Path(os.path.relpath(root, _REPO_ROOT)).as_posix(),
        "files": len(entries),
        "bytes": sum(entry["bytes"] for entry in entries),
        "by_folder": _by_folder(entries),
        "excluded": excluded,
        "entries": entries,
    }


def main(argv: list[str] | None = None) -> int:
    """Write the manifest and print a one-line summary.

    Args:
        argv: Command-line arguments; ``None`` reads ``sys.argv``.

    Returns:
        The process exit code: ``0`` on success.
    """
    parser = argparse.ArgumentParser(description="Inventory the fixture files.")
    parser.add_argument("--root", type=pathlib.Path, default=_HERE)
    parser.add_argument("--out", type=pathlib.Path, default=_HERE / "manifest.json")
    args = parser.parse_args(argv)
    manifest = build(args.root, args.out)
    args.out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(
        f"{args.out}: {manifest['files']} files, {manifest['bytes']} bytes, "
        f"{len(manifest['excluded'])} excluded"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
