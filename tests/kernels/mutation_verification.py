"""Mutation harness for mandatory verification on every ledger read (E05-05, S1-T10).

`plan-01-kernels.md` section 7b row 4 names the invariant and its breaking shape: *"a
code path returns a ledger without verifying it; a `--verify`-shaped escape appears"*.
This harness breaks each property to show the tests in
`tests/kernels/test_orchestrator.py` say something.

The properties worth breaking, in the order they would hurt:

- **an unverified `done` stage is treated as incomplete.** Dropping that condition is
  the criterion's own wrong result: the stage is *"skipped as complete"*, and the run
  reports success over bytes that are not there.
- **the read returns the verification outcome.** A read that returned only the ledger
  would leave a caller unable to act on the absence.
- **there is one read path.** A second, unverified read is the *"internal caller's
  shortcut"* the criterion forbids.
- **a need that is `done` but unverified is not produced.** Its dependant would
  otherwise take a stale hash and compose a key over content nothing can supply.
- **the manifest verifies as it reads.** `run.json` reporting `done` without saying
  which claims the filesystem no longer supports is a manifest agreeing with a lie.

Results are read from the JUnit XML rather than stdout, because long test names wrap and
a failed grep reads as a pass. Run with bytecode disabled:

    python -B tests/kernels/mutation_verification.py

A mutation whose expected-failure set is not met proves nothing: the anchor missed
(`[SKIP]`), or it appears more than once and may land in the wrong function (`[SKIP]`).
Both are printed, and neither is counted as proven. **Verify an anchor is unique before
adding it.**
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

ORCHESTRATOR = Path("src/docflow/kernels/orchestrator.py")
SUITES = "tests/kernels/test_orchestrator.py"

#: (label, anchor, replacement, the tests that MUST fail)
MUTATIONS: list[tuple[str, str, str, set[str]]] = [
    (
        "M1: skip a stage that is done for its key, verified or not",
        "    return (\n        is_terminal(record.state)\n        and record.cache_key == key\n        and stage_name not in unverified\n    )",
        "    return (\n        is_terminal(record.state)\n        and record.cache_key == key\n    )",
        {"test_a_run_re_dispatches_a_stage_whose_artifact_was_deleted"},
    ),
    (
        "M2: verify the ledger but never consult the verdict",
        "    if _already_done(recorded[stage_name], key, verified.unverified, stage_name):",
        "    if _already_done(recorded[stage_name], key, {}, stage_name):",
        {"test_a_run_re_dispatches_a_stage_whose_artifact_was_deleted"},
    ),
    (
        "M3: return the ledger without a verification outcome",
        "    ledger = store.read_ledger(unit_dir)\n    return Verified(ledger=ledger, unverified=_unverified_stages(ledger, unit_dir))",
        "    ledger = store.read_ledger(unit_dir)\n    return Verified(ledger=ledger, unverified={})",
        {
            "test_a_ledger_read_carries_its_verification_outcome",
            "test_a_deleted_artifact_makes_its_stage_read_as_unverified",
            "test_the_manifest_reports_the_unverified_claims",
        },
    ),
    (
        "M4: ask only whether the file exists, so a truncated one looks intact",
        "            and not store.verify(unit_dir, record.artifact_sha256)",
        "            and not (unit_dir / 'artifacts' / record.artifact_sha256).is_file()",
        # Only the *truncation* case distinguishes an existence check from a hash
        # check: `.is_file()` is False for a deleted file too, so naming the
        # deleted-artifact tests here would be a citation that cannot fail.
        {"test_a_truncated_artifact_is_as_unverified_as_a_deleted_one"},
    ),
    (
        "M5: check only non-done stages, so a done claim is never questioned",
        '            if record.state == "done"',
        '            if record.state != "done"',
        {"test_a_deleted_artifact_makes_its_stage_read_as_unverified"},
    ),
    (
        "M6: let an unverified need satisfy its dependant",
        "            or need in unverified\n        ):",
        "        ):",
        {"test_a_stage_left_unverified_and_blocked_does_not_lend_its_stale_hash"},
    ),
    (
        "M7: read the manifest without verifying",
        "    verified = [read_ledger(path.parent) for path in sorted(out_dir.glob(_LEDGER_GLOB))]",
        "    verified = [Verified(ledger=store.read_ledger(path.parent), unverified={}) for path in sorted(out_dir.glob(_LEDGER_GLOB))]",
        {"test_the_manifest_reports_the_unverified_claims"},
    ),
    (
        "M8: stop reporting the unverified claims in the manifest",
        "        UNVERIFIED_KEY: unverified,",
        "        UNVERIFIED_KEY: {},",
        {"test_the_manifest_reports_the_unverified_claims"},
    ),
    (
        "M9: report the wrong code for a deleted artifact",
        '_CODE_ARTIFACT_MISSING: Final[str] = "artifact_missing"',
        '_CODE_ARTIFACT_MISSING: Final[str] = "evidence_missing"',
        {
            "test_the_unverified_code_is_the_closed_sets_artifact_missing",
            "test_a_deleted_artifact_makes_its_stage_read_as_unverified",
        },
    ),
    (
        "M10: answer the check from the ledger's own claim",
        "            and not store.verify(unit_dir, record.artifact_sha256)",
        "            and record.artifact_sha256 is None",
        {
            "test_the_check_reads_the_store_not_the_ledgers_own_claim",
            "test_a_deleted_artifact_makes_its_stage_read_as_unverified",
        },
    ),
    (
        "M11: add a second, unverified read path",
        "def read_ledger(unit_dir: Path) -> Verified:",
        'def read_ledger_unverified(unit_dir: Path) -> store.Ledger:\n    """A fast path: read without verifying."""\n    return store.read_ledger(unit_dir)\n\n\ndef read_ledger(unit_dir: Path) -> Verified:',
        {"test_the_raw_ledger_read_is_reached_only_from_the_verification_layer"},
    ),
    (
        "M12: offer a parameter that skips the check",
        "def read_ledger(unit_dir: Path) -> Verified:",
        "def read_ledger(unit_dir: Path, verify: bool = True) -> Verified:",
        {"test_the_module_offers_no_flag_shaped_way_to_skip_verification"},
    ),
    (
        "M13: add a ledger-trust `verify` operation",
        "def verify_ledger(unit_dir: Path) -> Mapping[str, str]:",
        'def verify(unit_dir: Path) -> bool:\n    """A ledger-trust verifier - the escape the artifacts forbid."""\n    return not verify_ledger(unit_dir)\n\n\ndef verify_ledger(unit_dir: Path) -> Mapping[str, str]:',
        {"test_the_module_offers_no_flag_shaped_way_to_skip_verification"},
    ),
    (
        "M14: report only the first unverified stage",
        '            for name, record in ledger.stages.items()\n            if record.state == "done"',
        '            for name, record in list(ledger.stages.items())[:1]\n            if record.state == "done"',
        {"test_the_manifest_reports_the_unverified_claims"},
    ),
    (
        "M15: stop recording which claims a run could not honour",
        "        tally.unverified.append((unit.name, stage_name))",
        "        pass",
        {"test_a_run_re_dispatches_a_stage_whose_artifact_was_deleted"},
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
            original = ORCHESTRATOR.read_text(encoding="utf-8")

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
                ORCHESTRATOR.write_text(
                    original.replace(anchor, replacement, 1), encoding="utf-8"
                )
                failed = run(report)
            finally:
                ORCHESTRATOR.write_text(original, encoding="utf-8")

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
