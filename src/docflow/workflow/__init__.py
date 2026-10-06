"""Orchestrator: ``DocumentRequest → DocumentResult``.

The only component that knows the whole workflow. It decides what runs, in what order,
whether OCR or vision runs, which source is selected, when to reuse / skip / force /
resume, how to consolidate and how to report a failure. It implements no PDF, image, OCR
or LLM logic, and it is the only caller of the four processors — and only through their
public contracts, never through a ``primitives/`` module.

Principle line: *processors transform; the orchestrator decides, coordinates, manages
state and controls execution.*

Entry points: :func:`process_document`, :func:`process_page` and :func:`resume_document`.
Two workflow levels exist and must not mix — the documental level here, and the inference
level inside ``docflow.llm``.

The modules behind these symbols are mirrors of the workflow's own tasks: ``identity``
(``ORC-02``), ``context`` and ``persistence`` (``ORC-03``), ``stages`` (``ORC-04``),
``detection`` (``ORC-05``), ``planning`` (``ORC-06``), ``resolution`` (``ORC-07``),
``reuse`` (``ORC-08``), ``dependencies`` (``ORC-09``), ``preparation`` (``ORC-10``),
``execution`` (``ORC-11``), ``selection`` (``ORC-12``), ``llm_input`` (``ORC-13``),
``invocation`` (``ORC-14``), ``resume`` (``ORC-15``), ``errors`` (``ORC-16``),
``consolidation`` (``ORC-17``), ``tracing`` (``ORC-18``).

Symbols are re-exported here. A processor that only needs to report a state imports
:mod:`docflow.states` directly and never this module.
"""

from __future__ import annotations

from docflow.workflow.consolidation import (
    consolidate_document_result,
    consolidate_page_result,
)
from docflow.workflow.contracts import (
    DetectedInputType,
    DocumentContext,
    DocumentInputType,
    DocumentRequest,
    DocumentResult,
    DocumentStatus,
    ErrorOutcome,
    ExecutionPlan,
    ExecutionPolicy,
    ExtractionStrategy,
    PageContext,
    PageResult,
    PlannedStage,
    SourceKind,
    StageAction,
    StageExecution,
    StageName,
)
from docflow.workflow.dependencies import (
    dependencies_of,
    downstream_of,
    invalidate_downstream,
)
from docflow.workflow.detection import detect_input_type
from docflow.workflow.entrypoints import (
    process_document,
    process_page,
    resume_document,
)
from docflow.workflow.errors import handle_processor_error
from docflow.workflow.llm_input import build_llm_input
from docflow.workflow.planning import build_execution_plan
from docflow.workflow.resolution import resolve_stage
from docflow.workflow.reuse import is_stage_reusable, validate_stage_outputs
from docflow.workflow.selection import (
    select_extraction_strategy,
    select_source,
)

__all__ = [
    "DetectedInputType",
    "DocumentContext",
    "DocumentInputType",
    "DocumentRequest",
    "DocumentResult",
    "DocumentStatus",
    "ErrorOutcome",
    "ExecutionPlan",
    "ExecutionPolicy",
    "ExtractionStrategy",
    "PageContext",
    "PageResult",
    "PlannedStage",
    "SourceKind",
    "StageAction",
    "StageExecution",
    "StageName",
    "build_execution_plan",
    "build_llm_input",
    "consolidate_document_result",
    "consolidate_page_result",
    "dependencies_of",
    "detect_input_type",
    "downstream_of",
    "handle_processor_error",
    "invalidate_downstream",
    "is_stage_reusable",
    "process_document",
    "process_page",
    "resolve_stage",
    "resume_document",
    "select_extraction_strategy",
    "select_source",
    "validate_stage_outputs",
]
