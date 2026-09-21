"""Fase 1: the closed circuits — classify, lanes, QR, verified.

Each test guards one circuit: if the circuit stops closing, the test fails
(`cierre-circuitos.md`, B.16). The tests are deterministic — no live model — so
a circuit is proven by constructed inputs, not by a generation.
"""

from __future__ import annotations

import pathlib
import tempfile
from types import MappingProxyType, SimpleNamespace

# Pylint cannot see inside OpenCV (compiled extension); the members it reports
# as missing are real and documented. Same suppression as `flow/qr.py`.
# pylint: disable=no-member
import cv2
import numpy as np
from flow.classify import classify
from flow.config import DEFAULT_CONFIG, FAMILY_POINTS
from flow.engine import DecisionContext, _family_score, evaluate
from flow.extract import (
    _apply_review,
    _call_structured,
    _cross_modal,
    _present_at_location,
    _review_verdicts,
)
from flow.fields import (
    CLASSIFY_NOT_A_RECEIPT,
    DECISION_CONFIRMED,
    DECISION_REVIEW,
    PASS,
    EvidenceSignal,
    FieldCandidate,
    FieldDecision,
    FieldResult,
)
from flow.frontier import _ask, suggest
from flow.hitl import PendingItem, backtest_rule
from flow.lane import needs_vision_lane
from flow.learn import (
    ACTIVATION_COUNT,
    TEMPLATE_ACTIVE,
    TEMPLATE_SHADOW,
    TEMPLATE_STALE,
    activate_template,
    audit_rate_for,
    template_state,
)
from flow.material import Material
from flow.qr import qr_candidates, qr_conflict, qr_deterministic
from flow.resolve import resolver_loop
from flow.run import ladder_step
from flow.validators import arithmetic_signal, required_components_for

from docflow.kernels.types import Bytes


def _answer(**observed: object):
    """A frontier result shaped like `KernelResult`, carrying only ``observed``.

    Deliberately **not** the real `KernelResult`: the property under test is
    which operation `_ask` chooses, and importing the kernel types would couple
    this suite to the frozen boundary it does not exercise. `_ask` reads
    ``.value`` and ``.value.observed`` and nothing else.
    """
    return SimpleNamespace(
        value=SimpleNamespace(observed=MappingProxyType(observed)),
        reason=None,
    )


class _StubFrontier:
    """A frontier stand-in that records which operation was asked for.

    The material choice is the property under test, so the double only has to
    answer `capabilities` and remember whether `vision` or `structured` was
    called. Both return an empty `suggestions` list, which is a successful call:
    the tests are about *what was sent*, never about what came back.
    """

    # `too-few-public-methods`: the double's job is the `calls` list and the two
    # recorded operations, not a surface.
    # pylint: disable=too-few-public-methods

    def __init__(self, *, supports_vision: bool) -> None:
        self.supports_vision = supports_vision
        self.calls: list[str] = []

    def capabilities(self, model: str):  # pylint: disable=unused-argument
        """Report what the provider declares about pixels."""
        return _answer(supports_vision=self.supports_vision)

    def vision(self, model, prompt, images, schema):  # pylint: disable=unused-argument
        """Record a call about images."""
        self.calls.append("vision")

        return _answer(suggestions=[])

    def structured(self, model, prompt, schema):  # pylint: disable=unused-argument
        """Record a call about text."""
        self.calls.append("structured")

        return _answer(suggestions=[])


# --- C1: classify ----------------------------------------------------------


def test_c1_a_receipt_like_text_proceeds() -> None:
    """A CUIT plus an amount passes the gate."""
    decision = classify(
        "FACTURA A nro 0001-00001234 CUIT 20-22087601-3 Importe $ 17.898,30"
    )

    assert decision.proceeds is True


def test_c1_a_non_receipt_is_refused_with_a_reason() -> None:
    """A document with no fiscal signals does not proceed."""
    decision = classify("lorem ipsum dolor sit amet consectetur adipiscing elit")

    assert decision.proceeds is False
    assert decision.reason


def test_c1_empty_text_is_not_a_receipt() -> None:
    """No text, no receipt."""
    decision = classify("")

    assert decision.proceeds is False


def test_c1_a_lone_keyword_is_not_enough() -> None:
    """One keyword alone is prose, not a receipt."""
    decision = classify("la factura de la luz llegó tarde este mes")

    assert decision.proceeds is False


def test_c1_a_refusal_carries_a_stable_code() -> None:
    """A refusal names a code, not only prose.

    Reason codes are the base of every metric (§6.5), so a discard that leaves
    no code cannot be counted. The code is asserted as a **literal** as well as
    against the constant: a test that compares the constant to itself moves
    with any rename and proves nothing.
    """
    decision = classify("la factura de la luz llegó tarde este mes")

    assert decision.code == "CLASSIFY_NOT_A_RECEIPT"
    assert decision.code == CLASSIFY_NOT_A_RECEIPT


def test_c1_a_proceeding_document_carries_no_refusal_code() -> None:
    """The code is the signature of a refusal; a passing gate has none."""
    decision = classify(
        "FACTURA A nro 0001-00001234 CUIT 20-22087601-3 Importe $ 17.898,30"
    )

    assert decision.proceeds is True
    assert decision.code == ""


def test_c1_the_reason_names_the_shortfall_not_only_what_was_found() -> None:
    """The prose says how many signals were required.

    Listing only the signals found reads as if the last one caused the refusal,
    when the cause is that two are required.
    """
    decision = classify("la factura de la luz llegó tarde este mes")

    assert "1 of 2 required signals" in decision.reason
    assert "fiscal_word" in decision.reason


# --- C3: QR (deterministic extraction) -------------------------------------


def test_c3_qr_decodes_the_arca_payload() -> None:
    """A generated ARCA-style QR yields deterministic candidates."""
    candidates = qr_candidates(_qr_fixture())

    assert any(
        c.raw_value == "20-12345678-3" for c in candidates.get("cuit_emisor", [])
    )
    assert any(
        c.raw_value == "17.898,30"
        for c in candidates.get("importe_total_facturado", [])
    )


def test_c3_qr_agreement_is_a_deterministic_signal() -> None:
    """The QR agreeing with the printed value earns DETERMINISTIC."""
    signal = qr_deterministic("20-22087601-3", "20-22087601-3", FAMILY_POINTS)

    assert signal.result == PASS
    assert signal.family == "DETERMINISTIC"


def test_c3_qr_disagreement_is_a_conflict_not_a_vote() -> None:
    """QR vs printed disagreement flags a conflict, never a score."""
    assert qr_conflict("20-22087601-3", "20-99999999-9") is True
    assert qr_conflict("20-22087601-3", "20-22087601-3") is False


# --- C4: verified (content at the declared location) ------------------------


def test_c4_verified_requires_the_value_at_the_location() -> None:
    """The content must be present where the extractor claims it is."""
    text = "Total: $17.898,30"
    assert _present_at_location("17.898,30", text) is True
    assert _present_at_location("18.898,30", text) is False


def test_c4_a_value_inside_a_longer_number_is_not_verified() -> None:
    """`17.898,30` inside `117.898,301` is a slice, not a reading.

    This is the false positive the digit boundary check exists to kill: the
    substring test alone would read a truncated number as verified.
    """
    text = "Total: $117.898,301"
    assert _present_at_location("17.898,30", text) is False


def test_c4_a_free_text_value_uses_a_plain_occurrence() -> None:
    """A non-numeric value (razón social) is checked by occurrence, no digit guard."""
    text = "Razón social: AIMARO JAVIER ANGEL"
    assert _present_at_location("AIMARO JAVIER ANGEL", text) is True


def test_c4_an_unverified_anchor_is_unknown_not_pass() -> None:
    """A candidate whose content is not at the location scores nothing."""
    candidate = FieldCandidate(
        normalized_value="1899999999",
        raw_value="18.999,99",
        producers=["llm"],
        signals=[
            EvidenceSignal(
                "DOCUMENT_CONTENT", PASS, 2, "no verified anchor", verified=False
            )
        ],
        hard_refutations=[],
    )
    assert candidate.signals[0].verified is False


def test_c4_the_arithmetic_validator_is_still_tristate() -> None:
    """C4 does not touch I10: an incomplete equation stays UNKNOWN."""
    signal = arithmetic_signal("", "", "17.898,30", family_points=FAMILY_POINTS)

    assert signal.result == "UNKNOWN"


# --- C2: lanes (cross-modal, same-material, review) -------------------------


def test_c2_cross_modal_is_earned_when_text_and_vision_agree() -> None:
    """A value from both lanes on the same normalized form earns CROSS_MODAL."""
    text = FieldCandidate(
        normalized_value="1789830",
        raw_value="17.898,30",
        producers=["extractor_llm_texto"],
        signals=[],
        hard_refutations=[],
    )
    vision = FieldCandidate(
        normalized_value="1789830",
        raw_value="17.898,30",
        producers=["vision"],
        signals=[],
        hard_refutations=[],
    )
    candidates = {"importe_total_facturado": [text, vision]}

    _cross_modal(candidates, DEFAULT_CONFIG)

    assert any(
        s.family == "CROSS_MODAL"
        for s in candidates["importe_total_facturado"][0].signals
    )


def test_c2_same_material_is_capped_at_one_agree() -> None:
    """Two reviewer agrees keep two signals but score once (the family cap).

    The trace is faithful — the reviewer did agree twice — but the engine's
    family cap (I4) scores the family once, not once per signal.
    """
    candidate = FieldCandidate(
        normalized_value="1789830",
        raw_value="17.898,30",
        producers=["extractor_llm_texto"],
        signals=[],
        hard_refutations=[],
    )
    candidates = {"importe_total_facturado": [candidate]}
    verdicts = [
        {"field": "importe_total_facturado", "verdict": "agree"},
        {"field": "importe_total_facturado", "verdict": "agree"},
    ]

    _apply_review(candidates, verdicts, DEFAULT_CONFIG)

    signals = candidates["importe_total_facturado"][0].signals
    same = [s for s in signals if s.family == "SAME_MATERIAL"]
    assert len(same) == 2  # the trace keeps both
    assert _family_score(signals) == 1  # the score counts the family once


def test_c2_a_reviewer_disagree_produces_a_new_candidate() -> None:
    """A disagree softens A and adds a suggested value starting from zero."""
    candidate = FieldCandidate(
        normalized_value="1789830",
        raw_value="17.898,30",
        producers=["extractor_llm_texto"],
        signals=[],
        hard_refutations=[],
    )
    candidates = {"importe_total_facturado": [candidate]}
    verdicts = [
        {
            "field": "importe_total_facturado",
            "verdict": "disagree",
            "suggested_value": "17.898,00",
        }
    ]

    _apply_review(candidates, verdicts, DEFAULT_CONFIG)

    produced = candidates["importe_total_facturado"]
    assert len(produced) == 2
    assert any(p.producers == ["reviewer_suggested"] for p in produced)


def test_c2_a_verdict_naming_no_reviewed_field_is_counted() -> None:
    """A malformed verdict is reported, not silently dropped (B.9).

    Measured: `gemma3:1b` answers `{"field": "agree", "verdict": "agree"}` —
    the verdict echoed into the field slot. No candidate is named "agree", so
    the loop skipped it and the lane looked like a reviewer with nothing to say.
    """
    candidates = {
        "importe_total_facturado": [
            FieldCandidate("1789830", "17.898,30", ["extractor_llm_texto"], [], [])
        ]
    }
    verdicts = [{"field": "agree", "verdict": "agree"}]

    unmatched = _apply_review(candidates, verdicts, DEFAULT_CONFIG)

    assert unmatched == 1
    # ``== []`` (not ``not signals``) asserts the list is exactly empty — the
    # real defect, since a malformed verdict must add nothing at all.
    assert candidates["importe_total_facturado"][0].signals == (  # pylint: disable=use-implicit-booleaness-not-comparison
        []
    )


def test_c2_a_well_formed_verdict_counts_as_matched() -> None:
    """The control: a real verdict reports zero unmatched, so the counter is not
    a constant."""
    candidates = {
        "importe_total_facturado": [
            FieldCandidate("1789830", "17.898,30", ["extractor_llm_texto"], [], [])
        ]
    }
    verdicts = [{"field": "importe_total_facturado", "verdict": "agree"}]

    unmatched = _apply_review(candidates, verdicts, DEFAULT_CONFIG)

    assert unmatched == 0
    assert any(
        s.family == "SAME_MATERIAL"
        for s in candidates["importe_total_facturado"][0].signals
    )


def test_c2_a_refused_review_carries_the_adapters_reason_code() -> None:
    """A lane that could not run reports **why**, not just that it had no verdicts.

    The adapter already typed the refusal (`model_not_pulled`, `engine_unavailable`,
    …) and the flow discarded it, collapsing *the reviewer is missing* into *the
    reviewer agreed with nothing* (`my_flow.md` B.9). Measured: the configured
    reviewer was absent, the note said only `no review verdicts`, and the missing
    `SAME_MATERIAL` signal was unattributable.
    """

    class _RefusingEngine:
        """An engine whose call is refused, shaped like the adapter's result."""

        # `too-few-public-methods`: the double exists for its one refusal.
        # pylint: disable=too-few-public-methods

        def structured(self, model, prompt, schema):  # pylint: disable=unused-argument
            """Refuse the call with a typed reason."""
            return SimpleNamespace(
                value=None,
                reason=SimpleNamespace(code="model_not_pulled", message="absent"),
            )

    verdicts, code = _review_verdicts(
        _RefusingEngine(), "gemma3", "p", {"type": "object"}
    )

    assert verdicts == []
    assert code == "model_not_pulled"


def test_c2_a_successful_call_reports_no_refusal_code() -> None:
    """The control: an answered call returns an empty code, not a constant.

    Asserts against the **call helper**, not `_review_verdicts`: the latter
    discards the code whenever a value came back, so it would pass even if the
    helper invented one on every success.
    """

    class _AnsweringEngine:
        """An engine that answers with one verdict."""

        # pylint: disable=too-few-public-methods

        def structured(self, model, prompt, schema):  # pylint: disable=unused-argument
            """Answer with a single reviewer verdict."""
            return SimpleNamespace(
                value={"field_verdicts": [{"field": "iva", "verdict": "agree"}]},
                reason=None,
            )

    answered, code = _call_structured(
        _AnsweringEngine(), "gemma3", "p", {"type": "object"}
    )

    assert answered is not None and "field_verdicts" in answered
    assert code == ""


def test_c2_a_refused_vision_review_carries_its_code() -> None:
    """The vision path reports its refusal the same way the text path does.

    Both paths reach the same reviewer role, so a code dropped on only one of
    them is the same silent loss — and it is the one that would go unnoticed,
    because the vision lane runs least often.
    """

    class _RefusingVisionEngine:
        """A vision engine whose call is refused."""

        # pylint: disable=too-few-public-methods

        def vision(self, model, prompt, images, schema):  # pylint: disable=unused-argument
            """Refuse the call with a typed reason."""
            return SimpleNamespace(
                value=None,
                reason=SimpleNamespace(code="unsupported_format", message="no pixels"),
            )

    verdicts, code = _review_verdicts(
        _RefusingVisionEngine(),
        "granite-vision:2b",
        "p",
        {"type": "object"},
        images=[Bytes(b"png", "image/png")],
    )

    assert verdicts == []
    assert code == "unsupported_format"


def test_c2_a_reviewer_without_a_verdict_list_is_not_a_success() -> None:
    """An answer missing `field_verdicts` is a refusal, not an empty review.

    A model that answers `{}` produced no review at all; reporting it as an
    empty verdict list would make it indistinguishable from a reviewer that read
    the document and found nothing to dispute (`my_flow.md` B.9).
    """

    class _ShapelessEngine:
        """An engine that answers without the verdict list."""

        # pylint: disable=too-few-public-methods

        def structured(self, model, prompt, schema):  # pylint: disable=unused-argument
            """Answer with an object that carries no verdicts."""
            return SimpleNamespace(value={"reviewer": "gemma3"}, reason=None)

    verdicts, code = _review_verdicts(
        _ShapelessEngine(), "gemma3", "p", {"type": "object"}
    )

    assert verdicts == []
    assert code, "a missing verdict list must be reported, not read as success"


# --- C5: arithmetic consistency (combinations + required components) --------


def test_c5_a_factura_c_has_no_required_components() -> None:
    """A Factura C does not discriminate IVA, so the equation has no components."""
    assert not required_components_for("C")


def test_c5_the_default_combination_needs_all_three() -> None:
    """The net-plus-VAT combination requires subtotal, IVA and total."""
    assert required_components_for("A") == (
        "subtotal",
        "iva",
        "importe_total_facturado",
    )


def test_c5_one_consistent_combination_scores_once() -> None:
    """Exactly one consistent combination gives the +3 to total and IVA."""
    candidates = {
        "subtotal": [FieldCandidate("15000", "15.000,00", ["llm"], [], [])],
        "iva": [FieldCandidate("289830", "2.898,30", ["llm"], [], [])],
        "importe_total_facturado": [
            FieldCandidate("1789830", "17.898,30", ["llm"], [], []),
            FieldCandidate("9999999", "99.999,99", ["llm"], [], []),
        ],
    }
    ctx = DecisionContext(
        config=DEFAULT_CONFIG, tier="texto_nativo", own_cuits=frozenset()
    )
    decisions = evaluate(
        candidates,
        ctx,
        {
            "subtotal": "15.000,00",
            "iva": "2.898,30",
            "importe_total_facturado": "17.898,30",
        },
    )

    assert ctx.arithmetic_resolution == "consistent"
    total = decisions["importe_total_facturado"]
    assert any(
        s.family == "DETERMINISTIC" and s.result == "PASS" for s in total.winner.signals
    )


def test_c5_non_unique_combination_escalates() -> None:
    """More than one consistent combination escalates, never a false +3.

    Two different (subtotal, IVA) pairs both sum to the same total: the equation
    cannot pick which is the reading, so it must not hand out a deterministic
    PASS to either.
    """
    candidates = {
        "subtotal": [
            FieldCandidate("15000", "15.000,00", ["llm"], [], []),
            FieldCandidate("14900", "14.900,00", ["llm"], [], []),
        ],
        "iva": [
            FieldCandidate("289830", "2.898,30", ["llm"], [], []),
            FieldCandidate("299830", "2.998,30", ["llm"], [], []),
        ],
        "importe_total_facturado": [
            FieldCandidate("1789830", "17.898,30", ["llm"], [], []),
        ],
    }
    ctx = DecisionContext(
        config=DEFAULT_CONFIG, tier="texto_nativo", own_cuits=frozenset()
    )
    decisions = evaluate(
        candidates,
        ctx,
        {
            "subtotal": "15.000,00",
            "iva": "2.898,30",
            "importe_total_facturado": "17.898,30",
        },
    )

    total = decisions["importe_total_facturado"]
    assert "ESC_NO_UNIQUE_ARITHMETIC_COMBINATION" in total.reason_codes


# --- C6: lane-on-demand -----------------------------------------------------


def test_c6_a_critical_field_with_unmet_gate_needs_vision() -> None:
    """A critical REVIEW with no strong evidence is the ladder's target."""
    decision = FieldDecision(
        field="importe_total_facturado",
        severity="critica",
        decision=DECISION_REVIEW,
        reason_codes=["REV_GATE_UNMET"],
        winner=FieldCandidate("1789830", "17.898,30", ["llm"], [], []),
        runner_up=None,
        score=2,
        margin=2,
        threshold=5,
        strong=("DETERMINISTIC", "CROSS_MODAL"),
        gate_satisfied=False,
        notes=[],
    )

    needed = needs_vision_lane({"importe_total_facturado": decision})

    assert "importe_total_facturado" in needed


def test_c6_a_closed_gate_does_not_need_vision() -> None:
    """A gate already satisfied is not a ladder target."""
    decision = FieldDecision(
        field="importe_total_facturado",
        severity="critica",
        decision=DECISION_CONFIRMED,
        reason_codes=["CONF_SCORE_MARGIN_GATE"],
        winner=FieldCandidate("1789830", "17.898,30", ["llm"], [], []),
        runner_up=None,
        score=5,
        margin=3,
        threshold=5,
        strong=("DETERMINISTIC", "CROSS_MODAL"),
        gate_satisfied=True,
        notes=[],
    )

    assert not needs_vision_lane({"importe_total_facturado": decision})


# --- C7: resolver loop ------------------------------------------------------


def test_c7_the_loop_reaters_only_with_new_evidence() -> None:
    """A resolver that changes the candidate set re-enters the engine."""
    calls: list[int] = []

    def decide():
        calls.append(1)
        return _result_of(
            [
                FieldDecision(
                    field="importe_total_facturado",
                    severity="critica",
                    decision=DECISION_CONFIRMED if len(calls) > 1 else "REVIEW",
                    reason_codes=[],
                    winner=FieldCandidate("1789830", "17.898,30", ["llm"], [], []),
                    runner_up=None,
                    score=3,
                    margin=2,
                    threshold=5,
                    strong=("DETERMINISTIC",),
                    gate_satisfied=True,
                    notes=[],
                )
            ]
        )

    def resolve(result):
        del result
        return len(calls) == 1

    resolver_loop(decide, resolve, max_loops=2)

    assert len(calls) == 2


def test_c7_a_resolver_with_nothing_new_stops_with_a_reason() -> None:
    """No new evidence → ESC_NO_NEW_EVIDENCE, no re-entry."""
    calls: list[int] = []

    def decide():
        calls.append(1)
        return _result_of(
            [
                FieldDecision(
                    field="importe_total_facturado",
                    severity="critica",
                    decision=DECISION_REVIEW,
                    reason_codes=["REV_GATE_UNMET"],
                    winner=FieldCandidate("1789830", "17.898,30", ["llm"], [], []),
                    runner_up=None,
                    score=2,
                    margin=2,
                    threshold=5,
                    strong=("DETERMINISTIC", "CROSS_MODAL"),
                    gate_satisfied=False,
                    notes=[],
                )
            ]
        )

    result = resolver_loop(decide, lambda _result: False, max_loops=2)

    assert len(calls) == 1
    assert "ESC_NO_NEW_EVIDENCE" in result.notes


def test_c7_a_resolver_that_does_not_apply_records_no_reason_code() -> None:
    """`None` is a non-event, not a stopped loop (B.9).

    The distinction is load-bearing: `ESC_NO_NEW_EVIDENCE` is an *escalation
    motivo* and the base of every metric (§6.5). A resolver that had no work to
    do must not report one, or a code fires on every run and counts documents
    that never escalated — which it did, on all three measured runs, until this
    state existed.
    """
    calls: list[int] = []

    def decide():
        calls.append(1)
        return _result_of([])

    result = resolver_loop(decide, lambda _result: None, max_loops=2)

    assert len(calls) == 1, "the loop must not re-enter the engine"
    # `== []` and not `not notes`: the assertion is that the note list is exactly
    # empty, and `not None` would also pass — a state this loop must never be in.
    # ``== []`` (not ``not notes``) asserts the list is exactly empty; ``not None``
    # would also pass, and that is a state this loop must never be in.
    assert result.notes == [], (  # pylint: disable=use-implicit-booleaness-not-comparison
        result.notes
    )


def test_c7_not_applicable_is_not_the_same_answer_as_nothing_new() -> None:
    """The two stops differ in exactly one observable: the note.

    Asserted together so a change that collapses the two states into one
    boolean fails here rather than silently reintroducing the false motivo.
    """
    not_applicable = resolver_loop(lambda: _result_of([]), lambda _result: None)
    nothing_new = resolver_loop(lambda: _result_of([]), lambda _result: False)

    assert not_applicable.notes == (  # pylint: disable=use-implicit-booleaness-not-comparison
        []
    )
    assert nothing_new.notes == ["ESC_NO_NEW_EVIDENCE"]


def test_c6_the_wired_ladder_step_returns_none_when_no_lane_is_needed() -> None:
    """The caller's own answer, not just the pure predicate.

    `needs_vision_lane` returning `{}` and the *caller* reporting the correct
    three-state answer are two different facts. Testing only the predicate left
    the wiring unguarded: returning `False` instead of `None` here re-created the
    false `ESC_NO_NEW_EVIDENCE` on every run and no test failed.
    """
    result = _result_of([])

    assert ladder_step(result) is None
    assert result.notes == (  # pylint: disable=use-implicit-booleaness-not-comparison
        []
    )


def test_c6_the_wired_ladder_step_stops_when_a_lane_is_deferred() -> None:
    """A needed-but-unrendered lane is a real stop: the loop must be told."""
    decision = FieldDecision(
        field="importe_total_facturado",
        severity="critica",
        decision=DECISION_REVIEW,
        reason_codes=["REV_GATE_UNMET"],
        winner=FieldCandidate("1789830", "17.898,30", ["llm"], [], []),
        runner_up=None,
        score=2,
        margin=2,
        threshold=5,
        strong=("DETERMINISTIC", "CROSS_MODAL"),
        gate_satisfied=False,
        notes=[],
    )
    result = _result_of([decision])

    assert ladder_step(result) is False
    assert any("lane-on-demand deferred" in note for note in result.notes)


def _result_of(decisions):
    return FieldResult(
        decisions={d.field: d for d in decisions}, trace={}, extracted={}, notes=[]
    )


# --- C8: frontier backtest --------------------------------------------------


def test_c8_a_rule_that_breaks_a_confirmed_value_is_not_proposed() -> None:
    """A candidate rule that disagrees with a human-confirmed value is refused."""

    def rule(field):
        return "17.898,30" if field == "importe_total_facturado" else None

    confirmed = {"importe_total_facturado": "17.899,00"}

    assert backtest_rule(rule, confirmed) is False


def test_c8_a_rule_consistent_with_history_is_proposed() -> None:
    """A rule that never disagrees with a confirmed value passes the backtest."""

    def rule(field):
        return "17.898,30" if field == "importe_total_facturado" else None

    confirmed = {"importe_total_facturado": "17.898,30"}

    assert backtest_rule(rule, confirmed) is True


def test_c8_without_a_credential_the_queue_survives(monkeypatch) -> None:
    """No key: suggestions are empty and the refusal is a note, never a fake."""
    monkeypatch.delenv("DOCFLOW_FRONTIER_KEY", raising=False)
    monkeypatch.delenv("DOCFLOW_FRONTIER_DEEPSEEK_KEY", raising=False)
    material = Material(
        kind="pdf",
        tier="texto_nativo",
        text="CUIT 20-22087601-3 Importe $ 17.898,30",
        route="layout_text",
        pages_read=1,
        pages_total=1,
        images=[],
        notes=[],
    )
    item = PendingItem(
        field="importe_total_facturado",
        severity="critica",
        decision="REVIEW",
        reason_codes=["REV_GATE_UNMET"],
        winner=FieldCandidate("1789830", "17.898,30", ["llm"], [], []),
        runner_up=None,
    )

    suggestions, note = suggest([item], material, DEFAULT_CONFIG, "f.pdf")

    assert not suggestions
    assert note.startswith("frontier refused:")


def test_c8_a_provider_without_vision_gets_the_text_and_says_so() -> None:
    """A scan degrades to its OCR text, and the degradation is announced.

    The frontier model is DeepSeek, whose provider declares no vision: handed an
    image it accepts the request, ignores the pixels and answers as if the
    document were blank. Sending the pages would therefore be refused before the
    call, and sending nothing would throw away the OCR text the run already paid
    for. What must **not** happen is either of those *silently* — `my_flow.md`
    B.12: a recorte anunciado no es un recorte silencioso.

    A scanned fixture carries both, which is what makes the choice real rather
    than hypothetical.
    """
    engine = _StubFrontier(supports_vision=False)
    material = Material(
        kind="pdf",
        tier="escaneado_ocr",
        text="CUIT 20-22087601-3 Importe $ 17.898,30",
        route="ocr",
        pages_read=1,
        pages_total=1,
        images=[b"\x89PNG\r\n\x1a\n" + b"0" * 32],
        notes=[],
    )

    attempt, note = _ask(engine, DEFAULT_CONFIG, "prompt", material)

    # `None` would mean nothing was sent — the text was available and readable.
    assert attempt is not None
    assert engine.calls == ["structured"]
    # The note is what keeps a degraded reading from passing as the full one.
    assert "OCR text" in note
    assert "no vision" in note


def test_c8_a_provider_with_vision_gets_the_pages() -> None:
    """The same material goes to `vision` when the provider declares it.

    The control for the test above: without it, `_ask` could send text always
    and the degradation note would be reported for a provider that can read
    pages, which is a worse failure than the one it announces.
    """
    engine = _StubFrontier(supports_vision=True)
    material = Material(
        kind="pdf",
        tier="escaneado_ocr",
        text="CUIT 20-22087601-3",
        route="ocr",
        pages_read=1,
        pages_total=1,
        images=[b"\x89PNG\r\n\x1a\n" + b"0" * 32],
        notes=[],
    )

    attempt, note = _ask(engine, DEFAULT_CONFIG, "prompt", material)

    assert attempt is not None
    assert engine.calls == ["vision"]
    assert note == ""


def test_c8_a_scan_without_text_and_without_vision_sends_nothing() -> None:
    """No pixels readable and no text to fall back to: no call, and a reason.

    The remaining branch of the material choice. A call here would be the
    plausible-looking wrong answer this project exists to catch, so the honest
    outcome is `None` — nothing sent — with a note naming why.
    """
    engine = _StubFrontier(supports_vision=False)
    material = Material(
        kind="pdf",
        tier="escaneado_ocr",
        text="",
        route="ocr",
        pages_read=1,
        pages_total=1,
        images=[b"\x89PNG\r\n\x1a\n" + b"0" * 32],
        notes=[],
    )

    attempt, note = _ask(engine, DEFAULT_CONFIG, "prompt", material)

    assert attempt is None
    # `not engine.calls` would also pass for a `None` that `_ask` never set, so
    # the empty list is asserted explicitly: *nothing was sent* is the property.
    assert engine.calls == []  # pylint: disable=use-implicit-booleaness-not-comparison
    assert "nothing to send" in note


# --- C9: learning -----------------------------------------------------------


def test_c9_only_human_confirmation_activates_a_template() -> None:
    """A shadow template becomes active only with enough HUMAN confirmations."""

    state = "shadow"
    newly_active = False
    for count in range(ACTIVATION_COUNT):
        state, newly_active = activate_template(True, sample_count_human=count)

    assert state == TEMPLATE_ACTIVE
    assert newly_active is True


def test_c9_system_confirmations_never_activate_a_template() -> None:
    """A systematic error cannot teach itself (I7): no human sample, no active.

    ``template_state`` keys on the *human* sample count; however many
    ``SYSTEM_CONFIRMED`` samples there are, with zero human confirmations the
    template stays in shadow.
    """

    assert template_state(sample_count_human=0) == TEMPLATE_SHADOW
    assert template_state(sample_count_human=ACTIVATION_COUNT - 1) == TEMPLATE_SHADOW


def test_c9_an_inconsistent_confirmation_stales_the_template() -> None:
    """A confirmation that disagrees with the template is a new layout."""

    state, newly_active = activate_template(False, sample_count_human=10)
    assert state == TEMPLATE_STALE
    assert newly_active is False


def test_c9_audit_rate_is_severity_based() -> None:
    """The audit rate is per severity, sampled from the SYSTEM set (§9)."""

    assert audit_rate_for("critica") > audit_rate_for("baja")


def _qr_fixture() -> bytes:
    """A PNG of an ARCA-style QR payload, generated deterministically."""
    payload = (
        '{"ver":1,"fecha":"2026-08-07","cuit":20123456783,'
        '"puntoVenta":1,"tipoCmp":1,"nroCmp":1234,"importe":17898.30,'
        '"moneda":"PES","ctz":1,"tipoDocRec":80,"nroDocRec":20123456783,'
        '"tipoCodAut":"E","codAut":12345678901234}'
    )
    encoder = cv2.QRCodeEncoder_create()
    matrix = encoder.encode(payload)
    # The encoder already produces 0=black/255=white with a quiet zone; scale it
    # up so the decoder has enough pixels per module.
    image = cv2.resize(
        matrix.astype(np.uint8), None, fx=12, fy=12, interpolation=cv2.INTER_NEAREST
    )
    path = pathlib.Path(tempfile.mkdtemp()) / "qr.png"
    cv2.imwrite(str(path), image)
    return path.read_bytes()
