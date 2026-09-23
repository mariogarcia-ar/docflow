"""Docling pipeline construction and configuration (``OCR-03``).

Everything here is about *building* a converter, never running one: which pipeline a page gets,
and which of its stages are switched on. :mod:`docflow.ocr.primitives.execution` is what runs it.

Three rules shape the module, and each answers a specific way this could go wrong:

* **A predicate decides; an enabler applies.** ``should_enable_*`` reads the processor's options
  and answers a question; ``enable_*`` sets Docling's flag from that answer. Splitting them means
  the *decision* is testable without an engine and the *mechanism* is testable without a decision —
  a single function doing both would need Docling installed to test a boolean.
* **Every flag is set in both directions.** Docling defaults ``do_ocr`` and ``do_table_structure``
  to ``True``, so a processor that only ever switched capabilities *on* would silently ignore a
  request for ``tables=False``. The subplan puts that out of bounds in the same sentence as silent
  enablement: "a missing option must not silently enable a capability", and an option that is
  present and ignored is the same defect from the other side.
* **Non-boolean options are refused, not coerced.** ``bool("false")`` is ``True``. A request that
  arrives as JSON with a string where a flag belongs would turn a capability *on* while the caller
  asked for it off, with nothing downstream able to tell. Normalization is where the shape is
  enforced.

The engine is imported **inside** the functions that need it rather than at module level, because
``GEN-01`` asserts a clean interpreter can import every sub-package without loading an engine.
Importing this module touches no engine; only the functions that build an options object do.
"""

from __future__ import annotations

import importlib
from typing import Any

from docflow.ocr.contracts import NormalizedOCROptions, OCROptions
from docflow.ocr.primitives.engine import docling_module

#: Which Docling input format the configured pipeline is registered for.
#:
#: This processor reads images and nothing else — the prepared image a PDF render or an earlier
#: stage handed it. Naming the format rather than letting Docling infer it is what keeps a ``.png``
#: that happens to look like something else from being routed through a backend this processor
#: never intended to drive.
INPUT_FORMAT_NAME: str = "IMAGE"

#: Docling's flag for OCR, on the pipeline options object.
DOCLING_OCR_FLAG: str = "do_ocr"

#: Docling's flag for table structure detection.
DOCLING_TABLES_FLAG: str = "do_table_structure"

#: Docling's field holding the layout model's options.
#:
#: There is **no** ``do_layout`` flag on Docling 2.126.0, which was worth measuring rather than
#: assuming: layout is on when ``layout_options`` holds a value and off when it is ``None``. A
#: primitive that looked for a boolean would have found nothing and quietly changed no behaviour.
DOCLING_LAYOUT_FIELD: str = "layout_options"

PIPELINE_OPTIONS_MODULE_NAME: str = "docling.datamodel.pipeline_options"

#: The Docling pipeline class these options configure.
#:
#: ``PdfPipelineOptions`` despite the name: Docling's image backend runs the same pipeline, and
#: ``ImageFormatOption`` pairs it with the image input format. Recorded here so the choice is
#: visible in one place.
DOCLING_PIPELINE_OPTIONS_CLASS: str = "PdfPipelineOptions"


def normalize_docling_options(options: OCROptions) -> NormalizedOCROptions:
    """Turn a raw request's options into the canonical form the rest of the processor uses.

    This is the one place raw options become normalized ones. Everything downstream — the
    predicates, the metadata record, the processing key the orchestrator will derive — reads the
    normalized form, so two requests that mean the same thing cannot produce two different keys.

    Three things are canonicalized, and each is a real source of divergence rather than
    housekeeping:

    * **Language** is stripped and lowercased, and an empty string becomes ``None``. ``"EN"``,
      ``"en"`` and ``" en "`` are one request; ``""`` means "not specified" rather than "the empty
      language".
    * **``engine_options`` keys are sorted**, so the same mapping written in two orders produces
      the same value. A dict compares equal regardless of order, but its *serialization* does not,
      and the serialization is what reaches the processing key.
    * **Flags must be ``bool``.** Not coerced — refused. See the module docstring.

    Args:
        options: The raw options, as the request carried them.

    Returns:
        The canonical form.

    Raises:
        ValueError: A flag is not a ``bool``.

    # TODO: [MVP] tighter `engine_options` validation. This normalizes key order and leaves the
    # values to the engine, which reports a bad one when the pipeline is configured rather than
    # here; a value that Docling silently ignores would pass through unnoticed.
    """
    for name in ("ocr", "layout", "tables", "reading_order"):
        value = getattr(options, name)
        if not isinstance(value, bool):
            raise ValueError(
                f"the option {name!r} must be a bool, got {value!r} ({type(value).__name__}); "
                f"it is refused rather than coerced, because bool('false') is True and the "
                f"caller would get the opposite of what they asked for"
            )

    language = options.language
    if language is not None:
        language = language.strip().lower() or None

    return NormalizedOCROptions(
        ocr=options.ocr,
        layout=options.layout,
        tables=options.tables,
        reading_order=options.reading_order,
        language=language,
        engine_options={
            key: options.engine_options[key] for key in sorted(options.engine_options)
        },
    )


def should_enable_ocr(options: NormalizedOCROptions) -> bool:
    """Report whether OCR should run for these options.

    Compares against ``True`` rather than testing truthiness, so a value that is not a boolean
    fails toward *disabled*. The safe direction matters: the subplan forbids a missing option
    silently enabling a capability, and a truthiness test would enable OCR for any non-empty value
    that reached here.

    Args:
        options: The normalized options.

    Returns:
        ``True`` when OCR was explicitly requested.
    """
    return options.ocr is True


def should_enable_layout(options: NormalizedOCROptions) -> bool:
    """Report whether layout analysis should run.

    Args:
        options: The normalized options.

    Returns:
        ``True`` when layout was explicitly requested.
    """
    return options.layout is True


def should_enable_tables(options: NormalizedOCROptions) -> bool:
    """Report whether table detection should run.

    Args:
        options: The normalized options.

    Returns:
        ``True`` when tables were explicitly requested.
    """
    return options.tables is True


def should_enable_reading_order(options: NormalizedOCROptions) -> bool:
    """Report whether reading order should be resolved.

    Reading order has no Docling flag of its own — it is a property of how this processor orders
    the blocks it extracts, which is ``OCR-05``'s work. The predicate exists because the subplan
    names it, and because the option is a request the processor honours rather than a setting it
    forwards: answering it here keeps the decision in one place instead of scattering
    ``options.reading_order`` through the extraction code.

    Args:
        options: The normalized options.

    Returns:
        ``True`` when reading order was explicitly requested.
    """
    return options.reading_order is True


def enable_ocr(docling_options: Any, enabled: bool) -> Any:
    """Set Docling's OCR flag from a decision, and return the options.

    Takes the decision rather than the processor's options, so the halves stay separable: this
    function's contract is "make the flag match this boolean", which is testable without an engine
    and without constructing a request.

    Args:
        docling_options: Docling's pipeline options object, modified in place.
        enabled: Whether OCR should run.

    Returns:
        The same object, for chaining.
    """
    setattr(docling_options, DOCLING_OCR_FLAG, enabled)
    return docling_options


def enable_table_detection(docling_options: Any, enabled: bool) -> Any:
    """Set Docling's table-structure flag from a decision, and return the options.

    Docling defaults this flag to ``True``, so passing ``False`` is the case that matters: a
    processor that only switched capabilities *on* would ignore a request for no tables.

    Args:
        docling_options: Docling's pipeline options object, modified in place.
        enabled: Whether table detection should run.

    Returns:
        The same object, for chaining.
    """
    setattr(docling_options, DOCLING_TABLES_FLAG, enabled)
    return docling_options


def enable_layout_analysis(docling_options: Any, enabled: bool) -> Any:
    """Set whether Docling resolves layout, and return the options.

    Not a boolean flag. Docling 2.126.0 has no ``do_layout``; layout is on when ``layout_options``
    holds a value and off when it is ``None``. That was **measured** rather than assumed — a
    primitive that looked for a boolean would have found nothing and changed no behaviour while
    appearing to work.

    Turning layout *on* when options are already present leaves them alone: they may carry settings
    the caller placed there, and replacing them would discard a decision this module was not asked
    to revisit.

    Args:
        docling_options: Docling's pipeline options object, modified in place.
        enabled: Whether layout analysis should run.

    Returns:
        The same object, for chaining.
    """
    if not enabled:
        setattr(docling_options, DOCLING_LAYOUT_FIELD, None)
        return docling_options
    if getattr(docling_options, DOCLING_LAYOUT_FIELD, None) is not None:
        return docling_options
    setattr(docling_options, DOCLING_LAYOUT_FIELD, _layout_options_type()())
    return docling_options


def _layout_options_type() -> Any:
    """Return Docling's layout-options class.

    Loads the engine to find it, which is why it is a function rather than a module constant: a
    constant would make importing this module load Docling.

    Returns:
        The class, so a caller can construct one.

    Raises:
        OCREngineNotAvailableError: The engine is not importable.
    """
    module = _pipeline_options_module()
    return module.LayoutObjectDetectionOptions


def _pipeline_options_module() -> Any:
    """Import and return Docling's pipeline-options module.

    Returns:
        The ``docling.datamodel.pipeline_options`` module.

    Raises:
        OCREngineNotAvailableError: The engine is not importable.
    """
    docling_module()
    return importlib.import_module(PIPELINE_OPTIONS_MODULE_NAME)


def load_docling_pipeline() -> Any:
    """Build the Docling pipeline options this processor configures.

    Returns the **options**, not a converter: a converter is options plus an input format, and
    keeping the two separable is what lets :func:`configure_image_pipeline` be the only place that
    decides how this processor's request maps onto Docling's.

    The result carries Docling's own defaults, which is the point — Docling defaults ``do_ocr`` and
    ``do_table_structure`` to ``True``, and the caller is expected to set them from the request
    rather than inherit them.

    Returns:
        A fresh Docling pipeline-options object.

    Raises:
        OCREngineNotAvailableError: The engine is not importable.
    """
    module = _pipeline_options_module()
    return getattr(module, DOCLING_PIPELINE_OPTIONS_CLASS)()


def configure_image_pipeline(options: NormalizedOCROptions) -> Any:
    """Configure the image pipeline this processor drives, from normalized options.

    The order is fixed and readable: load Docling's defaults, then apply each of the processor's
    three capability decisions. Every decision goes through its predicate and its enabler, so there
    is no branch here that could enable a capability the request did not ask for.

    ``reading_order`` is deliberately absent: it has no Docling flag to set. It is a property of how
    the extracted blocks are ordered, which is ``OCR-05``'s work, and its predicate is read there.
    Setting a Docling flag for it here would be inventing one.

    Args:
        options: The normalized options.

    Returns:
        The configured pipeline-options object.

    Raises:
        OCREngineNotAvailableError: The engine is not importable.

    # TODO: [MVP] `language` and `engine_options` are normalized but not forwarded to Docling yet.
    # This task configures the capability flags; forwarding the rest is option coverage the subplan
    # tags as MVP.
    """
    docling_options = load_docling_pipeline()
    enable_ocr(docling_options, should_enable_ocr(options))
    enable_table_detection(docling_options, should_enable_tables(options))
    enable_layout_analysis(docling_options, should_enable_layout(options))
    return docling_options


__all__ = [
    "DOCLING_LAYOUT_FIELD",
    "DOCLING_OCR_FLAG",
    "DOCLING_TABLES_FLAG",
    "INPUT_FORMAT_NAME",
    "configure_image_pipeline",
    "enable_layout_analysis",
    "enable_ocr",
    "enable_table_detection",
    "load_docling_pipeline",
    "normalize_docling_options",
    "should_enable_layout",
    "should_enable_ocr",
    "should_enable_reading_order",
    "should_enable_tables",
]
