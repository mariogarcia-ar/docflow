"""The human-in-the-loop step, reduced to the mechanical half.

`my_flow.md` §8: a field whose decision is `REVIEW` or `ESCALATE` is a
**pending** item — the engine did not confirm it, and a person must look. This
module turns those fields into a queue and folds a human's confirmations in.

It is the adapter-free half of `scripts/poc-flow/flow/hitl.py`. The frontier
suggestion (`suggest`) needs `FrontierEngine`, which is Fase B2 (the adapter
plumbing); it is marked here rather than faked, so the queue — the deliverable
of §8's mechanical half — is real while the suggestion stays honest.

Two boundaries are enforced, never silent:

- **Only a pending field may be confirmed** (`my_flow.md` I6): confirming a
  field the engine already CONFIRMED is an out-of-band edit, and it is refused.
- **An empty value is not a decision.**

Everything here is pure: it reads the engine's decisions and returns records,
so it is testable without an adapter or a document.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from .fields import DECISION_ESCALATE, DECISION_REVIEW, FieldDecision

# `too-few-public-methods`: `PendingItem` and `HumanConfirmation` are records the
# flow hands between stages — their fields, not their methods, are the contract
# (`my_flow.md` B.15), the same reasoning v1's `hitl.py` states.
# pylint: disable=too-few-public-methods

__all__: list[str] = [
    "HumanConfirmation",
    "PendingItem",
    "apply_confirmations",
    "pending_items",
]

#: A pending item is a field the engine could not confirm.
PENDING_DECISIONS: Final[frozenset[str]] = frozenset(
    {DECISION_REVIEW, DECISION_ESCALATE}
)


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


class HumanConfirmation:
    """One field's value, settled by a human.

    This is the only ground truth the flow recognises (`my_flow.md` I6, I7): a
    value here is what a person decided, after looking at the document and the
    engine's candidates. It is **never** produced by a model.

    Attributes:
        field: The field name.
        value: The confirmed value, exactly as entered.
        note: Why, in the person's own words, or ``""``.

    """

    def __init__(self, field: str, value: str, note: str = "") -> None:
        self.field = field
        self.value = value
        self.note = note


def pending_items(decisions: Mapping[str, FieldDecision]) -> list[PendingItem]:
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


def apply_confirmations(
    confirmations: list[HumanConfirmation],
    pending: Mapping[str, PendingItem],
) -> tuple[dict[str, str], list[str]]:
    """Fold a human's confirmations into a settled per-field answer.

    Only a field that is **pending** may be confirmed (`my_flow.md` I6): a
    value the engine already CONFIRMED was not queued, so a confirmation for it
    is not a human decision — it is an out-of-band edit, and it is refused with
    a reason rather than silently folded in.

    Args:
        confirmations: What the person decided.
        pending: The queued fields, keyed by field name.

    Returns:
        The settled values (field to confirmed value), and the refusal notes for
        confirmations that named a non-pending field.

    """
    settled: dict[str, str] = {}
    refusals: list[str] = []
    for confirmation in confirmations:
        if confirmation.field not in pending:
            refusals.append(
                f"{confirmation.field!r} is not pending; a human may confirm "
                "only a field the engine could not decide"
            )
            continue
        if not confirmation.value.strip():
            refusals.append(
                f"{confirmation.field!r} was confirmed with an empty value, "
                "which is not a decision"
            )
            continue
        settled[confirmation.field] = confirmation.value
    return settled, refusals
