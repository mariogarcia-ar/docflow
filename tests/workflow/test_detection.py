"""Input-type detection (``ORC-05``)."""

from __future__ import annotations

from pathlib import Path

from docflow.workflow.detection import detect_input_type
from tests.workflow.samples import SAMPLE_IMAGE, SAMPLE_PDF, UNSUPPORTED_FILE


def test_a_pdf_is_detected_as_a_pdf() -> None:
    """A ``.pdf`` input is a PDF."""
    assert detect_input_type(SAMPLE_PDF, "auto") == "PDF"


def test_an_image_is_detected_as_an_image() -> None:
    """A ``.png`` input is an image."""
    assert detect_input_type(SAMPLE_IMAGE, "auto") == "IMAGE"


def test_an_unrecognized_file_is_unsupported() -> None:
    """An input this pipeline does not read is reported as such, never guessed."""
    assert detect_input_type(UNSUPPORTED_FILE, "auto") == "UNSUPPORTED"


def test_a_missing_file_is_unsupported_when_the_type_is_automatic(
    tmp_path: Path,
) -> None:
    """A file that is not there cannot be inspected."""
    assert detect_input_type(tmp_path / "absent.pdf", "auto") == "UNSUPPORTED"


def test_a_declared_type_is_honoured(tmp_path: Path) -> None:
    """The caller's statement is data, and detection does not override it."""
    absent = tmp_path / "absent.pdf"

    assert detect_input_type(absent, "PDF") == "PDF"
    assert detect_input_type(absent, "IMAGE") == "IMAGE"
