"""Tests for the atomic publication of the OCR artifacts (``OCR-10``)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from docflow.ocr.primitives import (
    OCRPrimitiveError,
    ensure_directory,
    write_json_atomic,
    write_text_atomic,
)


def test_a_text_artifact_holds_exactly_what_was_handed_to_it(tmp_path: Path) -> None:
    """What the result reports and what the file holds are the same string, byte for byte."""
    published = write_text_atomic(tmp_path / "ocr" / "text.txt", "line one\nline two")

    assert published.read_text(encoding="utf-8") == "line one\nline two"
    assert not list(tmp_path.rglob("*.tmp"))


def test_a_json_artifact_is_written_with_sorted_keys(tmp_path: Path) -> None:
    """The bytes depend on the content, not on the order the caller built the mapping in."""
    first = write_json_atomic(tmp_path / "one.json", {"b": 1, "a": 2})
    second = write_json_atomic(tmp_path / "two.json", {"a": 2, "b": 1})

    assert first.read_bytes() == second.read_bytes()
    assert first.read_text(encoding="utf-8").endswith("}\n")
    assert json.loads(first.read_text(encoding="utf-8")) == {"a": 2, "b": 1}


def test_an_empty_text_artifact_is_published_rather_than_refused(
    tmp_path: Path,
) -> None:
    """An image with no text legitimately writes an empty ``text.txt``.

    The emptiness is stated by the metrics and the ``EMPTY`` status; refusing to publish it would
    turn a reported measurement into a lost artifact.
    """
    published = write_text_atomic(tmp_path / "ocr" / "text.txt", "")

    assert published.is_file()
    assert published.stat().st_size == 0


def test_a_refused_rename_leaves_neither_a_tmp_file_nor_a_final_artifact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The atomic step is the rename: if it does not happen, nothing final is visible."""

    def refuse(*_arguments: object, **_keywords: object) -> None:
        """Refuse the rename, the way a full or read-only filesystem does."""
        raise OSError("scripted rename failure")

    monkeypatch.setattr("docflow.ocr.primitives.publication.os.replace", refuse)

    with pytest.raises(OCRPrimitiveError) as failure:
        write_text_atomic(tmp_path / "ocr" / "text.txt", "content")

    assert failure.value.error.type == "IO_ERROR"
    assert failure.value.error.recoverable is True
    assert not list(tmp_path.rglob("*.tmp"))
    assert not list(tmp_path.rglob("*.txt"))


def test_a_payload_that_is_not_representable_is_an_export_error(tmp_path: Path) -> None:
    """A value JSON cannot hold is a representation we could not produce, not a crash."""

    # pylint: disable=too-few-public-methods
    # Reason: the object exists to be unrepresentable, and it does nothing else.
    class NotJson:
        """A value that cannot be represented as JSON."""

    with pytest.raises(OCRPrimitiveError) as failure:
        write_json_atomic(tmp_path / "ocr" / "document.json", {"value": NotJson()})

    assert failure.value.error.type == "EXPORT_ERROR"
    assert not list(tmp_path.rglob("*.tmp"))


def test_ensure_directory_creates_every_parent_it_needs(tmp_path: Path) -> None:
    """A publication never has to know whether its destination existed."""
    created = ensure_directory(tmp_path / "document" / "ocr" / "tables")

    assert created.is_dir()
    assert ensure_directory(created) == created
