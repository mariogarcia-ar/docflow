"""Shared library for the lab tools under ``scripts/tools/`` (``SCR-01``).

This module is **not** a tool: it holds no contract, reaches no engine and imports nothing
from ``docflow``. Everything the five tools would otherwise copy five times lives here —
where a run writes, how a fixture name resolves, how a request's identity is derived, how a
parser is built and dispatched, how ``KEY=VALUE`` flags are read, and how a result and a
typed failure are printed and turned into an exit code.

A tool supplies only what is its own: its subcommands, its flags and one handler per
subcommand. The library supplies the frame around them, so a tool's ``main`` is a single
call to :func:`run_tool` and its parser is a list of :func:`add_subcommand` calls.

Nothing under ``src/docflow/`` may import it; the dependency runs one way (``scripts/`` →
``src/``), and the guard test asserts it rather than trusting it. The module is deliberately
free of any processor vocabulary: it never names a PDF, an image, an OCR or an LLM type, so a
sixth tool for a sixth processor would need no change here.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import sys
from collections.abc import Callable, Collection, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

#: Repository root, derived from this file's own location (``scripts/tools/_cli.py``).
REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]

#: The directory the tools live in. A tool invoked by path already has it on ``sys.path``;
#: a test that imports one as ``scripts.tools.<name>`` puts it there itself.
TOOLS_DIR: Final[Path] = REPO_ROOT / "scripts" / "tools"

#: The two committed fixture roots a bare fixture name is resolved against.
FIXTURES_ROOT: Final[Path] = REPO_ROOT / "tests" / "fixtures"
FIXTURES_TXT_ROOT: Final[Path] = REPO_ROOT / "tests" / "fixtures-txt"

#: The default output root of every tool: ``var/tools/<tool>/`` (``/var/`` is ignored).
TOOLS_OUTPUT_ROOT: Final[Path] = REPO_ROOT / "var" / "tools"

#: The default output root of the batch driver, which mirrors a folder tree rather than keying a
#: run by one input's digest: ``var/batch_pdf/<folder>/…``.
BATCH_OUTPUT_ROOT: Final[Path] = REPO_ROOT / "var" / "batch_pdf"

#: How many characters of the input's SHA-256 name a run directory. Enough to tell two
#: inputs apart, short enough to read; the same input always lands in the same directory.
HASH_PREFIX_LENGTH: Final[int] = 8

#: Exit code of a typed failure the library returned and the tool printed.
FAILURE_EXIT: Final[int] = 1

#: Statuses that mean the run failed. Everything else — ``success``, ``partial``,
#: ``partial_success``, ``PAUSED`` — produced a result, and a result is a success here.
FAILED_STATUSES: Final[frozenset[str]] = frozenset({"failed", "FAILED"})

#: Payload keys the run header already states. The human summary skips them — a reader who
#: saw the header does not need the same path twice — while ``--json`` keeps them, because a
#: body read on its own still has to name the file it describes.
HEADER_STATED_KEYS: Final[frozenset[str]] = frozenset({"input"})

#: What every tool's subcommand handler receives, and must return: an exit code.
Handler = Callable[[argparse.Namespace, argparse.ArgumentParser, Path, Path], int]


def bootstrap() -> None:
    """Put the repository root and ``src/`` on ``sys.path``.

    A tool is invoked by path from a checkout that is not necessarily installed
    (``python scripts/tools/pdf.py``), so the library it is about to import has to be
    reachable. The call below runs when this module is imported, which is what makes a
    tool's ``import docflow`` work with no ``pip install``. It adds paths only, never
    behaviour, and it is idempotent.
    """
    for entry in (REPO_ROOT / "src", REPO_ROOT):
        if str(entry) not in sys.path:
            sys.path.insert(0, str(entry))


bootstrap()


class FixtureNotFoundError(LookupError):
    """A fixture name resolved to no usable file under the fixture roots.

    The name resolves to nothing, to more than one file, or to a directory. All three are the
    tool's usage error (exit ``2``) and none of them is a typed failure of the library: an
    input the caller named but that cannot be read as a file is the caller's mistake.
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


def _search_fixture_roots(roots: tuple[Path, ...], name: str) -> list[Path]:
    """Return every path named ``name`` anywhere beneath the fixture roots.

    The fallback :func:`resolve_fixture` uses when a name is neither a path nor a subdirectory
    spelling of one: the fixture tree nests its inputs by kind (``pdf/``, ``image/``, ...),
    so ``--fixture pdf_sample_mixed.pdf`` has to find one that lives one level down. The
    result is deduplicated and sorted, so "exactly one match" is a fact and not an ordering.
    Directories are included: a name that turns out to be one is refused *as* a directory,
    which says more than "not found" about a path the caller can see in the tree.

    Args:
        roots: The fixture roots to search, in the caller's order.
        name: The file name to look for, at any depth.

    Returns:
        The matching absolute paths, sorted; empty when nothing matches.
    """
    found = {match.resolve() for root in roots for match in root.rglob(name)}
    return sorted(found)


def _directory_refusal(name: str, path: Path) -> FixtureNotFoundError:
    """Return the refusal for a name that names a directory rather than a file.

    Args:
        name: The name the caller gave.
        path: The directory it resolved to.

    Returns:
        The error to raise. It names the directory, because "not found" would be false.
    """
    return FixtureNotFoundError(f"fixture {name!r} is a directory, not a file: {path}")


def resolve_fixture(
    name: str,
    *,
    fixtures_root: str | Path | None = None,
    text: bool = False,
) -> Path:
    """Resolve a fixture name, or a path, to an absolute path that exists.

    A **path** is taken as given; a **name with a subdirectory** — e.g. ``casos/<uuid>.txt``
    — is looked up under the committed fixture roots; and a **bare name** is searched for
    anywhere beneath them, so the nested fixture tree needs no spelling from the caller. A
    bare name that matches more than one file is refused rather than guessed, and a name that
    names a **directory** is refused as one instead of being reported missing. The caller
    prints the returned path, so a resolved fixture is never silent.

    Args:
        name: A path, or a name relative to a fixture root.
        fixtures_root: A root that replaces both defaults when stated.
        text: Search ``tests/fixtures-txt/`` first, for a text input.

    Returns:
        The resolved absolute path.

    Raises:
        FixtureNotFoundError: When the name resolves to no file, to more than one, or to a
            directory.
    """
    candidate = Path(name).expanduser()
    if candidate.is_file():
        return candidate.resolve()
    if candidate.is_dir():
        raise _directory_refusal(name, candidate.resolve())

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
        if resolved.is_dir():
            raise _directory_refusal(name, resolved.resolve())

    matches = _search_fixture_roots(roots, name)
    files = [match for match in matches if match.is_file()]
    if len(files) == 1:
        return files[0]
    if files:
        candidates = ", ".join(str(match) for match in files)
        raise FixtureNotFoundError(
            f"fixture {name!r} is ambiguous under the fixture roots: {candidates}"
        )
    if matches:
        raise _directory_refusal(name, matches[0])

    searched = ", ".join(str(root) for root in roots)
    raise FixtureNotFoundError(f"fixture {name!r} was not found under {searched}")


def _add_input_argument(subparser: argparse.ArgumentParser) -> None:
    """Add the positional input to a subcommand's parser.

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


def _add_common_arguments(
    parser: argparse.ArgumentParser, *, identity: bool = False, fixtures: bool = True
) -> None:
    """Add the arguments every tool shares.

    Args:
        parser: The parser to extend.
        identity: Also add ``--document-id`` and ``--run-id``, for a tool whose contract
            carries correlation metadata. A tool whose contract does not (``workflow.py``)
            leaves them out rather than shipping a flag that does nothing.
        fixtures: Also add ``--fixture`` and ``--fixtures-root``. A tool whose input is a folder
            the run walks leaves them out: it resolves no fixture, so the flags would do nothing.
    """
    if fixtures:
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


def build_parser(
    prog: str,
    description: str,
    *,
    identity: bool = False,
    subcommand_required: bool = True,
    positional: tuple[str, str] | None = None,
    fixtures: bool = True,
) -> tuple[argparse.ArgumentParser, Any]:
    """Build a tool's parser: the shared arguments plus its subcommand group.

    Args:
        prog: The program name, as ``--help`` prints it.
        description: The one-line description, as ``--help`` prints it.
        identity: Also add ``--document-id`` and ``--run-id``.
        subcommand_required: Whether a subcommand has to be stated. A tool whose own command
            is a sensible default turns this off and states the command it ran in its header.
        positional: A positional of the tool's own, as ``(name, help)``, added *before* the
            subcommands: a tool whose input is a folder rather than a file takes it once, so
            it cannot live on a subcommand. ``argparse`` fills positionals in declaration
            order, which is why this is not the tool's own ``add_argument``.
        fixtures: Also add the fixture flags; see :func:`_add_common_arguments`.

    Returns:
        The parser, and the subcommand group to register subcommands on. The group is typed
        loosely because ``argparse`` exposes no public type for a subparser action.
    """
    parser = argparse.ArgumentParser(prog=prog, description=description)
    _add_common_arguments(parser, identity=identity, fixtures=fixtures)
    if positional is not None:
        parser.add_argument(positional[0], help=positional[1])
    subparsers = parser.add_subparsers(
        dest="subcommand", required=subcommand_required, metavar="SUBCOMMAND"
    )
    return parser, subparsers


def add_subcommand(
    subparsers: Any, name: str, help_text: str, *, input_argument: bool = True
) -> argparse.ArgumentParser:
    """Register one subcommand, with the positional input it shares with its siblings.

    Args:
        subparsers: The group :func:`build_parser` returned.
        name: The subcommand's name, exactly as the runbook spells it.
        help_text: The one-line help, as ``--help`` prints it.
        input_argument: Whether the subcommand takes the input positional. A tool whose input
            is a folder the run walks turns this off: one folder, many files.

    Returns:
        The subcommand's parser, for the flags that are its own.
    """
    subparser = subparsers.add_parser(name, help=help_text)
    if input_argument:
        _add_input_argument(subparser)
    return subparser


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
    if name is None or not str(name).strip():
        parser.error("an input is required: pass a path or --fixture NAME")
    try:
        return resolve_fixture(name, fixtures_root=args.fixtures_root, text=text)
    except FixtureNotFoundError as missing:
        parser.error(str(missing))
        raise  # unreachable: parser.error exits; kept so the return type is honest


def required(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    name: str,
    flag: str,
    *,
    why: str = "no default is substituted",
) -> Any:
    """Return a value the subcommand cannot run without, refusing a missing one by name.

    The check is deliberately a post-parse test rather than ``required=True`` on the
    argument: an argument-level requirement hides an injected ``default=`` behind exactly
    the same behaviour, so a guard could not tell the two apart. Here a default makes the
    run proceed, which is what makes the "no default model" guard falsifiable.

    Args:
        args: The parsed arguments.
        parser: The parser to report the usage error through.
        name: The argument's destination, e.g. ``"model"``.
        flag: The flag as the caller spelled it, for the message.
        why: The reason no value is invented for it.

    Returns:
        The value the caller stated.
    """
    value = getattr(args, name, None)
    if value is None:
        parser.error(f"{args.subcommand} requires {flag}; {why}")
    return value


def key_values(
    items: Sequence[str] | None,
    parser: argparse.ArgumentParser,
    *,
    flag: str,
) -> dict[str, Any]:
    """Turn repeated ``KEY=VALUE`` flags into a mapping, refusing a malformed one.

    Args:
        items: The repeated flag's values, or ``None`` when the flag was never given.
        parser: The parser to report the usage error through.
        flag: The flag as the caller spelled it, for the message.

    Returns:
        The values, in the order the caller gave them.
    """
    values: dict[str, Any] = {}
    for item in items or []:
        key, separator, value = item.partition("=")
        if not separator or not key:
            parser.error(f"{flag} expects KEY=VALUE, got {item!r}")
        values[key] = value
    return values


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


def run_tool(
    tool: str,
    parser: argparse.ArgumentParser,
    handlers: Mapping[str, Handler],
    argv: Sequence[str] | None = None,
    *,
    text: bool = False,
    out_only: Collection[str] = (),
    report_only: Collection[str] = (),
    header_extra: Callable[[argparse.Namespace], Mapping[str, Any]] | None = None,
    prepare: Callable[[argparse.Namespace], None] | None = None,
) -> int:
    """Run one tool: parse, resolve the run, print the header and dispatch.

    The whole frame a tool shares with its siblings lives here. Everything specific to a
    tool — its subcommands, its flags and its handlers — arrives as an argument.

    Args:
        tool: The tool's name; it names the output root and the run identity.
        parser: The tool's parser, built with :func:`build_parser`.
        handlers: One handler per documented subcommand.
        argv: The arguments, defaulting to ``sys.argv[1:]``.
        text: Prefer the text fixture root when resolving a bare fixture name.
        out_only: Subcommands that accept ``--out`` in place of an input.
        report_only: Subcommands that publish no file, whose report is the stdout summary.
            The header says so rather than naming a run root no run will create.
        header_extra: Further facts to state in the header, read from the arguments.
        prepare: A hook that runs after parsing and before the handler — the place a tool
            patches a seam in its own process.

    Returns:
        The handler's exit code: ``0`` when the run produced a result, ``1`` when the
        library returned a typed failure.
    """
    args = parser.parse_args(argv)
    subcommand = args.subcommand
    if subcommand in out_only and args.out:
        root = Path(args.out).expanduser().resolve()
        input_path = Path(getattr(args, "input", None) or root).resolve()
    else:
        input_path = resolve_input(args, parser, text=text)
        root = output_root(tool, input_path, out=args.out)
    extra = None if header_extra is None else header_extra(args)
    print_header(
        tool,
        subcommand,
        input_path,
        root,
        extra=extra,
        publishes=subcommand not in report_only,
    )
    if prepare is not None:
        prepare(args)
    return handlers[subcommand](args, parser, input_path, root)


def print_header(
    tool: str,
    subcommand: str,
    input_path: Path,
    output_root: Path,
    *,
    extra: Mapping[str, Any] | None = None,
    publishes: bool = True,
) -> None:
    """Print the run header to stderr: what was resolved, and where output goes.

    stderr on purpose: the human summary or the ``--json`` payload on stdout stays clean,
    while a resolved fixture and a derived identity are still never silent. This is the one
    place a run states its input, so :func:`print_result` does not repeat it — and it is
    also the only statement of it when the run ends in a typed failure and no payload is
    printed at all.

    Args:
        tool: The tool's name.
        subcommand: The subcommand being run.
        input_path: The absolute, resolved input path.
        output_root: The absolute output directory.
        extra: Any further facts the tool wants stated, one line each.
        publishes: Whether this subcommand writes anything under ``output_root``. A
            subcommand whose report *is* the stdout summary writes nothing, and the header
            says that instead of naming a directory no run creates.
    """
    lines = [
        f"== {tool}.py {subcommand} ==",
        f"input:  {input_path}",
        f"output: {output_root}"
        if publishes
        else "output: (none — this subcommand publishes no file)",
    ]
    for key, value in (extra or {}).items():
        lines.append(f"{key}: {value}")
    print("\n".join(lines), file=sys.stderr)


def print_result(payload: Mapping[str, Any], *, as_json: bool) -> None:
    """Print a result, as the human summary or as the machine-readable payload.

    The human summary omits the keys :data:`HEADER_STATED_KEYS` names, because
    :func:`print_header` stated them on stderr a moment earlier. The ``--json`` payload keeps
    them: a body read on its own has to name the file it describes.

    Args:
        payload: The payload, built from the result's own fields.
        as_json: Print canonical JSON instead of one ``key: value`` line per field.
    """
    if as_json:
        print(json.dumps(payload, indent=2, default=_json_default))
        return
    for key, value in payload.items():
        if key in HEADER_STATED_KEYS:
            continue
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


def report_result(result: Any, payload: Mapping[str, Any], *, as_json: bool) -> int:
    """Print a result's payload and return the exit code its own status maps to.

    Args:
        result: The library's result, whose ``status`` decides the exit code.
        payload: The payload, built from that result's own fields.
        as_json: Print the payload as JSON instead of the human summary.

    Returns:
        ``0`` when the run produced a result, ``1`` when it failed.
    """
    print_result(payload, as_json=as_json)
    return exit_code_for(result)


def write_payload(path: Path, payload: Mapping[str, Any]) -> Path:
    """Write a payload beside the artifacts it describes, as canonical JSON.

    The file half of :func:`print_result`: a tool that runs over a folder keeps one record per
    input there, where the artifacts of that input landed.

    Args:
        path: The file to write; its parents are created.
        payload: The payload, built from the result's own fields.

    Returns:
        The path written.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, default=_json_default) + "\n", encoding="utf-8"
    )
    return path


def optional_path(path: Path | None) -> str | None:
    """Render an optional artifact path as text, or ``None`` when none was produced."""
    return None if path is None else str(path)


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
