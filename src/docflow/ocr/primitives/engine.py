"""The OCR engine seam - the only module that knows Docling exists.

**Docling** is the engine this processor is built on (``subplan-procesador-ocr.md`` §3.5), and
it is the *only* one: unlike the image processor, there is no alternative to swap in, no
``EngineChoice`` enum and no engine option. That is a deliberate difference rather than an
omission. The image processor needed a choice because OpenCV and Pillow are genuinely
interchangeable for its work and the plan documents Pillow as the drop-in; the OCR plan says
"Docling is the only OCR engine" and puts a selectable engine out of bounds.

So the whole of this module is one dependency, contained: it names the library once, resolves
it lazily, reads its version, and turns its absence into a typed failure.

Nothing outside :mod:`docflow.ocr.primitives` may import this module. Neither the orchestrator
nor another processor reaches it: both go through :func:`docflow.ocr.process_ocr_image`.

Two rules shape it, and both come from the plan:

* **No silent substitution.** Asking for an OCR run when Docling is absent raises
  :class:`OCREngineNotAvailableError`. It does not quietly return an empty extraction, which
  would put "no text on this page" and "no engine installed" in the same result and let a
  caller reuse the second as if it were the first.
* **Importing the package touches no engine.** ``GEN-01`` asserts that a clean interpreter can
  import every sub-package without pulling a library in, so Docling is resolved *lazily*, on
  first use. ``import docflow.ocr.primitives.engine`` must stay cheap and side-effect free;
  :func:`docling_module` is what actually loads it, and it says so.

**The version pin is load-bearing, not paperwork.** ``subplan-procesador-ocr.md`` §3.6 makes
"same image + same engine version + same normalized options ⇒ same logical output structure"
the determinism posture, and §8 lists "Docling schema changes between versions" as a risk with
this module as the mitigation. A recorded version is what makes a stored extraction auditable:
without it, a re-run that produces different structure has no way to say whether the input
changed or the engine did.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
import sys
from types import ModuleType
from typing import Final

ENGINE_NAME: Final[str] = "docling"
"""The engine's name, as it appears in every artifact's ``metadata.json``.

A constant rather than a literal at each call site: this string is the engine's identity in a
provenance record, and two spellings of it would be two engines as far as a reader is
concerned.
"""

DOCLING_MODULE_NAME: Final[str] = "docling"
"""The import name the engine is resolved by."""

DOCLING_CONVERTER_MODULE_NAME: Final[str] = "docling.document_converter"
"""Where Docling's conversion API lives.

A *submodule*, not an attribute of the package: ``import docling`` does not make
``DocumentConverter`` reachable, because Docling imports its submodules lazily. Measured, not
assumed - ``hasattr(docling, 'document_converter')`` is ``False`` on Docling 2.126.0 while
``importlib.import_module('docling.document_converter')`` succeeds.

Named here, in the seam, so that ``OCR-03`` and ``OCR-04`` do not each reach into the library
and pick their own entry point. Which module this processor drives is a decision of *one*
module, and this is it.

``# TODO: [MVP]`` the path is asserted by the seam tests; the API surface it exposes is not
exercised until ``OCR-04`` runs a real conversion.
"""

DOCLING_CONVERTER_ATTRIBUTE: Final[str] = "DocumentConverter"
"""The class inside :data:`DOCLING_CONVERTER_MODULE_NAME` that performs a conversion."""

DOCLING_VERSION_UNKNOWN: Final[str] = "UNKNOWN"
"""Recorded when the library is importable but reports no version.

Distinct from a blank string on purpose. A blank ``engine_version`` reads as "we did not bother
to record it"; ``UNKNOWN`` reads as "we looked and the library would not say", which is the
honest answer and the one a re-run comparison needs.
"""


class OCREngineError(RuntimeError):
    """Base of the typed failures this seam reports."""


class OCREngineNotAvailableError(OCREngineError):
    """The OCR engine cannot be imported.

    Recoverable by neither the processor nor the orchestrator: the engine is a deployment
    precondition. It is reported as a type so a caller can classify it, never as an untyped
    ``ImportError`` and never by falling back to something else - there is nothing to fall back
    to, which is precisely why the failure must be loud.

    Attributes:
        library: The import name that could not be resolved.
    """

    def __init__(self, library: str) -> None:
        self.library = library
        super().__init__(
            f"the OCR engine requires {library!r}, which is not importable; install the "
            f"project's dependencies - this processor has no alternative engine and does not "
            f"substitute one"
        )


class OCREngineExecutionError(OCREngineError):
    """An engine call ran and failed.

    Attributes:
        operation: The primitive operation that was attempted.
        detail: The engine's own message, kept verbatim for diagnosis.
    """

    def __init__(self, operation: str, detail: str) -> None:
        self.operation = operation
        self.detail = detail
        message = f"{operation} failed in the {ENGINE_NAME} engine"
        super().__init__(f"{message}: {detail}" if detail else message)


def docling_module() -> ModuleType:
    """Import and return the Docling package.

    The one place the library is loaded. Called by every primitive that needs it, so no other
    module has to decide whether Docling is importable or how to report that it is not.

    Returns:
        The ``docling`` module.

    Raises:
        OCREngineNotAvailableError: The library is not importable.
    """
    try:
        return importlib.import_module(DOCLING_MODULE_NAME)
    except ImportError as failure:
        raise OCREngineNotAvailableError(DOCLING_MODULE_NAME) from failure


def is_engine_available() -> bool:
    """Report whether the engine could be loaded, without loading it.

    Uses ``find_spec`` rather than importing: a caller asking "is OCR possible here?" should not
    pay Docling's import cost - which is substantial - to find out, and should not have the
    answer depend on the side effects of loading it.

    Returns:
        ``True`` when the library is importable.
    """
    try:
        return importlib.util.find_spec(DOCLING_MODULE_NAME) is not None
    except (ImportError, ValueError):
        return False


def converter_module() -> ModuleType:
    """Import and return the module holding Docling's conversion API.

    Distinct from :func:`docling_module` because the two answer different questions: the package
    is where the *version* lives and the submodule is where the *API* lives. A caller that only
    needs a version should not pay the conversion import, which pulls in the whole model stack.

    Returns:
        The ``docling.document_converter`` module.

    Raises:
        OCREngineNotAvailableError: The library, or that submodule, is not importable.
    """
    docling_module()
    try:
        return importlib.import_module(DOCLING_CONVERTER_MODULE_NAME)
    except ImportError as failure:
        raise OCREngineNotAvailableError(DOCLING_CONVERTER_MODULE_NAME) from failure


def get_engine_version() -> str:
    """Return the installed Docling version, for ``metadata.json``.

    Read from the *distribution* rather than from a module attribute. Docling's package does not
    reliably expose ``__version__``, and one comes from the installed metadata while the other
    comes from whatever the source tree happens to say - two answers to one question, which is
    worse than none.

    Returns:
        The version string, or :data:`DOCLING_VERSION_UNKNOWN` when the distribution is
        importable but reports nothing.

    Raises:
        OCREngineNotAvailableError: The library is not importable at all.
    """
    docling_module()
    try:
        return importlib.metadata.version(DOCLING_MODULE_NAME)
    except importlib.metadata.PackageNotFoundError:
        return DOCLING_VERSION_UNKNOWN


def engine_provenance() -> dict[str, str]:
    """Return the engine name and version, as ``metadata.json`` records them.

    A dict rather than a record because the two values go straight into the metadata payload and
    nothing in the processor computes with them.

    Returns:
        ``{"engine": "docling", "engine_version": ...}``.
    """
    return {"engine": ENGINE_NAME, "engine_version": get_engine_version()}


def loaded_engines() -> list[str]:
    """Return the engine libraries currently imported into this process.

    Used by the tests that assert the seam is lazy: importing the package must leave this list
    empty.

    Returns:
        The engine modules present in :data:`sys.modules`, sorted.
    """
    return sorted(name for name in sys.modules if name in {DOCLING_MODULE_NAME})


__all__ = [
    "DOCLING_CONVERTER_ATTRIBUTE",
    "DOCLING_CONVERTER_MODULE_NAME",
    "DOCLING_MODULE_NAME",
    "DOCLING_VERSION_UNKNOWN",
    "ENGINE_NAME",
    "OCREngineError",
    "OCREngineExecutionError",
    "OCREngineNotAvailableError",
    "converter_module",
    "docling_module",
    "engine_provenance",
    "get_engine_version",
    "is_engine_available",
    "loaded_engines",
]
