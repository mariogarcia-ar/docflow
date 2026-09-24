"""The shape check of ``tests/fakes/engines/convention.py``, proved on a synthetic seam.

The real seams do not exist yet (``PDF-02``, ``IMG-02``, ``OCR-02``, ``LLM-02``), so the
mechanism is exercised on a seam written into ``tmp_path``. When the doubles land, each of
``PDF-14`` / ``IMG-15`` / ``OCR-14`` / ``LLM-03`` calls the same helper against its own seam.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from tests.fakes.engines.convention import (
    double_attributes_provided_by,
    engine_attributes_used_by,
    missing_from_double,
)

SEAM_SOURCE = '''
"""A seam that reaches two engine calls."""

import cv2


def load(path):
    """Read an image."""
    return cv2.imread(path)


def save(image, path):
    """Write an image."""
    return cv2.imwrite(path, image)
'''


class CompleteDouble:
    """A double that models both calls the seam makes."""

    @staticmethod
    def imread() -> None:
        """Pretend to read an image."""

    @staticmethod
    def imwrite() -> bool:
        """Pretend to write an image."""
        return True


class PartialDouble:
    """A double that models ``imread`` and something the seam never calls."""

    @staticmethod
    def imread() -> None:
        """Pretend to read an image."""

    @staticmethod
    def imreadmulti() -> None:
        """Pretend to read a multi-page image."""


def write_seam(tmp_path: Path, source: str) -> Path:
    """Write ``source`` as a seam module and return its path."""
    seam = tmp_path / "seam.py"
    seam.write_text(textwrap.dedent(source), encoding="utf-8")
    return seam


def test_the_check_lists_every_engine_attribute_the_seam_reaches(
    tmp_path: Path,
) -> None:
    """What the seam may call is what the double must model."""
    seam = write_seam(tmp_path, SEAM_SOURCE)

    assert engine_attributes_used_by(seam, "cv2") == {"imread", "imwrite"}


def test_the_check_ignores_an_engine_that_is_not_the_one_asked_for(
    tmp_path: Path,
) -> None:
    """The scan is scoped to one engine name, so a second engine cannot inflate the set."""
    seam = write_seam(tmp_path, SEAM_SOURCE)

    assert engine_attributes_used_by(seam, "PIL") == set()


def test_the_check_reports_an_attribute_the_double_lacks(tmp_path: Path) -> None:
    """A seam that grows a call the double does not model is the drift this guards."""
    seam = write_seam(tmp_path, SEAM_SOURCE)

    assert missing_from_double(seam, "cv2", PartialDouble()) == {"imwrite"}


def test_the_check_is_silent_when_the_double_models_every_call(tmp_path: Path) -> None:
    """No gap, no noise: a complete double must not be reported as drifted."""
    seam = write_seam(tmp_path, SEAM_SOURCE)

    assert missing_from_double(seam, "cv2", CompleteDouble()) == set()
    assert "imread" in double_attributes_provided_by(CompleteDouble())
