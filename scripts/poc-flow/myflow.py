#!/usr/bin/env python
"""One document, one answer: extract fiscal fields through the MoE engine.

This is the thin caller of the `flow` library next to it. The library owns the
flow; this file owns the argument surface and the console report.

Run:

    python scripts/poc-flow/myflow.py <document>

Output: one JSON object per document with the per-field decisions, the reason
codes, and the confirmed fields.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import sys


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser: the document and the run's dials."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("document", type=pathlib.Path, help="a PDF or image")
    parser.add_argument(
        "--own-cuit",
        action="append",
        default=[],
        help="a CUIT of the business itself (repeatable); the own-CUIT-as-"
        "emissor veto is fixed from day one",
    )
    parser.add_argument(
        "--work-root",
        type=pathlib.Path,
        default=None,
        help="directory for the intermediate artifacts and the resume journal; "
        "when given, a second run resumes at the first unfinished stage",
    )
    parser.add_argument(
        "--redo",
        action="store_true",
        help="ignore the journal and re-run every stage",
    )
    parser.add_argument(
        "--resolve",
        action="store_true",
        help="ask the frontier model to suggest a value for each field the "
        "engine could not confirm (needs --work-root)",
    )
    parser.add_argument(
        "--confirm",
        action="append",
        default=[],
        metavar="FIELD=VALUE",
        help="a human's settled value for a pending field, e.g. "
        "--confirm total=12100.00 (repeatable); only pending fields may be "
        "confirmed",
    )
    parser.add_argument("--pretty", action="store_true", help="indent the JSON output")
    return parser


def _serializable(result: object) -> object:
    """Turn the flow's dataclasses into plain JSON-able structures."""
    if dataclasses.is_dataclass(result) and not isinstance(result, type):
        return {
            key: _serializable(value)
            for key, value in dataclasses.asdict(result).items()
        }
    if isinstance(result, dict):
        return {str(key): _serializable(value) for key, value in result.items()}
    if isinstance(result, (list, tuple)):
        return [_serializable(value) for value in result]
    return result


def main(argv: list[str] | None = None) -> int:
    """Run the flow over one document and print the JSON verdict.

    Args:
        argv: The command-line arguments, or ``None`` for ``sys.argv``.

    Returns:
        ``0`` on success.

    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    document: pathlib.Path = args.document
    if not document.is_file():
        parser.error(f"{document} does not exist or is not a file")

    # The `flow` package sits beside this script, not on `sys.path`, so the
    # import must happen once this file's directory is the working directory
    # (`python scripts/poc-flow/myflow.py …`). A top-level import would fail
    # when run as a script.  pylint: disable=import-outside-toplevel
    from flow import run
    from flow.config import DEFAULT_CONFIG

    own_cuits = frozenset(
        "".join(ch for ch in cuit if ch.isdigit()) for cuit in args.own_cuit
    )

    from flow.hitl import HumanConfirmation

    confirmations: list[HumanConfirmation] = []
    for entry in args.confirm:
        if "=" not in entry:
            parser.error(f"--confirm {entry!r} is not FIELD=VALUE")
        field, value = entry.split("=", 1)
        confirmations.append(HumanConfirmation(field=field, value=value))

    result = run(
        document,
        DEFAULT_CONFIG,
        own_cuits=own_cuits,
        work_root=args.work_root,
        redo=args.redo,
        resolve=args.resolve,
        confirm=confirmations or None,
    )

    payload = _serializable(result)
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2 if args.pretty else None,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
