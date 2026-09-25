"""The typed failure a primitive raises, and the only exception this processor throws.

A result is the contract, so a failure is data: a primitive describes what went wrong with
a :class:`~docflow.pdf.contracts.PDFError` and raises :class:`PDFPrimitiveError` carrying
it. The entry points catch that one type and record the error in the result, so no
exception ever escapes ``process_pdf`` / ``process_pdf_page``.

The class lives beside the seam rather than in ``docflow.pdf.contracts`` because the
contract module is vocabulary only: the exception is how the seam reports, not what the
processor promises.
"""

from __future__ import annotations

from dataclasses import replace

from docflow.pdf.contracts import PDFError, PDFErrorType


class PDFPrimitiveError(Exception):
    """A typed failure from a primitive, ready to be recorded in a result.

    Attributes:
        error: The typed failure. It carries the failure kind, the page it belongs to
            (``None`` at document level) and whether the run can continue without the
            artifact that failed.
    """

    def __init__(self, error: PDFError) -> None:
        super().__init__(error.message)
        self.error = error


def typed_failure(
    failure_type: PDFErrorType,
    message: str,
    *,
    page_number: int | None = None,
    recoverable: bool = True,
    metadata: dict[str, object] | None = None,
) -> PDFPrimitiveError:
    """Build a typed failure with its diagnostic context.

    Args:
        failure_type: One of the documented failure kinds.
        message: Human-readable description; never a substitute for the typed kind.
        page_number: Page the failure belongs to, or ``None`` for the document.
        recoverable: Whether the run can continue without the artifact that failed.
        metadata: Diagnostic context, e.g. the engine's exit code and stderr.

    Returns:
        The failure, ready to raise or to record.
    """
    return PDFPrimitiveError(
        PDFError(
            type=failure_type,
            page_number=page_number,
            message=message,
            recoverable=recoverable,
            metadata=dict(metadata or {}),
        )
    )


def for_page(error: PDFError, page_number: int) -> PDFError:
    """Return ``error`` attributed to ``page_number``.

    A primitive knows the page it was called for only when the caller names it, so the
    entry point stamps the page it was processing onto whatever surfaced. Attribution is
    added here rather than guessed inside the primitives.

    Args:
        error: The failure as a primitive reported it.
        page_number: Page the caller was processing, 1-based.

    Returns:
        The same failure with ``page_number`` set.
    """
    return replace(error, page_number=page_number)
