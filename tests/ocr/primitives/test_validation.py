"""Tests for the OCR input and result validation (``OCR-09``).

The states are descriptive, and these cases pin exactly which fact produces which one. They are
built from a hand-assembled result, so every state is reachable without an engine and without
running the entry point — the end-to-end cases live in ``tests/ocr/test_entrypoints.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from docflow.ocr.contracts import (
    ArtifactPaths,
    OCRError,
    OCRMetrics,
    OCRResult,
    OCRValidation,
)
from docflow.ocr.primitives import (
    OCRPrimitiveError,
    validate_ocr_input,
    validate_ocr_result,
    validate_output_artifacts,
)

LONG_TEXT = "A heading and a paragraph long enough to be worth reporting."


def artifacts_for(output_dir: Path) -> ArtifactPaths:
    """Return the namespace's artifact paths."""
    return ArtifactPaths(
        text=output_dir / "text.txt",
        markdown=output_dir / "document.md",
        structured_document=output_dir / "document.json",
        tables_dir=output_dir / "tables",
        metadata=output_dir / "metadata.json",
    )


def publish_content(artifacts: ArtifactPaths, *, text: str) -> None:
    """Write the content artifacts a finished run would have published."""
    artifacts.text.parent.mkdir(parents=True, exist_ok=True)
    artifacts.text.write_text(text, encoding="utf-8")
    artifacts.markdown.write_text(text, encoding="utf-8")
    artifacts.structured_document.write_text("{}", encoding="utf-8")


def result_for(
    output_dir: Path,
    *,
    text: str = LONG_TEXT,
    published: bool = True,
    recorded: tuple[OCRError, ...] = (),
    status: str = "success",
    error: OCRError | None = None,
) -> OCRResult:
    """Return a result as the entry point would assemble it."""
    artifacts = artifacts_for(output_dir)
    if published:
        publish_content(artifacts, text=text)
    failures = [*recorded, *([] if error is None else [error])]
    return OCRResult(
        text=text,
        markdown=text,
        structured_document={},
        tables=[],
        blocks=[],
        layout=None,
        reading_order=[],
        metrics=OCRMetrics(
            characters=len(text),
            words=len(text.split()),
            blocks=0,
            tables=0,
            paragraphs=0,
            text_density=0.01,
            empty=not text.strip(),
            structure_detected=False,
        ),
        artifacts=artifacts,
        validation=OCRValidation(status="VALID", errors=failures, missing_artifacts=[]),
        metadata=None,
        status=status,  # type: ignore[arg-type]
        error=error,
    )


def test_a_readable_supported_file_passes_the_input_check(tmp_path: Path) -> None:
    """The check reports nothing when there is nothing to report."""
    candidate = tmp_path / "page.png"
    candidate.write_bytes(b"\x89PNG\r\n\x1a\n")

    assert validate_ocr_input(candidate) is None


def test_a_missing_file_is_an_invalid_input(tmp_path: Path) -> None:
    """The input is the problem, so the failure is not recoverable."""
    with pytest.raises(OCRPrimitiveError) as failure:
        validate_ocr_input(tmp_path / "absent.png")

    assert failure.value.error.type == "INVALID_INPUT"
    assert failure.value.error.recoverable is False


def test_a_container_this_processor_does_not_read_is_unsupported(
    tmp_path: Path,
) -> None:
    """A format we do not read is named as such, before any engine could guess from the bytes."""
    candidate = tmp_path / "scan.heic"
    candidate.write_bytes(b"not an image we read")

    with pytest.raises(OCRPrimitiveError) as failure:
        validate_ocr_input(candidate)

    assert failure.value.error.type == "UNSUPPORTED_IMAGE"
    assert failure.value.error.metadata["suffix"] == ".heic"


def test_an_empty_file_is_an_invalid_input(tmp_path: Path) -> None:
    """A zero-byte image is nothing to read, not an image with no text in it."""
    candidate = tmp_path / "page.png"
    candidate.write_bytes(b"")

    with pytest.raises(OCRPrimitiveError) as failure:
        validate_ocr_input(candidate)

    assert failure.value.error.type == "INVALID_INPUT"
    assert failure.value.error.metadata["size"] == 0


def test_a_missing_artifact_is_reported_by_path(tmp_path: Path) -> None:
    """The check answers with the paths that are not there, in declaration order."""
    artifacts = artifacts_for(tmp_path / "ocr")
    publish_content(artifacts, text=LONG_TEXT)
    artifacts.markdown.unlink()

    missing = validate_output_artifacts(
        [artifacts.text, artifacts.markdown], allow_empty=False
    )

    assert missing == [artifacts.markdown]


def test_an_empty_file_counts_only_when_the_extraction_is_empty(tmp_path: Path) -> None:
    """A zero-byte artifact states an empty extraction, and is a lost artifact otherwise."""
    empty = tmp_path / "text.txt"
    empty.write_text("", encoding="utf-8")

    assert validate_output_artifacts([empty], allow_empty=True) == []
    assert validate_output_artifacts([empty], allow_empty=False) == [empty]


def test_a_directory_counts_as_present(tmp_path: Path) -> None:
    """An empty ``tables/`` is the absence of tables, not a missing artifact."""
    tables = tmp_path / "tables"
    tables.mkdir()

    assert validate_output_artifacts([tables], allow_empty=False) == []


def test_a_complete_extraction_validates_as_valid(tmp_path: Path) -> None:
    """Nothing recorded and nothing missing is what a good run looks like."""
    assert validate_ocr_result(result_for(tmp_path / "ocr")).status == "VALID"


def test_an_extraction_with_no_text_validates_as_empty(tmp_path: Path) -> None:
    """Emptiness is reported, not failed — and the empty artifacts are still expected."""
    result = result_for(tmp_path / "ocr", text="")

    validation = validate_ocr_result(result)

    assert validation.status == "EMPTY"
    assert not validation.errors
    assert not validation.missing_artifacts


def test_an_extraction_below_the_floor_validates_as_low_content(tmp_path: Path) -> None:
    """A page that produced almost nothing is reported as such, and the orchestrator decides."""
    validation = validate_ocr_result(result_for(tmp_path / "ocr", text="ab"))

    assert validation.status == "LOW_CONTENT"


def test_a_lost_artifact_is_incomplete_and_the_failure_names_it(tmp_path: Path) -> None:
    """The state is descriptive, and the typed failure says which file to look for."""
    result = result_for(tmp_path / "ocr")
    assert result.artifacts is not None
    result.artifacts.markdown.unlink()

    validation = validate_ocr_result(result)

    assert validation.status == "INCOMPLETE"
    assert validation.missing_artifacts == [result.artifacts.markdown]
    assert [error.type for error in validation.errors] == ["EXPORT_ERROR"]
    assert validation.errors[0].metadata["artifact"] == str(result.artifacts.markdown)


def test_the_missing_artifact_failure_is_recorded_once(tmp_path: Path) -> None:
    """Validating twice reports the same gap twice, not four times."""
    result = result_for(tmp_path / "ocr")
    assert result.artifacts is not None
    result.artifacts.text.unlink()

    first = validate_ocr_result(result)
    second = validate_ocr_result(result)

    assert len(first.errors) == 1
    assert len(second.errors) == 1


def test_a_recorded_gap_makes_the_run_incomplete_without_losing_anything(
    tmp_path: Path,
) -> None:
    """A partial conversion is not a failure: the artifacts stand and the gap is named."""
    gap = OCRError(
        type="OCR_ERROR",
        message="the table structure could not be matched",
        recoverable=True,
        metadata={},
    )
    result = result_for(tmp_path / "ocr", recorded=(gap,))

    validation = validate_ocr_result(result)

    assert validation.status == "INCOMPLETE"
    assert not validation.missing_artifacts
    assert validation.errors == [gap]


def test_a_failed_run_reports_the_state_its_failure_names(tmp_path: Path) -> None:
    """A representation that could not be produced is a parse problem, not a generic one."""
    failure = OCRError(
        type="EXPORT_ERROR", message="no markdown", recoverable=True, metadata={}
    )
    result = result_for(
        tmp_path / "ocr", published=False, status="failed", error=failure
    )

    validation = validate_ocr_result(result)

    assert validation.status == "PARSE_ERROR"
    assert validation.errors == [failure]


def test_an_engine_failure_reports_the_generic_error_state(tmp_path: Path) -> None:
    """Everything that is not a representation problem is reported as ``ERROR``."""
    failure = OCRError(
        type="ENGINE_ERROR", message="no model", recoverable=False, metadata={}
    )
    result = result_for(
        tmp_path / "ocr", published=False, status="failed", error=failure
    )

    assert validate_ocr_result(result).status == "ERROR"


def test_a_successful_run_with_nothing_to_check_is_an_internal_error(
    tmp_path: Path,
) -> None:
    """A result that claims success but reports no artifacts is a defect of the run itself."""
    result = result_for(tmp_path / "ocr")
    result.artifacts = None

    validation = validate_ocr_result(result)

    assert validation.status == "ERROR"
    assert [error.type for error in validation.errors] == ["INTERNAL_ERROR"]


def test_a_failed_run_with_no_recorded_failure_is_still_an_error(
    tmp_path: Path,
) -> None:
    """A failure with no error record is itself an error: the state never comes out ``VALID``."""
    result = result_for(tmp_path / "ocr", published=False, status="failed")

    assert validate_ocr_result(result).status == "ERROR"
