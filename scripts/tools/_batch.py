"""The batch frame: a folder in, a mirrored tree out.

Every batch tool shares this — the walk, the mirror, the per-input record, the line the run prints
per input, the summary and the exit code. It is **not** a tool: it registers no ``main``, holds no
subcommand and names no processor. A tool supplies what is its own: the folder it walks, the
suffixes it takes, the command it runs and that command's method.

The shape is the one ``batch_pdf.py`` was written with, unchanged: each input writes into
``<root>/<its folder relative to the walked one>/<its stem>/``, with its payload as
``result.json`` beside whatever the method published, and a failure is printed as the library's
typed record and counted instead of ending the run.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any, Final

import _cli

#: The file each input's record is written to, inside that input's mirror directory.
RESULT_NAME: Final[str] = "result.json"

#: What one method returns: the payload its caller files, or the artifacts it published.
Payload = dict[str, Any]

#: A method as a batch tool calls it: the parsed flags, the parser to refuse through, the input,
#: and the directory that input's run writes under.
Method = Callable[[argparse.Namespace, argparse.ArgumentParser, Path, Path], Payload]


def build_parser(
    tool: str, description: str, *, subcommand_required: bool = False
) -> tuple[argparse.ArgumentParser, Any]:
    """Build a batch tool's parser: the folder, the tool's flags, then the processor's commands.

    Args:
        tool: The tool's name, as ``--help`` prints it.
        description: The one-line description, as ``--help`` prints it.
        subcommand_required: Whether a method has to be stated. A tool whose bare run is safe and
            complete leaves it optional, and the run states the command it made; a tool that could
            only fail without one — a provider and a model are never defaulted — requires it.

    Returns:
        The parser, and the subcommand group for the processor's own command registration. The
        group is typed loosely because ``argparse`` exposes no public type for it.
    """
    parser, subparsers = _cli.build_parser(
        f"{tool}.py",
        description,
        subcommand_required=subcommand_required,
        fixtures=False,
        positional=(
            "folder",
            "Folder to walk; the inputs below it are the run's inputs.",
        ),
    )
    parser.add_argument(
        "--recursive",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Walk the folder's subfolders too (the default).",
    )
    return parser, subparsers


def folder(args: argparse.Namespace, parser: argparse.ArgumentParser) -> Path:
    """Return the folder the arguments name, refusing anything that is not one."""
    walked = Path(args.folder).expanduser()
    if not walked.is_dir():
        parser.error(f"{args.folder!r} is not a folder: {walked.resolve()}")
    return walked.resolve()


def resolve_command(
    parser: argparse.ArgumentParser,
    argv: Sequence[str] | None,
    default: str,
) -> tuple[argparse.Namespace, str, bool]:
    """Parse the arguments, making the tool's own command when the caller states none.

    A command's flags are registered on that command, so a run that made ``text`` without parsing
    ``text`` would have no ``--ocr``, ``--layout`` or ``--language`` at all — the default would not
    be the flagged run it claims to be. The default is therefore appended to the arguments and
    parsed as a subcommand: a bare run and a stated one are the same run.

    Appending is enough because the folder positional is declared before the subcommands, so it is
    filled first and the appended name lands exactly where a subcommand belongs.

    Args:
        parser: The tool's parser, already built.
        argv: The raw arguments, defaulting to ``sys.argv[1:]``.
        default: The command this tool makes when none is stated.

    Returns:
        The parsed arguments, the command, and whether it was the tool's default. The last is
        returned rather than read back off the namespace: after the second parse the two runs are
        indistinguishable there, and the header still has to say which one happened.
    """
    arguments = list(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(arguments)
    if args.subcommand is not None:
        return args, str(args.subcommand), False
    return parser.parse_args([*arguments, default]), default, True


def default_root(tool: str) -> Path:
    """Return the root a batch tool mirrors under when ``--out`` is not stated.

    Args:
        tool: The tool's name.

    Returns:
        ``var/<tool>/``, beside the single-input tools' ``var/tools/<tool>/``. Both are ignored
        by git.
    """
    return _cli.REPO_ROOT / "var" / tool


def inputs_under(
    walked: Path, *, suffixes: Sequence[str], recursive: bool, skip: Path | None = None
) -> list[Path]:
    """Return the files to run over, in a stable order.

    Args:
        walked: The folder to walk.
        suffixes: The extensions this tool takes, matched case-insensitively.
        recursive: Whether to descend into the folder's subfolders.
        skip: A directory to leave out — the run's own output root, so a second run over the same
            tree does not pick up the files the first one wrote.

    Returns:
        The inputs, sorted, so two runs over one tree see the same order.
    """
    wanted = {suffix.lower() for suffix in suffixes}
    candidates = walked.rglob("*") if recursive else walked.glob("*")
    return sorted(
        path
        for path in candidates
        if path.is_file()
        and path.suffix.lower() in wanted
        and (skip is None or not path.is_relative_to(skip))
    )


def mirror_dir(root: Path, walked: Path, input_path: Path) -> Path:
    """Return the directory one input's run writes into.

    Args:
        root: The root the run mirrors the walked folder under.
        walked: The folder that was walked.
        input_path: The input being run.

    Returns:
        ``<root>/<the input's folder relative to the walked one>/<the input's stem>``.
    """
    return root / input_path.parent.relative_to(walked) / input_path.stem


def _failed(record: Mapping[str, Any]) -> bool:
    """Return whether one input's record is a failure.

    Two shapes count: the processor's typed failure, raised by a primitive and recorded here, and
    a contract run that *returned* a failed status. The exit-code mapping decides the second, so
    one place owns what "failed" means.
    """
    return (
        record["error"] is not None
        or _cli.exit_code_for(record["status"] or "success") == _cli.FAILURE_EXIT
    )


def _payload_failures(payload: Mapping[str, Any]) -> list[Any]:
    """Return the typed failures a payload states, in the shape the printer takes.

    A contract that returns rather than raises states its failure in the payload, and the
    processors do not spell it the same way: ``error`` for a run's single failure, ``errors`` for a
    list of them. Both are read, so the line the run prints and the summary it ends with agree
    about what happened instead of the one saying ``ok`` while the other counts a failure.

    Args:
        payload: What a method returned.

    Returns:
        The typed failures, empty when the payload states none.
    """
    single = payload.get("error")
    if single is not None:
        return [single]
    return list(payload.get("errors") or [])


def run_one(
    command: str,
    method: Method,
    errors: tuple[type[BaseException], ...],
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> dict[str, Any]:
    """Run one input, file its record, and report what happened.

    Args:
        command: The subcommand being run.
        method: That command's implementation.
        errors: The processor's typed failure, which a method raises rather than returns.
        args: The parsed arguments, shared by every input of the run.
        parser: The parser, to refuse a missing flag through.
        input_path: The input to run.
        root: The directory this input's run writes under.

    Returns:
        The input's record: its path, where it wrote, its own status, and the typed failure when
        there was one — raised by a primitive, or returned by the contract under either of the
        keys the processors use for it.
    """
    entry: dict[str, Any] = {
        "path": str(input_path),
        "output": str(root),
        "status": None,
        "error": None,
    }
    try:
        payload = method(args, parser, input_path, root)
    except errors as failure:
        entry["error"] = asdict(failure.error)
        if not args.json:
            print(f"{input_path.name}: FAILED -> {root}")
        _cli.print_error([failure.error])
        return entry
    _cli.write_payload(root / RESULT_NAME, payload)
    failures = _payload_failures(payload)
    entry["status"] = payload.get("status")
    entry["error"] = failures[0] if failures else None
    failed = _failed(entry)
    if not args.json:
        print(f"{input_path.name}: {'FAILED' if failed else 'ok'} -> {root}")
    if failed and failures:
        _cli.print_error(failures)
    return entry


def run_batch(
    tool: str,
    command: str,
    method: Method,
    errors: tuple[type[BaseException], ...],
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    *,
    suffixes: Sequence[str],
    default: bool = False,
    header_extra: Mapping[str, Any] | None = None,
    validate: _cli.Validate | None = None,
) -> int:
    """Walk the folder, run the command over every input, and report the run.

    Args:
        tool: The tool's name: it names the default root and the run header.
        command: The subcommand being run, already resolved.
        method: That command's implementation, from the tool's own shared layer.
        errors: The processor's typed failure, which a method raises rather than returns.
        args: The parsed arguments.
        parser: The parser, to refuse a folder that is not one through.
        suffixes: The input extensions this tool takes, case-insensitively.
        default: Whether the command is the one the tool made rather than the one the caller
            stated — the header says so, so a default is never silent.
        header_extra: The tool's own header fields, for what it resolves and states the way its
            single-input twin does — an asset root, say — rather than letting the two disagree.
        validate: The layer's check that this command's flags can run at all, made once before
            the walk. A method refuses a missing flag when it is called, which is per input:
            the header would already be printed, and a folder holding no input would never
            call the method at all and would report a successful run of nothing.

    Returns:
        ``0`` when every input produced a result, ``1`` when any input failed.
    """
    walked = folder(args, parser)
    if validate is not None:
        validate(command, args, parser)
    root = (
        Path(args.out).expanduser().resolve()
        if args.out is not None
        else default_root(tool) / walked.name
    )
    extra = dict(header_extra or {})
    if default:
        extra["command"] = f"{command} (default, none stated)"
    _cli.print_header(tool, command, walked, root, extra=extra or None)

    found = inputs_under(
        walked, suffixes=suffixes, recursive=bool(args.recursive), skip=root
    )
    records = [
        run_one(
            command,
            method,
            errors,
            args,
            parser,
            path,
            mirror_dir(root, walked, path),
        )
        for path in found
    ]
    failed = [entry for entry in records if _failed(entry)]
    _cli.print_result(
        {
            "input": str(walked),
            "command": command,
            "output_root": str(root),
            "files": len(found),
            "succeeded": len(records) - len(failed),
            "failed": len(failed),
            "results": records,
        },
        as_json=args.json,
    )
    return _cli.FAILURE_EXIT if failed else 0
