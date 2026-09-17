"""Shared reading of a generation's structured answer.

Two adapters parse the same thing — a completion that must be a JSON **object** —
from two vendors that agree on nothing else. The rule is what is shared, not the
transport, so it lives here rather than in either adapter or in a port: it is not an
interface anything must satisfy, and it names no kernel and no vendor.

Keeping it in one place is what stops the rule from drifting into two versions. The
failure mode this guards against is subtle and identical on both paths: a completion
that is *valid JSON but not an object* cannot satisfy a schema, and reporting it as an
absence would make it indistinguishable from a model that said nothing.
"""

from __future__ import annotations

import json
from typing import Any

__all__: list[str] = ["load_object"]


def load_object(raw: str) -> tuple[dict[str, Any] | None, str | None]:
    """Parse a completion that must be a JSON object.

    Args:
        raw: The completion text, exactly as the model produced it.

    Returns:
        The parsed object and ``None``, or ``None`` and a message naming why the text
        is not a usable object. The message is **not** a ``Reason``: the caller
        composes its own refusal, because the codes, terms and measurements differ
        between the two kernels and this module owns none of them.

    """
    try:
        parsed = json.loads(raw)
    except ValueError:
        return None, (
            "the model's answer was not valid JSON. The raw completion is preserved "
            "so the input can be inspected; reporting a value here would make a "
            "parse failure the same outcome as a model that returned nothing."
        )

    if not isinstance(parsed, dict):
        return None, (
            "the model's answer was valid JSON but not an object, so it cannot "
            f"satisfy a schema: {type(parsed).__name__}"
        )

    return parsed, None
