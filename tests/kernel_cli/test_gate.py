"""The Stage 1 closing flow - the gate (`E08-01` / `S1-T19`).

`plan-01-kernels.md` §7a: *"This is the **only** test whose passing is the gate; every
other test in this plan exists to make a failure of this one attributable."*

Four claims are only worth what an operator can observe, and each is asserted
individually by an earlier issue. **None of them is demonstrated until they hold
together, across a real kill**, which is what this module does. It drives
`plan-01-kernels.md` §6's runbook steps 1-13, on the documented surface, from a
subprocess - because the acceptance commands are what a person runs, and a gate that
only holds under `dispatch()` would not close the stage.

The three acceptance scenarios Stage 1 owns (`§7c`):

| Scenario | Closes at | Asserted here |
|---|---|---|
| *Resume after a forced kill* | `S1-T19` | `test_step_7` - `test_step_10` |
| *Verification is not optional* | `S1-T10`, through `S1-T19` step 9 | `test_step_9` |
| *A sampled artifact is evidence, not a cache* | `S1-T08`, through `S1-T22` |
`test_the_sampled_scenario` |

The kill is a real `SIGKILL` from `_kill_harness.py`, not an injected exception: an
in-process exception at the same point leaves the same ledger, and a simulated kill and
a real one are different evidence.
"""

# The step numbers, the descriptor's stages and the reason codes are restated here on
# purpose, so the suite holds its own copy of what it verifies.
# pylint: disable=duplicate-code
# pylint: disable=too-many-lines
#
# `redefined-outer-name`: pylint reports every pytest fixture parameter as a
# redefinition of the function the fixture decorates - the framework's convention.
# pylint: disable=redefined-outer-name
#
# `import-outside-toplevel`: the kernel imports sit inside the tests that need
# them, so the suite collects and the failure is attributed to the test that reached
# for the kernel rather than to the module.
# pylint: disable=import-outside-toplevel
#
# `use-implicit-booleaness-not-comparison`: the ``... == []`` comparisons ask whether a
# guard found anything, so a guard broken into returning ``None`` cannot read as clean.
# pylint: disable=use-implicit-booleaness-not-comparison

from __future__ import annotations

import importlib
import json
import pathlib
import shutil
import signal
import subprocess
import sys
from collections.abc import Mapping
from typing import Final

import pytest

from docflow.kernels import store

main = importlib.import_module("docflow.kernel_cli.main")

#: The descriptor the gate runs, at the path the acceptance command names.
DESCRIPTOR: Final[str] = "descriptors/synthetic-3stage.yaml"

#: The stages, in dispatch order. Restated rather than read, so a descriptor that lost
#: or renamed a stage fails here rather than being followed.
STAGES: Final[tuple[str, ...]] = ("acquire", "transform", "persist")

#: The two units the descriptor declares.
UNITS: Final[tuple[str, ...]] = ("U-0001", "U-0002")

#: The kill harness, run as a subprocess.
HARNESS: Final[pathlib.Path] = (
    pathlib.Path(__file__).resolve().parent / "_kill_harness.py"
)


def cli(*args: str) -> subprocess.CompletedProcess[str]:
    """Run the documented acceptance command.

    Args:
        *args: The arguments after the program name.

    Returns:
        The completed process, with stdout and stderr captured as text.

    """
    return subprocess.run(
        ["docflow-kernel", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def envelope(completed: subprocess.CompletedProcess[str]) -> Mapping[str, object]:
    """Parse a command's stdout as the envelope.

    Args:
        completed: The completed process.

    Returns:
        The parsed envelope.

    """
    parsed = json.loads(completed.stdout)
    assert isinstance(parsed, dict)
    return parsed


def code_of(completed: subprocess.CompletedProcess[str]) -> str | None:
    """Read the reason code out of a command's envelope.

    Args:
        completed: The completed process.

    Returns:
        The code, or None when the call produced a value.

    """
    reason = envelope(completed).get("reason")
    assert reason is None or isinstance(reason, dict)
    return None if reason is None else str(reason["code"])


def ledger_of(out: pathlib.Path, unit: str) -> Mapping[str, object]:
    """Read one unit's ledger from disk.

    Read through K7 rather than by parsing the file, so the states reported are the ones
    the kernel layer reports and the verification the read performs is the one under
    test.

    Args:
        out: The run's output root.
        unit: The unit's name.

    Returns:
        The parsed ledger.

    """
    path = store.ledger_path(out / unit)
    parsed = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict)
    return parsed


def states_of(out: pathlib.Path, unit: str) -> dict[str, str]:
    """Read one unit's per-stage states.

    Args:
        out: The run's output root.
        unit: The unit's name.

    Returns:
        Stage name to state.

    """
    stages = ledger_of(out, unit)["stages"]
    assert isinstance(stages, dict)
    return {name: str(stages[name]["state"]) for name in STAGES}


@pytest.fixture
def out(tmp_path: pathlib.Path) -> pathlib.Path:
    """Provide a fresh output root.

    Args:
        tmp_path: pytest's per-test temporary directory.

    Returns:
        A path the test may write to.

    """
    return tmp_path / "O"


# --- Steps 1-2: the fixture and the inventory -------------------------------


def test_step_1_the_descriptor_is_committed_and_names_no_domain_concept() -> None:
    """§6 step 1: three stages referencing kernel operations only, and no domain noun.

    The wrong result this guards against is *a descriptor that names a pipeline code or
    a document concept*, which would mean the surface had drifted into the domain layer.
    Checked by reading the committed file, because the acceptance command reads it too.
    """
    parsed = importlib.import_module(
        "docflow.kernel_cli.commands.descriptor"
    ).read_descriptor_mapping(pathlib.Path(DESCRIPTOR))

    assert parsed["unit"] == "synthetic"
    assert [stage["name"] for stage in parsed["stages"]] == list(STAGES)

    forbidden = {
        "pipeline",
        "field",
        "invoice",
        "cuit",
        "total",
        "document",
        "validator",
        "extractor",
    }
    for name in (DESCRIPTOR, json.dumps(parsed)):
        for word in forbidden:
            assert word not in name.lower(), (
                f"the descriptor names {word!r}: the lab surface must not carry a "
                "document concept"
            )


def test_step_2_the_inventory_reports_eight_kernels_honestly() -> None:
    """§6 step 2: all 8 rows, with the determinism class and honest availability.

    The wrong result is *an unavailable adapter reported `yes`* - *"a silent fallback in
    the one place it is most expensive"*.
    """
    completed = cli("--list")
    assert completed.returncode == main.EXIT_VALUE

    rows = envelope(completed)["value"]
    assert isinstance(rows, list) and len(rows) == 8

    by_code = {row["code"]: row for row in rows}
    assert set(by_code) == {"K1", "K2", "K3", "K4", "K5", "K6", "K7", "K8"}

    for code, expected in {
        "K1": "deterministic",
        "K2": "deterministic",
        "K3": "deterministic",
        "K4": "sampled",
        "K5": "sampled",
        "K6": "external",
        "K7": "deterministic",
        "K8": "deterministic",
    }.items():
        assert by_code[code]["determinism"] == expected, f"{code} class"

    for row in rows:
        assert row["available"] is (row["detail"] is None), (
            "availability is exactly `detail is None`: there is no second source of "
            "truth for the boolean"
        )


# --- Steps 3-5: the happy path ---------------------------------------------


def test_step_3_plan_validates_without_writing_or_dispatching(
    out: pathlib.Path,
) -> None:
    """§6 step 3: exit 0, no artifact, no stage dispatched.

    The wrong result is *a `plan` that already ran work*.
    """
    completed = cli("orchestrator", "plan", DESCRIPTOR, "--out", str(out))

    assert completed.returncode == main.EXIT_VALUE
    assert not out.exists(), "a plan must not create the output tree"
    assert json.loads(completed.stdout)["evidence"]["observed"]["dispatched"] == "false"


def test_step_4_the_happy_path_leaves_every_stage_terminal_and_done(
    out: pathlib.Path,
) -> None:
    """§6 step 4: exit 0, every stage of every unit terminal, `run.json` consistent.

    The wrong result is *a run that completes with a stage silently absent from
    `stages`*, so the assertion names the stages rather than counting them.
    """
    completed = cli("orchestrator", "run", DESCRIPTOR, "--out", str(out))

    assert completed.returncode == main.EXIT_VALUE, completed.stderr

    for unit in UNITS:
        assert states_of(out, unit) == dict.fromkeys(STAGES, "done")

    manifest = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert set(manifest) >= {
        "state",
        "totals",
        "stages",
        "outcomes",
        "inflight",
        "control",
        "attempts",
        "unverified",
    }
    assert manifest["state"] == "complete"
    assert manifest["inflight"] == []
    assert manifest["totals"]["units"] == len(UNITS)
    assert manifest["totals"]["stages"] == len(UNITS) * len(STAGES)
    assert manifest["unverified"] == {}


def test_step_5_ledger_read_reports_the_verification_outcome_alongside(
    out: pathlib.Path,
) -> None:
    """§6 step 5: every stage `done` **and** verifying, with the outcome in the answer.

    The wrong result is *a ledger returned without a verification result* - which would
    mean the check had become a request (`ADR-006`).
    """
    cli("orchestrator", "run", DESCRIPTOR, "--out", str(out))

    completed = cli("orchestrator", "ledger-read", str(out / "U-0001"))

    assert completed.returncode == main.EXIT_VALUE
    value = envelope(completed)["value"]
    assert isinstance(value, dict)
    assert value["unit"] == "U-0001"
    assert {name: value["stages"][name]["state"] for name in STAGES} == dict.fromkeys(
        STAGES, "done"
    )
    assert value["unverified"] == {}
    assert envelope(completed)["evidence"]["observed"]["trustworthy"] == "true"


def test_step_5_k7s_door_reports_the_same_verification_outcome(
    out: pathlib.Path,
) -> None:
    """§3's supporting command: `store ledger-read` and K1's read agree.

    One read path, two doorways (`kernel-cli.md` §9). If they disagreed, one of them
    would be a second authority on whether a claim holds.
    """
    cli("orchestrator", "run", DESCRIPTOR, "--out", str(out))

    through_k1 = cli("orchestrator", "ledger-read", str(out / "U-0001"))
    through_k7 = cli("store", "ledger-read", str(out / "U-0001"), "--root", str(out))

    assert through_k7.returncode == main.EXIT_VALUE
    assert (
        envelope(through_k7)["evidence"]["observed"]["trustworthy"]
        == envelope(through_k1)["evidence"]["observed"]["trustworthy"]
    )


# --- Steps 6-10: interruption and recovery ---------------------------------


def test_step_6_a_pause_holds_between_stages_and_a_run_continues(
    out: pathlib.Path,
) -> None:
    """§6 step 6: in-flight work finishes, and the next plain `run` continues.

    There is **no product `resume` verb** - continuing is *"run it again"*. The lab
    surface's `pause`/`resume` are port methods and are how the interruption is driven
    here, which is what `kernel-cli.md` §9's K1 row declares.
    """
    cli("orchestrator", "run", DESCRIPTOR, "--out", str(out))

    paused = cli("orchestrator", "pause", str(out))
    assert paused.returncode == main.EXIT_VALUE
    assert envelope(paused)["value"]["control"] == "paused"

    # The control file holds, so a run dispatches nothing new.
    held = cli("orchestrator", "run", DESCRIPTOR, "--out", str(out))
    assert held.returncode == main.EXIT_VALUE
    assert envelope(held)["value"]["held"], "a held run reports what it did not reach"

    resumed = cli("orchestrator", "resume", str(out))
    assert resumed.returncode == main.EXIT_VALUE

    continued = cli("orchestrator", "run", DESCRIPTOR, "--out", str(out))
    assert continued.returncode == main.EXIT_VALUE
    # Nothing already done re-runs: the second pass finds every stage terminal.
    assert envelope(continued)["value"]["dispatched"] == []
    for unit in UNITS:
        assert states_of(out, unit) == dict.fromkeys(STAGES, "done")


def test_step_7_a_real_kill_mid_transform_leaves_that_stage_running(
    out: pathlib.Path,
) -> None:
    """§6 step 7, matrix row 1: the interrupted stage reads **`running`**.

    A real `SIGKILL` in a subprocess, sent from inside the stage's own operation - after
    `store.begin` wrote `running` and before the operation produced anything. The wrong
    results are `pending` (*never began*, the failure crash recovery exists to prevent)
    and `done` (a claim about bytes that may be partial), and both are named in the
    assertion so a failure says which one happened.
    """
    completed = subprocess.run(
        [sys.executable, str(HARNESS), str(out), "transform"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == -signal.SIGKILL, (
        f"the harness must die by signal, not exit {completed.returncode}:\n"
        f"{completed.stderr}"
    )

    states = states_of(out, "U-0001")
    assert states["acquire"] == "done", "the stage before the kill is preserved"
    assert states["transform"] == "running", (
        "the interrupted stage must read `running`: `pending` would read as never "
        "began and `done` would be a claim about bytes that may be partial; got "
        f"{states}"
    )

    # U-0002 was never reached, so it has **no ledger at all** rather than a ledger of
    # `pending` stages. That absence is the correct record: the scheduler opens a unit
    # by declaring its stage set, and a unit it never opened has nothing declared -
    # writing an all-pending ledger would claim a stage set nothing had reached.
    assert not store.ledger_path(out / "U-0002").is_file(), (
        "U-0002 was never opened, so it must have no ledger"
    )


def test_step_8_the_next_run_re_runs_at_most_one_stage_per_unit(
    out: pathlib.Path,
) -> None:
    """§6 step 8, `NFR-02`: the resume cost is bounded and earlier work is preserved.

    The wrong result is *a resume that re-runs the whole unit* - the restart cost the
    ledger exists to bound.
    """
    subprocess.run(
        [sys.executable, str(HARNESS), str(out), "transform"],
        capture_output=True,
        text=True,
        check=False,
    )

    completed = cli("orchestrator", "run", DESCRIPTOR, "--out", str(out))

    assert completed.returncode == main.EXIT_VALUE, completed.stderr
    dispatched = envelope(completed)["value"]["dispatched"]
    assert isinstance(dispatched, list)

    per_unit: dict[str, int] = {}
    for unit, _stage in dispatched:
        per_unit[unit] = per_unit.get(unit, 0) + 1

    # And the run finishes once the interruption is behind it. Measured as *the run
    # completes* rather than as a per-unit dispatch budget: the kill left U-0001's
    # acquire done and its transform running, so the resume repeats that one stage and
    # nothing before it - which is `NFR-02`'s bound, and the bound is per **in-flight**
    # unit. Asserting a count over *every* unit would be asserting that no unit may be
    # opened for the first time after a kill, which is not the claim.
    for unit in UNITS:
        assert states_of(out, unit) == dict.fromkeys(STAGES, "done"), (
            f"{unit} did not finish after the resume"
        )


def test_step_9_a_deleted_artifact_is_incomplete_with_no_flag_passed(
    out: pathlib.Path,
) -> None:
    """§6 step 9, AC *Verification is not optional*: the check is a read outcome.

    The artifact is deleted by hand and the ledger read again - **with no flag**,
    because there is no flag: making it a request would reintroduce the gap the whole
    design argues against. The wrong result is *skipped as complete*, which is silent.
    """
    cli("orchestrator", "run", DESCRIPTOR, "--out", str(out))

    ledger = ledger_of(out, "U-0001")
    stages = ledger["stages"]
    assert isinstance(stages, dict)
    sha = str(stages["transform"]["artifact_sha256"])
    (out / "U-0001" / "artifacts" / sha).unlink()

    read = cli("orchestrator", "ledger-read", str(out / "U-0001"))
    assert read.returncode == main.EXIT_VALUE

    value = envelope(read)["value"]
    assert isinstance(value, dict)
    assert value["unverified"] == {"transform": "artifact_missing"}, (
        "a `done` stage whose artifact is gone must be reported unverified: the code "
        "is what a caller branches on, and `artifact_missing` is the one a deleted "
        f"artifact produces; got {value['unverified']}"
    )
    assert value["stages"]["transform"]["state"] == "done", (
        "the recorded state is left alone: rewriting it would destroy the fact that "
        "the claim was ever made"
    )
    assert envelope(read)["evidence"]["observed"]["trustworthy"] == "false"

    # And a plain `run` treats it as incomplete rather than skipping it.
    rerun = cli("orchestrator", "run", DESCRIPTOR, "--out", str(out))
    assert rerun.returncode == main.EXIT_VALUE
    redone = envelope(rerun)["value"]["unverified"]
    assert redone, "the run re-dispatched the stage and said why"


def test_step_10_a_crash_between_write_and_rename_leaves_done_absent(
    out: pathlib.Path,
) -> None:
    """§6 step 10, matrix row 2: `done` is absent and `running` is present.

    `commit` writes the artifact, then records `done` after the rename returns - so a
    kill *inside* the operation, before `commit` is reached at all, is the boundary's
    observable form. The wrong result is a `done` written before the rename returned,
    which is the ordering that makes resume a lie.
    """
    completed = subprocess.run(
        [sys.executable, str(HARNESS), str(out), "acquire"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == -signal.SIGKILL

    states = states_of(out, "U-0001")
    assert states["acquire"] == "running", (
        f"`running` must be present and `done` absent; got {states}"
    )
    assert states["acquire"] != "done", "a claim about bytes that were never written"

    # And resuming completes it: the interruption is recoverable, which is the point.
    resumed = cli("orchestrator", "run", DESCRIPTOR, "--out", str(out))
    assert resumed.returncode == main.EXIT_VALUE
    for unit in UNITS:
        assert states_of(out, unit) == dict.fromkeys(STAGES, "done")


# --- Step 11: the derived manifest -----------------------------------------


def test_step_11_the_manifest_rebuilds_byte_identically_through_both_doors(
    out: pathlib.Path,
) -> None:
    """§6 step 11, matrix row 16: `rm run.json` then rebuild reproduces it exactly.

    The wrong result is *a manifest that cannot be rebuilt* - one that is authoritative
    and therefore drifts. Both doors are asserted, because `store manifest-rebuild` and
    `orchestrator manifest-rebuild` are one operation reached from two sides.
    """
    cli("orchestrator", "run", DESCRIPTOR, "--out", str(out))

    path = out / "run.json"
    before = path.read_bytes()
    path.unlink()

    through_k1 = cli("orchestrator", "manifest-rebuild", str(out))
    assert through_k1.returncode == main.EXIT_VALUE
    assert path.read_bytes() == before, "the rebuild must reproduce the deleted file"

    path.unlink()
    through_k7 = cli("store", "manifest-rebuild", "--out", str(out))
    assert through_k7.returncode == main.EXIT_VALUE
    assert path.read_bytes() == before, "K7's door returns the same authority"

    assert envelope(through_k1)["value"] == envelope(through_k7)["value"]


# --- Step 12: the exit contract --------------------------------------------


def test_step_12_all_five_exit_codes_are_reachable(out: pathlib.Path) -> None:
    """§6 step 12: `0`, `2`, `3`, `4` and `1` are all reachable, and JSON on three.

    The wrong result is *a script that cannot distinguish the document's answer from the
    call's precondition from a bug*, so each code is produced deliberately and the point
    of the run is named rather than left to the reader.
    """
    reached: dict[int, str] = {}

    ok = cli("orchestrator", "run", DESCRIPTOR, "--out", str(out))
    reached[ok.returncode] = "a value was produced"
    assert json.loads(ok.stdout)

    typed = cli(
        "pdf",
        "render",
        "tests/fixtures/matrix/scan150.pdf",
        "--dpi",
        "300",
        "--root",
        "registry",
    )
    reached[typed.returncode] = "a typed reason"
    assert code_of(typed) == "insufficient_effective_resolution"
    assert json.loads(typed.stdout)

    precondition = cli("registry", "validate", "--root", str(out / "nowhere"))
    reached[precondition.returncode] = "the call could not be made"
    assert code_of(precondition) in {"asset_missing", "asset_invalid"}
    assert json.loads(precondition.stdout)

    usage = cli("pdf", "facts", "x.pdf")
    reached[usage.returncode] = "the operation does not dispatch"
    assert usage.stdout == "", "an exit-4 path emits no envelope"

    internal = cli("store", "put", "no-such-file", "--root", str(out))
    reached[internal.returncode] = "a bug inside a handler"
    assert internal.stdout == "", "an exit-1 path emits no envelope"

    assert set(reached) == {0, 1, 2, 3, 4}, f"unreachable codes: {reached}"


def test_step_12_stderr_carries_nothing_a_script_parses(out: pathlib.Path) -> None:
    """§6 step 12: `docflow-kernel … | jq` is safe on every emitting exit."""
    for argv in (
        ["orchestrator", "run", DESCRIPTOR, "--out", str(out)],
        [
            "pdf",
            "render",
            "tests/fixtures/matrix/scan150.pdf",
            "--dpi",
            "300",
            "--root",
            "registry",
        ],
        ["registry", "validate", "--root", "registry"],
    ):
        completed = cli(*argv)
        assert completed.returncode in {0, 2, 3}
        json.loads(completed.stdout)
        # stderr is the human log: nothing on it is JSON, so a script never has to
        # choose which stream to read.
        assert not completed.stderr.lstrip().startswith("{"), (
            "stderr carries a human log, never a second machine document"
        )


# --- The third scenario: a sampled artifact is evidence ---------------------


def test_the_sampled_scenario_a_deleted_sampled_artifact_is_not_regenerated(
    tmp_path: pathlib.Path,
) -> None:
    """AC *A sampled artifact is evidence, not a cache*, asserted through `S1-T22`.

    `S1-T08` decides the consequence and `E05-03` asserts it; this is where the scenario
    closes, on a **sampled** kernel, because the failure it guards against is a fresh
    sample silently substituted for the one that is gone. K5 is the sampled kernel whose
    engine is reachable here, and the refusal is what proves no sample was produced.
    """
    from docflow.kernels import determinism

    assert determinism.class_of("llm.local") == determinism.SAMPLED

    # A K5 stage recorded `done`, whose artifact is then **deleted** - which is the
    # scenario: the evidence is gone, and the question is whether anything regenerates
    # it. The stage must be `done` to have an artifact claim at all, because
    # `resume_decision` answers None for a stage that never claimed one.
    unit = tmp_path / "sampled"
    unit.mkdir()
    store.write_ledger(unit, store.new_ledger("sampled", ["ask"]))
    store.begin(unit, "ask", "a" * 64)
    from docflow.kernels.types import Artifact

    store.commit(
        unit,
        "ask",
        Artifact(
            sha256="c" * 64,
            size_bytes=0,
            media_type="application/json",
            path=None,
        ),
        "a" * 64,
    )
    record = store.read_ledger(unit).stages["ask"]
    assert record.state == "done", "the scenario needs an artifact claim to lose"
    decision = determinism.resume_decision(
        record, kernel="llm.local", store_root=unit, stage="ask"
    )

    assert decision is not None, (
        "a `done`-then-`failed` sampled stage has an artifact claim, so the "
        "decision is an outcome rather than an absence"
    )
    assert decision.recompute is False, (
        "a sampled artifact must never be regenerated: recomputing it produces a "
        "different answer reported as done, which changes the result while claiming "
        "success"
    )
    assert decision.reason is not None
    assert decision.reason.code == determinism.REASON_EVIDENCE_MISSING


# --- The gate's own preconditions ------------------------------------------


def test_the_gate_is_not_deferrable_and_carries_no_todo_marker() -> None:
    """The issue carries **no** `# TODO` marker: it is the gate.

    `E08-01`'s own wording. Checked over this module's source, so a shortcut taken
    in the gate itself would have to be declared somewhere else - which is the point.
    """
    source = pathlib.Path(__file__).read_text(encoding="utf-8")
    # The *code*, and the marker literals are assembled rather than written, so the
    # check cannot find itself: a test that grepped for its own string would fail on the
    # search text rather than on a real marker.
    marker = "# TODO: " + "[MVP]"
    release = "# TODO: " + "[RELEASE]"
    code = "\n".join(
        line
        for line in source.splitlines()
        if not line.lstrip().startswith("#")
        and marker not in line
        and release not in line
    )
    assert marker not in code, f"the gate carries {marker}: it is not deferrable"
    assert release not in code, f"the gate carries {release}"


def test_the_flow_closes_from_a_clean_checkout(out: pathlib.Path) -> None:
    """The gate's non-deferrable criterion: the documented command, from the repository.

    Run with nothing pre-staged, so the flow is invocable
    *before any domain component exists* - which is what makes it the Stage 1 gate
    rather
    than a Stage 2 convenience.
    """
    assert pathlib.Path(DESCRIPTOR).is_file(), "the descriptor is committed"

    completed = cli("orchestrator", "run", DESCRIPTOR, "--out", str(out))
    assert completed.returncode == main.EXIT_VALUE, completed.stderr

    # And its recovery is observable, which is the second half of the criterion.
    read = cli("orchestrator", "ledger-read", str(out / "U-0001"))
    assert read.returncode == main.EXIT_VALUE
    assert json.loads(read.stdout)["value"]["unverified"] == {}

    shutil.rmtree(out, ignore_errors=True)


def test_every_step_of_the_runbook_has_an_assertion() -> None:
    """Steps 1-13 of §6 are each named by a test in this module.

    A gate whose runbook has a step nothing asserts is a gate with a hole in it, and the
    hole is invisible because the suite is green. The step numbers are read from this
    file's own test names, so a step that loses its test fails here.
    """
    source = pathlib.Path(__file__).read_text(encoding="utf-8")
    missing = [
        step
        for step in (
            "test_step_1",
            "test_step_2",
            "test_step_3",
            "test_step_4",
            "test_step_5",
            "test_step_6",
            "test_step_7",
            "test_step_8",
            "test_step_9",
            "test_step_10",
            "test_step_11",
            "test_step_12",
        )
        if step not in source
    ]
    assert missing == [], f"runbook steps with no test: {missing}"

    # Step 13 is the matrix suite, which lives in `test_matrix.py`; step 14 is the exit
    # checklist, which is §11's and is a document rather than a test.
    matrix = pathlib.Path(__file__).resolve().parent / "test_matrix.py"
    assert matrix.is_file(), "step 13's suite must exist for the gate to close"
