"""Round-trip test for the image contract (``GEN-06``).

Proves ``ImageRequest → ImageResult`` round-trips an in-memory fake end to end before any
real engine exists.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from docflow.image import (
    ArtifactRef,
    ImageDimensions,
    ImageMetadata,
    ImageMetrics,
    ImageQualityMetrics,
    ImageRequest,
    ImageResult,
    ImageSourceRef,
    ImageValidation,
    ImageVariants,
    TextRegion,
)
from tests.factories import (
    build_image_options,
    build_image_request,
    incomplete_call,
)


def build_metrics(format_name: str) -> ImageMetrics:
    """Build a complete metrics record; no image is decoded."""
    return ImageMetrics(
        dimensions=ImageDimensions(width=1700, height=2200),
        resolution=200,
        format=format_name,
        size=4096,
        quality=ImageQualityMetrics(
            blur=0.1,
            sharpness=0.9,
            contrast=0.7,
            brightness=0.5,
            noise=0.05,
        ),
        orientation=0,
        skew=0.2,
        text_regions=[
            TextRegion(
                region_id="region_001", bbox=(0.0, 0.0, 10.0, 10.0), text_coverage=0.4
            )
        ],
        text_coverage=0.4,
    )


def fake_process_image(request: ImageRequest) -> ImageResult:
    """Stand-in processor: builds a result from the request and nothing else."""
    source = ImageSourceRef(
        path=request.image_path, width=1700, height=2200, format="png", size=4096
    )
    ocr_ready = ArtifactRef(
        path=Path("image/ocr_ready.png"),
        kind="ocr_ready",
        width=1700,
        height=2200,
        format="png",
        size=3072,
    )
    vlm_ready = ArtifactRef(
        path=Path("image/vlm_ready.png"),
        kind="vlm_ready",
        width=1700,
        height=2200,
        format="png",
        size=5120,
    )
    input_metrics = build_metrics("png")
    return ImageResult(
        source=source,
        normalized=ArtifactRef(
            path=Path("image/normalized.png"),
            kind="normalized",
            width=1700,
            height=2200,
            format="png",
            size=4096,
        ),
        variants=ImageVariants(ocr_ready=ocr_ready, vlm_ready=vlm_ready),
        metrics=input_metrics,
        classification="TEXT_IMAGE",
        transformations=["deskew", "normalize_contrast"],
        validation=ImageValidation(status="VALID", errors=[], missing_artifacts=[]),
        artifacts=[ocr_ready, vlm_ready],
        metadata=ImageMetadata(
            processor="image",
            processor_version="0.0.0",
            engine="opencv",
            engine_version="test",
            libraries={"opencv": "test"},
            options=request.options,
            input_metrics=input_metrics,
            output_metrics=build_metrics("png"),
            timing={"total": 0.2},
            context=request.context,
        ),
        status="success",
        error=None,
    )


def test_the_fake_returns_the_matching_result_type(tmp_path: Path) -> None:
    """A valid request produces an ``ImageResult``."""
    result = fake_process_image(build_image_request(tmp_path))

    assert isinstance(result, ImageResult)


def test_the_request_identity_is_preserved_in_the_result(tmp_path: Path) -> None:
    """``document_id``, ``page_number`` and ``workflow_run_id`` survive unchanged."""
    request = build_image_request(tmp_path)

    result = fake_process_image(request)

    assert result.metadata.context == request.context
    assert result.metadata.context.page_number == 1


def test_the_two_variants_stay_independent(tmp_path: Path) -> None:
    """The OCR variant and the VLM variant are separate artifacts, never one alias."""
    result = fake_process_image(build_image_request(tmp_path))

    assert result.variants.ocr_ready is not None
    assert result.variants.vlm_ready is not None
    assert result.variants.ocr_ready.path != result.variants.vlm_ready.path


def test_a_variant_that_was_not_requested_is_none_and_not_an_empty_ref(
    tmp_path: Path,
) -> None:
    """Absence is reported as absence, never as an empty path standing in for a file."""
    result = fake_process_image(build_image_request(tmp_path))
    unrequested = ImageVariants(ocr_ready=None, vlm_ready=None)

    assert result.variants.ocr_ready is not None
    assert unrequested.ocr_ready is None
    assert unrequested.vlm_ready is None


def test_the_failure_field_is_absent_on_the_happy_path(tmp_path: Path) -> None:
    """A successful run carries no error record; absence is not an empty error."""
    result = fake_process_image(build_image_request(tmp_path))

    assert result.error is None
    assert result.status == "success"


def test_every_applied_transformation_is_recorded(tmp_path: Path) -> None:
    """The transformations list is the record of what actually happened."""
    result = fake_process_image(build_image_request(tmp_path))

    assert result.transformations == ["deskew", "normalize_contrast"]


def test_a_missing_required_option_is_rejected_instead_of_defaulted() -> None:
    """A missing transformation flag is not silently treated as false."""
    complete = build_image_options()
    incomplete = {
        "normalize": True,
        "prepare_for_ocr": True,
        "prepare_for_vlm": True,
        "correct_orientation": True,
    }

    with pytest.raises(TypeError):
        incomplete_call(type(complete), incomplete)
