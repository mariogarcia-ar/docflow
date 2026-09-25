"""The in-memory OpenCV double (``IMG-15``).

OpenCV is a Python library: it hands back **decoded arrays and raw readings**, never files and
never an exit code. This double models exactly that. It stands where the seam resolves the
engine — the module attribute ``docflow.image.primitives.cv2`` — and answers with arrays of its
own, so the whole translation between the engine's shape and our artifact tree stays under test
(`README.md` §9.7). It never returns one of our types: a fake that returned an ``ImageResult``
would delete the half of the module it exists to exercise.

It mirrors the surface the seam touches, because the convention check in
``tests/fakes/engines/convention.py`` reads the seam statically and requires the double to
model *every* attribute the seam reaches on the engine — including the constants and the
exception type, not only the functions it calls.

**The pixels are synthetic and say so.** A decoded image is a banded grey pattern whose phase
is derived from the file's own first bytes: the container geometry read back (width, height)
is the file's, the values are the double's. That is what a double is — the readings our code
derives from those values are the code's business, and no test claims they are "right".

Three knobs make the failure paths reachable with no library installed:

* :attr:`FakeOpenCV.undecodable` — file names ``imread`` answers ``None`` for, which is how the
  engine reports a file it cannot decode;
* :attr:`FakeOpenCV.write_failures` — artifact names ``imwrite`` answers ``False`` for, which
  is how the engine reports a write it could not perform;
* :attr:`FakeOpenCV.raises` — an exception keyed by engine method name, so ``cv2.error`` and
  the paths that map it are reachable too.

Every call is recorded in :attr:`FakeOpenCV.calls`, so a test can prove which engine functions
the seam reached.

# TODO: [RELEASE] re-read this double against the engine's documented behaviour on every pin
# bump: a hand-written double is the one place an engine shape change has to be re-checked, and
# the suite cannot notice it by itself (`GEN-17`).
"""

from __future__ import annotations

import functools
import math
import struct
import zlib
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

#: The version the double reports. Deliberately synthetic: a test that asserted this value
#: would be asserting what the double was told, not what OpenCV says.
FAKE_ENGINE_VERSION = "9.9.9-test"

#: The two grey levels the synthetic image is built from: ink and paper.
INK_LEVEL = 45.0
PAPER_LEVEL = 230.0

#: Rows per band of the synthetic image. Wide bands keep the pattern's own edges rare enough
#: that the noise reading is a reading and not an artifact of the pattern.
BAND_ROWS = 8

#: The clamp every 8-bit array is kept inside.
MAX_LEVEL = 255.0

#: The suffix an atomic publication writes through before it renames. The double only needs it
#: to name an artifact the way the caller does.
TEMP_SUFFIX = ".tmp"

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class FakeCVError(Exception):
    """The engine's own exception type, which the seam maps to ``TRANSFORMATION_ERROR``."""


def _recorded(method: Callable[..., Any]) -> Callable[..., Any]:
    """Record one engine call, and honour a scripted exception for it.

    Args:
        method: The engine method to wrap.

    Returns:
        The wrapper: it appends the method's name to ``self.calls``, raises the method's
        scripted exception when one was configured, and otherwise runs the method.
    """

    @functools.wraps(method)
    def wrapper(self: FakeOpenCV, *args: Any, **kwargs: Any) -> Any:
        """Record the call, then answer it."""
        self.calls.append(method.__name__)
        scripted = self.raises.get(method.__name__)
        if scripted is not None:
            raise scripted
        return method(self, *args, **kwargs)

    return wrapper


class FakeImage:
    """An in-memory stand-in for a decoded image array.

    The layout is the engine's: a flat row-major sequence of channel values, with ``shape``
    reporting ``(height, width)`` for a single-channel image and ``(height, width, channels)``
    otherwise. Only the array behaviour the seam asks for is modelled — the readings
    (``mean``, ``std``, ``var``), absolute value, element-wise subtraction and a
    ``[rows, columns]`` slice window.
    """

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    # Reason: the constructor mirrors an array's own shape arguments: values plus geometry.

    def __init__(
        self,
        values: Sequence[float],
        width: int,
        height: int,
        channels: int = 1,
        dtype: str = "uint8",
    ) -> None:
        """Build an image over ``values``.

        Args:
            values: The channel values, row-major.
            width: Width in pixels.
            height: Height in pixels.
            channels: Channel count.
            dtype: The dtype the engine would report.

        Raises:
            ValueError: When the values do not fill the geometry — a double that silently
                reshaped them would hide a bug in the seam instead of failing loudly.
        """
        if len(values) != width * height * channels:
            raise ValueError(
                f"{len(values)} values do not fill {width}x{height}x{channels}"
            )
        self.values = [float(value) for value in values]
        self.width = width
        self.height = height
        self.channels = channels
        self.dtype = dtype

    @property
    def shape(self) -> tuple[int, ...]:
        """Return the array's shape in the engine's own convention."""
        if self.channels == 1:
            return (self.height, self.width)
        return (self.height, self.width, self.channels)

    @property
    def size(self) -> int:
        """Return the number of stored channel values."""
        return len(self.values)

    def mean(self) -> float:
        """Return the mean of every stored value."""
        return sum(self.values) / len(self.values)

    def variance(self) -> float:
        """Return the population variance of every stored value."""
        mean = self.mean()
        return sum((value - mean) ** 2 for value in self.values) / len(self.values)

    def std(self) -> float:
        """Return the population standard deviation of every stored value."""
        return math.sqrt(self.variance())

    def var(self) -> float:
        """Return the variance — the name the engine's arrays use."""
        return self.variance()

    def __abs__(self) -> FakeImage:
        """Return the element-wise absolute value."""
        return FakeImage(
            [abs(value) for value in self.values],
            self.width,
            self.height,
            self.channels,
            self.dtype,
        )

    def __getitem__(self, window: tuple[slice, slice]) -> FakeImage:
        """Return the sub-image the ``[rows, columns]`` window selects."""
        rows, columns = window
        top, bottom, _ = rows.indices(self.height)
        left, right, _ = columns.indices(self.width)
        values = [
            self.values[(y * self.width + x) * self.channels + channel]
            for y in range(top, bottom)
            for x in range(left, right)
            for channel in range(self.channels)
        ]
        return FakeImage(values, right - left, bottom - top, self.channels, self.dtype)


def _clamped(value: float) -> float:
    """Return ``value`` clamped to the 8-bit range."""
    return max(0.0, min(MAX_LEVEL, value))


def _at(image: FakeImage, x: int, y: int, channel: int = 0) -> float:
    """Return one channel value, replicating the edge outside the image.

    A coordinate outside the frame is clamped rather than answered with a constant: the engine's
    kernels read their neighbourhood with a replicated border, so a flat image has to read flat
    at its edges too. A caller that wants a *different* fill (``warpAffine``'s white wedges)
    checks the frame before asking.
    """
    clamped_x = max(0, min(image.width - 1, x))
    clamped_y = max(0, min(image.height - 1, y))
    return image.values[
        (clamped_y * image.width + clamped_x) * image.channels + channel
    ]


def _map_image(
    image: FakeImage, operation: Callable[[int, int, int], float]
) -> FakeImage:
    """Return a new image whose values come from ``operation(x, y, channel)``."""
    values = [
        _clamped(operation(x, y, channel))
        for y in range(image.height)
        for x in range(image.width)
        for channel in range(image.channels)
    ]
    return FakeImage(values, image.width, image.height, image.channels)


def _window_values(image: FakeImage, x: int, y: int, radius: int) -> list[float]:
    """Return the values of the first channel in a ``(2r+1)`` square window."""
    return [
        _at(image, x + dx, y + dy)
        for dy in range(-radius, radius + 1)
        for dx in range(-radius, radius + 1)
    ]


def _png_geometry(data: bytes) -> tuple[int, int] | None:
    """Return a PNG's width and height, or ``None`` when the file is not a complete PNG.

    A real decoder refuses a file whose structure is incomplete, so this double does too: the
    signature, a readable header and the end-of-file chunk all have to be present.
    """
    if not data.startswith(_PNG_SIGNATURE) or len(data) < 33:
        return None
    if data[12:16] != b"IHDR":
        return None
    if b"IEND" not in data[33:]:
        return None
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def _png_bytes(image: FakeImage) -> bytes:
    """Encode an image as a real, decodable 8-bit PNG.

    The published artifact has to be a genuine file: that is what makes it worth asserting that
    our publication did not mangle it.
    """
    colour_type = 2 if image.channels >= 3 else 0
    samples = image.channels if image.channels >= 3 else 1
    header = struct.pack(">IIBBBBB", image.width, image.height, 8, colour_type, 0, 0, 0)
    rows = bytearray()
    for y in range(image.height):
        rows.append(0)
        for x in range(image.width):
            for channel in range(samples):
                rows.append(int(_at(image, x, y, channel)) & 0xFF)

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    return (
        _PNG_SIGNATURE
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(rows), 6))
        + chunk(b"IEND", b"")
    )


def _synthesize(data: bytes, width: int, height: int, channels: int) -> list[float]:
    """Return a banded grey image whose phase comes from the file's own bytes."""
    offset = int.from_bytes(data[:4], "big") % (BAND_ROWS * 2)
    values: list[float] = []
    for y in range(height):
        level = INK_LEVEL if ((y + offset) // BAND_ROWS) % 2 == 0 else PAPER_LEVEL
        values.extend([level] * (width * channels))
    return values


class FakeClahe:
    """The equalizer ``createCLAHE`` returns, with the ``apply`` the seam calls."""

    # pylint: disable=too-few-public-methods
    # Reason: the object exists to model the engine's returned handle and nothing else.

    def __init__(self, clip_limit: float, tile_grid_size: tuple[int, int]) -> None:
        """Remember the parameters the caller named.

        Args:
            clip_limit: The clip limit the seam asked for.
            tile_grid_size: The tile grid the seam asked for.
        """
        self.clip_limit = clip_limit
        self.tile_grid_size = tile_grid_size

    def apply(self, image: FakeImage) -> FakeImage:
        """Return the image with its contrast stretched about its mean.

        This is the double's smoothing, not the engine's algorithm: it is a plausible,
        deterministic transformation that keeps the seam's wiring under test.

        Args:
            image: The single-channel image to equalize.

        Returns:
            The stretched image.
        """
        mean = image.mean()
        gain = 1.0 + 0.2 * self.clip_limit
        return _map_image(
            image, lambda x, y, _c: mean + (_at(image, x, y) - mean) * gain
        )


class FakeOpenCV:
    """A plain namespace standing in for ``cv2``, answering entirely in memory."""

    # pylint: disable=too-many-public-methods,too-many-instance-attributes,too-many-locals
    # Reason: the double models the engine surface the seam uses — one attribute per call — and
    # holds the knobs and the call log that make its behaviour observable. The per-pixel
    # samplers are the engine's own arithmetic, which is where its locals come from.
    # pylint: disable=invalid-name,redefined-builtin
    # Reason: the names are the engine's, and a caller has to use them: ``cvtColor``,
    # ``clipLimit`` and ``type`` are keywords of the interface this double stands in for.
    # Renaming them would make it a different interface from the one under test.

    error = FakeCVError
    __version__ = FAKE_ENGINE_VERSION

    IMREAD_GRAYSCALE = 0
    IMREAD_COLOR = 1
    IMWRITE_JPEG_QUALITY = 1
    INTER_LINEAR = 1
    INTER_AREA = 3
    COLOR_BGRA2BGR = 1
    COLOR_BGR2GRAY = 6
    COLOR_GRAY2BGR = 8
    THRESH_BINARY = 0
    THRESH_BINARY_INV = 1
    ADAPTIVE_THRESH_GAUSSIAN_C = 1
    CV_64F = 6
    MORPH_RECT = 0
    MORPH_CLOSE = 3
    RETR_EXTERNAL = 0
    CHAIN_APPROX_SIMPLE = 2
    BORDER_CONSTANT = 0

    def __init__(
        self,
        *,
        undecodable: Iterable[str] = (),
        write_failures: Iterable[str] = (),
        raises: Mapping[str, BaseException] | None = None,
    ) -> None:
        """Build a double with its failure knobs.

        Args:
            undecodable: File names ``imread`` answers ``None`` for.
            write_failures: Destination names ``imwrite`` answers ``False`` for.
            raises: An exception per engine method name, raised instead of answering.
        """
        self.undecodable = set(undecodable)
        self.write_failures = set(write_failures)
        self.raises = dict(raises or {})
        self.calls: list[str] = []
        self.writes: list[tuple[str, list[int]]] = []

    # --- Decode and encode ---------------------------------------------------------

    @_recorded
    def imread(self, path: str, flag: int = IMREAD_COLOR) -> FakeImage | None:
        """Decode ``path``, or answer ``None`` the way the engine does when it cannot."""
        source = Path(path)
        data = source.read_bytes()
        geometry = _png_geometry(data)
        if source.name in self.undecodable or geometry is None:
            return None
        width, height = geometry
        channels = 1 if flag == self.IMREAD_GRAYSCALE else 3
        return FakeImage(
            _synthesize(data, width, height, channels), width, height, channels
        )

    @_recorded
    def imwrite(self, path: str, image: FakeImage, params: Sequence[int] = ()) -> bool:
        """Encode ``image`` at ``path``; answer ``False`` when the store cannot be done.

        The call log and :attr:`write_failures` name the artifact by its final name: the
        temporary sibling the atomic publication writes through is that publication's detail,
        not something a test should have to spell out.
        """
        destination = Path(path)
        artifact = destination.name.removesuffix(TEMP_SUFFIX)
        self.writes.append((artifact, [int(value) for value in params]))
        if artifact in self.write_failures:
            return False
        if not destination.parent.is_dir():
            return False
        destination.write_bytes(_png_bytes(image))
        return True

    # --- Colour and geometry -------------------------------------------------------

    @_recorded
    def cvtColor(self, image: FakeImage, code: int) -> FakeImage:
        """Convert between the layouts the seam asks for."""
        if code == self.COLOR_BGR2GRAY:
            values = [
                0.114 * _at(image, x, y, 0)
                + 0.587 * _at(image, x, y, 1)
                + 0.299 * _at(image, x, y, 2)
                for y in range(image.height)
                for x in range(image.width)
            ]
            return FakeImage(values, image.width, image.height, 1)
        if code == self.COLOR_GRAY2BGR:
            values = [
                _at(image, x, y)
                for y in range(image.height)
                for x in range(image.width)
                for _channel in range(3)
            ]
            return FakeImage(values, image.width, image.height, 3)
        if code == self.COLOR_BGRA2BGR:
            values = [
                _at(image, x, y, channel)
                for y in range(image.height)
                for x in range(image.width)
                for channel in range(3)
            ]
            return FakeImage(values, image.width, image.height, 3)
        raise FakeCVError(f"unsupported conversion code {code}")

    @_recorded
    def resize(
        self,
        image: FakeImage,
        dsize: tuple[int, int],
        interpolation: int = INTER_LINEAR,
    ) -> FakeImage:
        """Resample to ``dsize``, which the engine spells ``(width, height)``."""
        del interpolation
        width, height = dsize
        values = [
            _at(
                image,
                min(image.width - 1, x * image.width // max(1, width)),
                min(image.height - 1, y * image.height // max(1, height)),
                channel,
            )
            for y in range(height)
            for x in range(width)
            for channel in range(image.channels)
        ]
        return FakeImage(values, width, height, image.channels)

    @_recorded
    def getRotationMatrix2D(
        self, center: tuple[float, float], angle: float, scale: float
    ) -> tuple[tuple[float, float], float, float]:
        """Return a rotation the double's ``warpAffine`` understands."""
        return (center, angle, scale)

    @_recorded
    def warpAffine(
        self,
        image: FakeImage,
        matrix: tuple[tuple[float, float], float, float],
        dsize: tuple[int, int],
        **kwargs: Any,
    ) -> FakeImage:
        """Rotate ``image`` about its centre, filling outside with the border value."""
        del kwargs
        width, height = dsize
        (center_x, center_y), angle, scale = matrix
        theta = math.radians(angle)
        cos_t, sin_t = math.cos(theta) * scale, math.sin(theta) * scale
        border = _border_level()

        def sample(x: int, y: int, channel: int) -> float:
            delta_x, delta_y = x - width / 2.0, y - height / 2.0
            source_x = cos_t * delta_x + sin_t * delta_y + center_x
            source_y = -sin_t * delta_x + cos_t * delta_y + center_y
            if not 0 <= source_x < image.width or not 0 <= source_y < image.height:
                return border
            return _at(image, int(source_x), int(source_y), channel)

        values = [
            sample(x, y, channel)
            for y in range(height)
            for x in range(width)
            for channel in range(image.channels)
        ]
        return FakeImage(values, width, height, image.channels)

    # --- Enhancement ---------------------------------------------------------------

    @_recorded
    def createCLAHE(
        self, clipLimit: float = 40.0, tileGridSize: tuple[int, int] = (8, 8)
    ) -> FakeClahe:
        """Return the equalizer handle the seam then applies."""
        return FakeClahe(clipLimit, tileGridSize)

    @_recorded
    def convertScaleAbs(
        self, image: FakeImage, alpha: float = 1.0, beta: float = 0.0
    ) -> FakeImage:
        """Return ``|alpha * image + beta|``, clamped to 8 bits."""
        return _map_image(
            image, lambda x, y, c: abs(alpha * _at(image, x, y, c) + beta)
        )

    @_recorded
    def fastNlMeansDenoising(
        self, image: FakeImage, h: float = 3.0, **kwargs: Any
    ) -> FakeImage:
        """Return the double's smoothing of a single-channel image."""
        del h, kwargs
        return _neighbourhood(image, radius=1, reducer=_mean_of)

    @_recorded
    def GaussianBlur(
        self, image: FakeImage, ksize: tuple[int, int], sigmaX: float = 0.0
    ) -> FakeImage:
        """Return a box-average blur over the requested kernel."""
        del sigmaX
        radius = max(1, (ksize[0] - 1) // 2)
        return _neighbourhood(image, radius=radius, reducer=_mean_of)

    @_recorded
    def medianBlur(self, image: FakeImage, ksize: int) -> FakeImage:
        """Return a median-filtered image."""
        radius = max(1, (ksize - 1) // 2)
        return _neighbourhood(image, radius=radius, reducer=_median_of)

    @_recorded
    def addWeighted(
        self,
        first: FakeImage,
        alpha: float,
        second: FakeImage,
        beta: float,
        gamma: float,
    ) -> FakeImage:
        """Return the element-wise weighted sum of two arrays."""
        values = [
            alpha * left + beta * right + gamma
            for left, right in zip(first.values, second.values, strict=True)
        ]
        return FakeImage(values, first.width, first.height, first.channels)

    @_recorded
    def absdiff(self, first: FakeImage, second: FakeImage) -> FakeImage:
        """Return the element-wise absolute difference."""
        values = [
            abs(left - right)
            for left, right in zip(first.values, second.values, strict=True)
        ]
        return FakeImage(values, first.width, first.height, first.channels)

    @_recorded
    def threshold(
        self, image: FakeImage, thresh: float, maxval: float, type: int
    ) -> tuple[float, FakeImage]:
        """Return the threshold used and the binary image it produced."""
        inverse = type == self.THRESH_BINARY_INV
        values = [
            maxval if (_at(image, x, y) <= thresh) == inverse else 0.0
            for y in range(image.height)
            for x in range(image.width)
        ]
        return thresh, FakeImage(values, image.width, image.height, 1)

    @_recorded
    def adaptiveThreshold(
        self,
        image: FakeImage,
        maxval: float,
        adaptiveMethod: int,
        type: int,  # pylint: disable=redefined-builtin
        blockSize: int,
        C: float,  # pylint: disable=invalid-name  # reason: the engine's own argument name
    ) -> FakeImage:
        """Return a locally thresholded binary image, mean-based and integral-image fast."""
        del adaptiveMethod, type
        radius = max(1, blockSize // 2)
        sums, integral = _integral(image)
        values = []
        for y in range(image.height):
            for x in range(image.width):
                left, right = max(0, x - radius), min(image.width, x + radius + 1)
                top, bottom = max(0, y - radius), min(image.height, y + radius + 1)
                count = (right - left) * (bottom - top)
                mean = _box_sum(sums, integral, left, top, right, bottom) / count
                values.append(maxval if _at(image, x, y) > mean - C else 0.0)
        return FakeImage(values, image.width, image.height, 1)

    @_recorded
    def morphologyEx(
        self, image: FakeImage, op: int, kernel: tuple[int, int]
    ) -> FakeImage:
        """Return a closing (dilate then erode) of a single-channel image."""
        if op != self.MORPH_CLOSE:
            raise FakeCVError(f"unsupported morphology {op}")
        radius = max(1, (kernel[0] - 1) // 2)
        dilated = _neighbourhood(image, radius=radius, reducer=max)
        return _neighbourhood(dilated, radius=radius, reducer=min)

    @_recorded
    def getStructuringElement(
        self, shape: int, ksize: tuple[int, int]
    ) -> tuple[int, int]:
        """Return the kernel description the seam then passes back in."""
        del shape
        return ksize

    # --- Readings ------------------------------------------------------------------

    @_recorded
    def Laplacian(self, image: FakeImage, ddepth: int) -> FakeImage:
        """Return the 4-neighbour Laplacian, whose variance is the blur reading."""
        del ddepth
        return _map_image(
            image,
            lambda x, y, _c: (
                4 * _at(image, x, y)
                - _at(image, x - 1, y)
                - _at(image, x + 1, y)
                - _at(image, x, y - 1)
                - _at(image, x, y + 1)
            ),
        )

    @_recorded
    def Sobel(self, image: FakeImage, ddepth: int, dx: int, dy: int) -> FakeImage:
        """Return a first-order difference in the requested direction."""
        del ddepth
        if dx:
            return _map_image(
                image, lambda x, y, _c: _at(image, x + 1, y) - _at(image, x - 1, y)
            )
        if dy:
            return _map_image(
                image, lambda x, y, _c: _at(image, x, y + 1) - _at(image, x, y - 1)
            )
        raise FakeCVError("Sobel needs a direction")

    @_recorded
    def countNonZero(self, image: FakeImage) -> int:
        """Return how many stored values are non-zero."""
        return sum(1 for value in image.values if value != 0.0)

    @_recorded
    def findNonZero(self, image: FakeImage) -> list[tuple[int, int]]:
        """Return the coordinates of the non-zero pixels, in row order."""
        return [
            (x, y)
            for y in range(image.height)
            for x in range(image.width)
            if _at(image, x, y) != 0.0
        ]

    @_recorded
    def boundingRect(self, points: Any) -> tuple[int, int, int, int]:
        """Return the bounding box of a contour or of a point set."""
        if isinstance(points, tuple) and len(points) == 4:
            return tuple(int(value) for value in points)  # type: ignore[return-value]
        return _box_of(points)

    @_recorded
    def minAreaRect(
        self, points: Any
    ) -> tuple[tuple[float, float], tuple[int, int], float]:
        """Return the smallest box around ``points`` and its angle, in the engine's range."""
        left, top, width, height = _box_of(points)
        return (
            (left + width / 2.0, top + height / 2.0),
            (width, height),
            _principal_angle(points),
        )

    @_recorded
    def findContours(
        self,
        image: FakeImage,
        mode: int = RETR_EXTERNAL,
        method: int = CHAIN_APPROX_SIMPLE,
    ) -> tuple[list[tuple[int, int, int, int]], None]:
        """Return one box per connected run of ink, as contours and no hierarchy."""
        del mode, method
        return _contours(image), None


def _border_level() -> float:
    """Return the level the border fill is read as — the double's white page."""
    return MAX_LEVEL


def _mean_of(values: Sequence[float]) -> float:
    """Return the mean of a window."""
    return sum(values) / len(values)


def _median_of(values: Sequence[float]) -> float:
    """Return the median of a window."""
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def _neighbourhood(
    image: FakeImage, *, radius: int, reducer: Callable[[Sequence[float]], float]
) -> FakeImage:
    """Return an image whose every pixel is ``reducer`` over its square window."""
    values = [
        reducer(_window_values(image, x, y, radius))
        for y in range(image.height)
        for x in range(image.width)
    ]
    return FakeImage(values, image.width, image.height, 1)


def _integral(image: FakeImage) -> tuple[list[float], int]:
    """Return a summed-area table of a single-channel image and its row width."""
    width = image.width
    sums = [0.0] * ((image.height + 1) * (width + 1))
    for y in range(image.height):
        for x in range(width):
            sums[(y + 1) * (width + 1) + x + 1] = (
                _at(image, x, y)
                + sums[y * (width + 1) + x + 1]
                + sums[(y + 1) * (width + 1) + x]
                - sums[y * (width + 1) + x]
            )
    return sums, width + 1


def _box_sum(
    sums: list[float], stride: int, left: int, top: int, right: int, bottom: int
) -> float:
    """Return the sum of a rectangle out of a summed-area table."""
    return (
        sums[bottom * stride + right]
        - sums[top * stride + right]
        - sums[bottom * stride + left]
        + sums[top * stride + left]
    )


def _box_of(points: Any) -> tuple[int, int, int, int]:
    """Return the bounding box of a sequence of ``(x, y)`` pairs."""
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return (min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1)


def _principal_angle(points: Any) -> float:
    """Return the point cloud's principal-axis angle, folded into the engine's ``0..90``."""
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    mean_x, mean_y = sum(xs) / len(xs), sum(ys) / len(ys)
    covariance_xx = sum((x - mean_x) ** 2 for x in xs)
    covariance_xy = sum(
        (x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)
    )
    angle = math.degrees(math.atan2(covariance_xy, covariance_xx)) % 90.0
    return angle


def _contours(image: FakeImage) -> list[tuple[int, int, int, int]]:
    """Return one bounding box per connected group of non-zero pixels."""
    open_runs: list[list[int]] = []
    boxes: list[tuple[int, int, int, int]] = []
    for y in range(image.height):
        row = [x for x in range(image.width) if _at(image, x, y) != 0.0]
        runs: list[list[int]] = []
        for x in row:
            attached = None
            for run in open_runs:
                if run[0] - 1 <= x <= run[1] + 1:
                    attached = run
                    break
            if attached is None:
                attached = [x, x, y, y]
                open_runs.append(attached)
            else:
                attached[0] = min(attached[0], x)
                attached[1] = max(attached[1], x)
                attached[3] = y
            if attached not in runs:
                runs.append(attached)
        for run in list(open_runs):
            if run not in runs:
                open_runs.remove(run)
                boxes.append((run[0], run[2], run[1] - run[0] + 1, run[3] - run[2] + 1))
    for run in open_runs:
        boxes.append((run[0], run[2], run[1] - run[0] + 1, run[3] - run[2] + 1))
    return boxes
