"""Read one corpus-policy value out of the registry (`E07-02` / `S1-T21`).

Every K2-K6 command needs at least one value that is **corpus policy** rather than a
parameter of the call: K2's `min_chars`, K3's legibility threshold. `ADR-009` puts
each of them in the registry with **no override**, so none of them may be a
constructor default, a flag, or a constant in the composition root (`E04-02` records
that resolution for `min_chars`, and `E04-03` for K3's thresholds).

This module is therefore the surface's one doorway to that policy, and it is
**load-or-refuse**. A command whose policy has not loaded reports `asset_missing` or
`asset_invalid` and exits `3`, which reads as *"the call could not be made"* - the
honest outcome, because the alternative is a defaulted threshold, i.e. this surface
deciding what *blank* or *illegible* means.

The value is read from the asset this surface names, not found by searching: a lookup
that hunted for a key would let a policy value move without anything noticing. Which
asset holds which key is data, and the key's namespace is written out at the call
site.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from docflow.kernels import registry as k8
from docflow.kernels.types import Evidence, KernelResult, Reason

__all__: list[str] = ["DEFAULT_ROOT", "POLICY_ASSET", "policy_number"]

#: Where the registry lives unless `--root` says otherwise. Relative, not absolute:
#: an absolute default would make the surface depend on where a checkout happens to
#: live.
DEFAULT_ROOT: Final[str] = "registry"

#: The one asset that holds numeric policy in Stage 1. A mapping from key to asset
#: would be a second place for a value to move, so the key's namespace and this name
#: are read together at the call site.
POLICY_ASSET: Final[str] = "policies/thresholds.json"


def policy_number(root: Path, key: str) -> KernelResult[float]:
    """Read one numeric policy value.

    Args:
        root: The registry root.
        key: The dotted key, e.g. ``reader.min_chars``.

    Returns:
        The value as a float, or no value and a typed reason: an unusable registry,
        an absent key, or a key whose value is not a number. A number is never
        defaulted, and a non-number is never coerced - a threshold read as a string
        would compare against a measurement and silently decide a classification.

    """
    loaded = k8.load_registry(root)
    if loaded.reason is not None:
        return _refusal(root, key, loaded.reason, {"registry": "unusable"})

    asset = loaded.value.assets.get(POLICY_ASSET) if loaded.value else None
    if asset is None:
        return _refusal(
            root,
            key,
            Reason(
                code="asset_missing",
                message=(
                    f"The registry declares no {POLICY_ASSET!r}, which is where this "
                    "surface reads policy. It is not defaulted here: a threshold is "
                    "corpus policy with no override (ADR-009) and has no honest "
                    "fallback."
                ),
            ),
            {"absent": POLICY_ASSET},
        )

    values = json.loads(asset.content.decode("utf-8"))
    if not isinstance(values, dict) or key not in values:
        return _refusal(
            root,
            key,
            Reason(
                code="asset_missing",
                message=(
                    f"{POLICY_ASSET} declares no policy value {key!r}. Refusing "
                    "rather than defaulting: a defaulted threshold changes which "
                    "pages are blank and which images are legible."
                ),
            ),
            {"absent": key},
        )

    value = values[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return _refusal(
            root,
            key,
            Reason(
                code="asset_invalid",
                message=(
                    f"The policy value {key!r} must be a number; it is "
                    f"{type(value).__name__}. Coercing it would put a rendering of "
                    "the value where the value belongs."
                ),
            ),
            {"value_type": type(value).__name__},
        )

    return KernelResult(
        value=float(value),
        evidence=Evidence(
            terms={"registry_root": str(root), "policy_key": key},
            measurements={"value": float(value)},
            observed={"asset": POLICY_ASSET},
        ),
        reason=None,
    )


def _refusal(
    root: Path, key: str, reason: Reason, observed: dict[str, str]
) -> KernelResult[float]:
    """Build the result for a policy value that could not be read.

    Args:
        root: The registry root.
        key: The key that was asked for.
        reason: The typed reason.
        observed: What was observed about the failure.

    Returns:
        No value and the reason.

    """
    return KernelResult(
        value=None,
        evidence=Evidence(
            terms={"registry_root": str(root), "policy_key": key},
            measurements={},
            observed=observed,
        ),
        reason=reason,
    )
