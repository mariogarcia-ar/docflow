"""K3's commands - `image` (`E07-02` / `S1-T21`).

Four `now` commands and three `MVP` ones. `info` is matrix row 6, `legibility` row 7
and `crop` row 8 - and `crop` is the one whose *evidence* is the contract: the inverse
map must land back in source coordinates (`NFR-07`), because a crop's local box
reported as a page region is valid JSON and nothing else notices.

`legibility`'s threshold is corpus policy (`ADR-009`) read from the registry, never
defaulted: a defaulted threshold is this surface deciding what *blurry* means, which
is the whole of matrix row 7.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

from docflow.adapters.image import RasterEngine
from docflow.kernel_cli.commands.policy import DEFAULT_ROOT, policy_number
from docflow.kernel_cli.commands.refusals import refusal
from docflow.kernel_cli.main import Call, Handler, UsageError
from docflow.kernels.types import Box, KernelResult, Reason

#: What each refusal in this module was blocked by. One value for the module,
#: because every refusal here is the same kind of event: a command whose
#: parameters do not name a call this surface can make.
_BLOCKED: Final[str] = "missing_parameter"

__all__: list[str] = []

#: The policy key the legibility threshold comes from.
_LEGIBILITY_KEY: Final[str] = "image.legibility_threshold"


def _box(text: str) -> Box:
    """Parse an ``x,y,w,h`` region.

    Args:
        text: The region string.

    Returns:
        The box.

    Raises:
        UsageError: If it is not four integers. Refusing rather than defaulting: a
            defaulted region crops pixels nobody asked for and reports success.

    """
    parts = [piece.strip() for piece in text.split(",")]
    if len(parts) != 4 or not all(part.isdigit() for part in parts):
        raise UsageError(
            f"--region must be 'x,y,w,h' with four non-negative integers; got {text!r}."
        )
    x, y, width, height = (int(part) for part in parts)
    return Box(x=x, y=y, width=width, height=height)


def info(*, file: str, **_: object) -> Call:
    """Report the file's size and its EXIF orientation, already applied.

    Args:
        file: The image to read.
        **_: Accepted, so an unknown flag reaches the dispatcher.

    Returns:
        The call.

    """
    return Call(result=RasterEngine().info(Path(file)))


def legibility(*, file: str, root: str = DEFAULT_ROOT, **_: object) -> Call:
    """Measure whether an image is fit to read: a measurement plus a reason.

    Args:
        file: The image to measure.
        root: The registry root the threshold comes from.
        **_: Accepted, so an unknown flag reaches the dispatcher.

    Returns:
        The call. Never a bare boolean - a caller has to be able to see *how*
        illegible it was.

    """
    threshold = policy_number(Path(root), _LEGIBILITY_KEY)
    if threshold.reason is not None:
        return Call(result=refusal(threshold.reason, blocked_by=_BLOCKED))
    value = threshold.value
    reason = threshold.reason
    if value is None:
        # `policy_number` answers with a value or a reason, never neither, so a
        # missing value here means a reason is present. Binding it first keeps the
        # call width in range and, more to the point, makes the invariant this branch
        # relies on visible at the place that relies on it.
        return Call(result=refusal(reason, blocked_by=_BLOCKED))
    return Call(result=RasterEngine().legibility(Path(file), value))


def rescale(*, file: str, target_dpi: object = None, **_: object) -> Call:
    """Rescale to a target resolution, or refuse when it is unreachable.

    `source_dpi` is **measured** rather than assumed. The adapter requires it, because
    a rescale that compared the target against an invented source resolution would
    either enlarge a scan (upscaling, which the kernel refuses) or report a
    resolution the pixels do not hold. So it is read from the engine's own `info`
    first, and a reading that fails is reported rather than defaulted.

    Args:
        file: The image to rescale.
        target_dpi: The target resolution. Required: a rescale with no target names
            no destination, and a default here would be this surface choosing one.
        **_: Accepted, so an unknown flag reaches the dispatcher.

    Returns:
        The call.

    """
    if target_dpi is None:
        return Call(
            result=refusal(
                Reason(
                    code="unsupported_format",
                    message=(
                        "--target-dpi is required: a rescale with no target is not a "
                        "smaller default, it is a request that names no destination."
                    ),
                ),
                blocked_by=_BLOCKED,
            )
        )

    engine = RasterEngine()
    described = engine.info(Path(file))
    if described.reason is not None or described.value is None:
        return Call(result=_refusal_from(described))

    source = _measured_dpi(described)
    if source is None:
        return Call(
            result=refusal(
                Reason(
                    code="unsupported_format",
                    message=(
                        "The engine reported no source resolution for this image, so "
                        "a rescale cannot decide whether the target is reachable. "
                        "Refusing rather than assuming a resolution the pixels do "
                        "not hold."
                    ),
                ),
                blocked_by=_BLOCKED,
            )
        )

    return Call(result=engine.rescale(Path(file), int(str(target_dpi)), source))


def _measured_dpi(described: KernelResult[Any]) -> int | None:
    """Read the source resolution out of an `info` result.

    Args:
        described: The engine's `info` result.

    Returns:
        The measured resolution in DPI, or None when it was not reported.

    """
    for key in ("dpi", "effective_dpi", "source_dpi"):
        value = described.evidence.measurements.get(key)
        if isinstance(value, (int, float)):
            return int(value)
        observed = described.evidence.observed.get(key)
        if isinstance(observed, (int, float)):
            return int(observed)
    return None


def _refusal_from(result: KernelResult[Any]) -> KernelResult[Any]:
    """Carry a failure through as a refusal.

    Args:
        result: The failed result.

    Returns:
        The same result, which already carries no value and a typed reason.

    """
    return result


def crop(*, file: str, region: str, **_: object) -> Call:
    """Crop a region, returning the crop **and** its inverse map.

    Args:
        file: The image to crop.
        region: The region as ``x,y,w,h`` in source coordinates.
        **_: Accepted, so an unknown flag reaches the dispatcher.

    Returns:
        The call, whose evidence carries the inverse map a result found inside the
        crop is mapped back through (`NFR-07`).

    Raises:
        UsageError: If the region falls outside the image. The kernel refuses that
            with a ``ValueError`` - correctly, since it cannot crop pixels that are
            not there - and the *caller wrote the region*. Reporting it as exit
            ``1`` would tell them the build is broken about a number they can
            change, so the surface translates it into the usage error it is.

    """
    engine = RasterEngine()
    try:
        return Call(result=engine.crop(Path(file), _box(region)))
    except ValueError as exc:
        raise UsageError(str(exc)) from exc


#: What this module declares, as data. Each entry is
#: ``(operation, handler, positional, flags)``: ``handler=None`` is an ``MVP``
#: command, ``positional`` is the argument a bare token binds to, and ``flags`` are
#: the port parameters the command reads. The contract test compares ``flags``
#: against the signature of the port method named in `_PORT_METHOD`.
COMMANDS: Final[tuple[tuple[str, Handler | None, str | None, tuple[str, ...]], ...]] = (
    ("info", info, "file", ()),
    ("legibility", legibility, "file", ("--root",)),
    ("rescale", rescale, "file", ("--target-dpi", "--save")),
    ("crop", crop, "file", ("--region", "--save")),
    ("deskew", None, "file", ("--save",)),
    ("phash", None, "file", ()),
    ("tile", None, "file", ("--max-pixels", "--save")),
)
