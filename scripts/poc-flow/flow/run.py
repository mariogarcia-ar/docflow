"""The top-level flow: read, extract, decide.

This is the one function a caller needs. It wires the three stages in
`my_flow.md` §1:

    read material (§2) → extract candidates (§4) → decide fields (§6)

Each stage's artifact is written to a work root as it completes, so a run that
fails at any point can be **resumed** at the first unfinished stage instead of
re-paying for the language-model calls. The journal and the intermediate
artifacts are owned by :mod:`.persist`.

What it deliberately does **not** do yet, marked for the next step:

- the resolver → engine loop (§7) and its 2-loop cap;
- the frontier escalation (§8) — an ESCALATE decision is returned as-is;
- learning, templates and audit sampling (§9).

Each of those is a TODO below, tagged exactly where it belongs.
"""

from __future__ import annotations

import pathlib

from ._bootstrap import ensure_docflow_importable
from .artifacts import load_artifacts
from .config import DEFAULT_CONFIG, Config
from .engine import DecisionContext, evaluate
from .extract import Extraction, extract
from .fields import DECISION_CONFIRMED, FieldResult
from .hitl import pending_items, suggest
from .material import TIER_DEGRADED, Material, read_material
from .persist import WorkTree, document_digest, work_signature

__all__: list[str] = ["run"]


def run(  # pylint: disable=too-many-arguments, too-many-locals, too-many-branches
    path: pathlib.Path,
    config: Config = DEFAULT_CONFIG,
    *,
    own_cuits: frozenset[str] = frozenset(),
    work_root: pathlib.Path | None = None,
    redo: bool = False,
    resolve: bool = False,
) -> FieldResult:
    """Process one document and return the engine's per-field decisions.

    The local count is the pipeline itself — read, extract, decide, queue — and
    each stage's inputs are the previous stage's outputs; splitting it into
    helpers would move the same count one frame away while hiding the order that
    matters, the same shape `extract.extract` documents.

    When ``work_root`` is given, each stage's artifact is written there as it
    completes and a second run resumes at the first unfinished stage. The
    journal covers the document's own bytes and the run's settings, so a changed
    input or a changed dial discards the journal rather than trusting it.

    Args:
        path: The document to process (PDF or image).
        config: The run's dials.
        own_cuits: The business's own CUITs (digits only), for the fixed
            own-CUIT-as-emisor veto. Empty means *not configured*, which the
            validator reports as UNKNOWN rather than a silent PASS.
        work_root: Where the intermediate artifacts and the journal live. When
            ``None``, nothing is persisted and the flow is a single pass.
        redo: Ignore the journal and re-run every stage.
        resolve: Ask the frontier model to suggest an answer for each field the
            engine could not confirm (§8). The suggestion is evidence, never a
            verdict; the queue is written either way.

    Returns:
        The decisions, the candidate trace and the confirmed extractions.

    """
    ensure_docflow_importable()
    artifacts = load_artifacts()

    tree: WorkTree | None = None
    if work_root is not None:
        tree = WorkTree(
            work_root,
            work_signature(config, own_cuits, artifacts),
            document_digest(path),
            redo=redo,
        )
        tree.announce()

    material: Material | None = None
    if tree is not None and tree.done("read"):
        material = tree.load_material()

    if material is None:
        material = read_material(path, config)
        if tree is not None:
            tree.save_material(material)

    if material.tier == TIER_DEGRADED:
        # Nothing was read, so there is nothing to decide. Every field the
        # caller might have asked about is answered with the degraded reason.
        return FieldResult(
            decisions={},
            trace={},
            extracted={},
            notes=list(material.notes) or ["the document could not be read"],
        )

    extraction: Extraction | None = None
    if tree is not None and tree.done("extract"):
        extraction = tree.load_extraction()

    if extraction is None:
        extraction = extract(material, config, artifacts)
        if tree is not None:
            tree.save_extraction(extraction)

    ctx = DecisionContext(config=config, tier=material.tier, own_cuits=own_cuits)
    decisions = evaluate(extraction.candidates, ctx, extraction.values)

    extracted = {
        field: decision.winner.raw_value
        for field, decision in decisions.items()
        if decision.decision == DECISION_CONFIRMED and decision.winner is not None
    }

    notes: list[str] = list(extraction.notes)

    # --- HITL (§8): queue the fields the engine could not confirm ---------
    queued = pending_items(decisions)
    if tree is not None:
        tree.save_pending(queued)
        if queued and resolve:
            suggestions, note = suggest(queued, material, config, path.name)
            tree.save_resolution(suggestions, note)
            if note:
                notes.append(f"frontier: {note}")
            elif suggestions:
                notes.append(
                    f"frontier suggested {len(suggestions)} value(s); confirmation "
                    "is still a human's"
                )
    elif queued:
        notes.append(
            f"{len(queued)} field(s) need human review: "
            f"{', '.join(item.field for item in queued)}"
        )

    result = FieldResult(
        decisions=decisions,
        trace=extraction.candidates,
        extracted=extracted,
        notes=notes,
    )

    if tree is not None:
        tree.save_result(result)

    return result
