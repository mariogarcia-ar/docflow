#!/usr/bin/env python
"""One document, one run: the v2 flow's console surface.

This is the thin caller of the `flow` library beside it. The library owns the
process; this file owns the argument surface and prints the report.

Run:

    python scripts/poc-flow-v2/myflow.py <document>

Output: a report on stdout — where the run went, what was decided, and what to
read next. `--json` prints the engine's result instead, for a program.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import sys

# The `flow` package sits beside this script, not on `sys.path`; the import must
# happen once this file's directory is the working directory. A top-level
# import would fail when run as a script.  pylint: disable=import-outside-toplevel


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser: the document and the run's dials."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("document", type=pathlib.Path, help="a PDF or image")
    parser.add_argument(
        "--work-root",
        type=pathlib.Path,
        default=None,
        help="directory for the artifacts, journal and run record; when given, "
        "a second run resumes at the first unfinished stage",
    )
    parser.add_argument(
        "--redo",
        action="store_true",
        help="ignore the journal and re-run every stage",
    )
    parser.add_argument(
        "--pause",
        action="store_true",
        help="stop after the current stage completes, journal intact",
    )
    parser.add_argument(
        "--stop",
        action="store_true",
        help="stop after the current stage completes and mark the run stopped",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="print progress to stderr as each stage runs",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the engine's result as JSON instead of the operator report",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="print the result as indented JSON (implies --json)",
    )
    parser.add_argument(
        "--resolve",
        action="store_true",
        help="ask the frontier to suggest a value for each pending field "
        "(needs --work-root)",
    )
    parser.add_argument(
        "--confirm",
        action="append",
        default=[],
        metavar="FIELD=VALUE",
        help="a human's settled value for a pending field (repeatable)",
    )
    return parser


def _serializable(value: object) -> object:
    """Turn dataclasses and mappings into plain JSON-able structures."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            key: _serializable(val) for key, val in dataclasses.asdict(value).items()
        }
    if isinstance(value, dict):
        return {str(key): _serializable(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serializable(val) for val in value]
    return value


def main(argv: list[str] | None = None) -> int:  # pylint: disable=too-many-locals
    """Run the flow over one document and print the report or the JSON result."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    document: pathlib.Path = args.document
    if not document.is_file():
        parser.error(f"{document} does not exist or is not a file")

    from flow import render_report, run

    outcome = run(
        document,
        {},
        work_root=args.work_root,
        redo=args.redo,
        pause=args.pause,
        stop=args.stop,
        verbose=args.verbose,
    )

    if args.resolve or args.confirm:
        outcome = _settle(outcome, document, args)

    if args.json or args.pretty:
        print(
            json.dumps(
                _serializable(outcome.result),
                ensure_ascii=False,
                indent=2 if args.pretty else None,
            )
        )
        return 0

    print(render_report(document, outcome.result, outcome.steps, args.work_root))
    return 0


def _settle(outcome, document, args):  # pylint: disable=too-many-locals
    """The frontier suggestion and the human's confirmations (§8, I6).

    Each branch carries its own local bookkeeping (the suggestion note, the
    per-field refusal notes, the settled/refused dicts); collapsing them into
    a shared helper would obscure the two distinct §8/I6 hand-offs.
    """
    from flow.config import DEFAULT_CONFIG
    from flow.frontier import suggest
    from flow.hitl import HumanConfirmation, apply_confirmations, pending_items
    from flow.material import read_material
    from flow.serial import encode

    if args.work_root is None:
        return outcome

    queued = pending_items(outcome.result.decisions)
    notes = list(outcome.result.notes)
    extracted = dict(outcome.result.extracted)

    if args.resolve and queued:
        material = read_material(document, DEFAULT_CONFIG)
        suggestions, note = suggest(queued, material, DEFAULT_CONFIG, document.name)
        if note:
            notes.append(f"frontier: {note}")
        elif suggestions:
            notes.append(f"frontier suggested {len(suggestions)} value(s)")
        # The suggestion is evidence, never a verdict: written beside the queue.
        (args.work_root / "resolution.json").write_text(
            encode(
                {
                    "suggestions": [
                        {
                            "field": s.field,
                            "suggested_value": s.suggested_value,
                            "reason": s.reason,
                        }
                        for s in suggestions
                    ]
                }
            ).decode("utf-8"),
            encoding="utf-8",
        )

    if args.confirm:
        pending_by_field = {item.field: item for item in queued}
        confirmations = []
        for entry in args.confirm:
            field, _, value = entry.partition("=")
            confirmations.append(HumanConfirmation(field=field, value=value))
        settled, refusals = apply_confirmations(confirmations, pending_by_field)
        extracted.update(settled)
        for refusal in refusals:
            notes.append(f"confirmation refused: {refusal}")
        (args.work_root / "confirmed.json").write_text(
            encode({"human_confirmed": settled}).decode("utf-8"),
            encoding="utf-8",
        )

    from flow.fields import FieldResult

    return type(outcome)(
        result=FieldResult(
            decisions=outcome.result.decisions,
            trace=outcome.result.trace,
            extracted=extracted,
            notes=notes,
        ),
        steps=outcome.steps,
    )


if __name__ == "__main__":
    sys.exit(main())
