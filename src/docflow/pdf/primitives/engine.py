"""The Poppler engine seam — the only module that knows which PDF engine is used.

Poppler is the engine this processor is built on (``docs/plan/README.md`` §9.3, from the
idea's §"Implementaciones reemplazables"). The whole of that dependency is contained here:
the binaries are named one by one, located on ``PATH``, probed for a version, and invoked
through a single runner that turns a non-zero exit into a typed failure.

Nothing outside :mod:`docflow.pdf.primitives` may import this module. Neither the
orchestrator nor another processor reaches it: both go through
:func:`docflow.pdf.process_pdf` / :func:`docflow.pdf.process_pdf_page`.

The engine is **explicit, never a substitute**. There is no configuration lookup with a
fallback reader behind it, and a missing binary raises :class:`PopplerNotAvailableError`
rather than quietly producing an empty text layer — which would be indistinguishable from
"this page has no text", the exact confusion ``docs/plan/README.md`` §7 forbids.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

POPPLER_ENGINE_NAME = "poppler"
"""Name under which every artifact records the engine that produced it.

A module-level constant rather than a parameter default: the engine is an explicit
dependency, and a name that could be overridden per call is exactly the silent substitute
``README.md`` §7 rules out. It is what lands in ``metadata.json`` as ``engine``.

# TODO: [RELEASE] Poppler is GPL-licensed; the licence posture for redistribution is a
# deployment decision, and this seam is what makes swapping the engine possible without
# touching the contract or the workflow.
"""

_VERSION_TIMEOUT_SECONDS = 10
_ENGINE_COMMAND_TIMEOUT_SECONDS = 120

# `pdftotext -v` prints "pdftotext version 25.02.0" followed by the copyright banners.
_VERSION_PATTERN = re.compile(
    r"^\s*(?P<command>\S+)\s+version\s+(?P<version>\S+)\s*$", re.MULTILINE
)

VERSION_PROBE_COMMAND_NAME = "pdftotext"
"""The binary asked for the version.

Poppler ships its tools with one shared version number, so probing one names all of them;
``pdftotext`` is the primary reader of this processor, which makes it the honest choice.
"""


class PopplerCommand(StrEnum):
    """The Poppler binaries this processor uses, named one at a time.

    An explicit list rather than a family assumed present: a binary that is missing has to
    fail where it is needed, not be discovered halfway through a document.
    """

    PDFINFO = "pdfinfo"
    PDFTOTEXT = "pdftotext"
    PDFIMAGES = "pdfimages"
    PDFSEPARATE = "pdfseparate"
    PDFTOPPM = "pdftoppm"
    PDFUNITE = "pdfunite"


VERSION_PROBE_COMMAND = PopplerCommand(VERSION_PROBE_COMMAND_NAME)
"""The version probe, as a member of the closed command list above."""


class PopplerError(RuntimeError):
    """Base of the typed failures this seam reports."""


class PopplerNotAvailableError(PopplerError):
    """A required Poppler binary is missing, or could not be identified.

    Recoverable by neither the processor nor the orchestrator: the engine is a deployment
    precondition. It is reported as a type so that a caller can classify it, never as an
    untyped crash and never as a silent substitute engine.
    """


class PopplerExecutionError(PopplerError):
    """A Poppler command ran and failed, or did not finish in time.

    Attributes:
        command: The binary that failed.
        returncode: Its exit status, or ``None`` when it had to be killed.
        stderr: Whatever it wrote to standard error.
    """

    def __init__(
        self,
        command: PopplerCommand,
        returncode: int | None,
        stderr: str,
    ) -> None:
        self.command = command
        self.returncode = returncode
        self.stderr = stderr
        outcome = (
            "did not exit in time"
            if returncode is None
            else f"exited with status {returncode}"
        )
        detail = f": {stderr.strip()}" if stderr.strip() else ""
        super().__init__(f"{command.value} {outcome}{detail}")


class PopplerOutputMissingError(PopplerError):
    """A Poppler command reported success and the expected artifact is not there.

    A post-condition guard, not a description of a known engine quirk: the command is asked
    for a single named file and the file is then confirmed to exist. No such case has been
    observed with Poppler 25.02.0 — every failure it produces, it also reports with a
    non-zero status. The guard is kept because the alternative to checking is publishing a
    path that does not exist, which is the silent stand-in ``docs/plan/README.md`` §7
    forbids, and because a check on the artifact is the only thing that stays true if the
    engine's reporting ever changes.

    Attributes:
        command: The binary that reported success.
        expected_path: The artifact that should have appeared and did not.
    """

    def __init__(self, command: PopplerCommand, expected_path: Path) -> None:
        self.command = command
        self.expected_path = expected_path
        super().__init__(
            f"{command.value} reported success but produced no file at {expected_path}"
        )


@dataclass(frozen=True)
class Engine:
    """The engine that produced an artifact, and its version.

    Attributes:
        name: Engine name — always :data:`POPPLER_ENGINE_NAME` for this implementation.
        version: Engine version, probed from the binary; never guessed and never blank.
    """

    name: str
    version: str


def get_engine_name() -> str:
    """Return the name of the engine this processor is built on.

    Returns:
        ``"poppler"``. A constant, because the engine is fixed for this implementation:
        swapping it is a change to this package, not a runtime choice.
    """
    return POPPLER_ENGINE_NAME


def find_engine_command(command: PopplerCommand) -> Path:
    """Locate one Poppler binary on ``PATH``.

    Args:
        command: The binary to locate.

    Returns:
        The absolute path of the binary.

    Raises:
        PopplerNotAvailableError: The binary is not on ``PATH``.

    # TODO: [MVP] probe for a minimum usable version instead of only for presence; the
    # PoC treats any Poppler that reports a version as usable.
    """
    located = shutil.which(command.value)
    if located is None:
        raise PopplerNotAvailableError(
            f"{command.value} was not found on PATH; the {POPPLER_ENGINE_NAME} engine "
            f"is required and no substitute is used"
        )
    return Path(located)


def get_engine_version() -> str:
    """Probe the engine for its version.

    Returns:
        The version string the engine reports, e.g. ``"25.02.0"``.

    Raises:
        PopplerNotAvailableError: The binary is missing, or did not report a version this
            module can read. A blank or ``"unknown"`` version is never returned: the
            provenance of an artifact has to name a real engine version.
    """
    binary = find_engine_command(VERSION_PROBE_COMMAND)
    try:
        completed = subprocess.run(
            [str(binary), "-v"],
            capture_output=True,
            text=True,
            check=False,
            timeout=_VERSION_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as failure:
        raise PopplerNotAvailableError(
            f"{VERSION_PROBE_COMMAND} could not be probed for a version: {failure}"
        ) from failure

    match = _VERSION_PATTERN.search(f"{completed.stdout}\n{completed.stderr}")
    if match is None:
        raise PopplerNotAvailableError(
            f"{VERSION_PROBE_COMMAND} reported no readable version: "
            f"{completed.stdout.strip()!r}"
        )
    return match.group("version")


def get_engine() -> Engine:
    """Return the engine and its version, for an artifact's provenance.

    Returns:
        The engine record to be recorded in ``metadata.json``.

    Raises:
        PopplerNotAvailableError: The engine is missing or unidentifiable.
    """
    return Engine(name=get_engine_name(), version=get_engine_version())


def run_engine_command(
    command: PopplerCommand,
    arguments: Sequence[str],
    *,
    timeout: int = _ENGINE_COMMAND_TIMEOUT_SECONDS,
) -> str:
    """Run one Poppler binary and return its standard output.

    The single place a Poppler process is spawned, so that every failure mode of the engine
    is typed in one function instead of being re-decided by each primitive.

    Args:
        command: The binary to run.
        arguments: Its arguments, in order.
        timeout: Seconds to wait before killing it. Explicit: a PDF that never finishes is
            a failure to report, not a hang to inherit.

    Returns:
        The command's standard output, decoded as text.

    Raises:
        PopplerNotAvailableError: The binary is not on ``PATH``.
        PopplerExecutionError: The command exited non-zero, or exceeded ``timeout``.
    """
    binary = find_engine_command(command)
    try:
        completed = subprocess.run(
            [str(binary), *arguments],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as failure:
        raise PopplerExecutionError(
            command,
            None,
            f"timed out after {timeout}s",
        ) from failure
    except OSError as failure:
        raise PopplerExecutionError(command, None, str(failure)) from failure

    if completed.returncode != 0:
        raise PopplerExecutionError(command, completed.returncode, completed.stderr)
    return completed.stdout
