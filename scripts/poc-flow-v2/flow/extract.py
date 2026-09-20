"""Extraction: the candidate producers behind the engine.

`my_flow.md` §4, run over the adapters. The split of roles:

- **regexp** produces candidates for fixed-format fields (CUIT, date); it never
  decides (§6.1).
- **Lane A, text** extracts from scratch with the local model (`extract_texto`).
- **Lane B, text** reviews adversarially, reading the source text plus A's
  extraction, asked to *find errors*, not to confirm (§4.1, I5).
- **Lane A, vision** extracts from the rendered pages (`extract_vision`); its
  producer is `vision`, the only source the cross-modal signal can come from.
- **Lane B, vision** reviews the pixels adversarially (I5).

`CROSS_MODAL` (+2) is earned when the text lane and the vision lane agree on the
same normalized value; `SAME_MATERIAL` (+1) when the reviewer agrees. Both are
capped per family by the engine (I4). A lane that cannot run — no text, no
images, no model — is a note, never a fake answer.
"""

from __future__ import annotations

# `wrong-import-order` / `wrong-import-position`: the `docflow` adapters are
# only importable once `_bootstrap` puts `src/` on `sys.path`, so the adapter
# imports must follow `ensure_docflow_importable()`. The order is load-bearing,
# not cosmetic — the same rule `scripts/poc/` documents for its drivers.
# pylint: disable=wrong-import-order, wrong-import-position
import json
import re
from collections.abc import Mapping
from typing import Final

from ._bootstrap import ensure_docflow_importable

ensure_docflow_importable()

from docflow.adapters.ollama import OllamaEngine  # noqa: E402
from docflow.kernels.types import Bytes  # noqa: E402

from .artifacts import Artifacts  # noqa: E402
from .config import Config  # noqa: E402
from .fields import (  # noqa: E402
    FAIL,
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

#: Where the document's text is substituted into the prompts.
TEXT_PLACEHOLDER: Final[str] = "{text}"

#: Where A's extraction is substituted into the review prompts. The reviewer
#: must receive the proposal to review (I5): a review prompt that names a
#: proposal but carries no placeholder is asking a model to grade something it
#: was never shown.
PROPOSAL_PLACEHOLDER: Final[str] = "{proposal}"

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

#: The reviewer verdicts, as the review schema's enum.
_AGREE: Final[str] = "agree"
_DISAGREE: Final[str] = "disagree"


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


def _present_at_location(raw: str, text: str) -> bool:
    """Whether the value is present at its declared location in the text.

    C4's mechanical check, in the form the text lane can supply today: the value
    (normalized) appears in the text (normalized). The full bbox re-read is the
    OCR-lane form (`# TODO: [MVP]`).
    """
    return _present_in_text(raw, text)


def _content_signal(raw: str, text: str | None, points: int) -> EvidenceSignal:
    """The DOCUMENT_CONTENT signal: PASS when the anchor is verified, UNKNOWN
    otherwise (`my_flow.md` §6.2: an unverified bbox does not score)."""
    verified = text is not None and _present_in_text(raw, text)
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
    text: str | None,
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
        signals = [_content_signal(raw, text, points)] if text is not None else []
        candidates[field] = [_candidate(raw, producer, signals)]
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


def _call_structured(
    engine: OllamaEngine, model: str, prompt: str, schema: Mapping[str, object]
) -> Mapping[str, object] | None:
    """One structured call; ``None`` on refusal, never an exception."""
    result = engine.structured(model, prompt, schema)
    if result.value is None:
        return None
    return dict(result.value)


def _call_vision(
    engine: OllamaEngine,
    model: str,
    prompt: str,
    images: list[Bytes],
    schema: Mapping[str, object],
) -> Mapping[str, object] | None:
    """One vision call; ``None`` on refusal or when there are no images."""
    if not images:
        return None
    result = engine.vision(model, prompt, images, schema)
    if result.value is None:
        return None
    return dict(result.value)


def _review_verdicts(
    engine: OllamaEngine,
    model: str,
    prompt: str,
    schema: Mapping[str, object],
    *,
    images: list[Bytes] | None = None,
) -> list[Mapping[str, object]]:
    """Run one review call and return its per-field verdicts, or an empty list.

    Args:
        images: When given, the call is `vision` so the reviewer sees the page
            (I5); when ``None``, it is `structured` and grades the transcript.
            The text reviewer reads text, the vision reviewer reads pixels.

    """
    if images is not None:
        answered = _call_vision(engine, model, prompt, images, schema)
    else:
        answered = _call_structured(engine, model, prompt, schema)
    if answered is None:
        return []
    verdicts = answered.get("field_verdicts")
    if not isinstance(verdicts, list):
        return []
    return [v for v in verdicts if isinstance(v, Mapping)]


def _apply_review(
    candidates: dict[str, list[FieldCandidate]],
    verdicts: list[Mapping[str, object]],
    config: Config,
) -> None:
    """Fold a reviewer's verdicts into the candidates it reviewed.

    The family points come from the run's config, never from a literal here: a
    second copy of a scoring weight is how two callers come to disagree while
    both report success.

    - ``agree`` → SAME_MATERIAL +1 on A's candidate;
    - ``disagree`` → soft refutation -2 on A's candidate, and a **new**
      candidate from ``suggested_value`` that starts from zero (`my_flow.md`
      §6.2);
    - ``uncertain`` → neutral.
    """
    same_material = config.family_points["SAME_MATERIAL"]
    soft = config.family_points["SOFT_REFUTATION"]
    for verdict in verdicts:
        field = str(verdict.get("field", ""))
        state = verdict.get("verdict")
        if field not in candidates:
            continue
        produced = candidates[field]
        if not produced:
            continue
        if state == _AGREE:
            produced[0].signals.append(
                EvidenceSignal(
                    "SAME_MATERIAL", PASS, same_material, "B agree", verified=False
                )
            )
        elif state == _DISAGREE:
            produced[0].signals.append(
                EvidenceSignal(
                    "SOFT_REFUTATION", FAIL, soft, "B disagree", verified=False
                )
            )
            suggested = verdict.get("suggested_value")
            if suggested is not None and str(suggested).strip():
                produced.append(_candidate(str(suggested), "reviewer_suggested", []))


def _cross_modal(candidates: dict[str, list[FieldCandidate]], config: Config) -> None:
    """Add CROSS_MODAL where the text lane and the vision lane agree.

    The signal is earned when a field has at least one text-lane producer and
    one vision-lane producer on the **same** normalized value. It is attached to
    that merged value's candidates; the engine's family cap keeps it to one.
    """
    points = config.family_points["CROSS_MODAL"]
    for _field, produced in candidates.items():
        text_values = {
            c.normalized_value
            for c in produced
            if any(p.startswith("extractor_llm") for p in c.producers)
        }
        vision_values = {
            c.normalized_value
            for c in produced
            if any(p == "vision" for p in c.producers)
        }
        agreed = text_values & vision_values
        for candidate in produced:
            if candidate.normalized_value in agreed:
                candidate.signals.append(
                    EvidenceSignal(
                        "CROSS_MODAL",
                        PASS,
                        points,
                        "text and vision lanes agree",
                    )
                )


def extract(  # pylint: disable=too-many-locals, too-many-branches
    material: Material,
    config: Config,
    artifacts: Artifacts,
) -> Extraction:
    """Run the four lanes over a document's material and collect candidates.

    The lane order is the argument: regexp, then text A, text B (review), vision
    A, vision B (review), then cross-modal — each step's inputs are the outputs
    of the one before.

    Args:
        material: The document's text, tier and rendered pages.
        config: The run's dials.
        artifacts: The loaded lane prompts and schemas.

    Returns:
        The candidates and document values, with any refusals noted.
    """
    notes: list[str] = []
    engine = OllamaEngine()

    extract_text_prompt = artifacts.prompts.get("extract_texto", "")
    extract_vision_prompt = artifacts.prompts.get("extract_vision", "")
    review_text_prompt = artifacts.prompts.get("review_texto", "")
    review_vision_prompt = artifacts.prompts.get("review_vision", "")

    extraction_schema = artifacts.extraction_schema
    review_schema = artifacts.review_schema

    candidates: dict[str, list[FieldCandidate]] = {}
    values: dict[str, str] = {}

    text = material.text or ""

    # --- regexp: fixed-format candidates, never decisions -----------------
    for field, produced in _regexp_candidates(text).items():
        candidates.setdefault(field, []).extend(produced)

    # --- Lane A, text -----------------------------------------------------
    text_fields: dict[str, list[FieldCandidate]] = {}
    if text:
        prompt = extract_text_prompt.replace(TEXT_PLACEHOLDER, text)
        answered = _call_structured(
            engine, config.text_model_a, prompt, extraction_schema
        )
        if answered is None:
            notes.append("text lane A refused; no text candidates")
        else:
            text_fields = _fields_to_candidates(
                answered, "extractor_llm_texto", text, config
            )
            for field, produced in text_fields.items():
                candidates.setdefault(field, []).extend(produced)
            for field in (SUBTOTAL_FIELD, IVA_FIELD, TOTAL_FIELD):
                if field in answered and answered[field] is not None:
                    values[field] = str(answered[field])

    # --- Lane B, text (reviewer) -----------------------------------------
    if text and text_fields:
        proposal = json.dumps(
            {field: produced[0].raw_value for field, produced in text_fields.items()},
            ensure_ascii=False,
        )
        review_prompt = review_text_prompt.replace(TEXT_PLACEHOLDER, text).replace(
            PROPOSAL_PLACEHOLDER, proposal
        )
        verdicts = _review_verdicts(
            engine, config.text_model_b, review_prompt, review_schema
        )
        _apply_review(candidates, verdicts, config)
        if not verdicts:
            notes.append("text lane B produced no review verdicts")

    # --- Lane A, vision ---------------------------------------------------
    vision_fields: dict[str, list[FieldCandidate]] = {}
    if config.vision_model_a and material.images:
        answered = _call_vision(
            engine,
            config.vision_model_a,
            extract_vision_prompt,
            material.images,
            extraction_schema,
        )
        if answered is None:
            notes.append("vision lane A refused; no vision candidates")
        else:
            vision_fields = _fields_to_candidates(answered, "vision", None, config)
            for field, produced in vision_fields.items():
                candidates.setdefault(field, []).extend(produced)

    # --- Lane B, vision (reviewer) ---------------------------------------
    if config.vision_model_b and material.images and vision_fields:
        proposal = json.dumps(
            {field: produced[0].raw_value for field, produced in vision_fields.items()},
            ensure_ascii=False,
        )
        review_prompt = review_vision_prompt.replace(PROPOSAL_PLACEHOLDER, proposal)
        verdicts = _review_verdicts(
            engine,
            config.vision_model_b,
            review_prompt,
            review_schema,
            images=material.images,
        )
        _apply_review(candidates, verdicts, config)

    # --- Cross-modal agreement -------------------------------------------
    _cross_modal(candidates, config)

    return Extraction(candidates=candidates, values=values, notes=notes)
