"""The run process: drive the stages over one document, with a record.

This is the heart of Fase A: the four stages run in order, each one persisted
and marked in the journal only when its artifact is written, each step recorded
into the trace, and the whole path written to `run.json` at the end. The stages
themselves are stubs — the process is real.

The process answers the three questions `plan/README.md` makes the definition
of "correct" (`my_flow.md` B.1-B.6, B.14):

1. **Where did the document go?** — the trace, `ran` vs `reused`, per step.
2. **What was decided?** — the artifacts each stage wrote, kept on disk.
3. **How does it resume?** — the journal marks; a later run starts at the first
   unfinished stage.

Pause and stop are states written **between stages**: a run that is asked to
pause finishes the stage in flight, marks it, writes the state, and stops — so
the journal never describes a half-written stage.
"""

from __future__ import annotations

import dataclasses
import pathlib
from collections.abc import Callable, Mapping

from .control import CONTROL_PAUSED, CONTROL_STOPPED
from .fields import FieldResult
from .progress import StepTrace, artifact, configure, emit, outcome, reused, step, trace
from .record import RunRecord
from .stages import (
    STAGE_DECIDE,
    STAGE_EXTRACT,
    STAGE_HITL,
    STAGE_READ,
    STAGES,
    stage_artifact,
)
from .stubs import StubContext, stub_decide, stub_extract, stub_hitl, stub_read
from .work import WorkTree

__all__: list[str] = [
    "STAGE_DECIDE",
    "STAGE_EXTRACT",
    "STAGE_HITL",
    "STAGE_READ",
    "RunOutcome",
    "run",
]


#: A stage's function: it takes a context and returns the value its artifact
#: will hold. Fase B replaces the stubs with the real libraries behind the same
#: signature.
StageFunc = Callable[[StubContext], object]


@dataclasses.dataclass(frozen=True, slots=True)
class RunOutcome:
    """What a run produced, so the caller can print or persist it.

    Attributes:
        result: The engine's field result (the stub's, in Fase A).
        steps: The trace of the run, in order.

    """

    result: FieldResult
    steps: tuple[StepTrace, ...]


#: The four stages in order, with the stub that implements each in Fase A.
_STAGES: tuple[tuple[str, StageFunc], ...] = (
    (STAGE_READ, stub_read),
    (STAGE_EXTRACT, stub_extract),
    (STAGE_DECIDE, stub_decide),
    (STAGE_HITL, stub_hitl),
)


def _run_one(
    stage: str,
    func: StageFunc,
    context: StubContext,
    tree: WorkTree,
    *,
    redo: bool,
) -> None:
    """Run or reuse one stage, recording the step and marking the journal.

    A stage is reused only when the journal says it is done **and** its
    artifact is on disk; a missing artifact means the mark cannot be trusted and
    the stage runs again. The mark is written only after the artifact is.
    """
    if tree.journal.done(stage) and not redo and tree.load_artifact(stage) is not None:
        reused(stage, "")
        outcome(_reuse_detail(stage, tree))
        artifact(*stage_artifact(tree.root, stage))
        return

    step(stage, f"{context.document}")
    value = func(context)
    written = tree.save_artifact(stage, value)
    tree.journal.mark(stage)
    outcome(_ran_detail(stage, value))
    artifact(*written)


def _reuse_detail(stage: str, tree: WorkTree) -> str:
    """What to say about a reused stage: name the artifact it came from."""
    names = ", ".join(path.name for path in stage_artifact(tree.root, stage))
    return f"reused from {names}"


def _ran_detail(stage: str, value: object) -> str:
    """What to say about a stage that ran: a one-line account of its value."""
    del value
    return f"{stage} ran"


def _result_of(tree: WorkTree) -> FieldResult:
    """The field result: the decide artifact, or an empty one when absent."""
    decide = tree.load_artifact(STAGE_DECIDE)
    if isinstance(decide, FieldResult):
        return decide
    return FieldResult(decisions={}, trace={}, extracted={}, notes=[])


def _result_without_tree() -> FieldResult:
    """The result of an unpersisted run: the decide stub's answer."""
    return stub_decide(StubContext(document="", work_root=None))


def run(  # pylint: disable=too-many-arguments, too-many-positional-arguments
    document: pathlib.Path,
    settings: Mapping[str, object],
    *,
    work_root: pathlib.Path | None = None,
    redo: bool = False,
    pause: bool = False,
    stop: bool = False,
    verbose: bool = False,
) -> RunOutcome:
    """Run the four stages over one document, persisting as it goes.

    Args:
        document: The document to process.
        settings: The run's dials, folded into the journal signature.
        work_root: Where the artifacts and the record live; when ``None`` the
            run is a single pass with nothing persisted.
        redo: Ignore the journal and re-run every stage.
        pause: Stop after the current stage completes, journal intact.
        stop: Stop after the current stage completes, journal intact, and
            leave the control state `stopped`.
        verbose: Print progress to stderr.

    Returns:
        The field result and the step trace.

    """
    configure(verbose)
    tree: WorkTree | None = None
    if work_root is not None:
        tree = WorkTree.open(work_root, document, settings)
        tree.journal.announce()
        if redo:
            tree.journal.clear_from(STAGES[0])

    context = StubContext(
        document=str(document),
        work_root=str(work_root) if work_root is not None else None,
    )

    if tree is not None and stop:
        tree.write_control(CONTROL_STOPPED)

    for stage, func in _STAGES:
        if tree is None:
            step(stage, context.document)
            func(context)
            continue
        _run_one(stage, func, context, tree, redo=redo)
        if pause or stop:
            # The stage in flight finished and was marked; now honour the
            # requested stop, which is exactly the boundary a resume needs.
            if pause:
                tree.write_control(CONTROL_PAUSED)
            break

    result = _result_of(tree) if tree is not None else _result_without_tree()
    steps = trace()
    if tree is not None:
        tree.save_record(
            RunRecord(
                document=document.name,
                digest=tree.journal.digest,
                signature=tree.journal.signature,
                steps=list(steps),
            )
        )
    emit(f"run: {len(steps)} step(s) recorded")
    return RunOutcome(result=result, steps=steps)


def _result_without_tree() -> FieldResult:
    """The result of an unpersisted run: the decide stub's answer."""
    return stub_decide(StubContext(document="", work_root=None))
