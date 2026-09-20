"""Extraction: the candidate producers behind the engine.

`my_flow.md` §4, run over the adapters. The split of roles:

- **regexp** produces candidates for fixed-format fields (CUIT, date); it never
  decides (§6.1).
- **Lane A, text** extracts from scratch with the local model, reading the
  registry prompt and schema (`docflow.kernels.registry`).
- **Lane B** (review) and the **vision lane** are deferred (`# TODO: [MVP]`):
  the registry holds one extraction prompt and one schema, not the role/lane
  split §4.1 names, and the review prompts do not exist there yet. A deferred
  lane is reported as a note, never faked.

The output is per-field :class:`FieldCandidate` lists with their signals. The
engine merges and scores; this module only *produces*.
"""

from __future__ import annotations

# `wrong-import-order` / `wrong-import-position`: the `docflow` adapters are
# only importable once `_bootstrap` puts `src/` on `sys.path`, so the adapter
# imports must follow `ensure_docflow_importable()`. The order is load-bearing,
# not cosmetic — the same rule `scripts/poc/` documents for its drivers.
# pylint: disable=wrong-import-order, wrong-import-position
import re
from collections.abc import Mapping
from typing import Final

from ._bootstrap import ensure_docflow_importable

ensure_docflow_importable()

from docflow.adapters.ollama import OllamaEngine  # noqa: E402

from .artifacts import Artifacts  # noqa: E402
from .config import Config  # noqa: E402
from .fields import (  # noqa: E402
    IVA_FIELD,
    PASS,
    SUBTOTAL_FIELD,
    TOTAL_FIELD,
    UNKNOWN,
    EvidenceSignal,
    Extraction,
    FieldCandidate,
    normalize,
)
from .material import Material  # noqa: E402

__all__: list[str] = ["extract"]

#: Where the document's text is substituted into the prompt.
TEXT_PLACEHOLDER: Final[str] = "{text}"

#: Fields that are **derived** rather than printed: a boolean or a classification
#: has no physical anchor in the document, so it never earns ``DOCUMENT_CONTENT``.
_DERIVED_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "comprobante_valido",
        "motivo_rechazo",
        "condicion_impositiva_dominante",
        "categoria_gasto",
        "centro_de_costo",
    }
)

#: The fixed-format patterns regexp produces candidates for. A regexp candidate
#: is a candidate, never a decision (§6.1).
_CUIT_RE: Final = re.compile(r"\b\d{2}-\d{8}-\d\b")
_ISO_DATE_RE: Final = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_PRINTED_DATE_RE: Final = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")


def _candidate(
    raw: str,
    producer: str,
    signals: list[EvidenceSignal] | None = None,
) -> FieldCandidate:
    return FieldCandidate(
        normalized_value=normalize(raw),
        raw_value=raw,
        producers=[producer],
        signals=list(signals) if signals else [],
        hard_refutations=[],
    )


def _present_in_text(raw: str, text: str) -> bool:
    """Whether a value is mechanically present in the document text.

    The stand-in for the full `verified` anchor of §4.2: the value's digits
    (ignoring separators) appear in the text's digits. §6.5 says exactly what
    this proves — traceability, not correctness.  # TODO: [MVP]
    """
    needle = normalize(raw)
    haystack = normalize(text)
    return bool(needle) and needle in haystack


def _content_signal(raw: str, text: str, points: int) -> EvidenceSignal:
    """The DOCUMENT_CONTENT signal: PASS when the anchor is verified, UNKNOWN
    otherwise (`my_flow.md` §6.2: an unverified bbox does not score)."""
    verified = _present_in_text(raw, text)
    return EvidenceSignal(
        "DOCUMENT_CONTENT",
        PASS if verified else UNKNOWN,
        points,
        "value present in the text" if verified else "no verified anchor",
        verified=verified,
    )


def _fields_to_candidates(
    fields: Mapping[str, object],
    producer: str,
    text: str,
    config: Config,
) -> dict[str, list[FieldCandidate]]:
    """Turn a model's field mapping into one candidate per non-empty field.

    A field with **no value** is skipped, whatever spelling the model used: the
    JSON ``null``, an empty string, or the string ``"null"``. A declared absence
    must not become a candidate, because it would score as if the model had
    found a value.
    """
    points = config.family_points["DOCUMENT_CONTENT"]
    candidates: dict[str, list[FieldCandidate]] = {}
    for field, value in fields.items():
        if value is None:
            continue
        raw = str(value).strip()
        if not raw or raw.lower() == "null":
            continue
        if field in _DERIVED_FIELDS:
            candidates[field] = [_candidate(raw, producer)]
            continue
        candidates[field] = [
            _candidate(raw, producer, [_content_signal(raw, text, points)])
        ]
    return candidates


def _regexp_candidates(text: str) -> dict[str, list[FieldCandidate]]:
    """The fixed-format candidates regexp produces, from the document text."""
    candidates: dict[str, list[FieldCandidate]] = {}
    cuit = _CUIT_RE.search(text)
    if cuit:
        candidates["cuit_emisor"] = [_candidate(cuit.group(0), "regexp")]
    date_match = _ISO_DATE_RE.search(text) or _PRINTED_DATE_RE.search(text)
    if date_match:
        raw = date_match.group(0)
        if "/" in raw:
            day, month, year = raw.split("/")
            raw = f"{year}-{int(month):02d}-{int(day):02d}"
        candidates["fecha_emision"] = [_candidate(raw, "regexp")]
    return candidates


def extract(  # pylint: disable=too-many-locals
    material: Material,
    config: Config,
    artifacts: Artifacts,
) -> Extraction:
    """Produce candidates from a document's material, over the text lane.

    The lane order is the argument: regexp, then lane A. The review lane and the
    vision lane are deferred — the registry does not yet hold their prompts —
    and that absence is a note, not a fake answer.

    Args:
        material: The document's text, tier and rendered pages.
        config: The run's dials.
        artifacts: The loaded registry prompt and schema.

    Returns:
        The candidates and document values, with any refusals noted.
    """
    notes: list[str] = []
    engine = OllamaEngine()

    candidates: dict[str, list[FieldCandidate]] = {}
    values: dict[str, str] = {}

    text = material.text or ""

    # --- regexp: fixed-format candidates, never decisions -----------------
    for field, produced in _regexp_candidates(text).items():
        candidates.setdefault(field, []).extend(produced)

    # --- Lane A, text -----------------------------------------------------
    if text:
        prompt = artifacts.prompt.replace(TEXT_PLACEHOLDER, text)
        answered = engine.structured(
            config.text_model_a, prompt, artifacts.extraction_schema
        )
        if answered.value is None:
            notes.append("text lane A refused; no text candidates")
        else:
            fields = dict(answered.value)
            produced = _fields_to_candidates(
                fields, "extractor_llm_texto", text, config
            )
            for field, field_candidates in produced.items():
                candidates.setdefault(field, []).extend(field_candidates)
            for field in (SUBTOTAL_FIELD, IVA_FIELD, TOTAL_FIELD):
                if field in fields and fields[field] is not None:
                    values[field] = str(fields[field])

    # The review and vision lanes are deferred: the registry holds one
    # extraction prompt, not the role/lane split §4.1 names.
    notes.append("review lane and vision lane deferred: no registry prompts")

    return Extraction(candidates=candidates, values=values, notes=notes)
