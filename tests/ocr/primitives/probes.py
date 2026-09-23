"""Shared probes the OCR suites run in a fresh interpreter.

Two questions recur across the modules here and neither can be answered honestly in-process:

* **Is an engine loaded?** The in-process answer is a fact about what *pytest* has already
  imported, not about the module under test. ``GEN-01``'s lazy-import rule is about a clean
  interpreter, so it has to be measured in one.
* **Does import have a side effect?** Docling's package, for instance, gains a
  ``document_converter`` attribute only once something imports the submodule — a side effect of
  Python's import machinery that an in-process check would attribute to the wrong thing.

A module rather than a fixture: these are values a test asks for and asserts about, not state
pytest should set up on its behalf.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

CLEAN_INTERPRETER_ENV = {"PYTHONPATH": str(REPO_ROOT / "src")}
"""The documented precondition, and nothing else from the ambient environment.

``pythonpath`` in ``pyproject.toml`` is a pytest setting, not an environment variable, so a
subprocess does not inherit it. Passing it explicitly is still an honest measurement: it is the
configuration the project declares, and it leaves no engine library on the path for a module to
pick up by accident.
"""


def run_in_clean_interpreter(code: str) -> subprocess.CompletedProcess[str]:
    """Run a snippet in a fresh interpreter with ``src/`` on the path.

    Args:
        code: The Python source to execute.

    Returns:
        The completed process, so a caller can assert on its exit code and both streams.
    """
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
        env=CLEAN_INTERPRETER_ENV,
        cwd=REPO_ROOT,
    )


def module_absent_from_a_clean_import(module_path: str, engine_name: str) -> bool:
    """Report whether importing a module pulls an engine in.

    Args:
        module_path: The module to import, as an import path.
        engine_name: The engine's import name to look for in ``sys.modules``.

    Returns:
        ``True`` when the engine is absent after the import, which is the state ``GEN-01``
        requires.
    """
    completed = run_in_clean_interpreter(
        f"import sys\nimport {module_path}\nprint({engine_name!r} in sys.modules)\n"
    )
    if completed.returncode != 0:
        raise AssertionError(f"importing {module_path} failed: {completed.stderr}")
    return completed.stdout.strip() == "False"


__all__ = [
    "CLEAN_INTERPRETER_ENV",
    "module_absent_from_a_clean_import",
    "run_in_clean_interpreter",
]
