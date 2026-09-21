"""Fase C1: the build gates — reachability, drift, and the journal.

Three gates that must fail the build when an invariant breaks, not merely pass
when it holds (`my_flow.md` B.16, B.11, B.5):

1. **Reachability (I8).** Every implemented (severity, tier) pair keeps a path to
   `CONFIRMED`; the one intentionally unreachable cell stays unreachable. If a
   threshold or a family point changes so a reachable pair stops closing, this
   fails.
2. **Prompt↔schema drift (B.11).** Every field the registry schema requires is
   named in the prompt, and vice versa; amounts are strings; a field declared as
   options must be a real `enum`, not prose in a `description`.
3. **Journal (B.5).** The signature is canonical (a set's order does not change
   it); a changed setting or input discards the journal; invalidation marks the
   downstream, never the artifact bytes.
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest
from flow import run
from flow._bootstrap import REGISTRY_ROOT, ensure_docflow_importable
from flow.artifacts import load_artifacts
from flow.config import DEFAULT_CONFIG
from flow.engine import DecisionContext, decide_field
from flow.fields import (
    DECISION_CONFIRMED,
    PASS,
    EvidenceSignal,
    FieldCandidate,
)
from flow.journal import Journal, run_signature
from flow.record import read_run
from flow.stages import STAGE_DECIDE, STAGE_EXTRACT, STAGE_READ, STAGES

ensure_docflow_importable()

# `wrong-import-position`: `docflow` is only importable once the bootstrap above has
# put `src/` on `sys.path`. The order is load-bearing, not cosmetic — the same rule
# `flow/artifacts.py` and `flow/extract.py` state for their own imports.
from docflow.kernels.registry import (  # noqa: E402  # pylint: disable=wrong-import-position
    load_registry,
)


def _candidate(raw: str, signals: list[EvidenceSignal]) -> FieldCandidate:
    return FieldCandidate(
        normalized_value="".join(ch for ch in raw if ch not in "., "),
        raw_value=raw,
        producers=["test"],
        signals=signals,
        hard_refutations=[],
    )


def _signal(family: str, points: int, *, verified: bool = False) -> EvidenceSignal:
    return EvidenceSignal(family, PASS, points, "test", verified=verified)


def _decide(field: str, tier: str, raw: str, signals: list[EvidenceSignal]) -> object:
    ctx = DecisionContext(config=DEFAULT_CONFIG, tier=tier, own_cuits=frozenset())
    return decide_field(field, [_candidate(raw, signals)], ctx, {})


# --- 1. Reachability (I8) -------------------------------------------------


def _det() -> EvidenceSignal:
    return _signal("DETERMINISTIC", 3)


def _content() -> EvidenceSignal:
    return _signal("DOCUMENT_CONTENT", 2, verified=True)


def _cross() -> EvidenceSignal:
    return _signal("CROSS_MODAL", 2)


def _same() -> EvidenceSignal:
    return _signal("SAME_MATERIAL", 1)


def test_reachability_confirms_every_implemented_pair() -> None:
    """Every implemented (severity, tier) pair closes with its maximum signals.

    The signal sets below are the Anexo A maxima for the families the engine
    implements today. If a threshold or point changes so one of these stops
    closing, this test fails — which is exactly I8's purpose.
    """
    cases = [
        # (field, tier, raw, signals)
        # critica, OCR, with arithmetic: 3 + 2 + 2 + 1 = 8 ≥ 5, gate DETERMINISTIC
        (
            "importe_total_facturado",
            "escaneado_ocr",
            "17.898,30",
            [_det(), _content(), _cross(), _same()],
        ),
        # critica, OCR, without arithmetic but cross-modal: 2+2+1 = 5 ≥ 5
        (
            "importe_total_facturado",
            "escaneado_ocr",
            "17.898,30",
            [_content(), _cross(), _same()],
        ),
        # alta (CUIT), native, with checksum: 3+2+1 = 6 ≥ 3
        (
            "cuit_emisor",
            "texto_nativo",
            "20-22087601-3",
            [_det(), _content(), _same()],
        ),
        # media (razón social), native: 2+1 = 3 ≥ 3, no gate
        (
            "razon_social_emisor",
            "texto_nativo",
            "AIMARO JAVIER ANGEL",
            [_content(), _same()],
        ),
        # baja (descripción), OCR: 2+2+1 = 5 ≥ 4, no gate
        ("descripcion", "escaneado_ocr", "repuestos", [_content(), _cross(), _same()]),
    ]
    for field, tier, raw, signals in cases:
        decision = _decide(field, tier, raw, signals)
        assert decision.decision == DECISION_CONFIRMED, (
            f"{field}/{tier} lost its path to CONFIRMED: {decision.decision} "
            f"{decision.reason_codes} (score {decision.score}, threshold "
            f"{decision.threshold}, gate {decision.gate_satisfied})"
        )


def test_reachability_keeps_the_intentional_gap() -> None:
    """A critical field in native text without any strong evidence cannot
    confirm — the one cell Anexo A leaves unreachable on purpose."""
    decision = _decide(
        "importe_total_facturado",
        "texto_nativo",
        "17.898,30",
        [_content(), _same()],
    )

    assert decision.decision != DECISION_CONFIRMED
    assert "REV_GATE_UNMET" in decision.reason_codes


# --- 2. Prompt↔schema drift (B.11) ----------------------------------------


def test_registry_schema_and_prompt_agree() -> None:
    """Every extraction prompt names every required field, and vice versa.

    Both extract lanes share the schema, so the drift test runs over the text
    prompt and the vision prompt alike — a field the schema requires and one
    lane never names is the same silent drift, just in one lane.
    """
    artifacts = load_artifacts()
    schema = artifacts.extraction_schema
    required = set(schema["required"])
    properties = set(schema["properties"])

    for role in ("extract_texto", "extract_vision"):
        prompt = artifacts.prompts[role]
        missing = sorted(name for name in required if name not in prompt)
        undeclared = sorted(name for name in properties if name not in prompt)
        assert not missing, (
            f"{role}: schema requires {missing} that the prompt never names"
        )
        assert not undeclared, (
            f"{role}: schema declares {undeclared} that the prompt never names"
        )


def test_a_closed_vocabulary_field_declares_a_real_enum() -> None:
    """A field whose answers are a closed list declares them as `enum`.

    The defect this guards is one of *omission*, and no test of the enum's
    contents can see it: drop the `enum` key and every "the options reach the
    prompt" assertion becomes vacuous, because there are no options to check.
    Measured, that omission is exactly what produced the echo — with the option
    list living in `description`, `deepseek-r1:1.5b` returned the description
    itself (`"090 | 099"`).

    The list below is a transcription, not a derivation: it names the fields
    whose answer set the prompt enumerates. A new field with a closed vocabulary
    must be added here, which is the point — the rule cannot be satisfied by
    silence.
    """
    closed_vocabulary: frozenset[str] = frozenset(
        {
            "comprobante_valido",
            "tipo_comprobante",
            "moneda",
            "condicion_impositiva_dominante",
            "categoria_gasto",
        }
    )
    schema = load_artifacts().extraction_schema

    missing = sorted(
        field
        for field in closed_vocabulary
        if "enum" not in schema["properties"].get(field, {})
    )

    assert not missing, (
        f"these fields answer from a closed list but declare no `enum`, so the "
        f"model can echo the option list as a value: {missing}"
    )


def test_no_prompt_example_collides_with_a_real_document_value() -> None:
    """A prompt's example must not be a value a real document can contain.

    Measured: the rule-3 example read `"C.U.I.T. Nro.: 20-1 Ing, Brutas: 201641"
    -> "cuit_emisor": "20-1"`, and the fixture's issuer CUIT is `20-22087601-3`
    — its **literal prefix**. `deepseek-r1:1.5b` returned `"20-1"` on 1 of 3 runs,
    and returned whatever the example said when the example was changed to
    `"99-9"`. Removing the example made it answer correctly 3 of 3.

    The rule is about the **shape** of an example, not its number: an example
    drawn from the value space of a real field is a plausible wrong answer
    (`my_flow.md` B.10), and it is indistinguishable from a reading.
    """
    artifacts = load_artifacts()
    examples = _prompt_examples(artifacts.prompts)

    assert examples, "the prompts are expected to carry worked examples"
    for role, example in examples:
        assert not _looks_like_a_real_value(example), (
            f"{role}: the example {example!r} is drawn from the value space of a "
            "real field; use a value no document can print (e.g. an impossible "
            "prefix such as 99-9) so a copied example cannot pass as a reading"
        )


#: The CUIT prefixes AFIP issues. A worked example must stay outside this set, so
#: a copied example can never pass as a reading. Measured: the rule-3 example was
#: `20-1`, and the fixture's issuer CUIT is `20-22087601-3` — the example is that
#: value's literal prefix, and the model returned it on 1 of 3 runs.
_CUIT_PREFIXES: frozenset[str] = frozenset(
    {"20", "23", "24", "25", "27", "30", "33", "34", "50"}
)

#: Patterns whose match makes a prompt example indistinguishable from a real
#: document value: a **possible** CUIT, a printed amount, or a printed date.
_LOOKS_REAL: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b\d{1,3}(?:\.\d{3})+,\d{2}\b"),  # a printed amount
    re.compile(r"\b\d{1,2}/\d{1,2}/\d{4}\b"),  # a printed date
)


def _prompt_examples(prompts: dict[str, str]) -> list[tuple[str, str]]:
    """The example values a prompt's worked examples introduce.

    `re.DOTALL` because a worked example wraps across lines and the arrow lands on
    the continuation: without it the CUIT example — the one whose collision was
    measured — is invisible to this guard.
    """
    found: list[tuple[str, str]] = []
    for role, text in sorted(prompts.items()):
        for match in re.finditer(r'"([^"]+)"\s*->\s*"[^"]*"', text, re.DOTALL):
            found.append((role, match.group(1)))
    return found


def _looks_like_a_real_value(example: str) -> bool:
    """Whether a quoted example could be mistaken for a value read from a file.

    A CUIT-shaped example is judged by its **prefix**: `99-9` cannot be a real
    CUIT prefix, so it is a safe illustration, while `20-1` is a real prefix and
    therefore indistinguishable from a truncated reading of `20-22087601-3`.
    """
    if any(pattern.search(example) for pattern in _LOOKS_REAL):
        return True
    return any(
        match.group(1) in _CUIT_PREFIXES
        for match in re.finditer(r"\b(\d{2})-\d", example)
    )


def test_the_condition_field_declares_afip_legends_not_rates() -> None:
    """`condicion_impositiva_dominante` holds a condition, never an alícuota.

    The field answers *who the emitter is before IVA*, declared with one of
    AFIP's legends (RG 259/98): responsable inscripto, monotributo, exento, no
    categorizado, consumidor final. The rates live in `alicuotas_detectadas`.

    Measured, the enum used to hold `[21, 10_5, 27, 2_5, exento_no_gravado]` —
    four rates plus one label — so the model answered the field with the rate
    it had just read (`condicion_impositiva_dominante: "21"`) and the condition
    was never captured. A vocabulary that mixes two questions gets the wrong
    answer to both.
    """
    schema = load_artifacts().extraction_schema
    enum = schema["properties"]["condicion_impositiva_dominante"]["enum"]

    rates = [option for option in enum if re.fullmatch(r"\d+(_\d+)?", option)]
    assert not rates, (
        f"`condicion_impositiva_dominante` accepts rates {rates}; a rate is not a "
        "condition and belongs in `alicuotas_detectadas`"
    )
    assert "Responsable Inscripto" in enum, enum
    assert "null" in enum, enum


def test_the_rate_field_declares_the_real_afip_rates() -> None:
    """`alicuotas_detectadas` names the AFIP rate set, including 5%.

    Measured against AFIP's Libro IVA Digital rate table: 0,00 (0003), 2,50
    (0009), 5,00 (0008), 10,50 (0004), 21,00 (0005), 27,00 (0006). The registry
    described the field as "every rate found" and the prompts listed only four,
    so a 5% line — a real rate for certain goods — had no name to be read into.
    """
    schema = load_artifacts().extraction_schema
    description = schema["properties"]["alicuotas_detectadas"]["description"]

    for rate in ("2_5", "5", "10_5", "21", "27"):
        # A bounded match, not a substring: `"5" in "10_5, 21"` is True, so a
        # substring check would pass while the 5% rate was missing entirely.
        assert re.search(rf"(?<![\d_]){re.escape(rate)}(?![\d_])", description), (
            f"the AFIP rate {rate!r} is missing from `alicuotas_detectadas`: "
            f"a rate with no name cannot be reported"
        )


def test_every_receipt_code_the_prompt_names_is_in_the_enum() -> None:
    """The other direction: a code the prompt teaches must be an accepted answer.

    The forward check (every enum option reaches the prompt) cannot see a code the
    prompt names but the enum rejects — the model would be taught `011` and then
    constrained out of answering it. The prompt is the source of truth for what a
    document prints, so it is parsed for the codes of the type table.
    """
    artifacts = load_artifacts()
    enum = artifacts.extraction_schema["properties"]["tipo_comprobante"]["enum"]

    for role in ("extract_texto", "extract_vision"):
        named = set(re.findall(r"\b(00[16]|011|090|099)\b", artifacts.prompts[role]))
        missing = sorted(code for code in named if code not in enum)
        assert not missing, (
            f"{role}: the prompt names {missing}, but the enum rejects them: "
            "the model is taught a code it cannot answer with"
        )


# `xfail` with `strict=True`: the overlap it reports is the *expected* state until
# step 3 trims `invoice.json`, and `strict` means the marker must be removed the
# moment the partition becomes clean — an `xpass` would otherwise go unnoticed.
@pytest.mark.xfail(
    strict=True,
    reason="step 3 pending: invoice.json still carries all 23 fields",
)
def test_the_extraction_steps_partition_every_field() -> None:
    """The four extraction steps together cover the contract, with no overlap.

    `invoice.json` is the single-pass contract: 23 fields. The layered implementation
    splits them across four artifacts — base reading, tax breakdown, line-of-business
    detail and classification — which are **declared but not loaded** yet, per
    `cierre-circuitos.md` §«Enfoque en capas», step 1.

    This test is what makes the split a property rather than a promise. Without it,
    "we will split the extraction" is a note; with it, dropping a field while
    partitioning fails the build. It reads the four schemas from the registry, so it
    also proves the reservations are declared and their files are valid JSON the
    provider could constrain on.

    The partition must be:
    - **complete**, every field of the single-pass contract lands in exactly one step;
    - **disjoint**, no field is claimed by two steps, because two steps claiming one
      field is two answers for one value.

    Until step 3 runs, this test fails on the overlap and that is the honest state:
    the four artifacts exist and are declared, while `invoice.json` still carries all
    23 fields. It is marked `xfail` on purpose — a `skip` would hide that the work is
    outstanding, and an unmarked failure would block the suite on a known state.
    Remove the marker when `invoice.json` is trimmed to the base step.
    """
    artifacts = load_artifacts()
    contract = set(artifacts.extraction_schema["properties"])
    steps = _extraction_step_properties()

    assert set(steps) == set(_EXTRACTION_STEPS), (
        f"the registry declares {sorted(steps)}, expected {sorted(_EXTRACTION_STEPS)}"
    )

    claimed: dict[str, str] = {}
    for name, fields in steps.items():
        for field in fields:
            assert field not in claimed, (
                f"`{field}` is claimed by both {claimed[field]!r} and {name!r}: two "
                "steps answering one field is two answers for one value"
            )
            claimed[field] = name

    lost = sorted(contract - set(claimed))
    assert not lost, f"the partition drops these fields from the contract: {lost}"

    extra = sorted(set(claimed) - contract)
    assert not extra, (
        f"the partition invents fields the contract does not declare: {extra}"
    )


#: The extraction steps a layered implementation runs, in order, and the registry
#: keys that declare each one's fields. Keyed declaratively rather than discovered,
#: so a step that disappears is a failure and not a smaller loop.
_EXTRACTION_STEPS: dict[str, str] = {
    "base": "schemas/extraction/invoice.json",
    "desglose": "schemas/extraction/desglose.json",
    "rubro": "schemas/extraction/rubro.json",
    "clasificacion": "schemas/extraction/clasificacion.json",
}


def _extraction_step_properties() -> dict[str, set[str]]:
    """Each extraction step, mapped to the fields its schema declares.

    Read from the manifest's assets rather than from the filesystem: the registry is
    the single source (`my_flow.md` B.15), and a schema that is on disk but
    undeclared is refused by K8 rather than silently half-counted.
    """
    loaded = load_registry(REGISTRY_ROOT)
    assert loaded.value is not None, "the registry must load for this gate to mean"
    assets = loaded.value.assets

    steps: dict[str, set[str]] = {}
    for name, key in _EXTRACTION_STEPS.items():
        asset = assets.get(key)
        assert asset is not None, f"the {name} schema {key!r} is not declared"
        parsed = json.loads(asset.content.decode("utf-8"))
        steps[name] = set(parsed["properties"])
    return steps


def test_every_enum_option_is_declared_in_the_prompt() -> None:
    """An enum's options reach the prompt, or the model is constrained blind.

    The schema constrains generation (Ollama receives it as `format`), so an
    option the prompt never mentions is an answer the model can be forced into
    without ever being told it was available. This is the drift the field-name
    check above cannot see: names can agree while the vocabulary does not.

    Measured: with the option list living only in the schema's `description`,
    `deepseek-r1:1.5b` returned the **description itself** as the value
    (`"090 | 099"`, and `"21 | 10_5 | 27 | 2_5 | exento_no_gravado | null"`).
    """
    artifacts = load_artifacts()
    schema = artifacts.extraction_schema

    for role in ("extract_texto", "extract_vision"):
        prompt = artifacts.prompts[role]
        for field, spec in schema["properties"].items():
            for option in spec.get("enum", []):
                assert option in prompt, (
                    f"{role}: `{field}` accepts {option!r} per the schema, but "
                    f"the prompt never mentions it"
                )


def test_every_enum_has_an_abstention_escape() -> None:
    """An enum that cannot abstain forces the model to invent an option.

    A grammar-backed enum leaves the model no way out of the set. Measured on a
    *remito* (a delivery note, not a fiscal receipt) against
    `enum: [A, B, C, 090, 099]`: **3 of 3 runs returned a receipt type** — `A`,
    `090`, `090` — none of which the document bears. Adding `"null"` to the same
    enum made it abstain in 2 of 3 (`my_flow.md` B.10: the dangerous failure mode
    is the one that returns a plausible value).

    A field whose enum is a closed classification must therefore carry an escape
    — either the literal `"null"`, or a member that **is** the abstention by its
    own definition (see `_ABSTENTION_IS_A_MEMBER`).
    """
    schema = load_artifacts().extraction_schema

    for field, spec in schema["properties"].items():
        options = spec.get("enum")
        if not options or field in _ABSTENTION_IS_A_MEMBER:
            continue
        assert "null" in options, (
            f"`{field}` has enum {options} with no 'null' escape, so the model "
            "cannot decline to answer"
        )


#: Enums where one of the values already **is** the abstention, so a `null` would
#: be a second way to say the same thing — or would contradict the prompt.
#:
#: - `comprobante_valido` is the binary classification *is this a readable
#:   receipt*: its prompt defines `"false"` as exactly that, and a document the
#:   model cannot judge takes `"false"`.
#: - `moneda` has a **declared default**: the prompt says *"without an explicit
#:   indication of currency, use ARS"*. Adding `null` would offer the model an
#:   answer the prompt forbids, which is worse than the constraint — the enum
#:   would then be able to produce a value no rule expects.
#:
#: The exceptions are stated here rather than by loosening the rule: a rule that
#: admits anything is not a rule, and the next enum added still has to justify
#: itself against it.
_ABSTENTION_IS_A_MEMBER: frozenset[str] = frozenset({"comprobante_valido", "moneda"})


def test_every_configured_local_model_name_is_tagged() -> None:
    """A configured model name carries its tag, or the runtime cannot invoke it.

    Measured against this Ollama runtime: ``POST /api/chat {"model": "gemma3"}``
    answers ``404 model not found`` even though ``gemma3:1b`` is pulled and
    answers ``200``. Ollama resolves a bare name **only** when it matches
    exactly, so a tagless name is not *the family* — it is a name that dies at
    the call.

    The lane that died this way reported ``no review verdicts``, which reads the
    same as a reviewer that agreed with everything. This test is what makes the
    configuration a checked fact rather than a string nobody validated
    (`my_flow.md` §4.1 names the family; the tag is what makes it reachable).
    """
    untagged = [
        name
        for name in (
            DEFAULT_CONFIG.text_model_a,
            DEFAULT_CONFIG.text_model_b,
            DEFAULT_CONFIG.vision_model_a,
            DEFAULT_CONFIG.vision_model_b,
        )
        if name is not None and ":" not in name
    ]

    assert not untagged, (
        f"these configured models carry no tag, so the runtime cannot invoke "
        f"them: {untagged}. Name the pulled model exactly, e.g. `gemma3:1b`."
    )


def test_registry_amounts_are_strings() -> None:
    """Every amount field is a string, so a printed amount survives as text."""
    schema = load_artifacts().extraction_schema
    amounts = [
        "subtotal",
        "iva",
        "impuestos_internos",
        "percepcion_iibb",
        "otros_impuestos",
        "monto_no_gravado",
        "importe_total_facturado",
    ]
    for name in amounts:
        if name in schema["properties"]:
            assert schema["properties"][name]["type"] == "string", (
                f"{name!r} is not declared a string"
            )


# --- 3. Journal (B.5) ------------------------------------------------------


def test_signature_is_canonical_across_set_order() -> None:
    """A set's iteration order does not leak into the signature.

    The two inputs are the same members in different orders, and the canonical
    form is the sorted list — so a `set` and a `list` with those members must
    sign identically. Without the sort, a set whose hash order differs from its
    sorted order would sign differently on every run (B.5).
    """
    a = run_signature({"own_cuits": {"d", "c", "a", "b"}})
    b = run_signature({"own_cuits": ["a", "b", "c", "d"]})

    assert a == b


def test_a_changed_setting_is_a_different_signature() -> None:
    """One changed dial is a different run, so the journal is discarded."""
    a = run_signature({"model": "a"})
    b = run_signature({"model": "b"})

    assert a != b


def test_clear_from_marks_the_stage_and_every_later_one() -> None:
    """Invalidation marks the stage and its downstream, never the artifact."""
    journal = Journal(pathlib.Path("/tmp"), "sig", "digest")
    for stage in STAGES:
        journal.mark(stage)

    journal.clear_from(STAGE_EXTRACT)

    assert journal.done(STAGE_READ) is True
    assert journal.done(STAGE_EXTRACT) is False
    assert journal.done(STAGE_DECIDE) is False


def test_a_changed_digest_is_a_different_run(tmp_path: pathlib.Path) -> None:
    """The document's own bytes are part of the journal; editing them re-runs."""
    work = tmp_path / "work"
    doc = tmp_path / "a.pdf"
    doc.write_bytes(b"a")

    run(doc, {}, work_root=work)
    doc.write_bytes(b"b")
    outcome = run(doc, {}, work_root=work)

    assert all(step.action == "ran" for step in outcome.steps)


def test_the_run_record_is_json_and_derived(tmp_path: pathlib.Path) -> None:
    """`run.json` parses back and carries the four steps, derived not assumed."""
    work = tmp_path / "work"
    doc = tmp_path / "a.pdf"
    doc.write_bytes(b"a")
    run(doc, {}, work_root=work)

    raw = json.loads((work / "run.json").read_text(encoding="utf-8"))
    assert raw["document"] == "a.pdf"
    assert len(raw["steps"]) == 4
    record = read_run(work)
    assert record is not None and len(record.steps) == 4
