"""Lab tool for the OCR processor (``SCR-04``).

A thin caller: its parser, its flags and one handler per subcommand are all it owns. The frame
around them — where a run writes, how the input resolves, the header, the printers and the exit
code — lives in :mod:`scripts.tools._cli`, and the eight methods themselves live in
:mod:`scripts.tools._ocr`, which ``batch_ocr.py`` drives over a folder tree. One file per run is
the only thing this tool adds to that layer.

There is no ``--engine`` flag: the engine is fixed and never presented as a selectable option.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
from typing import Final

import _cli
import _ocr

from docflow.ocr.primitives.errors import OCRPrimitiveError

#: Subcommands that publish no file: their report is the stdout summary, so the run header
#: says so instead of naming an output root no run creates. ``run`` publishes the contract's
#: document, and ``text`` and ``mixed`` publish the reading they report as ``text.txt``; the
#: remaining five write nothing but their report. Verified by the hand run in
#: ``docs/plan/bitacora.md`` (2026-09-27), by the ``text`` run of 2026-09-30, and by the ``mixed``
#: run of the same day.
REPORT_ONLY: Final[tuple[str, ...]] = (
    "md",
    "json",
    "tables",
    "blocks",
    "metrics",
)


def build_parser() -> argparse.ArgumentParser:
    """Build the tool's argument parser.

    Returns:
        The parser, with every documented subcommand registered.
    """
    parser, subparsers = _cli.build_parser(
        "ocr.py",
        "Lab bench for the OCR processor: one representation, or the contract.",
        identity=True,
    )

    _ocr.build_subcommands(subparsers)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the tool.

    Args:
        argv: The arguments, defaulting to ``sys.argv[1:]``.

    Returns:
        The process exit code: ``0`` when the run produced a result, ``1`` when the library
        returned a typed failure.
    """
    return _cli.run_tool("ocr", build_parser(), HANDLERS, argv, report_only=REPORT_ONLY)


def _handler(name: str) -> _cli.Handler:
    """Return the handler for one subcommand: run its method, print what it returned.

    Args:
        name: The subcommand's name, one of :data:`_ocr.COMMANDS`.

    Returns:
        A handler whose exit code is the one the payload's own status maps to; a method that
        reports no status is a method that cannot fail once it has returned.
    """

    def handle(
        args: argparse.Namespace,
        parser: argparse.ArgumentParser,
        input_path: Path,
        root: Path,
    ) -> int:
        try:
            payload = _ocr.COMMANDS[name](args, parser, input_path, root)
        except OCRPrimitiveError as failure:
            return _cli.print_error([failure.error])
        _cli.print_result(payload, as_json=args.json)
        status = payload.get("status")
        return 0 if status is None else _cli.exit_code_for(status)

    return handle


HANDLERS: dict[str, _cli.Handler] = {name: _handler(name) for name in _ocr.COMMANDS}


if __name__ == "__main__":
    raise SystemExit(main())
