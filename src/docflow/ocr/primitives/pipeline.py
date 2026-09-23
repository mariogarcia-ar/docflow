"""Docling pipeline construction and configuration (``OCR-02`` surface).

Everything here is about *building* a converter, never running one: which pipeline a page gets,
and which of its stages are switched on. The decisions are read from
:class:`~docflow.ocr.contracts.NormalizedOCROptions` rather than from a raw request, so a stage
can never be enabled by an option spelling this module did not expect.

Every body raises :class:`NotImplementedError`. A stub returning a plausible default would let a
caller mistake "not implemented yet" for a real configuration, which is the silent stand-in the
project forbids.

``OCR-03`` implements all of these.
"""

from __future__ import annotations

from docflow.ocr.contracts import NormalizedOCROptions


def load_docling_pipeline() -> object:
    """Build the Docling conversion pipeline this processor drives.

    Returns:
        The pipeline object, not a converter: a converter is a pipeline plus options, and
        separating the two keeps the options a value the caller can inspect.

    Raises:
        NotImplementedError: ``OCR-03`` implements this.

    # TODO: [MVP] implement (OCR-03).
    """
    raise NotImplementedError("load_docling_pipeline is implemented by OCR-03")


def configure_image_pipeline(options: NormalizedOCROptions) -> object:
    """Apply the requested stages to an image pipeline.

    Args:
        options: The normalized options.

    Returns:
        The configured pipeline.

    Raises:
        NotImplementedError: ``OCR-03`` implements this.

    # TODO: [MVP] implement (OCR-03).
    """
    raise NotImplementedError("configure_image_pipeline is implemented by OCR-03")


def normalize_docling_options(options: NormalizedOCROptions) -> dict[str, object]:
    """Translate the processor's options into Docling's own vocabulary.

    Args:
        options: The normalized options.

    Returns:
        Docling's option mapping, with canonical key order.

    Raises:
        NotImplementedError: ``OCR-03`` implements this.

    # TODO: [MVP] implement (OCR-03).
    """
    raise NotImplementedError("normalize_docling_options is implemented by OCR-03")


def should_enable_ocr(options: NormalizedOCROptions) -> bool:
    """Report whether OCR should run for these options.

    Args:
        options: The normalized options.

    Returns:
        ``True`` when OCR was requested.

    Raises:
        NotImplementedError: ``OCR-03`` implements this.

    # TODO: [MVP] implement (OCR-03).
    """
    raise NotImplementedError("should_enable_ocr is implemented by OCR-03")


def should_enable_layout(options: NormalizedOCROptions) -> bool:
    """Report whether layout analysis should run.

    Args:
        options: The normalized options.

    Returns:
        ``True`` when layout was requested.

    Raises:
        NotImplementedError: ``OCR-03`` implements this.

    # TODO: [MVP] implement (OCR-03).
    """
    raise NotImplementedError("should_enable_layout is implemented by OCR-03")


def should_enable_tables(options: NormalizedOCROptions) -> bool:
    """Report whether table detection should run.

    Args:
        options: The normalized options.

    Returns:
        ``True`` when tables were requested.

    Raises:
        NotImplementedError: ``OCR-03`` implements this.

    # TODO: [MVP] implement (OCR-03).
    """
    raise NotImplementedError("should_enable_tables is implemented by OCR-03")


def should_enable_reading_order(options: NormalizedOCROptions) -> bool:
    """Report whether reading order should be resolved.

    Args:
        options: The normalized options.

    Returns:
        ``True`` when reading order was requested.

    Raises:
        NotImplementedError: ``OCR-03`` implements this.

    # TODO: [MVP] implement (OCR-03).
    """
    raise NotImplementedError("should_enable_reading_order is implemented by OCR-03")


__all__ = [
    "configure_image_pipeline",
    "load_docling_pipeline",
    "normalize_docling_options",
    "should_enable_layout",
    "should_enable_ocr",
    "should_enable_reading_order",
    "should_enable_tables",
]
