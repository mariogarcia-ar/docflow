"""What each stage consumes, and the key that follows from it.

A processing key is only meaningful if it is computed from *the same* inputs and options in
the same way every time it is computed. That is what this module guarantees: planning, the
pre-flight reuse check and the execution path all ask :func:`stage_key` for a key rather
than each assembling one from its own idea of what feeds a stage.

The LLM stage's input is the *text* the page offers, so the text — not the path it was read
from — is what the key hashes. Two pages whose native text differs produce different keys
even when they were rendered from the same artifact.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any

from docflow.workflow import configuration
from docflow.workflow.contracts import (
    DocumentContext,
    DocumentRequest,
    PageContext,
    StageName,
)
from docflow.workflow.selection import (
    ARTIFACT_NATIVE_TEXT,
    ARTIFACT_NORMALIZED_IMAGE,
    ARTIFACT_OCR_READY,
    ARTIFACT_OCR_TEXT,
    ARTIFACT_PAGE_IMAGE,
    ARTIFACT_VLM_READY,
    RESULT_OCR,
    readable,
)

#: Artifact keys each stage publishes. Used to decide whether a later stage's input will
#: exist once the plan has been followed.
STAGE_OUTPUT_KEYS: dict[StageName, tuple[str, ...]] = {
    "PDF": (ARTIFACT_PAGE_IMAGE, ARTIFACT_NATIVE_TEXT),
    "IMAGE": (
        ARTIFACT_NORMALIZED_IMAGE,
        ARTIFACT_OCR_READY,
        ARTIFACT_VLM_READY,
    ),
    "OCR": (ARTIFACT_OCR_TEXT, "ocr_markdown"),
    "LLM": (),
}


def image_source(context: DocumentContext, page: PageContext) -> Path | None:
    """Return the image the IMAGE stage reads.

    Args:
        context: The document context.
        page: The page being routed.

    Returns:
        The page's rendered image, or the run's own input when the document *is* an image.
    """
    if page.artifacts.get(ARTIFACT_PAGE_IMAGE) is not None:
        return page.artifacts[ARTIFACT_PAGE_IMAGE]
    if context.input_type == "IMAGE":
        return context.input
    return None


def ocr_source(page: PageContext) -> Path | None:
    """Return the image the OCR stage reads.

    Args:
        page: The page being routed.

    Returns:
        The OCR-ready variant when it exists, else the normalized one, else the rendered
        page — the best-prepared representation the run actually produced.
    """
    for key in (ARTIFACT_OCR_READY, ARTIFACT_NORMALIZED_IMAGE, ARTIFACT_PAGE_IMAGE):
        path = page.artifacts.get(key)
        if path is not None:
            return path
    return None


def vlm_source(page: PageContext) -> Path | None:
    """Return the image the LLM stage sends to a vision model, when there is one.

    Args:
        page: The page being routed.

    Returns:
        The VLM-ready variant, or ``None`` when the run produced none.
    """
    path = page.artifacts.get(ARTIFACT_VLM_READY)
    return path if readable(path) else None


def document_text(page: PageContext) -> str | None:
    """Return the text the page offers an LLM, reading it from whatever produced it.

    Args:
        page: The page being routed.

    Returns:
        The native text when there is any, else the OCR text, else ``None`` — never an
        empty string standing in for text nobody produced.
    """
    native = page.artifacts.get(ARTIFACT_NATIVE_TEXT)
    if readable(native) and native is not None:
        return native.read_text(encoding="utf-8")
    result = page.results.get(RESULT_OCR)
    if result is not None and result.text:
        return str(result.text)
    extracted = page.artifacts.get(ARTIFACT_OCR_TEXT)
    if readable(extracted) and extracted is not None:
        return extracted.read_text(encoding="utf-8")
    return None


def stage_inputs(
    context: DocumentContext,
    page: PageContext | None,
    stage: StageName,
) -> tuple[Any, ...]:
    """Return everything one stage consumes, in a stable order.

    Args:
        context: The document context.
        page: The page the stage belongs to, or ``None`` for a document-level stage.
        stage: The stage being described.

    Returns:
        The stage's inputs: paths are hashed by content, text by value.
    """
    if stage == "PDF":
        return (context.input,)
    if page is None:
        return ()
    if stage == "IMAGE":
        return (image_source(context, page),)
    if stage == "OCR":
        return (ocr_source(page),)
    return (document_text(page), vlm_source(page))


def stage_options(request: DocumentRequest, stage: StageName) -> Mapping[str, Any]:
    """Return the options one stage runs under.

    Args:
        request: The request being served.
        stage: The stage being described.

    Returns:
        The stage's option mapping, built from the request and never defaulted.
    """
    if stage == "PDF":
        return asdict(configuration.pdf_options(request))
    if stage == "IMAGE":
        return asdict(configuration.image_options(request))
    if stage == "OCR":
        return asdict(configuration.ocr_options(request))
    return asdict(configuration.llm_settings(request))


def stage_key(
    context: DocumentContext,
    request: DocumentRequest,
    stage: StageName,
    page: PageContext | None = None,
) -> str:
    """Compute the processing key of one stage under the current configuration.

    Args:
        context: The document context.
        request: The request being served.
        stage: The stage being keyed.
        page: The page the stage belongs to, or ``None``.

    Returns:
        The key the frozen formula computes.
    """
    return configuration.processing_key_for(
        stage,
        inputs=stage_inputs(context, page, stage),
        options=stage_options(request, stage),
    )


def stage_options_hash(request: DocumentRequest, stage: StageName) -> str:
    """Compute the digest of one stage's normalized options.

    Args:
        request: The request being served.
        stage: The stage being keyed.

    Returns:
        The digest, in hexadecimal.
    """
    return configuration.options_hash_for(stage_options(request, stage))
