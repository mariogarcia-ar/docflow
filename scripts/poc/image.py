"""Direct probes of the K3 `image` adapter, one method per requirement.

`my_kernel_flow.md` §2 asks for three things of the `image` kernel:

1. resize (by DPI **and** by size),
2. crop,
3. validate legibility.

Each is a method below that calls `RasterEngine` directly, so what it reports is
the adapter's behaviour and not `docflow-kernel`'s.

Two of the requirements do not map onto the adapter as written, and this driver
reports that rather than papering over it:

- **"resize by size" has no operation.** `rescale` takes a *target DPI*, and the
  only size-shaped operations (`image tile`, `image deskew`, `image phash`) are
  declared but not implemented - `kernel-cli.md` §9 marks them `MVP`. `closest_size`
  is the nearest thing that exists and it lives in the kernel's internals, not on
  the engine.
- **`rescale` needs a source resolution the adapter cannot measure.** `info`
  reports the format and the EXIF orientation, and no DPI at all - so the CLI's own
  lookup (`commands/image.py::_measured_dpi`, which reads `dpi`/`effective_dpi`/
  `source_dpi` out of the result) finds nothing and refuses every run. `D4` below
  reproduces that; `D3` shows the adapter works when the caller supplies the number.

Run it with no arguments to probe the committed fixtures:

    python scripts/poc/image.py
"""

from __future__ import annotations

import argparse
import pathlib
import sys
from typing import Any

import _lib

# `docflow` is only importable once `src/` is on the path; see `pdf.py` for why
# the ordering of these two imports is load-bearing.
_lib.bootstrap()

from docflow.adapters.image import RasterEngine  # noqa: E402 - see the note above
from docflow.kernels.types import Box  # noqa: E402 - see the note above

__all__: list[str] = []

#: The resolution `rescale` is asked for. Below the 96 the fixtures declare, so the
#: probe exercises the honest path rather than the anti-upscale refusal.
TARGET_DPI: int = 72

#: The resolution the *caller* asserts the pixels hold, used only by D3. It is
#: asserted rather than measured because the adapter offers no way to measure it -
#: which is D4's whole point.
ASSERTED_SOURCE_DPI: int = 96

#: A region inside the 1564x1920 fixture, in **source page coordinates**.
REGION: Box = Box(x=100.0, y=120.0, width=400.0, height=300.0)

#: The keys the CLI's `_measured_dpi` looks for, in its own order. Kept here so the
#: reproduction of that lookup is a transcription of the command, not a guess.
_DPI_KEYS: tuple[str, ...] = ("dpi", "effective_dpi", "source_dpi")


def _engine() -> RasterEngine:
    """Build the K3 adapter.

    Returns:
        The engine, ready to call.

    """
    return RasterEngine()


# --- Supporting: what is the image? -----------------------------------------


def describe(engine: RasterEngine, path: pathlib.Path, expect: str) -> None:
    """Report what the image is.

    `info` is not one of the flow's three requirements, but it is what the other
    three are built on - and it is where the missing DPI shows.

    Args:
        engine: The K3 adapter.
        path: The image to inspect.
        expect: The bucket this probe is declared to land in.

    """
    attempt = _lib.run(
        f"image.info[{path.parent.name}]", engine.info, path, expect=expect
    )
    if not attempt.succeeded:
        return

    observed = attempt.result.evidence.observed
    print(
        f"         format={observed.get('format')!r} mode={observed.get('mode')!r} "
        f"exif={observed.get('exif_orientation')!r}"
    )


def load_bitmap(engine: RasterEngine, path: pathlib.Path, expect: str) -> None:
    """Decode a bitmap, with its declared orientation applied.

    Args:
        engine: The K3 adapter.
        path: The image to load.
        expect: The bucket this probe is declared to land in.

    """
    attempt = _lib.run(
        f"image.load[{path.suffix.lstrip('.')}]", engine.load, path, expect=expect
    )
    if not attempt.succeeded:
        return

    value = attempt.result.value
    written = _lib.save_bytes(f"{path.stem}-loaded.png", value.data)
    print(f"         wrote {written.relative_to(_lib.ROOT)}")


# --- Requirement 3: validate legibility -------------------------------------


def measure_legibility(
    engine: RasterEngine, path: pathlib.Path, threshold: float | None, expect: str
) -> None:
    """Measure sharpness against the caller's threshold.

    The threshold is corpus policy (`image.legibility_threshold`, `ADR-009`), read
    from the registry rather than chosen here. Passing ``None`` uses the policy
    value; passing a number uses that instead, which is how the *control* probe
    below shows that `illegible` is a comparison rather than a property of the file.

    Args:
        engine: The K3 adapter.
        path: The image to measure.
        threshold: The threshold to compare against, or ``None`` for the policy one.
        expect: The bucket this probe is declared to land in.

    """
    applied = (
        _lib.policy("image.legibility_threshold") if threshold is None else threshold
    )
    label = f"image.legibility[{path.parent.name}]@{applied:g}"
    _lib.run(label, engine.legibility, path, applied, expect=expect)


# --- Requirement 1: resize --------------------------------------------------


def resize_by_dpi(
    engine: RasterEngine,
    path: pathlib.Path,
    target_dpi: int,
    source_dpi: int,
    expect: str,
) -> None:
    """Rescale to a target DPI, with the source resolution supplied by the caller.

    `source_dpi` is a required parameter of the adapter and has no default: an
    invented source resolution is a number nobody measured, and it is what decides
    whether the target is reachable at all.

    Args:
        engine: The K3 adapter.
        path: The image to rescale.
        target_dpi: The resolution requested.
        source_dpi: The resolution the caller asserts the pixels hold.
        expect: The bucket this probe is declared to land in.

    """
    label = f"image.rescale[{target_dpi}<-{source_dpi}]"
    attempt = _lib.run(
        label, engine.rescale, path, target_dpi, source_dpi, expect=expect
    )
    if not attempt.succeeded:
        return

    written = _lib.save_bytes(
        f"{path.stem}-dpi{target_dpi}.png", attempt.result.value.data
    )
    print(f"         wrote {written.relative_to(_lib.ROOT)}")


def resize_by_dpi_like_the_cli(engine: RasterEngine, path: pathlib.Path) -> None:
    """Reproduce the CLI's own source-resolution lookup, which finds nothing.

    `commands/image.py::rescale` reads `info` first and then looks for one of
    `dpi`, `effective_dpi`, `source_dpi` in the measurements and in the
    observables. This probe performs **that same lookup** and reports which keys it
    asked for, so the refusal is attributable to a missing reading rather than to a
    broken rescale.

    Args:
        engine: The K3 adapter.
        path: The image the CLI would be pointed at.

    """
    described = engine.info(path)
    if described.value is None:
        _lib.note("image.rescale[via CLI]", "info refused, so the lookup never ran")
        return

    found: dict[str, Any] = {}
    for key in _DPI_KEYS:
        for source, where in (
            (described.evidence.measurements, "measurements"),
            (described.evidence.observed, "observed"),
        ):
            value = source.get(key)
            if isinstance(value, (int, float)):
                found[key] = f"{value} (from {where})"

    if found:
        _lib.note("image.rescale[via CLI]", f"the lookup found {found}")
        return

    _lib.note(
        "image.rescale[via CLI]",
        f"the lookup found NONE of {list(_DPI_KEYS)} -> the command refuses every run",
    )
    print(
        "      the adapter has no way to measure this, so `source_dpi` can only "
        "come from\nthe caller. From the CLI there is no such caller."
    )


def resize_by_size(engine: RasterEngine, path: pathlib.Path) -> None:
    """Report that the flow's "resize by size" has no operation behind it.

    This probe asserts nothing because there is nothing to call. `rescale` takes a
    target **DPI**; the size-shaped operations (`image tile`, `image deskew`,
    `image phash`) are `MVP` in `kernel-cli.md` §9 and exit `4`. Recording the
    absence is the honest answer, and it is what makes the gap a decision instead of
    an oversight.

    Args:
        engine: The K3 adapter.
        path: The image the operation would be pointed at.

    """
    operations = sorted(name for name in dir(engine) if not name.startswith("_"))
    _lib.note(
        "image.resize[by size]",
        f"no operation: RasterEngine exposes {operations}",
    )
    print(
        "      none of them takes a target size. `closest_size` exists in the "
        "kernel's\nown internals but is not on the engine (`kernel-cli.md` §9 "
        "marks the size-shaped\noperations MVP), so the requirement has no door."
    )


# --- Requirement 2: crop ----------------------------------------------------


def crop_region(
    engine: RasterEngine, path: pathlib.Path, region: Box, expect: str
) -> None:
    """Cut a region out and map its coordinates back to the source.

    The inverse map is not decoration: a crop whose local coordinates are reported
    as a page region points the next stage at the wrong area, and **both boxes are
    valid JSON** - so the error is invisible unless something checks the map.

    Args:
        engine: The K3 adapter.
        path: The image to crop.
        region: The region in source page coordinates.
        expect: The bucket this probe is declared to land in.

    """
    label = f"image.crop[{region.x:g},{region.y:g},{region.width:g},{region.height:g}]"
    attempt = _lib.run(label, engine.crop, path, region, expect=expect)
    if not attempt.succeeded:
        return

    observed = attempt.result.value.observed
    written = _lib.save_bytes(f"{path.stem}-crop.png", observed["image"].data)

    inverse = observed.get("inverse_map")
    local = observed.get("local_size")
    expected_local = [int(region.width), int(region.height)]
    agrees = list(local or []) == expected_local

    print(
        f"         wrote {written.relative_to(_lib.ROOT)}  "
        f"space={observed.get('coordinate_space')!r} local_size={local} "
        f"inverse=({inverse.offset_x:g},{inverse.offset_y:g} scale={inverse.scale:g})"
    )
    print(
        f"         the crop's own frame matches the region asked for: "
        f"{'yes' if agrees else 'NO'}"
    )


# --- The run ----------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Run every `image` probe and tally the result.

    Args:
        argv: The command-line arguments, or ``None`` for `sys.argv`.

    Returns:
        The number of probes that produced a bucket other than the one declared.

    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--out",
        type=pathlib.Path,
        default=_lib.DEFAULT_OUT,
        help="where rescaled and cropped bitmaps are written",
    )
    args = parser.parse_args(argv)

    _lib.set_out(args.out)
    _lib.reset()
    engine = _engine()

    print(
        f"threshold = {_lib.policy('image.legibility_threshold')} (from the registry)"
    )
    print(f"out       = {args.out}")
    print()

    # What the image is. `casos/` fixtures are the ones the flow names as inputs.
    describe(engine, _lib.CASE_IMAGE, "ok")
    load_bitmap(engine, _lib.CASE_IMAGE, "ok")

    print()
    # Requirement 3. Three probes, and the third is the control that proves the
    # first two are a *comparison* rather than a fixed verdict on the file.
    measure_legibility(engine, _lib.CASE_IMAGE, None, "ok")
    measure_legibility(engine, _lib.BLUR_IMAGE, None, "reason")
    measure_legibility(engine, _lib.BLUR_IMAGE, 0.0, "ok")

    print()
    # Requirement 1, the DPI half.
    resize_by_dpi(engine, _lib.CASE_IMAGE, TARGET_DPI, ASSERTED_SOURCE_DPI, "ok")
    # The target above what the pixels hold. The adapter refuses rather than
    # resampling upwards and reporting the request as satisfied.
    resize_by_dpi(engine, _lib.CASE_IMAGE, 400, ASSERTED_SOURCE_DPI, "reason")
    resize_by_dpi_like_the_cli(engine, _lib.CASE_IMAGE)

    print()
    # Requirement 1, the size half, which has no operation.
    resize_by_size(engine, _lib.CASE_IMAGE)

    print()
    # Requirement 2.
    crop_region(engine, _lib.CASE_IMAGE, REGION, "ok")

    print()
    return _lib.summary()


if __name__ == "__main__":
    sys.exit(main())
