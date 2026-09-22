"""Transformation primitives - the only module allowed to change pixels.

Every function here takes an image and returns a *new* one; none of them mutates its input in
place. That is a contract, not a style choice: ``IMG-07`` records every transformation it
applies, and a function that edited its argument would make the record a description of a
side effect rather than of a returned value.

The engine is passed in rather than chosen here - the seam in
:mod:`docflow.image.primitives.engine` decides which library is loaded, and a primitive that
picked its own engine would be a second, quieter seam.
"""

from __future__ import annotations

# pylint: disable=duplicate-code
# Same skeleton shape as `analysis.py`; the reason is stated in full there. `IMG-05` replaces
# each body and this disable goes with the last of them.
from types import ModuleType

from docflow.image.primitives.engine import EngineChoice
from docflow.image.primitives.failures import ImagePrimitiveError

INTERPOLATION_FOR_SHRINK = "area"
"""Resampling used when an image gets smaller.

Averaging over the source pixels is what keeps a downscale from aliasing; a nearest-neighbour
shrink would drop detail and make a legibility measure meaningless.
"""


def rotate_image(image: ModuleType, degrees: float, engine: EngineChoice) -> ModuleType:
    """Rotate an image about its centre.

    Args:
        image: The engine-native image; not modified.
        degrees: Rotation in degrees, positive counter-clockwise.
        engine: The engine to transform with.

    Returns:
        A new rotated image, sized to hold the rotated content.

    Raises:
        ImagePrimitiveError: The rotation cannot be applied.

    # TODO: [MVP] transform for real; the skeleton raises.
    """
    raise NotImplementedError


def deskew_image(image: ModuleType, angle: float, engine: EngineChoice) -> ModuleType:
    """Straighten an image by the given small angle.

    Args:
        image: The engine-native image; not modified.
        angle: The skew from :func:`docflow.image.primitives.analysis.detect_skew_angle`.
        engine: The engine to transform with.

    Returns:
        A new, straightened image.

    Raises:
        ImagePrimitiveError: The correction cannot be applied.

    # TODO: [MVP] transform for real; the skeleton raises.
    """
    raise NotImplementedError


def resize_image(
    image: ModuleType, width: int, height: int, engine: EngineChoice
) -> ModuleType:
    """Scale an image to exact pixel dimensions.

    Args:
        image: The engine-native image; not modified.
        width: Target width in pixels; must be positive.
        height: Target height in pixels; must be positive.
        engine: The engine to transform with.

    Returns:
        A new image at the requested size.

    Raises:
        ImagePrimitiveError: A dimension is not positive, or the scale fails.

    # TODO: [MVP] transform for real; the skeleton raises.
    """
    raise NotImplementedError


def convert_to_grayscale(image: ModuleType, engine: EngineChoice) -> ModuleType:
    """Drop colour, keeping luminance.

    Args:
        image: The engine-native image; not modified.
        engine: The engine to transform with.

    Returns:
        A new single-channel image.

    Raises:
        ImagePrimitiveError: The conversion cannot be applied.

    # TODO: [MVP] transform for real; the skeleton raises.
    """
    raise NotImplementedError


def binarize_image(
    image: ModuleType, engine: EngineChoice, threshold: int = 128
) -> ModuleType:
    """Reduce an image to two tones.

    Destructive by design, and the reason ``IMG-07`` only applies it when a metric justifies
    it: binarizing a colour document throws the colour away for good.

    Args:
        image: The engine-native image; not modified.
        engine: The engine to transform with.
        threshold: Luminance cut on the 0-255 scale.

    Returns:
        A new two-tone image.

    Raises:
        ImagePrimitiveError: The threshold is out of range, or binarization fails.

    # TODO: [MVP] transform for real; the skeleton raises.
    """
    raise NotImplementedError


def denoise_image(image: ModuleType, engine: EngineChoice) -> ModuleType:
    """Suppress sensor and compression noise.

    Args:
        image: The engine-native image; not modified.
        engine: The engine to transform with.

    Returns:
        A new, denoised image.

    Raises:
        ImagePrimitiveError: Denoising cannot be applied.

    # TODO: [MVP] transform for real; the skeleton raises.
    """
    raise NotImplementedError


def sharpen_image(image: ModuleType, engine: EngineChoice) -> ModuleType:
    """Increase local edge contrast.

    Args:
        image: The engine-native image; not modified.
        engine: The engine to transform with.

    Returns:
        A new, sharpened image.

    Raises:
        ImagePrimitiveError: Sharpening cannot be applied.

    # TODO: [MVP] transform for real; the skeleton raises.
    """
    raise NotImplementedError


def normalize_contrast(image: ModuleType, engine: EngineChoice) -> ModuleType:
    """Stretch luminance to use the full available range.

    Args:
        image: The engine-native image; not modified.
        engine: The engine to transform with.

    Returns:
        A new image with stretched contrast.

    Raises:
        ImagePrimitiveError: The stretch cannot be applied.

    # TODO: [MVP] transform for real; the skeleton raises.
    """
    raise NotImplementedError


def normalize_brightness(image: ModuleType, engine: EngineChoice) -> ModuleType:
    """Shift luminance towards a mid-range target.

    Args:
        image: The engine-native image; not modified.
        engine: The engine to transform with.

    Returns:
        A new image with adjusted brightness.

    Raises:
        ImagePrimitiveError: The shift cannot be applied.

    # TODO: [MVP] transform for real; the skeleton raises.
    """
    raise NotImplementedError


def convert_image_format(
    image: ModuleType, format_name: str, engine: EngineChoice
) -> ModuleType:
    """Re-encode an image into another format.

    Args:
        image: The engine-native image; not modified.
        format_name: Target format, e.g. ``"PNG"``; must be a supported format.
        engine: The engine to transform with.

    Returns:
        The re-encoded image.

    Raises:
        ImagePrimitiveError: The format is not supported, or encoding fails.

    # TODO: [MVP] transform for real; the skeleton raises.
    """
    raise NotImplementedError


def compress_image(image: ModuleType, quality: int, engine: EngineChoice) -> ModuleType:
    """Re-encode an image at a chosen quality.

    Args:
        image: The engine-native image; not modified.
        quality: Codec quality, 1-100; higher keeps more detail.
        engine: The engine to transform with.

    Returns:
        The re-encoded image.

    Raises:
        ImagePrimitiveError: The quality is out of range, or encoding fails.

    # TODO: [MVP] transform for real; the skeleton raises.
    """
    raise NotImplementedError


__all__ = [
    "INTERPOLATION_FOR_SHRINK",
    "ImagePrimitiveError",
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
]
