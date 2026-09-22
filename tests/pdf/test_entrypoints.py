"""Tests for the page entry point (``PDF-09``).

The task is composition, so most of what could go wrong is not in any single primitive:
a capability that silently does nothing, a failure that escapes as an exception, an artifact
written outside this processor's namespaces, a metadata file missing the provenance keys the
plan requires.

The partial-page scenario is the acceptance criterion and gets the most attention, because it
is the case the whole error model exists for. It is induced by replacing a primitive with a
raiser — the only way to reach a per-artifact failure that the engine itself is not currently
producing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from docflow.identities import ARTIFACT_METADATA_KEYS, PAGE_ARTIFACT_METADATA_KEYS
from docflow.pdf import PDFContext, PDFOptions, PDFRequest
from docflow.pdf.entrypoints import process_pdf_page
from docflow.pdf.primitives.failures import PDFPrimitiveError
from docflow.pdf.primitives.publishing import TEMP_SUFFIX
from tests.factories import build_pdf_request_for

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
TEXT_PDF = FIXTURES / "matrix" / "three-invoices.pdf"
MASKED_PDF = FIXTURES / "pdf_aptos_layout" / "36744cc6-2ed9-47e5-b4b8-66c31768164b.pdf"

TEXT_PAGE = 2
MASKED_PAGE = 1

PAGE_DIR_NAME = "page_002"
OTHER_PROCESSOR_NAMESPACES = ("image", "ocr", "llm")


def build_request(tmp_path: Path, source: Path = TEXT_PDF) -> PDFRequest:
    """Return a request whose options ask for everything the page can produce."""
    return build_pdf_request_for(source, tmp_path)


def process(tmp_path: Path, page_number: int = TEXT_PAGE, source: Path = TEXT_PDF):
    """Process one page into ``page_NNN/`` and return the result and its directory."""
    directory = tmp_path / f"page_{page_number:03d}"
    result = process_pdf_page(build_request(tmp_path, source), page_number, directory)
    return result, directory


def fail_with(error_type: str):
    """Return a stand-in primitive that raises a typed failure."""

    def raise_failure(*_args: object, **_kwargs: object) -> object:
        raise PDFPrimitiveError(
            error_type, "simulated failure", page_number=MASKED_PAGE, recoverable=True
        )

    return raise_failure


# --------------------------------------------------------------------------------------
# The happy path and the artifact tree
# --------------------------------------------------------------------------------------


def test_a_valid_page_publishes_the_documented_tree(tmp_path: Path) -> None:
    """The layout is the one ``subplan-procesador-pdf.md`` §3 fixes, and nothing else.

    Asserted as the complete set of files rather than as "these exist": an extra artifact in
    this namespace is a file a later stage would treat as part of the page.
    """
    _, directory = process(tmp_path)

    relative = sorted(
        str(path.relative_to(directory))
        for path in directory.rglob("*")
        if path.is_file()
    )

    assert relative == [
        "metadata.json",
        "native_text/blocks.json",
        "native_text/text.txt",
        "render/page.png",
        "source/page.pdf",
    ]


def test_a_valid_page_reports_success_and_valid(tmp_path: Path) -> None:
    """The happy path is ``success`` / ``VALID`` with no errors recorded."""
    result, _ = process(tmp_path)

    assert result.status == "success"
    assert result.validation.status == "VALID"
    assert not result.errors
    assert not result.validation.missing_artifacts


def test_the_result_points_at_the_artifacts_it_published(tmp_path: Path) -> None:
    """Every path on the result exists, and every one is listed in ``artifacts``."""
    result, _ = process(tmp_path)

    assert result.page_pdf is not None and result.page_pdf.exists()
    assert result.page_image is not None and result.page_image.exists()
    assert result.native_text is not None and result.native_text.exists()
    for path in (result.page_pdf, result.page_image, result.native_text):
        assert path in result.artifacts


def test_the_page_is_measured_and_classified(tmp_path: Path) -> None:
    """The metrics come from the real page and the classification is one of the three."""
    result, _ = process(tmp_path)

    assert result.metrics.characters > 0
    assert result.metrics.text_blocks > 0
    assert 0 < result.metrics.text_coverage < 1
    assert result.classification in ("TEXT", "IMAGE", "MIXED")


def test_the_text_blocks_are_published_as_json(tmp_path: Path) -> None:
    """``blocks.json`` round-trips the blocks, with a ``None`` box staying ``None``."""
    result, directory = process(tmp_path)

    payload = json.loads((directory / "native_text" / "blocks.json").read_text())

    assert len(payload) == len(result.text_blocks)
    for entry, block in zip(payload, result.text_blocks, strict=True):
        assert entry["block_id"] == block.block_id
        assert entry["text"] == block.text
        assert entry["page_number"] == block.page_number
        assert (entry["bbox"] is None) == (block.bbox is None)


def test_nothing_is_written_outside_this_processors_namespaces(tmp_path: Path) -> None:
    """No ``image/``, ``ocr/`` or ``llm/`` directory appears.

    Those belong to other processors; writing into them would have this processor claim
    work it does not do, and
    ``subplan-procesador-pdf.md`` §2 puts them out of bounds.

    Mutation that breaks it: write the render into ``image/`` instead of ``render/``. The
    assertion fails.
    """
    _, directory = process(tmp_path)

    top_level = {path.name for path in directory.iterdir()}
    assert top_level == {"source", "render", "native_text", "metadata.json"}
    for namespace in OTHER_PROCESSOR_NAMESPACES:
        assert not (directory / namespace).exists()


# --------------------------------------------------------------------------------------
# Provenance
# --------------------------------------------------------------------------------------


def test_the_metadata_records_every_required_key(tmp_path: Path) -> None:
    """The provenance keys ``docflow.identities`` fixes are all present.

    ``ARTIFACT_METADATA_KEYS`` and ``PAGE_ARTIFACT_METADATA_KEYS`` are the authority; reading
    them here rather than repeating the list means a change to the key set is caught here
    instead of shipping a metadata file that silently lacks a key.
    """
    _, directory = process(tmp_path)

    payload = json.loads((directory / "metadata.json").read_text())

    for key in (*ARTIFACT_METADATA_KEYS, *PAGE_ARTIFACT_METADATA_KEYS):
        assert key in payload, f"metadata.json is missing {key}"


def test_the_metadata_names_a_real_engine_and_version(tmp_path: Path) -> None:
    """The engine and its version are recorded, and neither is a placeholder.

    ``subplan-procesador-pdf.md`` §3 requires both; a blank or invented value would make two
    runs incomparable, which is the risk §10 names first.
    """
    result, directory = process(tmp_path)

    payload = json.loads((directory / "metadata.json").read_text())

    assert payload["engine"] == "poppler"
    assert payload["engine_version"]
    assert payload["engine_version"][0].isdigit()
    assert payload["processor"] == "pdf"
    assert payload["processor_version"] == result.metadata.processor_version


def test_the_recorded_identity_is_the_requested_one(tmp_path: Path) -> None:
    """The correlation context is echoed unchanged, never regenerated."""
    _, directory = process(tmp_path)

    payload = json.loads((directory / "metadata.json").read_text())

    assert payload["document_id"] == "doc-1"
    assert payload["workflow_run_id"] == "run-1"
    assert payload["page_number"] == TEXT_PAGE


def test_the_processing_key_is_present_and_explicitly_absent(tmp_path: Path) -> None:
    """``processing_key`` is recorded as ``None``, which is not the same as missing.

    The key is computed by ``ORC-02`` in Phase 2 from normalized options and input hashes the
    orchestrator owns. A processor that hashed its own would be making a workflow decision —
    out of bounds for this module — and worse, would be a second implementation of a value
    the reuse rule depends on being identical everywhere.

    Mutation that breaks it: compute a hash here. The assertion fails, and the reuse rule
    starts having two disagreeing sources.
    """
    _, directory = process(tmp_path)

    payload = json.loads((directory / "metadata.json").read_text())

    assert "processing_key" in payload
    assert payload["processing_key"] is None


# --------------------------------------------------------------------------------------
# The partial page (the acceptance criterion)
# --------------------------------------------------------------------------------------


def test_a_failing_capability_yields_a_partial_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Image extraction fails, the other artifacts survive, the page reports ``partial``.

    This is the acceptance criterion, and it is the case the error model exists for. A page
    whose images could not be written still has its render and its text, so losing the whole
    page would discard valid, expensive work — ``docs/plan/README.md`` §1.3.

    Mutation that breaks it: let the failure escape instead of recording it. The call raises
    and the test errors; the valid artifacts are never published.

    Note the shape of the guard: the three core artifacts are all present, so checking only
    for missing files would report ``VALID``. An earlier version of the validator did exactly
    that — it is the reason ``validate_pdf_page_result`` takes the recorded errors as well.
    """
    monkeypatch.setattr(
        "docflow.pdf.entrypoints.extract_images_from_page",
        fail_with("IMAGE_EXTRACTION_ERROR"),
    )

    result, _ = process(tmp_path, MASKED_PAGE, MASKED_PDF)

    assert result.status == "partial"
    assert result.validation.status == "PARTIAL"


def test_a_partial_page_keeps_every_valid_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``page.pdf``, ``page.png`` and ``text.txt`` are all present after the failure."""
    monkeypatch.setattr(
        "docflow.pdf.entrypoints.extract_images_from_page",
        fail_with("IMAGE_EXTRACTION_ERROR"),
    )

    result, _ = process(tmp_path, MASKED_PAGE, MASKED_PDF)

    assert result.page_pdf is not None and result.page_pdf.exists()
    assert result.page_image is not None and result.page_image.exists()
    assert result.native_text is not None and result.native_text.exists()


def test_a_partial_page_records_a_recoverable_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The failure is named, classified and marked recoverable.

    ``recoverable`` is what tells the orchestrator the page can be kept, so it is asserted
    rather than assumed; the classification is the one the contract already defines.
    """
    monkeypatch.setattr(
        "docflow.pdf.entrypoints.extract_images_from_page",
        fail_with("IMAGE_EXTRACTION_ERROR"),
    )

    result, _ = process(tmp_path, MASKED_PAGE, MASKED_PDF)

    failures = [
        error for error in result.errors if error.type == "IMAGE_EXTRACTION_ERROR"
    ]
    assert failures
    assert all(error.recoverable for error in failures)
    assert all(error.page_number == MASKED_PAGE for error in failures)


def test_a_partial_page_status_reaches_the_metadata_on_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The written ``metadata.json`` says ``partial`` too.

    The in-memory result is not the artifact a later stage reads; a disagreement between the
    two would make the file useless for exactly the decision it is meant to inform.

    Mutation that breaks it: publish the metadata before setting the final status. The file
    says ``success`` while the result says ``partial``.
    """
    monkeypatch.setattr(
        "docflow.pdf.entrypoints.extract_images_from_page",
        fail_with("IMAGE_EXTRACTION_ERROR"),
    )

    _, directory = process(tmp_path, MASKED_PAGE, MASKED_PDF)

    payload = json.loads((directory / "metadata.json").read_text())

    assert payload["status"] == "partial"
    assert payload["validation"] == "PARTIAL"
    assert any(entry["type"] == "IMAGE_EXTRACTION_ERROR" for entry in payload["errors"])


def test_a_failing_render_still_leaves_the_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same containment holds for a different capability.

    One capability's containment is not evidence for another's: each is a separate call with
    its own failure path, and a page that kept its render when text failed would still be
    losing the case that matters here.
    """
    monkeypatch.setattr(
        "docflow.pdf.entrypoints.render_page_to_image", fail_with("RENDER_ERROR")
    )

    result, _ = process(tmp_path)

    assert result.status == "partial"
    assert result.page_image is None
    assert result.native_text is not None and result.native_text.exists()
    assert any(error.type == "RENDER_ERROR" for error in result.errors)


def test_a_page_asked_for_nothing_succeeds_having_done_nothing(tmp_path: Path) -> None:
    """No capabilities requested is not a failure: nothing was asked and nothing failed.

    Worth pinning because the opposite reading is tempting. A page with no artifacts looks
    like a page that produced nothing, but it produced exactly what it was told to, and
    reporting ``failed`` would be a lie about why the run was empty. The status describes the
    run's outcome, not the artifact count.

    Mutation that breaks it: count missing artifacts regardless of the options. The verdict
    becomes ``INVALID`` and this page reports ``failed`` for obeying its request.
    """
    request = PDFRequest(
        pdf_path=TEXT_PDF,
        output_dir=tmp_path,
        options=PDFOptions(
            extract_pages=False,
            render=False,
            extract_text=False,
            extract_images=False,
            layout=False,
            dpi=200,
        ),
        context=PDFContext(document_id="doc-1", workflow_run_id="run-1"),
    )

    result = process_pdf_page(request, TEXT_PAGE, tmp_path / PAGE_DIR_NAME)

    assert result.status == "success"
    assert result.validation.status == "VALID"
    assert not result.artifacts


def test_a_page_whose_every_requested_capability_failed_is_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """All three requested capabilities failing is ``failed``, not ``partial``.

    There is no partial result to keep when nothing survived, so calling it ``PARTIAL`` would
    tell the orchestrator there is recoverable work here.

    ``extract_pages`` is off because that capability raises rather than records — a page that
    does not exist has nothing to keep — so the reachable version of "everything failed" is
    the two remaining capabilities both failing.

    Mutation that breaks it: return ``PARTIAL`` whenever any artifact is missing. The page
    reports recoverable work that does not exist.
    """
    monkeypatch.setattr(
        "docflow.pdf.entrypoints.render_page_to_image", fail_with("RENDER_ERROR")
    )
    monkeypatch.setattr(
        "docflow.pdf.entrypoints.engine_report", fail_with("TEXT_EXTRACTION_ERROR")
    )

    request = PDFRequest(
        pdf_path=TEXT_PDF,
        output_dir=tmp_path,
        options=PDFOptions(
            extract_pages=False,
            render=True,
            extract_text=True,
            extract_images=False,
            layout=True,
            dpi=200,
        ),
        context=PDFContext(document_id="doc-1", workflow_run_id="run-1"),
    )

    result = process_pdf_page(request, TEXT_PAGE, tmp_path / PAGE_DIR_NAME)

    assert result.status == "failed"
    assert result.validation.status == "INVALID"
    assert {error.type for error in result.errors} == {
        "RENDER_ERROR",
        "TEXT_EXTRACTION_ERROR",
    }


# --------------------------------------------------------------------------------------
# Options and boundaries
# --------------------------------------------------------------------------------------


def test_a_capability_that_was_not_requested_produces_nothing(tmp_path: Path) -> None:
    """``render: false`` means no render artifact and no error.

    ``PDF-05``'s acceptance criterion states this from the primitive's side; here it is the
    composition's job not to call the primitive at all.
    """
    request = PDFRequest(
        pdf_path=TEXT_PDF,
        output_dir=tmp_path,
        options=PDFOptions(
            extract_pages=True,
            render=False,
            extract_text=True,
            extract_images=True,
            layout=True,
            dpi=200,
        ),
        context=PDFContext(document_id="doc-1", workflow_run_id="run-1"),
    )

    result = process_pdf_page(request, TEXT_PAGE, tmp_path / PAGE_DIR_NAME)

    assert result.page_image is None
    assert not (tmp_path / PAGE_DIR_NAME / "render").exists()
    # A capability that was not asked for is not a capability that failed.
    assert result.status == "success"
    assert not [error for error in result.errors if error.type == "RENDER_ERROR"]


def test_a_page_below_one_is_refused(tmp_path: Path) -> None:
    """Page 0 never reaches the engine, through either the split or the render."""
    request = build_request(tmp_path)

    for invalid in (0, -1):
        with pytest.raises(ValueError, match="1-based"):
            process_pdf_page(request, invalid, tmp_path / f"bad{invalid}")


def test_a_page_that_does_not_exist_is_raised_not_recorded(tmp_path: Path) -> None:
    """A page the document does not have is the one failure that escapes.

    Every other failure is recorded so the page can survive it. This one cannot: there is no
    page to keep, so returning a partial result would invent one.
    """
    request = build_request(tmp_path)

    with pytest.raises(PDFPrimitiveError) as failure:
        process_pdf_page(request, 99, tmp_path / "page_099")

    assert failure.value.error_type == "PAGE_OUT_OF_RANGE"


def test_no_staged_file_survives_a_successful_page(tmp_path: Path) -> None:
    """Publication is atomic, so nothing is left holding a ``.tmp`` suffix."""
    _, directory = process(tmp_path)

    leftovers = [path.name for path in directory.rglob(f"*{TEMP_SUFFIX}")]

    assert not leftovers, f"a staged file was published: {leftovers}"


def test_the_input_document_is_never_modified(tmp_path: Path) -> None:
    """Processing a page does not touch the source, and writes nothing beside it."""
    before = TEXT_PDF.read_bytes()
    before_tree = sorted(path.name for path in TEXT_PDF.parent.iterdir())

    process(tmp_path)

    assert TEXT_PDF.read_bytes() == before
    assert sorted(path.name for path in TEXT_PDF.parent.iterdir()) == before_tree


def test_processing_the_same_page_twice_is_deterministic(tmp_path: Path) -> None:
    """The same page processed twice produces the same metrics and classification.

    The determinism class ``subplan-procesador-pdf.md`` §3 declares for this processor. The
    timing differs between runs by construction, so it is excluded rather than compared.
    """
    first, _ = process(tmp_path / "one")
    second, _ = process(tmp_path / "two")

    assert first.metrics == second.metrics
    assert first.classification == second.classification
    assert first.status == second.status
