"""Mutation harness for the determinism classes (E05-03, S1-T08).

`plan-01-kernels.md` section 7b row 5 says the invariant **a sampled artifact is never
regenerated** must have a test that FAILS when it is broken, and that breaking it
looks like *"the stage re-runs and reports `done` with a fresh sample, changing the
result while reporting success"*. This harness shows the tests say something.

The properties worth breaking, in the order they would hurt:

- **a sampled absence is `failed`.** Turning it into `recompute=True` IS the silent
  fallback: the result changes while the ledger reports success.
- **the class is read from the producing kernel.** Collapsing the table, or defaulting
  an unknown kernel, is what makes resume behaviour depend on a guess.
- **an unrecognised class is refused.** A fall-through reaches the deterministic branch
  and regenerates something nobody classified.
- **a present artifact is never a failure.** A class that failed on a present artifact
  would fail every run.
- **`present` is K7's answer, not a second opinion.** A truncated file is not the
  artifact a claim names.

Results are read from the JUnit XML rather than stdout, because long test names wrap and
a failed grep reads as a pass. Run with bytecode disabled:

    python -B tests/kernels/mutation_determinism.py

A mutation whose expected-failure set is not met proves nothing: the anchor missed
(`[SKIP]`), the anchor appears more than once and may land in the wrong function
(`[SKIP]`), or the test never exercised the code. All three are printed, and none is
counted as proven. **Verify an anchor is unique before adding it.**
"""

# Pylint reports `duplicate-code` against the other mutation harnesses. The scaffolding
# is deliberately identical - read the JUnit XML, run one mutation in a subprocess with
# bytecode disabled, restore the file - and that sameness is what makes them comparable
# at a glance. What differs is the mutation table and the file each one touches.
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

DETERMINISM = Path("src/docflow/kernels/determinism.py")
SUITES = "tests/kernels/test_determinism.py"

#: (label, anchor, replacement, the tests that MUST fail)
MUTATIONS: list[tuple[str, str, str, set[str]]] = [
    (
        "M1: let a sampled artifact be recomputed",
        "    if determinism_class == DETERMINISTIC:\n        # The artifact is a cache: the result is a function of the key, so re-running\n        # reproduces it. This is the one class where *missing* is recoverable.",
        "    if determinism_class in CLASS_NAMES:\n        # The artifact is a cache: the result is a function of the key, so re-running\n        # reproduces it. This is the one class where *missing* is recoverable.",
        {
            "test_a_missing_sampled_or_external_artifact_fails_with_evidence_missing[external]",
            "test_a_missing_sampled_or_external_artifact_fails_with_evidence_missing[sampled]",
            "test_a_sampled_decision_is_not_the_same_decision_as_a_deterministic_one",
        },
    ),
    (
        "M2: never recompute anything, so a deterministic absence fails too",
        "    if determinism_class == DETERMINISTIC:",
        "    if False:",
        {"test_a_missing_deterministic_artifact_may_be_recomputed"},
    ),
    (
        "M3: fail a present artifact, which would fail every run",
        "    if present:\n        return None",
        '    if present:\n        return MissingEvidence(\n            determinism_class=determinism_class, recompute=False, reason=Reason(code=REASON_EVIDENCE_MISSING, message="m")\n        )',
        {"test_a_present_artifact_is_never_a_failure"},
    ),
    (
        "M4: default an unknown class instead of refusing it",
        "    if determinism_class not in CLASS_NAMES:",
        "    if False:",
        {"test_an_unknown_class_is_refused_by_the_consequence"},
    ),
    (
        "M5: default an unknown kernel to deterministic",
        "    determinism = KERNEL_CLASSES.get(kernel)\n    if determinism is None:",
        "    determinism = KERNEL_CLASSES.get(kernel, DETERMINISTIC)\n    if determinism is None:",
        {"test_an_unknown_kernel_is_refused"},
    ),
    (
        "M6: default an unknown kernel to sampled",
        "    determinism = KERNEL_CLASSES.get(kernel)\n    if determinism is None:",
        "    determinism = KERNEL_CLASSES.get(kernel, SAMPLED)\n    if determinism is None:",
        {"test_an_unknown_kernel_is_refused"},
    ),
    (
        "M7: classify every kernel the same way",
        '"orchestrator": DETERMINISTIC,',
        '"orchestrator": SAMPLED,',
        {"test_the_declared_mapping_is_the_artifact_mapping"},
    ),
    (
        "M8: drop a kernel from the table",
        '        "registry": DETERMINISTIC,\n',
        "",
        {
            "test_the_mapping_covers_every_kernel_in_the_inventory",
            "test_the_declared_mapping_is_the_artifact_mapping",
        },
    ),
    (
        "M9: add a fourth class",
        "CLASS_NAMES: Final[tuple[str, ...]] = (DETERMINISTIC, SAMPLED, EXTERNAL)",
        'CLASS_NAMES: Final[tuple[str, ...]] = (DETERMINISTIC, SAMPLED, EXTERNAL, "best_effort")',
        {
            "test_exactly_three_classes_exist",
            "test_every_class_is_used_by_at_least_one_kernel",
        },
    ),
    (
        "M10: leave a declared class unused",
        '        "llm.frontier": EXTERNAL,',
        '        "llm.frontier": SAMPLED,',
        {
            "test_the_declared_mapping_is_the_artifact_mapping",
            "test_every_class_is_used_by_at_least_one_kernel",
        },
    ),
    (
        "M11: answer presence with a second opinion instead of K7's",
        "    return store.verify(root, sha256)",
        '    return (root / "artifacts" / sha256).exists()',
        # Only a *truncated* file distinguishes the two answers: `exists()` is True
        # for a valid artifact under either implementation, so naming the delegation
        # test here would be a citation that cannot fail.
        {"test_a_truncated_artifact_is_as_absent_as_a_deleted_one"},
    ),
    (
        "M12: check a stage that never claimed an artifact",
        '    if record.state != "done" or record.artifact_sha256 is None:\n        return None',
        "    if False:\n        return None",
        {"test_a_stage_that_is_not_done_has_no_artifact_claim_to_check[running]"},
    ),
    (
        "M13: stop naming the stage in the reason",
        'f"The artifact of stage {stage!r} is missing, and the kernel that "',
        'f"The artifact of a stage is missing, and the kernel that "',
        {
            "test_a_missing_sampled_or_external_artifact_fails_with_evidence_missing[sampled]"
        },
    ),
    (
        "M14: report a code the closed set does not contain",
        'REASON_EVIDENCE_MISSING: Final[str] = "evidence_missing"',
        'REASON_EVIDENCE_MISSING: Final[str] = "artifact_missing"',
        {
            "test_the_reason_code_is_in_the_closed_set",
            "test_a_done_stage_whose_sampled_artifact_is_deleted_fails",
            "test_a_missing_sampled_or_external_artifact_fails_with_evidence_missing[external]",
            "test_a_missing_sampled_or_external_artifact_fails_with_evidence_missing[sampled]",
        },
    ),
    (
        "M15: leave a kernel resolution declares unclassified",
        '        "llm.local": SAMPLED,\n',
        "",
        {"test_the_kernels_resolution_declares_are_all_classified"},
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


def run(report: Path) -> set[str]:
    """Run the suite and return the names of the tests that failed.

    Args:
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
            *SUITES.split(),
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
            f"pytest produced no report:\n{completed.stdout}\n{completed.stderr}"
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
        for label, anchor, replacement, must_fail in MUTATIONS:
            purge_bytecode()
            original = DETERMINISM.read_text(encoding="utf-8")

            if anchor not in original:
                print(f"[SKIP] {label}: anchor not found")
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
                DETERMINISM.write_text(
                    original.replace(anchor, replacement, 1), encoding="utf-8"
                )
                failed = run(report)
            finally:
                DETERMINISM.write_text(original, encoding="utf-8")

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
