"""Committed samples and request builders shared by the image processor's tests.

The four fixtures are the ones the subplan §6 names; they are committed bytes built by
``tests/fixtures/image/build_samples.py``. Unlike the PDF samples these are not scripted
against the double: the double decodes its own synthetic pixels, so what comes from these files
is their real container geometry and their real bytes — input that is hashed, published and
never modified.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from docflow.image import ImageOptions, ImageRequest
from tests.factories import build_image_options, build_image_request

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "image"

#: A colour page with a saturated accent: the happy path, and the case where the VLM variant
#: must keep the colour the OCR variant destroys.
COLOR_LAYOUT = FIXTURES / "color_layout.png"

#: A page whose text-like bars lean a few degrees off the horizontal.
SKEWED_TEXT = FIXTURES / "skewed_text.png"

#: A small colour mark with no text in it.
EMBEDDED_LOGO = FIXTURES / "embedded_logo.png"

#: A truncated container: the decode-failure path.
CORRUPT = FIXTURES / "corrupt.png"


def build_options(**overrides: Any) -> ImageOptions:
    """Return the shared fully specified options, with any subset overridden."""
    return replace(build_image_options(), **overrides)


def build_request(image_path: Path, output_dir: Path, **overrides: Any) -> ImageRequest:
    """Return a request for ``image_path``, with no option left implicit.

    It starts from the shared factory, so the correlation identity and the option set stay
    defined in one place.
    """
    return replace(
        build_image_request(output_dir),
        image_path=image_path,
        output_dir=output_dir,
        options=build_options(**overrides),
    )
