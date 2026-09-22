"""Transformation primitives - the only module allowed to change pixels.

Every function returns a **new** array and leaves its input untouched. That is a contract rather
than a style choice: ``IMG-07`` records every transformation it applies, and a function that edited
its argument would make that record a description of a side effect instead of of a returned value.

Every function also does exactly what it was asked and nothing more. The plan's risk table names
"over-eager enhancement degrades information (e.g. binarization destroying colour)" and answers it
with "apply transformations only when justified by metrics + explicit options". Justification is not
this module's job - deciding *whether* to binarize belongs to ``IMG-07`` and ``IMG-08`` - so nothing
here inspects a metric, picks a threshold by policy, or chains two operations together. A caller can
ask for something destructive, and that is the caller's decision to make and record.

The engine is passed in rather than chosen here: the seam in
:mod:`docflow.image.primitives.engine` decides which library is loaded, and a primitive that picked
its own engine would be a second, quieter seam.
"""

from __future__ import annotations

import numpy as np

from docflow.image.primitives.engine import (
    CHANNEL_COUNT_RGB,
    EngineChoice,
    ImageArray,
    engine_operation,
)
from docflow.image.primitives.failures import (
    classify_transformation_failure,
)

INTERPOLATION_FOR_SHRINK = "INTER_AREA"
"""Resampling used when an image gets smaller.

Averaging over the source pixels is what keeps a downscale from aliasing; nearest-neighbour would
drop whole rows and columns and make a legibility measure meaningless.
"""

INTERPOLATION_FOR_GROWTH = "INTER_CUBIC"
"""Resampling used when an image gets larger.

Cubic rather than linear because a growing image has to invent detail, and the smoother
reconstruction is the better guess where the result will be measured for sharpness.
"""

BINARIZATION_THRESHOLD = 128
"""Luminance cut for a fixed-threshold binarization, on the 0-255 scale.

Lives here rather than in the analysis module because it is a parameter of a transformation, not a
measurement: nothing in :mod:`docflow.image.primitives.analysis` reads it, and a measurement module
that also published the value a destructive operation would use was inviting the two to be changed
together.

# TODO: [MVP] provisional - a fixed cut ignores uneven lighting, where an adaptive one would not.
"""

OTSU_THRESHOLD = -1
"""Sentinels for "let the engine choose the cut from the histogram".

Passed as the threshold argument alongside the Otsu flag, which is what the engine's API requires.
Negative because no real luminance threshold is, so a caller can never reach this branch by accident
with a value they meant as a cut.
"""

MIN_COMPRESSION_QUALITY = 1
MAX_COMPRESSION_QUALITY = 100
"""Bounds of the codec's quality scale. A value outside them is refused rather than clamped.

Clamping would silently substitute a quality the caller did not ask for, which is the "no silent
stand-in" rule applied to a knob.
"""

DEFAULT_DENOISE_STRENGTH = 7
"""Filter strength for the luminance component, on the engine's own scale.

# TODO: [MVP] provisional - a fixed strength assumes uniform sensor noise.
"""

COLOUR_DENOISE_STRENGTH = 10
"""Filter strength for the colour components.

The engine's own documentation recommends this value, and it is higher than the luminance strength
on purpose: colour noise is grainier and carries less signal, so it can be smoothed harder without
losing a stroke.
"""

TEMPLATE_WINDOW_SIZE = 7
SEARCH_WINDOW_SIZE = 21
"""Patch size and search radius for the non-local means denoiser, in pixels.

Both must be odd, and both take the engine's recommended values. The search window governs how far
a pixel may look for similar neighbourhoods, so it is the parameter that decides whether the filter
can find an unbroken stroke a few pixels away.
"""

SHARPEN_AMOUNT = 1.0
"""Weight of the high-pass term when sharpening; the identity term is fixed at ``1.0``.

Unsharp masking is ``image + amount * (image - blurred)``. An amount of ``1.0`` doubles the
high-pass contribution, which is the conventional starting point.
"""

SHARPEN_SIGMA = 1.0
"""Gaussian radius used to build the unsharp mask's low-pass reference."""

CLIP_LIMIT = 2.0
CLIP_TILE_GRID = (8, 8)
"""Contrast-limits and tile grid for :func:`normalize_contrast`.

The clip limit caps how much a flat region's contrast may be stretched, which is what stops an
image with a clean background being amplified into visible noise. A low limit is chosen deliberately
for that reason.

# TODO: [MVP] provisional - set from the fixtures, not from a labelled corpus.
"""

GRAYSCALE_RANK = 2
"""Shape rank of an image with no channel axis."""

QUARTER_TURNS_PER_TURN = 4
"""Quarter turns in a full rotation; the modulus :func:`turn_quarter` normalises against."""

ENCODABLE_FORMATS: frozenset[str] = frozenset(
    {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}
)
"""Containers the engine has an encoder for, by extension including the dot.

Needed as a named set because the engine's own answer for an unknown extension is a native
exception, not a value a caller can classify.
"""


def to_grayscale(image: ImageArray, engine: EngineChoice) -> ImageArray:
    """Reduce an image to a single luminance channel.

    Args:
        image: The decoded pixels, RGB or grayscale.
        engine: The engine to transform with.

    Returns:
        A single-channel array; an already-grayscale input is returned as it stands.

    Raises:
        ImageEngineCapabilityError: The engine provides no colour conversion.
    """
    if image.ndim == GRAYSCALE_RANK:
        return image
    convert = engine_operation(engine, "cvtColor")
    return convert(image, engine_operation(engine, "COLOR_RGB2GRAY"))


def _require_colour(image: ImageArray, operation: str) -> None:
    """Refuse an operation that needs three channels when the input has fewer.

    Args:
        image: The array to check.
        operation: Name of the operation, for the failure message.

    Raises:
        ImagePrimitiveError: The array is not a three-channel image.
    """
    if image.ndim != 3 or image.shape[2] != CHANNEL_COUNT_RGB:
        raise classify_transformation_failure(
            operation,
            f"expected a 3-channel RGB image, got shape {image.shape!r}",
        )


def _require_positive(width: int, height: int, operation: str) -> None:
    """Refuse a target size that cannot produce an image.

    Args:
        width: Requested width.
        height: Requested height.
        operation: Name of the operation, for the failure message.

    Raises:
        ImagePrimitiveError: A dimension is not positive.
    """
    if width <= 0 or height <= 0:
        raise classify_transformation_failure(
            operation, f"expected positive dimensions, got {width}x{height}"
        )


def turn_quarter(image: ImageArray, quarter_turns: int) -> ImageArray:
    """Turn an image by whole quarter turns counter-clockwise.

    Deliberately **not** parameterised by an engine, and the only primitive here that is not. A
    quarter turn is a permutation of the pixel grid, not a re-sampling: no interpolation is
    involved and no library is needed, so routing it through an engine would add a dependency to
    buy nothing. It is written with the array library the whole primitive layer already speaks.

    It exists because :func:`rotate_image` cannot do this job. That function keeps the input's
    dimensions, which is right for a small tilt but means a 90-degree turn **crops** the page to its
    original frame instead of reorienting it. A quarter turn has to exchange width and height, and
    this is the primitive that does.

    Args:
        image: The decoded pixels, RGB or grayscale. Not modified.
        quarter_turns: How many quarter turns to apply, counter-clockwise; taken modulo four, so
            ``-1`` and ``3`` are the same request.

    Returns:
        A new image, with width and height exchanged for an odd number of quarter turns.
    """
    return np.ascontiguousarray(np.rot90(image, quarter_turns % QUARTER_TURNS_PER_TURN))


def rotate_image(image: ImageArray, degrees: float, engine: EngineChoice) -> ImageArray:
    """Rotate an image about its centre by an arbitrary angle.

    The output keeps the input's dimensions, so the corners of the rotated content are cropped and
    the triangles left at the edges are filled by replicating the border rather than with a colour
    that would be mistaken for content.

    Args:
        image: The decoded pixels, RGB or grayscale. Not modified.
        degrees: Rotation in degrees, counter-clockwise positive.
        engine: The engine to transform with.

    Returns:
        A new rotated image, the same size as the input.

    Raises:
        ImagePrimitiveError: The rotation cannot be applied.
    """
    opencv = engine_operation(engine, "warpAffine")
    matrix = engine_operation(engine, "getRotationMatrix2D")
    height, width = image.shape[0], image.shape[1]
    transform = matrix((width / 2, height / 2), degrees, 1.0)
    return opencv(
        image,
        transform,
        (width, height),
        flags=engine_operation(engine, INTERPOLATION_FOR_GROWTH),
        borderMode=engine_operation(engine, "BORDER_REPLICATE"),
    )


def deskew_image(image: ImageArray, angle: float, engine: EngineChoice) -> ImageArray:
    """Straighten an image by the tilt :func:`detect_skew_angle` reported.

    A thin wrapper over :func:`rotate_image` rather than a second rotation implementation, so the
    detector and the corrector cannot drift apart. The angle is passed through **unchanged**: a
    reading of ``+4`` from the detector is corrected by rotating ``+4``, which was established by
    measuring the engine rather than by reasoning about the sign. Inverting it here would double the
    tilt instead of removing it.

    Args:
        image: The decoded pixels, RGB or grayscale. Not modified.
        angle: The tilt in degrees, as ``detect_skew_angle`` reports it.
        engine: The engine to transform with.

    Returns:
        A new, straightened image.

    Raises:
        ImagePrimitiveError: The correction cannot be applied.
    """
    return rotate_image(image, angle, engine)


def resize_image(
    image: ImageArray, width: int, height: int, engine: EngineChoice
) -> ImageArray:
    """Scale an image to exact pixel dimensions.

    Args:
        image: The decoded pixels, RGB or grayscale. Not modified.
        width: Target width in pixels; must be positive.
        height: Target height in pixels; must be positive.
        engine: The engine to transform with.

    Returns:
        A new image at the requested size.

    Raises:
        ImagePrimitiveError: A dimension is not positive, or the engine refuses the scale.
    """
    _require_positive(width, height, "resize_image")
    opencv = engine_operation(engine, "resize")
    shrinking = width * height < image.shape[0] * image.shape[1]
    interpolation = INTERPOLATION_FOR_SHRINK if shrinking else INTERPOLATION_FOR_GROWTH
    return opencv(
        image, (width, height), interpolation=engine_operation(engine, interpolation)
    )


def convert_to_grayscale(image: ImageArray, engine: EngineChoice) -> ImageArray:
    """Drop colour, keeping luminance.

    Args:
        image: The decoded pixels, RGB or grayscale. Not modified.
        engine: The engine to transform with.

    Returns:
        A new single-channel image.

    Raises:
        ImagePrimitiveError: The conversion cannot be applied.
    """
    return to_grayscale(image, engine)


def binarize_image(
    image: ImageArray, engine: EngineChoice, threshold: int | None = None
) -> ImageArray:
    """Reduce an image to two tones.

    Destructive by design, and the reason ``IMG-07`` applies it only when a metric justifies it:
    binarizing a colour document discards the colour for good.

    Grayscale is applied first when the input is colour, because a threshold on three channels at
    once is a threshold on whichever channel dominates, which is not what "the darkest pixels" means
    to a caller.

    Args:
        image: The decoded pixels, RGB or grayscale. Not modified.
        engine: The engine to transform with.
        threshold: Luminance cut on the 0-255 scale. When ``None`` the engine derives it from the
            image histogram, which is what suits a page whose overall brightness is unknown.

    Returns:
        A new two-tone image, single-channel.

    Raises:
        ImagePrimitiveError: The threshold is out of range, or binarization fails.
    """
    if threshold is not None and not 0 <= threshold <= 255:
        raise classify_transformation_failure(
            "binarize_image", f"threshold must be within 0-255, got {threshold}"
        )
    threshold_fn = engine_operation(engine, "threshold")
    flags = engine_operation(engine, "THRESH_BINARY")
    if threshold is None:
        cut = OTSU_THRESHOLD
        flags |= engine_operation(engine, "THRESH_OTSU")
    else:
        cut = threshold
    return threshold_fn(to_grayscale(image, engine), cut, 255, flags)[1]


def denoise_image(image: ImageArray, engine: EngineChoice) -> ImageArray:
    """Suppress sensor and compression noise.

    Uses the fast non-local means filter, which averages each pixel with others whose neighbourhoods
    look like its own. That keeps edges and thin strokes intact where a blur would smear them, which
    matters when the result is measured for sharpness or fed to line detection.

    Args:
        image: The decoded pixels, RGB or grayscale. Not modified.
        engine: The engine to transform with.

    Returns:
        A new, denoised image with the input's channel structure.

    Raises:
        ImagePrimitiveError: Denoising cannot be applied.
    """
    if image.ndim == GRAYSCALE_RANK:
        denoise = engine_operation(engine, "fastNlMeansDenoising")
        return denoise(
            image,
            None,
            DEFAULT_DENOISE_STRENGTH,
            TEMPLATE_WINDOW_SIZE,
            SEARCH_WINDOW_SIZE,
        )
    denoise = engine_operation(engine, "fastNlMeansDenoisingColored")
    return denoise(
        image,
        None,
        DEFAULT_DENOISE_STRENGTH,
        COLOUR_DENOISE_STRENGTH,
        TEMPLATE_WINDOW_SIZE,
        SEARCH_WINDOW_SIZE,
    )


def sharpen_image(image: ImageArray, engine: EngineChoice) -> ImageArray:
    """Increase local edge contrast by unsharp masking.

    The image plus :data:`SHARPEN_AMOUNT` times its own high-pass residual, computed against a
    Gaussian low-pass reference. Written out rather than delegated because the engine's sharpening
    kernel carries no low-pass step, so it would amplify grain as readily as edges.

    Args:
        image: The decoded pixels, RGB or grayscale. Not modified.
        engine: The engine to transform with.

    Returns:
        A new, sharpened image. Values that would leave the 0-255 range are clamped, so the result
        never wraps a bright edge to black.

    Raises:
        ImagePrimitiveError: Sharpening cannot be applied.
    """
    blur = engine_operation(engine, "GaussianBlur")
    combine = engine_operation(engine, "addWeighted")
    low_pass = blur(image, (0, 0), SHARPEN_SIGMA)
    sharpened = combine(image, 1.0 + SHARPEN_AMOUNT, low_pass, -SHARPEN_AMOUNT, 0.0)
    return np.clip(sharpened, 0, 255).astype(image.dtype)


def normalize_contrast(image: ImageArray, engine: EngineChoice) -> ImageArray:
    """Stretch local contrast across an image's tiles.

    Contrast-limited adaptive histogram equalization. The tiling is what makes it usable on a page
    photographed with a shadow across it: a global stretch would leave the shadowed half dark, while
    a per-tile one lifts the local range without amplifying noise, because the clip limit caps how
    far a flat tile may be stretched.

    A colour image goes through brightness only, in CIELAB, so luminance is stretched without the
    hue shifting - equalizing the channels independently would recolour the page.

    Args:
        image: The decoded pixels, RGB or grayscale. Not modified.
        engine: The engine to transform with.

    Returns:
        A new image with stretched contrast, with the input's channel structure.

    Raises:
        ImagePrimitiveError: The stretch cannot be applied.
    """
    equalize = engine_operation(engine, "createCLAHE")
    clahe = equalize(clipLimit=CLIP_LIMIT, tileGridSize=CLIP_TILE_GRID)
    if image.ndim == GRAYSCALE_RANK:
        return clahe.apply(image)
    convert = engine_operation(engine, "cvtColor")
    lab = convert(image, engine_operation(engine, "COLOR_RGB2LAB"))
    lab[:, :, 0] = clahe.apply(lab[:, :, 0])
    return convert(lab, engine_operation(engine, "COLOR_LAB2RGB"))


def normalize_brightness(
    image: ImageArray, engine: EngineChoice, target: float = 128.0
) -> ImageArray:
    """Shift an image's mean luminance towards a target.

    The shift is capped so a pixel cannot wrap around the ends of the range, which is the failure
    mode of a naive offset: adding to a bright page without clamping turns white paper black.

    Args:
        image: The decoded pixels, RGB or grayscale. Not modified.
        engine: The engine to transform with.
        target: Desired mean luminance on the 0-255 scale.

    Returns:
        A new image with shifted brightness, with the input's channel structure.

    Raises:
        ImagePrimitiveError: The shift cannot be applied.
    """
    if not 0.0 <= target <= 255.0:
        raise classify_transformation_failure(
            "normalize_brightness", f"target must be within 0-255, got {target}"
        )
    current = float(to_grayscale(image, engine).mean())
    shift = target - current
    if shift == 0.0:
        return image.copy()
    shifted = np.clip(image.astype(np.float64) + shift, 0, 255)
    return shifted.astype(image.dtype)


def convert_image_format(
    image: ImageArray, format_name: str, engine: EngineChoice
) -> ImageArray:
    """Re-encode an image through another format, keeping the source colour convention.

    "Transform" here means *round-trip*: the image is encoded into the requested container and
    decoded straight back, so the caller receives the pixels the new format can actually carry. That
    is what makes the primitive honest about lossy formats - a JPEG round-trip loses detail, and the
    returned array shows that rather than claiming a conversion that did not happen.

    Args:
        image: The decoded pixels, RGB or grayscale. Not modified.
        format_name: Target container, e.g. ``"png"`` or ``"jpg"``, without a leading dot.
        engine: The engine to transform with.

    Returns:
        The re-decoded pixels, with the input's channel structure.

    Raises:
        ImagePrimitiveError: The container is unknown, or the round-trip fails.
    """
    encode = engine_operation(engine, "imencode")
    decode = engine_operation(engine, "imdecode")
    extension = f".{format_name.lower().lstrip('.')}"
    _require_encodable(extension, format_name)
    payload = _encode(
        encode, _for_engine(image, engine), extension, None, format_name, engine
    )
    restored = decode(
        np.frombuffer(payload, dtype=np.uint8),
        engine_operation(engine, "IMREAD_UNCHANGED"),
    )
    if restored is None:
        raise classify_transformation_failure(
            "convert_image_format",
            f"the engine could not decode its own {format_name} output",
        )
    return _from_engine(restored, engine)


def compress_image(image: ImageArray, quality: int, engine: EngineChoice) -> ImageArray:
    """Re-encode an image at a chosen quality, keeping the source colour convention.

    Like :func:`convert_image_format`, the result is the pixels the compression actually preserved.
    Reading the size instead would tell the caller nothing about what was lost.

    Args:
        image: The decoded pixels, RGB or grayscale. Not modified.
        quality: Codec quality, 1-100; higher keeps more detail.
        engine: The engine to transform with.

    Returns:
        The re-decoded pixels, with the input's channel structure.

    Raises:
        ImagePrimitiveError: The quality is out of range, or the round-trip fails.
    """
    if not MIN_COMPRESSION_QUALITY <= quality <= MAX_COMPRESSION_QUALITY:
        raise classify_transformation_failure(
            "compress_image",
            f"quality must be within {MIN_COMPRESSION_QUALITY}-{MAX_COMPRESSION_QUALITY}, "
            f"got {quality}",
        )
    encode = engine_operation(engine, "imencode")
    decode = engine_operation(engine, "imdecode")
    payload = _encode(
        encode, _for_engine(image, engine), ".jpg", quality, "compression", engine
    )
    restored = decode(
        np.frombuffer(payload, dtype=np.uint8),
        engine_operation(engine, "IMREAD_UNCHANGED"),
    )
    if restored is None:
        raise classify_transformation_failure(
            "compress_image", "the engine could not decode its own JPEG output"
        )
    return _from_engine(restored, engine)


def _for_engine(image: ImageArray, engine: EngineChoice) -> ImageArray:
    """Return the array in the channel order the engine's encoders expect.

    The seam normalises every image to RGB, but OpenCV's *encoders* expect BGR - the same engine
    that decodes to BGR. Returning the RGB array directly would swap red and blue in every written
    file, which is invisible on a grayscale test and glaring on a real one.

    Args:
        image: The decoded pixels, in RGB order.
        engine: The engine that will encode it.

    Returns:
        The array to hand to the encoder.
    """
    if _is_colour(image) and engine is EngineChoice.OPENCV:
        return engine_operation(engine, "cvtColor")(
            image, engine_operation(engine, "COLOR_RGB2BGR")
        )
    return image


def _from_engine(image: ImageArray, engine: EngineChoice) -> ImageArray:
    """Return a decoded array in the RGB order the rest of the processor expects.

    The inverse of :func:`_for_engine`, and required for the same reason: ``imdecode`` hands back
    whatever the container holds, which for OpenCV is BGR. Without this the round-trip would return
    a channel-swapped image even through a lossless format - a defect that a test checking only the
    shape would not notice.

    Args:
        image: The pixels as the engine decoded them.
        engine: The engine that decoded them.

    Returns:
        The pixels in RGB order when colour, otherwise unchanged.
    """
    if _is_colour(image) and engine is EngineChoice.OPENCV:
        return engine_operation(engine, "cvtColor")(
            image, engine_operation(engine, "COLOR_BGR2RGB")
        )
    return image


def _is_colour(image: ImageArray) -> bool:
    """Report whether an array carries three channels.

    Args:
        image: The array to inspect.

    Returns:
        ``True`` for a three-channel image.
    """
    return image.ndim == 3 and image.shape[2] == CHANNEL_COUNT_RGB


def _encode(
    encode: object,
    image: ImageArray,
    extension: str,
    quality: int | None,
    operation: str,
    engine: EngineChoice,
) -> bytes:
    """Encode an image, turning the engine's failure into the contract's vocabulary.

    Args:
        encode: The engine's encoder.
        image: The array to encode, already in the encoder's channel order.
        extension: Container extension including the dot.
        quality: Codec quality when the container takes one, else ``None``.
        operation: Primitive name, for the failure message.
        engine: The engine to resolve the quality flag with.

    Returns:
        The encoded bytes.

    Raises:
        ImagePrimitiveError: The engine refused the container or the encode.
    """
    parameters = (
        []
        if quality is None
        else [engine_operation(engine, _quality_flag(extension)), int(quality)]
    )
    # The extension comes first: `imencode(ext, img[, params])`. Passing the image first is the
    # natural reading and the engine reports it only as "Can't convert object to 'str'".
    succeeded, payload = encode(extension, image, parameters)
    if not succeeded or payload is None:
        raise classify_transformation_failure(
            operation, f"the engine could not encode into {extension}"
        )
    return bytes(payload)


def _require_encodable(extension: str, format_name: str) -> None:
    """Refuse a container the engine has no encoder for.

    Checked before the call because the engine's failure for an unknown extension is an exception
    raised from native code, which is neither the contract's vocabulary nor something a caller can
    classify.

    Args:
        extension: Container extension including the dot.
        format_name: The name the caller asked for, for the failure message.

    Raises:
        ImagePrimitiveError: The container has no encoder.
    """
    if extension not in ENCODABLE_FORMATS:
        raise classify_transformation_failure(
            "convert_image_format",
            f"no encoder for {format_name!r}; expected one of {sorted(ENCODABLE_FORMATS)}",
        )


def _quality_flag(extension: str) -> int:
    """Return the encoder flag naming a quality parameter for a container.

    Args:
        extension: Container extension including the dot.

    Returns:
        The engine's constant name for that container's quality knob.
    """
    return (
        "IMWRITE_JPEG_QUALITY"
        if extension in {".jpg", ".jpeg"}
        else "IMWRITE_PNG_COMPRESSION"
    )


__all__ = [
    "BINARIZATION_THRESHOLD",
    "CLIP_LIMIT",
    "CLIP_TILE_GRID",
    "COLOUR_DENOISE_STRENGTH",
    "DEFAULT_DENOISE_STRENGTH",
    "INTERPOLATION_FOR_GROWTH",
    "INTERPOLATION_FOR_SHRINK",
    "MAX_COMPRESSION_QUALITY",
    "MIN_COMPRESSION_QUALITY",
    "OTSU_THRESHOLD",
    "QUARTER_TURNS_PER_TURN",
    "SEARCH_WINDOW_SIZE",
    "SHARPEN_AMOUNT",
    "SHARPEN_SIGMA",
    "TEMPLATE_WINDOW_SIZE",
    "binarize_image",
    "compress_image",
    "convert_image_format",
    "convert_to_grayscale",
    "denoise_image",
    "deskew_image",
    "normalize_brightness",
    "normalize_contrast",
    "resize_image",
    "rotate_image",
    "sharpen_image",
    "to_grayscale",
    "turn_quarter",
]
