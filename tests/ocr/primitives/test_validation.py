"""Tests for structural validation (``OCR-09``).

The two acceptance criteria are the spine of this module:

* given an image that contains no text, the verdict is ``EMPTY`` and **no exception escapes the
  call**;
* given an expected artifact is missing, the verdict is ``INCOMPLETE`` with a typed ``OCRError``
  naming it.

The first is exercised against the committed blank fixture through a **real conversion** — "an image
that contains no text" is a fact about an image, and ``OCR-08`` measured what Docling returns for it
(an empty document, not an error). Everything else is a unit test over a hand-built result, because
a verdict is a function of the result's own fields and asserting it should not cost a conversion.

The verdicts are checked in the order they are decided, since that order is what stops a page being
reported ``VALID`` while an artifact is missing.
"""

from __future__ import annotations

import dataclasses
import typing
from pathlib import Path

import pytest

from docflow.ocr.contracts import (
    ArtifactPaths,
    OCRContext,
    OCRError,
    OCRErrorType,
    OCROptions,
    OCRRequest,
    OCRResult,
    OCRStatus,
    OCRValidation,
    OCRValidationState,
)
from docflow.ocr.primitives import (
    analyze,
    export,
    files,
    metadata,
    pipeline,
    validation,
)
from tests.ocr.primitives import engine_corpus
from tests.ocr.primitives.engine_corpus import blank_document, extracted_document

FAT_TEXT = "a paragraph with comfortably more characters than the low-content floor"


def a_context() -> OCRContext:
    """Return a correlation context for a hand-built result.

    Returns:
        The context.
    """
    return OCRContext(document_id="doc-1", page_number=1, workflow_run_id="run-1")


def a_metadata(document: object) -> object:
    """Return a provenance record for a hand-built result.

    Built through the real builder rather than with the constructor, so a change to the record's
    shape breaks in one place instead of in every test that needed a result.

    Args:
        document: The converted document whose metrics to borrow.

    Returns:
        The record.
    """
    normalized = pipeline.normalize_docling_options(engine_corpus.requested_options())
    return metadata.build_ocr_metadata(
        engine="docling",
        engine_version="0.0.0-test",
        processor_version=metadata.get_processor_version(),
        options=normalized,
        image_path=engine_corpus.FIXTURE,
        metrics=analyze.analyze_ocr_result(document),  # type: ignore[arg-type]
        validation=OCRValidation(status="VALID", errors=[], missing_artifacts=[]),
        timing={},
        transformations=[],
        context=a_context(),
    )


PAYLOAD_SECTIONS = (
    "text",
    "paragraphs",
    "titles",
    "reading_order",
    "metadata",
)


def written_paths(directory: Path, *, omit: str | None = None) -> ArtifactPaths:
    """Return the namespace's paths, writing every artifact except one.

    Args:
        directory: The namespace to write into.
        omit: The artifact to leave unwritten, by its ``ArtifactPaths`` field name.

    Returns:
        The paths.
    """
    directory.mkdir(parents=True, exist_ok=True)
    paths = files.build_ocr_output_paths(directory)
    for name in ("text", "markdown", "structured_document", "metadata"):
        if name == omit:
            continue
        path = getattr(paths, name)
        path.write_text("{}" if path.suffix == ".json" else "content", encoding="utf-8")
    return paths


def a_result(
    directory: Path,
    *,
    text: str = FAT_TEXT,
    status: str = "success",
    omit: str | None = None,
    payload: dict[str, object] | None = None,
) -> OCRResult:
    """Return a hand-built result whose artifacts are written under a directory.

    Args:
        directory: The namespace the artifacts live in.
        text: The text the extraction carries, and the payload unless ``payload`` says otherwise.
        status: The run's outcome.
        omit: An artifact to leave unwritten.
        payload: The structured payload, or ``None`` for the documented shape.

    Returns:
        The result.
    """
    document = extracted_document()
    structured = (
        payload
        if payload is not None
        else {
            "schema_version": "1.0.0",
            "text": text,
            "paragraphs": [],
            "titles": [],
            "reading_order": [],
            "metadata": {},
        }
    )
    return OCRResult(
        text=text,
        markdown="",
        structured_document=structured,
        tables=[],
        blocks=[],
        layout=document.layout,
        reading_order=[],
        metrics=analyze.analyze_ocr_result(document),
        artifacts=written_paths(directory, omit=omit),
        validation=OCRValidation(status="VALID", errors=[], missing_artifacts=[]),
        metadata=a_metadata(document),
        status=typing.cast(OCRStatus, status),
        error=None,
    )


# ======================================================================================
# Criterion 1 - a blank input is EMPTY, and nothing is thrown
# ======================================================================================


def test_a_blank_extraction_is_empty_and_raises_nothing(tmp_path: Path) -> None:
    """The criterion, and its second half: no exception escapes the call.

    A validator that raised would push the classification onto the orchestrator, which is exactly
    what the plan says the processor must not do. The blank page comes from the engine, so the
    ``EMPTY`` verdict is about a real conversion rather than about an empty dictionary.
    """
    blank = blank_document()
    payload = {
        "schema_version": "1.0.0",
        "text": blank.text,
        "paragraphs": [],
        "titles": [],
        "reading_order": [],
        "metadata": {},
    }

    verdict = validation.validate_ocr_result(
        a_result(tmp_path, text="", payload=payload)
    )

    assert verdict.status == "EMPTY"
    assert not verdict.errors


def test_an_empty_verdict_carries_no_errors(tmp_path: Path) -> None:
    """``EMPTY`` is a complete verdict, so a caller has nothing to recover from.

    Every error in the verdict would be a failure to report; there are none, which is what makes
    ``EMPTY`` different from ``PARSE_ERROR`` — that one carries the reason it could not be judged.
    """
    payload = {"schema_version": "1.0.0", "text": "", "paragraphs": [], "titles": []}

    empty = validation.validate_ocr_result(a_result(tmp_path, text="", payload=payload))
    unparseable = validation.validate_ocr_result(a_result(tmp_path, payload={}))

    assert empty.status == "EMPTY"
    assert not empty.errors
    assert unparseable.status == "PARSE_ERROR"
    assert unparseable.errors


def test_a_missing_artifact_outranks_an_empty_extraction(tmp_path: Path) -> None:
    """The order is what makes the verdict deterministic when two findings apply at once.

    An artifact that was promised and is not there is a fact about *this run*; an empty extraction
    is a fact about the page. The run's own failure is the more actionable, so it wins.
    """
    payload = {"schema_version": "1.0.0", "text": "", "paragraphs": [], "titles": []}

    verdict = validation.validate_ocr_result(
        a_result(tmp_path, text="", payload=payload, omit="text")
    )

    assert verdict.status == "INCOMPLETE"


# ======================================================================================
# Criterion 2 - a missing artifact is INCOMPLETE with a typed error naming it
# ======================================================================================


@pytest.mark.parametrize(
    "omitted", ["text", "markdown", "structured_document", "metadata"]
)
def test_a_missing_artifact_is_incomplete_and_named(
    tmp_path: Path, omitted: str
) -> None:
    """The criterion, over every artifact the processor promises.

    Parametrized rather than tested once because the four are checked by one function that reads a
    tuple: a typo or a dropped entry would leave three of them unverified, and the suite would not
    notice which.
    """
    verdict = validation.validate_ocr_result(a_result(tmp_path, omit=omitted))

    assert verdict.status == "INCOMPLETE"
    expected = getattr(files.build_ocr_output_paths(tmp_path), omitted)
    assert expected in verdict.missing_artifacts
    assert any(str(expected) in error.message for error in verdict.errors), (
        "no typed error names the missing artifact"
    )


def test_a_missing_artifact_error_is_typed_and_recoverable_is_false(
    tmp_path: Path,
) -> None:
    """A promised artifact that is not there cannot be worked around by continuing."""
    verdict = validation.validate_ocr_result(a_result(tmp_path, omit="text"))

    assert verdict.errors
    for error in verdict.errors:
        assert error.type in typing.get_args(OCRErrorType)
        assert not error.recoverable
        assert error.metadata["artifact"]


def test_an_empty_tables_directory_is_not_incomplete(tmp_path: Path) -> None:
    """The plan's own distinction: a page with no table needs no ``tables/`` artifact.

    Requiring the directory would make every tableless page ``INCOMPLETE``, which would make the
    verdict useless for the common case.
    """
    verdict = validation.validate_ocr_result(a_result(tmp_path))

    assert verdict.status == "VALID"
    assert not any(
        path.name == files.TABLES_DIRECTORY_NAME for path in verdict.missing_artifacts
    )


# ======================================================================================
# The other verdicts, and the order they are decided in
# ======================================================================================


def test_a_failed_run_is_error_and_carries_its_own_errors(tmp_path: Path) -> None:
    """The stage that failed knows more than a reader of the result does, so its errors travel.

    ``ERROR`` is decided first, so a failed run is never described as merely incomplete.
    """
    recorded = OCRError(
        type="ENGINE_ERROR",
        message="the engine refused the page",
        recoverable=False,
        metadata={},
    )
    failed = dataclasses.replace(a_result(tmp_path), status="failed", error=recorded)

    verdict = validation.validate_ocr_result(failed)

    assert verdict.status == "ERROR"
    assert verdict.errors == [recorded]


def test_a_result_with_no_structured_document_is_a_parse_error(tmp_path: Path) -> None:
    """The engine returned nothing this processor could turn into a document.

    That is a different fact from a blank page, which is why it gets a different state.
    """
    verdict = validation.validate_ocr_result(a_result(tmp_path, payload={}))

    assert verdict.status == "PARSE_ERROR"
    assert verdict.errors
    assert verdict.errors[0].type == "ENGINE_ERROR"


def test_a_payload_without_a_schema_version_is_a_parse_error(tmp_path: Path) -> None:
    """The marker of a payload this processor produced, rather than any dict that happens to
    exist."""
    verdict = validation.validate_ocr_result(
        a_result(tmp_path, payload={"text": "plenty of text here to clear the floor"})
    )

    assert verdict.status == "PARSE_ERROR"


def test_a_thin_extraction_is_low_content(tmp_path: Path) -> None:
    """A page that yielded a stamp or a page number: the extraction worked and the result is
    thin."""
    verdict = validation.validate_ocr_result(a_result(tmp_path, text="12"))

    assert verdict.status == "LOW_CONTENT"
    assert not verdict.errors


def test_a_full_extraction_is_valid(tmp_path: Path) -> None:
    """The ordinary case, and the one that must not be reached by accident."""
    verdict = validation.validate_ocr_result(a_result(tmp_path))

    assert verdict.status == "VALID"
    assert not verdict.errors
    assert not verdict.missing_artifacts


def test_the_low_content_floor_is_measured_on_stripped_text(tmp_path: Path) -> None:
    """Padding is not content, so a page of spaces is not "low" — it is empty.

    The two states must not be reachable from the same input by different arithmetic.
    """
    verdict = validation.validate_ocr_result(a_result(tmp_path, text="   \n\t  "))

    assert verdict.status == "EMPTY"


def test_leading_padding_does_not_lift_text_over_the_floor(tmp_path: Path) -> None:
    """The discriminating input: raw length above the floor, stripped length below it.

    An earlier version of this suite used text whose stripped length *was* its raw length, so
    measuring ``len(text)`` and ``len(text.strip())`` agreed and a mutation swapping them survived.
    These two characters short of the floor with forty spaces of indentation in front are the shape
    that separates the two readings: stripping gives ``LOW_CONTENT``, not stripping gives ``VALID``.
    """
    under = " " * 40 + "x" * (validation.LOW_CONTENT_CHARACTER_FLOOR - 2)

    verdict = validation.validate_ocr_result(a_result(tmp_path, text=under))

    assert len(under) > validation.LOW_CONTENT_CHARACTER_FLOOR, (
        "the input no longer discriminates: its raw length must exceed the floor"
    )
    assert len(under.strip()) < validation.LOW_CONTENT_CHARACTER_FLOOR
    assert verdict.status == "LOW_CONTENT"


def test_the_floor_boundary_is_the_floor(tmp_path: Path) -> None:
    """Exactly at the floor is ``VALID``; one character under is ``LOW_CONTENT``.

    The comparison's direction is the whole rule, and a test that only exercised the far side would
    pass for an off-by-one.
    """
    floor = validation.LOW_CONTENT_CHARACTER_FLOOR

    at = validation.validate_ocr_result(a_result(tmp_path, text="x" * floor))
    under = validation.validate_ocr_result(a_result(tmp_path, text="x" * (floor - 1)))

    assert at.status == "VALID"
    assert under.status == "LOW_CONTENT"


def test_the_real_fixture_validates_as_valid(tmp_path: Path) -> None:
    """The committed content fixture, through the whole verdict.

    Its payload is the one ``export_docling_json`` produces, so this is the first place the
    exporter and the validator are checked against each other rather than each on its own.
    """
    document = extracted_document()
    payload = export.export_docling_json(document)
    verdict = validation.validate_ocr_result(
        a_result(
            tmp_path,
            text=document.text,
            payload=typing.cast("dict[str, object]", payload),
        )
    )

    assert verdict.status == "VALID"


# ======================================================================================
# validate_ocr_request / validate_ocr_input
# ======================================================================================


def a_request(
    tmp_path: Path, *, image: Path | None = None, directory: Path | None = None
) -> OCRRequest:
    """Return a request that validates, with optional overrides.

    Args:
        tmp_path: The test's directory.
        image: The image path, or ``None`` for one that exists.
        directory: The output directory, or ``None`` for a usable one.

    Returns:
        The request.
    """
    source = image if image is not None else engine_corpus.FIXTURE
    return OCRRequest(
        image_path=source,
        output_dir=directory if directory is not None else tmp_path / "ocr",
        options=OCROptions(
            ocr=True,
            layout=True,
            tables=True,
            reading_order=True,
            language="es",
            engine_options={},
        ),
        context=a_context(),
    )


def test_a_usable_request_has_no_failures(tmp_path: Path) -> None:
    """The ordinary request: a real image, a creatable directory, a full context."""
    assert not validation.validate_ocr_request(a_request(tmp_path))


def test_a_missing_image_is_reported_before_any_work(tmp_path: Path) -> None:
    """The failure the processor would otherwise discover after paying for a conversion."""
    errors = validation.validate_ocr_request(
        a_request(tmp_path, image=tmp_path / "absent.png")
    )

    assert [error.type for error in errors] == ["MISSING_FILE"]
    assert not errors[0].recoverable


def test_an_output_path_that_is_a_file_is_reported(tmp_path: Path) -> None:
    """A different problem from a missing image, and a different error for it."""
    occupied = tmp_path / "ocr"
    occupied.write_text("not a directory", encoding="utf-8")

    errors = validation.validate_ocr_request(a_request(tmp_path, directory=occupied))

    assert [error.type for error in errors] == ["IO_ERROR"]


def test_a_blank_document_id_is_reported(tmp_path: Path) -> None:
    """Every artifact records it, so a blank one identifies nothing."""
    request = a_request(tmp_path)
    blanked = OCRRequest(
        image_path=request.image_path,
        output_dir=request.output_dir,
        options=request.options,
        context=OCRContext(document_id="   ", page_number=1, workflow_run_id="run-1"),
    )

    errors = validation.validate_ocr_request(blanked)

    assert [error.type for error in errors] == ["INTERNAL_ERROR"]
    assert errors[0].metadata["field"] == "context.document_id"


def test_a_page_number_below_one_is_reported(tmp_path: Path) -> None:
    """Pages are documented as 1-based, so zero is not a page."""
    request = a_request(tmp_path)
    zeroed = OCRRequest(
        image_path=request.image_path,
        output_dir=request.output_dir,
        options=request.options,
        context=OCRContext(document_id="doc-1", page_number=0, workflow_run_id="run-1"),
    )

    errors = validation.validate_ocr_request(zeroed)

    assert [error.type for error in errors] == ["INTERNAL_ERROR"]
    assert errors[0].metadata["field"] == "context.page_number"


def test_validate_request_never_raises_on_a_fully_broken_request(
    tmp_path: Path,
) -> None:
    """Four failures at once, reported together rather than one at a time.

    A validator that raised on the first would make a caller fix problems in sequence, and the
    criterion says no exception escapes. The output path is a **file**, which is the only way to
    reach the ``IO_ERROR`` branch: a path that is merely absent is creatable and therefore fine.
    """
    occupied = tmp_path / "occupied"
    occupied.write_text("not a directory", encoding="utf-8")
    request = a_request(tmp_path, image=tmp_path / "absent.png", directory=occupied)
    broken = OCRRequest(
        image_path=request.image_path,
        output_dir=request.output_dir,
        options=request.options,
        context=OCRContext(document_id="", page_number=0, workflow_run_id="run-1"),
    )

    errors = validation.validate_ocr_request(broken)

    assert len(errors) == 4, f"one failure per question, all reported: {errors}"
    assert all(error.type in typing.get_args(OCRErrorType) for error in errors)


def test_a_readable_image_passes_input_validation() -> None:
    """A committed fixture that exists and holds bytes."""
    assert not validation.validate_ocr_input(engine_corpus.FIXTURE)


def test_an_absent_image_is_a_missing_file() -> None:
    """Not a decode failure: there is nothing to decode."""
    errors = validation.validate_ocr_input(Path("/tmp/does-not-exist-ocr.png"))

    assert [error.type for error in errors] == ["MISSING_FILE"]


def test_an_empty_file_is_a_decode_error(tmp_path: Path) -> None:
    """The caller was right that a file is there, and nothing can be decoded from it.

    ``DECODE_ERROR`` rather than ``MISSING_FILE``, because the two send a reader to different
    places.
    """
    empty = tmp_path / "empty.png"
    empty.write_bytes(b"")

    errors = validation.validate_ocr_input(empty)

    assert [error.type for error in errors] == ["DECODE_ERROR"]
    assert errors[0].metadata["size"] == 0


# ======================================================================================
# The vocabularies, and the state guard
# ======================================================================================


def test_the_error_vocabulary_comes_from_the_contract() -> None:
    """Derived with ``get_args`` rather than restated, so the two cannot drift.

    The image processor records the defect this avoids: two hand-written lists, where the one nobody
    edits keeps passing.
    """
    assert typing.get_args(OCRErrorType) == validation.CONTRACT_ERROR_TYPES


def test_the_state_vocabulary_comes_from_the_contract() -> None:
    """Derived the same way as the error vocabulary, and for the same reason."""
    assert typing.get_args(OCRValidationState) == validation.CONTRACT_VALIDATION_STATES


def test_an_undeclared_state_is_refused() -> None:
    """A state the contract does not declare is a defect in this module, not a fact about a page.

    Raised rather than returned: a caller cannot act on a verdict it does not recognise.
    """
    with pytest.raises(ValueError, match="unknown validation state"):
        # The private helper is called directly: this is the only input that reaches its guard,
        # since every state `validate_ocr_result` passes comes from the contract.
        validation._validation("PROBABLY_FINE", [], [])  # pylint: disable=protected-access


def test_the_unreadable_input_types_are_contract_values() -> None:
    """The subset is only useful if its members exist."""
    assert set(typing.get_args(OCRErrorType)) >= validation.UNREADABLE_INPUT_ERROR_TYPES


@pytest.mark.parametrize("state", typing.get_args(OCRValidationState))
def test_every_declared_state_is_accepted_by_the_guard(state: str) -> None:
    """The guard must not reject a state the contract declares.

    Parametrized over the contract itself, so adding a state is checked rather than assumed.
    """
    assert (
        validation._validation(state, [], []).status  # pylint: disable=protected-access
        == state
    )


def test_validation_does_not_mutate_the_payload_it_reads(tmp_path: Path) -> None:
    """The verdict is a snapshot; the result it describes is unchanged."""
    built = a_result(tmp_path)
    before = dict(built.structured_document)

    validation.validate_ocr_result(built)

    assert built.structured_document == before
