# pylint: disable=duplicate-code
# Reason: this module is a deliberate sibling of ``docflow.pdf.primitives.publication`` and
# ``docflow.image.primitives.publication``. Two processors may not import each other's internals
# (`README.md` §7), so the same short rule is written a third time on purpose and none of the
# three copies is another's default.
"""Atomic publication of the OCR processor's artifacts: write, then rename.

Every artifact this processor publishes goes through here, so a reader never observes a
half-written file: the bytes land in a sibling named ``<destination>.tmp`` and one filesystem
rename makes them visible under their final name. A publication that fails removes its temporary
file, so an interrupted run leaves neither a final-named artifact nor a leftover ``.tmp``.

The check this module makes is that the write *happened* — not that it produced content. An
empty ``text.txt`` is a legitimate artifact here: an image with no text is reported ``EMPTY`` by
:mod:`docflow.ocr.primitives.validation`, and the emptiness is stated by the metrics and the
validation record rather than smuggled through a missing file. What this module refuses is an
artifact that was never produced at all.

# TODO: [RELEASE] filesystem-level crash safety (``fsync`` of the file and its directory before
# the rename) is not claimed here; the guarantee is atomic visibility, not durability across a
# power loss.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path

from docflow.ocr.primitives.errors import typed_failure

#: Suffix of the temporary file a publication writes before it renames into place.
TEMP_SUFFIX = ".tmp"


def ensure_directory(directory: Path) -> Path:
    """Create ``directory`` and every parent it needs, and return it.

    Args:
        directory: The directory that has to exist before an artifact can land in it.

    Returns:
        ``directory``.

    Raises:
        OCRPrimitiveError: With ``IO_ERROR`` when the directory cannot be created — the run then
            has nowhere to publish, which is a failure rather than a detail.
    """
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise typed_failure(
            "IO_ERROR",
            f"{directory} could not be created",
            recoverable=False,
            metadata={"directory": str(directory), "os_error": str(exc)},
        ) from exc
    return directory


def _publish(destination: Path, content: str) -> Path:
    """Write ``content`` through a ``.tmp`` sibling and rename it into place.

    Args:
        destination: Final artifact path.
        content: The artifact's content, verbatim.

    Returns:
        ``destination``, once it is complete.

    Raises:
        OCRPrimitiveError: With ``IO_ERROR`` when the temporary file was not produced, or when the
            filesystem refused the write or the rename. A read-only directory and a full disk are
            failures of the run, not crashes of it.
    """
    ensure_directory(destination.parent)
    temporary = destination.with_name(destination.name + TEMP_SUFFIX)
    try:
        try:
            temporary.write_text(content, encoding="utf-8")
            if not temporary.is_file():
                raise typed_failure(
                    "IO_ERROR",
                    f"{destination} was not written; nothing is published",
                    metadata={"destination": str(destination)},
                )
            os.replace(temporary, destination)
        except OSError as refused:
            raise typed_failure(
                "IO_ERROR",
                f"{destination} could not be published",
                metadata={
                    "destination": str(destination),
                    "os_error": str(refused),
                },
            ) from refused
    except BaseException:
        # A failed or interrupted publication must leave no trace of its attempt: the temporary
        # file is removed whatever went wrong, including a KeyboardInterrupt.
        temporary.unlink(missing_ok=True)
        raise
    return destination


def write_text_atomic(destination: Path, text: str) -> Path:
    """Publish ``text`` as a UTF-8 text artifact, atomically.

    Args:
        destination: Final artifact path.
        text: The artifact's content, exactly as it should read back.

    Returns:
        ``destination``, once it is complete.
    """
    return _publish(destination, text)


def write_json_atomic(destination: Path, payload: Mapping[str, object]) -> Path:
    """Publish ``payload`` as a deterministic JSON artifact, atomically.

    Keys are sorted, so the bytes of an artifact depend on its content and not on the order the
    caller happened to build it in. That is what makes the functional content of
    ``document.json`` byte-identical across two runs over the same input.

    Args:
        destination: Final artifact path.
        payload: The artifact content; a mapping, never a bare value.

    Returns:
        ``destination``, once it is complete.

    Raises:
        OCRPrimitiveError: With ``EXPORT_ERROR`` when the payload cannot be represented as JSON.
            A value that does not serialize is a representation this processor could not produce,
            not a crash of it.
    """
    try:
        document = json.dumps(dict(payload), indent=2, sort_keys=True) + "\n"
    except (TypeError, ValueError) as unrepresentable:
        raise typed_failure(
            "EXPORT_ERROR",
            f"{destination} could not be serialized",
            metadata={
                "destination": str(destination),
                "json_error": str(unrepresentable),
            },
        ) from unrepresentable
    return _publish(destination, document)
