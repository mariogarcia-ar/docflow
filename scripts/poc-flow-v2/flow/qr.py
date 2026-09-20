"""QR extraction: a deterministic source embedded in the document.

`my_flow.md` §4.2: an electronic receipt carries an ARCA QR whose payload names
the fiscal fields. Decoding is exact and needs no model, so the QR is a
**deterministic extraction**, not the truth of the receipt — its agreement with
the printed value scores `DETERMINISTIC`, and a disagreement is a **conflict**
(`conflicto_qr`), never a score.

The decode uses OpenCV's `QRCodeDetector`, which is available in the runtime and
imports nothing else. The payload may be the ARCA URL form (`/qr/?p=` with a
base64 body) or a plain JSON object; both are accepted, because a fixture is a
generated JSON and a real receipt is the URL form.
"""

from __future__ import annotations

import base64
import json
import re
from collections.abc import Mapping
from typing import Final

# Pylint cannot see inside OpenCV: it is a compiled extension whose attributes
# are not introspectable, so `cv2.imdecode`, `cv2.QRCodeDetector` and friends
# are reported as missing members while being real and documented. The
# suppression is stated once here rather than at each call site.
# pylint: disable=no-member
import cv2
import numpy as np

from .fields import PASS, EvidenceSignal, FieldCandidate, normalize

__all__: list[str] = [
    "qr_candidates",
    "qr_conflict",
    "qr_deterministic",
]

#: The ARCA QR URL marker: everything after `p=` is a base64-encoded JSON body.
_QR_URL_RE: Final = re.compile(r"[?&]p=([A-Za-z0-9+/=_-]+)")


def _decode_payload(data: str) -> dict[str, object]:
    """Turn the QR's raw text into a field mapping, ARCA URL or plain JSON."""
    match = _QR_URL_RE.search(data)
    if match:
        try:
            raw = base64.b64decode(match.group(1)).decode("utf-8")
            data = raw
        except (ValueError, UnicodeDecodeError):
            pass
    parsed = json.loads(data)
    if not isinstance(parsed, dict):
        return {}
    return parsed


def _decode_qr(image: bytes) -> str | None:
    """The QR payload text, or ``None`` when no QR is present or decodable."""
    buffer = np.frombuffer(image, dtype=np.uint8)
    frame = cv2.imdecode(buffer, cv2.IMREAD_GRAYSCALE)
    if frame is None:
        return None
    value, points, _ = cv2.QRCodeDetector().detectAndDecode(frame)
    del points
    return value if value else None


#: How the ARCA payload's fields map onto the schema's field names. The names
#: differ on purpose — the QR speaks ARCA, the schema speaks the flow.
_QR_FIELD_MAP: Final[dict[str, str]] = {
    "fecha": "fecha_emision",
    "cuit": "cuit_emisor",
    "importe": "importe_total_facturado",
    "moneda": "moneda",
    "nroCmp": "nro_comprobante",
    "tipoCmp": "tipo_comprobante",
    "puntoVenta": "punto_venta",
}


def qr_candidates(image: bytes) -> dict[str, list[FieldCandidate]]:
    """Decode the QR and return one deterministic candidate per fiscal field.

    Args:
        image: The rendered page bytes, or any image holding the QR.

    Returns:
        Field name to a single candidate from the QR. An empty mapping when the
        image holds no QR or the payload is unreadable — an absent QR is not an
        error, it is *no deterministic source* (`my_flow.md` I10).

    """
    data = _decode_qr(image)
    if data is None:
        return {}
    payload = _decode_payload(data)
    candidates: dict[str, list[FieldCandidate]] = {}
    for qr_field, flow_field in _QR_FIELD_MAP.items():
        value = payload.get(qr_field)
        if value is None:
            continue
        raw = str(value)
        if qr_field == "importe" and raw.replace(".", "", 1).isdigit():
            raw = _format_importe(raw)
        elif qr_field == "cuit":
            raw = _format_cuit(raw)
        candidates[flow_field] = [
            FieldCandidate(
                normalized_value=normalize(raw),
                raw_value=raw,
                producers=["qr"],
                signals=[],
                hard_refutations=[],
            )
        ]
    return candidates


def _format_importe(raw: str) -> str:
    """Print an amount the way the schema keeps it, without dropping the cents.

    The ARCA payload carries the importe as a number, and ``17898.3`` is
    ``17898.30`` — the trailing zero is data, not formatting (`my_flow.md` §5:
    an amount is returned as printed). Two decimals are the receipt's unit.
    """
    try:
        value = float(raw)
    except ValueError:
        return raw
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _format_cuit(raw: str) -> str:
    """Print a CUIT the schema's way: ``20-12345678-3`` from 11 digits.

    The ARCA payload carries the CUIT as its 11 digits; the schema keeps the
    hyphens. An unparseable value is returned unchanged — formatting must not
    invent separators a number did not have.
    """
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) != 11:
        return raw
    return f"{digits[:2]}-{digits[2:10]}-{digits[10]}"


def qr_deterministic(
    printed: str, qr_value: str, family_points: Mapping[str, int]
) -> EvidenceSignal:
    """The DETERMINISTIC signal for a QR that agrees with the printed value.

    A disagreement is **not** this function's answer — it is a conflict handled
    by :func:`qr_conflict`. Here the QR only ever agrees (PASS) or cannot be
    compared (UNKNOWN).
    """
    points = family_points["DETERMINISTIC"]
    if not printed or not qr_value:
        return EvidenceSignal(
            "DETERMINISTIC", "UNKNOWN", points, "QR and print cannot be compared"
        )
    if normalize(printed) == normalize(qr_value):
        return EvidenceSignal(
            "DETERMINISTIC", PASS, points, "QR matches the printed value"
        )
    return EvidenceSignal(
        "DETERMINISTIC", "UNKNOWN", points, "QR does not match the printed value"
    )


def qr_conflict(printed: str, qr_value: str) -> bool:
    """Whether the QR and the printed value disagree on the same field.

    A conflict is a flag (`conflicto_qr`, §4.2), never a score: it forces
    REVIEW or escalation rather than being resolved by points.
    """
    if not printed or not qr_value:
        return False
    return normalize(printed) != normalize(qr_value)
