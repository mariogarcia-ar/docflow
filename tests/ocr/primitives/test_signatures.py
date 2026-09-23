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

from docflow.ocr import primitives
from docflow.ocr.primitives import (
    analyze,
    engine,
    execution,
    export,
    extraction,
    files,
    layout,
    metadata,
    pipeline,
    rendering,
    text,
    validation,
)

# The surface `subplan-procesador-ocr.md` §3.4 fixes, grouped as that section groups it. Written
# out rather than derived from `__all__`, because the point is to pin what the *plan* names: a
# module that exported its own invention would satisfy a `__all__`-driven check.
PIPELINE_PRIMITIVES = (
    "load_docling_pipeline",
    "configure_image_pipeline",
    "enable_ocr",
    "enable_table_detection",
    "enable_layout_analysis",
    "normalize_docling_options",
    "should_enable_ocr",
    "should_enable_layout",
    "should_enable_tables",
    "should_enable_reading_order",
)
"""``subplan-procesador-ocr.md`` §3.4's *Pipeline/config* group, name for name.

``enable_ocr``, ``enable_table_detection`` and ``enable_layout_analysis`` are in the plan and in
``OCR-03``'s deliverable list, but ``OCR-02`` **did not declare them**. That went unnoticed
because the surface test was written from the modules rather than from the plan: it asserted the
names that existed instead of the names that were required, so a plan primitive that was never
created could not fail it. The list below is now the plan's, and that is the fix — a test derived
from what has been built can only ever confirm that what has been built is what was built.
"""

EXECUTION_PRIMITIVES = ("convert_image_with_docling",)

EXTRACTION_PRIMITIVES = (
    "build_ocr_document",
    "extract_docling_text",
    "extract_docling_markdown",
    "extract_docling_tables",
    "extract_docling_blocks",
    "extract_docling_layout",
    "extract_docling_metadata",
)
"""``OCR-04`` split the plan's *Extraction* group into its own module.

The subplan groups execution and extraction together in §3.4 and they have different reasons to
change: running the engine is about Docling's execution API while reading its result is about
Docling's *structure*, which is the thing §8's risk table says may move between versions. Keeping
them in one module meant a schema change and an execution change touched the same file.

The names are the plan's; only the module boundary moved, and it is recorded here so the
divergence from §3.4's grouping is visible rather than accidental.
"""

EXPORT_PRIMITIVES = (
    "export_docling_text",
    "export_docling_markdown",
    "export_docling_json",
    "export_docling_tables",
    "serialize_document_json",
)
"""``subplan-procesador-ocr.md`` §3.4's *Export* group, plus one declared extension.

The four ``export_docling_*`` names are the plan's. ``serialize_document_json`` is not, and it is
here deliberately: the determinism posture requires two runs over the same page to produce
byte-identical artifacts, which depends on sorted keys and a fixed indent. A caller handed the
payload alone would be free to serialize it another way, so the one canonical serialization is a
primitive rather than a detail of ``OCR-10``'s writing code.

**These were in ``OCR-04``'s deliverable list and ``OCR-02`` did not declare them** — the same
defect as the three ``enable_*`` primitives, found the same way: by reading the task's scope
against the surface instead of trusting the surface. They now live in their own module, because
an *exporter* turns a whole document into a serializable artifact while an *extractor* turns an
engine item into a contract record, and the exporters are the boundary Docling's own
``export_to_dict`` must not cross.
"""

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
"""§3.4's *Tables* group plus the two Markdown names, in one module.

``process_tables`` is not in §3.4: it is named by ``OCR-07``'s own scope, and it is the function
that turns the tables into ``(name, contents)`` pairs. It is declared separately below because the
plan-surface check compares this tuple against the module's ``__all__``, so a name in both would
have to appear here to pass — and it belongs to the same module for the same reason the rest do.
"""

TABLE_PIPELINE_PRIMITIVES = ("process_tables",)
"""The one table name ``OCR-07``'s scope has and §3.4's palette does not."""

VALIDATION_PRIMITIVES = (
    "validate_ocr_request",
    "validate_ocr_input",
    "validate_ocr_result",
    "validate_output_artifacts",
)

FILES_PRIMITIVES = (
    "create_ocr_directory",
    "build_ocr_output_paths",
    "ensure_directory",
    "write_text_atomic",
    "write_json_atomic",
    "read_json",
)
"""§3.4's *Validation* and *Files* groups, in two tuples and modules.

``OCR-09`` and ``OCR-10`` split what the ``OCR-02`` skeleton declared as one ``persistence.py``,
because §3.4 files them separately and a reader looking up a name should find it where the plan puts
it.
"""

FILES_MACHINERY = (
    "abandon",
    "discard_staged",
    "prune_staging_directory",
    "staging_directory",
    "temp_path",
)
METADATA_MACHINERY = (
    "build_metadata_payload",
    "require_metadata_keys",
)
"""The publication helpers neither §3.4 nor a task scope names, declared as an exception.

They exist because the two acceptance criteria are *about* them: "a forced failure leaves no
``.tmp``
files and no final-named artifacts" is a claim about :func:`~docflow.ocr.primitives.files.abandon`
and :func:`~docflow.ocr.primitives.files.discard_staged`, and "``metadata.json`` carries the seven
required keys" is a claim about
:func:`~docflow.ocr.primitives.metadata.require_metadata_keys`. Hiding them would move the
invariants
somewhere no test could reach them — the defect the image processor's own battery recorded, where
the
required-key guard was *unreachable* until it was extracted.

They are declared rather than private for the reason the image processor's ``atomic.py`` records:
these are the mechanisms the atomicity guarantee is made of, and a reader asking "how is a write
made
atomic here?" should find a documented answer rather than an underscore. The two tuples are split by
owning module because :func:`_locate` searches the groups in order, and a name listed under the
wrong
module fails as "declares no ..." rather than as anything informative.
"""


METADATA_PRIMITIVES = (
    "build_ocr_metadata",
    "merge_ocr_metadata",
    "get_processor_version",
)

ANALYZE_PRIMITIVES = ("analyze_ocr_result",)
"""``OCR-08``'s one name, which §3.4's palette does not list.

§3.4 names the *measurements* - ``count_ocr_characters``, ``is_ocr_empty``, ``count_blocks``,
``calculate_ocr_text_density``, ``count_tables`` - spread across the groups that own their
subjects. ``analyze_ocr_result`` is the task's deliverable and appears in the plan as such (its
scope, and §3.3's flow) rather than in the palette, exactly as ``process_tables`` does for
``OCR-07``. It lives in its own module because it composes primitives from three of the groups
below and belongs to none of them.
"""

ENGINE_PRIMITIVES = (
    "converter_module",
    "docling_module",
    "engine_provenance",
    "get_engine_version",
    "is_engine_available",
    "loaded_engines",
)
"""The seam's functions, which were **never** in this suite before ``OCR-08``.

A hole found by :func:`test_every_module_the_package_exports_is_grouped` rather than by reading:
``engine.py`` shipped in ``OCR-02``, exports six functions, and was absent from ``ALL_GROUPS``, so
none of the checks below ever inspected one of its signatures. Everything passed because nothing
looked - the same shape as the mutation that prompted the check.

The module's three exception classes are deliberately **not** here. A primitive is a function: the
annotation check asks for a return type, which a class has not, and the default-argument check reads
``__init__``, whose defaults are the exception's own contract. Listing them would have meant
weakening both checks for every real primitive to accommodate three names that are not primitives.
"""

ALL_GROUPS = (
    (pipeline, PIPELINE_PRIMITIVES),
    (engine, ENGINE_PRIMITIVES),
    (execution, EXECUTION_PRIMITIVES),
    (extraction, EXTRACTION_PRIMITIVES),
    (export, EXPORT_PRIMITIVES),
    (layout, LAYOUT_PRIMITIVES),
    (text, TEXT_PRIMITIVES),
    (rendering, RENDERING_PRIMITIVES + TABLE_PIPELINE_PRIMITIVES),
    (analyze, ANALYZE_PRIMITIVES),
    (validation, VALIDATION_PRIMITIVES),
    (files, FILES_PRIMITIVES + FILES_MACHINERY),
    (metadata, METADATA_PRIMITIVES + METADATA_MACHINERY),
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


IMPLEMENTED = (
    "abandon",
    "analyze_ocr_result",
    "build_metadata_payload",
    "build_ocr_document",
    "build_ocr_metadata",
    "build_ocr_output_paths",
    "calculate_ocr_text_density",
    "clean_ocr_text",
    "configure_image_pipeline",
    "converter_module",
    "convert_image_with_docling",
    "count_blocks",
    "count_ocr_characters",
    "count_ocr_words",
    "count_tables",
    "create_ocr_directory",
    "discard_staged",
    "docling_module",
    "enable_layout_analysis",
    "enable_ocr",
    "enable_table_detection",
    "engine_provenance",
    "ensure_directory",
    "export_docling_json",
    "export_docling_markdown",
    "export_docling_tables",
    "export_docling_text",
    "extract_docling_blocks",
    "extract_docling_layout",
    "extract_docling_markdown",
    "extract_docling_metadata",
    "extract_docling_tables",
    "extract_docling_text",
    "get_engine_version",
    "get_processor_version",
    "is_engine_available",
    "is_ocr_empty",
    "load_docling_pipeline",
    "loaded_engines",
    "merge_ocr_blocks",
    "merge_ocr_metadata",
    "normalize_bbox",
    "normalize_docling_options",
    "normalize_layout",
    "normalize_markdown",
    "normalize_ocr_text",
    "normalize_table",
    "preserve_reading_order",
    "process_tables",
    "prune_staging_directory",
    "read_json",
    "require_metadata_keys",
    "serialize_document_json",
    "should_enable_layout",
    "should_enable_ocr",
    "should_enable_reading_order",
    "should_enable_tables",
    "staging_directory",
    "table_to_json",
    "table_to_markdown",
    "temp_path",
    "validate_ocr_input",
    "validate_ocr_request",
    "validate_ocr_result",
    "validate_output_artifacts",
    "write_json_atomic",
    "write_text_atomic",
)
"""Primitives whose tasks have landed, so they no longer raise ``NotImplementedError``.

Each of ``OCR-03`` … ``OCR-10`` moves its own names in as it lands. The list is what keeps the
stub guard meaningful in both directions: without it, a primitive that had been implemented would
fail a test asserting it still refuses, and the temptation would be to delete that test rather
than to say which names are real.
"""


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


# Primitives ``OCR-03`` and later have implemented are no longer stubs, so the guard below no
# longer applies to them. Each task moves its own names out as it lands.
@pytest.mark.parametrize("name", [n for _, names in ALL_GROUPS for n in names])
def test_every_primitive_is_implemented_not_a_stub(name: str) -> None:
    """A primitive either refuses to answer or is implemented — never a plausible stand-in.

    The assertion runs in whichever direction the name's task has reached. While ``OCR-03`` …
    ``OCR-10`` are still landing, most of the surface must **refuse**: a skeleton returning ``0``
    would put a measured-looking zero into every :class:`~docflow.ocr.contracts.OCRMetrics`. The
    names in :data:`IMPLEMENTED` have landed and must have stopped refusing.

    A task that implements a primitive without moving its name into :data:`IMPLEMENTED` fails
    here, which is the prompt to update the list in the same change.
    """
    function = getattr(_locate(name), name)
    source = inspect.getsource(function)
    has_stub = "raise NotImplementedError" in source

    if name in IMPLEMENTED:
        assert not has_stub, (
            f"{name} is implemented but still carries a NotImplementedError body"
        )
    else:
        assert has_stub, (
            f"{name} no longer raises NotImplementedError. If it has just been implemented, "
            "move it into IMPLEMENTED in the same change."
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


def test_every_module_the_package_exports_is_grouped() -> None:
    """Every module in the package is in ``ALL_GROUPS``, checked from outside the tuple.

    A mutation that dropped the newly added ``analyze`` entry **survived** an earlier version of
    :func:`test_the_groupings_cover_every_exported_primitive`, and the reason is worth stating:
    that test derived *both* sides of its comparison from ``ALL_GROUPS`` — the modules it read
    ``__all__`` from and the names it expected — so removing an entry removed the module from the
    check as well as from the expectation. It could only ever compare the tuple with itself.

    The source of truth here is :data:`docflow.ocr.primitives.__all__`, which the package declares
    and this suite does not: a module missing from the groups means its primitives are unmeasured by
    every test above, and that is exactly the state the mutation produced while everything passed.
    """
    assert set(primitives.__all__) == {
        module.__name__.rsplit(".", 1)[-1] for module, _ in ALL_GROUPS
    }


def test_the_groupings_cover_every_exported_primitive() -> None:
    """No module exports a primitive this suite does not know about.

    The checks above are driven by the plan's names, so an *extra* export would slip past them -
    and an extra export is how a private helper becomes public API by accident.

    "Primitive" here means a **function**, which is what the checks above can inspect: they ask
    for a return annotation and for argument defaults, and a class answers neither. ``engine.py``
    exports three exception classes beside its six functions, and counting those as primitives
    would have meant weakening both checks for forty real ones to accommodate them.
    """
    declared = {name for _, names in ALL_GROUPS for name in names}
    exported = {
        name
        for module, _ in ALL_GROUPS
        for name in module.__all__
        if inspect.isfunction(getattr(module, name, None))
    }

    assert exported == declared, (
        f"exported but not in the plan's groups: {sorted(exported - declared)}; "
        f"in the groups but not exported: {sorted(declared - exported)}"
    )
