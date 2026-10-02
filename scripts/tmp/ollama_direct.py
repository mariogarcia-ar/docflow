"""Scratch probe: call the Ollama HTTP API directly, with no ``docflow`` import in the way.

A throwaway for comparing a raw ``POST /api/chat`` against what the library's provider seam does.
It is not the lab bench: nothing here is reused by ``scripts/tools/``.

    python scripts/tmp/ollama_direct.py --list-models
    python scripts/tmp/ollama_direct.py --model gemma3:12b "What is an invoice?"

The transport is its sibling :mod:`_ollama`, so a probe runs from this folder.

``--model`` is required: a default model is the silent stand-in this project forbids.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Any

from _ollama import (
    add_connection_arguments,
    chat,
    list_models,
    print_answer,
)


def build_parser() -> argparse.ArgumentParser:
    """Build the probe's argument parser.

    Returns:
        The parser, with the prompt and the flags it documents.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("prompt", nargs="?", help="the user message to send")
    parser.add_argument(
        "--model", help="the model tag to reach (required unless --list-models)"
    )
    add_connection_arguments(parser)
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="print every tag the daemon serves and exit",
    )
    return parser


def _stats(body: dict[str, Any]) -> dict[str, Any]:
    """Return the token counts a run is judged by.

    Args:
        body: The parsed response body.

    Returns:
        The model, the reason it stopped and the token counts.
    """
    return {
        "model": body.get("model"),
        "done_reason": body.get("done_reason"),
        "prompt_eval_count": body.get("prompt_eval_count"),
        "eval_count": body.get("eval_count"),
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Run the probe.

    Args:
        argv: The command line, defaulting to ``sys.argv[1:]``.

    Returns:
        ``0`` when the daemon answered, ``2`` when the arguments do not state a call.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    base_url = str(args.base_url).rstrip("/")

    if args.list_models:
        for name in list_models(base_url, args.timeout):
            print(name)
        return 0

    if not args.model or not args.prompt:
        parser.error("--model and a prompt are required unless --list-models")

    body = chat(
        base_url,
        args.model,
        args.prompt,
        system=args.system,
        options=dict(args.option),
        timeout=args.timeout,
    )
    print_answer(body, raw=args.raw)
    if not args.raw:
        print(json.dumps(_stats(body)), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
