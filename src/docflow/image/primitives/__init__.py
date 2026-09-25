# pylint: disable=too-many-lines
# Reason: the engine calls stay in one module on purpose. The frozen patch path is
# ``docflow.image.primitives.cv2`` and the convention check reads this module statically, so a
# call moved into a sibling would escape both — a double could drift from a seam nobody reads.
"""Low-level image primitives — the only place that knows OpenCV.

Every engine symbol of the image processor lives in this module: decoding, encoding, the
colour conversions, the enhancements, the quality readings, the geometry and the text-region
detection are reached from here and from nowhere else. The engine is resolved **at call
time** and named explicitly — there is no fallback, no probing for an installed library and
no silent Pillow substitution — so ``import docflow.image.primitives`` succeeds with OpenCV
absent and an absent library surfaces as a typed ``IO_ERROR`` from the call instead of an
import error. Pillow is the documented *alternative* implementation of this module, not a
quiet second path through it.

OpenCV is a Python library, not a CLI, so its contract shapes this module differently from
the PDF seam. Two of its habits drive the design:

* **it fails silently.** ``cv2.imread`` returns ``None`` for an undecodable file and
  ``cv2.imwrite`` returns ``False`` for a write it could not perform; neither raises. Both are
  checked here and turned into a typed ``DECODE_ERROR`` / ``WRITE_ERROR``, because treating
  ``None`` as an empty image is exactly the silent stand-in this project forbids;
* **it raises ``cv2.error``** for a bad dtype, kernel or depth, which is the one signal that
  carries a message. :func:`_apply` maps it to ``TRANSFORMATION_ERROR``, so no engine
  exception crosses the processor's contract.

Engine signal → failure kind (the mapping this module is the only owner of):

============================= ======================================================
Engine signal                 ``ImageErrorType``
============================= ======================================================
``imread`` returns ``None``   ``DECODE_ERROR`` (never an empty image)
``imwrite`` returns ``False`` ``WRITE_ERROR``
missing or empty file         ``INVALID_INPUT`` (decided by ``validate_image_input``)
unsupported extension         ``UNSUPPORTED_FORMAT`` (decided before the call)
library absent                ``IO_ERROR``, not recoverable
``cv2.error``                 ``TRANSFORMATION_ERROR``
anything else                 ``INTERNAL_ERROR``
============================= ======================================================

Two rules hold for everything here: the input image is never written to — no primitive takes
the source path as a destination — and nothing is published except through the atomic writer,
which the engine's own ``imwrite`` never bypasses.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal, TypeVar

from docflow.image.contracts import (
    ArtifactRef,
    ImageArtifactKind,
    ImageDimensions,
    ImageMetrics,
    ImageOptions,
    ImageQualityMetrics,
    TextRegion,
)
from docflow.image.primitives.composition import (
    BRIGHTNESS_MAX,
    BRIGHTNESS_MIN,
    BRIGHTNESS_TARGET,
    CONTRAST_CLIP_LIMIT,
    CONTRAST_MIN,
    CONTRAST_TILE_GRID_SIZE,
    DENOISE_SEARCH_WINDOW,
    DENOISE_STRENGTH,
    DENOISE_TEMPLATE_WINDOW,
    DESKEW_BORDER_VALUE,
    DESKEW_MIN_ANGLE,
    INK_MAX_VALUE,
    INK_THRESHOLD,
    MIN_REGION_AREA,
    NOISE_MAX,
    NOISE_MEDIAN_KERNEL,
    OCR_BINARIZE_BLOCK_SIZE,
    OCR_BINARIZE_C,
    SHARPEN_AMOUNT,
    SHARPEN_KERNEL,
    SHARPEN_SIGMA,
    TEXT_REGION_KERNEL,
    VLM_MAX_DIMENSION,
    ImageFileFacts,
    build_text_regions,
    calculate_text_coverage,
    classify_image,
)
from docflow.image.primitives.errors import ImagePrimitiveError, typed_failure
from docflow.image.primitives.publication import publish_artifact, publish_json
from docflow.image.primitives.validation import (
    validate_image_input,
    validate_image_result,
)

#: Name recorded as ``engine`` in every artifact's metadata.
ENGINE_NAME: Final[str] = "opencv"

#: The import name of the engine, resolved at call time and never at import time.
ENGINE_MODULE: Final[str] = "cv2"

#: Channel layouts a caller may ask :func:`convert_image_format` for.
ChannelLayout = Literal["GRAY", "BGR"]

#: The resolution a decoded array cannot tell us. OpenCV decodes pixels and reports no
#: density, so the field stays ``None``. It is named because ``None`` here is a statement
#: about the engine, not a placeholder for a number nobody took.
RESOLUTION_NOT_REPORTED: Final[None] = None

#: The seam the tests patch: the engine namespace, or ``None`` until it is resolved at call
#: time. The name is the engine's own, because ``README.md`` §9.7 and the subplan's double
#: table fix the injection point as ``docflow.image.primitives.cv2``.
cv2: Any = None  # pylint: disable=invalid-name  # reason: the frozen patch target's name

T = TypeVar("T")


@dataclass(frozen=True)
class PreparedImage:
    """What one preparation pipeline produced.

    Attributes:
        artifact: The published file.
        transformations: The transformations the pipeline applied, in order.
        metrics: The measurements of the produced image. Measuring what was published is how
            a variant's own readings reach ``metadata.json``; it is one extra pass over the
            representation, not a second execution of the pipeline.
    """

    artifact: ArtifactRef
    transformations: list[str]
    metrics: ImageMetrics


__all__ = [
    "BRIGHTNESS_MAX",
    "BRIGHTNESS_MIN",
    "BRIGHTNESS_TARGET",
    "CONTRAST_MIN",
    "ENGINE_MODULE",
    "ENGINE_NAME",
    "NOISE_MAX",
    "RESOLUTION_NOT_REPORTED",
    "VLM_MAX_DIMENSION",
    "ChannelLayout",
    "ImageFileFacts",
    "ImagePrimitiveError",
    "PreparedImage",
    "analyze_image",
    "binarize_image",
    "calculate_blur_score",
    "calculate_brightness_score",
    "calculate_contrast_score",
    "calculate_noise_score",
    "calculate_sharpness_score",
    "calculate_text_coverage",
    "classify_image",
    "compress_image",
    "convert_image_format",
    "convert_to_grayscale",
    "denoise_image",
    "deskew_image",
    "detect_orientation",
    "detect_skew_angle",
    "detect_text_regions",
    "get_image_channels",
    "get_image_dimensions",
    "get_image_metadata",
    "image_engine_version",
    "load_image",
    "normalize_brightness",
    "normalize_contrast",
    "normalize_image",
    "prepare_image_for_ocr",
    "prepare_image_for_vlm",
    "prepare_normalized_image",
    "publish_artifact",
    "publish_json",
    "resize_image",
    "rotate_image",
    "save_image",
    "sharpen_image",
    "typed_failure",
    "validate_image_input",
    "validate_image_result",
]


def _engine() -> Any:
    """Return the image engine, imported at call time and never at import time.

    Importing this package has to succeed with OpenCV absent, so the library is resolved
    here rather than by a module-level ``import``. The module attribute :data:`cv2` is the
    seam the tests patch: a double installed there is returned instead of the library, so no
    test imports OpenCV.

    Returns:
        The engine namespace.

    Raises:
        ImagePrimitiveError: With ``IO_ERROR`` when the library is not installed. An absent
            engine is reported, never replaced by a fallback: the Pillow alternative is a
            documented swap of this module, not a silent substitution.
    """
    if cv2 is not None:
        return cv2
    try:
        return importlib.import_module(ENGINE_MODULE)
    except ImportError as exc:
        raise typed_failure(
            "IO_ERROR",
            f"the {ENGINE_NAME} library is not available",
            recoverable=False,
            metadata={"module": ENGINE_MODULE},
        ) from exc


def _apply(operation: Callable[[Any], T], description: str) -> T:
    """Run one engine operation, mapping the engine's own exception to a typed failure.

    Args:
        operation: Callable taking the engine namespace and returning the engine's own
            value, untranslated.
        description: What the operation was doing, for the failure record.

    Returns:
        Whatever the operation returned.

    Raises:
        ImagePrimitiveError: With ``TRANSFORMATION_ERROR`` when the engine raises — a bad
            depth, a kernel the engine refuses, a function this build lacks.
    """
    engine = _engine()
    try:
        return operation(engine)
    except engine.error as exc:
        raise typed_failure(
            "TRANSFORMATION_ERROR",
            f"the engine could not {description}",
            metadata={"engine_error": str(exc)},
        ) from exc


def image_engine_version() -> str:
    """Return the engine version, as the engine itself reports it.

    Returns:
        The version token the library exposes, e.g. ``"5.0.0"``.

    Raises:
        ImagePrimitiveError: With ``IO_ERROR`` when the library is absent. The version is
            recorded in every artifact, so an unreadable one is reported rather than
            guessed.
    """
    engine = _engine()
    return str(engine.__version__)


# --- Load and store ----------------------------------------------------------------


def get_image_dimensions(pixels: Any) -> tuple[int, int]:
    """Return the width and height of a decoded image, in pixels.

    ``shape`` is ``(height, width)`` for a single-channel image and ``(height, width,
    channels)`` otherwise — the engine's convention, spelled out here because this is the one
    place it is translated.

    Args:
        pixels: The decoded image.

    Returns:
        ``(width, height)``.
    """
    shape = pixels.shape
    return int(shape[1]), int(shape[0])


def get_image_channels(pixels: Any) -> int:
    """Return the channel count of a decoded image.

    Args:
        pixels: The decoded image.

    Returns:
        The number of channels: 1 for a single-channel image, otherwise ``shape[2]``.
    """
    shape = pixels.shape
    return 1 if len(shape) < 3 else int(shape[2])


def get_image_metadata(image_path: Path, pixels: Any) -> ImageFileFacts:
    """Collect what the file and the decoded array report about one image.

    Args:
        image_path: The source file, read for its size only.
        pixels: The decoded image.

    Returns:
        The file's facts. ``resolution`` is :data:`RESOLUTION_NOT_REPORTED` because the
        engine's decode does not report a density; it is ``None`` rather than a default DPI.
        TODO: [MVP] read the container's own density (the PNG ``pHYs`` chunk, the JPEG EXIF
        tag) when a downstream decision needs it.
    """
    width, height = get_image_dimensions(pixels)
    return ImageFileFacts(
        path=image_path,
        format=image_path.suffix.lstrip(".").lower(),
        size=image_path.stat().st_size,
        width=width,
        height=height,
        channels=get_image_channels(pixels),
        resolution=RESOLUTION_NOT_REPORTED,
    )


def load_image(image_path: Path, *, grayscale: bool = False) -> Any:
    """Decode an image from disk.

    Args:
        image_path: The file to decode. It is only ever read.
        grayscale: Decode to a single channel instead of the engine's three-channel default.

    Returns:
        The engine's decoded array.

    Raises:
        ImagePrimitiveError: With ``DECODE_ERROR`` when the engine returns no image — which
            is how it reports an undecodable file, without raising. The empty answer is
            refused rather than passed on as an image.
    """
    engine = _engine()
    mode = engine.IMREAD_GRAYSCALE if grayscale else engine.IMREAD_COLOR
    pixels = engine.imread(str(image_path), mode)
    if pixels is None:
        raise typed_failure(
            "DECODE_ERROR",
            f"the engine could not decode {image_path}",
            recoverable=False,
            metadata={"image_path": str(image_path), "grayscale": grayscale},
        )
    return pixels


def _write_image(pixels: Any, destination: Path, parameters: list[int]) -> Path:
    """Encode decoded pixels at ``destination``, atomically.

    Args:
        pixels: The image to encode.
        destination: Final artifact path.
        parameters: The engine's own encoder parameters; empty means the encoder's default
            for the format the destination's suffix names.

    Returns:
        ``destination``, once it is complete and non-empty.

    Raises:
        ImagePrimitiveError: With ``WRITE_ERROR`` when the engine reports that it could not
            encode or store the image — the boolean it returns instead of raising.
    """

    def write(temporary: Path) -> None:
        """Encode the pixels at the temporary path the publication hands us."""
        engine = _engine()
        if not engine.imwrite(str(temporary), pixels, parameters):
            raise typed_failure(
                "WRITE_ERROR",
                f"the engine could not encode {destination}",
                metadata={"destination": str(destination)},
            )

    return publish_artifact(destination, write)


def save_image(pixels: Any, destination: Path) -> Path:
    """Publish decoded pixels at ``destination``, atomically.

    Args:
        pixels: The image to publish.
        destination: Final artifact path; its suffix decides the container.

    Returns:
        ``destination``, once it is complete.
    """
    return _write_image(pixels, destination, [])


def compress_image(pixels: Any, destination: Path, *, quality: int) -> Path:
    """Publish decoded pixels as a lossy JPEG at the requested quality.

    # TODO: [MVP] no Phase 1 caller: both variants are lossless PNG, so nothing on the happy
    # path asks for a quality factor. The primitive exists because the plan fixes it, and it
    # is the same writer with one engine parameter.

    Args:
        pixels: The image to publish.
        destination: Final artifact path; a ``.jpg`` or ``.jpeg`` suffix is expected.
        quality: The encoder's quality factor, 0-100, named by the caller rather than taken
            from the engine's default.

    Returns:
        ``destination``, once it is complete.
    """
    engine = _engine()
    return _write_image(pixels, destination, [engine.IMWRITE_JPEG_QUALITY, quality])


# --- Convert -----------------------------------------------------------------------


def convert_image_format(pixels: Any, target: ChannelLayout) -> Any:
    """Return ``pixels`` in the requested channel layout.

    The layout is what changes here; the *file* container is decided by the destination's
    suffix at publication, so this primitive never renames an artifact.

    Args:
        pixels: The decoded image.
        target: ``"GRAY"`` for a single channel, ``"BGR"`` for three.

    Returns:
        The converted image, or ``pixels`` itself when it is already in the requested
        layout — no conversion happened, and saying so is the truthful answer.
    """
    channels = get_image_channels(pixels)
    if target == "GRAY":
        if channels == 1:
            return pixels
        return _apply(
            lambda cv2: cv2.cvtColor(pixels, cv2.COLOR_BGR2GRAY),
            "convert the image to grayscale",
        )
    if channels == 1:
        return _apply(
            lambda cv2: cv2.cvtColor(pixels, cv2.COLOR_GRAY2BGR),
            "convert the image to three channels",
        )
    if channels == 4:
        return _apply(
            lambda cv2: cv2.cvtColor(pixels, cv2.COLOR_BGRA2BGR),
            "drop the alpha channel",
        )
    return pixels


def convert_to_grayscale(pixels: Any) -> Any:
    """Return ``pixels`` as a single-channel image.

    Args:
        pixels: The decoded image.

    Returns:
        The single-channel image; the OCR preparation's first step.
    """
    return convert_image_format(pixels, "GRAY")


def resize_image(pixels: Any, width: int, height: int) -> Any:
    """Return ``pixels`` resampled to ``width`` x ``height``.

    Args:
        pixels: The decoded image.
        width: Target width in pixels, strictly positive.
        height: Target height in pixels, strictly positive.

    Returns:
        The resampled image.

    Raises:
        ImagePrimitiveError: With ``INVALID_INPUT`` when a target dimension is not positive:
            a zero-sized target is a caller error, not a request the engine should be asked
            to guess about.
    """
    if width <= 0 or height <= 0:
        raise typed_failure(
            "INVALID_INPUT",
            f"a resize target of {width}x{height} is not a size",
            recoverable=False,
            metadata={"width": width, "height": height},
        )
    return _apply(
        lambda cv2: cv2.resize(pixels, (width, height), interpolation=cv2.INTER_AREA),
        f"resize the image to {width}x{height}",
    )


# --- Enhance -----------------------------------------------------------------------


def normalize_contrast(gray: Any) -> Any:
    """Return a single-channel image with its local contrast equalized.

    Args:
        gray: The single-channel image. CLAHE is a single-channel operator; the caller
            converts a colour image first.

    Returns:
        The contrast-normalized image.
    """
    engine = _engine()
    equalizer = engine.createCLAHE(
        clipLimit=CONTRAST_CLIP_LIMIT, tileGridSize=CONTRAST_TILE_GRID_SIZE
    )
    return _apply(
        lambda _: equalizer.apply(gray), "equalize the image's local contrast"
    )


def normalize_brightness(pixels: Any, delta: float) -> Any:
    """Return ``pixels`` shifted in brightness by ``delta`` grey levels.

    Args:
        pixels: The decoded image.
        delta: The shift, positive to brighten. The caller computes it from a measurement.

    Returns:
        The shifted image, saturated to the 8-bit range.
    """
    return _apply(
        lambda cv2: cv2.convertScaleAbs(pixels, alpha=1.0, beta=delta),
        f"shift the brightness by {delta}",
    )


def denoise_image(gray: Any) -> Any:
    """Return a single-channel image with the non-local-means denoiser applied.

    Args:
        gray: The single-channel image. This is the expensive operator, which is why it is
            applied only when the noise reading justifies it.

    Returns:
        The denoised image.
    """
    return _apply(
        lambda cv2: cv2.fastNlMeansDenoising(
            gray,
            h=DENOISE_STRENGTH,
            templateWindowSize=DENOISE_TEMPLATE_WINDOW,
            searchWindowSize=DENOISE_SEARCH_WINDOW,
        ),
        "denoise the image",
    )


def sharpen_image(pixels: Any) -> Any:
    """Return ``pixels`` sharpened with an unsharp mask.

    # TODO: [MVP] no Phase 1 caller: ``ImageOptions`` carries no sharpening flag, so nothing on
    # the happy path may ask for it — a transformation is applied only when an option and a
    # measurement justify it. The primitive exists because the plan fixes it.

    Args:
        pixels: The decoded image.

    Returns:
        The sharpened image.
    """
    blurred = _apply(
        lambda cv2: cv2.GaussianBlur(
            pixels, (SHARPEN_KERNEL, SHARPEN_KERNEL), SHARPEN_SIGMA
        ),
        "blur the image for sharpening",
    )
    return _apply(
        lambda cv2: cv2.addWeighted(
            pixels, 1.0 + SHARPEN_AMOUNT, blurred, -SHARPEN_AMOUNT, 0.0
        ),
        "sharpen the image",
    )


def binarize_image(gray: Any) -> Any:
    """Return a single-channel image thresholded into ink and background.

    The threshold is adaptive and its block size and constant are ours, named in
    :mod:`docflow.image.primitives.composition`: a threshold the engine computes (Otsu) is a
    number nobody recorded, and this project does not accept an unrecorded decision.

    Args:
        gray: The single-channel image.

    Returns:
        The binary image: 0 for ink, 255 for background.
    """
    return _apply(
        lambda cv2: cv2.adaptiveThreshold(
            gray,
            INK_MAX_VALUE,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            OCR_BINARIZE_BLOCK_SIZE,
            OCR_BINARIZE_C,
        ),
        "binarize the image",
    )


# --- Quality readings --------------------------------------------------------------


def calculate_blur_score(gray: Any) -> float:
    """Return the variance of the Laplacian — the standard blur reading.

    Args:
        gray: The single-channel image.

    Returns:
        The variance, in the engine's own units. It **falls** as the image blurs, which is
        how the quality rule in ``composition`` reads it.
    """
    return _apply(
        lambda cv2: float(cv2.Laplacian(gray, cv2.CV_64F).var()),
        "measure the image's blur",
    )


def calculate_sharpness_score(gray: Any) -> float:
    """Return the mean gradient magnitude — a Tenengrad-style sharpness reading.

    Args:
        gray: The single-channel image.

    Returns:
        The mean of the horizontal and vertical gradient magnitudes, in the engine's units.
    """
    horizontal = _apply(
        lambda cv2: cv2.Sobel(gray, cv2.CV_64F, 1, 0), "measure the horizontal gradient"
    )
    vertical = _apply(
        lambda cv2: cv2.Sobel(gray, cv2.CV_64F, 0, 1), "measure the vertical gradient"
    )
    combined = _apply(
        lambda cv2: cv2.addWeighted(abs(horizontal), 1.0, abs(vertical), 1.0, 0.0),
        "combine the gradients",
    )
    return float(combined.mean())


def calculate_contrast_score(gray: Any) -> float:
    """Return the standard deviation of the grey levels.

    Args:
        gray: The single-channel image. A colour image would give the deviation over all
            channels, so the caller measures the grey one.

    Returns:
        The standard deviation, in grey levels.
    """
    return float(gray.std())


def calculate_brightness_score(gray: Any) -> float:
    """Return the mean grey level.

    Args:
        gray: The single-channel image.

    Returns:
        The mean, in grey levels.
    """
    return float(gray.mean())


def calculate_noise_score(gray: Any) -> float:
    """Return the mean deviation from the local median — the standard noise reading.

    Args:
        gray: The single-channel image.

    Returns:
        The mean absolute difference between the image and its median-filtered copy, in grey
        levels. ``absdiff`` is used rather than subtraction because unsigned pixels saturate
        at zero, which would hide half of the deviation.
    """
    smoothed = _apply(
        lambda cv2: cv2.medianBlur(gray, NOISE_MEDIAN_KERNEL),
        "measure the image's local median",
    )
    deviation = _apply(
        lambda cv2: cv2.absdiff(gray, smoothed),
        "measure the deviation from the local median",
    )
    return float(deviation.mean())


# --- Orientation and geometry ------------------------------------------------------


def _ink_mask(gray: Any) -> Any:
    """Return a binary mask of the dark, ink-bearing pixels.

    Args:
        gray: The single-channel image.

    Returns:
        The mask: 255 where a pixel is ink, 0 elsewhere. The threshold is ours and named
        rather than left to an engine default.
    """
    return _apply(
        lambda cv2: cv2.threshold(
            gray, INK_THRESHOLD, INK_MAX_VALUE, cv2.THRESH_BINARY_INV
        )[1],
        "separate the ink from the background",
    )


def detect_orientation(gray: Any, width: int, height: int) -> int | None:
    """Return the rotation the measured ink implies **relative to the page frame**, in degrees.

    This is a decision of ours, not a reading: the engine reports geometry, not uprightness.
    Content that fills a page shares the page's own aspect; content that was scanned sideways
    contradicts it — its box is wide on a tall page, or tall on a wide one. That contradiction
    is the one rotation signal the pixels carry, and it is what this returns.

    # TODO: [MVP] a decoded array carries no rotation metadata. The authoritative source is
    # the container's own tag (a JPEG's EXIF orientation, a PDF page's ``/Rotate``), which the
    # PDF processor or a container reader has to supply; a content-shape heuristic cannot tell
    # a rotated page from a short one.

    Args:
        gray: The single-channel image.
        width: Page width in pixels, as decoded.
        height: Page height in pixels, as decoded.

    Returns:
        ``0`` or ``90``, or ``None`` when no ink was found: an image with nothing in it has no
        orientation to report, and ``0`` would read as a measurement.
    """
    points = _apply(
        lambda cv2: cv2.findNonZero(_ink_mask(gray)), "locate the image's ink"
    )
    if points is None or len(points) == 0:
        return None
    _, _, ink_width, ink_height = _apply(
        lambda cv2: cv2.boundingRect(points), "measure the inked area"
    )
    page_is_wide = width >= height
    ink_is_wide = ink_width >= ink_height
    return 0 if page_is_wide == ink_is_wide else 90


def detect_skew_angle(gray: Any) -> float | None:
    """Return the skew of the measured ink, in degrees.

    The engine reports a box angle in ``0..90``; the sign convention here is ours: an angle
    past 45 degrees is the same skew seen from the other side, so it is folded into
    ``-45..45`` where a negative value means the content leans the other way.

    Args:
        gray: The single-channel image.

    Returns:
        The skew in degrees, or ``None`` when no ink was found.
    """
    points = _apply(
        lambda cv2: cv2.findNonZero(_ink_mask(gray)), "locate the image's ink"
    )
    if points is None or len(points) == 0:
        return None
    angle = float(
        _apply(lambda cv2: cv2.minAreaRect(points)[2], "measure the ink's angle")
    )
    return angle if angle <= 45.0 else angle - 90.0


def rotate_image(pixels: Any, angle: float) -> Any:
    """Return ``pixels`` rotated by ``angle`` degrees about its centre.

    The frame keeps the source's size and the wedges the rotation leaves are filled with
    :data:`~docflow.image.primitives.composition.DESKEW_BORDER_VALUE` (white, like a page),
    rather than the engine's black default.

    Args:
        pixels: The decoded image.
        angle: The rotation, in degrees, counter-clockwise.

    Returns:
        The rotated image, the same size as the source.
    """
    width, height = get_image_dimensions(pixels)
    center = (width / 2.0, height / 2.0)
    return _apply(
        lambda cv2: cv2.warpAffine(
            pixels,
            cv2.getRotationMatrix2D(center, angle, 1.0),
            (width, height),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=DESKEW_BORDER_VALUE,
        ),
        f"rotate the image by {angle} degrees",
    )


def deskew_image(pixels: Any, skew: float) -> Any:
    """Return ``pixels`` with ``skew`` removed.

    Args:
        pixels: The decoded image.
        skew: The measured skew, as :func:`detect_skew_angle` reports it.

    Returns:
        The deskewed image.
    """
    return rotate_image(pixels, -skew)


# --- Visual analysis ---------------------------------------------------------------


def detect_text_regions(pixels: Any) -> list[TextRegion]:
    """Detect the regions of ``pixels`` that carry text, in reading order.

    The pipeline is ours: ink is separated from the background, a closing joins a word's
    glyphs into one blob, the blobs are traced as contours, and each is measured for the share
    of its own box that is actually ink. Regions too small to be text are dropped as speckle.

    The share is measured on the **raw** ink mask, not on the closed one: the closing exists to
    join glyphs, so it fills the gaps between them, and a reading taken from it would report a
    filled box for every region and carry no information.

    Args:
        pixels: The decoded image.

    Returns:
        The regions, ordered top to bottom and named deterministically. Every ``bbox`` is
        ``(left, top, right, bottom)`` in pixels.
    """
    ink = _ink_mask(convert_to_grayscale(pixels))
    closed = _apply(
        lambda cv2: cv2.morphologyEx(
            ink,
            cv2.MORPH_CLOSE,
            cv2.getStructuringElement(
                cv2.MORPH_RECT, (TEXT_REGION_KERNEL, TEXT_REGION_KERNEL)
            ),
        ),
        "join the glyphs into text regions",
    )
    contours = _apply(
        lambda cv2: cv2.findContours(
            closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )[0],
        "trace the text regions",
    )

    measured: list[tuple[tuple[float, float, float, float], float]] = []
    for contour in contours:
        # The loop's values are bound as defaults rather than closed over: the callable is run
        # immediately, but a closure over a loop variable reads as the classic late-binding bug.
        left, top, width, height = _apply(
            lambda cv2, region=contour: cv2.boundingRect(region),
            "measure a text region",
        )
        area = int(width) * int(height)
        if area < MIN_REGION_AREA:
            continue
        inside = ink[top : top + height, left : left + width]
        inked = _apply(
            lambda cv2, crop=inside: cv2.countNonZero(crop),
            "measure the ink inside a text region",
        )
        box = (float(left), float(top), float(left + width), float(top + height))
        measured.append((box, inked / float(area)))
    return build_text_regions(measured)


# --- Measurement and the two preparation pipelines ---------------------------------


def analyze_image(pixels: Any, facts: ImageFileFacts) -> ImageMetrics:
    """Measure one decoded image without writing anything.

    Args:
        pixels: The decoded image.
        facts: The file and array facts collected at load time.

    Returns:
        The measurements: dimensions and container facts, the five quality readings, the
        detected orientation and skew, and the text regions with the share of the image they
        occupy. Nothing is written and ``pixels`` is never mutated.
    """
    gray = convert_to_grayscale(pixels)
    regions = detect_text_regions(pixels)
    return ImageMetrics(
        dimensions=ImageDimensions(width=facts.width, height=facts.height),
        resolution=facts.resolution,
        format=facts.format,
        size=facts.size,
        quality=ImageQualityMetrics(
            blur=calculate_blur_score(gray),
            sharpness=calculate_sharpness_score(gray),
            contrast=calculate_contrast_score(gray),
            brightness=calculate_brightness_score(gray),
            noise=calculate_noise_score(gray),
        ),
        orientation=detect_orientation(gray, facts.width, facts.height),
        skew=detect_skew_angle(gray),
        text_regions=regions,
        text_coverage=calculate_text_coverage(regions, facts.width, facts.height),
    )


def _artifact_ref(path: Path, kind: ImageArtifactKind, pixels: Any) -> ArtifactRef:
    """Describe a published image artifact.

    Args:
        path: Where the artifact was published.
        kind: Which representation it holds.
        pixels: The image that was published, for its dimensions.

    Returns:
        The artifact reference, with the size read back from the file that was written.
    """
    width, height = get_image_dimensions(pixels)
    return ArtifactRef(
        path=path,
        kind=kind,
        width=width,
        height=height,
        format=path.suffix.lstrip(".").lower(),
        size=path.stat().st_size,
    )


def normalize_image(
    pixels: Any, metrics: ImageMetrics, options: ImageOptions
) -> tuple[Any, list[str]]:
    """Apply only the corrections the measurements and the options justify.

    Args:
        pixels: The decoded image.
        metrics: The image's measurements.
        options: The requested corrections. A correction whose option is off is not applied
            even when the measurement would justify it.

    Returns:
        The normalized image and the names of the transformations actually applied, in order.
        An empty list is a truthful answer: nothing needed correcting.
    """
    transformed = pixels
    applied: list[str] = []

    if options.correct_orientation and metrics.orientation:
        transformed = rotate_image(transformed, float(metrics.orientation))
        applied.append("correct_orientation")
    if (
        options.deskew
        and metrics.skew is not None
        and abs(metrics.skew) >= DESKEW_MIN_ANGLE
    ):
        transformed = deskew_image(transformed, metrics.skew)
        applied.append("deskew")
    if not BRIGHTNESS_MIN <= metrics.quality.brightness <= BRIGHTNESS_MAX:
        shifted = BRIGHTNESS_TARGET - metrics.quality.brightness
        transformed = normalize_brightness(transformed, shifted)
        applied.append("normalize_brightness")

    return transformed, applied


def _prepared(
    published: Path,
    kind: ImageArtifactKind,
    transformed: Any,
    applied: list[str],
) -> PreparedImage:
    """Describe one published representation, with its own measurements.

    Args:
        published: Where the representation was published.
        kind: Which representation it is.
        transformed: The image that was published.
        applied: The transformations that produced it, in order.

    Returns:
        The artifact, the transformations and the produced image's measurements.
    """
    return PreparedImage(
        artifact=_artifact_ref(published, kind, transformed),
        transformations=applied,
        metrics=analyze_image(transformed, get_image_metadata(published, transformed)),
    )


def prepare_normalized_image(
    pixels: Any, metrics: ImageMetrics, options: ImageOptions, destination: Path
) -> PreparedImage:
    """Produce the general normalized representation.

    Args:
        pixels: The decoded image.
        metrics: The image's measurements.
        options: The requested corrections.
        destination: Where ``normalized.png`` is published.

    Returns:
        What the pipeline produced. When nothing needed correcting the artifact is the
        canonical re-encoding of the decoded image, which is still a published
        representation and not a claim that a correction happened.
    """
    transformed, applied = normalize_image(pixels, metrics, options)
    published = save_image(transformed, destination)
    return _prepared(published, "normalized", transformed, applied)


def prepare_image_for_ocr(
    pixels: Any, metrics: ImageMetrics, options: ImageOptions, destination: Path
) -> PreparedImage:
    """Produce the OCR-optimized variant: single channel, high contrast, binarized.

    OCR benefits from a representation a VLM must not be given: greyscale destroys colour and
    binarization destroys everything but the ink. Every step but the last is applied only when
    the measurement justifies it; binarization is what this variant *is*.

    Args:
        pixels: The decoded image.
        metrics: The image's measurements.
        options: The requested corrections.
        destination: Where ``ocr_ready.png`` is published.

    Returns:
        What the pipeline produced, with the transformations applied in order.
    """
    transformed = pixels
    applied: list[str] = []

    if get_image_channels(transformed) != 1:
        transformed = convert_to_grayscale(transformed)
        applied.append("convert_to_grayscale")
    if metrics.quality.contrast < CONTRAST_MIN:
        transformed = normalize_contrast(transformed)
        applied.append("normalize_contrast")
    if metrics.quality.noise > NOISE_MAX:
        transformed = denoise_image(transformed)
        applied.append("denoise")
    if options.correct_orientation and metrics.orientation:
        transformed = rotate_image(transformed, float(metrics.orientation))
        applied.append("correct_orientation")
    if (
        options.deskew
        and metrics.skew is not None
        and abs(metrics.skew) >= DESKEW_MIN_ANGLE
    ):
        transformed = deskew_image(transformed, metrics.skew)
        applied.append("deskew")

    transformed = binarize_image(transformed)
    applied.append("binarize")

    published = save_image(transformed, destination)
    return _prepared(published, "ocr_ready", transformed, applied)


def prepare_image_for_vlm(
    pixels: Any, metrics: ImageMetrics, options: ImageOptions, destination: Path
) -> PreparedImage:
    """Produce the VLM-optimized variant: colour and layout preserved.

    A VLM needs what the OCR variant deliberately destroys, so this pipeline never converts to
    greyscale, never binarizes and never denoises: only the frame is corrected (turned upright,
    re-exposed) and a page too large for a bounded context is downscaled.

    Args:
        pixels: The decoded image.
        metrics: The image's measurements.
        options: The requested corrections.
        destination: Where ``vlm_ready.png`` is published.

    Returns:
        What the pipeline produced, with the transformations applied in order.
    """
    transformed = pixels
    applied: list[str] = []

    if options.correct_orientation and metrics.orientation:
        transformed = rotate_image(transformed, float(metrics.orientation))
        applied.append("correct_orientation")
    if not BRIGHTNESS_MIN <= metrics.quality.brightness <= BRIGHTNESS_MAX:
        shifted = BRIGHTNESS_TARGET - metrics.quality.brightness
        transformed = normalize_brightness(transformed, shifted)
        applied.append("normalize_brightness")

    width, height = get_image_dimensions(transformed)
    longest = max(width, height)
    if longest > VLM_MAX_DIMENSION:
        scale = VLM_MAX_DIMENSION / longest
        transformed = resize_image(
            transformed,
            max(1, round(width * scale)),
            max(1, round(height * scale)),
        )
        applied.append("resize")

    published = save_image(transformed, destination)
    return _prepared(published, "vlm_ready", transformed, applied)
