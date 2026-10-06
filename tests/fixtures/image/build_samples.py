"""Build the committed image fixtures of the image processor (``IMG-13``).

Run from the repository root:

```
python tests/fixtures/image/build_samples.py
```

The builder uses the standard library only and is deterministic — no timestamp, no random
identifier — so re-running it reproduces the committed bytes and a change to a fixture is
reviewable as a diff. It exists because a fixture has to be explainable: painting a PNG pixel
by pixel here says exactly what each sample contains, where an image exported from a drawing
tool would not.

The four samples are the ones `docs/plan/subplan-procesador-image.md` §6 names, each named for
what it exercises:

* ``color_layout.png`` — a colour page with a colour accent: the VLM variant keeps the colour
  the OCR variant destroys.
* ``skewed_text.png`` — text-like bars drawn a few degrees off the horizontal: the deskew and
  OCR paths.
* ``embedded_logo.png`` — a small colour mark with no text: a visual-only input.
* ``corrupt.png`` — the first bytes of ``color_layout.png``, truncated before the end-of-file
  chunk, so a decoder must refuse it.

No test reads these bytes looking for engine output: the engine is doubled in the suite
(`README.md` §9.7), so the fixtures exist to be *real input* — decoded, hashed, published and
never modified — not to predict what OpenCV would report about them. The pixels the double
decodes are its own synthetic ones; what comes from these files is their real container
geometry and their real bytes.

# TODO: [MVP] these samples stand in for real-world documents: flat colour, hard edges and no
# compression artifacts. A corpus-shaped fixture (a phone photo, a grainy scan, a rotated page
# with noise) arrives with the MVP corpus.
"""

from __future__ import annotations

import struct
import zlib
from collections.abc import Sequence
from pathlib import Path

HERE = Path(__file__).resolve().parent

RGB = tuple[int, int, int]

#: A page-like background, a dark ink and one saturated accent.
BACKGROUND: RGB = (246, 245, 240)
INK: RGB = (34, 34, 40)
ACCENT: RGB = (28, 94, 201)

#: How much of ``color_layout.png`` the truncated sample keeps: enough for a decoder to read
#: the header and start, not enough to find the end-of-file chunk.
CORRUPT_PREFIX_BYTES = 200


def _encode_png(width: int, height: int, rows: Sequence[Sequence[RGB]]) -> bytes:
    """Return a real, decodable 8-bit RGB PNG.

    Every scanline uses filter type 0 (None), so the encoder is the whole of the format's
    contract and the file stays byte-for-byte reproducible.
    """

    def chunk(tag: bytes, payload: bytes) -> bytes:
        crc = zlib.crc32(tag + payload)
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", crc & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(
        b"\x00" + bytes(channel for pixel in row for channel in pixel) for row in rows
    )
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def _blank(width: int, height: int, colour: RGB) -> list[list[RGB]]:
    """Return a ``width`` x ``height`` canvas filled with one colour."""
    return [[colour] * width for _ in range(height)]


def _bar(
    canvas: list[list[RGB]],
    colour: RGB,
    *,
    left: int,
    top: int,
    width: int,
    height: int,
    slope: float = 0.0,
) -> None:
    """Fill one rectangle, optionally displacing each column to suggest a skewed line."""
    canvas_height = len(canvas)
    canvas_width = len(canvas[0])
    for y in range(top, top + height):
        for x in range(left, left + width):
            shifted = round(y + (x - left) * slope)
            if 0 <= shifted < canvas_height and 0 <= x < canvas_width:
                canvas[shifted][x] = colour


#: The samples are deliberately small. The pixels the suite decodes are the double's own
#: synthetic ones (`tests/fakes/engines/fake_opencv.py`), and those are produced per pixel in
#: Python, so the sample size sets the suite's runtime rather than the fidelity of anything.
PAGE = (160, 120)
LOGO = (96, 96)


def color_layout() -> tuple[int, int, list[list[RGB]]]:
    """Return a colour page: dark text-like bars and one saturated accent block."""
    width, height = PAGE
    canvas = _blank(width, height, BACKGROUND)
    for index in range(5):
        _bar(canvas, INK, left=16, top=14 + index * 20, width=100, height=6)
    _bar(canvas, ACCENT, left=126, top=18, width=22, height=84)
    return width, height, canvas


def skewed_text() -> tuple[int, int, list[list[RGB]]]:
    """Return a page whose text-like bars lean a few degrees off the horizontal."""
    width, height = PAGE
    canvas = _blank(width, height, BACKGROUND)
    for index in range(5):
        _bar(
            canvas,
            INK,
            left=16,
            top=16 + index * 20,
            width=126,
            height=6,
            slope=0.06,
        )
    return width, height, canvas


def embedded_logo() -> tuple[int, int, list[list[RGB]]]:
    """Return a small colour mark with no text in it."""
    width, height = LOGO
    canvas = _blank(width, height, BACKGROUND)
    _bar(canvas, ACCENT, left=16, top=16, width=64, height=64)
    _bar(canvas, INK, left=32, top=32, width=32, height=32)
    return width, height, canvas


def main() -> None:
    """Write every sample, and the truncated one, into this directory."""
    written: list[tuple[str, int]] = []
    for name, painter in (
        ("color_layout.png", color_layout),
        ("skewed_text.png", skewed_text),
        ("embedded_logo.png", embedded_logo),
    ):
        width, height, canvas = painter()
        data = _encode_png(width, height, canvas)
        (HERE / name).write_bytes(data)
        written.append((name, len(data)))

    layout = (HERE / "color_layout.png").read_bytes()
    corrupt = layout[:CORRUPT_PREFIX_BYTES]
    (HERE / "corrupt.png").write_bytes(corrupt)
    written.append(("corrupt.png", len(corrupt)))

    for name, size in written:
        print(f"{name}: {size} bytes")


if __name__ == "__main__":
    main()
