"""Run every `scripts/poc/` probe driver and aggregate the result.

Each driver calls **one kernel's adapter** directly, one method per requirement in
`my_kernel_flow.md`, and prints its own table. This runs them all and adds up what
they reported.

    python scripts/poc/run_all.py            # every driver
    python scripts/poc/run_all.py --fast     # skip ocr and the two llm drivers
    python scripts/poc/run_all.py --only pdf image

Why a subprocess per driver rather than importing them: each one calls a separate
adapter with its own optional dependency (PyMuPDF, Pillow, Docling, Ollama), and
several of them take tens of seconds. A driver that crashes must not take the run
with it, and the exit code has to survive. That is also why each driver's tally is
read from its **exit code and its summary block** rather than by sharing state.

`--fast` exists because `ocr` reloads ONNX models on every call (~10 s each, and
there is no warm path across processes) and the two `llm` drivers make real
generations - together they turn a ten-second run into a couple of minutes.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys
from typing import Final

import _lib

__all__: list[str] = []

#: The drivers, in the order the flow numbers them (`my_kernel_flow.md` §1-§5).
DRIVERS: Final[tuple[str, ...]] = (
    "pdf",
    "image",
    "ocr",
    "llm_local",
    "llm_frontier",
)

#: The drivers `--fast` skips, with the reason each is slow. `llm_frontier` is NOT
#: here: with no credential every one of its probes refuses without a request, so it
#: costs milliseconds and skipping it would hide the gate chain for no saving.
SLOW: Final[dict[str, str]] = {
    "ocr": "loads ONNX models on every call (~10 s each, no warm path per process)",
    "llm_local": "makes real generations against Ollama",
}

#: The buckets a driver's summary block reports, in its own order.
_BUCKETS: Final[tuple[str, ...]] = _lib.BUCKETS

_SUMMARY_LINE: Final[re.Pattern[str]] = re.compile(
    r"^(?P<bucket>" + "|".join(_BUCKETS) + r")\s+(?P<count>\d+)$"
)


def _parse_summary(stdout: str) -> dict[str, int]:
    """Read a driver's bucket tally out of its own summary block.

    Parsing the block rather than recounting the probe lines, because the driver
    already decided what each probe meant - the bucket is its judgement, and a
    second derivation here is a second answer that would eventually disagree.

    Args:
        stdout: The driver's standard output.

    Returns:
        The tally, with every bucket present (zero when unreported).

    """
    tally = dict.fromkeys(_BUCKETS, 0)
    for line in stdout.splitlines():
        match = _SUMMARY_LINE.match(line.strip())
        if match:
            tally[match.group("bucket")] = int(match.group("count"))
    return tally


def _run_driver(name: str, out: pathlib.Path) -> tuple[int, dict[str, int], str]:
    """Run one driver as a subprocess.

    Args:
        name: The driver's module name, without the suffix.
        out: The output root to pass through.

    Returns:
        The exit code, the parsed tally, and the driver's combined output.

    """
    script = pathlib.Path(__file__).parent / f"{name}.py"
    completed = subprocess.run(
        [sys.executable, str(script), "--out", str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    combined = completed.stdout + completed.stderr
    return completed.returncode, _parse_summary(completed.stdout), combined


def _divergences(output: str) -> list[str]:
    """Pull the divergent probe lines out of a driver's output.

    Args:
        output: The driver's combined output.

    Returns:
        One line per divergence, already formatted by the driver.

    """
    found: list[str] = []
    collecting = False
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.endswith("divergent:"):
            collecting = True
            continue
        if collecting:
            if not stripped or stripped.startswith("every probe"):
                collecting = False
                continue
            found.append(stripped)
    return found


def main(argv: list[str] | None = None) -> int:
    """Run the selected drivers and print the aggregate.

    Args:
        argv: The command-line arguments, or ``None`` for ``sys.argv``.

    Returns:
        The number of drivers that diverged, crashed, or reported a defect.

    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--out",
        type=pathlib.Path,
        default=_lib.DEFAULT_OUT,
        help="where the drivers write their generated files",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="skip the drivers that are slow (see SLOW in this module)",
    )
    parser.add_argument(
        "--only",
        nargs="+",
        choices=DRIVERS,
        help="run only these drivers",
    )
    args = parser.parse_args(argv)

    _lib.set_out(args.out)

    selected = list(args.only) if args.only else list(DRIVERS)
    skipped = [name for name in selected if args.fast and name in SLOW]
    if args.fast:
        selected = [name for name in selected if name not in SLOW]

    print(f"out    = {args.out}")
    print(f"run    = {', '.join(selected)}")
    for name in skipped:
        print(f"skip   = {name}  ({SLOW[name]})")
    print()

    totals = dict.fromkeys(_BUCKETS, 0)
    failures: list[tuple[str, str]] = []
    diverged: list[tuple[str, list[str]]] = []

    for name in selected:
        print(f"=== {name} " + "=" * (56 - len(name)))
        code, tally, output = _run_driver(name, args.out)

        for bucket, count in tally.items():
            totals[bucket] += count

        probes = sum(tally.values())
        print(
            f"    {probes} probes: "
            + ", ".join(
                f"{bucket}={tally[bucket]}" for bucket in _BUCKETS if tally[bucket]
            )
        )

        # A driver's exit code IS its count of divergent probes, so a non-zero exit
        # that no parsed divergence accounts for means it died before printing its
        # table - a crash, which is a different thing from a divergent probe.
        found = _divergences(output)
        if code != len(found):
            failures.append((name, f"exit {code} with {len(found)} divergence(s)"))
            tail = [line for line in output.splitlines() if line.strip()][-6:]
            for line in tail:
                print(f"    | {line}")

        if found:
            diverged.append((name, found))
        for line in found:
            print(f"    ! {line}")
        print()

    print("=" * 63)
    print(f"{'bucket':<14}{'count':>6}")
    for bucket in _BUCKETS:
        print(f"{bucket:<14}{totals[bucket]:>6}")
    print(f"{'probes':<14}{sum(totals.values()):>6}")
    print()

    if totally_clean(failures, diverged, totals):
        print("nothing diverged, no driver crashed, and no defect was reported.")
        return 0

    if failures:
        print("drivers that did not finish cleanly:")
        for name, detail in failures:
            print(f"  {name}: {detail}")
    if diverged:
        print("drivers with a divergent probe:")
        for name, lines in diverged:
            print(f"  {name}:")
            for line in lines:
                print(f"    {line}")
    if totals["defect"]:
        print(f"  {totals['defect']} probe(s) raised an exception.")

    return len(failures) + len(diverged) + totals["defect"]


def totally_clean(
    failures: list[tuple[str, str]],
    diverged: list[tuple[str, list[str]]],
    totals: dict[str, int],
) -> bool:
    """Report whether the aggregate run found anything to report.

    Args:
        failures: The drivers that exited non-zero.
        diverged: The drivers with at least one divergent probe.
        totals: The bucket totals across every driver.

    Returns:
        ``True`` when nothing diverged, nothing crashed and nothing raised.

    """
    return not failures and not diverged and not totals["defect"]


if __name__ == "__main__":
    sys.exit(main())
