"""Contract-level fake processors (``ORC-19``).

These four doubles replace **whole processors**, at the public entry point the
orchestrator calls (``docflow.pdf.process_pdf`` and its three siblings). They are not the
engine doubles of ``tests/fakes/engines/``: those replace the *engine call inside* a real
processor. Neither can stand in for the other, and nothing here reaches an engine.

Each double does three things a real processor does:

* counts its calls, so a test can prove a stage did **not** run;
* writes real files under the request's output directory, so the orchestrator's artifact
  digests and its reuse rule have something real to check;
* returns the processor's own typed result, so the orchestrator is exercised through the
  contract and never around it.

Their content is deterministic: the same request twice produces byte-identical artifacts,
which is what makes "reuse" and "re-execute" distinguishable by a counter instead of by a
timestamp.
"""

from __future__ import annotations

# pylint: disable=duplicate-code
# Reason: the fake's geometry helper assembles the same ``ArtifactRef`` the image
# processor's seam does, and test code may not import that seam to share the construction —
# nothing under ``src/docflow/`` may import anything under ``tests/``, so the double stands
# beside the production module rather than on top of it.
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pytest

from docflow.image import (
    ArtifactRef,
    ImageDimensions,
    ImageError,
    ImageMetadata,
    ImageMetrics,
    ImageQualityMetrics,
    ImageRequest,
    ImageResult,
    ImageSourceRef,
    ImageValidation,
    ImageVariants,
)
from docflow.llm import (
    LLMError,
    LLMInput,
    LLMResult,
)
from docflow.ocr import (
    ArtifactPaths,
    BlockResult,
    LayoutResult,
    NormalizedOCROptions,
    OCRDocument,
    OCRError,
    OCRMetadata,
    OCRMetrics,
    OCRRequest,
    OCRResult,
    OCRValidation,
)
from docflow.pdf import (
    PDFMetadata,
    PDFPageMetadata,
    PDFPageMetrics,
    PDFPageResult,
    PDFPageValidation,
    PDFRequest,
    PDFResult,
    PDFValidation,
    TextBlock,
)
from docflow.states import StageState
from tests.llm.samples import build_result

#: Where each double is installed. The orchestrator resolves these attributes at call
#: time, so patching the module attribute is enough — and is the only seam it offers.
PATCH_TARGETS: dict[str, str] = {
    "pdf": "docflow.pdf.process_pdf",
    "image": "docflow.image.process_image",
    "ocr": "docflow.ocr.process_ocr_image",
    "llm": "docflow.llm.process_llm_request",
}

PROCESSOR_VERSION = "0.0.0"


def _write(path: Path, payload: bytes) -> Path:
    """Write bytes to a path, creating its parent."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


@dataclass
class FakePdf:
    """A whole PDF processor, deterministic and counted."""

    pages: int = 1
    text: str = "Native text of the page."
    calls: int = field(default=0, init=False)
    requests: list[PDFRequest] = field(default_factory=list, init=False)

    def __call__(self, request: PDFRequest) -> PDFResult:
        """Return a scripted document with ``pages`` pages of native text."""
        self.calls += 1
        self.requests.append(request)
        output = request.output_dir
        source = output / "source.pdf"
        _write(
            source,
            request.pdf_path.read_bytes()
            if request.pdf_path.is_file()
            else b"%PDF-1.4\n",
        )
        artifacts = [source]
        results: list[PDFPageResult] = []
        for number in range(1, self.pages + 1):
            results.append(self._page(request, number, artifacts))
        return PDFResult(
            source_path=request.pdf_path,
            metadata=PDFMetadata(
                processor="pdf",
                processor_version=PROCESSOR_VERSION,
                engine="poppler",
                engine_version="fake",
                page_count=self.pages,
                context=request.context,
                timing={"total": 0.0},
            ),
            pages=results,
            metrics=PDFPageMetrics(
                characters=len(self.text) * self.pages,
                words=len(self.text.split()) * self.pages,
                text_blocks=self.pages,
                images=0,
                text_coverage=0.5,
                image_coverage=0.0,
                largest_image_coverage=0.0,
            ),
            artifacts=artifacts,
            validation=PDFValidation(status="VALID", errors=[], missing_artifacts=[]),
            status="success",
            errors=[],
        )

    def _page(
        self, request: PDFRequest, number: int, artifacts: list[Path]
    ) -> PDFPageResult:
        """Build one page's result and publish its artifacts."""
        directory = request.output_dir / f"page_{number:03d}"
        page_pdf = _write(directory / "page.pdf", b"%PDF-1.4\n" + bytes([number]))
        page_image = _write(
            directory / "page.png", b"\x89PNG\r\n\x1a\n" + bytes([number])
        )
        native_text = directory / "text.txt"
        native_text.parent.mkdir(parents=True, exist_ok=True)
        native_text.write_text(self.text, encoding="utf-8")
        artifacts.extend([page_pdf, page_image, native_text])
        return PDFPageResult(
            page_number=number,
            page_pdf=page_pdf,
            page_image=page_image,
            native_text=native_text,
            text_blocks=[
                TextBlock(
                    block_id=f"block-{number}",
                    text=self.text,
                    bbox=(0.0, 0.0, 10.0, 10.0),
                    page_number=number,
                )
            ],
            embedded_images=[],
            metrics=PDFPageMetrics(
                characters=len(self.text),
                words=len(self.text.split()),
                text_blocks=1,
                images=0,
                text_coverage=0.5,
                image_coverage=0.0,
                largest_image_coverage=0.0,
            ),
            classification="TEXT",
            artifacts=[page_pdf, page_image, native_text],
            validation=PDFPageValidation(
                status="VALID", errors=[], missing_artifacts=[]
            ),
            metadata=PDFPageMetadata(
                processor="pdf",
                processor_version=PROCESSOR_VERSION,
                engine="poppler",
                engine_version="fake",
                context=request.context,
                timing={"total": 0.0},
            ),
            status="success",
        )


@dataclass
class FakeImage:
    """A whole image processor, deterministic and counted."""

    fail: bool = False
    calls: int = field(default=0, init=False)
    requests: list[ImageRequest] = field(default_factory=list, init=False)

    def __call__(self, request: ImageRequest) -> ImageResult:
        """Return the three representations, or a typed failure when scripted to."""
        self.calls += 1
        self.requests.append(request)
        output = request.output_dir
        if self.fail:
            return _failed_image(request)
        normalized = _write(output / "normalized.png", b"\x89PNG\r\n\x1a\nnormalized")
        ocr_ready = _write(output / "ocr_ready.png", b"\x89PNG\r\n\x1a\nocr")
        vlm_ready = _write(output / "vlm_ready.png", b"\x89PNG\r\n\x1a\nvlm")
        width, height, size = 160, 120, len(b"\x89PNG\r\n\x1a\n")
        references = [
            _reference(normalized, "normalized", width, height, size),
            _reference(ocr_ready, "ocr_ready", width, height, size),
            _reference(vlm_ready, "vlm_ready", width, height, size),
        ]
        metrics = _image_metrics()
        return ImageResult(
            source=ImageSourceRef(
                path=request.image_path,
                width=width,
                height=height,
                format="PNG",
                size=size,
            ),
            normalized=references[0],
            variants=ImageVariants(ocr_ready=references[1], vlm_ready=references[2]),
            metrics=metrics,
            classification="TEXT_IMAGE",
            transformations=["normalize"],
            validation=ImageValidation(status="VALID", errors=[], missing_artifacts=[]),
            artifacts=references,
            metadata=ImageMetadata(
                processor="image",
                processor_version=PROCESSOR_VERSION,
                engine="opencv",
                engine_version="fake",
                libraries={"opencv": "fake"},
                options=request.options,
                input_metrics=metrics,
                output_metrics=metrics,
                timing={"total": 0.0},
                context=request.context,
            ),
            status="success",
            error=None,
        )


@dataclass
class FakeOcr:
    """A whole OCR processor, deterministic and counted."""

    text: str = "Extracted text from OCR."
    fail: bool = False
    calls: int = field(default=0, init=False)
    requests: list[OCRRequest] = field(default_factory=list, init=False)

    def __call__(self, request: OCRRequest) -> OCRResult:
        """Return an extraction with text, markdown and a structured document."""
        self.calls += 1
        self.requests.append(request)
        output = request.output_dir
        if self.fail:
            return _failed_ocr()
        text = _write(output / "text.txt", self.text.encode("utf-8"))
        markdown = _write(output / "document.md", f"# Page\n\n{self.text}".encode())
        tables_dir = output / "tables"
        tables_dir.mkdir(parents=True, exist_ok=True)
        document = OCRDocument(
            text=self.text,
            paragraphs=[self.text],
            titles=[],
            blocks=[
                BlockResult(
                    block_id="block-1",
                    type="paragraph",
                    text=self.text,
                    bbox=(0.0, 0.0, 1.0, 1.0),
                    level=None,
                )
            ],
            tables=[],
            layout=LayoutResult(
                page_width=1.0, page_height=1.0, region_bboxes=[(0.0, 0.0, 1.0, 1.0)]
            ),
            reading_order=["block-1"],
            metadata={},
        )
        structured_document = _write_json(output / "document.json", asdict(document))
        metrics = OCRMetrics(
            characters=len(self.text),
            words=len(self.text.split()),
            blocks=1,
            tables=0,
            paragraphs=1,
            text_density=1.0,
            empty=False,
            structure_detected=True,
        )
        validation = OCRValidation(status="VALID", errors=[], missing_artifacts=[])
        metadata = OCRMetadata(
            engine="docling",
            engine_version="fake",
            processor_version=PROCESSOR_VERSION,
            options=NormalizedOCROptions(
                ocr=request.options.ocr,
                layout=request.options.layout,
                tables=request.options.tables,
                reading_order=request.options.reading_order,
                language=request.options.language,
                engine_options=dict(request.options.engine_options),
            ),
            input=request.image_path,
            metrics=metrics,
            validation=validation,
            timing={"total": 0.0},
            transformations=[],
            context=request.context,
        )
        metadata_path = _write_json(output / "metadata.json", {"processor": "ocr"})
        return OCRResult(
            text=self.text,
            markdown=f"# Page\n\n{self.text}",
            structured_document=structured_document,
            tables=[],
            blocks=list(document.blocks),
            layout=document.layout,
            reading_order=list(document.reading_order),
            metrics=metrics,
            artifacts=ArtifactPaths(
                text=text,
                markdown=markdown,
                structured_document=structured_document,
                tables_dir=tables_dir,
                metadata=metadata_path,
            ),
            validation=validation,
            metadata=metadata,
            status="success",
            error=None,
        )


@dataclass
class FakeLlm:
    """A whole LLM processor, deterministic and counted."""

    result: dict[str, object] = field(
        default_factory=lambda: {"fields": {"total": "42.00"}}
    )
    fail: bool = False
    calls: int = field(default=0, init=False)
    requests: list[LLMInput] = field(default_factory=list, init=False)

    def __call__(self, request: LLMInput) -> LLMResult:
        """Return a parsed response, or a typed failure when scripted to."""
        self.calls += 1
        self.requests.append(request)
        if self.fail:
            error = LLMError(
                type="PROVIDER_ERROR",
                message="the fake provider refused",
                recoverable=False,
                metadata={},
            )
            return build_result(
                request,
                run_id="fake-run",
                schema_valid=False,
                validation_errors=[error.message],
                errors=[error],
                status=StageState.FAILED,
                metadata=dict(request.metadata),
            )
        return build_result(
            request,
            run_id="fake-run",
            raw_response=json.dumps(self.result),
            parsed_response=self.result,
            metadata=dict(request.metadata),
        )


@dataclass
class ProcessorDoubles:
    """The four contract-level doubles, installed together."""

    pdf: FakePdf = field(default_factory=FakePdf)
    image: FakeImage = field(default_factory=FakeImage)
    ocr: FakeOcr = field(default_factory=FakeOcr)
    llm: FakeLlm = field(default_factory=FakeLlm)

    def install(self, monkeypatch: pytest.MonkeyPatch) -> ProcessorDoubles:
        """Install every double at its processor's public entry point."""
        for name, target in PATCH_TARGETS.items():
            monkeypatch.setattr(target, getattr(self, name))
        return self

    def calls(self) -> dict[str, int]:
        """Return each double's call count, for a test that asserts what did not run."""
        return {
            "pdf": self.pdf.calls,
            "image": self.image.calls,
            "ocr": self.ocr.calls,
            "llm": self.llm.calls,
        }


def _write_json(path: Path, payload: object) -> Path:
    """Write a JSON artifact and return its path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return path


def _reference(
    path: Path, kind: str, width: int, height: int, size: int
) -> ArtifactRef:
    """Build an image artifact reference."""
    return ArtifactRef(
        path=path,
        kind=kind,  # type: ignore[arg-type]
        width=width,
        height=height,
        format="PNG",
        size=size,
    )


def _image_metrics() -> ImageMetrics:
    """Return a deterministic set of image measurements."""
    return ImageMetrics(
        dimensions=ImageDimensions(width=160, height=120),
        resolution=300,
        format="PNG",
        size=8,
        quality=ImageQualityMetrics(
            blur=1.0, sharpness=1.0, contrast=1.0, brightness=1.0, noise=1.0
        ),
        orientation=0,
        skew=0.0,
        text_regions=[],
        text_coverage=0.5,
    )


def _failed_image(request: ImageRequest) -> ImageResult:
    """Return the typed failure of an image processor that could not decode."""
    error = ImageError(
        type="DECODE_ERROR",
        message="the fake refused to decode",
        recoverable=False,
        metadata={},
    )
    return ImageResult(
        source=ImageSourceRef(
            path=request.image_path,
            width=None,
            height=None,
            format="PNG",
            size=None,
        ),
        normalized=None,
        variants=ImageVariants(ocr_ready=None, vlm_ready=None),
        metrics=None,
        classification=None,
        transformations=[],
        validation=ImageValidation(
            status="ERROR", errors=[error], missing_artifacts=[]
        ),
        artifacts=[],
        metadata=ImageMetadata(
            processor="image",
            processor_version=PROCESSOR_VERSION,
            engine="opencv",
            engine_version=None,
            libraries={},
            options=request.options,
            input_metrics=None,
            output_metrics=None,
            timing={"total": 0.0},
            context=request.context,
        ),
        status="failed",
        error=error,
    )


def _failed_ocr() -> OCRResult:
    """Return the typed failure of an OCR processor that could not read the page."""
    error = OCRError(
        type="ENGINE_ERROR",
        message="the fake refused to read the image",
        recoverable=False,
        metadata={},
    )
    return OCRResult(
        text=None,
        markdown=None,
        structured_document=None,
        tables=None,
        blocks=None,
        layout=None,
        reading_order=None,
        metrics=None,
        artifacts=None,
        validation=OCRValidation(status="ERROR", errors=[error], missing_artifacts=[]),
        metadata=None,
        status="failed",
        error=error,
    )
