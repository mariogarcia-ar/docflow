"""Preparing the document skeleton (``ORC-10``)."""

from __future__ import annotations

from pathlib import Path

from docflow.states import StageState
from docflow.workflow.context import create_document_context
from docflow.workflow.preparation import prepare_document
from tests.fakes.processors import ProcessorDoubles
from tests.workflow.samples import SAMPLE_IMAGE, document_request, execution_policy


def test_a_pdf_becomes_one_page_context_per_page(
    tmp_path: Path, processors: ProcessorDoubles
) -> None:
    """The document's pages come from the PDF stage's own per-page results."""
    processors.pdf.pages = 3
    request = document_request(tmp_path)
    context = create_document_context(
        request, input_type="PDF", workflow_run_id="run-1"
    )

    prepared = prepare_document(context, request)

    assert [page.page_number for page in prepared.pages] == [1, 2, 3]
    assert prepared.stages["PDF"].status is StageState.SUCCESS
    assert all(page.artifacts["page_image"] is not None for page in prepared.pages)
    assert all(page.artifacts["native_text"] is not None for page in prepared.pages)
    assert all(page.status is StageState.READY for page in prepared.pages)


def test_a_direct_image_becomes_one_logical_page(
    tmp_path: Path, processors: ProcessorDoubles
) -> None:
    """The image is the page, and no PDF stage pretends to have run."""
    request = document_request(tmp_path, input_path=SAMPLE_IMAGE, input_type="IMAGE")
    context = create_document_context(
        request, input_type="IMAGE", workflow_run_id="run-1"
    )

    prepared = prepare_document(context, request)

    assert [page.page_number for page in prepared.pages] == [1]
    assert prepared.pages[0].artifacts["page_image"] == SAMPLE_IMAGE
    assert "PDF" not in prepared.stages
    assert processors.pdf.calls == 0
    assert any(
        record.get("reason") == "direct_image_input" for record in prepared.decisions
    )


def test_a_dry_run_prepares_without_running_the_pdf_stage(
    tmp_path: Path, processors: ProcessorDoubles
) -> None:
    """A dry run cannot both inspect the run and pay for it."""
    request = document_request(tmp_path, execution=execution_policy(dry_run=True))
    context = create_document_context(
        request, input_type="PDF", workflow_run_id="run-1"
    )

    prepared = prepare_document(context, request)

    assert processors.pdf.calls == 0
    assert prepared.pages == []
    assert prepared.stages["PDF"].status is StageState.NOT_STARTED
