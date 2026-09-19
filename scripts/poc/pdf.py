"""Direct probes of the K2 `pdf` adapter, one method per requirement.

`my_kernel_flow.md` §1 asks for four things of the `pdf` kernel:

1. cut the PDF into pages,
2. decide whether a page is predominantly text or image,
3. text -> extract with `pdftotext --layout` and save it to a file,
4. image -> export the page as an image, for OCR afterwards.

Each is a method below that calls `PdfEngine` directly. Nothing here goes through
`docflow-kernel`, so what this reports is the adapter's behaviour and not the
lab surface's.

**The routing is the script's, not the adapter's.** Steps 3 and 4 are *decisions*,
and `kernel-cli.md` §3 guardrail 2 forbids a kernel from taking one: `classify`
reports a shape and the measurements behind it, and the choice of what to do about
that shape belongs to the caller. So `extract_page` below is the caller in that
sentence - it reads the shape the kernel measured and then asks a second, separate
operation for the artifact.

Run it with no arguments to probe the committed fixtures:

    python scripts/poc/pdf.py

Add `--out <dir>` to change where bytes and text land (`var/poc/` by default).
"""

from __future__ import annotations

import argparse
import pathlib
import sys

import _lib

# `docflow` is only importable once `src/` is on the path, and `pyproject.toml`'s
# `pythonpath = ["src"]` applies to pytest alone. That is why `_lib` is imported
# first and `bootstrap()` is called before the adapter import below - the ordering
# is load-bearing, not stylistic.
_lib.bootstrap()

from docflow.adapters.pdf import PdfEngine  # noqa: E402 - see the note above
from docflow.kernel_cli.commands.pages import page_token, parse_pages  # noqa: E402

__all__: list[str] = []

#: A page selection **as a caller writes it** - ``kernel-cli.md`` §9's grammar, not
#: the page list the port takes. Both are spelled with digits and commas, so a
#: bench that hands the text straight to an adapter produces a plausible call that
#: fails inside the kernel (`TypeError: '<' not supported between instances of
#: 'str' and 'int'`) instead of a page range. Expanding it is the *surface's* job
#: (`commands/pages.py`), which is why this bench borrows that parser rather than
#: writing a second one: two parsers for one grammar would be two answers.
#:
#: **One constant for the three operations that take a selection.** `split`,
#: `render` and `layout_text` accept the same text because `--pages` is one flag;
#: separate constants would let them drift into three grammars, which is the class
#: of defect this bench exists to make unrepresentable.
PAGES_AS_WRITTEN: str = "5-15"

#: The selection that must be **refused** rather than honoured, because
#: `pdf layout` requires its pages strictly ascending (`commands/pdf.py`) while
#: `split` and `render` honour whatever order they are given. So a reordering is a
#: *usage* answer - the library's equivalent of exit 4 - and never a defect, which
#: is the distinction `REORDERED_PAGES` is here to keep visible.
REORDERED_PAGES: str = "15,5"

#: The resolution a render is asked for. 72 DPI is 1:1 with PDF user units, so a
#: page rendered at 72 needs no resampling - which is what makes it the honest
#: default for a probe that is measuring the adapter rather than a pipeline.
RENDER_DPI: int = 72

#: The DPI the large fixture cannot satisfy. Measured: its pages hold 295.59 DPI,
#: and the adapter refuses to upscale - so this probe asserts the *refusal*, which
#: is matrix row 4 (`kernel-cli.md` §11).
OVER_THE_CEILING_DPI: int = 300

#: A page number the one-page text fixture does not have, to provoke the usage
#: answer.
_MISSING_PAGE: int = 99


def _engine() -> PdfEngine:
    """Build the K2 adapter with the registry's threshold.

    `min_chars` is a required constructor argument with no default (`ADR-009`,
    corpus policy), so it is read from the registry rather than chosen here.

    Returns:
        The engine, ready to call.

    """
    return PdfEngine(min_chars=_lib.policy("reader.min_chars"))


# --- Requirement 2: is the page text or image? ------------------------------


def classify_page(
    engine: PdfEngine, path: pathlib.Path, page: int, expect: str
) -> None:
    """Measure one page's shape.

    Args:
        engine: The K2 adapter.
        path: The PDF to inspect.
        page: One-based page number.
        expect: The bucket this probe is declared to land in.

    """
    _lib.run(
        f"pdf.classify[{path.parent.name}]", engine.classify, path, page, expect=expect
    )


# --- Requirement 1: cut the PDF into pages ----------------------------------


def split_pages(
    engine: PdfEngine,
    path: pathlib.Path,
    written: str,
    total: int | None,
    expect: str,
) -> None:
    """Cut a page range out of a PDF and write the result.

    The selection arrives **as a caller writes it** and is expanded here, because
    the port takes page numbers and not text. Handing the text to the adapter is
    the defect this signature exists to prevent: both spellings are digits and
    commas, so the mistake survives review and fails inside the kernel's own
    validation rather than at the boundary that could have refused it.

    Args:
        engine: The K2 adapter.
        path: The PDF to cut.
        written: The selection as a caller writes it, in `kernel-cli.md` §9's
            grammar - the same text `--pages` accepts.
        total: How many pages the document has, so the range is checked against
            the document. ``None`` means it could not be measured; the numbers are
            then returned unvalidated rather than checked against an invented
            count.
        expect: The bucket this probe is declared to land in.

    """
    pages = parse_pages(written, total)
    attempt = _lib.run(
        f"pdf.split[{written}]", engine.split, path, pages, expect=expect
    )
    if not attempt.succeeded:
        return

    name = f"{path.stem}-{page_token(written)}.pdf"
    written_to = _lib.save_bytes(name, attempt.result.value.data)
    print(f"         wrote {_lib.shown(written_to)}")


def document_pages(engine: PdfEngine, path: pathlib.Path) -> int | None:
    """Report how many pages a document has, from the engine's own probe.

    The count is *measured*, never assumed: a page range is checked against the
    document, and a count hardcoded in this bench would keep validating ranges
    against a fixture that had since changed.

    Args:
        engine: The K2 adapter.
        path: The PDF to measure.

    Returns:
        The page count, or ``None`` when the probe reported none - in which case a
        selection cannot be checked, and the caller must not invent a count to
        check it against.

    """
    attempt = _lib.run(f"pdf.probe[{path.parent.name}]", engine.probe, path)
    if not attempt.succeeded:
        return None

    pages = attempt.result.evidence.measurements.get("page_count")
    return None if pages is None else int(pages)


# --- Requirement 3: text -> pdftotext --layout, saved ----------------------


def layout_text(
    engine: PdfEngine,
    path: pathlib.Path,
    written: str,
    expect: str,
    total: int | None = None,
    *,
    save: bool = True,
) -> _lib.Attempt:
    """Extract a page range's text with its physical layout preserved, and save it.

    Same boundary as `split_pages` and `render_page`, for the same reason: the
    selection arrives **as a caller writes it** - `kernel-cli.md` §9's `--pages`
    grammar - and is expanded here, because the adapter takes page numbers. Text
    handed straight to the adapter is not refused at the call; it reaches the
    kernel's own validation and raises `TypeError` on comparing a `str` with an
    `int`, which reads as a broken build rather than as a wrong selection.

    `layout_text` is deliberately **not** on `PdfSource` (`plans/README.md` §3
    freezes the port at five operations) - it is reached on the adapter, which is
    exactly what this bench is for.

    Unlike `split` and `render`, this operation **refuses a reordered selection**
    rather than honouring it: the reader returns one page's text after another's,
    so an order the caller chose is an order no measurement supports. That is a
    usage answer and the caller sees it as one - see `REORDERED_PAGES`.

    Returns the attempt rather than nothing, so a batch caller reuses this call's
    result instead of running the extraction a second time.

    Args:
        engine: The K2 adapter.
        path: The PDF to read.
        written: The selection as a caller writes it, in `kernel-cli.md` §9's
            grammar - the same text `--pages` accepts.
        expect: The bucket this probe is declared to land in.
        total: How many pages the document has, so the range is checked against
            the document. ``None`` - the reading a batch caller takes, having not
            probed the file - leaves the numbers unvalidated rather than checked
            against an invented count.
        save: Whether to write the text under the driver's own output root. A
            batch caller passes ``False``: it writes the text into its mirrored
            tree, and a second flat copy would be a file nothing pairs with a
            document.

    Returns:
        The attempt, carrying the result the probe described.

    """
    pages = parse_pages(written, total)
    attempt = _lib.run(
        f"pdf.layout_text[{written}]", engine.layout_text, path, pages, expect=expect
    )
    if not attempt.succeeded:
        return attempt

    if save:
        name = f"{path.stem}-{page_token(written)}.layout.txt"
        written_to = _lib.save_text(name, attempt.result.value)
        print(f"         wrote {_lib.shown(written_to)}")
    return attempt


# --- Requirement 4: image -> export the page for OCR -----------------------


def render_page(
    engine: PdfEngine,
    path: pathlib.Path,
    written: str,
    dpi: int,
    expect: str,
    total: int | None = None,
    *,
    save: bool = True,
) -> _lib.Attempt:
    """Render a page range as a bitmap, ready to be handed to K4.

    Same boundary as `split_pages`, for the same reason: the selection arrives
    **as a caller writes it** - `kernel-cli.md` §9's `--pages` grammar - and is
    expanded here, because `PdfSource.render` takes page numbers. Text handed
    straight to the adapter is not refused at the call: it reaches the kernel's
    own validation and raises `TypeError` on comparing a `str` with an `int`,
    which reads as a broken build rather than as a wrong selection.

    Returns the attempt rather than nothing, so a batch caller reuses this call's
    result instead of rendering the page a second time.

    Args:
        engine: The K2 adapter.
        path: The PDF to render.
        written: The selection as a caller writes it, in `kernel-cli.md` §9's
            grammar - the same text `--pages` accepts.
        dpi: The resolution requested.
        expect: The bucket this probe is declared to land in.
        total: How many pages the document has, so the range is checked against
            the document. ``None`` - the reading a batch caller takes, having not
            probed the file - leaves the numbers unvalidated rather than checked
            against an invented count.
        save: Whether to write the bitmap under the driver's own output root.
            A batch caller passes ``False`` and writes its own mirrored name.

    Returns:
        The attempt, carrying the result the probe described.

    """
    pages = parse_pages(written, total)
    label = f"pdf.render[{written}]@{dpi}"
    attempt = _lib.run(label, engine.render, path, pages, dpi, expect=expect)
    if not attempt.succeeded:
        return attempt

    value = attempt.result.value
    if save:
        suffix = ".png" if value.media_type == "image/png" else ".bin"
        name = f"{path.stem}-{page_token(written)}-dpi{dpi}{suffix}"
        written_to = _lib.save_bytes(name, value.data)
        print(f"         wrote {_lib.shown(written_to)}")
    return attempt


def effective_dpi(engine: PdfEngine, path: pathlib.Path, page: int) -> None:
    """Measure the resolution a page's pixels actually hold.

    Kernel-only, like `layout_text`, and reported because it is the number that
    decides whether a render is reachable at all.

    Args:
        engine: The K2 adapter.
        path: The PDF to measure.
        page: One-based page number.

    """
    _lib.run("pdf.effective_dpi", engine.effective_dpi, path, page)


# --- The requirement that spans two operations ------------------------------


def extract_page(engine: PdfEngine, path: pathlib.Path, page: int) -> None:
    """Route one page to the operation its measured shape calls for.

    This is the shape of `my_kernel_flow.md` §1 end to end, and the routing is
    performed **here** rather than in the kernel: `classify` answers what the page
    is, and the caller decides what to ask for next.

    Both branches go through this bench's own helpers (`layout_text`,
    `render_page`) rather than calling the adapter, so this routing cannot be the
    one place a selection reaches the kernel as text. A second call site is a
    second boundary, and that is how the defect this bench now prevents survived
    review the first time.

    Args:
        engine: The K2 adapter.
        path: The PDF to process.
        page: One-based page number.

    """
    attempt = _lib.run(
        f"pdf.extract_page[{page}]/classify", engine.classify, path, page
    )
    if not attempt.succeeded:
        return

    measured = attempt.result
    shape = str(measured.evidence.observed.get("shape", "?"))

    if shape in {"text", "mixed"}:
        named = layout_text(engine, path, str(page), "ok", save=False)
        if named.succeeded:
            written = _lib.save_text(
                f"{path.stem}-p{page}.routed.txt", named.result.value
            )
            print(f"         wrote {_lib.shown(written)}")
    else:
        rendered = render_page(engine, path, str(page), RENDER_DPI, "ok", save=False)
        if rendered.succeeded:
            written = _lib.save_bytes(
                f"{path.stem}-p{page}-routed{RENDER_DPI}.png",
                rendered.result.value.data,
            )
            print(f"         wrote {_lib.shown(written)} (for K4)")

    _lib.note(f"pdf.extract_page[{page}]", f"routed on shape={shape!r}")


# --- The run ----------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Run every `pdf` probe and tally the result.

    Args:
        argv: The command-line arguments, or ``None`` for `sys.argv`.

    Returns:
        The number of probes that produced a bucket other than the one declared.

    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--out",
        type=pathlib.Path,
        default=_lib.DEFAULT_OUT,
        help="where rendered pages and extracted text are written",
    )
    args = parser.parse_args(argv)

    _lib.set_out(args.out)
    _lib.reset()
    engine = _engine()

    print(f"min_chars = {_lib.policy('reader.min_chars')} (from the registry)")
    print(f"out       = {args.out}")
    print()

    # The page counts, measured once from each document's own probe and before
    # anything is asked of a selection: a range is checked against the document it
    # belongs to, and a count hardcoded here would keep validating against a
    # fixture that had since changed.
    large_pages = document_pages(engine, _lib.LARGE_PDF)
    source_pages = document_pages(engine, _lib.SOURCE_PDF)

    print()
    # Requirement 2, on both fixtures the folder names label. A text PDF and a
    # scanned one are the two answers the routing depends on.
    classify_page(engine, _lib.TEXT_PDF, 1, "ok")
    classify_page(engine, _lib.SCAN_PDF, 1, "ok")
    # A page with neither text nor image. `MetodoCITRA17-APL.pdf` pages 2 and 58
    # report `blank_page` **although they draw ~748 vector items** - a known false
    # positive, and the reason this probe asserts the bug rather than the truth.
    classify_page(engine, _lib.LARGE_PDF, 2, "reason")

    print()
    # Requirement 4, on the fixture it is right for.
    render_page(engine, _lib.SCAN_PDF, "1", RENDER_DPI, "ok")

    print()
    # The anti-upscale rule, which is the adapter refusing rather than obeying.
    effective_dpi(engine, _lib.LARGE_PDF, 1)
    render_page(engine, _lib.LARGE_PDF, "1", OVER_THE_CEILING_DPI, "reason")

    print()
    # Requirement 3, on a range wide enough to be a range rather than a page.
    layout_text(engine, _lib.SOURCE_PDF, "1", "ok", source_pages)
    layout_text(engine, _lib.LARGE_PDF, PAGES_AS_WRITTEN, "ok", large_pages)
    # `pdf layout` requires its pages strictly ascending, so this is the one
    # operation of the three where a reordered selection is refused rather than
    # honoured - an answer, not a defect.
    layout_text(engine, _lib.LARGE_PDF, REORDERED_PAGES, "usage", large_pages)

    print()
    # Requirement 1. The selection is written the way a caller writes it, and
    # expanded against a page count measured from the document itself.
    split_pages(engine, _lib.SOURCE_PDF, "1", source_pages, "ok")
    split_pages(engine, _lib.LARGE_PDF, "2,3", large_pages, "ok")
    split_pages(engine, _lib.LARGE_PDF, "22,33", large_pages, "ok")
    # The range grammar, which is the surface's and not the port's: `5-15` is
    # eleven pages, and passing the text straight to `split` raises a `TypeError`
    # about comparing a `str` with an `int`.
    split_pages(engine, _lib.LARGE_PDF, PAGES_AS_WRITTEN, large_pages, "ok")

    print()
    # A page the document does not have. The kernel raises `ValueError` - the
    # library's equivalent of exit 4 - and this probe confirms it does not crash
    # the process with a traceback.
    render_page(engine, _lib.TEXT_PDF, str(_MISSING_PAGE), RENDER_DPI, "usage")
    # A selection of two enumerated pages, then the same grammar a caller would
    # type. Both go through `parse_pages`, so neither reaches the kernel as text.
    render_page(engine, _lib.LARGE_PDF, "1,2", RENDER_DPI, "ok", large_pages)
    render_page(engine, _lib.LARGE_PDF, "all", RENDER_DPI, "ok", large_pages)
    render_page(
        engine,
        _lib.LARGE_PDF,
        PAGES_AS_WRITTEN,
        RENDER_DPI,
        "ok",
        large_pages,
    )

    print()
    # The requirement that spans two operations.
    extract_page(engine, _lib.TEXT_PDF, 1)
    extract_page(engine, _lib.SCAN_PDF, 1)

    print()
    return _lib.summary()


if __name__ == "__main__":
    sys.exit(main())
