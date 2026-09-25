"""Tests for the input and result validation (``IMG-10``).

Validation reports a state; it never decides what happens next. The cases below walk both
halves of that: the input checks that run before any engine call, and the structural checks over
what a result declares.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from docflow.image import (
    ArtifactRef,
    ImageError,
    ImageErrorType,
    ImageMetadata,
    ImageResult,
    ImageSourceRef,
    ImageStatus,
    ImageValidation,
    ImageVariants,
)
from docflow.image.primitives import (
    ImagePrimitiveError,
    validate_image_input,
    validate_image_result,
)
from tests.factories import build_image_options, build_image_request
from tests.image.samples import COLOR_LAYOUT


def build_result(
    *,
    tmp_path: Path,
    artifacts: list[ArtifactRef] | None = None,
    classification: str | None = "TEXT_IMAGE",
    status: ImageStatus = "success",
    failure: ImageErrorType | None = None,
) -> ImageResult:
    """Build an image result declaring the artifact refs a case needs.

    Args:
        tmp_path: Root the request is built under.
        artifacts: The artifacts the result claims to have published.
        classification: The descriptive classification, or ``None``.
        status: The run's outcome.
        failure: The typed failure the run recorded, if any.

    Returns:
        The result, assembled without running the processor.
    """
    request = build_image_request(tmp_path)
    errors = (
        []
        if failure is None
        else [
            ImageError(type=failure, message="scripted", recoverable=False, metadata={})
        ]
    )
    declared = list(artifacts or [])
    source = ImageSourceRef(
        path=request.image_path, width=None, height=None, format="png", size=None
    )
    return ImageResult(
        source=source,
        normalized=declared[0] if declared else None,
        variants=ImageVariants(
            ocr_ready=declared[1] if len(declared) > 1 else None,
            vlm_ready=None,
        ),
        metrics=None,
        classification=classification,
        transformations=[],
        validation=ImageValidation(status="ERROR", errors=errors, missing_artifacts=[]),
        artifacts=declared,
        metadata=ImageMetadata(
            processor="image",
            processor_version="0.0.0",
            engine="opencv",
            engine_version=None,
            libraries={},
            options=build_image_options(),
            input_metrics=None,
            output_metrics=None,
            timing={"total": 0.0},
            context=request.context,
        ),
        status=status,
        error=errors[0] if errors else None,
    )


def published(tmp_path: Path, name: str, *, content: bytes = b"\x89PNG\r\n\x1a\nx"):
    """Write a file under ``tmp_path/image`` and return an artifact ref for it."""
    path = tmp_path / "image" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return ArtifactRef(
        path=path,
        kind="normalized",
        width=160,
        height=120,
        format="png",
        size=len(content),
    )


def test_a_committed_sample_passes_the_input_check_without_reaching_the_engine() -> (
    None
):
    """The check is structural: a real fixture passes it with no engine involved."""
    validate_image_input(COLOR_LAYOUT)


def test_a_missing_file_is_invalid_input(tmp_path: Path) -> None:
    """There is no image to work with, and that is not recoverable."""
    with pytest.raises(ImagePrimitiveError) as failure:
        validate_image_input(tmp_path / "absent.png")

    assert failure.value.error.type == "INVALID_INPUT"
    assert failure.value.error.recoverable is False


def test_an_extension_this_processor_does_not_read_is_unsupported(
    tmp_path: Path,
) -> None:
    """A container we do not claim to read is named as such, not handed to the engine."""
    candidate = tmp_path / "scan.heic"
    candidate.write_bytes(b"not an image we read")

    with pytest.raises(ImagePrimitiveError) as failure:
        validate_image_input(candidate)

    assert failure.value.error.type == "UNSUPPORTED_FORMAT"
    assert failure.value.error.recoverable is False


def test_an_empty_file_is_invalid_input(tmp_path: Path) -> None:
    """A zero-byte file is not an image; a decode would report it, and this is cheaper."""
    candidate = tmp_path / "empty.png"
    candidate.write_bytes(b"")

    with pytest.raises(ImagePrimitiveError) as failure:
        validate_image_input(candidate)

    assert failure.value.error.type == "INVALID_INPUT"
    assert failure.value.error.metadata["size"] == 0


@pytest.mark.parametrize(
    ("failure", "expected"),
    [("DECODE_ERROR", "ERROR"), ("UNSUPPORTED_FORMAT", "UNSUPPORTED")],
)
def test_a_failed_run_reports_the_state_its_failure_names(
    tmp_path: Path, failure: ImageErrorType, expected: str
) -> None:
    """Two failures, two descriptive states: the vocabulary says which problem it was."""
    result = build_result(tmp_path=tmp_path, status="failed", failure=failure)

    validation = validate_image_result(result)

    assert validation.status == expected
    assert [error.type for error in validation.errors] == [failure]


def test_an_artifact_the_result_declares_but_never_published_is_invalid_output(
    tmp_path: Path,
) -> None:
    """A claim on disk that does not hold is a finding, with the path that is missing."""
    present = published(tmp_path, "normalized.png")
    absent = published(tmp_path, "ocr_ready.png")
    absent.path.unlink()
    result = build_result(tmp_path=tmp_path, artifacts=[present, absent])

    validation = validate_image_result(result)

    assert validation.status == "INVALID_OUTPUT"
    assert validation.missing_artifacts == [absent.path]
    assert present.path.is_file()


def test_a_published_but_degraded_image_reports_low_quality(tmp_path: Path) -> None:
    """``LOW_QUALITY`` describes the readings; it is not an invalid output."""
    artifact = published(tmp_path, "normalized.png")
    result = build_result(
        tmp_path=tmp_path, artifacts=[artifact], classification="LOW_QUALITY"
    )

    validation = validate_image_result(result)

    assert validation.status == "LOW_QUALITY"
    assert not validation.missing_artifacts


def test_a_published_usable_image_with_no_failures_is_valid(tmp_path: Path) -> None:
    """The happy path's state, and the failures the stages recorded ride along."""
    artifact = published(tmp_path, "normalized.png")
    result = build_result(tmp_path=tmp_path, artifacts=[artifact])

    validation = validate_image_result(result)

    assert validation.status == "VALID"
    assert not validation.errors
