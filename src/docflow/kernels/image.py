"""K3 ``kernel.image`` — load with EXIF applied, legibility, rescale, crop.

The image *decisions*: whether a bitmap is legible against the caller's threshold,
whether a rescale target is reachable, what a crop's inverse map is, and which
orientation was found and whether it was applied (`sad.md` §3, `E04-03` / ``S1-T13``).

**The raster library is not imported here, not named here, and not callable from
here.** Pillow lives in `docflow/adapters/image.py`, which reaches this module
through the :class:`~docflow.kernels.image_vendor.RasterVendor` seam declared in
`docflow/kernels/image_vendor.py`. `sad.md` §1 requires every kernel to be usable
without its engine installed, and this module used to hold `from PIL import …` in
four places — an engine inside a kernel.

Every operation takes ``vendor`` as a keyword-only argument with **no default**. A
default would have to name a concrete library, which is the import this module
exists not to have, and an unbound seam must be a typed failure rather than a
substitute engine.

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
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from docflow.kernels.image_vendor import (
    EXIF_ORIENTATION_TAG,
    EXIF_UPRIGHT,
    RasterFrame,
    RasterVendor,
    RasterVendorError,
)
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
#: Public because the *adapter* raises it for a file it cannot decode, and a
#: caller matching on the code must not have to know which layer produced it.
CODE_UNSUPPORTED_FORMAT: Final[str] = "unsupported_format"
CODE_ENGINE_UNAVAILABLE: Final[str] = "engine_unavailable"
#: The requested resolution exceeds what the source pixels hold. The same
#: condition K2's ``render`` refuses on, and deliberately the same word: a caller
#: matching on the code must not have to know which kernel declined.
_CODE_INSUFFICIENT_RESOLUTION: Final[str] = "insufficient_effective_resolution"

# --- Engine identity ---------------------------------------------------------

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


def _identity_terms(vendor: RasterVendor) -> Mapping[str, str]:
    """Report the library's identity terms, or nothing when it cannot answer.

    A cache-key term must be a non-empty string, so an unavailable library contributes
    **nothing** rather than an ``"unknown"`` placeholder — a placeholder would key two
    genuinely different engines the same way, which is the failure the engine-version
    term exists to prevent (`sad.md` §5).

    Args:
        vendor: The raster implementation.

    Returns:
        The engine identity terms, or an empty mapping.

    """

    terms: dict[str, str] = {}
    try:
        terms |= dict(vendor.engine_terms())
    except RasterVendorError:
        return MappingProxyType({})

    return MappingProxyType(terms)


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


def _decode(vendor: RasterVendor, path: Path) -> tuple[RasterFrame, int | None]:
    """Decode an image and read the orientation its EXIF declares.

    Args:
        vendor: The raster implementation.
        path: The image to decode.

    Returns:
        The decoded frame and the orientation tag's value, or ``None`` when the file
        declares none. The frame comes back **unrotated**: applying the rotation is the
        next step, so that the tag can be reported before it is consumed.

    Raises:
        RasterVendorError: When the file is absent or is not a decodable image.

    """

    frame, meta = vendor.decode(path)

    return frame, meta.exif_orientation


def _upright(vendor: RasterVendor, frame: RasterFrame) -> RasterFrame:
    """Return the frame with its declared orientation applied.

    The rotation is the vendor's; the *decision* that it must happen is this module's,
    and it is what makes a sideways photo unrepresentable in the value that leaves:
    there is no code path that returns the stored pixels unrotated.

    Args:
        vendor: The raster implementation.
        frame: The decoded frame.

    Returns:
        The rotated frame. When nothing was declared, or the declaration is *already
        upright*, the frame comes back unchanged.

    """

    return vendor.upright(frame)


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

    return orientation != EXIF_UPRIGHT


def _sharpness(vendor: RasterVendor, luminance: RasterFrame) -> float:
    """Measure how much fine detail the image carries.

    The variance of the discrete Laplacian. Sharp edges produce a large response and a
    blurred image produces almost none, which is what makes this the standard sharpness
    measurement rather than an arbitrary number.

    The *matrix* is supplied from here because which kernel defines sharpness is a
    decision; applying a convolution is the library's business.

    Args:
        vendor: The raster implementation.
        luminance: The single-channel frame.

    Returns:
        The variance, in the library's own units. It is a measurement, not a verdict.

    """

    convolved = vendor.convolved(luminance, _LAPLACIAN_KERNEL, _LAPLACIAN_SIZE)

    return vendor.statistics(convolved).variance


def _contrast(vendor: RasterVendor, luminance: RasterFrame) -> float:
    """Measure how far apart the image's brightness values sit.

    Normalized by the full channel range so the number is comparable across images
    rather than only within one.

    Args:
        vendor: The raster implementation.
        luminance: The single-channel frame.

    Returns:
        A value in ``[0, 1]``: zero for a flat field, approaching one for an image
        using the whole range.

    """

    deviation = vendor.statistics(luminance).stddev

    return min(1.0, deviation / (_CHANNEL_MAXIMUM / 2.0))


def _row_profile_variance(
    vendor: RasterVendor, luminance: RasterFrame, angle: float
) -> float:
    """Measure how strongly text lines separate when the image is rotated.

    The skew estimate works by projection: at the correct angle the dark rows of text
    line up and the row profile becomes strongly bimodal, so its spread peaks. At any
    other angle the rows smear together and the spread collapses. This is the standard
    deskew criterion, used here only to *report* the angle rather than to correct it.

    Args:
        vendor: The raster implementation.
        luminance: The single-channel frame, already downsampled.
        angle: The candidate rotation, in degrees.

    Returns:
        The spread of the rotated frame's row profile. Higher means the rows separate
        more cleanly.

    """

    turned = vendor.rotated(luminance, angle, _ROTATION_FILL)

    return vendor.statistics(turned).stddev


def _skew_estimate(vendor: RasterVendor, luminance: RasterFrame) -> float:
    """Estimate how far the page is rotated, in degrees.

    A bounded sweep around zero, on a downsampled copy: skew is an angle, so reducing
    the width does not change the answer while it does make the sweep cheap enough to
    run on every measurement.

    Args:
        vendor: The raster implementation.
        luminance: The single-channel frame.

    Returns:
        The angle at which the row profile separates most cleanly. Its sign is
        meaningful and its magnitude is bounded by the sweep.

    """

    width, height = luminance.size
    if width == 0 or height == 0:
        return 0.0

    scale = _SKEW_ANALYSIS_WIDTH / width
    reduced = vendor.resized(
        luminance,
        (_SKEW_ANALYSIS_WIDTH, max(1, int(height * scale))),
        smooth=False,
    )

    best_angle = 0.0
    best_score = -1.0

    steps = int((_SKEW_RANGE_DEGREES * 2) / _SKEW_STEP_DEGREES) + 1
    for index in range(steps):
        angle = -_SKEW_RANGE_DEGREES + index * _SKEW_STEP_DEGREES
        score = _row_profile_variance(vendor, reduced, angle)
        if score > best_score:
            best_score = score
            best_angle = angle

    return round(best_angle, 2)


def load(path: Path, *, vendor: RasterVendor) -> KernelResult[Bytes]:
    """Load a bitmap, with its declared orientation already applied.

    Args:
        path: The image to load.
        vendor: The raster implementation.

    Returns:
        The decoded and rotated bitmap as PNG bytes, or no value and a typed
        ``Reason``. The rotation happens before the bytes leave this module, so a
        sideways photo is not representable in the value returned. Which way it was
        rotated is reported by :func:`info`, because the caller may need to undo it.

    """
    terms = _identity_terms(vendor)

    try:
        frame, orientation = _decode(vendor, path)
    except RasterVendorError as refused:
        return _failure(refused.reason, terms, {}, {"file": path.name})

    applied = _orientation_to_apply(orientation)
    upright = _upright(vendor, frame)
    width, height = upright.size

    try:
        payload = vendor.encoded_png(upright)
    except RasterVendorError as refused:
        return _failure(refused.reason, terms, {}, {"file": path.name})

    return KernelResult(
        value=Bytes(data=payload, media_type=_MEDIA_TYPE),
        evidence=_evidence(
            terms,
            {"width": float(width), "height": float(height)},
            {
                "file": path.name,
                "source_mode": str(frame.mode),
                "width": width,
                "height": height,
                "media_type": _MEDIA_TYPE,
                # Reported alongside the value, not only on `info`: a caller that
                # loads without asking is still entitled to know the bytes it holds
                # are not the bytes on disk.
                "exif_orientation": orientation,
                "exif_orientation_applied": applied,
            },
        ),
        reason=None,
    )


def info(path: Path, *, vendor: RasterVendor) -> KernelResult[Evidence]:
    """Report what the image is, including the orientation that was applied.

    Args:
        path: The image to inspect.
        vendor: The raster implementation.

    Returns:
        The dimensions, the colour model, and both halves of the orientation
        observation: the tag that was *found* and whether it was *applied*. Those
        are two different facts, and reporting only the second would make a
        rotation indistinguishable from a file that needed none.

    """
    terms = _identity_terms(vendor)

    try:
        frame, meta = vendor.decode(path)
    except RasterVendorError as refused:
        return _failure(refused.reason, terms, {}, {"file": path.name})

    orientation = meta.exif_orientation
    applied = _orientation_to_apply(orientation)
    width, height = frame.size

    return _observed(
        terms,
        {"width": float(width), "height": float(height)},
        {
            "file": path.name,
            "width": width,
            "height": height,
            "mode": str(frame.mode),
            "format": meta.format,
            "exif_orientation": orientation,
            "exif_orientation_applied": applied,
            "exif_orientation_tag": EXIF_ORIENTATION_TAG,
        },
    )


def legibility(
    path: Path, threshold: float, *, vendor: RasterVendor
) -> KernelResult[Evidence]:
    """Measure how legible an image is, against the caller's threshold.

    Args:
        path: The image to measure.
        threshold: The caller's minimum acceptable value for the sharpness
            measurement. It is a required parameter with no default, because the
            value to compare against is policy and belongs to the caller
            (`prd.md` FR-15).
        vendor: The raster implementation.

    Returns:
        The raw measurements — sharpness, contrast, skew — or, when the sharpness
        falls below ``threshold``, no value and an ``illegible`` reason **with the
        same measurements attached**. The measurements are on the result in both
        cases, so a caller can read the number the verdict was taken from instead
        of receiving a bare boolean.

    """
    terms = _identity_terms(vendor)

    try:
        frame, _meta = vendor.decode(path)
        luminance = vendor.greyscale(frame)
    except RasterVendorError as refused:
        return _failure(refused.reason, terms, {}, {"file": path.name})

    try:
        sharpness = _sharpness(vendor, luminance)
        contrast = _contrast(vendor, luminance)
        skew = _skew_estimate(vendor, luminance)
    except RasterVendorError as refused:
        return _failure(refused.reason, terms, {}, {"file": path.name})

    measurements: dict[str, float] = {
        "laplacian_variance": round(sharpness, 4),
        "contrast": round(contrast, 6),
        "skew_estimate": skew,
        "threshold_applied": threshold,
    }
    observed: dict[str, object] = {
        "file": path.name,
        "width": frame.size[0],
        "height": frame.size[1],
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
            terms,
            measurements,
            observed,
        )

    return _observed(terms, measurements, observed)


def rescale(  # pylint: disable=too-many-locals
    path: Path, target_dpi: int, source_dpi: int, *, vendor: RasterVendor
) -> KernelResult[Bytes]:
    """Rescale an image to a target resolution.

    The variable count is one over Pylint's ceiling and the suppression is stated
    rather than the function reshaped. The names are the two resolutions, the decoded
    frame, its size, the scale factor, the resampled frame, its size, the payload, the
    identity terms, the evidence record's two mappings and the observed base — the
    count grew by one when the vendor stopped being module-level and became a
    parameter. Extracting the result assembly was tried and made it worse: it moved
    these names into a second function that then needed seven arguments, which is two
    findings rather than one.

    Args:
        path: The image to rescale.
        target_dpi: The resolution the caller wants.
        source_dpi: The resolution the image's pixels already hold. It is a
            parameter because ``Box`` carries no DPI and a kernel that invented one
            would be reporting a number nobody measured.
        vendor: The raster implementation.

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

    terms = _identity_terms(vendor)

    try:
        frame, _meta = vendor.decode(path)
    except RasterVendorError as refused:
        return _failure(refused.reason, terms, {}, {"file": path.name})

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
    width, height = frame.size

    try:
        resized = vendor.resized(
            frame,
            (max(1, round(width * factor)), max(1, round(height * factor))),
            smooth=True,
        )
        payload = vendor.encoded_png(resized)
    except RasterVendorError as refused:
        return _failure(refused.reason, terms, {}, {"file": path.name})

    new_width, new_height = resized.size

    return KernelResult(
        value=Bytes(data=payload, media_type=_MEDIA_TYPE),
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


def crop(  # pylint: disable=too-many-locals
    path: Path, region: Box, *, vendor: RasterVendor
) -> KernelResult[Evidence]:
    """Cut a region out of an image and map its coordinates back to the source.

    The variable count is over Pylint's ceiling and the suppression is stated rather
    than the function reshaped. The names are the source rectangle's four edges, the
    frame and its size, the cropped frame, the payload, the inverse map, the identity
    terms and the evidence record's two mappings — four of them grew when the vendor
    became a parameter and the encoded bytes became explicit.

    Args:
        path: The image to crop.
        region: The region in **source page coordinates**.
        vendor: The raster implementation.

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

    terms = _identity_terms(vendor)

    try:
        frame, _meta = vendor.decode(path)
    except RasterVendorError as refused:
        return _failure(refused.reason, terms, {}, {"file": path.name})

    width, height = frame.size
    left = round(region.x)
    top = round(region.y)
    right = left + round(region.width)
    bottom = top + round(region.height)

    if left < 0 or top < 0 or right > width or bottom > height:
        raise ValueError(
            f"region {region} falls outside the image, which is {width}x{height}"
        )

    try:
        cropped = vendor.cropped(frame, (left, top, right, bottom))
        payload = vendor.encoded_png(cropped)
    except RasterVendorError as refused:
        return _failure(refused.reason, terms, {}, {"file": path.name})

    inverse = InverseMap(offset_x=float(left), offset_y=float(top), scale=1.0)

    return _observed(
        terms,
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
            "image": Bytes(data=payload, media_type=_MEDIA_TYPE),
            "inverse_map": inverse,
            "coordinate_space": "source_page",
        },
    )
