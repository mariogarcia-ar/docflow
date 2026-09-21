#!/usr/bin/env python
"""One document, one prompt, one local answer: the K5 lane's console probe.

The smallest caller of the v2 flow. A document becomes **text** through the
flow's own routes, the text is substituted into the caller's prompt, and the
local model answers. Nothing else runs: no classification, no lanes, no
decision engine, no registry.

| the input | how it becomes text | whose route |
|---|---|---|
| a text file | read as-is | :func:`_direct`, here |
| a PDF with a text layer | ``pdftotext -layout`` | `flow.material.read_material` |
| a PDF page without one | rendered, then OCR | `flow.material.read_material` |
| an image | legibility gate, then OCR | `flow.material.read_material` |

Only **text** is sent, which is what every route above produces.

Run:

    # the document and a prompt, which is the whole interface
    python scripts/poc-flow-v2/myllmlocal.py tests/fixtures-txt/casos/<doc>.txt \\
        --prompt registry/prompts/extraction/invoice_deteccion.txt

    # another model, as the runtime names it
    python scripts/poc-flow-v2/myllmlocal.py <document> --prompt <file> \\
        --model gemma3:1b

    # a schema of the caller's own; without one the answer only has to be an
    # object, and the prompt is what asks for the shape
    python scripts/poc-flow-v2/myllmlocal.py <document> --prompt <file> \\
        --schema var/fields.json

    # read the answer with jq, since stdout is one JSON object
    python scripts/poc-flow-v2/myllmlocal.py <document> --prompt <file> | jq .answer

    # a bigger window: the flow declares 8192 and an exported value wins
    DOCFLOW_OLLAMA_NUM_CTX=16384 python scripts/poc-flow-v2/myllmlocal.py <document> \\
        --prompt <file>

    # what the sampling options would be, and which source supplied each one,
    # without reading a document or calling a model
    python scripts/poc-flow-v2/myllmlocal.py --show-env

``--model`` is the only dial. A prompt and a schema are *inputs*, and that is why
neither is derived from the other: pairing them here would make this client
decide which question the caller asked.

`--show-env` is the one mode that needs neither a document nor a prompt: it
reports the three sources of a sampling option — an exported variable, the
`.env` file, and the flow's own declaration — and the value each one settled on,
so *did my `.env` get read* is answerable without spending a call. It runs before
any document is opened.

Stdout is one JSON object — the answer with the call's own numbers beside it, so
``| jq`` works. The route and the window go to stderr: a run that reported only
the answer would leave *by which route this text was produced* and *whether the
prompt fitted the window* to be found by opening a file.

Exit codes: ``0`` a value, ``2`` a typed refusal, ``4`` a malformed invocation.
``kernel-cli.md`` §5 splits a refusal into ``2`` (the document answered) and
``3`` (no call could be made) by reason *code*, and that mapping lives in
``REASON_CODE_EXITS``, which a bench must not import — so every refusal is ``2``
and the ``refusal`` key carries the code a caller matches on.
"""

from __future__ import annotations

# `import-outside-toplevel`: `flow/__init__.py` imports `material`, so *any*
# `flow` submodule drags Docling and OpenCV in — deferring the imports keeps
# `--help` and a malformed argv from paying for an OCR engine.
# pylint: disable=import-outside-toplevel
import argparse
import dataclasses
import json
import os
import pathlib
import sys
from collections.abc import Mapping
from typing import TYPE_CHECKING, Final, NoReturn, Protocol, cast

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from docflow.kernels.types import KernelResult

__all__: list[str] = []

#: Where the document's text is substituted into the prompt. A prompt without it
#: never carries the document, and the model then answers the template's own
#: question while the report reads like a reading of the file.
TEXT_PLACEHOLDER: Final[str] = "{text}"

#: What this client reads as text directly. `flow.material.read_material` answers
#: a PDF and an image and reports anything else as `invalid` (*neither a PDF nor
#: an image*), so a text file is the one route a caller owns.
TEXT_SUFFIXES: Final[frozenset[str]] = frozenset({".txt", ".md", ".text"})

#: What the answer has to be when the caller names no schema: an object, and
#: nothing more. A default naming the registry's fields would be this client
#: deciding which question the prompt asked.
UNCONSTRAINED_SCHEMA: Final[dict[str, object]] = {"type": "object"}

#: The exit codes this client reports.
EXIT_OK: Final[int] = 0
EXIT_REFUSED: Final[int] = 2
EXIT_USAGE: Final[int] = 4


class UsageError(ValueError):
    """A malformed invocation: a file the caller named that cannot be read."""


class StructuredEngine(Protocol):
    """The one adapter method this client calls.

    Declared rather than imported from the port so the import stays lazy and so
    a test can answer without a runtime. One method, because one is what a
    single-prompt probe needs.
    """

    def structured(
        self, model: str, prompt: str, schema: Mapping[str, object]
    ) -> KernelResult[Mapping[str, object]]:
        """Ask a model for a structured answer against a schema."""


class _Parser(argparse.ArgumentParser):
    """An argument parser that reports a malformed invocation as exit 4.

    `argparse` exits `2` for its own errors, and `2` means *a typed refusal* in
    the contract above: a caller matching on the exit code would read a typo in
    its own argv as a statement about the document.
    """

    def error(self, message: str) -> NoReturn:
        """Print the usage error and stop with exit 4."""
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        raise SystemExit(EXIT_USAGE)


@dataclasses.dataclass(frozen=True, slots=True)
class Text:
    """The text a document produced, and the route that produced it.

    Attributes:
        body: The document's text, or ``None`` when nothing could be read.
        route: The operations that ran: ``direct``, ``layout_text``,
            ``render+ocr`` or ``ocr``.
        notes: Why a read produced nothing, in the reader's own words.

    """

    body: str | None
    route: str
    notes: list[str]


def _build_parser() -> _Parser:
    """Build the argument parser: the document and what to ask about it."""
    parser = _Parser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "document",
        type=pathlib.Path,
        nargs="?",
        help="a text file, a PDF, or an image (omitted with --show-env)",
    )
    parser.add_argument(
        "--prompt",
        type=pathlib.Path,
        default=None,
        metavar="FILE",
        help=f"the prompt file, with {TEXT_PLACEHOLDER!r} where the document goes",
    )
    parser.add_argument(
        "--schema",
        type=pathlib.Path,
        default=None,
        metavar="FILE",
        help="a JSON schema the answer must satisfy (default: an object, "
        "unconstrained)",
    )
    parser.add_argument(
        "--model",
        default=None,
        metavar="TAG",
        help="the model as the runtime names it (default: the flow's text lane)",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="indent the JSON",
    )
    parser.add_argument(
        "--show-env",
        action="store_true",
        help="report the sampling options this run would send, and where each "
        "one came from, without reading a document or calling a model",
    )
    return parser


def _read_text(path: pathlib.Path) -> str:
    """Read a caller's file as text, refusing rather than substituting on failure."""
    try:
        return path.read_text(encoding="utf-8")
    except OSError as problem:
        raise UsageError(f"{path}: {problem}") from problem


def _substituted(template: str, text: str) -> str:
    """The prompt with the document's text in it, or a usage error.

    A template with no placeholder cannot be answered *about* the document: the
    model is asked the template's own question, answers plausibly, and nothing in
    the result says the text was never sent.
    """
    if TEXT_PLACEHOLDER not in template:
        raise UsageError(
            f"the prompt does not contain {TEXT_PLACEHOLDER!r}: without it the "
            "document's own text never reaches the model"
        )
    return template.replace(TEXT_PLACEHOLDER, text)


def _read_schema(path: pathlib.Path) -> dict[str, object]:
    """Read a caller's schema, which must be a JSON object."""
    try:
        loaded = json.loads(_read_text(path))
    except json.JSONDecodeError as problem:
        raise UsageError(f"{path} is not valid JSON: {problem}") from problem
    if not isinstance(loaded, dict):
        raise UsageError(
            f"{path} is not a JSON object: the model is asked for an object, and "
            "a schema has to say which one"
        )
    return loaded


def _direct(path: pathlib.Path) -> Text:
    """A text file's text, read here.

    `# TODO: [MVP]` This route belongs in `flow/material.py` beside the PDF and
    image ones the day a second caller needs it; today it lives here because
    `read_material` answers a text file with `invalid`, and a text file is this
    probe's first case.
    """
    try:
        return Text(body=path.read_text(encoding="utf-8"), route="direct", notes=[])
    except (OSError, UnicodeDecodeError) as problem:
        return Text(
            body=None,
            route="",
            notes=[f"could not read the text file: {problem}"],
        )


def _document_text(document: pathlib.Path) -> Text:
    """The document's text, by the route its own kind needs."""
    if document.suffix.lower() in TEXT_SUFFIXES:
        return _direct(document)

    from flow.material import read_material

    material = read_material(document)
    return Text(body=material.text, route=material.route, notes=list(material.notes))


def _engine() -> StructuredEngine:
    """The flow's local engine, with its sampling window declared.

    `flow.extract._engine` is reused rather than rebuilt: it pairs the window
    declaration with the engine on purpose, because the adapter reads its options
    from the environment at call time and an engine built without the dial would
    get the runtime's own default window — measured, 4096 — rather than an error.
    """
    from flow.extract import _engine as flow_engine

    return cast("StructuredEngine", flow_engine())


def _default_model() -> str:
    """The flow's own text-lane model.

    Derived, never re-spelled: a second copy of the literal is how two callers
    come to disagree about which model answered while both report success.
    """
    from flow.config import DEFAULT_CONFIG

    return DEFAULT_CONFIG.text_model_a


def _sampling_variables() -> dict[str, str]:
    """The sampling variables currently in the environment, by full name."""
    from flow.sampling import SAMPLING_ENV_PREFIX

    return {
        name: value
        for name, value in os.environ.items()
        if name.startswith(SAMPLING_ENV_PREFIX)
    }


def _sampling_environment() -> dict[str, object]:
    """What the sampling options would be, and where each value came from.

    Reporting the **origin** and not only the value is the point of this function.
    A run that printed `num_ctx: 8192` says nothing about whether the caller's
    `.env` was honoured, the flow's own default applied, or an operator's export
    won — the three cases someone debugging this is trying to tell apart.
    Measured, that ambiguity is exactly what made `.env` look like it worked while
    nothing read the file.

    The three sources are consulted in the order `flow.extract._engine` uses:
    `load_env` first (an exported variable wins, then the file), then
    `apply_sampling`, which writes only what is still unset. Running them here for
    real — rather than predicting what they would do — is what makes the report
    evidence instead of a second opinion that could drift from the loader.
    """
    from flow.dotenv import DOTENV_PATH, load_env
    from flow.sampling import SAMPLING_ENV_PREFIX, apply_sampling

    exported = _sampling_variables()
    # `apply_sampling` runs after, so leaving it out of this read is what makes
    # *the file set it* distinguishable from *the flow declared it*.
    set_from_dotenv = load_env()
    after_file = _sampling_variables()
    apply_sampling()
    after_flow = _sampling_variables()

    def _origin(name: str) -> str:
        """Which of the three sources supplied a variable's value."""
        if name in exported:
            return "environment"
        if name in after_file:
            return "dotenv"
        if name in after_flow:
            return "flow default"
        return "runtime default"

    return {
        "dotenv": str(DOTENV_PATH),
        "dotenv_exists": DOTENV_PATH.is_file(),
        "variables_set_from_dotenv": set_from_dotenv,
        "sources": {name: _origin(name) for name in sorted(after_flow)},
        "effective_options": {
            name.removeprefix(SAMPLING_ENV_PREFIX).lower(): value
            for name, value in sorted(after_flow.items())
        },
    }


def _number(value: object) -> float | None:
    """A measurement as a number, or ``None`` when nothing measured it.

    ``0.0`` is a real reading and is kept; a missing key is not a zero.
    """
    return None if value is None else float(cast("float", value))


def _call(
    attempt: KernelResult[Mapping[str, object]],
) -> tuple[str | None, str | None, dict[str, object]]:
    """The refusal, its message, and the numbers that expose a prompt cut.

    The prompt's share of `num_ctx` is what a runtime silently drops past, so the
    token count is recorded wherever it lands: a value with no record of the
    window is a number nobody can check.
    """
    reason = attempt.reason
    measured = attempt.evidence.measurements
    observed = attempt.evidence.observed
    return (
        None if reason is None else reason.code,
        None if reason is None else reason.message,
        {
            "prompt_tokens": _number(measured.get("prompt_tokens")),
            "completion_tokens": _number(measured.get("completion_tokens")),
            "num_ctx": observed.get("num_ctx"),
            "done_reason": observed.get("done_reason"),
        },
    )


def _report(  # pylint: disable=too-many-arguments, too-many-positional-arguments
    document: pathlib.Path,
    text: Text,
    prompt: pathlib.Path,
    model: str,
    *,
    answer: dict[str, object] | None,
    refusal: str | None,
    message: str | None,
    call: dict[str, object] | None,
) -> dict[str, object]:
    """Assemble the one report both paths produce.

    Built in one place so a document that never reached a model and one that was
    answered cannot drift into two shapes: a consumer reads a key's absence from
    its value, never from the report's layout.
    """
    return {
        "document": str(document),
        "route": text.route,
        "characters": len(text.body or ""),
        "prompt": str(prompt),
        "model": model,
        "answer": answer,
        "refusal": refusal,
        "message": message,
        "call": call,
    }


def _without_a_call(
    document: pathlib.Path, text: Text, prompt: pathlib.Path, model: str
) -> dict[str, object]:
    """The report for a document that produced no text: no model is paid.

    Two codes, and they are different findings (B.9): `ESC_DEGRADED_MATERIAL` is
    *we could not read it* — the flow's own word for §2's degraded read — and
    `blank_page` is *we read it and there was nothing there*.
    """
    from flow.fields import ESC_DEGRADED_MATERIAL

    refused = ESC_DEGRADED_MATERIAL if text.body is None else "blank_page"
    return _report(
        document,
        text,
        prompt,
        model,
        answer=None,
        refusal=refused,
        message="; ".join(text.notes) or "the document produced no text",
        call=None,
    )


def _answer(
    document: pathlib.Path,
    text: Text,
    prompt_path: pathlib.Path,
    prompt: str,
    model: str,
    schema: dict[str, object],
) -> dict[str, object]:
    """One structured call, reported as the answer plus what the call itself said."""
    attempt = _engine().structured(model, prompt, schema)
    refusal, message, call = _call(attempt)
    return _report(
        document,
        text,
        prompt_path,
        model,
        answer=None if attempt.value is None else dict(attempt.value),
        refusal=refusal,
        message=message,
        call=call,
    )


def _announce(report: dict[str, object]) -> None:
    """Print the route and the window on stderr, keeping stdout one document."""
    print(
        f"route       {report['route']} · {report['characters']} character(s)",
        file=sys.stderr,
    )
    print(f"prompt      {report['prompt']}", file=sys.stderr)
    print(f"model       {report['model']}", file=sys.stderr)
    call = report["call"]
    if isinstance(call, dict):
        print(
            f"call        {call['prompt_tokens']} prompt token(s) of "
            f"{call['num_ctx']} · {call['completion_tokens']} completion · "
            f"done_reason {call['done_reason']!r}",
            file=sys.stderr,
        )
    else:
        print(f"refused     {report['refusal']}: {report['message']}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    """Read one document, ask the model one prompt, print the answer as JSON."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    # `--show-env` answers before any document is read or any model is called: it
    # is the question *what would this run send*, and paying for a PDF read to
    # answer it would make the flag unusable on the machine where it is needed —
    # the one with a broken setup.
    if args.show_env:
        print(
            json.dumps(
                _sampling_environment(),
                ensure_ascii=False,
                indent=2 if args.pretty else None,
            )
        )
        return EXIT_OK

    if args.document is None:
        parser.error("the following arguments are required: document")
    if args.prompt is None:
        parser.error("the following arguments are required: --prompt")

    document: pathlib.Path = args.document
    if not document.is_file():
        parser.error(f"{document} does not exist or is not a file")
    if args.model is not None and not str(args.model).strip():
        parser.error("--model requires a non-empty name")

    try:
        text = _document_text(document)
        prompt = _substituted(_read_text(args.prompt), text.body or "")
        schema = (
            UNCONSTRAINED_SCHEMA if args.schema is None else _read_schema(args.schema)
        )
    except UsageError as problem:
        print(f"error: {problem}", file=sys.stderr)
        return EXIT_USAGE

    model = _default_model() if args.model is None else str(args.model).strip()
    # `.strip()` and not the truthiness of the string: a document of whitespace
    # is not text, and asking a model about it spends a generation to be told
    # what an empty page already says.
    if text.body is None or not text.body.strip():
        report = _without_a_call(document, text, args.prompt, model)
    else:
        report = _answer(document, text, args.prompt, prompt, model, schema)

    _announce(report)
    print(json.dumps(report, ensure_ascii=False, indent=2 if args.pretty else None))
    return EXIT_OK if report["refusal"] is None else EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())
