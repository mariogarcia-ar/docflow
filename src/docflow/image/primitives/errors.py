"""The typed failure a primitive raises, and the only exception this processor throws.

A result is the contract, so a failure is data: a primitive describes what went wrong with a
:class:`~docflow.image.contracts.ImageError` and raises :class:`ImagePrimitiveError` carrying
it. The entry points catch that one type and record the error in the result, so no exception
ever escapes ``process_image`` / ``process_image_from_page``.

The class lives beside the seam rather than in :mod:`docflow.image.contracts` because the
contract module is vocabulary only: the exception is how the seam reports, not what the
processor promises.
"""

from __future__ import annotations

from typing import Any

from docflow.image.contracts import ImageError, ImageErrorType


class ImagePrimitiveError(Exception):
    """A typed failure from a primitive, ready to be recorded in a result.

    Attributes:
        error: The typed failure. It carries the failure kind, a human-readable message,
            whether the run can continue without the artifact that failed, and diagnostic
            context.
    """

    def __init__(self, error: ImageError) -> None:
        super().__init__(error.message)
        self.error = error


def typed_failure(
    failure_type: ImageErrorType,
    message: str,
    *,
    recoverable: bool = True,
    metadata: dict[str, Any] | None = None,
) -> ImagePrimitiveError:
    """Build a typed failure with its diagnostic context.

    Args:
        failure_type: One of the documented failure kinds.
        message: Human-readable description; never a substitute for the typed kind.
        recoverable: Whether the run can continue without the artifact that failed.
        metadata: Diagnostic context, e.g. the engine's own message.

    Returns:
        The failure, ready to raise or to record.
    """
    return ImagePrimitiveError(
        ImageError(
            type=failure_type,
            message=message,
            recoverable=recoverable,
            metadata=dict(metadata or {}),
        )
    )
