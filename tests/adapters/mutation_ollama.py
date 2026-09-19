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

#: Where the answer-shaped helpers moved when `ollama.py` reached Pylint's line cap.
#: Two mutations below anchor here, and they are not optional: the self-grading guard
#: and the tag-stripping comparison live in this file, so a harness that could only
#: mutate `ollama.py` would report the two of them as `SKIP` — which reads identically
#: to a mutation that was never written, and leaves two invariants unguarded in
#: silence. That is precisely the failure mode these harnesses exist to prevent.
RESULTS = Path("src/docflow/adapters/ollama_results.py")

#: (label, anchor, replacement, the tests that MUST fail, the file the anchor is in)
MUTATIONS: list[tuple[str, str, str, set[str], Path]] = [
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
        SOURCE,
    ),
    (
        "M2: treat a cut generation as a complete one (parse it)",
        "if done_reason == _DONE_REASON_LENGTH:",
        "if done_reason == _DONE_REASON_LENGTH + '_never':",
        {"test_a_cut_generation_is_truncated_and_never_parsed"},
        SOURCE,
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
        SOURCE,
    ),
    (
        "M4: drop the self-grading guard",
        "if produced_by and ollama_results.same_model(model, produced_by):",
        "if False and ollama_results.same_model(model, produced_by):",
        {"test_a_model_grading_its_own_output_is_refused"},
        SOURCE,
    ),
    (
        "M5: compare model names without ignoring the tag",
        'return left.split(":")[0].strip() == right.split(":")[0].strip()',
        "return left.strip() == right.strip()",
        {"test_the_self_grading_guard_ignores_the_tag"},
        RESULTS,
    ),
    (
        "M6: stop reporting an unreachable runtime as a typed reason",
        "except (ConnectionError, ValueError) as exc:",
        "except (ValueError,) as exc:  # pylint: disable=broad-exception-caught",
        {"test_a_runtime_that_is_down_is_a_typed_reason"},
        SOURCE,
    ),
    (
        "M7: drop the raw completion from the evidence",
        '"raw_completion": raw,',
        '"raw_completion": "",',
        {"test_the_raw_completion_is_preserved_on_both_outcomes"},
        SOURCE,
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
        SOURCE,
    ),
    (
        "M9: stop comparing the digest after the first sighting",
        "first = self._seen_digests.setdefault(bare, digest)\n"
        "        changed = first != digest",
        "first = digest\n"
        "        self._seen_digests[bare] = first\n"
        "        changed = False",
        {"test_a_mid_run_swap_is_visible_as_a_difference"},
        SOURCE,
    ),
    (
        "M10: never report the loaded context length",
        "        for entry in loaded:\n"
        '            if str(entry.get("digest", "")) == digest:',
        "        for entry in []:  # pylint: disable=use-list-literal\n"
        '            if str(entry.get("digest", "")) == digest:',
        {"test_num_ctx_is_reported_when_the_model_is_loaded"},
        SOURCE,
    ),
    (
        "M11: drop num_ctx, params and the adapter revision from the evidence",
        '            "adapter_revision": revision,\n'
        '            "num_ctx": num_ctx,\n'
        '            "params": dict(_options_from_environment()),\n',
        "",
        {"test_the_evidence_reports_num_ctx_params_and_the_adapter_revision"},
        SOURCE,
    ),
    (
        "M12: warm with a different window than a real call will use",
        '"options": {**dict(_options_from_environment()), "num_predict": 1},',
        '"options": {"num_predict": 1},',
        {"test_warm_offers_the_same_options_a_real_call_will_send"},
        SOURCE,
    ),
    (
        "M13: read num_ctx before the call, reporting a stale window",
        '        bare = model.strip().partition(":")[0]\n'
        "        num_ctx = self._effective_context_length(bare, digest)",
        '        bare = model.strip().partition(":")[0]\n'
        '        num_ctx = spec.value.observed["num_ctx"]',
        {"test_num_ctx_is_the_window_this_call_loaded_the_model_at"},
        SOURCE,
    ),
    (
        "M14: stop recording how much prompt was sent",
        '            "prompt_characters": float(prompt_characters),\n',
        "",
        {
            "test_the_prompt_measurement_is_recorded_so_silent_input_truncation_is"
            "_visible"
        },
        SOURCE,
    ),
    (
        # Restores the defect measured on this path: with no instruction saying the
        # grade is JSON, the runtime **echoes the samples back**, the parser accepts
        # the object, and the call reports a *value* — the grade is the thing being
        # graded. Nothing can fail here, which is why only a prompt-level test can
        # catch it.
        "M15: judge without stating in words that the grade is JSON",
        "        payload = (\n"
        '            f"{rubric}\\n\\n"\n'
        '            f"{JSON_ANSWER_INSTRUCTION}\\n\\n"\n'
        '            f"{json.dumps(list(samples), ensure_ascii=False)}"\n'
        "        )",
        '        payload = f"{rubric}\\n\\n" + json.dumps(list(samples),'
        " ensure_ascii=False)",
        {
            "test_judge_asks_for_the_answer_in_json_and_not_only_in_the_schema",
            "test_the_judge_instruction_does_not_replace_the_rubric_or_the_samples",
        },
        SOURCE,
    ),
    (
        "M16: send the JSON instruction in place of the rubric",
        "        payload = (\n"
        '            f"{rubric}\\n\\n"\n'
        '            f"{JSON_ANSWER_INSTRUCTION}\\n\\n"\n'
        '            f"{json.dumps(list(samples), ensure_ascii=False)}"\n'
        "        )",
        "        payload = (\n"
        '            f"{JSON_ANSWER_INSTRUCTION}\\n\\n"\n'
        '            f"{json.dumps(list(samples), ensure_ascii=False)}"\n'
        "        )",
        {"test_the_judge_instruction_does_not_replace_the_rubric_or_the_samples"},
        SOURCE,
    ),
    (
        # Restores the defect the silent failure came from: the adapter dropped the
        # caller's schema and sent `{"type": "object"}`. Measured on this runtime, the
        # consequence was not an error — the model **echoed the samples back**, the
        # echo parsed as an object, and the call reported a *value*. Nothing could
        # fail, because all a parser can check is that the answer is an object.
        "M17: substitute an empty schema for the caller's grade shape",
        "        return self.structured(model, payload, schema)",
        '        return self.structured(model, payload, {"type": "object"})',
        {"test_judge_sends_the_schema_it_was_given"},
        SOURCE,
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


def _targets() -> set[Path]:
    """Return every source file the mutation table anchors in.

    Derived from the table rather than listed by hand, so adding a mutation in a new
    file cannot silently skip its restore step.

    Returns:
        The paths a mutation may modify.

    """
    return {target for *_rest, target in MUTATIONS}


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
    # Every file a mutation anchors in is read once up front and restored byte for
    # byte after each run. Restoring only `SOURCE` would leave a mutated
    # `ollama_results.py` on disk after the first run that touched it, and the next
    # mutation would then be measured against a source that is already broken.
    originals = {path: path.read_text(encoding="utf-8") for path in {*_targets()}}
    survivors: list[str] = []

    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "report.xml"
        for label, anchor, replacement, expected, target in MUTATIONS:
            original = originals[target]
            if anchor not in original:
                print(f"[SKIP] {label}\n       anchor not found — nothing was proved")
                survivors.append(label)
                continue

            target.write_text(
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
            target.write_text(original, encoding="utf-8")

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
