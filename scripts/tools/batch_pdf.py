"""Lab tool for the PDF processor over a folder tree (``SCR-12``).

``pdf.py`` runs one file; this runs the same eight methods over every PDF under a folder. What it
shares with the other batch tools — the walk, the mirror, the per-input record, the summary and
the exit code — is :mod:`_batch`; what is its own is the suffix it takes, the layer its methods
come from (:mod:`_pdf`) and the command a run makes when the caller states none.

With no subcommand stated it runs ``inspect`` — stated in the run header, never silent — which is
the flag-free method that publishes nothing, so a bare run can only report. (``split`` is the other
method needing no flag, and it writes; defaulting to it would have a bare run fill the tree.)
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from typing import Final

import _batch
import _pdf

from docflow.pdf.primitives.errors import PDFPrimitiveError

#: The command a run makes when the caller states none. ``split`` is the only other method that
#: needs no flag, and it publishes; this one only reports, so a bare run cannot fill the tree. The
#: header says when it was the default rather than a stated choice.
DEFAULT_COMMAND: Final[str] = "inspect"

#: The inputs this tool takes: the PDF layer's own set, so the two agree by construction.
SUFFIXES: Final[tuple[str, ...]] = _pdf.SUFFIXES

#: No command of this tool is report-only: the frame files a record for every input that produced
#: a payload, so the header may name the run root whatever the command was. Declared because the
#: guard that pins the claim is per tool.
REPORT_ONLY: Final[tuple[str, ...]] = ()


def build_parser() -> argparse.ArgumentParser:
    """Build the tool's argument parser.

    Returns:
        The parser: the folder, the tool's own flags, and the PDF methods with their flags. A
        subcommand is optional — this tool has a command of its own — so its flags belong after it.
    """
    parser, subparsers = _batch.build_parser(
        "batch_pdf",
        "Lab bench for the PDF processor over a folder: one method, every PDF below it.",
    )
    _pdf.build_subcommands(subparsers, input_argument=False)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the tool.

    Args:
        argv: The arguments, defaulting to ``sys.argv[1:]``.

    Returns:
        ``0`` when every input produced a result, ``1`` when any input failed, ``2`` for a usage
        error.
    """
    parser = build_parser()
    args, command, default = _batch.resolve_command(parser, argv, DEFAULT_COMMAND)
    return _batch.run_batch(
        "batch_pdf",
        command,
        _pdf.COMMANDS[command],
        (PDFPrimitiveError,),
        args,
        parser,
        suffixes=SUFFIXES,
        default=default,
        validate=_pdf.validate_flags,
    )


if __name__ == "__main__":
    raise SystemExit(main())
