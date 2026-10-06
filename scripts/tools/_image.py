"""The image bench's shared command layer (``SCR-13``).

``image.py`` runs one file and ``batch_image.py`` runs a folder tree: two callers of the same seven
methods. This module holds them, so neither tool owns a second copy of a payload, a flag or a
refusal — the flags are registered by :func:`build_subcommands` and the methods are reached through
:data:`COMMANDS`, both by name.

It is **not** a tool: it has no ``main``, it prints nothing, and it is never invoked directly. A
method does the work and returns the payload; the caller decides whether that becomes stdout
(:mod:`_cli`'s printers) or a file beside the artifacts. The processor's typed failures are raised,
never caught here — a tool prints them and exits ``1``.

It carries the lab-bench exception of ``subplan-scripts.md`` §3.2 for its own processor: it may
drive ``docflow.image.primitives``.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any, Final

import _cli

from docflow import image as image_processor
from docflow.image import (
    ImageContext,
    ImageOptions,
    ImageRequest,
    primitives,
    representation_suffix,
)
from docflow.image.primitives import composition

#: One subcommand per method, with the help text both tools print.
SUBCOMMANDS: tuple[tuple[str, str], ...] = (
    ("info", "File and pixel facts, read without measuring quality."),
    ("metrics", "The technical analysis: quality, orientation, skew, regions."),
    ("normalize", "Produce the normalized representation."),
    ("ocr-ready", "Produce ocr_ready.png through its own pipeline."),
    ("vlm-ready", "Produce the VLM variant through its own pipeline."),
    ("classify", "The image's descriptive classification."),
    ("run", "Run the image contract."),
)

#: The subcommands whose representation keeps the page's tone, and which therefore take a
#: quality factor. ``ocr-ready`` is deliberately absent: its pipeline binarizes the page, and
#: a lossy encoder would ring around every glyph edge.
LOSSY_KINDS: Final[tuple[str, ...]] = ("normalize", "vlm-ready")

#: What the ``--quality`` flag means when it is not stated. Named, because the absence is a
#: decision the caller made and the artifact has to say which container it got.
QUALITY_HELP: Final[str] = (
    "Publish the representation as a lossy JPEG at this quality (1-100); "
    "without it the artifact is a lossless PNG."
)

#: The inputs the image processor takes, matched case-insensitively: what it can decode.
SUFFIXES: Final[tuple[str, ...]] = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp")

#: What one method returns: the payload its caller prints, or writes beside the artifacts.
Payload = dict[str, Any]

#: A method as the tools call it: the parsed flags, the parser to refuse through, the input and
#: the directory that input's run writes under.
Command = Callable[[argparse.Namespace, argparse.ArgumentParser, Path, Path], Payload]


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


def _add_quality(subparser: argparse.ArgumentParser) -> None:
    """Add the quality factor, on the subcommands whose representation may be lossy."""
    subparser.add_argument("--quality", type=int, default=None, help=QUALITY_HELP)


def build_subcommands(
    subparsers: Any, *, input_argument: bool = True
) -> dict[str, argparse.ArgumentParser]:
    """Register every subcommand with the flags that are its own.

    Args:
        subparsers: The group :func:`_cli.build_parser` returned.
        input_argument: Whether a subcommand takes the input positional. ``image.py`` runs one
            file, so it does; ``batch_image.py`` takes a folder once and walks it, so it does not.

    Returns:
        The subcommand parsers by name, for a tool that wants to reach one directly.
    """
    parsers: dict[str, argparse.ArgumentParser] = {}
    for name, help_text in SUBCOMMANDS:
        parser = _cli.add_subcommand(
            subparsers, name, help_text, input_argument=input_argument
        )
        if name in ("normalize", "ocr-ready", "vlm-ready"):
            _add_corrections(parser)
            if name in LOSSY_KINDS:
                _add_quality(parser)
        elif name == "run":
            parser.add_argument(
                "--from-page", action="store_true", help="Use the page-level wrapper."
            )
            parser.add_argument(
                "--page", type=int, default=1, help="Logical page number, 1-based."
            )
            parser.add_argument(
                "--normalize",
                action="store_true",
                help="Produce the normalized representation.",
            )
            parser.add_argument(
                "--prepare-for-ocr",
                action="store_true",
                help="Produce the OCR variant.",
            )
            parser.add_argument(
                "--prepare-for-vlm",
                action="store_true",
                help="Produce the VLM variant.",
            )
            _add_corrections(parser)
            _add_quality(parser)
        parsers[name] = parser
    return parsers


def _decoded(input_path: Path) -> tuple[Any, Any, Any]:
    """Decode an image and return it with its file facts and its measurements."""
    pixels = primitives.load_image(input_path)
    facts = primitives.get_image_metadata(input_path, pixels)
    return pixels, facts, primitives.analyze_image(pixels, facts)


def _quality(args: argparse.Namespace, kind: str) -> int | None:
    """Return the quality factor stated for ``kind``, or ``None`` when none applies.

    Only the kinds whose representation keeps the page's tone take the flag, so the
    binarized ``ocr-ready`` pipeline is handed ``None`` and cannot quietly degrade it.
    """
    if kind not in LOSSY_KINDS:
        return None
    stated = args.quality
    return None if stated is None else int(stated)


def _pipeline_options(args: argparse.Namespace, kind: str) -> ImageOptions:
    """Build the options one preparation subcommand runs under.

    The variant flags are read off the subcommand itself — ``normalize`` produces the normalized
    representation — while the two corrections come from the caller's flags. No correction is ever
    applied because a measurement suggested it and nobody asked.
    """
    return ImageOptions(
        normalize=kind == "normalize",
        prepare_for_ocr=kind == "ocr-ready",
        prepare_for_vlm=kind == "vlm-ready",
        correct_orientation=bool(args.correct_orientation),
        deskew=bool(args.deskew),
        quality=_quality(args, kind),
    )


def _run_options(args: argparse.Namespace) -> ImageOptions:
    """Build the transformations a contract run asks for, from the caller's flags."""
    return ImageOptions(
        normalize=bool(args.normalize),
        prepare_for_ocr=bool(args.prepare_for_ocr),
        prepare_for_vlm=bool(args.prepare_for_vlm),
        correct_orientation=bool(args.correct_orientation),
        deskew=bool(args.deskew),
        quality=None if args.quality is None else int(args.quality),
    )


def _artifact_payload(prepared: Any) -> Payload:
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


def _run_payload(result: Any) -> Payload:
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


def _info(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> Payload:
    """Read the file and pixel facts of one image."""
    del args, parser, root
    _, facts, _ = _decoded(input_path)
    return {
        "input": str(input_path),
        "format": facts.format,
        "size": facts.size,
        "width": facts.width,
        "height": facts.height,
        "channels": facts.channels,
        "resolution": facts.resolution,
    }


def _metrics(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> Payload:
    """Measure one image."""
    del args, parser, root
    _, _, metrics = _decoded(input_path)
    return {"input": str(input_path), "metrics": asdict(metrics)}


def _classify(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> Payload:
    """Measure one image and name its classification."""
    del args, parser, root
    _, _, metrics = _decoded(input_path)
    return {
        "input": str(input_path),
        "metrics": asdict(metrics),
        "classification": composition.classify_image(metrics),
    }


def _prepared(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
    *,
    kind: str,
    pipeline: Callable[..., Any],
    base_name: str,
) -> Payload:
    """Run one preparation pipeline and report what it published.

    ``base_name`` is the representation's lossless name; the container actually written follows
    the quality factor, and ``representation_suffix`` — the processor's own rule — decides it, so
    the tool and the library cannot disagree about what a run produced.
    """
    del parser
    pixels, _, metrics = _decoded(input_path)
    options = _pipeline_options(args, kind)
    destination = root / Path(base_name).with_suffix(
        representation_suffix(kind, options.quality)
    )
    prepared = pipeline(pixels, metrics, options, destination)
    return {"input": str(input_path), "representation": _artifact_payload(prepared)}


def _normalize(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> Payload:
    """Produce the general normalized representation."""
    return _prepared(
        args,
        parser,
        input_path,
        root,
        kind="normalize",
        pipeline=primitives.prepare_normalized_image,
        base_name="normalized.png",
    )


def _ocr_ready(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> Payload:
    """Produce the OCR-optimized variant."""
    return _prepared(
        args,
        parser,
        input_path,
        root,
        kind="ocr-ready",
        pipeline=primitives.prepare_image_for_ocr,
        base_name="ocr_ready.png",
    )


def _vlm_ready(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> Payload:
    """Produce the VLM-optimized variant through its own pipeline."""
    return _prepared(
        args,
        parser,
        input_path,
        root,
        kind="vlm-ready",
        pipeline=primitives.prepare_image_for_vlm,
        base_name="vlm_ready.png",
    )


def _run(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> Payload:
    """Run the image contract, directly or through the page-level wrapper.

    The run identity is derived from the program's own name (``image.py``, ``batch_image.py``), so
    a batch's run id says which tool produced it unless the caller pinned one.
    """
    document_id, run_id = _cli.identity_for(args, Path(parser.prog).stem, input_path)
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
    return _run_payload(result)


#: The seven methods by subcommand name. Both tools dispatch through this, so a subcommand's
#: behaviour lives in exactly one place.
COMMANDS: dict[str, Command] = {
    "info": _info,
    "metrics": _metrics,
    "normalize": _normalize,
    "ocr-ready": _ocr_ready,
    "vlm-ready": _vlm_ready,
    "classify": _classify,
    "run": _run,
}
