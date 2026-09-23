"""Structural validation of a result, and the translation of failures into the contract.

"Structural" is the whole point, and ``docs/plan/README.md`` §7 says why: a silent failure - a
truncated write, a plausible wrong value - is reported as correct unless something checks. So the
check here is not "did the run finish" but **"does every artifact this result claims to have
published actually exist, and is every field it promises populated"**.

Two rules from the plan shape everything below:

* **Validation states are descriptive only.** ``VALID``, ``LOW_QUALITY``, ``INVALID_OUTPUT``,
  ``UNSUPPORTED`` and ``ERROR`` describe what was found; none of them becomes a routing decision or
  a
  workflow action. The options are read for exactly one purpose - telling "not requested" from
  "requested and missing" - and never to decide what a state means.
* **Errors are returned, not thrown.** A failure that crosses the contract as a raised exception is
a
  failure the caller cannot inspect, so every path here converts an
  :class:`~docflow.image.primitives.failures.ImagePrimitiveError` into the contract's
  :class:`~docflow.image.contracts.ImageError` and hands it back inside the result.

The artifacts arrive as **named parameters rather than a dictionary keyed by capability name**. A
mapping would have been shorter to write and would have made a typo in a key indistinguishable from
"not published" - the exact failure this module exists to catch, reintroduced at its own boundary. A
test asserts the signature names each artifact, so adding one to the result cannot be done without
deciding how it is validated.
"""

from __future__ import annotations

import typing
from pathlib import Path
from typing import Final

from docflow.image.contracts import (
    ArtifactRef,
    ImageError,
    ImageErrorType,
    ImageOptions,
    ImageValidation,
)
from docflow.image.primitives.failures import ImagePrimitiveError

VALID = "VALID"
LOW_QUALITY = "LOW_QUALITY"
INVALID_OUTPUT = "INVALID_OUTPUT"
UNSUPPORTED = "UNSUPPORTED"
ERROR = "ERROR"
"""The descriptive states, bound to names for readability.

A caller annotating its own code should reference the contract's ``ImageValidationState``; these
exist because a bare ``"VALID"`` in the middle of a comparison is unreadable. A test asserts each
one
is a real literal of that type, so a typo cannot quietly become a sixth state.
"""

ARTIFACT_CAPABILITIES: Final[tuple[tuple[str, str], ...]] = (
    ("normalize", "normalized"),
    ("prepare_for_ocr", "ocr_ready"),
    ("prepare_for_vlm", "vlm_ready"),
)
"""Each capability's request option and the result field its artifact lands in.

One table rather than parallel lists, following the reasoning the PDF processor's validator records:
deriving the missing artifacts and the unsatisfied capabilities separately and pairing them
afterwards
mispairs them the moment the two lists differ in length, which happens as soon as a capability was
not
requested. The table makes the pairing explicit and impossible to get wrong.
"""

_MISSING_ARTIFACT_ERROR_TYPE = "WRITE_ERROR"
"""The failure kind a missing artifact reports.

An artifact a caller asked for and did not get is a write that did not happen or a file that was not
kept, which is what ``WRITE_ERROR`` names. ``IO_ERROR`` would be the honest kind if the cause were
known to be a read failure, and this module deliberately does not claim that: it knows only that the
reference is absent.
"""

_UNREADABLE_INPUT_ERROR_TYPES: Final[frozenset[str]] = frozenset(
    {"INVALID_INPUT", "UNSUPPORTED_FORMAT", "DECODE_ERROR"}
)
"""The failure kinds that mean the run could not read its input at all.

Such a run is ``UNSUPPORTED`` rather than ``ERROR``: the difference is that nothing about the
processor failed, the file simply is not something it can process.
"""

CONTRACT_ERROR_TYPES: Final[tuple[str, ...]] = typing.get_args(ImageErrorType)
"""The contract's error kinds, **derived from the contract** rather than restated.

The primitive layer spells the same seven names out on purpose, because it must not depend on the
contract's shape; a test compares the two lists to hold that duplication honest. This module is the
opposite case - it already imports the contract's records, so a second copy would be pure
duplication with nothing to catch a divergence. Reading the literal through ``typing.get_args``
gives the runtime iterable this validator needs, from the one source of truth.
"""

ARTIFACT_FIELDS: Final[tuple[str, ...]] = tuple(
    field for _, field in ARTIFACT_CAPABILITIES
)
"""Every artifact field the validator knows about, in the table's order."""


def validate_image_result(
    normalized: ArtifactRef | None,
    ocr_ready: ArtifactRef | None,
    vlm_ready: ArtifactRef | None,
    options: ImageOptions,
    recorded_errors: tuple[ImagePrimitiveError, ...] = (),
    *,
    low_quality: bool = False,
) -> ImageValidation:
    """Check a result against what it claims, and classify what went wrong.

    The order of the tests is what makes the answer deterministic, and it is chosen so the most
    serious finding wins:

    1. **An unrecoverable failure recorded by the run is** ``ERROR``, or ``UNSUPPORTED`` when the
       failure was that the input could not be read. A run that failed is not "valid with a note",
       and the artifacts that survived it do not change that.
    2. **A requested artifact that is absent is** ``INVALID_OUTPUT``, with a typed error naming it.
       The most concrete kind of silent failure: the result points at a file that is not there.
    3. **A recoverable failure leaves the state** ``ERROR`` as well, since the run had trouble even
       though it published everything it promised.
    4. **A page the measurements called unusable is** ``LOW_QUALITY`` - describing the input rather
       than the run, since every artifact is present.
    5. Anything else is ``VALID``.

    Args:
        normalized: The baseline artifact, or ``None``.
        ocr_ready: The OCR variant, or ``None``.
        vlm_ready: The VLM variant, or ``None``.
        options: What the run was asked for. Read only to tell "not requested" from "requested and
            missing", never to decide what a state means.
        recorded_errors: Failures the run already classified, in the order they happened.
        low_quality: Whether the image's own measurements failed the legibility thresholds, as
            ``classify_image`` reports. A description of the input, not of this run.

    Returns:
        The validation record: a state, the typed errors justifying it, and the artifacts that were
        expected and not found.
    """
    published = {
        "normalized": normalized,
        "ocr_ready": ocr_ready,
        "vlm_ready": vlm_ready,
    }
    errors = [as_image_error(failure) for failure in recorded_errors]

    # Computed before the state is decided, and reported in every branch that has any. Which
    # artifacts a result promised and did not deliver is a fact independent of why the run failed,
    # and the contract carries a field for it: discarding the list because the state is ERROR would
    # throw away the one piece of information a caller needs in order to act.
    missing = [
        field
        for capability, field in ARTIFACT_CAPABILITIES
        if _requested(options, capability) and published.get(field) is None
    ]
    absent = [Path(name) for name in missing]

    if any(not error.recoverable for error in errors):
        return _validation(_state_for(errors), errors, absent)

    if missing:
        errors.extend(missing_artifact_error(field) for field in missing)
        return _validation(INVALID_OUTPUT, errors, absent)

    if errors:
        return _validation(_state_for(errors), errors, absent)

    if low_quality:
        return _validation(LOW_QUALITY, errors, absent)

    return _validation(VALID, errors, absent)


def as_image_error(failure: ImagePrimitiveError) -> ImageError:
    """Translate a primitive failure into the contract's error record.

    Args:
        failure: The failure to translate.

    Returns:
        The contract's record, carrying the primitive's own words and context. The path travels in
        the metadata rather than a message, so a caller can act on it rather than parse it.
    """
    metadata: dict[str, object] = dict(failure.detail)
    if failure.path is not None:
        metadata["path"] = failure.path
    return ImageError(
        type=_as_error_type(failure.error_type),
        message=failure.message,
        recoverable=failure.recoverable,
        metadata=metadata,
    )


def missing_artifact_error(field: str) -> ImageError:
    """Build the typed error for an artifact that was requested and not found.

    Public because this is the scenario the WBS states as an acceptance criterion, so a caller
    assembling a result by hand has to be able to produce exactly the record this module would.

    Args:
        field: The artifact field that is missing, as named in :data:`ARTIFACT_CAPABILITIES`.

    Returns:
        The typed error, always ``recoverable=False``: an artifact that was asked for and not
        delivered is not something a run continues past.
    """
    return ImageError(
        type=_as_error_type(_MISSING_ARTIFACT_ERROR_TYPE),
        message=f"the run promised {field!r} and published nothing for it",
        recoverable=False,
        metadata={"artifact": field},
    )


def _validation(
    status: str, errors: list[ImageError], missing: list[Path]
) -> ImageValidation:
    """Assemble the validation record.

    Args:
        status: One of the descriptive states.
        errors: The typed errors found.
        missing: The artifacts expected and not found.

    Returns:
        The record.
    """
    # Every caller passes one of the five names bound above, and a test asserts each is a literal of
    # the contract's type, so the narrowing cannot be wrong.
    return ImageValidation(
        status=status,  # type: ignore[arg-type]
        errors=errors,
        missing_artifacts=missing,
    )


def _requested(options: ImageOptions, capability: str) -> bool:
    """Report whether a capability was asked for.

    Args:
        options: The request.
        capability: The capability's option name.

    Returns:
        ``True`` when it was requested.
    """
    return bool(getattr(options, capability))


def _state_for(errors: list[ImageError]) -> str:
    """Return the state a set of recorded failures justifies.

    Args:
        errors: The typed errors the run recorded.

    Returns:
        ``UNSUPPORTED`` when the run could not read its input at all, ``ERROR`` otherwise.
    """
    if any(error.type in _UNREADABLE_INPUT_ERROR_TYPES for error in errors):
        return UNSUPPORTED
    return ERROR


def _as_error_type(name: str) -> ImageErrorType:
    """Narrow a primitive error name to the contract's literal.

    Args:
        name: One of the primitive error kinds.

    Returns:
        The same name as the contract's type.

    Raises:
        ValueError: The name is not one the contract knows. Not reachable from the primitives, whose
            own vocabulary is checked when a failure is constructed, but reachable from a caller
            passing a string it made up.
    """
    if name not in CONTRACT_ERROR_TYPES:
        raise ValueError(
            f"{name!r} is not one of the contract's error kinds; "
            f"expected one of {list(CONTRACT_ERROR_TYPES)}"
        )
    return name  # type: ignore[return-value]


__all__ = [
    "ARTIFACT_CAPABILITIES",
    "ARTIFACT_FIELDS",
    "CONTRACT_ERROR_TYPES",
    "ERROR",
    "INVALID_OUTPUT",
    "LOW_QUALITY",
    "UNSUPPORTED",
    "VALID",
    "as_image_error",
    "missing_artifact_error",
    "validate_image_result",
]
