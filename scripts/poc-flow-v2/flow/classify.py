"""Classification: is this document a receipt, before any model runs.

`my_flow.md` §3 is a cheap gate before the expensive extraction. This module is
its pure, deterministic half: it reads text and returns a verdict, using rules
that cost nothing — a CUIT pattern, an amount, a date, a fiscal keyword. It
imports no adapter, so the rule is testable without a document.

The gate is deliberately **weak, not clever**: a false negative pays the model
unnecessarily; a false positive only pays a model that then has nothing to
extract. The cheap, conservative call is to let a document through when it
shows *at least two* independent fiscal signals, and to refuse the clearly
non-receipts.
"""

from __future__ import annotations

import dataclasses
import re
from typing import Final

__all__: list[str] = [
    "Decision",
    "classify",
]

#: The independent fiscal signals the gate counts. Each is a named pattern: a
#: document earns a signal when its text matches, and the verdict needs two.
_CUIT_RE: Final = re.compile(r"\b\d{2}-\d{8}-\d\b")
_AMOUNT_RE: Final = re.compile(r"(?:\$\s*)?\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{2})?")
_DATE_RE: Final = re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b")
_FISCAL_WORDS: Final[tuple[str, ...]] = (
    "factura",
    "comprobante",
    "cuit",
    "iva",
    "cae",
    "recibo",
    "ticket",
    "nota de credito",
    "nota de débito",
    "nota de debito",
)


@dataclasses.dataclass(frozen=True, slots=True)
class Decision:
    """Whether the text is a receipt, and which signals decided it.

    Attributes:
        proceeds: ``True`` when the document should go to extraction.
        reason: Why, in words a console can print. Never empty.
        signals: The fiscal signals found, as ``name: count``.

    """

    proceeds: bool
    reason: str
    signals: dict[str, int]


def classify(text: str) -> Decision:
    """Decide whether the text looks like a receipt, by cheap rules only.

    Args:
        text: The document's text, already extracted (§2). Empty text is never a
            receipt.

    Returns:
        The decision. A document proceeds when it carries **two or more**
        independent fiscal signals; a single signal is not enough, because a
        lone keyword in prose is not a receipt.

    """
    lowered = text.lower()
    signals: dict[str, int] = {
        "cuit": len(_CUIT_RE.findall(text)),
        "amount": len(_AMOUNT_RE.findall(text)),
        "date": len(_DATE_RE.findall(text)),
    }
    for word in _FISCAL_WORDS:
        if word in lowered:
            signals["fiscal_word"] = signals.get("fiscal_word", 0) + 1

    present = [name for name, count in signals.items() if count > 0]
    if not text.strip():
        return Decision(False, "the document produced no text", signals)

    if len(present) >= 2:
        return Decision(
            True,
            f"receipt-like text ({', '.join(present)})",
            signals,
        )
    if "cuit" in present and "amount" in present:
        return Decision(True, "a CUIT and an amount are present", signals)

    return Decision(
        False,
        f"not a receipt ({', '.join(present) or 'no fiscal signals'})",
        signals,
    )
