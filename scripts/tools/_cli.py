"""Shared plumbing for the lab tools under ``scripts/tools/`` (``SCR-01``).

This module is **not** a tool: it holds no contract, reaches no engine and imports nothing
from ``docflow``. It is the plumbing five callers would otherwise copy five times — the
output root, fixture resolution, the run header, the two printers and the exit-code mapping
— and nothing more. Nothing under ``src/docflow/`` may import it; the dependency runs one
way (``scripts/`` → ``src/``), and the guard test asserts it rather than trusting it.

The module is deliberately free of any processor vocabulary: it never names a PDF, an image,
an OCR or an LLM type, so a sixth tool for a sixth processor would need no change here.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

#: Repository root, derived from this file's own location (``scripts/tools/_cli.py``).
REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]

#: The two committed fixture roots a bare fixture name is resolved against.
FIXTURES_ROOT: Final[Path] = REPO_ROOT / "tests" / "fixtures"
FIXTURES_TXT_ROOT: Final[Path] = REPO_ROOT / "tests" / "fixtures-txt"

#: The default output root of every tool: ``var/tools/<tool>/`` (``/var/`` is ignored).
TOOLS_OUTPUT_ROOT: Final[Path] = REPO_ROOT / "var" / "tools"

#: How many characters of the input's SHA-256 name a run directory. Enough to tell two
#: inputs apart, short enough to read; the same input always lands in the same directory.
HASH_PREFIX_LENGTH: Final[int] = 8

#: Exit code of a typed failure the library returned and the tool printed.
FAILURE_EXIT: Final[int] = 1

#: Statuses that mean the run failed. Everything else — ``success``, ``partial``,
#: ``partial_success``, ``PAUSED`` — produced a result, and a result is a success here.
FAILED_STATUSES: Final[frozenset[str]] = frozenset({"failed", "FAILED"})


class FixtureNotFoundError(LookupError):
    """A fixture name resolved to nothing under any of the fixture roots.

    The tool turns this into a usage error (exit ``2``): an input the caller named but that
    does not exist is the caller's mistake, not a typed failure of the library.
    """


def file_digest(path: Path) -> str:
    """Return the SHA-256 of a file, read in bounded chunks.

    Args:
        path: The file to read.

    Returns:
        The digest, in hexadecimal.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def output_root(tool: str, input_path: Path, *, out: str | Path | None = None) -> Path:
    """Return the directory a tool's run writes under.

    The same input always lands in the same directory — the name carries the first
    :data:`HASH_PREFIX_LENGTH` characters of its SHA-256 — so a run can be repeated and
    compared, while two distinct inputs can never collide. Output is never written beside
    the input and never into ``out/``.

    Args:
        tool: The tool's name, one directory level under ``var/tools/``.
        input_path: The run's input; its bytes name the directory.
        out: An explicit output directory, which replaces the default root entirely.

    Returns:
        The absolute output directory. It is not created here: the library's own
        publication creates the directories it writes into.
    """
    if out is not None:
        return Path(out).expanduser().resolve()
    prefix = file_digest(input_path)[:HASH_PREFIX_LENGTH]
    return TOOLS_OUTPUT_ROOT / tool / f"{input_path.stem}-{prefix}"


def resolve_fixture(
    name: str,
    *,
    fixtures_root: str | Path | None = None,
    text: bool = False,
) -> Path:
    """Resolve a fixture name, or a path, to an absolute path that exists.

    A **path** is taken as given; a **bare name** — optionally with a subdirectory, e.g.
    ``casos/<uuid>.txt`` — is searched under the committed fixture roots. The caller prints
    the returned path, so a resolved fixture is never silent.

    Args:
        name: A path, or a name relative to a fixture root.
        fixtures_root: A root that replaces both defaults when stated.
        text: Search ``tests/fixtures-txt/`` first, for a text input.

    Returns:
        The resolved absolute path.

    Raises:
        FixtureNotFoundError: When the name resolves to no existing file.
    """
    candidate = Path(name).expanduser()
    if candidate.is_file():
        return candidate.resolve()

    if fixtures_root is not None:
        roots: tuple[Path, ...] = (Path(fixtures_root).expanduser(),)
    elif text:
        roots = (FIXTURES_TXT_ROOT, FIXTURES_ROOT)
    else:
        roots = (FIXTURES_ROOT, FIXTURES_TXT_ROOT)

    for root in roots:
        resolved = root / name
        if resolved.is_file():
            return resolved.resolve()

    searched = ", ".join(str(root) for root in roots)
    raise FixtureNotFoundError(f"fixture {name!r} was not found under {searched}")


def add_input_argument(subparser: argparse.ArgumentParser) -> None:
    """Add the positional input to a subparser.

    The positional belongs to the subcommand (``pdf.py inspect <input>``), while
    ``--fixture`` is a global option (``pdf.py --fixture <name> inspect``): both spellings
    the runbook quotes work, and either may be used.

    Args:
        subparser: The subparser to extend.
    """
    subparser.add_argument(
        "input",
        nargs="?",
        help="Input path or a bare fixture name. Optional when --fixture is given.",
    )


def add_common_arguments(
    parser: argparse.ArgumentParser, *, identity: bool = False
) -> None:
    """Add the arguments every tool shares.

    Args:
        parser: The parser to extend.
        identity: Also add ``--document-id`` and ``--run-id``, for a tool whose contract
            carries correlation metadata. A tool whose contract does not (``workflow.py``)
            leaves them out rather than shipping a flag that does nothing.
    """
    parser.add_argument(
        "--fixture",
        help="Fixture name resolved under tests/fixtures/ or tests/fixtures-txt/.",
    )
    parser.add_argument(
        "--fixtures-root",
        help="A root that replaces both default fixture roots for this run.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the machine-readable payload instead of the human summary.",
    )
    parser.add_argument(
        "--out",
        help="Output directory; replaces var/tools/<tool>/<stem>-<hash8>/ entirely.",
    )
    if identity:
        parser.add_argument(
            "--document-id",
            help="Document identity recorded in the request's context; defaults to the "
            "input's file name.",
        )
        parser.add_argument(
            "--run-id",
            help="Run identity recorded in the request's context; defaults to a "
            "tool-derived identity printed in the header.",
        )


def resolve_input(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    *,
    text: bool = False,
) -> Path:
    """Return the absolute input path the flags describe, or fail as a usage error.

    Args:
        args: The parsed arguments of a tool that added the common arguments.
        parser: The parser to report a usage error through.
        text: Prefer the text fixture root for a bare name.

    Returns:
        The resolved absolute input path.
    """
    name = args.fixture if args.fixture is not None else getattr(args, "input", None)
    if name is None:
        parser.error("an input is required: pass a path or --fixture NAME")
    try:
        return resolve_fixture(name, fixtures_root=args.fixtures_root, text=text)
    except FixtureNotFoundError as missing:
        parser.error(str(missing))
        raise  # unreachable: parser.error exits; kept so the return type is honest


def identity_for(
    args: argparse.Namespace, tool: str, input_path: Path
) -> tuple[str, str]:
    """Return the ``(document_id, workflow_run_id)`` a request's context carries.

    Both are derived from what the caller stated, or from the input itself; both are printed
    in the run header, so a derived identity is stated rather than implied.

    Args:
        args: The parsed arguments, which may carry ``--document-id`` and ``--run-id``.
        tool: The tool's name, part of the derived run identity.
        input_path: The input, whose name seeds the derived identities.

    Returns:
        The document identity and the run identity.
    """
    document_id = getattr(args, "document_id", None) or input_path.stem
    run_id = getattr(args, "run_id", None) or run_id_for(tool, input_path)
    return document_id, run_id


def run_id_for(tool: str, input_path: Path) -> str:
    """Return the run identity derived from a tool and its input.

    Args:
        tool: The tool's name.
        input_path: The input, whose digest makes the identity reproducible.

    Returns:
        A short, reproducible run identity.
    """
    prefix = file_digest(input_path)[:HASH_PREFIX_LENGTH]
    return f"tool-{tool}-{prefix}"


def print_header(
    tool: str,
    subcommand: str,
    input_path: Path,
    output_root: Path,
    *,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """Print the run header to stderr: what was resolved, and where output goes.

    stderr on purpose: the human summary or the ``--json`` payload on stdout stays clean,
    while a resolved fixture and a derived identity are still never silent.

    Args:
        tool: The tool's name.
        subcommand: The subcommand being run.
        input_path: The absolute, resolved input path.
        output_root: The absolute output directory.
        extra: Any further facts the tool wants stated, one line each.
    """
    lines = [
        f"== {tool}.py {subcommand} ==",
        f"input:  {input_path}",
        f"output: {output_root}",
    ]
    for key, value in (extra or {}).items():
        lines.append(f"{key}: {value}")
    print("\n".join(lines), file=sys.stderr)


def print_result(payload: Mapping[str, Any], *, as_json: bool) -> None:
    """Print a result, as the human summary or as the machine-readable payload.

    Args:
        payload: The payload, built from the result's own fields.
        as_json: Print canonical JSON instead of one ``key: value`` line per field.
    """
    if as_json:
        print(json.dumps(payload, indent=2, default=_json_default))
        return
    for key, value in payload.items():
        print(f"{key}: {_human(value)}")


def print_error(records: Sequence[Any]) -> int:
    """Print typed failure records and return the failure exit code.

    The library types its failures and returns them; a tool prints them and exits ``1``. It
    never raises one, and it never shows a traceback for a failure the library already typed.

    Args:
        records: The typed error records, as dataclasses or mappings.

    Returns:
        :data:`FAILURE_EXIT`.
    """
    for record in records:
        fields = _record_mapping(record)
        kind = fields.get("type", "ERROR")
        message = fields.get("message", "")
        print(f"ERROR {kind}: {message}")
        details = {
            key: value
            for key, value in fields.items()
            if key not in ("type", "message")
        }
        if details:
            print(f"  {json.dumps(details, default=_json_default)}")
    return FAILURE_EXIT


def exit_code_for(result: Any) -> int:
    """Return the exit code a finished run maps to.

    Args:
        result: A result object carrying a ``status``, or a status string itself.

    Returns:
        ``1`` when the status names a failure, ``0`` otherwise. A partially failed run
        produced a result and is a success here; only ``failed`` is not.
    """
    status = result if isinstance(result, str) else getattr(result, "status", None)
    return FAILURE_EXIT if _status_name(status) in FAILED_STATUSES else 0


def _status_name(status: Any) -> str:
    """Return a status as a plain string, reading an enum's value when it has one."""
    if status is None:
        return ""
    return str(getattr(status, "value", status))


def _json_default(value: Any) -> str:
    """Serialize a value the JSON encoder does not know, e.g. a ``Path``."""
    return str(value)


def _human(value: Any) -> str:
    """Render one payload value as a single readable line."""
    if isinstance(value, Path):
        return str(value)
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    if isinstance(value, (list, tuple)):
        if not value:
            return "[]"
        if all(isinstance(item, (str, int, float, bool, Path)) for item in value):
            return ", ".join(str(item) for item in value)
        return json.dumps(value, default=_json_default)
    return json.dumps(value, default=_json_default)


def _record_mapping(record: Any) -> dict[str, Any]:
    """Return an error record as a plain mapping, whatever shape it arrived in."""
    if dataclasses.is_dataclass(record) and not isinstance(record, type):
        return dataclasses.asdict(record)
    if isinstance(record, Mapping):
        return dict(record)
    return dict(vars(record))
