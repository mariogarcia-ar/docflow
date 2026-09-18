"""K2 ``PdfSource`` port adapter over **PyMuPDF** and the **`pdftotext`** binary.

The one place in the PDF path where a vendor is named. Two things live here and
nothing else does:

- :class:`PyMuPdfVendor`, which satisfies `docflow/kernels/pdf_vendor.py` — it
  reads bytes and returns measurements, and it names ``pymupdf`` and ``pdftotext``
  for the whole system.
- :class:`PdfEngine`, which implements ``PdfSource`` by delegating the *analysis*
  to `docflow/kernels/pdf.py` and the *access* to the vendor above.

Why there are two objects rather than one
------------------------------------------

The split is the architecture's, not this file's preference. `sad.md` §1 lists
``pdftotext`` among the adapters, and `docflow/kernels/pdf.py` used to call it
directly — a vendor inside a kernel. The analysis that sits on top of the bytes is
*not* vendor work: which shape a page has, whether its text is invisible, whether a
producer contradicts its own measurements. Those are judgements with tests against
them and no library in them.

So the vendors moved down and the analysis stayed:

```text
PdfEngine(PdfSource)        this file — implements the caller's contract
      |
      +-- kernels/pdf.py            analysis: shapes, invisible text, contradictions
      |         |
      |         +-- PdfVendor      the seam (kernels/pdf_vendor.py)
      |
      +-- PyMuPdfVendor             access: pymupdf + pdftotext   <- the only vendors
```

One interface, one implementation, and no engine setting
--------------------------------------------------------

There is no ``engine=`` parameter and no ``--engine`` flag: `ADR-001` fixes the
engine, and a second reader would be a matrix of behaviours under one name.

``min_chars`` **is** a constructor argument, and it is required. The port declares
no threshold on purpose (`prd.md` FR-15, `ADR-009`), while the blank decision needs
one, so the value enters here rather than being invented below:

    engine = PdfEngine(min_chars=policy.min_chars)

`ADR-009` makes that value a registry asset read at Stage 3 with no override; until
``registry/policies/thresholds.yaml`` exists, the caller supplies it and the
adapter refuses to guess. **There is no default**: constructing without it is a
``TypeError``, not a substituted threshold, because a default here would be a
routing decision taken by whichever layer happened to be constructed first.

PoC stage
---------

Each deliberate shortcut carries a marker naming what must replace it. One is
structural: the reader binary is resolved per call rather than cached.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final
from xml.etree import ElementTree

from docflow.adapters.pdf_stable import stabilise_file_id
from docflow.kernels import pdf as analysis
from docflow.kernels.pdf_vendor import (
    CutDocument,
    DocumentInfo,
    PageFacts,
    PdfVendorError,
    Word,
)
from docflow.kernels.types import Bytes, Evidence, KernelResult, Reason, Token

# Pylint cannot see inside PyMuPDF: it is a compiled extension whose attributes
# are not introspectable, so `document.metadata`, `document.needs_pass` and
# `page.get_image_info` are reported as missing members while being real and
# documented. The suppression is stated once here rather than at each call site.
# pylint: disable=no-member

# Pylint reports `duplicate-code` against `adapters/ollama.py`: both translate an
# optional-library import into the same typed reason, word for word. That is the
# contract rather than a copy — the reason and its message are what a caller reads
# — and the alternative is a shared helper that a kernel would have to import from
# an adapter's internals.
# pylint: disable=duplicate-code

__all__: list[str] = ["PdfEngine", "PyMuPdfVendor"]

# --- Reason codes, from the closed set of `kernel-cli.md` §5 -----------------

_CODE_ENGINE_UNAVAILABLE: Final[str] = "engine_unavailable"
_CODE_UNSUPPORTED_FORMAT: Final[str] = "unsupported_format"
_CODE_ENCRYPTED: Final[str] = "encrypted"

# --- Vendor identity --------------------------------------------------------

#: The page-description engine. Imported lazily so this module imports without it
#: and a missing library becomes a typed ``Reason`` rather than an ``ImportError``
#: raised at import time.
_ENGINE_MODULE: Final[str] = "pymupdf"

#: The reader binary `sad.md` §1 names for the conversion path.
_READER_BINARY: Final[str] = "pdftotext"

#: The encoding the reader is asked to emit. Passed explicitly because the default
#: follows the host's locale, and two machines extracting the same file would then
#: disagree on the bytes without disagreeing on the document.
_READER_ENCODING: Final[str] = "UTF-8"

#: How long a reader invocation may take.
_READER_TIMEOUT_SECONDS: Final[int] = 300

#: Points per inch. PDF user units are points, so a page rendered at 72 DPI is
#: rendered at 1:1.
_POINTS_PER_INCH: Final[float] = 72.0

#: PDF text rendering mode 3 is *neither fill nor stroke*: the text occupies the
#: page and draws nothing. That, and only that, is what makes a text layer
#: invisible — not its colour, not its opacity.
_INVISIBLE_RENDER_MODE: Final[str] = "3"

#: A ``Tr`` operator preceded by its operand, e.g. ``3 Tr``. Scanned in the page's
#: own content stream, which is where the instruction actually lives.
_RENDER_MODE_PATTERN: Final[re.Pattern[bytes]] = re.compile(rb"(\d+(?:\.\d+)?)\s+Tr\b")


def _consecutive_runs(pages: Sequence[int]) -> list[tuple[int, ...]]:
    """Group a page selection into maximal runs of consecutive ascending pages.

    ``[1, 2, 3]`` is one run; ``[1, 2, 5, 6, 7]`` is two; ``[3, 1]`` is two runs of
    one page each, **in the order requested**. That last case is the reason this
    groups rather than sorts: the order of the selection is part of the request, and
    the engine's own range insertion would return the pages in document order.

    The grouping exists because the reader copies a page's resources per insertion:
    inserting a 59-page range as 59 single-page calls produced a file 5.2 times the
    size of the same pages inserted as one run.

    Args:
        pages: The one-based page numbers, in the order requested.

    Returns:
        The runs, in the order they must be inserted.

    """
    runs: list[tuple[int, ...]] = []
    for page in pages:
        if runs and page == runs[-1][-1] + 1:
            runs[-1] = (*runs[-1], page)
        else:
            runs.append((page,))
    return runs


class PyMuPdfVendor:
    """A :class:`~docflow.kernels.pdf_vendor.PdfVendor` over PyMuPDF and poppler.

    Stateless apart from the lazily imported engine module, and constructed with no
    settings: every value this reader uses arrives as a parameter from the kernel
    above it. That is what keeps a threshold from having anywhere to hide here.
    """

    def __init__(self) -> None:
        """Initialise the vendor with no engine bound yet."""
        self._engine: Any | None = None

    # --- Engine and reader access -------------------------------------------

    def engine(self) -> Any:
        """Return the page-description engine, importing it on first use.

        Returns:
            The engine module.

        Raises:
            PdfVendorError: When the library is not installed. Reported rather than
                raised as an ``ImportError``, because *the engine is missing* and
                *the code is broken* need different remediation.

        """
        if self._engine is not None:
            return self._engine

        try:
            import pymupdf  # pylint: disable=import-outside-toplevel
        except ImportError as exc:
            raise PdfVendorError(
                Reason(
                    code=_CODE_ENGINE_UNAVAILABLE,
                    message=(
                        f"the {_ENGINE_MODULE!r} library is not installed, so PDF "
                        f"pages cannot be read. Install it "
                        f"(`pip install {_ENGINE_MODULE}`); no substitute reader is "
                        "used, because a different engine reading the same bytes is "
                        "a different measurement reported as this one."
                    ),
                )
            ) from exc

        self._engine = pymupdf

        return self._engine

    @staticmethod
    def reader() -> str:
        """Locate the text-layer reader binary.

        Returns:
            The binary's path.

        Raises:
            PdfVendorError: When it is not on PATH. A missing binary is never
                substituted with another reader (`wbs.md` §9).

        """
        import shutil  # pylint: disable=import-outside-toplevel

        found = shutil.which(_READER_BINARY)
        if found is None:
            raise PdfVendorError(
                Reason(
                    code=_CODE_ENGINE_UNAVAILABLE,
                    message=(
                        f"the {_READER_BINARY!r} binary is not on PATH, so the text "
                        "layer cannot be read. It ships with poppler "
                        "(`brew install poppler` / `apt install poppler-utils`). No "
                        "substitute reader is used: a different extractor would "
                        "report different tokens under this engine's identity."
                    ),
                )
            )

        return found

    def _open(self, path: Path) -> Any:
        """Open a PDF, converting every failure into a typed refusal.

        Args:
            path: The file to open.

        Returns:
            The open document.

        Raises:
            PdfVendorError: When the file is absent, cannot be opened, or is
                encrypted.

        """
        engine = self.engine()

        if not path.exists():
            raise PdfVendorError(
                Reason(
                    code=_CODE_UNSUPPORTED_FORMAT,
                    message=f"{path.name!r} does not exist at {path}",
                )
            )

        try:
            document = engine.open(str(path))
        except Exception as exc:  # pylint: disable=broad-exception-caught
            # Broad because PyMuPDF raises several unrelated types from `open`
            # depending on how a file is malformed, and the two outcomes that
            # matter are "it opens" and "it does not".
            raise PdfVendorError(
                Reason(
                    code=_CODE_UNSUPPORTED_FORMAT,
                    message=(
                        f"{path.name!r} could not be opened as a PDF: "
                        f"{type(exc).__name__}: {exc}"
                    ),
                )
            ) from exc

        if document.needs_pass:
            document.close()
            raise PdfVendorError(
                Reason(
                    code=_CODE_ENCRYPTED,
                    message=(
                        f"{path.name!r} refuses to open without a password. The "
                        "document is reported as encrypted rather than as "
                        "unreadable, because the two need different remediation."
                    ),
                )
            )

        return document

    # --- The seam -----------------------------------------------------------

    def document_info(self, path: Path) -> DocumentInfo:
        """Report what the file is, without rendering anything.

        Args:
            path: The PDF to inspect.

        Returns:
            The page count, page sizes and declared metadata.

        Raises:
            PdfVendorError: When the file is absent, encrypted or not a PDF.

        """
        engine = self.engine()
        document = self._open(path)

        try:
            sizes = tuple(
                (float(page.rect.width), float(page.rect.height)) for page in document
            )
            metadata = dict(document.metadata or {})
            encrypted = bool(document.needs_pass)
        finally:
            document.close()

        _ = engine

        return DocumentInfo(
            page_count=len(sizes),
            page_sizes=sizes,
            producer=str(metadata.get("producer") or "absent"),
            creator=str(metadata.get("creator") or "absent"),
            format=str(metadata.get("format") or "absent"),
            encrypted=encrypted,
        )

    def page_facts(self, path: Path, page: int) -> PageFacts:
        """Measure one page.

        Args:
            path: The PDF to measure.
            page: One-based page number.

        Returns:
            The page's measurements.

        Raises:
            PdfVendorError: When the file cannot be opened or the page is outside
                it.

        """
        document = self._open(path)

        try:
            if page < 1 or page > document.page_count:
                raise PdfVendorError(
                    Reason(
                        code=_CODE_UNSUPPORTED_FORMAT,
                        message=(
                            f"page {page} is outside the document, which has "
                            f"{document.page_count} page(s)"
                        ),
                    )
                )
            page_object = document[page - 1]

            return PageFacts(
                number=page,
                width_points=float(page_object.rect.width),
                height_points=float(page_object.rect.height),
                char_count=len((page_object.get_text() or "").strip()),
                image_count=len(page_object.get_images(full=True)),
                largest_image_fraction=_largest_image_fraction(page_object),
                invisible_text=_invisible_text(page_object, document),
                effective_dpi=_measured_dpi(page_object, document),
            )
        finally:
            document.close()

    def words(self, path: Path, pages: Sequence[int]) -> Mapping[int, tuple[Word, ...]]:
        """Read the text layer's words, page by page, with their boxes.

        Args:
            path: The PDF to read.
            pages: The one-based page numbers to keep.

        Returns:
            Page number to that page's words, omitting pages that carried none.

        Raises:
            PdfVendorError: When the reader binary is missing or fails.

        """
        binary = self.reader()

        with tempfile.TemporaryDirectory(prefix="docflow_pdf_bbox_") as workdir:
            output = Path(workdir) / "words.xml"
            completed = subprocess.run(
                [binary, "-bbox", "-q", str(path), str(output)],
                capture_output=True,
                timeout=_READER_TIMEOUT_SECONDS,
                check=False,
            )

            if completed.returncode != 0:
                stderr = (completed.stderr or b"").decode("utf-8", "replace")[:200]
                raise PdfVendorError(
                    Reason(
                        code=_CODE_ENGINE_UNAVAILABLE,
                        message=(
                            f"the {_READER_BINARY!r} binary could not read "
                            f"{path.name!r}: exited {completed.returncode}: "
                            f"{stderr!r}"
                        ),
                    )
                )

            if not output.exists():
                # No file means the binary found no text at all. That is a
                # measurement about the document rather than a failure of the call.
                return {}

            raw = output.read_bytes()

        return _parse_bbox_xml(raw, set(pages))

    def layout(self, path: Path, page: int) -> str:
        """Read one page's text with its physical layout preserved.

        The page is read on its own with ``-f``/``-l`` rather than as part of a
        range, because a caller may ask for pages that are not contiguous.
        Composing the result from per-page reads is byte-identical to one range
        invocation — the tests assert that equivalence rather than trusting it,
        since a silent difference here would be a different document.

        Args:
            path: The PDF to read.
            page: One-based page number.

        Returns:
            The page's layout text, form feed included.

        Raises:
            PdfVendorError: When the reader binary is missing or fails.

        """
        binary = self.reader()
        completed = subprocess.run(
            [
                binary,
                "-layout",
                "-enc",
                _READER_ENCODING,
                "-q",
                "-f",
                str(page),
                "-l",
                str(page),
                str(path),
                "-",
            ],
            capture_output=True,
            timeout=_READER_TIMEOUT_SECONDS,
            check=False,
        )

        if completed.returncode != 0:
            stderr = (completed.stderr or b"").decode("utf-8", "replace")[:200]
            raise PdfVendorError(
                Reason(
                    code=_CODE_ENGINE_UNAVAILABLE,
                    message=(
                        f"the {_READER_BINARY!r} binary could not read "
                        f"{path.name!r}: exited {completed.returncode}: {stderr!r}"
                    ),
                )
            )

        return completed.stdout.decode(_READER_ENCODING, "replace")

    def render_png(self, path: Path, pages: Sequence[int], dpi: int) -> bytes:
        """Render a page range as a single PNG.

        Args:
            path: The PDF to render.
            pages: The one-based page numbers to render, in order.
            dpi: The resolution to render at.

        Returns:
            The encoded PNG bytes.

        Raises:
            PdfVendorError: When the file cannot be opened or a page is outside it.

        """
        engine = self.engine()
        document = self._open(path)

        try:
            images = [
                document[number - 1].get_pixmap(
                    matrix=engine.Matrix(
                        dpi / _POINTS_PER_INCH, dpi / _POINTS_PER_INCH
                    ),
                    colorspace=engine.csRGB,
                    alpha=False,
                )
                for number in pages
            ]
        finally:
            document.close()

        return _encode_png(engine, images)

    def split_pdf(self, path: Path, pages: Sequence[int]) -> CutDocument:
        """Cut a page range out of the file as a new document.

        **The selection is inserted in runs, not one page at a time.** A loop that
        called ``insert_pdf`` once per page copied the page's *resources* on every
        call, so a 59-page document came out at 3773437 bytes against 721297 for the
        same pages inserted as runs - a factor of 5.2, with the font objects
        duplicated page by page (1863 ``/Font`` references against 170). The pages
        and their content were identical either way; only the packaging was wrong.

        Grouping is safe because the runs preserve the requested order: the caller
        may legitimately name pages out of order, and ``[3, 1]`` becomes the runs
        ``(3,)`` and ``(1,)`` rather than one sorted span. Nothing is reordered,
        merged or de-duplicated here - the kernel has already refused a selection
        that repeats a page, and the runs are derived from the selection *as given*.

        Args:
            path: The PDF to split.
            pages: The one-based page numbers to keep, in order.

        Returns:
            The extracted bytes and the page sizes they carry.

        Raises:
            PdfVendorError: When the file cannot be opened or a page is outside it.

        """
        engine = self.engine()
        document = self._open(path)

        try:
            extracted = engine.open()
            for run in _consecutive_runs(pages):
                extracted.insert_pdf(
                    document, from_page=run[0] - 1, to_page=run[-1] - 1
                )

            payload = stabilise_file_id(extracted.tobytes(deflate=True, garbage=3))
            sizes = tuple(
                (float(page.rect.width), float(page.rect.height)) for page in extracted
            )
            extracted.close()
        finally:
            document.close()

        return CutDocument(data=payload, page_sizes=sizes)

    def engine_terms(self) -> Mapping[str, str]:
        """Report the page-description engine's revision.

        Returns:
            The engine's name and version.

        Raises:
            PdfVendorError: When the library is not installed.

        """
        engine = self.engine()
        version = getattr(engine, "version", None)
        if isinstance(version, (tuple, list)) and version:
            version = str(version[0])

        return MappingProxyType(
            {"engine": _ENGINE_MODULE, "engine_version": str(version or "unknown")}
        )

    def reader_terms(self) -> Mapping[str, str]:
        """Report the reader binary's revision.

        Returns:
            The binary's name and version.

        Raises:
            PdfVendorError: When the binary is not on PATH.

        """
        binary = self.reader()
        revision = "unknown"
        try:
            completed = subprocess.run(
                [binary, "-v"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            first_line = (completed.stdout or completed.stderr or "").splitlines()
            if first_line:
                revision = first_line[0].strip()
        except (OSError, subprocess.SubprocessError):
            revision = "unknown"

        return MappingProxyType({"reader": _READER_BINARY, "reader_revision": revision})


class PdfEngine:
    """``PdfSource`` over a :class:`PyMuPdfVendor` and the kernel's analysis.

    Reachable only through the port. The composition root imports this class; no
    module under ``docflow/ports/`` does (`ADR-004`).
    """

    def __init__(self, *, min_chars: int, vendor: Any = None) -> None:
        """Initialise the adapter.

        Args:
            min_chars: The caller's threshold for the text layer: below this many
                characters a page's text is not treated as its content. **Required,
                with no default** — the value is corpus policy (`ADR-009`) and a
                default here would be this adapter deciding what "blank" means.
            vendor: The reader to use instead of building one. It exists so the
                tests can exercise the boundary without the libraries, and so a
                caller can supply a configured reader. ``None`` means *build the
                documented one*; it never means *use a substitute*.

        """
        self._min_chars = min_chars
        self._vendor = vendor if vendor is not None else PyMuPdfVendor()

    # --- Operations ---------------------------------------------------------

    def probe(self, path: Path) -> KernelResult[Evidence]:
        """Report what the file is, without rendering anything.

        Args:
            path: The PDF to inspect.

        Returns:
            The page count, page sizes, declared metadata and encryption state, or
            no value and a typed ``Reason``.

        """
        return analysis.probe(path, vendor=self._vendor)

    def classify(self, path: Path, page: int) -> KernelResult[Evidence]:
        """Measure one page's shape and report how the measurement was taken.

        Args:
            path: The PDF to inspect.
            page: One-based page number.

        Returns:
            The measured shape and its observations, or no value and a typed
            ``Reason``.

        """
        return analysis.classify(
            path, page, min_chars=self._min_chars, vendor=self._vendor
        )

    def tokens(
        self, path: Path, pages: Sequence[int], dpi: int
    ) -> KernelResult[Sequence[Token]]:
        """Extract the text layer's positioned tokens for a page range.

        Args:
            path: The PDF to read.
            pages: The one-based page numbers to read.
            dpi: The resolution the boxes are expressed in.

        Returns:
            The tokens, or no value and a typed ``Reason``.

        """
        return analysis.extract_tokens(path, pages, dpi, vendor=self._vendor)

    def render(self, path: Path, pages: Sequence[int], dpi: int) -> KernelResult[Bytes]:
        """Render a page range as a bitmap at a requested resolution.

        Args:
            path: The PDF to render.
            pages: The one-based page numbers to render.
            dpi: The resolution requested by the caller.

        Returns:
            The rendered bitmap, or no value and a typed ``Reason``.

        """
        return analysis.render(path, pages, dpi, vendor=self._vendor)

    def split(self, path: Path, pages: Sequence[int]) -> KernelResult[Bytes]:
        """Cut a page range out of the file as a new document.

        Args:
            path: The PDF to split.
            pages: The one-based page numbers the result must contain.

        Returns:
            The extracted document, or no value and a typed ``Reason``.

        """
        return analysis.split(path, pages, vendor=self._vendor)

    # --- Operations outside the port ----------------------------------------

    def effective_dpi(self, path: Path, page: int) -> KernelResult[Evidence]:
        """Measure the resolution a page's embedded pixels actually hold.

        Kernel-only: `plans/README.md` §3 freezes ``PdfSource``, so this is not on
        the port. It is exposed because the caller that decides *whether to render*
        needs the number **before** asking for a render.

        Args:
            path: The PDF to measure.
            page: One-based page number.

        Returns:
            The measured resolution, or no value and a typed ``Reason``.

        """
        return analysis.effective_dpi(path, page, vendor=self._vendor)

    def layout_text(self, path: Path, pages: Sequence[int]) -> KernelResult[str]:
        """Extract the text layer with its physical layout preserved.

        Kernel-only for the same reason as :meth:`effective_dpi`.

        Args:
            path: The PDF to read.
            pages: The one-based page numbers to read, strictly ascending.

        Returns:
            The layout text, or no value and a typed ``Reason``.

        """
        return analysis.layout_text(path, pages, vendor=self._vendor)


# --- Vendor-side readers ----------------------------------------------------


def _largest_image_fraction(page: Any) -> float:
    """Measure how much of the page the largest placed image covers.

    Args:
        page: The page to measure.

    Returns:
        The largest image's area over the page's area, ``0.0`` when the page places
        no image. May exceed ``1.0``: an image can be placed partly off the page,
        and clamping the value would hide that.

    """
    infos = _image_infos(page)
    if not infos:
        return 0.0

    page_area = float(page.rect.width) * float(page.rect.height)
    if page_area <= 0:
        return 0.0

    largest = 0.0
    for info in infos:
        bbox = info.get("bbox")
        if not bbox:
            continue
        placed = _placed_size(bbox)
        if placed is None:
            continue
        largest = max(largest, placed[0] * placed[1])

    return largest / page_area


def _image_infos(page: Any) -> list[Mapping[str, Any]]:
    """List the images a page places, with their xrefs.

    ``xrefs=True`` is not optional. Without it the engine omits the ``xref`` key
    entirely, and a measurement that needs to reach the image's own bytes silently
    receives nothing instead of failing — which is how a resolution check ends up
    reporting that every page is fine.

    Args:
        page: The page to inspect.

    Returns:
        The placement records, or an empty list when the page places no image.

    """
    try:
        return list(page.get_image_info(xrefs=True))
    except Exception:  # pylint: disable=broad-exception-caught
        # Broad for a specific reason: PyMuPDF raises several unrelated exception
        # types here depending on how a page's resources are malformed, and the two
        # outcomes that matter are "the page places an image" and "it does not".
        return []


def _placed_size(bbox: Sequence[float]) -> tuple[float, float] | None:
    """Measure the width and height a placement record describes.

    Args:
        bbox: The placement's rectangle, as ``(x0, y0, x1, y1)``.

    Returns:
        The ``(width, height)`` pair, or ``None`` for a degenerate rectangle.

    """
    width = abs(float(bbox[2]) - float(bbox[0]))
    height = abs(float(bbox[3]) - float(bbox[1]))

    if width <= 0 or height <= 0:
        return None

    return width, height


def _invisible_text(page: Any, document: Any) -> bool:
    """Report whether the page's text layer is invisible.

    The instruction is read from the page's own content stream. It has to be: the
    engine's text extraction returns invisible text as ordinary text, so measuring
    the extracted characters cannot distinguish a visible layer from a hidden one.
    The difference is not in the characters but in the operator that draws them.

    Args:
        page: The page to inspect.
        document: The document the page belongs to.

    Returns:
        ``True`` when the content stream selects the no-draw text render mode.

    """
    try:
        xrefs = page.get_contents()
        stream = b"".join(document.xref_stream(xref) or b"" for xref in xrefs)
    except Exception:  # pylint: disable=broad-exception-caught
        # Broad for the same reason as `_image_infos`: an object stream that cannot
        # be read is *no evidence of a hidden layer*, which is a valid measurement.
        return False

    return any(
        match.group(1) == _INVISIBLE_RENDER_MODE.encode()
        for match in _RENDER_MODE_PATTERN.finditer(stream)
    )


def _measured_dpi(page: Any, document: Any) -> float | None:
    """Measure the resolution the page's embedded pixels actually hold.

    The number comes from the embedded image's own pixel dimensions divided by the
    area of the page it is placed in — never from the request and never from the
    file's metadata, both of which describe what someone *intended* rather than
    what the bytes contain.

    Args:
        page: The page to measure.
        document: The document the page belongs to. Accepted because the
            measurement is conceptually about stored bytes, and a caller holding
            only a page should not have to know that this engine happens to expose
            the pixel dimensions on the placement record.

    Returns:
        The effective DPI, or ``None`` when the page places no measurable image. A
        ``None`` is not a zero: it states that this measurement does not apply.

    """
    del document  # the placement record carries the pixel dimensions

    infos = _image_infos(page)
    if not infos:
        return None

    measured: list[float] = []
    for info in infos:
        bbox = info.get("bbox")
        if not bbox:
            continue

        placed = _placed_size(bbox)
        if placed is None:
            continue

        pixel_width = float(info.get("width") or 0)
        pixel_height = float(info.get("height") or 0)
        if pixel_width <= 0 or pixel_height <= 0:
            continue

        width, height = placed
        horizontal = pixel_width / (width / _POINTS_PER_INCH)
        vertical = pixel_height / (height / _POINTS_PER_INCH)

        # The smaller of the two per placement: a page stretched on one axis is
        # only as legible as its weaker dimension, and reporting the larger would
        # flatter the source.
        measured.append(min(horizontal, vertical))

    if not measured:
        return None

    # The worst placement on the page: a render is only as faithful as the
    # weakest image it has to reproduce.
    return round(min(measured), 2)


def _local_name(tag: str) -> str:
    """Strip an XML namespace from an element tag.

    The reader's ``-bbox`` output declares ``xmlns="http://www.w3.org/1999/xhtml"``,
    so every tag arrives as ``{http://www.w3.org/1999/xhtml}page`` and matching on
    the bare word finds nothing at all. Matching on the local name keeps the parse
    working whether or not the reader ever drops that declaration.

    Args:
        tag: The element's tag as the parser reports it.

    Returns:
        The tag with any ``{namespace}`` prefix removed.

    """
    return tag.rpartition("}")[2]


def _parse_bbox_xml(raw: bytes, wanted: set[int]) -> dict[int, tuple[Word, ...]]:
    """Parse the reader's XHTML into words per page.

    Args:
        raw: The XHTML bytes the binary wrote.
        wanted: The page numbers to keep.

    Returns:
        A mapping of page number to that page's words, for the requested pages
        that carried any.

    """
    root = ElementTree.fromstring(raw)

    pages = [node for node in root.iter() if _local_name(node.tag) == "page"]

    result: dict[int, tuple[Word, ...]] = {}
    for page_number, page in enumerate(pages, start=1):
        if page_number not in wanted:
            continue

        words = tuple(
            Word(
                text=element.text or "",
                x_min=float(element.get("xMin", "0")),
                y_min=float(element.get("yMin", "0")),
                x_max=float(element.get("xMax", "0")),
                y_max=float(element.get("yMax", "0")),
            )
            for element in page.iter()
            if _local_name(element.tag) == "word"
        )
        if words:
            result[page_number] = words

    return result


def _encode_png(engine: Any, images: Sequence[Any]) -> bytes:
    """Encode rendered pages as a single PNG.

    Args:
        engine: The engine module.
        images: The rendered pixmaps, one per page.

    Returns:
        The encoded PNG bytes. A single page is encoded directly; several pages are
        stacked vertically into one image, because ``Bytes`` is one buffer and
        inventing a container format here would be a second contract.

    """
    if len(images) == 1:
        return bytes(images[0].tobytes("png"))

    total_height = sum(image.height for image in images)
    width = max(image.width for image in images)
    canvas = engine.Pixmap(engine.csRGB, engine.IRect(0, 0, width, total_height))
    canvas.clear_with(255)

    # Each pixmap is *moved* to its row before being copied; the copy target is then
    # read back off the pixmap, so the two cannot disagree.
    #
    # `Pixmap.copy(source, target)` does not place the source at `target`: composing
    # `IRect(0, offset, w, offset+h)` copied only the first page and left the rest
    # white. Measured on a three-page selection, the inks per vertical third were
    # `[433731, 0, 0]` against `[433731, 63783, 33474]` - a descriptor announcing
    # `pages_rendered: [1, 2, 3]` over two blank rows.
    offset = 0
    for image in images:
        image.set_origin(0, offset)
        canvas.copy(image, image.irect)
        offset += image.height

    return bytes(canvas.tobytes("png"))
