"""Entry points of the image processor.

The signatures are frozen by ``docs/plan/README.md`` §4 (the idea's §"Naming"): ``image``
exposes ``process_image()`` and ``process_image_from_page()``. Phase 0 ships the
signatures only; the bodies raise rather than returning a placeholder.

Phase 1 fills these in: ``IMG-12`` implements :func:`process_image`.
"""

from __future__ import annotations

from pathlib import Path

from docflow.image.contracts import ImageOptions, ImageRequest, ImageResult


def process_image(request: ImageRequest) -> ImageResult:
    """Analyse, normalize and prepare one image.

    Args:
        request: The image to process, its requested transformations and its
            correlation context.

    Returns:
        The result. On the happy path ``status`` is ``"success"``; a failure is reported
        as a typed :class:`~docflow.image.contracts.ImageError` inside the result, never
        as an exception across the contract.

    Raises:
        NotImplementedError: Phase 0 ships the signature only.

    # TODO: [MVP] chain validate → load → analyze → normalize → classify →
    # prepare_variants → validate → persist (IMG-12).
    """
    raise NotImplementedError("process_image is implemented in Phase 1 by IMG-12")


def process_image_from_page(
    image_path: Path,
    output_dir: Path,
    options: ImageOptions,
    document_id: str,
    page_number: int,
    workflow_run_id: str,
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

    Returns:
        Whatever :func:`process_image` returns.

    Raises:
        NotImplementedError: Phase 0 ships the signature only.

    # TODO: [MVP] build the request and delegate (IMG-12).
    """
    raise NotImplementedError(
        "process_image_from_page is implemented in Phase 1 by IMG-12"
    )
