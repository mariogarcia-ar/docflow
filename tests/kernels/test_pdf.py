"""Tests for K2 ``kernel.pdf`` (``E04-02`` / ``S1-T12``).

Fixtures are **generated**, not committed: `kernel-cli.md` §12 asks for synthetic
fixtures rather than corpus documents, and ``plan-01-kernels.md`` §13 marks a
fixture generator as the ``# TODO: [MVP]`` that replaces committed ones. Every
fixture here is named for the failure it provokes.

The load-bearing tests are the two that must fail when their invariant breaks:

- ``test_render_refuses_a_resolution_the_source_cannot_supply`` — the legacy PoC
  upscaled a page to meet a requested DPI and reported success. That is the
  failure this assertion exists to make impossible.
- ``test_classify_reports_an_invisible_text_layer_as_evidence`` — the engine's own
  text extraction returns invisible text as ordinary text, so the naive
  measurement reports a text page. The hidden layer has to be detected as what it
  is: a rendering instruction that draws nothing.

Three Pylint relaxations are declared, each because the rule contradicts what this
suite is for rather than because the code is sloppy: a contract test restates the
names it checks instead of importing them (``duplicate-code``), one test per
acceptance criterion costs file length (``too-many-lines``), and a pytest fixture
is injected by name, so a test parameter necessarily shadows the fixture function
it asks for — that shadowing *is* the wiring.
"""

# pylint: disable=duplicate-code
# pylint: disable=redefined-outer-name
# pylint: disable=too-many-lines

from __future__ import annotations

import pathlib

import pymupdf
import pytest

from docflow.kernels import pdf
from docflow.kernels.types import KernelResult

# --- Fixture construction ----------------------------------------------------

#: The render mode that draws neither fill nor stroke. It is what makes a text
#: layer invisible, and it is what the classifier has to notice.
_INVISIBLE_RENDER_MODE: int = 3

#: A page one inch square, so a placed image's pixel width is its DPI directly.
_ONE_INCH_POINTS: float = 72.0

#: The resolution of the deliberately under-resolution fixture.
_LOW_DPI: int = 150


def _page_with_text(
    path: pathlib.Path, lines: tuple[str, ...] = ("TOTAL 15400.00",)
) -> pathlib.Path:
    """Write a single-page PDF carrying a visible text layer.

    Args:
        path: Where to write the file.
        lines: The lines to place, each on its own baseline.

    Returns:
        The written path.

    """
    document = pymupdf.open()
    page = document.new_page(width=300, height=400)
    for index, line in enumerate(lines):
        page.insert_text((40, 90 + index * 30), line)
    document.save(path)
    document.close()

    return path


def _page_with_invisible_text(path: pathlib.Path) -> pathlib.Path:
    """Write a scan carrying a stale **invisible** text layer.

    The shape is the one the silent-failure matrix describes: an image page with
    text planted behind it that a reader will happily extract and that a person
    cannot see. Building it with the real render mode is what makes the fixture
    provoke the real failure instead of a stand-in for it.

    Args:
        path: Where to write the file.

    Returns:
        The written path.

    """
    document = pymupdf.open()
    page = document.new_page(width=300, height=200)
    page.insert_text((40, 90), "STALE HIDDEN LAYER", render_mode=_INVISIBLE_RENDER_MODE)
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 120, 80))
    pixmap.clear_with(200)
    page.insert_image(pymupdf.Rect(0, 0, 300, 200), pixmap=pixmap)
    document.save(path)
    document.close()

    return path


def _page_with_scan(path: pathlib.Path, dpi: int) -> pathlib.Path:
    """Write a single-page PDF holding one image at a known resolution.

    The page is one inch square, so the image's pixel width *is* its DPI: 150 px
    on a 1-inch page is 150 DPI, measured rather than declared.

    Args:
        path: Where to write the file.
        dpi: The resolution the embedded pixels should hold.

    Returns:
        The written path.

    """
    document = pymupdf.open()
    page = document.new_page(width=_ONE_INCH_POINTS, height=_ONE_INCH_POINTS)
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, dpi, dpi))
    pixmap.clear_with(240)
    page.insert_image(
        pymupdf.Rect(0, 0, _ONE_INCH_POINTS, _ONE_INCH_POINTS), pixmap=pixmap
    )
    document.save(path)
    document.close()

    return path


def _multi_page(
    path: pathlib.Path, count: int = 3, height: float = 400.0
) -> pathlib.Path:
    """Write a document with several distinguishable pages.

    Each page carries its own text and its own height, so a split can be checked
    for both content order and preserved page boxes.

    Args:
        path: Where to write the file.
        count: How many pages to write.
        height: The *first* page's height; later pages differ by 10 points each.

    Returns:
        The written path.

    """
    document = pymupdf.open()
    for number in range(1, count + 1):
        page = document.new_page(width=200 + number, height=height + number * 10)
        page.insert_text((30, 60), f"page {number}")
    document.save(path)
    document.close()

    return path


def _blank_page(path: pathlib.Path) -> pathlib.Path:
    """Write a single empty page.

    Args:
        path: Where to write the file.

    Returns:
        The written path.

    """
    document = pymupdf.open()
    document.new_page()
    document.save(path)
    document.close()

    return path


# --- Fixtures ----------------------------------------------------------------


@pytest.fixture
def text_pdf(tmp_path: pathlib.Path) -> pathlib.Path:
    """A one-page PDF with a visible text layer."""
    return _page_with_text(tmp_path / "text.pdf")


@pytest.fixture
def hidden_layer_pdf(tmp_path: pathlib.Path) -> pathlib.Path:
    """A scan carrying a stale invisible text layer."""
    return _page_with_invisible_text(tmp_path / "scan-hidden-layer.pdf")


@pytest.fixture
def low_dpi_pdf(tmp_path: pathlib.Path) -> pathlib.Path:
    """A page whose embedded pixels hold 150 DPI."""
    return _page_with_scan(tmp_path / "scan150.pdf", dpi=_LOW_DPI)


@pytest.fixture
def three_pages_pdf(tmp_path: pathlib.Path) -> pathlib.Path:
    """A three-page document with distinguishable pages."""
    return _multi_page(tmp_path / "three-pages.pdf")


@pytest.fixture
def blank_pdf(tmp_path: pathlib.Path) -> pathlib.Path:
    """A single empty page."""
    return _blank_page(tmp_path / "blank.pdf")


# --- Criterion: the module declares its surface ------------------------------


def test_module_exports_exactly_the_five_operations_plus_the_shape_set() -> None:
    """``__all__`` is the declared surface, sorted for the linter.

    ``PAGE_SHAPES`` is exported because it is the closed set a caller asserts
    against; the private helpers are not, because a caller reaching for one would
    be reaching past the kernel's contract.

    ``layout_text`` is the sixth name and the only one that is **not** a port
    operation: it exists for callers that need the reader's own character grid, and
    it is deliberately absent from ``PdfSource`` because `plans/README.md` §3
    freezes that port. Its presence here is asserted rather than assumed so that a
    seventh name cannot appear unnoticed.
    """
    exported: list[str] = list(pdf.__all__)

    assert exported == sorted(exported), "__all__ must stay alphabetically sorted"
    assert set(exported) == {
        "PAGE_SHAPES",
        "classify",
        "effective_dpi",
        "extract_tokens",
        "layout_text",
        "probe",
        "render",
        "split",
    }
    for name in exported:
        assert hasattr(pdf, name), f"{name} is exported but not defined"


def test_the_four_page_shapes_are_the_closed_set() -> None:
    """Four shapes, and ``blank`` is one of them.

    ``blank`` is a shape rather than the absence of one, which is what keeps
    *this page has no content* from being reported as *this page had no text*.
    """
    assert pdf.PAGE_SHAPES == ("text", "image", "mixed", "blank")


# --- Criterion: probe --------------------------------------------------------


def test_probe_reports_the_page_count_and_declared_metadata(
    text_pdf: pathlib.Path,
) -> None:
    """``probe`` describes the file without rendering anything."""

    result = pdf.probe(text_pdf)

    assert isinstance(result, KernelResult)
    assert result.reason is None
    assert result.value is not None
    assert result.value.measurements["page_count"] == 1.0
    assert "producer" in result.value.observed
    assert "creator" in result.value.observed
    assert result.value.observed["encrypted"] is False


def test_the_evidence_accompanies_the_value_on_a_successful_call(
    text_pdf: pathlib.Path, low_dpi_pdf: pathlib.Path
) -> None:
    """Every call reports what it observed, and for these operations that is the value.

    The boundary contract requires evidence on every call. For ``probe``,
    ``classify`` and ``effective_dpi`` the value *is* the observation record, and
    the evidence field carries the same record — not an empty one standing in for
    a report that was not made.
    """
    results = (
        pdf.probe(text_pdf),
        pdf.classify(text_pdf, 1, min_chars=1),
        pdf.effective_dpi(low_dpi_pdf, 1),
    )

    for result in results:
        assert result.value is not None
        assert result.evidence.observed, (
            "a successful call must report what it observed; an empty evidence "
            "record would make the value indistinguishable from a bare stand-in"
        )
        assert result.evidence is result.value, (
            "for an observation-valued operation the evidence is the value, not a "
            "second copy that can drift from it"
        )


def test_probe_of_a_missing_file_is_a_typed_reason_not_an_empty_observation(
    tmp_path: pathlib.Path,
) -> None:
    """A file that is not there reports why; it never returns empty observations."""
    result = pdf.probe(tmp_path / "absent.pdf")

    assert result.value is None
    assert result.reason is not None
    assert result.reason.code == "unsupported_format"


def test_probe_reports_an_encrypted_document_as_encrypted(
    tmp_path: pathlib.Path,
) -> None:
    """An encrypted PDF is refused as ``encrypted``, not as unreadable.

    The two need different remediation, so collapsing them would send an operator
    looking for a corrupt file when the file is merely locked.
    """
    source = _page_with_text(tmp_path / "plain.pdf")
    protected = tmp_path / "locked.pdf"
    document = pymupdf.open(source)
    document.save(
        protected,
        # Pylint cannot see the constant: PyMuPDF is a compiled extension, so its
        # module-level attributes are invisible to static analysis. The value
        # exists and the assertion below is what proves the encryption took.
        encryption=pymupdf.PDF_ENCRYPT_AES_256,  # pylint: disable=no-member
        owner_pw="owner",
        user_pw="user",
    )
    document.close()

    result = pdf.probe(protected)

    assert result.value is None
    assert result.reason is not None
    assert result.reason.code == "encrypted"


# --- Criterion: classify detects the invisible layer -------------------------


def test_classify_reports_an_invisible_text_layer_as_evidence(
    hidden_layer_pdf: pathlib.Path,
) -> None:
    """A stale hidden layer is reported, not silently read as a text page.

    The naive measurement fails here: the engine's text extraction returns the
    hidden layer's characters as ordinary text, so a classifier built on the
    extracted character count reports a text page and is wrong. The layer is
    detected as what it is — a no-draw rendering instruction — and reported
    alongside the shape.
    """
    result = pdf.classify(hidden_layer_pdf, 1, min_chars=1)

    assert result.value is not None
    observed = result.value.observed

    assert observed["invisible_text"] is True, (
        "the page's text layer is invisible and must be reported as such; the "
        "engine returns its characters as ordinary text, so nothing else notices"
    )
    assert observed["shape"] == "image", (
        "a scan with a stale hidden layer is an image page; reporting 'text' would "
        "mean the document is never converted and the visible content is never read"
    )


def test_classify_does_not_report_an_invisible_layer_on_a_visible_page(
    text_pdf: pathlib.Path,
) -> None:
    """The detection is not a constant: a visible layer reports ``False``.

    Without this, an implementation that always answered ``True`` would satisfy
    the assertion above while carrying no information at all.
    """
    result = pdf.classify(text_pdf, 1, min_chars=1)

    assert result.value is not None
    assert result.value.observed["invisible_text"] is False


def test_classify_reports_the_shape_from_the_measurement(
    text_pdf: pathlib.Path, low_dpi_pdf: pathlib.Path
) -> None:
    """The shape follows the measurements, in the closed set of four."""
    text = pdf.classify(text_pdf, 1, min_chars=1)
    scan = pdf.classify(low_dpi_pdf, 1, min_chars=1)

    assert text.value is not None
    assert scan.value is not None
    assert text.value.observed["shape"] == "text"
    assert scan.value.observed["shape"] == "image"
    assert text.value.observed["shape"] in pdf.PAGE_SHAPES
    assert scan.value.observed["shape"] in pdf.PAGE_SHAPES


def test_classify_takes_the_character_threshold_from_the_caller(
    text_pdf: pathlib.Path,
) -> None:
    """The same page changes shape when the caller changes the threshold.

    This is `prd.md` FR-15 expressed as a test: the threshold is the caller's
    value, so a kernel holding a constant would make both calls agree and this
    assertion would fail.
    """
    permissive = pdf.classify(text_pdf, 1, min_chars=1)
    strict = pdf.classify(text_pdf, 1, min_chars=10_000)

    assert permissive.value is not None
    assert strict.value is not None
    assert permissive.value.observed["shape"] == "text"
    assert strict.value.observed["shape"] == "image", (
        "with a threshold above the page's character count the text layer does not "
        "count as content, so the page is an image page"
    )
    assert permissive.value.observed["min_chars_applied"] == 1
    assert strict.value.observed["min_chars_applied"] == 10_000


def test_classify_reports_a_blank_page_as_blank_not_as_a_textless_page(
    blank_pdf: pathlib.Path,
) -> None:
    """A page with no text and no image reports ``blank_page``.

    *Blank* is a statement about the page; *a page with no text* is a statement
    about its text layer, and a page holding an image falls in the second category
    while being the opposite of blank.
    """
    result = pdf.classify(blank_pdf, 1, min_chars=1)

    assert result.value is None
    assert result.reason is not None
    assert result.reason.code == "blank_page"
    assert result.evidence.measurements["char_count"] == 0.0
    assert result.evidence.measurements["image_count"] == 0.0


def test_classify_refuses_a_page_outside_the_document(text_pdf: pathlib.Path) -> None:
    """A page number the document does not have is a usage error.

    Raised rather than returned as a ``Reason``: it is a mistake in the request,
    not an answer about the document, which is the distinction between exit 4 and
    exit 2.
    """
    with pytest.raises(ValueError, match="outside the document"):
        pdf.classify(text_pdf, 7, min_chars=1)

    with pytest.raises(ValueError, match="outside the document"):
        pdf.classify(text_pdf, 0, min_chars=1)


# --- Criterion: effective DPI is measured, never taken from the request ------


def test_effective_dpi_is_measured_from_the_embedded_pixels(
    low_dpi_pdf: pathlib.Path,
) -> None:
    """The measured resolution is the embedded pixels over the placed area.

    The fixture is one inch square, so the answer is the pixel width directly —
    which means an implementation that echoed the request, or read a metadata
    field, could not produce this number.
    """
    result = pdf.effective_dpi(low_dpi_pdf, 1)

    assert result.value is not None
    assert result.value.measurements["effective_dpi"] == float(_LOW_DPI)


def test_effective_dpi_reports_an_absence_rather_than_a_zero(
    text_pdf: pathlib.Path,
) -> None:
    """A page with no image has no effective resolution, and says so.

    A zero would read as a measurement that was taken and came out at nothing,
    which is a different statement from *this measurement does not apply*.
    """
    result = pdf.effective_dpi(text_pdf, 1)

    assert result.value is None
    assert result.reason is not None
    assert "effective_dpi" not in result.evidence.measurements


# --- Criterion: render never upscales ---------------------------------------


def test_render_refuses_a_resolution_the_source_cannot_supply(
    low_dpi_pdf: pathlib.Path,
) -> None:
    """A 300 DPI request on a 150 DPI scan is refused, and writes nothing.

    This is the invariant the legacy PoC violated by enlarging the page to meet
    the request and reporting success — larger and no more legible. Breaking it
    looks like a value coming back where a ``Reason`` was required.
    """
    result = pdf.render(low_dpi_pdf, [1], dpi=300)

    assert result.value is None, (
        "an upscaled page reported as a satisfied 300 DPI render is the failure "
        "this assertion exists to prevent"
    )
    assert result.reason is not None
    assert result.reason.code == "insufficient_effective_resolution"
    assert result.evidence.measurements["effective_dpi"] == float(_LOW_DPI)
    assert result.evidence.measurements["dpi_requested"] == 300.0
    assert result.evidence.observed["files_written"] == 0, (
        "no larger file may be produced when the request is refused"
    )


def test_render_honours_a_resolution_the_source_can_supply(
    low_dpi_pdf: pathlib.Path,
) -> None:
    """The same scan renders at a resolution it actually holds.

    The pair with the test above is what proves the refusal is about the measured
    shortfall and not a blanket refusal of scans.
    """
    result = pdf.render(low_dpi_pdf, [1], dpi=100)

    assert result.value is not None
    assert result.value.media_type == "image/png"
    assert result.value.data.startswith(b"\x89PNG")
    assert result.evidence.observed["upscaled"] is False


def test_render_never_reports_a_resolution_it_did_not_honour(
    low_dpi_pdf: pathlib.Path,
) -> None:
    """The reported DPI is the one applied, and a refusal reports the request.

    A render that quietly produced the 150 DPI pixels and labelled them 300 would
    pass a naive "did it succeed" check while being the exact silent failure the
    spec names.
    """
    refused = pdf.render(low_dpi_pdf, [1], dpi=600)
    accepted = pdf.render(low_dpi_pdf, [1], dpi=150)

    assert refused.value is None
    assert refused.reason is not None
    assert accepted.value is not None
    assert accepted.evidence.observed["dpi_applied"] == 150


def test_render_renders_a_vector_page_at_any_requested_resolution(
    text_pdf: pathlib.Path,
) -> None:
    """Vector content has no pixels to fall short of, so it is not refused.

    The check measures embedded pixels; a text page has none, and refusing it
    would make the kernel unusable for the case it was built for.
    """
    result = pdf.render(text_pdf, [1], dpi=300)

    assert result.value is not None
    assert result.evidence.observed["dpi_applied"] == 300


def test_render_refuses_a_non_positive_dpi(text_pdf: pathlib.Path) -> None:
    """A zero or negative resolution is a usage error."""
    with pytest.raises(ValueError, match="dpi must be positive"):
        pdf.render(text_pdf, [1], dpi=0)


# --- Criterion: extract_tokens ----------------------------------------------


def test_extract_tokens_returns_positioned_tokens_with_boxes(
    text_pdf: pathlib.Path,
) -> None:
    """Tokens carry their text and a box in source page coordinates."""
    result = pdf.extract_tokens(text_pdf, [1], dpi=72)

    assert result.value is not None
    assert result.value, "the fixture carries text, so tokens must come back"

    first = result.value[0]
    assert first.text
    assert first.page == 1
    assert first.bbox.width > 0
    assert first.bbox.height > 0


def test_extract_tokens_reports_no_confidence_rather_than_perfect_confidence(
    text_pdf: pathlib.Path,
) -> None:
    """A text layer is not a recogniser, so its confidence is ``None``.

    ``None`` is never coerced to ``1.0``: the text layer reports no confidence at
    all, and a perfect score would be a claim nobody made.
    """
    result = pdf.extract_tokens(text_pdf, [1], dpi=72)

    assert result.value is not None
    assert all(token.confidence is None for token in result.value), (
        "a missing confidence must stay missing; 1.0 would be invented"
    )


def test_extract_tokens_scales_boxes_to_the_requested_resolution(
    text_pdf: pathlib.Path,
) -> None:
    """The same word's box grows with the DPI, so coordinates mean one thing.

    The reader reports at 72 DPI; the box a caller receives is expressed at the
    DPI they asked for, which is what makes a token's box comparable with the box
    ``render`` produces.
    """
    at_72 = pdf.extract_tokens(text_pdf, [1], dpi=72)
    at_144 = pdf.extract_tokens(text_pdf, [1], dpi=144)

    assert at_72.value is not None
    assert at_144.value is not None
    assert at_144.value[0].bbox.x == pytest.approx(at_72.value[0].bbox.x * 2, rel=0.01)
    assert at_144.value[0].bbox.width == pytest.approx(
        at_72.value[0].bbox.width * 2, rel=0.01
    )


def test_extract_tokens_reports_the_page_accounting(
    three_pages_pdf: pathlib.Path,
) -> None:
    """What was asked for and what was read are both reported.

    A truncated read and a page with no text are different facts, and the only way
    to tell them apart is to report both numbers.
    """
    result = pdf.extract_tokens(three_pages_pdf, [1, 2], dpi=72)

    assert result.value is not None
    assert result.evidence.observed["pages_requested"] == [1, 2]
    assert result.evidence.observed["pages_read"] == [1, 2]
    assert result.evidence.observed["reading_order"] == "not_resolved", (
        "imposing a reading order at this boundary is the domain layer's job"
    )


def test_extract_tokens_refuses_an_empty_selection(text_pdf: pathlib.Path) -> None:
    """An empty selection is refused rather than widened to the whole document.

    Widening it would perform work the caller did not ask for, which is the same
    class of error as doing less than asked.
    """
    with pytest.raises(ValueError, match="selection is empty"):
        pdf.extract_tokens(text_pdf, [], dpi=72)


def test_extract_tokens_refuses_a_page_outside_the_document(
    text_pdf: pathlib.Path,
) -> None:
    """A page the document does not have is a usage error."""
    with pytest.raises(ValueError, match="outside the document"):
        pdf.extract_tokens(text_pdf, [1, 9], dpi=72)


# --- Criterion: split --------------------------------------------------------


def test_split_preserves_the_page_count_and_boxes_of_the_range(
    three_pages_pdf: pathlib.Path,
) -> None:
    """The extracted document holds exactly the requested pages, same sizes.

    A split that separates a document from its pages is row 5 of the matrix, and
    it is silent because the output is a perfectly valid PDF of the wrong thing.
    """
    source = pymupdf.open(three_pages_pdf)
    expected = [
        (round(source[1].rect.width, 3), round(source[1].rect.height, 3)),
        (round(source[2].rect.width, 3), round(source[2].rect.height, 3)),
    ]
    source.close()

    result = pdf.split(three_pages_pdf, [2, 3])

    assert result.value is not None
    assert result.evidence.measurements["pages_extracted"] == 2.0
    assert [
        (round(float(size[0]), 3), round(float(size[1]), 3))
        for size in result.evidence.observed["result_page_sizes"]
    ] == expected, "the page boxes must match the source range"


def test_split_records_the_mapping_back_to_the_source(
    three_pages_pdf: pathlib.Path,
) -> None:
    """The descriptor states which source page each result page came from."""
    result = pdf.split(three_pages_pdf, [3, 1])

    assert result.value is not None
    mapping = result.evidence.observed["source_pages"]

    assert [entry["source_page"] for entry in mapping] == [3, 1], (
        "the requested order is honoured: reordering pages is a legitimate "
        "request, and sorting it would make the output not match the selection"
    )


def test_split_refuses_a_repeated_page(three_pages_pdf: pathlib.Path) -> None:
    """A duplicate page is refused instead of duplicating content silently."""
    with pytest.raises(ValueError, match="repeats a page"):
        pdf.split(three_pages_pdf, [1, 1])


def test_split_refuses_an_empty_selection(three_pages_pdf: pathlib.Path) -> None:
    """An empty selection is a usage error."""
    with pytest.raises(ValueError, match="selection is empty"):
        pdf.split(three_pages_pdf, [])


def test_split_output_is_a_pdf(
    three_pages_pdf: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """The extracted bytes are a readable PDF holding the requested pages."""
    result = pdf.split(three_pages_pdf, [1, 2])

    assert result.value is not None
    assert result.value.media_type == "application/pdf"

    written = tmp_path / "extracted.pdf"
    written.write_bytes(result.value.data)

    reopened = pymupdf.open(written)
    try:
        assert reopened.page_count == 2
    finally:
        reopened.close()


# --- Criterion: no threshold constant lives in the module -------------------


def test_the_module_declares_no_threshold_constant() -> None:
    """What counts as too little text is the caller's value, never a constant.

    Asserted over the module's own public constants rather than by reading the
    source: a ``MIN_CHARS`` or ``MIN_DPI`` added here would be a routing decision
    in disguise (`prd.md` FR-15). The reason codes are excluded because they are
    the closed vocabulary of `kernel-cli.md` §5 rather than tunable values.
    """
    forbidden = {"min", "max", "threshold", "quality", "limit", "umbral"}
    declared = [
        name for name in vars(pdf) if name.isupper() and not name.startswith("_")
    ]

    assert declared, "the module declares constants, so this check is not vacuous"

    for name in sorted(declared):
        assert not any(part in name.lower() for part in forbidden), (
            f"{name!r} looks like a policy threshold; a threshold is the caller's "
            "value and must not live in this module"
        )


def test_the_modules_constants_name_no_policy_value() -> None:
    """No constant, public or private, is a tunable policy value.

    Checked as a forbidden vocabulary rather than an allow-list, because an
    allow-list would fail every time a constant is legitimately renamed — and a
    guard that cries wolf is a guard that gets loosened. What matters is that no
    name reads as something a caller should be deciding: a minimum, a maximum, a
    threshold, a quality, a limit.
    """
    forbidden = ("min", "max", "threshold", "quality", "limit", "umbral", "dpi")
    declared = [name for name in vars(pdf) if name.isupper()]

    assert declared, "the module declares constants, so this check is not vacuous"

    for name in sorted(declared):
        lowered = name.lower()
        for part in forbidden:
            assert part not in lowered, (
                f"{name!r} reads like a policy value ({part!r}); a threshold or a "
                "resolution limit belongs to the caller, not to this module"
            )


# --- The reader binary is required, never substituted -----------------------


def test_a_missing_reader_binary_is_a_typed_reason_and_not_a_substitute(
    text_pdf: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without ``pdftotext`` the call reports why, and reads nothing.

    `wbs.md` §9: a missing binary is a typed ``Reason``, never a fallback reader.
    A substitute extractor would report different tokens under this engine's
    identity, which is a different measurement wearing the same label.
    """
    monkeypatch.setattr(pdf.shutil, "which", lambda _name: None)

    result = pdf.extract_tokens(text_pdf, [1], dpi=72)

    assert result.value is None
    assert result.reason is not None
    assert result.reason.code == "engine_unavailable"
    assert "pdftotext" in result.reason.message


# --- The reason vocabulary --------------------------------------------------


def test_every_reason_code_raised_here_is_in_the_closed_set() -> None:
    """The codes this module can raise are the ones `kernel-cli.md` §5 declares.

    A code outside that set would be unassertable by the silent-failure suite,
    because the suite targets codes and a novel one has no row behind it.
    """
    closed_set = {
        "blank_page",
        "encrypted",
        "engine_unavailable",
        "insufficient_effective_resolution",
        "unsupported_format",
    }
    declared = {value for name, value in vars(pdf).items() if name.startswith("_CODE_")}

    assert declared, "the module declares reason codes, so this is not vacuous"
    assert declared <= closed_set, (
        f"codes outside the closed set: {declared - closed_set}"
    )
