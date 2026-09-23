"""Atomic publication and the ``metadata.json`` that describes a run.

Owned by ``IMG-11``. Two guarantees live here, and they answer two different failure modes:

* **An artifact is complete or it is absent.** Every file is written under a staging directory
  inside the namespace and renamed into place, so a reader that finds the final name finds a
  complete file and a run that dies halfway leaves nothing a later stage could mistake for a result.
  The rename is ``Path.replace`` rather than ``os.rename`` because it is atomic on the same
  filesystem *and* works when the destination exists, which matters because a rerun over the same
  bytes lands in the same directory.
* **A failed run leaves nothing behind.** :func:`discard_staged` removes every staged file under the
  namespace, and :func:`abandon` removes the published artifacts as well. Both are called before the
  failure is returned rather than in a ``finally``, because the decision to clean up belongs to the
  caller that knows the run failed - this module cannot tell a half-written artifact from one that
  is simply the only one requested.

The staging form is ``image/.tmp/<final name>`` rather than a ``<final name>.tmp`` sibling, which is
the form the plan names and, for images, the only one that works: :func:`docflow.image.primitives
.load.save_image` infers the encoder from the destination's extension, so a staged ``.tmp`` suffix
would be rejected as an unsupported format before a single byte was written.

The metadata payload is assembled here and written atomically like any other artifact. Its key set
is not invented: :data:`docflow.identities.ARTIFACT_METADATA_KEYS` fixes the seven keys every
processor's ``metadata.json`` must carry, and a test asserts they are all present. The remaining
keys are this processor's own, and the nested records are expanded field by field rather than dumped
with
``dataclasses.asdict`` - a record gaining a field should be a visible decision here, not a silent
addition to a file whose schema other tools read.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

from docflow.identities import ARTIFACT_METADATA_KEYS
from docflow.image.contracts import (
    ArtifactRef,
    ImageError,
    ImageMetadata,
    ImageMetrics,
    ImageOptions,
    ImageSourceRef,
    ImageValidation,
)

TEMP_SUFFIX = ".tmp"
"""Suffix of a staged sibling, which this processor no longer writes.

Kept so the cleanup recognises it: a file left by an interrupted run of an earlier build, or by a
caller staging its own write, carries this suffix and would otherwise survive every sweep.
"""

TEMP_DIRECTORY_NAME = ".tmp"
"""Name of the staging directory this processor stages every artifact through.

Holds the artifacts' *final* file names, unchanged: the encoder is chosen from the extension, so a
staged ``normalized.png.tmp`` would be refused as an unsupported format. The directory is what makes
a staged file unambiguously not an artifact, and it lives inside the namespace it stages into, so a
rename out of it never crosses a filesystem.
"""

METADATA_FILE_NAME = "metadata.json"
"""Name of the provenance artifact inside the ``image/`` namespace."""

METADATA_ARTIFACT_KIND = "metadata"
"""Artifact kind recorded for it.

Not one of the contract's ``ImageArtifactKind`` values, which describe image representations. A
``metadata.json`` is not an image and the contract has no kind for it, so the reference built for it
carries this name and is deliberately kept out of ``ImageResult.artifacts`` - that list is the
images a consumer can read, not the file that describes them.
"""


def staging_directory(output_dir: Path) -> Path:
    """Return the staging directory inside a namespace, creating it.

    Args:
        output_dir: The ``image/`` directory the caller owns.

    Returns:
        ``output_dir/.tmp``.
    """
    staged = output_dir / TEMP_DIRECTORY_NAME
    staged.mkdir(parents=True, exist_ok=True)
    return staged


def temp_path(final_path: Path) -> Path:
    """Return the staging path a final path is written through.

    Args:
        final_path: The published path.

    Returns:
        The staging path, e.g. ``/x/image/.tmp/normalized.png``. The name is unchanged and only the
        parent differs, so a writer that infers its encoder from the extension still works.
    """
    return final_path.parent / TEMP_DIRECTORY_NAME / final_path.name


def prune_staging_directory(staged_directory: Path) -> bool:
    """Remove a staging directory that has nothing left in it.

    Called after every rename, so a successful run leaves no empty ``.tmp`` behind. An empty staging
    directory is otherwise indistinguishable from the residue of a failed run, and "inspecting the
    namespace finds nothing staged" is the acceptance criterion a failure is judged by.

    Args:
        staged_directory: The directory to remove, if it is empty.

    Returns:
        Whether it was removed. ``False`` when it is absent or still holds another staged artifact,
        which is the ordinary case for a run publishing several files: the last rename prunes it.
    """
    if not staged_directory.is_dir():
        return False
    if any(staged_directory.iterdir()):
        return False
    staged_directory.rmdir()
    return True


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
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_text(content, encoding="utf-8")
    staged.replace(final_path)
    prune_staging_directory(staged.parent)
    return final_path


def publish_json(final_path: Path, payload: dict[str, Any]) -> Path:
    """Write a JSON artifact atomically.

    Args:
        final_path: Where the artifact is published.
        payload: The object to serialise.

    Returns:
        ``final_path``, once the file is complete.
    """
    return publish_text(final_path, json.dumps(payload, indent=2, default=str) + "\n")


def publish_metadata(
    payload: dict[str, Any], output_dir: Path, engine: object = None
) -> ArtifactRef:
    """Write the run's ``metadata.json`` atomically and describe it.

    Takes the engine for signature symmetry with the image publishers and ignores it: metadata is
    text, so no codec is involved. Passing ``None`` is the ordinary case.

    Args:
        payload: The metadata object.
        output_dir: The ``image/`` directory. Never chosen here, so ownership of the namespace stays
            with the caller.
        engine: Unused; present so a caller can treat every publisher alike.

    Returns:
        A reference to the written file.
    """
    _ = engine
    path = publish_json(output_dir / METADATA_FILE_NAME, payload)
    return ArtifactRef(
        path=path,
        kind=METADATA_ARTIFACT_KIND,
        width=0,
        height=0,
        format="JSON",
        size=path.stat().st_size,
    )


def discard_staged(output_dir: Path) -> list[Path]:
    """Remove every staged file under a namespace, and report what was removed.

    Called when a run fails. It removes the staging directory and everything under it, and also any
    ``*.tmp`` sibling a caller or an older writer may have left beside an artifact, because a
    cleanup that knew about only one of the two forms would leave the other behind for a reader to
    find.

    Args:
        output_dir: The ``image/`` directory.

    Returns:
        The paths that were removed, for a caller that wants to report what it cleaned up.
    """
    if not output_dir.exists():
        return []

    removed: list[Path] = []
    staged_directory = output_dir / TEMP_DIRECTORY_NAME
    if staged_directory.is_dir():
        for entry in sorted(staged_directory.rglob("*")):
            if entry.is_file():
                entry.unlink()
                removed.append(entry)
        for entry in sorted(staged_directory.rglob("*"), reverse=True):
            if entry.is_dir():
                entry.rmdir()
        staged_directory.rmdir()
        removed.append(staged_directory)

    for entry in sorted(output_dir.glob(f"*{TEMP_SUFFIX}")):
        if entry.is_file():
            entry.unlink()
            removed.append(entry)

    return removed


def abandon(output_dir: Path) -> list[Path]:
    """Remove everything a failed run published, and report what was removed.

    Removes the staged files and the final-named artifacts together. A failed run must leave no
    partially valid artifact visible, and an artifact under its final name is visible whether or not
    the run that wrote it went on to succeed.

    Only files this processor would have written are considered - the fixed artifact names and the
    staging forms - so a caller pointing at a directory that holds anything else does not lose it.

    Args:
        output_dir: The ``image/`` directory.

    Returns:
        The paths that were removed.
    """
    removed = discard_staged(output_dir)
    if not output_dir.exists():
        return removed

    for name in (*PUBLISHED_FILE_NAMES, METADATA_FILE_NAME):
        path = output_dir / name
        if path.is_file():
            path.unlink()
            removed.append(path)

    return removed


PUBLISHED_FILE_NAMES: Final[tuple[str, ...]] = (
    "normalized.png",
    "ocr_ready.png",
    "vlm_ready.png",
)
"""Every image artifact this processor publishes, by name.

Restated from the modules that own the names rather than imported, because this list is used to
*delete* files: importing it would make a change in one pipeline silently widen a cleanup's reach.
A test asserts this tuple matches the three constants those modules declare.
"""


def build_metadata_payload(
    metadata: ImageMetadata,
    source: ImageSourceRef,
    classification: str,
    transformations: list[str],
    validation: ImageValidation,
    artifacts: list[ArtifactRef],
    processing_key: str | None = None,
) -> dict[str, Any]:
    """Assemble the ``metadata.json`` payload.

    The seven keys :data:`docflow.identities.ARTIFACT_METADATA_KEYS` requires come first, so a
    reader
    scanning the file sees the provenance before the details.

    Args:
        metadata: The provenance record from the result.
        source: The reference to the original input.
        classification: The descriptive classification, as data.
        transformations: Every transformation applied, in order.
        validation: The structural validation of the run.
        artifacts: Every image artifact published.
        processing_key: The reuse key, or ``None`` when it has not been computed.

    Returns:
        The payload, ready to serialise.
    """
    payload = {
        # The seven keys `docflow.identities` fixes for every processor.
        "processor": metadata.processor,
        "processor_version": metadata.processor_version,
        "engine": metadata.engine,
        "engine_version": metadata.engine_version,
        "document_id": metadata.context.document_id,
        "workflow_run_id": metadata.context.workflow_run_id,
        "processing_key": processing_key,
        # This processor's own.
        "page_number": metadata.context.page_number,
        "classification": classification,
        "status": validation.status,
        "transformations": list(transformations),
        "libraries": dict(metadata.libraries),
        "timing": dict(metadata.timing),
        "options": _options_payload(metadata.options),
        "input": {
            "path": str(source.path),
            "width": source.width,
            "height": source.height,
            "format": source.format,
            "size": source.size,
            # Whether the dimensions beside it are measurements. A failed run reports zeroes it
            # never measured (see `composition.UNKNOWN_DIMENSIONS`), and a consumer that took
            # them for a real size would compute with an image that does not exist. The
            # inference is sound here and only here: the primitives refuse a non-positive shape,
            # so an image this processor decoded always has positive dimensions - zero therefore
            # means "never measured" and cannot mean "empty".
            "dimensions_measured": source.width > 0 and source.height > 0,
        },
        "input_metrics": _metrics_payload(metadata.input_metrics),
        "output_metrics": _metrics_payload(metadata.output_metrics),
        "artifacts": [_artifact_payload(artifact) for artifact in artifacts],
        "errors": [_error_payload(error) for error in validation.errors],
        "missing_artifacts": [str(path) for path in validation.missing_artifacts],
    }
    # Guarded rather than trusted: the key set is not optional, and a payload missing a provenance
    # key is a ``metadata.json`` other tools cannot rely on.
    require_metadata_keys(payload)
    return payload


def require_metadata_keys(payload: dict[str, Any]) -> None:
    """Refuse a metadata payload that is missing a provenance key.

    A function rather than three inline lines, because the invariant it guards is one a test must be
    able to provoke. Nothing that calls :func:`build_metadata_payload` can trigger it - the literal
    it returns carries all seven keys - so an inline check would be a branch no writer reaches and
    no test could falsify. Extracting it makes the guard itself testable, and keeps the guarantee
    true for any caller that assembles or amends a payload.

    Args:
        payload: The payload to check.

    Returns:
        ``None`` when every required key is present.

    Raises:
        ValueError: One or more keys from :data:`docflow.identities.ARTIFACT_METADATA_KEYS` are
            absent, naming them.
    """
    absent = [key for key in ARTIFACT_METADATA_KEYS if key not in payload]
    if absent:
        raise ValueError(f"the metadata payload is missing required keys: {absent}")


def _options_payload(options: ImageOptions) -> dict[str, bool]:
    """Expand the options into a JSON object.

    Args:
        options: The requested options.

    Returns:
        Each flag by name.
    """
    return {
        "normalize": options.normalize,
        "prepare_for_ocr": options.prepare_for_ocr,
        "prepare_for_vlm": options.prepare_for_vlm,
        "correct_orientation": options.correct_orientation,
        "deskew": options.deskew,
    }


def _metrics_payload(metrics: ImageMetrics) -> dict[str, Any]:
    """Expand a metrics record into a JSON object.

    Field by field rather than through ``dataclasses.asdict``: a record gaining a field should be a
    visible edit here, because this payload is a schema other tools read. ``resolution`` and
    ``skew`` may legitimately be ``None``, which is the contract's "not determined" and not a
    placeholder.

    Args:
        metrics: The record to expand.

    Returns:
        The metrics by name.
    """
    return {
        "dimensions": {
            "width": metrics.dimensions.width,
            "height": metrics.dimensions.height,
        },
        "resolution": metrics.resolution,
        "format": metrics.format,
        "size": metrics.size,
        "quality": {
            "blur": metrics.quality.blur,
            "sharpness": metrics.quality.sharpness,
            "contrast": metrics.quality.contrast,
            "brightness": metrics.quality.brightness,
            "noise": metrics.quality.noise,
        },
        "orientation": metrics.orientation,
        "skew": metrics.skew,
        "text_coverage": metrics.text_coverage,
        "text_regions": [
            {
                "region_id": region.region_id,
                "bbox": list(region.bbox),
                "text_coverage": region.text_coverage,
            }
            for region in metrics.text_regions
        ],
    }


def _artifact_payload(artifact: ArtifactRef) -> dict[str, Any]:
    """Expand an artifact reference into a JSON object.

    The path is recorded **relative to nothing** - that is, as it stands - because the caller
    chooses the output directory and only it knows what the path is relative to. A path rewritten
    here would be this module inventing a root.

    Args:
        artifact: The reference to expand.

    Returns:
        The artifact by name.
    """
    return {
        "path": str(artifact.path),
        "kind": artifact.kind,
        "width": artifact.width,
        "height": artifact.height,
        "format": artifact.format,
        "size": artifact.size,
    }


def _error_payload(error: ImageError) -> dict[str, Any]:
    """Expand a typed error into a JSON object.

    Args:
        error: The error to expand.

    Returns:
        The error by name, with its metadata passed through.
    """
    return {
        "type": error.type,
        "message": error.message,
        "recoverable": error.recoverable,
        "metadata": dict(error.metadata),
    }


__all__ = [
    "METADATA_ARTIFACT_KIND",
    "METADATA_FILE_NAME",
    "PUBLISHED_FILE_NAMES",
    "TEMP_DIRECTORY_NAME",
    "TEMP_SUFFIX",
    "abandon",
    "build_metadata_payload",
    "discard_staged",
    "prune_staging_directory",
    "publish_json",
    "publish_metadata",
    "publish_text",
    "require_metadata_keys",
    "staging_directory",
    "temp_path",
]
