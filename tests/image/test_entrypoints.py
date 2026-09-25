"""Tests for the image entry points (``IMG-12``, ``IMG-13``).

The suite drives the real pipeline with the engine doubled, so every assertion is about our
flow, our naming, our recording and our error mapping. The three invariants the subplan §6
fixes live here, each with the mutation that must break it named in its docstring and recorded
in the root ``README.md``.
"""

from __future__ import annotations

import json
import tomllib
from collections.abc import Callable
from pathlib import Path

import pytest

from docflow.identities import ARTIFACT_METADATA_KEYS
from docflow.image import ImageError, process_image_from_page
from docflow.image.entrypoints import PROCESSOR_VERSION, process_image
from docflow.image.primitives import ImagePrimitiveError
from tests.fakes.engines.fake_opencv import FakeOpenCV
from tests.image.samples import (
    COLOR_LAYOUT,
    CORRUPT,
    EMBEDDED_LOGO,
    SKEWED_TEXT,
    build_options,
    build_request,
)
from tests.support import files_under, sha256_of

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

#: Every artifact the happy path publishes, in the namespace the plan fixes.
HAPPY_PATH_ARTIFACTS = {
    "metadata.json",
    "normalized.png",
    "ocr_ready.png",
    "vlm_ready.png",
}

#: The other processors' namespaces, none of which this processor may touch.
OTHER_NAMESPACES = ("source", "render", "native_text", "ocr", "llm")


def metadata_of(output_dir: Path) -> dict:
    """Return the parsed ``metadata.json`` of a finished run."""
    return json.loads((output_dir / "metadata.json").read_text(encoding="utf-8"))


def test_the_happy_path_publishes_the_namespace_and_a_complete_result(
    opencv: Callable[..., FakeOpenCV], tmp_path: Path
) -> None:
    """Acceptance: a valid colour input yields the three representations and one result."""
    opencv()
    request = build_request(COLOR_LAYOUT, tmp_path / "image")

    result = process_image(request)

    assert result.status == "success"
    assert result.classification in {
        "TEXT_IMAGE",
        "VISUAL_IMAGE",
        "MIXED_IMAGE",
        "LOW_QUALITY",
    }
    assert files_under(request.output_dir) == HAPPY_PATH_ARTIFACTS
    assert result.normalized is not None
    assert result.variants.ocr_ready is not None
    assert result.variants.vlm_ready is not None
    assert not list(tmp_path.rglob("*.tmp"))
    assert not any((tmp_path / namespace).exists() for namespace in OTHER_NAMESPACES)


def test_the_metadata_records_the_provenance_the_identities_and_the_transformations(
    opencv: Callable[..., FakeOpenCV], tmp_path: Path
) -> None:
    """Acceptance: ``metadata.json`` names the processor, the engine and what was applied."""
    opencv()
    request = build_request(COLOR_LAYOUT, tmp_path / "image")

    result = process_image(request)
    payload = metadata_of(request.output_dir)

    assert set(ARTIFACT_METADATA_KEYS) <= set(payload)
    assert payload["processor"] == "image"
    assert payload["processor_version"] == PROCESSOR_VERSION
    assert payload["engine"] == "opencv"
    assert payload["engine_version"] == FakeOpenCV.__version__
    assert payload["document_id"] == "doc-1"
    assert payload["workflow_run_id"] == "run-1"
    assert payload["processing_key"]
    assert payload["libraries"] == {"opencv": FakeOpenCV.__version__}
    assert payload["status"] == "success"
    assert payload["classification"] == result.classification
    assert payload["options"] == {
        "normalize": True,
        "prepare_for_ocr": True,
        "prepare_for_vlm": True,
        "correct_orientation": True,
        "deskew": True,
    }
    assert payload["input_metrics"]["dimensions"] == {"width": 160, "height": 120}
    assert payload["output_metrics"]["format"] == "png"


def test_the_two_variants_are_written_by_their_own_pipelines(
    opencv: Callable[..., FakeOpenCV], tmp_path: Path
) -> None:
    """Acceptance: OCR and VLM prepare independently, and each pipeline's work is recorded."""
    opencv()
    request = build_request(COLOR_LAYOUT, tmp_path / "image")

    result = process_image(request)
    payload = metadata_of(request.output_dir)

    ocr = result.variants.ocr_ready
    vlm = result.variants.vlm_ready
    assert ocr is not None and vlm is not None
    assert ocr.path != vlm.path
    assert ocr.path.read_bytes() != vlm.path.read_bytes()
    assert (
        payload["variant_transformations"]["ocr_ready"]
        != payload["variant_transformations"]["vlm_ready"]
    )
    assert "binarize" in payload["variant_transformations"]["ocr_ready"]
    assert "binarize" not in payload["variant_transformations"]["vlm_ready"]
    assert set(payload["variant_transformations"]) == {
        "normalized",
        "ocr_ready",
        "vlm_ready",
    }


def test_a_variant_that_was_not_requested_is_none_and_produces_no_artifact(
    opencv: Callable[..., FakeOpenCV], tmp_path: Path
) -> None:
    """Absence is reported as absence: no empty ref, and no file standing in for one."""
    opencv()
    request = build_request(
        COLOR_LAYOUT,
        tmp_path / "image",
        prepare_for_ocr=False,
        prepare_for_vlm=False,
    )

    result = process_image(request)

    assert result.variants.ocr_ready is None
    assert result.variants.vlm_ready is None
    assert not result.transformations
    assert files_under(request.output_dir) == {"metadata.json", "normalized.png"}
    assert metadata_of(request.output_dir)["variant_transformations"] == {
        "normalized": []
    }


def test_a_corrupt_input_is_a_typed_decode_error_and_publishes_nothing(
    opencv: Callable[..., FakeOpenCV], tmp_path: Path
) -> None:
    """Acceptance: an undecodable file is refused, and no partial artifact is published."""
    opencv()
    request = build_request(CORRUPT, tmp_path / "image")

    result = process_image(request)

    assert result.status == "failed"
    assert result.error is not None
    assert result.error.type == "DECODE_ERROR"
    assert result.error.recoverable is False
    assert result.validation.status == "ERROR"
    assert not result.artifacts
    assert result.normalized is None
    assert result.metrics is None
    assert result.classification is None
    assert not request.output_dir.exists()
    assert not list(tmp_path.rglob("*"))


def test_an_unsupported_container_is_named_as_such_and_never_decoded(
    opencv: Callable[..., FakeOpenCV], tmp_path: Path
) -> None:
    """The refusal happens before the engine is asked, and the state says which problem it was."""
    fake = opencv()
    candidate = tmp_path / "scan.heic"
    candidate.write_bytes(b"not an image we read")

    result = process_image(build_request(candidate, tmp_path / "image"))

    assert result.error is not None
    assert result.error.type == "UNSUPPORTED_FORMAT"
    assert result.validation.status == "UNSUPPORTED"
    assert fake.calls == []


def test_a_missing_input_is_reported_rather_than_raised(
    opencv: Callable[..., FakeOpenCV], tmp_path: Path
) -> None:
    """A failure is data on the result: no exception crosses the contract."""
    opencv()

    result = process_image(build_request(tmp_path / "absent.png", tmp_path / "image"))

    assert result.status == "failed"
    assert result.error is not None
    assert result.error.type == "INVALID_INPUT"
    assert result.source.size is None
    assert result.source.width is None


def test_the_input_image_is_never_modified(
    opencv: Callable[..., FakeOpenCV], tmp_path: Path
) -> None:
    """Invariant 1: immutable input.

    The mutation that must break this test is making a publication write to ``image_path``
    itself — publishing the normalized image over the source instead of into the namespace —
    which the digest comparison below catches.
    """
    opencv()
    request = build_request(COLOR_LAYOUT, tmp_path / "image")
    before = sha256_of(COLOR_LAYOUT)
    modified = COLOR_LAYOUT.stat().st_mtime_ns

    process_image(request)

    assert sha256_of(COLOR_LAYOUT) == before
    assert COLOR_LAYOUT.stat().st_mtime_ns == modified
    assert (
        request.output_dir / "normalized.png"
    ).read_bytes() != COLOR_LAYOUT.read_bytes()


def test_the_ocr_and_vlm_variants_are_never_one_artifact(
    opencv: Callable[..., FakeOpenCV], tmp_path: Path
) -> None:
    """Invariant 2: the OCR variant is not the VLM variant.

    The mutation that must break this test is making ``prepare_image_for_vlm`` return the path
    ``prepare_image_for_ocr`` wrote — the two paths, or the two recorded transformation lists,
    then coincide.
    """
    opencv()
    request = build_request(COLOR_LAYOUT, tmp_path / "image")

    result = process_image(request)
    payload = metadata_of(request.output_dir)

    ocr = result.variants.ocr_ready
    vlm = result.variants.vlm_ready
    assert ocr is not None and vlm is not None
    assert ocr.path.name == "ocr_ready.png"
    assert vlm.path.name == "vlm_ready.png"
    assert ocr.path != vlm.path
    assert ocr.size != vlm.size
    assert payload["variant_transformations"]["ocr_ready"] == [
        "convert_to_grayscale",
        "binarize",
    ]
    assert payload["variant_transformations"]["vlm_ready"] == []


def test_every_artifact_the_result_declares_lives_under_the_image_namespace(
    opencv: Callable[..., FakeOpenCV], tmp_path: Path
) -> None:
    """Invariant 3: namespace ownership.

    The mutation that must break this test is redirecting ``metadata.json`` to the parent
    directory — the file listing below then finds a file outside the ``image/`` namespace.
    """
    opencv()
    request = build_request(COLOR_LAYOUT, tmp_path / "image")

    result = process_image(request)

    assert set(request.output_dir.iterdir()) == {
        request.output_dir / name for name in HAPPY_PATH_ARTIFACTS
    }
    for artifact in result.artifacts:
        assert artifact.path.is_relative_to(request.output_dir)
        assert artifact.path.stat().st_size > 0
    assert {path.name for path in tmp_path.iterdir()} == {"image"}
    assert not any((tmp_path / namespace).exists() for namespace in OTHER_NAMESPACES)


def test_a_variant_that_cannot_be_published_is_reported_and_the_run_is_not_a_success(
    opencv: Callable[..., FakeOpenCV], tmp_path: Path
) -> None:
    """A lost artifact is named, and the run never claims a success with a missing file."""
    opencv(write_failures={"ocr_ready.png"})
    request = build_request(COLOR_LAYOUT, tmp_path / "image")

    result = process_image(request)

    assert result.status == "failed"
    assert result.variants.ocr_ready is None
    assert result.normalized is not None
    assert result.variants.vlm_ready is not None
    assert [error.type for error in result.validation.errors] == ["WRITE_ERROR"]
    assert result.validation.status == "ERROR"
    assert not (request.output_dir / "ocr_ready.png").exists()
    assert not list(tmp_path.rglob("*.tmp"))


def test_a_metadata_that_cannot_be_published_is_reported(
    opencv: Callable[..., FakeOpenCV],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The run's own record is part of the run: losing it is a failure, not a footnote."""
    opencv()

    def refuse(*_arguments: object) -> Path:
        """Fail the way a refused publication does."""
        raise ImagePrimitiveError(
            ImageError(
                type="WRITE_ERROR",
                message="scripted refusal",
                recoverable=True,
                metadata={},
            )
        )

    monkeypatch.setattr("docflow.image.entrypoints.publish_json", refuse)
    request = build_request(COLOR_LAYOUT, tmp_path / "image")

    result = process_image(request)

    assert result.status == "failed"
    assert result.error is not None and result.error.type == "WRITE_ERROR"
    assert not (request.output_dir / "metadata.json").exists()
    assert (request.output_dir / "normalized.png").is_file()


def test_the_entry_point_for_a_rendered_page_carries_the_page_identity(
    opencv: Callable[..., FakeOpenCV], tmp_path: Path
) -> None:
    """The wrapper builds the request and delegates; it never opens a PDF."""
    opencv()

    result = process_image_from_page(
        image_path=COLOR_LAYOUT,
        output_dir=tmp_path / "image",
        options=build_options(),
        document_id="doc-9",
        page_number=7,
        workflow_run_id="run-9",
    )

    assert result.status == "success"
    assert result.metadata.context.document_id == "doc-9"
    assert result.metadata.context.page_number == 7
    assert metadata_of(tmp_path / "image")["workflow_run_id"] == "run-9"


def test_the_recorded_processor_version_is_the_packaged_one() -> None:
    """Provenance that names a version the package does not have is a defect."""
    packaged = tomllib.loads(
        (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]["version"]

    assert packaged == PROCESSOR_VERSION


def test_the_double_answered_every_call_the_seam_made(
    opencv: Callable[..., FakeOpenCV], tmp_path: Path
) -> None:
    """The engine is reached through the seam and nowhere else."""
    fake = opencv()

    process_image(build_request(COLOR_LAYOUT, tmp_path / "image"))

    assert "imread" in fake.calls
    assert "imwrite" in fake.calls
    assert fake.writes[0][0] == "normalized.png"


@pytest.mark.parametrize("fixture_path", [COLOR_LAYOUT, SKEWED_TEXT, EMBEDDED_LOGO])
def test_the_committed_fixtures_are_real_png_bytes(fixture_path: Path) -> None:
    """A fixture named for a case has to be the case: a signature, a header and an end chunk."""
    data = fixture_path.read_bytes()

    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    assert b"IHDR" in data[:32]
    assert b"IEND" in data[-16:]
    assert len(data) > 100


def test_the_truncated_fixture_is_the_happy_path_one_without_its_end() -> None:
    """The failure sample is a real prefix, not invented bytes."""
    assert COLOR_LAYOUT.read_bytes().startswith(CORRUPT.read_bytes())
    assert len(CORRUPT.read_bytes()) < len(COLOR_LAYOUT.read_bytes())
