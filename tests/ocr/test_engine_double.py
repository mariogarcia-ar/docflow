"""The Docling double's compliance with the engine-double convention (``OCR-14``).

The suite never reaches Docling: the double is installed at the engine call and at the engine
namespace, and it answers with the library's own shapes (`README.md` §9.7). The attribute check of
``tests/fakes/engines/convention.py`` deliberately does not apply here — the OCR seam replaces a
symbol of ours rather than an engine namespace — so what keeps this double honest is the set of
checks below: the native shape, the adversarial order that makes the ordering invariant
falsifiable, and the rule that no test of this processor imports the engine.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.fakes.engines.fake_docling import (
    BODY_LAYER,
    FAKE_ENGINE_VERSION,
    FURNITURE_LAYER,
    FakeConversionStatus,
    FakeCoordOrigin,
    FakeDocling,
    FakeDoclingError,
    empty_document,
    footer_document,
    prepared_document,
)
from tests.ocr.samples import PREPARED
from tests.support import imported_modules


def test_the_double_answers_the_conversion_with_the_engines_own_shape() -> None:
    """A conversion has a status, the engine's errors and a document — never one of our types."""
    conversion = FakeDocling()(PREPARED, {})

    assert conversion.status is FakeConversionStatus.SUCCESS
    assert not conversion.errors
    assert conversion.document is not None
    assert not hasattr(conversion, "OCRResult")
    assert not hasattr(conversion.document, "OCRDocument")


def test_the_document_exposes_the_surface_the_seam_reads() -> None:
    """``iterate_items``, the two exports, the table view and the pages: nothing else is needed."""
    document = FakeDocling()(PREPARED, {}).document

    assert callable(document.export_to_text)
    assert callable(document.export_to_markdown)
    assert isinstance(document.export_to_text(), str)
    assert isinstance(document.export_to_markdown(), str)
    assert len(list(document.iterate_items())) == len(document.items)
    assert len(document.tables) == 1
    assert min(document.pages) == 1


def test_the_boxes_are_reached_through_the_engines_own_provenance() -> None:
    """The shape the seam unwraps is the engine's: ``prov[0].bbox`` **in its own origin**.

    The engine reports this processor's pages in ``BOTTOMLEFT`` and hands a box over as
    ``(l, b, r, t)``, so the second value is the one nearer the bottom: the fixtures' top-down
    rectangle ``(12, 96, 204, 108)`` arrives here as ``(12, 12, 204, 24)`` on a 120-pixel page.
    Asserting the converted numbers instead would assert our conversion back at itself, and would
    keep letting a seam that ignores the origin pass.
    """
    item, _level = next(iter(FakeDocling()(PREPARED, {}).document.iterate_items()))

    assert item.prov[0].page_no == 1
    assert item.prov[0].bbox.coord_origin == FakeCoordOrigin.BOTTOMLEFT
    assert item.prov[0].bbox.as_tuple() == (12.0, 12.0, 204.0, 24.0)


def test_the_items_come_back_in_adversarial_order() -> None:
    """A fake that handed back already-sorted blocks would let a broken sort pass.

    The numbers are the engine's own — measured from the bottom — so the caption the double hands
    over *first* is the one nearest the bottom of the page and carries the *smallest* ``t``. An
    assertion written the other way round would be asserting a top-down box the engine never
    reports.
    """
    document = FakeDocling()(PREPARED, {}).document
    tops = [item.prov[0].bbox.t for item, _level in document.iterate_items()]

    assert tops != sorted(tops)
    assert tops[0] < tops[-1]


def test_a_page_footer_is_filed_outside_the_body_and_hidden_until_it_is_asked_for() -> (
    None
):
    """The layer rule is modelled, not assumed: ``furniture`` is left out unless it is stated.

    This is the shape that lost a fiscal code in silence. A double that handed the footer over
    with the body could only ever agree with a seam that asked for nothing.
    """
    document = footer_document(240.0, 120.0)
    both = {BODY_LAYER, FURNITURE_LAYER}

    assert "CAE N°: 86327284406071" not in [
        item.text for item, _level in document.iterate_items()
    ]
    assert "CAE N°: 86327284406071" in [
        item.text
        for item, _level in document.iterate_items(included_content_layers=both)
    ]
    assert "CAE N°: 86327284406071" not in document.export_to_text()
    assert "CAE N°: 86327284406071" in document.export_to_text(
        included_content_layers=both
    )


def test_a_table_is_a_document_item_and_a_table_view_at_once() -> None:
    """The engine yields tables from its item iterator and exposes them again as tables."""
    document = FakeDocling()(PREPARED, {}).document

    assert document.tables[0] in document.items
    assert document.tables[0].data.num_rows == 2
    assert [cell.text for cell in document.tables[0].data.table_cells] == [
        "Region",
        "Revenue",
        "North",
        "120",
    ]


def test_the_empty_document_holds_nothing_and_still_has_a_page() -> None:
    """The emptiness is data: a page was converted, and nothing was found on it."""
    document = empty_document(240.0, 120.0)

    assert not document.items
    assert not document.tables
    assert document.export_to_text() == ""
    assert document.export_to_markdown() == ""
    assert document.pages[1].size.width == 240.0


def test_the_double_reports_a_version_and_the_seam_reads_it() -> None:
    """The version is what makes a re-run comparable, so the double has to expose one."""
    assert FakeDocling.__version__ == FAKE_ENGINE_VERSION
    assert isinstance(FAKE_ENGINE_VERSION, str)
    assert FAKE_ENGINE_VERSION


def test_the_double_can_fail_the_way_the_engine_fails() -> None:
    """An exception during conversion is reachable with no engine installed."""
    with pytest.raises(FakeDoclingError):
        FakeDocling(raises=FakeDoclingError("the layout model refused this page"))(
            PREPARED, {}
        )


def test_the_double_records_every_conversion_it_was_asked_for() -> None:
    """A test can prove that no conversion happened, or which file was converted."""
    fake = FakeDocling()

    assert not fake.calls
    fake(PREPARED, {})

    assert fake.calls == [PREPARED]


def test_the_page_frame_is_the_files_own(tmp_path: Path) -> None:
    """The frame is read from the file, so a document never describes a page nobody handed over."""
    not_a_png = tmp_path / "page.png"
    not_a_png.write_bytes(b"this is not a PNG at all")

    with pytest.raises(ValueError):
        FakeDocling()(not_a_png, {})


def test_the_double_does_not_import_our_types() -> None:
    """A double that models our types is drifting into the layer it must exercise."""
    double = (
        Path(__file__).resolve().parents[1] / "fakes" / "engines" / "fake_docling.py"
    )
    imported = {name for _line, name in imported_modules(double)}

    assert not [module for module in imported if module.startswith("docflow")]


def test_no_test_of_this_processor_imports_the_engine() -> None:
    """The suite proves our translation, and it must run with Docling absent (`README.md` §9.7)."""
    offenders = [
        f"{path.name}:{line} imports {name}"
        for path in sorted(Path(__file__).resolve().parent.rglob("*.py"))
        for line, name in imported_modules(path)
        if name.split(".")[0] == "docling"
    ]

    assert not offenders, f"a test reaches the engine: {offenders}"


def test_the_prepared_document_describes_the_page_the_fixture_is() -> None:
    """Its boxes stay inside the frame the fixture declares, so the page and the content agree."""
    document = prepared_document(240.0, 120.0)

    boxes = [item.prov[0].bbox.as_tuple() for item in document.items if item.prov]
    assert boxes
    for left, top, right, bottom in boxes:
        assert 0 <= left < right <= 240
        assert 0 <= top < bottom <= 120
