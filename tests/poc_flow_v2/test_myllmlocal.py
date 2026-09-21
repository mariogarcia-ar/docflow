"""The K5 lane probe: one document, one prompt, one answer.

Each test guards one thing `myllmlocal.py` promises, and each is paired with a
mutation in `mutation_invariants.py` — a test that only passes when the code is
correct proves nothing (B.16).

The subject is the **wiring**, not the model: a real generation would prove the
model, and every route here ends in a `flow` function that another suite already
covers. What is guarded is that this client *reaches* those functions with the
right document and the right prompt.
"""

from __future__ import annotations

import pathlib
from types import SimpleNamespace

import pytest
from flow.fields import ESC_DEGRADED_MATERIAL
from flow.material import TIER_DEGRADED, TIER_NATIVE, Material
from myllmlocal import (  # pylint: disable=import-outside-toplevel
    TEXT_PLACEHOLDER,
    Inputs,
    UsageError,
    _exit_code,
    _material,
    _substituted,
    ask,
)

from docflow.kernels.types import Evidence, KernelResult


def _inputs(template: str = "") -> Inputs:
    """A resolved input pair, with a template that carries the document."""
    return Inputs(
        prompt=template or f"Resumí este documento:\n{TEXT_PLACEHOLDER}",
        prompt_source="given (a test)",
        schema={"type": "object", "properties": {}, "required": []},
        schema_source="given (a test)",
        registry=None,
    )


def _material_with(
    *,
    tier: str,
    text: str | None,
    route: str,
    pages_read: int,
    notes: list[str] | None = None,
) -> Material:
    """A PDF material a stand-in reader answers, so a test states only its case.

    One builder, because the record's eight fields are the contract and a test
    that spelled them all out would fail on the field it never meant to describe.
    """
    return Material(
        kind="pdf",
        tier=tier,
        text=text,
        route=route,
        pages_read=pages_read,
        pages_total=1,
        images=[],
        notes=list(notes) if notes else [],
    )


# The two stand-ins below exist for their single method each; the rule expects a
# class with a public surface, which a double deliberately does not have.
# pylint: disable=too-few-public-methods


class _RecordingEngine:
    """A stand-in engine that records the prompt it was handed.

    It answers with one value and the measurements a real call reports, so the
    caller walks its whole path without a runtime and without a model.
    """

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def structured(self, _model, prompt, _schema):
        """Record the prompt and answer with a value."""
        self.prompts.append(prompt)
        return KernelResult(
            value={"resumen": "una respuesta"},
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
        """Refuse, the way the runtime refuses a model that was never pulled."""
        return SimpleNamespace(
            value=None,
            reason=SimpleNamespace(code="model_not_pulled", message="absent"),
            evidence=Evidence(terms={}, measurements={}, observed={}),
        )


def test_a_text_file_is_read_directly(tmp_path: pathlib.Path) -> None:
    """A text file's material is read here, not by `read_material`.

    Measured, this is the defect it closes: `flow.material.read_material` answers
    a text file with `invalid` — *neither a PDF nor an image* — so routing a text
    file through it would report every document of the first case as unreadable.
    `read_material` is replaced by a raiser, so a client that reached it would
    fail here instead of quietly degrading.
    """
    source = tmp_path / "factura.txt"
    source.write_text("FACTURA A CUIT 20-22087601-3 TOTAL 17.898,30", encoding="utf-8")

    material = _material(source)

    assert material.kind == "text", "a text file must be read here, not by K2"
    assert material.tier == TIER_NATIVE
    assert material.text == source.read_text(encoding="utf-8")


def test_a_pdf_reaches_the_flows_own_reader(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A PDF is read by `read_material`, never by a second reader.

    The spy is what makes this falsifiable: a client that grew its own PDF branch
    would never call the flow's reader, and this test would fail naming the call
    that did not happen.
    """
    seen: list[pathlib.Path] = []

    def _spy(path: pathlib.Path, config=None) -> Material:  # pylint: disable=unused-argument
        """Record the path and answer a material, without touching an engine."""
        seen.append(path)
        return _material_with(
            tier=TIER_NATIVE,
            text="FACTURA A",
            route="layout_text",
            pages_read=1,
        )

    monkeypatch.setattr("flow.material.read_material", _spy)
    source = tmp_path / "comprobante.pdf"
    source.write_bytes(b"%PDF-1.4 not really")

    material = _material(source)

    assert seen == [source], "the flow's own reader is what a PDF must reach"
    assert material.route == "layout_text"


def test_the_document_text_reaches_the_model(tmp_path: pathlib.Path) -> None:
    """The prompt the model receives carries the document's own text.

    The whole point of the client is *this document* and *this prompt*. A
    substitution that dropped the text would still produce a plausible answer,
    which is why the assertion is on the string that was **sent**.
    """
    source = tmp_path / "factura.txt"
    source.write_text("CUIT 20-22087601-3 TOTAL 17.898,30", encoding="utf-8")
    engine = _RecordingEngine()

    report = ask(source, _inputs(), model="un-modelo", engine=engine)

    assert len(engine.prompts) == 1, "one document, one call"
    assert "20-22087601-3" in engine.prompts[0], (
        "the document's text never reached the prompt"
    )
    assert TEXT_PLACEHOLDER not in engine.prompts[0], (
        "the placeholder was left in the prompt, so the model was asked about a "
        f"literal {TEXT_PLACEHOLDER!r}"
    )
    assert report["answer"] == {"resumen": "una respuesta"}


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


def test_a_document_with_no_text_never_reaches_a_model(
    tmp_path: pathlib.Path,
) -> None:
    """A material that produced no text is reported, and nothing is paid for.

    A whitespace-only file is the case a truthiness check would let through: the
    string is non-empty, so the model would be asked about a document that is not
    there — and the answer would look like a reading.
    """
    source = tmp_path / "vacio.txt"
    source.write_text("   \n\n", encoding="utf-8")
    engine = _RecordingEngine()

    report = ask(source, _inputs(), model="un-modelo", engine=engine)

    assert not engine.prompts, "a document with no text must not cost a call"
    assert report["answer"] is None
    assert report["call"]["refusal"] == "blank_page", (
        "reading it and finding nothing is a different fact from failing to read it"
    )


def test_a_degraded_material_names_its_own_reason(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """*We could not read it* and *it was blank* are kept apart (B.9).

    Both are refusals with no call, and collapsing them into one code would tell
    a caller that a document nobody managed to read is a blank one.
    """

    def _degraded(path: pathlib.Path, config=None) -> Material:  # pylint: disable=unused-argument
        """Answer the material K2 answers when nothing could be read."""
        return _material_with(
            tier=TIER_DEGRADED,
            text=None,
            route="",
            pages_read=0,
            notes=["encrypted"],
        )

    monkeypatch.setattr("flow.material.read_material", _degraded)
    source = tmp_path / "protegido.pdf"
    source.write_bytes(b"%PDF-1.4")

    report = ask(source, _inputs(), model="un-modelo", engine=_RecordingEngine())

    assert report["call"]["refusal"] == ESC_DEGRADED_MATERIAL
    assert "encrypted" in report["call"]["message"], (
        "the read's own reason must survive into the report"
    )


def test_a_refused_call_is_a_report_and_never_an_exception(
    tmp_path: pathlib.Path,
) -> None:
    """A refusal is an answer with its code, and the exit code says so.

    `kernel-cli.md` §5 reserves exit 2 for a typed refusal, and a client that
    raised instead would report *the code has a bug* about a model that simply
    was not pulled.
    """
    source = tmp_path / "factura.txt"
    source.write_text("FACTURA A CUIT 20-22087601-3", encoding="utf-8")

    report = ask(source, _inputs(), model="no-existe:1b", engine=_RefusingEngine())

    assert report["answer"] is None
    assert report["call"]["refusal"] == "model_not_pulled"
    assert _exit_code(report) == 2, "a typed refusal is exit 2, never a traceback"


def test_an_unmeasured_number_stays_none_instead_of_becoming_zero(
    tmp_path: pathlib.Path,
) -> None:
    """A refusal before the request left has no prompt tokens — not zero.

    ``0.0`` is a real reading (a prompt the runtime evaluated as nothing), so
    substituting it for a number nothing took would make *unmeasurable* and
    *empty* the same figure. The assertion is on the **report a refusal
    produces**, not on the helper: a helper-level test would pass with the
    report writing zeros beside it, which is the shape a consumer reads.
    """
    source = tmp_path / "factura.txt"
    source.write_text("FACTURA A CUIT 20-22087601-3", encoding="utf-8")

    report = ask(source, _inputs(), model="no-existe:1b", engine=_RefusingEngine())

    assert report["call"]["prompt_tokens"] is None
    assert report["call"]["num_ctx"] is None
    assert report["call"]["refusal"] == "model_not_pulled"
