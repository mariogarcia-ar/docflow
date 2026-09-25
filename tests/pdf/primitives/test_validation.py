"""Tests for the input fail-fast check and the result validation (``PDF-11``)."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from docflow.pdf import process_pdf, process_pdf_page
from docflow.pdf.primitives import (
    PDFPrimitiveError,
    validate_pdf,
    validate_pdf_page_result,
    validate_pdf_result,
)
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


def test_the_committed_samples_pass_the_check_without_reaching_the_engine(
    poppler: Callable[..., FakePoppler],
) -> None:
    """The fail-fast check decides from the file itself, so no engine call is spent."""
    fake = poppler()

    for sample in (SAMPLE_TEXT, SAMPLE_IMAGE, SAMPLE_MIXED):
        validate_pdf(sample)

    assert fake.calls == []


def test_a_missing_file_is_invalid_input(tmp_path: Path) -> None:
    """A document that is not there is reported as such, not opened."""
    with pytest.raises(PDFPrimitiveError) as failure:
        validate_pdf(tmp_path / "absent.pdf")

    assert failure.value.error.type == "INVALID_INPUT"
    assert failure.value.error.recoverable is False


def test_an_extension_this_processor_does_not_read_is_unsupported(
    tmp_path: Path,
) -> None:
    """The check is honest about what it claims to read."""
    candidate = tmp_path / "document.txt"
    shutil.copyfile(SAMPLE_TEXT, candidate)

    with pytest.raises(PDFPrimitiveError) as failure:
        validate_pdf(candidate)

    assert failure.value.error.type == "UNSUPPORTED_PDF"


def test_the_truncated_sample_is_corrupt_before_any_engine_call(
    poppler: Callable[..., FakePoppler],
) -> None:
    """The bucket this fixture belongs to: pre-engine, so no double is needed for it."""
    fake = poppler()

    with pytest.raises(PDFPrimitiveError) as failure:
        validate_pdf(SAMPLE_CORRUPT)

    assert failure.value.error.type == "CORRUPTED_PDF"
    assert failure.value.error.recoverable is False
    assert fake.calls == []


def test_an_encrypted_document_is_reported_from_its_own_trailer(tmp_path: Path) -> None:
    """Encryption is a typed fail-fast path; the password handling is deferred, not guessed."""
    candidate = tmp_path / "encrypted.pdf"
    candidate.write_bytes(
        b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"
        b"trailer\n<< /Size 2 /Root 1 0 R /Encrypt 3 0 R >>\n%%EOF\n"
    )

    with pytest.raises(PDFPrimitiveError) as failure:
        validate_pdf(candidate)

    assert failure.value.error.type == "ENCRYPTED_PDF"
    assert failure.value.error.recoverable is False


def test_a_header_version_this_processor_does_not_read_is_unsupported(
    tmp_path: Path,
) -> None:
    """A version outside the documented range is named, not handed to an engine."""
    candidate = tmp_path / "future.pdf"
    candidate.write_bytes(b"%PDF-3.0\n1 0 obj\nendobj\n%%EOF\n")

    with pytest.raises(PDFPrimitiveError) as failure:
        validate_pdf(candidate)

    assert failure.value.error.type == "UNSUPPORTED_PDF"
    assert failure.value.error.metadata["header"] == "%PDF-3.0"


def test_an_empty_file_is_corrupt(tmp_path: Path) -> None:
    """A zero-byte document has no header to read."""
    candidate = tmp_path / "empty.pdf"
    candidate.touch()

    with pytest.raises(PDFPrimitiveError) as failure:
        validate_pdf(candidate)

    assert failure.value.error.type == "CORRUPTED_PDF"


def test_a_page_that_declares_a_missing_artifact_is_invalid(
    poppler: Callable[..., FakePoppler], tmp_path: Path
) -> None:
    """A declared artifact that is absent is a finding, never a silent absence."""
    poppler(mixed_document())
    request = build_request(SAMPLE_MIXED, tmp_path / "document")

    page = process_pdf_page(request, 1, request.output_dir / "page_001")
    assert page.validation.status == "VALID"
    assert page.page_image is not None

    page.page_image.unlink()
    validation = validate_pdf_page_result(page)

    assert validation.status == "INVALID"
    assert validation.missing_artifacts == [page.page_image]
    assert [error.type for error in validation.errors] == ["IO_ERROR"]


def test_a_page_count_that_disagrees_with_the_pages_is_invalid(
    poppler: Callable[..., FakePoppler], tmp_path: Path
) -> None:
    """The count and the pages cannot describe two different documents."""
    poppler(text_document())
    request = build_request(SAMPLE_TEXT, tmp_path / "document")

    result = process_pdf(request)
    assert result.validation.status == "VALID"

    result.pages.pop()
    validation = validate_pdf_result(result)

    assert validation.status == "INVALID"
    assert [error.type for error in validation.errors] == ["INTERNAL_ERROR"]
    assert validation.errors[0].metadata == {"page_count": 3, "page_results": 2}


def test_the_document_result_of_a_valid_run_is_valid(
    poppler: Callable[..., FakePoppler], tmp_path: Path
) -> None:
    """The happy path validates itself: every declared artifact is on disk."""
    poppler(image_document())
    request = build_request(SAMPLE_IMAGE, tmp_path / "document")

    result = process_pdf(request)

    assert result.validation.status == "VALID"
    assert not result.validation.errors
    assert not result.validation.missing_artifacts
