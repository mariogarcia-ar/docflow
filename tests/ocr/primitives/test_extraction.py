# pylint: disable=broad-exception-caught,protected-access
# Two deliberate boundary tests. `test_no_bad_input_leaks_a_bare_exception_type` catches
# `Exception` on purpose: the claim is that *nothing* Docling raises crosses the seam, so the
# check has to be able to see every exception and fail on the ones that are not the seam's.
# And two tests reach `_build_image_converter` and `_render_table`, which are private because they
# are not the plan's surface - but they are exactly where the invariant lives: the converter build
# is the failure boundary, and the renderer's padding is what keeps a ragged grid from producing a
# broken Markdown table. Testing them through the public path would mean provoking a Docling
# internals failure and committing a ragged fixture to reach the same assertion.
"""End-to-end extraction tests against the engine (``OCR-04``).

These are **integration tests**: they run Docling for real over a committed fixture. That is a
deliberate choice over mocking, and it is what the acceptance criteria demand — the criterion names
a fixture and a run, not a simulated one. The cost is real (seconds per conversion, and the model
files must be present), so the module is small and every test earns its conversion.

What is *not* integration is the mapping logic: the label table and the bbox reader are exercised
against plain stand-ins too, so a change to the mapping is caught without paying for a conversion.

The fixture is ``tests/fixtures/ocr/ocr_prepared_text_and_table.png``, which this task's criterion
names. ``OCR-12`` owns the fixture set; it is built by ``scripts/tools/ocr_fixture.py``, which
prepares a real invoice from the corpus with the *image* processor — because "prepared" is what
that pipeline produces, and the documented flow is `PDF` → `image` → `ocr`.
"""

from __future__ import annotations

import json
import typing
from pathlib import Path
from types import SimpleNamespace

import pytest

from docflow.image.contracts import ImageOptions
from docflow.image.primitives.analyze import analyze_image
from docflow.image.primitives.engine import EngineChoice
from docflow.image.primitives.load import load_image, save_image
from docflow.image.primitives.transform import convert_to_grayscale
from docflow.image.primitives.variants import prepare_image_for_ocr
from docflow.ocr.contracts import (
    BlockResult,
    LayoutResult,
    OCRBlockType,
    OCRDocument,
    TableResult,
)
from docflow.ocr.primitives import execution, export, extraction
from docflow.ocr.primitives.engine import (
    OCREngineExecutionError,
    OCREngineNotAvailableError,
)
from docflow.ocr.primitives.extraction import (
    DOCLING_LABEL_TO_BLOCK_TYPE,
    _bbox_of,
    _label_value,
)
from tests.ocr.primitives import probes
from tests.ocr.primitives.engine_corpus import (
    DOCUMENT_JSON_SECTIONS,
    FIXTURE,
    REPO_ROOT,
    configured_pipeline,
    extracted_document,
)

FIXTURES = REPO_ROOT / "tests" / "fixtures"
SOURCE = FIXTURES / "expected-extraction" / "9e0fd65b-7db2-40a1-9959-ab13e7b030cd.jpg"


# ======================================================================================
# Acceptance criterion 1 — a heading, a paragraph and a table with its cells
# ======================================================================================


def test_the_document_contains_a_heading_a_paragraph_and_a_table_with_cells() -> None:
    """The acceptance criterion, verbatim."""
    document = extracted_document()

    assert document.titles, "no heading was extracted"
    assert document.paragraphs, "no paragraph was extracted"
    assert document.tables, "no table was extracted"

    table = document.tables[0]
    assert table.cells, "the table carries no cells"
    assert all(isinstance(row, list) for row in table.cells)
    assert any(cell.strip() for row in table.cells for cell in row), (
        "every cell is blank"
    )


def test_the_heading_and_paragraphs_are_real_text() -> None:
    """The content is text, not an empty structure that satisfies the shape.

    Worth asserting separately: a mapping that produced the right *shape* with empty strings would
    pass the criterion above and be useless.
    """
    document = extracted_document()

    assert all(title.strip() for title in document.titles)
    assert all(paragraph.strip() for paragraph in document.paragraphs)
    assert len(document.text.strip()) > 100


def test_the_table_is_rectangular_and_multi_row() -> None:
    """The criterion says "a table with its cells"; a 1x1 mis-detection is not one.

    Both halves matter. A single row means the table model found a line rather than a grid, and a
    ragged grid would break every renderer downstream — which is why ``export._render_table`` pads
    rows and why this asserts the input it receives is already rectangular.
    """
    cells = extracted_document().tables[0].cells
    widths = {len(row) for row in cells}

    assert len(cells) >= 2, f"the table has one row: {cells}"
    assert len(widths) == 1, f"the table's rows are ragged: {widths}"
    assert max(widths) >= 2, f"the table has one column: {cells}"


def test_the_document_is_engine_independent() -> None:
    """Nothing Docling's own appears in the record.

    ``subplan-procesador-ocr.md`` §3.4: "Docling native structures must not leak past
    ``ocr/primitives/``". Asserted over the whole record, because the leak would be a single field
    holding an engine object — which no shape assertion would notice.
    """
    document = extracted_document()

    assert isinstance(document, OCRDocument)
    for block in document.blocks:
        assert isinstance(block, BlockResult)
        assert type(block).__module__.startswith("docflow.")
    for table in document.tables:
        assert isinstance(table, TableResult)
        assert all(isinstance(cell, str) for row in table.cells for cell in row)
    assert isinstance(document.layout, LayoutResult)
    assert all(isinstance(value, float) for value in document.layout.region_bboxes[0])
    for value in document.metadata.values():
        assert isinstance(value, (str, int, float, bool, list, dict)), type(value)


def test_the_layout_reports_the_page_the_engine_saw() -> None:
    """Page geometry comes from the engine's page, and is positive."""
    document = extracted_document()

    assert document.layout.page_width > 0
    assert document.layout.page_height > 0
    assert document.layout.region_bboxes, "no region boxes were collected"


def test_the_metadata_reports_the_engines_own_schema() -> None:
    """The engine's schema name and version are recorded, keyed by this processor's names."""
    metadata = extracted_document().metadata

    assert metadata["schema_name"]
    assert metadata["schema_version"]
    assert metadata["page_count"] == 1
    assert metadata["text_items"] > 0


def test_the_block_identifiers_are_minted_in_this_processors_spelling() -> None:
    """``block_NNN``, not Docling's ``#/texts/0``.

    The engine's reference would be a deterministic identifier too, and it would be Docling's
    spelling crossing the boundary — which the subplan forbids, so the identifier is minted.

    Asserted over the **real** extraction: the first draft of this test compared a list of strings
    to itself, which is true for any input and proves nothing.
    """
    identifiers = [block.block_id for block in extracted_document().blocks]

    assert identifiers, (
        "no blocks were extracted, so the assertions below prove nothing"
    )
    assert not any(identifier.startswith("#/") for identifier in identifiers)
    assert all(identifier.startswith("block_") for identifier in identifiers)
    assert identifiers == [
        f"block_{index:03d}" for index in range(1, len(identifiers) + 1)
    ]


def test_the_table_identifiers_are_zero_padded_so_they_sort() -> None:
    """``table_001`` sorts before ``table_010``; an unpadded name would not.

    The plan fixes the padding because these names become file names under ``ocr/tables/``, and a
    directory listing sorts them.
    """
    identifiers = [table.table_id for table in extracted_document().tables]

    assert identifiers
    assert all(identifier.startswith("table_") for identifier in identifiers)
    assert all(
        len(identifier.split("_")[1]) == extraction.TABLE_ID_PADDING
        for identifier in identifiers
    )


# ======================================================================================
# The finding that decided how the fixture is prepared
# ======================================================================================


def test_binarizing_the_input_destroys_the_table_the_engine_can_find(
    tmp_path: Path,
) -> None:
    """The integration fact between two processors, pinned so it cannot be undone by accident.

    The image processor's OCR-optimized variant ends with a binarization. Fed to Docling, that
    variant collapses this fixture's table from 5x4 to **1x1**: the table-structure model needs
    the luminance detail a threshold discards. The normalized colour variant loses the table
    entirely (0 detected). Grayscale — what the fixture is — keeps it.

    Asserted rather than merely documented because the obvious future "improvement" is to feed the
    OCR processor the artifact named ``ocr_ready.png``, which is exactly the input that breaks the
    table. `OCR-11`'s entry point reads a prepared image; whoever wires it should meet this test
    first.
    """
    pixels = load_image(SOURCE, EngineChoice.OPENCV)
    metrics = analyze_image(pixels, SOURCE, EngineChoice.OPENCV)
    binarized, _applied = prepare_image_for_ocr(
        pixels,
        metrics,
        ImageOptions(
            normalize=True,
            prepare_for_ocr=True,
            prepare_for_vlm=False,
            correct_orientation=True,
            deskew=True,
        ),
        EngineChoice.OPENCV,
    )
    assert binarized is not None
    prepared = tmp_path / "binarized.png"
    save_image(binarized, prepared, EngineChoice.OPENCV)

    destroyed = extraction.build_ocr_document(
        execution.convert_image_with_docling(prepared, configured_pipeline())
    )

    assert destroyed.tables, "the binarized input produced no table at all"
    cells = destroyed.tables[0].cells
    assert len(cells) * max(len(row) for row in cells) <= 4, (
        "the binarized input no longer collapses the table, so the fixture's grayscale "
        f"preparation may no longer be necessary: {cells}"
    )


def test_grayscale_alone_keeps_the_table_intact() -> None:
    """The other half of the finding: the preparation the fixture does use is sufficient."""
    cells = extracted_document().tables[0].cells

    assert len(cells) >= 2
    assert all(len(row) >= 2 for row in cells)


def test_the_fixture_is_single_channel_which_is_what_preserves_the_table() -> None:
    """The fixture on disk is grayscale.

    A colour or binarized fixture committed by accident would make the criterion pass or fail for
    a reason the tests above would attribute to the extraction.
    """
    assert load_image(FIXTURE, EngineChoice.OPENCV).ndim == 2


def test_the_fixture_has_the_shape_the_source_produces() -> None:
    """The fixture is reproducible: the same source prepared the same way gives the same geometry.

    Not a byte comparison — PNG encoding is the encoder's business — but the same shape, which is
    what makes the fixture a *prepared* image rather than an arbitrary one.
    """
    prepared = convert_to_grayscale(
        load_image(SOURCE, EngineChoice.OPENCV), EngineChoice.OPENCV
    )

    assert prepared.shape == load_image(FIXTURE, EngineChoice.OPENCV).shape


# ======================================================================================
# Acceptance criterion 2 — an engine failure is contained, never escaping
# ======================================================================================


def test_a_conversion_failure_surfaces_as_a_typed_seam_error(tmp_path: Path) -> None:
    """The criterion: "never as an escaping exception", and typed.

    The failure is provoked for real — a path that does not exist — rather than mocked, because the
    claim is about what Docling actually raises and whether this layer contains it.
    """
    with pytest.raises(OCREngineExecutionError) as raised:
        execution.convert_image_with_docling(
            tmp_path / "absent.png", configured_pipeline()
        )

    assert raised.value.operation == execution.CONVERSION_OPERATION
    assert raised.value.detail, "the engine's own message was dropped"


def test_the_upstream_exception_is_chained_rather_than_replaced(tmp_path: Path) -> None:
    """``raise ... from failure`` keeps the cause, so a traceback still shows what Docling said."""
    with pytest.raises(OCREngineExecutionError) as raised:
        execution.convert_image_with_docling(
            tmp_path / "absent.png", configured_pipeline()
        )

    assert raised.value.__cause__ is not None


def test_no_bad_input_leaks_a_bare_exception_type(tmp_path: Path) -> None:
    """Every upstream failure arrives as the seam's type, whatever Docling raised.

    Swept over several kinds of bad input, because the point is that *no* upstream type crosses
    this boundary. A single case would only prove that one of them is contained.
    """
    blank = tmp_path / "blank.txt"
    blank.write_text("this is not an image", encoding="utf-8")
    truncated = tmp_path / "truncated.png"
    truncated.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 40)

    for candidate in (tmp_path / "absent.png", blank, truncated):
        try:
            execution.convert_image_with_docling(candidate, configured_pipeline())
        except OCREngineExecutionError:
            continue
        except Exception as failure:
            pytest.fail(
                f"{candidate.name} leaked {type(failure).__name__} "
                "instead of the seam's type"
            )


def test_the_converter_build_failure_is_also_typed() -> None:
    """A converter that cannot be built is the seam's failure too, not an escaping one."""
    with pytest.raises(OCREngineExecutionError) as raised:
        execution._build_image_converter(SimpleNamespace())

    assert raised.value.operation == execution.CONVERTER_BUILD_OPERATION


def test_the_engine_absence_is_reported_through_the_seam(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing engine is the seam's typed failure here too, not an ``ImportError``."""

    def refuse(  # pylint: disable=unused-argument
        name: str, package: str | None = None
    ) -> object:
        # `package` mirrors `importlib.import_module`'s signature so the stand-in is drop-in.
        if name == "docling" or name.startswith("docling."):
            raise ImportError(f"no module named {name!r}")
        return __import__(name)

    monkeypatch.setattr("importlib.import_module", refuse)

    with pytest.raises(OCREngineNotAvailableError):
        execution.docling_module()


# ======================================================================================
# The exporters
# ======================================================================================


def test_the_text_export_is_newline_terminated_and_non_empty() -> None:
    """A line-oriented text file ends with a newline; a blob does not."""
    document = extracted_document()

    text = export.export_docling_text(document)

    assert text
    assert text.endswith("\n")
    assert not text.endswith("\n\n")
    assert text.strip() == document.text.strip()


def test_the_markdown_export_is_built_from_the_documents_own_blocks() -> None:
    """The artifact is reproducible from the artifact's own inputs.

    The engine's Markdown renderer is free to change between versions; if ``document.md`` were
    taken from it, a consumer diffing two runs would see a difference produced by the renderer
    rather than by the page.
    """
    document = extracted_document()

    markdown = export.export_docling_markdown(document)

    assert markdown.endswith("\n")
    assert document.titles[0].split()[0] in markdown
    assert markdown.lstrip().startswith("#")
    assert "|" in markdown
    assert "---" in markdown


def test_the_json_export_carries_a_schema_version_and_every_section() -> None:
    """``document.json`` is a versioned schema, and the version is this processor's."""
    document = extracted_document()

    payload = export.export_docling_json(document)

    assert payload["schema_version"] == export.DOCUMENT_SCHEMA_VERSION
    assert set(payload) >= set(DOCUMENT_JSON_SECTIONS)
    assert len(payload["blocks"]) == len(document.blocks)
    assert len(payload["tables"]) == len(document.tables)


def test_the_json_serialization_is_byte_identical_for_equal_input() -> None:
    """The determinism posture at the serialization step.

    Keys sorted and the indent fixed, so a diff between two runs shows a real difference or
    nothing at all. ``sort_keys`` is what makes this true even though the payload is built in
    insertion order.
    """
    document = extracted_document()

    first = export.serialize_document_json(export.export_docling_json(document))
    second = export.serialize_document_json(export.export_docling_json(document))

    assert first == second
    assert json.loads(first)["schema_version"] == export.DOCUMENT_SCHEMA_VERSION


def test_the_json_payload_is_serializable() -> None:
    """A payload holding a non-serializable object would fail at publish time, in ``OCR-10``."""
    payload = export.export_docling_json(extracted_document())

    assert json.loads(json.dumps(payload, sort_keys=True)) == payload


def test_the_table_export_names_one_file_per_table() -> None:
    """Names come from the table's identifier, and there is one per table."""
    document = extracted_document()

    tables = export.export_docling_tables(document)

    assert len(tables) == len(document.tables)
    for name, markdown in tables:
        assert name.endswith(".md")
        assert name.startswith("table_")
        assert markdown.strip()


def test_a_table_with_no_rows_renders_nothing_rather_than_an_empty_table() -> None:
    """The edge the fixture does not reach: a table object with no cells.

    Hand-built rather than converted, because no committed fixture produces it and a renderer that
    emitted a headerless pipe row would be writing a table that does not exist.
    """
    empty = TableResult(table_id="table_001", index=1, markdown="", bbox=None, cells=[])

    assert export._render_table(empty) == ""


def test_ragged_rows_are_padded_to_the_widest() -> None:
    """A Markdown table needs a rectangular body; a short row would break the rendering."""
    ragged = TableResult(
        table_id="table_001",
        index=1,
        markdown="",
        bbox=None,
        cells=[["a", "b", "c"], ["d"], ["e", "f"]],
    )

    rendered = export._render_table(ragged)
    widths = [row.count("|") for row in rendered.splitlines()]

    assert len(set(widths)) == 1, f"ragged rendering: {rendered!r}"


# ======================================================================================
# The mapping, without paying for a conversion
# ======================================================================================


def test_the_label_map_covers_every_block_type_the_contract_declares() -> None:
    """Every contract block type except ``other`` is reachable from some Docling label.

    ``other`` is the fallback and needs no label. The rest must be reachable, or the contract
    advertises a category nothing can produce.
    """
    declared = set(typing.get_args(OCRBlockType))
    mapped = set(DOCLING_LABEL_TO_BLOCK_TYPE.values())

    assert mapped <= declared, f"the map invents block types: {mapped - declared}"
    unreachable = declared - mapped - {"other"}
    assert not unreachable, f"these contract types are unreachable: {unreachable}"


def test_an_unmapped_label_becomes_other_rather_than_being_dropped() -> None:
    """Docling recognises more content kinds than the contract names.

    Dropping them would be the silent loss this processor exists to avoid; ``other`` says "the
    engine produced something this processor has no vocabulary for", which a reader can act on.
    """
    stand_in = SimpleNamespace(
        label=SimpleNamespace(value="checkbox_selected"), text="x"
    )

    assert _label_value(stand_in) == "checkbox_selected"
    assert "checkbox_selected" not in DOCLING_LABEL_TO_BLOCK_TYPE


def test_a_bbox_reader_reports_absent_provenance_as_none_not_as_a_zero_box() -> None:
    """``None`` is the contract's "not extracted"; a zero box is a real location.

    Conflating them would make a missing measurement look like a point in the corner, which is the
    class of plausible-wrong-value the image processor's crop primitive refuses for the same
    reason.
    """
    no_prov = SimpleNamespace(prov=[])
    no_bbox = SimpleNamespace(prov=[SimpleNamespace(bbox=None)])
    with_bbox = SimpleNamespace(
        prov=[SimpleNamespace(bbox=SimpleNamespace(l=1.0, t=2.0, r=3.0, b=4.0))]
    )

    assert _bbox_of(no_prov) is None
    assert _bbox_of(no_bbox) is None
    assert _bbox_of(with_bbox) == (1.0, 2.0, 3.0, 4.0)


# ======================================================================================
# The lazy-import rule still holds
# ======================================================================================


@pytest.mark.parametrize(
    "module_path",
    [
        "docflow.ocr.primitives.execution",
        "docflow.ocr.primitives.extraction",
        "docflow.ocr.primitives.export",
    ],
)
def test_importing_the_extraction_modules_loads_no_engine(module_path: str) -> None:
    """``GEN-01``: these modules are imported by the package initialiser.

    The engine is reached through helper functions, not at module scope, so importing the whole
    primitives package stays free of Docling.
    """
    assert probes.module_absent_from_a_clean_import(module_path, "docling")
