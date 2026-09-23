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
from docflow.ocr.primitives import engine as ocr_engine

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


# Every processor seam, by the module path this test resolves it through. A seam added to `src/`
# without an entry here is a seam whose dependency this test cannot see, so the list is the one
# place a new processor has to be registered - and the OCR seam was exactly that gap: it was
# declared in `pyproject.toml` while this file still only knew about the image one.
#
# The PDF seam is here too, and registered as what it is: a *system binary* seam. Its engine is
# Poppler, reached through `subprocess`, so no `pip` requirement can cover it and the manifest is
# not its home. Listing it keeps the guard total - "every seam is accounted for" - while the
# second set says how each one is accounted for. Without that split the discovery check below
# would force either a false entry in `dependencies` or a hole in the guard.
SEAMS_IMPORTED_AS_MODULES = (
    "docflow.image.primitives.engine",
    "docflow.ocr.primitives.engine",
)
"""Seams whose engine is a Python distribution, so `pip` must be able to install it."""

SEAMS_REACHED_AS_BINARIES = ("docflow.pdf.primitives.engine",)
"""Seams whose engine is a system binary: installable by no package manager this file drives."""

SEAMS = SEAMS_IMPORTED_AS_MODULES + SEAMS_REACHED_AS_BINARIES


def declared_requirements() -> list[str]:
    """Return the runtime dependencies the manifest declares."""
    manifest = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    return list(manifest["project"]["dependencies"])


def module_roots_a_processor_loads() -> set[str]:
    """Return the top-level modules the processor seams resolve at run time.

    Derived from the seams themselves rather than restated: the point of the test is that the
    manifest tracks the code, so a hand-written copy of the module names here would defeat it.

    The two seams are read differently because their engines differ in kind. The image seam
    offers a *choice* between interchangeable libraries, so its modules come from the enum. The
    OCR seam has a single engine and no enum, so its module names are read from the constants it
    publishes - which is still the seam answering, not this test.
    """
    roots = {ARRAY_LIBRARY_NAME}
    for choice in EngineChoice:
        roots.add(engine_module(choice).__name__.split(".")[0])
        roots.add(operations_module(choice).__name__.split(".")[0])
    roots.add(ocr_engine.DOCLING_MODULE_NAME.split(".", maxsplit=1)[0])
    roots.add(ocr_engine.DOCLING_CONVERTER_MODULE_NAME.split(".", maxsplit=1)[0])
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


def distributions_a_declaration_installs(name: str) -> set[str]:
    """Return the distributions a declared requirement brings with it, transitively.

    The manifest is not the whole story on a clean install, and this is the case that proves it:
    ``docling`` 2.126.0 is a thin meta-package whose only base requirement is
    ``docling-slim[standard]``, and it is **docling-slim that owns the ``docling`` module**.
    Checking the declared names alone reports the engine as uncovered and would push a maintainer
    towards one of two wrong fixes - declaring ``docling-slim`` (which loses the ``[standard]``
    extras the OCR models live in) or adding a false entry.

    Extra-gated requirements are excluded. A module that only exists when an optional extra is
    requested is not something a base install can rely on, so counting it would make the guard
    pass for a deployment that never asked for the extra. Requirements without a marker, and
    those gated on something a base install satisfies, are followed.

    Args:
        name: A distribution name from the manifest.

    Returns:
        Every distribution name reachable from it, itself included when it is installed.
    """
    seen: set[str] = set()
    pending = [canonicalize_name(name)]
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        try:
            requirements = metadata.requires(current) or []
        except metadata.PackageNotFoundError:
            continue
        for entry in requirements:
            requirement = Requirement(entry)
            if requirement.marker is not None and not requirement.marker.evaluate():
                continue
            dependency = canonicalize_name(requirement.name)
            if dependency not in seen:
                pending.append(dependency)
    return seen


def distributions_the_manifest_installs() -> set[str]:
    """Return every distribution the declared dependencies install, transitively.

    Returns:
        The closure of the manifest's requirements.
    """
    installed: set[str] = set()
    for entry in declared_requirements():
        installed |= distributions_a_declaration_installs(Requirement(entry).name)
    return installed


def test_every_module_an_engine_loads_is_provided_by_a_declared_dependency() -> None:
    """The invariant a clean install depends on.

    ``importlib.metadata.packages_distributions`` is the mapping that matters, because a module
    name and a distribution name are not the same string - the image engine loads ``cv2`` and
    ``PIL`` while the manifest names ``opencv-python-headless`` and ``Pillow``, and the OCR
    engine loads ``docling`` while the module belongs to ``docling-slim``.

    Compared against the manifest's **transitive closure** rather than its literal names, because
    that is what ``pip install`` actually puts on disk. Requiring the sets to intersect means
    either distribution satisfies an engine that both of them provide.
    """
    installed = distributions_the_manifest_installs()
    providers = metadata.packages_distributions()
    uncovered = {
        module: providers.get(module)
        for module in module_roots_a_processor_loads()
        if not installed
        & {canonicalize_name(name) for name in providers.get(module, [])}
    }

    assert not uncovered, (
        f"the seams load modules no declared dependency provides: {uncovered}\n"
        f"declared closure: {sorted(installed)}"
    )


def test_every_processor_seam_is_registered_with_this_guard() -> None:
    """A seam in `src/` that this test does not know about is an unguarded dependency.

    Discovered from the filesystem rather than asserted from a hand-written list, so adding a
    processor seam without registering it here fails rather than passing quietly. This is the
    check that would have caught the OCR seam's own gap: `docling` was declared in the manifest
    before this file knew the OCR seam existed.

    It also found the PDF seam, which is why the registry is split in two. Poppler is a system
    binary, so the manifest is not its home - but a seam the guard cannot classify is worse than
    one it classifies as external, because the first is silently unguarded.
    """
    package_root = Path(__file__).resolve().parents[1] / "src"
    discovered = {
        path.relative_to(package_root).with_suffix("").as_posix().replace("/", ".")
        for path in package_root.glob("docflow/*/primitives/engine.py")
    }

    assert discovered == set(SEAMS), (
        "these engine seams exist but are not covered by this guard: "
        f"{sorted(discovered - set(SEAMS))}"
    )


def test_the_binary_seams_are_not_claimed_as_pip_dependencies() -> None:
    """A system-binary engine must not appear in `dependencies`.

    `pip` cannot install Poppler, so a requirement naming it would be a lie a resolver cannot
    honour: the install would fail, or worse, succeed against an unrelated package of that name.
    The README's Requirements section is where an operator is told about it instead.
    """
    declared = {
        canonicalize_name(Requirement(entry).name) for entry in declared_requirements()
    }

    for binary in ("poppler", "poppler-utils"):
        assert binary not in declared, (
            f"{binary} is a system binary, not a pip distribution; it belongs in the README"
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
