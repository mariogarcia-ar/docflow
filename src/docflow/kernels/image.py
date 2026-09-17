"""K3 ``kernel.image`` — load with EXIF applied, legibility, rescale, crop.

The image kernel, thin and deterministic (`sad.md` §3, `E04-03` / ``S1-T13``). One
engine sits behind it: **Pillow**, for decoding, rotating, measuring and encoding.

Three silent failures live here, and all three are failures of *honesty about what
was observed* rather than failures of computation.

**A photo read sideways loses a whole page and reports no error.** A bitmap carries
no field saying which way is up, so the orientation has to be found in EXIF and
**applied** before the bytes leave this module. More subtly, the rotation has to be
*reported*: a rotation nobody recorded is indistinguishable from an image that
needed none, which is why ``info`` separates the tag that was found from the fact
that it was applied.

**A blurred bitmap reaching OCR produces invented text.** Legibility therefore comes
back as a **measurement plus a reason**, never as a bare boolean — a boolean is a
decision, and the decision belongs to the caller comparing the measurement against
its own policy value (`kernel-cli.md` §3, guardrail 2).

**A crop whose local coordinates are reported as page coordinates points the trace
at the wrong pixels while remaining valid JSON**, so nothing else notices. The
inverse map is what closes it, and it travels *with* the cropped bytes rather than
being a step the caller is trusted to remember. This is `NFR-07`.

What this module never does
---------------------------

- **No threshold constant.** ``legibility`` takes the value to compare against as a
  required parameter. What counts as illegible is the *caller's* policy
  (`prd.md` FR-15), and a kernel holding its own constant has made a routing
  decision whether or not it prints one.
- **No quality or confidence score.** A number that aggregates measurements is a
  decision wearing a number's clothes. **Never** (`kernel-cli.md` §3).
- **No decision.** The kernel reports the measurement and, when it falls below the
  caller's value, why. Whether that means *route to OCR* is Diagnosis's call at
  Stage 2 (`S2-T04`).
- **No deskew, denoise, binarize, auto-contrast, phash or tile.** Documented
  targets, not Stage 1 scope (``# TODO: [MVP]``).
- **No upscale reported as satisfied.** **Never** (`kernel-cli.md` §14).
- **No domain noun.** **Never** (`kernel-cli.md` §10).

PoC stage
---------

Every deliberate shortcut carries a marker naming what must replace it. Two are
worth stating up front: ``load`` decodes fully in memory rather than streaming, and
``rescale`` takes the source resolution as a parameter because ``Box`` carries no
DPI and the kernel must not invent one.
"""

from __future__ import annotations

import dataclasses
import io
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from docflow.kernels.types import Box, Bytes, Evidence, KernelResult, Reason

# Pylint sees the decode-refusal shape below as a duplicate of the one in
# `docflow/kernels/pdf.py`. It is: both kernels translate an engine's opaque
# failure into the same typed reason, because that is the contract. Sharing a
# helper would mean one kernel importing the other's internals or a third module
# both depend on, for six lines — and the two will diverge as the engines' failure
# modes are understood better.
# pylint: disable=duplicate-code

__all__: list[str] = [
    "InverseMap",
    "crop",
    "info",
    "legibility",
    "load",
    "rescale",
]

# --- Reason codes, from the closed set of `kernel-cli.md` §5 -----------------

_CODE_ILLEGIBLE: Final[str] = "illegible"
_CODE_UNSUPPORTED_FORMAT: Final[str] = "unsupported_format"
_CODE_ENGINE_UNAVAILABLE: Final[str] = "engine_unavailable"
#: The requested resolution exceeds what the source pixels hold. The same
#: condition K2's ``render`` refuses on, and deliberately the same word: a caller
#: matching on the code must not have to know which kernel declined.
_CODE_INSUFFICIENT_RESOLUTION: Final[str] = "insufficient_effective_resolution"

# --- Engine identity ---------------------------------------------------------

#: The raster engine. Imported lazily so this module imports without it, and a
#: missing library becomes a typed ``Reason`` rather than an `ImportError` raised
#: at import time.
_ENGINE_PACKAGE: Final[str] = "PIL"

#: The EXIF tag that carries the orientation. It is a tag number and not a name
#: because that is what the format defines.
_EXIF_ORIENTATION_TAG: Final[int] = 274

#: The orientation that means *already upright*. Applying it is a no-op, and every
#: other value means the pixels have to move.
_EXIF_UPRIGHT: Final[int] = 1

#: PNG, because it is lossless: a rescaled or cropped page must not acquire JPEG
#: artefacts on its way to OCR.
_MEDIA_TYPE: Final[str] = "image/png"

#: The luminance mode the measurements are taken in. Legibility is a property of
#: brightness structure, not of colour.
_LUMINANCE: Final[str] = "L"

#: The discrete Laplacian: the second-derivative kernel whose variance is the
#: standard sharpness measure. Edges produce a large response; a blurred image
#: produces almost none.
_LAPLACIAN_KERNEL: Final[tuple[float, ...]] = (
    0.0,
    1.0,
    0.0,
    1.0,
    -4.0,
    1.0,
    0.0,
    1.0,
    0.0,
)
_LAPLACIAN_SIZE: Final[tuple[int, int]] = (3, 3)

#: The full scale of an 8-bit channel, for normalizing contrast into [0, 1].
_CHANNEL_MAXIMUM: Final[float] = 255.0

#: The skew search: a bounded sweep in degrees, because a document photographed at
#: a plausible angle is inside this range and an unbounded search would cost more
#: than the answer is worth.
_SKEW_RANGE_DEGREES: Final[float] = 5.0
_SKEW_STEP_DEGREES: Final[float] = 0.25

#: The width the skew analysis is done at. Downsampling first is what keeps the
#: sweep cheap, and it does not change the answer: skew is an angle, not a detail.
_SKEW_ANALYSIS_WIDTH: Final[int] = 400

#: The fill used when rotating. White, because a page is white and a black wedge
#: would corrupt the very measurement the rotation exists to improve.
_ROTATION_FILL: Final[int] = 255


@dataclasses.dataclass(frozen=True, slots=True)
class InverseMap:
    """The map from a crop's local coordinates back to the source page.

    A crop is cut in its own frame — the crop's ``(0, 0)`` is its top-left corner —
    while everything downstream is expressed in **source page coordinates**. This
    is the object that converts between them.

    It travels with the cropped bytes rather than being a step the caller is
    trusted to remember, because the failure it prevents is silent: a crop whose
    local coordinates are reported as a page region points the trace at the wrong
    pixels, and both boxes are valid JSON.

    Attributes:
        offset_x: Source-page x of the crop's origin.
        offset_y: Source-page y of the crop's origin.
        scale: Source-page units per local unit. ``1.0`` for a crop taken at the
            resolution of the page it came from.

    """

    offset_x: float
    offset_y: float
    scale: float

    def to_source(self, local_x: float, local_y: float) -> tuple[float, float]:
        """Map a point in the crop's local frame into source page coordinates.

        Args:
            local_x: The x coordinate within the crop.
            local_y: The y coordinate within the crop.

        Returns:
            The ``(x, y)`` pair in source page coordinates.

        """
        return (
            self.offset_x + local_x * self.scale,
            self.offset_y + local_y * self.scale,
        )


class _Refused(Exception):
    """An image that cannot be decoded, carrying the ``Reason`` that explains it."""

    def __init__(self, reason: Reason) -> None:
        """Store the reason.

        Args:
            reason: Why the image was refused.

        """
        super().__init__(reason.message)
        self.reason = reason


# --- Engine access -----------------------------------------------------------


def _engine() -> tuple[Any | None, Reason | None]:
    """Import the raster engine, or explain why it is unavailable.

    The import is inside the function by design: ``pyproject.toml`` declares no
    runtime dependency, so importing this module must not require the engine, and a
    missing library must arrive as a ``Reason`` rather than as an `ImportError`
    raised at import time.

    Returns:
        The ``PIL.Image`` module, or ``None`` with a typed ``Reason``.

    """
    try:
        from PIL import Image  # pylint: disable=import-outside-toplevel
    except ImportError:
        return None, Reason(
            code=_CODE_ENGINE_UNAVAILABLE,
            message=(
                f"the {_ENGINE_PACKAGE!r} library is not installed, so images "
                f"cannot be decoded. Install it (`pip install pillow`); no "
                "substitute engine is used, because a different decoder reading "
                "the same bytes is a different measurement reported as this one."
            ),
        )

    return Image, None


def _terms(engine: Any) -> Mapping[str, str]:
    """Report the engine's revision, as a cache-key term.

    Args:
        engine: The engine module.

    Returns:
        The adapter revision terms. The version is a key term because the same call
        against a different engine build is different work (`sad.md` §5).

    """
    return MappingProxyType(
        {
            "engine": _ENGINE_PACKAGE,
            "engine_version": str(getattr(engine, "__version__", "unknown")),
        }
    )


def _evidence(
    terms: Mapping[str, str],
    measurements: Mapping[str, float],
    observed: Mapping[str, object],
) -> Evidence:
    """Build an evidence record.

    Args:
        terms: The cache-key terms.
        measurements: The numeric measurements.
        observed: The remaining observations.

    Returns:
        The assembled ``Evidence``.

    """
    return Evidence(
        terms=MappingProxyType(dict(terms)),
        measurements=MappingProxyType(dict(measurements)),
        observed=MappingProxyType(dict(observed)),
    )


def _observed(
    terms: Mapping[str, str],
    measurements: Mapping[str, float],
    observed: Mapping[str, object],
) -> KernelResult[Evidence]:
    """Build a successful result whose value **is** the observation record.

    ``info``, ``legibility`` and ``crop`` produce measurements or a geometry-bearing
    bundle rather than content, so their value is an ``Evidence``. The same record
    is also the call's evidence, and it is the same object rather than a copy: the
    contract requires every call to report what it observed, and for these three
    that report *is* the answer.

    Args:
        terms: The cache-key terms.
        measurements: The numeric measurements.
        observed: The remaining observations.

    Returns:
        A ``KernelResult`` carrying the evidence as its value.

    """
    evidence = _evidence(terms, measurements, observed)

    return KernelResult(value=evidence, evidence=evidence, reason=None)


def _failure(
    reason: Reason,
    terms: Mapping[str, str],
    measurements: Mapping[str, float],
    observed: Mapping[str, object],
) -> KernelResult[Any]:
    """Build a failed result that still carries what was measured.

    A failure with no evidence cannot be diagnosed, and these measurements are
    frequently the reason the caller set the threshold where it did.

    Args:
        reason: Why no value was produced.
        terms: The cache-key terms.
        measurements: The measurements taken.
        observed: The remaining observations.

    Returns:
        A ``KernelResult`` with no value and the evidence attached.

    """
    return KernelResult(
        value=None,
        evidence=_evidence(terms, measurements, observed),
        reason=reason,
    )


# --- Decoding ----------------------------------------------------------------


def _decode(path: Path, engine: Any) -> tuple[Any, int | None]:
    """Decode an image and read the orientation its EXIF declares.

    Args:
        path: The image to decode.
        engine: The engine module.

    Returns:
        The decoded image and the orientation tag's value, or ``None`` when the
        image declares none. The image is returned **unrotated**: applying the
        rotation is the caller's next step, so that the tag can be reported before
        it is consumed.

    Raises:
        _Refused: When the file is absent or the bytes are not a format the engine
            accepts.

    """
    if not path.exists():
        raise _Refused(
            Reason(
                code=_CODE_UNSUPPORTED_FORMAT,
                message=f"{path.name!r} does not exist at {path}",
            )
        )

    try:
        image = engine.open(path)
        image.load()
    except Exception as exc:
        raise _Refused(
            Reason(
                code=_CODE_UNSUPPORTED_FORMAT,
                message=(
                    f"{path.name!r} could not be decoded as an image: "
                    f"{type(exc).__name__}: {exc}"
                ),
            )
        ) from exc

    orientation: int | None = None
    try:
        raw = image.getexif().get(_EXIF_ORIENTATION_TAG)
        if raw is not None:
            orientation = int(raw)
    except Exception:  # pylint: disable=broad-exception-caught
        # An unreadable EXIF block means *no declared orientation*, which is a
        # valid observation — and the alternative, failing the whole decode over
        # optional metadata, would reject images that are perfectly readable.
        orientation = None

    return image, orientation


def _upright(image: Any) -> Any:
    """Return the image with its declared orientation applied.

    ``ImageOps.exif_transpose`` both reads the tag and performs the rotation, which
    is what makes a sideways photo unrepresentable in the value that leaves this
    module: there is no code path that returns the stored pixels unrotated.

    Args:
        image: The decoded image.

    Returns:
        The rotated image. When nothing was declared, or the declaration is
        *already upright*, the image is returned unchanged.

    """
    from PIL import ImageOps  # pylint: disable=import-outside-toplevel

    return ImageOps.exif_transpose(image) or image


def _orientation_to_apply(orientation: int | None) -> bool:
    """Report whether an orientation value requires the pixels to move.

    Args:
        orientation: The EXIF tag's value, or ``None``.

    Returns:
        ``True`` when a rotation had to be applied. An absent tag and the
        *already upright* value both mean no rotation, which is why the report
        distinguishes them from a rotation of zero degrees: the two are different
        observations about the file.

    """
    if orientation is None:
        return False

    return orientation != _EXIF_UPRIGHT


def _encoded(image: Any) -> bytes:
    """Encode an image as PNG bytes.

    Args:
        image: The image to encode.

    Returns:
        The encoded buffer.

    """
    buffer = io.BytesIO()
    target = image if image.mode in {"RGB", "RGBA", "L"} else image.convert("RGB")
    target.save(buffer, format="PNG", optimize=True)

    return buffer.getvalue()


# --- Measurements ------------------------------------------------------------


def _luminance(image: Any) -> Any:
    """Reduce an image to the single channel the measurements are taken in.

    Args:
        image: The image.

    Returns:
        A luminance-mode copy.

    """
    return image if image.mode == _LUMINANCE else image.convert(_LUMINANCE)


def _laplacian_variance(image: Any, filters: Any, stats: Any) -> float:
    """Measure how much fine detail the image carries.

    The variance of the discrete Laplacian. Sharp edges produce a large response
    and a blurred image produces almost none, which is what makes this the standard
    sharpness measurement rather than an arbitrary number.

    Args:
        image: The luminance image.
        ImageFilter: The engine's filter module.
        ImageStat: The engine's statistics module.

    Returns:
        The variance, in the engine's own units. It is a measurement, not a verdict.

    """
    kernel = filters.Kernel(_LAPLACIAN_SIZE, list(_LAPLACIAN_KERNEL), scale=1, offset=0)
    filtered = image.filter(kernel)

    return float(stats.Stat(filtered).var[0])


def _contrast(image: Any, stats: Any) -> float:
    """Measure how far apart the image's brightness values sit.

    Normalized by the full channel range so the number is comparable across images
    rather than only within one.

    Args:
        image: The luminance image.
        ImageStat: The engine's statistics module.

    Returns:
        A value in ``[0, 1]``: zero for a flat field, approaching one for an image
        using the whole range.

    """
    deviation = float(stats.Stat(image).stddev[0])

    return min(1.0, deviation / (_CHANNEL_MAXIMUM / 2.0))


def _row_profile_variance(image: Any, angle: float, engine: Any, stats: Any) -> float:
    """Measure how strongly text lines separate when the image is rotated.

    The skew estimate works by projection: at the correct angle the dark rows of
    text line up and the row profile becomes strongly bimodal, so its spread peaks.
    At any other angle the rows smear together and the spread collapses. This is
    the standard deskew criterion, used here only to *report* the angle rather than
    to correct it.

    Args:
        image: The luminance image, already downsampled.
        angle: The candidate rotation, in degrees.
        engine: The engine module, for the resampling constant the call accepts.
        stats: The engine's statistics module.

    Returns:
        The spread of the rotated image's row profile. Higher means the rows
        separate more cleanly.

    """
    rotated = image.rotate(
        angle,
        resample=engine.Resampling.BILINEAR,
        expand=False,
        fillcolor=_ROTATION_FILL,
    )

    return float(stats.Stat(rotated).stddev[0])


def _skew_estimate(image: Any, engine: Any, stats: Any) -> float:
    """Estimate how far the page is rotated, in degrees.

    A bounded sweep around zero, on a downsampled copy: skew is an angle, so
    reducing the width does not change the answer while it does make the sweep
    cheap enough to run on every measurement.

    Args:
        image: The luminance image.
        engine: The engine module.
        stats: The engine's statistics module.

    Returns:
        The angle at which the row profile separates most cleanly. Its sign is
        meaningful and its magnitude is bounded by the sweep.

    """
    width, height = image.size
    if width == 0 or height == 0:
        return 0.0

    scale = _SKEW_ANALYSIS_WIDTH / width
    reduced = image.resize(
        (_SKEW_ANALYSIS_WIDTH, max(1, int(height * scale))),
        resample=engine.Resampling.BILINEAR,
    )

    best_angle = 0.0
    best_score = -1.0

    steps = int((_SKEW_RANGE_DEGREES * 2) / _SKEW_STEP_DEGREES) + 1
    for index in range(steps):
        angle = -_SKEW_RANGE_DEGREES + index * _SKEW_STEP_DEGREES
        score = _row_profile_variance(reduced, angle, engine, stats)
        if score > best_score:
            best_score = score
            best_angle = angle

    return round(best_angle, 2)


# --- The four operations -----------------------------------------------------


def load(path: Path) -> KernelResult[Bytes]:
    """Load a bitmap, with its declared orientation already applied.

    Args:
        path: The image to load.

    Returns:
        The decoded and rotated bitmap as PNG bytes, or no value and a typed
        ``Reason``. The rotation happens before the bytes leave this module, so a
        sideways photo is not representable in the value returned. Which way it was
        rotated is reported by :func:`info`, because the caller may need to undo it.

    """
    engine, failure = _engine()
    if engine is None:
        return _failure(failure or Reason("engine_unavailable", ""), {}, {}, {})

    try:
        image, orientation = _decode(path, engine)
    except _Refused as refused:
        return _failure(refused.reason, _terms(engine), {}, {"file": path.name})

    rotated = _orientation_to_apply(orientation)
    upright = _upright(image)
    width, height = upright.size

    return KernelResult(
        value=Bytes(data=_encoded(upright), media_type=_MEDIA_TYPE),
        evidence=_evidence(
            _terms(engine),
            {"width": float(width), "height": float(height)},
            {
                "file": path.name,
                "source_mode": str(image.mode),
                "width": width,
                "height": height,
                "media_type": _MEDIA_TYPE,
                # Reported alongside the value, not only on `info`: a caller that
                # loads without asking is still entitled to know the bytes it holds
                # are not the bytes on disk.
                "exif_orientation": orientation,
                "exif_orientation_applied": rotated,
            },
        ),
        reason=None,
    )


def info(path: Path) -> KernelResult[Evidence]:
    """Report what the image is, including the orientation that was applied.

    Args:
        path: The image to inspect.

    Returns:
        The dimensions, the colour model, and both halves of the orientation
        observation: the tag that was *found* and whether it was *applied*. Those
        are two different facts, and reporting only the second would make a
        rotation indistinguishable from a file that needed none.

    """
    engine, failure = _engine()
    if engine is None:
        return _failure(failure or Reason("engine_unavailable", ""), {}, {}, {})

    try:
        image, orientation = _decode(path, engine)
    except _Refused as refused:
        return _failure(refused.reason, _terms(engine), {}, {"file": path.name})

    applied = _orientation_to_apply(orientation)
    width, height = image.size

    return _observed(
        _terms(engine),
        {"width": float(width), "height": float(height)},
        {
            "file": path.name,
            "width": width,
            "height": height,
            "mode": str(image.mode),
            "format": str(image.format or "unknown"),
            "exif_orientation": orientation,
            "exif_orientation_applied": applied,
            "exif_orientation_tag": _EXIF_ORIENTATION_TAG,
        },
    )


def legibility(path: Path, threshold: float) -> KernelResult[Evidence]:
    """Measure how legible an image is, against the caller's threshold.

    Args:
        path: The image to measure.
        threshold: The caller's minimum acceptable value for the sharpness
            measurement. It is a required parameter with no default, because the
            value to compare against is policy and belongs to the caller
            (`prd.md` FR-15).

    Returns:
        The raw measurements — sharpness, contrast, skew — or, when the sharpness
        falls below ``threshold``, no value and an ``illegible`` reason **with the
        same measurements attached**. The measurements are on the result in both
        cases, so a caller can read the number the verdict was taken from instead
        of receiving a bare boolean.

    """
    engine, failure = _engine()
    if engine is None:
        return _failure(failure or Reason("engine_unavailable", ""), {}, {}, {})

    try:
        image, _orientation = _decode(path, engine)
    except _Refused as refused:
        return _failure(refused.reason, _terms(engine), {}, {"file": path.name})

    # Imported here, not at module scope, for the same reason `_engine` is: the
    # module must import without Pillow so a missing library arrives as a typed
    # `Reason` rather than as an `ImportError` at import time.
    # pylint: disable=import-outside-toplevel
    from PIL import ImageFilter as PillowFilter
    from PIL import ImageStat as PillowStat

    # pylint: enable=import-outside-toplevel

    luminance = _luminance(image)
    sharpness = _laplacian_variance(luminance, PillowFilter, PillowStat)
    contrast = _contrast(luminance, PillowStat)
    skew = _skew_estimate(luminance, engine, PillowStat)

    measurements: dict[str, float] = {
        "laplacian_variance": round(sharpness, 4),
        "contrast": round(contrast, 6),
        "skew_estimate": skew,
        "threshold_applied": threshold,
    }
    observed: dict[str, object] = {
        "file": path.name,
        "width": image.size[0],
        "height": image.size[1],
        "threshold_applied": threshold,
    }

    if sharpness < threshold:
        return _failure(
            Reason(
                code=_CODE_ILLEGIBLE,
                message=(
                    f"{path.name!r} measures {sharpness:.2f} of sharpness, below "
                    f"the {threshold} the caller requires, so no value is "
                    "returned. The measurement is on the evidence, not replaced by "
                    "it: whether this makes the image unusable is the caller's "
                    "decision, taken against its own policy."
                ),
            ),
            _terms(engine),
            measurements,
            observed,
        )

    return _observed(_terms(engine), measurements, observed)


def rescale(  # pylint: disable=too-many-locals
    path: Path, target_dpi: int, source_dpi: int
) -> KernelResult[Bytes]:
    """Rescale an image to a target resolution.

    The variable count is one over Pylint's ceiling and the suppression is stated
    rather than the function reshaped: the names are the two resolutions, the
    decoded image, its size, the scale factor, the resized image and its size, and
    the evidence record's two mappings. Grouping them into a helper would move the
    same count one frame away without making the refusal-vs-resize logic clearer.

    Args:
        path: The image to rescale.
        target_dpi: The resolution the caller wants.
        source_dpi: The resolution the image's pixels already hold. It is a
            parameter because ``Box`` carries no DPI and a kernel that invented one
            would be reporting a number nobody measured.

    Returns:
        The rescaled bitmap, with the target it actually honoured in the evidence,
        or no value and a typed ``Reason``. A target the source cannot reach is
        **refused**: enlarging the pixels would produce a larger file that is no
        more legible while reporting the request as met
        (`kernel-cli.md` §14). Vector content has no such limit, but an image
        always does, so this operation always measures before it writes.

    Raises:
        ValueError: If either resolution is not positive.

    """
    if target_dpi <= 0:
        raise ValueError(f"target_dpi must be positive, got {target_dpi}")
    if source_dpi <= 0:
        raise ValueError(f"source_dpi must be positive, got {source_dpi}")

    engine, failure = _engine()
    if engine is None:
        return _failure(failure or Reason("engine_unavailable", ""), {}, {}, {})

    try:
        image, _orientation = _decode(path, engine)
    except _Refused as refused:
        return _failure(refused.reason, _terms(engine), {}, {"file": path.name})

    terms = _terms(engine)
    observed_base: dict[str, object] = {
        "file": path.name,
        "source_dpi": source_dpi,
        "dpi_requested": target_dpi,
        "files_written": 0,
    }

    if target_dpi > source_dpi:
        return _failure(
            Reason(
                code=_CODE_INSUFFICIENT_RESOLUTION,
                message=(
                    f"the source holds {source_dpi} DPI, so a {target_dpi} DPI "
                    "rescale cannot be produced from it. The request is refused "
                    "rather than met by enlarging the pixels: a larger file would "
                    "look the same and claim a resolution the source does not "
                    "contain."
                ),
            ),
            terms,
            {"source_dpi": float(source_dpi), "dpi_requested": float(target_dpi)},
            observed_base,
        )

    factor = target_dpi / source_dpi
    width, height = image.size
    resized = image.resize(
        (max(1, round(width * factor)), max(1, round(height * factor))),
        engine.Resampling.LANCZOS,
    )
    new_width, new_height = resized.size

    return KernelResult(
        value=Bytes(data=_encoded(resized), media_type=_MEDIA_TYPE),
        evidence=_evidence(
            terms,
            {
                "source_dpi": float(source_dpi),
                "dpi_honoured": float(target_dpi),
                "width": float(new_width),
                "height": float(new_height),
            },
            {
                "file": path.name,
                "source_size": [width, height],
                "result_size": [new_width, new_height],
                "resampling": "LANCZOS",
                "media_type": _MEDIA_TYPE,
                "upscaled": False,
            },
        ),
        reason=None,
    )


def crop(path: Path, region: Box) -> KernelResult[Evidence]:
    """Cut a region out of an image and map its coordinates back to the source.

    Args:
        path: The image to crop.
        region: The region in **source page coordinates**.

    Returns:
        The evidence for the crop — its bytes in ``observed["image"]`` and the
        inverse map in ``observed["inverse_map"]`` — or no value and a typed
        ``Reason``. The map is returned with the bytes because the coordinates must
        be converted **before** they leave this module: a crop whose local
        coordinates are reported as a page region points the trace at the wrong
        pixels while remaining valid JSON, which is `NFR-07`.

    Raises:
        ValueError: If the region is degenerate or falls outside the image. A crop
            that cannot be taken is a mistake in the request, not an answer about
            the document.

    """
    if region.width <= 0 or region.height <= 0:
        raise ValueError(
            f"region must have a positive extent, got {region.width}x{region.height}"
        )

    engine, failure = _engine()
    if engine is None:
        return _failure(failure or Reason("engine_unavailable", ""), {}, {}, {})

    try:
        image, _orientation = _decode(path, engine)
    except _Refused as refused:
        return _failure(refused.reason, _terms(engine), {}, {"file": path.name})

    width, height = image.size
    left = round(region.x)
    top = round(region.y)
    right = left + round(region.width)
    bottom = top + round(region.height)

    if left < 0 or top < 0 or right > width or bottom > height:
        raise ValueError(
            f"region {region} falls outside the image, which is {width}x{height}"
        )

    cropped = image.crop((left, top, right, bottom))
    inverse = InverseMap(offset_x=float(left), offset_y=float(top), scale=1.0)

    return _observed(
        _terms(engine),
        {
            "source_x": float(left),
            "source_y": float(top),
            "width": float(cropped.size[0]),
            "height": float(cropped.size[1]),
        },
        {
            "file": path.name,
            "source_box": [float(left), float(top), float(right), float(bottom)],
            "source_size": [width, height],
            "local_size": [cropped.size[0], cropped.size[1]],
            "image": Bytes(data=_encoded(cropped), media_type=_MEDIA_TYPE),
            "inverse_map": inverse,
            "coordinate_space": "source_page",
        },
    )
