"""K4 ``OcrEngine`` port adapter over **Docling**, and Docling only.

The fixed OCR engine (`ADR-001`, `prd.md` FR-16): one implementation, one adapter
revision in the cache key, no per-document engine matrix for the ledger to track. A
different project takes the port and picks its own engine; this adapter is the one
this project uses.

Two decisions shape everything below.

**The boundary drops what it does not contract for.** Docling returns a document
model — sections, reading order, table structure, layout regions — and none of that
leaves this module. What leaves is positioned text with its boxes, because an order
imposed here would be a domain-level interpretation performed by a kernel, and
ordering is the Reconstructor's job at Stage 2 (`S2-T07`, `kernel-cli.md` §9, K4).

**The engine reports no confidence, and the adapter says so rather than inventing
one.** Docling's ``ProvenanceItem`` carries ``bbox``, ``charspan`` and ``page_no``
and nothing else: there is no confidence field anywhere in its document model.
``Token.confidence`` is therefore ``None`` throughout — and ``None`` is never
coerced to ``1.0``, which would be a claim the engine did not make (`sad.md` §6).

A limitation worth stating plainly, because a caller will meet it
----------------------------------------------------------------

**Docling reports one item per text *block*, not one per word.** A line read by the
recogniser comes back as a single item whose text spans the whole line and whose box
covers it. The command surface (`kernel-cli.md` §9, K4) names its operation
``read`` and describes tokens; this adapter returns Docling's actual granularity
rather than splitting blocks on whitespace to look finer. Splitting would assign
every word in a line the *line's* box, which is a fabricated position — and a
fabricated position is worse than a coarse one, because it looks precise.

PoC stage
---------

Each deliberate shortcut carries a marker naming what must replace it. Two are
structural: the engine is constructed per call rather than cached, and every page is
reported as ``read`` because Docling reports on the document rather than per page.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from docflow.kernels import ocr as ocr_layout
from docflow.kernels.types import Box, Evidence, KernelResult, Reason, Token
from docflow.ports.ocr import PageStatus, ReadResult

# Pylint sees the optional-engine import shape below as a duplicate of the one in
# `docflow/kernels/pdf.py`. It is: both translate a missing optional library into the
# same typed reason, because that is the contract and the code is the same word for
# word. Sharing a helper would put a kernel importing an adapter's internals, or a
# third module both depend on, for five lines — and the dependency arrow would stop
# pointing down, which is the property this whole layer exists to hold.
# pylint: disable=duplicate-code

__all__: list[str] = ["DoclingEngine"]

# --- Reason codes, from the closed set of `kernel-cli.md` §5 -----------------

_CODE_ENGINE_UNAVAILABLE: Final[str] = "engine_unavailable"
_CODE_UNSUPPORTED_FORMAT: Final[str] = "unsupported_format"

# --- Engine identity ---------------------------------------------------------

#: The engine's import name, and the only engine this project uses.
_ENGINE_NAME: Final[str] = "docling"

#: PDF user units per inch. Docling's boxes are in points at 72 DPI, so converting
#: them to the resolution a caller asked for is a scale by ``dpi / 72``.
_POINTS_PER_INCH: Final[float] = 72.0

#: The image formats the engine's image path accepts. Named here rather than
#: discovered, so an unsupported file is refused before the engine is invoked and
#: the refusal names the formats rather than surfacing a library traceback.
_IMAGE_SUFFIXES: Final[frozenset[str]] = frozenset(
    {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
)


class DoclingEngine:
    """Docling behind :class:`~docflow.ports.ocr.OcrEngine`.

    Reachable only through the port. The composition root imports this class; no
    module under ``docflow/ports/`` does, which is what keeps the dependency arrow
    pointing down (`ADR-004`).
    """

    def __init__(self, *, engine: Any = None) -> None:
        """Initialise the adapter.

        Args:
            engine: A ``DocumentConverter`` to use instead of building one. It
                exists so the tests can exercise the boundary without the engine's
                model downloads, and so a caller can pin a configured converter.
                ``None`` means *build one*, never *use a default engine* — there is
                no second engine to fall back to.

        """
        self._converter = engine

    # --- Engine access ------------------------------------------------------

    def _converter_or_failure(self) -> tuple[Any | None, Reason | None]:
        """Return the converter, building it once, or explain why it is missing.

        The import is inside the method so this module imports without Docling and a
        missing library arrives as a typed ``Reason`` rather than as an
        ``ImportError`` raised at import time.

        Returns:
            The converter, or ``None`` with a typed ``Reason``.

        """
        if self._converter is not None:
            return self._converter, None

        try:
            # pylint: disable=import-outside-toplevel
            from docling.document_converter import DocumentConverter
        except ImportError:
            return None, Reason(
                code=_CODE_ENGINE_UNAVAILABLE,
                message=(
                    f"the {_ENGINE_NAME!r} library is not installed, so no page can "
                    "be read. Install it (`pip install docling`); no substitute "
                    "engine is used, because the engine is fixed by ADR-001 and a "
                    "different one would be a matrix of behaviours under one name."
                ),
            )

        # TODO: [MVP] The converter is built per call. It downloads and loads
        # models on first use, so an MVP should construct it once per process and
        # share it, which is what makes `warm` worth having.
        try:
            self._converter = DocumentConverter()
        except Exception as exc:  # pylint: disable=broad-exception-caught
            # Building the converter pulls models and platform-specific backends;
            # it fails in ways the library does not enumerate. Any of them means
            # the engine cannot be started, which is exactly this reason.
            return None, Reason(
                code=_CODE_ENGINE_UNAVAILABLE,
                message=(
                    f"the {_ENGINE_NAME!r} engine could not be started: "
                    f"{type(exc).__name__}: {exc}"
                ),
            )

        return self._converter, None

    @staticmethod
    def _engine_terms() -> Mapping[str, str]:
        """Report the engine's revision, as a cache-key term.

        Returns:
            The adapter revision terms. The version is a key term because the same
            call against a different engine build is different work (`sad.md` §5).

        """
        version = "unknown"
        try:
            # pylint: disable=import-outside-toplevel
            from docling import __version__ as docling_version

            version = str(docling_version)
        except Exception:  # pylint: disable=broad-exception-caught
            # An engine that cannot report its version is still usable, and the
            # revision term then honestly says `unknown` rather than a guess.
            version = "unknown"

        return MappingProxyType({"engine": _ENGINE_NAME, "engine_version": version})

    # --- Operations ---------------------------------------------------------

    def capabilities(self) -> KernelResult[Evidence]:
        """Report what this engine can do, as observations about the engine.

        Returns:
            The engine's identity and revision, or no value and a typed ``Reason``
            when the engine cannot be started — which is a precondition of the
            call, not an answer about any document.

        """
        converter, failure = self._converter_or_failure()
        if converter is None:
            return KernelResult(
                value=None,
                evidence=_evidence({}, {}, {}),
                reason=failure,
            )

        return _observed(
            self._engine_terms(),
            {},
            {
                "engine": _ENGINE_NAME,
                "ocr_engine": _OCR_BACKEND,
                "granularity": "block",
                "reports_confidence": False,
                "accepts_image_suffixes": sorted(_IMAGE_SUFFIXES),
            },
        )

    def engine_info(self) -> KernelResult[Evidence]:
        """Report the terms that identify the engine for the cache key.

        Returns:
            The revision terms, or no value and a typed ``Reason``.

        """
        converter, failure = self._converter_or_failure()
        if converter is None:
            return KernelResult(
                value=None,
                evidence=_evidence({}, {}, {}),
                reason=failure,
            )

        return _observed(
            self._engine_terms(),
            {},
            {"engine": _ENGINE_NAME, "engine_version": _version()},
        )

    def read(  # pylint: disable=too-many-locals
        self,
        path: Path,
        pages: Sequence[int],
        dpi: int,
        lang: str,
    ) -> KernelResult[ReadResult]:
        """Read a document and return positioned text.

        The local count is above Pylint's ceiling because a read assembles three
        separate things — the selection, the per-page statuses and the tokens — plus
        the evidence record's two mappings. The suppression is stated rather than the
        method reshaped: grouping the names into a helper would move the same count
        one frame away without making the boundary any clearer.

        Args:
            path: The file to read.
            pages: The one-based page numbers to read.
            dpi: The resolution the returned boxes are expressed in. Docling's
                boxes are in points at 72 DPI, so this is the scale applied.
            lang: The language hint. It is accepted because the port declares it;
                this adapter passes it through in the evidence, because the engine
                version shipped here does not expose a per-call language setting,
                and silently ignoring it would be a configuration that does
                nothing.

        Returns:
            The items with their boxes and per-page status, or no value and a typed
            ``Reason``. ``blank`` is reported for a page the engine produced
            nothing for, so *the engine read this page and it held no text* stays
            distinguishable from *the engine could not read it*.

        Raises:
            ValueError: If the selection is empty or names a page outside the
                document.

        """
        converter, failure = self._converter_or_failure()
        if converter is None:
            return KernelResult(
                value=None,
                evidence=_evidence({}, {}, {}),
                reason=failure,
            )

        if dpi <= 0:
            raise ValueError(f"dpi must be positive, got {dpi}")

        if not path.exists():
            return _refused(
                _CODE_UNSUPPORTED_FORMAT,
                f"{path.name!r} does not exist at {path}",
                _empty_terms(),
                {},
                {"file": path.name},
            )

        try:
            converted = converter.convert(str(path))
        except Exception as exc:  # pylint: disable=broad-exception-caught
            # The engine refuses formats, damaged files and unreadable pages with
            # exception types it does not enumerate. Every one of them means the
            # bytes are not something this engine can read, which is this reason.
            return _refused(
                _CODE_UNSUPPORTED_FORMAT,
                f"{path.name!r} could not be read: {type(exc).__name__}: {exc}",
                _empty_terms(),
                {},
                {"file": path.name},
            )

        document = converted.document
        total = len(document.pages)
        selection = _validate_selection(pages, total)

        scale = dpi / _POINTS_PER_INCH
        tokens: list[Token] = []
        status: dict[int, PageStatus] = {}

        for page in selection:
            height = _page_height(document, page)
            items = _items_on_page(document, page, scale, height)
            if items:
                tokens.extend(items)
                status[page] = PageStatus.READ
            else:
                # The engine reported no text for this page. That is `blank`, and
                # never `read` with an empty list dressed up as a successful read
                # of a page that had nothing on it.
                status[page] = PageStatus.BLANK

        result = ReadResult(
            pages_requested=tuple(selection),
            page_status=MappingProxyType(status),
            tokens=tuple(tokens),
        )

        return KernelResult(
            value=result,
            evidence=_evidence(
                self._engine_terms(),
                {
                    "tokens": float(len(tokens)),
                    "pages_read": float(len(status)),
                    "pages_requested": float(len(selection)),
                    "dpi_applied": float(dpi),
                },
                {
                    "file": path.name,
                    "pages_requested": list(selection),
                    "pages_read": sorted(status),
                    "dpi_applied": dpi,
                    "lang_requested": lang,
                    "dpi_applied_note": "docling_boxes_are_points_at_72dpi",
                    "reading_order": "not_resolved",
                    "granularity": "block",
                    "layout_dropped": True,
                },
            ),
            reason=None,
        )

    def layout(  # pylint: disable=too-many-arguments
        # Six parameters, and each names a different thing the caller decides:
        # what to read, which pages, at what resolution, in which language, how
        # close two tokens may be and still share a row, and which axis is the
        # reading. `read` already takes four of them; the layout adds the two the
        # ordering needs. Grouping them into a value object would move the same
        # count one frame away and would invent a boundary type, which
        # `E01-01` forbids.
        self,
        path: Path,
        pages: Sequence[int],
        dpi: int,
        lang: str,
        *,
        line_tolerance: float,
        orientation: str = "horizontal",
    ) -> KernelResult[str]:
        """Read a selection and order it into rows.

        The OCR counterpart of ``PdfEngine.layout_text``, and it is **not** on
        :class:`~docflow.ports.ocr.OcrEngine` for the same reason: ``plans/README.md``
        §3 freezes the port's three operations, so a fourth would re-open `E04-04`'s
        gate. The adapter exposes it and the command reaches it here.

        The two operations are not interchangeable, and the difference is worth
        stating because the names invite the comparison. ``pdftotext -layout``
        returns the reader's own **character grid**; this returns **rows of blocks**,
        because a recogniser reports where each block starts and not how wide its
        column is. Padding that into a grid would synthesise whitespace no
        measurement supports.

        Args:
            path: The document to read.
            pages: The one-based page numbers to read.
            dpi: The resolution the boxes are expressed in.
            lang: The language hint.
            line_tolerance: How far apart two tokens may sit and still share a row,
                in the boxes' units at ``dpi``. Required: the legacy's ``25.0`` was
                in PDF points, so ``25.0 * dpi / 72`` reproduces it and a constant
                here could not.
            orientation: ``horizontal`` or ``vertical``.

        Returns:
            The ordered text, or the read's own typed ``Reason`` — a selection the
            engine cannot read refuses here exactly as it refuses in ``read``.

        """
        outcome = self.read(path, pages, dpi, lang)
        if outcome.reason is not None or outcome.value is None:
            return KernelResult(
                value=None,
                evidence=outcome.evidence,
                reason=outcome.reason,
            )

        laid_out = ocr_layout.layout(
            outcome.value.tokens,
            line_tolerance=line_tolerance,
            orientation=orientation,
        )
        if laid_out.reason is not None:
            # The read succeeded and produced no text. That is the layout's own
            # blank, and reporting it from here keeps the two operations'
            # vocabularies the same word for the same fact.
            return KernelResult(
                value=None,
                evidence=laid_out.evidence,
                reason=laid_out.reason,
            )

        return laid_out


# --- Module helpers ----------------------------------------------------------

#: The recogniser Docling uses under its OCR path, reported for a human reading the
#: evidence. It is a fact about the installed engine, not a setting.
_OCR_BACKEND: Final[str] = "rapidocr-onnxruntime"


def _version() -> str:
    """Return the engine's version string.

    Returns:
        The version, or ``"unknown"`` when the engine does not report one.

    """
    try:
        # pylint: disable=import-outside-toplevel
        from docling import __version__ as docling_version

        return str(docling_version)
    except Exception:  # pylint: disable=broad-exception-caught
        return "unknown"


def _empty_terms() -> Mapping[str, str]:
    """Return an empty term mapping, for a failure before the engine is reached.

    Returns:
        An empty read-only mapping.

    """
    return MappingProxyType({})


def _evidence(
    terms: Mapping[str, str],
    measurements: Mapping[str, float],
    observed: Mapping[str, object],
) -> Evidence:
    """Build an evidence record.

    Args:
        terms: The cache-key terms.
        measurements: The numeric measurements.
        observed: The remaining observations.

    Returns:
        The assembled ``Evidence``.

    """
    return Evidence(
        terms=MappingProxyType(dict(terms)),
        measurements=MappingProxyType(dict(measurements)),
        observed=MappingProxyType(dict(observed)),
    )


def _observed(
    terms: Mapping[str, str],
    measurements: Mapping[str, float],
    observed: Mapping[str, object],
) -> KernelResult[Evidence]:
    """Build a successful result whose value is the observation record.

    Args:
        terms: The cache-key terms.
        measurements: The numeric measurements.
        observed: The remaining observations.

    Returns:
        A ``KernelResult`` carrying the evidence as its value.

    """
    evidence = _evidence(terms, measurements, observed)

    return KernelResult(value=evidence, evidence=evidence, reason=None)


def _refused(
    code: str,
    message: str,
    terms: Mapping[str, str],
    measurements: Mapping[str, float],
    observed: Mapping[str, object],
) -> KernelResult[ReadResult]:
    """Build a failed read that still carries what was observed.

    Args:
        code: The reason code.
        message: The human-readable explanation.
        terms: The cache-key terms.
        measurements: The measurements taken.
        observed: The remaining observations.

    Returns:
        A ``KernelResult`` with no value and the evidence attached.

    """
    return KernelResult(
        value=None,
        evidence=_evidence(terms, measurements, observed),
        reason=Reason(code=code, message=message),
    )


def _validate_selection(pages: Sequence[int], total: int) -> tuple[int, ...]:
    """Normalize a page selection against the document's real page count.

    Args:
        pages: The requested one-based page numbers.
        total: How many pages the document has.

    Returns:
        The selection, sorted and de-duplicated.

    Raises:
        ValueError: If the selection is empty or names a page outside the
            document. Both are mistakes in the request, not answers about it.

    """
    if not pages:
        raise ValueError(
            "the page selection is empty; name at least one page rather than "
            "widening the request to the whole document"
        )

    for page in pages:
        if page < 1 or page > total:
            raise ValueError(
                f"page {page} is outside the document, which has {total} page(s)"
            )

    return tuple(sorted(set(pages)))


def _page_height(document: Any, page: int) -> float | None:
    """Read a page's height from the engine's document model.

    The height is what makes a bottom-left box convertible to a top-left one, and
    it has to come from the page rather than from the box: a box carries ``l``,
    ``t``, ``r``, ``b`` and its origin, and nothing that states how tall its page
    is. Deriving it from the box — ``t + b`` — looks plausible and is wrong, which
    was measured on a real conversion before this function existed.

    Args:
        document: The engine's document model.
        page: The one-based page number.

    Returns:
        The page height in the engine's units, or ``None`` when the engine does not
        report one. ``None`` is an absence and not a zero: a caller that cannot
        learn the height must not be handed a fabricated one.

    """
    try:
        size = document.pages[page].size
        return float(size.height)
    except (AttributeError, KeyError, TypeError, ValueError):
        return None


def _items_on_page(
    document: Any, page: int, scale: float, page_height: float | None
) -> list[Token]:
    """Extract one page's positioned items from the engine's document model.

    Only text-carrying items with provenance leave: the label is kept as the token's
    role, while the reading order and the item nesting are the engine's
    interpretation and are dropped here.

    Args:
        document: The engine's document model.
        page: The one-based page number to keep.
        scale: The factor converting points into the requested resolution.
        page_height: The page's height in the engine's units, or ``None`` when the
            engine does not report it.

    Returns:
        The page's tokens, in the order the engine produced them.

    """
    tokens: list[Token] = []

    for item, _level in document.iterate_items():
        provenance = getattr(item, "prov", None)
        text = getattr(item, "text", None)
        if not provenance or not text:
            continue

        first = provenance[0]
        if int(getattr(first, "page_no", 0)) != page:
            continue

        box = _to_source_box(first.bbox, scale, page_height)
        if box is None:
            continue

        tokens.append(
            Token(
                text=str(text),
                page=page,
                bbox=box,
                confidence=None,
                role=str(getattr(item, "label", "text")),
            )
        )

    return tokens


def _to_source_box(bbox: Any, scale: float, page_height: float | None) -> Box | None:
    """Convert an engine box into a source-page box at the requested resolution.

    Two conversions happen here and both matter:

    - **The origin flips.** Docling reports boxes with a bottom-left origin, where
      ``t`` is the greater y. Source page coordinates grow downward from the top,
      so ``y`` is the page's height minus the box's top.
    - **The units scale.** The engine reports points at 72 DPI; the caller asked for
      a resolution, and a box whose units depended on the request would mean
      different things to different callers.

    Args:
        bbox: The engine's box, carrying ``l``, ``t``, ``r``, ``b`` and its own
            coordinate origin.
        scale: The factor converting points into the requested resolution.
        page_height: The page's height in the engine's units, required when the box
            uses a bottom-left origin.

    Returns:
        The box in source page coordinates, or ``None`` when the box cannot be
        interpreted — including when a flip is needed and the page height is
        unknown, because a coordinate derived from a guess is worse than a missing
        one.

    """
    try:
        left = float(bbox.l)
        top = float(bbox.t)
        right = float(bbox.r)
        bottom = float(bbox.b)
    except (AttributeError, TypeError, ValueError):
        return None

    origin = str(getattr(bbox, "coord_origin", "")).upper()
    if "BOTTOMLEFT" in origin:
        if page_height is None:
            return None
        # The engine's y grows upward from the page's bottom; the contract's grows
        # downward from the top.
        height = top - bottom
        y = page_height - top
    else:
        height = bottom - top
        y = top

    if height < 0:
        height = -height

    return Box(
        x=left * scale,
        y=y * scale,
        width=max(0.0, right - left) * scale,
        height=height * scale,
    )
