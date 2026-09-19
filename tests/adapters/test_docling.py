"""Tests for the Docling ``OcrEngine`` adapter (``E04-04`` / ``S1-T14``).

The engine is a heavyweight, platform-specific dependency, so the tests split in
two: the **boundary** is exercised with a stub converter that produces the engine's
document shape, and a small **real-engine** class runs only when Docling is importable
and a model is already present. That split is `plan-01-kernels.md` §13 Track 1's
"Docling is deliberately faked behind `OcrEngine` for the fast flow" — the port, not
the engine, is what Stage 1 fixes.

The assertions that matter, one per silent-failure row:

- ``test_a_page_the_engine_reports_nothing_for_is_blank_not_read`` — row 9. The
  status is ``blank``, never ``read`` with an invented token list.
- ``test_confidence_is_none_and_never_coerced`` — row 10. Docling reports no
  confidence at all, so every token's is ``None``.
- ``test_a_truncated_read_is_visible_in_the_page_accounting`` — row 11. What was
  asked for and what was read are both reported.

Pylint relaxations are declared for the reasons the other suites state: a contract
test restates the names it checks (``duplicate-code``), one test per behaviour costs
file length (``too-many-lines``, ``redefined-outer-name``).
"""

# pylint: disable=duplicate-code
# pylint: disable=redefined-outer-name
# pylint: disable=too-few-public-methods
# The seven stubs below reproduce the engine's document shape and nothing else: a
# box, a provenance record, an item, a page, a document, a conversion result and a
# converter. Each is a one-purpose stand-in, so "too few public methods" is the
# description of the design rather than a defect in it — adding a second method
# would give a stub behaviour the real object does not have.
# pylint: disable=too-many-lines

from __future__ import annotations

import pathlib

import pytest

from docflow.adapters.docling import DoclingEngine
from docflow.ports import OcrEngine, PageStatus

# --- A stub that reproduces the engine's document shape ----------------------


class _Box:
    """The engine's bounding box, origin included."""

    def __init__(self, left: float, top: float, right: float, bottom: float) -> None:
        self.l = left
        self.t = top
        self.r = right
        self.b = bottom
        self.coord_origin = "CoordOrigin.BOTTOMLEFT"


class _Prov:
    """One provenance record: which page, and where on it."""

    def __init__(self, page_no: int, box: _Box) -> None:
        self.page_no = page_no
        self.bbox = box
        self.charspan = (0, 1)


class _Item:
    """One document item: its text, its label and where it came from."""

    def __init__(self, text: str, label: str, prov: list[_Prov] | None) -> None:
        self.text = text
        self.label = label
        self.prov = prov


class _Cell:
    """One table cell, with its own box and its grid position.

    A cell's box is **top-left**, unlike the table's own provenance box, which is
    the difference the real engine has and the reason the adapter reads the origin
    from the box rather than assuming one.

    The attribute count is above Pylint's ceiling because this is a fake of the
    engine's cell type, not a value of ours: it holds the four grid indices, the
    two header flags and the box and text, which is what the real type carries.
    Dropping the indices would make the fake agree with the adapter's current
    reading rather than with the engine's model.
    """

    # pylint: disable=too-many-instance-attributes

    def __init__(
        self,
        text: str,
        box: _Box | None,
        row: int = 0,
        col: int = 0,
    ) -> None:
        self.text = text
        self.bbox = box
        self.start_row_offset_idx = row
        self.end_row_offset_idx = row + 1
        self.start_col_offset_idx = col
        self.end_col_offset_idx = col + 1
        self.column_header = False
        self.row_header = False


def _cell_box(left: float, top: float, right: float, bottom: float) -> _Box:
    """Build a cell box with the top-left origin the engine reports for a cell."""
    box = _Box(left, top, right, bottom)
    box.coord_origin = "CoordOrigin.TOPLEFT"
    return box


class _TableData:
    """The cells and the grid of a table."""

    def __init__(self, cells: list[_Cell]) -> None:
        self.table_cells = cells
        self.num_rows = 1
        self.num_cols = len(cells)
        self.grid = [[cell] for cell in cells]


class _Table:
    """A table item: no ``text`` of its own, cells with their own boxes."""

    def __init__(self, cells: list[_Cell], prov: list[_Prov] | None) -> None:
        self.data = _TableData(cells)
        self.prov = prov
        self.label = "table"
        # Deliberately absent: a real ``TableItem`` carries no ``text`` member,
        # and that absence is the whole reason the cells vanish without the flag.


class _Size:
    """A page's dimensions."""

    def __init__(self, width: float, height: float) -> None:
        self.width = width
        self.height = height


class _Page:
    """A document page."""

    def __init__(self, width: float, height: float) -> None:
        self.size = _Size(width, height)


class _Document:
    """The engine's document model, reduced to what the adapter reads."""

    def __init__(
        self, pages: int, items: list[_Item], tables: list[_Table] | None = None
    ) -> None:
        self.pages = {n: _Page(600.0, 800.0) for n in range(1, pages + 1)}
        self._items = items
        # ``None`` is not the same as ``[]``: the real model always exposes the
        # attribute, and a fake that omitted it would let the adapter's ``or []``
        # guard go untested.
        self.tables = [] if tables is None else tables

    def iterate_items(self) -> list[tuple[_Item, int]]:
        """Yield the items with their nesting level."""
        return [(item, 0) for item in self._items]


class _Converted:
    """What a conversion returns."""

    def __init__(self, document: _Document) -> None:
        self.document = document


class _StubConverter:
    """A converter that returns a prepared document."""

    def __init__(self, document: _Document) -> None:
        self._document = document
        self.calls: list[str] = []

    def convert(self, path: str) -> _Converted:
        """Record the call and return the prepared document."""
        self.calls.append(path)

        return _Converted(self._document)


class _RaisingConverter:
    """A converter that fails the way the engine fails on unreadable bytes."""

    def convert(self, path: str) -> _Converted:
        """Raise, to exercise the refusal path."""
        raise ValueError(f"cannot convert {path}")


def _engine_with(document: _Document) -> tuple[DoclingEngine, _StubConverter]:
    """Build an adapter over a stub converter.

    Args:
        document: The document the stub should return.

    Returns:
        The adapter and the stub, so a test can inspect what was called.

    """
    stub = _StubConverter(document)
    return DoclingEngine(engine=stub), stub


@pytest.fixture
def one_item_document() -> _Document:
    """A one-page document carrying a single positioned item."""
    return _Document(
        1,
        [
            _Item(
                "FACTURA TOTAL 15400.00",
                "text",
                [_Prov(1, _Box(37.0, 183.0, 165.0, 166.0))],
            )
        ],
    )


@pytest.fixture
def a_file(tmp_path: pathlib.Path) -> pathlib.Path:
    """A path that exists, so the adapter reaches the converter."""
    target = tmp_path / "documento.png"
    target.write_bytes(b"\x89PNG\r\n\x1a\nstub")

    return target


# --- The port contract -------------------------------------------------------


def test_the_adapter_satisfies_the_port() -> None:
    """The adapter is structurally an ``OcrEngine``."""
    assert isinstance(DoclingEngine(engine=_StubConverter(_Document(1, []))), OcrEngine)


def test_capabilities_reports_the_engine_and_its_granularity() -> None:
    """``capabilities`` describes the engine without touching a document."""
    engine, _ = _engine_with(_Document(1, []))

    result = engine.capabilities()

    assert result.value is not None
    assert result.value.observed["engine"] == "docling"
    assert result.value.observed["granularity"] == "block"
    assert result.value.observed["reports_confidence"] is False, (
        "the engine reports no confidence; claiming otherwise would invite a "
        "caller to read a value that does not exist"
    )


def test_engine_info_is_populated_and_carries_the_revision() -> None:
    """``engine_info`` is the value that feeds the cache key."""
    engine, _ = _engine_with(_Document(1, []))

    result = engine.engine_info()

    assert result.value is not None
    assert result.value.observed["engine"] == "docling"
    assert "engine_version" in result.value.observed
    assert result.value.terms["engine"] == "docling"


# --- Reading -----------------------------------------------------------------


def test_read_returns_the_text_with_its_box(a_file: pathlib.Path) -> None:
    """A read item becomes a token carrying its text and its page."""
    engine, _ = _engine_with(
        _Document(
            1,
            [
                _Item(
                    "TOTAL 15400.00",
                    "text",
                    [_Prov(1, _Box(37.0, 183.0, 165.0, 166.0))],
                )
            ],
        )
    )

    result = engine.read(a_file, [1], dpi=72, lang="es", tables=False)

    assert result.value is not None
    assert len(result.value.tokens) == 1

    token = result.value.tokens[0]
    assert token.text == "TOTAL 15400.00"
    assert token.page == 1
    assert token.bbox.width == pytest.approx(128.0)
    assert token.bbox.height == pytest.approx(17.0)


def test_the_box_is_flipped_into_top_left_source_coordinates(
    a_file: pathlib.Path,
) -> None:
    """A bottom-left box becomes a top-left one using the **page's** height.

    The fixture places the item at ``t=183`` on an 800-point page, so its distance
    from the top is ``800 - 183 = 617``. Deriving the height from the box instead
    (``t + b``) gives a different, wrong answer — which is why the height comes from
    the document model and a missing height yields no box rather than a guessed one.
    """
    engine, _ = _engine_with(
        _Document(
            1,
            [_Item("x", "text", [_Prov(1, _Box(10.0, 183.0, 20.0, 166.0))])],
        )
    )

    result = engine.read(a_file, [1], dpi=72, lang="es", tables=False)

    assert result.value is not None
    token = result.value.tokens[0]
    assert token.bbox.y == pytest.approx(800.0 - 183.0), (
        "the y must be measured from the page's top, which needs the page height"
    )


def test_the_box_scales_with_the_requested_resolution(a_file: pathlib.Path) -> None:
    """The same item at 144 DPI has a box twice the size of the one at 72."""
    document = _Document(
        1, [_Item("x", "text", [_Prov(1, _Box(10.0, 183.0, 20.0, 166.0))])]
    )
    engine, _ = _engine_with(document)

    at_72 = engine.read(a_file, [1], dpi=72, lang="es", tables=False).value
    at_144 = engine.read(a_file, [1], dpi=144, lang="es", tables=False).value

    assert at_72 is not None and at_144 is not None
    assert at_144.tokens[0].bbox.x == pytest.approx(at_72.tokens[0].bbox.x * 2)
    assert at_144.tokens[0].bbox.width == pytest.approx(at_72.tokens[0].bbox.width * 2)


# --- Row 10: missing confidence read as perfect -----------------------------


def test_confidence_is_none_and_never_coerced(a_file: pathlib.Path) -> None:
    """Every token's confidence is ``None``, because the engine reports none.

    ``1.0`` would be a claim nobody made. It is also not `0.0`, which would read as
    a claim of total failure. The absence is the honest value.
    """
    engine, _ = _engine_with(
        _Document(
            1,
            [
                _Item("a", "text", [_Prov(1, _Box(1.0, 2.0, 3.0, 1.0))]),
                _Item("b", "text", [_Prov(1, _Box(1.0, 9.0, 3.0, 8.0))]),
            ],
        )
    )

    result = engine.read(a_file, [1], dpi=72, lang="es", tables=False)

    assert result.value is not None
    assert result.value.tokens
    assert all(token.confidence is None for token in result.value.tokens)
    assert not any(token.confidence == 1.0 for token in result.value.tokens)


# --- Row 9: a blank page returning invented text ----------------------------


def test_a_page_the_engine_reports_nothing_for_is_blank_not_read(
    a_file: pathlib.Path,
) -> None:
    """A page with no items reports ``blank``, never ``read`` with tokens.

    The failure this catches is an adapter that marks every requested page ``read``
    and simply returns an empty list for the empty ones — which makes *the engine
    read this page and it held nothing* indistinguishable from *the engine could not
    read it*.
    """
    engine, _ = _engine_with(_Document(1, []))

    result = engine.read(a_file, [1], dpi=72, lang="es", tables=False)

    assert result.value is not None
    assert result.value.page_status[1] is PageStatus.BLANK
    assert result.value.tokens == ()

    # The presence of the status is what distinguishes `blank` from a missing page:
    # the page was reached and reported on.
    assert 1 in result.value.page_status


def test_a_page_with_items_is_read(a_file: pathlib.Path) -> None:
    """A page carrying items reports ``read``, so the status carries information."""
    engine, _ = _engine_with(
        _Document(1, [_Item("x", "text", [_Prov(1, _Box(1.0, 2.0, 3.0, 1.0))])])
    )

    result = engine.read(a_file, [1], dpi=72, lang="es", tables=False)

    assert result.value is not None
    assert result.value.page_status[1] is PageStatus.READ


def test_a_blank_page_and_a_read_page_are_distinguishable_in_one_call(
    a_file: pathlib.Path,
) -> None:
    """Two pages, one with text and one without, get different statuses."""
    engine, _ = _engine_with(
        _Document(
            2, [_Item("solo en la 1", "text", [_Prov(1, _Box(1.0, 2.0, 3.0, 1.0))])]
        )
    )

    result = engine.read(a_file, [1, 2], dpi=72, lang="es", tables=False)

    assert result.value is not None
    assert result.value.page_status[1] is PageStatus.READ
    assert result.value.page_status[2] is PageStatus.BLANK


# --- Row 11: a truncated page read as a page with no text -------------------


def test_a_truncated_read_is_visible_in_the_page_accounting(
    a_file: pathlib.Path,
) -> None:
    """What was asked for and what was read are both reported.

    The engine reports on the document it was given, so a request for a page the
    document does not have is refused as a usage error rather than silently
    dropped. What the accounting makes visible is the difference between the two
    lists, which is how a truncation stops looking like a page with no text.
    """
    engine, _ = _engine_with(
        _Document(3, [_Item("x", "text", [_Prov(2, _Box(1.0, 2.0, 3.0, 1.0))])])
    )

    result = engine.read(a_file, [1, 2, 3], dpi=72, lang="es", tables=False)

    assert result.value is not None
    assert result.value.pages_requested == (1, 2, 3)
    assert result.value.pages_read == (1, 2, 3)
    assert result.evidence.measurements["pages_requested"] == 3.0
    assert result.evidence.measurements["pages_read"] == 3.0
    assert result.evidence.observed["pages_requested"] == [1, 2, 3]
    assert result.evidence.observed["pages_read"] == [1, 2, 3]


def test_pages_read_is_derived_from_the_statuses(a_file: pathlib.Path) -> None:
    """``ReadResult.pages_read`` cannot disagree with the per-page statuses."""
    engine, _ = _engine_with(
        _Document(2, [_Item("x", "text", [_Prov(2, _Box(1.0, 2.0, 3.0, 1.0))])])
    )

    result = engine.read(a_file, [1, 2], dpi=72, lang="es", tables=False)

    assert result.value is not None
    assert result.value.pages_read == tuple(sorted(result.value.page_status))


# --- Criterion: layout is dropped at the boundary ---------------------------


def test_layout_and_reading_order_do_not_leave_the_adapter(
    a_file: pathlib.Path,
) -> None:
    """No layout, no table structure and no resolved order crosses the boundary.

    The engine's document model carries sections, reading order and item nesting;
    none of it is in the result. The ``role`` is the engine's label, which is a fact
    about the item rather than an ordering imposed on the page.
    """
    engine, _ = _engine_with(
        _Document(
            1,
            [
                _Item("segundo", "text", [_Prov(1, _Box(1.0, 9.0, 3.0, 8.0))]),
                _Item("primero", "text", [_Prov(1, _Box(1.0, 2.0, 3.0, 1.0))]),
            ],
        )
    )

    result = engine.read(a_file, [1], dpi=72, lang="es", tables=False)

    assert result.value is not None
    assert result.evidence.observed["reading_order"] == "not_resolved"
    assert result.evidence.observed["layout_dropped"] is True
    assert [token.text for token in result.value.tokens] == ["segundo", "primero"], (
        "the engine's own order is preserved, not re-sorted: imposing an order here "
        "is the domain layer's job"
    )
    fields = set(type(result.value).__annotations__)
    assert not any("order" in name or "layout" in name for name in fields)


# --- Typed failure paths -----------------------------------------------------


def test_a_missing_file_is_a_typed_reason(tmp_path: pathlib.Path) -> None:
    """An absent file reports ``unsupported_format``, never an empty read."""
    engine, _ = _engine_with(_Document(1, []))

    result = engine.read(
        tmp_path / "no-existe.png", [1], dpi=72, lang="es", tables=False
    )

    assert result.value is None
    assert result.reason is not None
    assert result.reason.code == "unsupported_format"


def test_bytes_the_engine_cannot_read_are_a_typed_reason(
    a_file: pathlib.Path,
) -> None:
    """A conversion failure is reported, not raised."""
    engine = DoclingEngine(engine=_RaisingConverter())

    result = engine.read(a_file, [1], dpi=72, lang="es", tables=False)

    assert result.value is None
    assert result.reason is not None
    assert result.reason.code == "unsupported_format"


def test_a_missing_engine_is_a_typed_reason_and_not_a_substitute(
    a_file: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without the library the call reports why, and reads nothing.

    ``wbs.md`` §9: a missing engine is a typed ``Reason``, never a substitute. The
    engine is fixed by `ADR-001`, so there is no second one to fall back to.
    """
    engine = DoclingEngine()
    monkeypatch.setattr(
        engine, "_converter_or_failure", lambda: (None, _missing_engine_reason())
    )

    result = engine.read(a_file, [1], dpi=72, lang="es", tables=False)

    assert result.value is None
    assert result.reason is not None
    assert result.reason.code == "engine_unavailable"


def _missing_engine_reason():
    """Build the reason a missing engine produces.

    Returns:
        A ``Reason`` with the ``engine_unavailable`` code.

    """
    from docflow.kernels.types import Reason  # pylint: disable=import-outside-toplevel

    return Reason(code="engine_unavailable", message="docling is not installed")


# --- Usage errors ------------------------------------------------------------


def test_an_empty_selection_is_refused(a_file: pathlib.Path) -> None:
    """An empty selection is a usage error, not a licence to read everything."""
    engine, _ = _engine_with(_Document(1, []))

    with pytest.raises(ValueError, match="selection is empty"):
        engine.read(a_file, [], dpi=72, lang="es", tables=False)


def test_a_page_outside_the_document_is_refused(a_file: pathlib.Path) -> None:
    """A page the document does not have is a usage error."""
    engine, _ = _engine_with(_Document(1, []))

    with pytest.raises(ValueError, match="outside the document"):
        engine.read(a_file, [1, 9], dpi=72, lang="es", tables=False)


def test_a_non_positive_dpi_is_refused(a_file: pathlib.Path) -> None:
    """A zero or negative resolution is a usage error."""
    engine, _ = _engine_with(_Document(1, []))

    with pytest.raises(ValueError, match="dpi must be positive"):
        engine.read(a_file, [1], dpi=0, lang="es", tables=False)


# --- The engine is not a setting --------------------------------------------


def test_the_adapter_exposes_no_engine_setting() -> None:
    """There is no parameter that selects an engine, and no engine member.

    `ADR-001` and `prd.md` FR-16: the engine is Docling and only Docling. An
    ``engine=``-shaped *setting* would be a matrix of behaviours; the constructor's
    ``engine`` argument is an injected converter for tests, and this test states the
    difference so the two cannot be confused.
    """
    import inspect  # pylint: disable=import-outside-toplevel

    signature = inspect.signature(DoclingEngine.__init__)
    assert list(signature.parameters) == ["self", "engine"]

    source = inspect.getsource(DoclingEngine)
    assert "--engine" not in source
    assert "ocrmac" not in source and "tesseract" not in source, (
        "a second engine would make the OCR path a matrix of behaviours"
    )


# --- The reason vocabulary ---------------------------------------------------


def test_every_reason_code_raised_here_is_in_the_closed_set() -> None:
    """The codes this adapter can raise are the ones `kernel-cli.md` §5 declares.

    A code outside that set would be unassertable by the silent-failure suite,
    because the suite targets codes and a novel one would have no row behind it.
    """
    # Imported here so the module under test is reached through the package the
    # adapter actually ships in, not through the class the tests already hold.
    # pylint: disable=import-outside-toplevel
    from docflow.adapters import docling as module

    closed_set = {"engine_unavailable", "unsupported_format", "blank_page"}
    declared = {
        value for name, value in vars(module).items() if name.startswith("_CODE_")
    }

    assert declared, "the adapter declares reason codes, so this is not vacuous"
    assert declared <= closed_set, (
        f"codes outside the closed set: {declared - closed_set}"
    )


# --- The `tables` parameter --------------------------------------------------


def _invoice_with_a_table() -> _Document:
    """A page carrying body text and a two-cell table.

    The table is what `E04-04` dropped: a ``TableItem`` has no ``text`` of its own,
    so the filter that keeps text-carrying items loses the whole construct. The
    cells below are the two columns of one row, and the body item is there so the
    page is not solely a table.
    """
    return _Document(
        1,
        [_Item("cuerpo", "text", [_Prov(1, _Box(1.0, 20.0, 3.0, 19.0))])],
        [
            _Table(
                [
                    _Cell(
                        "EZ9F34110", _cell_box(20.0, 249.0, 62.0, 257.0), row=0, col=0
                    ),
                    _Cell(
                        "8.613,90", _cell_box(543.0, 249.0, 560.0, 257.0), row=0, col=8
                    ),
                ],
                [_Prov(1, _Box(19.0, 597.0, 575.0, 560.0))],
            )
        ],
    )


def test_table_cells_are_dropped_by_default(a_file: pathlib.Path) -> None:
    """The default is what every existing caller receives, and it is unchanged.

    `E04-04` froze this port with the cells dropped and its criterion 3 asserts
    `layout_dropped`, so the inclusion is opt-in: inverting the default would change
    what every caller gets without re-opening that gate.
    """
    engine, _ = _engine_with(_invoice_with_a_table())

    result = engine.read(a_file, [1], dpi=72, lang="es", tables=False)

    assert result.value is not None
    assert [token.text for token in result.value.tokens] == ["cuerpo"]
    assert result.evidence.observed["tables"] == "dropped"


def test_table_cells_join_the_reading_when_asked_for(a_file: pathlib.Path) -> None:
    """`tables=True` recovers the cells, which is the defect this parameter closes.

    Measured on `casos/66cd35e9`: 42 tokens without the flag and 69 with it, and the
    row naming `EZ9F34110` is absent from the first and present in the second.
    """
    engine, _ = _engine_with(_invoice_with_a_table())

    result = engine.read(a_file, [1], dpi=72, lang="es", tables=True)

    assert result.value is not None
    texts = [token.text for token in result.value.tokens]
    assert texts == ["cuerpo", "EZ9F34110", "8.613,90"], (
        "the cells are reported in the engine's own order, after the body items, "
        "and no cell is invented or dropped"
    )
    assert result.evidence.observed["tables"] == "cells_included"


def test_a_table_cell_carries_its_own_role_and_box(a_file: pathlib.Path) -> None:
    """A cell is a positioned token, which is what makes a row readable across it.

    The role says which tokens came from a table, so a consumer that wants the
    structure can group them without guessing - and the box is the cell's own, not
    the table's: a token carrying the table's box would have a position no
    measurement supports for the text it holds.
    """
    engine, _ = _engine_with(_invoice_with_a_table())

    result = engine.read(a_file, [1], dpi=72, lang="es", tables=True)

    assert result.value is not None
    cells = [token for token in result.value.tokens if token.role == "table_cell"]
    assert len(cells) == 2

    first = cells[0]
    assert first.bbox.x == pytest.approx(20.0), (
        "the cell's own left edge, not the table's (19.0)"
    )
    assert first.bbox.width == pytest.approx(42.0)
    assert first.confidence is None, "a cell's confidence is not invented either"


def test_a_cell_without_a_box_is_skipped_rather_than_placed(
    a_file: pathlib.Path,
) -> None:
    """A cell with no box has nothing to say about where it is.

    Placing it at a made-up origin would put text at a position the document does
    not have it, which is the synthesis this layer refuses everywhere.
    """
    document = _Document(
        1,
        [],
        [
            _Table(
                [_Cell("sin caja", None)], [_Prov(1, _Box(19.0, 597.0, 575.0, 560.0))]
            )
        ],
    )
    engine, _ = _engine_with(document)

    result = engine.read(a_file, [1], dpi=72, lang="es", tables=True)

    assert result.value is not None
    assert result.value.tokens == ()
    assert result.value.page_status[1] is PageStatus.BLANK


def test_a_table_on_another_page_is_not_reported(a_file: pathlib.Path) -> None:
    """Provenance decides the page, and a cell is not moved onto a page it is not on."""
    document = _Document(
        2,
        [],
        [
            _Table(
                [_Cell("de la pagina 2", _cell_box(20.0, 249.0, 62.0, 257.0))],
                [_Prov(2, _Box(19.0, 597.0, 575.0, 560.0))],
            )
        ],
    )
    engine, _ = _engine_with(document)

    first = engine.read(a_file, [1], dpi=72, lang="es", tables=True)
    second = engine.read(a_file, [2], dpi=72, lang="es", tables=True)

    assert first.value is not None and second.value is not None
    assert first.value.tokens == ()
    assert [token.text for token in second.value.tokens] == ["de la pagina 2"]


def test_a_cell_box_is_not_origin_flipped_twice(a_file: pathlib.Path) -> None:
    """A cell's box is already top-left, and the adapter reads the origin from it.

    The table's *own* provenance box is bottom-left, so a conversion that assumed
    one origin for both would place every cell at the page's height minus its top -
    which lands the text near the wrong edge and looks plausible on a short page.
    """
    engine, _ = _engine_with(_invoice_with_a_table())

    result = engine.read(a_file, [1], dpi=72, lang="es", tables=True)

    assert result.value is not None
    cell = next(t for t in result.value.tokens if t.role == "table_cell")
    # The cell's top is 249.0 and the page is 800 points tall. A flip would give
    # 800 - 257 = 543, so the assertion distinguishes the two rather than passing
    # under both.
    assert cell.bbox.y == pytest.approx(249.0), (
        f"a top-left cell box must pass through unchanged; got {cell.bbox.y}"
    )
