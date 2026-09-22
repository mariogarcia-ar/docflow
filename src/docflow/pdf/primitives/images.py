"""Embedded image primitives — the pictures physically stored inside a page.

Owned by ``PDF-07``. A page with no embedded images is valid data, not a failure: many
text-dominant pages contain none, and reporting that as an error would make the processor
lie about the document.

Identifiers are zero-padded and assigned in the engine's order, so a re-run over the same
bytes publishes the same names in the same order — the determinism class
``subplan-procesador-pdf.md`` §3 declares for this processor.

Six facts about the engine shape this module, each verified against Poppler 25.02.0 rather
than assumed:

* **``pdfimages`` cannot report where an image sits.** There is no ``-list`` position
  column and no flag that adds one — the full ``-h`` output has no geometry option at all.
  So :func:`get_image_blocks` cannot answer ``bbox`` from this engine: it returns the
  documented ``None``, which is what ``TextBlock.bbox``'s optionality exists for. Filling in
  zeroes would place every image at the page origin and silently corrupt the coverage
  arithmetic ``PDF-08`` builds on top.
* **``pdfimages`` extracts more files than there are images.** It also writes soft masks
  (``smask``) and hard masks (``mask``), which are pieces of another image rather than
  pictures in their own right. The ``-list`` output marks each row's ``type``, so the list is
  the authority on which artifacts are images; the files are then paired to it by position.
* A page with **no** images exits 0 and writes nothing, and so does a page whose range simply
  holds none. An empty result is data.
* **A zero bound processes the whole document** — the fifth tool here with that hazard, after
  ``pdfseparate``, ``pdftoppm``, ``pdftotext`` and ``pdfinfo`` — so the shared seam guard runs
  here too.
* ``-f 99 -l 99`` past the end exits 99 and writes nothing.
* **The output prefix is not a filename.** Files are named ``<prefix>-NNN.<ext>``, so the
  prefix is a stem and the extension follows from the chosen format.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from docflow.pdf.contracts import EmbeddedImage
from docflow.pdf.primitives.engine import (
    PopplerCommand,
    page_range_arguments,
    require_positive_page_range,
)
from docflow.pdf.primitives.failures import classify_image_failure, run_classified
from docflow.pdf.primitives.naming import image_index_name

IMAGE_TYPE = "image"
"""The ``-list`` type that denotes a picture.

The other types it emits — ``smask`` and ``mask`` — are a soft or hard mask belonging to
another image. They are extracted by the engine as separate files, so they have to be
excluded explicitly rather than assumed absent.
"""

POINTS_PER_INCH = 72.0
"""PDF points in an inch. The unit every geometry in this processor is expressed in."""

LIST_HEADER_ROWS = 2
"""``pdfimages -list`` prints a column header and a rule before the data rows."""

_MIN_LIST_COLUMNS = 15
"""Columns in a data row: page, num, type, width, height, color, comp, bpc, enc, interp,
object, ID, x-ppi, y-ppi, size, ratio. The last two are merged when the size column is
narrow, so a row is accepted at fifteen and parsed from the front."""

_IMAGE_FILENAME = re.compile(r"^(?P<stem>.+)-(?P<index>\d+)\.(?P<extension>\w+)$")


@dataclass(frozen=True)
class EmbeddedImageRecord:
    """One row of ``pdfimages -list``, as data.

    Not a contract type: it carries engine vocabulary (``enc``, ``interp``, ``object``) that
    belongs to this package. :func:`as_embedded_image` maps it onto the contract.

    Attributes:
        page_number: Page the image belongs to.
        index: The engine's own per-document image index.
        image_type: ``image``, ``smask`` or ``mask``.
        width: Pixel width.
        height: Pixel height.
        x_ppi: Horizontal resolution in pixels per inch that the engine reports.
        y_ppi: Vertical resolution in pixels per inch.
        color: Colour space name.
        encoding: Encoding name.
        size: Size string as printed, e.g. ``"11.5K"``.
    """

    page_number: int
    index: int
    image_type: str
    width: int
    height: int
    x_ppi: float
    y_ppi: float
    color: str
    encoding: str
    size: str

    def size_in_points(self) -> tuple[float, float]:
        """Return the image's drawn size in PDF points.

        The engine reports no geometry, but it does report the resolution the image is
        placed at, and ``pixels / ppi * 72`` is the size on the page. Verified against
        ``pdftohtml -zoom 1``, which reports the same rectangles independently — the two
        engines agreeing is what makes this a measurement rather than an inference.

        Returns:
            The ``(width, height)`` in points. Falls back to the pixel count when a
            resolution is missing or zero, which is the case for some colour spaces: a
            zero would make the area silently infinite, which is worse than an
            approximation that is documented.
        """
        if self.x_ppi <= 0 or self.y_ppi <= 0:
            return (float(self.width), float(self.height))
        return (
            self.width / self.x_ppi * POINTS_PER_INCH,
            self.height / self.y_ppi * POINTS_PER_INCH,
        )

    def area_in_points(self) -> float:
        """Return the image's drawn area in square PDF points."""
        width, height = self.size_in_points()
        return width * height


def parse_image_list(output: str) -> list[EmbeddedImageRecord]:
    """Parse ``pdfimages -list`` output into records.

    Args:
        output: The command's standard output.

    Returns:
        One record per listed image, in the engine's order, masks included. Rows that do not
        have enough columns to be data are skipped, which is how the header and the rule are
        dropped without matching their text.

    Raises:
        ValueError: A row had enough columns but a field that should be numeric was not.
            Raised rather than skipped: a row that looks like data and does not parse means
            the output shape changed, and quietly dropping it would under-report images.
    """
    records: list[EmbeddedImageRecord] = []

    for line in output.splitlines()[LIST_HEADER_ROWS:]:
        fields = line.split()
        if len(fields) < _MIN_LIST_COLUMNS:
            continue
        page_number, index, image_type, width, height, color, encoding = fields[:7]
        try:
            records.append(
                EmbeddedImageRecord(
                    page_number=int(page_number),
                    index=int(index),
                    image_type=image_type,
                    width=int(width),
                    height=int(height),
                    x_ppi=float(fields[12]),
                    y_ppi=float(fields[13]),
                    color=color,
                    encoding=encoding,
                    size=fields[-2],
                )
            )
        except ValueError as failure:
            raise ValueError(f"unreadable pdfimages row: {line!r}") from failure

    return records


def embedded_image_records(
    pdf_path: Path, page_number: int
) -> list[EmbeddedImageRecord]:
    """List the images of one page.

    Args:
        pdf_path: Source PDF. Read only.
        page_number: Page index, 1-based.

    Returns:
        One record per image on the page, masks included, in the engine's order.

    Raises:
        ValueError: ``page_number`` is below 1.
        PDFPrimitiveError: The document is unreadable, or the page does not exist.
    """
    require_positive_page_range((page_number, page_number))

    output = run_classified(
        PopplerCommand.PDFIMAGES,
        [
            "-list",
            *page_range_arguments((page_number, page_number), pdf_path),
        ],
        pdf_path,
        page_number=page_number,
    )

    # The engine accepts a range that starts before the page and reports every page it
    # covers, so the page column is filtered rather than trusted to match the request.
    return [
        record
        for record in parse_image_list(output)
        if record.page_number == page_number
    ]


def as_embedded_image(record: EmbeddedImageRecord) -> EmbeddedImage:
    """Map an engine record onto the processor's contract type.

    Args:
        record: The engine's row.

    Returns:
        The contract record, carrying the engine's own attributes in ``metadata`` and no
        path: the artifact's location is only known once it has been written.
    """
    return EmbeddedImage(
        image_id=image_index_name(record.index),
        path=Path(),
        # `pdfimages` reports no geometry at all, so there is nothing to report here.
        bbox=None,
        width=record.width,
        height=record.height,
        format=record.encoding,
        metadata={
            "engine_index": str(record.index),
            "engine_type": record.image_type,
            "color": record.color,
            "engine_size": record.size,
            # The resolution is what makes the image's drawn area computable at all, since
            # the engine reports no rectangle. Kept on the contract record so `PDF-08` can
            # measure coverage without going back to the engine.
            "x_ppi": str(record.x_ppi),
            "y_ppi": str(record.y_ppi),
        },
    )


def extract_images_from_page(
    pdf_path: Path,
    page_number: int,
    output_dir: Path,
) -> list[EmbeddedImage]:
    """Write every image embedded in one page, with stable zero-padded names.

    Args:
        pdf_path: Source PDF. Read only.
        page_number: Page index, 1-based.
        output_dir: Directory for the extracted images (``embedded_images/``). Created if
            absent; the engine does not create it.

    Returns:
        One record per extracted image, in the engine's order, each pointing at
        ``image_001.png``, ``image_002.png``, … Returns an empty list when the page embeds
        no image — a measurement, not a failure.

    Raises:
        ValueError: ``page_number`` is below 1, or the engine's listing and the files it
            wrote cannot be reconciled.
        PDFPrimitiveError: The document is unreadable, or the page does not exist.
    """
    require_positive_page_range((page_number, page_number))

    images = [
        record
        for record in embedded_image_records(pdf_path, page_number)
        if record.image_type == IMAGE_TYPE
    ]
    if not images:
        # Nothing to extract. Returning before the output directory is created keeps an
        # image-free page from publishing an empty ``embedded_images/`` namespace, which
        # would claim the page had images that produced nothing. The listing is what decides
        # this, so the check happens before any directory exists.
        return []

    output_dir.mkdir(parents=True, exist_ok=True)

    prefix = output_dir / "_staged"
    run_classified(
        PopplerCommand.PDFIMAGES,
        [
            "-png",
            *page_range_arguments((page_number, page_number), pdf_path),
            str(prefix),
        ],
        pdf_path,
        page_number=page_number,
    )

    try:
        return _publish_images(output_dir, prefix, images)
    except (OSError, ValueError) as failure:
        # Nothing is published until every rename has happened, so a failure in the publish
        # step leaves the engine's staged files behind. They are removed before the failure
        # is reported: a residue in a published namespace is a file a later stage would read
        # as an artifact, and `PDF-12`'s acceptance criterion is that an interrupted run
        # leaves neither a final-named artifact nor a staged one.
        _discard_staged(output_dir, prefix)
        # Typed as an image failure rather than a document failure: the page parsed well
        # enough to be listed, so its render and its text are unaffected and `PDF-09` can
        # keep the page.
        raise classify_image_failure(
            pdf_path, failure, page_number=page_number
        ) from failure


def _discard_staged(output_dir: Path, prefix: Path) -> None:
    """Remove the engine's staged files, ignoring their absence.

    Args:
        output_dir: The directory the engine wrote into.
        prefix: The stem the engine was given.
    """
    for path in output_dir.glob(f"{prefix.name}-*"):
        path.unlink(missing_ok=True)


def _publish_images(
    output_dir: Path,
    prefix: Path,
    images: list[EmbeddedImageRecord],
) -> list[EmbeddedImage]:
    """Rename the staged files onto their published names and pair them with records.

    Args:
        output_dir: The ``embedded_images/`` directory.
        prefix: The stem the engine was given.
        images: The image records, in the engine's order, masks already excluded.

    Returns:
        The published records, in order, each carrying its real path.

    Raises:
        ValueError: The engine wrote a different number of files than were listed. Raised
            rather than tolerated because the pairing is positional: a missing file would
            misalign every record after it and attach the wrong path to the wrong image.
    """
    written = _ordered_staged_files(output_dir, prefix, images)
    if len(written) != len(images):
        raise ValueError(
            f"pdfimages wrote {len(written)} file(s) for {len(images)} listed image(s)"
        )

    published: list[EmbeddedImage] = []
    for position, (record, staged_path) in enumerate(
        zip(images, written, strict=True), start=1
    ):
        target = output_dir / f"{image_index_name(position)}.png"
        staged_path.replace(target)
        published.append(_with_path(as_embedded_image(record), target, position))

    return published


def _ordered_staged_files(
    output_dir: Path,
    prefix: Path,
    images: list[EmbeddedImageRecord],
) -> list[Path]:
    """Return the staged files that correspond to the listed images.

    Selection is by the engine's **index**, not by file order. The engine writes one file per
    ``-list`` row, masks included, so a page with three images and two masks produces five
    files; the indices in the listing say which files are the images. An earlier version of
    this function paired files to records by position, which failed on the first document
    tried — the mask files shift every record after them, silently attaching the wrong path
    to the wrong image had the counts happened to match.

    Args:
        output_dir: The directory the engine wrote into.
        prefix: The stem the engine was given.
        images: The image records, in the engine's order, masks already excluded.

    Returns:
        The matching paths, ordered by the images' own order.

    Raises:
        ValueError: A listed image has no file. Raised rather than skipped, because a
            missing file means the pairing cannot be trusted at all.
    """
    by_index: dict[int, Path] = {}
    for path in output_dir.glob(f"{prefix.name}-*"):
        if not path.is_file():
            continue
        found = _IMAGE_FILENAME.match(path.name)
        if found is not None:
            by_index[int(found.group("index"))] = path

    missing = [record.index for record in images if record.index not in by_index]
    if missing:
        raise ValueError(f"pdfimages wrote no file for image index(es) {missing}")

    # Every staged file that is not one of the kept images is a mask belonging to one of
    # them. Removing them here is what keeps the published directory to the artifacts the
    # records actually point at — `PDF-09` treats every file under this namespace as a page
    # artifact, so a leftover mask would be published as an image of its own.
    for index, path in by_index.items():
        if index not in {record.index for record in images}:
            path.unlink()

    return [by_index[record.index] for record in images]


def _with_path(record: EmbeddedImage, path: Path, index: int) -> EmbeddedImage:
    """Return the record with its artifact path and published identifier filled in.

    Args:
        record: The record built from the engine's listing.
        path: Where the artifact was published.
        index: The record's position among the published images, 1-based.

    Returns:
        A new record. The contract type is frozen, so this is a replacement rather than a
        mutation.
    """
    return EmbeddedImage(
        image_id=image_index_name(index),
        path=path,
        bbox=record.bbox,
        width=record.width,
        height=record.height,
        format=record.format,
        metadata=record.metadata,
    )


def get_image_blocks(pdf_path: Path, page_number: int) -> list[EmbeddedImage]:
    """Report the images embedded in a page, with their size and engine attributes.

    **``bbox`` is always ``None``, and that is a limitation of the engine rather than of this
    function.** ``pdfimages`` exposes no geometry: it has no position column in ``-list`` and
    no flag that adds one, so there is no honest value to report. ``subplan-procesador-pdf.md``
    §3 leaves ``bbox`` optional for exactly this case, and ``PDF-08`` must therefore compute
    ``image_coverage`` from something other than image placement.

    Args:
        pdf_path: Source PDF. Read only.
        page_number: Page index, 1-based.

    Returns:
        One record per embedded image, in the engine's order. Empty when the page embeds no
        image.

    Raises:
        ValueError: ``page_number`` is below 1.
        PDFPrimitiveError: The document is unreadable, or the page does not exist.
    """
    return [
        as_embedded_image(record)
        for record in embedded_image_records(pdf_path, page_number)
        if record.image_type == IMAGE_TYPE
    ]


__all__ = [
    "IMAGE_TYPE",
    "POINTS_PER_INCH",
    "EmbeddedImageRecord",
    "as_embedded_image",
    "embedded_image_records",
    "extract_images_from_page",
    "get_image_blocks",
    "parse_image_list",
]
