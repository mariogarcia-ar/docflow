"""Locate the workspace and make the `docflow` adapters importable.

The `docflow` package lives under ``src/`` (`pyproject.toml`), so the import is
always ``docflow.…``. The `pythonpath = ["src"]` setting applies to `pytest` and
nothing else, so a standalone library that calls the adapters directly must put
``src/`` on `sys.path` itself — exactly as `scripts/poc/_lib.py::bootstrap` does.

This module is deliberately small and depends only on the standard library, so
it can be imported before `docflow` resolves.
"""

from __future__ import annotations

import pathlib
import sys

#: The repository root. This file lives at `scripts/poc-flow-v2/flow/`, so the
#: root is three parents up.
REPO_ROOT: pathlib.Path = pathlib.Path(__file__).resolve().parents[3]

#: Where the `docflow` package physically lives.
SRC: pathlib.Path = REPO_ROOT / "src"

#: Where the flow's registry content lives (`registry/` at the repo root). The
#: assets themselves are read through K8 (`docflow.kernels.registry`), never by
#: path; this is only the root the loader is handed (`my_flow.md` B.15).
REGISTRY_ROOT: pathlib.Path = REPO_ROOT / "registry"


def ensure_docflow_importable() -> None:
    """Put ``src/`` on ``sys.path`` so ``import docflow`` resolves.

    Idempotent: calling it twice is harmless. It is the one place in this
    package that touches ``sys.path``, so the adapters stay a dependency of the
    caller and never of a module that only needs the standard library.
    """
    text = str(SRC)
    if text not in sys.path:
        sys.path.insert(0, text)
