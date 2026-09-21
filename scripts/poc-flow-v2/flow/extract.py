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

from .amounts import read_amount_columns  # noqa: E402
from .artifacts import RESERVED_EXTRACTION_STEPS, Artifacts  # noqa: E402
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
from .sampling import apply_sampling  # noqa: E402

__all__: list[str] = ["extract"]

#: Where the document's text is substituted into the prompts.
TEXT_PLACEHOLDER: Final[str] = "{text}"

#: Where the classification step's rubro is substituted into the line-of-business
#: prompt. The caller decides whether to run that step at all, so the prompt never
#: has to ask *does this apply*.
RUBRO_PLACEHOLDER: Final[str] = "{rubro}"

#: The field the classification step settles and the line-of-business step depends
#: on. Named once because two steps name it: one produces it, the other is gated by
#: its value.
CATEGORY_FIELD: Final[str] = "categoria_gasto"

#: The rubros whose receipt has a line-of-business question to answer. A restaurant
#: receipt may print diners, a fuel one exact litres; nothing else does.
RUBRO_CATEGORIES: Final[frozenset[str]] = frozenset({"Restaurante", "Combustible"})

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
    """Whether the value is present as a **whole** token at its location.

    C4's mechanical check. The stand-in's defect is a substring false positive:
    `"17.898,30"` matches inside `"117.898,301"` and reads as verified while
    being the tail of a different number. A numeric value is verified only when
    it appears with **digit boundaries** on both sides — a complete number, not
    a slice of a longer one. Free-text values (razón social, description) have
    no digit to guard, so a plain occurrence is the check that applies.

    The full bbox re-read (`location` + `content`, §4.2) is the OCR-lane form
    and stays `# TODO: [MVP]`: the extractor does not declare a box today.
    """
    value = normalize(raw)
    if not value:
        return False
    haystack = normalize(text)
    if not value.isdigit():
        return value in haystack
    index = haystack.find(value)
    while index != -1:
        before = haystack[index - 1] if index > 0 else ""
        after = (
            haystack[index + len(value)] if index + len(value) < len(haystack) else ""
        )
        if not before.isdigit() and not after.isdigit():
            return True
        index = haystack.find(value, index + 1)
    return False


def _content_signal(raw: str, text: str | None, points: int) -> EvidenceSignal:
    """The DOCUMENT_CONTENT signal: PASS when the anchor is verified, UNKNOWN
    otherwise (`my_flow.md` §6.2: an unverified bbox does not score)."""
    verified = text is not None and _present_at_location(raw, text)
    return EvidenceSignal(
        "DOCUMENT_CONTENT",
        PASS if verified else UNKNOWN,
        points,
        "value present in the text" if verified else "no verified anchor",
        verified=verified,
    )


def _declared_absent(value: object) -> bool:
    """Whether a producer declared *no value* for a field.

    Three spellings mean the same thing and none of them is a value: JSON
    ``null``, an empty string, and the **string** ``"null"``. Measured:
    `deepseek-r1:1.5b` answers the string ``"null"`` — not the JSON token — for
    every amount it cannot read.

    One owner, used by the candidate builder **and** the document values. Two
    callers each spelling *absent* for themselves is exactly how a declared
    absence became an arithmetic component here: `_fields_to_candidates`
    filtered it and the values loop did not, so ``values`` carried
    ``'subtotal': 'null'`` and `_values_for` handed it to the rule as a
    component (`my_flow.md` §6.4: a component the rule cannot read makes the
    equation UNKNOWN, never a failed combination).
    """
    if value is None:
        return True
    text = str(value).strip()
    return not text or text.lower() == "null"


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
        if _declared_absent(value):
            continue
        raw = str(value).strip()
        if field in _DERIVED_FIELDS:
            candidates[field] = [_candidate(raw, producer)]
            continue
        signals = [_content_signal(raw, text, points)] if text is not None else []
        candidates[field] = [_candidate(raw, producer, signals)]
    return candidates


def _regexp_candidates(text: str, config: Config) -> dict[str, list[FieldCandidate]]:
    """The fixed-format candidates regexp produces, from the document text.

    Three fields, all of them **format** rather than comprehension: the CUIT,
    the date, and the labeled amount row. The amounts were added after a
    measurement: the `desglose` step returned invented figures on five runs out
    of five on a perfectly legible row (`amounts.py` states the measurement), and
    a totals row is two lines of fixed columns — the case §4.2 assigns to
    `regexp`, which *produces candidates and never decides*.

    Every candidate carries its :func:`_content_signal` anchor, and for this
    producer the anchor is **stronger** than for a model's answer: the raw value
    is a slice of `text` itself, so "is it present where it claims to be" is not
    an inference. A producer that returned a value without saying it was in the
    document is the one thing §5's `producers` list are all shown with —
    measured, leaving it off cost the critical amount its `DOCUMENT_CONTENT +2`,
    and with it its only route to `CONFIRMED`.
    """
    points = config.family_points["DOCUMENT_CONTENT"]
    candidates: dict[str, list[FieldCandidate]] = {}
    cuit = _CUIT_RE.search(text)
    if cuit:
        candidates["cuit_emisor"] = [_regexp_candidate(cuit.group(0), text, points)]
    printed_date = _PRINTED_DATE_RE.search(text)
    iso_date = _ISO_DATE_RE.search(text)
    if iso_date:
        candidates["fecha_emision"] = [
            _regexp_candidate(iso_date.group(0), text, points)
        ]
    elif printed_date:
        # Normalised to ISO for the report, anchored on the form the document
        # actually prints: the derived string is not a substring of the page, so
        # anchoring it would report `no verified anchor` for a date that is
        # plainly there.
        day, month, year = printed_date.groups()
        candidates["fecha_emision"] = [
            _regexp_candidate(
                f"{year}-{int(month):02d}-{int(day):02d}",
                text,
                points,
                anchor=printed_date.group(0),
            )
        ]
    for field, printed in read_amount_columns(text).items():
        candidates[field] = [_regexp_candidate(printed, text, points)]
    return candidates


def _regexp_candidate(
    raw: str, text: str, points: int, *, anchor: str | None = None
) -> FieldCandidate:
    """One `regexp` candidate carrying the anchor its own value earns.

    The anchor is verified against the string as **found** in the document, which
    is `raw` unless the caller derived it (`anchor`).
    """
    printed = anchor if anchor is not None else raw
    return _candidate(raw, "regexp", [_content_signal(printed, text, points)])


def _call_structured(
    engine: OllamaEngine, model: str, prompt: str, schema: Mapping[str, object]
) -> tuple[Mapping[str, object] | None, str]:
    """One structured call.

    Returns:
        The parsed answer (or ``None``) and the refusal's reason code: ``""``
        when the call succeeded, otherwise the adapter's own code. The code is
        returned rather than logged because the caller is the only place that can
        say which lane it belonged to — and a lane that did not run must say
        **why** (`my_flow.md` B.9): a bare "no verdicts" reads the same whether the
        model is missing, the runtime is down, or the reviewer simply agreed with
        nothing to add.

    """
    result = engine.structured(model, prompt, schema)
    if result.value is None:
        return None, (result.reason.code if result.reason else "no_reason")
    return dict(result.value), ""


def _call_vision(
    engine: OllamaEngine,
    model: str,
    prompt: str,
    images: list[Bytes],
    schema: Mapping[str, object],
) -> tuple[Mapping[str, object] | None, str]:
    """One vision call; ``(None, code)`` on refusal, or when there are no images."""
    if not images:
        return None, "no images to read"
    result = engine.vision(model, prompt, images, schema)
    if result.value is None:
        return None, (result.reason.code if result.reason else "no_reason")
    return dict(result.value), ""


def _review_verdicts(
    engine: OllamaEngine,
    model: str,
    prompt: str,
    schema: Mapping[str, object],
    *,
    images: list[Bytes] | None = None,
) -> tuple[list[Mapping[str, object]], str]:
    """Run one review call and return its verdicts and the refusal code.

    Args:
        images: When given, the call is `vision` so the reviewer sees the page
            (I5); when ``None``, it is `structured` and grades the transcript.
            The text reviewer reads text, the vision reviewer reads pixels.

    Returns:
        The per-field verdicts (possibly empty) and the refusal code, which is
        ``""`` only when the model actually answered. A model that answered with
        an empty verdict list is **not** a refusal and returns ``""`` — the two
        are different facts and the caller reports them differently.

    """
    if images is not None:
        answered, code = _call_vision(engine, model, prompt, images, schema)
    else:
        answered, code = _call_structured(engine, model, prompt, schema)
    if answered is None:
        return [], code
    verdicts = answered.get("field_verdicts")
    if not isinstance(verdicts, list):
        return [], "the reviewer answered without a field_verdicts list"
    return [v for v in verdicts if isinstance(v, Mapping)], ""


def _apply_review(
    candidates: dict[str, list[FieldCandidate]],
    verdicts: list[Mapping[str, object]],
    config: Config,
) -> int:
    """Fold a reviewer's verdicts into the candidates it reviewed.

    The family points come from the run's config, never from a literal here: a
    second copy of a scoring weight is how two callers come to disagree while
    both report success.

    - ``agree`` → SAME_MATERIAL +1 on A's candidate;
    - ``disagree`` → soft refutation -2 on A's candidate, and a **new**
      candidate from ``suggested_value`` that starts from zero (`my_flow.md`
      §6.2);
    - ``uncertain`` → neutral.

    Returns:
        How many verdicts named a field this document produced **no candidate
        for**. A verdict whose ``field`` is a value rather than a field name
        (measured: ``gemma3:1b`` answers ``{"field": "agree", "verdict":
        "agree"}``) can never be applied, and silently dropping it makes a
        reviewer that answered nothing look like a reviewer with nothing to say
        (`my_flow.md` B.9).

    """
    same_material = config.family_points["SAME_MATERIAL"]
    soft = config.family_points["SOFT_REFUTATION"]
    unmatched = 0
    for verdict in verdicts:
        field = str(verdict.get("field", ""))
        state = verdict.get("verdict")
        if field not in candidates:
            unmatched += 1
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
    return unmatched


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


def document_values(answered: Mapping[str, object]) -> dict[str, str]:
    """The document-level amounts the arithmetic rule needs (§6.4).

    A named function rather than an inline loop for the reason the defect
    existed: the rule was written inline at the call site, so a test could only
    restate it — and a test that restates the implementation passes whether or
    not the implementation is right. Here the rule has one address.

    A declared absence is **not** a component. Measured: `deepseek-r1:1.5b`
    answers the string ``"null"`` for the amounts it cannot read, and
    ``values`` carried it straight into the arithmetic as a component.

    Args:
        answered: The lane's field mapping, as the model returned it.

    Returns:
        Only the components that carry a value. A field the model declared
        absent is left out, so `_values_for` never offers it as a combination
        term — which is what makes an unreadable component *absent* rather than
        *inconsistent* (I10).

    """
    return {
        field: str(answered[field])
        for field in (SUBTOTAL_FIELD, IVA_FIELD, TOTAL_FIELD)
        if field in answered and not _declared_absent(answered[field])
    }


def _reviewer_note(
    lane: str, model: str, verdicts: int, refusal: str, unmatched: int
) -> str:
    """What to say about a reviewer lane, or ``""`` when it did its job.

    The three outcomes are different facts and must not collapse into one string
    (`my_flow.md` B.9): a reviewer that **could not be asked** (a refusal names
    the adapter's own code), one that answered something unusable (a verdict
    naming no reviewed field), and one that answered with **no verdicts at all**.
    A missing reviewer and an agreeing one read the same otherwise, and the absent
    `SAME_MATERIAL` signal becomes unattributable.

    Args:
        lane: Which lane, for the message: ``"text"`` or ``"vision"``.
        model: The model the lane was configured with.
        verdicts: How many usable verdicts came back.
        refusal: The adapter's reason code, ``""`` when the call succeeded.
        unmatched: Verdicts naming a field this document produced no candidate for.

    Returns:
        The note, or ``""`` when the reviewer answered usefully.

    """
    if refusal:
        return f"{lane} lane B ({model}) refused: {refusal}; no SAME_MATERIAL signal"
    if unmatched:
        return (
            f"{lane} lane B ({model}) answered {unmatched} verdict(s) naming no "
            "reviewed field; discarded"
        )
    if not verdicts:
        return f"{lane} lane B ({model}) answered with no field verdicts"
    return ""


# `too-few-public-methods`: `_Collected` is a record the lanes extend together —
# its fields are the contract, not its methods. The same reasoning `fields.py` and
# `material.py` state for their boundary records.
# pylint: disable=too-few-public-methods


class _Collected:
    """What every lane and step accumulates, bundled so it can be passed once.

    A record rather than three parallel arguments: the three are extended together
    by every producer, and passing them separately pushed the runner past pylint's
    argument budget for no gain in clarity.

    Attributes:
        candidates: Field name to the candidates produced so far.
        values: The document-level amounts the arithmetic rule reads.
        notes: Human-readable notes about what refused or was skipped.

    """

    def __init__(
        self,
        candidates: dict[str, list[FieldCandidate]],
        values: dict[str, str],
        notes: list[str],
    ) -> None:
        self.candidates = candidates
        self.values = values
        self.notes = notes


def _run_reserved_steps(
    engine: OllamaEngine,
    material: Material,
    config: Config,
    artifacts: Artifacts,
    collected: _Collected,
) -> None:
    """Run the reserved extraction steps over the same material, in order.

    The layered split (`cierre-circuitos.md` §«Enfoque en capas») answers the same
    document four times, once per domain of knowledge — reading, tax mechanics,
    line-of-business detail, judgement — instead of asking one prompt for all 23
    fields. Each step gets its **own prompt and its own schema**, so the grammar
    constrains only that step's keys.

    Two orderings are load-bearing:

    - **`clasificacion` before `rubro`**, because `categoria_gasto` decides whether
      the line-of-business step runs at all. `rubro` asks about litres or diners;
      asking that of every receipt is what made a model answer with nothing. The
      order is declared in `RESERVED_EXTRACTION_STEPS` and guarded by
      `test_the_step_order_satisfies_the_dependency_between_steps`.
    - **`desglose` runs always**, so its `subtotal`/`iva`/`importe_total_facturado`
      reach `values` together — the combination §6.4 validates is a unit, and the
      step that holds it is the step that can settle it.

    A step that refuses is a **note**, never a silent gap: the fields it would have
    contributed are simply absent, which is a fact the decision layer already
    handles (`unknown scores nothing`).

    Args:
        engine: The local engine.
        material: The document's text and pages.
        config: The run's dials.
        artifacts: The loaded artifacts, including the reserved steps.
        collected: The candidates, values and notes to extend, in place.

    """
    text = material.text or ""
    for step in RESERVED_EXTRACTION_STEPS:
        if step == "rubro" and not _rubro_applies(collected.candidates):
            continue
        try:
            prompt_template, schema = artifacts.reserved_extraction_step(step)
        except KeyError as exc:
            collected.notes.append(f"{step} step unavailable: {exc}")
            continue

        answered, refusal = _call_structured(
            engine,
            config.text_model_a,
            _step_prompt(step, prompt_template, text, collected.candidates),
            schema,
        )
        if answered is None:
            collected.notes.append(f"{step} step refused ({refusal}); fields absent")
            continue

        for field, field_candidates in _fields_to_candidates(
            answered, f"extractor_{step}", text, config
        ).items():
            collected.candidates.setdefault(field, []).extend(field_candidates)
        collected.values.update(document_values(answered))


def _step_prompt(
    step: str,
    template: str,
    text: str,
    candidates: dict[str, list[FieldCandidate]],
) -> str:
    """A reserved step's prompt with its placeholders substituted.

    Two substitutions, and only the line-of-business step needs the second: it is
    the one whose question depends on what the classification step settled.
    """
    prompt = template.replace(TEXT_PLACEHOLDER, text)
    if step == "rubro":
        prompt = prompt.replace(RUBRO_PLACEHOLDER, _rubro_value(candidates))
    return prompt


def _rubro_value(candidates: dict[str, list[FieldCandidate]]) -> str:
    """The `categoria_gasto` the classification step already settled."""
    produced = candidates.get(CATEGORY_FIELD)
    return produced[0].raw_value if produced else ""


def _rubro_applies(candidates: dict[str, list[FieldCandidate]]) -> bool:
    """Whether the line-of-business step has a rubro that gives it a question.

    The step asks about diners or litres; on a receipt that is neither a restaurant
    nor a fuel purchase there is nothing to ask, so it is **skipped** rather than
    asked and answered with nulls on every document (measured: both fields came back
    absent from a restaurant receipt when the single pass asked anyway).
    """
    return _rubro_value(candidates) in RUBRO_CATEGORIES


def _engine() -> OllamaEngine:
    """Build the local engine with the flow's sampling window declared.

    The two steps are one function so they cannot drift apart: the adapter reads
    its options from the environment **at call time**, so an engine built without
    the declaration runs at the runtime's own default — measured, 4096 — and a
    caller that built the engine but forgot the dial would get a silent window
    change rather than an error. Keeping them together makes *declared window*
    an attribute of the engine instead of a step a caller has to remember.
    """
    apply_sampling()
    return OllamaEngine()


# `too-many-locals`: `extract` is the lane sequence itself — each lane's
# candidate map, the two review prompts, the collected record. Its shape is the
# contract `my_flow.md` §4 states, and splitting it would move the same names one
# frame away.
# pylint: disable=too-many-locals


def extract(  # pylint: disable=too-many-branches
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
    engine = _engine()

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
    for field, produced in _regexp_candidates(text, config).items():
        candidates.setdefault(field, []).extend(produced)

    # --- Lane A, text -----------------------------------------------------
    text_fields: dict[str, list[FieldCandidate]] = {}
    if text:
        prompt = extract_text_prompt.replace(TEXT_PLACEHOLDER, text)
        answered, refusal = _call_structured(
            engine, config.text_model_a, prompt, extraction_schema
        )
        if answered is None:
            notes.append(f"text lane A refused ({refusal}); no text candidates")
        else:
            text_fields = _fields_to_candidates(
                answered, "extractor_llm_texto", text, config
            )
            for field, produced in text_fields.items():
                candidates.setdefault(field, []).extend(produced)
            values.update(document_values(answered))

    # --- Lane B, text (reviewer) -----------------------------------------
    if text and text_fields:
        proposal = json.dumps(
            {field: produced[0].raw_value for field, produced in text_fields.items()},
            ensure_ascii=False,
        )
        review_prompt = review_text_prompt.replace(TEXT_PLACEHOLDER, text).replace(
            PROPOSAL_PLACEHOLDER, proposal
        )
        verdicts, refusal = _review_verdicts(
            engine, config.text_model_b, review_prompt, review_schema
        )
        unmatched = _apply_review(candidates, verdicts, config)
        note = _reviewer_note(
            "text", config.text_model_b, len(verdicts), refusal, unmatched
        )
        if note:
            notes.append(note)

    # --- Lane A, vision ---------------------------------------------------
    vision_fields: dict[str, list[FieldCandidate]] = {}
    if config.vision_model_a and material.images:
        answered, refusal = _call_vision(
            engine,
            config.vision_model_a,
            extract_vision_prompt,
            material.images,
            extraction_schema,
        )
        if answered is None:
            notes.append(f"vision lane A refused ({refusal}); no vision candidates")
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
        verdicts, refusal = _review_verdicts(
            engine,
            config.vision_model_b,
            review_prompt,
            review_schema,
            images=material.images,
        )
        unmatched = _apply_review(candidates, verdicts, config)
        note = _reviewer_note(
            "vision", config.vision_model_b, len(verdicts), refusal, unmatched
        )
        if note:
            notes.append(note)

    # --- Cross-modal agreement -------------------------------------------
    _cross_modal(candidates, config)

    # --- The reserved steps, in order -------------------------------------
    collected = _Collected(candidates, values, notes)
    _run_reserved_steps(engine, material, config, artifacts, collected)

    return Extraction(candidates=candidates, values=values, notes=notes)
