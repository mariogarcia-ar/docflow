"""Corpus policy: the thresholds the registry owns, read rather than restated.

`ADR-009` / `NFR-06a`: corpus policy lives in a K8 asset and is **not settable**
by a flag or an environment variable at any stage. The reason is in `sad.md` §5.1
— the registry hash is a cache-key term, so it is only sound if the registry is
the sole source of every value the hash covers. A threshold that arrived from
somewhere else would change a stage's output without entering the key, and the
ledger would record `done` about a result produced under a setting nothing
recorded.

The measured defect this module closes: `flow/config.py` declared `MIN_CHARS`,
`RENDER_DPI` and `LEGIBILITY_THRESHOLD` as constants, duplicating
`registry/policies/thresholds.json` value for value. Two copies of a threshold
agree the day they are written and are free to disagree afterwards — and here
they had already drifted in *name*: the flow's `render_dpi` is the registry's
`diagnosis.min_dpi`, which is a floor a page must reach, not a render target.
`kernel_cli/commands/policy.py` states the rule these constants break: policy
"may not be a constructor default, a flag, or a constant in the composition
root".

The reader is **load-or-refuse**, the same shape `scripts/poc/_lib.py::policy`
and `kernel_cli/commands/policy.py` use: a key that is not declared raises rather
than falling back, because a defaulted threshold is this module deciding what
*blank* or *illegible* means. `config.py` still carries the numbers — a library
must be able to run without a registry on disk — but they are now marked as the
**fallback** they are, and `read_policy` prefers the registry whenever it is
readable.
"""

from __future__ import annotations

import json
from typing import Final

from ._bootstrap import REGISTRY_ROOT

__all__: list[str] = ["POLICY_ASSET", "read_policy"]

#: The one asset that holds numeric policy. The name is a contract with
#: `kernel_cli/commands/policy.py::POLICY_ASSET` and `scripts/poc/_lib.py`: three
#: callers read the same file, and one of them renaming it would leave the others
#: reading a file that is no longer there.
POLICY_ASSET: Final[str] = "registry/policies/thresholds.json"


def read_policy(key: str) -> float | None:
    """Read one numeric policy value from the registry, or ``None``.

    Returns ``None`` rather than raising for the *registry* being absent or
    unreadable, and that asymmetry is deliberate: a missing registry is a fact
    about the environment a library is running in, so the caller falls back to
    the number it declares. A key that is **absent from a registry that loaded**
    is a different fact — a typo, or a policy that moved — and that one raises,
    because falling back there would hide the drift this module exists to catch.

    Args:
        key: The dotted policy key, e.g. ``reader.min_chars``.

    Returns:
        The declared value as a float, or ``None`` when the registry is not
        readable from here.

    Raises:
        KeyError: When the registry loaded but does not declare ``key``.

    """
    try:
        values = json.loads((REGISTRY_ROOT.parent / POLICY_ASSET).read_text("utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(values, dict):
        return None
    if key not in values:
        raise KeyError(
            f"{POLICY_ASSET} declares no {key!r}; it declares {sorted(values)}. "
            "Refusing rather than defaulting: a threshold that arrived from "
            "nowhere would change a stage's output without entering the "
            "registry hash (`ADR-009`)."
        )
    value = values[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise KeyError(f"{POLICY_ASSET} declares {key!r} as {value!r}, not a number")
    return float(value)
