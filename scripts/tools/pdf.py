"""Lab tool for the PDF processor (``SCR-02``).

A thin caller: its parser, its flags and one handler per subcommand are all it owns. The
frame around them — where the run writes, how the input resolves, the header, the printers
and the exit code — lives in :mod:`scripts.tools._cli`.

The tool adds no transformation, no validation and no default: a missing ``--dpi`` is a
usage error, never a substituted resolution.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any, Final

import _cli

from docflow import pdf as pdf_processor
from docflow.pdf import PDFContext, PDFOptions, PDFRequest, primitives
from docflow.pdf.primitives import composition
from docflow.pdf.primitives.errors import PDFPrimitiveError

#: Subcommands that publish no file: their report is the stdout summary, so the run header
#: says so instead of naming an output root no run creates. The other five do write —
#: ``classify`` among them, because measuring image dominance extracts the page's embedded
#: images. Verified by the hand run in ``docs/plan/bitacora.md`` (2026-09-27).
REPORT_ONLY: Final[tuple[str, ...]] = ("inspect", "text", "blocks")


def build_parser() -> argparse.ArgumentParser:
    """Build the tool's argument parser.

    Returns:
        The parser, with every documented subcommand registered.
    """
    parser, subparsers = _cli.build_parser(
        "pdf.py",
        "Lab bench for the PDF processor: one primitive, or the contract.",
        identity=True,
    )
    _cli.add_subcommand(
        subparsers, "inspect", "Page count, per-page geometry and encryption."
    )
    _cli.add_subcommand(subparsers, "split", "One self-contained PDF per page.")

    render = _cli.add_subcommand(subparsers, "render", "Render one page to PNG.")
    render.add_argument("--page", type=int, help="Page index, 1-based.")
    render.add_argument("--dpi", type=int, help="Render resolution; never defaulted.")

    for name, help_text in (
        ("text", "The page's native text."),
        ("blocks", "The page's native text blocks."),
        ("images", "The page's embedded images."),
        ("classify", "The page's descriptive TEXT/IMAGE/MIXED classification."),
    ):
        scoped = _cli.add_subcommand(subparsers, name, help_text)
        scoped.add_argument("--page", type=int, help="Page index, 1-based.")

    run = _cli.add_subcommand(subparsers, "run", "Run the PDF contract.")
    run.add_argument("--page", type=int, help="Run one page instead of the document.")
    run.add_argument("--dpi", type=int, help="Render resolution; never defaulted.")
    run.add_argument(
        "--extract-pages", action="store_true", help="One self-contained PDF per page."
    )
    run.add_argument("--render", action="store_true", help="Render each page to PNG.")
    run.add_argument(
        "--extract-text", action="store_true", help="Native text and its blocks."
    )
    run.add_argument("--extract-images", action="store_true", help="Embedded images.")
    run.add_argument(
        "--layout", action="store_true", help="Keep layout in the extracted blocks."
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the tool.

    Args:
        argv: The arguments, defaulting to ``sys.argv[1:]``.

    Returns:
        The process exit code: ``0`` when the run produced a result, ``1`` when the library
        returned a typed failure.
    """
    return _cli.run_tool("pdf", build_parser(), HANDLERS, argv, report_only=REPORT_ONLY)


def _page(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """Return ``--page``, refusing to guess one."""
    return int(
        _cli.required(args, parser, "page", "--page", why="no page number is defaulted")
    )


def _dpi(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """Return ``--dpi``, refusing to substitute a resolution."""
    return int(
        _cli.required(args, parser, "dpi", "--dpi", why="no resolution is defaulted")
    )


def _cmd_inspect(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> int:
    """Print the document's page count, geometry and engine report."""
    del parser, root
    try:
        document = primitives.inspect_pdf(input_path)
    except PDFPrimitiveError as failure:
        return _cli.print_error([failure.error])
    _cli.print_result(
        {
            "input": str(input_path),
            "page_count": document.page_count,
            "page_dimensions": [list(size) for size in document.page_dimensions],
            "engine_metadata": document.engine_metadata,
        },
        as_json=args.json,
    )
    return 0


def _cmd_split(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> int:
    """Split the document and print the published page files."""
    del parser
    try:
        produced = primitives.split_pdf(input_path, root)
    except PDFPrimitiveError as failure:
        return _cli.print_error([failure.error])
    _cli.print_result(
        {
            "input": str(input_path),
            "output_dir": str(root),
            "pages": [str(path) for path in produced],
        },
        as_json=args.json,
    )
    return 0


def _cmd_render(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> int:
    """Render one page and print where the PNG landed."""
    page = _page(args, parser)
    dpi = _dpi(args, parser)
    destination = root / f"page_{page:03d}_{dpi}dpi.png"
    try:
        produced = primitives.render_page_to_image(input_path, page, destination, dpi)
    except PDFPrimitiveError as failure:
        return _cli.print_error([failure.error])
    _cli.print_result(
        {
            "input": str(input_path),
            "page": page,
            "dpi": dpi,
            "output": str(produced),
        },
        as_json=args.json,
    )
    return 0


def _cmd_text(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> int:
    """Print one page's native text."""
    del root
    page = _page(args, parser)
    try:
        text, _ = primitives.extract_text_from_page(input_path, page, True)
    except PDFPrimitiveError as failure:
        return _cli.print_error([failure.error])
    _cli.print_result(
        {"input": str(input_path), "page": page, "text": text}, as_json=args.json
    )
    return 0


def _cmd_blocks(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> int:
    """Print one page's native text blocks, in reading order."""
    del root
    page = _page(args, parser)
    try:
        _, blocks = primitives.extract_text_from_page(input_path, page, True)
    except PDFPrimitiveError as failure:
        return _cli.print_error([failure.error])
    _cli.print_result(
        {
            "input": str(input_path),
            "page": page,
            "blocks": [asdict(block) for block in blocks],
        },
        as_json=args.json,
    )
    return 0


def _cmd_images(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> int:
    """Extract and print one page's embedded images."""
    page = _page(args, parser)
    try:
        images = primitives.extract_images_from_page(input_path, page, root / "images")
    except PDFPrimitiveError as failure:
        return _cli.print_error([failure.error])
    _cli.print_result(
        {
            "input": str(input_path),
            "page": page,
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
        },
        as_json=args.json,
    )
    return 0


def _cmd_classify(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> int:
    """Print one page's measured composition and its descriptive classification."""
    page = _page(args, parser)
    try:
        document = primitives.inspect_pdf(input_path)
        width, height = document.page_dimensions[page - 1]
        text, blocks = primitives.extract_text_from_page(input_path, page, True)
        images = primitives.extract_images_from_page(input_path, page, root / "images")
    except PDFPrimitiveError as failure:
        return _cli.print_error([failure.error])
    page_data = composition.PDFPageData(
        page_number=page,
        page_width=width,
        page_height=height,
        text=text,
        text_blocks=blocks,
        embedded_images=images,
    )
    metrics = composition.analyze_pdf_page(page_data)
    _cli.print_result(
        {
            "input": str(input_path),
            "page": page,
            "metrics": asdict(metrics),
            "classification": composition.classify_pdf_page(metrics),
        },
        as_json=args.json,
    )
    return 0


def _run_options(
    args: argparse.Namespace, parser: argparse.ArgumentParser
) -> PDFOptions:
    """Build the capabilities the run asks for, every field supplied by a flag."""
    return PDFOptions(
        extract_pages=bool(args.extract_pages),
        render=bool(args.render),
        extract_text=bool(args.extract_text),
        extract_images=bool(args.extract_images),
        layout=bool(args.layout),
        dpi=_dpi(args, parser),
    )


def _page_payload(result: Any) -> dict[str, Any]:
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


def _document_payload(result: Any) -> dict[str, Any]:
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


def _cmd_run(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> int:
    """Run the PDF contract, whole document or a single page."""
    document_id, run_id = _cli.identity_for(args, "pdf", input_path)
    request = PDFRequest(
        pdf_path=input_path,
        output_dir=root,
        options=_run_options(args, parser),
        context=PDFContext(document_id=document_id, workflow_run_id=run_id),
    )
    if args.page is not None:
        page = int(args.page)
        page_result = pdf_processor.process_pdf_page(
            request, page, root / f"page_{page:03d}"
        )
        return _cli.report_result(
            page_result, _page_payload(page_result), as_json=args.json
        )
    result = pdf_processor.process_pdf(request)
    return _cli.report_result(result, _document_payload(result), as_json=args.json)


HANDLERS: dict[str, _cli.Handler] = {
    "inspect": _cmd_inspect,
    "split": _cmd_split,
    "render": _cmd_render,
    "text": _cmd_text,
    "blocks": _cmd_blocks,
    "images": _cmd_images,
    "classify": _cmd_classify,
    "run": _cmd_run,
}


if __name__ == "__main__":
    raise SystemExit(main())
