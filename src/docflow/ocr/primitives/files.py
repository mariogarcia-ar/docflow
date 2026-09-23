"""Atomic publication in the ``ocr/`` namespace (``OCR-10``) - §3.4's *Files* group.

Two guarantees, answering two failure modes:

* **An artifact is complete or it is absent.** Every file is written under ``ocr/.tmp/`` and renamed
  into place, so a reader that finds the final name finds a complete file, and a run that dies
  halfway leaves nothing a later stage could mistake for a result. The rename is ``Path.replace``
  rather than ``os.rename`` because it is atomic on one filesystem *and* replaces an existing
  destination, which matters because a rerun over the same page lands in the same directory.
* **A failed run leaves nothing behind.** :func:`discard_staged` removes everything staged, and
  :func:`abandon` removes the published artifacts as well. Both are called by the code that knows
  the run failed rather than from a ``finally``: this module cannot tell a half-written artifact
  from the only one that was requested.

The staging form is ``ocr/.tmp/<final name>`` — the name unchanged, only the parent different. That
is what the plan names, and for this processor it is also the only form that cannot be corrupted by
inference: every artifact name here carries its own extension (``text.txt``, ``document.json``), and
a writer that chose an encoder from the name would break on a ``.tmp`` suffix. The directory is what
marks a file as not-an-artifact, and it lives inside the namespace it stages into, so the rename
never crosses a filesystem.

There is no ``publish_artifact`` here and no per-artifact publisher for text, Markdown and JSON.
Unlike the image processor — whose artifacts are *images* whose encoder must be chosen — every
artifact this processor publishes is bytes with a name, so one writer covers all of them and
:func:`publish_namespace` walks the five artifacts in one place. A family of near-identical
publishers would be five copies of one idea.
"""

from __future__ import annotations

# pylint: disable=duplicate-code
# This module is parallel to `docflow.image.primitives.atomic`, and that is the only shape
# available: `docs/plan/README.md` §3 states that a processor never imports another, so the shared
# staging/publication body cannot be factored out without breaking the one architectural rule that
# keeps four processors independently buildable. The bodies are near-identical *on purpose* - a
# reader who has understood one processor's atomicity should recognise the next one's immediately -
# and the alternative, a shared helper module, would put a fifth name in the dependency graph whose
# owner no task names.
import json
from pathlib import Path
from typing import Any, Final

from docflow.ocr.contracts import ArtifactPaths

TEMP_SUFFIX: Final[str] = ".tmp"
"""Suffix of a staged sibling, which this processor no longer writes.

Kept so the cleanup recognises it: a file left by an interrupted run of an older build, or by a
caller staging its own write, carries this suffix and would otherwise survive every sweep.
"""

TEMP_DIRECTORY_NAME: Final[str] = ".tmp"
"""Name of the staging directory inside the ``ocr/`` namespace."""

TEXT_FILE_NAME: Final[str] = "text.txt"
"""The plain-text artifact."""

MARKDOWN_FILE_NAME: Final[str] = "document.md"
"""The Markdown artifact."""

STRUCTURED_FILE_NAME: Final[str] = "document.json"
"""The versioned structured artifact."""

METADATA_FILE_NAME: Final[str] = "metadata.json"
"""The provenance artifact, and the only home of timing."""

TABLES_DIRECTORY_NAME: Final[str] = "tables"
"""The directory the per-table Markdown files live in."""

PUBLISHED_FILE_NAMES: Final[tuple[str, ...]] = (
    TEXT_FILE_NAME,
    MARKDOWN_FILE_NAME,
    STRUCTURED_FILE_NAME,
    METADATA_FILE_NAME,
)
"""Every file this processor publishes, by name.

Restated rather than derived from the constants above so that :func:`abandon`, which *deletes*,
cannot have its reach widened by an edit somewhere else. A test asserts this tuple matches the four
constants, so the two cannot drift silently.
"""


def ensure_directory(directory: Path) -> Path:
    """Create a directory if it is absent.

    Args:
        directory: The directory to ensure.

    Returns:
        The directory.
    """
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def create_ocr_directory(output_dir: Path) -> Path:
    """Create the namespace if it is absent.

    The staging directory is created with it rather than lazily on the first write: a caller that
    inspects the namespace before anything is published then sees a directory that exists and is
    empty, which is the same thing a successful run leaves, rather than a missing path.

    Args:
        output_dir: The ``ocr/`` directory.

    Returns:
        The directory.
    """
    ensure_directory(output_dir)
    ensure_directory(staging_directory(output_dir))
    return output_dir


def build_ocr_output_paths(output_dir: Path) -> ArtifactPaths:
    """Return the canonical artifact paths for a namespace.

    One place knows the layout, so a caller never assembles a path from parts and a change to the
    namespace is one edit. The directory is **not** created here: naming the paths a run will write
    and deciding to write them are different decisions, and a function that created directories
    would make merely asking a question have a side effect.

    Args:
        output_dir: The ``ocr/`` directory.

    Returns:
        Every path this processor publishes, under that directory.
    """
    return ArtifactPaths(
        text=output_dir / TEXT_FILE_NAME,
        markdown=output_dir / MARKDOWN_FILE_NAME,
        structured_document=output_dir / STRUCTURED_FILE_NAME,
        tables_dir=output_dir / TABLES_DIRECTORY_NAME,
        metadata=output_dir / METADATA_FILE_NAME,
    )


def staging_directory(output_dir: Path) -> Path:
    """Return the staging directory inside a namespace, creating it.

    Args:
        output_dir: The ``ocr/`` directory the caller owns.

    Returns:
        ``output_dir/.tmp``.
    """
    return ensure_directory(output_dir / TEMP_DIRECTORY_NAME)


def temp_path(final_path: Path) -> Path:
    """Return the staging path a final path is written through.

    Args:
        final_path: The published path.

    Returns:
        The staging path, e.g. ``/x/ocr/.tmp/text.txt``. Only the parent differs, so the artifact's
        own name — and any reader that keys off its extension — is preserved.
    """
    return final_path.parent / TEMP_DIRECTORY_NAME / final_path.name


def write_text_atomic(path: Path, content: str) -> Path:
    """Write text atomically.

    Args:
        path: Where to publish. Its parent is created if absent.
        content: The text to write.

    Returns:
        ``path``, once the file is complete.
    """
    staged = temp_path(path)
    ensure_directory(staged.parent)
    staged.write_text(content, encoding="utf-8")
    staged.replace(path)
    prune_staging_directory(staged.parent)
    return path


def write_json_atomic(path: Path, payload: dict[str, Any]) -> Path:
    """Write JSON atomically.

    Keys are sorted and the indent is fixed, for the reason
    :func:`docflow.ocr.primitives.export.serialize_document_json` records: two runs over one page
    must produce byte-identical files, so a diff between two artifacts shows a real difference or
    nothing at all. A caller with a payload that needs a different rendering should use
    :func:`write_text_atomic` with the text it wants.

    Args:
        path: Where to publish.
        payload: The object to serialise.

    Returns:
        ``path``, once the file is complete.
    """
    return write_text_atomic(
        path,
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str)
        + "\n",
    )


def read_json(path: Path) -> dict[str, Any]:
    """Read a JSON artifact back.

    Args:
        path: The file to read.

    Returns:
        The parsed object.

    Raises:
        OSError: The file cannot be read.
        json.JSONDecodeError: The file is not JSON.
    """
    return json.loads(path.read_text(encoding="utf-8"))


def prune_staging_directory(staged_directory: Path) -> bool:
    """Remove a staging directory that has nothing left in it.

    Called after every rename, so a successful run leaves no empty ``.tmp`` behind. An empty staging
    directory is otherwise indistinguishable from the residue of a failed run, and the acceptance
    criterion is phrased as inspecting the namespace and finding nothing staged.

    Args:
        staged_directory: The directory to remove, if it is empty.

    Returns:
        Whether it was removed. ``False`` when it is absent or still holds another staged artifact,
        which is the ordinary case for a run publishing several files: the last rename prunes it.

    # TODO: [RELEASE] the writes here are atomic against a *process* failure, not a *system* one.
    # ``Path.replace`` is atomic on a POSIX filesystem, so a reader never sees a half-written
    # artifact; but nothing calls ``fsync`` on the file or its directory, so a power loss can still
    # lose a rename the caller was told succeeded. Closing that needs a durability barrier per
    # artifact, which costs a sync on every publish and belongs with the operational hardening
    # rather than in the PoC.
    """
    if not staged_directory.is_dir():
        return False
    if any(staged_directory.iterdir()):
        return False
    staged_directory.rmdir()
    return True


def discard_staged(output_dir: Path) -> list[Path]:
    """Remove everything staged under a namespace, and report what was removed.

    Removes the staging directory and its contents, and also any ``*.tmp`` sibling a caller or an
    older writer left beside an artifact, because a cleanup that knew about only one of the two
    forms would leave the other behind for a reader to find.

    Args:
        output_dir: The ``ocr/`` directory.

    Returns:
        The paths that were removed, for a caller that wants to report what it cleaned up.
    """
    if not output_dir.exists():
        return []

    removed: list[Path] = []
    staged_directory_path = output_dir / TEMP_DIRECTORY_NAME
    if staged_directory_path.is_dir():
        for entry in sorted(staged_directory_path.rglob("*")):
            if entry.is_file():
                entry.unlink()
                removed.append(entry)
        for entry in sorted(staged_directory_path.rglob("*"), reverse=True):
            if entry.is_dir():
                entry.rmdir()
        staged_directory_path.rmdir()
        removed.append(staged_directory_path)

    for entry in sorted(output_dir.glob(f"*{TEMP_SUFFIX}")):
        if entry.is_file():
            entry.unlink()
            removed.append(entry)

    return removed


def abandon(output_dir: Path) -> list[Path]:
    """Remove everything a failed run published, and report what was removed.

    A failed run must leave no partially valid artifact visible, and an artifact under its final
    name
    is visible whether or not the run that wrote it went on to succeed. Only names this processor
    would have written are considered, so a caller pointing at a directory that holds anything else
    does not lose it.

    Args:
        output_dir: The ``ocr/`` directory.

    Returns:
        The paths that were removed.
    """
    removed = discard_staged(output_dir)
    if not output_dir.exists():
        return removed

    for name in PUBLISHED_FILE_NAMES:
        path = output_dir / name
        if path.is_file():
            path.unlink()
            removed.append(path)

    tables_dir = output_dir / TABLES_DIRECTORY_NAME
    if tables_dir.is_dir():
        for entry in sorted(tables_dir.rglob("*"), reverse=True):
            if entry.is_file():
                entry.unlink()
                removed.append(entry)
            elif entry.is_dir():
                entry.rmdir()
        tables_dir.rmdir()
        removed.append(tables_dir)

    return removed


__all__ = [
    "MARKDOWN_FILE_NAME",
    "METADATA_FILE_NAME",
    "PUBLISHED_FILE_NAMES",
    "STRUCTURED_FILE_NAME",
    "TABLES_DIRECTORY_NAME",
    "TEMP_DIRECTORY_NAME",
    "TEMP_SUFFIX",
    "TEXT_FILE_NAME",
    "abandon",
    "build_ocr_output_paths",
    "create_ocr_directory",
    "discard_staged",
    "ensure_directory",
    "prune_staging_directory",
    "read_json",
    "staging_directory",
    "temp_path",
    "write_json_atomic",
    "write_text_atomic",
]
