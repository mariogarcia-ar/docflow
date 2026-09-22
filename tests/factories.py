"""Shared builders for the contract round-trip tests (``GEN-06``).

Five contracts are round-tripped by five test modules, and every one of them needs a valid
request to round-trip. Building each request once here keeps the properties that matter in
the tests — identity preservation, no silent stand-in, descriptive classification — and
keeps the request literals out of five copies.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from docflow.image import ImageContext, ImageOptions, ImageRequest
from docflow.llm import LLMInput
from docflow.ocr import OCRContext, OCROptions, OCRRequest
from docflow.pdf import PDFContext, PDFOptions, PDFRequest
from docflow.workflow import DocumentRequest, ExecutionPolicy


def incomplete_call(target: Any, kwargs: dict[str, Any]) -> Any:
    """Call ``target`` with keyword arguments that are deliberately incomplete.

    ``target`` is typed ``Any`` on purpose. The whole point of the call is that it is
    arity-invalid, so a static arity check would flag the test rather than the behaviour
    under test; routing it through ``Any`` keeps the real constructor call real without
    silencing a checker globally.

    Args:
        target: The callable under test.
        kwargs: The arguments to pass.

    Returns:
        Whatever ``target`` returns. A contract with a required field raises ``TypeError``
        instead of returning, which is what the callers assert.
    """
    return target(**kwargs)


def default_execution_policy() -> ExecutionPolicy:
    """Return the execution policy the orchestrator tests run under."""
    return ExecutionPolicy(
        resume=False,
        reuse_successful=True,
        retry_failed=False,
        skip_stages=[],
        force_stages=[],
        stop_after_stage=None,
        start_from_stage=None,
        invalidate_downstream=True,
        dry_run=False,
        parallel_pages=True,
    )


def build_pdf_options() -> PDFOptions:
    """Return a fully specified set of PDF capabilities."""
    return PDFOptions(
        extract_pages=True,
        render=True,
        extract_text=True,
        extract_images=True,
        layout=True,
        dpi=200,
    )


def build_pdf_request(tmp_path: Path) -> PDFRequest:
    """Return a valid PDF request rooted in ``tmp_path``."""
    return PDFRequest(
        pdf_path=tmp_path / "document.pdf",
        output_dir=tmp_path / "document",
        options=build_pdf_options(),
        context=PDFContext(document_id="doc-1", workflow_run_id="run-1"),
    )


def build_image_options() -> ImageOptions:
    """Return a fully specified set of image transformations."""
    return ImageOptions(
        normalize=True,
        prepare_for_ocr=True,
        prepare_for_vlm=True,
        correct_orientation=True,
        deskew=True,
    )


def build_image_request(tmp_path: Path) -> ImageRequest:
    """Return a valid image request rooted in ``tmp_path``."""
    return ImageRequest(
        image_path=tmp_path / "page.png",
        output_dir=tmp_path / "image",
        options=build_image_options(),
        context=ImageContext(
            document_id="doc-1", page_number=1, workflow_run_id="run-1"
        ),
    )


def build_ocr_options() -> OCROptions:
    """Return a fully specified set of OCR options."""
    return OCROptions(
        ocr=True,
        layout=True,
        tables=True,
        reading_order=True,
        language="en",
        engine_options={"do_table_structure": True},
    )


def build_ocr_request(tmp_path: Path) -> OCRRequest:
    """Return a valid OCR request rooted in ``tmp_path``."""
    return OCRRequest(
        image_path=tmp_path / "ocr_ready.png",
        output_dir=tmp_path / "ocr",
        options=build_ocr_options(),
        context=OCRContext(document_id="doc-1", page_number=1, workflow_run_id="run-1"),
    )


def build_llm_input() -> LLMInput:
    """Return a valid single-call LLM input with no graph."""
    return LLMInput(
        task="extract_fields",
        provider="ollama",
        model="test-model",
        template="simple_extract",
        document="A document body.",
        images=[],
        extra_context={},
        schema="simple",
        options={"temperature": 0.0},
        graph=None,
        metadata={"document_id": "doc-1", "workflow_run_id": "run-1"},
    )


def build_document_request(tmp_path: Path) -> DocumentRequest:
    """Return a valid document request rooted in ``tmp_path``."""
    return DocumentRequest(
        document_id="doc-1",
        input_path=tmp_path / "document.pdf",
        input_type="PDF",
        workflow="default",
        policies={"allow_ocr": True, "allow_vlm": False},
        execution=default_execution_policy(),
        options={},
        metadata={},
    )
