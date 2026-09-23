"""Entry points of the image processor.

The signatures are frozen by ``docs/plan/README.md`` §4 (the idea's §"Naming"): ``image``
exposes ``process_image()`` and ``process_image_from_page()``, and both keep those names.

``IMG-12`` fills them in. The composition lives in
:mod:`docflow.image.primitives.composition`; these two functions are the published surface
over it, and they add nothing of their own:

* :func:`process_image` is what the orchestrator calls.
* :func:`process_image_from_page` is the page-level convenience the plan names: it builds the
  request and delegates.

The **engine is a required keyword argument**, and that is a deliberate departure from the
Phase 0 stub, which took the request alone. Out of bounds for this task reads "no default
engine or threshold substitution", and ``EngineChoice`` has no ``AUTO`` member for the same
reason: a default here would be this processor answering "which engine?" on the caller's
behalf, which is the silent substitution the seam exists to prevent. Making it required means
no call site can be written without naming one.
"""

from __future__ import annotations

from pathlib import Path

from docflow.image.contracts import (
    ImageContext,
    ImageOptions,
    ImageRequest,
    ImageResult,
)
from docflow.image.primitives.composition import process_image_result
from docflow.image.primitives.engine import EngineChoice


def process_image(
    request: ImageRequest,
    *,
    engine: EngineChoice,
    processing_key: str | None = None,
) -> ImageResult:
    """Analyse, normalize and prepare one image.

    Args:
        request: The image to process, its requested transformations and its correlation
            context.
        engine: The engine to decode, measure and transform with, named explicitly by the
            caller. Required: see the module docstring for why it has no default.
        processing_key: The reuse key, when the orchestrator has computed one. ``None``
            records that it has not been computed, which is not the same as the key being
            absent.

    Returns:
        The result. On the happy path ``status`` is ``"success"``; a failure is reported as a
        typed :class:`~docflow.image.contracts.ImageError` inside the result, never as an
        exception across the contract.
    """
    return process_image_result(request, engine, processing_key=processing_key)


def process_image_from_page(
    image_path: Path,
    output_dir: Path,
    options: ImageOptions,
    document_id: str,
    page_number: int,
    workflow_run_id: str,
    *,
    engine: EngineChoice,
    processing_key: str | None = None,
) -> ImageResult:
    """Process an image that a PDF page produced.

    A thin wrapper: it builds an :class:`~docflow.image.contracts.ImageRequest`, carrying
    the page identity through, and delegates to :func:`process_image`.

    Args:
        image_path: The image to process, named explicitly.
        output_dir: Root of the ``image/`` artifact namespace.
        options: Requested transformations and variants.
        document_id: Identity of the document the page belongs to.
        page_number: Logical page the image belongs to, 1-based.
        workflow_run_id: Identity of the run that issued the request.
        engine: The engine to process with. Required, for the reason the module docstring
            gives.
        processing_key: The reuse key, when the orchestrator has computed one.

    Returns:
        Whatever :func:`process_image` returns.
    """
    return process_image(
        ImageRequest(
            image_path=image_path,
            output_dir=output_dir,
            options=options,
            context=ImageContext(
                document_id=document_id,
                page_number=page_number,
                workflow_run_id=workflow_run_id,
            ),
        ),
        engine=engine,
        processing_key=processing_key,
    )


__all__ = ["process_image", "process_image_from_page"]
