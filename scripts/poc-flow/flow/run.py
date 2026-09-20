"""The top-level flow: read, extract, decide — as separable stages.

`my_flow.md` §1 names the chain:

    read material (§2) → extract candidates (§4) → decide fields (§6) → queue (§8)

This module exposes **one function per stage** plus two entry points:

- :func:`run` — the whole chain, the existing API, unchanged.
- :func:`run_stage` — run **one** named stage, resolving its dependencies first
  from the work root when they are missing, or forcing a re-run when asked.

The separation is what makes a single stage callable: the stages were already
the units the work root persists; this module only stops gluing them into one
function. Each stage's inputs are the previous stage's artifacts, so a stage on
its own either loads what it needs or runs what it needs first — which is what
:data:`~.persist.STAGE_DEPENDENCIES` declares.

What it deliberately does **not** do yet, marked for the next step:

- the resolver → engine loop (§7) and its 2-loop cap;
- learning, templates and audit sampling (§9).
"""

from __future__ import annotations

import pathlib

from ._bootstrap import ensure_docflow_importable
from .artifacts import Artifacts, load_artifacts
from .config import DEFAULT_CONFIG, Config
from .engine import DecisionContext, evaluate
from .extract import Extraction, extract
from .fields import DECISION_CONFIRMED, FieldResult
from .hitl import (
    HumanConfirmation,
    apply_confirmations,
    pending_items,
    suggest,
)
from .material import TIER_DEGRADED, Material, read_material
from .persist import (
    CONFIRMED_NAME,
    RESOLUTION_NAME,
    STAGE_DECIDE,
    STAGE_DEPENDENCIES,
    STAGE_EXTRACT,
    STAGE_HITL,
    STAGE_READ,
    WorkTree,
    document_digest,
    stage_artifact,
    work_signature,
)
from .progress import artifact, configure, emit, outcome, reused, step

__all__: list[str] = [
    "STAGE_DECIDE",
    "STAGE_EXTRACT",
    "STAGE_HITL",
    "STAGE_READ",
    "run",
    "run_stage",
]


def _record(tree: WorkTree | None, stage: str) -> None:
    """Attach a stage's artifact paths to its trace entry.

    Only when a work root exists: without one the stage wrote nothing, and naming
    a file that was never written is worse than naming none.
    """
    if tree is not None:
        artifact(*stage_artifact(tree.root, stage))


def _open_tree(  # pylint: disable=too-many-arguments, too-many-positional-arguments
    path: pathlib.Path,
    work_root: pathlib.Path,
    config: Config,
    own_cuits: frozenset[str],
    artifacts: Artifacts,
    *,
    redo: bool,
) -> WorkTree:
    """Open the work tree, announcing what a previous run left behind."""
    tree = WorkTree(
        work_root,
        work_signature(config, own_cuits, artifacts),
        document_digest(path),
        redo=redo,
    )
    tree.announce()
    return tree


def _ensure_material(
    path: pathlib.Path,
    config: Config,
    tree: WorkTree | None,
) -> Material:
    """Read the material, loading it from the work root when already done."""
    material: Material | None = None
    if tree is not None and tree.done(STAGE_READ):
        material = tree.load_material()
        if material is not None:
            reused("read", material.tier)
            outcome(f"{material.tier} · route {material.route or '—'}")
            _record(tree, STAGE_READ)
    if material is None:
        step("read", path.name)
        material = read_material(path, config)
        emit(
            f"read: tier={material.tier} route={material.route!r} "
            f"pages={material.pages_read}"
        )
        if tree is not None:
            tree.save_material(material)
        outcome(
            f"{material.tier} · route {material.route or '—'} · "
            f"{material.pages_read}/{material.pages_total or '?'} page(s)"
        )
        _record(tree, STAGE_READ)
    return material


def _ensure_extraction(
    material: Material,
    config: Config,
    artifacts: Artifacts,
    tree: WorkTree | None,
) -> Extraction:
    """Extract candidates, loading them from the work root when already done."""
    extraction: Extraction | None = None
    if tree is not None and tree.done(STAGE_EXTRACT):
        extraction = tree.load_extraction()
        if extraction is not None:
            reused("extract", f"{len(extraction.candidates)} field(s)")
            outcome(f"{len(extraction.candidates)} field(s) with candidates")
            _record(tree, STAGE_EXTRACT)
    if extraction is None:
        step("extract", f"{len(material.text or '')} chars of text")
        extraction = extract(material, config, artifacts)
        emit(f"extract: {len(extraction.candidates)} field(s) with candidates")
        if tree is not None:
            tree.save_extraction(extraction)
        outcome(
            f"{len(extraction.candidates)} field(s) with candidates"
            + (f" · {len(extraction.notes)} note(s)" if extraction.notes else "")
        )
        _record(tree, STAGE_EXTRACT)
    return extraction


def _run_read(
    path: pathlib.Path,
    config: Config,
    tree: WorkTree | None,
) -> Material:
    """Stage 1: read the document into material."""
    return _ensure_material(path, config, tree)


def _run_extract(
    path: pathlib.Path,
    config: Config,
    artifacts: Artifacts,
    tree: WorkTree | None,
) -> Extraction:
    """Stage 2: produce candidates from the material (reading it first)."""
    material = _ensure_material(path, config, tree)
    return _ensure_extraction(material, config, artifacts, tree)


def _run_decide(  # pylint: disable=too-many-arguments, too-many-positional-arguments
    path: pathlib.Path,
    config: Config,
    artifacts: Artifacts,
    own_cuits: frozenset[str],
    tree: WorkTree | None,
) -> tuple[FieldResult, Material]:
    """Stage 3: score candidates into per-field decisions (extracting first)."""
    material = _ensure_material(path, config, tree)
    if material.tier == TIER_DEGRADED:
        # Nothing was read, so there is nothing to decide.
        return (
            FieldResult(
                decisions={},
                trace={},
                extracted={},
                notes=list(material.notes) or ["the document could not be read"],
            ),
            material,
        )

    extraction = _ensure_extraction(material, config, artifacts, tree)
    step("decide", f"{len(extraction.candidates)} field(s)")
    ctx = DecisionContext(config=config, tier=material.tier, own_cuits=own_cuits)
    decisions = evaluate(extraction.candidates, ctx, extraction.values)

    extracted = {
        field: decision.winner.raw_value
        for field, decision in decisions.items()
        if decision.decision == DECISION_CONFIRMED and decision.winner is not None
    }

    emit(
        f"decide: {len(decisions)} decided, {len(extracted)} confirmed, "
        f"{len(decisions) - len(extracted)} not confirmed"
    )

    result = FieldResult(
        decisions=decisions,
        trace=extraction.candidates,
        extracted=extracted,
        notes=list(extraction.notes),
    )
    if tree is not None:
        tree.save_result(result)
    outcome(
        f"{len(decisions)} field(s) decided · {len(extracted)} confirmed · "
        f"{len(decisions) - len(extracted)} pending"
    )
    _record(tree, STAGE_DECIDE)
    return result, material


def _run_hitl(  # pylint: disable=too-many-arguments, too-many-positional-arguments, too-many-locals
    path: pathlib.Path,
    config: Config,
    artifacts: Artifacts,
    own_cuits: frozenset[str],
    tree: WorkTree | None,
    *,
    resolve: bool,
    confirm: list[HumanConfirmation] | None,
) -> FieldResult:
    """Stage 4: queue the unconfirmed fields, suggest, and settle by a human."""
    result, material = _run_decide(path, config, artifacts, own_cuits, tree)

    queued = pending_items(result.decisions)
    notes: list[str] = list(result.notes)

    step("hitl", f"{len(queued)} field(s) pending")
    if tree is not None:
        tree.save_pending(queued)
        _record(tree, STAGE_HITL)

    if queued and resolve and tree is not None:
        step("resolve", f"{len(queued)} field(s) to the frontier")
        suggestions, note = suggest(queued, material, config, path.name)
        tree.save_resolution(suggestions, note)
        artifact(tree.root / RESOLUTION_NAME)
        if note:
            notes.append(f"frontier: {note}")
            emit(f"resolve: {note}")
            outcome(f"frontier refused: {note}")
        else:
            notes.append(
                f"frontier suggested {len(suggestions)} value(s); confirmation "
                "is still a human's"
            )
            emit(f"resolve: {len(suggestions)} suggestion(s)")
            outcome(f"{len(suggestions)} suggestion(s), none of them a verdict")

    if queued and tree is None:
        notes.append(
            f"{len(queued)} field(s) need human review: "
            f"{', '.join(item.field for item in queued)}"
        )

    outcome(f"{len(queued)} field(s) queued for a human")

    extracted = dict(result.extracted)
    if confirm:
        pending_by_field = {item.field: item for item in queued}
        settled, refusals = apply_confirmations(confirm, pending_by_field)
        step("confirm", f"{len(settled)} accepted, {len(refusals)} refused")
        if tree is not None:
            # Only the accepted ones are ground truth; a refused confirmation is
            # an out-of-band edit and must not leak into `confirmed.json`.
            tree.save_confirmations([c for c in confirm if c.field in settled])
            artifact(tree.root / CONFIRMED_NAME)
        extracted.update(settled)
        for refusal in refusals:
            notes.append(f"confirmation refused: {refusal}")
            emit(f"confirm: refused {refusal}")
        if settled:
            notes.append(
                f"{len(settled)} field(s) settled by a human: "
                f"{', '.join(sorted(settled))}"
            )
            emit(f"confirm: settled {', '.join(sorted(settled))}")
        outcome(f"{len(settled)} field(s) settled by a human · {len(refusals)} refused")

    final = FieldResult(
        decisions=result.decisions,
        trace=result.trace,
        extracted=extracted,
        notes=notes,
    )
    if tree is not None:
        tree.save_result(final)
    return final


def run(  # pylint: disable=too-many-arguments
    path: pathlib.Path,
    config: Config = DEFAULT_CONFIG,
    *,
    own_cuits: frozenset[str] = frozenset(),
    work_root: pathlib.Path | None = None,
    redo: bool = False,
    resolve: bool = False,
    confirm: list[HumanConfirmation] | None = None,
    verbose: bool = False,
) -> FieldResult:
    """Process one document and return the engine's per-field decisions.

    The whole chain — read, extract, decide, queue — the same surface as
    before. When ``work_root`` is given, each stage's artifact is written there
    as it completes and a second run resumes at the first unfinished stage.

    Args:
        path: The document to process (PDF or image).
        config: The run's dials.
        own_cuits: The business's own CUITs (digits only), for the fixed
            own-CUIT-as-emisor veto.
        work_root: Where the intermediate artifacts and the journal live. When
            ``None``, nothing is persisted and the flow is a single pass.
        redo: Ignore the journal and re-run every stage.
        resolve: Ask the frontier model to suggest an answer for each pending
            field (§8). The suggestion is evidence, never a verdict.
        confirm: A human's settled values for the pending fields (§8, I6).
        verbose: Print progress to stderr as each stage runs.

    Returns:
        The decisions, the candidate trace and the confirmed extractions.

    """
    ensure_docflow_importable()
    configure(verbose)
    artifacts = load_artifacts()

    tree: WorkTree | None = None
    if work_root is not None:
        tree = _open_tree(path, work_root, config, own_cuits, artifacts, redo=redo)

    result = _run_hitl(
        path,
        config,
        artifacts,
        own_cuits,
        tree,
        resolve=resolve,
        confirm=confirm,
    )
    return result


def run_stage(  # pylint: disable=too-many-arguments, too-many-locals
    stage: str,
    path: pathlib.Path,
    config: Config = DEFAULT_CONFIG,
    *,
    own_cuits: frozenset[str] = frozenset(),
    work_root: pathlib.Path | None = None,
    redo: bool = False,
    resolve: bool = False,
    confirm: list[HumanConfirmation] | None = None,
    with_dependencies: bool = True,
    verbose: bool = False,
) -> FieldResult:
    """Run **one** named stage and return its result.

    A stage's dependencies are its inputs. With ``with_dependencies=True`` (the
    default), a missing input is produced first — running ``decide`` on a fresh
    work root first runs ``read`` then ``extract``. With
    ``with_dependencies=False``, a missing input raises instead of a silent
    re-run.

    Args:
        stage: One of ``read``, ``extract``, ``decide``, ``hitl``.
        path: The document to process.
        config: The run's dials.
        own_cuits: The business's own CUITs, for the own-CUIT veto.
        work_root: Where the artifacts and the journal live.
        redo: Re-run the requested stage even when its artifact exists, and
            invalidate everything downstream of it.
        resolve: For the ``hitl`` stage: ask the frontier to suggest.
        confirm: For the ``hitl`` stage: a human's settled values.
        with_dependencies: Produce missing inputs first. When ``False``, a
            missing dependency raises.
        verbose: Print progress to stderr as the stage runs.

    Returns:
        The result of the requested stage. For ``read`` and ``extract`` this is
        a :class:`FieldResult` with an empty decision set, because the material
        and the candidates are intermediate, not final.

    Raises:
        ValueError: If ``stage`` is not one of the four names.
        LookupError: If ``with_dependencies=False`` and an input is missing.

    """
    ensure_docflow_importable()
    configure(verbose)
    if stage not in STAGE_DEPENDENCIES:
        raise ValueError(
            f"unknown stage {stage!r}; choose from {list(STAGE_DEPENDENCIES)}"
        )

    artifacts = load_artifacts()
    tree: WorkTree | None = None
    if work_root is not None:
        tree = _open_tree(path, work_root, config, own_cuits, artifacts, redo=redo)

    # Re-running an intermediate stage invalidates its own artifact and
    # everything downstream, so a stale `decision.json` is never trusted.
    if tree is not None and redo:
        tree.clear_from(stage)

    if not with_dependencies:
        if tree is None:
            raise LookupError(f"stage {stage!r} without dependencies needs a work root")
        for dependency in STAGE_DEPENDENCIES[stage]:
            if not tree.done(dependency):
                raise LookupError(
                    f"stage {stage!r} needs {dependency!r}, which is not done; "
                    "run with dependencies, or run the dependency first"
                )

    if stage == STAGE_READ:
        material = _run_read(path, config, tree)
        return FieldResult(
            decisions={}, trace={}, extracted={}, notes=list(material.notes)
        )

    if stage == STAGE_EXTRACT:
        extraction = _run_extract(path, config, artifacts, tree)
        return FieldResult(
            decisions={},
            trace=extraction.candidates,
            extracted={},
            notes=list(extraction.notes),
        )

    if stage == STAGE_DECIDE:
        result, _material = _run_decide(path, config, artifacts, own_cuits, tree)
        return result

    # stage == STAGE_HITL
    return _run_hitl(
        path,
        config,
        artifacts,
        own_cuits,
        tree,
        resolve=resolve,
        confirm=confirm,
    )
