"""Serialisation of the data contract: dataclasses to and from JSON.

One owner for the shape (`my_flow.md` B.15): the artifacts are written by
:func:`encode` and read back by the ``*_from_dict`` functions here. A second
encoder elsewhere would be a second source of truth about the same form.

The helpers cover the types the run process persists: `FieldResult`,
`FieldDecision`, `FieldCandidate` and `EvidenceSignal`.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Mapping
from typing import Any

from .fields import (
    EvidenceSignal,
    Extraction,
    FieldCandidate,
    FieldDecision,
    FieldResult,
)
from .hitl import HumanConfirmation, PendingItem
from .material import Material

__all__: list[str] = [
    "confirmation_from_dict",
    "confirmation_to_dict",
    "encode",
    "extraction_from_dict",
    "extraction_to_dict",
    "jsonable",
    "material_from_dict",
    "material_to_dict",
    "pending_from_dict",
    "pending_to_dict",
    "result_from_dict",
    "result_to_dict",
]


def jsonable(value: object) -> object:
    """Normalise a value for JSON: dataclasses become dicts, tuples and
    frozensets become lists, Paths their string form.

    Sets are **sorted** before conversion: their iteration order depends on hash
    randomisation, and a signature built from an unsorted set would differ
    between runs (`my_flow.md` B.5).
    """
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {key: jsonable(val) for key, val in dataclasses.asdict(value).items()}
    if isinstance(value, (frozenset, set)):
        return [jsonable(item) for item in sorted(value, key=repr)]
    if isinstance(value, (tuple, list)):
        return [jsonable(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): jsonable(val) for key, val in value.items()}
    return value


def encode(payload: object) -> bytes:
    """Serialise an artifact: UTF-8, non-ASCII left as-is, indented (`B.6`)."""
    return json.dumps(jsonable(payload), ensure_ascii=False, indent=2).encode("utf-8")


# --- the data contract, to and from JSON --------------------------------


def _signal_to_dict(signal: EvidenceSignal) -> dict[str, object]:
    return {
        "family": signal.family,
        "result": signal.result,
        "points": signal.points,
        "detail": signal.detail,
        "verified": signal.verified,
    }


def _signal_from_dict(data: Mapping[str, Any]) -> EvidenceSignal:
    return EvidenceSignal(
        family=str(data["family"]),
        result=str(data["result"]),
        points=int(data["points"]),
        detail=str(data["detail"]),
        verified=bool(data.get("verified", False)),
    )


def _candidate_to_dict(candidate: FieldCandidate) -> dict[str, object]:
    return {
        "normalized_value": candidate.normalized_value,
        "raw_value": candidate.raw_value,
        "producers": list(candidate.producers),
        "signals": [_signal_to_dict(signal) for signal in candidate.signals],
        "hard_refutations": list(candidate.hard_refutations),
    }


def _candidate_from_dict(data: Mapping[str, Any]) -> FieldCandidate:
    return FieldCandidate(
        normalized_value=str(data["normalized_value"]),
        raw_value=str(data["raw_value"]),
        producers=list(data["producers"]),
        signals=[_signal_from_dict(signal) for signal in data["signals"]],
        hard_refutations=list(data["hard_refutations"]),
    )


def _decision_to_dict(decision: FieldDecision) -> dict[str, object]:
    return {
        "field": decision.field,
        "severity": decision.severity,
        "decision": decision.decision,
        "reason_codes": list(decision.reason_codes),
        "winner": (
            _candidate_to_dict(decision.winner) if decision.winner is not None else None
        ),
        "runner_up": (
            _candidate_to_dict(decision.runner_up)
            if decision.runner_up is not None
            else None
        ),
        "score": decision.score,
        "margin": decision.margin,
        "threshold": decision.threshold,
        "strong": list(decision.strong),
        "gate_satisfied": decision.gate_satisfied,
        "notes": list(decision.notes),
    }


def _decision_from_dict(data: Mapping[str, Any]) -> FieldDecision:
    winner = data.get("winner")
    runner_up = data.get("runner_up")
    return FieldDecision(
        field=str(data["field"]),
        severity=str(data["severity"]),
        decision=str(data["decision"]),
        reason_codes=list(data["reason_codes"]),
        winner=(_candidate_from_dict(winner) if isinstance(winner, Mapping) else None),
        runner_up=(
            _candidate_from_dict(runner_up) if isinstance(runner_up, Mapping) else None
        ),
        score=int(data["score"]),
        margin=int(data["margin"]),
        threshold=int(data["threshold"]),
        strong=tuple(data["strong"]),
        gate_satisfied=bool(data["gate_satisfied"]),
        notes=list(data["notes"]),
    )


def result_to_dict(result: FieldResult) -> dict[str, object]:
    """The engine's answer as a plain object, for the `decide` artifact."""
    return {
        "decisions": {
            field: _decision_to_dict(decision)
            for field, decision in result.decisions.items()
        },
        "trace": {
            field: [_candidate_to_dict(c) for c in produced]
            for field, produced in result.trace.items()
        },
        "extracted": dict(result.extracted),
        "notes": list(result.notes),
    }


def result_from_dict(data: Mapping[str, Any]) -> FieldResult:
    """Rebuild the engine's answer from the `decide` artifact."""
    return FieldResult(
        decisions={
            str(field): _decision_from_dict(decision)
            for field, decision in data["decisions"].items()
        },
        trace={
            str(field): [_candidate_from_dict(c) for c in produced]
            for field, produced in data["trace"].items()
        },
        extracted={str(key): str(value) for key, value in data["extracted"].items()},
        notes=list(data["notes"]),
    )


def extraction_to_dict(extraction: Extraction) -> dict[str, object]:
    """The `extract` stage's artifact as a plain object."""
    return {
        "candidates": {
            field: [_candidate_to_dict(c) for c in produced]
            for field, produced in extraction.candidates.items()
        },
        "values": dict(extraction.values),
        "notes": list(extraction.notes),
    }


def extraction_from_dict(data: Mapping[str, Any]) -> Extraction:
    """Rebuild the `extract` stage's artifact."""
    return Extraction(
        candidates={
            str(field): [_candidate_from_dict(c) for c in produced]
            for field, produced in data["candidates"].items()
        },
        values={str(key): str(value) for key, value in data["values"].items()},
        notes=list(data["notes"]),
    )


def _pending_to_dict(item: PendingItem) -> dict[str, object]:
    return {
        "field": item.field,
        "severity": item.severity,
        "decision": item.decision,
        "reason_codes": list(item.reason_codes),
        "winner": (
            _candidate_to_dict(item.winner) if item.winner is not None else None
        ),
        "runner_up": (
            _candidate_to_dict(item.runner_up) if item.runner_up is not None else None
        ),
    }


def _pending_from_dict(data: Mapping[str, Any]) -> PendingItem:
    winner = data.get("winner")
    runner_up = data.get("runner_up")
    return PendingItem(
        field=str(data["field"]),
        severity=str(data["severity"]),
        decision=str(data["decision"]),
        reason_codes=list(data["reason_codes"]),
        winner=(_candidate_from_dict(winner) if isinstance(winner, Mapping) else None),
        runner_up=(
            _candidate_from_dict(runner_up) if isinstance(runner_up, Mapping) else None
        ),
    )


def pending_to_dict(items: list[PendingItem]) -> dict[str, object]:
    """The `hitl` stage's artifact as a plain object."""
    return {"pending": [_pending_to_dict(item) for item in items]}


def pending_from_dict(data: Mapping[str, Any]) -> list[PendingItem]:
    """Rebuild the `hitl` stage's queue."""
    raw = data.get("pending")
    if not isinstance(raw, list):
        return []
    return [_pending_from_dict(entry) for entry in raw if isinstance(entry, Mapping)]


def confirmation_to_dict(confirmation: HumanConfirmation) -> dict[str, object]:
    """A settled value as a plain object."""
    return {
        "field": confirmation.field,
        "value": confirmation.value,
        "note": confirmation.note,
    }


def confirmation_from_dict(data: Mapping[str, Any]) -> HumanConfirmation:
    """Rebuild a settled value."""
    return HumanConfirmation(
        field=str(data["field"]),
        value=str(data["value"]),
        note=str(data.get("note", "")),
    )


def material_to_dict(material: Material) -> dict[str, object]:
    """The `read` stage's artifact, without the image bytes.

    The rendered pages are written as files beside the artifact (`images/`), so
    the JSON carries their count, not their bytes — a material with megabytes of
    base64 inline is the artifact nobody opens.
    """
    return {
        "kind": material.kind,
        "tier": material.tier,
        "text": material.text,
        "route": material.route,
        "pages_read": material.pages_read,
        "pages_total": material.pages_total,
        "image_count": len(material.images),
        "notes": list(material.notes),
    }


def material_from_dict(data: Mapping[str, Any]) -> Material:
    """Rebuild the `read` stage's artifact, with no images (they live on disk)."""
    return Material(
        kind=str(data["kind"]),
        tier=str(data["tier"]),
        text=str(data["text"]) if data.get("text") is not None else None,
        route=str(data["route"]),
        pages_read=int(data["pages_read"]),
        pages_total=int(data["pages_total"])
        if data.get("pages_total") is not None
        else None,
        images=[],
        notes=list(data["notes"]),
    )
