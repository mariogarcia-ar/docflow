"""Read the flow's artifacts from the registry, through K8.

`my_flow.md` B.15 / B.11: prompts and schemas are registry assets, read through
`docflow.kernels.registry` — never by walking a local directory, and never from
a `scripts/poc-flow-v2/artifacts/` copy. One loader, one source; the registry's
own manifest is what declares which assets exist, and a change to an asset
changes the registry hash, which is what keeps the journal honest.

The registry holds the pipeline assets (one extraction prompt, one schema); the
role/lane split (`extract_texto` vs `extract_vision`, `review_texto` vs
`review_vision`) is the Fase A/B deferred work — the registry has one prompt per
role today, so the flow uses it for every lane and marks the missing splits as
`# TODO: [MVP]`.
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

#: The registry keys the extraction and schema live under, per `manifest.json`.
#: One prompt and one schema today; the lane split is deferred (`# TODO: [MVP]`).
_EXTRACTION_PROMPT_KEY: Final[str] = "prompts/extraction/invoice.txt"
_EXTRACTION_SCHEMA_KEY: Final[str] = "schemas/extraction/invoice.json"


# `too-few-public-methods`: `Artifacts` is a load-or-refuse bundle; its fields
# are the contract. The same reasoning v1's `artifacts.py` states.
# pylint: disable=too-few-public-methods


class Artifacts:
    """The loaded artifacts one run reads from.

    Attributes:
        prompt: The extraction prompt text.
        extraction_schema: The parsed extraction JSON schema.
        signature: The registry's own hash, so a changed asset is a different
            run and the journal cannot be reused across it (`my_flow.md` B.5).

    """

    def __init__(
        self,
        prompt: str,
        extraction_schema: Mapping[str, object],
        signature: str,
    ) -> None:
        self.prompt = prompt
        self.extraction_schema = dict(extraction_schema)
        self.signature = signature


def load_artifacts() -> Artifacts:
    """Load the extraction prompt and schema from the registry, refusing rather
    than defaulting.

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
    prompt_asset = assets.get(_EXTRACTION_PROMPT_KEY)
    schema_asset = assets.get(_EXTRACTION_SCHEMA_KEY)
    if prompt_asset is None or schema_asset is None:
        raise RuntimeError(
            "the extraction prompt or schema is missing from the registry"
        )

    prompt = prompt_asset.content.decode("utf-8")
    schema = json.loads(schema_asset.content.decode("utf-8"))
    if not isinstance(schema, dict):
        raise RuntimeError("the extraction schema is not a JSON object")

    return Artifacts(
        prompt=prompt,
        extraction_schema=schema,
        signature=registry_hash(loaded.value),
    )
