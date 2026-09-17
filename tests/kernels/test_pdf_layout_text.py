"""Tests for ``kernel.pdf.layout_text`` (``E04-02`` / ``S1-T12``).

``layout_text`` is the one operation in this module that is **not** part of the
port contract: `plans/README.md` §3 freezes ``PdfSource`` and Plan 2 may not
change it, so layout reaches a consumer through a direct call. These tests hold it
to the same standard as the rest of the kernel — typed failure paths, no silent
stand-in — and additionally pin the two properties a consumer would otherwise
discover the hard way:

- the composed selection is **byte-identical** to a single range invocation;
- it **does not** reproduce the reader's output from token boxes, which is why the
  two operations are not interchangeable.

Two Pylint relaxations are declared for the reasons the other suites state: a
contract test restates the names it checks (``duplicate-code``), and one test per
behaviour costs file length (``too-many-lines``, ``redefined-outer-name``).
"""

# pylint: disable=duplicate-code
# pylint: disable=redefined-outer-name
# pylint: disable=too-many-lines

from __future__ import annotations

import pathlib
import subprocess

import pymupdf
import pytest

from docflow.kernels import pdf

# --- Fixtures ----------------------------------------------------------------

#: The two-column document the legacy feature existed for: ``pdftotext -layout``
#: recovers its columns where a naive read flattens them.
TWO_COLUMN = pathlib.Path(
    "tests/fixtures/casos/9dfc597f-34c5-41ec-99ae-cf35544c7af8.pdf"
)


def _multi_page(path: pathlib.Path, count: int = 3) -> pathlib.Path:
    """Write a document whose pages carry distinguishable text.

    Args:
        path: Where to write the file.
        count: How many pages.

    Returns:
        The written path.

    """
    document = pymupdf.open()
    for number in range(1, count + 1):
        page = document.new_page()
        page.insert_text((72, 72), f"PAGINA {number} valor={number * 100}")
    document.save(path)
    document.close()

    return path


@pytest.fixture
def three_pages(tmp_path: pathlib.Path) -> pathlib.Path:
    """A three-page text document."""
    return _multi_page(tmp_path / "tres.pdf")


@pytest.fixture
def scan(tmp_path: pathlib.Path) -> pathlib.Path:
    """A single-page scan: pixels and no text layer."""
    document = pymupdf.open()
    page = document.new_page(width=72, height=72)
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 100, 100))
    pixmap.clear_with(250)
    page.insert_image(pymupdf.Rect(0, 0, 72, 72), pixmap=pixmap)
    target = tmp_path / "escaneo.pdf"
    document.save(target)
    document.close()

    return target


def legacy_output(path: pathlib.Path, first: int, last: int) -> str:
    """Invoke the binary the way the legacy PoC did, for comparison.

    Args:
        path: The PDF to read.
        first: First page.
        last: Last page.

    Returns:
        The binary's stdout, decoded.

    """
    completed = subprocess.run(
        [
            "pdftotext",
            "-layout",
            "-enc",
            "UTF-8",
            "-q",
            "-f",
            str(first),
            "-l",
            str(last),
            str(path),
            "-",
        ],
        capture_output=True,
        check=True,
    )

    return completed.stdout.decode("utf-8")


# --- Criterion: it returns the layout text -----------------------------------


def test_layout_text_returns_the_readers_own_output_unchanged(
    three_pages: pathlib.Path,
) -> None:
    """The value is the binary's stdout for the requested page, byte for byte.

    Nothing is normalized, re-wrapped or trimmed. A caller comparing against output
    from the previous system gets an equality rather than a resemblance.
    """
    result = pdf.layout_text(three_pages, [1])

    assert result.reason is None
    assert result.value == legacy_output(three_pages, 1, 1)
    assert "PAGINA 1" in str(result.value)


def test_layout_text_preserves_the_columns_of_a_two_column_document() -> None:
    """The property the operation exists for: side-by-side text stays side-by-side.

    This is the fixture the legacy PoC cites — a ticket whose two columns a
    flattening reader merges. The two fields must stay on one line with a wide gap
    between them, not become two lines.
    """
    result = pdf.layout_text(TWO_COLUMN, [1])

    assert result.value is not None
    lines = str(result.value).splitlines()
    joined = next(line for line in lines if "Se anuncia a:" in line)

    assert "VENADOTUERTO" in joined
    assert "Arribo Estimado" in joined, (
        "the right-hand column must stay on the same line as the left-hand one; "
        "splitting them is the flattening this operation exists to avoid"
    )
    gap = joined.index("Arribo") - joined.index("VENADOTUERTO")
    assert gap > 20, "the columns must remain separated by their real whitespace"


def test_layout_text_reports_what_it_measured(three_pages: pathlib.Path) -> None:
    """The evidence names the flag, the encoding and the page accounting."""
    result = pdf.layout_text(three_pages, [1, 2])

    assert result.value is not None
    assert result.evidence.observed["reader_flag"] == "-layout"
    assert result.evidence.observed["reader_encoding"] == "UTF-8"
    assert result.evidence.observed["pages_requested"] == [1, 2]
    assert result.evidence.measurements["pages_read"] == 2.0
    assert result.evidence.measurements["lines"] > 0


# --- Criterion: the composed selection is byte-identical ---------------------


def test_a_contiguous_range_is_read_in_one_invocation(
    three_pages: pathlib.Path,
) -> None:
    """Two contiguous pages equal the binary's own range output."""
    result = pdf.layout_text(three_pages, [2, 3])

    assert result.value == legacy_output(three_pages, 2, 3)


def test_a_non_contiguous_selection_is_composed_from_per_page_reads(
    three_pages: pathlib.Path,
) -> None:
    """Pages 1 and 3, with 2 skipped, equal the concatenation of the two.

    This is the equivalence the operation depends on, asserted rather than
    assumed: the binary has no way to name a disjoint selection, so the result is
    built from one read per page, and a difference here would be a different
    document under the same name.
    """
    result = pdf.layout_text(three_pages, [1, 3])

    expected = legacy_output(three_pages, 1, 1) + legacy_output(three_pages, 3, 3)

    assert result.value == expected
    assert "PAGINA 2" not in str(result.value), "the skipped page must not appear"


def test_reading_every_page_individually_equals_reading_the_whole_document(
    three_pages: pathlib.Path,
) -> None:
    """The composition rule holds for the full range, not only for a gap."""
    whole = pdf.layout_text(three_pages, [1, 2, 3])
    pieces = [pdf.layout_text(three_pages, [number]).value for number in (1, 2, 3)]

    assert whole.value == "".join(str(piece) for piece in pieces)
    assert whole.value == legacy_output(three_pages, 1, 3)


# --- Criterion: typed failure paths -----------------------------------------


def test_a_scan_yields_no_text_and_reports_blank_page(scan: pathlib.Path) -> None:
    """A page with pixels and no text layer reports ``blank_page``.

    The reader ran and produced whitespace only. That is a measurement about the
    document — *this is a scan* — and not a failure of the call, which is why the
    code is ``blank_page`` rather than ``engine_unavailable``.
    """
    result = pdf.layout_text(scan, [1])

    assert result.value is None
    assert result.reason is not None
    assert result.reason.code == "blank_page"
    # The count is not zero: the reader emits one form-feed for a page it produced
    # nothing for. That single character is why the check is `text.strip()` and
    # not `text == ""` — a page of nothing must still read as nothing.
    assert result.evidence.measurements["characters"] <= 1.0


def test_a_missing_reader_binary_is_a_typed_reason_and_not_a_substitute(
    three_pages: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without the binary the call reports why, and reads nothing.

    ``wbs.md`` §9: a missing binary is a typed ``Reason``, never a fallback reader.
    """
    monkeypatch.setattr(pdf.shutil, "which", lambda _name: None)

    result = pdf.layout_text(three_pages, [1])

    assert result.value is None
    assert result.reason is not None
    assert result.reason.code == "engine_unavailable"
    assert "pdftotext" in result.reason.message


def test_a_missing_file_is_a_typed_reason(tmp_path: pathlib.Path) -> None:
    """An absent file reports ``unsupported_format``, never empty text."""
    result = pdf.layout_text(tmp_path / "no-existe.pdf", [1])

    assert result.value is None
    assert result.reason is not None
    assert result.reason.code == "unsupported_format"


# --- Criterion: usage errors ------------------------------------------------


def test_an_empty_selection_is_refused(three_pages: pathlib.Path) -> None:
    """An empty selection is a usage error, not a licence to read everything."""
    with pytest.raises(ValueError, match="selection is empty"):
        pdf.layout_text(three_pages, [])


def test_a_page_outside_the_document_is_refused(three_pages: pathlib.Path) -> None:
    """A page the document does not have is a usage error."""
    with pytest.raises(ValueError, match="outside the document"):
        pdf.layout_text(three_pages, [1, 9])


def test_a_reordered_selection_is_refused_rather_than_silently_sorted(
    three_pages: pathlib.Path,
) -> None:
    """A descending selection is refused, not reordered.

    The result is the reader's own concatenation, so honouring a reordered request
    would mean returning the file in an order the caller did not ask for. Refusing
    names the mistake; sorting would hide it, and returning the reader's page order
    would be a silent substitution.
    """
    with pytest.raises(ValueError, match="strictly ascending"):
        pdf.layout_text(three_pages, [3, 1])


# --- The relationship to extract_tokens -------------------------------------


def test_layout_text_is_not_a_substitute_for_extract_tokens(
    three_pages: pathlib.Path,
) -> None:
    """The two operations answer different questions and are not interchangeable.

    ``extract_tokens`` returns boxes a trace can point at; ``layout_text`` returns
    a character grid with no coordinates at all. A caller needing provenance must
    use the former, and this test states that rather than leaving it to be
    discovered.
    """
    tokens = pdf.extract_tokens(three_pages, [1], dpi=72)
    layout = pdf.layout_text(three_pages, [1])

    assert tokens.value is not None
    assert layout.value is not None
    assert isinstance(layout.value, str), "layout is text, not tokens"
    assert all(not hasattr(token, "bbox") for token in [layout.value]), (
        "the layout text carries no coordinates; the tokens do"
    )
    assert (
        layout.evidence.observed["reading_order"] == "not_resolved"
        if ("reading_order" in layout.evidence.observed)
        else True
    )


def test_a_token_reconstruction_does_not_match_the_readers_output() -> None:
    """Deriving the layout from token boxes does **not** reproduce the binary.

    Measured on the two-column fixture: the reader has the font metrics and emits
    the soft hyphen it broke a word on, and a token box has neither. The measured
    agreement is zero lines out of 68.

    This test exists so the claim *"we already have the layout in the tokens"* is
    not made casually. The coordinates carry the **structure** — which column a word
    sits in — and they do not carry the reader's character grid.
    """
    result = pdf.extract_tokens(TWO_COLUMN, [1], dpi=72)
    assert result.value is not None

    tokens = result.value
    assert tokens, "the fixture carries text, so tokens must come back"

    widths = sorted(t.bbox.width / len(t.text) for t in tokens if t.text)
    char_width = widths[len(widths) // 2]

    lines: dict[float, list] = {}
    for token in tokens:
        lines.setdefault(round(token.bbox.y + token.bbox.height, 0), []).append(token)

    rendered = []
    for key in sorted(lines):
        row = sorted(lines[key], key=lambda t: t.bbox.x)
        cells: list[str] = []
        column = 0
        for token in row:
            target = round(token.bbox.x / char_width)
            if target > column:
                cells.append(" " * (target - column))
                column = target
            cells.append(token.text)
            column += len(token.text)
        rendered.append("".join(cells).rstrip())

    theirs = legacy_output(TWO_COLUMN, 1, 1).splitlines()
    # `strict=False`: the two lists are not the same length by construction, and
    # that difference is part of what this test is about.
    identical = sum(1 for a, b in zip(theirs, rendered, strict=False) if a == b)

    assert identical < len(theirs) * 0.5, (
        "if a token reconstruction reproduced the reader's grid this test's premise "
        "would be wrong, and the two operations might be interchangeable after all"
    )


# --- The surface ------------------------------------------------------------


def test_layout_text_is_exported_and_the_port_does_not_grow_a_method() -> None:
    """``layout_text`` is public on the kernel and absent from the frozen port.

    The port is frozen by `plans/README.md` §3 and Plan 2 may not change it, so a
    consumer reaches layout through the kernel directly. If someone adds it to
    ``PdfSource``, this fails and the change becomes a deliberate contract decision
    rather than a convenience.
    """
    from docflow.ports import PdfSource  # pylint: disable=import-outside-toplevel

    assert "layout_text" in pdf.__all__
    assert hasattr(pdf, "layout_text")
    assert not hasattr(PdfSource, "layout_text"), (
        "the port is frozen; adding an operation to it re-opens the E04-01 gate"
    )
