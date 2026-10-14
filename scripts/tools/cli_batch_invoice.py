"""Lab tool for the invoice flow over a folder tree.

``cli_invoice.py`` runs the flow over one paper; this runs it over every receipt image below a
folder, and leaves one ``invoice.json`` per receipt. What it shares with the four processor batch
tools — the walk, the per-input record, the summary and the exit code — is :mod:`_batch`; what is
its own is the suffix set it takes, the one command it offers and where its report lands.

**One command, on purpose.** Only ``flow`` files the per-image report; the five step commands each
answer a question about one step and file no reading a corpus run can collect, so they are not
registered — naming one is a usage error, not a silent no-op. ``--provider`` and ``--model`` are
required with no default, and ``flow`` also requires ``--rubro``, so there is no flag-free method to
make: the subcommand is **required**, as it is on :mod:`scripts.tools.batch_llm`.

**The report lands beside each image, not under the mirror.** This is the one place the tool differs
from its siblings. ``invoice.json`` is filed next to the receipt it read — that is what makes it the
flow's own cache, so a second walk over the same folder returns every reading the first one already
bought and reaches no model. ``--out`` therefore names the mirror root for the per-step artifacts
and the batch record; it does **not** name where the reports go. A walk never re-ingests its own
reports: it takes image suffixes, and JSON is not one of them.

**A failed receipt does not end the walk.** The flow returns a ``FAILED`` status rather than raising
when a step fails, and a primitive's typed failure is caught the way every batch tool catches it, so
one rejected or unreadable paper is counted and the rest of the corpus still runs.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from typing import Final

import _batch
import _invoice
import _llm

from docflow.llm.primitives.errors import LLMPrimitiveError

#: The one command a corpus run makes: the flow, whose reading is the report filed per receipt.
SUBCOMMANDS: Final[tuple[str, ...]] = (_invoice.FLOW,)

#: The inputs this tool takes: the page images a receipt comes as. The vision twin of every step
#: reads the pixels, so a walk over a folder of receipts is a walk over images.
SUFFIXES: Final[tuple[str, ...]] = _llm.IMAGE_SUFFIXES

#: No command of this tool is report-only: the frame files a record for every input that produced
#: a payload, so the header may name the run root whatever the command was. Declared because the
#: guard that pins the claim is per tool.
REPORT_ONLY: Final[tuple[str, ...]] = ()


def build_parser() -> argparse.ArgumentParser:
    """Build the tool's argument parser.

    Returns:
        The parser: the folder, the asset root the steps resolve against, the scripted provider's
        switch, and the flow. A subcommand is **required** — this tool has no flag-free command to
        fall back on.
    """
    parser, subparsers = _batch.build_parser(
        "cli_batch_invoice",
        "Lab bench for the invoice flow over a folder: one reading, every receipt below it.",
        subcommand_required=True,
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
    _invoice.build_subcommands(subparsers, input_argument=False, only=SUBCOMMANDS)
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
        "cli_batch_invoice",
        str(args.subcommand),
        _invoice.COMMANDS[str(args.subcommand)],
        (LLMPrimitiveError,),
        args,
        parser,
        suffixes=SUFFIXES,
        validate=_invoice.validate_flags,
        header_extra={
            "assets_dir": str(_llm.asset_root(args)),
            **_llm.config_header(),
        },
    )


if __name__ == "__main__":
    raise SystemExit(main())
