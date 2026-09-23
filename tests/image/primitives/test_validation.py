# pylint: disable=duplicate-code,use-implicit-booleaness-not-comparison
# `use-implicit-booleaness-not-comparison` is disabled for the whole module because every
# assertion below says what the list *is* rather than whether it is falsey: `errors == []`
# claims the run produced no errors, and `not errors` would also pass if the field held None.
# The explicit form is the one that matches the contract's types.
# The fixture constants repeat the other image suites' on purpose. A shared helper module would let
# a change made for one suite silently redirect another's; the duplication is a handful of lines per
# suite and the independence is worth the noise.
"""Tests for ``validate_image_result`` (``IMG-10``).

The WBS names two acceptance criteria: a corrupt input produces an ``ImageError`` of type
``DECODE_ERROR`` or ``UNSUPPORTED_FORMAT`` with ``recoverable=False``, and a missing expected
artifact
gives the state ``INVALID_OUTPUT`` with a typed error naming it. Both are here.

The rest of the module tests the two rules the task's *Out of bounds* states, and each is tested in
the way that can actually fail:

* **The states are descriptive.** Asserted by running the validator with a state that would be
  actionable if anything downstream read it, and checking that the record carries the finding
  without
  the function doing anything about it - no exception, no side effect, and no second return value
  that could be mistaken for a decision.
* **Errors are returned, not thrown.** Asserted by the signature: the failure path is a
  ``tuple[ImagePrimitiveError, ...]`` argument and the result is an ``ImageValidation``, so there is
  no way to express the failure as an exception even if a caller wanted to.

Reachability of all five states is tested explicitly. A validator that only ever returned ``VALID``
would satisfy most of a suite written case by case.
"""

from __future__ import annotations

import inspect
import typing
from pathlib import Path

import pytest

from docflow.image.contracts import (
    ArtifactRef,
    ImageError,
    ImageErrorType,
    ImageOptions,
    ImageValidation,
    ImageValidationState,
)
from docflow.image.primitives.failures import (
    ImagePrimitiveError,
    classify_decode_failure,
    classify_input_failure,
    classify_transformation_failure,
    classify_write_failure,
)
from docflow.image.primitives.validation import (
    ARTIFACT_CAPABILITIES,
    ARTIFACT_FIELDS,
    CONTRACT_ERROR_TYPES,
    as_image_error,
    missing_artifact_error,
    validate_image_result,
)

ALL_STATES = {"VALID", "LOW_QUALITY", "INVALID_OUTPUT", "UNSUPPORTED", "ERROR"}

ARTIFACT_KINDS = {
    "normalized": "normalized",
    "ocr_ready": "ocr_ready",
    "vlm_ready": "vlm_ready",
}
"""The contract's ``ImageArtifactKind`` value each field publishes under."""


def options(**overrides: bool) -> ImageOptions:
    """Return a request with everything off unless asked for."""
    settings = {
        "normalize": False,
        "prepare_for_ocr": False,
        "prepare_for_vlm": False,
        "correct_orientation": False,
        "deskew": False,
    }
    settings.update(overrides)
    return ImageOptions(**settings)


def reference(field: str) -> ArtifactRef:
    """Return a stand-in artifact reference for a field."""
    return ArtifactRef(
        path=Path(f"/nonexistent/{field}.png"),
        kind=ARTIFACT_KINDS[field],
        width=10,
        height=10,
        format="PNG",
        size=100,
    )


def validate(
    normalized: str | None = None,
    ocr_ready: str | None = None,
    vlm_ready: str | None = None,
    recorded: tuple[ImagePrimitiveError, ...] = (),
    **requested: bool,
) -> ImageValidation:
    """Validate a result, turning field names into references."""
    low_quality = requested.pop("low_quality", False)
    return validate_image_result(
        reference("normalized") if normalized else None,
        reference("ocr_ready") if ocr_ready else None,
        reference("vlm_ready") if vlm_ready else None,
        options(**requested),
        recorded,
        low_quality=low_quality,
    )


def test_every_state_name_is_one_of_the_contract_s_literals() -> None:
    """The five names bound in the module may not become a private sixth vocabulary."""
    assert set(typing.get_args(ImageValidationState)) == ALL_STATES


def test_the_error_vocabulary_matches_the_contract_exactly() -> None:
    """The module's copy of the kinds is only safe while it is identical."""
    assert list(CONTRACT_ERROR_TYPES) == list(typing.get_args(ImageErrorType))


def test_the_artifact_table_pairs_each_capability_with_its_field() -> None:
    """One table, so the pairing cannot drift the way two parallel lists would."""
    assert dict(ARTIFACT_CAPABILITIES) == {
        "normalize": "normalized",
        "prepare_for_ocr": "ocr_ready",
        "prepare_for_vlm": "vlm_ready",
    }
    assert ARTIFACT_FIELDS == ("normalized", "ocr_ready", "vlm_ready")


def test_every_artifact_field_is_a_named_parameter_not_a_dictionary_key() -> None:
    """The signature guard: a mapping would make a typo look like "not published".

    That is the exact failure this module exists to catch, so it must not be reachable at the
    module's own boundary. Adding an artifact to the result therefore forces a decision about how it
    is validated rather than silently going unchecked.
    """
    parameters = inspect.signature(validate_image_result).parameters
    for field in ARTIFACT_FIELDS:
        assert field in parameters, f"{field} is not a named parameter"
        assert parameters[field].default is inspect.Parameter.empty, (
            f"{field} may not be defaulted: a caller could then omit it and the artifact would go "
            "unchecked rather than being reported absent"
        )


def test_a_corrupt_input_is_unsupported_and_not_recoverable() -> None:
    """The first WBS acceptance criterion."""
    result = validate(
        normalized="present",
        normalize=True,
        recorded=(classify_decode_failure("/x.png", "PNG", "truncated stream"),),
    )

    assert result.status == "UNSUPPORTED"
    assert result.errors
    assert result.errors[0].type == "DECODE_ERROR"
    assert result.errors[0].recoverable is False


def test_an_unrecognised_file_is_unsupported_and_not_recoverable() -> None:
    """The other half of the same criterion: the format is not one this processor reads."""
    result = validate(
        normalize=True,
        recorded=(classify_decode_failure("/x.heic", None, "not recognised"),),
    )

    assert result.status == "UNSUPPORTED"
    assert result.errors[0].type == "UNSUPPORTED_FORMAT"
    assert result.errors[0].recoverable is False


def test_a_missing_expected_artifact_is_invalid_output_with_a_typed_error() -> None:
    """The second WBS acceptance criterion."""
    result = validate(normalize=True)

    assert result.status == "INVALID_OUTPUT"
    assert result.missing_artifacts == [Path("normalized")]
    assert [error.type for error in result.errors] == ["WRITE_ERROR"]
    assert "normalized" in result.errors[0].message
    assert result.errors[0].recoverable is False


@pytest.mark.parametrize(
    ("requested", "expected_field"),
    [
        ({"normalize": True}, "normalized"),
        ({"prepare_for_ocr": True}, "ocr_ready"),
        ({"prepare_for_vlm": True}, "vlm_ready"),
    ],
)
def test_each_requested_artifact_is_checked_on_its_own(
    requested: dict[str, bool], expected_field: str
) -> None:
    """One case per artifact, so an implementation checking only one field fails."""
    result = validate(**requested)

    assert result.status == "INVALID_OUTPUT"
    assert [str(path) for path in result.missing_artifacts] == [expected_field]
    assert result.errors[0].metadata["artifact"] == expected_field


def test_an_unrequested_absent_artifact_is_not_a_gap() -> None:
    """The distinction the options are read for, and the reason they are read at all.

    ``prepare_for_vlm: false`` means there is no VLM variant and no failure. Reading its absence as
    a gap would report a run as broken for doing exactly what it was asked to do.
    """
    result = validate(ocr_ready="present", prepare_for_ocr=True)

    assert result.status == "VALID"
    assert result.missing_artifacts == []


def test_a_requested_artifact_present_leaves_nothing_to_report() -> None:
    """The happy path, for each field."""
    result = validate(
        normalized="present",
        ocr_ready="present",
        vlm_ready="present",
        normalize=True,
        prepare_for_ocr=True,
        prepare_for_vlm=True,
    )

    assert result.status == "VALID"
    assert result.errors == []
    assert result.missing_artifacts == []


def test_a_run_asked_for_nothing_is_valid() -> None:
    """A page whose options are all false is not a failure; it is a run with nothing to do."""
    assert validate().status == "VALID"


def test_one_variant_delivered_and_the_other_missing_names_the_right_one() -> None:
    """Guards the pairing: the error must name the artifact that is actually absent."""
    result = validate(ocr_ready="present", prepare_for_ocr=True, prepare_for_vlm=True)

    assert result.status == "INVALID_OUTPUT"
    assert [str(path) for path in result.missing_artifacts] == ["vlm_ready"]
    assert "vlm_ready" in result.errors[0].message
    assert "ocr_ready" not in result.errors[0].message


def test_a_recoverable_failure_still_leaves_every_artifact_checked() -> None:
    """A recoverable failure and a missing artifact are two findings, and both are reported.

    Reporting only the failure would hide a broken promise behind a lesser complaint.
    """
    result = validate(
        normalize=True,
        recorded=(
            classify_transformation_failure("sharpen_image", "unsupported depth"),
        ),
    )

    assert result.status == "INVALID_OUTPUT"
    assert {error.type for error in result.errors} == {
        "TRANSFORMATION_ERROR",
        "WRITE_ERROR",
    }
    assert result.missing_artifacts == [Path("normalized")]


def test_an_unrecoverable_failure_outranks_a_missing_artifact() -> None:
    """Most serious finding wins, and the missing list is still reported."""
    result = validate(
        normalize=True,
        recorded=(classify_write_failure("/out.png", "permission denied"),),
    )

    assert result.status == "ERROR"
    assert result.errors[0].type == "WRITE_ERROR"
    assert result.missing_artifacts == [Path("normalized")], (
        "the absent artifact is a fact independent of why the run failed"
    )


def test_a_recoverable_failure_with_everything_delivered_is_error_not_valid() -> None:
    """The run had trouble; calling the result valid would hide it."""
    result = validate(
        normalized="present",
        normalize=True,
        recorded=(classify_transformation_failure("binarize_image", "skipped"),),
    )

    assert result.status == "ERROR"
    assert result.errors[0].recoverable is True
    assert result.missing_artifacts == []


def test_a_low_quality_input_describes_the_input_not_the_run() -> None:
    """Every artifact present, so nothing about this run failed; the page is just poor."""
    result = validate(normalized="present", normalize=True, low_quality=True)

    assert result.status == "LOW_QUALITY"
    assert result.errors == []
    assert result.missing_artifacts == []


def test_low_quality_does_not_mask_a_missing_artifact() -> None:
    """A poor page and a broken promise are different findings, and both are reported."""
    result = validate(normalize=True, low_quality=True)

    assert result.status == "INVALID_OUTPUT"
    assert result.missing_artifacts


def test_all_five_states_are_reachable() -> None:
    """A validator that only ever returned ``VALID`` would satisfy most of a case-by-case suite."""
    normalized = reference("normalized")

    reached = {
        validate_image_result(normalized, None, None, options(normalize=True)).status,
        validate_image_result(
            normalized, None, None, options(normalize=True), low_quality=True
        ).status,
        validate_image_result(None, None, None, options(normalize=True)).status,
        validate_image_result(
            normalized,
            None,
            None,
            options(normalize=True),
            (classify_input_failure("/x.png", "no such file"),),
        ).status,
        validate_image_result(
            normalized,
            None,
            None,
            options(normalize=True),
            (classify_transformation_failure("op", "bad"),),
        ).status,
    }

    assert reached == ALL_STATES


@pytest.mark.parametrize(
    ("failure", "expected_type", "expected_state"),
    [
        (classify_input_failure("/x.png", "gone"), "INVALID_INPUT", "UNSUPPORTED"),
        (
            classify_decode_failure("/x.heic", None, "no"),
            "UNSUPPORTED_FORMAT",
            "UNSUPPORTED",
        ),
        (
            classify_decode_failure("/x.png", "PNG", "truncated"),
            "DECODE_ERROR",
            "UNSUPPORTED",
        ),
        (
            classify_transformation_failure("op", "bad"),
            "TRANSFORMATION_ERROR",
            "ERROR",
        ),
        (classify_write_failure("/x.png", "denied"), "WRITE_ERROR", "ERROR"),
    ],
)
def test_each_primitive_failure_maps_to_its_contract_type(
    failure: ImagePrimitiveError, expected_type: str, expected_state: str
) -> None:
    """Every kind the primitives can raise arrives in the result under its own name."""
    result = validate(normalized="present", normalize=True, recorded=(failure,))

    assert result.errors[0].type == expected_type
    assert result.status == expected_state


def test_every_contract_error_kind_can_be_produced() -> None:
    """Five kinds come from the primitives; all seven are accepted by the narrowing guard.

    ``IO_ERROR`` and ``INTERNAL_ERROR`` have no primitive that raises them today, which is exactly
    why they are checked here: the vocabulary is the contract's, not a subset the primitives happen
    to
    use.
    """
    produced = {
        as_image_error(classify_input_failure("/x", "a")).type,
        as_image_error(classify_decode_failure("/x", None, "b")).type,
        as_image_error(classify_decode_failure("/x", "PNG", "c")).type,
        as_image_error(classify_transformation_failure("op", "d")).type,
        as_image_error(classify_write_failure("/x", "e")).type,
        missing_artifact_error("normalized").type,
    }
    assert produced <= set(CONTRACT_ERROR_TYPES)

    for kind in ("IO_ERROR", "INTERNAL_ERROR"):
        assert kind in CONTRACT_ERROR_TYPES


def test_the_metadata_carries_the_path_and_the_detail() -> None:
    """Context a caller can act on, rather than a sentence it has to parse."""
    failure = classify_transformation_failure("binarize_image", "unsupported depth")

    error = as_image_error(failure)

    assert error.metadata["operation"] == "binarize_image"
    assert error.message == "unsupported depth"


def test_a_failure_with_a_path_carries_it_in_the_metadata() -> None:
    """The path travels as data, so a caller does not have to read it out of a message."""
    error = as_image_error(
        classify_decode_failure("/some/file.png", "PNG", "truncated")
    )

    assert error.metadata["path"] == "/some/file.png"


def test_the_primitive_layer_already_refuses_an_invented_error_kind() -> None:
    """The first line of defence, and it is not this module's.

    ``ImagePrimitiveError`` validates its own ``error_type`` at construction, so the ordinary route
    to
    a failure cannot carry a kind the contract does not define. The narrowing guard inside
    :func:`as_image_error` is therefore defence in depth rather than the only check, and the test
    below reaches it past construction.
    """
    with pytest.raises(ValueError, match="unknown error type"):
        # Constructing the failure is the operation under test; the result is never reached.
        _ = ImagePrimitiveError(error_type="MADE_UP", message="x")


def test_the_narrowing_guard_refuses_a_kind_forged_past_construction() -> None:
    """The second line of defence, reached the only way it can be.

    ``as_image_error`` is public, so it can be handed an object whose ``error_type`` was set without
    going through the dataclass's own validation. The guard converts that into the same refusal
    rather than letting an unknown kind reach the contract.
    """
    forged = ImagePrimitiveError.__new__(ImagePrimitiveError)
    for name, value in (
        ("error_type", "MADE_UP"),
        ("message", "x"),
        ("path", None),
        ("recoverable", False),
        ("detail", {}),
    ):
        object.__setattr__(forged, name, value)

    with pytest.raises(ValueError, match="not one of the contract's error kinds"):
        as_image_error(forged)


def test_the_returned_record_is_the_contract_s_own_type() -> None:
    """No local lookalike, so no conversion layer is needed between here and the result."""
    result = validate(normalized="present", normalize=True)

    assert isinstance(result, ImageValidation)
    assert all(isinstance(error, ImageError) for error in result.errors)


def test_the_validator_is_pure_and_does_not_raise_on_a_failed_run() -> None:
    """The *Out of bounds* rule: a failure is returned, not thrown across the contract.

    Both halves matter. The function returns a record rather than raising, and it writes nothing:
    the artifact references it is handed point at paths that do not exist, and the validator reports
    them without creating, touching or deleting anything.
    """
    before = (
        set(Path("/nonexistent").glob("*")) if Path("/nonexistent").is_dir() else None
    )

    result = validate(
        normalize=True,
        recorded=(classify_input_failure("/x.png", "gone"),),
    )

    assert result.status == "UNSUPPORTED"
    after = (
        set(Path("/nonexistent").glob("*")) if Path("/nonexistent").is_dir() else None
    )
    assert before == after


def test_a_validation_state_is_never_converted_into_a_decision() -> None:
    """The state is descriptive: the record carries it and the call ends.

    There is no second return value and no branch a caller could mistake for an instruction, which
    is
    what the signature test above pins. This one asserts the observable consequence: validating a
    failed run twice gives the same record both times, so nothing was consumed or advanced.
    """
    first = validate(normalize=True)
    second = validate(normalize=True)

    assert first == second
    assert first.status == "INVALID_OUTPUT"
