"""K2 ``kernel.pdf`` — probe, classify, extract tokens, render, split.

The PDF *analysis*: which of the four shapes a page has, whether its text layer is
invisible, whether a declared producer contradicts what the page measures. Those are
judgements with tests against them and no vendor in them (`sad.md` §3, `E04-02` /
``S1-T12``).

**The vendors are not imported here, not named here, and not callable from here.**
``pymupdf`` and the ``pdftotext`` binary live in `docflow/adapters/pdf.py`, which
reaches this module through the :class:`~docflow.kernels.pdf_vendor.PdfVendor` seam
declared in `docflow/kernels/pdf_vendor.py`. `sad.md` §1 lists ``pdftotext`` among
the **adapters**, and until this split it was called from here — a vendor inside a
kernel.

Two silent failures shape the code below, and both are failures of *honesty about
what the bytes say* rather than failures of computation.

**A scan with a stale invisible OCR layer behind it reads as a text PDF**, so the
page is never converted and the text a person can see is never read. The trap is
sharp: the engine's ``page.get_text()`` **returns that invisible text as ordinary
text**, so the naive measurement reports a text page and is wrong. The layer is
detected as what it is — a rendering instruction, ``Tr 3``, meaning *draw nothing*
— and reported as evidence rather than used as a verdict.

**A 150 DPI scan rendered at 300 is reported as satisfying 300** — larger and no
more legible. ``render`` measures the effective resolution from the **embedded
pixels** and refuses a request the source cannot honour, producing no file at all.
It never upscales.

Why the seam is a parameter rather than an import
--------------------------------------------------

A kernel may not import an adapter — the arrow points down, and
`tests/kernels/test_store.py` enforces that for the layer. So the vendor arrives as
an argument. That is the same inversion ``PdfSource`` uses one level up: the
consumer declares the interface and the implementer satisfies it.

Every operation therefore takes ``vendor`` as a keyword-only argument with **no
default**. A default would have to name a concrete reader, which is the import this
module exists not to have, and an unbound seam must be a typed failure rather than a
substitute.

What this module never does
---------------------------

- **No threshold constant.** What counts as too low a resolution is the
  *caller's* value (`prd.md` FR-15). ``classify`` compares against a
  ``min_chars`` the caller passes; nothing here decides that a page is unusable.
- **No routing decision.** ``classify`` returns a measurement — ``text``,
  ``image``, ``mixed`` or ``blank`` — never *"convert this"* or *"route to OCR"*.
  Routing a stale-layer page away from conversion is Diagnosis's decision at
  Stage 2 (`S2-T04`, `kernel-cli.md` §3 guardrail 2).
- **No substitute reader.** A missing ``pdftotext`` is a typed ``Reason``, never
  a silent fall back to a different extractor (`wbs.md` §9).
- **No domain noun.** **Never** (`kernel-cli.md` §10).

PoC stage
---------

Every deliberate shortcut carries a marker naming what must replace it. Page facts
beyond classification and embedded-image extraction are documented targets rather
than Stage 1 scope, and the classification measures text *presence* rather than text
*coverage*.

Values transcribed from the legacy PoC (`legacy/`, analysed but deliberately not
copied) are noted where they inform a default; the code here is written from the
specification, not ported.
"""

# pylint: disable=too-many-lines
# The module carries five operations, the shape decision, the result assembly and the
# reason vocabulary. Splitting it to satisfy a line budget would separate the
# resolution measurement from the refusal that depends on it, which is the pairing
# this module exists to keep together.

# pylint: disable=too-many-locals
# `classify` and `extract_tokens` assemble an evidence record whose terms,
# measurements and observations are each several values. The alternative is building
# the record in a helper that returns a mapping, which moves the same count one frame
# away without making anything clearer.

from __future__ import annotations

import contextlib
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from docflow.kernels.pdf_vendor import PageFacts, PdfVendor, PdfVendorError, Word
from docflow.kernels.types import Box, Bytes, Evidence, KernelResult, Reason, Token

__all__: list[str] = [
    "PAGE_SHAPES",
    "classify",
    "effective_dpi",
    "extract_tokens",
    "layout_text",
    "probe",
    "render",
    "split",
]

#: The four page shapes ``classify`` may report. ``blank`` is a shape, and it is
#: not the same statement as *"a page with no text"* (`kernel-cli.md` §5).
PAGE_SHAPES: Final[tuple[str, ...]] = ("text", "image", "mixed", "blank")

# --- Reason codes, from the closed set of `kernel-cli.md` §5 -----------------

_CODE_INSUFFICIENT_RESOLUTION: Final[str] = "insufficient_effective_resolution"
_CODE_BLANK_PAGE: Final[str] = "blank_page"
_CODE_ENCRYPTED: Final[str] = "encrypted"
_CODE_UNSUPPORTED_FORMAT: Final[str] = "unsupported_format"
_CODE_ENGINE_UNAVAILABLE: Final[str] = "engine_unavailable"

# --- Points, and the invisible-text instruction -------------------------------
#
# The kernel keeps these two because it is the layer that gives them meaning. The
# vendor scans for the operator; the analysis is what decides it means *invisible*.

#: Points per inch. PDF user units are points, so a page rendered at 72 DPI is
#: rendered at 1:1. The reader's coordinates arrive in points and the caller asks
#: for a DPI, so the conversion is part of the *contract* rather than of the
#: reading.
POINTS_PER_INCH: Final[float] = 72.0

#: PDF text rendering mode 3 is *neither fill nor stroke*: the text occupies the
#: page and draws nothing. That, and only that, is what makes a text layer
#: invisible — not its colour, not its opacity.
INVISIBLE_RENDER_MODE: Final[str] = "3"

#: A ``Tr`` operator preceded by its operand, e.g. ``3 Tr``.
RENDER_MODE_PATTERN: Final[re.Pattern[bytes]] = re.compile(rb"(\d+(?:\.\d+)?)\s+Tr\b")

#: Producer strings that a scanned document carries when a capture device or a
#: scan pipeline wrote it. Used only to report a *contradiction*, never to decide
#: the shape: the measurement comes from the pixels, and the metadata is the thing
#: being checked against it.
_SCAN_PRODUCER_MARKERS: Final[tuple[str, ...]] = (
    "scan",
    "scanner",
    "camscanner",
    "adobe scan",
    "hp scan",
    "epson",
    "canon",
    "xerox",
    "ricoh",
    "brother",
    "kyocera",
)


# --- Argument validation (usage errors, exit 4 at the CLI boundary) ----------


def _validate_page(page: int, page_count: int) -> None:
    """Reject a page number outside the document.

    Args:
        page: The one-based page number requested.
        page_count: How many pages the document has.

    Raises:
        ValueError: If ``page`` is not a page of this document.

    """
    if page < 1 or page > page_count:
        raise ValueError(
            f"page {page} is outside the document, which has {page_count} page(s) "
            f"(valid: 1..{page_count})"
        )


def _validate_selection(pages: Sequence[int], page_count: int) -> tuple[int, ...]:
    """Normalize a page selection into a sorted, de-duplicated, valid tuple.

    Args:
        pages: The requested one-based page numbers.
        page_count: How many pages the document has.

    Returns:
        The selection in ascending order, with duplicates removed.

    Raises:
        ValueError: If the selection is empty or names a page outside the
            document. An empty selection is refused rather than silently widened
            to the whole document, because widening it would perform work the
            caller did not ask for.

    """
    if not pages:
        raise ValueError(
            "the page selection is empty; name at least one page. An empty "
            "selection is refused rather than widened to the whole document, "
            "because doing more than asked is not a helpful default."
        )

    for page in pages:
        _validate_page(page, page_count)

    return tuple(sorted(set(pages)))


def _producer_contradiction(producer: str, creator: str, facts: PageFacts) -> bool:
    """Report whether the declaring metadata contradicts what the page measures.

    A scan tool names itself in the producer and the creator. When it does, and
    the page nevertheless carries a text layer, the metadata and the measurement
    disagree — which is worth reporting rather than resolving, because resolving it
    means choosing which of the two to believe.

    Args:
        producer: The document's declared producer.
        creator: The document's declared creator.
        facts: The page's measurements.

    Returns:
        ``True`` when the declared producer looks like a capture device and the
        page carries text anyway.

    """
    declared = f"{producer} {creator}".lower()
    looks_like_capture = any(marker in declared for marker in _SCAN_PRODUCER_MARKERS)

    return looks_like_capture and facts.char_count > 0


def _shape_of(facts: PageFacts, min_chars: int) -> str:
    """Name the shape the measurements describe.

    Four outcomes, and ``blank`` is one of them. A page that carries an image and
    too little text to judge is an *image* page — a scan — rather than a text page
    with a short line on it, which is the distinction that keeps a scanned invoice
    from being read as a text one.

    **Invisible text does not count as text.** That is the whole of row 3 of the
    silent-failure matrix: a stale hidden layer is characters that draw nothing, so
    the page's *visible* content is whatever else is on it. Counting those
    characters would report such a page as ``text`` or ``mixed``, the document
    would never be converted, and the content a person can see would never be read —
    which is precisely the failure the layer's detection exists to prevent.

    Args:
        facts: The page's measurements.
        min_chars: The caller's threshold: below this many characters the text
            layer is not treated as the page's content. It is a parameter because
            deciding it is the caller's job (`prd.md` FR-15).

    Returns:
        One of :data:`PAGE_SHAPES`.

    """
    if facts.is_blank:
        return "blank"

    visible_text = not facts.invisible_text
    has_text = visible_text and facts.char_count >= min_chars
    has_image = facts.image_count > 0

    if has_text and has_image:
        return "mixed"
    if has_text:
        return "text"
    if has_image:
        return "image"

    # Neither a usable visible text layer nor an image, yet not empty: characters
    # exist but below the caller's threshold, or they draw nothing. Reported as an
    # image page because the pixels are all there is to read.
    return "image"


def _blank_page_reason(name: str, number: int) -> Reason:
    """Build the reason a blank page produces.

    Args:
        name: The file's name, for the message.
        number: The one-based page number.

    Returns:
        The ``blank_page`` reason.

    """
    return Reason(
        code=_CODE_BLANK_PAGE,
        message=(
            f"page {number} of {name!r} carries no text and no image, so it has "
            "no content to describe. This is a statement about the page, not "
            "about its text layer: a page that holds an image is a scan, which "
            "is a different shape."
        ),
    )


def _failure(
    reason: Reason,
    terms: Mapping[str, str],
    measurements: Mapping[str, float],
    observed: Mapping[str, object],
) -> KernelResult[Any]:
    """Build a failed result that still carries what was measured.

    A failure with no evidence cannot be diagnosed, and the measurements taken
    before the refusal are frequently the reason the caller set the threshold
    where it did.

    Args:
        reason: Why no value was produced.
        terms: The cache-key terms.
        measurements: The measurements taken.
        observed: The remaining observations.

    Returns:
        A ``KernelResult`` with no value and the evidence attached.

    """
    return KernelResult(
        value=None,
        evidence=_evidence(terms, measurements, observed),
        reason=reason,
    )


def _observed(
    terms: Mapping[str, str],
    measurements: Mapping[str, float],
    observed: Mapping[str, object],
) -> KernelResult[Evidence]:
    """Build a successful result whose value **is** the observation record.

    Three operations here — ``probe``, ``classify`` and ``effective_dpi`` —
    produce measurements rather than content, so their value is an ``Evidence``.
    The same record is then also the call's evidence, and it is the same object
    rather than a copy: the contract requires every call to report what it
    observed, and for these three that report *is* the answer, not a description
    of one.

    Args:
        terms: The cache-key terms.
        measurements: The numeric measurements.
        observed: The remaining observations.

    Returns:
        A ``KernelResult`` carrying the evidence as its value.

    """
    evidence = _evidence(terms, measurements, observed)

    return KernelResult(value=evidence, evidence=evidence, reason=None)


def _evidence(
    terms: Mapping[str, str],
    measurements: Mapping[str, float],
    observed: Mapping[str, object],
) -> Evidence:
    """Build the evidence record for one call.

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


def _refused(
    vendor_error: PdfVendorError, terms: Mapping[str, str]
) -> KernelResult[Any]:
    """Turn a reader's refusal into a failed result, keeping its measurements.

    A refusal frequently *is* the measurement — ``insufficient_effective_resolution``
    is only diagnosable if the page's actual DPI comes with it — so the evidence the
    reader attached travels with the reason rather than being dropped.

    Args:
        vendor_error: The refusal, with whatever was measured before it.
        terms: The cache-key terms, which may be empty for a refusal that happened
            before the reader's identity could be asked for. Empty is the honest
            value there, not a placeholder.

    Returns:
        A ``KernelResult`` carrying the reason and the partial evidence.

    """
    return _failure(
        vendor_error.reason,
        terms,
        vendor_error.measurements,
        vendor_error.observed,
    )


def _identity_terms(vendor: PdfVendor) -> Mapping[str, str]:
    """Report the reader's identity terms, or nothing when it cannot answer.

    A cache-key term must be a non-empty string, so an unavailable reader
    contributes **nothing** rather than an ``"unknown"`` placeholder — a placeholder
    would key two genuinely different engines the same way, which is the failure the
    model-revision term exists to prevent (`sad.md` §5).

    Args:
        vendor: The reader.

    Returns:
        The engine and reader revision terms, or an empty mapping.

    """
    terms: dict[str, str] = {}
    with contextlib.suppress(PdfVendorError):
        terms |= dict(vendor.engine_terms())
    with contextlib.suppress(PdfVendorError):
        terms |= dict(vendor.reader_terms())

    return MappingProxyType(terms)


# --- The five operations -----------------------------------------------------


def probe(path: Path, *, vendor: PdfVendor) -> KernelResult[Evidence]:
    """Report what the file is, without rendering anything.

    Args:
        path: The PDF to inspect.
        vendor: The reader.

    Returns:
        The page count, page sizes, declared metadata and encryption state, or no
        value and a typed ``Reason``. A file that cannot be opened reports
        ``encrypted`` or ``unsupported_format``: the observations are never
        returned empty as a stand-in for a successful probe.

    """
    terms = _identity_terms(vendor)

    try:
        info = vendor.document_info(path)
    except PdfVendorError as refused:
        return _refused(refused, terms)

    return _observed(
        terms,
        {"page_count": float(info.page_count)},
        {
            "file": path.name,
            "page_sizes": [list(size) for size in info.page_sizes],
            "producer": info.producer,
            "creator": info.creator,
            "format": info.format,
            "encrypted": info.encrypted,
        },
    )


def classify(
    path: Path, page: int, *, min_chars: int, vendor: PdfVendor
) -> KernelResult[Evidence]:
    """Measure one page's shape and report how the measurement was taken.

    Args:
        path: The PDF to inspect.
        page: One-based page number.
        min_chars: The caller's threshold for the text layer. Required, with no
            default: a default would be this kernel deciding what *blank* means
            (`prd.md` FR-15).
        vendor: The reader.

    Returns:
        The measured shape and its observations, or no value and a typed
        ``Reason``. A scan carrying an invisible text layer is reported as an image
        page **with** ``invisible_text`` set and any contradicting producer metadata
        present, so the hidden layer is evidence rather than a silent reading of the
        page as text. A page carrying no content at all returns a ``blank_page``
        reason: *blank* is a shape, and it is not the same statement as *a page with
        no text*.

    Raises:
        ValueError: If ``page`` is outside the document. A page number is a usage
            error rather than a property of the bytes, so it does not become a
            ``Reason`` — and it is checked against the document's real page count
            rather than assumed.

    """
    terms = _identity_terms(vendor)

    try:
        info = vendor.document_info(path)
        _validate_page(page, info.page_count)
        facts = vendor.page_facts(path, page)
    except PdfVendorError as refused:
        return _refused(refused, terms)

    shape = _shape_of(facts, min_chars)
    contradiction = _producer_contradiction(info.producer, info.creator, facts)

    measurements: dict[str, float] = {
        "char_count": float(facts.char_count),
        "image_count": float(facts.image_count),
        "largest_image_fraction": round(facts.largest_image_fraction, 6),
    }
    if facts.effective_dpi is not None:
        measurements["effective_dpi"] = facts.effective_dpi

    observed: dict[str, object] = {
        "file": path.name,
        "page": facts.number,
        "page_size": [facts.width_points, facts.height_points],
        "shape": shape,
        "invisible_text": facts.invisible_text,
        "producer": info.producer,
        "creator": info.creator,
        "producer_contradiction": contradiction,
        "min_chars_applied": min_chars,
    }

    # The blank decision is taken in exactly one place — `_shape_of` — and read
    # back here. Two independent tests for the same fact is how they come to
    # disagree, and the shape is already in the observations so a failed result
    # still reports what was measured.
    if shape == "blank":
        return _failure(
            _blank_page_reason(path.name, facts.number),
            terms,
            measurements,
            observed,
        )

    return _observed(terms, measurements, observed)


def effective_dpi(
    path: Path, page: int, *, vendor: PdfVendor
) -> KernelResult[Evidence]:
    """Measure the resolution a page's embedded pixels actually hold.

    A separate operation from ``render`` because this is the number the caller
    needs *before* asking for a render: it is what makes an unsatisfiable request
    predictable rather than surprising. It is **not** on ``PdfSource`` — the port is
    frozen by `plans/README.md` §3 — and it is exposed because the caller that
    decides whether to render needs it.

    Args:
        path: The PDF to measure.
        page: One-based page number.
        vendor: The reader.

    Returns:
        The measured resolution, or no value and a typed ``Reason``. A page that
        places no image has no effective DPI to report, and that absence is stated
        rather than reported as a zero (`kernel-cli.md` §3 guardrail 2: a zero would
        read as a measurement of nothing).

    Raises:
        ValueError: If ``page`` is outside the document.

    """
    terms = _identity_terms(vendor)

    try:
        info = vendor.document_info(path)
        _validate_page(page, info.page_count)
        facts = vendor.page_facts(path, page)
    except PdfVendorError as refused:
        return _refused(refused, terms)

    observed: dict[str, object] = {
        "file": path.name,
        "page": page,
        "page_size": [facts.width_points, facts.height_points],
        "image_count": facts.image_count,
    }

    if facts.effective_dpi is None:
        return _failure(
            Reason(
                code=_CODE_UNSUPPORTED_FORMAT,
                message=(
                    f"page {page} of {path.name!r} places no measurable image, so "
                    "it has no effective resolution. Reported as an absence rather "
                    "than as zero DPI, which would read as a measurement that was "
                    "made."
                ),
            ),
            terms,
            {"image_count": float(facts.image_count)},
            observed,
        )

    return _observed(
        terms,
        {
            "effective_dpi": facts.effective_dpi,
            "image_count": float(facts.image_count),
        },
        observed,
    )


def extract_tokens(
    path: Path, pages: Sequence[int], dpi: int, *, vendor: PdfVendor
) -> KernelResult[Sequence[Token]]:
    """Extract the text layer's positioned tokens for a page range.

    The text layer is read by the ``pdftotext`` binary, which is the tool `sad.md`
    §1 names for this path, in its ``-bbox`` mode so each word arrives with the box
    it occupies. Coordinates are converted here from the reader's top-left origin at
    72 DPI into **source page coordinates at the requested DPI**, so a token's box
    means the same thing as the box ``render`` produces.

    Args:
        path: The PDF to read.
        pages: The one-based page numbers to read.
        dpi: The resolution the returned boxes are expressed in.
        vendor: The reader.

    Returns:
        The positioned tokens, or no value and a typed ``Reason``. A token's
        confidence is ``None``: the text layer is not a recogniser and reports no
        confidence, and ``None`` is never coerced to ``1.0`` (`sad.md` §6).

    Raises:
        ValueError: If the selection is empty or names a page outside the document,
            or if ``dpi`` is not positive.

    """
    if dpi <= 0:
        raise ValueError(f"dpi must be positive, got {dpi}")

    terms = _identity_terms(vendor)

    try:
        info = vendor.document_info(path)
        _validate_page(1, info.page_count)
        selection = _validate_selection(pages, info.page_count)
        words_by_page = vendor.words(path, selection)
    except PdfVendorError as refused:
        return _refused(refused, terms)

    scale = dpi / POINTS_PER_INCH
    tokens: list[Token] = []
    for page_number in selection:
        for word in words_by_page.get(page_number, ()):
            tokens.append(_token_of(word, page_number, scale))

    return KernelResult(
        value=tokens,
        evidence=_evidence(
            terms,
            {
                "tokens": float(len(tokens)),
                "pages_read": float(len(words_by_page)),
                "pages_requested": float(len(selection)),
                "dpi_applied": float(dpi),
            },
            {
                "file": path.name,
                "pages_requested": list(selection),
                "pages_read": sorted(words_by_page),
                "dpi_applied": dpi,
                "coordinate_space": "source_page_at_dpi",
                "reading_order": "not_resolved",
            },
        ),
        reason=None,
    )


def _token_of(word: Word, page: int, scale: float) -> Token:
    """Convert one reader word into a token in source page coordinates.

    Args:
        word: The word as the reader reported it, in PDF points from the top-left.
        page: The page the word is on.
        scale: The factor from points to the requested DPI.

    Returns:
        The token, with no confidence — the text layer is not a recogniser.

    """
    return Token(
        text=word.text,
        page=page,
        bbox=Box(
            x=word.x_min * scale,
            y=word.y_min * scale,
            width=(word.x_max - word.x_min) * scale,
            height=(word.y_max - word.y_min) * scale,
        ),
        confidence=None,
        role="text",
    )


def layout_text(
    path: Path, pages: Sequence[int], *, vendor: PdfVendor
) -> KernelResult[str]:
    """Extract the text layer with its physical layout preserved.

    The reader's ``-layout`` mode renders each page as a fixed grid of characters,
    which is a different reading from ``extract_tokens``' word boxes: this one keeps
    the *columns* the type was set in, and it is what the row-2 fixtures are checked
    against. Read per page and concatenated, because a caller may name pages that are
    not contiguous; the tests assert that composing per-page reads is byte-identical
    to one range invocation, since a silent difference here would be a different
    document.

    Pages must be strictly ascending. A reordered selection would return the reader's
    own concatenation, which is a document the caller did not ask for.

    Args:
        path: The PDF to read.
        pages: The one-based page numbers to read, strictly ascending.
        vendor: The reader.

    Returns:
        The layout text with form feeds between pages, or no value and a typed
        ``Reason``. A range whose text is entirely whitespace reports ``blank_page``:
        that is a measurement about the document's text layer, not a failure of the
        call.

    Raises:
        ValueError: If the selection is empty, not strictly ascending, or names a
            page outside the document.

    """
    terms = _identity_terms(vendor)

    try:
        info = vendor.document_info(path)
        selection = _validate_selection(pages, info.page_count)
    except PdfVendorError as refused:
        return _refused(refused, terms)

    if list(selection) != list(pages):
        raise ValueError(
            f"pages must be strictly ascending, got {list(pages)}. The result is "
            "the reader's own concatenation, so a reordered selection would return "
            "a document the caller did not ask for rather than the order it asked "
            "for."
        )

    try:
        chunks = [vendor.layout(path, page) for page in selection]
    except PdfVendorError as refused:
        return _refused(refused, terms)

    text = "".join(chunks)
    measurements: dict[str, float] = {
        "pages_read": float(len(selection)),
        "characters": float(len(text)),
        "lines": float(text.count("\n")),
    }
    observed: dict[str, object] = {
        "file": path.name,
        "pages_requested": list(selection),
        "page_separator": "\\f",
        "reader_flag": "-layout",
    }

    if not text.strip():
        # The reader ran and produced only whitespace. That is a measurement about
        # the document's text layer, not a failure of the call.
        return _failure(
            Reason(
                code=_CODE_BLANK_PAGE,
                message=(
                    f"the requested page(s) of {path.name!r} yielded no text, so "
                    "there is no layout to preserve. This is what a scan looks "
                    "like: it has pixels, not a text layer."
                ),
            ),
            terms,
            measurements,
            observed,
        )

    return KernelResult(
        value=text,
        evidence=_evidence(terms, measurements, observed),
        reason=None,
    )


def render(
    path: Path, pages: Sequence[int], dpi: int, *, vendor: PdfVendor
) -> KernelResult[Bytes]:
    """Render a page range as a bitmap, never upscaling.

    Args:
        path: The PDF to render.
        pages: The one-based page numbers to render.
        dpi: The resolution the caller requests.
        vendor: The reader.

    Returns:
        The rendered bitmap, or no value and a typed ``Reason``. A request that
        exceeds what the source pixels hold reports
        ``insufficient_effective_resolution`` and produces **no larger file**: the
        effective resolution is measured from the embedded pixels, and a page is
        never enlarged to pretend the request was met.

    Raises:
        ValueError: If the selection is empty or names a page outside the document,
            or if ``dpi`` is not positive.

    """
    if dpi <= 0:
        raise ValueError(f"dpi must be positive, got {dpi}")

    terms = _identity_terms(vendor)

    try:
        info = vendor.document_info(path)
        selection = _validate_selection(pages, info.page_count)
        shortage = _first_short_page(vendor, path, selection, dpi)
    except PdfVendorError as refused:
        return _refused(refused, terms)

    if shortage is not None:
        page_number, measured = shortage

        return _failure(
            Reason(
                code=_CODE_INSUFFICIENT_RESOLUTION,
                message=(
                    f"page {page_number} holds {measured:.1f} DPI of embedded "
                    f"pixels, so a {dpi} DPI render cannot be produced from it. "
                    "The requested resolution is refused rather than met by "
                    "enlarging the page: a larger file would look the same and "
                    "claim a resolution the source does not contain."
                ),
            ),
            terms,
            {"effective_dpi": measured, "dpi_requested": float(dpi)},
            {
                "file": path.name,
                "page": page_number,
                "pages_requested": list(selection),
                "files_written": 0,
            },
        )

    try:
        payload = vendor.render_png(path, selection, dpi)
    except PdfVendorError as refused:
        return _refused(refused, terms)

    return KernelResult(
        value=Bytes(data=payload, media_type="image/png"),
        evidence=_evidence(
            terms,
            {
                "pages_rendered": float(len(selection)),
                "dpi_applied": float(dpi),
                "bytes": float(len(payload)),
            },
            {
                "file": path.name,
                "pages_rendered": list(selection),
                "dpi_applied": dpi,
                "upscaled": False,
            },
        ),
        reason=None,
    )


def split(
    path: Path, pages: Sequence[int], *, vendor: PdfVendor
) -> KernelResult[Bytes]:
    """Cut a page range out of the file as a new document.

    Args:
        path: The PDF to split.
        pages: The one-based page numbers the result must contain, in the order
            requested. The order is honoured: reordering pages is a legitimate
            request, and silently sorting them would make the output not match the
            caller's selection.
        vendor: The reader.

    Returns:
        The extracted document, or no value and a typed ``Reason``. The result
        preserves the source's page size and therefore its page boxes, and the
        mapping back to the source range is recorded in the evidence — a split that
        separates a document from its pages is row 5 of the silent-failure matrix.

    Raises:
        ValueError: If the selection is empty, names a page outside the document, or
            repeats a page.

    """
    terms = _identity_terms(vendor)

    try:
        info = vendor.document_info(path)
        _validate_selection(pages, info.page_count)
        if len(set(pages)) != len(pages):
            raise ValueError(
                "the page selection repeats a page; a split places each source "
                "page once, and a duplicate would silently duplicate content"
            )
        for page in pages:
            _validate_page(page, info.page_count)

        cut = vendor.split_pdf(path, pages)
    except PdfVendorError as refused:
        return _refused(refused, terms)

    source_pages = [
        {
            "source_page": page,
            "width": info.page_sizes[page - 1][0],
            "height": info.page_sizes[page - 1][1],
        }
        for page in pages
    ]

    return KernelResult(
        value=Bytes(data=cut.data, media_type="application/pdf"),
        evidence=_evidence(
            terms,
            {
                "pages_extracted": float(len(cut.page_sizes)),
                "bytes": float(len(cut.data)),
            },
            {
                "file": path.name,
                "pages_requested": list(pages),
                "source_pages": source_pages,
                "result_page_sizes": [list(size) for size in cut.page_sizes],
                "mapping": "result page N <- source page pages_requested[N-1]",
            },
        ),
        reason=None,
    )


# --- The render gate ---------------------------------------------------------


def _first_short_page(
    vendor: PdfVendor, path: Path, pages: Sequence[int], dpi: int
) -> tuple[int, float] | None:
    """Find the first requested page whose pixels cannot supply the resolution.

    This is the refusal that makes *"a 150 DPI scan rendered at 300"* impossible:
    the number comes from the embedded pixels, so a request the source cannot honour
    is refused before anything is rendered, and no larger file exists to be mistaken
    for a satisfied request.

    Args:
        vendor: The reader.
        path: The PDF to measure.
        pages: The requested one-based pages.
        dpi: The requested resolution.

    Returns:
        The offending page and its measured resolution, or ``None`` when every
        requested page can honour the request. A page with no measurable image has no
        resolution to fall short of, so it is not an obstacle: vector content renders
        at any resolution the caller asks for.

    Raises:
        PdfVendorError: When a page cannot be measured at all.

    """
    for page_number in pages:
        measured = vendor.page_facts(path, page_number).effective_dpi
        if measured is not None and measured < dpi:
            return page_number, measured

    return None
