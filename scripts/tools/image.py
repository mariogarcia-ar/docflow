"""Lab tool for the image processor (``SCR-03``).

A thin caller: its parser, its flags and one handler per subcommand are all it owns. The
frame around them — where the run writes, how the input resolves, the header, the printers
and the exit code — lives in :mod:`scripts.tools._cli`.

The tool adds no transformation, no threshold and no default: the two preparation variants
are two distinct pipelines, and the tool never aliases one to the other.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any, Final

import _cli

from docflow import image as image_processor
from docflow.image import ImageContext, ImageOptions, ImageRequest, primitives
from docflow.image.primitives import ImagePrimitiveError, composition

#: Subcommands that publish no file: their report is the stdout summary, so the run header
#: says so instead of naming an output root no run creates. ``normalize``, ``ocr-ready``,
#: ``vlm-ready`` and ``run`` do write. Verified by the hand run in
#: ``docs/plan/bitacora.md`` (2026-09-27).
REPORT_ONLY: Final[tuple[str, ...]] = ("info", "metrics", "classify")


def build_parser() -> argparse.ArgumentParser:
    """Build the tool's argument parser.

    Returns:
        The parser, with every documented subcommand registered.
    """
    parser, subparsers = _cli.build_parser(
        "image.py",
        "Lab bench for the image processor: one pipeline, or the contract.",
        identity=True,
    )

    for name, help_text in (
        ("info", "File and pixel facts, read without measuring quality."),
        ("metrics", "The technical analysis: quality, orientation, skew, regions."),
        ("classify", "The image's descriptive classification."),
    ):
        _cli.add_subcommand(subparsers, name, help_text)

    for name, help_text in (
        ("normalize", "Produce normalized.png."),
        ("ocr-ready", "Produce ocr_ready.png through its own pipeline."),
        ("vlm-ready", "Produce vlm_ready.png through its own pipeline."),
    ):
        pipeline = _cli.add_subcommand(subparsers, name, help_text)
        _add_corrections(pipeline)

    run = _cli.add_subcommand(subparsers, "run", "Run the image contract.")
    run.add_argument(
        "--from-page", action="store_true", help="Use the page-level wrapper."
    )
    run.add_argument(
        "--page", type=int, default=1, help="Logical page number, 1-based."
    )
    run.add_argument(
        "--normalize",
        action="store_true",
        help="Produce the normalized representation.",
    )
    run.add_argument(
        "--prepare-for-ocr", action="store_true", help="Produce the OCR variant."
    )
    run.add_argument(
        "--prepare-for-vlm", action="store_true", help="Produce the VLM variant."
    )
    _add_corrections(run)
    return parser


def _add_corrections(subparser: argparse.ArgumentParser) -> None:
    """Add the two frame corrections a preparation subcommand may ask for."""
    subparser.add_argument(
        "--correct-orientation",
        action="store_true",
        help="Apply the detected orientation correction.",
    )
    subparser.add_argument(
        "--deskew", action="store_true", help="Apply the detected skew correction."
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the tool.

    Args:
        argv: The arguments, defaulting to ``sys.argv[1:]``.

    Returns:
        The process exit code: ``0`` when the run produced a result, ``1`` when the library
        returned a typed failure.
    """
    return _cli.run_tool(
        "image", build_parser(), HANDLERS, argv, report_only=REPORT_ONLY
    )


def _decoded(input_path: Path) -> tuple[Any, Any, Any]:
    """Decode an image and return it with its file facts and its measurements."""
    pixels = primitives.load_image(input_path)
    facts = primitives.get_image_metadata(input_path, pixels)
    return pixels, facts, primitives.analyze_image(pixels, facts)


def _pipeline_options(args: argparse.Namespace, kind: str) -> ImageOptions:
    """Build the options one preparation subcommand runs under.

    The variant flags are read off the subcommand itself — ``normalize`` produces the
    normalized representation — while the two corrections come from the caller's flags. No
    correction is ever applied because a measurement suggested it and nobody asked.
    """
    return ImageOptions(
        normalize=kind == "normalize",
        prepare_for_ocr=kind == "ocr-ready",
        prepare_for_vlm=kind == "vlm-ready",
        correct_orientation=bool(args.correct_orientation),
        deskew=bool(args.deskew),
    )


def _artifact_payload(prepared: Any) -> dict[str, Any]:
    """Build a payload from one prepared representation's own fields."""
    artifact = prepared.artifact
    return {
        "path": str(artifact.path),
        "kind": artifact.kind,
        "width": artifact.width,
        "height": artifact.height,
        "format": artifact.format,
        "size": artifact.size,
        "transformations": list(prepared.transformations),
        "metrics": asdict(prepared.metrics),
    }


def _cmd_info(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> int:
    """Print the file and pixel facts of one image."""
    del parser, root
    try:
        _, facts, _ = _decoded(input_path)
    except ImagePrimitiveError as failure:
        return _cli.print_error([failure.error])
    _cli.print_result(
        {
            "input": str(input_path),
            "format": facts.format,
            "size": facts.size,
            "width": facts.width,
            "height": facts.height,
            "channels": facts.channels,
            "resolution": facts.resolution,
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
    """Print the technical analysis of one image."""
    del parser, root
    try:
        _, _, metrics = _decoded(input_path)
    except ImagePrimitiveError as failure:
        return _cli.print_error([failure.error])
    _cli.print_result(
        {"input": str(input_path), "metrics": asdict(metrics)}, as_json=args.json
    )
    return 0


def _cmd_classify(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> int:
    """Print one image's measurements and its descriptive classification."""
    del parser, root
    try:
        _, _, metrics = _decoded(input_path)
    except ImagePrimitiveError as failure:
        return _cli.print_error([failure.error])
    _cli.print_result(
        {
            "input": str(input_path),
            "metrics": asdict(metrics),
            "classification": composition.classify_image(metrics),
        },
        as_json=args.json,
    )
    return 0


def _prepared_command(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
    *,
    kind: str,
    pipeline: Callable[..., Any],
    destination_name: str,
) -> int:
    """Run one preparation pipeline and print what it published."""
    del parser
    try:
        pixels, _, metrics = _decoded(input_path)
        prepared = pipeline(
            pixels,
            metrics,
            _pipeline_options(args, kind),
            root / destination_name,
        )
    except ImagePrimitiveError as failure:
        return _cli.print_error([failure.error])
    _cli.print_result(
        {"input": str(input_path), "representation": _artifact_payload(prepared)},
        as_json=args.json,
    )
    return 0


def _cmd_normalize(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> int:
    """Produce the general normalized representation."""
    return _prepared_command(
        args,
        parser,
        input_path,
        root,
        kind="normalize",
        pipeline=primitives.prepare_normalized_image,
        destination_name="normalized.png",
    )


def _cmd_ocr_ready(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> int:
    """Produce the OCR-optimized variant."""
    return _prepared_command(
        args,
        parser,
        input_path,
        root,
        kind="ocr-ready",
        pipeline=primitives.prepare_image_for_ocr,
        destination_name="ocr_ready.png",
    )


def _cmd_vlm_ready(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> int:
    """Produce the VLM-optimized variant through its own pipeline."""
    return _prepared_command(
        args,
        parser,
        input_path,
        root,
        kind="vlm-ready",
        pipeline=primitives.prepare_image_for_vlm,
        destination_name="vlm_ready.png",
    )


def _run_options(args: argparse.Namespace) -> ImageOptions:
    """Build the transformations a run asks for, from the caller's flags."""
    return ImageOptions(
        normalize=bool(args.normalize),
        prepare_for_ocr=bool(args.prepare_for_ocr),
        prepare_for_vlm=bool(args.prepare_for_vlm),
        correct_orientation=bool(args.correct_orientation),
        deskew=bool(args.deskew),
    )


def _run_payload(result: Any) -> dict[str, Any]:
    """Build a payload from an image result's own fields."""
    context = result.metadata.context
    return {
        "status": str(result.status),
        "document_id": context.document_id,
        "page_number": context.page_number,
        "workflow_run_id": context.workflow_run_id,
        "source": {
            "path": str(result.source.path),
            "width": result.source.width,
            "height": result.source.height,
            "format": result.source.format,
            "size": result.source.size,
        },
        "classification": result.classification,
        "transformations": list(result.transformations),
        "normalized": None
        if result.normalized is None
        else str(result.normalized.path),
        "ocr_ready": None
        if result.variants.ocr_ready is None
        else str(result.variants.ocr_ready.path),
        "vlm_ready": None
        if result.variants.vlm_ready is None
        else str(result.variants.vlm_ready.path),
        "artifacts": [str(ref.path) for ref in result.artifacts],
        "validation": {
            "status": result.validation.status,
            "errors": [asdict(error) for error in result.validation.errors],
        },
        "error": None if result.error is None else asdict(result.error),
    }


def _cmd_run(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> int:
    """Run the image contract, directly or through the page-level wrapper."""
    del parser
    document_id, run_id = _cli.identity_for(args, "image", input_path)
    options = _run_options(args)
    if args.from_page:
        result = image_processor.process_image_from_page(
            input_path, root, options, document_id, int(args.page), run_id
        )
    else:
        result = image_processor.process_image(
            ImageRequest(
                image_path=input_path,
                output_dir=root,
                options=options,
                context=ImageContext(
                    document_id=document_id,
                    page_number=int(args.page),
                    workflow_run_id=run_id,
                ),
            )
        )
    return _cli.report_result(result, _run_payload(result), as_json=args.json)


HANDLERS: dict[str, _cli.Handler] = {
    "info": _cmd_info,
    "metrics": _cmd_metrics,
    "normalize": _cmd_normalize,
    "ocr-ready": _cmd_ocr_ready,
    "vlm-ready": _cmd_vlm_ready,
    "classify": _cmd_classify,
    "run": _cmd_run,
}


if __name__ == "__main__":
    raise SystemExit(main())
