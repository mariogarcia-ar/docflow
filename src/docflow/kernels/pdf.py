"""K2 ``kernel.pdf`` — probe, classify, extract tokens, render, split.

The PDF acquisition kernel, thin and deterministic (`sad.md` §3, `E04-02` /
``S1-T12``). Two engines sit behind it: **PyMuPDF** for anything that needs the
page as an object or as pixels, and the **``pdftotext``** binary for the text
layer, because that is the tool `sad.md` §1 names for the conversion path and
``ADR-001`` says Docling does not apply there.

Two silent failures live in this module, and both are failures of *honesty about
what the bytes say* rather than failures of computation.

**A scan with a stale invisible OCR layer behind it reads as a text PDF**, so the
page is never converted and the text a person can see is never read. The trap is
sharp: PyMuPDF's ``page.get_text()`` **returns that invisible text as ordinary
text**, so the naive measurement reports a text page and is wrong. The layer is
detected as what it is — a rendering instruction, ``Tr 3``, meaning *draw
nothing* — and reported as evidence rather than used as a verdict.

**A 150 DPI scan rendered at 300 is reported as satisfying 300** — larger and no
more legible. ``render`` measures the effective resolution from the **embedded
pixels** and refuses a request the source cannot honour, producing no file at
all. It never upscales.

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

Every deliberate shortcut carries a marker naming what must replace it. Two are
worth stating up front because they shape the whole module: page facts beyond
classification and embedded-image extraction are documented targets rather than
Stage 1 scope, and the classification measures text *presence* rather than text
*coverage*.

Values transcribed from the legacy PoC (`legacy/`, analysed but deliberately not
copied) are noted where they inform a default; the code here is written from the
specification, not ported.
"""

# Pylint cannot see inside PyMuPDF: it is a compiled extension whose attributes are
# not introspectable, so `document.metadata`, `document.needs_pass` and
# `page.get_image_info` are reported as missing members while being real and
# documented. The suppression is stated once here rather than repeated at each call
# site.
# pylint: disable=no-member

# pylint: disable=too-many-lines
# The module carries five operations, the engine access, the measurement helpers,
# the reader-binary decode and the reason vocabulary. Splitting it to satisfy a line
# budget would separate the resolution measurement from the refusal that depends on
# it, which is the pairing this module exists to keep together.

# pylint: disable=too-many-instance-attributes
# `_PageFacts` is a measurement record whose eight fields are the measurements — not
# an accumulation of convenience members. Pooling them would hide which quantity a
# shape decision was taken from.

# pylint: disable=too-many-locals
# `classify` and `effective_dpi` assemble an evidence record whose terms,
# measurements and observations are each several values. The alternative is building
# the record in a helper that returns a mapping, which moves the same count one frame
# away without making anything clearer.

from __future__ import annotations

import dataclasses
import re
import shutil
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final
from xml.etree import ElementTree

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

# --- Engine identity ---------------------------------------------------------

#: The reader binary `sad.md` §1 names for the conversion path.
_READER_BINARY: Final[str] = "pdftotext"

#: The page-description engine. Imported lazily so this module imports without it
#: and a missing library becomes a typed ``Reason`` rather than an ``ImportError``
#: raised at import time.
_ENGINE_MODULE: Final[str] = "pymupdf"

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

#: The encoding the reader is asked to emit. Passed explicitly because the
#: default follows the host's locale, and two machines extracting the same file
#: would then disagree on the bytes without disagreeing on the document.
_READER_ENCODING: Final[str] = "UTF-8"

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


@dataclasses.dataclass(frozen=True, slots=True)
class _PageFacts:
    """One page's raw measurements, before any shape is named.

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


class _Refused(Exception):
    """A PDF that cannot be opened, carrying the ``Reason`` that explains it."""

    def __init__(self, reason: Reason) -> None:
        """Store the reason.

        Args:
            reason: Why the document was refused.

        """
        super().__init__(reason.message)
        self.reason = reason


# --- Engine access -----------------------------------------------------------


def _engine() -> tuple[Any | None, Reason | None]:
    """Import the page-description engine, or explain why it is unavailable.

    The import is deliberately inside the function: ``pyproject.toml`` declares no
    runtime dependency, so importing this module must not require the engine, and
    a missing library must arrive as a ``Reason`` rather than as an ``ImportError``
    raised at import time.

    Returns:
        The engine module, or ``None`` with a typed ``Reason``.

    """
    try:
        import pymupdf  # pylint: disable=import-outside-toplevel
    except ImportError:
        return None, Reason(
            code=_CODE_ENGINE_UNAVAILABLE,
            message=(
                f"the {_ENGINE_MODULE!r} library is not installed, so PDF pages "
                f"cannot be read. Install it (`pip install {_ENGINE_MODULE}`); no "
                "substitute reader is used, because a different engine reading the "
                "same bytes is a different measurement reported as this one."
            ),
        )

    return pymupdf, None


def _reader() -> tuple[str | None, Reason | None]:
    """Locate the text-layer reader binary.

    Returns:
        The binary's path, or ``None`` with a typed ``Reason`` naming the remedy.
        A missing binary is never substituted with another reader (`wbs.md` §9).

    """
    found = shutil.which(_READER_BINARY)
    if found is None:
        return None, Reason(
            code=_CODE_ENGINE_UNAVAILABLE,
            message=(
                f"the {_READER_BINARY!r} binary is not on PATH, so the text layer "
                "cannot be read. It ships with poppler "
                f"(`brew install poppler` / `apt install poppler-utils`). No "
                "substitute reader is used: a different extractor would report "
                "different tokens under this engine's identity."
            ),
        )

    return found, None


def _engine_terms(engine: Any) -> Mapping[str, str]:
    """Report the engine's revision, as a cache-key term.

    Args:
        engine: The engine module.

    Returns:
        A mapping of stable identity terms. The version is a key term because the
        same call against a different engine build is different work
        (`sad.md` §5).

    """
    version = getattr(engine, "version", None)
    if isinstance(version, (tuple, list)) and version:
        version = str(version[0])

    return MappingProxyType(
        {
            "engine": _ENGINE_MODULE,
            "engine_version": str(version or "unknown"),
        }
    )


def _reader_terms(binary: str) -> Mapping[str, str]:
    """Report the reader binary's identity, as a cache-key term.

    Args:
        binary: The resolved binary path.

    Returns:
        The adapter revision terms.

    """
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

    return MappingProxyType(
        {
            "reader": _READER_BINARY,
            "reader_revision": revision,
        }
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


# --- Opening -----------------------------------------------------------------


def _open_document(path: Path, engine: Any) -> Any:
    """Open a PDF, converting every failure into a typed ``Reason``.

    Args:
        path: The file to open.
        engine: The engine module.

    Returns:
        The open document.

    Raises:
        _Refused: When the file is absent, is encrypted, or is not a PDF.

    """
    if not path.exists():
        raise _Refused(
            Reason(
                code=_CODE_UNSUPPORTED_FORMAT,
                message=f"{path.name!r} does not exist at {path}",
            )
        )

    try:
        document = engine.open(str(path))
    except Exception as exc:
        raise _Refused(
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
        raise _Refused(
            Reason(
                code=_CODE_ENCRYPTED,
                message=(
                    f"{path.name!r} refuses to open without a password. The "
                    "document is reported as encrypted rather than as unreadable, "
                    "because the two need different remediation."
                ),
            )
        )

    return document


# --- Measurements ------------------------------------------------------------


def _largest_image_fraction(page: Any) -> float:
    """Measure how much of the page the largest placed image covers.

    This is a measurement, not a verdict: the legacy PoC calibrated a threshold of
    ``0.5`` on this quantity to decide whether a page is dominated by an image,
    and that number is not reproduced here — deciding with it is the caller's
    (`prd.md` FR-15).

    Args:
        page: The page to measure.

    Returns:
        The largest image's area over the page's area, ``0.0`` when the page
        places no image. May exceed ``1.0``: an image can be placed partly off the
        page, and clamping the value would hide that.

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
        The placement records, or an empty list when the page places no image or
        the list cannot be read.

    """
    try:
        return list(page.get_image_info(xrefs=True))
    except Exception:  # pylint: disable=broad-exception-caught
        # Deliberately broad, and the reason is specific: PyMuPDF raises several
        # unrelated exception types from this call depending on how a page's
        # resources are malformed, and the two outcomes that matter here are "the
        # page places an image" and "it does not". A narrow catch would let an
        # unanticipated type escape as a crash on a document that is merely odd.
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
        # Broad for the same reason as `_image_infos`: an object stream that
        # cannot be read is *no evidence of a hidden layer*, which is a valid
        # measurement, and the exception types this raises are not enumerable
        # across the PDFs the corpus will contain.
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
        document: The document the page belongs to. It is accepted because the
            measurement is conceptually about stored bytes, and a caller holding
            only a page should not have to know that this engine happens to expose
            the pixel dimensions on the placement record itself.

    Returns:
        The effective DPI, or ``None`` when the page places no measurable image.
        A ``None`` is not a zero: it states that this measurement does not apply,
        which is different from a measurement of nothing.

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


def _page_facts(page: Any, document: Any) -> _PageFacts:
    """Collect every measurement for one page.

    Args:
        page: The page to measure.
        document: The document the page belongs to.

    Returns:
        The page's raw measurements.

    """
    page.clean_contents()

    return _PageFacts(
        number=int(page.number) + 1,
        width_points=float(page.rect.width),
        height_points=float(page.rect.height),
        char_count=len((page.get_text() or "").strip()),
        image_count=len(page.get_images(full=True)),
        largest_image_fraction=_largest_image_fraction(page),
        invisible_text=_invisible_text(page, document),
        effective_dpi=_measured_dpi(page, document),
    )


def _producer_contradiction(producer: str, creator: str, facts: _PageFacts) -> bool:
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


def _shape_of(facts: _PageFacts, min_chars: int) -> str:
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


# --- The five operations -----------------------------------------------------


def probe(path: Path) -> KernelResult[Evidence]:
    """Report what the file is, without rendering anything.

    Args:
        path: The PDF to inspect.

    Returns:
        The page count, page sizes, declared metadata and encryption state, or no
        value and a typed ``Reason``. A file that cannot be opened reports
        ``encrypted`` or ``unsupported_format``: the observations are never
        returned empty as a stand-in for a successful probe.

    """
    engine, failure = _engine()
    if engine is None:
        return _failure(failure or Reason("engine_unavailable", ""), {}, {}, {})

    try:
        document = _open_document(path, engine)
    except _Refused as refused:
        return _failure(refused.reason, _engine_terms(engine), {}, {"file": path.name})

    try:
        sizes = [[float(page.rect.width), float(page.rect.height)] for page in document]
        metadata = dict(document.metadata or {})
        encrypted = bool(document.needs_pass)
    finally:
        document.close()

    producer = str(metadata.get("producer") or "absent")
    creator = str(metadata.get("creator") or "absent")

    return _observed(
        _engine_terms(engine),
        {"page_count": float(len(sizes))},
        {
            "file": path.name,
            "page_sizes": sizes,
            "producer": producer,
            "creator": creator,
            "format": str(metadata.get("format") or "absent"),
            "encrypted": encrypted,
        },
    )


def classify(path: Path, page: int, min_chars: int) -> KernelResult[Evidence]:
    """Measure one page's shape and report how the measurement was taken.

    Args:
        path: The PDF to inspect.
        page: One-based page number.
        min_chars: The caller's minimum character count for the text layer to
            count as the page's content. Required, with no default: a default
            here would be the kernel supplying a threshold, which `prd.md` FR-15
            assigns to the caller.

    Returns:
        The measured shape in ``observed["shape"]`` with its supporting
        observations, or no value and a typed ``Reason``. A page carrying an
        invisible text layer is measured with ``invisible_text`` set, so the stale
        layer is evidence rather than a silent reading of the page as text. A page
        holding neither text nor image reports ``blank_page``: *blank* is a shape,
        and it is not the same statement as *a page with no text*.

    Raises:
        ValueError: If ``page`` is outside the document. That is a usage error,
            not an outcome of the document, which is why it is raised rather than
            returned as a ``Reason`` — exit 4 rather than exit 2.

    """
    engine, failure = _engine()
    if engine is None:
        return _failure(failure or Reason("engine_unavailable", ""), {}, {}, {})

    try:
        document = _open_document(path, engine)
    except _Refused as refused:
        return _failure(
            refused.reason, _engine_terms(engine), {}, {"file": path.name, "page": page}
        )

    try:
        _validate_page(page, document.page_count)
        page_object = document[page - 1]
        facts = _page_facts(page_object, document)
        metadata = dict(document.metadata or {})
    finally:
        document.close()

    producer = str(metadata.get("producer") or "absent")
    creator = str(metadata.get("creator") or "absent")
    contradiction = _producer_contradiction(producer, creator, facts)
    shape = _shape_of(facts, min_chars)

    terms = _engine_terms(engine)
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
        "producer": producer,
        "creator": creator,
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


def effective_dpi(path: Path, page: int) -> KernelResult[Evidence]:
    """Measure the resolution a page's embedded pixels actually hold.

    A separate operation from ``render`` because this is the number the caller
    needs *before* asking for a render: it is what makes an unsatisfiable request
    predictable rather than surprising.

    Args:
        path: The PDF to measure.
        page: One-based page number.

    Returns:
        The measured resolution, or no value and a typed ``Reason``. A page that
        places no image has no effective DPI to report, and that absence is stated
        rather than reported as a zero (`kernel-cli.md` §3 guardrail 2: a zero
        would read as a measurement of nothing).

    Raises:
        ValueError: If ``page`` is outside the document.

    """
    engine, failure = _engine()
    if engine is None:
        return _failure(failure or Reason("engine_unavailable", ""), {}, {}, {})

    try:
        document = _open_document(path, engine)
    except _Refused as refused:
        return _failure(
            refused.reason, _engine_terms(engine), {}, {"file": path.name, "page": page}
        )

    try:
        _validate_page(page, document.page_count)
        page_object = document[page - 1]
        measured = _measured_dpi(page_object, document)
        facts = _PageFacts(
            number=page,
            width_points=float(page_object.rect.width),
            height_points=float(page_object.rect.height),
            char_count=0,
            image_count=len(page_object.get_images(full=True)),
            largest_image_fraction=0.0,
            invisible_text=False,
            effective_dpi=measured,
        )
    finally:
        document.close()

    terms = _engine_terms(engine)
    observed: dict[str, object] = {
        "file": path.name,
        "page": facts.number,
        "page_size": [facts.width_points, facts.height_points],
        "image_count": facts.image_count,
    }

    if measured is None:
        return _failure(
            Reason(
                code=_CODE_UNSUPPORTED_FORMAT,
                message=(
                    f"page {facts.number} of {path.name!r} places no measurable "
                    "image, so it has no effective resolution. Reported as an "
                    "absence rather than as zero DPI, which would read as a "
                    "measurement that was made."
                ),
            ),
            terms,
            {"image_count": float(facts.image_count)},
            observed,
        )

    return _observed(
        terms,
        {"effective_dpi": measured, "image_count": float(facts.image_count)},
        observed,
    )


def extract_tokens(
    path: Path, pages: Sequence[int], dpi: int
) -> KernelResult[Sequence[Token]]:
    """Extract the text layer's positioned tokens for a page range.

    The text layer is read by the ``pdftotext`` binary, which is the tool
    `sad.md` §1 names for this path, in its ``-bbox`` mode so each word arrives
    with the box it occupies. Coordinates are converted from the binary's
    top-left origin at 72 DPI into **source page coordinates at the requested
    DPI**, so a token's box means the same thing as the box ``render`` produces.

    Args:
        path: The PDF to read.
        pages: The one-based page numbers to read.
        dpi: The resolution the returned boxes are expressed in.

    Returns:
        The positioned tokens, or no value and a typed ``Reason``. A token's
        confidence is ``None``: the text layer is not a recogniser and reports no
        confidence, and ``None`` is never coerced to ``1.0`` (`sad.md` §6).

    Raises:
        ValueError: If the selection is empty or names a page outside the
            document, or if ``dpi`` is not positive.

    """
    if dpi <= 0:
        raise ValueError(f"dpi must be positive, got {dpi}")

    engine, engine_failure = _engine()
    if engine is None:
        return _failure(engine_failure or Reason("engine_unavailable", ""), {}, {}, {})

    binary, reader_failure = _reader()
    if binary is None:
        return _failure(
            reader_failure or Reason("engine_unavailable", ""),
            _engine_terms(engine),
            {},
            {"file": path.name},
        )

    try:
        document = _open_document(path, engine)
    except _Refused as refused:
        return _failure(refused.reason, _engine_terms(engine), {}, {"file": path.name})

    try:
        _validate_page(1, document.page_count)
        selection = _validate_selection(pages, document.page_count)
    finally:
        document.close()

    terms = dict(_engine_terms(engine)) | dict(_reader_terms(binary))
    scale = dpi / _POINTS_PER_INCH

    try:
        words_by_page = _read_words(binary, path, selection)
    except (OSError, subprocess.SubprocessError) as exc:
        return _failure(
            Reason(
                code=_CODE_ENGINE_UNAVAILABLE,
                message=(
                    f"the {_READER_BINARY!r} binary could not read {path.name!r}: "
                    f"{type(exc).__name__}: {exc}"
                ),
            ),
            terms,
            {},
            {"file": path.name, "pages_requested": list(selection)},
        )

    tokens: list[Token] = []
    for page_number in selection:
        for word in words_by_page.get(page_number, ()):
            tokens.append(
                Token(
                    text=word.text,
                    page=page_number,
                    bbox=Box(
                        x=word.x_min * scale,
                        y=word.y_min * scale,
                        width=(word.x_max - word.x_min) * scale,
                        height=(word.y_max - word.y_min) * scale,
                    ),
                    confidence=None,
                    role="text",
                )
            )

    counters: dict[str, float] = {
        "tokens": float(len(tokens)),
        "pages_read": float(len(words_by_page)),
        "pages_requested": float(len(selection)),
        "dpi_applied": float(dpi),
    }

    return KernelResult(
        value=tokens,
        evidence=_evidence(
            terms,
            counters,
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


def layout_text(path: Path, pages: Sequence[int]) -> KernelResult[str]:
    """Extract the text layer with its physical layout preserved.

    The reader's ``-layout`` mode renders each page as a fixed grid of characters,
    so columns, aligned fields and tables survive as the whitespace they occupy on
    the page. It is the cheapest useful read of a PDF that already carries text,
    and on material whose meaning depends on what sits beside what it is the
    *better* read: a two-column document flattened into a single column of text is
    not a different rendering of the same facts, it is a different set of facts.

    **This operation is a convenience, not a contract, and nothing depends on it.**
    It is deliberately absent from ``docflow/ports/pdf.py``: `plans/README.md` §3
    freezes the port interfaces and Plan 2 may not change them, so a consumer that
    needs layout reaches this function directly. It is under consideration as an
    optimisation for the text path, and it is **not** wired into any flow yet.

    What it is not
    --------------

    It is **not** a replacement for ``extract_tokens``, and the two are not
    interchangeable. ``extract_tokens`` returns positioned boxes in source page
    coordinates, which is what a trace needs and what a layout can be *derived*
    from; this returns a character grid, which carries no coordinates at all — a
    consumer cannot say which pixels a line came from.

    It also does **not** let a caller reproduce the reader's output byte-for-byte
    from the tokens. The reader has the font metrics and emits the soft hyphen it
    broke a word on; a token box has neither. Measured on the two-column fixture
    ``casos/9dfc597f``: 0 of 68 lines of a token-derived reconstruction match the
    reader's own output, while the *structure* — which column each word sits in —
    is recoverable.

    Args:
        path: The PDF to read.
        pages: The one-based page numbers to read, in strictly ascending order. A
            non-contiguous selection such as ``[1, 3]`` is served by reading each
            page and joining the results, which is byte-identical to reading a
            contiguous range in one invocation — asserted by the tests rather than
            assumed.

    Returns:
        The layout text, or no value and a typed ``Reason``. A document whose
        requested pages yield no text returns ``blank_page``: the reader produced
        nothing because there is nothing, which is a statement about the document.
        A file this engine cannot open returns ``encrypted`` or
        ``unsupported_format``.

    Raises:
        ValueError: If the selection is empty, names a page outside the document,
            or is not strictly ascending. The order is required rather than
            imposed: the result is the reader's own concatenation, so a caller who
            asked for a different order would otherwise silently receive one it did
            not ask for.

    """
    engine, engine_failure = _engine()
    if engine is None:
        return _failure(engine_failure or Reason("engine_unavailable", ""), {}, {}, {})

    binary, reader_failure = _reader()
    if binary is None:
        return _failure(
            reader_failure or Reason("engine_unavailable", ""),
            _engine_terms(engine),
            {},
            {"file": path.name},
        )

    try:
        document = _open_document(path, engine)
    except _Refused as refused:
        return _failure(refused.reason, _engine_terms(engine), {}, {"file": path.name})

    try:
        selection = _validate_selection(pages, document.page_count)
        if list(selection) != list(pages):
            raise ValueError(
                f"pages must be strictly ascending, got {list(pages)}. The result "
                "is the reader's own concatenation, so a reordered selection would "
                "return a document the caller did not ask for rather than the order "
                "it asked for."
            )
    finally:
        document.close()

    terms = dict(_engine_terms(engine)) | dict(_reader_terms(binary))

    try:
        chunks = [_read_layout(binary, path, page) for page in selection]
    except (OSError, subprocess.SubprocessError) as exc:
        return _failure(
            Reason(
                code=_CODE_ENGINE_UNAVAILABLE,
                message=(
                    f"the {_READER_BINARY!r} binary could not read {path.name!r}: "
                    f"{type(exc).__name__}: {exc}"
                ),
            ),
            terms,
            {},
            {"file": path.name, "pages_requested": list(selection)},
        )

    text = "".join(chunks)
    observed: dict[str, object] = {
        "file": path.name,
        "pages_requested": list(selection),
        "page_separator": "\\f",
        "reader_flag": "-layout",
        "reader_encoding": _READER_ENCODING,
    }
    measurements: dict[str, float] = {
        "pages_read": float(len(selection)),
        "characters": float(len(text)),
        "lines": float(text.count("\n")),
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


def render(path: Path, pages: Sequence[int], dpi: int) -> KernelResult[Bytes]:
    """Render a page range as a bitmap, never upscaling.

    Args:
        path: The PDF to render.
        pages: The one-based page numbers to render.
        dpi: The resolution the caller requests.

    Returns:
        The rendered bitmap, or no value and a typed ``Reason``. A request that
        exceeds what the source pixels hold reports
        ``insufficient_effective_resolution`` and produces **no larger file**: the
        effective resolution is measured from the embedded pixels, and a page is
        never enlarged to pretend the request was met.

    Raises:
        ValueError: If the selection is empty or names a page outside the
            document, or if ``dpi`` is not positive.

    """
    if dpi <= 0:
        raise ValueError(f"dpi must be positive, got {dpi}")

    engine, failure = _engine()
    if engine is None:
        return _failure(failure or Reason("engine_unavailable", ""), {}, {}, {})

    try:
        document = _open_document(path, engine)
    except _Refused as refused:
        return _failure(refused.reason, _engine_terms(engine), {}, {"file": path.name})

    try:
        selection = _validate_selection(pages, document.page_count)
        shortage = _first_short_page(document, selection, dpi)

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
                _engine_terms(engine),
                {"effective_dpi": measured, "dpi_requested": float(dpi)},
                {
                    "file": path.name,
                    "page": page_number,
                    "pages_requested": list(selection),
                    "files_written": 0,
                },
            )

        images = [
            document[page_number - 1].get_pixmap(
                matrix=engine.Matrix(dpi / _POINTS_PER_INCH, dpi / _POINTS_PER_INCH),
                colorspace=engine.csRGB,
                alpha=False,
            )
            for page_number in selection
        ]
    finally:
        document.close()

    payload = _encode_png(engine, images)

    return KernelResult(
        value=Bytes(data=payload, media_type="image/png"),
        evidence=_evidence(
            _engine_terms(engine),
            {
                "pages_rendered": float(len(images)),
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


def split(path: Path, pages: Sequence[int]) -> KernelResult[Bytes]:
    """Cut a page range out of the file as a new document.

    Args:
        path: The PDF to split.
        pages: The one-based page numbers the result must contain, in the order
            requested. The order is honoured: reordering pages is a legitimate
            request, and silently sorting them would make the output not match the
            caller's selection.

    Returns:
        The extracted document, or no value and a typed ``Reason``. The result
        preserves the source's page size and therefore its page boxes, and the
        mapping back to the source range is recorded in the evidence — a split
        that separates a document from its pages is row 5 of the silent-failure
        matrix.

    Raises:
        ValueError: If the selection is empty or names a page outside the
            document.

    """
    engine, failure = _engine()
    if engine is None:
        return _failure(failure or Reason("engine_unavailable", ""), {}, {}, {})

    try:
        document = _open_document(path, engine)
    except _Refused as refused:
        return _failure(refused.reason, _engine_terms(engine), {}, {"file": path.name})

    source_pages: list[dict[str, object]] = []
    try:
        # Order-preserving validation: `split` honours the requested order, so it
        # checks every page itself rather than going through the sorting helper.
        _validate_selection(pages, document.page_count)
        if len(set(pages)) != len(pages):
            raise ValueError(
                "the page selection repeats a page; a split places each source "
                "page once, and a duplicate would silently duplicate content"
            )
        for page in pages:
            _validate_page(page, document.page_count)
            source = document[page - 1]
            source_pages.append(
                {
                    "source_page": page,
                    "width": float(source.rect.width),
                    "height": float(source.rect.height),
                }
            )

        extracted = engine.open()
        for page in pages:
            extracted.insert_pdf(document, from_page=page - 1, to_page=page - 1)

        payload = extracted.tobytes(deflate=True, garbage=3)
        page_count = extracted.page_count
        sizes = [
            [float(page.rect.width), float(page.rect.height)] for page in extracted
        ]
        extracted.close()
    finally:
        document.close()

    return KernelResult(
        value=Bytes(data=payload, media_type="application/pdf"),
        evidence=_evidence(
            _engine_terms(engine),
            {
                "pages_extracted": float(page_count),
                "bytes": float(len(payload)),
            },
            {
                "file": path.name,
                "pages_requested": list(pages),
                "source_pages": source_pages,
                "result_page_sizes": sizes,
                "mapping": "result page N <- source page pages_requested[N-1]",
            },
        ),
        reason=None,
    )


# --- Helpers -----------------------------------------------------------------


def _read_layout(binary: str, path: Path, page: int) -> str:
    """Read one page's text with its physical layout preserved.

    The page is read on its own with ``-f``/``-l`` rather than as part of a range,
    because a caller may ask for pages that are not contiguous. Composing the
    result from per-page reads is byte-identical to one range invocation — the tests
    assert that equivalence rather than trusting it, since a silent difference here
    would be a different document.

    Args:
        binary: The resolved reader binary.
        path: The PDF to read.
        page: The one-based page number.

    Returns:
        The page's layout text, form feed included, exactly as the reader emitted
        it.

    Raises:
        OSError: If the binary cannot be executed.
        subprocess.SubprocessError: If the binary fails or times out.

    """
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
        timeout=300,
        check=False,
    )

    if completed.returncode != 0:
        stderr = (completed.stderr or b"").decode("utf-8", "replace")[:200]
        raise subprocess.SubprocessError(
            f"{_READER_BINARY!r} exited {completed.returncode}: {stderr!r}"
        )

    return completed.stdout.decode(_READER_ENCODING, "replace")


@dataclasses.dataclass(frozen=True, slots=True)
class _Word:
    """One word as the reader binary reported it, in PDF user units.

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


def _read_words(
    binary: str, path: Path, pages: Sequence[int]
) -> dict[int, tuple[_Word, ...]]:
    """Read the text layer's words, page by page, with their boxes.

    The binary's ``-bbox`` mode emits XHTML, so the file is parsed as XML rather
    than scanned with a pattern: a document whose text contains an angle bracket
    is ordinary, and a pattern that reads markup cannot survive it.

    Args:
        binary: The resolved reader binary.
        path: The PDF to read.
        pages: The one-based pages to keep.

    Returns:
        A mapping of page number to that page's words. A requested page with no
        words is **absent** from the mapping rather than present with an empty
        tuple, so *the reader produced nothing for this page* stays
        distinguishable from *this page had no words*.

    Raises:
        OSError: If the binary cannot be executed.
        subprocess.SubprocessError: If the binary fails or times out.

    """
    with tempfile.TemporaryDirectory(prefix="docflow_pdf_bbox_") as workdir:
        output = Path(workdir) / "words.xml"
        completed = subprocess.run(
            [binary, "-bbox", "-q", str(path), str(output)],
            capture_output=True,
            timeout=300,
            check=False,
        )

        if completed.returncode != 0:
            stderr = (completed.stderr or b"").decode("utf-8", "replace")[:200]
            raise subprocess.SubprocessError(
                f"{_READER_BINARY!r} exited {completed.returncode}: {stderr!r}"
            )

        if not output.exists():
            # No file means the binary found no text at all. That is a
            # measurement about the document rather than a failure of the call.
            return {}

        raw = output.read_bytes()

    return _parse_bbox_xml(raw, set(pages))


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


def _parse_bbox_xml(raw: bytes, wanted: set[int]) -> dict[int, tuple[_Word, ...]]:
    """Parse the reader's XHTML into words per page.

    Args:
        raw: The XHTML bytes the binary wrote.
        wanted: The page numbers to keep.

    Returns:
        A mapping of page number to that page's words, for the requested pages
        that carried any.

    """
    root = ElementTree.fromstring(raw)
    # this module's own reader invocation produced, never untrusted network input.

    pages = [node for node in root.iter() if _local_name(node.tag) == "page"]

    result: dict[int, tuple[_Word, ...]] = {}
    for page_number, page in enumerate(pages, start=1):
        if page_number not in wanted:
            continue

        words = tuple(
            _Word(
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


def _first_short_page(
    document: Any, pages: Sequence[int], dpi: int
) -> tuple[int, float] | None:
    """Find the first requested page whose pixels cannot supply the resolution.

    Args:
        document: The open document.
        pages: The requested one-based pages.
        dpi: The requested resolution.

    Returns:
        The offending page and its measured resolution, or ``None`` when every
        requested page can honour the request. A page with no measurable image has
        no resolution to fall short of, so it is not an obstacle: vector content
        renders at any resolution the caller asks for.

    """
    for page_number in pages:
        page = document[page_number - 1]
        measured = _measured_dpi(page, document)
        if measured is not None and measured < dpi:
            return page_number, measured

    return None


def _encode_png(engine: Any, images: Sequence[Any]) -> bytes:
    """Encode rendered pages as a single PNG.

    Args:
        engine: The engine module.
        images: The rendered pixmaps, one per page.

    Returns:
        The encoded PNG bytes. A single page is encoded directly; several pages
        are stacked vertically into one image, because ``Bytes`` is one buffer and
        inventing a container format here would be a second contract.

    """
    if len(images) == 1:
        return bytes(images[0].tobytes("png"))

    total_height = sum(image.height for image in images)
    width = max(image.width for image in images)
    canvas = engine.Pixmap(engine.csRGB, engine.IRect(0, 0, width, total_height))
    canvas.clear_with(255)

    offset = 0
    for image in images:
        target = engine.IRect(0, offset, image.width, offset + image.height)
        canvas.copy(image, target)
        offset += image.height

    return bytes(canvas.tobytes("png"))
