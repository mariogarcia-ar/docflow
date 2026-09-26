"""Filesystem and import-graph assertions shared by the per-processor test suites.

Three questions more than one suite asks, and none of the answers belongs to one processor:

* *was this input rewritten?* — the digest of the source file, before and after a run;
* *what did the run publish?* — every file below a directory, as paths relative to it;
* *what does this module import?* — the import graph, which is what both the "no processor imports
  another processor" rule and the "nothing under ``src/`` imports ``tests/``" rule are about.

They live here rather than in one suite because more than one suite asks them, and a copy per suite
is the copy-paste this project's DRY rule forbids. Nothing under ``src/docflow/`` imports this
module: it is test infrastructure, not a component.
"""

from __future__ import annotations

import ast
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


def imported_modules(path: Path) -> list[tuple[int, str]]:
    """Return every module ``path`` imports, with the line that imports it.

    The module is read statically rather than executed: a production module that imports a fake has
    already turned one into a fallback by the time an executed check could observe it, and a test
    that imports an engine has already stopped proving anything about the engine's absence.

    Args:
        path: The Python module to read.

    Returns:
        ``(line, module)`` pairs, in source order, for both ``import x`` and ``from x import y``.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        found.extend((node.lineno, name) for name in names)
    return found
