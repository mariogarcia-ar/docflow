"""The four pending circuits, each proved to fail when its invariant breaks.

Written after an audit that asked *is the wiring complete?* — enumerating what
each artifact **declares** and checking that something reads or emits it. The
audit found one defect (a dial read as a constant), one misreport of its own (the
policy asset *is* read, by `docflow-kernel`), and three circuits that were
declared but not reachable.

Each gate here names the measurement or the contract it protects, and each is
paired with a mutation in `mutation_invariants.py`.
"""

from __future__ import annotations

import json

import pytest
from flow._bootstrap import REGISTRY_ROOT
from flow.amounts import read_amount_columns
from flow.config import DEFAULT_CONFIG, POLICY_FALLBACKS
from flow.extract import _regexp_candidates
from flow.policy import POLICY_ASSET, read_policy
from flow.validators import all_components_are_amounts, arithmetic_consistent

#: The totals row of a real receipt, copied from a fixture's parsed text. The
#: label row carries 12 whitespace tokens for 9 columns (`IVA 10,5%` and
#: `Imp. Int.` hold spaces), which is what makes whitespace-zipping the label row
#: against the value row wrong and column alignment right.
_TOTALS_ROW = (
    "       Bruto           %      Desc./Rec.     Subtotal      IVA 10,5%"
    "       IVA 21,0%          Percep.         Imp. Int.            TOTAL\n"
    "   14.791,98           0,00         0,00   14.791,98             0,00"
    "       3.106,32                0,00          0,00            17.898,30"
)


def test_the_amount_reader_reads_the_printed_totals_row() -> None:
    """The deterministic reader returns the three amounts the row prints.

    Measured, this is the defect it closes: the `desglose` step asked a 1.5B
    model for nine amounts and returned invented figures on **five runs out of
    five** on this very row — `'00000000.00'`, `'123456789.10'`, and `'21%:
    2.100.00'` twice (an alícuota where an importe belongs, B.7). A totals row is
    two lines of fixed columns, which `my_flow.md` §4.2 assigns to `regexp`.

    The assertion is on the three values that make the arithmetic rule judgeable,
    so it fails if any name-to-column pairing drifts.
    """
    amounts = read_amount_columns(_TOTALS_ROW)

    assert amounts.get("subtotal") == "14.791,98", (
        f"the reader did not pair `Subtotal`/`Bruto` with its own column: got {amounts}"
    )
    assert amounts.get("iva") == "3.106,32", (
        f"the IVA column is the sum of the printed rate columns: got {amounts}"
    )
    assert amounts.get("importe_total_facturado") == "17.898,30"


def test_the_reader_output_lets_the_arithmetic_rule_judge() -> None:
    """What the reader returns passes the precondition and the equation.

    Two links, and both are load-bearing: `all_components_are_amounts` is what
    turned a junk component into a visible fact (`R2`), and the equation is what
    awards the critical field its `DETERMINISTIC` +3. A reader that returned
    `'3106.32'` — a float wearing a string's clothes — would pass the equation
    and lose the printed form B.11 requires, so the shape is asserted too.
    """
    amounts = read_amount_columns(_TOTALS_ROW)
    subtotal, iva, total = (
        amounts.get("subtotal"),
        amounts.get("iva"),
        amounts.get("importe_total_facturado"),
    )

    assert all_components_are_amounts(subtotal, iva, total)
    assert arithmetic_consistent(subtotal, iva, total), (
        "14791.98 + 3106.32 == 17898.30, so the row is consistent and the "
        "critical amount has a deterministic route to CONFIRMED"
    )
    assert "," in amounts["iva"], (
        "an amount leaves the reader in the printed form (B.11); a bare number "
        "loses the separators the document shows"
    )


def test_the_reader_refuses_a_row_it_cannot_identify() -> None:
    """No totals row, no amounts — never a partial guess.

    `I10` / `B.9`: an amount that cannot be read is **absent**, which the engine
    already handles (`UNKNOWN` scores nothing and vetoes nothing). Inventing one
    from the nearest numbers is the failure mode `B.10` calls dangerous — no
    error, just a plausible value.
    """
    assert not read_amount_columns("no numbers here at all")
    assert not read_amount_columns("Pág. 1 / 1\nVenc. de CAE: 17/08/2026")


def test_a_label_far_from_every_column_is_not_paired() -> None:
    """A label with no column near it is dropped, not paired with the nearest.

    The guard, and why it needs its own constructed input: **measured**, the real
    receipt's widest label-to-column gap is 6.5 characters against a tolerance of
    20, so no assertion about the fixture can reach this line — deleting the
    guard left every fixture-based test green, and the mutation said so.

    This row reaches it. The trailing `Observaciones` sits 32 characters from the
    value columns, and the two readings differ in a way that matters:

    | | `importe_total_facturado` |
    |---|---|
    | with the guard | `'17.898,30'` |
    | guard removed (measured) | **absent** |

    Without the guard, `Observaciones` is assigned to the nearest column — the
    total's — and the total's own label is pushed out. The column disappears and
    the critical amount with it, silently: nothing raises, the field is gone.
    """
    row = (
        "   Subtotal      IVA 21,0%          TOTAL"
        "                        Observaciones\n"
        "   14.791,98       3.106,32        17.898,30"
    )

    amounts = read_amount_columns(row)

    assert amounts.get("importe_total_facturado") == "17.898,30", (
        "a stray label took the total's column, so the total is missing: "
        f"got {sorted(amounts)}"
    )
    assert "observaciones" not in amounts
    assert amounts.get("subtotal") == "14.791,98"
    assert amounts.get("iva") == "3.106,32"


def test_the_deterministic_producer_anchors_the_values_it_reads() -> None:
    """`regexp` says where each value is, because it read it from there.

    The defect this guards, measured on a real run: `_regexp_candidates` built
    every candidate with **no signals at all**, while the model's lanes attached
    `DOCUMENT_CONTENT`. The anchor is *better* justified for `regexp` than for a
    model — its raw value is a slice of the text — and leaving it off cost the
    critical amount its `DOCUMENT_CONTENT +2`, which with `DETERMINISTIC +3` is
    the only route to `CONFIRMED` for a `critica` field (`t_native=5` **and** a
    strong family). The field stopped at `REVIEW score=3`.

    The gate asserts the family is **present**, not that it passed: a value the
    reader genuinely cannot anchor must report `UNKNOWN` rather than be dropped,
    so the trace shows *no anchor* instead of *nothing was claimed*. Asserting
    `PASS` for every field would be the stronger-looking gate and the wrong one.
    """
    text = (
        "FACTURA A\nCUIT: 20-22087601-3\nFecha de Emisión: 07/08/2026\n"
        "   Subtotal   IVA 21,0%      TOTAL\n"
        "  14.791,98           0,00   14.791,98\n"
    )

    produced = _regexp_candidates(text, DEFAULT_CONFIG)

    assert produced, "the producer found nothing, so the gate proves nothing"
    for field, candidates in produced.items():
        for candidate in candidates:
            families = {signal.family for signal in candidate.signals}
            assert "DOCUMENT_CONTENT" in families, (
                f"{field}={candidate.raw_value!r} carries no anchor: a "
                "deterministic producer must say where it read the value"
            )


def test_the_anchor_is_reported_even_when_it_cannot_be_verified() -> None:
    """An unverifiable anchor is `UNKNOWN`, and it is still recorded.

    A producer that passes a value the text does not contain must not look like a
    producer that never claimed anything: the two states are *no anchor* and
    *nothing claimed*, and `§6.2` scores them the same while `B.9` requires them
    to read differently.
    """
    text = (
        "FACTURA A\n   Subtotal   IVA 21,0%      TOTAL\n  14.791,98  0,00  14.791,98\n"
    )

    produced = _regexp_candidates(text, DEFAULT_CONFIG)
    subtotal = produced["subtotal"][0]

    anchors = [s for s in subtotal.signals if s.family == "DOCUMENT_CONTENT"]
    assert anchors, "the anchor must be recorded, whatever its verdict"
    assert anchors[0].result == "UNKNOWN", (
        "this value is a column of the row, so the surrounding digits make the "
        "digit-boundary anchor undecidable — measured: `normalize` drops the "
        "spaces and the columns' digits touch (`1479198000`), so the anchor "
        "answers UNKNOWN and the value must lose only the +2, not be dropped"
    )


def test_every_policy_fallback_matches_the_registry_asset() -> None:
    """Each number `config.py` carries equals the policy the registry declares.

    `ADR-009` / `NFR-06a` make these corpus policy with the registry as its only
    source. `config.py` keeps the numbers so the library runs with no registry on
    disk — the one case `read_policy` cannot cover — and that fallback is exactly
    where a silent drift would live: two copies of a threshold agree the day they
    are written.

    The defect this already found is in the names, not the numbers:
    `config.render_dpi` mirrors `diagnosis.min_dpi`, and the flow had called it a
    render target when the registry calls it a floor.
    """
    asset = json.loads(
        (REGISTRY_ROOT.parent / POLICY_ASSET).read_text(encoding="utf-8")
    )

    for attribute, key in POLICY_FALLBACKS.items():
        assert key in asset, (
            f"{attribute!r} mirrors {key!r}, which {POLICY_ASSET} does not "
            f"declare; it declares {sorted(asset)}"
        )
        declared = read_policy(key)
        fallback = getattr(DEFAULT_CONFIG, attribute)
        assert declared == float(fallback), (
            f"{attribute!r} falls back to {fallback!r} while the registry "
            f"declares {key}={declared!r}: the two copies have drifted, and the "
            "registry is the authority"
        )


def test_the_policy_reader_refuses_a_key_the_asset_does_not_declare() -> None:
    """A key absent from a registry that loaded raises, rather than defaulting.

    The asymmetry with a *missing registry* is the point: no registry is a fact
    about the machine, so the caller falls back; a key that is not there in a
    registry that parsed is a misspelling or a policy that moved, and falling
    back would hide the drift this module exists to catch.
    """
    with pytest.raises(KeyError, match="declares no"):
        read_policy("reader.min_chars_typo")


def test_the_policy_reader_refuses_a_non_numeric_policy() -> None:
    """A boolean is not a threshold, even though `bool` is an `int` in Python.

    `reader.correct` is a real key in the asset and it is `false`. Read as a
    number it would be `0.0` — a threshold of zero, silently accepting every
    page the policy meant to gate. `isinstance(True, int)` is `True`, so the
    check has to name the boolean explicitly.
    """
    with pytest.raises(KeyError, match="not a number"):
        read_policy("reader.correct")


def test_the_own_cuit_flag_reaches_the_veto() -> None:
    """A CUIT passed on the command line becomes the setting the veto reads.

    The defect this closes is one of reachability, not of logic: the
    `CUITS_OWN_AS_EMISOR` validator was implemented and tested from the start,
    and **unreachable** — the entry point called `run(document, {})`, so the
    setting never held a value and a receipt the business issued to itself could
    not be vetoed by any invocation. A rule only the tests can trigger is a rule
    the product does not have.

    The digits are what is asserted, because the validator compares digits:
    a caller who types the printed form `20-22087601-3` must get the same veto
    as one who types `20220876013`, or the flag works for half its callers.
    """
    from myflow import (  # pylint: disable=import-outside-toplevel
        _build_parser,
        _settings,
    )

    parser = _build_parser()

    empty = _settings(parser.parse_args(["doc.pdf"]))
    printed = _settings(parser.parse_args(["doc.pdf", "--own-cuit", "20-22087601-3"]))
    digits = _settings(parser.parse_args(["doc.pdf", "--own-cuit", "20220876013"]))

    assert not empty, "a run with no flag must not invent a setting"
    assert printed["own_cuits"] == ["20220876013"]
    assert printed == digits, (
        "the printed and the digit forms are the same business, so they must "
        "produce the same setting"
    )
