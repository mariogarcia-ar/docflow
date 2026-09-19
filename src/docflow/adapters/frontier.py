"""K6 ``LlmEngine`` port adapter over a **frontier provider**, speaking its HTTP API.

The hosted-generation engine. It satisfies `LlmEngine`'s five operations —
``capabilities``, ``warm``, ``structured``, ``vision`` and ``judge`` — and the three
failures it exists to prevent are all failures of *attribution*: the answer is
available, and what is lost is the ability to say what happened.

**The raw completion is the artifact of record, and it is captured before anything
coerces it.** A parse bug and a model that returned nothing produce the same final
state — no value — and are indistinguishable once the text is gone. So the bytes come
off the wire first, are held whole, and are reported whether or not the parse succeeds
(`kernel-cli.md` §9, §11 row 14).

**Absence, ``null`` and a value are three outcomes, not two.** A model that returned
nothing, a model that returned ``null`` for a field, and a model that returned a
value are different facts about the run, and collapsing any pair of them makes the
result unattributable. ``None`` is never a stand-in for *missing*.

**A rate limit or an outage is never a rejection.** ``429`` and an unreachable host
are facts about *the provider*, and they are reported as such — with the imposed delay
recorded verbatim — rather than being collapsed into *this field is invalid*, which is
a fact about the document. Whether to wait and try again is policy, and policy is not
this kernel's (`prd.md` FR-15).

The transport is ``httpx``, spoken directly, so the response headers this adapter
depends on — ``retry-after`` above all — stay visible at the boundary instead of
behind a client library's abstraction.

What this adapter never does
----------------------------

- **No default provider, no fallback model.** A name whose prefix names no configured
  provider fails with ``provider_unknown``; a name that resolves to nothing fails with
  ``model_unknown``. Nothing resolves to a working model by accident
  (`kernel-cli.md` §8, §14).
- **No schema accepted and then not sent.** The frozen port declares
  ``vision(model, prompt, images, schema)`` — *"the same, about images"* — and
  ``kernel-cli.md`` §9 requires ``--schema-file`` on ``llm.frontier vision``. Both entry
  points therefore put the schema in the request as a forced tool call, so the answer is
  **constrained during generation** rather than parsed afterwards and hoped for. This
  was a real defect: the constraint sat behind an ``if not vision``, which made a
  `vision` call report a schema it never sent.
- **No secret in a parameter.** There is no API key on any signature. The key is read
  from the environment, so no call path can take one from a command line or a
  descriptor (`kernel-cli.md` §9, K6).
- **No retry until two answers agree.** The imposed delay is recorded and returned;
  retrying is the orchestrator's decision, made once and visibly (`kernel-cli.md` §7).
- **No aggregate confidence score.** A single number over an external model's output
  is a decision wearing a number's clothes (`prd.md`).

PoC stage
---------

Each deliberate shortcut carries a marker naming what must replace it. Two are
structural: one provider is implemented, and the transport is created per call.
"""

# Pylint reports `duplicate-code` between this module's ``_generate`` and K5's.
# The two are **not** copies: they speak different transports (Ollama's ``/api/chat``
# and this provider's ``/v1/messages``), raise different codes, read different
# response fields, and signalled truncation differently (``done_reason`` versus
# ``stop_reason``). What they share is the *shape* the frozen `LlmEngine` port
# imposes — a private generator resolving the model, refusing on a transport failure,
# refusing on a non-200, refusing on a cut, and parsing last. Reshaping either one to
# dodge the metric would make it diverge from the port it implements, which is the
# one thing both must mirror. Suppressed here, at the module the metric names second,
# rather than project-wide: the rule is useful everywhere else.
# pylint: disable=duplicate-code
# pylint: disable=too-many-lines

from __future__ import annotations

import base64
import json
import os
import re
import time
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any, Final

from docflow.adapters._json_object import JSON_ANSWER_INSTRUCTION, load_object
from docflow.adapters.frontier_providers import (
    FORWARDED_PARAMETERS,
    PROVIDERS,
    Answer,
    Provider,
    provider_named,
)
from docflow.kernels.types import CallRecord, Evidence, KernelResult, Reason

__all__: list[str] = ["ENV_HOST", "ENV_KEY", "FrontierEngine"]

# --- Reason codes, from the closed set of `kernel-cli.md` §5 -----------------

_CODE_PROVIDER_UNKNOWN: Final[str] = "provider_unknown"
_CODE_PROVIDER_UNAVAILABLE: Final[str] = "provider_unavailable"
_CODE_MODEL_UNKNOWN: Final[str] = "model_unknown"
_CODE_TRUNCATED_OUTPUT: Final[str] = "truncated_output"
_CODE_ROLE_CONFLICT: Final[str] = "role_conflict"
_CODE_UNSUPPORTED_FORMAT: Final[str] = "unsupported_format"

# --- Operational settings, read from the environment ------------------------
#
# A provider's *address* and its *credential* are both operational settings, and both
# come from the environment. The credential never becomes a parameter: a parameter
# would put a key on a command line and into a process listing (`kernel-cli.md` §9).
#
# Which variable holds them is **per provider**, and the table that says so lives in
# `frontier_providers.py` — this module asks a :class:`Provider` rather than reading a
# constant, because a second provider needs a name, a dialect, an address and a key
# variable of its own and a module-level constant can only hold one of each.

#: The shared credential variable, kept as the module-level name because the
#: kernel-CLI's availability probe imports it to know what to check. Every provider
#: consults it when its own variable is absent; see
#: `frontier_providers.FALLBACK_ENV_KEY` for why both names exist.
ENV_KEY: Final[str] = "DOCFLOW_FRONTIER_KEY"

#: The variable that overrides **anthropic's** base URL, likewise kept because the
#: probe and the docs name it. A second provider's override has a different name, and
#: the provider resolves it.
ENV_HOST: Final[str] = "DOCFLOW_FRONTIER_ANTHROPIC_HOST"

#: Kept as the private spellings the module body reads.
_ENV_KEY: Final[str] = ENV_KEY
_ENV_HOST: Final[str] = ENV_HOST

#: Where a default install points when the caller names no provider. Kept because
#: the constructor's docstring and the docs name it; a provider resolves its own
#: address from its table entry, and this is the one an unqualified name falls back
#: to. It is the *address* that is defaulted, never a model.
_DEFAULT_HOST: Final[str] = "https://api.anthropic.com"

#: A provider-prefixed model name, e.g. ``anthropic:claude-sonnet-4-6``.
_MODEL_NAME = re.compile(r"^(?P<provider>[A-Za-z0-9_-]+):(?P<model>.+)$")

#: The provider's stop reason that means the token ceiling cut the answer. Read from
#: the raw response, never inferred from the text. The dialects **translate** their
#: own spelling into this one (`OpenAIDialect` maps `length` to it), so the ceiling
#: rule has a single string to compare rather than one per vendor.
_STOP_REASON_MAX_TOKENS: Final[str] = "max_tokens"

#: The sampling parameters this adapter forwards, read from the shared vocabulary.
#: Anything else is dropped rather than refused, because the provider owns its own
#: parameter vocabulary.
_FORWARDED_PARAMETERS: Final[tuple[str, ...]] = FORWARDED_PARAMETERS

#: The provider's request header carrying the delayed-retry instruction. Recorded
#: verbatim; never reinterpreted into a different delay.
_HEADER_RETRY_AFTER: Final[str] = "retry-after"

#: How long a single call may take. A frontier call is slow, and a timeout that fires
#: mid-answer would be reported as a failed call rather than as a long one.
_TIMEOUT_SECONDS: Final[float] = 600.0


class FrontierEngine:
    """A frontier provider behind :class:`~docflow.ports.LlmEngine`.

    Reachable only through the port. The composition root imports this class; no
    module under ``docflow/ports/`` does (`ADR-004`).
    """

    def __init__(self, *, base_url: str | None = None, client: Any = None) -> None:
        """Initialise the adapter.

        Args:
            base_url: An explicit base URL for **every** provider. ``None`` lets
                each provider resolve its own address from its environment
                variable, falling back to its documented default. It is an override
                for a test or a proxy, not a provider selector: which provider is
                called is decided by the caller's model name.
            client: An HTTP client to use instead of building one. It exists so the
                tests can exercise the boundary without a live provider, and so a
                caller can supply a configured client. ``None`` means *build one*,
                never *use a default model*.

        """
        self._base_url_override = base_url.rstrip("/") if base_url else None
        self._client = client
        # The identity each model resolved to the first time this adapter saw it,
        # keyed by the full ``provider:model`` name. A hosted model can be updated
        # under a fixed name, so the same comparison the local adapter makes is
        # what makes the change visible rather than surprising.
        self._seen_revisions: dict[str, str] = {}
        self._adapter_revisions: dict[str, str] = {}
        # The record of the last call, and the last raw completion. Both are
        # per-call facts the frozen `KernelResult` cannot carry — E01 fixed its
        # three fields — so they are exposed on the adapter for the caller that
        # composes the envelope (`E07-02`). See the module's "Where the call record
        # goes" note.
        self._last_call_record: CallRecord | None = None
        self._last_raw_completion: bytes | None = None

    def _base_url_for(self, provider: Provider) -> str:
        """Report the address to call for one provider.

        Args:
            provider: The provider.

        Returns:
            The explicit override when the caller gave one, otherwise the
            provider's own resolved address.

        """
        return self._base_url_override or provider.base_url(os.environ)

    def _key_for(self, provider: Provider) -> str:
        """Read one provider's credential from the environment.

        Args:
            provider: The provider.

        Returns:
            The credential.

        Raises:
            OSError: When neither this provider's variable nor the shared one is
                set. The caller turns it into a typed reason, because *no key* and
                *a rejected key* need different remediation.

        """
        variable = provider.key_variable(os.environ)
        if variable is None:
            raise OSError(
                f"no key is configured for {provider.name!r}. Set "
                f"{provider.env_key} (or the shared {ENV_KEY}) in the environment; "
                "it is deliberately not a parameter, so it cannot arrive on a "
                "command line or in a descriptor."
            )

        return str(os.environ[variable])

    # --- The two per-call facts the envelope needs --------------------------

    @property
    def last_call_record(self) -> CallRecord | None:
        """Report what the most recent call cost and which revision answered.

        ``None`` before any call. Every call — success or typed failure — leaves a
        record, because a failed call still spent latency and still reached a
        revision, and that is what `kernel-cli.md` §7 lets a test assert for an
        ``external`` kernel.

        Returns:
            The record, or ``None`` when nothing has been called yet.

        """
        return self._last_call_record

    @property
    def last_raw_completion(self) -> bytes | None:
        """Report the most recent completion's bytes, exactly as they arrived.

        This is the artifact of record. It is captured off the wire **before** any
        parse is attempted and kept even when the parse fails, so that *the model
        returned nothing* and *the parse rejected what it returned* stay
        distinguishable (`kernel-cli.md` §11 row 14).

        Returns:
            The bytes, or ``None`` when no call has completed yet.

        """
        return self._last_raw_completion

    # --- Transport ----------------------------------------------------------

    def _http(self, provider: Provider) -> Any:
        """Return the HTTP client, building one if none was supplied.

        Built **per provider**, because the base URL is part of the client: one
        client pointed at one host cannot serve two providers, and constructing it
        per call is the shortcut this adapter already carried.

        Args:
            provider: The provider whose address the client is bound to.

        Returns:
            The client.

        """
        if self._client is not None:
            return self._client

        import httpx  # pylint: disable=import-outside-toplevel

        return httpx.Client(
            base_url=self._base_url_for(provider), timeout=_TIMEOUT_SECONDS
        )

    def _headers(self, provider: Provider) -> dict[str, str]:
        """Build the request headers for one provider, reading its credential.

        The header *names* come from the provider's dialect, which is the whole
        reason a dialect exists: ``x-api-key`` and ``Authorization: Bearer`` are the
        same fact written two ways, and the adapter should not be the place where
        somebody remembers which.

        Args:
            provider: The provider being called.

        Returns:
            The headers.

        Raises:
            OSError: When no key is configured for it. The caller turns it into a
                typed reason, because *no key* and *a rejected key* need different
                remediation.

        """
        return provider.dialect.headers(self._key_for(provider))

    def _post(self, provider: Provider, payload: Mapping[str, Any]) -> Any:
        """Send one request and return the response.

        Args:
            provider: The provider being called, which decides the address, the
                endpoint and the header names.
            payload: The JSON body.

        Returns:
            The response object.

        Raises:
            OSError: When the provider cannot be reached, or no key is configured.
                Callers turn it into a typed reason, because *the provider is down*
                and *the model answered badly* need different remediation.

        """
        headers = self._headers(provider)
        path = provider.dialect.path()
        try:
            return self._http(provider).post(path, json=dict(payload), headers=headers)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise OSError(
                f"the provider at {self._base_url_for(provider)} could not be "
                f"reached: {type(exc).__name__}: {exc}"
            ) from exc

    # --- Model identity -----------------------------------------------------

    def _split(self, model: str) -> tuple[str | None, str]:
        """Split a model name into its provider prefix and the model.

        A thin delegation to :func:`_split_model`, which is module-level so the
        self-grading guard can use it without reaching into a private member.

        Args:
            model: The name the caller used.

        Returns:
            The prefix (``None`` when the name carries none) and the model part.

        """
        return _split_model(model)

    def _runtime_revision(self, provider: Provider) -> str:
        """Report one provider's adapter revision, so the engine is a cache term.

        The provider's name and the dialect it speaks are part of every request, so
        the same call against a different provider or dialect is different work
        (`sad.md` §5). Cached **per provider**: one adapter now speaks to several, and
        a single cached string would report the first provider's revision for a call
        made to the second.

        Args:
            provider: The provider being called.

        Returns:
            The revision string.

        """
        cached = self._adapter_revisions.get(provider.name)
        if cached is None:
            cached = f"{provider.name} {provider.dialect.name}"
            self._adapter_revisions[provider.name] = cached

        return cached

    def _resolve_revision(self, name: str, revision: str) -> tuple[str, bool]:
        """Record this model's revision and compare it with the first sighting.

        A hosted model is updated under a fixed name, so *which revision answered* is
        the identity and has to be comparable across a run. The first resolution is
        remembered and every later one is checked against it.

        Args:
            name: The full ``provider:model`` name.
            revision: The revision this resolution produced.

        Returns:
            The first-seen revision and whether this resolution disagrees with it.

        """
        first = self._seen_revisions.setdefault(name, revision)

        return first, first != revision

    def _record(  # pylint: disable=too-many-arguments
        self,
        *,
        provider: Provider,
        model: str,
        revision: str,
        latency_ms: float,
        answer: Answer | None,
        request_id: str | None,
    ) -> CallRecord:
        """Build and store the call record for one call.

        Always populated (`kernel-cli.md` §9, K6). A field the provider did not
        report is ``None`` — the type says ``None`` means *unreported* — and never
        ``0``, which would read as *the provider said zero tokens*.

        **The token names are the dialect's business, not this function's.** The two
        dialects call the same two numbers different things (`input_tokens` versus
        `prompt_tokens`), and the dialect has already normalised them into an
        :class:`Answer`. Reading the raw body here is what made this function
        anthropic-shaped.

        Args:
            provider: The provider that answered.
            model: The model part of the caller's name.
            revision: The resolved revision.
            latency_ms: Wall-clock latency of the call.
            answer: The normalised answer, or ``None`` when there was none.
            request_id: The provider's request identifier, or ``None``.

        Returns:
            The record, also stored as :attr:`last_call_record`.

        """
        record = CallRecord(
            provider=provider.name,
            model=model,
            model_revision=revision,
            prompt_tokens=None if answer is None else answer.prompt_tokens,
            completion_tokens=None if answer is None else answer.completion_tokens,
            total_tokens=None if answer is None else answer.total_tokens,
            # A frontier provider meters its calls, but the *price* is a billing
            # fact this adapter does not look up: a rate card hardcoded here would
            # be a number that silently goes stale.
            cost_usd=None,  # TODO: [MVP]: read the provider's rate card
            latency_ms=round(latency_ms, 3),
            request_id=request_id,
        )
        self._last_call_record = record

        return record

    # --- Operations ---------------------------------------------------------

    def capabilities(self, model: str) -> KernelResult[Evidence]:
        """Report the provider's identity for a model, without generating.

        Args:
            model: The model as the caller named it, prefixed with its provider.

        Returns:
            The provider, the model and the adapter revision, or no value and a
            typed ``Reason``: ``provider_unknown`` when the prefix names no
            configured provider, ``model_unknown`` when the name carries no prefix
            at all. Nothing resolves to a working model by accident.

        """
        prefix, name = self._split(model)
        if prefix is None:
            return _refused(
                _CODE_MODEL_UNKNOWN,
                (
                    f"the model name {model!r} carries no provider prefix. A "
                    f"frontier model is named `<provider>:<model>`, e.g. "
                    f"{_example_name()}; no default provider is substituted."
                ),
                {},
                {},
                {"model": model, "known_providers": sorted(PROVIDERS)},
            )

        provider = provider_named(prefix)
        if provider is None:
            return _refused(
                _CODE_PROVIDER_UNKNOWN,
                (
                    f"the provider prefix {prefix!r} names no configured provider. "
                    f"This build speaks to {sorted(PROVIDERS)}; no fallback provider "
                    "is substituted."
                ),
                {},
                {},
                {"model": model, "known_providers": sorted(PROVIDERS)},
            )

        revision = self._runtime_revision(provider)
        # The revision of a *hosted* model cannot be known without asking, and
        # asking here would spend a call the caller did not request. What is known
        # is the name the caller will use and the adapter revision, and those are
        # what is reported — never an invented revision.
        capabilities = ["completion"] + (["vision"] if provider.supports_vision else [])
        return _observed(
            MappingProxyType(
                {
                    "provider": provider.name,
                    "model": name,
                    "adapter_revision": revision,
                    "model_revision": name,
                }
            ),
            {},
            {
                "model": model,
                "provider": provider.name,
                "dialect": provider.dialect.name,
                "adapter_revision": revision,
                "revision_is_resolved_on_call": True,
                "supports_vision": provider.supports_vision,
                # Whether the schema can be **pinned**, or merely requested. A
                # caller that needs the constraint to be a guarantee has to know
                # which it got, and this is the only place that says so before a
                # call is paid for.
                "pins_tool_choice": provider.pins_tool_choice,
                "capabilities": capabilities,
            },
        )

    def warm(self, model: str) -> KernelResult[Evidence]:
        """Check that a model resolves, without generating.

        A hosted provider has no cold start to avoid, so warming means *confirm the
        name resolves and the credential is present*. It is implemented because the
        port declares it, and because *the provider is reachable* is worth being
        able to check before a batch begins.

        Args:
            model: The model as the caller named it.

        Returns:
            A confirmation, or no value and a typed ``Reason``.

        """
        resolved = self.capabilities(model)
        if resolved.value is None:
            return resolved

        # The provider is re-resolved from the name rather than carried in the
        # evidence: `capabilities` answers for *several* providers now, and reaching
        # into its observed mapping for the name would be this method trusting a
        # field it did not check.
        prefix, _name = self._split(model)
        provider = provider_named(prefix or "")
        if provider is None:
            return resolved

        variable = provider.key_variable(os.environ)
        if variable is None:
            return _refused(
                _CODE_PROVIDER_UNAVAILABLE,
                (
                    f"no key is configured for {provider.name!r}, so {model!r} "
                    f"cannot be called. Set {provider.env_key} (or the shared "
                    f"{ENV_KEY}) in the environment; it is deliberately not a "
                    "parameter."
                ),
                {},
                {},
                {"model": model, "provider": provider.name, "warm": False},
            )

        revision = self._runtime_revision(provider)

        return _observed(
            MappingProxyType(
                {
                    "provider": provider.name,
                    "model": model,
                    "adapter_revision": revision,
                }
            ),
            {},
            {
                "model": model,
                "provider": provider.name,
                "key_variable": variable,
                "warm": True,
                "generation": False,
            },
        )

    def structured(
        self,
        model: str,
        prompt: str,
        schema: Mapping[str, object],
    ) -> KernelResult[Mapping[str, object]]:
        """Ask the model for a structured answer against a schema.

        Args:
            model: The model as the caller named it.
            prompt: The prompt text, exactly as it will be sent.
            schema: The schema the answer must satisfy, supplied by the caller.

        Returns:
            The parsed answer, or no value and a typed ``Reason``. The raw
            completion is captured **before** the parse and kept either way, so
            *the model returned nothing* and *the parse rejected what it returned*
            stay distinguishable.

        """
        return self._generate(model, prompt, schema, images=(), vision=False)

    def vision(
        self,
        model: str,
        prompt: str,
        images: Sequence[Any],
        schema: Mapping[str, object],
    ) -> KernelResult[Mapping[str, object]]:
        """Ask the model for a structured answer about images.

        Args:
            model: The model as the caller named it.
            prompt: The prompt text, exactly as it will be sent.
            images: The images the prompt refers to.
            schema: The schema the answer must satisfy, supplied by the caller.

        Returns:
            The parsed answer, or no value and a typed ``Reason``, with the same
            raw-capture and absence rules as ``structured``.

        """
        return self._generate(model, prompt, schema, images=images, vision=True)

    def judge(
        self,
        model: str,
        rubric: str,
        samples: Sequence[Mapping[str, object]],
        produced_by: str,
    ) -> KernelResult[Mapping[str, object]]:
        """Grade samples against a rubric.

        Args:
            model: The model as the caller named it, in the grading role.
            rubric: The grading criteria, supplied by the caller.
            samples: The samples to grade.
            produced_by: The model that produced the samples.

        Returns:
            The grades, or no value and a typed ``Reason``. Grading one's own output
            reports ``role_conflict``: the labeller role must not share a run with
            the governor role, because a model grading its own output measures its
            own habits rather than the answer's correctness (§11 row 15).

        """
        if produced_by and _same_model(model, produced_by):
            return _refused(
                _CODE_ROLE_CONFLICT,
                (
                    f"{model!r} is asked to grade samples it produced itself. The "
                    "labeller role must not share a run with the governor role: a "
                    "model grading its own output measures its own habits rather "
                    "than the answer's correctness."
                ),
                {},
                {},
                {"model": model, "produced_by": produced_by},
            )

        # The answer's shape is asked for in words, not only in the schema, and the
        # measurement is why. The schema reaches the provider as a tool definition,
        # and a provider that does not *choose* to call the tool answers in prose
        # instead — measured against DeepSeek with the empty schema below: 1138
        # completion tokens of reasoning, a text block explaining that no source
        # document was supplied, and no `tool_use` block at all. That is reported
        # `unsupported_format` with 5850 bytes of raw completion preserved, and it
        # is *this adapter's* request that produced it: a rubric that asks for a
        # judgement and never says the judgement is JSON leaves the model free to
        # send it as prose.
        #
        # The measurement also shows that the empty schema is **not** the cause, so
        # it is not the fix: `structured(..., {"type": "object"})` returns a value
        # when the prompt names the shape, and a 23-property schema returns
        # `unsupported_format` when the prompt does not. The schema constrains an
        # answer that is already JSON; only the prompt decides that it is JSON.
        payload = (
            f"{rubric}\n\n"
            f"{JSON_ANSWER_INSTRUCTION}\n\n"
            f"{json.dumps(list(samples), ensure_ascii=False)}"
        )

        return self.structured(model, payload, {"type": "object"})

    # --- The shared generation path -----------------------------------------

    # The local count is high because the order is deliberate: resolve the name,
    # build the body, call, capture the raw bytes, then parse. The capture has to
    # precede the parse, and the classification has several genuinely distinct
    # outcomes — a transport failure, a rate limit, an unknown model, a server error,
    # an unparseable body, a cut generation, an absence, a `null`, and a value. Each
    # needs its own typed answer, and folding any pair together would make two facts
    # of the run indistinguishable. Splitting it would separate the capture from the
    # parse, which is the one ordering this function exists to guarantee.
    # pylint: disable=too-many-locals,too-many-return-statements,too-many-branches
    # pylint: disable=too-many-statements
    def _generate(
        self,
        model: str,
        prompt: str,
        schema: Mapping[str, object],
        *,
        images: Sequence[Any],
        vision: bool,
    ) -> KernelResult[Mapping[str, object]]:
        """Execute one generation and apply the capture-before-parse rule.

        Args:
            model: The model as the caller named it.
            prompt: The prompt text.
            schema: The schema the answer must satisfy.
            images: The images to attach, empty for a text call.
            vision: Whether this is a vision call, for the evidence.

        Returns:
            The parsed answer, or no value and a typed ``Reason``.

        """
        resolved = self.capabilities(model)
        if resolved.value is None:
            return _refused(
                resolved.reason.code if resolved.reason else _CODE_MODEL_UNKNOWN,
                resolved.reason.message if resolved.reason else "",
                {},
                {},
                {"model": model},
            )

        prefix, name = self._split(model)
        provider = provider_named(prefix or "")
        if provider is None:
            # Unreachable through `capabilities`, which refused above — but the
            # provider is *dereferenced* below, so the guard is here rather than
            # relying on a caller having run first.
            return _refused(
                _CODE_PROVIDER_UNKNOWN,
                f"the provider prefix {prefix!r} names no configured provider.",
                {},
                {},
                {"model": model, "known_providers": sorted(PROVIDERS)},
            )

        # **A provider that cannot read pixels is refused, not tried.** This is the
        # difference between a typed answer and a plausible one: measured, DeepSeek
        # accepts the image, ignores it, and answers `"NO IMAGE"` as a **value** with
        # `stop_reason: end_turn`. Nothing downstream could tell that from a real
        # reading, which is exactly the silent failure this project exists to catch —
        # so the refusal lives here, where the fact is known before the call is paid
        # for.
        if images and not provider.supports_vision:
            return _refused(
                _CODE_UNSUPPORTED_FORMAT,
                (
                    f"{provider.name!r} cannot be asked about images. Sending one "
                    "would not fail: measured, it accepts the request, ignores the "
                    "pixels and answers as if the document were blank, which is a "
                    "plausible-looking wrong answer rather than an error. Use a "
                    "provider that declares vision, or send the text instead."
                ),
                {},
                {},
                {
                    "model": model,
                    "provider": provider.name,
                    "image_count": len(images),
                    "supports_vision": False,
                },
            )

        revision = self._runtime_revision(provider)

        # The ceiling is a policy decision this kernel refuses to supply, so a
        # missing one is a precondition failure rather than a crash. It is a typed
        # reason for the same purpose as the others: a caller must be able to tell
        # *the call could not legitimately be made* from *the document answered*.
        try:
            ceiling = _max_tokens()
        except OSError as exc:
            return _refused(
                _CODE_PROVIDER_UNAVAILABLE, str(exc), {}, {}, {"model": model}
            )

        # The dialect builds the body, and that is what makes the schema a
        # *constraint* rather than a hope in both wire formats. The long note below
        # is kept because it records why the schema is sent for **both** entry
        # points, which was a real defect:
        #
        # this block used to sit behind `if not vision`, so a `vision` call accepted
        # a schema, echoed it back in `observed.declared_schema`, and **never sent
        # it**. The constraint silently degraded into a hope that the model would
        # format its own answer as JSON. Measured with the schema withheld, against
        # `{total: integer}`: a `tool_use` block parsed and a text block that
        # happened to contain JSON also parsed — so the defect is invisible whenever
        # the model cooperates — while prose (*"El total es 7 pesos."*) and a JSON
        # code fence both returned `unsupported_format`. That is a failure of **this
        # adapter's parsing** reported against the provider.
        #
        # Whether the choice can be *pinned* is the provider's answer, not this
        # function's: DeepSeek refuses every pinning form with HTTP 400 on both
        # endpoints it exposes ("Thinking mode does not support this tool_choice"),
        # so it is sent the weakest form it accepts. What was actually sent is
        # recorded below, because *enforced* and *requested* are different facts.
        body = provider.dialect.payload(
            model=name,
            prompt=prompt,
            schema=schema,
            images=images,
            ceiling=ceiling,
            sampling=_sampling_parameters(),
            pin=provider.pins_tool_choice,
        )

        started = time.monotonic()
        try:
            response = self._post(provider, body)
        except OSError as exc:
            self._record(
                provider=provider,
                model=name,
                revision=revision,
                latency_ms=(time.monotonic() - started) * 1000,
                answer=None,
                request_id=None,
            )
            self._last_raw_completion = None

            return _refused(
                _CODE_PROVIDER_UNAVAILABLE,
                str(exc),
                _unresolved_terms(model, name, revision),
                {},
                {"model": model, "provider": provider.name, "vision": vision},
            )

        latency = (time.monotonic() - started) * 1000
        headers = getattr(response, "headers", {}) or {}
        request_id = _header_from(headers)

        # --- The rate limit and the outage are facts about the provider --------
        if response.status_code == 429:
            retry_after = headers.get(_HEADER_RETRY_AFTER)
            self._record(
                provider=provider,
                model=name,
                revision=revision,
                latency_ms=latency,
                answer=None,
                request_id=request_id,
            )
            self._last_raw_completion = _raw_bytes(response)

            return _refused(
                _CODE_PROVIDER_UNAVAILABLE,
                (
                    "the provider rate-limited the call (HTTP 429). It asked for a "
                    f"delay of {retry_after!r} before another attempt; that value is "
                    "recorded verbatim rather than reinterpreted, and retrying is "
                    "the caller's decision, never this kernel's."
                ),
                _unresolved_terms(model, name, revision),
                {},
                {
                    "model": model,
                    "provider": provider.name,
                    "http_status": 429,
                    "retry_after": retry_after,
                    "vision": vision,
                },
            )

        if response.status_code == 404:
            self._record(
                provider=provider,
                model=name,
                revision=revision,
                latency_ms=latency,
                answer=None,
                request_id=request_id,
            )
            self._last_raw_completion = _raw_bytes(response)

            return _refused(
                _CODE_MODEL_UNKNOWN,
                (
                    f"the provider does not know the model {name!r} (HTTP 404). No "
                    "default is substituted; check the name or the provider's model "
                    "list."
                ),
                _unresolved_terms(model, name, revision),
                {},
                {
                    "model": model,
                    "provider": provider.name,
                    "http_status": 404,
                },
            )

        if response.status_code != 200:
            self._record(
                provider=provider,
                model=name,
                revision=revision,
                latency_ms=latency,
                answer=None,
                request_id=request_id,
            )
            self._last_raw_completion = _raw_bytes(response)

            # The provider's own words are quoted, because a 400 is almost always a
            # fact about **this request** rather than about the provider's health —
            # and the generic sentence used to say the opposite. Measured on
            # DeepSeek: the pinned tool choice is a 400 whose body explains itself
            # ("Thinking mode does not support this tool_choice"), and reporting
            # that as *the provider is unavailable* sends a reader to check a status
            # page for a bug in the request.
            detail = _provider_complaint(response)
            return _refused(
                _CODE_PROVIDER_UNAVAILABLE,
                (
                    f"the provider answered HTTP {response.status_code} for "
                    f"{name!r}: {detail} A 4xx is a fact about this request rather "
                    "than about the provider's health; a 5xx is the provider's."
                ),
                _unresolved_terms(model, name, revision),
                {},
                {
                    "model": model,
                    "provider": provider.name,
                    "http_status": response.status_code,
                },
            )

        # --- The raw completion, captured BEFORE anything coerces it ----------
        #
        # This is the invariant of §11 row 14. The bytes come off the wire and are
        # held whole and unparsed; every branch below sees them already preserved,
        # so a parse failure cannot destroy the only record of what arrived.
        self._last_raw_completion = _raw_bytes(response)

        # A 200 whose body is not JSON — a captive portal, an intercepting proxy, a
        # truncated response — is a fact about *the provider's answer*, not about the
        # document, and it must not escape as an exception. Without this guard the
        # adapter raised `ValueError` out of the caller's stack, which is precisely
        # the "unhandled failure" this issue exists to replace with a typed one.
        try:
            parsed_body = response.json()
        except ValueError:
            self._record(
                provider=provider,
                model=name,
                revision=revision,
                latency_ms=latency,
                answer=None,
                request_id=request_id,
            )

            return _refused(
                _CODE_UNSUPPORTED_FORMAT,
                (
                    f"the provider answered HTTP 200 with a body that is not JSON "
                    f"({len(self._last_raw_completion or b'')} bytes preserved), so "
                    "no answer could be read. This is a fact about the provider's "
                    "response rather than about the document."
                ),
                _unresolved_terms(model, name, revision),
                {},
                {
                    "model": model,
                    "provider": provider.name,
                    "http_status": 200,
                    "body_is_json": False,
                },
            )

        # The dialect normalises the response — including the request id header,
        # whose name the two formats disagree about — and the rest of this method
        # reads one shape.
        answer = provider.dialect.read(
            parsed_body if isinstance(parsed_body, Mapping) else {},
            headers,
        )
        resolved_revision = answer.model or name
        first, changed = self._resolve_revision(model, resolved_revision)

        record = self._record(
            provider=provider,
            model=name,
            revision=resolved_revision,
            latency_ms=latency,
            answer=answer,
            request_id=answer.request_id,
        )

        stop_reason = answer.stop_reason
        measurements = {
            "prompt_tokens": float(record.prompt_tokens or 0),
            "completion_tokens": float(record.completion_tokens or 0),
            "latency_ms": record.latency_ms,
        }
        observed: dict[str, object] = {
            "model": model,
            "provider": provider.name,
            "dialect": provider.dialect.name,
            "model_revision": resolved_revision,
            "adapter_revision": revision,
            "first_seen_revision": first,
            "revision_changed": changed,
            "stop_reason": stop_reason,
            "http_status": 200,
            "request_id": record.request_id,
            "raw_completion_bytes": float(len(self._last_raw_completion or b"")),
            "vision": vision,
            "attempts": 1,
            # Whether the schema could be pinned on this provider. *Enforced* and
            # *requested* are different facts, and a caller comparing two runs has
            # to be able to tell which one it got.
            "pins_tool_choice": provider.pins_tool_choice,
        }

        if stop_reason == _STOP_REASON_MAX_TOKENS:
            return _refused(
                _CODE_TRUNCATED_OUTPUT,
                (
                    "the generation was cut by the token ceiling "
                    f"(stop_reason={stop_reason!r}), so the answer is incomplete. It "
                    "is reported as truncated rather than parsed: a cut that lands "
                    "after the last complete field parses cleanly, which is how a "
                    "partial answer is mistaken for a whole one."
                ),
                _terms(model, resolved_revision, revision),
                measurements,
                observed,
            )

        # --- Absence, `null` and a value are three outcomes -------------------
        #
        # **The normalised blocks are what is parsed, never the raw body.** The two
        # dialects disagree about where the answer lives and what shape it is in
        # (Anthropic's `tool_use.input` is an object, OpenAI's
        # `tool_calls[0].function.arguments` is a JSON *string*), and the dialect has
        # already reduced both to the block vocabulary this function reads. Parsing
        # `parsed_body` here is what kept this parser anthropic-shaped.
        #
        # The local name is `payload` because `answer` is the :class:`Answer` above,
        # and shadowing it would make the line below read as if the same object were
        # being parsed twice.
        payload, outcome = _extract_answer({"content": list(answer.blocks)})
        observed["outcome"] = outcome
        observed["declared_schema"] = dict(schema)
        # Whether the text was ever handed to a parser. This is row 14's invariant in
        # observable form: *the model said nothing* and *the model said something
        # that would not parse* are different facts, and without this they differ
        # only in a sentence nobody may assert on.
        observed["parse_attempted"] = outcome == "value"

        if outcome == "absent":
            return _refused(
                _CODE_UNSUPPORTED_FORMAT,
                (
                    "the model returned no content at all. This is reported as an "
                    "absence and is never collapsed into `null`: *the model said "
                    "nothing* and *the model said nothing for this field* are "
                    "different facts about the run."
                ),
                _terms(model, resolved_revision, revision),
                measurements,
                observed,
            )

        if outcome == "null":
            return KernelResult(
                value=MappingProxyType({"value": None}),
                evidence=_evidence(
                    _terms(model, resolved_revision, revision), measurements, observed
                ),
                reason=None,
            )

        # The object check is shared with K5: two vendors, one rule. What differs —
        # the codes, the terms, the measurements — stays here.
        observed["parse_attempted"] = True
        parsed, problem = load_object(payload)
        if problem is not None:
            return _refused(
                _CODE_UNSUPPORTED_FORMAT,
                f"{problem} The raw completion is preserved "
                f"({len(self._last_raw_completion or b'')} bytes).",
                _terms(model, resolved_revision, revision),
                measurements,
                observed,
            )

        return KernelResult(
            value=MappingProxyType(parsed or {}),
            evidence=_evidence(
                _terms(model, resolved_revision, revision), measurements, observed
            ),
            reason=None,
        )


# --- Settings ----------------------------------------------------------------


def _max_tokens() -> int:
    """Read the response ceiling from the environment.

    Returns:
        The ceiling in tokens.

    Raises:
        OSError: When it is not configured. A default here would be this kernel
            choosing how much answer to buy, which is a policy decision and a
            threshold (`prd.md` FR-15).

    """
    raw = os.environ.get("DOCFLOW_FRONTIER_MAX_TOKENS")
    if raw is None:
        raise OSError(
            "DOCFLOW_FRONTIER_MAX_TOKENS is not set. The response ceiling is a "
            "policy decision, and this kernel does not supply one: a default here "
            "would decide how much answer the caller bought."
        )

    try:
        return int(raw)
    except ValueError as exc:
        raise OSError(
            f"DOCFLOW_FRONTIER_MAX_TOKENS is not an integer: {raw!r}"
        ) from exc


def _sampling_parameters() -> dict[str, Any]:
    """Read the sampling parameters the environment declares.

    The names come from the **shared vocabulary** in `frontier_providers.py`, which
    every dialect forwards verbatim. The two wire formats agree on `temperature`,
    `top_p` and `seed`; a name only one of them understands would be dropped by the
    other rather than renamed, because renaming it here would be this adapter
    inventing a parameter for a vendor that never declared one.

    Returns:
        The parameters to forward, possibly empty. The provider's own defaults apply
        to everything else, because inventing a parameter would be this adapter
        choosing a behaviour the caller did not ask for.

    """
    parameters: dict[str, Any] = {}
    for name in _FORWARDED_PARAMETERS:
        raw = os.environ.get(f"DOCFLOW_FRONTIER_{name.upper()}")
        if raw is None:
            continue
        try:
            parameters[name] = float(raw) if "." in raw else int(raw)
        except ValueError:
            # A malformed setting is ignored rather than fatal: the alternative is
            # a provider that cannot be used at all because of a typo in an optional
            # tuning value. It is not a model, an engine or a threshold, so reading
            # nothing is a safe outcome.
            continue

    return parameters


# --- Response reading --------------------------------------------------------


def _example_name() -> str:
    """Report a model name that would be accepted, for a refusal's message.

    Built from the table rather than written as a literal, so the example cannot go
    stale when the providers change. A refusal that names a provider this build no
    longer speaks to is worse than no example.

    Returns:
        A ``<provider>:<model>`` name using the first provider in the table.

    """
    first = next(iter(PROVIDERS.values()))

    return f"{first.name}:claude-sonnet-4-6"


def _header_from(headers: Mapping[str, Any]) -> str | None:
    """Read the request id out of a response, trying both dialects' names.

    Two names because the formats disagree and a provider imitating one may copy the
    other's spelling; asking for both is cheaper than discovering a missing id. The
    value is *not* recorded through the dialect, because a failure branch reads it
    before a dialect has had the body to normalise.

    Args:
        headers: The response headers.

    Returns:
        The id, or ``None`` when neither name is present.

    """
    for name in ("request-id", "x-request-id"):
        value = headers.get(name)
        if value:
            return str(value)

    return None


def _provider_complaint(response: Any) -> str:
    """Quote what a provider said about a request it refused.

    A 4xx is a fact about **this request**, and the provider almost always says
    which — measured on DeepSeek, a pinned tool choice is a 400 whose body reads
    *"Thinking mode does not support this tool_choice"*. Reporting that as *the
    provider is unavailable* sends a reader to check a status page for a bug in the
    request, which is the attribution failure this function exists to prevent.

    The text is quoted, **never parsed**: it is a provider's prose, its shape is not
    a contract, and a parser here would be one more thing to keep in step with four
    vendors.

    Args:
        response: The response object.

    Returns:
        The provider's own words, truncated, or a note that it said nothing
        readable. Never an empty string: a caller must be able to tell *it explained
        itself* from *it did not*.

    """
    raw = _raw_bytes(response)
    if not raw:
        return "(the provider sent no readable body)"

    text = " ".join(raw.decode("utf-8", errors="replace").split())

    return f"{text[:300]}" if text else "(the provider sent an empty body)"


def _raw_bytes(response: Any) -> bytes | None:
    """Return the response body's bytes, exactly as they arrived.

    Args:
        response: The response object.

    Returns:
        The body as bytes, or ``None`` when it could not be read.

    """
    content = getattr(response, "content", None)
    if isinstance(content, (bytes, bytearray)):
        return bytes(content)

    text = getattr(response, "text", None)
    if isinstance(text, str):
        return text.encode("utf-8")

    return None


def _extract_answer(body: Mapping[str, Any]) -> tuple[str, str]:
    """Read the model's answer, distinguishing absence from ``null`` from a value.

    The three outcomes are the point (`kernel-cli.md` §11 row 14): a model that said
    nothing, a model that said ``null`` for a field, and a model that said a value
    are different facts, and collapsing any pair makes the result unattributable.

    Args:
        body: The response body.

    Returns:
        The answer text and one of ``"absent"``, ``"null"`` or ``"value"``.

    """
    blocks = body.get("content")
    if not isinstance(blocks, list) or not blocks:
        return "", "absent"

    for block in blocks:
        outcome = _classify_block(block)
        if outcome is not None:
            return outcome

    return "", "absent"


# The count is high because this function *is* a case analysis: a block is not a
# mapping, not a tool call, a tool call with no payload, a tool call with one, not a
# text block, a text block with no text, an empty one, or one with text. Each case has
# its own answer, and folding any pair together would collapse two of the three
# outcomes `kernel-cli.md` §11 row 14 requires to stay apart.
# pylint: disable=too-many-return-statements
def _classify_block(block: Any) -> tuple[str, str] | None:
    """Classify one content block, or report that it says nothing usable.

    Args:
        block: One entry of the response's ``content`` list.

    Returns:
        The answer and its outcome, or ``None`` when the block is not one this
        adapter reads and the caller should look at the next one.

    """
    if not isinstance(block, dict):
        return None

    if block.get("type") == "tool_use":
        payload = block.get("input")
        if payload is None:
            return "", "null"

        return json.dumps(payload, ensure_ascii=False), "value"

    if block.get("type") != "text":
        return None

    text = block.get("text")
    if text is None:
        return "", "null"
    if isinstance(text, str) and not text.strip():
        return "", "absent"

    return str(text), "value"


def _same_model(left: str, right: str) -> bool:
    """Report whether two model names denote the same model.

    The provider prefix is ignored, so ``anthropic:x`` and ``x`` are the same model
    to the runtime; a self-grading guard that missed that would be defeated by a
    prefix.

    Args:
        left: One model name.
        right: The other.

    Returns:
        ``True`` when the unprefixed names match.

    """
    return _split_model(left)[1].strip() == _split_model(right)[1].strip()


def _split_model(model: str) -> tuple[str | None, str]:
    """Split a model name into its provider prefix and the model.

    Module-level rather than a method so the self-grading guard can use it without
    reaching into a private member of the class.

    Args:
        model: The name the caller used, e.g. ``anthropic:claude-sonnet-4-6``.

    Returns:
        The prefix (``None`` when the name carries none) and the model part.

    """
    match = _MODEL_NAME.match(model.strip())
    if match is None:
        return None, model.strip()

    return match.group("provider"), match.group("model")


def _encode_image(image: Any) -> str:
    """Encode one image as base64.

    Args:
        image: A ``Bytes``-like object with ``data``, or raw bytes.

    Returns:
        The base64 string.

    """
    payload = getattr(image, "data", None)
    if payload is None:
        payload = image if isinstance(image, bytes) else bytes(image)

    return base64.b64encode(payload).decode("ascii")


def _terms(model: str, revision: str, adapter_revision: str) -> Mapping[str, str]:
    """Report the cache-key terms for one model.

    Args:
        model: The name the caller used.
        revision: The resolved model revision. When the provider never answered, the
            caller passes :func:`_unresolved_terms` instead — the model revision is
            then genuinely unknown, and this function is not the place to guess it.
        adapter_revision: The adapter's revision.

    Returns:
        The terms. ``model_revision`` is the identity; the name is recorded beside
        it so an operator can see which name produced the run.

    """
    return MappingProxyType(
        {
            "provider": _provider_of(model),
            "model": model,
            "model_revision": revision,
            "adapter_revision": adapter_revision,
        }
    )


def _unresolved_terms(
    model: str, name: str, adapter_revision: str
) -> Mapping[str, str]:
    """Report the terms for a call that never reached a resolved model.

    A rate limit, an outage and a rejected credential all happen **before** the
    provider says which model revision answered, so no revision exists to report.
    Substituting the model's *name* would be exactly the mistake this issue exists to
    prevent — a name is not a revision, and a hosted model is updated under a fixed
    name — so the term says ``"unresolved"`` and the caller can see that the identity
    was never established rather than reading a name as one.

    Args:
        model: The name the caller used, prefix included.
        name: The model part, which is what a request would carry.
        adapter_revision: The adapter's revision, which *is* known — it is a fact
            about this adapter rather than about the provider's answer.

    Returns:
        The terms, with the model revision explicitly unresolved.

    """
    return MappingProxyType(
        {
            "provider": _provider_of(model),
            "model": model,
            "model_name": name,
            "model_revision": "unresolved",
            "adapter_revision": adapter_revision,
        }
    )


def _provider_of(model: str) -> str:
    """Report the provider a caller's model name names.

    Read from the prefix rather than threaded through every caller: the terms are
    built on paths that never resolved a provider (a transport failure, a refused
    credential) and the prefix is the only fact available there. An unprefixed name
    reports an empty string, which is honest — *no provider was named* — rather than
    a guessed one.

    Args:
        model: The name the caller used.

    Returns:
        The provider name, or ``""`` when the name carries no prefix.

    """
    prefix, _name = _split_model(model)

    return prefix or ""


def _evidence(
    terms: Mapping[str, str],
    measurements: Mapping[str, float],
    observed: Mapping[str, object],
) -> Evidence:
    """Build an evidence record.

    Args:
        terms: The cache-key terms.
        measurements: The numeric measurements.
        observed: The remaining observations.

    Returns:
        The assembled ``Evidence``.

    """
    return Evidence(
        terms=MappingProxyType(dict(terms)),
        measurements=MappingProxyType(dict(measurements)),
        observed=MappingProxyType(dict(observed)),
    )


def _observed(
    terms: Mapping[str, str],
    measurements: Mapping[str, float],
    observed: Mapping[str, object],
) -> KernelResult[Evidence]:
    """Build an ``Evidence``-valued result.

    Args:
        terms: The cache-key terms.
        measurements: The numeric measurements.
        observed: The remaining observations.

    Returns:
        The result, carrying no reason.

    """
    return KernelResult(
        value=_evidence(terms, measurements, observed),
        evidence=_evidence(terms, measurements, observed),
        reason=None,
    )


def _refused(
    code: str,
    message: str,
    terms: Mapping[str, str],
    measurements: Mapping[str, float],
    observed: Mapping[str, object],
) -> KernelResult[Any]:
    """Build a typed refusal.

    Args:
        code: A code from the closed set of `kernel-cli.md` §5.
        message: The human-readable explanation.
        terms: The cache-key terms.
        measurements: The numeric measurements.
        observed: The remaining observations.

    Returns:
        The result, carrying no value and a ``Reason``.

    """
    return KernelResult(
        value=None,
        evidence=_evidence(terms, measurements, observed),
        reason=Reason(code=code, message=message),
    )
