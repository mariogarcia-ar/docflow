"""Build the committed OCR fixtures, deterministically, with the standard library alone.

Two images, each named for the case it provokes:

* ``ocr_prepared_text_and_table.png`` — a prepared page with a heading, one paragraph and a 2x2
  table. It provokes the happy path: structure extraction, ordering and the table export.
* ``ocr_blank.png`` — a page with nothing on it. It provokes the ``EMPTY`` path, which is *data
  about the input* rather than a failure of the run.

Nothing here is random and nothing depends on a clock: re-running the script reproduces the same
bytes, so a fixture can be regenerated and reviewed as a diff. The script uses no third-party
library on purpose — a fixture builder that needs an engine installed would make the suite
dependent on the very engine it must run without.

The pixels are *not* what the processor is tested against: the Docling double answers with its own
content and reads only the file's frame (``tests/fakes/engines/fake_docling.py``). What these files
provide is what a fixture is for here — real PNG bytes at the seam, an immutable input the suite
hashes, and a frame the double can read.

The images are 240x120 so the committed bytes stay small; the resolution buys nothing, because
nothing in the suite decodes them.
"""

from __future__ import annotations

import struct
import zlib
from collections.abc import Sequence
from pathlib import Path

#: The frame every OCR fixture uses. The Docling double reads it from the file's header.
WIDTH = 240
HEIGHT = 120

#: Paper and ink, as 8-bit grey levels.
PAPER = 245
INK = 30

#: A mid grey, for the table's grid lines — structure the eye can see in a diff.
RULE = 150

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _chunk(tag: bytes, payload: bytes) -> bytes:
    """Return one PNG chunk: length, tag, payload and CRC."""
    return (
        struct.pack(">I", len(payload))
        + tag
        + payload
        + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
    )


def _png(rows: Sequence[Sequence[int]]) -> bytes:
    """Encode a grid of 8-bit grey levels as a real, decodable PNG."""
    height = len(rows)
    width = len(rows[0])
    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    raw = bytearray()
    for row in rows:
        raw.append(0)
        raw.extend(row)
    return (
        _PNG_SIGNATURE
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + _chunk(b"IEND", b"")
    )


def _blank_rows() -> list[list[int]]:
    """Return an empty page."""
    return [[PAPER] * WIDTH for _ in range(HEIGHT)]


def _fill(rows: list[list[int]], box: tuple[int, int, int, int], level: int) -> None:
    """Paint one rectangle, clipped to the frame."""
    left, top, right, bottom = box
    for y in range(max(top, 0), min(bottom, HEIGHT)):
        for x in range(max(left, 0), min(right, WIDTH)):
            rows[y][x] = level


def _prepared_rows() -> list[list[int]]:
    """Return a page with a heading, one paragraph written as two lines, and a 2x2 table.

    The layout mirrors the content the Docling double reports, so a reader comparing the fixture
    with the extraction sees the same page.
    """
    rows = _blank_rows()
    _fill(rows, (12, 12, 190, 22), INK)  # the heading
    _fill(rows, (12, 36, 228, 44), INK)  # the paragraph
    _fill(rows, (12, 48, 210, 56), INK)
    for y in (68, 84, 100):  # the table's rules
        _fill(rows, (12, y, 150, y + 2), RULE)
    for x in (12, 78, 150):  # the table's columns
        _fill(rows, (x, 68, x + 2, 102), RULE)
    return rows


def main() -> None:
    """Write both fixtures beside this script."""
    directory = Path(__file__).resolve().parent
    (directory / "ocr_prepared_text_and_table.png").write_bytes(_png(_prepared_rows()))
    (directory / "ocr_blank.png").write_bytes(_png(_blank_rows()))


if __name__ == "__main__":
    main()
