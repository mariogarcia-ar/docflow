"""Tests for the engine-independent composition (``LLM-04``, ``LLM-05``, ``LLM-07``, ``LLM-14``,
``LLM-15``).

Nothing here needs a provider: the inputs are values this processor produces, and every assertion
is about rendering, keying, parsing, comparing or measuring.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

import pytest

from docflow.llm.contracts import (
    ComparisonResult,
    LLMGraphState,
    LLMNodeResult,
    Timing,
    Usage,
)
from docflow.llm.primitives import LLMPrimitiveError
from docflow.llm.primitives.composition import (
    CHAIN_DEPENDENCIES,
    DEFAULT_MAX_ATTEMPTS,
    INFERENCE_CHAIN,
    assets_dir_for,
    attempt_validation_state,
    build_inference_plan,
    build_messages,
    calculate_request_key,
    compare_outputs,
    context_verdict,
    count_tokens,
    default_inference_graph,
    find_reusable_node_result,
    image_tokens_for,
    increment_attempt,
    input_hashes,
    is_context_limit_exceeded,
    is_node_reusable,
    max_attempts,
    merge_timing,
    merge_usage,
    mint_attempt_id,
    normalize_llm_options,
    output_dir_for,
    parse_json_response,
    pinned_run_id,
    process_prompt,
    process_template,
    request_timeout,
    resolve_generator,
    sanitize_text,
    schema_digest,
    should_retry,
    stated_context_window,
    stated_model_version,
    truncate_to_token_limit,
    typed_failure,
    validate_cached_result,
)
from docflow.states import StageState
from tests.llm.samples import ANSWER, build_input

TEMPLATE = "doc=<doc>\nextra=<extra>\nschema=<schema>\n"


# --- rendering (LLM-04) ------------------------------------------------------------------------


def test_every_placeholder_is_resolved_and_none_is_left_behind() -> None:
    """Acceptance: the rendered prompt holds the document and the schema, and no placeholder."""
    rendered = process_template(
        TEMPLATE,
        document="a body",
        extra_context={"source": "native_text"},
        schema={"type": "object"},
    )

    assert "a body" in rendered
    assert '{"source":"native_text"}' in rendered
    assert '{"type":"object"}' in rendered
    for placeholder in ("<doc>", "<extra>", "<schema>"):
        assert placeholder not in rendered


def test_a_template_asking_for_a_document_the_request_does_not_carry_is_refused() -> (
    None
):
    """Substituting an empty string would send a model a document that reads as empty."""
    with pytest.raises(LLMPrimitiveError) as raised:
        process_template("<doc>", document=None, extra_context={}, schema=None)

    assert raised.value.error.type == "DEPENDENCY_ERROR"
    assert raised.value.error.metadata["placeholder"] == "<doc>"


def test_a_template_asking_for_a_schema_the_request_does_not_name_is_refused() -> None:
    """The same rule as the document: an absent input is reported, never rendered as nothing."""
    with pytest.raises(LLMPrimitiveError) as raised:
        process_template("<schema>", document="a body", extra_context={}, schema=None)

    assert raised.value.error.metadata["placeholder"] == "<schema>"


def test_a_template_that_does_not_use_a_placeholder_does_not_need_that_input() -> None:
    """A prompt with no ``<doc>`` is a legitimate prompt; only a *used* placeholder is required."""
    assert (
        process_template("plain", document=None, extra_context={}, schema=None)
        == "plain"
    )


def test_named_extra_placeholders_give_each_input_its_own_section() -> None:
    """Two inputs, two sections: neither placeholder renders the other's value."""
    rendered = process_template(
        "read=<extra:reading>\nreviewed=<extra:review>\n",
        document=None,
        extra_context={"reading": {"total": "10"}, "review": "disagree"},
        schema=None,
    )

    assert rendered == 'read={"total":"10"}\nreviewed=disagree\n'


def test_a_named_extra_placeholder_the_request_cannot_fill_is_refused() -> None:
    """The rule is the document's rule: an absent key is reported, never rendered as nothing."""
    with pytest.raises(LLMPrimitiveError) as raised:
        process_template(
            "<extra:proposal>", document=None, extra_context={}, schema=None
        )

    assert raised.value.error.type == "DEPENDENCY_ERROR"
    assert raised.value.error.metadata["placeholder"] == "<extra:proposal>"
    assert raised.value.error.metadata["key"] == "proposal"


def test_a_string_extra_value_is_inserted_verbatim_and_anything_else_as_canonical_json() -> (
    None
):
    """An ``extra_context`` value that is already text is not quoted on the way into the prompt."""
    rendered = process_template(
        "rubro=<extra:rubro> proposal=<extra:proposal>",
        document=None,
        extra_context={"rubro": "Restaurante", "proposal": {"total": "10"}},
        schema=None,
    )

    assert rendered == 'rubro=Restaurante proposal={"total":"10"}'


def test_text_that_arrives_from_the_request_is_never_scanned_for_placeholders() -> None:
    """A receipt that prints ``<extra>`` prints it; resolution does not run over inserted text."""
    rendered = process_template(
        "<doc>|<extra:proposal>",
        document="total <extra> 10 and <doc> again",
        extra_context={"proposal": "fine"},
        schema=None,
    )

    assert rendered == "total <extra> 10 and <doc> again|fine"


def test_the_same_inputs_render_the_same_prompt_twice() -> None:
    """Acceptance: the rendered prompt is byte-identical across two renders."""
    request = build_input()

    first = process_prompt(request, TEMPLATE, {"type": "object"})
    second = process_prompt(request, TEMPLATE, {"type": "object"})

    assert first.text == second.text
    assert first.tokens == second.tokens


def test_a_carriage_return_never_reaches_the_prompt_but_a_newline_does() -> None:
    """Two spellings of one document must be one prompt; NUL bytes are removed, not counted."""
    assert sanitize_text("a\r\nb\rc\x00d") == "a\nb\ncd"


def test_truncation_happens_only_when_a_limit_was_stated_and_is_recorded() -> None:
    """Acceptance: truncation is explicit and recorded, never a quiet shortening."""
    request = build_input(options={"max_prompt_tokens": 5}, document="x" * 400)

    measured = process_prompt(request, "<doc>", None)
    untruncated = process_prompt(build_input(document="x" * 400), "<doc>", None)

    assert measured.truncated is True
    assert measured.tokens <= 5
    assert untruncated.truncated is False
    assert untruncated.tokens > 5


def test_messages_carry_the_rendered_prompt_as_one_user_turn() -> None:
    """The template is the instruction; a second system turn would be a second place for it."""
    assert build_messages("hello") == [{"role": "user", "content": "hello"}]


# --- measurement (LLM-15) ---------------------------------------------------------------------


def test_the_token_count_is_an_estimate_and_says_so() -> None:
    """An approximate count that is labelled beats a fabricated exact one."""
    assert count_tokens("x" * 400) == 100
    assert count_tokens("") == 0


def test_a_truncated_prompt_fits_the_limit_it_was_given() -> None:
    """The prefix that fits is returned, and a limit of nothing leaves nothing."""
    assert count_tokens(truncate_to_token_limit("x" * 400, 10)) <= 10
    assert truncate_to_token_limit("x" * 400, 0) == ""
    assert truncate_to_token_limit("short", 100) == "short"


def test_an_unknown_window_is_not_an_overflow() -> None:
    """An unmeasured ceiling is not evidence, and claiming one would refuse a call that works."""
    assert is_context_limit_exceeded(10_000, None) is False
    assert is_context_limit_exceeded(10_001, 10_000) is True
    assert is_context_limit_exceeded(10_000, 10_000) is False


def test_a_cost_nobody_measured_is_never_reported_as_fitting() -> None:
    """``fits`` is claimed only when the total *and* the window are known.

    An image costs a model thousands of prompt tokens no text measurement sees, so a request that
    carries one whose cost the caller never stated is ``unmeasured`` against a stated window — and
    still ``exceeds`` when the text alone is over, because that much is known.
    """
    assert context_verdict(615, 4096, image_count=1, image_tokens=None) == "unmeasured"
    assert context_verdict(615, None, image_count=1, image_tokens=None) == "unmeasured"
    assert context_verdict(10_000, 4096, image_count=1, image_tokens=None) == "exceeds"
    assert context_verdict(615, 4096) == "fits"
    assert context_verdict(615, None) == "unmeasured"


def test_a_stated_image_cost_is_added_to_the_text_it_measures() -> None:
    """The comparison uses every number anyone knows: text plus one cost per image."""
    assert context_verdict(615, 4096, image_count=1, image_tokens=2800) == "fits"
    assert context_verdict(615, 4096, image_count=2, image_tokens=2800) == "exceeds"
    assert context_verdict(615, 4096, image_count=1, image_tokens=4000) == "exceeds"


def test_only_a_positive_integer_prices_an_image() -> None:
    """A cost nobody stated is not stated — and a malformed one is not a zero either."""
    assert image_tokens_for(build_input(metadata={"image_tokens": 2800})) == 2800
    assert image_tokens_for(build_input()) is None
    for unstated in (None, 0, -1, True, "2800"):
        assert (
            image_tokens_for(build_input(metadata={"image_tokens": unstated})) is None
        )


def test_usage_adds_up_and_stays_unmeasured_when_nothing_was_measured() -> None:
    """A figure no record reported is ``None``, never a zero that reads as a measurement."""
    measured = Usage(10, 2, 12, None, {"a": 1}, None)
    other = Usage(5, 1, 6, 3, {"b": 2}, 0.25)

    total = merge_usage([measured, other])

    assert (total.input_tokens, total.output_tokens, total.total_tokens) == (15, 3, 18)
    assert total.cached_tokens == 3
    assert total.estimated_cost == 0.25
    assert total.provider_usage == {"a": 1, "b": 2}
    assert merge_usage([Usage(None, None, None, None, {}, None)]).total_tokens is None


def test_timing_adds_up_and_keeps_an_unmeasured_figure_unmeasured() -> None:
    """``total_time`` is always a measurement; the three finer figures may be unknown."""
    total = merge_timing([Timing(None, 0.1, 0.2, 0.5), Timing(None, None, None, 0.25)])

    assert total.load_time == 0.1
    assert total.inference_time == 0.2
    assert total.total_time == 0.75
    assert merge_timing([]).load_time is None


# --- the request key (LLM-05) ------------------------------------------------------------------


def key_for(**overrides: Any) -> str:
    """Return a request key over a baseline set of components, with any of them overridden."""
    components: dict[str, Any] = {
        "provider": "ollama",
        "model": "test-model",
        "model_version": "v1",
        "rendered_prompt": "prompt",
        "hashes": {"document": "abc", "images": []},
        "schema_hash": "def",
        "options": {"temperature": 0.0},
    }
    return calculate_request_key(**{**components, **overrides})


def test_the_same_logical_request_always_keys_the_same() -> None:
    """Acceptance: identical inputs, identical key."""
    assert key_for() == key_for()


@pytest.mark.parametrize(
    ("field", "changed"),
    [
        ("provider", "openai_compatible"),
        ("model", "another-model"),
        ("model_version", "v2"),
        ("rendered_prompt", "another prompt"),
        ("hashes", {"document": "abc", "images": ["x"]}),
        ("schema_hash", None),
        ("options", {"temperature": 0.5}),
    ],
)
def test_any_change_to_the_logical_request_changes_the_key(
    field: str, changed: Any
) -> None:
    """Every component of the documented formula is load-bearing, including a removed one."""
    assert key_for(**{field: changed}) != key_for()


def test_the_key_function_cannot_see_a_run_identity() -> None:
    """The exclusions are structural: the formula has no parameter for what must not enter it."""
    parameters = set(inspect.signature(calculate_request_key).parameters)

    assert parameters == {
        "provider",
        "model",
        "model_version",
        "rendered_prompt",
        "hashes",
        "schema_hash",
        "options",
    }


def test_a_schema_is_keyed_by_its_content_rather_than_its_identifier() -> None:
    """Renaming an identical schema does not change the key; editing it does."""
    first = schema_digest({"type": "object", "required": ["a"]})
    second = schema_digest({"required": ["a"], "type": "object"})
    third = schema_digest({"type": "object", "required": ["b"]})

    assert first == second
    assert first != third
    assert schema_digest(None) is None


def test_inputs_are_hashed_by_content_and_an_absent_document_is_not_an_empty_one() -> (
    None
):
    """``None`` and ``""`` are different inputs and must not hash alike."""
    assert input_hashes(None, [])["document"] is None
    assert input_hashes("", [])["document"] is not None
    assert input_hashes("a", []) == input_hashes("a", [])
    assert input_hashes("a", []) != input_hashes("b", [])


def test_an_image_that_cannot_be_read_is_a_missing_dependency(tmp_path: Path) -> None:
    """An input the request names but the run cannot open does not resolve."""
    with pytest.raises(LLMPrimitiveError) as raised:
        input_hashes("a", [tmp_path / "gone.png"])

    assert raised.value.error.type == "DEPENDENCY_ERROR"


# --- options, policy and the request's own metadata ---------------------------------------------


def test_the_credential_is_never_part_of_normalized_options() -> None:
    """A key is persisted in an artifact; an API key must not be in one."""
    normalized = normalize_llm_options({"api_key": "secret-token", "temperature": 0.1})

    assert normalized == {"temperature": 0.1}
    assert "secret-token" not in str(normalized)


def test_the_attempt_policy_is_one_retry_unless_the_request_states_another() -> None:
    """The policy is recorded where it can be seen, and a stated one wins."""
    assert max_attempts({}) == DEFAULT_MAX_ATTEMPTS
    assert max_attempts({"max_attempts": 3}) == 3
    assert max_attempts({"max_attempts": 0}) == DEFAULT_MAX_ATTEMPTS
    assert max_attempts({"max_attempts": "three"}) == DEFAULT_MAX_ATTEMPTS


def test_the_timeout_is_documented_unless_the_request_states_one() -> None:
    """A hidden default timeout is a decision; a recorded one is a policy."""
    assert request_timeout({}) == request_timeout({})
    assert request_timeout({"timeout": 3}) == 3.0
    assert request_timeout({"timeout": -1}) == request_timeout({})


def test_a_retry_needs_a_retryable_failure_and_a_policy_that_allows_it() -> None:
    """Either half missing means no second paid call."""
    assert should_retry(retryable=True, attempt_index=1, attempt_limit=2) is True
    assert should_retry(retryable=False, attempt_index=1, attempt_limit=2) is False
    assert should_retry(retryable=True, attempt_index=2, attempt_limit=2) is False
    assert increment_attempt(1) == 2


def test_attempt_identifiers_differ_per_attempt_and_are_reproducible() -> None:
    """Acceptance: two attempts of one call never share an identifier."""
    assert mint_attempt_id("classify", 1) != mint_attempt_id("classify", 2)
    assert mint_attempt_id(None, 1) == "call-attempt-001"
    assert mint_attempt_id("classify", 2) == "classify-attempt-002"


def test_a_verdict_is_derived_from_the_typed_failure() -> None:
    """The verdict and the classification cannot disagree: one is computed from the other."""
    assert attempt_validation_state(None) == "VALID"
    assert attempt_validation_state(typed("TIMEOUT").error) == "RETRYABLE"
    assert attempt_validation_state(typed("MODEL_UNAVAILABLE").error) == "INVALID"


def typed(kind: str):
    """Return a typed failure of ``kind``, for the classification cases."""
    return typed_failure(kind, "x")  # type: ignore[arg-type]


# --- parsing and comparison (LLM-07, LLM-14) ----------------------------------------------------


def test_an_answer_is_parsed_as_it_arrives() -> None:
    """The plain case."""
    assert parse_json_response('{"a": 1}') == {"a": 1}


def test_an_answer_wrapped_in_one_fence_is_unwrapped() -> None:
    """Models habitually fence JSON; unwrapping one fence is a documented tolerance."""
    assert parse_json_response('```json\n{"a": 1}\n```') == {"a": 1}


def test_an_answer_that_is_not_json_is_reported_with_the_text_that_arrived() -> None:
    """Acceptance: invalid JSON is typed, and the raw answer travels with it for diagnosis."""
    with pytest.raises(LLMPrimitiveError) as raised:
        parse_json_response("not json at all")

    assert raised.value.error.type == "INVALID_JSON"
    assert raised.value.error.metadata["response"] == "not json at all"


def test_two_agreeing_outputs_are_reported_field_by_field() -> None:
    """Acceptance: agreement is still per-field evidence, never an aggregate score."""
    comparison = compare(ANSWER, dict(ANSWER))

    assert comparison.matches == ANSWER
    assert not comparison.conflicts
    assert all(value == 1.0 for value in comparison.agreement.values())
    assert "confidence" not in comparison.metadata


def test_two_differing_outputs_enumerate_every_field_that_differs() -> None:
    """Acceptance: disagreement is data, and this function picks no winner."""
    comparison = compare(ANSWER, {**ANSWER, "page_count": 4})

    assert comparison.matches["summary"] == ANSWER["summary"]
    assert comparison.conflicts["page_count"] == {"left": 3, "right": 4}
    assert comparison.agreement["page_count"] == 0.0
    assert comparison.agreement["summary"] == 1.0


def test_a_field_only_one_side_reported_is_a_conflict_and_not_a_match() -> None:
    """A field one output omitted is a disagreement about what the document says."""
    comparison = compare({"a": 1, "b": 2}, {"a": 1})

    assert set(comparison.matches) == {"a"}
    assert comparison.conflicts["b"] == {"left": 2, "right": None}


def test_an_output_that_is_not_a_mapping_is_compared_as_one_value() -> None:
    """A scalar answer is still compared; it is simply one field deep."""
    comparison = compare("left", "right")

    assert comparison.conflicts == {"value": {"left": "left", "right": "right"}}


def compare(left: Any, right: Any) -> ComparisonResult:
    """Return a comparison of two outputs, for the cases above."""
    return compare_outputs(left, right, left_node="extract_a", right_node="extract_b")


# --- the reuse rule (LLM-05) --------------------------------------------------------------------


def node_result(**overrides: Any) -> LLMNodeResult:
    """Return a reusable node result, with any field overridden for the case under test."""
    fields: dict[str, Any] = {
        "node_id": "classify",
        "request_key": "key-1",
        "status": StageState.SUCCESS,
        "result": {"summary": "s"},
        "attempts": [],
        "validation": {"status": "VALID", "retryable": False},
        "errors": [],
        "usage": Usage(None, None, None, None, {}, None),
        "timing": Timing(None, None, None, 0.1),
        "metadata": {},
    }
    return LLMNodeResult(**{**fields, **overrides})


def test_a_valid_success_under_the_same_key_is_reusable() -> None:
    """Acceptance: the three lines of the reuse rule, all true."""
    assert validate_cached_result(node_result()) is True
    assert is_node_reusable(node_result(), "key-1") is True


@pytest.mark.parametrize(
    "broken",
    [
        {"status": StageState.FAILED},
        {"request_key": ""},
        {"result": None},
        {"validation": {"status": "INVALID", "retryable": False}},
    ],
)
def test_anything_less_than_a_valid_success_is_not_reusable(
    broken: dict[str, Any],
) -> None:
    """A node that failed, named no key, carries no result or is invalid has to run."""
    assert validate_cached_result(node_result(**broken)) is False
    assert is_node_reusable(node_result(**broken), "key-1") is False


def test_a_matching_key_under_a_different_request_is_not_reusable() -> None:
    """Acceptance: a mismatched key means the logical request changed."""
    assert is_node_reusable(node_result(), "another-key") is False


def test_no_persisted_result_means_no_reuse() -> None:
    """The absence of a result is not a result."""
    assert validate_cached_result(None) is False
    assert is_node_reusable(None, "key-1") is False


def test_a_result_is_found_in_the_state_only_when_it_may_be_reused() -> None:
    """The lookup applies the whole rule, so a caller cannot forget half of it."""
    state = graph_state(node_results={"classify": node_result()})

    assert find_reusable_node_result(state, "classify", "key-1") is not None
    assert find_reusable_node_result(state, "classify", "other") is None
    assert find_reusable_node_result(state, "elsewhere", "key-1") is None


def graph_state(**overrides: Any) -> LLMGraphState:
    """Return an empty chain state, with any field overridden for the case under test."""
    fields: dict[str, Any] = {
        "run_id": "run-1",
        "graph_id": "default_inference",
        "graph_version": "1",
        "status": StageState.NOT_STARTED,
        "current_nodes": [],
        "node_states": {},
        "node_results": {},
        "attempts": {},
        "comparisons": {},
        "errors": [],
        "usage": Usage(None, None, None, None, {}, None),
        "stop_requested": False,
        "final_result": None,
    }
    return LLMGraphState(**{**fields, **overrides})


# --- the descriptor (LLM-12's shape) ------------------------------------------------------------


def test_the_documented_chain_compiles_to_its_documented_order() -> None:
    """The default descriptor is the subplan's chain, and the order is the order it must run in."""
    plan = build_inference_plan(default_inference_graph())

    assert plan.node_ids == INFERENCE_CHAIN
    assert plan.graph_id == "default_inference"
    for node in plan.nodes:
        assert node.depends_on == CHAIN_DEPENDENCIES[node.node_id]


def test_a_node_that_depends_on_something_that_does_not_precede_it_is_refused() -> None:
    """Executing it would ask a node to read a result that cannot exist yet."""
    descriptor = {
        "graph_id": "g",
        "graph_version": "1",
        "nodes": [
            {"node_id": "second", "template": "t", "depends_on": ["first"]},
            {"node_id": "first", "template": "t"},
        ],
    }

    with pytest.raises(LLMPrimitiveError) as raised:
        build_inference_plan(descriptor)

    assert raised.value.error.type == "DEPENDENCY_ERROR"
    assert raised.value.error.metadata["unresolved"] == ["first"]


def test_a_descriptor_that_declares_the_same_node_twice_is_refused() -> None:
    """Two nodes with one name cannot both be recorded under it."""
    descriptor = {
        "graph_id": "g",
        "graph_version": "1",
        "nodes": [
            {"node_id": "a", "template": "t"},
            {"node_id": "a", "template": "t"},
        ],
    }

    with pytest.raises(LLMPrimitiveError) as raised:
        build_inference_plan(descriptor)

    assert "twice" in raised.value.error.message


@pytest.mark.parametrize(
    "descriptor",
    [
        None,
        {"graph_version": "1", "nodes": [{"node_id": "a", "template": "t"}]},
        {"graph_id": "g", "nodes": [{"node_id": "a", "template": "t"}]},
        {"graph_id": "g", "graph_version": "1", "nodes": []},
        {"graph_id": "g", "graph_version": "1", "nodes": [{"node_id": "a"}]},
        {"graph_id": "g", "graph_version": "1", "nodes": ["a"]},
        {
            "graph_id": "g",
            "graph_version": "1",
            "nodes": [{"node_id": "a", "template": "t", "depends_on": "b"}],
        },
    ],
)
def test_a_descriptor_that_cannot_be_executed_is_refused_rather_than_guessed_at(
    descriptor: Any,
) -> None:
    """Every missing piece is named by the field it is missing, and none is defaulted."""
    with pytest.raises(LLMPrimitiveError) as raised:
        build_inference_plan(descriptor)

    assert raised.value.error.type == "DEPENDENCY_ERROR"


def test_a_prefix_of_the_chain_is_a_valid_descriptor() -> None:
    """The shape is data: a caller may declare fewer nodes, in dependency order."""
    descriptor = {
        "graph_id": "short",
        "graph_version": "2",
        "nodes": [
            {"node_id": "classify", "template": "simple_extract", "task": "classify"},
            {
                "node_id": "extract_a",
                "template": "simple_extract",
                "task": "extract_a",
                "depends_on": ["classify"],
            },
        ],
    }

    plan = build_inference_plan(descriptor)

    assert plan.node_ids == ("classify", "extract_a")


def test_the_generator_a_call_resolves_to_is_stated() -> None:
    """A schema means structure, images mean vision, and neither means plain text."""
    assert resolve_generator(structured=True, multimodal=True) == "generate_structured"
    assert resolve_generator(structured=False, multimodal=True) == "generate_multimodal"
    assert resolve_generator(structured=False, multimodal=False) == "generate_text"


# --- the request's own metadata -----------------------------------------------------------------


def test_the_asset_root_and_the_run_namespace_come_from_the_request_or_not_at_all() -> (
    None
):
    """There is no default for either: a guessed place is a request that means two things."""
    stated = build_input(output_dir=Path("/tmp/llm-run"))

    assert assets_dir_for(stated).name == "llm"
    assert output_dir_for(stated) == Path("/tmp/llm-run")
    assert output_dir_for(build_input()) is None
    assert pinned_run_id(build_input(run_id="pinned")) == "pinned"
    assert pinned_run_id(build_input()) is None
    assert stated_model_version(build_input(metadata={"model_version": "v9"})) == "v9"
    assert stated_model_version(build_input()) is None
    assert stated_context_window(build_input(options={"context_window": 8192})) == 8192

    with pytest.raises(LLMPrimitiveError) as raised:
        assets_dir_for(build_input(assets=None))

    assert raised.value.error.type == "DEPENDENCY_ERROR"
    assert raised.value.error.metadata["metadata_key"] == "assets_dir"
