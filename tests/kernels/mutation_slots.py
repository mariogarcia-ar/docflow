"""Mutation harness for typed slots, barriers and contained failure (E05-04, S1-T09).

`plan-01-kernels.md` section 7b assigns this issue two invariants whose tests must FAIL
when broken:

- *"a partial barrier set releases when every member is terminal"* - breaking it is a
  join that starts on **one** member, which produces a result from an input that was
  never ready, and it is silent because the value looks plausible.
- *"one unit failing does not abort the run"* - breaking it is a run that stops at the
  first failing unit, which loses the accounting for every unit behind it and reports
  the failure against the run rather than against the unit.

The properties worth breaking, in the order they would hurt:

- **the barrier needs ALL its members.** `any`-semantics is the natural bug: `all()` and
  `any()` look alike, and only a test with a *partial* set can tell them apart.
- **a failure is terminal for the barrier.** A member that failed produces no artifact,
  and the dependant must be reported rather than waited on forever.
- **the failure is attributed to the unit.** A report that named the run, or that named
  a unit which completed, satisfies neither criterion.
- **a held unit is not a failed one.** A pause is not a crash, and a run that confused
  them would report a stopped job as broken.
- **the slot set is closed.** A fourth slot accepted is a bound nothing can honour.
- **`gpu` is bounded to one.** The declared simplification is enforced, not documented.

Results are read from the JUnit XML rather than stdout, because long test names wrap and
a failed grep reads as a pass. Run with bytecode disabled:

    python -B tests/kernels/mutation_slots.py

A mutation whose expected-failure set is not met proves nothing: either the anchor
missed (`[SKIP]`), the anchor appears more than once and may land in the wrong function,
or the test never exercised the code. All three are printed, and none is counted as
proven. **Verify an anchor is unique before adding it.**
"""

# The scaffolding is deliberately identical to the sibling harnesses - read the JUnit
# XML, run one mutation in a subprocess with bytecode disabled, restore the file - and
# that sameness is what makes them comparable at a glance. What differs is the mutation
# table.
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
CLI = Path("src/docflow/cli.py")

ORCHESTRATOR_SUITES = (
    "tests/kernels/test_orchestrator.py tests/kernels/test_orchestrator_slots.py"
)
CLI_SUITES = "tests/cli/test_main.py"

#: (label, file, anchor, replacement, the tests that MUST fail)
MUTATIONS: list[tuple[str, Path, str, str, set[str]]] = [
    (
        "M1: release a barrier on ANY of its members rather than all of them",
        ORCHESTRATOR,
        "        if (\n            not is_terminal(record.state)\n            or record.artifact_sha256 is None\n            or need in unverified\n        ):\n            return None",
        "        if not is_terminal(record.state) or need in unverified:\n            continue",
        {"test_a_partial_barrier_set_does_not_release"},
    ),
    (
        "M2: let a failed barrier member satisfy its dependant",
        ORCHESTRATOR,
        "        if (\n            not is_terminal(record.state)\n            or record.artifact_sha256 is None\n            or need in unverified\n        ):\n            return None",
        '        if (\n            not is_terminal(record.state)\n            or record.artifact_sha256 is None\n            or need in unverified\n        ):\n            record = store.StageRecord(\n                state=record.state,\n                artifact_sha256="0" * 64,\n                reason_code=record.reason_code,\n                cache_key=record.cache_key,\n                attempts=record.attempts,\n            )',
        {"test_a_failed_barrier_member_does_not_deadlock_the_join"},
    ),
    (
        "M3: attribute a unit's failure to the whole run instead of the unit",
        ORCHESTRATOR,
        "    if unfinished:\n        tally.failed.append((unit_name, unfinished))",
        '    if unfinished:\n        tally.failed.append(("<the-run>", unfinished))',
        {"test_the_failure_is_reported_against_its_own_unit_not_the_run"},
    ),
    (
        "M4: report every unit as failed, whether it completed or not",
        ORCHESTRATOR,
        "    unfinished = tuple(\n        name for name in graph.order if recorded[name].state not in _SUCCESSFUL_STATES\n    )",
        "    unfinished = tuple(name for name in graph.order)",
        {"test_a_unit_that_completed_is_not_reported_as_failed"},
    ),
    (
        "M5: report only the stage that reported the reason, not the work it stopped",
        ORCHESTRATOR,
        "    unfinished = tuple(\n        name for name in graph.order if recorded[name].state not in _SUCCESSFUL_STATES\n    )",
        '    unfinished = tuple(\n        name for name in graph.order if recorded[name].state == "failed"\n    )',
        {"test_the_failure_is_reported_against_its_own_unit_not_the_run"},
    ),
    (
        "M6: record a held unit as a failed one",
        ORCHESTRATOR,
        "    if not held:\n        _record_unit_failure(unit.name, graph, read_ledger(unit_dir), tally)",
        "    _record_unit_failure(unit.name, graph, read_ledger(unit_dir), tally)",
        {"test_a_pause_that_arrives_mid_unit_does_not_report_the_unit_as_failed"},
    ),
    (
        "M7: accept a slot name outside the typed set",
        ORCHESTRATOR,
        "        if self.slot not in SLOT_NAMES:",
        "        if False:",
        {"test_a_stage_claiming_an_unknown_slot_is_refused"},
    ),
    (
        "M8: drop `remote` from the typed slot set",
        ORCHESTRATOR,
        'SLOT_NAMES: Final[frozenset[str]] = frozenset({"cpu", "gpu", "remote"})',
        'SLOT_NAMES: Final[frozenset[str]] = frozenset({"cpu", "gpu"})',
        # Caught at import time: `remote` is a declared slot in the test graphs, so
        # removing it makes the descriptor a stage claims invalid. The module-level
        # collection error is the observable, and the named test would not run at all.
        {"tests.kernels.test_orchestrator_slots"},
    ),
    (
        "M9: default a stage that claims no device to the GPU slot",
        ORCHESTRATOR,
        '_SLOT_DEFAULT: Final[str] = "cpu"',
        '_SLOT_DEFAULT: Final[str] = "gpu"',
        {"test_a_stage_that_names_no_slot_contends_for_cpu"},
    ),
    (
        "M10: tolerate a bound set that omits a slot",
        ORCHESTRATOR,
        "        if unknown or missing:",
        "        if unknown:",
        {"test_a_bound_set_missing_a_slot_is_refused"},
    ),
    (
        "M11: accept a negative bound by reading it as zero",
        ORCHESTRATOR,
        "            if bound < 0:",
        "            if False:",
        {"test_a_negative_bound_is_refused"},
    ),
    (
        "M12: let the GPU bound exceed one generation per device",
        ORCHESTRATOR,
        "        if gpu > 1:",
        "        if False:",
        {"test_the_gpu_bound_is_refused_above_one_per_device"},
    ),
    (
        "M13: stop refusing a graph whose slot has no capacity at all",
        ORCHESTRATOR,
        "    if starved:",
        "    if False:",
        {
            "test_a_graph_whose_slot_has_no_capacity_is_refused_before_anything_is_written"
        },
    ),
    (
        "M14: let a zero-capacity slot read as having capacity",
        ORCHESTRATOR,
        "        return self.bounds[slot] > 0",
        "        return self.bounds[slot] >= 0",
        {"test_a_zero_bound_is_a_real_bound_rather_than_an_absence"},
    ),
    (
        "M15: stop threading the caller's bounds through the run",
        ORCHESTRATOR,
        "    validate(descriptor, input_hashes, operations, keys, slots)",
        "    validate(descriptor, input_hashes, operations, keys, SLOT_BOUNDS)",
        {
            "test_a_graph_whose_slot_has_no_capacity_is_refused_before_anything_is_written"
        },
    ),
    (
        "M16: ignore the declared CPU bound in the product surface",
        CLI,
        '        return orchestrator.SlotBounds(\n            bounds=MappingProxyType(\n                {"cpu": cpu, "gpu": 1, "remote": 1},\n            )\n        )',
        "        return orchestrator.SLOT_BOUNDS",
        {"test_run_resolves_the_cpu_slot_from_the_environment"},
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
                suites = ORCHESTRATOR_SUITES if path == ORCHESTRATOR else CLI_SUITES
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
    sys.exit(main())
