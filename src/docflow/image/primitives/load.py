"""Load and store primitives - reading an image and its technical facts.

The rule that shapes this module is at the end of its name: **nothing here writes back to a file
that already exists**. :func:`save_image` refuses an occupied destination, because a processor that
clobbered its own input could not be re-run and would destroy the only copy of the original.

Three engine asymmetries were measured rather than assumed, and all three are resolved here so
nothing downstream has to know which engine ran:

* **Channel order.** OpenCV decodes to BGR and Pillow to RGB. Every colour image leaving this module
  is in **RGB**, converted exactly once inside :func:`load_image`.
* **How failure is signalled.** ``cv2.imread`` returns ``None`` for a file it cannot decode while
  writing the reason to file descriptor 2; Pillow raises. Both become a typed
  :class:`ImagePrimitiveError`, and the descriptor noise is silenced because the same information
  travels through the contract.
* **How the format is named.** Pillow parses the header and reports ``JPEG`` perfectly. OpenCV
  offers only a yes/no header check, so identifying the format through it would mean falling back
  to the **file extension** - and a ``.jpg`` that actually holds a PNG would be reported as a JPEG.
  The format is therefore read from the file's magic bytes, which is both engine-independent and
  the only answer that matches the header rather than the file name.
"""

from __future__ import annotations

import contextlib
import os
import struct
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from docflow.image.contracts import ImageDimensions
from docflow.image.primitives.engine import (
    CHANNEL_COUNT_RGB,
    CHANNEL_RANK_GRAYSCALE,
    EngineChoice,
    ImageArray,
    array_module,
    operations_module,
)
from docflow.image.primitives.failures import (
    classify_decode_failure,
    classify_input_failure,
    classify_write_failure,
)

SUPPORTED_FORMATS: frozenset[str] = frozenset(
    {"PNG", "JPEG", "TIFF", "BMP", "WEBP", "GIF"}
)
"""The formats the processor is allowed to decode.

Canonical names, not aliases: ``JPEG`` covers both ``.jpg`` and ``.jpeg``, because those are two
spellings of one format and a set listing both would invite code that treats them as different.
"""

COLOUR_ORDER = "RGB"
"""The channel order of every colour image leaving this module, whichever engine decoded it."""

MAX_HEADER_BYTES = 12
"""How many leading bytes are needed to identify every format in :data:`SUPPORTED_FORMATS`."""

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
"""The eight bytes every PNG starts with; also the offset the chunk chain begins at."""

RESOLUTION_PREFIX_BYTES = 4096
"""How much of a file is read when looking for a declared resolution.

Bounded rather than reading the whole file because a scanned input can be tens of megabytes and
the two containers that declare a resolution do so before their pixel data: PNG's ``pHYs`` must
precede ``IDAT``, and a JPEG's JFIF segment follows the start-of-image marker directly.
"""

INCHES_PER_METRE = 39.3701
"""PNG states its resolution per metre, so a declared value comes back through this divisor."""

CENTIMETRES_PER_INCH = 2.54
"""JFIF can state its resolution per centimetre instead of per inch."""

_PNG_RESOLUTION_CHUNK = b"pHYs"
_PNG_PIXEL_DATA_CHUNK = b"IDAT"
_PNG_UNIT_METRE = 1
"""PNG's resolution chunk, the chunk that ends the search, and its "unit is the metre" flag."""

_JFIF_MARKER = b"JFIF\x00"
_JFIF_UNITS_PER_INCH = 1
_JFIF_UNITS_PER_CENTIMETRE = 2
"""The JFIF application segment and its two units, the third being "aspect ratio only"."""

_MAGIC_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (_PNG_SIGNATURE, "PNG"),
    (b"\xff\xd8\xff", "JPEG"),
    (b"II*\x00", "TIFF"),
    (b"MM\x00*", "TIFF"),
    (b"BM", "BMP"),
    (b"GIF87a", "GIF"),
    (b"GIF89a", "GIF"),
)
"""Leading bytes that identify a format, longest first where a prefix could be ambiguous."""

_WEBP_PREFIX = b"RIFF"
_WEBP_MARKER = b"WEBP"
"""WebP is a RIFF container, so its ``WEBP`` marker sits at offset 8 rather than at the start."""

_PILLOW_SINGLE_CHANNEL_MODES: frozenset[str] = frozenset({"L", "1", "I", "F"})
"""Pillow modes that carry one channel, in its several spellings.

`L` is 8-bit luminance, `1` is bilevel, and `I` and `F` are wider integer and float samples.
They are grouped here rather than collapsed to `L`, because converting a wider mode to
`L` would rescale its values.
"""


@dataclass(frozen=True)
class ImageFileFacts:
    """What can be known about an image file without decoding its pixels.

    Attributes:
        path: The file's own path, read but never written.
        format: Format name from the file's header, in the canonical spelling of
            :data:`SUPPORTED_FORMATS`.
        size: The file's size in bytes.
        resolution: Dots per inch the file declares, or ``None`` when it declares none this reader
            can determine. Only PNG and JPEG are read; see :func:`_resolution_from_header`.
    """

    path: Path
    format: str
    size: int
    resolution: int | None


def load_image(
    path: Path, engine: EngineChoice, *, grayscale: bool = False
) -> ImageArray:
    """Decode an image file into an engine-agnostic array.

    The result is always RGB for colour and single-channel for grayscale, whichever engine ran.
    That normalisation is why this is not a one-line delegation: OpenCV would hand back BGR, and a
    caller comparing two engines' output would see an unexplained channel swap.

    Args:
        path: The file to read.
        engine: The engine to decode with, named explicitly.
        grayscale: When true, decode one channel instead of RGB.

    Returns:
        The decoded pixels, in RGB order or grayscale.

    Raises:
        ImageEngineNotAvailableError: The engine or the array library is missing.
        ImagePrimitiveError: ``INVALID_INPUT`` when the file cannot be read, ``UNSUPPORTED_FORMAT``
            when its header names a format outside :data:`SUPPORTED_FORMATS`, or ``DECODE_ERROR``
            when a supported format fails to decode.
    """
    facts = get_image_metadata(path, engine)

    if engine is EngineChoice.OPENCV:
        return _load_with_opencv(path, facts, grayscale=grayscale)
    return _load_with_pillow(path, engine, facts, grayscale=grayscale)


def save_image(image: ImageArray, path: Path, engine: EngineChoice) -> Path:
    """Write an array to a destination path that must not already exist.

    The plan states the rule as "``save_image`` must never target ``image_path``". This implements
    the enforceable form of it, because a primitive holding an array cannot prove which file the
    array came from: a guard comparing against a caller-supplied source path would pass while the
    source was destroyed. An existing file is either that source or a previous run's artifact, so
    replacing one is a decision the caller makes visibly.

    Args:
        image: The array to write, in RGB order or grayscale.
        path: Where to write it; must not already exist.
        engine: The engine to encode with.

    Returns:
        The path written.

    Raises:
        ImageEngineNotAvailableError: The engine is missing.
        ImagePrimitiveError: ``WRITE_ERROR`` when the destination exists, the format is
            unsupported, or the library cannot encode or write the image.
    """
    if path.exists():
        raise classify_write_failure(
            str(path),
            "refusing to overwrite an existing file: the destination may be the source image or "
            "a previous run's artifact",
        )

    target_format = _format_from_extension(path)
    if target_format is None or target_format not in SUPPORTED_FORMATS:
        raise classify_write_failure(
            str(path),
            f"the destination extension names no supported format; expected one of "
            f"{sorted(SUPPORTED_FORMATS)}",
        )

    if engine is EngineChoice.OPENCV:
        _save_with_opencv(image, path)
    else:
        _save_with_pillow(image, path, engine)
    return path


def get_image_metadata(path: Path, engine: EngineChoice) -> ImageFileFacts:
    """Read a file's format and size without decoding its pixels.

    The format comes from the file's magic bytes, never from its extension: a ``.jpg`` that holds a
    PNG is reported as a PNG, because the extension is a naming convention and the header is the
    fact. Reading the bytes directly also makes this identical under either engine, so the answer
    cannot drift when the engine is swapped.

    Args:
        path: The file to read.
        engine: The engine that will read it, resolved first so a missing engine is not reported as
            a bad file.

    Returns:
        The file's facts.

    Raises:
        ImageEngineNotAvailableError: The engine is missing.
        ImagePrimitiveError: ``INVALID_INPUT`` when the file cannot be read, or
            ``UNSUPPORTED_FORMAT`` when its header names a format outside
            :data:`SUPPORTED_FORMATS`.
    """
    if not path.is_file():
        raise classify_input_failure(str(path), "file does not exist or is not a file")

    # Resolving the engine before reading means a missing engine is reported as such rather than as
    # an unreadable file, which would send the operator to the wrong problem.
    operations_module(engine)

    format_name = _format_from_header(path)
    if format_name is None:
        raise classify_decode_failure(
            str(path),
            None,
            "the file's header does not name a format this processor reads",
        )
    if format_name not in SUPPORTED_FORMATS:
        raise classify_decode_failure(
            str(path),
            format_name,
            f"format {format_name} is outside the supported set "
            f"{sorted(SUPPORTED_FORMATS)}",
        )
    return ImageFileFacts(
        path=path,
        format=format_name,
        size=path.stat().st_size,
        resolution=_resolution_from_header(path, format_name),
    )


def get_image_dimensions(image: ImageArray, engine: EngineChoice) -> ImageDimensions:
    """Read an already-decoded array's pixel dimensions.

    Takes the array rather than a path, so a caller does not decode a second time to learn
    something the first decode already knew.

    Args:
        image: The decoded pixels.
        engine: The engine that produced them; an array's shape is the same fact under either
            engine, so this is read for symmetry with the other primitives.

    Returns:
        The dimensions.

    Raises:
        ImagePrimitiveError: ``INVALID_INPUT`` when the array has no usable shape.
    """
    _ = engine
    shape = getattr(image, "shape", None)
    if shape is None or len(shape) < CHANNEL_RANK_GRAYSCALE:
        raise classify_input_failure(
            "<array>", f"expected a 2D or 3D array, got shape {shape!r}"
        )
    height, width = int(shape[0]), int(shape[1])
    if height <= 0 or width <= 0:
        raise classify_input_failure(
            "<array>", f"expected positive dimensions, got {width}x{height}"
        )
    return ImageDimensions(width=width, height=height)


def _format_from_header(path: Path) -> str | None:
    """Identify a file's format from its magic bytes.

    Args:
        path: The file to identify.

    Returns:
        The canonical format name, or ``None`` when no known signature matches.
    """
    header = path.read_bytes()[:MAX_HEADER_BYTES]
    if header[: len(_WEBP_PREFIX)] == _WEBP_PREFIX and header[8:12] == _WEBP_MARKER:
        return "WEBP"
    for signature, name in _MAGIC_SIGNATURES:
        if header.startswith(signature):
            return name
    return None


def _resolution_from_header(path: Path, format_name: str) -> int | None:
    """Read the resolution a file declares, or ``None``.

    Read from the raw bytes rather than asked of the engine, for the same reason the format is:
    OpenCV exposes no way to read a resolution at all, so delegating would make this field's value
    depend on which engine happened to run - and a swap that changes a recorded number is exactly
    what the seam exists to prevent.

    Only PNG and JPEG are read. Those are what this processor produces and between them they cover
    the common inputs; the other supported containers report ``None``, which the contract defines as
    "not determined" rather than as a measurement of zero.

    A file declaring different horizontal and vertical resolutions also reports ``None``. The
    contract carries one integer, and filling it with either axis would silently assert the image is
    square-pixeled when the file says it is not.

    Args:
        path: The file to read.
        format_name: Its already-determined format, so the bytes are not re-sniffed.

    Returns:
        Dots per inch, or ``None``.

    # TODO: [MVP] TIFF and BMP declare a resolution too; a scanner that writes TIFF reports None.
    """
    if format_name not in {"PNG", "JPEG"}:
        return None
    with path.open("rb") as handle:
        prefix = handle.read(RESOLUTION_PREFIX_BYTES)
    if format_name == "PNG":
        return _png_resolution(prefix)
    return _jpeg_resolution(prefix)


def _png_resolution(prefix: bytes) -> int | None:
    """Read a PNG's ``pHYs`` chunk.

    Args:
        prefix: The first bytes of the file.

    Returns:
        Dots per inch, or ``None`` when the chunk is absent, states another unit, or is not square.
    """
    index = len(_PNG_SIGNATURE)
    while index + 12 <= len(prefix):
        length = struct.unpack(">I", prefix[index : index + 4])[0]
        kind = prefix[index + 4 : index + 8]
        if kind == _PNG_RESOLUTION_CHUNK:
            per_x, per_y, unit = struct.unpack(">IIB", prefix[index + 8 : index + 17])
            if unit != _PNG_UNIT_METRE:
                return None
            horizontal = round(per_x / INCHES_PER_METRE)
            vertical = round(per_y / INCHES_PER_METRE)
            return horizontal if horizontal == vertical else None
        if kind == _PNG_PIXEL_DATA_CHUNK:
            # The spec places pHYs before the pixel data, so reaching IDAT means there is none.
            return None
        index += 12 + length
    return None


def _jpeg_resolution(prefix: bytes) -> int | None:
    """Read a JPEG's JFIF application segment.

    Args:
        prefix: The first bytes of the file.

    Returns:
        Dots per inch, or ``None`` when there is no JFIF segment or it states another unit.
    """
    index = 2
    while index + 4 <= len(prefix):
        if prefix[index] != 0xFF:
            index += 1
            continue
        marker = prefix[index + 1]
        if marker in {0xD8, 0x01} or 0xD0 <= marker <= 0xD7:
            index += 2
            continue
        length = struct.unpack(">H", prefix[index + 2 : index + 4])[0]
        if marker == 0xE0 and prefix[index + 4 : index + 9] == _JFIF_MARKER:
            units = prefix[index + 11]
            density_x = struct.unpack(">H", prefix[index + 12 : index + 14])[0]
            return _jfif_density(density_x, units)
        index += 2 + length
    return None


def _jfif_density(density: int, units: int) -> int | None:
    """Convert a JFIF density reading to dots per inch.

    Args:
        density: The declared density along the horizontal axis.
        units: The JFIF unit flag.

    Returns:
        Dots per inch, or ``None`` for the unit that means "aspect ratio only".
    """
    if units == _JFIF_UNITS_PER_INCH:
        return density
    if units == _JFIF_UNITS_PER_CENTIMETRE:
        return round(density * CENTIMETRES_PER_INCH)
    return None


def _format_from_extension(path: Path) -> str | None:
    """Identify the format a destination file name asks for.

    Used only for writing, where the extension is the only statement of intent available: a save
    has to choose one codec before any bytes exist.

    Args:
        path: The destination path.

    Returns:
        The canonical format name, or ``None`` when the extension names nothing supported.
    """
    suffix = path.suffix.lstrip(".").upper()
    return {"JPG": "JPEG", "TIF": "TIFF"}.get(suffix, suffix) or None


def _load_with_opencv(
    path: Path, facts: ImageFileFacts, *, grayscale: bool
) -> ImageArray:
    """Decode with OpenCV and normalise to RGB.

    A single-channel file is returned as one channel rather than promoted to three. An artifact this
    processor wrote from its own grayscale stage - ``ocr_ready.png`` - is a one-channel file, and
    reading it back as three would mean a variant could not be re-analyzed as what it actually is.

    Args:
        path: The file to read.
        facts: Its already-read facts, so the failure can name the format without re-sniffing.
        grayscale: Whether the caller wants one channel regardless of what the file holds.

    Returns:
        The decoded array, in RGB order when the file is colour.

    Raises:
        ImagePrimitiveError: ``DECODE_ERROR`` when OpenCV reports it cannot read the file.
    """
    opencv = operations_module(EngineChoice.OPENCV)
    # `IMREAD_UNCHANGED` when the caller has no preference, so the file's own channel count
    # survives. The earlier version used `IMREAD_COLOR` here, which silently promoted a
    # single-channel file to three and lost the distinction the artifacts depend on.
    mode = opencv.IMREAD_GRAYSCALE if grayscale else opencv.IMREAD_UNCHANGED
    with _engine_stderr_silenced():
        decoded = opencv.imread(str(path), mode)
    if decoded is None:
        # OpenCV signals a decode failure by returning None rather than raising. The file already
        # passed the format check, so this is a damaged file, not an unsupported one.
        raise classify_decode_failure(
            str(path), facts.format, "the image failed to decode"
        )
    if grayscale or decoded.ndim == CHANNEL_RANK_GRAYSCALE:
        return decoded
    if decoded.ndim == 3 and decoded.shape[2] == CHANNEL_COUNT_RGB:
        return opencv.cvtColor(decoded, opencv.COLOR_BGR2RGB)
    # Four-channel files are not something this processor produces; converting them would be a
    # guess about which channel to drop, so they are reported rather than silently reshaped.
    raise classify_decode_failure(
        str(path),
        facts.format,
        f"expected a grayscale or 3-channel image, got shape {decoded.shape!r}",
    )


def _load_with_pillow(
    path: Path, engine: EngineChoice, facts: ImageFileFacts, *, grayscale: bool
) -> ImageArray:
    """Decode with Pillow and normalise to RGB.

    A single-channel file stays single-channel unless the caller asks otherwise, which is what the
    OpenCV path does and what makes the two engines agree: ``ocr_ready.png`` is written from a
    grayscale stage, and reading it back as three channels would make an artifact of this processor
    unreadable as what it is.

    Args:
        path: The file to read.
        engine: The engine to decode with.
        facts: Its already-read facts, used to type the failure.
        grayscale: Whether the caller wants one channel regardless of what the file holds.

    Returns:
        The decoded array, in RGB order when the file is colour.

    Raises:
        ImagePrimitiveError: ``DECODE_ERROR`` when Pillow cannot decode the file.
    """
    pillow = operations_module(engine)
    try:
        with pillow.open(str(path)) as opened:
            target = "L" if grayscale else _pillow_mode_for(opened.mode)
            return array_module().asarray(opened.convert(target))
    except OSError as failure:
        # Pillow raises OSError for a broken stream, and UnidentifiedImageError - a subclass - for
        # an unrecognised one. Both are decode failures here: the format was already checked.
        raise classify_decode_failure(
            str(path), facts.format, str(failure)
        ) from failure


def _pillow_mode_for(source_mode: str) -> str:
    """Return the Pillow mode to convert a decoded image into.

    The single-channel modes are kept as they are; everything else becomes ``RGB``. Pillow has
    several one-channel spellings - ``L`` for 8-bit luminance, ``1`` for bilevel, and
    ``I`` and ``F`` for wider samples.
    wider samples - and collapsing them all to ``L`` would rescale the wider ones.

    Args:
        source_mode: The mode Pillow reported for the file.

    Returns:
        The mode to convert into.
    """
    return "L" if source_mode in _PILLOW_SINGLE_CHANNEL_MODES else "RGB"


@contextlib.contextmanager
def _engine_stderr_silenced() -> Iterator[None]:
    """Silence the engine's error channel while it decodes.

    OpenCV's codecs write diagnostics such as ``libpng error: IDAT: invalid window size`` straight
    to file descriptor 2. That is not :data:`sys.stderr`, so ``contextlib.redirect_stderr`` does not
    catch it and the text leaks into test output as noise that reads like a failure. Nothing is lost
    by hiding it: the same condition is reported as a typed :class:`ImagePrimitiveError` through the
    contract, which is where a caller can act on it. The descriptor is restored in a ``finally``, so
    a silenced block cannot poison the rest of the process.

    Yields:
        Nothing; the block runs with descriptor 2 redirected to the null device.
    """
    saved = os.dup(2)
    devnull = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(devnull, 2)
        yield
    finally:
        os.dup2(saved, 2)
        os.close(devnull)
        os.close(saved)


def _save_with_opencv(image: ImageArray, path: Path) -> None:
    """Encode with OpenCV, converting RGB back to the BGR order it expects.

    Args:
        image: The array to write, in RGB order or grayscale.
        path: Destination.

    Raises:
        ImagePrimitiveError: ``WRITE_ERROR`` when OpenCV cannot write the file.
    """
    opencv = operations_module(EngineChoice.OPENCV)
    to_write = image
    if getattr(image, "ndim", 0) == 3 and image.shape[2] == CHANNEL_COUNT_RGB:
        to_write = opencv.cvtColor(image, opencv.COLOR_RGB2BGR)
    if not opencv.imwrite(str(path), to_write):
        raise classify_write_failure(
            str(path), "the engine reported it could not write the image"
        )


def _save_with_pillow(image: ImageArray, path: Path, engine: EngineChoice) -> None:
    """Encode with Pillow.

    Args:
        image: The array to write, in RGB order or grayscale.
        path: Destination.
        engine: The engine to encode with.

    Raises:
        ImagePrimitiveError: ``WRITE_ERROR`` when Pillow cannot write the file.
    """
    pillow = operations_module(engine)
    mode = "L" if getattr(image, "ndim", 0) == CHANNEL_RANK_GRAYSCALE else "RGB"
    try:
        pillow.fromarray(image, mode).save(str(path))
    except (OSError, ValueError) as failure:
        raise classify_write_failure(str(path), str(failure)) from failure


__all__ = [
    "COLOUR_ORDER",
    "SUPPORTED_FORMATS",
    "ImageDimensions",
    "ImageFileFacts",
    "get_image_dimensions",
    "get_image_metadata",
    "load_image",
    "save_image",
]
