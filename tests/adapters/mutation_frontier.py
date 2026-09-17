"""Mutation harness for the frontier adapter's invariants (E04-06).

Each entry breaks exactly one invariant in the source, runs the targeted suite, and
records which tests failed. A mutation whose failure set does not contain the test
that guards the invariant proves nothing: either the anchor missed, or the test never
exercised the code. Results are read from the JUnit XML, because the suite's long test
names wrap in stdout and a failed grep reads as a pass.

Run with no provider key in the environment, so a live path never masks a mutation:

    python tests/adapters/mutation_frontier.py
"""

# Pylint reports `duplicate-code` between this harness and K5's. The scaffolding is
# deliberately identical — read the JUnit XML, run one mutation in a subprocess with
# bytecode disabled, restore the source — and that sameness is what makes the two
# harnesses comparable at a glance. What differs, and is not shared, is the mutation
# table and the environment each needs. Factoring the scaffolding into a helper module
# would be the better end state, and it is not worth a new module in PoC.
# pylint: disable=duplicate-code

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

SOURCE = Path("src/docflow/adapters/frontier.py")
SUITE = "tests/adapters/test_frontier.py"

#: (label, anchor, replacement, the tests that MUST fail)
MUTATIONS: list[tuple[str, str, str, set[str]]] = [
    (
        "M1: capture the raw completion only after the parse",
        "        self._last_raw_completion = _raw_bytes(response)\n"
        "\n"
        "        # A 200 whose body is not JSON",
        "        # A 200 whose body is not JSON",
        {"test_a_200_with_a_non_json_body_is_a_typed_reason"},
    ),
    (
        "M2: drop the raw completion entirely",
        "        self._last_raw_completion = _raw_bytes(response)\n"
        "\n"
        "        # A 200 whose body is not JSON",
        "        # A 200 whose body is not JSON",
        {
            "test_the_raw_completion_is_kept_on_success",
            "test_a_200_with_a_non_json_body_is_a_typed_reason",
        },
    ),
    (
        "M3: drop the outcome label that separates absence from null",
        '        observed["outcome"] = outcome',
        '        observed["outcome"] = "value" if outcome else outcome',
        {"test_an_absent_answer_is_reported_as_absent"},
    ),
    (
        "M4: collapse a null answer into a value",
        '        if outcome == "null":',
        '        if outcome == "null" and False:',
        {"test_a_null_field_is_reported_as_null_and_not_as_absent"},
    ),
    (
        "M5: reinterpret the imposed retry delay",
        "            retry_after = headers.get(_HEADER_RETRY_AFTER)",
        "            retry_after = 5",
        {"test_a_429_records_the_imposed_delay_verbatim"},
    ),
    (
        "M6: report an outage as a rejection of the document",
        "                _CODE_PROVIDER_UNAVAILABLE,\n                str(exc),",
        "                _CODE_UNSUPPORTED_FORMAT,\n                str(exc),",
        {"test_an_outage_is_never_reported_as_a_rejection"},
    ),
    (
        "M7: substitute a default provider for an unknown prefix",
        "        if prefix != _PROVIDER:",
        "        if False:",
        {"test_an_unknown_provider_prefix_is_refused"},
    ),
    (
        "M8: drop the self-grading guard",
        "        if produced_by and _same_model(model, produced_by):",
        "        if False and _same_model(model, produced_by):",
        {"test_a_model_grading_its_own_output_is_refused"},
    ),
    (
        "M9: compare model names without ignoring the provider prefix",
        "    return _split_model(left)[1].strip() == _split_model(right)[1].strip()",
        "    return left.strip() == right.strip()",
        {"test_the_self_grading_guard_ignores_the_provider_prefix"},
    ),
    (
        "M10: stop recording the call, so a failure looks like no call",
        "    def _record(  # pylint: disable=too-many-arguments",
        "    def _never_record(  # pylint: disable=too-many-arguments",
        {"test_the_call_record_is_populated_on_a_typed_failure"},
    ),
    (
        "M11: report an unreported token count as zero",
        "            prompt_tokens=int(prompt) if isinstance(prompt, int) else None,",
        "            prompt_tokens=int(prompt) if isinstance(prompt, int) else 0,",
        {"test_unreported_tokens_are_none_and_never_zero"},
    ),
    (
        "M12: report the model name as its revision on a failed call",
        '            "model_revision": "unresolved",',
        '            "model_revision": name,',
        {"test_a_failed_call_reports_an_unresolved_model_revision"},
    ),
    (
        "M13: parse past a maximum-token stop",
        "        if stop_reason == _STOP_REASON_MAX_TOKENS:",
        "        if stop_reason == _STOP_REASON_MAX_TOKENS + '_never':",
        {"test_a_max_tokens_stop_is_truncated_and_never_parsed"},
    ),
    (
        "M14: substitute a ceiling when the environment declares none",
        '    raw = os.environ.get("DOCFLOW_FRONTIER_MAX_TOKENS")\n    if raw is None:',
        "    raw = os.environ.get(\"DOCFLOW_FRONTIER_MAX_TOKENS\", '1024')\n"
        "    if raw is None:",
        {"test_a_missing_ceiling_is_a_typed_reason_not_a_crash"},
    ),
]


def _failed_tests(xml_path: Path) -> set[str]:
    """Read the names of failing tests from a JUnit report.

    Args:
        xml_path: The report.

    Returns:
        The failing test names, without their class or module prefix.

    """
    root = ET.parse(xml_path).getroot()
    failed: set[str] = set()
    for case in root.iter("testcase"):
        if any(child.tag in {"failure", "error"} for child in case):
            failed.add(case.get("name", ""))
    return failed


def _environment() -> dict[str, str]:
    """Build a child environment with no provider reachable.

    Returns:
        The environment.

    """
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PATH"] = "/opt/homebrew/bin:" + env.get("PATH", "")
    # No key and a dead host: a mutation must be caught by the stubbed suite, and a
    # live provider would otherwise change what is exercised.
    env.pop("DOCFLOW_FRONTIER_KEY", None)
    env.pop("ANTHROPIC_API_KEY", None)
    env["DOCFLOW_FRONTIER_HOST"] = "http://127.0.0.1:9"
    return env


def main() -> int:
    """Run every mutation and report whether it was falsified.

    Returns:
        The process exit code: 0 when every mutation was caught.

    """
    original = SOURCE.read_text(encoding="utf-8")
    survivors: list[str] = []

    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "report.xml"
        for label, anchor, replacement, expected in MUTATIONS:
            if anchor not in original:
                print(f"[SKIP] {label}\n       anchor not found — nothing was proved")
                survivors.append(label)
                continue

            SOURCE.write_text(
                original.replace(anchor, replacement, 1), encoding="utf-8"
            )
            shutil.rmtree("__pycache__", ignore_errors=True)
            subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "-m",
                    "pytest",
                    SUITE,
                    "-q",
                    "--no-header",
                    "-p",
                    "no:cacheprovider",
                    f"--junit-xml={report}",
                ],
                env=_environment(),
                check=False,
                capture_output=True,
                text=True,
            )
            observed = _failed_tests(report)
            SOURCE.write_text(original, encoding="utf-8")

            caught = expected & observed
            missed = expected - observed
            verdict = "FALSIFIED" if not missed else "SURVIVED"
            print(f"[{verdict}] {label}")
            for name in sorted(caught):
                print(f"           caught by {name}")
            for name in sorted(missed):
                print(f"           NOT caught by {name}")
            if missed or not caught:
                survivors.append(label)

    print()
    if survivors:
        print(f"{len(survivors)} of {len(MUTATIONS)} mutations were NOT falsified:")
        for label in survivors:
            print(f"  - {label}")
        return 1

    print(f"all {len(MUTATIONS)} mutations falsified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
