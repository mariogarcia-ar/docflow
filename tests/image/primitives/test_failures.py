"""Tests for the primitive failure vocabulary (``IMG-02``).

The primitive layer spells out the contract's seven error kinds instead of importing them, so
that it does not depend on the processor's contract shape. This module is where that deliberate
duplication is held honest: the two lists must match exactly, in order, and a test fails the
moment one drifts.
"""

from __future__ import annotations

import typing

import pytest

from docflow.image import ImageErrorType
from docflow.image.primitives.failures import (
    PRIMITIVE_ERROR_TYPES,
    ImagePrimitiveError,
    classify_decode_failure,
    classify_input_failure,
    classify_transformation_failure,
    classify_write_failure,
)


def test_the_primitive_vocabulary_matches_the_contract_exactly() -> None:
    """The duplicated list is only safe while it is identical."""
    contract_types = typing.get_args(ImageErrorType)
    assert contract_types == PRIMITIVE_ERROR_TYPES


def test_the_vocabulary_order_is_the_contract_order() -> None:
    """Order matters because the record above documents itself as "mirrored in order"."""
    assert list(PRIMITIVE_ERROR_TYPES) == list(typing.get_args(ImageErrorType))


def test_an_unknown_error_type_is_rejected_at_construction() -> None:
    """A typo in a classifier must fail here, not silently produce an unclassifiable record."""
    with pytest.raises(ValueError, match="unknown error type"):
        # Constructing the record is the operation under test; the result is never reached.
        _ = ImagePrimitiveError(error_type="NOT_A_KIND", message="invented")


def test_a_valid_error_type_constructs_and_renders_its_path() -> None:
    """The happy path, plus the one piece of formatting the type adds."""
    failure = ImagePrimitiveError(
        error_type="DECODE_ERROR", message="truncated file", path="x.png"
    )
    assert failure.error_type == "DECODE_ERROR"
    assert str(failure) == "DECODE_ERROR: truncated file (x.png)"


def test_an_error_without_a_path_does_not_render_empty_parentheses() -> None:
    """A transformation failure concerns no file, and must not imply one."""
    failure = ImagePrimitiveError(
        error_type="TRANSFORMATION_ERROR", message="rotation failed"
    )
    assert str(failure) == "TRANSFORMATION_ERROR: rotation failed"


def test_a_readable_file_of_unknown_format_is_unsupported_not_corrupt() -> None:
    """The distinction the contract draws: format unknown is not file damaged."""
    failure = classify_decode_failure("x.heic", None, "format not recognised")
    assert failure.error_type == "UNSUPPORTED_FORMAT"


def test_a_known_format_that_fails_to_decode_is_a_decode_error() -> None:
    """And can become supported without being a different kind of failure."""
    failure = classify_decode_failure("x.png", "PNG", "truncated after header")
    assert failure.error_type == "DECODE_ERROR"
    assert failure.detail["format"] == "PNG"


def test_unreadable_input_is_an_invalid_input_not_a_decode_error() -> None:
    """A file that cannot be opened never reached the decoder."""
    failure = classify_input_failure("missing.png", "file does not exist")
    assert failure.error_type == "INVALID_INPUT"
    assert failure.recoverable is False


def test_a_write_failure_names_the_destination_and_is_not_recoverable() -> None:
    """Writing the wrong path is a bug, not a transient condition."""
    failure = classify_write_failure("out.png", "permission denied")
    assert failure.error_type == "WRITE_ERROR"
    assert failure.path == "out.png"
    assert failure.recoverable is False


def test_a_transformation_failure_records_the_operation_and_is_recoverable() -> None:
    """A transformation may legitimately be skipped and the pipeline continue."""
    failure = classify_transformation_failure("binarize", "unsupported depth")
    assert failure.error_type == "TRANSFORMATION_ERROR"
    assert failure.detail["operation"] == "binarize"
    assert failure.recoverable is True
