"""The K5 lane probe: one document, one prompt, one answer.

Each test guards one promise of `myllmlocal.py`, and a test that only passes when
the code is correct proves nothing — the mutations that falsify them live in
`mutation_invariants.py`.

The subject is the **wiring**, not the model: a real generation would prove the
model, and every route here ends in a `flow` function another suite already
covers. What is guarded is that this client reaches the flow's reader with the
document, and the model with the prompt the caller named.
"""

from __future__ import annotations

import json
import pathlib
from types import SimpleNamespace

import myllmlocal as client_module  # pylint: disable=import-outside-toplevel
import pytest
from myllmlocal import (  # pylint: disable=import-outside-toplevel
    DIGEST_LENGTH,
    ENV_STEM,
    PROPOSAL_PLACEHOLDER,
    TEXT_PLACEHOLDER,
    Text,
    UsageError,
    _direct,
    _document_text,
    _substituted,
)
from myllmlocal import main as client_main

from docflow.kernels.types import Evidence, KernelResult

#: A prompt that carries the document, so a test states only its own case.
PROMPT_BODY = f"Extraé el total:\n{TEXT_PLACEHOLDER}"

#: A reviewer's prompt: the two placeholders `registry/prompts/review/invoice.txt`
#: carries. Both are asserted, because a reviewer that received the literal
#: `{proposal}` would report verdicts about that string rather than an extraction.
REVIEW_PROMPT_BODY = (
    f"--- DOCUMENT TEXT ---\n{TEXT_PLACEHOLDER}\n--- END ---\n"
    f"--- PROPOSED EXTRACTION ---\n{PROPOSAL_PLACEHOLDER}\n--- END ---"
)

#: The extraction a reviewer judges, as a caller would hand it over.
PROPOSAL_BODY = {"total": "17.898,30", "cuit_emisor": "20-22087601-3"}

#: A document that looks like a receipt. The classifier no longer gates the call,
#: so the text is chosen to be *plausible*, not to pass a gate.
DOCUMENT_BODY = "FACTURA A CUIT 20-22087601-3 TOTAL 17.898,30"


@pytest.fixture(autouse=True)
def _reports_beside_the_test(tmp_path: pathlib.Path) -> None:
    """Point the default report directory at the test's own temporary tree.

    Every run saves its report now, so without this the suite would deposit files
    in the repository's `var/llmlocal/` — the real default, exercised by accident
    rather than asserted. `--out` overrides it wherever a test is *about* the
    location; this only keeps a test that is about something else from writing
    where an operator's runs go.
    """
    client_module.DEFAULT_OUT = tmp_path / "llmlocal"


def _write(tmp_path: pathlib.Path, name: str, body: str) -> pathlib.Path:
    """Write a file beside the test and return its path."""
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


# The stand-ins below exist for their single method each; the rule expects a class
# with a public surface, which a double deliberately does not have.
# pylint: disable=too-few-public-methods


class _RecordingEngine:
    """A stand-in engine that records what it was handed.

    It answers with one value and the measurements a real call reports, so the
    caller walks its whole path without a runtime and without a model.
    """

    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.schemas: list[object] = []

    def structured(self, _model, prompt, schema):
        """Record the prompt and the schema, then answer with a value."""
        self.prompts.append(prompt)
        self.schemas.append(schema)
        return KernelResult(
            value={"total": "17.898,30"},
            evidence=Evidence(
                terms={},
                measurements={"prompt_tokens": 10.0, "completion_tokens": 4.0},
                observed={"num_ctx": 8192, "done_reason": "stop"},
            ),
            reason=None,
        )


class _RefusingEngine:
    """A stand-in engine whose call is refused with a typed reason."""

    def structured(self, _model, _prompt, _schema):
        """Refuse the way the runtime refuses a model that was never pulled."""
        return SimpleNamespace(
            value=None,
            reason=SimpleNamespace(code="model_not_pulled", message="absent"),
            evidence=Evidence(terms={}, measurements={}, observed={}),
        )


def test_a_text_file_is_read_directly(tmp_path: pathlib.Path) -> None:
    """A text file's text is read here, not by `read_material`.

    Measured, this is the defect it closes: `flow.material.read_material` answers
    a text file with `invalid` — *neither a PDF nor an image* — so routing a text
    file through it would report every document of the first case as unreadable.
    """
    source = _write(tmp_path, "factura.txt", DOCUMENT_BODY)

    text = _document_text(source)

    assert text.route == "direct", "a text file must be read here, not by K2"
    assert text.body == DOCUMENT_BODY


def test_a_pdf_reaches_the_flows_own_reader(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A PDF is read by `read_material`, never by a second reader.

    The spy is what makes this falsifiable: a client that grew its own PDF branch
    would never call the flow's reader, and this test would fail naming the call
    that did not happen.
    """
    seen: list[pathlib.Path] = []

    def _spy(path: pathlib.Path, config=None):  # pylint: disable=unused-argument
        """Record the path and answer a material, without touching an engine."""
        seen.append(path)
        return SimpleNamespace(text="FACTURA A", route="layout_text", notes=[])

    monkeypatch.setattr("flow.material.read_material", _spy)
    source = tmp_path / "comprobante.pdf"
    source.write_bytes(b"%PDF-1.4 not really")

    text = _document_text(source)

    assert seen == [source], "the flow's own reader is what a PDF must reach"
    assert text.route == "layout_text"


def test_the_document_text_reaches_the_model(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The prompt the model receives carries the document's own text.

    The whole point of the client is *this document* and *this prompt*. A
    substitution that dropped the text would still produce a plausible answer,
    which is why the assertion is on the string that was **sent**.
    """
    source = _write(tmp_path, "factura.txt", DOCUMENT_BODY)
    prompt = _write(tmp_path, "prompt.txt", PROMPT_BODY)
    engine = _RecordingEngine()
    monkeypatch.setattr("myllmlocal._engine", lambda: engine)

    code = client_main([str(source), "--prompt", str(prompt), "--model", "un-modelo"])

    assert code == 0, "a value came back, so the exit code is 0"
    assert len(engine.prompts) == 1, "one document, one call"
    assert "20-22087601-3" in engine.prompts[0], (
        "the document's text never reached the prompt"
    )
    assert TEXT_PLACEHOLDER not in engine.prompts[0], (
        "the placeholder was left in the prompt, so the model was asked about a "
        f"literal {TEXT_PLACEHOLDER!r}"
    )


def test_a_prompt_without_the_placeholder_is_refused() -> None:
    """A prompt that cannot carry the document is a usage error, not a call.

    Without this, the model is asked the template's own question, answers
    plausibly, and nothing in the result says the document was never sent.
    """
    with pytest.raises(UsageError) as raised:
        _substituted("resumí el documento", "cualquier texto")

    assert TEXT_PLACEHOLDER in str(raised.value), (
        "the refusal must name the placeholder that is missing"
    )


def test_a_prompt_without_the_placeholder_never_reaches_the_model(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same refusal, seen from the console: exit 4 and no call made."""
    source = _write(tmp_path, "factura.txt", DOCUMENT_BODY)
    prompt = _write(tmp_path, "prompt.txt", "resumí el documento")
    engine = _RecordingEngine()
    monkeypatch.setattr("myllmlocal._engine", lambda: engine)

    code = client_main([str(source), "--prompt", str(prompt)])

    assert code == 4, "a malformed invocation is exit 4, not a statement about a file"
    assert not engine.prompts, "no model may be paid for a prompt that cannot carry it"


def test_the_schema_is_an_object_when_the_caller_names_none(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no `--schema` the answer only has to be an object.

    The prompt is what asks for the shape. A default naming the registry's fields
    would be this client deciding which question the caller asked — which is how
    `--prompt invoice_deteccion.txt` came to answer the *base* extraction.
    """
    source = _write(tmp_path, "factura.txt", DOCUMENT_BODY)
    prompt = _write(tmp_path, "prompt.txt", PROMPT_BODY)
    engine = _RecordingEngine()
    monkeypatch.setattr("myllmlocal._engine", lambda: engine)

    client_main([str(source), "--prompt", str(prompt)])

    assert engine.schemas == [{"type": "object"}], (
        "the caller's prompt alone must not be paired with a schema nobody asked for"
    )


def test_a_caller_schema_is_the_one_that_is_sent(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A schema the caller names is what the model is constrained by."""
    source = _write(tmp_path, "factura.txt", DOCUMENT_BODY)
    prompt = _write(tmp_path, "prompt.txt", PROMPT_BODY)
    declared = {"type": "object", "properties": {"total": {"type": "string"}}}
    schema = _write(tmp_path, "fields.json", json.dumps(declared))
    engine = _RecordingEngine()
    monkeypatch.setattr("myllmlocal._engine", lambda: engine)

    client_main([str(source), "--prompt", str(prompt), "--schema", str(schema)])

    assert engine.schemas == [declared]


def test_a_document_with_no_text_never_reaches_a_model(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A document that produced no text is reported, and nothing is paid for.

    A whitespace-only file is the case a truthiness check would let through: the
    string is non-empty, so the model would be asked about a document that is not
    there — and the answer would look like a reading.
    """
    source = _write(tmp_path, "vacio.txt", "   \n\n")
    prompt = _write(tmp_path, "prompt.txt", PROMPT_BODY)
    engine = _RecordingEngine()
    monkeypatch.setattr("myllmlocal._engine", lambda: engine)

    client_main([str(source), "--prompt", str(prompt)])

    assert not engine.prompts, "a document with no text must not cost a call"


def test_a_blank_document_is_not_reported_as_unreadable(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A document read and found empty is `blank_page`, not a degraded read.

    The two are different findings (B.9): collapsing them would tell a caller
    that a document nobody managed to read is a blank one.
    """
    source = _write(tmp_path, "vacio.txt", "   \n")
    prompt = _write(tmp_path, "prompt.txt", PROMPT_BODY)

    client_main([str(source), "--prompt", str(prompt)])

    out = json.loads(capsys.readouterr().out)
    assert out["refusal"] == "blank_page"


def test_a_material_that_could_not_be_read_names_the_readers_own_reason(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """A degraded read carries the reader's words, and its own code."""
    source = _write(tmp_path, "protegido.pdf", "%PDF-1.4")
    prompt = _write(tmp_path, "prompt.txt", PROMPT_BODY)

    def _degraded(_path: pathlib.Path, config=None):  # pylint: disable=unused-argument
        """Answer the material K2 answers when nothing could be read."""
        return Text(body=None, route="", notes=["the document is encrypted"])

    monkeypatch.setattr("myllmlocal._document_text", _degraded)

    client_main([str(source), "--prompt", str(prompt)])

    out = json.loads(capsys.readouterr().out)
    assert out["refusal"] == "ESC_DEGRADED_MATERIAL"
    assert "encrypted" in out["message"], (
        "the read's own reason must survive into the report"
    )


def test_a_refused_call_is_a_report_and_never_an_exception(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """A refusal is an answer with its code, and the exit code says so.

    `kernel-cli.md` §5 reserves exit 2 for a typed refusal, and a client that
    raised instead would report *the code has a bug* about a model that simply
    was not pulled.
    """
    source = _write(tmp_path, "factura.txt", DOCUMENT_BODY)
    prompt = _write(tmp_path, "prompt.txt", PROMPT_BODY)
    monkeypatch.setattr("myllmlocal._engine", _RefusingEngine)

    code = client_main([str(source), "--prompt", str(prompt), "--model", "no-existe"])

    assert code == 2, "a typed refusal is exit 2, never a traceback"
    out = json.loads(capsys.readouterr().out)
    assert out["answer"] is None
    assert out["refusal"] == "model_not_pulled"


def test_an_unmeasured_number_stays_none_instead_of_becoming_zero(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """A refusal before the request left has no prompt tokens — not zero.

    ``0.0`` is a real reading (a prompt the runtime evaluated as nothing), so
    substituting it for a number nothing took would make *unmeasurable* and
    *empty* the same figure. The assertion is on the **report a refusal
    produces**, not on a helper: a helper-level test would pass with the report
    writing zeros beside it, which is the shape a consumer reads.
    """
    source = _write(tmp_path, "factura.txt", DOCUMENT_BODY)
    prompt = _write(tmp_path, "prompt.txt", PROMPT_BODY)
    monkeypatch.setattr("myllmlocal._engine", _RefusingEngine)

    client_main([str(source), "--prompt", str(prompt), "--model", "no-existe"])

    out = json.loads(capsys.readouterr().out)
    assert out["call"]["prompt_tokens"] is None
    assert out["call"]["num_ctx"] is None


def test_the_report_carries_no_pipeline_decision(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """The probe does not run the pipeline's receipt gate.

    `flow.classify` decides whether the *run* proceeds. A probe asked one question
    does not make that decision, and carrying its verdict would put a pipeline
    stage's answer in a report about a model call.
    """
    source = _write(tmp_path, "factura.txt", DOCUMENT_BODY)
    prompt = _write(tmp_path, "prompt.txt", PROMPT_BODY)
    monkeypatch.setattr("myllmlocal._engine", _RecordingEngine)

    client_main([str(source), "--prompt", str(prompt)])

    out = json.loads(capsys.readouterr().out)
    assert set(out) == {
        "document",
        "route",
        "characters",
        "prompt",
        "proposal",
        "model",
        "answer",
        "refusal",
        "message",
        "call",
    }, "the report's shape is the contract a consumer reads"


def test_a_missing_prompt_is_exit_four(tmp_path: pathlib.Path) -> None:
    """`--prompt` is required, and a missing one is a malformed invocation."""
    source = _write(tmp_path, "factura.txt", DOCUMENT_BODY)

    with pytest.raises(SystemExit) as stopped:
        client_main([str(source)])

    assert stopped.value.code == 4, "argparse's own exit 2 would read as a refusal"


def test_a_text_file_that_cannot_be_read_reports_it(tmp_path: pathlib.Path) -> None:
    """A text file that cannot be read is reported, never substituted."""
    text = _direct(tmp_path / "no-existe.txt")

    assert text.body is None
    assert text.route == "", "a read that produced nothing ran no operation"
    assert text.notes, "the failure has to say something"


def test_show_env_needs_neither_a_document_nor_a_prompt(capsys) -> None:
    """`--show-env` answers the environment question on its own.

    It exists for the machine where the setup is broken: requiring a document would
    make it unusable exactly where it is needed. The exit code is `0` because the
    question was answered — no document was asked about, so nothing can have been
    refused.
    """
    code = client_main(["--show-env"])

    assert code == 0
    report = json.loads(capsys.readouterr().out)
    assert "effective_options" in report
    assert "sources" in report


def test_show_env_names_where_each_value_came_from(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """The report attributes each option to its source, which is the whole point.

    A report printing only `num_ctx: 8192` leaves *the caller's `.env` was read*,
    *the flow declared it* and *an operator exported it* indistinguishable —
    measured, that ambiguity is what made a `.env` nothing read look like it was
    working. Each case is set up separately here, and the **source string** is what
    is asserted, not the value: two sources can agree on a number and disagree on
    who supplied it.
    """
    from flow.sampling import SAMPLING_ENV_PREFIX

    variable = f"{SAMPLING_ENV_PREFIX}NUM_CTX"
    dotenv = tmp_path / ".env"
    dotenv.write_text(f"{variable}=2048\n", encoding="utf-8")
    monkeypatch.setattr("flow.dotenv.DOTENV_PATH", dotenv)
    monkeypatch.delenv(variable, raising=False)

    client_main(["--show-env"])
    from_file = json.loads(capsys.readouterr().out)
    assert from_file["sources"][variable] == "dotenv"
    assert from_file["effective_options"]["num_ctx"] == "2048"
    assert from_file["variables_set_from_dotenv"] == 1

    monkeypatch.setenv(variable, "4096")
    client_main(["--show-env"])
    exported = json.loads(capsys.readouterr().out)
    assert exported["sources"][variable] == "environment", (
        "an exported variable must outrank the file; reporting it as 'dotenv' "
        "would hide that the export was honoured"
    )
    assert exported["effective_options"]["num_ctx"] == "4096"
    assert exported["variables_set_from_dotenv"] == 0


def test_show_env_with_no_dotenv_reports_the_flows_own_declaration(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """With no file at all, `num_ctx` is attributable to the flow, not to silence.

    The third source, and the one that matters most in a fresh checkout: without a
    distinct label, a run at the flow's default would read the same as a run whose
    file was present and empty.
    """
    from flow.sampling import SAMPLING_ENV_PREFIX

    variable = f"{SAMPLING_ENV_PREFIX}NUM_CTX"
    monkeypatch.setattr("flow.dotenv.DOTENV_PATH", tmp_path / "no-existe.env")
    monkeypatch.delenv(variable, raising=False)

    client_main(["--show-env"])
    report = json.loads(capsys.readouterr().out)

    assert report["dotenv_exists"] is False
    assert report["variables_set_from_dotenv"] == 0
    assert report["sources"][variable] == "flow default"


def test_the_proposal_reaches_a_reviewers_prompt(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--proposal` fills `{proposal}`, and no placeholder survives the fill.

    A reviewer's prompt asks about *this* extraction. When the placeholder is left
    standing the model judges that literal string, and its verdicts describe a
    token rather than a document — the same failure `{text}` is guarded against,
    one placeholder over.
    """
    source = _write(tmp_path, "factura.txt", DOCUMENT_BODY)
    prompt = _write(tmp_path, "review.txt", REVIEW_PROMPT_BODY)
    proposal = _write(tmp_path, "extraction.json", json.dumps(PROPOSAL_BODY))
    engine = _RecordingEngine()
    monkeypatch.setattr("myllmlocal._engine", lambda: engine)

    code = client_main(
        [str(source), "--prompt", str(prompt), "--proposal", str(proposal)]
    )

    assert code == 0, "the call was answered, so nothing was refused"
    assert len(engine.prompts) == 1, "one document, one call"
    assert PROPOSAL_PLACEHOLDER not in engine.prompts[0], (
        "the reviewer was left judging the literal placeholder"
    )
    assert "17.898,30" in engine.prompts[0], (
        "the extraction under review never reached the prompt"
    )
    assert DOCUMENT_BODY in engine.prompts[0], (
        "the reviewer has to judge the extraction against the document it came from"
    )


def test_a_proposal_is_re_serialised_as_a_document(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A JSON object proposal is indented; anything else is passed through.

    Two halves, and the second is what keeps this from becoming this client
    authoring the extraction: re-formatting a value that is not an object — an
    array, a hand-written note — would be inventing the shape the reviewer is
    supposed to judge. The test names a `.txt` file for the pass-through case on
    purpose: the rule is the *content*, not the extension, and a `.txt` holding an
    object is indented like any other.
    """
    source = _write(tmp_path, "factura.txt", DOCUMENT_BODY)
    prompt = _write(tmp_path, "review.txt", REVIEW_PROMPT_BODY)
    engine = _RecordingEngine()
    monkeypatch.setattr("myllmlocal._engine", lambda: engine)

    as_object = _write(tmp_path, "extraction.json", json.dumps(PROPOSAL_BODY))
    client_main([str(source), "--prompt", str(prompt), "--proposal", str(as_object)])
    # The *indentation* is what is asserted, not the key: `json.dumps` writes the
    # compact form with the same `"cuit_emisor": "…"` substring, so an assertion on
    # the key alone would pass with the body passed straight through.
    assert '\n  "cuit_emisor": "20-22087601-3"' in engine.prompts[0], (
        "each key has to sit on its own line, or the reviewer reads one long line"
    )

    as_text = _write(tmp_path, "notas.txt", "el total me parece mal tipeado")
    client_main([str(source), "--prompt", str(prompt), "--proposal", str(as_text)])
    assert "el total me parece mal tipeado" in engine.prompts[1], (
        "a file that is not a JSON object must arrive exactly as it was written"
    )

    # Spaced on purpose: re-serialising this array would tighten it to
    # `["17.898,30"]`, so the spacing is what shows the bytes were left alone.
    as_array = _write(tmp_path, "lineas.json", '[ "17.898,30" ]')
    client_main([str(source), "--prompt", str(prompt), "--proposal", str(as_array)])
    assert '[ "17.898,30" ]' in engine.prompts[2], (
        "valid JSON that is not an object is passed through, never re-shaped"
    )


def test_a_reviewer_with_no_proposal_is_not_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """Without `--proposal` the placeholder holds `null`, and the call still runs.

    A reviewer's template carries a second placeholder, so the guard on `{text}`
    must not extend to it: refusing here would stop the one run an operator wants
    when they are debugging *what the reviewer says about nothing*. The report's
    `proposal` key is what says none was supplied.
    """
    source = _write(tmp_path, "factura.txt", DOCUMENT_BODY)
    prompt = _write(tmp_path, "review.txt", REVIEW_PROMPT_BODY)
    engine = _RecordingEngine()
    monkeypatch.setattr("myllmlocal._engine", lambda: engine)

    client_main([str(source), "--prompt", str(prompt)])

    assert len(engine.prompts) == 1, "the call is made; nothing here is a refusal"
    assert PROPOSAL_PLACEHOLDER not in engine.prompts[0], (
        "an unfilled placeholder still reaches the model as a literal"
    )
    assert "null" in engine.prompts[0]


def test_a_prompt_that_never_names_a_proposal_is_left_alone(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An extraction prompt is not touched by a flag it does not use.

    The substitution is conditional on the placeholder being present, so the fix
    for the reviewer cannot alter what the extraction lanes send.
    """
    source = _write(tmp_path, "factura.txt", DOCUMENT_BODY)
    prompt = _write(tmp_path, "prompt.txt", PROMPT_BODY)
    engine = _RecordingEngine()
    monkeypatch.setattr("myllmlocal._engine", lambda: engine)

    client_main([str(source), "--prompt", str(prompt)])

    assert engine.prompts[0] == f"Extraé el total:\n{DOCUMENT_BODY}", (
        "a prompt with no proposal placeholder must arrive byte for byte"
    )


def test_the_report_is_written_beside_the_other_runs(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """Every run saves the object it prints, under `--out`.

    The point of the file is that a second consumer does not have to reconstruct
    the report from a terminal. The bytes are compared to what stdout carried, not
    to a re-serialisation: two renderings of one report could agree on every field
    and still be different documents.
    """
    out = tmp_path / "reports"
    source = _write(tmp_path, "factura.txt", DOCUMENT_BODY)
    prompt = _write(tmp_path, "prompt.txt", PROMPT_BODY)
    monkeypatch.setattr("myllmlocal._engine", _RecordingEngine)

    client_main([str(source), "--prompt", str(prompt), "--out", str(out)])

    printed = capsys.readouterr().out
    written = list(out.glob("*.json"))
    assert len(written) == 1, "one question, one report file"
    assert written[0].name.startswith("factura."), (
        "the document names the file, so an operator can see whose run it is"
    )
    assert json.loads(written[0].read_text(encoding="utf-8")) == json.loads(printed), (
        "the saved report and the printed one must be the same object"
    )


def test_the_same_question_overwrites_its_own_report_and_no_other(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second run of one question replaces its file; another question adds one.

    Both halves matter. If the name were the document alone, a reviewer's file
    would overwrite the extraction's; if it ignored the document, two documents
    would share one file. The digest is of *which question was asked*, and this is
    the assertion that says so.
    """
    out = tmp_path / "reports"
    source = _write(tmp_path, "factura.txt", DOCUMENT_BODY)
    prompt = _write(tmp_path, "prompt.txt", PROMPT_BODY)
    other = _write(tmp_path, "otro.txt", REVIEW_PROMPT_BODY)
    monkeypatch.setattr("myllmlocal._engine", _RecordingEngine)

    client_main([str(source), "--prompt", str(prompt), "--out", str(out)])
    first = {path.name for path in out.glob("*.json")}
    client_main([str(source), "--prompt", str(prompt), "--out", str(out)])
    assert {path.name for path in out.glob("*.json")} == first, (
        "re-running one question must not accumulate files"
    )

    client_main([str(source), "--prompt", str(other), "--out", str(out)])
    assert len(list(out.glob("*.json"))) == 2, (
        "a different question is a different file, even for the same document"
    )


def test_the_digest_length_is_what_names_the_file(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The file name carries the declared digest length, not an inline literal."""
    out = tmp_path / "reports"
    source = _write(tmp_path, "factura.txt", DOCUMENT_BODY)
    prompt = _write(tmp_path, "prompt.txt", PROMPT_BODY)
    monkeypatch.setattr("myllmlocal._engine", _RecordingEngine)

    client_main([str(source), "--prompt", str(prompt), "--out", str(out)])

    (written,) = out.glob("*.json")
    stem, digest, _ = written.name.split(".")
    assert stem == "factura"
    assert len(digest) == DIGEST_LENGTH, "the digest is as long as it was declared"


def test_a_run_at_the_default_directory_still_saves(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """The default `--out` is a real directory, not a flag with no effect.

    The autouse fixture moves the default for the suite's other tests, so this one
    puts it back and names it: without the assertion, a default that no longer
    reached the save would only be noticed by someone whose run wrote nowhere.
    """
    out = tmp_path / "default-out"
    source = _write(tmp_path, "factura.txt", DOCUMENT_BODY)
    prompt = _write(tmp_path, "prompt.txt", PROMPT_BODY)
    monkeypatch.setattr(client_module, "DEFAULT_OUT", out)
    monkeypatch.setattr("myllmlocal._engine", _RecordingEngine)

    client_main([str(source), "--prompt", str(prompt)])

    assert len(list(out.glob("*.json"))) == 1, (
        "with no --out, the run must save under the default directory"
    )
    assert "saved" in capsys.readouterr().err


def test_show_env_saves_its_report_under_its_own_name(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """`--show-env` has no document, so its file is named for the mode.

    Naming it after a `.txt` or a `.pdf` would be a claim about what the file
    holds; the question it answers is about the environment.
    """
    out = tmp_path / "reports"
    monkeypatch.setattr("flow.dotenv.DOTENV_PATH", tmp_path / "no-existe.env")

    client_main(["--show-env", "--out", str(out)])

    (written,) = out.glob("*.json")
    assert written.name.startswith(f"{ENV_STEM}."), (
        f"a `--show-env` report is saved as {ENV_STEM}.<digest>.json"
    )
    assert json.loads(written.read_text(encoding="utf-8")) == json.loads(
        capsys.readouterr().out
    )


def test_an_unwritable_out_is_exit_four_before_a_model_is_paid(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An `--out` that cannot be written to is a malformed invocation, not a call.

    Refused **before** the generation, which is the half that matters: discovering
    it afterwards would charge the caller for an answer with nowhere to go. A file
    where the directory should be is the case that makes `mkdir` fail.
    """
    source = _write(tmp_path, "factura.txt", DOCUMENT_BODY)
    prompt = _write(tmp_path, "prompt.txt", PROMPT_BODY)
    occupied = _write(tmp_path, "ocupado.txt", "not a directory")
    engine = _RecordingEngine()
    monkeypatch.setattr("myllmlocal._engine", lambda: engine)

    code = client_main([str(source), "--prompt", str(prompt), "--out", str(occupied)])

    assert code == 4, "a path the caller named wrongly is exit 4, never a refusal"
    assert not engine.prompts, "an unwritable --out must not cost a model call"


def test_a_schema_that_is_not_an_object_is_refused(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `--schema` that is valid JSON but not an object is a usage error.

    The refusal names what was read instead of what a schema is: `null` is valid
    JSON, so *is not valid JSON* would send a caller looking for a syntax error
    that is not there.
    """
    source = _write(tmp_path, "factura.txt", DOCUMENT_BODY)
    prompt = _write(tmp_path, "prompt.txt", PROMPT_BODY)
    wrong = _write(tmp_path, "array.json", "[1, 2]")
    engine = _RecordingEngine()
    monkeypatch.setattr("myllmlocal._engine", lambda: engine)

    code = client_main([str(source), "--prompt", str(prompt), "--schema", str(wrong)])

    assert code == 4, "a schema of the wrong shape is a malformed invocation"
    assert not engine.prompts, "the model is not asked under a schema nobody could read"
