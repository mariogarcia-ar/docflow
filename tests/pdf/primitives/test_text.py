"""Tests for the native-text primitives (``PDF-06``).

Two committed fixtures carry the two answers this task has to keep apart:

* ``three-invoices.pdf`` — a text-dominant page, where the text layer exists and is real.
* ``pdf_escaneados/3ac5a2ec-…pdf`` — an image-only page with **no** text layer at all.

The second is the one that matters. The plan is explicit that an empty text layer is data
rather than a defect, so the tests below pin the empty answer *and* pin that it is not
turned into an error, an OCR call, or a form feed.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from docflow.pdf.primitives.failures import PDFPrimitiveError, classify_text_failure
from docflow.pdf.primitives.text import (
    PAGE_BREAK,
    XHTML_NAMESPACE,
    engine_report,
    extract_text_from_page,
    get_text_blocks,
    paragraphs,
    strip_page_breaks,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
THREE_PAGE_PDF = FIXTURES / "matrix" / "three-invoices.pdf"
IMAGE_ONLY_PDF = (
    FIXTURES / "pdf_escaneados" / "3ac5a2ec-d129-47c0-947a-4680c7e25f06.pdf"
)
HYPHENATED_PDF = FIXTURES / "matrix" / "pdf_hyphenated.pdf"
ACCENTS_PDF = FIXTURES / "matrix" / "pdf_accents.pdf"

_REPO_ROOT = FIXTURES.parents[1]
_SOURCE_ROOT = str(_REPO_ROOT / "src")

TEXT_PAGE = 2
PAGE_COUNT = 3


@pytest.fixture(name="text_page_pdf")
def text_page_pdf_fixture() -> Path:
    """Return the committed fixture whose pages carry a text layer."""
    assert THREE_PAGE_PDF.exists(), f"missing fixture: {THREE_PAGE_PDF}"
    return THREE_PAGE_PDF


@pytest.fixture(name="image_only_pdf")
def image_only_pdf_fixture() -> Path:
    """Return the committed fixture whose page has no text layer."""
    assert IMAGE_ONLY_PDF.exists(), f"missing fixture: {IMAGE_ONLY_PDF}"
    return IMAGE_ONLY_PDF


@pytest.fixture(name="hyphenated_pdf")
def hyphenated_pdf_fixture() -> Path:
    """Return the committed fixture whose text layer splits words across lines."""
    assert HYPHENATED_PDF.exists(), f"missing fixture: {HYPHENATED_PDF}"
    return HYPHENATED_PDF


@pytest.fixture(name="accents_pdf")
def accents_pdf_fixture() -> Path:
    """Return the committed fixture whose text layer carries non-ASCII characters."""
    assert ACCENTS_PDF.exists(), f"missing fixture: {ACCENTS_PDF}"
    return ACCENTS_PDF


def test_a_text_page_yields_its_own_text(text_page_pdf: Path) -> None:
    """The page's text is read, and it is the page that was asked for."""
    text = extract_text_from_page(text_page_pdf, TEXT_PAGE)

    assert text
    assert f"page {TEXT_PAGE} of {PAGE_COUNT}" in text


def test_the_page_framing_is_not_part_of_the_payload(text_page_pdf: Path) -> None:
    """No form feed survives into the returned text.

    Mutation that breaks it: return the engine's raw output instead of calling
    ``strip_page_breaks``. Every page then ends with ``\\x0c``, and a caller counting
    characters counts one that is not document text.
    """
    for page_number in range(1, PAGE_COUNT + 1):
        assert PAGE_BREAK not in extract_text_from_page(text_page_pdf, page_number)


def test_an_image_only_page_yields_the_empty_string(image_only_pdf: Path) -> None:
    """A page with no text layer reports no text — it does not report a form feed.

    This is the trap the module exists to avoid. ``pdftotext`` answers an image-only page
    with a single form feed, so a naive implementation returns a one-character "text layer"
    and every downstream measurement counts a character that is not there.

    Mutation that breaks it: drop the ``strip_page_breaks`` call. The result becomes
    ``"\\x0c"``, the first assertion fails, and the assertion that matters — that this is
    indistinguishable from "no text" — stops holding.
    """
    text = extract_text_from_page(image_only_pdf, 1)

    assert text == ""
    assert not text.strip()


def test_an_empty_text_layer_is_data_and_not_an_error(image_only_pdf: Path) -> None:
    """No OCR fallback, and no exception either.

    ``subplan-procesador-pdf.md`` §3 is explicit: an empty result is data. Mutation that
    breaks it: raise when the text is empty — the page is then lost instead of reported as a
    page with no text, and the absence of a text layer gets confused with the failure to
    read one.
    """
    assert extract_text_from_page(image_only_pdf, 1) == ""
    assert not get_text_blocks(image_only_pdf, 1)


def test_the_engine_own_character_count_includes_the_framing(
    image_only_pdf: Path, text_page_pdf: Path
) -> None:
    """The reported count is the engine's, measured before the payload was edited.

    Kept deliberately: it is a measurement of what the engine produced, so it is not
    ``len(text)``. Mutation that breaks it: compute the count from the stripped text, which
    makes the image-only page report zero characters and erases the evidence that the engine
    answered at all.
    """
    empty_page = engine_report(image_only_pdf, 1)
    text_page = engine_report(text_page_pdf, TEXT_PAGE)

    assert empty_page.engine_characters == len(PAGE_BREAK)
    assert empty_page.text == ""
    assert text_page.engine_characters > len(text_page.text)


def test_the_report_and_the_plain_text_agree(text_page_pdf: Path) -> None:
    """Both entry points describe the same page, from independent calls.

    They read the same page with the same default, so they must not disagree about what it
    says. An earlier version of ``engine_report`` omitted the ``-layout`` flag while its
    sibling defaulted it on, so the two returned different text — a real inconsistency this
    test caught rather than a hypothetical one.
    """
    report = engine_report(text_page_pdf, TEXT_PAGE)

    assert report.text == extract_text_from_page(text_page_pdf, TEXT_PAGE)
    assert report.page_number == TEXT_PAGE


@pytest.mark.parametrize("layout", [True, False])
def test_the_report_honours_the_layout_flag_like_its_sibling(
    text_page_pdf: Path, layout: bool
) -> None:
    """The two entry points stay in step at both settings, not only at the default."""
    report = engine_report(text_page_pdf, TEXT_PAGE, layout=layout)

    assert report.text == extract_text_from_page(
        text_page_pdf, TEXT_PAGE, layout=layout
    )


def test_the_text_is_reported_rather_than_rewritten(text_page_pdf: Path) -> None:
    """Nothing in the payload is normalised, joined or reflowed.

    ``subplan-procesador-pdf.md`` §2 puts content interpretation out of bounds for this
    processor. The module adds none of its own: the output is compared against an
    independent engine read, so any extra pass changes the comparison.

    Mutation that breaks it: add a ``re.sub(r"(\\w)-\\n(\\w)", ...)`` pass to
    :func:`extract_text_from_page`. The de-hyphenation guard below is the test that catches
    it; this one catches a rewriting pass that alters anything else.
    """
    raw = extract_text_from_page(text_page_pdf, TEXT_PAGE)

    assert "\n" in raw
    assert raw == raw.strip()
    assert raw == strip_page_breaks(
        subprocess.run(
            [
                "pdftotext",
                "-layout",
                "-f",
                str(TEXT_PAGE),
                "-l",
                str(TEXT_PAGE),
                str(text_page_pdf),
                "-",
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )


def test_a_hyphenated_line_break_survives_the_read(hyphenated_pdf: Path) -> None:
    """A word split across two lines keeps its hyphen and its break.

    This is the case that makes the module's stance observable. It also documents a fact
    about the engine that is easy to miss and decides what ``layout`` actually controls:
    ``pdftotext`` **de-hyphenates by default** — a document saying ``"well-\\nknown"`` comes
    back as ``"wellknown"`` unless ``-layout`` is passed. So the engine is already
    interpreting the text in its default mode, and ``-layout`` is what makes it stop.

    Mutation that breaks it: drop ``-layout`` from the argument list, or add a de-hyphenation
    pass. Either way the joined ``wellknown`` appears and the ``"-\\n"`` sequence is gone.
    """
    layout_text = extract_text_from_page(hyphenated_pdf, 1, layout=True)
    plain_text = extract_text_from_page(hyphenated_pdf, 1, layout=False)

    assert "well-\nknown" in layout_text
    assert "exam-\nple" in layout_text

    # And the opposite mode really does lose it: asserting this keeps the fixture honest,
    # because a fixture that did not exercise the difference would let both assertions pass
    # while proving nothing.
    assert "well-knew" not in plain_text
    assert "wellknown" in plain_text
    assert layout_text != plain_text


def test_paragraphs_are_slices_of_the_text_not_a_rewrite() -> None:
    """Splitting loses nothing, and rejoining is not claimed to be lossless.

    The pieces are checked to be substrings of the input rather than equal to a normalised
    form, which is the property that keeps the split non-destructive.
    """
    text = "first line\nsecond line\n\nsecond paragraph\n\n\nthird\n\n"

    pieces = paragraphs(text)

    assert pieces == ["first line\nsecond line", "second paragraph", "third"]
    for piece in pieces:
        assert piece in text


def test_paragraphs_drops_only_blank_runs() -> None:
    """A blank run is not a paragraph; nothing else is discarded."""
    assert paragraphs("\n\n\n") == []
    assert paragraphs("") == []
    assert paragraphs("   \n  ") == []


def test_blocks_come_back_in_the_engine_order_with_stable_ids(
    text_page_pdf: Path,
) -> None:
    """Blocks are ordered as laid out, with contiguous identifiers and real boxes."""
    blocks = get_text_blocks(text_page_pdf, TEXT_PAGE)

    assert blocks
    assert [block.block_id for block in blocks] == [
        f"block_{index:03d}" for index in range(1, len(blocks) + 1)
    ]
    assert all(block.page_number == TEXT_PAGE for block in blocks)
    assert all(block.text for block in blocks)
    assert [block.text for block in blocks] == sorted(
        (block.text for block in blocks),
        key=lambda text: min(
            block.bbox[1]
            for block in blocks
            if block.text == text and block.bbox is not None
        ),
    )


def test_every_block_carries_its_placement(text_page_pdf: Path) -> None:
    """A block that has a box reports real coordinates, in page points."""
    blocks = get_text_blocks(text_page_pdf, TEXT_PAGE)

    for block in blocks:
        assert block.bbox is not None
        x_min, y_min, x_max, y_max = block.bbox
        assert 0 <= x_min < x_max
        assert 0 <= y_min < y_max


def test_blocks_are_found_through_the_xhtml_namespace(text_page_pdf: Path) -> None:
    """The layout document is namespaced, and the parser has to say so.

    Mutation that breaks it: query ``"block"`` instead of ``"{namespace}block"``. ElementTree
    then matches nothing, every page reports zero blocks, and the failure looks like a
    document with no text rather than like a parser bug.
    """
    assert XHTML_NAMESPACE in "http://www.w3.org/1999/xhtml"
    assert get_text_blocks(text_page_pdf, TEXT_PAGE)


def test_blocks_are_deterministic_across_two_runs(text_page_pdf: Path) -> None:
    """The same bytes give the same blocks, which is this processor's determinism class."""
    first = get_text_blocks(text_page_pdf, TEXT_PAGE)
    second = get_text_blocks(text_page_pdf, TEXT_PAGE)

    assert first == second


def test_different_pages_do_not_return_the_same_text(text_page_pdf: Path) -> None:
    """Each page reports its own content.

    A reader that ignored the range would return page 1 for every request while still
    producing well-formed text, so a presence check alone would not catch it.
    """
    texts = [
        extract_text_from_page(text_page_pdf, page_number)
        for page_number in range(1, PAGE_COUNT + 1)
    ]

    assert len(set(texts)) == PAGE_COUNT


def test_a_page_below_one_is_refused(text_page_pdf: Path) -> None:
    """Page 0 never reaches the engine, which would read it as 'no range'.

    ``pdftotext -f 0 -l 0`` returns the whole document — the fourth tool in this package
    with the hazard — so a forwarded zero would produce plausible text from the wrong pages.

    Mutation that breaks it: remove the ``require_positive_page_range`` calls. Both
    ``pytest.raises`` blocks fail.
    """
    for invalid in (0, -1):
        with pytest.raises(ValueError, match="1-based"):
            extract_text_from_page(text_page_pdf, invalid)
        with pytest.raises(ValueError, match="1-based"):
            get_text_blocks(text_page_pdf, invalid)


def test_a_page_past_the_end_is_a_typed_failure(text_page_pdf: Path) -> None:
    """A page the document does not have is reported, not guessed at."""
    with pytest.raises(PDFPrimitiveError) as failure:
        extract_text_from_page(text_page_pdf, PAGE_COUNT + 1)

    assert failure.value.error_type == "PAGE_OUT_OF_RANGE"


def test_a_text_failure_is_recoverable_while_a_document_failure_is_not() -> None:
    """The classification of a text failure says the page can survive it.

    ``PDF-09`` needs this to report a page as ``PARTIAL`` rather than losing it entirely,
    since a failed text layer leaves the render and the embedded images intact.
    """
    recoverable = classify_text_failure(
        Path("doc.pdf"), ValueError("boom"), page_number=1
    )
    document_level = PDFPrimitiveError("CORRUPTED_PDF", "unreadable")

    assert recoverable.error_type == "TEXT_EXTRACTION_ERROR"
    assert recoverable.recoverable is True
    assert document_level.recoverable is False


def test_text_extraction_never_modifies_the_source(text_page_pdf: Path) -> None:
    """Reading the text layer is read-only."""
    before = hashlib.sha256(text_page_pdf.read_bytes()).hexdigest()

    extract_text_from_page(text_page_pdf, TEXT_PAGE)
    get_text_blocks(text_page_pdf, TEXT_PAGE)
    engine_report(text_page_pdf, TEXT_PAGE)

    assert hashlib.sha256(text_page_pdf.read_bytes()).hexdigest() == before


def test_strip_page_breaks_handles_the_three_shapes_it_meets() -> None:
    """The de-framing is defined on the shapes the engine actually produces."""
    assert strip_page_breaks(PAGE_BREAK) == ""
    assert strip_page_breaks("text\n\n" + PAGE_BREAK) == "text"
    assert strip_page_breaks("a" + PAGE_BREAK + "b") == "ab"


# A locale that is genuinely not UTF-8, so Python decodes with something else. ``C`` will
# not do: since Python 3.7 it enables UTF-8 Mode for the C locale (PEP 540), which masks the
# very hazard this guards against. Verified on macOS with ``sys.flags.utf8_mode``: 1 under
# ``C``, 0 under ``en_US.ISO8859-1``.
NON_UTF8_LOCALES = ("en_US.ISO8859-1", "de_DE.ISO8859-1", "en_US.US-ASCII")

CORRECT_ACCENTS = "caf\u00e9 con leche, se\u00f1or."


def _non_utf8_locale() -> str | None:
    """Return an installed locale whose preferred encoding is not UTF-8.

    Returns:
        The locale name, or ``None`` when this machine has none — in which case the
        encoding guard cannot be falsified here and the test skips rather than pretending.
    """
    for candidate in NON_UTF8_LOCALES:
        probe = subprocess.run(
            [
                sys.executable,
                "-c",
                "import locale,sys;"
                "print(locale.getpreferredencoding(False), sys.flags.utf8_mode)",
            ],
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "LC_ALL": candidate, "LANG": candidate},
        )
        if probe.returncode != 0:
            continue
        encoding, _, utf8_mode = probe.stdout.strip().partition(" ")
        if "utf" not in encoding.lower() and utf8_mode.strip() == "0":
            return candidate
    return None


def test_non_ascii_text_is_decoded_the_same_under_any_locale(accents_pdf: Path) -> None:
    """Accented text survives regardless of the host's locale.

    Decoding is pinned in the engine seam because ``subprocess`` with ``text=True`` and no
    encoding decodes using the **host locale**. Under a genuinely non-UTF-8 locale the same
    bytes come back as mojibake — ``café`` reads ``cafÃ©`` — so extracted text would depend
    on the machine, contradicting the deterministic class ``subplan-procesador-pdf.md`` §3
    declares for this processor.

    The check runs in a **fresh interpreter with a non-UTF-8 locale**. Setting the variable
    in this process would not work: the locale is read at startup. Measured directly, the
    module returns the correct text with the pin and mojibake without it — under
    ``en_US.ISO8859-1`` only, since a UTF-8 locale masks the difference.

    The verdict is compared **inside** the child and returned as an ASCII token. Printing
    the accented text and letting the terminal render it made an earlier version of this
    check contradict itself: the replacement character it showed was the terminal's
    transcoding, not the decoded value.

    Mutation that breaks it: remove ``encoding=ENGINE_ENCODING`` from
    ``run_engine_command``. The child then reports ``False``.
    """
    locale_name = _non_utf8_locale()
    if locale_name is None:
        pytest.skip(
            "no non-UTF-8 locale is installed, so locale-dependent decoding cannot be "
            "exercised here"
        )

    probe = (
        "import sys;"
        "from pathlib import Path;"
        "from docflow.pdf.primitives.text import extract_text_from_page;"
        "print('OK' if sys.argv[2] in extract_text_from_page(Path(sys.argv[1]), 1) "
        "else 'MOJIBAKE')"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe, str(accents_pdf), CORRECT_ACCENTS],
        capture_output=True,
        text=True,
        check=True,
        env={
            **os.environ,
            "LC_ALL": locale_name,
            "LANG": locale_name,
            "PYTHONPATH": _SOURCE_ROOT,
        },
        cwd=_REPO_ROOT,
    )

    assert completed.stdout.strip() == "OK", (
        f"decoding is locale-dependent under {locale_name}: {completed.stdout.strip()}"
    )
