"""Deterministic validators: the mechanical experts of the decision engine.

Each validator answers PASS / FAIL / UNKNOWN (`my_flow.md` I10). UNKNOWN means
*the information to decide is missing*: it scores nothing, penalises nothing and
never vetoes. A hard refutation is only produced when the rule declares it has
every component it needs (`my_flow.md` §6.3/§6.4) — an incomplete equation is
UNKNOWN, never FAIL.

`my_flow.md` §6.1 makes the split explicit: a parser produces candidates (it
never decides), and a validator supports or refutes. This module is the
validator half; the candidate-producing half lives in `extract.py`.

Everything here is pure: it reads strings and returns :class:`EvidenceSignal`,
so every rule is testable without an adapter or a document.
"""

from __future__ import annotations

import datetime
import re
from typing import Final

from .fields import (
    FAIL,
    IVA_FIELD,
    PASS,
    SUBTOTAL_FIELD,
    TOTAL_FIELD,
    UNKNOWN,
    EvidenceSignal,
)

__all__: list[str] = [
    "ARITHMETIC_INCONSISTENT",
    "CUITS_CHECKSUM_INVALID",
    "CUITS_OWN_AS_EMISOR",
    "DATE_NONEXISTENT",
    "arithmetic_consistent",
    "arithmetic_signal",
    "cuit_signal",
    "date_signal",
    "required_components_for",
]

#: The veto names the engine recognizes (`my_flow.md` §6.3). The closed list is
#: owned by the config; these constants are the four this version implements.
CUITS_CHECKSUM_INVALID: Final[str] = "CUITS_CHECKSUM_INVALID"
CUITS_OWN_AS_EMISOR: Final[str] = "CUITS_OWN_AS_EMISOR"
DATE_NONEXISTENT: Final[str] = "DATE_NONEXISTENT"
ARITHMETIC_INCONSISTENT: Final[str] = "ARITHMETIC_INCONSISTENT"

#: The receipt types that do **not** discriminate IVA (`my_flow.md` §6.4): for a
#: Factura C the net-plus-VAT equation has nothing to judge, so no component is
#: required and the validator answers UNKNOWN rather than vetoing a type it does
#: not model.
_NO_IVA_TYPES: Final[frozenset[str]] = frozenset({"C"})

#: TODO: [MVP] The ``required_components`` per ``tipo_comprobante`` (`my_flow.md`
#: §6.4) is not modelled: this version assumes the net-plus-VAT combination and
#: reports UNKNOWN whenever a component is missing.

#: A decimal separator parse that tolerates the Argentine printed format:
#: thousands ``.``, decimal ``,``. Returns ``None`` when the text is not a
#: plain amount.
_AMOUNT_RE: Final = re.compile(r"^\$?\s*[\d\s.,]+$")


def _digits(cuit: str) -> str:
    """The CUIT's digits only."""
    return "".join(ch for ch in cuit if ch.isdigit())


def _cuit_checksum_ok(cuit: str) -> bool:
    """The AFIP/ARCA CUIT check digit (modulo 11 over the weighted digits).

    Pure arithmetic: returns ``True`` when the last digit matches the check,
    ``False`` when it does not.
    """
    digits = _digits(cuit)
    if len(digits) != 11:
        return False
    weights = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)
    total = sum(int(d) * w for d, w in zip(digits[:10], weights, strict=True))
    check = 11 - (total % 11)
    if check == 11:
        check = 0
    if check == 10:
        return False  # an invalid CUIT by construction
    return check == int(digits[10])


def _parse_amount(raw: str) -> float | None:
    """Parse a printed Argentine amount to a float, or ``None`` when it is not.

    The printed form ``1.234,56`` is thousands ``.`` decimal ``,``; the reversed
    form (decimal ``.``) is also accepted so a mis-read does not become an
    UNKNOWN that hides a real inconsistency.
    """
    text = raw.strip().lstrip("$").strip()
    if not text or not _AMOUNT_RE.match(text):
        return None
    compact = text.replace(" ", "")
    if "," in compact and "." in compact:
        normalized = compact.replace(".", "").replace(",", ".")
    elif "," in compact:
        normalized = compact.replace(",", ".")
    else:
        normalized = compact
    try:
        return float(normalized)
    except ValueError:
        return None


def required_components_for(tipo_comprobante: str) -> tuple[str, ...]:
    """The components the arithmetic rule needs for a receipt type (§6.4).

    A Factura C does not discriminate IVA, so the net-plus-VAT equation has no
    components and the validator answers UNKNOWN rather than judging it wrong.
    The default is the net-plus-VAT combination: subtotal, IVA and total.
    """
    tipo = str(tipo_comprobante).strip()
    if tipo in _NO_IVA_TYPES:
        return ()
    return (SUBTOTAL_FIELD, IVA_FIELD, TOTAL_FIELD)


def arithmetic_consistent(
    subtotal: str,
    iva: str,
    total: str,
    *,
    tolerance: float = 0.01,
) -> bool:
    """Whether ``subtotal + IVA == total`` within tolerance.

    Pure predicate, exported so the engine can evaluate **combinations** (§6.4)
    without reaching into the validator's signal vocabulary. Returns ``False``
    when any component is unparseable — the caller decides whether that is
    UNKNOWN (a single combination) or a non-unique resolution (many).
    """
    sub = _parse_amount(subtotal)
    tax = _parse_amount(iva)
    tot = _parse_amount(total)
    if sub is None or tax is None or tot is None:
        return False
    return abs(sub + tax - tot) <= tolerance


def cuit_signal(
    value: str,
    *,
    own_cuits: frozenset[str],
    family_points: dict[str, int],
) -> EvidenceSignal:
    """The CUIT validator: checksum and own-CUIT guard.

    The own-CUIT rule is fixed from day one (`my_flow.md` §6.3): a CUIT that is
    the business's own cannot be the issuer's. It does not depend on learning;
    it requires the own-CUIT list as configuration.

    Args:
        value: The candidate's raw CUIT.
        own_cuits: The business's own CUITs, digits only. Empty means *no
            own-CUIT configured*, which makes that half UNKNOWN rather than a
            silent PASS.
        family_points: The per-family points table.

    Returns:
        A ``DETERMINISTIC`` PASS when the checksum holds, a hard refutation when
        it fails or is an own CUIT, UNKNOWN when the value is not 11 digits.

    """
    digits = _digits(value)
    if len(digits) != 11:
        return EvidenceSignal(
            "DETERMINISTIC",
            UNKNOWN,
            family_points["DETERMINISTIC"],
            "CUIT has no 11 digits, so the checksum cannot be decided",
        )

    if not _cuit_checksum_ok(value):
        return EvidenceSignal(
            "DETERMINISTIC",
            FAIL,
            family_points["DETERMINISTIC"],
            CUITS_CHECKSUM_INVALID,
        )

    if digits in own_cuits:
        return EvidenceSignal(
            "DETERMINISTIC",
            FAIL,
            family_points["DETERMINISTIC"],
            CUITS_OWN_AS_EMISOR,
        )

    return EvidenceSignal(
        "DETERMINISTIC", PASS, family_points["DETERMINISTIC"], "CUIT checksum valid"
    )


def date_signal(value: str, *, family_points: dict[str, int]) -> EvidenceSignal:
    """The date validator: a date must exist and parse.

    Args:
        value: The candidate's raw date.
        family_points: The per-family points table.

    Returns:
        A ``DETERMINISTIC`` PASS when the date exists, a hard refutation when it
        does not, UNKNOWN when it is empty or not a plain date.

    """
    text = value.strip()
    if not text:
        return EvidenceSignal(
            "DETERMINISTIC",
            UNKNOWN,
            family_points["DETERMINISTIC"],
            "no date to validate",
        )
    try:
        datetime.date.fromisoformat(text)
    except ValueError:
        return EvidenceSignal(
            "DETERMINISTIC",
            FAIL,
            family_points["DETERMINISTIC"],
            DATE_NONEXISTENT,
        )
    return EvidenceSignal(
        "DETERMINISTIC", PASS, family_points["DETERMINISTIC"], "date exists"
    )


def arithmetic_signal(
    subtotal: str,
    iva: str,
    total: str,
    *,
    family_points: dict[str, int],
    tolerance: float = 0.01,
) -> EvidenceSignal:
    """The arithmetic validator over the ``{subtotal, IVA, total}`` combination.

    A complete equation yields PASS or a hard refutation. A missing component
    yields UNKNOWN (`my_flow.md` §6.4): an incomplete equation cannot produce a
    veto, because the "inconsistency" might only be the absent component.

    Args:
        subtotal: The printed subtotal.
        iva: The printed IVA.
        total: The printed total.
        family_points: The per-family points table.
        tolerance: The explicit tolerance, default one cent. No validator accepts
            "≈" (`my_flow.md` §7).

    Returns:
        PASS when ``subtotal + IVA == total`` within tolerance; a hard
        refutation otherwise; UNKNOWN when any component is unparseable.

    """
    if not all((subtotal.strip(), iva.strip(), total.strip())):
        return EvidenceSignal(
            "DETERMINISTIC",
            UNKNOWN,
            family_points["DETERMINISTIC"],
            "arithmetic needs subtotal, IVA and total; a component is missing",
        )

    sub = _parse_amount(subtotal)
    tax = _parse_amount(iva)
    tot = _parse_amount(total)
    if sub is None or tax is None or tot is None:
        return EvidenceSignal(
            "DETERMINISTIC",
            UNKNOWN,
            family_points["DETERMINISTIC"],
            "a component is not a plain amount, so the equation cannot be judged",
        )

    if abs(sub + tax - tot) <= tolerance:
        return EvidenceSignal(
            "DETERMINISTIC",
            PASS,
            family_points["DETERMINISTIC"],
            f"subtotal+IVA==total within {tolerance}",
        )
    return EvidenceSignal(
        "DETERMINISTIC",
        FAIL,
        family_points["DETERMINISTIC"],
        ARITHMETIC_INCONSISTENT,
    )
