"""Mutation harness for K1's core (``E05-01``, ``S1-T06``).

The rule from `.github/copilot-instructions.md` and `plan-01-kernels.md` §7b: a test
that guards an invariant must FAIL when the invariant is broken. A green suite proves
nothing until each guard has been shown to redden on the thing it guards, so each entry
below breaks exactly one property, runs the targeted suite, and records which tests
failed.

Four properties are the substance of this issue, and they are the ones worth mutating:

- **the manifest is derived** — `run` writes it by calling `rebuild_index`, and
  `rebuild_index` reads the ledger tree and nothing else. Breaking either half makes
  two producers disagree, which is drift by construction.
- **dispatch is keyed** — a stage is skipped only when it is terminal **for the key it
  would run under now**. Dropping the key comparison makes a changed registry hash
  invisible, which is exactly the "done and no longer correct" failure `sad.md` §5
  exists to prevent.
- **a blocked stage is not dispatched** — a need that produced no artifact must stop
  its dependants rather than let them compose a key over an absent hash.
- **the descriptor's shape is closed** — an unknown key is refused, which is what keeps
  a domain descriptor from being executed here.

Plus the E02 change this issue required: **a terminal outcome names the key it ran
under** (`prd.md` FR-08). Three mutations cover that, running the store suites.

Results are read from the JUnit XML rather than stdout, because long test names wrap and
a failed grep reads as a pass. Run with bytecode disabled:

    python -B tests/kernels/mutation_orchestrator.py

A mutation whose failure set does not contain the test that guards the property proves
nothing: either the anchor missed (`[SKIP]`) or the test never exercised the code. Both
are printed and neither is counted as proven.
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
PORT = Path("src/docflow/ports/store.py")
ADAPTER = Path("src/docflow/adapters/store.py")

ORCHESTRATOR_SUITE = "tests/kernels/test_orchestrator.py"
STORE_SUITES = "tests/kernels/test_store.py tests/adapters/test_store.py"

#: (label, file, anchor, replacement, the tests that MUST fail)
MUTATIONS: list[tuple[str, Path, str, str, set[str]]] = [
    (
        "M1: assemble the manifest instead of deriving it",
        ORCHESTRATOR,
        "    manifest = rebuild_index(out_dir)\n    # TODO: [MVP] The pretty-printed JSON is the PoC's format.",
        '    manifest = {"state": "complete", "totals": {}, "stages": {}, "outcomes": {}, "inflight": []}\n    # TODO: [MVP] The pretty-printed JSON is the PoC\'s format.',
        {"test_rebuild_index_reproduces_the_manifest_from_the_ledgers_alone"},
    ),
    (
        "M2: let rebuild_index trust an existing run.json instead of the ledgers",
        ORCHESTRATOR,
        "    verified = [read_ledger(path.parent) for path in sorted(out_dir.glob(_LEDGER_GLOB))]",
        '    manifest_path = out_dir / MANIFEST_NAME\n    if manifest_path.is_file():\n        return json.loads(manifest_path.read_text(encoding="utf-8"))\n    verified = [read_ledger(path.parent) for path in sorted(out_dir.glob(_LEDGER_GLOB))]',
        {"test_rebuild_index_ignores_an_existing_manifest_entirely"},
    ),
    (
        "M3: skip a stage on its state alone, ignoring the key",
        ORCHESTRATOR,
        "    if _already_done(recorded[stage_name], key, verified.unverified, stage_name):",
        "    if is_terminal(recorded[stage_name].state):",
        {"test_a_changed_registry_hash_makes_every_keyed_stage_new_work"},
    ),
    (
        "M3b: compare the key to itself, so any key matches",
        ORCHESTRATOR,
        "    if _already_done(recorded[stage_name], key, verified.unverified, stage_name):",
        "    if is_terminal(recorded[stage_name].state) and (\n        recorded[stage_name].cache_key == recorded[stage_name].cache_key\n    ):",
        {"test_a_changed_unit_input_makes_a_downstream_stage_new_work"},
    ),
    (
        "M4: dispatch a stage whose need produced no artifact",
        ORCHESTRATOR,
        "    upstream = _upstream_hashes(recorded, verified.unverified, stage)\n    if upstream is None:\n        tally.blocked.append((unit.name, stage_name))\n        return read_control(unit_dir.parent), verified",
        "    upstream = _upstream_hashes(recorded, verified.unverified, stage) or {}\n    if upstream is None:\n        tally.blocked.append((unit.name, stage_name))\n        return read_control(unit_dir.parent), verified",
        {"test_a_stage_whose_need_produced_no_artifact_is_not_dispatched"},
    ),
    (
        "M5: tolerate an unknown key in a stage entry",
        ORCHESTRATOR,
        '    _refuse_unknown_keys(raw, _STAGE_KEYS, "stage")',
        '    _refuse_unknown_keys(raw, frozenset(raw), "stage")',
        {
            "test_a_descriptor_carrying_an_unknown_key_is_refused[extra0]",
            "test_a_descriptor_carrying_an_unknown_key_is_refused[extra1]",
            "test_a_descriptor_carrying_an_unknown_key_is_refused[extra2]",
            "test_a_descriptor_carrying_an_unknown_key_is_refused[extra3]",
        },
    ),
    (
        "M6: drop the cache key from the ledger write on commit",
        STORE,
        '    return _with_state(unit_dir, stage, "done", artifact.sha256, None, cache_key)',
        '    return _with_state(unit_dir, stage, "done", artifact.sha256, None, None)',
        {"test_commit_records_the_artifact_hash_and_the_key_it_ran_under"},
    ),
    (
        "M7: let a terminal outcome be written without a key",
        STORE,
        "        if self.state in _TERMINAL_OUTCOME_STATES and self.cache_key is None:",
        "        if False:",
        {
            "test_a_terminal_outcome_requires_the_cache_key_it_ran_under[done]",
            "test_a_terminal_outcome_requires_the_cache_key_it_ran_under[failed]",
        },
    ),
    (
        "M8: accept the empty string as a key",
        STORE,
        '        if self.cache_key == "":',
        "        if False:",
        {"test_an_empty_string_is_refused_where_none_is_the_absence[cache_key]"},
    ),
    (
        "M9: stop writing the key to the ledger file",
        STORE,
        '                "cache_key": self.cache_key,',
        '                "cache_key": None,',
        {"test_fail_records_the_reason_code_and_the_key_it_ran_under"},
    ),
    (
        "M10: stop reading the key back from the ledger file",
        STORE,
        '            cache_key=entry["cache_key"],',
        "            cache_key=None,",
        {"test_a_done_stage_names_an_artifact_that_a_manifest_can_follow"},
    ),
    (
        "M11: drop the key from the port's commit signature",
        PORT,
        '        self, unit_dir: Path, stage: str, artifact: Artifact, cache_key: str\n    ) -> KernelResult[Ledger]:\n        """Mark a stage ``done`` against the artifact that now exists.',
        '        self, unit_dir: Path, stage: str, artifact: Artifact\n    ) -> KernelResult[Ledger]:\n        """Mark a stage ``done`` against the artifact that now exists.',
        {"test_every_signature_matches_the_port_parameter_for_parameter"},
    ),
    (
        "M12: stop forwarding the key through the adapter's begin",
        ADAPTER,
        '        return self._ledger_call(\n            kernel.begin, unit_dir, stage, "begin", cache_key=cache_key\n        )',
        '        return self._ledger_call(\n            kernel.begin, unit_dir, stage, "begin", cache_key=None\n        )',
        {"test_begin_forwards_the_key_the_stage_will_run_under"},
    ),
]


def purge_bytecode() -> None:
    """Delete every ``__pycache__`` tree under ``src`` and ``tests``.

    A stale ``.pyc`` reused by the next subprocess makes the harness report a
    one-mutation lag - a false verdict in both directions.
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
        The failed tests' names. A collection error is reported under the module's
        node name, which is asserted rather than discarded: a mutation that breaks the
        import is a mutation that landed.

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
        env={**environment},
    )
    if not report.exists():
        raise RuntimeError(
            f"pytest produced no report for {suites}:\n{completed.stdout}\n{completed.stderr}"
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

            try:
                path.write_text(
                    original.replace(anchor, replacement, 1), encoding="utf-8"
                )
                suites = ORCHESTRATOR_SUITE if path == ORCHESTRATOR else STORE_SUITES
                failed = run(suites, report)
            finally:
                path.write_text(original, encoding="utf-8")

            caught = must_fail <= failed
            unexpected = sorted(failed - must_fail)
            status = "caught" if caught else "SURVIVED"
            print(f"[{status}] {label}")
            print(f"    expected to fail: {sorted(must_fail)}")
            print(f"    actually failed:  {sorted(failed)}")
            if unexpected:
                print(f"    also failed (not required): {unexpected}")
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
