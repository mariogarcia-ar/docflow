# pylint: disable=duplicate-code,use-implicit-booleaness-not-comparison
# The fixture constants and the assertion helpers repeat the other image suites' on purpose, so
# each suite reads on its own. And every emptiness assertion below says what a list *is* rather
# than whether it is falsey: `offenders == []` claims the check found nothing, and `not
# offenders` would also pass if the variable held ``None`` - a different, and wronger, answer.
"""Hardening tests: the three invariants and the failure paths (``IMG-13``).

This module is the processor's proof that it does what ``subplan-procesador-image.md`` §6
claims, and it is organised the way ``tests/pdf/test_hardening.py`` is, because the same
problem recurs: **every invariant here is about absence.** No modified input, no variant
aliased over another, no file outside the namespace. Absence is exactly what a passing test
cannot demonstrate on its own — a suite that never checks for the stray file is green whether
or not the file is written — so each invariant carries the mutation that must break it, and
the observation is recorded beside the test.

What the entry-point suite already covers is not repeated. ``tests/image/test_entrypoints.py``
proves the flow runs; this module proves the four things that are true *around* the flow:
``IMG-13``'s three invariants, and that a failed run is as clean as a successful one.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import typing
from dataclasses import fields
from pathlib import Path

import pytest

from docflow.image import process_image
from docflow.image.contracts import (
    ImageClassification,
    ImageOptions,
    ImageRequest,
    ImageResult,
)
from docflow.image.primitives import variants
from docflow.image.primitives.engine import EngineChoice
from docflow.image.primitives.load import load_image
from tests.factories import (
    IMAGE_ARTIFACT_TREE,
    IMAGE_NAMESPACES_OWNED_BY_OTHERS,
    build_image_request_for,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "image"

COLOR_LAYOUT = FIXTURES / "color_layout.png"
SKEWED_TEXT = FIXTURES / "skewed_text.png"
EMBEDDED_LOGO = FIXTURES / "embedded_logo.png"
CORRUPT = FIXTURES / "corrupt.png"

HAPPY_FIXTURES = (COLOR_LAYOUT, SKEWED_TEXT, EMBEDDED_LOGO)
"""The three fixtures a complete run can succeed on.

``corrupt.png`` is absent on purpose: it is committed to provoke the decode failure, and
including it here would make the happy-path sweep assert a success that cannot happen.

``# TODO: [MVP]`` these are synthetic images drawn by ``scripts/tools/image_fixtures.py``.
They exercise the code paths and the color/gray distinction, which is what the invariants
need, but they are not scans — a real corpus would be needed to say anything about quality.
"""


def sha256(path: Path) -> str:
    """Return a file's hex digest.

    Args:
        path: The file to hash.

    Returns:
        The digest as hex.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def directory_listing(directory: Path) -> list[str]:
    """Return a directory's immediate entry names, sorted.

    Args:
        directory: The directory to list.

    Returns:
        The entry names.
    """
    return sorted(entry.name for entry in directory.iterdir())


def namespace_tree(output_dir: Path) -> list[str]:
    """Return every file under a namespace, relative and sorted.

    Args:
        output_dir: The ``image/`` directory.

    Returns:
        The relative POSIX paths.
    """
    return sorted(
        path.relative_to(output_dir).as_posix()
        for path in output_dir.rglob("*")
        if path.is_file()
    )


# ======================================================================================
# The happy path
# ======================================================================================
# Mutation: make `process_image` publish `metadata.json` before settling the verdict, so the
# file records the provisional status rather than the final one. Observed: the metadata
# assertion below fails on all three fixtures. Restored: green.
#
# The files are asserted as the complete set rather than one by one, because "normalized.png
# exists" is also true of a run that additionally wrote something nobody asked for.


@pytest.mark.parametrize("source", HAPPY_FIXTURES)
def test_the_happy_path_produces_the_complete_tree_and_a_parseable_record(
    tmp_path: Path, source: Path
) -> None:
    """The WBS acceptance criterion, swept across the three fixtures a run can succeed on."""
    request = build_image_request_for(source, tmp_path / "image")

    result = process_image(request, engine=EngineChoice.OPENCV)

    assert result.status == "success"
    assert result.error is None
    assert result.classification in (
        "TEXT_IMAGE",
        "VISUAL_IMAGE",
        "MIXED_IMAGE",
        "LOW_QUALITY",
    )
    assert namespace_tree(request.output_dir) == sorted(IMAGE_ARTIFACT_TREE)

    payload = json.loads(
        (request.output_dir / "metadata.json").read_text(encoding="utf-8")
    )
    assert payload["status"] == result.validation.status
    assert payload["classification"] == result.classification
    assert payload["processor"] == "image"
    assert payload["libraries"], "no library versions were recorded"


def test_the_classification_never_leaves_the_contracts_closed_set(
    tmp_path: Path,
) -> None:
    """No fixture produces a classification outside the four the contract declares.

    The closed set is the visible symptom of this processor taking a routing decision, which
    ``extends`` the contract's four values, which the subplan §2 puts out of bounds: a fifth
    value could only be reached by asking "what should happen next?".
    """
    allowed = set(typing.get_args(ImageClassification))
    seen: set[str] = set()

    for index, source in enumerate(HAPPY_FIXTURES):
        result = process_image(
            build_image_request_for(source, tmp_path / f"image{index}"),
            engine=EngineChoice.OPENCV,
        )
        assert result.classification in allowed
        seen.add(result.classification)

    assert seen, "no image was classified at all, so the assertion above proved nothing"


# ======================================================================================
# Invariant 1 — input immutability
# ======================================================================================
# Mutation: in `composition`, `prepare_normalized_image` is given
# `self.request.image_path.parent` instead of `self.request.output_dir`, so the artifact is
# published beside the source. Observed: `test_invariant_1_the_source_is_byte_identical`
# FAILS on `source0` (`assert [...] == [...]`, the directory listing gained
# `normalized.png`), and the harness reported the residue it wrote beside the committed
# fixture. Restored: green (5 passed).
#
# The digest alone is not sufficient, and that is the point of the pair. This mutation leaves
# the source's *bytes* intact and writes a new file next to it — a digest-only test would stay
# green. The directory listing is what catches it, the same pairing `PDF-12` arrived at after a
# digest alone missed a stray file.
#
# **Harness warning, learned the hard way.** The mutation writes into `tests/fixtures/image/`,
# so any harness applying it must snapshot that directory and remove the residue, or the next
# mutation reads a polluted corpus and reports a false failure. Worse, a harness that rewrites
# a source file and restores it inside the same filesystem-timestamp granularity leaves the
# *mutated* `.pyc` in `__pycache__`, and Python keeps executing the mutation after the source
# is back — which reads exactly like "the test does not recover". Both are handled in the
# recorded run: fixtures are snapshotted and cleaned, and every run purges bytecode with
# `PYTHONDONTWRITEBYTECODE` set.


@pytest.mark.parametrize("source", HAPPY_FIXTURES)
def test_invariant_1_the_source_is_byte_identical_and_nothing_is_written_beside_it(
    tmp_path: Path, source: Path
) -> None:
    """The input file, and the directory holding it, are unchanged by a run."""
    before_digest = sha256(source)
    before_tree = directory_listing(source.parent)

    process_image(
        build_image_request_for(source, tmp_path / "image"), engine=EngineChoice.OPENCV
    )

    assert sha256(source) == before_digest
    assert directory_listing(source.parent) == before_tree


def test_invariant_1_holds_when_the_confrontation_is_harsher(tmp_path: Path) -> None:
    """The source keeps its digest even when every option that writes is switched on.

    A separate test from the sweep above because the failure mode differs: the sweep proves a
    normal run is read-only, this one proves no *optional* artifact path reaches back to the
    input. The first draft of the plan's mutation — "write to `image_path` in place" — is only
    reachable when an artifact is actually produced, so a run with normalization off would not
    have caught it.
    """
    before_digest = sha256(SKEWED_TEXT)

    result = process_image(
        build_image_request_for(SKEWED_TEXT, tmp_path / "image"),
        engine=EngineChoice.OPENCV,
    )

    assert result.normalized is not None
    assert result.variants.ocr_ready is not None
    assert result.variants.vlm_ready is not None
    assert sha256(SKEWED_TEXT) == before_digest


def test_invariant_1_the_source_reference_points_at_the_original(
    tmp_path: Path,
) -> None:
    """The result names the input it read, not a copy this processor made of it.

    A processor that copied its input into the namespace and reported *that* as the source would
    pass every hash test above while making the provenance chain point at itself.
    """
    request = build_image_request_for(COLOR_LAYOUT, tmp_path / "image")

    result = process_image(request, engine=EngineChoice.OPENCV)

    assert result.source.path == COLOR_LAYOUT
    assert result.source.size == COLOR_LAYOUT.stat().st_size
    assert not any(
        path.name.startswith("color_layout")
        for path in request.output_dir.rglob("*")
        if path.is_file() and path.name != "metadata.json"
    ), "the input was copied into the namespace"


# ======================================================================================
# Invariant 2 — the OCR variant is not the VLM variant
# ======================================================================================
# Mutation: in `variants.publish_variants`, pass `OCR_FILE_NAME` for the VLM artifact so both
# refs resolve to `ocr_ready.png`. Observed: two tests FAIL —
# `test_invariant_2_the_two_variants_are_separate_files_with_different_bytes`
# (`assert .../ocr_ready.png != .../ocr_ready.png`) and
# `test_invariant_2_the_vlm_variant_keeps_colour_while_the_ocr_variant_may_not` (the OCR bytes
# were overwritten by the VLM ones, so the reloaded "OCR" variant came back with 3 channels).
# Restored: green (4 passed).
#
# A second mutation covers the other half: `prepare_image_for_vlm` returns
# `prepare_image_for_ocr(...)` directly. Observed: the same two tests fail — the paths differ,
# but the VLM artifact comes back with 1 channel. Restored: green.
#
# Colour is the assertion that carries the real weight. Two distinct *paths* still permit one
# pipeline to have produced the other's pixels — precisely the confusion the plan warns about:
# "it never assumes the OCR-optimal image equals the VLM-optimal image". The channel counts are
# what make the two outputs genuinely different representations, and only the second mutation is
# caught by them alone.


def test_invariant_2_the_two_variants_are_separate_files_with_different_bytes(
    tmp_path: Path,
) -> None:
    """Both variants exist, at different paths, holding different bytes."""
    request = build_image_request_for(SKEWED_TEXT, tmp_path / "image")

    result = process_image(request, engine=EngineChoice.OPENCV)

    ocr = result.variants.ocr_ready
    vlm = result.variants.vlm_ready
    assert ocr is not None
    assert vlm is not None
    assert ocr.path != vlm.path
    assert ocr.path.name == "ocr_ready.png"
    assert vlm.path.name == "vlm_ready.png"
    assert ocr.path.read_bytes() != vlm.path.read_bytes()


def test_invariant_2_the_vlm_variant_keeps_colour_while_the_ocr_variant_may_not(
    tmp_path: Path,
) -> None:
    """The observable difference between the two representations, measured from the files.

    Read back from disk rather than from the in-memory arrays, because the pipeline's promise is
    about the artifacts a later stage will read, and a variant that was correct in memory could
    still have been written through the wrong encoder.
    """

    request = build_image_request_for(COLOR_LAYOUT, tmp_path / "image")

    result = process_image(request, engine=EngineChoice.OPENCV)

    assert result.variants.ocr_ready is not None
    assert result.variants.vlm_ready is not None
    ocr_pixels = load_image(result.variants.ocr_ready.path, EngineChoice.OPENCV)
    vlm_pixels = load_image(result.variants.vlm_ready.path, EngineChoice.OPENCV)

    assert vlm_pixels.ndim == 3, "the VLM variant lost its colour channels"
    assert vlm_pixels.shape[2] == 3
    assert ocr_pixels.ndim == 2, (
        "the OCR variant kept three channels; it is meant to be one"
    )


def test_invariant_2_the_two_pipelines_are_separate_functions_not_one_with_a_flag() -> (
    None
):
    """The OCR and VLM pipelines are two functions, checked in the source.

    A behavioural test cannot see this: one function with a `mode` flag can produce two correct
    outputs today and be merged into a single path by the next change. The plan states the
    independence as a property of the design, so it is asserted where the design lives. This is
    an **invariant test in the source**, which is weaker than a behavioural one — it is here
    because there is no behavioural observation that distinguishes the two shapes.

    The VLM source is also checked for the operations that destroy what a VLM needs: a single
    code path that binarized and then claimed to preserve layout would pass every test above.
    """

    ocr_source = inspect.getsource(variants.prepare_image_for_ocr)
    vlm_source = inspect.getsource(variants.prepare_image_for_vlm)
    assert ocr_source != vlm_source
    assert "convert_to_grayscale" in ocr_source

    for destroyed in ("binarize_image", "convert_to_grayscale", "denoise_image"):
        assert destroyed not in vlm_source, (
            f"the VLM pipeline calls {destroyed}, which destroys the layout and colour it "
            "exists to preserve"
        )


def test_invariant_2_requesting_one_variant_does_not_produce_the_other(
    tmp_path: Path,
) -> None:
    """The flags are independent, and neither implies the other."""
    request = build_image_request_for(COLOR_LAYOUT, tmp_path / "image")
    request = ImageRequest(
        image_path=request.image_path,
        output_dir=request.output_dir,
        options=ImageOptions(
            normalize=True,
            prepare_for_ocr=True,
            prepare_for_vlm=False,
            correct_orientation=True,
            deskew=True,
        ),
        context=request.context,
    )

    result = process_image(request, engine=EngineChoice.OPENCV)

    assert result.variants.ocr_ready is not None
    assert result.variants.vlm_ready is None
    assert not (request.output_dir / "vlm_ready.png").exists()
    assert namespace_tree(request.output_dir) == [
        "metadata.json",
        "normalized.png",
        "ocr_ready.png",
    ]


# ======================================================================================
# Invariant 3 — namespace ownership
# ======================================================================================
# Mutation: in `composition.succeed`, publish `metadata.json` to
# `self.request.output_dir.parent` — the page directory rather than the `image/` one. Observed:
# two tests FAIL — `test_invariant_3_every_artifact_resolves_under_the_namespace`
# (`.../metadata.json` is not under `.../image`) and
# `test_invariant_3_nothing_is_written_into_another_processors_namespace`.
# `test_invariant_3_holds_on_the_failure_path_too` stays green, which is correct and is why it
# exists as its own test: the failure path has a *separate* publication call, so a mutation that
# redirected only that one would be invisible to the two tests above. Restored: green (3 passed).
#
# The invariant is stated over the *parent* directory rather than over `image/`, because the
# failure it guards against is precisely a write that escaped upward. Asserting inside the
# namespace would still be true of a run that also wrote outside it.


def _page_root(tmp_path: Path) -> Path:
    """Return a page directory with the sibling namespaces other processors own.

    Args:
        tmp_path: The test's temporary directory.

    Returns:
        The page directory, with an empty directory per foreign namespace.
    """
    root = tmp_path / "page_001"
    root.mkdir()
    for namespace in IMAGE_NAMESPACES_OWNED_BY_OTHERS:
        (root / namespace).mkdir()
    return root


def test_invariant_3_every_artifact_resolves_under_the_namespace(
    tmp_path: Path,
) -> None:
    """Every published file — images and ``metadata.json`` alike — lives under ``image/``."""
    root = _page_root(tmp_path)
    request = build_image_request_for(COLOR_LAYOUT, root / "image")

    result = process_image(request, engine=EngineChoice.OPENCV)

    published = [
        *result.artifacts,
        result.normalized,
        result.variants.ocr_ready,
        result.variants.vlm_ready,
    ]
    resolved_namespace = request.output_dir.resolve()
    for artifact in published:
        if artifact is None:
            continue
        assert artifact.path.resolve().is_relative_to(resolved_namespace), artifact.path
    assert (request.output_dir / "metadata.json").is_file()
    assert namespace_tree(request.output_dir) == sorted(IMAGE_ARTIFACT_TREE)


def test_invariant_3_nothing_is_written_into_another_processors_namespace(
    tmp_path: Path,
) -> None:
    """``source/``, ``render/``, ``native_text/``, ``ocr/`` and ``llm/`` stay empty.

    Those directories belong to other processors, and writing into one would have this processor
    claim work it does not do.
    """
    root = _page_root(tmp_path)

    process_image(
        build_image_request_for(SKEWED_TEXT, root / "image"), engine=EngineChoice.OPENCV
    )

    for namespace in IMAGE_NAMESPACES_OWNED_BY_OTHERS:
        assert directory_listing(root / namespace) == [], (
            f"{namespace}/ was written into"
        )
    # And the only thing at page level is the `image/` namespace itself.
    assert sorted(entry.name for entry in root.iterdir()) == sorted(
        (*IMAGE_NAMESPACES_OWNED_BY_OTHERS, "image")
    )


def test_invariant_3_holds_on_the_failure_path_too(tmp_path: Path) -> None:
    """A failed run writes its record inside the namespace, not beside it.

    The failure path has its own publication call, so it can escape the namespace independently
    of the happy path — and a mutation that redirected only that one would be invisible to the
    test above.
    """
    root = _page_root(tmp_path)
    request = build_image_request_for(CORRUPT, root / "image")

    result = process_image(request, engine=EngineChoice.OPENCV)

    assert result.status == "failed"
    assert (root / "metadata.json").exists() is False
    assert namespace_tree(root / "image") == ["metadata.json"]
    for namespace in IMAGE_NAMESPACES_OWNED_BY_OTHERS:
        assert directory_listing(root / namespace) == []


# ======================================================================================
# A failed run is as clean as a successful one
# ======================================================================================


def test_a_failed_run_leaves_no_staged_file_and_no_final_named_artifact(
    tmp_path: Path,
) -> None:
    """``IMG-11``'s guarantee, observed through the entry point rather than the primitive."""
    request = build_image_request_for(CORRUPT, tmp_path / "image")

    result = process_image(request, engine=EngineChoice.OPENCV)

    assert result.status == "failed"
    assert not (request.output_dir / ".tmp").exists()
    assert not list(request.output_dir.rglob("*.tmp"))
    assert not (request.output_dir / "normalized.png").exists()
    assert not (request.output_dir / "ocr_ready.png").exists()
    assert not (request.output_dir / "vlm_ready.png").exists()
    assert namespace_tree(request.output_dir) == ["metadata.json"]


def test_a_failed_run_after_a_successful_one_removes_the_earlier_artifacts(
    tmp_path: Path,
) -> None:
    """The second run over the same directory must not leave the first run's output in place.

    This is the failure the first draft of ``IMG-12`` had: the cleanup ran on two of eight failure
    paths, so a decode failure left a complete, valid-looking artifact set from a previous run for
    a reader to mistake for this one's.
    """
    output_dir = tmp_path / "image"
    first = process_image(
        build_image_request_for(COLOR_LAYOUT, output_dir), engine=EngineChoice.OPENCV
    )
    assert first.status == "success"
    assert (output_dir / "normalized.png").is_file()

    second = process_image(
        build_image_request_for(CORRUPT, output_dir), engine=EngineChoice.OPENCV
    )

    assert second.status == "failed"
    assert namespace_tree(output_dir) == ["metadata.json"]


def test_the_failure_record_names_the_cause_and_parses(tmp_path: Path) -> None:
    """A failed run's ``metadata.json`` says what went wrong, for an operator reading it later."""
    request = build_image_request_for(CORRUPT, tmp_path / "image")

    result = process_image(request, engine=EngineChoice.OPENCV)

    payload = json.loads(
        (request.output_dir / "metadata.json").read_text(encoding="utf-8")
    )
    assert payload["status"] == "ERROR"
    assert payload["failed_before_publish"] is True
    assert payload["input"]["dimensions_measured"] is False
    assert result.error is not None
    assert payload["errors"][0]["type"] == result.error.type
    assert payload["errors"][0]["message"]


# ======================================================================================
# Purity — no processor is imported, no workflow decision is made
# ======================================================================================


def test_no_other_processor_appears_in_the_image_processors_imports() -> None:
    """The image processor imports no sibling, checked in the source of every module.

    ``docs/plan/README.md`` §3: a processor never calls another processor; only the orchestrator
    composes them. An import would make this processor depend on the deployment order of the
    others and would be the first step towards it making a workflow decision.
    """
    package = Path(__file__).resolve().parents[2] / "src" / "docflow" / "image"
    forbidden = ("docflow.pdf", "docflow.ocr", "docflow.llm", "docflow.workflow")
    offenders: list[str] = []

    for module in sorted(package.rglob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                if name.startswith(forbidden):
                    offenders.append(f"{module.name}: {name}")

    assert offenders == [], f"the image processor imports a sibling: {offenders}"


def test_no_workflow_vocabulary_appears_in_the_result(tmp_path: Path) -> None:
    """The result carries descriptive states only, never an instruction for what runs next.

    The validation states and the classification are descriptive by contract. A result that
    carried ``requires_ocr`` or a stage name would be this processor answering a question the
    orchestrator owns.
    """
    request = build_image_request_for(COLOR_LAYOUT, tmp_path / "image")

    result = process_image(request, engine=EngineChoice.OPENCV)

    declared = {field.name for field in fields(ImageResult)}
    assert not declared & {
        "next_stage",
        "requires_ocr",
        "requires_vlm",
        "skip",
        "force",
        "resume",
        "pipeline",
    }
    assert result.validation.status in ("VALID", "LOW_QUALITY")


def test_the_engine_is_recorded_explicitly_and_never_defaulted(tmp_path: Path) -> None:
    """Two engines, two provenance records: nothing is substituted for the caller's choice."""
    opencv = process_image(
        build_image_request_for(COLOR_LAYOUT, tmp_path / "opencv"),
        engine=EngineChoice.OPENCV,
    )
    pillow = process_image(
        build_image_request_for(COLOR_LAYOUT, tmp_path / "pillow"),
        engine=EngineChoice.PILLOW,
    )

    assert opencv.metadata.engine == "opencv"
    assert pillow.metadata.engine == "pillow"
    assert opencv.metadata.engine_version != pillow.metadata.engine_version
    assert opencv.metadata.libraries["opencv"]
    assert pillow.metadata.libraries["pillow"]
