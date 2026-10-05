"""Tests for the request check, the asset loaders and the schema verdict (``LLM-07``).

Nothing here reaches a provider: the assets are the committed fixtures, the answers are literals,
and every assertion is about what this processor says about them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from docflow.llm.contracts import LLMResult, Timing, Usage
from docflow.llm.primitives import LLMPrimitiveError
from docflow.llm.primitives.validation import (
    SUPPORTED_KEYWORDS,
    load_schema,
    load_template,
    validate_llm_input,
    validate_llm_result,
    validate_schema,
)
from docflow.states import StageState
from tests.factories import build_llm_input
from tests.llm.samples import ANSWER, ASSETS, build_input, build_result


def test_a_request_that_names_no_provider_is_refused_by_name() -> None:
    """There is no default provider, so an unnamed one is a failure rather than a guess."""
    with pytest.raises(LLMPrimitiveError) as raised:
        validate_llm_input(build_input(provider=""))

    assert raised.value.error.type == "DEPENDENCY_ERROR"
    assert raised.value.error.metadata["missing"] == ["provider"]


def test_a_request_that_names_no_model_or_template_lists_everything_missing() -> None:
    """One failure report names all of it, so a caller fixes the request once."""
    with pytest.raises(LLMPrimitiveError) as raised:
        validate_llm_input(build_input(model="   ", template=""))

    assert raised.value.error.metadata["missing"] == ["model", "template"]


def test_the_committed_template_loads_verbatim() -> None:
    """The asset is resolved through the declared root and read as it is."""
    template = load_template("simple_extract", ASSETS)

    assert "<doc>" in template
    assert "<extra>" in template
    assert "<schema>" in template


def test_a_template_that_does_not_resolve_is_a_missing_dependency() -> None:
    """A named template that is not there is a dependency, not an empty prompt."""
    with pytest.raises(LLMPrimitiveError) as raised:
        load_template("no_such_template", ASSETS)

    assert raised.value.error.type == "DEPENDENCY_ERROR"
    assert raised.value.error.recoverable is False


def test_no_schema_means_no_schema() -> None:
    """A request that names none gets ``None`` — not an empty schema standing in."""
    assert load_schema(None, ASSETS) is None


def test_the_committed_schema_loads_as_a_document() -> None:
    """The schema fixture exercises required fields, types and closed properties."""
    schema = load_schema("simple", ASSETS)

    assert schema is not None
    assert schema["required"] == ["summary", "topics"]
    assert schema["additionalProperties"] is False


def test_a_schema_using_a_keyword_this_processor_does_not_enforce_is_refused(
    tmp_path: Path,
) -> None:
    """A validator that ignored a rule would report valid an answer it never checked."""
    (tmp_path / "schema").mkdir()
    patterned = (
        '{"type": "object", "properties": {"a": {"type": "string", "pattern": "^a+$"}}}'
    )
    (tmp_path / "schema" / "patterned.schema.json").write_text(
        patterned, encoding="utf-8"
    )

    with pytest.raises(LLMPrimitiveError) as raised:
        load_schema("patterned", tmp_path)

    assert raised.value.error.type == "SCHEMA_ERROR"
    assert raised.value.error.metadata["unsupported"] == ["pattern"]


def test_a_schema_that_is_not_json_is_reported(tmp_path: Path) -> None:
    """A malformed asset cannot validate anything, so it is refused before any call."""
    (tmp_path / "schema").mkdir()
    (tmp_path / "schema" / "broken.schema.json").write_text("{", encoding="utf-8")

    with pytest.raises(LLMPrimitiveError) as raised:
        load_schema("broken", tmp_path)

    assert raised.value.error.type == "SCHEMA_ERROR"


def test_the_enforced_subset_is_the_one_the_module_documents() -> None:
    """The annotations carry no rule; the seven that do are the ones a violation can come from."""
    assert "pattern" not in SUPPORTED_KEYWORDS
    assert {
        "type",
        "required",
        "properties",
        "additionalProperties",
        "items",
        "enum",
        "minItems",
        "title",
        "description",
        "default",
    } == SUPPORTED_KEYWORDS


def simple_schema() -> dict[str, Any]:
    """Return the committed schema, loaded through the asset root."""
    schema = load_schema("simple", ASSETS)
    assert schema is not None
    return schema


def test_a_valid_answer_satisfies_the_schema() -> None:
    """The happy path's own answer is the one the fixture accepts."""
    assert not validate_schema(ANSWER, simple_schema())


def test_a_missing_required_field_is_named_by_path() -> None:
    """Acceptance: ``validation_errors`` names the missing field, not just "invalid"."""
    violations = validate_schema({"topics": ["region"]}, simple_schema())

    assert violations == ["$: required property 'summary' is missing"]


def test_a_wrong_type_is_named_with_what_was_expected_and_what_arrived() -> None:
    """A verdict a reader cannot act on is not a verdict."""
    violations = validate_schema(
        {"summary": "s", "topics": "not-a-list"}, simple_schema()
    )

    assert violations == ["$.topics: expected array, got string"]


def test_an_extra_property_is_reported_when_the_schema_closes_the_object() -> None:
    """Acceptance: an unexpected field is never silently accepted."""
    violations = validate_schema(
        {"summary": "s", "topics": [], "extra": 1}, simple_schema()
    )

    assert violations == ["$: property 'extra' is not allowed by the schema"]


def test_the_items_schema_is_enforced_element_by_element() -> None:
    """A list of the wrong element type is wrong, and the message says which element."""
    violations = validate_schema({"summary": "s", "topics": ["ok", 7]}, simple_schema())

    assert violations == ["$.topics[1]: expected string, got integer"]


def test_an_enum_is_enforced_when_a_schema_states_one() -> None:
    """The subset includes ``enum``, so it is applied rather than merely accepted."""
    schema = {"type": "string", "enum": ["a", "b"]}

    assert not validate_schema("a", schema)
    assert validate_schema("c", schema) == ["$: 'c' is not one of ['a', 'b']"]


def test_a_minimum_item_count_is_enforced_when_a_schema_states_one() -> None:
    """A closed vocabulary is not a complete answer: the count is checked too.

    A review enumerates the field names it adjudicates *and* how many verdicts it owes. With
    ``minItems`` unenforced, an answer that dropped five of seven verdicts was valid against its
    schema — measured on a real model, and the reason the keyword is in the enforced subset.
    """
    schema = {
        "type": "object",
        "properties": {
            "verdicts": {"type": "array", "minItems": 3, "items": {"type": "string"}}
        },
        "required": ["verdicts"],
    }

    assert not validate_schema({"verdicts": ["a", "b", "c"]}, schema)
    assert validate_schema({"verdicts": ["a", "b"]}, schema) == [
        "$.verdicts: expected at least 3 items, got 2"
    ]


def finished_result(**overrides: Any) -> LLMResult:
    """Return a consistent result, with any field overridden for the case under test."""
    return build_result(
        build_llm_input(),
        raw_response='{"summary": "s"}',
        parsed_response={"summary": "s"},
        usage=Usage(None, None, None, None, {}, None),
        timing=Timing(None, None, None, 0.1),
        **overrides,
    )


def test_a_success_that_recorded_no_attempt_is_a_contradiction() -> None:
    """A result that names no attempt read as an answer nothing produced."""
    with pytest.raises(LLMPrimitiveError) as raised:
        validate_llm_result(finished_result())

    assert raised.value.error.metadata["contradictions"] == [
        "a successful run recorded no attempt"
    ]


def test_a_failed_result_without_a_typed_error_is_a_contradiction() -> None:
    """A failure is a classification; a bare status is not one."""
    with pytest.raises(LLMPrimitiveError):
        validate_llm_result(
            finished_result(status=StageState.FAILED, schema_valid=True)
        )


def test_a_valid_verdict_that_carries_violations_is_a_contradiction() -> None:
    """The verdict and the violations have to agree, or neither can be trusted."""
    with pytest.raises(LLMPrimitiveError):
        validate_llm_result(finished_result(validation_errors=["something"]))
