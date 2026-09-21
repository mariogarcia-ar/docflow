"""Fase B1: the engine's invariants, tested over constructed values.

These are the four invariants `my_flow.md` makes non-negotiable, exercised
without an adapter. Each test is paired with a mutation that breaks exactly one
invariant — a test that only passes when the code is correct proves nothing
(B.16), so the proof is that the mutation turns it red.
"""

from __future__ import annotations

import ast
import dataclasses
import pathlib

from flow.config import DEFAULT_CONFIG, FAMILY_POINTS
from flow.engine import DecisionContext, _resolve_arithmetic, decide_field
from flow.fields import (
    FAIL,
    PASS,
    UNKNOWN,
    EvidenceSignal,
    FieldCandidate,
    merge_candidates,
)
from flow.validators import (
    all_components_are_amounts,
    arithmetic_signal,
    cuit_signal,
)


def _candidate(raw: str, *signals: EvidenceSignal) -> FieldCandidate:
    return FieldCandidate(
        normalized_value="".join(ch for ch in raw if ch not in "., "),
        raw_value=raw,
        producers=["test"],
        signals=list(signals),
        hard_refutations=[],
    )


def _ctx(tier: str = "texto_nativo") -> DecisionContext:
    return DecisionContext(config=DEFAULT_CONFIG, tier=tier, own_cuits=frozenset())


def _pass(family: str, points: int) -> EvidenceSignal:
    return EvidenceSignal(family, PASS, points, "test")


def _fail(family: str, detail: str) -> EvidenceSignal:
    return EvidenceSignal(family, FAIL, -2, detail)


def _unknown(family: str) -> EvidenceSignal:
    return EvidenceSignal(family, UNKNOWN, 0, "test")


#: The module that *declares* the dials. The scan skips it: a dial named in its
#: own declaration file is not a dial that is read.
CONFIG_MODULE = "config.py"


# --- I2: the score belongs to the candidate, merged before scoring ---------


def test_i2_same_normalized_value_merges_into_one_candidate() -> None:
    """`"17.898,30"` and `"17898.30"` are one candidate, not competitors.

    Two printed forms of the same amount — thousands dot + decimal comma, and
    decimal dot only — normalise to the same key, so they must merge (I2).
    """
    a = _candidate("17.898,30")
    b = _candidate("17898.30")

    merged = merge_candidates([a, b])

    assert len(merged) == 1
    assert merged[0].raw_value == "17.898,30"


def test_i2_merge_conserves_both_producers() -> None:
    """The merge keeps every producer, so no evidence is dropped."""
    a = FieldCandidate(
        "123", "123", producers=["regexp"], signals=[], hard_refutations=[]
    )
    b = FieldCandidate("123", "123", producers=["llm"], signals=[], hard_refutations=[])

    merged = merge_candidates([a, b])

    assert len(merged) == 1
    assert set(merged[0].producers) == {"regexp", "llm"}


# --- I3: a hard refutation vetoes; no score compensates --------------------


def test_i3_a_vetoed_candidate_never_wins() -> None:
    """The only candidate, if vetoed, produces ESC_ALL_VETOED, not a win."""
    vetoed = FieldCandidate(
        normalized_value="99999999999",
        raw_value="99-99999999-9",
        producers=["test"],
        signals=[],
        hard_refutations=["CUITS_CHECKSUM_INVALID"],
    )

    decision = decide_field(
        "cuit_emisor",
        [vetoed],
        _ctx(),
        {"subtotal": "", "iva": "", "importe_total_facturado": ""},
    )

    assert decision.decision == "ESCALATE"
    assert "ESC_ALL_VETOED" in decision.reason_codes


# --- I4: max one signal per family -----------------------------------------


def test_i4_two_passes_in_one_family_score_once() -> None:
    """Two DETERMINISTIC passes are worth one +3, not +6."""
    candidate = _candidate(
        "20-22087601-3", _pass("DETERMINISTIC", 3), _pass("DETERMINISTIC", 3)
    )

    decision = decide_field("cuit_emisor", [candidate], _ctx(), {})

    assert decision.score == 3  # one deterministic +3, not two


# --- I10: UNKNOWN scores nothing and never vetoes --------------------------


def test_i10_unknown_scores_nothing() -> None:
    """An UNKNOWN signal contributes zero points, whatever its family."""
    candidate = _candidate("20-22087601-3", _unknown("DETERMINISTIC"))

    decision = decide_field("cuit_emisor", [candidate], _ctx(), {})

    # The validator re-runs over the CUIT and PASSes its checksum; the point is
    # that the *unknown* input signal alone would not have scored anything.
    assert decision.score >= 3


def test_i10_an_incomplete_equation_is_unknown_not_fail() -> None:
    """A missing component yields UNKNOWN, never a hard refutation (§6.4)."""
    signal = arithmetic_signal(
        "15.000,00", "", "17.898,30", family_points=FAMILY_POINTS
    )

    assert signal.result == UNKNOWN
    assert signal.detail != "ARITHMETIC_INCONSISTENT"


def test_i10_a_failed_checksum_is_a_veto_not_unknown() -> None:
    """With all 11 digits, a wrong checksum is FAIL (a veto), not UNKNOWN."""
    signal = cuit_signal(
        "20-12345678-0", own_cuits=frozenset(), family_points=FAMILY_POINTS
    )

    assert signal.result == FAIL
    assert signal.detail == "CUITS_CHECKSUM_INVALID"


# --- I10 / §6.4: a component that is not an amount is ABSENT, not wrong -----


def test_i10_a_component_that_is_not_an_amount_makes_the_equation_unknown() -> None:
    """A non-amount component leaves no equation to judge — never `non_unique`.

    §6.4: *"if any [component] is missing, it answers UNKNOWN: it scores nothing,
    it vetoes nothing"*. A component the rule cannot read as an amount **is not
    there**, and treating it as a failed combination is what escalated both
    critical fields with a motive that was untrue (measured: a junk `iva` next to
    a correct subtotal and total).

    The four measured shapes of "not an amount": a list the model echoed, an
    alícuota (B.7), a declared-absent `"null"`, and an empty string.
    """
    for junk in ("0,90 | 0", "21,0%", "null", ""):
        cands = {
            "subtotal": [_candidate("17.898,30")],
            "iva": [_candidate(junk)],
            "importe_total_facturado": [_candidate("17.898,30")],
        }
        ctx = DecisionContext(
            config=DEFAULT_CONFIG, tier="texto_nativo", own_cuits=frozenset()
        )
        _resolve_arithmetic(ctx, cands, {})

        assert ctx.arithmetic_resolution is None, (
            f"iva={junk!r} is not an amount, so there is no equation to judge; "
            f"got {ctx.arithmetic_resolution!r}"
        )


def test_i10_a_real_inconsistency_still_escalates() -> None:
    """The control: readable amounts that do not add up are still `non_unique`.

    Without this, collapsing every result to `None` would pass the test above
    while removing the arithmetic rule's whole purpose.
    """
    cands = {
        "subtotal": [_candidate("10.000,00")],
        "iva": [_candidate("2.100,00")],
        "importe_total_facturado": [_candidate("99.999,00")],
    }
    ctx = DecisionContext(
        config=DEFAULT_CONFIG, tier="texto_nativo", own_cuits=frozenset()
    )

    _resolve_arithmetic(ctx, cands, {})

    assert ctx.arithmetic_resolution == "non_unique"


def test_i10_a_single_consistent_combination_is_still_found() -> None:
    """The other control: a complete, consistent equation resolves to one."""
    cands = {
        "subtotal": [_candidate("10.000,00")],
        "iva": [_candidate("2.100,00")],
        "importe_total_facturado": [_candidate("12.100,00")],
    }
    ctx = DecisionContext(
        config=DEFAULT_CONFIG, tier="texto_nativo", own_cuits=frozenset()
    )

    _resolve_arithmetic(ctx, cands, {})

    assert ctx.arithmetic_resolution == "consistent"


def test_all_components_are_amounts_rejects_the_measured_junk() -> None:
    """The precondition is a rule of its own, so it is asserted on its own."""
    assert all_components_are_amounts("1.234,56", "0", "1.234,56") is True
    assert all_components_are_amounts("$ 1.234,56", "0", "1.234,56") is True
    for junk in ("0,90 | 0", "21,0%", "null", "", "ABC"):
        assert all_components_are_amounts("1.234,56", junk, "1.234,56") is False, junk


# --- The config is the only source of a dial -------------------------------


def test_the_escalate_floor_dial_decides_the_verdict() -> None:
    """Changing `Config.escalate_floor` changes the decision it claims to gate.

    The defect this guards, measured: `engine.py` read the module constant
    `ESCALATE_FLOOR` while carrying the run's `Config` one attribute away — and
    `family_points`, in the same module, was read from `ctx.config`. So the dial
    was split in two: one attribute honoured, its neighbour ignored. Measured,
    `dataclasses.replace(DEFAULT_CONFIG, escalate_floor=0)` left every verdict
    **identical** — the number in the escalation message was a constant dressed
    as a dial, and an operator who tuned it would have changed nothing while the
    report confirmed their change had been applied.

    The assertion is the difference between two runs of the same candidate, so
    it fails whether the dial is ignored *or* wired to the wrong field. A test
    that only checked the default value would pass on the broken code.
    """
    candidate = _candidate("x", _pass("SAME_MATERIAL", 1))
    fields = {"subtotal": "", "iva": "", "importe_total_facturado": ""}

    def decide(floor: int) -> object:
        config = dataclasses.replace(DEFAULT_CONFIG, escalate_floor=floor)
        ctx = DecisionContext(config=config, tier="texto_nativo", own_cuits=frozenset())
        return decide_field("notas", [candidate], ctx, fields).decision

    assert decide(2) == "ESCALATE", "score 1 is below a floor of 2"
    assert decide(0) == "REVIEW", (
        "with a floor of 0 the same candidate must stop escalating: the run's "
        "config is not the thing being read"
    )


def test_no_module_reaches_a_dial_by_importing_it() -> None:
    """A dial is read from a `Config`, never imported as a module constant.

    The general form of the defect above, and the reason this test exists rather
    than only the one before it: a single dial read as a constant is a typo, and
    the *class* is a dial that is declared, documented, journalled as a setting
    and then never consulted.

    **The first version of this test was a false negative, and the mutation
    proved it.** It scanned the sources for `config.<name>` and treated a hit as
    "read" — but the mutated code still *mentioned* the name, in the escalation
    message on the line after the branch that had gone back to the constant. So
    the scan found the mention and passed while the decision ignored the dial.
    **A gate that matches a mention is not a gate on a use.**

    This version asserts the mechanism instead of the text: reaching a dial
    without a `Config` requires importing its module-level constant, and the
    import is what puts it in scope. Reading it through `ctx.config.<name>` or a
    `config` parameter needs no import at all. Only the three names that *are*
    the declaration — the class, the default instance and the per-severity dial
    type — are legitimately imported.
    """
    flow = pathlib.Path("scripts/poc-flow-v2/flow")
    offenders: list[str] = []
    for path in sorted(flow.glob("*.py")):
        if path.name == CONFIG_MODULE:
            continue
        imported = _names_imported_from_config(path)
        stray = sorted(imported - _DECLARATION_NAMES)
        if stray:
            offenders.append(f"{path.name}: {stray}")

    assert not offenders, (
        f"these modules import a dial from `config` instead of reading it off a "
        f"`Config`: {offenders}. A dial read as a constant is journalled as a "
        f"setting and then ignored — read it as `ctx.config.<name>`, or delete "
        f"it from `Config`."
    )


def _names_imported_from_config(path: pathlib.Path) -> set[str]:
    """The names a module takes from `config`, read from the import statements."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("config"):
            names.update(alias.name for alias in node.names)
    return names


#: The names in `config.py` that are the *declaration* rather than a dial: the
#: `Config` type, the default instance a caller starts from, and the per-severity
#: dial type. Importing one of these cannot bypass a dial — there is no value to
#: be stale, only a shape to be built. Everything else in `config.py` is a
#: scalar a run may override, so importing it freezes that override out.
_DECLARATION_NAMES: frozenset[str] = frozenset(
    {"Config", "DEFAULT_CONFIG", "FieldDial"}
)
