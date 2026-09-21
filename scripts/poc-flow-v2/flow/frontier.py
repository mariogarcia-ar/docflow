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
from docflow.kernels.types import KernelResult  # noqa: E402

from .config import Config  # noqa: E402
from .hitl import SUGGESTION_SCHEMA, PendingItem, Suggestion  # noqa: E402
from .material import Material  # noqa: E402

__all__: list[str] = [
    "suggest",
]

#: The frontier is reached only when the engine could not settle a field; the
#: prompt asks it to read the document and suggest, not to re-extract.
_EMPTY_NOTE: Final[str] = ""

#: What is said when the pages could not be sent and the OCR text was sent
#: instead. `my_flow.md` B.12: a recorte anunciado is not a silent one — the note
#: is what keeps a degraded reading from passing as the full one.
_DEGRADED_NOTE: Final[str] = (
    "read the OCR text, not the pages: this provider declares no vision, so the "
    "image is refused before the call rather than sent and ignored"
)

#: What is said when the provider cannot read pixels **and** the document has no
#: text to fall back to. There is no honest call left to make, and substituting
#: one would be the plausible-looking wrong answer this project exists to catch.
_NO_MATERIAL_NOTE: Final[str] = (
    "nothing to send: this provider declares no vision and the document has no "
    "text layer to read instead"
)


def _reads_pixels(engine: FrontierEngine, model: str) -> bool:
    """Whether ``model`` declares it can be asked about images.

    Asked **before** the call. K6 refuses an image to a provider without vision —
    measured, DeepSeek accepts the request, ignores the pixels and answers as if
    the document were blank — so asking first is what lets the step fall back to
    real text instead of spending the whole call on a refusal.

    Args:
        engine: The frontier adapter.
        model: The model as the caller named it.

    Returns:
        ``True`` when the provider declares vision. A ``capabilities`` that
        cannot answer also returns ``False``: the text path is the one that
        cannot be wrong about a document it was not asked to look at.

    """
    declared = engine.capabilities(model)
    if declared.value is None:
        return False

    return bool(declared.value.observed.get("supports_vision"))


def _ask(
    engine: FrontierEngine,
    config: Config,
    prompt: str,
    material: Material,
) -> tuple[KernelResult[Mapping[str, object]] | None, str]:
    """Send the frontier the richest material it can actually read.

    `my_flow.md` §8 and I5 say the frontier reads the **source**, and the rendered
    pages are the closest thing to it. But the *provider* decides what it can be
    asked, and the honest answer is not always the richest one:

    - no images: text, and no note — there was nothing else to send.
    - images and vision: the pages, and no note — the full reading.
    - images, no vision, and text: the text, **and a note**. Refusing here would
      throw away material the model could have read; sending the image would be
      refused before the call. Degrading silently would be the one thing worse
      than either, so the degradation is announced (B.12).
    - images, no vision, and no text: nothing, and a note naming why.

    Args:
        engine: The frontier adapter.
        config: The run's dials.
        prompt: The prompt, with the document's text already substituted when
            there is any.
        material: The document's text and rendered pages.

    Returns:
        The attempt — or ``None`` when there was nothing honest to send — and the
        note announcing a degradation or a refusal. The note is empty when the
        richest readable material went out as-is.

    """
    if not material.images:
        attempt = engine.structured(config.frontier_model, prompt, SUGGESTION_SCHEMA)

        return attempt, _EMPTY_NOTE

    if _reads_pixels(engine, config.frontier_model):
        attempt = engine.vision(
            config.frontier_model, prompt, material.images, SUGGESTION_SCHEMA
        )

        return attempt, _EMPTY_NOTE

    if not material.text:
        return None, _NO_MATERIAL_NOTE

    attempt = engine.structured(config.frontier_model, prompt, SUGGESTION_SCHEMA)

    return attempt, _DEGRADED_NOTE


def suggest(
    items: list[PendingItem],
    material: Material,
    config: Config,
    document_name: str,
) -> tuple[list[Suggestion], str]:
    """Ask the frontier to suggest a value for each pending field.

    The frontier reads the original document — the rendered pages when the
    document has them **and the provider can read them**, the text otherwise
    (`my_flow.md` §8, I5: the reviewer reads the source, not just the JSON). A
    missing credential is a real state: the suggestions are empty and the note
    says why.

    Args:
        items: The pending fields.
        material: The document's text and rendered pages.
        config: The run's dials.
        document_name: The document's file name, for the prompt.

    Returns:
        The suggestions, and a note when the call refused or the material was
        degraded from pages to text.

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

    attempt, note = _ask(engine, config, prompt, material)

    if attempt is None:
        return [], note

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

    return suggestions, note
