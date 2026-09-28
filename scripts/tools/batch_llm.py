"""Lab tool for the LLM processor over a folder tree (``SCR-15``).

``llm.py`` runs one input; this runs the same methods over every text file under a folder. What it
shares with the other batch tools — the walk, the mirror, the per-input record, the summary and the
exit code — is :mod:`_batch`; what is its own is the suffix set it takes, the layer its methods come
from (:mod:`_llm`) and the four commands it offers.

**Four of the eight, on purpose.** ``status`` asks about a *run directory*, not about an input;
``models`` asks about a *model* and never reads the input at all; ``fake`` is a demonstration of the
provider seam, and a demonstration is a single-input thing. None of the three is a question a corpus
run answers per file, so none of them is registered — naming one is a usage error, not a silent
no-op. ``resume`` is left out for a related reason: it *pins* one run identity, and a corpus run
shares one identity across many inputs.

**No default command.** Unlike the other batch tools, a bare run here refuses: ``--provider`` and
``--model`` are required on every command, so there is no flag-free method to make. Stating the
command is the caller's job, and the parser enforces it.

**``--fake`` installs the scripted provider**, so a corpus chain is demonstrable with no model
served and no token spent. It replaces the provider seam and nothing else; the refusal on a missing
``--provider``/``--model`` stands either way.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from typing import Final

import _batch
import _llm

from docflow.llm.primitives.errors import LLMPrimitiveError

#: The commands a corpus run may make: the ones whose answer is a property of the input. The other
#: four are the tool's own — see the module docstring.
SUBCOMMANDS: Final[tuple[str, ...]] = ("call", "graph", "node", "tokens")

#: The inputs this tool takes: the LLM layer's own set — the extracted text a task is performed
#: over, ``.txt`` and the engine's Markdown.
SUFFIXES: Final[tuple[str, ...]] = _llm.SUFFIXES

#: No command of this tool is report-only: the frame files a record for every input that produced a
#: payload, so the header may name the run root whatever the command was. Declared because the
#: guard that pins the claim is per tool.
REPORT_ONLY: Final[tuple[str, ...]] = ()


def build_parser() -> argparse.ArgumentParser:
    """Build the tool's argument parser.

    Returns:
        The parser: the folder, the tool's own flags, and the four commands with their flags. A
        subcommand is **required** — this tool has no flag-free command to fall back on.
    """
    parser, subparsers = _batch.build_parser(
        "batch_llm",
        "Lab bench for the LLM processor over a folder: one command, every text below it.",
        subcommand_required=True,
    )
    parser.add_argument(
        "--assets-dir",
        default=str(_llm.DEFAULT_ASSETS_DIR),
        help="Template and schema root; printed with every run.",
    )
    parser.add_argument(
        "--fake",
        action="store_true",
        help="Install the committed scripted provider, so no model is reached.",
    )
    _llm.build_subcommands(subparsers, input_argument=False, only=SUBCOMMANDS)
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
    args = parser.parse_args(argv)
    if args.fake:
        _llm.install_fake()
    return _batch.run_batch(
        "batch_llm",
        str(args.subcommand),
        _llm.COMMANDS[str(args.subcommand)],
        (LLMPrimitiveError,),
        args,
        parser,
        suffixes=SUFFIXES,
        header_extra={"assets_dir": str(_llm.asset_root(args))},
    )


if __name__ == "__main__":
    raise SystemExit(main())
