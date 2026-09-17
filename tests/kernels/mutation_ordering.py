"""Mutation harness for the durable ordering and the control (E05-02, S1-T07).

`plan-01-kernels.md` section 7b row 3 says the invariant *"`running` is written
**before** the work starts"* must have a test that FAILS when it is broken, and that
breaking it looks like *"the scheduler writes state only on completion and a killed
stage reports as never having run"*. This harness is what establishes that the tests in
`tests/kernels/test_orchestrator.py` say something.

The properties worth breaking, in the order they would hurt:

- **`begin` is called before the operation.** Moving it after the dispatch, or dropping
  it, makes a killed stage read as *never began*.
- **the ledger is read from inside the operation** is the only place the ordering is
  observable, so the tests that do it are the ones these mutations must redden.
- **the control is polled at every checkpoint.** Dropping the per-stage read makes
  `pause` land at a unit boundary, indistinguishable from *let the job finish*.
- **a held run is not reported complete.** Reading *no unfinished units* as *finished*
  is a `done` claim about work that never happened, one level up.
- **the attempt count is derived, not defaulted.** A count that does not grow makes a
  retry loop invisible, and `kernel-cli.md` section 7's prohibition is enforceable only
  if the pattern can be seen.

Results are read from the JUnit XML rather than stdout, because long test names wrap and
a failed grep reads as a pass. Run with bytecode disabled:

    python -B tests/kernels/mutation_ordering.py

A mutation whose expected-failure set is not met proves nothing: either the anchor
missed (`[SKIP]`), the anchor appears more than once and may land in the wrong function,
or the test never exercised the code. All three are printed, and none is counted as
proven. **Verify an anchor is unique before adding it.**
"""

# Pylint reports `duplicate-code` against the other mutation harnesses. The scaffolding
# is deliberately identical - read the JUnit XML, run one mutation in a subprocess with
# bytecode disabled, restore the file - and that sameness is what makes them comparable
# at a glance. What differs is the mutation table and the files each one touches.
# pylint: disable=duplicate-code
# An anchor is a literal fragment of the source it mutates, so it cannot be wrapped
# without changing what it matches. The line ceiling does not apply to them.
# pylint: disable=line-too-long

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ORCHESTRATOR = Path("src/docflow/kernels/orchestrator.py")
STORE = Path("src/docflow/kernels/store.py")

ORCHESTRATOR_SUITES = "tests/kernels/test_orchestrator.py"
STORE_SUITES = "tests/kernels/test_store.py tests/adapters/test_store.py"

#: (label, file, anchor, replacement, the tests that MUST fail)
MUTATIONS: list[tuple[str, Path, str, str, set[str]]] = [
    (
        "M1: write the state only after the work",
        ORCHESTRATOR,
        "    store.begin(unit_dir, stage_name, call.cache_key)\n\n    result = operation(call)",
        "    result = operation(call)\n\n    store.begin(unit_dir, stage_name, call.cache_key)",
        {"test_the_ledger_reads_running_from_inside_the_operation"},
    ),
    (
        "M2: never write `running` at all",
        ORCHESTRATOR,
        "    store.begin(unit_dir, stage_name, call.cache_key)\n\n    result = operation(call)",
        "    result = operation(call)",
        {"test_the_ledger_reads_running_from_inside_the_operation"},
    ),
    (
        "M3: hand commit something that is not the stored artifact",
        ORCHESTRATOR,
        "        store.commit(unit_dir, stage_name, result.value, call.cache_key)",
        "        store.commit(unit_dir, stage_name, result.value.sha256, call.cache_key)  # type: ignore[arg-type]",
        {
            "test_a_failure_is_recorded_as_failed_and_not_committed",
            "test_a_three_stage_graph_runs_over_n_units",
        },
    ),
    (
        "M4: poll the control only between units, not between stages",
        ORCHESTRATOR,
        "    for stage_name in graph.order:\n        if control.holds:",
        "    for stage_name in graph.order:\n        if False:",
        {"test_a_pause_lands_at_a_stage_boundary_not_a_unit_boundary"},
    ),
    (
        "M5: read the control only after the first unit",
        ORCHESTRATOR,
        "    control = read_control(out_dir)\n    for unit_name in descriptor.units:",
        '    control = Control(state="running")\n    for unit_name in descriptor.units:',
        {"test_a_paused_run_dispatches_nothing_and_reports_what_it_held"},
    ),
    (
        "M6: report a held run as complete",
        ORCHESTRATOR,
        "    if not inflight:\n        return _RUN_COMPLETE\n\n    return _RUN_HOLDING if read_control(out_dir).holds else _RUN_INCOMPLETE",
        "    if not inflight:\n        return _RUN_COMPLETE\n\n    return _RUN_COMPLETE",
        {"test_a_run_paused_with_work_half_done_reports_holding"},
    ),
    (
        "M6b: report a paused partial run as incomplete",
        ORCHESTRATOR,
        "    if not inflight:\n        return _RUN_COMPLETE\n\n    return _RUN_HOLDING if read_control(out_dir).holds else _RUN_INCOMPLETE",
        "    if not inflight:\n        return _RUN_COMPLETE\n\n    return _RUN_INCOMPLETE",
        {"test_a_run_paused_with_work_half_done_reports_holding"},
    ),
    (
        "M7: treat an empty ledger tree as a finished run",
        ORCHESTRATOR,
        "    if units == 0:\n        return _RUN_HOLDING if read_control(out_dir).holds else _RUN_INCOMPLETE",
        "    if units == 0:\n        return _RUN_COMPLETE",
        {"test_a_run_held_before_its_first_unit_is_not_reported_complete"},
    ),
    (
        "M8: read an unrecognised control as carry-on",
        ORCHESTRATOR,
        "        if self.state not in CONTROL_STATES:",
        "        if False:",
        {"test_an_unrecognised_control_state_is_refused"},
    ),
    (
        "M9: treat `stopped` as though it did not hold",
        ORCHESTRATOR,
        'HOLDING_CONTROLS: Final[frozenset[str]] = frozenset({"paused", "stopped"})',
        'HOLDING_CONTROLS: Final[frozenset[str]] = frozenset({"paused"})',
        {"test_a_stopped_control_holds_at_the_same_checkpoint"},
    ),
    (
        "M10: conflate held work with skipped work",
        ORCHESTRATOR,
        '            tally.held.append(f"{unit.name}:{stage_name}")',
        "            tally.skipped.append((unit.name, stage_name))",
        {"test_a_pause_lands_at_a_stage_boundary_not_a_unit_boundary"},
    ),
    (
        "M11: do not count the attempt `running` opens",
        STORE,
        '    if state == "running":\n        return previous.attempts + 1',
        '    if state == "running":\n        return previous.attempts',
        {"test_the_attempt_count_grows_with_each_write_that_is_an_attempt"},
    ),
    (
        "M12: count `done` as a second attempt",
        STORE,
        '    if state in _ATTEMPT_OUTCOMES and previous.state != "running":\n        return previous.attempts + 1',
        "    if state in _ATTEMPT_OUTCOMES:\n        return previous.attempts + 1",
        {"test_the_attempt_count_grows_with_each_write_that_is_an_attempt"},
    ),
    (
        "M13: let a run state claim it was never run",
        STORE,
        "        if self.state in _ATTEMPTED_STATES and self.attempts == 0:",
        "        if False:",
        {"test_a_hand_edited_ledger_is_rejected_on_read[corruption6]"},
    ),
    (
        "M14: stop carrying the attempt count through the ledger file",
        STORE,
        '                "attempts": self.attempts,',
        '                "attempts": 0,',
        {"test_a_second_run_of_the_same_stage_is_counted"},
    ),
]


def purge_bytecode() -> None:
    """Delete every `__pycache__` tree under `src` and `tests`.

    A stale `.pyc` reused by the next subprocess makes the harness report a
    one-mutation lag, which is a false verdict in both directions.
    """
    for root in (Path("src"), Path("tests")):
        for cache in root.rglob("__pycache__"):
            shutil.rmtree(cache, ignore_errors=True)


def run(suites: str, report: Path) -> set[str]:
    """Run a suite and return the names of the tests that failed.

    Args:
        suites: The paths to pass to pytest.
        report: Where to write the JUnit XML.

    Returns:
        The failed tests' names, including a collection error under its module node.

    """
    environment = {
        "PYTHONDONTWRITEBYTECODE": "1",
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
    }
    completed = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "pytest",
            *suites.split(),
            "-q",
            f"--junit-xml={report}",
            "-p",
            "no:cacheprovider",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    if not report.exists():
        raise RuntimeError(
            f"pytest produced no report for {suites}:\n{completed.stdout}\n"
            f"{completed.stderr}"
        )

    tree = ET.parse(report)
    return {
        str(node.get("name"))
        for node in tree.iter("testcase")
        if node.find("failure") is not None or node.find("error") is not None
    }


def main() -> int:
    """Run every mutation, restore the source, and report which ones were caught.

    Returns:
        0 when every mutation is caught, 1 otherwise.

    """
    survivors: list[str] = []
    with tempfile.TemporaryDirectory() as directory:
        report = Path(directory) / "report.xml"
        for label, path, anchor, replacement, must_fail in MUTATIONS:
            purge_bytecode()
            original = path.read_text(encoding="utf-8")

            if anchor not in original:
                print(f"[SKIP] {label}: anchor not found in {path}")
                survivors.append(label)
                continue
            if anchor == replacement:
                print(f"[SKIP] {label}: anchor and replacement are identical")
                survivors.append(label)
                continue
            if original.count(anchor) > 1:
                print(
                    f"[SKIP] {label}: anchor appears {original.count(anchor)} times, "
                    "so it may land in the wrong function"
                )
                survivors.append(label)
                continue

            try:
                path.write_text(
                    original.replace(anchor, replacement, 1), encoding="utf-8"
                )
                suites = ORCHESTRATOR_SUITES if path == ORCHESTRATOR else STORE_SUITES
                failed = run(suites, report)
            finally:
                path.write_text(original, encoding="utf-8")

            caught = must_fail <= failed
            print(f"[{'caught' if caught else 'SURVIVED'}] {label}")
            print(f"    expected to fail: {sorted(must_fail)}")
            print(f"    actually failed:  {sorted(failed)}")
            if not caught:
                survivors.append(label)

    purge_bytecode()
    print()
    if survivors:
        print(f"{len(survivors)} of {len(MUTATIONS)} mutations SURVIVED:")
        for label in survivors:
            print(f"  - {label}")
        return 1

    print(f"All {len(MUTATIONS)} mutations caught.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
