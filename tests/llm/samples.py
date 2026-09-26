"""Committed samples and request builders shared by the LLM processor's tests.

The template and the schema are the two fixtures the subplan §6 names, committed verbatim under
``tests/fixtures/llm/`` — and they are *assets*, resolved through the root the request states in
``metadata["assets_dir"]``, exactly as a production caller would resolve its own prompt registry.
The document text is a literal here rather than a file: the request carries text, and nothing in
this processor reads a document from disk.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Final

from docflow.llm import LLMGraphState, LLMInput, Usage
from docflow.llm.primitives import default_inference_graph
from docflow.states import StageState
from tests.factories import build_llm_input

#: The asset root both committed fixtures live under.
ASSETS: Final[Path] = Path(__file__).resolve().parents[1] / "fixtures" / "llm"

#: The document the happy path sends. Deliberately short and domain-free: this processor's job is
#: the call, not the document.
DOCUMENT: Final[str] = (
    "The northern region closed the quarter at twelve percent above plan.\n"
    "Two of the three warehouses were audited in the same period."
)

#: The answer the scripted fake returns by default: one object that satisfies ``simple`` exactly.
ANSWER: Final[dict[str, Any]] = {
    "summary": "The document describes one region and its revenue.",
    "topics": ["region", "revenue"],
    "page_count": 3,
}


def measured_usage() -> Usage:
    """Return the usage record the committed fake reports, so two tests cannot spell it differently.

    It is what the fake's Ollama body reports (twelve prompt tokens, four generated), and it is
    shared because both the contract round trip and the persistence round trip need a usage record
    to travel through their own machinery.
    """
    return Usage(
        input_tokens=12,
        output_tokens=4,
        total_tokens=16,
        cached_tokens=None,
        provider_usage={"prompt_eval_count": 12, "eval_count": 4},
        estimated_cost=None,
    )


#: The identity every sample request carries, so a test that varies one field varies only one.
CONTEXT: Final[dict[str, Any]] = {"document_id": "doc-1", "workflow_run_id": "run-1"}


def build_input(
    *,
    assets: Path | None = ASSETS,
    output_dir: Path | None = None,
    run_id: str | None = None,
    document: str | None = DOCUMENT,
    metadata: dict[str, Any] | None = None,
    **overrides: Any,
) -> LLMInput:
    """Return a valid single-call input rooted in the committed fixtures.

    Args:
        assets: The asset root to state in ``metadata["assets_dir"]``, or ``None`` to state none —
            which is how the tests reach the "no asset root" path.
        output_dir: The ``llm/`` namespace to persist into, or ``None`` to persist nothing.
        run_id: The identity to pin, or ``None`` to let the run mint one.
        document: The document text, or ``None`` for a request that carries none.
        metadata: Additional metadata keys.
        overrides: Further fields of the shared factory to replace.

    Returns:
        The request, with the correlation identity, the asset root and the option set in one place.
    """
    stated: dict[str, Any] = {**CONTEXT, **(metadata or {})}
    if assets is not None:
        stated["assets_dir"] = str(assets)
    if output_dir is not None:
        stated["output_dir"] = str(output_dir)
    if run_id is not None:
        stated["run_id"] = run_id
    return replace(
        build_llm_input(),
        document=document,
        extra_context={"source": "native_text"},
        metadata=stated,
        **overrides,
    )


def empty_state(
    graph_id: str = "default_inference", run_id: str = "run-1"
) -> LLMGraphState:
    """Return a chain state that has not started, for the cases that build their own."""
    return LLMGraphState(
        run_id=run_id,
        graph_id=graph_id,
        graph_version="1",
        status=StageState.RUNNING,
        current_nodes=[],
        node_states={},
        node_results={},
        attempts={},
        comparisons={},
        errors=[],
        usage=Usage(None, None, None, None, {}, None),
        stop_requested=False,
        final_result=None,
    )


def build_graph_input(
    output_dir: Path | None, *, graph: dict[str, Any] | None = None, **overrides: Any
) -> LLMInput:
    """Return a valid graph input whose run namespace is ``output_dir``.

    The descriptor defaults to the documented chain, taken from the processor's own default so the
    tests and the shipped default cannot drift apart; a test that wants another shape passes one.

    Args:
        output_dir: The ``llm/`` namespace the run persists into, or ``None`` for an in-memory run.
        graph: The descriptor to run, or ``None`` for the documented chain.
        overrides: Fields of :func:`build_input` to replace.
    """
    return build_input(
        output_dir=output_dir,
        run_id="run-1",
        graph=default_inference_graph() if graph is None else graph,
        **overrides,
    )
