"""Tests for atomic publication (``IMG-11``).

The rule is one sentence — write to ``.tmp``, validate, rename — and the cases below hold it to
its two consequences: a reader never sees a half-written artifact, and a failed attempt leaves
no trace of itself.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from docflow.image import ImageError
from docflow.image.primitives import ImagePrimitiveError, publish_artifact, publish_json


def test_a_publication_writes_a_temporary_sibling_then_renames_it(
    tmp_path: Path,
) -> None:
    """The final name only ever exists complete."""
    destination = tmp_path / "image" / "normalized.png"
    seen: list[str] = []

    def write(temporary: Path) -> None:
        """Record what the callback was handed, then produce it."""
        seen.append(temporary.name)
        temporary.write_bytes(b"complete artifact")

    published = publish_artifact(destination, write)

    assert published == destination
    assert seen == ["normalized.png.tmp"]
    assert destination.read_bytes() == b"complete artifact"
    assert not list(tmp_path.rglob("*.tmp"))


def test_a_failing_publication_leaves_neither_the_artifact_nor_its_temporary(
    tmp_path: Path,
) -> None:
    """An interrupted write is not a small artifact: it is no artifact."""
    destination = tmp_path / "image" / "normalized.png"

    def write(temporary: Path) -> None:
        """Leave a partial file behind, the way an interrupted encoder would."""
        temporary.write_bytes(b"half")
        raise ImagePrimitiveError(
            ImageError(
                type="WRITE_ERROR", message="scripted", recoverable=False, metadata={}
            )
        )

    with pytest.raises(ImagePrimitiveError):
        publish_artifact(destination, write)

    assert not destination.exists()
    assert not list(tmp_path.rglob("*.tmp"))


def test_an_empty_artifact_is_never_published(tmp_path: Path) -> None:
    """A zero-byte image is a failure, not a small one."""
    destination = tmp_path / "image" / "normalized.png"

    with pytest.raises(ImagePrimitiveError) as failure:
        publish_artifact(destination, lambda temporary: temporary.write_bytes(b""))

    assert failure.value.error.type == "IO_ERROR"
    assert not destination.exists()


def test_a_write_that_produced_nothing_is_an_io_error(tmp_path: Path) -> None:
    """A callback that silently does nothing cannot be mistaken for a publication."""
    destination = tmp_path / "image" / "normalized.png"

    with pytest.raises(ImagePrimitiveError) as failure:
        publish_artifact(destination, lambda _: None)

    assert failure.value.error.type == "IO_ERROR"
    assert str(destination) in failure.value.error.metadata["destination"]


def test_json_payloads_do_not_depend_on_the_order_they_were_built_in(
    tmp_path: Path,
) -> None:
    """Two spellings of one record produce one artifact."""
    first = tmp_path / "a" / "metadata.json"
    second = tmp_path / "b" / "metadata.json"

    publish_json(first, {"b": 1, "a": {"d": 2, "c": 3}})
    publish_json(second, {"a": {"c": 3, "d": 2}, "b": 1})

    assert first.read_bytes() == second.read_bytes()
    assert json.loads(first.read_text(encoding="utf-8")) == {
        "a": {"c": 3, "d": 2},
        "b": 1,
    }
