"""Structural validation and atomic publication in the ``ocr/`` namespace (``OCR-02`` surface).

Two concerns that both sit at the *boundary* of the processor, which is why they share a module:
validation says whether what the processor is about to hand back is complete, and publication is
what makes "complete" mean anything on disk.

Validation states are descriptive — ``VALID``, ``EMPTY``, ``LOW_CONTENT``, ``INCOMPLETE``,
``PARSE_ERROR``, ``ERROR`` — and never become a workflow action. Nothing here retries, and nothing
here throws: a failure is classified and returned, because the orchestrator owns the decision
about what to do next.

Atomicity lives here rather than in each caller: an artifact is written under ``ocr/.tmp/`` and
renamed into place, so a run that dies part-way leaves nothing a later stage could mistake for a
result. Every writer in the processor goes through this module.

Every body raises :class:`NotImplementedError`. ``OCR-09`` implements the validation half and
``OCR-10`` the publication half.
"""

from __future__ import annotations

from pathlib import Path

from docflow.ocr.contracts import (
    ArtifactPaths,
    OCRError,
    OCRRequest,
    OCRResult,
    OCRValidation,
)


def validate_ocr_request(request: OCRRequest) -> list[OCRError]:
    """Check the request before any work starts.

    Args:
        request: The request to check.

    Returns:
        The failures found; empty when the request is usable.

    Raises:
        NotImplementedError: ``OCR-09`` implements this.

    # TODO: [MVP] implement (OCR-09).
    """
    raise NotImplementedError("validate_ocr_request is implemented by OCR-09")


def validate_ocr_input(image_path: Path) -> list[OCRError]:
    """Check that the input image can be read.

    Args:
        image_path: The image to check.

    Returns:
        The failures found; empty when the image is readable.

    Raises:
        NotImplementedError: ``OCR-09`` implements this.

    # TODO: [MVP] implement (OCR-09).
    """
    raise NotImplementedError("validate_ocr_input is implemented by OCR-09")


def validate_ocr_result(result: OCRResult) -> OCRValidation:
    """Check a result against what it claims.

    Args:
        result: The result to validate.

    Returns:
        The verdict: a state, the typed errors behind it, and any missing artifacts.

    Raises:
        NotImplementedError: ``OCR-09`` implements this.

    # TODO: [MVP] implement (OCR-09).
    """
    raise NotImplementedError("validate_ocr_result is implemented by OCR-09")


def validate_output_artifacts(paths: ArtifactPaths) -> list[Path]:
    """Report which promised artifacts are absent.

    Args:
        paths: The paths the result claims to have published.

    Returns:
        The artifacts that were expected and not found.

    Raises:
        NotImplementedError: ``OCR-09`` implements this.

    # TODO: [MVP] implement (OCR-09).
    """
    raise NotImplementedError("validate_output_artifacts is implemented by OCR-09")


def build_ocr_output_paths(output_dir: Path) -> ArtifactPaths:
    """Return the canonical artifact paths for a namespace.

    Args:
        output_dir: The ``ocr/`` directory.

    Returns:
        Every path this processor publishes, under that directory.

    Raises:
        NotImplementedError: ``OCR-10`` implements this.

    # TODO: [MVP] implement (OCR-10).
    """
    raise NotImplementedError("build_ocr_output_paths is implemented by OCR-10")


def create_ocr_directory(output_dir: Path) -> Path:
    """Create the namespace if it is absent.

    Args:
        output_dir: The ``ocr/`` directory.

    Returns:
        The directory.

    Raises:
        NotImplementedError: ``OCR-10`` implements this.

    # TODO: [MVP] implement (OCR-10).
    """
    raise NotImplementedError("create_ocr_directory is implemented by OCR-10")


def ensure_directory(directory: Path) -> Path:
    """Create a directory if it is absent.

    Args:
        directory: The directory to ensure.

    Returns:
        The directory.

    Raises:
        NotImplementedError: ``OCR-10`` implements this.

    # TODO: [MVP] implement (OCR-10).
    """
    raise NotImplementedError("ensure_directory is implemented by OCR-10")


def write_text_atomic(path: Path, content: str) -> Path:
    """Write text atomically.

    Args:
        path: Where to publish.
        content: The text to write.

    Returns:
        The path, once the file is complete.

    Raises:
        NotImplementedError: ``OCR-10`` implements this.

    # TODO: [MVP] implement (OCR-10).
    """
    raise NotImplementedError("write_text_atomic is implemented by OCR-10")


def write_json_atomic(path: Path, payload: dict[str, object]) -> Path:
    """Write JSON atomically.

    Args:
        path: Where to publish.
        payload: The object to serialise.

    Returns:
        The path, once the file is complete.

    Raises:
        NotImplementedError: ``OCR-10`` implements this.

    # TODO: [MVP] implement (OCR-10).
    """
    raise NotImplementedError("write_json_atomic is implemented by OCR-10")


def read_json(path: Path) -> dict[str, object]:
    """Read a JSON artifact back.

    Args:
        path: The file to read.

    Returns:
        The parsed object.

    Raises:
        NotImplementedError: ``OCR-10`` implements this.

    # TODO: [MVP] implement (OCR-10).
    """
    raise NotImplementedError("read_json is implemented by OCR-10")


__all__ = [
    "build_ocr_output_paths",
    "create_ocr_directory",
    "ensure_directory",
    "read_json",
    "validate_ocr_input",
    "validate_ocr_request",
    "validate_ocr_result",
    "validate_output_artifacts",
    "write_json_atomic",
    "write_text_atomic",
]
