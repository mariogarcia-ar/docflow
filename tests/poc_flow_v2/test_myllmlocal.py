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

import pytest
from myllmlocal import (  # pylint: disable=import-outside-toplevel
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

#: A document that looks like a receipt. The classifier no longer gates the call,
#: so the text is chosen to be *plausible*, not to pass a gate.
DOCUMENT_BODY = "FACTURA A CUIT 20-22087601-3 TOTAL 17.898,30"


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
