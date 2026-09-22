"""Render primitive — one faithful PNG per page, at an explicit resolution.

Owned by ``PDF-05``. The render is what this processor publishes; making it *prettier* is
``procesador-image``'s job, and this module does not deskew, denoise, binarize or enhance.
It renders and gets out of the way.

Four facts about the engine shape this module, each verified against Poppler 25.02.0 rather
than assumed:

* ``pdftoppm`` takes a **prefix and appends its own suffix** — the format and, without
  ``-singlefile``, the page number. A prefix already ending in ``.png`` therefore produces
  ``page.png.png``, which is why the engine is handed a suffix-free prefix and the final
  name is put in place afterwards.
* **Any page number below 1 renders page 1.** ``-f 0 -l 0`` is accepted, exits 0 and writes
  a byte-identical copy of the page-1 render, so the mistake is undetectable from the
  output. The shared :func:`~docflow.pdf.primitives.engine.require_positive_page_range`
  guard is what prevents it; it is *the only* defence here, because unlike ``pdfseparate``
  this tool has no ``%d`` template that would make it refuse a zero bound.
* A page beyond the document exits with status 99 and writes nothing.
* ``-r 0`` does **not** mean "no resolution" — it exits 0 and silently renders at 150 DPI,
  the tool's own default. A resolution of zero is therefore rejected rather than forwarded,
  because accepting it would record a DPI in ``metadata.json`` that the image does not have.
"""

from __future__ import annotations

from pathlib import Path

from docflow.pdf.primitives.engine import (
    PopplerCommand,
    PopplerOutputMissingError,
    require_positive_page_range,
)
from docflow.pdf.primitives.failures import run_classified

RENDER_FORMAT = "png"
"""The only render format in Phase 1. A constant, so no caller can silently pick another."""

MIN_RENDER_DPI = 1
"""Lowest resolution accepted.

Not a quality opinion: ``pdftoppm -r 0`` is accepted by the engine and renders at its own
default of 150 DPI, so a zero passed through would put a resolution in ``metadata.json``
that no image on disk actually has.
"""

_STAGED_SUFFIX = "-staged"
"""Marker in the staged file's stem, so a leftover `.tmp`-style write is recognisable.

The staged name is derived from the published one rather than generated, which keeps two
concurrent renders of the same page from landing on the same file.
"""


def render_page_to_image(
    pdf_path: Path,
    page_number: int,
    output_path: Path,
    dpi: int = 200,
) -> Path:
    """Render one page to a PNG image.

    Args:
        pdf_path: Source PDF. Read only.
        page_number: Page index, 1-based.
        output_path: Where the PNG is written, e.g. ``page_001/render/page.png``. Its
            parent directory is created if absent — the engine does not create it.
        dpi: Render resolution. The default is the value the frozen signature of
            ``subplan-procesador-pdf.md`` §3 documents; a caller always passes the
            resolution from ``PDFOptions.dpi``, so it stands in for no measurement.

    Returns:
        ``output_path``, once the file exists and is non-empty.

    Raises:
        ValueError: ``page_number`` is below 1, or ``dpi`` is below
            :data:`MIN_RENDER_DPI`.
        PopplerExecutionError: The engine rejected the page — a page past the end of the
            document exits with status 99.
        PopplerOutputMissingError: The engine reported success and wrote nothing.
    """
    require_positive_page_range((page_number, page_number))
    if dpi < MIN_RENDER_DPI:
        raise ValueError(
            f"dpi must be at least {MIN_RENDER_DPI}; got {dpi}. The engine accepts 0 and "
            "silently renders at its own default resolution"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # The engine appends its own suffix to the prefix it is given, so it is handed a stem
    # and the published name is put in place afterwards. `-singlefile` is not optional:
    # without it the same prefix would yield one file per page in the range.
    prefix = output_path.parent / f"{output_path.stem}{_STAGED_SUFFIX}"
    run_classified(
        PopplerCommand.PDFTOPPM,
        [
            "-singlefile",
            "-f",
            str(page_number),
            "-l",
            str(page_number),
            f"-{RENDER_FORMAT}",
            "-r",
            str(dpi),
            str(pdf_path),
            str(prefix),
        ],
        pdf_path,
        page_number=page_number,
    )

    staged = Path(f"{prefix}.{RENDER_FORMAT}")
    if not staged.exists() or staged.stat().st_size == 0:
        # A staged file that is absent or empty is not an artifact, and leaving it behind
        # would put a file in a published namespace that no result describes.
        staged.unlink(missing_ok=True)
        raise PopplerOutputMissingError(PopplerCommand.PDFTOPPM, output_path)

    staged.replace(output_path)
    return output_path


__all__ = ["MIN_RENDER_DPI", "RENDER_FORMAT", "render_page_to_image"]
