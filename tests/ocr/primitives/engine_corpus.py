"""The committed OCR fixture, converted once and shared by the primitives' suites.

``test_extraction`` and ``test_layout`` both need the same three things: the request asking for
everything this processor can extract, the configured pipeline it is handed to, and the fixture
converted through the real engine. Each module building its own copy is what pylint's
``duplicate-code`` flagged — and the cost is not only the duplicated lines: it paid for two
conversions of one image, and it let the two suites drift into asking the engine for different
options while both believed they described "everything".

A module rather than a pytest fixture, for the reason the extraction suite records: a fixture's
parameter name shadows the function in every test signature, which the linter flags, and these are
values a test asks for rather than state pytest sets up on its behalf.
"""

from __future__ import annotations

from dataclasses import replace
from functools import lru_cache
from pathlib import Path

from docflow.ocr.contracts import OCRDocument, OCROptions
from docflow.ocr.primitives import execution, extraction, pipeline
from tests.factories import build_ocr_options

REPO_ROOT = Path(__file__).resolve().parents[3]

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "ocr" / "ocr_prepared_text_and_table.png"
"""The fixture the task criteria name.

Built by ``scripts/tools/ocr_fixture.py`` from a real scan in the corpus, prepared with the *image*
processor — "prepared" is what that pipeline produces, and the documented flow is
`PDF` -> `image` -> `ocr`. ``OCR-12`` owns the fixture set.
"""


def requested_options() -> OCROptions:
    """Return a request asking for everything this processor can extract.

    The shape comes from :func:`tests.factories.build_ocr_options` so the two OCR suites and the
    contract round-trip cannot drift into describing "everything" differently. Only the language
    differs, and deliberately: the fixture is a Spanish invoice, and the language tag is the one
    option whose *value* the engine reads rather than a flag it either honours or does not.

    Returns:
        The raw options.
    """
    return replace(build_ocr_options(), language="es")


def configured_pipeline() -> object:
    """Return a configured Docling pipeline.

    Returns:
        The pipeline options, ready for :func:`execution.convert_image_with_docling`.
    """
    return pipeline.configure_image_pipeline(
        pipeline.normalize_docling_options(requested_options())
    )


def convert() -> OCRDocument:
    """Convert the fixture, uncached, and return the engine-independent document.

    Uncached because a test that asserts two *runs* agree has to be able to run the engine twice;
    handing it the cached document twice would make it a statement about object identity, which is
    what the determinism criterion is not. Everything else should use :func:`extracted_document`.

    Returns:
        The extracted document, in the engine's own pixel frame.
    """
    result = execution.convert_image_with_docling(FIXTURE, configured_pipeline())
    return extraction.build_ocr_document(result)


@lru_cache(maxsize=1)
def extracted_document() -> OCRDocument:
    """Convert the fixture once and return the engine-independent document.

    Cached because a conversion loads the model stack and takes seconds; two suites each paying it
    would make the pair slow enough that the next person deletes one. Cached for the *process*, so
    both modules share one conversion.

    Returns:
        The extracted document, in the engine's own pixel frame.
    """
    return convert()


__all__ = [
    "FIXTURE",
    "REPO_ROOT",
    "configured_pipeline",
    "convert",
    "extracted_document",
    "requested_options",
]
