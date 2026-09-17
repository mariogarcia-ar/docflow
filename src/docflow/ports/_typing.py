"""Static predicates shared by the import-isolation tests.

The five port modules and the adapters behind them are checked by a *static*
assertion rather than a prose claim: importing any module under
``docflow/ports/`` must not import any module under ``docflow/adapters/``
(``E04-01``, `ADR-004`). The dependency arrow only ever points down, and that is
what makes the reuse claim structural instead of stylistic.

Why this is a module and not a helper inside a test
---------------------------------------------------

The check has to be provable **independently of the real modules importing**.
If the predicate lived inside a test body, the only way to falsify it would be
to mutate the real ``docflow/ports/`` tree — and a mutation that makes a port
import an adapter can also make the port unimportable, in which case the test
module fails at *collection* and the helper under test never runs at all. The
predicate therefore takes a **source string**, so a test can feed it a synthetic
adversary and assert that the offender is named.

``plan-01-kernels.md`` §7b — *"Adapter isolation"*: the test is the import check
plus a fake adapter satisfying each port, and breaking it looks like *"an adapter
is imported from a port; the arrow stops pointing down"*.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator

__all__ = ["ADAPTER_PACKAGE", "imported_package_paths", "is_adapter_import"]

#: The package no port module may import from. The rule is stated once, here.
ADAPTER_PACKAGE: str = "docflow.adapters"

#: The final dotted segment that identifies the adapter package, so a *relative*
#: import (``from ..adapters import docling``) is caught as readily as an
#: absolute one (``from docflow.adapters import docling``).
_ADAPTER_SEGMENT: str = "adapters"


def _dotted_paths(node: ast.ImportFrom) -> Iterator[str]:
    """Rebuild the dotted paths an ``ImportFrom`` names, dots included.

    ``node.module`` is ``None`` for ``from . import x`` and drops the leading
    dots for a relative import, so the level is re-attached here. The imported
    **names** are appended as well, because Python offers three spellings of the
    same illegal import and only one of them puts the package in ``module``:

    - ``from docflow.adapters import docling`` - in ``module``;
    - ``from ..adapters.docling import DoclingEngine`` - in ``module``;
    - ``from docflow import adapters`` - in ``names``.

    A helper that read only ``module`` would report clean on the third, which is
    why the alias names are part of the path rather than discarded.

    Args:
        node: The ``ImportFrom`` node.

    Yields:
        One dotted path per imported name, with relative dots preserved.

    """
    prefix = "." * node.level + ((node.module + ".") if node.module else "")

    yield from (prefix + alias.name for alias in node.names)


def imported_package_paths(source: str) -> Iterator[str]:
    """Yield the dotted module path of every import a source declares.

    Relative dots are preserved, so a caller can distinguish an absolute import
    from a relative one without losing the segments that identify the target.
    One path is yielded per imported name, so ``from docflow import adapters``
    yields ``docflow.adapters`` rather than ``docflow``.

    Args:
        source: Python source text. A synthetic string is as valid as a file.

    Yields:
        The dotted module path of each ``import`` and ``from ... import`` node.

    Raises:
        SyntaxError: If ``source`` is not parseable Python.

    """
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            yield from _dotted_paths(node)


def is_adapter_import(module_path: str) -> bool:
    """Report whether a dotted module path reaches the adapter package.

    Two forms are recognized, because both are real ways to write the illegal
    import: the absolute path (``docflow.adapters.ollama``) and any path whose
    segments include the package, which is what catches the relative spelling
    (``..adapters.docling.DoclingEngine``) and the ``from package import module``
    one (``docflow.adapters``).

    The match is on whole segments, never on a substring: ``docflow.adaptersomething``
    is not the adapter package, and a check built on ``"adapters" in path`` would
    be silently wrong in exactly the case it exists to catch.

    Args:
        module_path: A dotted module path, as ``imported_package_paths`` yields.

    Returns:
        ``True`` when the path names the adapter package or something inside it.

    """
    if module_path == ADAPTER_PACKAGE or module_path.startswith(ADAPTER_PACKAGE + "."):
        return True

    segments = [segment for segment in module_path.split(".") if segment]

    return _ADAPTER_SEGMENT in segments
