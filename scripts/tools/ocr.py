#!/usr/bin/env python3
"""Lab tool for ``procesador-ocr`` - drive this processor by hand.

Owned by ``OCR-14``. A caller of ``docflow.ocr``, not a component of it: every subcommand
resolves to a library function or primitive, and nothing here re-implements a conversion, a
measurement or a rendering.

    python scripts/tools/ocr.py run     page.png
    python scripts/tools/ocr.py text    page.png
    python scripts/tools/ocr.py md      page.png
    python scripts/tools/ocr.py json    page.png
    python scripts/tools/ocr.py tables  page.png
    python scripts/tools/ocr.py blocks  page.png
    python scripts/tools/ocr.py metrics page.png
    python scripts/tools/ocr.py diff    page-a.png page-b.png

Output defaults to ``var/tools/ocr/<stem>-<hash>/``, where the hash is of the input's bytes, so
two runs over the same file land in the same tree and a ``text`` after a ``run`` reads what the
run wrote.

Four boundaries hold, and each is a decision rather than an accident:

* **A tool may reach ``ocr/primitives/`` directly.** That is what makes it a lab bench:
  ``blocks`` drives ``preserve_reading_order`` without publishing anything, which is how an
  operator inspects ordering and bbox normalization in isolation. ``run`` still goes through
  ``process_ocr_image``, because that is the surface the orchestrator will use.
* **No library dependency.** Nothing under ``src/docflow/`` imports this file, so deleting
  ``scripts/`` leaves the library and its tests untouched.
* **Never reimplements.** ``md`` prints ``OCRResult.markdown``; it does not re-render Markdown
  from the blocks. ``tables`` prints ``OCRResult.tables``; it does not re-detect them. A second
  renderer here would be a second definition of the artifact and the two would drift.
* **No ``--engine`` flag.** Docling is this processor's only engine and is never a user-selectable
  setting; a flag would invent a knob the library refuses to have. ``diff`` compares two runs of
  the **same** input — never OCR against native text or against a VLM, which is a documental
  decision belonging to the orchestrator.

The input is never written to. Every subcommand reads the image and writes only under its own
output root.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPO_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from docflow.ocr import (  # noqa: E402
    OCRContext,
    OCROptions,
    OCRRequest,
    OCRResult,
    process_ocr_image,
)
from docflow.ocr.primitives.engine import engine_provenance  # noqa: E402
from docflow.ocr.primitives.metadata import (  # noqa: E402
    PROCESSOR_NAME,
    get_processor_version,
)

TOOL_NAME = "ocr"
HASH_LENGTH = 8
DEFAULT_OUT_ROOT = Path("var/tools/ocr")

METADATA_FILE_NAME = "metadata.json"
"""Named here rather than imported, because ``files`` owns the namespace the *processor* writes
and the tool reads it back by name. Importing the constant would tie the tool's reader to a module
whose tuple is restated for deletion; a test asserts the two names agree."""


def options_for(language: str | None) -> OCROptions:
    """Return the options every subcommand uses.

    Everything this processor can extract, enabled: the tool exists to exercise the processor as it
    is deployed, and a lab run that silently asked for less would be measuring a different pipeline
    than production runs.

    Args:
        language: The expected language tag, or ``None`` to leave it to the engine.

    Returns:
        The raw options.
    """
    return OCROptions(
        ocr=True,
        layout=True,
        tables=True,
        reading_order=True,
        language=language,
        engine_options={},
    )


def request_for(image_path: Path, output_dir: Path, language: str | None) -> OCRRequest:
    """Build a request with the identity of a lab run.

    Args:
        image_path: The image to process.
        output_dir: The run's output root, i.e. this processor's ``ocr/`` namespace.
        language: The expected language tag, or ``None``.

    Returns:
        The request, with the tool's own identity in the correlation context so a run's artifacts
        are recognisable as lab output rather than as an orchestrator run.
    """
    return OCRRequest(
        image_path=image_path,
        output_dir=output_dir,
        options=options_for(language),
        context=OCRContext(
            document_id=f"lab-{image_path.stem}", page_number=1, workflow_run_id="lab"
        ),
    )


def run_directory(image_path: Path, out_root: Path) -> Path:
    """Return this invocation's output directory.

    The stem plus a short content hash, so the same bytes always land in the same tree: two runs
    over a renamed copy of one file share a directory, which is what makes a manual experiment
    reproducible.

    Args:
        image_path: The input image.
        out_root: The directory the tool writes under.

    Returns:
        ``<out_root>/<stem>-<hash>/``.
    """
    digest = hashlib.sha256(image_path.read_bytes()).hexdigest()[:HASH_LENGTH]
    return out_root / f"{image_path.stem}-{digest}"


def emit_json(payload: Any) -> None:
    """Print a payload as machine-readable JSON.

    Only called when ``--json`` was given. Printing JSON in both modes and then the human summary
    on top would make ``--json`` change nothing except to add noise - the one thing a
    machine-readable flag must not do.

    Args:
        payload: The value to serialise.
    """
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


def result_payload(result: OCRResult) -> dict[str, Any]:
    """Expand a result into the JSON shape every subcommand reports.

    Keys are expanded field by field rather than produced by ``dataclasses.asdict``: this is a
    readout an operator inspects, so a record gaining a field must be a visible edit rather than a
    silent appearance in the output. The document's full text is deliberately absent - ``text``
    prints it on its own, and a summary that embedded it would bury the summary.

    Args:
        result: The run's result.

    Returns:
        The payload.
    """
    return {
        "status": result.status,
        "validation": {
            "status": result.validation.status,
            "errors": [
                {"type": error.type, "message": error.message}
                for error in result.validation.errors
            ],
            "missing_artifacts": [
                str(path) for path in result.validation.missing_artifacts
            ],
        },
        "engine": {
            "name": result.metadata.engine,
            "version": result.metadata.engine_version,
        },
        "processor": {
            "name": PROCESSOR_NAME,
            "version": get_processor_version(),
        },
        "input": str(result.metadata.input),
        "options": {
            "ocr": result.metadata.options.ocr,
            "layout": result.metadata.options.layout,
            "tables": result.metadata.options.tables,
            "reading_order": result.metadata.options.reading_order,
            "language": result.metadata.options.language,
        },
        "metrics": {
            "characters": result.metrics.characters,
            "words": result.metrics.words,
            "blocks": result.metrics.blocks,
            "tables": result.metrics.tables,
            "paragraphs": result.metrics.paragraphs,
            "text_density": result.metrics.text_density,
            "empty": result.metrics.empty,
            "structure_detected": result.metrics.structure_detected,
        },
        "layout": {
            "page_width": result.layout.page_width,
            "page_height": result.layout.page_height,
            "regions": len(result.layout.region_bboxes),
        },
        "reading_order": list(result.reading_order),
        "tables": [
            {
                "table_id": table.table_id,
                "index": table.index,
                "bbox": list(table.bbox) if table.bbox is not None else None,
                "rows": len(table.cells),
                "columns": len(table.cells[0]) if table.cells else 0,
            }
            for table in result.tables
        ],
        "blocks": [
            {
                "block_id": block.block_id,
                "type": block.type,
                "bbox": list(block.bbox) if block.bbox is not None else None,
                "level": block.level,
            }
            for block in result.blocks
        ],
        "artifacts": {
            "text": str(result.artifacts.text),
            "markdown": str(result.artifacts.markdown),
            "structured_document": str(result.artifacts.structured_document),
            "tables_dir": str(result.artifacts.tables_dir),
            "metadata": str(result.artifacts.metadata),
        },
        "timing": dict(result.metadata.timing),
        "error": (
            {"type": result.error.type, "message": result.error.message}
            if result.error is not None
            else None
        ),
    }


def _run(image_path: Path, run_dir: Path, language: str | None) -> OCRResult:
    """Run the processor over one image into a run directory.

    Args:
        image_path: The image to read.
        run_dir: The run's output root.
        language: The expected language tag, or ``None``.

    Returns:
        The result.
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    return process_ocr_image(request_for(image_path, run_dir, language))


# ---------------------------------------------------------------------------------------
# Subcommands - one per operation an operator needs
# ---------------------------------------------------------------------------------------


def command_run(args: argparse.Namespace) -> int:
    """Process the image through the processor's own entry point and summarise the result."""
    result = _run(args.image, args.run_dir, args.language)
    payload = result_payload(result)

    if args.json:
        emit_json(payload)
    else:
        print(
            f"{args.image} -> {payload['status']} ({payload['validation']['status']})"
        )
        print(
            f"  engine:    {payload['engine']['name']} {payload['engine']['version']}"
        )
        metrics = payload["metrics"]
        print(
            f"  content:   {metrics['characters']} chars, {metrics['words']} words, "
            f"{metrics['blocks']} blocks, {metrics['tables']} tables"
        )
        print(
            f"  layout:    {payload['layout']['page_width']}x"
            f"{payload['layout']['page_height']} ({payload['layout']['regions']} regions)"
        )
        print(f"  output:    {args.run_dir}")
        for name in sorted(payload["artifacts"]):
            print(f"    + {Path(payload['artifacts'][name]).name}")
        if payload["error"] is not None:
            print(
                f"  error:     {payload['error']['type']}: {payload['error']['message']}"
            )
    return 0 if result.status == "success" else 1


def command_text(args: argparse.Namespace) -> int:
    """Print the extraction as plain text, running into the output tree.

    The text is taken from ``OCRResult.text`` rather than read back from ``text.txt``: the result
    is what the processor hands a caller, and reading the file would make the tool's output depend
    on a write having succeeded. The run happens first so the artifacts exist for a later
    inspection.
    """
    result = _run(args.image, args.run_dir, args.language)
    if args.json:
        emit_json({"status": result.status, "text": result.text})
    else:
        print(result.text, end="")
    return 0 if result.status == "success" else 1


def command_md(args: argparse.Namespace) -> int:
    """Print ``OCRResult.markdown``, never a re-rendering of the blocks."""
    result = _run(args.image, args.run_dir, args.language)
    if args.json:
        emit_json({"status": result.status, "markdown": result.markdown})
    else:
        print(result.markdown, end="")
    return 0 if result.status == "success" else 1


def command_json(args: argparse.Namespace) -> int:
    """Print the ``document.json`` payload the processor built.

    ``structured_document`` is the payload the artifact holds, so this is the artifact's content
    rather than a readout derived beside it. Reading the file back would report the same object
    only when the write succeeded, which is what ``run`` is for.
    """
    result = _run(args.image, args.run_dir, args.language)
    payload = result.structured_document
    if args.json:
        emit_json(payload)
    else:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if result.status == "success" else 1


def command_tables(args: argparse.Namespace) -> int:
    """Print the detected tables, in reading order, with their cells."""
    result = _run(args.image, args.run_dir, args.language)
    tables = [
        {
            "table_id": table.table_id,
            "index": table.index,
            "bbox": list(table.bbox) if table.bbox is not None else None,
            "cells": [list(row) for row in table.cells],
            "markdown": table.markdown,
        }
        for table in result.tables
    ]

    if args.json:
        emit_json({"status": result.status, "tables": tables})
    elif not tables:
        print("no tables detected")
    else:
        for table in tables:
            rows, columns = (
                len(table["cells"]),
                len(table["cells"][0]) if table["cells"] else 0,
            )
            print(f"{table['table_id']}  ({rows} rows x {columns} columns)")
            print(table["markdown"])
            print()
    return 0 if result.status == "success" else 1


def command_blocks(args: argparse.Namespace) -> int:
    """Print every block with its normalized bbox, in the order the rule computed.

    The order shown is ``OCRResult.reading_order``, which is the published order. The engine's own
    arrival order is available from the extraction primitives, and exposing it here as a second
    column was rejected: a lab tool that printed two orders side by side would invite a reader to
    treat them as alternatives, and only one of them is the artifact.
    """
    result = _run(args.image, args.run_dir, args.language)
    by_id = {block.block_id: block for block in result.blocks}
    rows = []
    for identifier in result.reading_order:
        block = by_id.get(identifier)
        if block is None:
            continue
        rows.append(
            {
                "block_id": block.block_id,
                "type": block.type,
                "bbox": list(block.bbox) if block.bbox is not None else None,
                "level": block.level,
                "characters": len(block.text),
                "text": block.text,
            }
        )

    if args.json:
        emit_json({"status": result.status, "blocks": rows})
    else:
        print(f"{len(rows)} blocks, in reading order")
        for row in rows:
            box = row["bbox"]
            where = (
                "no bbox"
                if box is None
                else f"({box[0]:.4f}, {box[1]:.4f}, {box[2]:.4f}, {box[3]:.4f})"
            )
            preview = row["text"].replace("\n", " ")[:60]
            print(f"  {row['block_id']:<12} {row['type']:<10} {where}  {preview}")
    return 0 if result.status == "success" else 1


def command_metrics(args: argparse.Namespace) -> int:
    """Print the content metrics, and the layout frame they were measured in.

    The frame is printed beside the figures because ``text_density`` is characters per unit of page
    area and is meaningless without it: this processor normalizes the layout, so the area is ``1.0``
    and the density equals the character count, while the same measurement in the engine's pixel
    frame gives a much smaller figure. Both are right for the frame they describe.
    """
    result = _run(args.image, args.run_dir, args.language)
    payload = {
        "status": result.status,
        "engine": engine_provenance(),
        "metrics": {
            "characters": result.metrics.characters,
            "words": result.metrics.words,
            "blocks": result.metrics.blocks,
            "tables": result.metrics.tables,
            "paragraphs": result.metrics.paragraphs,
            "text_density": result.metrics.text_density,
            "empty": result.metrics.empty,
            "structure_detected": result.metrics.structure_detected,
        },
        "frame": {
            "page_width": result.layout.page_width,
            "page_height": result.layout.page_height,
            "area": result.layout.page_width * result.layout.page_height,
        },
    }

    if args.json:
        emit_json(payload)
    else:
        metrics = payload["metrics"]
        frame = payload["frame"]
        print(f"{args.image}")
        print(f"  characters:  {metrics['characters']}")
        print(f"  words:       {metrics['words']}")
        print(f"  blocks:      {metrics['blocks']}")
        print(f"  paragraphs:  {metrics['paragraphs']}")
        print(f"  tables:      {metrics['tables']}")
        print(f"  empty:       {metrics['empty']}")
        print(f"  structure:   {metrics['structure_detected']}")
        print(f"  text_density:{metrics['text_density']}")
        print(
            f"  frame:       {frame['page_width']}x{frame['page_height']} (area {frame['area']})"
        )
        print(
            "  note: text_density is characters per unit of page area, in the frame above."
        )
    return 0 if result.status == "success" else 1


def functional_content(output_dir: Path) -> dict[str, str]:
    """Return every published artifact that is not allowed to vary between runs.

    ``metadata.json`` is excluded because it is the one artifact whose content legitimately moves:
    it carries the run's wall-clock timing. Every other artifact must be reproducible, which is
    what invariant 1 means, and a whole-tree byte comparison would fail on every correct run.

    Args:
        output_dir: The ``ocr/`` namespace of a run.

    Returns:
        Each functional artifact's content, keyed by its path relative to the namespace.
    """
    excluded = {METADATA_FILE_NAME}
    return {
        str(path.relative_to(output_dir)): path.read_text(encoding="utf-8")
        for path in sorted(output_dir.rglob("*"))
        if path.is_file() and path.name not in excluded
    }


def diff_payload(first: Path, second: Path) -> dict[str, Any]:
    """Compare two runs' functional content.

    Args:
        first: The first run's namespace.
        second: The second run's namespace.

    Returns:
        The comparison: whether the content matched, which files differed, and which were present
        in only one of the two.
    """
    left = functional_content(first)
    right = functional_content(second)
    shared = sorted(set(left) & set(right))

    differing = [name for name in shared if left[name] != right[name]]
    return {
        "first": str(first),
        "second": str(second),
        "identical": not differing and set(left) == set(right),
        "compared": shared,
        "differing": differing,
        "only_in_first": sorted(set(left) - set(right)),
        "only_in_second": sorted(set(right) - set(left)),
        "excluded": [METADATA_FILE_NAME],
    }


def command_diff(args: argparse.Namespace) -> int:
    """Run the same input twice and report whether the functional content is identical.

    The tool-side counterpart of ``OCR-12``'s invariant 1. It compares the **functional content** -
    everything the processor publishes except ``metadata.json``, which is the one artifact permitted
    to carry timing - because raw-byte equality of the whole tree would fail on every correct run.

    Both runs read the *same* input. Comparing two different sources is the orchestrator's decision
    (which source wins, and whether OCR runs at all) and this tool does not make it: ``--second-out``
    names a second output directory, never a second image.

    The two namespaces are deliberately different directories. Running twice into one would have the
    second run overwrite the first, and the comparison would then be between a run and itself.
    """
    first_dir = args.run_dir
    second_dir = args.second_out
    if second_dir is None:
        second_dir = first_dir.parent / f"{first_dir.name}-second"

    first = _run(args.image, first_dir, args.language)
    second = _run(args.image, second_dir, args.language)

    payload = diff_payload(first_dir, second_dir)
    payload["status"] = {"first": first.status, "second": second.status}

    if args.json:
        emit_json(payload)
    else:
        verdict = "identical" if payload["identical"] else "DIFFERENT"
        print(f"{args.image}: two runs are {verdict}")
        print(f"  first:  {first_dir}")
        print(f"  second: {second_dir}")
        print(
            f"  compared {len(payload['compared'])} artifacts, excluding {METADATA_FILE_NAME}"
        )
        for name in payload["differing"]:
            print(f"    ! {name} differs")
        for name in payload["only_in_first"]:
            print(f"    ! {name} only in the first run")
        for name in payload["only_in_second"]:
            print(f"    ! {name} only in the second run")
    return 0 if payload["identical"] else 1


def build_parser() -> argparse.ArgumentParser:
    """Build the command line.

    Returns:
        The parser, with one subcommand per operation of ``docflow.ocr``.
    """
    # The globals are attached to the top-level parser *and* to each sub-parser with
    # `argparse.SUPPRESS`, so `ocr.py text p.png --out dir` works as well as
    # `ocr.py --out dir text p.png`. Declaring them on only one side means an operator putting the
    # flag where it reads naturally gets "unrecognized arguments" or silently loses the value.
    parser = argparse.ArgumentParser(
        prog=f"python scripts/tools/{TOOL_NAME}.py",
        description="Drive the docflow OCR processor by hand.",
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--language",
        default=None,
        help="expected language tag; omitted leaves it to the engine",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def leaf(name: str, help_text: str):
        child = sub.add_parser(name, help=help_text)
        child.add_argument("image", type=Path)
        child.add_argument("--out", type=Path, default=argparse.SUPPRESS)
        child.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
        child.add_argument("--language", default=argparse.SUPPRESS)
        return child

    leaf("run", "process the image and publish the ocr namespace")
    leaf("text", "plain text to stdout only")
    leaf("md", "the published Markdown to stdout only")
    leaf("json", "the document.json payload to stdout")
    leaf("tables", "detected tables, in reading order")
    leaf("blocks", "blocks with their normalized bboxes, in reading order")
    leaf("metrics", "the content metrics and the frame they were measured in")

    diff = leaf("diff", "run the same input twice and compare functional content")
    diff.add_argument("--second-out", type=Path, default=None)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Run one subcommand.

    Args:
        argv: The arguments, or ``None`` to read them from the process.

    Returns:
        The process exit code.
    """
    args = build_parser().parse_args(argv)

    if not args.image.exists():
        print(f"no such file: {args.image}", file=sys.stderr)
        return 2

    args.run_dir = run_directory(args.image, args.out)
    args.run_dir.mkdir(parents=True, exist_ok=True)

    handlers = {
        "run": command_run,
        "text": command_text,
        "md": command_md,
        "json": command_json,
        "tables": command_tables,
        "blocks": command_blocks,
        "metrics": command_metrics,
        "diff": command_diff,
    }

    try:
        return handlers[args.command](args)
    except Exception as failure:
        # A tool is an operator's surface: a bad image should print its cause, not a traceback.
        print(f"{type(failure).__name__}: {failure}", file=sys.stderr)
        return 1


__all__ = [
    "DEFAULT_OUT_ROOT",
    "build_parser",
    "main",
    "options_for",
    "request_for",
    "result_payload",
    "run_directory",
]

if __name__ == "__main__":
    raise SystemExit(main())
