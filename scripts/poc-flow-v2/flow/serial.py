"""Serialisation of the data contract: dataclasses to and from JSON.

One owner for the shape (`my_flow.md` B.15): the artifacts are written by
:func:`encode` and read back by the ``*_from_dict`` functions here. A second
encoder elsewhere would be a second source of truth about the same form.

The helpers mirror `scripts/poc-flow/flow/persist.py`, reduced to the types the
run process persists in Fase A: `FieldResult`, `FieldDecision`, `FieldCandidate`
and `EvidenceSignal`. Fase B ports the rest of the engine on top of the same
shapes and needs no change here.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Mapping
from typing import Any

from .fields import (
    EvidenceSignal,
    FieldCandidate,
    FieldDecision,
    FieldResult,
)

__all__: list[str] = [
    "encode",
    "jsonable",
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
