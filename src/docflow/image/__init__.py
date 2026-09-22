"""Image processor: ``ImageRequest → ImageResult``.

Analyses one image, measures its technical quality, normalizes it and prepares the
``ocr_ready`` / ``vlm_ready`` variants that later stages may request. The two variants
are independent: the processor never assumes the OCR-optimal image equals the VLM-optimal
image, and it never decides which one a later stage should use.

Engine: OpenCV, with Pillow as the documented drop-in alternative, reached only from
:mod:`docflow.image.primitives`. The processor imports no other processor.

Entry points: :func:`process_image` and :func:`process_image_from_page`. The latter is a
wrapper that builds an :class:`~docflow.image.contracts.ImageRequest` for an image a PDF
produced and delegates; it never opens or renders a PDF itself.

Symbols are re-exported here, but only :mod:`docflow.image.primitives` may import them.
"""

from __future__ import annotations

from docflow.image.contracts import (
    ArtifactRef,
    ImageArtifactKind,
    ImageClassification,
    ImageContext,
    ImageDimensions,
    ImageError,
    ImageErrorType,
    ImageMetadata,
    ImageMetrics,
    ImageOptions,
    ImageQualityMetrics,
    ImageRequest,
    ImageResult,
    ImageSourceRef,
    ImageStatus,
    ImageValidation,
    ImageValidationState,
    ImageVariants,
    TextRegion,
)
from docflow.image.entrypoints import process_image, process_image_from_page

__all__ = [
    "ArtifactRef",
    "ImageArtifactKind",
    "ImageClassification",
    "ImageContext",
    "ImageDimensions",
    "ImageError",
    "ImageErrorType",
    "ImageMetadata",
    "ImageMetrics",
    "ImageOptions",
    "ImageQualityMetrics",
    "ImageRequest",
    "ImageResult",
    "ImageSourceRef",
    "ImageStatus",
    "ImageValidation",
    "ImageValidationState",
    "ImageVariants",
    "TextRegion",
    "process_image",
    "process_image_from_page",
]
