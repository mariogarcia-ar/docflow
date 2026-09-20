"""Mutation harness for the engine invariants (``my_flow.md`` I2/I3/I4/I10).

Each mutation breaks exactly one invariant in the source, runs the invariant
suite, and records which tests failed. A mutation whose failure set does not
contain the test that guards the invariant proves nothing: either the anchor
missed, or the test never exercised the code. A test that only passes when the
code is correct proves nothing (B.16) — this harness is how we prove the
converse, that each test fails when its invariant breaks.

Run with bytecode disabled, so the mutated module is actually re-read:

    python -B tests/poc_flow_v2/mutation_invariants.py
"""

from __future__ import annotations

import pathlib
import subprocess
import sys
import xml.etree.ElementTree as ET

FLOW = pathlib.Path("scripts/poc-flow-v2/flow")
SUITE = pathlib.Path("tests/poc_flow_v2/test_invariants.py")

#: (label, file, anchor, replacement, the tests that MUST fail)
MUTATIONS: list[tuple[str, pathlib.Path, str, str, set[str]]] = [
    (
        "I2: merge by raw value instead of normalized, so equal values compete",
        FLOW / "fields.py",
        "        key = candidate.normalized_value",
        "        key = candidate.raw_value",
        {"test_i2_same_normalized_value_merges_into_one_candidate"},
    ),
    (
        "I3: a vetoed candidate is treated as live, so no score compensates",
        FLOW / "fields.py",
        "        return bool(self.hard_refutations)",
        "        return False",
        {"test_i3_a_vetoed_candidate_never_wins"},
    ),
    (
        "I4: sum every PASS in a family, so two signals double-count",
        FLOW / "engine.py",
        "            best_positive[signal.family] = max(\n"
        "                best_positive.get(signal.family, 0), signal.points\n"
        "            )",
        "            best_positive[signal.family] = (\n"
        "                best_positive.get(signal.family, 0) + signal.points\n"
        "            )",
        {"test_i4_two_passes_in_one_family_score_once"},
    ),
    (
        "I10: a missing arithmetic component vetoes instead of answering UNKNOWN",
        FLOW / "validators.py",
        (
            '            "arithmetic needs subtotal, IVA and total; a component '
            'is missing",'
        ),
        "            ARITHMETIC_INCONSISTENT,",
        {"test_i10_an_incomplete_equation_is_unknown_not_fail"},
    ),
]


def _run_suite() -> tuple[int, set[str]]:
    """Run the invariant suite and return (exit code, failed test names)."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(SUITE),
            "-q",
            "--tb=no",
            "--junitxml=/tmp/mutation_invariants.xml",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    failed: set[str] = set()
    try:
        root = ET.parse("/tmp/mutation_invariants.xml").getroot()
        for case in root.iter("testcase"):
            if case.find("failure") is not None:
                failed.add(case.get("name", ""))
    except (ET.ParseError, OSError):
        pass
    return result.returncode, failed


def main() -> int:
    """Run every mutation, report whether its guard test failed, restore source."""
    print("mutation  expected failing tests  observed")
    print("-" * 60)
    all_proved = True
    for label, path, anchor, replacement, expected in MUTATIONS:
        original = path.read_text(encoding="utf-8")
        if anchor not in original:
            print(f"ANCHOR MISSING: {label}")
            all_proved = False
            continue
        mutated = original.replace(anchor, replacement, 1)
        path.write_text(mutated, encoding="utf-8")
        try:
            _, failed = _run_suite()
        finally:
            path.write_text(original, encoding="utf-8")

        proved = expected <= failed
        status = "OK" if proved else "NOT PROVED"
        if not proved:
            all_proved = False
        expected_list = ", ".join(sorted(expected))
        failed_list = ", ".join(sorted(failed))
        report = (
            f"{label}\n"
            f"    expects: {expected_list}\n"
            f"    failed:  {failed_list}\n"
            f"    {status}"
        )
        print(report)
    print("-" * 60)
    return 0 if all_proved else 1


if __name__ == "__main__":
    sys.exit(main())
