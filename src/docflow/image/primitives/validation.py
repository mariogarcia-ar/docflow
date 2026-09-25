"""Fail-fast validation of the input, and structural validation of what was produced.

Two jobs, one rule: nothing is guessed.

* :func:`validate_image_input` runs **before any engine call**, so a missing file or a
  container this processor does not read is reported as a typed failure instead of being
  handed to an engine that would answer about something else. Its failure kinds are
  ``INVALID_INPUT`` and ``UNSUPPORTED_FORMAT``.
* :func:`validate_image_result` checks what exists on disk against what the result declares,
  so an artifact the result claims to have published but did not is an ``INVALID_OUTPUT``
  finding rather than a silent absence, and a failed run maps its typed failure onto the
  descriptive ``UNSUPPORTED`` / ``ERROR`` state.

Validation never decides what happens next: it reports a state, and the orchestrator owns
every consequence of it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from docflow.image.contracts import (
    ArtifactRef,
    ImageError,
    ImageResult,
    ImageValidation,
    ImageValidationState,
)
from docflow.image.primitives.errors import typed_failure

#: Container formats this processor claims to read. Anything else is reported as
#: unsupported rather than handed to an engine that might guess from the bytes.
SUPPORTED_IMAGE_SUFFIXES: Final[tuple[str, ...]] = (
    ".bmp",
    ".jpeg",
    ".jpg",
    ".png",
    ".tif",
    ".tiff",
)

#: The validation state a failed run reports, by the kind of failure that ended it. A
#: format this processor does not read is not an error of the work, so it is named
#: ``UNSUPPORTED``; everything else is ``ERROR``.
FAILURE_VALIDATION_STATES: Final[dict[str, ImageValidationState]] = {
    "UNSUPPORTED_FORMAT": "UNSUPPORTED",
}


def validate_image_input(image_path: Path) -> None:
    """Fail fast when ``image_path`` cannot be read as an image, before any engine call.

    Args:
        image_path: The candidate image.

    Raises:
        ImagePrimitiveError: With ``INVALID_INPUT`` when there is no readable file or the
            file is empty, and ``UNSUPPORTED_FORMAT`` when its extension names a container
            this processor does not read. Neither is recoverable: the input is the problem,
            not one artifact of it.
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
            "UNSUPPORTED_FORMAT",
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


def validation_state_for(error: ImageError | None) -> ImageValidationState:
    """Return the descriptive state a failed run reports for its failure.

    Args:
        error: The failure that ended the run, or ``None``.

    Returns:
        ``"UNSUPPORTED"`` for a container this processor does not read, and ``"ERROR"`` for
        every other failure — including a missing error record, which is itself an error.
    """
    if error is None:
        return "ERROR"
    return FAILURE_VALIDATION_STATES.get(error.type, "ERROR")


def _declared_artifact_refs(result: ImageResult) -> list[ArtifactRef]:
    """Return every artifact the result declares, each one once.

    The named handles (``normalized``, ``variants``) and the ``artifacts`` list overlap by
    design, so the union is taken without counting a file twice and in declaration order.
    """
    declared = list(result.artifacts)
    if result.normalized is not None:
        declared.append(result.normalized)
    declared.extend(
        variant
        for variant in (result.variants.ocr_ready, result.variants.vlm_ready)
        if variant is not None
    )
    return list(dict.fromkeys(declared))


def _is_readable(artifact: ArtifactRef) -> bool:
    """Return whether ``artifact`` exists on disk with content."""
    return artifact.path.is_file() and artifact.path.stat().st_size > 0


def validate_image_result(result: ImageResult) -> ImageValidation:
    """Validate the result against the artifacts it declares.

    Args:
        result: The result to check; its ``validation.errors`` already carries the failures
            the stages recorded.

    Returns:
        The validation record. A failed run reports ``UNSUPPORTED`` or ``ERROR`` and keeps
        its recorded failures; a run that declares an artifact it did not publish reports
        ``INVALID_OUTPUT`` with the missing paths listed; a published image whose readings
        fell outside the usable bands reports ``LOW_QUALITY``; anything else is ``VALID``.
    """
    errors = list(result.validation.errors)
    missing = [
        artifact.path
        for artifact in _declared_artifact_refs(result)
        if not _is_readable(artifact)
    ]

    if result.status == "failed":
        return ImageValidation(
            status=validation_state_for(result.error),
            errors=errors,
            missing_artifacts=missing,
        )
    if missing:
        return ImageValidation(
            status="INVALID_OUTPUT", errors=errors, missing_artifacts=missing
        )
    if result.classification == "LOW_QUALITY":
        return ImageValidation(
            status="LOW_QUALITY", errors=errors, missing_artifacts=[]
        )
    return ImageValidation(status="VALID", errors=errors, missing_artifacts=[])
