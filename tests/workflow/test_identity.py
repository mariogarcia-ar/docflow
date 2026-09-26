"""Identity primitives (``ORC-02``)."""

from __future__ import annotations

from pathlib import Path

from docflow.workflow.identity import (
    build_workflow_run_id,
    canonical_json,
    input_hash,
    options_hash,
    processing_key,
)


def test_the_processing_key_is_deterministic() -> None:
    """The same four inputs always produce the same key."""
    first = processing_key("pdf", "0.0.0", ["abc"], {"dpi": 200})
    second = processing_key("pdf", "0.0.0", ["abc"], {"dpi": 200})

    assert first == second
    assert first


def test_the_processing_key_ignores_option_order() -> None:
    """Two spellings of one configuration produce one key."""
    first = processing_key("pdf", "0.0.0", ["abc"], {"dpi": 200, "render": True})
    second = processing_key("pdf", "0.0.0", ["abc"], {"render": True, "dpi": 200})

    assert first == second


def test_a_changed_option_changes_both_hashes() -> None:
    """An option change must miss the cache, and both digests must say so."""
    before = {"dpi": 200}
    after = {"dpi": 300}

    assert options_hash(before) != options_hash(after)
    assert processing_key("pdf", "0.0.0", ["abc"], before) != processing_key(
        "pdf", "0.0.0", ["abc"], after
    )


def test_a_changed_processor_version_changes_the_key() -> None:
    """An upgraded processor never reuses what the previous version produced."""
    assert processing_key("pdf", "0.0.0", ["abc"], {}) != processing_key(
        "pdf", "0.0.1", ["abc"], {}
    )


def test_an_input_is_hashed_by_content(tmp_path: Path) -> None:
    """Rewriting a file in place changes its hash; the path alone does not."""
    artifact = tmp_path / "page.png"
    artifact.write_bytes(b"first")
    first = input_hash(artifact)
    artifact.write_bytes(b"second")
    second = input_hash(artifact)

    assert first != second
    assert input_hash(tmp_path / "absent.png") == input_hash(tmp_path / "absent.png")


def test_the_canonical_form_is_key_order_stable() -> None:
    """Serialization depends on content, not on insertion order."""
    assert canonical_json({"b": 1, "a": 2}) == canonical_json({"a": 2, "b": 1})


def test_a_run_identity_is_minted_and_unique() -> None:
    """Two runs never claim the same identity."""
    first = build_workflow_run_id()

    assert first
    assert first != build_workflow_run_id()
