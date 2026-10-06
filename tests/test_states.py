"""Tests for the shared stage-state vocabulary (``GEN-03``).

The vocabulary is a *closed* set of nine states. That closure is an invariant, not a
convention: an extra member would let one component report a state another cannot
interpret, and an alias would let ``SKIPPED`` and ``REUSED`` become the same word.
"""

from __future__ import annotations

import importlib
import json

from docflow.states import StageState

# The nine states `README.md` §5 Phase 0 fixes and §9.6 closes, in the documented order.
# The idea's §"Estados de nodo" lists the same nine for the LLM subgraph, which is why
# `LLM-01` requires the node vocabulary to be "aligned with the orchestrator vocabulary".
DOCUMENTED_MEMBERS = [
    "NOT_STARTED",
    "READY",
    "RUNNING",
    "SUCCESS",
    "FAILED",
    "SKIPPED",
    "REUSED",
    "INVALIDATED",
    "PAUSED",
]


def test_vocabulary_has_exactly_the_documented_members() -> None:
    """The enum has the nine documented members and nothing else."""
    assert [member.name for member in StageState] == DOCUMENTED_MEMBERS


def test_no_member_is_a_silent_alias_of_another() -> None:
    """Every member has a distinct value, so no two states are the same word."""
    values = [member.value for member in StageState]

    assert len(set(values)) == len(values)


def test_every_member_value_equals_its_name() -> None:
    """A state serializes under the name the plan documents."""
    for member in StageState:
        assert member.value == member.name


def test_skipped_and_reused_stay_distinct() -> None:
    """Deliberately not running is not the same as not having to run."""
    assert StageState.SKIPPED != StageState.REUSED


def test_a_state_round_trips_through_json() -> None:
    """The vocabulary serializes as a plain string, with no custom encoder."""
    assert json.loads(json.dumps(StageState.REUSED)) == "REUSED"


def test_the_vocabulary_is_a_str_enum() -> None:
    """States compare equal to their string form, as the persistence layer expects."""
    assert isinstance(StageState.SUCCESS, str)
    assert StageState.SUCCESS == "SUCCESS"


def test_the_llm_subgraph_reuses_the_same_vocabulary() -> None:
    """A node state is a stage state: one concept, one set of words."""
    node_state = importlib.import_module("docflow.llm.contracts").LLMNodeState

    assert node_state is StageState
    assert {member.name for member in node_state} == set(DOCUMENTED_MEMBERS)
