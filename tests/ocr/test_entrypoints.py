# pylint: disable=duplicate-code
# Reason: two of this module's cases are deliberate siblings of another processor's suite — the
# committed-fixture check and the page-wrapper check. A fixture is proven where it lives, so the
# check belongs beside the bytes it describes, and the wrapper cases are the same shape because the
# frozen entry-point convention makes every ``process_*_from_page`` the same shape. Sharing the
# bodies would move a proof into another processor's file and hide which one broke.
"""Tests for the OCR entry points (``OCR-11`` … ``OCR-13``).

The suite drives the real pipeline with the engine doubled, so every assertion is about our flow,
our naming, our recording and our error mapping. The three invariants the subplan §6 fixes live
here, each with the mutation that must break it named in its docstring and recorded in the root
``README.md``.
"""

from __future__ import annotations

import json
import re
import struct
import tomllib
from collections.abc import Callable
from pathlib import Path

import pytest

from docflow.identities import ARTIFACT_METADATA_KEYS
from docflow.ocr import process_ocr_from_page
from docflow.ocr.contracts import OCRError
from docflow.ocr.entrypoints import PROCESSOR_VERSION, process_ocr_image
from docflow.ocr.primitives import OCRPrimitiveError, table_to_markdown
from docflow.ocr.primitives import write_json_atomic as publish_json
from tests.fakes.engines.fake_docling import (
    FAKE_ENGINE_VERSION,
    FakeConversionStatus,
    FakeDocling,
    FakeDoclingError,
    empty_document,
)
from tests.ocr.samples import (
    BLANK,
    OPTION_VALUES,
    PREPARED,
    build_options,
    build_request,
)
from tests.support import files_under, sha256_of

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

#: Every artifact the happy path publishes, in the namespace the plan fixes.
HAPPY_PATH_ARTIFACTS = {
    "document.json",
    "document.md",
    "metadata.json",
    "tables/table_001.md",
    "text.txt",
}

#: The same run's artifacts when there is no table to export.
NO_TABLE_ARTIFACTS = {"document.json", "document.md", "metadata.json", "text.txt"}

#: The other processors' namespaces, none of which this processor may touch.
OTHER_NAMESPACES = ("source", "render", "native_text", "image", "llm")

#: A run-time stamp in the shapes a builder would produce one with.
TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}|\d{2}:\d{2}:\d{2}")

#: The reading order the double's page implies, once the boxes decide it.
EXPECTED_READING_ORDER = ["block_001", "block_002", "table_001", "block_003"]


def metadata_of(output_dir: Path) -> dict:
    """Return the parsed ``metadata.json`` of a finished run."""
    return json.loads((output_dir / "metadata.json").read_text(encoding="utf-8"))


def document_of(output_dir: Path) -> dict:
    """Return the parsed ``document.json`` of a finished run."""
    return json.loads((output_dir / "document.json").read_text(encoding="utf-8"))


def test_the_happy_path_publishes_the_namespace_and_a_complete_result(
    docling: Callable[..., FakeDocling], tmp_path: Path
) -> None:
    """Acceptance: a valid prepared image yields every artifact and one result."""
    docling()
    request = build_request(PREPARED, tmp_path / "ocr")

    result = process_ocr_image(request)

    assert result.status == "success"
    assert result.validation.status == "VALID"
    assert result.text
    assert files_under(request.output_dir) == HAPPY_PATH_ARTIFACTS
    assert not list(tmp_path.rglob("*.tmp"))
    assert not any((tmp_path / namespace).exists() for namespace in OTHER_NAMESPACES)


def test_the_extraction_translates_the_engines_structures_into_ours(
    docling: Callable[..., FakeDocling], tmp_path: Path
) -> None:
    """The document, its blocks, its tables and its layout are ours, and they agree."""
    docling()
    request = build_request(PREPARED, tmp_path / "ocr")

    result = process_ocr_image(request)

    assert result.blocks is not None and result.tables is not None
    assert [block.type for block in result.blocks] == ["title", "paragraph", "caption"]
    assert result.blocks[1].text == (
        "Revenue grew by twelve percent across every region."
    )
    assert result.tables[0].cells == [["Region", "Revenue"], ["North", "120"]]
    assert result.tables[0].index == 1
    assert result.reading_order == EXPECTED_READING_ORDER
    assert result.layout is not None
    assert (result.layout.page_width, result.layout.page_height) == (240.0, 120.0)
    assert len(result.layout.region_bboxes) == 6  # five items and one table
    assert all(
        0.0 <= value <= 1.0 for box in result.layout.region_bboxes for value in box
    )
    assert result.structured_document is not None
    assert result.structured_document["metadata"]["schema_version"] == "1"
    assert result.structured_document["reading_order"] == EXPECTED_READING_ORDER
    # JSON has no tuples, so the file and the in-memory value are compared in JSON's own terms.
    assert document_of(request.output_dir) == json.loads(
        json.dumps(result.structured_document)
    )
    assert (request.output_dir / "tables" / "table_001.md").read_text(
        encoding="utf-8"
    ) == table_to_markdown([["Region", "Revenue"], ["North", "120"]])


def test_the_metadata_records_the_provenance_the_identities_and_the_options(
    docling: Callable[..., FakeDocling], tmp_path: Path
) -> None:
    """Acceptance: ``metadata.json`` names the processor, the engine and what was applied."""
    docling()
    request = build_request(PREPARED, tmp_path / "ocr")

    result = process_ocr_image(request)
    payload = metadata_of(request.output_dir)

    assert set(ARTIFACT_METADATA_KEYS) <= set(payload)
    assert payload["processor"] == "ocr"
    assert payload["processor_version"] == PROCESSOR_VERSION
    assert payload["engine"] == "docling"
    assert payload["engine_version"] == FAKE_ENGINE_VERSION
    assert payload["document_id"] == "doc-1"
    assert payload["workflow_run_id"] == "run-1"
    assert payload["processing_key"]
    assert payload["status"] == "success"
    assert payload["options"] == OPTION_VALUES
    assert payload["validation"]["status"] == "VALID"
    assert payload["metrics"]["empty"] is False
    assert payload["metrics"]["tables"] == 1
    assert payload["metrics"]["paragraphs"] == 1
    assert payload["timing"]["total"] >= 0
    assert result.metadata is not None
    assert result.metadata.validation.status == "VALID"


def test_a_blank_image_is_reported_empty_and_not_thrown(
    docling: Callable[..., FakeDocling], tmp_path: Path
) -> None:
    """Acceptance: emptiness is data. The run succeeds, and no partial artifact is left."""
    docling(document=empty_document)
    request = build_request(BLANK, tmp_path / "ocr")

    result = process_ocr_image(request)

    assert result.status == "success"
    assert result.validation.status == "EMPTY"
    assert result.metrics is not None
    assert result.metrics.empty is True
    assert result.metrics.characters == 0
    assert files_under(request.output_dir) == NO_TABLE_ARTIFACTS
    assert not list(tmp_path.rglob("*.tmp"))
    assert metadata_of(request.output_dir)["validation"]["status"] == "EMPTY"


def test_an_engine_error_is_contained_and_leaves_no_residue(
    docling: Callable[..., FakeDocling], tmp_path: Path
) -> None:
    """Acceptance: an engine that raises during conversion is a typed failure, not a crash."""
    docling(raises=FakeDoclingError("the layout model refused this page"))
    request = build_request(PREPARED, tmp_path / "ocr")

    result = process_ocr_image(request)

    assert result.status == "failed"
    assert result.error is not None and result.error.type == "ENGINE_ERROR"
    assert result.error.recoverable is False
    assert result.validation.status == "ERROR"
    assert not list(tmp_path.rglob("*.tmp"))
    assert not request.output_dir.exists()
    assert result.text is None
    assert result.metrics is None
    assert result.metadata is None


def test_a_failure_the_engine_returns_rather_than_raises_is_reported(
    docling: Callable[..., FakeDocling], tmp_path: Path
) -> None:
    """A refused conversion must not read as a successful extraction of an empty page."""
    docling(status=FakeConversionStatus.FAILURE, errors=["no model available"])
    request = build_request(PREPARED, tmp_path / "ocr")

    result = process_ocr_image(request)

    assert result.status == "failed"
    assert result.error is not None and result.error.type == "OCR_ERROR"
    assert result.error.metadata["errors"] == ["no model available"]
    assert result.validation.status == "ERROR"
    assert not request.output_dir.exists()


def test_a_partial_conversion_keeps_what_it_got_and_reports_the_gap(
    docling: Callable[..., FakeDocling], tmp_path: Path
) -> None:
    """A partial conversion is not a failure: the artifacts stand and the gap is named."""
    docling(
        status=FakeConversionStatus.PARTIAL_SUCCESS,
        errors=["the table structure could not be matched"],
    )
    request = build_request(PREPARED, tmp_path / "ocr")

    result = process_ocr_image(request)

    assert result.status == "success"
    assert result.validation.status == "INCOMPLETE"
    assert [error.type for error in result.validation.errors] == ["OCR_ERROR"]
    assert result.validation.errors[0].recoverable is True
    assert files_under(request.output_dir) == HAPPY_PATH_ARTIFACTS
    assert metadata_of(request.output_dir)["validation"]["status"] == "INCOMPLETE"


def test_an_unsupported_container_is_named_as_such_and_never_converted(
    docling: Callable[..., FakeDocling], tmp_path: Path
) -> None:
    """The refusal happens before the engine is asked, and names the problem it was."""
    fake = docling()
    candidate = tmp_path / "scan.heic"
    candidate.write_bytes(b"not an image we read")

    result = process_ocr_image(build_request(candidate, tmp_path / "ocr"))

    assert result.error is not None
    assert result.error.type == "UNSUPPORTED_IMAGE"
    assert result.error.recoverable is False
    assert result.validation.status == "ERROR"
    assert fake.calls == []


def test_a_missing_input_is_reported_rather_than_raised(
    docling: Callable[..., FakeDocling], tmp_path: Path
) -> None:
    """A failure is data on the result: no exception crosses the contract."""
    docling()

    result = process_ocr_image(build_request(tmp_path / "absent.png", tmp_path / "ocr"))

    assert result.status == "failed"
    assert result.error is not None and result.error.type == "INVALID_INPUT"
    assert result.artifacts is None


def test_the_input_image_is_never_modified(
    docling: Callable[..., FakeDocling], tmp_path: Path
) -> None:
    """The input is read, never written."""
    docling()
    before = sha256_of(PREPARED)
    modified = PREPARED.stat().st_mtime_ns

    process_ocr_image(build_request(PREPARED, tmp_path / "ocr"))

    assert sha256_of(PREPARED) == before
    assert PREPARED.stat().st_mtime_ns == modified


def test_the_tables_flag_decides_what_is_claimed(
    docling: Callable[..., FakeDocling], tmp_path: Path
) -> None:
    """``tables: false`` claims no table, even though the engine handed one over."""
    docling()
    request = build_request(PREPARED, tmp_path / "ocr", tables=False)

    result = process_ocr_image(request)

    assert result.tables == []
    assert result.metrics is not None and result.metrics.tables == 0
    assert files_under(request.output_dir) == NO_TABLE_ARTIFACTS


def test_the_layout_flag_decides_what_is_claimed(
    docling: Callable[..., FakeDocling], tmp_path: Path
) -> None:
    """``layout: false`` claims no box, while the page size is still measured."""
    docling()
    request = build_request(PREPARED, tmp_path / "ocr", layout=False)

    result = process_ocr_image(request)

    assert result.blocks is not None
    assert all(block.bbox is None for block in result.blocks)
    assert result.tables is not None and result.tables[0].bbox is None
    assert result.layout is not None and result.layout.region_bboxes == []
    assert result.layout.page_width == 240.0


def test_the_reading_order_flag_decides_whether_geometry_sorting_happens(
    docling: Callable[..., FakeDocling], tmp_path: Path
) -> None:
    """``reading_order: false`` keeps the engine's own sequence instead of deciding one.

    The blocks then come back in the order the engine handed them over — the caption first — and
    the two body lines are no longer adjacent, so the paragraph merge joins one item per run and
    the paragraph arrives split. That is the option's meaning: nothing is reordered, so only what
    the engine placed next to each other is joined.
    """
    docling()
    request = build_request(PREPARED, tmp_path / "ocr", reading_order=False)

    result = process_ocr_image(request)

    assert result.blocks is not None
    assert [block.type for block in result.blocks] == [
        "caption",
        "paragraph",
        "title",
        "paragraph",
    ]
    assert result.metadata is not None
    assert "preserve_reading_order" not in result.metadata.transformations


def test_a_metadata_that_cannot_be_published_is_reported(
    docling: Callable[..., FakeDocling],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The run's own record is part of the run: losing it is a failure, not a footnote."""
    docling()

    def refuse(destination: Path, payload: object) -> Path:
        """Publish everything but the run's own record."""
        if destination.name == "metadata.json":
            raise OCRPrimitiveError(
                OCRError(
                    type="IO_ERROR",
                    message="scripted refusal",
                    recoverable=True,
                    metadata={},
                )
            )
        return publish_json(destination, payload)  # type: ignore[arg-type]

    monkeypatch.setattr("docflow.ocr.entrypoints.write_json_atomic", refuse)
    request = build_request(PREPARED, tmp_path / "ocr")

    result = process_ocr_image(request)

    assert result.status == "failed"
    assert result.error is not None and result.error.type == "IO_ERROR"
    assert result.validation.status == "ERROR"
    assert not (request.output_dir / "metadata.json").exists()
    assert (request.output_dir / "text.txt").is_file()
    assert result.text is not None


def test_the_entry_point_for_a_page_carries_the_page_identity(
    docling: Callable[..., FakeDocling], tmp_path: Path
) -> None:
    """The wrapper builds the request and delegates; it never opens a PDF."""
    docling()

    result = process_ocr_from_page(
        image_path=PREPARED,
        output_dir=tmp_path / "ocr",
        options=build_options(),
        document_id="doc-9",
        page_number=7,
        workflow_run_id="run-9",
    )

    assert result.status == "success"
    assert result.metadata is not None
    assert result.metadata.context.document_id == "doc-9"
    assert result.metadata.context.page_number == 7
    assert metadata_of(tmp_path / "ocr")["workflow_run_id"] == "run-9"


def test_the_recorded_processor_version_is_the_packaged_one() -> None:
    """Provenance that names a version the package does not have is a defect."""
    packaged = tomllib.loads(
        (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]["version"]

    assert packaged == PROCESSOR_VERSION


def test_the_double_answered_the_conversion_the_seam_asked_for(
    docling: Callable[..., FakeDocling], tmp_path: Path
) -> None:
    """The engine is reached through the seam, with the file the request named."""
    fake = docling()
    request = build_request(PREPARED, tmp_path / "ocr")

    process_ocr_image(request)

    assert fake.calls == [PREPARED]


def test_the_two_runs_of_the_same_input_produce_the_same_functional_content(
    docling: Callable[..., FakeDocling], tmp_path: Path
) -> None:
    """Invariant 1: deterministic ordering and a stable format.

    The mutation that must break this test is dropping the stable sort key — replacing
    ``sorted(blocks, key=…)`` with the engine's own iteration order in
    ``docflow.ocr.primitives.composition.preserve_reading_order`` — which the byte comparison of
    ``document.json`` catches, because the double hands its items over in adversarial order.
    """
    docling()
    first = build_request(PREPARED, tmp_path / "first")
    second = build_request(PREPARED, tmp_path / "second")

    first_result = process_ocr_image(first)
    second_result = process_ocr_image(second)

    assert first_result.status == "success"
    assert second_result.status == "success"
    assert first_result.reading_order is not None
    assert first_result.reading_order == EXPECTED_READING_ORDER
    assert (first.output_dir / "document.json").read_bytes() == (
        second.output_dir / "document.json"
    ).read_bytes()
    assert (first.output_dir / "text.txt").read_bytes() == (
        second.output_dir / "text.txt"
    ).read_bytes()
    assert document_of(first.output_dir) == document_of(second.output_dir)

    # The run's own record is the one place run-time data is allowed, and timing is the *only*
    # thing two runs over the same input may differ in.
    first_metadata = metadata_of(first.output_dir)
    second_metadata = metadata_of(second.output_dir)
    assert first_metadata["timing"] and second_metadata["timing"]
    del first_metadata["timing"], second_metadata["timing"]
    assert first_metadata == second_metadata


def test_no_functional_artifact_carries_a_run_time_stamp(
    docling: Callable[..., FakeDocling], tmp_path: Path
) -> None:
    """Invariant 2: timing lives in ``metadata.json`` and nowhere else.

    The mutation that must break this test is injecting ``datetime.now().isoformat()`` into the
    ``document.json`` payload or the Markdown builder — ``document.json`` is built in
    ``docflow.ocr.entrypoints`` from ``OCRDocument``, and ``document.md`` in
    ``docflow.ocr.primitives.normalize_markdown``.
    """
    docling()
    request = build_request(PREPARED, tmp_path / "ocr")

    result = process_ocr_image(request)

    functional = [
        request.output_dir / "text.txt",
        request.output_dir / "document.md",
        request.output_dir / "document.json",
        request.output_dir / "tables" / "table_001.md",
    ]
    for path in functional:
        assert not TIMESTAMP.search(path.read_text(encoding="utf-8")), path
    assert result.metadata is not None
    assert result.metadata.timing
    assert metadata_of(request.output_dir)["timing"]


def test_a_publication_that_fails_leaves_neither_a_tmp_file_nor_an_artifact(
    docling: Callable[..., FakeDocling],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Invariant 3: atomic publication — nothing final is visible until the rename happens.

    The mutation that must break this test is publishing to the final path instead of to the
    ``.tmp`` sibling in ``docflow.ocr.primitives.publication._publish``: with the rename refused,
    that implementation leaves final-named artifacts behind, and this test finds them.
    """
    docling()

    def refuse(*_arguments: object, **_keywords: object) -> None:
        """Refuse every rename, the way a full or read-only filesystem does."""
        raise OSError("scripted rename failure")

    monkeypatch.setattr("docflow.ocr.primitives.publication.os.replace", refuse)
    request = build_request(PREPARED, tmp_path / "ocr")

    result = process_ocr_image(request)

    assert result.status == "failed"
    assert result.error is not None and result.error.type == "IO_ERROR"
    assert files_under(request.output_dir) == set()
    assert not list(tmp_path.rglob("*.tmp"))


def test_the_committed_fixtures_are_real_png_bytes() -> None:
    """A fixture named for a case has to be the case: a signature, a header and an end chunk."""
    for fixture_path in (PREPARED, BLANK):
        data = fixture_path.read_bytes()

        assert data.startswith(b"\x89PNG\r\n\x1a\n")
        assert data[12:16] == b"IHDR"
        assert b"IEND" in data[-16:]
        assert struct.unpack(">II", data[16:24]) == (240, 120)


def test_the_two_fixtures_are_not_the_same_page() -> None:
    """The blank fixture is a page with nothing on it, not a copy of the happy path."""
    assert PREPARED.read_bytes() != BLANK.read_bytes()
    assert len(BLANK.read_bytes()) < len(PREPARED.read_bytes())
