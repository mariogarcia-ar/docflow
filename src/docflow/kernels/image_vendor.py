"""The seam between K3's decisions and the raster library that moves the pixels.

K3 is split in two, and this module is the split. It declares **what the decisions
need from a raster library**, with no library named and nothing implemented:

- the **value types** a library produces — an opaque frame plus the facts the kernel
  may read about it;
- the **`RasterVendor` protocol** the kernel asks through;
- the **typed failure** a library raises instead of a traceback.

`docflow/kernels/image.py` holds the decisions — whether a bitmap is legible against
the caller's threshold, whether a rescale is reachable, what a crop's inverse map is,
which orientation was found and whether it was applied — and imports no imaging
library at all. `docflow/adapters/image.py` holds the implementation over Pillow.

Why the seam is here rather than in `ports/`
--------------------------------------------

`plans/README.md` §3 freezes **five** port interfaces, and `docflow/ports/` holds
exactly those five; `tests/ports/test_ports.py` asserts `RasterImage` is absent, for
the reason that module states: a raster library is the one engine in the inventory
that is not a vendor service behind a swap-able boundary, so a sixth interface would
put a boundary where the architecture did not ask for one.

That is a statement about **which engine answers**, and it does not mean the imaging
library belongs *inside* the kernel. `sad.md` §1 requires every kernel to be usable
without its engine installed, and a module holding `from PIL import …` is not. So this
is an **inner seam**, and its direction is the mirror image of a port's:

```text
ports/            (no K3 port — frozen at five, deliberately)
      ^
adapters/image.py   RasterEngine     the four operations; owns Pillow
      |
      v  calls
kernels/image.py    the decisions     thresholds, refusals, inverse map; no Pillow
      |
      v  asks through
kernels/image_vendor.py  RasterVendor   the seam the decisions declare
      ^
adapters/image.py   PillowVendor     the implementation over Pillow
```

The consumer declares the interface and the implementer satisfies it — the same
inversion `PdfSource` uses one level up, and the same one `PdfVendor` uses beside it.
The dependency arrow keeps pointing down: the adapter imports the kernel, never the
reverse.

Primitives, not answers
-----------------------

Everything here is a **primitive**: decode, rotate, convolve, take statistics, resize,
crop, encode. None of them names a verdict, a threshold or a reason.

That is what keeps the decisions in the kernel. `legibility` compares a sharpness
number against the caller's value, and `rescale` refuses an unreachable target — both
of those are judgements about *what the measurement means*, and neither is here. What
is here is how a Laplacian gets convolved and how a standard deviation gets taken,
which is a fact about the library rather than about the document.

A vendor that cannot serve a call raises :class:`RasterVendorError` carrying a
``Reason`` from the closed set of `kernel-cli.md` §5 rather than returning a stand-in.
There is no default implementation here and no module-level instance: an unbound seam
is a typed ``engine_unavailable``, never a substitute engine.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

from docflow.kernels.vendor_refusal import VendorRefusal

__all__: list[str] = [
    "EXIF_ORIENTATION_TAG",
    "EXIF_UPRIGHT",
    "ImageMeta",
    "RasterFrame",
    "RasterStats",
    "RasterVendor",
    "RasterVendorError",
]

#: The EXIF tag that carries the orientation. It is a tag number and not a name
#: because that is what the format defines. It lives here rather than in either side
#: of the seam because both need it and must agree: the implementation reads it, and
#: the kernel reports which tag it read.
EXIF_ORIENTATION_TAG: int = 274

#: The orientation that means *already upright*. Applying it is a no-op, and every
#: other value means the pixels have to move. The kernel compares against it, so it
#: is a fact about EXIF rather than about a library.
EXIF_UPRIGHT: int = 1


@dataclasses.dataclass(frozen=True, slots=True)
class RasterFrame:
    """One decoded frame, with the facts about it the kernel may read.

    The ``handle`` is opaque and belongs to the implementation: the kernel passes it
    back to the vendor for the next operation and never inspects it. What the kernel
    *can* read is here, so a decision never has to ask the library a question through
    a call that could fail.

    Attributes:
        handle: The implementation's own object. Opaque to the kernel.
        width: Frame width in pixels.
        height: Frame height in pixels.
        mode: The implementation's colour model, as it reports it. The kernel
            carries it as an observation and never compares it to a literal — the
            one place that needs a single channel asks for
            :meth:`RasterVendor.greyscale` instead.

    """

    handle: object
    width: int
    height: int
    mode: str

    @property
    def size(self) -> tuple[int, int]:
        """Report the frame's ``(width, height)`` pair.

        Returns:
            The size, in pixels.

        """
        return self.width, self.height


@dataclasses.dataclass(frozen=True, slots=True)
class ImageMeta:
    """What a file declares about itself, before any pixels are touched.

    Attributes:
        format: The container format the library recognised, e.g. ``"JPEG"``. It is
            reported, never used to decide anything.
        exif_orientation: The EXIF orientation tag's value, or ``None`` when the
            file declares none. **Unapplied**: the value describes how the stored
            pixels are arranged, and the kernel is what decides whether to move them.

    """

    format: str
    exif_orientation: int | None


@dataclasses.dataclass(frozen=True, slots=True)
class RasterStats:
    """The two distribution numbers the measurements are built from.

    Both, rather than one, because the kernel's two measurements need different ones:
    sharpness is a **variance** of a convolved frame and contrast is a **standard
    deviation** of the frame itself. Returning a pair keeps that distinction in the
    kernel, where it is a fact about what is being measured, rather than in the
    library, where it would be an accident of which call was made.

    Attributes:
        stddev: The standard deviation over the frame's single channel.
        variance: The variance over the convolved frame's single channel.

    """

    stddev: float
    variance: float


class RasterVendorError(VendorRefusal):
    """A raster library that cannot serve a call, carrying the ``Reason`` why.

    Subclasses :class:`~docflow.kernels.vendor_refusal.VendorRefusal`, which
    carries the constructor and the two attributes a caller reads: ``reason``
    and the evidence taken before the refusal.
    """


@runtime_checkable
class RasterVendor(Protocol):
    """What K3's decisions need from the library that moves the pixels.

    Implemented by `docflow/adapters/image.py`. Every method either answers the
    primitive asked for or raises :class:`RasterVendorError`; none of them returns a
    stand-in, and none of them decides anything a threshold would settle.
    """

    def decode(self, path: Path) -> tuple[RasterFrame, ImageMeta]:
        """Decode a file into a frame, without applying its orientation.

        The orientation is **not** applied here. The kernel reports the tag before it
        is consumed, and an implementation that rotated during decode would make *the
        rotation that was found* unobservable — which is the report row 6 depends on.

        Args:
            path: The image to decode.

        Returns:
            The decoded frame and what the file declares about itself.

        Raises:
            RasterVendorError: When the file is absent or the bytes are not a format
                the library accepts.

        """

    def upright(self, frame: RasterFrame) -> RasterFrame:
        """Apply the frame's declared orientation.

        Args:
            frame: The frame to rotate.

        Returns:
            The rotated frame. A frame that declared nothing, or declared *already
            upright*, comes back unchanged.

        Raises:
            RasterVendorError: When the rotation cannot be performed.

        """

    def greyscale(self, frame: RasterFrame) -> RasterFrame:
        """Reduce the frame to the single channel the measurements are taken in.

        The kernel asks for *a single channel* rather than naming one, because the
        name of that channel is the library's vocabulary. Legibility is a property of
        brightness structure, not of colour, and this is how it gets one.

        Args:
            frame: The frame to reduce.

        Returns:
            A single-channel frame.

        Raises:
            RasterVendorError: When the conversion cannot be performed.

        """

    def convolved(
        self, frame: RasterFrame, matrix: Sequence[float], size: tuple[int, int]
    ) -> RasterFrame:
        """Convolve the frame with a matrix.

        The kernel supplies the matrix. That is the whole distinction this seam is
        built on: *which* kernel defines a sharpness measurement is a decision, and
        *how* a convolution is applied is a fact about the library.

        Args:
            frame: The frame to convolve.
            matrix: The convolution matrix, row-major, with ``size`` entries.
            size: The matrix's ``(width, height)``.

        Returns:
            The convolved frame.

        Raises:
            RasterVendorError: When the convolution cannot be applied.

        """

    def statistics(self, frame: RasterFrame) -> RasterStats:
        """Take the distribution numbers over the frame's single channel.

        Args:
            frame: A single-channel frame.

        Returns:
            The standard deviation and the variance.

        Raises:
            RasterVendorError: When the frame carries more than one channel, or the
                statistics cannot be taken.

        """

    def rotated(self, frame: RasterFrame, angle: float, fill: int) -> RasterFrame:
        """Rotate the frame about its centre, without expanding it.

        Args:
            frame: The frame to rotate.
            angle: The rotation, in degrees, clockwise.
            fill: The value used where the rotation exposes new pixels.

        Returns:
            The rotated frame, the same size as the input.

        Raises:
            RasterVendorError: When the rotation cannot be performed.

        """

    def resized(
        self, frame: RasterFrame, size: tuple[int, int], *, smooth: bool
    ) -> RasterFrame:
        """Resample the frame to an exact size.

        Args:
            frame: The frame to resample.
            size: The ``(width, height)`` to reach, already computed by the caller.
            smooth: Whether to use the library's higher-quality resampling. The
                kernel asks for it when the result is the *product* and omits it
                when the result is only ever measured, which is a choice about what
                the pixels are for rather than about which algorithm.

        Returns:
            The resampled frame.

        Raises:
            RasterVendorError: When the resample cannot be performed.

        """

    def cropped(
        self, frame: RasterFrame, box: tuple[int, int, int, int]
    ) -> RasterFrame:
        """Cut a ``(left, top, right, bottom)`` rectangle out of the frame.

        Args:
            frame: The frame to cut.
            box: The rectangle, in the frame's own pixel coordinates.

        Returns:
            The cropped frame.

        Raises:
            RasterVendorError: When the rectangle is outside the frame.

        """

    def encoded_png(self, frame: RasterFrame) -> bytes:
        """Encode the frame as PNG.

        PNG because it is lossless: a rescaled or cropped page must not acquire JPEG
        artefacts on its way to OCR. The kernel names the media type it wants; which
        encoder produces it is the library's business.

        Args:
            frame: The frame to encode.

        Returns:
            The encoded buffer.

        Raises:
            RasterVendorError: When the frame cannot be encoded.

        """

    def engine_terms(self) -> Mapping[str, str]:
        """Report the library's identity, as cache-key terms.

        Returns:
            The engine's name and version. The version is a key term because the same
            call against a different library build is different work (`sad.md` §5).

        Raises:
            RasterVendorError: When the library is not installed.

        """
