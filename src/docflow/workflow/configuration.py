"""Reading the run's configuration, and refusing to guess it (``ORC-02`` / ``ORC-14``).

Everything a stage needs that is not state is *data in the request*: which options the
processors get, which provider and model the LLM call uses, and where artifacts are
written. This module is the one place that reads those values, so "the orchestrator never
invented a default" is checkable in one file.

A missing key is **refused by name**: there is no fallback model, no default DPI and no
implicit output directory, because each of those would be a silent stand-in for a decision
the caller did not make. The refusal is an exception here and is converted into a failed
``DocumentResult`` at the entry point, so it never crosses the public contract.

The processor identity (name and version) comes from each processor's own entry-point
module. It is the processor's statement about itself, which is what the processing key has
to be computed from; duplicating the numbers here would let them drift.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from docflow.image import ImageOptions
from docflow.image import entrypoints as image_entrypoints
from docflow.llm import entrypoints as llm_entrypoints
from docflow.ocr import OCROptions
from docflow.ocr import entrypoints as ocr_entrypoints
from docflow.pdf import PDFOptions
from docflow.pdf import entrypoints as pdf_entrypoints
from docflow.workflow import identity
from docflow.workflow.contracts import (
    DocumentContext,
    DocumentRequest,
    ExecutionPolicy,
    StageName,
)

#: Processor name and version per stage, as each processor states them about itself.
PROCESSOR_IDENTITIES: dict[StageName, tuple[str, str]] = {
    "PDF": (pdf_entrypoints.PROCESSOR_NAME, pdf_entrypoints.PROCESSOR_VERSION),
    "IMAGE": (image_entrypoints.PROCESSOR_NAME, image_entrypoints.PROCESSOR_VERSION),
    "OCR": (ocr_entrypoints.PROCESSOR_NAME, ocr_entrypoints.PROCESSOR_VERSION),
    "LLM": (llm_entrypoints.PROCESSOR_NAME, llm_entrypoints.PROCESSOR_VERSION),
}

#: Identity of the orchestrator itself, for the document-level processing key.
WORKFLOW_NAME: Final[str] = "workflow"
WORKFLOW_VERSION: Final[str] = "0.0.0"


class WorkflowConfigurationError(Exception):
    """The request is missing configuration a stage cannot run without.

    Attributes:
        key: The option key that was missing, named so the caller can fix it.
    """

    def __init__(self, key: str, message: str) -> None:
        super().__init__(message)
        self.key = key


@dataclass(frozen=True)
class LlmSettings:
    """The inference configuration the LLM stage runs under.

    Attributes:
        task: The task to perform.
        provider: Provider name.
        model: Model name.
        template: Template identifier.
        schema: Schema identifier, or ``None`` when the task validates nothing.
        options: Provider and decoding options.
    """

    task: str
    provider: str
    model: str
    template: str
    schema: str | None
    options: dict[str, Any]


def _required(options: Mapping[str, Any], key: str, *, purpose: str) -> Any:
    """Return ``options[key]``, refusing by name when it is absent.

    Args:
        options: The request's option mapping.
        key: The key the run needs.
        purpose: What needed it, for the message.

    Returns:
        The value.

    Raises:
        WorkflowConfigurationError: When the key is absent.
    """
    if key not in options:
        raise WorkflowConfigurationError(
            key, f"{purpose} requires options[{key!r}]; no default is substituted"
        )
    return options[key]


def policy_flag(policies: Mapping[str, Any], key: str) -> bool:
    """Return a document policy flag, refusing to invent its value.

    Args:
        policies: The document policies in force.
        key: The flag to read, e.g. ``allow_ocr``.

    Returns:
        The flag the caller stated.

    Raises:
        WorkflowConfigurationError: When the policy is absent. A default here would let a
            run OCR a document that never permitted it.
    """
    if key not in policies:
        raise WorkflowConfigurationError(
            key, f"document policies must state {key!r}; no default is substituted"
        )
    return bool(policies[key])


def work_root(request: DocumentRequest) -> Path:
    """Return the directory every artifact of this run is written under.

    Args:
        request: The request being served.

    Returns:
        The working root the caller stated.

    Raises:
        WorkflowConfigurationError: When the request names no output directory.
    """
    return Path(_required(request.options, "output_dir", purpose="the run"))


def state_path(request: DocumentRequest) -> Path:
    """Return where this document's durable context lives.

    Args:
        request: The request being served.

    Returns:
        The state file path, inside the run's working root.
    """
    return work_root(request) / "document_context.json"


def pdf_options(request: DocumentRequest) -> PDFOptions:
    """Return the PDF capabilities this run asks for.

    Args:
        request: The request being served.

    Returns:
        The options, every field supplied by the caller.
    """
    return PDFOptions(**_required(request.options, "pdf", purpose="the PDF stage"))


def image_options(request: DocumentRequest) -> ImageOptions:
    """Return the image transformations this run asks for.

    Args:
        request: The request being served.

    Returns:
        The options, every field supplied by the caller.
    """
    return ImageOptions(
        **_required(request.options, "image", purpose="the IMAGE stage")
    )


def ocr_options(request: DocumentRequest) -> OCROptions:
    """Return the OCR options this run asks for.

    Args:
        request: The request being served.

    Returns:
        The options, every field supplied by the caller.
    """
    return OCROptions(**_required(request.options, "ocr", purpose="the OCR stage"))


def llm_settings(request: DocumentRequest) -> LlmSettings:
    """Return the inference configuration this run asks for.

    Args:
        request: The request being served.

    Returns:
        The settings, every field supplied by the caller.

    Raises:
        WorkflowConfigurationError: When a required setting is absent. A default model or
            a default schema would be a claim about the caller's intent.
    """
    raw: Mapping[str, Any] = _required(request.options, "llm", purpose="the LLM stage")
    return LlmSettings(
        task=str(_required(raw, "task", purpose="the LLM stage")),
        provider=str(_required(raw, "provider", purpose="the LLM stage")),
        model=str(_required(raw, "model", purpose="the LLM stage")),
        template=str(_required(raw, "template", purpose="the LLM stage")),
        schema=None if raw.get("schema") is None else str(raw["schema"]),
        options=dict(raw.get("options", {})),
    )


def processing_key_for(
    stage: StageName,
    *,
    inputs: Sequence[Any],
    options: Mapping[str, Any],
) -> str:
    """Compute one stage's processing key from its identity, its inputs and its options.

    Args:
        stage: The stage the key belongs to.
        inputs: Everything the stage consumes; paths are hashed by content.
        options: The options in force for the stage.

    Returns:
        The key, exactly as the frozen formula computes it.
    """
    processor, version = PROCESSOR_IDENTITIES[stage]
    return identity.processing_key(
        processor, version, [identity.input_hash(*inputs)], options
    )


def document_processing_key(context: DocumentContext, request: DocumentRequest) -> str:
    """Compute the document-level processing key of a run.

    Args:
        context: The document context; its input digest is the input side of the key.
        request: The request being served; its options are the option side.

    Returns:
        The key that names this document's unit of work. The run identity does not
        participate, so a second run over unchanged inputs reproduces it.
    """
    return identity.processing_key(
        WORKFLOW_NAME,
        WORKFLOW_VERSION,
        [context.input_hash],
        dict(request.options),
    )


def execution_policy_payload(policy: ExecutionPolicy) -> dict[str, Any]:
    """Return the JSON-writable payload of an execution policy.

    Args:
        policy: The policy to serialize.

    Returns:
        A mapping whose keys mirror the policy's own fields.
    """
    return {
        "resume": policy.resume,
        "reuse_successful": policy.reuse_successful,
        "retry_failed": policy.retry_failed,
        "skip_stages": list(policy.skip_stages),
        "force_stages": list(policy.force_stages),
        "stop_after_stage": policy.stop_after_stage,
        "start_from_stage": policy.start_from_stage,
        "invalidate_downstream": policy.invalidate_downstream,
        "dry_run": policy.dry_run,
        "parallel_pages": policy.parallel_pages,
    }


def options_hash_for(options: Mapping[str, Any]) -> str:
    """Compute the digest of a stage's normalized options.

    Args:
        options: The options in force.

    Returns:
        The digest, in hexadecimal.
    """
    return identity.options_hash(dict(options))
