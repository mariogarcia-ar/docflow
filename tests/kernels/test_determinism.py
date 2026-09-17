"""Determinism classes - the tests that would notice a regenerated sample.

`E05-03` / `S1-T08`. The invariant is **a sampled artifact is never regenerated**, and
`plan-01-kernels.md` §7b row 5 says its test must FAIL when the invariant breaks - the
breaking shape being *"the stage re-runs and reports ``done`` with a fresh sample,
changing the result while reporting success"*.

Five groups:

1. **Exactly three classes**, and the mapping is `kernel-cli.md` §7's.
2. **A deterministic artifact is recomputable** - the one class where an absence is
   recoverable, because the result is a function of the key.
3. **A sampled artifact is never regenerated**: its absence is `evidence_missing`, and
   the test would notice a fresh sample reported as done.
4. **The class is read, not guessed** - an unknown kernel is refused, because both
   available defaults change results.
5. **A present artifact is never a failure**, whatever the class. The class only changes
   what an *absence* means.
"""

from __future__ import annotations

import ast
import pathlib
from collections.abc import Mapping
from types import MappingProxyType

import pytest

from docflow.kernels import determinism, resolution, store
from docflow.kernels.types import Artifact

# --- Constants ---------------------------------------------------------------

DETERMINISM_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "src"
    / "docflow"
    / "kernels"
    / "determinism.py"
)

DETERMINISM_TREE: ast.Module = ast.parse(DETERMINISM_PATH.read_text(encoding="utf-8"))

#: The class mapping `kernel-cli.md` §7 states, restated here on purpose: a contract
#: test must hold its own copy rather than import the table it verifies.
EXPECTED_CLASSES: Mapping[str, str] = MappingProxyType(
    {
        "orchestrator": "deterministic",
        "pdf": "deterministic",
        "image": "deterministic",
        "ocr": "sampled",
        "llm.local": "sampled",
        "llm.frontier": "external",
        "store": "deterministic",
        "registry": "deterministic",
    }
)

SOME_SHA256: str = "9f2a" * 16


def _a_stage(
    state: str = "done",
    *,
    artifact_sha256: str | None = SOME_SHA256,
    reason_code: str | None = None,
    cache_key: str | None = "c41b" * 16,
    attempts: int = 1,
) -> store.StageRecord:
    """Build a stage record for the decision tests.

    Args:
        state: The recorded state.
        artifact_sha256: The artifact claim, or None.
        reason_code: The reason code, or None.
        cache_key: The key the stage ran under, or None.
        attempts: The attempt count.

    Returns:
        The record.

    """
    return store.StageRecord(
        state=state,
        artifact_sha256=artifact_sha256,
        reason_code=reason_code,
        cache_key=cache_key,
        attempts=attempts,
    )


# --- 1. Exactly three classes, and the mapping is the artifact's -------------


def test_exactly_three_classes_exist() -> None:
    """`sad.md` §4 declares three; a fourth would be a class nothing consumes."""
    assert determinism.CLASS_NAMES == ("deterministic", "sampled", "external")
    assert len(determinism.CLASS_NAMES) == 3


def test_the_declared_mapping_is_the_artifact_mapping() -> None:
    """Every kernel the artifacts name has the class they name.

    `kernel-cli.md` §7: K1/K2/K3/K7/K8 deterministic, K4/K5 sampled, K6 external.
    K4's class is `02-arch-components.md`'s *"model-dependent"* mapped to `sampled` by
    `sad.md` §4, which is the artifact that decides it for resume purposes.
    """
    assert dict(determinism.declared_classes()) == dict(EXPECTED_CLASSES)


def test_every_declared_class_is_one_of_the_three() -> None:
    """A class outside the set is a kernel whose resume behaviour is undefined."""
    assert set(determinism.declared_classes().values()) <= set(determinism.CLASS_NAMES)


def test_every_class_is_used_by_at_least_one_kernel() -> None:
    """A declared class no kernel reports is a class nothing consumes.

    The reverse check of the one above: a class in the set but not in the table would
    be dead vocabulary, and the escalation ladder in Plan 2 would reference a term with
    no producer.
    """
    used = set(determinism.declared_classes().values())

    assert used == set(determinism.CLASS_NAMES)


def test_the_mapping_covers_every_kernel_in_the_inventory() -> None:
    """Eight kernels, eight entries: a kernel absent from the table cannot resume."""
    assert len(determinism.declared_classes()) == 8
    assert {"orchestrator", "pdf", "image", "ocr"} <= set(
        determinism.declared_classes()
    )


# --- 2. A deterministic artifact is recomputable -----------------------------


def test_a_missing_deterministic_artifact_may_be_recomputed() -> None:
    """The one class where an absence is recoverable: the key determines the bytes."""
    decision = determinism.consequence_for(
        "deterministic", present=False, stage="acquire"
    )

    assert decision is not None
    assert decision.recompute is True
    assert decision.failed is False
    assert decision.reason is None


def test_a_present_artifact_is_never_a_failure() -> None:
    """The class only changes what an *absence* means.

    For all three classes a present artifact answers *nothing to do* - a class that
    failed on a present artifact would fail every run.
    """
    for determinism_class in determinism.CLASS_NAMES:
        assert (
            determinism.consequence_for(determinism_class, present=True, stage="any")
            is None
        ), determinism_class


# --- 3. A sampled artifact is evidence, never a cache ------------------------


@pytest.mark.parametrize("determinism_class", ["sampled", "external"])
def test_a_missing_sampled_or_external_artifact_fails_with_evidence_missing(
    determinism_class: str,
) -> None:
    """Its absence is a `failed` stage with a typed reason - **never** a re-sample.

    An external artifact's record of a moment is gone for the same reason: a later call
    is a new observation, not a correction of the old one.
    """
    decision = determinism.consequence_for(
        determinism_class, present=False, stage="transform"
    )

    assert decision is not None
    assert decision.recompute is False, "regeneration must not be available"
    assert decision.failed is True
    assert decision.reason is not None
    assert decision.reason.code == "evidence_missing"
    assert "transform" in decision.reason.message, "the reason names the stage"


def test_the_reason_code_is_in_the_closed_set() -> None:
    """`kernel-cli.md` §5: a code outside the vocabulary is untestable.

    Exit `2` follows from the code being an expected negative rather than a
    precondition failure, so the code is the assertion target and never the message.
    """
    closed = {
        "illegible",
        "insufficient_effective_resolution",
        "blank_page",
        "truncated_output",
        "model_not_pulled",
        "model_unknown",
        "provider_unknown",
        "engine_unavailable",
        "provider_unavailable",
        "asset_invalid",
        "asset_missing",
        "artifact_missing",
        "evidence_missing",
        "encrypted",
        "unsupported_format",
        "role_conflict",
    }

    assert determinism.REASON_EVIDENCE_MISSING in closed

    # And the code a decision actually produces is that one, not merely *a* code in
    # the set: asserting the constant alone passes for any valid code, so a change to
    # another in-set value would go unnoticed.
    decision = determinism.consequence_for("sampled", present=False, stage="s")
    assert decision is not None and decision.reason is not None
    assert decision.reason.code == "evidence_missing", (
        "the consequence must report evidence_missing specifically: a different valid "
        "code is a different fact, and the assertion targets the fact"
    )


def test_the_module_offers_no_way_to_regenerate_a_sampled_artifact() -> None:
    """*No code path re-samples to fill a gap* - asserted over the source.

    A behavioural test cannot prove an absence: it can only show that the paths it
    takes do not regenerate. The strongest available statement is that the module
    exposes no function that produces an artifact at all - it *decides*, and the
    decision for a sampled artifact is `failed`.
    """
    produced = {
        node.name
        for node in ast.walk(DETERMINISM_TREE)
        if isinstance(node, ast.FunctionDef)
        and node.returns is not None
        and "Artifact" in ast.unparse(node.returns)
    }

    assert produced == set(), (
        f"determinism decides consequences; it must produce no artifact: {produced}"
    )
    assert not hasattr(determinism, "regenerate")
    assert not hasattr(determinism, "resample")


def test_the_decision_never_returns_a_value_for_a_missing_sampled_artifact() -> None:
    """The decision's shape leaves no room for *a fresh sample reported as done*.

    `MissingEvidence.recompute` is the only action it can express besides failing, and
    it is False for both non-deterministic classes. There is no third option that could
    carry a value.
    """
    decision = determinism.consequence_for("sampled", present=False, stage="s")

    assert decision is not None
    assert not hasattr(decision, "artifact")
    assert not hasattr(decision, "value")
    assert decision.failed is True


def test_a_sampled_decision_is_not_the_same_decision_as_a_deterministic_one() -> None:
    """The two classes must be distinguishable, or the consequence is not per-class.

    A test that asserted only *"an absent artifact produces a decision"* would pass
    against an implementation that regenerated everything, which is the failure the
    issue exists to prevent.
    """
    sampled = determinism.consequence_for("sampled", present=False, stage="s")
    deterministic = determinism.consequence_for(
        "deterministic", present=False, stage="s"
    )

    assert sampled != deterministic
    assert sampled is not None and deterministic is not None
    assert sampled.recompute is not deterministic.recompute


# --- 4. The class is read, not guessed ---------------------------------------


def test_an_unknown_kernel_is_refused() -> None:
    """Both available defaults change results, so neither is taken.

    `deterministic` would make the system regenerate a sampled artifact, and `sampled`
    would make it discard recomputable work. Refusing is the only answer that reports
    the real problem.
    """
    with pytest.raises(ValueError) as excinfo:
        determinism.class_of("invented")

    assert "No determinism class is declared" in str(excinfo.value)
    assert "invented" in str(excinfo.value)


def test_an_unknown_class_is_refused_by_the_consequence() -> None:
    """An unrecognised class would otherwise take a branch no rule chose."""
    with pytest.raises(ValueError) as excinfo:
        determinism.consequence_for("sometimes", present=False, stage="s")

    assert "is not a determinism class" in str(excinfo.value)


def test_the_class_is_read_from_the_producing_kernel() -> None:
    """A named kernel's class is what the decision is taken under."""
    assert determinism.class_of("llm.local") == "sampled"
    assert determinism.class_of("pdf") == "deterministic"
    assert determinism.class_of("llm.frontier") == "external"


def test_the_kernels_resolution_declares_are_all_classified() -> None:
    """The families resolution can resolve must have a class, or resume is undefined.

    A cross-module check: `resolution.py` declares which kernels a capability belongs
    to, and every one of them has to appear in this table. A capability that resolved
    and then had no resume behaviour would fail at the worst moment - the one after a
    crash.
    """
    families = resolution.declared_capabilities()
    kernels = {capability.kernel for capability in families.values()}

    assert kernels, "resolution declares no kernel, so this check is vacuous"
    assert kernels <= set(determinism.declared_classes())


# --- 5. The three steps, composed --------------------------------------------


def test_a_done_stage_whose_artifact_is_present_needs_no_decision(
    tmp_path: pathlib.Path,
) -> None:
    """The composed path: a recorded `done` over bytes that are still there."""
    root = tmp_path / "store"
    artifact = store.put(root, b"the bytes", media_type="text/plain")

    decision = determinism.resume_decision(
        _a_stage(artifact_sha256=artifact.sha256),
        kernel="pdf",
        store_root=root,
        stage="acquire",
    )

    assert decision is None, "nothing to do: the bytes the claim names are there"


def test_a_done_stage_whose_deterministic_artifact_is_deleted_may_recompute(
    tmp_path: pathlib.Path,
) -> None:
    """The composed path for a cache: the bytes are gone, and may be produced again."""
    root = tmp_path / "store"
    artifact = store.put(root, b"the bytes", media_type="text/plain")
    _delete(root, artifact.sha256)

    decision = determinism.resume_decision(
        _a_stage(artifact_sha256=artifact.sha256),
        kernel="pdf",
        store_root=root,
        stage="acquire",
    )

    assert decision is not None
    assert decision.recompute is True


def test_a_done_stage_whose_sampled_artifact_is_deleted_fails(
    tmp_path: pathlib.Path,
) -> None:
    """The composed path for evidence: `failed` with `evidence_missing`, never a sample.

    This is `plan-01-kernels.md` §3's evidence-table row and the acceptance scenario
    *"A sampled artifact is evidence, not a cache"* - the wrong result being *"a fresh
    sample silently substituted"*.
    """
    root = tmp_path / "store"
    artifact = store.put(root, b"a model's answer", media_type="application/json")
    _delete(root, artifact.sha256)

    decision = determinism.resume_decision(
        _a_stage(artifact_sha256=artifact.sha256),
        kernel="llm.local",
        store_root=root,
        stage="transform",
    )

    assert decision is not None
    assert decision.failed is True
    assert decision.reason is not None
    assert decision.reason.code == "evidence_missing"


def test_a_truncated_artifact_is_as_absent_as_a_deleted_one(
    tmp_path: pathlib.Path,
) -> None:
    """A file whose bytes do not hash to its name is not the artifact a claim names.

    K7's `verify` answers *present* this way already, and reusing it is what keeps one
    definition of *the bytes are there* rather than two that could disagree.
    """
    root = tmp_path / "store"
    artifact = store.put(root, b"a model's answer", media_type="application/json")
    path = root / "artifacts" / artifact.sha256
    path.write_bytes(b"truncated")

    decision = determinism.resume_decision(
        _a_stage(artifact_sha256=artifact.sha256),
        kernel="llm.local",
        store_root=root,
        stage="transform",
    )

    assert decision is not None
    assert decision.failed is True


@pytest.mark.parametrize(
    "state", ["pending", "running", "failed", "blocked", "stale", "skipped"]
)
def test_a_stage_that_is_not_done_has_no_artifact_claim_to_check(
    state: str, tmp_path: pathlib.Path
) -> None:
    """Only `done` claims bytes, so only `done` can have lost them.

    A `running` stage has no artifact and a `failed` one has a reason by construction;
    asking whether their artifact is present would report *missing evidence* about a
    stage that never claimed any.

    Args:
        state: The non-`done` state under test.
        tmp_path: The pytest fixture.

    """
    record = _a_stage(
        state=state,
        artifact_sha256=None,
        reason_code="blank_page" if state == "failed" else None,
        cache_key=None
        if state in {"pending", "blocked", "stale", "skipped"}
        else "c" * 64,
        attempts=1 if state in {"running", "failed"} else 0,
    )

    assert (
        determinism.resume_decision(
            record, kernel="llm.local", store_root=tmp_path / "store", stage="s"
        )
        is None
    )


def test_the_composed_path_refuses_an_unknown_kernel(tmp_path: pathlib.Path) -> None:
    """The composition cannot skip the class read: it is the first step."""
    with pytest.raises(ValueError) as excinfo:
        determinism.resume_decision(
            _a_stage(),
            kernel="invented",
            store_root=tmp_path / "store",
            stage="s",
        )

    assert "No determinism class is declared" in str(excinfo.value)


# --- Static guards: the layer's own rules ------------------------------------


def test_the_module_imports_nothing_above_the_kernel_layer() -> None:
    """No adapter, no port, no third party: this is a kernel-layer decision."""
    imported: list[str] = []
    for node in ast.walk(DETERMINISM_TREE):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.append(node.module)

    forbidden = (
        "docflow.adapters",
        "docflow.components",
        "docflow.ports",
        "docflow.kernel_cli",
    )

    assert [name for name in imported if name.startswith(forbidden)] == []
    assert all(
        name.split(".")[0] not in {"yaml", "docling", "ollama", "httpx"}
        for name in imported
    )


def test_no_public_identifier_names_a_domain_concept() -> None:
    """`kernel-cli.md` §10's forbidden vocabulary appears in no public name."""
    forbidden = (
        "invoice",
        "verdict",
        "document_type",
        "pipeline",
        "validator",
        "extractor",
        "segmenter",
        "identif",
        "catalog",
        "reviewer",
        "material",
        "ErVR",
        "EpVR",
        "ErpVR",
    )
    identifiers = {
        node.id
        for node in ast.walk(DETERMINISM_TREE)
        if isinstance(node, ast.Name) and not node.id.startswith("_")
    }
    identifiers |= {
        alias.name
        for node in ast.walk(DETERMINISM_TREE)
        if isinstance(node, ast.alias)
        for alias in [node]
    }

    offenders = [
        name
        for name in identifiers
        for word in forbidden
        if word.lower() in name.lower()
    ]

    assert offenders == [], (
        f"domain vocabulary leaked into the kernel layer: {offenders}"
    )


def test_the_module_is_the_deliverable_path_the_issue_names() -> None:
    """The deliverable path is `docflow/kernels/determinism.py`."""
    assert DETERMINISM_PATH.name == "determinism.py"
    assert DETERMINISM_PATH.parent.name == "kernels"


def _delete(root: pathlib.Path, sha256: str) -> None:
    """Delete a stored artifact by hand, as an operator would.

    Args:
        root: The store root.
        sha256: The artifact's digest.

    """
    (root / "artifacts" / sha256).unlink()


def test_an_artifact_written_by_the_store_is_the_one_the_decision_finds(
    tmp_path: pathlib.Path,
) -> None:
    """The composed path and K7 agree on what *present* means, by construction.

    `artifact_is_present` delegates to K7's `verify`, so there is one definition rather
    than two that could drift. This pins the delegation rather than assuming it.
    """
    root = tmp_path / "store"
    artifact: Artifact = store.put(root, b"bytes", media_type="text/plain")

    assert determinism.artifact_is_present(root, artifact.sha256) is True
    assert determinism.artifact_is_present(root, "0" * 64) is False


def test_the_class_table_is_immutable() -> None:
    """The table is a declaration, not configuration: a mutation must be deliberate."""
    assert isinstance(determinism.declared_classes(), MappingProxyType) or isinstance(
        determinism.KERNEL_CLASSES, MappingProxyType
    )

    with pytest.raises(TypeError):
        determinism.KERNEL_CLASSES["pdf"] = "sampled"  # type: ignore[index]
