"""Lab tool for the PDF processor over a folder tree (``SCR-12``).

``pdf.py`` runs one file; this runs the same eight methods over every PDF under a folder, one
line per input, and mirrors the folder under ``var/batch_pdf/<folder>/`` — or under the directory
``--out`` names. Each input gets its own directory there (``<mirror>/<stem>/``), so two PDFs in
one folder cannot collide, and each holds the ``result.json`` the run produced beside whatever
artifacts the method published.

The command is the *only* choice this tool makes, and it makes none by itself: it runs the
subcommand the caller states, with the flags `_pdf` registered for it. With no subcommand stated
it runs ``inspect`` — stated in the run header, never silent — which is the one method that needs
no further flag.

A batch does not stop at the first bad file: a corpus has bad files, and the interesting output
is which ones. Every failure is printed as the library's typed record and counted; the exit code
is ``1`` when any input failed, ``0`` when none did, ``2`` for a usage error.

Like the other tools, it calls and never reimplements: the work lives in :mod:`_pdf`, and this
module walks, mirrors, records and reports.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any, Final

import _cli
import _pdf

from docflow.pdf.primitives.errors import PDFPrimitiveError

#: The command a run makes when the caller states none. It is the only method that needs no
#: further flag, and the header says when it was the default rather than a stated choice.
DEFAULT_COMMAND: Final[str] = "inspect"

#: The file each input's record is written to, inside that input's mirror directory.
RESULT_NAME: Final[str] = "result.json"

#: No command of this tool is report-only: every input's run writes its record under the run
#: root, so the header may name that root whatever the command was.
REPORT_ONLY: Final[tuple[str, ...]] = ()


def build_parser() -> argparse.ArgumentParser:
    """Build the tool's argument parser.

    Returns:
        The parser: the folder, the tool's own flags, and the PDF subcommands with their flags.
        A subcommand is optional — this tool has a command of its own — and its flags therefore
        belong after it.
    """
    parser, subparsers = _cli.build_parser(
        "batch_pdf.py",
        "Lab bench for the PDF processor over a folder: one command, every PDF below it.",
        subcommand_required=False,
        positional=("folder", "Folder to walk; the PDFs below it are the inputs."),
    )
    parser.add_argument(
        "--recursive",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Walk the folder's subfolders too (the default).",
    )
    _pdf.build_subcommands(subparsers, input_argument=False)
    return parser


def pdfs_under(
    folder: Path, *, recursive: bool, skip: Path | None = None
) -> list[Path]:
    """Return the PDFs to run over, in a stable order.

    Args:
        folder: The folder to walk.
        recursive: Whether to descend into its subfolders.
        skip: A directory to leave out — the run's own output root, so a second run over the
            same tree does not pick up the pages an earlier one wrote.

    Returns:
        The inputs, sorted, so two runs over one tree see the same order.
    """
    candidates = folder.rglob("*") if recursive else folder.glob("*")
    return sorted(
        path
        for path in candidates
        if path.is_file()
        and path.suffix.lower() == ".pdf"
        and (skip is None or not path.is_relative_to(skip))
    )


def mirror_dir(run_root: Path, folder: Path, input_path: Path) -> Path:
    """Return the directory one input's run writes into.

    Args:
        run_root: The root the run mirrors the folder under.
        folder: The folder the run walked.
        input_path: The input being run.

    Returns:
        ``<run_root>/<the input's folder relative to the walked folder>/<the input's stem>``.
    """
    relative = input_path.parent.relative_to(folder)
    return run_root / relative / input_path.stem


def _folder(args: argparse.Namespace, parser: argparse.ArgumentParser) -> Path:
    """Return the folder to walk, refusing anything that is not one."""
    folder = Path(args.folder).expanduser()
    if not folder.is_dir():
        parser.error(f"{args.folder!r} is not a folder: {folder.resolve()}")
    return folder.resolve()


def _run_root(args: argparse.Namespace, folder: Path) -> Path:
    """Return the root the folder is mirrored under, from ``--out`` or the default."""
    if args.out is not None:
        return Path(args.out).expanduser().resolve()
    return _cli.BATCH_OUTPUT_ROOT / folder.name


def _run_one(
    command: str,
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> dict[str, Any]:
    """Run one input, write its record, and report what happened.

    Args:
        command: The subcommand to run.
        args: The parsed arguments, shared by every input of the run.
        parser: The parser, to refuse a missing flag through.
        input_path: The PDF to run.
        root: The directory this input's run writes under.

    Returns:
        The input's record: its path, where it wrote, its own status, and the typed failure when
        there was one.
    """
    record: dict[str, Any] = {
        "path": str(input_path),
        "output": str(root),
        "status": None,
        "error": None,
    }
    try:
        payload = _pdf.COMMANDS[command](args, parser, input_path, root)
    except PDFPrimitiveError as failure:
        record["error"] = asdict(failure.error)
        if not args.json:
            print(f"{input_path.name}: FAILED -> {root}")
        _cli.print_error([failure.error])
        return record
    _cli.write_payload(root / RESULT_NAME, payload)
    record["status"] = payload.get("status")
    if not args.json:
        print(f"{input_path.name}: ok -> {root}")
    return record


def main(argv: Sequence[str] | None = None) -> int:
    """Run the tool.

    Args:
        argv: The arguments, defaulting to ``sys.argv[1:]``.

    Returns:
        ``0`` when every input produced a result, ``1`` when any input failed, ``2`` for a usage
        error.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    folder = _folder(args, parser)
    command = args.subcommand or DEFAULT_COMMAND
    run_root = _run_root(args, folder)
    extra = {} if args.subcommand else {"command": f"{command} (default, none stated)"}
    _cli.print_header(
        "batch_pdf",
        command,
        folder,
        run_root,
        extra=extra,
        publishes=command not in REPORT_ONLY,
    )

    found = pdfs_under(folder, recursive=bool(args.recursive), skip=run_root)
    records = [
        _run_one(command, args, parser, path, mirror_dir(run_root, folder, path))
        for path in found
    ]
    failed = [record for record in records if record["error"] is not None]
    _cli.print_result(
        {
            "input": str(folder),
            "command": command,
            "output_root": str(run_root),
            "files": len(found),
            "succeeded": len(records) - len(failed),
            "failed": len(failed),
            "results": records,
        },
        as_json=args.json,
    )
    return _cli.FAILURE_EXIT if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
