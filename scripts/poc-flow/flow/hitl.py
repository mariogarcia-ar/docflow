"""The human-in-the-loop step: the fields the engine could not confirm.

`my_flow.md` §8, reduced to the mechanical half. A field whose decision is
`REVIEW` or `ESCALATE` is a **pending** item: the engine did not confirm it, and
a person must look. This module turns those fields into a queue and, when a
frontier credential is present, asks the frontier model to **suggest** an answer
against the original document — a suggestion is evidence, never a decision.

The split mirrors `scripts/poc/hitl.py`'s honest boundaries:

- **A suggestion is a candidate, not a verdict.** It carries the document it
  came from and the frontier model's name, and it is never folded back into the
  engine's score. Confirming it is a human's act (`my_flow.md` I6).
- **No credential is a real state, not a failure.** The queue is still written;
  only the suggestion step refuses, and the queue survives it.
- **The frontier is not exempt from the refuters.** §8 runs the mechanical
  validators over `campos_frontier` too; this module re-uses the same rule by
  sending only the disputed fields, so the arithmetic and the CUIT checksum
  still apply where they can.
"""

from __future__ import annotations

# `wrong-import-order` / `wrong-import-position`: `docflow.adapters.frontier` is
# only importable once `_bootstrap` puts `src/` on `sys.path`, so the adapter
# import must follow `ensure_docflow_importable()`. The order is load-bearing,
# not cosmetic — the same rule `material.py` and `extract.py` document.
# `too-few-public-methods`: `PendingItem` and `Suggestion` are records the flow
# hands between stages; their fields are the contract, not their methods.
# pylint: disable=wrong-import-order, wrong-import-position, too-few-public-methods
import json
from collections.abc import Mapping
from typing import Any, Final

from ._bootstrap import ensure_docflow_importable

ensure_docflow_importable()

from docflow.adapters.frontier import FrontierEngine  # noqa: E402

from .config import Config  # noqa: E402
from .fields import (  # noqa: E402
    DECISION_ESCALATE,
    DECISION_REVIEW,
    FieldDecision,
)
from .material import Material  # noqa: E402

__all__: list[str] = [
    "SUGGESTION_SCHEMA",
    "PendingItem",
    "Suggestion",
    "pending_items",
    "suggest",
]

#: A pending item is a field the engine could not confirm.
PENDING_DECISIONS: Final[frozenset[str]] = frozenset(
    {DECISION_REVIEW, DECISION_ESCALATE}
)

#: The shape a frontier suggestion must satisfy. One entry per disputed field,
#: a per-field answer and a reason — never an aggregate confidence, because an
#: aggregate is the score this project forbids (`my_flow.md` §9).
SUGGESTION_SCHEMA: Final[dict[str, object]] = {
    "type": "object",
    "properties": {
        "suggestions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "field": {"type": "string"},
                    "suggested_value": {"type": ["string", "null"]},
                    "reason": {"type": "string"},
                },
                "required": ["field", "suggested_value", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["suggestions"],
    "additionalProperties": False,
}


class PendingItem:
    """One field the engine could not confirm, queued for a human.

    Attributes:
        field: The field name.
        severity: The field's severity.
        decision: Why it is pending — ``REVIEW`` or ``ESCALATE``.
        reason_codes: The engine's stable reason codes.
        winner: The best candidate the engine had, or ``None``.
        runner_up: The next-best, or ``None``.

    """

    def __init__(  # pylint: disable=too-many-arguments, too-many-positional-arguments
        self,
        field: str,
        severity: str,
        decision: str,
        reason_codes: list[str],
        winner: Any,
        runner_up: Any,
    ) -> None:
        self.field = field
        self.severity = severity
        self.decision = decision
        self.reason_codes = list(reason_codes)
        self.winner = winner
        self.runner_up = runner_up


class Suggestion:
    """The frontier model's suggested answer for one pending field.

    Attributes:
        field: The field name.
        suggested_value: The proposed value, or ``None`` when the frontier
            declined to answer.
        reason: Why, in the frontier's own words.

    """

    def __init__(self, field: str, suggested_value: str | None, reason: str) -> None:
        self.field = field
        self.suggested_value = suggested_value
        self.reason = reason


def pending_items(
    decisions: Mapping[str, FieldDecision],
) -> list[PendingItem]:
    """The fields the engine did not confirm, in stable order.

    Args:
        decisions: The engine's per-field verdicts.

    Returns:
        The pending items. A CONFIRMED field is never queued.

    """
    items: list[PendingItem] = []
    for field in sorted(decisions):
        decision = decisions[field]
        if decision.decision not in PENDING_DECISIONS:
            continue
        items.append(
            PendingItem(
                field=field,
                severity=decision.severity,
                decision=decision.decision,
                reason_codes=decision.reason_codes,
                winner=decision.winner,
                runner_up=decision.runner_up,
            )
        )
    return items


def suggest(
    items: list[PendingItem],
    material: Material,
    config: Config,
    document_name: str,
) -> tuple[list[Suggestion], str]:
    """Ask the frontier model to suggest an answer for each pending field.

    The frontier reads the original document — the rendered images when the
    document has them, the text otherwise (`my_flow.md` §8: the frontier reads
    the original, not just the JSON). A missing credential is a real state: the
    suggestions are empty and the note says why, and the queue is unaffected.

    Args:
        items: The pending fields.
        material: The document's text and rendered pages.
        config: The run's dials.
        document_name: The document's file name, for the prompt.

    Returns:
        The suggestions, and a note when the call refused. A suggestion's
        ``suggested_value`` is ``None`` when the frontier declined.

    """
    if not items:
        return [], ""

    engine = FrontierEngine()

    # The frontier suggests from the **material the engine already read**, not by
    # re-reading: a second read is a second answer, and the frontier is asked
    # about the disputed fields, not to re-extract the whole document.
    disputed = json.dumps(
        [
            {
                "field": item.field,
                "reason_codes": item.reason_codes,
                "winner": (item.winner.raw_value if item.winner is not None else None),
            }
            for item in items
        ],
        ensure_ascii=False,
    )

    prompt = (
        "You are shown an extraction the local engine could not confirm. For "
        "each disputed field, suggest the value the original document supports. "
        "Read the document; do not infer a value you cannot see. Answer only "
        "with the JSON the schema asks for.\n\n"
        f"Document: {document_name}\n\n"
        f"Disputed fields: {disputed}\n\n"
    )

    if material.text:
        prompt += f"Document text:\n{material.text}\n"

    if material.images:
        attempt = engine.vision(
            config.frontier_model,
            prompt,
            material.images,
            SUGGESTION_SCHEMA,
        )
    else:
        attempt = engine.structured(config.frontier_model, prompt, SUGGESTION_SCHEMA)

    if attempt.value is None:
        code = attempt.reason.code if attempt.reason else "unknown"
        return [], f"frontier refused: {code}"

    answered = dict(attempt.value)
    raw = answered.get("suggestions")
    if not isinstance(raw, list):
        return [], "frontier answered without suggestions"

    suggestions: list[Suggestion] = []
    for entry in raw:
        if not isinstance(entry, Mapping):
            continue
        suggestions.append(
            Suggestion(
                field=str(entry.get("field", "")),
                suggested_value=(
                    None
                    if entry.get("suggested_value") is None
                    else str(entry["suggested_value"])
                ),
                reason=str(entry.get("reason", "")),
            )
        )
    return suggestions, ""
