"""The image engine seam - the only module that knows which library reads images.

**OpenCV** is the engine this processor is built on (``subplan-procesador-image.md`` §3,
from the idea's §"Implementaciones reemplazables"); **Pillow** is the documented drop-in
alternative, and ``numpy`` comes with either as the array vocabulary the primitives speak.
The whole of that dependency is contained here: the libraries are named one by one, resolved
on demand, probed for a version, and reached through helpers that turn a missing engine into
a typed failure.

Nothing outside :mod:`docflow.image.primitives` may import this module. Neither the
orchestrator nor another processor reaches it: both go through
:func:`docflow.image.process_image`.

Two rules shape it, and both come from the plan:

* **The engine is explicit, never a substitute.** There is no configuration lookup with a
  silent fallback behind it. Asking for OpenCV when OpenCV is absent raises
  :class:`ImageEngineNotAvailableError` - it does not quietly measure the image with Pillow
  instead, which would put one engine's numbers in another engine's provenance record.
* **Importing the package touches no engine.** ``GEN-01`` asserts that a clean interpreter
  can import every sub-package without pulling a library in, so the engines are resolved
  *lazily*, on first use. ``import docflow.image.primitives.engine`` must stay cheap and
  side-effect free; :func:`engine_module` is what actually loads one, and it says so.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from dataclasses import dataclass
from enum import StrEnum
from types import ModuleType
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray

    ImageArray = NDArray[np.uint8]
    """An image as a ``(height, width, channels)`` array of 8-bit samples, channels in RGB order.

    This is the *engine-agnostic* image the rest of the processor passes around, and it is what
    makes the two engines swappable without the contract noticing. The engines disagree on the
    channel order - OpenCV decodes to BGR, Pillow to RGB - so the conversion happens once, inside
    :mod:`docflow.image.primitives.load`, and nothing downstream has to know which engine ran.

    A grayscale image is ``(height, width)`` with no trailing axis, exactly as both engines
    represent it.
    """
else:
    # `Any` at runtime, `NDArray[np.uint8]` to a type checker; the real type is named above, only
    # for static analysis. A module-level `import numpy` would turn a missing numpy into a bare
    # ImportError at `import docflow.image.primitives` - exactly the untyped failure
    # `array_module` exists to prevent - so the runtime annotation is deliberately wider. It still
    # resolves, which is what keeps `typing.get_type_hints` working on every primitive.
    ImageArray = Any

OPENCV_ENGINE_NAME = "opencv"
"""Name under which the OpenCV-backed implementation records its provenance."""

PILLOW_ENGINE_NAME = "pillow"
"""Name under which the Pillow-backed implementation records its provenance."""

ARRAY_LIBRARY_NAME = "numpy"
"""The array vocabulary the primitives speak, whichever engine produced the pixels.

Not an engine: it does not decode or transform anything on its own. It is recorded
separately in ``metadata.json`` because the numeric types a measurement returns depend on
it, so a re-run is only comparable when its version is known too.
"""

CHANNEL_COUNT_RGB = 3
"""Channels in a colour :data:`ImageArray`."""

CHANNEL_RANK_GRAYSCALE = 2
"""Shape rank of a grayscale :data:`ImageArray`; its axes are height and width with no channels."""


class EngineChoice(StrEnum):
    """The image engine to use, named explicitly by the caller.

    An enum rather than a string so a typo is a failure at the call site rather than a
    missing engine discovered halfway through a document. There is no ``AUTO`` member on
    purpose: "pick one for me" is exactly the silent substitution the plan forbids.
    """

    OPENCV = OPENCV_ENGINE_NAME
    PILLOW = PILLOW_ENGINE_NAME


_MODULE_BY_ENGINE: dict[EngineChoice, str] = {
    EngineChoice.OPENCV: "cv2",
    EngineChoice.PILLOW: "PIL",
}

_OPERATIONS_MODULE_BY_ENGINE: dict[EngineChoice, str] = {
    EngineChoice.OPENCV: "cv2",
    EngineChoice.PILLOW: "PIL.Image",
}
"""Where each engine's *operations* live, which is not where its version lives.

OpenCV's package is its whole API, so one name covers both. Pillow splits them: the version is
``PIL.__version__`` but the API is ``PIL.Image``, and importing ``PIL`` alone does **not** make
``PIL.Image`` reachable - it is a lazily imported submodule. That asymmetry is a fact about the
engines, so it is recorded here rather than rediscovered in every primitive.
"""


class ImageEngineError(RuntimeError):
    """Base of the typed failures this seam reports."""


class ImageEngineNotAvailableError(ImageEngineError):
    """A requested engine, or the array library, cannot be imported.

    Recoverable by neither the processor nor the orchestrator: the engine is a deployment
    precondition. It is reported as a type so a caller can classify it, never as an untyped
    ImportError and never by falling back to the other engine.

    Attributes:
        engine: The engine that was asked for, or ``None`` for the array library.
        library: The import name that could not be resolved.
    """

    def __init__(self, library: str, engine: EngineChoice | None = None) -> None:
        self.engine = engine
        self.library = library
        subject = (
            f"the {engine.value} engine" if engine is not None else "the array library"
        )
        super().__init__(
            f"{subject} requires {library!r}, which is not importable; install it or "
            f"select an engine that is installed - no engine is substituted automatically"
        )


class ImageEngineExecutionError(ImageEngineError):
    """An engine call ran and failed.

    Attributes:
        operation: The primitive operation that was attempted.
        engine: The engine that was in use.
        detail: The engine's own message, kept verbatim for diagnosis.
    """

    def __init__(self, operation: str, engine: EngineChoice, detail: str) -> None:
        self.operation = operation
        self.engine = engine
        self.detail = detail
        message = f"{operation} failed under the {engine.value} engine"
        super().__init__(f"{message}: {detail}" if detail else message)


class ImageEngineCapabilityError(ImageEngineError):
    """The engine is installed but does not provide an operation the primitive needs.

    This is the honest answer at an engine boundary that has been reached and cannot be crossed.
    The two engines are not equivalent: OpenCV is an image-processing library and Pillow is a codec,
    so the measuring and transforming primitives are built on OpenCV and a Pillow-only deployment
    cannot compute a blur score at all. The alternative is to reimplement filtering and
    thresholding on raw arrays, which is the "scope creep into a full image-processing library" the
    subplan lists as a risk and forbids.

    The plan requires that a swap change only ``primitives/`` and never the contract; it does not
    require every operation to exist under every engine. Reporting the gap as a type keeps the
    choice visible instead of failing in whatever way an attribute lookup happens to fail.

    Attributes:
        operation: The operation that is missing.
        engine: The engine that lacks it.
    """

    def __init__(self, operation: str, engine: EngineChoice) -> None:
        self.operation = operation
        self.engine = engine
        super().__init__(
            f"the {engine.value} engine provides no {operation!r}; it is a codec, not an "
            f"image-processing library - use an engine that implements it, or port the primitive"
        )


@dataclass(frozen=True)
class Engine:
    """An engine and its version, for an artifact's provenance.

    Attributes:
        name: Engine name - one of :class:`EngineChoice`'s values.
        version: Version the engine reports; never guessed and never blank.
    """

    name: str
    version: str


@dataclass(frozen=True)
class EngineProvenance:
    """Everything ``metadata.json`` needs to describe how the pixels were produced.

    Attributes:
        engine: The engine and its version.
        array_library: The array library's name and version.
    """

    engine: Engine
    array_library: Engine


def engine_module(engine: EngineChoice) -> ModuleType:
    """Import and return the module an engine lives in.

    The single point where a library is actually loaded, which is what keeps
    ``import docflow.image.primitives.engine`` free of engines - ``GEN-01`` asserts exactly
    that, and a module-level ``import cv2`` here would break it.

    Args:
        engine: The engine to load.

    Returns:
        The engine's module object.

    Raises:
        ImageEngineNotAvailableError: The library is not importable.
    """
    name = _MODULE_BY_ENGINE[engine]
    try:
        return importlib.import_module(name)
    except ImportError as failure:
        raise ImageEngineNotAvailableError(name, engine) from failure


def operations_module(engine: EngineChoice) -> ModuleType:
    """Import and return the module an engine's operations live in.

    Distinct from :func:`engine_module` because "where the version lives" and "where the API
    lives" are the same place for OpenCV and two different places for Pillow.

    Args:
        engine: The engine whose operations are needed.

    Returns:
        The engine's operations module.

    Raises:
        ImageEngineNotAvailableError: The library is not importable.
    """
    name = _OPERATIONS_MODULE_BY_ENGINE[engine]
    try:
        return importlib.import_module(name)
    except ImportError as failure:
        raise ImageEngineNotAvailableError(name, engine) from failure


def engine_operation(engine: EngineChoice, name: str) -> object:
    """Return one of an engine's operations, or report that it has none.

    Primitives reach the engine through this rather than through attribute access, so a missing
    operation is a typed :class:`ImageEngineCapabilityError` naming the operation and the engine
    instead of a bare ``AttributeError`` naming neither.

    Args:
        engine: The engine to look in.
        name: The operation's name as the engine spells it.

    Returns:
        The operation, ready to call.

    Raises:
        ImageEngineNotAvailableError: The engine is missing.
        ImageEngineCapabilityError: The engine is present but has no such operation.
    """
    module = operations_module(engine)
    found = getattr(module, name, None)
    if found is None:
        raise ImageEngineCapabilityError(name, engine)
    return found


def array_module() -> ModuleType:
    """Import and return the array library.

    Returns:
        ``numpy``'s module object.

    Raises:
        ImageEngineNotAvailableError: ``numpy`` is not importable.
    """
    try:
        return importlib.import_module(ARRAY_LIBRARY_NAME)
    except ImportError as failure:
        raise ImageEngineNotAvailableError(ARRAY_LIBRARY_NAME) from failure


def is_engine_available(engine: EngineChoice) -> bool:
    """Report whether an engine can be imported, without importing it into this process.

    Uses ``importlib.util.find_spec`` rather than a real import so a caller can *ask* without
    paying for the load - the difference matters for a probe that runs before any document.

    Args:
        engine: The engine to check.

    Returns:
        ``True`` when the library is findable.
    """
    try:
        return importlib.util.find_spec(_MODULE_BY_ENGINE[engine]) is not None
    except (ImportError, ValueError):
        # A missing parent package or a malformed spec both mean "cannot import it".
        return False


def engine_version(engine: EngineChoice) -> str:
    """Read the version an engine reports.

    Args:
        engine: The engine to probe.

    Returns:
        The version string, e.g. ``"4.11.0"``.

    Raises:
        ImageEngineNotAvailableError: The library is missing.
        ImageEngineExecutionError: The library is present but reports no version this module
            can read. A blank version is never returned: the provenance of an artifact has to
            name a real engine version.
    """
    module = engine_module(engine)
    version = getattr(module, "__version__", None)
    if not version:
        raise ImageEngineExecutionError(
            "read the engine version", engine, "the library reports no __version__"
        )
    return str(version)


def array_library_version() -> str:
    """Read the array library's version.

    Returns:
        The version string.

    Raises:
        ImageEngineNotAvailableError: ``numpy`` is missing.
        ImageEngineExecutionError: It reports no readable version.
    """
    module = array_module()
    version = getattr(module, "__version__", None)
    if not version:
        raise ImageEngineExecutionError(
            "read the array library version",
            EngineChoice.OPENCV,
            "numpy reports no __version__",
        )
    return str(version)


def get_engine(engine: EngineChoice) -> Engine:
    """Return an engine and its version, for an artifact's provenance.

    Args:
        engine: The engine to describe.

    Returns:
        The engine record.

    Raises:
        ImageEngineNotAvailableError: The engine is missing.
        ImageEngineExecutionError: Its version cannot be read.
    """
    return Engine(name=engine.value, version=engine_version(engine))


def get_provenance(engine: EngineChoice) -> EngineProvenance:
    """Return everything ``metadata.json`` needs about how the pixels were produced.

    Args:
        engine: The engine in use.

    Returns:
        The engine and the array library, each with its version.

    Raises:
        ImageEngineNotAvailableError: The engine or the array library is missing.
        ImageEngineExecutionError: A version cannot be read.
    """
    return EngineProvenance(
        engine=get_engine(engine),
        array_library=Engine(name=ARRAY_LIBRARY_NAME, version=array_library_version()),
    )


def loaded_engines() -> list[str]:
    """Return the engine libraries currently imported into this process.

    Used by the tests that assert the seam is lazy: importing the package must leave this
    list empty.

    Returns:
        The import names present in :data:`sys.modules`, sorted.
    """
    return sorted(name for name in sys.modules if name in _MODULE_BY_ENGINE.values())


__all__ = [
    "ARRAY_LIBRARY_NAME",
    "CHANNEL_COUNT_RGB",
    "CHANNEL_RANK_GRAYSCALE",
    "OPENCV_ENGINE_NAME",
    "PILLOW_ENGINE_NAME",
    "Engine",
    "EngineChoice",
    "EngineProvenance",
    "ImageArray",
    "ImageEngineCapabilityError",
    "ImageEngineError",
    "ImageEngineExecutionError",
    "ImageEngineNotAvailableError",
    "array_library_version",
    "array_module",
    "engine_module",
    "engine_operation",
    "engine_version",
    "get_engine",
    "get_provenance",
    "is_engine_available",
    "loaded_engines",
    "operations_module",
]
