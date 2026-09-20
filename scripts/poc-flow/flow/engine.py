"""The decision engine: the MoE consensus of `my_flow.md` §6.

Each field receives candidates and signals from several experts; this engine
combines the signals into a score per candidate instead of counting votes.

The invariants enforced here, concretely:

- **I2** — candidates are merged by ``normalized_value`` *before* scoring.
- **I3** — a hard refutation vetoes a candidate; no score compensates it.
- **I4** — one signal per family: within a family only the highest PASS counts,
  and a FAIL in a family is a soft refutation, never an addition.
- **I10** — UNKNOWN scores nothing and never vetoes.

The engine is pure over its inputs: it imports no adapter, so every rule is
testable with constructed candidates.
"""

from __future__ import annotations

from collections.abc import Mapping

from .config import (
    DEFAULT_CONFIG,
    ESCALATE_FLOOR,
    FAMILY_POINTS,
    Config,
    FieldDial,
)
from .fields import (
    DECISION_CONFIRMED,
    DECISION_ESCALATE,
    DECISION_REVIEW,
    FAIL,
    PASS,
    EvidenceSignal,
    FieldCandidate,
    FieldDecision,
    merge_candidates,
    severity_for,
)
from .validators import arithmetic_signal, cuit_signal, date_signal

__all__: list[str] = [
    "DecisionContext",
    "decide_field",
    "evaluate",
]

#: The fields the deterministic validators apply to, and their rule. A field
#: outside this mapping carries no deterministic signal — its gate then needs a
#: cross-lane or native-anchor signal to close, which is exactly Anexo A.
_VALIDATOR_FIELDS: frozenset[str] = frozenset({"cuit_emisor", "fecha_emision"})


# `too-few-public-methods`: `DecisionContext` is a bundle of dials handed to a
# pure decision function, not a class with behaviour; see the note on
# `Material`.
# pylint: disable=too-few-public-methods


class DecisionContext:
    """The run's dials, bundled for a pure decision.

    Attributes:
        config: The run's configuration.
        tier: The material tier (``texto_nativo`` / ``escaneado_ocr`` /
            ``degradado``).
        own_cuits: The business's own CUITs, digits only.
        validator_fields: The fields a deterministic validator applies to.
        veto_codes: The closed veto list; a FAIL whose detail is not in it is a
            soft refutation.

    """

    def __init__(
        self,
        *,
        config: Config = DEFAULT_CONFIG,
        tier: str,
        own_cuits: frozenset[str],
    ) -> None:
        self.config = config
        self.tier = tier
        self.own_cuits = own_cuits
        self.validator_fields = _VALIDATOR_FIELDS
        self.veto_codes = config.veto_codes


def _points(config: Config, family: str) -> int:
    return config.family_points.get(family, FAMILY_POINTS.get(family, 0))


def _validator_signals(
    field: str,
    candidate: FieldCandidate,
    ctx: DecisionContext,
) -> list[EvidenceSignal]:
    """The deterministic signals a field's candidate earns, if the field has a
    validator.

    These apply to the merged value, so they run once per candidate rather than
    once per producer.
    """
    if field not in ctx.validator_fields:
        return []
    config = ctx.config
    if field == "cuit_emisor":
        return [
            cuit_signal(
                candidate.raw_value,
                own_cuits=ctx.own_cuits,
                family_points=config.family_points,
            )
        ]
    if field == "fecha_emision":
        return [date_signal(candidate.raw_value, family_points=config.family_points)]
    return []


def _attach_arithmetic(
    field: str,
    candidate: FieldCandidate,
    values: Mapping[str, str],
    ctx: DecisionContext,
) -> list[EvidenceSignal]:
    """The arithmetic signal for the total/IVA/subtotal combination.

    The rule refutes a combination, not a field (`my_flow.md` §6.4): when the
    three values are all present and consistent, the total and the IVA each get
    the +3; when they are all present and inconsistent, the combination is
    vetoed. A missing component yields UNKNOWN.
    """
    if field not in {"total", "iva"}:
        return []
    sub = values.get("subtotal", "")
    tax = values.get("iva", "")
    tot = values.get("total", "")
    # Only the candidate that matches the chosen total gets the signal; the
    # others are left to the ordinary scoring.
    if candidate.raw_value != values.get(field, ""):
        return []
    signal = arithmetic_signal(sub, tax, tot, family_points=ctx.config.family_points)
    return [signal]


def _family_score(signals: list[EvidenceSignal]) -> int:
    """One candidate's score, one signal per family.

    Within a family only the highest PASS counts (I4). A FAIL in a family is a
    soft refutation of ``-2`` — unless the signal's detail names a veto code, in
    which case the caller has already removed it. UNKNOWN contributes nothing.
    """
    best_positive: dict[str, int] = {}
    soft: dict[str, int] = {}
    for signal in signals:
        if signal.result == PASS:
            best_positive[signal.family] = max(
                best_positive.get(signal.family, 0), signal.points
            )
        elif signal.result == FAIL:
            soft[signal.family] = -2
    return sum(best_positive.values()) + sum(soft.values())


def _hard_refutations(
    signals: list[EvidenceSignal], veto_codes: frozenset[str]
) -> list[str]:
    """The FAIL signals whose detail names a veto code, in stable order."""
    found: list[str] = []
    for signal in signals:
        if (
            signal.result == FAIL
            and signal.detail in veto_codes
            and signal.detail not in found
        ):
            found.append(signal.detail)
    return found


def _threshold(dial: FieldDial, tier: str) -> int:
    """The confirmation floor for a severity at a tier."""
    return dial.t_native if tier == "texto_nativo" else dial.t_ocr


def _strong_for(dial: FieldDial) -> tuple[str, ...]:
    """The strong-evidence families a severity's gate requires."""
    return dial.strong


def _gate_met(signals: list[EvidenceSignal], strong: tuple[str, ...]) -> bool:
    """Whether the candidate's signals close the strong-evidence gate."""
    if not strong:
        return True
    families = {signal.family for signal in signals if signal.result == PASS}
    return any(family in families for family in strong)


def decide_field(  # pylint: disable=too-many-locals
    field: str,
    candidates: list[FieldCandidate],
    ctx: DecisionContext,
    values: Mapping[str, str],
) -> FieldDecision:
    """Decide one field from its candidates and the run's dials.

    The local count is the decision itself — merge, veto, score, gate — and each
    step pushes the previous one out of scope, the same shape `docling.py::read`
    documents for its own ordered pipeline.

    Args:
        field: The field name.
        candidates: The unmerged candidates the producers handed in.
        ctx: The run's dials.
        values: The document-level values (subtotal, IVA, total), used only by
            the arithmetic combination.

    Returns:
        The decision, with its reason codes and trace.

    """
    config = ctx.config
    severity = severity_for(field)
    dial = config.severity[severity]

    merged = merge_candidates(candidates)
    for candidate in merged:
        candidate.signals.extend(_validator_signals(field, candidate, ctx))
        candidate.signals.extend(_attach_arithmetic(field, candidate, values, ctx))

    vetoed: list[FieldCandidate] = []
    live: list[FieldCandidate] = []
    for candidate in merged:
        candidate.hard_refutations.extend(
            _hard_refutations(candidate.signals, ctx.veto_codes)
        )
        (vetoed if candidate.vetoed else live).append(candidate)

    # A vetoed candidate is kept in the trace but never scores.
    for candidate in vetoed:
        candidate.hard_refutations[:] = sorted(set(candidate.hard_refutations))

    scored = sorted(
        live,
        key=lambda candidate: _family_score(candidate.signals),
        reverse=True,
    )
    winner = scored[0] if scored else None
    runner_up = scored[1] if len(scored) > 1 else None

    score = _family_score(winner.signals) if winner else 0
    margin = score - (_family_score(runner_up.signals) if runner_up else 0)

    threshold = _threshold(dial, ctx.tier)
    strong = _strong_for(dial)
    gate = _gate_met(winner.signals, strong) if winner else False

    notes: list[str] = []
    reason_codes: list[str] = []

    if not live:
        reason_codes.append("ESC_ALL_VETOED")
        decision = DECISION_ESCALATE
        notes.append("every candidate was vetoed")
    elif score < ESCALATE_FLOOR:
        reason_codes.append("ESC_LOW_SCORE")
        decision = DECISION_ESCALATE
        notes.append(f"score {score} below the escalate floor {ESCALATE_FLOOR}")
    elif score >= threshold and margin >= dial.margin and gate:
        reason_codes.append("CONF_SCORE_MARGIN_GATE")
        decision = DECISION_CONFIRMED
    elif not gate:
        reason_codes.append("REV_GATE_UNMET")
        decision = DECISION_REVIEW
        notes.append(f"score {score} meets the floor but strong evidence is missing")
    elif margin < dial.margin:
        reason_codes.append("REV_CLOSE_MARGIN")
        decision = DECISION_REVIEW
        notes.append(f"margin {margin} below {dial.margin}")
    else:
        reason_codes.append("REV_SCORE_MID")
        decision = DECISION_REVIEW
        notes.append(f"score {score} below the threshold {threshold}")

    return FieldDecision(
        field=field,
        severity=severity,
        decision=decision,
        reason_codes=reason_codes,
        winner=winner,
        runner_up=runner_up,
        score=score,
        margin=margin,
        threshold=threshold,
        strong=strong,
        gate_satisfied=gate,
        notes=notes,
    )


def evaluate(
    decisions: Mapping[str, list[FieldCandidate]],
    ctx: DecisionContext,
    values: Mapping[str, str],
) -> dict[str, FieldDecision]:
    """Decide every field in a document.

    Args:
        decisions: Field name to its unmerged candidates.
        ctx: The run's dials.
        values: Document-level values for the arithmetic combination.

    Returns:
        Field name to :class:`FieldDecision`.

    """
    return {
        field: decide_field(field, candidates, ctx, values)
        for field, candidates in decisions.items()
    }
