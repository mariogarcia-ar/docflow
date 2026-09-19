"""Tests for the frontier ``LlmEngine`` adapter (``E04-06`` / ``S1-T16``).

The transport is stubbed for the invariants, so the suite runs with no provider, no
key and no network. That is not a convenience here — `kernel-cli.md` §11 row 14
explicitly needs an **unreachable provider**, and §12 records that the row has no
committed fixture for exactly that reason. The stub *is* the unreachable provider.

The assertions that matter, one per silent-failure row:

- ``test_the_raw_completion_survives_a_parse_failure`` — row 14's invariant. The
  bytes are captured before the parse and kept when the parse fails, so a parse bug
  cannot become indistinguishable from a model that returned nothing.
- ``test_absence_null_and_a_value_stay_three_outcomes`` — row 14's other half.
- ``test_a_429_records_the_imposed_delay_verbatim`` and
  ``test_an_outage_is_never_reported_as_a_rejection`` — the *provider was down*
  versus *this field is invalid* distinction.
- ``test_a_model_grading_its_own_output_is_refused`` — row 15's `reason.code`.

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
from typing import Final

import pytest

from docflow.adapters._json_object import JSON_ANSWER_INSTRUCTION
from docflow.adapters.frontier import FrontierEngine
from docflow.ports import LlmEngine

# --- A stub transport --------------------------------------------------------

PROVIDER_BODY = {
    "id": "msg_01ABC",
    "model": "claude-sonnet-4-6-20260101",
    "content": [{"type": "tool_use", "name": "emit", "input": {"total": "1500"}}],
    "stop_reason": "tool_use",
    "usage": {"input_tokens": 120, "output_tokens": 18, "total_tokens": 138},
}


class _Response:
    """A minimal response, carrying only what the adapter reads."""

    def __init__(
        self,
        status_code: int,
        body: dict | None = None,
        *,
        headers: dict | None = None,
        raw: bytes | None = None,
    ) -> None:
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.headers = headers or {}
        payload = json.dumps(self._body).encode("utf-8") if raw is None else raw
        self.content = payload
        self.text = payload.decode("utf-8", errors="replace")

    def json(self) -> dict:
        """Return the decoded body, raising on a body that is not JSON.

        Raises:
            ValueError: When the bytes are not a JSON object. A stub that answered
                ``{}`` here would let a test pass against a client that cannot
                exist: a real ``httpx`` response raises on an unparseable body, and
                the adapter's guard exists precisely for that case.

        """
        decoded = json.loads(self.text)
        if not isinstance(decoded, dict):
            raise ValueError("the body is not a JSON object")

        return decoded


class _StubClient:
    """An HTTP client that answers from a prepared response instead of a socket."""

    def __init__(self, response: _Response | None = None) -> None:
        self._response = response
        self.calls: list[tuple[str, dict]] = []
        self.headers_seen: dict | None = None

    def post(
        self, path: str, json: dict | None = None, headers: dict | None = None
    ) -> _Response:
        """Answer a request from the prepared response.

        Args:
            path: The requested path, recorded so a test can assert the route.
            json: The request body, recorded so a test can assert what was sent.
            headers: The request headers, recorded so a test can inspect them.

        Returns:
            The prepared response.

        """
        self.calls.append((path, dict(json or {})))
        self.headers_seen = dict(headers or {})
        if self._response is None:
            return _Response(500, {}, raw=b"no response prepared")

        return self._response


class _DeadClient:
    """A client whose transport is down — the unreachable provider of row 14."""

    def post(  # pylint: disable=unused-argument
        self, path: str, json: dict | None = None, headers: dict | None = None
    ) -> _Response:
        """Fail the way a refused connection fails."""
        raise ConnectionRefusedError("connection refused")


def _body_with(content: list | None, *, stop_reason: str = "tool_use") -> dict:
    """Build a response body with a given content list.

    Args:
        content: The content blocks, or None to omit the key.
        stop_reason: The stop reason.

    Returns:
        The body.

    """
    body = dict(PROVIDER_BODY)
    if content is None:
        body.pop("content", None)
    else:
        body["content"] = content
    body["stop_reason"] = stop_reason

    return body


def _engine(response: _Response | None = None) -> FrontierEngine:
    """Build an adapter over a stub client.

    Args:
        response: The response the stub answers with.

    Returns:
        The adapter.

    """
    return FrontierEngine(base_url="http://stub", client=_StubClient(response))


@pytest.fixture(autouse=True)
def _configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Supply the key and the response ceiling every test needs.

    Both come from the environment by design, so a test that needs them sets them
    rather than passing them to a call.

    Args:
        monkeypatch: The pytest fixture.

    """
    monkeypatch.setenv("DOCFLOW_FRONTIER_KEY", "test-key-not-a-real-one")
    monkeypatch.setenv("DOCFLOW_FRONTIER_MAX_TOKENS", "1024")


# --- The port contract -------------------------------------------------------


def test_the_adapter_satisfies_the_port() -> None:
    """The adapter is structurally an ``LlmEngine``."""
    assert isinstance(_engine(), LlmEngine)


def test_the_adapter_exposes_the_ports_five_operations_and_no_more() -> None:
    """The public operations are the port's five, and nothing was added.

    ``last_call_record`` and ``last_raw_completion`` are deliberately **properties**,
    not operations: ``CallRecord`` cannot ride on ``KernelResult`` (E01 froze three
    fields) and adding a method to the port would re-open `E04-01`'s gate.
    """
    public = {
        name
        for name in vars(FrontierEngine)
        if not name.startswith("_") and callable(getattr(FrontierEngine, name))
    }

    assert public == {"capabilities", "warm", "structured", "vision", "judge"}


# --- No fallback provider ----------------------------------------------------


def test_an_unknown_provider_prefix_is_refused() -> None:
    """A prefix naming no configured provider reports ``provider_unknown``.

    ``openai`` used to be the example of an *unknown* provider; it is now a
    configured one, which is why this test names a provider no build should ever
    speak to. The property under test never was *openai is refused* — it is **the
    refusal happens for a name nothing claims**, and the evidence lists what is
    claimable so a reader can see the difference.
    """
    result = _engine().capabilities("acme:some-model")

    assert result.value is None
    assert result.reason is not None
    assert result.reason.code == "provider_unknown"
    assert "acme" in result.reason.message
    assert "openai" in result.evidence.observed["known_providers"]


def test_a_name_with_no_prefix_is_refused_as_an_unknown_model() -> None:
    """A bare name reports ``model_unknown``, naming what a name should look like."""
    result = _engine().capabilities("claude-sonnet-4-6")

    assert result.value is None
    assert result.reason is not None
    assert result.reason.code == "model_unknown"


def test_no_default_provider_is_substituted() -> None:
    """Neither refusal produces a value, so nothing resolved to a working model.

    The pair with the two tests above: the criterion is not merely that an error is
    raised but that **no default exists to fall back to**. A name whose provider is
    *unknown* and a name with *no* provider must both come back empty — a build that
    answered either from a default would make "there is no fallback" a sentence
    rather than a property.
    """
    for name in ("acme:some-model", "claude-sonnet-4-6", ":", ""):
        result = _engine().capabilities(name)
        assert result.value is None, name


def test_a_known_provider_resolves() -> None:
    """The control: a valid name resolves, so the refusals above are not blanket."""
    result = _engine().capabilities("anthropic:claude-sonnet-4-6")

    assert result.reason is None
    assert result.value is not None
    assert result.value.observed["provider"] == "anthropic"


# --- Row 14: the raw completion is captured before the parse -----------------


def test_the_raw_completion_survives_a_parse_failure() -> None:
    """The bytes are kept when the parse fails, so the two failures stay distinct.

    This is the invariant of row 14. The model returned prose; the parse rejects it.
    Without the raw bytes, *the model returned nothing usable* and *the parse
    rejected what it returned* are the same shape — no value — and the input needed
    to tell them apart is gone.
    """
    engine = _engine(
        _Response(
            200,
            _body_with([{"type": "tool_use", "input": {"a": 1}}]),
            raw=b'{"content": "not the JSON you asked for"}',
        )
    )
    # The body says tool_use with a mapping, but the raw bytes disagree — which is
    # the point: the adapter must report what arrived, not what it hoped for.
    result = engine.structured("anthropic:m", "p", {"type": "object"})

    assert engine.last_raw_completion == b'{"content": "not the JSON you asked for"}'
    assert len(engine.last_raw_completion) > 0
    assert result is not None


def test_the_raw_completion_is_kept_on_success() -> None:
    """A successful call keeps the bytes too, so both outcomes are comparable."""
    engine = _engine(_Response(200, PROVIDER_BODY))

    engine.structured("anthropic:m", "p", {"type": "object"})

    assert engine.last_raw_completion is not None
    assert b"msg_01ABC" in engine.last_raw_completion


def test_the_raw_completion_is_kept_on_a_typed_refusal() -> None:
    """Even a refusal keeps whatever the provider sent."""
    engine = _engine(_Response(429, {}, headers={"retry-after": "30"}))

    engine.structured("anthropic:m", "p", {"type": "object"})

    assert engine.last_raw_completion is not None


def test_the_evidence_reports_the_raw_length() -> None:
    """The length of what arrived is on the evidence, so a test can assert it."""
    engine = _engine(_Response(200, PROVIDER_BODY))

    result = engine.structured("anthropic:m", "p", {"type": "object"})

    assert result.value is not None
    assert result.evidence.observed["raw_completion_bytes"] == float(
        len(engine.last_raw_completion)
    )


# --- Row 14: absence, null and a value are three outcomes --------------------


def test_an_absent_answer_is_never_parsed() -> None:
    """An absence is reported without a parse being attempted.

    Row 14's invariant, made machine-observable: *the model said nothing* and *the
    model said something that would not parse* are different facts, and if neither
    reaches a parser they must still differ in a place a test may assert on — not
    only in a sentence (`kernel-cli.md` §5 forbids asserting on prose).
    """
    engine = _engine(_Response(200, _body_with(None)))

    result = engine.structured("anthropic:m", "p", {"type": "object"})

    assert result.value is None
    assert result.evidence.observed["outcome"] == "absent"
    assert result.evidence.observed["parse_attempted"] is False


def test_an_unparseable_answer_reports_that_a_parse_was_attempted() -> None:
    """The pair above: a text answer *is* handed to a parser.

    Without this, `parse_attempted` could be hardcoded `False` and the test above
    would still pass, while the flag told a reader nothing.
    """
    engine = _engine(_Response(200, _body_with([{"type": "text", "text": "not json"}])))

    result = engine.structured("anthropic:m", "p", {"type": "object"})

    assert result.value is None
    assert result.reason is not None
    assert result.evidence.observed["outcome"] == "value"
    assert result.evidence.observed["parse_attempted"] is True


def test_a_200_with_a_non_json_body_is_a_typed_reason() -> None:
    """A 200 whose body is not JSON is reported, never raised.

    This happens with an intercepting proxy, a captive portal, or a truncated
    response: the status says success and the body is not an answer. It is a fact
    about the provider's response, not about the document — and before this was
    guarded the adapter raised ``ValueError`` straight out of the caller's stack,
    which is the unhandled failure this issue exists to replace with a typed one.
    """
    engine = _engine(_Response(200, {}, raw=b"<html>not an answer</html>"))

    result = engine.structured("anthropic:m", "p", {"type": "object"})

    assert result.value is None
    assert result.reason is not None
    assert result.reason.code == "unsupported_format"
    assert result.evidence.observed["body_is_json"] is False
    assert engine.last_raw_completion == b"<html>not an answer</html>"
    assert engine.last_call_record is not None


def test_an_absent_answer_is_reported_as_absent() -> None:
    """No content at all is ``absent``, and it is not `null`."""
    engine = _engine(_Response(200, _body_with(None)))

    result = engine.structured("anthropic:m", "p", {"type": "object"})

    assert result.value is None
    assert result.reason is not None
    assert result.evidence.observed["outcome"] == "absent"


def test_a_null_field_is_reported_as_null_and_not_as_absent() -> None:
    """A `null` answer returns successfully, carrying `null` — not an absence.

    This is the half that gets collapsed in practice: a `null` is a *value the model
    gave*, and reporting it as an absence loses the fact that the model answered.
    """
    engine = _engine(
        _Response(
            200, _body_with([{"type": "tool_use", "name": "emit", "input": None}])
        )
    )

    result = engine.structured("anthropic:m", "p", {"type": "object"})

    assert result.reason is None
    assert result.value is not None
    assert dict(result.value) == {"value": None}
    assert result.evidence.observed["outcome"] == "null"


def test_a_present_value_is_reported_as_a_value() -> None:
    """The third outcome, so all three are distinguishable side by side."""
    engine = _engine(_Response(200, PROVIDER_BODY))

    result = engine.structured("anthropic:m", "p", {"type": "object"})

    assert result.reason is None
    assert result.value is not None
    assert dict(result.value) == {"total": "1500"}
    assert result.evidence.observed["outcome"] == "value"


def test_the_three_outcomes_are_pairwise_distinguishable() -> None:
    """Absent, `null` and a value differ in *two* independent places.

    The outcome label and the presence of a value both separate them, so an
    implementation that collapsed any pair would fail on at least one assertion.
    """
    absent = _engine(_Response(200, _body_with(None))).structured(
        "anthropic:m", "p", {"type": "object"}
    )
    null = _engine(
        _Response(
            200, _body_with([{"type": "tool_use", "name": "emit", "input": None}])
        )
    ).structured("anthropic:m", "p", {"type": "object"})
    value = _engine(_Response(200, PROVIDER_BODY)).structured(
        "anthropic:m", "p", {"type": "object"}
    )

    assert (absent.value is None, null.value is None, value.value is None) == (
        True,
        False,
        False,
    )
    assert (
        absent.evidence.observed["outcome"],
        null.evidence.observed["outcome"],
        value.evidence.observed["outcome"],
    ) == ("absent", "null", "value")


def test_an_empty_text_block_is_an_absence() -> None:
    """A whitespace-only text block is nothing said, not a value of spaces."""
    engine = _engine(_Response(200, _body_with([{"type": "text", "text": "   "}])))

    result = engine.structured("anthropic:m", "p", {"type": "object"})

    assert result.value is None
    assert result.evidence.observed["outcome"] == "absent"


# --- Truncation ---------------------------------------------------------------


def test_a_max_tokens_stop_is_truncated_and_never_parsed() -> None:
    """``stop_reason: max_tokens`` yields ``truncated_output``, not a value.

    The body below is the dangerous shape: the payload is a complete mapping, so it
    would parse cleanly. Returning it is exactly how a cut answer is reported as a
    whole one.
    """
    engine = _engine(
        _Response(
            200,
            _body_with(
                [{"type": "tool_use", "input": {"a": 1}}], stop_reason="max_tokens"
            ),
        )
    )

    result = engine.structured("anthropic:m", "p", {"type": "object"})

    assert result.value is None
    assert result.reason is not None
    assert result.reason.code == "truncated_output"
    assert result.evidence.observed["stop_reason"] == "max_tokens"


# --- A rate limit and an outage are facts about the provider ----------------


def test_a_429_records_the_imposed_delay_verbatim() -> None:
    """The ``retry-after`` value is reported as given, never reinterpreted.

    Reinterpreting it — into a backoff, a default, or seconds-vs-milliseconds — is
    the silent failure: the caller then waits a different time than the provider
    asked for, and nothing says so.
    """
    engine = _engine(_Response(429, {}, headers={"retry-after": "30"}))

    result = engine.structured("anthropic:m", "p", {"type": "object"})

    assert result.value is None
    assert result.reason is not None
    assert result.reason.code == "provider_unavailable"
    assert result.evidence.observed["retry_after"] == "30", (
        "the value must be the provider's, verbatim — a parsed int 30 and the "
        "string '30' are both acceptable, but a substituted delay is not"
    )
    assert result.evidence.observed["http_status"] == 429


def test_a_429_with_no_retry_after_does_not_invent_one() -> None:
    """An absent header is reported as absent, never defaulted to a number.

    A default delay would be this kernel choosing a policy value, which is exactly
    what `prd.md` FR-15 forbids — and it would be invisible, because the caller
    would see a number and believe the provider sent it.
    """
    engine = _engine(_Response(429, {}, headers={}))

    result = engine.structured("anthropic:m", "p", {"type": "object"})

    assert result.reason is not None
    assert result.reason.code == "provider_unavailable"
    assert result.evidence.observed["retry_after"] is None


def test_an_outage_is_never_reported_as_a_rejection() -> None:
    """An unreachable provider degrades to ``provider_unavailable``, not a refusal.

    This is row 14's *no committed fixture* case: the provider is unreachable
    because the transport is down. The distinction is the whole issue — *the
    provider was down* reads as *this document is invalid* when the two are
    collapsed.
    """
    engine = FrontierEngine(base_url="http://stub", client=_DeadClient())

    result = engine.structured("anthropic:m", "p", {"type": "object"})

    assert result.value is None
    assert result.reason is not None
    assert result.reason.code == "provider_unavailable"
    assert result.reason.code != "unsupported_format", (
        "an outage is not a statement about the document"
    )
    assert "could not be reached" in result.reason.message


def test_a_server_error_is_provider_unavailable_not_a_rejection() -> None:
    """A 5xx is the same class as an outage, and reports the same way."""
    engine = _engine(_Response(503, {}))

    result = engine.structured("anthropic:m", "p", {"type": "object"})

    assert result.reason is not None
    assert result.reason.code == "provider_unavailable"
    assert result.evidence.observed["http_status"] == 503


def test_a_404_is_an_unknown_model() -> None:
    """A model the provider does not know is ``model_unknown``, not an outage."""
    engine = _engine(_Response(404, {}))

    result = engine.structured("anthropic:m", "p", {"type": "object"})

    assert result.reason is not None
    assert result.reason.code == "model_unknown"


def test_a_missing_credential_is_a_typed_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No key configured is reported, not raised."""
    monkeypatch.delenv("DOCFLOW_FRONTIER_KEY", raising=False)
    engine = _engine(_Response(200, PROVIDER_BODY))

    result = engine.structured("anthropic:m", "p", {"type": "object"})

    assert result.value is None
    assert result.reason is not None
    assert result.reason.code == "provider_unavailable"


def test_a_missing_ceiling_is_a_typed_reason_not_a_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No response ceiling configured is reported, never defaulted.

    A default ceiling would be this kernel deciding how much answer the caller
    bought — a policy value, and an invisible one.
    """
    monkeypatch.delenv("DOCFLOW_FRONTIER_MAX_TOKENS", raising=False)
    engine = _engine(_Response(200, PROVIDER_BODY))

    result = engine.structured("anthropic:m", "p", {"type": "object"})

    assert result.value is None
    assert result.reason is not None
    assert result.reason.code == "provider_unavailable"


# --- call_record is always populated ----------------------------------------


def test_the_call_record_is_populated_on_success() -> None:
    """Provider, revision, tokens, latency and request id are all recorded.

    `kernel-cli.md` §7 makes this the assertion surface for an ``external`` kernel:
    the value is not assertable, so the record is what a test may check.
    """
    engine = _engine(_Response(200, PROVIDER_BODY, headers={"request-id": "req_123"}))

    engine.structured("anthropic:m", "p", {"type": "object"})

    record = engine.last_call_record
    assert record is not None
    assert record.provider == "anthropic"
    assert record.model == "m"
    assert record.model_revision == "claude-sonnet-4-6-20260101"
    assert record.prompt_tokens == 120
    assert record.completion_tokens == 18
    assert record.total_tokens == 138
    assert record.latency_ms >= 0
    assert record.request_id == "req_123"


def test_the_call_record_is_populated_on_a_typed_failure() -> None:
    """A failed call still spent latency and reached a revision.

    Reporting no record would make *the call failed* indistinguishable from *no call
    was made*, which is the same collapse this issue exists to prevent.
    """
    engine = _engine(_Response(503, {}))

    engine.structured("anthropic:m", "p", {"type": "object"})

    record = engine.last_call_record
    assert record is not None
    assert record.provider == "anthropic"
    assert record.latency_ms >= 0


def test_unreported_tokens_are_none_and_never_zero() -> None:
    """A field the provider did not report is ``None``, not ``0``.

    ``0`` would read as *the provider said zero tokens*, which is a fact the
    provider never stated. The type says ``None`` means unreported, and honouring
    that is what keeps the two apart.
    """
    engine = _engine(_Response(200, {"content": [{"type": "text", "text": '{"a":1}'}]}))

    engine.structured("anthropic:m", "p", {"type": "object"})

    record = engine.last_call_record
    assert record is not None
    assert record.prompt_tokens is None
    assert record.completion_tokens is None
    assert record.total_tokens is None
    assert record.cost_usd is None, "a rate card is not invented here"


def test_there_is_no_call_record_before_any_call() -> None:
    """``None`` before a call, so *not yet called* is its own state."""
    assert _engine().last_call_record is None
    assert _engine().last_raw_completion is None


# --- Row 15: self-grading ----------------------------------------------------

#: A grade, in the shape a caller would supply from the registry. Used by the judge
#: tests below, and deliberately **not** an empty object: the defect these tests guard
#: was the adapter substituting `{"type": "object"}` for whatever the caller asked.
GRADE: Final[dict[str, object]] = {
    "type": "object",
    "properties": {
        "fields": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        },
    },
    "required": ["fields"],
    "additionalProperties": False,
}


def test_a_model_grading_its_own_output_is_refused() -> None:
    """``judge`` refuses when the grader produced the samples."""
    engine = _engine(_Response(200, PROVIDER_BODY))

    result = engine.judge(
        "anthropic:m", "rubric", [{"x": 1}], produced_by="anthropic:m", schema=GRADE
    )

    assert result.value is None
    assert result.reason is not None
    assert result.reason.code == "role_conflict"


def test_the_self_grading_guard_ignores_the_provider_prefix() -> None:
    """``anthropic:m`` grading ``m`` is still self-grading.

    A guard comparing raw strings would be defeated by a prefix — the same class of
    mistake as treating a prefix as part of the model's identity.
    """
    engine = _engine(_Response(200, PROVIDER_BODY))

    result = engine.judge(
        "anthropic:m", "rubric", [{"x": 1}], produced_by="m", schema=GRADE
    )

    assert result.value is None
    assert result.reason is not None
    assert result.reason.code == "role_conflict"


def test_a_different_model_may_grade() -> None:
    """A grader that did not produce the samples runs.

    The pair with the two tests above: the guard refuses a match, not every call.
    """
    engine = _engine(_Response(200, PROVIDER_BODY))

    result = engine.judge(
        "anthropic:other", "rubric", [{"x": 1}], produced_by="anthropic:m", schema=GRADE
    )

    assert result.reason is None, "a different model is a legitimate grader"


def test_judge_asks_for_the_answer_in_json_and_not_only_in_the_schema() -> None:
    """``judge`` states in words that the grade is JSON.

    **This was a real defect, and the measurement is why the test exists.** The
    schema reaches a provider as a *tool definition*, and a provider that does not
    choose to call the tool answers in prose. Measured against DeepSeek with this
    function's own payload: 1138 completion tokens, `stop_reason: end_turn`, one
    `thinking` block and one `text` block explaining that no source document had
    been supplied — and no `tool_use` block, so the answer was reported
    `unsupported_format` with 5850 bytes of raw completion preserved. The request
    was well-formed and the schema was valid; what was missing was a sentence
    saying the grade is an object.

    **The empty schema is not the cause, so it is not the assertion.** Measured on
    the same provider: `structured(..., {"type": "object"})` returns a value when
    the prompt names the shape, and a 23-property schema *fails* when the prompt
    does not. A test asserting on the schema would therefore have been satisfied by
    a change that fixed nothing.

    The assertion is about the **request body**, like the vision test above: the
    stub is cooperative, so asserting that its JSON parsed would pass with the
    defect fully in place.

    """
    client = _StubClient(_Response(200, PROVIDER_BODY))
    engine = FrontierEngine(base_url="http://stub", client=client)

    engine.judge(
        "anthropic:other", "rubric", [{"x": 1}], produced_by="anthropic:m", schema=GRADE
    )

    _path, sent = client.calls[0]
    prompt = sent["messages"][0]["content"][0]["text"]
    assert JSON_ANSWER_INSTRUCTION in prompt
    # The instruction must reach the model *and* the samples must still follow it,
    # or the fix would trade a parseable answer for no samples to grade.
    assert prompt.endswith('"x": 1}]')
    assert prompt.index(JSON_ANSWER_INSTRUCTION) < prompt.index('"x": 1')


def test_the_judge_instruction_does_not_replace_the_rubric() -> None:
    """The rubric is still sent, before the instruction and the samples.

    The pair with the test above: a request that named the shape and dropped the
    caller's criteria would be a fix that silently changed what was asked.
    """
    client = _StubClient(_Response(200, PROVIDER_BODY))
    engine = FrontierEngine(base_url="http://stub", client=client)

    engine.judge(
        "anthropic:other",
        "weigh it",
        [{"x": 1}],
        produced_by="anthropic:m",
        schema=GRADE,
    )

    _path, sent = client.calls[0]
    prompt = sent["messages"][0]["content"][0]["text"]
    assert prompt.startswith("weigh it")
    assert prompt.index("weigh it") < prompt.index(JSON_ANSWER_INSTRUCTION)


def test_judge_does_not_call_the_model_to_grade_itself() -> None:
    """The refusal happens before the wire, so no call is made at all.

    A guard that refused *after* posting would spend a request and a provider's
    tokens on a call whose answer cannot be used.
    """
    client = _StubClient(_Response(200, PROVIDER_BODY))
    engine = FrontierEngine(base_url="http://stub", client=client)

    engine.judge(
        "anthropic:m", "rubric", [{"x": 1}], produced_by="anthropic:m", schema=GRADE
    )

    assert not client.calls


def test_judge_sends_the_schema_it_was_given() -> None:
    """The grade's shape reaches the provider, and is not an empty object.

    **This is the port change that closed the defect, asserted where it can be lost.**
    ``judge`` used to build its own ``{"type": "object"}`` and drop the caller's
    schema on the floor, so nothing in the request said what a grade was. The failure
    differed by provider and both were measured: the frontier path returned prose and
    reported ``unsupported_format``; the local path **echoed the samples back**, which
    parsed, so the call reported a *value* — the grade was the thing being graded and
    nothing could object.

    The assertion is about the **request body**: a cooperative stub answers the same
    body whatever schema was sent, so a test on the parsed value would pass with the
    defect fully in place.

    """
    client = _StubClient(_Response(200, PROVIDER_BODY))
    engine = FrontierEngine(base_url="http://stub", client=client)

    engine.judge(
        "anthropic:other", "rubric", [{"x": 1}], produced_by="anthropic:m", schema=GRADE
    )

    _path, sent = client.calls[0]
    assert sent["tools"][0]["input_schema"] == GRADE
    assert sent["tools"][0]["input_schema"] != {"type": "object"}


# --- Secrets -----------------------------------------------------------------


def test_no_operation_takes_a_credential() -> None:
    """No signature carries an API key or a secret.

    This is the contract test `plan-01-kernels.md` §8 asks for, at the adapter
    level: secrets come from the environment only, so no call path can take one
    from a command line or a descriptor.
    """
    import inspect  # pylint: disable=import-outside-toplevel

    for name in ("capabilities", "warm", "structured", "vision", "judge"):
        signature = inspect.signature(getattr(FrontierEngine, name))
        for parameter in signature.parameters:
            for forbidden in ("key", "secret", "token", "credential", "password"):
                assert forbidden not in parameter.lower(), f"{name}({parameter})"


def test_the_credential_is_read_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The key reaches the request from the environment, and nowhere else."""
    monkeypatch.setenv("DOCFLOW_FRONTIER_KEY", "from-the-environment")
    client = _StubClient(_Response(200, PROVIDER_BODY))
    engine = FrontierEngine(base_url="http://stub", client=client)

    engine.structured("anthropic:m", "p", {"type": "object"})

    assert client.headers_seen is not None
    assert client.headers_seen["x-api-key"] == "from-the-environment"


def test_the_constructor_defaults_the_address_but_never_a_model() -> None:
    """Each provider's *address* is defaulted; no model ever is.

    The address is now resolved **per provider** rather than stored once, because
    one adapter speaks to several and a single cached URL would send the second
    provider's call to the first one's host.
    """
    # pylint: disable=import-outside-toplevel
    from docflow.adapters.frontier_providers import PROVIDERS

    engine = FrontierEngine()

    for name, provider in PROVIDERS.items():
        url = engine._base_url_for(provider)  # pylint: disable=protected-access
        assert url.startswith("http"), name
        assert not url.endswith("/"), name

    assert not hasattr(engine, "model")
    assert not hasattr(engine, "default_model")


# --- The reason vocabulary ---------------------------------------------------


def test_every_reason_code_raised_here_is_in_the_closed_set() -> None:
    """The codes this adapter can raise are the ones `kernel-cli.md` §5 declares."""
    # pylint: disable=import-outside-toplevel
    from docflow.adapters import frontier as module

    closed_set = {
        "provider_unknown",
        "provider_unavailable",
        "model_unknown",
        "truncated_output",
        "role_conflict",
        "unsupported_format",
    }
    declared = {
        value for name, value in vars(module).items() if name.startswith("_CODE_")
    }

    assert declared, "the adapter declares reason codes, so this is not vacuous"
    assert declared <= closed_set, (
        f"codes outside the closed set: {declared - closed_set}"
    )


# --- The evidence a test may assert on ---------------------------------------


def test_a_failed_call_reports_an_unresolved_model_revision() -> None:
    """A rate limit never learned a revision, and says so instead of guessing.

    A name is not a revision — a hosted model is updated under a fixed name — so
    reporting the name as the revision here would be the same class of mistake as
    keying on a moving tag. The term says ``"unresolved"`` and the name is beside it.
    """
    engine = _engine(_Response(429, {}, headers={"retry-after": "30"}))

    result = engine.structured("anthropic:m", "p", {"type": "object"})

    assert result.reason is not None
    assert result.evidence.terms["model_revision"] == "unresolved"
    assert result.evidence.terms["model_name"] == "m"
    assert result.evidence.terms["adapter_revision"].startswith("anthropic ")


def test_a_resolved_call_reports_the_providers_revision_not_its_name() -> None:
    """On success the revision is the provider's, and it is not the name.

    The pair with the test above: the adapter distinguishes *revision known* from
    *revision unknown* rather than reporting one thing for both.
    """
    engine = _engine(_Response(200, PROVIDER_BODY))

    result = engine.structured("anthropic:m", "p", {"type": "object"})

    assert result.value is not None
    assert result.evidence.terms["model_revision"] == "claude-sonnet-4-6-20260101"
    assert result.evidence.terms["model_revision"] != "m"


def test_the_evidence_carries_the_terms_a_test_may_assert_on() -> None:
    """An ``external`` kernel's value is not assertable; the record and evidence are."""
    engine = _engine(_Response(200, PROVIDER_BODY, headers={"request-id": "req_9"}))

    result = engine.structured("anthropic:m", "p", {"type": "object"})

    assert result.value is not None
    assert result.evidence.terms["provider"] == "anthropic"
    assert result.evidence.terms["model_revision"] == "claude-sonnet-4-6-20260101"
    assert result.evidence.terms["adapter_revision"].startswith("anthropic ")
    assert result.evidence.observed["attempts"] == 1
    assert result.evidence.observed["request_id"] == "req_9"


def test_a_revised_model_is_visible_as_a_difference() -> None:
    """A model updated under a fixed name is reported as a change.

    A hosted model's revision moves without the *name* moving, so the same
    first-seen-versus-now comparison the local adapter makes is what keeps the
    change visible instead of silent.
    """
    client = _StubClient()
    engine = FrontierEngine(base_url="http://stub", client=client)

    first = dict(PROVIDER_BODY) | {"model": "claude-sonnet-4-6-20260101"}
    client._response = _Response(200, first)  # pylint: disable=protected-access
    one = engine.structured("anthropic:m", "p", {"type": "object"})

    second = dict(PROVIDER_BODY) | {"model": "claude-sonnet-4-6-20260201"}
    client._response = _Response(200, second)  # pylint: disable=protected-access
    two = engine.structured("anthropic:m", "p", {"type": "object"})

    assert one.evidence.observed["revision_changed"] is False
    assert two.evidence.observed["revision_changed"] is True
    assert two.evidence.observed["first_seen_revision"] == "claude-sonnet-4-6-20260101"


def test_the_thinking_prefix_is_not_an_accepted_provider() -> None:
    """A near-miss prefix is refused rather than trimmed into a match."""
    result = _engine().capabilities("anthropic2:claude")

    assert result.value is None
    assert result.reason is not None
    assert result.reason.code == "provider_unknown"


def test_warm_confirms_without_generating() -> None:
    """``warm`` reports reachability and makes no generation call."""
    client = _StubClient(_Response(200, PROVIDER_BODY))
    engine = FrontierEngine(base_url="http://stub", client=client)

    result = engine.warm("anthropic:m")

    assert result.value is not None
    assert result.value.observed["warm"] is True
    assert result.value.observed["generation"] is False
    assert not client.calls, "warm must not spend a generation"


def test_warm_reports_a_missing_credential_as_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``warm`` fails the same way a call would when no key is configured."""
    monkeypatch.delenv("DOCFLOW_FRONTIER_KEY", raising=False)
    engine = _engine(_Response(200, PROVIDER_BODY))

    result = engine.warm("anthropic:m")

    assert result.value is None
    assert result.reason is not None
    assert result.reason.code == "provider_unavailable"


def test_an_image_is_encoded_onto_the_message() -> None:
    """A vision call carries the image as base64 on the message."""
    from docflow.kernels.types import Bytes  # pylint: disable=import-outside-toplevel

    client = _StubClient(_Response(200, PROVIDER_BODY))
    engine = FrontierEngine(base_url="http://stub", client=client)

    engine.vision(
        "anthropic:m",
        "describe",
        [Bytes(data=b"png", media_type="image/png")],
        {"type": "object"},
    )

    _path, sent = client.calls[0]
    blocks = sent["messages"][0]["content"]
    image = next(block for block in blocks if block["type"] == "image")
    assert image["source"]["media_type"] == "image/png"
    assert image["source"]["data"] == "cG5n"


def test_a_vision_call_sends_the_schema_it_was_given() -> None:
    """A vision call constrains the answer, and does not merely hope for one.

    **This was a real defect, and it is the reason the test exists.** The schema was
    sent behind `if not vision:`, so `vision` accepted a schema, echoed it back in
    `observed.declared_schema`, and never put it on the wire. Measured with the
    schema withheld: a `tool_use` block and a text block containing JSON both
    parsed — the defect is invisible whenever the model cooperates — while prose
    (*"El total es 7 pesos."*) and a JSON code fence returned `unsupported_format`,
    a failure of *this adapter's parsing* reported against the provider.

    The assertion is deliberately about the **request body** and not about the
    parsed value: asserting that a cooperative stub's JSON parsed says nothing about
    whether a constraint was sent, which is exactly how the defect survived the
    neighbouring image test. The image is asserted present in the same call, so a
    fix that constrained the schema by dropping the pixels cannot pass.

    """
    from docflow.kernels.types import Bytes  # pylint: disable=import-outside-toplevel

    schema = {
        "type": "object",
        "properties": {"total": {"type": "integer"}},
        "required": ["total"],
        "additionalProperties": False,
    }
    client = _StubClient(_Response(200, PROVIDER_BODY))
    engine = FrontierEngine(base_url="http://stub", client=client)

    engine.vision(
        "anthropic:m",
        "describe",
        [Bytes(data=b"png", media_type="image/png")],
        schema,
    )

    _path, sent = client.calls[0]
    tools = sent["tools"]
    assert [tool["name"] for tool in tools] == ["emit"]
    assert tools[0]["input_schema"] == schema
    assert sent["tool_choice"] == {"type": "tool", "name": "emit"}
    # The pixels and the constraint travel together: this is still a vision call.
    assert [b["type"] for b in sent["messages"][0]["content"]] == ["text", "image"]


def test_both_entry_points_send_the_same_schema_constraint() -> None:
    """`structured` and `vision` differ by the images alone, never by the schema.

    The two entry points share one generation path, and the property that makes them
    one operation rather than two is that the constraint is identical. Comparing the
    whole bodies catches a divergence *anywhere* in them, not only the key this suite
    happened to name — the defect this guards against was one `if` around one key.

    """
    from docflow.kernels.types import Bytes  # pylint: disable=import-outside-toplevel

    schema = {"type": "object", "properties": {"total": {"type": "integer"}}}

    def body_of(call: str) -> dict:
        """Return the request body one entry point sends.

        Args:
            call: ``"structured"`` or ``"vision"``.

        Returns:
            The body the adapter posted.

        """
        client = _StubClient(_Response(200, PROVIDER_BODY))
        engine = FrontierEngine(base_url="http://stub", client=client)
        if call == "vision":
            engine.vision(
                "anthropic:m",
                "p",
                [Bytes(data=b"png", media_type="image/png")],
                schema,
            )
        else:
            engine.structured("anthropic:m", "p", schema)
        return client.calls[0][1]

    text_call = body_of("structured")
    image_call = body_of("vision")

    assert text_call["tools"] == image_call["tools"]
    assert text_call["tool_choice"] == image_call["tool_choice"]
    # The one intended difference: the image block rides on the message.
    assert [b["type"] for b in text_call["messages"][0]["content"]] == ["text"]
    assert [b["type"] for b in image_call["messages"][0]["content"]] == [
        "text",
        "image",
    ]
