"""Progress reporting to stderr.

The flow's JSON verdict lives on stdout; progress belongs on stderr, where an
operator reading a console can follow it without corrupting the answer. This
module is the single owner of the verbose switch: a caller configures it once,
and every stage emits through :func:`emit`, which is a no-op when verbosity is
off.

Nothing here imports `docflow`, so it is importable before `src/` is on
``sys.path``.
"""

from __future__ import annotations

import sys

__all__: list[str] = [
    "configure",
    "emit",
    "is_verbose",
    "step",
]

_VERBOSE: bool = False


def configure(verbose: bool) -> None:
    """Turn verbose output on or off, for this process.

    Args:
        verbose: Whether :func:`emit` and :func:`step` should write to stderr.

    """
    # pylint: disable=global-statement
    global _VERBOSE  # one process-wide switch, set once by the entry point.
    _VERBOSE = verbose


def is_verbose() -> bool:
    """Whether verbose output is on."""
    return _VERBOSE


def emit(message: str) -> None:
    """Write one progress line to stderr, only when verbosity is on.

    Args:
        message: The line to write.

    """
    if _VERBOSE:
        print(message, file=sys.stderr)


def step(name: str, detail: str = "") -> None:
    """Write a stage marker, distinguishing it from a plain step.

    Args:
        name: The stage or step name.
        detail: Optional detail, appended after the name.

    """
    if not _VERBOSE:
        return
    line = f"== {name}"
    if detail:
        line += f": {detail}"
    print(line, file=sys.stderr)
