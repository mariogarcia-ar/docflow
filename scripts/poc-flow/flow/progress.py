"""Progress reporting: live lines to stderr, and the run's path as data.

The flow's report lives on stdout; progress belongs on stderr, where an
operator reading a console can follow it without corrupting the answer. This
module is the single owner of the verbose switch: a caller configures it once,
and every stage emits through :func:`emit`, which is a no-op when verbosity is
off.

Besides the live lines, the module keeps an ordered **step trace**: every stage
that ran or was reused, in the order it happened, with its result and the files
it wrote. :func:`trace` hands that back as data, so a caller can print the path
the run took and name the file an operator has to open next — instead of
dumping the run's JSON and leaving both answers to be read out of it.

Nothing here imports `docflow`, so it is importable before `src/` is on
``sys.path``.
"""

from __future__ import annotations

import dataclasses
import pathlib
import sys

__all__: list[str] = [
    "StepTrace",
    "artifact",
    "configure",
    "emit",
    "is_verbose",
    "outcome",
    "reused",
    "step",
    "trace",
]


@dataclasses.dataclass(frozen=True, slots=True)
class StepTrace:
    """One entry of the run's path: what happened, and what it left behind.

    Attributes:
        name: The stage or step name.
        action: ``"ran"`` when the step executed, ``"reused"`` when its artifact
            was loaded from the work root.
        detail: The step's result, e.g. ``"16 decided, 2 confirmed"``.
        artifacts: The files the step wrote or reused, as printable paths.

    """

    name: str
    action: str
    detail: str
    artifacts: tuple[str, ...]


_VERBOSE: bool = False

#: The steps, in the order they happened. Recorded whether or not verbosity is
#: on: the trace is the report's path section, not a verbose extra.
_STEPS: list[StepTrace] = []


def configure(verbose: bool) -> None:
    """Turn verbose output on or off and start a fresh trace.

    Args:
        verbose: Whether the live lines should be written to stderr. The trace
            is recorded either way.

    """
    # pylint: disable=global-statement
    global _VERBOSE  # one process-wide switch, set once by the entry point.
    _VERBOSE = verbose
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
    """Record and announce a step that **ran**, with its initial detail.

    Args:
        name: The stage or step name.
        detail: What the step started with, e.g. the document's name.

    """
    _STEPS.append(StepTrace(name=name, action="ran", detail=detail, artifacts=()))
    if _VERBOSE:
        line = f"== {name}"
        if detail:
            line += f": {detail}"
        print(line, file=sys.stderr)


def reused(name: str, detail: str = "") -> None:
    """Record and announce a step whose artifact was **loaded**, not re-run.

    Args:
        name: The stage name.
        detail: What was loaded.

    """
    _STEPS.append(StepTrace(name=name, action="reused", detail=detail, artifacts=()))
    if _VERBOSE:
        line = f"{name}: loaded from work root"
        if detail:
            line += f" ({detail})"
        print(line, file=sys.stderr)


def outcome(text: str) -> None:
    """Set the last step's result, once its work is done.

    Args:
        text: The result, in the same words the report will show.

    """
    if not _STEPS:
        return
    _STEPS[-1] = dataclasses.replace(_STEPS[-1], detail=text)
    if _VERBOSE:
        print(f"   {text}", file=sys.stderr)


def artifact(*paths: pathlib.Path | str) -> None:
    """Attach the files a step wrote to its trace entry.

    The report names these paths, so an operator knows which file to open
    instead of having to look them up in the work root. A duplicate is dropped:
    naming the same file twice adds nothing.

    Args:
        *paths: The files, as paths or printable strings.

    """
    if not _STEPS or not paths:
        return
    kept = list(_STEPS[-1].artifacts)
    for path in paths:
        rendered = str(path)
        if rendered not in kept:
            kept.append(rendered)
    _STEPS[-1] = dataclasses.replace(_STEPS[-1], artifacts=tuple(kept))


def trace() -> tuple[StepTrace, ...]:
    """The run's path in order: what ran, what was reused, what it wrote."""
    return tuple(_STEPS)
