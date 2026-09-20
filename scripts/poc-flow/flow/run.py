"""The top-level flow: read, extract, decide.

This is the one function a caller needs. It wires the three stages in
`my_flow.md` §1:

    read material (§2) → extract candidates (§4) → decide fields (§6)

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
from .fields import DECISION_CONFIRMED, DECISION_ESCALATE, FieldResult
from .material import TIER_DEGRADED, Material, read_material

__all__: list[str] = ["run"]


def run(
    path: pathlib.Path,
    config: Config = DEFAULT_CONFIG,
    *,
    own_cuits: frozenset[str] = frozenset(),
) -> FieldResult:
    """Process one document and return the engine's per-field decisions.

    Args:
        path: The document to process (PDF or image).
        config: The run's dials.
        own_cuits: The business's own CUITs (digits only), for the fixed
            own-CUIT-as-emisor veto. Empty means *not configured*, which the
            validator reports as UNKNOWN rather than a silent PASS.

    Returns:
        The decisions, the candidate trace and the confirmed extractions.

    """
    ensure_docflow_importable()
    artifacts = load_artifacts()

    material: Material = read_material(path, config)

    if material.tier == TIER_DEGRADED:
        # Nothing was read, so there is nothing to decide. Every field the
        # caller might have asked about is answered with the degraded reason.
        return FieldResult(
            decisions={},
            trace={},
            extracted={},
            notes=list(material.notes) or ["the document could not be read"],
        )

    extraction: Extraction = extract(material, config, artifacts)

    ctx = DecisionContext(config=config, tier=material.tier, own_cuits=own_cuits)
    decisions = evaluate(extraction.candidates, ctx, extraction.values)

    extracted = {
        field: decision.winner.raw_value
        for field, decision in decisions.items()
        if decision.decision == DECISION_CONFIRMED and decision.winner is not None
    }

    notes: list[str] = list(extraction.notes)
    escalated = [
        field
        for field, decision in decisions.items()
        if decision.decision == DECISION_ESCALATE
    ]
    if escalated:
        # TODO: [MVP] `my_flow.md` §8: an ESCALATE decision should run the
        # resolver → lane-on-demand → frontier chain here, not just be named.
        notes.append(
            f"fields to escalate to the frontier: {', '.join(sorted(escalated))}"
        )

    return FieldResult(
        decisions=decisions,
        trace=extraction.candidates,
        extracted=extracted,
        notes=notes,
    )
