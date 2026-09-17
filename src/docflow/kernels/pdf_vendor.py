"""The seam between K2's analysis and the PDF libraries that read the bytes.

K2 is split in two, and this module is the split. It declares **what the analysis
needs**, with no vendor named and nothing implemented:

- the **value types** a reader produces — page facts, words, document identity;
- the **`PdfVendor` protocol** the kernel asks through;
- the **typed failure** a reader raises instead of a traceback.

`docflow/kernels/pdf.py` holds the analysis — which shape a page has, whether its
text layer is invisible, whether a producer contradicts its own measurements — and
uses no PDF library at all. `docflow/adapters/pdf.py` holds the implementation over
`pymupdf` and the `pdftotext` binary, and imports this module.

Why the protocol lives in the kernels layer and not in `ports/`
--------------------------------------------------------------

`plans/README.md` §3 freezes the five port interfaces, so `PdfSource` cannot grow a
page-fact operation without re-opening `E04-01`'s gate. But the analysis genuinely
needs per-page measurements, and the port deliberately exposes none: *"no page-fact
or embedded-image surface"* is a documented `# TODO: [MVP]` target, not Stage 1
scope.

So this is a **second, inner seam**, and its direction is the mirror image of the
port's:

```text
ports/pdf.py     PdfSource      what a CALLER above Stage 1 depends on
      ^
adapters/pdf.py  PdfEngine      the adapter: implements PdfSource, owns the vendors
      |
      v  calls
kernels/pdf.py   analysis       the five operations, no vendor
      |
      v  asks through
kernels/pdf_vendor.py  PdfVendor  what the ANALYSIS needs from a reader
      ^
adapters/pdf.py  PyMuPdfVendor  the implementation over pymupdf + pdftotext
```

The consumer declares the interface and the implementer satisfies it — the same
inversion `PdfSource` uses one level up. Nothing in `ports/` changes, and the
dependency arrow keeps pointing down: the adapter imports the kernel, never the
reverse.

What a vendor reports, and what it must not
-------------------------------------------

Every method reports **measurements or bytes**. None of them names a shape, a
routing decision or a threshold: `page_facts` returns six numbers and a flag, and
what those mean for a page is `kernels/pdf.py`'s reading (`prd.md` FR-15).

A vendor that cannot serve a call raises :class:`PdfVendorError` carrying a
``Reason`` from the closed set of `kernel-cli.md` §5 rather than returning a
stand-in. There is no default implementation here and no module-level instance:
an unbound seam is a typed ``engine_unavailable``, never a substitute reader.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

from docflow.kernels.types import Reason

__all__: list[str] = [
    "CutDocument",
    "DocumentInfo",
    "PageFacts",
    "PdfVendor",
    "PdfVendorError",
    "Word",
]


@dataclasses.dataclass(frozen=True, slots=True)
class PageFacts:  # pylint: disable=too-many-instance-attributes
    """One page's raw measurements, before any shape is named.

    Every field is a measurement. None of them is a verdict: whether a page is
    ``text``, ``image``, ``mixed`` or ``blank`` is decided in `kernels/pdf.py`
    from these numbers plus the caller's threshold, and that decision is not
    duplicated here.

    The eight fields are the measurements rather than an accumulation of
    convenience members, which is why the attribute ceiling does not apply.
    Pooling them would hide which quantity a shape decision was taken from.

    Attributes:
        number: One-based page number.
        width_points: Page width in PDF user units.
        height_points: Page height in PDF user units.
        char_count: Characters the text layer yields.
        image_count: Images the page places.
        largest_image_fraction: Largest image's area over the page's area, or
            ``0.0`` when the page places no image.
        invisible_text: Whether the content stream sets the no-draw text render
            mode.
        effective_dpi: The resolution the page's pixels actually hold, or ``None``
            when the page cannot be measured that way.

    """

    number: int
    width_points: float
    height_points: float
    char_count: int
    image_count: int
    largest_image_fraction: float
    invisible_text: bool
    effective_dpi: float | None

    @property
    def is_blank(self) -> bool:
        """Whether the page carries neither text nor image.

        Both must be absent. A page with an image and no text is a *scan*, which
        is a different statement from a page that holds nothing at all.

        Returns:
            ``True`` when the page is empty of both.

        """
        return self.char_count == 0 and self.image_count == 0


@dataclasses.dataclass(frozen=True, slots=True)
class Word:
    """One word as a reader reported it, in PDF user units.

    The units are the reader's, not the caller's: converting them to the DPI a
    caller asked for is the kernel's job, because the requested resolution is a
    parameter of the *operation* rather than a property of the bytes.

    Attributes:
        text: The word's characters.
        x_min: Left edge in PDF points, origin top-left.
        y_min: Top edge in PDF points, origin top-left.
        x_max: Right edge in PDF points.
        y_max: Bottom edge in PDF points.

    """

    text: str
    x_min: float
    y_min: float
    x_max: float
    y_max: float


@dataclasses.dataclass(frozen=True, slots=True)
class DocumentInfo:
    """What a document is, as its own bytes report it.

    Declared metadata is **reported, never trusted**: ``producer`` and ``creator``
    are what the file claims, and the kernel compares them against the
    measurements rather than believing them. That comparison is why they travel.

    Attributes:
        page_count: How many pages the document has.
        page_sizes: Each page's ``[width, height]`` in PDF user units.
        producer: The declared producer, or ``"absent"``.
        creator: The declared creator, or ``"absent"``.
        format: The declared format, or ``"absent"``.
        encrypted: Whether the document refuses to open without a password.

    """

    page_count: int
    page_sizes: tuple[tuple[float, float], ...]
    producer: str
    creator: str
    format: str
    encrypted: bool


@dataclasses.dataclass(frozen=True, slots=True)
class CutDocument:
    """A document cut out of another one, with the sizes it came out with.

    The sizes travel because ``split``'s contract is that the result preserves the
    source's page boxes for the requested range, and the caller has to be able to
    assert that without re-opening the bytes. They are measured on the *result*,
    which is what makes the claim checkable.

    Attributes:
        data: The extracted document's bytes.
        page_sizes: Each result page's ``(width, height)`` in PDF user units, in
            the order the pages were requested.

    """

    data: bytes
    page_sizes: tuple[tuple[float, float], ...]


class PdfVendorError(Exception):
    """A reader that cannot serve a call, carrying the ``Reason`` that says why.

    An exception rather than a ``(None, Reason)`` pair, because these are raised
    from inside loops and across several frames — a return value would have to be
    checked at every one of them, and the check that gets forgotten is the one that
    lets a refusal be reported as a measurement.

    ``measurements`` and ``observed`` travel with the reason because a refusal
    frequently *is* the measurement: ``insufficient_effective_resolution`` is only
    diagnosable if the page's actual DPI comes with it.
    """

    def __init__(
        self,
        reason: Reason,
        measurements: Mapping[str, float] | None = None,
        observed: Mapping[str, object] | None = None,
    ) -> None:
        """Store the reason and whatever was measured before refusing.

        Args:
            reason: Why no value could be produced.
            measurements: The numeric measurements taken before the refusal.
            observed: The remaining observations taken before the refusal.

        """
        super().__init__(reason.message)
        self.reason = reason
        self.measurements: dict[str, float] = dict(measurements or {})
        self.observed: dict[str, object] = dict(observed or {})


@runtime_checkable
class PdfVendor(Protocol):
    """What K2's analysis needs from the libraries that read PDF bytes.

    Implemented by `docflow/adapters/pdf.py`. Every method either answers the
    measurement asked for or raises :class:`PdfVendorError`; none of them returns a
    stand-in, and none of them decides anything a threshold would settle.
    """

    def document_info(self, path: Path) -> DocumentInfo:
        """Report what the file is, without rendering.

        Args:
            path: The PDF to inspect.

        Returns:
            The document's identity as its bytes report it.

        Raises:
            PdfVendorError: When the file is absent, encrypted or not a PDF.

        """

    def page_facts(self, path: Path, page: int) -> PageFacts:
        """Measure one page.

        Args:
            path: The PDF to measure.
            page: One-based page number.

        Returns:
            The page's six measurements and its invisible-text flag.

        Raises:
            PdfVendorError: When the file cannot be opened or the page is outside
                it.

        """

    def words(self, path: Path, pages: Sequence[int]) -> Mapping[int, tuple[Word, ...]]:
        """Read the text layer's words, page by page, with their boxes.

        Args:
            path: The PDF to read.
            pages: The one-based page numbers to keep.

        Returns:
            A mapping of page number to that page's words. A requested page with
            no words is **absent** from the mapping rather than present with an
            empty tuple, so *the reader produced nothing for this page* stays
            distinguishable from *this page had no words*.

        Raises:
            PdfVendorError: When the reader binary is missing or fails.

        """

    def layout(self, path: Path, page: int) -> str:
        """Read one page's text with its physical layout preserved.

        Args:
            path: The PDF to read.
            page: One-based page number.

        Returns:
            The page's layout text, form feed included, exactly as the reader
            emitted it.

        Raises:
            PdfVendorError: When the reader binary is missing or fails.

        """

    def render_png(self, path: Path, pages: Sequence[int], dpi: int) -> bytes:
        """Render a page range as a PNG at the requested resolution.

        The vendor renders; it does **not** decide whether the request is
        satisfiable. The effective-resolution refusal belongs to the kernel, which
        measures it through :meth:`page_facts`.

        Args:
            path: The PDF to render.
            pages: The one-based page numbers to render, in order.
            dpi: The resolution to render at.

        Returns:
            The encoded PNG bytes. Several pages are stacked vertically into one
            image, because ``Bytes`` is one buffer.

        Raises:
            PdfVendorError: When the file cannot be opened or a page is outside it.

        """

    def split_pdf(self, path: Path, pages: Sequence[int]) -> CutDocument:
        """Cut a page range out of the file as a new document.

        Args:
            path: The PDF to split.
            pages: The one-based page numbers the result must contain, in order.

        Returns:
            The extracted bytes and the page sizes they carry.

        Raises:
            PdfVendorError: When the file cannot be opened or a page is outside it.

        """

    def engine_terms(self) -> Mapping[str, str]:
        """Report the page-description engine's revision, as a cache-key term.

        Returns:
            The engine's identity and version. The version is a key term because
            the same call against a different engine build is different work
            (`sad.md` §5).

        Raises:
            PdfVendorError: When the engine library is not installed.

        """

    def reader_terms(self) -> Mapping[str, str]:
        """Report the reader binary's identity, as a cache-key term.

        Returns:
            The binary's name and version.

        Raises:
            PdfVendorError: When the binary is not on PATH.

        """
