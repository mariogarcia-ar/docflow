"""Lab tool for the OCR processor (``SCR-04``).

A thin caller: its parser, its flags and one handler per subcommand are all it owns. The
frame around them — where the run writes, how the input resolves, the header, the printers
and the exit code — lives in :mod:`scripts.tools._cli`.

There is no ``--engine`` flag: the engine is fixed and never presented as a selectable
option.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any, Final

import _cli

from docflow import ocr as ocr_processor
from docflow.ocr import OCRContext, OCROptions, OCRRequest, primitives
from docflow.ocr.primitives import composition
from docflow.ocr.primitives.errors import OCRPrimitiveError

#: Subcommands that publish no file: their report is the stdout summary, so the run header
#: says so instead of naming an output root no run creates. Only ``run`` publishes its
#: document. Verified by the hand run in ``docs/plan/bitacora.md`` (2026-09-27).
REPORT_ONLY: Final[tuple[str, ...]] = (
    "text",
    "md",
    "json",
    "tables",
    "blocks",
    "metrics",
)


def build_parser() -> argparse.ArgumentParser:
    """Build the tool's argument parser.

    Returns:
        The parser, with every documented subcommand registered.
    """
    parser, subparsers = _cli.build_parser(
        "ocr.py",
        "Lab bench for the OCR processor: one representation, or the contract.",
        identity=True,
    )

    for name, help_text in (
        ("text", "The extraction's plain text."),
        ("md", "The extraction's Markdown."),
        ("json", "The structured document, serialized."),
        ("tables", "Detected tables, in reading order."),
        ("blocks", "Ordered blocks, in reading order."),
        ("metrics", "Content metrics, over the built document."),
    ):
        scoped = _cli.add_subcommand(subparsers, name, help_text)
        _add_ocr_options(scoped)

    run = _cli.add_subcommand(subparsers, "run", "Run the OCR contract.")
    _add_ocr_options(run)
    run.add_argument(
        "--page", type=int, default=1, help="Logical page number, 1-based."
    )
    return parser


def _add_ocr_options(subparser: argparse.ArgumentParser) -> None:
    """Add the OCR capability flags a subcommand builds its options from."""
    subparser.add_argument(
        "--ocr",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run OCR; on by default because it is the processor's purpose.",
    )
    subparser.add_argument("--layout", action="store_true", help="Extract layout.")
    subparser.add_argument(
        "--tables", action="store_true", help="Detect and extract tables."
    )
    subparser.add_argument(
        "--reading-order", action="store_true", help="Preserve reading order."
    )
    subparser.add_argument(
        "--language", help="Expected language tag, or omit for none."
    )
    subparser.add_argument(
        "--engine-option",
        action="append",
        metavar="KEY=VALUE",
        help="Engine passthrough option; may be repeated.",
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the tool.

    Args:
        argv: The arguments, defaulting to ``sys.argv[1:]``.

    Returns:
        The process exit code: ``0`` when the run produced a result, ``1`` when the library
        returned a typed failure.
    """
    return _cli.run_tool("ocr", build_parser(), HANDLERS, argv, report_only=REPORT_ONLY)


def _options(args: argparse.Namespace, parser: argparse.ArgumentParser) -> OCROptions:
    """Build the OCR options the flags describe."""
    return OCROptions(
        ocr=bool(args.ocr),
        layout=bool(args.layout),
        tables=bool(args.tables),
        reading_order=bool(args.reading_order),
        language=args.language,
        engine_options=_cli.key_values(
            args.engine_option, parser, flag="--engine-option"
        ),
    )


def _conversion(
    args: argparse.Namespace, parser: argparse.ArgumentParser, input_path: Path
) -> tuple[Any, Any]:
    """Run one engine conversion and return it with the options that configured it."""
    normalized = primitives.normalize_docling_options(_options(args, parser))
    config = primitives.configure_image_pipeline(normalized)
    return primitives.convert_image_with_docling(input_path, config), normalized


def _document(
    args: argparse.Namespace, parser: argparse.ArgumentParser, input_path: Path
) -> tuple[Any, Any]:
    """Convert once and translate everything the run claims, in reading order.

    This is the bench assembling its own processor's primitives so that one representation
    can be looked at without a whole ``run``; it composes, it transforms nothing itself.
    """
    conversion, normalized = _conversion(args, parser, input_path)
    reported = primitives.conversion_failure(conversion, input_path)
    if reported is not None and not reported.recoverable:
        raise OCRPrimitiveError(reported)
    geometry = primitives.extract_docling_layout(conversion)
    blocks = primitives.extract_docling_blocks(
        conversion, geometry, with_layout=normalized.layout
    )
    tables = (
        primitives.extract_docling_tables(
            conversion, geometry, with_layout=normalized.layout
        )
        if normalized.tables
        else []
    )
    ordered = composition.preserve_reading_order(
        blocks, tables, by_geometry=normalized.reading_order
    )
    document = primitives.build_ocr_document(
        text=primitives.normalize_ocr_text(primitives.extract_docling_text(conversion)),
        blocks=ordered.blocks,
        tables=ordered.tables,
        layout=composition.normalize_layout(geometry, with_regions=normalized.layout),
        reading_order=ordered.reading_order,
        options=normalized,
        engine_version=primitives.get_engine_version(),
    )
    return ordered, document


def _cmd_text(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> int:
    """Print the extraction's plain text."""
    del root
    try:
        conversion, _ = _conversion(args, parser, input_path)
        text = primitives.extract_docling_text(conversion)
    except OCRPrimitiveError as failure:
        return _cli.print_error([failure.error])
    _cli.print_result({"input": str(input_path), "text": text}, as_json=args.json)
    return 0


def _cmd_md(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> int:
    """Print the extraction's Markdown."""
    del root
    try:
        conversion, _ = _conversion(args, parser, input_path)
        markdown = primitives.extract_docling_markdown(conversion)
    except OCRPrimitiveError as failure:
        return _cli.print_error([failure.error])
    _cli.print_result(
        {"input": str(input_path), "markdown": markdown}, as_json=args.json
    )
    return 0


def _cmd_json(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> int:
    """Print the structured document, serialized."""
    del root
    try:
        _, document = _document(args, parser, input_path)
    except OCRPrimitiveError as failure:
        return _cli.print_error([failure.error])
    _cli.print_result(
        {"input": str(input_path), "document": asdict(document)}, as_json=args.json
    )
    return 0


def _cmd_tables(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> int:
    """Print the detected tables, in reading order."""
    del root
    try:
        ordered, _ = _document(args, parser, input_path)
    except OCRPrimitiveError as failure:
        return _cli.print_error([failure.error])
    _cli.print_result(
        {
            "input": str(input_path),
            "tables": [asdict(table) for table in ordered.tables],
        },
        as_json=args.json,
    )
    return 0


def _cmd_blocks(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> int:
    """Print the ordered blocks."""
    del root
    try:
        ordered, _ = _document(args, parser, input_path)
    except OCRPrimitiveError as failure:
        return _cli.print_error([failure.error])
    _cli.print_result(
        {
            "input": str(input_path),
            "blocks": [asdict(block) for block in ordered.blocks],
            "reading_order": list(ordered.reading_order),
        },
        as_json=args.json,
    )
    return 0


def _cmd_metrics(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> int:
    """Print the content metrics of the built document."""
    del root
    try:
        _, document = _document(args, parser, input_path)
        metrics = composition.analyze_ocr_result(document)
    except OCRPrimitiveError as failure:
        return _cli.print_error([failure.error])
    _cli.print_result(
        {"input": str(input_path), "metrics": asdict(metrics)}, as_json=args.json
    )
    return 0


def _artifact_payload(result: Any) -> dict[str, Any] | None:
    """Build the artifact-path payload from an OCR result's own fields."""
    if result.artifacts is None:
        return None
    return {
        "text": str(result.artifacts.text),
        "markdown": str(result.artifacts.markdown),
        "structured_document": str(result.artifacts.structured_document),
        "tables_dir": str(result.artifacts.tables_dir),
        "metadata": str(result.artifacts.metadata),
    }


def _cmd_run(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> int:
    """Run the OCR contract and print what it published."""
    document_id, run_id = _cli.identity_for(args, "ocr", input_path)
    context = OCRContext(
        document_id=document_id,
        page_number=int(args.page),
        workflow_run_id=run_id,
    )
    request = OCRRequest(
        image_path=input_path,
        output_dir=root,
        options=_options(args, parser),
        context=context,
    )
    result = ocr_processor.process_ocr_image(request)
    return _cli.report_result(
        result,
        {
            "status": str(result.status),
            "document_id": context.document_id,
            "page_number": context.page_number,
            "workflow_run_id": context.workflow_run_id,
            "text": result.text,
            "markdown": result.markdown,
            "tables": None if result.tables is None else len(result.tables),
            "blocks": None if result.blocks is None else len(result.blocks),
            "metrics": None if result.metrics is None else asdict(result.metrics),
            "artifacts": _artifact_payload(result),
            "validation": {
                "status": result.validation.status,
                "errors": [asdict(error) for error in result.validation.errors],
            },
            "error": None if result.error is None else asdict(result.error),
        },
        as_json=args.json,
    )


HANDLERS: dict[str, _cli.Handler] = {
    "run": _cmd_run,
    "text": _cmd_text,
    "md": _cmd_md,
    "json": _cmd_json,
    "tables": _cmd_tables,
    "blocks": _cmd_blocks,
    "metrics": _cmd_metrics,
}


if __name__ == "__main__":
    raise SystemExit(main())
