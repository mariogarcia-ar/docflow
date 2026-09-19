"""The image-only batch walk: a folder of images in, a mirrored tree of bitmaps out.

`my_kernel_flow.md` §2, applied to a folder:

> resize by dpi and size, crop, validate their legibility.

This is `batch.py` §6 with the PDF half taken out, and the counterpart of
`batch_pdf.py`. Where that one routes a *page* to text or pixels, this one takes an
image that is **already** pixels and does the three things §2 asks of it: measures
whether it is worth reading, brings it to the resolution the corpus declares
readable, and cuts the regions a caller names.

Why a driver of its own
-----------------------

Because §2 is a step of its own. `batch.py` runs the legibility gate and then goes
straight to OCR; `batch_pdf.py` never touches K3 at all. Neither answers *what does
this folder of images look like* - how many are legible, what resolution they hold,
which ones an OCR pass would be wasting its time on. That answer costs one `info`
and one `legibility` per image and needs no engine downstream of K3, which is what
makes this usable on the 11k-document corpus (`prd.md`) where `batch.py` is not.

**This is not K1.** Like `batch.py`, it composes the adapters for one walk of a
folder: no ledger, no cache key, no `pause`/`resume`, and re-running re-does the
work. "Batch" names the shape of the run, not the orchestrator.

The image is the unit, and there are no sub-units
-------------------------------------------------

A PDF has pages, so `batch_pdf.py` decides per page. An image has no such division:
one file is one measurement, one legibility reading and any number of crops. So the
unit is the **file**, and what a file produces is a small record rather than a
sequence of routes.

What each image becomes
-----------------------

| Step | Operation | Output at the mirrored path |
|---|---|---|
| measured | `info` | nothing; the size, format and orientation are recorded |
| gated | `legibility` | nothing; the reading and the verdict are recorded |
| brought to the floor | `rescale` | `<stem>-dpiN.png`, when it needs it |
| cropped | `crop` | `<stem>-crop-rX-Y-W-H.png`, when a region is asked for |

The legibility gate is a **report**, not a filter. `illegible` is a legitimate
answer about a document - matrix row 7 - so this driver records it and still
measures everything else. Whether to continue is the caller's decision
(`kernel-cli.md` §3 guardrail 2), and a batch that silently dropped every blurred
image would answer its cut of the corpus without saying what it had thrown away.

What is deliberately **not** here
---------------------------------

- **No "resize by size".** §2 asks for it and there is no operation behind it:
  `RasterEngine` exposes `crop`, `info`, `legibility`, `load`, `rescale`, `vendor`,
  and none takes a target size. `image.py` records that finding; this driver does not
  invent a fourth step to cover it.
- **No OCR.** The material this driver writes is K4's *input*; reading it is
  `batch.py`'s job, and doing it here would make a K3 walk depend on a model.
- **No deskew.** `image deskew` is `MVP` in `kernel-cli.md` §9.

The interesting value is the resolution, and it is the one that cannot be measured
---------------------------------------------------------------------------------

`rescale` takes `source_dpi` as a required parameter, and **K3 offers no way to read
it**: `info` reports `width`, `height`, `mode`, `format` and the EXIF orientation,
and no DPI at all. So this driver measures the resolution the only way it can - from
the pixels themselves, using a caller-supplied assumption about the physical size of
the document - and when the caller supplies none, it **records the gap and does not
rescale**. That is the same finding `image.py`'s `via CLI` probe reports, and it is
the reason `image rescale` cannot succeed from the CLI.

TODO: [MVP] The assumption has no default here on purpose: `--assumed-dpi` decides a
number nobody measured, and `ADR-009` makes a threshold corpus policy rather than a
driver's choice. When K3 can read the DPI (a widened `ImageMeta`, `image.py` FINDING
D), the flag goes away and the measurement replaces it.

Run it:

    python scripts/poc/batch_image.py <input-dir> [--out DIR] [--region x,y,w,h]
                                       [--target-dpi N] [--assumed-dpi N]

Examples:

    python scripts/poc/batch_image.py tests/fixtures/casos
    python scripts/poc/batch_image.py tests/fixtures/blur --no-save
    python scripts/poc/batch_image.py documentos --target-dpi 150 --assumed-dpi 96
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import sys
from typing import Final

import _lib
import _mirror

# The ordering is load-bearing, exactly as in every other driver here: `_lib` puts
# `src/` on `sys.path`, and `image` is imported so this module reuses its helpers
# instead of re-implementing them. `pyproject.toml`'s `pythonpath = ["src"]` applies
# to pytest alone.
_lib.bootstrap()

import image as image_driver  # noqa: E402 - see the note above

from docflow.adapters.image import RasterEngine  # noqa: E402 - see the note above

__all__: list[str] = []

#: The resolution an image is brought to, read from the registry at run time
#: (`diagnosis.min_dpi`, `ADR-009`) rather than pinned here - the same source
#: `batch_pdf.py` uses, because the two drivers feed the same downstream stage and a
#: second number would make them disagree about what is readable.
MIN_DPI_KEY: Final[str] = "diagnosis.min_dpi"


@dataclasses.dataclass(frozen=True, slots=True)
class ImageOutcome:
    """What happened to one image.

    Attributes:
        source: The file's path relative to the input root - also its mirrored
            location in the output.
        width: The measured width, or ``0`` when `info` was refused.
        height: The measured height, or ``0`` when `info` was refused.
        format: The declared format, or ``""``.
        exif_orientation: The EXIF orientation tag's value, or ``None``.
        sharpness: The measured sharpness, or ``None`` when it was not measured.
        legibility: ``"ok"``, ``"illegible"``, or the reason code that stopped it.
        artifacts: The files written, relative to the output root.
        note: A short explanation, for the refused cases.
        source_dpi: The resolution the rescale was attempted against, or ``None``
            when neither a sidecar nor the caller supplied one.
        source_dpi_origin: Where that resolution came from - a recorded sidecar or
            the caller's assumption. Recorded because the two are **not** the same
            kind of fact, and a reader comparing two runs has to be able to tell
            which one decided whether the floor was reachable.

    """

    source: str
    width: int
    height: int
    format: str
    exif_orientation: int | None
    sharpness: float | None
    legibility: str
    artifacts: tuple[str, ...]
    note: str = ""
    source_dpi: int | None = None
    source_dpi_origin: str = ""

    @property
    def produced(self) -> int:
        """How many artifacts this image produced.

        Returns:
            The count. Zero is a real answer - an image can be measured, found
            illegible and written nowhere.

        """
        return len(self.artifacts)


#: Every image outcome of this walk, in order.
OUTCOMES: list[ImageOutcome] = []


def _engine() -> RasterEngine:
    """Build the K3 adapter.

    Returns:
        The engine, ready to call.

    """
    return image_driver._engine()


def _target_dpi() -> int:
    """Read the resolution images are brought to, from the registry.

    Returns:
        The corpus's declared minimum readable resolution.

    """
    return int(_lib.policy(MIN_DPI_KEY))


def describe_image(
    engine: RasterEngine, source: pathlib.Path
) -> tuple[int, int, str, int | None]:
    """Measure what the image is.

    Args:
        engine: The K3 adapter.
        source: The image to inspect.

    Returns:
        The width, height, format and EXIF orientation, each zeroed or emptied when
        `info` was refused - so a caller reads a refusal as *nothing measured*
        rather than as a plausible size.

    """
    measured = _mirror.silently(engine.info, source)
    if measured.value is None:
        return 0, 0, "", None

    observed = measured.evidence.observed
    orientation = observed.get("exif_orientation")
    return (
        int(observed.get("width", 0)),
        int(observed.get("height", 0)),
        str(observed.get("format", "")),
        None if orientation is None else int(orientation),
    )


def read_source_dpi(
    source: pathlib.Path, assumed_dpi: int | None
) -> tuple[int | None, str]:
    """Find the resolution the pixels hold: from a sidecar, or from the caller.

    **This closes the gap `--assumed-dpi` was papering over.** K3 cannot report a
    source resolution (`info` carries width, height, format and the EXIF orientation
    and no DPI at all), so this step could only ever be told one — and a number the
    caller asserts is an *assumption*, not a measurement. Meanwhile `batch_pdf.py`
    **measures** exactly this number to cap its render, and used to throw it away; it
    now writes both resolutions into `<stem>.pages.json`.

    So the search order is *measured, then assumed*, and the two are never confused:

    1. **A sibling sidecar that records `rendered_dpi`.** This is the measurement —
       the PNG beside it was written at that resolution, by a step that read it from
       the PDF rather than being told it.
    2. **The caller's `--assumed-dpi`.** An assumption, kept because a folder of
       images that never went through a PDF has no sidecar and no other way in.

    The sidecar **wins over the caller**, which is the opposite of the usual flag
    precedence and is deliberate: `--assumed-dpi` describes what the caller *believes*
    about a file, and a recorded measurement is knowledge. Letting a belief override
    a measurement is how a rescale gets refused for being below a floor it actually
    clears.

    Note what is read: **`rendered_dpi` and not `measured_dpi`.** The first is the
    resolution of *this* file — the artifact the next stage holds. The second is what
    the page's original pixels held, which is a fact about the PDF, not about the
    bitmap derived from it. They are equal whenever the render was capped by the
    page, and they diverge the moment the registry's floor is raised: a 120-DPI page
    rendered at 120 has both at 120, and one rendered at a higher floor would have
    `measured_dpi` 120 with a `rendered_dpi` above it — and it is the latter that
    describes the bytes on disk.

    Args:
        source: The image being processed.
        assumed_dpi: The resolution the caller asserts, or ``None``.

    Returns:
        The resolution, or ``None`` when neither a sidecar nor the caller supplied
        one, and a short note saying where it came from — recorded so a reader can
        tell a measurement from an assumption without re-deriving either.

    """
    recorded = _sidecar_dpi(source)
    if recorded is not None:
        return recorded, f"from the sidecar: {_sidecar_name(source)}"

    if assumed_dpi is not None:
        return assumed_dpi, "from --assumed-dpi (an assumption, not a measurement)"

    return None, "no sidecar and no --assumed-dpi"


def _sidecar_name(source: pathlib.Path) -> str:
    """Report the sidecar's name for one artifact, without touching the disk.

    The naming rule has two shapes because the two producers write different names:
    `batch_pdf.py` renders a page as ``<stem>-p<N>.png`` and records it in
    ``<document-stem>.pages.json``, so the document stem has to be recovered from the
    page artifact's. A file with no ``-pN`` suffix is its own stem.

    Args:
        source: The artifact.

    Returns:
        The sidecar's file name.

    """
    return f"{_document_stem(source)}.pages.json"


def _document_stem(source: pathlib.Path) -> str:
    """Recover the document's stem from a page artifact's name.

    ``66cd35e9-…-p3.png`` belongs to ``66cd35e9-….pages.json``. Recovering it matters
    because the page number is in the artifact's name and **not** in the sidecar's:
    one record covers every page of a document, so a walk needs the stem to find it
    and the page number to pick the right entry.

    Args:
        source: The artifact.

    Returns:
        The document's stem.

    """
    stem = source.stem
    _head, separator, tail = stem.rpartition("-p")
    if separator and tail.isdigit():
        return _head

    return stem


def _page_number(source: pathlib.Path) -> int | None:
    """Report which page of its document an artifact is, if its name says so.

    Args:
        source: The artifact.

    Returns:
        The one-based page number, or ``None`` when the name carries none - which is
        a legitimate answer for an image that never came from a PDF.

    """
    _head, separator, tail = source.stem.rpartition("-p")
    if separator and tail.isdigit():
        return int(tail)

    return None


def _sidecar_dpi(source: pathlib.Path) -> int | None:
    """Read the recorded render resolution for one artifact, if a sidecar has it.

    Never raises and never guesses: an absent file, unreadable JSON, a missing key or
    a null value all return ``None``, which the caller reports as *no measurement*.
    A malformed sidecar is not this driver's to diagnose — it would be reporting a
    defect in `batch_pdf.py`'s output from inside an image walk.

    Args:
        source: The artifact.

    Returns:
        The recorded resolution, or ``None``.

    """
    sidecar = source.parent / _sidecar_name(source)
    if not sidecar.is_file():
        return None

    try:
        record = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None

    entry = _page_entry(record, _page_number(source))
    if entry is None:
        return None

    recorded = entry.get("rendered_dpi")
    if not isinstance(recorded, int) or isinstance(recorded, bool):
        return None

    return recorded


def _page_entry(record: object, page: int | None) -> dict | None:
    """Find one page's entry in a pages record.

    A record with no usable ``pages`` list, or no entry for the page asked about,
    yields ``None``: the sidecar exists but does not answer this question, which is a
    different fact from *there is no sidecar* and is reported the same way — as *no
    measurement*.

    Args:
        record: The parsed sidecar.
        page: The one-based page number, or ``None`` for a single-page artifact.

    Returns:
        The entry, or ``None``.

    """
    if not isinstance(record, dict):
        return None

    pages = record.get("pages")
    if not isinstance(pages, list):
        return None

    entries = [entry for entry in pages if isinstance(entry, dict)]
    if page is None:
        return entries[0] if len(entries) == 1 else None

    for entry in entries:
        if entry.get("number") == page:
            return entry

    return None


def read_legibility(
    engine: RasterEngine, source: pathlib.Path
) -> tuple[float | None, str]:
    """Read the sharpness against the corpus's threshold.

    `illegible` is a **legitimate answer about the document**, not a failure of this
    walk (matrix row 7), so it is returned as a verdict rather than raised or
    filtered.

    Args:
        engine: The K3 adapter.
        source: The image to measure.

    Returns:
        The measured sharpness, and the verdict: ``"ok"``, ``"illegible"``, or the
        reason code that stopped the measurement. The sharpness is ``None`` only when
        nothing was measured.

    """
    attempt = _mirror.silently(
        image_driver.measure_legibility, engine, source, None, "ok"
    )

    sharpness: float | None = None
    if attempt.result is not None and attempt.result.evidence is not None:
        value = attempt.result.evidence.measurements.get("laplacian_variance")
        sharpness = None if value is None else float(value)

    if attempt.succeeded:
        return sharpness, "ok"
    reason = attempt.result.reason if attempt.result is not None else None
    return sharpness, (reason.code if reason is not None else "refused")


def bring_to_floor(
    engine: RasterEngine,
    source: pathlib.Path,
    mirror_dir: pathlib.Path,
    out_root: pathlib.Path,
    source_dpi: int | None,
    target_dpi: int,
    *,
    save: bool,
) -> tuple[str | None, str]:
    """Rescale the image to the corpus's floor, and say what happened either way.

    **The one thing this driver cannot measure.** `rescale` requires `source_dpi` and
    K3 reports no DPI at all, so the number has to come from somewhere else — a
    recorded sidecar when the artifact came through `batch_pdf.py`, or the caller's
    `--assumed-dpi` otherwise (see `read_source_dpi`). With neither, the step is
    **skipped and recorded**, never guessed: an invented source resolution is what
    decides whether the target is reachable, so a default here would either enlarge a
    scan or refuse a rescale that was possible - and it would do it while reporting a
    resolution nobody measured.

    An image whose resolution is **below** the floor is the case worth naming. The
    floor is a *minimum readable* resolution, so a 96-DPI image against a 150 floor
    cannot be brought up to it: the adapter refuses to upscale, and that refusal is
    right, because resampling cannot put information into pixels that were never
    sampled. The honest answer is *this image is below what the corpus considers
    readable, and no rescale will change that* - which is a finding about the corpus,
    and the reason `legibility` and the floor disagree. Reporting it as a silent
    absence of a file is exactly the failure this project exists to prevent.

    Args:
        engine: The K3 adapter.
        source: The image to rescale.
        mirror_dir: The directory the image mirrors into.
        out_root: The output root, for reporting relative paths.
        source_dpi: The resolution the caller asserts the pixels hold, or ``None``.
        target_dpi: The resolution to bring the image to.
        save: Whether to write the bitmap.

    Returns:
        The written file relative to the output root (or ``None``), and a note
        explaining a skip. The note is empty only when a file was written.

    """
    if source_dpi is None:
        return None, (
            "not rescaled: no sidecar recorded a resolution and no --assumed-dpi was "
            "given, and K3 cannot measure the DPI itself"
        )

    if source_dpi < target_dpi:
        return None, (
            f"below the floor: {source_dpi} < {target_dpi} declared readable, and "
            "upscaling is refused - resampling cannot add information"
        )

    attempt = _mirror.silently(
        image_driver.resize_by_dpi,
        engine,
        source,
        target_dpi,
        source_dpi,
        "ok",
        save=False,
    )
    if not attempt.succeeded:
        return None, f"rescale refused ({attempt.outcome.detail})"
    if not save:
        return None, "not written (--no-save)"

    target = mirror_dir / f"{source.stem}-dpi{target_dpi}.png"
    target.write_bytes(attempt.result.value.data)
    return _mirror.relative_to(target, out_root), ""


def cut_region(
    engine: RasterEngine,
    source: pathlib.Path,
    mirror_dir: pathlib.Path,
    out_root: pathlib.Path,
    region: str,
    *,
    save: bool,
) -> tuple[str | None, str]:
    """Cut a region out, when the caller named one.

    The region arrives **as a caller writes it** and is expanded by
    `image_driver.parse_region`, the one owner of that grammar - the same discipline
    `batch_pdf.py` follows for `--pages`. A crop carries its inverse map back to
    source coordinates (`NFR-07`), which is what lets a later stage point at the
    right area of the original.

    Args:
        engine: The K3 adapter.
        source: The image to crop.
        mirror_dir: The directory the image mirrors into.
        out_root: The output root, for reporting relative paths.
        region: The region as a caller writes it, ``x,y,w,h``.
        save: Whether to write the crop.

    Returns:
        The written file relative to the output root (or ``None``), and a note
        explaining a skip. A malformed region is the caller's own text and raises
        before anything is written.

    """
    attempt = _mirror.silently(
        image_driver.crop_region, engine, source, region, "ok", save=False
    )
    if not attempt.succeeded:
        return None, f"crop refused ({attempt.outcome.detail})"
    if not save:
        return None, "not written (--no-save)"

    observed = attempt.result.value.observed
    name = f"{source.stem}-crop-{image_driver.region_token(region)}.png"
    target = mirror_dir / name
    target.write_bytes(observed["image"].data)
    return _mirror.relative_to(target, out_root), ""


def process_image(
    engine: RasterEngine,
    source: pathlib.Path,
    root: pathlib.Path,
    out_root: pathlib.Path,
    *,
    region: str | None,
    target_dpi: int,
    assumed_dpi: int | None,
    save: bool,
) -> ImageOutcome:
    """Measure one image, gate it, and write what §2 asks for.

    Args:
        engine: The K3 adapter.
        source: The image to process.
        root: The input root.
        out_root: The output root.
        region: A region to crop, in the ``x,y,w,h`` grammar, or ``None`` for none.
        target_dpi: The resolution to bring the image to.
        assumed_dpi: The resolution the caller asserts the pixels hold, or ``None``.
        save: Whether to write any artifact.

    Returns:
        What happened to the image.

    """
    relative = _mirror.relative_to(source, root)
    mirror_dir = out_root / pathlib.Path(relative).parent
    mirror_dir.mkdir(parents=True, exist_ok=True)

    width, height, image_format, orientation = describe_image(engine, source)
    if width == 0 and height == 0:
        note = "info refused, so no size could be measured"
        _mirror.write_skipped(mirror_dir, source.stem, "image", note)
        return ImageOutcome(relative, 0, 0, "", None, None, "refused", (), note)

    sharpness, legibility = read_legibility(engine, source)

    # Where the source resolution comes from, and why the order matters. See
    # `read_source_dpi`: a **recorded** resolution beats a caller's assumption, so an
    # artifact that came through `batch_pdf.py` is rescaled against a measurement
    # rather than against a belief about it. That is the whole reason item 1 recorded
    # `rendered_dpi` in the sidecar.
    source_dpi, dpi_origin = read_source_dpi(source, assumed_dpi)

    artifacts: list[str] = []
    notes: list[str] = []
    if not save:
        return ImageOutcome(
            relative,
            width,
            height,
            image_format,
            orientation,
            sharpness,
            legibility,
            (),
            "not written (--no-save)",
        )

    scaled, scale_note = bring_to_floor(
        engine, source, mirror_dir, out_root, source_dpi, target_dpi, save=save
    )
    if scaled is not None:
        artifacts.append(scaled)
    if scale_note:
        notes.append(scale_note)

    if region is not None:
        try:
            cropped, crop_note = cut_region(
                engine, source, mirror_dir, out_root, region, save=save
            )
        except ValueError as exc:
            # The caller's own region text is malformed. It is a refusal, not a
            # defect, and it must not take the rest of the walk with it.
            _mirror.write_skipped(mirror_dir, source.stem, "image", str(exc))
            return ImageOutcome(
                relative,
                width,
                height,
                image_format,
                orientation,
                sharpness,
                legibility,
                tuple(artifacts),
                f"bad --region: {exc}",
            )
        if cropped is not None:
            artifacts.append(cropped)
        if crop_note:
            notes.append(crop_note)

    outcome = ImageOutcome(
        relative,
        width,
        height,
        image_format,
        orientation,
        sharpness,
        legibility,
        tuple(artifacts),
        "; ".join(notes),
        source_dpi=source_dpi,
        source_dpi_origin=dpi_origin,
    )
    _write_image_record(outcome, mirror_dir, source.stem)
    return outcome


def _write_image_record(
    outcome: ImageOutcome, mirror_dir: pathlib.Path, stem: str
) -> pathlib.Path:
    """Record what the image turned out to be.

    The artifacts alone say *a rescaled bitmap exists*; they do not say that the
    source was 2200x2700, that its sharpness was 0.66, or that no rescale happened
    because the resolution could not be measured. The record makes the census a file
    a pipeline can read instead of a console line that scrolls away.

    It is named `<stem>.image.json` and not `<stem>.json`: that name means *these are
    the extracted fields* (`batch.py`'s contract), and a consumer globbing for `.json`
    would read a measurement record as an extraction.

    Args:
        outcome: The image's outcome.
        mirror_dir: The directory the image mirrors into.
        stem: The image's stem.

    Returns:
        The path written.

    """
    # The two facts about the resolution travel beside the legibility reading, and for
    # the same reason: `legibility` without the threshold it was judged against is a
    # verdict a reader cannot check, and `source_dpi` without its origin is a number
    # indistinguishable from a guess.
    record = {
        "source": outcome.source,
        "width": outcome.width,
        "height": outcome.height,
        "format": outcome.format,
        "exif_orientation": outcome.exif_orientation,
        "sharpness": outcome.sharpness,
        "legibility": outcome.legibility,
        "source_dpi": outcome.source_dpi,
        "source_dpi_origin": outcome.source_dpi_origin,
        "artifacts": list(outcome.artifacts),
        "note": outcome.note,
    }
    target = mirror_dir / f"{stem}.image.json"
    target.write_text(
        json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return target


def process_file(
    engine: RasterEngine,
    source: pathlib.Path,
    root: pathlib.Path,
    out_root: pathlib.Path,
    *,
    region: str | None,
    target_dpi: int,
    assumed_dpi: int | None,
    save: bool,
) -> ImageOutcome | None:
    """Process one input file, or report that it is not an image.

    Args:
        engine: The K3 adapter.
        source: The file to process.
        root: The input root.
        out_root: The output root.
        region: A region to crop, or ``None``.
        target_dpi: The resolution to bring the image to.
        assumed_dpi: The resolution the caller asserts the pixels hold, or ``None``.
        save: Whether to write any artifact.

    Returns:
        The image's outcome, or ``None`` when the file is not an image - this driver
        is image-only by name, and a PDF is *not walked* rather than
        skipped-with-a-record, because the caller chose this driver's scope.

    """
    if _mirror.kind_of(source) != "image":
        return None
    return process_image(
        engine,
        source,
        root,
        out_root,
        region=region,
        target_dpi=target_dpi,
        assumed_dpi=assumed_dpi,
        save=save,
    )


def main(argv: list[str] | None = None) -> int:
    """Walk a folder of images, measure and gate every one, and verify the mirror.

    Args:
        argv: The command-line arguments, or ``None`` for `sys.argv`.

    Returns:
        The number of problems: mirrored-ness violations plus refused images.

    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("input", type=pathlib.Path, help="the folder to walk")
    parser.add_argument(
        "--out",
        type=pathlib.Path,
        default=None,
        help="the output root (default: var/poc/batch_image)",
    )
    parser.add_argument(
        "--region",
        default=None,
        help="a region to crop from every image, as x,y,w,h (default: none)",
    )
    parser.add_argument(
        "--target-dpi",
        type=int,
        default=None,
        help=f"the resolution to bring images to (default: {MIN_DPI_KEY} from the registry)",
    )
    parser.add_argument(
        "--assumed-dpi",
        type=int,
        default=None,
        help=(
            "the resolution the images are assumed to hold; without it no rescale "
            "runs, because K3 cannot measure a DPI"
        ),
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="measure and gate without writing any artifact",
    )
    args = parser.parse_args(argv)

    root: pathlib.Path = args.input
    if not root.is_dir():
        parser.error(f"{root} is not a directory")

    out_root = args.out if args.out is not None else _lib.DEFAULT_OUT / "batch_image"
    save = not args.no_save
    _lib.set_out(out_root)
    _lib.reset()

    target_dpi = args.target_dpi if args.target_dpi is not None else _target_dpi()

    # The tree first, so a directory that holds no file still exists in the output
    # and the mirror is complete even if the walk finds nothing (`S3-T06`).
    directories = _mirror.mirror_directories(root, out_root)
    engine = _engine()

    threshold = image_driver.policy_threshold()
    print(f"in  = {root}")
    print(f"out = {out_root}")
    print(f"threshold = {threshold} (registry: image.legibility_threshold)")
    print(
        f"target-dpi = {target_dpi} "
        f"({'given' if args.target_dpi is not None else f'registry: {MIN_DPI_KEY}'})"
    )
    assumed = (
        f"{args.assumed_dpi} (given, a fallback for images with no sidecar)"
        if args.assumed_dpi is not None
        else "not given -> only sidecar-recorded resolutions will be used"
    )
    print(f"assumed-dpi = {assumed}")
    print(f"region = {args.region or 'none'}    save = {save}")
    print()

    files = list(_mirror.walk(root))
    images = [path for path in files if _mirror.kind_of(path) == "image"]
    for source in files:
        outcome = process_file(
            engine,
            source,
            root,
            out_root,
            region=args.region,
            target_dpi=target_dpi,
            assumed_dpi=args.assumed_dpi,
            save=save,
        )
        if outcome is None:
            continue
        OUTCOMES.append(outcome)

        size = f"{outcome.width}x{outcome.height}" if outcome.width else "unmeasured"
        sharp = f"{outcome.sharpness:.4f}" if outcome.sharpness is not None else "none"
        if outcome.note.startswith("bad --region"):
            print(f" -- {outcome.source:44} {size:>11} {outcome.note}")
        else:
            print(
                f" ok {outcome.source:44} {size:>11} {outcome.format:>5} "
                f"sharpness={sharp:>9} {outcome.legibility:>10} "
                f"wrote {outcome.produced}"
            )
            if outcome.note:
                # A skip is printed rather than left in the record alone: the
                # operator watching the run is the one who can act on it, and a
                # step that silently did nothing is the failure this bench exists
                # to expose.
                print(f"      {outcome.note}")

    print()
    print("=== the mirror")
    # Only the files this driver walks: a `.pdf` in the input tree is outside an
    # image-only driver's scope, and reporting it as a violation would blame this run
    # for a file it was never asked about.
    problems = _mirror.verify_mirror_for(root, out_root, images)
    if not problems:
        print(
            f" ok {len(images)} image(s) and {directories} director(ies) mirrored "
            "at the same relative paths"
        )
    for problem in problems:
        print(f" !! {problem}")

    print()
    print(f"{'legibility':<14}{'images':>7}")
    census: dict[str, int] = {}
    for outcome in OUTCOMES:
        census[outcome.legibility] = census.get(outcome.legibility, 0) + 1
    for key in sorted(census):
        print(f"{key:<14}{census[key]:>7}")
    if not census:
        print(f"{'(none)':<14}{0:>7}")

    written = sum(outcome.produced for outcome in OUTCOMES)
    print(f"{'written':<14}{written:>7}")
    print()

    # An image that answered *illegible* was measured successfully and answered the
    # question - matrix row 7 - so it is not a problem. Only a refusal is, which is
    # the same distinction the reporting contract draws between a `reason` and a
    # `defect`.
    refused = [
        outcome for outcome in OUTCOMES if outcome.legibility not in {"ok", "illegible"}
    ]
    illegible = [o for o in OUTCOMES if o.legibility == "illegible"]
    below = [o for o in OUTCOMES if o.note.startswith("below the floor")]
    print(f"{len(images)} image(s) walked, {written} artifact(s) written.")
    if illegible:
        print(f"{len(illegible)} image(s) measured illegible.")
    if below:
        # Not a refusal and not a defect: a finding about the corpus, recorded so
        # that *no rescaled file* is never mistaken for *nothing to do*.
        print(
            f"{len(below)} image(s) are below the declared floor and were not "
            "rescaled - upscaling cannot add information."
        )
    if refused:
        print(f"{len(refused)} image(s) produced no measurement; see the notes above.")
    if not problems and not refused:
        print("every image was walked and the tree mirrors exactly.")
        return 0
    return len(problems) + len(refused)


if __name__ == "__main__":
    sys.exit(main())
