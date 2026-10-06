"""Committed samples and request builders shared by the OCR processor's tests.

The two fixtures are the ones the subplan §6 names; they are committed bytes built by
``tests/fixtures/ocr/build_samples.py``. The Docling double answers with its own content and reads
only the file's frame, so what comes from these files is real container geometry and real bytes —
input that is hashed, handed to the seam and never modified.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Final

from docflow.ocr import BlockResult, OCRBlockType, OCROptions, OCRRequest
from tests.factories import build_ocr_options, build_ocr_request

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "ocr"

#: A prepared page with a heading, a paragraph and a 2x2 table: the happy path.
PREPARED = FIXTURES / "ocr_prepared_text_and_table.png"

#: A page with nothing on it: the ``EMPTY`` path, which is data rather than a failure.
BLANK = FIXTURES / "ocr_blank.png"

#: The shared options as ``metadata.json`` records them, spelled once.
#:
#: Two tests need the same six values — one asserting the artifact echoes them, one removing a key
#: to prove a required option is never defaulted — and a second copy would let the two drift apart.
OPTION_VALUES: Final[dict[str, Any]] = {
    "ocr": True,
    "layout": True,
    "tables": True,
    "reading_order": True,
    "language": "en",
    "engine_options": {"do_table_structure": True},
}


def build_block(
    block_id: str,
    type_: OCRBlockType,
    text: str,
    *,
    bbox: tuple[float, float, float, float] | None = None,
    level: int | None = None,
) -> BlockResult:
    """Return one block, so a case spells out only what it is about.

    Args:
        block_id: The block's identifier.
        type_: The block's structural role.
        text: Its text.
        bbox: Its normalized box, or ``None`` when the case claims no geometry.
        level: Its heading depth, or ``None``.
    """
    return BlockResult(block_id=block_id, type=type_, text=text, bbox=bbox, level=level)


def build_options(**overrides: Any) -> OCROptions:
    """Return the shared fully specified options, with any subset overridden."""
    return replace(build_ocr_options(), **overrides)


def build_request(image_path: Path, output_dir: Path, **overrides: Any) -> OCRRequest:
    """Return a request for ``image_path``, with no option left implicit.

    It starts from the shared factory, so the correlation identity and the option set stay defined
    in one place.
    """
    return replace(
        build_ocr_request(output_dir),
        image_path=image_path,
        output_dir=output_dir,
        options=build_options(**overrides),
    )
