#!/usr/bin/env python3
"""Lab tool for ``procesador-pdf`` — drive this processor by hand.

Owned by ``PDF-14``. A caller of ``docflow.pdf``, not a component of it: every subcommand
resolves to a library function or primitive, and nothing here re-implements extraction,
decoding or classification.

    python scripts/tools/pdf.py inspect  mi.pdf
    python scripts/tools/pdf.py split    mi.pdf
    python scripts/tools/pdf.py render   mi.pdf --page 3 --dpi 400
    python scripts/tools/pdf.py text     mi.pdf --page 1
    python scripts/tools/pdf.py blocks   mi.pdf --page 1
    python scripts/tools/pdf.py images   mi.pdf --page 1
    python scripts/tools/pdf.py classify mi.pdf
    python scripts/tools/pdf.py run      mi.pdf

Output defaults to ``var/tools/pdf/<stem>-<hash>/``, where the hash is of the input's bytes,
so two runs over the same file land in the same tree and an ``inspect`` after a ``run`` reads
what the run wrote.

Three boundaries hold, and each one is a decision rather than an accident:

* **A tool may reach ``pdf/primitives/`` directly.** That is what makes it a lab bench:
  ``render --page 3 --dpi 400`` drives ``render_page_to_image`` without a document run, and
  ``split`` drives ``split_pdf`` without rendering or text extraction. ``GEN-19`` forbids
  that reach from ``docflow.workflow/``; a tool sits outside both frontiers.
* **No library dependency.** Nothing under ``src/docflow/`` imports this file, so deleting
  ``scripts/`` leaves the library and its tests untouched.
* **No workflow decision.** Every subcommand executes unconditionally. The tool never
  decides reuse, never skips a stage and never consults an artifact's validity — ``REUSE`` /
  ``SKIP`` / ``FORCE`` belong to the orchestrator.

The input is never written to. Every subcommand reads the document and writes only under its
own output root.
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

from docflow.pdf import (  # noqa: E402 - the path has to be set first
    PDFContext,
    PDFOptions,
    PDFRequest,
)
from docflow.pdf.entrypoints import process_pdf  # noqa: E402
from docflow.pdf.primitives.composition import (  # noqa: E402
    PageContent,
    analyze_pdf_page,
    classify_pdf_page,
)
from docflow.pdf.primitives.document import (  # noqa: E402
    get_page_count,
    get_page_dimensions,
    get_pdf_metadata,
)
from docflow.pdf.primitives.images import extract_images_from_page  # noqa: E402
from docflow.pdf.primitives.naming import page_index_name  # noqa: E402
from docflow.pdf.primitives.render import render_page_to_image  # noqa: E402
from docflow.pdf.primitives.split import split_pdf  # noqa: E402
from docflow.pdf.primitives.text import (  # noqa: E402
    engine_report,
    extract_text_from_page,
    get_text_blocks,
)

DEFAULT_OUT_ROOT = Path("var/tools/pdf")
TOOL_NAME = "pdf"
HASH_LENGTH = 8


def run_directory(pdf_path: Path, out_root: Path) -> Path:
    """Return this invocation's output directory.

    The stem plus a short content hash, so the same bytes always land in the same tree. Two
    runs over a renamed copy of one file therefore share a directory, which is what makes a
    manual experiment reproducible.

    Args:
        pdf_path: The input document.
        out_root: The directory the tool writes under.

    Returns:
        ``<out_root>/<stem>-<hash>/``.
    """
    digest = hashlib.sha256(pdf_path.read_bytes()).hexdigest()[:HASH_LENGTH]
    return out_root / f"{pdf_path.stem}-{digest}"


def request_for(pdf_path: Path, output_dir: Path, dpi: int) -> PDFRequest:
    """Build a request that asks for every capability.

    Args:
        pdf_path: The document to read.
        output_dir: The run's output root.
        dpi: Render resolution.

    Returns:
        The request, with the tool's own identity in the correlation context so a run's
        artifacts are recognisable as lab output rather than as an orchestrator run.
    """
    return PDFRequest(
        pdf_path=pdf_path,
        output_dir=output_dir,
        options=PDFOptions(
            extract_pages=True,
            render=True,
            extract_text=True,
            extract_images=True,
            layout=True,
            dpi=dpi,
        ),
        context=PDFContext(document_id=f"lab-{pdf_path.stem}", workflow_run_id="lab"),
    )


def emit_json(payload: Any) -> None:
    """Print a payload as machine-readable JSON.

    Only called when ``--json`` was given. An earlier version printed JSON in both modes and
    then the human summary on top, so ``--json`` changed nothing except to add noise — the
    one thing a machine-readable flag must not do.

    Args:
        payload: The value to serialise.
    """
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


# ---------------------------------------------------------------------------------------
# Subcommands — one per public operation of `docflow.pdf`
# ---------------------------------------------------------------------------------------


def command_inspect(args: argparse.Namespace) -> int:
    """Print what the document reports about itself."""
    pdf_path: Path = args.pdf

    payload = {
        "metadata": get_pdf_metadata(pdf_path),
        "page_count": get_page_count(pdf_path),
        "page_dimensions": {
            page_index_name(page): get_page_dimensions(pdf_path, page)
            for page in range(1, get_page_count(pdf_path) + 1)
        },
    }

    if args.json:
        emit_json(payload)
    else:
        print(f"{pdf_path}  ({payload['page_count']} page(s))")
        for key in ("PDF version", "Page size", "Encrypted"):
            if key in payload["metadata"]:
                print(f"  {key:14s}: {payload['metadata'][key]}")
        print("  page sizes   :")
        for name, size in payload["page_dimensions"].items():
            print(f"    {name}: {size[0]} x {size[1]} pt")
    return 0


def command_split(args: argparse.Namespace) -> int:
    """Write one self-contained PDF per page, in the document layout.

    ``split_pdf`` writes flat ``page_NNN.pdf`` files; the tool arranges them into
    ``page_NNN/source/page.pdf`` so a manual ``split`` leaves the same tree a ``run`` does.
    That is arrangement, not reimplementation: the extraction is still the primitive's.

    The staging directory is used because the primitive's output names and the documented
    layout differ; nothing is published under a final name until the rename.
    """
    staging = args.run_dir / "_split"
    written = split_pdf(args.pdf, staging)

    placed: list[Path] = []
    for index, page_pdf in enumerate(written, start=1):
        target = args.run_dir / page_index_name(index) / "source" / "page.pdf"
        target.parent.mkdir(parents=True, exist_ok=True)
        page_pdf.replace(target)
        placed.append(target)

    # The staging directory is an implementation detail; leaving it would put an undeclared
    # entry in the run tree.
    for leftover in sorted(staging.rglob("*"), reverse=True):
        leftover.rmdir() if leftover.is_dir() else leftover.unlink()
    staging.rmdir()

    if args.json:
        emit_json({"pages": [str(path) for path in placed]})
    else:
        for path in placed:
            print(path)
        print(f"{len(placed)} page(s) written under {args.run_dir}")
    return 0


def command_render(args: argparse.Namespace) -> int:
    """Render one page to a PNG."""
    target = args.run_dir / page_index_name(args.page) / "render" / "page.png"
    written = render_page_to_image(args.pdf, args.page, target, dpi=args.dpi)

    if args.json:
        emit_json({"render": str(written), "dpi": args.dpi})
    else:
        print(f"{written}  ({args.dpi} dpi)")
    return 0


def command_text(args: argparse.Namespace) -> int:
    """Print one page's native text."""
    text = extract_text_from_page(args.pdf, args.page)

    if args.json:
        emit_json({"text": text})
    else:
        # The text itself, byte for byte: this subcommand exists to read the layer, and a
        # summary of it would be the tool interpreting what it is meant to show.
        sys.stdout.write(text)
    return 0


def command_blocks(args: argparse.Namespace) -> int:
    """Print one page's text blocks with their bounding boxes."""
    blocks = get_text_blocks(args.pdf, args.page)

    payload = [
        {
            "block_id": block.block_id,
            "text": block.text,
            "bbox": list(block.bbox) if block.bbox is not None else None,
        }
        for block in blocks
    ]
    if args.json:
        emit_json(payload)
    else:
        for block in payload:
            print(f"{block['block_id']}  {block['bbox']}  {block['text']}")
    return 0


def command_images(args: argparse.Namespace) -> int:
    """Extract one page's embedded images."""
    directory = args.run_dir / page_index_name(args.page) / "embedded_images"
    images = extract_images_from_page(args.pdf, args.page, directory)

    payload = [
        {
            "image_id": image.image_id,
            "path": str(image.path),
            "width": image.width,
            "height": image.height,
            "format": image.format,
            "bbox": list(image.bbox) if image.bbox is not None else None,
        }
        for image in images
    ]
    if args.json:
        emit_json(payload)
    else:
        print(f"{len(payload)} image(s) under {directory}")
        for image in payload:
            print(f"  {image['image_id']}  {image['width']}x{image['height']}")
    return 0


def command_classify(args: argparse.Namespace) -> int:
    """Print each page's metrics and its descriptive classification."""
    payload = []
    for page in range(1, get_page_count(args.pdf) + 1):
        report = engine_report(args.pdf, page)
        metrics = analyze_pdf_page(
            PageContent(
                page_number=page,
                text=report.text,
                text_blocks=get_text_blocks(args.pdf, page),
                # The listing, not an extraction: classifying must not write files.
                embedded_images=_image_records(args.pdf, page),
                page_dimensions=get_page_dimensions(args.pdf, page),
            )
        )
        payload.append(
            {
                "page_number": page,
                "classification": classify_pdf_page(metrics),
                "metrics": {
                    "characters": metrics.characters,
                    "words": metrics.words,
                    "text_blocks": metrics.text_blocks,
                    "images": metrics.images,
                    "text_coverage": metrics.text_coverage,
                    "image_coverage": metrics.image_coverage,
                    "largest_image_coverage": metrics.largest_image_coverage,
                },
            }
        )

    if args.json:
        emit_json(payload)
    else:
        for entry in payload:
            metrics = entry["metrics"]
            print(
                f"page {entry['page_number']}: {entry['classification']:5s} "
                f"{metrics['characters']:6d} chars  {metrics['images']} img  "
                f"text_cov={metrics['text_coverage']:.4f} "
                f"image_cov={metrics['image_coverage']:.4f}"
            )
    return 0


def _image_records(pdf_path: Path, page_number: int) -> list[Any]:
    """Return a page's embedded images without extracting them to disk.

    Args:
        pdf_path: The document.
        page_number: Page index, 1-based.

    Returns:
        The image records, carrying size and engine attributes but no written file.
    """
    from docflow.pdf.primitives.images import get_image_blocks

    return get_image_blocks(pdf_path, page_number)


def command_run(args: argparse.Namespace) -> int:
    """Process the whole document and print a summary of the result."""
    result = process_pdf(request_for(args.pdf, args.run_dir, args.dpi))

    payload = {
        "status": result.status,
        "validation": result.validation.status,
        "page_count": result.metadata.page_count,
        "engine": f"{result.metadata.engine} {result.metadata.engine_version}",
        "pages": [
            {
                "page_number": page.page_number,
                "status": page.status,
                "classification": page.classification,
                "artifacts": len(page.artifacts),
            }
            for page in result.pages
        ],
        "metrics": {
            "characters": result.metrics.characters,
            "words": result.metrics.words,
            "images": result.metrics.images,
        },
        "artifacts": len(result.artifacts),
        "errors": [
            {"type": error.type, "message": error.message} for error in result.errors
        ],
    }

    if args.json:
        emit_json(payload)
    else:
        print(f"{args.pdf} -> {payload['status']} ({payload['validation']})")
        print(f"  {payload['page_count']} page(s), {payload['artifacts']} artifact(s)")
        print(f"  engine: {payload['engine']}")
        for page in payload["pages"]:
            print(
                f"    page {page['page_number']}: {page['status']:7s} "
                f"{page['classification']:5s} {page['artifacts']} artifact(s)"
            )
        for error in payload["errors"]:
            print(f"  ! {error['type']}: {error['message']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the command line.

    Returns:
        The parser, with one subcommand per public operation of ``docflow.pdf``.
    """
    # The globals are attached to a parent parser and inherited by every subcommand, so
    # `pdf.py split mi.pdf --out dir` works as well as `pdf.py --out dir split mi.pdf`. An
    # earlier version declared them once on the top-level parser, where argparse accepts them
    # only *before* the subcommand — an operator putting the flag where it reads naturally
    # got "unrecognized arguments" instead of a run.
    parser = argparse.ArgumentParser(
        prog=f"python scripts/tools/{TOOL_NAME}.py",
        description="Drive the docflow PDF processor by hand.",
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    sub = parser.add_subparsers(dest="command", required=True)

    def leaf(name: str, help_text: str, *, page: bool, dpi: bool = False):
        child = sub.add_parser(name, help=help_text)
        child.add_argument("pdf", type=Path)
        # SUPPRESS: when the flag is given before the subcommand it is already set on the
        # top-level namespace, and a default here would overwrite it with the empty value.
        child.add_argument("--out", type=Path, default=argparse.SUPPRESS)
        child.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
        if page:
            child.add_argument("--page", type=int, required=True)
        if dpi:
            child.add_argument("--dpi", type=int, default=200)
        return child

    leaf("inspect", "what the document reports about itself", page=False)
    leaf("split", "one self-contained PDF per page", page=False)
    leaf("render", "render one page to a PNG", page=True, dpi=True)
    leaf("text", "print one page's native text", page=True)
    leaf("blocks", "print one page's text blocks", page=True)
    leaf("images", "extract one page's embedded images", page=True)
    leaf("classify", "per-page metrics and classification", page=False)
    leaf("run", "process the whole document", page=False, dpi=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Run one subcommand.

    Args:
        argv: The arguments, or ``None`` to read them from the process.

    Returns:
        The process exit code.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    # `--out` / `--json` are accepted on either side of the subcommand, because an operator
    # writes whichever reads naturally and both are reasonable. The two positions land on
    # different namespaces, so they are merged here rather than losing one to the other's
    # default — which is what happened when only the sub-parsers declared them (a flag before
    # the subcommand was silently dropped).

    if not args.pdf.exists():
        print(f"no such file: {args.pdf}", file=sys.stderr)
        return 2

    args.run_dir = run_directory(args.pdf, args.out)
    args.run_dir.mkdir(parents=True, exist_ok=True)
    args.dpi = getattr(args, "dpi", 200)

    handlers = {
        "inspect": command_inspect,
        "split": command_split,
        "render": command_render,
        "text": command_text,
        "blocks": command_blocks,
        "images": command_images,
        "classify": command_classify,
        "run": command_run,
    }

    try:
        return handlers[args.command](args)
    except Exception as failure:
        # A tool is an operator's surface: an unreadable document should print its typed
        # cause, not a traceback. The library's classification is preserved in the message.
        print(f"{type(failure).__name__}: {failure}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
