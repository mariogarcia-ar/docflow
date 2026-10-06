"""Lab tool for the PDF processor (``SCR-02``).

A thin caller: its parser, its flags and one handler per subcommand are all it owns. The frame
around them — where a run writes, how an input resolves, the header, the printers and the exit
code — lives in :mod:`scripts.tools._cli`, and the eight methods themselves live in
:mod:`scripts.tools._pdf`, which ``batch_pdf.py`` drives over a folder tree. One file per run is
the only thing this tool adds to that layer.

The tool adds no transformation, no validation and no default: a missing ``--dpi`` is a usage
error, never a substituted resolution.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
from typing import Final

import _cli
import _pdf

from docflow.pdf.primitives.errors import PDFPrimitiveError

#: Subcommands that publish no file: their report is the stdout summary, so the run header
#: says so instead of naming an output root no run creates. The other six do write —
#: ``classify`` among them, because measuring image dominance extracts the page's embedded
#: images, and ``text`` because it publishes each page's native text beside them. Verified by
#: the hand runs in ``docs/plan/bitacora.md`` (2026-09-27, 2026-09-29).
REPORT_ONLY: Final[tuple[str, ...]] = ("inspect", "blocks")


def build_parser() -> argparse.ArgumentParser:
    """Build the tool's argument parser.

    Returns:
        The parser, with every documented subcommand registered.
    """
    parser, subparsers = _cli.build_parser(
        "pdf.py",
        "Lab bench for the PDF processor: one primitive, or the contract.",
        identity=True,
    )
    _pdf.build_subcommands(subparsers)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the tool.

    Args:
        argv: The arguments, defaulting to ``sys.argv[1:]``.

    Returns:
        The process exit code: ``0`` when the run produced a result, ``1`` when the library
        returned a typed failure.
    """
    return _cli.run_tool(
        "pdf",
        build_parser(),
        HANDLERS,
        argv,
        report_only=REPORT_ONLY,
        validate=_pdf.validate_flags,
    )


def _handler(name: str) -> _cli.Handler:
    """Return the handler for one subcommand: run its method, print what it returned.

    Args:
        name: The subcommand's name, one of :data:`_pdf.COMMANDS`.

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
            payload = _pdf.COMMANDS[name](args, parser, input_path, root)
        except PDFPrimitiveError as failure:
            return _cli.print_error([failure.error])
        _cli.print_result(payload, as_json=args.json)
        status = payload.get("status")
        return 0 if status is None else _cli.exit_code_for(status)

    return handle


HANDLERS: dict[str, _cli.Handler] = {name: _handler(name) for name in _pdf.COMMANDS}


if __name__ == "__main__":
    raise SystemExit(main())
