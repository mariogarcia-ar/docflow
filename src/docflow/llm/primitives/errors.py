# pylint: disable=duplicate-code
# Reason: this module is a deliberate sibling of ``docflow.ocr.primitives.errors`` (and of the
# ``pdf`` and ``image`` twins). A processor may not import another processor's internals
# (`README.md` §7), so the same small rule — a typed failure is data, and a primitive raises it
# rather than returning it — is written once per processor on purpose.
"""The typed failure a primitive raises, and the retryability of every failure kind.

A result is the contract, so a failure is data: a primitive describes what went wrong with an
:class:`~docflow.llm.contracts.LLMError` and raises :class:`LLMPrimitiveError` carrying it. The
entry points catch that one type and record the error in the attempt, the node or the run, so no
exception ever escapes :func:`docflow.llm.process_llm_request`.

The class lives beside the seam rather than in :mod:`docflow.llm.contracts` because the contract
module is vocabulary only: the exception is how the seam reports, not what the processor promises.

:data:`RETRYABLE_KINDS` is the second half of the same decision — "each is marked ``RETRYABLE`` or
``NON_RETRYABLE``" (subplan §3). It is a closed set, and a kind absent from it is not retryable:
an unclassified failure never buys another attempt.
"""

from __future__ import annotations

from typing import Any, Final

from docflow.llm.contracts import LLMError, LLMErrorType


class LLMPrimitiveError(Exception):
    """A typed failure from a primitive, ready to be recorded in a result.

    Attributes:
        error: The typed failure, carrying its kind, a human-readable message, whether the run
            can continue without what failed, and diagnostic context.
    """

    def __init__(self, error: LLMError) -> None:
        super().__init__(error.message)
        self.error = error


#: The kinds a further attempt may fix: the provider was unreachable or late, or it answered
#: something the processor could not use and might answer differently on a second call.
RETRYABLE_KINDS: Final[frozenset[LLMErrorType]] = frozenset(
    {
        "PROVIDER_ERROR",
        "TIMEOUT",
        "INVALID_RESPONSE",
        "INVALID_JSON",
        "SCHEMA_ERROR",
    }
)

#: The kinds that do not buy a retry, and why — recorded so the table reads as a decision rather
#: than as a gap:
#: ``MODEL_UNAVAILABLE`` — the model is not there; asking again immediately changes nothing.
#: ``CONTEXT_OVERFLOW`` — the prompt is too long; the same prompt will be too long again.
#: ``DEPENDENCY_ERROR`` — a declared input (template, schema, image, graph) does not resolve.
#: ``INTERNAL_ERROR`` — a defect of this processor, not of the provider.
NON_RETRYABLE_KINDS: Final[frozenset[LLMErrorType]] = frozenset(
    {
        "MODEL_UNAVAILABLE",
        "CONTEXT_OVERFLOW",
        "DEPENDENCY_ERROR",
        "INTERNAL_ERROR",
    }
)


def typed_failure(
    failure_type: LLMErrorType,
    message: str,
    *,
    recoverable: bool = True,
    metadata: dict[str, Any] | None = None,
) -> LLMPrimitiveError:
    """Build a typed failure with its diagnostic context.

    Args:
        failure_type: One of the nine documented failure kinds.
        message: Human-readable description; never a substitute for the typed kind.
        recoverable: Whether the run can continue without what failed.
        metadata: Diagnostic context, e.g. the provider's own message.

    Returns:
        The failure, ready to raise or to record.
    """
    return LLMPrimitiveError(
        LLMError(
            type=failure_type,
            message=message,
            recoverable=recoverable,
            metadata=dict(metadata or {}),
        )
    )


def is_retryable(error: LLMError) -> bool:
    """Return whether another attempt may fix ``error``.

    Args:
        error: The failure that ended an attempt.

    Returns:
        ``True`` only for a kind in :data:`RETRYABLE_KINDS`. An unclassified kind is never
        retried: an unknown failure has not earned a second paid call.
    """
    return error.type in RETRYABLE_KINDS
