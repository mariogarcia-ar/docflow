"""Build the committed PDF fixtures of the PDF processor (``PDF-13``).

Run from the repository root:

```
python tests/fixtures/pdf/build_samples.py
```

The builder uses the standard library only and is deterministic — no timestamp, no random
identifier — so re-running it reproduces the committed bytes and a change to a fixture is
reviewable as a diff. It exists because a fixture has to be explainable: writing a PDF byte
by byte here says exactly what each sample contains, where a file exported from a word
processor would not.

The four samples are the ones `docs/plan/subplan-procesador-pdf.md` §6 names, each named for
what it exercises:

* ``pdf_sample_text.pdf`` — multi-page, text-dominant: the happy path.
* ``pdf_sample_image.pdf`` — one page, no text layer, one embedded image.
* ``pdf_sample_mixed.pdf`` — one page with both a text layer and an embedded image.
* ``pdf_corrupt.pdf`` — the first bytes of a real sample, with no end-of-file marker.

No test reads these bytes looking for engine output: the engine is doubled in the suite
(`README.md` §9.7), so the fixtures exist to be *real input* — hashed, published and never
modified — not to predict what Poppler would say about them.

# TODO: [MVP] these samples stand in for real-world documents: three synthetic pages with
# plain ASCII text and one solid-colour image. A corpus-shaped fixture (rotated pages, a
# text layer beside a scan, a page numbering trap) arrives with the MVP corpus.
"""

from __future__ import annotations

import zlib
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import count
from pathlib import Path

HERE = Path(__file__).resolve().parent

PAGE_WIDTH = 612
PAGE_HEIGHT = 792
PAGE_BOX = f"[0 0 {PAGE_WIDTH} {PAGE_HEIGHT}]"

#: The embedded image is a solid 48x48 RGB square; its exact pixels do not matter, but its
#: being a real image XObject does — the sample has to be a genuine PDF with an image.
IMAGE_SIZE = 48
IMAGE_RGB = (200, 40, 40)

#: How much of a real sample ``pdf_corrupt.pdf`` keeps: enough for a PDF header, not enough
#: to reach the end-of-file marker.
CORRUPT_PREFIX_BYTES = 200


@dataclass(frozen=True)
class Sample:
    """One fixture's content: its pages, their text lines and their embedded image."""

    name: str
    pages: tuple[tuple[str, ...], ...]
    image: bool


SAMPLES: tuple[Sample, ...] = (
    Sample(
        name="pdf_sample_text.pdf",
        pages=(
            ("Page one of the text sample.", "Second line of page one."),
            ("Page two of the text sample.", "Second line of page two."),
            ("Page three of the text sample.", "Second line of page three."),
        ),
        image=False,
    ),
    Sample(
        name="pdf_sample_image.pdf",
        pages=((),),
        image=True,
    ),
    Sample(
        name="pdf_sample_mixed.pdf",
        pages=(("A caption above the embedded image.",),),
        image=True,
    ),
)


def _stream_object(stream: bytes) -> bytes:
    """Return the body of a stream object."""
    return (
        b"<< /Length "
        + str(len(stream)).encode()
        + b" >>\nstream\n"
        + stream
        + b"endstream"
    )


def _image_object() -> bytes:
    """Return the body of a Flate-compressed RGB image XObject."""
    pixels = bytes(IMAGE_RGB) * IMAGE_SIZE * IMAGE_SIZE
    header = (
        b"<< /Type /XObject /Subtype /Image /Width "
        + str(IMAGE_SIZE).encode()
        + b" /Height "
        + str(IMAGE_SIZE).encode()
        + b" /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode"
    )
    return (
        header
        + b" /Length "
        + str(len(zlib.compress(pixels))).encode()
        + b" >>\nstream\n"
        + zlib.compress(pixels)
        + b"endstream"
    )


def _content_stream(lines: Sequence[str], *, image: bool) -> bytes:
    """Return a page's content stream: its text lines and, optionally, the image."""
    commands = ["BT /F1 12 Tf 72 720 Td 16 TL"]
    commands.extend(f"({line}) Tj T*" for line in lines)
    commands.append("ET")
    if image:
        commands.append(f"q {IMAGE_SIZE * 2} 0 0 {IMAGE_SIZE * 2} 72 420 cm /Im1 Do Q")
    return ("\n".join(commands) + "\n").encode("latin-1")


def build_pdf(pages: Sequence[Sequence[str]], *, image: bool) -> bytes:
    """Return a complete, valid PDF with ``pages`` of text and an optional embedded image."""
    numbers = count(1)
    catalog_number = next(numbers)
    pages_number = next(numbers)
    font_number = next(numbers)

    plan: list[tuple[Sequence[str], int, int, int | None]] = []
    for lines in pages:
        page_number = next(numbers)
        content_number = next(numbers)
        image_number = next(numbers) if image else None
        plan.append((lines, page_number, content_number, image_number))

    objects: dict[int, bytes] = {
        catalog_number: (
            b"<< /Type /Catalog /Pages " + str(pages_number).encode() + b" 0 R >>"
        ),
        pages_number: b"<< /Type /Pages /Kids ["
        + b" ".join(
            str(page_number).encode() + b" 0 R" for _, page_number, _, _ in plan
        )
        + b"] /Count "
        + str(len(plan)).encode()
        + b" >>",
        font_number: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }

    for lines, page_number, content_number, image_number in plan:
        image_resources = (
            b" /XObject << /Im1 " + str(image_number).encode() + b" 0 R >>"
            if image_number is not None
            else b""
        )
        objects[page_number] = (
            b"<< /Type /Page /Parent "
            + str(pages_number).encode()
            + b" 0 R /MediaBox "
            + PAGE_BOX.encode()
            + b" /Resources << /Font << /F1 "
            + str(font_number).encode()
            + b" 0 R >>"
            + image_resources
            + b" >> /Contents "
            + str(content_number).encode()
            + b" 0 R >>"
        )
        objects[content_number] = _stream_object(
            _content_stream(lines, image=image_number is not None)
        )
        if image_number is not None:
            objects[image_number] = _image_object()

    document = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets: dict[int, int] = {}
    for number in sorted(objects):
        offsets[number] = len(document)
        document += f"{number} 0 obj\n".encode("latin-1")
        document += objects[number]
        document += b"\nendobj\n"

    start_xref = len(document)
    size = max(objects) + 1
    document += f"xref\n0 {size}\n".encode("latin-1")
    document += b"0000000000 65535 f \n"
    for number in range(1, size):
        document += f"{offsets[number]:010d} 00000 n \n".encode("latin-1")
    document += (
        f"trailer\n<< /Size {size} /Root {catalog_number} 0 R >>\nstartxref\n"
        f"{start_xref}\n%%EOF\n"
    ).encode("latin-1")
    return bytes(document)


def main() -> None:
    """Write every sample, and the truncated one, into this directory."""
    written: list[tuple[str, int]] = []
    for sample in SAMPLES:
        data = build_pdf(sample.pages, image=sample.image)
        (HERE / sample.name).write_bytes(data)
        written.append((sample.name, len(data)))

    mixed = (HERE / "pdf_sample_mixed.pdf").read_bytes()
    corrupt = mixed[:CORRUPT_PREFIX_BYTES]
    (HERE / "pdf_corrupt.pdf").write_bytes(corrupt)
    written.append(("pdf_corrupt.pdf", len(corrupt)))

    for name, size in written:
        print(f"{name}: {size} bytes")


if __name__ == "__main__":
    main()
