"""Mutation harness for the product surface (E06-01, S1-T18).

`plan-01-kernels.md` section 7b and the issue's criteria name four properties, and this
harness breaks each one to show the tests in `tests/cli/test_main.py` say something.

The properties worth breaking, in the order they would hurt:

- **`stop` with no id stops nothing.** The command an operator reaches for when unsure
  must be the one that cannot destroy anything (`FR-02`). A `--force` that became a
  general kill is the worst mutation here.
- **`run` is idempotent, and a plain `run` is the only way to resume.** Dispatching
  terminal work again is the restart cost the ledger exists to bound; a `resume` verb
  would be a second recovery path the artifacts forbid.
- **precedence is CLI -> environment -> `.env` -> default**, and `--force` is never
  settable by environment - refused at the resolution step rather than after reading it.
- **two surfaces, never crossed.** `docflow` never imports `docflow-kernel`, in either
  direction.

Results are read from the JUnit XML rather than stdout, because long test names wrap and
a failed grep reads as a pass. Run with bytecode disabled:

    python -B tests/cli/mutation_cli.py

A mutation whose expected-failure set is not met proves nothing: the anchor missed
(`[SKIP]`), or it appears more than once and may land in the wrong function (`[SKIP]`).
Both are printed, and neither is counted as proven. **Verify an anchor is unique before
adding it.**
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

CLI = Path("src/docflow/cli.py")
SUITES = "tests/cli/test_main.py"

#: (label, anchor, replacement, the tests that MUST fail)
MUTATIONS: list[tuple[str, str, str, set[str]]] = [
    (
        "M1: let a bare `stop` kill everything",
        "    if not positionals:\n        return _report_running(root, force=force)",
        "    if not positionals and not force:\n        return _report_running(root, force=force)",
        {"test_stop_force_with_no_arguments_still_stops_nothing"},
    ),
    (
        "M2: report a bare `stop` but write the control anyway",
        '    for job in running:\n        lines.append(f"  {job.job_id}  {job.descriptor}  pid {job.pid}")',
        '    for job in running:\n        orchestrator.write_control(pathlib.Path(job.out_dir), "stopped")\n        lines.append(f"  {job.job_id}  {job.descriptor}  pid {job.pid}")',
        {"test_stop_with_no_arguments_reports_and_stops_nothing"},
    ),
    (
        "M3: signal a process that is already gone",
        "    if not _alive(job.pid):",
        "    if False:",
        {"test_a_forced_stop_does_not_signal_a_process_that_is_gone"},
    ),
    (
        "M4: mark activity from inflight alone, not the run state",
        '    return manifest["state"] != "complete"',
        '    return bool(manifest["inflight"])',
        {"test_a_run_paused_before_its_first_stage_is_still_reported_as_active"},
    ),
    (
        "M5: re-dispatch work that is already terminal",
        "    report = orchestrator.run(",
        '    orchestrator.write_control(out_dir, "running")\n    report = orchestrator.run(',
        {"test_a_run_asked_to_hold_dispatches_nothing_and_says_so"},
    ),
    (
        "M6: derive the job id from the raw path, so `out` and `./out` differ",
        "    resolved = out_dir.expanduser().resolve()",
        "    resolved = out_dir",
        {"test_the_job_id_is_derived_from_the_resolved_root"},
    ),
    (
        "M7: drop the environment layer from the precedence chain",
        '    from_environment = environment.get(f"{_ENV_PREFIX}{flag.upper()}")\n    if from_environment is not None and from_environment != "":\n        return from_environment',
        '    from_environment = None\n    if from_environment is not None and from_environment != "":\n        return from_environment',
        {"test_precedence_is_cli_then_environment_then_dotenv_then_default"},
    ),
    (
        "M8: put the `.env` layer above the environment",
        '    from_environment = environment.get(f"{_ENV_PREFIX}{flag.upper()}")',
        '    from_environment = (dotenv or {}).get(f"{_ENV_PREFIX}{flag.upper()}")',
        {"test_precedence_is_cli_then_environment_then_dotenv_then_default"},
    ),
    (
        "M9: put the default above the CLI flag",
        "    if cli_value is not None:\n        return cli_value",
        "    if False:\n        return cli_value",
        {"test_precedence_is_cli_then_environment_then_dotenv_then_default"},
    ),
    (
        "M10: let `--force` be settable by environment",
        "    if flag in NEVER_FROM_ENVIRONMENT:",
        "    if False:",
        {"test_a_flag_that_is_never_settable_by_environment_is_refused"},
    ),
    (
        "M11: treat an empty flag value as an absence",
        "    if cli_value is not None:\n        return cli_value",
        "    if cli_value:\n        return cli_value",
        {"test_an_empty_flag_value_is_a_value_not_an_absence"},
    ),
    (
        "M12: substitute a default output root instead of reporting none",
        '    if resolved_out is None:\n        raise UsageError("run needs an output root: --out <dir> or DOCFLOW_OUT")',
        '    if resolved_out is None:\n        resolved_out = "out"',
        {"test_run_without_an_output_root_is_a_usage_error"},
    ),
    (
        "M13: report an internal error as a usage error",
        "    return EXIT_INTERNAL\n",
        "    return EXIT_USAGE\n",
        {"test_main_returns_an_internal_error_for_a_bug_and_never_a_usage_error"},
    ),
    (
        "M14: let the lab surface into the product module",
        "from docflow.kernels import orchestrator, store",
        "from docflow.kernel_cli import main as lab\nfrom docflow.kernels import orchestrator, store",
        {"test_the_product_surface_never_imports_the_lab_surface"},
    ),
    (
        "M15: accept a document-concept flag",
        '        rest, values=("out", "jobs", "slots", "descriptor"), booleans=()',
        '        rest, values=("out", "jobs", "slots", "descriptor"), booleans=("pipeline",)',
        {"test_no_verb_and_no_flag_names_a_document_concept"},
    ),
    (
        "M16: put the job file after the run instead of before it",
        "    write_job(out_dir, job)",
        "    pass",
        {"test_run_before_the_first_stage_records_the_job"},
    ),
    (
        "M17: hand a stage a stand-in artifact for a source it cannot produce",
        '        source = call.stage.params.get("source", "generated")\n        if source != "generated":',
        '        source = call.stage.params.get("source", "generated")\n        if False:',
        {"test_the_operations_table_refuses_a_source_it_cannot_produce"},
    ),
    (
        "M18: skip a job that cannot be read by reporting it as absent from discovery",
        "            jobs.append(read_job(candidate))\n        except (FileNotFoundError, KeyError, ValueError):\n            continue",
        "            jobs.append(read_job(candidate))\n        except Exception:\n            raise",
        {"test_discovery_ignores_directories_that_hold_no_job"},
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
            original = CLI.read_text(encoding="utf-8")

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
                CLI.write_text(
                    original.replace(anchor, replacement, 1), encoding="utf-8"
                )
                failed = run(report)
            finally:
                CLI.write_text(original, encoding="utf-8")

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
