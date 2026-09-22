"""The bridge from engine failures to the contract's error vocabulary.

The primitives report failures as :class:`ImagePrimitiveError`; the processor turns those into
the contract's :class:`docflow.image.ImageError`. Keeping the two apart is what stops a
primitive from having to know the contract's shape, and stops the contract from having to know
which engine failed.

The vocabulary of ``error_type`` is the contract's literal set, imported as a bare tuple of
strings rather than the ``Literal`` itself: the values must match, and a test asserts they do.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# pylint: disable=duplicate-code
# Deliberately the same seven values as `docflow.image.contracts.ImageErrorType`, spelled out
# rather than imported from it: the primitive layer reports failures without depending on the
# processor's contract shape, so the primitives stay testable on their own and the contract can
# change its record types without reaching down here. The duplication is not left to trust -
# `test_the_primitive_vocabulary_matches_the_contract_exactly` fails if the two ever diverge.

PRIMITIVE_ERROR_TYPES: tuple[str, ...] = (
    "INVALID_INPUT",
    "UNSUPPORTED_FORMAT",
    "DECODE_ERROR",
    "TRANSFORMATION_ERROR",
    "WRITE_ERROR",
    "IO_ERROR",
    "INTERNAL_ERROR",
)
"""The error kinds a primitive may report - the contract's set, mirrored in order."""

_RECOVERABLE: frozenset[str] = frozenset({"LOW_QUALITY", "INVALID_OUTPUT"})
"""Kinds the processor may retry or route around.

Informational only for the primitive layer: it records whether a failure is worth retrying,
and leaves the decision to the processor.
"""


@dataclass(frozen=True)
class ImagePrimitiveError(Exception):
    """A failure inside the image primitives, typed by the contract's vocabulary.

    Attributes:
        error_type: One of :data:`PRIMITIVE_ERROR_TYPES`.
        message: What went wrong, in the primitive's own words.
        path: The file involved, when the failure concerns one.
        recoverable: Whether the failure is worth retrying.
        detail: Extra context for diagnosis, kept free-form.
    """

    error_type: str
    message: str
    path: str | None = None
    recoverable: bool = field(default=False)
    detail: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.error_type not in PRIMITIVE_ERROR_TYPES:
            raise ValueError(
                f"unknown error type {self.error_type!r}; "
                f"expected one of {PRIMITIVE_ERROR_TYPES}"
            )

    def __str__(self) -> str:
        where = f" ({self.path})" if self.path else ""
        return f"{self.error_type}: {self.message}{where}"


def classify_input_failure(path: str, reason: str) -> ImagePrimitiveError:
    """Report a file that cannot be read at all.

    Args:
        path: The file that failed.
        reason: Why it could not be read.

    Returns:
        The typed failure.
    """
    return ImagePrimitiveError(
        error_type="INVALID_INPUT", message=reason, path=path, recoverable=False
    )


def classify_decode_failure(
    path: str, format_name: str | None, reason: str
) -> ImagePrimitiveError:
    """Report a file that is readable but not decodable.

    Separates the two cases the contract cares about: a format the engine does not handle is
    ``UNSUPPORTED_FORMAT`` and is not retryable, while a damaged file of a known format is
    ``DECODE_ERROR``.

    Args:
        path: The file that failed.
        format_name: The format the file declares, when it could be read.
        reason: Why decoding failed.

    Returns:
        The typed failure.
    """
    if format_name is None:
        return ImagePrimitiveError(
            error_type="UNSUPPORTED_FORMAT", message=reason, path=path
        )
    return ImagePrimitiveError(
        error_type="DECODE_ERROR",
        message=reason,
        path=path,
        detail={"format": format_name},
    )


def classify_write_failure(path: str, reason: str) -> ImagePrimitiveError:
    """Report a destination that could not be written.

    Args:
        path: The destination that failed.
        reason: Why the write failed.

    Returns:
        The typed failure.
    """
    return ImagePrimitiveError(
        error_type="WRITE_ERROR", message=reason, path=path, recoverable=False
    )


def classify_transformation_failure(operation: str, reason: str) -> ImagePrimitiveError:
    """Report a transformation that could not be applied.

    Args:
        operation: The transformation that failed.
        reason: Why it failed.

    Returns:
        The typed failure.
    """
    return ImagePrimitiveError(
        error_type="TRANSFORMATION_ERROR",
        message=reason,
        recoverable=True,
        detail={"operation": operation},
    )


__all__ = [
    "PRIMITIVE_ERROR_TYPES",
    "ImagePrimitiveError",
    "classify_decode_failure",
    "classify_input_failure",
    "classify_transformation_failure",
    "classify_write_failure",
]
