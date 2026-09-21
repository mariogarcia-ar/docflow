"""The deterministic amount reader: a printed totals row, read by column.

Why this module exists — the defect it closes, measured:

The `desglose` step asks a local model for nine amounts. Measured over five runs
on a receipt whose totals row is perfectly legible, it returned `'00000000.00'`,
`'123456789.10'`, `'14791,98'`, `'12.345,60'` and `'21%: 2.100.00'` — one run in
five got the subtotal right, and the IVA column came back as the *rate* in two of
them (`my_flow.md` B.7: an alícuota is not an importe). The document prints:

```
    Bruto      %   Desc./Rec.   Subtotal   IVA 10,5%   IVA 21,0%   ...   TOTAL
 14.791,98  0,00      0,00     14.791,98      0,00       3.106,32   ...  17.898,30
```

**A totals row is not a semantic task.** It is two lines of fixed columns, and
`my_flow.md` §4.2 already assigns fixed-format fields to `regexp`, which *produces
candidates and never decides*. So the amounts are read here — deterministically,
from the characters — and the model keeps every field that needs reading
comprehension (razón social, descripción, the tax condition).

The columns are matched by **horizontal position**, not by label order: measured,
the label row carries 12 whitespace-separated tokens for 9 columns, because
`IVA 10,5%` and `Imp. Int.` contain spaces. Splitting the label row on whitespace
and zipping it against the value row pairs the wrong number with the wrong name —
the first prototype did exactly that and produced nine mangled labels. Assigning
each *label token* to its nearest value column, then regrouping, recovers the
nine columns correctly.

The reader refuses rather than guesses, which is the rule `my_flow.md` I10 and
B.9 state: a row it cannot identify, or a column whose label it does not know, is
simply absent from the result. An amount is never inferred from a bare number
floating in the text.
"""

from __future__ import annotations

import re
from typing import Final

from .fields import IVA_FIELD, SUBTOTAL_FIELD, TOTAL_FIELD

__all__: list[str] = ["read_amount_columns"]

#: One printed Argentine amount: thousands `.`, decimal `,`, two decimals.
#:
#: The shape is deliberately narrow. `'21%: 2.100.00'` does not match (it holds a
#: `%`), and a bare integer does not match either — a table column is printed
#: with its decimals, and accepting `'0'` would also accept a page number.
_AMOUNT: Final = re.compile(r"^\$?\d{1,3}(?:\.\d{3})*,\d{2}$")

#: The printed label of each column, normalised to the contract's field names.
#:
#: Two labels map to `subtotal` because a receipt prints either one: `Bruto` is
#: the gross figure on a discriminated receipt, `Subtotal` on the line below it.
#: Both are the net base the IVA is added to, which is what the arithmetic rule
#: in §6.4 needs.
#:
#: `iva` is **not** here: the rate columns are summable and are handled below.
#: `percepcion_iibb`, `impuestos_internos` and `otros_impuestos` are deliberately
#: **absent**: their columns exist on this fixture, but nothing in the contract
#: says which printed label is which, and a guess between them is exactly the
#: plausible-looking wrong value B.10 warns about. They are read by the model
#: until a real receipt corpus says what their labels are.
_LABELS: Final[dict[str, str]] = {
    "subtotal": SUBTOTAL_FIELD,
    "bruto": SUBTOTAL_FIELD,
    "neto": SUBTOTAL_FIELD,
    "total": TOTAL_FIELD,
}

#: The prefix that marks a column as one IVA rate, e.g. `IVA 21,0%`.
_IVA_LABEL: Final[str] = "iva"

#: How far apart a label and its value may sit, in characters, to be the same
#: column. Measured on the fixture: the widest gap between a label's centre and
#: its value's centre is 9 characters (`Imp. Int.`), so this refuses a pairing
#: that is a column away rather than accepting whichever column is nearest.
_COLUMN_TOLERANCE: Final[int] = 20


def read_amount_columns(text: str) -> dict[str, str]:
    """Read the labeled amount row and map its columns to contract fields.

    Args:
        text: The document's text, as the reader produced it.

    Returns:
        Field name to the amount **exactly as printed** (`my_flow.md` B.11: a
        number would lose the separators the document shows). Empty when no
        totals row was found — never a partial guess.

    """
    row = _amount_row(text.splitlines())
    if row is None:
        return {}
    label_line, value_line = row
    columns = _columns(label_line, value_line)

    amounts: dict[str, str] = {}
    rates: list[str] = []
    for label, value in columns:
        # The document prints its column labels capitalised (`Bruto`, `IVA
        # 21,0%`); the tables above are lowercase because that is how the
        # contract names them. Folding once here is what lets the two meet.
        folded = label.lower()
        field = _LABELS.get(folded)
        if field is not None:
            amounts.setdefault(field, value)
        elif folded.startswith(_IVA_LABEL):
            rates.append(value)
    if rates:
        # A discriminated receipt prints one column per rate and declares the
        # tax as their sum; the arithmetic rule then reads `subtotal + IVA ==
        # total` against the total it prints on the same line. A single rate is
        # the ordinary case and summing one value returns it unchanged.
        #
        # The sum is formatted **back** into the printed shape. It is computed
        # as a float because the two columns must be added, but an amount that
        # left here as `'3106.32'` would be a number wearing a string's clothes:
        # `my_flow.md` B.11 requires the printed form, and the separator is the
        # reader's evidence that the field was read and not computed.
        amounts[IVA_FIELD] = _printed(sum(_as_float(rate) for rate in rates))
    return amounts


def _amount_row(lines: list[str]) -> tuple[str, str] | None:
    """The first adjacent (label, values) pair that is a totals row.

    The test is mechanical and deliberately strict: three or more whitespace
    tokens, **every one of them an amount**. A line of prose fails it (words),
    and a line with a single number fails it (a page number, a phone number).
    Measured against the fixture, this identifies the totals row and nothing
    else in the document.
    """
    for index in range(len(lines) - 1):
        values = _tokens(lines[index + 1])
        if len(values) >= 3 and all(_AMOUNT.match(text) for _, text in values):
            return lines[index], lines[index + 1]
    return None


def _tokens(line: str) -> list[tuple[float, str]]:
    """The line's whitespace-separated tokens with their horizontal centres."""
    return [
        ((match.start() + match.end()) / 2, match.group(0))
        for match in re.finditer(r"\S+", line)
    ]


def _columns(label_line: str, value_line: str) -> list[tuple[str, str]]:
    """Pair each value with the label whose column it occupies.

    Each label **token** is assigned to the value column it sits closest to, and
    a column's label is every token assigned to it, joined in order. That is what
    rebuilds `IVA 21,0%` from its two tokens and `Imp. Int.` from its three,
    instead of leaving them as separate columns.
    """
    labels = _tokens(label_line)
    values = _tokens(value_line)
    if not values:
        return []

    def nearest_column(centre: float) -> int:
        """The value column closest to a label token's centre."""
        return min(range(len(values)), key=lambda index: abs(values[index][0] - centre))

    grouped: dict[int, list[str]] = {}
    for label_centre, label in labels:
        nearest = nearest_column(label_centre)
        if abs(values[nearest][0] - label_centre) > _COLUMN_TOLERANCE:
            # A label with no column near it belongs to another table, or to a
            # wrapped header. Dropping it is the honest answer: pairing it with
            # the nearest column anyway is how a mangled label becomes a
            # plausible-looking wrong field.
            continue
        grouped.setdefault(nearest, []).append(label)

    return [
        (" ".join(grouped[index]), value)
        for index, (_, value) in enumerate(values)
        if index in grouped
    ]


def _as_float(raw: str) -> float:
    """A printed amount as a float, for summing two IVA columns.

    Only ever called on a string `_AMOUNT` already matched, so the shape is
    known: thousands `.`, decimal `,`.
    """
    return float(raw.replace(".", "").replace(",", "."))


def _printed(value: float) -> str:
    """A float back in the Argentine printed shape: `1.234,56` (`B.11`)."""
    whole, _, cents = f"{value:.2f}".partition(".")
    grouped = f"{int(whole):,}".replace(",", ".")
    return f"{grouped},{cents}"
