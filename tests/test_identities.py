"""Tests for the three identities (``GEN-04``).

The names are frozen by ``docs/plan/subplan-orquestador.md`` §3.4. The hashing itself
belongs to ``ORC-02``, so nothing here computes a key: these tests guard the vocabulary
that both the key and the artifact metadata are built from.
"""

from __future__ import annotations

from docflow.identities import (
    ARTIFACT_METADATA_KEYS,
    IDENTITY_FIELDS,
    PAGE_ARTIFACT_METADATA_KEYS,
    PROCESSING_KEY_FORMULA,
)


def test_the_three_identities_are_exactly_the_documented_names() -> None:
    """Reuse, resume and idempotency rest on these three names and no others."""
    assert IDENTITY_FIELDS == ("document_id", "workflow_run_id", "processing_key")


def test_the_processing_key_formula_names_its_four_inputs() -> None:
    """The formula's components are auditable, so a silent redefinition is visible."""
    for component in (
        "processor",
        "processor_version",
        "input_hashes",
        "normalized_options",
    ):
        assert component in PROCESSING_KEY_FORMULA


def test_the_run_identity_is_absent_from_the_processing_key() -> None:
    """A new run over unchanged inputs must reproduce the same key, or reuse never fires."""
    assert "workflow_run_id" not in PROCESSING_KEY_FORMULA


def test_every_artifact_metadata_key_set_carries_the_identities() -> None:
    """An artifact that cannot name its run and its unit of work cannot be reused."""
    for identity in IDENTITY_FIELDS:
        assert identity in ARTIFACT_METADATA_KEYS


def test_every_artifact_metadata_key_set_carries_the_engine_identity() -> None:
    """A re-run is comparable to a previous one only when both name their engine."""
    for key in ("processor", "processor_version", "engine", "engine_version"):
        assert key in ARTIFACT_METADATA_KEYS


def test_page_artifacts_additionally_carry_their_page_number() -> None:
    """A per-page artifact is meaningless without the page it describes."""
    assert "page_number" in PAGE_ARTIFACT_METADATA_KEYS
