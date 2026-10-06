"""Committed samples and request builders shared by the PDF processor's tests.

The four fixtures are the ones the subplan §6 names; they are committed bytes built by
``tests/fixtures/pdf/build_samples.py``. The document specs below are what the in-memory
Poppler double answers for each of them — scripted, not measured — so a translated result
can be read against a file a human can open.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from docflow.pdf import PDFOptions, PDFRequest
from tests.factories import build_pdf_options, build_pdf_request
from tests.fakes.engines.fake_poppler import FakeImage, FakePage

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "pdf"

#: A three-page, text-dominant document: the happy path.
SAMPLE_TEXT = FIXTURES / "pdf_sample_text.pdf"

#: One page with no text layer and one embedded image.
SAMPLE_IMAGE = FIXTURES / "pdf_sample_image.pdf"

#: One page with a text layer *and* an embedded image.
SAMPLE_MIXED = FIXTURES / "pdf_sample_mixed.pdf"

#: A truncated header: the pre-engine failure path.
SAMPLE_CORRUPT = FIXTURES / "pdf_corrupt.pdf"


def text_document() -> list[FakePage]:
    """Return the engine's answer for :data:`SAMPLE_TEXT`."""
    return [
        FakePage(lines=("Page one of the text sample.", "Second line of page one.")),
        FakePage(lines=("Page two of the text sample.", "Second line of page two.")),
        FakePage(
            lines=("Page three of the text sample.", "Second line of page three.")
        ),
    ]


def image_document() -> list[FakePage]:
    """Return the engine's answer for :data:`SAMPLE_IMAGE`."""
    return [FakePage(lines=(), images=(FakeImage(),))]


def mixed_document() -> list[FakePage]:
    """Return the engine's answer for :data:`SAMPLE_MIXED`."""
    return [
        FakePage(
            lines=("A caption above the embedded image.",),
            images=(FakeImage(width=120, height=90, encoding="jpeg"),),
        )
    ]


def build_options(**overrides: Any) -> PDFOptions:
    """Return the shared fully specified capabilities, with any subset overridden."""
    return replace(build_pdf_options(), **overrides)


def build_request(pdf_path: Path, output_dir: Path, **overrides: Any) -> PDFRequest:
    """Return a request for ``pdf_path``, with no capability left implicit.

    It starts from the shared factory, so the correlation identity and the option set stay
    defined in one place.
    """
    return replace(
        build_pdf_request(output_dir),
        pdf_path=pdf_path,
        output_dir=output_dir,
        options=build_options(**overrides),
    )
