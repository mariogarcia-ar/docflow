"""The declared dependencies cover what the library actually loads (``GEN-05``).

``pyproject.toml`` is the single tooling home, and ``dependencies`` is the one place a consumer of
this library learns what it needs. That list sat empty while the image processor used numpy, OpenCV
and Pillow across a dozen modules, so ``pip install docflow`` on a clean machine produced a package
that could not process a single image - the development environment happened to have them, which is
exactly why nothing noticed.

The drift is easy to reintroduce, because the engine seam makes it invisible to a source scan: the
libraries are reached through ``importlib``, so no ``import cv2`` statement exists to find. These
tests close the gap from the direction that survives a refactor - *what the seam loads* must be
covered by *what the manifest declares* - so a fourth engine added to the seam without a dependency
fails here rather than on a user's machine.
"""

from __future__ import annotations

import tomllib
from importlib import metadata
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from docflow.image.primitives.engine import (
    ARRAY_LIBRARY_NAME,
    EngineChoice,
    engine_module,
    operations_module,
)

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def declared_requirements() -> list[str]:
    """Return the runtime dependencies the manifest declares."""
    manifest = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    return list(manifest["project"]["dependencies"])


def module_roots_a_processor_loads() -> set[str]:
    """Return the top-level modules the image seam resolves at run time.

    Derived from the seam itself rather than restated: the point of the test is that the manifest
    tracks the code, so a hand-written copy of the module names here would defeat it.
    """
    roots = {ARRAY_LIBRARY_NAME}
    for choice in EngineChoice:
        roots.add(engine_module(choice).__name__.split(".")[0])
        roots.add(operations_module(choice).__name__.split(".")[0])
    return roots


def test_the_manifest_declares_requirements_rather_than_leaving_the_list_empty() -> (
    None
):
    """An empty list is the defect this file was written for, and it must not come back.

    A bare ``assert requirements`` would pass on a list of comments-only nonsense, so the shape is
    asserted too: each entry has to parse as a requirement.
    """
    requirements = declared_requirements()

    assert requirements, "`project.dependencies` is empty although `src/` imports numpy"
    for entry in requirements:
        Requirement(entry)


def test_every_module_an_engine_loads_is_provided_by_a_declared_dependency() -> None:
    """The invariant a clean install depends on.

    ``importlib.metadata.packages_distributions`` is the mapping that matters, because a module name
    and a distribution name are not the same string - the engine loads ``cv2`` and ``PIL`` while the
    manifest names ``opencv-python-headless`` and ``Pillow``. Requiring the sets to intersect means
    either distribution satisfies an engine that both of them provide.
    """
    declared = {
        canonicalize_name(Requirement(entry).name) for entry in declared_requirements()
    }
    providers = metadata.packages_distributions()
    uncovered = {
        module: providers.get(module)
        for module in module_roots_a_processor_loads()
        if not declared
        & {canonicalize_name(name) for name in providers.get(module, [])}
    }

    assert not uncovered, (
        f"the seam loads modules no declared dependency provides: {uncovered}\n"
        f"declared: {sorted(declared)}"
    )


def installed_version(name: str) -> str | None:
    """Return an installed distribution's version, or ``None`` when it is absent.

    ``metadata.version`` *raises* for a missing distribution rather than returning a falsey value,
    so a test that called it directly would report an error where the question is a boolean one.
    """
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def test_the_declared_dependencies_are_installed_in_this_environment() -> None:
    """The development environment and the manifest must describe the same project.

    A version installed but undeclared hides the problem from every test that only imports it; a
    version declared but not installed would make the suite pass for the wrong reason on a machine
    that had it by accident. This asserts the two agree, so neither can drift unnoticed.
    """
    missing = [
        entry
        for entry in declared_requirements()
        if installed_version(Requirement(entry).name) is None
    ]

    assert missing == [], f"declared but not installed: {missing}"
