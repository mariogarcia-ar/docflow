"""End-to-end tests for ``process_ocr_image`` (``OCR-11``).

Lives beside ``tests/ocr/test_contracts.py`` rather than under ``primitives/`` because it does not
test a primitive: it drives the processor's published entry point, which is what
``src/docflow/ocr/entrypoints.py`` is. The name mirrors that module, as
``tests/image/test_entrypoints.py`` and ``tests/pdf/test_entrypoints.py`` mirror theirs.

The location is also load-bearing. It used to be ``primitives/test_composition.py``, and
``test_composition`` sorts before ``test_engine`` inside ``primitives/`` — so this module's first
conversion imported Docling before ``test_engine``'s "the seam is lazy" assertions ran, and those
failed against a polluted process rather than against the code. Two tests failed that way and passed
in isolation, which is the signature of an ordering collision rather than a defect. Naming the file
after the module it exercises is what puts it after ``primitives/`` in collection order and restores
the invariant.

Two acceptance criteria, and the second is the one that shapes this module:

1. A valid request over a prepared image reaches ``status == "success"``,
   ``validation.status == "VALID"``, and the ``ocr/`` namespace holds ``text.txt``, ``document.md``,
   ``document.json`` and ``metadata.json``.
2. The same input run twice into two output directories produces a byte-identical ``document.json``
   and a ``metadata.json`` that differs **only** in its timing fields.

Criterion 2 is why nothing here asserts a shape the artifact could satisfy by accident. Two runs of
one page must agree on *every* field but the clock, so the test diffs the two payloads field by
field with the timing subtree removed rather than comparing a digest — a digest that matched would
not say *which* field had been allowed to vary, and the interesting failure is precisely a
plausible-looking field that drifted.

These tests run the real engine over the committed fixture. That is deliberate: the chain's whole
job is to hand the engine's output to five primitives in the right order, and a test that stubbed
the engine would assert the order against a mock instead of against the conversion the order exists
to serve. The suite pays for one conversion per output directory, which is why the count is kept
low.
"""

from __future__ import annotations

# pylint: disable=duplicate-code
# This module is parallel to `tests.image.test_entrypoints`, and the overlap is the shape of an
# end-to-end suite rather than shared logic: both drive a processor's published entry point over a
# committed fixture, assert the namespace it publishes, diff two runs for determinism, and check the
# same failure modes (a missing input, a rerun over a previous run's artifacts).
# `docs/plan/README.md` §3 forbids a processor importing another, so the *production* duplication
# cannot be factored out; and a shared test helper would be a fifth name whose owner no task names.
# The overlap is confined to assertion scaffolding - the values asserted, the fixtures and the
# primitives exercised are this processor's own.
import inspect
import itertools
import json
import typing
from pathlib import Path
from typing import Any

import pytest

from docflow.ocr import entrypoints
from docflow.ocr.contracts import (
    OCRContext,
    OCRDocument,
    OCROptions,
    OCRRequest,
    OCRResult,
    OCRValidation,
)
from docflow.ocr.entrypoints import process_ocr_image
from docflow.ocr.primitives import composition, files, validation
from docflow.ocr.primitives import layout as layout_module
from docflow.ocr.primitives.composition import (
    RECORDED_STAGES,
    process_ocr_result,
)
from tests.ocr.primitives.engine_corpus import (
    BLANK_FIXTURE,
    FIXTURE,
    REPO_ROOT,
    extracted_document,
    requested_options,
)

#: The four files criterion 1 names, in the order §3.2's tree lists them.
REQUIRED_ARTIFACTS: tuple[str, ...] = (
    "text.txt",
    "document.md",
    "document.json",
    "metadata.json",
)

#: Provenance fields that a second run is *allowed* to differ in. Everything else must not.
#:
#: Timing is wall-clock and cannot be reproducible; the plan's posture is that ``metadata.json`` is
#: the only artifact permitted to carry it, and the determinism criterion is phrased as "differs
#: only in timing fields" - so the allowance is stated here as data rather than as a filter written
#: inline, and a test below asserts that nothing else in the file is allowed to move.
TIMING_FIELDS: tuple[str, ...] = ("timing",)


def request_for(output_dir: Path, *, options: OCROptions | None = None) -> OCRRequest:
    """Return a request over the committed content fixture rooted at ``output_dir``.

    Args:
        output_dir: The ``ocr/`` namespace this run owns.
        options: The raw options, or ``None`` for the corpus' "everything this processor can
            extract" set.

    Returns:
        The request.
    """
    return OCRRequest(
        image_path=FIXTURE,
        output_dir=output_dir,
        options=options if options is not None else requested_options(),
        context=OCRContext(document_id="doc-1", page_number=1, workflow_run_id="run-1"),
    )


def run_into(output_dir: Path, **kwargs: Any) -> OCRResult:
    """Run the entry point over the fixture into ``output_dir``.

    Args:
        output_dir: The ``ocr/`` namespace this run owns.
        **kwargs: Passed through to :func:`request_for`.

    Returns:
        The result.
    """
    return process_ocr_image(request_for(output_dir, **kwargs))


def payload_of(output_dir: Path, name: str) -> dict[str, Any]:
    """Read a published JSON artifact back.

    Args:
        output_dir: The ``ocr/`` namespace.
        name: The file's name.

    Returns:
        The parsed object.
    """
    return json.loads((output_dir / name).read_text(encoding="utf-8"))


def without_timing(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of a payload with every allowed-to-vary field removed.

    Args:
        payload: The ``metadata.json`` object.

    Returns:
        The object, minus :data:`TIMING_FIELDS`.
    """
    return {key: value for key, value in payload.items() if key not in TIMING_FIELDS}


# ======================================================================================
# Criterion 1 - a valid request reaches success and publishes the four artifacts
# ======================================================================================


def test_a_valid_request_reaches_success_and_publishes_the_four_artifacts(
    tmp_path: Path,
) -> None:
    """The criterion, end to end: the status, the verdict and the namespace.

    All three are asserted together because they are one claim. ``status == "success"`` with an
    ``INCOMPLETE`` verdict would mean the run reported files it did not write, and a ``VALID``
    verdict with a missing file would mean the validator inspected a namespace other than the one
    the caller holds.
    """
    output_dir = tmp_path / "ocr"

    result = run_into(output_dir)

    assert result.status == "success"
    assert result.validation.status == "VALID"
    assert result.error is None
    for name in REQUIRED_ARTIFACTS:
        assert (output_dir / name).is_file(), f"{name} was not published"


def test_the_published_paths_are_the_files_that_exist(tmp_path: Path) -> None:
    """``result.artifacts`` names real files, so a consumer can read what it was handed.

    A result whose paths are built from the request rather than from the publish is the failure this
    guards: it would be correct in shape and wrong in fact, and every field a caller checks would
    agree with it.
    """
    result = run_into(tmp_path / "ocr")

    for path in (
        result.artifacts.text,
        result.artifacts.markdown,
        result.artifacts.structured_document,
        result.artifacts.metadata,
    ):
        assert path.is_file(), f"{path} does not exist"


def test_the_layout_is_normalized_and_the_reading_order_is_the_computed_one(
    tmp_path: Path,
) -> None:
    """The wiring ``OCR-11`` exists to do, asserted where the flow actually runs.

    Two things are checked, and both were previously gaps rather than features:

    * **The frame.** ``OCR-04`` extracts the engine's pixels (measured, 840 by 1036) and says in
      as many words that it does not normalize; §9's frozen decision 4 requires "normalized 0-1
      coordinates". Before this task no production module called ``normalize_layout``, so
      ``document.json`` carried pixels.
    * **The order.** ``preserve_reading_order`` positions ``table_001`` at index 10 — between the
      line items and the totals, where it is on the page — while the engine lists it last, at index
      19. Asserting the index rather than "the order changed" is what makes this test fail if the
      sort is dropped: the engine's order is a perfectly plausible list.

    The artifact is read from disk rather than from the result, because the artifact is what a
    consumer sees and this is the test that says the two agree.
    """
    output_dir = tmp_path / "ocr"

    run_into(output_dir)
    payload = payload_of(output_dir, "document.json")

    assert payload["layout"]["page_width"] == 1.0
    assert payload["layout"]["page_height"] == 1.0
    for box in payload["layout"]["region_bboxes"]:
        assert all(0.0 <= value <= 1.0 for value in box), (
            f"outside the unit square: {box}"
        )

    ordered = payload["reading_order"]
    assert ordered.index("table_001") == 10, (
        f"the table is not in the computed reading order: {ordered}"
    )
    assert [block["block_id"] for block in payload["blocks"]] == [
        name for name in ordered if name.startswith("block_")
    ]


def test_the_reading_order_is_independent_of_the_sorting_frame() -> None:
    """The order the sort produces is the same in the engine's pixels as in the unit frame.

    This is asserted because the *opposite* was believed, in writing, for six tasks. ``layout.py``
    said the two frames "would disagree the moment a page was not square", and that claim is false
    and cannot be true: normalization divides each axis by that axis' own size, so it is monotone
    per axis and preserves every ordering comparison. Measured on the committed fixture, the
    engine's pixel frame, the normalized frame and a 10x-scaled frame give the identical order.

    What the normalization changes is the coordinate *values* the artifact carries, and what
    reorders a page is the **origin flip** (``BOTTOMLEFT`` to ``TOPLEFT``), not the scale. Asserting
    the invariance here is also what makes the mutation battery honest: a mutation that swaps the
    page dimensions is an **equivalent mutant** — no test can distinguish it, because the property
    is a theorem — so recording it as "survived" without this test would let a reader mistake a
    proof for a gap.
    """
    document = extracted_document()
    width = document.layout.page_width
    height = document.layout.page_height
    assert width > 1.0, "the fixture is already normalized; this test's premise moved"

    pixel_order = _order_in_frame(document, width, height)
    unit_order = _order_in_frame(document, 1.0, 1.0)
    scaled_order = _order_in_frame(document, width * 10.0, height * 10.0)

    assert pixel_order == unit_order, "the sort is not frame-invariant"
    assert scaled_order == unit_order, "a uniform rescale changed the reading order"
    assert pixel_order != document.reading_order, (
        "the fixture's items already arrive in sorted order, so this test proves nothing"
    )


def _order_in_frame(
    document: OCRDocument, page_width: float, page_height: float
) -> list[str]:
    """Order a document's items using a given page frame.

    Args:
        document: The extracted document, in the engine's pixel frame.
        page_width: The frame's width.
        page_height: The frame's height.

    Returns:
        The identifiers in the order that frame produces.
    """
    _, _, order = layout_module.preserve_reading_order(
        document.blocks, document.tables, page_width, page_height
    )
    return order


def test_the_text_artifact_reads_in_the_order_the_payload_declares(
    tmp_path: Path,
) -> None:
    """``text.txt``'s items appear in the order ``document.json``'s ``reading_order`` gives.

    **The first version of this test asserted the opposite and measured nothing.** It compared the
    table's *line index* in a reading-order rebuild (9) against the engine's text (18) and concluded
    the engine emitted its text out of order. Line indices are skewed by the engine's blank-line
    spacing, and they hid the figure that decides the question: how many items **precede** the
    table. There are nine in both texts.

    So the assertion is content- and offset-based rather than line-based, and it is stated as the
    property the artifact must have — every ordered item's offset increases — rather than as a claim
    about which producer built it. Measured, the engine's own text satisfies it, which is why
    ``export_docling_text`` (the declared producer of ``text.txt``) reads ``document.text`` and this
    module leaves that field alone. The count of items preceding the table is asserted directly
    because it is the figure that separates the two hypotheses, and a pure ordering check would pass
    on a text that had simply dropped the table.
    """
    output_dir = tmp_path / "ocr"

    result = run_into(output_dir)
    text = (output_dir / "text.txt").read_text(encoding="utf-8")
    payload = payload_of(output_dir, "document.json")

    offsets: list[tuple[str, int]] = []
    for identifier in payload["reading_order"]:
        probe = _probe_for(result, identifier)
        if not probe:
            continue
        offset = text.find(probe)
        assert offset >= 0, f"{identifier} ({probe[:40]!r}) is absent from text.txt"
        offsets.append((identifier, offset))

    assert len(offsets) >= len(payload["reading_order"]) - 3, (
        "too few items were locatable for the ordering claim to mean anything"
    )
    for (earlier, first), (later, second) in itertools.pairwise(offsets):
        assert first <= second, f"{earlier} appears after {later} in the text"

    table_offset = next(offset for name, offset in offsets if name == "table_001")
    preceding = [name for name, offset in offsets if offset < table_offset]
    assert len(preceding) == 9, (
        f"{len(preceding)} items precede the table, not the 9 the page has: {preceding}"
    )


def _probe_for(result: OCRResult, identifier: str) -> str:
    """Return a distinctive snippet for one ordered item.

    Args:
        result: The run's result, carrying the blocks and tables.
        identifier: The item's id.

    Returns:
        A snippet to search the text for, or ``""`` when the item carries no text.
    """
    for block in result.blocks:
        if block.block_id == identifier:
            return block.text.strip()
    for table in result.tables:
        if table.table_id == identifier and table.cells:
            return table.cells[0][0].strip()
    return ""


def test_a_run_leaves_no_staging_residue(tmp_path: Path) -> None:
    """The namespace holds the artifacts and nothing else.

    ``metadata.json`` is written twice — once with the provisional verdict, once with the real one —
    and each write stages through ``.tmp``. The second write is what makes this worth asserting:
    two renames must still leave one empty staging directory pruned, not one left behind because the
    first write created it and the second did not revisit.
    """
    output_dir = tmp_path / "ocr"

    run_into(output_dir)

    assert not (output_dir / files.TEMP_DIRECTORY_NAME).exists()
    assert [
        path.name for path in sorted(output_dir.iterdir()) if path.is_file()
    ] == sorted(REQUIRED_ARTIFACTS)
    assert not list(output_dir.glob(f"*{files.TEMP_SUFFIX}"))


def test_the_run_publishes_a_table_artifact_for_the_fixture(tmp_path: Path) -> None:
    """A page with a table gets its per-table Markdown, under ``tables/``.

    ``tables/`` is deliberately not a *required* artifact — a tableless page needs none — so its
    presence has to be asserted from the content rather than from the required list.
    """
    output_dir = tmp_path / "ocr"

    result = run_into(output_dir)

    assert result.tables, "the fixture's table was not extracted"
    assert (output_dir / "tables").is_dir()
    published = sorted(path.name for path in (output_dir / "tables").iterdir())
    assert published == ["table_001.md"]


def test_the_metrics_describe_the_extraction(tmp_path: Path) -> None:
    """The measured figures land on the result and in the artifact.

    The density is asserted as "greater than zero" rather than against a literal: it is measured in
    the layout's own frame, and the flow normalizes that frame to a unit page, so the figure equals
    the character count — a legitimate reading that
    :func:`docflow.ocr.primitives.layout.calculate_ocr_text_density` documents — and one that would
    make a pixel-frame literal wrong.
    """
    output_dir = tmp_path / "ocr"

    result = run_into(output_dir)

    assert result.metrics.characters > 0
    assert result.metrics.words > 0
    assert result.metrics.blocks == len(result.blocks)
    assert result.metrics.tables == len(result.tables)
    assert result.metrics.empty is False
    assert result.metrics.structure_detected is True
    assert result.metrics.text_density > 0.0


# ======================================================================================
# Criterion 2 - two runs agree on everything but the clock
# ======================================================================================


def test_two_runs_produce_a_byte_identical_document_json(tmp_path: Path) -> None:
    """The criterion's first half, byte for byte and not merely semantically.

    Byte-identity is the stronger claim and the one the plan asks for: it is what lets a consumer
    diff two artifacts and trust that a difference is real. Serialization sorts keys and fixes the
    indent for exactly this reason, and a run whose payload was equal but whose rendering was not
    would pass a dictionary comparison and fail this.
    """
    first, second = tmp_path / "ocr-a", tmp_path / "ocr-b"

    run_into(first)
    run_into(second)

    assert (first / "document.json").read_bytes() == (
        second / "document.json"
    ).read_bytes()


def test_two_runs_agree_on_every_artifact_that_is_not_allowed_to_differ(
    tmp_path: Path,
) -> None:
    """``text.txt`` and ``document.md`` are byte-identical too.

    Only ``metadata.json`` may carry the clock, so the other two have no allowance at all.
    Asserting them separately from ``document.json`` keeps the failure legible: three files can
    drift for three different reasons, and one assertion over all three would report only that
    something moved.
    """
    first, second = tmp_path / "ocr-a", tmp_path / "ocr-b"

    run_into(first)
    run_into(second)

    for name in ("text.txt", "document.md"):
        assert (first / name).read_bytes() == (second / name).read_bytes(), (
            f"{name} moved"
        )


def test_two_runs_differ_in_metadata_timing_and_in_nothing_else(tmp_path: Path) -> None:
    """The criterion's second half, and the only allowed difference is named.

    The two payloads are compared with :data:`TIMING_FIELDS` removed, so the assertion covers every
    other key the record carries — the engine and its version, the processor version, the options,
    the input path, the metrics, the verdict, the transformations, the context, the processing key
    and the tables published. A field that quietly started carrying a timestamp, a temporary path or
    a run counter would surface here rather than in a digest that nobody could read.

    The timing subtree is then asserted to be *present* and *numeric* in both, because "differs only
    in timing" is only true if timing is there to differ in — a run that stopped recording it would
    satisfy the diff trivially.
    """
    first, second = tmp_path / "ocr-a", tmp_path / "ocr-b"

    run_into(first)
    run_into(second)
    payload_a = payload_of(first, "metadata.json")
    payload_b = payload_of(second, "metadata.json")

    for name in TIMING_FIELDS:
        assert name in payload_a, f"{name} is missing, so the diff proves nothing"
        assert isinstance(payload_a[name], dict)
        assert payload_a[name], "the timing record is empty"
        for stage, seconds in payload_a[name].items():
            assert isinstance(seconds, (int, float)), (
                f"{stage} is not a duration: {seconds!r}"
            )
        assert payload_b[name].keys() == payload_a[name].keys(), (
            "two runs recorded different stages"
        )

    assert without_timing(payload_a) == without_timing(payload_b)


def test_the_timing_record_names_every_stage_whose_duration_can_be_known(
    tmp_path: Path,
) -> None:
    """The recorded stages are the ones the run can finish measuring, plus the total.

    ``metadata.json`` is the only home of timing, and a stage that ran without being recorded would
    make the record a partial account that still looked complete. The set compared against is
    ``RECORDED_STAGES`` — every stage but ``publish_metadata``, which writes this very file and so
    cannot contribute a duration to it — so the comparison is against the flow's own list rather
    than against a second copy of the stage names in this module.

    ``total`` is asserted to be at least the longest stage rather than the sum of all of them: the
    stages run in sequence, so ``total`` must dominate each one, and the sum would be wrong by the
    duration of whichever stage is missing from the record by design.
    """
    output_dir = tmp_path / "ocr"

    run_into(output_dir)
    timing = payload_of(output_dir, "metadata.json")["timing"]

    assert set(timing) == set(RECORDED_STAGES), (
        f"unrecorded stages: {sorted(set(RECORDED_STAGES) - set(timing))}; "
        f"invented stages: {sorted(set(timing) - set(RECORDED_STAGES))}"
    )
    assert timing["total"] >= max(timing[stage] for stage in RECORDED_STAGES)


# ======================================================================================
# The contract boundary - a failure is reported, never raised
# ======================================================================================


def test_a_missing_input_is_reported_as_a_typed_failure_not_an_exception(
    tmp_path: Path,
) -> None:
    """A bad request reaches the caller as a result, and nothing escapes.

    This is the boundary the plan draws: the orchestrator reads ``status`` and ``error`` and
    decides, so a processor that raised would push a decision it does not own onto its caller.
    """
    request = OCRRequest(
        image_path=tmp_path / "absent.png",
        output_dir=tmp_path / "ocr",
        options=requested_options(),
        context=OCRContext(document_id="doc-1", page_number=1, workflow_run_id="run-1"),
    )

    result = process_ocr_image(request)

    assert result.status == "failed"
    assert result.error is not None
    assert result.validation.status == "ERROR"
    assert result.validation.errors, "the failed run classified nothing"


def test_a_failed_run_publishes_nothing_it_could_be_mistaken_for(
    tmp_path: Path,
) -> None:
    """A failed run leaves an empty namespace, not a plausible artifact.

    ``abandon`` removes the staged files and the published ones together. A run that died after
    writing ``text.txt`` would otherwise leave a file a later stage would read as this run's answer.
    """
    output_dir = tmp_path / "ocr"
    request = OCRRequest(
        image_path=tmp_path / "absent.png",
        output_dir=output_dir,
        options=requested_options(),
        context=OCRContext(document_id="doc-1", page_number=1, workflow_run_id="run-1"),
    )

    process_ocr_image(request)

    for name in REQUIRED_ARTIFACTS:
        assert not (output_dir / name).exists(), f"{name} survived a failed run"
    assert not (output_dir / files.TEMP_DIRECTORY_NAME).exists()


def test_a_failed_run_replaces_the_artifacts_a_previous_run_left(
    tmp_path: Path,
) -> None:
    """A second run into the same namespace does not leave the first run's answer behind.

    This is the failure mode the image processor records: a rerun that fails must not leave the
    previous run's artifact sitting under the name this run was supposed to publish, because nothing
    downstream could tell the two apart.
    """
    output_dir = tmp_path / "ocr"
    run_into(output_dir)
    assert (output_dir / "text.txt").is_file()

    failed = OCRRequest(
        image_path=tmp_path / "absent.png",
        output_dir=output_dir,
        options=requested_options(),
        context=OCRContext(document_id="doc-1", page_number=1, workflow_run_id="run-1"),
    )
    result = process_ocr_image(failed)

    assert result.status == "failed"
    assert not (output_dir / "text.txt").exists()
    assert not (output_dir / "document.json").exists()


def test_the_empty_fixture_validates_as_empty_and_still_publishes(
    tmp_path: Path,
) -> None:
    """``EMPTY`` is a verdict, not a failure: the artifacts are still written.

    The plan is explicit that the processor reports this state rather than acting on it —
    ``LOW_CONTENT -> use the VLM`` is the orchestrator's decision and this module does not know the
    VLM exists. So a blank page must still reach ``status == "success"`` with its namespace
    populated, and the verdict must say what the page was.
    """
    output_dir = tmp_path / "ocr"
    request = OCRRequest(
        image_path=BLANK_FIXTURE,
        output_dir=output_dir,
        options=requested_options(),
        context=OCRContext(document_id="doc-1", page_number=1, workflow_run_id="run-1"),
    )

    result = process_ocr_image(request)

    assert result.status == "success"
    assert result.validation.status == "EMPTY"
    assert result.metrics.empty is True
    for name in REQUIRED_ARTIFACTS:
        assert (output_dir / name).is_file(), (
            f"{name} was not published for a blank page"
        )


def test_the_processing_key_is_recorded_as_not_computed(tmp_path: Path) -> None:
    """``None`` is recorded as ``None``, because that is the true answer.

    ``ORC-02`` owns the formula, so this processor cannot compute a key — and a processor that
    invented one would publish a value a cache would trust.
    """
    output_dir = tmp_path / "ocr"

    run_into(output_dir)

    assert payload_of(output_dir, "metadata.json")["processing_key"] is None


def test_a_supplied_processing_key_is_recorded_verbatim(tmp_path: Path) -> None:
    """A key the orchestrator computed travels through unchanged."""
    output_dir = tmp_path / "ocr"

    process_ocr_image(
        request_for(output_dir), processing_key="key-from-the-orchestrator"
    )

    assert (
        payload_of(output_dir, "metadata.json")["processing_key"]
        == "key-from-the-orchestrator"
    )


# ======================================================================================
# The entry point's own shape
# ======================================================================================


def test_the_entry_point_declares_the_frozen_signature() -> None:
    """``process_ocr_image(request)`` is the frozen surface; nothing was added beside it.

    ``docs/plan/README.md`` §4 fixes the name, and ``tests/test_skeleton.py`` fixes that it is
    resolvable, callable and fully annotated. What this adds is that the *only* extra parameter is
    the keyword-only processing key: a second positional parameter would be a second contract, and
    the plan's §3.4 names one.

    ``process_ocr_from_page`` is deliberately absent. §9's resolved decision 5 defers it to Phase 3,
    and a wrapper whose only input the caller already holds would be argument shuffling.
    """
    signature = inspect.signature(process_ocr_image)
    parameters = list(signature.parameters.values())
    hints = typing.get_type_hints(process_ocr_image)

    assert parameters[0].name == "request"
    assert hints["request"] is OCRRequest, hints["request"]
    assert hints["return"] is OCRResult, hints["return"]
    assert [parameter.name for parameter in parameters] == ["request", "processing_key"]
    assert parameters[1].kind is inspect.Parameter.KEYWORD_ONLY
    assert not hasattr(entrypoints, "process_ocr_from_page")


def test_the_composition_refuses_a_processing_key_it_was_not_given() -> None:
    """The composition's key is required and keyword-only, so no caller can omit it silently.

    ``None`` means "the orchestrator has not computed one", which is a statement a caller has to
    make deliberately; the signature suite refuses a defaulted argument, and this asserts the
    refusal still holds at the internal boundary as well as the published one.
    """
    parameter = inspect.signature(process_ocr_result).parameters["processing_key"]

    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is inspect.Parameter.empty


def test_every_stage_the_composition_names_is_a_stage_it_runs() -> None:
    """``RUN_STAGES`` and the executed tuple describe the same flow, in the same order.

    The tuple of bound methods in ``process_ocr_result`` is what runs and ``RUN_STAGES`` is what
    gets recorded, so the two drifting would produce a timing record that named stages nobody ran
    — or, worse, a stage that ran without appearing in the record a reader trusts.
    """
    source = inspect.getsource(composition.process_ocr_result)
    for stage in composition.RUN_STAGES:
        assert f"run.{_stage_method(stage)}" in source, (
            f"{stage} is declared but not run"
        )


def _stage_method(stage: str) -> str:
    """Map a stage's recorded name to the ``_Run`` method that runs it.

    Args:
        stage: The stage's name.

    Returns:
        The attribute name on ``_Run``.
    """
    return {"metrics": "measure"}.get(stage, stage)


def test_the_validation_this_module_trusts_reads_the_disk(tmp_path: Path) -> None:
    """The premise behind ``validate_result`` running *after* ``persist``, asserted directly.

    ``validate_ocr_result`` calls ``validate_output_artifacts``, which asks whether each promised
    path ``is_file()`` — ``metadata.json`` included. A verdict taken before the write therefore
    reports ``INCOMPLETE`` for a run that is about to publish everything, which is what the first
    draft of the composition did on every happy path.

    Pinning the premise here means a future change to the validator's reach shows up as this test
    failing rather than as a mysterious ``INCOMPLETE`` at the other end of the suite.
    """
    output_dir = tmp_path / "ocr"
    paths = files.build_ocr_output_paths(output_dir)

    assert validation.validate_output_artifacts(paths), (
        "an empty namespace reported no missing artifact, so the ordering constraint is gone"
    )

    run_into(output_dir)

    assert not validation.validate_output_artifacts(paths)


def test_an_artifact_missing_after_persist_refuses_to_settle(tmp_path: Path) -> None:
    """``validate_result`` refuses a run whose namespace is incomplete, and that guard is reachable.

    This drives the internal stage rather than the entry point, for the reason the repo records
    elsewhere: **the state cannot arise from the normal path**, because ``persist`` writes exactly
    the four artifacts the validator requires — so pointing the run at a namespace where one is
    absent is the only way to construct it. A mutation that made ``validate_result`` return ``True``
    unconditionally survived the end-to-end suite for precisely that reason, which is what this test
    closes: it is the one place the refusal is observable.

    The stage is called on a bare record rather than through ``process_ocr_result`` because the flow
    would never reach it in this state, and because the assertion is about the *verdict* the stage
    computes from what it can see on disk.
    """
    output_dir = tmp_path / "ocr"
    output_dir.mkdir()
    (output_dir / "document.md").write_text("present", encoding="utf-8")

    run = composition._Run(  # pylint: disable=protected-access
        request=request_for(output_dir), processing_key=None, started=0.0
    )

    published = run.validate_result()

    assert published is False, "an incomplete namespace was allowed to settle"
    assert run.verdict is not None
    assert run.verdict.status == "INCOMPLETE"
    assert run.verdict.missing_artifacts, "the verdict does not name what is missing"


def test_the_repo_root_the_fixture_lives_under_is_the_one_that_exists() -> None:
    """A guard on the corpus helper this module shares.

    ``REPO_ROOT`` is derived from the corpus module's own depth, so a re-nesting of the test tree
    would make every fixture path in this file wrong at once. Asserting it here turns that into one
    clear failure instead of four confusing ones.
    """
    assert (REPO_ROOT / "pyproject.toml").is_file()
    assert FIXTURE.is_file()


def test_the_contract_validation_type_is_what_the_verdict_carries(
    tmp_path: Path,
) -> None:
    """``result.validation`` is the contract's record, not something shape-compatible.

    The whole result crosses the contract boundary, so a verdict assembled from a local dataclass
    would satisfy every field assertion in this module and still be the wrong thing to hand a
    consumer.
    """
    result = run_into(tmp_path / "ocr")

    assert isinstance(result.validation, OCRValidation)
    assert result.validation.status in ("VALID", "EMPTY", "LOW_CONTENT")


@pytest.mark.parametrize("name", REQUIRED_ARTIFACTS)
def test_each_required_artifact_is_non_empty(tmp_path: Path, name: str) -> None:
    """Every published file has content, so "present" and "written" are the same claim.

    A zero-byte file would satisfy the criterion's file check and give a consumer nothing, and the
    ``EMPTY`` path is the one where that could plausibly happen: a blank page's artifacts are
    legitimately empty in the *extraction* sense, and the files that record that fact must still say
    so in bytes.
    """
    output_dir = tmp_path / "ocr"

    run_into(output_dir)

    assert (output_dir / name).stat().st_size > 0
