"""Atomic publication — an artifact is complete or it is absent.

Owned by ``PDF-09`` for the sequence itself; ``PDF-12`` is what hardens it across every
namespace. The rule is ``subplan-procesador-pdf.md`` §3: write to ``.tmp``, validate, then
rename into place. A reader that finds the final name finds a complete file, and a run that
dies halfway leaves nothing a later stage could mistake for an artifact.

The rename is ``Path.replace`` rather than ``os.rename`` because it is atomic on the same
filesystem and also works when the destination already exists — two runs over the same bytes
land in the same directory, which is the point of a reproducible run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

TEMP_SUFFIX = ".tmp"
"""Suffix of a file that is not yet an artifact. Never a valid published name."""


def temp_path(final_path: Path) -> Path:
    """Return the temporary path a final path is staged through.

    Args:
        final_path: The published path.

    Returns:
        The staging path, e.g. ``page.png.tmp``.
    """
    return final_path.with_name(f"{final_path.name}{TEMP_SUFFIX}")


def publish_text(final_path: Path, content: str) -> Path:
    """Write text atomically.

    Args:
        final_path: Where the artifact is published. Its parent is created if absent.
        content: The text to write.

    Returns:
        ``final_path``, once the file is complete.
    """
    final_path.parent.mkdir(parents=True, exist_ok=True)
    staged = temp_path(final_path)
    staged.write_text(content, encoding="utf-8")
    staged.replace(final_path)
    return final_path


def publish_json(final_path: Path, payload: dict[str, Any]) -> Path:
    """Write a JSON artifact atomically.

    Args:
        final_path: Where the artifact is published. Its parent is created if absent.
        payload: The object to serialise.

    Returns:
        ``final_path``, once the file is complete. Keys are sorted and the indent fixed, so
        two runs over the same content produce byte-identical files — the determinism class
        this processor declares depends on it.
    """
    return publish_text(
        final_path,
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
    )


def discard(path: Path) -> None:
    """Remove a path, ignoring its absence.

    Used to clear a staged file whose validation failed, so a failed write leaves no residue
    for a later run to find.

    Args:
        path: The path to remove.
    """
    path.unlink(missing_ok=True)


def discard_staged(final_path: Path) -> None:
    """Remove the staged form of a final path, ignoring its absence.

    Args:
        final_path: The path whose staging file should be removed.
    """
    discard(temp_path(final_path))


__all__ = [
    "TEMP_SUFFIX",
    "discard",
    "discard_staged",
    "publish_json",
    "publish_text",
    "temp_path",
]
