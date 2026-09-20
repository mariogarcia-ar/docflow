"""The run report: where the flow went, and what a human has to read.

The run's JSON verdict is the machine's contract; this module is the operator's.
It answers three questions, in this order:

1. **Where did the run go?** The step trace, in order, with `ran` versus
   `reused` — so a resumed run is visible as a resumed run.
2. **What did the engine decide, per field?** Grouped by outcome, with the value
   it settled on and the reason code behind it.
3. **Do I have to open a file, and which one?** The files that carry work left
   for a person, or the evidence behind a decision that was not confirmed.

Nothing here imports `docflow`, and nothing here re-derives a decision: every
line is read from the result the engine returned and the trace the stages
recorded. A report that computed its own score would be a second engine.
"""

from __future__ import annotations

import pathlib
from collections.abc import Sequence
from typing import Final

from .fields import (
    DECISION_CONFIRMED,
    DECISION_ESCALATE,
    DECISION_REVIEW,
    FieldDecision,
    FieldResult,
)
from .progress import StepTrace

__all__: list[str] = ["render"]

#: The order the field groups are printed in: what the engine settled first,
#: then what a person has to look at.
_GROUPS: Final[tuple[tuple[str, str], ...]] = (
    (DECISION_CONFIRMED, "confirmed"),
    (DECISION_REVIEW, "review"),
    (DECISION_ESCALATE, "escalate"),
)

#: Severity order inside a group, so a critical field is never buried under a
#: low one. An unknown severity sorts last rather than first.
_SEVERITY_ORDER: Final[dict[str, int]] = {
    "critica": 0,
    "alta": 1,
    "media": 2,
    "baja": 3,
}

#: What each artifact is for, so the "read next" section says why to open it
#: instead of only naming the path. Only the files that carry work left for a
#: person are listed: the intermediates are readable but nobody has to read
#: them to finish the run, and naming them buries the two that matter.
_ARTIFACT_PURPOSE: Final[dict[str, str]] = {
    "pending.json": "the fields a human must settle",
    "resolution.json": "the frontier's suggestions — evidence, never a verdict",
    "confirmed.json": "the values a human settled — the only ground truth",
    "decision.json": "every decision, with the signals behind it",
}

#: The artifact that must be read first when anything is unconfirmed. The queue
#: is the hand-off: everything else is evidence for one of its entries.
_QUEUE_ARTIFACT: Final[str] = "pending.json"

#: The columns of a decision row, sized so a row with the longest reason code
#: still fits a standard 80-column console without wrapping.
_FIELD_WIDTH: Final[int] = 30
_VALUE_WIDTH: Final[int] = 14


def render(
    document: pathlib.Path,
    result: FieldResult,
    steps: Sequence[StepTrace],
    work_root: pathlib.Path | None = None,
) -> str:
    """Render one run as an operator report.

    Args:
        document: The document that was processed.
        result: The engine's per-field verdicts.
        steps: The run's step trace, in order.
        work_root: Where the artifacts were written, when there is one.

    Returns:
        The report, ready to print.

    """
    lines = [f"document: {document.name}"]
    if work_root is not None:
        lines.append(f"work root: {work_root}")
    lines.append("")
    lines.append("path")
    lines.extend(_path_lines(steps))
    lines.extend(_field_lines(result))
    lines.extend(_next_lines(result, steps))
    if result.notes:
        lines.append("")
        lines.append("notes")
        lines.extend(f"  - {note}" for note in result.notes)
    return "\n".join(lines)


def _path_lines(steps: Sequence[StepTrace]) -> list[str]:
    """The steps in order: what ran, what was reused, and what each produced."""
    if not steps:
        return ["  (not recorded)"]
    lines: list[str] = []
    for index, entry in enumerate(steps, start=1):
        line = f"  {index}. {entry.name:<9} {entry.action:<7}"
        if entry.detail:
            line += f" {entry.detail}"
        lines.append(line)
    return lines


def _field_lines(result: FieldResult) -> list[str]:
    """The decisions, grouped by outcome, most severe first inside each group."""
    lines: list[str] = []
    for outcome, label in _GROUPS:
        fields = [
            decision
            for decision in result.decisions.values()
            if decision.decision == outcome
        ]
        if not fields:
            continue
        lines.append("")
        lines.append(f"{label} ({len(fields)})")
        lines.extend(_decision_lines(fields))
    return lines


def _decision_lines(decisions: list[FieldDecision]) -> list[str]:
    """One line per field: the value the engine has, and why."""
    ordered = sorted(
        decisions,
        key=lambda d: (_SEVERITY_ORDER.get(d.severity, 9), d.field),
    )
    return [_decision_line(decision) for decision in ordered]


def _decision_line(decision: FieldDecision) -> str:
    """One field's row: severity, name, the winner's printed value, and why."""
    value = decision.winner.raw_value if decision.winner is not None else "—"
    if len(value) > _VALUE_WIDTH:
        value = value[: _VALUE_WIDTH - 1] + "…"
    reason = decision.reason_codes[0] if decision.reason_codes else "—"
    line = (
        f"  {decision.severity:<7} {decision.field:<{_FIELD_WIDTH}}"
        f" {value:<{_VALUE_WIDTH}} {reason}"
    ).rstrip()
    why = decision.notes[0] if decision.notes else ""
    if why:
        line += f"\n      why: {why}"
    return line


def _next_lines(result: FieldResult, steps: Sequence[StepTrace]) -> list[str]:
    """The files worth opening, in the order worth opening them.

    Only files a step actually wrote are named — a path that was never written
    is not an instruction, it is a guess. The queue comes first when it has
    something in it, because that is where the unfinished work is.
    """
    written: list[str] = []
    for entry in steps:
        for path in entry.artifacts:
            name = pathlib.PurePath(path).name
            if name not in written:
                written.append(name)

    pending = sum(
        1
        for decision in result.decisions.values()
        if decision.decision != DECISION_CONFIRMED
    )
    ordered = sorted(
        written,
        key=lambda name: 0 if name == _QUEUE_ARTIFACT else 1,
    )

    lines: list[str] = []
    for name in ordered:
        if name not in _ARTIFACT_PURPOSE:
            continue
        if name == _QUEUE_ARTIFACT and not pending:
            continue
        path = next(
            artifact
            for entry in steps
            for artifact in entry.artifacts
            if pathlib.PurePath(artifact).name == name
        )
        head = f"  {path}"
        if name == _QUEUE_ARTIFACT:
            head += f"  ({pending} field(s))"
        lines.append(f"{head} — {_ARTIFACT_PURPOSE[name]}")

    if not lines:
        if pending:
            # Nothing was written (no work root), so there is no file to name.
            # Saying "nothing to read" here would read as "nothing to do".
            return [
                "",
                "read next",
                "  no file: this run wrote none — pass --work-root to keep the queue",
            ]
        return ["", "read next", "  nothing: every field is confirmed"]
    return ["", "read next", *lines]
