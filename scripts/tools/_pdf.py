"""The PDF bench's shared command layer (``SCR-11``).

``pdf.py`` runs one file and ``batch_pdf.py`` runs a folder tree: two callers of the same eight
methods. This module holds them, so neither tool owns a second copy of a payload, a flag or a
refusal — the flags are registered by :func:`build_subcommands` and the methods are reached
through :data:`COMMANDS`, both by name.

It is **not** a tool: it has no ``main``, it prints nothing, and it is never invoked directly. A
method does the work and returns the payload; the caller decides whether that becomes stdout
(:mod:`_cli`'s printers) or a file beside the artifacts. The processor's typed failures are
raised, never caught here — a tool prints them and exits ``1`` — with one exception: the loop
over every page keeps a failed page's record beside the pages that succeeded, because one bad
page must not cost a caller the rest of the document.

**Page scope.** Five of the eight methods are page-addressed: ``render``, ``text``, ``blocks``,
``images`` and ``classify``. A stated ``--page`` reads that page; its absence reads **every**
page of the document, in order — a one-page document is simply a scope of size one, with no
branch for it. The scope a run resolved to is stated back in the payload, so an omitted flag is
never silent. ``run`` is not one of them: its ``--page`` switches to the page-level contract and
its absence runs the whole document.

It carries the lab-bench exception of ``subplan-scripts.md`` §3.2 for its own processor: it may
drive ``docflow.pdf.primitives``. ``workflow.py`` may not, and does not use this module.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from functools import partial
from pathlib import Path
from typing import Any, Final

import _cli

from docflow import pdf as pdf_processor
from docflow.pdf import PDFContext, PDFOptions, PDFRequest, primitives
from docflow.pdf.primitives import PDFPrimitiveError, composition

#: One subcommand per method, with the help text both tools print.
SUBCOMMANDS: tuple[tuple[str, str], ...] = (
    ("inspect", "Page count, per-page geometry and encryption."),
    ("split", "One self-contained PDF per page."),
    ("render", "Render one page to PNG."),
    ("text", "The page's native text."),
    ("blocks", "The page's native text blocks."),
    ("images", "The page's embedded images."),
    ("classify", "The page's descriptive TEXT/IMAGE/MIXED classification."),
    ("run", "Run the PDF contract."),
)

#: The inputs the PDF processor takes, matched case-insensitively: what it can read.
SUFFIXES: Final[tuple[str, ...]] = (".pdf",)

#: The subcommands that read pages: a stated ``--page`` selects one and its absence selects
#: every page, so the flag is never required. ``run`` takes ``--page`` too
#: (:data:`PAGE_FLAG_COMMANDS`), but there its absence means something else — the whole
#: document contract.
PAGE_COMMANDS: Final[tuple[str, ...]] = (
    "render",
    "text",
    "blocks",
    "images",
    "classify",
)

#: The subcommands that take ``--page``: those five, plus ``run``, whose ``--page`` selects one
#: page when it is given and whose absence runs the whole document.
PAGE_FLAG_COMMANDS: Final[tuple[str, ...]] = (*PAGE_COMMANDS, "run")

#: The help each page-taking subcommand prints for ``--page``: one flag, two meanings.
PAGE_HELP: Final[dict[str, str]] = {
    **dict.fromkeys(PAGE_COMMANDS, "Page index, 1-based; omit it to read every page."),
    "run": "Page index, 1-based; omit it to run the whole document.",
}

#: The subcommands that resolve a page at a stated resolution: rendering one and running the
#: contract both do, so ``--dpi`` is taken and required on each.
DPI_COMMANDS: Final[tuple[str, ...]] = ("render", "run")

#: What one method returns: the payload its caller prints, or writes beside the artifacts.
Payload = dict[str, Any]

#: A method as the tools call it: the parsed flags, the parser to refuse through, the input and
#: the directory that input's run writes under.
Command = Callable[[argparse.Namespace, argparse.ArgumentParser, Path, Path], Payload]


def build_subcommands(
    subparsers: Any, *, input_argument: bool = True
) -> dict[str, argparse.ArgumentParser]:
    """Register every subcommand with the flags that are its own.

    Both tools call this, which is what keeps their flag surface one thing rather than two: a
    subcommand added here is a subcommand in both.

    Args:
        subparsers: The group :func:`_cli.build_parser` returned.
        input_argument: Whether a subcommand takes the input positional. ``pdf.py`` runs one
            file, so it does; ``batch_pdf.py`` takes a folder once and walks it, so it does not.

    Returns:
        The subcommand parsers by name, for a tool that wants to reach one directly.
    """
    parsers: dict[str, argparse.ArgumentParser] = {}
    for name, help_text in SUBCOMMANDS:
        parser = _cli.add_subcommand(
            subparsers, name, help_text, input_argument=input_argument
        )
        if name in PAGE_FLAG_COMMANDS:
            parser.add_argument("--page", type=int, help=PAGE_HELP[name])
        if name in DPI_COMMANDS:
            parser.add_argument(
                "--dpi", type=int, help="Render resolution; never defaulted."
            )
        if name == "run":
            for flag, flag_help in (
                ("--extract-pages", "One self-contained PDF per page."),
                ("--render", "Render each page to PNG."),
                ("--extract-text", "Native text and its blocks."),
                ("--extract-images", "Embedded images."),
                ("--layout", "Keep layout in the extracted blocks."),
            ):
                parser.add_argument(flag, action="store_true", help=flag_help)
        parsers[name] = parser
    return parsers


@dataclass(frozen=True)
class PageScope:
    """The pages one run covers, and what the run must state about them.

    Attributes:
        pages: The page numbers to read, in order — one of them when the caller stated a
            page, all of them when they stated none.
        label: The scope as the payload states it: ``"page 2"``, or ``"all pages (3)"``.
        stated: Whether the caller named a page. It decides the payload's **shape**, not its
            content: a one-page document read without ``--page`` is still an all-pages run,
            because that is the question that was asked.
        document: The inspection the scope needed, when it needed one. It is ``None`` when
            ``--page`` was stated — so the single-page path makes no engine call it did not
            make before — and is handed on so the one method that needs the geometry
            (``classify``) does not read the same document a second time.
    """

    pages: list[int]
    label: str
    stated: bool
    document: composition.PDFDocumentInfo | None = None


def page_scope(args: argparse.Namespace, input_path: Path) -> PageScope:
    """Return the pages a run covers, inspecting the document only when it must.

    ``--page`` has no default on purpose: its absence is what selects every page, so a
    substituted value would turn a whole-document read into a one-page read without saying so.

    Args:
        args: The parsed arguments, whose ``page`` is ``None`` when the caller stated none.
        input_path: The document, read for its page count when no page was stated.

    Returns:
        The scope. A stated page needs no inspection, which is what keeps that path's engine
        calls exactly what they were.

    Raises:
        PDFPrimitiveError: Propagated from ``inspect_pdf`` — a document that cannot be read
            fails before any page is, with the record it has always produced.
    """
    if args.page is not None:
        page_number = int(args.page)
        return PageScope(pages=[page_number], label=f"page {page_number}", stated=True)
    document = primitives.inspect_pdf(input_path)
    return PageScope(
        pages=list(range(1, document.page_count + 1)),
        label=f"all pages ({document.page_count})",
        stated=False,
        document=document,
    )


def _pages(
    scope: PageScope, one: Callable[[int], Payload]
) -> tuple[list[Payload], list[Payload]]:
    """Run one page's work over a scope, collecting a page's typed failure.

    A page that fails does not end the document: its typed record is kept beside the pages that
    succeeded, so one bad page cannot cost a caller the other twenty-nine.
    """
    entries: list[Payload] = []
    errors: list[Payload] = []
    for page_number in scope.pages:
        try:
            entries.append(one(page_number))
        except PDFPrimitiveError as failure:
            errors.append(asdict(primitives.for_page(failure.error, page_number)))
    return entries, errors


def _scope_status(entries: Sequence[Payload], errors: Sequence[Payload]) -> str:
    """Return the outcome over a scope: every page produced one, some did, or none did."""
    if not entries:
        return "failed"
    return "partial" if errors else "success"


def _scope_payload(
    input_path: Path, scope: PageScope, one: Callable[[int], Payload]
) -> Payload:
    """Build a run's payload: one page's own shape, or every page's list and outcome.

    A stated page keeps the shape it has always had — its own keys, plus the scope it states —
    and a failure is raised rather than reported, because one page has nowhere to lose it.
    Every page gathers its entries, keeps the failures beside them, and names the outcome over
    the whole scope.
    """
    if scope.stated:
        return {
            "input": str(input_path),
            "scope": scope.label,
            **one(scope.pages[0]),
        }
    entries, errors = _pages(scope, one)
    return {
        "input": str(input_path),
        "scope": scope.label,
        "pages": entries,
        "status": _scope_status(entries, errors),
        "errors": errors,
    }


def _images_dir(root: Path, page_number: int, *, every_page: bool) -> Path:
    """Return the directory one page's embedded images are written to.

    A stated page keeps the flat ``images/`` directory it has always used. A scope of many
    pages gives each its own, because the processor names an extracted image from a per-call
    index (``image_001.png``, ``image_002.png``, …): two pages sharing one directory would have
    the second overwrite the first.
    """
    if not every_page:
        return root / "images"
    return root / f"page_{page_number:03d}" / "images"


def dpi(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """Return ``--dpi``, refusing to substitute a resolution."""
    return int(
        _cli.required(args, parser, "dpi", "--dpi", why="no resolution is defaulted")
    )


def validate_flags(
    command: str, args: argparse.Namespace, parser: argparse.ArgumentParser
) -> None:
    """Refuse a missing required flag, once, before the run starts.

    ``--dpi`` is the only flag a command cannot run without (:data:`DPI_COMMANDS`), and the set
    is the one :func:`build_subcommands` registers the flag from — a second copy of it would be
    a second thing to keep in step. ``--page`` is not guarded here: a page-addressed command
    that states none reads every page, so there is no gap to refuse.

    Both tools pass this as their ``validate`` hook, so the refusal happens before the header
    and a batch refuses once rather than per input — and an empty folder, which calls no
    method at all, cannot report a successful run of a command that was missing its flag.

    Args:
        command: The subcommand being run.
        args: The parsed arguments.
        parser: The parser to report the usage error through.
    """
    if command in DPI_COMMANDS:
        dpi(args, parser)


def run_options(
    args: argparse.Namespace, parser: argparse.ArgumentParser
) -> PDFOptions:
    """Build the capabilities the contract run asks for, every field supplied by a flag."""
    return PDFOptions(
        extract_pages=bool(args.extract_pages),
        render=bool(args.render),
        extract_text=bool(args.extract_text),
        extract_images=bool(args.extract_images),
        layout=bool(args.layout),
        dpi=dpi(args, parser),
    )


def _inspect(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> Payload:
    """Read the document's page count, geometry and engine report."""
    del args, parser, root
    document = primitives.inspect_pdf(input_path)
    return {
        "input": str(input_path),
        "page_count": document.page_count,
        "page_dimensions": [list(size) for size in document.page_dimensions],
        "engine_metadata": document.engine_metadata,
    }


def _split(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> Payload:
    """Split the document and report the published page files."""
    del args, parser
    produced = primitives.split_pdf(input_path, root)
    return {
        "input": str(input_path),
        "output_dir": str(root),
        "pages": [str(path) for path in produced],
    }


def _render_page(
    input_path: Path, page_number: int, root: Path, resolution: int
) -> Payload:
    """Render one page and report where the PNG landed."""
    destination = root / f"page_{page_number:03d}_{resolution}dpi.png"
    produced = primitives.render_page_to_image(
        input_path, page_number, destination, resolution
    )
    return {"page": page_number, "dpi": resolution, "output": str(produced)}


def _render(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> Payload:
    """Render one page, or every page, and report where each PNG landed."""
    scope = page_scope(args, input_path)
    resolution = dpi(args, parser)
    return _scope_payload(
        input_path,
        scope,
        partial(_render_page, input_path, root=root, resolution=resolution),
    )


def _text_page(input_path: Path, page_number: int, root: Path) -> Payload:
    """Read one page's native text and publish both of its text artifacts.

    Two files, one per read: ``page_NNN.txt`` is the reconstruction from the word rows, and
    ``page_NNN_layout.txt`` is the engine's own ``-layout`` rendering, kept beside it rather
    than instead of it because it carries the page's columns and the reconstruction does not.
    Both are named after the page, the way ``render`` names its PNG: the scope decides how
    many files a run publishes, never what one of them is called. The writes reuse the
    processor's own atomic writer, so a half-written artifact is never visible.
    """
    text, _ = primitives.extract_text_from_page(input_path, page_number, True)
    laid_out = primitives.extract_layout_text_from_page(input_path, page_number)
    published = primitives.publish_text(root / f"page_{page_number:03d}.txt", text)
    published_layout = primitives.publish_text(
        root / f"page_{page_number:03d}_layout.txt", laid_out
    )
    return {
        "page": page_number,
        "text": text,
        "output": str(published),
        "layout_output": str(published_layout),
    }


def _text(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> Payload:
    """Read one page's native text, or every page's, publishing one file per page."""
    del parser
    scope = page_scope(args, input_path)
    return _scope_payload(input_path, scope, partial(_text_page, input_path, root=root))


def _blocks_page(input_path: Path, page_number: int) -> Payload:
    """Read one page's native text blocks, in reading order."""
    _, blocks = primitives.extract_text_from_page(input_path, page_number, True)
    return {"page": page_number, "blocks": [asdict(block) for block in blocks]}


def _blocks(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> Payload:
    """Read one page's native text blocks, or every page's, in reading order."""
    del parser, root
    scope = page_scope(args, input_path)
    return _scope_payload(input_path, scope, partial(_blocks_page, input_path))


def _images_page(
    input_path: Path, page_number: int, root: Path, *, every_page: bool
) -> Payload:
    """Extract one page's embedded images into that page's own directory."""
    images = primitives.extract_images_from_page(
        input_path, page_number, _images_dir(root, page_number, every_page=every_page)
    )
    return {
        "page": page_number,
        "images": [
            {
                "image_id": image.image_id,
                "path": str(image.path),
                "width": image.width,
                "height": image.height,
                "format": image.format,
                "metadata": image.metadata,
            }
            for image in images
        ],
    }


def _images(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> Payload:
    """Extract one page's embedded images, or every page's."""
    del parser
    scope = page_scope(args, input_path)
    return _scope_payload(
        input_path,
        scope,
        partial(_images_page, input_path, root=root, every_page=not scope.stated),
    )


def _classify_page(
    input_path: Path,
    page_number: int,
    root: Path,
    *,
    every_page: bool,
    document: composition.PDFDocumentInfo | None,
) -> Payload:
    """Measure one page's composition and name its classification.

    The inspection the scope already made is handed in; only a stated page, whose scope needed
    no inspection, reads the document here.
    """
    if document is None:
        document = primitives.inspect_pdf(input_path)
    width, height = document.page_dimensions[page_number - 1]
    text, blocks = primitives.extract_text_from_page(input_path, page_number, True)
    images = primitives.extract_images_from_page(
        input_path, page_number, _images_dir(root, page_number, every_page=every_page)
    )
    metrics = composition.analyze_pdf_page(
        composition.PDFPageData(
            page_number=page_number,
            page_width=width,
            page_height=height,
            text=text,
            text_blocks=blocks,
            embedded_images=images,
        )
    )
    return {
        "page": page_number,
        "metrics": asdict(metrics),
        "classification": composition.classify_pdf_page(metrics),
    }


def _classify(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> Payload:
    """Measure one page's composition, or every page's, and name its classification."""
    del parser
    scope = page_scope(args, input_path)
    return _scope_payload(
        input_path,
        scope,
        partial(
            _classify_page,
            input_path,
            root=root,
            every_page=not scope.stated,
            document=scope.document,
        ),
    )


def _page_payload(result: Any) -> Payload:
    """Build a payload from a page result's own fields."""
    return {
        "status": str(result.status),
        "page_number": result.page_number,
        "classification": result.classification,
        "page_pdf": _cli.optional_path(result.page_pdf),
        "page_image": _cli.optional_path(result.page_image),
        "native_text": _cli.optional_path(result.native_text),
        "text_blocks": [asdict(block) for block in result.text_blocks],
        "embedded_images": [
            {
                "image_id": image.image_id,
                "path": str(image.path),
                "width": image.width,
                "height": image.height,
                "format": image.format,
            }
            for image in result.embedded_images
        ],
        "metrics": asdict(result.metrics),
        "artifacts": [str(path) for path in result.artifacts],
        "errors": [asdict(error) for error in result.validation.errors],
    }


def _document_payload(result: Any) -> Payload:
    """Build a payload from a document result's own fields."""
    return {
        "status": str(result.status),
        "source_path": str(result.source_path),
        "engine": result.metadata.engine,
        "engine_version": result.metadata.engine_version,
        "page_count": result.metadata.page_count,
        "metrics": asdict(result.metrics),
        "pages": [
            {
                "page_number": page.page_number,
                "status": str(page.status),
                "classification": page.classification,
                "page_image": _cli.optional_path(page.page_image),
                "native_text": _cli.optional_path(page.native_text),
                "errors": [asdict(error) for error in page.validation.errors],
            }
            for page in result.pages
        ],
        "artifacts": [str(path) for path in result.artifacts],
        "errors": [asdict(error) for error in result.errors],
    }


def _run(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> Payload:
    """Run the PDF contract, whole document or a single page.

    The run identity is derived from the program's own name (``pdf.py``, ``batch_pdf.py``), so a
    batch's run id says which tool produced it unless the caller pinned one.
    """
    document_id, run_id = _cli.identity_for(args, Path(parser.prog).stem, input_path)
    request = PDFRequest(
        pdf_path=input_path,
        output_dir=root,
        options=run_options(args, parser),
        context=PDFContext(document_id=document_id, workflow_run_id=run_id),
    )
    if args.page is not None:
        page_number = int(args.page)
        return _page_payload(
            pdf_processor.process_pdf_page(
                request, page_number, root / f"page_{page_number:03d}"
            )
        )
    return _document_payload(pdf_processor.process_pdf(request))


#: The eight methods by subcommand name. Both tools dispatch through this, so a subcommand's
#: behaviour lives in exactly one place.
COMMANDS: dict[str, Command] = {
    "inspect": _inspect,
    "split": _split,
    "render": _render,
    "text": _text,
    "blocks": _blocks,
    "images": _images,
    "classify": _classify,
    "run": _run,
}
