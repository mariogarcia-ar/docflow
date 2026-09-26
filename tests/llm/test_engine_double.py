"""The provider double's compliance with the engine-double convention (``LLM-03``).

The suite never reaches a provider: the double is installed at the seven primitives inside the seam,
and it answers with the provider's own shapes (`README.md` §9.7). The attribute check of
``tests/fakes/engines/convention.py`` deliberately does not apply here — the LLM seam replaces
symbols of ours rather than an engine namespace — so what keeps this double honest is the set of
checks below: the native shape, the scripted sequence, the call counter, and the rule that no test
of this processor imports a client library.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import tests.llm
from docflow.llm.primitives import (
    PRIMITIVE_NAMES,
    LLMPrimitiveError,
    ModelQuery,
    ProviderCall,
    typed_failure,
)
from tests.fakes.engines.fake_provider import (
    DEFAULT_CONTENT,
    FAKE_CONTEXT_WINDOW,
    FAKE_MODEL_VERSION,
    FAKE_MODELS,
    FakeProvider,
    invalid_json,
)
from tests.llm.samples import ANSWER
from tests.support import imported_modules

#: The client libraries no test of this processor may import: the seam resolves them lazily, and a
#: suite that imported one would stop proving that.
CLIENT_LIBRARIES = ("httpx", "openai", "ollama", "anthropic")


def call(provider: str = "ollama") -> ProviderCall:
    """Return a provider call, for the shapes below."""
    return ProviderCall(
        provider=provider,
        base_url=None,
        api_key=None,
        model="test-model",
        messages=[{"role": "user", "content": "a prompt"}],
        images=[],
        options={},
        schema=None,
        timeout=5.0,
    )


def query(model: str = "test-model") -> ModelQuery:
    """Return a model query, for the inventory cases below."""
    return ModelQuery(
        provider="ollama", model=model, base_url=None, api_key=None, timeout=5.0
    )


def test_the_double_exposes_every_primitive_the_seam_defines() -> None:
    """A double that modelled six of seven would leave one primitive untested and unnoticed."""
    fake = FakeProvider()

    assert {name for name in PRIMITIVE_NAMES if hasattr(fake, name)} == set(
        PRIMITIVE_NAMES
    )


def test_an_ollama_answer_is_the_providers_own_body_and_not_one_of_our_types() -> None:
    """A fake that returned an ``LLMResult`` would delete the translation it exists to exercise."""
    body = FakeProvider().generate_structured(call())

    assert body["message"]["content"] == DEFAULT_CONTENT
    assert body["prompt_eval_count"] == 12
    assert body["eval_count"] == 4
    assert not hasattr(body, "usage")
    assert json.loads(body["message"]["content"]) == ANSWER


def test_an_openai_compatible_answer_uses_that_dialects_field_names() -> None:
    """The two providers differ in their wire shape, and the double models each one."""
    body = FakeProvider().generate_text(call("openai"))

    assert body["choices"][0]["message"]["content"] == DEFAULT_CONTENT
    assert body["usage"] == {
        "prompt_tokens": 12,
        "completion_tokens": 4,
        "total_tokens": 16,
    }


def test_the_double_is_deterministic_and_records_every_call_it_was_asked_for() -> None:
    """Acceptance: the same input gets the same answer, and the counter increments."""
    fake = FakeProvider()

    first = fake.generate_text(call())
    second = fake.generate_text(call())

    assert first == second
    assert len(fake.calls) == 2
    assert fake.calls[0].messages[0]["content"] == "a prompt"
    assert not fake.model_calls


def test_a_scripted_sequence_reproduces_a_failure_then_a_success() -> None:
    """Acceptance: LLM-08's retry path is scriptable, which is why this fake is not canned."""
    fake = FakeProvider(answers=[invalid_json(), None])

    first = fake.generate_text(call())
    second = fake.generate_text(call())

    assert first["message"]["content"] == "not json at all"
    with pytest.raises(json.JSONDecodeError):
        json.loads(first["message"]["content"])
    assert json.loads(second["message"]["content"]) == ANSWER
    assert len(fake.calls) == 2


def test_a_scripted_typed_failure_is_raised_exactly_as_the_seam_would_raise_it() -> (
    None
):
    """The double replaces the seam, so the failure it scripts is the seam's typed failure."""
    fake = FakeProvider(answers=[typed_failure("TIMEOUT", "too slow")])

    with pytest.raises(LLMPrimitiveError) as raised:
        fake.generate_structured(call())

    assert raised.value.error.type == "TIMEOUT"


def test_a_callable_answer_lets_a_case_script_per_call() -> None:
    """A sequence is not always enough: a case may want the answer to depend on the request."""
    fake = FakeProvider(
        answers=[lambda provider_call: f'{{"seen": "{provider_call.model}"}}']
    )

    body = fake.generate_text(call())

    assert json.loads(body["message"]["content"]) == {"seen": "test-model"}


def test_the_inventory_primitives_answer_about_the_model_without_a_provider() -> None:
    """The four model primitives answer with what the case declared, and record being asked."""
    fake = FakeProvider()

    assert fake.list_models(query()) == list(FAKE_MODELS)
    assert fake.check_model_available(query()) is True
    assert fake.get_context_window(query()) == FAKE_CONTEXT_WINDOW
    assert fake.get_model_info(query())["version"] == FAKE_MODEL_VERSION
    assert len(fake.model_calls) == 4
    assert not fake.calls


def test_the_double_refuses_a_model_the_endpoint_does_not_offer() -> None:
    """Acceptance: an unavailable model is a typed refusal, never a silent substitution."""
    with pytest.raises(LLMPrimitiveError) as raised:
        FakeProvider().check_model_available(query("absent"))

    assert raised.value.error.type == "MODEL_UNAVAILABLE"


def test_a_model_that_states_no_window_reports_an_unknown_one() -> None:
    """An unknown window is ``None``, which is what makes it not an overflow downstream."""
    fake = FakeProvider(context_window=None)

    assert fake.get_context_window(query()) is None


def test_no_test_of_this_processor_imports_a_client_library() -> None:
    """Read statically: a suite that imported one would stop proving the seam resolves it late."""
    package_root = Path(tests.llm.__file__).parent
    offenders: list[str] = []

    for module in sorted(package_root.rglob("*.py")):
        for line, name in imported_modules(module):
            if name.split(".")[0] in CLIENT_LIBRARIES:
                offenders.append(f"{module.name}:{line} imports {name}")

    assert not offenders, f"a test imports a client library: {offenders}"
