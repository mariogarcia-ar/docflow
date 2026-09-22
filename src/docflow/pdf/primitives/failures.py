"""The bridge between engine failures and this processor's error vocabulary.

Owned by ``PDF-03`` (the first primitive that has real failure paths); the *state mapping*
and ``validate_pdf_result`` belong to ``PDF-11``. What lives here is deliberately narrow: a
typed error carrying the contract's own ``PDFErrorType``, so a primitive never has to hand
a caller a raw engine string and ``PDF-09``/``PDF-10`` never have to re-parse one.

Why a bridge at all: the engine reports failure three different ways, and only one of them
is a status code.

* A missing file exits 1 with ``I/O Error: Couldn't open file`` on **stderr** and an empty
  stdout.
* A truncated PDF exits 1 with ``Couldn't find trailer dictionary`` — the same status, a
  different cause, and *after* printing nothing to stdout.
* A page past the end of the document exits **99**.
* An encrypted PDF exits 1 with ``Incorrect password``.

So the status alone cannot distinguish corruption from encryption, and classifying by
matching the engine's English diagnostics would break on the next Poppler release. The
classification here therefore leans on facts about the document rather than about the
message: its presence, its ``%PDF-`` header, and the ``/Encrypt`` entry the PDF format
itself uses to mark encryption.
"""

from __future__ import annotations

from pathlib import Path

from docflow.pdf.contracts import PDFErrorType
from docflow.pdf.primitives.engine import PopplerError

PDF_HEADER = b"%PDF-"
"""Every PDF begins with this. Its absence is not a matter of interpretation."""

ENCRYPT_MARKER = b"/Encrypt"
"""The trailer entry the format uses to mark a document as encrypted.

Checked in the raw bytes, because the one moment this needs answering is the one moment the
engine refuses to parse the file.
"""

PAGE_OUT_OF_RANGE_STATUS = 99
"""The status Poppler's tools use for a page the document does not have."""

_RECOVERABLE: dict[str, bool] = {
    "MISSING_FILE": False,
    "ENCRYPTED_PDF": False,
    "CORRUPTED_PDF": False,
    "UNSUPPORTED_PDF": False,
    "PAGE_OUT_OF_RANGE": False,
    "IO_ERROR": True,
}
"""Whether a run can continue without the artifact that failed.

A document-level failure stops the document. ``IO_ERROR`` is the one entry marked
recoverable: it describes a write that failed at a path the caller controls, so a retry or
a different output root is a real option rather than a hope.
"""


class PDFPrimitiveError(PopplerError):
    """A primitive failure classified into the contract's own error vocabulary.

    Raised instead of a raw :class:`~docflow.pdf.primitives.engine.PopplerError` so the
    cause survives into ``PDFResult.errors`` without the caller re-reading engine text.

    Attributes:
        error_type: One of the ``PDFErrorType`` literals.
        page_number: Page the failure belongs to, or ``None`` for the document.
        recoverable: Whether the run can continue without this artifact.
        detail: The engine's own message, kept verbatim for diagnosis.
    """

    def __init__(
        self,
        error_type: PDFErrorType,
        message: str,
        *,
        page_number: int | None = None,
        recoverable: bool | None = None,
        detail: str = "",
    ) -> None:
        self.error_type = error_type
        self.page_number = page_number
        self.recoverable = (
            _RECOVERABLE[error_type] if recoverable is None else recoverable
        )
        self.detail = detail
        super().__init__(message)


def looks_like_a_pdf(pdf_path: Path) -> bool:
    """Report whether a file starts with the PDF header.

    Args:
        pdf_path: File to check.

    Returns:
        ``True`` when the first bytes are ``%PDF-``.
    """
    with pdf_path.open("rb") as handle:
        return handle.read(len(PDF_HEADER)) == PDF_HEADER


def declares_encryption(pdf_path: Path) -> bool:
    """Report whether a document's bytes carry the ``/Encrypt`` trailer entry.

    Args:
        pdf_path: File to check.

    Returns:
        ``True`` when the marker is present. Combined with a failed engine call this is a
        reliable signal; on its own it is a hint, so callers pair the two rather than
        trusting either alone.
    """
    return ENCRYPT_MARKER in pdf_path.read_bytes()


def check_pdf_is_readable(pdf_path: Path) -> None:
    """Fail fast, with a typed cause, when a document cannot be read at all.

    Called before the engine so the three failures that make parsing pointless are named
    without depending on the engine's diagnostics.

    Args:
        pdf_path: PDF to inspect.

    Raises:
        PDFPrimitiveError: The file is absent, does not begin with ``%PDF-``, or declares
            itself encrypted. Password handling is deferred, so an encrypted document is
            reported rather than guessed at.
    """
    if not pdf_path.exists():
        raise PDFPrimitiveError(
            "MISSING_FILE", f"no file at {pdf_path}", detail=str(pdf_path)
        )

    if not pdf_path.is_file():
        raise PDFPrimitiveError(
            "MISSING_FILE", f"{pdf_path} is not a regular file", detail=str(pdf_path)
        )

    if not looks_like_a_pdf(pdf_path):
        raise PDFPrimitiveError(
            "CORRUPTED_PDF",
            f"{pdf_path} does not begin with the PDF header",
            detail=str(pdf_path),
        )

    # Only consulted after the header check, and only reported as encryption when the file
    # also claims to be a PDF. A text layer that happens to contain the marker is then not
    # mistaken for an encrypted document.
    if declares_encryption(pdf_path):
        raise PDFPrimitiveError(
            "ENCRYPTED_PDF",
            f"{pdf_path} is encrypted; passwords are not handled yet",
            detail=str(pdf_path),
        )


def classify_engine_failure(
    pdf_path: Path,
    failure: PopplerError,
    *,
    page_number: int | None = None,
) -> PDFPrimitiveError:
    """Turn an engine failure into a typed one.

    Args:
        pdf_path: The document that was being read.
        failure: What the engine raised.
        page_number: Page being requested, when the call was page-scoped.

    Returns:
        A :class:`PDFPrimitiveError` carrying the closest honest classification. A failure
        that cannot be attributed is reported as ``CORRUPTED_PDF`` rather than as
        ``INTERNAL_ERROR``: the engine only reached here because the file failed to parse,
        and naming the actual symptom is more useful than naming our own uncertainty.
    """
    status = getattr(failure, "returncode", None)
    if status == PAGE_OUT_OF_RANGE_STATUS and page_number is not None:
        return PDFPrimitiveError(
            "PAGE_OUT_OF_RANGE",
            f"page {page_number} does not exist in {pdf_path}",
            page_number=page_number,
            detail=str(failure),
        )

    return PDFPrimitiveError(
        "CORRUPTED_PDF",
        f"{pdf_path} could not be parsed",
        page_number=page_number,
        detail=str(failure),
    )


__all__ = [
    "ENCRYPT_MARKER",
    "PAGE_OUT_OF_RANGE_STATUS",
    "PDF_HEADER",
    "PDFPrimitiveError",
    "check_pdf_is_readable",
    "classify_engine_failure",
    "declares_encryption",
    "looks_like_a_pdf",
]
