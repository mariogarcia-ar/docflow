"""Mutation harness for the K2 kernel/adapter split (``E04-02``).

The split moved the vendors out of `docflow/kernels/pdf.py` and into
`docflow/adapters/pdf.py`. What these mutations check is that the *properties* the
split was for are guarded, and that the new ones it introduced are too.

Each entry breaks exactly one property, runs the targeted suites, and records which
tests failed. A mutation whose failure set does not contain the test that guards the
property proves nothing: either the anchor missed, or the test never exercised the
code. Results are read from the JUnit XML, because long test names wrap in stdout
and a failed grep reads as a pass.

Run with bytecode disabled:  python -B tests/adapters/mutation_pdf.py
"""

# Pylint reports `duplicate-code` against the two adapter harnesses. The scaffolding
# is deliberately identical — read the JUnit XML, run one mutation in a subprocess
# with bytecode disabled, restore the file — and that sameness is what makes them
# comparable at a glance. What differs, and is not shared, is the mutation table and
# the files each one touches. Factoring the scaffolding into a helper module is the
# better end state and is not worth a new module in PoC.
# pylint: disable=duplicate-code

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

KERNEL = Path("src/docflow/kernels/pdf.py")
ADAPTER = Path("src/docflow/adapters/pdf.py")
SUITES = ["tests/kernels/test_pdf.py", "tests/kernels/test_pdf_layout_text.py"]

#: (label, file, anchor, replacement, the tests that MUST fail)
MUTATIONS: list[tuple[str, Path, str, str, set[str]]] = [
    (
        "M1: fall back to a substitute reader instead of reporting it missing",
        ADAPTER,
        "        found = shutil.which(_READER_BINARY)\n        if found is None:",
        "        found = shutil.which(_READER_BINARY)\n        if False:",
        {"test_a_missing_reader_binary_is_a_typed_reason_and_not_a_substitute"},
    ),
    (
        "M2: count invisible text as visible, so a stale layer reads as text",
        KERNEL,
        "    visible_text = not facts.invisible_text",
        "    visible_text = True",
        # One test, not two: the pair that guards the invisible-layer rule is
        # `reports_as_evidence` (the detection) plus the shape assertion inside it.
        # The visible-page control checks the *flag*, which this mutation does not
        # change — it changes what the flag is allowed to mean for the shape. Citing
        # it would be citing a test that cannot fail here.
        {"test_classify_reports_an_invisible_text_layer_as_evidence"},
    ),
    (
        "M3: upscale a scan instead of refusing the resolution",
        KERNEL,
        "        if measured is not None and measured < dpi:",
        "        if False:",
        {"test_render_refuses_a_resolution_the_source_cannot_supply"},
    ),
    (
        "M4: collapse blank into a page with no text",
        KERNEL,
        '    if facts.is_blank:\n        return "blank"',
        '    if facts.is_blank:\n        return "image"',
        {"test_classify_reports_a_blank_page_as_blank_not_as_a_textless_page"},
    ),
    (
        "M5: coerce an absent confidence to a perfect one",
        KERNEL,
        '        confidence=None,\n        role="text",',
        '        confidence=1.0,\n        role="text",',
        {"test_extract_tokens_reports_no_confidence_rather_than_perfect_confidence"},
    ),
    (
        "M6: drop the coordinate conversion and report the reader's units",
        KERNEL,
        "    scale = dpi / POINTS_PER_INCH",
        "    scale = 1.0",
        {"test_extract_tokens_scales_boxes_to_the_requested_resolution"},
    ),
    (
        "M7: let a reordered selection produce the reader's concatenation",
        KERNEL,
        "    if list(selection) != list(pages):",
        "    if False:",
        {"test_a_reordered_selection_is_refused_rather_than_silently_sorted"},
    ),
    (
        "M8: take the blank decision in a second place besides _shape_of",
        KERNEL,
        '    if shape == "blank":',
        '    if shape == "blank" and False:',
        {"test_classify_reports_a_blank_page_as_blank_not_as_a_textless_page"},
    ),
    (
        "M9: accept an empty selection by widening it to the document",
        KERNEL,
        "    if not pages:",
        "    if not pages and False:",
        {
            "test_an_empty_selection_is_refused",
            "test_extract_tokens_refuses_an_empty_selection",
        },
    ),
    (
        "M10: let a duplicate page through and duplicate content",
        KERNEL,
        "        if len(set(pages)) != len(pages):",
        "        if False:",
        {"test_split_refuses_a_repeated_page"},
    ),
    (
        "M11: report a missing reader as a successful empty extraction",
        KERNEL,
        "    except PdfVendorError as refused:\n"
        "        return _refused(refused, terms)\n"
        "\n"
        "    scale = dpi / POINTS_PER_INCH",
        "    except PdfVendorError:\n"
        "        words_by_page = {}\n"
        "\n"
        "    scale = dpi / POINTS_PER_INCH",
        {"test_a_missing_reader_binary_is_a_typed_reason_and_not_a_substitute"},
    ),
    (
        "M12: split without preserving the source page sizes",
        KERNEL,
        '            "result_page_sizes": [list(size) for size in cut.page_sizes],',
        '            "result_page_sizes": [[0.0, 0.0] for _ in cut.page_sizes],',
        {"test_split_preserves_the_page_count_and_boxes_of_the_range"},
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
    """Build a child environment that reaches no network and writes no bytecode.

    Returns:
        The environment.

    """
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PATH"] = "/opt/homebrew/bin:" + env.get("PATH", "")
    return env


def main() -> int:
    """Run every mutation and report whether it was falsified.

    Returns:
        The process exit code: 0 when every mutation was caught.

    """
    originals = {
        KERNEL: KERNEL.read_text(encoding="utf-8"),
        ADAPTER: ADAPTER.read_text(encoding="utf-8"),
    }
    survivors: list[str] = []

    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "report.xml"
        for label, target, anchor, replacement, expected in MUTATIONS:
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
                    *SUITES,
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
