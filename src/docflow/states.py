"""The shared stage-state vocabulary — one set of words for the whole pipeline.

The orchestrator, the four processors and the LLM inference subgraph all report state
with these words, so a state recorded by one component is readable by another.

The set is **closed**: exactly the nine members below, with no further member added
without an explicit plan revision. Two members exist precisely because the distinction
matters operationally:

* ``SKIPPED`` — the stage was deliberately *not* run.
* ``REUSED`` — a valid result already existed, so the stage did not need to run.

Conflating those two hides the difference between "we chose not to pay" and "we did not
have to pay", which is the whole basis of the reuse rule.

This module is deliberately free of the orchestrator's decision logic. A processor that
needs to report a state imports this module and nothing else; it never imports
``docflow.workflow``, because deciding what a state means is the orchestrator's job.
"""

from __future__ import annotations

from enum import StrEnum


class StageState(StrEnum):
    """State of one stage of the document workflow.

    A ``str`` subclass, so a state round-trips through JSON without a custom encoder.
    """

    NOT_STARTED = "NOT_STARTED"
    READY = "READY"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    REUSED = "REUSED"
    INVALIDATED = "INVALIDATED"
    PAUSED = "PAUSED"
