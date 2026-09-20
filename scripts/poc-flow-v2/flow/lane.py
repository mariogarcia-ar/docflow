"""Lane-on-demand: the ladder the Anexo A requires before escalating.

`my_flow.md` §6.5: a critical field in native text with no deterministic signal
and no cross-lane agreement is the one cell the Anexo A leaves unreachable — and
the ladder's answer is to run the vision lane on demand *before* escalating,
never to lower the threshold. This module owns the pure, testable half: which
fields still need a lane, and why.

The render itself is the caller's: a native-text PDF has no rendered pages until
one is asked for, and that call is an adapter concern. The detection here is what
makes the ladder checkable without paying for a render.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from .fields import FieldDecision

__all__: list[str] = [
    "MISSING_STRONG_EVIDENCE",
    "needs_vision_lane",
]

#: The reason code a field that still cannot close the strong-evidence gate
#: after every available lane has run escalates with (§6.5).
MISSING_STRONG_EVIDENCE: Final[str] = "ESC_MISSING_STRONG_EVIDENCE"


def needs_vision_lane(
    decisions: Mapping[str, FieldDecision],
) -> dict[str, list[str]]:
    """The critical fields whose gate is still unmet and why, for the ladder.

    A field needs the vision lane when it is **critical**, its decision is
    `REVIEW` with an unmet gate, and its winner has no strong-evidence signal.
    That is exactly the Anexo A cell: without a deterministic rule or a
    cross-lane agreement, the ladder runs vision on demand before escalating.

    Args:
        decisions: The engine's per-field verdicts.

    Returns:
        Field name to the strong families still missing. An empty mapping when
        every critical field closed or has the evidence it needs.

    """
    needed: dict[str, list[str]] = {}
    for field, decision in decisions.items():
        if decision.severity != "critica":
            continue
        if decision.decision != "REVIEW":
            continue
        if decision.gate_satisfied:
            continue
        winner = decision.winner
        strong = list(decision.strong)
        present = {
            signal.family
            for signal in (winner.signals if winner is not None else [])
            if signal.result == "PASS"
        }
        missing = [family for family in strong if family not in present]
        if missing:
            needed[field] = missing
    return needed
