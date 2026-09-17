"""K1's commands - `orchestrator` (`E07-02` / `S1-T21`).

Eight `now` commands, and the ones that matter most are `run` and `ledger-read`:
they are the two halves of the Stage 1 gate. `run` drives the graph; `ledger-read`
reports what the graph did **together with the verification outcome**, because
verification is an outcome of reading and never a request (`kernel-cli.md` §9).

`run` is the only command on this whole surface that touches K1, and it is where the
`synthetic-3stage.yaml` descriptor becomes a flow a shell can close. The operation
table it dispatches through is bound **here** and not in the dispatcher: K1 executes
a graph it did not write and knows no operation by name, so the binding is the
composition root's job.

`orchestrator status`, `jobs`, `pause`, `resume` and `stop` are the product surface's
verbs (`FR-01`, `FR-02`). They are exposed here because §9 lists them, and they read
and write the same `job.json` and `control.json` the product surface does - one
mechanism, two doorways, no second implementation.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from docflow.kernel_cli.commands.descriptor import read_descriptor_mapping
from docflow.kernel_cli.commands.refusals import answered
from docflow.kernel_cli.main import Call, Handler
from docflow.kernels import orchestrator
from docflow.kernels import store as k7
from docflow.kernels.types import Artifact, Evidence, KernelResult, Reason


def _descriptor(path: str) -> orchestrator.Descriptor:
    """Read a descriptor from a JSON or YAML file.

    Args:
        path: The descriptor's path.

    Returns:
        The parsed descriptor.

    """
    return orchestrator.read_descriptor(Path(path), _read_mapping)


def _read_mapping(path: Path) -> Any:
    """Read a descriptor file, through the composition root's reader.

    The seam is `orchestrator.read_descriptor`'s injected callable, and
    `descriptor.read_descriptor_mapping` is what binds it. Delegating rather than
    parsing here keeps the vendor (PyYAML) in one module that names it.

    Args:
        path: The descriptor's path.

    Returns:
        The parsed mapping.

    """
    return read_descriptor_mapping(path)


def _stage_operations(
    out_dir: Path,
) -> dict[tuple[str, str], orchestrator.StageOperation]:
    """Bind the operations a run's stages dispatch through.

    Two operations, and both are **synthetic**: `store put` produces bytes from the
    stage's own key, and `pdf probe` stores a description of what it saw. That is
    what the descriptor declares (`params: {source: generated}`), and it is what
    makes the Stage 1 flow close without Docling, Ollama or a provider - the
    adapters exist and are exercised on their own commands, but the *graph* does not
    depend on them.

    A descriptor naming an operation this table lacks is refused by
    `orchestrator.validate` before the first ledger is touched, so an unimplemented
    operation is a typed refusal rather than a stand-in.

    Args:
        out_dir: The run's output root.

    Returns:
        The table, keyed by ``(kernel, op)``.

    """
    del out_dir

    def put(call: orchestrator.StageCall) -> KernelResult[Artifact]:
        """Store bytes derived from the stage's identity.

        Args:
            call: The dispatch call.

        Returns:
            The stored artifact.

        """

        payload = f"{call.unit}:{call.stage.name}:{call.input_hash}".encode()
        artifact = k7.put(call.unit_dir, payload, media_type="application/octet-stream")
        return KernelResult(
            value=artifact,
            evidence=Evidence(
                terms=MappingProxyType({"cache_key": call.cache_key}),
                measurements=MappingProxyType({"bytes": float(artifact.size_bytes)}),
                observed=MappingProxyType({"unit": call.unit, "synthetic": "true"}),
            ),
            reason=None,
        )

    def probe(call: orchestrator.StageCall) -> KernelResult[Artifact]:
        """Store a description of what the stage was handed.

        Args:
            call: The dispatch call.

        Returns:
            The stored artifact.

        """

        payload = f"probe:{call.unit}:{sorted(call.needs)}".encode()
        artifact = k7.put(call.unit_dir, payload, media_type="application/octet-stream")
        return KernelResult(
            value=artifact,
            evidence=Evidence(
                terms=MappingProxyType({"cache_key": call.cache_key}),
                measurements=MappingProxyType({"needs": float(len(call.needs))}),
                observed=MappingProxyType({"unit": call.unit, "synthetic": "true"}),
            ),
            reason=None,
        )

    return {("store", "put"): put, ("pdf", "probe"): probe}


def _key_context(descriptor: orchestrator.Descriptor) -> orchestrator.KeyContext:
    """Compose the cache-key context for a run.

    Args:
        descriptor: The descriptor being run.

    Returns:
        The registry hash and the per-kernel terms.

    """

    def terms() -> orchestrator.KernelTerms:
        """Return the terms for a synthetic kernel.

        Returns:
            The terms.

        """
        return orchestrator.KernelTerms(
            kernel_version="0.1.0",
            adapter_revision="synthetic bench",
            model_revision="none",
        )

    # TODO: [MVP] A constant registry hash: there is no registry on disk until
    # S3-T04, so two runs differing only in registry content compose the same key.
    # Recorded in E06-01 as well, and named in run.json's terms.
    return orchestrator.KeyContext(
        registry_hash=hashlib.sha256(b"no registry in stage 1").hexdigest(),
        kernels=MappingProxyType(
            {stage.kernel: terms() for stage in descriptor.graph.stages}
        ),
    )


def _slots(cpu_jobs: object, raw_slots: object) -> orchestrator.SlotBounds:
    """Resolve the per-slot bounds from the command's flags.

    The parameter is named `cpu_jobs` rather than `jobs` because `jobs` is a **command**
    on this surface: `orchestrator jobs` discovers runs. `NFR-04` puts `--jobs` on the
    `cpu` slot, and the bound is the same quantity under a name that cannot be
    confused with the verb.

    Args:
        cpu_jobs: The `--jobs` value, or None.
        raw_slots: The `--slots` value, or None.

    Returns:
        The bounds.

    Raises:
        ValueError: If a bound is unparseable or outside what the model permits.

    """
    bounds: dict[str, int] = dict(orchestrator.SLOT_BOUNDS.as_mapping())
    if cpu_jobs is not None:
        bounds["cpu"] = int(str(cpu_jobs))
    if raw_slots is not None:
        for pair in str(raw_slots).split(","):
            name, _, value = pair.partition("=")
            if not name.strip() or not value.strip():
                raise ValueError(
                    f"--slots must be a comma-separated list of name=value pairs; "
                    f"got {pair!r}"
                )
            bounds[name.strip()] = int(value.strip())
    return orchestrator.SlotBounds(bounds=MappingProxyType(bounds))


def plan(*, descriptor: str, out: str, **_: object) -> Call:
    """Validate a descriptor without dispatching anything.

    `kernel-cli.md` §6 step 3: exit `0`, no artifact written, no stage dispatched.
    The wrong result it guards against is *"a plan that already ran work"*.

    Args:
        descriptor: The descriptor to validate.
        out: Where the run's output root would be.
        **_: Accepted, so an unknown flag reaches the dispatcher.

    Returns:
        The call, whose value is a mapping describing what was validated.

    """
    del out
    parsed = _descriptor(descriptor)
    orchestrator.validate(
        parsed,
        _input_hashes(parsed),
        _stage_operations(Path(".")),
        _key_context(parsed),
        orchestrator.SLOT_BOUNDS,
    )
    return Call(
        result=KernelResult(
            value={
                "units": list(parsed.units),
                "stages": [stage.name for stage in parsed.graph.stages],
                "order": list(parsed.graph.order),
            },
            evidence=Evidence(
                terms=MappingProxyType({"descriptor": descriptor}),
                measurements=MappingProxyType(
                    {"stages": float(len(parsed.graph.stages))}
                ),
                observed=MappingProxyType({"dispatched": "false"}),
            ),
            reason=None,
        )
    )


def run(
    *,
    descriptor: str,
    out: str,
    jobs: object = None,  # pylint: disable=redefined-outer-name
    slots: object = None,
    **_: object,
) -> Call:
    """Drive a descriptor's graph and report what it did.

    Args:
        descriptor: The descriptor to run.
        out: The run's output root.
        jobs: The `--jobs` bound for the `cpu` slot.
        slots: The `--slots` bounds, as `cpu=n,gpu=n,remote=n`.
        **_: Accepted, so an unknown flag reaches the dispatcher.

    Returns:
        The call, whose value is the report.

    Raises:
        ValueError: If a bound is unusable, or the descriptor is refused.

    """
    parsed = _descriptor(descriptor)
    out_dir = Path(out)
    report = orchestrator.run(
        parsed,
        out_dir,
        input_hashes=_input_hashes(parsed),
        operations=_stage_operations(out_dir),
        keys=_key_context(parsed),
        slots=_slots(jobs, slots),
    )
    return Call(
        result=KernelResult(
            value={
                "dispatched": [list(pair) for pair in report.dispatched],
                "skipped": [list(pair) for pair in report.skipped],
                "blocked": [list(pair) for pair in report.blocked],
                "held": list(report.held),
                "unverified": [list(pair) for pair in report.unverified],
                "failed": [[unit, list(stages)] for unit, stages in report.failed],
            },
            evidence=Evidence(
                terms=MappingProxyType({"descriptor": descriptor}),
                measurements=MappingProxyType(
                    {"dispatched": float(len(report.dispatched))}
                ),
                observed=MappingProxyType(
                    {"state": str(report.manifest["state"]), "out": str(out_dir)}
                ),
            ),
            reason=None,
        )
    )


def _input_hashes(descriptor: orchestrator.Descriptor) -> dict[str, str]:
    """Derive one input hash per unit.

    Synthetic, and the seed is the unit's own name, so the flow is reproducible and
    two units never share a key.

    Args:
        descriptor: The descriptor.

    Returns:
        Unit name to input hash.

    """

    return {
        unit: hashlib.sha256(f"generated input for {unit}".encode()).hexdigest()
        for unit in descriptor.units
    }


def ledger_read(*, unit: str, **_: object) -> Call:
    """Read a unit's ledger, **with** its verification outcome.

    The verification is not a flag and not a separate command: it is what reading a
    ledger *reports*, and this command is the visible half of that
    (`kernel-cli.md` §9, ADR-006).

    Args:
        unit: The unit directory.
        **_: Accepted, so an unknown flag reaches the dispatcher.

    Returns:
        The call, whose value is the ledger and its unverified stages.

    """
    verified = orchestrator.read_ledger(Path(unit))
    ledger = verified.ledger
    return Call(
        result=KernelResult(
            value={
                "unit": ledger.unit,
                "stages": {
                    name: dict(record.as_mapping())
                    for name, record in ledger.stages.items()
                },
                "unverified": dict(verified.unverified),
            },
            evidence=Evidence(
                terms=MappingProxyType({"unit": ledger.unit}),
                measurements=MappingProxyType({"stages": float(len(ledger.stages))}),
                observed=MappingProxyType(
                    {"trustworthy": str(verified.trustworthy).lower()}
                ),
            ),
            reason=None,
        )
    )


def manifest_rebuild(*, out: str, **_: object) -> Call:
    """Rebuild the manifest from the ledgers alone, and write it.

    `write_index` rather than `rebuild_index`, and the difference is the command's
    subject. `rebuild_index` *derives* the manifest and hands it back - which is what
    a caller who wants to compare two of them needs. This command's subject is the
    **file**: `kernel-cli.md` §6 step 11 deletes `run.json` and expects the command to
    reproduce it, and a command that only derived one would leave the tree exactly as
    it found it while reporting success.

    Writing it is still one authority: `write_index` derives by calling
    `rebuild_index` and writes what that returned, so the file is derived rather than
    assembled (`E05-01`).

    Args:
        out: The run's output root.
        **_: Accepted, so an unknown flag reaches the dispatcher.

    Returns:
        The call, carrying the manifest that was written.

    """
    return Call(
        result=KernelResult(
            value=dict(orchestrator.write_index(Path(out))),
            evidence=Evidence(
                terms=MappingProxyType({"out": out}),
                measurements=MappingProxyType({}),
                observed=MappingProxyType({"derived": "true", "written": "true"}),
            ),
            reason=None,
        )
    )


def status(*, job: str, **_: object) -> Call:
    """Report a run's state from its manifest.

    Args:
        job: The run's output root, which is what a job id addresses.
        **_: Accepted, so an unknown flag reaches the dispatcher.

    Returns:
        The call, whose value is the run's state.

    """
    manifest = orchestrator.rebuild_index(Path(job))
    return Call(
        result=KernelResult(
            value={
                "state": manifest["state"],
                "control": manifest["control"],
                "totals": manifest["totals"],
                "inflight": manifest["inflight"],
            },
            evidence=Evidence(
                terms=MappingProxyType({"job": job}),
                measurements=MappingProxyType({}),
                observed=MappingProxyType({"derived": "true"}),
            ),
            reason=None,
        )
    )


def jobs(*, root: str = ".", **_: object) -> Call:
    """Discover runs under a root.

    Args:
        root: Where to look for run output roots.
        **_: Accepted, so an unknown flag reaches the dispatcher.

    Returns:
        The call, whose value lists the runs found.

    """
    found: list[dict[str, object]] = []
    for path in sorted(Path(root).glob(f"*/{orchestrator.MANIFEST_NAME}")):
        manifest = orchestrator.rebuild_index(path.parent)
        found.append({"out": str(path.parent), "state": manifest["state"]})
    return Call(
        result=answered(
            found,
            terms={"root": root, "discovered": "true"},
            measurements={"runs": float(len(found))},
        )
    )


def pause(*, job: str, **_: object) -> Call:
    """Ask a run to hold at its next checkpoint.

    Args:
        job: The run's output root.
        **_: Accepted, so an unknown flag reaches the dispatcher.

    Returns:
        The call, whose value is the control that was written.

    """
    control = orchestrator.write_control(Path(job), "paused")
    return Call(
        result=KernelResult(
            value={"control": control.state},
            evidence=Evidence(
                terms=MappingProxyType({"job": job}),
                measurements=MappingProxyType({}),
                observed=MappingProxyType({"requested": "paused"}),
            ),
            reason=None,
        )
    )


def resume(*, job: str, **_: object) -> Call:
    """Clear a run's hold so the next `run` continues.

    There is no separate resume verb on the product surface - a plain `run` is the
    resume (`FR-01`). This command exists because §9 lists it as K1's `pause`/
    `resume` pair, and it writes the same `control.json`.

    Args:
        job: The run's output root.
        **_: Accepted, so an unknown flag reaches the dispatcher.

    Returns:
        The call, whose value is the control that was written.

    """
    control = orchestrator.write_control(Path(job), "running")
    return Call(
        result=KernelResult(
            value={"control": control.state},
            evidence=Evidence(
                terms=MappingProxyType({"job": job}),
                measurements=MappingProxyType({}),
                observed=MappingProxyType({"requested": "running"}),
            ),
            reason=None,
        )
    )


def stop(*, job: str, force: object = False, **_: object) -> Call:
    """Ask a run to stop.

    `--force` changes *how* the run stops, never *what* stops. With no job it stops
    nothing, which is the same rule the product surface follows: a bare `stop` is a
    request to hold, not a licence to kill whatever is running.

    Args:
        job: The run's output root.
        force: Whether to also terminate the recorded process.
        **_: Accepted, so an unknown flag reaches the dispatcher.

    Returns:
        The call, whose value is the control that was written.

    """
    control = orchestrator.write_control(Path(job), "stopped")
    terminated = False
    if force:
        terminated = _terminate(Path(job))
    return Call(
        result=KernelResult(
            value={"control": control.state, "terminated": terminated},
            evidence=Evidence(
                terms=MappingProxyType({"job": job}),
                measurements=MappingProxyType({}),
                observed=MappingProxyType(
                    {"requested": "stopped", "force": str(bool(force)).lower()}
                ),
            ),
            reason=None,
        )
    )


def _terminate(out_dir: Path) -> bool:
    """Terminate the process a run recorded, if it is still alive.

    Args:
        out_dir: The run's output root.

    Returns:
        True when a signal was delivered.

    """
    job_file = out_dir / "job.json"
    if not job_file.is_file():
        return False
    recorded = json.loads(job_file.read_text(encoding="utf-8"))
    pid = recorded.get("pid")
    if not isinstance(pid, int):
        return False
    try:
        os.kill(pid, 15)
    except (ProcessLookupError, PermissionError):
        return False
    return True


#: A command this module declares but does not implement, and why. Declared rather
#: than omitted so *"not implemented"* and *"does not exist"* stay distinguishable.
MVP_COMMANDS: Final[tuple[tuple[str, str], ...]] = (("orchestrator", "rebuild-index"),)


#: What this module declares, as ``(operation, handler, positional, flags)``.
#:
#: ``plan`` and ``run`` take the descriptor as a **bare argument**, because that is
#: what a descriptor is: which graph to execute, not a parameter of one. `--out` is
#: the run's output root and is deliberately not `--root` - that is which store a
#: kernel reads, and a command needing both would mean the boundary had been crossed
#: (`kernel-cli.md` §10).
COMMANDS: Final[tuple[tuple[str, Handler | None, str, tuple[str, ...]], ...]] = (
    ("plan", plan, "descriptor", ("--out",)),
    ("run", run, "descriptor", ("--out", "--jobs", "--slots")),
    ("ledger-read", ledger_read, "unit", ()),
    ("manifest-rebuild", manifest_rebuild, "out", ()),
    ("status", status, "job", ()),
    ("jobs", jobs, "", ("--root",)),
    ("pause", pause, "job", ()),
    ("resume", resume, "job", ()),
    ("stop", stop, "job", ("--force",)),
)


def reason_for(message: str) -> Reason:
    """Build the typed refusal this module uses for an unusable argument.

    Args:
        message: What is wrong.

    Returns:
        A `Reason` in the closed vocabulary.

    """
    return Reason(code="asset_invalid", message=message)
