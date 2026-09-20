"""Progress reporting to stderr.

The flow's JSON verdict lives on stdout; progress belongs on stderr, where an
operator reading a console can follow it without corrupting the answer. This
module is the single owner of the verbose switch: a caller configures it once,
and every stage emits through :func:`emit`, which is a no-op when verbosity is
off.

Besides the live lines, the module keeps an ordered **step trace**: every stage
that ran or was reused, in the order it happened. :func:`summary` prints that
trace at the end, so an operator can read back the exact path the run took and
check it was the intended one.

Nothing here imports `docflow`, so it is importable before `src/` is on
``sys.path``.
"""

from __future__ import annotations

import sys

__all__: list[str] = [
    "configure",
    "emit",
    "is_verbose",
    "reused",
    "step",
    "summary",
]

_VERBOSE: bool = False

#: One entry of the step trace: ``(name, action, detail)``, in the order the
#: steps happened. ``action`` is ``"ran"`` when the stage executed, ``"reused"``
#: when its artifact was loaded from the work root.
_STEPS: list[tuple[str, str, str]] = []


def configure(verbose: bool) -> None:
    """Turn verbose output on or off, for this process.

    Args:
        verbose: Whether the live lines and the final summary should be written.

    """
    # pylint: disable=global-statement
    global _VERBOSE  # one process-wide switch, set once by the entry point.
    _VERBOSE = verbose
    if not verbose:
        _STEPS.clear()


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
    """Record and announce a stage that **ran**, with its result.

    Args:
        name: The stage or step name.
        detail: The stage's result, appended after the name.

    """
    if not _VERBOSE:
        return
    _STEPS.append((name, "ran", detail))
    line = f"== {name}"
    if detail:
        line += f": {detail}"
    print(line, file=sys.stderr)


def reused(name: str, detail: str = "") -> None:
    """Record and announce a stage whose artifact was **loaded**, not re-run.

    Args:
        name: The stage name.
        detail: What was loaded.

    """
    if not _VERBOSE:
        return
    _STEPS.append((name, "reused", detail))
    line = f"{name}: loaded from work root"
    if detail:
        line += f" ({detail})"
    print(line, file=sys.stderr)


def summary() -> None:
    """Print the step trace at the end, so the run's path is reviewable.

    Each line is the numbered step, its action and its result. The trace is what
    answers *did the flow take the intended path*: the sequence, and which
    stages were reused instead of run.
    """
    if not _VERBOSE or not _STEPS:
        return
    print("== summary", file=sys.stderr)
    for index, (name, action, detail) in enumerate(_STEPS, start=1):
        line = f"{index:2}. {name:<9} {action:<7}"
        if detail:
            line += f" {detail}"
        print(line, file=sys.stderr)
