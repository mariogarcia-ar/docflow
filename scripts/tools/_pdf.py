"""The PDF bench's shared command layer (``SCR-11``).

``pdf.py`` runs one file and ``batch_pdf.py`` runs a folder tree: two callers of the same eight
methods. This module holds them, so neither tool owns a second copy of a payload, a flag or a
refusal — the flags are registered by :func:`build_subcommands` and the methods are reached
through :data:`COMMANDS`, both by name.

It is **not** a tool: it has no ``main``, it prints nothing, and it is never invoked directly. A
method does the work and returns the payload; the caller decides whether that becomes stdout
(:mod:`_cli`'s printers) or a file beside the artifacts. The processor's typed failures are
raised, never caught here — a tool prints them and exits ``1``.

It carries the lab-bench exception of ``subplan-scripts.md`` §3.2 for its own processor: it may
drive ``docflow.pdf.primitives``. ``workflow.py`` may not, and does not use this module.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any, Final

import _cli

from docflow import pdf as pdf_processor
from docflow.pdf import PDFContext, PDFOptions, PDFRequest, primitives
from docflow.pdf.primitives import composition

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

#: The subcommands that read one page: their report is a page's, so ``--page`` is not optional.
PAGE_COMMANDS: Final[tuple[str, ...]] = (
    "render",
    "text",
    "blocks",
    "images",
    "classify",
)

#: The subcommands that take ``--page``: those five, plus ``run``, whose ``--page`` selects one
#: page when it is given. A whole-document run states none, so the flag is taken and not
#: required there — the one place the two sets differ.
PAGE_FLAG_COMMANDS: Final[tuple[str, ...]] = (*PAGE_COMMANDS, "run")

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
            parser.add_argument("--page", type=int, help="Page index, 1-based.")
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


def page(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """Return ``--page``, refusing to guess one."""
    return int(
        _cli.required(args, parser, "page", "--page", why="no page number is defaulted")
    )


def dpi(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """Return ``--dpi``, refusing to substitute a resolution."""
    return int(
        _cli.required(args, parser, "dpi", "--dpi", why="no resolution is defaulted")
    )


def validate_flags(
    command: str, args: argparse.Namespace, parser: argparse.ArgumentParser
) -> None:
    """Refuse a missing required flag, once, before the run starts.

    The guards are the same two :func:`page` and :func:`dpi` the methods call, over the same
    name sets :func:`build_subcommands` registers the flags from: a command that takes a flag it
    cannot run without is a command this refuses, and ``run`` — which takes ``--page`` without
    requiring it — is the one case the two sets do not share. The sets are not restated here,
    because a second copy of them is a second thing to keep in step.

    Both tools pass this as their ``validate`` hook, so the refusal happens before the header
    and a batch refuses once rather than per input — and an empty folder, which calls no
    method at all, cannot report a successful run of a command that was missing its flag.

    Args:
        command: The subcommand being run.
        args: The parsed arguments.
        parser: The parser to report the usage error through.
    """
    if command in PAGE_COMMANDS:
        page(args, parser)
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


def _render(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> Payload:
    """Render one page and report where the PNG landed."""
    page_number = page(args, parser)
    resolution = dpi(args, parser)
    destination = root / f"page_{page_number:03d}_{resolution}dpi.png"
    produced = primitives.render_page_to_image(
        input_path, page_number, destination, resolution
    )
    return {
        "input": str(input_path),
        "page": page_number,
        "dpi": resolution,
        "output": str(produced),
    }


def _text(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> Payload:
    """Read one page's native text."""
    del root
    page_number = page(args, parser)
    text, _ = primitives.extract_text_from_page(input_path, page_number, True)
    return {"input": str(input_path), "page": page_number, "text": text}


def _blocks(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> Payload:
    """Read one page's native text blocks, in reading order."""
    del root
    page_number = page(args, parser)
    _, blocks = primitives.extract_text_from_page(input_path, page_number, True)
    return {
        "input": str(input_path),
        "page": page_number,
        "blocks": [asdict(block) for block in blocks],
    }


def _images(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> Payload:
    """Extract one page's embedded images."""
    page_number = page(args, parser)
    images = primitives.extract_images_from_page(
        input_path, page_number, root / "images"
    )
    return {
        "input": str(input_path),
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


def _classify(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> Payload:
    """Measure one page's composition and name its classification."""
    page_number = page(args, parser)
    document = primitives.inspect_pdf(input_path)
    width, height = document.page_dimensions[page_number - 1]
    text, blocks = primitives.extract_text_from_page(input_path, page_number, True)
    images = primitives.extract_images_from_page(
        input_path, page_number, root / "images"
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
        "input": str(input_path),
        "page": page_number,
        "metrics": asdict(metrics),
        "classification": composition.classify_pdf_page(metrics),
    }


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
