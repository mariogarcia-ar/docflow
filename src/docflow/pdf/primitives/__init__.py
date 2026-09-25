"""Low-level PDF primitives — the only place that knows Poppler.

Every engine symbol of the PDF processor lives in this module: ``pdfinfo``, ``pdftotext``,
``pdfimages``, ``pdfseparate``, ``pdftoppm`` and ``pdfunite`` are reached from here and
from nowhere else. The engine is resolved **at call time** and named explicitly — there is
no fallback, no probing for an installed binary and no default reader — so
``import docflow.pdf.primitives`` succeeds with Poppler absent and an absent binary
surfaces as a typed ``IO_ERROR`` from the call instead of an import error.

The subprocess contract shapes the module. Poppler is a set of CLI binaries: it returns
**files plus an exit code and stderr**, never a value. So each primitive runs one binary,
reads its exit code and stderr into a typed failure, and publishes what the binary wrote
through :mod:`docflow.pdf.primitives.publication`. The engine writes into a scratch
directory; the artifact names under ``source/``, ``render/``, ``native_text/`` and
``embedded_images/`` are ours, never the engine's numbering.

Engine signal → failure kind (the mapping this module is the only owner of):

=========================== ======================================================
Engine signal               ``PDFErrorType``
=========================== ======================================================
no readable file, bad range ``INVALID_INPUT`` (decided here or before the call)
header version not 1.x/2.x  ``UNSUPPORTED_PDF``
exit 3                      ``ENCRYPTED_PDF``
``Syntax Error`` in stderr  ``CORRUPTED_PDF`` (fatal even on exit 0)
exit 1                      ``INVALID_INPUT``
``Wrong page range given``  ``PAGE_EXTRACTION_ERROR`` (not ``RENDER_ERROR``)
exit 2                      ``IO_ERROR``
exit 99 while rendering     ``RENDER_ERROR``
exit 99 while extracting    ``PAGE_EXTRACTION_ERROR`` / ``TEXT_EXTRACTION_ERROR`` /
                            ``IMAGE_EXTRACTION_ERROR``, per the binary
binary not found            ``IO_ERROR``, not recoverable
=========================== ======================================================

Two rules hold for everything here: the input PDF is never written to, and nothing is
published except through the atomic writer.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

from docflow.pdf.contracts import EmbeddedImage, PDFErrorType, TextBlock
from docflow.pdf.primitives.composition import (
    PDFDocumentInfo,
    PDFPageData,
    analyze_pdf_page,
    classify_pdf_page,
)
from docflow.pdf.primitives.errors import PDFPrimitiveError, for_page, typed_failure
from docflow.pdf.primitives.publication import publish_file, publish_json, publish_text
from docflow.pdf.primitives.validation import (
    validate_pdf,
    validate_pdf_page_result,
    validate_pdf_result,
)

#: Name recorded as ``engine`` in every artifact's metadata.
ENGINE_NAME: Final[str] = "poppler"

#: The binary whose ``-v`` names the engine version.
VERSION_BINARY: Final[str] = "pdfinfo"

#: Every call is bounded: the engine has no timeout flag of its own, so the seam owns it.
#: TODO: [RELEASE] make the budget configurable and proportional to the document.
POPPLER_TIMEOUT_SECONDS: Final[float] = 120.0

#: Upper bound passed as ``-l`` when the whole document is inspected in one call. The
#: engine clamps it to the real page count, which is what makes one call enough.
ALL_PAGES_UPPER_BOUND: Final[int] = 999_999

#: Text encoding requested from the engine, fixed rather than inherited from its default.
TEXT_ENCODING: Final[str] = "UTF-8"

#: A point bounding box: ``(left, top, right, bottom)``, in PDF points.
BBox = tuple[float, float, float, float]

_PAGE_SIZE_ROW = re.compile(r"^Page\s+(\d+)\s+size:\s+([0-9.]+)\s+x\s+([0-9.]+)")
_ENGINE_INDEX = re.compile(r"-(\d+)\.[A-Za-z0-9]+$")

__all__ = [
    "ALL_PAGES_UPPER_BOUND",
    "ENGINE_NAME",
    "POPPLER_TIMEOUT_SECONDS",
    "TEXT_ENCODING",
    "VERSION_BINARY",
    "BBox",
    "PDFDocumentInfo",
    "PDFPageData",
    "PDFPrimitiveError",
    "analyze_pdf_page",
    "classify_pdf_page",
    "extract_images_from_page",
    "extract_page",
    "extract_text_from_page",
    "for_page",
    "inspect_pdf",
    "merge_pdfs",
    "poppler_version",
    "publish_file",
    "publish_json",
    "publish_text",
    "render_page_to_image",
    "split_pdf",
    "typed_failure",
    "validate_pdf",
    "validate_pdf_page_result",
    "validate_pdf_result",
]


def _run_poppler(
    binary: str,
    arguments: Sequence[str],
    *,
    page_number: int | None = None,
    failure_type: PDFErrorType = "INTERNAL_ERROR",
    recoverable: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run one Poppler binary and return its completed process.

    Args:
        binary: The binary name, resolved on ``PATH`` at call time.
        arguments: Its arguments, in order.
        page_number: Page the call belongs to, or ``None`` for the document.
        failure_type: The failure kind a non-zero exit maps to when stderr carries no
            more specific signal.
        recoverable: Whether the run can continue without what this call produced.

    Returns:
        The completed process, with stdout decoded as text.

    Raises:
        PDFPrimitiveError: With ``IO_ERROR`` when the binary is absent or the call times
            out, or with the mapped kind of a non-zero exit or a syntax error.
    """
    argv = [binary, *arguments]
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            check=False,
            timeout=POPPLER_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise typed_failure(
            "IO_ERROR",
            f"the {ENGINE_NAME} binary {binary!r} is not available",
            page_number=page_number,
            recoverable=False,
            metadata={"binary": binary, "argv": argv},
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise typed_failure(
            "INTERNAL_ERROR",
            f"{binary} did not finish within {POPPLER_TIMEOUT_SECONDS}s",
            page_number=page_number,
            recoverable=recoverable,
            metadata={"binary": binary, "argv": argv},
        ) from exc

    if completed.returncode != 0:
        raise _engine_failure(
            binary,
            completed,
            page_number=page_number,
            failure_type=failure_type,
            recoverable=recoverable,
        )

    stderr = completed.stderr or ""
    if "Syntax Error" in stderr:
        # The CLI-driver reference treats this as fatal even on a successful exit, and so
        # do we: publishing the text of a document the reader could not fully parse would
        # report truncated content as a complete extraction.
        raise typed_failure(
            "CORRUPTED_PDF",
            f"{binary} reported a syntax error",
            page_number=page_number,
            recoverable=False,
            metadata={"binary": binary, "argv": argv, "stderr": stderr.strip()},
        )

    return completed


def _engine_failure(
    binary: str,
    completed: subprocess.CompletedProcess[str],
    *,
    page_number: int | None,
    failure_type: PDFErrorType,
    recoverable: bool,
) -> PDFPrimitiveError:
    """Map the engine's exit code and stderr onto a typed failure."""
    stderr = (completed.stderr or "").strip()
    metadata: dict[str, Any] = {
        "binary": binary,
        "exit_code": completed.returncode,
        "stderr": stderr,
    }

    if "Syntax Error" in stderr:
        return typed_failure(
            "CORRUPTED_PDF",
            f"{binary} reported a syntax error",
            page_number=page_number,
            recoverable=False,
            metadata=metadata,
        )
    if completed.returncode == 3:
        return typed_failure(
            "ENCRYPTED_PDF",
            f"{binary} could not read the document's permissions",
            page_number=page_number,
            recoverable=False,
            metadata=metadata,
        )
    if completed.returncode == 1:
        return typed_failure(
            "INVALID_INPUT",
            f"{binary} could not open the document",
            page_number=page_number,
            recoverable=False,
            metadata=metadata,
        )
    if "Wrong page range given" in stderr:
        # The exit code is the generic 99; only stderr separates an impossible page range
        # from a failure of the work itself.
        return typed_failure(
            "PAGE_EXTRACTION_ERROR",
            f"{binary} rejected the requested page range",
            page_number=page_number,
            recoverable=False,
            metadata=metadata,
        )
    if completed.returncode == 2:
        return typed_failure(
            "IO_ERROR",
            f"{binary} could not open its output",
            page_number=page_number,
            recoverable=recoverable,
            metadata=metadata,
        )
    return typed_failure(
        failure_type,
        f"{binary} exited with {completed.returncode}",
        page_number=page_number,
        recoverable=recoverable,
        metadata=metadata,
    )


def poppler_version() -> str:
    """Return the engine version, as the engine itself reports it.

    Returns:
        The version token of the engine's own ``-v`` line, e.g. ``"25.02.0"``.

    Raises:
        PDFPrimitiveError: With ``IO_ERROR`` when the binary is absent and
            ``INTERNAL_ERROR`` when its report cannot be read: the version is recorded in
            every artifact, so an unreadable one is reported rather than guessed.
    """
    completed = _run_poppler(
        VERSION_BINARY, ["-v"], failure_type="IO_ERROR", recoverable=False
    )
    reported = completed.stdout or completed.stderr or ""
    for line in reported.splitlines():
        tokens = line.split()
        if "version" in tokens:
            version = tokens[tokens.index("version") + 1 :]
            if version:
                return version[0]

    raise typed_failure(
        "INTERNAL_ERROR",
        f"{VERSION_BINARY} did not report a version",
        recoverable=False,
        metadata={"reported": reported.strip()},
    )


def inspect_pdf(pdf_path: Path) -> PDFDocumentInfo:
    """Read the document's metadata, page count and per-page dimensions in one call.

    One call, so the count and the geometry cannot describe two different reads.

    Args:
        pdf_path: The document to inspect.

    Returns:
        The document information. ``page_dimensions`` carries one entry per page, in page
        order, in PDF points.

    Raises:
        PDFPrimitiveError: With the typed kind of the engine's failure, or
            ``INTERNAL_ERROR`` when its report cannot be read as a whole.
    """
    completed = _run_poppler(
        "pdfinfo",
        ["-box", "-f", "1", "-l", str(ALL_PAGES_UPPER_BOUND), str(pdf_path)],
        failure_type="CORRUPTED_PDF",
        recoverable=False,
    )

    page_count: int | None = None
    dimensions: dict[int, tuple[float, float]] = {}
    engine_metadata: dict[str, str] = {}
    try:
        for line in completed.stdout.splitlines():
            key, _, value = line.partition(":")
            name = key.strip()
            if not name:
                continue
            per_page = _PAGE_SIZE_ROW.match(line)
            if per_page is not None:
                dimensions[int(per_page.group(1))] = (
                    float(per_page.group(2)),
                    float(per_page.group(3)),
                )
                continue
            if name == "Pages":
                page_count = int(value.strip())
                continue
            if name.startswith("Page"):
                continue
            engine_metadata[name] = value.strip()
    except ValueError as exc:
        raise typed_failure(
            "INTERNAL_ERROR",
            "the engine's inspection report could not be read",
            recoverable=False,
            metadata={"stdout": completed.stdout},
        ) from exc

    if page_count is None:
        raise typed_failure(
            "INTERNAL_ERROR",
            "the engine reported no page count",
            recoverable=False,
            metadata={"stdout": completed.stdout},
        )

    if set(dimensions) != set(range(1, page_count + 1)):
        # TODO: [MVP] a report that names fewer pages than it counts is rejected rather
        # than padded: an unmeasured page must not inherit a neighbour's geometry.
        raise typed_failure(
            "INTERNAL_ERROR",
            "the engine's page count and its per-page geometry disagree",
            recoverable=False,
            metadata={
                "page_count": page_count,
                "geometry_pages": sorted(dimensions),
                "stdout": completed.stdout,
            },
        )

    return PDFDocumentInfo(
        page_count=page_count,
        page_dimensions=[dimensions[number] for number in range(1, page_count + 1)],
        engine_metadata=engine_metadata,
    )


def extract_page(pdf_path: Path, page_number: int, output_path: Path) -> Path:
    """Publish one page as a self-contained PDF.

    Args:
        pdf_path: The document to read. It is never written to.
        page_number: Page index, 1-based.
        output_path: Where the one-page PDF is published.

    Returns:
        ``output_path``, once it is complete.

    Raises:
        PDFPrimitiveError: With ``PAGE_EXTRACTION_ERROR`` when the engine refuses the
            page, or the mapped kind of its failure.
    """
    with tempfile.TemporaryDirectory(prefix="docflow-pdf-split-") as scratch:
        pattern = Path(scratch) / "page-%03d.pdf"
        _run_poppler(
            "pdfseparate",
            [
                "-f",
                str(page_number),
                "-l",
                str(page_number),
                str(pdf_path),
                str(pattern),
            ],
            page_number=page_number,
            failure_type="PAGE_EXTRACTION_ERROR",
        )
        return publish_file(Path(scratch) / f"page-{page_number:03d}.pdf", output_path)


def split_pdf(pdf_path: Path, output_dir: Path) -> list[Path]:
    """Publish one self-contained PDF per page, in page order.

    Args:
        pdf_path: The document to split.
        output_dir: Directory that receives ``page_001.pdf``, ``page_002.pdf``, …

    Returns:
        The published paths, in page order.
    """
    document = inspect_pdf(pdf_path)
    return [
        extract_page(pdf_path, page_number, output_dir / f"page_{page_number:03d}.pdf")
        for page_number in range(1, document.page_count + 1)
    ]


def merge_pdfs(pdf_paths: Sequence[Path], output_path: Path) -> Path:
    """Publish the concatenation of ``pdf_paths`` into one PDF, in the given order.

    Args:
        pdf_paths: Documents to concatenate.
        output_path: Where the merged PDF is published.

    Returns:
        ``output_path``, once it is complete.

    Raises:
        PDFPrimitiveError: With ``INVALID_INPUT`` when no document was given.

    # TODO: [MVP] generic utility, off the happy path: no caller inside the pipeline, so
    # it is implemented and tested but never composed into a document run.
    """
    if not pdf_paths:
        raise typed_failure(
            "INVALID_INPUT", "merge_pdfs needs at least one document", recoverable=False
        )

    with tempfile.TemporaryDirectory(prefix="docflow-pdf-merge-") as scratch:
        produced = Path(scratch) / "merged.pdf"
        _run_poppler(
            "pdfunite",
            [*(str(path) for path in pdf_paths), str(produced)],
            failure_type="IO_ERROR",
            recoverable=False,
        )
        return publish_file(produced, output_path)


def render_page_to_image(
    pdf_path: Path,
    page_number: int,
    output_path: Path,
    dpi: int = 200,
) -> Path:
    """Render one page to PNG at an explicit resolution.

    Args:
        pdf_path: The document to read.
        page_number: Page index, 1-based.
        output_path: Where the PNG is published.
        dpi: Render resolution; PNG is the only render format in Phase 1.

    Returns:
        ``output_path``, once it is complete.

    Raises:
        PDFPrimitiveError: With ``INVALID_INPUT`` when the resolution makes no sense, or
            ``RENDER_ERROR`` when the render fails.
    """
    if dpi <= 0:
        raise typed_failure(
            "INVALID_INPUT", f"dpi must be positive, not {dpi}", recoverable=False
        )

    with tempfile.TemporaryDirectory(prefix="docflow-pdf-render-") as scratch:
        root = Path(scratch) / "page"
        _run_poppler(
            "pdftoppm",
            [
                "-png",
                "-r",
                str(dpi),
                "-f",
                str(page_number),
                "-l",
                str(page_number),
                "-singlefile",
                str(pdf_path),
                str(root),
            ],
            page_number=page_number,
            failure_type="RENDER_ERROR",
        )
        return publish_file(root.with_suffix(".png"), output_path)


def _text_bbox(columns: Sequence[str]) -> BBox:
    """Return the engine's ``left/top/width/height`` columns as a point bounding box."""
    left, top, width, height = (float(value) for value in columns[6:10])
    return (left, top, left + width, top + height)


def _close_line(
    line_words: list[str], page_lines: list[str], flow_lines: list[str]
) -> None:
    """Close the open line: its text joins the page and the flow."""
    if not line_words:
        return
    text = " ".join(line_words)
    page_lines.append(text)
    flow_lines.append(text)
    line_words.clear()


def _close_flow(
    flow_lines: list[str],
    flow_bbox: BBox | None,
    *,
    page_number: int,
    layout: bool,
    block_number: int,
) -> TextBlock | None:
    """Return the flow as a block, or ``None`` when the flow carried no text."""
    text = "\n".join(flow_lines)
    if not text:
        return None
    return TextBlock(
        block_id=f"block_{block_number:03d}",
        text=text,
        bbox=flow_bbox if layout else None,
        page_number=page_number,
    )


def _parse_text_rows(
    reported: str, page_number: int, *, layout: bool
) -> tuple[str, list[TextBlock]]:
    """Turn one ``pdftotext`` row report into the page's text and its ordered blocks.

    The rows carry a level: ``3`` opens a flow, ``4`` opens a line and ``5`` is a word.
    The text comes from the same rows the blocks do, so the two artifacts cannot describe
    two different reads.

    # TODO: [MVP] blocks are the engine's flows, and a word carries no character offsets:
    # a layout-aware reconstruction that reads columns properly is deferred (``PDF-06``).
    """
    page_lines: list[str] = []
    blocks: list[TextBlock] = []
    flow_lines: list[str] = []
    flow_bbox: BBox | None = None
    line_words: list[str] = []

    for row in reported.splitlines():
        columns = row.split("\t")
        if len(columns) < 12:
            continue
        level = columns[0].strip()
        if level == "3":
            _close_line(line_words, page_lines, flow_lines)
            block = _close_flow(
                flow_lines,
                flow_bbox,
                page_number=page_number,
                layout=layout,
                block_number=len(blocks) + 1,
            )
            if block is not None:
                blocks.append(block)
            flow_lines = []
            flow_bbox = _text_bbox(columns)
        elif level == "4":
            _close_line(line_words, page_lines, flow_lines)
        elif level == "5":
            word = columns[11].strip()
            if word:
                line_words.append(word)
        # Every other level — the header row, the page row — publishes no text.

    _close_line(line_words, page_lines, flow_lines)
    block = _close_flow(
        flow_lines,
        flow_bbox,
        page_number=page_number,
        layout=layout,
        block_number=len(blocks) + 1,
    )
    if block is not None:
        blocks.append(block)

    return "\n".join(page_lines), blocks


def extract_text_from_page(
    pdf_path: Path,
    page_number: int,
    layout: bool = True,
) -> tuple[str, list[TextBlock]]:
    """Extract one page's native text and its ordered blocks from a single read.

    Args:
        pdf_path: The document to read.
        page_number: Page index, 1-based.
        layout: Whether the blocks keep their bounding boxes. The read is the same either
            way; only the boxes are dropped, so text and blocks still come from one call.

    Returns:
        The page's text and its blocks in reading order. A page with no text layer returns
        an empty text and no blocks: an empty extraction is data, not a failure to fix.

    Raises:
        PDFPrimitiveError: With ``TEXT_EXTRACTION_ERROR`` when the engine fails.
    """
    completed = _run_poppler(
        "pdftotext",
        [
            "-tsv",
            "-f",
            str(page_number),
            "-l",
            str(page_number),
            "-enc",
            TEXT_ENCODING,
            str(pdf_path),
            "-",
        ],
        page_number=page_number,
        failure_type="TEXT_EXTRACTION_ERROR",
    )
    return _parse_text_rows(completed.stdout, page_number, layout=layout)


def _reported_images(pdf_path: Path, page_number: int) -> list[dict[str, Any]]:
    """Read the engine's own report of the images embedded in one page."""
    completed = _run_poppler(
        "pdfimages",
        ["-list", "-f", str(page_number), "-l", str(page_number), str(pdf_path)],
        page_number=page_number,
        failure_type="IMAGE_EXTRACTION_ERROR",
    )

    reported: list[dict[str, Any]] = []
    for row in completed.stdout.splitlines():
        columns = row.split()
        if len(columns) < 13 or not columns[0].isdigit():
            # The engine's header and its dashed rule are not rows of measurements.
            continue
        try:
            if int(columns[0]) != page_number or not columns[3].isdigit():
                continue
            reported.append(
                {
                    "type": columns[2],
                    "width": int(columns[3]),
                    "height": int(columns[4]),
                    "color": columns[5],
                    "bpc": columns[7],
                    "encoding": columns[8],
                    "object_id": f"{columns[10]} {columns[11]}",
                }
            )
        except (IndexError, ValueError) as exc:
            raise typed_failure(
                "INTERNAL_ERROR",
                "the engine's image report could not be read",
                page_number=page_number,
                recoverable=True,
                metadata={"row": row},
            ) from exc

    return reported


def _engine_file_index(path: Path) -> int:
    """Return the sequence number the engine put in a produced file's name."""
    match = _ENGINE_INDEX.search(path.name)
    if match is None:
        raise typed_failure(
            "INTERNAL_ERROR",
            f"the engine produced a file this processor cannot order: {path.name}",
            metadata={"file": str(path)},
        )
    return int(match.group(1))


def extract_images_from_page(
    pdf_path: Path,
    page_number: int,
    output_dir: Path,
) -> list[EmbeddedImage]:
    """Extract the images embedded in one page, with their records, in one call.

    Args:
        pdf_path: The document to read.
        page_number: Page index, 1-based.
        output_dir: Directory that receives ``image_001.png``, ``image_002.png``, … It is
            created only when the page has images.

    Returns:
        One record per extracted image, in the engine's scan order. The bounding box is
        ``None``: this engine reports no placement for an embedded image, and an
        unreported box is not a guessed one. A page with no embedded images returns an
        empty list, which is data rather than a failure.

    Raises:
        PDFPrimitiveError: With ``IMAGE_EXTRACTION_ERROR`` when the engine fails, or
            ``INTERNAL_ERROR`` when its report and its output disagree.
    """
    reported = _reported_images(pdf_path, page_number)

    with tempfile.TemporaryDirectory(prefix="docflow-pdf-images-") as scratch:
        root = Path(scratch) / "image"
        _run_poppler(
            "pdfimages",
            [
                "-png",
                "-f",
                str(page_number),
                "-l",
                str(page_number),
                str(pdf_path),
                str(root),
            ],
            page_number=page_number,
            failure_type="IMAGE_EXTRACTION_ERROR",
        )
        produced = sorted(Path(scratch).glob("image-*.png"), key=_engine_file_index)

        if len(produced) != len(reported):
            raise typed_failure(
                "INTERNAL_ERROR",
                "the engine listed a different number of images than it extracted",
                page_number=page_number,
                recoverable=True,
                metadata={"listed": len(reported), "extracted": len(produced)},
            )

        images: list[EmbeddedImage] = []
        for index, (source, attributes) in enumerate(
            zip(produced, reported, strict=True), start=1
        ):
            image_id = f"image_{index:03d}"
            images.append(
                EmbeddedImage(
                    image_id=image_id,
                    path=publish_file(source, output_dir / f"{image_id}.png"),
                    bbox=None,
                    width=attributes["width"],
                    height=attributes["height"],
                    format=attributes["encoding"],
                    metadata={
                        key: attributes[key]
                        for key in ("type", "color", "bpc", "object_id")
                    },
                )
            )
        return images
