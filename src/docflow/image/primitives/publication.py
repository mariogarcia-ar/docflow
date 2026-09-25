# pylint: disable=duplicate-code
# Reason: this module is a deliberate sibling of ``docflow.pdf.primitives.publication``. Two
# processors may not import each other's internals (`README.md` §7), so the same four-line rule
# is written twice on purpose and neither copy is the other's default.
"""Atomic publication: write to ``.tmp``, validate, rename.

Every artifact this processor publishes goes through here, so a reader never observes a
half-written file: the bytes land in a sibling named ``<destination>.tmp``, the whole write
is validated, and only then does one filesystem rename make it visible under its final name.
A publication that fails removes its temporary file, so an interrupted run leaves neither a
final-named artifact nor a leftover ``.tmp``.

The image writer is the engine's, so the callback shape is what keeps this module
engine-free: the seam hands in the function that encodes the pixels, and this module owns the
``.tmp`` naming, the validation and the rename. The engine never names an artifact.

# TODO: [RELEASE] filesystem-level crash safety (``fsync`` of the file and its directory
# before the rename) is not claimed here; the guarantee is atomic visibility, not durability
# across a power loss.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from pathlib import Path

from docflow.image.primitives.errors import typed_failure

#: Suffix of the temporary file a publication writes before it renames into place.
TEMP_SUFFIX = ".tmp"


def publish_artifact(destination: Path, write: Callable[[Path], None]) -> Path:
    """Write through a ``.tmp`` sibling, validate it, then rename it over ``destination``.

    Args:
        destination: Final artifact path.
        write: Callback that produces the artifact at the temporary path it is given.

    Returns:
        ``destination``, once it is complete.

    Raises:
        ImagePrimitiveError: With ``IO_ERROR`` when the temporary file was not produced, or
            was produced empty. An empty image artifact is a failure, not a small one:
            publishing it would report a broken run as a successful one.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + TEMP_SUFFIX)
    try:
        write(temporary)
        produced = temporary.is_file() and temporary.stat().st_size > 0
        if not produced:
            raise typed_failure(
                "IO_ERROR",
                f"{destination} was not written; nothing is published",
                metadata={"destination": str(destination)},
            )
        os.replace(temporary, destination)
    except BaseException:
        # A failed or interrupted publication must leave no trace of its attempt: the
        # temporary file is removed whatever went wrong, including a KeyboardInterrupt.
        temporary.unlink(missing_ok=True)
        raise
    return destination


def publish_json(destination: Path, payload: Mapping[str, object]) -> Path:
    """Publish ``payload`` as a deterministic JSON artifact, atomically.

    Keys are sorted, so the bytes of an artifact depend on its content and not on the order
    the caller happened to build it in.

    Args:
        destination: Final artifact path.
        payload: The artifact content; a mapping, never a bare value.

    Returns:
        ``destination``, once it is complete.
    """
    document = json.dumps(dict(payload), indent=2, sort_keys=True) + "\n"
    return publish_artifact(
        destination,
        lambda path: path.write_text(document, encoding="utf-8"),
    )
