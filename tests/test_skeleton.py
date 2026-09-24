"""Skeleton tests: what ``GEN-01`` and ``GEN-02`` promise, checked.

The Phase 0 exit is "skeleton imports cleanly, one happy-path test per contract
round-trips an in-memory fake end to end, and the four QA gates pass". The round trips live
in the per-sub-package modules; this module checks the shape the skeleton promises:

* the five sub-packages import, in a clean interpreter, without dragging an engine in;
* every documented entry point exists as a *typed* signature;
* no contract field carries an undocumented default;
* ``tests/`` mirrors ``src/docflow/``;
* a stub raises rather than returning a placeholder.

The clean-interpreter check runs in a subprocess on purpose. Importing inside the test
process would tell us only what pytest had already imported; ``GEN-01``'s evidence is an
import from a clean interpreter, so that is what is measured.
"""

from __future__ import annotations

import ast
import importlib
import json
import os
import subprocess
import sys
import typing
from dataclasses import MISSING, fields, is_dataclass
from pathlib import Path

import pytest

from tests.factories import build_document_request, build_pdf_request

REPO_ROOT = Path(__file__).resolve().parents[1]

# ``GEN-01``'s evidence is an import "from a clean interpreter with src/ on the path".
# pytest puts src/ on the path for the main process through ``pythonpath``, which is not
# an environment variable, so a subprocess would not inherit it. The check below passes it
# explicitly, which is still an honest measurement: it is the documented precondition, and
# it leaves no engine library on the path for the skeleton to pick up by accident.
CLEAN_INTERPRETER_ENV = {
    **os.environ,
    "PYTHONPATH": str(REPO_ROOT / "src"),
}

SUB_PACKAGES = (
    "docflow.pdf",
    "docflow.image",
    "docflow.ocr",
    "docflow.llm",
    "docflow.workflow",
)

INTERNAL_PACKAGES = ("primitives", "utils", "helpers")

# The seams that will call an engine. Importing one must not need an engine installed,
# which is why ``primitives/`` resolves its engine lazily instead of at module import.
PRIMITIVE_MODULES = (
    "docflow.pdf.primitives",
    "docflow.image.primitives",
    "docflow.ocr.primitives",
    "docflow.llm.primitives",
)

# Test infrastructure that is not a mirror of a source package: `tests/fakes/engines/` holds
# the engine doubles the convention fixes (`README.md` §9.7). Anything else under `tests/`
# still has to mirror `src/docflow/`.
NON_MIRROR_TEST_PACKAGES = ("fakes",)

ENTRY_POINTS: dict[str, tuple[str, ...]] = {
    "docflow.pdf": ("process_pdf", "process_pdf_page"),
    "docflow.image": ("process_image", "process_image_from_page"),
    "docflow.ocr": ("process_ocr_image",),
    "docflow.llm": ("process_llm_request", "process_llm_node"),
    "docflow.workflow": ("process_document", "process_page"),
}

# Entry points reserved for the orchestrator: no processor may define them.
RESERVED_ENTRY_POINTS = ("process_document", "process_page")

CONTRACT_MODULES = (
    "docflow.pdf.contracts",
    "docflow.image.contracts",
    "docflow.ocr.contracts",
    "docflow.llm.contracts",
    "docflow.workflow.contracts",
)

# A default is a silent stand-in unless there is a stated reason it cannot be one.
# Each entry names the field and the reason; a field absent from this map must have no
# default at all.
ALLOWED_DEFAULTS: dict[str, str] = {
    "docflow.pdf.contracts.PDFResult.errors": (
        "a successful document run has an empty failure list, and an empty list is the "
        "true answer rather than a substitute for one"
    ),
}

# One import name per concrete engine the plan names in `README.md` §9.3. A first import
# of any of them in a clean interpreter would mean the skeleton reaches an engine.
ENGINE_MODULES = (
    "docling",
    "cv2",
    "PIL",
    "fitz",
    "pypdfium2",
    "pdf2image",
    "openai",
    "ollama",
    "anthropic",
    "httpx",
)


def engine_modules_loaded_by(modules: tuple[str, ...]) -> list[str]:
    """Import ``modules`` in a clean interpreter and return the engine modules loaded.

    The subprocess is the measurement: in-process, the answer would be a fact about what
    pytest had already imported rather than about the module under test.
    """
    code = (
        "import json, sys\n"
        f"import {', '.join(modules)}\n"
        f"engines = {ENGINE_MODULES!r}\n"
        "loaded = sorted({m.split('.')[0] for m in sys.modules})\n"
        "print(json.dumps([m for m in loaded if m in engines]))\n"
    )

    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        env=CLEAN_INTERPRETER_ENV,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip(), "the subprocess printed no observation"
    loaded: list[str] = json.loads(completed.stdout)
    return loaded


def test_the_five_sub_packages_import_in_a_clean_interpreter() -> None:
    """``import docflow.pdf, …`` succeeds with no engine library pulled in."""
    loaded = engine_modules_loaded_by(SUB_PACKAGES)

    assert loaded == [], f"importing the skeleton pulled in an engine library: {loaded}"


def test_importing_the_primitive_seams_pulls_in_no_engine() -> None:
    """A seam resolves its engine lazily: importing it must not need one installed.

    This is what keeps the suite runnable in the environment `GEN-21` uses — no engine on
    the machine. A module-level ``import cv2`` (or docling, or a provider SDK) in any
    ``primitives/`` module turns that environment from green to broken.
    """
    loaded = engine_modules_loaded_by(SUB_PACKAGES + PRIMITIVE_MODULES)

    assert loaded == [], (
        f"importing a primitive seam pulled in an engine library: {loaded}"
    )


@pytest.mark.parametrize(("package", "names"), ENTRY_POINTS.items())
def test_every_documented_entry_point_exists_and_is_typed(
    package: str, names: tuple[str, ...]
) -> None:
    """Each entry point is resolvable, callable and fully annotated."""
    module = importlib.import_module(package)

    for name in names:
        entry_point = getattr(module, name)

        assert callable(entry_point), f"{package}.{name} is not callable"
        hints = typing.get_type_hints(entry_point)
        assert "return" in hints, f"{package}.{name} has no return annotation"
        for parameter in typing.get_type_hints(entry_point):
            assert parameter, f"{package}.{name} has an empty annotation name"
        for parameter in entry_point.__code__.co_varnames[
            : entry_point.__code__.co_argcount
        ]:
            assert parameter in hints, (
                f"{package}.{name} leaves {parameter} unannotated"
            )


def test_the_three_internal_packages_exist_for_every_processor() -> None:
    """The idea's layout fixes ``primitives/``, ``utils/`` and ``helpers/`` per processor."""
    for package in SUB_PACKAGES:
        if package == "docflow.workflow":
            continue
        for internal in INTERNAL_PACKAGES:
            module = importlib.import_module(f"{package}.{internal}")
            assert module is not None


def test_no_processor_defines_a_reserved_orchestrator_name() -> None:
    """The two reserved names belong to the orchestrator and to nothing else."""
    for package in SUB_PACKAGES:
        if package == "docflow.workflow":
            continue
        module = importlib.import_module(package)
        for reserved in RESERVED_ENTRY_POINTS:
            assert not hasattr(module, reserved), (
                f"{package} defines the reserved name {reserved}"
            )


def test_tests_mirrors_the_source_tree() -> None:
    """A test package exists for each sub-package, and the mirror is not partial."""
    source_packages = {
        path.name
        for path in (REPO_ROOT / "src" / "docflow").iterdir()
        if path.is_dir() and (path / "__init__.py").exists()
    }
    test_packages = {
        path.name
        for path in (REPO_ROOT / "tests").iterdir()
        if path.is_dir() and (path / "__init__.py").exists()
    } - set(NON_MIRROR_TEST_PACKAGES)

    assert source_packages == test_packages


def test_no_contract_field_carries_an_undocumented_default() -> None:
    """A required field is required; a default must be argued for, not inherited."""
    undocumented: list[str] = []

    for module_name in CONTRACT_MODULES:
        module = importlib.import_module(module_name)
        for name, member in vars(module).items():
            if not is_dataclass(member) or not isinstance(member, type):
                continue
            if member.__module__ != module_name:
                continue
            for field in fields(member):
                has_default = field.default is not MISSING
                has_factory = field.default_factory is not MISSING
                if not (has_default or has_factory):
                    continue
                qualified = f"{module_name}.{name}.{field.name}"
                if qualified not in ALLOWED_DEFAULTS:
                    undocumented.append(qualified)

    assert not undocumented, (
        "these contract fields carry a default with no stated reason they cannot stand "
        f"in for a real answer: {undocumented}"
    )


def test_a_stub_raises_instead_of_returning_a_placeholder() -> None:
    """A caller can never mistake a Phase 0 stub for a processed document."""
    workflow_module = importlib.import_module("docflow.workflow")
    pdf_module = importlib.import_module("docflow.pdf")

    document_request = build_document_request(Path("."))
    pdf_request = build_pdf_request(Path("."))

    with pytest.raises(NotImplementedError):
        workflow_module.process_document(document_request)

    with pytest.raises(NotImplementedError):
        pdf_module.process_pdf_page(pdf_request, 1, Path("page_001"))


def test_a_processor_reports_a_state_without_importing_the_orchestrator() -> None:
    """Importing the vocabulary must not import ``docflow.workflow`` or a processor.

    The check is a subprocess because the in-process answer would be a fact about what
    pytest had already imported rather than about the module under test.
    """
    code = (
        "import sys\n"
        "import docflow.states\n"
        "assert 'docflow.workflow' not in sys.modules, sys.modules.keys()\n"
        "assert docflow.states.StageState.SUCCESS == 'SUCCESS'\n"
    )

    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        env=CLEAN_INTERPRETER_ENV,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_importing_one_processor_does_not_import_another() -> None:
    """No processor imports another processor: only the orchestrator composes them."""
    code = (
        "import sys\n"
        "import docflow.pdf, docflow.ocr\n"
        "for other in ('docflow.image', 'docflow.llm', 'docflow.workflow'):\n"
        "    assert other not in sys.modules, f'{other} was imported'\n"
    )

    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        env=CLEAN_INTERPRETER_ENV,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_no_module_under_src_imports_the_test_tree() -> None:
    """A double must never be reachable from production code (`README.md` §9.7).

    Read statically rather than executed: the assertion is about the import graph, and a
    production module that imports `tests` has already turned a fake into a fallback by the
    time any test could observe it.
    """
    offenders: list[str] = []

    for path in sorted((REPO_ROOT / "src" / "docflow").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                if name.split(".")[0] == "tests":
                    relative = path.relative_to(REPO_ROOT)
                    offenders.append(f"{relative}:{node.lineno} imports {name}")

    assert not offenders, (
        "production modules import the test tree, so a double can become a fallback: "
        f"{offenders}"
    )
