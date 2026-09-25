# pylint: disable=duplicate-code
# Reason: the identity and option-canonicalisation helpers are deliberate siblings of
# ``docflow.pdf.entrypoints``. Two processors may not import each other's internals
# (`README.md` §7 — "no processor imports another processor"), so the same short rule is
# written twice on purpose and neither copy is the other's default.
"""Entry points of the image processor.

The signatures are frozen by ``docs/plan/README.md`` §4 (the idea's §"Naming"): ``image``
exposes ``process_image()`` and ``process_image_from_page()``. Both return a typed result: a
failure is described in an ``ImageError`` inside the result, never thrown across the contract.

Where the artifacts go — ``request.output_dir`` *is* the namespace the plan calls ``image/``:

```
output_dir/
├── normalized.png     # when options.normalize is set
├── ocr_ready.png      # when options.prepare_for_ocr is set
├── vlm_ready.png      # when options.prepare_for_vlm is set
└── metadata.json
```

Nothing is written outside that directory, and everything is published atomically through the
seam's writer (``.tmp`` → validate → rename).

The order of the stages is the one the subplan fixes: validate the input, resolve the engine
version, load, measure, then prepare the requested representations, classify and validate.
Only the *requested* representations are produced: a variant nobody asked for is ``None``, not
an empty artifact.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any, Final, TypeVar

from docflow.image.contracts import (
    ArtifactRef,
    ImageContext,
    ImageError,
    ImageMetadata,
    ImageMetrics,
    ImageOptions,
    ImageRequest,
    ImageResult,
    ImageSourceRef,
    ImageValidation,
    ImageVariants,
)
from docflow.image.primitives import (
    ENGINE_NAME,
    ImageFileFacts,
    ImagePrimitiveError,
    analyze_image,
    classify_image,
    get_image_metadata,
    image_engine_version,
    load_image,
    prepare_image_for_ocr,
    prepare_image_for_vlm,
    prepare_normalized_image,
    publish_json,
    validate_image_input,
    validate_image_result,
)

#: Name recorded as ``processor`` in every artifact's metadata.
PROCESSOR_NAME: Final[str] = "image"

#: Version recorded as ``processor_version`` in every artifact's metadata. A test asserts it
#: matches ``pyproject.toml``: the provenance an artifact carries has to name the code that
#: produced it.
PROCESSOR_VERSION: Final[str] = "0.0.0"

#: Artifact names, fixed so a reader never has to guess what a file is.
NORMALIZED_NAME: Final[Path] = Path("normalized.png")
OCR_READY_NAME: Final[Path] = Path("ocr_ready.png")
VLM_READY_NAME: Final[Path] = Path("vlm_ready.png")
METADATA_NAME: Final[Path] = Path("metadata.json")

T = TypeVar("T")


def _attempt(
    failures: list[ImageError], action: Callable[..., T], *arguments: Any
) -> T | None:
    """Run one stage, recording a typed failure instead of raising it.

    Args:
        failures: The run's failure list, which this call appends to.
        action: The seam function to run.
        arguments: Its arguments.

    Returns:
        What the stage produced, or ``None`` when it failed. The caller keeps whatever other
        stages produced, and the recorded failure explains the gap.
    """
    try:
        return action(*arguments)
    except ImagePrimitiveError as failure:
        failures.append(failure.error)
        return None


def _file_digest(path: Path) -> str:
    """Return the SHA-256 of a file, read in bounded chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_size(image_path: Path) -> int | None:
    """Return the source file's size, or ``None`` when it cannot be read.

    A path that was validated and then vanished is not given a size it never had.
    """
    try:
        return image_path.stat().st_size
    except OSError:
        return None


def _normalized_options(options: ImageOptions) -> dict[str, object]:
    """Return the options in canonical form, one key per capability.

    Canonical rather than raw, so two spellings of the same configuration produce the same
    record — and therefore the same processing key.
    """
    return {
        "normalize": options.normalize,
        "prepare_for_ocr": options.prepare_for_ocr,
        "prepare_for_vlm": options.prepare_for_vlm,
        "correct_orientation": options.correct_orientation,
        "deskew": options.deskew,
    }


def _processing_key(request: ImageRequest) -> str:
    """Return this unit of work's key, per the documented formula.

    ``hash(processor + processor_version + input_hashes + normalized_options)``, with the run
    identity deliberately absent: a new run over unchanged inputs must reproduce the key.

    # TODO: [MVP] the orchestrator mints the document-level key (`ORC-02`); this
    # processor-local record makes the artifact self-describing until both are reconciled at
    # Phase 2.
    """
    material = "|".join(
        (
            PROCESSOR_NAME,
            PROCESSOR_VERSION,
            _file_digest(request.image_path),
            json.dumps(_normalized_options(request.options), sort_keys=True),
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _failed_result(
    request: ImageRequest,
    error: ImageError,
    started: float,
    engine_version: str | None,
) -> ImageResult:
    """Return the result of a run that failed before producing any artifact.

    Nothing is published: an artifact tree that only describes a failure is exactly the
    partially written output the atomic-publication rule exists to prevent. Everything that
    would have been measured is ``None`` — an undecodable input has no geometry, no readings
    and no classification, and a zero would read as a measured answer.

    Args:
        request: The request that failed.
        error: The typed failure that ended it.
        started: When the run started, for its duration.
        engine_version: The engine version, or ``None`` when none was read.

    Returns:
        The failed result, already validated: the descriptive state says which kind of problem
        ended the run (``UNSUPPORTED`` for a container this processor does not read).
    """
    result = _assemble_failure(request, error, started, engine_version)
    result.validation = validate_image_result(result)
    return result


def _assemble_failure(
    request: ImageRequest,
    error: ImageError,
    started: float,
    engine_version: str | None,
) -> ImageResult:
    """Assemble the result of a run that failed before producing any artifact."""
    return ImageResult(
        source=ImageSourceRef(
            path=request.image_path,
            width=None,
            height=None,
            format=request.image_path.suffix.lstrip(".").lower(),
            size=_source_size(request.image_path),
        ),
        normalized=None,
        variants=ImageVariants(ocr_ready=None, vlm_ready=None),
        metrics=None,
        classification=None,
        transformations=[],
        validation=ImageValidation(
            status="ERROR", errors=[error], missing_artifacts=[]
        ),
        artifacts=[],
        metadata=ImageMetadata(
            processor=PROCESSOR_NAME,
            processor_version=PROCESSOR_VERSION,
            engine=ENGINE_NAME,
            engine_version=engine_version,
            libraries={} if engine_version is None else {ENGINE_NAME: engine_version},
            options=request.options,
            input_metrics=None,
            output_metrics=None,
            timing={"total": perf_counter() - started},
            context=request.context,
        ),
        status="failed",
        error=error,
    )


def _identity_payload(
    request: ImageRequest, engine_version: str | None
) -> dict[str, Any]:
    """Return the keys every artifact ``metadata.json`` must record.

    ``engine_version`` is ``None`` when no engine call was reached; it is never a placeholder
    standing in for a version nobody read.
    """
    return {
        "processor": PROCESSOR_NAME,
        "processor_version": PROCESSOR_VERSION,
        "engine": ENGINE_NAME,
        "engine_version": engine_version,
        "document_id": request.context.document_id,
        "workflow_run_id": request.context.workflow_run_id,
        "processing_key": _processing_key(request),
    }


def _publish_metadata(
    request: ImageRequest,
    engine_version: str | None,
    result: ImageResult,
    metrics: ImageMetrics,
    variant_transformations: dict[str, list[str]],
) -> Path:
    """Publish ``metadata.json`` for this run.

    Args:
        request: The request being processed.
        engine_version: The engine version, or ``None`` when none was read.
        result: The result as assembled so far.
        metrics: The input's measurements.
        variant_transformations: The transformations each variant's own pipeline applied.

    Returns:
        The published metadata path.
    """
    return publish_json(
        request.output_dir / METADATA_NAME,
        {
            **_identity_payload(request, engine_version),
            "libraries": result.metadata.libraries,
            "status": result.status,
            "classification": result.classification,
            "transformations": list(result.transformations),
            "variant_transformations": variant_transformations,
            "options": _normalized_options(request.options),
            "input_metrics": asdict(metrics),
            "output_metrics": (
                None
                if result.metadata.output_metrics is None
                else asdict(result.metadata.output_metrics)
            ),
        },
    )


@dataclass
class _Representations:
    """What the requested preparation pipelines produced.

    A pipeline that fails contributes nothing here: the caller records its typed failure and the
    run keeps whatever the other pipelines published.

    Attributes:
        normalized: The general representation, or ``None`` when it was not requested or failed.
        ocr_ready: The OCR variant, or ``None``.
        vlm_ready: The VLM variant, or ``None``.
        artifacts: Every image this run published, in preparation order.
        transformations: Every transformation applied, in preparation order.
        per_variant: The transformations each pipeline applied, keyed by representation.
        output_metrics: The measurements of the normalized representation, or ``None``.
    """

    normalized: ArtifactRef | None = None
    ocr_ready: ArtifactRef | None = None
    vlm_ready: ArtifactRef | None = None
    artifacts: list[ArtifactRef] = field(default_factory=list)
    transformations: list[str] = field(default_factory=list)
    per_variant: dict[str, list[str]] = field(default_factory=dict)
    output_metrics: ImageMetrics | None = None


def _prepare_representations(
    request: ImageRequest,
    pixels: Any,
    metrics: ImageMetrics,
    failures: list[ImageError],
) -> _Representations:
    """Prepare the representations the request asked for.

    Only what was asked for is produced: a variant nobody requested is ``None``, not an
    artifact, and a variant whose pipeline failed is reported through ``failures`` rather than
    raised.

    Args:
        request: The request being processed.
        pixels: The decoded input image.
        metrics: The input's measurements.
        failures: The run's failure list, which each attempt appends to.

    Returns:
        What was produced, in the plan's preparation order.
    """
    produced = _Representations()
    wanted = (
        (
            request.options.normalize,
            prepare_normalized_image,
            NORMALIZED_NAME,
            "normalized",
        ),
        (
            request.options.prepare_for_ocr,
            prepare_image_for_ocr,
            OCR_READY_NAME,
            "ocr_ready",
        ),
        (
            request.options.prepare_for_vlm,
            prepare_image_for_vlm,
            VLM_READY_NAME,
            "vlm_ready",
        ),
    )

    for requested, pipeline, name, label in wanted:
        if not requested:
            continue
        prepared = _attempt(
            failures,
            pipeline,
            pixels,
            metrics,
            request.options,
            request.output_dir / name,
        )
        if prepared is None:
            continue
        produced.artifacts.append(prepared.artifact)
        produced.transformations.extend(prepared.transformations)
        produced.per_variant[label] = prepared.transformations
        if label == "normalized":
            produced.normalized = prepared.artifact
            produced.output_metrics = prepared.metrics
        elif label == "ocr_ready":
            produced.ocr_ready = prepared.artifact
        else:
            produced.vlm_ready = prepared.artifact

    return produced


def _assemble_result(
    request: ImageRequest,
    facts: ImageFileFacts,
    metrics: ImageMetrics,
    produced: _Representations,
    failures: list[ImageError],
    engine_version: str | None,
    libraries: dict[str, str],
    started: float,
) -> ImageResult:
    """Assemble the result of a run that measured its input.

    The failure list is shared rather than copied on purpose: publishing the metadata happens
    after this call, and a failure there has to reach the validation record instead of being
    dropped between the two steps.
    """
    return ImageResult(
        source=ImageSourceRef(
            path=request.image_path,
            width=facts.width,
            height=facts.height,
            format=facts.format,
            size=facts.size,
        ),
        normalized=produced.normalized,
        variants=ImageVariants(
            ocr_ready=produced.ocr_ready, vlm_ready=produced.vlm_ready
        ),
        metrics=metrics,
        classification=classify_image(metrics),
        transformations=produced.transformations,
        validation=ImageValidation(
            status="VALID", errors=failures, missing_artifacts=[]
        ),
        artifacts=produced.artifacts,
        metadata=ImageMetadata(
            processor=PROCESSOR_NAME,
            processor_version=PROCESSOR_VERSION,
            engine=ENGINE_NAME,
            engine_version=engine_version,
            libraries=libraries,
            options=request.options,
            input_metrics=metrics,
            output_metrics=produced.output_metrics,
            timing={"total": perf_counter() - started},
            context=request.context,
        ),
        status="success",
        error=None,
    )


def process_image(request: ImageRequest) -> ImageResult:
    """Analyse, normalize and prepare one image.

    Args:
        request: The image to process, its requested transformations and its correlation
            context. ``request.output_dir`` is the ``image/`` namespace.

    Returns:
        The result. On the happy path ``status`` is ``"success"``, the requested
        representations are published and every transformation applied is recorded. A failure
        is reported as a typed :class:`~docflow.image.contracts.ImageError` inside the result
        and is never raised across the contract; the input image is never modified.
    """
    started = perf_counter()
    engine_version: str | None = None

    try:
        validate_image_input(request.image_path)
        engine_version = image_engine_version()
        libraries = {ENGINE_NAME: engine_version}
        pixels = load_image(request.image_path)
        facts: ImageFileFacts = get_image_metadata(request.image_path, pixels)
        metrics = analyze_image(pixels, facts)
    except ImagePrimitiveError as failure:
        return _failed_result(request, failure.error, started, engine_version)

    failures: list[ImageError] = []
    produced = _prepare_representations(request, pixels, metrics, failures)
    result = _assemble_result(
        request, facts, metrics, produced, failures, engine_version, libraries, started
    )

    # The metadata publication is attempted, not assumed: a failure to write it is recorded
    # and reported, so the run never claims a success whose metadata is missing from disk.
    # It is deliberately not added to ``result.artifacts``: every entry there is an image and
    # ``ImageArtifactKind`` has no kind for a JSON record — a kind invented for it would be a
    # mislabelled artifact.
    _attempt(
        failures,
        _publish_metadata,
        request,
        engine_version,
        result,
        metrics,
        produced.per_variant,
    )

    if failures:
        # The contract's status vocabulary is two values wide, so a run that lost an artifact
        # reports `failed` and the recorded failures say which one: it never claims a success
        # with a missing file.
        result.status = "failed"
        result.error = failures[0]

    result.validation = validate_image_result(result)
    return result


def process_image_from_page(
    image_path: Path,
    output_dir: Path,
    options: ImageOptions,
    document_id: str,
    page_number: int,
    workflow_run_id: str,
) -> ImageResult:
    """Process an image that a PDF page produced.

    A thin wrapper: it builds an :class:`~docflow.image.contracts.ImageRequest`, carrying the
    page identity through, and delegates to :func:`process_image`. It never opens or renders a
    PDF itself.

    Args:
        image_path: The image to process, named explicitly.
        output_dir: The ``image/`` artifact namespace.
        options: Requested transformations and variants.
        document_id: Identity of the document the page belongs to.
        page_number: Logical page the image belongs to, 1-based.
        workflow_run_id: Identity of the run that issued the request.

    Returns:
        Whatever :func:`process_image` returns.
    """
    return process_image(
        ImageRequest(
            image_path=image_path,
            output_dir=output_dir,
            options=options,
            context=ImageContext(
                document_id=document_id,
                page_number=page_number,
                workflow_run_id=workflow_run_id,
            ),
        )
    )
