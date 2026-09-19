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

from docflow.adapters._json_object import load_object
from docflow.kernels.types import CallRecord, Evidence, KernelResult, Reason

__all__: list[str] = ["FrontierEngine"]

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

#: The environment variable naming the provider's base URL.
_ENV_HOST: Final[str] = "DOCFLOW_FRONTIER_HOST"

#: The environment variable holding the API key. Read here and nowhere else.
_ENV_KEY: Final[str] = "DOCFLOW_FRONTIER_KEY"

#: The provider this adapter speaks to. One provider in Stage 1 (`# TODO: [MVP]`:
#: a second provider, batch API, token counting).
_PROVIDER: Final[str] = "anthropic"

#: Where a default install points. It is the *address* that is defaulted, never a
#: model: a wrong address fails loudly, while a substituted model would not.
_DEFAULT_HOST: Final[str] = "https://api.anthropic.com"

#: The provider's API version header value. It is part of the *request*, so it is a
#: deliberate constant rather than something discovered at runtime.
_API_VERSION: Final[str] = "2023-06-01"

#: How long a single call may take. A frontier call is slow, and a timeout that fires
#: mid-answer would be reported as a failed call rather than as a long one.
_TIMEOUT_SECONDS: Final[float] = 600.0

#: The endpoints this adapter uses.
_PATH_MESSAGES: Final[str] = "/v1/messages"
_PATH_MODELS: Final[str] = "/v1/models"

#: A provider-prefixed model name, e.g. ``anthropic:claude-sonnet-4-6``.
_MODEL_NAME = re.compile(r"^(?P<provider>[A-Za-z0-9_-]+):(?P<model>.+)$")

#: The provider's stop reason that means the token ceiling cut the answer. Read from
#: the raw response, never inferred from the text.
_STOP_REASON_MAX_TOKENS: Final[str] = "max_tokens"

#: The sampling parameters this adapter forwards. Anything else is dropped rather
#: than refused, because the provider owns its own parameter vocabulary.
_FORWARDED_PARAMETERS: Final[tuple[str, ...]] = ("temperature", "top_p", "top_k")

#: The provider's request header carrying the delayed-retry instruction. Recorded
#: verbatim; never reinterpreted into a different delay.
_HEADER_RETRY_AFTER: Final[str] = "retry-after"


class FrontierEngine:
    """A frontier provider behind :class:`~docflow.ports.LlmEngine`.

    Reachable only through the port. The composition root imports this class; no
    module under ``docflow/ports/`` does (`ADR-004`).
    """

    def __init__(self, *, base_url: str | None = None, client: Any = None) -> None:
        """Initialise the adapter.

        Args:
            base_url: The provider's base URL. ``None`` reads :data:`_ENV_HOST` and
                falls back to the default address.
            client: An HTTP client to use instead of building one. It exists so the
                tests can exercise the boundary without a live provider, and so a
                caller can supply a configured client. ``None`` means *build one*,
                never *use a default model*.

        """
        self._base_url = (
            base_url or os.environ.get(_ENV_HOST) or _DEFAULT_HOST
        ).rstrip("/")
        self._client = client
        # The identity each model resolved to the first time this adapter saw it,
        # keyed by the full ``provider:model`` name. A hosted model can be updated
        # under a fixed name, so the same comparison the local adapter makes is
        # what makes the change visible rather than surprising.
        self._seen_revisions: dict[str, str] = {}
        self._adapter_revision: str | None = None
        # The record of the last call, and the last raw completion. Both are
        # per-call facts the frozen `KernelResult` cannot carry — E01 fixed its
        # three fields — so they are exposed on the adapter for the caller that
        # composes the envelope (`E07-02`). See the module's "Where the call record
        # goes" note.
        self._last_call_record: CallRecord | None = None
        self._last_raw_completion: bytes | None = None

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

    def _http(self) -> Any:
        """Return the HTTP client, building one if none was supplied.

        Returns:
            The client.

        """
        if self._client is not None:
            return self._client

        import httpx  # pylint: disable=import-outside-toplevel

        self._client = httpx.Client(base_url=self._base_url, timeout=_TIMEOUT_SECONDS)

        return self._client

    def _headers(self) -> dict[str, str]:
        """Build the request headers, reading the credential from the environment.

        Returns:
            The headers.

        Raises:
            OSError: When no key is configured. The caller turns it into a typed
                reason, because *no key* and *a rejected key* need different
                remediation.

        """
        key = os.environ.get(_ENV_KEY)
        if not key:
            raise OSError(
                f"no provider key is configured. Set {_ENV_KEY} in the environment; "
                "it is deliberately not a parameter, so it cannot arrive on a "
                "command line or in a descriptor."
            )

        return {
            "x-api-key": key,
            "anthropic-version": _API_VERSION,
            "content-type": "application/json",
        }

    def _post(self, path: str, payload: Mapping[str, Any]) -> Any:
        """Send one request and return the response.

        Args:
            path: The endpoint path.
            payload: The JSON body.

        Returns:
            The response object.

        Raises:
            OSError: When the provider cannot be reached, or no key is configured.
                Callers turn it into a typed reason, because *the provider is down*
                and *the model answered badly* need different remediation.

        """
        headers = self._headers()
        try:
            return self._http().post(path, json=dict(payload), headers=headers)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise OSError(
                f"the provider at {self._base_url} could not be reached: "
                f"{type(exc).__name__}: {exc}"
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

    def _runtime_revision(self) -> str:
        """Report the adapter's revision, so the engine is a cache term.

        The provider's API version is part of every request, so the same call
        against a different version is different work (`sad.md` §5). Read once.

        Returns:
            The revision string.

        """
        if self._adapter_revision is None:
            self._adapter_revision = f"{_PROVIDER} {_API_VERSION}"

        return self._adapter_revision

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
        model: str,
        revision: str,
        latency_ms: float,
        body: Mapping[str, Any] | None,
        request_id: str | None,
    ) -> CallRecord:
        """Build and store the call record for one call.

        Always populated (`kernel-cli.md` §9, K6). A field the provider did not
        report is ``None`` — the type says ``None`` means *unreported* — and never
        ``0``, which would read as *the provider said zero tokens*.

        Args:
            name: The full ``provider:model`` name.
            model: The model part.
            revision: The resolved revision.
            latency_ms: Wall-clock latency of the call.
            body: The response body, or ``None`` when there was none.
            request_id: The provider's request identifier, or ``None``.

        Returns:
            The record, also stored as :attr:`last_call_record`.

        """
        usage = dict((body or {}).get("usage") or {})
        prompt = usage.get("input_tokens")
        completion = usage.get("output_tokens")
        total = usage.get("total_tokens")

        record = CallRecord(
            provider=_PROVIDER,
            model=model,
            model_revision=revision,
            prompt_tokens=int(prompt) if isinstance(prompt, int) else None,
            completion_tokens=int(completion) if isinstance(completion, int) else None,
            total_tokens=int(total) if isinstance(total, int) else None,
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
                    f"{_PROVIDER}:claude-sonnet-4-6; no default provider is "
                    "substituted."
                ),
                {},
                {},
                {"model": model, "known_providers": [_PROVIDER]},
            )
        if prefix != _PROVIDER:
            return _refused(
                _CODE_PROVIDER_UNKNOWN,
                (
                    f"the provider prefix {prefix!r} names no configured provider. "
                    f"This build speaks to {_PROVIDER!r}; no fallback provider is "
                    "substituted."
                ),
                {},
                {},
                {"model": model, "known_providers": [_PROVIDER]},
            )

        revision = self._runtime_revision()
        # The revision of a *hosted* model cannot be known without asking, and
        # asking here would spend a call the caller did not request. What is known
        # is the name the caller will use and the adapter revision, and those are
        # what is reported — never an invented revision.
        return _observed(
            MappingProxyType(
                {
                    "provider": _PROVIDER,
                    "model": name,
                    "adapter_revision": revision,
                    "model_revision": name,
                }
            ),
            {},
            {
                "model": model,
                "provider": _PROVIDER,
                "adapter_revision": revision,
                "revision_is_resolved_on_call": True,
                "supports_vision": True,
                "capabilities": ["completion", "vision"],
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

        if not os.environ.get(_ENV_KEY):
            return _refused(
                _CODE_PROVIDER_UNAVAILABLE,
                (
                    f"no provider key is configured, so {model!r} cannot be called. "
                    f"Set {_ENV_KEY} in the environment; it is deliberately not a "
                    "parameter."
                ),
                {},
                {},
                {"model": model, "warm": False},
            )

        revision = self._runtime_revision()

        return _observed(
            MappingProxyType(
                {"provider": _PROVIDER, "model": model, "adapter_revision": revision}
            ),
            {},
            {"model": model, "provider": _PROVIDER, "warm": True, "generation": False},
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

        payload = f"{rubric}\n\n" + json.dumps(list(samples), ensure_ascii=False)

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

        _prefix, name = self._split(model)
        revision = self._runtime_revision()

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

        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        content.extend(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": getattr(image, "media_type", "image/png"),
                    "data": _encode_image(image),
                },
            }
            for image in images
        )

        body: dict[str, Any] = {
            "model": name,
            "max_tokens": ceiling,
            "messages": [{"role": "user", "content": content}],
        }
        body.update(_sampling_parameters())

        # The schema is sent as a tool the model *must* call, which is how this API
        # constrains a structured answer rather than merely describing one. It is
        # sent for **both** entry points, and that is the correction of a real defect:
        # this block used to sit behind `if not vision`, so a `vision` call accepted a
        # schema, echoed it back in `observed.declared_schema`, and **never sent it**.
        # The constraint silently degraded into a hope that the model would format its
        # own answer as JSON.
        #
        # Measured with the schema withheld, against `{total: integer}`: a `tool_use`
        # block parsed and a text block that happened to contain JSON also parsed —
        # so the defect is invisible whenever the model cooperates — while prose
        # (*"El total es 7 pesos."*) and a JSON code fence both returned
        # `unsupported_format`. That is a failure of **this adapter's parsing**
        # reported against the provider, and the honest read of it is that the caller
        # asked for a constraint and did not get one.
        #
        # `OllamaEngine._generate` sends its `format` unconditionally, so the two
        # adapters agree on this. Nothing about the images changes: they ride on the
        # message either way, and the tool constrains the shape of the answer about
        # them, which is exactly what `vision(..., schema)` promises in the port.
        body["tools"] = [
            {
                "name": "emit",
                "description": "Return the structured answer.",
                "input_schema": dict(schema),
            }
        ]
        body["tool_choice"] = {"type": "tool", "name": "emit"}

        started = time.monotonic()
        try:
            response = self._post(_PATH_MESSAGES, body)
        except OSError as exc:
            self._record(
                model=name,
                revision=revision,
                latency_ms=(time.monotonic() - started) * 1000,
                body=None,
                request_id=None,
            )
            self._last_raw_completion = None

            return _refused(
                _CODE_PROVIDER_UNAVAILABLE,
                str(exc),
                _unresolved_terms(model, name, revision),
                {},
                {"model": model, "provider": _PROVIDER, "vision": vision},
            )

        latency = (time.monotonic() - started) * 1000
        headers = getattr(response, "headers", {}) or {}
        request_id = headers.get("request-id") or headers.get("x-request-id")

        # --- The rate limit and the outage are facts about the provider --------
        if response.status_code == 429:
            retry_after = headers.get(_HEADER_RETRY_AFTER)
            self._record(
                model=name,
                revision=revision,
                latency_ms=latency,
                body=None,
                request_id=str(request_id) if request_id else None,
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
                    "provider": _PROVIDER,
                    "http_status": 429,
                    "retry_after": retry_after,
                    "vision": vision,
                },
            )

        if response.status_code == 404:
            self._record(
                model=name,
                revision=revision,
                latency_ms=latency,
                body=None,
                request_id=str(request_id) if request_id else None,
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
                {"model": model, "provider": _PROVIDER, "http_status": 404},
            )

        if response.status_code != 200:
            self._record(
                model=name,
                revision=revision,
                latency_ms=latency,
                body=None,
                request_id=str(request_id) if request_id else None,
            )
            self._last_raw_completion = _raw_bytes(response)

            return _refused(
                _CODE_PROVIDER_UNAVAILABLE,
                (
                    f"the provider answered HTTP {response.status_code} for "
                    f"{name!r}. The provider is unavailable rather than the answer "
                    "being wrong; this is never reported as a rejection of the "
                    "document."
                ),
                _unresolved_terms(model, name, revision),
                {},
                {
                    "model": model,
                    "provider": _PROVIDER,
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
                model=name,
                revision=revision,
                latency_ms=latency,
                body=None,
                request_id=str(request_id) if request_id else None,
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
                    "provider": _PROVIDER,
                    "http_status": 200,
                    "body_is_json": False,
                },
            )

        resolved_revision = str(parsed_body.get("model") or name)
        first, changed = self._resolve_revision(model, resolved_revision)

        record = self._record(
            model=name,
            revision=resolved_revision,
            latency_ms=latency,
            body=parsed_body,
            request_id=str(request_id) if request_id else None,
        )

        stop_reason = str(parsed_body.get("stop_reason") or "")
        measurements = {
            "prompt_tokens": float(record.prompt_tokens or 0),
            "completion_tokens": float(record.completion_tokens or 0),
            "latency_ms": record.latency_ms,
        }
        observed: dict[str, object] = {
            "model": model,
            "provider": _PROVIDER,
            "model_revision": resolved_revision,
            "adapter_revision": revision,
            "first_seen_revision": first,
            "revision_changed": changed,
            "stop_reason": stop_reason,
            "http_status": 200,
            "request_id": record.request_id,
            "raw_completion_bytes": float(len(self._last_raw_completion)),
            "vision": vision,
            "attempts": 1,
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
        answer, outcome = _extract_answer(parsed_body)
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
        parsed, problem = load_object(answer)
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
            "provider": _PROVIDER,
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
            "provider": _PROVIDER,
            "model": model,
            "model_name": name,
            "model_revision": "unresolved",
            "adapter_revision": adapter_revision,
        }
    )


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
