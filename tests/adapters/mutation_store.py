"""Mutation harness for the K7 store adapter (``E04-04``, ``E04-07``).

`docflow/adapters/store.py` is not a vendor seam: there is no third-party library to
hide, and the filesystem is the thing being named. What it is for is that a caller can
depend on ``ArtifactStore`` instead of on `docflow/kernels/store.py`, which is what
`sad.md` §1 says is already true. So the properties to break here are the port's, not
the kernel's:

- **a failed verification is a value, and only an unputtable question is a reason.**
  This is the distinction the port says it exists to protect, and it has two edges:
  collapsing *absent* into a reason, and collapsing *cannot look* into ``False``.
- **a miss is a typed reason and never an empty value**, with the stored-empty case
  kept apart from it.
- **a refusal stays inside the closed code set** and names the misuse.
- **nothing the kernel raises reaches the caller** — the port returns two states and
  no third.
- **``rebuild_manifest`` refuses rather than deriving a summary**, because the summary
  belongs to K1.

Each entry breaks exactly one property, runs the targeted suite, and records which
tests failed. A mutation whose failure set does not contain the test that guards the
property proves nothing: either the anchor missed, or the test never exercised the
code. Results are read from the JUnit XML, because long test names wrap in stdout and
a failed grep reads as a pass.

Run with bytecode disabled:  python -B tests/adapters/mutation_store.py
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

ADAPTER = Path("src/docflow/adapters/store.py")
KERNEL = Path("src/docflow/kernels/store.py")
SUITES = ["tests/adapters/test_store.py"]

#: (label, file, anchor, replacement, the tests that MUST fail)
MUTATIONS: list[tuple[str, Path, str, str, set[str]]] = [
    (
        "M1: answer False where the question could not be asked",
        ADAPTER,
        "        if _a_file_stands_in_the_way(root):\n            return _refused(",
        "        if False:\n            return _refused(",
        {"test_a_verify_that_cannot_be_asked_is_a_reason"},
    ),
    (
        "M1b: turn an ordinary miss into a refusal",
        ADAPTER,
        "        if _a_file_stands_in_the_way(root):",
        "        if True:",
        {"test_verify_on_an_absent_root_is_an_answer_not_a_reason"},
    ),
    (
        "M2: stop walking the path, so a file in the way looks absent",
        ADAPTER,
        "    return any(part.is_file() for part in (root, *root.parents))",
        "    return False",
        {"test_a_verify_that_cannot_be_asked_is_a_reason"},
    ),
    (
        "M3: call an unputtable question a missing artifact",
        ADAPTER,
        "                _CODE_UNSUPPORTED_FORMAT,\n                NotADirectoryError(",
        "                _CODE_ARTIFACT_MISSING,\n                NotADirectoryError(",
        {"test_a_verify_that_cannot_be_asked_is_a_reason"},
    ),
    (
        "M4: measure the verification wrongly in the evidence",
        ADAPTER,
        'evidence=_evidence({"artifact_sha256": sha256, "intact": intact}),',
        'evidence=_evidence({"artifact_sha256": sha256, "intact": not intact}),',
        {"test_a_failed_verification_is_a_value_with_no_reason"},
    ),
    (
        "M5: answer a miss with an empty buffer instead of a reason",
        ADAPTER,
        "        except FileNotFoundError as refused:\n            return _refused(_CODE_ARTIFACT_MISSING, refused)",
        '        except FileNotFoundError:\n            payload = b""',
        {"test_get_on_a_miss_is_a_typed_reason_and_never_empty_bytes"},
    ),
    (
        "M5b: report a miss with a code that does not name it",
        ADAPTER,
        '_CODE_ARTIFACT_MISSING: Final[str] = "artifact_missing"',
        '_CODE_ARTIFACT_MISSING: Final[str] = "unsupported_format"',
        {"test_get_on_a_miss_is_a_typed_reason_and_never_empty_bytes"},
    ),
    (
        "M6: declare a reason code outside the closed set",
        ADAPTER,
        '_CODE_ENGINE_UNAVAILABLE: Final[str] = "engine_unavailable"',
        '_CODE_ENGINE_UNAVAILABLE: Final[str] = "not_a_real_code"',
        {
            "test_every_reason_code_raised_here_is_in_the_closed_set",
            "test_rebuild_manifest_refuses_rather_than_deriving_a_summary",
        },
    ),
    (
        "M7: accept anything as a ledger",
        ADAPTER,
        "        if not isinstance(ledger, kernel.Ledger):",
        "        if False:",
        {"test_a_ledger_that_is_not_a_ledger_is_a_usage_error"},
    ),
    (
        "M8: report a misused write_ledger as a missing artifact",
        ADAPTER,
        "        if not isinstance(ledger, kernel.Ledger):\n            return _refused(\n                _CODE_UNSUPPORTED_FORMAT,",
        "        if not isinstance(ledger, kernel.Ledger):\n            return _refused(\n                _CODE_ARTIFACT_MISSING,",
        {"test_a_ledger_that_is_not_a_ledger_is_a_usage_error"},
    ),
    (
        "M9: write done about bytes that were never stored",
        ADAPTER,
        "        return _ledger_result(ledger, artifact.sha256)\n\n    def fail(",
        "        return _ledger_result(ledger, None)\n\n    def fail(",
        {"test_begin_then_commit_reaches_done_through_the_port"},
    ),
    (
        "M10: understand a committed artifact as a bare hash",
        ADAPTER,
        "        except TypeError as refused:\n            # `commit` refuses anything that is not the `Artifact` `put` returned. The",
        "        except TypeError:\n            return _ledger_result(None, None)\n        except TypeError as refused:\n            # `commit` refuses anything that is not the `Artifact` `put` returned. The",
        {"test_commit_refuses_something_that_is_not_an_artifact"},
    ),
    (
        "M11: build a summary of the store's own instead of delegating to K1",
        ADAPTER,
        "        return KernelResult(\n            value=None,\n            evidence=_evidence(\n                {},",
        "        return KernelResult(\n            value={'units': {}},\n            evidence=_evidence(\n                {},",
        {"test_rebuild_manifest_refuses_rather_than_deriving_a_summary"},
    ),
    (
        "M12: put an observation where the numbers go",
        ADAPTER,
        '                {"out_dir": out_dir.name, "awaits": "kernels/orchestrator.py"},',
        '                {"[out_dir]": out_dir.name, "[awaits]": "kernels/orchestrator.py"},',
        {"test_rebuild_manifest_refuses_rather_than_deriving_a_summary"},
    ),
    (
        "M13: return an empty ledger for a unit that never ran",
        ADAPTER,
        "        except FileNotFoundError as refused:\n            return _refused(_CODE_ARTIFACT_MISSING, refused)\n        except (OSError, ValueError) as refused:\n            return _refused(_CODE_UNSUPPORTED_FORMAT, refused)\n\n        return _ledger_result(ledger, None)\n\n    def write_ledger(",
        "        except FileNotFoundError:\n            return _ledger_result(kernel.new_ledger(unit_dir.name, []), None)\n        except (OSError, ValueError) as refused:\n            return _refused(_CODE_UNSUPPORTED_FORMAT, refused)\n\n        return _ledger_result(ledger, None)\n\n    def write_ledger(",
        {"test_read_ledger_on_a_unit_that_never_ran_is_a_reason"},
    ),
    (
        "M14: attribute the ledger's states to the wrong stage",
        ADAPTER,
        '    if stage is not None:\n        observed["stage"] = stage',
        '    if stage is not None:\n        observed["stage"] = "unknown"',
        {"test_begin_then_commit_reaches_done_through_the_port"},
    ),
    (
        "M15: let the kernel's AttributeError reach the caller",
        ADAPTER,
        "        if not isinstance(ledger, kernel.Ledger):\n            return _refused(",
        "        if not isinstance(ledger, kernel.Ledger):\n            raise TypeError(\n                'not a ledger'\n            ) if False else None\n            return _refused(",
        {"test_the_kernel_exceptions_never_escape_a_call"},
    ),
    (
        "M16: hand back a descriptor for bytes that were never stored",
        ADAPTER,
        "        except (OSError, ValueError) as refused:\n            return _refused(_CODE_UNSUPPORTED_FORMAT, refused)\n\n        return KernelResult(\n            value=artifact,",
        "        except (OSError, ValueError) as refused:\n            return KernelResult(\n                value=kernel.Artifact(\n                    sha256='0' * 64, size_bytes=0, media_type=media_type, path=''\n                ),\n                evidence=_evidence({}),\n                reason=None,\n            )\n\n        return KernelResult(\n            value=artifact,",
        {"test_a_put_failure_is_reported_rather_than_acting_as_a_descriptor"},
    ),
    (
        "M17: stamp a successful read with a reason",
        ADAPTER,
        '        return KernelResult(\n            value=payload,\n            evidence=_evidence(\n                {"artifact_sha256": sha256, "bytes": float(len(payload))}\n            ),\n            reason=None,',
        '        return KernelResult(\n            value=payload,\n            evidence=_evidence(\n                {"artifact_sha256": sha256, "bytes": float(len(payload))}\n            ),\n            reason=Reason(code=_CODE_UNSUPPORTED_FORMAT, message="read anyway"),',
        {"test_a_stored_empty_artifact_is_a_value_not_a_miss"},
    ),
    (
        "M18: forget the caller's root and write to a fixed one",
        ADAPTER,
        "            artifact = kernel.put(root, data, media_type)",
        '            artifact = kernel.put(\n                Path("/tmp/docflow-mutation-store"), data, media_type\n            )',
        {
            "test_the_adapter_is_stateless_so_one_instance_serves_any_tree",
            "test_put_returns_the_descriptor_and_get_reads_it_back",
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
        ADAPTER: ADAPTER.read_text(encoding="utf-8"),
        KERNEL: KERNEL.read_text(encoding="utf-8"),
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
            if anchor == replacement:
                print(
                    f"[SKIP] {label}\n       replacement is identical — nothing changed"
                )
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
