"""Tests for the page and document entry points (``PDF-09``, ``PDF-10``, ``PDF-13``).

The suite drives the real pipeline with the engine call doubled, so every assertion is
about our loop, our naming, our ordering and our error mapping.
"""

from __future__ import annotations

import hashlib
import json
import tomllib
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

from docflow.identities import ARTIFACT_METADATA_KEYS, PAGE_ARTIFACT_METADATA_KEYS
from docflow.pdf import entrypoints, process_pdf, process_pdf_page
from docflow.pdf.contracts import PDFError
from docflow.pdf.entrypoints import PROCESSOR_VERSION
from docflow.pdf.primitives import PDFPrimitiveError
from tests.fakes.engines.fake_poppler import FakePoppler
from tests.pdf.samples import (
    SAMPLE_CORRUPT,
    SAMPLE_IMAGE,
    SAMPLE_MIXED,
    SAMPLE_TEXT,
    build_request,
    image_document,
    mixed_document,
    text_document,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PAGE_DIRECTORIES = ("page_001", "page_002", "page_003")
PAGE_ARTIFACTS = (
    "source/page.pdf",
    "render/page.png",
    "native_text/text.txt",
    "native_text/blocks.json",
    "metadata.json",
)


def sha256_of(path: Path) -> str:
    """Return the digest of a file, so a test can prove it was not rewritten."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def files_under(directory: Path) -> set[str]:
    """Return every file below ``directory``, as paths relative to it."""
    return {
        path.relative_to(directory).as_posix()
        for path in directory.rglob("*")
        if path.is_file()
    }


def test_the_happy_path_processes_every_page_and_publishes_its_namespace(
    poppler: Callable[..., FakePoppler], tmp_path: Path
) -> None:
    """Acceptance: a valid multi-page PDF yields one complete unit per page."""
    poppler(text_document())
    request = build_request(SAMPLE_TEXT, tmp_path / "document")

    result = process_pdf(request)

    assert result.status == "success"
    assert result.metadata.page_count == 3
    assert len(result.pages) == 3
    assert result.source_path == SAMPLE_TEXT
    assert files_under(result.source_path.parent) != set()  # the fixture still exists
    assert {path.name for path in request.output_dir.iterdir()} == {
        "source",
        "metadata.json",
        *PAGE_DIRECTORIES,
    }
    for page_directory in PAGE_DIRECTORIES:
        page_root = request.output_dir / page_directory
        assert files_under(page_root) == set(PAGE_ARTIFACTS)
    assert not any(
        (request.output_dir / namespace).exists()
        for namespace in ("image", "ocr", "llm")
    )
    assert not list(request.output_dir.rglob("*.tmp"))


def test_the_document_metadata_records_the_provenance_and_the_identities(
    poppler: Callable[..., FakePoppler], tmp_path: Path
) -> None:
    """Acceptance: ``metadata.json`` names the processor, the engine and the unit of work."""
    poppler(text_document())
    request = build_request(SAMPLE_TEXT, tmp_path / "document")

    result = process_pdf(request)
    document_metadata = json.loads(
        (request.output_dir / "metadata.json").read_text(encoding="utf-8")
    )
    page_metadata = json.loads(
        (request.output_dir / "page_001" / "metadata.json").read_text(encoding="utf-8")
    )

    for payload in (document_metadata, page_metadata):
        assert set(ARTIFACT_METADATA_KEYS) <= set(payload)
        assert payload["processor"] == "pdf"
        assert payload["processor_version"] == PROCESSOR_VERSION
        assert payload["engine"] == "poppler"
        assert payload["engine_version"] == "1.2.3-test"
        assert payload["document_id"] == "doc-1"
        assert payload["workflow_run_id"] == "run-1"
        assert payload["processing_key"]

    assert document_metadata["page_count"] == 3
    assert document_metadata["source_sha256"] == sha256_of(SAMPLE_TEXT)
    assert len(document_metadata["page_dimensions"]) == 3
    assert page_metadata["page_number"] == 1
    assert set(PAGE_ARTIFACT_METADATA_KEYS) <= set(page_metadata)
    assert page_metadata["dpi"] == 200
    assert page_metadata["classification"] == result.pages[0].classification


def test_a_text_dominant_page_is_classified_text_with_its_blocks(
    poppler: Callable[..., FakePoppler], tmp_path: Path
) -> None:
    """Acceptance: the classification is data, and the text layer came with it."""
    poppler(text_document())
    request = build_request(SAMPLE_TEXT, tmp_path / "document")

    result = process_pdf(request)
    page = result.pages[0]

    assert page.classification == "TEXT"
    assert page.native_text is not None
    assert page.native_text.read_text(encoding="utf-8").startswith(
        "Page one of the text sample."
    )
    blocks = json.loads(
        (request.output_dir / "page_001" / "native_text" / "blocks.json").read_text(
            encoding="utf-8"
        )
    )
    assert [entry["block_id"] for entry in blocks["blocks"]] == [
        "block_001",
        "block_002",
    ]
    assert page.text_blocks[0].bbox is not None


def test_an_image_dominant_page_is_classified_image_and_keeps_its_images(
    poppler: Callable[..., FakePoppler], tmp_path: Path
) -> None:
    """Acceptance: little native text plus a visual representation is ``IMAGE``."""
    poppler(image_document())
    request = build_request(SAMPLE_IMAGE, tmp_path / "document")

    result = process_pdf(request)
    page = result.pages[0]

    assert page.classification == "IMAGE"
    assert page.status == "success"
    assert page.native_text is not None
    assert page.native_text.read_text(encoding="utf-8") == ""
    assert [embedded.image_id for embedded in page.embedded_images] == ["image_001"]
    assert (
        request.output_dir / "page_001" / "embedded_images" / "image_001.png"
    ).is_file()


def test_a_page_with_text_and_an_image_keeps_both_sources(
    poppler: Callable[..., FakePoppler], tmp_path: Path
) -> None:
    """``PDF-07``: our names and our order for a page that carries both."""
    poppler(mixed_document())
    request = build_request(SAMPLE_MIXED, tmp_path / "document")

    result = process_pdf(request)
    page = result.pages[0]

    assert page.classification == "TEXT"
    assert page.text_blocks
    assert [embedded.format for embedded in page.embedded_images] == ["jpeg"]
    assert files_under(request.output_dir / "page_001") == {
        *PAGE_ARTIFACTS,
        "embedded_images/image_001.png",
    }


def test_a_capability_that_was_not_requested_produces_no_artifact_and_no_error(
    poppler: Callable[..., FakePoppler], tmp_path: Path
) -> None:
    """``PDF-05``: the processor runs exactly what was requested."""
    fake = poppler(text_document())
    request = build_request(SAMPLE_TEXT, tmp_path / "document", render=False)

    result = process_pdf(request)

    assert result.status == "success"
    assert result.pages[0].page_image is None
    assert not (request.output_dir / "page_001" / "render").exists()
    assert "pdftoppm" not in {Path(call[0]).name for call in fake.calls}


def test_one_failing_stage_yields_a_partial_page_that_keeps_its_artifacts(
    poppler: Callable[..., FakePoppler], tmp_path: Path
) -> None:
    """Acceptance: a failing stage is described, and the valid work is not thrown away."""
    poppler(mixed_document(), failures={("pdfimages", 1): (99, "some other error")})
    request = build_request(SAMPLE_MIXED, tmp_path / "document")

    result = process_pdf(request)
    page = result.pages[0]

    assert result.status == "partial"
    assert page.status == "partial"
    assert files_under(request.output_dir / "page_001") == set(PAGE_ARTIFACTS)
    assert page.embedded_images == []
    assert page.validation.status == "IMAGE_EXTRACTION_ERROR"
    failures = [
        error
        for error in page.validation.errors
        if error.type == "IMAGE_EXTRACTION_ERROR"
    ]
    assert len(failures) == 1
    assert failures[0].recoverable is True
    assert failures[0].page_number == 1
    assert not list(request.output_dir.rglob("*.tmp"))


def test_a_page_metadata_that_cannot_be_published_is_reported(
    monkeypatch: pytest.MonkeyPatch,
    poppler: Callable[..., FakePoppler],
    tmp_path: Path,
) -> None:
    """A failure while publishing the page's own metadata is recorded, never dropped."""
    poppler(text_document())
    request = build_request(
        SAMPLE_TEXT, tmp_path / "document", render=False, extract_images=False
    )
    real_publish_json = entrypoints.publish_json

    def refuse(destination: Path, payload: Mapping[str, object]) -> Path:
        """Fail only for the page's metadata, leaving the other artifacts publishable."""
        if destination.name == "metadata.json":
            raise PDFPrimitiveError(
                PDFError(
                    type="IO_ERROR",
                    page_number=None,
                    message="refused",
                    recoverable=True,
                    metadata={},
                )
            )
        return real_publish_json(destination, payload)

    monkeypatch.setattr(entrypoints, "publish_json", refuse)

    page = process_pdf_page(request, 1, request.output_dir / "page_001")

    assert page.status == "partial"
    assert page.native_text is not None
    assert [error.type for error in page.validation.errors] == ["IO_ERROR"]
    assert not (request.output_dir / "page_001" / "metadata.json").exists()


def test_the_render_resolution_is_the_requested_one_and_reaches_the_page_metadata(
    poppler: Callable[..., FakePoppler], tmp_path: Path
) -> None:
    """``PDF-05``: the dpi is recorded, and it is the one the engine was asked for."""
    fake = poppler(text_document())
    request = build_request(SAMPLE_TEXT, tmp_path / "document", dpi=150)

    process_pdf(request)

    render_call = next(call for call in fake.calls if Path(call[0]).name == "pdftoppm")
    assert render_call[render_call.index("-r") + 1] == "150"
    page_metadata = json.loads(
        (request.output_dir / "page_001" / "metadata.json").read_text(encoding="utf-8")
    )
    assert page_metadata["dpi"] == 150


def test_a_corrupt_document_fails_before_any_engine_call(
    poppler: Callable[..., FakePoppler], tmp_path: Path
) -> None:
    """The committed corrupt fixture belongs to the pre-engine bucket."""
    fake = poppler(text_document())
    request = build_request(SAMPLE_CORRUPT, tmp_path / "document")

    result = process_pdf(request)

    assert result.status == "failed"
    assert not result.pages
    assert not result.artifacts
    assert [error.type for error in result.errors] == ["CORRUPTED_PDF"]
    assert result.validation.status == "ERROR"
    assert result.metadata.engine_version is None
    assert fake.calls == []
    assert not request.output_dir.exists()


def test_a_missing_document_fails_with_a_typed_error_and_no_exception(
    poppler: Callable[..., FakePoppler], tmp_path: Path
) -> None:
    """A failure across the contract is a result, never a raised exception."""
    fake = poppler(text_document())
    request = build_request(tmp_path / "absent.pdf", tmp_path / "document")

    result = process_pdf(request)

    assert result.status == "failed"
    assert [error.type for error in result.errors] == ["INVALID_INPUT"]
    assert fake.calls == []


def test_a_page_outside_the_document_is_refused_before_the_engine_is_asked(
    poppler: Callable[..., FakePoppler], tmp_path: Path
) -> None:
    """The engine clamps a low page silently, so the range decision is ours."""
    fake = poppler(text_document())
    request = build_request(SAMPLE_TEXT, tmp_path / "document")

    page = process_pdf_page(request, 9, request.output_dir / "page_009")

    assert page.status == "failed"
    assert page.validation.status == "ERROR"
    assert [error.type for error in page.validation.errors] == ["INVALID_INPUT"]
    assert not page.artifacts
    assert [Path(call[0]).name for call in fake.calls] == ["pdfinfo"]


def test_every_page_yields_exactly_one_result_and_one_directory(
    poppler: Callable[..., FakePoppler], tmp_path: Path
) -> None:
    """Invariant 1: page completeness.

    The mutation that must break this test is dropping a page — iterating one page short,
    or returning a prefix — which the count, the directory set and the document validation
    below all catch.
    """
    poppler(text_document())
    request = build_request(SAMPLE_TEXT, tmp_path / "document")

    result = process_pdf(request)

    assert result.metadata.page_count == 3
    assert [page.page_number for page in result.pages] == [1, 2, 3]
    assert {path.name for path in request.output_dir.glob("page_*")} == set(
        PAGE_DIRECTORIES
    )
    assert result.validation.status == "VALID"
    assert files_under(request.output_dir).issuperset(
        f"{directory}/{name}"
        for directory in PAGE_DIRECTORIES
        for name in PAGE_ARTIFACTS
    )


def test_the_input_document_is_never_modified(
    poppler: Callable[..., FakePoppler], tmp_path: Path
) -> None:
    """Invariant 2: immutable input.

    The mutation that must break this test is publishing an extracted page over
    ``request.pdf_path`` instead of into the page's ``source/`` directory: the digest
    comparison below then fails.
    """
    poppler(text_document())
    request = build_request(SAMPLE_TEXT, tmp_path / "document")
    before = sha256_of(SAMPLE_TEXT)

    process_pdf(request)

    assert sha256_of(SAMPLE_TEXT) == before
    assert (request.output_dir / "source" / "document.pdf").read_bytes() == (
        SAMPLE_TEXT.read_bytes()
    )


def test_the_recorded_processor_version_is_the_packaged_one() -> None:
    """Provenance that names a version the package does not have is a defect."""
    packaged = tomllib.loads(
        (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]["version"]

    assert packaged == PROCESSOR_VERSION


def test_the_double_answered_every_call_the_seam_made(
    poppler: Callable[..., FakePoppler], tmp_path: Path
) -> None:
    """A call the double does not model is recorded, so drift fails instead of passing."""
    fake = poppler(text_document())

    process_pdf(build_request(SAMPLE_TEXT, tmp_path / "document"))

    assert fake.unhandled == []
    assert {Path(call[0]).name for call in fake.calls} == {
        "pdfinfo",
        "pdfseparate",
        "pdftoppm",
        "pdftotext",
        "pdfimages",
    }


@pytest.mark.parametrize("fixture_path", [SAMPLE_TEXT, SAMPLE_IMAGE, SAMPLE_MIXED])
def test_the_committed_fixtures_are_real_pdf_bytes(fixture_path: Path) -> None:
    """A fixture named for a case has to be the case: header, trailer, and not empty."""
    data = fixture_path.read_bytes()

    assert data.startswith(b"%PDF-")
    assert data.rstrip().endswith(b"%%EOF")
    assert len(data) > 100
