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
from typing import Final

from .config import (
    DEFAULT_CONFIG,
    Config,
    FieldDial,
)
from .fields import (
    DECISION_CONFIRMED,
    DECISION_ESCALATE,
    DECISION_REVIEW,
    FAIL,
    IVA_FIELD,
    PASS,
    SUBTOTAL_FIELD,
    TOTAL_FIELD,
    EvidenceSignal,
    FieldCandidate,
    FieldDecision,
    merge_candidates,
    normalize,
    severity_for,
)
from .validators import (
    all_components_are_amounts,
    arithmetic_consistent,
    arithmetic_signal,
    cuit_signal,
    date_signal,
    required_components_for,
)

__all__: list[str] = [
    "DecisionContext",
    "decide_field",
    "evaluate",
]

#: The fields the deterministic validators apply to, and their rule. A field
#: outside this mapping carries no deterministic signal — its gate then needs a
#: cross-lane or native-anchor signal to close, which is exactly Anexo A.
_VALIDATOR_FIELDS: frozenset[str] = frozenset({"cuit_emisor", "fecha_emision"})

#: The reason code a non-unique arithmetic combination escalates with
#: (`my_flow.md` §6.4).
ESC_NO_UNIQUE_ARITHMETIC: Final[str] = "ESC_NO_UNIQUE_ARITHMETIC_COMBINATION"


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
        #: The arithmetic combination resolution, set by :func:`evaluate` before
        #: deciding. One of: ``None`` (no combination evaluable — every
        #: component is UNKNOWN), ``"consistent"`` (exactly one combination),
        #: or ``"non_unique"`` (zero or many consistent combinations, which
        #: escalates).
        self.arithmetic_resolution: str | None = None
        #: The one combination that added up, as ``(subtotal, iva, total)`` in
        #: the spelling its producers used. ``None`` whenever the resolution is
        #: not ``"consistent"``.
        #:
        #: It is stored rather than recomputed, and that is the point. Measured
        #: on a real run: this resolution found `14.791,98 + 3.106,32 ==
        #: 17.898,30` at the **candidate** level, and the signal was then built
        #: from the document *values* — where the model's own reading of the
        #: subtotal (`'12.356,12'`) and of the IVA (`'21%: 6.178,08'`, a rate and
        #: an amount run together, `B.7`) did not add up. The validated
        #: combination was thrown away and a different one judged, so the +3
        #: never reached the field it belonged to.
        self.arithmetic_combination: tuple[str, str, str] | None = None


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
    ctx: DecisionContext,
) -> list[EvidenceSignal]:
    """The arithmetic signal for the subtotal/IVA/total combination.

    The rule refutes a combination, not a field (`my_flow.md` §6.4). The
    combination resolution is computed once in :func:`evaluate` and carried on
    the context: exactly one consistent combination gives the +3 to its total
    and IVA; zero or many escalates (`ESC_NO_UNIQUE_ARITHMETIC_COMBINATION`);
    no evaluable combination stays UNKNOWN.

    The signal is built from the combination the resolver **validated**, not from
    the document values, and the candidate is matched to it by
    :func:`normalize`. Both halves of that were defects, measured on one run:

    - the match compared ``raw_value``, so `'17.898,30'` (regexp) and
      `'17898.30'` (the model) were *the same amount* to `normalize` and two
      different ones here — the third place `I2` had been left unapplied;
    - the equation was recomputed from ``values``, which is the model's own
      reading of the row, so the combination that had actually been validated was
      discarded and a junk one judged instead.
    """
    if field not in {TOTAL_FIELD, IVA_FIELD}:
        return []
    if ctx.arithmetic_resolution != "consistent" or ctx.arithmetic_combination is None:
        return []
    sub, tax, tot = ctx.arithmetic_combination
    expected = tax if field == IVA_FIELD else tot
    if normalize(candidate.raw_value) != normalize(expected):
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
) -> FieldDecision:
    """Decide one field from its candidates and the run's dials.

    The local count is the decision itself — merge, veto, score, gate — and each
    step pushes the previous one out of scope, the same shape `docling.py::read`
    documents for its own ordered pipeline.

    **No document values are needed here.** The arithmetic rule is resolved once,
    before any field, and carried on the context (`_resolve_arithmetic`); this
    function reads the combination it validated. A `values` parameter used to sit
    in this signature and was not read after the resolution moved — measured, the
    signal was being rebuilt from it instead, which is the defect the attachment
    gate guards.

    Args:
        field: The field name.
        candidates: The unmerged candidates the producers handed in.
        ctx: The run's dials, including the arithmetic resolution.

    Returns:
        The decision, with its reason codes and trace.

    """
    config = ctx.config
    severity = severity_for(field)
    dial = config.severity[severity]

    merged = merge_candidates(candidates)
    for candidate in merged:
        candidate.signals.extend(_validator_signals(field, candidate, ctx))
        candidate.signals.extend(_attach_arithmetic(field, candidate, ctx))

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
    elif (
        field in {TOTAL_FIELD, IVA_FIELD} and ctx.arithmetic_resolution == "non_unique"
    ):
        reason_codes.append(ESC_NO_UNIQUE_ARITHMETIC)
        decision = DECISION_ESCALATE
        notes.append("zero or more than one arithmetic combination is consistent")
    elif score < ctx.config.escalate_floor:
        reason_codes.append("ESC_LOW_SCORE")
        decision = DECISION_ESCALATE
        notes.append(
            f"score {score} below the escalate floor {ctx.config.escalate_floor}"
        )
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


def _resolve_arithmetic(
    ctx: DecisionContext,
    candidates: Mapping[str, list[FieldCandidate]],
    values: Mapping[str, str],
) -> None:
    """Resolve the arithmetic combination once, before any field is decided.

    §6.4: the rule refutes a **combination**, not a field. The candidates for
    subtotal, IVA and total each offer alternative values; the combination is
    the cross-product of their normalized values. Exactly one consistent
    combination → ``"consistent"`` (its +3 goes to the matching total/IVA);
    zero or many → ``"non_unique"``; no evaluable component → ``None``.
    """
    tipo = _tipo_comprobante(candidates, values)
    required = required_components_for(tipo)
    if not required:
        ctx.arithmetic_resolution = None
        ctx.arithmetic_combination = None
        return

    subtotals = _values_for(candidates, SUBTOTAL_FIELD, values)
    taxes = _values_for(candidates, IVA_FIELD, values)
    totals = _values_for(candidates, TOTAL_FIELD, values)
    if not (subtotals and taxes and totals):
        ctx.arithmetic_resolution = None
        ctx.arithmetic_combination = None
        return

    # §6.4's precondition of completeness, applied before the equation is judged:
    # a component that is not a plain amount is **not there**, so the combination
    # is not judgeable at all — never "inconsistent". Measured: a junk `iva`
    # (`'0,90 | 0'`, an alícuota, or a declared-absent `'null'`) alongside a
    # correct subtotal and total produced `non_unique`, and escalated both
    # critical fields with a motive that was simply untrue (I10, B.9).
    judged = [
        (sub, tax, tot)
        for sub in subtotals
        for tax in taxes
        for tot in totals
        if all_components_are_amounts(sub, tax, tot)
    ]
    if not judged:
        # Every component is unreadable: no equation to judge, so no resolution.
        # The field keeps its other routes to CONFIRMED — UNKNOWN scores nothing
        # and vetoes nothing (§6.4, I10).
        ctx.arithmetic_resolution = None
        ctx.arithmetic_combination = None
        return

    consistent = [
        (sub, tax, tot)
        for sub, tax, tot in judged
        if arithmetic_consistent(sub, tax, tot)
    ]

    if len(consistent) == 1:
        ctx.arithmetic_resolution = "consistent"
        ctx.arithmetic_combination = consistent[0]
    else:
        ctx.arithmetic_resolution = "non_unique"
        ctx.arithmetic_combination = None


def _tipo_comprobante(
    candidates: Mapping[str, list[FieldCandidate]], values: Mapping[str, str]
) -> str:
    """The receipt type, read from the candidates or the document values."""
    produced = candidates.get("tipo_comprobante")
    if produced:
        return produced[0].raw_value
    return values.get("tipo_comprobante", "")


def _values_for(
    candidates: Mapping[str, list[FieldCandidate]],
    field: str,
    values: Mapping[str, str],
) -> list[str]:
    """The alternative raw values a field offers, deduplicated by **value**.

    `I2` states the rule: every producer that reaches the same
    ``normalized_value`` is *one* candidate, because two printed forms of an
    amount are one amount. This function had deduplicated by ``raw_value``
    instead, which put the same invariant one level lower and broke it: measured,
    `regexp` read the total as `'17.898,30'` and the model returned `'17898.30'`
    — the same number, and both normalize to `1789830` — so the cross-product
    held *two* combinations that satisfied `subtotal + IVA == total`. Exactly one
    consistent combination had become two, and the critical amount escalated with
    `ESC_NO_UNIQUE_ARITHMETIC_COMBINATION`: a false motive, since there was
    never more than one total on the page (B.9, I10).

    The first spelling of each value survives, and the order stays stable, so the
    representative a caller reports does not depend on dictionary iteration.
    """
    found: list[str] = []
    seen: set[str] = set()
    for raw in (
        *(candidate.raw_value for candidate in candidates.get(field, [])),
        values.get(field, ""),
    ):
        if not raw:
            continue
        key = normalize(raw)
        if key and key not in seen:
            seen.add(key)
            found.append(raw)
    return found


def evaluate(
    decisions: Mapping[str, list[FieldCandidate]],
    ctx: DecisionContext,
    values: Mapping[str, str],
) -> dict[str, FieldDecision]:
    """Decide every field in a document.

    The arithmetic combination is resolved once, before any field, so the
    total and the IVA see the same resolution (§6.4).

    Args:
        decisions: Field name to its unmerged candidates.
        ctx: The run's dials.
        values: Document-level values for the arithmetic combination.

    Returns:
        Field name to :class:`FieldDecision`.

    """
    _resolve_arithmetic(ctx, decisions, values)
    return {
        field: decide_field(field, candidates, ctx)
        for field, candidates in decisions.items()
    }
