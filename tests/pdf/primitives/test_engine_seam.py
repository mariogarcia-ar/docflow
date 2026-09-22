"""The engine seam is a seam: one module knows the engine, and no other reaches past it.

``docs/plan/README.md`` §7 fixes the rule — *a concrete engine/library is reached only from
a processor's own* ``primitives/``. ``subplan-procesador-pdf.md`` §3 narrows it for this
processor: the primitives *are* the only place that touches Poppler, and inside them the
dependency is funnelled through one module, so the engine is swapped by editing that module
alone.

This test guards the narrower half of the rule, which is the half a refactor breaks
silently: a primitive that calls ``subprocess.run(["pdftotext", …])`` itself still passes
every extraction test while quietly making the engine unswappable.
"""

from __future__ import annotations

import ast
import importlib
import textwrap
from pathlib import Path

import pytest

from docflow.pdf.primitives import engine

ENGINE_MODULE_NAME = "engine"
ENGINE_MODULE_PATH = Path(engine.__file__)
PRIMITIVES_DIR = ENGINE_MODULE_PATH.parent
PRIMITIVES_PACKAGE = "docflow.pdf.primitives"

FORBIDDEN_IMPORTS = frozenset(
    {"subprocess", "shutil", "fitz", "pypdf", "pypdfium2", "pdf2image"}
)

# A process spawn, however it is spelled. `os.system` and `os.popen` reach an engine just
# as effectively as `subprocess` does. Matched against *calls*, never against prose: a
# primitive is allowed to mention `subprocess` in a docstring explaining why it does not
# use one.
PROCESS_SPAWN_CALLS = frozenset(
    {
        "subprocess.run",
        "subprocess.Popen",
        "subprocess.call",
        "subprocess.check_call",
        "subprocess.check_output",
        "os.system",
        "os.popen",
        "os.spawnv",
    }
)


def imported_roots(source: str) -> set[str]:
    """Return the top-level modules ``source`` imports.

    Args:
        source: Python source to parse.

    Returns:
        The set of top-level module names imported by any ``import`` or ``from`` statement.
    """
    tree = ast.parse(source)
    roots: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])

    return roots


def spawn_calls(source: str) -> set[str]:
    """Return the process-spawning calls ``source`` actually makes.

    Args:
        source: Python source to parse.

    Returns:
        The dotted names of the spawn calls found, e.g. ``{"subprocess.run"}``. Comments and
        docstrings are not calls, so mentioning one is not a violation.
    """
    found: set[str] = set()

    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        name = _dotted_name(node.func)
        if name in PROCESS_SPAWN_CALLS:
            found.add(name)

    return found


def _dotted_name(node: ast.expr) -> str:
    """Render an attribute/name expression as a dotted string, or ``""`` if it is neither."""
    parts: list[str] = []
    current: ast.expr = node

    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value

    if not isinstance(current, ast.Name):
        return ""

    parts.append(current.id)
    return ".".join(reversed(parts))


def primitive_modules() -> list[Path]:
    """Return every primitive module that is not the seam itself."""
    return sorted(
        path for path in PRIMITIVES_DIR.glob("*.py") if path.stem != ENGINE_MODULE_NAME
    )


def test_the_seam_module_imports() -> None:
    """There is exactly one module the engine is allowed to leak into."""
    assert ENGINE_MODULE_PATH.name == f"{ENGINE_MODULE_NAME}.py"
    assert (
        importlib.import_module(f"{PRIMITIVES_PACKAGE}.{ENGINE_MODULE_NAME}") is engine
    )


def test_no_primitive_reaches_an_engine_except_through_the_seam() -> None:
    """Only ``engine.py`` imports ``subprocess``, ``shutil`` or a PDF library directly.

    Mutation that breaks it: add ``import subprocess`` to ``split.py`` and call
    ``subprocess.run(["pdfseparate", …])`` there. The assertion fails — the engine is now
    reachable from two places, and swapping Poppler means finding both.
    """
    violations: dict[str, list[str]] = {}

    for path in primitive_modules():
        roots = imported_roots(path.read_text(encoding="utf-8"))
        forbidden = sorted(roots & FORBIDDEN_IMPORTS)
        if forbidden:
            violations[path.name] = forbidden

    assert not violations, (
        "these primitives reach an engine directly instead of going through "
        f"{ENGINE_MODULE_PATH.name}: {violations}"
    )


def test_the_seam_is_the_only_module_that_names_a_process_spawn() -> None:
    """Even an engine reached through a non-imported path is caught here.

    Matched against calls, not text: ``document.py`` explains in its docstring that engine
    access goes through the seam rather than through a direct ``subprocess`` call, and a
    primitive is allowed to say that.
    """
    spawning = {
        path.name: sorted(spawn_calls(path.read_text(encoding="utf-8")))
        for path in primitive_modules()
    }

    assert {name: found for name, found in spawning.items() if found} == {}


@pytest.mark.parametrize(
    ("mutated_source", "expected_root", "expected_spawn"),
    [
        (
            textwrap.dedent(
                """
                import subprocess

                def extract_page(pdf_path, page_number, output_path):
                    subprocess.run(["pdfseparate", str(pdf_path)], check=False)
                    return output_path
                """
            ),
            "subprocess",
            "subprocess.run",
        ),
        (
            textwrap.dedent(
                """
                from fitz import open as open_pdf

                def extract_page(pdf_path, page_number, output_path):
                    open_pdf(pdf_path)
                    return output_path
                """
            ),
            "fitz",
            None,
        ),
        (
            textwrap.dedent(
                """
                import os

                def extract_page(pdf_path, page_number, output_path):
                    os.system(f"pdfseparate {pdf_path}")
                    return output_path
                """
            ),
            "os",
            "os.system",
        ),
    ],
)
def test_the_guard_detects_a_primitive_that_reaches_the_engine(
    mutated_source: str, expected_root: str, expected_spawn: str | None
) -> None:
    """The guard is falsified against primitives that do reach the engine.

    Without this, the guard could be green because it inspects nothing. Each mutated source
    goes through the same helpers the guard uses, so these tests fail if detection stops
    working — the harness itself is what is under test here, not a real module.

    Two guards cover the two ways an engine is reached, and each case exercises the one
    that must catch it: a PDF library or ``subprocess`` import trips the import check,
    while ``os.system`` trips the call check — ``os`` itself is a legitimate stdlib import,
    so only the call is the defect.
    """
    assert expected_root in imported_roots(mutated_source)

    if expected_root in FORBIDDEN_IMPORTS:
        assert imported_roots(mutated_source) & FORBIDDEN_IMPORTS

    if expected_spawn is not None:
        assert expected_spawn in spawn_calls(mutated_source)


def test_prose_about_a_subprocess_is_not_a_violation() -> None:
    """Mentioning the mechanism in a docstring is not the same as using it.

    This is the guard's own boundary condition: ``document.py`` documents that engine access
    goes through the seam instead of a direct call, and a text-based check would flag that
    sentence. The check is on calls for exactly this reason.
    """
    prose_only = textwrap.dedent(
        '''
        """Engine access goes through the seam, never through a direct subprocess call."""

        def extract_page(pdf_path, page_number, output_path):
            # No subprocess.run here on purpose.
            return output_path
        '''
    )

    assert not spawn_calls(prose_only)
    assert "subprocess" not in imported_roots(prose_only)
