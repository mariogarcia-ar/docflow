"""Native text primitives — the text layer the PDF already carries.

Owned by ``PDF-06``. An empty text layer is **data**, not a defect to fix: this module has
no OCR fallback, because "nothing was found" and "nothing could be read" are different
answers and only the orchestrator may decide what to do about the second one.

The text is reported as the engine found it. Nothing here rewrites it — no joining of
hyphenated words, no reflowing, no normalisation beyond the page framing. A module that
"fixed" line breaks would be interpreting the document, and interpretation is exactly what
``subplan-procesador-pdf.md`` §2 puts out of bounds for this processor. It is also not
reversible: joining ``"well-\\nknown"`` to ``"wellknown"`` loses a hyphen the document
actually had.

Five facts about the engine shape this module, each verified against Poppler 25.02.0 rather
than assumed:

* **A page with no text yields ``"\\x0c"``, not ``""``.** ``pdftotext`` terminates every
  extracted page with a form feed, so an image-only page returns one byte. Comparing the raw
  result to ``""`` would report a text layer that is not there, and would let a caller count
  a form feed as a character — which is how a page with no text gets classified as ``TEXT``.
  :func:`strip_page_breaks` removes the framing.
* **A zero or negative bound extracts the whole document.** ``-f 0 -l 0`` returns all three
  pages of the fixture. Fourth tool in this package with the hazard, and the reason
  :func:`~docflow.pdf.primitives.engine.require_positive_page_range` runs here too.
* The page break is a **terminator**: ``-f 1 -l 1`` gives ``"page 1…\\n\\n\\x0c"``. A
  single-page extraction therefore has a trailing break where a multi-page run has a
  separator, so the framing is stripped before the payload is returned or measured.
* ``-bbox-layout`` emits XHTML in the **XHTML namespace**, so the block parser queries by
  qualified name. An image-only page still produces a well-formed document with zero
  ``block`` elements — absence of text is an empty list, not a parse failure.
* Text encoding is pinned in the seam (``ENGINE_ENCODING``): ``subprocess`` would otherwise
  decode with the host locale and turn ``café`` into ``cafÃ©`` on a non-UTF-8 machine.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

from docflow.pdf.contracts import TextBlock
from docflow.pdf.primitives.engine import (
    PopplerCommand,
    PopplerError,
    page_range_arguments,
    require_positive_page_range,
    run_engine_command,
)
from docflow.pdf.primitives.failures import (
    classify_engine_failure,
    classify_text_failure,
)

PAGE_BREAK = "\x0c"
"""The form feed ``pdftotext`` uses to separate pages."""

XHTML_NAMESPACE = "http://www.w3.org/1999/xhtml"
"""Namespace of the document ``-bbox-layout`` emits. Without it, no element is found."""

_BLOCK_TAG = f"{{{XHTML_NAMESPACE}}}block"
_WORD_TAG = f"{{{XHTML_NAMESPACE}}}word"
_LINE_TAG = f"{{{XHTML_NAMESPACE}}}line"

_FIRST_BLOCK_ID = 1

_BBOX_KEYS = ("xMin", "yMin", "xMax", "yMax")


@dataclass(frozen=True)
class TextPage:
    """One page's native text and the engine's own measurement of it.

    Both halves come from the same call, and they are returned together because the raw text
    cannot be measured once the framing is stripped: the character count would lose the
    break, and ``PDF-08`` needs a number rather than a derived one.

    Attributes:
        page_number: Page index, 1-based.
        text: The page's text with the framing removed. Empty for a page with no text
            layer — which is what "no text" actually looks like.
        engine_characters: Characters the engine reported, form feeds included. Reportable
            as a composition measurement, never as a stand-in for ``len(text)``.
        paragraphs: The page's text as non-empty pieces in reading order, for callers that
            need a granularity between the page and the block.
    """

    page_number: int
    text: str
    engine_characters: int
    paragraphs: list[str]


def strip_page_breaks(raw: str) -> str:
    """Remove the page framing ``pdftotext`` adds.

    Args:
        raw: The engine's raw output.

    Returns:
        The text with every form feed removed and the edges trimmed. An image-only page,
        which the engine reports as a single form feed, becomes the empty string — the
        honest answer, since that is what the engine found.
    """
    return raw.replace(PAGE_BREAK, "").strip()


def paragraphs(text: str) -> list[str]:
    """Split a page's text into its non-empty pieces.

    A split, not a rewrite: each piece is a slice of the input with its surrounding
    whitespace trimmed, so nothing the engine reported is lost or reordered. Internal
    newlines are preserved, because collapsing them would be a reflow.

    Args:
        text: The page's text, framing already stripped.

    Returns:
        The pieces in reading order, with blank runs dropped.
    """
    return [piece.strip() for piece in text.split("\n\n") if piece.strip()]


def engine_report(path: Path, page_number: int, layout: bool = True) -> TextPage:
    """Extract a page's text and the engine's measurement of it, in one call.

    Takes the same ``layout`` flag as :func:`extract_text_from_page` and defaults it the
    same way. An earlier version omitted it, which made this function and its sibling return
    *different* text for the same page — the two disagreeing about what the page says, with
    neither being obviously wrong. The agreement is asserted by a test rather than left to
    the two call sites to keep in step.

    Args:
        path: Source PDF. Read only.
        page_number: Page index, 1-based.
        layout: Preserve the page's physical layout, as in :func:`extract_text_from_page`.

    Returns:
        The page's text, the engine's character count and its paragraphs.

    Raises:
        ValueError: ``page_number`` is below 1.
        PDFPrimitiveError: The document is unreadable, or the page does not exist.
    """
    require_positive_page_range((page_number, page_number))

    arguments = [
        *(["-layout"] if layout else []),
        *page_range_arguments((page_number, page_number), path),
        "-",
    ]
    try:
        raw = run_engine_command(PopplerCommand.PDFTOTEXT, arguments)
    except PopplerError as failure:
        raise classify_engine_failure(
            path, failure, page_number=page_number
        ) from failure

    text = strip_page_breaks(raw)
    return TextPage(
        page_number=page_number,
        text=text,
        # Measured on the raw output, so the count is the engine's own rather than one
        # derived from text this module already edited.
        engine_characters=len(raw),
        paragraphs=paragraphs(text),
    )


def extract_text_from_page(
    pdf_path: Path,
    page_number: int,
    layout: bool = True,
) -> str:
    """Read the native text of one page.

    Args:
        pdf_path: Source PDF. Read only.
        page_number: Page index, 1-based.
        layout: Preserve the page's physical layout in the text. The default follows the
            frozen signature of ``subplan-procesador-pdf.md` §3; the caller passes
            ``PDFOptions.layout``.

    Returns:
        The page's native text, as the engine produced it. Empty when the page has no text
        layer — a measurement, never an error and never a prompt to substitute an engine.

    Raises:
        ValueError: ``page_number`` is below 1.
        PDFPrimitiveError: The document is unreadable, or the page does not exist.
    """
    require_positive_page_range((page_number, page_number))

    arguments = [
        *(["-layout"] if layout else []),
        *page_range_arguments((page_number, page_number), pdf_path),
        "-",
    ]
    try:
        raw = run_engine_command(PopplerCommand.PDFTOTEXT, arguments)
    except PopplerError as failure:
        raise classify_engine_failure(
            pdf_path, failure, page_number=page_number
        ) from failure

    return strip_page_breaks(raw)


def get_text_blocks(pdf_path: Path, page_number: int) -> list[TextBlock]:
    """Read the native text of one page as ordered blocks with their placement.

    Args:
        pdf_path: Source PDF. Read only.
        page_number: Page index, 1-based.

    Returns:
        The page's text blocks in the order the engine laid them out. Empty when the page
        has no text layer.

    Raises:
        ValueError: ``page_number`` is below 1.
        PDFPrimitiveError: The document is unreadable, the page does not exist, or the
            engine's layout document could not be parsed.
    """
    require_positive_page_range((page_number, page_number))

    try:
        markup = run_engine_command(
            PopplerCommand.PDFTOTEXT,
            [
                "-bbox-layout",
                *page_range_arguments((page_number, page_number), pdf_path),
                "-",
            ],
        )
    except PopplerError as failure:
        raise classify_engine_failure(
            pdf_path, failure, page_number=page_number
        ) from failure

    try:
        root = ElementTree.fromstring(markup)
    except ElementTree.ParseError as failure:
        # Typed as a text failure rather than a document failure: the document parsed well
        # enough to produce a layout report, so the page's other artifacts are unaffected.
        raise classify_text_failure(
            pdf_path, failure, page_number=page_number
        ) from failure

    return _blocks_on_page(root, page_number)


def _blocks_on_page(root: ElementTree.Element, page_number: int) -> list[TextBlock]:
    """Build the blocks of one page from a parsed layout document.

    Args:
        root: The parsed ``-bbox-layout`` document.
        page_number: Page index, 1-based.

    Returns:
        The page's blocks, in document order. Blocks carrying no text are skipped: an empty
        bounding box says nothing about the document's content.
    """
    blocks: list[TextBlock] = []

    for element in root.iter(_BLOCK_TAG):
        text = _block_text(element)
        if not text:
            continue
        blocks.append(
            TextBlock(
                # Numbered by position among the blocks that were kept, so the identifier
                # is stable across runs over the same bytes and gaps never appear.
                block_id=f"block_{len(blocks) + _FIRST_BLOCK_ID:03d}",
                text=text,
                bbox=_block_bbox(element),
                page_number=page_number,
            )
        )

    return blocks


def _block_text(element: ElementTree.Element) -> str:
    """Return one block's text, joined across its lines.

    Lines and words are joined with single spaces, in the engine's own order rather than a
    re-sorted one, which is what keeps the output deterministic. The join is a join of
    existing tokens, not a rewrite: no token is altered or dropped.
    """
    lines: list[str] = []
    for line in element.iter(_LINE_TAG):
        words = [word.text or "" for word in line.iter(_WORD_TAG)]
        joined = " ".join(word for word in words if word)
        if joined:
            lines.append(joined)
    if lines:
        return " ".join(lines)

    # A block without explicit lines still carries words; falling back to them keeps text
    # the engine did report rather than dropping the block.
    words = [word.text or "" for word in element.iter(_WORD_TAG)]
    return " ".join(word for word in words if word)


def _block_bbox(
    element: ElementTree.Element,
) -> tuple[float, float, float, float] | None:
    """Return a block's bounding box, or ``None`` when the engine omitted or malformed it.

    ``TextBlock.bbox`` is optional for exactly this reason. The absence is reported as
    ``None`` rather than filled with zeroes, which would place every unplaced block at the
    page origin and make the coverage arithmetic of ``PDF-08`` wrong.
    """
    values = [element.get(key) for key in _BBOX_KEYS]
    if any(value is None for value in values):
        return None
    try:
        x_min, y_min, x_max, y_max = (
            float(value) for value in values if value is not None
        )
    except ValueError:
        return None
    return (x_min, y_min, x_max, y_max)


__all__ = [
    "PAGE_BREAK",
    "XHTML_NAMESPACE",
    "TextPage",
    "engine_report",
    "extract_text_from_page",
    "get_text_blocks",
    "paragraphs",
    "strip_page_breaks",
]
