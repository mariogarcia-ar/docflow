"""The data model the engine decides over, and the field vocabulary.

This is the "runtime data contract" `my_flow.md` names as the next deliverable:
:class:`EvidenceSignal` (with its ``result``), :class:`FieldCandidate`,
:class:`FieldDecision` (with reason codes) and the trace they sit in. The shapes
come almost literally from §5 and §6.5.

`my_flow.md` I2 lives here: the score belongs to the candidate, and candidates
with the same ``normalized_value`` merge **before** scoring.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable
from typing import Final

# `too-many-instance-attributes`: `FieldDecision` is the engine's per-field
# verdict and its shape is the contract of `my_flow.md` §6.5 — splitting it
# would move the same names one frame away without adding behaviour.
# pylint: disable=too-many-instance-attributes

__all__: list[str] = [
    "DECISION_CONFIRMED",
    "DECISION_ESCALATE",
    "DECISION_REVIEW",
    "FAIL",
    "FIELD_SEVERITY",
    "IVA_FIELD",
    "PASS",
    "REASON_CODES",
    "SUBTOTAL_FIELD",
    "TOTAL_FIELD",
    "UNKNOWN",
    "EvidenceSignal",
    "Extraction",
    "FieldCandidate",
    "FieldDecision",
    "FieldResult",
    "NormalizedField",
    "normalize",
    "normalized_value",
    "raw_for",
]

#: The three validator states (`my_flow.md` I10). UNKNOWN scores nothing,
#: penalises nothing and never vetoes.
PASS: Final[str] = "PASS"
FAIL: Final[str] = "FAIL"
UNKNOWN: Final[str] = "UNKNOWN"

#: The three engine outcomes (`my_flow.md` §6.5).
DECISION_CONFIRMED: Final[str] = "CONFIRMED"
DECISION_REVIEW: Final[str] = "REVIEW"
DECISION_ESCALATE: Final[str] = "ESCALATE"

#: The three fields the arithmetic validator combines (`my_flow.md` §6.4).
#: The names are the schema's — `importe_total_facturado`, not `total` — because
#: the schema and the registry are the downstream contract and the engine adapts
#: to them. A single owner keeps the triple consistent across `engine`,
#: `extract` and `validators`.
SUBTOTAL_FIELD: Final[str] = "subtotal"
IVA_FIELD: Final[str] = "iva"
TOTAL_FIELD: Final[str] = "importe_total_facturado"

#: Which severity each field belongs to (`my_flow.md` §6.5). Everything else is
#: ``baja`` — an unknown field must not be silently treated as critical.
FIELD_SEVERITY: Final[dict[str, str]] = {
    "importe_total_facturado": "critica",
    "iva": "critica",
    "cuit_emisor": "alta",
    "fecha_emision": "alta",
    "razon_social_emisor": "media",
    "descripcion": "baja",
    "categoria_gasto": "baja",
}

#: The stable reason codes (`my_flow.md` §6.5). These are the ``motivo`` of an
#: escalation and the base of every metric; a decision must name one or more.
REASON_CODES: Final[frozenset[str]] = frozenset(
    {
        "CONF_SCORE_MARGIN_GATE",
        "REV_SCORE_MID",
        "REV_CLOSE_MARGIN",
        "REV_GATE_UNMET",
        "REV_REVIEWER_CONFLICT",
        "REV_QR_CONFLICT",
        "ESC_LOW_SCORE",
        "ESC_ALL_VETOED",
        "ESC_NO_UNIQUE_ARITHMETIC_COMBINATION",
        "ESC_MISSING_STRONG_EVIDENCE",
        "ESC_QR_CONFLICT",
        "ESC_NO_NEW_EVIDENCE",
        "ESC_LOOP_LIMIT",
        "ESC_DEGRADED_MATERIAL",
        "CLASSIFY_NOT_A_RECEIPT",
    }
)

#: The code the classification gate refuses with (`my_flow.md` §3). It is not an
#: ``ESC_`` code: a document that is not a receipt did not escalate — it was
#: discarded before extraction, which is a different outcome and so a different
#: word. Named here rather than in `classify.py` because this module is the one
#: owner of the vocabulary.
CLASSIFY_NOT_A_RECEIPT: Final[str] = "CLASSIFY_NOT_A_RECEIPT"

#: The code a material that could not be read at all escalates with (§6.5). It
#: is an ``ESC_`` code because §2 sends a degraded material straight to the
#: ladder, unlike a non-receipt, which is discarded. Distinct from
#: :data:`CLASSIFY_NOT_A_RECEIPT` on purpose (B.9): *we could not read it* and
#: *we read it and it is not a receipt* are different findings, and collapsing
#: them makes a document nobody managed to read look like a bad receipt.
ESC_DEGRADED_MATERIAL: Final[str] = "ESC_DEGRADED_MATERIAL"

#: Characters that are not digits or the CUIT's own hyphen, for the CUIT rule:
#: the value is cut at the first character that is not a digit or the hyphen
#: that belongs to the number itself.
_CUIT_KEEP: Final[str] = "0123456789-"


def normalized_value(raw: str | None) -> str:
    """The comparison key for a candidate's value.

    Only formatting is removed — thousands separators (`.` and `,`), a currency
    symbol, and surrounding whitespace. The printed value is **never** rewritten
    as a number, so no zero is dropped and no separator becomes data
    (`my_flow.md` §5).
    """
    if raw is None:
        return ""
    text = raw.strip()
    if text.upper().startswith("$"):
        text = text[1:]
    return "".join(ch for ch in text if ch not in "., ")


def normalize(raw: str | None) -> str:
    """Alias of :func:`normalized_value`, kept as the public name in the flow."""
    return normalized_value(raw)


def raw_for(raw: str | None) -> str:
    """The printed value as stored, with a stable stand-in for the absent case.

    The flow never learns from a raw reading, so a missing value is kept as an
    explicit ``""`` rather than ``None``: *no value* is a state a decision can
    branch on, and ``None``-without-reason is the silent stand-in this project
    forbids.
    """
    return "" if raw is None else raw


@dataclasses.dataclass(frozen=True, slots=True)
class EvidenceSignal:
    """One signal the engine scores a candidate with (`my_flow.md` §6.2).

    Attributes:
        family: The evidence family — ``DETERMINISTIC``, ``DOCUMENT_CONTENT``,
            ``CROSS_MODAL``, ``SAME_MATERIAL``, ``LAYOUT_HISTORY``, or a
            negative one.
        result: One of :data:`PASS`, :data:`FAIL`, :data:`UNKNOWN`.
        points: The points the family is worth when ``result`` is PASS. Kept on
            the signal so the engine reads the table from the config, not from
            the signal itself.
        detail: What produced the signal, e.g. ``"B agree"`` or a rule name.
        verified: For ``DOCUMENT_CONTENT``: whether the anchor was mechanically
            verified. Ignored for other families.

    """

    family: str
    result: str
    points: int
    detail: str
    verified: bool = False


@dataclasses.dataclass(frozen=True, slots=True)
class FieldCandidate:
    """One candidate for one field, after merging by ``normalized_value``.

    Attributes:
        normalized_value: The comparison key (§5).
        raw_value: The printed value, preserved (§5).
        producers: Who produced it — ``extractor_llm_texto``, ``regexp``,
            ``vision``, ``reviewer_suggested``.
        signals: The evidence signals, one per family after the family cap is
            applied.
        hard_refutations: The veto reasons. When non-empty, the candidate is
            vetoed and no score can compensate (`my_flow.md` I3).

    """

    normalized_value: str
    raw_value: str
    producers: list[str]
    signals: list[EvidenceSignal]
    hard_refutations: list[str]

    @property
    def vetoed(self) -> bool:
        """Whether a hard refutation invalidates this candidate."""
        return bool(self.hard_refutations)


def merge_candidates(
    candidates: Iterable[FieldCandidate],
) -> list[FieldCandidate]:
    """Merge candidates that share a ``normalized_value`` into one.

    The merge is by value only (`my_flow.md` I2): producers, signals and hard
    refutations concatenate. Without this, ``"125.340,50"`` and ``"125340.5"``
    would appear as competitors and the margin would collapse to zero.
    """
    merged: dict[str, FieldCandidate] = {}
    for candidate in candidates:
        key = candidate.normalized_value
        if key not in merged:
            merged[key] = FieldCandidate(
                normalized_value=key,
                raw_value=candidate.raw_value,
                producers=[],
                signals=[],
                hard_refutations=[],
            )
        slot = merged[key]
        for producer in candidate.producers:
            if producer not in slot.producers:
                slot.producers.append(producer)
        slot.signals.extend(candidate.signals)
        slot.hard_refutations.extend(candidate.hard_refutations)
    return list(merged.values())


@dataclasses.dataclass(frozen=True, slots=True)
class FieldDecision:
    """The engine's verdict for one field (`my_flow.md` §6.5).

    Attributes:
        field: The field name.
        severity: One of the four severities.
        decision: :data:`DECISION_CONFIRMED`, :data:`DECISION_REVIEW` or
            :data:`DECISION_ESCALATE`.
        reason_codes: One or more of :data:`REASON_CODES`.
        winner: The winning candidate, or ``None`` when the field escalates with
            no candidate.
        runner_up: The next-best candidate, or ``None``.
        score: The winner's score, or 0.
        margin: Winner minus runner-up score.
        threshold: The confirmation floor that applied.
        strong: The strong-evidence families this severity required.
        gate_satisfied: Whether the strong-evidence gate was met.
        notes: Human-readable detail.

    """

    field: str
    severity: str
    decision: str
    reason_codes: list[str]
    winner: FieldCandidate | None
    runner_up: FieldCandidate | None
    score: int
    margin: int
    threshold: int
    strong: tuple[str, ...]
    gate_satisfied: bool
    notes: list[str]


@dataclasses.dataclass(frozen=True, slots=True)
class NormalizedField:
    """A field as a producer handed it back, before candidates form.

    Attributes:
        field: The field name.
        raw_value: The printed value.
        normalized: The comparison key.
        producer: Who produced it.

    """

    field: str
    raw_value: str
    normalized: str
    producer: str


@dataclasses.dataclass(frozen=True, slots=True)
class FieldResult:
    """The whole engine's answer for one document.

    Attributes:
        decisions: Field name to :class:`FieldDecision`.
        trace: The candidates and signals that produced each decision, for audit.
        extracted: Field name to the chosen raw value, for a confirmed field.
        notes: Document-level notes (degraded material, missing lanes).

    """

    decisions: dict[str, FieldDecision]
    trace: dict[str, list[FieldCandidate]]
    extracted: dict[str, str]
    notes: list[str]


@dataclasses.dataclass(frozen=True, slots=True)
class Extraction:
    """What the producers handed back, before the engine merges and scores.

    The `extract` stage's artifact: the unmerged candidates per field, the
    document-level values the arithmetic combination needs, and the stage's
    notes. The engine consumes this and returns a :class:`FieldResult`.

    Attributes:
        candidates: Field name to the list of unmerged candidates.
        values: Document-level values (subtotal, IVA, total).
        notes: A refused call, a skipped lane.

    """

    candidates: dict[str, list[FieldCandidate]]
    values: dict[str, str]
    notes: list[str]


def severity_for(field: str) -> str:
    """The severity a field maps to, defaulting to ``baja``."""
    return FIELD_SEVERITY.get(field, "baja")
