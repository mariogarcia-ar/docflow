"""Lab tool for the invoice flow: the registry's five steps over one paper.

Where ``llm.py`` runs one inference the caller composes, this runs the flow the registry already
ships as data — is the paper a receipt (**validity**), what does it say (**extraction**), what is
its **breakdown** of items and amounts, its **class** and the **line of business** it belongs to.
The five steps, their order and both of their identifier pairs (the text one and the vision twin)
live in :mod:`scripts.tools._invoice`; the frame — the output root, the header, the printers and
the exit code — is :mod:`scripts.tools._cli`, and the request itself is the bench's, reached in
:mod:`scripts.tools._llm`. This file owns only its parser, its flags and one handler per command.

**``flow`` files one unified report beside the input.** It writes ``invoice.json`` next to the paper
it read: the input, the flow's status and the gate's verdict, then one section per step holding that
step's answer alone. The step's own directory keeps the run; the report keeps the reading — and
because it sits beside the input, a second ``flow`` over the same paper reads it back instead of
running the steps again, stating ``reused`` in its payload.

**It adds a convention member on purpose.** ``scripts/tools/`` was pinned to the five processor
benches plus their layers; this is the first *domain* caller of one of them, so its registration in
the guard test and in ``subplan-scripts.md`` is the plan revision that admits it. It reaches the
library the way ``llm.py`` does — through the bench's command layer, never an engine and never a
provider SDK — and it adds no contract, no option type and no default.

**No default provider and no default model.** A default is exactly the silent stand-in this project
forbids, so ``--provider`` and ``--model`` are required on every command, and the refusal is the
bench's own ``validate`` hook: it happens before the header, so a run that cannot start never
announces itself. ``--assets-dir`` defaults to the committed local registry, because the flow's
identifiers are the registry's and not the fixture root's.

**The input's own kind picks the twin.** A text input drives the five text steps; a page image
drives their vision twins, which read the pixels and state no document. Nothing is stated to choose
between them: ``--image`` attaches further pages beside a text input, exactly as the bench's own
``call`` does.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
from typing import Final

import _cli
import _invoice
import _llm

from docflow.llm.primitives.errors import LLMPrimitiveError

#: No command of this tool is report-only: every step files its answer and the run that produced it
#: under its own directory, and the flow files one directory per step. Declared because the guard
#: that pins the claim is per tool.
REPORT_ONLY: Final[tuple[str, ...]] = ()


def build_parser() -> argparse.ArgumentParser:
    """Build the tool's argument parser.

    Returns:
        The parser: the shared arguments, the asset root the steps resolve against, the scripted
        provider's switch, and the tool's own commands.
    """
    parser, subparsers = _cli.build_parser(
        "cli_invoice.py",
        "Lab bench for the invoice flow: the registry's five steps over one paper.",
        identity=True,
    )
    parser.add_argument(
        "--assets-dir",
        default=str(_invoice.default_assets_dir()),
        help="Template and schema root; printed with every run.",
    )
    parser.add_argument(
        "--fake",
        action="store_true",
        help="Install the committed scripted provider, so no model is reached.",
    )
    _invoice.build_subcommands(subparsers)
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
        "cli_invoice",
        build_parser(),
        HANDLERS,
        argv,
        text=True,
        report_only=REPORT_ONLY,
        validate=_invoice.validate_flags,
        header_extra=lambda args: {
            "assets_dir": str(Path(args.assets_dir).expanduser()),
            **_llm.config_header(),
        },
        prepare=_install_fake_if_stated,
    )


def _install_fake_if_stated(args: argparse.Namespace) -> None:
    """Install the scripted provider when the caller asked for a demonstration."""
    if args.fake:
        _llm.install_fake()


def _handler(name: str) -> _cli.Handler:
    """Return the handler for one subcommand: run its method, print what it returned.

    Args:
        name: The subcommand's name, one of :data:`_invoice.COMMANDS`.

    Returns:
        A handler whose exit code is the one the payload's own status maps to.
    """

    def handle(
        args: argparse.Namespace,
        parser: argparse.ArgumentParser,
        input_path: Path,
        root: Path,
    ) -> int:
        try:
            payload = _invoice.COMMANDS[name](args, parser, input_path, root)
        except LLMPrimitiveError as failure:
            return _cli.print_error([failure.error])
        _cli.print_result(payload, as_json=args.json)
        status = payload.get("status")
        return 0 if status is None else _cli.exit_code_for(status)

    return handle


HANDLERS: dict[str, _cli.Handler] = {name: _handler(name) for name in _invoice.COMMANDS}


if __name__ == "__main__":
    raise SystemExit(main())
