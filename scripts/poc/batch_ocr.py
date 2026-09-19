"""The OCR-only batch walk: a folder of images in, a mirrored tree of text out.

`my_kernel_flow.md` §3, applied to a folder:

> take an image and extract its text **to a file, preserving the layout as far as
> possible**.

Images only
-----------

§3's input is an **image**, and this driver takes it literally: the walk covers
`_mirror.IMAGE_SUFFIXES` and nothing else. A `.pdf` is **not walked** - silently, the
same way `batch_image.py` declines one - because the caller chose the scope, and a
PDF's route to OCR is `batch_pdf.py`'s question: it is the driver that decides the
route *per page* and renders the bitmap this one would then read. Handing a PDF here
would read page 1 of it and report it as the whole document.

This is the step `batch.py` runs *inside* a larger chain and the one no other driver
isolates: `batch.py` reaches K4 only for the pages `pdf.route_page` sent it, and then
goes on to a model; `batch_pdf.py` stops before OCR entirely. Neither answers *what
does this folder of images read as* - and that is the question a corpus of 11k
documents (`prd.md`) has to be asked before anything downstream can be built on it.

Why a driver of its own
-----------------------

OCR is the expensive, non-deterministic step: ~1.5 s per call warm and ~10 s for the
first call in a process, against a deterministic classification that costs
milliseconds. A walk that reads a folder and stops there is how the reading is
inspected **on its own** - before a model, before a verdict - and it is the only way
to see what the recogniser produced rather than what a pipeline did with it.

**This is not K1.** Like `batch.py`, it composes the adapter for one walk of a
folder: no ledger, no cache key, no `pause`/`resume`. What it *does* have is a
resume journal (`_mirror.Resume`): a file already read by this driver under these
settings is skipped, so a walk killed at document 8 000 does not pay for ONNX again
on the first 7 999. That is not the same thing as K1 - there is no stage graph, no
per-stage key and no derived manifest, and `--redo` throws the journal away.

One image is one read, and the read answers for its single page
---------------------------------------------------------------

K4's `read` takes a page range and reports, **per page**, whether that page was read
or found blank. An image is one page, and the engine says so itself - measured,
`pages_requested` is `(1,)` and `page_status` is `{'1': 'read'}` for a `.jpeg`. So the
file is the unit of work and that one page is the unit of the answer:

| Step | Operation | What it gives |
|---|---|---|
| read | `read` | `page_status` for every page asked about, and the tokens |
| order | `layout` | the text with its rows preserved - the flow's requirement |

Both run, and that is a decision rather than belt-and-braces:

- **`layout` is the operation the flow asks for.** It is the text with its physical
  arrangement, and it is **not** on `OcrEngine` (`plans/README.md` §3 freezes the
  port's three operations), so it is reached on the adapter.
- **`read` is the only one that can account for a page.** Measured: `layout 1-3` on
  the fixture whose page 2 is blank returns 680 characters and says nothing about
  page 2 - `blank_page` is raised only when *every* page in the selection is blank.
  A census built on `layout` alone would silently drop the blank pages, which is
  precisely the loss this project exists to make visible.

One text file per image, not per page
-------------------------------------

`layout` returns a single string for the whole selection and names no page inside it,
so a per-page split would be a guess. Measured: `ocr.SEPARATOR` is the **row**
separator (`" | "`), so splitting on it would cut rows rather than pages. The
selection therefore lands in one `<stem>-p<selection>.txt`, and the per-page facts
live in `<stem>.ocr.json`, which is built from `read` and knows each page's status and
token count - for an image, the one page it is.

What each file becomes
----------------------

| Engine's word | Meaning | Output at the mirrored path |
|---|---|---|
| `read` | the page carried text | the image's `.txt`, plus its status in the record |
| `blank` | the page carried nothing | nothing; the page is recorded as blank |
| `unreadable` | part of the vocabulary | nothing; recorded, and the run says so |
| refused | the file could not be read at all | `.skipped.json` naming the reason |

`blank` is **not** a failure. It is the engine's statement that a page carries no
text - the distinction between *nothing was there* and *the reading produced nothing*,
which is what the previous system's silent failures were made of. It gets a record,
not a file: an empty `.txt` is indistinguishable from a read that produced nothing.

`unreadable` is in `PageStatus` but was **not reachable** from any input tried - a
white page, a black one and a 1x1 pixel all answer `blank`, and a text file renamed
`.png` is refused before any page exists. A caller must not assume a page that yielded
no text was reported as `unreadable` rather than `blank`.

The engine logs, and this driver does not own them
--------------------------------------------------

`RapidOCR` prints a banner to **stdout** on every call, from inside a library no layer
here controls. It is emitted by the adapter's own engine rather than by `_lib`'s probe
line, so `_mirror.silently` does not catch it: a run shows several engine lines per
file. `ocr.read_in_quiet` captures them, and the reading is printed again afterwards
so the measurement is not lost with the banner.

TODO: [MVP] Silencing a dependency belongs in the adapter that owns it. When it can
quieten its engine, the helper goes away.

Run it:

    python scripts/poc/batch_ocr.py <input-dir> [--out DIR] [--pages SEL] [--lang L]

Examples:

    python scripts/poc/batch_ocr.py tests/fixtures/otros
    python scripts/poc/batch_ocr.py /tmp/imagenes --lang es --out /tmp/ocr-out
"""

from __future__ import annotations

import dataclasses
import json
import pathlib
import sys

import _lib
import _mirror

# The ordering is load-bearing, exactly as in every other driver here: `_lib` puts
# `src/` on `sys.path`, and `ocr` is imported so this module reuses its helpers
# instead of re-implementing them. `pyproject.toml`'s `pythonpath = ["src"]` applies
# to pytest alone.
_lib.bootstrap()

import ocr as ocr_driver  # noqa: E402 - see the note above

from docflow.adapters.docling import DoclingEngine  # noqa: E402 - see the note above

__all__: list[str] = []


@dataclasses.dataclass(frozen=True, slots=True)
class PageOutcome:
    """What the engine said about one page.

    Attributes:
        number: One-based page number.
        status: The engine's word for the page - ``"read"``, ``"blank"`` or
            ``"unreadable"``.
        tokens: How many tokens on that page the read returned.

    """

    number: int
    status: str
    tokens: int


@dataclasses.dataclass(frozen=True, slots=True)
class ScanOutcome:
    """What happened to one scanned image.

    Attributes:
        source: The file's path relative to the input root - also its mirrored
            location in the output.
        pages: One entry per page the engine answered for. An image is one page, so
            this is a one-element tuple in every reachable case - and empty when the
            read itself was refused.
        characters: How many characters the ordered text holds.
        artifact: The written text, relative to the output root, or ``None``.
        note: Why nothing was written, when nothing was.

    """

    source: str
    pages: tuple[PageOutcome, ...]
    characters: int
    artifact: str | None
    note: str = ""

    @property
    def read_pages(self) -> int:
        """How many pages the engine reported as read.

        Returns:
            The count. An image the engine found blank reports zero, which is a real
            answer rather than a failure.

        """
        return sum(1 for page in self.pages if page.status == "read")

    @property
    def statuses(self) -> dict[str, int]:
        """Tally the engine's per-page words.

        Returns:
            A count per status, so a run reports *two pages read, one blank* rather
            than a bare total that hides the blank one.

        """
        tally: dict[str, int] = {}
        for page in self.pages:
            tally[page.status] = tally.get(page.status, 0) + 1
        return tally


#: Every document outcome of this walk, in order.
OUTCOMES: list[ScanOutcome] = []


def _engine() -> DoclingEngine:
    """Build the K4 adapter.

    Returns:
        The engine, ready to call.

    """
    return ocr_driver._engine()


def read_pages(
    engine: DoclingEngine,
    source: pathlib.Path,
    written: str,
    *,
    lang: str,
) -> tuple[tuple[PageOutcome, ...], str]:
    """Ask the engine about every page of a selection, in one call.

    The whole selection goes in **one** `read`: the first call in a process pays for
    loading the ONNX models (~10 s), and a per-page call would not avoid that but
    would re-run detection once per page on the same document.

    The engine validates the range itself - it converts the document and compares
    against `len(document.pages)` - so a page outside it raises `ValueError` from
    inside the adapter. This reports it rather than adding a second validator that
    could disagree with the one the adapter already applies.

    Args:
        engine: The K4 adapter.
        source: The image to read.
        written: The selection as a caller writes it, in the `--pages` grammar.
        lang: The language hint passed to the engine.

    Returns:
        One `PageOutcome` per page the engine answered for, and a note explaining a
        refusal. The note is empty when the read happened.

    """
    attempt = _mirror.silently(
        ocr_driver.read_text, engine, source, written, "ok", lang=lang
    )
    if not attempt.succeeded:
        return (), f"read refused ({attempt.outcome.detail})"

    result = attempt.result.value
    per_page: dict[int, int] = {}
    for token in result.tokens:
        per_page[int(token.page)] = per_page.get(int(token.page), 0) + 1

    pages = tuple(
        PageOutcome(int(number), status, per_page.get(int(number), 0))
        for number, status in sorted(
            ocr_driver.status_values(result.page_status).items()
        )
    )
    return pages, ""


def process_document(
    engine: DoclingEngine,
    source: pathlib.Path,
    root: pathlib.Path,
    out_root: pathlib.Path,
    *,
    selection: str | None,
    lang: str,
    save: bool,
) -> ScanOutcome:
    """Read one scanned image and write its ordered text.

    Args:
        engine: The K4 adapter.
        source: The image to read.
        root: The input root.
        out_root: The output root.
        selection: Which pages to read, in the `--pages` grammar, or ``None`` for
            page 1 - one page is read when the caller has not said how long the
            document is, and ``all`` is available when they have.
        lang: The language hint passed to the engine.
        save: Whether to write the text.

    Returns:
        What happened to the document, with one entry per page the engine answered
        for.

    """
    relative = _mirror.relative_to(source, root)
    mirror_dir = out_root / pathlib.Path(relative).parent
    mirror_dir.mkdir(parents=True, exist_ok=True)

    chosen = selection if selection is not None else "1"

    pages, note = read_pages(engine, source, chosen, lang=lang)
    if not pages:
        _mirror.write_skipped(mirror_dir, source.stem, "ocr", note)
        return ScanOutcome(relative, (), 0, None, note)

    # `layout` answers the flow's requirement - the text with its rows - in one call
    # for the whole selection. It names no page, which is why `read` ran first: the
    # statuses above are the census, and this is the text.
    laid = _mirror.silently(
        ocr_driver.layout_rows, engine, source, chosen, "ok", lang=lang, save=False
    )

    artifact: str | None = None
    if save:
        if laid.succeeded:
            target = mirror_dir / f"{source.stem}-p{page_token(chosen)}.txt"
            target.write_text(laid.result.value, encoding="utf-8")
            artifact = _mirror.relative_to(target, out_root)
        else:
            note = laid.outcome.detail

    outcome = ScanOutcome(
        relative,
        pages,
        len(laid.result.value) if laid.succeeded else 0,
        artifact,
        note,
    )
    if save:
        _write_record(outcome, mirror_dir, source.stem)
    return outcome


def page_token(written: str) -> str:
    """Render a page selection as a filename-safe token.

    The same discipline as `pdf.py`'s `page_token`, and it keeps the *shape* of the
    request rather than its expansion: ``1-3`` stays ``1-3``, so a name says which
    range produced it without spelling out fifty numbers.

    Args:
        written: The selection as the caller wrote it.

    Returns:
        The selection with its separators collapsed to ``-``.

    """
    return written.strip().replace(",", "-").replace(" ", "")


def _write_record(
    outcome: ScanOutcome, mirror_dir: pathlib.Path, stem: str
) -> pathlib.Path:
    """Record what the engine said about each page.

    The text alone says *there is a file for this selection*; it does not say that
    page 5 was blank, nor how many tokens each page contributed. The record makes the
    reading a file a pipeline can audit instead of a console line that scrolls away -
    and it is the only place a blank page survives at all, since a blank page has no
    text and therefore no `.txt`.

    It is named `<stem>.ocr.json` and not `<stem>.json`: that name means *these are
    the extracted fields* (`batch.py`'s contract), and a consumer globbing for
    `.json` would read a reading record as an extraction.

    Args:
        outcome: The document's outcome.
        mirror_dir: The directory the document mirrors into.
        stem: The document's stem.

    Returns:
        The path written.

    """
    record = {
        "source": outcome.source,
        "pages": [
            {"number": page.number, "status": page.status, "tokens": page.tokens}
            for page in outcome.pages
        ],
        "statuses": outcome.statuses,
        "characters": outcome.characters,
        "artifact": outcome.artifact,
        "note": outcome.note,
    }
    target = mirror_dir / f"{stem}.ocr.json"
    target.write_text(
        json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return target


def process_file(
    engine: DoclingEngine,
    source: pathlib.Path,
    root: pathlib.Path,
    out_root: pathlib.Path,
    *,
    selection: str | None,
    lang: str,
    save: bool,
) -> ScanOutcome | None:
    """Process one input file, or report that K4 would not read it.

    Args:
        engine: The K4 adapter.
        source: The file to process.
        root: The input root.
        out_root: The output root.
        selection: Which pages to read, or ``None`` for page 1.
        lang: The language hint passed to the engine.
        save: Whether to write the text.

    Returns:
        The image's outcome, or ``None`` when the file is not an image - this driver
        reads images only (``my_kernel_flow.md`` §3), so a PDF is *not walked*
        rather than skipped-with-a-record: the caller chose the scope, and a PDF's
        route to OCR is `batch_pdf.py`'s per-page decision.

    """
    if _mirror.kind_of(source) != "image":
        return None
    return process_document(
        engine, source, root, out_root, selection=selection, lang=lang, save=save
    )


def main(argv: list[str] | None = None) -> int:
    """Walk a folder of images, read every one, and verify the mirrored tree.

    Args:
        argv: The command-line arguments, or ``None`` for `sys.argv`.

    Returns:
        The number of problems: mirrored-ness violations plus refused images, and
        **not** the skipped ones - a skip is a question already answered.

    """
    parser = _mirror.batch_parser(
        __doc__.splitlines()[0], _lib.DEFAULT_OUT / "batch_ocr"
    )
    parser.add_argument(
        "--pages",
        default=None,
        help="which pages to read, in the --pages grammar (default: page 1; an image "
        "has exactly one)",
    )
    parser.add_argument(
        "--lang",
        default=None,
        help=f"the language hint passed to the engine (default: {ocr_driver.LANG!r})",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="read every image without writing any text",
    )
    args = parser.parse_args(argv)

    root: pathlib.Path = args.input
    if not root.is_dir():
        parser.error(f"{root} is not a directory")

    out_root = args.out if args.out is not None else _lib.DEFAULT_OUT / "batch_ocr"
    save = not args.no_save
    _lib.set_out(out_root)
    _lib.reset()

    # The language is a property of the corpus and this driver is the caller that
    # knows which corpus it was pointed at, so it is resolved once here and passed
    # down as a parameter. Writing `ocr_driver.LANG` would change every later call in
    # the process, including another driver's own probes.
    lang = ocr_driver.LANG if args.lang is None else str(args.lang)

    directories = _mirror.mirror_directories(root, out_root)
    engine = _engine()

    # The signature covers everything that decides what a reading *means*. Change any
    # of it and a stored reading answers a different question, so the journal is
    # discarded rather than partially trusted.
    resume = _mirror.Resume.begin(
        out_root,
        "batch_ocr",
        redo=args.redo,
        engine="docling",
        lang=lang,
        pages=args.pages,
        dpi=72,
    )

    print(f"in  = {root}")
    print(f"out = {out_root}")
    print(f"lang = {lang!r}    pages = {args.pages or '1'}    save = {save}")
    print("the first read loads ONNX models (~10 s); calls after it are ~1.5 s")
    print()

    files = list(_mirror.walk(root))
    images = [path for path in files if _mirror.kind_of(path) == "image"]
    # Declared, never silent: a folder of PDFs produces no output at all, and a run
    # that said nothing would read as a broken driver rather than as a scope decision.
    declined = [path for path in files if _mirror.kind_of(path) in {"pdf", "invalid"}]
    for source in images:
        relative = _mirror.relative_to(source, root)
        digest = _mirror.digest_of(source)
        if resume.is_done(relative, digest):
            print(f" == {relative:40} skipped: already read by this driver")
            continue

        outcome = process_file(
            engine, source, root, out_root, selection=args.pages, lang=lang, save=save
        )
        if outcome is None:
            continue
        OUTCOMES.append(outcome)

        # Only a reading that produced text is recorded. A refusal is retried next
        # time: `blank` and an unreadable file can both change, and recording them
        # would turn a transient condition into a permanent one.
        if save and outcome.pages:
            resume.record(relative, digest, artifact=outcome.artifact)
            resume.flush_if_due()

        if outcome.pages:
            statuses = " ".join(
                f"{key}={value}" for key, value in outcome.statuses.items()
            )
            print(
                f" ok {outcome.source:40} {len(outcome.pages):>3} page(s)  "
                f"{outcome.characters:>6} chars  read {outcome.read_pages:<3} "
                f"{statuses}"
            )
        else:
            print(f" -- {outcome.source:40} {outcome.note}")
        if outcome.note and outcome.pages:
            print(f"      {outcome.note}")

    print()
    if declined:
        print(
            f"{len(declined)} file(s) declined: this driver reads images only - a PDF "
            "is walked by batch_pdf.py, which routes it per page"
        )
    # Only the files this driver walks: a `.md` in the input tree is outside an OCR
    # driver's scope, and reporting it as a violation would blame this run for a file
    # it was never asked about.
    problems = _mirror.verify_mirror_for(root, out_root, images)
    _mirror.report_mirror(problems, len(images), directories, "image")

    print()
    print(f"{'page status':<14}{'pages':>6}")
    census: dict[str, int] = {}
    for outcome in OUTCOMES:
        for key, value in outcome.statuses.items():
            census[key] = census.get(key, 0) + value
    for key in sorted(census):
        print(f"{key:<14}{census[key]:>6}")
    if not census:
        print(f"{'(no pages)':<14}{0:>6}")

    written = sum(1 for outcome in OUTCOMES if outcome.artifact is not None)
    print(f"{'written':<14}{written:>6}")
    print()

    # An image the engine answered *blank* about was read successfully and answered
    # the question - an empty page is a statement, not an error. Only an unreadable
    # image is a problem, and that is a fact about the file.
    refused = [outcome for outcome in OUTCOMES if not outcome.pages]
    silent = [
        outcome for outcome in OUTCOMES if outcome.pages and outcome.artifact is None
    ]
    written = sum(1 for outcome in OUTCOMES if outcome.artifact is not None)
    print(f"{len(images)} image(s) walked, {written} text file(s) written.")
    if resume.reused:
        print(f"{resume.reused} image(s) skipped as already processed.")
    if silent:
        print(
            f"{len(silent)} image(s) yielded no text; each page's status is recorded."
        )
    if refused:
        print(f"{len(refused)} image(s) could not be read; see the notes above.")
    if not problems and not refused:
        print("every image was walked and the tree mirrors exactly.")
        resume.flush(save)
        return 0
    resume.flush(save)
    return len(problems) + len(refused)


if __name__ == "__main__":
    sys.exit(main())
