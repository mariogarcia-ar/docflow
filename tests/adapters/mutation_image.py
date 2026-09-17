"""Mutation harness for the K3 kernel/adapter split (``E04-03``).

The split moved Pillow out of `docflow/kernels/image.py` and into
`docflow/adapters/image.py`. What these mutations check is that the properties the
kernel exists for are guarded, and that the new ones the split introduced are too.

Each entry breaks exactly one property, runs the targeted suite, and records which
tests failed. A mutation whose failure set does not contain the test that guards the
property proves nothing: either the anchor missed, or the test never exercised the
code. Results are read from the JUnit XML, because long test names wrap in stdout and
a failed grep reads as a pass.

Run with bytecode disabled:  python -B tests/adapters/mutation_image.py
"""

# Pylint reports `duplicate-code` against the other adapter harnesses. The scaffolding
# is deliberately identical — read the JUnit XML, run one mutation in a subprocess with
# bytecode disabled, restore the file — and that sameness is what makes them comparable
# at a glance. What differs, and is not shared, is the mutation table and the files each
# one touches. Factoring the scaffolding into a helper module is the better end state
# and is not worth a new module in PoC.
# pylint: disable=duplicate-code
# An anchor is a literal fragment of the source it mutates, so it cannot be wrapped
# without changing what it matches. The line ceiling does not apply to them.
# pylint: disable=line-too-long

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

KERNEL = Path("src/docflow/kernels/image.py")
ADAPTER = Path("src/docflow/adapters/image.py")
SUITES = ["tests/kernels/test_image.py", "tests/adapters/test_image.py"]

#: (label, file, anchor, replacement, the tests that MUST fail)
MUTATIONS: list[tuple[str, Path, str, str, set[str]]] = [
    (
        "M1: substitute a stand-in engine instead of refusing",
        ADAPTER,
        "        except ImportError as exc:",
        "        except ImportError:",
        {"test_a_missing_library_is_a_typed_refusal_not_an_import_error"},
    ),
    (
        "M2: report an orientation as applied when nothing was declared",
        KERNEL,
        "    if orientation is None:\n        return False",
        "    if orientation is None:\n        return True",
        {"test_info_reports_no_orientation_on_an_upright_image"},
    ),
    (
        "M3: treat the already-upright value as a rotation",
        KERNEL,
        "    return orientation != EXIF_UPRIGHT",
        "    return True",
        # The *declared-upright* case, not the absent-tag one: an absent tag is
        # caught by M2, and this mutation only changes what a present tag means.
        {"test_an_image_declaring_itself_upright_reports_no_rotation"},
    ),
    (
        "M4: stop applying the orientation, leaving a sideways photo readable",
        KERNEL,
        "    return vendor.upright(frame)",
        "    return frame",
        {"test_load_applies_the_orientation_before_the_bytes_leave"},
    ),
    (
        "M5: report the orientation as applied without applying it",
        KERNEL,
        "    applied = _orientation_to_apply(orientation)\n    upright = _upright(vendor, frame)",
        "    applied = _orientation_to_apply(orientation)\n    upright = frame",
        {"test_load_applies_the_orientation_before_the_bytes_leave"},
    ),
    (
        "M6: declare a reason code outside the closed set",
        KERNEL,
        '_CODE_ILLEGIBLE: Final[str] = "illegible"',
        '_CODE_ILLEGIBLE: Final[str] = "not_a_real_code"',
        {"test_every_reason_code_raised_here_is_in_the_closed_set"},
    ),
    (
        "M6b: give the illegible failure a code the closure does not allow",
        KERNEL,
        "            code=_CODE_ILLEGIBLE,",
        '            code="not_a_real_code",',
        {"test_legibility_reports_a_measurement_and_a_reason"},
    ),
    (
        "M7: drop the measurements from the illegible failure",
        KERNEL,
        "            terms,\n            measurements,\n            observed,\n        )\n\n    return _observed(terms, measurements, observed)",
        "            terms,\n            {},\n            observed,\n        )\n\n    return _observed(terms, measurements, observed)",
        {"test_legibility_reports_a_measurement_and_a_reason"},
    ),
    (
        "M8: take the threshold into the kernel instead of using the caller's",
        KERNEL,
        "    if sharpness < threshold:",
        "    if sharpness < 20.0:",
        {"test_the_threshold_is_the_callers_by_changing_it_on_an_unchanged_image"},
    ),
    (
        "M9: upscale a target the source cannot reach",
        KERNEL,
        "    if target_dpi > source_dpi:",
        "    if False:",
        {"test_rescale_refuses_a_target_the_source_cannot_reach"},
    ),
    (
        "M10: report the local box as the source region",
        KERNEL,
        '            "source_box": [float(left), float(top), float(right), float(bottom)],',
        '            "source_box": [0.0, 0.0, float(right - left), float(bottom - top)],',
        {
            "test_crop_never_reports_local_coordinates_as_the_source_region",
        },
    ),
    (
        "M11: build the inverse map with a zero offset",
        KERNEL,
        "    inverse = InverseMap(offset_x=float(left), offset_y=float(top), scale=1.0)",
        "    inverse = InverseMap(offset_x=0.0, offset_y=0.0, scale=1.0)",
        {"test_crop_maps_local_coordinates_back_to_the_source"},
    ),
    (
        "M12: accept a degenerate region by widening it",
        KERNEL,
        "    if region.width <= 0 or region.height <= 0:",
        "    if region.width < -1e9 or region.height < -1e9:",
        {"test_crop_refuses_a_degenerate_region"},
    ),
    (
        "M13: accept a region outside the image",
        KERNEL,
        "    if left < 0 or top < 0 or right > width or bottom > height:",
        "    if False:",
        {"test_crop_refuses_a_region_outside_the_image"},
    ),
    (
        "M14: swallow a decode failure and report success",
        KERNEL,
        "    frame, meta = vendor.decode(path)\n\n    return frame, meta.exif_orientation",
        "    try:\n"
        "        frame, meta = vendor.decode(path)\n"
        "    except RasterVendorError:\n"
        "        return None\n\n"
        "    return frame, meta.exif_orientation",
        {"test_a_missing_file_is_a_typed_reason"},
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
    """Build a child environment that writes no bytecode.

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
