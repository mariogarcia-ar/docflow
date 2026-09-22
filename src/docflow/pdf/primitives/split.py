"""Split/extract primitives — one self-contained PDF per page, source untouched.

Owned by ``PDF-04``. Output lands under ``page_NNN/source/page.pdf``; the input file is
read-only, and the input-immutability invariant of ``PDF-13`` guards exactly that.

Five facts about the engine shape this module, each verified against Poppler 25.02.0 rather
than assumed:

* ``pdfseparate``'s ``%d`` expands to the **PDF's own page number**, not to a counter, so a
  range split needs renumbering (:mod:`docflow.pdf.primitives.naming`).
* With no range it splits **every** page, so this module never has to know the page count —
  which is why it does not depend on ``PDF-03``'s ``get_page_count``.
* The engine never creates intermediate directories: a missing directory is an ``I/O
  Error``.
* An out-of-range page exits with status **99**, so the caller gets the engine's own
  diagnosis rather than a guess.
* **A page number of zero is not an error to the engine; with a ``%d`` template it is the
  absence of a range.** ``pdfseparate -f 0 -l 0 doc.pdf 'page_%03d.pdf'`` exits **0** and
  splits the whole document. The first version of this module relied on that template, so
  ``extract_page(doc, 0, out)`` published page 1 — renumbered to ``page_001`` — and returned
  it as though it were page 0: a wrong page delivered as a success, which is the silent
  stand-in ``docs/plan/README.md`` §7 forbids.

Two independent defences close that, and both are needed:

1. :func:`~docflow.pdf.primitives.engine.require_positive_page_range`, called before the
   engine is invoked. It lives in the seam because ``pdftoppm`` has the same hazard
   (``PDF-05``), so the rule is stated once.
2. The single-page path hands the engine a **file** output path rather than a template.
   With a file, ``-f 0 -l 0`` is refused outright (``must contain '%d'``, status 99), so the
   engine is a second line of defence rather than the source of the ambiguity.

Either alone would do; keeping both means a future refactor that removes one is caught by
the other. Mutation testing verified this: removing *both* reintroduces the wrong-page
result, while removing either one alone leaves the guards test green.
"""

from __future__ import annotations

from pathlib import Path

from docflow.pdf.primitives.engine import (
    PopplerCommand,
    PopplerError,
    PopplerOutputMissingError,
    page_range_arguments,
    require_positive_page_range,
    run_engine_command,
)
from docflow.pdf.primitives.failures import classify_engine_failure
from docflow.pdf.primitives.naming import engine_page_template, renumber_split_output

_SPLIT_GLOB = "page_*.pdf"


def _split_range_to_directory(
    pdf_path: Path,
    output_directory: Path,
    page_range: tuple[int, int] | None,
) -> list[Path]:
    """Split a range — or the whole document — into numbered one-page PDFs.

    Args:
        pdf_path: Source PDF. Read only.
        output_directory: Directory the split writes into; created if absent.
        page_range: The ``(first, last)`` pages to split, or ``None`` for every page.

    Returns:
        The published one-page PDFs, in page order, named ``page_001.pdf``, … .

    Raises:
        ValueError: The range is not 1-based, or is empty.
        PopplerExecutionError: The engine failed.
        PopplerOutputMissingError: The engine reported success and wrote nothing.
    """
    output_directory.mkdir(parents=True, exist_ok=True)
    template = engine_page_template(output_directory)

    run_engine_command(
        PopplerCommand.PDFSEPARATE,
        [*page_range_arguments(page_range, pdf_path), template],
    )

    written = sorted(output_directory.glob(_SPLIT_GLOB))
    if not written:
        raise PopplerOutputMissingError(PopplerCommand.PDFSEPARATE, Path(template))

    return renumber_split_output(
        directory=output_directory,
        first_page=page_range[0] if page_range else 1,
        expected_count=len(written),
    )


def extract_page(pdf_path: Path, page_number: int, output_path: Path) -> Path:
    """Write one page of a PDF as a self-contained one-page PDF.

    Args:
        pdf_path: Source PDF. Read only: never written to.
        page_number: Page index, 1-based.
        output_path: Where the one-page PDF is written, e.g.
            ``page_001/source/page.pdf``. Its parent directory is created if absent.

    Returns:
        ``output_path``, once the file exists.

    Raises:
        ValueError: ``page_number`` is below 1.
        PopplerExecutionError: The engine rejected the page — an out-of-range page exits
            with status 99.
        PopplerOutputMissingError: The engine reported success and wrote nothing.
    """
    require_positive_page_range((page_number, page_number))
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # A file path rather than a `%d` template, deliberately: with an explicit file the
    # engine refuses a zero or inverted range instead of reading the bounds as "no range"
    # and silently splitting the whole document.
    try:
        run_engine_command(
            PopplerCommand.PDFSEPARATE,
            [
                "-f",
                str(page_number),
                "-l",
                str(page_number),
                str(pdf_path),
                str(output_path),
            ],
        )
    except PopplerError as failure:
        raise classify_engine_failure(
            pdf_path, failure, page_number=page_number
        ) from failure

    if not output_path.exists():
        raise PopplerOutputMissingError(PopplerCommand.PDFSEPARATE, output_path)
    return output_path


def split_pdf(pdf_path: Path, output_dir: Path) -> list[Path]:
    """Write every page of a PDF as its own one-page PDF.

    Args:
        pdf_path: Source PDF. Read only.
        output_dir: Directory to write the one-page PDFs into; created if absent.

    Returns:
        The written files, in page order, named ``page_001.pdf``, ``page_002.pdf``, … .

    Raises:
        PopplerExecutionError: The engine failed.
        PopplerOutputMissingError: The engine reported success and wrote nothing.
    """
    return _split_range_to_directory(
        pdf_path=pdf_path, output_directory=output_dir, page_range=None
    )


def merge_pdfs(pdf_paths: list[Path], output_path: Path) -> Path:
    """Concatenate PDFs into one file.

    A generic utility, deliberately off the happy path: nothing in the document workflow
    merges pages back together. It is here because the engine offers it and because a
    writer assembling a document from per-page artifacts needs it.

    # TODO: [MVP] the PoC exercises this off the happy path only; rebase it on real
    # multi-document assembly if the orchestrator ever needs to rebuild a document.

    Args:
        pdf_paths: Files to concatenate, in the order they should appear.
        output_path: Where the combined PDF is written.

    Returns:
        ``output_path``, once the file exists.

    Raises:
        ValueError: ``pdf_paths`` is empty. The engine itself exits 99 in that case, so the
            check is for the caller's benefit rather than a guard against silence.
        PopplerExecutionError: The engine failed.
        PopplerOutputMissingError: The engine reported success and wrote nothing.
    """
    if not pdf_paths:
        raise ValueError("merge_pdfs needs at least one input PDF")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    run_engine_command(
        PopplerCommand.PDFUNITE,
        [*(str(path) for path in pdf_paths), str(output_path)],
    )

    if not output_path.exists():
        raise PopplerOutputMissingError(PopplerCommand.PDFUNITE, output_path)
    return output_path


__all__ = ["extract_page", "merge_pdfs", "split_pdf"]
