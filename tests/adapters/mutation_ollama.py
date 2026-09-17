"""Mutation harness for the Ollama adapter's invariants (E04-05).

Each entry breaks exactly one invariant in the source, runs the targeted suite, and
records which tests failed. A mutation whose failure set does not contain the test
that guards the invariant proves nothing: either the anchor missed, or the test never
exercised the code. Results are read from the JUnit XML, because the suite's long
test names wrap in stdout and a failed grep reads as a pass.

Run with the OLLAMA DISABLED so the live test never masks a mutation:

    python mutation_ollama.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

SOURCE = Path("src/docflow/adapters/ollama.py")
SUITE = "tests/adapters/test_ollama.py"

#: (label, anchor, replacement, the tests that MUST fail)
MUTATIONS: list[tuple[str, str, str, set[str]]] = [
    (
        "M1: report the tag as the identity instead of the digest",
        '                "model_revision": digest,\n'
        '                "first_seen_revision": first,',
        '                "model_revision": model,\n'
        '                "first_seen_revision": first,',
        {
            "test_the_digest_is_reported_and_the_tag_is_marked_moving",
            "test_the_digest_is_not_the_tag",
        },
    ),
    (
        "M2: treat a cut generation as a complete one (parse it)",
        "if done_reason == _DONE_REASON_LENGTH:",
        "if done_reason == _DONE_REASON_LENGTH + '_never':",
        {"test_a_cut_generation_is_truncated_and_never_parsed"},
    ),
    (
        "M3: substitute a default model when the name resolves to nothing",
        '            if name.partition(":")[0] == bare:\n'
        '                return str(entry.get("digest", ""))\n'
        "\n"
        "        return None",
        '            if name.partition(":")[0] == bare:\n'
        '                return str(entry.get("digest", ""))\n'
        "\n"
        '        return str(catalogue[0].get("digest", ""))',
        {
            "test_an_absent_model_is_a_typed_reason_naming_the_remedy",
            "test_no_default_model_is_substituted_for_an_absent_one",
        },
    ),
    (
        "M4: drop the self-grading guard",
        "if produced_by and _same_model(model, produced_by):",
        "if False and _same_model(model, produced_by):",
        {"test_a_model_grading_its_own_output_is_refused"},
    ),
    (
        "M5: compare model names without ignoring the tag",
        'return left.split(":")[0].strip() == right.split(":")[0].strip()',
        "return left.strip() == right.strip()",
        {"test_the_self_grading_guard_ignores_the_tag"},
    ),
    (
        "M6: stop reporting an unreachable runtime as a typed reason",
        "except (ConnectionError, ValueError) as exc:",
        "except (ValueError,) as exc:  # pylint: disable=broad-exception-caught",
        {"test_a_runtime_that_is_down_is_a_typed_reason"},
    ),
    (
        "M7: drop the raw completion from the evidence",
        '"raw_completion": raw,',
        '"raw_completion": "",',
        {"test_the_raw_completion_is_preserved_on_both_outcomes"},
    ),
    (
        "M8: grow an operation the port does not declare",
        "    def warm(self, model: str) -> KernelResult[Evidence]:",
        "    def engine_info(self, model: str) -> KernelResult[Evidence]:\n"
        '        """A surface the port does not declare."""\n'
        "        return self.capabilities(model)\n"
        "\n"
        "    def warm(self, model: str) -> KernelResult[Evidence]:",
        {"test_the_adapter_exposes_the_ports_five_operations_and_no_more"},
    ),
    (
        "M9: stop comparing the digest after the first sighting",
        "first = self._seen_digests.setdefault(bare, digest)\n"
        "        changed = first != digest",
        "first = digest\n"
        "        self._seen_digests[bare] = first\n"
        "        changed = False",
        {"test_a_mid_run_swap_is_visible_as_a_difference"},
    ),
    (
        "M10: never report the loaded context length",
        "        for entry in loaded:\n"
        '            if str(entry.get("digest", "")) == digest:',
        "        for entry in []:  # pylint: disable=use-list-literal\n"
        '            if str(entry.get("digest", "")) == digest:',
        {"test_num_ctx_is_reported_when_the_model_is_loaded"},
    ),
    (
        "M11: drop num_ctx, params and the adapter revision from the evidence",
        '            "adapter_revision": revision,\n'
        '            "num_ctx": num_ctx,\n'
        '            "params": dict(_options_from_environment()),\n',
        "",
        {"test_the_evidence_reports_num_ctx_params_and_the_adapter_revision"},
    ),
    (
        "M12: warm with a different window than a real call will use",
        '"options": {**dict(_options_from_environment()), "num_predict": 1},',
        '"options": {"num_predict": 1},',
        {"test_warm_offers_the_same_options_a_real_call_will_send"},
    ),
    (
        "M13: read num_ctx before the call, reporting a stale window",
        '        bare = model.strip().partition(":")[0]\n'
        "        num_ctx = self._effective_context_length(bare, digest)",
        '        bare = model.strip().partition(":")[0]\n'
        '        num_ctx = spec.value.observed["num_ctx"]',
        {"test_num_ctx_is_the_window_this_call_loaded_the_model_at"},
    ),
    (
        "M14: stop recording how much prompt was sent",
        '            "prompt_characters": float(prompt_characters),\n',
        "",
        {
            "test_the_prompt_measurement_is_recorded_so_silent_input_truncation_is"
            "_visible"
        },
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
    """Build a child environment that cannot reach a live runtime.

    Returns:
        The environment.

    """
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PATH"] = "/opt/homebrew/bin:" + env.get("PATH", "")
    # Silence the live class: a mutation must be caught by the stubbed suite, and a
    # runtime that happens to be up would otherwise change what is exercised.
    env["DOCFLOW_OLLAMA_HOST"] = "http://127.0.0.1:9"
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
