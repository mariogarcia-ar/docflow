"""Tests for atomic publication (``LLM-11``).

Two properties, and both are about what a reader can observe: a finished artifact is complete, and
a publication that failed leaves nothing behind — neither a final-named file nor a ``.tmp``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from docflow.llm.primitives import LLMPrimitiveError
from docflow.llm.primitives.publication import (
    TEMP_SUFFIX,
    ensure_directory,
    write_json_atomic,
    write_text_atomic,
)


def test_a_published_text_artifact_reads_back_verbatim(tmp_path: Path) -> None:
    """The bytes on disk are the bytes that were handed in."""
    destination = tmp_path / "run" / "note.txt"

    write_text_atomic(destination, "one line\n")

    assert destination.read_text(encoding="utf-8") == "one line\n"
    assert not list(tmp_path.rglob(f"*{TEMP_SUFFIX}"))


def test_a_published_json_artifact_is_key_sorted_and_reproducible(
    tmp_path: Path,
) -> None:
    """Two runs over the same content produce the same bytes, whatever order built it."""
    first = tmp_path / "a.json"
    second = tmp_path / "b.json"

    write_json_atomic(first, {"b": 1, "a": 2})
    write_json_atomic(second, {"a": 2, "b": 1})

    assert first.read_bytes() == second.read_bytes()
    assert first.read_text(encoding="utf-8").startswith('{\n  "a": 2')


def test_a_publication_that_fails_leaves_neither_a_tmp_file_nor_an_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Invariant: an interrupted publication leaves no trace of its attempt."""
    destination = tmp_path / "run" / "state.json"

    def refuse(*_args: object, **_kwargs: object) -> str:
        raise OSError("the filesystem refused the write")

    monkeypatch.setattr(Path, "write_text", refuse)

    with pytest.raises(LLMPrimitiveError) as raised:
        write_json_atomic(destination, {"a": 1})

    assert raised.value.error.type == "INTERNAL_ERROR"
    assert not destination.exists()
    assert not list(tmp_path.rglob(f"*{TEMP_SUFFIX}"))


def test_a_payload_that_cannot_be_serialized_is_reported_rather_than_written(
    tmp_path: Path,
) -> None:
    """A value JSON cannot represent is a representation we could not produce."""
    destination = tmp_path / "state.json"

    with pytest.raises(LLMPrimitiveError) as raised:
        write_json_atomic(destination, {"a": object()})

    assert raised.value.error.type == "INTERNAL_ERROR"
    assert not destination.exists()


def test_a_directory_that_cannot_be_created_is_reported(tmp_path: Path) -> None:
    """A run with nowhere to publish has failed; it does not fall back to another place."""
    blocker = tmp_path / "file"
    blocker.write_text("not a directory", encoding="utf-8")

    with pytest.raises(LLMPrimitiveError) as raised:
        ensure_directory(blocker / "sub")

    assert raised.value.error.recoverable is False
