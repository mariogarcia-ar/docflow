# pylint: disable=duplicate-code,use-implicit-booleaness-not-comparison
# The fixture constants repeat the other image suites' on purpose, and every assertion below says
# what a list *is* rather than whether it is falsey: `errors == []` claims the run produced no
# errors, and `not errors` would also pass if the field held ``None``.
"""Tests for atomic publication and the ``metadata.json`` payload (``IMG-11``).

The WBS names two acceptance criteria: after a forced failure, `image/` holds no `.tmp` files and no
final-named artifacts; and after a successful run, `metadata.json` parses and carries the processor
and library versions, the transformations and the metrics. Both are here.

The failure-path tests build the mess a failed run leaves rather than simulating one, because the
thing being tested is what a cleanup does to files on disk:

* a staged sibling `normalized.png.tmp` left by an interrupted run,
* the `.tmp` staging directory, holding a partial file,
* a final-named artifact written before the failure.

All three must be gone afterwards, and nothing the processor did not write may be touched - which is
why one of the tests leaves an unrelated file in the directory and asserts it survives. The failure
that triggers the cleanup is provoked for real, by asking for an extension no encoder claims.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from docflow.identities import ARTIFACT_METADATA_KEYS
from docflow.image.contracts import (
    ArtifactRef,
    ImageContext,
    ImageMetadata,
    ImageOptions,
    ImageSourceRef,
    ImageValidation,
)
from docflow.image.primitives import normalize, variants
from docflow.image.primitives.analyze import analyze_image
from docflow.image.primitives.atomic import (
    METADATA_ARTIFACT_KIND,
    METADATA_FILE_NAME,
    PUBLISHED_FILE_NAMES,
    TEMP_DIRECTORY_NAME,
    TEMP_SUFFIX,
    abandon,
    build_metadata_payload,
    discard_staged,
    publish_json,
    publish_metadata,
    publish_text,
    require_metadata_keys,
    staging_directory,
    temp_path,
)
from docflow.image.primitives.classify import classify_image
from docflow.image.primitives.engine import EngineChoice
from docflow.image.primitives.failures import ImagePrimitiveError
from docflow.image.primitives.load import load_image
from docflow.image.primitives.publishing import (
    TRANSFORMATION_CONTEXT_KEY,
    publish_artifact,
)
from docflow.image.primitives.validation import validate_image_result

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "image"
COLOR_LAYOUT = FIXTURES / "color_layout.png"

ENGINE = EngineChoice.OPENCV


def options(**overrides: bool) -> ImageOptions:
    """Return a request with normalization on and the variants off."""
    settings = {
        "normalize": True,
        "prepare_for_ocr": False,
        "prepare_for_vlm": False,
        "correct_orientation": True,
        "deskew": True,
    }
    settings.update(overrides)
    return ImageOptions(**settings)


def metadata_payload(tmp_path: Path) -> dict[str, object]:
    """Build a realistic metadata payload from the fixture."""
    image = load_image(COLOR_LAYOUT, ENGINE)
    metrics = analyze_image(image, COLOR_LAYOUT, ENGINE)
    validation = validate_image_result(None, None, None, options())
    record = ImageMetadata(
        processor="image",
        processor_version="0.0.0",
        engine="opencv",
        engine_version="5.0.0",
        libraries={"numpy": "2.3.5", "opencv": "5.0.0"},
        options=options(),
        input_metrics=metrics,
        output_metrics=metrics,
        timing={"load": 0.01, "analyze": 0.02},
        context=ImageContext(
            document_id="doc-1", page_number=1, workflow_run_id="run-1"
        ),
    )
    source = ImageSourceRef(
        path=COLOR_LAYOUT,
        width=image.shape[1],
        height=image.shape[0],
        format="PNG",
        size=COLOR_LAYOUT.stat().st_size,
    )
    artifact = ArtifactRef(
        path=tmp_path / "image" / "normalized.png",
        kind="normalized",
        width=image.shape[1],
        height=image.shape[0],
        format="PNG",
        size=1234,
    )
    return build_metadata_payload(
        record,
        source,
        classify_image(metrics),
        ["deskew_image"],
        validation,
        [artifact],
    )


def test_temp_path_stages_under_the_dot_tmp_directory_keeping_the_name() -> None:
    """The staging path keeps the final name and changes only its parent.

    Keeping the name is what lets the writer infer its encoder from the extension; a
    ``normalized.png.tmp`` sibling would be refused as an unsupported format before a byte was
    written.
    """
    staged = temp_path(Path("/x/image/normalized.png"))

    assert staged == Path("/x/image") / TEMP_DIRECTORY_NAME / "normalized.png"
    assert staged.name == "normalized.png"
    assert staged.parent.name == TEMP_DIRECTORY_NAME


def test_publish_text_leaves_only_the_final_file(tmp_path: Path) -> None:
    """The rename is the whole point: staging never survives a successful write."""
    target = tmp_path / "image" / "note.txt"

    publish_text(target, "hello")

    assert target.read_text(encoding="utf-8") == "hello"
    assert sorted(entry.name for entry in target.parent.iterdir()) == ["note.txt"]


def test_publish_json_writes_parseable_json_without_staging(tmp_path: Path) -> None:
    """A metadata file has to be readable by another tool, not only by this one."""
    target = tmp_path / "image" / METADATA_FILE_NAME

    publish_json(target, {"k": 1, "nested": {"a": [1, 2]}})

    assert json.loads(target.read_text(encoding="utf-8")) == {
        "k": 1,
        "nested": {"a": [1, 2]},
    }
    assert sorted(entry.name for entry in target.parent.iterdir()) == [
        METADATA_FILE_NAME
    ]


def test_a_published_image_is_the_final_name_and_nothing_else(tmp_path: Path) -> None:
    """``publish_artifact`` stages and renames too, so a successful write leaves no residue."""
    output_dir = tmp_path / "image"
    image = load_image(COLOR_LAYOUT, ENGINE)

    reference = publish_artifact(
        image,
        output_dir,
        PUBLISHED_FILE_NAMES[0],
        "normalized",
        ("deskew_image",),
        ENGINE,
    )

    assert sorted(entry.name for entry in output_dir.iterdir()) == [
        PUBLISHED_FILE_NAMES[0]
    ]
    assert reference.size == reference.path.stat().st_size


def test_a_failed_run_leaves_no_tmp_files_and_no_final_named_artifacts(
    tmp_path: Path,
) -> None:
    """The first WBS acceptance criterion, against the mess a real failure leaves."""
    output_dir = tmp_path / "image"
    (output_dir / TEMP_DIRECTORY_NAME).mkdir(parents=True)
    (output_dir / TEMP_DIRECTORY_NAME / "partial.png").write_bytes(b"half written")
    (output_dir / f"normalized.png{TEMP_SUFFIX}").write_bytes(b"staged")
    (output_dir / "normalized.png").write_bytes(b"published before the failure")
    (output_dir / METADATA_FILE_NAME).write_text("{}", encoding="utf-8")

    abandon(output_dir)

    assert not list(output_dir.glob(f"*{TEMP_SUFFIX}")), "a staged sibling survived"
    assert not (output_dir / TEMP_DIRECTORY_NAME).exists(), (
        "the staging directory survived"
    )
    assert not (output_dir / "normalized.png").exists(), (
        "a final-named artifact survived"
    )
    assert not (output_dir / METADATA_FILE_NAME).exists(), "the metadata file survived"


def test_discard_staged_leaves_the_published_artifacts_alone(tmp_path: Path) -> None:
    """The narrower cleanup, for a caller that wants to keep what was already published."""
    output_dir = tmp_path / "image"
    output_dir.mkdir(parents=True)
    (output_dir / f"normalized.png{TEMP_SUFFIX}").write_bytes(b"staged")
    (output_dir / "normalized.png").write_bytes(b"published")

    discard_staged(output_dir)

    assert (output_dir / "normalized.png").is_file()
    assert not list(output_dir.glob(f"*{TEMP_SUFFIX}"))


def test_cleanup_never_removes_a_file_the_processor_did_not_write(
    tmp_path: Path,
) -> None:
    """A cleanup's reach is fixed by name, so a caller pointing at a shared directory is safe."""
    output_dir = tmp_path / "image"
    output_dir.mkdir(parents=True)
    (output_dir / "normalized.png").write_bytes(b"mine")
    (output_dir / "a-consumers-file.txt").write_text("not mine")

    abandon(output_dir)

    assert sorted(entry.name for entry in output_dir.iterdir()) == [
        "a-consumers-file.txt"
    ]


def test_cleanup_reports_what_it_removed(tmp_path: Path) -> None:
    """A caller can say what it cleaned up rather than claiming a silent tidy."""
    output_dir = tmp_path / "image"
    output_dir.mkdir(parents=True)
    staged = output_dir / f"ocr_ready.png{TEMP_SUFFIX}"
    staged.write_bytes(b"staged")

    removed = discard_staged(output_dir)

    assert staged in removed


def test_cleanup_of_a_directory_that_never_existed_is_a_no_op(tmp_path: Path) -> None:
    """A run that failed before writing anything has nothing to clean, and must not raise."""
    assert discard_staged(tmp_path / "never-created") == []
    assert abandon(tmp_path / "never-created") == []


def test_the_published_names_match_what_the_pipelines_declare() -> None:
    """The list is restated here because it is used to *delete*; a drift would widen its reach."""
    assert set(PUBLISHED_FILE_NAMES) == {
        normalize.NORMALIZED_FILE_NAME,
        variants.OCR_FILE_NAME,
        variants.VLM_FILE_NAME,
    }


def test_the_metadata_payload_carries_every_required_key(tmp_path: Path) -> None:
    """The key set is fixed by ``docflow.identities``, not by this processor."""
    payload = metadata_payload(tmp_path)

    absent = [key for key in ARTIFACT_METADATA_KEYS if key not in payload]
    assert absent == [], f"the payload is missing {absent}"


def test_the_metadata_records_the_versions_the_transformations_and_the_metrics(
    tmp_path: Path,
) -> None:
    """The second WBS acceptance criterion, key by key."""
    payload = metadata_payload(tmp_path)

    assert payload["processor"] == "image"
    assert payload["processor_version"] == "0.0.0"
    assert payload["engine"] == "opencv"
    assert payload["engine_version"] == "5.0.0"
    assert payload["libraries"]["numpy"] == "2.3.5"
    assert payload["transformations"] == ["deskew_image"]
    assert "quality" in payload["input_metrics"]
    assert "quality" in payload["output_metrics"]
    assert payload["timing"]["analyze"] == 0.02


def test_the_metadata_records_the_processing_key_as_not_computed(
    tmp_path: Path,
) -> None:
    """``processing_key`` is the orchestrator's to compute, so it is present and ``None``.

    Present because a consumer has to be able to see it was not computed, which is not the same as
    it being absent - and a processor that hashed its own would be making a workflow decision.
    """
    payload = metadata_payload(tmp_path)

    assert "processing_key" in payload
    assert payload["processing_key"] is None


def test_the_metadata_expands_nested_records_field_by_field(tmp_path: Path) -> None:
    """The payload is a schema other tools read, so a new field is a visible edit here."""
    payload = metadata_payload(tmp_path)

    quality = payload["input_metrics"]["quality"]
    assert set(quality) == {"blur", "sharpness", "contrast", "brightness", "noise"}
    assert set(payload["options"]) == {
        "normalize",
        "prepare_for_ocr",
        "prepare_for_vlm",
        "correct_orientation",
        "deskew",
    }
    assert set(payload["input"]) == {
        "path",
        "width",
        "height",
        "format",
        "size",
        # Added by `IMG-12`: a failed run reports zeroes it never measured, and this flag is what
        # tells a consumer that they are absence rather than a size.
        "dimensions_measured",
    }
    assert set(payload["artifacts"][0]) == {
        "path",
        "kind",
        "width",
        "height",
        "format",
        "size",
    }


def test_a_payload_missing_a_required_key_is_refused(tmp_path: Path) -> None:
    """The guard is reachable and refuses, naming what is absent.

    Provoked directly, because nothing that calls the builder can produce an incomplete payload -
    which is the point: the guard is there for a caller that assembles or amends one.
    """
    payload = metadata_payload(tmp_path)
    assert set(payload) >= set(ARTIFACT_METADATA_KEYS)

    del payload["processing_key"]

    with pytest.raises(ValueError, match="processing_key"):
        require_metadata_keys(payload)


def test_the_metadata_round_trips_through_the_file(tmp_path: Path) -> None:
    """Written atomically, parsed back, equal to what was handed in."""
    output_dir = tmp_path / "image"
    payload = metadata_payload(tmp_path)

    reference = publish_metadata(payload, output_dir, ENGINE)

    assert reference.path.name == METADATA_FILE_NAME
    assert reference.kind == METADATA_ARTIFACT_KIND
    assert reference.format == "JSON"
    assert not list(output_dir.glob(f"*{TEMP_SUFFIX}"))
    assert json.loads(reference.path.read_text(encoding="utf-8")) == json.loads(
        json.dumps(payload, default=str)
    )


def test_no_metadata_value_is_a_placeholder(tmp_path: Path) -> None:
    """A required key may not be blank, and the two nullable values say so explicitly.

    ``processing_key`` is ``None`` because it is not computed, and ``resolution`` is ``None``
    because
    the fixture declares none - both are the contract's "not determined", which a test has to state
    rather than leave to a reader's assumption.
    """
    payload = metadata_payload(tmp_path)

    for key in ARTIFACT_METADATA_KEYS:
        if key == "processing_key":
            continue
        value = payload[key]
        assert value not in ("", None), f"{key} is a placeholder"
    assert payload["input_metrics"]["resolution"] is None
    assert payload["input_metrics"]["dimensions"]["width"] > 0


def test_the_metadata_json_is_human_readable(tmp_path: Path) -> None:
    """Indented and newline-terminated, because a human reads it during an incident."""
    target = tmp_path / METADATA_FILE_NAME

    publish_json(target, {"a": 1})

    text = target.read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert "\n  " in text


def test_the_metadata_reference_is_not_an_image_artifact(tmp_path: Path) -> None:
    """Its kind is outside the contract's ``ImageArtifactKind``, deliberately.

    ``ImageResult.artifacts`` is the images a consumer can read; the file describing them is not one
    of them, and giving it an image kind would invite a consumer to try to decode it.
    """
    reference = publish_metadata(metadata_payload(tmp_path), tmp_path / "image", ENGINE)

    assert reference.kind not in {"normalized", "ocr_ready", "vlm_ready", "region"}


def test_a_rerun_replaces_the_previous_artifact_atomically(tmp_path: Path) -> None:
    """Two runs over the same bytes land in the same directory, which the rename allows."""
    output_dir = tmp_path / "image"
    image = load_image(COLOR_LAYOUT, ENGINE)

    first = publish_artifact(
        image, output_dir, "normalized.png", "normalized", (), ENGINE
    )
    second = publish_artifact(
        image, output_dir, "normalized.png", "normalized", (), ENGINE
    )

    assert first.size == second.size
    assert sorted(entry.name for entry in output_dir.iterdir()) == ["normalized.png"]


def test_a_successful_write_does_not_raise_on_an_occupied_destination(
    tmp_path: Path,
) -> None:
    """A rerun over the same directory is normal, so an existing artifact is replaced and not an
    error.

    The staged-then-renamed write is what makes this work: ``Path.replace`` succeeds where a plain
    write to an existing path would need a separate delete, and the destination is never briefly
    absent - a reader either sees the old file or the new one.
    """
    output_dir = tmp_path / "image"
    output_dir.mkdir(parents=True)
    image = load_image(COLOR_LAYOUT, ENGINE)
    occupied = output_dir / "normalized.png"
    occupied.write_bytes(b"a previous run's artifact")

    reference = publish_artifact(
        image, output_dir, "normalized.png", "normalized", (), ENGINE
    )

    assert reference.path.read_bytes() != b"a previous run's artifact"
    assert sorted(entry.name for entry in output_dir.iterdir()) == ["normalized.png"]


def test_a_failed_image_write_leaves_no_staging_and_no_final_artifact(
    tmp_path: Path,
) -> None:
    """A real encoding failure, not a simulated one, and the whole namespace afterwards.

    The destination ends in an extension no encoder claims, so ``save_image`` refuses it and raises
    before writing a byte - the earliest failure this publisher can meet. The rename never runs, so
    the final name must be absent and the staging directory must not be left holding the wreckage.
    """
    output_dir = tmp_path / "image"

    with pytest.raises(ImagePrimitiveError) as raised:
        publish_artifact(
            load_image(COLOR_LAYOUT, ENGINE),
            output_dir,
            "normalized.jpgx",
            "normalized",
            ("deskew_image", "convert_to_grayscale"),
            ENGINE,
        )

    assert raised.value.detail[TRANSFORMATION_CONTEXT_KEY] == [
        "deskew_image",
        "convert_to_grayscale",
    ]
    assert sorted(entry.name for entry in output_dir.iterdir()) == []


def test_cleaning_up_after_a_failed_run_removes_a_leaked_staged_file(
    tmp_path: Path,
) -> None:
    """The first WBS acceptance criterion, end to end: force a failure, then inspect the namespace.

    The failure above is provoked for real, and the staged file it could have leaked is planted by
    hand because the publisher already removes its own on the way out - the criterion is about what
    a caller finds when the process dies between the write and the rename, which no in-process test
    can provoke. What is asserted is the guarantee: ``abandon`` leaves neither form behind.
    """
    output_dir = tmp_path / "image"

    with pytest.raises(ImagePrimitiveError):
        publish_artifact(
            load_image(COLOR_LAYOUT, ENGINE),
            output_dir,
            "normalized.jpgx",
            "normalized",
            (),
            ENGINE,
        )
    leaked = staging_directory(output_dir) / "normalized.png"
    leaked.write_bytes(b"written, then the process died")

    removed = abandon(output_dir)

    assert leaked in removed
    assert not (output_dir / TEMP_DIRECTORY_NAME).exists()
    assert not (output_dir / "normalized.png").exists()
    assert not list(output_dir.glob(f"*{TEMP_SUFFIX}"))
    assert sorted(entry.name for entry in output_dir.iterdir()) == []


def test_a_validation_record_reaches_the_metadata_errors_list(tmp_path: Path) -> None:
    """A failure recorded by the validator appears in the file, not only in the result object."""
    image = load_image(COLOR_LAYOUT, ENGINE)
    metrics = analyze_image(image, COLOR_LAYOUT, ENGINE)
    validation = validate_image_result(None, None, None, options())
    assert validation.errors, "normalization was requested and nothing published"

    payload = metadata_payload(tmp_path)
    assert payload["missing_artifacts"] == ["normalized"]
    assert payload["errors"][0]["type"] == "WRITE_ERROR"

    record = ImageMetadata(
        processor="image",
        processor_version="0.0.0",
        engine="opencv",
        engine_version="5.0.0",
        libraries={},
        options=options(),
        input_metrics=metrics,
        output_metrics=metrics,
        timing={},
        context=ImageContext(document_id="d", page_number=1, workflow_run_id="r"),
    )
    empty = ImageValidation(status="VALID", errors=[], missing_artifacts=[])
    payload = build_metadata_payload(
        record,
        ImageSourceRef(path=COLOR_LAYOUT, width=10, height=10, format="PNG", size=1),
        "VISUAL_IMAGE",
        [],
        empty,
        [],
    )
    assert payload["errors"] == []
    assert payload["missing_artifacts"] == []
    assert payload["status"] == "VALID"
