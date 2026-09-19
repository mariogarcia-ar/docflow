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

import _lib

# `docflow` is only importable once `src/` is on the path; see `pdf.py` for why
# the ordering of these two imports is load-bearing.
_lib.bootstrap()

from docflow.adapters.docling import DoclingEngine  # noqa: E402 - see the note above

__all__: list[str] = []

#: The resolution the returned boxes are expressed in. Docling measures in points
#: at 72 DPI, so 72 is the scale that changes nothing.
BOX_DPI: int = 72

#: The language hint. The port requires it, so a caller has to name something.
LANG: str = "en"

#: How far apart two tokens may sit and still share a row, **in the boxes' units at
#: `BOX_DPI`**. Required by `layout`, with no default, because the legacy's `25.0`
#: was in PDF points and a constant in the adapter could not express that.
LINE_TOLERANCE: float = 25.0 * BOX_DPI / 72.0


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
    engine: DoclingEngine, path: pathlib.Path, pages: list[int], expect: str
) -> None:
    """Read a page range and report the tokens **without** a resolved order.

    Args:
        engine: The K4 adapter.
        path: The document to read.
        pages: The one-based page numbers to read.
        expect: The bucket this probe is declared to land in.

    """
    label = f"ocr.read[{path.suffix.lstrip('.')}]"
    attempt = _lib.run(
        label, engine.read, path, pages, BOX_DPI, LANG, tables=False, expect=expect
    )
    if not attempt.succeeded:
        return

    result = attempt.result.value
    # `PageStatus` is a `str` enum, so `.value` is the word a person reads. Using
    # `str(status)` would print `PageStatus.READ` - the exact mistake
    # `commands/ocr.py::_described` documents and avoids.
    statuses = {str(page): status.value for page, status in result.page_status.items()}
    print(
        f"         requested={list(result.pages_requested)} read={list(result.pages_read)} "
        f"status={statuses} tokens={len(result.tokens)}"
    )
    if result.tokens:
        first = result.tokens[0]
        print(
            f"         first token: {first.text[:40]!r} role={first.role!r} "
            f"confidence={first.confidence}"
        )


def layout_rows(
    engine: DoclingEngine, path: pathlib.Path, pages: list[int], expect: str
) -> None:
    """Read a page range and order the engine's blocks into rows, then save it.

    This is the operation that satisfies the requirement - it is the text **with its
    layout**, as opposed to `read`'s unordered tokens.

    Args:
        engine: The K4 adapter.
        path: The document to read.
        pages: The one-based page numbers to read.
        expect: The bucket this probe is declared to land in.

    """
    label = f"ocr.layout[{path.suffix.lstrip('.')}]"
    attempt = _lib.run(
        label,
        engine.layout,
        path,
        pages,
        BOX_DPI,
        LANG,
        line_tolerance=LINE_TOLERANCE,
        tables=False,
        expect=expect,
    )
    if not attempt.succeeded:
        return

    text = attempt.result.value
    written = _lib.save_text(f"{path.stem}-p{pages[0]}.ocr-layout.txt", text)
    rows = [row for row in text.splitlines() if row.strip()]
    print(
        f"         {len(rows)} rows, {len(text)} chars -> {written.relative_to(_lib.ROOT)}"
    )
    if rows:
        print(f"         first row: {rows[0][:70]!r}")


def layout_with_tables(
    engine: DoclingEngine, path: pathlib.Path, pages: list[int], expect: str
) -> None:
    """Order the blocks into rows **including** a table's cells.

    Kept separate from `layout_rows` because `tables` changes what a row means: off,
    a table's cells are blocks in reading order; on, a table's row reads across its
    columns the way a line reads across a page. A caller that compared two runs
    without knowing which was which would be comparing two different statements.

    Args:
        engine: The K4 adapter.
        path: The document to read.
        pages: The one-based page numbers to read.
        expect: The bucket this probe is declared to land in.

    """
    attempt = _lib.run(
        f"ocr.layout[tables,{path.suffix.lstrip('.')}]",
        engine.layout,
        path,
        pages,
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
    engine: DoclingEngine, path: pathlib.Path, pages: list[int]
) -> None:
    """Run both orderings of the same page and print the difference.

    This is the probe that answers the flow's requirement directly: the same page,
    through the two operations, side by side. `read` reports the order as unresolved
    by design; `layout` is the one that orders.

    Args:
        engine: The K4 adapter.
        path: The document to read.
        pages: The one-based page numbers to read.

    """
    read = _lib.run(
        "ocr.requirement/read", engine.read, path, pages, BOX_DPI, LANG, tables=False
    )
    laid = _lib.run(
        "ocr.requirement/layout",
        engine.layout,
        path,
        pages,
        BOX_DPI,
        LANG,
        line_tolerance=LINE_TOLERANCE,
        tables=False,
    )

    if read.succeeded:
        observed = read.result.evidence.observed
        print(
            f"         read:   reading_order={observed.get('reading_order')!r} "
            f"layout_dropped={observed.get('layout_dropped')!r}"
        )
    if laid.succeeded:
        written = _lib.save_text(
            f"{path.stem}-p{pages[0]}.requirement.txt", laid.result.value
        )
        print(f"         layout: ordered rows -> {written.relative_to(_lib.ROOT)}")

    _lib.note(
        "ocr.requirement",
        "'layout' satisfies it; 'read' reports the order as not_resolved by design",
    )


def blank_page(engine: DoclingEngine, path: pathlib.Path, expect: str) -> None:
    """Read a page that carries nothing and confirm it is a statement, not an error.

    A blank page keeps ``"blank"`` in `page_status` and contributes no token. It is
    a legitimate answer (exit 0 through the CLI), not a failure - and the distinction
    is what keeps a genuinely empty page from reading as a page of invented text.

    Args:
        engine: The K4 adapter.
        path: The blank image to read.
        expect: The bucket this probe is declared to land in.

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
        return

    result = attempt.result.value
    statuses = {str(page): status.value for page, status in result.page_status.items()}
    print(f"         status={statuses} tokens={len(result.tokens)}")


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
    read_text(engine, _lib.CASE_IMAGE, [1], "ok")
    layout_rows(engine, _lib.CASE_IMAGE, [1], "ok")
    layout_with_tables(engine, _lib.SOURCE_PDF, [1], "ok")

    print()
    compare_read_and_layout(engine, _lib.CASE_IMAGE, [1])

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
