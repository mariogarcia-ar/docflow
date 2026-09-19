"""Shared reading of a generation's structured answer, and the request that earns it.

Two adapters parse the same thing — a completion that must be a JSON **object** —
from two vendors that agree on nothing else. The rule is what is shared, not the
transport, so it lives here rather than in either adapter or in a port: it is not an
interface anything must satisfy, and it names no kernel and no vendor.

Keeping it in one place is what stops the rule from drifting into two versions. The
failure mode this guards against is subtle and identical on both paths: a completion
that is *valid JSON but not an object* cannot satisfy a schema, and reporting it as an
absence would make it indistinguishable from a model that said nothing.

Both ends of that rule live here, because they are one rule. :func:`load_object` reads
the answer; :data:`JSON_ANSWER_INSTRUCTION` is the sentence that makes a prose-shaped
request produce an answer worth reading. **A schema does not do that on its own** — it
constrains an answer that is already JSON, and an instruction that never says *JSON*
leaves the model free to reply in sentences. Measured on the frontier path: a rubric
asking for a per-field judgement came back as 1138 completion tokens of reasoning and
a text block, with no tool call anywhere in the response.
"""

from __future__ import annotations

import json
from typing import Any, Final

__all__: list[str] = ["JSON_ANSWER_INSTRUCTION", "load_object"]

#: The sentence a caller that needs an object appends when its own instruction asks for
#: a *judgement* rather than for a *shape*.
#:
#: It exists because the answer's shape has to be asked for in words and not only in the
#: schema. The schema reaches the provider as a tool definition, and a provider that
#: does
#: not choose to call the tool answers in prose instead — the request was
#: well-formed and the schema was a perfectly valid (if empty) object, and the model
#: still replied in paragraphs, because nothing in the prompt asked for anything else.
#: The refusal that results is typed and honest (`unsupported_format`, with the raw
#: completion preserved), but it is the *caller's* sentence that produced it.
#:
#: It says *object* and not *tool*, because it is appended ahead of the samples and must
#: stay true whatever the adapter sends underneath: pinning a tool is the provider's
#: answer to give (see `frontier_providers`), and an instruction naming a mechanism the
#: provider may refuse would be a promise this module cannot keep.
JSON_ANSWER_INSTRUCTION: Final[str] = (
    "Answer with a single JSON object. Do not answer in prose, and do not wrap the "
    "object in a code fence."
)


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
