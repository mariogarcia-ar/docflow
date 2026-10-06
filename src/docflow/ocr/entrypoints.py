# pylint: disable=duplicate-code
# Reason: the identity and option-canonicalisation helpers are deliberate siblings of
# ``docflow.pdf.entrypoints`` and ``docflow.image.entrypoints``. Two processors may not import
# each other's internals (`README.md` §7 — "no processor imports another processor"), so the same
# short rule is written a third time on purpose and none of the copies is another's default.
"""Entry point of the OCR processor.

The signature is frozen by ``docs/plan/README.md`` §4 (the idea's §"Naming"): ``ocr`` exposes
``process_ocr_image()``. It returns a typed result: a failure is described in an ``OCRError``
inside the result, never thrown across the contract.

Where the artifacts go — ``request.output_dir`` *is* the namespace the plan calls ``ocr/``:

```
output_dir/
├── text.txt
├── document.md
├── document.json
├── tables/
│   └── table_001.md
└── metadata.json
```

Nothing is written outside that directory, and everything is published atomically
(``.tmp`` → rename) through the seam's writers.

The order of the stages is the one the subplan §3.3 fixes: validate the input, read the engine
version, normalize the options, configure the pipeline, convert once, translate the engine's
structures, order them, then build the three representations, publish, measure, validate and
record. The option flags decide what is *claimed*: an extraction that was not asked for a layout
reports no boxes, one that was not asked for tables claims none, and the page size is always
reported because everything is measured against it.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from time import perf_counter
from typing import Any, Final, TypeVar

from docflow.ocr import primitives
from docflow.ocr.contracts import (
    ArtifactPaths,
    NormalizedOCROptions,
    OCRContext,
    OCRDocument,
    OCRError,
    OCRMetrics,
    OCROptions,
    OCRRequest,
    OCRResult,
    OCRValidation,
)
from docflow.ocr.primitives import (
    DOCUMENT_SCHEMA_VERSION,
    ENGINE_NAME,
    OCRPrimitiveError,
    OrderedDocument,
    analyze_ocr_result,
    build_ocr_document,
    build_ocr_metadata,
    configure_image_pipeline,
    conversion_failure,
    extract_docling_blocks,
    extract_docling_layout,
    extract_docling_markdown,
    extract_docling_tables,
    extract_docling_text,
    get_engine_version,
    normalize_docling_options,
    normalize_layout,
    normalize_markdown,
    normalize_ocr_text,
    preserve_reading_order,
    process_tables,
    typed_failure,
    validate_ocr_input,
    validate_ocr_result,
    write_json_atomic,
    write_text_atomic,
)

#: Name recorded as ``processor`` in every artifact's metadata.
PROCESSOR_NAME: Final[str] = "ocr"

#: Version recorded as ``processor_version`` in every artifact's metadata. A test asserts it
#: matches ``pyproject.toml``: the provenance an artifact carries has to name the code that
#: produced it.
PROCESSOR_VERSION: Final[str] = "0.0.0"

#: Artifact names, fixed so a reader never has to guess what a file is.
TEXT_NAME: Final[Path] = Path("text.txt")
MARKDOWN_NAME: Final[Path] = Path("document.md")
STRUCTURED_NAME: Final[Path] = Path("document.json")
TABLES_DIR_NAME: Final[Path] = Path("tables")
METADATA_NAME: Final[Path] = Path("metadata.json")

T = TypeVar("T")


@dataclass
class _Extraction:
    """What one engine conversion produced, in the forms the rest of the run needs.

    The Markdown travels beside the document rather than inside it: :class:`OCRDocument` is the
    engine-independent structure — text, blocks, tables, layout, reading order — and Markdown is one
    of its *representations*, rendered from the engine's own export in ``OCR-06``.

    Attributes:
        document: The engine-independent document, ordered and measured.
        markdown: The normalized Markdown representation.
        ordered: The ordered content, whose blocks and tables the document shares.
        metrics: The content measurements.
        failures: The recoverable failures the conversion itself reported.
    """

    document: OCRDocument
    markdown: str
    ordered: OrderedDocument
    metrics: OCRMetrics
    failures: list[OCRError]


def _attempt(
    failures: list[OCRError], action: Callable[..., T], *arguments: Any
) -> T | None:
    """Run one stage, recording a typed failure instead of raising it.

    Args:
        failures: The run's failure list, which this call appends to.
        action: The seam function to run.
        arguments: Its arguments.

    Returns:
        What the stage produced, or ``None`` when it failed. The run keeps whatever other stages
        produced, and the recorded failure explains the gap.
    """
    try:
        return action(*arguments)
    except OCRPrimitiveError as failure:
        failures.append(failure.error)
        return None


def _file_digest(path: Path) -> str:
    """Return the SHA-256 of a file, read in bounded chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalized_options(request: OCRRequest) -> dict[str, Any]:
    """Return the options in canonical form, one key per capability.

    Canonical rather than raw, so two spellings of the same configuration produce the same record
    — and therefore the same processing key.
    """
    options = normalize_docling_options(request.options)
    return {
        "ocr": options.ocr,
        "layout": options.layout,
        "tables": options.tables,
        "reading_order": options.reading_order,
        "language": options.language,
        "engine_options": options.engine_options,
    }


def _processing_key(request: OCRRequest) -> str:
    """Return this unit of work's key, per the documented formula.

    ``hash(processor + processor_version + input_hashes + normalized_options)``, with the run
    identity deliberately absent: a new run over unchanged inputs must reproduce the key.

    # TODO: [MVP] the orchestrator mints the document-level key (`ORC-02`); this processor-local
    # record makes the artifact self-describing until both are reconciled at Phase 2.
    """
    material = "|".join(
        (
            PROCESSOR_NAME,
            PROCESSOR_VERSION,
            _file_digest(request.image_path),
            json.dumps(_normalized_options(request), sort_keys=True),
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _convert(image_path: Path, config: dict[str, Any]) -> Any:
    """Run the engine call, typing anything it throws.

    The engine call is reached **through the module** and not through a name bound at import time:
    the frozen injection point is the module attribute
    ``docflow.ocr.primitives.convert_image_with_docling``, so a double installed there is the one
    that answers. Binding the function here would make the patch a no-op and the suite would reach
    the real engine.

    The frozen injection point *is* the engine call, so an exception from it arrives here and not
    through a wrapper inside the seam. The engine's own exception class cannot be named without
    importing the engine, so the mapping is by position: whatever escapes the engine call is the
    engine failing, which is an ``ENGINE_ERROR`` rather than a crash of this processor. This is the
    path the double's "raise during conversion" knob exercises.

    Args:
        image_path: The prepared image.
        config: The engine configuration.

    Returns:
        The engine's own conversion result.

    Raises:
        OCRPrimitiveError: With ``ENGINE_ERROR`` when the call threw.
    """
    try:
        return primitives.convert_image_with_docling(image_path, config)
    except OCRPrimitiveError:
        raise
    except Exception as exc:  # pylint: disable=broad-exception-caught
        raise typed_failure(
            "ENGINE_ERROR",
            f"the {ENGINE_NAME} conversion of {image_path} raised",
            recoverable=False,
            metadata={"engine_error": str(exc), "image_path": str(image_path)},
        ) from exc


def _artifact_paths(output_dir: Path) -> ArtifactPaths:
    """Return the namespace's artifact paths, all inside ``output_dir``."""
    return ArtifactPaths(
        text=output_dir / TEXT_NAME,
        markdown=output_dir / MARKDOWN_NAME,
        structured_document=output_dir / STRUCTURED_NAME,
        tables_dir=output_dir / TABLES_DIR_NAME,
        metadata=output_dir / METADATA_NAME,
    )


def _failed_result(error: OCRError) -> OCRResult:
    """Return the result of a run that failed before it produced any artifact.

    Nothing is published: an artifact tree that only describes a failure is exactly the partially
    written output the atomic-publication rule exists to prevent. Every product field is ``None``
    — an extraction that never happened has no text, no metrics and no metadata, and a zero or an
    empty string would read as a measured answer.

    Args:
        error: The typed failure that ended the run.

    Returns:
        The failed result, already validated: the descriptive state says which kind of problem
        ended the run (``PARSE_ERROR`` for a representation that could not be produced).
    """
    result = OCRResult(
        text=None,
        markdown=None,
        structured_document=None,
        tables=None,
        blocks=None,
        layout=None,
        reading_order=None,
        metrics=None,
        artifacts=None,
        validation=OCRValidation(status="ERROR", errors=[error], missing_artifacts=[]),
        metadata=None,
        status="failed",
        error=error,
    )
    result.validation = validate_ocr_result(result)
    return result


def _transformations(layout: bool, reading_order: bool) -> list[str]:
    """Return every normalization this run applied, in order.

    It is a record of work, not of configuration: the option set already says what was asked for,
    and this says what was done with what came back.
    """
    applied = ["normalize_ocr_text", "normalize_markdown", "merge_ocr_blocks"]
    if layout:
        applied.append("normalize_layout")
    if reading_order:
        applied.append("preserve_reading_order")
    return applied


def _assemble_result(
    request: OCRRequest,
    extraction: _Extraction,
    structured: dict[str, Any],
    artifacts: ArtifactPaths,
    failures: list[OCRError],
    engine_version: str,
    started: float,
) -> OCRResult:
    """Assemble the result of a run that measured its input and published its artifacts.

    The failure list is shared rather than copied on purpose: publishing the metadata happens after
    this call, and a failure there has to reach the validation record instead of being dropped
    between the two steps.
    """
    document = extraction.document
    options = normalize_docling_options(request.options)
    validation = OCRValidation(status="VALID", errors=failures, missing_artifacts=[])
    return OCRResult(
        text=document.text,
        markdown=extraction.markdown,
        structured_document=structured,
        tables=extraction.ordered.tables,
        blocks=extraction.ordered.blocks,
        layout=document.layout,
        reading_order=extraction.ordered.reading_order,
        metrics=extraction.metrics,
        artifacts=artifacts,
        validation=validation,
        metadata=build_ocr_metadata(
            request.image_path,
            request.context,
            engine_version=engine_version,
            processor_version=PROCESSOR_VERSION,
            options=options,
            metrics=extraction.metrics,
            validation=validation,
            timing={"total": perf_counter() - started},
            transformations=_transformations(options.layout, options.reading_order),
        ),
        status="success",
        error=None,
    )


def _metadata_payload(request: OCRRequest, result: OCRResult) -> dict[str, Any]:
    """Return the ``metadata.json`` payload of a finished run.

    ``timing`` is the only run-time data in the whole artifact tree; the functional content — text,
    Markdown and the structured document — carries none, which is what makes two runs comparable
    byte for byte.
    """
    metadata = result.metadata
    if metadata is None or result.artifacts is None or result.metrics is None:
        raise typed_failure(
            "INTERNAL_ERROR",
            "a published run reported no metadata to record",
            recoverable=False,
            metadata={"output_dir": str(request.output_dir)},
        )
    return {
        "processor": PROCESSOR_NAME,
        "processor_version": PROCESSOR_VERSION,
        "engine": ENGINE_NAME,
        "engine_version": metadata.engine_version,
        "document_id": request.context.document_id,
        "workflow_run_id": request.context.workflow_run_id,
        "processing_key": _processing_key(request),
        "schema_version": DOCUMENT_SCHEMA_VERSION,
        "status": result.status,
        "options": _normalized_options(request),
        "input": str(request.image_path),
        "metrics": asdict(result.metrics),
        "validation": {
            "status": metadata.validation.status,
            "errors": [asdict(error) for error in metadata.validation.errors],
            "missing_artifacts": [
                str(path) for path in metadata.validation.missing_artifacts
            ],
        },
        "timing": metadata.timing,
        "transformations": list(metadata.transformations),
    }


def _extract(
    request: OCRRequest, normalized: NormalizedOCROptions, engine_version: str
) -> _Extraction:
    """Run the engine once and translate everything it returned.

    Args:
        request: The request being processed.
        normalized: The canonical options, which decide what the run claims.
        engine_version: The version the engine reported.

    Returns:
        The document, its Markdown representation, the ordered content, the measurements and the
        recoverable failures the conversion itself reported.

    Raises:
        OCRPrimitiveError: When the conversion failed outright, or when a representation could not
            be produced — the caller reports it as the run's typed failure.
    """
    conversion = _convert(request.image_path, configure_image_pipeline(normalized))
    reported = conversion_failure(conversion, request.image_path)
    if reported is not None and not reported.recoverable:
        raise OCRPrimitiveError(reported)

    geometry = extract_docling_layout(conversion)
    blocks = extract_docling_blocks(conversion, geometry, with_layout=normalized.layout)
    # The tables flag decides what is *claimed*: the engine is configured without table detection
    # when it is off, and a table that arrived anyway is not reported as a result of this run.
    tables = (
        extract_docling_tables(conversion, geometry, with_layout=normalized.layout)
        if normalized.tables
        else []
    )
    ordered = preserve_reading_order(
        blocks, tables, by_geometry=normalized.reading_order
    )
    document = build_ocr_document(
        text=normalize_ocr_text(extract_docling_text(conversion)),
        blocks=ordered.blocks,
        tables=ordered.tables,
        layout=normalize_layout(geometry, with_regions=normalized.layout),
        reading_order=ordered.reading_order,
        options=normalized,
        engine_version=engine_version,
    )
    return _Extraction(
        document=document,
        markdown=normalize_markdown(extract_docling_markdown(conversion)),
        ordered=ordered,
        metrics=analyze_ocr_result(document),
        failures=[] if reported is None else [reported],
    )


def process_ocr_image(request: OCRRequest) -> OCRResult:
    """Extract text, structure and tables from a prepared image.

    Args:
        request: The prepared image to read and the OCR options to use.
            ``request.output_dir`` is the ``ocr/`` namespace.

    Returns:
        The extraction result and the paths of the artifacts published under ``ocr/``. On the happy
        path ``status`` is ``"success"`` and ``validation.status`` reports what the extraction
        contained — ``VALID``, ``EMPTY`` for an image with no text, or ``LOW_CONTENT`` for a page
        too short to be useful. A failure is reported as a typed
        :class:`~docflow.ocr.contracts.OCRError` inside the result and is never raised across the
        contract; the input image is never written to.
    """
    started = perf_counter()

    try:
        validate_ocr_input(request.image_path)
        engine_version = get_engine_version()
        normalized = normalize_docling_options(request.options)
        extraction = _extract(request, normalized, engine_version)
    except OCRPrimitiveError as failure:
        return _failed_result(failure.error)

    # Two different things are counted here, and the difference decides the run's status. A *gap*
    # is what the engine reported about a conversion that still produced a document — a partial
    # result is not a failure, and the validation says so. A *loss* is an artifact this run could
    # not publish, which is a failure whatever else succeeded.
    failures: list[OCRError] = list(extraction.failures)
    gaps = len(failures)
    artifacts = _artifact_paths(request.output_dir)
    # One value, one file: the serialized document the result reports and the bytes of
    # ``document.json`` are the same object, so the two can never drift apart.
    structured = asdict(extraction.document)
    attempts = (
        (write_text_atomic, (artifacts.text, extraction.document.text)),
        (write_text_atomic, (artifacts.markdown, extraction.markdown)),
        (write_json_atomic, (artifacts.structured_document, structured)),
        (process_tables, (extraction.ordered.tables, artifacts.tables_dir)),
    )
    lost = sum(
        _attempt(failures, action, *arguments) is None for action, arguments in attempts
    )

    result = _assemble_result(
        request, extraction, structured, artifacts, failures, engine_version, started
    )
    result.validation = validate_ocr_result(result)
    result.metadata = replace(result.metadata, validation=result.validation)

    # The metadata publication is attempted, not assumed: a failure to write it is recorded and
    # reported, so the run never claims a success whose record is missing from disk.
    lost += (
        _attempt(
            failures,
            write_json_atomic,
            artifacts.metadata,
            _metadata_payload(request, result),
        )
        is None
    )

    if lost:
        result.status = "failed"
        result.error = failures[gaps]

    result.validation = validate_ocr_result(result)
    result.metadata = replace(result.metadata, validation=result.validation)
    return result


def process_ocr_from_page(
    image_path: Path,
    output_dir: Path,
    options: OCROptions,
    document_id: str,
    page_number: int,
    workflow_run_id: str,
) -> OCRResult:
    """Extract from a page image, building the request and delegating.

    It never reads a PDF and never selects a page image itself: those belong to other processors,
    and this wrapper only carries the correlation identity a page-level caller already has.

    # TODO: [MVP] no Phase 1 caller composes this: the subplan §9 defers it to the Phase 3
    # integration, where the orchestrator hands it a rendered page.
    """
    return process_ocr_image(
        OCRRequest(
            image_path=image_path,
            output_dir=output_dir,
            options=options,
            context=OCRContext(
                document_id=document_id,
                page_number=page_number,
                workflow_run_id=workflow_run_id,
            ),
        )
    )
