"""The one way a command says *this call could not be made* (`E07-02` / `S1-T21`).

Five command modules had their own helper building the same value: a `KernelResult`
with no value, empty evidence and a typed reason. The duplication was **real** - the
same shape written four times, so a change to what a refusal carries would have had to
be made in four places, and three of them would have been forgotten.

Extracting it is the same call `E04-03` made for the two vendor-refusal classes and
`E07-02` made for the page parser: when two copies have the same *risk* rather than
merely the same *lines*, sharing them is what keeps the risk in one place.

Why a refusal is a `KernelResult` rather than an exception
----------------------------------------------------------

`kernel-cli.md` §5 gives a call that could not legitimately be made its own exit (`3`),
distinct from both *the document's answer* (`2`) and *a bug* (`1`). An exception would
reach exit `1`, collapsing *"this flag is missing"* into *"the code is broken"* - the
one distinction the exit table exists to make. So a command that cannot proceed
returns this, and the dispatcher's `REASON_CODE_EXITS` places it at `3`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from docflow.kernels.types import Evidence, KernelResult, Reason

__all__: list[str] = ["answered", "missing", "refusal"]

#: The observed key saying what a refusal was blocked by. Declared so the four
#: callers cannot each invent a different spelling of the same fact.
BLOCKED_BY: str = "blocked_by"

#: What stopped a call whose caller did not name something the call requires. The
#: same word whichever name is missing - an asset, a key, a root - because "the caller
#: did not say which" is one condition, and a per-command synonym would make it look
#: like three.
BLOCKED_MISSING: str = "missing_parameter"


def missing(message: str) -> KernelResult[Any]:
    """Build the refusal for a call that named no value for a required parameter.

    The *message* is an argument because what the omission costs differs per command
    and the caller is the only one who knows: no root lists the wrong tree, no asset
    names no keys. Everything else about the refusal is the same, which is why this
    exists rather than each command writing the same four-line value out.

    Args:
        message: Why the call cannot proceed without the parameter.

    Returns:
        The result, carrying no value and the ``missing_parameter`` block reason.

    """
    return refusal(
        Reason(code="asset_missing", message=message), blocked_by=BLOCKED_MISSING
    )


def refusal(
    reason: Reason,
    *,
    blocked_by: str,
    terms: Mapping[str, str] | None = None,
    measurements: Mapping[str, float] | None = None,
    observed: Mapping[str, str] | None = None,
) -> KernelResult[Any]:
    """Build the result for a call that could not be made.

    Args:
        reason: The typed reason, whose code decides the exit (`kernel-cli.md` §5).
        blocked_by: What stopped the call - a missing parameter, an unusable policy
            value, an unimplemented flag. Required rather than defaulted: it is the
            one field that says *why* this is a precondition failure, and a default
            would make it a field nobody reads.
        terms: The evidence terms, when the caller has any.
        measurements: The evidence measurements. Empty is a real state: a call that
            did not happen measured nothing.
        observed: Extra observations, merged with ``blocked_by``.

    Returns:
        The result, carrying no value.

    """
    merged = {BLOCKED_BY: blocked_by}
    if observed is not None:
        merged.update(observed)
    return KernelResult(
        value=None,
        evidence=Evidence(
            terms=dict(terms) if terms is not None else {},
            measurements=dict(measurements) if measurements is not None else {},
            observed=merged,
        ),
        reason=reason,
    )


def answered(
    value: object,
    *,
    terms: Mapping[str, str],
    measurements: Mapping[str, float],
    observed: Mapping[str, str] | None = None,
) -> KernelResult[Any]:
    """Build a result from a value and what was measured about producing it.

    Two commands answer with a list derived by reading a tree - K1's `jobs` and K7's
    `ls` - and both built the same envelope by hand. Sharing it keeps the shape in one
    place, so a change to what evidence a listing carries reaches both.

    Args:
        value: The value to report.
        terms: The evidence terms - what the answer is *about*.
        measurements: What was counted to produce it.
        observed: Extra observations about how it was produced.

    Returns:
        A result with a value and no reason: the question was answered, even when the
        answer is an empty list.

    """
    return KernelResult(
        value=value,
        evidence=Evidence(
            terms=dict(terms),
            measurements=dict(measurements),
            observed=dict(observed) if observed is not None else {},
        ),
        reason=None,
    )
