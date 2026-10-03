# pylint: disable=too-many-lines,duplicate-code
# Reason: the provider seam is one module on purpose. The frozen injection point is the module
# attribute ``docflow.llm.primitives.<generator>``, and the double replaces that symbol, so a
# transport moved into a sibling package would escape the injection point and stop being
# exercised. The two providers are siblings only where they must be: they differ in their URL
# paths and payload shapes, which is the part that cannot be shared, and they share the HTTP
# plumbing they can.
"""Low-level provider primitives — the only place in the tree that knows a provider.

Ollama, vLLM and a hosted OpenAI-compatible API are reached from this package and from nowhere
else. Neither the orchestrator nor another processor may import it; both go through
:func:`docflow.llm.process_llm_request`.

**The surface.** Seven names, and every one of them is a *transport*: it sends a request and
hands back what the provider answered, in the provider's own shape — a mapping parsed from the
provider's JSON body. Nothing here parses a model's answer, validates it against a schema or
decides whether a result is reusable; that is the rest of the package's job, and it is the half
the injected double deliberately leaves under test.

=============================== ==========================================================
Primitive                       Reaches
=============================== ==========================================================
``generate_text``               ``POST /api/chat`` (Ollama) · ``POST /chat/completions``
``generate_multimodal``         the same two, with the images attached
``generate_structured``         the same two, with the response format constrained
``list_models``                 ``GET /api/tags`` (Ollama) · ``GET /models``
``check_model_available``       :func:`list_models`, then a typed refusal
``get_context_window``          ``POST /api/show`` (Ollama) · not stated by the other kind
``get_model_info``              ``POST /api/show`` (Ollama) · ``GET /models/{id}``
=============================== ==========================================================

**Streaming.** Reading an answer as it is written is a property of the *call*, not an eighth
primitive: :attr:`~docflow.llm.primitives.ProviderCall.stream` asks to be read as it is written
and :attr:`~docflow.llm.primitives.ProviderCall.observer` watches it arrive. The generators
return exactly what they return today — the provider's whole body, reassembled from the deltas
— so a streaming caller and a waiting one receive the same body and the surface stays the seven
names above. An OpenAI-compatible stream states no usage unless the endpoint chooses to send it,
and a figure no endpoint stated is reported as ``None``, never as a zero.

**Lazy import.** ``httpx`` is resolved inside the call that needs it, never at module import
time, so ``import docflow.llm.primitives`` succeeds on a machine with no HTTP client — the
guarantee ``tests/test_skeleton.py`` measures. An absent client is a typed ``PROVIDER_ERROR``.

**Engine signal → failure kind** (the mapping this module is the only owner of):

=================================================== ==================================
Engine signal                                       ``LLMErrorType``
=================================================== ==================================
no client library installed                         ``PROVIDER_ERROR``, retryable
connection refused, DNS failure, TLS failure        ``PROVIDER_ERROR``, retryable
read or connect timeout                             ``TIMEOUT``, retryable
HTTP 404 naming the model                           ``MODEL_UNAVAILABLE``, not retryable
HTTP 400/413 whose body names the context length    ``CONTEXT_OVERFLOW``, not retryable
any other non-2xx status                            ``PROVIDER_ERROR``, retryable
a body that is not JSON, or carries no answer text  ``INVALID_RESPONSE``, retryable
anything else                                       ``INTERNAL_ERROR``, not retryable
=================================================== ==================================

Two rules hold for everything here: an unnamed provider is refused rather than guessed at, and
``api_key`` is sent but never recorded — it is dropped from the normalized options before a
request key or an artifact is written.

# TODO: [MVP] provider-native schema dialects, prompt caching and per-provider concurrency
# limits. # TODO: [RELEASE] GPU-competition and queue policy.
"""

from __future__ import annotations

import base64
import importlib
import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Protocol

from docflow.llm.contracts import Usage

# Re-exported so the entry point imports the whole provider surface from one module.
from docflow.llm.primitives.composition import (
    API_KEY_OPTION,
    ASSETS_DIR_KEY,
    CHAIN_DEPENDENCIES,
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_TIMEOUT_SECONDS,
    INFERENCE_CHAIN,
    OUTPUT_DIR_KEY,
    RUN_ID_KEY,
    STREAM_OPTION,
    assets_dir_for,
    attempt_validation_record,
    attempt_validation_state,
    build_inference_plan,
    build_messages,
    calculate_request_key,
    canonical_json,
    compare_outputs,
    count_tokens,
    default_inference_graph,
    find_reusable_node_result,
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
    request_timeout,
    resolve_generator,
    schema_digest,
    should_retry,
    stated_context_window,
    stated_model_version,
    truncate_to_token_limit,
    validate_cached_result,
)
from docflow.llm.primitives.errors import (
    NON_RETRYABLE_KINDS,
    RETRYABLE_KINDS,
    LLMPrimitiveError,
    is_retryable,
    typed_failure,
)
from docflow.llm.primitives.persistence import (
    load_graph_state,
    load_result,
    save_graph_state,
    save_result,
)
from docflow.llm.primitives.publication import (
    ensure_directory,
    write_json_atomic,
    write_text_atomic,
)
from docflow.llm.primitives.validation import (
    load_schema,
    load_template,
    validate_llm_input,
    validate_llm_result,
    validate_schema,
)

#: Provider names this seam reaches, and the transport each one resolves to. A name absent from
#: this mapping is refused by name: there is no default provider and no probing for one.
PROVIDER_KINDS: Final[dict[str, str]] = {
    "ollama": "ollama",
    "openai_compatible": "openai_compatible",
    "openai": "openai_compatible",
    "vllm": "openai_compatible",
}

#: The documented default endpoint of each transport. A default *address* for a local daemon is a
#: convention, not an answer, and it is recorded in the run's metadata so it is never hidden.
OLLAMA_BASE_URL: Final[str] = "http://localhost:11434"
OPENAI_COMPATIBLE_BASE_URL: Final[str] = "http://localhost:8000/v1"

#: The generator names :func:`docflow.llm.primitives.composition.resolve_generator` returns.
GENERATORS: Final[tuple[str, ...]] = (
    "generate_text",
    "generate_multimodal",
    "generate_structured",
)

#: The whole primitive surface — what the double must model and what the conformance test reads.
PRIMITIVE_NAMES: Final[tuple[str, ...]] = (
    *GENERATORS,
    "list_models",
    "check_model_available",
    "get_context_window",
    "get_model_info",
)

#: The Ollama parameter that carries a model's context window.
NUM_CTX = re.compile(r"num_ctx\s+(\d+)")

#: The values a caller states through ``options`` that Ollama reads at the *top* of the
#: ``/api/chat`` body rather than as model parameters: ``think`` is a reasoning model's thinking
#: switch, ``keep_alive`` is how long the model stays loaded. Everything else in ``options`` is a
#: decoding parameter and stays inside ``options``.
_OLLAMA_REQUEST_FIELDS: Final[tuple[str, ...]] = ("think", "keep_alive")

#: The two channels a streamed answer arrives on: the answer itself, and the trace a reasoning
#: model writes before it. ``content`` is Ollama's own field name for the first; the second is
#: read from ``message.thinking`` on Ollama and ``delta.reasoning_content`` on the
#: OpenAI-compatible dialect, which are the two spellings the models behind each one use.
CONTENT_CHANNEL: Final[str] = "content"
THINKING_CHANNEL: Final[str] = "thinking"


@dataclass(frozen=True)
class StreamDelta:
    """One piece of an answer, read as it was written.

    Attributes:
        channel: :data:`CONTENT_CHANNEL` for the answer, :data:`THINKING_CHANNEL` for a reasoning
            model's trace.
        text: The piece itself, exactly as the provider wrote it.
    """

    channel: str
    text: str


#: What a caller gives a streaming call to watch it: called once per delta, in arrival order,
#: while the answer is written. An observer is never required — a streaming call without one is
#: still read as it arrives — and it never replaces the answer: the body the primitive returns
#: is the whole one, exactly as a waiting call would have received it.
DeltaObserver = Callable[[StreamDelta], None]

#: A provider's own reader: given the lines of a streaming answer and the observer to feed,
#: return the body the same call would have returned without streaming.
_StreamConsumer = Callable[[Iterable[str], "DeltaObserver | None"], dict[str, Any]]

#: Where each dialect spells a streamed delta's text, by channel. Ollama names the two fields
#: after the channels themselves; the OpenAI-compatible dialect calls a reasoning trace
#: ``reasoning_content``, which is the spelling DeepSeek and vLLM use.
_OLLAMA_DELTA_FIELDS: Final[tuple[tuple[str, str], ...]] = (
    (CONTENT_CHANNEL, CONTENT_CHANNEL),
    (THINKING_CHANNEL, THINKING_CHANNEL),
)

_OPENAI_DELTA_FIELDS: Final[tuple[tuple[str, str], ...]] = (
    (CONTENT_CHANNEL, "content"),
    (THINKING_CHANNEL, "reasoning_content"),
)

#: What a provider must mention in a 400/413 body for it to be a context overflow rather than a
#: malformed request. The wording differs per provider, so the check is on the idea, not a line.
_CONTEXT_HINTS: Final[tuple[str, ...]] = (
    "context length",
    "context window",
    "context size",
    "maximum context",
    "too long",
    "num_ctx",
)

#: Nanoseconds in a second: Ollama reports its durations in nanoseconds.
_NANOSECONDS: Final[float] = 1_000_000_000.0

__all__ = [
    "API_KEY_OPTION",
    "ASSETS_DIR_KEY",
    "CHAIN_DEPENDENCIES",
    "CONTENT_CHANNEL",
    "DEFAULT_MAX_ATTEMPTS",
    "DEFAULT_TIMEOUT_SECONDS",
    "GENERATORS",
    "INFERENCE_CHAIN",
    "NON_RETRYABLE_KINDS",
    "OLLAMA_BASE_URL",
    "OPENAI_COMPATIBLE_BASE_URL",
    "OUTPUT_DIR_KEY",
    "PRIMITIVE_NAMES",
    "PROVIDER_KINDS",
    "RETRYABLE_KINDS",
    "RUN_ID_KEY",
    "STREAM_OPTION",
    "THINKING_CHANNEL",
    "DeltaObserver",
    "LLMPrimitiveError",
    "ModelQuery",
    "OllamaProvider",
    "OpenAICompatibleProvider",
    "ProviderCall",
    "ProviderResponse",
    "StreamDelta",
    "assets_dir_for",
    "attempt_validation_record",
    "attempt_validation_state",
    "build_inference_plan",
    "build_messages",
    "calculate_request_key",
    "canonical_json",
    "check_model_available",
    "compare_outputs",
    "count_tokens",
    "default_inference_graph",
    "ensure_directory",
    "find_reusable_node_result",
    "generate_multimodal",
    "generate_structured",
    "generate_text",
    "get_context_window",
    "get_model_info",
    "increment_attempt",
    "input_hashes",
    "is_context_limit_exceeded",
    "is_node_reusable",
    "is_retryable",
    "list_models",
    "load_graph_state",
    "load_result",
    "load_schema",
    "load_template",
    "max_attempts",
    "merge_timing",
    "merge_usage",
    "mint_attempt_id",
    "normalize_llm_options",
    "output_dir_for",
    "parse_json_response",
    "pinned_run_id",
    "process_prompt",
    "request_timeout",
    "resolve_generator",
    "save_graph_state",
    "save_result",
    "schema_digest",
    "should_retry",
    "stated_context_window",
    "stated_model_version",
    "translate_provider_response",
    "truncate_to_token_limit",
    "typed_failure",
    "usage_of",
    "validate_cached_result",
    "validate_llm_input",
    "validate_llm_result",
    "validate_schema",
    "write_json_atomic",
    "write_text_atomic",
]


@dataclass(frozen=True)
class ProviderCall:
    """One inference, described in provider-neutral terms.

    The transport turns this into whatever body its provider expects, which is why the images
    travel as paths and the schema as a loaded mapping: the shape of the wire is the transport's
    business, and the double must not have to know it either.

    Attributes:
        provider: The provider name, as the request stated it.
        base_url: The endpoint, or ``None`` to use the transport's documented default.
        api_key: The credential to send, or ``None`` for an unauthenticated local endpoint.
        model: Model name. Never defaulted.
        messages: The chat messages, in order.
        images: Image paths to attach, in order.
        options: Decoding options passed through to the provider.
        schema: The response schema, when the call is structured.
        timeout: Per-call timeout, in seconds.
        stream: Whether to read the answer as it is written rather than wait for the whole of
            it. The body the generator returns is the same either way; only when it is available
            changes.
        observer: Called once per delta while a streaming call arrives, or ``None`` to stream
            unwatched. Ignored by a call that does not stream.
    """

    provider: str
    base_url: str | None
    api_key: str | None
    model: str
    messages: list[dict[str, Any]]
    images: list[str]
    options: dict[str, Any]
    schema: dict[str, Any] | None
    timeout: float
    stream: bool = False
    observer: DeltaObserver | None = None


@dataclass(frozen=True)
class ModelQuery:
    """One question about a model, rather than about an inference.

    Attributes:
        provider: The provider name, as the request stated it.
        model: Model name.
        base_url: The endpoint, or ``None`` to use the transport's documented default.
        api_key: The credential to send, or ``None``.
        timeout: Per-call timeout, in seconds.
    """

    provider: str
    model: str
    base_url: str | None
    api_key: str | None
    timeout: float


@dataclass(frozen=True)
class ProviderResponse:
    """What a provider's answer says, once its body has been read in *our* terms.

    The body itself is not modelled here: the transport returns it as it arrived, and this record
    is the translation of it — the half that stays under test while the double replaces the
    transport.

    Attributes:
        text: The answer text, exactly as the provider wrote it.
        model: The model the provider says answered, or ``None`` when it does not say.
        finish_reason: Why generation stopped, or ``None``.
        usage: The provider's own usage figures, under its own key names.
        timing: The durations the provider reported, in seconds.
        body: The provider's raw response body, verbatim.
    """

    text: str
    model: str | None
    finish_reason: str | None
    usage: dict[str, Any]
    timing: dict[str, float]
    body: dict[str, Any]


@dataclass(frozen=True)
class _Fields:
    """The two scalar fields an answer may or may not state."""

    model: str | None
    finish_reason: str | None


class LLMProvider(Protocol):
    """The provider surface, stated once so a swap changes only its implementation.

    Every method answers in the provider's own terms: the generators return the provider's parsed
    response body, and the three model methods answer a question about a model rather than about
    an inference. A different provider changes this module and nothing else — not the contract,
    not the workflow.
    """

    def generate_text(self, call: ProviderCall) -> Mapping[str, Any]:
        """Send a text-only call and return the provider's response body."""

    def generate_multimodal(self, call: ProviderCall) -> Mapping[str, Any]:
        """Send a call carrying images and return the provider's response body."""

    def generate_structured(self, call: ProviderCall) -> Mapping[str, Any]:
        """Send a call constrained to a response format and return the response body."""

    def list_models(self, query: ModelQuery) -> list[str]:
        """Return the model names the endpoint offers."""

    def check_model_available(self, query: ModelQuery) -> bool:
        """Return ``True``, or raise a typed ``MODEL_UNAVAILABLE``."""

    def get_context_window(self, query: ModelQuery) -> int | None:
        """Return the model's context window, or ``None`` when the provider states none."""

    def get_model_info(self, query: ModelQuery) -> dict[str, Any]:
        """Return what the provider knows about the model, version included when it has one."""


def _http() -> Any:
    """Return the HTTP client library, imported at call time and never at import time.

    Importing this package has to succeed with no client installed, so the library is resolved
    here rather than by a module-level ``import``.

    Returns:
        The library module.

    Raises:
        LLMPrimitiveError: With ``PROVIDER_ERROR`` when no client is installed. An absent client
            is reported, never worked around.
    """
    try:
        return importlib.import_module("httpx")
    except ImportError as exc:
        raise typed_failure(
            "PROVIDER_ERROR",
            "no HTTP client is available to reach a provider",
            metadata={"module": "httpx"},
        ) from exc


def _headers(api_key: str | None) -> dict[str, str]:
    """Return the request headers: the credential when there is one, and nothing otherwise."""
    return {} if api_key is None else {"Authorization": f"Bearer {api_key}"}


def _status_failure(
    provider: str, model: str, status: int, body: str
) -> LLMPrimitiveError:
    """Return the typed failure an HTTP status means, by name rather than by number alone."""
    if status == 404:
        return typed_failure(
            "MODEL_UNAVAILABLE",
            f"{provider} does not offer the model {model!r}",
            recoverable=False,
            metadata={"provider": provider, "model": model, "status": status},
        )
    if status in (400, 413) and any(hint in body.lower() for hint in _CONTEXT_HINTS):
        return typed_failure(
            "CONTEXT_OVERFLOW",
            f"{provider} refused the request as longer than {model!r} can take",
            recoverable=False,
            metadata={"provider": provider, "model": model, "status": status},
        )
    return typed_failure(
        "PROVIDER_ERROR",
        f"{provider} answered HTTP {status}",
        metadata={
            "provider": provider,
            "model": model,
            "status": status,
            "body": body[:500],
        },
    )


def _parsed_body(response: Any, subject: ProviderCall | ModelQuery) -> dict[str, Any]:
    """Return a response's JSON body, typed when the provider answered something else."""
    try:
        body = response.json()
    except ValueError as exc:
        raise typed_failure(
            "INVALID_RESPONSE",
            f"{subject.provider} answered something that is not JSON",
            metadata={"provider": subject.provider, "status": response.status_code},
        ) from exc
    if not isinstance(body, dict):
        raise typed_failure(
            "INVALID_RESPONSE",
            f"{subject.provider} answered a JSON value that is not an object",
            metadata={"provider": subject.provider},
        )
    return body


def _guarded(subject: ProviderCall | ModelQuery, request: Callable[[Any], Any]) -> Any:
    """Run one HTTP request, typing every way it can fail.

    The client library is handed to ``request`` rather than imported here twice, so the import
    stays at call time and the mapping below is written once for both of the ways this module
    sends — a request read whole and one read as it arrives.

    Args:
        subject: The call or query being sent, read for its provider, model and timeout.
        request: Given the client library, performs the request and returns its result.

    Returns:
        Whatever ``request`` returned.

    Raises:
        LLMPrimitiveError: With the kind the engine-signal table fixes.
    """
    http = _http()
    try:
        return request(http)
    except http.TimeoutException as exc:
        raise typed_failure(
            "TIMEOUT",
            f"{subject.provider} did not answer within {subject.timeout}s",
            metadata={
                "provider": subject.provider,
                "model": subject.model,
                "timeout": subject.timeout,
            },
        ) from exc
    except http.HTTPError as exc:
        raise typed_failure(
            "PROVIDER_ERROR",
            f"{subject.provider} could not be reached",
            metadata={
                "provider": subject.provider,
                "model": subject.model,
                "error": str(exc),
            },
        ) from exc


def _send(
    method: str, url: str, subject: ProviderCall | ModelQuery, **kwargs: Any
) -> Any:
    """Send one HTTP request and return its response, once it is not an error status.

    Args:
        method: The verb to send, ``"post"`` or ``"get"``.
        url: The endpoint.
        subject: The call or query being sent, read for its provider, model and timeout.
        kwargs: The request's own keyword arguments.

    Returns:
        The response.

    Raises:
        LLMPrimitiveError: With the kind the engine-signal table fixes.
    """

    def request(http: Any) -> Any:
        response = getattr(http, method)(
            url,
            timeout=subject.timeout,
            headers=_headers(subject.api_key),
            **kwargs,
        )
        if response.status_code >= 400:
            raise _status_failure(
                subject.provider, subject.model, response.status_code, response.text
            )
        return response

    return _guarded(subject, request)


def _post_json(
    url: str, body: Mapping[str, Any], subject: ProviderCall | ModelQuery
) -> dict[str, Any]:
    """POST ``body`` as JSON and return the parsed response body."""
    response = _send("post", url, subject, json=dict(body))
    return _parsed_body(response, subject)


def _stream_json(
    url: str, body: Mapping[str, Any], subject: ProviderCall, consume: _StreamConsumer
) -> dict[str, Any]:
    """POST ``body`` as JSON, read the answer as it is written, and return its whole body.

    The lines the provider sends are the transport's business, so each provider reads its own
    through ``consume``; what is shared is the request, the error mapping and the promise that
    the caller gets the body a waiting call would have received.

    Args:
        url: The endpoint.
        body: The request body, with its provider's streaming switch already set.
        subject: The streaming call, read for its endpoint, timeout and observer.
        consume: The provider's reader for its own streaming lines.

    Returns:
        The reassembled body.

    Raises:
        LLMPrimitiveError: With the kind the engine-signal table fixes, and with
            ``INVALID_RESPONSE`` when a chunk is not a JSON object.
    """

    def request(http: Any) -> dict[str, Any]:
        with http.stream(
            "POST",
            url,
            timeout=subject.timeout,
            headers=_headers(subject.api_key),
            json=dict(body),
        ) as response:
            if response.status_code >= 400:
                response.read()
                raise _status_failure(
                    subject.provider, subject.model, response.status_code, response.text
                )
            return consume(response.iter_lines(), subject.observer)

    return _guarded(subject, request)


def _json_object(line: str) -> dict[str, Any]:
    """Return one streaming line's parsed object.

    Args:
        line: One line of a streaming answer.

    Returns:
        The parsed object.

    Raises:
        LLMPrimitiveError: With ``INVALID_RESPONSE`` when the line is not a JSON object — a
            chunk this module cannot read is an answer it cannot assemble, and inventing an
            empty one would report a truncated answer as a whole one.
    """
    try:
        chunk = json.loads(line)
    except ValueError as exc:
        raise typed_failure(
            "INVALID_RESPONSE",
            "a streaming chunk is not JSON",
            metadata={"chunk": line[:200]},
        ) from exc
    if not isinstance(chunk, dict):
        raise typed_failure(
            "INVALID_RESPONSE",
            "a streaming chunk is not a JSON object",
            metadata={"chunk": line[:200]},
        )
    return chunk


def _sse_payload(line: str) -> dict[str, Any] | None:
    """Return one server-sent event's object, or ``None`` when the line carries none.

    Args:
        line: One line of an OpenAI-compatible stream.

    Returns:
        The event's parsed object, or ``None`` for a blank line, a comment, or the closing
        ``data: [DONE]`` marker — none of which carries any of the answer.
    """
    text = line.strip()
    if not text or text.startswith(":"):
        return None
    if text.startswith("data:"):
        text = text[len("data:") :].strip()
    if not text or text == "[DONE]":
        return None
    return _json_object(text)


def _get_json(url: str, subject: ModelQuery) -> dict[str, Any]:
    """GET ``url`` and return the parsed response body."""
    response = _send("get", url, subject)
    return _parsed_body(response, subject)


def _collect(
    piece: Any, channel: str, sink: list[str], observer: DeltaObserver | None
) -> None:
    """Append one streamed piece to its channel and show it to the observer.

    A piece the provider did not send is not a piece: an absent field leaves the channel alone
    rather than contributing an empty string to it.

    Args:
        piece: What the provider sent for this channel, if anything.
        channel: The channel the piece belongs to.
        sink: The pieces read so far for this channel.
        observer: Called with the piece, or ``None`` to read unwatched.
    """
    if isinstance(piece, str) and piece:
        sink.append(piece)
        if observer is not None:
            observer(StreamDelta(channel=channel, text=piece))


def _image_parts(paths: Sequence[str]) -> list[tuple[str, str]]:
    """Return ``(mime_type, base64)`` for each image, reading the bytes once.

    Raises:
        LLMPrimitiveError: With ``DEPENDENCY_ERROR`` when an image the request names cannot be
            read — the call cannot be sent without it, and sending it without the image would
            answer a different question.
    """
    parts: list[tuple[str, str]] = []
    for path in paths:
        try:
            payload = Path(path).read_bytes()
        except OSError as unreadable:
            raise typed_failure(
                "DEPENDENCY_ERROR",
                f"the image {path!r} could not be read",
                recoverable=False,
                metadata={"image": str(path), "os_error": str(unreadable)},
            ) from unreadable
        suffix = Path(path).suffix.lower()
        mime = "image/jpeg" if suffix in (".jpg", ".jpeg") else "image/png"
        parts.append((mime, base64.b64encode(payload).decode("ascii")))
    return parts


class _HttpProvider:
    """The plumbing every HTTP provider shares: the URL, the two verbs and the model check.

    What a provider *does* differ in is its paths and its payload shapes; what it does *not*
    differ in is how a request is sent and how a failure is classified, so that part exists once.
    """

    kind: str = ""

    def _base_url(self, subject: ProviderCall | ModelQuery) -> str:
        """Return the endpoint to use: the subject's own, or the kind's documented default."""
        raise NotImplementedError

    def generate_text(self, call: ProviderCall) -> Mapping[str, Any]:
        """Send a text-only call."""
        return self._generate(call, multimodal=False)

    def generate_multimodal(self, call: ProviderCall) -> Mapping[str, Any]:
        """Send a call carrying images."""
        return self._generate(call, multimodal=True)

    def generate_structured(self, call: ProviderCall) -> Mapping[str, Any]:
        """Send a call whose response format is constrained."""
        return self._generate(call, multimodal=bool(call.images))

    def list_models(self, query: ModelQuery) -> list[str]:
        """Return the model names the endpoint offers."""
        raise NotImplementedError

    def check_model_available(self, query: ModelQuery) -> bool:
        """Return ``True``, or refuse by name.

        Raises:
            LLMPrimitiveError: With ``MODEL_UNAVAILABLE`` when the endpoint does not offer the
                model — never a silent substitution with another one.
        """
        available = self.list_models(query)
        if query.model not in available:
            raise typed_failure(
                "MODEL_UNAVAILABLE",
                f"{query.provider} does not offer the model {query.model!r}",
                recoverable=False,
                metadata={
                    "provider": query.provider,
                    "model": query.model,
                    "available": available[:50],
                },
            )
        return True

    def get_context_window(self, query: ModelQuery) -> int | None:
        """Return the model's context window when the provider states one, else ``None``.

        This dialect has no endpoint that states a window, so the answer is *unknown* rather than
        invented — ``is_context_limit_exceeded`` treats ``None`` as "cannot tell" and never as an
        overflow.
        """
        # pylint: disable=unused-argument
        # Reason: the query is part of the surface every provider shares, and a dialect that has
        # no answer to it still has to accept the question.
        return None

    def get_model_info(self, query: ModelQuery) -> dict[str, Any]:
        """Return what the provider knows about the model."""
        raise NotImplementedError

    def _generate(self, call: ProviderCall, *, multimodal: bool) -> Mapping[str, Any]:
        """Build the provider's body and send it. Implemented per provider kind."""
        raise NotImplementedError


class OllamaProvider(_HttpProvider):
    """Ollama, reached over its own HTTP API.

    Local and, by default, unauthenticated; the endpoint's address is the documented default
    unless the request states another.
    """

    kind = "ollama"

    def _base_url(self, subject: ProviderCall | ModelQuery) -> str:
        """Return the Ollama endpoint for this subject."""
        stated = subject.base_url
        return OLLAMA_BASE_URL if not stated else str(stated).rstrip("/")

    def _generate(self, call: ProviderCall, *, multimodal: bool) -> Mapping[str, Any]:
        """POST ``/api/chat`` with an Ollama-shaped body."""
        message: dict[str, Any] = {
            "role": "user",
            "content": call.messages[-1]["content"],
        }
        if multimodal:
            message["images"] = [
                payload for _mime, payload in _image_parts(call.images)
            ]
        body: dict[str, Any] = {
            "model": call.model,
            "messages": [message],
            "stream": call.stream,
        }
        options = dict(call.options)
        for name in _OLLAMA_REQUEST_FIELDS:
            if name in options:
                body[name] = options.pop(name)
        body["options"] = options
        if call.schema is not None:
            body["format"] = dict(call.schema)
        url = f"{self._base_url(call)}/api/chat"
        if call.stream:
            return _stream_json(url, body, call, self._consume_stream)
        return _post_json(url, body, call)

    def _consume_stream(
        self, lines: Iterable[str], observer: DeltaObserver | None
    ) -> dict[str, Any]:
        """Read Ollama's chunks into the body a waiting call would have received.

        Ollama sends one JSON object per line and repeats nothing: the deltas carry the answer
        in ``message.content`` and a reasoning model's trace in ``message.thinking``, and the
        last object carries the counters. The message is rebuilt from the deltas and the last
        object is the body, exactly as a non-streaming call returns it.

        Args:
            lines: The provider's streaming lines.
            observer: Called once per delta, or ``None`` to read unwatched.

        Returns:
            The reassembled body.

        Raises:
            LLMPrimitiveError: With ``INVALID_RESPONSE`` when a line is not a JSON object.
        """
        sinks: dict[str, list[str]] = {CONTENT_CHANNEL: [], THINKING_CHANNEL: []}
        closing: dict[str, Any] = {}
        for line in lines:
            if not line.strip():
                continue
            closing = _json_object(line)
            message = closing.get("message") or {}
            for channel, field in _OLLAMA_DELTA_FIELDS:
                _collect(message.get(field), channel, sinks[channel], observer)
        message = dict(closing.get("message") or {})
        message[CONTENT_CHANNEL] = "".join(sinks[CONTENT_CHANNEL])
        if sinks[THINKING_CHANNEL]:
            message[THINKING_CHANNEL] = "".join(sinks[THINKING_CHANNEL])
        closing["message"] = message
        return closing

    def list_models(self, query: ModelQuery) -> list[str]:
        """Return the tags the daemon serves."""
        body = _get_json(f"{self._base_url(query)}/api/tags", query)
        return [
            str(entry.get("name", ""))
            for entry in body.get("models", [])
            if entry.get("name")
        ]

    def get_context_window(self, query: ModelQuery) -> int | None:
        """Return the ``num_ctx`` the model is configured with, when it states one."""
        declared = str(self._show(query).get("parameters") or "")
        found = NUM_CTX.search(declared)
        return int(found.group(1)) if found else None

    def get_model_info(self, query: ModelQuery) -> dict[str, Any]:
        """Return the model's digest and declared parameters.

        A locally pulled model is identified by its digest, so that is the version this returns;
        an endpoint that states none returns ``None`` rather than a fabricated one.
        """
        info = self._show(query)
        details = info.get("details") or {}
        digest = info.get("digest")
        return {
            "provider": "ollama",
            "model": query.model,
            "version": digest if isinstance(digest, str) and digest else None,
            "digest": digest,
            "family": details.get("family"),
            "parameter_size": details.get("parameter_size"),
        }

    def _show(self, query: ModelQuery) -> dict[str, Any]:
        """Return ``POST /api/show``'s body for the model."""
        return _post_json(
            f"{self._base_url(query)}/api/show", {"model": query.model}, query
        )


class OpenAICompatibleProvider(_HttpProvider):
    """vLLM and any hosted API that speaks the OpenAI chat-completions dialect.

    The two are one transport because they are one wire format: the endpoint is what differs, and
    it is stated by the request rather than assumed.
    """

    kind = "openai_compatible"

    def _base_url(self, subject: ProviderCall | ModelQuery) -> str:
        """Return the endpoint for this subject."""
        stated = subject.base_url
        return OPENAI_COMPATIBLE_BASE_URL if not stated else str(stated).rstrip("/")

    def _generate(self, call: ProviderCall, *, multimodal: bool) -> Mapping[str, Any]:
        """POST ``/chat/completions`` with an OpenAI-shaped body."""
        content: Any = call.messages[-1]["content"]
        if multimodal:
            content = [{"type": "text", "text": content}] + [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{payload}"},
                }
                for mime, payload in _image_parts(call.images)
            ]
        body: dict[str, Any] = {
            "model": call.model,
            "messages": [{"role": "user", "content": content}],
            "stream": call.stream,
            **call.options,
        }
        if call.schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "response",
                    "strict": True,
                    "schema": dict(call.schema),
                },
            }
        url = f"{self._base_url(call)}/chat/completions"
        if call.stream:
            return _stream_json(url, body, call, self._consume_stream)
        return _post_json(url, body, call)

    def _consume_stream(
        self, lines: Iterable[str], observer: DeltaObserver | None
    ) -> dict[str, Any]:
        """Read an OpenAI-compatible event stream into the body a waiting call would have got.

        The dialect sends server-sent events: each carries a ``choices[0].delta`` piece of the
        answer, and the last one that stops generation carries the reason. The body is rebuilt
        in the shape a non-streaming call returns — one ``choices[0].message`` — so that nothing
        downstream can tell the two apart. Usage is reported only when the endpoint chose to
        send it, and an endpoint that sent none leaves it absent rather than zero.

        Args:
            lines: The provider's streaming lines.
            observer: Called once per delta, or ``None`` to read unwatched.

        Returns:
            The reassembled body.

        Raises:
            LLMPrimitiveError: With ``INVALID_RESPONSE`` when an event is not a JSON object.
        """
        sinks: dict[str, list[str]] = {CONTENT_CHANNEL: [], THINKING_CHANNEL: []}
        model: str | None = None
        finish_reason: Any = None
        usage: dict[str, Any] = {}
        for line in lines:
            payload = _sse_payload(line)
            if payload is None:
                continue
            if payload.get("model"):
                model = str(payload["model"])
            if isinstance(payload.get("usage"), Mapping):
                usage = dict(payload["usage"])
            choice = (payload.get("choices") or [{}])[0]
            if choice.get("finish_reason") is not None:
                finish_reason = choice["finish_reason"]
            delta = choice.get("delta") or {}
            for channel, field in _OPENAI_DELTA_FIELDS:
                _collect(delta.get(field), channel, sinks[channel], observer)
        message: dict[str, Any] = {
            "role": "assistant",
            "content": "".join(sinks[CONTENT_CHANNEL]),
        }
        if sinks[THINKING_CHANNEL]:
            message["reasoning_content"] = "".join(sinks[THINKING_CHANNEL])
        body: dict[str, Any] = {
            "model": model,
            "choices": [{"message": message, "finish_reason": finish_reason}],
        }
        if usage:
            body["usage"] = usage
        return body

    def list_models(self, query: ModelQuery) -> list[str]:
        """Return the ids the endpoint serves."""
        body = _get_json(f"{self._base_url(query)}/models", query)
        return [
            str(entry.get("id", ""))
            for entry in body.get("data", [])
            if entry.get("id")
        ]

    def get_model_info(self, query: ModelQuery) -> dict[str, Any]:
        """Return the model's identity as the endpoint states it.

        An OpenAI-compatible ``/models`` entry carries an id and a creation timestamp. Neither is
        a version, so ``version`` is ``None`` — a fabricated one would enter the request key and
        make two different models look like one.
        """
        body = _get_json(f"{self._base_url(query)}/models/{query.model}", query)
        return {
            "provider": "openai_compatible",
            "model": str(body.get("id") or query.model),
            "version": None,
            "created": body.get("created"),
            "owned_by": body.get("owned_by"),
        }


def transport_for(provider: str) -> _HttpProvider:
    """Return the transport a provider name resolves to.

    Args:
        provider: The name the request stated.

    Returns:
        The transport.

    Raises:
        LLMPrimitiveError: With ``PROVIDER_ERROR`` when the name is not one this seam reaches.
            There is no default provider: a call sent to a guessed one would answer a question
            nobody asked.
    """
    kind = PROVIDER_KINDS.get(provider)
    if kind is None:
        raise typed_failure(
            "PROVIDER_ERROR",
            f"{provider!r} is not a provider this processor reaches",
            recoverable=False,
            metadata={"provider": provider, "known": sorted(PROVIDER_KINDS)},
        )
    return OllamaProvider() if kind == "ollama" else OpenAICompatibleProvider()


def generate_text(call: ProviderCall) -> Mapping[str, Any]:
    """Send a text-only call and return the provider's own response body.

    The module attribute is the frozen injection point: the double replaces *this name*, which is
    why the entry point resolves it through the module at call time.
    """
    return transport_for(call.provider).generate_text(call)


def generate_multimodal(call: ProviderCall) -> Mapping[str, Any]:
    """Send a call carrying images and return the provider's own response body."""
    return transport_for(call.provider).generate_multimodal(call)


def generate_structured(call: ProviderCall) -> Mapping[str, Any]:
    """Send a response-format-constrained call and return the provider's own response body."""
    return transport_for(call.provider).generate_structured(call)


def list_models(query: ModelQuery) -> list[str]:
    """Return the model names the endpoint offers."""
    return transport_for(query.provider).list_models(query)


def check_model_available(query: ModelQuery) -> bool:
    """Return ``True``, or raise a typed ``MODEL_UNAVAILABLE`` naming what is missing."""
    return transport_for(query.provider).check_model_available(query)


def get_context_window(query: ModelQuery) -> int | None:
    """Return the model's context window, or ``None`` when no endpoint states one."""
    return transport_for(query.provider).get_context_window(query)


def get_model_info(query: ModelQuery) -> dict[str, Any]:
    """Return what the provider knows about the model, including its version when it has one."""
    return transport_for(query.provider).get_model_info(query)


def translate_provider_response(
    provider: str, body: Mapping[str, Any]
) -> ProviderResponse:
    """Return one provider's response body in the processor's own terms.

    Args:
        provider: The provider that answered.
        body: The provider's parsed response body.

    Returns:
        The answer text, the provider's usage figures and durations, and the body verbatim.

    Raises:
        LLMPrimitiveError: With ``INVALID_RESPONSE`` when the body carries no answer text, and
            ``PROVIDER_ERROR`` when the provider is not one this seam reaches. An answer that is
            not there is not an empty answer.
    """
    kind = PROVIDER_KINDS.get(provider)
    if kind is None:
        raise typed_failure(
            "PROVIDER_ERROR",
            f"{provider!r} is not a provider this processor reaches",
            recoverable=False,
            metadata={"provider": provider},
        )
    text, usage, timing, fields = (
        _ollama_fields(body) if kind == "ollama" else _openai_fields(body)
    )
    if text is None:
        raise typed_failure(
            "INVALID_RESPONSE",
            f"{provider} answered without any text",
            metadata={"provider": provider, "body": canonical_json(body)[:500]},
        )
    return ProviderResponse(
        text=text,
        model=fields.model,
        finish_reason=fields.finish_reason,
        usage=usage,
        timing=timing,
        body=dict(body),
    )


def _ollama_fields(
    body: Mapping[str, Any],
) -> tuple[str | None, dict[str, Any], dict[str, float], _Fields]:
    """Return the text, usage, durations and scalars of an Ollama answer."""
    message = body.get("message") or {}
    text = message.get("content")
    if text is None:
        text = body.get("response")
    usage = {
        "prompt_eval_count": body.get("prompt_eval_count"),
        "eval_count": body.get("eval_count"),
    }
    timing = {
        name: value / _NANOSECONDS
        for name, value in (
            ("load_time", body.get("load_duration")),
            ("inference_time", body.get("eval_duration")),
            ("total_time", body.get("total_duration")),
        )
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }
    fields = _Fields(model=body.get("model"), finish_reason=body.get("done_reason"))
    return (text if isinstance(text, str) else None), usage, timing, fields


def _openai_fields(
    body: Mapping[str, Any],
) -> tuple[str | None, dict[str, Any], dict[str, float], _Fields]:
    """Return the text, usage, durations and scalars of an OpenAI-compatible answer."""
    choices = body.get("choices") or []
    first = choices[0] if choices else {}
    message = first.get("message") or {}
    text = message.get("content")
    usage = dict(body.get("usage") or {})
    details = usage.get("prompt_tokens_details")
    if "cached_tokens" not in usage and isinstance(details, Mapping):
        usage["cached_tokens"] = details.get("cached_tokens")
    fields = _Fields(model=body.get("model"), finish_reason=first.get("finish_reason"))
    return (text if isinstance(text, str) else None), usage, {}, fields


def usage_of(provider: str, reported: Mapping[str, Any]) -> Usage:
    """Return a usage record from a provider's own figures.

    Args:
        provider: The provider that answered.
        reported: The usage figures, under the provider's own key names.

    Returns:
        The record, with ``None`` for every figure the provider did not report — never a zero,
        which would read as a measurement.
    """
    if PROVIDER_KINDS.get(provider) == "ollama":
        prompt = reported.get("prompt_eval_count")
        completion = reported.get("eval_count")
        total: int | None = None
        if isinstance(prompt, int) and isinstance(completion, int):
            total = prompt + completion
        return Usage(
            input_tokens=prompt,
            output_tokens=completion,
            total_tokens=total,
            cached_tokens=None,
            provider_usage=dict(reported),
            estimated_cost=None,
        )
    return Usage(
        input_tokens=reported.get("prompt_tokens"),
        output_tokens=reported.get("completion_tokens"),
        total_tokens=reported.get("total_tokens"),
        cached_tokens=reported.get("cached_tokens"),
        provider_usage=dict(reported),
        estimated_cost=None,
    )
