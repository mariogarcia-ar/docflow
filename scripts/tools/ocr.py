"""Lab tool for the OCR processor (``SCR-04``).

A thin caller: it parses arguments, builds a real contract object and calls either one of
its own processor's primitives or the ``process_ocr_image`` entry point. There is no
``--engine`` flag: the engine is fixed and never presented as a selectable option.

The tool is invoked by path, so the repository root and the ``src/`` layout are put on
``sys.path`` before the library is imported. That bootstrap is bench plumbing: it adds no
behaviour and reaches no engine.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

_TOOLS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _TOOLS_DIR.parents[1]
for _entry in (str(_REPO_ROOT), str(_REPO_ROOT / "src"), str(_TOOLS_DIR)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

import _cli  # noqa: E402  # reason: imported after the path bootstrap above

from docflow import ocr as ocr_processor  # noqa: E402
from docflow.ocr import (  # noqa: E402
    OCRContext,
    OCROptions,
    OCRRequest,
    primitives,
)
from docflow.ocr.primitives import composition  # noqa: E402
from docflow.ocr.primitives.errors import OCRPrimitiveError  # noqa: E402

Handler = Callable[[argparse.Namespace, argparse.ArgumentParser, Path, Path], int]


def build_parser() -> argparse.ArgumentParser:
    """Build the tool's argument parser.

    Returns:
        The parser, with every documented subcommand registered.
    """
    parser = argparse.ArgumentParser(
        prog="ocr.py",
        description="Lab bench for the OCR processor: one representation, or the contract.",
    )
    _cli.add_common_arguments(parser, identity=True)
    subparsers = parser.add_subparsers(
        dest="subcommand", required=True, metavar="SUBCOMMAND"
    )

    for name, help_text in (
        ("text", "The extraction's plain text."),
        ("md", "The extraction's Markdown."),
        ("json", "The structured document, serialized."),
        ("tables", "Detected tables, in reading order."),
        ("blocks", "Ordered blocks, in reading order."),
        ("metrics", "Content metrics, over the built document."),
    ):
        scoped = subparsers.add_parser(name, help=help_text)
        _cli.add_input_argument(scoped)
        _add_ocr_options(scoped)

    run = subparsers.add_parser("run", help="Run the OCR contract.")
    _cli.add_input_argument(run)
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
    parser = build_parser()
    args = parser.parse_args(argv)
    input_path = _cli.resolve_input(args, parser)
    root = _cli.output_root("ocr", input_path, out=args.out)
    _cli.print_header("ocr", args.subcommand, input_path, root)
    return HANDLERS[args.subcommand](args, parser, input_path, root)


def _options(args: argparse.Namespace, parser: argparse.ArgumentParser) -> OCROptions:
    """Build the OCR options the flags describe."""
    engine_options: dict[str, Any] = {}
    for item in args.engine_option or []:
        key, separator, value = item.partition("=")
        if not separator or not key:
            parser.error(f"--engine-option expects KEY=VALUE, got {item!r}")
        engine_options[key] = value
    return OCROptions(
        ocr=bool(args.ocr),
        layout=bool(args.layout),
        tables=bool(args.tables),
        reading_order=bool(args.reading_order),
        language=args.language,
        engine_options=engine_options,
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
    _cli.print_result(
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
    return _cli.exit_code_for(result)


HANDLERS: dict[str, Handler] = {
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
