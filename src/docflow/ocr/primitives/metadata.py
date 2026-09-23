"""The provenance record and the ``metadata.json`` payload (``OCR-10``) - §3.4's *Metadata* group.

Three functions, and the split between them is the whole design:

* :func:`build_ocr_metadata` assembles the typed :class:`~docflow.ocr.contracts.OCRMetadata` record
  — engine, versions, options, input, metrics, validation, timing, transformations, context.
* :func:`build_metadata_payload` renders that record as the ``metadata.json`` object, adding the
  identities every artifact's metadata must carry (``docflow.identities.ARTIFACT_METADATA_KEYS``).
* :func:`merge_ocr_metadata` folds the engine's own reported facts into the payload.

They are separate because they have different inputs and different lifetimes: the record is built
while the run happens, the payload is assembled at publish time, and the merge comes last because
the engine's facts are the ones most likely to be absent.

**Timing lives here and nowhere else.** ``ocr/metadata.json`` is the only artifact allowed to carry
a duration or a clock reading; ``text.txt``, ``document.md`` and ``document.json`` must be
byte-identical across two runs over one page, which is ``OCR-06``'s determinism posture and
``OCR-12``'s invariant 2. So :func:`build_metadata_payload` takes timing as an **input** and never
reads a clock itself — a function that called ``time.monotonic`` would need a path that produced a
timestamp from nothing, and it has none.

``processing_key`` is **not this processor's to compute**. ``subplan-orquestador.md`` §3.4 defines
it
as ``hash(processor + processor_version + input_hashes + normalized_options)`` and ``ORC-02`` owns
it, because the formula needs normalized options and input hashes — orchestrator knowledge. A
processor that hashed its own key would be making a workflow decision, which
``subplan-procesador-ocr.md`` §2 puts out of bounds. So the payload builder takes the key from its
caller and records ``None`` until the orchestrator supplies one: an explicit "not yet computed" is
honest, whereas a self-computed hash would be a second, disagreeing implementation of a value the
reuse rule depends on being identical everywhere. The PDF processor records the same reasoning.

Every payload field is expanded explicitly rather than dumped with ``dataclasses.asdict``: the file
is a schema other tools read, so a record gaining a field should be a visible edit here rather than
a
silent addition to the output.
"""

from __future__ import annotations

# pylint: disable=duplicate-code
# The payload renderer is parallel to `docflow.image.primitives.atomic`'s and to the PDF
# processor's provenance module, for the reason `files.py` records: `docs/plan/README.md` §3 forbids
# a processor importing another, so the shared shape cannot be factored out. The *keys* are not
# duplicated - they come from `docflow.identities.ARTIFACT_METADATA_KEYS` - only the expansion of
# this processor's own records into JSON.
from pathlib import Path
from typing import Any, Final

from docflow.identities import ARTIFACT_METADATA_KEYS
from docflow.ocr.contracts import (
    NormalizedOCROptions,
    OCRContext,
    OCRError,
    OCRMetadata,
    OCRMetrics,
    OCRValidation,
)

PROCESSOR_NAME: Final[str] = "ocr"
"""This processor's name, as it appears in every artifact it publishes."""

PROCESSOR_VERSION: Final[str] = "0.0.0"
"""Version of this processor's implementation.

Deliberately a module constant rather than ``importlib.metadata.version("docflow")``: the package is
not installed in the no-install test path ``pyproject.toml`` supports, so a distribution lookup
would fail exactly where it is needed most. Bumping it must be part of any change to what the
processor produces, because ``identities.PROCESSING_KEY_FORMULA`` puts the version in the reuse key.

``# TODO: [RELEASE]`` derive this from the package distribution once an installed deployment is the
only supported mode, so a release cannot ship with a stale constant.
"""

TABLES_PUBLISHED_KEY: Final[str] = "tables_published"
"""Payload key recording how many per-table files were written.

Not part of :class:`~docflow.ocr.contracts.OCRMetadata`, which is the *extraction's* provenance:
this count is provenance of the *publication*, and no other field implies it — ``metrics.tables`` is
how many grids the engine found, which a failed write would leave unchanged.
"""


def get_processor_version() -> str:
    """Return this processor's version.

    Returns:
        The version string recorded in every artifact's ``metadata.json``.
    """
    return PROCESSOR_VERSION


def build_ocr_metadata(
    engine: str,
    engine_version: str,
    processor_version: str,
    options: NormalizedOCROptions,
    image_path: Path,
    metrics: OCRMetrics,
    validation: OCRValidation,
    timing: dict[str, float],
    transformations: list[str],
    context: OCRContext,
) -> OCRMetadata:
    """Assemble the provenance record.

    No field has a fallback. A blank engine or version would be the silent stand-in the plan
    forbids, and every argument is passed straight through, so a caller with nothing to record
    cannot get a plausible-looking default from here: it has to hand over the value or not call this
    function.

    Args:
        engine: The engine's name, from the seam.
        engine_version: The engine's version, from the seam.
        processor_version: This processor's version.
        options: The normalized options used.
        image_path: The image that was read.
        metrics: The content metrics.
        validation: The validation outcome.
        timing: Wall-clock seconds by stage.
        transformations: Every transformation applied, in order.
        context: The correlation context, echoed unchanged.

    Returns:
        The record.
    """
    return OCRMetadata(
        engine=engine,
        engine_version=engine_version,
        processor_version=processor_version,
        options=options,
        input=image_path,
        metrics=metrics,
        validation=validation,
        timing=dict(timing),
        transformations=list(transformations),
        context=context,
    )


def build_metadata_payload(
    metadata: OCRMetadata,
    *,
    processing_key: str | None,
    tables_published: int,
) -> dict[str, Any]:
    """Render the record as the ``metadata.json`` object.

    All seven keys :data:`docflow.identities.ARTIFACT_METADATA_KEYS` requires are present:
    ``processor`` and ``processor_version`` are this module's; ``engine`` and ``engine_version``
    come
    from the record; ``document_id`` and ``workflow_run_id`` come from the context; and
    ``processing_key`` comes from the caller, as ``None`` when the orchestrator has not computed
    one.

    **Neither keyword has a default, and that is the plan's rule rather than a preference.** The
    suite refuses any primitive that defaults an argument, because a default is a silent stand-in
    unless it is argued for. ``processing_key=None`` in particular would read as "this run has no
    reuse key" whether or not the caller had thought about it, and the value is what the reuse rule
    turns on — so a caller that has not been handed a key says so explicitly, once per call site.

    Args:
        metadata: The record to render.
        processing_key: The reuse key, or ``None`` when it has not been computed.
        tables_published: How many per-table files the run wrote.

    Returns:
        The payload, expanded field by field so a record gaining a field is a visible edit here
        rather than a silent addition to a schema other tools read.
    """
    return {
        "processor": PROCESSOR_NAME,
        "processor_version": metadata.processor_version,
        "engine": metadata.engine,
        "engine_version": metadata.engine_version,
        "document_id": metadata.context.document_id,
        "workflow_run_id": metadata.context.workflow_run_id,
        "processing_key": processing_key,
        "input": str(metadata.input),
        "page_number": metadata.context.page_number,
        "options": _options_payload(metadata.options),
        "metrics": _metrics_payload(metadata.metrics),
        "validation": _validation_payload(metadata.validation),
        "timing": dict(metadata.timing),
        "transformations": list(metadata.transformations),
        TABLES_PUBLISHED_KEY: tables_published,
    }


def merge_ocr_metadata(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    """Merge the engine's own metadata into the record.

    The engine's keys are its business and move between versions, so they are nested under one key
    rather than spread into the top level: a Docling upgrade that renamed a field would otherwise
    rename a key of *this* processor's schema. The nested object is a fresh dict, so the payload
    does not retain the caller's.

    A key collision cannot arise and is not guarded against: ``base``'s keys are this module's and
    ``extra``'s are one level down, so there is no shared namespace to collide in. A guard would be
    a branch no input can reach.

    Args:
        base: The record so far, from :func:`build_metadata_payload`.
        extra: The engine's own reported facts.

    Returns:
        The merged record.
    """
    merged = dict(base)
    merged["engine_metadata"] = {str(key): value for key, value in extra.items()}
    return merged


def require_metadata_keys(payload: dict[str, Any]) -> None:
    """Refuse a payload missing any key every artifact's metadata must carry.

    Extracted from :func:`build_metadata_payload` rather than left inline, for the reason the image
    processor records: the literal that function builds carries all seven keys by construction, so a
    check inside it is unreachable and no test can falsify it. As its own function it is true for
    any
    caller that assembles or amends a payload, and a mutation that disables it is caught.

    Args:
        payload: The payload to check.

    Raises:
        ValueError: A required key is absent, naming every one that is.
    """
    missing = [key for key in ARTIFACT_METADATA_KEYS if key not in payload]
    if missing:
        raise ValueError(
            f"the metadata payload is missing required keys {missing}; every artifact's "
            f"metadata.json must carry {list(ARTIFACT_METADATA_KEYS)}"
        )


def _options_payload(options: NormalizedOCROptions) -> dict[str, Any]:
    """Render normalized options as a JSON object.

    Args:
        options: The options to render.

    Returns:
        The object, with the engine passthrough nested under its own key.
    """
    return {
        "ocr": options.ocr,
        "layout": options.layout,
        "tables": options.tables,
        "reading_order": options.reading_order,
        "language": options.language,
        "engine_options": dict(options.engine_options),
    }


def _metrics_payload(metrics: OCRMetrics) -> dict[str, Any]:
    """Render the content metrics as a JSON object.

    Args:
        metrics: The metrics to render.

    Returns:
        The object.
    """
    return {
        "characters": metrics.characters,
        "words": metrics.words,
        "blocks": metrics.blocks,
        "tables": metrics.tables,
        "paragraphs": metrics.paragraphs,
        "text_density": metrics.text_density,
        "empty": metrics.empty,
        "structure_detected": metrics.structure_detected,
    }


def _validation_payload(validation: OCRValidation) -> dict[str, Any]:
    """Render the validation verdict as a JSON object.

    The verdict is recorded **as it stood at publish time**, so it is rendered rather than
    recomputed: a reader of the artifact is asking what the run concluded, not what the files would
    be judged to be now.

    Args:
        validation: The verdict to render.

    Returns:
        The object.
    """
    return {
        "status": validation.status,
        "errors": [_error_payload(error) for error in validation.errors],
        "missing_artifacts": [str(path) for path in validation.missing_artifacts],
    }


def _error_payload(error: OCRError) -> dict[str, Any]:
    """Render one typed failure as a JSON object.

    Args:
        error: The failure to render.

    Returns:
        The object.
    """
    return {
        "type": error.type,
        "message": error.message,
        "recoverable": error.recoverable,
        "metadata": dict(error.metadata),
    }


__all__ = [
    "PROCESSOR_NAME",
    "PROCESSOR_VERSION",
    "TABLES_PUBLISHED_KEY",
    "build_metadata_payload",
    "build_ocr_metadata",
    "get_processor_version",
    "merge_ocr_metadata",
    "require_metadata_keys",
]
