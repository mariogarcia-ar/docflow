"""The run process: drive the stages over one document, with a record.

This is the heart of Fase A: the four stages run in order, each one persisted
and marked in the journal only when its artifact is written, each step recorded
into the trace, and the whole path written to `run.json` at the end. Fase B1
wires the real decision engine into `decide` and `hitl`; `read` and `extract`
are still the deferred stages, now returning the real contracts.

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

from .artifacts import load_artifacts
from .classify import classify
from .config import DEFAULT_CONFIG, Config
from .control import CONTROL_PAUSED, CONTROL_STOPPED
from .engine import DecisionContext, evaluate
from .extract import extract
from .fields import (
    DECISION_CONFIRMED,
    ESC_DEGRADED_MATERIAL,
    Extraction,
    FieldResult,
)
from .hitl import pending_items
from .lane import needs_vision_lane
from .material import TIER_DEGRADED, Material, read_material
from .progress import StepTrace, artifact, configure, emit, outcome, reused, step, trace
from .record import RunRecord
from .resolve import resolver_loop
from .stages import (
    STAGE_DECIDE,
    STAGE_DEPENDENCIES,
    STAGE_EXTRACT,
    STAGE_HITL,
    STAGE_READ,
    STAGES,
    StageInput,
    stage_artifact,
)
from .work import WorkTree

#: A stage's function: it takes its input and returns the value its artifact
#: will hold.
StageFunc = Callable[[StageInput], object]


@dataclasses.dataclass(frozen=True, slots=True)
class RunOutcome:
    """What a run produced, so the caller can print or persist it.

    Attributes:
        result: The engine's field result.
        steps: The trace of the run, in order.

    """

    result: FieldResult
    steps: tuple[StepTrace, ...]


def _material_tier(material: object) -> str:
    """The tier a `read` artifact declares, defaulting to the OCR tier."""
    if isinstance(material, Material):
        return material.tier
    if isinstance(material, Mapping) and isinstance(material.get("tier"), str):
        return str(material["tier"])
    return "escaneado_ocr"


def _own_cuits(settings: Mapping[str, object]) -> frozenset[str]:
    """The business's own CUITs, digits only, from the run's settings."""
    raw = settings.get("own_cuits")
    if not isinstance(raw, (frozenset, set, list, tuple)):
        return frozenset()
    return frozenset(str(value) for value in raw)


def ladder_step(result: FieldResult) -> bool | None:
    """One step of the Anexo A ladder: does a lane still have to run?

    The pure half (which fields need a lane) lives in `lane.py`; the render
    itself is deferred (`# TODO: [MVP]`) — a native-text material carries no
    pages until one is rendered, and that adapter call is the missing piece.
    Until then the step reports the need honestly rather than pretending the
    ladder ran.

    It is a module-level function rather than a closure so the *decision* is
    testable without an adapter: a closure can only be reached through a full
    `decide` stage, which is how the caller's answer came to be unguarded.

    Args:
        result: The engine's current decisions.

    Returns:
        ``None`` when no critical field needs a lane — the ladder does not apply,
        so the loop records no reason code. ``False`` when a lane is needed and
        the deferred render could not produce it: that *is* a stopped loop, and
        `ESC_NO_NEW_EVIDENCE` names it.

    """
    needed = needs_vision_lane(result.decisions)
    if not needed:
        return None
    result.notes.append(
        f"lane-on-demand deferred: {', '.join(sorted(needed))} "
        "still lack strong evidence"
    )
    return False


def decide_stage(inputs: StageInput) -> FieldResult:
    """Stage `decide`: score the extraction's candidates with the real engine."""
    config: Config = DEFAULT_CONFIG
    extraction: object = inputs.deps.get(STAGE_EXTRACT)
    if not isinstance(extraction, Extraction):
        return FieldResult(
            decisions={},
            trace={},
            extracted={},
            notes=["decide ran without an extraction to score"],
        )
    material = inputs.deps.get(STAGE_READ)
    context = DecisionContext(
        config=config,
        tier=_material_tier(material),
        own_cuits=_own_cuits(inputs.settings),
    )

    def decide_once() -> FieldResult:
        decisions = evaluate(extraction.candidates, context, extraction.values)
        extracted = {
            field: decision.winner.raw_value
            for field, decision in decisions.items()
            if decision.decision == DECISION_CONFIRMED and decision.winner is not None
        }
        return FieldResult(
            decisions=decisions,
            trace=extraction.candidates,
            extracted=extracted,
            notes=list(extraction.notes),
        )

    result = resolver_loop(decide_once, ladder_step, max_loops=config.max_loops)
    return result


def hitl_stage(inputs: StageInput) -> list[object]:
    """Stage `hitl`: queue every field the engine did not confirm."""
    result: object = inputs.deps.get(STAGE_DECIDE)
    if not isinstance(result, FieldResult):
        return []
    return list(pending_items(result.decisions))


def _read_stage(inputs: StageInput) -> object:
    """Stage `read`: the real material, read through the adapters."""
    return read_material(inputs.path)


def _extract_stage(inputs: StageInput) -> object:
    """Stage `extract`: the real extraction over the read material.

    Two gates run first, and they are different facts that must not collapse
    into one (`my_flow.md` §2, §3, B.9):

    - **The material is degraded** — `read` could not read it at all. §2 says a
      degraded material escalates directly, so it short-circuits here with its
      own reason code. Asking `classify` about empty text would report *"not a
      receipt"*, which is a claim about a document nobody managed to read.
    - **The text is not a receipt** — `classify`'s cheap rules (§3). The
      document was read and is not a receipt, which is a finding about it.

    Either way no model is paid, and the reason is a note — never a fake answer.
    """
    material: object = inputs.deps.get(STAGE_READ)
    if not isinstance(material, Material):
        return Extraction(
            candidates={}, values={}, notes=["no material to extract from"]
        )
    if material.tier == TIER_DEGRADED:
        why = "; ".join(material.notes) or "no reason recorded by the read"
        return Extraction(
            candidates={},
            values={},
            notes=[ESC_DEGRADED_MATERIAL, f"degraded material: {why}"],
        )
    decision = classify(material.text or "")
    if not decision.proceeds:
        return Extraction(
            candidates={},
            values={},
            notes=[decision.code, f"classified out: {decision.reason}"],
        )
    return extract(material, DEFAULT_CONFIG, load_artifacts())


#: The four stages in order, with the function that implements each.
_STAGES: tuple[tuple[str, StageFunc], ...] = (
    (STAGE_READ, _read_stage),
    (STAGE_EXTRACT, _extract_stage),
    (STAGE_DECIDE, decide_stage),
    (STAGE_HITL, hitl_stage),
)


def _run_one(
    stage: str,
    func: StageFunc,
    inputs: StageInput,
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

    step(stage, inputs.document)
    value = func(inputs)
    written = tree.save_artifact(stage, value)
    tree.journal.mark(stage)
    outcome(_ran_detail(stage, value))
    artifact(*written)


def _reuse_detail(stage: str, tree: WorkTree) -> str:
    """What to say about a reused stage: name the artifact it came from."""
    names = ", ".join(path.name for path in stage_artifact(tree.root, stage))
    return f"reused from {names}"


def _ran_detail(stage: str, value: object) -> str:
    """A one-line account of a stage that ran.

    Every branch reports something **measured**. The literal fallback is the
    only unmeasured answer, so no stage that has a value worth describing may
    reach it — `read` in particular: `my_flow.md` B.12 says a cut is not a
    silent cut, and a degraded read reported as the bare word "ran" is exactly
    the silence that rule forbids.
    """
    if isinstance(value, FieldResult):
        count = len(value.decisions)
        confirmed = sum(
            1
            for decision in value.decisions.values()
            if decision.decision == DECISION_CONFIRMED
        )
        return f"{count} field(s) decided, {confirmed} confirmed"
    if isinstance(value, Extraction):
        return f"{len(value.candidates)} field(s) with candidates"
    if isinstance(value, Material):
        return _material_detail(value)
    if isinstance(value, list):
        return f"{len(value)} field(s) pending"
    return f"{stage} ran"


def _material_detail(material: Material) -> str:
    """What `read` measured: its tier and route, or why it could not read."""
    if material.tier == TIER_DEGRADED:
        why = material.notes[0] if material.notes else "no reason recorded"
        return f"degraded: {why}"
    pages = (
        f"{material.pages_read}/{material.pages_total}"
        if material.pages_total is not None
        else f"{material.pages_read}"
    )
    return f"{material.tier} via {material.route!r}, {pages} page(s)"


def _result_of(tree: WorkTree) -> FieldResult:
    """The field result: the decide artifact, or an empty one when absent."""
    decide = tree.load_artifact(STAGE_DECIDE)
    if isinstance(decide, FieldResult):
        return decide
    return FieldResult(decisions={}, trace={}, extracted={}, notes=[])


def _result_without_tree() -> FieldResult:
    """The result of an unpersisted run: nothing persisted, nothing decided."""
    return FieldResult(decisions={}, trace={}, extracted={}, notes=[])


def _stage_input(
    tree: WorkTree | None,
    stage: str,
    document: pathlib.Path,
    settings: Mapping[str, object],
) -> StageInput:
    """The inputs a stage receives: its dependency artifacts, already loaded."""
    deps: dict[str, object] = {}
    if tree is not None:
        for dependency in STAGE_DEPENDENCIES.get(stage, ()):
            loaded = tree.load_artifact(dependency)
            if loaded is not None:
                deps[dependency] = loaded
    return StageInput(
        document=document.name,
        path=document,
        settings=settings,
        deps=deps,
    )


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
    artifacts = load_artifacts()
    signature_settings = dict(settings)
    signature_settings["registry"] = artifacts.signature
    tree: WorkTree | None = None
    if work_root is not None:
        tree = WorkTree.open(work_root, document, signature_settings)
        tree.journal.announce()
        if redo:
            tree.journal.clear_from(STAGES[0])

    if tree is not None and stop:
        tree.write_control(CONTROL_STOPPED)

    for stage, func in _STAGES:
        inputs = _stage_input(tree, stage, document, settings)
        if tree is None:
            step(stage, document.name)
            func(inputs)
            continue
        _run_one(stage, func, inputs, tree, redo=redo)
        if pause or stop:
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
