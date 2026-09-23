#!/usr/bin/env python3
"""Lab tool for ``procesador-image`` - drive this processor by hand.

Owned by ``IMG-15``. A caller of ``docflow.image``, not a component of it: every subcommand
resolves to a library function or primitive, and nothing here re-implements a measurement, a
transformation or a classification.

    python scripts/tools/image.py info      page.png
    python scripts/tools/image.py metrics   page.png
    python scripts/tools/image.py normalize page.png
    python scripts/tools/image.py ocr-ready page.png
    python scripts/tools/image.py vlm-ready page.png
    python scripts/tools/image.py classify  page.png
    python scripts/tools/image.py crop      page.png --box 10,20,300,400
    python scripts/tools/image.py run       page.png --ocr-ready --vlm-ready

Output defaults to ``var/tools/image/<stem>-<hash>/``, where the hash is of the input's bytes,
so two runs over the same file land in the same tree and an ``info`` after a ``run`` reads what
the run wrote.

Four boundaries hold, and each one is a decision rather than an accident:

* **A tool may reach ``image/primitives/`` directly.** That is what makes it a lab bench:
  ``metrics`` drives ``analyze_image`` without publishing anything, and ``crop`` drives
  ``crop_region`` on its own without a document run.
* **No library dependency.** Nothing under ``src/docflow/`` imports this file, so deleting
  ``scripts/`` leaves the library and its tests untouched.
* **No workflow decision.** Every subcommand executes unconditionally. The tool never decides
  whether normalization is warranted, never skips a stage and never consults an artifact's
  validity — that justification belongs to the processor's own option handling, and ``REUSE`` /
  ``SKIP`` / ``FORCE`` belong to the orchestrator.
* **No ``--engine`` flag.** The engine seam is not an operator knob: ``EngineChoice`` has no
  ``AUTO`` member and the processor's entry points require an explicit choice precisely so that
  no call site answers "which engine?" by accident. A flag here would make it a user preference
  and invite a run whose provenance nobody can reconstruct from the command line.

**The OCR and VLM variants are separate subcommands, never one with a flag.** The processor's
whole design rests on those two images not being interchangeable, and a single ``prepare``
command would teach the opposite to whoever reads this tool next.

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

from docflow.image import (  # noqa: E402
    ImageContext,
    ImageOptions,
    ImageRequest,
    process_image,
)
from docflow.image.primitives.analyze import analyze_image  # noqa: E402
from docflow.image.primitives.atomic import publish_json  # noqa: E402
from docflow.image.primitives.classify import classify_image  # noqa: E402
from docflow.image.primitives.engine import EngineChoice  # noqa: E402
from docflow.image.primitives.load import (  # noqa: E402
    get_image_metadata,
    load_image,
)
from docflow.image.primitives.normalize import (  # noqa: E402
    NORMALIZED_ARTIFACT_KIND,
    NORMALIZED_FILE_NAME,
)
from docflow.image.primitives.provenance import (  # noqa: E402
    processor_name,
    processor_version,
)
from docflow.image.primitives.publishing import publish_artifact  # noqa: E402
from docflow.image.primitives.transform import crop_region  # noqa: E402
from docflow.image.primitives.variants import (  # noqa: E402
    OCR_ARTIFACT_KIND,
    OCR_FILE_NAME,
    VLM_ARTIFACT_KIND,
    VLM_FILE_NAME,
    prepare_image_for_ocr,
    prepare_image_for_vlm,
)

TOOL_NAME = "image"
HASH_LENGTH = 8
DEFAULT_OUT_ROOT = Path("var/tools/image")

ENGINE = EngineChoice.OPENCV
"""The engine every subcommand uses.

OpenCV, because the plan fixes it as this processor's engine and the tool exists to exercise
the processor as deployed. It is a module constant rather than a flag for the reason the module
docstring gives.
"""

REGIONS_DIRECTORY = "regions"
"""Where an explicit crop is written, matching the plan's namespace tree."""


def run_directory(image_path: Path, out_root: Path) -> Path:
    """Return this invocation's output directory.

    The stem plus a short content hash, so the same bytes always land in the same tree. Two
    runs over a renamed copy of one file therefore share a directory, which is what makes a
    manual experiment reproducible.

    Args:
        image_path: The input image.
        out_root: The directory the tool writes under.

    Returns:
        ``<out_root>/<stem>-<hash>/``.
    """
    digest = hashlib.sha256(image_path.read_bytes()).hexdigest()[:HASH_LENGTH]
    return out_root / f"{image_path.stem}-{digest}"


def request_for(
    image_path: Path, output_dir: Path, *, ocr: bool, vlm: bool
) -> ImageRequest:
    """Build a request with the identity of a lab run.

    Args:
        image_path: The image to process.
        output_dir: The run's output root.
        ocr: Whether the OCR variant is wanted.
        vlm: Whether the VLM variant is wanted.

    Returns:
        The request, with the tool's own identity in the correlation context so a run's
        artifacts are recognisable as lab output rather than as an orchestrator run.
    """
    return ImageRequest(
        image_path=image_path,
        output_dir=output_dir,
        options=ImageOptions(
            normalize=True,
            prepare_for_ocr=ocr,
            prepare_for_vlm=vlm,
            correct_orientation=True,
            deskew=True,
        ),
        context=ImageContext(
            document_id=f"lab-{image_path.stem}", page_number=1, workflow_run_id="lab"
        ),
    )


def emit_json(payload: Any) -> None:
    """Print a payload as machine-readable JSON.

    Only called when ``--json`` was given. Printing JSON in both modes and then the human
    summary on top would make ``--json`` change nothing except to add noise — the one thing a
    machine-readable flag must not do.

    Args:
        payload: The value to serialise.
    """
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


def metrics_payload(image_path: Path) -> dict[str, Any]:
    """Measure an image without writing anything.

    Args:
        image_path: The image to measure.

    Returns:
        The metrics, plus the engine provenance so a reading can be attributed to a build.
    """
    image = load_image(image_path, ENGINE)
    metrics = analyze_image(image, image_path, ENGINE)
    facts = get_image_metadata(image_path, ENGINE)
    return {
        "path": str(image_path),
        "engine": ENGINE.value,
        "processor": processor_name(),
        "processor_version": processor_version(),
        "format": facts.format,
        "size": facts.size,
        "resolution": facts.resolution,
        "dimensions": {
            "width": metrics.dimensions.width,
            "height": metrics.dimensions.height,
        },
        "quality": {
            "blur": metrics.quality.blur,
            "sharpness": metrics.quality.sharpness,
            "contrast": metrics.quality.contrast,
            "brightness": metrics.quality.brightness,
            "noise": metrics.quality.noise,
        },
        "orientation": metrics.orientation,
        "skew": metrics.skew,
        "text_coverage": metrics.text_coverage,
        "text_regions": [
            {
                "region_id": region.region_id,
                "bbox": list(region.bbox),
                "text_coverage": region.text_coverage,
            }
            for region in metrics.text_regions
        ],
    }


# ---------------------------------------------------------------------------------------
# Subcommands - one per operation an operator needs
# ---------------------------------------------------------------------------------------


def command_info(args: argparse.Namespace) -> int:
    """Print what the file reports about itself, without decoding its pixels."""
    facts = get_image_metadata(args.image, ENGINE)
    payload = {
        "path": str(args.image),
        "format": facts.format,
        "size": facts.size,
        "resolution": facts.resolution,
    }

    if args.json:
        emit_json(payload)
    else:
        print(f"{args.image}")
        print(f"  format:     {facts.format}")
        print(f"  size:       {facts.size} bytes")
        resolution = f"{facts.resolution} dpi" if facts.resolution else "not declared"
        print(f"  resolution: {resolution}")
    return 0


def command_metrics(args: argparse.Namespace) -> int:
    """Print the full metrics of an image, writing nothing."""
    payload = metrics_payload(args.image)

    if args.json:
        emit_json(payload)
    else:
        dimensions = payload["dimensions"]
        quality = payload["quality"]
        print(f"{args.image}  {dimensions['width']}x{dimensions['height']}")
        print(f"  blur        {quality['blur']:.4f}")
        print(f"  sharpness   {quality['sharpness']:.4f}")
        print(f"  contrast    {quality['contrast']:.4f}")
        print(f"  brightness  {quality['brightness']:.4f}")
        print(f"  noise       {quality['noise']:.4f}")
        orientation = payload["orientation"] if payload["orientation"] else "none"
        skew = f"{payload['skew']:.4f}" if payload["skew"] else "none"
        print(f"  orientation {orientation}")
        print(f"  skew        {skew}")
        print(
            f"  text        {payload['text_coverage']:.4f} over "
            f"{len(payload['text_regions'])} region(s)"
        )
    return 0


def command_normalize(args: argparse.Namespace) -> int:
    """Publish the normalized representation."""
    return _publish_single(
        args, NORMALIZED_FILE_NAME, NORMALIZED_ARTIFACT_KIND, "normalize"
    )


def command_ocr_ready(args: argparse.Namespace) -> int:
    """Publish the OCR-optimized variant, on its own.

    A separate subcommand from ``vlm-ready`` on purpose: the two images are not
    interchangeable, and a single command with a flag would teach that they are.
    """
    return _publish_variant(args, OCR_FILE_NAME, OCR_ARTIFACT_KIND, "ocr-ready")


def command_vlm_ready(args: argparse.Namespace) -> int:
    """Publish the VLM-optimized variant, on its own.

    Separate from ``ocr-ready`` for the reason stated there.
    """
    return _publish_variant(args, VLM_FILE_NAME, VLM_ARTIFACT_KIND, "vlm-ready")


def _publish_single(
    args: argparse.Namespace, file_name: str, kind: str, label: str
) -> int:
    """Normalize an image and publish one artifact.

    Args:
        args: The parsed arguments.
        file_name: The artifact's file name.
        kind: The artifact kind to record.
        label: The subcommand name, for the human line.

    Returns:
        The exit code.
    """
    image = load_image(args.image, ENGINE)
    metrics = analyze_image(image, args.image, ENGINE)
    normalized, applied = _normalize(image, metrics, args)

    reference = publish_artifact(
        normalized, args.run_dir, file_name, kind, applied, ENGINE
    )
    payload = {
        "command": label,
        "path": str(reference.path),
        "transformations": list(applied),
        "dimensions": {"width": reference.width, "height": reference.height},
        "size": reference.size,
    }

    if args.json:
        emit_json(payload)
    else:
        print(f"{args.image} -> {reference.path}")
        print(f"  {reference.width}x{reference.height}  {reference.size} bytes")
        steps = ", ".join(applied) if applied else "none applied"
        print(f"  transformations: {steps}")
    return 0


def _publish_variant(
    args: argparse.Namespace, file_name: str, kind: str, label: str
) -> int:
    """Build one purpose-specific variant and publish it.

    Args:
        args: The parsed arguments.
        file_name: The variant's file name.
        kind: The artifact kind to record.
        label: The subcommand name, for the human line.

    Returns:
        The exit code.
    """
    image = load_image(args.image, ENGINE)
    metrics = analyze_image(image, args.image, ENGINE)
    options = ImageOptions(
        normalize=False,
        prepare_for_ocr=label == "ocr-ready",
        prepare_for_vlm=label == "vlm-ready",
        correct_orientation=True,
        deskew=True,
    )
    if label == "ocr-ready":
        pixels, applied = prepare_image_for_ocr(image, metrics, options, ENGINE)
    else:
        pixels, applied = prepare_image_for_vlm(image, metrics, options, ENGINE)

    if pixels is None:  # pragma: no cover - the option above always asks for one
        raise ValueError(f"{label} produced no pixels although it was requested")

    reference = publish_artifact(pixels, args.run_dir, file_name, kind, applied, ENGINE)
    payload = {
        "command": label,
        "path": str(reference.path),
        "transformations": list(applied),
        "channels": _channel_count(reference.path),
        "dimensions": {"width": reference.width, "height": reference.height},
        "size": reference.size,
    }

    if args.json:
        emit_json(payload)
    else:
        print(f"{args.image} -> {reference.path}")
        print(f"  full name: {file_name}")
        print(
            f"  {reference.width}x{reference.height}  {payload['channels']} channel(s)"
        )
        steps = ", ".join(applied) if applied else "none applied"
        print(f"  transformations: {steps}")
    return 0


def _channel_count(path: Path) -> int:
    """Return how many channels a published image has.

    Read back from the artifact rather than taken from the array, because the claim an operator
    is checking - "the VLM variant kept its colour" - is about the file a later stage will read.

    Args:
        path: The published image.

    Returns:
        ``3`` for a colour image, ``1`` for a single-channel one.
    """
    pixels = load_image(path, ENGINE)
    return 3 if pixels.ndim == 3 else 1


def _normalize(
    image: Any, metrics: Any, args: argparse.Namespace
) -> tuple[Any, tuple[str, ...]]:
    """Run the baseline normalization.

    ``normalize`` is always true here: the tool never decides whether normalization is
    warranted. That justification is the processor's option handling, and a tool that guessed
    would be making the decision an operator came here to observe.

    Args:
        image: The decoded pixels.
        metrics: The image's measurements.
        args: The parsed arguments, for the run directory.

    Returns:
        The normalized pixels and the transformations applied.
    """
    from docflow.image.primitives.normalize import normalize_image

    _ = args
    return normalize_image(
        image,
        metrics,
        ImageOptions(
            normalize=True,
            prepare_for_ocr=False,
            prepare_for_vlm=False,
            correct_orientation=True,
            deskew=True,
        ),
        ENGINE,
    )


def command_classify(args: argparse.Namespace) -> int:
    """Print the descriptive classification and the metrics behind it."""
    payload = metrics_payload(args.image)
    classification = classify_image(_metrics_of(args.image))
    payload = {"path": str(args.image), "classification": classification, **payload}

    if args.json:
        emit_json(payload)
    else:
        quality = payload["quality"]
        print(f"{args.image}: {classification}")
        print(
            f"  blur={quality['blur']:.2f} sharpness={quality['sharpness']:.2f} "
            f"contrast={quality['contrast']:.2f} noise={quality['noise']:.2f}"
        )
        print(f"  text_coverage={payload['text_coverage']:.4f}")
    return 0


def _metrics_of(image_path: Path) -> Any:
    """Return an image's metrics record.

    Args:
        image_path: The image to measure.

    Returns:
        The metrics.
    """
    return analyze_image(load_image(image_path, ENGINE), image_path, ENGINE)


def command_crop(args: argparse.Namespace) -> int:
    """Extract an explicitly requested region and publish it under ``regions/``."""
    box = _parse_box(args.box)
    payload = {"box": list(box), "path": str(args.image)}

    image = load_image(args.image, ENGINE)
    region = crop_region(image, box, ENGINE)
    regions_dir = args.run_dir / REGIONS_DIRECTORY
    name = f"region_{args.name}.png"
    reference = publish_artifact(region, regions_dir, name, "region", (), ENGINE)

    payload["output"] = str(reference.path)
    payload["dimensions"] = {"width": reference.width, "height": reference.height}
    payload["size"] = reference.size

    if args.json:
        emit_json(payload)
    else:
        print(f"{args.image} -> {reference.path}")
        print(
            f"  box {box}  {reference.width}x{reference.height}  {reference.size} bytes"
        )
    return 0


def _parse_box(text: str) -> tuple[int, int, int, int]:
    """Parse a ``x,y,width,height`` argument.

    Args:
        text: The argument as given.

    Returns:
        The four integers.

    Raises:
        ValueError: The argument does not hold exactly four integers.
    """
    parts = [part.strip() for part in text.split(",")]
    if len(parts) != 4:
        raise ValueError(f"a box needs four comma-separated integers, got {text!r}")
    return (int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]))


def command_run(args: argparse.Namespace) -> int:
    """Process the image through the processor's own entry point and summarise the result."""
    request = request_for(
        args.image, args.run_dir, ocr=args.ocr_ready, vlm=args.vlm_ready
    )
    result = process_image(request, engine=ENGINE)

    payload = {
        "status": result.status,
        "validation": result.validation.status,
        "classification": result.classification,
        "engine": f"{result.metadata.engine} {result.metadata.engine_version}",
        "source": {
            "path": str(result.source.path),
            "width": result.source.width,
            "height": result.source.height,
            "format": result.source.format,
        },
        "transformations": list(result.transformations),
        "artifacts": [
            {"path": str(artifact.path), "kind": artifact.kind, "size": artifact.size}
            for artifact in result.artifacts
        ],
        "timing": dict(result.metadata.timing),
        "error": (
            {"type": result.error.type, "message": result.error.message}
            if result.error
            else None
        ),
    }

    # The record the processor wrote is copied to the run root, so a lab directory read months
    # later explains itself without the reader having to know which stage produced it.
    publish_json(args.run_dir / "tool-run.json", _run_record(payload))

    if args.json:
        emit_json(payload)
    else:
        print(f"{args.image} -> {payload['status']} ({payload['validation']})")
        print(f"  classification: {payload['classification']}")
        print(
            f"  source: {payload['source']['width']}x{payload['source']['height']} "
            f"{payload['source']['format']}"
        )
        print(f"  engine: {payload['engine']}")
        for artifact in payload["artifacts"]:
            print(f"    + {Path(artifact['path']).name}  ({artifact['kind']})")
        steps = (
            ", ".join(payload["transformations"])
            if payload["transformations"]
            else "none"
        )
        print(f"  transformations: {steps}")
        if payload["error"]:
            print(f"  ! {payload['error']['type']}: {payload['error']['message']}")
    return 0


def _run_record(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the lab record written beside the run's artifacts.

    A separate file from the processor's ``metadata.json`` rather than a merge: that file is
    the processor's own output contract and a tool must not add fields to it. This one says
    which command produced the directory, which ``metadata.json`` has no business knowing.

    Args:
        payload: The summary of the run.

    Returns:
        The record to serialise.
    """
    return {
        "tool": f"scripts/tools/{TOOL_NAME}.py",
        "command": "run",
        "engine": ENGINE.value,
        "processor": processor_name(),
        "processor_version": processor_version(),
        "status": payload["status"],
        "artifacts": payload["artifacts"],
        "transformations": payload["transformations"],
    }


def build_parser() -> argparse.ArgumentParser:
    """Build the command line.

    Returns:
        The parser, with one subcommand per operation of ``docflow.image``.
    """
    # The globals are attached to the top-level parser *and* to each sub-parser with
    # `argparse.SUPPRESS`, so `image.py crop p.png --box 0,0,1,1 --out dir` works as well as
    # `image.py --out dir crop p.png --box 0,0,1,1`. Declaring them on only one side means an
    # operator putting the flag where it reads naturally gets "unrecognized arguments" or
    # silently loses the value to a default.
    parser = argparse.ArgumentParser(
        prog=f"python scripts/tools/{TOOL_NAME}.py",
        description="Drive the docflow image processor by hand.",
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    sub = parser.add_subparsers(dest="command", required=True)

    def leaf(name: str, help_text: str):
        child = sub.add_parser(name, help=help_text)
        child.add_argument("image", type=Path)
        child.add_argument("--out", type=Path, default=argparse.SUPPRESS)
        child.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
        return child

    leaf("info", "what the file reports about itself")
    leaf("metrics", "the full measurements, writing nothing")
    leaf("normalize", "publish the normalized representation")
    leaf("ocr-ready", "publish the OCR-optimized variant")
    leaf("vlm-ready", "publish the VLM-optimized variant")
    leaf("classify", "the descriptive classification and its metrics")

    crop = leaf("crop", "extract an explicitly requested region")
    crop.add_argument("--box", required=True, help="x,y,width,height")
    crop.add_argument("--name", default="001", help="region file name suffix")

    run = leaf("run", "process the image through the processor")
    run.add_argument("--ocr-ready", action="store_true", help="also prepare for OCR")
    run.add_argument("--vlm-ready", action="store_true", help="also prepare for VLM")

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
        "info": command_info,
        "metrics": command_metrics,
        "normalize": command_normalize,
        "ocr-ready": command_ocr_ready,
        "vlm-ready": command_vlm_ready,
        "classify": command_classify,
        "crop": command_crop,
        "run": command_run,
    }

    try:
        return handlers[args.command](args)
    except Exception as failure:
        # A tool is an operator's surface: a bad image or a bad box should print its cause, not
        # a traceback. The library's typed classification is preserved in the message.
        print(f"{type(failure).__name__}: {failure}", file=sys.stderr)
        return 1


__all__ = [
    "DEFAULT_OUT_ROOT",
    "ENGINE",
    "REGIONS_DIRECTORY",
    "build_parser",
    "main",
    "run_directory",
]

if __name__ == "__main__":
    raise SystemExit(main())
