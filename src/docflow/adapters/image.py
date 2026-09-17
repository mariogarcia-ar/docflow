"""K3's raster adapter over **Pillow**, and the four operations behind it.

The one place in the image path where an imaging library is named. Two things live
here and nothing else does:

- :class:`PillowVendor`, which satisfies `docflow/kernels/image_vendor.py` — it moves
  pixels and returns primitives, and it names ``PIL`` for the whole system.
- :class:`RasterEngine`, which exposes K3's four operations by delegating the
  *decisions* to `docflow/kernels/image.py` and the *pixels* to the vendor above.

Why there are two objects rather than one
------------------------------------------

The split is the architecture's, not this file's preference. `sad.md` §1 requires
every kernel to be usable without its engine installed, and `docflow/kernels/image.py`
used to hold `from PIL import …` in four places — an engine inside a kernel.

The decisions on top of the pixels are *not* library work: whether a bitmap is legible
against the caller's threshold, whether a rescale target is reachable, what a crop's
inverse map is, which orientation was found and whether it was applied. Those are
judgements with tests against them and no library in them.

So the library moved down and the decisions stayed:

```text
RasterEngine                this file — the four operations a caller uses
      |
      +-- kernels/image.py            decisions: thresholds, refusals, inverse map
      |         |
      |         +-- RasterVendor        the seam (kernels/image_vendor.py)
      |
      +-- PillowVendor                pixels: decode, rotate, convolve  <- PIL
```
**There is no port here, and that is deliberate.** `plans/README.md` §3 freezes five
port interfaces and a raster library is not a vendor service behind a swap-able
boundary, so a sixth interface would put a boundary where the architecture did not ask
for one. What lives here is the mirror image of a port — an *inner* seam — and its
point is testability and replaceability of the library, not engine selection.

The threshold is a parameter, never a setting
----------------------------------------------

`legibility` takes the value to compare against as a required argument, and there is no
default anywhere in this file. `rescale` takes the source resolution as a parameter
because ``Box`` carries no DPI and an invented one would be a number nobody measured.
Neither is a setting: a threshold here would be a routing decision taken by whichever
layer happened to be constructed first (`prd.md` FR-15, `ADR-009`).

PoC stage
---------

Each deliberate shortcut carries a marker naming what must replace it. One is
structural: ``load`` decodes fully in memory rather than streaming.
"""

from __future__ import annotations

import io
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from docflow.kernels import image as decisions
from docflow.kernels.image_vendor import (
    EXIF_ORIENTATION_TAG,
    ImageMeta,
    RasterFrame,
    RasterStats,
    RasterVendorError,
)
from docflow.kernels.types import Box, Bytes, Evidence, KernelResult, Reason

# Pylint reports `duplicate-code` against `adapters/pdf.py`: both translate an
# optional-library import into the same typed reason, word for word. That is the
# contract rather than a copy — the code and its message are what a caller reads —
# and the alternative is a shared helper that a kernel would import from an adapter's
# internals.
# pylint: disable=duplicate-code

__all__: list[str] = ["PillowVendor", "RasterEngine"]

# --- Reason codes, from the closed set of `kernel-cli.md` §5 -----------------

_CODE_ENGINE_UNAVAILABLE: Final[str] = "engine_unavailable"

#: The library this adapter speaks to. Named once, here.
_ENGINE_PACKAGE: Final[str] = "PIL"

#: PNG, because it is lossless: a rescaled or cropped page must not acquire JPEG
#: artefacts on its way to OCR.
_MEDIA_TYPE: Final[str] = "image/png"


class PillowVendor:
    """A :class:`~docflow.kernels.image_vendor.RasterVendor` over Pillow.

    Constructed with no settings: every value it uses arrives as a parameter from the
    decisions above it, which is what keeps a threshold from having anywhere to hide
    here.
    """

    # --- Library access -----------------------------------------------------

    @staticmethod
    def engine() -> Any:
        """Return the ``PIL.Image`` module, importing it on first use.

        The import is inside the function by design: ``pyproject.toml`` declares no
        runtime dependency, so importing this module must not require the library, and
        a missing one must arrive as a typed ``Reason`` rather than as an
        ``ImportError`` raised at import time.

        Returns:
            The ``PIL.Image`` module.

        Raises:
            RasterVendorError: When the library is not installed.

        """
        try:
            from PIL import Image  # pylint: disable=import-outside-toplevel
        except ImportError as exc:
            raise RasterVendorError(
                Reason(
                    code=_CODE_ENGINE_UNAVAILABLE,
                    message=(
                        f"the {_ENGINE_PACKAGE!r} library is not installed, so "
                        "images cannot be decoded. Install it "
                        "(`pip install pillow`); no substitute engine is used, "
                        "because a different decoder reading the same bytes is a "
                        "different measurement reported as this one."
                    ),
                )
            ) from exc

        return Image

    # --- The seam -----------------------------------------------------------

    def decode(self, path: Path) -> tuple[RasterFrame, ImageMeta]:
        """Decode a file into a frame, without applying its orientation.

        Args:
            path: The image to decode.

        Returns:
            The frame and what the file declares about itself.

        Raises:
            RasterVendorError: When the file is absent or is not a decodable image.

        """
        engine = self.engine()

        if not path.exists():
            raise RasterVendorError(
                Reason(
                    code=decisions.CODE_UNSUPPORTED_FORMAT,
                    message=f"{path.name!r} does not exist at {path}",
                )
            )

        try:
            opened = engine.open(path)
            opened.load()
        except Exception as exc:  # pylint: disable=broad-exception-caught
            # Broad because Pillow raises several unrelated types from `open`
            # depending on how a file is malformed, and the two outcomes that matter
            # are "it decodes" and "it does not".
            raise RasterVendorError(
                Reason(
                    code=decisions.CODE_UNSUPPORTED_FORMAT,
                    message=(
                        f"{path.name!r} could not be decoded as an image: "
                        f"{type(exc).__name__}: {exc}"
                    ),
                )
            ) from exc

        orientation = self._orientation_of(opened)

        return (
            RasterFrame(
                handle=opened,
                width=int(opened.width),
                height=int(opened.height),
                mode=str(opened.mode),
            ),
            ImageMeta(
                format=str(opened.format or "unknown"),
                exif_orientation=orientation,
            ),
        )

    @staticmethod
    def _orientation_of(image: Any) -> int | None:
        """Read the EXIF orientation tag, or report that the file declares none.

        Args:
            image: The decoded image.

        Returns:
            The tag's value, or ``None``. An unreadable EXIF block means *no declared
            orientation*, which is a valid observation — and the alternative, failing
            the whole decode over optional metadata, would reject images that are
            perfectly readable.

        """
        try:
            raw = image.getexif().get(EXIF_ORIENTATION_TAG)
            if raw is not None:
                return int(raw)
        except Exception:  # pylint: disable=broad-exception-caught
            return None

        return None

    def upright(self, frame: RasterFrame) -> RasterFrame:
        """Apply the frame's declared orientation.

        ``ImageOps.exif_transpose`` both reads the tag and performs the rotation, which
        is what makes a sideways photo unrepresentable in the frame that comes back.

        Args:
            frame: The frame to rotate.

        Returns:
            The rotated frame, or the same frame when nothing needed moving.

        Raises:
            RasterVendorError: When the rotation cannot be performed.

        """
        try:
            from PIL import ImageOps  # pylint: disable=import-outside-toplevel

            rotated = ImageOps.exif_transpose(frame.handle) or frame.handle
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise RasterVendorError(
                Reason(
                    code=_CODE_ENGINE_UNAVAILABLE,
                    message=(
                        "the declared orientation could not be applied: "
                        f"{type(exc).__name__}: {exc}"
                    ),
                )
            ) from exc

        return self._frame(rotated)

    def greyscale(self, frame: RasterFrame) -> RasterFrame:
        """Reduce the frame to one channel.

        Args:
            frame: The frame to reduce.

        Returns:
            A single-channel frame.

        Raises:
            RasterVendorError: When the conversion cannot be performed.

        """
        try:
            converted = frame.handle.convert("L")
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise RasterVendorError(
                Reason(
                    code=_CODE_ENGINE_UNAVAILABLE,
                    message=(
                        f"the frame could not be reduced to one channel: "
                        f"{type(exc).__name__}: {exc}"
                    ),
                )
            ) from exc

        return self._frame(converted)

    def convolved(
        self, frame: RasterFrame, matrix: Sequence[float], size: tuple[int, int]
    ) -> RasterFrame:
        """Convolve the frame with the kernel's matrix.

        Args:
            frame: The frame to convolve.
            matrix: The matrix, row-major.
            size: The matrix's ``(width, height)``.

        Returns:
            The convolved frame.

        Raises:
            RasterVendorError: When the convolution cannot be applied.

        """
        try:
            from PIL import ImageFilter  # pylint: disable=import-outside-toplevel

            kernel = ImageFilter.Kernel(size, list(matrix), scale=1, offset=0)
            filtered = frame.handle.filter(kernel)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise RasterVendorError(
                Reason(
                    code=_CODE_ENGINE_UNAVAILABLE,
                    message=(
                        f"the frame could not be convolved: {type(exc).__name__}: {exc}"
                    ),
                )
            ) from exc

        return self._frame(filtered)

    def statistics(self, frame: RasterFrame) -> RasterStats:
        """Take the standard deviation and variance over one channel.

        Args:
            frame: A single-channel frame.

        Returns:
            The two distribution numbers.

        Raises:
            RasterVendorError: When the statistics cannot be taken.

        """
        try:
            from PIL import ImageStat  # pylint: disable=import-outside-toplevel

            stats = ImageStat.Stat(frame.handle)
            deviation = float(stats.stddev[0])
            variance = float(stats.var[0])
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise RasterVendorError(
                Reason(
                    code=_CODE_ENGINE_UNAVAILABLE,
                    message=(
                        "statistics could not be taken over the frame: "
                        f"{type(exc).__name__}: {exc}"
                    ),
                )
            ) from exc

        return RasterStats(stddev=deviation, variance=variance)

    def rotated(self, frame: RasterFrame, angle: float, fill: int) -> RasterFrame:
        """Rotate the frame about its centre, without expanding it.

        Args:
            frame: The frame to rotate.
            angle: The rotation, in degrees.
            fill: The value used where the rotation exposes new pixels.

        Returns:
            The rotated frame.

        Raises:
            RasterVendorError: When the rotation cannot be performed.

        """
        try:
            engine = self.engine()
            turned = frame.handle.rotate(
                angle,
                resample=engine.Resampling.BILINEAR,
                expand=False,
                fillcolor=fill,
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise RasterVendorError(
                Reason(
                    code=_CODE_ENGINE_UNAVAILABLE,
                    message=(
                        f"the frame could not be rotated: {type(exc).__name__}: {exc}"
                    ),
                )
            ) from exc

        return self._frame(turned)

    def resized(
        self, frame: RasterFrame, size: tuple[int, int], *, smooth: bool
    ) -> RasterFrame:
        """Resample the frame to an exact size.

        Args:
            frame: The frame to resample.
            size: The ``(width, height)`` to reach.
            smooth: Whether to use the higher-quality filter. ``True`` for a result
                that is the product, ``False`` for one that is only ever measured.

        Returns:
            The resampled frame.

        Raises:
            RasterVendorError: When the resample cannot be performed.

        """
        try:
            engine = self.engine()
            resample = (
                engine.Resampling.LANCZOS if smooth else engine.Resampling.BILINEAR
            )
            scaled = frame.handle.resize(size, resample=resample)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise RasterVendorError(
                Reason(
                    code=_CODE_ENGINE_UNAVAILABLE,
                    message=(
                        f"the frame could not be resampled: {type(exc).__name__}: {exc}"
                    ),
                )
            ) from exc

        return self._frame(scaled)

    def cropped(
        self, frame: RasterFrame, box: tuple[int, int, int, int]
    ) -> RasterFrame:
        """Cut a rectangle out of the frame.

        Args:
            frame: The frame to cut.
            box: The ``(left, top, right, bottom)`` rectangle, in frame pixels.

        Returns:
            The cropped frame.

        Raises:
            RasterVendorError: When the rectangle is outside the frame.

        """
        try:
            cut = frame.handle.crop(box)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise RasterVendorError(
                Reason(
                    code=_CODE_ENGINE_UNAVAILABLE,
                    message=(
                        f"the region could not be cut: {type(exc).__name__}: {exc}"
                    ),
                )
            ) from exc

        return self._frame(cut)

    def encoded_png(self, frame: RasterFrame) -> bytes:
        """Encode the frame as PNG.

        Args:
            frame: The frame to encode.

        Returns:
            The encoded buffer.

        Raises:
            RasterVendorError: When the frame cannot be encoded.

        """
        buffer = io.BytesIO()
        try:
            target = (
                frame.handle
                if frame.mode in {"RGB", "RGBA", "L"}
                else frame.handle.convert("RGB")
            )
            target.save(buffer, format="PNG", optimize=True)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise RasterVendorError(
                Reason(
                    code=_CODE_ENGINE_UNAVAILABLE,
                    message=(
                        f"the frame could not be encoded as PNG: "
                        f"{type(exc).__name__}: {exc}"
                    ),
                )
            ) from exc

        return buffer.getvalue()

    def engine_terms(self) -> Mapping[str, str]:
        """Report Pillow's identity, as cache-key terms.

        Returns:
            The engine's name and version.

        Raises:
            RasterVendorError: When the library is not installed.

        """
        # The version is read off the module the seam already resolves, so there is
        # one access path to the library and a missing one arrives as the same typed
        # refusal everywhere.
        engine = self.engine()
        version = str(getattr(engine, "__version__", "unknown"))

        return MappingProxyType(
            {
                "engine": _ENGINE_PACKAGE,
                "engine_version": version,
            }
        )

    @staticmethod
    def _frame(handle: Any) -> RasterFrame:
        """Wrap a library object as a frame.

        Args:
            handle: The library's own object.

        Returns:
            The frame, with the dimensions the library reports.

        """
        return RasterFrame(
            handle=handle,
            width=int(handle.width),
            height=int(handle.height),
            mode=str(handle.mode),
        )


class RasterEngine:
    """K3's four operations, over a vendor and the kernel's decisions.

    Not a port implementation: K3 has no port, deliberately (see this module's
    docstring). This is the surface a caller uses.
    """

    def __init__(self, *, vendor: Any = None) -> None:
        """Initialise the adapter.

        Args:
            vendor: The raster implementation to use instead of building one. It
                exists so the tests can exercise the boundary without the library,
                and so a caller can supply a configured one. ``None`` means *build the
                documented vendor*; it never means *use a substitute engine*.

        """
        self._vendor = vendor if vendor is not None else PillowVendor()

    @property
    def vendor(self) -> Any:
        """Report the raster implementation in use.

        Returns:
            The vendor, so a caller can hold the same one across engines.

        """
        return self._vendor

    # --- Operations ---------------------------------------------------------

    def load(self, path: Path) -> KernelResult[Bytes]:
        """Load a bitmap, with its declared orientation already applied.

        Args:
            path: The image to load.

        Returns:
            The decoded and rotated bitmap as PNG bytes, or no value and a typed
            ``Reason``.

        """
        return decisions.load(path, vendor=self._vendor)

    def info(self, path: Path) -> KernelResult[Evidence]:
        """Report what the image is, including the orientation that was applied.

        Args:
            path: The image to inspect.

        Returns:
            The dimensions, the colour model, and both halves of the orientation
            observation.

        """
        return decisions.info(path, vendor=self._vendor)

    def legibility(self, path: Path, threshold: float) -> KernelResult[Evidence]:
        """Measure how legible an image is, against the caller's threshold.

        Args:
            path: The image to measure.
            threshold: The caller's minimum acceptable sharpness. Required, with no
                default: the value to compare against is policy (`prd.md` FR-15).

        Returns:
            The measurements, or no value and an ``illegible`` reason **with the same
            measurements attached**.

        """
        return decisions.legibility(path, threshold, vendor=self._vendor)

    def rescale(
        self, path: Path, target_dpi: int, source_dpi: int
    ) -> KernelResult[Bytes]:
        """Rescale an image to a target resolution, never enlarging past the source.

        Args:
            path: The image to rescale.
            target_dpi: The resolution the caller wants.
            source_dpi: The resolution the pixels already hold. A parameter because
                ``Box`` carries no DPI, and an invented one would be a number nobody
                measured.

        Returns:
            The rescaled bitmap with the target it honoured, or no value and a typed
            ``Reason``.

        """
        return decisions.rescale(path, target_dpi, source_dpi, vendor=self._vendor)

    def crop(self, path: Path, region: Box) -> KernelResult[Evidence]:
        """Cut a region out of an image and map its coordinates back to the source.

        Args:
            path: The image to crop.
            region: The region in **source page coordinates**.

        Returns:
            The crop's bytes and its inverse map, or no value and a typed ``Reason``.

        """
        return decisions.crop(path, region, vendor=self._vendor)
