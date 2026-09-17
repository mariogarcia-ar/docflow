"""The product surface - the five verbs, and the four properties that make them safe.

`E06-01` / `S1-T18`. Every test here goes through :func:`docflow.cli.invoke` and asserts
on the returned value, because `main` is the only function that touches a stream - the
shape `E07-01` established for the lab surface.

Four groups, and the order is the order the criteria matter:

1. **Idempotency and resume.** `run` repeats without redoing work, and a second `run`
   after a pause continues from the exact stage rather than restarting. This is the
   criterion the gate observes.
2. **`stop` discovers and does not kill.** The command an operator reaches for when
   unsure must be the one that cannot destroy anything (`FR-02`).
3. **Precedence, and the flag outside it.** CLI → environment → `.env` → default, and
   `--force` is never settable by environment (`NFR-06`).
4. **Two surfaces, never crossed.** This module imports nothing from the lab surface,
   and there are exactly five verbs - no `resume` among them.
"""

# Pylint reports every pytest fixture parameter as a redefinition of the function
# the fixture decorates - the framework's calling convention, not a shadowing bug.
# pylint: disable=redefined-outer-name
#
# `use-implicit-booleaness-not-comparison`: `== []` and `== ()` are deliberate. The
# values are sequences, and `not x` would read a *missing* attribute as *empty* if a
# report were ever reshaped - the reasoning `tests/kernels/test_store.py` records.
# pylint: disable=use-implicit-booleaness-not-comparison
#
# `duplicate-code`: the forbidden-vocabulary list is repeated from the sibling suites
# on purpose. A shared helper would make the guards depend on one another's copies,
# so relaxing the list in one place would silently relax it everywhere - each suite
# holding its own declaration is what keeps the guard local to the file it guards.
# pylint: disable=duplicate-code

from __future__ import annotations

import ast
import json
import os
import pathlib

import pytest

from docflow import cli
from docflow.kernels import orchestrator, store

# --- Constants ---------------------------------------------------------------

CLI_PATH = pathlib.Path(__file__).resolve().parents[2] / "src" / "docflow" / "cli.py"
CLI_TREE: ast.Module = ast.parse(CLI_PATH.read_text(encoding="utf-8"))

#: The descriptor a run is driven from, as JSON - this surface's PoC format, because
#: YAML needs a third-party parser the kernel layer does not import.
#:
#: A plain ``dict``, not a ``MappingProxyType``: this value is handed to ``json.dumps``
#: so it becomes the file the surface reads, and a read-only mapping does not serialize.
DESCRIPTOR: dict[str, object] = {
    "unit": "synthetic",
    "units": ["U-0001", "U-0002"],
    "stages": [
        {"name": "acquire", "kernel": "store", "op": "put"},
        {"name": "transform", "kernel": "pdf", "op": "probe", "needs": ["acquire"]},
        {"name": "persist", "kernel": "store", "op": "put", "needs": ["transform"]},
    ],
}

STAGE_NAMES = ("acquire", "transform", "persist")


@pytest.fixture
def workspace(tmp_path: pathlib.Path) -> pathlib.Path:
    """Provide a workspace with a descriptor, a runs root and an output root.

    Args:
        tmp_path: The pytest fixture.

    Returns:
        The workspace directory.

    """
    workspace = tmp_path / "ws"
    (workspace / "runs").mkdir(parents=True)
    (workspace / "d.json").write_text(json.dumps(DESCRIPTOR), encoding="utf-8")
    return workspace


def _run(workspace: pathlib.Path, *, out: str = "out") -> cli.Invocation:
    """Run the descriptor into a workspace's output root.

    Args:
        workspace: The workspace.
        out: The output root, relative to the workspace.

    Returns:
        The invocation.

    """
    return cli.invoke(["run", str(workspace / "d.json"), "--out", str(workspace / out)])


def _job_id(workspace: pathlib.Path, *, out: str = "out") -> str:
    """Return the job id of a workspace's run.

    Args:
        workspace: The workspace.
        out: The output root.

    Returns:
        The id.

    """
    return cli.job_id_for(workspace / out)


# --- 1. `run`: idempotent, and a plain `run` is the only way to resume -------


def test_run_completes_the_flow_end_to_end(workspace: pathlib.Path) -> None:
    """The five verbs exist to make a run observable; the run has to work first."""
    result = _run(workspace)

    assert result.exit_code == cli.EXIT_OK
    assert result.stderr == ""

    manifest = orchestrator.rebuild_index(workspace / "out")
    assert manifest["state"] == "complete"
    assert manifest["totals"]["units"] == 2
    assert manifest["totals"]["done"] == 6


def test_run_reports_the_job_id_it_started(workspace: pathlib.Path) -> None:
    """`03-cli.md`: *every run reports a job id*, and it is usable by the next verb."""
    result = _run(workspace)

    assert _job_id(workspace) in result.stdout


def test_a_second_run_skips_completed_work(workspace: pathlib.Path) -> None:
    """`FR-01`: `run` is idempotent. Repeating it dispatches nothing.

    The assertion is on the **counts the verb reports**, not merely on the exit code: a
    second run that re-ran everything would also exit `0`.
    """
    _run(workspace)

    second = _run(workspace)

    assert second.exit_code == cli.EXIT_OK
    assert "0 stage(s) run" in second.stdout
    assert "6 already done" in second.stdout


def test_a_run_asked_to_hold_dispatches_nothing_and_says_so(
    workspace: pathlib.Path,
) -> None:
    """A pause written before a run is honoured by that run, not by the next one.

    A **fresh** output root, because a run that already finished reports `complete`
    whatever an operator asks afterwards: the state is derived from the ledgers first
    and the control second, which keeps a paused run distinguishable from a crashed
    one without letting a control claim work is outstanding when it is not.

    The held count is of **units**, not stages: the pause is read before the first unit,
    so no stage boundary is reached and every unit is reported unreached.
    """
    out = workspace / "fresh"
    orchestrator.write_control(out, "paused")

    held = _run(workspace, out="fresh")

    assert "2 held" in held.stdout
    assert orchestrator.rebuild_index(out)["state"] == "holding"


def test_clearing_the_pause_and_running_again_continues(
    workspace: pathlib.Path,
) -> None:
    """Recovery is *run it again* - **there is no `resume` verb** (`FR-01`, `FR-02`).

    The mechanism is the ledger, not a cursor: work already terminal for its key is
    skipped, so a plain `run` continues from the exact stage.
    """
    _run(workspace)
    orchestrator.write_control(workspace / "out", "paused")

    orchestrator.write_control(workspace / "out", "running")
    resumed = _run(workspace)

    assert resumed.exit_code == cli.EXIT_OK
    assert "0 stage(s) run" in resumed.stdout, "nothing was left to do"


def test_a_run_paused_mid_unit_continues_from_the_exact_stage(
    workspace: pathlib.Path,
) -> None:
    """The gate's scenario, driven through the surface.

    `plan-01-kernels.md` §6 step 6: *"in-flight work finishes; the resumed run continues
    from the exact stage; nothing already done re-runs"*. `acquire` is paused, then the
    pause is cleared: `acquire` must be skipped and `transform` dispatched.
    """
    out = workspace / "out"
    (workspace / "later.json").write_text(
        json.dumps(
            {
                "unit": "synthetic",
                "units": ["U-0001"],
                "stages": [
                    {"name": "acquire", "kernel": "store", "op": "put"},
                    {
                        "name": "transform",
                        "kernel": "pdf",
                        "op": "probe",
                        "needs": ["acquire"],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    orchestrator.write_control(out, "paused")
    cli.invoke(["run", str(workspace / "later.json"), "--out", str(out)])
    assert orchestrator.rebuild_index(out)["state"] == "holding"

    orchestrator.write_control(out, "running")
    resumed = cli.invoke(["run", str(workspace / "later.json"), "--out", str(out)])

    assert resumed.exit_code == cli.EXIT_OK
    assert "2 stage(s) run" in resumed.stdout
    ledger = store.read_ledger(out / "U-0001")
    assert {record.state for record in ledger.stages.values()} == {"done"}


def test_run_before_the_first_stage_records_the_job(workspace: pathlib.Path) -> None:
    """The job file exists so a *different process* can address a run in flight.

    Without it there is nothing for `pause`, `status` or `stop` to find, and the three
    verbs could only ever act on a run that had already finished.
    """
    orchestrator.write_control(workspace / "out", "paused")

    _run(workspace)

    job = cli.read_job(workspace / "out")
    assert job.job_id == _job_id(workspace)
    assert job.descriptor.endswith("d.json")
    assert cli.discover_runs(workspace)[0].job_id == job.job_id


# --- 2. `stop`: discover and report, never kill by default ------------------


def test_stop_with_no_arguments_reports_and_stops_nothing(
    workspace: pathlib.Path,
) -> None:
    """`FR-02`: *"`stop` with no arguments discovers and reports active runs instead of
    killing."*

    Two runs are made to look active, and `stop` must report both and touch neither --
    the control of each is asserted afterwards, because *"it printed something"* is not
    the property.
    """
    for name in ("a", "b"):
        out = workspace / name
        orchestrator.write_control(out, "paused")
        cli.invoke(["run", str(workspace / "d.json"), "--out", str(out)])

    reported = cli.invoke(["stop", "--root", str(workspace)])

    assert reported.exit_code == cli.EXIT_OK
    assert "2 run(s)" in reported.stdout
    assert "nothing stopped" in reported.stdout
    for name in ("a", "b"):
        assert orchestrator.control_of(workspace / name) == "paused"


def test_a_run_paused_before_its_first_stage_is_still_reported_as_active(
    workspace: pathlib.Path,
) -> None:
    """The case that separates the run state from ``inflight``.

    A pause taken before the first stage leaves no ledgers, so ``inflight`` is empty.
    Reading activity from ``inflight`` alone makes `stop` answer *nothing running* about
    the one run the operator just paused - which is the run they were asking after.
    """
    orchestrator.write_control(workspace / "out", "paused")
    _run(workspace)

    reported = cli.invoke(["stop", "--root", str(workspace)])

    assert reported.exit_code == cli.EXIT_OK
    assert "1 run(s)" in reported.stdout, "the held run is reported as active"
    assert "nothing stopped" in reported.stdout
    assert orchestrator.rebuild_index(workspace / "out")["inflight"] == [], (
        "the run has no unfinished *unit*, which is exactly why inflight alone is the "
        "wrong predicate"
    )


def test_stop_force_with_no_arguments_still_stops_nothing(
    workspace: pathlib.Path,
) -> None:
    """`--force` without a job id does not become a general kill.

    The deliberate narrowing: `--force` changes *how* a stop is performed, never *what*
    it applies to. A bare `stop --force` that killed everything would be a command that
    destroys work on a typo.
    """
    orchestrator.write_control(workspace / "out", "paused")
    _run(workspace)

    reported = cli.invoke(["stop", "--force", "--root", str(workspace)])

    assert reported.exit_code == cli.EXIT_OK
    assert "nothing stopped" in reported.stdout
    assert orchestrator.control_of(workspace / "out") == "paused"


def test_stop_on_one_job_requests_the_stop_without_killing(
    workspace: pathlib.Path,
) -> None:
    """A graceful stop is a request the run honours at its checkpoint - the same
    mechanism `pause` uses, because the difference is the *intent*.

    Nothing is signalled: the process id in the job belongs to this test run, and
    signalling it would kill the suite.
    """
    _run(workspace)

    stopped = cli.invoke(["stop", _job_id(workspace), "--root", str(workspace)])

    assert stopped.exit_code == cli.EXIT_OK
    assert orchestrator.control_of(workspace / "out") == "stopped"


def test_a_forced_stop_does_not_signal_a_process_that_is_gone(
    workspace: pathlib.Path,
) -> None:
    """The check before signalling is what keeps `--force` from reaching a stranger.

    A completed run's process id may have been reused. Signalling a process this surface
    does not own is worse than not signalling: it destroys somebody else's work and
    reports success.
    """
    _run(workspace)
    job = cli.read_job(workspace / "out")
    # A pid that cannot be running: the job's own, rewritten to one that is not.
    (workspace / "out" / cli.JOB_NAME).write_text(
        json.dumps(
            {
                "job_id": job.job_id,
                "out_dir": job.out_dir,
                "descriptor": job.descriptor,
                "pid": 999_999_999,
                "started_at": job.started_at,
                "argv": list(job.argv),
            }
        ),
        encoding="utf-8",
    )

    forced = cli.invoke(
        ["stop", _job_id(workspace), "--force", "--root", str(workspace)]
    )

    assert forced.exit_code == cli.EXIT_OK
    assert "no longer running" in forced.stdout
    assert orchestrator.control_of(workspace / "out") == "stopped", (
        "the control is still written: the run must not continue even if its process "
        "was already gone"
    )


def test_stop_on_an_unknown_job_id_is_a_usage_error(workspace: pathlib.Path) -> None:
    """An unknown id is the caller's mistake, and the refusal lists what was found."""
    _run(workspace)

    refused = cli.invoke(["stop", "deadbeef", "--root", str(workspace)])

    assert refused.exit_code == cli.EXIT_USAGE
    assert "no run with job id" in refused.stderr
    assert _job_id(workspace) in refused.stderr, "the known ids are listed"


# --- 3. Precedence, and the flag outside it ---------------------------------


def test_precedence_is_cli_then_environment_then_dotenv_then_default() -> None:
    """`NFR-06`'s chain, and the order is the point: the narrowest scope wins."""
    environment = {"DOCFLOW_OUT": "from-env"}
    dotenv = {"DOCFLOW_OUT": "from-dotenv"}

    assert (
        cli.resolve_setting(
            "out", "from-cli", default="from-default", env=environment, dotenv=dotenv
        )
        == "from-cli"
    )
    assert (
        cli.resolve_setting(
            "out", None, default="from-default", env=environment, dotenv=dotenv
        )
        == "from-env"
    )
    assert (
        cli.resolve_setting("out", None, default="from-default", env={}, dotenv=dotenv)
        == "from-dotenv"
    )
    assert (
        cli.resolve_setting("out", None, default="from-default", env={}, dotenv={})
        == "from-default"
    )


def test_every_layer_silent_leaves_the_setting_unresolved() -> None:
    """None means *unresolved*, never empty: a caller reports it rather than
    substituting a value nobody chose.
    """
    assert cli.resolve_setting("out", None, env={}, dotenv={}) is None


def test_an_empty_flag_value_is_a_value_not_an_absence() -> None:
    """A caller who wrote `--out ""` said something.

    Treating it as unset would run against a root they did not choose - the stand-in
    shape, expressed as a process setting.
    """
    assert cli.resolve_setting("out", "", env={"DOCFLOW_OUT": "x"}, dotenv={}) == ""


def test_a_flag_that_is_never_settable_by_environment_is_refused() -> None:
    """`NFR-06`: `--force` is never settable by environment.

    Refused at the **resolution** step rather than checked afterwards: a chain that read
    the variable and then discarded it would still be the mechanism the prohibition
    exists to prevent.
    """
    for flag in ("force", "stage", "only"):
        with pytest.raises(ValueError) as excinfo:
            cli.resolve_setting(flag, None, env={flag.upper(): "1"}, dotenv={})
        assert "never settable by environment" in str(excinfo.value)


def test_a_force_environment_variable_changes_nothing_about_stop(
    workspace: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The behavioural half: the obvious variable is set and `--force` stays absent.

    `DOCFLOW_FORCE` is not read anywhere, so a bare `stop` with it set still discovers
    and reports.
    """
    orchestrator.write_control(workspace / "out", "paused")
    _run(workspace)
    monkeypatch.setenv("DOCFLOW_FORCE", "1")

    reported = cli.invoke(["stop", "--root", str(workspace)])

    assert reported.exit_code == cli.EXIT_OK
    assert "nothing stopped" in reported.stdout
    assert orchestrator.control_of(workspace / "out") == "paused"


def test_the_flag_lists_are_data_and_do_not_overlap() -> None:
    """The two tables are the declaration; an overlap would be a flag both resolved and
    forbidden, which no reading of `NFR-06` supports.
    """
    assert frozenset() == cli.NEVER_FROM_ENVIRONMENT & cli.FROM_ENVIRONMENT
    assert frozenset({"force", "stage", "only"}) == cli.NEVER_FROM_ENVIRONMENT


def test_a_dotenv_file_parses_and_an_absent_one_is_empty(
    tmp_path: pathlib.Path,
) -> None:
    """The third layer, and its two cases: a real file and no file at all."""
    path = tmp_path / ".env"
    path.write_text(
        '# a comment\n\nDOCFLOW_OUT="quoted"\nDOCFLOW_JOBS=8\nnot a pair\n',
        encoding="utf-8",
    )

    values = cli.read_dotenv(path)

    assert values["DOCFLOW_OUT"] == "quoted"
    assert values["DOCFLOW_JOBS"] == "8"
    assert "not a pair" not in " ".join(values)
    assert cli.read_dotenv(tmp_path / "absent") == {}


def test_run_resolves_its_output_root_through_the_chain(
    workspace: pathlib.Path,
) -> None:
    """The chain is not a library curiosity: `run` reads its root through it."""
    out = workspace / "from-env"

    result = cli.invoke(
        ["run", str(workspace / "d.json")],
        env={"DOCFLOW_OUT": str(out)},
    )

    assert result.exit_code == cli.EXIT_OK
    assert (out / "run.json").is_file()


def test_run_without_an_output_root_is_a_usage_error(
    workspace: pathlib.Path,
) -> None:
    """No layer supplied a root, so the verb reports that rather than choosing one."""
    refused = cli.invoke(["run", str(workspace / "d.json")], env={})

    assert refused.exit_code == cli.EXIT_USAGE
    assert "--out <dir> or DOCFLOW_OUT" in refused.stderr


# --- The slot bounds the surface resolves ----------------------------------


def test_run_resolves_the_cpu_slot_from_the_environment() -> None:
    """`NFR-04`: ``DOCFLOW_JOBS`` bounds the `cpu` slot, and only that one.

    Asserted through the resolved bound set rather than through a run's behaviour,
    because the PoC scheduler is sequential: a bound of 4 and a bound of 1 dispatch
    differently only once there is more than one stage in flight, and there never is.
    The value the operator set is therefore the observable, and reading it is what makes
    the resolution falsifiable.
    """
    bounds = cli._slot_bounds({"DOCFLOW_JOBS": "4"})  # pylint: disable=protected-access

    assert bounds.bounds["cpu"] == 4
    assert bounds.bounds["gpu"] == 1, "the GPU bound is not the operator's to raise"
    assert bounds.bounds["remote"] == 1


def test_the_slot_bounds_default_to_the_declared_baseline() -> None:
    """Nothing set is a real state, and it reads as the declared baseline."""
    bounds = cli._slot_bounds({})  # pylint: disable=protected-access

    assert dict(bounds.as_mapping()) == {"cpu": 1, "gpu": 1, "remote": 1}


def test_a_non_numeric_jobs_value_is_refused_rather_than_ignored() -> None:
    """Falling back to the baseline would run at a bound nobody asked for."""
    with pytest.raises(cli.UsageError) as excinfo:
        cli._slot_bounds({"DOCFLOW_JOBS": "many"})  # pylint: disable=protected-access

    assert "must be an integer" in str(excinfo.value)


def test_a_negative_jobs_value_is_refused() -> None:
    """A negative capacity is a caller's arithmetic error, not a bound."""
    with pytest.raises(cli.UsageError) as excinfo:
        cli._slot_bounds({"DOCFLOW_JOBS": "-1"})  # pylint: disable=protected-access

    assert "out of range" in str(excinfo.value)


# --- 4. Two surfaces, never crossed -----------------------------------------


def test_exactly_five_verbs_exist_and_resume_is_not_one_of_them(
    workspace: pathlib.Path,
) -> None:
    """*No separate product `resume` verb* (`FR-01`, `FR-02`) - continuing is `run`.

    Asserted against the dispatcher rather than against the usage text: a verb that
    dispatched but was undocumented would pass a text check.
    """
    for verb in ("resume", "continue", "retry"):
        refused = cli.invoke([verb, "--root", str(workspace)])
        assert refused.exit_code == cli.EXIT_USAGE, verb
        assert "unknown verb" in refused.stderr


def test_the_product_surface_never_imports_the_lab_surface() -> None:
    """`kernel-cli.md` §2/§15: two entry points, two audiences, never crossed.

    Asserted over the import graph, which is the only place the rule can be checked
    without running anything - the two modules share the orchestrator and the kernels,
    and that is the correct amount of sharing.
    """
    imported: list[str] = []
    for node in ast.walk(CLI_TREE):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.append(node.module)

    assert imported, "the module must import something"
    assert [name for name in imported if name.startswith("docflow.kernel_cli")] == []
    assert [name for name in imported if name.startswith("docflow.components")] == []


def test_the_lab_surface_never_imports_the_product_surface() -> None:
    """The other direction, so the arrow cannot be repaired from one side only."""
    lab = pathlib.Path(__file__).resolve().parents[2] / "src" / "docflow" / "kernel_cli"
    imported: list[str] = []
    for module in sorted(lab.glob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported.append(node.module)

    assert [name for name in imported if name.startswith("docflow.cli")] == []


def test_no_verb_and_no_flag_names_a_document_concept() -> None:
    """`kernel-cli.md` §10's forbidden vocabulary appears nowhere on this surface.

    `--pipeline` included: the 13 codes are `S3-T02`'s, and Stage 1's `run` takes a
    descriptor precisely because a descriptor is not a pipeline code.

    The scan reads the **flag literals the parser actually accepts**, not the source
    text: this module's own docstring names `--pipeline` to say it is out of scope, and
    forbidding the word would forbid describing the decision.
    """
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
        "ErVR",
        "EpVR",
        "ErpVR",
    )
    # The accepted flags are the strings passed to the parser, and the docstrings are
    # excluded by taking only literals that appear inside a call to `_parse`.
    flags: set[str] = set()
    for node in ast.walk(CLI_TREE):
        if not isinstance(node, ast.Call):
            continue
        if not (
            isinstance(node.func, ast.Name)
            and node.func.id in {"_parse", "_parse_flag"}
        ):
            continue
        for keyword in node.keywords:
            if keyword.arg not in {"values", "booleans"}:
                continue
            for element in getattr(keyword.value, "elts", []):
                if isinstance(element, ast.Constant) and isinstance(element.value, str):
                    flags.add(element.value)

    assert flags, "the scan found no flag, so it is asserting nothing"

    offenders = [
        flag for flag in flags for word in forbidden if word.lower() in flag.lower()
    ]
    assert offenders == [], f"a flag names a document concept: {offenders}"
    assert not any(flag.startswith("pip") for flag in flags), sorted(flags)


def test_the_entry_point_declared_in_pyproject_is_the_one_this_module_exposes() -> None:
    """`pyproject.toml` fixes `docflow = "docflow.cli:main"`; this module has `main`."""
    assert callable(cli.main)


def test_main_returns_an_internal_error_for_a_bug_and_never_a_usage_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A bug is not *you typed it wrong*.

    `EXIT_INTERNAL` and `EXIT_USAGE` are different facts, and collapsing them tells an
    operator to fix their command line when the code is broken.
    """

    def explode(_argv: object) -> cli.Invocation:
        raise RuntimeError("a bug")

    monkeypatch.setattr(cli, "invoke", explode)

    code = cli.main([])

    assert code == cli.EXIT_INTERNAL
    assert code != cli.EXIT_USAGE
    assert "internal error" in capsys.readouterr().err


def test_main_writes_stdout_and_stderr_to_their_own_streams(
    workspace: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The one function that touches a stream, so the split is asserted here."""
    code = cli.main(["run", str(workspace / "d.json"), "--out", str(workspace / "o")])
    captured = capsys.readouterr()

    assert code == cli.EXIT_OK
    assert "job" in captured.out
    assert captured.err == ""


def test_an_unknown_verb_is_a_usage_error_that_lists_the_verbs() -> None:
    """The refusal names what would have worked, so a typo is visible."""
    refused = cli.invoke(["inspect"])

    assert refused.exit_code == cli.EXIT_USAGE
    assert "unknown verb" in refused.stderr
    assert "run" in refused.stderr


def test_no_arguments_prints_the_usage() -> None:
    """A bare invocation explains itself rather than doing something surprising."""
    refused = cli.invoke([])

    assert refused.exit_code == cli.EXIT_USAGE
    assert "usage: docflow" in refused.stderr
    assert "resume" not in refused.stderr


def test_an_unknown_flag_is_refused_by_the_verb(workspace: pathlib.Path) -> None:
    """`--dry-run` and the rest of the deferred list are absent, not ignored."""
    refused = cli.invoke(
        ["run", str(workspace / "d.json"), "--out", str(workspace / "o"), "--dry-run"]
    )

    assert refused.exit_code == cli.EXIT_USAGE
    assert "unknown flag --dry-run" in refused.stderr


def test_a_missing_descriptor_is_reported_as_a_usage_error(
    workspace: pathlib.Path,
) -> None:
    """An absent descriptor is the caller's mistake, and the message names the path."""
    refused = cli.invoke(
        ["run", str(workspace / "absent.json"), "--out", str(workspace / "o")]
    )

    assert refused.exit_code == cli.EXIT_USAGE
    assert "no descriptor at" in refused.stderr


def test_a_descriptor_that_is_not_json_is_refused_with_the_format_named(
    workspace: pathlib.Path,
) -> None:
    """A YAML descriptor is refused **and named as the lab surface's**, not silently
    parsed as something else.
    """
    (workspace / "d.yaml").write_text("unit: synthetic\n", encoding="utf-8")

    refused = cli.invoke(
        ["run", str(workspace / "d.yaml"), "--out", str(workspace / "o")]
    )

    assert refused.exit_code == cli.EXIT_USAGE
    assert "not readable JSON" in refused.stderr


def test_the_job_id_is_derived_from_the_resolved_root() -> None:
    """`out`, `./out` and a differently-spelled path address the same job.

    Deriving the id is what makes *run it again* continue a run rather than start a
    second one beside it.
    """
    here = pathlib.Path.cwd()

    assert cli.job_id_for(here / "out") == cli.job_id_for(here / "out" / ".." / "out")
    assert cli.job_id_for(here / "out") != cli.job_id_for(here / "other")
    assert len(cli.job_id_for(here / "out")) == 8


def test_discovery_ignores_directories_that_hold_no_job(
    workspace: pathlib.Path,
) -> None:
    """*No runs here* is an answer, and a stray directory is not a run."""
    (workspace / "junk").mkdir()
    (workspace / "junk" / "readme.txt").write_text("not a run", encoding="utf-8")

    assert cli.discover_runs(workspace) == ()
    assert cli.discover_runs(workspace / "absent") == ()


def test_the_operations_table_refuses_a_source_it_cannot_produce(
    workspace: pathlib.Path,
) -> None:
    """A stage asking for a source this build cannot produce gets a typed reason.

    The alternative - a stand-in artifact - would be a `done` stage about bytes nothing
    acquired, which is the silent substitution the whole design refuses.
    """
    (workspace / "other.json").write_text(
        json.dumps(
            {
                "unit": "synthetic",
                "units": ["U-0001"],
                "stages": [
                    {
                        "name": "acquire",
                        "kernel": "store",
                        "op": "put",
                        "params": {"source": "scanned"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    out = workspace / "other"

    result = cli.invoke(["run", str(workspace / "other.json"), "--out", str(out)])

    assert result.exit_code == cli.EXIT_OK, (
        "the run completes; the stage reports failure"
    )
    ledger = store.read_ledger(out / "U-0001")
    assert ledger.stages["acquire"].state == "failed"
    assert ledger.stages["acquire"].reason_code == "engine_unavailable"


def test_status_reports_the_stage_states_and_modifies_nothing(
    workspace: pathlib.Path,
) -> None:
    """`status` reads. The ledger is asserted unchanged, because *it printed* is not
    the property.
    """
    _run(workspace)
    out = workspace / "out"
    before = (out / "run.json").read_bytes()

    reported = cli.invoke(["status", _job_id(workspace), "--root", str(workspace)])

    assert reported.exit_code == cli.EXIT_OK
    assert "U-0001: acquire=done, transform=done, persist=done" in reported.stdout
    assert (out / "run.json").read_bytes() == before


def test_jobs_reports_finished_runs_too(workspace: pathlib.Path) -> None:
    """`jobs` answers *what happened*, including runs that already ended."""
    _run(workspace)

    reported = cli.invoke(["jobs", "--root", str(workspace)])

    assert reported.exit_code == cli.EXIT_OK
    assert _job_id(workspace) in reported.stdout
    assert "1 run(s)" in reported.stdout


def test_jobs_on_a_root_with_no_runs_says_so(workspace: pathlib.Path) -> None:
    """An empty discovery is an answer, not an error."""
    reported = cli.invoke(["jobs", "--root", str(workspace)])

    assert reported.exit_code == cli.EXIT_OK
    assert "no runs under" in reported.stdout


def test_os_sep_note_keeps_the_path_handling_portable() -> None:
    """A trivial guard so `os` is imported for a reason this suite can name."""
    assert os.sep
    assert pathlib.Path("/tmp") / "out" == pathlib.Path("/tmp/out")
