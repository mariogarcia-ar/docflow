"""Generate the silent-failure matrix's fixtures (`E07-03` / `S1-T22`).

`kernel-cli.md` §12 names the fixture set, one per row, and §12's own `# TODO: [MVP]`
asks for exactly this: *"generate these synthetically where possible rather than
committing real documents."* Every fixture here is generated, so:

- the repository carries no corpus data;
- each fixture is **exactly** the failure it provokes, not a document that happens to
  exhibit it - so a fixture cannot drift away from its row without this file changing;
- regenerating is deterministic, so a diff is a real change rather than a re-export.

Run it after changing anything here, and commit the result:

    python tests/fixtures/matrix/build.py

Each fixture's provoking property is asserted by `tests/kernel_cli/test_matrix.py`,
which is what makes a regenerated file that lost its property a red test rather than a
quiet re-baseline.

The two single-page PDFs are written by hand rather than through a library, so their
bytes do not change when a library's version does. `three-invoices.pdf` uses PyMuPDF
because laying out three real text pages by hand would be a font-programming exercise
with no fidelity gain.

Rows with no fixture, and why (`kernel-cli.md` §12 says so): rows 1-2 and 16 are
procedures over the artifacts the other rows produce, and row 14 is a procedure over the
host setting - an unreachable provider is a *closed port*, not a document.
"""

from __future__ import annotations

import io
import pathlib

HERE = pathlib.Path(__file__).resolve().parent

#: The descriptor the Stage 1 gate runs, copied in so this directory is
#: self-contained.
_DESCRIPTOR = "synthetic-3stage.yaml"

#: PDF text rendering mode 3 is *neither fill nor stroke*: the text occupies the page
#: and draws nothing. It is the only thing that makes a text layer invisible
#: (`kernels/pdf.py`, `INVISIBLE_RENDER_MODE`), which is what row 3 turns on.
_INVISIBLE_RENDER_MODE = 3

#: Row 8's page size, in pixels. Deliberately not square: a square page would let a
#: transposed `(x, y)` produce the same ``source_box`` as the correct mapping, so the
#: row would still pass with the two axes swapped.
_PAGE_SIZE = (840, 1036)


def _jpeg(width: int, height: int) -> bytes:
    """Build a small greyscale JPEG.

    Pillow is what K3's adapter already binds, so this adds no dependency - and a JPEG
    is what a scan is, which is the property rows 3 and 4 turn on.

    Args:
        width: The width in pixels.
        height: The height in pixels.

    Returns:
        The encoded bytes.

    """
    from PIL import Image  # pylint: disable=import-outside-toplevel

    image = Image.new("L", (width, height), color=200)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=70)
    return buffer.getvalue()


def _page_objects(
    *,
    width: int,
    height: int,
    jpeg: bytes | None,
    invisible_text: str | None,
    visible_text: str | None,
) -> list[bytes]:
    """Build the object list for a one-page PDF.

    Args:
        width: The MediaBox width in points.
        height: The MediaBox height in points.
        jpeg: A full-page image, or None.
        invisible_text: Text drawn in render mode 3.
        visible_text: Text drawn normally.

    Returns:
        The objects, in order, with the catalog first.

    """
    xobjects = b"/XObject << /Im0 5 0 R >>" if jpeg is not None else b""

    parts: list[bytes] = []
    if jpeg is not None:
        parts.append(b"q %d 0 0 %d 0 0 cm /Im0 Do Q" % (width, height))
    if invisible_text:
        parts.append(
            b"BT /F1 12 Tf %d Tr 72 712 Td (" % _INVISIBLE_RENDER_MODE
            + invisible_text.encode()
            + b") Tj ET"
        )
    if visible_text:
        parts.append(
            b"BT /F1 12 Tf 0 Tr 72 712 Td (" + visible_text.encode() + b") Tj ET"
        )
    content = b"\n".join(parts)

    image_object = (
        (
            b"<< /Type /XObject /Subtype /Image /Width %d /Height %d "
            b"/ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /DCTDecode "
            b"/Length %d >>\nstream\n"
            % (width, height, len(jpeg))
            + jpeg
            + b"\nendstream"
        )
        if jpeg is not None
        else b"<< >>"
    )

    return [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [4 0 R] /Count 1 >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Resources "
        b"<< /Font << /F1 3 0 R >> %s >> /Contents 6 0 R >>"
        % (width, height, xobjects),
        image_object,
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
    ]


def _write_pdf(path: pathlib.Path, objects: list[bytes]) -> None:
    """Write a PDF from an object list, with a correct cross-reference table.

    Args:
        path: Where to write it.
        objects: The objects, numbered from 1.

    """
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"

    xref = len(out)
    out += b"xref\n0 %d\n" % (len(objects) + 1)
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    path.write_bytes(bytes(out))


def _scan_with_hidden_layer(path: pathlib.Path) -> None:
    """Write row 3's fixture: a scan carrying a stale invisible OCR layer.

    **Both properties are needed.** The image makes the page measure as a scan; render
    mode 3 makes the text layer invisible. With only the text the page is a text PDF and
    there is no failure to provoke; with only the image there is no layer to be stale,
    and nothing distinguishes it from row 4's fixture.

    Args:
        path: Where to write it.

    """
    _write_pdf(
        path,
        _page_objects(
            width=612,
            height=792,
            jpeg=_jpeg(612, 792),
            invisible_text="stale ocr layer",
            visible_text=None,
        ),
    )


def _plain_scan(path: pathlib.Path) -> None:
    """Write row 4's fixture: a genuine scan, an image and no text layer at all.

    The MediaBox is A5 sized for the embedded pixel count, so the page measures below
    300 DPI - which is what makes a `--dpi 300` request unanswerable.

    Args:
        path: Where to write it.

    """
    _write_pdf(
        path,
        _page_objects(
            width=826,
            height=1169,
            jpeg=_jpeg(826, 1169),
            invisible_text=None,
            visible_text=None,
        ),
    )


def _three_pages(path: pathlib.Path) -> None:
    """Write row 5's fixture: three pages of visible text.

    Each page carries **more text than any plausible `min_chars`**, and that is not
    decoration: with too little, the page measures as an image rather than a text page
    and the fixture stops provoking row 5 at all. Six characters did exactly that -
    the fixture looked right and classified as a scan. The line below is long enough
    that the text layer is unambiguous at the default threshold.

    Args:
        path: Where to write it.

    """
    import fitz  # pylint: disable=import-outside-toplevel

    body = (
        "This page carries enough visible text that the text layer is unambiguous. "
        "A range split out of this document must contain the pages it names."
    )
    document = fitz.open()
    for index in range(3):
        page = document.new_page(width=612, height=792)
        page.insert_text((72, 200), f"page {index + 1} of 3")
        page.insert_textbox(fitz.Rect(72, 220, 540, 500), body)
    document.save(path)
    document.close()


def _page_image(path: pathlib.Path) -> None:
    """Write row 8's fixture: a page image whose crop must map back to it.

    The properties row 8 turns on are **geometric**, so they are chosen rather than
    incidental: the image is larger than any region the row crops, so a region inside
    it is answerable, and its dimensions are not square, so a transposed or swapped
    width/height cannot pass by coincidence - a square page would let an
    ``(x, y)``/``(y, x)`` mix-up produce the same numbers.

    No DPI is written into the file, deliberately. `crop` maps coordinates and never
    rescales, so a declared resolution would be an unrelated fact sitting in the
    fixture, and a reader could mistake it for the thing the row measures.

    Args:
        path: Where to write it.

    """
    from PIL import Image  # pylint: disable=import-outside-toplevel

    Image.new("L", _PAGE_SIZE, color=230).save(path, format="PNG")


def build() -> list[str]:
    """Generate every fixture, and return what was written.

    Returns:
        The fixture names, sorted.

    """
    descriptor_source = (
        pathlib.Path(__file__).resolve().parents[3] / "descriptors" / _DESCRIPTOR
    )
    (HERE / _DESCRIPTOR).write_text(
        descriptor_source.read_text(encoding="utf-8"), encoding="utf-8"
    )

    _scan_with_hidden_layer(HERE / "scan-hidden-layer.pdf")
    _plain_scan(HERE / "scan150.pdf")
    _three_pages(HERE / "three-invoices.pdf")
    _page_image(HERE / "page.png")

    return sorted(path.name for path in HERE.glob("*") if path.name != "build.py")


def main() -> int:
    """Generate, verify and report.

    Returns:
        0 when every fixture is non-empty, 1 otherwise - an empty fixture would make
        its row assert against nothing.

    """
    print(f"generating into {HERE}")
    failed = False
    for name in build():
        size = (HERE / name).stat().st_size
        print(f"  {name}: {size} bytes")
        if size == 0:
            print(f"  !! {name} is empty: its row would assert against nothing")
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
