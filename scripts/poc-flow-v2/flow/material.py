"""The material a document is read from, and the function that produces it.

This module owns the adapter calls for `my_flow.md` §2 (route and read). It is
the only module in this package that imports the adapters, apart from
`extract.py` (the language models); the decision it executes lives in
:mod:`.route`, so the rule stays testable without paying for the read.

The reads are the same three the PoC measured:

- a PDF page whose text layer is classified `text`/`mixed` is read with
  `PdfEngine.layout_text` (`pdftotext -layout`);
- a page with no usable text layer is rendered at the floor capped by the page's
  own measured resolution (the adapter refuses to upscale), then read with
  `DoclingEngine.layout` (rows, preserving order);
- an image file is legibility-gated, then read with `DoclingEngine.layout`.
"""

from __future__ import annotations

# `wrong-import-order` / `wrong-import-position`: the `docflow` adapters are
# only importable once `_bootstrap` puts `src/` on `sys.path`, so the adapter
# imports must follow `ensure_docflow_importable()`. The order is load-bearing,
# not cosmetic — the same rule `scripts/poc/` documents for its drivers.
# pylint: disable=wrong-import-order, wrong-import-position
import pathlib
import shutil
import tempfile
from typing import Final

from ._bootstrap import ensure_docflow_importable

ensure_docflow_importable()

from docflow.adapters.docling import DoclingEngine  # noqa: E402
from docflow.adapters.image import RasterEngine  # noqa: E402
from docflow.adapters.pdf import PdfEngine  # noqa: E402
from docflow.kernels.types import Bytes  # noqa: E402

from .config import DEFAULT_CONFIG, Config  # noqa: E402
from .route import Decision, decide  # noqa: E402

__all__: list[str] = [
    "TIER_DEGRADED",
    "TIER_NATIVE",
    "TIER_OCR",
    "Material",
    "read_material",
]

#: The tiers `my_flow.md` §2 names. A tier is the confidence class of the
#: reading, not a claim of truth about the document.
TIER_NATIVE: Final[str] = "texto_nativo"
TIER_OCR: Final[str] = "escaneado_ocr"
TIER_DEGRADED: Final[str] = "degradado"

#: The shapes K2 classifies a text layer as.
_TEXT_SHAPES: Final[frozenset[str]] = frozenset({"text", "mixed"})

#: Suffixes the raster engine accepts, for the image-file branch.
_IMAGE_SUFFIXES: Final[frozenset[str]] = frozenset(
    {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}
)


# `too-many-instance-attributes` / `too-few-public-methods`: `Material` is the
# record the read stage hands to the extraction stage; its fields are the
# contract and it has no behaviour to add. The same reasoning `fields.py` states
# for its boundary records.
# pylint: disable=too-many-instance-attributes, too-few-public-methods


class Material:
    """What a document was read from, and the text it produced.

    Attributes:
        kind: ``"pdf"`` or ``"image"``.
        tier: One of the :data:`TIER_*` classes.
        text: The document's text, joined across pages, or ``None`` when no page
            produced text.
        route: The operations that ran, e.g. ``"layout_text"`` or
            ``"render+ocr"``.
        pages_read: How many pages contributed text.
        pages_total: How many pages the document has, or ``None`` when unknown.
        images: The rendered pages as :class:`Bytes`, for the vision lane. A
            text page has no image and therefore none here.
        notes: Human-readable notes, e.g. a page cap or a per-page refusal.

    """

    def __init__(  # pylint: disable=too-many-arguments, too-many-positional-arguments
        self,
        *,
        kind: str,
        tier: str,
        text: str | None,
        route: str,
        pages_read: int,
        pages_total: int | None,
        images: list[Bytes],
        notes: list[str],
    ) -> None:
        self.kind = kind
        self.tier = tier
        self.text = text
        self.route = route
        self.pages_read = pages_read
        self.pages_total = pages_total
        self.images = images
        self.notes = notes


def _shape_of(pdf: PdfEngine, path: pathlib.Path, page: int) -> str:
    """Measure one page's shape, or ``""`` when it could not be measured.

    The shape is read from the evidence even when there is no value: `classify`
    answers a blank page with ``value=None`` while still reporting
    ``shape='blank'``, and reading the shape only alongside a value collapses
    *blank* into *unmeasurable*.
    """
    measured = pdf.classify(path, page)
    if measured.evidence is not None:
        shape = measured.evidence.observed.get("shape", "")
        return str(shape)
    return ""


def _page_count(pdf: PdfEngine, path: pathlib.Path) -> int | None:
    """Read a PDF's page count from a probe, or ``None`` when it refused."""
    probed = pdf.probe(path)
    if probed.value is None:
        return None
    counted = probed.value.measurements.get("page_count")
    return int(counted) if counted else None


def _measured_dpi(pdf: PdfEngine, path: pathlib.Path, page: int) -> int | None:
    """Measure the resolution a page's embedded pixels hold.

    ``None`` when unmeasurable: the caller then uses its own floor, and the
    adapter caps the render by whatever the page holds.
    """
    measured = pdf.effective_dpi(path, page)
    if measured.value is None:
        return None
    value = measured.value.measurements.get("effective_dpi")
    return int(value) if value else None


def _legibility(
    raster: RasterEngine, path: pathlib.Path, threshold: float
) -> tuple[str, float | None, float]:
    """Measure an image's sharpness and translate it to the decisor's vocabulary.

    The threshold comes from the caller's config, never from a constant here.
    The measurements travel with the verdict either way, so the reason can name
    the number it was taken from.
    """
    measured = raster.legibility(path, threshold)
    sharpness = None
    if measured.evidence is not None:
        value = measured.evidence.measurements.get("laplacian_variance")
        sharpness = float(value) if value is not None else None
    if measured.value is not None:
        return "ok", sharpness, threshold
    code = measured.reason.code if measured.reason is not None else "unknown"
    return code, sharpness, threshold


def _render_dpi(pdf: PdfEngine, path: pathlib.Path, page: int, floor: int) -> int:
    """The resolution to render at: the floor, capped by the page's own pixels.

    The adapter refuses to upscale, and that refusal is right: an upscaled page
    is larger and no more legible. Asking for the floor blindly would leave the
    page that most needs exporting with no file at all.
    """
    measured = _measured_dpi(pdf, path, page)
    if measured is None:
        return floor
    return min(floor, measured)


def _read_pdf(  # pylint: disable=too-many-arguments, too-many-positional-arguments, too-many-locals, too-many-statements
    pdf: PdfEngine,
    ocr: DoclingEngine,
    raster: RasterEngine,
    path: pathlib.Path,
    config: Config,
    scratch: pathlib.Path,
) -> Material:
    """Read a PDF page by page, deciding each page's route on its own.

    A PDF is a container whose pages are independent: one file mixes text pages,
    image pages and blank ones. Pages go aside individually, and the document
    still produces the text of the pages that could be read.

    The three engines are each a different thing the read needs (measure, render,
    recognise); grouping them into a value object would move the count one frame
    away and invent a boundary type. The loop's count is the page-by-page
    decision itself, which is the point of this function.

    Args:
        scratch: A directory for the rendered page frames, removed by the caller.
    """
    total = _page_count(pdf, path)
    if total is None or total <= 0:
        return Material(
            kind="pdf",
            tier=TIER_DEGRADED,
            text=None,
            route="",
            pages_read=0,
            pages_total=total,
            images=[],
            notes=["the document reports no pages"],
        )

    texts: list[str] = []
    images: list[Bytes] = []
    routes: list[str] = []
    refusals: list[str] = []

    for page in range(1, total + 1):
        shape = _shape_of(pdf, path, page)
        resolution = _render_dpi(pdf, path, page, config.render_dpi)

        # Render before deciding, so the legibility reading exists in time to
        # decide whether reading the pixels is worth it. A text page pays a
        # render it does not need — the price of asking first.
        rendered = pdf.render(path, [page], resolution)
        legibility: str = ""
        sharpness: float | None = None
        threshold: float | None = None
        image = None
        frame = scratch / f"{path.stem}-p{page}.png"
        if rendered.value is not None:
            image = rendered.value
            try:
                frame.write_bytes(image.data)
                legibility, sharpness, threshold = _legibility(
                    raster, frame, config.legibility_threshold
                )
            except OSError:
                pass

        verdict: Decision = decide(
            shape=shape,
            legibility=legibility,
            sharpness=sharpness,
            threshold=threshold,
            measured_dpi=resolution,
            min_chars=config.min_chars,
            text_shapes=_TEXT_SHAPES,
        )

        if not verdict.proceeds:
            refusals.append(f"p{page}: {verdict.reason}")
            continue

        if verdict.route == "text":
            read = pdf.layout_text(path, [page])
            if read.value is None:
                code = read.reason.code if read.reason else "unknown"
                refusals.append(f"p{page}: layout_text refused ({code})")
                continue
            texts.append(read.value)
            if "layout_text" not in routes:
                routes.append("layout_text")
            continue

        if image is None:
            code = rendered.reason.code if rendered.reason else "unknown"
            refusals.append(f"p{page}: render refused ({code})")
            continue

        read = ocr.layout(
            frame,
            [1],
            config.ocr_dpi,
            config.ocr_lang,
            line_tolerance=config.ocr_line_tolerance_points * config.ocr_dpi / 72,
            orientation="horizontal",
            tables=False,
        )
        if read.value is None:
            code = read.reason.code if read.reason else "unknown"
            refusals.append(f"p{page}: ocr refused ({code})")
            continue
        texts.append(read.value)
        images.append(image)
        if "render+ocr" not in routes:
            routes.append("render+ocr")

    if not texts:
        return Material(
            kind="pdf",
            tier=TIER_DEGRADED,
            text=None,
            route="",
            pages_read=0,
            pages_total=total,
            images=[],
            notes=refusals,
        )

    tier = TIER_NATIVE if routes == ["layout_text"] else TIER_OCR
    return Material(
        kind="pdf",
        tier=tier,
        text="\f".join(texts),
        route="+".join(routes),
        pages_read=len(texts),
        pages_total=total,
        images=images,
        notes=refusals,
    )


def _read_image(
    raster: RasterEngine,
    ocr: DoclingEngine,
    path: pathlib.Path,
    config: Config,
) -> Material:
    """Read an image file: legibility-gate, then OCR with layout ordering."""
    legibility, sharpness, threshold = _legibility(
        raster, path, config.legibility_threshold
    )
    verdict = decide(
        shape="image",
        legibility=legibility,
        sharpness=sharpness,
        threshold=threshold,
        min_chars=config.min_chars,
        text_shapes=_TEXT_SHAPES,
    )
    if not verdict.proceeds:
        return Material(
            kind="image",
            tier=TIER_DEGRADED,
            text=None,
            route="",
            pages_read=0,
            pages_total=1,
            images=[],
            notes=[verdict.reason],
        )

    read = ocr.layout(
        path,
        [1],
        config.ocr_dpi,
        config.ocr_lang,
        line_tolerance=config.ocr_line_tolerance_points * config.ocr_dpi / 72,
        orientation="horizontal",
        tables=False,
    )
    if read.value is None:
        code = read.reason.code if read.reason else "unknown"
        return Material(
            kind="image",
            tier=TIER_DEGRADED,
            text=None,
            route="",
            pages_read=0,
            pages_total=1,
            images=[],
            notes=[f"ocr refused ({code})"],
        )

    return Material(
        kind="image",
        tier=TIER_OCR,
        text=read.value,
        route="ocr",
        pages_read=1,
        pages_total=1,
        images=[],
        notes=[],
    )


def read_material(path: pathlib.Path, config: Config = DEFAULT_CONFIG) -> Material:
    """Read one document into its :class:`Material`, by whichever route applies.

    Args:
        path: The source file.
        config: The run's dials.

    Returns:
        The material, never ``None``. A degraded material carries ``text=None``
        and its reasons in ``notes``.
    """
    pdf = PdfEngine(min_chars=config.min_chars)
    raster = RasterEngine()
    ocr = DoclingEngine()

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        scratch = pathlib.Path(tempfile.mkdtemp(prefix="docflow-flow-"))
        try:
            return _read_pdf(pdf, ocr, raster, path, config, scratch)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
    if suffix in _IMAGE_SUFFIXES:
        return _read_image(raster, ocr, path, config)

    return Material(
        kind="invalid",
        tier=TIER_DEGRADED,
        text=None,
        route="",
        pages_read=0,
        pages_total=None,
        images=[],
        notes=[f"{suffix or '(no suffix)'} is neither a PDF nor an image"],
    )
