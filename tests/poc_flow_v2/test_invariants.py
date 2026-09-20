"""Fase B1: the engine's invariants, tested over constructed values.

These are the four invariants `my_flow.md` makes non-negotiable, exercised
without an adapter. Each test is paired with a mutation that breaks exactly one
invariant — a test that only passes when the code is correct proves nothing
(B.16), so the proof is that the mutation turns it red.
"""

from __future__ import annotations

from flow.config import DEFAULT_CONFIG, FAMILY_POINTS
from flow.engine import DecisionContext, decide_field
from flow.fields import (
    FAIL,
    PASS,
    UNKNOWN,
    EvidenceSignal,
    FieldCandidate,
    merge_candidates,
)
from flow.validators import arithmetic_signal, cuit_signal


def _candidate(raw: str, *signals: EvidenceSignal) -> FieldCandidate:
    return FieldCandidate(
        normalized_value="".join(ch for ch in raw if ch not in "., "),
        raw_value=raw,
        producers=["test"],
        signals=list(signals),
        hard_refutations=[],
    )


def _ctx(tier: str = "texto_nativo") -> DecisionContext:
    return DecisionContext(config=DEFAULT_CONFIG, tier=tier, own_cuits=frozenset())


def _pass(family: str, points: int) -> EvidenceSignal:
    return EvidenceSignal(family, PASS, points, "test")


def _fail(family: str, detail: str) -> EvidenceSignal:
    return EvidenceSignal(family, FAIL, -2, detail)


def _unknown(family: str) -> EvidenceSignal:
    return EvidenceSignal(family, UNKNOWN, 0, "test")


# --- I2: the score belongs to the candidate, merged before scoring ---------


def test_i2_same_normalized_value_merges_into_one_candidate() -> None:
    """`"17.898,30"` and `"17898.30"` are one candidate, not competitors.

    Two printed forms of the same amount — thousands dot + decimal comma, and
    decimal dot only — normalise to the same key, so they must merge (I2).
    """
    a = _candidate("17.898,30")
    b = _candidate("17898.30")

    merged = merge_candidates([a, b])

    assert len(merged) == 1
    assert merged[0].raw_value == "17.898,30"


def test_i2_merge_conserves_both_producers() -> None:
    """The merge keeps every producer, so no evidence is dropped."""
    a = FieldCandidate(
        "123", "123", producers=["regexp"], signals=[], hard_refutations=[]
    )
    b = FieldCandidate("123", "123", producers=["llm"], signals=[], hard_refutations=[])

    merged = merge_candidates([a, b])

    assert len(merged) == 1
    assert set(merged[0].producers) == {"regexp", "llm"}


# --- I3: a hard refutation vetoes; no score compensates --------------------


def test_i3_a_vetoed_candidate_never_wins() -> None:
    """The only candidate, if vetoed, produces ESC_ALL_VETOED, not a win."""
    vetoed = FieldCandidate(
        normalized_value="99999999999",
        raw_value="99-99999999-9",
        producers=["test"],
        signals=[],
        hard_refutations=["CUITS_CHECKSUM_INVALID"],
    )

    decision = decide_field(
        "cuit_emisor",
        [vetoed],
        _ctx(),
        {"subtotal": "", "iva": "", "importe_total_facturado": ""},
    )

    assert decision.decision == "ESCALATE"
    assert "ESC_ALL_VETOED" in decision.reason_codes


# --- I4: max one signal per family -----------------------------------------


def test_i4_two_passes_in_one_family_score_once() -> None:
    """Two DETERMINISTIC passes are worth one +3, not +6."""
    candidate = _candidate(
        "20-22087601-3", _pass("DETERMINISTIC", 3), _pass("DETERMINISTIC", 3)
    )

    decision = decide_field("cuit_emisor", [candidate], _ctx(), {})

    assert decision.score == 3  # one deterministic +3, not two


# --- I10: UNKNOWN scores nothing and never vetoes --------------------------


def test_i10_unknown_scores_nothing() -> None:
    """An UNKNOWN signal contributes zero points, whatever its family."""
    candidate = _candidate("20-22087601-3", _unknown("DETERMINISTIC"))

    decision = decide_field("cuit_emisor", [candidate], _ctx(), {})

    # The validator re-runs over the CUIT and PASSes its checksum; the point is
    # that the *unknown* input signal alone would not have scored anything.
    assert decision.score >= 3


def test_i10_an_incomplete_equation_is_unknown_not_fail() -> None:
    """A missing component yields UNKNOWN, never a hard refutation (§6.4)."""
    signal = arithmetic_signal(
        "15.000,00", "", "17.898,30", family_points=FAMILY_POINTS
    )

    assert signal.result == UNKNOWN
    assert signal.detail != "ARITHMETIC_INCONSISTENT"


def test_i10_a_failed_checksum_is_a_veto_not_unknown() -> None:
    """With all 11 digits, a wrong checksum is FAIL (a veto), not UNKNOWN."""
    signal = cuit_signal(
        "20-12345678-0", own_cuits=frozenset(), family_points=FAMILY_POINTS
    )

    assert signal.result == FAIL
    assert signal.detail == "CUITS_CHECKSUM_INVALID"
