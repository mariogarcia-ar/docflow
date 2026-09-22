"""Document primitives — what a PDF reports about itself, before any extraction.

Owned by ``PDF-03``. These functions read the document's own properties: its metadata, its
page count and each page's size. They extract nothing, render nothing and classify nothing.

Engine access goes through :mod:`docflow.pdf.primitives.engine` rather than a direct
``subprocess`` invocation, so the engine stays swappable inside this package.

Five facts about the engine shape this module, each verified against Poppler 25.02.0 rather
than assumed:

* ``pdfinfo`` reports page sizes only for an explicit range. Without one there is a single
  ``Page size:`` line and no per-page figures at all, so a per-page dimension cannot be read
  from the default invocation.
* **``-f 0 -l 0`` is accepted and prints two per-page lines — pages 1 and 2.** The zero
  bound again reads as "no range", and the range it produces is neither empty nor the whole
  document. That is why :func:`~docflow.pdf.primitives.engine.require_positive_page_range`
  runs here too, and why the requested range is never what gets parsed: the page number is
  matched against the numbered line instead of being assumed from position.
* ``-f 1 -l 99999`` is accepted and silently truncated to the document's own pages; only a
  range starting *past* the end exits 99. The engine's answer is therefore the authority on
  how many pages exist, never the bound that was asked for.
* A missing or corrupt file exits **1** — not 99 — with the diagnosis on stderr and nothing
  on stdout. Code that only checked for 99 would read a truncated document as a success.
* An encrypted file also exits **1**, with ``Incorrect password``, which is why causes are
  separated by inspecting the document rather than by matching the message
  (:mod:`docflow.pdf.primitives.failures`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from docflow.pdf.primitives.engine import (
    PopplerCommand,
    PopplerError,
    require_positive_page_range,
    run_engine_command,
)
from docflow.pdf.primitives.failures import (
    PDFPrimitiveError,
    check_pdf_is_readable,
    classify_engine_failure,
)

_PAGE_COUNT_PATTERN = re.compile(r"^Pages:\s+(\d+)\s*$", re.MULTILINE)
_PAGE_SIZE_PATTERN = re.compile(
    r"^Page\s+(\d+)\s+size:\s+([\d.]+)\s+x\s+([\d.]+)\s+pts", re.MULTILINE
)
_ENCRYPTED_PATTERN = re.compile(r"^Encrypted:\s+(\S+)\s*$", re.MULTILINE)
_METADATA_PATTERN = re.compile(r"^([A-Za-z][^:]*?):\s+(.*?)\s*$")

_SIZE_LINE_MARKER = "Page "
"""Prefix of the per-page lines, which are not document metadata."""

ENCRYPTED_YES = "yes"
"""The value ``Encrypted:`` carries when the document declares encryption."""


@dataclass(frozen=True)
class PDFDocumentInfo:
    """What a PDF reports about itself, gathered in one pass.

    Attributes:
        metadata: The document's own metadata, as the engine reports it (title, producer,
            creation date, …). Values are strings because that is how they are read.
        page_count: Number of pages.
        page_dimensions: Page size in PDF points, per page, in page order.
        encrypted: Whether the document declares itself encrypted. Always ``False`` in a
            value that is returned at all: an encrypted document is reported as a typed
            failure instead, because nothing else on this record could be trusted if the
            engine could not read the file.
    """

    metadata: dict[str, str]
    page_count: int
    page_dimensions: list[tuple[float, float]]
    encrypted: bool


def _run_pdfinfo(pdf_path: Path, *, page_range: tuple[int, int] | None = None) -> str:
    """Run ``pdfinfo`` and classify any failure into the contract's vocabulary.

    Args:
        pdf_path: PDF to inspect.
        page_range: Pages to report per-page lines for, or ``None`` for the document only.

    Returns:
        The command's standard output.

    Raises:
        PDFPrimitiveError: The document is unreadable, or the engine rejected the range.
    """
    check_pdf_is_readable(pdf_path)
    arguments = [
        *(("-f", str(page_range[0]), "-l", str(page_range[1])) if page_range else ()),
        str(pdf_path),
    ]

    try:
        return run_engine_command(PopplerCommand.PDFINFO, arguments)
    except PopplerError as failure:
        raise classify_engine_failure(
            pdf_path,
            failure,
            page_number=page_range[0] if page_range else None,
        ) from failure


def _parse_page_count(output: str, pdf_path: Path) -> int:
    """Read the page count from ``pdfinfo`` output.

    Args:
        output: The command's standard output.
        pdf_path: The document, for the error message.

    Returns:
        The number of pages.

    Raises:
        PDFPrimitiveError: No page count is present, which means the output was not
            ``pdfinfo``'s. Reported rather than defaulted to zero: a document whose count
            could not be read is not a document with no pages.
    """
    found = _PAGE_COUNT_PATTERN.search(output)
    if found is None:
        raise PDFPrimitiveError(
            "CORRUPTED_PDF",
            f"{pdf_path} reported no page count",
            detail=output.strip(),
        )
    return int(found.group(1))


def _parse_page_sizes(output: str) -> list[tuple[int, float, float]]:
    """Read the numbered per-page sizes from ``pdfinfo`` output.

    Args:
        output: The command's standard output.

    Returns:
        ``(page_number, width, height)`` triples in the order the engine printed them.
    """
    return [
        (int(page), float(width), float(height))
        for page, width, height in _PAGE_SIZE_PATTERN.findall(output)
    ]


def get_pdf_metadata(pdf_path: Path) -> dict[str, str]:
    """Read the document's own metadata.

    Args:
        pdf_path: PDF to inspect. Never written to.

    Returns:
        The metadata as key/value pairs, exactly as the engine reports it. The per-page
        lines are excluded: they are not document metadata.

    Raises:
        PDFPrimitiveError: The document is absent, encrypted or unreadable.

    # TODO: [MVP] real per-key typing (dates, page sizes) is deferred and every value is
    # exposed as the engine's own string.
    """
    output = _run_pdfinfo(pdf_path)

    metadata: dict[str, str] = {}
    for line in output.splitlines():
        if line.startswith(_SIZE_LINE_MARKER):
            continue
        found = _METADATA_PATTERN.match(line)
        if found is not None:
            metadata[found.group(1).strip()] = found.group(2)
    return metadata


def get_page_count(pdf_path: Path) -> int:
    """Count the pages of a PDF.

    Args:
        pdf_path: PDF to inspect.

    Returns:
        The number of pages.

    Raises:
        PDFPrimitiveError: The document is absent, encrypted or unreadable.
    """
    return _parse_page_count(_run_pdfinfo(pdf_path), pdf_path)


def get_page_dimensions(pdf_path: Path, page_number: int) -> tuple[float, float]:
    """Measure one page.

    Args:
        pdf_path: PDF to inspect.
        page_number: Page index, 1-based.

    Returns:
        The page's ``(width, height)`` in PDF points.

    Raises:
        ValueError: ``page_number`` is below 1.
        PDFPrimitiveError: The page does not exist, or the document is unreadable.
    """
    require_positive_page_range((page_number, page_number))

    output = _run_pdfinfo(pdf_path, page_range=(page_number, page_number))

    # Matched on the printed page number, never on position: a range that starts past the
    # end exits 99, and one that starts at zero is shifted by the engine, so position is not
    # a reliable key.
    for found_page, width, height in _parse_page_sizes(output):
        if found_page == page_number:
            return (width, height)

    raise PDFPrimitiveError(
        "PAGE_OUT_OF_RANGE",
        f"page {page_number} does not exist in {pdf_path}",
        page_number=page_number,
        detail=output.strip(),
    )


def inspect_pdf(pdf_path: Path) -> PDFDocumentInfo:
    """Summarise a document in one call.

    Args:
        pdf_path: PDF to inspect.

    Returns:
        The document's metadata, page count and per-page dimensions.

    Raises:
        PDFPrimitiveError: The document is absent, encrypted or unreadable.
    """
    # The count is read first, because the per-page pass needs an explicit range and the
    # bounds cannot be guessed — `-f 0 -l 0` yields two lines rather than none or all.
    page_count = get_page_count(pdf_path)
    output = _run_pdfinfo(pdf_path, page_range=(1, page_count))
    sizes = _parse_page_sizes(output)

    if len(sizes) != page_count:
        raise PDFPrimitiveError(
            "CORRUPTED_PDF",
            f"{pdf_path} reports {page_count} page(s) but {len(sizes)} page size(s)",
            detail=output.strip(),
        )

    declared = _ENCRYPTED_PATTERN.search(output)

    return PDFDocumentInfo(
        metadata=get_pdf_metadata(pdf_path),
        page_count=page_count,
        page_dimensions=[(width, height) for _, width, height in sizes],
        # The engine's own field. A document that was read this far was readable, so this is
        # expected to be `False`; it is still reported from the output rather than assumed,
        # because a PDF can be encrypted with an empty user password and open anyway.
        encrypted=bool(declared and declared.group(1).lower() == ENCRYPTED_YES),
    )


__all__ = [
    "PDFDocumentInfo",
    "get_page_count",
    "get_page_dimensions",
    "get_pdf_metadata",
    "inspect_pdf",
]
