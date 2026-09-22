"""Entry points of the PDF processor.

The signatures are frozen by ``docs/plan/README.md`` §4 (the idea's §"Naming"): ``pdf``
exposes ``process_pdf()`` and ``process_pdf_page()``.

``PDF-09`` implements :func:`process_pdf_page` here: it composes the primitives of
``pdf/primitives/`` into one page run, publishes the page's artifacts and returns a
``PDFPageResult``. ``PDF-10`` implements :func:`process_pdf`, which stays a stub until then.

The composition is deliberately dull — each capability runs when the request asked for it,
its failure is recorded rather than raised, and the page keeps whatever succeeded. Two rules
shape it:

* **A failing capability is reported, never propagated.** A page whose embedded images could
  not be written still has its render and its text, so it is ``PARTIAL``, not lost. The
  exception path is reserved for the page not existing at all, where there is nothing to
  keep.
* **Writes stay inside this processor's namespaces.** ``source/``, ``render/``,
  ``native_text/``, ``embedded_images/`` and ``metadata.json``, and nothing else — not
  ``image/``, ``ocr/`` or ``llm/``, which belong to other processors.
"""

from __future__ import annotations

import time
from pathlib import Path

from docflow.pdf.contracts import (
    EmbeddedImage,
    PDFError,
    PDFErrorType,
    PDFPageClassification,
    PDFPageMetrics,
    PDFPageResult,
    PDFPageValidation,
    PDFRequest,
    PDFResult,
    PDFStatus,
    TextBlock,
)
from docflow.pdf.primitives.composition import (
    PageContent,
    analyze_pdf_page,
    classify_pdf_page,
)
from docflow.pdf.primitives.document import get_page_dimensions
from docflow.pdf.primitives.engine import PopplerError, get_engine
from docflow.pdf.primitives.failures import PDFPrimitiveError
from docflow.pdf.primitives.images import extract_images_from_page
from docflow.pdf.primitives.naming import page_index_name
from docflow.pdf.primitives.provenance import processor_name, processor_version
from docflow.pdf.primitives.publishing import publish_json, publish_text
from docflow.pdf.primitives.render import render_page_to_image
from docflow.pdf.primitives.split import extract_page
from docflow.pdf.primitives.text import engine_report, get_text_blocks
from docflow.pdf.primitives.validation import (
    page_metadata,
    validate_pdf_page_result,
)

SOURCE_DIR = "source"
RENDER_DIR = "render"
NATIVE_TEXT_DIR = "native_text"
EMBEDDED_IMAGES_DIR = "embedded_images"

PAGE_PDF_NAME = "page.pdf"
PAGE_IMAGE_NAME = "page.png"
TEXT_NAME = "text.txt"
BLOCKS_NAME = "blocks.json"
METADATA_NAME = "metadata.json"

EMPTY_METRICS = PDFPageMetrics(
    characters=0,
    words=0,
    text_blocks=0,
    images=0,
    text_coverage=0.0,
    image_coverage=0.0,
    largest_image_coverage=0.0,
)
"""What a page measures when nothing could be measured.

Not a substitute for a measurement: it is what a page whose every capability failed
genuinely contains. ``classify_pdf_page`` is never called on it — a page that produced
nothing is reported as an error, not labelled ``MIXED``.
"""


def process_pdf(request: PDFRequest) -> PDFResult:
    """Process every page of a PDF and return the consolidated document result.

    Args:
        request: The document to process, its requested capabilities and its
            correlation context.

    Returns:
        The document result, with one :class:`~docflow.pdf.contracts.PDFPageResult` per
        page in page order and an aggregate
        :class:`~docflow.pdf.contracts.PDFPageMetrics`.

    Raises:
        NotImplementedError: ``PDF-10`` owns this entry point.

    # TODO: [MVP] implement the page loop and the aggregate consolidation (PDF-10).
    """
    raise NotImplementedError("process_pdf is implemented in Phase 1 by PDF-10")


def process_pdf_page(
    request: PDFRequest,
    page_number: int,
    output_dir: Path,
) -> PDFPageResult:
    """Process exactly one page of a PDF.

    Args:
        request: The document the page belongs to; its ``options`` decide which
            capabilities run.
        page_number: Page index, 1-based.
        output_dir: Directory for this page's artifacts (``page_NNN/``).

    Returns:
        The page result. When one capability fails while others succeed, the status is
        ``partial`` and the valid artifacts are preserved.

    Raises:
        ValueError: ``page_number`` is below 1.
        PDFPrimitiveError: The page does not exist. There is no partial result to keep when
            the page itself is not there, so this is the one failure that is raised rather
            than recorded.
    """
    started = time.perf_counter()
    timing: dict[str, float] = {}
    errors: list[PDFError] = []

    # The one capability whose failure is not contained: a page that does not exist has no
    # partial result to return, so `extract_page` raises and the caller gets the typed
    # failure. Every capability below records its failure instead.
    page_pdf = (
        extract_page(
            request.pdf_path, page_number, output_dir / SOURCE_DIR / PAGE_PDF_NAME
        )
        if request.options.extract_pages
        else None
    )

    page_image, image_timing = _render_stage(request, page_number, output_dir, errors)
    native_text, text_blocks, text_timing = _text_stage(
        request, page_number, output_dir, errors
    )
    embedded_images, image_extraction_timing = _images_stage(
        request, page_number, output_dir, errors
    )
    timing.update(image_timing, **text_timing, **image_extraction_timing)

    stage = time.perf_counter()
    metrics, classification = _measure(
        request, page_number, errors, native_text, text_blocks, embedded_images
    )
    timing["analyze"] = time.perf_counter() - stage
    timing["total"] = time.perf_counter() - started

    result = _assemble(
        request=request,
        page_number=page_number,
        timing=timing,
        errors=errors,
        page_pdf=page_pdf,
        page_image=page_image,
        native_text=native_text,
        text_blocks=text_blocks,
        embedded_images=embedded_images,
        metrics=metrics,
        classification=classification,
    )
    publish_json(output_dir / METADATA_NAME, _metadata_payload(result, request))
    return result


def _assemble(
    *,
    request: PDFRequest,
    page_number: int,
    timing: dict[str, float],
    errors: list[PDFError],
    page_pdf: Path | None,
    page_image: Path | None,
    native_text: Path | None,
    text_blocks: list[TextBlock],
    embedded_images: list[EmbeddedImage],
    metrics: PDFPageMetrics,
    classification: PDFPageClassification,
) -> PDFPageResult:
    """Build the page result and settle its verdict.

    The verdict is settled **here**, before the caller writes ``metadata.json``, so the file
    cannot disagree with the result it describes — an earlier version published the metadata
    with the provisional ``success`` while the in-memory result said ``partial``.

    Args:
        request: The request the page was processed under.
        page_number: Page index.
        timing: Wall-clock seconds by stage.
        errors: The failures recorded while processing.
        page_pdf: The one-page PDF, or ``None``.
        page_image: The render, or ``None``.
        native_text: The text artifact, or ``None``.
        text_blocks: The page's text blocks.
        embedded_images: The page's embedded images.
        metrics: The page's measurements.
        classification: The page's descriptive class.

    Returns:
        The result, with its validation, errors and status already final.
    """
    engine = get_engine()
    result = PDFPageResult(
        page_number=page_number,
        page_pdf=page_pdf,
        page_image=page_image,
        native_text=native_text,
        text_blocks=text_blocks,
        embedded_images=embedded_images,
        metrics=metrics,
        classification=classification,
        artifacts=_published_artifacts(
            page_pdf, page_image, native_text, embedded_images
        ),
        validation=PDFPageValidation(status="VALID", errors=[], missing_artifacts=[]),
        metadata=page_metadata(
            engine_name=engine.name,
            engine_version=engine.version,
            processor=processor_name(),
            processor_version=processor_version(),
            context=request.context,
            timing=timing,
        ),
        status="success",
    )

    validation = validate_pdf_page_result(result, errors, request.options)
    result.validation = validation
    result.errors = list(validation.errors)
    result.status = _status_for(validation)
    return result


def _render_stage(
    request: PDFRequest,
    page_number: int,
    output_dir: Path,
    errors: list[PDFError],
) -> tuple[Path | None, dict[str, float]]:
    """Render the page, recording a failure rather than raising it.

    Args:
        request: The request, for the document path and the requested DPI.
        page_number: Page index.
        output_dir: The page directory.
        errors: The failure list to append to.

    Returns:
        The render's path (or ``None``) and the stage's timing.
    """
    if not request.options.render:
        return None, {}

    started = time.perf_counter()
    render: Path | None = None
    try:
        render = render_page_to_image(
            request.pdf_path,
            page_number,
            output_dir / RENDER_DIR / PAGE_IMAGE_NAME,
            dpi=request.options.dpi,
        )
    except (PopplerError, PDFPrimitiveError) as failure:
        errors.append(_page_error(failure, page_number, "render", "RENDER_ERROR"))
    return render, {"render": time.perf_counter() - started}


def _text_stage(
    request: PDFRequest,
    page_number: int,
    output_dir: Path,
    errors: list[PDFError],
) -> tuple[Path | None, list[TextBlock], dict[str, float]]:
    """Extract and publish the page's native text and its blocks.

    The text and the blocks are one stage because they are one capability: publishing
    ``text.txt`` without ``blocks.json`` would leave the page's text namespace half-written,
    which is the partial artifact ``PDF-12`` exists to prevent.

    Args:
        request: The request, for the document path.
        page_number: Page index.
        output_dir: The page directory.
        errors: The failure list to append to.

    Returns:
        The text artifact's path (or ``None``), the blocks, and the stage's timing.
    """
    if not request.options.extract_text:
        return None, [], {}

    started = time.perf_counter()
    artifact: Path | None = None
    blocks: list[TextBlock] = []
    try:
        report = engine_report(request.pdf_path, page_number)
        artifact = publish_text(output_dir / NATIVE_TEXT_DIR / TEXT_NAME, report.text)
        blocks = get_text_blocks(request.pdf_path, page_number)
        publish_json(
            output_dir / NATIVE_TEXT_DIR / BLOCKS_NAME,
            [_block_payload(block) for block in blocks],
        )
    except (PopplerError, PDFPrimitiveError) as failure:
        errors.append(
            _page_error(failure, page_number, "extract_text", "TEXT_EXTRACTION_ERROR")
        )
    return artifact, blocks, {"extract_text": time.perf_counter() - started}


def _images_stage(
    request: PDFRequest,
    page_number: int,
    output_dir: Path,
    errors: list[PDFError],
) -> tuple[list[EmbeddedImage], dict[str, float]]:
    """Extract the page's embedded images, recording a failure rather than raising it.

    Args:
        request: The request, for the document path.
        page_number: Page index.
        output_dir: The page directory.
        errors: The failure list to append to.

    Returns:
        The extracted images and the stage's timing.
    """
    if not request.options.extract_images:
        return [], {}

    started = time.perf_counter()
    images: list[EmbeddedImage] = []
    try:
        images = extract_images_from_page(
            request.pdf_path, page_number, output_dir / EMBEDDED_IMAGES_DIR
        )
    except (PopplerError, PDFPrimitiveError) as failure:
        errors.append(
            _page_error(
                failure, page_number, "extract_images", "IMAGE_EXTRACTION_ERROR"
            )
        )
    return images, {"extract_images": time.perf_counter() - started}


def _measure(
    request: PDFRequest,
    page_number: int,
    errors: list[PDFError],
    native_text: Path | None,
    text_blocks: list[TextBlock],
    embedded_images: list[EmbeddedImage],
) -> tuple[PDFPageMetrics, PDFPageClassification]:
    """Measure and classify the page, or report why neither could be done.

    Args:
        request: The request, for the document path.
        page_number: Page index.
        errors: The failures collected so far, appended to when the page area is unknown.
        native_text: The published text artifact, or ``None``.
        text_blocks: The page's text blocks.
        embedded_images: The page's embedded images.

    Returns:
        The metrics and the descriptive classification. When the page's dimensions cannot be
        read there is nothing to divide by, so the metrics are the honest zeroes of a page
        that produced no measurement and the classification is ``MIXED`` — which asserts
        nothing about content, unlike ``TEXT`` or ``IMAGE`` would.
    """
    text = native_text.read_text(encoding="utf-8") if native_text is not None else ""

    try:
        dimensions = get_page_dimensions(request.pdf_path, page_number)
    except PDFPrimitiveError as failure:
        errors.append(_page_error(failure, page_number, "measure", "IO_ERROR"))
        return EMPTY_METRICS, "MIXED"

    metrics = analyze_pdf_page(
        PageContent(
            page_number=page_number,
            text=text,
            text_blocks=text_blocks,
            embedded_images=embedded_images,
            page_dimensions=dimensions,
        )
    )
    return metrics, classify_pdf_page(metrics)


def _page_error(
    failure: Exception,
    page_number: int,
    capability: str,
    error_type: PDFErrorType,
) -> PDFError:
    """Build a typed error for a capability that failed.

    Args:
        failure: What went wrong.
        page_number: Page the failure belongs to.
        capability: The capability that failed.
        error_type: The contract's classification to use.

    Returns:
        The error record, marked recoverable because the page keeps its other artifacts.
    """
    return PDFError(
        type=error_type,
        page_number=page_number,
        message=f"{capability} failed: {failure}",
        recoverable=True,
        metadata={"capability": capability},
    )


def _published_artifacts(
    page_pdf: Path | None,
    page_image: Path | None,
    native_text: Path | None,
    embedded_images: list[EmbeddedImage],
) -> list[Path]:
    """List every file this page actually published, in a stable order.

    Args:
        page_pdf: The one-page PDF, or ``None``.
        page_image: The render, or ``None``.
        native_text: The text artifact, or ``None``.
        embedded_images: The extracted images.

    Returns:
        The published paths. Only real files are listed: an artifact field that points at
        nothing must not appear as though it were produced.
    """
    images = [image.path for image in embedded_images]
    blocks = native_text.parent / BLOCKS_NAME if native_text is not None else None
    candidates = [page_pdf, page_image, native_text, blocks, *images]
    return [path for path in candidates if path is not None and path.exists()]


def _block_payload(block: TextBlock) -> dict[str, object]:
    """Render a ``TextBlock`` as a JSON-serialisable object.

    Args:
        block: The block to serialise.

    Returns:
        Its fields, with the bounding box as a list so it survives JSON unchanged. ``None``
        stays ``None``: a block with no placement must not acquire a fabricated one.
    """
    return {
        "block_id": block.block_id,
        "text": block.text,
        "bbox": list(block.bbox) if block.bbox is not None else None,
        "page_number": block.page_number,
    }


def _metadata_payload(result: PDFPageResult, request: PDFRequest) -> dict[str, object]:
    """Build the page's ``metadata.json`` payload.

    Args:
        result: The page result.
        request: The request the page was processed under.

    Returns:
        The payload, carrying the provenance keys ``docflow.identities`` requires plus the
        options the page was processed with and the classification as data.

    Note:
        ``processing_key`` is recorded as ``None``. It is computed by ``ORC-02`` in Phase 2
        from normalized options and input hashes the orchestrator owns, and a processor that
        hashed its own would be making a workflow decision — see
        :mod:`docflow.pdf.primitives.provenance`. The key is present so a consumer can see it
        was not computed, which is not the same as it being absent.
    """
    return {
        "processor": result.metadata.processor,
        "processor_version": result.metadata.processor_version,
        "engine": result.metadata.engine,
        "engine_version": result.metadata.engine_version,
        "document_id": request.context.document_id,
        "workflow_run_id": request.context.workflow_run_id,
        "processing_key": None,
        "page_number": result.page_number,
        "directory": page_index_name(result.page_number),
        "status": result.status,
        "validation": result.validation.status,
        "classification": result.classification,
        "metrics": {
            "characters": result.metrics.characters,
            "words": result.metrics.words,
            "text_blocks": result.metrics.text_blocks,
            "images": result.metrics.images,
            "text_coverage": result.metrics.text_coverage,
            "image_coverage": result.metrics.image_coverage,
            "largest_image_coverage": result.metrics.largest_image_coverage,
        },
        "options": {
            "extract_pages": request.options.extract_pages,
            "render": request.options.render,
            "extract_text": request.options.extract_text,
            "extract_images": request.options.extract_images,
            "layout": request.options.layout,
            "dpi": request.options.dpi,
        },
        "errors": [
            {
                "type": error.type,
                "message": error.message,
                "recoverable": error.recoverable,
                "metadata": error.metadata,
            }
            for error in result.errors
        ],
        "artifacts": [str(path) for path in result.artifacts],
        "timing": result.metadata.timing,
    }


def _status_for(validation: PDFPageValidation) -> PDFStatus:
    """Map a validation verdict onto the page's status.

    Args:
        validation: The verdict.

    Returns:
        ``success`` for a valid page, ``partial`` when some artifacts survived, ``failed``
        when none did.
    """
    if validation.status == "VALID":
        return "success"
    if validation.status in ("PARTIAL",):
        return "partial"
    return "failed"


__all__ = ["process_pdf", "process_pdf_page"]
