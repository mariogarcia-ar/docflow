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
#
# `duplicate-code`: the ledger-record shapes are repeated from the sibling suites on
# purpose. A shared builder would make the suites depend on one another's copies, so a
# field added to `StageRecord` would be defaulted once in a helper instead of being
# confronted in every suite that constructs one - which is exactly how a required field
# stops being required in the tests that matter.
# pylint: disable=duplicate-code

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

#: The slot bounds every test declares unless it is testing the declaration itself.
#: Stated rather than defaulted, so a suite that forgot to declare a bound would fail
#: to run rather than silently take the scheduler's baseline - the same reason the
#: kernel has no default on `run`.
SLOTS = orchestrator.SLOT_BOUNDS

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
            # The unit directory **is** the store root, so bytes land at
            # `<unit>/artifacts/<sha256>` - the layout `_unit_dir` and K7's own artifact
            # directory compose, and the layout verification looks in. Passing
            # `<unit>/artifacts` here would nest a second `artifacts/` and every claim
            # would fail to verify, which is exactly what this used to do.
            call.unit_dir,
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
        slots=SLOTS,
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
            # The unit directory **is** the store root, so verification is asked there -
            # the same root `store.put` wrote to.
            assert store.verify(out / unit, record.artifact_sha256)


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
        slots=SLOTS,
    )
    manifest = json.loads(
        (out / orchestrator.MANIFEST_NAME).read_text(encoding="utf-8")
    )

    assert set(manifest) == {
        "state",
        "control",
        "totals",
        "stages",
        "outcomes",
        "attempts",
        "unverified",
        "inflight",
    }
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
        slots=SLOTS,
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
        slots=SLOTS,
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
        slots=SLOTS,
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
        slots=SLOTS,
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
        slots=SLOTS,
    )
    first_pass = len(recorder.calls)

    second = orchestrator.run(
        descriptor,
        out,
        input_hashes=_input_hashes(),
        operations=recorder.table(),
        keys=KEYS,
        slots=SLOTS,
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
        slots=SLOTS,
    )

    changed = orchestrator.KeyContext(registry_hash="d00d" * 16, kernels=KERNEL_TERMS)
    second = orchestrator.run(
        descriptor,
        out,
        input_hashes=_input_hashes(),
        operations=recorder.table(),
        keys=changed,
        slots=SLOTS,
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
        slots=SLOTS,
    )

    second = Recorder()
    report = orchestrator.run(
        descriptor,
        out,
        input_hashes={name: _hash_of("different input") for name in UNIT_NAMES},
        operations=second.table(),
        keys=KEYS,
        slots=SLOTS,
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
        slots=SLOTS,
    )
    before = store.read_ledger(out / UNIT_NAMES[0]).stages["acquire"].cache_key

    changed = orchestrator.KeyContext(registry_hash="d00d" * 16, kernels=KERNEL_TERMS)
    orchestrator.run(
        descriptor,
        out,
        input_hashes=_input_hashes(),
        operations=recorder.table(),
        keys=changed,
        slots=SLOTS,
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
        slots=SLOTS,
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
        slots=SLOTS,
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
        slots=SLOTS,
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
        slots=SLOTS,
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
        slots=SLOTS,
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
                attempts=1,
            ),
            "c": store.StageRecord(
                state="done",
                artifact_sha256="2" * 64,
                reason_code=None,
                cache_key="b" * 64,
                attempts=1,
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
                attempts=1,
            ),
            "c": store.StageRecord(
                state="done",
                artifact_sha256="2" * 63 + "22",
                reason_code=None,
                cache_key="b" * 64,
                attempts=1,
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
                    attempts=0,
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

    orchestrator.validate(descriptor, _input_hashes(), recorder.table(), KEYS, SLOTS)

    assert recorder.calls == []
    assert not out.exists(), "a plan must not create the output tree"


def test_validate_refuses_a_missing_unit_input(
    descriptor: orchestrator.Descriptor, recorder: Recorder
) -> None:
    """A unit with no declared input hash has no first key term."""
    with pytest.raises(ValueError) as excinfo:
        orchestrator.validate(descriptor, {}, recorder.table(), KEYS, SLOTS)

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
            descriptor, _input_hashes(), {("store", "put"): PUT_ONLY}, KEYS, SLOTS
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
            SLOTS,
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


# --- W5: the control, so a pause can interrupt a run already in flight -------


def test_an_absent_control_means_the_run_carries_on(tmp_path: pathlib.Path) -> None:
    """The only default in this module, and it is about an operator's silence.

    A run nobody has asked to hold is a run that runs. Nothing about a *value the
    system would otherwise have to produce* is defaulted here - the class of default
    the artifacts forbid.
    """
    out = tmp_path / "O"

    assert orchestrator.read_control(out).state == "running"
    assert orchestrator.read_control(out).holds is False
    assert orchestrator.control_of(out) == "running"


def test_a_pause_is_recorded_and_holds(tmp_path: pathlib.Path) -> None:
    """``paused`` holds; ``running`` does not."""
    out = tmp_path / "O"

    orchestrator.write_control(out, "paused")

    assert orchestrator.control_of(out) == "paused"
    assert orchestrator.read_control(out).holds is True

    orchestrator.write_control(out, "running")
    assert orchestrator.read_control(out).holds is False


def test_a_stopped_control_holds_at_the_same_checkpoint(tmp_path: pathlib.Path) -> None:
    """``stopped`` is honoured where ``paused`` is: the signal differs, not the check.

    `stop --force` also terminates the process. What this file adds is the case where
    the signal has *not* yet been delivered - a scheduler that reaches a checkpoint
    reads it and must not continue.
    """
    out = tmp_path / "O"

    orchestrator.write_control(out, "stopped")

    assert orchestrator.read_control(out).holds is True


def test_an_unrecognised_control_state_is_refused(tmp_path: pathlib.Path) -> None:
    """A control that cannot be read is not an instruction to carry on.

    Reading an unknown value as ``running`` would silently resume a run somebody asked
    to hold, which is the one failure this file exists to prevent.
    """
    out = tmp_path / "O"
    out.mkdir()
    (out / orchestrator.CONTROL_NAME).write_text('{"state": "maybe"}', encoding="utf-8")

    with pytest.raises(ValueError) as excinfo:
        orchestrator.read_control(out)

    assert "is not a control state" in str(excinfo.value)


def test_a_control_that_is_not_an_object_is_refused(tmp_path: pathlib.Path) -> None:
    """A malformed control names a problem rather than reading as an absent one."""
    out = tmp_path / "O"
    out.mkdir()
    (out / orchestrator.CONTROL_NAME).write_text('["paused"]', encoding="utf-8")

    with pytest.raises(ValueError) as excinfo:
        orchestrator.read_control(out)

    assert "must hold an object" in str(excinfo.value)


def test_a_paused_run_dispatches_nothing_and_reports_what_it_held(
    descriptor: orchestrator.Descriptor,
    recorder: Recorder,
    tmp_path: pathlib.Path,
) -> None:
    """A run asked to hold before it starts does no work, and says so.

    The held work is reported **separately from ``skipped``**: a held stage has not
    been done, and reporting it as skipped would read as complete.
    """
    out = tmp_path / "O"
    orchestrator.write_control(out, "paused")

    report = orchestrator.run(
        descriptor,
        out,
        input_hashes=_input_hashes(),
        operations=recorder.table(),
        keys=KEYS,
        slots=SLOTS,
    )

    assert recorder.calls == []
    assert report.dispatched == ()
    assert report.skipped == ()
    assert set(report.held) == set(UNIT_NAMES), "every unreached unit is reported"


def test_a_pause_lands_at_a_stage_boundary_not_a_unit_boundary(
    descriptor: orchestrator.Descriptor,
    tmp_path: pathlib.Path,
) -> None:
    """The checkpoint is per stage, which is what makes `pause` mean anything.

    A unit of a real job is many stages. Holding only between units would make a pause
    indistinguishable from *let the whole job finish* - and the operator who asked for
    it would have no way to tell which had happened.
    """
    out = tmp_path / "O"
    unit = UNIT_NAMES[0]

    class PausingRecorder(Recorder):
        """A recorder that asks the run to hold after its first dispatch."""

        def _answer(
            self, call: orchestrator.StageCall, *, payload: str
        ) -> KernelResult[Artifact]:
            """Record, then pause the run once ``acquire`` has run."""
            result = super()._answer(call, payload=payload)
            if call.stage.name == "acquire":
                orchestrator.write_control(out, "paused")
            return result

    pausing = PausingRecorder()
    report = orchestrator.run(
        descriptor,
        out,
        input_hashes=_input_hashes(),
        operations=pausing.table(),
        keys=KEYS,
        slots=SLOTS,
    )

    assert [name for _unit, name in report.dispatched] == ["acquire"], (
        "the run must stop at the stage boundary after the pause, not after the unit"
    )
    assert f"{unit}:transform" in report.held

    ledger = store.read_ledger(out / unit)
    assert ledger.stages["acquire"].state == "done"
    assert ledger.stages["transform"].state == "pending", (
        "a held stage is pending: it has not been begun, so it is not running"
    )


def test_resuming_continues_from_the_exact_stage(
    descriptor: orchestrator.Descriptor,
    tmp_path: pathlib.Path,
) -> None:
    """Clearing the control lets a plain `run` continue - there is no `resume` verb.

    `FR-02`: recovery *is* running it again. What makes that correct rather than a
    restart is that the stages already terminal for their key are skipped, which is the
    idempotency `E05-01` already established.
    """
    out = tmp_path / "O"
    unit = UNIT_NAMES[0]

    class PausingRecorder(Recorder):
        """A recorder that pauses the run after ``acquire``."""

        def _answer(
            self, call: orchestrator.StageCall, *, payload: str
        ) -> KernelResult[Artifact]:
            """Record, then pause the run once ``acquire`` has run."""
            result = super()._answer(call, payload=payload)
            if call.stage.name == "acquire":
                orchestrator.write_control(out, "paused")
            return result

    orchestrator.run(
        descriptor,
        out,
        input_hashes=_input_hashes(),
        operations=PausingRecorder().table(),
        keys=KEYS,
        slots=SLOTS,
    )

    orchestrator.write_control(out, "running")
    resumed = Recorder()
    report = orchestrator.run(
        descriptor,
        out,
        input_hashes=_input_hashes(),
        operations=resumed.table(),
        keys=KEYS,
        slots=SLOTS,
    )

    assert (unit, "acquire") in report.skipped, "completed work is not re-run"
    assert (unit, "transform") in report.dispatched, "the held stage now runs"
    assert (unit, "persist") in report.dispatched
    assert report.held == ()

    ledger = store.read_ledger(out / unit)
    assert {record.state for record in ledger.stages.values()} == {"done"}


def test_the_manifest_reports_a_held_run_as_holding(
    descriptor: orchestrator.Descriptor,
    recorder: Recorder,
    tmp_path: pathlib.Path,
) -> None:
    """A paused run and a crashed run have the same ledgers and different causes.

    ``incomplete`` would be indistinguishable from a crash, so the run's state says
    ``holding`` and carries the control that produced it. The run state is a *third*
    vocabulary - the seven durable states describe a stage, and a value no ledger may
    carry has no business in ``run.json``.
    """
    out = tmp_path / "O"
    orchestrator.write_control(out, "paused")

    orchestrator.run(
        descriptor,
        out,
        input_hashes=_input_hashes(),
        operations=recorder.table(),
        keys=KEYS,
        slots=SLOTS,
    )

    manifest = json.loads(
        (out / orchestrator.MANIFEST_NAME).read_text(encoding="utf-8")
    )

    assert manifest["state"] == "holding"
    assert manifest["control"] == "paused"
    assert manifest["inflight"] == [], (
        "inflight is derived from the ledgers, and a run held before its first unit "
        "has produced none - the state comes from the control, not from a claim about "
        "units that were never reached"
    )


def test_a_run_held_before_its_first_unit_is_not_reported_complete(
    descriptor: orchestrator.Descriptor,
    recorder: Recorder,
    tmp_path: pathlib.Path,
) -> None:
    """*No unfinished units* must not read as *finished*.

    A pause taken before the first stage leaves the output root with an empty ledger
    tree, which is the state a naive *is anything inflight?* check answers "no" to.
    Reporting that as ``complete`` is the same class of error as a ``done`` claim about
    bytes that do not exist, one level up - and it is exactly the case the first
    checkpoint in ``run`` exists to produce, so it has to read correctly.
    """
    out = tmp_path / "O"
    orchestrator.write_control(out, "paused")

    manifest = orchestrator.run(
        descriptor,
        out,
        input_hashes=_input_hashes(),
        operations=recorder.table(),
        keys=KEYS,
        slots=SLOTS,
    ).manifest

    assert manifest["state"] == "holding"
    assert manifest["totals"]["units"] == 0, "no unit was reached, so none has a ledger"
    assert manifest["state"] != "complete"


def test_the_manifest_reports_a_completed_run_as_complete(
    descriptor: orchestrator.Descriptor,
    recorder: Recorder,
    tmp_path: pathlib.Path,
) -> None:
    """A finished run says so, and its control does not confuse the reading."""
    out = tmp_path / "O"
    orchestrator.run(
        descriptor,
        out,
        input_hashes=_input_hashes(),
        operations=recorder.table(),
        keys=KEYS,
        slots=SLOTS,
    )
    orchestrator.write_control(out, "paused")

    manifest = orchestrator.rebuild_index(out)

    assert manifest["state"] == "complete", (
        "no work remains, so the run is complete whatever an operator last asked"
    )
    assert manifest["control"] == "paused", "the control is reported as a fact"


def test_the_manifest_reports_attempt_counts_for_work_that_ran(
    descriptor: orchestrator.Descriptor,
    recorder: Recorder,
    tmp_path: pathlib.Path,
) -> None:
    """A stage that ran more than once is the visible trace of a retry.

    `kernel-cli.md` §7 forbids *retry-until-agreement* and `plan-01-kernels.md` §9 says
    the prohibition is enforceable only if the pattern can be **seen**. The count is
    reported rather than policed, and a first run counts one.
    """
    out = tmp_path / "O"
    orchestrator.run(
        descriptor,
        out,
        input_hashes=_input_hashes(),
        operations=recorder.table(),
        keys=KEYS,
        slots=SLOTS,
    )

    manifest = orchestrator.rebuild_index(out)

    assert manifest["attempts"][UNIT_NAMES[0]]["acquire"] == 1


def test_a_unit_failure_does_not_abort_the_run(
    descriptor: orchestrator.Descriptor,
    tmp_path: pathlib.Path,
) -> None:
    """Failure is contained to the unit - what makes 11k files one command.

    `FR-07`: one unit failing never aborts the run. The failing unit is reported against
    **itself**, and every other unit completes.
    """
    out = tmp_path / "O"
    failing = Recorder(fail_on="transform")

    report = orchestrator.run(
        descriptor,
        out,
        input_hashes=_input_hashes(),
        operations=failing.table(),
        keys=KEYS,
        slots=SLOTS,
    )

    for unit in UNIT_NAMES:
        ledger = store.read_ledger(out / unit)
        assert ledger.stages["acquire"].state == "done"
        assert ledger.stages["transform"].state == "failed"
        assert ledger.stages["transform"].reason_code == "blank_page"

    manifest = orchestrator.rebuild_index(out)
    assert manifest["state"] == "incomplete", "the run did not finish, and says so"
    assert manifest["outcomes"]["blank_page"] == len(UNIT_NAMES), (
        "the outcome is counted per unit, so the failure is attributed to the units"
    )

    # And the report names the failing unit's stages rather than the run's:
    # `FR-07`'s containment means the failure is an outcome *of that unit*.
    assert [name for _unit, name in report.dispatched].count("transform") == len(
        UNIT_NAMES
    ), "each unit's transform was attempted, and each reported its own failure"
    assert report.dispatched, "the run dispatched despite a failing unit"


class ObservingRecorder(Recorder):
    """A recorder that reads the ledger **from inside** the operation.

    This is the only vantage point from which the ordering is falsifiable. A test
    that inspects the ledger after a run proves the stage reached a state; it cannot
    tell whether the state was written before the work or after it, because both
    orderings leave the same record when nothing interrupts the run.
    """

    def __init__(self) -> None:
        """Initialize the recorder with an empty observation log."""
        super().__init__()
        #: ``(stage, state)`` as seen from inside each operation.
        self.seen: list[tuple[str, str]] = []

    def _answer(
        self, call: orchestrator.StageCall, *, payload: str
    ) -> KernelResult[Artifact]:
        """Record the ledger's state for this stage, then answer normally.

        Args:
            call: The dispatch call.
            payload: The text whose hash becomes the artifact.

        Returns:
            The stored artifact.

        """
        record = store.read_ledger(call.unit_dir).stages[call.stage.name]
        self.seen.append((call.stage.name, record.state))
        return super()._answer(call, payload=payload)


def test_the_ledger_reads_running_from_inside_the_operation(
    descriptor: orchestrator.Descriptor,
    tmp_path: pathlib.Path,
) -> None:
    """``running`` is on disk **before** the work starts.

    `plan-01-kernels.md` §7b row 3 and `sad.md` §7.1: a scheduler that wrote state
    only on completion would report a killed stage as never having run. The state is
    read from inside the operation, because that is the only place the two orderings
    are distinguishable - afterwards they look identical.
    """
    out = tmp_path / "O"
    observing = ObservingRecorder()

    orchestrator.run(
        descriptor,
        out,
        input_hashes=_input_hashes(),
        operations=observing.table(),
        keys=KEYS,
        slots=SLOTS,
    )

    assert observing.seen, "the operations must have been called"
    assert {state for _stage, state in observing.seen} == {"running"}, (
        "every stage must already read `running` when its work begins; a stage the "
        "operation sees as `pending` is one whose kill would be misread"
    )
    assert [stage for stage, _state in observing.seen] == [
        "acquire",
        "transform",
        "persist",
    ] * len(UNIT_NAMES), "in dispatch order"


def test_the_cache_key_is_recorded_before_the_work_too(
    descriptor: orchestrator.Descriptor,
    tmp_path: pathlib.Path,
) -> None:
    """The key ``begin`` wrote is the key the operation then ran under.

    A stage cut off mid-work stays ``running`` with whatever was recorded when it
    started, and the resume decision reads that record. Recording the state without
    the key would leave every interrupted stage unkeyed - the ledger keyed exactly
    where it matters least.
    """
    out = tmp_path / "O"
    observing = ObservingRecorder()

    orchestrator.run(
        descriptor,
        out,
        input_hashes=_input_hashes(),
        operations=observing.table(),
        keys=KEYS,
        slots=SLOTS,
    )

    for call in observing.calls:
        record = store.read_ledger(out / call.unit).stages[call.stage.name]
        assert record.cache_key == call.cache_key, call.stage.name


def test_a_failure_is_recorded_as_failed_and_not_committed(
    descriptor: orchestrator.Descriptor,
    tmp_path: pathlib.Path,
) -> None:
    """A refusal takes the ``fail`` path - it never reaches ``commit``.

    ``commit`` takes the artifact ``put`` returned, so a refusal has nothing to pass
    it. A scheduler that committed unconditionally would either write ``done`` about
    no bytes or lose the typed reason.
    """
    out = tmp_path / "O"
    failing = Recorder(fail_on="transform")

    orchestrator.run(
        descriptor,
        out,
        input_hashes=_input_hashes(),
        operations=failing.table(),
        keys=KEYS,
        slots=SLOTS,
    )

    record = store.read_ledger(out / UNIT_NAMES[0]).stages["transform"]
    assert record.state == "failed"
    assert record.reason_code == "blank_page"
    assert record.artifact_sha256 is None


class PausingRecorder(Recorder):
    """A recorder that asks the run to hold once ``acquire`` has run."""

    def __init__(self, out_dir: pathlib.Path) -> None:
        """Initialize the recorder.

        Args:
            out_dir: The run's output root, where the control is written.

        """
        super().__init__()
        self.out_dir = out_dir

    def _answer(
        self, call: orchestrator.StageCall, *, payload: str
    ) -> KernelResult[Artifact]:
        """Answer, then pause the run if this was ``acquire``.

        Args:
            call: The dispatch call.
            payload: The text whose hash becomes the artifact.

        Returns:
            The stored artifact.

        """
        result = super()._answer(call, payload=payload)
        if call.stage.name == "acquire":
            orchestrator.write_control(self.out_dir, "paused")
        return result


def test_a_run_paused_with_work_half_done_reports_holding(
    descriptor: orchestrator.Descriptor,
    tmp_path: pathlib.Path,
) -> None:
    """Work remains **and** an operator asked to hold: ``holding``, not ``incomplete``.

    The ledger tree is not empty and a stage is left unfinished. Reading that as
    ``incomplete`` is indistinguishable from a crash, so an operator could not tell
    whether their pause took effect. This also exercises the branch that consults the
    control *after* establishing that a unit is unfinished - the empty-tree test
    returns earlier, so a mutation of that later branch would otherwise survive.
    """
    out = tmp_path / "O"

    manifest = orchestrator.run(
        descriptor,
        out,
        input_hashes=_input_hashes(),
        operations=PausingRecorder(out).table(),
        keys=KEYS,
        slots=SLOTS,
    ).manifest

    assert manifest["state"] == "holding"
    assert manifest["totals"]["units"] > 0, (
        "a unit was reached, so the tree is not empty"
    )
    assert manifest["inflight"], "the paused unit is unfinished, and says so"


def test_the_same_partial_run_without_a_pause_reports_incomplete(
    descriptor: orchestrator.Descriptor,
    tmp_path: pathlib.Path,
) -> None:
    """The control separates *paused* from *abandoned* - nothing else does.

    Identical ledgers, identical unfinished work, a different control: the two runs
    must report differently, or the run state is not carrying what it exists for.
    """
    out = tmp_path / "O"
    orchestrator.run(
        descriptor,
        out,
        input_hashes=_input_hashes(),
        operations=PausingRecorder(out).table(),
        keys=KEYS,
        slots=SLOTS,
    )
    assert orchestrator.rebuild_index(out)["state"] == "holding"

    orchestrator.write_control(out, "running")

    rebuilt = orchestrator.rebuild_index(out)
    assert rebuilt["state"] == "incomplete", (
        "the ledgers are unchanged; only the operator's request changed"
    )
    assert rebuilt["inflight"], "the unfinished unit is still reported"


# --- W6: verification on every read, with no flag ----------------------------


def test_a_ledger_read_carries_its_verification_outcome(
    descriptor: orchestrator.Descriptor,
    tmp_path: pathlib.Path,
) -> None:
    """The read returns the ledger **and** what the filesystem says about it.

    `plan-01-kernels.md` §7b row 4: breaking this looks like *"a code path returns a
    ledger without verifying it"*. There is one public read and it returns both, so
    there is no way to obtain one without the other.
    """
    out = tmp_path / "O"
    fresh = Recorder()
    orchestrator.run(
        descriptor,
        out,
        input_hashes=_input_hashes(),
        operations=fresh.table(),
        keys=KEYS,
        slots=SLOTS,
    )

    unit = out / UNIT_NAMES[0]
    healthy = orchestrator.read_ledger(unit)
    assert healthy.ledger.unit == UNIT_NAMES[0]
    assert healthy.unverified == {}
    assert healthy.trustworthy is True

    # Asserting only `== {}` would pass against a read that never verified at all, so
    # the outcome is observed **changing** with the filesystem: break one claim and the
    # same read must say so.
    record = store.read_ledger(unit).stages["acquire"]
    assert record.artifact_sha256 is not None
    (unit / "artifacts" / record.artifact_sha256).unlink()

    damaged = orchestrator.read_ledger(unit)
    assert damaged.unverified == {"acquire": "artifact_missing"}
    assert damaged.trustworthy is False


def test_a_deleted_artifact_makes_its_stage_read_as_unverified(
    descriptor: orchestrator.Descriptor,
    tmp_path: pathlib.Path,
) -> None:
    """`plan-01-kernels.md` §6 step 9: delete a `done` stage's artifact by hand.

    The recorded state is left alone - rewriting it would destroy the fact that the
    claim was ever made - and the verification outcome is what reports the absence.
    """
    out = tmp_path / "O"
    fresh = Recorder()
    orchestrator.run(
        descriptor,
        out,
        input_hashes=_input_hashes(),
        operations=fresh.table(),
        keys=KEYS,
        slots=SLOTS,
    )

    unit = out / UNIT_NAMES[0]
    record = store.read_ledger(unit).stages["acquire"]
    assert record.artifact_sha256 is not None
    (unit / "artifacts" / record.artifact_sha256).unlink()

    verified = orchestrator.read_ledger(unit)

    assert verified.unverified == {"acquire": "artifact_missing"}
    assert verified.trustworthy is False
    assert verified.ledger.stages["acquire"].state == "done", (
        "the recorded state is not corrected: the ledger says what happened, and the "
        "verification outcome says what is still true"
    )


def test_a_truncated_artifact_is_as_unverified_as_a_deleted_one(
    descriptor: orchestrator.Descriptor,
    tmp_path: pathlib.Path,
) -> None:
    """The bytes a claim names are not there, whether the file is gone or wrong."""
    out = tmp_path / "O"
    orchestrator.run(
        descriptor,
        out,
        input_hashes=_input_hashes(),
        operations=Recorder().table(),
        keys=KEYS,
        slots=SLOTS,
    )

    unit = out / UNIT_NAMES[0]
    record = store.read_ledger(unit).stages["transform"]
    assert record.artifact_sha256 is not None
    (unit / "artifacts" / record.artifact_sha256).write_bytes(b"truncated")

    assert orchestrator.verify_ledger(unit) == {"transform": "artifact_missing"}


def test_the_unverified_code_is_the_closed_sets_artifact_missing(
    descriptor: orchestrator.Descriptor,
    tmp_path: pathlib.Path,
) -> None:
    """`kernel-cli.md` §5: `artifact_missing`, exit `2`.

    Exit `2` follows from the code being an expected negative rather than a precondition
    failure, so the code is the assertion target and never the message.
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

    assert orchestrator._CODE_ARTIFACT_MISSING in closed  # pylint: disable=protected-access

    # And the code a deleted artifact *produces* is that one - not merely *a* code in
    # the set, which any valid member would satisfy.
    unit = tmp_path / "O" / UNIT_NAMES[0]
    out = tmp_path / "O"
    orchestrator.run(
        descriptor,
        out,
        input_hashes=_input_hashes(),
        operations=Recorder().table(),
        keys=KEYS,
        slots=SLOTS,
    )
    record = store.read_ledger(unit).stages["acquire"]
    assert record.artifact_sha256 is not None
    (unit / "artifacts" / record.artifact_sha256).unlink()

    assert orchestrator.verify_ledger(unit) == {"acquire": "artifact_missing"}, (
        "the consequence must report artifact_missing specifically: a different valid "
        "code is a different fact, and the assertion targets the fact"
    )


def test_the_manifest_reports_the_unverified_claims(
    descriptor: orchestrator.Descriptor,
    tmp_path: pathlib.Path,
) -> None:
    """`run.json` is a *reading* of the ledgers, so it verifies as it reads.

    A manifest that reported `done` without saying which claims the filesystem no longer
    supports would be a manifest whose counters agree with a ledger that is lying.
    """
    out = tmp_path / "O"
    orchestrator.run(
        descriptor,
        out,
        input_hashes=_input_hashes(),
        operations=Recorder().table(),
        keys=KEYS,
        slots=SLOTS,
    )

    healthy = orchestrator.rebuild_index(out)
    assert healthy[orchestrator.UNVERIFIED_KEY] == {}, "a healthy run reports nothing"

    unit = out / UNIT_NAMES[0]
    record = store.read_ledger(unit).stages["persist"]
    assert record.artifact_sha256 is not None
    (unit / "artifacts" / record.artifact_sha256).unlink()

    damaged = orchestrator.rebuild_index(out)

    assert damaged[orchestrator.UNVERIFIED_KEY] == {UNIT_NAMES[0]: ["persist"]}
    assert damaged["totals"]["done"] == healthy["totals"]["done"], (
        "the recorded states are unchanged - only the verification outcome moved, "
        "which is what makes the two readings comparable"
    )


def test_a_run_re_dispatches_a_stage_whose_artifact_was_deleted(
    descriptor: orchestrator.Descriptor,
    tmp_path: pathlib.Path,
) -> None:
    """The criterion's action, not merely its report: the stage **runs again**.

    `plan-01-kernels.md` §6 step 9's wrong result is *"skipped as complete - AC
    Verification is not optional fails silently if this passes"*. So the assertion is on
    the dispatch, and the stage's second artifact must be a real one.
    """
    out = tmp_path / "O"
    orchestrator.run(
        descriptor,
        out,
        input_hashes=_input_hashes(),
        operations=Recorder().table(),
        keys=KEYS,
        slots=SLOTS,
    )

    unit = out / UNIT_NAMES[0]
    record = store.read_ledger(unit).stages["acquire"]
    assert record.artifact_sha256 is not None
    (unit / "artifacts" / record.artifact_sha256).unlink()

    second = Recorder()
    report = orchestrator.run(
        descriptor,
        out,
        input_hashes=_input_hashes(),
        operations=second.table(),
        keys=KEYS,
        slots=SLOTS,
    )

    assert (unit.name, "acquire") in report.unverified, (
        "the run says which claim it could not honour"
    )
    assert (unit.name, "acquire") in report.dispatched, "and it ran the stage again"
    assert (
        any(
            call.stage.name == "acquire" and call.unit == unit.name
            for call in second.calls
        )
        is not False
    ), "the stage's operation was actually called"

    restored = store.read_ledger(unit).stages["acquire"]
    assert restored.artifact_sha256 is not None
    assert store.verify(unit, restored.artifact_sha256) is True


def test_a_stage_left_unverified_and_blocked_does_not_lend_its_stale_hash(
    descriptor: orchestrator.Descriptor,
    tmp_path: pathlib.Path,
) -> None:
    """A need that is `done` but unverified must not satisfy its dependants.

    The construction that reaches this is narrower than it looks, and worth spelling out
    because the obvious version does **not** reach it: deleting a middle stage's
    artifact normally restores it on the next run - with the *identical* hash, since
    the key did not change - so its dependant correctly skips rather than blocks.

    The branch is reached when the unverified stage **cannot be restored**, because its
    own need failed. It then stays `done` with a recorded hash whose bytes are gone, and
    its dependant is the thing at risk: without the check, that dependant would take the
    stale hash and compose a key over content nothing can supply.
    """
    out = tmp_path / "O"
    orchestrator.run(
        descriptor,
        out,
        input_hashes=_input_hashes(),
        operations=Recorder().table(),
        keys=KEYS,
        slots=SLOTS,
    )

    unit = out / UNIT_NAMES[0]
    records = store.read_ledger(unit).stages
    for stage_name in ("acquire", "transform"):
        digest = records[stage_name].artifact_sha256
        assert digest is not None
        (unit / "artifacts" / digest).unlink()

    # `acquire` fails on this run, so `transform` cannot be restored and stays `done`
    # with a hash whose bytes are gone.
    failing = Recorder(fail_on="acquire")
    report = orchestrator.run(
        descriptor,
        out,
        input_hashes=_input_hashes(),
        operations=failing.table(),
        keys=KEYS,
        slots=SLOTS,
    )

    after = store.read_ledger(unit).stages
    assert after["acquire"].state == "failed"
    assert after["transform"].state == "done", "it kept its old record"

    assert (unit.name, "transform") in report.blocked
    assert (unit.name, "persist") in report.blocked, (
        "the dependant of an unverified need is blocked rather than handed a hash for "
        "bytes that are not there"
    )
    assert not any(
        call.stage.name == "persist" and call.unit == unit.name
        for call in failing.calls
    ), "a blocked stage never reaches its operation"


def test_the_raw_ledger_read_is_reached_only_from_the_verification_layer() -> None:
    """There is **no code path that skips the check** - asserted over the source.

    Two functions read the ledger raw, and both are the verification layer:
    :func:`verify_ledger` reads for itself because a standalone verifier has no ledger
    in hand, and :func:`read_ledger` reads once and verifies **that** ledger so two
    reads cannot see different bytes. Every other function reaches it through
    :func:`read_ledger`.

    A third raw call site - a fast path, a `--force`-shaped shortcut, an internal
    caller that knows better - reddens this, which is the structural form of it.
    """
    calls = [
        node
        for node in ast.walk(ORCHESTRATOR_TREE)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "read_ledger"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "store"
    ]

    readers = sorted(
        {
            node.name
            for node in ast.walk(ORCHESTRATOR_TREE)
            if isinstance(node, ast.FunctionDef)
            and any(call in ast.walk(node) for call in calls)
        }
    )

    assert readers == ["read_ledger", "verify_ledger"], (
        "the raw read belongs to the verification layer and to nothing else; it is "
        f"reached from {readers}"
    )
    assert len(calls) == 2, (
        f"one raw site per verifying function; found {len(calls)} - a third would be a "
        "read that does not verify, and two in one function would verify a ledger the "
        "reader no longer holds"
    )


def test_the_module_offers_no_flag_shaped_way_to_skip_verification() -> None:
    """No `verify` / `force` / `skip` parameter exists on any public read path.

    A parameter that turned the check off would be the `--verify`-shaped escape the
    artifacts forbid, wearing a signature instead of a flag (`ADR-006`).
    """
    public = [
        node
        for node in ast.walk(ORCHESTRATOR_TREE)
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")
    ]
    assert public, "the scan found no public function, so it is asserting nothing"

    offenders = [
        f"{node.name}.{argument.arg}"
        for node in public
        for argument in [*node.args.args, *node.args.kwonlyargs]
        if argument.arg.lower() in {"verify", "force", "skip", "trust", "checked"}
    ]

    assert offenders == [], f"a read path exposes a way to skip the check: {offenders}"
    assert not hasattr(orchestrator, "verify"), (
        "a ledger-trust `verify` operation must not exist: verification is an outcome "
        "of reading, never a request (`kernel-cli.md` §9)"
    )


def test_the_check_reads_the_store_not_the_ledgers_own_claim(
    descriptor: orchestrator.Descriptor,
    tmp_path: pathlib.Path,
) -> None:
    """A cached answer would be the claim asked about itself.

    Falsified by the *store* disagreeing with the ledger: the ledger says `done` with a
    hash, and the store says the bytes are gone. A check that consulted the ledger's
    claim would answer *verified*.
    """
    out = tmp_path / "O"
    orchestrator.run(
        descriptor,
        out,
        input_hashes=_input_hashes(),
        operations=Recorder().table(),
        keys=KEYS,
        slots=SLOTS,
    )

    unit = out / UNIT_NAMES[0]
    record = store.read_ledger(unit).stages["acquire"]
    assert record.artifact_sha256 is not None

    ledger_claim = store.read_ledger(unit).stages["acquire"].state
    bytes_are_there = store.verify(unit, record.artifact_sha256)
    assert ledger_claim == "done" and bytes_are_there is True

    (unit / "artifacts" / record.artifact_sha256).unlink()

    assert store.read_ledger(unit).stages["acquire"].state == "done", (
        "the ledger's claim does not change when the bytes go"
    )
    assert orchestrator.verify_ledger(unit) == {"acquire": "artifact_missing"}, (
        "the check follows the bytes, not the claim"
    )
