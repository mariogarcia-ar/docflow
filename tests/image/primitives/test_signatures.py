"""Tests for the declared-but-unimplemented primitive signatures (``IMG-02``).

``IMG-02``'s scope is the package plus *the signatures* of ``IMG-03`` … ``IMG-05``. This module
pins that surface down, so a later task cannot quietly rename or drop a primitive: the names are
the interfaces the rest of the processor is written against, and changing one is a decision, not
a refactor.

It also asserts each stub refuses to answer. A skeleton that returned a plausible zero would put
a measured-looking ``0`` into ``ImageMetrics`` for every image, which is precisely the silent
stand-in the project forbids - so the honest place for it to stop is ``NotImplementedError``.
"""

from __future__ import annotations

import inspect
import typing
from collections.abc import Callable
from dataclasses import FrozenInstanceError

import pytest

from docflow.image.primitives import analysis, load, transform
from docflow.image.primitives.engine import EngineChoice

LOAD_PRIMITIVES = (
    "load_image",
    "save_image",
    "get_image_metadata",
    "get_image_dimensions",
)

ANALYSIS_PRIMITIVES = (
    "calculate_blur_score",
    "calculate_sharpness_score",
    "calculate_contrast_score",
    "calculate_brightness_score",
    "calculate_noise_score",
    "detect_orientation",
    "detect_skew_angle",
    "detect_text_regions",
    "calculate_text_coverage",
)

TRANSFORM_PRIMITIVES = (
    "rotate_image",
    "deskew_image",
    "resize_image",
    "convert_to_grayscale",
    "binarize_image",
    "denoise_image",
    "sharpen_image",
    "normalize_contrast",
    "normalize_brightness",
    "convert_image_format",
    "compress_image",
)


ENGINE = EngineChoice.OPENCV
"""The engine every stub is called with; none of them reaches far enough to use it."""


def _call(primitive: Callable[..., object]) -> object:
    """Call a primitive with placeholder arguments of every declared kind.

    The stubs are called for real rather than merely inspected, because "declared but
    unimplemented" is only true if the body actually stops. Arguments are filled by annotation so
    the call reaches the body instead of failing earlier in argument binding.
    """
    arguments: dict[str, object] = {}
    for name, parameter in inspect.signature(primitive).parameters.items():
        if name == "engine":
            arguments[name] = ENGINE
        elif parameter.annotation in ("ModuleType", "int", "float"):
            arguments[name] = 1
        elif parameter.annotation == "str":
            arguments[name] = "placeholder"
        else:
            arguments[name] = None
    return primitive(**arguments)


def _primitive(module: object, name: str) -> Callable[..., object]:
    """Return a named primitive, failing the test if it is absent."""
    assert hasattr(module, name), f"{module.__name__} declares no {name}"
    return typing.cast("Callable[..., object]", getattr(module, name))


@pytest.mark.parametrize("name", LOAD_PRIMITIVES)
def test_the_load_primitives_are_declared_and_still_stubs(name: str) -> None:
    """IMG-03's surface exists and refuses to answer until it is implemented."""
    with pytest.raises(NotImplementedError):
        _call(_primitive(load, name))


@pytest.mark.parametrize("name", ANALYSIS_PRIMITIVES)
def test_the_analysis_primitives_are_declared_and_still_stubs(name: str) -> None:
    """IMG-04's surface exists and refuses to answer until it is implemented."""
    with pytest.raises(NotImplementedError):
        _call(_primitive(analysis, name))


@pytest.mark.parametrize("name", TRANSFORM_PRIMITIVES)
def test_the_transformation_primitives_are_declared_and_still_stubs(name: str) -> None:
    """IMG-05's surface exists and refuses to answer until it is implemented."""
    with pytest.raises(NotImplementedError):
        _call(_primitive(transform, name))


@pytest.mark.parametrize(
    ("module", "name"),
    [
        (load, "load_image"),
        (analysis, "calculate_blur_score"),
        (transform, "rotate_image"),
    ],
)
def test_every_primitive_requires_the_engine_as_an_explicit_argument(
    module: object, name: str
) -> None:
    """The engine is a parameter, not a module-level default.

    A primitive that resolved the engine itself would be a second seam, and the one place the
    engine choice could be changed without anyone noticing.
    """
    signature = inspect.signature(_primitive(module, name))
    assert "engine" in signature.parameters
    engine_parameter = signature.parameters["engine"]
    assert engine_parameter.annotation == "EngineChoice"
    assert engine_parameter.default is inspect.Parameter.empty


@pytest.mark.parametrize("module", [load, analysis, transform])
def test_every_annotation_in_the_skeleton_resolves(module: object) -> None:
    """A postponed annotation still has to name a type that exists.

    A bare string is trivially "present"; this is what stops a typo in a hint from surviving as
    an unresolvable name until someone introspects the module at runtime. Functions are checked
    one at a time because ``get_type_hints`` on the module itself reports only its variables.
    """
    functions = [
        (name, value)
        for name, value in vars(module).items()
        if inspect.isfunction(value) and value.__module__ == module.__name__
    ]
    assert functions, f"{module.__name__} declares no functions"

    for name, primitive in functions:
        hints = typing.get_type_hints(primitive)
        assert "return" in hints, f"{name} has an unresolvable return annotation"


@pytest.mark.parametrize(
    "name", LOAD_PRIMITIVES + ANALYSIS_PRIMITIVES + TRANSFORM_PRIMITIVES
)
def test_every_primitive_is_fully_documented_and_typed(name: str) -> None:
    """The DoD asks for complete hints and Google-style docstrings."""
    primitive = _locate(name)

    signature = inspect.signature(primitive)
    assert signature.return_annotation is not inspect.Signature.empty
    for parameter in signature.parameters.values():
        assert parameter.annotation is not inspect.Parameter.empty, (
            f"{name}'s parameter {parameter.name} is unannotated"
        )

    doc = inspect.getdoc(primitive) or ""
    assert "Args:" in doc
    assert "Returns:" in doc


def test_the_image_dimensions_record_is_immutable() -> None:
    """Contract records are frozen so a primitive cannot edit one in place."""
    dimensions = load.ImageDimensions(width=10, height=20)
    with pytest.raises(FrozenInstanceError):
        dimensions.width = 30  # type: ignore[misc]


def _locate(name: str) -> Callable[..., object]:
    """Return the primitive of that name from whichever module declares it."""
    for module in (load, analysis, transform):
        if hasattr(module, name):
            return _primitive(module, name)
    raise AssertionError(f"no module declares {name}")
