"""Orchestrator: ``DocumentRequest → DocumentResult``.

The only component that knows the whole workflow. It decides what runs, in what order,
whether OCR or vision runs, which source is selected, when to reuse / skip / force /
resume, how to consolidate and how to report a failure. It implements no PDF, image, OCR
or LLM logic, and it is the only caller of the four processors — and only through their
public contracts, never through a ``primitives/`` module.

Principle line: *processors transform; the orchestrator decides, coordinates, manages
state and controls execution.*

Entry points: :func:`process_document` and :func:`process_page`. Two workflow levels exist
and must not mix — the documental level here, and the inference level inside
``docflow.llm``.

Phase 0 ships the skeleton. Phase 2 fills it in: ``ORC-01`` … ``ORC-19``, with the
decisions, invalidation, resume and consolidation guarantees of
``docs/plan/subplan-orquestador.md``.

Symbols are re-exported here. A processor that only needs to report a state imports
:mod:`docflow.states` directly and never this module.
"""

from __future__ import annotations

from docflow.workflow.contracts import (
    DocumentInputType,
    DocumentRequest,
    DocumentResult,
    DocumentStatus,
    ExecutionPolicy,
)
from docflow.workflow.entrypoints import process_document, process_page

__all__ = [
    "DocumentInputType",
    "DocumentRequest",
    "DocumentResult",
    "DocumentStatus",
    "ExecutionPolicy",
    "process_document",
    "process_page",
]
