"""K4 ``kernel.ocr`` — turn positioned tokens into ordered text.

The OCR counterpart of ``pdf layout``. ``pdftotext -layout`` can hand the PDF path
a character grid because the reader has the font metrics; **an OCR engine has
none**, so the grid has to be rebuilt from the token boxes. That is what this
module is, and it is why it is analysis rather than an engine call: the boxes are
already in the boundary contract, and nothing here needs a vendor.

What it produces, and what it does not
--------------------------------------

It groups tokens into **rows** by their vertical centre, orders each row left to
right, and joins the rows. The result is text in *layout order* — the vertical
position a person reads, not the order the engine happened to emit.

It does **not** produce a character grid. A grid needs every cell's extent, and an
engine that reports blocks reports where each block starts, not how wide the column
is. Padding those to columns would synthesise whitespace no measurement supports,
which is the class of stand-in this project refuses everywhere. The row structure
carries the pairing; the column widths do not exist.

Why the row test is an anchor, not a running mean
-------------------------------------------------

The legacy PoC grouped by comparing each box against its row's **running mean**, so
three boxes at 0, 24 and 30 units landed in one row whose spread was 30 while the
tolerance was 25 — the row was wider than the tolerance that formed it. Comparing
against the row's **first member** instead bounds every row's spread by the
tolerance, which is the property the tolerance is read as promising. It is asserted
by a test rather than described here.

The tolerance is the caller's
-----------------------------

``line_tolerance`` is required and has no default. A row height that the kernel
chose would be a threshold inside the kernel, and the legacy's ``25.0`` cannot be
transcribed as-is: it was in **PDF points at 72 DPI**, and a box at 300 DPI is
4.16 times larger. The caller converts — ``25.0 * dpi / 72`` reproduces the legacy's
meaning — and this module only applies the number it was given (``prd.md`` FR-15).

Orientation is the caller's too
-------------------------------

:func:`dominant_orientation` reports the counts it measured and the orientation they
support. It is an **observation**, so the layout call takes the orientation as a
parameter rather than deciding it, and reports the measurement in its evidence
either way.

PoC stage
---------

Reading order is ``S2-T07``'s responsibility (``prd.md`` FR-17). This module exists
because the OCR path has no reader of its own and the row structure is needed
before a component can own it; when the Reconstructor lands, this is what it
starts from. Marked rather than implied.
"""

# TODO: [MVP] Move this analysis to `docflow/components/reconstructor.py` when
# `S2-T07` lands. It is here because K4's OCR path needs a reading and a kernel is
# the only layer that reads: `prd.md` FR-17 assigns the *order* to the
# Reconstructor, and this function is the raw material for it rather than a
# competitor. The move is a relocate, not a rewrite - nothing here imports a
# vendor or an adapter.

from __future__ import annotations

from collections.abc import Sequence
from types import MappingProxyType
from typing import Final

from docflow.kernels.types import Box, Evidence, KernelResult, Reason, Token

__all__: list[str] = ["ORIENTATIONS", "dominant_orientation", "layout"]

#: The two orientations a document's text may run in.
ORIENTATIONS: Final[tuple[str, ...]] = ("horizontal", "vertical")

#: The separator between two tokens that share a row.
#:
#: A recorded constant rather than a defaulted parameter, because it is the one
#: thing in the output that says *these two sat beside each other*. It is also the
#: character a Markdown table uses, which is a collision worth naming rather than
#: discovering: a caller that feeds this text to a Markdown renderer must know that
#: a ``|`` here means adjacency and not a table cell.
SEPARATOR: Final[str] = " | "

#: The reason code for a selection that yielded no text at all.
#:
#: From the closed set of ``kernel-cli.md`` §5, and the same code ``pdf layout``
#: reports: a page whose tokens are all whitespace is a measurement about the
#: reading, not a failure of the call.
_CODE_BLANK: Final[str] = "blank_page"


def dominant_orientation(tokens: Sequence[Token]) -> tuple[str, dict[str, float]]:
    """Report which orientation the tokens' shapes support, and by how much.

    A token counts as ``horizontal`` when its box is at least as wide as it is
    tall. That is a **proxy** for "the text runs along the x axis", not a
    measurement of direction: a two-line block in a table cell is taller than it is
    wide and counts as ``vertical`` although no glyph in it is rotated. The
    ambiguity is why both the counts and the winner are returned — a caller that
    sees a narrow majority can treat it as the weak evidence it is.

    Args:
        tokens: The tokens to measure.

    Returns:
        The dominant orientation, and the counts behind it. A tie, or a selection
        with no tokens, reports ``horizontal`` — the reading default the legacy
        used, and the one that degrades to the familiar case.

    """
    counts = {"horizontal": 0.0, "vertical": 0.0}
    for token in tokens:
        box = token.bbox
        counts["horizontal" if box.width >= box.height else "vertical"] += 1.0

    if counts["vertical"] > counts["horizontal"]:
        return "vertical", counts

    return "horizontal", counts


def layout(
    tokens: Sequence[Token],
    *,
    line_tolerance: float,
    orientation: str = "horizontal",
    separator: str = SEPARATOR,
) -> KernelResult[str]:
    """Order positioned tokens into rows and join them into text.

    Args:
        tokens: The tokens to order, in whatever order the engine produced them.
        line_tolerance: How far apart, in the boxes' own units, two tokens may be
            and still share a row. Required: the value depends on the resolution
            the tokens were read at, so a constant here would mean different things
            at different DPIs.
        orientation: ``horizontal`` (rows by vertical position, left to right) or
            ``vertical`` (columns by horizontal position, top to bottom) — see
            :func:`dominant_orientation`.
        separator: What to place between two tokens that share a row.

    Returns:
        The ordered text, or no value and a typed ``Reason`` when the tokens hold
        nothing but whitespace.

    Raises:
        ValueError: If the tolerance is not positive, or the orientation is not one
            of :data:`ORIENTATIONS`. Both are mistakes in the request rather than
            answers about a document.

    """
    if line_tolerance <= 0:
        raise ValueError(
            f"line_tolerance must be positive, got {line_tolerance}. A tolerance of "
            "zero would put every token in a row of its own, which is the engine's "
            "own order wearing this module's name."
        )
    if orientation not in ORIENTATIONS:
        raise ValueError(
            f"orientation must be one of {list(ORIENTATIONS)}, got {orientation!r}."
        )

    usable = [_entry(token) for token in tokens if token.text.strip()]
    measured = {
        "tokens_read": float(len(tokens)),
        "tokens_placed": float(len(usable)),
    }

    rows = (
        _rows_by_vertical(usable, line_tolerance)
        if orientation == "horizontal"
        else _rows_by_horizontal(usable, line_tolerance)
    )

    if not usable:
        # The engine ran and produced only whitespace. That is a measurement about
        # the reading, not a failure of the call.
        return KernelResult(
            value=None,
            evidence=_evidence(
                measured, orientation, line_tolerance, separator, rows=0.0
            ),
            reason=Reason(
                code=_CODE_BLANK,
                message=(
                    "the selection yielded no text, so there is no layout to order. "
                    "This is what a blank page looks like: it has pixels and no "
                    "characters to place."
                ),
            ),
        )

    text = "\n".join(separator.join(entry["text"] for entry in row) for row in rows)
    text += "\n"

    measured["rows"] = float(len(rows))
    measured["characters"] = float(len(text))

    return KernelResult(
        value=text,
        evidence=_evidence(
            measured, orientation, line_tolerance, separator, rows=float(len(rows))
        ),
        reason=None,
    )


def _entry(token: Token) -> dict[str, object]:
    """Reduce a token to the four values the ordering reads.

    The coordinates are read through :func:`_coordinate`, so a box built by hand
    with a non-numeric member is refused here with a message naming the member —
    rather than failing later inside the arithmetic with a ``TypeError`` that names
    nothing. A `TypeError` from a kernel is exit `1`, *"a defect in this build"*,
    and this is the caller's input.

    Args:
        token: The token.

    Returns:
        Its text, its left edge, and the two centre coordinates.

    Raises:
        ValueError: If one of the box's four numbers is not a real number.

    """
    x = _coordinate(token.bbox, "x")
    y = _coordinate(token.bbox, "y")
    width = _coordinate(token.bbox, "width")
    height = _coordinate(token.bbox, "height")

    return {
        "text": token.text.strip(),
        "left": x,
        "center_x": x + width / 2,
        "center_y": y + height / 2,
    }


def _coordinate(box: Box, member: str) -> float:
    """Read one member of a box as a real number, or name the member that is not.

    Args:
        box: The box.
        member: The member's name.

    Returns:
        The value.

    Raises:
        ValueError: If the member is missing or is not a real number.

    """
    value = getattr(box, member, None)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(
            f"the token's bbox.{member} is {value!r}, not a number, so the token "
            "cannot be placed. Every token read by an engine carries four numbers "
            "here, so this means a caller built one by hand."
        )
    return float(value)


def _rows_by_vertical(
    entries: list[dict[str, object]], tolerance: float
) -> list[list[dict[str, object]]]:
    """Group entries into rows by vertical centre, then order each row by left edge.

    The anchor is each row's **first** member rather than its running mean: see the
    module docstring. A row formed this way cannot be wider than ``tolerance``.

    Args:
        entries: The reduced tokens.
        tolerance: The row tolerance, in the boxes' units.

    Returns:
        The rows, top to bottom, each ordered left to right.

    Raises:
        ValueError: If a tolerance is not a number the comparison can use, which
            means the caller passed geometry rather than the resolution it was read
            at.

    """
    return _group(entries, "center_y", "left", tolerance)


def _rows_by_horizontal(
    entries: list[dict[str, object]], tolerance: float
) -> list[list[dict[str, object]]]:
    """Group entries into columns by horizontal centre, then order by vertical centre.

    Args:
        entries: The reduced tokens.
        tolerance: The column tolerance, in the boxes' units.

    Returns:
        The columns, left to right, each ordered top to bottom.

    Raises:
        ValueError: If the tolerance is not a number the comparison can use.

    """
    return _group(entries, "center_x", "center_y", tolerance)


def _group(
    entries: list[dict[str, object]],
    axis: str,
    within: str,
    tolerance: float,
) -> list[list[dict[str, object]]]:
    """Group entries along one axis, ordering each group along the other.

    Args:
        entries: The reduced tokens.
        axis: The coordinate that decides the group, e.g. ``center_y``.
        within: The coordinate that orders inside a group, e.g. ``left``.
        tolerance: How far from a group's first member a token may sit.

    Returns:
        The groups in ascending order of their anchor, each ordered ascending along
        ``within``.

    Raises:
        ValueError: If a coordinate is not comparable, which happens when a caller
            passes boxes whose units do not match the tolerance.

    """
    groups: list[dict[str, object]] = []
    for entry in sorted(entries, key=lambda item: _number(item, axis)):
        coordinate = _number(entry, axis)
        placed = False
        for group in groups:
            # The anchor, not a running mean: the spread this admits is bounded by
            # the tolerance, which is what the tolerance is read as promising.
            if abs(_number(group, "anchor") - coordinate) <= tolerance:
                _members(group).append(entry)
                placed = True
                break
        if not placed:
            groups.append({"anchor": coordinate, "members": [entry]})

    groups.sort(key=lambda group: _number(group, "anchor"))
    return [
        sorted(_members(group), key=lambda item: _number(item, within))
        for group in groups
    ]


def _members(group: dict[str, object]) -> list[dict[str, object]]:
    """Return the mutable member list of a group.

    Args:
        group: The group.

    Returns:
        Its members, which the caller appends to.

    """
    members = group["members"]
    assert isinstance(members, list), "every group is built with a member list"
    return members


def _number(entry: dict[str, object], key: str) -> float:
    """Read one coordinate as a number, or say which one was not.

    Args:
        entry: The reduced token or group.
        key: The coordinate's name.

    Returns:
        The value.

    Raises:
        ValueError: If the value is missing or is not a real number.

    """
    value = entry.get(key)
    if not isinstance(value, (int, float)):
        raise ValueError(
            f"cannot order by {key!r}: the value is {value!r}, not a number. Every "
            "token carries a box, so this means a caller built one by hand."
        )
    return float(value)


def _evidence(
    measured: dict[str, float],
    orientation: str,
    tolerance: float,
    separator: str,
    *,
    rows: float,
) -> Evidence:
    """Assemble the evidence record for a layout call.

    Args:
        measured: The numbers this call produced.
        orientation: The orientation it was asked for.
        tolerance: The tolerance it applied.
        separator: The adjacency marker it used.
        rows: How many rows it produced.

    Returns:
        The record, with the request's own terms alongside the measurements.

    """
    measurements = dict(measured)
    measurements["rows"] = rows
    measurements["line_tolerance_applied"] = float(tolerance)

    return Evidence(
        terms=MappingProxyType({}),
        measurements=MappingProxyType(measurements),
        observed=MappingProxyType(
            {
                "orientation": orientation,
                "row_test": "anchor",
                "separator": separator,
                # Named rather than implied, so a reader of the envelope knows what
                # kind of reading this is: rows of blocks, not a character grid.
                "reading": "rows_from_boxes",
            }
        ),
    )
