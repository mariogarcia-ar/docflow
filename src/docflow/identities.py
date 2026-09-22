"""The three identities, and the artifact ``metadata.json`` key set that carries them.

Reuse, resume and idempotency are only expressible if a run, a document and a unit of work
each have a stable name. Those are the three identities:

``document_id``
    Which document this is. Supplied by the caller, preserved end to end, and never
    generated from a path: the same bytes reached by two paths are the same document.

``workflow_run_id``
    Which run of the orchestrator this is. Generated per run by
    :func:`~docflow.workflow.identity.build_workflow_run_id`; it identifies a run, and it
    never participates in a processing key.

``processing_key``
    Which unit of work a cached result belongs to. Two results are interchangeable only
    if their keys match.

The processing key is defined exactly as the plan fixes it::

    processing_key = hash(processor + processor_version + input_hashes + normalized_options)

Two consequences follow, and they are the reason the formula names its inputs explicitly:

* a change to a **processor version** changes the key, so an upgraded processor never
  reuses output the previous version produced;
* **normalized** options are hashed, not raw ones, so two spellings of the same
  configuration yield the same key.

The run identity is absent from the formula on purpose: a new run over unchanged inputs
must reproduce the same key, or reuse would never trigger.

This module fixes the names. The hashing itself lives in ``ORC-02`` and the LLM node-level
``request_key`` in ``LLM-05``; both consume the definition above.
"""

from __future__ import annotations

from typing import Final

#: The three identity field names, in the order they should appear in documentation.
IDENTITY_FIELDS: Final[tuple[str, ...]] = (
    "document_id",
    "workflow_run_id",
    "processing_key",
)

#: The processing-key definition, verbatim from `docs/plan/subplan-orquestador.md` §3.4.
PROCESSING_KEY_FORMULA: Final[str] = (
    "hash(processor + processor_version + input_hashes + normalized_options)"
)

#: Keys every artifact ``metadata.json`` must record, whatever the processor.
#:
#: ``engine`` and ``engine_version`` are here because a re-run is only comparable to a
#: previous one when the engine that produced each is known; ``processing_key`` is here
#: because that is what makes the artifact reusable rather than merely present.
ARTIFACT_METADATA_KEYS: Final[tuple[str, ...]] = (
    "processor",
    "processor_version",
    "engine",
    "engine_version",
    "document_id",
    "workflow_run_id",
    "processing_key",
)

#: Keys a per-page artifact ``metadata.json`` must record, in addition to
#: :data:`ARTIFACT_METADATA_KEYS`.
PAGE_ARTIFACT_METADATA_KEYS: Final[tuple[str, ...]] = ("page_number",)
