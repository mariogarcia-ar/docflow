"""Processor invocation helpers (``ORC-14``).

The helpers are the orchestrator's whole knowledge of the processors, so what they are
tested for is exactly that: they call the contract once, and they register what it
returned.
"""

from __future__ import annotations

from pathlib import Path

from docflow.image import ImageContext, ImageRequest
from docflow.llm import LLMInput
from docflow.workflow.contracts import StageExecution
from docflow.workflow.detection import detect_input_type
from docflow.workflow.invocation import run_image_processing, run_llm
from tests.fakes.processors import ProcessorDoubles
from tests.image.samples import build_options as build_image_options
from tests.workflow.samples import SAMPLE_IMAGE
from tests.workflow.samples import stage as build_stage


def _stage() -> StageExecution:
    """Return a fresh stage execution for an image."""
    return build_stage("IMAGE", input_artifacts=(SAMPLE_IMAGE,))


def test_the_image_helper_calls_the_contract_once_and_registers_its_artifacts(
    tmp_path: Path, processors: ProcessorDoubles
) -> None:
    """One call, and every published representation recorded on the stage."""
    stage = _stage()
    request = ImageRequest(
        image_path=SAMPLE_IMAGE,
        output_dir=tmp_path / "image",
        options=build_image_options(),
        context=ImageContext(
            document_id="doc-1", page_number=1, workflow_run_id="run-1"
        ),
    )

    result = run_image_processing(request, stage)

    assert processors.image.calls == 1
    assert result.status == "success"
    assert len(stage.output_artifacts) == 3
    assert all(artifact.is_file() for artifact in stage.output_artifacts)
    assert len(stage.metadata["output_hashes"]) == 3


def test_the_llm_helper_reaches_the_processor_through_its_entry_point(
    processors: ProcessorDoubles,
) -> None:
    """The seam is the processor's public entry point and nothing lower."""
    stage = build_stage("LLM")
    request = LLMInput(
        task="extract_fields",
        provider="ollama",
        model="test-model",
        template="simple_extract",
        document="some text",
        images=[],
        extra_context={},
        schema="simple",
        options={},
        graph=None,
        metadata={},
    )

    result = run_llm(request, stage)

    assert processors.llm.calls == 1
    assert processors.llm.requests == [request]
    assert result.parsed_response == {"fields": {"total": "42.00"}}


def test_detection_is_not_a_processor_call(processors: ProcessorDoubles) -> None:
    """The input type is decided without reaching anything."""
    assert detect_input_type(SAMPLE_IMAGE, "auto") == "IMAGE"
    assert processors.calls() == {"pdf": 0, "image": 0, "ocr": 0, "llm": 0}
