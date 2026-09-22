"""Rebuild the committed image fixtures under ``tests/fixtures/image/``.

The fixtures are committed rather than generated inside ``conftest`` so that a failing test points
at bytes that live in the repository - the convention the PDF fixtures already follow. This script
is how those bytes are produced, and it is idempotent: running it twice leaves the tree identical,
so ``--check`` is a cheap way to confirm the committed files still match their source.

It deliberately does **not** import ``docflow.image.primitives``. A fixture generator built on the
code under test could not tell "the fixture is wrong" from "the reader is wrong", and the whole
point of these files is to be an independent statement of what the reader must handle.

Run from the repository root::

    python scripts/tools/image_fixtures.py
    python scripts/tools/image_fixtures.py --check
"""

from __future__ import annotations

import argparse
import struct
import zlib
from pathlib import Path

import numpy as np

FIXTURES = Path("tests/fixtures/image")

COLOR_LAYOUT_SIZE = (240, 160)
"""Width and height of ``color_layout.png``: small enough to commit, large enough to read."""

SKEWED_TEXT_SIZE = (400, 300)
"""Width and height of ``skewed_text.png``."""

SKEW_ANGLE_DEGREES = 4.0
"""Rotation applied to ``skewed_text.png``, inside the range a deskew step is meant to fix."""

EMBEDDED_LOGO_SIZE = (96, 64)
"""Width and height of ``embedded_logo.png``."""

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def encode_png(pixels: np.ndarray) -> bytes:
    """Encode an RGB array as PNG bytes, using only the standard library.

    Hand-rolled rather than delegated to Pillow so the fixture bytes cannot change with whichever
    image library happens to be installed: a fixture that shifted under a dependency upgrade would
    turn an unrelated install into a test failure.

    Args:
        pixels: ``(height, width, 3)`` uint8 array.

    Returns:
        The complete PNG file as bytes.
    """
    height, width, _ = pixels.shape
    scanlines = b"".join(b"\x00" + pixels[row].tobytes() for row in range(height))

    def chunk(kind: bytes, payload: bytes) -> bytes:
        body = kind + payload
        return (
            struct.pack(">I", len(payload))
            + body
            + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        PNG_SIGNATURE
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(scanlines, 9))
        + chunk(b"IEND", b"")
    )


def build_color_layout() -> np.ndarray:
    """Build a document whose colour carries information.

    That is the fixture's whole purpose: the "text" is dark red on a light field and three solid
    bars are pure red, green and blue. A pipeline that dropped colour would leave the bars
    indistinguishable and the red text invisible against white, so this is the file that proves a
    VLM variant kept colour rather than measuring a grayscale copy.

    Returns:
        ``(height, width, 3)`` uint8 array.
    """
    width, height = COLOR_LAYOUT_SIZE
    canvas = np.full((height, width, 3), 255, dtype=np.uint8)

    bar_width = width // 3
    canvas[20:60, 0:bar_width] = (0, 160, 0)
    canvas[20:60, bar_width : 2 * bar_width] = (200, 0, 0)
    canvas[20:60, 2 * bar_width : width] = (0, 0, 200)

    for row_index in range(6):
        top = 80 + row_index * 12
        for segment in range(5):
            left = 16 + segment * 40
            canvas[top : top + 5, left : left + 28] = (140, 0, 0)

    return canvas


def build_skewed_text() -> np.ndarray:
    """Build a text-like page rotated by :data:`SKEW_ANGLE_DEGREES`.

    The rotation is applied by hand with nearest-neighbour sampling, again to keep the fixture
    independent of the libraries the deskew code will use.

    Returns:
        ``(height, width, 3)`` uint8 array.
    """
    width, height = SKEWED_TEXT_SIZE
    upright = np.full((height, width, 3), 255, dtype=np.uint8)
    for row_index in range(12):
        top = 40 + row_index * 18
        left = 40 + (row_index % 3) * 10
        upright[top : top + 6, left : left + 260] = (30, 30, 30)

    radians = np.deg2rad(SKEW_ANGLE_DEGREES)
    cosine, sine = np.cos(radians), np.sin(radians)
    centre_x, centre_y = width / 2, height / 2

    rows, columns = np.mgrid[0:height, 0:width]
    x = columns - centre_x
    y = rows - centre_y
    source_x = np.rint(cosine * x + sine * y + centre_x).astype(int)
    source_y = np.rint(-sine * x + cosine * y + centre_y).astype(int)
    inside = (
        (source_x >= 0) & (source_x < width) & (source_y >= 0) & (source_y < height)
    )

    rotated = np.full_like(upright, 255)
    rotated[inside] = upright[source_y[inside], source_x[inside]]
    return rotated


def build_embedded_logo() -> np.ndarray:
    """Build a small logo-like mark on a white field.

    Stands in for a logo lifted out of a PDF: small, high contrast, and nothing like a full page -
    which is exactly why the classification stage has to be able to tell it apart from one.

    Returns:
        ``(height, width, 3)`` uint8 array.
    """
    width, height = EMBEDDED_LOGO_SIZE
    canvas = np.full((height, width, 3), 255, dtype=np.uint8)
    canvas[12:52, 12:52] = (0, 90, 170)
    canvas[26:38, 26:38] = (255, 255, 255)
    return canvas


def build_corrupt_png() -> bytes:
    """Build a PNG that keeps its signature and header but has a damaged data stream.

    Keeping the signature and a valid ``IHDR`` is what makes the fixture useful. A file that failed
    the magic-number check would exercise the "not an image at all" path, while this one has to be
    *recognised as a PNG and then fail to decode* - the distinction the contract draws between
    ``UNSUPPORTED_FORMAT`` and ``DECODE_ERROR``. The trailing ``IEND`` is preserved so the file
    stays structurally plausible rather than obviously truncated.

    Returns:
        The damaged file's bytes.
    """
    valid = encode_png(build_embedded_logo())

    marker = b"IDAT"
    index = valid.index(marker)
    payload_start = index + len(marker)
    payload_length = struct.unpack(">I", valid[index - 4 : index])[0]
    damaged = bytes(
        byte ^ 0xA5 for byte in valid[payload_start : payload_start + payload_length]
    )
    return valid[:payload_start] + damaged + valid[payload_start + payload_length :]


def build_fixtures() -> dict[str, bytes]:
    """Return every fixture this generator owns, keyed by file name.

    Returns:
        File name to file bytes.
    """
    return {
        "color_layout.png": encode_png(build_color_layout()),
        "skewed_text.png": encode_png(build_skewed_text()),
        "embedded_logo.png": encode_png(build_embedded_logo()),
        "corrupt.png": build_corrupt_png(),
    }


def main(argv: list[str] | None = None) -> int:
    """Write the fixtures, or report drift against them.

    Args:
        argv: Command-line arguments; ``--check`` reports without writing.

    Returns:
        ``0`` on success, ``1`` when ``--check`` found a fixture that differs.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="report whether the committed fixtures match this generator, without writing",
    )
    arguments = parser.parse_args(argv)

    drifted = [
        name
        for name, payload in build_fixtures().items()
        if not (FIXTURES / name).is_file() or (FIXTURES / name).read_bytes() != payload
    ]

    if arguments.check:
        if drifted:
            print("fixtures differ from the generator: " + ", ".join(drifted))
            return 1
        print("all image fixtures match the generator")
        return 0

    FIXTURES.mkdir(parents=True, exist_ok=True)
    for name, payload in build_fixtures().items():
        (FIXTURES / name).write_bytes(payload)
        print(f"wrote {FIXTURES / name} ({len(payload)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
