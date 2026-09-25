"""Tests for the Poppler seam and the primitives that reach it (``PDF-02`` … ``PDF-08``).

Every assertion here is about **our** translation: the arguments we build, the artifacts we
name and order, the failures we type. Nothing asserts what Poppler returns, renders or
reports — the double answers with the CLI's own shape (``README.md`` §9.7).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from docflow.pdf.primitives import (
    ENGINE_NAME,
    PDFPrimitiveError,
    extract_images_from_page,
    extract_page,
    extract_text_from_page,
    inspect_pdf,
    merge_pdfs,
    poppler_version,
    render_page_to_image,
    split_pdf,
)
from tests.fakes.engines.fake_poppler import FakeImage, FakePage, FakePoppler
from tests.pdf.samples import (
    SAMPLE_IMAGE,
    SAMPLE_MIXED,
    SAMPLE_TEXT,
    image_document,
    mixed_document,
    text_document,
)


def calls_to(fake: FakePoppler, binary: str) -> list[list[str]]:
    """Return every call the seam made to one engine binary."""
    return [call for call in fake.calls if Path(call[0]).name == binary]


def sha256_of(path: Path) -> str:
    """Return the digest of a file, so a test can prove it was not rewritten."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


class _PageShyPoppler(FakePoppler):
    """A double whose inspection report counts more pages than it describes."""

    # pylint: disable=too-few-public-methods
    # Reason: a scripted double overrides one handler; its public surface is the parent's.

    def _document_info(self, argv: Sequence[str]) -> str:
        """Return a report with a page count and no per-page geometry."""
        del argv
        return "Title: broken\nPages: 3\n"


class _OverReportingPoppler(FakePoppler):
    """A double whose image report lists an image its extraction does not produce."""

    # pylint: disable=too-few-public-methods
    # Reason: a scripted double overrides one handler; its public surface is the parent's.

    def _images(self, argv: Sequence[str]) -> str:
        """Return the report with one row too many."""
        if "-list" in argv:
            return super()._images(argv) + (
                "   1     9 image      48    48  rgb     3   8  image  no        6  0"
                "    36    36   33B 0.5%\n"
            )
        return super()._images(argv)


def test_the_engine_is_named_and_its_version_comes_from_its_own_report(
    poppler: Callable[..., FakePoppler],
) -> None:
    """The seam reads the version rather than defaulting one."""
    fake = poppler(version="4.5.6-scripted")

    assert poppler_version() == "4.5.6-scripted"
    assert calls_to(fake, "pdfinfo") == [["pdfinfo", "-v"]]


def test_inspection_reads_the_count_and_the_geometry_from_one_call(
    poppler: Callable[..., FakePoppler],
) -> None:
    """``PDF-03``: one call, so the count and the geometry cannot disagree by accident."""
    fake = poppler(text_document())

    document = inspect_pdf(SAMPLE_TEXT)

    assert document.page_count == 3
    assert document.page_dimensions == [(612.0, 792.0)] * 3
    assert len(calls_to(fake, "pdfinfo")) == 1
    assert "-box" in fake.calls[0]


def test_a_report_that_counts_more_pages_than_it_describes_is_refused(
    poppler: Callable[..., FakePoppler],
) -> None:
    """An unmeasured page must not inherit a neighbour's geometry."""
    poppler(double=_PageShyPoppler())

    with pytest.raises(PDFPrimitiveError) as failure:
        inspect_pdf(SAMPLE_TEXT)

    assert failure.value.error.type == "INTERNAL_ERROR"
    assert failure.value.error.metadata["page_count"] == 3


def test_a_syntax_error_from_the_engine_is_a_corrupt_document(
    poppler: Callable[..., FakePoppler],
) -> None:
    """``PDF-03``: the engine's failure becomes a typed failure, not an exception."""
    poppler(text_document(), failures={"pdfinfo": (99, "Syntax Error: xref table")})

    with pytest.raises(PDFPrimitiveError) as failure:
        inspect_pdf(SAMPLE_TEXT)

    assert failure.value.error.type == "CORRUPTED_PDF"
    assert failure.value.error.recoverable is False


def test_a_missing_binary_is_an_unrecoverable_io_error(
    poppler: Callable[..., FakePoppler],
) -> None:
    """Absence surfaces at the call, because the engine is resolved at call time."""
    poppler(text_document(), raises={"pdfinfo": FileNotFoundError("no pdfinfo")})

    with pytest.raises(PDFPrimitiveError) as failure:
        inspect_pdf(SAMPLE_TEXT)

    assert failure.value.error.type == "IO_ERROR"
    assert failure.value.error.recoverable is False
    assert failure.value.error.metadata["binary"] == "pdfinfo"


def test_a_syntax_error_is_fatal_even_when_the_engine_exits_zero(
    poppler: Callable[..., FakePoppler],
) -> None:
    """A document the reader could not fully parse is never published as extracted."""
    poppler(text_document(), noise={"pdftotext": "Syntax Error: bad object"})

    with pytest.raises(PDFPrimitiveError) as failure:
        extract_text_from_page(SAMPLE_TEXT, 1)

    assert failure.value.error.type == "CORRUPTED_PDF"


def test_extract_page_publishes_one_page_and_never_touches_the_source(
    poppler: Callable[..., FakePoppler], tmp_path: Path
) -> None:
    """``PDF-04``: the source is immutable, and the artifact is the page we asked for."""
    fake = poppler(text_document())
    before = sha256_of(SAMPLE_TEXT)

    published = extract_page(SAMPLE_TEXT, 2, tmp_path / "source" / "page.pdf")

    assert published == tmp_path / "source" / "page.pdf"
    assert published.read_bytes().startswith(b"%PDF-")
    assert b"page 2" in published.read_bytes()
    assert sha256_of(SAMPLE_TEXT) == before
    argv = calls_to(fake, "pdfseparate")[0]
    assert argv[:5] == ["pdfseparate", "-f", "2", "-l", "2"]
    assert argv[5] == str(SAMPLE_TEXT)
    # The engine writes into a scratch pattern; the artifact name is ours, never its own.
    assert argv[6].endswith("page-%03d.pdf")


def test_split_publishes_one_file_per_page_in_page_order(
    poppler: Callable[..., FakePoppler], tmp_path: Path
) -> None:
    """``PDF-04``: our loop decides the count and the order, not a directory listing."""
    poppler(text_document())

    published = split_pdf(SAMPLE_TEXT, tmp_path / "split")

    assert [path.name for path in published] == [
        "page_001.pdf",
        "page_002.pdf",
        "page_003.pdf",
    ]
    assert [path.read_bytes().splitlines()[1] for path in published] == [
        b"% extracted page 1 of 3",
        b"% extracted page 2 of 3",
        b"% extracted page 3 of 3",
    ]


def test_merge_publishes_the_concatenation_in_the_given_order(
    poppler: Callable[..., FakePoppler], tmp_path: Path
) -> None:
    """``PDF-04``: the deferred utility still names its parts in order."""
    fake = poppler(text_document())
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    first.write_bytes(b"%PDF-1.7\n%%EOF\n")
    second.write_bytes(b"%PDF-1.7\n%%EOF\n")

    merged = merge_pdfs([first, second], tmp_path / "merged.pdf")

    assert b"first.pdf, second.pdf" in merged.read_bytes()
    # The engine merges into a scratch file; the published name is ours.
    assert calls_to(fake, "pdfunite")[0][-1].endswith("merged.pdf")
    assert str(first) in calls_to(fake, "pdfunite")[0]
    assert not list(tmp_path.rglob("*.tmp"))


def test_merge_refuses_to_run_without_a_document(
    poppler: Callable[..., FakePoppler], tmp_path: Path
) -> None:
    """An empty input list is a request that cannot be answered, not an empty output."""
    fake = poppler(text_document())

    with pytest.raises(PDFPrimitiveError) as failure:
        merge_pdfs([], tmp_path / "merged.pdf")

    assert failure.value.error.type == "INVALID_INPUT"
    assert fake.calls == []


def test_render_asks_for_png_and_the_requested_resolution(
    poppler: Callable[..., FakePoppler], tmp_path: Path
) -> None:
    """``PDF-05``: the dpi is ours to state, never the engine's default."""
    fake = poppler(text_document())
    output = tmp_path / "render" / "page.png"

    published = render_page_to_image(SAMPLE_TEXT, 2, output, dpi=150)

    assert published == output
    argv = calls_to(fake, "pdftoppm")[0]
    assert argv[1:4] == ["-png", "-r", "150"]
    assert argv[4:8] == ["-f", "2", "-l", "2"]
    assert "-singlefile" in argv
    assert published.read_bytes() == fake.renders[(2, 150)]


def test_render_refuses_a_resolution_that_is_not_positive(
    poppler: Callable[..., FakePoppler], tmp_path: Path
) -> None:
    """A nonsensical resolution is refused before the engine is asked anything."""
    fake = poppler(text_document())

    with pytest.raises(PDFPrimitiveError) as failure:
        render_page_to_image(SAMPLE_TEXT, 1, tmp_path / "page.png", dpi=0)

    assert failure.value.error.type == "INVALID_INPUT"
    assert fake.calls == []


def test_text_and_blocks_come_from_one_read(
    poppler: Callable[..., FakePoppler],
) -> None:
    """``PDF-06``: two artifacts from one read cannot describe two different reads."""
    fake = poppler(text_document())

    text, blocks = extract_text_from_page(SAMPLE_TEXT, 1)

    text_calls = calls_to(fake, "pdftotext")
    assert len(text_calls) == 1
    assert text_calls[0][1] == "-tsv"
    assert str(SAMPLE_TEXT) in text_calls[0]
    assert text_calls[0][-1] == "-"  # the text goes to stdout: one read, both artifacts
    assert text == "Page one of the text sample.\nSecond line of page one."
    assert [block.block_id for block in blocks] == ["block_001", "block_002"]
    assert [block.text for block in blocks] == text.splitlines()
    assert [(block.bbox is not None) for block in blocks] == [True, True]
    assert {block.page_number for block in blocks} == {1}


def test_dropping_the_layout_keeps_the_same_read(
    poppler: Callable[..., FakePoppler],
) -> None:
    """The blocks lose their boxes on request; the text still comes from that one read."""
    fake = poppler(text_document())

    text, blocks = extract_text_from_page(SAMPLE_TEXT, 1, layout=False)

    assert len(calls_to(fake, "pdftotext")) == 1
    assert text == "Page one of the text sample.\nSecond line of page one."
    assert [block.bbox for block in blocks] == [None, None]


def test_a_page_without_a_text_layer_reports_empty_text_as_data(
    poppler: Callable[..., FakePoppler],
) -> None:
    """``PDF-06``: an empty extraction is a fact about the page, not a failure."""
    poppler(image_document())

    text, blocks = extract_text_from_page(SAMPLE_IMAGE, 1)

    assert text == ""
    assert not blocks


def test_images_are_named_in_scan_order_with_the_engine_report(
    poppler: Callable[..., FakePoppler], tmp_path: Path
) -> None:
    """``PDF-07``: our names and our order, with the report's own attributes."""
    pages = [
        FakePage(
            images=(
                FakeImage(width=120, height=90, encoding="jpeg"),
                FakeImage(width=48, height=48, encoding="image"),
            )
        )
    ]
    poppler(pages)

    images = extract_images_from_page(SAMPLE_MIXED, 1, tmp_path / "embedded_images")

    assert [image.image_id for image in images] == ["image_001", "image_002"]
    assert [image.path.name for image in images] == ["image_001.png", "image_002.png"]
    assert [(image.width, image.height, image.format) for image in images] == [
        (120, 90, "jpeg"),
        (48, 48, "image"),
    ]
    assert all(image.bbox is None for image in images)
    assert images[0].metadata["color"] == "rgb"
    assert all(image.path.is_file() for image in images)


def test_a_page_without_embedded_images_reports_none_and_writes_nothing(
    poppler: Callable[..., FakePoppler], tmp_path: Path
) -> None:
    """``PDF-07``: no images is data; an empty directory is not created to say so."""
    poppler(text_document())
    output_dir = tmp_path / "embedded_images"

    images = extract_images_from_page(SAMPLE_TEXT, 1, output_dir)

    assert not images
    assert not output_dir.exists()


def test_a_report_and_an_extraction_that_disagree_are_refused(
    poppler: Callable[..., FakePoppler], tmp_path: Path
) -> None:
    """Our translation never pairs a record with a file the engine did not write."""
    poppler(double=_OverReportingPoppler(mixed_document()))

    with pytest.raises(PDFPrimitiveError) as failure:
        extract_images_from_page(SAMPLE_MIXED, 1, tmp_path / "embedded_images")

    assert failure.value.error.type == "INTERNAL_ERROR"
    assert failure.value.error.metadata == {"listed": 2, "extracted": 1}


def engine_call(binary: str, tmp_path: Path) -> Callable[[], object]:
    """Return an action that makes the seam run one engine binary."""
    if binary == "pdfseparate":
        return lambda: extract_page(SAMPLE_TEXT, 1, tmp_path / "page.pdf")
    if binary == "pdftoppm":
        return lambda: render_page_to_image(SAMPLE_TEXT, 1, tmp_path / "page.png")
    if binary == "pdftotext":
        return lambda: extract_text_from_page(SAMPLE_TEXT, 1)
    return lambda: extract_images_from_page(SAMPLE_TEXT, 1, tmp_path / "images")


@pytest.mark.parametrize(
    ("binary", "expected"),
    [
        ("pdfseparate", "PAGE_EXTRACTION_ERROR"),
        ("pdftoppm", "RENDER_ERROR"),
        ("pdftotext", "TEXT_EXTRACTION_ERROR"),
        ("pdfimages", "IMAGE_EXTRACTION_ERROR"),
    ],
)
def test_a_stage_failure_keeps_the_shape_of_its_own_work(
    poppler: Callable[..., FakePoppler],
    tmp_path: Path,
    binary: str,
    expected: str,
) -> None:
    """The generic engine exit maps to the stage's kind, so a caller knows what failed."""
    poppler(text_document(), failures={binary: (99, "some other error")})

    with pytest.raises(PDFPrimitiveError) as failure:
        engine_call(binary, tmp_path)()

    assert failure.value.error.type == expected
    assert failure.value.error.recoverable is True


@pytest.mark.parametrize(
    ("exit_code", "stderr", "expected"),
    [
        (1, "", "INVALID_INPUT"),
        (3, "Command Line Error: Incorrect password", "ENCRYPTED_PDF"),
        (2, "", "IO_ERROR"),
        (99, "Syntax Error: Couldn't read xref table", "CORRUPTED_PDF"),
        (
            99,
            "Wrong page range given: the first page (9) can not be after the last page (3).",
            "PAGE_EXTRACTION_ERROR",
        ),
    ],
)
def test_the_engine_signals_map_to_their_documented_failure_kind(
    poppler: Callable[..., FakePoppler],
    tmp_path: Path,
    exit_code: int,
    stderr: str,
    expected: str,
) -> None:
    """One exit code cannot decide a kind; stderr separates the cases the code merges."""
    poppler(text_document(), failures={"pdftoppm": (exit_code, stderr)})

    with pytest.raises(PDFPrimitiveError) as failure:
        render_page_to_image(SAMPLE_TEXT, 1, tmp_path / "page.png")

    assert failure.value.error.type == expected


def test_the_engine_family_is_named_poppler() -> None:
    """The engine recorded in metadata is a name, not a guess about what is installed."""
    assert ENGINE_NAME == "poppler"
