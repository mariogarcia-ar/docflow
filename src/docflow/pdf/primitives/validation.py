"""Fail-fast validation of the input, and structural validation of what was produced.

Two jobs, one rule: nothing is guessed.

* :func:`validate_pdf` runs **before any engine call**, so a missing, unsupported,
  encrypted or corrupted document is reported as a typed failure instead of being handed to
  an engine that would answer about something else. Its failure kinds are
  ``INVALID_INPUT``, ``UNSUPPORTED_PDF``, ``ENCRYPTED_PDF`` and ``CORRUPTED_PDF``.
* :func:`validate_pdf_page_result` and :func:`validate_pdf_result` check what exists on
  disk against what the result declares, so an artifact the result claims to have
  published but did not is an ``INVALID`` finding rather than a silent absence.

Validation never decides what happens next: it reports a state, and the orchestrator owns
every consequence of it.
"""

from __future__ import annotations

from pathlib import Path

from docflow.pdf.contracts import (
    PDFError,
    PDFPageResult,
    PDFPageValidation,
    PDFPageValidationState,
    PDFResult,
    PDFValidation,
    PDFValidationState,
)
from docflow.pdf.primitives.errors import typed_failure

#: Prefix every readable PDF starts with.
SUPPORTED_PDF_MAGIC = b"%PDF-"

#: Header versions this processor claims to read. Anything else is reported as
#: unsupported rather than handed to an engine that might guess.
SUPPORTED_PDF_HEADER_VERSIONS = (b"%PDF-1.", b"%PDF-2.")

#: The marker a complete PDF ends with; the engine's own readers require it too.
PDF_EOF_MARKER = b"%%EOF"

#: The trailer key an encrypted document declares.
PDF_ENCRYPTION_MARKER = b"/Encrypt"

#: How much of the file is read to decide. Both slices are bounded so the check stays
#: cheap on a large document: the header and the trailer, never the whole file.
HEADER_BYTES = 1024
TRAILER_BYTES = 2048

#: The validation state a single failing stage maps to. A stage that has a state of its own
#: reports it; the rest are partial, because the page kept every artifact that did succeed.
STAGE_VALIDATION_STATES: dict[str, PDFPageValidationState] = {
    "PAGE_EXTRACTION_ERROR": "PARTIAL",
    "RENDER_ERROR": "RENDER_ERROR",
    "TEXT_EXTRACTION_ERROR": "TEXT_EXTRACTION_ERROR",
    "IMAGE_EXTRACTION_ERROR": "IMAGE_EXTRACTION_ERROR",
}


def validate_pdf(pdf_path: Path) -> None:
    """Fail fast when ``pdf_path`` cannot be read as a PDF, before any engine call.

    Args:
        pdf_path: The candidate document.

    Raises:
        PDFPrimitiveError: With ``INVALID_INPUT`` when there is no readable file,
            ``UNSUPPORTED_PDF`` when it is not a PDF version this processor reads,
            ``CORRUPTED_PDF`` when the header or the trailer is missing or truncated, or
            ``ENCRYPTED_PDF`` when the trailer declares encryption. None of them is
            recoverable: the input is the problem, not one artifact of it.
    """
    if not pdf_path.is_file():
        raise typed_failure(
            "INVALID_INPUT",
            f"{pdf_path} is not a readable file",
            recoverable=False,
            metadata={"pdf_path": str(pdf_path)},
        )

    if pdf_path.suffix.lower() != ".pdf":
        raise typed_failure(
            "UNSUPPORTED_PDF",
            f"{pdf_path} does not have a .pdf extension",
            recoverable=False,
            metadata={"pdf_path": str(pdf_path), "suffix": pdf_path.suffix},
        )

    size = pdf_path.stat().st_size
    if size == 0:
        raise typed_failure(
            "CORRUPTED_PDF",
            f"{pdf_path} is empty",
            recoverable=False,
            metadata={"pdf_path": str(pdf_path), "size": 0},
        )

    try:
        with pdf_path.open("rb") as handle:
            header = handle.read(HEADER_BYTES)
            handle.seek(max(0, size - TRAILER_BYTES))
            trailer = handle.read(TRAILER_BYTES)
    except OSError as exc:
        raise typed_failure(
            "INVALID_INPUT",
            f"{pdf_path} could not be read: {exc}",
            recoverable=False,
            metadata={"pdf_path": str(pdf_path)},
        ) from exc

    if not header.startswith(SUPPORTED_PDF_MAGIC):
        raise typed_failure(
            "CORRUPTED_PDF",
            f"{pdf_path} does not start with a PDF header",
            recoverable=False,
            metadata={"pdf_path": str(pdf_path)},
        )

    if not header.startswith(SUPPORTED_PDF_HEADER_VERSIONS):
        raise typed_failure(
            "UNSUPPORTED_PDF",
            f"{pdf_path} declares a PDF version this processor does not read",
            recoverable=False,
            metadata={
                "pdf_path": str(pdf_path),
                "header": header[:8].decode("latin-1"),
            },
        )

    if PDF_EOF_MARKER not in trailer:
        raise typed_failure(
            "CORRUPTED_PDF",
            f"{pdf_path} is truncated: it has no end-of-file marker",
            recoverable=False,
            metadata={"pdf_path": str(pdf_path), "size": size},
        )

    # TODO: [MVP] the checks above are the header, the trailer and the encryption marker of
    # the last few kilobytes, not a real structural parse: a document that is internally
    # broken but well-bracketed is reported by the engine instead.

    if PDF_ENCRYPTION_MARKER in trailer:
        # TODO: [MVP] real password handling (`pdfinfo`/`pdftotext` take -upw/-opw):
        # today an encrypted document is reported, never opened with a guess.
        raise typed_failure(
            "ENCRYPTED_PDF",
            f"{pdf_path} is encrypted",
            recoverable=False,
            metadata={"pdf_path": str(pdf_path)},
        )


def _declared_page_artifacts(page_result: PDFPageResult) -> list[Path]:
    """Return every file the page result says it published, each one once.

    The three named paths and the ``artifacts`` list overlap by design — the named fields
    are convenient handles on files the list also carries — so the union is taken without
    counting a file twice.
    """
    declared = [
        path
        for path in (
            page_result.page_pdf,
            page_result.page_image,
            page_result.native_text,
        )
        if path is not None
    ]
    declared.extend(page_result.artifacts)
    return list(dict.fromkeys(declared))


def _page_state(
    page_result: PDFPageResult,
    errors: list[PDFError],
    missing: list[Path],
) -> PDFPageValidationState:
    """Return the page's validation state from its outcome and what exists on disk."""
    if page_result.status == "failed":
        return "ERROR"
    if missing:
        return "INVALID"
    if not errors:
        return "VALID"
    kinds = {error.type for error in errors}
    if len(kinds) == 1:
        return STAGE_VALIDATION_STATES.get(next(iter(kinds)), "PARTIAL")
    return "PARTIAL"


def validate_pdf_page_result(page_result: PDFPageResult) -> PDFPageValidation:
    """Validate one page against the artifacts it declares.

    The page result is validated *after* processing: ``validation.errors`` already carries
    the failures the stages recorded, and this call adds what the file system says about
    the artifacts the result claims to have published.

    Args:
        page_result: The page result to check.

    Returns:
        The validation record to store on the result. A declared artifact that is absent is
        reported as an ``IO_ERROR`` on the page and makes the state ``INVALID``.
    """
    errors = list(page_result.validation.errors)
    missing = [
        path for path in _declared_page_artifacts(page_result) if not path.is_file()
    ]

    for path in missing:
        errors.append(
            PDFError(
                type="IO_ERROR",
                page_number=page_result.page_number,
                message=f"{path} is declared by the result but missing on disk",
                recoverable=True,
                metadata={"path": str(path)},
            )
        )

    return PDFPageValidation(
        status=_page_state(page_result, errors, missing),
        errors=errors,
        missing_artifacts=missing,
    )


def _document_state(result: PDFResult, missing: list[Path]) -> PDFValidationState:
    """Return the document's validation state from its outcome and its pages."""
    if result.status == "failed":
        return "ERROR"
    if missing:
        return "INVALID"
    if result.metadata.page_count != len(result.pages):
        return "INVALID"
    page_states = {page.validation.status for page in result.pages}
    if page_states & {"ERROR", "INVALID"}:
        return "INVALID"
    if page_states - {"VALID"}:
        return "PARTIAL"
    return "VALID"


def validate_pdf_result(result: PDFResult) -> PDFValidation:
    """Validate a document result against the artifacts it declares and its own pages.

    Args:
        result: The document result to check.

    Returns:
        The validation record to store on the result. A declared artifact that is absent,
        or a page count that disagrees with the number of page results, is reported as a
        typed error and makes the state ``INVALID``.
    """
    errors = list(result.errors)
    missing = [path for path in result.artifacts if not path.is_file()]

    for path in missing:
        errors.append(
            PDFError(
                type="IO_ERROR",
                page_number=None,
                message=f"{path} is declared by the result but missing on disk",
                recoverable=False,
                metadata={"path": str(path)},
            )
        )

    if result.metadata.page_count != len(result.pages):
        errors.append(
            PDFError(
                type="INTERNAL_ERROR",
                page_number=None,
                message="the reported page count and the number of page results disagree",
                recoverable=False,
                metadata={
                    "page_count": result.metadata.page_count,
                    "page_results": len(result.pages),
                },
            )
        )

    return PDFValidation(
        status=_document_state(result, missing),
        errors=errors,
        missing_artifacts=missing,
    )
