# pylint: disable=duplicate-code,use-implicit-booleaness-not-comparison
# The fixture constants and the request builders repeat the other image suites' on purpose, so
# each suite can be read on its own. And every emptiness assertion below says what a list *is*
# rather than whether it is falsey: `artifacts == []` claims the run published nothing, and
# `not artifacts` would also pass if the field held ``None`` - which is a different, and
# wronger, answer.
"""End-to-end tests for ``process_image`` (``IMG-12``).

Every test here goes through the **public entry point** with real bytes from a committed fixture.
The primitives have their own suites; what is unproven until this file exists is that they compose
into a run - that the order is right, that the namespace is respected, and above all that a failure
produces a typed result instead of an exception or a half-written directory.

The WBS names two acceptance criteria, and both are here: a valid input reaches
``status == "success"`` with every output under ``image/``, and any valid input is byte-identical
afterwards.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import time
import typing
from pathlib import Path

import pytest

from docflow.identities import ARTIFACT_METADATA_KEYS
from docflow.image import (
    ImageContext,
    ImageOptions,
    ImageRequest,
    process_image,
    process_image_from_page,
)
from docflow.image.contracts import (
    ArtifactRef,
    ImageClassification,
    ImageVariants,
)
from docflow.image.primitives.analyze import analyze_image
from docflow.image.primitives.composition import _Run
from docflow.image.primitives.engine import EngineChoice, ImageEngineError
from docflow.image.primitives.failures import ImagePrimitiveError
from docflow.image.primitives.load import load_image
from docflow.image.primitives.normalize import normalize_image
from docflow.image.primitives.variants import (
    prepare_image_for_ocr,
    prepare_image_for_vlm,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "image"
COLOR_LAYOUT = FIXTURES / "color_layout.png"
SKEWED_TEXT = FIXTURES / "skewed_text.png"
CORRUPT = FIXTURES / "corrupt.png"

ENGINE = EngineChoice.OPENCV
"""The engine the plan fixes for this processor.

Pillow is exercised separately in the tests that assert a missing capability is *contained*
rather than raised, because that is the one thing Pillow changes about the contract.
"""

CLASSIFICATIONS = ("TEXT_IMAGE", "VISUAL_IMAGE", "MIXED_IMAGE", "LOW_QUALITY")


def options(**overrides: bool) -> ImageOptions:
    """Return a fully specified request configuration.

    Args:
        **overrides: Flags to replace.

    Returns:
        The options.
    """
    settings: dict[str, bool] = {
        "normalize": True,
        "prepare_for_ocr": False,
        "prepare_for_vlm": False,
        "correct_orientation": True,
        "deskew": True,
    }
    settings.update(overrides)
    return ImageOptions(**settings)


def request_for(tmp_path: Path, source: Path, **overrides: bool) -> ImageRequest:
    """Build a request for a fixture rooted in ``tmp_path``.

    Args:
        tmp_path: The test's temporary directory.
        source: The image to process.
        **overrides: Option flags to replace.

    Returns:
        The request.
    """
    return ImageRequest(
        image_path=source,
        output_dir=tmp_path / "image",
        options=options(**overrides),
        context=ImageContext(
            document_id="doc-1", page_number=3, workflow_run_id="run-1"
        ),
    )


def digest(path: Path) -> str:
    """Return the SHA-256 of a file's bytes.

    Args:
        path: The file to hash.

    Returns:
        The hex digest.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def published_tree(output_dir: Path) -> list[str]:
    """Return every path under the namespace, relative and sorted.

    Args:
        output_dir: The ``image/`` directory.

    Returns:
        The relative POSIX paths.
    """
    return sorted(
        path.relative_to(output_dir).as_posix() for path in output_dir.rglob("*")
    )


# --------------------------------------------------------------------------------------
# The two acceptance criteria
# --------------------------------------------------------------------------------------


def test_a_valid_image_reaches_success_with_every_output_under_the_namespace(
    tmp_path: Path,
) -> None:
    """The first WBS acceptance criterion, on real bytes from a committed fixture."""
    request = request_for(tmp_path, COLOR_LAYOUT)

    result = process_image(request, engine=ENGINE)

    assert result.status == "success"
    assert result.error is None
    assert result.classification in CLASSIFICATIONS
    assert result.validation.status == "VALID"
    assert result.normalized is not None
    assert result.normalized.path == request.output_dir / "normalized.png"
    assert result.normalized.path.is_file()
    assert published_tree(request.output_dir) == ["metadata.json", "normalized.png"]
    for artifact in result.artifacts:
        assert artifact.path.resolve().is_relative_to(request.output_dir.resolve())


def test_the_source_bytes_are_unchanged_by_processing(tmp_path: Path) -> None:
    """The second WBS acceptance criterion: the input image is read, never written."""
    before = digest(COLOR_LAYOUT)

    process_image(request_for(tmp_path, COLOR_LAYOUT), engine=ENGINE)

    assert digest(COLOR_LAYOUT) == before


def test_processing_never_writes_outside_the_image_namespace(tmp_path: Path) -> None:
    """Namespace ownership: the sibling directories belong to other processors."""
    root = tmp_path / "page_001"
    root.mkdir()
    owned_by_others = ("source", "render", "native_text", "ocr", "llm")
    for name in owned_by_others:
        (root / name).mkdir()
    request = ImageRequest(
        image_path=COLOR_LAYOUT,
        output_dir=root / "image",
        options=options(),
        context=ImageContext(
            document_id="doc-1", page_number=1, workflow_run_id="run-1"
        ),
    )

    result = process_image(request, engine=ENGINE)

    assert result.status == "success"
    for name in owned_by_others:
        assert list((root / name).iterdir()) == [], f"{name}/ was written into"


# --------------------------------------------------------------------------------------
# The full flow
# --------------------------------------------------------------------------------------


def test_both_variants_are_published_as_two_distinct_files(tmp_path: Path) -> None:
    """The OCR and VLM pipelines are independent, and each publishes its own file."""
    request = request_for(
        tmp_path, SKEWED_TEXT, prepare_for_ocr=True, prepare_for_vlm=True
    )

    result = process_image(request, engine=ENGINE)

    assert result.status == "success"
    assert result.variants.ocr_ready is not None
    assert result.variants.vlm_ready is not None
    ocr = result.variants.ocr_ready.path
    vlm = result.variants.vlm_ready.path
    assert ocr != vlm
    assert ocr.name == "ocr_ready.png"
    assert vlm.name == "vlm_ready.png"
    assert ocr.read_bytes() != vlm.read_bytes(), (
        "the two pipelines produced the same bytes"
    )
    assert published_tree(request.output_dir) == [
        "metadata.json",
        "normalized.png",
        "ocr_ready.png",
        "vlm_ready.png",
    ]


def test_a_variant_that_was_not_requested_is_not_published(tmp_path: Path) -> None:
    """``None`` means "not requested", and nothing nobody asked for is written."""
    request = request_for(tmp_path, COLOR_LAYOUT)

    result = process_image(request, engine=ENGINE)

    assert result.status == "success"
    assert result.variants.ocr_ready is None
    assert result.variants.vlm_ready is None
    assert not (request.output_dir / "ocr_ready.png").exists()
    assert not (request.output_dir / "vlm_ready.png").exists()


def test_the_output_is_measured_separately_from_the_input(tmp_path: Path) -> None:
    """``output_metrics`` describes the published image, not a copy of the source's numbers."""
    request = request_for(tmp_path, SKEWED_TEXT, prepare_for_ocr=True)

    result = process_image(request, engine=ENGINE)

    assert result.status == "success"
    assert result.metadata.input_metrics is result.metrics
    # The record must be its own object, measured from the published pixels rather than aliased
    # to the source's. Asserting *which* field moved would pin a threshold; asserting that the
    # record is not the same object is the invariant, and the fields cannot be compared for
    # inequality wholesale because the dimensions are legitimately shared.
    assert result.metadata.output_metrics is not result.metrics
    assert result.metadata.output_metrics.dimensions == result.metrics.dimensions
    assert (
        result.metadata.output_metrics.text_regions is not result.metrics.text_regions
    ), "the output record shares its mutable lists with the input's"


def test_the_output_metrics_are_the_source_metrics_when_nothing_was_normalized(
    tmp_path: Path,
) -> None:
    """No normalization means no second image: the output *is* the input, measured once.

    The natural reading of ``output_metrics`` is "what the published artifact measures", and
    with ``normalize=False`` nothing is published, so there is no second image to measure.
    """
    request = request_for(tmp_path, COLOR_LAYOUT, normalize=False)

    result = process_image(request, engine=ENGINE)

    assert result.status == "success"
    assert result.normalized is None
    assert result.metadata.output_metrics is result.metrics


def test_the_transformation_list_is_the_three_pipelines_concatenated_in_stage_order(
    tmp_path: Path,
) -> None:
    """Each pipeline reports its own steps, and the run reports them in the order they ran.

    Comparing against the primitives called directly is the point: a test that only checked the
    list was non-empty passed even when the normalization stage was moved after the variant
    stage and its steps were silently dropped from the record, because the variants alone still
    produced a non-empty list.
    """
    request = request_for(
        tmp_path, SKEWED_TEXT, prepare_for_ocr=True, prepare_for_vlm=True
    )
    pixels = load_image(SKEWED_TEXT, ENGINE)
    measured = analyze_image(pixels, SKEWED_TEXT, ENGINE)

    result = process_image(request, engine=ENGINE)

    assert result.status == "success"
    _, normalize_steps = normalize_image(pixels, measured, request.options, ENGINE)
    _, ocr_steps = prepare_image_for_ocr(pixels, measured, request.options, ENGINE)
    _, vlm_steps = prepare_image_for_vlm(pixels, measured, request.options, ENGINE)
    assert result.transformations == [
        *normalize_steps,
        *ocr_steps,
        *vlm_steps,
    ]
    assert result.transformations, "a skewed page needed at least one correction"


def test_a_refused_validation_fails_the_run_and_removes_what_it_published(
    tmp_path: Path,
) -> None:
    """A run whose artifacts do not pass validation is not reported as a success.

    Driven through the run's own validation step, because the condition cannot arise from the
    publication path: every publisher that returns a reference has just written the file, so
    ``validate_image_result`` sees exactly the artifacts the options asked for. The guard still
    has to exist - it is what makes the contract's promise true if a future publisher ever
    returns a reference to something it did not write - and this is what proves it routes a
    refusal to a failure instead of letting it through as a success.
    """
    request = request_for(tmp_path, COLOR_LAYOUT, prepare_for_ocr=True)
    run = _Run(
        request=request,
        engine=ENGINE,
        processing_key=None,
        started=time.perf_counter(),
    )
    run.classification = "TEXT_IMAGE"
    # The OCR variant was requested and is absent, which is precisely what the validator calls
    # `INVALID_OUTPUT`.
    run.normalized = ArtifactRef(
        path=request.output_dir / "normalized.png",
        kind="normalized",
        width=1,
        height=1,
        format="PNG",
        size=1,
    )
    run.variants = ImageVariants(ocr_ready=None, vlm_ready=None)

    accepted = run.validate()

    assert accepted is False
    assert run.failure is not None
    assert run.validation is not None
    assert run.validation.status == "INVALID_OUTPUT"

    failed = run.finish()

    assert failed.status == "failed"
    assert failed.error is not None
    assert failed.error.type == "INTERNAL_ERROR"
    assert failed.artifacts == []


def test_no_staging_directory_survives_a_successful_run(tmp_path: Path) -> None:
    """Publication is atomic, so a successful run leaves nothing staged behind it."""
    request = request_for(tmp_path, COLOR_LAYOUT, prepare_for_ocr=True)

    process_image(request, engine=ENGINE)

    assert not (request.output_dir / ".tmp").exists()
    assert not list(request.output_dir.rglob("*.tmp"))


def test_the_run_reports_its_own_timing_by_stage(tmp_path: Path) -> None:
    """``timing`` is a measurement of this run, and a stage never reports a negative duration."""
    request = request_for(tmp_path, COLOR_LAYOUT)

    result = process_image(request, engine=ENGINE)

    timing = result.metadata.timing
    assert "total" in timing
    assert {"validate_input", "load", "analyze", "normalize", "variants"} <= set(timing)
    for stage, seconds in timing.items():
        assert seconds >= 0.0, f"{stage} reported a negative duration"


# --------------------------------------------------------------------------------------
# A failed run
# --------------------------------------------------------------------------------------


def test_a_corrupt_input_is_reported_as_a_typed_error_not_an_exception(
    tmp_path: Path,
) -> None:
    """The scenario the subplan states: a typed failure inside the result."""
    request = request_for(tmp_path, CORRUPT)

    result = process_image(request, engine=ENGINE)

    assert result.status == "failed"
    assert result.error is not None
    assert result.error.type in ("DECODE_ERROR", "UNSUPPORTED_FORMAT")
    assert result.error.recoverable is False
    assert result.validation.status == "ERROR"


def test_a_failed_run_publishes_no_image_artifact(tmp_path: Path) -> None:
    """The scenario's second half: nothing partial is left under ``image/``."""
    request = request_for(tmp_path, CORRUPT, prepare_for_ocr=True, prepare_for_vlm=True)

    result = process_image(request, engine=ENGINE)

    assert result.status == "failed"
    assert result.artifacts == []
    assert result.normalized is None
    assert result.variants.ocr_ready is None
    assert result.variants.vlm_ready is None
    assert published_tree(request.output_dir) == ["metadata.json"]


def test_a_missing_input_is_reported_as_an_unrecoverable_invalid_input(
    tmp_path: Path,
) -> None:
    """A path that does not exist is a typed failure, not a traceback."""
    request = request_for(tmp_path, FIXTURES / "does-not-exist.png")

    result = process_image(request, engine=ENGINE)

    assert result.status == "failed"
    assert result.error is not None
    assert result.error.type == "INVALID_INPUT"
    assert result.error.recoverable is False


def test_the_failure_record_is_written_and_describes_the_failure(
    tmp_path: Path,
) -> None:
    """A failed run still leaves an account of itself, and it parses."""
    request = request_for(tmp_path, CORRUPT)

    result = process_image(request, engine=ENGINE)

    payload = json.loads(
        (request.output_dir / "metadata.json").read_text(encoding="utf-8")
    )
    assert set(ARTIFACT_METADATA_KEYS) <= set(payload)
    assert payload["status"] == "ERROR"
    assert payload["failed_before_publish"] is True
    assert payload["artifacts"] == []
    assert payload["errors"][0]["type"] == result.error.type


def test_a_failed_run_replaces_the_artifacts_a_previous_run_left(
    tmp_path: Path,
) -> None:
    """A reader that finds ``normalized.png`` is entitled to believe the run succeeded."""
    request = request_for(tmp_path, COLOR_LAYOUT)
    assert process_image(request, engine=ENGINE).status == "success"
    assert (request.output_dir / "normalized.png").is_file()

    failed = ImageRequest(
        image_path=CORRUPT,
        output_dir=request.output_dir,
        options=request.options,
        context=request.context,
    )
    result = process_image(failed, engine=ENGINE)

    assert result.status == "failed"
    assert published_tree(request.output_dir) == ["metadata.json"]


# --------------------------------------------------------------------------------------
# The engine boundary
# --------------------------------------------------------------------------------------


def test_an_engine_that_cannot_measure_is_contained_by_the_contract(
    tmp_path: Path,
) -> None:
    """Pillow is a codec: it reaches the contract as a typed result, never as a raised error.

    The primitive that needs OpenCV raises ``ImageEngineCapabilityError`` from deep inside the
    measurement stage. Letting it escape would put an engine error across the contract - the
    caller asked for an ``ImageResult``. It is translated to a typed failure instead.
    """
    request = request_for(tmp_path, COLOR_LAYOUT)

    result = process_image(request, engine=EngineChoice.PILLOW)

    assert result.status == "failed"
    assert result.error is not None
    assert result.error.type == "INTERNAL_ERROR"
    assert result.error.metadata.get("engine_error") == "ImageEngineCapabilityError"
    assert published_tree(request.output_dir) == ["metadata.json"]


@pytest.mark.parametrize("engine", [EngineChoice.OPENCV, EngineChoice.PILLOW])
def test_no_engine_error_or_primitive_error_escapes_the_entry_point(
    tmp_path: Path, engine: EngineChoice
) -> None:
    """Every path returns a result: the contract's promise is total, under either engine."""
    request = request_for(tmp_path, CORRUPT, prepare_for_ocr=True, prepare_for_vlm=True)

    try:
        result = process_image(request, engine=engine)
    except (ImageEngineError, ImagePrimitiveError) as escaped:  # pragma: no cover
        pytest.fail(f"{type(escaped).__name__} escaped the entry point: {escaped}")

    assert result.status == "failed"
    assert result.error is not None


def test_the_recorded_libraries_are_the_ones_the_engine_reported(
    tmp_path: Path,
) -> None:
    """Provenance is read from the engine, never guessed, and a version is never blank."""
    request = request_for(tmp_path, COLOR_LAYOUT)

    result = process_image(request, engine=ENGINE)

    libraries = result.metadata.libraries
    assert libraries["opencv"]
    assert libraries["numpy"]
    assert result.metadata.engine == "opencv"
    assert result.metadata.engine_version == libraries["opencv"]
    assert result.metadata.processor == "image"
    assert result.metadata.processor_version


def test_the_engine_is_required_so_no_call_site_can_omit_it() -> None:
    """``EngineChoice`` has no ``AUTO`` member, and the entry points have no engine default.

    A default would be this processor answering "which engine?" on the caller's behalf - the
    silent substitution the seam exists to prevent. Asserted on the signature because that is
    what a call site sees.
    """
    for function in (process_image, process_image_from_page):
        engine_parameter = inspect.signature(function).parameters["engine"]
        assert engine_parameter.default is inspect.Parameter.empty, (
            f"{function.__name__} supplies a default engine"
        )
        assert engine_parameter.kind is inspect.Parameter.KEYWORD_ONLY, (
            f"{function.__name__} lets the engine be passed positionally, where it can be "
            "omitted by accident"
        )


# --------------------------------------------------------------------------------------
# ``metadata.json``
# --------------------------------------------------------------------------------------


def test_the_metadata_carries_the_versions_the_transformations_and_the_metrics(
    tmp_path: Path,
) -> None:
    """The second WBS acceptance criterion's second half, on the file rather than the object."""
    request = request_for(tmp_path, SKEWED_TEXT, prepare_for_ocr=True)

    result = process_image(request, engine=ENGINE)

    payload = json.loads(
        (request.output_dir / "metadata.json").read_text(encoding="utf-8")
    )
    assert set(ARTIFACT_METADATA_KEYS) <= set(payload)
    assert payload["processor"] == result.metadata.processor
    assert payload["processor_version"] == result.metadata.processor_version
    assert payload["engine"] == result.metadata.engine
    assert payload["libraries"] == result.metadata.libraries
    assert payload["transformations"] == result.transformations
    assert payload["classification"] == result.classification
    assert payload["status"] == result.validation.status
    assert [entry["path"] for entry in payload["artifacts"]] == [
        str(artifact.path) for artifact in result.artifacts
    ]
    assert payload["input_metrics"]["dimensions"]["width"] > 0
    assert payload["output_metrics"]["dimensions"]["width"] > 0


def test_no_metadata_value_is_a_placeholder(tmp_path: Path) -> None:
    """A blank string or a bare zero where a real answer belongs is the forbidden stand-in."""
    request = request_for(tmp_path, COLOR_LAYOUT)

    result = process_image(request, engine=ENGINE)

    payload = json.loads(
        (request.output_dir / "metadata.json").read_text(encoding="utf-8")
    )
    for key in ("processor", "processor_version", "engine", "engine_version"):
        assert payload[key], f"{key} is blank"
    assert payload["document_id"] == "doc-1"
    assert payload["workflow_run_id"] == "run-1"
    assert payload["input"]["size"] == COLOR_LAYOUT.stat().st_size
    assert payload["input"]["format"] == "PNG"
    assert payload["input"]["width"] == result.metrics.dimensions.width > 0
    assert payload["input_metrics"]["quality"]["sharpness"] > 0.0
    assert payload["timing"]["total"] > 0.0


def test_a_failed_run_says_the_source_dimensions_were_never_measured(
    tmp_path: Path,
) -> None:
    """The zeroes in a failed record are flagged as absence, not left to be read as a size.

    A consumer that took ``width == 0`` for a real measurement would compute with a size that
    does not exist. The flag is what makes the difference explicit.
    """
    request = request_for(tmp_path, CORRUPT)

    process_image(request, engine=ENGINE)

    payload = json.loads(
        (request.output_dir / "metadata.json").read_text(encoding="utf-8")
    )
    assert payload["input"]["dimensions_measured"] is False
    assert payload["input"]["width"] == 0
    assert payload["input_metrics"]["quality"]["sharpness"] == 0.0


def test_a_successful_run_says_the_source_dimensions_were_measured(
    tmp_path: Path,
) -> None:
    """The same flag, on the path where the dimensions are real."""
    request = request_for(tmp_path, COLOR_LAYOUT)

    result = process_image(request, engine=ENGINE)

    payload = json.loads(
        (request.output_dir / "metadata.json").read_text(encoding="utf-8")
    )
    assert payload["input"]["dimensions_measured"] is True
    assert payload["input"]["width"] == result.metrics.dimensions.width


def test_the_processing_key_is_recorded_as_not_computed(tmp_path: Path) -> None:
    """The key belongs to the orchestrator; ``None`` says it has not been computed yet."""
    request = request_for(tmp_path, COLOR_LAYOUT)

    result = process_image(request, engine=ENGINE)

    payload = json.loads(
        (request.output_dir / "metadata.json").read_text(encoding="utf-8")
    )
    assert "processing_key" in payload
    assert payload["processing_key"] is None
    assert result.status == "success"


def test_a_supplied_processing_key_is_recorded_verbatim(tmp_path: Path) -> None:
    """When the orchestrator has computed one, it is passed through unaltered."""
    request = request_for(tmp_path, COLOR_LAYOUT)

    process_image(request, engine=ENGINE, processing_key="abc123")

    payload = json.loads(
        (request.output_dir / "metadata.json").read_text(encoding="utf-8")
    )
    assert payload["processing_key"] == "abc123"


# --------------------------------------------------------------------------------------
# The page-level entry point
# --------------------------------------------------------------------------------------


def test_the_page_entry_point_builds_the_request_and_carries_the_page_identity(
    tmp_path: Path,
) -> None:
    """The wrapper adds nothing of its own: it delegates and preserves the context."""
    output_dir = tmp_path / "image"

    result = process_image_from_page(
        COLOR_LAYOUT,
        output_dir,
        options(),
        document_id="doc-9",
        page_number=7,
        workflow_run_id="run-9",
        engine=ENGINE,
    )

    assert result.status == "success"
    payload = json.loads((output_dir / "metadata.json").read_text(encoding="utf-8"))
    assert payload["document_id"] == "doc-9"
    assert payload["workflow_run_id"] == "run-9"
    assert payload["page_number"] == 7


def test_the_two_entry_points_agree_on_the_same_input(tmp_path: Path) -> None:
    """``process_image_from_page`` is a wrapper, so its result must match a direct call's."""
    direct_dir = tmp_path / "direct"
    wrapped_dir = tmp_path / "wrapped"

    direct = process_image(
        ImageRequest(
            image_path=COLOR_LAYOUT,
            output_dir=direct_dir,
            options=options(),
            context=ImageContext(
                document_id="doc-9", page_number=7, workflow_run_id="run-9"
            ),
        ),
        engine=ENGINE,
    )
    wrapped = process_image_from_page(
        COLOR_LAYOUT,
        wrapped_dir,
        options(),
        document_id="doc-9",
        page_number=7,
        workflow_run_id="run-9",
        engine=ENGINE,
    )

    assert direct.status == wrapped.status
    assert direct.classification == wrapped.classification
    assert direct.transformations == wrapped.transformations
    assert published_tree(direct_dir) == published_tree(wrapped_dir)


def test_the_declared_classification_type_is_what_the_run_reports(
    tmp_path: Path,
) -> None:
    """The classification is one of the contract's four values, never a fifth spelling."""
    request = request_for(tmp_path, SKEWED_TEXT)

    result = process_image(request, engine=ENGINE)

    assert result.classification in typing.get_args(ImageClassification)
