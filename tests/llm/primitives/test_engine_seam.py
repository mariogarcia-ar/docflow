"""Tests for the provider seam, driven by a stub HTTP client (``LLM-02``, ``LLM-09``).

No socket is opened. The seam resolves its client through :func:`importlib.import_module` at call
time — that is what keeps importing the package free of a client library — so a stub installed
in ``sys.modules`` is the client, and every request it was asked for can be inspected. That is
how the payload shapes, the endpoint defaults and the error mapping are proven without a
provider.

# pylint: disable=protected-access
# Reason: the cases reach ``_CONTEXT_HINTS`` and the transport classes by their own names on
# purpose: a test that read them through a second public name would be testing the alias.
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path
from typing import Any

import pytest

from docflow.llm.primitives import (
    OLLAMA_BASE_URL,
    OPENAI_COMPATIBLE_BASE_URL,
    PRIMITIVE_NAMES,
    LLMPrimitiveError,
    ModelQuery,
    OllamaProvider,
    OpenAICompatibleProvider,
    ProviderCall,
    check_model_available,
    generate_multimodal,
    generate_structured,
    generate_text,
    get_context_window,
    get_model_info,
    is_retryable,
    list_models,
    translate_provider_response,
    transport_for,
    usage_of,
)
from tests.fakes.engines.fake_provider import FakeProvider
from tests.llm.primitives.http_stub import StubClient


def call(**overrides: Any) -> ProviderCall:
    """Return a provider call, with any field overridden for the case under test."""
    fields: dict[str, Any] = {
        "provider": "ollama",
        "base_url": None,
        "api_key": None,
        "model": "test-model",
        "messages": [{"role": "user", "content": "a prompt"}],
        "images": [],
        "options": {"temperature": 0.0},
        "schema": None,
        "timeout": 5.0,
    }
    return ProviderCall(**{**fields, **overrides})


def query(**overrides: Any) -> ModelQuery:
    """Return a model query, with any field overridden for the case under test."""
    fields: dict[str, Any] = {
        "provider": "ollama",
        "model": "test-model",
        "base_url": None,
        "api_key": None,
        "timeout": 5.0,
    }
    return ModelQuery(**{**fields, **overrides})


def test_an_absent_client_is_reported_rather_than_worked_around(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider that cannot be reached is a failure, not an invitation to answer locally."""
    monkeypatch.setitem(sys.modules, "httpx", None)

    with pytest.raises(LLMPrimitiveError) as raised:
        generate_text(call())

    assert raised.value.error.type == "PROVIDER_ERROR"
    assert raised.value.error.metadata == {"module": "httpx"}


def test_a_provider_this_seam_does_not_reach_is_refused_by_name() -> None:
    """There is no default provider: a guessed endpoint would answer a question nobody asked."""
    with pytest.raises(LLMPrimitiveError) as raised:
        transport_for("something-else")

    assert raised.value.error.type == "PROVIDER_ERROR"
    assert raised.value.error.recoverable is False
    assert "ollama" in raised.value.error.metadata["known"]


def test_an_ollama_call_posts_its_own_body_to_its_own_endpoint(http) -> None:
    """The request body is Ollama's, and the endpoint is the documented local one."""
    client = http(body={"message": {"content": "{}"}, "model": "test-model"})

    body = generate_structured(call(schema={"type": "object"}))

    assert body["message"]["content"] == "{}"
    sent = client.requests[0]
    assert sent["method"] == "POST"
    assert sent["url"] == f"{OLLAMA_BASE_URL}/api/chat"
    assert sent["json"] == {
        "model": "test-model",
        "messages": [{"role": "user", "content": "a prompt"}],
        "stream": False,
        "options": {"temperature": 0.0},
        "format": {"type": "object"},
    }
    assert "headers" in sent and sent["headers"] == {}
    assert sent["timeout"] == 5.0


def test_an_ollama_request_field_is_lifted_out_of_the_model_options(http) -> None:
    """``think`` and ``keep_alive`` are ``/api/chat`` fields: Ollama reads them at the top level."""
    client = http(body={"message": {"content": "{}"}, "model": "test-model"})

    generate_structured(
        call(options={"think": False, "keep_alive": "30m", "temperature": 0.2})
    )

    sent = client.requests[0]["json"]
    assert sent["think"] is False
    assert sent["keep_alive"] == "30m"
    assert sent["options"] == {"temperature": 0.2}


def test_an_ollama_call_that_states_no_option_sends_an_empty_map(http) -> None:
    """Nothing stated is nothing sent: the daemon keeps the model's own defaults."""
    client = http(body={"message": {"content": "{}"}})

    generate_text(call(options={}))

    body = client.requests[0]["json"]
    assert body["options"] == {}
    assert "temperature" not in body and "top_p" not in body


def test_an_openai_compatible_call_posts_a_constrained_response_format(http) -> None:
    """The two providers differ in their wire format; that difference is the transport's job."""
    client = http(body={"choices": [{"message": {"content": "{}"}}]})

    generate_structured(
        call(provider="vllm", base_url="http://gpu:8000/v1/", schema={"type": "object"})
    )

    sent = client.requests[0]
    assert sent["url"] == "http://gpu:8000/v1/chat/completions"
    assert sent["json"]["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "response",
            "strict": True,
            "schema": {"type": "object"},
        },
    }


def test_a_credential_is_sent_as_a_header_and_never_into_the_body(http) -> None:
    """The credential reaches the provider and nothing else."""
    client = http()

    generate_text(call(api_key="a-secret"))

    assert client.requests[0]["headers"] == {"Authorization": "Bearer a-secret"}
    assert "a-secret" not in str(client.requests[0]["json"])


def test_an_ollama_call_carries_its_images_as_bare_base64(http, tmp_path: Path) -> None:
    """Ollama takes the encoded bytes inside the message, and reads the container from the path."""
    payload = b"\x89PNG\r\n\x1a\npayload"
    image = tmp_path / "page.png"
    image.write_bytes(payload)
    client = http()

    generate_multimodal(call(images=[str(image)]))

    assert client.requests[0]["json"]["messages"][0]["images"] == [
        base64.b64encode(payload).decode("ascii")
    ]


def test_an_openai_compatible_call_carries_its_images_as_content_parts(
    http, tmp_path: Path
) -> None:
    """The OpenAI dialect takes a data URL beside the text, in the same message."""
    payload = b"\x89PNG\r\n\x1a\npayload"
    image = tmp_path / "page.png"
    image.write_bytes(payload)
    client = http(body={"choices": [{"message": {"content": "{}"}}]})

    generate_multimodal(call(provider="openai", images=[str(image)]))

    parts = client.requests[0]["json"]["messages"][0]["content"]
    assert parts[0] == {"type": "text", "text": "a prompt"}
    assert parts[1]["image_url"]["url"] == (
        f"data:image/png;base64,{base64.b64encode(payload).decode('ascii')}"
    )


def test_an_image_the_request_names_but_the_run_cannot_read_is_a_missing_dependency(
    http, tmp_path: Path
) -> None:
    """The call cannot be sent without it, and sending it without the image answers elsewhere."""
    http()

    with pytest.raises(LLMPrimitiveError) as raised:
        generate_multimodal(call(images=[str(tmp_path / "gone.png")]))

    assert raised.value.error.type == "DEPENDENCY_ERROR"


@pytest.mark.parametrize(
    ("status", "body", "kind", "retryable"),
    [
        (404, {"error": "model not found"}, "MODEL_UNAVAILABLE", False),
        (400, {"error": "maximum context length is 4096"}, "CONTEXT_OVERFLOW", False),
        (413, {"error": "prompt too long for this model"}, "CONTEXT_OVERFLOW", False),
        (400, {"error": "malformed request"}, "PROVIDER_ERROR", True),
        (500, {"error": "internal"}, "PROVIDER_ERROR", True),
    ],
)
def test_an_http_status_is_mapped_to_a_kind_by_name(
    http, status: int, body: dict[str, Any], kind: str, retryable: bool
) -> None:
    """A 404 and a 500 are both failures, and only one of them is worth another call."""
    http(body=body, status=status)

    with pytest.raises(LLMPrimitiveError) as raised:
        generate_text(call())

    assert raised.value.error.type == kind
    assert is_retryable(raised.value.error) is retryable


def test_a_timeout_is_a_timeout(http) -> None:
    """A provider that did not answer is not a provider that refused."""
    http(raises=StubClient.TimeoutException("timed out"))

    with pytest.raises(LLMPrimitiveError) as raised:
        generate_text(call())

    assert raised.value.error.type == "TIMEOUT"
    assert raised.value.error.metadata["timeout"] == 5.0


def test_a_transport_error_is_a_provider_error(http) -> None:
    """Connection refused and a DNS failure are the provider being unreachable."""
    http(raises=StubClient.HTTPError("connection refused"))

    with pytest.raises(LLMPrimitiveError) as raised:
        generate_text(call())

    assert raised.value.error.type == "PROVIDER_ERROR"


@pytest.mark.parametrize("body", ["not json at all", "[1, 2]"])
def test_a_body_that_is_not_a_json_object_is_an_invalid_response(
    http, body: Any
) -> None:
    """An answer this processor cannot read is reported, never treated as an empty answer."""
    http(body=body)

    with pytest.raises(LLMPrimitiveError) as raised:
        generate_text(call())

    assert raised.value.error.type == "INVALID_RESPONSE"


def test_the_ollama_model_list_is_read_from_its_own_key(http) -> None:
    """The two endpoints name their lists differently, and each is read as it is written."""
    client = http(body={"models": [{"name": "llama3"}, {"name": "qwen"}]})

    assert list_models(query()) == ["llama3", "qwen"]
    assert client.requests[0]["url"] == f"{OLLAMA_BASE_URL}/api/tags"


def test_the_openai_model_list_is_read_too(http) -> None:
    """A second client, because the two providers answer one question two ways."""
    client = http(body={"data": [{"id": "gpt"}, {"id": "mistral"}]})

    assert list_models(query(provider="openai")) == ["gpt", "mistral"]
    assert client.requests[0]["url"] == f"{OPENAI_COMPATIBLE_BASE_URL}/models"


def test_a_model_the_endpoint_does_not_offer_is_refused_by_name(http) -> None:
    """Acceptance: ``check_model_available`` raises ``MODEL_UNAVAILABLE``, never a substitution."""
    http(body={"models": [{"name": "another-model"}]})

    with pytest.raises(LLMPrimitiveError) as raised:
        check_model_available(query())

    assert raised.value.error.type == "MODEL_UNAVAILABLE"
    assert raised.value.error.metadata["available"] == ["another-model"]


def test_a_model_the_endpoint_offers_passes_the_check(http) -> None:
    """The check is a check, not a refusal waiting to happen."""
    http(body={"models": [{"name": "test-model"}]})

    assert check_model_available(query()) is True


def test_the_context_window_is_read_from_the_parameters_the_model_declares(
    http,
) -> None:
    """Ollama states ``num_ctx`` among the model's parameters, or states nothing."""
    http(body={"parameters": 'stop "<|eot_id|>"\nnum_ctx 8192\n'})

    assert get_context_window(query()) == 8192


def test_a_model_that_states_no_window_reports_none(http) -> None:
    """An unmeasured ceiling is ``None``, never a fabricated number."""
    http(body={"parameters": "temperature 0.8"})

    assert get_context_window(query()) is None


def test_a_provider_that_cannot_state_a_window_asks_nobody(http) -> None:
    """No OpenAI-compatible endpoint states a window, so none is invented or requested."""
    client = http()

    assert get_context_window(query(provider="openai")) is None
    assert client.requests == []


def test_the_model_version_is_the_digest_a_local_model_is_identified_by(http) -> None:
    """Acceptance: a version is recorded only where the provider states one."""
    http(body={"digest": "sha256:abc", "details": {"family": "llama"}})

    info = get_model_info(query())

    assert info["version"] == "sha256:abc"
    assert info["family"] == "llama"


def test_an_endpoint_that_states_no_version_reports_none(http) -> None:
    """A fabricated version would enter the request key and make two models look like one."""
    http(body={"id": "gpt", "created": 1_700_000_000})

    info = get_model_info(query(provider="openai"))

    assert info["version"] is None
    assert info["created"] == 1_700_000_000


def test_an_ollama_answer_is_translated_with_its_own_usage_names() -> None:
    """The translation is ours; the body is the provider's."""
    # The body is the double's own native shape, so this case cannot drift from the shape the
    # rest of the suite feeds the seam.
    body = FakeProvider().body_for(call(), '{"a": 1}')

    response = translate_provider_response("ollama", body)

    assert response.text == '{"a": 1}'
    assert response.finish_reason == "stop"
    assert response.timing["load_time"] == 0.1
    assert response.timing["inference_time"] == 0.4
    usage = usage_of("ollama", response.usage)
    assert (usage.input_tokens, usage.output_tokens, usage.total_tokens) == (12, 4, 16)
    assert usage.cached_tokens is None


def test_an_openai_answer_is_translated_with_its_own_usage_names() -> None:
    """The same record, from a differently shaped body."""
    response = translate_provider_response(
        "vllm",
        {
            "model": "mistral",
            "choices": [
                {"message": {"content": "{}"}, "finish_reason": "length"},
            ],
            "usage": {"prompt_tokens": 3, "completion_tokens": 5, "total_tokens": 8},
        },
    )

    assert response.finish_reason == "length"
    assert not response.timing
    usage = usage_of("vllm", response.usage)
    assert (usage.input_tokens, usage.total_tokens) == (3, 8)


def test_an_answer_without_any_text_is_an_invalid_response() -> None:
    """An answer that is not there is not an empty answer."""
    with pytest.raises(LLMPrimitiveError) as raised:
        translate_provider_response("ollama", {"model": "llama3"})

    assert raised.value.error.type == "INVALID_RESPONSE"


def test_the_two_transports_expose_the_same_surface() -> None:
    """A provider swap changes the transport and nothing else (``LLM-09``)."""
    surfaces = [
        {name for name in PRIMITIVE_NAMES if hasattr(kind, name)}
        for kind in (OllamaProvider(), OpenAICompatibleProvider())
    ]

    assert surfaces[0] == set(PRIMITIVE_NAMES)
    assert surfaces[1] == set(PRIMITIVE_NAMES)
