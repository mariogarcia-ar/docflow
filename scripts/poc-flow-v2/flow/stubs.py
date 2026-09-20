"""The stage stubs: values a run process can drive without an adapter.

The Fase A plan builds the run process over **fakes** (`plan/README.md`). Each
stage here returns a constructed value and records the call, so the process —
journal, resume, pause/stop, trace, report — is exercised before any model or
engine is connected. Nothing imports `docflow`; this module is pure standard
library plus the frozen data contract in `fields.py`.

Fase B replaces each stub with the real library. The tests of Fase A keep
passing unchanged, because a stage's contract is its name and its artifact, not
what produced the value inside it.
"""

from __future__ import annotations

import dataclasses
import time

from .fields import (
    DECISION_CONFIRMED,
    DECISION_REVIEW,
    EvidenceSignal,
    FieldCandidate,
    FieldDecision,
    FieldResult,
)

__all__: list[str] = [
    "STUB_LATENCY_SECONDS",
    "STUB_RESULT",
    "StubContext",
    "stub_decide",
    "stub_extract",
    "stub_hitl",
    "stub_read",
]


def _decisions() -> dict[str, FieldDecision]:
    """The fixed decision set: one confirmed field, one in review."""
    return {
        "cuit_emisor": FieldDecision(
            field="cuit_emisor",
            severity="alta",
            decision=DECISION_CONFIRMED,
            reason_codes=["CONF_SCORE_MARGIN_GATE"],
            winner=FieldCandidate(
                normalized_value="20123456783",
                raw_value="20-12345678-3",
                producers=["regexp"],
                signals=[
                    EvidenceSignal(
                        family="DETERMINISTIC",
                        result="PASS",
                        points=3,
                        detail="CUIT checksum valid",
                        verified=False,
                    )
                ],
                hard_refutations=[],
            ),
            runner_up=None,
            score=3,
            margin=3,
            threshold=3,
            strong=("DETERMINISTIC", "CROSS_MODAL", "NATIVE_ANCHOR"),
            gate_satisfied=True,
            notes=[],
        ),
        "importe_total_facturado": FieldDecision(
            field="importe_total_facturado",
            severity="critica",
            decision=DECISION_REVIEW,
            reason_codes=["REV_GATE_UNMET"],
            winner=FieldCandidate(
                normalized_value="1789830",
                raw_value="17.898,30",
                producers=["extractor_llm_texto"],
                signals=[
                    EvidenceSignal(
                        family="DOCUMENT_CONTENT",
                        result="PASS",
                        points=2,
                        detail="value present in the text",
                        verified=True,
                    )
                ],
                hard_refutations=[],
            ),
            runner_up=None,
            score=2,
            margin=2,
            threshold=5,
            strong=("DETERMINISTIC", "CROSS_MODAL"),
            gate_satisfied=False,
            notes=["score 2 meets the floor but strong evidence is missing"],
        ),
    }


def _trace_for(
    decisions: dict[str, FieldDecision],
) -> dict[str, list[FieldCandidate]]:
    """The candidate set behind each decision, so trace and decisions agree."""
    return {
        field: [decision.winner] if decision.winner is not None else []
        for field, decision in decisions.items()
    }


def _build_result() -> FieldResult:
    decisions = _decisions()
    return FieldResult(
        decisions=decisions,
        trace=_trace_for(decisions),
        extracted={"cuit_emisor": "20-12345678-3"},
        notes=["stub: no model ran"],
    )


#: A fixed result the stub stages hand back: one field confirmed, one in review
#: — enough for the report and the queue to have something real to show.
STUB_RESULT: FieldResult = _build_result()


#: How long each stub waits before answering, so an interrupt or pause test has
#: a real window to act in. Fase B removes the wait together with the stub.
STUB_LATENCY_SECONDS: float = 0.5


def _simulate_work() -> None:
    """Block briefly, standing in for the real stage's adapter call.

    The wait exists only so a run can be interrupted or paused mid-stage — it
    models the latency of the read/extract/decide work, not any of its result.
    """
    time.sleep(STUB_LATENCY_SECONDS)


@dataclasses.dataclass(frozen=True, slots=True)
class StubContext:
    """What a stub stage needs, recorded so a test can assert the hand-off.

    Attributes:
        document: The document being processed.
        work_root: Where the run writes, or ``None``.

    """

    document: str
    work_root: str | None


def stub_read(context: StubContext) -> object:
    """Stage `read`: return a fixed material and say so.

    The value is a plain mapping, not a `Material` — Fase A never constructs the
    adapter's type, and the run process must not depend on its shape. Fase B
    replaces this with the real `Material`.
    """
    _simulate_work()
    return {
        "kind": "pdf",
        "tier": "texto_nativo",
        "route": "layout_text",
        "pages_read": 1,
        "pages_total": 1,
        "notes": [f"stub read of {context.document}"],
    }


def stub_extract(context: StubContext) -> object:
    """Stage `extract`: return a fixed extraction over the material."""
    _simulate_work()
    return {
        "candidates": {"cuit_emisor": ["20-12345678-3"], "total": ["17.898,30"]},
        "values": {"subtotal": "15.000,00", "iva": "2.898,30", "total": "17.898,30"},
        "notes": [f"stub extract of {context.document}"],
    }


def stub_decide(context: StubContext) -> FieldResult:
    """Stage `decide`: return the fixed decision set.

    The context is unused by design: the stub's answer is fixed, so the same
    result is returned whatever document the process hands it — which is the
    point of a stub (Fase A drives the process, not the engine).
    """
    _simulate_work()
    del context
    return STUB_RESULT


def stub_hitl(context: StubContext) -> list[dict[str, object]]:
    """Stage `hitl`: queue every field the engine did not confirm.

    The context is unused by design, for the same reason as `stub_decide`.
    """
    _simulate_work()
    del context
    return [
        {
            "field": "importe_total_facturado",
            "severity": "critica",
            "decision": DECISION_REVIEW,
            "reason_codes": ["REV_GATE_UNMET"],
        }
    ]
