"""Mutation harness for resolution by capability (``E04-07``, ``S1-T17``).

The invariant is **"there is no fallback"**, and `plan-01-kernels.md` §7b says its test
must FAIL when the invariant breaks. This harness is what establishes that the tests in
`tests/kernels/test_resolution.py` are falsifiable rather than merely green: each entry
below breaks exactly one property, runs the suite, and records which tests failed.

The properties worth breaking here, in the order they would hurt:

- **a bad name does not resolve.** Replacing the refusal with anything that returns a
  value is the silent fallback itself, and it is the one mutation that must never
  survive.
- **the refusal is a ``Reason``, not an exception.** A raise would reach exit `1`
  instead of exit `3`, collapsing *"this name is wrong"* into *"the code has a bug"*.
- **the name style is per-family.** Collapsing the two styles into one rule makes one
  of the two adapters answer about a model it does not have - and the wrong model is
  worse than no answer.
- **the kernel, the operation and the binding are all checked.** Dropping any of the
  three lets a call resolve to an engine that cannot serve it.
- **the seven terms are composed, not defaulted.** A dropped term is an absent term.

Results are read from the JUnit XML rather than stdout, because long test names wrap and
a failed grep reads as a pass. Run with bytecode disabled:

    python -B tests/kernels/mutation_resolution.py

A mutation whose expected-failure set is not met proves nothing: either the anchor
missed (`[SKIP]`) or the test never exercised the code. Both are printed, and neither is
counted as proven. **A parametrized test's name needs its suffix.**
"""

# Pylint reports `duplicate-code` against the other mutation harnesses. The scaffolding
# is deliberately identical - read the JUnit XML, run one mutation in a subprocess with
# bytecode disabled, restore the file - and that sameness is what makes them comparable
# at a glance. What differs is the mutation table and the file each one touches.
# pylint: disable=duplicate-code
# An anchor is a literal fragment of the source it mutates, so it cannot be wrapped
# without changing what it matches. The line ceiling does not apply to them.
# pylint: disable=line-too-long

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

RESOLUTION = Path("src/docflow/kernels/resolution.py")
SUITES = "tests/kernels/test_resolution.py"

#: (label, anchor, replacement, the tests that MUST fail)
MUTATIONS: list[tuple[str, str, str, set[str]]] = [
    (
        "M1: skip the prefixless-name refusal, so a bare name falls through",
        "    if capability is None and prefix is None:",
        "    if False:",
        {"test_a_bare_name_fails_with_model_unknown"},
    ),
    (
        "M2: skip the unknown-family refusal in the routing checks",
        '    if capability is None:\n        return _refused(\n            "provider_unknown",',
        '    if False and capability is None:\n        return _refused(\n            "provider_unknown",',
        {"test_an_unknown_provider_fails_with_provider_unknown"},
    ),
    (
        "M3: substitute a default family for an unknown prefix",
        '    return known.get(match.group("family"))',
        '    return known.get(match.group("family")) or known["ollama"]',
        {"test_an_unknown_provider_fails_with_provider_unknown"},
    ),
    (
        "M4: guess a family for a prefixless name",
        '    match = _FAMILY.match(model.strip())\n    if match is None:\n        return None\n\n    return known.get(match.group("family"))',
        '    match = _FAMILY.match(model.strip())\n    if match is None:\n        return known["ollama"]\n\n    return known.get(match.group("family"))',
        {"test_a_bare_name_fails_with_model_unknown"},
    ),
    (
        "M5: raise the refusal instead of returning a Reason",
        '    if capability is None and prefix is None:\n        return _refused(\n            "model_unknown",',
        '    if capability is None and prefix is None:\n        _refused(\n            "model_unknown",',
        {"test_a_bare_name_fails_with_model_unknown"},
    ),
    (
        "M6: forward every name as written, ignoring the family's style",
        "    if capability.answers_to == ANSWERS_TO_BARE:\n        return bare",
        "    if capability.answers_to == ANSWERS_TO_BARE:\n        return model.strip()",
        {"test_the_local_adapter_is_asked_for_the_bare_name"},
    ),
    (
        "M7: prefix every name, ignoring the family's style",
        "    if capability.answers_to == ANSWERS_TO_BARE:\n        return bare",
        "    if False:\n        return bare",
        {"test_the_local_adapter_is_asked_for_the_bare_name"},
    ),
    (
        "M8: stop checking the kernel a family belongs to",
        "    if capability.kernel != request.kernel:",
        "    if False:",
        {"test_a_name_resolving_to_another_kernel_is_refused"},
    ),
    (
        "M9: stop checking the operation a family serves",
        "    if request.operation not in capability.operations:",
        "    if False:",
        {"test_an_operation_a_family_does_not_serve_is_refused"},
    ),
    (
        "M10: resolve a family that has no bound engine",
        "    if capability.family not in request.engines:",
        "    if False:",
        {"test_a_declared_family_with_no_bound_engine_is_refused"},
    ),
    (
        "M11: rewrite an adapter's own refusal code",
        "        return KernelResult(\n            value=None, evidence=reported.evidence, reason=reported.reason\n        )",
        '        return KernelResult(\n            value=None,\n            evidence=reported.evidence,\n            reason=Reason(code="model_unknown", message="rewritten"),\n        )',
        {"test_the_adapters_own_reason_is_forwarded_not_rewritten"},
    ),
    (
        "M12: report the tag as the model revision",
        '        model_revision=str(observed["model_revision"]),',
        '        model_revision=str(observed["model"]),',
        {"test_a_local_model_resolves_and_reports_its_digest"},
    ),
    (
        "M13: drop the adapter revision from the resolution",
        '            "adapter_revision": resolved.adapter_revision,',
        '            "adapter_revision": "unknown",',
        {"test_the_evidence_terms_carry_the_revisions_the_report_claims"},
    ),
    (
        "M14: substitute a registry hash constant in resolve_with_registry",
        "        registry_hash=registry_kernel.registry_hash(loaded.value),",
        '        registry_hash="dead" * 16,',
        {"test_resolve_with_registry_reads_the_hash_from_k8"},
    ),
    (
        "M15: return an empty params mapping rather than the reported one",
        "    return MappingProxyType({str(key): str(value) for key, value in raw.items()})",
        "    return MappingProxyType({})",
        {"test_resolution_reports_the_engine_revision_and_the_parameters"},
    ),
    (
        "M16: add a default parameter to a public entry point",
        "def resolve_with_registry(\n    request: Request,\n    *,",
        'def resolve_with_registry(\n    request: Request,\n    *,\n    fallback: str = "ollama",',
        {"test_the_public_surface_exposes_no_parameter_with_a_default"},
    ),
    (
        "M17: declare Docling as a capability family",
        'CAPABILITIES: tuple[Capability, ...] = (\n    Capability(\n        family="ollama",',
        'CAPABILITIES: tuple[Capability, ...] = (\n    Capability(\n        family="docling",\n        kernel="ocr",\n        answers_to=ANSWERS_TO_BARE,\n        operations=frozenset({OPERATION_VISION}),\n    ),\n    Capability(\n        family="ollama",',
        {"test_the_declared_table_is_the_whole_registry"},
    ),
    (
        "M18: read the environment for a model",
        "import dataclasses\nimport re",
        "import dataclasses\nimport os\nimport re",
        {"test_os_is_not_imported"},
    ),
]


def purge_bytecode() -> None:
    """Delete every ``__pycache__`` tree under ``src`` and ``tests``.

    A stale ``.pyc`` reused by the next subprocess makes the harness report a
    one-mutation lag - a false verdict in both directions.
    """
    for root in (Path("src"), Path("tests")):
        for cache in root.rglob("__pycache__"):
            shutil.rmtree(cache, ignore_errors=True)


def run(report: Path) -> set[str]:
    """Run the suite and return the names of the tests that failed.

    Args:
        report: Where to write the JUnit XML.

    Returns:
        The failed tests' names, including a collection error under its module node.

    """
    environment = {
        "PYTHONDONTWRITEBYTECODE": "1",
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
    }
    completed = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "pytest",
            SUITES,
            "-q",
            f"--junit-xml={report}",
            "-p",
            "no:cacheprovider",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**environment},
    )
    if not report.exists():
        raise RuntimeError(
            f"pytest produced no report:\n{completed.stdout}\n{completed.stderr}"
        )

    tree = ET.parse(report)
    return {
        str(node.get("name"))
        for node in tree.iter("testcase")
        if node.find("failure") is not None or node.find("error") is not None
    }


def main() -> int:
    """Run every mutation, restore the source, and report which were caught.

    Returns:
        0 when every mutation is caught, 1 otherwise.

    """
    survivors: list[str] = []
    with tempfile.TemporaryDirectory() as directory:
        report = Path(directory) / "report.xml"
        for label, anchor, replacement, must_fail in MUTATIONS:
            purge_bytecode()
            original = RESOLUTION.read_text(encoding="utf-8")

            if anchor not in original:
                print(f"[SKIP] {label}: anchor not found")
                survivors.append(label)
                continue
            if anchor == replacement:
                print(f"[SKIP] {label}: anchor and replacement are identical")
                survivors.append(label)
                continue

            try:
                RESOLUTION.write_text(
                    original.replace(anchor, replacement, 1), encoding="utf-8"
                )
                failed = run(report)
            finally:
                RESOLUTION.write_text(original, encoding="utf-8")

            caught = must_fail <= failed
            print(f"[{'caught' if caught else 'SURVIVED'}] {label}")
            print(f"    expected to fail: {sorted(must_fail)}")
            print(f"    actually failed:  {sorted(failed)}")
            if not caught:
                survivors.append(label)

    purge_bytecode()
    print()
    if survivors:
        print(f"{len(survivors)} of {len(MUTATIONS)} mutations SURVIVED:")
        for label in survivors:
            print(f"  - {label}")
        return 1

    print(f"All {len(MUTATIONS)} mutations caught.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
