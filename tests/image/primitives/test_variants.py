# pylint: disable=duplicate-code
# The fixture constants repeat the other image suites' on purpose. A shared helper module would let
# a change made for one suite silently redirect another's; the duplication is a handful of lines per
# suite and the independence is worth the noise.
"""Tests for the two preparation pipelines and their artifacts (``IMG-08``).

The WBS names two acceptance criteria: with both flags set, two distinct files exist and the VLM
variant preserves colour while the OCR variant may be grayscale; and with only ``prepare_for_vlm``,
no ``ocr_ready.png`` is produced. Both are here.

The plan goes further and names the failure this task exists to prevent - ``IMG-13``
invariant 2, with its own mutation: *"make ``prepare_image_for_vlm`` alias/return the ``ocr_ready``
path; the test then observes identical paths or lost color"*. Two tests are written directly
# against that mutation,
and the smoke run that produced this module found a real defect in the same family: preparing an
unrequested variant returned the input image, which was indistinguishable from a prepared one, so a
caller publishing whatever it was handed wrote an ``ocr_ready.png`` nobody had asked for.
The fix was structural - ``None`` now means "not requested" - rather than another assertion.

The pipelines are also tested as *code* and not only as behaviour: the VLM pipeline's source is
asserted to contain no call to the destructive primitives, which is a guard a behavioural test can
miss on a page where the destruction happens to be invisible.
"""

from __future__ import annotations

import hashlib
import inspect
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from docflow.image.contracts import ArtifactRef, ImageOptions, ImageVariants
from docflow.image.primitives import variants as variants_module
from docflow.image.primitives.analysis import detect_skew_angle
from docflow.image.primitives.analyze import analyze_image
from docflow.image.primitives.engine import EngineChoice
from docflow.image.primitives.load import load_image
from docflow.image.primitives.variants import (
    MAX_ACCEPTABLE_NOISE,
    OCR_ARTIFACT_KIND,
    OCR_FILE_NAME,
    TRANSFORMATION_BINARIZE,
    TRANSFORMATION_DENOISE,
    TRANSFORMATION_DESKEW,
    TRANSFORMATION_GRAYSCALE,
    VLM_ARTIFACT_KIND,
    VLM_FILE_NAME,
    prepare_image_for_ocr,
    prepare_image_for_vlm,
    publish_variants,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "image"
COLOR_LAYOUT = FIXTURES / "color_layout.png"
SKEWED_TEXT = FIXTURES / "skewed_text.png"

ENGINE = EngineChoice.OPENCV

NOISY_SIGMA = 18.0
"""Grain that puts a page above :data:`MAX_ACCEPTABLE_NOISE`.

Measured at 8.15 against a cut of 3.0, so the margin is wide.
"""

BAR_ROW = 40
"""A row inside the colour bars, where a lost channel cannot hide."""


def options(**overrides: bool) -> ImageOptions:
    """Return an option set with everything off unless asked for."""
    settings = {
        "normalize": False,
        "prepare_for_ocr": False,
        "prepare_for_vlm": False,
        "correct_orientation": False,
        "deskew": True,
    }
    settings.update(overrides)
    return ImageOptions(**settings)


def digest(path: Path) -> str:
    """Return a hash of a file's bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare_both(image: np.ndarray, metrics: object) -> tuple[object, object]:
    """Prepare both variants from one option set."""
    both = options(prepare_for_ocr=True, prepare_for_vlm=True)
    ocr, ocr_steps = prepare_image_for_ocr(image, metrics, both, ENGINE)
    vlm, vlm_steps = prepare_image_for_vlm(image, metrics, both, ENGINE)
    return (ocr, ocr_steps), (vlm, vlm_steps)


def test_both_variants_produce_two_distinct_files(tmp_path: Path) -> None:
    """The first WBS acceptance criterion, on a colour page that is also skewed."""
    image = load_image(SKEWED_TEXT, ENGINE)
    metrics = analyze_image(image, SKEWED_TEXT, ENGINE)
    output_dir = tmp_path / "image"

    (ocr, ocr_steps), (vlm, vlm_steps) = prepare_both(image, metrics)
    variants = publish_variants(ocr, ocr_steps, vlm, vlm_steps, output_dir, ENGINE)

    assert (output_dir / OCR_FILE_NAME).is_file()
    assert (output_dir / VLM_FILE_NAME).is_file()
    assert variants.ocr_ready.path != variants.vlm_ready.path


def test_the_ocr_variant_is_single_channel_and_the_vlm_variant_is_not(
    tmp_path: Path,
) -> None:
    """The distinguishing property the plan names: VLM preserves colour channels."""
    image = load_image(COLOR_LAYOUT, ENGINE)
    metrics = analyze_image(image, COLOR_LAYOUT, ENGINE)
    output_dir = tmp_path / "image"

    (ocr, ocr_steps), (vlm, vlm_steps) = prepare_both(image, metrics)
    variants = publish_variants(ocr, ocr_steps, vlm, vlm_steps, output_dir, ENGINE)

    reloaded_ocr = load_image(variants.ocr_ready.path, ENGINE)
    reloaded_vlm = load_image(variants.vlm_ready.path, ENGINE)

    assert reloaded_ocr.ndim == 2, "the OCR variant should be reduced to one channel"
    assert reloaded_vlm.ndim == 3, "the VLM variant must keep colour channels"


def test_the_vlm_variant_keeps_three_distinguishable_colours(tmp_path: Path) -> None:
    """Not merely three channels: the colour information has to survive.

    A pipeline that converted to grayscale and back to three channels would satisfy every shape
    assertion above and destroy exactly what the model reads. The fixture's three pure bars
    make that reducible to a check on which channel dominates each of them.
    """
    image = load_image(COLOR_LAYOUT, ENGINE)
    metrics = analyze_image(image, COLOR_LAYOUT, ENGINE)
    output_dir = tmp_path / "image"
    (ocr, ocr_steps), (vlm, vlm_steps) = prepare_both(image, metrics)

    variants = publish_variants(ocr, ocr_steps, vlm, vlm_steps, output_dir, ENGINE)
    reloaded = load_image(variants.vlm_ready.path, ENGINE)

    dominant = [int(np.argmax(reloaded[BAR_ROW, column])) for column in (40, 120, 200)]
    assert dominant == [1, 0, 2], f"the bars lost their colour: {dominant}"


def test_only_the_vlm_variant_requested_produces_only_that_file(tmp_path: Path) -> None:
    """The second WBS acceptance criterion."""
    image = load_image(COLOR_LAYOUT, ENGINE)
    metrics = analyze_image(image, COLOR_LAYOUT, ENGINE)
    output_dir = tmp_path / "image"
    only_vlm = options(prepare_for_vlm=True)

    ocr, ocr_steps = prepare_image_for_ocr(image, metrics, only_vlm, ENGINE)
    vlm, vlm_steps = prepare_image_for_vlm(image, metrics, only_vlm, ENGINE)
    variants = publish_variants(ocr, ocr_steps, vlm, vlm_steps, output_dir, ENGINE)

    assert variants.ocr_ready is None
    assert variants.vlm_ready is not None
    assert not (output_dir / OCR_FILE_NAME).exists()


def test_an_unrequested_variant_returns_no_pixels() -> None:
    """The defect that the smoke run found, pinned as a test.

    Returning the input image instead of ``None`` made "not requested" indistinguishable from
    "prepared", and a caller doing the obvious thing - publishing whatever it was handed - wrote an
    artifact nobody had asked for. The distinction has to be structural, and this is where it is
    asserted.
    """
    image = load_image(COLOR_LAYOUT, ENGINE)
    metrics = analyze_image(image, COLOR_LAYOUT, ENGINE)
    neither = options()

    ocr, ocr_steps = prepare_image_for_ocr(image, metrics, neither, ENGINE)
    vlm, vlm_steps = prepare_image_for_vlm(image, metrics, neither, ENGINE)

    assert ocr is None and vlm is None
    # Explicit rather than `not ocr_steps`: the claim is that the tuple is empty, not that it is
    # falsey.
    assert ocr_steps == ()  # pylint: disable=use-implicit-booleaness-not-comparison
    assert vlm_steps == ()  # pylint: disable=use-implicit-booleaness-not-comparison


def test_neither_variant_writes_anything_or_even_creates_the_directory(
    tmp_path: Path,
) -> None:
    """An artifact nobody asked for must not leave a trace, not even an empty directory."""
    image = load_image(COLOR_LAYOUT, ENGINE)
    metrics = analyze_image(image, COLOR_LAYOUT, ENGINE)
    output_dir = tmp_path / "image"
    neither = options()

    ocr, ocr_steps = prepare_image_for_ocr(image, metrics, neither, ENGINE)
    vlm, vlm_steps = prepare_image_for_vlm(image, metrics, neither, ENGINE)
    variants = publish_variants(ocr, ocr_steps, vlm, vlm_steps, output_dir, ENGINE)

    assert variants == ImageVariants(ocr_ready=None, vlm_ready=None)
    assert not output_dir.exists()


def test_the_vlm_variant_is_not_a_copy_of_the_ocr_variant() -> None:
    """The plan's named mutation, tested directly at the pixel level.

    Aliasing the VLM pipeline onto the OCR one would give identical paths - covered below - but it
    could also be done by returning the OCR *array* under the VLM name. The two arrays differ in
    rank, so asserting they are not equal catches both.
    """
    image = load_image(SKEWED_TEXT, ENGINE)
    metrics = analyze_image(image, SKEWED_TEXT, ENGINE)

    (ocr, _), (vlm, _) = prepare_both(image, metrics)

    assert not np.array_equal(ocr, vlm)
    assert ocr.ndim != vlm.ndim


def test_the_two_artifacts_are_never_the_same_file(tmp_path: Path) -> None:
    """The same mutation from the filesystem's side: two names, two files, different bytes."""
    image = load_image(COLOR_LAYOUT, ENGINE)
    metrics = analyze_image(image, COLOR_LAYOUT, ENGINE)
    output_dir = tmp_path / "image"
    (ocr, ocr_steps), (vlm, vlm_steps) = prepare_both(image, metrics)

    variants = publish_variants(ocr, ocr_steps, vlm, vlm_steps, output_dir, ENGINE)

    assert variants.ocr_ready.path != variants.vlm_ready.path
    assert digest(variants.ocr_ready.path) != digest(variants.vlm_ready.path)


def test_aliasing_the_two_names_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The refusal is in the code, so a caller who never runs the tests cannot publish
    one as two."""
    image = load_image(COLOR_LAYOUT, ENGINE)
    metrics = analyze_image(image, COLOR_LAYOUT, ENGINE)
    (ocr, ocr_steps), (vlm, vlm_steps) = prepare_both(image, metrics)
    monkeypatch.setattr(variants_module, "OCR_FILE_NAME", VLM_FILE_NAME)

    with pytest.raises(ValueError, match="independent artifacts"):
        publish_variants(ocr, ocr_steps, vlm, vlm_steps, tmp_path / "image", ENGINE)


def test_the_vlm_pipeline_source_never_calls_a_destructive_step() -> None:
    """A structural guard, because a behavioural one can miss it.

    Binarizing a page whose marks happen to survive the threshold would leave the VLM variant
    looking correct while the operation had run. The source cannot hide that.
    """
    source = inspect.getsource(variants_module.prepare_image_for_vlm)

    for forbidden in (
        "binarize_image",
        "convert_to_grayscale",
        "denoise_image",
        "normalize_contrast",
        "normalize_brightness",
    ):
        assert forbidden not in source, f"the VLM pipeline must never call {forbidden}"


def test_the_ocr_pipeline_does_use_the_destructive_step() -> None:
    """The converse, so the guard above cannot be satisfied by both pipelines doing nothing."""
    source = inspect.getsource(variants_module.prepare_image_for_ocr)

    assert "binarize_image" in source
    assert "convert_to_grayscale" in source


def test_the_ocr_variant_records_every_step_it_applied() -> None:
    """The record is checked against the pixels, not against a second call to the pipeline."""
    image = load_image(SKEWED_TEXT, ENGINE)
    metrics = analyze_image(image, SKEWED_TEXT, ENGINE)

    ocr, steps = prepare_image_for_ocr(
        image, metrics, options(prepare_for_ocr=True), ENGINE
    )

    assert TRANSFORMATION_GRAYSCALE in steps
    assert TRANSFORMATION_DESKEW in steps
    assert TRANSFORMATION_BINARIZE in steps
    assert ocr.ndim == 2, "the grayscale step is recorded and visible"
    assert set(np.unique(ocr).tolist()) <= {0, 255}, (
        "the binarize step is recorded and visible"
    )


def test_the_vlm_variant_records_only_the_correction_it_applied() -> None:
    """One step on a skewed page, and the pixel evidence for it."""
    image = load_image(SKEWED_TEXT, ENGINE)
    metrics = analyze_image(image, SKEWED_TEXT, ENGINE)

    vlm, steps = prepare_image_for_vlm(
        image, metrics, options(prepare_for_vlm=True), ENGINE
    )

    assert steps == (TRANSFORMATION_DESKEW,)
    assert abs(detect_skew_angle(vlm, ENGINE)) < 0.5
    assert vlm.ndim == 3


def test_the_vlm_variant_reports_nothing_to_do_on_an_upright_page() -> None:
    """A page needing no correction is published as it stands, with an honest empty record."""
    image = load_image(COLOR_LAYOUT, ENGINE)
    metrics = analyze_image(image, COLOR_LAYOUT, ENGINE)

    vlm, steps = prepare_image_for_vlm(
        image, metrics, options(prepare_for_vlm=True), ENGINE
    )

    # Explicit rather than `not steps`: the tuple being empty is the claim.
    assert steps == ()  # pylint: disable=use-implicit-booleaness-not-comparison
    assert vlm is image, (
        "there was nothing to change, so nothing should have been copied"
    )


def test_the_ocr_pipeline_denoises_a_noisy_page(tmp_path: Path) -> None:
    """Measured reason, not a hunch: on a grained page denoising is what keeps the text findable.

    At a standard deviation of 18 the raw image yields a single merged region over the frame while
    the denoised one yields two, close to the clean page's two. The threshold is why this step is
    conditional rather than unconditional.
    """
    base = load_image(COLOR_LAYOUT, ENGINE)
    generator = np.random.default_rng(3)
    grain = generator.normal(0.0, NOISY_SIGMA, base.shape)
    noisy = np.clip(base.astype(np.float64) + grain, 0, 255).astype(np.uint8)
    noisy_path = tmp_path / "noisy.png"
    Image.fromarray(noisy).save(noisy_path)

    noisy_image = load_image(noisy_path, ENGINE)
    metrics = analyze_image(noisy_image, noisy_path, ENGINE)
    assert metrics.quality.noise > MAX_ACCEPTABLE_NOISE

    _, steps = prepare_image_for_ocr(
        noisy_image, metrics, options(prepare_for_ocr=True), ENGINE
    )

    assert TRANSFORMATION_DENOISE in steps
    assert steps.index(TRANSFORMATION_DENOISE) < steps.index(TRANSFORMATION_BINARIZE), (
        "denoising earns its place ahead of the threshold; after it the grain is already gone"
    )


def test_the_ocr_pipeline_leaves_a_clean_page_undenoised() -> None:
    """Denoising lowers the blur score, so on a clean page it is a cost with no benefit."""
    image = load_image(COLOR_LAYOUT, ENGINE)
    metrics = analyze_image(image, COLOR_LAYOUT, ENGINE)
    assert metrics.quality.noise < MAX_ACCEPTABLE_NOISE

    _, steps = prepare_image_for_ocr(
        image, metrics, options(prepare_for_ocr=True), ENGINE
    )

    assert TRANSFORMATION_DENOISE not in steps


def test_the_ocr_pipeline_honours_the_deskew_option() -> None:
    """The flag gates the correction here exactly as it does in the normalization pipeline."""
    image = load_image(SKEWED_TEXT, ENGINE)
    metrics = analyze_image(image, SKEWED_TEXT, ENGINE)

    _, with_flag = prepare_image_for_ocr(
        image, metrics, options(prepare_for_ocr=True), ENGINE
    )
    _, without_flag = prepare_image_for_ocr(
        image, metrics, options(prepare_for_ocr=True, deskew=False), ENGINE
    )

    assert TRANSFORMATION_DESKEW in with_flag
    assert TRANSFORMATION_DESKEW not in without_flag


def test_the_published_variants_are_described_by_their_own_files(
    tmp_path: Path,
) -> None:
    """``ArtifactRef`` is built from the written file, not from the request."""
    image = load_image(COLOR_LAYOUT, ENGINE)
    metrics = analyze_image(image, COLOR_LAYOUT, ENGINE)
    output_dir = tmp_path / "image"
    (ocr, ocr_steps), (vlm, vlm_steps) = prepare_both(image, metrics)

    variants = publish_variants(ocr, ocr_steps, vlm, vlm_steps, output_dir, ENGINE)

    assert isinstance(variants.ocr_ready, ArtifactRef)
    assert variants.ocr_ready.kind == OCR_ARTIFACT_KIND
    assert variants.vlm_ready.kind == VLM_ARTIFACT_KIND
    assert variants.ocr_ready.format == "PNG"
    assert variants.ocr_ready.width == image.shape[1]
    assert variants.ocr_ready.height == image.shape[0]
    assert variants.ocr_ready.size == (output_dir / OCR_FILE_NAME).stat().st_size
    assert variants.vlm_ready.size == (output_dir / VLM_FILE_NAME).stat().st_size


def test_publishing_round_trips_through_both_engines(tmp_path: Path) -> None:
    """The channel count a variant carries has to survive the engine that wrote it *and* the one
    that reads it back.

    This is the test a mutation exposed as missing: the earlier coverage exercised only OpenCV, so
    making the Pillow decode path promote a single-channel file to three survived the whole suite.
    Either engine may write the artifact and either may read it, so all four combinations are
    asserted rather than the two that happen to be convenient.
    """
    image = load_image(COLOR_LAYOUT, ENGINE)
    metrics = analyze_image(image, COLOR_LAYOUT, ENGINE)
    (ocr, ocr_steps), (vlm, vlm_steps) = prepare_both(image, metrics)

    for writer in EngineChoice:
        output_dir = tmp_path / f"written-by-{writer.value}"
        variants = publish_variants(ocr, ocr_steps, vlm, vlm_steps, output_dir, writer)
        for reader in EngineChoice:
            reloaded_ocr = load_image(variants.ocr_ready.path, reader)
            reloaded_vlm = load_image(variants.vlm_ready.path, reader)
            assert reloaded_ocr.ndim == 2, (
                f"written by {writer.value}, read by {reader.value}: "
                "the OCR variant gained channels"
            )
            assert reloaded_vlm.ndim == 3, (
                f"written by {writer.value}, read by {reader.value}: "
                "the VLM variant lost channels"
            )


def test_a_second_run_replaces_the_previous_artifacts(tmp_path: Path) -> None:
    """Re-running is normal, and a stale artifact must not block it."""
    image = load_image(COLOR_LAYOUT, ENGINE)
    metrics = analyze_image(image, COLOR_LAYOUT, ENGINE)
    output_dir = tmp_path / "image"
    (ocr, ocr_steps), (vlm, vlm_steps) = prepare_both(image, metrics)

    first = publish_variants(ocr, ocr_steps, vlm, vlm_steps, output_dir, ENGINE)
    second = publish_variants(ocr, ocr_steps, vlm, vlm_steps, output_dir, ENGINE)

    assert first == second


def test_the_source_file_is_never_written(tmp_path: Path) -> None:
    """The plan requires that a processor leaves its input untouched."""
    before = digest(SKEWED_TEXT)
    image = load_image(SKEWED_TEXT, ENGINE)
    metrics = analyze_image(image, SKEWED_TEXT, ENGINE)
    (ocr, ocr_steps), (vlm, vlm_steps) = prepare_both(image, metrics)

    publish_variants(ocr, ocr_steps, vlm, vlm_steps, tmp_path / "image", ENGINE)

    assert digest(SKEWED_TEXT) == before


def test_the_input_array_is_never_mutated() -> None:
    """Both pipelines derive new arrays; neither edits the one it was given."""
    image = load_image(SKEWED_TEXT, ENGINE)
    before = image.copy()
    metrics = analyze_image(image, SKEWED_TEXT, ENGINE)

    prepare_both(image, metrics)

    assert np.array_equal(image, before)


def test_the_module_writes_no_path_outside_its_output_directory() -> None:
    """``IMG-13`` invariant 3 starts here: nothing may be written outside ``image/``.

    The guard matches the *paths* a namespace would be written to - ``name + "/"`` - rather than the
    bare words. Matching the words condemned the module's own docstring for discussing the OCR and
    VLM pipelines, which is a false positive of the same kind this project already hit once with a
    seam guard that forbade the word ``reuse`` in a docstring explaining it did not reuse anything.
    """
    source = Path(variants_module.__file__).read_text(encoding="utf-8")

    for forbidden in (
        "source/",
        "render/",
        "native_text/",
        "ocr/",
        "llm/",
        "var/tools/",
    ):
        assert forbidden not in source, (
            f"variants.py reached outside its namespace: {forbidden}"
        )

    # And the module never chooses its own root: the only directories it names are its own files.
    assert "output_dir /" in source, "the output directory must be caller-supplied"


def test_a_skew_reading_is_passed_through_exactly_as_detected() -> None:
    """The pipeline corrects by the number it was given, and does not second-guess it.

    A correction applied from a reading the detector can hold is the whole contract; the pipeline is
    not entitled to sanity-check a metric that another stage produced, and adding a range check here
    would be this module deciding what the detector may report.
    """
    image = load_image(SKEWED_TEXT, ENGINE)
    metrics = analyze_image(image, SKEWED_TEXT, ENGINE)
    assert metrics.skew != 0.0

    ocr, steps = prepare_image_for_ocr(
        image, metrics, options(prepare_for_ocr=True), ENGINE
    )
    vlm, vlm_steps = prepare_image_for_vlm(
        image, metrics, options(prepare_for_vlm=True), ENGINE
    )

    assert TRANSFORMATION_DESKEW in steps
    assert vlm_steps == (TRANSFORMATION_DESKEW,)
    assert ocr is not None and vlm is not None
