"""Read the flow's own artifacts from `scripts/poc-flow/artifacts/`.

These files are **content**, not code: prompts are edited by a human when the
reader gets something wrong, and schemas when the downstream contract moves.
They live as files so those edits are one-file diffs (`my_flow.md` §0).

This loader is deliberately separate from `_bootstrap`: it imports nothing but
the standard library, so it can be tested without `docflow` on the path.
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import Mapping
from typing import Any, Final

__all__: list[str] = [
    "ARTIFACT_DIRS",
    "Artifacts",
    "load_artifacts",
]

from ._bootstrap import ARTIFACTS_ROOT

#: The six artifact directories `my_flow.md` §0 names, and the sibling tree the
#: task asked for. `schema-visual` and `schema-visual_reviews` hold one JSON per
#: `(emisor, tipo_comprobante, layout_fingerprint)`; the rest are plain files.
PROMPTS_DIR: Final[pathlib.Path] = ARTIFACTS_ROOT / "prompts"
REVIEW_PROMPTS_DIR: Final[pathlib.Path] = ARTIFACTS_ROOT / "prompts_reviews"
SCHEMA_DIR: Final[pathlib.Path] = ARTIFACTS_ROOT / "schema"
REVIEW_SCHEMA_DIR: Final[pathlib.Path] = ARTIFACTS_ROOT / "schema_review"
VISUAL_DIR: Final[pathlib.Path] = ARTIFACTS_ROOT / "schema-visual"
VISUAL_REVIEW_DIR: Final[pathlib.Path] = ARTIFACTS_ROOT / "schema-visual_reviews"

#: The directories, keyed by their role, so the loader and any reader share one
#: spelling.
ARTIFACT_DIRS: Final[dict[str, pathlib.Path]] = {
    "prompts": PROMPTS_DIR,
    "prompts_reviews": REVIEW_PROMPTS_DIR,
    "schema": SCHEMA_DIR,
    "schema_review": REVIEW_SCHEMA_DIR,
    "schema-visual": VISUAL_DIR,
    "schema-visual_reviews": VISUAL_REVIEW_DIR,
}

#: The schema a review verdict must satisfy (`my_flow.md` §0, `review_schema`).
#: It is a file in `schema_review/`, but the flow also wants the parsed mapping
#: directly. Loaded by **stem**, not by filename: the file is
#: `schema_review/review.json`, so its stem is ``review``.
_REVIEW_SCHEMA_NAME: Final[str] = "review"


# `too-few-public-methods`: `Artifacts` is a load-or-refuse bundle, not a class
# with behaviour; its fields are the contract. See the note on `Material`.
# pylint: disable=too-few-public-methods


class Artifacts:
    """The loaded artifacts one run reads from.

    Loading is load-or-refuse: an absent or invalid file raises, it is never
    defaulted. A prompt that arrived from nowhere would make the flow answer a
    question about the wrong document while claiming to answer about the real
    one.

    Attributes:
        prompts: Role to prompt text (``extract_texto``, ``extract_vision``).
        review_prompts: Role to review prompt text (``review_texto``,
            ``review_vision``).
        extraction_schema: The parsed extraction JSON schema.
        review_schema: The parsed review JSON schema.
        visual_schemas: Key (path stem) to parsed schema-visual JSON.
        visual_review_schemas: Key (path stem) to parsed schema-visual_reviews
            JSON.

    """

    def __init__(  # pylint: disable=too-many-arguments, too-many-positional-arguments
        self,
        prompts: Mapping[str, str],
        review_prompts: Mapping[str, str],
        extraction_schema: Mapping[str, object],
        review_schema: Mapping[str, object],
        visual_schemas: Mapping[str, Mapping[str, object]],
        visual_review_schemas: Mapping[str, Mapping[str, object]],
    ) -> None:
        self.prompts = dict(prompts)
        self.review_prompts = dict(review_prompts)
        self.extraction_schema = dict(extraction_schema)
        self.review_schema = dict(review_schema)
        self.visual_schemas = {k: dict(v) for k, v in visual_schemas.items()}
        self.visual_review_schemas = {
            k: dict(v) for k, v in visual_review_schemas.items()
        }


def _text_files(directory: pathlib.Path, suffix: str) -> dict[str, str]:
    """Read every ``*.suffix`` file in a directory, keyed by its stem.

    Args:
        directory: The directory to read.
        suffix: The extension, without the leading dot.

    Returns:
        Stem to file text.

    Raises:
        FileNotFoundError: If the directory is missing. A missing artifact
            directory is a mistake in the checkout, never a default.

    """
    if not directory.is_dir():
        raise FileNotFoundError(f"artifact directory missing: {directory}")
    loaded: dict[str, str] = {}
    for path in sorted(directory.glob(f"*.{suffix}")):
        loaded[path.stem] = path.read_text(encoding="utf-8")
    return loaded


def _json_files(directory: pathlib.Path) -> dict[str, Mapping[str, object]]:
    """Read every ``*.json`` file in a directory, keyed by its stem.

    Args:
        directory: The directory to read.

    Returns:
        Stem to parsed JSON mapping.

    Raises:
        FileNotFoundError: If the directory is missing.
        ValueError: If a file does not parse as a JSON object. A corrupt schema
            is a mistake, and the flow must not run against it.

    """
    if not directory.is_dir():
        raise FileNotFoundError(f"artifact directory missing: {directory}")
    loaded: dict[str, Mapping[str, object]] = {}
    for path in sorted(directory.glob("*.json")):
        raw = path.read_text(encoding="utf-8")
        parsed: Any = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError(f"{path} is not a JSON object")
        loaded[path.stem] = parsed
    return loaded


def load_artifacts() -> Artifacts:
    """Load every artifact the flow reads, refusing rather than defaulting.

    Returns:
        The loaded artifacts.

    """
    prompts = _text_files(PROMPTS_DIR, "txt")
    review_prompts = _text_files(REVIEW_PROMPTS_DIR, "txt")
    schemas = _json_files(SCHEMA_DIR)
    review_schemas = _json_files(REVIEW_SCHEMA_DIR)

    if _REVIEW_SCHEMA_NAME not in review_schemas:
        raise FileNotFoundError(
            f"{REVIEW_SCHEMA_DIR} carries no {_REVIEW_SCHEMA_NAME!r}"
        )

    return Artifacts(
        prompts=prompts,
        review_prompts=review_prompts,
        extraction_schema=schemas.get("extraction", {}),
        review_schema=review_schemas[_REVIEW_SCHEMA_NAME],
        visual_schemas=_json_files(VISUAL_DIR),
        visual_review_schemas=_json_files(VISUAL_REVIEW_DIR),
    )
