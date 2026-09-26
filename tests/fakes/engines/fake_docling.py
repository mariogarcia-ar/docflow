"""The in-memory Docling double (``OCR-14``).

Docling is a Python library: it hands back **its own document model**, never files and never one of
our types. This double models exactly that. It stands where the seam resolves the engine — the
module attribute ``docflow.ocr.primitives.docling`` and the engine call
:func:`docflow.ocr.primitives.convert_image_with_docling` — so the whole translation between the
engine's structures and our artifact tree stays under test (`README.md` §9.7). It never returns one
of our types: a fake that returned an ``OCRResult`` would delete the half of the module it exists to
exercise.

Two properties of this double are load-bearing, and neither is cosmetic:

* **the items come back in adversarial order.** The real engine iterates its document in reading
  order, so a fake that did the same would let a broken sort pass unnoticed. This one hands the
  caption back before the heading and the table before both, while each item's provenance still
  records where it sits on the page — which is what makes the ordering invariant falsifiable;
* **the shapes are the engine's own.** ``ConversionStatus`` is a ``str`` enum,
  ``document.iterate_items()`` yields ``(item, level)`` pairs, a bounding box is reached through
  ``prov[0].bbox.as_tuple()``, a table's cells carry their row and column offsets, and a page
  reports its size. Anything less faithful would stop testing the translation.

Three knobs make Docling's failure surface reachable with no library installed:

* :attr:`FakeDocling.raises` — an exception during conversion, the shape that arrives as an
  exception rather than as a status;
* :attr:`FakeDocling.status` / :attr:`FakeDocling.errors` — the *returned* failure, which the real
  engine also reports without raising;
* the ``document`` factory — :func:`empty_document` produces the blank page whose emptiness is
  **data**, not a failure.

Every conversion is recorded in :attr:`FakeDocling.calls`, so a test can prove that no conversion
happened at all.

# TODO: [RELEASE] re-read this double against the engine's documented shapes on every pin bump: a
# hand-written double is the one place an engine shape change has to be re-checked, and the suite
# cannot notice it by itself (`GEN-17`).
"""

from __future__ import annotations

import struct
from collections.abc import Callable, Iterator, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Any

#: The version the double reports. Deliberately synthetic: a test that asserted a real version
#: would be asserting what Docling says, not what our seam does.
FAKE_ENGINE_VERSION = "9.9.9-test"

#: The frame every committed OCR fixture uses, asserted by the fixtures' own test.
FIXTURE_WIDTH = 240
FIXTURE_HEIGHT = 120

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class FakeConversionStatus(StrEnum):
    """The engine's conversion status, modelled as the ``str`` enum the real one is."""

    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILURE = "failure"


class FakeDocItemLabel(StrEnum):
    """The engine's item labels, as far as this seam reads them."""

    TEXT = "text"
    TITLE = "title"
    SECTION_HEADER = "section_header"
    LIST_ITEM = "list_item"
    CAPTION = "caption"
    PICTURE = "picture"
    PAGE_FOOTER = "page_footer"
    TABLE = "table"


class FakeDoclingError(Exception):
    """The engine's own exception, for the conversions that raise instead of returning."""


class FakeSize:
    """A page's size, in the engine's own units."""

    # pylint: disable=too-few-public-methods
    # Reason: the object exists to model the engine's returned handle and nothing else.

    def __init__(self, width: float, height: float) -> None:
        """Record the size.

        Args:
            width: Page width.
            height: Page height.
        """
        self.width = width
        self.height = height


class FakeBoundingBox:
    """A bounding box with the engine's own field names and its ``as_tuple`` accessor."""

    # pylint: disable=invalid-name,too-few-public-methods
    # Reason: ``l``/``t``/``r``/``b`` are the engine's own field names; there is nothing else here.

    def __init__(self, left: float, top: float, right: float, bottom: float) -> None:
        """Record the four coordinates.

        Args:
            left: Left edge.
            top: Top edge.
            right: Right edge.
            bottom: Bottom edge.
        """
        self.l = left
        self.t = top
        self.r = right
        self.b = bottom

    def as_tuple(self) -> tuple[float, float, float, float]:
        """Return the box the way the engine's callers read it."""
        return (self.l, self.t, self.r, self.b)


class FakeProvenance:
    """Where the engine found an item: a page and a box."""

    # pylint: disable=too-few-public-methods
    # Reason: the object exists to model the engine's returned handle and nothing else.

    def __init__(self, page_no: int, box: FakeBoundingBox) -> None:
        """Record the location.

        Args:
            page_no: 1-based page.
            box: The item's box on that page.
        """
        self.page_no = page_no
        self.bbox = box


class FakeTextItem:
    """A text-bearing item: a label, its text and where it was found."""

    # pylint: disable=too-few-public-methods
    # Reason: the object exists to model the engine's returned handle and nothing else.

    def __init__(
        self,
        label: FakeDocItemLabel,
        text: str,
        box: FakeBoundingBox | None = None,
        page_no: int = 1,
    ) -> None:
        """Build an item.

        Args:
            label: The engine's label for it.
            text: Its text; empty for a picture.
            box: Where it sits, or ``None`` for an item with no provenance.
            page_no: 1-based page it sits on.
        """
        self.label = label
        self.text = text
        self.prov = [] if box is None else [FakeProvenance(page_no, box)]


class FakeTableCell:
    """One cell of a detected table, with the offsets the engine places it by."""

    # pylint: disable=too-few-public-methods
    # Reason: the object exists to model the engine's returned handle and nothing else.

    def __init__(self, text: str, row: int, column: int) -> None:
        """Record the cell.

        Args:
            text: The cell's text.
            row: The cell's row offset.
            column: The cell's column offset.
        """
        self.text = text
        self.start_row_offset_idx = row
        self.start_col_offset_idx = column
        self.row_span = 1
        self.col_span = 1


class FakeTableData:
    """A table's grid, as the engine reports it: a size plus offset-addressed cells."""

    # pylint: disable=too-few-public-methods
    # Reason: the object exists to model the engine's returned handle and nothing else.

    def __init__(
        self, num_rows: int, num_cols: int, rows: Sequence[Sequence[str]]
    ) -> None:
        """Build the table's data from a plain grid.

        Args:
            num_rows: Row count the engine reports.
            num_cols: Column count the engine reports.
            rows: The cell texts, by row and then by column.
        """
        self.num_rows = num_rows
        self.num_cols = num_cols
        self.table_cells = [
            FakeTableCell(text, row, column)
            for row, cells in enumerate(rows)
            for column, text in enumerate(cells)
        ]


class FakeTableItem:
    """A detected table: the ``table`` label, its data and where it was found."""

    # pylint: disable=too-few-public-methods
    # Reason: the object exists to model the engine's returned handle and nothing else.

    def __init__(
        self,
        rows: Sequence[Sequence[str]],
        box: FakeBoundingBox | None = None,
        page_no: int = 1,
    ) -> None:
        """Build a table item.

        Args:
            rows: The cell texts, by row and then by column.
            box: Where it sits, or ``None``.
            page_no: 1-based page it sits on.
        """
        self.label = FakeDocItemLabel.TABLE
        self.text = ""
        self.data = FakeTableData(len(rows), len(rows[0]) if rows else 0, rows)
        self.prov = [] if box is None else [FakeProvenance(page_no, box)]


class FakeDoclingDocument:
    """The engine's document model, in the subset this seam reads.

    Tables are document items like any other — the real engine yields them from
    ``iterate_items()`` and exposes the same objects again through ``document.tables`` — so this
    double keeps one item sequence and derives the table view from it. That is what makes the
    seam's "a table is not also a block" skip a tested path rather than an assumption.

    The exports are the double's own strings, in the order a reading model would produce them,
    while :meth:`iterate_items` hands the items back in the adversarial order the factory chose.
    That split is deliberate: the plan fixes the adversarial iteration order so a broken sort is
    falsifiable, and the export is a separate surface the seam must translate rather than reorder.
    """

    def __init__(
        self,
        items: Sequence[Any],
        text: str,
        markdown: str,
        width: float,
        height: float,
    ) -> None:
        """Build a document.

        Args:
            items: Every item, tables included, in the adversarial order the factory chose.
            text: The plain-text export.
            markdown: The Markdown export.
            width: Page width.
            height: Page height.
        """
        self.items = list(items)
        self.tables = [
            item for item in self.items if item.label == FakeDocItemLabel.TABLE
        ]
        self.pages = {1: _Page(FakeSize(width, height))}
        self._text = text
        self._markdown = markdown

    def iterate_items(self) -> Iterator[tuple[Any, int]]:
        """Yield ``(item, level)`` pairs, in the double's adversarial order."""
        for item in self.items:
            yield item, 1 if item.label == FakeDocItemLabel.SECTION_HEADER else 0

    def export_to_text(self) -> str:
        """Return the plain-text export."""
        return self._text

    def export_to_markdown(self) -> str:
        """Return the Markdown export."""
        return self._markdown


class _Page:
    """A page, holding nothing but its size."""

    # pylint: disable=too-few-public-methods
    # Reason: the object exists to model the engine's returned handle and nothing else.

    def __init__(self, size: FakeSize) -> None:
        """Record the page's size.

        Args:
            size: The page's size.
        """
        self.size = size


class FakeConversionResult:
    """What one conversion returns: a status, the engine's errors, and a document."""

    # pylint: disable=too-few-public-methods
    # Reason: the object exists to model the engine's returned handle and nothing else.

    def __init__(
        self,
        status: FakeConversionStatus,
        errors: Sequence[str],
        document: FakeDoclingDocument | None,
    ) -> None:
        """Record the outcome.

        Args:
            status: The conversion's status.
            errors: The engine's own error messages.
            document: The converted document, or ``None`` when there is none.
        """
        self.status = status
        self.errors = list(errors)
        self.document = document


#: A document factory: the frame of the file being converted, answered with a document.
DocumentFactory = Callable[[float, float], FakeDoclingDocument]


def _box(left: float, top: float, right: float, bottom: float) -> FakeBoundingBox:
    """Return a box, for the factories below."""
    return FakeBoundingBox(left, top, right, bottom)


def prepared_document(width: float, height: float) -> FakeDoclingDocument:
    """Return the document of the fixture the subplan calls ``ocr_prepared_text_and_table``.

    It holds a heading, one paragraph written as two body-text items, a caption, a picture with no
    text at all, and one 2x2 table — everything the extraction, the ordering, the builders and the
    table export need. The items are handed over in **adversarial order**: the caption comes first,
    then the table, then the second body line, then the first, then the heading.

    Args:
        width: The page's width, taken from the file.
        height: The page's height, taken from the file.

    Returns:
        The document.
    """
    tenth = height / 10
    items = [
        FakeTextItem(
            FakeDocItemLabel.CAPTION,
            "Source: internal ledger",
            _box(width * 0.05, tenth * 8, width * 0.85, tenth * 9),
        ),
        FakeTableItem(
            [["Region", "Revenue"], ["North", "120"]],
            _box(width * 0.05, tenth * 5, width * 0.60, tenth * 8),
        ),
        FakeTextItem(
            FakeDocItemLabel.TEXT,
            "across every region.",
            _box(width * 0.05, tenth * 4, width * 0.85, tenth * 5),
        ),
        FakeTextItem(
            FakeDocItemLabel.SECTION_HEADER,
            "Quarterly report",
            _box(width * 0.05, tenth * 1, width * 0.85, tenth * 2),
        ),
        FakeTextItem(
            FakeDocItemLabel.TEXT,
            "Revenue grew by twelve percent",
            _box(width * 0.05, tenth * 3, width * 0.85, tenth * 4),
        ),
        FakeTextItem(
            FakeDocItemLabel.PICTURE,
            "",
            _box(width * 0.70, tenth * 5, width * 0.95, tenth * 7),
        ),
    ]
    text = (
        "Quarterly report\n\n"
        "Revenue grew by twelve percent across every region.\n\n"
        "Region Revenue\nNorth 120\n\n"
        "Source: internal ledger"
    )
    markdown = (
        "# Quarterly report\n\n"
        "Revenue grew by twelve percent across every region.\n\n"
        "| Region | Revenue |\n| --- | --- |\n| North | 120 |\n\n"
        "Source: internal ledger"
    )
    return FakeDoclingDocument(items, text, markdown, width, height)


def empty_document(width: float, height: float) -> FakeDoclingDocument:
    """Return an image with no text in it at all.

    The conversion of this document **succeeds**: the emptiness is data about the input, which is
    why the processor reports ``EMPTY`` rather than failing.

    Args:
        width: The page's width, taken from the file.
        height: The page's height, taken from the file.

    Returns:
        The document.
    """
    return FakeDoclingDocument([], "", "", width, height)


def _frame(data: bytes) -> tuple[float, float]:
    """Return the page frame a PNG declares, in the units the engine would report.

    The document's *content* is the double's and says so; the *frame* is the file's, read from its
    own header, so the boxes the double reports describe the page that was really handed over.

    Args:
        data: The file's bytes.

    Returns:
        ``(width, height)``.

    Raises:
        ValueError: When the bytes are not a PNG. Raising is the point: a test that handed the
            double something else has a bug, and a silent default frame would hide it.
    """
    if not data.startswith(_PNG_SIGNATURE) or data[12:16] != b"IHDR":
        raise ValueError(
            "the Docling double reads a PNG frame and this file is not one"
        )
    width, height = struct.unpack(">II", data[16:24])
    return float(width), float(height)


class FakeDocling:
    """The in-memory Docling double.

    It is callable — that is the engine call — and it also carries ``__version__``, because the
    seam resolves the engine's version from the same namespace.

    Attributes:
        calls: Every image path the double was asked to convert, in order.
        status: The status every conversion reports.
        errors: The engine's own error messages every conversion reports.
        raises: An exception every conversion raises instead of returning, or ``None``.
        document: The factory that builds the document for the file's frame.
    """

    # pylint: disable=too-few-public-methods
    # Reason: the double is a callable handle with knobs; the seam calls it and reads its version,
    # and both of those are attributes of the engine's own surface.

    #: The version the engine namespace reports.
    __version__ = FAKE_ENGINE_VERSION

    def __init__(
        self,
        *,
        document: DocumentFactory = prepared_document,
        status: FakeConversionStatus = FakeConversionStatus.SUCCESS,
        errors: Sequence[str] = (),
        raises: Exception | None = None,
    ) -> None:
        """Build the double.

        Args:
            document: The factory producing the converted document.
            status: The status the conversion reports.
            errors: The engine's own error messages.
            raises: An exception to raise instead of converting.
        """
        self.calls: list[Path] = []
        self.document = document
        self.status = status
        self.errors = list(errors)
        self.raises = raises

    def __call__(self, image_path: Path, config: Any) -> FakeConversionResult:
        """Convert one image, the way the engine call does.

        Args:
            image_path: The prepared image.
            config: The engine configuration; recorded only through the call itself.

        Returns:
            The engine's own conversion result.

        Raises:
            Exception: Whatever :attr:`raises` holds, when one is configured.
        """
        del config  # the double answers with content, not with a pipeline
        path = Path(image_path)
        self.calls.append(path)
        if self.raises is not None:
            raise self.raises
        width, height = _frame(path.read_bytes())
        return FakeConversionResult(
            status=self.status,
            errors=self.errors,
            document=self.document(width, height),
        )
