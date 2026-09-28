"""Lab tool for the image processor over a folder tree (``SCR-13``).

``image.py`` runs one file; this runs the same seven methods over every image under a folder. What
it shares with the other batch tools — the walk, the mirror, the per-input record, the summary and
the exit code — is :mod:`_batch`; what is its own is the suffix set it takes, the layer its methods
come from (:mod:`_image`) and the command a run makes when the caller states none.

With no subcommand stated it runs ``info`` — stated in the run header, never silent — the flag-free
method that publishes nothing, so a bare run can only report. Every other method here writes:
``normalize``, ``ocr-ready``, ``vlm-ready`` and ``run`` all publish.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from typing import Final

import _batch
import _image

from docflow.image.primitives import ImagePrimitiveError

#: The command a run makes when the caller states none. ``info`` reads the file's facts and writes
#: nothing, so a bare run cannot fill the tree; the header says when it was the default rather than
#: a stated choice.
DEFAULT_COMMAND: Final[str] = "info"

#: The inputs this tool takes: the image layer's own set, so the two agree by construction.
SUFFIXES: Final[tuple[str, ...]] = _image.SUFFIXES

#: No command of this tool is report-only: the frame files a record for every input that produced
#: a payload, so the header may name the run root whatever the command was. Declared because the
#: guard that pins the claim is per tool.
REPORT_ONLY: Final[tuple[str, ...]] = ()


def build_parser() -> argparse.ArgumentParser:
    """Build the tool's argument parser.

    Returns:
        The parser: the folder, the tool's own flags, and the image methods with their flags. A
        subcommand is optional — this tool has a command of its own — so its flags belong after it.
    """
    parser, subparsers = _batch.build_parser(
        "batch_image",
        "Lab bench for the image processor over a folder: one method, every image below it.",
    )
    _image.build_subcommands(subparsers, input_argument=False)
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
        "batch_image",
        command,
        _image.COMMANDS[command],
        (ImagePrimitiveError,),
        args,
        parser,
        suffixes=SUFFIXES,
        default=default,
    )


if __name__ == "__main__":
    raise SystemExit(main())
