"""The PDF-only batch walk: a folder of PDFs in, a mirrored tree of text and pages out.

`my_kernel_flow.md` §1, applied to a folder:

> cut the PDF into pages, decide whether a page is predominantly text or image,
> text -> extract it and save it to a file, image -> export the page as an image,
> for OCR afterwards.

This is `batch.py` §6 with everything from K3 onward taken out. No OCR, no local
model, no field extraction - the walk stops where the flow's first kernel stops, and
what it produces is the **material** a later stage reads: a `.txt` per text page and
a `.png` per image page, at the same relative paths as the input.

Why a driver of its own, rather than a flag on `batch.py`
--------------------------------------------------------

Because the two answer different questions. `batch.py` asks *"what fields does this
corpus hold"* and its answer costs an ONNX load per document and a generation per
document. This asks *"what does this corpus consist of"* - how many pages are text,
how many are scans, how many are blank - and its answer costs one `classify` per
page. Running the first to get the second is minutes of work to obtain a page
tally, and it is unusable on the 11k-document corpus (`prd.md`) for exactly that
reason.

**This is not K1.** Like `batch.py`, it composes the adapters for one walk of a
folder: no ledger, no cache key, no `pause`/`resume`, and re-running re-does the
work. "Batch" names the shape of the run, not the orchestrator.

Per page, not per document
--------------------------

`batch.py` classifies page 1 and applies that answer to the whole document,
because §6 is about a document's fields. Here the unit is the **page**, and the
difference is not cosmetic: the large fixture has 59 pages of which **2 report
`blank_page`** while the rest carry text, so a per-document decision would route
those two to the renderer and export three pageless bitmaps. Measured: a range
containing page 2 is *not* refused by either operation - `layout_text 1-3` returns
1263 characters and `render 1-3` returns 208 761 bytes - so a range operation
cannot be asked "is this range text or image" and the granularity has to be the
page.

One route per page, and the file says which
-------------------------------------------

A page's shape decides what it becomes:

| Shape | Route | Output at the mirrored path |
|---|---|---|
| `text`, `mixed` | `layout_text` | `<stem>-pN.txt` |
| `image` | `render` | `<stem>-pN.png`, for K4 |
| `blank` | none | nothing; reported in the summary |

`blank` is **not** exported. It is the kernel's own statement that a page carries
neither usable text nor an image, so rendering it would write a bitmap of nothing
and hand it to OCR to read nothing - work whose result is known before it is done.
The page is still *accounted for*: the per-document `<stem>.pages.json` records it.

The routing itself is not implemented here. It is `pdf.route_page`, the one place a
measured shape becomes an operation, because a second copy of that table is how a
batch starts routing scans to a text reader.

Run it:

    python scripts/poc/batch_pdf.py <input-dir> [--out DIR] [--pages SEL] [--dpi N]

Examples:

    python scripts/poc/batch_pdf.py tests/fixtures/pdf_escaneados
    python scripts/poc/batch_pdf.py documentos --out /tmp/docflow --pages 1-3
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import sys
from typing import Final

import _lib
import _mirror

# The ordering is load-bearing, exactly as in every other driver here: `_lib`
# puts `src/` on `sys.path`, and `pdf` is imported so this module reuses its
# helpers instead of re-implementing them. `pyproject.toml`'s `pythonpath = ["src"]`
# applies to pytest alone.
_lib.bootstrap()

import pdf as pdf_driver  # noqa: E402 - see the note above

from docflow.adapters.pdf import PdfEngine  # noqa: E402 - see the note above
from docflow.kernel_cli.commands.pages import parse_pages  # noqa: E402

__all__: list[str] = []

#: The resolution an exported page is rendered at, read from the registry at run
#: time (`diagnosis.min_dpi`, `ADR-009`) rather than pinned here. Exporting a page
#: is the step whose whole purpose is to hand K4 pixels, so a resolution below the
#: corpus's declared floor would produce an image the pipeline has already decided
#: is too thin to read - and a hardcoded number would disagree with the registry
#: the moment someone changed it.
#:
#: `pdf.py`'s own `RENDER_DPI` (72) is deliberately **not** reused: that bench
#: measures the adapter at 1:1 with PDF user units, while this driver produces
#: material for OCR. Two purposes, two numbers, each named.
MIN_DPI_KEY: Final[str] = "diagnosis.min_dpi"


@dataclasses.dataclass(frozen=True, slots=True)
class PageOutcome:
    """What happened to one page.

    Attributes:
        number: One-based page number.
        shape: What `classify` measured, or ``""`` when it was refused.
        route: The operation asked, or ``None`` when nothing was asked.
        artifact: The written file, relative to the output root, or ``None`` for a
            blank page or a refusal.
        note: A short explanation, for the refused cases.

    """

    number: int
    shape: str
    route: str | None
    artifact: str | None
    note: str = ""


@dataclasses.dataclass(frozen=True, slots=True)
class DocumentOutcome:
    """What happened to one PDF.

    Attributes:
        source: The file's path relative to the input root - also its mirrored
            location in the output.
        pages: One entry per page, in document order.
        note: Why the document produced nothing, when it did not.

    """

    source: str
    pages: tuple[PageOutcome, ...]
    note: str = ""

    @property
    def produced(self) -> int:
        """How many pages produced an artifact.

        Returns:
            The count, blank pages and refusals excluded.

        """
        return sum(1 for page in self.pages if page.artifact is not None)

    @property
    def shapes(self) -> dict[str, int]:
        """Tally the measured shapes across the document's pages.

        Returns:
            A count per shape, with ``"refused"`` for a page that could not be
            measured - named rather than dropped, so the tally always accounts for
            every page the document has.

        """
        tally: dict[str, int] = {}
        for page in self.pages:
            key = page.shape or "refused"
            tally[key] = tally.get(key, 0) + 1
        return tally


#: Every document outcome of this walk, in order.
OUTCOMES: list[DocumentOutcome] = []


def _engine() -> PdfEngine:
    """Build the K2 adapter with the registry's threshold.

    Returns:
        The engine, ready to call.

    """
    return pdf_driver._engine()


def _render_dpi() -> int:
    """Read the resolution an exported page is rendered at, from the registry.

    Returns:
        The corpus's declared minimum readable resolution.

    """
    return int(_lib.policy(MIN_DPI_KEY))


def _export_dpi(engine: PdfEngine, source: pathlib.Path, page: int) -> int:
    """Decide what resolution a page is exported at, within what its pixels hold.

    The registry's floor is the *target*, and the page's own measured resolution is
    the *ceiling*: the adapter refuses to upscale (`kernel-cli.md` §11 row 4), and
    that refusal is correct - an upscaled page is larger and no more legible. So
    asking for 150 DPI on a 120 DPI scan does not produce a bigger file, it produces
    **no file**, which is the one outcome this driver must not have: the page it was
    asked to export for OCR is the page that most needs exporting.

    Measured on the committed scan fixture: `render @120` returns 165 960 bytes and
    `render @150` is refused `insufficient_effective_resolution`. So the floor is
    applied as a target and capped by the measurement, and the two are recorded
    separately - *what the corpus asks for* and *what this page could give* - rather
    than one number hiding the other.

    Args:
        engine: The K2 adapter.
        source: The PDF being exported.
        page: One-based page number.

    Returns:
        The registry's floor, or the page's measured resolution when that is lower.
        When the measurement itself is refused, the floor is returned unchanged: the
        render's own refusal is a better answer than a resolution invented here.

    """
    measured = _mirror.silently(engine.effective_dpi, source, page)
    if measured.value is None:
        return _render_dpi()

    held = measured.evidence.measurements.get("effective_dpi")
    if held is None:
        return _render_dpi()
    return max(1, min(_render_dpi(), int(held)))


def process_page(
    engine: PdfEngine,
    source: pathlib.Path,
    mirror_dir: pathlib.Path,
    out_root: pathlib.Path,
    page: int,
    *,
    save: bool,
) -> PageOutcome:
    """Classify one page and write the artifact its shape calls for.

    Args:
        engine: The K2 adapter.
        source: The PDF being walked.
        mirror_dir: The directory the document mirrors into.
        out_root: The output root, for reporting relative paths.
        page: One-based page number.
        save: Whether to write the artifact. ``False`` classifies and routes
            without writing, which is what a caller taking a page census wants.

    Returns:
        What happened to the page.

    """
    shape, refused = _mirror.silently(pdf_driver.shape_of, engine, source, page)
    if not shape:
        # Nothing measured a shape at all, so there is no decision to take.
        return PageOutcome(page, "", None, None, f"classify refused: {refused}")

    # A blank page carries neither usable text nor an image: rendering it would
    # hand K4 a bitmap of nothing. It is accounted for, not exported - and it is
    # *blank*, not *refused*: `classify` answers such a page with a `blank_page`
    # reason while still reporting the shape, and the two mean different things.
    if shape == "blank":
        return PageOutcome(page, shape, None, None, "blank: nothing to export")

    # The route **and** its name come from the one owner of the shape table. This
    # driver must not re-derive it: a `if shape in TEXT_SHAPES` here is a second
    # copy of a decision `pdf.route_page` already made, and the copy is what a
    # mutation can outlive without anything noticing.
    route, routed = _mirror.silently(
        pdf_driver.route_page,
        engine,
        source,
        page,
        shape,
        _export_dpi(engine, source, page),
    )
    if not routed.succeeded:
        return PageOutcome(page, shape, None, None, routed.outcome.detail)

    if not save:
        return PageOutcome(page, shape, route, None, "not written (--no-save)")

    if route == "layout_text":
        target = mirror_dir / f"{source.stem}-p{page}.txt"
        target.write_text(routed.result.value, encoding="utf-8")
    else:
        target = mirror_dir / f"{source.stem}-p{page}.png"
        target.write_bytes(routed.result.value.data)

    return PageOutcome(page, shape, route, _mirror.relative_to(target, out_root))


def process_document(
    engine: PdfEngine,
    source: pathlib.Path,
    root: pathlib.Path,
    out_root: pathlib.Path,
    *,
    selection: str | None,
    save: bool,
) -> DocumentOutcome:
    """Walk one PDF page by page and write its mirrored artifacts.

    Args:
        engine: The K2 adapter.
        source: The PDF to process.
        root: The input root.
        out_root: The output root.
        selection: Which pages to process, in the `--pages` grammar, or ``None``
            for every page. The selection is expanded against the document's own
            measured page count.
        save: Whether to write the artifacts.

    Returns:
        What happened to the document, with one entry per page.

    """
    relative = _mirror.relative_to(source, root)
    mirror_dir = out_root / pathlib.Path(relative).parent
    mirror_dir.mkdir(parents=True, exist_ok=True)

    total = _mirror.silently(pdf_driver.document_pages, engine, source)
    if total is None:
        note = "probe reported no page count, so no page range could be checked"
        _mirror.write_skipped(mirror_dir, source.stem, "pdf", note)
        return DocumentOutcome(relative, (), note)

    try:
        # `parse_pages`, not a second parser: `--pages` is one grammar with one
        # owner (`commands/pages.py`), and a batch that spelled it differently
        # would disagree with the CLI about what `5-15` means.
        chosen = parse_pages("all" if selection is None else selection, total)
    except ValueError as exc:
        # The caller's own text is wrong - a malformed range or a page the
        # document does not have - so it is a refusal, not a defect here.
        _mirror.write_skipped(mirror_dir, source.stem, "pdf", f"bad --pages: {exc}")
        return DocumentOutcome(relative, (), f"bad --pages: {exc}")

    pages = tuple(
        process_page(engine, source, mirror_dir, out_root, page, save=save)
        for page in chosen
    )
    outcome = DocumentOutcome(relative, pages)

    if save:
        _write_pages_record(outcome, mirror_dir, source.stem)
    return outcome


def _write_pages_record(
    outcome: DocumentOutcome,
    mirror_dir: pathlib.Path,
    stem: str,
) -> pathlib.Path:
    """Record what each page of a document turned out to be.

    This is the difference between a driver a person watches and one a pipeline can
    read. The artifacts alone say *a text file exists for page 4*; they do not say
    that pages 2 and 58 are blank, nor that a page was classified and refused. The
    record makes the page census a file rather than a line of console output that
    scrolls away.

    It is named `<stem>.pages.json` and not `<stem>.json`: that name means *these
    are the extracted fields* (`batch.py`'s contract), and a consumer globbing for
    `.json` would read a page census as an extraction.

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
            {
                "number": page.number,
                "shape": page.shape,
                "route": page.route,
                "artifact": page.artifact,
                "note": page.note,
            }
            for page in outcome.pages
        ],
        "shapes": outcome.shapes,
        "produced": outcome.produced,
    }
    target = mirror_dir / f"{stem}.pages.json"
    target.write_text(
        json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return target


def process_file(
    engine: PdfEngine,
    source: pathlib.Path,
    root: pathlib.Path,
    out_root: pathlib.Path,
    *,
    selection: str | None,
    save: bool,
) -> DocumentOutcome | None:
    """Process one input file, or report that it is not a PDF.

    Args:
        engine: The K2 adapter.
        source: The file to process.
        root: The input root.
        out_root: The output root.
        selection: Which pages to process, or ``None`` for every page.
        save: Whether to write the artifacts.

    Returns:
        The document's outcome, or ``None`` when the file is not a PDF - this
        driver is PDF-only by name, and a non-PDF is *not walked* rather than
        skipped-with-a-record, because the caller chose this driver's scope.

    """
    if _mirror.kind_of(source) != "pdf":
        return None
    return process_document(
        engine, source, root, out_root, selection=selection, save=save
    )


def _mirror_scope(
    root: pathlib.Path, out_root: pathlib.Path, pdfs: list[pathlib.Path]
) -> list[str]:
    """Check the mirror over the files this driver was asked to walk.

    Kept as this driver's name for `_mirror.verify_mirror_for`, which explains why
    a scope-limited driver checks only its own files. `batch_image.py` reaches that
    helper directly - it has no reason to wrap it too.

    Args:
        root: The input root.
        out_root: The output root.
        pdfs: The PDFs this walk processed.

    Returns:
        One message per violation; empty when the mirror is exact for this scope.

    """
    return _mirror.verify_mirror_for(root, out_root, pdfs)


def main(argv: list[str] | None = None) -> int:
    """Walk a folder of PDFs, route every page, and verify the mirrored tree.

    Args:
        argv: The command-line arguments, or ``None`` for `sys.argv`.

    Returns:
        The number of problems: mirrored-ness violations plus refused documents.

    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("input", type=pathlib.Path, help="the folder to walk")
    parser.add_argument(
        "--out",
        type=pathlib.Path,
        default=None,
        help="the output root (default: var/poc/batch_pdf)",
    )
    parser.add_argument(
        "--pages",
        default=None,
        help="which pages to process, in the --pages grammar (default: all)",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="classify and route without writing any artifact",
    )
    args = parser.parse_args(argv)

    root: pathlib.Path = args.input
    if not root.is_dir():
        parser.error(f"{root} is not a directory")

    out_root = args.out if args.out is not None else _lib.DEFAULT_OUT / "batch_pdf"
    save = not args.no_save
    _lib.set_out(out_root)
    _lib.reset()

    dpi = _render_dpi()
    # The registry's floor is passed **down** to each render (`_export_dpi`), never
    # written into `pdf.py`'s own `RENDER_DPI`: that constant belongs to the probe
    # driver, and setting it here would change those probes for the rest of the
    # process - a driver silently reconfiguring another one.

    # The tree first, so a directory that holds no file still exists in the output
    # and the mirror is complete even if the walk finds nothing (`S3-T06`).
    directories = _mirror.mirror_directories(root, out_root)
    engine = _engine()

    print(f"in  = {root}")
    print(f"out = {out_root}")
    print(
        f"dpi = {dpi} target (registry: {MIN_DPI_KEY}), capped per page by the pixels"
    )
    print(f"pages = {args.pages or 'all'}    save = {save}")
    print()

    files = list(_mirror.walk(root))
    pdfs = [path for path in files if _mirror.kind_of(path) == "pdf"]
    for source in files:
        outcome = process_file(
            engine, source, root, out_root, selection=args.pages, save=save
        )
        if outcome is None:
            continue
        OUTCOMES.append(outcome)

        attended = sum(1 for page in outcome.pages if page.route is not None)
        if outcome.produced:
            shapes = " ".join(f"{key}={value}" for key, value in outcome.shapes.items())
            print(
                f" ok {outcome.source:44} {attended:>3} page(s)  "
                f"wrote {outcome.produced:<3} {shapes}"
            )
        elif outcome.note:
            print(f" -- {outcome.source:44} {outcome.note}")
        else:
            # Every page was blank: the document was walked, measured and answered
            # - it simply holds nothing to export. That is a *result*, not a
            # refusal, and reporting it in the same breath as a failed walk is how
            # a blank catalog page reads as a broken run.
            shapes = " ".join(f"{key}={value}" for key, value in outcome.shapes.items())
            print(f" .. {outcome.source:44} nothing to export  {shapes}")

    print()
    print("=== the mirror")
    # Only the files this driver walks: a `.md` in the input tree is outside a
    # PDF-only driver's scope, and reporting it as a violation would blame this run
    # for a file it was never asked about.
    problems = _mirror_scope(root, out_root, pdfs)
    if not problems:
        print(
            f" ok {len(pdfs)} PDF(s) and {directories} director(ies) mirrored "
            "at the same relative paths"
        )
    for problem in problems:
        print(f" !! {problem}")

    print()
    print(f"{'shape':<14}{'pages':>6}")
    census: dict[str, int] = {}
    for outcome in OUTCOMES:
        for key, value in outcome.shapes.items():
            census[key] = census.get(key, 0) + value
    for key in sorted(census):
        print(f"{key:<14}{census[key]:>6}")
    if not census:
        print(f"{'(no pages)':<14}{0:>6}")

    written = sum(outcome.produced for outcome in OUTCOMES)
    print(f"{'written':<14}{written:>6}")
    print()

    # A document that answered *blank* was walked successfully and produced
    # nothing; one that was refused produced nothing because something went wrong.
    # Only the second is a problem, and keeping the two apart is the same
    # distinction the reporting contract draws between a `reason` and a `defect`.
    refused = [outcome for outcome in OUTCOMES if outcome.note and not outcome.produced]
    blank = [
        outcome for outcome in OUTCOMES if not outcome.note and not outcome.produced
    ]
    print(f"{len(pdfs)} PDF(s) walked, {written} artifact(s) written.")
    if blank:
        print(f"{len(blank)} document(s) held nothing to export.")
    if refused:
        print(f"{len(refused)} document(s) produced nothing; see the notes above.")
    if not problems and not refused:
        print("every PDF was walked and the tree mirrors exactly.")
        return 0
    return len(problems) + len(refused)


if __name__ == "__main__":
    sys.exit(main())
