"""Tests for the LLM entry points (``LLM-06`` … ``LLM-15``).

The suite drives the real pipeline with the provider doubled, so every assertion is about our flow,
our keying, our recording and our error mapping. The two invariants the subplan §6 claims live
here, each with the mutation that must break it named in its docstring and recorded in the root
``README.md``; the third is deferred with the chain's dynamic machinery and is not claimed.
"""

from __future__ import annotations

import json
import shutil
import tomllib
from collections.abc import Callable
from pathlib import Path

import pytest

from docflow.llm import primitives
from docflow.llm.entrypoints import (
    NOT_PERSISTED,
    PROCESSOR_NAME,
    PROCESSOR_VERSION,
    execute_llm_graph,
    process_llm_node,
    process_llm_request,
)
from docflow.llm.primitives import (
    INFERENCE_CHAIN,
    STREAM_OPTION,
    StreamDelta,
    default_inference_graph,
)
from docflow.states import StageState
from tests.fakes.engines.fake_provider import FakeProvider
from tests.fakes.engines.fake_provider import invalid_json as not_json
from tests.llm.samples import (
    ANSWER,
    ASSETS,
    build_graph_input,
    build_input,
    empty_state,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

#: The other processors' namespaces, none of which this processor may touch.
OTHER_NAMESPACES = ("pdf", "image", "ocr", "source", "render")


def failed(kind: str, message: str = "no"):
    """Return the typed failure the seam would have produced for ``kind``."""
    return primitives.typed_failure(kind, message)  # type: ignore[arg-type]


# --- one call (LLM-06, LLM-07, LLM-08) ----------------------------------------------------------


def test_the_happy_path_returns_a_validated_result_from_one_call(
    provider: Callable[..., FakeProvider], tmp_path: Path
) -> None:
    """Acceptance: ``SUCCESS``, ``schema_valid``, a non-empty key and exactly one attempt."""
    output = tmp_path / "run_001"
    fake = provider()
    request = build_input(output_dir=output, run_id="run-1")

    result = process_llm_request(request)

    assert result.status == StageState.SUCCESS
    assert result.status == "SUCCESS"
    assert result.schema_valid is True
    assert not result.validation_errors
    assert not result.errors
    assert result.parsed_response == ANSWER
    assert len(result.attempts) == 1
    assert result.attempts[0].request_key
    assert result.attempts[0].validation == "VALID"
    assert result.usage.input_tokens == 12
    assert result.usage.total_tokens == 16
    assert result.timing.total_time >= 0
    assert len(fake.calls) == 1
    assert fake.calls[0].messages[0]["content"].startswith("Summarise the document")
    assert result.attempts[0].request_metadata["finish_reason"] == "stop"
    assert (
        "The northern region closed the quarter" in fake.calls[0].messages[0]["content"]
    )


def test_the_run_publishes_only_its_own_namespace_and_leaves_no_temporary_file(
    provider: Callable[..., FakeProvider], tmp_path: Path
) -> None:
    """Invariant: everything lands under the run's ``llm/`` namespace, atomically."""
    output = tmp_path / "run_001"
    provider()
    request = build_input(output_dir=output)

    result = process_llm_request(request)

    assert sorted(path.name for path in output.iterdir()) == ["final_result.json"]
    assert not list(tmp_path.rglob("*.tmp"))
    assert not any((tmp_path / namespace).exists() for namespace in OTHER_NAMESPACES)
    assert result.metadata["persisted"] == str(output)
    saved = json.loads((output / "final_result.json").read_text(encoding="utf-8"))
    assert saved["status"] == "SUCCESS"
    assert saved["parsed_response"] == ANSWER
    assert saved["attempts"][0]["request_key"] == result.attempts[0].request_key


def test_a_run_that_was_not_asked_to_persist_writes_nothing(
    provider: Callable[..., FakeProvider], tmp_path: Path
) -> None:
    """No namespace was requested, so no namespace appears — not even an empty one."""
    provider()

    result = process_llm_request(build_input())

    assert result.status == StageState.SUCCESS
    assert result.metadata["persisted"] == NOT_PERSISTED
    assert not list(tmp_path.rglob("*"))


def test_the_metadata_records_the_provenance_and_the_policy(
    provider: Callable[..., FakeProvider], tmp_path: Path
) -> None:
    """A reader of a run can see the key, the window, the policy and the estimated count."""
    provider()
    request = build_input(
        output_dir=tmp_path / "run_001",
        metadata={"model_version": "stated-v2"},
        options={"context_window": 4096, "max_attempts": 3, "temperature": 0.0},
    )

    result = process_llm_request(request)
    payload = json.loads(
        (tmp_path / "run_001" / "final_result.json").read_text(encoding="utf-8")
    )

    assert result.metadata["processor"] == PROCESSOR_NAME
    assert result.metadata["processor_version"] == PROCESSOR_VERSION
    assert result.metadata["document_id"] == "doc-1"
    assert result.metadata["workflow_run_id"] == "run-1"
    assert result.metadata["model_version"] == "stated-v2"
    assert result.metadata["context_window"] == 4096
    assert result.metadata["attempt_limit"] == 3
    assert result.metadata["prompt_tokens_estimated"] is True
    assert result.metadata["prompt_truncated"] is False
    assert payload["metadata"]["request_key"] == result.metadata["request_key"]
    assert payload["metadata"]["normalized_options"] == {
        "context_window": 4096,
        "max_attempts": 3,
        "temperature": 0.0,
    }


def test_the_declared_processor_version_matches_the_package() -> None:
    """Provenance that names the wrong code is worse than provenance that names none."""
    with (REPOSITORY_ROOT / "pyproject.toml").open("rb") as handle:
        declared = tomllib.load(handle)["project"]["version"]

    assert declared == PROCESSOR_VERSION


def test_the_credential_never_reaches_an_artifact(
    provider: Callable[..., FakeProvider], tmp_path: Path
) -> None:
    """A key is written to disk and persisted; an API key must not be in one."""
    provider()
    output = tmp_path / "run_001"

    process_llm_request(
        build_input(output_dir=output, options={"api_key": "secret-token"})
    )

    written = (output / "final_result.json").read_text(encoding="utf-8")
    assert "secret-token" not in written
    assert "api_key" not in written


def test_the_same_logical_request_keys_the_same_across_two_runs(
    provider: Callable[..., FakeProvider], tmp_path: Path
) -> None:
    """Invariant 2: the key is a function of the logical request, not of the run that made it.

    *Mutation that breaks it:* add the run identity to the key material — e.g. include
    ``pinned_run_id(request)`` in the dictionary :func:`calculate_request_key` is given — and the
    two runs below, which differ only in ``run_id`` and in their output directory, stop agreeing.
    """
    provider()
    first = process_llm_request(build_input(output_dir=tmp_path / "a", run_id="run-a"))
    second = process_llm_request(build_input(output_dir=tmp_path / "b", run_id="run-b"))

    first_attempt = first.attempts[0]
    second_attempt = second.attempts[0]
    assert first_attempt.request_key == second_attempt.request_key
    assert first.metadata["request_key"] == second.metadata["request_key"]
    assert first_attempt.attempt_id == second_attempt.attempt_id
    assert first.run_id != second.run_id
    assert first.metadata["prompt_tokens"] == second.metadata["prompt_tokens"]


def test_a_streamed_call_is_the_same_logical_request_as_a_waiting_one(
    tmp_path: Path,
) -> None:
    """Invariant: reading an answer as it is written does not change the request it answers.

    *Mutation that breaks it:* stop dropping ``stream`` in
    :func:`docflow.llm.primitives.normalize_llm_options` — let it hash with the rest of the
    options — and the two runs below, which differ only in whether they stream, disagree on
    ``request_key``. A streamed answer is the same answer, so a node one run streamed has to stay
    reusable by the next; the observer also has to be fed, and the deltas it is fed have to be the
    answer the call returned.
    """
    seen: list[StreamDelta] = []

    def observe(delta: StreamDelta) -> None:
        seen.append(delta)

    waiting = process_llm_request(build_input(output_dir=tmp_path / "a"))
    streamed = process_llm_request(
        build_input(
            output_dir=tmp_path / "b", options={STREAM_OPTION: True, "temperature": 0.0}
        ),
        observer=observe,
    )

    assert seen
    assert "".join(delta.text for delta in seen) == streamed.raw_response
    assert streamed.attempts[0].request_key == waiting.attempts[0].request_key
    assert streamed.metadata["request_key"] == waiting.metadata["request_key"]
    assert streamed.raw_response == waiting.raw_response
    assert streamed.parsed_response == waiting.parsed_response


def test_the_stream_switch_is_not_handed_to_the_provider_as_a_decoding_option(
    provider: Callable[..., FakeProvider], tmp_path: Path
) -> None:
    """``stream`` selects how the answer is read; the transport states the wire field itself."""
    fake = provider()

    process_llm_request(
        build_input(
            output_dir=tmp_path, options={STREAM_OPTION: True, "temperature": 0.0}
        ),
        observer=lambda delta: None,
    )

    call = fake.calls[0]
    assert call.stream is True
    assert call.observer is not None
    assert "stream" not in call.options
    assert call.options["temperature"] == 0.0


def test_a_retryable_invalid_answer_is_retried_and_the_prior_attempt_is_kept(
    provider: Callable[..., FakeProvider], tmp_path: Path
) -> None:
    """Acceptance: invalid JSON on attempt one, valid on attempt two, both attempts recorded."""
    fake = provider(answers=[not_json(), None])
    request = build_input(output_dir=tmp_path / "run_001", options={"max_attempts": 2})

    result = process_llm_request(request)

    assert result.status == StageState.SUCCESS
    assert result.schema_valid is True
    assert len(result.attempts) == 2
    assert result.attempts[0].error is not None
    assert result.attempts[0].error.type == "INVALID_JSON"
    assert result.attempts[0].validation == "RETRYABLE"
    assert result.attempts[0].status == "failed"
    assert result.attempts[1].error is None
    assert result.attempts[0].attempt_id != result.attempts[1].attempt_id
    assert result.attempts[0].request_key == result.attempts[1].request_key
    assert len(fake.calls) == 2


def test_a_failure_the_provider_cannot_fix_is_not_retried(
    provider: Callable[..., FakeProvider], tmp_path: Path
) -> None:
    """Acceptance: a ``NON_RETRYABLE`` error makes no further attempt, whatever the policy."""
    fake = provider(
        answers=[failed("MODEL_UNAVAILABLE", "the model is gone")],
    )
    request = build_input(output_dir=tmp_path / "run_001", options={"max_attempts": 5})

    result = process_llm_request(request)

    assert result.status == StageState.FAILED
    assert result.errors[0].type == "MODEL_UNAVAILABLE"
    assert len(result.attempts) == 1
    assert len(fake.calls) == 1
    assert result.metadata["attempt_limit"] == 5


def test_a_retryable_failure_stops_at_the_policy_limit(
    provider: Callable[..., FakeProvider], tmp_path: Path
) -> None:
    """The policy is a ceiling: a call that never validates stops at the stated attempt count."""
    fake = provider(answers=[not_json(), not_json(), not_json()])
    request = build_input(output_dir=tmp_path / "run_001", options={"max_attempts": 2})

    result = process_llm_request(request)

    assert result.status == StageState.FAILED
    assert len(result.attempts) == 2
    assert len(fake.calls) == 2
    assert result.errors[0].type == "INVALID_JSON"


def test_a_schema_violation_is_reported_with_the_fields_that_violated_it(
    provider: Callable[..., FakeProvider], tmp_path: Path
) -> None:
    """Acceptance: an answer that breaks the schema is refused, and the verdict names the field."""
    provider(answers=['{"summary": "s", "topics": "not-a-list"}'])
    request = build_input(output_dir=tmp_path / "run_001", options={"max_attempts": 1})

    result = process_llm_request(request)

    assert result.status == StageState.FAILED
    assert result.schema_valid is False
    assert result.errors[0].type == "SCHEMA_ERROR"
    assert result.validation_errors == ["$.topics: expected array, got string"]
    assert result.attempts[0].parsed_response == {
        "summary": "s",
        "topics": "not-a-list",
    }


def test_an_extra_field_is_never_silently_accepted(
    provider: Callable[..., FakeProvider], tmp_path: Path
) -> None:
    """Acceptance: the schema closes the object, so an unexpected field is a violation."""
    provider(answers=[json.dumps({**ANSWER, "surprise": 1})])
    request = build_input(output_dir=tmp_path / "run_001", options={"max_attempts": 1})

    result = process_llm_request(request)

    assert result.status == StageState.FAILED
    assert result.errors[0].type == "SCHEMA_ERROR"
    assert result.validation_errors == [
        "$: property 'surprise' is not allowed by the schema"
    ]


# --- planning failures (LLM-04, LLM-15) ---------------------------------------------------------


def test_a_request_without_an_asset_root_is_refused_before_any_call(
    provider: Callable[..., FakeProvider],
) -> None:
    """The root has no default, so a request that names none is a missing dependency."""
    fake = provider()
    request = build_input(assets=None)

    result = process_llm_request(request)

    assert result.status == StageState.FAILED
    assert result.errors[0].type == "DEPENDENCY_ERROR"
    assert not result.attempts
    assert fake.calls == []
    assert result.metadata["persisted"] == NOT_PERSISTED


def test_a_prompt_placeholder_the_request_cannot_fill_is_refused(
    provider: Callable[..., FakeProvider],
) -> None:
    """A missing document is reported, never rendered as an empty one."""
    fake = provider()
    request = build_input(document=None)

    result = process_llm_request(request)

    assert result.errors[0].type == "DEPENDENCY_ERROR"
    assert result.errors[0].metadata["placeholder"] == "<doc>"
    assert fake.calls == []


def test_a_prompt_longer_than_the_stated_window_is_refused_before_the_call(
    provider: Callable[..., FakeProvider],
) -> None:
    """Acceptance: the overflow is reported, and no call is made to discover it."""
    fake = provider()
    request = build_input(document="x" * 4000, options={"context_window": 100})

    result = process_llm_request(request)

    assert result.errors[0].type == "CONTEXT_OVERFLOW"
    assert result.metadata["persisted"] == NOT_PERSISTED
    assert fake.calls == []


def test_an_unknown_window_is_not_an_overflow(
    provider: Callable[..., FakeProvider],
) -> None:
    """With no stated window the call is made: an unmeasured ceiling is not evidence."""
    fake = provider()

    result = process_llm_request(build_input(document="x" * 4000))

    assert result.status == StageState.SUCCESS
    assert result.metadata["context_window"] is None
    assert result.metadata["context_verdict"] == "unmeasured"
    assert len(fake.calls) == 1


def test_the_window_the_pre_flight_checks_is_the_window_the_call_asks_for(
    provider: Callable[..., FakeProvider],
) -> None:
    """A statement that guards the call and a statement the provider gets are the same statement."""
    fake = provider()

    process_llm_request(build_input(options={"context_window": 4096}))

    assert fake.calls[0].context_window == 4096
    assert (
        fake.calls[0].options.get("num_ctx") is None
    )  # the transport's spelling, not this layer's


def test_a_local_only_option_is_not_handed_to_a_hosted_provider(
    provider: Callable[..., FakeProvider],
) -> None:
    """Ollama's own keys are dropped for a hosted dialect, which would spread them into its body."""
    fake = provider()

    process_llm_request(
        build_input(
            provider="deepseek",
            options={"num_ctx": 8192, "think": False, "temperature": 0.1},
        )
    )

    assert fake.calls[0].options == {"temperature": 0.1}


def test_a_local_only_option_is_kept_for_the_local_daemon(
    provider: Callable[..., FakeProvider],
) -> None:
    """The same keys are Ollama's own, so the local daemon still receives them."""
    fake = provider()

    process_llm_request(build_input(options={"num_ctx": 8192}))

    assert fake.calls[0].options["num_ctx"] == 8192


def test_a_deepseek_schema_travels_in_the_prompt_to_the_provider(
    provider: Callable[..., FakeProvider],
) -> None:
    """The dialect sends no schema on the wire, so the call the provider receives carries it in
    the prompt instead."""
    fake = provider()

    process_llm_request(build_input(provider="deepseek"))

    assert primitives.SCHEMA_BLOCK_HEADING in fake.calls[0].messages[0]["content"]


def test_a_page_image_reaches_the_call_and_keys_the_request(
    provider: Callable[..., FakeProvider], tmp_path: Path
) -> None:
    """Invariant 4: the image a request names is in the call the provider receives.

    *Mutation that breaks it:* drop ``images=list(request.images)`` from the planned call — the
    call is made, the double answers, and the page the request paid for never leaves the process.
    It is the streaming seam's defect the other way round: a field the seam carries that nothing
    above it fills in.

    The second half is why the bytes are keyed and not the path: a page re-exported under the same
    name is a different page, and an answer about the first is not an answer about the second.
    """
    page = tmp_path / "page.png"
    page.write_bytes(b"\x89PNG\r\n\x1a\nfirst")
    fake = provider()

    result = process_llm_request(
        build_input(document=None, images=[str(page)], template="simple_read_pixels")
    )

    assert result.status == StageState.SUCCESS
    assert fake.calls[0].images == [str(page)]
    assert result.metadata["images"] == 1
    first_key = result.attempts[0].request_key

    page.write_bytes(b"\x89PNG\r\n\x1a\nsecond")
    second = process_llm_request(
        build_input(document=None, images=[str(page)], template="simple_read_pixels")
    )

    assert second.attempts[0].request_key != first_key


def test_a_priced_image_is_counted_before_the_call_and_an_unpriced_one_is_no_fit(
    provider: Callable[..., FakeProvider], tmp_path: Path
) -> None:
    """Invariant 5: the pre-flight adds what the caller stated, and claims no fit it cannot measure.

    *Mutation that breaks it:* compare ``prompt.tokens`` alone — the text fits the stated window
    comfortably, so the call is made, the double answers, and nothing records that the window was
    the smaller number. The second half fails under the same mutation, because an image nobody
    priced would read as ``fits`` rather than ``unmeasured``.
    """
    page = tmp_path / "page.png"
    page.write_bytes(b"\x89PNG\r\n\x1a\npayload")
    priced = provider()

    result = process_llm_request(
        build_input(
            document=None,
            images=[str(page)],
            template="simple_read_pixels",
            options={"context_window": 4096},
            metadata={"image_tokens": 4000},
        )
    )

    assert result.errors[0].type == "CONTEXT_OVERFLOW"
    assert result.errors[0].metadata["image_tokens"] == 4000
    assert result.errors[0].metadata["images"] == 1
    assert priced.calls == []

    unpriced = provider()
    ran = process_llm_request(
        build_input(
            document=None,
            images=[str(page)],
            template="simple_read_pixels",
            options={"context_window": 4096},
        )
    )

    assert ran.status == StageState.SUCCESS
    assert ran.metadata["context_verdict"] == "unmeasured"
    assert len(unpriced.calls) == 1


def test_a_schema_this_processor_cannot_enforce_is_refused(
    provider: Callable[..., FakeProvider], tmp_path: Path
) -> None:
    """A rule we cannot apply is not a rule we may ignore."""
    fake = provider()
    assets = tmp_path / "assets"
    shutil.copytree(ASSETS, assets)
    (assets / "schema" / "patterned.schema.json").write_text(
        '{"type": "object", "properties": {"a": {"type": "string", "pattern": "^a+$"}}}',
        encoding="utf-8",
    )

    result = process_llm_request(build_input(assets=assets, schema="patterned"))

    assert result.status == StageState.FAILED
    assert result.errors[0].type == "SCHEMA_ERROR"
    assert fake.calls == []


def test_a_record_that_cannot_be_written_is_reported_rather_than_claimed(
    provider: Callable[..., FakeProvider],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Acceptance: the run never claims a success whose record is missing from disk."""
    provider()

    def refuse(*_args: object, **_kwargs: object) -> str:
        raise OSError("the filesystem refused the write")

    monkeypatch.setattr(Path, "write_text", refuse)

    result = process_llm_request(build_input(output_dir=tmp_path / "run_001"))

    assert result.status == StageState.FAILED
    assert result.errors[-1].type == "INTERNAL_ERROR"
    assert result.parsed_response == ANSWER


# --- the chain (LLM-10, LLM-11, LLM-12, LLM-13, LLM-14) -----------------------------------------


def test_the_chain_runs_every_node_and_consolidates_them(
    provider: Callable[..., FakeProvider], tmp_path: Path
) -> None:
    """Acceptance: the documented chain, every node ``SUCCESS``, one consolidated result."""
    output = tmp_path / "run_001"
    fake = provider()
    request = build_graph_input(output)

    result = process_llm_request(request)

    assert result.status == StageState.SUCCESS
    assert set(result.node_results) == set(INFERENCE_CHAIN)
    assert list(result.metadata["node_actions"]) == list(INFERENCE_CHAIN)
    assert all(
        node_result.status == StageState.SUCCESS
        for node_result in result.node_results.values()
    )
    assert result.graph_id == "default_inference"
    assert result.parsed_response == result.node_results["consolidate"].result
    assert len(fake.calls) == len(INFERENCE_CHAIN)
    assert sorted(path.name for path in output.iterdir()) == [
        "final_result.json",
        "state.json",
    ]
    state = json.loads((output / "state.json").read_text(encoding="utf-8"))
    assert set(state["node_states"]) == set(INFERENCE_CHAIN)
    assert state["final_result"]["status"] == "SUCCESS"
    assert state["usage"]["total_tokens"] == 16 * len(INFERENCE_CHAIN)
    assert not list(tmp_path.rglob("*.tmp"))


def test_the_chain_compares_the_outputs_of_a_node_that_declared_two_inputs(
    provider: Callable[..., FakeProvider], tmp_path: Path
) -> None:
    """``LLM-14``: the comparison pairs come from the descriptor, and disagreement is data."""
    provider()
    request = build_graph_input(tmp_path / "run_001")

    result = process_llm_request(request)

    comparison = result.comparisons["compare:extract_a~extract_b"]
    assert comparison.matches == ANSWER
    assert comparison.conflicts == {}
    assert comparison.metadata["left_node"] == "extract_a"
    assert result.metadata["node_actions"] == dict.fromkeys(INFERENCE_CHAIN, "EXECUTE")


def test_a_resumed_chain_reuses_every_valid_node_and_calls_the_provider_for_none(
    provider: Callable[..., FakeProvider], tmp_path: Path
) -> None:
    """Invariant 1: a ``SUCCESS`` node under a matching key is reused, never re-called.

    *Mutation that breaks it:* make :func:`is_node_reusable` always return ``False`` — or drop its
    ``SUCCESS`` check — and the second run below calls the provider for ``classify`` again, which
    the second double's empty call list is there to notice.
    """
    output = tmp_path / "run_001"
    provider()
    process_llm_request(build_graph_input(output))

    resumed = provider()
    second = process_llm_request(build_graph_input(output))

    assert second.status == StageState.SUCCESS
    assert resumed.calls == []
    assert second.metadata["node_actions"] == dict.fromkeys(INFERENCE_CHAIN, "REUSE")
    state = primitives.load_graph_state(output)
    assert state is not None
    assert set(state.node_states.values()) == {StageState.REUSED}
    assert all(
        node_result.status == StageState.SUCCESS
        for node_result in second.node_results.values()
    )


def test_every_node_that_reaches_the_provider_is_observed_and_a_reused_one_is_not(
    provider: Callable[..., FakeProvider], tmp_path: Path
) -> None:
    """An observer follows the chain, and stops at the nodes a resume reused.

    *Mutation that breaks it:* drop ``observer=observer`` on the way from
    :func:`execute_llm_graph` through :func:`_resolve_node` into :func:`process_llm_node` — the
    chain runs, the provider answers, and ``first_seen`` is empty. The second half is the other
    side of the same rule: a ``REUSED`` node reaches no provider, so nothing arrives to watch.
    """
    output = tmp_path / "run_001"
    first_seen: list[StreamDelta] = []
    first_fake = provider()
    first = process_llm_request(
        build_graph_input(output, options={STREAM_OPTION: True, "temperature": 0.0}),
        observer=first_seen.append,
    )

    resumed_seen: list[StreamDelta] = []
    resumed = provider()
    second = process_llm_request(
        build_graph_input(output, options={STREAM_OPTION: True, "temperature": 0.0}),
        observer=resumed_seen.append,
    )

    assert first.status == StageState.SUCCESS
    assert len(first_seen) == len(first_fake.calls) > 0
    assert second.metadata["node_actions"] == dict.fromkeys(INFERENCE_CHAIN, "REUSE")
    assert resumed.calls == []
    assert not resumed_seen
    assert second.raw_response == first.raw_response


def test_a_chain_interrupted_by_a_failed_node_resumes_without_repeating_the_valid_ones(
    provider: Callable[..., FakeProvider], tmp_path: Path
) -> None:
    """Acceptance: ``classify`` and ``extract_a`` reuse; ``extract_b`` onward runs."""
    output = tmp_path / "run_001"
    provider(answers=[None, None, failed("MODEL_UNAVAILABLE", "the model went away")])

    first = process_llm_request(build_graph_input(output))

    assert first.status == StageState.FAILED
    assert first.metadata["node_actions"] == {
        "classify": "EXECUTE",
        "extract_a": "EXECUTE",
        "extract_b": "EXECUTE",
    }
    assert first.node_results["extract_b"].status == StageState.FAILED
    assert set(first.node_results) == {"classify", "extract_a", "extract_b"}

    resumed = provider()
    second = process_llm_request(build_graph_input(output))

    assert second.status == StageState.SUCCESS
    assert second.metadata["node_actions"] == {
        "classify": "REUSE",
        "extract_a": "REUSE",
        "extract_b": "EXECUTE",
        "compare": "EXECUTE",
        "validate": "EXECUTE",
        "consolidate": "EXECUTE",
    }
    assert len(resumed.calls) == 4
    assert not second.errors


def test_a_node_that_fails_leaves_a_state_a_later_run_can_read(
    provider: Callable[..., FakeProvider], tmp_path: Path
) -> None:
    """Acceptance: the chain state stays loadable after a failure — nothing is corrupt."""
    output = tmp_path / "run_001"
    provider(answers=[None, None, failed("MODEL_UNAVAILABLE", "gone")])

    process_llm_request(build_graph_input(output))

    state = primitives.load_graph_state(output)
    assert state is not None
    assert state.node_states["extract_b"] == StageState.FAILED
    assert state.node_states["compare"] == StageState.NOT_STARTED
    assert state.errors == ["gone"]


def test_the_run_asks_the_provider_for_nothing_but_the_generation(
    provider: Callable[..., FakeProvider], tmp_path: Path
) -> None:
    """One inference, one call: the inventory primitives are reachable but never probed here."""
    fake = provider()

    process_llm_request(build_graph_input(tmp_path / "run_001"))

    assert len(fake.calls) == len(INFERENCE_CHAIN)
    assert fake.model_calls == []


def test_a_descriptor_that_cannot_be_executed_fails_the_run_by_name(
    provider: Callable[..., FakeProvider], tmp_path: Path
) -> None:
    """The deferred machinery is refused, not stubbed: a routing key fails by name."""
    fake = provider()
    request = build_graph_input(
        tmp_path / "run_001",
        graph={
            "graph_id": "g",
            "graph_version": "1",
            "nodes": [
                {"node_id": "a", "template": "simple_extract", "when": "on_failure"}
            ],
        },
    )

    result = process_llm_request(request)

    assert result.status == StageState.FAILED
    assert result.errors[0].type == "DEPENDENCY_ERROR"
    assert result.errors[0].metadata["unsupported"] == ["when"]
    assert fake.calls == []
    assert result.graph_id is None


def test_a_saved_state_that_belongs_to_another_graph_is_not_resumed(
    provider: Callable[..., FakeProvider], tmp_path: Path
) -> None:
    """Continuing it would reuse results that answered a different question."""
    output = tmp_path / "run_001"
    provider()
    process_llm_request(build_graph_input(output))

    other = default_inference_graph()
    other["graph_id"] = "another_graph"
    result = process_llm_request(build_graph_input(output, graph=other))
    assert result.status == StageState.FAILED
    assert result.errors[0].type == "DEPENDENCY_ERROR"
    assert result.errors[0].metadata["saved"] == ["default_inference", "1"]


# --- one node, standalone (LLM-10) ---------------------------------------------------------------


def test_a_node_records_its_outcome_into_the_state(
    provider: Callable[..., FakeProvider],
) -> None:
    """The node moves to ``SUCCESS``, and its key, attempts and result land in the state."""
    fake = provider()
    request = build_graph_input(None)
    state = empty_state()

    node_result = process_llm_node(
        {
            "node_id": "classify",
            "depends_on": [],
            "task": "classify",
            "template": "simple_extract",
            "schema": "simple",
            "request": request,
        },
        state,
    )

    assert node_result.status == StageState.SUCCESS
    assert node_result.request_key
    assert node_result.validation == {"status": "VALID", "retryable": False}
    assert node_result.attempts == state.attempts["classify"]
    assert state.node_results["classify"] == node_result
    assert state.node_states["classify"] == StageState.SUCCESS
    assert not state.current_nodes
    assert len(fake.calls) == 1
    assert state.final_result is None


def test_a_node_whose_provider_fails_is_a_typed_failed_result_and_not_an_exception(
    provider: Callable[..., FakeProvider],
) -> None:
    """Acceptance: the failure is reported in the node, and the state stays loadable."""
    provider(answers=[failed("MODEL_UNAVAILABLE", "gone")])
    state = empty_state()

    node_result = process_llm_node(
        {
            "node_id": "classify",
            "depends_on": [],
            "task": "classify",
            "template": "simple_extract",
            "schema": "simple",
            "request": build_graph_input(None),
        },
        state,
    )

    assert node_result.status == StageState.FAILED
    assert node_result.errors[0].type == "MODEL_UNAVAILABLE"
    assert node_result.result is None
    assert state.errors == ["gone"]
    assert primitives.validate_cached_result(node_result) is False


def test_a_node_that_cannot_be_planned_carries_no_key_and_can_never_be_reused(
    provider: Callable[..., FakeProvider],
) -> None:
    """A node that never got a key cannot be reused — which is what an empty key states."""
    provider()
    state = empty_state()

    node_result = process_llm_node(
        {
            "node_id": "classify",
            "depends_on": [],
            "task": "classify",
            "template": "no_such_template",
            "schema": "simple",
            "request": build_graph_input(None),
        },
        state,
    )

    assert node_result.status == StageState.FAILED
    assert node_result.request_key == ""
    assert node_result.errors[0].type == "DEPENDENCY_ERROR"
    assert primitives.validate_cached_result(node_result) is False


def test_execute_llm_graph_is_the_same_run_as_a_request_carrying_a_descriptor(
    provider: Callable[..., FakeProvider], tmp_path: Path
) -> None:
    """The named entry point and the descriptor path are one implementation, not two."""
    provider()
    request = build_graph_input(tmp_path / "run_001")

    direct = execute_llm_graph(request)
    through_the_entry_point = process_llm_request(request)

    assert direct.graph_id == through_the_entry_point.graph_id
    assert set(direct.node_results) == set(through_the_entry_point.node_results)
    assert direct.parsed_response == through_the_entry_point.parsed_response
