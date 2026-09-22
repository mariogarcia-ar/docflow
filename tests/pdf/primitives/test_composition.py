"""Tests for composition and classification (``PDF-08``).

Two kinds of case, deliberately separated:

* **Crafted metric vectors**, because the classification is a pure function of metrics and
  the boundaries are what matter. A page can be asked for without a PDF on disk.
* **Real bytes**, because a threshold that has never been compared against a real document
  is a threshold nobody has checked. The fixtures cover the three answers: a text-dominant
  page, a full-page scan, and an invoice that carries both.

The third subject here is the invariant ``PDF-13`` names: the classification vocabulary is
closed and the function is pure. Both are asserted rather than assumed.
"""

from __future__ import annotations

import inspect
import subprocess
import sys
from pathlib import Path

import pytest

from docflow.pdf.contracts import EmbeddedImage, PDFPageMetrics, TextBlock
from docflow.pdf.primitives.composition import (
    DOMINANT_IMAGE_COVERAGE_MIN,
    IMAGE_COVERAGE_MIN,
    TEXT_CHAR_MIN,
    TEXT_COVERAGE_MIN,
    WORD_MIN,
    PageContent,
    analyze_pdf_page,
    classify_pdf_page,
)
from docflow.pdf.primitives.document import get_page_dimensions
from docflow.pdf.primitives.images import get_image_blocks
from docflow.pdf.primitives.text import engine_report, get_text_blocks

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
TEXT_PDF = FIXTURES / "matrix" / "three-invoices.pdf"
SCAN_PDF = FIXTURES / "matrix" / "scan150.pdf"
MIXED_PDF = FIXTURES / "pdf_aptos_layout" / "36744cc6-2ed9-47e5-b4b8-66c31768164b.pdf"

CLASSIFICATIONS = ("TEXT", "IMAGE", "MIXED")

_REPO_ROOT = FIXTURES.parents[1]
_SOURCE_ROOT = str(_REPO_ROOT / "src")


def metrics(
    *,
    characters: int = 0,
    words: int = 0,
    text_blocks: int = 0,
    images: int = 0,
    text_coverage: float = 0.0,
    image_coverage: float = 0.0,
    largest_image_coverage: float = 0.0,
) -> PDFPageMetrics:
    """Build a metrics vector, so each test states only the field it is about."""
    return PDFPageMetrics(
        characters=characters,
        words=words,
        text_blocks=text_blocks,
        images=images,
        text_coverage=text_coverage,
        image_coverage=image_coverage,
        largest_image_coverage=largest_image_coverage,
    )


def page_content(path: Path, page_number: int) -> PageContent:
    """Assemble a real page's content from the primitives built in PDF-03/06/07."""
    return PageContent(
        page_number=page_number,
        text=engine_report(path, page_number).text,
        text_blocks=get_text_blocks(path, page_number),
        embedded_images=get_image_blocks(path, page_number),
        page_dimensions=get_page_dimensions(path, page_number),
    )


# --------------------------------------------------------------------------------------
# The classification vocabulary and its purity (PDF-13, invariant 3)
# --------------------------------------------------------------------------------------


def test_the_classification_is_always_one_of_three_literals() -> None:
    """Every metric vector produces one of ``TEXT`` / ``IMAGE`` / ``MIXED``.

    Swept over the corners and a grid, rather than asserted for a few hand-picked vectors,
    because the failure this guards against is a branch that returns something else.

    Mutation that breaks it: return ``"OCR"`` from any branch. The membership assertion fails
    — that is invariant 3's documented mutation, and the point of it is that introducing a
    fourth value is the visible symptom of this processor taking a routing decision.
    """
    values = (0.0, 0.5, 1.0)
    counts = (0, TEXT_CHAR_MIN, TEXT_CHAR_MIN * 10)

    for characters in counts:
        for image_coverage in values:
            for largest in values:
                result = classify_pdf_page(
                    metrics(
                        characters=characters,
                        words=characters // 5,
                        images=1 if image_coverage else 0,
                        text_coverage=min(1.0, characters / 1000),
                        image_coverage=image_coverage,
                        largest_image_coverage=largest,
                    )
                )
                assert result in CLASSIFICATIONS, result


def test_classification_depends_on_nothing_but_its_argument() -> None:
    """The function takes metrics and nothing else — no context, no options, no flag.

    Invariant 3's purity half. Asserted on the signature *and* by calling it in a fresh
    interpreter that never imports the orchestrator, because a signature can be honest while
    a module-level import quietly reaches for a workflow decision.

    Mutation that breaks it: add a ``force_ocr`` parameter read from ``PDFContext``, or
    import ``docflow.workflow`` here. The parameter assertion or the subprocess check fails.
    """
    parameters = list(inspect.signature(classify_pdf_page).parameters)
    assert parameters == ["metrics"]

    probe = (
        "import sys;"
        "from docflow.pdf.primitives.composition import classify_pdf_page;"
        "from docflow.pdf.contracts import PDFPageMetrics;"
        "classify_pdf_page(PDFPageMetrics(0, 0, 0, 0, 0.0, 0.0, 0.0));"
        "assert 'docflow.workflow' not in sys.modules;"
        "print('PURE')"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        check=True,
        env={"PYTHONPATH": _SOURCE_ROOT},
        cwd=_REPO_ROOT,
    )

    assert completed.stdout.strip() == "PURE"


def test_the_thresholds_are_named_constants_not_literals() -> None:
    """The boundaries are named, so they are reviewable in one place.

    A literal in a comparison is the silent default ``docs/plan/README.md`` §7 forbids. The
    values are provisional for the PoC; their being *named* is not.
    """
    assert TEXT_CHAR_MIN > 0
    assert WORD_MIN > 0
    assert 0 < TEXT_COVERAGE_MIN < 1
    assert 0 < IMAGE_COVERAGE_MIN < 1
    assert 0 < DOMINANT_IMAGE_COVERAGE_MIN <= 1
    assert IMAGE_COVERAGE_MIN < DOMINANT_IMAGE_COVERAGE_MIN


# --------------------------------------------------------------------------------------
# The classification itself
# --------------------------------------------------------------------------------------


def test_real_text_with_negligible_image_area_is_text() -> None:
    """A page dominated by its text layer is ``TEXT``.

    Mutation that breaks it: drop the text thresholds. The page falls through to ``MIXED``.
    """
    result = classify_pdf_page(
        metrics(
            characters=TEXT_CHAR_MIN * 5,
            words=WORD_MIN * 5,
            text_blocks=4,
            images=1,
            text_coverage=0.3,
            image_coverage=0.01,
            largest_image_coverage=0.01,
        )
    )

    assert result == "TEXT"


def test_a_single_dominant_image_is_image_whatever_text_is_on_top() -> None:
    """A full-page picture is ``IMAGE`` even when it carries a text layer.

    A scanned page with an OCR layer is exactly this case, and it is the reason the dominant
    test comes first: judging it by its text would call it ``TEXT`` and hide the fact that
    the page is a picture.
    """
    result = classify_pdf_page(
        metrics(
            characters=TEXT_CHAR_MIN * 10,
            words=WORD_MIN * 10,
            text_blocks=20,
            images=1,
            text_coverage=0.4,
            image_coverage=1.0,
            largest_image_coverage=1.0,
        )
    )

    assert result == "IMAGE"


def test_almost_no_text_with_an_image_is_image() -> None:
    """A page whose only content is visual is ``IMAGE``, even below the dominant threshold."""
    result = classify_pdf_page(
        metrics(
            characters=3,
            words=1,
            images=1,
            text_coverage=0.001,
            image_coverage=IMAGE_COVERAGE_MIN,
            largest_image_coverage=IMAGE_COVERAGE_MIN,
        )
    )

    assert result == "IMAGE"


def test_real_text_beside_a_real_image_is_mixed() -> None:
    """Both present and both substantial is ``MIXED``."""
    result = classify_pdf_page(
        metrics(
            characters=TEXT_CHAR_MIN * 5,
            words=WORD_MIN * 5,
            text_blocks=6,
            images=2,
            text_coverage=0.2,
            image_coverage=0.55,
            largest_image_coverage=0.4,
        )
    )

    assert result == "MIXED"


def test_a_page_with_neither_text_nor_images_is_not_called_text() -> None:
    """An empty page is not a text page.

    Mutation that breaks it: return ``TEXT`` as the fall-through branch. A blank page then
    claims to carry a text layer, which is the claim ``PDF-06`` went out of its way not to
    make.
    """
    result = classify_pdf_page(metrics())

    assert result in CLASSIFICATIONS
    assert result != "TEXT"


def test_long_words_alone_do_not_make_a_page_text() -> None:
    """The character and word floors are both required, not either one.

    Mutation that breaks it: test ``characters`` alone. A page of three very long tokens then
    passes the character floor and is called ``TEXT``.
    """
    result = classify_pdf_page(
        metrics(
            characters=TEXT_CHAR_MIN * 3,
            words=1,
            text_blocks=1,
            text_coverage=0.3,
        )
    )

    assert result != "TEXT"


# --------------------------------------------------------------------------------------
# The measurements
# --------------------------------------------------------------------------------------


def test_measuring_a_real_text_page() -> None:
    """A text-dominant document measures as text, with a real coverage fraction."""
    page = analyze_pdf_page(page_content(TEXT_PDF, 1))

    assert page.characters > 0
    assert page.words > 0
    assert page.text_blocks > 0
    assert page.images == 0
    assert page.image_coverage == 0.0
    assert page.largest_image_coverage == 0.0
    assert 0 < page.text_coverage < 1
    assert classify_pdf_page(page) == "TEXT"


def test_measuring_a_full_page_scan_gives_total_image_coverage() -> None:
    """A scan that is the whole page measures as exactly full coverage.

    The strongest available check on the pixel-to-point derivation: this fixture's image is
    826 x 1169 px at 72 ppi on an 826 x 1169 pt page, so the answer is 1.0 and any error in
    the arithmetic shows up as a number that is not 1.0.

    Note what this test does **not** catch. At exactly 72 ppi the pixel count and the point
    count are numerically identical, so using pixels as the area would still give 1.0 here.
    That mutation is caught by the 170 ppi vector below instead — the two tests are not
    redundant, and this one is not the guard it looks like.
    """
    page = analyze_pdf_page(page_content(SCAN_PDF, 1))

    assert page.images == 1
    assert page.image_coverage == pytest.approx(1.0)
    assert page.largest_image_coverage == pytest.approx(1.0)
    assert page.characters == 0
    assert classify_pdf_page(page) == "IMAGE"


def test_the_image_area_is_scaled_by_resolution_not_measured_in_pixels() -> None:
    """An image at 170 ppi occupies far less of the page than its pixel count suggests.

    On ``scan150`` the resolution is exactly 72 ppi, which makes pixels and points coincide
    and hides the difference entirely. This vector uses the masked fixture's first image —
    150 x 32 px at 170 ppi — where the two answers are 5.6x apart: 861 square points drawn
    against 4800 if the pixel count were taken as the area.

    Mutation that breaks it: return the raw pixel count from ``_image_area``. The computed
    coverage becomes 4800/500000 rather than 861/500000, and the assertion fails. That
    mutation survives every other test in this module.
    """
    content = PageContent(
        page_number=1,
        text="",
        text_blocks=[],
        embedded_images=[
            EmbeddedImage(
                image_id="image_001",
                path=Path("image_001.png"),
                bbox=None,
                width=150,
                height=32,
                format="image",
                metadata={"x_ppi": "170", "y_ppi": "169"},
            )
        ],
        page_dimensions=(500.0, 1000.0),
    )

    page = analyze_pdf_page(content)

    # 150/170*72 = 63.53 pt wide, 32/169*72 = 13.63 pt tall  ->  866.1 sq pt
    assert page.image_coverage == pytest.approx(866.1 / 500_000, rel=1e-3)
    assert page.image_coverage != pytest.approx(4800 / 500_000, rel=1e-3)


def test_a_higher_resolution_means_a_smaller_drawn_image() -> None:
    """Doubling the reported resolution halves each dimension and quarters the area.

    The direction of the relationship, asserted directly: it is what makes the derivation a
    measurement of the page rather than of the file's bytes.
    """

    def coverage_at(ppi: float) -> float:
        return analyze_pdf_page(
            PageContent(
                page_number=1,
                text="",
                text_blocks=[],
                embedded_images=[
                    EmbeddedImage(
                        image_id="image_001",
                        path=Path("image_001.png"),
                        bbox=None,
                        width=144,
                        height=144,
                        format="image",
                        metadata={"x_ppi": str(ppi), "y_ppi": str(ppi)},
                    )
                ],
                page_dimensions=(1000.0, 1000.0),
            )
        ).image_coverage

    assert coverage_at(72.0) == pytest.approx(4 * coverage_at(144.0))


def test_measuring_a_page_that_carries_both() -> None:
    """An invoice with text and small images measures both and is called ``TEXT``.

    Worth pinning: three images on a page do not by themselves make it visual, and a
    classifier that treated "has images" as "is an image" would get this wrong.
    """
    page = analyze_pdf_page(page_content(MIXED_PDF, 1))

    assert page.images == 3
    assert page.characters > 0
    assert page.image_coverage > 0
    assert page.image_coverage < IMAGE_COVERAGE_MIN
    assert page.largest_image_coverage < page.image_coverage
    assert classify_pdf_page(page) == "TEXT"


def test_largest_image_coverage_is_the_largest_single_image() -> None:
    """The field means one image's share, not the sum.

    ``PDF-09`` reads this to tell "one picture fills the page" from "many pictures tile it",
    so the two fields must not be interchangeable.
    """
    page = analyze_pdf_page(page_content(MIXED_PDF, 1))

    assert page.largest_image_coverage <= page.image_coverage


def test_an_empty_page_measures_as_zeroes_without_raising() -> None:
    """Nothing on a page is a measurement of nothing, not an error."""
    page = analyze_pdf_page(
        PageContent(
            page_number=1,
            text="",
            text_blocks=[],
            embedded_images=[],
            page_dimensions=(612.0, 792.0),
        )
    )

    assert (page.characters, page.words, page.images) == (0, 0, 0)
    assert page.text_coverage == 0.0
    assert page.image_coverage == 0.0


def test_a_degenerate_page_with_content_is_refused() -> None:
    """A page reporting no area while carrying content is an error, not a zero.

    Returning ``0.0`` would put a fabricated fraction into the metrics; dividing by zero
    would be a crash. Both are worse than saying the measurement cannot be made.

    Mutation that breaks it: return ``0.0`` when the page area is zero. The ``pytest.raises``
    block fails and the fabricated measurement is published.
    """
    content = PageContent(
        page_number=1,
        text="some text that is long enough to be noticed by the metrics",
        text_blocks=[
            TextBlock(
                block_id="block_001",
                text="some text",
                bbox=(0.0, 0.0, 100.0, 20.0),
                page_number=1,
            )
        ],
        embedded_images=[],
        page_dimensions=(0.0, 0.0),
    )

    with pytest.raises(ValueError, match="no area"):
        analyze_pdf_page(content)


def test_blocks_without_a_box_contribute_no_area_but_are_still_counted() -> None:
    """``bbox`` is optional, so its absence must not crash the arithmetic.

    ``PDF-07`` returns ``None`` boxes by design, and ``PDF-06`` returns them when the engine
    omits geometry. Counting the block while contributing no area keeps the block count
    honest without inventing a rectangle for it.
    """
    content = PageContent(
        page_number=1,
        text="text",
        text_blocks=[
            TextBlock(block_id="block_001", text="text", bbox=None, page_number=1),
            TextBlock(
                block_id="block_002",
                text="more",
                bbox=(0.0, 0.0, 100.0, 100.0),
                page_number=1,
            ),
        ],
        embedded_images=[],
        page_dimensions=(1000.0, 1000.0),
    )

    page = analyze_pdf_page(content)

    assert page.text_blocks == 2
    assert page.text_coverage == pytest.approx(0.01)


def test_an_inverted_box_contributes_nothing_rather_than_a_negative_area() -> None:
    """A malformed box cannot subtract from the total."""
    content = PageContent(
        page_number=1,
        text="text",
        text_blocks=[
            TextBlock(
                block_id="block_001",
                text="bad",
                bbox=(100.0, 100.0, 0.0, 0.0),
                page_number=1,
            )
        ],
        embedded_images=[],
        page_dimensions=(1000.0, 1000.0),
    )

    assert analyze_pdf_page(content).text_coverage == 0.0


def test_an_image_without_a_reported_resolution_falls_back_to_pixels() -> None:
    """A missing resolution is approximated, not turned into a division by zero.

    Pinned because the fallback is a documented approximation: it must not raise, and it must
    not produce an infinite coverage.
    """
    content = PageContent(
        page_number=1,
        text="",
        text_blocks=[],
        embedded_images=[
            EmbeddedImage(
                image_id="image_001",
                path=Path("image_001.png"),
                bbox=None,
                width=100,
                height=50,
                format="image",
                metadata={"x_ppi": "0", "y_ppi": "0"},
            )
        ],
        page_dimensions=(10_000.0, 10_000.0),
    )

    page = analyze_pdf_page(content)

    assert page.image_coverage == pytest.approx(5000 / 100_000_000)
    assert page.image_coverage < 1


def test_measuring_is_deterministic_over_the_same_page() -> None:
    """The same page measures the same way twice — this processor's determinism class."""
    content = page_content(MIXED_PDF, 1)

    assert analyze_pdf_page(content) == analyze_pdf_page(content)
