"""Mutation harness for the engine invariants (``my_flow.md`` I2/I3/I4/I10).

Each mutation breaks exactly one invariant in the source, runs the invariant
suite, and records which tests failed. A mutation whose failure set does not
contain the test that guards the invariant proves nothing: either the anchor
missed, or the test never exercised the code. A test that only passes when the
code is correct proves nothing (B.16) — this harness is how we prove the
converse, that each test fails when its invariant breaks.

Run with bytecode disabled, so the mutated module is actually re-read:

    python -B tests/poc_flow_v2/mutation_invariants.py
"""

from __future__ import annotations

import pathlib
import subprocess
import sys
import xml.etree.ElementTree as ET

FLOW = pathlib.Path("scripts/poc-flow-v2/flow")
CLIENT = pathlib.Path("scripts/poc-flow-v2/myllmlocal.py")
SUITE = pathlib.Path("tests/poc_flow_v2/test_invariants.py")
SAMPLING_SUITE = pathlib.Path("tests/poc_flow_v2/test_sampling.py")
PENDING_SUITE = pathlib.Path("tests/poc_flow_v2/test_pendientes.py")
CLIENT_SUITE = pathlib.Path("tests/poc_flow_v2/test_myllmlocal.py")

#: (label, file, anchor, replacement, the tests that MUST fail)
MUTATIONS: list[tuple[str, pathlib.Path, str, str, set[str]]] = [
    (
        "I2: merge by raw value instead of normalized, so equal values compete",
        FLOW / "fields.py",
        "        key = candidate.normalized_value",
        "        key = candidate.raw_value",
        {"test_i2_same_normalized_value_merges_into_one_candidate"},
    ),
    (
        "I3: a vetoed candidate is treated as live, so no score compensates",
        FLOW / "fields.py",
        "        return bool(self.hard_refutations)",
        "        return False",
        {"test_i3_a_vetoed_candidate_never_wins"},
    ),
    (
        "I4: sum every PASS in a family, so two signals double-count",
        FLOW / "engine.py",
        "            best_positive[signal.family] = max(\n"
        "                best_positive.get(signal.family, 0), signal.points\n"
        "            )",
        "            best_positive[signal.family] = (\n"
        "                best_positive.get(signal.family, 0) + signal.points\n"
        "            )",
        {"test_i4_two_passes_in_one_family_score_once"},
    ),
    (
        "I10: a missing arithmetic component vetoes instead of answering UNKNOWN",
        FLOW / "validators.py",
        (
            '            "arithmetic needs subtotal, IVA and total; a component '
            'is missing",'
        ),
        "            ARITHMETIC_INCONSISTENT,",
        {"test_i10_an_incomplete_equation_is_unknown_not_fail"},
    ),
    (
        "sampling: the window is never declared, so the runtime's default wins",
        FLOW / "extract.py",
        "    apply_sampling()\n    return OllamaEngine()",
        "    return OllamaEngine()",
        {"test_every_model_call_runs_under_a_declared_window"},
    ),
    (
        "sampling: an operator's exported window is overwritten by the default",
        FLOW / "sampling.py",
        "    if os.environ.get(name):\n        return\n",
        "",
        {"test_an_operators_window_is_not_overwritten"},
    ),
    (
        "I2: the arithmetic alternatives are deduplicated by raw value, not value",
        FLOW / "engine.py",
        "        key = normalize(raw)\n        if key and key not in seen:",
        "        key = raw\n        if key and key not in seen:",
        {
            "test_i2_the_arithmetic_alternatives_are_deduplicated_by_value",
            "test_i2_the_resolution_is_unique_when_a_producer_restates_an_amount",
        },
    ),
    (
        "amounts: the deterministic producer returns values with no anchor",
        FLOW / "extract.py",
        "[_content_signal(printed, text, points)]",
        "[]",
        {
            "test_the_deterministic_producer_anchors_the_values_it_reads",
            "test_the_anchor_is_reported_even_when_it_cannot_be_verified",
        },
    ),
    (
        "arithmetic: the signal is rebuilt from values instead of the combination",
        FLOW / "engine.py",
        "    sub, tax, tot = ctx.arithmetic_combination",
        "    sub, tax, tot = ('', '', '')",
        {
            "test_the_validated_combination_is_the_signal_the_field_earns",
            "test_a_total_in_the_combination_confirms_once_its_anchor_is_present",
        },
    ),
    (
        "arithmetic: a candidate is matched to the combination by raw value",
        FLOW / "engine.py",
        "    if normalize(candidate.raw_value) != normalize(expected):",
        "    if candidate.raw_value != expected:",
        {
            "test_the_validated_combination_is_the_signal_the_field_earns",
        },
    ),
    (
        "arithmetic: the +3 is attached to every total the field offers",
        FLOW / "engine.py",
        "    expected = tax if field == IVA_FIELD else tot\n"
        "    if normalize(candidate.raw_value) != normalize(expected):\n"
        "        return []",
        "    expected = tax if field == IVA_FIELD else tot",
        {
            "test_a_total_outside_the_validated_combination_earns_nothing",
        },
    ),
    (
        "config: the escalate floor is a literal, so the dial is inert",
        FLOW / "engine.py",
        "    elif score < ctx.config.escalate_floor:",
        "    elif score < 2:",
        {"test_the_escalate_floor_dial_decides_the_verdict"},
    ),
    (
        "config: a module imports a dial as a module-level constant",
        FLOW / "engine.py",
        "from .config import (\n    DEFAULT_CONFIG,\n    Config,\n    FieldDial,\n)",
        "from .config import (\n    DEFAULT_CONFIG,\n    ESCALATE_FLOOR,\n"
        "    Config,\n    FieldDial,\n)",
        {"test_no_module_reaches_a_dial_by_importing_it"},
    ),
    (
        "amounts: a label far from every column is paired with the nearest anyway",
        FLOW / "amounts.py",
        "_COLUMN_TOLERANCE: Final[int] = 20",
        "_COLUMN_TOLERANCE: Final[int] = 10_000",
        {"test_a_label_far_from_every_column_is_not_paired"},
    ),
    (
        "amounts: the summed IVA leaves as a float, losing the printed form",
        FLOW / "amounts.py",
        "        amounts[IVA_FIELD] = _printed(sum(_as_float(rate) for rate in rates))",
        "        amounts[IVA_FIELD] = str(sum(_as_float(rate) for rate in rates))",
        {"test_the_reader_output_lets_the_arithmetic_rule_judge"},
    ),
    (
        "amounts: an unidentifiable row yields whatever numbers it finds",
        FLOW / "amounts.py",
        "    if row is None:\n        return {}",
        "    if row is None:\n        return {'subtotal': '0,00'}",
        {"test_the_reader_refuses_a_row_it_cannot_identify"},
    ),
    (
        "policy: a fallback drifts from the registry asset it mirrors",
        FLOW / "config.py",
        '    "render_dpi": "diagnosis.min_dpi",',
        '    "render_dpi": "diagnosis.min_dpi_typo",',
        {"test_every_policy_fallback_matches_the_registry_asset"},
    ),
    (
        "policy: a missing key falls back instead of refusing",
        FLOW / "policy.py",
        "    if key not in values:\n        raise KeyError(",
        "    if key not in values:\n        return 0.0\n    if False:\n"
        "        raise KeyError(",
        {"test_the_policy_reader_refuses_a_key_the_asset_does_not_declare"},
    ),
    (
        "policy: a boolean policy is read as the number 0.0",
        FLOW / "policy.py",
        "    if isinstance(value, bool) or not isinstance(value, (int, float)):",
        "    if not isinstance(value, (int, float)):",
        {"test_the_policy_reader_refuses_a_non_numeric_policy"},
    ),
    (
        "cli: the own-CUIT flag is parsed and then dropped",
        pathlib.Path("scripts/poc-flow-v2/myflow.py"),
        '        settings["own_cuits"] = [',
        '        settings["owncuits"] = [',
        {"test_the_own_cuit_flag_reaches_the_veto"},
    ),
    (
        "probe: a text file is routed to read_material, which calls it invalid",
        CLIENT,
        "    if path.suffix.lower() in TEXT_SUFFIXES:",
        "    if False:",
        {"test_a_text_file_is_read_directly"},
    ),
    (
        "probe: the document's text is substituted with nothing",
        CLIENT,
        "    return template.replace(TEXT_PLACEHOLDER, text)",
        '    return template.replace(TEXT_PLACEHOLDER, "")',
        {"test_the_document_text_reaches_the_model"},
    ),
    (
        "probe: a prompt with no placeholder is sent, so it never carries the text",
        CLIENT,
        "    if TEXT_PLACEHOLDER not in template:",
        "    if False:",
        {"test_a_prompt_without_the_placeholder_is_refused"},
    ),
    (
        "probe: a whitespace-only document reaches the model instead of going aside",
        CLIENT,
        "    if not text.strip():",
        "    if not text:",
        {"test_a_document_with_no_text_never_reaches_a_model"},
    ),
    (
        "probe: a degraded material is reported as a blank page",
        CLIENT,
        "    refused = ESC_DEGRADED_MATERIAL if material.tier == TIER_DEGRADED "
        'else "blank_page"',
        '    refused = "blank_page"',
        {"test_a_degraded_material_names_its_own_reason"},
    ),
    (
        "probe: a typed refusal is reported as a value on the exit code",
        CLIENT,
        '    return EXIT_OK if facts.get("refusal") is None else EXIT_REFUSED',
        "    return EXIT_OK",
        {"test_a_refused_call_is_a_report_and_never_an_exception"},
    ),
    (
        "probe: an unmeasured number is reported as 0.0 instead of None",
        CLIENT,
        '    return None if value is None else float(cast("float", value))',
        '    return 0.0 if value is None else float(cast("float", value))',
        {"test_an_unmeasured_number_stays_none_instead_of_becoming_zero"},
    ),
]


def _run_suite() -> tuple[int, set[str]]:
    """Run the guarded suites and return (exit code, failed test names).

    Every suite runs every time: a mutation's expected failure set names the test
    that must fail, and it does not matter which file that test lives in. Running
    only `test_invariants.py` would leave the sampling mutations' anchors in
    place and their guards unexercised — a mutation whose suite never loads the
    test it expects fails for the wrong reason, and one that expects a test from
    another file could never pass at all.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(SUITE),
            str(SAMPLING_SUITE),
            str(PENDING_SUITE),
            str(CLIENT_SUITE),
            "-q",
            "--tb=no",
            "--junitxml=/tmp/mutation_invariants.xml",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    failed: set[str] = set()
    try:
        root = ET.parse("/tmp/mutation_invariants.xml").getroot()
        for case in root.iter("testcase"):
            if case.find("failure") is not None:
                failed.add(case.get("name", ""))
    except (ET.ParseError, OSError):
        pass
    return result.returncode, failed


def main() -> int:
    """Run every mutation, report whether its guard test failed, restore source."""
    print("mutation  expected failing tests  observed")
    print("-" * 60)
    all_proved = True
    for label, path, anchor, replacement, expected in MUTATIONS:
        original = path.read_text(encoding="utf-8")
        if anchor not in original:
            print(f"ANCHOR MISSING: {label}")
            all_proved = False
            continue
        mutated = original.replace(anchor, replacement, 1)
        path.write_text(mutated, encoding="utf-8")
        try:
            _, failed = _run_suite()
        finally:
            path.write_text(original, encoding="utf-8")

        proved = expected <= failed
        status = "OK" if proved else "NOT PROVED"
        if not proved:
            all_proved = False
        expected_list = ", ".join(sorted(expected))
        failed_list = ", ".join(sorted(failed))
        report = (
            f"{label}\n"
            f"    expects: {expected_list}\n"
            f"    failed:  {failed_list}\n"
            f"    {status}"
        )
        print(report)
    print("-" * 60)
    return 0 if all_proved else 1


if __name__ == "__main__":
    sys.exit(main())
