"""Tests for the Ollama ``LlmEngine`` adapter (``E04-05`` / ``S1-T15``).

The transport is stubbed for the invariants, so the suite runs without a runtime,
and a small **live** class exercises the real API when one is reachable. The split
matters here more than elsewhere: the two failures this adapter exists to prevent —
a moving tag and a truncated completion — are properties of the *real* response, and
a stub can only prove the adapter reads the field it was told to read.

The assertions that matter, one per silent-failure row:

- ``test_a_cut_generation_is_truncated_and_never_parsed`` — row 12. The cut is
  detected from ``done_reason`` and the partial answer is **not** returned as a
  value, even though it happened to land after the last complete field.
- ``test_the_digest_is_reported_and_the_tag_is_marked_moving`` — row 13's half that
  can be asserted without pulling: the identity is the digest, and the tag is
  recorded as the moving thing it is.

Pylint relaxations are declared for the reasons the other suites state: a contract
test restates the names it checks (``duplicate-code``), one test per behaviour costs
file length (``too-many-lines``, ``redefined-outer-name``), and the stubs are
one-purpose stand-ins by design (``too-few-public-methods``).
"""

# pylint: disable=duplicate-code
# pylint: disable=redefined-outer-name
# pylint: disable=too-few-public-methods
# pylint: disable=too-many-lines

from __future__ import annotations

import json

import pytest

from docflow.adapters.ollama import OllamaEngine
from docflow.ports import LlmEngine

# --- A stub transport --------------------------------------------------------

CATALOGUE = {
    "models": [
        {
            "name": "smollm2:latest",
            "digest": "cef4a1e09247f018ca0c482ad4c2ce1474"
            + "aba5e87f245dacf97f07948d05d8b4",
            "details": {
                "family": "llama",
                "parameter_size": "1.7B",
                "quantization_level": "Q8_0",
            },
            "capabilities": ["completion"],
        },
        {
            "name": "qwen2.5vl:3b",
            "digest": "fb90415cde1ef08aa669" + "0" * 44,
            "details": {
                "family": "qwen2vl",
                "parameter_size": "3B",
                "quantization_level": "Q4_K_M",
            },
            "capabilities": ["completion", "vision"],
        },
    ]
}


class _Response:
    """A minimal response, carrying only what the adapter reads.

    ``raw`` exists so a test can put **bytes** on the wire instead of a body that
    gets re-serialised. That matters for one shape in particular: Ollama answers a
    refused request with an ``error`` key whose value is *JSON encoded as a string*,
    and a stub handed the parsed dict would re-emit it as a dict — losing the nesting
    the adapter has to unpeel. Measured: a test written with a dict let a mutation
    that disabled the unpeeling **survive**.
    """

    def __init__(
        self, status_code: int, body: dict, text: str = "", raw: bytes | None = None
    ) -> None:
        self.status_code = status_code
        self._body = body
        self.text = (
            raw.decode("utf-8") if raw is not None else (text or json.dumps(body))
        )

    def json(self) -> dict:
        """Return the decoded body."""
        return self._body


class _StubClient:
    """An HTTP client that answers from prepared responses instead of a socket."""

    def __init__(
        self,
        *,
        chat: dict | None = None,
        status: int = 200,
        raw: bytes | None = None,
    ) -> None:
        self._chat = chat
        self._status = status
        self._raw = raw
        self.calls: list[tuple[str, dict]] = []
        self.loaded_context_length: int | None = None
        self.version_unavailable = False
        # The window the runtime reports *before* the call. A chat call replaces it
        # with whatever the request asked for, which is what the real runtime does
        # when a generation loads the model at a new window.
        self.preloaded_context_length: int | None = None

    def get(self, path: str) -> _Response:
        """Answer a read-only request.

        Args:
            path: The requested path, recorded so a test can assert the route.

        Returns:
            The catalogue, the loaded-model list or the version.

        """
        self.calls.append(("GET", {"path": path}))

        if path.endswith("/ps"):
            loaded = []
            window = self.loaded_context_length
            if window is None:
                window = self.preloaded_context_length
            if window is not None:
                loaded.append(
                    {
                        "name": "smollm2:latest",
                        "digest": CATALOGUE["models"][0]["digest"],
                        "context_length": window,
                    }
                )
            return _Response(200, {"models": loaded})

        if path.endswith("/version"):
            if self.version_unavailable:
                return _Response(500, {}, text="unavailable")
            return _Response(200, {"version": "0.31.1"})

        return _Response(200, CATALOGUE)

    def post(  # pylint: disable=unused-argument
        self, path: str, json: dict | None = None
    ) -> _Response:
        """Answer a chat request, loading the model at the requested window.

        The path is unused because the stub answers one route; the body is recorded
        so a test can assert what was sent.

        Args:
            path: The requested path.
            json: The request body.

        Returns:
            The prepared chat response.

        """
        self.calls.append(("POST", dict(json or {})))
        asked = (json or {}).get("options", {}).get("num_ctx")
        if isinstance(asked, int):
            self.loaded_context_length = asked
        if self._raw is not None:
            return _Response(self._status, {}, raw=self._raw)
        if self._chat is None:
            return _Response(self._status, {}, text="not found")

        return _Response(self._status, self._chat)


class _SwappingClient(_StubClient):
    """A client whose model is re-pulled under a moving tag mid-run.

    The first catalogue answer holds the original digest; every answer after it
    holds a different one, which is what a ``pull`` of a moving tag does to the
    bytes a name resolves to.
    """

    def __init__(self) -> None:
        super().__init__(chat=_chat_body('{"a": 1}'))
        self._seen = 0

    def get(self, path: str) -> _Response:
        """Answer the catalogue, then answer it with a swapped digest.

        Args:
            path: The requested path.

        Returns:
            The version, the loaded list, or a catalogue whose digest has moved.

        """
        if path.endswith("/tags"):
            self._seen += 1
            digest = "a" * 64 if self._seen == 1 else "b" * 64
            return _Response(
                200,
                {
                    "models": [
                        {
                            "name": "qwen2.5:latest",
                            "digest": digest,
                            "details": {"family": "qwen2"},
                            "capabilities": ["completion"],
                        }
                    ]
                },
            )

        return super().get(path)


class _DeadClient:
    """A client whose transport is down."""

    def get(self, path: str) -> _Response:  # pylint: disable=unused-argument
        """Fail the way a refused connection fails."""
        raise ConnectionRefusedError("connection refused")

    def post(  # pylint: disable=unused-argument
        self, path: str, json: dict | None = None
    ) -> _Response:
        """Fail the way a refused connection fails."""
        raise ConnectionRefusedError("connection refused")


def _chat_body(
    content: str,
    *,
    done_reason: str = "stop",
    eval_count: int = 7,
    prompt_eval_count: int = 40,
) -> dict:
    """Build a chat response body.

    Args:
        content: The message text.
        done_reason: The reason the runtime stopped.
        eval_count: Completion tokens.
        prompt_eval_count: Prompt tokens.

    Returns:
        The body.

    """
    return {
        "model": "smollm2:latest",
        "message": {"role": "assistant", "content": content},
        "done": True,
        "done_reason": done_reason,
        "eval_count": eval_count,
        "prompt_eval_count": prompt_eval_count,
        "total_duration": 1_638_417_000,
    }


def _engine(**kwargs) -> OllamaEngine:
    """Build an adapter over a stub client.

    Args:
        **kwargs: Forwarded to the stub client.

    Returns:
        The adapter.

    """
    return OllamaEngine(base_url="http://stub", client=_StubClient(**kwargs))


# --- The port contract -------------------------------------------------------


def test_the_adapter_satisfies_the_port() -> None:
    """The adapter is structurally an ``LlmEngine``."""
    assert isinstance(_engine(), LlmEngine)


def test_the_adapter_exposes_the_ports_five_operations_and_no_more() -> None:
    """The adapter's public surface is the port's, and nothing was added.

    The port declares five operations. An extra public method would be a second
    surface to keep in step, and `E04-01` froze the port at five.
    """
    public = {
        name
        for name in vars(OllamaEngine)
        if not name.startswith("_") and callable(getattr(OllamaEngine, name))
    }

    assert public == {"capabilities", "warm", "structured", "vision", "judge"}


# --- Row 13: the digest is the identity --------------------------------------


def test_the_digest_is_reported_and_the_tag_is_marked_moving() -> None:
    """``capabilities`` reports the digest, and says the tag moves.

    ``qwen2.5`` is a moving tag: the same name resolves to different bytes after a
    pull. The digest is the identity, and ``tag_is_moving`` states the trap rather
    than leaving it to be remembered.
    """
    result = _engine().capabilities("smollm2:latest")

    assert result.value is not None
    assert result.value.observed["model_revision"] == CATALOGUE["models"][0]["digest"]
    assert result.value.observed["tag_is_moving"] is True
    assert result.value.terms["model_revision"] == CATALOGUE["models"][0]["digest"]


def test_the_digest_is_not_the_tag() -> None:
    """The reported revision differs from the name the caller used.

    Without this, an implementation that echoed the request back would satisfy the
    assertion above while reporting no identity at all.
    """
    result = _engine().capabilities("smollm2:latest")

    assert result.value is not None
    assert result.value.observed["model_revision"] != "smollm2:latest"
    assert len(str(result.value.observed["model_revision"])) == 64


def test_a_bare_name_resolves_to_the_tagged_model() -> None:
    """``smollm2`` and ``smollm2:latest`` are the same model to the runtime."""
    bare = _engine().capabilities("smollm2")
    tagged = _engine().capabilities("smollm2:latest")

    assert bare.value is not None and tagged.value is not None
    assert (
        bare.value.observed["model_revision"] == tagged.value.observed["model_revision"]
    )


def test_capabilities_reports_whether_the_model_sees_images() -> None:
    """A vision model reports ``supports_vision``; a text-only one does not."""
    vision = _engine().capabilities("qwen2.5vl:3b")
    text = _engine().capabilities("smollm2:latest")

    assert vision.value is not None and text.value is not None
    assert vision.value.observed["supports_vision"] is True
    assert text.value.observed["supports_vision"] is False


# --- Criterion: no fallback model -------------------------------------------


def test_a_request_the_runtime_refuses_is_not_reported_as_an_unknown_model() -> None:
    """A 400 is a fact about *this request*, and it says so.

    **This was a real defect and it misattributed the most common failure there is.**
    Measured: a 167 035-character prompt against `num_ctx: 4096` answers HTTP 400
    with `{"type": "exceed_context_size_error", "n_prompt_tokens": 38187,
    "n_ctx": 4096}` — and the adapter reported `model_unknown`, for a model whose
    `capabilities` call had *succeeded* moments earlier. A reader sent to look for a
    missing model cannot find the oversized prompt sitting in front of them.

    The body below is the real one, nested exactly as Ollama sends it: an `error` key
    whose value is **JSON encoded as a string**. A stub that sent a flat
    `{"error": "..."}` — or a dict, which `_Response` would re-serialise — would let a
    simpler parser pass while the runtime's actual shape went unread, and the message
    would come out as an opaque blob.

    **That is not hypothetical: the first version of this test did exactly that.** It
    built the body with `json.dumps` and handed the *parsed dict* to `_Response`,
    which re-serialises, so `error` reached the adapter as a dict and the unpeeling
    branch was never exercised — a mutation that disabled that branch **survived**.
    The body is therefore passed as **raw bytes** (`raw=`), which is the only way to
    put the runtime's real nesting on the wire.

    """
    inner = json.dumps(
        {
            "error": {
                "code": 400,
                "message": (
                    "request (38187 tokens) exceeds the available context size "
                    "(4096 tokens), try increasing it"
                ),
                "type": "exceed_context_size_error",
                "n_prompt_tokens": 38187,
                "n_ctx": 4096,
            }
        }
    )
    raw = json.dumps({"error": inner}).encode("utf-8")
    engine = _engine(status=400, raw=raw)

    result = engine.structured("smollm2:latest", "x" * 2000, {"type": "object"})

    assert result.value is None
    assert result.reason is not None
    # Not `model_unknown`: the name resolved, and the runtime said why it refused.
    assert result.reason.code == "unsupported_format"
    assert "exceeds the available context size" in result.reason.message
    assert result.evidence.observed["http_status"] == 400

    # **The unpeeling is asserted by what it *removes*, not by what it contains.**
    # The first version of this test only checked that the sentence was *present* —
    # and it is present either way, because the raw nested blob has the message
    # inside it too. A mutation that disabled the unpeeling therefore **survived**:
    # the refusal still read well enough to satisfy `in`. What separates the two
    # routes is the JSON scaffolding around the sentence, so that is what is checked.
    assert '"code"' not in result.reason.message
    assert "\\" not in result.reason.message
    assert result.reason.message.count("exceeds the available context size") == 1


def test_an_absent_model_is_a_typed_reason_naming_the_remedy() -> None:
    """A name that is not present locally reports ``model_not_pulled``.

    The message names `ollama pull <model>`, which is the remedy. The available
    models are listed in the evidence, because an operator reading only the code
    would have to guess what to type instead.
    """
    result = _engine().capabilities("no-existe:9b")

    assert result.value is None
    assert result.reason is not None
    assert result.reason.code == "model_not_pulled"
    assert "ollama pull no-existe:9b" in result.reason.message
    assert set(result.evidence.observed["available"]) == {
        "smollm2:latest",
        "qwen2.5vl:3b",
    }
    assert result.evidence.observed["available"] == sorted(
        result.evidence.observed["available"]
    ), "the list is reported in a fixed order, so the message is reproducible"


def test_no_default_model_is_substituted_for_an_absent_one() -> None:
    """The failure is returned; no other model is tried.

    This is `kernel-cli.md` §8's prohibition as an assertion: an unknown name never
    resolves to a working model. A fallback would produce a value here.
    """
    result = _engine(chat=_chat_body('{"total": "1"}')).capabilities("no-existe:9b")

    assert result.value is None
    assert result.reason is not None


def test_a_runtime_that_is_down_is_a_typed_reason() -> None:
    """An unreachable runtime reports ``engine_unavailable``, not a crash."""
    engine = OllamaEngine(base_url="http://stub", client=_DeadClient())

    result = engine.capabilities("smollm2:latest")

    assert result.value is None
    assert result.reason is not None
    assert result.reason.code == "engine_unavailable"
    assert "could not be reached" in result.reason.message


# --- Row 12: truncation is never parsed as complete -------------------------


def test_a_cut_generation_is_truncated_and_never_parsed() -> None:
    """``done_reason: length`` yields ``truncated_output``, not a parsed partial.

    The body below is the dangerous case: the cut landed **after** the last complete
    field, so the text is valid JSON and parses cleanly. An adapter that parses first
    and checks afterwards returns a value here — which is how a partial answer is
    reported as a whole one.
    """
    engine = _engine(chat=_chat_body('{"a": "uno", "b": "dos"}', done_reason="length"))

    result = engine.structured("smollm2:latest", "prompt", {"type": "object"})

    assert result.value is None, (
        "the cut answer parses cleanly, and returning it is exactly the silent "
        "failure this assertion exists to catch"
    )
    assert result.reason is not None
    assert result.reason.code == "truncated_output"
    assert result.evidence.observed["done_reason"] == "length"


def test_a_complete_generation_parses() -> None:
    """``done_reason: stop`` yields the parsed value.

    The pair with the test above proves the refusal is about the cut and not a
    blanket refusal to return anything.
    """
    engine = _engine(chat=_chat_body('{"a": "uno"}', done_reason="stop"))

    result = engine.structured("smollm2:latest", "prompt", {"type": "object"})

    assert result.reason is None
    assert result.value is not None
    assert dict(result.value) == {"a": "uno"}


def test_the_raw_completion_is_preserved_on_both_outcomes() -> None:
    """The raw text travels with the result, complete or cut.

    Without it, a truncated call and a complete one that produced an odd value are
    the same shape, and telling them apart needs the model invoked again — which a
    sampled kernel must not do.
    """
    cut = _engine(chat=_chat_body('{"a":', done_reason="length")).structured(
        "smollm2:latest", "p", {"type": "object"}
    )
    whole = _engine(chat=_chat_body('{"a": 1}', done_reason="stop")).structured(
        "smollm2:latest", "p", {"type": "object"}
    )

    assert cut.evidence.observed["raw_completion"] == '{"a":'
    assert whole.evidence.observed["raw_completion"] == '{"a": 1}'


def test_a_non_json_answer_is_a_typed_reason() -> None:
    """Prose where JSON was required is reported, not coerced into a mapping."""
    engine = _engine(chat=_chat_body("no soy JSON"))

    result = engine.structured("smollm2:latest", "p", {"type": "object"})

    assert result.value is None
    assert result.reason is not None
    assert result.reason.code == "unsupported_format"
    assert "not valid JSON" in result.reason.message


def test_a_json_answer_that_is_not_an_object_is_a_typed_reason() -> None:
    """A JSON array cannot satisfy a schema, and is refused as such."""
    engine = _engine(chat=_chat_body("[1, 2, 3]"))

    result = engine.structured("smollm2:latest", "p", {"type": "object"})

    assert result.value is None
    assert result.reason is not None
    assert result.reason.code == "unsupported_format"


# --- The evidence a sampled kernel may be asserted on -----------------------


def test_the_evidence_carries_the_terms_a_test_may_assert_on() -> None:
    """A sampled kernel's value is not assertable; its evidence is.

    `kernel-cli.md` §7: for K4 and K5 a test asserts the digest, the parameters and
    the adapter revision — never the generated text.
    """
    engine = _engine(chat=_chat_body('{"a": 1}'))

    result = engine.structured("smollm2:latest", "p", {"type": "object"})

    assert result.value is not None
    assert result.evidence.terms["model"] == "smollm2:latest"
    assert len(result.evidence.terms["model_revision"]) == 64
    assert result.evidence.observed["done_reason"] == "stop"
    assert result.evidence.observed["attempts"] == 1
    assert result.evidence.measurements["completion_tokens"] == 7.0
    assert result.evidence.measurements["prompt_tokens"] == 40.0


def test_the_tag_is_recorded_alongside_the_digest() -> None:
    """An operator can see which name produced a run, and which bytes answered."""
    result = _engine(chat=_chat_body('{"a": 1}')).structured(
        "smollm2:latest", "p", {"type": "object"}
    )

    assert result.evidence.terms["model"] == "smollm2:latest"
    assert result.evidence.terms["model_revision"] != "smollm2:latest"


# --- Criterion: the digest is compared for the whole run --------------------


def test_a_mid_run_swap_is_visible_as_a_difference() -> None:
    """A tag that resolves to different bytes is reported as a change.

    This is row 13's assertion without needing to pull anything: the second
    resolution disagrees with the first, and the disagreement is in the evidence
    rather than having to be remembered. The adapter is asked twice and the digest
    differs between the answers.
    """
    engine = OllamaEngine(base_url="http://stub", client=_SwappingClient())

    first = engine.capabilities("qwen2.5")
    second = engine.capabilities("qwen2.5")

    assert first.value is not None and second.value is not None
    assert (
        first.value.observed["model_revision"]
        != second.value.observed["model_revision"]
    )
    assert second.value.observed["revision_changed"] is True
    assert (
        second.value.observed["first_seen_revision"]
        == first.value.observed["model_revision"]
    )


def test_an_unchanged_model_is_not_reported_as_changed() -> None:
    """The pair above: a stable model reports no change.

    Without this, an implementation that always answered ``revision_changed: True``
    would satisfy the swap test while making the flag meaningless.
    """
    engine = _engine()

    first = engine.capabilities("smollm2:latest")
    second = engine.capabilities("smollm2:latest")

    assert first.value is not None and second.value is not None
    assert second.value.observed["revision_changed"] is False


# --- Criterion: evidence carries what a test may assert on ------------------


def test_the_evidence_reports_num_ctx_params_and_the_adapter_revision() -> None:
    """The four terms `kernel-cli.md` §7 names travel with the call.

    A sampled kernel's value is not assertable, so this is the whole assertion
    surface: without these the class is declared but not *observable*, and a
    resume cannot tell a re-run from a different run.
    """
    engine = _engine(chat=_chat_body('{"a": 1}'))

    result = engine.structured("smollm2:latest", "p", {"type": "object"})

    assert result.value is not None
    observed = result.evidence.observed
    assert "num_ctx" in observed
    assert isinstance(observed["params"], dict)
    assert observed["adapter_revision"].startswith("ollama ")
    assert result.evidence.terms["adapter_revision"] == observed["adapter_revision"]


def test_num_ctx_is_the_loaded_window_and_not_the_declared_one() -> None:
    """``num_ctx`` reports what the runtime *loaded*, or ``None`` if not loaded.

    The two differ in practice — a model declaring 8192 loads under 4096 — so
    reporting the declared figure would be reporting a number nothing used. The
    stub reports no loaded models, and ``None`` is the honest answer.
    """
    engine = _engine(chat=_chat_body('{"a": 1}'))

    result = engine.structured("smollm2:latest", "p", {"type": "object"})

    assert result.value is not None
    assert result.evidence.observed["num_ctx"] is None


def test_num_ctx_is_reported_when_the_model_is_loaded() -> None:
    """A loaded model's window is reported as the integer the runtime loaded it at.

    The pair with the test above proves ``None`` means *not loaded* rather than
    *never reported*.
    """
    client = _StubClient(chat=_chat_body('{"a": 1}'))
    client.loaded_context_length = 4096
    engine = OllamaEngine(base_url="http://stub", client=client)

    result = engine.structured("smollm2:latest", "p", {"type": "object"})

    assert result.value is not None
    assert result.evidence.observed["num_ctx"] == 4096


def test_num_ctx_is_the_window_this_call_loaded_the_model_at(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``num_ctx`` is read after the call, so it is this call's window.

    A pre-call read reports the *previous* call's window: the model was loaded at
    4096, this call asks for 1024, and reading before the call would report 4096
    while the `params` beside it said 1024 — evidence that contradicts itself.
    """
    monkeypatch.setenv("DOCFLOW_OLLAMA_NUM_CTX", "1024")
    client = _StubClient(chat=_chat_body('{"a": 1}'))
    client.preloaded_context_length = 4096
    engine = OllamaEngine(base_url="http://stub", client=client)

    result = engine.structured("smollm2:latest", "p", {"type": "object"})

    assert result.value is not None
    assert result.evidence.observed["num_ctx"] == 1024
    assert result.evidence.observed["params"]["num_ctx"] == 1024


def test_the_prompt_measurement_is_recorded_so_silent_input_truncation_is_visible() -> (
    None
):
    """Both the characters sent and the tokens evaluated are reported.

    The runtime **cuts an oversized prompt silently** — measured, a 2,429-token
    prompt against a 256-token window was evaluated as 130 tokens and answered with
    ``done_reason: "stop"``. The adapter cannot decide whether that happened without
    a tokenizer, and a characters-per-token constant would be the kernel inventing a
    threshold. So both numbers are recorded and the discrepancy is left visible.
    """
    engine = _engine(chat=_chat_body('{"a": 1}', prompt_eval_count=130))

    result = engine.structured("smollm2:latest", "x" * 8000, {"type": "object"})

    assert result.value is not None
    assert result.evidence.measurements["prompt_characters"] == 8000.0
    assert result.evidence.measurements["prompt_tokens"] == 130.0, (
        "the evaluated count is what the runtime actually read, and it is recorded "
        "beside the characters sent so a caller can see they disagree"
    )


def test_a_complete_generation_is_not_reported_as_truncated() -> None:
    """``done_reason: stop`` with a small prompt parses, and claims no cut.

    The pair that keeps the input-truncation record from being read as *always
    suspicious*: the two measurements agree here, and the value is returned.
    """
    engine = _engine(chat=_chat_body('{"a": 1}', prompt_eval_count=12))

    result = engine.structured("smollm2:latest", "short prompt", {"type": "object"})

    assert result.reason is None
    assert result.value is not None
    assert result.evidence.observed["done_reason"] == "stop"
    assert result.evidence.measurements["prompt_characters"] == 12.0


def test_warm_offers_the_same_options_a_real_call_will_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``warm`` loads the model under the window a later call will use.

    Warming with different options loads the model only to have the first real call
    reload it, which is the cold start warming exists to avoid. The environment is
    set here because with no options declared the two bodies would agree by
    accident, and the mutation that breaks this would survive.
    """
    monkeypatch.setenv("DOCFLOW_OLLAMA_NUM_CTX", "2048")
    monkeypatch.setenv("DOCFLOW_OLLAMA_TEMPERATURE", "0.0")
    client = _StubClient(chat=_chat_body('{"a": 1}'))
    engine = OllamaEngine(base_url="http://stub", client=client)

    engine.warm("smollm2:latest")
    engine.structured("smollm2:latest", "p", {"type": "object"})

    warm_body, call_body = (body for method, body in client.calls if method == "POST")
    assert warm_body["options"].get("num_predict") == 1, "warm asks for one token only"
    for name in ("num_ctx", "temperature"):
        assert warm_body["options"].get(name) == call_body["options"].get(name), (
            f"warm and a real call disagree on {name!r}, so the first call would "
            "reload the model"
        )
    assert warm_body["options"]["num_ctx"] == 2048, "the declared window is forwarded"


def test_no_adapter_revision_is_invented_when_the_runtime_will_not_say() -> None:
    """An unreadable version is ``"ollama unknown"``, never a plausible build.

    A fabricated revision would enter the cache key and make two different engines
    share a key, which is the same class of mistake as keying on a moving tag.
    """
    client = _StubClient(chat=_chat_body('{"a": 1}'))
    client.version_unavailable = True
    engine = OllamaEngine(base_url="http://stub", client=client)

    result = engine.structured("smollm2:latest", "p", {"type": "object"})

    assert result.value is not None
    assert result.evidence.observed["adapter_revision"] == "ollama unknown"


# --- Self-grading is refused on this path too -------------------------------


def test_a_model_grading_its_own_output_is_refused() -> None:
    """``judge`` refuses when the grader produced the samples.

    The prohibition belongs to the escalation ladder, but the guard is not worth
    withholding from the path that can also reach it.
    """
    engine = _engine(chat=_chat_body('{"grade": "ok"}'))

    result = engine.judge(
        "smollm2:latest", "rubric", [{"x": 1}], produced_by="smollm2:latest"
    )

    assert result.value is None
    assert result.reason is not None
    assert result.reason.code == "role_conflict"


def test_the_self_grading_guard_ignores_the_tag() -> None:
    """``smollm2`` grading ``smollm2:latest`` is still self-grading.

    A guard that compared the raw strings would be defeated by a tag, which is the
    same class of mistake as treating the tag as the model's identity.
    """
    engine = _engine(chat=_chat_body('{"grade": "ok"}'))

    result = engine.judge("smollm2", "rubric", [{"x": 1}], produced_by="smollm2:latest")

    assert result.value is None
    assert result.reason is not None
    assert result.reason.code == "role_conflict"


def test_a_different_model_may_grade() -> None:
    """A grader that did not produce the samples is allowed to run.

    The pair with the two tests above: the guard refuses a match, not every call.
    """
    engine = _engine(chat=_chat_body('{"grade": "ok"}'))

    result = engine.judge(
        "qwen2.5vl:3b", "rubric", [{"x": 1}], produced_by="smollm2:latest"
    )

    assert result.reason is None, "a different model is a legitimate grader"


# --- No secret, no invented setting -----------------------------------------


def test_no_operation_takes_a_credential() -> None:
    """No signature carries an API key or a secret.

    Secrets come from the environment only. A parameter would put one on a command
    line and into a process listing (`kernel-cli.md` §9, K6).
    """
    import inspect  # pylint: disable=import-outside-toplevel

    for name in ("capabilities", "warm", "structured", "vision", "judge"):
        signature = inspect.signature(getattr(OllamaEngine, name))
        for parameter in signature.parameters:
            assert "key" not in parameter.lower()
            assert "secret" not in parameter.lower()
            assert "token" not in parameter.lower()


def test_the_constructor_defaults_the_address_but_never_a_model() -> None:
    """The runtime's *address* is defaulted; no model ever is.

    A wrong address fails loudly and immediately. A substituted model would not,
    which is why one is a setting and the other is forbidden.
    """
    engine = OllamaEngine()

    assert engine._base_url.startswith("http")  # pylint: disable=protected-access
    assert not hasattr(engine, "model")
    assert not hasattr(engine, "default_model")


# --- The reason vocabulary ---------------------------------------------------


def test_every_reason_code_raised_here_is_in_the_closed_set() -> None:
    """The codes this adapter can raise are the ones `kernel-cli.md` §5 declares."""
    # pylint: disable=import-outside-toplevel
    from docflow.adapters import ollama as module

    closed_set = {
        "model_not_pulled",
        "model_unknown",
        "truncated_output",
        "engine_unavailable",
        "unsupported_format",
        "role_conflict",
    }
    declared = {
        value for name, value in vars(module).items() if name.startswith("_CODE_")
    }

    assert declared, "the adapter declares reason codes, so this is not vacuous"
    assert declared <= closed_set, (
        f"codes outside the closed set: {declared - closed_set}"
    )


# --- Live runtime, when one is reachable ------------------------------------


def _runtime_is_up() -> bool:
    """Report whether an Ollama runtime answers on the default address.

    Returns:
        ``True`` when it responds.

    """
    try:
        # pylint: disable=import-outside-toplevel
        import httpx

        return (
            httpx.get("http://127.0.0.1:11434/api/version", timeout=2).status_code
            == 200
        )
    except Exception:  # pylint: disable=broad-exception-caught
        return False


@pytest.mark.skipif(not _runtime_is_up(), reason="no Ollama runtime is reachable")
def test_live_the_digest_is_a_real_identity() -> None:
    """Against a real runtime, the digest is 64 hex characters and not the tag.

    This is the assertion a stub cannot make: the digest comes from the runtime's
    catalogue, and only a live call proves the adapter reads the right endpoint.
    """
    engine = OllamaEngine()

    catalogue = engine.capabilities("smollm2:latest")
    if catalogue.value is None:
        pytest.skip(f"smollm2 is not pulled: {catalogue.reason.code}")

    revision = str(catalogue.value.observed["model_revision"])
    assert len(revision) == 64
    assert all(c in "0123456789abcdef" for c in revision)
    assert revision != "smollm2:latest"
