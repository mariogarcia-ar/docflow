"""Learning: the two confirmation channels and the template lifecycle.

`my_flow.md` §9, reduced to its pure, deterministic half. The engine confirms
fields (`SYSTEM_CONFIRMED`); a human settles the rest (`HUMAN_CONFIRMED`). Only
the human channel is ground truth, and only it activates anything with an
effect on the score (I7) — an error systematic across every model cannot teach
itself.

This module owns the rules, not the persistence: template states, activation
counts, and the audit sampling rates. The store is the caller's.
"""

from __future__ import annotations

from typing import Final

__all__: list[str] = [
    "HUMAN_CONFIRMED",
    "SYSTEM_CONFIRMED",
    "TEMPLATE_ACTIVE",
    "TEMPLATE_RETIRED",
    "TEMPLATE_SHADOW",
    "TEMPLATE_STALE",
    "activate_template",
    "audit_rate_for",
    "template_state",
]

#: The two confirmation channels (§9). SYSTEM_CONFIRMED feeds shadow statistics
#: only; HUMAN_CONFIRMED is ground truth.
SYSTEM_CONFIRMED: Final[str] = "SYSTEM_CONFIRMED"
HUMAN_CONFIRMED: Final[str] = "HUMAN_CONFIRMED"

#: The template lifecycle states (§9).
TEMPLATE_SHADOW: Final[str] = "shadow"
TEMPLATE_ACTIVE: Final[str] = "active"
TEMPLATE_STALE: Final[str] = "stale"
TEMPLATE_RETIRED: Final[str] = "retired"

#: How many human confirmations a template needs to go from shadow to active.
#: Initial value, uncalibrated (§9).
ACTIVATION_COUNT: Final[int] = 3

#: The initial audit rate per severity (§9), sampled from the SYSTEM_CONFIRMED
#: set so calibration is not circular.
AUDIT_RATES: Final[dict[str, float]] = {
    "critica": 0.20,
    "alta": 0.10,
    "media": 0.05,
    "baja": 0.02,
}


def template_state(
    *,
    sample_count_human: int,
    last_seen_days: int = 0,
    stale_after_days: int = 30,
) -> str:
    """The state a template is in, from its confirmed samples and age.

    A template is active once ``ACTIVATION_COUNT`` humans confirmed it
    consistently; it goes stale when not seen for ``stale_after_days`` (or when
    a human confirmed a different layout, which the caller passes as a state
    change). A shadow template has human samples below the activation count.
    """
    if sample_count_human >= ACTIVATION_COUNT:
        if last_seen_days > stale_after_days:
            return TEMPLATE_STALE
        return TEMPLATE_ACTIVE
    return TEMPLATE_SHADOW


def activate_template(
    confirmed_consistent: bool,
    *,
    sample_count_human: int,
) -> tuple[str, bool]:
    """Record one human confirmation against a template and return its new state.

    Args:
        confirmed_consistent: Whether the confirmation agreed with the template
            (an inconsistent one is a new layout, so the template goes stale).
        sample_count_human: The consistent human confirmations so far.

    Returns:
        ``(new_state, newly_active)``. Only ``HUMAN_CONFIRMED`` activates a
        template (`my_flow.md` I7); a shadow template with enough consistent
        confirmations becomes active.
    """
    if not confirmed_consistent:
        return TEMPLATE_STALE, False
    new_count = sample_count_human + 1
    state = template_state(sample_count_human=new_count)
    return state, state == TEMPLATE_ACTIVE and sample_count_human < ACTIVATION_COUNT


def audit_rate_for(severity: str) -> float:
    """The audit rate for a confirmed field's severity (§9).

    The rate is sampled from the SYSTEM_CONFIRMED set, not from itself: without
    the sample, calibration would measure the engine against its own
    confirmations and could not estimate the false-confirmation rate.
    """
    return AUDIT_RATES.get(severity, 0.05)
