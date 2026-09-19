"""Direct probes of the K4 `ocr` adapter, one method per requirement.

`my_kernel_flow.md` §3 asks for one thing of the `ocr` kernel:

> take an image and extract its text **to a file, preserving the layout as far as
> possible**.

That single sentence hides the one distinction this driver exists to make visible,
because the adapter has **two** operations that could answer it and they are not
interchangeable:

- ``read`` returns positioned tokens with **no reading order resolved** - it reports
  ``reading_order: "not_resolved"`` and ``layout_dropped: true``. That is deliberate:
  ordering is the `Reconstructor`'s job at Stage 2 (`S2-T07`), and an order resolved
  inside a kernel would be a domain-level interpretation performed at the primitive
  layer.
- ``layout`` orders the engine's blocks into rows. It is **not** on `OcrEngine` -
  `plans/README.md` §3 freezes the port's three operations - so it is reached on the
  adapter, which is exactly what this bench is for.

So ``layout`` satisfies the requirement and ``read`` does not, and C3 below prints
both on the same page so the difference is a measurement rather than a claim.

Run it with no arguments to probe the committed fixtures:

    python scripts/poc/ocr.py

`read` loads ONNX models **on every call** - measured ~9-11 s, and there is no warm
path, because each probe is a fresh process. Expect this driver to take a couple of
minutes.
"""

from __future__ import annotations

import argparse
import pathlib
import sys
from typing import Any

import _lib

# `docflow` is only importable once `src/` is on the path; see `pdf.py` for why
# the ordering of these two imports is load-bearing.
_lib.bootstrap()

from docflow.adapters.docling import DoclingEngine  # noqa: E402 - see the note above
from docflow.kernel_cli.commands.pages import parse_pages  # noqa: E402

__all__: list[str] = []

#: The resolution the returned boxes are expressed in. Docling measures in points
#: at 72 DPI, so 72 is the scale that changes nothing.
BOX_DPI: int = 72

#: The language hint. The port requires it, so a caller has to name something.
#: `commands/ocr.py::_DEFAULT_LANG` records the same word for the same reason; the
#: two are not shared because the surface's constant is private to it, and a bench
#: importing a private name from a command module would break on a refactor there.
LANG: str = "en"

#: How far apart two tokens may sit and still share a row, **in the boxes' units at
#: `BOX_DPI`**. Required by `layout`, with no default, because the legacy's `25.0`
#: was in PDF points and a constant in the adapter could not express that.
LINE_TOLERANCE: float = 25.0 * BOX_DPI / 72.0

#: A page selection **as a caller writes it** - `kernel-cli.md` §9's grammar, and
#: the same one K2 takes: `commands/ocr.py` expands `--pages` with the very
#: `parse_pages` `commands/pdf.py` uses. K4's adapter takes `Sequence[int]`, so text
#: handed straight to it does not fail at the call - it fails inside the kernel's
#: own validation with `TypeError: '<' not supported between instances of 'str' and
#: 'int'`, which reads as a broken build rather than as a wrong selection.
#: **Measured**, on the first run of this driver.
PAGES_AS_WRITTEN: str = "1"

#: A page the one-page fixture does not have. K4 validates a selection against the
#: document it converts (`len(document.pages)`), so this provokes its own refusal -
#: the usage answer - and the bench reports it rather than the process crashing.
MISSING_PAGE: str = "5"


def _engine() -> DoclingEngine:
    """Build the K4 adapter.

    Returns:
        The engine, ready to call.

    """
    return DoclingEngine()


# --- What the engine is -----------------------------------------------------


def report_capabilities(engine: DoclingEngine, expect: str) -> None:
    """Report what the engine can do, and which revision is doing it.

    The revision matters beyond documentation: it is the *adapter revision* term of
    the cache key (`sad.md` §5), so a stored artifact is only reproducible against
    the engine that produced it.

    Args:
        engine: The K4 adapter.
        expect: The bucket this probe is declared to land in.

    """
    attempt = _lib.run("ocr.capabilities", engine.capabilities, expect=expect)
    if not attempt.succeeded:
        return

    terms = attempt.result.evidence.terms
    print(f"         terms={sorted(terms)}")

    identity = _lib.run("ocr.engine_info", engine.engine_info, expect="ok")
    if identity.succeeded:
        print(f"         identity={dict(identity.result.evidence.terms)}")


# --- Requirement: image -> text, layout preserved ---------------------------


def read_text(
    engine: DoclingEngine,
    path: pathlib.Path,
    written: str,
    expect: str = "ok",
    *,
    lang: str = LANG,
    tables: bool = False,
) -> _lib.Attempt:
    """Read a page range and report the tokens **without** a resolved order.

    The selection arrives **as a caller writes it** and is expanded here, because
    `OcrEngine.read` takes page numbers. K4 validates the range against the document
    it converts, so an out-of-document page raises `ValueError` - the library's
    equivalent of exit 4 - and `_lib.run` buckets that as a *usage* answer rather
    than letting it take the process down.

    Returns the attempt, so a caller that needs the tokens - the batch driver does,
    for the record - does not pay for a second read.

    Args:
        engine: The K4 adapter.
        path: The document to read.
        written: The selection as a caller writes it, in `kernel-cli.md` §9's
            grammar - the same text `--pages` accepts.
        expect: The bucket this probe is declared to land in.
        lang: The language hint passed to the engine. A parameter rather than this
            module's constant, because the corpus decides it: a batch pointed at a
            Spanish folder must not change this driver's own probes for the rest of
            the process.
        tables: Whether a table's cells are read as their own blocks (off) or a
            table row is joined across its columns (on). It changes what a row
            *means*, so it is never defaulted silently at a call site.

    Returns:
        The attempt, carrying the `ReadResult` or the refusal.

    """
    label = f"ocr.read[{path.suffix.lstrip('.')}]"
    return _lib.run(
        label,
        engine.read,
        path,
        parse_pages(written),
        BOX_DPI,
        lang,
        tables=tables,
        expect=expect,
    )


def page_count(engine: DoclingEngine, path: pathlib.Path) -> int:
    """Report how many pages the engine converted.

    Read out of a `read` of page 1 rather than counted here: K4 is the only layer
    that knows, and its own `pages_requested` is the document's length when the
    selection is a single page. A count invented in this bench would disagree with
    the validator the adapter already applies.

    Args:
        engine: The K4 adapter.
        path: The document to measure.

    Returns:
        The page count, or ``0`` when the document could not be read - which a
        caller must read as *unmeasured*, never as *a document with no pages*.

    """
    attempt = _lib.run(
        f"ocr.probe[{path.suffix.lstrip('.')}]",
        engine.read,
        path,
        [1],
        BOX_DPI,
        LANG,
        tables=False,
    )
    if not attempt.succeeded:
        return 0
    return len(attempt.result.value.pages_requested)


def layout_rows(
    engine: DoclingEngine,
    path: pathlib.Path,
    written: str,
    expect: str = "ok",
    *,
    lang: str = LANG,
    tables: bool = False,
    save: bool = True,
) -> _lib.Attempt:
    """Read a page range and order the engine's blocks into rows, and save it.

    This is the operation that satisfies the requirement - it is the text **with its
    layout**, as opposed to `read`'s unordered tokens.

    **A blank page inside the range is skipped in silence, and that is measured.**
    `layout` raises `blank_page` only when *every* page in the selection is blank:
    `layout 1-3` on the fixture whose page 2 is blank returns 680 characters and says
    nothing about page 2, while `layout 2,3` returns 382. So the range operation
    cannot report which of its pages carried text - a per-page census needs `read`,
    which reports `page_status` for each page it was asked about.

    Returns the attempt rather than nothing, so a batch caller reuses this call's
    text instead of reading the page twice - and on this kernel a second read is
    another ~1.5 s warm, ~10 s if the ONNX models are not yet loaded.

    Args:
        engine: The K4 adapter.
        path: The document to read.
        written: The selection as a caller writes it, in `kernel-cli.md` §9's
            grammar - the same text `--pages` accepts.
        expect: The bucket this probe is declared to land in.
        lang: The language hint passed to the engine; see `read_text`.
        tables: Whether a table's row is joined across its columns. Off means a
            table's cells are blocks in reading order; on means a row reads the way
            a line reads across a page. A caller comparing two runs without knowing
            which is which is comparing two different statements.
        save: Whether to write the text under the driver's output root. A batch
            caller passes ``False``: it writes into its mirrored tree, and this
            flat copy would be a file nothing pairs with a document.

    Returns:
        The attempt, carrying the layout text or the refusal.

    """
    label = f"ocr.layout[{path.suffix.lstrip('.')}]"
    attempt = _lib.run(
        label,
        engine.layout,
        path,
        parse_pages(written),
        BOX_DPI,
        lang,
        line_tolerance=LINE_TOLERANCE,
        tables=tables,
        expect=expect,
    )
    if not attempt.succeeded:
        return attempt

    text = attempt.result.value
    rows = [row for row in text.splitlines() if row.strip()]
    print(f"         {len(rows)} rows, {len(text)} chars")
    if rows:
        print(f"         first row: {rows[0][:70]!r}")
    if save:
        written_to = _lib.save_text(f"{path.stem}-p{written}.ocr-layout.txt", text)
        print(f"         wrote {_lib.shown(written_to)}")
    return attempt


def read_in_quiet(engine: DoclingEngine, path: pathlib.Path) -> _lib.Attempt:
    """Read page 1 with the engine's own logging and this bench's probes silenced.

    K4's RapidOCR banner prints on **every** call, from inside a library this bench
    does not own, and a batch prints one line per file: the banner plus the probe's
    own report would bury it. The redirect is here rather than in the batch drivers
    because it is a property of *this kernel* - `_mirror.silently` hides the probe
    line, and only K4 needs stdout captured on top of that.

    TODO: [MVP] Redirecting a library's logging through stdout is a workaround for a
    dependency that logs unconditionally. When the adapter can quieten its engine,
    this helper goes away.

    Args:
        engine: The K4 adapter.
        path: The document to read.

    Returns:
        The attempt, as `read_text` would return it.

    """
    import contextlib
    import io

    sink = io.StringIO()
    with contextlib.redirect_stdout(sink):
        outcome = read_text(engine, path, "1", "ok")

    if outcome.succeeded:
        # The probe's own line was swallowed with the banner, so the measurement is
        # reported here - a probe that prints nothing reports nothing.
        result = outcome.result.value
        statuses = status_values(result.page_status)
        print(
            f"         requested={list(result.pages_requested)} "
            f"read={list(result.pages_read)} status={statuses} "
            f"tokens={len(result.tokens)}"
        )
    return outcome


def status_values(status: Any) -> dict[str, str]:
    """Render a page-status mapping as the words a person reads.

    `PageStatus` is a `str` enum, so `.value` is the word and `str(status)` would
    print `PageStatus.READ` - the exact mistake `commands/ocr.py::_described`
    documents and avoids. One helper so a probe and a batch cannot disagree about
    how a status is spelled.

    Args:
        status: The engine's per-page status mapping.

    Returns:
        A mapping of page number, as a string, to the status word.

    """
    return {str(page): value.value for page, value in status.items()}


def layout_with_tables(
    engine: DoclingEngine, path: pathlib.Path, written: str, expect: str
) -> None:
    """Order the blocks into rows **including** a table's cells.

    Kept separate from `layout_rows` because `tables` changes what a row means: off,
    a table's cells are blocks in reading order; on, a table's row reads across its
    columns the way a line reads across a page. A caller that compared two runs
    without knowing which was which would be comparing two different statements.

    Args:
        engine: The K4 adapter.
        path: The document to read.
        written: The selection as a caller writes it.
        expect: The bucket this probe is declared to land in.

    """
    attempt = _lib.run(
        f"ocr.layout[tables,{path.suffix.lstrip('.')}]",
        engine.layout,
        path,
        parse_pages(written),
        BOX_DPI,
        LANG,
        line_tolerance=LINE_TOLERANCE,
        tables=True,
        expect=expect,
    )
    if not attempt.succeeded:
        return

    rows = [row for row in attempt.result.value.splitlines() if row.strip()]
    print(f"         {len(rows)} rows with table cells joined")


def compare_read_and_layout(
    engine: DoclingEngine, path: pathlib.Path, written: str
) -> None:
    """Run both orderings of the same page and print the difference.

    This is the probe that answers the flow's requirement directly: the same page,
    through the two operations, side by side. `read` reports the order as unresolved
    by design; `layout` is the one that orders.

    **It also shows the one thing `layout` cannot report**: a per-page census. On a
    range, `layout` returns the text its pages held and names no page, while `read`
    returns `page_status` for every page it was asked about - including the ones it
    found blank. That is why a batch that must account for each page needs `read`
    even though `layout` is the operation the requirement asks for.

    Args:
        engine: The K4 adapter.
        path: The document to read.
        written: The selection as a caller writes it.

    """
    read = _lib.run(
        "ocr.requirement/read",
        engine.read,
        path,
        parse_pages(written),
        BOX_DPI,
        LANG,
        tables=False,
    )
    laid = _lib.run(
        "ocr.requirement/layout",
        engine.layout,
        path,
        parse_pages(written),
        BOX_DPI,
        LANG,
        line_tolerance=LINE_TOLERANCE,
        tables=False,
    )

    if read.succeeded:
        observed = read.result.evidence.observed
        statuses = status_values(read.result.value.page_status)
        print(
            f"         read:   reading_order={observed.get('reading_order')!r} "
            f"layout_dropped={observed.get('layout_dropped')!r} status={statuses}"
        )
    if laid.succeeded:
        written_to = _lib.save_text(
            f"{path.stem}-p{written}.requirement.txt", laid.result.value
        )
        print(f"         layout: ordered rows -> {_lib.shown(written_to)}")

    _lib.note(
        "ocr.requirement",
        "'layout' satisfies it; 'read' reports the order as not_resolved by design, "
        "and is the one that reports a status per page",
    )


def blank_page(engine: DoclingEngine, path: pathlib.Path, expect: str) -> _lib.Attempt:
    """Read a page that carries nothing and confirm it is a statement, not an error.

    A blank page keeps ``"blank"`` in `page_status` and contributes no token. It is
    a legitimate answer (exit 0 through the CLI), not a failure - and the distinction
    is what keeps a genuinely empty page from reading as a page of invented text.

    Measured: `blank` is what the engine answers for a white page, a black one and a
    1x1 pixel alike, and `unreadable` is in the vocabulary but was not reachable from
    any of them - so a caller must not assume a page that failed to yield text is
    reported as *unreadable* rather than *blank*.

    Args:
        engine: The K4 adapter.
        path: The blank image to read.
        expect: The bucket this probe is declared to land in.

    Returns:
        The attempt, so a caller can reuse the reading.

    """
    attempt = _lib.run(
        "ocr.read[blank]",
        engine.read,
        path,
        [1],
        BOX_DPI,
        LANG,
        tables=False,
        expect=expect,
    )
    if not attempt.succeeded:
        return attempt

    result = attempt.result.value
    statuses = status_values(result.page_status)
    print(f"         status={statuses} tokens={len(result.tokens)}")
    return attempt


# --- The run ----------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Run every `ocr` probe and tally the result.

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
        help="where the extracted text is written",
    )
    args = parser.parse_args(argv)

    _lib.set_out(args.out)
    _lib.reset()
    engine = _engine()

    print(f"dpi={BOX_DPI} lang={LANG!r} line_tolerance={LINE_TOLERANCE:g}")
    print(f"out = {args.out}")
    print()

    report_capabilities(engine, "ok")

    print()
    # The requirement. An image, and the page range the fixtures have.
    read_text(engine, _lib.CASE_IMAGE, PAGES_AS_WRITTEN)
    layout_rows(engine, _lib.CASE_IMAGE, PAGES_AS_WRITTEN)
    layout_with_tables(engine, _lib.SOURCE_PDF, PAGES_AS_WRITTEN, "ok")

    print()
    # A page the document does not have. K4 validates the selection against the
    # document it converts, so this is its own `ValueError` - the library's
    # equivalent of exit 4 - and the bench reports it rather than crashing.
    read_text(engine, _lib.CASE_IMAGE, MISSING_PAGE, "usage")

    print()
    compare_read_and_layout(engine, _lib.CASE_IMAGE, PAGES_AS_WRITTEN)

    print()
    # A blank page: an answer, not a failure. Generated rather than committed,
    # because a white rectangle is not worth 4 KB in the repository - and a fixture
    # that is generated here cannot drift from what this probe expects.
    blank = _lib.out_dir() / "blank.png"
    _write_blank_png(blank)
    blank_page(engine, blank, "ok")

    print()
    return _lib.summary()


def _write_blank_png(path: pathlib.Path) -> None:
    """Write a 600x800 white PNG, using the same library the adapter does.

    Pillow is a declared dependency of the image adapter and is installed wherever
    the probes run, so reaching for it here adds no dependency of its own.

    Args:
        path: Where to write the image.

    """
    # Deferred like the adapter's own vendor import, so importing this module does
    # not require Pillow to be present for a probe that never writes a blank page.
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (600, 800), "white").save(path)


if __name__ == "__main__":
    sys.exit(main())
