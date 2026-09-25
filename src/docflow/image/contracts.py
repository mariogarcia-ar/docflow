"""Contract types of the image processor: ``ImageRequest → ImageResult``.

This module is vocabulary only. It performs no I/O, imports no engine and contains no
processing logic; OpenCV is reached exclusively from :mod:`docflow.image.primitives`.

``context`` is correlation and tracing data. It is never read as workflow state — this
processor never decides whether OCR or a VLM should run next.

**Absence is stated, never faked.** A run can fail before anything is measured — an absent
file, a format this processor does not read, a decode the engine refused. Every field that
would then hold a measurement (``ImageSourceRef.width``/``height``,
``ImageMetadata.engine_version``, ``ImageMetadata.input_metrics``/``output_metrics``,
``ImageResult.metrics``/``classification``) is typed ``X | None`` and says ``None`` in that
case: a ``0``, an empty ref or a default classification would read as an answer nobody
observed. No such field carries a default, so ``None`` is always passed deliberately.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

ImageStatus = Literal["success", "failed"]

# Technical classification of the prepared image. Descriptive: it never routes.
ImageClassification = Literal[
    "TEXT_IMAGE", "VISUAL_IMAGE", "MIXED_IMAGE", "LOW_QUALITY"
]

# Descriptive validation states, never converted into a workflow action.
ImageValidationState = Literal[
    "VALID",
    "LOW_QUALITY",
    "INVALID_OUTPUT",
    "UNSUPPORTED",
    "ERROR",
]

ImageErrorType = Literal[
    "INVALID_INPUT",
    "UNSUPPORTED_FORMAT",
    "DECODE_ERROR",
    "TRANSFORMATION_ERROR",
    "WRITE_ERROR",
    "IO_ERROR",
    "INTERNAL_ERROR",
]

# Kind of artifact a ref points at, so a caller never has to guess from the file name.
ImageArtifactKind = Literal["normalized", "ocr_ready", "vlm_ready", "region"]


@dataclass(frozen=True)
class ImageOptions:
    """Requested transformations and variants.

    OCR and VLM do not share an optimal image: OCR may want grayscale, deskew and
    binarization while a VLM must keep colour and layout. The two flags are therefore
    independent and neither implies the other.

    Attributes:
        normalize: Produce the general normalized representation.
        prepare_for_ocr: Produce the OCR-optimized variant.
        prepare_for_vlm: Produce the VLM-optimized variant.
        correct_orientation: Correct the detected orientation.
        deskew: Correct the detected skew angle.
    """

    normalize: bool
    prepare_for_ocr: bool
    prepare_for_vlm: bool
    correct_orientation: bool
    deskew: bool


@dataclass(frozen=True)
class ImageContext:
    """Correlation metadata for tracing. Never workflow state.

    Attributes:
        document_id: Identity of the document this request belongs to.
        page_number: Logical page the image belongs to, 1-based.
        workflow_run_id: Identity of the run that issued the request.
    """

    document_id: str
    page_number: int
    workflow_run_id: str


@dataclass(frozen=True)
class ImageRequest:
    """Input contract of the image processor.

    Attributes:
        image_path: Source image. Treated as immutable: never overwritten.
        output_dir: Root of the ``image/`` artifact namespace.
        options: Requested transformations and variants.
        context: Correlation metadata.
    """

    image_path: Path
    output_dir: Path
    options: ImageOptions
    context: ImageContext


@dataclass(frozen=True)
class ImageSourceRef:
    """Reference to the original input image.

    Attributes:
        path: Where the source image is.
        width: Width in pixels, or ``None`` when the engine never decoded the file.
            ``None`` means "not measured": a failed decode has no geometry, and zero
            would read as a measured answer.
        height: Height in pixels, or ``None`` for the same reason as ``width``.
        format: Image format as reported by the engine, or from the file itself when the
            decode never happened.
        size: Size in bytes, or ``None`` when the file could not be read at all.
    """

    path: Path
    width: int | None
    height: int | None
    format: str
    size: int | None


@dataclass(frozen=True)
class ArtifactRef:
    """Reference to one image file this processor published.

    Attributes:
        path: Where the artifact is.
        kind: Which representation it holds.
        width: Width in pixels.
        height: Height in pixels.
        format: Image format.
        size: Size in bytes.
    """

    path: Path
    kind: ImageArtifactKind
    width: int
    height: int
    format: str
    size: int


@dataclass(frozen=True)
class ImageVariants:
    """Optional purpose-specific variants. ``None`` means "not requested".

    Attributes:
        ocr_ready: The OCR-optimized variant, or ``None``.
        vlm_ready: The VLM-optimized variant, or ``None``.
    """

    ocr_ready: ArtifactRef | None
    vlm_ready: ArtifactRef | None


@dataclass(frozen=True)
class ImageDimensions:
    """Pixel dimensions of an image.

    Attributes:
        width: Width in pixels.
        height: Height in pixels.
    """

    width: int
    height: int


@dataclass(frozen=True)
class ImageQualityMetrics:
    """Measured quality scores. Measurements, not judgements.

    Attributes:
        blur: Blur score.
        sharpness: Sharpness score.
        contrast: Contrast score.
        brightness: Brightness score.
        noise: Noise score.
    """

    blur: float
    sharpness: float
    contrast: float
    brightness: float
    noise: float


@dataclass(frozen=True)
class TextRegion:
    """One region where text was detected.

    Attributes:
        region_id: Deterministic identifier within the image.
        bbox: Bounding box of the region.
        text_coverage: Fraction of the region covered by text.
    """

    region_id: str
    bbox: tuple[float, float, float, float]
    text_coverage: float


@dataclass(frozen=True)
class ImageError:
    """A typed failure, returned inside the result rather than thrown.

    Attributes:
        type: Failure classification.
        message: Human-readable description.
        recoverable: Whether the run can continue without this artifact.
        metadata: Additional diagnostic context.
    """

    type: ImageErrorType
    message: str
    recoverable: bool
    metadata: dict[str, Any]


@dataclass(frozen=True)
class ImageMetrics:
    """Technical metrics of one image, measured without mutating it.

    Attributes:
        dimensions: Pixel dimensions.
        resolution: Resolution in DPI when the format carries it, else ``None``.
        format: Image format.
        size: Size in bytes.
        quality: Quality scores.
        orientation: Detected orientation in degrees, or ``None`` when not detected.
        skew: Detected skew angle in degrees, or ``None`` when not detected.
        text_regions: Regions where text was detected.
        text_coverage: Fraction of the image covered by text.
    """

    dimensions: ImageDimensions
    resolution: int | None
    format: str
    size: int
    quality: ImageQualityMetrics
    orientation: int | None
    skew: float | None
    text_regions: list[TextRegion]
    text_coverage: float


@dataclass(frozen=True)
class ImageValidation:
    """Structural validation of the result.

    Attributes:
        status: Validation state.
        errors: Failures found while validating.
        missing_artifacts: Artifacts the validation expected and did not find.
    """

    status: ImageValidationState
    errors: list[ImageError]
    missing_artifacts: list[Path]


@dataclass(frozen=True)
class ImageMetadata:
    """Provenance of the processing.

    Attributes:
        processor: Processor name.
        processor_version: Processor version.
        engine: Named engine, recorded explicitly.
        engine_version: Engine version as the engine reports it, or ``None`` when no
            engine call was reached — a failed input is reported before the version is
            read, and a placeholder version would claim a provenance nobody observed.
        libraries: Versions of the libraries actually used.
        options: The options that were requested.
        input_metrics: Metrics of the source image, or ``None`` when nothing was measured.
        output_metrics: Metrics of the normalized image, or ``None`` when nothing was
            produced.
        timing: Wall-clock durations by stage.
        context: Correlation metadata echoed from the request.
    """

    processor: str
    processor_version: str
    engine: str
    engine_version: str | None
    libraries: dict[str, str]
    options: ImageOptions
    input_metrics: ImageMetrics | None
    output_metrics: ImageMetrics | None
    timing: dict[str, float]
    context: ImageContext


@dataclass
class ImageResult:
    """Output contract of the image processor, one per image.

    Attributes:
        source: Reference to the original input.
        normalized: The general normalized representation, or ``None`` when not
            requested.
        variants: Purpose-specific variants.
        metrics: Metrics of the source image, or ``None`` when nothing was measured.
        classification: Descriptive classification, or ``None`` when nothing was
            classified. Never a routing decision.
        transformations: Every transformation actually applied, in order.
        validation: Structural validation of the result.
        artifacts: Every file this processor published.
        metadata: Provenance of the processing.
        status: Outcome of the run.
        error: The typed failure when ``status`` is ``failed``.
    """

    source: ImageSourceRef
    normalized: ArtifactRef | None
    variants: ImageVariants
    metrics: ImageMetrics | None
    classification: ImageClassification | None
    transformations: list[str]
    validation: ImageValidation
    artifacts: list[ArtifactRef]
    metadata: ImageMetadata
    status: ImageStatus
    error: ImageError | None
