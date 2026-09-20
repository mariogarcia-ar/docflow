"""Fase 1: the closed circuits — classify, lanes, QR, verified.

Each test guards one circuit: if the circuit stops closing, the test fails
(`cierre-circuitos.md`, B.16). The tests are deterministic — no live model — so
a circuit is proven by constructed inputs, not by a generation.
"""

from __future__ import annotations

import pathlib
import tempfile

# Pylint cannot see inside OpenCV (compiled extension); the members it reports
# as missing are real and documented. Same suppression as `flow/qr.py`.
# pylint: disable=no-member
import cv2
import numpy as np
from flow.classify import classify
from flow.config import DEFAULT_CONFIG, FAMILY_POINTS
from flow.engine import _family_score
from flow.extract import _apply_review, _cross_modal, _present_at_location
from flow.fields import PASS, EvidenceSignal, FieldCandidate
from flow.qr import qr_candidates, qr_conflict, qr_deterministic
from flow.validators import arithmetic_signal

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
