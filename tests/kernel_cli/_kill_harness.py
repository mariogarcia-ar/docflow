"""Drive the Stage 1 flow in a subprocess and kill it mid-stage (`E08-01` / `S1-T19`).

This is the harness the gate's kill criterion needs, and it exists as a *separate
process* for one reason: **a real `SIGKILL` cannot be observed from inside the process
it kills.** An in-process exception at the same point would leave the same ledger, and
that is exactly the confusion this file avoids - a simulated kill and a real one are
different evidence, and the gate asks for the real one.

The script runs the three-stage descriptor over a unit set, and deliberately kills
itself during one named stage, **after that stage has begun**. `store.begin` writes
`running` before the operation is called, so what the ledger says afterwards is the
claim a kill leaves behind.

Usage:

    python tests/kernel_cli/_kill_harness.py <out-dir> <stage> [<signal>]

The exit status is the signal's when the kill happened, and non-zero for a usage
problem. Nothing is printed on the success path: the evidence is the ledger, not a log.
"""

# `import-outside-toplevel`: every kernel import is inside the function that needs it,
# so the harness module itself imports without the kernel package - which is what lets
# the subprocess fail with a clear error rather than at import time.
# pylint: disable=import-outside-toplevel

from __future__ import annotations

import os
import pathlib
import signal
import sys

# The three stages, matching `descriptors/synthetic-3stage.yaml`. Not read from the file
# because this harness needs the *stage names* before the run starts, to decide where to
# die - and reading the graph to then re-read it inside the run would be two readers of
# one file.
STAGES: tuple[str, ...] = ("acquire", "transform", "persist")


def _install_kill(stage: str, signum: int) -> dict[tuple[str, str], object]:
    """Build the operation table, with one stage made fatal.

    Two operations, one per ``(kernel, op)`` pair the graph declares, and each decides
    by ``call.stage.name`` whether it is the stage to die in. The table is keyed the way
    the orchestrator keys it, so the harness dispatches the same graph the descriptor
    declares without parsing YAML to find out.

    Args:
        stage: The stage during which to die.
        signum: The signal to send. `SIGKILL` is the faithful one: the process gets no
            chance to write anything, which is what makes the ledger the only record.

    Returns:
        The table, keyed by ``(kernel, op)``.

    """
    from docflow.kernels import store
    from docflow.kernels.types import Artifact, Evidence, KernelResult

    def operation(call: object) -> KernelResult[Artifact]:
        """Store the stage's bytes, or die.

        Args:
            call: The dispatch call. Typed loosely because this file is a harness, and
                importing the orchestrator's `StageCall` at module scope would make the
                harness unimportable without the kernel package.

        Returns:
            The stored artifact. When this is the kill stage, it does not return.

        """
        name = call.stage.name  # type: ignore[attr-defined]
        if name == stage:
            # The ledger already reads `running`: `_dispatch` called `store.begin`
            # before reaching here. That ordering is what this harness proves, and the
            # signal is real so nothing unwinds and nothing is written on the way out.
            os.kill(os.getpid(), signum)

        # Both attribute accesses are on the dispatch call, which is typed loosely here
        # because importing `StageCall` at module scope would make this harness
        # unimportable without the kernel package.
        unit = call.unit  # type: ignore[attr-defined]
        input_hash = call.input_hash  # type: ignore[attr-defined]
        unit_dir = call.unit_dir  # type: ignore[attr-defined]
        payload = f"{unit}:{name}:{input_hash}".encode()
        artifact = store.put(
            unit_dir,
            payload,
            media_type="application/octet-stream",  # type: ignore[attr-defined]
        )
        return KernelResult(
            value=artifact,
            evidence=Evidence(terms={}, measurements={}, observed={}),
            reason=None,
        )

    return {("store", "put"): operation, ("pdf", "probe"): operation}


def main(argv: list[str]) -> int:
    """Run the flow and kill it during the named stage.

    Args:
        argv: ``[out_dir, stage, signal]``.

    Returns:
        A non-zero status on a usage problem; otherwise the process never returns on the
        kill path, and returns 0 if the named stage is not in the graph.

    """
    if len(argv) < 3:
        print("usage: _kill_harness.py <out-dir> <stage> [<signal>]", file=sys.stderr)
        return 2

    out_dir = pathlib.Path(argv[1])
    stage = argv[2]
    signum = int(argv[3]) if len(argv) > 3 else int(signal.SIGKILL)

    if stage not in STAGES:
        print(f"unknown stage {stage!r}; known: {list(STAGES)}", file=sys.stderr)
        return 2

    from docflow.kernels import orchestrator

    descriptor = orchestrator.descriptor_from_mapping(
        {
            "unit": "synthetic",
            "units": ["U-0001", "U-0002"],
            "stages": [
                {"name": "acquire", "kernel": "store", "op": "put"},
                {
                    "name": "transform",
                    "kernel": "pdf",
                    "op": "probe",
                    "needs": ["acquire"],
                },
                {
                    "name": "persist",
                    "kernel": "store",
                    "op": "put",
                    "needs": ["transform"],
                },
            ],
        }
    )

    operations = _install_kill(stage, signum)
    keys = orchestrator.KeyContext(
        registry_hash="a" * 64,
        kernels={
            kernel: orchestrator.KernelTerms(
                kernel_version="1", adapter_revision="harness", model_revision="none"
            )
            for kernel in ("store", "pdf")
        },
    )
    hashes = {
        unit: f"{unit}-input".encode().hex().ljust(64, "0") for unit in descriptor.units
    }

    orchestrator.run(
        descriptor,
        out_dir,
        input_hashes=hashes,
        operations=operations,
        keys=keys,
        slots=orchestrator.SLOT_BOUNDS,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
