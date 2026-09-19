"""The providers this adapter can reach, and the wire dialects they speak.

`frontier.py` used to conflate three separate things behind one constant
(``_PROVIDER = "anthropic"``): the **name** a caller writes as a prefix, the
**wire protocol** (headers, endpoint, body shape) and the **host and credential**
that protocol needs. That conflation is why a second provider could not be added
without editing the generation path: measured, ``capabilities("deepseek:…")``
answered ``provider_unknown`` because the only provider *name* was also the only
*protocol*.

This module separates them. A :class:`Provider` is a **name**, the :class:`Dialect`
it speaks, the environment variables holding its credential and address, and what it
can honestly be asked to do. A :class:`Dialect` turns one call into a request and
turns a response back into the normalised shape `frontier.py` already knows how to
read.

Why the dialogues normalise instead of the caller branching
-----------------------------------------------------------

The two dialects disagree about almost everything observable. Per field, the shape
in each:

- **credential header**: ``x-api-key`` + version header / ``Authorization: Bearer``
- **endpoint**: ``/v1/messages`` / ``/v1/chat/completions``
- **the answer**: ``content[]`` blocks whose ``tool_use.input`` is an **object** /
  ``choices[0].message`` whose ``tool_calls[0].function.arguments`` is a **JSON
  string**
- **stop reason**: ``stop_reason: "max_tokens"`` / ``finish_reason: "length"``
- **token counts**: ``usage.input_tokens`` / ``usage.prompt_tokens``
- **request id header**: ``request-id`` / ``x-request-id``

Rather than teach the generation path all six, each dialect **normalises its
response into the block shape this adapter already parses** — ``{"type": "tool_use",
"input": …}`` and ``{"type": "text", "text": …}``. That is deliberate: the block
reader (`frontier.py::_classify_block`) carries the *absence / null / value*
distinction `kernel-cli.md` §11 row 14 requires, it is already falsified by a
mutation, and a second parser would be a second answer to the same question.

The pin, and why it is per provider
-----------------------------------

The schema is sent as a tool the model is asked to call, so *which tool it must
call* is what makes the answer's shape a constraint rather than a hope. Every
provider supports asking; they disagree about whether the choice can be **pinned**:

- Anthropic's ``{"type": "tool", "name": "emit"}`` pins it, and its own API accepts
  that.
- OpenAI's ``{"type": "function", "function": {"name": "emit"}}`` and ``"required"``
  pin it, and OpenAI's own API accepts those.
- **DeepSeek rejects all three with HTTP 400** — ``"Thinking mode does not support
  this tool_choice"`` — on both of the endpoints it exposes. Measured; ``"auto"``,
  ``{"type": "any"}`` and omitting the field all answer 200 with a correct
  ``tool_use``.

So a provider declares :attr:`Provider.pins_tool_choice`, and a provider that cannot
pin gets the **weakest** form it accepts rather than the strongest written down for
a different vendor. What was actually sent is recorded on the evidence, because
*the constraint was enforced* and *the constraint was requested* are different facts
and only one of them is a guarantee.

Adding a provider
-----------------

One entry in :data:`PROVIDERS` and, if it speaks a new wire format, one
:class:`Dialect`. Nothing in `frontier.py` changes — which is the point of the
split, and the thing that was not true before.

PoC stage
---------

TODO: [MVP] This table is a **constant in the adapter** and belongs in the registry:
`prd.md` FR-10 makes K8 the home of the model catalog, and `S3-T12` owns the
operational-settings vocabulary this table's variable names have to agree with. It
lives here until that task lands, because a loader with its own error handling is
more moving parts than a table of four facts per provider is worth right now.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Protocol

# Pylint reports `duplicate-code` between `FORWARDED_PARAMETERS` below and
# `ollama.py`'s `_FORWARDED_OPTIONS`, and it reports it on **line 1** of a module —
# so the suppression has to be module-level rather than inline at the tuple.
#
# The two are **not** one list written twice: they are two vendors' vocabularies that
# happen to overlap. Ollama also forwards `num_ctx`, a parameter the hosted providers
# have no equivalent of, and adding it here to dodge the metric would send a field
# they do not accept. What is shared is a coincidence of four names, and merging them
# would mean one vendor's option rename silently retuning another's.
#
# Suppressed here, at the module the metric names **second**, rather than
# project-wide: the rule is right everywhere else, including at the two dialects
# below, where it would catch a copied body. Same reasoning and same placement as
# `frontier.py`'s own suppression.
# pylint: disable=duplicate-code

__all__: list[str] = [
    "DIALECTS",
    "FALLBACK_ENV_KEY",
    "PROVIDERS",
    "Answer",
    "AnthropicDialect",
    "Dialect",
    "OpenAIDialect",
    "Provider",
    "provider_named",
]

#: The credential variable shared by every provider, consulted **after** a
#: provider's own variable is absent.
#:
#: One name for all of them, because a single-provider setup is the common case and
#: making every caller learn a per-vendor variable to place one key would be
#: ceremony around the ordinary thing. A per-provider name exists for the case that
#: needs it: `judge` must not be the model that produced the samples, so a run that
#: wants two *frontier* models needs two keys held at once — which one shared name
#: cannot express.
#:
#: Precedence is `provider-specific → this → no key`, and the order matters: setting
#: the specific name is how a caller says *use this one for this vendor*, and a
#: shared name silently overriding it would make that unexpressible.
FALLBACK_ENV_KEY: Final[str] = "DOCFLOW_FRONTIER_KEY"

#: The sampling options forwarded to a provider, as a name the dialect writes.
#: Anything else a caller sets in the environment is dropped rather than refused:
#: the runtime owns its own option vocabulary and a vendor-specific name invented
#: here would be this adapter choosing a parameter.
FORWARDED_PARAMETERS: Final[tuple[str, ...]] = (
    "temperature",
    "top_p",
    "top_k",
    "seed",
    "num_predict",
)


@dataclass(frozen=True, slots=True)
class Answer:
    """One provider's response, normalised into the shape the adapter reads.

    Attributes:
        blocks: The content, in the **block vocabulary `frontier.py` already
            parses** — ``{"type": "tool_use", "input": …}`` for an answer, or
            ``{"type": "text", "text": …}``. Normalising here is what keeps the
            absence/`null`/value distinction in one place.
        stop_reason: The provider's own word for why generation ended, **translated
            into the Anthropic vocabulary** so the ceiling rule has one spelling to
            check. OpenAI's ``"length"`` becomes ``"max_tokens"``; nothing else is
            rewritten, because an unrecognised reason is a fact worth keeping.
        prompt_tokens: Input tokens, or ``None`` when the provider did not report
            them. ``None`` means *unreported* and is never ``0``, which would read
            as *the provider said zero*.
        completion_tokens: Output tokens, or ``None``.
        total_tokens: The provider's own total, or ``None``. Not recomputed from
            the other two: a sum this adapter invented would be indistinguishable
            from a number the provider reported.
        model: The model the provider says answered, or ``None``.
        request_id: The provider's request identifier, or ``None``.

    """

    blocks: tuple[Mapping[str, Any], ...]
    stop_reason: str
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    model: str | None
    request_id: str | None


class Dialect(Protocol):
    """One wire protocol, as the four things a call needs from it.

    A ``Protocol`` rather than a base class because the two implementations share no
    code — they disagree about every field — and inheriting would suggest a shared
    body that does not exist. What they *do* share is the shape a call site needs,
    which is what a protocol states.

    The ellipses below are the interface rather than missing work: this is a
    declaration, and each method's contract is in its docstring.
    """

    # pylint: disable=unnecessary-ellipsis

    #: The dialect's name, for a provider's adapter revision string.
    name: str

    def path(self) -> str:
        """Report the endpoint path.

        Returns:
            The path, relative to the provider's base URL.

        """
        ...

    def headers(self, key: str) -> dict[str, str]:
        """Build the request headers, including the credential.

        Args:
            key: The credential.

        Returns:
            The headers.

        """
        ...

    # The argument count is the call's shape, not a smell: a request needs the model,
    # the prompt, the schema, the images, the ceiling, the sampling and whether the
    # tool choice may be pinned, and folding any pair into a sub-object would invent a
    # vocabulary no provider uses.
    def payload(  # pylint: disable=too-many-arguments
        self,
        *,
        model: str,
        prompt: str,
        schema: Mapping[str, object],
        images: Sequence[Any],
        ceiling: int,
        sampling: Mapping[str, Any],
        pin: bool,
    ) -> dict[str, Any]:
        """Build the request body.

        Args:
            model: The model part of the caller's name, without its prefix.
            prompt: The prompt text.
            schema: The schema the answer must satisfy.
            images: The images to attach, empty for a text call.
            ceiling: The maximum tokens to spend answering.
            sampling: The sampling parameters to forward.
            pin: Whether the provider accepts a pinned tool choice. A provider that
                does not is sent the weakest form it accepts.

        Returns:
            The body.

        """
        ...

    def read(self, body: Mapping[str, Any], headers: Mapping[str, str]) -> Answer:
        """Normalise a response.

        Args:
            body: The decoded response body.
            headers: The response headers, for the request id.

        Returns:
            The normalised answer.

        """
        ...


#: The Anthropic version header's value. Part of the *request*, so it is a
#: deliberate constant rather than something discovered at runtime.
_ANTHROPIC_VERSION: Final[str] = "2023-06-01"

#: The tool name the schema is sent under, in both dialects. One name because it is
#: one concept: the model is asked to emit the structured answer and nothing else.
_TOOL_NAME: Final[str] = "emit"

#: The tool's description, likewise shared.
_TOOL_DESCRIPTION: Final[str] = "Return the structured answer."


def _integer(value: Any) -> int | None:
    """Read a token count, keeping *unreported* distinct from *zero*.

    Args:
        value: The value the provider reported.

    Returns:
        The count, or ``None`` when the provider did not report one.

    """
    return (
        int(value) if isinstance(value, int) and not isinstance(value, bool) else None
    )


class AnthropicDialect:
    """The Anthropic Messages API, spoken natively by Anthropic.

    DeepSeek also exposes this dialect (at ``/anthropic``), which is why it is the
    **dialect** and not the *provider* that owns the format: a wire format is not
    the same thing as a vendor, and keeping them separate is what lets a second
    vendor reuse one implementation.
    """

    # `name` is a class constant but is spelled in lowercase because it satisfies the
    # `Dialect` protocol's attribute, which every dialect and every provider writes
    # the same way. UPPER_CASE here would make the protocol and its implementations
    # disagree about the attribute's name.
    name: Final[str] = "anthropic"  # pylint: disable=invalid-name

    def path(self) -> str:
        """Report the endpoint path.

        Returns:
            The Messages path.

        """
        return "/v1/messages"

    def headers(self, key: str) -> dict[str, str]:
        """Build the request headers.

        Args:
            key: The credential.

        Returns:
            The headers, with the credential in ``x-api-key``.

        """
        return {
            "x-api-key": key,
            "anthropic-version": _ANTHROPIC_VERSION,
            "content-type": "application/json",
        }

    def payload(  # pylint: disable=too-many-arguments
        self,
        *,
        model: str,
        prompt: str,
        schema: Mapping[str, object],
        images: Sequence[Any],
        ceiling: int,
        sampling: Mapping[str, Any],
        pin: bool,
    ) -> dict[str, Any]:
        """Build the Messages body.

        Args:
            model: The model part of the caller's name.
            prompt: The prompt text.
            schema: The schema the answer must satisfy.
            images: The images to attach.
            ceiling: The maximum tokens to spend answering.
            sampling: The sampling parameters to forward.
            pin: Whether the provider accepts a pinned tool choice.

        Returns:
            The body.

        """
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        content.extend(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": getattr(image, "media_type", "image/png"),
                    "data": _encode(image),
                },
            }
            for image in images
        )

        body: dict[str, Any] = {
            "model": model,
            "max_tokens": ceiling,
            "messages": [{"role": "user", "content": content}],
            "tools": [
                {
                    "name": _TOOL_NAME,
                    "description": _TOOL_DESCRIPTION,
                    "input_schema": dict(schema),
                }
            ],
        }
        body.update(sampling)

        if pin:
            body["tool_choice"] = {"type": "tool", "name": _TOOL_NAME}
        else:
            # The weakest form that still says *prefer the tool*. Measured on
            # DeepSeek: `{"type": "any"}` answers 200 where the pinned form is a
            # 400, and it produces the same `tool_use` block.
            body["tool_choice"] = {"type": "any"}

        return body

    def read(self, body: Mapping[str, Any], headers: Mapping[str, str]) -> Answer:
        """Normalise a Messages response.

        The blocks are already in this adapter's vocabulary — this dialect is the
        one that defines it — so they are passed through and only the *envelope*
        is read: the stop reason, the usage field names and the request id header.

        Args:
            body: The decoded response body.
            headers: The response headers.

        Returns:
            The normalised answer.

        """
        blocks = body.get("content")
        usage = body.get("usage") or {}

        return Answer(
            blocks=tuple(b for b in (blocks or []) if isinstance(b, Mapping)),
            stop_reason=str(body.get("stop_reason") or ""),
            prompt_tokens=_integer(usage.get("input_tokens")),
            completion_tokens=_integer(usage.get("output_tokens")),
            total_tokens=_integer(usage.get("total_tokens")),
            model=str(body["model"]) if body.get("model") else None,
            request_id=_header(headers, "request-id", "x-request-id"),
        )


class OpenAIDialect:
    """The OpenAI chat-completions API, and everything that copies it.

    One dialect covers OpenAI itself and every provider that imitates it (Groq,
    Together, OpenRouter, a local vLLM): they differ by host and credential, not by
    wire format. That is why ``PROVIDERS`` names a dialect per provider rather than
    a vendor per code path.
    """

    name: Final[str] = "openai"  # pylint: disable=invalid-name

    def path(self) -> str:
        """Report the endpoint path.

        Returns:
            The chat-completions path.

        """
        return "/v1/chat/completions"

    def headers(self, key: str) -> dict[str, str]:
        """Build the request headers.

        Args:
            key: The credential.

        Returns:
            The headers, with the credential as a bearer token.

        """
        return {
            "Authorization": f"Bearer {key}",
            "content-type": "application/json",
        }

    def payload(  # pylint: disable=too-many-arguments
        self,
        *,
        model: str,
        prompt: str,
        schema: Mapping[str, object],
        images: Sequence[Any],
        ceiling: int,
        sampling: Mapping[str, Any],
        pin: bool,
    ) -> dict[str, Any]:
        """Build the chat-completions body.

        The images ride on the **same message** as the text, as `image_url` parts
        carrying a data URL — which is this dialect's way of saying what Anthropic
        says with an `image` block. Kept in one message deliberately: splitting them
        across two turns changes what the model is answering about.

        Args:
            model: The model part of the caller's name.
            prompt: The prompt text.
            schema: The schema the answer must satisfy.
            images: The images to attach.
            ceiling: The maximum tokens to spend answering.
            sampling: The sampling parameters to forward.
            pin: Whether the provider accepts a pinned tool choice.

        Returns:
            The body.

        """
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        content.extend(
            {
                "type": "image_url",
                "image_url": {
                    "url": (
                        f"data:{getattr(image, 'media_type', 'image/png')};base64,"
                        f"{_encode(image)}"
                    )
                },
            }
            for image in images
        )

        body: dict[str, Any] = {
            "model": model,
            "max_tokens": ceiling,
            "messages": [{"role": "user", "content": content}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": _TOOL_NAME,
                        "description": _TOOL_DESCRIPTION,
                        "parameters": dict(schema),
                    },
                }
            ],
        }
        body.update(sampling)

        if pin:
            body["tool_choice"] = {"type": "function", "function": {"name": _TOOL_NAME}}
        else:
            # `"required"` is the weaker pinning form this dialect defines, and it
            # is still refused by the providers that refuse the strict one. `"auto"`
            # is what they accept, and it produces the same `tool_calls`.
            body["tool_choice"] = "auto"

        return body

    def read(self, body: Mapping[str, Any], headers: Mapping[str, str]) -> Answer:
        """Normalise a chat-completions response into this adapter's block shape.

        **This is where the dialects genuinely differ, and the difference is not
        cosmetic.** Anthropic hands back `tool_use.input` as a decoded object; this
        dialect hands back `tool_calls[0].function.arguments` as a **JSON string**,
        measured. Feeding that string straight into the block reader would make it
        look like a text answer and it would be parsed twice — so it is decoded
        *here*, and a string that will not decode becomes a text block, which the
        caller reports as `unsupported_format` rather than as a value. A malformed
        answer must never be reported as a good one.

        Args:
            body: The decoded response body.
            headers: The response headers.

        Returns:
            The normalised answer.

        """
        choices = body.get("choices")
        choice = choices[0] if isinstance(choices, list) and choices else {}
        message = choice.get("message") if isinstance(choice, Mapping) else {}
        message = message if isinstance(message, Mapping) else {}
        usage = body.get("usage") or {}

        return Answer(
            blocks=tuple(_blocks(message)),
            # `length` is this dialect's word for the ceiling; translated so the
            # truncation rule has one spelling to check. Anything else is passed
            # through, including an empty reason.
            stop_reason={
                "length": "max_tokens",
            }.get(
                str(choice.get("finish_reason") or ""),
                str(choice.get("finish_reason") or ""),
            ),
            prompt_tokens=_integer(usage.get("prompt_tokens")),
            completion_tokens=_integer(usage.get("completion_tokens")),
            total_tokens=_integer(usage.get("total_tokens")),
            model=str(body["model"]) if body.get("model") else None,
            request_id=_header(headers, "x-request-id", "request-id"),
        )


def _blocks(message: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Turn one assistant message into this adapter's content blocks.

    Args:
        message: The `message` of the first choice.

    Returns:
        The blocks, in the order the answer should be read: a tool call first, then
        any text. Tool call first because a message carrying both is answering *and*
        explaining, and the answer is the field values.

    """
    blocks: list[Mapping[str, Any]] = []

    calls = message.get("tool_calls")
    for call in calls if isinstance(calls, list) else []:
        function = (call or {}).get("function") if isinstance(call, Mapping) else {}
        function = function if isinstance(function, Mapping) else {}
        raw = function.get("arguments")

        if isinstance(raw, str):
            try:
                decoded = json.loads(raw)
            except ValueError:
                # A tool call whose arguments are not JSON is reported as **text**,
                # not as a value: the block reader then hands it to the object
                # parser, which refuses it and says so. Decoding a broken payload
                # into `{}` here would report a failed answer as an empty one.
                blocks.append({"type": "text", "text": raw})
                continue
        else:
            decoded = raw

        blocks.append({"type": "tool_use", "name": _TOOL_NAME, "input": decoded})

    text = message.get("content")
    if isinstance(text, str) and text.strip():
        blocks.append({"type": "text", "text": text})

    return blocks


def _header(headers: Mapping[str, str], *names: str) -> str | None:
    """Find the first of several header names a provider might use.

    Two names because the dialects disagree and a provider imitating one may copy
    the other's spelling. Asking for both is cheaper than discovering a missing id.

    Args:
        headers: The response headers.
        names: The candidate names, most specific first.

    Returns:
        The value, or ``None`` when none is present.

    """
    for name in names:
        value = headers.get(name)
        if value:
            return str(value)

    return None


def _encode(image: Any) -> str:
    """Encode an image into the base64 both dialects carry.

    Args:
        image: A ``Bytes`` value.

    Returns:
        The base64 string. ``Bytes`` is the port's type; anything without ``data``
        is treated as raw bytes, and ``bytes(path)`` raising is the caller's error
        rather than one this function invents a behaviour for.

    """
    import base64  # pylint: disable=import-outside-toplevel

    payload = getattr(image, "data", None)
    if payload is None:
        payload = image if isinstance(image, bytes) else bytes(image)

    return base64.b64encode(payload).decode("ascii")


@dataclass(frozen=True, slots=True)
class Provider:
    """One provider: the name, the dialect, and what it can honestly be asked.

    Attributes:
        name: The prefix a caller writes, e.g. ``deepseek:deepseek-v4-pro``.
        dialect: The wire format it speaks.
        env_key: The environment variable holding **this provider's** credential.
            Per provider because cross-provider contrast is the point of K6: `judge`
            must not be the model that produced the samples, so two credentials can
            be held at once rather than one reassigned between calls. Absent, the
            shared :data:`FALLBACK_ENV_KEY` is consulted.
        env_host: The environment variable overriding its base URL.
        default_host: Where the provider lives when nothing overrides it.
        pins_tool_choice: Whether the provider accepts a **pinned** tool choice.
            Measured, not assumed — see the module docstring.
        supports_vision: Whether it can be asked about pixels. ``False`` is a real
            answer and is **refused loudly** rather than attempted: measured,
            DeepSeek answers `"NO IMAGE"` as a value when handed an image, which is
            exactly the plausible-looking wrong answer this project exists to catch.

    """

    name: str
    dialect: Dialect
    env_key: str
    env_host: str
    default_host: str
    pins_tool_choice: bool
    supports_vision: bool

    def key_variable(self, environment: Mapping[str, str]) -> str | None:
        """Report which variable holds this provider's credential, if any.

        Args:
            environment: The environment to read.

        Returns:
            The name of the variable that holds a non-empty value, preferring this
            provider's own over the shared one, or ``None`` when neither is set.
            The **name** rather than the value, so a caller can say which variable
            it used — the value is a secret and is read here and nowhere else.

        """
        for candidate in (self.env_key, FALLBACK_ENV_KEY):
            if environment.get(candidate):
                return candidate

        return None

    def base_url(self, environment: Mapping[str, str]) -> str:
        """Report the address to call, honouring the override variable.

        Args:
            environment: The environment to read.

        Returns:
            The base URL, without a trailing slash.

        """
        return (environment.get(self.env_host) or self.default_host).rstrip("/")


#: The providers reachable from this build, keyed by the name a caller writes.
#:
#: The doubles are not decoration: **DeepSeek is reachable only because it speaks
#: the Anthropic dialect at `/anthropic`**, which is a measured fact rather than a
#: documented one, and it is the reason `deepseek` is one table entry and not a
#: third implementation of the generation path.
PROVIDERS: Final[Mapping[str, Provider]] = {
    "anthropic": Provider(
        name="anthropic",
        dialect=AnthropicDialect(),
        env_key="DOCFLOW_FRONTIER_ANTHROPIC_KEY",
        env_host="DOCFLOW_FRONTIER_ANTHROPIC_HOST",
        default_host="https://api.anthropic.com",
        pins_tool_choice=True,
        supports_vision=True,
    ),
    "deepseek": Provider(
        name="deepseek",
        dialect=AnthropicDialect(),
        env_key="DOCFLOW_FRONTIER_DEEPSEEK_KEY",
        # The `/anthropic` suffix is load-bearing and is *not* the vendor's default
        # base URL: DeepSeek's own API root serves the OpenAI dialect, and only this
        # path serves the Anthropic one. Measured: `/v1/messages` on the bare host
        # is a 404 while `/anthropic/v1/messages` answers 200.
        env_host="DOCFLOW_FRONTIER_DEEPSEEK_HOST",
        default_host="https://api.deepseek.com/anthropic",
        pins_tool_choice=False,
        supports_vision=False,
    ),
    "openai": Provider(
        name="openai",
        dialect=OpenAIDialect(),
        env_key="DOCFLOW_FRONTIER_OPENAI_KEY",
        env_host="DOCFLOW_FRONTIER_OPENAI_HOST",
        default_host="https://api.openai.com",
        pins_tool_choice=True,
        supports_vision=True,
    ),
}

#: Dialects by name, so a provider can be declared before its class is written and
#: a test can assert every provider names one that exists.
DIALECTS: Final[Mapping[str, Dialect]] = {
    dialect.name: dialect
    for dialect in {
        provider.dialect.name: provider.dialect for provider in PROVIDERS.values()
    }.values()
}


def provider_named(name: str) -> Provider | None:
    """Find a provider by the prefix a caller wrote.

    Args:
        name: The prefix.

    Returns:
        The provider, or ``None`` when no provider carries that name. ``None`` is
        the answer rather than a default: substituting a provider would make
        *there is no fallback* untrue in the one place it is asserted.

    """
    return PROVIDERS.get(name)
