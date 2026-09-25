"""Entry points of the PDF processor.

The signatures are frozen by ``docs/plan/README.md`` §4 (the idea's §"Naming"): ``pdf``
exposes ``process_pdf()`` and ``process_pdf_page()``. Both return a typed result: a failure
is described in a ``PDFError`` inside the result, never thrown across the contract.

Where the artifacts go — ``request.output_dir`` is the document directory the namespace
diagram calls ``document/``:

```
output_dir/
├── source/document.pdf           reference copy of the input; the input itself is never touched
├── metadata.json
└── page_001/
    ├── source/page.pdf
    ├── render/page.png
    ├── native_text/text.txt
    ├── native_text/blocks.json
    ├── embedded_images/image_001.png
    └── metadata.json
```

Nothing is written outside those namespaces, and everything is published atomically.

``process_pdf_page`` is a real entry point, not a private step of the document loop: it can
process one page on its own, so it inspects the document once to learn that page's geometry.
``# TODO: [MVP]``: pass the inspected document down once the contract can carry it, so a
page is not re-inspected inside a full document run.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any, Final, TypeVar

from docflow.pdf.contracts import (
    EmbeddedImage,
    PDFError,
    PDFMetadata,
    PDFOptions,
    PDFPageMetadata,
    PDFPageMetrics,
    PDFPageResult,
    PDFPageValidation,
    PDFRequest,
    PDFResult,
    PDFStatus,
    PDFValidation,
    TextBlock,
)
from docflow.pdf.primitives import (
    ENGINE_NAME,
    PDFPageData,
    PDFPrimitiveError,
    analyze_pdf_page,
    classify_pdf_page,
    extract_images_from_page,
    extract_page,
    extract_text_from_page,
    for_page,
    inspect_pdf,
    poppler_version,
    publish_file,
    publish_json,
    publish_text,
    render_page_to_image,
    validate_pdf,
    validate_pdf_page_result,
    validate_pdf_result,
)

#: Name recorded as ``processor`` in every artifact's metadata.
PROCESSOR_NAME: Final[str] = "pdf"

#: Version recorded as ``processor_version`` in every artifact's metadata. A test asserts
#: it matches ``pyproject.toml``: the provenance an artifact carries has to name the code
#: that produced it.
PROCESSOR_VERSION: Final[str] = "0.0.0"

#: Artifact names, fixed so a reader never has to guess what a file is.
PAGE_PDF_NAME: Final[Path] = Path("source") / "page.pdf"
PAGE_IMAGE_NAME: Final[Path] = Path("render") / "page.png"
PAGE_TEXT_NAME: Final[Path] = Path("native_text") / "text.txt"
PAGE_BLOCKS_NAME: Final[Path] = Path("native_text") / "blocks.json"
PAGE_METADATA_NAME: Final[Path] = Path("metadata.json")
EMBEDDED_IMAGES_DIRECTORY: Final[Path] = Path("embedded_images")
DOCUMENT_SOURCE_NAME: Final[Path] = Path("source") / "document.pdf"
DOCUMENT_METADATA_NAME: Final[Path] = Path("metadata.json")

#: The geometry of a page that could not be measured. It is not a guessed size: a page with
#: no known geometry reports coverages of zero, and the failure that caused it is recorded.
UNKNOWN_GEOMETRY: Final[tuple[float, float]] = (0.0, 0.0)

T = TypeVar("T")


@dataclass
class _PageArtifacts:
    """What a page's stages produced.

    A stage that fails leaves its field untouched, which is how a partial page keeps only
    the artifacts that are real. ``text`` stays empty until the text stage runs: a
    capability the caller did not request contributes nothing to the measurements, and the
    classification describes the composition that was actually extracted.

    Attributes:
        page_pdf: The one-page PDF, or ``None`` when it was not produced.
        page_image: The rendered PNG, or ``None`` when it was not produced.
        native_text: The extracted text file, or ``None`` when it was not produced.
        text: The extracted text itself, for the measurements.
        text_blocks: Native text blocks in reading order.
        embedded_images: Extracted embedded images, in scan order.
        published: Every file the page published, in publication order.
    """

    page_pdf: Path | None = None
    page_image: Path | None = None
    native_text: Path | None = None
    text: str = ""
    text_blocks: list[TextBlock] = field(default_factory=list)
    embedded_images: list[EmbeddedImage] = field(default_factory=list)
    published: list[Path] = field(default_factory=list)


def _attempt(
    failures: list[PDFError],
    page_number: int,
    action: Callable[..., T],
    *arguments: Any,
) -> T | None:
    """Run one stage, recording a typed failure instead of raising it.

    Args:
        failures: The page's failure list, which this call appends to.
        page_number: Page being processed; stamped onto whatever surfaces.
        action: The primitive to run.
        arguments: Its arguments.

    Returns:
        What the stage produced, or ``None`` when it failed — the caller keeps whatever
        other stages produced and the failure explains the gap.
    """
    try:
        return action(*arguments)
    except PDFPrimitiveError as failure:
        failures.append(for_page(failure.error, page_number))
        return None


def _file_digest(path: Path) -> str:
    """Return the SHA-256 of a file, read in bounded chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalized_options(options: PDFOptions) -> dict[str, object]:
    """Return the options in canonical form, one key per capability.

    Canonical rather than raw, so two spellings of the same configuration produce the same
    record — and therefore the same processing key.
    """
    return {
        "dpi": options.dpi,
        "extract_images": options.extract_images,
        "extract_pages": options.extract_pages,
        "extract_text": options.extract_text,
        "layout": options.layout,
        "render": options.render,
    }


def _processing_key(request: PDFRequest) -> str:
    """Return this unit of work's key, per the documented formula.

    ``hash(processor + processor_version + input_hashes + normalized_options)``, with the run
    identity deliberately absent: a new run over unchanged inputs must reproduce the key.

    # TODO: [MVP] the orchestrator mints the document-level key (`ORC-02`); this
    # processor-local record makes the artifact self-describing until both are reconciled
    # at Phase 2.
    """
    material = "|".join(
        (
            PROCESSOR_NAME,
            PROCESSOR_VERSION,
            _file_digest(request.pdf_path),
            json.dumps(_normalized_options(request.options), sort_keys=True),
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _identity_payload(
    request: PDFRequest, engine_version: str | None
) -> dict[str, Any]:
    """Return the keys every artifact ``metadata.json`` must record.

    ``engine_version`` is ``None`` when no engine call was reached; it is never a
    placeholder standing in for a version nobody read.
    """
    return {
        "processor": PROCESSOR_NAME,
        "processor_version": PROCESSOR_VERSION,
        "engine": ENGINE_NAME,
        "engine_version": engine_version,
        "document_id": request.context.document_id,
        "workflow_run_id": request.context.workflow_run_id,
        "processing_key": _processing_key(request),
    }


def _aggregate_metrics(pages: list[PDFPageResult]) -> PDFPageMetrics:
    """Return the document's metrics: counts summed over pages, coverages averaged."""
    return PDFPageMetrics(
        characters=sum(page.metrics.characters for page in pages),
        words=sum(page.metrics.words for page in pages),
        text_blocks=sum(page.metrics.text_blocks for page in pages),
        images=sum(page.metrics.images for page in pages),
        text_coverage=_mean([page.metrics.text_coverage for page in pages]),
        image_coverage=_mean([page.metrics.image_coverage for page in pages]),
        largest_image_coverage=_mean(
            [page.metrics.largest_image_coverage for page in pages]
        ),
    )


def _mean(values: list[float]) -> float:
    """Return the arithmetic mean, or ``0.0`` when there is nothing to average."""
    return sum(values) / len(values) if values else 0.0


def _page_status(errors: list[PDFError], published: list[Path]) -> PDFStatus:
    """Return the page's outcome from its recorded failures and what it published."""
    if not errors:
        return "success"
    return "partial" if published else "failed"


def _document_status(pages: list[PDFPageResult], errors: list[PDFError]) -> PDFStatus:
    """Return the document's outcome from its pages and its own failures.

    A document that produced no page at all is a failure, not a success over nothing.
    """
    if errors:
        return "failed"
    if pages and all(page.status == "success" for page in pages):
        return "success"
    if any(page.status in {"success", "partial"} for page in pages):
        return "partial"
    return "failed"


def _failed_document(
    request: PDFRequest,
    error: PDFError,
    started: float,
    engine_version: str | None,
) -> PDFResult:
    """Return the result of a document that failed before producing any artifact.

    Nothing is published: an artifact tree that only describes a failure is exactly the
    partially written output the atomic-publication rule exists to prevent. The aggregate
    metrics are the counts over the zero pages that were produced.
    """
    return PDFResult(
        source_path=request.pdf_path,
        metadata=PDFMetadata(
            processor=PROCESSOR_NAME,
            processor_version=PROCESSOR_VERSION,
            engine=ENGINE_NAME,
            engine_version=engine_version,
            page_count=0,
            context=request.context,
            timing={"total": perf_counter() - started},
        ),
        pages=[],
        metrics=PDFPageMetrics(
            characters=0,
            words=0,
            text_blocks=0,
            images=0,
            text_coverage=0.0,
            image_coverage=0.0,
            largest_image_coverage=0.0,
        ),
        artifacts=[],
        validation=PDFValidation(status="ERROR", errors=[error], missing_artifacts=[]),
        status="failed",
        errors=[error],
    )


def _build_page_result(
    request: PDFRequest,
    page_number: int,
    output_dir: Path,
    produced: _PageArtifacts,
    failures: list[PDFError],
    engine_version: str | None,
    page_size: tuple[float, float],
    started: float,
    *,
    publish_metadata: bool,
) -> PDFPageResult:
    """Assemble one page result, publish its metadata and validate it."""
    metrics = analyze_pdf_page(
        PDFPageData(
            page_number=page_number,
            page_width=page_size[0],
            page_height=page_size[1],
            text=produced.text,
            text_blocks=produced.text_blocks,
            embedded_images=produced.embedded_images,
        )
    )
    result = PDFPageResult(
        page_number=page_number,
        page_pdf=produced.page_pdf,
        page_image=produced.page_image,
        native_text=produced.native_text,
        text_blocks=produced.text_blocks,
        embedded_images=produced.embedded_images,
        metrics=metrics,
        classification=classify_pdf_page(metrics),
        artifacts=list(produced.published),
        # The failure list is shared rather than copied on purpose: publishing the page's
        # own metadata happens below, and a failure there has to reach the validation
        # record instead of being dropped between the two steps.
        validation=PDFPageValidation(
            status="VALID", errors=failures, missing_artifacts=[]
        ),
        metadata=PDFPageMetadata(
            processor=PROCESSOR_NAME,
            processor_version=PROCESSOR_VERSION,
            engine=ENGINE_NAME,
            engine_version=engine_version,
            context=request.context,
            timing={"total": perf_counter() - started},
        ),
        status=_page_status(failures, produced.published),
    )

    if publish_metadata:
        payload = {
            **_identity_payload(request, engine_version),
            "page_number": page_number,
            "page_width": page_size[0],
            "page_height": page_size[1],
            "dpi": request.options.dpi,
            "classification": result.classification,
            "metrics": asdict(result.metrics),
            "options": _normalized_options(request.options),
        }
        metadata_path = _attempt(
            failures,
            page_number,
            publish_json,
            output_dir / PAGE_METADATA_NAME,
            payload,
        )
        if metadata_path is not None:
            result.artifacts.append(metadata_path)

    result.validation = validate_pdf_page_result(result)
    result.status = _page_status(result.validation.errors, result.artifacts)
    return result


def process_pdf(request: PDFRequest) -> PDFResult:
    """Process every page of a PDF and return the consolidated document result.

    Args:
        request: The document to process, its requested capabilities and its
            correlation context. ``request.output_dir`` is the document directory.

    Returns:
        The document result, with one :class:`~docflow.pdf.contracts.PDFPageResult` per
        page in page order and an aggregate
        :class:`~docflow.pdf.contracts.PDFPageMetrics`. ``status`` is ``"success"`` when
        every page succeeded, ``"partial"`` when some did, and ``"failed"`` when the
        document could not be produced at all. A failure is reported in ``errors``; it is
        never raised.
    """
    started = perf_counter()
    engine_version: str | None = None

    # TODO: [MVP] per-document validation is structural and bounded (header, trailer, the
    # engine's own report); a semantic check of the document's content is deferred.
    # TODO: [RELEASE] resource caps for very large documents: pages are processed one at a
    # time, but a page whose render is enormous is not bounded.
    try:
        validate_pdf(request.pdf_path)
        engine_version = poppler_version()
        document = inspect_pdf(request.pdf_path)
    except PDFPrimitiveError as failure:
        return _failed_document(request, failure.error, started, engine_version)

    pages = [
        process_pdf_page(
            request, page_number, request.output_dir / f"page_{page_number:03d}"
        )
        for page_number in range(1, document.page_count + 1)
    ]

    errors: list[PDFError] = []
    artifacts: list[Path] = []
    try:
        artifacts.append(
            publish_file(request.pdf_path, request.output_dir / DOCUMENT_SOURCE_NAME)
        )
    except PDFPrimitiveError as failure:
        errors.append(failure.error)

    result = PDFResult(
        source_path=request.pdf_path,
        metadata=PDFMetadata(
            processor=PROCESSOR_NAME,
            processor_version=PROCESSOR_VERSION,
            engine=ENGINE_NAME,
            engine_version=engine_version,
            page_count=document.page_count,
            context=request.context,
            timing={"total": perf_counter() - started},
        ),
        pages=pages,
        metrics=_aggregate_metrics(pages),
        artifacts=[
            *artifacts,
            *(path for page in pages for path in page.artifacts),
        ],
        validation=PDFValidation(status="VALID", errors=[], missing_artifacts=[]),
        status=_document_status(pages, errors),
        errors=errors,
    )

    try:
        result.artifacts.append(
            publish_json(
                request.output_dir / DOCUMENT_METADATA_NAME,
                {
                    **_identity_payload(request, engine_version),
                    "page_count": document.page_count,
                    "source_path": str(request.pdf_path),
                    "source_sha256": _file_digest(request.pdf_path),
                    "options": _normalized_options(request.options),
                    "engine_metadata": document.engine_metadata,
                    "page_dimensions": [
                        [width, height] for width, height in document.page_dimensions
                    ],
                    "metrics": asdict(result.metrics),
                },
            )
        )
    except PDFPrimitiveError as failure:
        # The document's own artifact tree is incomplete, so the run reports that rather
        # than a success with a missing file.
        result.errors.append(failure.error)
        result.status = "failed"

    result.validation = validate_pdf_result(result)
    return result


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
        ``"partial"``, the valid artifacts are preserved and the failure is recorded in
        ``validation.errors`` with its ``recoverable`` flag. A page outside the document,
        or one whose document cannot be inspected, is ``"failed"`` and publishes nothing.
    """
    started = perf_counter()
    options = request.options
    failures: list[PDFError] = []
    produced = _PageArtifacts()

    document = _attempt(failures, page_number, inspect_pdf, request.pdf_path)
    if document is None:
        return _build_page_result(
            request,
            page_number,
            output_dir,
            produced,
            failures,
            None,
            UNKNOWN_GEOMETRY,
            started,
            publish_metadata=False,
        )

    if not 1 <= page_number <= document.page_count:
        # The page range is decided here, before any engine call: the engine clamps a low
        # page silently and rejects an impossible range generically, so leaving it to the
        # engine could render a neighbour's page and report it as this one.
        failures.append(
            PDFError(
                type="INVALID_INPUT",
                page_number=page_number,
                message=f"page {page_number} is outside 1..{document.page_count}",
                recoverable=False,
                metadata={"page_count": document.page_count},
            )
        )
        return _build_page_result(
            request,
            page_number,
            output_dir,
            produced,
            failures,
            None,
            UNKNOWN_GEOMETRY,
            started,
            publish_metadata=False,
        )

    engine_version = _attempt(failures, page_number, poppler_version)
    page_size = document.page_dimensions[page_number - 1]

    if options.extract_pages:
        produced.page_pdf = _attempt(
            failures,
            page_number,
            extract_page,
            request.pdf_path,
            page_number,
            output_dir / PAGE_PDF_NAME,
        )
        if produced.page_pdf is not None:
            produced.published.append(produced.page_pdf)

    if options.render:
        produced.page_image = _attempt(
            failures,
            page_number,
            render_page_to_image,
            request.pdf_path,
            page_number,
            output_dir / PAGE_IMAGE_NAME,
            options.dpi,
        )
        if produced.page_image is not None:
            produced.published.append(produced.page_image)

    if options.extract_text:
        extracted = _attempt(
            failures,
            page_number,
            extract_text_from_page,
            request.pdf_path,
            page_number,
            options.layout,
        )
        if extracted is not None:
            produced.text, produced.text_blocks = extracted
            produced.native_text = _attempt(
                failures,
                page_number,
                publish_text,
                output_dir / PAGE_TEXT_NAME,
                produced.text,
            )
            if produced.native_text is not None:
                produced.published.append(produced.native_text)
            blocks = _attempt(
                failures,
                page_number,
                publish_json,
                output_dir / PAGE_BLOCKS_NAME,
                {"blocks": [asdict(block) for block in produced.text_blocks]},
            )
            if blocks is not None:
                produced.published.append(blocks)

    if options.extract_images:
        extracted_images = _attempt(
            failures,
            page_number,
            extract_images_from_page,
            request.pdf_path,
            page_number,
            output_dir / EMBEDDED_IMAGES_DIRECTORY,
        )
        if extracted_images is not None:
            produced.embedded_images = extracted_images
            produced.published.extend(image.path for image in extracted_images)

    return _build_page_result(
        request,
        page_number,
        output_dir,
        produced,
        failures,
        engine_version,
        page_size,
        started,
        publish_metadata=True,
    )
