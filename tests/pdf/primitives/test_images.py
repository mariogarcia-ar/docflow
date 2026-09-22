"""Tests for the embedded-image primitives (``PDF-07``).

Three committed fixtures carry the three answers this task has to keep apart:

* ``pdf_aptos_layout/36744cc6-…pdf`` — a page with three images **and two masks**, which is
  the case that breaks a naive extraction.
* ``matrix/scan150.pdf`` — a single full-page scan.
* ``matrix/three-invoices.pdf`` — a text page with **no** embedded image at all.

The first is the important one: ``pdfimages`` writes a file per ``-list`` row, so a page
whose images have masks yields more files than images.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from docflow.pdf.primitives.failures import PDFPrimitiveError, classify_image_failure
from docflow.pdf.primitives.images import (
    IMAGE_TYPE,
    EmbeddedImageRecord,
    as_embedded_image,
    embedded_image_records,
    extract_images_from_page,
    get_image_blocks,
    parse_image_list,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
MASKED_PDF = FIXTURES / "pdf_aptos_layout" / "36744cc6-2ed9-47e5-b4b8-66c31768164b.pdf"
SCAN_PDF = FIXTURES / "matrix" / "scan150.pdf"
NO_IMAGE_PDF = FIXTURES / "matrix" / "three-invoices.pdf"

MASKED_PAGE = 1
MASKED_IMAGE_COUNT = 3
MASKED_MASK_COUNT = 2


@pytest.fixture(name="masked_pdf")
def masked_pdf_fixture() -> Path:
    """Return the fixture whose page has images with soft and hard masks."""
    assert MASKED_PDF.exists(), f"missing fixture: {MASKED_PDF}"
    return MASKED_PDF


@pytest.fixture(name="scan_pdf")
def scan_pdf_fixture() -> Path:
    """Return the fixture whose page is a single full-page scan."""
    assert SCAN_PDF.exists(), f"missing fixture: {SCAN_PDF}"
    return SCAN_PDF


@pytest.fixture(name="no_image_pdf")
def no_image_pdf_fixture() -> Path:
    """Return the fixture whose page carries a text layer and no embedded image."""
    assert NO_IMAGE_PDF.exists(), f"missing fixture: {NO_IMAGE_PDF}"
    return NO_IMAGE_PDF


def test_the_listing_separates_images_from_their_masks(masked_pdf: Path) -> None:
    """The engine's listing names each row's type, and masks are not images.

    This is the fact the whole module is shaped around: a page with three images and two
    masks is reported as five rows, and only three of them are pictures.

    Mutation that breaks it: drop the ``image_type == IMAGE_TYPE`` filter. The count becomes
    five and every assertion below fails.
    """
    records = embedded_image_records(masked_pdf, MASKED_PAGE)

    types = [record.image_type for record in records]
    assert types.count(IMAGE_TYPE) == MASKED_IMAGE_COUNT
    assert len(records) == MASKED_IMAGE_COUNT + MASKED_MASK_COUNT
    assert set(types) == {"image", "smask", "mask"}


def test_extraction_returns_exactly_the_images_not_the_masks(
    masked_pdf: Path, tmp_path: Path
) -> None:
    """The returned records are the images, and each one points at a real file."""
    images = extract_images_from_page(masked_pdf, MASKED_PAGE, tmp_path)

    assert len(images) == MASKED_IMAGE_COUNT
    for image in images:
        assert image.path.exists()
        assert image.path.stat().st_size > 0
        assert image.metadata["engine_type"] == IMAGE_TYPE

    assert [image.image_id for image in images] == [
        f"image_{index:03d}" for index in range(1, MASKED_IMAGE_COUNT + 1)
    ]


def test_no_mask_file_is_left_in_the_published_directory(
    masked_pdf: Path, tmp_path: Path
) -> None:
    """The mask files the engine wrote are removed, not published.

    ``PDF-09`` treats every file under the page's ``embedded_images/`` namespace as an
    artifact of that page, so a leftover mask becomes an image of its own — one the records
    do not describe. Mutation that breaks it: remove the cleanup loop in
    ``_ordered_staged_files``. Two ``_staged-*`` files survive and this assertion fails.
    """
    published = tmp_path / "embedded_images"

    images = extract_images_from_page(masked_pdf, MASKED_PAGE, published)

    assert sorted(path.name for path in published.iterdir()) == sorted(
        image.path.name for image in images
    )
    assert not [path for path in published.iterdir() if "staged" in path.name]


def test_images_are_paired_by_the_engine_index_not_by_file_order(
    masked_pdf: Path, tmp_path: Path
) -> None:
    """Each record's path belongs to that record, not to its position in the file list.

    The engine interleaves masks with images, so a positional pairing attaches the wrong file
    to every record after the first mask. The dimensions are therefore checked against the
    listing rather than merely checked to exist.

    Mutation that breaks it: pair ``zip(images, sorted(files))`` instead of looking each
    record up by its engine index. On this fixture the first record then receives a mask's
    file and the dimensions stop matching.
    """
    records = [
        record
        for record in embedded_image_records(masked_pdf, MASKED_PAGE)
        if record.image_type == IMAGE_TYPE
    ]

    images = extract_images_from_page(masked_pdf, MASKED_PAGE, tmp_path)

    assert [image.metadata["engine_index"] for image in images] == [
        str(record.index) for record in records
    ]
    assert [(image.width, image.height) for image in images] == [
        (record.width, record.height) for record in records
    ]


def test_distinct_images_produce_distinct_files(
    masked_pdf: Path, tmp_path: Path
) -> None:
    """Three images are three different pictures, not one picture copied three times.

    A pairing bug that pointed every record at the same staged file would still satisfy an
    existence check, so the contents are compared.
    """
    images = extract_images_from_page(masked_pdf, MASKED_PAGE, tmp_path)

    digests = {hashlib.sha256(image.path.read_bytes()).hexdigest() for image in images}
    assert len(digests) == MASKED_IMAGE_COUNT


def test_a_scan_page_yields_its_one_image(scan_pdf: Path, tmp_path: Path) -> None:
    """A full-page scan is one image with a real pixel size."""
    images = extract_images_from_page(scan_pdf, 1, tmp_path)

    assert len(images) == 1
    assert images[0].width > 0
    assert images[0].height > 0
    assert images[0].path.exists()


def test_a_page_without_images_yields_an_empty_list(
    no_image_pdf: Path, tmp_path: Path
) -> None:
    """No embedded image is data, not a failure.

    Mutation that breaks it: raise when the listing is empty. The page is then lost instead
    of reported as a page that contains only text.

    An empty page also writes nothing: the module returns before invoking the engine, which
    keeps an image-free page from producing a stray artifact.
    """
    published = tmp_path / "embedded_images"

    images = extract_images_from_page(no_image_pdf, 1, published)

    assert not images
    assert not published.exists() or not list(published.iterdir())


def test_the_listing_of_an_image_free_page_is_empty(no_image_pdf: Path) -> None:
    """The engine exits 0 and lists nothing, which the parser reports as nothing."""
    assert not embedded_image_records(no_image_pdf, 1)


def test_bbox_is_absent_because_the_engine_reports_no_geometry(
    masked_pdf: Path,
) -> None:
    """``pdfimages`` cannot answer where an image sits, so the field is ``None``.

    It has no position column in ``-list`` and no flag that adds one. The honest answer is
    ``None``, which is why ``subplan-procesador-pdf.md`` §3 makes ``bbox`` optional; a zeroed
    box would place every image at the page origin and make the coverage arithmetic of
    ``PDF-08`` silently wrong.

    Mutation that breaks it: fill ``bbox`` with ``(0, 0, 0, 0)`` or a guess. The assertion
    fails, and the wrong placement starts propagating.
    """
    blocks = get_image_blocks(masked_pdf, MASKED_PAGE)

    assert blocks
    assert all(block.bbox is None for block in blocks)


def test_blocks_and_extraction_agree_on_what_the_page_contains(
    masked_pdf: Path, tmp_path: Path
) -> None:
    """The listing-only read and the extracting read describe the same images."""
    blocks = get_image_blocks(masked_pdf, MASKED_PAGE)
    extracted = extract_images_from_page(masked_pdf, MASKED_PAGE, tmp_path)

    assert len(blocks) == len(extracted)
    assert [(b.width, b.height) for b in blocks] == [
        (e.width, e.height) for e in extracted
    ]


def test_the_engine_attributes_are_kept_on_the_record(masked_pdf: Path) -> None:
    """What the engine reported about each image survives onto the contract type.

    These attributes are the only colour-space and encoding information available, since the
    engine reports no geometry; discarding them would leave nothing but a pixel count.
    """
    blocks = get_image_blocks(masked_pdf, MASKED_PAGE)

    for block in blocks:
        assert block.metadata["color"]
        assert block.metadata["engine_index"]
        assert block.metadata["engine_size"]
        assert block.format


def test_a_page_below_one_is_refused(masked_pdf: Path, tmp_path: Path) -> None:
    """Page 0 never reaches the engine, which would read it as 'no range'.

    ``pdfimages -f 0 -l 0`` extracts the whole document — the fifth tool in this package with
    that hazard — so a forwarded zero would silently publish another page's images.

    Mutation that breaks it: remove the ``require_positive_page_range`` calls from both entry
    points; the ``pytest.raises`` blocks fail.
    """
    for invalid in (0, -1):
        with pytest.raises(ValueError, match="1-based"):
            extract_images_from_page(masked_pdf, invalid, tmp_path / f"bad{invalid}")
        with pytest.raises(ValueError, match="1-based"):
            get_image_blocks(masked_pdf, invalid)


def test_a_page_past_the_end_is_a_typed_failure(masked_pdf: Path) -> None:
    """A page the document does not have is reported, not guessed at."""
    with pytest.raises(PDFPrimitiveError) as failure:
        get_image_blocks(masked_pdf, 99)

    assert failure.value.error_type == "PAGE_OUT_OF_RANGE"


def test_an_image_failure_is_recoverable(masked_pdf: Path) -> None:
    """A failure to extract images says the page can survive it.

    ``PDF-09`` needs this to keep the page: a failed image extraction leaves the render and
    the native text untouched, so the page is ``PARTIAL`` rather than lost.
    """
    failure = classify_image_failure(
        masked_pdf, ValueError("boom"), page_number=MASKED_PAGE
    )

    assert failure.error_type == "IMAGE_EXTRACTION_ERROR"
    assert failure.recoverable is True


def test_extraction_never_modifies_the_source(masked_pdf: Path, tmp_path: Path) -> None:
    """Reading and extracting is read-only for the document.

    The engine is given an output stem inside the caller's directory, so nothing is written
    beside the input — the mistake ``pdftohtml`` would have made had it been used here.
    """
    before = hashlib.sha256(masked_pdf.read_bytes()).hexdigest()
    before_tree = sorted(path.name for path in masked_pdf.parent.iterdir())

    extract_images_from_page(masked_pdf, MASKED_PAGE, tmp_path / "images")
    get_image_blocks(masked_pdf, MASKED_PAGE)

    assert hashlib.sha256(masked_pdf.read_bytes()).hexdigest() == before
    # Compared against the directory as it was, so the test reports its own pollution rather
    # than asserting an absolute that may already be false for unrelated reasons.
    assert sorted(path.name for path in masked_pdf.parent.iterdir()) == before_tree


def test_parsing_rejects_a_row_that_looks_like_data_but_is_not() -> None:
    """A malformed data row is an error, not a silently dropped image.

    Skipping it would under-report the page's images, which is worse than failing: the page
    would look complete while missing one.
    """
    header = (
        "page   num  type   width height color comp bpc  enc interp  object ID "
        "x-ppi y-ppi size ratio\n"
        "-------------------------------------------------------------------\n"
    )
    malformed = (
        header
        + "   1     0 image notanumber 32 rgb 3 8 image no 13 0 170 169 2513B 17%\n"
    )

    with pytest.raises(ValueError, match="unreadable pdfimages row"):
        parse_image_list(malformed)


def test_parsing_ignores_the_header_without_matching_its_text() -> None:
    """Header and rule are skipped by shape, so a renamed column cannot break the parse."""
    assert not parse_image_list("page num type\n----\n")


def test_the_record_maps_onto_the_contract_type() -> None:
    """The engine record converts with the engine's vocabulary tucked into metadata."""
    record = EmbeddedImageRecord(
        page_number=1,
        index=7,
        image_type=IMAGE_TYPE,
        width=10,
        height=20,
        x_ppi=72.0,
        y_ppi=72.0,
        color="rgb",
        encoding="image",
        size="1K",
    )

    image = as_embedded_image(record)

    assert image.image_id == "image_007"
    assert (image.width, image.height) == (10, 20)
    assert image.metadata["engine_index"] == "7"
    assert image.bbox is None


def test_the_drawn_size_is_derived_from_the_reported_resolution(
    masked_pdf: Path,
) -> None:
    """The image's size on the page comes from its pixels and its resolution.

    The engine reports no rectangle, but it does report the resolution the image is placed
    at, and ``pixels / ppi * 72`` gives the size in PDF points. Verified against
    ``pdftohtml -zoom 1``, which reports the rectangles independently — the two agreeing is
    what makes this a measurement rather than an inference.

    Mutation that breaks it: return the raw pixel count from ``size_in_points``. The first
    image is 150 x 32 px at 170 ppi, so the derived 63.5 x 13.6 pts become 150 x 32 and the
    assertion fails.
    """
    images = get_image_blocks(masked_pdf, MASKED_PAGE)

    first = images[0]
    assert first.metadata["x_ppi"] == "170.0"
    assert first.width / float(first.metadata["x_ppi"]) * 72 == pytest.approx(
        63.5, abs=0.1
    )


@pytest.mark.parametrize(
    ("pixels", "ppi", "expected_points"),
    [
        ((72, 72), (72.0, 72.0), (72.0, 72.0)),
        ((144, 144), (72.0, 72.0), (144.0, 144.0)),
    ],
)
def test_size_in_points_scales_with_resolution(
    pixels: tuple[int, int],
    ppi: tuple[float, float],
    expected_points: tuple[float, float],
) -> None:
    """Doubling the resolution halves the drawn size for the same pixel count."""
    record = EmbeddedImageRecord(
        page_number=1,
        index=0,
        image_type=IMAGE_TYPE,
        width=pixels[0],
        height=pixels[1],
        x_ppi=ppi[0],
        y_ppi=ppi[1],
        color="gray",
        encoding="image",
        size="1K",
    )

    assert record.size_in_points() == pytest.approx(expected_points)
    assert record.area_in_points() == pytest.approx(
        expected_points[0] * expected_points[1]
    )


def test_a_missing_resolution_does_not_produce_an_infinite_area() -> None:
    """A zero resolution falls back to the pixel count instead of dividing by zero.

    Some colour spaces report no resolution. Dividing by zero would be an exception; the
    fallback is an approximation, which is why it is documented rather than silent.
    """
    record = EmbeddedImageRecord(
        page_number=1,
        index=0,
        image_type=IMAGE_TYPE,
        width=50,
        height=40,
        x_ppi=0.0,
        y_ppi=0.0,
        color="gray",
        encoding="image",
        size="1K",
    )

    assert record.size_in_points() == (50.0, 40.0)
    assert record.area_in_points() == 2000.0
