"""Static isolation guards for the port package (``E04-01`` / ``S1-T11``).

This module deliberately imports **nothing** from ``docflow``. That is not
stylistic: the guard it carries must survive a port that cannot be imported.

A mutation that makes a port import an adapter can also make that port — and
therefore the whole ``docflow.ports`` package — fail to import. Any test module
with a module-level ``from docflow.ports import ...`` then dies at **collection**,
so the named assertion never runs and pytest reports a module-level error instead
of the failure the guard was written to produce. A green-looking outcome for the
wrong reason is worse than no guard, because it is trusted.

The predicate is therefore loaded **from its file** rather than through its
package, so no import of ``docflow.ports`` can take this module down. The two
predicates are the same file; what differs is that this one arrives without
executing the package the file lives in.

``plan-01-kernels.md`` §7b — *"Adapter isolation"*: the test is the import check,
and breaking it looks like *"an adapter is imported from a port; the arrow stops
pointing down"*.
"""

# pylint: disable=duplicate-code
# This module restates the port module names rather than importing them, and that
# is the point: importing them is what would make the guard collapse when a port
# breaks. A contract test holds its own copy of what it checks.

from __future__ import annotations

import ast
import importlib.util
import pathlib
import sys
import types
import typing

import pytest

# --- Loading the predicate without the package -------------------------------

#: ``<repo>/src/docflow/ports``, derived from this file's location rather than
#: from an import, so the guard works even when the package does not import.
PORTS_ROOT: pathlib.Path = (
    pathlib.Path(__file__).resolve().parents[2] / "src" / "docflow" / "ports"
)

#: The modules declared under ``docflow/ports``. Named explicitly rather than
#: globbed, so a new module has to be declared here by hand — which is the moment
#: someone notices the frozen five-interface set changed.
PORT_MODULES: frozenset[str] = frozenset(
    {
        "__init__.py",
        "_typing.py",
        "pdf.py",
        "ocr.py",
        "llm.py",
        "store.py",
        "registry.py",
    }
)

#: The private module that carries the predicate.
_PREDICATE_MODULE: str = "_typing.py"

#: The name the predicate module is registered under in ``sys.modules``. Kept
#: distinct from ``docflow.ports._typing`` so loading it here cannot collide with
#: the package's own import of it.
_PREDICATE_NAME: str = "_ports_typing_loaded_from_path"


def _load_predicate() -> types.ModuleType:
    """Load ``docflow/ports/_typing.py`` by path, without importing its package.

    ``importlib.util.spec_from_file_location`` executes the file directly, so the
    parent ``__init__.py`` never runs. That is what keeps this module collectable
    when a port is broken.

    Returns:
        The loaded ``_typing`` module.

    """
    path = PORTS_ROOT / _PREDICATE_MODULE
    spec = importlib.util.spec_from_file_location(_PREDICATE_NAME, path)

    assert spec is not None and spec.loader is not None, f"cannot load {path}"

    module = importlib.util.module_from_spec(spec)
    sys.modules[_PREDICATE_NAME] = module
    spec.loader.exec_module(module)

    return module


PREDICATE: typing.Any = _load_predicate()
ADAPTER_PACKAGE: str = PREDICATE.ADAPTER_PACKAGE
imported_package_paths = PREDICATE.imported_package_paths
is_adapter_import = PREDICATE.is_adapter_import


def port_sources() -> list[tuple[str, str]]:
    """Read every declared port module's text.

    Returns:
        ``(module name, source)`` for each module in ``PORT_MODULES``.

    """
    return [
        (name, (PORTS_ROOT / name).read_text(encoding="utf-8"))
        for name in sorted(PORT_MODULES)
    ]


# --- The real tree: the arrow must point down -------------------------------


def test_no_port_module_imports_an_adapter() -> None:
    """The dependency arrow points down: no port imports an adapter.

    This is the guard ``ADR-004``'s reuse claim rests on. It reads the real
    modules' syntax trees, so it holds for a module that cannot be imported just
    as well as for one that can — which is the case that matters, because a port
    importing an adapter is exactly a port that may stop importing.
    """
    for module_name, source in port_sources():
        offenders = [
            path for path in imported_package_paths(source) if is_adapter_import(path)
        ]

        assert not offenders, (
            f"{module_name} imports {offenders!r} from the adapter package; the "
            "dependency arrow must only point down"
        )


def test_no_port_module_imports_anything_outside_the_lower_layers() -> None:
    """A port imports the standard library, its own package, and ``kernels``.

    Anything else — a domain module, a component, a third-party package — is a
    dependency the caller did not agree to, and a second arrow pointing the wrong
    way is as bad as the first.
    """
    allowed_local_prefixes = ("docflow.kernels", "docflow.ports")

    for module_name, source in port_sources():
        for path in imported_package_paths(source):
            if path.lstrip(".").split(".")[0] != "docflow":
                continue

            assert path.startswith(allowed_local_prefixes), (
                f"{module_name} imports {path!r}, which is neither a boundary type "
                "nor a port"
            )


def test_the_real_tree_scan_is_not_vacuous() -> None:
    """The scan reads every declared module and finds imports in them.

    A scan that read no files, or read files whose imports were empty, would make
    both guards above pass while asserting nothing about the tree they exist to
    police.
    """
    sources = port_sources()

    assert {name for name, _source in sources} == PORT_MODULES
    for module_name, source in sources:
        assert list(imported_package_paths(source)), f"{module_name} declares no import"


def test_the_ports_package_contains_only_the_declared_modules() -> None:
    """No module was introduced under ``docflow/ports`` beyond the declared set.

    A pure directory listing, so it needs no import and survives a package that
    cannot be imported. The set is written out by hand rather than globbed: a
    sixth port appearing is precisely the change this guard exists to make
    somebody declare on purpose.
    """
    actual = {path.name for path in PORTS_ROOT.glob("*.py")}

    assert actual <= PORT_MODULES, (
        f"unexpected modules: {sorted(actual - PORT_MODULES)}"
    )
    assert actual >= PORT_MODULES, f"missing modules: {sorted(PORT_MODULES - actual)}"
    assert not (PORTS_ROOT / "image.py").exists(), (
        "K3 has no port: its raster library is the one engine that is not a vendor "
        "service behind a swap-able boundary, so a sixth interface would put a "
        "boundary where the architecture did not ask for one"
    )


# --- The predicate's own behaviour, on synthetic sources ---------------------


ILLEGAL_SOURCES: tuple[str, ...] = (
    "import docflow.adapters\n",
    "import docflow.adapters.docling\n",
    "import docflow.adapters.docling as docling\n",
    "from docflow.adapters import docling\n",
    "from docflow.adapters.docling import DoclingEngine\n",
    "from ..adapters import docling\n",
    "from ..adapters.docling import DoclingEngine\n",
    "from docflow import adapters\n",
    "from . import adapters\n",
)

LEGAL_SOURCES: tuple[str, ...] = (
    "import json\n",
    "from collections.abc import Mapping\n",
    "from docflow.kernels.types import KernelResult\n",
    "from docflow.kernels import store\n",
    "from docflow.ports.pdf import PdfSource\n",
    "from . import pdf\n",
    "from .pdf import PdfSource\n",
    "from ..kernels.types import Reason\n",
    "from docflow.ports.store import ArtifactStore\n",
)


@pytest.mark.parametrize("source", ILLEGAL_SOURCES)
def test_an_adapter_import_is_detected_in_every_spelling(source: str) -> None:
    """Each way of writing the illegal import is caught.

    The relative and ``from package import module`` forms are the ones a naive
    check misses. Both are ordinary Python, so a port using either would hold the
    arrow pointing up while a prefix-matching check reported clean.
    """
    paths = list(imported_package_paths(source))

    assert any(is_adapter_import(path) for path in paths), (
        f"{source!r} reaches {ADAPTER_PACKAGE} through {paths!r} and must be "
        "detected; a check that misses it passes while the arrow already points up"
    )


@pytest.mark.parametrize("source", LEGAL_SOURCES)
def test_a_legal_import_is_not_flagged(source: str) -> None:
    """Downward and same-layer imports are left alone.

    A guard that fired on ``from ..kernels.types import Reason`` would be
    unusable: that import is what a port is *made* of.
    """
    paths = list(imported_package_paths(source))

    assert not any(is_adapter_import(path) for path in paths), (
        f"{source!r} is a legal import and must not be reported as an adapter one"
    )


def test_an_adapter_import_inside_a_function_body_is_detected() -> None:
    """A deferred import is still an import.

    The module-level case is the obvious one, but the dependency arrow does not
    care where in the file the statement sits. It is also the form a mutation
    takes when it must not disturb ``from __future__`` placement, so this is the
    case the guard is most likely to meet in practice.
    """
    source = "def read() -> None:\n    from docflow.adapters import docling\n"

    assert any(is_adapter_import(path) for path in imported_package_paths(source))


def test_the_forbidden_path_itself_is_flagged_but_a_lookalike_is_not() -> None:
    """The predicate matches whole segments, not a substring.

    ``docflow.adaptersomething`` is not the adapter package, and a check built on
    a bare ``"adapters" in path`` would be wrong in the one direction that is
    expensive: silently clean on a real violation.
    """
    assert is_adapter_import(ADAPTER_PACKAGE)
    assert is_adapter_import(f"{ADAPTER_PACKAGE}.docling")
    assert not is_adapter_import("docflow.adaptersomething")
    assert not is_adapter_import("docflow.kernels.adapters_helper")
    assert not is_adapter_import("docflow.adapters_like")


def test_the_import_walk_yields_one_path_per_imported_name() -> None:
    """All three import forms are walked, one path per imported name."""
    source = (
        "import os\n"
        "from pathlib import Path\n"
        "from collections.abc import Mapping\n"
        "from . import pdf\n"
    )

    assert list(imported_package_paths(source)) == [
        "os",
        "pathlib.Path",
        "collections.abc.Mapping",
        ".pdf",
    ]


def test_a_multi_name_import_is_expanded_into_one_path_each() -> None:
    """``from docflow import adapters, kernels`` yields two paths, not one.

    This is what makes ``from docflow import adapters`` detectable: the package in
    the statement is ``docflow``, and only the imported *name* carries the segment
    that identifies the illegal target.
    """
    assert list(imported_package_paths("from docflow import adapters, kernels\n")) == [
        "docflow.adapters",
        "docflow.kernels",
    ]


def test_the_illegal_case_set_is_not_accidentally_empty() -> None:
    """Both case sets are populated and disjoint.

    Without this, emptying ``ILLEGAL_SOURCES`` would leave the parametrized test
    above passing with zero cases — a green suite that asserts nothing.
    """
    assert len(ILLEGAL_SOURCES) >= 5
    assert len(LEGAL_SOURCES) >= 5
    assert set(ILLEGAL_SOURCES).isdisjoint(LEGAL_SOURCES)


def test_an_unparseable_source_raises_rather_than_reporting_clean() -> None:
    """A source that cannot be parsed is an error, never a silent clean result.

    If a syntax error were swallowed into *"no adapter import found"*, the guard
    would report clean on exactly the file nobody could read.
    """
    with pytest.raises(SyntaxError):
        list(imported_package_paths("def broken(:\n"))


def test_the_walk_reads_the_syntax_tree_and_not_the_text() -> None:
    """A comment cannot satisfy the walk, and cannot trip it either.

    Stated as an assertion about the tree rather than about behaviour, because the
    failure it guards against — a text search that finds the word in a comment or
    a docstring — is the one that would look correct in review.
    """
    source = "# from docflow.adapters import docling\nimport json\n"

    assert isinstance(ast.parse(source), ast.Module)
    assert list(imported_package_paths(source)) == ["json"]


# --- The guard survives a broken package ------------------------------------


def test_this_module_does_not_import_the_ports_package() -> None:
    """The guard module itself imports nothing from ``docflow``.

    This is the property that makes the guard load-bearing rather than decorative.
    It is asserted over this file's own syntax tree, so a later edit that adds a
    convenient ``from docflow.ports import ...`` at the top fails here rather than
    quietly making the guard collapse at collection exactly when it is needed.
    """
    source = pathlib.Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("docflow"), (
                    f"this module must not import {alias.name!r}: a port that fails "
                    "to import would then take this guard down at collection"
                )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "__future__":
                continue

            assert not module.startswith("docflow"), (
                f"this module must not import from {module!r}: a port that fails to "
                "import would then take this guard down at collection"
            )
