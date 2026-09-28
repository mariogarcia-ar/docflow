"""Lab tool for the OCR processor over a folder tree (``SCR-14``).

``ocr.py`` runs one image; this runs the same seven methods over every image under a folder. What
it shares with the other batch tools — the walk, the mirror, the per-input record, the summary and
the exit code — is :mod:`_batch`; what is its own is the suffix set it takes, the layer its methods
come from (:mod:`_ocr`) and the command a run makes when the caller states none.

With no subcommand stated it runs ``text`` — stated in the run header, never silent — the flag-free
method that publishes nothing, so a bare run can only report. It is not cheap: every input is
converted once by the engine, so a corpus of images takes as long as the engine takes. Only ``run``
publishes artifacts here; ``text``, ``md``, ``json``, ``tables``, ``blocks`` and ``metrics`` write
nothing but their record.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from typing import Final

import _batch
import _ocr

from docflow.ocr.primitives.errors import OCRPrimitiveError

#: The command a run makes when the caller states none. ``text`` reads one representation and
#: writes no artifact, so a bare run cannot fill the tree; the header says when it was the default
#: rather than a stated choice.
DEFAULT_COMMAND: Final[str] = "text"

#: The inputs this tool takes: the OCR layer's own set, so the two agree by construction.
SUFFIXES: Final[tuple[str, ...]] = _ocr.SUFFIXES

#: No command of this tool is report-only: the frame files a record for every input that produced
#: a payload, so the header may name the run root whatever the command was. Declared because the
#: guard that pins the claim is per tool.
REPORT_ONLY: Final[tuple[str, ...]] = ()


def build_parser() -> argparse.ArgumentParser:
    """Build the tool's argument parser.

    Returns:
        The parser: the folder, the tool's own flags, and the OCR methods with their flags. A
        subcommand is optional — this tool has a command of its own — so its flags belong after it.
    """
    parser, subparsers = _batch.build_parser(
        "batch_ocr",
        "Lab bench for the OCR processor over a folder: one method, every image below it.",
    )
    _ocr.build_subcommands(subparsers, input_argument=False)
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
        "batch_ocr",
        command,
        _ocr.COMMANDS[command],
        (OCRPrimitiveError,),
        args,
        parser,
        suffixes=SUFFIXES,
        default=default,
    )


if __name__ == "__main__":
    raise SystemExit(main())
