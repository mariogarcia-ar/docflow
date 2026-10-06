"""Lab tool for the LLM processor (``SCR-05``).

A thin caller: its parser, its flags and one handler per subcommand are all it owns. The frame
around them — where a run writes, how the input resolves, the header, the printers and the exit
code — lives in :mod:`scripts.tools._cli`, and the nine methods themselves live in
:mod:`scripts.tools._llm`, which ``batch_llm.py`` drives over a folder tree with the five of them
that are about an input.

``--provider`` and ``--model`` are required on every inference subcommand: a default model is
exactly the silent stand-in this project forbids. The input is the document — or, when it is an
image, the page itself: a vision call reads the pixels and states no text, and ``--image`` attaches
further pages beside it. ``--stream`` reads the answer as it is written,
echoing a reasoning model's trace and its answer to stderr while stdout stays the payload; the body
the run records is the one a waiting call would have received. ``prompt`` states the same request
and stops before the provider, so the rendered ask can be read — and its token count weighed
against a stated window — without paying for a call. The ``fake`` subcommand installs the committed
scripted provider at the provider seam and then demonstrates the chain and its resume path twice —
with no model reached and no token spent.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
from typing import Final

import _cli
import _llm

from docflow.llm.primitives.errors import LLMPrimitiveError

#: Subcommands that publish no file: their report is the stdout summary, so the run header
#: says so instead of naming an output root no run creates. ``node`` builds its request with
#: no output directory on purpose, so it publishes nothing even when it succeeds; ``prompt``
#: renders and stops, and its request carries no output directory either. Verified by
#: the hand run in ``docs/plan/bitacora.md`` (2026-09-27).
REPORT_ONLY: Final[tuple[str, ...]] = ("prompt", "node", "status", "models", "tokens")


def build_parser() -> argparse.ArgumentParser:
    """Build the tool's argument parser.

    Returns:
        The parser, with every documented subcommand registered.
    """
    parser, subparsers = _cli.build_parser(
        "llm.py",
        "Lab bench for the LLM processor: one inference, or the inventory.",
        identity=True,
    )
    parser.add_argument(
        "--assets-dir",
        default=str(_llm.default_assets_dir()),
        help="Template and schema root; printed with every run.",
    )
    _llm.build_subcommands(subparsers)
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
        "llm",
        build_parser(),
        HANDLERS,
        argv,
        text=True,
        out_only=("status",),
        report_only=REPORT_ONLY,
        header_extra=lambda args: {
            "assets_dir": str(Path(args.assets_dir).expanduser()),
            **_llm.config_header(),
        },
    )


def _handler(name: str) -> _cli.Handler:
    """Return the handler for one subcommand: run its method, print what it returned.

    Args:
        name: The subcommand's name, one of :data:`_llm.COMMANDS`.

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
            payload = _llm.COMMANDS[name](args, parser, input_path, root)
        except LLMPrimitiveError as failure:
            return _cli.print_error([failure.error])
        _cli.print_result(payload, as_json=args.json)
        status = payload.get("status")
        return 0 if status is None else _cli.exit_code_for(status)

    return handle


HANDLERS: dict[str, _cli.Handler] = {name: _handler(name) for name in _llm.COMMANDS}


if __name__ == "__main__":
    raise SystemExit(main())
