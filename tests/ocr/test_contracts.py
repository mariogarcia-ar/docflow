"""Round-trip test for the OCR contract (``GEN-06``).

Proves ``OCRRequest → OCRResult`` round-trips an in-memory fake end to end before Docling
is reached at all.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from docflow.ocr import (
    ArtifactPaths,
    BlockResult,
    LayoutResult,
    NormalizedOCROptions,
    OCRMetadata,
    OCRMetrics,
    OCRRequest,
    OCRResult,
    OCRValidation,
    TableResult,
)
from tests.factories import build_ocr_options, build_ocr_request, incomplete_call


def normalized_options(request: OCRRequest) -> NormalizedOCROptions:
    """Return the canonical form of the request's options."""
    options = request.options
    return NormalizedOCROptions(
        ocr=options.ocr,
        layout=options.layout,
        tables=options.tables,
        reading_order=options.reading_order,
        language=options.language,
        engine_options=dict(options.engine_options),
    )


def fake_process_ocr_image(request: OCRRequest) -> OCRResult:
    """Stand-in processor: builds a result from the request and nothing else."""
    blocks = [
        BlockResult(
            block_id="block_001",
            type="title",
            text="A heading",
            bbox=(0.0, 0.0, 100.0, 20.0),
            level=1,
        ),
        BlockResult(
            block_id="block_002",
            type="paragraph",
            text="A paragraph.",
            bbox=(0.0, 30.0, 100.0, 60.0),
            level=None,
        ),
    ]
    tables = [
        TableResult(
            table_id="table_001",
            index=1,
            markdown="| a | b |\n| - | - |\n| 1 | 2 |",
            bbox=(0.0, 70.0, 100.0, 120.0),
            cells=[["a", "b"], ["1", "2"]],
        )
    ]
    metrics = OCRMetrics(
        characters=25,
        words=4,
        blocks=len(blocks),
        tables=len(tables),
        paragraphs=1,
        text_density=0.02,
        empty=False,
        structure_detected=True,
    )
    artifacts = ArtifactPaths(
        text=Path("ocr/text.txt"),
        markdown=Path("ocr/document.md"),
        structured_document=Path("ocr/document.json"),
        tables_dir=Path("ocr/tables"),
        metadata=Path("ocr/metadata.json"),
    )
    return OCRResult(
        text="A heading\n\nA paragraph.",
        markdown="# A heading\n\nA paragraph.",
        structured_document={"text": "A heading\n\nA paragraph."},
        tables=tables,
        blocks=blocks,
        layout=LayoutResult(
            page_width=612.0, page_height=792.0, region_bboxes=[(0.0, 0.0, 100.0, 20.0)]
        ),
        reading_order=["block_001", "block_002", "table_001"],
        metrics=metrics,
        artifacts=artifacts,
        validation=OCRValidation(status="VALID", errors=[], missing_artifacts=[]),
        metadata=OCRMetadata(
            engine="docling",
            engine_version="test",
            processor_version="0.0.0",
            options=normalized_options(request),
            input=request.image_path,
            metrics=metrics,
            validation=OCRValidation(status="VALID", errors=[], missing_artifacts=[]),
            timing={"total": 0.5},
            transformations=[],
            context=request.context,
        ),
        status="success",
        error=None,
    )


def test_the_fake_returns_the_matching_result_type(tmp_path: Path) -> None:
    """A valid request produces an ``OCRResult``."""
    result = fake_process_ocr_image(build_ocr_request(tmp_path))

    assert isinstance(result, OCRResult)


def test_the_request_identity_is_preserved_in_the_result(tmp_path: Path) -> None:
    """``document_id``, ``page_number`` and ``workflow_run_id`` survive unchanged."""
    request = build_ocr_request(tmp_path)

    result = fake_process_ocr_image(request)

    assert result.metadata.context == request.context


def test_the_engine_is_named_and_versioned(tmp_path: Path) -> None:
    """A re-run is comparable to a previous one only when the engine is recorded."""
    result = fake_process_ocr_image(build_ocr_request(tmp_path))

    assert result.metadata.engine == "docling"
    assert result.metadata.engine_version


def test_reading_order_names_every_block_and_table(tmp_path: Path) -> None:
    """Ordering is explicit data, so no consumer has to infer it from list position."""
    result = fake_process_ocr_image(build_ocr_request(tmp_path))

    published = {block.block_id for block in result.blocks}
    published |= {table.table_id for table in result.tables}

    assert set(result.reading_order) == published


def test_the_structured_document_is_serializable(tmp_path: Path) -> None:
    """The engine-independent representation survives a JSON round trip."""
    result = fake_process_ocr_image(build_ocr_request(tmp_path))

    assert json.loads(json.dumps(result.structured_document)) == (
        result.structured_document
    )


def test_a_missing_required_option_is_rejected_instead_of_defaulted() -> None:
    """A missing option is not silently treated as false."""
    complete = build_ocr_options()
    incomplete = {
        "ocr": True,
        "layout": True,
        "tables": True,
        "reading_order": True,
        "language": "en",
    }

    with pytest.raises(TypeError):
        incomplete_call(type(complete), incomplete)
