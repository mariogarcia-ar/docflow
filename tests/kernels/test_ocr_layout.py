"""Tests for ``kernel.ocr.layout`` (``E04-04``'s successor / the OCR layout path).

``layout`` is the OCR counterpart of ``pdf layout``, and the two are **not**
interchangeable: ``pdftotext -layout`` returns the reader's own character grid
because a text reader has the font metrics, and a recogniser reports blocks. So
these tests hold the row structure, which is the whole of what this module claims.

Three properties carry the design, and each one has a test that **fails when the
property is broken** rather than a test that merely passes while it holds:

- A row's spread is bounded by the tolerance. The legacy compared against a running
  mean, which admitted rows wider than the tolerance that formed them; the anchor
  is what fixes it, and ``test_a_row_cannot_be_wider_than_the_tolerance`` is the
  falsifier.
- The tolerance is the caller's and has no default. A defaulted constant is a
  threshold inside a kernel (``prd.md`` FR-15), and the signature is the assertion.
- Orientation is a **measurement** that is reported, and the applied orientation is
  a parameter — so a caller that forces the wrong one can see the disagreement in
  the evidence.

One Pylint relaxation is declared for the reason the other suites state: a contract
test restates the names it checks (``duplicate-code``).
"""

# pylint: disable=duplicate-code
# A contract test that reads the module's ``__all__`` and a signature restates
# names the source already carries. Deriving them would make the test agree with
# whatever the source says, which is the vacuity the rest of this suite is written
# to avoid.

from __future__ import annotations

import inspect
from types import MappingProxyType

import pytest

from docflow.kernels import ocr
from docflow.kernels.types import Box, Token


def token(
    text: str, x: float, y: float, width: float = 10.0, height: float = 4.0
) -> Token:
    """Build a token at a position, for the ordering tests.

    Args:
        text: The token's text.
        x: Left edge.
        y: Top edge.
        width: Box width.
        height: Box height.

    Returns:
        The token.

    """
    return Token(
        text=text,
        page=1,
        bbox=Box(x=x, y=y, width=width, height=height),
        confidence=None,
        role="text",
    )


# --- The row structure -------------------------------------------------------


def test_tokens_on_one_row_are_joined_in_reading_order() -> None:
    """Two tokens at the same height are one row, left before right."""
    right = token("VALOR", x=200.0, y=100.0)
    left = token("ETIQUETA", x=20.0, y=100.0)

    # Given right-to-left, so the order in the result is the module's doing.
    result = ocr.layout([right, left], line_tolerance=10.0)

    assert result.reason is None
    assert result.value == "ETIQUETA | VALOR\n"


def test_rows_are_ordered_top_to_bottom() -> None:
    """Rows come out in the order a person reads the page."""
    lower = token("SEGUNDA", x=20.0, y=200.0)
    upper = token("PRIMERA", x=20.0, y=100.0)

    result = ocr.layout([lower, upper], line_tolerance=10.0)

    assert result.value == "PRIMERA\nSEGUNDA\n"


def test_tokens_further_apart_than_the_tolerance_are_separate_rows() -> None:
    """The tolerance is what decides, and it is applied as given."""
    near = ocr.layout(
        [token("A", 20.0, 100.0), token("B", 20.0, 108.0)], line_tolerance=10.0
    )
    far = ocr.layout(
        [token("A", 20.0, 100.0), token("B", 20.0, 108.0)], line_tolerance=5.0
    )

    assert near.value == "A | B\n"
    assert far.value == "A\nB\n"


def test_a_row_cannot_be_wider_than_the_tolerance() -> None:
    """The invariant the legacy violated, and the reason the anchor exists.

    The legacy PoC grouped each box against its row's **running mean**, so a chain
    of boxes each within the tolerance of the *current* mean could drift: with a
    tolerance of 25, its own worked example put 0, 24 and 30 in one row whose spread
    was 30 — a row wider than the tolerance that admits it. Anchoring on the row's
    first member bounds the spread by the tolerance.

    The values below are that example, shifted to centre coordinates, and they are
    chosen because they **discriminate**: the anchor gives two rows and the running
    mean gives one, so a mutation back to the mean fails this test rather than
    passing it. An earlier version of this test used a chain whose every step
    exceeded the tolerance from both readings, and it passed against the mutant —
    a vacuous test, which is the failure this suite is written to avoid.
    """
    tolerance = 25.0
    tokens = [
        token("A", 20.0, 0.0),  # centre 2
        token("B", 20.0, 24.0),  # centre 26 — 24 from the anchor, so it joins
        token("C", 20.0, 30.0),  # centre 32 — 30 from the anchor: a new row
    ]

    result = ocr.layout(tokens, line_tolerance=tolerance)

    assert result.value == "A | B\nC\n", (
        "the anchor must place C in a row of its own: it is 30 from the row's "
        "first member, while the tolerance is 25. A running mean would drift to "
        "32 and admit it, producing one row of spread 30."
    )
    # Stated as a count as well, because the assertion above is the one a mutation
    # changes and this is the one a reader checks.
    assert len([row for row in (result.value or "").splitlines() if row]) == 2


# --- The tolerance is the caller's -------------------------------------------


def test_line_tolerance_has_no_default() -> None:
    """A keyword-only parameter with no default is the assertion.

    A default here would be a threshold inside a kernel, which `prd.md` FR-15
    forbids: what counts as the same row depends on the resolution the tokens were
    read at, so a constant in the signature would mean different things at
    different DPIs and would be invisible at every call site.
    """
    signature = inspect.signature(ocr.layout)
    parameter = signature.parameters["line_tolerance"]

    assert parameter.default is inspect.Parameter.empty, (
        "line_tolerance must not be defaulted: the legacy's 25.0 was in PDF points, "
        "so a constant here would mean a fifth of a row at 300 DPI"
    )
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY


def test_a_non_positive_tolerance_is_refused() -> None:
    """Zero would put every token in a row of its own and call it a reading."""
    with pytest.raises(ValueError, match="must be positive"):
        ocr.layout([token("A", 20.0, 100.0)], line_tolerance=0.0)

    with pytest.raises(ValueError, match="must be positive"):
        ocr.layout([token("A", 20.0, 100.0)], line_tolerance=-1.0)


def test_an_unknown_orientation_is_refused_rather_than_guessed() -> None:
    """Guessing would return a reading the caller did not ask for."""
    with pytest.raises(ValueError, match="orientation must be one of"):
        ocr.layout(
            [token("A", 20.0, 100.0)], line_tolerance=10.0, orientation="diagonal"
        )


# --- Orientation is a measurement --------------------------------------------


def test_dominant_orientation_counts_the_boxes_it_measured() -> None:
    """Both the winner and the counts are returned, so weak evidence is visible."""
    wide = token("ANCHO", 0.0, 0.0, width=100.0, height=10.0)
    wide2 = token("ANCHO2", 0.0, 20.0, width=80.0, height=10.0)
    tall = token("L", 0.0, 40.0, width=5.0, height=40.0)

    orientation, counts = ocr.dominant_orientation([wide, wide2, tall])

    assert orientation == "horizontal"
    assert counts == {"horizontal": 2.0, "vertical": 1.0}


def test_a_tie_reports_horizontal() -> None:
    """The reading default, and it is the benign direction."""
    wide = token("ANCHO", 0.0, 0.0, width=100.0, height=10.0)
    tall = token("ALTO", 0.0, 20.0, width=5.0, height=40.0)

    orientation, counts = ocr.dominant_orientation([wide, tall])

    assert orientation == "horizontal"
    assert counts == {"horizontal": 1.0, "vertical": 1.0}


def test_no_tokens_reports_horizontal_with_zero_counts() -> None:
    """An empty selection is a measurement of zero, not a missing answer."""
    assert ocr.dominant_orientation([]) == (
        "horizontal",
        {"horizontal": 0.0, "vertical": 0.0},
    )


def test_vertical_orientation_orders_by_column() -> None:
    """The rotated reading: groups form along x and order along y.

    Two tokens sharing an ``x`` are one column, so they are joined with the
    separator; the column further right is a second row.
    """
    bottom = token("ABAJO", 100.0, 200.0, width=5.0, height=30.0)
    top = token("ARRIBA", 100.0, 40.0, width=5.0, height=30.0)
    other = token("OTRA", 300.0, 50.0, width=5.0, height=30.0)

    result = ocr.layout(
        [bottom, top, other], line_tolerance=10.0, orientation="vertical"
    )

    assert result.value == "ARRIBA | ABAJO\nOTRA\n"


# --- Evidence -----------------------------------------------------------------


def test_the_evidence_says_what_kind_of_reading_this_is() -> None:
    """`rows_from_boxes`, not a grid, so a reader of the envelope cannot confuse it."""
    result = ocr.layout([token("A", 20.0, 100.0)], line_tolerance=10.0)

    assert result.evidence.observed["reading"] == "rows_from_boxes"
    assert result.evidence.observed["row_test"] == "anchor"
    assert result.evidence.observed["orientation"] == "horizontal"
    assert result.evidence.measurements["line_tolerance_applied"] == 10.0


def test_the_evidence_reports_what_was_read_and_what_was_placed() -> None:
    """A whitespace-only token is read and not placed, and both numbers are reported."""
    result = ocr.layout(
        [token("A", 20.0, 100.0), token("   ", 20.0, 200.0)], line_tolerance=10.0
    )

    assert result.evidence.measurements["tokens_read"] == 2.0
    assert result.evidence.measurements["tokens_placed"] == 1.0


# --- Failure paths -----------------------------------------------------------


def test_no_usable_tokens_reports_blank_page_with_no_value() -> None:
    """A page with pixels and no characters is a measurement, not a failure."""
    result = ocr.layout([token("   ", 20.0, 100.0)], line_tolerance=10.0)

    assert result.value is None
    assert result.reason is not None
    assert result.reason.code == "blank_page"


def test_an_empty_selection_reports_blank_page() -> None:
    """The same statement, from the same code, as `pdf layout`'s blank."""
    result = ocr.layout([], line_tolerance=10.0)

    assert result.value is None
    assert result.reason is not None
    assert result.reason.code == "blank_page"


def test_a_token_without_a_usable_coordinate_is_refused_not_skipped() -> None:
    """A missing coordinate is a defect in the caller, and it names itself.

    Skipping such a token would silently drop text from a reading, which is the
    class of stand-in the project refuses: the result would look complete and be
    short.
    """
    broken = Token(
        text="X",
        page=1,
        bbox=Box(x="no", y=1.0, width=1.0, height=1.0),  # type: ignore[arg-type]
        confidence=None,
        role="text",
    )

    with pytest.raises(ValueError, match=r"bbox\.x is 'no', not a number"):
        ocr.layout([broken], line_tolerance=10.0)


# --- The module's shape ------------------------------------------------------


def test_the_module_exports_the_three_names_it_claims() -> None:
    """`layout` is public on the kernel and absent from the frozen port."""
    from docflow.ports.ocr import OcrEngine  # pylint: disable=import-outside-toplevel

    assert ocr.__all__ == ["ORIENTATIONS", "dominant_orientation", "layout"]
    assert "horizontal" in ocr.ORIENTATIONS and "vertical" in ocr.ORIENTATIONS
    assert not hasattr(OcrEngine, "layout"), (
        "E04-04 freezes OcrEngine's three operations; layout is kernel-only, and "
        "moving it onto the port is a contract decision that re-opens that gate"
    )


def test_the_module_imports_no_vendor_and_no_adapter() -> None:
    """The analysis is reachable with no engine installed, which is what it buys."""
    source = inspect.getsource(ocr)

    for forbidden in ("import docling", "from docling", "docflow.adapters", "pymupdf"):
        assert forbidden not in source, (
            f"kernel.ocr reached outside its layer: {forbidden!r} appears in it"
        )


def test_the_separator_is_the_one_the_output_uses() -> None:
    """Declared as a constant, and it collides with Markdown's table cell on purpose.

    The collision is worth a test rather than a comment: a caller that feeds this
    text to a Markdown renderer must know that a `|` here means *adjacency* and not
    a table cell, and a rename that quietly changed the character would change what
    every stored reading means.
    """
    assert ocr.SEPARATOR == " | "

    result = ocr.layout(
        [token("A", 20.0, 100.0), token("B", 60.0, 100.0)], line_tolerance=10.0
    )

    assert result.value == "A | B\n"


def test_evidence_mappings_are_immutable() -> None:
    """The boundary types are frozen, and the record they carry with them must be."""
    result = ocr.layout([token("A", 20.0, 100.0)], line_tolerance=10.0)

    assert isinstance(result.evidence.observed, MappingProxyType)
    assert isinstance(result.evidence.measurements, MappingProxyType)
