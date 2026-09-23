"""Tests for atomic publication and the provenance record (``OCR-10``).

The two acceptance criteria are the spine of this module:

* given a failure forced after conversion, inspecting ``ocr/`` finds **no ``.tmp`` files and no
  final-named artifacts**;
* given a successful run, ``metadata.json`` records the engine ``"docling"``, a non-empty
  ``engine_version`` and the timing fields.

Both are about the filesystem, so both run against ``tmp_path``. The failure is forced by a real
write that cannot succeed rather than by a simulated one — a fabricated failure would test the test.

The remaining tests cover the guarantees the criteria rest on: that a published artifact is complete
or absent, that a successful run prunes its staging directory (an empty ``.tmp/`` is otherwise
indistinguishable from the residue of a failed run), and that the metadata payload carries the seven
keys :mod:`docflow.identities` requires.
"""

from __future__ import annotations

import json
import typing
from pathlib import Path

import pytest

from docflow.identities import ARTIFACT_METADATA_KEYS
from docflow.ocr.contracts import OCRContext, OCRError, OCRValidation
from docflow.ocr.primitives import analyze, files, metadata, pipeline
from tests.ocr.primitives import engine_corpus
from tests.ocr.primitives.engine_corpus import extracted_document


def a_validation(status: str = "VALID") -> OCRValidation:
    """Return a verdict for a hand-built record.

    Args:
        status: The state to record.

    Returns:
        The verdict.
    """
    return OCRValidation(
        status=typing.cast("typing.Any", status), errors=[], missing_artifacts=[]
    )


def a_record(**overrides: object) -> object:
    """Return a provenance record built through the real builder.

    Args:
        **overrides: Fields to replace, e.g. ``engine="other"``.

    Returns:
        The record.
    """
    document = extracted_document()
    arguments: dict[str, object] = {
        "engine": "docling",
        "engine_version": "2.126.0",
        "processor_version": metadata.get_processor_version(),
        "options": pipeline.normalize_docling_options(
            engine_corpus.requested_options()
        ),
        "image_path": engine_corpus.FIXTURE,
        "metrics": analyze.analyze_ocr_result(document),
        "validation": a_validation(),
        "timing": {"convert": 5.0, "extract": 0.3},
        "transformations": ["convert_to_grayscale"],
        "context": OCRContext(
            document_id="doc-1", page_number=1, workflow_run_id="run-1"
        ),
    }
    arguments.update(overrides)
    return metadata.build_ocr_metadata(**arguments)  # type: ignore[arg-type]


# ======================================================================================
# Criterion 1 - a failed run leaves nothing behind
# ======================================================================================


def test_a_forced_write_failure_leaves_no_tmp_and_no_artifact(tmp_path: Path) -> None:
    """The criterion, forced by a real failure rather than a simulated one.

    ``write_text_atomic`` is asked to publish into a path that cannot exist — its parent is a *file*
    — so the write fails inside the real mechanism. What matters is what the namespace looks like
    afterwards: the failure is contained, and nothing a later stage could mistake for a result is
    left behind.
    """
    namespace = files.create_ocr_directory(tmp_path / "ocr")
    blocked = namespace / "blocked.txt"
    blocked.write_text("a file where a directory would have to be", encoding="utf-8")

    with pytest.raises(OSError):
        files.write_text_atomic(blocked / "sub" / "artifact.txt", "content")

    assert blocked.is_file()
    staged = files.staging_directory(namespace)
    assert not list(staged.iterdir()), "a staged file survived a failed write"


def testabandon_removes_both_staged_and_published_artifacts(tmp_path: Path) -> None:
    """A failed run must leave nothing a reader could mistake for a result.

    An artifact under its final name is visible whether or not the run that wrote it went on to
    succeed, so both forms are removed.
    """
    namespace = files.create_ocr_directory(tmp_path / "ocr")
    paths = files.build_ocr_output_paths(namespace)
    files.write_text_atomic(paths.text, "text")
    files.write_text_atomic(paths.metadata, "{}")
    files.write_text_atomic(files.temp_path(paths.markdown), "staged")

    removed = files.abandon(namespace)

    assert removed
    assert not paths.text.exists()
    assert not paths.metadata.exists()
    assert not (namespace / files.TEMP_DIRECTORY_NAME).exists()
    assert sorted(entry.name for entry in namespace.iterdir()) == []


def test_a_successful_run_prunes_itsstaging_directory(tmp_path: Path) -> None:
    """Otherwise success and failure look identical to a reader inspecting the namespace.

    The rename empties ``.tmp/`` but leaves the directory, and the criterion is phrased as finding
    nothing staged — an empty directory is exactly the residue of a run that died.
    """
    paths = files.build_ocr_output_paths(tmp_path / "ocr")

    files.write_text_atomic(paths.text, "text")

    assert paths.text.is_file()
    assert not (paths.text.parent / files.TEMP_DIRECTORY_NAME).exists()


def test_thestaging_directory_survives_while_files_are_still_staged(
    tmp_path: Path,
) -> None:
    """It is pruned by the *last* rename, not by every one.

    A run publishing five artifacts stages them one at a time; a prune that removed the directory
    when the first file left it would break the rest of the run.
    """
    namespace = files.create_ocr_directory(tmp_path / "ocr")
    staged = files.staging_directory(namespace)
    (staged / "one.txt").write_text("a", encoding="utf-8")
    (staged / "two.txt").write_text("b", encoding="utf-8")

    assert files.prune_staging_directory(staged) is False
    assert staged.is_dir()

    (staged / "one.txt").unlink()
    (staged / "two.txt").unlink()
    assert files.prune_staging_directory(staged) is True
    assert not staged.exists()


def test_a_staged_tmp_sibling_is_swept_too(tmp_path: Path) -> None:
    """A file staged by an interrupted older build carries the suffix, not the directory form.

    A cleanup that knew about only one of the two forms would leave the other for a reader to find.
    """
    namespace = files.create_ocr_directory(tmp_path / "ocr")
    sibling = namespace / f"text.txt{files.TEMP_SUFFIX}"
    sibling.write_text("staged by an older writer", encoding="utf-8")

    removed = files.discard_staged(namespace)

    assert sibling in removed
    assert not sibling.exists()


def testabandon_leaves_unrelated_files_alone(tmp_path: Path) -> None:
    """Its reach is fixed by name, never a sweep of the directory.

    A caller pointing at a directory that holds anything else must not lose it — the same property
    the image processor's cleanup is tested for.
    """
    namespace = files.create_ocr_directory(tmp_path / "ocr")
    stranger = namespace / "someone-elses-file.txt"
    stranger.write_text("not mine", encoding="utf-8")

    files.abandon(namespace)

    assert stranger.is_file()


def testabandon_removes_published_table_files(tmp_path: Path) -> None:
    """The tables live in a subdirectory, so a cleanup that only walked the namespace would miss
    them."""
    namespace = files.create_ocr_directory(tmp_path / "ocr")
    paths = files.build_ocr_output_paths(namespace)
    files.ensure_directory(paths.tables_dir)
    table = paths.tables_dir / "table_001.md"
    table.write_text("| a |\n| --- |\n", encoding="utf-8")

    files.abandon(namespace)

    assert not paths.tables_dir.exists()


def testabandon_on_an_absent_namespace_returns_nothing(tmp_path: Path) -> None:
    """Called before anything was created, it is a no-op rather than an error."""
    assert not files.abandon(tmp_path / "never-created")


# ======================================================================================
# Criterion 2 - metadata.json records the engine and the timing
# ======================================================================================


def test_metadata_records_the_engine_and_a_non_empty_version(tmp_path: Path) -> None:
    """The criterion, verbatim. ``engine`` is always ``"docling"`` and never a choice."""
    paths = files.build_ocr_output_paths(tmp_path / "ocr")
    payload = metadata.build_metadata_payload(
        a_record(), processing_key=None, tables_published=0
    )  # type: ignore[arg-type]

    files.write_json_atomic(paths.metadata, payload)
    read_back = files.read_json(paths.metadata)

    assert read_back["engine"] == "docling"
    assert read_back["engine_version"]
    assert read_back["engine_version"].strip()


def test_metadata_records_the_timing_fields(tmp_path: Path) -> None:
    """``metadata.json`` is the only artifact allowed to carry a clock reading."""
    paths = files.build_ocr_output_paths(tmp_path / "ocr")
    files.write_json_atomic(
        paths.metadata,
        metadata.build_metadata_payload(
            a_record(), processing_key=None, tables_published=0
        ),
    )  # type: ignore[arg-type]

    read_back = files.read_json(paths.metadata)

    assert read_back["timing"] == {"convert": 5.0, "extract": 0.3}


def test_metadata_carries_every_required_key(tmp_path: Path) -> None:
    """The seven keys :mod:`docflow.identities` fixes for every processor's metadata."""
    paths = files.build_ocr_output_paths(tmp_path / "ocr")
    files.write_json_atomic(
        paths.metadata,
        metadata.build_metadata_payload(
            a_record(), processing_key=None, tables_published=0
        ),
    )  # type: ignore[arg-type]

    read_back = files.read_json(paths.metadata)

    for key in ARTIFACT_METADATA_KEYS:
        assert key in read_back, f"the payload lost {key}"


def test_the_engine_name_is_read_from_the_record_it_is_given() -> None:
    """Not hardcoded, even though the engine is fixed.

    The value *is* always ``"docling"`` — Docling is the only engine and is never a selectable
    option — so a literal would produce the same payload for every record this processor builds, and
    the record's own field would become decoration. A record built with a different name is the only
    input that separates the two, and it is what a future engine seam would produce.
    """
    payload = metadata.build_metadata_payload(
        a_record(engine="some-other-engine"),  # type: ignore[arg-type]
        processing_key=None,
        tables_published=0,
    )

    assert payload["engine"] == "some-other-engine"


def test_the_engine_version_is_read_from_the_record_it_is_given() -> None:
    """The version is what makes two runs comparable, so a blank one would defeat the record."""
    payload = metadata.build_metadata_payload(
        a_record(engine_version="9.9.9-test"),  # type: ignore[arg-type]
        processing_key=None,
        tables_published=0,
    )

    assert payload["engine_version"] == "9.9.9-test"


def test_the_processing_key_is_none_until_the_orchestrator_supplies_one() -> None:
    """Not this processor's to compute, so it records the absence explicitly.

    A self-computed hash would be a second, disagreeing implementation of a value the reuse rule
    depends on being identical everywhere — ``ORC-02`` owns the formula.
    """
    payload = metadata.build_metadata_payload(
        a_record(), processing_key=None, tables_published=0
    )  # type: ignore[arg-type]

    assert "processing_key" in payload
    assert payload["processing_key"] is None

    supplied = metadata.build_metadata_payload(
        a_record(),  # type: ignore[arg-type]
        processing_key="k",
        tables_published=0,
    )

    assert supplied["processing_key"] == "k"


def test_metadata_records_the_verdict_as_it_stood_at_publish_time() -> None:
    """A reader of the artifact asks what the run concluded, not what the files would be judged to
    be
    now."""
    payload = metadata.build_metadata_payload(
        a_record(validation=a_validation("LOW_CONTENT")),  # type: ignore[arg-type]
        processing_key=None,
        tables_published=0,
    )

    assert payload["validation"]["status"] == "LOW_CONTENT"


def test_metadata_renders_typed_failures_rather_than_stringifying_them() -> None:
    """A verdict's errors are data a caller may act on, so their fields survive."""
    error = OCRError(
        type="IO_ERROR",
        message="a promised artifact is missing",
        recoverable=False,
        metadata={"artifact": "/x/ocr/text.txt"},
    )
    verdict = OCRValidation(
        status="INCOMPLETE", errors=[error], missing_artifacts=[Path("/x/y")]
    )

    payload = metadata.build_metadata_payload(
        a_record(validation=verdict), processing_key=None, tables_published=0
    )  # type: ignore[arg-type]

    assert payload["validation"]["errors"] == [
        {
            "type": "IO_ERROR",
            "message": "a promised artifact is missing",
            "recoverable": False,
            "metadata": {"artifact": "/x/ocr/text.txt"},
        }
    ]
    assert payload["validation"]["missing_artifacts"] == ["/x/y"]


def test_the_payload_records_the_metrics_it_was_given() -> None:
    """The metrics travel into the artifact rather than being recomputed at publish time."""
    document = extracted_document()
    payload = metadata.build_metadata_payload(
        a_record(), processing_key=None, tables_published=0
    )  # type: ignore[arg-type]
    expected = analyze.analyze_ocr_result(document)

    assert payload["metrics"]["characters"] == expected.characters
    assert payload["metrics"]["blocks"] == expected.blocks
    assert payload["metrics"]["structure_detected"] is expected.structure_detected


def test_the_payload_records_the_options_and_transformations() -> None:
    """Provenance is what makes a rerun comparable, so both travel."""
    payload = metadata.build_metadata_payload(
        a_record(), processing_key=None, tables_published=0
    )  # type: ignore[arg-type]

    assert payload["options"]["ocr"] is True
    assert payload["options"]["language"] == "es"
    assert payload["transformations"] == ["convert_to_grayscale"]


def test_the_payload_records_the_input_and_the_page() -> None:
    """Which image, and which page of it."""
    payload = metadata.build_metadata_payload(
        a_record(), processing_key=None, tables_published=0
    )  # type: ignore[arg-type]

    assert payload["input"] == str(engine_corpus.FIXTURE)
    assert payload["page_number"] == 1


# ======================================================================================
# The payload guard
# ======================================================================================


def test_a_payload_missing_a_required_key_is_refused() -> None:
    """Extracted from the builder so it can be falsified at all.

    Inline in ``build_metadata_payload`` the check is unreachable — the literal there carries every
    key by construction — so no test could kill a mutation disabling it. As its own function it is
    true for any caller that assembles or amends a payload.
    """
    payload = metadata.build_metadata_payload(
        a_record(), processing_key=None, tables_published=0
    )  # type: ignore[arg-type]
    del payload["processing_key"]

    with pytest.raises(ValueError, match="processing_key"):
        metadata.require_metadata_keys(payload)


def test_the_guard_names_every_missing_key() -> None:
    """One at a time would make a caller fix problems in sequence."""
    with pytest.raises(ValueError) as raised:
        metadata.require_metadata_keys({})

    message = str(raised.value)
    for key in ARTIFACT_METADATA_KEYS:
        assert key in message


def test_a_complete_payload_passes_the_guard() -> None:
    """The guard must not refuse the object the builder produces."""
    metadata.require_metadata_keys(
        metadata.build_metadata_payload(
            a_record(), processing_key=None, tables_published=0
        )
    )  # type: ignore[arg-type]


# ======================================================================================
# The engine-metadata merge
# ======================================================================================


def test_engine_metadata_is_nested_rather_than_spread() -> None:
    """The engine's keys move between versions; this processor's schema must not move with them."""
    base = metadata.build_metadata_payload(
        a_record(), processing_key=None, tables_published=0
    )  # type: ignore[arg-type]

    merged = metadata.merge_ocr_metadata(
        base, {"schema_name": "DoclingDocument", "page_count": 1}
    )

    assert merged["engine_metadata"] == {
        "schema_name": "DoclingDocument",
        "page_count": 1,
    }
    assert "schema_name" not in merged
    assert base.get("engine_metadata") is None, "the merge mutated its input"


def test_the_merge_keeps_every_required_key() -> None:
    """A merged payload is still a payload."""
    merged = metadata.merge_ocr_metadata(
        metadata.build_metadata_payload(
            a_record(), processing_key=None, tables_published=0
        ),
        {"extra": 1},  # type: ignore[arg-type]
    )

    metadata.require_metadata_keys(merged)


def test_the_merged_engine_metadata_does_not_alias_the_callers_dict() -> None:
    """The payload must not change under a caller that keeps using its own dict."""
    base = metadata.build_metadata_payload(
        a_record(), processing_key=None, tables_published=0
    )  # type: ignore[arg-type]
    engine_facts = {"page_count": 1}

    merged = metadata.merge_ocr_metadata(base, engine_facts)
    engine_facts["page_count"] = 99

    assert merged["engine_metadata"]["page_count"] == 1


# ======================================================================================
# The namespace and the writers
# ======================================================================================


def test_the_namespace_layout_is_declared_in_one_place(tmp_path: Path) -> None:
    """Every path comes from one function, so a change to the layout is one edit."""
    paths = files.build_ocr_output_paths(tmp_path / "ocr")

    assert paths.text.name == files.TEXT_FILE_NAME
    assert paths.markdown.name == files.MARKDOWN_FILE_NAME
    assert paths.structured_document.name == files.STRUCTURED_FILE_NAME
    assert paths.metadata.name == files.METADATA_FILE_NAME
    assert paths.tables_dir.name == files.TABLES_DIRECTORY_NAME


def test_building_paths_creates_nothing(tmp_path: Path) -> None:
    """Naming the paths a run will write and deciding to write them are different decisions."""
    namespace = tmp_path / "ocr"

    files.build_ocr_output_paths(namespace)

    assert not namespace.exists()


def test_the_published_names_match_the_constants() -> None:
    """``PUBLISHED_FILE_NAMES`` is restated because it is used to *delete*.

    An edit to a constant somewhere else must not silently widen a cleanup's reach, so the tuple is
    written out — and this test is what keeps the two definitions from drifting.
    """
    assert set(files.PUBLISHED_FILE_NAMES) == {
        files.TEXT_FILE_NAME,
        files.MARKDOWN_FILE_NAME,
        files.STRUCTURED_FILE_NAME,
        files.METADATA_FILE_NAME,
    }


def test_the_staging_path_keeps_the_artifacts_own_name(tmp_path: Path) -> None:
    """Only the parent changes, and that is what makes the staged file writeable at all.

    Every artifact here carries its own extension, so a writer that chose an encoder — or any reader
    that keyed off the suffix — would break on a staged name. The directory is what marks a file as
    not-an-artifact; the name stays.
    """
    final = tmp_path / "ocr" / files.TEXT_FILE_NAME

    staged = files.temp_path(final)

    assert staged.name == final.name
    assert staged.parent != final.parent
    assert staged.parent.name == files.TEMP_DIRECTORY_NAME
    assert staged.suffix == ".txt", f"the extension was lost: {staged.name}"


def test_writing_json_sorts_its_keys(tmp_path: Path) -> None:
    """Two runs over one page must produce byte-identical files."""
    first = tmp_path / "one.json"
    second = tmp_path / "two.json"

    files.write_json_atomic(first, {"b": 1, "a": 2})
    files.write_json_atomic(second, {"a": 2, "b": 1})

    assert first.read_text(encoding="utf-8") == second.read_text(encoding="utf-8")
    assert first.read_text(encoding="utf-8").startswith("{")
    assert json.loads(first.read_text(encoding="utf-8")) == {"a": 2, "b": 1}


def test_writing_is_byte_identical_across_two_runs(tmp_path: Path) -> None:
    """The determinism posture, on the writer rather than on the exporter."""
    payload = metadata.build_metadata_payload(
        a_record(), processing_key=None, tables_published=0
    )  # type: ignore[arg-type]
    first = tmp_path / "a" / "metadata.json"
    second = tmp_path / "b" / "metadata.json"

    files.write_json_atomic(first, payload)
    files.write_json_atomic(second, payload)

    assert first.read_bytes() == second.read_bytes()


def test_a_rewrite_replaces_rather_than_appends(tmp_path: Path) -> None:
    """A rerun over the same page lands in the same directory and must not concatenate."""
    path = tmp_path / "ocr" / "text.txt"

    files.write_text_atomic(path, "first and longer")
    files.write_text_atomic(path, "second")

    assert path.read_text(encoding="utf-8") == "second"


def test_reading_back_what_was_written_round_trips(tmp_path: Path) -> None:
    """Nesting and non-ASCII survive the writer and the reader together."""
    path = tmp_path / "ocr" / "document.json"
    payload = {"nested": {"a": [1, 2]}, "unicode": "café"}

    files.write_json_atomic(path, payload)

    assert files.read_json(path) == payload


def test_reading_a_non_json_file_raises(tmp_path: Path) -> None:
    """The reader is not a parser of last resort: a caller that wants a default asks for one."""
    path = tmp_path / "not-json.json"
    path.write_text("this is not JSON", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        files.read_json(path)
