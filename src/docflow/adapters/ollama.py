"""K5 ``LlmEngine`` port adapter over **Ollama**, speaking its HTTP API directly.

The local-generation engine. It satisfies `LlmEngine`'s five operations —
`capabilities`, `warm`, `structured`, `vision` and `judge` — and two silent failures
shape everything below, and both
are failures of *attribution* rather than of computation.

**A local model is identified by a digest, not a tag.** ``qwen2.5`` is a moving
tag: pulling it again mid-run changes the thing that produced every later value,
and nothing in the output would say so. The digest is read from ``/api/tags`` — the
one endpoint that carries it — recorded at first use, and compared for the rest of
the run. A swap becomes a difference rather than a surprise.

**A completion cut by the context window is a typed failure, never a value.** Ollama
signals the cut with ``done_reason: "length"``, and a completion severed after the
last complete field parses cleanly — which is precisely how a truncated answer gets
reported as a whole one. The raw completion is therefore kept alongside the parsed
structure, so a truncated call is distinguishable from a complete one without
re-invoking the model.

The transport is ``httpx``, not the ``ollama`` package: the package is not
installed, and the API is four endpoints. Speaking it directly also keeps the
response fields this adapter depends on — ``done_reason`` above all — visible at the
boundary rather than behind a client library's abstraction.

What this adapter never does
----------------------------

- **No default or fallback model.** An unknown name produces ``model_unknown``, and
  a name that is well-formed but absent locally produces ``model_not_pulled`` with
  the remedy in the message. Nothing resolves to a working model by accident
  (`kernel-cli.md` §8, §14).
- **No secret in a parameter.** There is no API key on any signature; the endpoint
  host comes from the environment, because a local runtime's address is an
  operational setting and a credential is not.
- **No retry until two answers agree.** Attempts are counted and reported; the
  pattern is visible rather than forbidden by hope (`kernel-cli.md` §7).
- **No confidence aggregation.** A sampled kernel's value is not assertable — the
  evidence is.

PoC stage
---------

Each deliberate shortcut carries a marker naming what must replace it. Two are
structural: the transport is created per call, and ``judge`` is implemented
generically because the port declares it, even though only the frontier path
exercises it in Stage 1.
"""

from __future__ import annotations

import base64
import json
import os
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any, Final

from docflow.adapters._json_object import load_object
from docflow.kernels.types import Evidence, KernelResult, Reason

__all__: list[str] = ["OllamaEngine"]

# --- Reason codes, from the closed set of `kernel-cli.md` §5 -----------------

_CODE_MODEL_NOT_PULLED: Final[str] = "model_not_pulled"
_CODE_MODEL_UNKNOWN: Final[str] = "model_unknown"
_CODE_TRUNCATED_OUTPUT: Final[str] = "truncated_output"
_CODE_ENGINE_UNAVAILABLE: Final[str] = "engine_unavailable"
_CODE_UNSUPPORTED_FORMAT: Final[str] = "unsupported_format"

# --- Endpoints ---------------------------------------------------------------

_PATH_TAGS: Final[str] = "/api/tags"
_PATH_SHOW: Final[str] = "/api/show"
_PATH_CHAT: Final[str] = "/api/chat"
_PATH_PS: Final[str] = "/api/ps"
_PATH_VERSION: Final[str] = "/api/version"

# --- Operational settings, read from the environment ------------------------
#
# A local runtime's address is an operational setting, not a credential, so the
# environment is the right home for it — and it is *not* a model, an engine or a
# threshold, none of which may be substituted from anywhere (`plans/README.md` §2).

#: The environment variable naming the runtime's base URL.
_ENV_HOST: Final[str] = "DOCFLOW_OLLAMA_HOST"

#: Where a default Ollama install listens. It is the *address* that is defaulted,
#: never a model: a wrong address fails loudly, while a substituted model would not.
_DEFAULT_HOST: Final[str] = "http://127.0.0.1:11434"

#: How long a single call may take. Generation on a local model is slow, and a
#: timeout that fires mid-answer would be reported as a failed call rather than as a
#: long one.
_TIMEOUT_SECONDS: Final[float] = 600.0

#: The ``done_reason`` value that means the context window or the token ceiling cut
#: the answer. Read from the raw response, never inferred from the text.
_DONE_REASON_LENGTH: Final[str] = "length"

#: The code for a model asked to grade its own output. It is in the closed set of
#: `kernel-cli.md` §5 and attributed to K6, but the guard is not worth withholding
#: from the path that can also reach it.
_CODE_ROLE_CONFLICT: Final[str] = "role_conflict"

#: The sampling options this adapter forwards. Anything else a caller passes is
#: dropped rather than refused, because the runtime owns its own option vocabulary.
#: ``num_ctx`` is here because it is a term a test asserts on: without it the
#: runtime quietly applies its own default window, and a generation cut by that
#: window could not be told from one cut by a window the caller chose.
_FORWARDED_OPTIONS: Final[tuple[str, ...]] = (
    "temperature",
    "top_p",
    "top_k",
    "seed",
    "num_predict",
    "num_ctx",
)


class OllamaEngine:
    """Ollama behind :class:`~docflow.ports.LlmEngine`.

    Reachable only through the port. The composition root imports this class; no
    module under ``docflow/ports/`` does (`ADR-004`).
    """

    def __init__(self, *, base_url: str | None = None, client: Any = None) -> None:
        """Initialise the adapter.

        Args:
            base_url: The runtime's base URL. ``None`` reads
                :data:`_ENV_HOST` and falls back to the default address.
            client: An HTTP client to use instead of building one. It exists so the
                tests can exercise the boundary without a running runtime, and so a
                caller can supply a configured client. ``None`` means *build one*,
                never *use a default model*.

        """
        self._base_url = (
            base_url or os.environ.get(_ENV_HOST) or _DEFAULT_HOST
        ).rstrip("/")
        self._client = client
        # The digest each model resolved to the first time this adapter saw it,
        # keyed by bare name. This is what makes a mid-run swap a difference
        # rather than a surprise.
        self._seen_digests: dict[str, str] = {}
        self._adapter_revision: str | None = None

    # --- Transport ----------------------------------------------------------

    def _http(self) -> Any:
        """Return the HTTP client, building one if none was supplied.

        Returns:
            The client.

        Raises:
            Reason: Never — the import failure is turned into a typed reason by the
                callers, which is why this raises nothing of its own.

        """
        if self._client is not None:
            return self._client

        import httpx  # pylint: disable=import-outside-toplevel

        self._client = httpx.Client(base_url=self._base_url, timeout=_TIMEOUT_SECONDS)

        return self._client

    def _post(self, path: str, payload: Mapping[str, Any]) -> Any:
        """Send one request and return the response.

        Args:
            path: The endpoint path.
            payload: The JSON body.

        Returns:
            The response object.

        Raises:
            ConnectionError: When the runtime cannot be reached. Callers turn it
                into a typed reason, because *the runtime is down* and *the model
                answered badly* need different remediation.

        """
        try:
            return self._http().post(path, json=dict(payload))
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise ConnectionError(
                f"the Ollama runtime at {self._base_url} could not be reached: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

    def _get(self, path: str) -> Any:
        """Send one GET and return the response.

        Args:
            path: The endpoint path.

        Returns:
            The response object.

        Raises:
            ConnectionError: When the runtime cannot be reached.

        """
        try:
            return self._http().get(path)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise ConnectionError(
                f"the Ollama runtime at {self._base_url} could not be reached: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

    # --- Model identity -----------------------------------------------------

    def _resolve_identity(self, model: str) -> KernelResult[Evidence]:
        """Resolve a model to its digest and compare it with the first sighting.

        The comparison is the run-wide half of the digest discipline: the digest is
        recorded the first time a model is seen, and every later resolution is
        checked against it. A ``pull`` under a moving tag changes the bytes the name
        resolves to, and the change has to surface as a **difference** in the
        evidence rather than as a silent substitution.

        Args:
            model: The model as the caller named it.

        Returns:
            The catalogue facts for the model, with ``revision_changed`` set when a
            previous resolution disagrees, or no value and a typed ``Reason``.

        """
        try:
            catalogue = self._catalogue()
        except (ConnectionError, ValueError) as exc:
            return _refused(
                _CODE_ENGINE_UNAVAILABLE, str(exc), {}, {}, {"model": model}
            )

        digest = self._digest_of(model, catalogue)
        if digest is None:
            return _refused(
                _CODE_MODEL_NOT_PULLED,
                (
                    f"the model {model!r} is not present in this Ollama runtime. "
                    f"Pull it first: `ollama pull {model}`. The available models are "
                    f"{sorted(str(e.get('name')) for e in catalogue)}; no default is "
                    "substituted."
                ),
                {},
                {},
                {
                    "model": model,
                    "available": sorted(str(e.get("name")) for e in catalogue),
                },
            )

        entry = next(e for e in catalogue if str(e.get("digest", "")) == digest)
        details = dict(entry.get("details") or {})
        declared = entry.get("capabilities") or []

        bare = model.strip().partition(":")[0]
        first = self._seen_digests.setdefault(bare, digest)
        changed = first != digest

        return _observed(
            _terms(model, digest),
            {},
            {
                "model": model,
                "model_revision": digest,
                "first_seen_revision": first,
                "revision_changed": changed,
                "num_ctx": self._effective_context_length(bare, digest),
                "params": dict(_options_from_environment()),
                "tag_is_moving": True,
                "family": str(details.get("family", "unknown")),
                "parameter_size": str(details.get("parameter_size", "unknown")),
                "quantization": str(details.get("quantization_level", "unknown")),
                "capabilities": sorted(str(c) for c in declared),
                "supports_vision": "vision" in declared,
            },
        )

    def _effective_context_length(self, bare: str, digest: str) -> int | None:
        """Report the context window the runtime actually loaded the model with.

        **Not** the window the model declares. They differ in practice: a model
        whose metadata says 8192 loads under a 4096 window when the caller names no
        ``num_ctx``, and reporting the declared number would be reporting a figure
        nothing used. The loaded value is read from ``/api/ps``, which reports only
        *loaded* models — so ``None`` means *not currently loaded*, and the
        declared value in ``model_info`` is deliberately **not** substituted for it,
        because the two answer different questions.

        Call this **after** the generation, not before: ``/api/ps`` describes the
        model as it is currently loaded, and the generation is what loads it under
        the window it used. A pre-call read reports the previous call's window.

        Args:
            bare: The model's name without its tag.
            digest: The digest it resolved to.

        Returns:
            The loaded window in tokens, or ``None`` when the model is not loaded.

        """
        try:
            response = self._get(_PATH_PS)
        except ConnectionError:
            return None

        if response.status_code != 200:
            return None

        try:
            loaded = response.json().get("models") or []
        except ValueError:
            return None

        for entry in loaded:
            if str(entry.get("digest", "")) == digest:
                value = entry.get("context_length")
                return int(value) if isinstance(value, int) else None
            if str(entry.get("name", "")).partition(":")[0] == bare:
                value = entry.get("context_length")
                return int(value) if isinstance(value, int) else None

        return None

    def _runtime_revision(self) -> str:
        """Report the runtime's build, so the engine's revision is a cache term.

        Read once per adapter. ``/api/version`` is the endpoint that carries it, and
        the same call against a different build is different work (`sad.md` §5).

        Returns:
            The version string, or ``"unknown"`` when it cannot be read. Unknown is
            a real answer for an optional identity term, not a stand-in for a model
            or an engine.

        """
        if self._adapter_revision is not None:
            return self._adapter_revision

        version = "unknown"
        try:
            response = self._get(_PATH_VERSION)
            if response.status_code == 200:
                version = str(response.json().get("version") or "unknown")
        except (ConnectionError, ValueError):
            version = "unknown"

        self._adapter_revision = f"ollama {version}"

        return self._adapter_revision

    def _catalogue(self) -> list[dict[str, Any]]:
        """Fetch the models the runtime holds, with their digests.

        ``/api/tags`` is the only endpoint that reports a digest; ``/api/show``
        does not, despite describing a single model in more detail. That asymmetry
        is why the identity check reads the catalogue rather than the model.

        Returns:
            The catalogue entries.

        Raises:
            ConnectionError: When the runtime cannot be reached.
            ValueError: When the runtime answers with something that is not a
                catalogue.

        """
        response = self._get(_PATH_TAGS)
        if response.status_code != 200:
            raise ValueError(
                f"{_PATH_TAGS} answered {response.status_code}: {response.text[:200]}"
            )

        body = response.json()
        models = body.get("models")
        if not isinstance(models, list):
            raise ValueError(f"{_PATH_TAGS} answered without a models list")

        return models

    def _digest_of(
        self, model: str, catalogue: Sequence[Mapping[str, Any]]
    ) -> str | None:
        """Find the digest a model name resolves to.

        Args:
            model: The name the caller used.
            catalogue: The runtime's catalogue.

        Returns:
            The digest, or ``None`` when the name matches nothing. The name is
            matched with and without its tag, because ``qwen2.5`` and
            ``qwen2.5:latest`` are the same model to the runtime and only one of
            them appears in the catalogue.

        """
        wanted = model.strip()
        bare = wanted.split(":")[0]

        for entry in catalogue:
            name = str(entry.get("name", ""))
            if name == wanted:
                return str(entry.get("digest", ""))

        for entry in catalogue:
            name = str(entry.get("name", ""))
            if name.partition(":")[0] == bare:
                return str(entry.get("digest", ""))

        return None

    # --- Operations ---------------------------------------------------------

    def capabilities(self, model: str) -> KernelResult[Evidence]:
        """Report the model's identity and parameters, without generating.

        Args:
            model: The model as the caller named it.

        Returns:
            The **digest**, never the tag alone, or no value and a typed ``Reason``:
            ``model_not_pulled`` when the name is well-formed but absent locally,
            ``engine_unavailable`` when the runtime cannot be reached. The evidence
            reports the digest, the effective ``num_ctx``, the sampling parameters
            and the adapter revision — the terms a test may assert on, because a
            sampled kernel's *value* is not assertable (`kernel-cli.md` §7).

        """
        return self._resolve_identity(model)

    def warm(self, model: str) -> KernelResult[Evidence]:
        """Load the model so the first real call pays no cold start.

        A minimal completion is issued rather than a metadata call, because the
        question is *is this model resident and able to answer*, and only a call
        that generates can answer it.

        Args:
            model: The model to warm.

        Returns:
            Evidence that the model answered, or no value and a typed ``Reason``.

        """
        spec = self._resolve_identity(model)
        if spec.value is None:
            return spec

        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "ok"}],
            "stream": False,
            # The *same* options a real call will send, so the model loads under the
            # window the later call will use. Warming with a different window would
            # load the model only to have the first real call reload it, which is
            # precisely the cold start warming exists to avoid. ``num_predict`` is
            # capped at 1 because the question is *is it resident*, not *what does it
            # say*.
            "options": {**dict(_options_from_environment()), "num_predict": 1},
        }

        try:
            response = self._post(_PATH_CHAT, payload)
        except ConnectionError as exc:
            return _refused(
                _CODE_ENGINE_UNAVAILABLE, str(exc), {}, {}, {"model": model}
            )

        if response.status_code != 200:
            return _refused(
                _CODE_MODEL_NOT_PULLED,
                (
                    f"warming {model!r} failed with HTTP {response.status_code}: "
                    f"{response.text[:200]}. If the model is absent, pull it with "
                    f"`ollama pull {model}`."
                ),
                {},
                {},
                {"model": model},
            )

        digest = str(spec.value.observed["model_revision"])
        revision = self._runtime_revision()

        return _observed(
            _terms(model, digest, revision),
            {"warm_latency_ms": _ms(response.json().get("total_duration"))},
            {
                "model": model,
                "model_revision": digest,
                "adapter_revision": revision,
                "warm": True,
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
            The parsed answer, or no value and a typed ``Reason``. A generation cut
            by the context window reports ``truncated_output`` and is **never**
            parsed as complete. The raw completion is preserved on the evidence
            either way.

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
            truncation and raw-completion rules as ``structured``.

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

        The prohibition lives in the frontier adapter's role in Stage 1, but the
        guard belongs wherever the call can be made: a model grading samples it
        produced measures its own habits rather than the answer's correctness, so a
        matching ``produced_by`` is refused here too rather than only there.

        Args:
            model: The model as the caller named it, in the grading role.
            rubric: The grading criteria, supplied by the caller.
            samples: The samples to grade.
            produced_by: The model that produced the samples.

        Returns:
            The grades, or no value and a typed ``Reason``. Grading one's own output
            reports ``role_conflict``.

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

    # The local count is high because the order is deliberate: resolve the model,
    # read the environment, build the body, call, then classify the response. Each
    # step pushes an earlier one out of scope, so the pipeline stays legible.
    # pylint: disable=too-many-locals,too-many-return-statements
    def _generate(
        self,
        model: str,
        prompt: str,
        schema: Mapping[str, object],
        *,
        images: Sequence[Any],
        vision: bool,
    ) -> KernelResult[Mapping[str, object]]:
        """Execute one generation and apply the truncation rule.

        Args:
            model: The model as the caller named it.
            prompt: The prompt text.
            schema: The schema the answer must satisfy.
            images: The images to attach, empty for a text call.
            vision: Whether this is a vision call, for the evidence.

        Returns:
            The parsed answer, or no value and a typed ``Reason``.

        """
        spec = self._resolve_identity(model)
        if spec.value is None:
            return _refused(
                spec.reason.code if spec.reason else _CODE_MODEL_UNKNOWN,
                spec.reason.message if spec.reason else "",
                {},
                {},
                {"model": model},
            )

        digest = str(spec.value.observed["model_revision"])
        revision = self._runtime_revision()
        message: dict[str, Any] = {"role": "user", "content": prompt}
        if images:
            message["images"] = [_encode_image(image) for image in images]

        payload: dict[str, Any] = {
            "model": model,
            "messages": [message],
            "stream": False,
            "format": dict(schema),
            "options": dict(_options_from_environment()),
        }

        try:
            response = self._post(_PATH_CHAT, payload)
        except ConnectionError as exc:
            return _refused(
                _CODE_ENGINE_UNAVAILABLE,
                str(exc),
                _terms(model, digest, revision),
                {},
                {"model": model, "vision": vision},
            )

        if response.status_code != 200:
            return _refused(
                _CODE_MODEL_UNKNOWN,
                (
                    f"{model!r} failed with HTTP {response.status_code}: "
                    f"{response.text[:200]}"
                ),
                _terms(model, digest, revision),
                {},
                {"model": model, "vision": vision},
            )

        body = response.json()
        raw = str((body.get("message") or {}).get("content") or "")
        done_reason = str(body.get("done_reason") or "")

        # Read *after* the call: ``/api/ps`` reports the window the model is loaded
        # at, and the call is what loads it. Reading before the call reports the
        # previous call's window — a stale number presented as this call's.
        bare = model.strip().partition(":")[0]
        num_ctx = self._effective_context_length(bare, digest)

        # Both sides of the prompt are recorded, because the runtime **cuts an
        # oversized prompt silently**. Measured here: one prompt of ~2,429 tokens
        # sent with room left to answer came back evaluated at **130** tokens under
        # ``num_ctx: 256`` with ``done_reason: "stop"`` — no failure, no signal, a
        # confident answer to a question partly discarded. At ``num_ctx: 1024`` the
        # same prompt evaluated at 514 tokens and reported ``length``, so whether the
        # cut surfaces at all depends on the window. Deciding it inside the adapter
        # would need the prompt's token count, and inventing a characters-per-token
        # constant would be **this kernel choosing a threshold**, which `prd.md`
        # FR-15 forbids. So the two facts are recorded and the discrepancy is left
        # where a caller can see it, rather than being smoothed into a confidence
        # the adapter does not have.
        prompt_characters = len(prompt) + sum(len(str(i)) for i in images)

        measurements = {
            "prompt_tokens": float(body.get("prompt_eval_count") or 0),
            "prompt_characters": float(prompt_characters),
            "completion_tokens": float(body.get("eval_count") or 0),
            "total_duration_ms": _ms(body.get("total_duration")),
        }
        observed = {
            "model": model,
            "model_revision": digest,
            "adapter_revision": revision,
            "num_ctx": num_ctx,
            "params": dict(_options_from_environment()),
            "done_reason": done_reason,
            "raw_completion": raw,
            "vision": vision,
            "attempts": 1,
        }

        if done_reason == _DONE_REASON_LENGTH:
            return _refused(
                _CODE_TRUNCATED_OUTPUT,
                (
                    "the generation was cut by the context window or the token "
                    f"ceiling (done_reason={done_reason!r}), so the answer is "
                    "incomplete. It is reported as truncated rather than parsed: a "
                    "cut that lands after the last complete field parses cleanly, "
                    "which is how a partial answer is mistaken for a whole one."
                ),
                _terms(model, digest, revision),
                measurements,
                observed,
            )

        # The object check is shared with K6: two vendors, one rule. What differs —
        # the codes, the terms, the measurements — stays here.
        parsed, problem = load_object(raw)
        if problem is not None:
            return _refused(
                _CODE_UNSUPPORTED_FORMAT,
                f"{problem} The raw completion was {raw[:200]!r}.",
                _terms(model, digest, revision),
                measurements,
                observed,
            )

        return KernelResult(
            value=MappingProxyType(parsed or {}),
            evidence=_evidence(_terms(model, digest, revision), measurements, observed),
            reason=None,
        )


# --- Module helpers ----------------------------------------------------------


def _options_from_environment() -> dict[str, Any]:
    """Read the sampling options the environment declares.

    Only the options in :data:`_FORWARDED_OPTIONS` are read, from
    ``DOCFLOW_OLLAMA_<OPTION>``. The runtime's own defaults apply to the rest,
    because inventing a sampling parameter here would be this adapter choosing a
    behaviour the caller did not ask for.

    Returns:
        The options to forward, possibly empty.

    """
    options: dict[str, Any] = {}
    for name in _FORWARDED_OPTIONS:
        raw = os.environ.get(f"DOCFLOW_OLLAMA_{name.upper()}")
        if raw is None:
            continue
        try:
            options[name] = float(raw) if "." in raw else int(raw)
        except ValueError:
            # A malformed setting is ignored rather than fatal: the alternative is a
            # runtime that cannot be used at all because of a typo in an optional
            # tuning value. It is not a model, an engine or a threshold, so reading
            # nothing is a safe outcome.
            continue

    return options


def _same_model(left: str, right: str) -> bool:
    """Report whether two model names denote the same model.

    Tags are ignored: ``qwen2.5`` and ``qwen2.5:latest`` are the same model to the
    runtime, and a self-grading guard that missed that would be defeated by a tag.

    Args:
        left: One model name.
        right: The other.

    Returns:
        ``True`` when the bare names match.

    """
    return left.split(":")[0].strip() == right.split(":")[0].strip()


def _encode_image(image: Any) -> str:
    """Encode an image into the base64 string the API expects.

    Args:
        image: A ``Bytes`` value, or a path, or bytes.

    Returns:
        The base64 string.

    """
    payload = getattr(image, "data", None)
    if payload is None:
        payload = image if isinstance(image, bytes) else bytes(image)

    return base64.b64encode(payload).decode("ascii")


def _terms(model: str, digest: str, adapter_revision: str = "") -> Mapping[str, str]:
    """Report the cache-key terms for one model.

    Args:
        model: The name the caller used.
        digest: The resolved digest.
        adapter_revision: The runtime's build, e.g. ``"ollama 0.31.1"``. Empty
            omits the term, which the paths that fire before the runtime is known
            (a typed refusal) rely on.

    Returns:
        The terms. The **digest** is the model's identity, and the tag is recorded
        beside it so an operator can see which name produced the run.

    """
    terms = {"model": model, "model_revision": digest}
    if adapter_revision:
        terms["adapter_revision"] = adapter_revision

    return MappingProxyType(terms)


def _ms(nanoseconds: Any) -> float:
    """Convert the API's nanosecond durations to milliseconds.

    Args:
        nanoseconds: The value the API reported, or ``None``.

    Returns:
        Milliseconds, or ``0.0`` when the API reported nothing. A missing duration
        is reported as zero latency rather than as an absence, because it is a
        measurement about the call rather than a claim about the document.

    """
    try:
        return round(float(nanoseconds) / 1_000_000, 3)
    except (TypeError, ValueError):
        return 0.0


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
    """Build a successful result whose value is the observation record.

    Args:
        terms: The cache-key terms.
        measurements: The numeric measurements.
        observed: The remaining observations.

    Returns:
        A ``KernelResult`` carrying the evidence as its value.

    """
    evidence = _evidence(terms, measurements, observed)

    return KernelResult(value=evidence, evidence=evidence, reason=None)


def _refused(
    code: str,
    message: str,
    terms: Mapping[str, str],
    measurements: Mapping[str, float],
    observed: Mapping[str, object],
) -> KernelResult[Any]:
    """Build a failed result that still carries what was observed.

    Args:
        code: The reason code.
        message: The human-readable explanation.
        terms: The cache-key terms.
        measurements: The measurements taken.
        observed: The remaining observations.

    Returns:
        A ``KernelResult`` with no value and the evidence attached.

    """
    return KernelResult(
        value=None,
        evidence=_evidence(terms, measurements, observed),
        reason=Reason(code=code, message=message),
    )
