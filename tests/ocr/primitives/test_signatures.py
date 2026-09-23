"""Tests for the declared OCR primitive surface (``OCR-02``).

``OCR-02``'s scope is the seam plus *the signatures* of ``OCR-03`` … ``OCR-10``. This module pins
that surface down, so a later task cannot quietly rename or drop a primitive: the names are the
interfaces the rest of the processor is written against, and changing one is a decision rather
than a refactor.

It also asserts every stub refuses to answer. A skeleton returning a plausible zero would put a
measured-looking ``0`` into :class:`~docflow.ocr.contracts.OCRMetrics` for every image, which is
the silent stand-in the project forbids - so the honest place for it to stop is
``NotImplementedError``.
"""

from __future__ import annotations

import inspect
import typing
from collections.abc import Callable

import pytest

from docflow.ocr.primitives import (
    execution,
    layout,
    metadata,
    persistence,
    pipeline,
    rendering,
    text,
)

# The surface `subplan-procesador-ocr.md` §3.4 fixes, grouped as that section groups it. Written
# out rather than derived from `__all__`, because the point is to pin what the *plan* names: a
# module that exported its own invention would satisfy a `__all__`-driven check.
PIPELINE_PRIMITIVES = (
    "load_docling_pipeline",
    "configure_image_pipeline",
    "normalize_docling_options",
    "should_enable_ocr",
    "should_enable_layout",
    "should_enable_tables",
    "should_enable_reading_order",
)

EXECUTION_PRIMITIVES = (
    "convert_image_with_docling",
    "extract_docling_text",
    "extract_docling_markdown",
    "extract_docling_tables",
    "extract_docling_blocks",
    "extract_docling_layout",
    "extract_docling_metadata",
)

LAYOUT_PRIMITIVES = (
    "normalize_bbox",
    "normalize_layout",
    "preserve_reading_order",
    "count_blocks",
    "calculate_ocr_text_density",
)

TEXT_PRIMITIVES = (
    "count_ocr_characters",
    "count_ocr_words",
    "clean_ocr_text",
    "normalize_ocr_text",
    "is_ocr_empty",
)

RENDERING_PRIMITIVES = (
    "normalize_markdown",
    "merge_ocr_blocks",
    "count_tables",
    "normalize_table",
    "table_to_markdown",
    "table_to_json",
)

PERSISTENCE_PRIMITIVES = (
    "validate_ocr_request",
    "validate_ocr_input",
    "validate_ocr_result",
    "validate_output_artifacts",
    "build_ocr_output_paths",
    "create_ocr_directory",
    "ensure_directory",
    "write_text_atomic",
    "write_json_atomic",
    "read_json",
)

METADATA_PRIMITIVES = (
    "build_ocr_metadata",
    "merge_ocr_metadata",
    "get_processor_version",
)

ALL_GROUPS = (
    (pipeline, PIPELINE_PRIMITIVES),
    (execution, EXECUTION_PRIMITIVES),
    (layout, LAYOUT_PRIMITIVES),
    (text, TEXT_PRIMITIVES),
    (rendering, RENDERING_PRIMITIVES),
    (persistence, PERSISTENCE_PRIMITIVES),
    (metadata, METADATA_PRIMITIVES),
)


def _locate(name: str) -> object:
    """Return the module that declares a primitive.

    Args:
        name: The primitive's name.

    Returns:
        The owning module.
    """
    for module, names in ALL_GROUPS:
        if name in names:
            return module
    raise AssertionError(f"no group declares {name}")


def _primitive(module: object, name: str) -> Callable[..., object]:
    """Return a named primitive, failing the test if it is absent.

    Args:
        module: The module to look in.
        name: The primitive's name.

    Returns:
        The callable.
    """
    assert hasattr(module, name), f"{module.__name__} declares no {name}"
    return typing.cast("Callable[..., object]", getattr(module, name))


@pytest.mark.parametrize(
    ("module", "names"),
    ALL_GROUPS,
    ids=[module.__name__.rsplit(".", maxsplit=1)[-1] for module, _ in ALL_GROUPS],
)
def test_every_primitive_the_plan_names_exists(
    module: object, names: tuple[str, ...]
) -> None:
    """The surface is the plan's, name for name."""
    for name in names:
        _primitive(module, name)


@pytest.mark.parametrize("name", [n for _, names in ALL_GROUPS for n in names])
def test_every_primitive_is_implemented_not_a_stub(name: str) -> None:
    """OCR-03 … OCR-10 have not run yet, so every body still refuses to answer.

    This is the inverse of the guard the image suite grew: there the stubs had been filled, and
    the test flipped to assert no ``NotImplementedError`` remained. Here nothing is implemented,
    so the assertion is that the surface refuses rather than returning a plausible value. It must
    be **updated** by each of OCR-03 … OCR-10 as they land, which is the point: a task that
    implements a primitive without removing its stub guard would be caught.
    """
    source = inspect.getsource(_locate(name))
    assert "raise NotImplementedError" in source, (
        f"{name} no longer raises NotImplementedError. If it has just been implemented, move it "
        "out of this test's list in the same change."
    )


@pytest.mark.parametrize("name", [n for _, names in ALL_GROUPS for n in names])
def test_every_primitive_is_fully_annotated(name: str) -> None:
    """A signature the rest of the processor is written against must be complete."""
    primitive = _primitive(_locate(name), name)
    signature = inspect.signature(primitive)
    hints = typing.get_type_hints(primitive)

    assert "return" in hints, f"{name} has no return annotation"
    for parameter in signature.parameters.values():
        if parameter.name in {"self", "cls"}:
            continue
        assert parameter.name in hints, f"{name} leaves {parameter.name} unannotated"


@pytest.mark.parametrize(
    "name",
    [n for _, names in ALL_GROUPS for n in names if n != "get_processor_version"],
)
def test_no_primitive_carries_a_default_argument(name: str) -> None:
    """A default is a silent stand-in unless it is argued for, and none of these is.

    ``get_processor_version`` is exempt because it takes no arguments at all, which the assertion
    below checks rather than skips over.
    """
    signature = inspect.signature(_primitive(_locate(name), name))

    for parameter in signature.parameters.values():
        if parameter.name in {"self", "cls"}:
            continue
        assert parameter.default is inspect.Parameter.empty, (
            f"{name} defaults {parameter.name} to {parameter.default!r}; the plan requires every "
            "option to be named explicitly"
        )


def test_the_processor_version_is_a_constant_not_a_lookup() -> None:
    """Reading it must not need the package to be installed.

    ``pyproject.toml`` puts ``src/`` on the path so the suite runs from a clean checkout with no
    install step. A distribution lookup would raise ``PackageNotFoundError`` in exactly that
    configuration, which is the one the gates run in.
    """
    version = metadata.get_processor_version()

    assert version
    assert version == metadata.PROCESSOR_VERSION


def test_the_groupings_cover_every_exported_primitive() -> None:
    """No module exports a primitive this suite does not know about.

    The checks above are driven by the plan's names, so an *extra* export would slip past them -
    and an extra export is how a private helper becomes public API by accident.
    """
    declared = {name for _, names in ALL_GROUPS for name in names}
    exported = {
        name
        for module, _ in ALL_GROUPS
        for name in module.__all__
        if callable(getattr(module, name, None))
    }

    assert exported == declared, (
        f"exported but not in the plan's groups: {sorted(exported - declared)}; "
        f"in the groups but not exported: {sorted(declared - exported)}"
    )
