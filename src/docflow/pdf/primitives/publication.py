"""Atomic publication: write to ``.tmp``, validate, rename.

Every artifact this processor publishes goes through here, so a reader never observes a
half-written file: the bytes land in a sibling named ``<destination>.tmp``, the whole
write is validated, and only then does one filesystem rename make it visible under its
final name. A publication that fails removes its temporary file, so an interrupted run
leaves neither a final-named artifact nor a leftover ``.tmp``.

The engine writes into a scratch directory that this module then publishes, which is the
same rule seen from the other side: the engine's own numbering and directory layout never
become our artifact names.

# TODO: [RELEASE] filesystem-level crash safety (``fsync`` of the file and its directory
# before the rename) is not claimed here; the guarantee is atomic visibility, not durability
# across a power loss.
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable, Mapping
from pathlib import Path

from docflow.pdf.primitives.errors import typed_failure

#: Suffix of the temporary file a publication writes before it renames into place.
TEMP_SUFFIX = ".tmp"


def _publish(destination: Path, write: Callable[[Path], None]) -> Path:
    """Write through a ``.tmp`` sibling, validate it, then rename it over ``destination``.

    Args:
        destination: Final artifact path.
        write: Callback that produces the artifact at the temporary path it is given.

    Returns:
        ``destination``, once it is complete.

    Raises:
        PDFPrimitiveError: With ``IO_ERROR`` when the temporary file was not produced —
            the write is validated before it is renamed, so an artifact that never
            materialised cannot be published.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + TEMP_SUFFIX)
    try:
        write(temporary)
        if not temporary.is_file():
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


def publish_text(destination: Path, text: str, *, encoding: str = "utf-8") -> Path:
    """Publish ``text`` at ``destination``, atomically.

    An empty text is a legitimate artifact — a page with no native text layer publishes an
    empty file rather than a missing one — so emptiness is not rejected here.

    Args:
        destination: Final artifact path.
        text: The complete artifact content.
        encoding: Text encoding; explicit UTF-8 by default, as the engine is asked for.

    Returns:
        ``destination``, once it is complete.
    """
    return _publish(destination, lambda path: path.write_text(text, encoding=encoding))


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
    document = json.dumps(dict(payload), indent=2, sort_keys=True)
    return publish_text(destination, document + "\n")


def publish_file(source: Path, destination: Path, *, allow_empty: bool = False) -> Path:
    """Publish a file an engine wrote, validating it before it becomes visible.

    Args:
        source: The engine's own output, in its scratch directory.
        destination: Final artifact path.
        allow_empty: Whether a zero-byte source is acceptable. It is not for engine
            artifacts: an empty render or an empty extracted image is a failure, and
            publishing it would report a broken run as a successful one.

    Returns:
        ``destination``, once it is complete.

    Raises:
        PDFPrimitiveError: With ``IO_ERROR`` when the engine produced no file, or an empty
            one where content was required.
    """
    if not source.is_file():
        raise typed_failure(
            "IO_ERROR",
            f"the engine produced no file at {source}",
            metadata={"source": str(source), "destination": str(destination)},
        )
    if not allow_empty and source.stat().st_size == 0:
        raise typed_failure(
            "IO_ERROR",
            f"the engine produced an empty file at {source}",
            metadata={"source": str(source), "destination": str(destination)},
        )
    return _publish(destination, lambda path: shutil.copyfile(source, path))
