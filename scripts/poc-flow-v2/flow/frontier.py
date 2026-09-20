"""The frontier step: suggestions for the fields the engine could not confirm.

`my_flow.md` §8, the half that needs the adapter. The frontier reads the
original document (text or rendered pages) and suggests a value per disputed
field. Three boundaries are kept, never silent:

- **A suggestion is evidence, never a verdict** (`my_flow.md` I6): it is written
  to `resolution.json` and a human settles it; it is never folded back into the
  engine's score.
- **No credential is a real state, not a failure**: the queue survives, the
  suggestion step refuses, and the reason is a note.
- **The frontier is not exempt from the refuters** (§8): only the disputed
  fields are sent, so the mechanical validators still apply where they can.
"""

from __future__ import annotations

# `wrong-import-order` / `wrong-import-position`: the `docflow` adapter is only
# importable once `_bootstrap` puts `src/` on `sys.path`, so the import must
# follow `ensure_docflow_importable()`. The order is load-bearing — the same
# rule `extract.py` and `material.py` document.
# pylint: disable=wrong-import-order, wrong-import-position
import json
from collections.abc import Mapping
from typing import Final

from ._bootstrap import ensure_docflow_importable

ensure_docflow_importable()

from docflow.adapters.frontier import FrontierEngine  # noqa: E402

from .config import Config  # noqa: E402
from .hitl import SUGGESTION_SCHEMA, PendingItem, Suggestion  # noqa: E402
from .material import Material  # noqa: E402

__all__: list[str] = [
    "suggest",
]

#: The frontier is reached only when the engine could not settle a field; the
#: prompt asks it to read the document and suggest, not to re-extract.
_EMPTY_NOTE: Final[str] = ""


def suggest(
    items: list[PendingItem],
    material: Material,
    config: Config,
    document_name: str,
) -> tuple[list[Suggestion], str]:
    """Ask the frontier to suggest a value for each pending field.

    The frontier reads the original document — the rendered pages when the
    document has them, the text otherwise (`my_flow.md` §8, I5: the reviewer
    reads the source, not just the JSON). A missing credential is a real state:
    the suggestions are empty and the note says why.

    Args:
        items: The pending fields.
        material: The document's text and rendered pages.
        config: The run's dials.
        document_name: The document's file name, for the prompt.

    Returns:
        The suggestions, and a note when the call refused.

    """
    if not items:
        return [], _EMPTY_NOTE

    engine = FrontierEngine()
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
            config.frontier_model, prompt, material.images, SUGGESTION_SCHEMA
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
    return suggestions, _EMPTY_NOTE
