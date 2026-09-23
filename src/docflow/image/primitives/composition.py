"""The image processing flow, as one readable sequence of steps.

Owned by ``IMG-12``. It composes the primitives of :mod:`docflow.image.primitives` into a run -
validate the input, load, measure, normalize, build the variants, classify, validate the
outputs, publish - and it decides nothing on its own. Every threshold, every transformation
and every verdict belongs to the primitive that owns it; this module only puts them in order.

Two rules from the plan shape it, and both are about what a *failure* produces:

* **A typed error is returned, never raised.** ``subplan-procesador-image.md`` §4: the
  processor "never throws across the contract where a typed result is expected". A caller that
  receives an :class:`~docflow.image.contracts.ImageResult` can inspect the failure; a caller
  that receives an exception cannot.
* **A failed run publishes nothing.** No artifact is written under its final name, so the
  namespace the plan describes holds either a complete set of outputs or none of them. The
  atomic publication of ``IMG-11`` makes each individual file all-or-nothing; refusing to
  start the publication at all is what makes the *set* all-or-nothing.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from docflow.identities import ARTIFACT_METADATA_KEYS
from docflow.image.contracts import (
    ArtifactRef,
    ImageClassification,
    ImageDimensions,
    ImageMetadata,
    ImageMetrics,
    ImageQualityMetrics,
    ImageRequest,
    ImageResult,
    ImageSourceRef,
    ImageValidation,
    ImageVariants,
)
from docflow.image.primitives.analyze import analyze_image
from docflow.image.primitives.atomic import (
    abandon,
    build_metadata_payload,
    publish_metadata,
)
from docflow.image.primitives.classify import classify_image
from docflow.image.primitives.engine import (
    Engine,
    EngineChoice,
    EngineProvenance,
    ImageEngineError,
    get_provenance,
)
from docflow.image.primitives.failures import ImagePrimitiveError
from docflow.image.primitives.load import (
    ImageFileFacts,
    get_image_metadata,
    load_image,
)
from docflow.image.primitives.normalize import (
    normalize_image,
    prepare_normalized_image,
)
from docflow.image.primitives.provenance import processor_name, processor_version
from docflow.image.primitives.validation import (
    LOW_QUALITY,
    VALID,
    as_image_error,
    validate_image_result,
)
from docflow.image.primitives.variants import (
    prepare_image_for_ocr,
    prepare_image_for_vlm,
    publish_variants,
)

UNKNOWN_DIMENSIONS = ImageDimensions(width=0, height=0)
"""Dimensions of an image whose pixels were never decoded.

Zero, and not a guess. The width and height are genuinely unknown when the decode failed - the
file's header may be intact while its pixel data is not - and the contract's
:class:`~docflow.image.contracts.ImageSourceRef` declares them as ``int``, so there is no
``None`` to carry "unknown" here the way ``ImageMetrics.resolution`` does.

The zeroes are readable *because of the status beside them*: a result whose ``status`` is
``"failed"`` and whose ``error.type`` is a decode failure has published nothing and measured
nothing, so every number in it is a zero of absence. A successful result can never carry them -
:func:`analyze_image` refuses a non-positive shape - which is what keeps this from being a
placeholder standing in for a real answer.

# TODO: [MVP] give `ImageSourceRef` nullable dimensions so a failed decode can say "unknown"
# rather than "zero". That is a contract change and belongs to its own task.
"""

EMPTY_METRICS = ImageMetrics(
    dimensions=UNKNOWN_DIMENSIONS,
    resolution=None,
    format="UNKNOWN",
    size=0,
    quality=ImageQualityMetrics(
        blur=0.0,
        sharpness=0.0,
        contrast=0.0,
        brightness=0.0,
        noise=0.0,
    ),
    orientation=None,
    skew=None,
    text_regions=[],
    text_coverage=0.0,
)
"""What an image measures when nothing could be measured.

Not a substitute for a measurement - it is the honest record of a run that produced none. It is
what makes the failure path total: :class:`~docflow.image.contracts.ImageResult` promises an
``ImageMetrics``, and a run that could not decode its input has no other answer to give.
:func:`classify_image` is never called on it, because classifying an image that was never read
would be inventing a verdict.
"""

FORMAT_UNKNOWN: Final[str] = "UNKNOWN"
"""Format recorded when the input could not be read at all."""


RUN_STAGES: Final[tuple[str, ...]] = (
    "resolve_engine",
    "validate_input",
    "load",
    "analyze",
    "normalize",
    "variants",
    "publish",
    "measure_output",
    "validate",
)
"""The steps of one run, in the order ``docs/idea/procesador-image.md`` §"Flujo general" fixes.

Named here so the code that drives them can say *what* the order is rather than repeat it, and so
a stage quietly going missing is a visible gap. Every stage but ``resolve_engine`` and
``validate`` can fail; all of them report their own duration.
"""


@dataclass
# pylint: disable=too-many-instance-attributes
# The record is the run's state and it holds one attribute per stage's output, because the
# alternative is threading a dozen values through nine method signatures - which is what the
# previous single-function version did, and it measured 26 locals and 10 return statements. The
# attribute count tracks the pipeline's length, so a cheaper linter number would come from
# hiding the state, not from simplifying it.
class _Run:
    """What one attempt accumulates, and the steps it performs.

    A record rather than a dozen locals, and the steps as methods rather than a long function.
    Both are the same decision: the flow has nine stages and eight of them can fail, so doing the
    bookkeeping inline made the function long enough that ``pylint`` measured 26 locals and 10
    return statements. Holding the state here keeps the flow reading as the sequence of steps the
    plan fixes, and it puts the teardown in exactly one place - which is not cosmetic, because
    having the cleanup on two of the failure paths instead of all of them is how a load failure
    once left a previous run's ``normalized.png`` in the namespace looking like this run's output.

    Attributes:
        request: The request being served.
        engine: The engine named by the caller.
        processing_key: The reuse key, when the orchestrator supplied one.
        started: When the run began, for the ``total`` timing.
        timing: Wall-clock seconds by stage.
        provenance: The engine and library versions, once resolved.
        source_facts: The input's format and size, once read.
        image: The decoded source pixels.
        metrics: What the source measured.
        normalized_pixels: The normalized pixels, or the source's when normalization was skipped.
        normalize_steps: What normalization applied.
        ocr_pixels: The prepared OCR variant, or ``None`` when not requested.
        ocr_steps: What the OCR pipeline applied.
        vlm_pixels: The prepared VLM variant, or ``None`` when not requested.
        vlm_steps: What the VLM pipeline applied.
        classification: The descriptive class, once reached.
        normalized: The published baseline artifact, or ``None``.
        variants: Both published variant references, each possibly ``None``.
        transformations: Every transformation applied, in order.
        output_metrics: What the published image measured.
        validation: The structural verdict.
        failure: The failure that ended the run, or ``None`` while it is still going.
    """

    request: ImageRequest
    engine: EngineChoice
    processing_key: str | None
    started: float
    timing: dict[str, float] = field(default_factory=dict)
    provenance: EngineProvenance | None = None
    source_facts: ImageFileFacts | None = None
    image: Any = None
    metrics: ImageMetrics | None = None
    normalized_pixels: Any = None
    normalize_steps: tuple[str, ...] = ()
    ocr_pixels: Any = None
    ocr_steps: tuple[str, ...] = ()
    vlm_pixels: Any = None
    vlm_steps: tuple[str, ...] = ()
    classification: ImageClassification | None = None
    normalized: ArtifactRef | None = None
    variants: ImageVariants | None = None
    transformations: list[str] = field(default_factory=list)
    output_metrics: ImageMetrics | None = None
    validation: ImageValidation | None = None
    failure: Exception | None = None

    def attempt(self, stage: str, call: Callable[[], Any]) -> Any:
        """Run one stage, recording its duration and containing its failure.

        The two error vocabularies are caught together. ``ImagePrimitiveError`` is the
        contract's; ``ImageEngineError`` and its subclasses are the seam's, raised from deep
        inside a primitive - a Pillow deployment reaching a primitive that needs OpenCV raises
        ``ImageEngineCapabilityError`` from thirty frames down. Letting that escape would put an
        engine error across the contract, which the subplan forbids: the caller asked for an
        ``ImageResult`` and would get an exception it has no vocabulary for.

        Args:
            stage: The stage's name, used as its key in ``timing``.
            call: The stage's work.

        Returns:
            Whatever the stage returned, which is meaningless when it failed - the caller checks
            :attr:`failure`, not this value, because several stages legitimately return ``None``.
        """
        self.failure = None
        started = time.perf_counter()
        try:
            value = call()
        except (ImagePrimitiveError, ImageEngineError) as failure:
            self.timing[stage] = time.perf_counter() - started
            self.failure = failure
            return None
        self.timing[stage] = time.perf_counter() - started
        return value

    def resolve_engine(self) -> bool:
        """Resolve the engine, so no later stage can fail for a missing library halfway through.

        An absent engine is a failure of the *run*, not of the input: it names a library the
        deployment did not install, and no retry of the same file changes that.

        Returns:
            Whether the engine was resolved.
        """
        self.provenance = self.attempt(
            "resolve_engine", lambda: get_provenance(self.engine)
        )
        return self.failure is None

    def read_input_facts(self) -> bool:
        """Read the input's format and size without decoding its pixels.

        Returns:
            Whether the input could be read at all.
        """
        self.source_facts = self.attempt(
            "validate_input",
            lambda: get_image_metadata(self.request.image_path, self.engine),
        )
        if self.failure is None:
            return True
        # The read failed, so the failure *is* the verdict on the input. Replaced with this
        # module's own wording rather than re-wrapped: the primitive's message names the reason,
        # and `_unreadable_input` says which step it stopped.
        self.failure = _unreadable_input(self.request.image_path)
        return False

    def decode(self) -> bool:
        """Decode the source pixels.

        Returns:
            Whether the pixels were read.
        """
        self.image = self.attempt(
            "load", lambda: load_image(self.request.image_path, self.engine)
        )
        return self.failure is None

    def measure(self) -> bool:
        """Measure the source image.

        Returns:
            Whether the source was measured.
        """
        self.metrics = self.attempt(
            "analyze",
            lambda: analyze_image(self.image, self.request.image_path, self.engine),
        )
        return self.failure is None

    def normalize(self) -> bool:
        """Apply the baseline normalization the measurements and flags justify.

        Returns:
            Whether normalization completed.
        """
        result = self.attempt(
            "normalize",
            lambda: normalize_image(
                self.image, self.metrics, self.request.options, self.engine
            ),
        )
        if self.failure is not None:
            return False
        self.normalized_pixels, self.normalize_steps = result
        return True

    def prepare_variants(self) -> bool:
        """Build whichever variants the request asked for.

        Both are built from the **source** pixels with the **source** metrics, not from the
        normalized image. The two pipelines are independent - that is ``IMG-13`` invariant 2 -
        and feeding one from the other's output would make a correction applied for
        normalization show up twice, in a variant that never asked for it.

        Returns:
            Whether both pipelines completed.
        """
        prepared = self.attempt(
            "variants",
            lambda: (
                prepare_image_for_ocr(
                    self.image, self.metrics, self.request.options, self.engine
                ),
                prepare_image_for_vlm(
                    self.image, self.metrics, self.request.options, self.engine
                ),
            ),
        )
        if self.failure is not None:
            return False
        (self.ocr_pixels, self.ocr_steps), (self.vlm_pixels, self.vlm_steps) = prepared
        self.classification = classify_image(self.metrics)
        self.transformations = [*self.normalize_steps, *self.ocr_steps, *self.vlm_steps]
        return True

    def publish(self) -> bool:
        """Publish the normalized artifact and whichever variants were prepared.

        Returns:
            Whether every artifact was written.
        """
        published = self.attempt(
            "publish",
            lambda: (
                prepare_normalized_image(
                    self.normalized_pixels,
                    self.request.output_dir,
                    self.request.options,
                    self.normalize_steps,
                    self.engine,
                ),
                publish_variants(
                    self.ocr_pixels,
                    self.ocr_steps,
                    self.vlm_pixels,
                    self.vlm_steps,
                    self.request.output_dir,
                    self.engine,
                ),
            ),
        )
        if self.failure is not None:
            return False
        self.normalized, self.variants = published
        return True

    def measure_output(self) -> bool:
        """Measure the image that was published, which is not the image that was read.

        Reusing the input's metrics would be cheaper and would describe the wrong image: the
        normalized artifact has usually been deskewed and contrast-stretched, so its scores
        differ from the source's by exactly the corrections the run applied. When normalization
        did not run there is no output artifact, and the output *is* the input - the same pixels
        from the same file - so the source's measurements are the output's.

        Returns:
            Whether the output was measured.
        """
        if self.normalized is None:
            self.output_metrics = self.metrics
            return True
        self.output_metrics = self.attempt(
            "measure_output",
            lambda: analyze_image(
                self.normalized_pixels, self.normalized.path, self.engine
            ),
        )
        return self.failure is None

    def validate(self) -> bool:
        """Check the result against what it claims, and settle its verdict.

        Cannot fail: the validator returns a verdict rather than raising, which is the whole point
        of it existing.

        Returns:
            Always ``True``, so it can sit in the stage sequence with the others.
        """
        started = time.perf_counter()
        self.validation = validate_image_result(
            self.normalized,
            self.variants.ocr_ready if self.variants else None,
            self.variants.vlm_ready if self.variants else None,
            self.request.options,
            low_quality=self.classification == "LOW_QUALITY",
        )
        self.timing["validate"] = time.perf_counter() - started
        if self.validation.status in (VALID, LOW_QUALITY):
            return True
        # The artifacts are on disk but the validation refused them. Reporting `success` here is
        # exactly the silent failure `docs/plan/README.md` §7 warns about, so the run is failed -
        # and `finish` removes what it published, because a reader that finds
        # `image/normalized.png` is entitled to believe it passed validation.
        self.failure = _validation_failure(self.validation)
        return False

    def finish(self) -> ImageResult:
        """Build the failed result for whatever ended this run.

        Returns:
            The failed result, with ``status == "failed"`` and ``error`` populated.
        """
        self.timing["total"] = time.perf_counter() - self.started
        assert self.failure is not None, "finish() called on a run that has not failed"
        return _failed(
            self.request,
            self.engine,
            self.failure,
            timing=self.timing,
            provenance=self.provenance,
            processing_key=self.processing_key,
            source_facts=self.source_facts,
            metrics=self.metrics,
            classification=self.classification,
            validation=self.validation,
        )

    def succeed(self) -> ImageResult:
        """Build and publish the result of a run that completed.

        Returns:
            The result. ``metadata.json`` is published last and describes the result that was just
            settled, so the file on disk cannot disagree with the object handed to the caller.
        """
        self.timing["total"] = time.perf_counter() - self.started
        artifacts = _artifact_list(self.normalized, self.variants)
        metadata = _metadata_record(
            self.request,
            self.provenance,
            self.request.options,
            self.metrics,
            self.output_metrics,
            self.timing,
        )
        result = ImageResult(
            source=_source_ref(
                self.request, self.source_facts, self.metrics.dimensions
            ),
            normalized=self.normalized,
            variants=self.variants,
            metrics=self.metrics,
            classification=self.classification,
            transformations=self.transformations,
            validation=self.validation,
            artifacts=artifacts,
            metadata=metadata,
            status="success",
            error=None,
        )
        publish_metadata(
            build_metadata_payload(
                metadata,
                result.source,
                self.classification,
                self.transformations,
                self.validation,
                artifacts,
                processing_key=self.processing_key,
            ),
            self.request.output_dir,
            self.engine,
        )
        return result


def process_image_result(
    request: ImageRequest,
    engine: EngineChoice,
    *,
    processing_key: str | None = None,
) -> ImageResult:
    """Process one image and return the contract's result, whatever happened.

    Args:
        request: The image to process, its requested transformations and its correlation
            context.
        engine: The engine to decode, measure and transform with, named explicitly by the
            caller. There is no default: ``EngineChoice`` has no ``AUTO`` member precisely so
            that "pick one for me" cannot be expressed.
        processing_key: The reuse key, when the orchestrator has computed one. ``None`` records
            that it has not, which is not the same as the key being absent.

    Returns:
        The result. On the happy path ``status`` is ``"success"``; otherwise it is ``"failed"``
        and ``error`` carries the typed failure. A run that failed published nothing but its
        failure record.

    Note:
        The stages are a tuple of bound methods so the order is stated once, as data, rather than
        as a sequence of early returns. Each stage reports whether it succeeded; the first that
        does not ends the run, and :meth:`_Run.finish` is the one place the teardown happens.
    """
    run = _Run(
        request=request,
        engine=engine,
        processing_key=processing_key,
        started=time.perf_counter(),
    )
    stages = (
        run.resolve_engine,
        run.read_input_facts,
        run.decode,
        run.measure,
        run.normalize,
        run.prepare_variants,
        run.publish,
        run.measure_output,
        run.validate,
    )
    for stage in stages:
        if not stage():
            return run.finish()
    return run.succeed()


def _artifact_list(
    normalized: ArtifactRef | None, variants: ImageVariants
) -> list[ArtifactRef]:
    """Return every published artifact, in the order the plan's tree lists them.

    ``None`` entries are omitted rather than filtered out later: an artifact that was not
    requested is not part of this run's output, and a ``None`` in the list would be a slot a
    consumer has to check.

    Args:
        normalized: The baseline artifact, or ``None``.
        variants: Both variant references, each possibly ``None``.

    Returns:
        The artifacts that were published.
    """
    published: list[ArtifactRef] = []
    if normalized is not None:
        published.append(normalized)
    if variants.ocr_ready is not None:
        published.append(variants.ocr_ready)
    if variants.vlm_ready is not None:
        published.append(variants.vlm_ready)
    return published


def _source_ref(
    request: ImageRequest, facts: ImageFileFacts, dimensions: ImageDimensions
) -> ImageSourceRef:
    """Describe the original input, from what the run measured.

    Args:
        request: The request, for the input path.
        facts: The file's technical facts, read before the pixels were decoded.
        dimensions: The decoded image's own dimensions, or :data:`UNKNOWN_DIMENSIONS` when
            there were none to measure.

    Returns:
        The source reference. The dimensions come from the decoded array rather than the file
        header: the array is what the run actually measured, and reading the header a second
        time would be a second answer that could disagree with the first.
    """
    return ImageSourceRef(
        path=request.image_path,
        width=dimensions.width,
        height=dimensions.height,
        format=facts.format,
        size=facts.size,
    )


def _metadata_record(
    request: ImageRequest,
    provenance: EngineProvenance,
    options: Any,
    input_metrics: ImageMetrics,
    output_metrics: ImageMetrics,
    timing: dict[str, float],
) -> ImageMetadata:
    """Assemble the provenance record for a run.

    Args:
        request: The request the run was made under.
        provenance: The engine and array library that produced the pixels.
        options: The options the run was asked for.
        input_metrics: What the source image measured.
        output_metrics: What the normalized image measured.
        timing: Wall-clock seconds by stage.

    Returns:
        The provenance record. No field has a fallback: a blank engine or version would be the
        silent stand-in the plan forbids, and a caller that cannot supply one has a failure to
        report instead.
    """
    return ImageMetadata(
        processor=processor_name(),
        processor_version=processor_version(),
        engine=provenance.engine.name,
        engine_version=provenance.engine.version,
        libraries={
            provenance.engine.name: provenance.engine.version,
            provenance.array_library.name: provenance.array_library.version,
        },
        options=options,
        input_metrics=input_metrics,
        output_metrics=output_metrics,
        timing=timing,
        context=request.context,
    )


def _failed(
    request: ImageRequest,
    engine: EngineChoice,
    failure: Exception,
    *,
    timing: dict[str, float],
    provenance: EngineProvenance | None,
    processing_key: str | None,
    source_facts: ImageFileFacts | None = None,
    metrics: ImageMetrics | None = None,
    classification: ImageClassification | None = None,
    validation: ImageValidation | None = None,
) -> ImageResult:
    """Build the result of a run that failed, publishing only its ``metadata.json``.

    The failure is converted to a typed :class:`~docflow.image.contracts.ImageError` and carried
    inside the result. ``metadata.json`` is still written - it is the *record* of the failure,
    and a run that failed silently at the filesystem level would leave an operator with nothing
    to read - but no image artifact is, and any the run had published are removed first.

    Args:
        request: The request the run was made under.
        engine: The engine the run was using.
        failure: The primitive failure the run stopped on.
        timing: Wall-clock seconds by stage, including the stages that never ran.
        provenance: The engine and library versions, or ``None`` when the engine itself was
            missing and its version could not be read.
        processing_key: The reuse key, when the orchestrator supplied one.
        source_facts: The input's technical facts, when they could be read.
        metrics: What was measured before the failure, when anything was.
        classification: The classification, when it had been reached.
        validation: The verdict, when validation ran. Supplied by the caller that failed *after*
            validating, so the reasons it refused the artifacts are not lost.

    Returns:
        The failed result, with ``status == "failed"`` and ``error`` populated.
    """
    _ = engine
    # Every failure route in this module funnels through here, so the cleanup lives here too:
    # a future failure path cannot forget it, which is how a load failure once left a previous
    # run's `normalized.png` sitting in the namespace looking like this run's output.
    #
    # `abandon` removes both the staged files and the final-named artifacts this processor
    # writes, and it removes the `metadata.json` too - so it runs *before* the failure record is
    # published below, not after. It touches nothing it did not write, so a caller pointing at a
    # shared directory loses nothing.
    abandon(request.output_dir)

    error = as_image_error(_as_primitive_failure(failure))
    measured = metrics if metrics is not None else EMPTY_METRICS
    verdict = (
        validation
        if validation is not None
        else ImageValidation(status="ERROR", errors=[error], missing_artifacts=[])
    )

    metadata = _metadata_record(
        request,
        provenance if provenance is not None else _missing_engine_provenance(engine),
        request.options,
        measured,
        measured,
        timing,
    )
    result = ImageResult(
        source=(
            _source_ref(request, source_facts, measured.dimensions)
            if source_facts is not None
            else ImageSourceRef(
                path=request.image_path,
                width=UNKNOWN_DIMENSIONS.width,
                height=UNKNOWN_DIMENSIONS.height,
                format=FORMAT_UNKNOWN,
                size=0,
            )
        ),
        normalized=None,
        variants=ImageVariants(ocr_ready=None, vlm_ready=None),
        metrics=measured,
        classification=classification if classification is not None else "LOW_QUALITY",
        transformations=[],
        validation=verdict,
        artifacts=[],
        metadata=metadata,
        status="failed",
        error=error,
    )
    # The record of a failure is the one file a failed run may leave. It is written through the
    # same atomic publication as every other artifact, so a reader either finds a complete
    # account of the failure or nothing at all.
    publish_metadata(
        _failure_metadata_payload(result, request, processing_key),
        request.output_dir,
        engine,
    )
    return result


def _missing_engine_provenance(engine: EngineChoice) -> EngineProvenance:
    """Describe an engine that could not be resolved.

    Args:
        engine: The engine that was missing.

    Returns:
        A provenance record naming the engine the caller asked for, with the version the run
        could not read recorded as ``UNKNOWN`` rather than as a blank string.
    """
    return EngineProvenance(
        engine=Engine(name=engine.value, version=FORMAT_UNKNOWN),
        array_library=Engine(name=FORMAT_UNKNOWN, version=FORMAT_UNKNOWN),
    )


def _failure_metadata_payload(
    result: ImageResult, request: ImageRequest, processing_key: str | None
) -> dict[str, Any]:
    """Build the ``metadata.json`` payload for a failed run.

    Args:
        result: The failed result.
        request: The request the run was made under.
        processing_key: The reuse key, when the orchestrator supplied one.

    Returns:
        The payload, carrying every key :data:`docflow.identities.ARTIFACT_METADATA_KEYS`
        requires plus the failure that ended the run.
    """
    payload = build_metadata_payload(
        result.metadata,
        result.source,
        result.classification,
        [],
        result.validation,
        [],
        processing_key=processing_key,
    )
    # `build_metadata_payload` is written for a run that published something, so it carries an
    # empty artifact list naturally. What it cannot know is that the run never reached the point
    # of producing anything, which is the single most useful fact in a failure record.
    payload["failed_before_publish"] = not result.artifacts
    _ = request
    absent = [key for key in ARTIFACT_METADATA_KEYS if key not in payload]
    if absent:  # pragma: no cover - the builder already refuses this
        raise ValueError(f"the metadata payload is missing required keys: {absent}")
    return payload


def _unreadable_input(path: Path) -> ImagePrimitiveError:
    """Describe an input that could not be read at all.

    Args:
        path: The input path.

    Returns:
        A typed ``INVALID_INPUT`` failure. Not recoverable: the same path will fail the same way
        on the next attempt, so retrying is not something this processor can promise.
    """
    return ImagePrimitiveError(
        error_type="INVALID_INPUT",
        message=f"the input image cannot be read: {path}",
        path=str(path),
        recoverable=False,
    )


def _validation_failure(validation: ImageValidation) -> ImagePrimitiveError:
    """Describe a run whose artifacts did not pass validation.

    Args:
        validation: The verdict that refused them.

    Returns:
        A typed ``INTERNAL_ERROR`` failure naming each reason. ``INTERNAL_ERROR`` rather than a
        narrower kind because the artifacts were written and *then* refused: the failure is in
        what this run produced, not in the input it was given.
    """
    reasons = (
        "; ".join(error.message for error in validation.errors) or validation.status
    )
    return ImagePrimitiveError(
        error_type="INTERNAL_ERROR",
        message=f"the published artifacts did not pass validation: {reasons}",
        recoverable=False,
    )


def _as_primitive_failure(failure: Exception) -> ImagePrimitiveError:
    """Translate any failure this module's primitives can raise into one typed failure.

    The primitives report through two vocabularies. :class:`ImagePrimitiveError` is the
    contract's, and is already what the caller wants. :class:`ImageEngineError` and its
    subclasses are the *seam's*, and they are raised from deep inside a primitive - a Pillow
    deployment reaching a primitive that needs OpenCV raises
    :class:`~docflow.image.primitives.engine.ImageEngineCapabilityError` from thirty frames
    down. Letting that escape would put an engine error across the contract, which
    ``subplan-procesador-image.md`` §4 forbids: the caller asked for an ``ImageResult`` and
    would get an exception it has no vocabulary for.

    The translation is not a guess about the cause. An engine the deployment lacks, or an
    operation it cannot provide, is an ``INTERNAL_ERROR`` - nothing about the input was wrong,
    so no other kind describes it, and the engine's own words are kept as the message.

    Args:
        failure: The failure to translate.

    Returns:
        A typed failure: the original when it already was one, so nothing is re-wrapped and
        no detail is lost.
    """
    if isinstance(failure, ImagePrimitiveError):
        return failure
    return ImagePrimitiveError(
        error_type="INTERNAL_ERROR",
        message=str(failure),
        recoverable=False,
        detail={"engine_error": type(failure).__name__},
    )


__all__ = [
    "EMPTY_METRICS",
    "FORMAT_UNKNOWN",
    "RUN_STAGES",
    "UNKNOWN_DIMENSIONS",
    "process_image_result",
]
