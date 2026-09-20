"""Read the flow's artifacts from the registry, through K8.

`my_flow.md` B.15 / B.11: prompts and schemas are registry assets, read through
`docflow.kernels.registry` — never by walking a local directory. One loader, one
source; the registry's manifest declares which assets exist, and a change to an
asset changes the registry hash, which keeps the journal honest.

The role/lane split of `my_flow.md` §4.1 maps onto these registry keys:

    extract_texto  → prompts/extraction/invoice.txt   (the text lane's prompt)
    extract_vision → prompts/extraction/vision.txt    (the vision lane's prompt)
    review_texto   → prompts/review/texto.txt         (the text reviewer)
    review_vision  → prompts/review/vision.txt        (the vision reviewer)

The extraction schema is shared by both extract lanes; the review schema shapes
the reviewer's verdicts, never an extraction.
"""

from __future__ import annotations

# `wrong-import-order` / `wrong-import-position`: `docflow.kernels.registry` is
# only importable once `_bootstrap` puts `src/` on `sys.path`, so the import
# must follow `ensure_docflow_importable()`. The order is load-bearing, not
# cosmetic — the same rule `extract.py` and `material.py` document.
# pylint: disable=wrong-import-order, wrong-import-position
import json
from collections.abc import Mapping
from typing import Final

from ._bootstrap import REGISTRY_ROOT, ensure_docflow_importable

ensure_docflow_importable()

from docflow.kernels.registry import load_registry, registry_hash  # noqa: E402

__all__: list[str] = [
    "Artifacts",
    "load_artifacts",
]

#: The registry keys each lane prompt and each schema live under, per the
#: manifest. The keys are the asset identity; the values are the role names the
#: flow speaks.
_PROMPT_KEYS: Final[dict[str, str]] = {
    "extract_texto": "prompts/extraction/invoice.txt",
    "extract_vision": "prompts/extraction/vision.txt",
    "review_texto": "prompts/review/texto.txt",
    "review_vision": "prompts/review/vision.txt",
}
_EXTRACTION_SCHEMA_KEY: Final[str] = "schemas/extraction/invoice.json"
_REVIEW_SCHEMA_KEY: Final[str] = "schemas/review/review.json"


# `too-few-public-methods`: `Artifacts` is a load-or-refuse bundle; its fields
# are the contract. The same reasoning v1's `artifacts.py` states.
# pylint: disable=too-few-public-methods


class Artifacts:
    """The loaded artifacts one run reads from.

    Attributes:
        prompts: Role to prompt text, keyed by the lane names above.
        extraction_schema: The parsed extraction JSON schema.
        review_schema: The parsed review JSON schema.
        signature: The registry's own hash, so a changed asset is a different
            run and the journal cannot be reused across it (`my_flow.md` B.5).

    """

    def __init__(
        self,
        prompts: Mapping[str, str],
        extraction_schema: Mapping[str, object],
        review_schema: Mapping[str, object],
        signature: str,
    ) -> None:
        self.prompts = dict(prompts)
        self.extraction_schema = dict(extraction_schema)
        self.review_schema = dict(review_schema)
        self.signature = signature


def load_artifacts() -> Artifacts:
    """Load every lane prompt and both schemas, refusing rather than defaulting.

    Returns:
        The loaded artifacts.

    Raises:
        RuntimeError: If the registry cannot be loaded or an asset is missing —
            a missing prompt would make the flow answer about a different
            document while claiming success, which is the silent failure K8
            exists to prevent.

    """
    loaded = load_registry(REGISTRY_ROOT)
    if loaded.value is None:
        code = loaded.reason.code if loaded.reason is not None else "unknown"
        raise RuntimeError(f"registry refused: {code}")

    assets = loaded.value.assets
    prompts: dict[str, str] = {}
    for role, key in _PROMPT_KEYS.items():
        asset = assets.get(key)
        if asset is None:
            raise RuntimeError(f"the {role} prompt is missing from the registry")
        prompts[role] = asset.content.decode("utf-8")

    schema_asset = assets.get(_EXTRACTION_SCHEMA_KEY)
    review_asset = assets.get(_REVIEW_SCHEMA_KEY)
    if schema_asset is None or review_asset is None:
        raise RuntimeError(
            "the extraction or review schema is missing from the registry"
        )

    schema = json.loads(schema_asset.content.decode("utf-8"))
    review = json.loads(review_asset.content.decode("utf-8"))
    if not isinstance(schema, dict) or not isinstance(review, dict):
        raise RuntimeError("an extraction schema is not a JSON object")

    return Artifacts(
        prompts=prompts,
        extraction_schema=schema,
        review_schema=review,
        signature=registry_hash(loaded.value),
    )
