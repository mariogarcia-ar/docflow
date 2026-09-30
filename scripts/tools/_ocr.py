"""The OCR bench's shared command layer (``SCR-14``).

``ocr.py`` runs one image and ``batch_ocr.py`` runs a folder tree: two callers of the same seven
methods. This module holds them, so neither tool owns a second copy of a payload, a flag or a
conversion — the flags are registered by :func:`build_subcommands` and the methods are reached
through :data:`COMMANDS`, both by name.

It is **not** a tool: it has no ``main``, it prints nothing, and it is never invoked directly. A
method does the work and returns the payload; the caller decides whether that becomes stdout
(:mod:`_cli`'s printers) or a file beside the artifacts. The processor's typed failures are raised,
never caught here — a tool prints them and exits ``1``.

Two of the seven methods publish: ``run`` publishes the contract's document, and ``text`` publishes
the reading it reports as ``text.txt``. The other five build a payload and write nothing.

It carries the lab-bench exception of ``subplan-scripts.md`` §3.2 for its own processor: it may
drive ``docflow.ocr.primitives``.

There is no ``--engine`` flag: the engine is fixed and never presented as a selectable option.
``--tables`` is on for the ``tables`` subcommand and off everywhere else: detection is engine
work, so the command whose whole answer is the detected tables asks for them itself rather than
requiring the caller to say it twice.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any, Final

import _cli

from docflow import ocr as ocr_processor
from docflow.ocr import OCRContext, OCROptions, OCRRequest, primitives
from docflow.ocr.primitives import composition
from docflow.ocr.primitives.errors import OCRPrimitiveError

#: One subcommand per method, with the help text both tools print.
SUBCOMMANDS: tuple[tuple[str, str], ...] = (
    ("text", "The extraction's plain text, published as text.txt."),
    ("md", "The extraction's Markdown."),
    ("json", "The structured document, serialized."),
    ("tables", "Detected tables, in reading order."),
    ("blocks", "Ordered blocks, in reading order."),
    ("metrics", "Content metrics, over the built document."),
    ("run", "Run the OCR contract."),
)

#: The inputs the OCR processor takes, matched case-insensitively. Its input *is* an image, so the
#: set is the one the image processor can decode — stated here rather than imported from the image
#: bench: which inputs a processor takes is that processor's own fact.
SUFFIXES: Final[tuple[str, ...]] = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp")

#: The name ``text`` publishes the text it read under. It is the processor's own name for the same
#: content (``ocr/entrypoints.py`` ``TEXT_NAME``, restated in ``ArtifactPaths.text``), so a ``text``
#: run and a ``run`` run of one image leave one artifact name for one reading. Stated here rather
#: than imported: the bench reaches a processor's public surface and its own primitives, and the
#: package re-exports the contract, not its entry point's private names.
TEXT_NAME: Final[Path] = Path("text.txt")

#: What one method returns: the payload its caller prints, or writes beside the artifacts.
Payload = dict[str, Any]

#: A method as the tools call it: the parsed flags, the parser to refuse through, the input and
#: the directory that input's run writes under.
Command = Callable[[argparse.Namespace, argparse.ArgumentParser, Path, Path], Payload]

#: The help ``--tables`` prints. The command whose answer *is* the detected tables says so,
#: instead of reading like a flag the caller has to remember: detection is engine work, and a
#: ``tables`` run that did not ask for it could only ever report the empty list.
TABLE_FLAG_HELP: Final[dict[bool, str]] = {
    False: "Detect and extract tables.",
    True: "Detect and extract tables; on by default, because this command answers with them.",
}


def _add_ocr_options(
    subparser: argparse.ArgumentParser, *, tables_by_default: bool = False
) -> None:
    """Add the OCR capability flags a subcommand builds its options from.

    Args:
        subparser: The subcommand's parser.
        tables_by_default: Whether table detection is on when the caller states nothing. It is
            on for ``tables`` and for that command alone — the same shape as ``--ocr`` being on
            because OCR is the processor's purpose: the capability a command exists to show is
            not a flag the caller has to remember. ``--no-tables`` still states the opposite.
    """
    subparser.add_argument(
        "--ocr",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run OCR; on by default because it is the processor's purpose.",
    )
    subparser.add_argument("--layout", action="store_true", help="Extract layout.")
    subparser.add_argument(
        "--tables",
        action=argparse.BooleanOptionalAction,
        default=tables_by_default,
        help=TABLE_FLAG_HELP[tables_by_default],
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


def build_subcommands(
    subparsers: Any, *, input_argument: bool = True
) -> dict[str, argparse.ArgumentParser]:
    """Register every subcommand with the flags that are its own.

    Args:
        subparsers: The group :func:`_cli.build_parser` returned.
        input_argument: Whether a subcommand takes the input positional. ``ocr.py`` runs one
            file, so it does; ``batch_ocr.py`` takes a folder once and walks it, so it does not.

    Returns:
        The subcommand parsers by name, for a tool that wants to reach one directly.
    """
    parsers: dict[str, argparse.ArgumentParser] = {}
    for name, help_text in SUBCOMMANDS:
        parser = _cli.add_subcommand(
            subparsers, name, help_text, input_argument=input_argument
        )
        _add_ocr_options(parser, tables_by_default=name == "tables")
        if name == "run":
            parser.add_argument(
                "--page", type=int, default=1, help="Logical page number, 1-based."
            )
        parsers[name] = parser
    return parsers


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
    """Run one engine conversion and return it with the options that configured it.

    The engine call is typed here the way the processor's own entrypoint types it: its exception
    class cannot be named without importing the engine, so whatever escapes the call is the engine
    failing. Reporting that as a typed failure is what keeps one bad image from ending a corpus
    run at the first input, and it is the same mapping the contract path applies.
    """
    normalized = primitives.normalize_docling_options(_options(args, parser))
    config = primitives.configure_image_pipeline(normalized)
    try:
        conversion = primitives.convert_image_with_docling(input_path, config)
    except OCRPrimitiveError:
        raise
    except Exception as exc:  # pylint: disable=broad-exception-caught
        # The engine's own exception class is not nameable without importing the engine; the
        # typed failure below is the point of the mapping, exactly as in the processor's seam.
        raise primitives.typed_failure(
            "ENGINE_ERROR",
            f"the {primitives.ENGINE_NAME} conversion of {input_path} raised",
            recoverable=False,
            metadata={"engine_error": str(exc), "image_path": str(input_path)},
        ) from exc
    return conversion, normalized


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


def _text(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> Payload:
    """Read one conversion's plain text and publish it as the run's ``text.txt``.

    The text is normalized before it is written, which is the form the processor's own ``run``
    gives ``text.txt`` (``normalize_ocr_text``): the bench publishes the *same* artifact for the
    same image, under the same name, so two runs of one input cannot be read as two readings. It
    is what the payload reports, too — the processor's rule is that what the result states is
    exactly what the file holds.
    """
    conversion, _ = _conversion(args, parser, input_path)
    text = primitives.normalize_ocr_text(primitives.extract_docling_text(conversion))
    published = primitives.write_text_atomic(root / TEXT_NAME, text)
    return {
        "input": str(input_path),
        "text": text,
        "output": str(published),
    }


def _md(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> Payload:
    """Read one conversion's Markdown."""
    del root
    conversion, _ = _conversion(args, parser, input_path)
    return {
        "input": str(input_path),
        "markdown": primitives.extract_docling_markdown(conversion),
    }


def _json(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> Payload:
    """Build and serialize the structured document."""
    del root
    _, document = _document(args, parser, input_path)
    return {"input": str(input_path), "document": asdict(document)}


def _tables(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> Payload:
    """Read the detected tables, in reading order."""
    del root
    ordered, _ = _document(args, parser, input_path)
    return {
        "input": str(input_path),
        "tables": [asdict(table) for table in ordered.tables],
    }


def _blocks(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> Payload:
    """Read the ordered blocks."""
    del root
    ordered, _ = _document(args, parser, input_path)
    return {
        "input": str(input_path),
        "blocks": [asdict(block) for block in ordered.blocks],
        "reading_order": list(ordered.reading_order),
    }


def _metrics(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> Payload:
    """Measure the built document."""
    del root
    _, document = _document(args, parser, input_path)
    return {
        "input": str(input_path),
        "metrics": asdict(composition.analyze_ocr_result(document)),
    }


def _artifact_payload(result: Any) -> Payload | None:
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


def _run(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> Payload:
    """Run the OCR contract and report what it published.

    The run identity is derived from the program's own name (``ocr.py``, ``batch_ocr.py``), so a
    batch's run id says which tool produced it unless the caller pinned one.
    """
    document_id, run_id = _cli.identity_for(args, Path(parser.prog).stem, input_path)
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
    return {
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
    }


#: The seven methods by subcommand name. Both tools dispatch through this, so a subcommand's
#: behaviour lives in exactly one place.
COMMANDS: dict[str, Command] = {
    "text": _text,
    "md": _md,
    "json": _json,
    "tables": _tables,
    "blocks": _blocks,
    "metrics": _metrics,
    "run": _run,
}
