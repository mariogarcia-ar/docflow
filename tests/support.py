"""Filesystem assertions shared by the per-processor test suites.

Two questions every processor's end-to-end tests ask, and neither answer belongs to one
processor:

* *was this input rewritten?* — the digest of the source file, before and after a run;
* *what did the run publish?* — every file below a directory, as paths relative to it.

They live here rather than in one suite because both suites ask them, and a copy per suite is
the copy-paste this project's DRY rule forbids. Nothing under ``src/docflow/`` imports this
module: it is test infrastructure, not a component.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_of(path: Path) -> str:
    """Return the digest of a file, so a test can prove it was not rewritten.

    Args:
        path: The file to hash.

    Returns:
        Its SHA-256, in hexadecimal.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def files_under(directory: Path) -> set[str]:
    """Return every file below ``directory``, as paths relative to it.

    Args:
        directory: The directory to walk.

    Returns:
        The relative, POSIX-style paths of its files; an empty set when it holds none.
    """
    return {
        path.relative_to(directory).as_posix()
        for path in directory.rglob("*")
        if path.is_file()
    }
