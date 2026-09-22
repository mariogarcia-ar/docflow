"""Tests for the document entry point (``PDF-10``).

The composition itself is exercised through ``process_pdf``, but the centre of gravity here
is **invariant 1** of ``subplan-procesador-pdf.md`` §6: every input page yields exactly one
``PDFPageResult`` and one ``page_NNN/`` directory, and the reported page count agrees with
the pages actually processed.

That invariant is the one only the document can check. A page loop that drops its last page
still produces perfectly valid page results — each of them independently correct — so no
page-level test can see the gap. The document-level count is the only witness.

A second theme is the aggregate: it must describe what the document *yielded*, and the tests
pin that it agrees with the pages it summarises rather than being plausible on its own.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from docflow.identities import ARTIFACT_METADATA_KEYS
from docflow.pdf import PDFContext, PDFRequest
from docflow.pdf.contracts import PDFError, PDFPageResult, PDFPageValidation
from docflow.pdf.entrypoints import EMPTY_METRICS, process_pdf
from docflow.pdf.primitives.composition import aggregate_page_metrics
from docflow.pdf.primitives.failures import PDFPrimitiveError
from docflow.pdf.primitives.validation import page_metadata
from tests.factories import build_pdf_options, build_pdf_request_for

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
THREE_PAGE_PDF = FIXTURES / "matrix" / "three-invoices.pdf"
SINGLE_PAGE_PDF = FIXTURES / "matrix" / "scan150.pdf"

PAGE_COUNT = 3


def build_request(tmp_path: Path, source: Path = THREE_PAGE_PDF) -> PDFRequest:
    """Return a request whose options ask for everything, rooted in ``tmp_path``."""
    return build_pdf_request_for(source, tmp_path)


def run(tmp_path: Path, source: Path = THREE_PAGE_PDF):
    """Process a whole document and return the result and its output root."""
    root = tmp_path / "document"
    return process_pdf(build_request(root, source)), root


# --------------------------------------------------------------------------------------
# Invariant 1 — page completeness
# --------------------------------------------------------------------------------------


def test_every_page_produces_exactly_one_result(tmp_path: Path) -> None:
    """The number of page results equals the number of pages the engine reported.

    Mutation that breaks it: iterate ``range(page_count - 1)`` in the page loop, dropping the
    last page. Every remaining page result is still valid, so only this count reveals the
    gap — which is why the invariant is asserted at the document level.
    """
    result, _ = run(tmp_path)

    assert result.metadata.page_count == PAGE_COUNT
    assert len(result.pages) == PAGE_COUNT
    assert len(result.pages) == result.metadata.page_count


def test_the_pages_are_in_page_order(tmp_path: Path) -> None:
    """Page numbers are contiguous, ascending and start at one.

    Mutation that breaks it: sort ``pages`` by something other than the page number, or
    iterate a set. The order stops matching and the assertion fails. ``PDF-13`` uses the same
    check with a duplicated page as its mutation.

    The order is also written to ``metadata.json``, so a consumer can check it without
    walking the tree.
    """
    result, root = run(tmp_path)

    assert [page.page_number for page in result.pages] == list(range(1, PAGE_COUNT + 1))
    assert json.loads((root / "metadata.json").read_text())["page_order"] == [
        1,
        2,
        3,
    ]


def test_every_page_gets_its_own_directory(tmp_path: Path) -> None:
    """One ``page_NNN/`` directory per page, and no others.

    The directories are counted rather than checked for existence: a loop that ran one page
    twice would leave the right set of directories only if it also reused the number, and the
    set comparison catches that.
    """
    _, root = run(tmp_path)

    directories = sorted(
        path.name
        for path in root.iterdir()
        if path.is_dir() and path.name.startswith("page_")
    )

    assert directories == [f"page_{index:03d}" for index in range(1, PAGE_COUNT + 1)]


def test_a_page_count_of_one_is_not_a_special_case(tmp_path: Path) -> None:
    """A single-page document yields one page result.

    Worth an explicit case: an off-by-one in the loop bound often shows up only at the
    boundary, and a loop that dropped the last page would still pass on a document whose
    tests all used three pages if the bound happened to be inclusive.
    """
    result, _ = run(tmp_path, SINGLE_PAGE_PDF)

    assert result.metadata.page_count == 1
    assert len(result.pages) == 1
    assert result.pages[0].page_number == 1


# --------------------------------------------------------------------------------------
# The document result
# --------------------------------------------------------------------------------------


def test_a_valid_document_reports_success(tmp_path: Path) -> None:
    """The happy path is ``success`` / ``VALID`` with no errors."""
    result, _ = run(tmp_path)

    assert result.status == "success"
    assert result.validation.status == "VALID"
    assert not result.errors
    assert all(page.status == "success" for page in result.pages)


def test_the_source_is_copied_immutably(tmp_path: Path) -> None:
    """``source/document.pdf`` exists and is byte-identical to the input.

    A reference copy, not a transformation: ``subplan-procesador-pdf.md`` §3 keeps the
    original bytes so a later stage can re-read the document exactly as it arrived.
    """
    result, root = run(tmp_path)

    copy = root / "source" / "document.pdf"

    assert copy.exists()
    assert copy.read_bytes() == THREE_PAGE_PDF.read_bytes()
    assert copy in result.artifacts
    assert result.source_path == THREE_PAGE_PDF


def test_the_input_document_is_never_modified(tmp_path: Path) -> None:
    """The immutable-input invariant, at document scope.

    Mutation that breaks it: copy the document onto itself, or write the reference copy to
    ``request.pdf_path``. The digest comparison fails.

    The directory listing is compared before and after as well, so the test reports its own
    pollution rather than asserting an absolute that may already be false.
    """
    before = THREE_PAGE_PDF.read_bytes()
    before_tree = sorted(path.name for path in THREE_PAGE_PDF.parent.iterdir())

    run(tmp_path)

    assert THREE_PAGE_PDF.read_bytes() == before
    assert sorted(path.name for path in THREE_PAGE_PDF.parent.iterdir()) == before_tree


def test_the_aggregate_agrees_with_the_pages_it_summarises(tmp_path: Path) -> None:
    """The document's totals are the sums of its pages, not an independent reading.

    Mutation that breaks it: compute the aggregate from a second engine pass, or from the
    first page alone. The comparison against the per-page sum fails, which is the check that
    makes the aggregate trustworthy rather than merely plausible.
    """
    result, _ = run(tmp_path)

    assert result.metrics.characters == sum(
        page.metrics.characters for page in result.pages
    )
    assert result.metrics.words == sum(page.metrics.words for page in result.pages)
    assert result.metrics.images == sum(page.metrics.images for page in result.pages)
    assert result.metrics == aggregate_page_metrics(
        [page.metrics for page in result.pages]
    )


def test_the_aggregate_reports_the_largest_single_image(tmp_path: Path) -> None:
    """The aggregate's ``largest_image_coverage`` is a maximum, not a sum or a mean.

    Conflating it with the mean would make a document with one full-page scan look the same
    as a document with many small ones.
    """
    result, _ = run(tmp_path)

    assert result.metrics.largest_image_coverage == max(
        page.metrics.largest_image_coverage for page in result.pages
    )


def test_the_artifacts_list_covers_every_published_file(tmp_path: Path) -> None:
    """Every artifact in the list exists, and each page's files are represented."""
    result, _ = run(tmp_path)

    assert result.artifacts
    for path in result.artifacts:
        assert path.exists(), f"{path} is listed but was not published"

    for page in result.pages:
        for path in page.artifacts:
            assert path in result.artifacts


def test_the_artifacts_list_has_no_duplicates(tmp_path: Path) -> None:
    """A file reached by two paths appears once, so the list is a set of real files."""
    result, _ = run(tmp_path)

    assert len(result.artifacts) == len(set(result.artifacts))


# --------------------------------------------------------------------------------------
# Provenance
# --------------------------------------------------------------------------------------


def test_the_document_metadata_records_every_required_key(tmp_path: Path) -> None:
    """The provenance keys ``docflow.identities`` fixes are all present.

    Read from ``ARTIFACT_METADATA_KEYS`` rather than repeated, so a change to the key set is
    caught here instead of shipping a metadata file that silently lacks a key.
    """
    _, root = run(tmp_path)

    payload = json.loads((root / "metadata.json").read_text())

    for key in ARTIFACT_METADATA_KEYS:
        assert key in payload, f"metadata.json is missing {key}"


def test_the_document_metadata_names_the_engine_and_the_page_count(
    tmp_path: Path,
) -> None:
    """The engine, its version and the page count are all recorded."""
    result, root = run(tmp_path)

    payload = json.loads((root / "metadata.json").read_text())

    assert payload["engine"] == "poppler"
    assert payload["engine_version"][0].isdigit()
    assert payload["processor"] == "pdf"
    assert payload["page_count"] == PAGE_COUNT
    assert payload["pages_processed"] == PAGE_COUNT
    assert payload["processor_version"] == result.metadata.processor_version


def test_the_processing_key_is_explicitly_not_computed(tmp_path: Path) -> None:
    """``processing_key`` is ``None`` at document level too, for the same reason as the page.

    ``ORC-02`` owns the formula in Phase 2. A processor that hashed its own would be making
    a workflow decision and would be a second implementation of a value the reuse rule needs
    to be identical everywhere.
    """
    _, root = run(tmp_path)

    payload = json.loads((root / "metadata.json").read_text())

    assert "processing_key" in payload
    assert payload["processing_key"] is None


def test_the_document_metadata_reports_partial_when_a_page_is_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A document with one partial page is partial, and says so on disk.

    A caller that reads ``success`` will assume the whole document is there, so this is the
    one status that must not be optimistic.

    Mutation that breaks it: report ``success`` whenever the validation is ``VALID``. The
    partial page's own verdict is ``PARTIAL``, so the document-level check fails.
    """

    def fail_images(*_args: object, **_kwargs: object) -> object:
        raise PDFPrimitiveError(
            "IMAGE_EXTRACTION_ERROR", "simulated", page_number=1, recoverable=True
        )

    monkeypatch.setattr("docflow.pdf.entrypoints.extract_images_from_page", fail_images)

    result, root = run(tmp_path)

    assert result.status == "partial"
    assert result.validation.status == "PARTIAL"
    assert any(page.status == "partial" for page in result.pages)
    assert json.loads((root / "metadata.json").read_text())["status"] == "partial"


# --------------------------------------------------------------------------------------
# Boundaries
# --------------------------------------------------------------------------------------


def test_a_document_whose_every_page_failed_is_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """All pages failing is ``failed``, not ``partial``.

    ``partial`` promises there is something to keep; when nothing survived there is not.

    The pages are made to fail by replacing the page entry point with one that reports a
    failed page — the document loop is what is under test here, and driving it through real
    engine failures would only re-test ``PDF-09``.

    Mutation that breaks it: the trailing ``or pages`` this function originally had, which
    made the ``failed`` branch unreachable for any document with pages — that is, for every
    document that reaches it. The assertion then reads ``partial``.
    """

    def failed_page(
        request: PDFRequest, page_number: int, output_dir: Path
    ) -> PDFPageResult:
        del request, output_dir
        return PDFPageResult(
            page_number=page_number,
            page_pdf=None,
            page_image=None,
            native_text=None,
            text_blocks=[],
            embedded_images=[],
            metrics=EMPTY_METRICS,
            classification="MIXED",
            artifacts=[],
            validation=PDFPageValidation(
                status="INVALID",
                errors=[
                    PDFError(
                        type="IO_ERROR",
                        page_number=page_number,
                        message="simulated",
                        recoverable=False,
                        metadata={},
                    )
                ],
                missing_artifacts=[],
            ),
            metadata=page_metadata(
                engine_name="poppler",
                engine_version="test",
                processor="pdf",
                processor_version="test",
                context=PDFContext(document_id="doc-1", workflow_run_id="run-1"),
                timing={},
            ),
            status="failed",
        )

    monkeypatch.setattr("docflow.pdf.entrypoints.process_pdf_page", failed_page)

    request = build_request(tmp_path / "document")

    result = process_pdf(request)

    assert all(page.status == "failed" for page in result.pages)
    assert result.status == "failed"


def test_a_document_that_cannot_be_read_raises(tmp_path: Path) -> None:
    """An unreadable document has no partial result worth returning."""
    request = PDFRequest(
        pdf_path=tmp_path / "absent.pdf",
        output_dir=tmp_path / "out",
        options=build_pdf_options(),
        context=PDFContext(document_id="doc-1", workflow_run_id="run-1"),
    )

    with pytest.raises(PDFPrimitiveError) as failure:
        process_pdf(request)

    assert failure.value.error_type == "MISSING_FILE"


def test_no_staged_file_survives_a_document_run(tmp_path: Path) -> None:
    """Atomic publication holds at document scope as well as per page."""
    _, root = run(tmp_path)

    leftovers = [str(path.relative_to(root)) for path in root.rglob("*.tmp")]

    assert not leftovers, f"a staged file was published: {leftovers}"


def test_the_same_document_processed_twice_agrees(tmp_path: Path) -> None:
    """Two runs over the same bytes produce the same metrics, order and statuses.

    The determinism class ``subplan-procesador-pdf.md`` §3 declares for this processor.
    Timing differs by construction and is excluded.
    """
    first, _ = run(tmp_path / "one")
    second, _ = run(tmp_path / "two")

    assert first.metrics == second.metrics
    assert [page.page_number for page in first.pages] == [
        page.page_number for page in second.pages
    ]
    assert first.status == second.status
    assert [page.classification for page in first.pages] == [
        page.classification for page in second.pages
    ]
