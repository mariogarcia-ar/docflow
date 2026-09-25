"""The in-memory Poppler double (``PDF-14``).

Poppler is a set of CLI binaries: it hands back **files plus an exit code and stderr**,
never a return value. This double models exactly that. It stands where the seam calls
``subprocess.run`` — ``docflow.pdf.primitives.subprocess.run`` — and answers with what the
CLI would have written, so the whole translation between the subprocess contract and our
artifact tree stays under test (`README.md` §9.7). It never returns one of our types: a
fake that returned a ``PDFPageResult`` would delete the half of the module it exists to
exercise.

The double mirrors the module surface the seam touches, because the convention check in
``tests/fakes/engines/convention.py`` reads the seam statically and requires the double to
model *every* attribute the seam reaches on the engine — including the type it names in an
annotation and the exception it handles, not only the function it calls.

Two knobs make the failure paths reachable with no engine installed:

* ``failures`` — a non-zero exit with stderr, keyed by binary name or by
  ``(binary, page)``;
* ``raises`` — an exception, so a missing binary or a timeout is reachable too.

Anything the double does not model is recorded in :attr:`FakePoppler.unhandled` and
answered with the generic non-zero exit, so a call the double drifted away from fails
loudly instead of passing silently.

# TODO: [RELEASE] re-read this double against the engine's documented output on every
# pin bump: a hand-written double is the one place an engine shape change has to be
# re-checked, and the suite cannot notice it by itself (`GEN-17`).
"""

from __future__ import annotations

import subprocess
import zlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: The version the double reports. Deliberately synthetic: a test that asserted this value
#: would be asserting what the double was told, not what Poppler says, and the version a
#: real engine reports is not this processor's business.
FAKE_ENGINE_VERSION = "1.2.3-test"

#: The generic exit code the engine family uses for "other error".
GENERIC_ERROR = 99

#: The engine's message for an impossible page range. It arrives under the generic exit
#: code, so only the text separates it from a failure of the work itself.
WRONG_PAGE_RANGE = (
    "Wrong page range given: the first page ({page}) can not be after the last page "
    "({count})."
)

TSV_HEADER = (
    "level\tpage_num\tpar_num\tblock_num\tline_num\tword_num\tleft\ttop\twidth\t"
    "height\tconf\ttext"
)

IMAGES_HEADER = (
    "page   num  type   width height color comp bpc  enc interp  object ID "
    "x-ppi y-ppi size ratio"
)
IMAGES_RULE = "-" * len(IMAGES_HEADER)


@dataclass(frozen=True)
class FakeImage:
    """One image the engine would report and extract for a page.

    Attributes:
        width: Image width in pixels.
        height: Image height in pixels.
        encoding: The encoding the engine reports, e.g. ``"image"`` or ``"jpeg"``.
        color: The colour space the engine reports.
        bpc: Bits per component the engine reports.
    """

    width: int = 48
    height: int = 48
    encoding: str = "image"
    color: str = "rgb"
    bpc: str = "8"


@dataclass(frozen=True)
class FakePage:
    """One page the engine would report: its geometry, its text and its images.

    Attributes:
        lines: The page's native text lines, in reading order.
        size: The page's width and height in PDF points.
        images: The images embedded in the page, in scan order.
    """

    lines: tuple[str, ...] = ()
    size: tuple[float, float] = (612.0, 792.0)
    images: tuple[FakeImage, ...] = ()


def png_bytes(
    width: int, height: int, color: tuple[int, int, int] = (200, 40, 40)
) -> bytes:
    """Return a real, decodable PNG of a solid colour.

    The engine's artifacts have to be real artifacts: the bytes this returns can be
    compared with what our publication wrote, which is how a test proves the artifact was
    not mangled on its way to its final name.
    """

    def chunk(tag: bytes, payload: bytes) -> bytes:
        crc = zlib.crc32(tag + payload)
        return len(payload).to_bytes(4, "big") + tag + payload + crc.to_bytes(4, "big")

    header = (
        width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + bytes([8, 2, 0, 0, 0])  # 8 bits per channel, truecolour
    )
    raw = b"".join(b"\x00" + bytes(color) * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


class FakePoppler:
    """A stand-in for the Poppler binaries, answering where ``subprocess.run`` is called."""

    # pylint: disable=too-few-public-methods
    # Reason: only ``run`` is public by design; the rest are per-binary handlers, so the
    # convention check sees the engine surface the seam may call and nothing else.

    #: The two names the seam reaches on the engine besides ``run``: it annotates with the
    #: first and handles the second, so the convention check requires the double to know
    #: both.
    CompletedProcess = subprocess.CompletedProcess
    TimeoutExpired = subprocess.TimeoutExpired

    def __init__(
        self,
        pages: Sequence[FakePage] = (FakePage(),),
        *,
        version: str = FAKE_ENGINE_VERSION,
        failures: Mapping[str | tuple[str, int], tuple[int, str]] | None = None,
        raises: Mapping[str | tuple[str, int], BaseException] | None = None,
        noise: Mapping[str | tuple[str, int], str] | None = None,
    ) -> None:
        """Build a double over a scripted document.

        Args:
            pages: The document the engine would report.
            version: What the version probe answers.
            failures: A non-zero exit with stderr, keyed by binary name or by
                ``(binary, page)``.
            raises: An exception to raise instead of answering, keyed the same way.
            noise: stderr to attach to a *successful* call, for the paths that treat a
                warning as fatal.
        """
        self.pages = list(pages)
        self.version = version
        self.failures = dict(failures or {})
        self.raises = dict(raises or {})
        self.noise = dict(noise or {})
        self.calls: list[list[str]] = []
        self.unhandled: list[list[str]] = []
        self.renders: dict[tuple[int, int], bytes] = {}

    def run(
        self, args: Sequence[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        """Answer one engine call the way the CLI would.

        Args:
            args: The argv the seam built; ``args[0]`` names the binary.
            kwargs: The call's keyword arguments, accepted and unused: the seam's own
                transport options are not the engine's contract.

        Returns:
            The completed process: its exit code, its stdout and its stderr.
        """
        del kwargs
        argv = [str(argument) for argument in args]
        self.calls.append(argv)
        binary = Path(argv[0]).name
        page_number = self._page_of(argv)

        for key in ((binary, page_number), binary):
            if key in self.raises:
                raise self.raises[key]
            if key in self.failures:
                code, stderr = self.failures[key]
                return self._completed(argv, code, stderr=stderr)

        if page_number is not None and page_number > len(self.pages):
            return self._completed(
                argv,
                GENERIC_ERROR,
                stderr=WRONG_PAGE_RANGE.format(page=page_number, count=len(self.pages)),
            )

        stdout = self._answer(binary, argv)
        if stdout is None:
            self.unhandled.append(argv)
            return self._completed(
                argv, GENERIC_ERROR, stderr=f"unmodelled call: {binary}"
            )
        return self._completed(
            argv, 0, stdout=stdout, stderr=self._noise_for(binary, page_number)
        )

    # -- the engine's own answers ------------------------------------------------

    def _answer(self, binary: str, argv: Sequence[str]) -> str | None:
        """Return the stdout the binary would have produced, or ``None`` if unmodelled."""
        if binary == "pdfinfo":
            return self._version(argv) if "-v" in argv else self._document_info(argv)
        handlers = {
            "pdfseparate": self._separate,
            "pdftotext": self._text,
            "pdfimages": self._images,
            "pdftoppm": self._render,
            "pdfunite": self._unite,
        }
        handler = handlers.get(binary)
        return None if handler is None else handler(argv)

    def _version(self, argv: Sequence[str]) -> str:
        del argv
        return (
            f"pdfinfo version {self.version}\n"
            "Copyright 2005-2025 The Poppler Developers - "
            "http://poppler.freedesktop.org\n"
        )

    def _document_info(self, argv: Sequence[str]) -> str:
        """The ``pdfinfo -box`` report: the page count plus the per-page geometry."""
        last = min(self._last_page(argv), len(self.pages))
        rows = [f"Title: {self._title}", f"Pages: {len(self.pages)}", "Encrypted: no"]
        rows.extend(
            f"Page {number} size: {self.pages[number - 1].size[0]:g} x "
            f"{self.pages[number - 1].size[1]:g} pts"
            for number in range(1, last + 1)
        )
        rows.extend(f"Page {number} rot: 0" for number in range(1, last + 1))
        return "\n".join(rows) + "\n"

    def _separate(self, argv: Sequence[str]) -> str:
        """The ``pdfseparate`` run: one self-contained page, at the caller's pattern."""
        page_number = self._page_of(argv) or 1
        pattern = argv[-1]
        Path(pattern % page_number).write_bytes(self._page_pdf(page_number))
        return ""

    def _text(self, argv: Sequence[str]) -> str:
        """The ``pdftotext -tsv`` report: the page's flows, lines and words."""
        page_number = self._page_of(argv) or 1
        page = self.pages[page_number - 1]
        width, height = page.size
        rows = [
            TSV_HEADER,
            f"1\t{page_number}\t0\t0\t0\t0\t0.000000\t0.000000\t{width:.6f}\t"
            f"{height:.6f}\t-1\t###PAGE###",
        ]
        for line_number, line in enumerate(page.lines):
            top = 72.0 + 20.0 * line_number
            rows.append(
                f"3\t{page_number}\t0\t{line_number}\t0\t0\t72.000000\t{top:.6f}\t"
                f"460.000000\t12.000000\t-1\t###FLOW###"
            )
            rows.append(
                f"4\t{page_number}\t0\t{line_number}\t{line_number}\t0\t72.000000\t"
                f"{top:.6f}\t460.000000\t12.000000\t-1\t###LINE###"
            )
            rows.extend(
                f"5\t{page_number}\t0\t{line_number}\t{line_number}\t{word_number}\t"
                f"{72.0 + 50.0 * word_number:.2f}\t{top + 1.0:.2f}\t40.00\t9.43\t100\t"
                f"{word}"
                for word_number, word in enumerate(line.split())
            )
        return "\n".join(rows) + "\n"

    def _images(self, argv: Sequence[str]) -> str:
        """The ``pdfimages`` run: either the report, or the extracted image files."""
        page_number = self._page_of(argv) or 1
        page = self.pages[page_number - 1]
        if "-list" in argv:
            rows = [IMAGES_HEADER, IMAGES_RULE]
            rows.extend(
                f"{page_number:4d} {index:5d} image   {image.width:5d} {image.height:5d}  "
                f"{image.color}     3   {image.bpc}  {image.encoding}  no        6  0    "
                f"36    36   33B 0.5%"
                for index, image in enumerate(page.images)
            )
            return "\n".join(rows) + "\n"

        root = argv[-1]
        for index, image in enumerate(page.images):
            Path(f"{root}-{index:03d}.png").write_bytes(
                png_bytes(image.width, image.height)
            )
        return ""

    def _render(self, argv: Sequence[str]) -> str:
        """The ``pdftoppm -singlefile`` run: one PNG named after the caller's root."""
        page_number = self._page_of(argv) or 1
        dpi = self._dpi_of(argv)
        width, height = self.pages[page_number - 1].size
        data = png_bytes(round(width / 72 * dpi), round(height / 72 * dpi))
        self.renders[(page_number, dpi)] = data
        Path(f"{argv[-1]}.png").write_bytes(data)
        return ""

    def _unite(self, argv: Sequence[str]) -> str:
        """The ``pdfunite`` run: a merged file that names its parts, in order."""
        Path(argv[-1]).write_bytes(
            b"%PDF-1.7\n% merged in order: "
            + b", ".join(Path(part).name.encode() for part in argv[1:-1])
            + b"\n%%EOF\n"
        )
        return ""

    # -- helpers -----------------------------------------------------------------

    @property
    def _title(self) -> str:
        return "docflow pdf fixture"

    def _completed(
        self,
        argv: Sequence[str],
        returncode: int,
        *,
        stdout: str = "",
        stderr: str = "",
    ) -> subprocess.CompletedProcess[str]:
        """Build the completed process the seam will read."""
        return subprocess.CompletedProcess(list(argv), returncode, stdout, stderr)

    def _noise_for(self, binary: str, page_number: int | None) -> str:
        """Return the stderr a successful call carries, if the double was told to add one."""
        return self.noise.get((binary, page_number), self.noise.get(binary, ""))

    def _page_of(self, argv: Sequence[str]) -> int | None:
        """Return the ``-f`` page of a call, clamped below as the engine clamps it."""
        if "-f" not in argv:
            return None
        return max(1, int(argv[argv.index("-f") + 1]))

    def _last_page(self, argv: Sequence[str]) -> int:
        """Return the ``-l`` page of a call, or the last page of the document."""
        if "-l" not in argv:
            return len(self.pages)
        return max(1, int(argv[argv.index("-l") + 1]))

    def _dpi_of(self, argv: Sequence[str]) -> int:
        """Return the ``-r`` resolution of a call."""
        return int(argv[argv.index("-r") + 1]) if "-r" in argv else 150

    def _page_pdf(self, page_number: int) -> bytes:
        """Return the bytes of a one-page PDF the engine would have produced."""
        return (
            f"%PDF-1.7\n% extracted page {page_number} of {len(self.pages)}\n%%EOF\n"
        ).encode("latin-1")
