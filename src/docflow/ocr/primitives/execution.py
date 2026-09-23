"""Running Docling over one image (``OCR-04``).

The only module that invokes the engine. Its result is Docling's own structure;
:mod:`docflow.ocr.primitives.extraction` is what turns that into the engine-independent
:class:`~docflow.ocr.contracts.OCRDocument`.

Two decisions live here, and both are about keeping the engine's failure modes inside this
processor's vocabulary:

* **The converter is built here, not in the pipeline module.** ``OCR-03`` produces the pipeline
  *options* — what the pipeline does. Pairing them with an input format and constructing a
  converter is a different question — what the pipeline runs over — and this is the task that
  runs it.
* **Every upstream failure is re-raised as a typed seam error.** Docling raises whatever its
  internals raise: ``RuntimeError``, ``pydantic`` validation errors, a bare ``OSError`` from a
  missing file. Letting one cross this boundary would put an unstructured exception into a
  contract that promises a typed :class:`~docflow.ocr.contracts.OCRError`, and the caller would
  have nothing to classify.

Only the image input format is registered. This processor reads images and nothing else — the
prepared image a PDF render or an earlier stage handed it — so a converter that could also open a
PDF would be offering a capability this processor must never use.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

from docflow.ocr.primitives.engine import (
    DOCLING_CONVERTER_MODULE_NAME,
    OCREngineExecutionError,
    docling_module,
)

CONVERSION_OPERATION: str = "convert_image_with_docling"
"""The operation name recorded in a seam failure, so the message says which call failed."""

CONVERTER_BUILD_OPERATION: str = "build_image_converter"
"""The operation name recorded when the converter itself cannot be constructed."""


def _converter_module() -> Any:
    """Import and return the module holding Docling's conversion API.

    Returns:
        The ``docling.document_converter`` module.

    Raises:
        OCREngineNotAvailableError: The engine is not importable.
    """
    docling_module()
    return importlib.import_module(DOCLING_CONVERTER_MODULE_NAME)


def _input_format() -> Any:
    """Return Docling's enum member for the image input format.

    Returns:
        ``InputFormat.IMAGE``.

    Raises:
        OCREngineNotAvailableError: The engine is not importable.
    """
    base_models = importlib.import_module("docling.datamodel.base_models")
    return base_models.InputFormat.IMAGE


def _build_image_converter(pipeline_options: Any) -> Any:
    """Pair configured pipeline options with the image input format and build a converter.

    A separate step from :func:`convert_image_with_docling` because it is the expensive one: a
    converter loads models, and a caller running several images wants to build it once. Making
    that separable is what lets a batch pay for the models once without this module holding
    state.

    Args:
        pipeline_options: Options from
            :func:`docflow.ocr.primitives.pipeline.configure_image_pipeline`.

    Returns:
        A Docling converter registered for images only.

    Raises:
        OCREngineNotAvailableError: The engine is not importable.
        OCREngineExecutionError: The converter cannot be constructed.
    """
    converter_module = _converter_module()
    input_format = _input_format()
    try:
        option = converter_module.ImageFormatOption(pipeline_options=pipeline_options)
        return converter_module.DocumentConverter(
            allowed_formats=[input_format],
            format_options={input_format: option},
        )
    except Exception as failure:
        raise OCREngineExecutionError(
            CONVERTER_BUILD_OPERATION, f"{type(failure).__name__}: {failure}"
        ) from failure


def convert_image_with_docling(image_path: Path, pipeline: Any) -> Any:
    """Run the engine over one prepared image.

    ``pipeline`` arrives as the *options* object ``OCR-03`` produces, and the converter is built
    around it here. The parameter keeps its declared name and position from ``OCR-02``'s
    signature, because that signature is what the rest of the processor is written against.

    Args:
        image_path: The prepared image, already normalized or ``ocr_ready``.
        pipeline: The configured pipeline options.

    Returns:
        Docling's conversion result. Its ``document`` is the structure
        :mod:`docflow.ocr.primitives.extraction` reads; this function does not interpret it.

    Raises:
        OCREngineNotAvailableError: The engine is not importable.
        OCREngineExecutionError: The conversion failed, or returned no document. The upstream
            exception type is kept in the message rather than swallowed, so a caller can still
            tell a missing file from a model failure.

    # TODO: [MVP] the converter is rebuilt per call, so a batch reloads the models each time.
    # `build_image_converter` is separated out precisely so a caller can hoist it; wiring that
    # into the entry point is `OCR-11`'s to decide.
    """
    converter = _build_image_converter(pipeline)
    try:
        result = converter.convert(image_path)
    except Exception as failure:
        raise OCREngineExecutionError(
            CONVERSION_OPERATION, f"{type(failure).__name__}: {failure}"
        ) from failure

    if getattr(result, "document", None) is None:
        # Docling can return a result whose document is absent when a backend refused the input.
        # Returning it would push an ``AttributeError`` into the extraction layer, where it would
        # look like a bug in this processor rather than a refusal by the engine.
        raise OCREngineExecutionError(
            CONVERSION_OPERATION, "the engine returned a result with no document"
        )
    return result


__all__ = [
    "CONVERSION_OPERATION",
    "CONVERTER_BUILD_OPERATION",
    "convert_image_with_docling",
]
