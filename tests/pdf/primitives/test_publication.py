"""Tests for the atomic publication (``PDF-12``)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from docflow.pdf.primitives import (
    PDFPrimitiveError,
    publish_file,
    publish_json,
    publish_text,
)
from docflow.pdf.primitives.publication import TEMP_SUFFIX


def test_a_publication_writes_a_temporary_sibling_then_renames_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No final-named artifact is written before the whole write succeeded."""
    destination = tmp_path / "native_text" / "text.txt"
    renames: list[tuple[Path, Path]] = []
    real_replace = os.replace

    def recording_replace(source: str | Path, target: str | Path) -> None:
        """Record the rename, proving the artifact travelled through a ``.tmp`` name."""
        renames.append((Path(source), Path(target)))
        real_replace(source, target)

    monkeypatch.setattr(
        "docflow.pdf.primitives.publication.os.replace", recording_replace
    )

    published = publish_text(destination, "extracted text")

    assert published == destination
    assert destination.read_text(encoding="utf-8") == "extracted text"
    assert renames == [(Path(str(destination) + TEMP_SUFFIX), destination)]
    assert not list(tmp_path.rglob(f"*{TEMP_SUFFIX}"))


def test_a_failing_publication_leaves_neither_the_artifact_nor_its_temporary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An interrupted publish leaves no final-named artifact and no leftover ``.tmp``."""
    destination = tmp_path / "metadata.json"

    def refuse(source: str | Path, target: str | Path) -> None:
        """Fail where the rename would make the artifact visible."""
        raise RuntimeError("interrupted")

    monkeypatch.setattr("docflow.pdf.primitives.publication.os.replace", refuse)

    with pytest.raises(RuntimeError, match="interrupted"):
        publish_json(destination, {"page_count": 1})

    assert not destination.exists()
    assert not list(tmp_path.rglob(f"*{TEMP_SUFFIX}"))


def test_an_empty_engine_artifact_is_never_published(tmp_path: Path) -> None:
    """An empty render or extraction is a failure, not a zero-byte artifact."""
    source = tmp_path / "produced.png"
    source.write_bytes(b"")

    with pytest.raises(PDFPrimitiveError) as failure:
        publish_file(source, tmp_path / "render" / "page.png")

    assert failure.value.error.type == "IO_ERROR"
    assert not (tmp_path / "render").exists()


def test_an_engine_artifact_that_was_never_produced_is_an_io_error(
    tmp_path: Path,
) -> None:
    """A missing engine output is reported, never published as empty."""
    with pytest.raises(PDFPrimitiveError) as failure:
        publish_file(tmp_path / "absent.pdf", tmp_path / "source" / "page.pdf")

    assert failure.value.error.type == "IO_ERROR"


def test_an_empty_text_is_a_publishable_artifact(tmp_path: Path) -> None:
    """A page with no text layer publishes an empty text rather than a missing one."""
    destination = publish_text(tmp_path / "native_text" / "text.txt", "")

    assert destination.is_file()
    assert destination.read_bytes() == b""


def test_json_payloads_do_not_depend_on_the_order_they_were_built_in(
    tmp_path: Path,
) -> None:
    """Determinism: two spellings of one payload are one artifact."""
    first = publish_json(tmp_path / "one.json", {"b": 2, "a": 1})
    second = publish_json(tmp_path / "two.json", {"a": 1, "b": 2})

    assert first.read_bytes() == second.read_bytes()
