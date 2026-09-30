# pylint: disable=too-many-lines,duplicate-code
# Reason: the engine call, the extraction of every engine structure and the builders that
# normalize them stay in one module on purpose. The frozen patch path is
# ``docflow.ocr.primitives.convert_image_with_docling`` and the double replaces that symbol, so a
# call moved into a sibling would escape the injection point and stop being exercised. The lazy
# engine resolution and the version reader are deliberate siblings of
# ``docflow.image.primitives``: a processor may not import another processor's internals, so every
# seam resolves its own engine and the shape repeats.
"""Low-level OCR primitives — the only place that knows Docling.

Docling is the single OCR engine of this project. It is fixed (never a user-selectable setting),
it is reached **only** from this package, and the value ``"docling"`` is recorded in metadata
rather than offered as an option.

The engine is resolved **at call time** and named explicitly — there is no fallback, no probing
for an installed library and no silent substitution — so ``import docflow.ocr.primitives``
succeeds with Docling absent and an absent library surfaces as a typed ``ENGINE_ERROR`` from the
call instead of an import error. Docling is a Python library, and two of its habits shape this
module:

* **it reports failure twice.** A conversion that fails may raise, or it may *return* a
  ``ConversionResult`` whose status is ``failure`` with a populated ``errors`` list.
  :func:`conversion_failure` owns that half of the surface, because a returned failure is not an
  exception and would otherwise be read as a successful conversion of an empty page;
* **its structures are rich and its own.** ``DoclingDocument``, ``TextItem``, ``TableItem``,
  ``PageItem`` and their provenance are translated here into the engine-independent
  :class:`~docflow.ocr.contracts.OCRDocument`; nothing downstream — and no other processor —
  ever sees a Docling type.

Engine signal → failure kind (the mapping this module is the only owner of):

=================================================== ==================================
Engine signal                                       ``OCRErrorType``
=================================================== ==================================
missing / empty file, bad extension                 ``INVALID_INPUT`` /
                                                    ``UNSUPPORTED_IMAGE`` (decided by
                                                    ``validate_ocr_input``, pre-engine)
library absent, pipeline not loadable               ``ENGINE_ERROR``, not recoverable
status ``failure``                                  ``OCR_ERROR``
status ``partial_success``                          recorded as recoverable: the run goes
                                                    on and the validation reports
                                                    ``INCOMPLETE``
status the seam does not model                      ``ENGINE_ERROR``
no page geometry reported                           ``LAYOUT_ERROR``
``export_to_text`` / ``export_to_markdown`` raising or not returning ``str``
                                                    ``EXPORT_ERROR``
anything else                                       ``INTERNAL_ERROR``
=================================================== ==================================

Two rules hold for everything here: the input image is never written to, and nothing is
published except through :mod:`docflow.ocr.primitives.publication`, which owns the ``.tmp`` →
rename step.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, Final

from docflow.ocr.contracts import (
    BlockResult,
    LayoutResult,
    NormalizedOCROptions,
    OCRContext,
    OCRDocument,
    OCRError,
    OCRErrorType,
    OCRMetadata,
    OCRMetrics,
    OCROptions,
    OCRValidation,
    TableResult,
)
from docflow.ocr.primitives.composition import (
    DOCLING_LABEL_TO_BLOCK_TYPE,
    DOCUMENT_SCHEMA_VERSION,
    ExtractedBlock,
    ExtractedTable,
    LayoutGeometry,
    OrderedDocument,
    analyze_ocr_result,
    merge_ocr_blocks,
    normalize_bbox,
    normalize_layout,
    normalize_table,
    preserve_reading_order,
    table_to_markdown,
)
from docflow.ocr.primitives.errors import OCRPrimitiveError, typed_failure
from docflow.ocr.primitives.publication import (
    ensure_directory,
    write_json_atomic,
    write_text_atomic,
)
from docflow.ocr.primitives.validation import (
    validate_ocr_input,
    validate_ocr_result,
    validate_output_artifacts,
)

#: Name recorded as ``engine`` in every artifact's metadata.
ENGINE_NAME: Final[str] = "docling"

#: The import name of the engine, resolved at call time and never at import time.
ENGINE_MODULE: Final[str] = "docling"

#: Whether the engine should render page images. It should not: this processor publishes text,
#: Markdown, a structured document and tables, and an image artifact nobody reads is a file that
#: only exists to be skipped. This settles the dossier's open question on ``generate_page_images``.
GENERATE_PAGE_IMAGES: Final[bool] = False

#: The origin an engine states when a box's ``t``/``b`` are measured from the **bottom** of the
#: page. Docling reports it for the pages this processor converts, so a box read as top-down
#: describes the page upside down (:func:`_engine_box`).
BOTTOM_LEFT_ORIGIN: Final[str] = "BOTTOMLEFT"

#: The conversion statuses this seam models, and the failure kind each one carries. A status that
#: is not a key here is not a conversion this processor can describe, so it is an
#: ``ENGINE_ERROR``.
STATUS_FAILURES: Final[dict[str, OCRErrorType]] = {
    "failure": "OCR_ERROR",
    "partial_success": "OCR_ERROR",
}

#: The statuses that end the run. A status that is modelled and not listed here continues with
#: its gap recorded.
FATAL_STATUSES: Final[frozenset[str]] = frozenset({"failure"})

#: Engine namespace, or ``None`` until it is resolved at call time. The tests install the double
#: here so the engine's *version* is answered without Docling being installed; the engine *call*
#: is the seam the double replaces at :func:`convert_image_with_docling` (`README.md` §9.7).
docling: Any = None  # pylint: disable=invalid-name  # reason: the engine's own name

__all__ = [
    "DOCLING_LABEL_TO_BLOCK_TYPE",
    "DOCUMENT_SCHEMA_VERSION",
    "ENGINE_MODULE",
    "ENGINE_NAME",
    "GENERATE_PAGE_IMAGES",
    "BlockResult",
    "ExtractedBlock",
    "ExtractedTable",
    "LayoutGeometry",
    "OCRError",
    "OCRPrimitiveError",
    "OrderedDocument",
    "TableResult",
    "analyze_ocr_result",
    "build_ocr_document",
    "build_ocr_metadata",
    "configure_image_pipeline",
    "conversion_failure",
    "convert_image_with_docling",
    "ensure_directory",
    "extract_docling_blocks",
    "extract_docling_layout",
    "extract_docling_markdown",
    "extract_docling_tables",
    "extract_docling_text",
    "get_engine_version",
    "load_docling_pipeline",
    "merge_ocr_blocks",
    "normalize_docling_options",
    "normalize_layout",
    "normalize_markdown",
    "normalize_ocr_text",
    "normalize_table",
    "preserve_reading_order",
    "process_tables",
    "table_to_markdown",
    "typed_failure",
    "validate_ocr_input",
    "validate_ocr_result",
    "validate_output_artifacts",
    "write_json_atomic",
    "write_text_atomic",
]


def _engine() -> Any:
    """Return the Docling package, imported at call time and never at import time.

    Importing this package has to succeed with Docling absent, so the library is resolved here
    rather than by a module-level ``import``. The module attribute :data:`docling` is the seam the
    tests patch: a double installed there answers instead of the library, so no test imports
    Docling.

    Returns:
        The engine package.

    Raises:
        OCRPrimitiveError: With ``ENGINE_ERROR`` when the library is not installed. An absent
            engine is reported, never replaced: there is no second OCR engine in this processor
            and never a silent substitution.
    """
    if docling is not None:
        return docling
    try:
        return importlib.import_module(ENGINE_MODULE)
    except ImportError as exc:
        raise typed_failure(
            "ENGINE_ERROR",
            f"the {ENGINE_NAME} library is not available",
            recoverable=False,
            metadata={"module": ENGINE_MODULE},
        ) from exc


def get_engine_version() -> str:
    """Return the engine version, as the engine itself reports it.

    The version is recorded in every artifact's metadata, so an unreadable one is reported rather
    than guessed: a re-run is only comparable to a previous one when the engine that produced each
    is known.

    Returns:
        The version token the library exposes, e.g. ``"2.126.0"``.

    Raises:
        OCRPrimitiveError: With ``ENGINE_ERROR`` when the library is absent or exposes no version.
    """
    engine = _engine()
    version = getattr(engine, "__version__", None)
    if not version:
        raise typed_failure(
            "ENGINE_ERROR",
            f"the {ENGINE_NAME} library reports no version",
            recoverable=False,
            metadata={"module": ENGINE_MODULE},
        )
    return str(version)


def normalize_docling_options(options: OCROptions) -> NormalizedOCROptions:
    """Return the canonical form of the requested OCR options.

    Two equivalent requests have to produce the same normalized options, because a processing key
    is computed from them and a key that differs for the same configuration would defeat reuse.
    Keys are therefore put in a fixed order and the language tag is folded to its canonical
    spelling.

    Args:
        options: The raw options as requested.

    Returns:
        The canonical options. A language that is only whitespace names no language at all and is
        reported as ``None`` rather than as an empty tag the engine would have to interpret.
    """
    language = (
        None if options.language is None else str(options.language).strip().lower()
    )
    return NormalizedOCROptions(
        ocr=bool(options.ocr),
        layout=bool(options.layout),
        tables=bool(options.tables),
        reading_order=bool(options.reading_order),
        language=language or None,
        engine_options={
            key: options.engine_options[key] for key in sorted(options.engine_options)
        },
    )


def configure_image_pipeline(options: NormalizedOCROptions) -> dict[str, Any]:
    """Fold the normalized options into the engine configuration, inline.

    Each capability is decided by the option's own value, in one construction: there is no
    ``enable_*`` / ``should_enable_*`` predicate per flag, because a predicate would be a second
    place the same decision is made. A declared flag always wins over a passthrough key of the
    same name, so an ``engine_options`` entry can add a knob but cannot quietly switch off a
    capability the caller asked for.

    Args:
        options: The canonical options.

    Returns:
        The engine-facing configuration: the engine's own option names, plus whatever the caller
        passed through in ``engine_options``.
    """
    return {
        **options.engine_options,
        "do_ocr": options.ocr,
        "do_table_structure": options.tables,
        "ocr_language": options.language,
        "generate_page_images": GENERATE_PAGE_IMAGES,
    }


def load_docling_pipeline(config: dict[str, Any]) -> Any:
    """Build the engine's conversion pipeline for one image.

    This is the only function that imports Docling, and it is reached only from
    :func:`convert_image_with_docling` — the engine call and the double's injection point. A test
    therefore never constructs a real pipeline, and the suite runs with no engine installed.

    Args:
        config: The configuration :func:`configure_image_pipeline` produced.

    Returns:
        The engine's converter, ready to convert one image.

    Raises:
        OCRPrimitiveError: With ``ENGINE_ERROR`` when the library or one of its modules is
            missing.
    """
    try:
        converter_module = importlib.import_module(
            f"{ENGINE_MODULE}.document_converter"
        )
        pipeline_module = importlib.import_module(
            f"{ENGINE_MODULE}.datamodel.pipeline_options"
        )
        base_models = importlib.import_module(f"{ENGINE_MODULE}.datamodel.base_models")
    except ImportError as exc:
        raise typed_failure(
            "ENGINE_ERROR",
            f"the {ENGINE_NAME} pipeline could not be loaded",
            recoverable=False,
            metadata={"module": ENGINE_MODULE, "import_error": str(exc)},
        ) from exc

    pipeline_options = pipeline_module.PdfPipelineOptions(
        do_ocr=config["do_ocr"],
        do_table_structure=config["do_table_structure"],
        generate_page_images=config["generate_page_images"],
    )
    return converter_module.DocumentConverter(
        format_options={
            base_models.InputFormat.IMAGE: converter_module.ImageFormatOption(
                pipeline_options=pipeline_options
            )
        }
    )


def convert_image_with_docling(image_path: Path, config: dict[str, Any]) -> Any:
    """Convert one prepared image with the engine — the engine call, and the double's seam.

    The whole processor's engine dependence is this one call: everything the conversion returns is
    the engine's own shape, and translating it is what the rest of this module is for. The tests
    replace this symbol, so no test invokes the engine.

    Args:
        image_path: The prepared image. It is only ever read.
        config: The configuration :func:`configure_image_pipeline` produced.

    Returns:
        The engine's own conversion result, untranslated.
    """
    pipeline = load_docling_pipeline(config)
    return pipeline.convert(str(image_path))


def _status_value(status: Any) -> str:
    """Return the engine's conversion status as a plain string.

    Docling's ``ConversionStatus`` is a ``str`` enum; the value is read when it is present, so the
    seam never depends on an enum class it cannot import without loading the engine at import time.
    """
    return str(getattr(status, "value", status))


def conversion_failure(conversion: Any, image_path: Path) -> OCRError | None:
    """Map the conversion's returned status onto a typed failure, or ``None`` when it succeeded.

    A returned failure is the half of Docling's failure surface that does not raise. Reading only
    the document would report a refused conversion as a successful extraction of an empty page,
    which is exactly the silent stand-in this project forbids.

    Args:
        conversion: The engine's own conversion result.
        image_path: The image the conversion was asked about, for the failure's context.

    Returns:
        ``None`` when the status is ``success``; a recoverable ``OCR_ERROR`` when the conversion
        was partial — the run continues and the validation reports ``INCOMPLETE``; an unrecoverable
        failure when the conversion failed, or reported a status this seam does not model.
    """
    status = _status_value(getattr(conversion, "status", None))
    if status == "success":
        return None

    return OCRError(
        type=STATUS_FAILURES.get(status, "ENGINE_ERROR"),
        message=f"the {ENGINE_NAME} conversion of {image_path} reported {status}",
        recoverable=status in STATUS_FAILURES and status not in FATAL_STATUSES,
        metadata={
            "engine_status": status,
            "errors": [
                str(error) for error in getattr(conversion, "errors", None) or []
            ],
            "image_path": str(image_path),
        },
    )


def _document(conversion: Any) -> Any:
    """Return the engine's document, or fail with a typed error when there is none."""
    document = getattr(conversion, "document", None)
    if document is None:
        raise typed_failure(
            "OCR_ERROR",
            "the conversion returned no document",
            recoverable=False,
            metadata={
                "engine_status": _status_value(getattr(conversion, "status", None))
            },
        )
    return document


def _items(document: Any) -> list[tuple[Any, int]]:
    """Return the engine's items and their levels, in the engine's own order."""
    return list(document.iterate_items())


def _label(item: Any) -> str:
    """Return an item's label as a plain string."""
    return _status_value(getattr(item, "label", None))


def _located(item: Any) -> tuple[Any, int] | None:
    """Return the item's own box **as the engine reported it**, and the page it sits on.

    ``prov`` is where the engine records where an item was found; the first entry is the item's own
    position. An item without provenance was not located on a page, and ``None`` states that rather
    than inventing a box. The box is handed over untranslated — it still carries the origin its
    numbers are measured from, and :func:`_engine_box` is the one place that is honoured.
    """
    provenance = getattr(item, "prov", None) or []
    if not provenance:
        return None
    box = getattr(provenance[0], "bbox", None)
    if box is None:
        return None
    return box, int(getattr(provenance[0], "page_no", 1))


def _origin_of(box: Any) -> str:
    """Return the box's coordinate origin as a plain string, or ``""`` when it states none."""
    return _status_value(getattr(box, "coord_origin", "") or "")


def _engine_box(box: Any, page_height: float) -> tuple[float, float, float, float]:
    """Return the engine's box in the convention the document states: top-down, engine units.

    The engine says where its numbers are measured from, and it is not always the top: Docling
    reports ``BOTTOMLEFT`` for the pages this processor converts, so the item highest on the page
    carries the *largest* ``t``. Numbers read as if they were top-down therefore describe the page
    upside down — an inverted ``--reading-order`` and a ``bbox`` whose top is its bottom. The
    conversion is the engine's own (``to_top_left_origin``) rather than arithmetic of ours, and it
    is made once, here, so every box the rest of this module normalizes is top-down. A box that
    states no origin is taken at its word: it is already what it says it is.
    """
    if _origin_of(box) == BOTTOM_LEFT_ORIGIN:
        box = box.to_top_left_origin(page_height)
    left, top, right, bottom = box.as_tuple()
    return (float(left), float(top), float(right), float(bottom))


def _claimed_box(
    item: Any, geometry: LayoutGeometry, *, with_layout: bool
) -> tuple[tuple[float, float, float, float] | None, int]:
    """Return an item's normalized box and page, claiming no box when none was asked for.

    The engine reports a box either way; publishing a geometry the caller did not request would be
    a claim about work nobody asked for.
    """
    located = _located(item)
    if located is None:
        return None, 1
    box, page = located
    if not with_layout:
        return None, page
    raw = _engine_box(box, geometry.height)
    return normalize_bbox(raw, geometry.width, geometry.height), page


def extract_docling_layout(conversion: Any) -> LayoutGeometry:
    """Read the page geometry out of the engine's own document.

    Args:
        conversion: The engine's conversion result.

    Returns:
        The page size and the detected regions, in the engine's units, ready to be normalized.

    Raises:
        OCRPrimitiveError: With ``LAYOUT_ERROR`` when the engine reports no page, or a page with no
            usable size. A converted image always has a page, so a missing one is a layout the
            engine could not build — and without it there is no unit to measure anything against.
    """
    document = _document(conversion)
    pages = getattr(document, "pages", None) or {}
    if not pages:
        raise typed_failure(
            "LAYOUT_ERROR",
            "the engine reported no page geometry",
            recoverable=False,
            metadata={},
        )

    page = pages[min(pages)]
    width = float(page.size.width)
    height = float(page.size.height)
    if width <= 0 or height <= 0:
        raise typed_failure(
            "LAYOUT_ERROR",
            "the engine reported a page with no usable size",
            recoverable=False,
            metadata={"page_width": width, "page_height": height},
        )

    regions: list[tuple[float, float, float, float]] = []
    for item, _level in _items(document):
        located = _located(item)
        if located is not None:
            regions.append(_engine_box(located[0], height))
    return LayoutGeometry(width=width, height=height, region_bboxes=regions)


def extract_docling_blocks(
    conversion: Any, geometry: LayoutGeometry, *, with_layout: bool
) -> list[ExtractedBlock]:
    """Translate the engine's text items into our blocks, in the engine's own order.

    An item labelled ``table`` is left out on purpose: a table is extracted as a table, and the
    same content must not arrive twice. An item with no text carries nothing to report.

    No ordering guarantee is claimed here — the blocks come back in the order the engine handed
    them over, and putting them in reading order is a separate, deterministic step.

    Args:
        conversion: The engine's conversion result.
        geometry: The page geometry, used to normalize each box.
        with_layout: Whether a geometry was asked for; see :func:`_claimed_box`.

    Returns:
        The blocks, un-ordered and un-named.
    """
    blocks: list[ExtractedBlock] = []
    for order, (item, level) in enumerate(_items(_document(conversion))):
        if _label(item) == "table":
            continue
        text = str(getattr(item, "text", "") or "").strip()
        if not text:
            continue
        box, page = _claimed_box(item, geometry, with_layout=with_layout)
        blocks.append(
            ExtractedBlock(
                order=order,
                page=page,
                type=DOCLING_LABEL_TO_BLOCK_TYPE.get(_label(item), "other"),
                text=text,
                bbox=box,
                level=int(level) if level else None,
            )
        )
    return blocks


def _table_grid(table: Any) -> list[list[str]]:
    """Return a table's cells as a grid, placed by the engine's own row and column offsets."""
    data = getattr(table, "data", None)
    rows = int(getattr(data, "num_rows", 0) or 0)
    cells = list(getattr(data, "table_cells", None) or [])
    if rows <= 0 and not cells:
        return []
    width = int(getattr(data, "num_cols", 0) or 0)
    if width <= 0:
        width = max((int(cell.start_col_offset_idx) + 1 for cell in cells), default=0)
    grid = [[""] * width for _ in range(rows)]
    for cell in cells:
        row = int(cell.start_row_offset_idx)
        column = int(cell.start_col_offset_idx)
        if 0 <= row < rows and 0 <= column < width:
            grid[row][column] = str(getattr(cell, "text", "") or "")
    return grid


def extract_docling_tables(
    conversion: Any, geometry: LayoutGeometry, *, with_layout: bool
) -> list[ExtractedTable]:
    """Translate the engine's tables into our tables, in the engine's own order.

    Args:
        conversion: The engine's conversion result.
        geometry: The page geometry, used to normalize each box.
        with_layout: Whether a geometry was asked for; see :func:`_claimed_box`.

    Returns:
        The tables, un-ordered, un-named and already rectangular.
    """
    tables: list[ExtractedTable] = []
    for order, table in enumerate(getattr(_document(conversion), "tables", None) or []):
        box, _page = _claimed_box(table, geometry, with_layout=with_layout)
        tables.append(
            ExtractedTable(
                order=order, bbox=box, cells=normalize_table(_table_grid(table))
            )
        )
    return tables


def _export(conversion: Any, method: str, representation: str) -> str:
    """Call one of the engine's export methods and type its failure.

    Args:
        conversion: The engine's conversion result.
        method: The export method's name.
        representation: What the export produces, for the failure record.

    Returns:
        The exported text.

    Raises:
        OCRPrimitiveError: With ``EXPORT_ERROR`` when the export raises or returns something that
            is not text — a representation that cannot be produced is a failure of the run, not an
            empty artifact.
    """
    document = _document(conversion)
    try:
        exported = getattr(document, method)()
    except Exception as exc:  # pylint: disable=broad-exception-caught
        # The engine's export can fail in its own ways and its exception class cannot be named
        # here without importing the engine at call time; the typed failure below is the point.
        raise typed_failure(
            "EXPORT_ERROR",
            f"the engine could not export the {representation}",
            metadata={"engine_error": str(exc)},
        ) from exc
    if not isinstance(exported, str):
        raise typed_failure(
            "EXPORT_ERROR",
            f"the engine exported the {representation} as {type(exported).__name__}",
            metadata={"exported_type": type(exported).__name__},
        )
    return exported


def extract_docling_text(conversion: Any) -> str:
    """Return the engine's plain-text export, untranslated.

    Args:
        conversion: The engine's conversion result.

    Returns:
        The engine's own plain text.

    Raises:
        OCRPrimitiveError: With ``EXPORT_ERROR`` when the engine cannot produce it.
    """
    return _export(conversion, "export_to_text", "text")


def extract_docling_markdown(conversion: Any) -> str:
    """Return the engine's Markdown export, untranslated.

    Args:
        conversion: The engine's conversion result.

    Returns:
        The engine's own Markdown.

    Raises:
        OCRPrimitiveError: With ``EXPORT_ERROR`` when the engine cannot produce it.
    """
    return _export(conversion, "export_to_markdown", "markdown")


def normalize_ocr_text(text: str) -> str:
    """Normalize the engine's plain text into the form ``text.txt`` holds.

    Line endings are unified, trailing whitespace is removed from every line and trailing blank
    lines are dropped. Nothing is added: a text that is empty stays empty, and the emptiness is
    reported by the metrics and the ``EMPTY`` status rather than by an invented placeholder.

    Args:
        text: The engine's own text.

    Returns:
        The normalized text, with no trailing newline — what the result reports is exactly what the
        file holds.
    """
    unified = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in unified.split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def normalize_markdown(markdown: str) -> str:
    """Normalize the engine's Markdown into the form ``document.md`` holds.

    Args:
        markdown: The engine's own Markdown.

    Returns:
        The normalized Markdown, ending in exactly one newline when it has any content, and empty
        when it has none.
    """
    normalized = normalize_ocr_text(markdown)
    return f"{normalized}\n" if normalized else ""


def process_tables(tables: list[TableResult], tables_dir: Path) -> list[Path]:
    """Publish every detected table as ``tables/table_NNN.md``, in reading order.

    Args:
        tables: The tables, already in reading order and already named.
        tables_dir: The ``ocr/tables/`` directory. It is created only when there is a table to
            publish: an image with no table produces no directory and no failure.

    Returns:
        The published paths, in reading order.
    """
    return [
        write_text_atomic(tables_dir / f"{table.table_id}.md", table.markdown)
        for table in tables
    ]


def build_ocr_metadata(
    image_path: Path,
    context: OCRContext,
    *,
    engine_version: str,
    processor_version: str,
    options: NormalizedOCROptions,
    metrics: OCRMetrics,
    validation: OCRValidation,
    timing: dict[str, float],
    transformations: list[str],
) -> OCRMetadata:
    """Build the provenance record of one extraction.

    Args:
        image_path: The image that was read.
        context: The correlation metadata echoed from the request.
        engine_version: The version the engine reported.
        processor_version: The version of the code that produced the artifacts.
        options: The canonical options the run used.
        metrics: The content measurements.
        validation: The validation outcome recorded at publish time.
        timing: Wall-clock durations by stage; the only home of run-time data.
        transformations: Every normalization actually applied, in order.

    Returns:
        The metadata record. ``engine`` is the fixed engine name: it is recorded, never chosen.
    """
    return OCRMetadata(
        engine=ENGINE_NAME,
        engine_version=engine_version,
        processor_version=processor_version,
        options=options,
        input=image_path,
        metrics=metrics,
        validation=validation,
        timing=timing,
        transformations=transformations,
        context=context,
    )


def build_ocr_document(
    *,
    text: str,
    blocks: list[BlockResult],
    tables: list[TableResult],
    layout: LayoutResult,
    reading_order: list[str],
    options: NormalizedOCROptions,
    engine_version: str,
) -> OCRDocument:
    """Assemble the engine-independent document from what was extracted.

    The metadata block is built here rather than passed in, because it is the same record in every
    document: the schema version, the engine and the canonical options. It holds no timing and no
    correlation identity — ``document.json`` is functional content, and two runs over the same
    image have to produce the same bytes.

    Args:
        text: The plain text, normalized.
        blocks: The blocks, in reading order.
        tables: The tables, in reading order.
        layout: The normalized layout.
        reading_order: Block and table identifiers, in reading order.
        options: The canonical options the run used.
        engine_version: The version the engine reported.

    Returns:
        The document. ``paragraphs`` and ``titles`` are read off the blocks, so the two views
        cannot disagree about what the extraction contains.
    """
    return OCRDocument(
        text=text,
        paragraphs=[block.text for block in blocks if block.type == "paragraph"],
        titles=[block.text for block in blocks if block.type == "title"],
        blocks=blocks,
        tables=tables,
        layout=layout,
        reading_order=reading_order,
        metadata={
            "schema_version": DOCUMENT_SCHEMA_VERSION,
            "engine": ENGINE_NAME,
            "engine_version": engine_version,
            "options": {
                "ocr": options.ocr,
                "layout": options.layout,
                "tables": options.tables,
                "reading_order": options.reading_order,
                "language": options.language,
                "engine_options": options.engine_options,
            },
        },
    )
