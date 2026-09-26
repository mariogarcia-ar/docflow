"""Input-type detection (``ORC-05``).

The first decision of a run is what it was given. It is taken *before* any plan exists, so
it is taken without reading the document: the declared type is honoured when the caller
states one, and otherwise the file's own name decides. An input the orchestrator cannot
recognize is reported ``UNSUPPORTED`` — a stated answer, never a guess at a supported type.

Inspecting the *bytes* is deliberately not done here. A JPEG renamed ``.pdf`` is a corrupt
PDF as far as this component is concerned, and telling the two apart is the processor's
job: it owns the format knowledge and reports the failure as a typed result.

# TODO: [MVP] content sniffing (a magic-number probe) so a mislabelled input is detected
# here rather than failing inside a processor.
"""

from __future__ import annotations

from pathlib import Path

from docflow.workflow.contracts import (
    DetectedInputType,
    DocumentInputType,
)

#: Suffixes this pipeline reads as PDF.
PDF_SUFFIXES = frozenset({".pdf"})

#: Suffixes this pipeline reads as an image. The list is the container set the image
#: processor's engine was written against.
IMAGE_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".gif"}
)


def detect_input_type(
    input_path: Path, declared: DocumentInputType
) -> DetectedInputType:
    """Decide whether the input is a PDF, an image, or neither.

    Args:
        input_path: The input the request named.
        declared: The type the caller stated, or ``"auto"`` to let this function decide.

    Returns:
        ``"PDF"``, ``"IMAGE"`` or ``"UNSUPPORTED"``. A declared type is returned as
        stated — the caller's statement is data, and overriding it would make the request's
        ``input_type`` field meaningless.
    """
    if declared != "auto":
        return declared
    if not input_path.is_file():
        return "UNSUPPORTED"
    suffix = input_path.suffix.lower()
    if suffix in PDF_SUFFIXES:
        return "PDF"
    if suffix in IMAGE_SUFFIXES:
        return "IMAGE"
    return "UNSUPPORTED"
