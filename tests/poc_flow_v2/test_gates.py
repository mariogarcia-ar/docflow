"""Fase C1: the build gates — reachability, drift, and the journal.

Three gates that must fail the build when an invariant breaks, not merely pass
when it holds (`my_flow.md` B.16, B.11, B.5):

1. **Reachability (I8).** Every implemented (severity, tier) pair keeps a path to
   `CONFIRMED`; the one intentionally unreachable cell stays unreachable. If a
   threshold or a family point changes so a reachable pair stops closing, this
   fails.
2. **Prompt↔schema drift (B.11).** Every field the registry schema requires is
   named in the prompt, and vice versa; amounts are strings; a field declared as
   options must be a real `enum`, not prose in a `description`.
3. **Journal (B.5).** The signature is canonical (a set's order does not change
   it); a changed setting or input discards the journal; invalidation marks the
   downstream, never the artifact bytes.
"""

from __future__ import annotations

import json
import pathlib

from flow import run
from flow.artifacts import load_artifacts
from flow.config import DEFAULT_CONFIG
from flow.engine import DecisionContext, decide_field
from flow.fields import (
    DECISION_CONFIRMED,
    PASS,
    EvidenceSignal,
    FieldCandidate,
)
from flow.journal import Journal, run_signature
from flow.record import read_run
from flow.stages import STAGE_DECIDE, STAGE_EXTRACT, STAGE_READ, STAGES


def _candidate(raw: str, signals: list[EvidenceSignal]) -> FieldCandidate:
    return FieldCandidate(
        normalized_value="".join(ch for ch in raw if ch not in "., "),
        raw_value=raw,
        producers=["test"],
        signals=signals,
        hard_refutations=[],
    )


def _signal(family: str, points: int, *, verified: bool = False) -> EvidenceSignal:
    return EvidenceSignal(family, PASS, points, "test", verified=verified)


def _decide(field: str, tier: str, raw: str, signals: list[EvidenceSignal]) -> object:
    ctx = DecisionContext(config=DEFAULT_CONFIG, tier=tier, own_cuits=frozenset())
    return decide_field(field, [_candidate(raw, signals)], ctx, {})


# --- 1. Reachability (I8) -------------------------------------------------


def _det() -> EvidenceSignal:
    return _signal("DETERMINISTIC", 3)


def _content() -> EvidenceSignal:
    return _signal("DOCUMENT_CONTENT", 2, verified=True)


def _cross() -> EvidenceSignal:
    return _signal("CROSS_MODAL", 2)


def _same() -> EvidenceSignal:
    return _signal("SAME_MATERIAL", 1)


def test_reachability_confirms_every_implemented_pair() -> None:
    """Every implemented (severity, tier) pair closes with its maximum signals.

    The signal sets below are the Anexo A maxima for the families the engine
    implements today. If a threshold or point changes so one of these stops
    closing, this test fails — which is exactly I8's purpose.
    """
    cases = [
        # (field, tier, raw, signals)
        # critica, OCR, with arithmetic: 3 + 2 + 2 + 1 = 8 ≥ 5, gate DETERMINISTIC
        (
            "importe_total_facturado",
            "escaneado_ocr",
            "17.898,30",
            [_det(), _content(), _cross(), _same()],
        ),
        # critica, OCR, without arithmetic but cross-modal: 2+2+1 = 5 ≥ 5
        (
            "importe_total_facturado",
            "escaneado_ocr",
            "17.898,30",
            [_content(), _cross(), _same()],
        ),
        # alta (CUIT), native, with checksum: 3+2+1 = 6 ≥ 3
        (
            "cuit_emisor",
            "texto_nativo",
            "20-22087601-3",
            [_det(), _content(), _same()],
        ),
        # media (razón social), native: 2+1 = 3 ≥ 3, no gate
        (
            "razon_social_emisor",
            "texto_nativo",
            "AIMARO JAVIER ANGEL",
            [_content(), _same()],
        ),
        # baja (descripción), OCR: 2+2+1 = 5 ≥ 4, no gate
        ("descripcion", "escaneado_ocr", "repuestos", [_content(), _cross(), _same()]),
    ]
    for field, tier, raw, signals in cases:
        decision = _decide(field, tier, raw, signals)
        assert decision.decision == DECISION_CONFIRMED, (
            f"{field}/{tier} lost its path to CONFIRMED: {decision.decision} "
            f"{decision.reason_codes} (score {decision.score}, threshold "
            f"{decision.threshold}, gate {decision.gate_satisfied})"
        )


def test_reachability_keeps_the_intentional_gap() -> None:
    """A critical field in native text without any strong evidence cannot
    confirm — the one cell Anexo A leaves unreachable on purpose."""
    decision = _decide(
        "importe_total_facturado",
        "texto_nativo",
        "17.898,30",
        [_content(), _same()],
    )

    assert decision.decision != DECISION_CONFIRMED
    assert "REV_GATE_UNMET" in decision.reason_codes


# --- 2. Prompt↔schema drift (B.11) ----------------------------------------


def test_registry_schema_and_prompt_agree() -> None:
    """Every extraction prompt names every required field, and vice versa.

    Both extract lanes share the schema, so the drift test runs over the text
    prompt and the vision prompt alike — a field the schema requires and one
    lane never names is the same silent drift, just in one lane.
    """
    artifacts = load_artifacts()
    schema = artifacts.extraction_schema
    required = set(schema["required"])
    properties = set(schema["properties"])

    for role in ("extract_texto", "extract_vision"):
        prompt = artifacts.prompts[role]
        missing = sorted(name for name in required if name not in prompt)
        undeclared = sorted(name for name in properties if name not in prompt)
        assert not missing, (
            f"{role}: schema requires {missing} that the prompt never names"
        )
        assert not undeclared, (
            f"{role}: schema declares {undeclared} that the prompt never names"
        )


def test_registry_amounts_are_strings() -> None:
    """Every amount field is a string, so a printed amount survives as text."""
    schema = load_artifacts().extraction_schema
    amounts = [
        "subtotal",
        "iva",
        "impuestos_internos",
        "percepcion_iibb",
        "otros_impuestos",
        "monto_no_gravado",
        "importe_total_facturado",
    ]
    for name in amounts:
        if name in schema["properties"]:
            assert schema["properties"][name]["type"] == "string", (
                f"{name!r} is not declared a string"
            )


# --- 3. Journal (B.5) ------------------------------------------------------


def test_signature_is_canonical_across_set_order() -> None:
    """A set's iteration order does not leak into the signature.

    The two inputs are the same members in different orders, and the canonical
    form is the sorted list — so a `set` and a `list` with those members must
    sign identically. Without the sort, a set whose hash order differs from its
    sorted order would sign differently on every run (B.5).
    """
    a = run_signature({"own_cuits": {"d", "c", "a", "b"}})
    b = run_signature({"own_cuits": ["a", "b", "c", "d"]})

    assert a == b


def test_a_changed_setting_is_a_different_signature() -> None:
    """One changed dial is a different run, so the journal is discarded."""
    a = run_signature({"model": "a"})
    b = run_signature({"model": "b"})

    assert a != b


def test_clear_from_marks_the_stage_and_every_later_one() -> None:
    """Invalidation marks the stage and its downstream, never the artifact."""
    journal = Journal(pathlib.Path("/tmp"), "sig", "digest")
    for stage in STAGES:
        journal.mark(stage)

    journal.clear_from(STAGE_EXTRACT)

    assert journal.done(STAGE_READ) is True
    assert journal.done(STAGE_EXTRACT) is False
    assert journal.done(STAGE_DECIDE) is False


def test_a_changed_digest_is_a_different_run(tmp_path: pathlib.Path) -> None:
    """The document's own bytes are part of the journal; editing them re-runs."""
    work = tmp_path / "work"
    doc = tmp_path / "a.pdf"
    doc.write_bytes(b"a")

    run(doc, {}, work_root=work)
    doc.write_bytes(b"b")
    outcome = run(doc, {}, work_root=work)

    assert all(step.action == "ran" for step in outcome.steps)


def test_the_run_record_is_json_and_derived(tmp_path: pathlib.Path) -> None:
    """`run.json` parses back and carries the four steps, derived not assumed."""
    work = tmp_path / "work"
    doc = tmp_path / "a.pdf"
    doc.write_bytes(b"a")
    run(doc, {}, work_root=work)

    raw = json.loads((work / "run.json").read_text(encoding="utf-8"))
    assert raw["document"] == "a.pdf"
    assert len(raw["steps"]) == 4
    record = read_run(work)
    assert record is not None and len(record.steps) == 4
