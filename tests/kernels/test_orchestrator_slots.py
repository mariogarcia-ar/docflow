"""K1 typed slots, barriers and contained failure - `E05-04` / `S1-T09`.

The three claims this module makes, and the shape of the test that would notice if one
stopped being true:

1. **A bounded set of typed slots exists**, and a name outside it is refused rather
   than defaulted. The falsifying test is not *"`cpu` is allowed"* - that passes
   against a module that allows everything - but *"`gpus` is refused"*.
2. **A barrier releases only when every member is terminal**, and a failure releases
   nothing. The interesting case is the *partial* set, because the passing case is the
   same answer whether the release condition is `any` or `all`.
3. **Failure is contained to the unit.** The unit that failed is named against itself,
   every other unit completes, and the run reports `incomplete` rather than `complete`.

A fourth claim belongs to `E05-04`'s reasoning rather than to `FR-07`: the `gpu` bound
of one is **enforced**, not documented. It is asserted doubly - the declaration is
refused above one, and the manifest could not have reported a larger figure anyway,
because the manifest reads ledgers and a ledger carries no slot.
"""

# The same framework and shape reasons as the sibling suite: pytest's injection
# convention, a suite that must not be split from its criteria, and record shapes
# deliberately repeated rather than shared through a builder.
# pylint: disable=redefined-outer-name
# pylint: disable=too-many-lines
# pylint: disable=use-implicit-booleaness-not-comparison
# pylint: disable=duplicate-code

from __future__ import annotations

import hashlib
import json
import pathlib
from types import MappingProxyType

import pytest

from docflow.kernels import orchestrator, store
from docflow.kernels.types import Artifact, Evidence, KernelResult, Reason


def _hash_of(text: str) -> str:
    """Return the sha256 of a string, as a unit's own input hash.

    Args:
        text: The text to digest.

    Returns:
        The hexadecimal digest.

    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


UNIT_NAMES: tuple[str, ...] = ("U-0001", "U-0002")

KEYS = orchestrator.KeyContext(
    registry_hash="c41b" * 16,
    kernels=MappingProxyType(
        {
            "store": orchestrator.KernelTerms(
                kernel_version="1.0.0",
                adapter_revision="filesystem 1",
                model_revision="none",
            ),
            "ocr": orchestrator.KernelTerms(
                kernel_version="1.0.0",
                adapter_revision="docling 1",
                model_revision="layout-v1",
            ),
            "llm.local": orchestrator.KernelTerms(
                kernel_version="1.0.0",
                adapter_revision="ollama 0.31.1",
                model_revision="qwen2.5:latest",
            ),
        }
    ),
)

SLOTS = orchestrator.SLOT_BOUNDS


def _input_hashes() -> dict[str, str]:
    """Return one distinct input hash per unit.

    Returns:
        Unit name to input hash, distinct per unit so a mix-up is visible.

    """
    return {name: _hash_of(f"input for {name}") for name in UNIT_NAMES}


# --- A graph that contends for all three slots ------------------------------

#: A graph whose every stage is in a different slot, so the slot declaration is
#: exercised rather than only parsed. `acquire` is `cpu`, `read` is `gpu` (an OCR-style
#: stage) and `ask` is `remote` (a provider call).
THREE_SLOTS: MappingProxyType[str, object] = MappingProxyType(
    {
        "unit": "synthetic",
        "units": list(UNIT_NAMES),
        "stages": [
            {"name": "acquire", "kernel": "store", "op": "put", "slot": "cpu"},
            {
                "name": "read",
                "kernel": "ocr",
                "op": "run",
                "needs": ["acquire"],
                "slot": "gpu",
            },
            {
                "name": "ask",
                "kernel": "llm.local",
                "op": "ask",
                "needs": ["read"],
                "slot": "remote",
            },
        ],
    }
)


class Recorder:
    """An operation table for the three-slot graph, optionally failing one stage."""

    # The recorder is a test double whose surface is exactly what the tests reach for:
    # one factory plus one operation per kernel. More members would be surface with no
    # test behind it - the same reasoning the sibling suite records.
    # pylint: disable=too-few-public-methods

    def __init__(self, *, fail_on: str | None = None) -> None:
        """Initialize the recorder.

        Args:
            fail_on: A stage name whose operation reports a typed reason.

        """
        self.calls: list[orchestrator.StageCall] = []
        self.fail_on = fail_on

    def table(self) -> dict[tuple[str, str], orchestrator.StageOperation]:
        """Return the operation table.

        Returns:
            The table the orchestrator dispatches through.

        """
        return {
            ("store", "put"): self._generic,
            ("ocr", "run"): self._generic,
            ("llm.local", "ask"): self._generic,
        }

    def _generic(self, call: orchestrator.StageCall) -> KernelResult[Artifact]:
        """Store the call's bytes, or report the injected failure.

        Args:
            call: The dispatch call.

        Returns:
            The stored artifact, or a typed reason.

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
            call.unit_dir,
            f"{call.unit}:{call.stage.name}:{call.input_hash}".encode("utf-8"),
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
    """Provide the three-slot descriptor.

    Returns:
        The descriptor, covering two units.

    """
    return orchestrator.descriptor_from_mapping(THREE_SLOTS)


# --- Criterion 1: three typed slots, and a fourth is refused ---------------


def test_exactly_three_typed_slots_exist() -> None:
    """`cpu`, `gpu` and `remote`, and the set is asserted as a whole.

    Asserted as an equality rather than a membership, because `"cpu" in SLOT_NAMES`
    passes against a module that also accepts `tpu`.
    """
    assert frozenset({"cpu", "gpu", "remote"}) == orchestrator.SLOT_NAMES


def test_a_stage_that_names_no_slot_contends_for_cpu() -> None:
    """Not claiming a device is not a reservation, so the default is `cpu`."""
    stage = orchestrator.Stage(
        name="a", kernel="store", op="put", needs=(), params=MappingProxyType({})
    )

    assert stage.slot == "cpu", (
        "a stage with no declared slot must not land on a device slot: it would "
        "consume a bound nobody declared it against"
    )


def test_a_stage_claiming_an_unknown_slot_is_refused() -> None:
    """An unrecognised slot would be scheduled against no bound at all."""
    with pytest.raises(ValueError) as excinfo:
        orchestrator.Stage(
            name="a",
            kernel="store",
            op="put",
            needs=(),
            params=MappingProxyType({}),
            slot="gpus",
        )

    assert "not one of the typed slots" in str(excinfo.value)
    assert "gpus" in str(excinfo.value), "the refusal names the offending slot"


def test_a_descriptor_stage_claiming_an_unknown_slot_is_refused() -> None:
    """The refusal holds through the descriptor path, not only the constructor."""
    payload = {
        "unit": "u",
        "stages": [{"name": "a", "kernel": "store", "op": "put", "slot": "gpus"}],
    }

    with pytest.raises(ValueError) as excinfo:
        orchestrator.descriptor_from_mapping(payload)

    assert "gpus" in str(excinfo.value)


def test_a_non_string_slot_is_refused_by_its_own_message() -> None:
    """A number cannot be matched against the closed set, and coercing it hides that."""
    payload = {
        "unit": "u",
        "stages": [{"name": "a", "kernel": "store", "op": "put", "slot": 1}],
    }

    with pytest.raises(TypeError) as excinfo:
        orchestrator.descriptor_from_mapping(payload)

    assert "must be a string" in str(excinfo.value)


# --- Criterion 2: the bounds are per slot, and every slot is declared -------


def test_the_bounds_name_every_typed_slot() -> None:
    """A bound set is complete, so no slot silently takes a scheduler default."""
    bounds = orchestrator.SlotBounds(
        bounds=MappingProxyType({"cpu": 4, "gpu": 1, "remote": 2})
    )

    assert bounds.as_mapping() == {"cpu": 4, "gpu": 1, "remote": 2}


def test_a_bound_set_missing_a_slot_is_refused() -> None:
    """The falsifier for completeness: `cpu` and `gpu` alone must not be accepted."""
    with pytest.raises(ValueError) as excinfo:
        orchestrator.SlotBounds(bounds=MappingProxyType({"cpu": 1, "gpu": 1}))

    assert "missing" in str(excinfo.value)
    assert "remote" in str(excinfo.value)


def test_a_bound_set_naming_an_unknown_slot_is_refused() -> None:
    """A bound nothing can honour reads as a promise."""
    with pytest.raises(ValueError) as excinfo:
        orchestrator.SlotBounds(
            bounds=MappingProxyType({"cpu": 1, "gpu": 1, "remote": 1, "tpu": 1})
        )

    assert "unknown" in str(excinfo.value)


def test_a_negative_bound_is_refused() -> None:
    """A negative capacity is not a bound; treating it as zero hides an error."""
    with pytest.raises(ValueError) as excinfo:
        orchestrator.SlotBounds(
            bounds=MappingProxyType({"cpu": -1, "gpu": 1, "remote": 1})
        )

    assert "must not be negative" in str(excinfo.value)


def test_a_zero_bound_is_a_real_bound_rather_than_an_absence() -> None:
    """*This deployment has no `remote`* is stateable, and it is not the default."""
    bounds = orchestrator.SlotBounds(
        bounds=MappingProxyType({"cpu": 1, "gpu": 1, "remote": 0})
    )

    assert bounds.allows("remote") is False
    assert bounds.allows("cpu") is True


def test_the_gpu_bound_is_refused_above_one_per_device() -> None:
    """The declared simplification is enforced, not merely documented.

    `sad.md` §7.2: `gpu` is one in-flight generation per device, and the competition
    policy for two generators sharing one device's VRAM is an open decision
    (`plan-01-kernels.md` §12 #7). A larger bound would be honoured without anything
    having decided how the device is shared.
    """
    with pytest.raises(ValueError) as excinfo:
        orchestrator.SlotBounds(
            bounds=MappingProxyType({"cpu": 4, "gpu": 2, "remote": 1})
        )

    assert "one in-flight generation per device" in str(excinfo.value)


def test_the_declared_gpu_bound_is_the_permitted_one() -> None:
    """The documented value passes - so the refusal above is a bound, not a blanket."""
    bounds = orchestrator.SlotBounds(
        bounds=MappingProxyType({"cpu": 4, "gpu": 1, "remote": 1})
    )

    assert bounds.bounds["gpu"] == 1


def test_a_graph_whose_slot_has_no_capacity_is_refused_before_anything_is_written(
    descriptor: orchestrator.Descriptor, tmp_path: pathlib.Path
) -> None:
    """A run that could never proceed is named while the output tree is still empty."""
    out = tmp_path / "O"
    starved = orchestrator.SlotBounds(
        bounds=MappingProxyType({"cpu": 1, "gpu": 0, "remote": 1})
    )

    with pytest.raises(ValueError) as excinfo:
        orchestrator.run(
            descriptor,
            out,
            input_hashes=_input_hashes(),
            operations=Recorder().table(),
            keys=KEYS,
            slots=starved,
        )

    assert "no capacity above zero" in str(excinfo.value)
    assert "gpu" in str(excinfo.value)
    assert not out.exists(), "the refusal happens before the first ledger is touched"


def test_a_run_within_its_bounds_dispatches_every_stage(
    descriptor: orchestrator.Descriptor, tmp_path: pathlib.Path
) -> None:
    """The positive control: the bounds do not refuse work that fits inside them."""
    out = tmp_path / "O"

    report = orchestrator.run(
        descriptor,
        out,
        input_hashes=_input_hashes(),
        operations=Recorder().table(),
        keys=KEYS,
        slots=SLOTS,
    )

    assert len(report.dispatched) == len(UNIT_NAMES) * 3
    assert report.failed == ()
    assert report.manifest["state"] == "complete"


def test_the_slots_a_graph_contends_for_are_the_ones_it_declares(
    descriptor: orchestrator.Descriptor,
) -> None:
    """The declaration reaches the graph, so the bound is applied to real work.

    Without this, every slot test above could pass against a graph whose stages all
    defaulted to `cpu` - and the `gpu` bound would then be guarding nothing.
    """
    assert {stage.slot for stage in descriptor.graph.stages} == {
        "cpu",
        "gpu",
        "remote",
    }


# --- Criterion 3: barriers release on a set, and a partial set does not -----


def _barrier_payload() -> MappingProxyType[str, object]:
    """Build a graph whose join waits on two members of a set.

    Returns:
        The descriptor payload: two root stages, then a join needing both.

    """
    return MappingProxyType(
        {
            "unit": "synthetic",
            "units": ["U-0001"],
            "stages": [
                {"name": "ab", "kernel": "store", "op": "put"},
                {"name": "c", "kernel": "store", "op": "put"},
                {"name": "join", "kernel": "store", "op": "put", "needs": ["ab", "c"]},
            ],
        }
    )


def test_a_partial_barrier_set_does_not_release(tmp_path: pathlib.Path) -> None:
    """The join waits for **both** members; one terminal member releases nothing.

    The falsifier for `any`-semantics: a set that released on one member would dispatch
    the join here, and this test asserts the operation was never called.
    """
    out = tmp_path / "O"
    recorder = Recorder(fail_on="c")
    descriptor = orchestrator.descriptor_from_mapping(_barrier_payload())

    report = orchestrator.run(
        descriptor,
        out,
        input_hashes={"U-0001": _hash_of("u")},
        operations=recorder.table(),
        keys=KEYS,
        slots=SLOTS,
    )

    called = [call.stage.name for call in recorder.calls]
    assert "join" not in called, (
        "the barrier released on a partial set: `c` produced no artifact, so the join "
        "had one member satisfied out of two"
    )
    assert ("U-0001", "join") in report.blocked
    assert ("U-0001", "ab") in report.dispatched, "the member that did complete ran"


def test_a_failed_barrier_member_does_not_deadlock_the_join(
    tmp_path: pathlib.Path,
) -> None:
    """A failure is terminal, so the barrier is reported rather than waited on forever.

    `sad.md` §7.2: *"a failure does not deadlock the barrier."* The run finishes, the
    join is blocked, and the run's state says it did not complete - all three are the
    same fact, and a run that hung would satisfy none of them.
    """
    out = tmp_path / "O"
    descriptor = orchestrator.descriptor_from_mapping(_barrier_payload())

    report = orchestrator.run(
        descriptor,
        out,
        input_hashes={"U-0001": _hash_of("u")},
        operations=Recorder(fail_on="c").table(),
        keys=KEYS,
        slots=SLOTS,
    )

    assert report.blocked, "the join was reported, rather than left waiting"
    assert report.manifest["state"] == "incomplete"
    assert report.failed, "the unit that could not complete is named"


def test_a_complete_barrier_set_releases_exactly_once(tmp_path: pathlib.Path) -> None:
    """Every member terminal releases the join, and it is dispatched once.

    The positive control for the test above: the same graph with no failure must
    dispatch the join, or the partial-set test would pass against a barrier that never
    releases at all.
    """
    out = tmp_path / "O"
    recorder = Recorder()
    descriptor = orchestrator.descriptor_from_mapping(_barrier_payload())

    report = orchestrator.run(
        descriptor,
        out,
        input_hashes={"U-0001": _hash_of("u")},
        operations=recorder.table(),
        keys=KEYS,
        slots=SLOTS,
    )

    assert [call.stage.name for call in recorder.calls].count("join") == 1
    assert ("U-0001", "join") in report.dispatched
    assert report.failed == ()


def test_a_released_barrier_is_not_released_again_by_a_second_run(
    tmp_path: pathlib.Path,
) -> None:
    """Exactly once, across runs: the second pass finds the join terminal for its key.

    A barrier that re-released on every pass would be a stage re-run for no reason,
    which is the idempotency `E05-01` established and this issue must not break.
    """
    out = tmp_path / "O"
    descriptor = orchestrator.descriptor_from_mapping(_barrier_payload())
    recorder = Recorder()

    orchestrator.run(
        descriptor,
        out,
        input_hashes={"U-0001": _hash_of("u")},
        operations=recorder.table(),
        keys=KEYS,
        slots=SLOTS,
    )
    before = len(recorder.calls)

    second = orchestrator.run(
        descriptor,
        out,
        input_hashes={"U-0001": _hash_of("u")},
        operations=recorder.table(),
        keys=KEYS,
        slots=SLOTS,
    )

    assert len(recorder.calls) == before, "the second pass dispatched nothing"
    assert second.dispatched == ()
    assert second.failed == ()


# --- Criterion 4: failure is contained to the unit --------------------------


def test_one_unit_failing_leaves_the_other_unit_complete(
    descriptor: orchestrator.Descriptor, tmp_path: pathlib.Path
) -> None:
    """`FR-07`: one failure never aborts the run; the other units finish.

    Both units fail on the same stage name here, so the *containment* being tested is
    the propagation rather than the cause: each unit's failure stays inside its own
    ledger, and each unit is reported for its own.
    """
    out = tmp_path / "O"

    report = orchestrator.run(
        descriptor,
        out,
        input_hashes=_input_hashes(),
        operations=Recorder(fail_on="read").table(),
        keys=KEYS,
        slots=SLOTS,
    )

    for unit in UNIT_NAMES:
        ledger = store.read_ledger(out / unit)
        assert ledger.stages["acquire"].state == "done"
        assert ledger.stages["read"].state == "failed"

    assert report.manifest["state"] == "incomplete"
    assert report.manifest["totals"]["failed"] == len(UNIT_NAMES)


def test_the_failure_is_reported_against_its_own_unit_not_the_run(
    descriptor: orchestrator.Descriptor, tmp_path: pathlib.Path
) -> None:
    """`failed` names units, and the stages inside them that did not complete.

    This is what `FR-07`'s containment means to an operator: *this unit failed*, not
    *the run failed*. A report carrying a single run-level failure would lose which unit
    to fix, and neither of the assertions below could hold.
    """
    out = tmp_path / "O"

    report = orchestrator.run(
        descriptor,
        out,
        input_hashes=_input_hashes(),
        operations=Recorder(fail_on="read").table(),
        keys=KEYS,
        slots=SLOTS,
    )

    reported_units = [unit for unit, _stages in report.failed]
    assert reported_units == list(UNIT_NAMES), (
        "each failing unit is named, in dispatch order"
    )
    for _unit, stages in report.failed:
        # The stage that reported the reason **and** the work it stopped. Asserting
        # only the first would be satisfied by a report that named the symptom and
        # dropped the dependant - which is the half of the answer an operator needs to
        # know what is left to do.
        assert stages == ("read", "ask"), (
            "the failing stage and the stage it blocked are both named, in dispatch "
            f"order; got {stages}"
        )


def test_a_unit_that_completed_is_not_reported_as_failed(
    descriptor: orchestrator.Descriptor, tmp_path: pathlib.Path
) -> None:
    """The falsifier for over-reporting: a clean unit is absent from `failed`.

    Without this, a run that reported every unit would satisfy both tests above.
    """
    out = tmp_path / "O"

    report = orchestrator.run(
        descriptor,
        out,
        input_hashes=_input_hashes(),
        operations=Recorder().table(),
        keys=KEYS,
        slots=SLOTS,
    )

    assert report.failed == ()
    assert report.manifest["state"] == "complete"


def test_a_pause_that_arrives_mid_unit_does_not_report_the_unit_as_failed(
    tmp_path: pathlib.Path,
) -> None:
    """A real pause arrives **while a unit is in flight**, and that is not a failure.

    This is the case the guard around the failure measurement exists for. A control
    written before the run never enters :func:`_run_unit` at all, so it cannot reach the
    guard; the only way to reach it is a pause that lands *between two stages of a
    unit*. That is also what an operator's `pause` does - a second process writes the
    file while the run is working - so the operation here writes it, which is the same
    mechanism the surface uses rather than a test-only shortcut.

    Without the guard, the stages the pause prevented would be measured as incomplete
    and the unit reported as failed: a *pause* indistinguishable from a *crash*. The
    run's state is the second half of the same claim, and it must read ``holding``.
    """
    out = tmp_path / "O"

    class PausingRecorder(Recorder):
        """A recorder whose first operation pauses the run, as another process would."""

        # The subclass adds one operation override and nothing else; that single member
        # *is* its whole contract, which is the same reason `Recorder` carries the
        # disable.
        # pylint: disable=too-few-public-methods

        def _generic(self, call: orchestrator.StageCall) -> KernelResult[Artifact]:
            """Pause the run after the first stage completes.

            Args:
                call: The dispatch call.

            Returns:
                The stored artifact.

            """
            result = super()._generic(call)
            if len(self.calls) == 1:
                orchestrator.write_control(out, "paused")
            return result

    report = orchestrator.run(
        orchestrator.descriptor_from_mapping(THREE_SLOTS),
        out,
        input_hashes=_input_hashes(),
        operations=PausingRecorder().table(),
        keys=KEYS,
        slots=SLOTS,
    )

    assert report.held, "the pause landed between two stages of the first unit"
    assert report.failed == (), (
        "a unit held mid-flight is not a failed unit: its remaining stages were never "
        "attempted, and reporting them as incomplete makes `pause` look like a crash"
    )
    assert report.manifest["state"] == "holding", (
        "the run says it is holding, not that it is broken"
    )


def test_a_held_unit_is_not_measured_for_failure(tmp_path: pathlib.Path) -> None:
    """A pause is not a crash, and the two must not share a column.

    A held unit's stages have not been *attempted*. Reporting them as incomplete would
    make `pause` indistinguishable from a crash - the confusion `E05-02` recorded for
    the `held`/`skipped` pair, one level down.

    This is where the *reachability* limit of that claim lives, and it is stated rather
    than implied: a control that already holds means :func:`_run_unit` is never entered,
    so no unit ledger is written and there is nothing for the failure measurement to
    read. The guard is asserted as the observable it has - **no unit was driven** -
    because a filter inside the measurement would be a different implementation of the
    same outcome and cannot be distinguished from this one from outside.
    """
    out = tmp_path / "O"
    orchestrator.write_control(out, "paused")

    report = orchestrator.run(
        orchestrator.descriptor_from_mapping(THREE_SLOTS),
        out,
        input_hashes=_input_hashes(),
        operations=Recorder().table(),
        keys=KEYS,
        slots=SLOTS,
    )

    assert report.held, "the units were held"
    assert report.failed == (), "held work is not failed work"
    assert report.dispatched == (), "no unit was driven at all"


# --- The manifest's own limits ---------------------------------------------


def test_the_manifest_reports_no_slot_because_a_ledger_carries_none(
    descriptor: orchestrator.Descriptor, tmp_path: pathlib.Path
) -> None:
    """A slot is a scheduling attribute, so it is not a durable fact.

    This is a deliberate *absence*, and it is asserted rather than left implicit because
    a slot in the manifest would force `rebuild_index` to read the descriptor - which is
    the second authority that function exists to not have. The assertion names the key
    so a future addition is confronted here.
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

    manifest = json.loads(
        (out / orchestrator.MANIFEST_NAME).read_text(encoding="utf-8")
    )

    assert "slots" not in manifest, (
        "the manifest is derived from ledgers and nothing else; a slot is a descriptor "
        "attribute, so reporting it would mean reading the descriptor"
    )
    for unit_stages in manifest["stages"].values():
        for entry in unit_stages.values():
            assert set(entry) == set(
                store.StageRecord(
                    state="pending",
                    artifact_sha256=None,
                    reason_code=None,
                    cache_key=None,
                    attempts=0,
                ).as_mapping()
            ), "a stage entry carries the ledger's fields and nothing more"
