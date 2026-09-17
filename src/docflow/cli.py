"""The product surface - ``docflow``: the five verbs that make resume observable.

`E06-01` / `S1-T18`. This is not a thin wrapper over the orchestrator. It is the surface
the closing criterion is observed through: ``stop --force`` is what produces the
interrupted stage the gate reads, and a second ``run`` is what proves the resume
continued from the exact stage rather than from acquisition.

Two entry points, two audiences, never crossed
----------------------------------------------

``docflow`` is the product. ``docflow-kernel`` is the lab bench. ``docflow run`` never
invokes ``docflow-kernel`` (`kernel-cli.md` §2, §15), and this module imports nothing
from ``docflow.kernel_cli`` - the two share the orchestrator and the kernels, which is
the correct amount of sharing and the only correct amount.

What a *job* is
---------------

A job is a run with an output root. Its id is a short digest of that root's **resolved**
path, so the same ``--out`` always addresses the same job and a second ``run`` continues
the first rather than starting a parallel one. The metadata an operator needs - which
descriptor, which process, when it started - lives in ``<out>/job.json`` beside the
control and the manifest.

That is what makes ``pause``, ``stop`` and ``status`` addressable from a *different
process* than the one running the job: they read and write files at a root they can
already find. Running the five verbs is therefore not the same as running the
orchestrator five times; it is five verbs over one durable record.

``stop`` discovers, it does not kill by default
-----------------------------------------------

`FR-02`: *"`stop` with no arguments discovers and reports active runs instead of
killing."* So ``stop`` with no job id **reports** and exits, whatever ``--force`` says -
``--force`` without a job id is narrowed to *the runs already being stopped*. This is
deliberate: the command an operator reaches for when they are unsure must be the
command that cannot destroy anything.

Settings precedence, and the one flag outside it
------------------------------------------------

`NFR-06`: operational settings resolve **CLI flag → environment → `.env` → built-in
default**, and that chain governs *operational* settings only: paths, slots, model and
host. `NFR-06a` puts corpus policy in the registry with no override at all, which is why
no policy value appears here.

``--force`` is deliberately **outside** the chain. `NFR-06` names it as never settable
by
environment, and the implementation honours that by never *reading* a variable for it -
a test sets the obvious name and asserts nothing changes. Reading it would be the
mechanism; refusing it after reading it would still be a mechanism.

Deliberately out of scope
-------------------------

- **No `resume` verb.** Continuing is *"run it again"* (`FR-01`, `FR-02`). The lab
  surface's ``orchestrator resume`` is a port method, not a product verb.
- **No `--pipeline <CODE>`.** The 13 codes are descriptors, `S3-T02` (Plan 3). A
  descriptor is not a pipeline code (`kernel-cli.md` §9). ``run`` takes a descriptor.
- **No batch or mirrored tree.** `docflow/batch.py` is `S3-T06` (Plan 3).
- **No per-component subcommands.** Ten of them are `S2-T16` (Plan 2).
- **No `--failed` / `--state` / `--dry-run` and the rest of the `03-cli.md` deferred
  list.** `# TODO: [MVP]` (`prd.md` §7).
- **No `--no-validate`.** **Never** (ADR-002, `prd.md` FR-18).
- **No `--verify`.** Verification is an outcome of reading a ledger; there is no flag
for
  it on any surface. **Never** (ADR-006, `kernel-cli.md` §9).
- **No `--rebuild-index` flag.** `rebuild_index()` stays a library call in the PoC.
  `# TODO: [MVP]` (`prd.md` §7).
- **No document noun in a verb or a flag.** **Never** (`kernel-cli.md` §10).

PoC stage
---------

The lifecycle stage is **PoC**: close the flow, keep the shortcuts visible. Each
deliberate shortcut carries a marker naming what must replace it.

"""

# Pylint's line ceiling is exceeded by decision: `wbs.md` §8 assigns this surface one
# deliverable path, and five verbs plus their parsing, their precedence chain and their
# reporting are one surface rather than five modules that would each import the other
# four. The same decision `docflow/kernels/orchestrator.py` records.
# pylint: disable=too-many-lines

from __future__ import annotations

import dataclasses
import datetime
import hashlib
import json
import os
import pathlib
import signal
import sys
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Final

from docflow.kernels import orchestrator, store
from docflow.kernels.types import Artifact, Evidence, KernelResult, Reason

__all__: list[str] = [
    "EXIT_INTERNAL",
    "EXIT_OK",
    "EXIT_USAGE",
    "JOB_NAME",
    "Invocation",
    "Job",
    "discover_runs",
    "invoke",
    "job_id_for",
    "main",
    "read_job",
    "resolve_setting",
    "write_job",
]

#: A verb succeeded. Note this surface does **not** adopt `kernel-cli.md` §5's five-code
# : contract: that contract exists because a *kernel* answers a question about a
# document,
#: and it encodes *the document's answer* against *the call's precondition*. The product
#: surface answers no such question, so it uses the three codes any CLI needs and no
#: more. No ``KernelResult`` is emitted here; the envelope is the lab surface's.
EXIT_OK: Final[int] = 0

#: Unexpected internal error. A traceback goes to stderr.
EXIT_INTERNAL: Final[int] = 1

#: Usage error: an unknown verb, a bad flag, a missing argument, or a job id that no
#: discovered run answers to.
EXIT_USAGE: Final[int] = 4

#: The job's metadata file, at the run's output root.
JOB_NAME: Final[str] = "job.json"

# : The environment prefix for operational settings. The *canonical* variable names
# belong
#: to `S3-T12`, which owns `.env.example`; this is the prefix those names will use.
_ENV_PREFIX: Final[str] = "DOCFLOW_"

#: Flags that are **never** settable by environment (`NFR-06`). Listed as data so the
# : property is a table rather than a habit, and so a test can assert the list against
# the
#: flags the parser actually accepts.
NEVER_FROM_ENVIRONMENT: Final[frozenset[str]] = frozenset({"force", "stage", "only"})

#: Flags whose value is a path or a count and which *do* follow the precedence chain.
#: `NFR-06` scopes the chain to operational settings: paths, slots, model and host.
FROM_ENVIRONMENT: Final[frozenset[str]] = frozenset({"out", "jobs", "slots"})

#: How many characters of a job's digest are shown. Short enough to type, long enough
#: that two output roots in one workspace do not collide.
_JOB_ID_LENGTH: Final[int] = 8


@dataclasses.dataclass(frozen=True, slots=True)
class Invocation:
    """What one command did, as a value rather than as a side effect.

    ``main`` is the only function that touches a stream, so every verb can be tested by
    calling :func:`invoke` and asserting on the returned value - the shape `E07-01`
    established for the lab surface, and for the same reason.

    Attributes:
        exit_code: The process exit code.
        stdout: What a script reads.
        stderr: What a person reads.

    """

    exit_code: int
    stdout: str
    stderr: str


@dataclasses.dataclass(frozen=True, slots=True)
class Job:
    """A run's operator-facing identity: its id, its root and how it was started.

    Attributes:
        job_id: The short digest of the resolved output root.
        out_dir: The output root, as an absolute path.
        descriptor: The descriptor the run was started from.
        pid: The process that started it, so ``stop --force`` has something to signal.
        started_at: An ISO-8601 UTC timestamp, for a report a person reads.
        argv: The command line, so a report can say how the run was invoked.

    """

    job_id: str
    out_dir: str
    descriptor: str
    pid: int
    started_at: str
    argv: tuple[str, ...]


def job_id_for(out_dir: pathlib.Path) -> str:
    """Return the job id for an output root.

    The id is a digest of the **resolved** path, so ``out``, ``./out`` and ``out/``
    address the same job. Deriving it rather than minting it is what makes *"run it
    again"* continue a run instead of starting a second one beside it (`FR-01`).

    Args:
        out_dir: The run's output root.

    Returns:
        The first :data:`_JOB_ID_LENGTH` hexadecimal characters of the path's digest.

    """
    resolved = out_dir.expanduser().resolve()
    return hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:_JOB_ID_LENGTH]


def read_job(out_dir: pathlib.Path) -> Job:
    """Read a run's job metadata.

    Args:
        out_dir: The run's output root.

    Returns:
        The job.

    Raises:
        FileNotFoundError: If the root holds no job. A root with no job is not an empty
            job: it is a directory that happens to have the same name as one.

    """
    path = out_dir / JOB_NAME
    if not path.is_file():
        raise FileNotFoundError(f"No job at {path}: this root holds no run.")

    payload = json.loads(path.read_text(encoding="utf-8"))
    return Job(
        job_id=str(payload["job_id"]),
        out_dir=str(payload["out_dir"]),
        descriptor=str(payload["descriptor"]),
        pid=int(payload["pid"]),
        started_at=str(payload["started_at"]),
        argv=tuple(str(part) for part in payload["argv"]),
    )


def write_job(out_dir: pathlib.Path, job: Job) -> None:
    """Write a run's job metadata, atomically.

    Written through K7's atomic write for the same reason a ledger is: a half-written
    job file would be a root that answers *what is running here* with a parse error.

    Args:
        out_dir: The run's output root, created if it does not exist.
        job: The job to record.

    """
    out_dir.mkdir(parents=True, exist_ok=True)
    # TODO: [MVP] K7 exposes no public atomic-write entry point, so this reaches the
    # private helper - the same shortcut `orchestrator.write_control` takes, and the
    # same remedy applies: a narrow `store.write_json_atomically` belongs to
    # `E02`/`E07-02`, which own K7's surface.
    store._atomic_write(  # pylint: disable=protected-access
        out_dir / JOB_NAME,
        (
            json.dumps(
                {
                    "job_id": job.job_id,
                    "out_dir": job.out_dir,
                    "descriptor": job.descriptor,
                    "pid": job.pid,
                    "started_at": job.started_at,
                    "argv": list(job.argv),
                },
                indent=2,
            )
            + "\n"
        ).encode("utf-8"),
    )


def discover_runs(root: pathlib.Path) -> Sequence[Job]:
    """Find the runs under a root, newest first.

    A run is a directory carrying a job file. The search is **one level deep** plus the
    root itself, which matches how an output root is named and keeps discovery from
    walking a tree it does not own.

    Args:
        root: The directory to search.

    Returns:
        The jobs found, ordered by start time descending so a report leads with the most
        recent run. A root that does not exist yields nothing rather than raising: *"no
        runs here"* is an answer, and an absent search directory is the same answer.

    """
    if not root.is_dir():
        return ()

    candidates = [root, *(path for path in sorted(root.iterdir()) if path.is_dir())]
    jobs = []
    for candidate in candidates:
        try:
            jobs.append(read_job(candidate))
        except (FileNotFoundError, KeyError, ValueError):
            continue

    return tuple(sorted(jobs, key=lambda job: job.started_at, reverse=True))


def resolve_setting(
    flag: str,
    cli_value: str | None,
    *,
    default: str | None = None,
    env: Mapping[str, str] | None = None,
    dotenv: Mapping[str, str] | None = None,
) -> str | None:
    """Resolve one operational setting by `NFR-06`'s precedence chain.

    **CLI flag → environment → ``.env`` → built-in default**, and in that order because
    the narrowest scope wins: a flag belongs to one invocation, a variable to one shell,
    a ``.env`` file to one checkout, and a default to the program.

    Args:
        flag: The flag's name, without dashes, e.g. ``"out"``.
        cli_value: The value the command line gave, or None when the flag was absent. An
            **empty string is a value**, not an absence: a caller who wrote ``--out ""``
            said something, and treating it as unset would run against a root they did
            not choose.
        default: The built-in default, or None when there is none. None means the
        setting
            is *unresolved* rather than empty, and the caller reports that rather than
            substituting one.
        env: The environment, or None for the real one. Injected so a test never mutates
            the process environment and a leaked variable cannot make a suite pass.
        dotenv: A parsed `.env`, or None for none. Injected for the same reason.

    Returns:
        The resolved value, or None when every layer is silent.

    Raises:
        ValueError: If ``flag`` is in :data:`NEVER_FROM_ENVIRONMENT`. A flag that may
        not
            come from the environment is not resolved by a chain that reads one, and
            raising is what keeps the prohibition in one place instead of in the habit
            of
            every caller.

    """
    if flag in NEVER_FROM_ENVIRONMENT:
        raise ValueError(
            f"{flag!r} is never settable by environment (`NFR-06`), so it is not "
            "resolved by the precedence chain. A chain that read a variable for it "
            "would be the mechanism the prohibition exists to prevent."
        )

    if cli_value is not None:
        return cli_value

    environment = os.environ if env is None else env
    from_environment = environment.get(f"{_ENV_PREFIX}{flag.upper()}")
    if from_environment is not None and from_environment != "":
        return from_environment

    if dotenv is not None:
        from_dotenv = dotenv.get(f"{_ENV_PREFIX}{flag.upper()}")
        if from_dotenv is not None and from_dotenv != "":
            return from_dotenv

    return default


def read_dotenv(path: pathlib.Path) -> Mapping[str, str]:
    """Parse a ``.env`` file into a mapping.

    `NFR-06`'s third layer, and the only one that is a file. The parser is deliberately
    small: ``KEY=VALUE`` per line, ``#`` starts a comment, blank lines are skipped, and
    a
    value may be double-quoted. Anything richer - interpolation, ``export``, multi-line
    values - is a format with its own semantics, and inventing those here would be
    inventing the canonical variable set that `S3-T12` owns.

    Args:
        path: The file. An absent file yields an empty mapping, because a checkout
            without a ``.env`` is the normal case rather than an error.

    Returns:
        The parsed values.

    """
    if not path.is_file():
        return MappingProxyType({})

    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        cleaned = value.strip()
        if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] == '"':
            cleaned = cleaned[1:-1]
        values[name.strip()] = cleaned

    return MappingProxyType(values)


def invoke(argv: Sequence[str], *, env: Mapping[str, str] | None = None) -> Invocation:
    """Run one command line and return what it did.

    Args:
        argv: The arguments **after** the program name.
        env: The environment, or None for the real one. Injected so the precedence tests
            do not mutate the process environment.

    Returns:
        The invocation.

    """
    if not argv:
        return Invocation(
            exit_code=EXIT_USAGE,
            stdout="",
            stderr=_usage(),
        )

    verb, *rest = argv
    handlers = {
        "run": _verb_run,
        "status": _verb_status,
        "jobs": _verb_jobs,
        "pause": _verb_pause,
        "stop": _verb_stop,
    }

    handler = handlers.get(verb)
    if handler is None:
        return Invocation(
            exit_code=EXIT_USAGE,
            stdout="",
            stderr=f"unknown verb {verb!r}. The verbs are {sorted(handlers)}.\n",
        )

    try:
        return handler(rest, env=env)
    except UsageError as refused:
        return Invocation(exit_code=EXIT_USAGE, stdout="", stderr=f"{refused}\n")


class UsageError(Exception):
    """A command line this surface cannot honour.

    Raised rather than returned so a verb's body reads as the thing it does, and caught
    in one place so every usage refusal exits the same way. It carries no ``Reason``:
    a usage error is a mistake in the caller's own code, not a document's answer, which
    is the distinction `kernel-cli.md` §5 draws between exit `4` and exit `2`.
    """


def _usage() -> str:
    """Return the usage text.

    Returns:
        The text.

    """
    return (
        "usage: docflow <verb> [options]\n"
        "\n"
        "  run <descriptor> --out <dir> [--jobs N] [--slots cpu=N,...]\n"
        "  status <job-id> [--root <dir>]\n"
        "  jobs [--root <dir>]\n"
        "  pause <job-id> [--root <dir>]\n"
        "  stop [<job-id>] [--root <dir>] [--force]\n"
    )


def _parse(
    rest: Sequence[str], *, values: Sequence[str] = (), booleans: Sequence[str] = ()
) -> tuple[tuple[str, ...], Mapping[str, str], frozenset[str]]:
    """Parse a verb's arguments into positionals, value flags and boolean flags.

    Args:
        rest: The arguments after the verb.
        values: The flags that take a value.
        booleans: The flags that take none.

    Returns:
        The positionals, the value flags as a mapping, and the boolean flags present.

    Raises:
        UsageError: On an unknown flag, a value flag with no value, or a boolean flag
            given one.

    """
    positionals: list[str] = []
    taken: dict[str, str] = {}
    present: set[str] = set()

    index = 0
    while index < len(rest):
        token = rest[index]
        if not token.startswith("--"):
            positionals.append(token)
            index += 1
            continue

        name = token[2:]
        if name in booleans:
            present.add(name)
            index += 1
            continue
        if name in values:
            if index + 1 >= len(rest):
                raise UsageError(f"--{name} needs a value")
            taken[name] = rest[index + 1]
            index += 2
            continue
        raise UsageError(f"unknown flag --{name}")

    return tuple(positionals), MappingProxyType(taken), frozenset(present)


def _runs_root(
    taken: Mapping[str, str], env: Mapping[str, str] | None = None
) -> pathlib.Path:
    """Return the directory a discovery verb should search.

    Args:
        taken: The parsed value flags.
        env: The environment, or None for the real one.

    Returns:
        ``--root``, else ``DOCFLOW_RUNS``, else the current directory. This is an
        operational path, so it follows `NFR-06`'s chain, and the default is the working
        directory - the place an operator's own runs were started from.

    """
    resolved = resolve_setting(
        "runs",
        taken.get("root"),
        default=str(pathlib.Path.cwd()),
        env=env,
        dotenv=read_dotenv(pathlib.Path(".env")),
    )
    return pathlib.Path(str(resolved))


def _job_for(job_id: str, runs_root: pathlib.Path) -> Job:
    """Return the discovered job a job id names.

    Args:
        job_id: The id as the operator typed it.
        runs_root: The directory to search.

    Returns:
        The job.

    Raises:
        UsageError: If no discovered run answers to the id. The message lists the ids
            that were found, so an operator can see a typo rather than guess.

    """
    jobs = discover_runs(runs_root)
    for job in jobs:
        if job.job_id == job_id:
            return job

    known = sorted(job.job_id for job in jobs)
    raise UsageError(
        f"no run with job id {job_id!r} under {runs_root}. Known ids: {known or 'none'}"
    )


# --- run ---------------------------------------------------------------------


def _verb_run(
    rest: Sequence[str], *, env: Mapping[str, str] | None = None
) -> Invocation:
    """Start or continue a run, and it is the same verb either way.

    Args:
        rest: The verb's arguments.
        env: The environment, or None for the real one.

    Returns:
        The invocation.

    Raises:
        UsageError: On a missing descriptor or output root.

    """
    positionals, taken, _ = _parse(
        rest, values=("out", "jobs", "slots", "descriptor"), booleans=()
    )
    descriptor_arg = taken.get("descriptor") or (
        positionals[0] if positionals else None
    )
    if descriptor_arg is None:
        raise UsageError("run needs a descriptor: docflow run <descriptor> --out <dir>")

    resolved_out = resolve_setting(
        "out",
        taken.get("out"),
        env=env,
        dotenv=read_dotenv(pathlib.Path(".env")),
    )
    if resolved_out is None:
        raise UsageError("run needs an output root: --out <dir> or DOCFLOW_OUT")

    out_dir = pathlib.Path(str(resolved_out))
    descriptor = orchestrator.read_descriptor(
        pathlib.Path(descriptor_arg), _read_descriptor_mapping
    )

    job = Job(
        job_id=job_id_for(out_dir),
        out_dir=str(out_dir.expanduser().resolve()),
        descriptor=str(descriptor_arg),
        pid=os.getpid(),
        started_at=_now(),
        argv=("run", descriptor_arg, "--out", str(resolved_out)),
    )
    # The job is recorded **before** the first stage, so `jobs` can see a run that is in
    # flight rather than only completed ones, and so `pause` from another process has a
    # root to address.
    write_job(out_dir, job)

    report = orchestrator.run(
        descriptor,
        out_dir,
        input_hashes=_input_hashes(descriptor),
        operations=_operations(out_dir),
        keys=_key_context(),
    )

    return Invocation(
        exit_code=EXIT_OK,
        stdout=(
            f"job {job.job_id} — {len(report.dispatched)} stage(s) run, "
            f"{len(report.skipped)} already done, {len(report.held)} held\n"
            f"state: {report.manifest['state']}\n"
        ),
        stderr="",
    )


def _read_descriptor_mapping(path: pathlib.Path) -> Mapping[str, object]:
    """Read a descriptor file into a mapping.

    JSON is this surface's PoC format, and it is the reason the descriptor loader takes
    an injected reader: parsing YAML needs a third-party library, and the kernel layer
    imports none. A ``descriptors/*.yaml`` file is read by `E07-02`'s lab surface, which
    owns the YAML binding.

    Args:
        path: The descriptor file.

    Returns:
        The parsed mapping.

    Raises:
        UsageError: If the file is missing or is not an object. Both are the caller's
            mistake rather than a document's answer.

    """
    if not path.is_file():
        raise UsageError(f"no descriptor at {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as refused:
        raise UsageError(
            f"{path} is not readable JSON ({refused}). This surface reads JSON "
            "descriptors in the PoC; the YAML binding belongs to the lab surface."
        ) from refused
    if not isinstance(payload, dict):
        raise UsageError(f"{path} must hold an object, not {type(payload).__name__}")
    return payload


def _operations(
    out_dir: pathlib.Path,
) -> Mapping[tuple[str, str], orchestrator.StageOperation]:
    """Return the operation table this surface can execute.

    At Stage 1 the table serves **generated** input only, which is what the synthetic
    descriptor declares (``params: {source: generated}``). Anything else is refused with
    a typed reason rather than approximated: a stage whose input the surface cannot
    produce has no honest answer, and inventing one is the silent stand-in this codebase
    refuses everywhere.

    Args:
        out_dir: The run's output root.

    Returns:
        The table, keyed by ``(kernel, op)``.

    """

    def generated_put(call: orchestrator.StageCall) -> KernelResult[Artifact]:
        """Produce the stage's bytes from its own key and store them.

        The bytes are a function of the unit, the stage and the input hash, so the flow
        is end-to-end verifiable and deterministic - a real pipeline's operation reads a
        real artifact instead.

        Args:
            call: The dispatch call.

        Returns:
            The stored artifact, or no value and a typed reason when the stage asked for
            a source this surface cannot produce.

        """
        source = call.stage.params.get("source", "generated")
        if source != "generated":
            return KernelResult(
                value=None,
                evidence=Evidence(
                    terms=MappingProxyType({"source": source}),
                    measurements=MappingProxyType({}),
                    observed=MappingProxyType(
                        {"unit": call.unit, "stage": call.stage.name}
                    ),
                ),
                reason=Reason(
                    code="engine_unavailable",
                    message=(
                        f"stage {call.stage.name!r} asks for source {source!r}, and "
                        "this build produces generated input only. A real acquisition "
                        "op arrives with the components at Stage 2; substituting one "
                        "here would be a stand-in rather than an answer."
                    ),
                ),
            )

        payload = f"{call.unit}:{call.stage.name}:{call.input_hash}".encode()
        return KernelResult(
            # The unit directory **is** the store root, so bytes land at
            # `<unit>/artifacts/<sha256>` - the layout `_unit_dir` and K7's own
            # `_ARTIFACT_DIRECTORY` compose. Passing `<unit>/artifacts` as the root
            # would nest a second `artifacts/` inside the first.
            value=store.put(call.unit_dir, payload, "application/json"),
            evidence=Evidence(
                terms=MappingProxyType({"cache_key": call.cache_key}),
                measurements=MappingProxyType({"bytes": float(len(payload))}),
                observed=MappingProxyType({"source": source}),
            ),
            reason=None,
        )

    operations: dict[tuple[str, str], orchestrator.StageOperation] = {
        ("store", "put"): generated_put,
        ("pdf", "probe"): generated_put,
        ("image", "info"): generated_put,
    }
    # TODO: [MVP] The table is synthetic by construction, exactly as
    # `plan-01-kernels.md` §13 Track 1 requires: Stage 1 closes a flow through
    # orchestrator + store + ledger before any domain component exists. Stage 2's
    # `S2-T16` binds the real component operations, at which point this table is fed by
    # the composition root rather than declared here.
    _ = out_dir
    return MappingProxyType(operations)


def _input_hashes(descriptor: orchestrator.Descriptor) -> Mapping[str, str]:
    """Compose the input hash for every unit a descriptor declares.

    `FR-28`'s batch behaviour - a folder mirroring its tree - is `S3-T06`'s, so at this
    stage a unit's input is named by the descriptor and hashed from its name. That is
    enough for the flow to be end-to-end and deterministic, and it is honest about being
    a stand-in: a real run hashes the artifact it acquired.

    Args:
        descriptor: The descriptor to key.

    Returns:
        Unit name to input hash.

    """
    return {
        unit: hashlib.sha256(f"generated input for {unit}".encode()).hexdigest()
        for unit in descriptor.units
    }


def _key_context() -> orchestrator.KeyContext:
    """Return the cache-key context for a run.

    Args:
        Returns:
            The registry hash and the per-kernel terms.

    """
    # TODO: [MVP] The registry hash is a required key term (`prd.md` FR-08) and there is
    # no registry on disk yet - `S3-T04` populates it and `S3-T12` owns the operational
    # settings around it. A constant here is a real limitation rather than a choice: it
    # means two runs differing only in registry content compose the same key. It is
    # recorded in `run.json`'s terms and named in the epic.
    registry_hash = hashlib.sha256(b"no registry in stage 1").hexdigest()

    # Every kernel the table can execute reports the same terms: the table is
    # synthetic, so there is no engine behind it to have a revision.
    def terms() -> orchestrator.KernelTerms:
        """Return the key terms for a synthetic kernel.

        Returns:
            The terms.

        """
        return orchestrator.KernelTerms(
            kernel_version="0.1.0",
            adapter_revision="declared by S1-T18",
            model_revision="none",
        )

    return orchestrator.KeyContext(
        registry_hash=registry_hash,
        kernels=MappingProxyType(
            {
                kernel: terms()
                for kernel in ("store", "pdf", "image", "ocr", "llm.local")
            }
        ),
    )


def _now() -> str:
    """Return the current UTC time as an ISO-8601 string.

    Returns:
        The timestamp. Seconds' resolution, because a report is read by a person and a
        job's ordering is what matters, not its start to the microsecond.

    """
    return datetime.datetime.now(datetime.UTC).replace(microsecond=0).isoformat()


# --- status ------------------------------------------------------------------


def _verb_status(
    rest: Sequence[str], *, env: Mapping[str, str] | None = None
) -> Invocation:
    """Report one run in detail.

    Args:
        rest: The verb's arguments.
        env: The environment, or None for the real one.

    Returns:
        The invocation.

    Raises:
        UsageError: On a missing or unknown job id.

    """
    positionals, taken, _ = _parse(rest, values=("root",), booleans=())
    if not positionals:
        raise UsageError("status needs a job id: docflow status <job-id>")

    job = _job_for(positionals[0], _runs_root(taken, env))
    out_dir = pathlib.Path(job.out_dir)

    manifest = orchestrator.rebuild_index(out_dir)
    stages = manifest["stages"]
    assert isinstance(stages, Mapping)

    lines = [
        f"job {job.job_id}  {job.descriptor}",
        f"  state     {manifest['state']}",
        f"  control   {manifest['control']}",
        f"  units     {manifest['totals']['units']}",
        f"  in flight {len(manifest['inflight'])}",
    ]
    for unit, records in sorted(stages.items()):
        states = ", ".join(
            f"{name}={record['state']}" for name, record in records.items()
        )
        lines.append(f"  {unit}: {states}")

    return Invocation(exit_code=EXIT_OK, stdout="\n".join(lines) + "\n", stderr="")


# --- jobs --------------------------------------------------------------------


def _verb_jobs(
    rest: Sequence[str], *, env: Mapping[str, str] | None = None
) -> Invocation:
    """Report every run this surface can find.

    Args:
        rest: The verb's arguments.
        env: The environment, or None for the real one.

    Returns:
        The invocation.

    """
    _, taken, _ = _parse(rest, values=("root",), booleans=())
    root = _runs_root(taken, env)
    jobs = discover_runs(root)

    if not jobs:
        return Invocation(
            exit_code=EXIT_OK,
            stdout=f"no runs under {root}\n",
            stderr="",
        )

    lines = [f"{len(jobs)} run(s) under {root}", ""]
    for job in jobs:
        try:
            control = orchestrator.control_of(pathlib.Path(job.out_dir))
        except (FileNotFoundError, ValueError):
            control = "unknown"
        lines.append(f"  {job.job_id}  {control:<10} {job.descriptor}  pid {job.pid}")

    return Invocation(exit_code=EXIT_OK, stdout="\n".join(lines) + "\n", stderr="")


# --- pause -------------------------------------------------------------------


def _verb_pause(
    rest: Sequence[str], *, env: Mapping[str, str] | None = None
) -> Invocation:
    """Ask a run to hold at its next stage boundary.

    The run finishes the stage it is in and stops before the next one. Nothing is
    killed: a pause is a request, and the ledger is left consistent for the plain `run`
    that continues it (`FR-02`).

    Args:
        rest: The verb's arguments.
        env: The environment, or None for the real one.

    Returns:
        The invocation.

    Raises:
        UsageError: On a missing or unknown job id.

    """
    positionals, taken, _ = _parse(rest, values=("root",), booleans=())
    if not positionals:
        raise UsageError("pause needs a job id: docflow pause <job-id>")

    job = _job_for(positionals[0], _runs_root(taken, env))
    orchestrator.write_control(pathlib.Path(job.out_dir), "paused")

    return Invocation(
        exit_code=EXIT_OK,
        stdout=(
            f"job {job.job_id} paused — in-flight work finishes, then it holds.\n"
            f"run it again to continue from the exact stage.\n"
        ),
        stderr="",
    )


# --- stop --------------------------------------------------------------------


def _verb_stop(
    rest: Sequence[str], *, env: Mapping[str, str] | None = None
) -> Invocation:
    """Report what is running, and stop only when told which run.

    `FR-02`: *"`stop` with no arguments discovers and reports active runs instead of
    killing."* So a bare `stop` prints and exits, whether or not `--force` was given -
    the command an operator reaches for when unsure must be the one that cannot destroy
    anything.

    Args:
        rest: The verb's arguments.
        env: The environment, or None for the real one.

    Returns:
        The invocation.

    Raises:
        UsageError: On an unknown job id.

    """
    positionals, taken, present = _parse(rest, values=("root",), booleans=("force",))
    force = "force" in present
    root = _runs_root(taken, env)

    if not positionals:
        return _report_running(root, force=force)

    job = _job_for(positionals[0], root)
    return _stop_one(job, force=force)


def _report_running(root: pathlib.Path, *, force: bool) -> Invocation:
    """Report the runs a stop would touch, and touch none of them.

    Args:
        root: The directory to search.
        force: Whether the operator also asked for a forced stop. It changes what the
            report *says* and not what the verb *does*.

    Returns:
        The invocation.

    """
    jobs = discover_runs(root)
    running = [job for job in jobs if _is_active(job)]

    if not running:
        return Invocation(
            exit_code=EXIT_OK,
            stdout=f"nothing running under {root}\n",
            stderr="",
        )

    lines = [f"{len(running)} run(s) under {root}", ""]
    for job in running:
        lines.append(f"  {job.job_id}  {job.descriptor}  pid {job.pid}")

    lines.append("")
    if force:
        # The honest narrowing: `--force` with no id does not become a general kill.
        lines.append(
            "nothing stopped. pass a job id to stop one; "
            "--force only changes how that stop is performed.\n"
        )
    else:
        lines.append(
            "nothing stopped. pass a job id to stop one, or --force for one.\n"
        )

    return Invocation(exit_code=EXIT_OK, stdout="\n".join(lines), stderr="")


def _stop_one(job: Job, *, force: bool) -> Invocation:
    """Stop one run, gracefully or immediately.

    A graceful stop is a request the run honours at its next checkpoint - the same
    mechanism `pause` uses, because the difference between them is the *intent* rather
    than the machinery. A forced stop requests the same thing **and** signals the
    process, so a run that has not yet reached a checkpoint still learns it must not
    continue.

    The signal is sent to a process id read from a file, so this checks that the process
    is still alive before signalling: a completed run's id may have been reused, and
    signalling a stranger is worse than not signalling.

    Args:
        job: The run to stop.
        force: Whether to signal the process as well as request the stop.

    Returns:
        The invocation.

    """
    out_dir = pathlib.Path(job.out_dir)
    orchestrator.write_control(out_dir, "stopped")

    if not force:
        return Invocation(
            exit_code=EXIT_OK,
            stdout=(
                f"job {job.job_id} stopping — in-flight work finishes, then it holds.\n"
                f"run it again to continue from the exact stage.\n"
            ),
            stderr="",
        )

    if not _alive(job.pid):
        return Invocation(
            exit_code=EXIT_OK,
            stdout=(
                f"job {job.job_id} marked stopped; process {job.pid} is no longer "
                "running, so nothing was signalled.\n"
            ),
            stderr="",
        )

    os.kill(job.pid, signal.SIGTERM)
    return Invocation(
        exit_code=EXIT_OK,
        stdout=(
            f"job {job.job_id} stopped (pid {job.pid} signalled).\n"
            f"the interrupted stage reads `running`; run it again to continue.\n"
        ),
        stderr="",
    )


def _is_active(job: Job) -> bool:
    """Report whether a run has not finished.

    The predicate reads the **run state**, not ``inflight`` alone. Those differ in the
    case that matters most to this verb: a run paused *before its first stage* has no
    ledgers, so ``inflight`` is empty - and a `stop` that reported *nothing running*
    about a run an operator had just paused would be wrong about the one run they were
    asking after.

    Args:
        job: The run.

    Returns:
        True when the manifest does not report the run complete. A root whose manifest
        cannot be read is **not** reported active: an unreadable run is a fact to
        investigate rather than work to stop, and claiming it is running would invite a
        kill nobody can justify.

    """
    try:
        manifest = orchestrator.rebuild_index(pathlib.Path(job.out_dir))
    except (FileNotFoundError, ValueError, KeyError):
        return False

    return manifest["state"] != "complete"


def _alive(pid: int) -> bool:
    """Report whether a process is still running.

    Args:
        pid: The process id.

    Returns:
        True when the process can be signalled. Signal `0` performs the permission and
        existence checks without delivering anything, which is the only portable way to
        ask.

    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def main(argv: Sequence[str] | None = None) -> int:
    """Run the product surface.

    The only function that touches a stream, so every verb is tested through
    :func:`invoke` and asserted on a value.

    Args:
        argv: The arguments including the program name, or None for ``sys.argv``.

    Returns:
        The process exit code.

    """
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        result = invoke(arguments)
    except Exception as failure:  # pylint: disable=broad-except
        # A traceback here would be this surface's bug rather than a document's answer,
        # and `EXIT_INTERNAL` is the code that says so: never `EXIT_USAGE`, which would
        # collapse *broken* into *you typed it wrong*.
        print(f"docflow: internal error: {failure}", file=sys.stderr)
        return EXIT_INTERNAL

    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    return result.exit_code
