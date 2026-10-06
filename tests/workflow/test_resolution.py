"""The stage decision order (``ORC-07``)."""

from __future__ import annotations

from docflow.states import StageState
from docflow.workflow.resolution import resolve_stage
from tests.workflow.samples import execution_policy


def test_a_reusable_stage_is_reused() -> None:
    """A valid result whose key matches is not paid for twice."""
    resolution = resolve_stage(
        "OCR",
        policy=execution_policy(),
        processing_key="key",
        reusable=True,
    )

    assert resolution.action == "REUSE"
    assert resolution.reason == "valid_result_reused"
    assert resolution.processing_key == "key"


def test_a_stage_with_no_result_executes() -> None:
    """Nothing to reuse means execute."""
    resolution = resolve_stage(
        "OCR", policy=execution_policy(), processing_key="key", reusable=False
    )

    assert resolution.action == "EXECUTE"
    assert resolution.reason == "no_valid_result"


def test_an_explicit_skip_outranks_reuse() -> None:
    """The caller's stated skip wins over a result that could have been reused."""
    resolution = resolve_stage(
        "OCR",
        policy=execution_policy(skip_stages=["OCR"]),
        processing_key="key",
        reusable=True,
    )

    assert resolution.action == "SKIP"
    assert resolution.reason == "explicit_skip"


def test_an_explicit_skip_outranks_a_force() -> None:
    """The order is the contract: skip is decided before force."""
    resolution = resolve_stage(
        "OCR",
        policy=execution_policy(skip_stages=["OCR"], force_stages=["OCR"]),
        processing_key="key",
        reusable=True,
    )

    assert resolution.action == "SKIP"


def test_a_force_outranks_reuse() -> None:
    """Paying again is the point of a force."""
    resolution = resolve_stage(
        "OCR",
        policy=execution_policy(force_stages=["OCR"]),
        processing_key="key",
        reusable=True,
    )

    assert resolution.action == "FORCE"
    assert resolution.reason == "forced_by_policy"


def test_a_force_outranks_a_routing_skip() -> None:
    """Forcing OCR on a page with native text must still run it."""
    resolution = resolve_stage(
        "OCR",
        policy=execution_policy(force_stages=["OCR"]),
        processing_key="key",
        reusable=True,
        skip_reason="native_text_present",
    )

    assert resolution.action == "FORCE"


def test_a_routing_reason_skips_the_stage() -> None:
    """The run's own reason is recorded as the skip's reason."""
    resolution = resolve_stage(
        "OCR",
        policy=execution_policy(),
        processing_key="key",
        reusable=False,
        skip_reason="native_text_present",
    )

    assert resolution.action == "SKIP"
    assert resolution.reason == "native_text_present"


def test_a_stage_whose_input_cannot_arrive_is_blocked() -> None:
    """An impossible input is named, not run and failed."""
    resolution = resolve_stage(
        "OCR",
        policy=execution_policy(),
        processing_key="key",
        reusable=False,
        input_available=False,
    )

    assert resolution.action == "BLOCKED"
    assert resolution.reason == "input_unavailable"


def test_a_failed_stage_is_not_retried_when_the_policy_forbids_it() -> None:
    """``retry_failed`` is read, not assumed."""
    resolution = resolve_stage(
        "OCR",
        policy=execution_policy(retry_failed=False),
        processing_key="key",
        reusable=False,
        prior_status=StageState.FAILED,
    )

    assert resolution.action == "BLOCKED"
    assert resolution.reason == "failed_and_retry_disabled"
