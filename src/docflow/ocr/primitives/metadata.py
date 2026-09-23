"""Assembling the OCR provenance record (``OCR-02`` surface).

Separate from the engine seam so that a processor version can be recorded without loading the
engine, and so the engine version has exactly one source. The engine pair is *passed in* rather
than read here: :mod:`docflow.ocr.primitives.engine` owns that answer, and a second reader would
be a second answer.

Every body raises :class:`NotImplementedError`. ``OCR-10`` implements these.
"""

from __future__ import annotations

from pathlib import Path

from docflow.ocr.contracts import (
    NormalizedOCROptions,
    OCRContext,
    OCRMetadata,
    OCRMetrics,
    OCRValidation,
)

#: This processor's version, as recorded in every artifact's ``metadata.json``.
#:
#: Deliberately a module constant rather than ``importlib.metadata.version("docflow")``, for the
#: reason the PDF and image processors record: the package is not installed in the no-install test
#: path ``pyproject.toml`` supports, so a distribution lookup would fail exactly where it is
#: needed most. Bumping it must be part of any change to what the processor produces, because
#: ``identities.PROCESSING_KEY_FORMULA`` puts the version in the reuse key.
#:
#: ``# TODO: [RELEASE]`` derive this from the package distribution once an installed deployment is
#: the only supported mode, so a release cannot ship with a stale constant.
PROCESSOR_VERSION: str = "0.0.0"


def get_processor_version() -> str:
    """Return this processor's version.

    Returns:
        The version string recorded in every artifact's ``metadata.json``.
    """
    return PROCESSOR_VERSION


def build_ocr_metadata(
    engine: str,
    engine_version: str,
    processor_version: str,
    options: NormalizedOCROptions,
    image_path: Path,
    metrics: OCRMetrics,
    validation: OCRValidation,
    timing: dict[str, float],
    transformations: list[str],
    context: OCRContext,
) -> OCRMetadata:
    """Assemble the provenance record.

    Args:
        engine: The engine's name, from the seam.
        engine_version: The engine's version, from the seam.
        processor_version: This processor's version.
        options: The normalized options used.
        image_path: The image that was read.
        metrics: The content metrics.
        validation: The validation outcome.
        timing: Wall-clock seconds by stage.
        transformations: Every transformation applied, in order.
        context: The correlation context, echoed unchanged.

    Returns:
        The record. No field has a fallback: a blank engine or version would be the silent
        stand-in the plan forbids.

    Raises:
        NotImplementedError: ``OCR-10`` implements this.

    # TODO: [MVP] implement (OCR-10).
    """
    raise NotImplementedError("build_ocr_metadata is implemented by OCR-10")


def merge_ocr_metadata(
    base: dict[str, object], extra: dict[str, object]
) -> dict[str, object]:
    """Merge engine metadata into the record.

    Args:
        base: The record so far.
        extra: The engine's own metadata.

    Returns:
        The merged record.

    Raises:
        NotImplementedError: ``OCR-10`` implements this.

    # TODO: [MVP] implement (OCR-10).
    """
    raise NotImplementedError("merge_ocr_metadata is implemented by OCR-10")


__all__ = [
    "PROCESSOR_VERSION",
    "build_ocr_metadata",
    "get_processor_version",
    "merge_ocr_metadata",
]
