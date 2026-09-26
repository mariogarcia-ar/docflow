"""Calling the four processors, and nothing else (``ORC-14``).

The orchestrator's entire knowledge of the processors is these five functions. Each one
builds nothing, decides nothing and reads no engine: it calls one processor through its
public contract, records the artifacts the processor published on the stage that owns it,
and hands the typed result back.

The processor is resolved **through its module at call time** — ``docflow.pdf.process_pdf``
rather than a name bound at import — so the seam is the module attribute, which is what a
contract-level fake replaces. No engine (Poppler, OpenCV, Docling, a provider) is reachable
from here, and no processor ``primitives/`` module is imported at all.
"""

from __future__ import annotations

from typing import Any

from docflow import image as image_processor
from docflow import llm as llm_processor
from docflow import ocr as ocr_processor
from docflow import pdf as pdf_processor
from docflow.image import ImageRequest, ImageResult
from docflow.llm import LLMInput, LLMResult
from docflow.ocr import OCRRequest, OCRResult
from docflow.pdf import PDFRequest, PDFResult
from docflow.states import StageState
from docflow.workflow.contracts import StageExecution
from docflow.workflow.stages import register_stage_outputs


def run_pdf(request: PDFRequest, stage: StageExecution) -> PDFResult:
    """Run the PDF processor and register what it published.

    Args:
        request: The PDF request, built by the caller.
        stage: The stage execution the artifacts belong to.

    Returns:
        The processor's typed result, never an exception.
    """
    result = pdf_processor.process_pdf(request)
    register_stage_outputs(stage, result.artifacts)
    return result


def run_image_processing(request: ImageRequest, stage: StageExecution) -> ImageResult:
    """Run the image processor and register what it published.

    Args:
        request: The image request, built by the caller.
        stage: The stage execution the artifacts belong to.

    Returns:
        The processor's typed result, never an exception.
    """
    result = image_processor.process_image(request)
    register_stage_outputs(stage, [reference.path for reference in result.artifacts])
    return result


def run_ocr(request: OCRRequest, stage: StageExecution) -> OCRResult:
    """Run the OCR processor and register what it published.

    Args:
        request: The OCR request, built by the caller.
        stage: The stage execution the artifacts belong to.

    Returns:
        The processor's typed result, never an exception.
    """
    result = ocr_processor.process_ocr_image(request)
    artifacts = result.artifacts
    if artifacts is not None:
        register_stage_outputs(
            stage,
            [
                artifacts.text,
                artifacts.markdown,
                artifacts.structured_document,
                artifacts.metadata,
            ],
        )
    return result


def run_llm(request: LLMInput, stage: StageExecution) -> LLMResult:
    """Run the LLM processor and register what it published.

    Args:
        request: The inference request, built by the caller.
        stage: The stage execution the artifacts belong to.

    Returns:
        The processor's typed result, never an exception.

    # TODO: [MVP] ``LLMResult`` carries no artifact list, so nothing is registered and the
    # reuse rule for this stage falls back to status and key. The processor contract is
    # what has to expose its paths.
    """
    # pylint: disable=unused-argument
    # Reason: the parameter is the seam's shape, shared by the four invocation helpers; a
    # caller must not have to know which processor happens to publish paths today.
    return llm_processor.process_llm_request(request)


def result_succeeded(result: PDFResult | ImageResult | OCRResult | LLMResult) -> bool:
    """Return whether a processor's result reports success.

    Args:
        result: Any of the four processors' results.

    Returns:
        ``True`` on the processors' own success vocabulary. The three documental
        processors report ``"success"``; the LLM processor reports the shared stage state.
    """
    if isinstance(result, LLMResult):
        return result.status is StageState.SUCCESS
    return result.status == "success"


def describe_failure(
    result: PDFResult | ImageResult | OCRResult | LLMResult,
) -> dict[str, Any]:
    """Return the typed failure a processor result carries, and its context.

    Args:
        result: A result whose status reports failure.

    Returns:
        A record naming the typed kind, the message and whether the run could continue.
        The typed kind is always present: a message alone is not a classification.
    """
    if isinstance(result, LLMResult) and result.errors:
        error = result.errors[0]
        return {
            "type": error.type,
            "message": error.message,
            "recoverable": error.recoverable,
            "metadata": dict(error.metadata),
        }
    error = getattr(result, "error", None)
    if error is not None:
        return {
            "type": error.type,
            "message": error.message,
            "recoverable": error.recoverable,
            "metadata": dict(error.metadata),
        }
    errors = getattr(result, "errors", [])
    if errors:
        first = errors[0]
        return {
            "type": first.type,
            "message": first.message,
            "recoverable": first.recoverable,
            "metadata": dict(first.metadata),
        }
    return {
        "type": "INTERNAL_ERROR",
        "message": "the processor reported failure without a typed error",
        "recoverable": False,
        "metadata": {},
    }
