"""The resolver loop: re-entering the engine only with new evidence.

`my_flow.md` §7, reduced to its pure, deterministic half. The resolver derives
candidates with a trace and sends them back to the engine — but a loop that
re-runs the engine over the **same** evidence cannot give a different answer,
so two invariants bound it:

- **A re-entry happens only when the candidate set or the signal set changed**
  (`ESC_NO_NEW_EVIDENCE` when it did not).
- **The loop is capped** at ``max_loops`` (`ESC_LOOP_LIMIT` when exhausted).

The resolver itself — which mechanical validator dirimes a field, and how — is
the caller's; this module owns the loop shape, the change detection and the
reason codes. Nothing here imports an adapter, so the loop is testable with
constructed decisions.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Final

from .fields import FieldDecision, FieldResult

__all__: list[str] = [
    "ESC_LOOP_LIMIT",
    "ESC_NO_NEW_EVIDENCE",
    "MAX_LOOPS",
    "resolver_loop",
    "same_decision_set",
]

#: The reason codes the loop itself produces (§6.5, §7). These are the
#: ``motivo`` of the loop, not of a field.
ESC_NO_NEW_EVIDENCE: Final[str] = "ESC_NO_NEW_EVIDENCE"
ESC_LOOP_LIMIT: Final[str] = "ESC_LOOP_LIMIT"

#: The loop is capped at two re-entries (§7).
MAX_LOOPS: Final[int] = 2


def same_decision_set(
    before: Mapping[str, FieldDecision],
    after: Mapping[str, FieldDecision],
) -> bool:
    """Whether two decision sets are the same evidence, field by field.

    Two sets are *the same* when every field carries the same decision, the
    same winner value and the same reason codes. A changed score or margin does
    **not** count as new evidence — a new candidate or a new signal does, and
    those change the winner or the reason.
    """
    if set(before) != set(after):
        return False
    for field in before:
        left = before[field]
        right = after[field]
        left_value = left.winner.raw_value if left.winner is not None else None
        right_value = right.winner.raw_value if right.winner is not None else None
        if left.decision != right.decision:
            return False
        if left_value != right_value:
            return False
        if list(left.reason_codes) != list(right.reason_codes):
            return False
    return True


def resolver_loop(
    decide: Callable[[], FieldResult],
    resolve: Callable[[FieldResult], bool],
    *,
    max_loops: int = MAX_LOOPS,
) -> FieldResult:
    """Run the decide → resolve → decide loop, bounded and change-aware.

    Args:
        decide: A zero-argument callable that runs the engine over the current
            candidate set and returns the field result. The resolver mutates the
            candidate set between calls; ``decide`` re-reads it.
        resolve: The resolver. It reads the current result, mutates the
            candidate set, and returns ``True`` when it produced a new candidate
            or signal, ``False`` when it had nothing new.
        max_loops: How many re-entries are allowed after the first run.

    Returns:
        The final result. Its notes carry the loop's own reason code when the
        loop stopped early (`ESC_NO_NEW_EVIDENCE`) or exhausted its cap
        (`ESC_LOOP_LIMIT`).

    """
    result = decide()
    previous = result.decisions

    for _ in range(max_loops):
        if not resolve(result):
            result.notes.append(ESC_NO_NEW_EVIDENCE)
            break
        result = decide()
        if same_decision_set(previous, result.decisions):
            result.notes.append(ESC_NO_NEW_EVIDENCE)
            break
        previous = result.decisions
    else:
        result.notes.append(ESC_LOOP_LIMIT)

    return result
