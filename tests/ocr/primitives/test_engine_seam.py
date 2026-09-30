"""Tests for the Docling seam and the primitives that reach it (``OCR-02`` … ``OCR-04``).

Every assertion here is about **our** translation: the configuration we fold the options into, the
failures we type, the structures we read and the representations we normalize. Nothing asserts what
Docling computes — the double answers with the engine's own shapes (`README.md` §9.7) — and
``load_docling_pipeline`` is deliberately not called: it is the one function that imports the
engine, it is reached only from the engine call the double replaces, and the suite has to pass with
no Docling installed.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from docflow.ocr import OCROptions
from docflow.ocr.contracts import (
    BlockResult,
    LayoutResult,
    OCRContext,
    OCRMetrics,
    OCRValidation,
)
from docflow.ocr.primitives import (
    OCRPrimitiveError,
    build_ocr_document,
    build_ocr_metadata,
    configure_image_pipeline,
    conversion_failure,
    extract_docling_blocks,
    extract_docling_layout,
    extract_docling_markdown,
    extract_docling_tables,
    extract_docling_text,
    get_engine_version,
    normalize_docling_options,
    normalize_markdown,
    normalize_ocr_text,
    preserve_reading_order,
    process_tables,
)
from tests.factories import build_ocr_options
from tests.fakes.engines.fake_docling import (
    FAKE_ENGINE_VERSION,
    FakeConversionStatus,
    FakeDocling,
    empty_document,
    footer_document,
    prepared_document,
)
from tests.ocr.samples import PREPARED

SEAM = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "docflow"
    / "ocr"
    / "primitives"
    / "__init__.py"
)


def options(**overrides: Any) -> OCROptions:
    """Return the shared fully specified options, with any subset overridden."""
    return replace(build_ocr_options(), **overrides)


def conversion(*, document: Any = None, status: Any = None, errors: Any = ()) -> Any:
    """Return the engine's own conversion result, produced by the double."""
    document = document or prepared_document
    fake = FakeDocling(
        document=document,
        status=status if status is not None else FakeConversionStatus.SUCCESS,
        errors=errors,
    )
    return fake(PREPARED, {})


def test_equivalent_options_normalize_to_the_same_record() -> None:
    """Two spellings of one configuration have to produce one normalized record."""
    first = normalize_docling_options(
        OCROptions(
            ocr=True,
            layout=True,
            tables=True,
            reading_order=True,
            language="EN",
            engine_options={"do_table_structure": True, "images_scale": 2},
        )
    )
    second = normalize_docling_options(
        OCROptions(
            ocr=True,
            layout=True,
            tables=True,
            reading_order=True,
            language=" en ",
            engine_options={"images_scale": 2, "do_table_structure": True},
        )
    )

    assert first == second
    assert first.language == "en"
    assert list(first.engine_options) == ["do_table_structure", "images_scale"]


def test_a_language_that_is_only_whitespace_names_no_language() -> None:
    """An empty tag is not a language, and the engine must not have to interpret one."""
    assert normalize_docling_options(options(language="   ")).language is None
    assert normalize_docling_options(options(language=None)).language is None


def test_the_pipeline_configuration_folds_every_flag_inline() -> None:
    """The flags become the engine's own option names, in one construction."""
    configuration = configure_image_pipeline(
        normalize_docling_options(options(layout=False, tables=False))
    )

    assert configuration["do_ocr"] is True
    assert configuration["do_table_structure"] is False
    assert configuration["generate_page_images"] is False
    assert configuration["ocr_language"] == "en"


def test_a_declared_flag_wins_over_a_passthrough_key_of_the_same_name() -> None:
    """``engine_options`` may add a knob; it may not switch off what the caller asked for."""
    configuration = configure_image_pipeline(
        normalize_docling_options(
            options(tables=True, engine_options={"do_table_structure": False})
        )
    )

    assert configuration["do_table_structure"] is True


def test_the_engine_version_comes_from_the_engine_namespace(
    docling: Any,
) -> None:
    """The version is read, not defaulted: it is what makes two runs comparable."""
    docling()

    assert get_engine_version() == FAKE_ENGINE_VERSION


def test_an_absent_engine_is_reported_and_not_substituted(
    docling: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing library is an ``ENGINE_ERROR``: there is no second OCR engine to fall back to."""
    docling()
    monkeypatch.setattr("docflow.ocr.primitives.docling", None)
    monkeypatch.setattr("docflow.ocr.primitives.ENGINE_MODULE", "docflow_absent_engine")

    with pytest.raises(OCRPrimitiveError) as failure:
        get_engine_version()

    assert failure.value.error.type == "ENGINE_ERROR"
    assert failure.value.error.recoverable is False


def test_an_engine_namespace_without_a_version_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A version nobody can read is reported rather than guessed."""
    monkeypatch.setattr("docflow.ocr.primitives.docling", object())

    with pytest.raises(OCRPrimitiveError) as failure:
        get_engine_version()

    assert failure.value.error.type == "ENGINE_ERROR"


def test_a_successful_conversion_carries_no_failure() -> None:
    """``None`` is the only answer that means the conversion succeeded."""
    assert conversion_failure(conversion(), PREPARED) is None


def test_a_partial_conversion_is_recorded_as_recoverable() -> None:
    """The run goes on and the validation reports the gap: a partial result is data."""
    reported = conversion_failure(
        conversion(
            status=FakeConversionStatus.PARTIAL_SUCCESS, errors=["table unmatched"]
        ),
        PREPARED,
    )

    assert reported is not None
    assert reported.type == "OCR_ERROR"
    assert reported.recoverable is True
    assert reported.metadata["errors"] == ["table unmatched"]
    assert reported.metadata["engine_status"] == "partial_success"


def test_a_failed_conversion_is_not_recoverable() -> None:
    """A refused conversion must not be read as an empty document."""
    reported = conversion_failure(
        conversion(status=FakeConversionStatus.FAILURE, errors=["no model"]), PREPARED
    )

    assert reported is not None
    assert reported.type == "OCR_ERROR"
    assert reported.recoverable is False


def test_a_status_the_seam_does_not_model_is_an_engine_error() -> None:
    """An unrecognized status is not a conversion this processor can describe."""
    reported = conversion_failure(
        conversion(status="something_new", errors=[]), PREPARED
    )

    assert reported is not None
    assert reported.type == "ENGINE_ERROR"
    assert reported.recoverable is False


def test_the_layout_is_read_from_the_documents_own_page() -> None:
    """The page size is the engine's, and the regions are the items' own boxes."""
    geometry = extract_docling_layout(conversion())

    assert (geometry.width, geometry.height) == (240.0, 120.0)
    assert geometry.region_bboxes[0] == (12.0, 96.0, 204.0, 108.0)


def test_a_document_with_no_page_is_a_layout_error() -> None:
    """A converted image always has a page; a missing one is a layout nothing can be measured on."""
    document = empty_document(240.0, 120.0)
    document.pages = {}

    with pytest.raises(OCRPrimitiveError) as failure:
        extract_docling_layout(conversion(document=lambda *_: document))

    assert failure.value.error.type == "LAYOUT_ERROR"


def test_a_page_with_no_usable_size_is_a_layout_error() -> None:
    """A zero-sized page is a measurement nobody can use, not a measurement of zero."""
    document = empty_document(0.0, 0.0)

    with pytest.raises(OCRPrimitiveError) as failure:
        extract_docling_layout(conversion(document=lambda *_: document))

    assert failure.value.error.type == "LAYOUT_ERROR"


def test_the_blocks_come_back_in_the_engines_own_order() -> None:
    """No ordering is claimed here: the order is the engine's, and sorting is a separate step."""
    engine_conversion = conversion()

    blocks = extract_docling_blocks(
        engine_conversion, extract_docling_layout(engine_conversion), with_layout=True
    )

    assert [block.text for block in blocks] == [
        "Source: internal ledger",
        "across every region.",
        "Quarterly report",
        "Revenue grew by twelve percent",
    ]
    assert [block.order for block in blocks] == [0, 2, 3, 4]


def test_a_table_item_is_not_also_a_block() -> None:
    """The same content must not arrive twice: a table is extracted as a table."""
    engine_conversion = conversion()
    blocks = extract_docling_blocks(
        engine_conversion, extract_docling_layout(engine_conversion), with_layout=True
    )

    assert "table" not in {block.type for block in blocks}
    assert (
        len(
            extract_docling_tables(
                engine_conversion,
                extract_docling_layout(engine_conversion),
                with_layout=True,
            )
        )
        == 1
    )


def test_an_item_with_no_text_is_not_a_block() -> None:
    """A picture item carries nothing to report, so it is not reported as a block."""
    engine_conversion = conversion()

    blocks = extract_docling_blocks(
        engine_conversion, extract_docling_layout(engine_conversion), with_layout=True
    )

    assert len(blocks) == 4
    assert "" not in {block.text for block in blocks}


def test_a_box_is_claimed_only_when_a_layout_was_asked_for() -> None:
    """Nothing claims a measurement whose extraction was not requested."""
    engine_conversion = conversion()
    geometry = extract_docling_layout(engine_conversion)

    blocks = extract_docling_blocks(engine_conversion, geometry, with_layout=False)
    tables = extract_docling_tables(engine_conversion, geometry, with_layout=False)

    assert all(block.bbox is None for block in blocks)
    assert tables[0].bbox is None


def test_the_tables_carry_their_cells_in_the_engines_own_offsets() -> None:
    """The grid is built from the offsets, so a cell lands where the engine placed it."""
    engine_conversion = conversion()
    tables = extract_docling_tables(
        engine_conversion, extract_docling_layout(engine_conversion), with_layout=True
    )

    assert tables[0].cells == [["Region", "Revenue"], ["North", "120"]]


def test_the_exports_are_returned_untranslated() -> None:
    """Normalizing is a separate step; the seam hands back what the engine produced."""
    engine_conversion = conversion()

    assert extract_docling_text(engine_conversion).startswith("Quarterly report")
    assert extract_docling_markdown(engine_conversion).startswith("# Quarterly report")


def test_a_page_footer_is_read_instead_of_being_left_in_its_own_layer() -> None:
    """The engine files a footer in ``furniture`` and reads the body alone; this seam reads both.

    The operator's invoice is the case: the layout model calls the band holding the ``CAE`` a page
    footer, the engine files it outside the body, and its traversal and exports would leave it out
    of every artifact without saying so. A block is where that line stops being invisible — and
    the page's footer is part of the page.
    """
    engine_conversion = conversion(document=footer_document)
    geometry = extract_docling_layout(engine_conversion)
    blocks = extract_docling_blocks(engine_conversion, geometry, with_layout=True)

    assert "CAE N°: 86327284406071" in extract_docling_text(engine_conversion)
    assert [block.text for block in blocks] == [
        "Quarterly report",
        "Revenue grew by twelve percent",
        "CAE N°: 86327284406071",
    ]
    footer = blocks[-1]
    assert footer.type == "other"
    assert footer.bbox is not None and footer.bbox[1] > 0.8


def test_an_export_that_raises_is_an_export_error() -> None:
    """A representation that cannot be produced fails the run; it does not become an empty one."""

    class Refusing:
        """A document whose exports fail."""

        # pylint: disable=too-few-public-methods
        # Reason: the stub exists to fail the way the engine's exporter does, and nothing else.

        def export_to_text(self, **_: Any) -> str:
            """Fail the way the engine's exporter does."""
            raise RuntimeError("the exporter gave up")

    with pytest.raises(OCRPrimitiveError) as failure:
        extract_docling_text(conversion(document=lambda *_: Refusing()))

    assert failure.value.error.type == "EXPORT_ERROR"


def test_an_export_that_is_not_text_is_an_export_error() -> None:
    """A representation that is not text is reported, never coerced."""

    class Wrong:
        """A document whose export returns the wrong type."""

        # pylint: disable=too-few-public-methods
        # Reason: the stub exists to answer with the wrong type, and nothing else.

        def export_to_markdown(self, **_: Any) -> list[Any]:
            """Answer with something that is not text."""
            return []

    with pytest.raises(OCRPrimitiveError) as failure:
        extract_docling_markdown(conversion(document=lambda *_: Wrong()))

    assert failure.value.error.type == "EXPORT_ERROR"
    assert failure.value.error.metadata["exported_type"] == "list"


def test_the_text_normalization_unifies_line_endings_and_drops_trailing_blanks() -> (
    None
):
    """One normalizer for the text representation, and it adds nothing."""
    assert normalize_ocr_text("a  \r\nb\r\n\r\n\r\n") == "a\nb"
    assert normalize_ocr_text("") == ""


def test_the_markdown_normalization_ends_with_one_newline() -> None:
    """A Markdown document ends in exactly one newline; an empty one stays empty."""
    assert normalize_markdown("# Title\n\nBody\n\n\n") == "# Title\n\nBody\n"
    assert normalize_markdown("") == ""


def test_the_tables_are_published_under_their_reading_order_names(
    tmp_path: Path,
) -> None:
    """``table_001.md`` and up, zero-padded, holding exactly what the result reports."""
    engine_conversion = conversion()
    extracted = extract_docling_tables(
        engine_conversion, extract_docling_layout(engine_conversion), with_layout=True
    )
    named = preserve_reading_order([], extracted, by_geometry=True).tables

    published = process_tables(named, tmp_path / "ocr" / "tables")

    assert [path.name for path in published] == ["table_001.md"]
    assert published[0].read_text(encoding="utf-8") == named[0].markdown


def test_no_table_means_no_tables_directory(tmp_path: Path) -> None:
    """An image with no table produces no artifact and no failure."""
    assert process_tables([], tmp_path / "ocr" / "tables") == []
    assert not (tmp_path / "ocr").exists()


def test_the_document_reads_its_paragraphs_and_titles_off_the_blocks() -> None:
    """The two views of the content cannot disagree, because one is read off the other."""
    composed = build_ocr_document(
        text="A heading\n\nA paragraph.",
        blocks=[
            BlockResult(
                block_id="block_001",
                type="title",
                text="A heading",
                bbox=None,
                level=1,
            ),
            BlockResult(
                block_id="block_002",
                type="paragraph",
                text="A paragraph.",
                bbox=None,
                level=None,
            ),
        ],
        tables=[],
        layout=LayoutResult(page_width=1.0, page_height=1.0, region_bboxes=[]),
        reading_order=["block_001", "block_002"],
        options=normalize_docling_options(options()),
        engine_version=FAKE_ENGINE_VERSION,
    )

    assert composed.titles == ["A heading"]
    assert composed.paragraphs == ["A paragraph."]
    assert composed.metadata["schema_version"] == "1"
    assert composed.metadata["engine"] == "docling"
    assert composed.metadata["engine_version"] == FAKE_ENGINE_VERSION


def test_the_metadata_record_carries_the_engine_and_the_caller_identity() -> None:
    """The provenance of a run names the code, the engine and the correlation identity."""
    record = build_ocr_metadata(
        PREPARED,
        OCRContext(document_id="doc-1", page_number=1, workflow_run_id="run-1"),
        engine_version=FAKE_ENGINE_VERSION,
        processor_version="0.0.0",
        options=normalize_docling_options(options()),
        metrics=OCRMetrics(
            characters=1,
            words=1,
            blocks=1,
            tables=0,
            paragraphs=1,
            text_density=0.1,
            empty=False,
            structure_detected=True,
        ),
        validation=OCRValidation(status="VALID", errors=[], missing_artifacts=[]),
        timing={"total": 0.0},
        transformations=["normalize_ocr_text"],
    )

    assert record.engine == "docling"
    assert record.engine_version == FAKE_ENGINE_VERSION
    assert record.context.document_id == "doc-1"
    assert record.input == PREPARED


def test_the_seam_resolves_the_engine_at_call_time_and_not_at_import() -> None:
    """The injection point is the module attribute: a module-level import would break it."""
    source = SEAM.read_text(encoding="utf-8")

    assert "importlib.import_module(ENGINE_MODULE)" in source
    assert "import docling" not in source
    assert 'ENGINE_MODULE: Final[str] = "docling"' in source


def test_the_seam_reaches_no_other_engine() -> None:
    """Docling is the only engine this processor has, and nothing else may be imported here."""
    source = SEAM.read_text(encoding="utf-8")

    for library in ("cv2", "PIL", "fitz", "openai", "ollama", "httpx", "torch"):
        assert f"import {library}" not in source


def test_the_closed_surface_has_no_predicate_or_second_export() -> None:
    """The surface is closed: no ``enable_*``, no ``should_enable_*``, no ``export_docling_*``."""
    source = SEAM.read_text(encoding="utf-8")

    assert "def enable_" not in source
    assert "def should_enable_" not in source
    assert "def export_docling_" not in source
