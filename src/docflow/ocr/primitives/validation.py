# pylint: disable=duplicate-code
# Reason: this module is a deliberate sibling of ``docflow.image.primitives.validation``. Two
# processors may not import each other's internals (`README.md` §7), so the same short rules — the
# supported-suffix list, the fail-fast input check, the failure-to-state map — are written twice on
# purpose and neither copy is the other's default.
"""Fail-fast validation of the input, and structural validation of what was produced.

Two jobs, one rule: nothing is guessed.

* :func:`validate_ocr_input` runs **before any engine call**, so a missing file or a container
  this processor does not read is reported as a typed failure instead of being handed to an
  engine that would answer about something else. Its failure kinds are ``INVALID_INPUT`` and
  ``UNSUPPORTED_IMAGE``.
* :func:`validate_output_artifacts` and :func:`validate_ocr_result` check what exists on disk
  against what the result declares, and map the outcome onto the descriptive states
  ``VALID`` / ``EMPTY`` / ``LOW_CONTENT`` / ``INCOMPLETE`` / ``PARSE_ERROR`` / ``ERROR``.

The states are descriptive and nothing more: this module never decides whether OCR should have
run, nor what a ``LOW_CONTENT`` extraction should be replaced with. It reports; the orchestrator
decides.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Final

from docflow.ocr.contracts import (
    ArtifactPaths,
    OCRError,
    OCRResult,
    OCRValidation,
    OCRValidationState,
)
from docflow.ocr.primitives.composition import LOW_CONTENT_MIN_CHARACTERS
from docflow.ocr.primitives.errors import typed_failure

#: Container formats this processor claims to read. Anything else is reported as unsupported
#: rather than handed to an engine that might guess from the bytes.
SUPPORTED_IMAGE_SUFFIXES: Final[tuple[str, ...]] = (
    ".bmp",
    ".jpeg",
    ".jpg",
    ".png",
    ".tif",
    ".tiff",
)

#: The validation state a failed run reports, by the kind of failure that ended it. A failure
#: to produce a representation is reported as ``PARSE_ERROR`` — the artifact that cannot be
#: relied on is the structured document — and every other kind is ``ERROR``.
FAILURE_VALIDATION_STATES: Final[dict[str, OCRValidationState]] = {
    "EXPORT_ERROR": "PARSE_ERROR",
}


def validate_ocr_input(image_path: Path) -> None:
    """Fail fast when ``image_path`` cannot be read as an image, before any engine call.

    Args:
        image_path: The prepared image the request points at.

    Raises:
        OCRPrimitiveError: With ``INVALID_INPUT`` when there is no readable file or the file is
            empty, and ``UNSUPPORTED_IMAGE`` when its extension names a container this processor
            does not read. Neither is recoverable: the input is the problem, not one artifact of
            it.
    """
    if not image_path.is_file():
        raise typed_failure(
            "INVALID_INPUT",
            f"{image_path} is not a readable file",
            recoverable=False,
            metadata={"image_path": str(image_path)},
        )

    suffix = image_path.suffix.lower()
    if suffix not in SUPPORTED_IMAGE_SUFFIXES:
        raise typed_failure(
            "UNSUPPORTED_IMAGE",
            f"{image_path} does not have a supported image extension",
            recoverable=False,
            metadata={"image_path": str(image_path), "suffix": suffix},
        )

    if image_path.stat().st_size == 0:
        raise typed_failure(
            "INVALID_INPUT",
            f"{image_path} is empty",
            recoverable=False,
            metadata={"image_path": str(image_path), "size": 0},
        )


def validation_state_for(error: OCRError | None) -> OCRValidationState:
    """Return the descriptive state a failed run reports for its failure.

    Args:
        error: The failure that ended the run, or ``None``.

    Returns:
        ``"PARSE_ERROR"`` for a failure to produce a representation, and ``"ERROR"`` for every
        other failure — including a missing error record, which is itself an error.
    """
    if error is None:
        return "ERROR"
    return FAILURE_VALIDATION_STATES.get(error.type, "ERROR")


def _is_present(path: Path, *, allow_empty: bool) -> bool:
    """Return whether ``path`` exists with the content its kind requires.

    Args:
        path: The declared artifact.
        allow_empty: Whether a zero-byte file counts as present. A directory always does: an
            empty ``tables/`` is the absence of tables, not a missing artifact.
    """
    if path.is_dir():
        return True
    if not path.is_file():
        return False
    return allow_empty or path.stat().st_size > 0


def validate_output_artifacts(
    paths: Sequence[Path], *, allow_empty: bool
) -> list[Path]:
    """Return the declared artifacts that are not on disk.

    Args:
        paths: The artifacts the result declares.
        allow_empty: Whether an empty file is acceptable. It is exactly when the extraction is
            empty: a blank image has no text to write, and a zero-byte ``text.txt`` states that
            where the metrics and the ``EMPTY`` status already state it. A zero-byte artifact
            from a non-empty extraction is a lost artifact and is reported.

    Returns:
        The paths that are missing, in declaration order.
    """
    return [path for path in paths if not _is_present(path, allow_empty=allow_empty)]


def declared_artifacts(artifacts: ArtifactPaths, result: OCRResult) -> list[Path]:
    """Return the artifacts a successful OCR result must have published.

    ``metadata.json`` is deliberately absent: it is the record *of* the run, written after the
    extraction it describes, and a run whose own record cannot be written fails on that step
    rather than through this list. ``tables/`` is required only when the extraction found a
    table, so an image with no table is not reported as incomplete for lacking one.

    Args:
        artifacts: The declared paths.
        result: The result, read for whether it found any table.

    Returns:
        The paths to check, in publication order.
    """
    declared = [artifacts.text, artifacts.markdown, artifacts.structured_document]
    if result.tables:
        declared.append(artifacts.tables_dir)
    return declared


def missing_artifact_failures(missing: Sequence[Path]) -> list[OCRError]:
    """Return one typed failure per declared artifact that is not on disk.

    Args:
        missing: The paths reported by :func:`validate_output_artifacts`.

    Returns:
        An ``EXPORT_ERROR`` per path, each naming the artifact it is about, so a caller that
        reads only the errors still knows which file to look for.
    """
    return [
        OCRError(
            type="EXPORT_ERROR",
            message=f"{path} was not published",
            recoverable=True,
            metadata={"artifact": str(path)},
        )
        for path in missing
    ]


def validate_ocr_result(result: OCRResult) -> OCRValidation:
    """Validate a result against the artifacts it declares and the content it measured.

    **It never copies the result's failure list, and it reports on that same list.** The entry
    point shares one list between the stages and the validation, so a failure recorded *after*
    this call — a ``metadata.json`` that could not be published — still reaches the record instead
    of being dropped between the two steps.

    Args:
        result: The result to check; its ``validation.errors`` already carries the failures the
            stages recorded, and this call appends the artifacts it finds missing.

    Returns:
        The validation record. A failed run reports ``PARSE_ERROR`` or ``ERROR`` and keeps its
        recorded failures; a run that lost an artifact, or lost part of the conversion, reports
        ``INCOMPLETE`` with a typed failure naming the gap; an extraction that produced no text at
        all reports ``EMPTY``; an extraction too short to be usable reports ``LOW_CONTENT``;
        anything else is ``VALID``.
    """
    recorded = result.validation.errors

    if result.status == "failed":
        return OCRValidation(
            status=validation_state_for(result.error),
            errors=recorded,
            missing_artifacts=[],
        )

    if result.artifacts is None or result.metrics is None:
        recorded.append(
            OCRError(
                type="INTERNAL_ERROR",
                message="a successful run reported no artifacts and no metrics",
                recoverable=False,
                metadata={},
            )
        )
        return OCRValidation(status="ERROR", errors=recorded, missing_artifacts=[])

    empty = result.metrics.empty
    missing = validate_output_artifacts(
        declared_artifacts(result.artifacts, result), allow_empty=empty
    )
    for failure in missing_artifact_failures(missing):
        if failure.metadata["artifact"] not in {
            existing.metadata.get("artifact") for existing in recorded
        }:
            recorded.append(failure)

    if missing or recorded:
        return OCRValidation(
            status="INCOMPLETE", errors=recorded, missing_artifacts=missing
        )
    if empty:
        return OCRValidation(status="EMPTY", errors=recorded, missing_artifacts=[])
    if result.metrics.characters < LOW_CONTENT_MIN_CHARACTERS:
        return OCRValidation(
            status="LOW_CONTENT", errors=recorded, missing_artifacts=[]
        )
    return OCRValidation(status="VALID", errors=recorded, missing_artifacts=[])
