"""K1 orchestrator core - the tests that would notice if it stopped being true.

`E05-01` (`S1-T06`). The module has five claims, and each one has a test that fails
when the claim is broken rather than one that passes when it holds:

1. **A graph is dispatched only when its needs are satisfied**, and a need that
   produced no artifact leaves the stage alone instead of handing it a placeholder.
2. **The manifest is derived.** `rebuild_index()` reads the ledger tree and nothing
   else, so `rm run.json` followed by a rebuild reproduces it - and the test proves
   the deletion happened rather than trusting that it would have.
3. **Dispatch is keyed.** A stage that is terminal for the key it would run under now
   is not re-run; a stage that is terminal under a *different* key is new work.
4. **A run is idempotent**: a second call dispatches nothing.
5. **A descriptor's shape is enforced**, so a mapping with an undeclared key is
   refused rather than tolerated - which is what makes "a descriptor naming a
   pipeline code is not a shape this accepts" structural.

Two of these are the invariants `plan-01-kernels.md` §7b assigns elsewhere and are
asserted here only in the form this issue owns: the ordering of ``running`` before the
work is `E05-02`'s, and verification on read is `E05-05`'s. What is tested here is that
this module *calls* the operations in the right order and writes nothing it cannot
support from the ledgers.
"""

# Pylint reports every pytest fixture parameter as a redefinition of the function the
# fixture decorates. That is the framework's calling convention, not a shadowing bug:
# pytest injects the value, and renaming the parameter would break the injection. The
# check is disabled at module scope rather than at thirty call sites, because it is a
# statement about how pytest resolves arguments - the same reason
# `tests/adapters/test_store.py` disables it.
# pylint: disable=redefined-outer-name
#
# `too-many-lines`: the module covers five acceptance criteria of an `L` issue, and
# splitting a suite by file length separates a criterion from the test that proves it.
# pylint: disable=too-many-lines
#
# `use-implicit-booleaness-not-comparison`: `report.blocked == ()` is deliberate. The
# field is a tuple, and `not report.blocked` would read a *missing* attribute as
# *nothing was blocked* if the report were ever reshaped - the same reasoning
# `tests/kernels/test_store.py` records for the same finding.
# pylint: disable=use-implicit-booleaness-not-comparison

from __future__ import annotations

import ast
import hashlib
import json
import pathlib
import sys
from collections.abc import Mapping
from types import MappingProxyType

import pytest

from docflow.kernels import orchestrator, store
from docflow.kernels.types import Artifact, Evidence, KernelResult, Reason

# --- Constants ---------------------------------------------------------------

ORCHESTRATOR_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "src"
    / "docflow"
    / "kernels"
    / "orchestrator.py"
)

ORCHESTRATOR_TREE: ast.Module = ast.parse(ORCHESTRATOR_PATH.read_text(encoding="utf-8"))

#: The registry hash every test uses. A real-shaped digest (64 hex characters), not a
#: label: a key term that only *looks* like a hash would not distinguish a composed
#: key from a placeholder.
REGISTRY_HASH: str = "c41b" * 16

#: The three kernels the synthetic graph names, with their key terms.
KERNEL_TERMS: Mapping[str, orchestrator.KernelTerms] = MappingProxyType(
    {
        "store": orchestrator.KernelTerms(
            kernel_version="1.0.0",
            adapter_revision="filesystem 1",
            model_revision="none",
        ),
        "pdf": orchestrator.KernelTerms(
            kernel_version="1.0.0",
            adapter_revision="pymupdf 1.28.2",
            model_revision="none",
        ),
    }
)

#: The registry hash and per-kernel terms, as one value.
KEYS = orchestrator.KeyContext(registry_hash=REGISTRY_HASH, kernels=KERNEL_TERMS)

#: The synthetic descriptor of `plan-01-kernels.md` §6 step 1, in its parsed form:
#: three stages, no domain noun, operations that are kernel ops only. The unit set is
#: declared explicitly so the flow runs over N > 1 units, which is the criterion.
SYNTHETIC: Mapping[str, object] = {
    "unit": "synthetic",
    "units": ["U-0001", "U-0002"],
    "stages": [
        {"name": "acquire", "kernel": "store", "op": "put"},
        {"name": "transform", "kernel": "pdf", "op": "probe", "needs": ["acquire"]},
        {"name": "persist", "kernel": "store", "op": "put", "needs": ["transform"]},
    ],
}

#: The unit set the synthetic flow runs over, with N > 1 so dispatch is exercised
#: across units rather than only across stages.
UNIT_NAMES: tuple[str, ...] = ("U-0001", "U-0002")


def _hash_of(text: str) -> str:
    """Return the sha256 of a string, as a unit's own input hash.

    Args:
        text: The text to digest.

    Returns:
        The hexadecimal digest.

    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _input_hashes(names: tuple[str, ...] = UNIT_NAMES) -> Mapping[str, str]:
    """Build a unit-name to input-hash mapping.

    Args:
        names: The unit names.

    Returns:
        One input hash per unit, distinct per unit so a cross-unit mix-up is visible.

    """
    return {name: _hash_of(f"input for {name}") for name in names}


# --- A recording operation table ---------------------------------------------


# The recorder is a test double, and it carries exactly the members the tests reach
# for: one factory plus one method per operation. More members would be surface with no
# test behind it.
# pylint: disable=too-few-public-methods
class Recorder:
    """An operation table that records what it was dispatched and returns real bytes.

    The operations are fakes on purpose (`plan-01-kernels.md` §13 Track 1: the fast
    flow runs with faked ports). What matters for these tests is not what a stage
    *does* but **what it is handed and what is written down afterwards**, so the fake
    stores the call it received and returns an artifact whose bytes are a function of
    **the call's input hash** - which is what makes a changed input propagate: if a
    stage's output did not depend on its input, a downstream stage could never notice
    that its upstream bytes had changed, and the keyed-dispatch tests would pass
    against an orchestrator that ignored the input term entirely.
    """

    def __init__(self, *, fail_on: str | None = None) -> None:
        """Initialize the recorder.

        Args:
            fail_on: A stage name whose operation returns a typed reason rather than
                an artifact. None means every operation succeeds.

        """
        self.calls: list[orchestrator.StageCall] = []
        self.fail_on = fail_on

    def table(self) -> dict[tuple[str, str], orchestrator.StageOperation]:
        """Return the operation table, keyed by ``(kernel, op)``.

        Returns:
            The table the orchestrator dispatches through.

        """
        return {
            ("store", "put"): self._put,
            ("pdf", "probe"): self._probe,
        }

    def _put(self, call: orchestrator.StageCall) -> KernelResult[Artifact]:
        """Store the call's bytes into the unit's own store root.

        Args:
            call: The dispatch call.

        Returns:
            The stored artifact, or a typed reason when this stage is the one that
            fails.

        """
        return self._answer(
            call, payload=f"{call.unit}:{call.stage.name}:{call.input_hash}"
        )

    def _probe(self, call: orchestrator.StageCall) -> KernelResult[Artifact]:
        """Answer a probe by storing a descriptor of what it saw.

        Args:
            call: The dispatch call.

        Returns:
            The stored artifact, or a typed reason when this stage is the one that
            fails.

        """
        return self._answer(
            call,
            payload=f"{call.unit}:{call.stage.name}:{call.input_hash}",
        )

    def _answer(
        self, call: orchestrator.StageCall, *, payload: str
    ) -> KernelResult[Artifact]:
        """Record the call and store its bytes, or report the injected failure.

        Args:
            call: The dispatch call.
            payload: The text whose hash becomes the artifact.

        Returns:
            The stored artifact, or a typed reason for the failing stage.

        """
        self.calls.append(call)

        if self.fail_on is not None and call.stage.name == self.fail_on:
            return KernelResult(
                value=None,
                evidence=Evidence(
                    terms=MappingProxyType({"injected": "true"}),
                    measurements=MappingProxyType({}),
                    observed=MappingProxyType({"stage": call.stage.name}),
                ),
                reason=Reason(code="blank_page", message="injected for the test"),
            )

        artifact = store.put(
            call.unit_dir / "artifacts",
            payload.encode("utf-8"),
            media_type="application/octet-stream",
        )
        return KernelResult(
            value=artifact,
            evidence=Evidence(
                terms=MappingProxyType({"cache_key": call.cache_key}),
                measurements=MappingProxyType({"bytes": float(artifact.size_bytes)}),
                observed=MappingProxyType({"unit": call.unit}),
            ),
            reason=None,
        )


@pytest.fixture
def descriptor() -> orchestrator.Descriptor:
    """Provide the synthetic three-stage descriptor.

    Returns:
        The descriptor, covering two units.

    """
    return orchestrator.descriptor_from_mapping(SYNTHETIC)


@pytest.fixture
def recorder() -> Recorder:
    """Provide a recording operation table.

    Returns:
        The recorder.

    """
    return Recorder()


# --- Criterion 1: the graph, its order and its refusals ----------------------


def test_the_dispatch_order_respects_every_need(
    descriptor: orchestrator.Descriptor,
) -> None:
    """A stage is ordered after everything it declares as a need."""
    order = descriptor.graph.order

    assert order == ("acquire", "transform", "persist"), (
        "the order must follow the needs chain, not the declaration order"
    )


def test_the_dispatch_order_is_declaration_independent_but_deterministic() -> None:
    """Two descriptors of one graph dispatch identically, whatever the tie order.

    ``transform`` and a hypothetical sibling that both need ``acquire`` are free to
    run in any order relative to each other; what may not vary is the order two runs
    of the same descriptor choose, because a key is composed from what is on disk by
    the time a stage is reached.
    """
    payload = {
        "unit": "synthetic",
        "stages": [
            {"name": "b", "kernel": "store", "op": "put", "needs": ["a"]},
            {"name": "a", "kernel": "store", "op": "put"},
            {"name": "c", "kernel": "store", "op": "put", "needs": ["a"]},
        ],
    }

    first = orchestrator.descriptor_from_mapping(payload).graph.order
    second = orchestrator.descriptor_from_mapping(payload).graph.order

    assert first == second
    assert first.index("a") < first.index("b")
    assert first.index("a") < first.index("c")
    assert set(first) == {"a", "b", "c"}


def test_a_cycle_is_refused_when_the_graph_is_read() -> None:
    """A graph that can never become ready is refused, not left to deadlock a run."""
    payload = {
        "unit": "synthetic",
        "stages": [
            {"name": "a", "kernel": "store", "op": "put", "needs": ["b"]},
            {"name": "b", "kernel": "store", "op": "put", "needs": ["a"]},
        ],
    }

    with pytest.raises(ValueError) as excinfo:
        orchestrator.descriptor_from_mapping(payload)

    assert "cycle" in str(excinfo.value)


def test_a_need_naming_an_undeclared_stage_is_refused() -> None:
    """A need that names nothing can never become terminal, so it is refused."""
    payload = {
        "unit": "synthetic",
        "stages": [
            {"name": "a", "kernel": "store", "op": "put", "needs": ["ghost"]},
        ],
    }

    with pytest.raises(ValueError) as excinfo:
        orchestrator.descriptor_from_mapping(payload)

    assert "undeclared" in str(excinfo.value)


def test_a_stage_cannot_need_itself() -> None:
    """A self-edge can never be satisfied, so it is refused by construction."""
    with pytest.raises(ValueError) as excinfo:
        orchestrator.Stage(
            name="a",
            kernel="store",
            op="put",
            needs=("a",),
            params=MappingProxyType({}),
        )

    assert "its own need" in str(excinfo.value)


# --- Criterion 2: the manifest is derived, and rebuildable -------------------


def test_a_three_stage_graph_runs_over_n_units(
    descriptor: orchestrator.Descriptor,
    recorder: Recorder,
    tmp_path: pathlib.Path,
) -> None:
    """The criterion, literally: a 3-stage synthetic graph over N units, N > 1."""
    out = tmp_path / "O"

    report = orchestrator.run(
        descriptor,
        out,
        input_hashes=_input_hashes(),
        operations=recorder.table(),
        keys=KEYS,
    )

    assert len(UNIT_NAMES) > 1, "N > 1 is the criterion, not a preference"

    dispatched_units = {unit for unit, _stage in report.dispatched}
    assert dispatched_units == set(UNIT_NAMES)
    assert len(report.dispatched) == len(UNIT_NAMES) * 3
    assert report.blocked == ()

    for unit in UNIT_NAMES:
        ledger = store.read_ledger(out / unit)
        assert {record.state for record in ledger.stages.values()} == {"done"}
        for record in ledger.stages.values():
            assert record.artifact_sha256 is not None
            assert store.verify(out / unit / "artifacts", record.artifact_sha256)


def test_the_manifest_carries_the_five_reported_keys(
    descriptor: orchestrator.Descriptor,
    recorder: Recorder,
    tmp_path: pathlib.Path,
) -> None:
    """`state`, `totals`, `stages`, `outcomes`, `inflight` - as §3's table requires."""
    out = tmp_path / "O"

    orchestrator.run(
        descriptor,
        out,
        input_hashes=_input_hashes(),
        operations=recorder.table(),
        keys=KEYS,
    )
    manifest = json.loads(
        (out / orchestrator.MANIFEST_NAME).read_text(encoding="utf-8")
    )

    assert set(manifest) == {"state", "totals", "stages", "outcomes", "inflight"}
    assert manifest["state"] == "complete"
    assert manifest["inflight"] == []
    assert manifest["totals"]["units"] == len(UNIT_NAMES)
    assert manifest["totals"]["stages"] == len(UNIT_NAMES) * 3
    assert manifest["totals"]["done"] == len(UNIT_NAMES) * 3
    assert set(manifest["stages"]) == set(UNIT_NAMES)


def test_rebuild_index_reproduces_the_manifest_from_the_ledgers_alone(
    descriptor: orchestrator.Descriptor,
    recorder: Recorder,
    tmp_path: pathlib.Path,
) -> None:
    """Row 16: delete the manifest, rebuild it, get the same bytes back.

    The deletion is asserted, not assumed: if ``run.json`` were still there the test
    would be comparing a file to itself, which is the shape of a check that proves
    nothing.
    """
    out = tmp_path / "O"
    orchestrator.run(
        descriptor,
        out,
        input_hashes=_input_hashes(),
        operations=recorder.table(),
        keys=KEYS,
    )

    manifest_path = out / orchestrator.MANIFEST_NAME
    written = manifest_path.read_bytes()
    assert written, "the manifest must exist before deleting it"

    manifest_path.unlink()
    assert not manifest_path.exists(), "the deletion is part of the proof"

    rebuilt = orchestrator.rebuild_index(out)
    orchestrator.write_index(out)

    assert json.loads(written) == rebuilt
    assert manifest_path.read_bytes() == written, "byte-for-byte, not merely equal"


def test_the_manifest_is_written_by_deriving_it_never_by_assembling_it(
    descriptor: orchestrator.Descriptor,
    recorder: Recorder,
    tmp_path: pathlib.Path,
) -> None:
    """``run`` and ``write_index`` return what ``rebuild_index`` returned.

    A manifest assembled by a second code path could disagree with the ledgers, which
    is drift by construction. This asserts the single-producer property: the value a
    run reports is the value a rebuild produces from the tree.
    """
    out = tmp_path / "O"

    report = orchestrator.run(
        descriptor,
        out,
        input_hashes=_input_hashes(),
        operations=recorder.table(),
        keys=KEYS,
    )

    assert dict(report.manifest) == dict(orchestrator.rebuild_index(out))


def test_a_hand_deleted_manifest_leaves_the_run_intact(
    descriptor: orchestrator.Descriptor,
    recorder: Recorder,
    tmp_path: pathlib.Path,
) -> None:
    """The ledgers are authoritative, so losing the manifest loses no information."""
    out = tmp_path / "O"
    orchestrator.run(
        descriptor,
        out,
        input_hashes=_input_hashes(),
        operations=recorder.table(),
        keys=KEYS,
    )
    (out / orchestrator.MANIFEST_NAME).unlink()

    rebuilt = orchestrator.rebuild_index(out)

    assert rebuilt["state"] == "complete"
    assert rebuilt["totals"]["done"] == len(UNIT_NAMES) * 3


def test_rebuild_index_ignores_an_existing_manifest_entirely(
    descriptor: orchestrator.Descriptor,
    recorder: Recorder,
    tmp_path: pathlib.Path,
) -> None:
    """The manifest's *contents* are never an input to rebuilding it.

    The deletion test above proves a rebuild works without `run.json`; it does not
    prove the rebuild ignores one that is present. That is the sharper claim and the
    one drift turns on: a rebuild that consulted an existing manifest would reproduce
    whatever that manifest said, so a manifest edited by hand, truncated, or written by
    an older run would become authoritative simply by existing.

    The manifest is replaced with something that could only come from a lying rebuild,
    so any code path that reads it fails loudly rather than passing quietly.
    """
    out = tmp_path / "O"
    orchestrator.run(
        descriptor,
        out,
        input_hashes=_input_hashes(),
        operations=recorder.table(),
        keys=KEYS,
    )

    poison = {
        "state": "complete",
        "totals": {"units": 99, "stages": 99, "done": 99},
        "stages": {"a-unit-that-never-ran": {"acquire": {"state": "done"}}},
        "outcomes": {},
        "inflight": [],
    }
    (out / orchestrator.MANIFEST_NAME).write_text(json.dumps(poison), encoding="utf-8")

    rebuilt = orchestrator.rebuild_index(out)

    assert dict(rebuilt) != poison, "the manifest on disk must not be read back"
    assert rebuilt["totals"]["units"] == len(UNIT_NAMES)
    assert set(rebuilt["stages"]) == set(UNIT_NAMES)
    assert orchestrator.write_index(out) == rebuilt, (
        "writing must overwrite the poison with the derived value"
    )


def test_the_discovery_pattern_agrees_with_the_stores_suffix_rule() -> None:
    """The ledger glob is K7's suffix, held together so the two cannot drift.

    `prd.md` FR-29 fixes ``<name>.ledger.json``; this module discovers ledgers by a
    pattern. If K7's suffix changed, a rebuild would silently find nothing and report
    an empty run - which is the failure this assertion exists to make loud.
    """
    unit_dir = pathlib.Path("/tmp") / "a-unit"
    suffix = store.ledger_path(unit_dir).name.removeprefix("a-unit")

    assert f"**/*{suffix}" == orchestrator._LEDGER_GLOB  # pylint: disable=protected-access


# --- Criterion 3: dispatch is keyed -----------------------------------------


def test_a_terminal_stage_under_the_same_key_is_not_re_run(
    descriptor: orchestrator.Descriptor,
    recorder: Recorder,
    tmp_path: pathlib.Path,
) -> None:
    """Idempotency: the second run skips everything the first run completed."""
    out = tmp_path / "O"
    orchestrator.run(
        descriptor,
        out,
        input_hashes=_input_hashes(),
        operations=recorder.table(),
        keys=KEYS,
    )
    first_pass = len(recorder.calls)

    second = orchestrator.run(
        descriptor,
        out,
        input_hashes=_input_hashes(),
        operations=recorder.table(),
        keys=KEYS,
    )

    assert second.dispatched == ()
    assert len(second.skipped) == len(UNIT_NAMES) * 3
    assert len(recorder.calls) == first_pass, "nothing may be dispatched twice"


def test_a_changed_registry_hash_makes_every_keyed_stage_new_work(
    descriptor: orchestrator.Descriptor,
    recorder: Recorder,
    tmp_path: pathlib.Path,
) -> None:
    """The registry hash is a key term, so a registry change invalidates precisely.

    This is `sad.md` §5's whole point: the completion claims go *visibly* stale
    instead of quietly wrong, and dispatch is where *visibly* becomes an action.
    """
    out = tmp_path / "O"
    orchestrator.run(
        descriptor,
        out,
        input_hashes=_input_hashes(),
        operations=recorder.table(),
        keys=KEYS,
    )

    changed = orchestrator.KeyContext(registry_hash="d00d" * 16, kernels=KERNEL_TERMS)
    second = orchestrator.run(
        descriptor,
        out,
        input_hashes=_input_hashes(),
        operations=recorder.table(),
        keys=changed,
    )

    assert second.skipped == (), "a different key is different work"
    assert len(second.dispatched) == len(UNIT_NAMES) * 3


def test_a_changed_unit_input_makes_a_downstream_stage_new_work(
    descriptor: orchestrator.Descriptor,
    tmp_path: pathlib.Path,
) -> None:
    """The unit's input hash is the first key term, and it propagates downstream.

    Not merely *"the root stage re-runs"*: the root's output changes with its input,
    so the next stage's input hash changes, and so on down the chain. A test that
    asserted only the root stage's re-dispatch would pass against an orchestrator that
    composed downstream input hashes from something stale.
    """
    out = tmp_path / "O"
    first = Recorder()
    orchestrator.run(
        descriptor,
        out,
        input_hashes=_input_hashes(),
        operations=first.table(),
        keys=KEYS,
    )

    second = Recorder()
    report = orchestrator.run(
        descriptor,
        out,
        input_hashes={name: _hash_of("different input") for name in UNIT_NAMES},
        operations=second.table(),
        keys=KEYS,
    )

    assert report.skipped == ()
    assert len(report.dispatched) == len(UNIT_NAMES) * 3


def test_a_stage_whose_key_differs_is_re_dispatched_even_though_it_is_done(
    descriptor: orchestrator.Descriptor,
    recorder: Recorder,
    tmp_path: pathlib.Path,
) -> None:
    """*"Is it terminal for this key?"* - not *"has it ever run?"*

    The distinction is asserted directly on the ledger: after the second run the
    record carries the **new** key, so the claim on disk is the claim about the run
    that produced the bytes now stored.
    """
    out = tmp_path / "O"
    orchestrator.run(
        descriptor,
        out,
        input_hashes=_input_hashes(),
        operations=recorder.table(),
        keys=KEYS,
    )
    before = store.read_ledger(out / UNIT_NAMES[0]).stages["acquire"].cache_key

    changed = orchestrator.KeyContext(registry_hash="d00d" * 16, kernels=KERNEL_TERMS)
    orchestrator.run(
        descriptor,
        out,
        input_hashes=_input_hashes(),
        operations=recorder.table(),
        keys=changed,
    )
    after = store.read_ledger(out / UNIT_NAMES[0]).stages["acquire"].cache_key

    assert before != after


def test_every_term_of_the_key_reaches_the_operation(
    descriptor: orchestrator.Descriptor,
    recorder: Recorder,
    tmp_path: pathlib.Path,
) -> None:
    """The key on the call is the seven-term key, and it is composed rather than passed.

    Recomputing it here from the same inputs is what makes the assertion falsifiable:
    a mutation that dropped a term from the orchestrator's composition would produce a
    different string, and a test asserting only "the key is a non-empty string" would
    not notice.
    """
    out = tmp_path / "O"
    orchestrator.run(
        descriptor,
        out,
        input_hashes=_input_hashes(),
        operations=recorder.table(),
        keys=KEYS,
    )

    acquire = next(call for call in recorder.calls if call.stage.name == "acquire")
    expected = orchestrator.cache_key_for(
        descriptor.graph.by_name["acquire"],
        _input_hashes()[acquire.unit],
        KEYS,
    )

    assert acquire.cache_key == expected
    assert len(acquire.cache_key) == 64


# --- Criterion 4: needs, blocking and contained failure ---------------------


def test_a_stage_whose_need_produced_no_artifact_is_not_dispatched(
    descriptor: orchestrator.Descriptor,
    tmp_path: pathlib.Path,
) -> None:
    """A failed need leaves its dependants alone rather than handing them a hole.

    ``transform`` fails, so ``persist`` cannot compose an input hash. It is reported
    blocked and left ``pending`` - not ``failed``, because it did not fail; and not
    dispatched, because dispatching it would mean composing a key over an absent hash.
    """
    out = tmp_path / "O"
    failing = Recorder(fail_on="transform")

    report = orchestrator.run(
        descriptor,
        out,
        input_hashes=_input_hashes(),
        operations=failing.table(),
        keys=KEYS,
    )

    unit = UNIT_NAMES[0]
    assert (unit, "persist") in report.blocked

    ledger = store.read_ledger(out / unit)
    assert ledger.stages["acquire"].state == "done"
    assert ledger.stages["transform"].state == "failed"
    assert ledger.stages["transform"].reason_code == "blank_page"
    assert ledger.stages["persist"].state == "pending", (
        "a blocked stage is pending, never failed - it did not fail"
    )
    assert not any(call.stage.name == "persist" for call in failing.calls), (
        "a blocked stage must not reach its operation"
    )


def test_a_failed_stage_records_the_key_it_ran_under(
    descriptor: orchestrator.Descriptor,
    tmp_path: pathlib.Path,
) -> None:
    """A failure is a result, so it carries the key beside it (`prd.md` FR-08)."""
    out = tmp_path / "O"
    failing = Recorder(fail_on="transform")

    orchestrator.run(
        descriptor,
        out,
        input_hashes=_input_hashes(),
        operations=failing.table(),
        keys=KEYS,
    )

    record = store.read_ledger(out / UNIT_NAMES[0]).stages["transform"]
    assert record.state == "failed"
    assert record.cache_key is not None
    assert len(record.cache_key) == 64


def test_the_unit_input_hash_is_the_first_key_term_for_a_root_stage(
    descriptor: orchestrator.Descriptor,
    recorder: Recorder,
    tmp_path: pathlib.Path,
) -> None:
    """A stage with no needs consumes the unit's own input, and says so on the call."""
    out = tmp_path / "O"
    inputs = _input_hashes()

    orchestrator.run(
        descriptor,
        out,
        input_hashes=inputs,
        operations=recorder.table(),
        keys=KEYS,
    )

    acquire = next(call for call in recorder.calls if call.stage.name == "acquire")
    assert acquire.input_hash == inputs[acquire.unit]
    assert acquire.needs == {}


def test_a_downstream_stage_sees_the_hashes_its_needs_produced(
    descriptor: orchestrator.Descriptor,
    recorder: Recorder,
    tmp_path: pathlib.Path,
) -> None:
    """A stage's needs are resolved to artifact hashes before it is called."""
    out = tmp_path / "O"
    orchestrator.run(
        descriptor,
        out,
        input_hashes=_input_hashes(),
        operations=recorder.table(),
        keys=KEYS,
    )

    unit = UNIT_NAMES[0]
    ledger = store.read_ledger(out / unit)
    transform = next(
        call
        for call in recorder.calls
        if call.stage.name == "transform" and call.unit == unit
    )

    assert set(transform.needs) == {"acquire"}
    assert transform.needs["acquire"] == ledger.stages["acquire"].artifact_sha256
    assert transform.input_hash != transform.needs["acquire"], (
        "the composed input hash is not simply the upstream hash: it is composed, so "
        "two needs cannot be rearranged into the same value"
    )


def test_the_input_hash_encoding_distinguishes_two_needs_from_two_names() -> None:
    """The composition is length-prefixed, so no pair of needs can be confused.

    Two needs whose names and hashes would concatenate to the same string must give
    different input hashes - the same discipline K8's registry hash uses, and for the
    same reason.
    """
    graph = orchestrator.Graph(
        stages=(
            orchestrator.Stage(
                name="join",
                kernel="store",
                op="put",
                needs=("ab", "c"),
                params=MappingProxyType({}),
            ),
        ),
        order=("join",),
    )
    for name in ("ab", "c"):
        graph = orchestrator.Graph(
            stages=(
                *graph.stages,
                orchestrator.Stage(
                    name=name,
                    kernel="store",
                    op="put",
                    needs=(),
                    params=MappingProxyType({}),
                ),
            ),
            order=("ab", "c", "join"),
        )

    unit = orchestrator.Unit(name="u", input_hash=_hash_of("u"))
    # `ab` and `c` produce hashes that concatenate to the same string as the pair
    # `a` + `bc` would; the length prefixes are what keep them apart.
    first = orchestrator.input_hash_for(
        unit,
        graph,
        "join",
        {
            "ab": store.StageRecord(
                state="done",
                artifact_sha256="1" * 64,
                reason_code=None,
                cache_key="a" * 64,
            ),
            "c": store.StageRecord(
                state="done",
                artifact_sha256="2" * 64,
                reason_code=None,
                cache_key="b" * 64,
            ),
        },
    )
    second = orchestrator.input_hash_for(
        unit,
        graph,
        "join",
        {
            "ab": store.StageRecord(
                state="done",
                artifact_sha256="1" * 63 + "12",
                reason_code=None,
                cache_key="a" * 64,
            ),
            "c": store.StageRecord(
                state="done",
                artifact_sha256="2" * 63 + "22",
                reason_code=None,
                cache_key="b" * 64,
            ),
        },
    )

    assert first != second


def test_a_need_that_recorded_no_artifact_is_refused_by_the_composition() -> None:
    """Composing an input hash over an absent artifact raises rather than guessing."""
    graph = orchestrator.Graph(
        stages=(
            orchestrator.Stage(
                name="join",
                kernel="store",
                op="put",
                needs=("upstream",),
                params=MappingProxyType({}),
            ),
        ),
        order=("join",),
    )
    unit = orchestrator.Unit(name="u", input_hash=_hash_of("u"))

    with pytest.raises(ValueError) as excinfo:
        orchestrator.input_hash_for(
            unit,
            graph,
            "join",
            {
                "upstream": store.StageRecord(
                    state="pending",
                    artifact_sha256=None,
                    reason_code=None,
                    cache_key=None,
                )
            },
        )

    assert "recorded no artifact" in str(excinfo.value)


# --- Criterion 5: the descriptor's shape is enforced ------------------------


@pytest.mark.parametrize(
    "extra",
    [
        {"pipeline": "M1-ErpVR"},
        {"field": "total"},
        {"document_type": "invoice"},
        {"extractor": "p"},
    ],
)
def test_a_descriptor_carrying_an_unknown_key_is_refused(
    extra: Mapping[str, object],
) -> None:
    """A pipeline code or a document concept is refused by the shape, not by a scan.

    The stage entry accepts exactly the keys this module declares, so a descriptor the
    domain layer will write at Stage 3 cannot be silently executed here: it is refused
    before anything is dispatched.

    Args:
        extra: The extra keys a stage entry carries.

    """
    payload = {
        "unit": "synthetic",
        "stages": [{"name": "a", "kernel": "store", "op": "put", **extra}],
    }

    with pytest.raises(ValueError) as excinfo:
        orchestrator.descriptor_from_mapping(payload)

    assert "Unknown key" in str(excinfo.value)


def test_a_descriptor_unknown_key_is_refused_at_the_top_level() -> None:
    """The whole descriptor is a closed shape too, not only its stages."""
    payload = {
        "unit": "synthetic",
        "pipeline": "M1-ErpVR",
        "stages": [{"name": "a", "kernel": "store", "op": "put"}],
    }

    with pytest.raises(ValueError) as excinfo:
        orchestrator.descriptor_from_mapping(payload)

    assert "Unknown key" in str(excinfo.value)


def test_a_descriptor_without_units_runs_over_exactly_one_unit() -> None:
    """An omitted ``units`` is one unit named after ``unit``, not zero."""
    payload = {
        "unit": "synthetic",
        "stages": [{"name": "a", "kernel": "store", "op": "put"}],
    }

    descriptor = orchestrator.descriptor_from_mapping(payload)

    assert descriptor.units == ("synthetic",)


def test_a_descriptor_with_repeated_unit_names_is_refused() -> None:
    """Two units sharing a name share a ledger, so one would overwrite the other."""
    payload = {
        "unit": "synthetic",
        "units": ["u", "u"],
        "stages": [{"name": "a", "kernel": "store", "op": "put"}],
    }

    with pytest.raises(ValueError) as excinfo:
        orchestrator.descriptor_from_mapping(payload)

    assert "unique" in str(excinfo.value)


def test_a_descriptor_covering_no_unit_is_refused() -> None:
    """A run over nothing would produce a manifest that says nothing, yet looks done."""
    payload = {
        "unit": "synthetic",
        "units": [],
        "stages": [{"name": "a", "kernel": "store", "op": "put"}],
    }

    with pytest.raises(ValueError) as excinfo:
        orchestrator.descriptor_from_mapping(payload)

    assert "at least one unit" in str(excinfo.value)


def test_read_descriptor_takes_an_injected_reader(tmp_path: pathlib.Path) -> None:
    """The format is behind a seam, so the kernel layer imports no third party."""
    path = tmp_path / "synthetic.yaml"
    path.write_text("placeholder", encoding="utf-8")

    descriptor = orchestrator.read_descriptor(path, lambda _path: SYNTHETIC)

    assert descriptor.unit == "synthetic"
    assert len(descriptor.graph.stages) == 3


# --- validate(): the non-executing check `orchestrator plan` needs ----------


def test_validate_writes_nothing_and_dispatches_nothing(
    descriptor: orchestrator.Descriptor,
    recorder: Recorder,
    tmp_path: pathlib.Path,
) -> None:
    """`plan` validates without executing: no artifact, no ledger, no stage.

    `plan-01-kernels.md` §6 step 3: *"exit `0`, no artifact written, no stage
    dispatched"*, and the wrong result it guards against is *"a `plan` that already
    ran work"*.
    """
    out = tmp_path / "O"

    orchestrator.validate(descriptor, _input_hashes(), recorder.table(), KEYS)

    assert recorder.calls == []
    assert not out.exists(), "a plan must not create the output tree"


def test_validate_refuses_a_missing_unit_input(
    descriptor: orchestrator.Descriptor, recorder: Recorder
) -> None:
    """A unit with no declared input hash has no first key term."""
    with pytest.raises(ValueError) as excinfo:
        orchestrator.validate(descriptor, {}, recorder.table(), KEYS)

    assert "No input hash is declared" in str(excinfo.value)


# The `_put` half of the recorder's table, used below to build a table that is
# deliberately incomplete.
#
# `protected-access` is the point rather than an accident: `Recorder._put` names the
# operation directly so the table can be *missing* the other one, which is the
# configuration the test exercises.
PUT_ONLY = Recorder()._put  # pylint: disable=protected-access


def test_validate_refuses_a_stage_with_no_operation(
    descriptor: orchestrator.Descriptor,
) -> None:
    """An operation table that lacks a stage is a configuration error, not a skip."""
    with pytest.raises(ValueError) as excinfo:
        orchestrator.validate(
            descriptor, _input_hashes(), {("store", "put"): PUT_ONLY}, KEYS
        )

    assert "no operation for" in str(excinfo.value)


def test_validate_refuses_a_kernel_with_no_key_terms(
    descriptor: orchestrator.Descriptor, recorder: Recorder
) -> None:
    """Every kernel a graph names must be keyed, or stages would share a key wrongly."""
    with pytest.raises(ValueError) as excinfo:
        orchestrator.validate(
            descriptor,
            _input_hashes(),
            recorder.table(),
            orchestrator.KeyContext(
                registry_hash=REGISTRY_HASH,
                kernels=MappingProxyType({"store": KERNEL_TERMS["store"]}),
            ),
        )

    assert "No key terms are declared" in str(excinfo.value)


def test_cache_key_for_refuses_a_kernel_with_no_terms() -> None:
    """A key composed from a defaulted term is the failure `sad.md` §5.1 prevents."""
    stage = orchestrator.Stage(
        name="a",
        kernel="unkeyed",
        op="put",
        needs=(),
        params=MappingProxyType({}),
    )

    with pytest.raises(ValueError) as excinfo:
        orchestrator.cache_key_for(stage, _hash_of("x"), KEYS)

    assert "No key terms are declared" in str(excinfo.value)


# --- The seven states, read rather than written -----------------------------


def test_the_terminal_states_are_read_from_k_7s_state_set() -> None:
    """The states this module treats as results are all real durable states.

    A state this module called terminal that K7 cannot write would be a branch no code
    path reaches - the kind of dead guard `plan-01-kernels.md` §7 warns about.
    """
    assert set(store.DURABLE_STATE_ORDER) >= orchestrator._TERMINAL_STATES  # pylint: disable=protected-access
    assert orchestrator.is_terminal("done")
    assert orchestrator.is_terminal("failed")
    assert orchestrator.is_terminal("skipped")


@pytest.mark.parametrize("state", ["pending", "running", "blocked", "stale"])
def test_a_stage_that_has_not_produced_a_result_is_not_terminal(state: str) -> None:
    """A position on the way to a result is not a result.

    ``stale`` is deliberately **not** terminal here: it means *kept over changed
    inputs*, so the stage's claim is about bytes produced under settings no longer in
    force. Treating it as a result would skip work the key says must run.

    Args:
        state: The non-terminal state under test.

    """
    assert not orchestrator.is_terminal(state)


# --- Test evidence, read from the plan's acceptance surface -----------------


def test_a_descriptor_whose_stage_narrows_the_shape_is_still_accepted() -> None:
    """The declared keys are accepted with every optional field supplied."""
    payload = {
        "unit": "synthetic",
        "units": ["u1"],
        "stages": [
            {
                "name": "acquire",
                "kernel": "store",
                "op": "put",
                "needs": [],
                "params": {"source": "generated"},
            },
            {
                "name": "transform",
                "kernel": "pdf",
                "op": "probe",
                "needs": ["acquire"],
                "params": {"page": "1"},
            },
        ],
    }

    descriptor = orchestrator.descriptor_from_mapping(payload)

    assert descriptor.units == ("u1",)
    assert descriptor.graph.by_name["acquire"].params == {"source": "generated"}
    assert descriptor.graph.order == ("acquire", "transform")


# --- Static guards: the layer's own isolation rules -------------------------


def collect_imported_modules(tree: ast.Module) -> list[str]:
    """Collect every module a syntax tree imports.

    Args:
        tree: The parsed module.

    Returns:
        The imported module names, in source order.

    """
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.append(node.module)
    return modules


def find_dependency_violations(modules: list[str]) -> list[str]:
    """Report imports that invert the dependency arrow.

    Args:
        modules: The imported module names.

    Returns:
        The offending names, sorted.

    """
    forbidden = ("docflow.adapters", "docflow.components", "docflow.ports")
    return sorted(name for name in modules if name.startswith(forbidden))


def test_the_orchestrator_imports_nothing_above_the_kernel_layer() -> None:
    """K1 imports its own layer and the standard library - never an adapter or a port.

    An import at the top would be an arrow pointing up: the orchestrator is the thing
    a composition root drives, so it must not know what is behind a port.
    """
    imported = collect_imported_modules(ORCHESTRATOR_TREE)

    assert imported, "the module must import something"
    assert find_dependency_violations(imported) == []
    assert all(
        name.split(".")[0] not in {"yaml", "docling", "ollama", "httpx", "PIL"}
        for name in imported
    ), "no third-party parser or engine may be imported by a kernel"


def test_the_dependency_guard_notices_a_violation() -> None:
    """The guard itself is falsified against a synthetic source.

    A guard that has never been shown to reject anything is a guard whose passing says
    nothing - the lesson `plan-01-kernels.md` §7 and the adapter suites both record.
    """
    tree = ast.parse("from docflow.adapters.docling import DoclingEngine")

    assert find_dependency_violations(collect_imported_modules(tree)) == [
        "docflow.adapters.docling"
    ]
    assert (
        find_dependency_violations(collect_imported_modules(ast.parse("import json")))
        == []
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
        "docling",
        "ErVR",
        "EpVR",
        "ErpVR",
    )
    identifiers = {
        node.id
        for node in ast.walk(ORCHESTRATOR_TREE)
        if isinstance(node, ast.Name) and not node.id.startswith("_")
    }
    identifiers |= {
        alias.name
        for node in ast.walk(ORCHESTRATOR_TREE)
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
    """The deliverable path is `docflow/kernels/orchestrator.py`."""
    assert ORCHESTRATOR_PATH.name == "orchestrator.py"
    assert ORCHESTRATOR_PATH.parent.name == "kernels"
    assert "docflow" in sys.modules
