"""Load and store primitives - reading an image and its technical facts.

The rule that shapes this module is at the end of its name: **nothing here writes back to the
source**. ``save_image`` refuses a destination equal to the image it read, because a processor
that overwrote its input could not be re-run and would destroy the only copy of the original.

Phase 1 declares the shapes; ``IMG-03`` fills them in.
"""

from __future__ import annotations

# pylint: disable=duplicate-code
# Same skeleton shape as `analysis.py` and `transform.py`; the reason is stated once there, in
# the `duplicate-code` block above `PRIMITIVE_ERROR_TYPES`' sibling module. `IMG-03` replaces
# each body and this disable goes with the last of them.
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

from docflow.image.primitives.engine import EngineChoice

SUPPORTED_FORMATS: frozenset[str] = frozenset(
    {"PNG", "JPEG", "JPG", "TIFF", "TIF", "BMP", "WEBP", "GIF"}
)
"""The formats the engine is allowed to decode.

A closed set rather than "whatever the engine accepts", so an unsupported file is reported as
``UNSUPPORTED_FORMAT`` instead of being coerced into a format the rest of the pipeline does not
expect.
"""


@dataclass(frozen=True)
class ImageFileFacts:
    """What can be known about an image file without decoding it.

    Attributes:
        path: The file's own path, read but never written.
        format: Format name as the file declares it, upper-cased.
        size: The file's size in bytes.
    """

    path: Path
    format: str
    size: int


@dataclass(frozen=True)
class ImageDimensions:
    """An image's pixel dimensions.

    Attributes:
        width: Width in pixels.
        height: Height in pixels.
    """

    width: int
    height: int


def load_image(path: Path, engine: EngineChoice) -> ModuleType:
    """Decode an image file into an engine-native image.

    Args:
        path: The file to read.
        engine: The engine to decode with, named explicitly.

    Returns:
        The engine's own image object.

    Raises:
        ImageEngineNotAvailableError: The engine is missing.
        ImagePrimitiveError: The file cannot be decoded, typed ``DECODE_ERROR`` or
            ``UNSUPPORTED_FORMAT`` rather than raising the engine's own exception.

    # TODO: [MVP] decode for real; the skeleton raises before touching the file.
    """
    raise NotImplementedError


def save_image(image: ModuleType, path: Path, engine: EngineChoice) -> Path:
    """Write an engine-native image to a destination path.

    The destination is chosen by the caller and is never the source path: the primitive checks
    the two differ rather than trusting the caller to remember.

    Args:
        image: The engine-native image to write.
        path: Where to write it; must not be the path the image was read from.
        engine: The engine to encode with.

    Returns:
        The path written.

    Raises:
        ImagePrimitiveError: The destination is the source path, or the write fails.

    # TODO: [MVP] encode for real; the skeleton raises before touching the file.
    """
    raise NotImplementedError


def get_image_metadata(path: Path, engine: EngineChoice) -> ImageFileFacts:
    """Read a file's format and size without decoding its pixels.

    Args:
        path: The file to read.
        engine: The engine to read with.

    Returns:
        The file's facts.

    Raises:
        ImageEngineNotAvailableError: The engine is missing.
        ImagePrimitiveError: The file is not an image this engine can read.
            ``UNSUPPORTED_FORMAT`` when the format is not in :data:`SUPPORTED_FORMATS`.

    # TODO: [MVP] read the header for real.
    """
    raise NotImplementedError


def get_image_dimensions(image: ModuleType, engine: EngineChoice) -> ImageDimensions:
    """Read an already-decoded image's pixel dimensions.

    Args:
        image: The engine-native image.
        engine: The engine that produced it.

    Returns:
        The dimensions.

    # TODO: [MVP] read the shape for real.
    """
    raise NotImplementedError


__all__ = [
    "SUPPORTED_FORMATS",
    "ImageDimensions",
    "ImageFileFacts",
    "get_image_dimensions",
    "get_image_metadata",
    "load_image",
    "save_image",
]
