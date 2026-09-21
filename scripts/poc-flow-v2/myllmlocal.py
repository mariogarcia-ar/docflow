#!/usr/bin/env python
"""One document, one prompt, one local answer: the K5 lane's console surface.

This is a thin caller of the `flow` library beside it, and it answers a question
without running the whole pipeline: *given this document and this prompt, what
does the local model say?*

The document becomes text through the flow's own routes (`my_flow.md` §1-§2) —
never through a second reader:

| the input | how it becomes text | whose route |
|---|---|---|
| a text file | read as-is | this client (see below) |
| a PDF with a text layer | `pdftotext -layout` | `flow.material.read_material` |
| a PDF page without one | rendered, then OCR | `flow.material.read_material` |
| an image | legibility gate, then OCR | `flow.material.read_material` |

Only the **text** is sent. The vision lane of §4.1 is the flow's work and
`myflow.py` runs it: all four routes above end in a transcript by requirement, so
a probe that sent pixels would be answering a different question.

Run:

    python scripts/poc-flow-v2/myllmlocal.py <document> --prompt var/prompt.txt

Stdout is one JSON object — the model's answer with the call's own numbers beside
it, so `| jq` works. The route and the provenance go to stderr, because a run
that reported only the answer would leave *which route produced this text* and
*whether the prompt fitted the window* to be found by opening a file (B.12).

`--prompt` / `--schema` default to the registry's own (`extract_texto` from
`prompts/extraction/invoice.txt`, `schemas/extraction/invoice.json`), read
through K8 — a second reader of the same asset is a second answer (B.11, B.15).

Exit codes, as far as a client can follow `kernel-cli.md` §5: `0` a value, `2` a
typed refusal, `3` a precondition this run could not meet, `4` a malformed
invocation. **§5 splits a refusal into exit 2 (the document answered) and exit 3
(no call could be made) by reason *code*, and reproducing that mapping here would
be a second copy of a table `REASON_CODE_EXITS` owns — so every refusal is 2 and
`call.refusal` carries the code a caller matches on.**
"""

# `duplicate-code`: `main` opens with the same four lines `myflow.py` does —
# build the parser, parse argv, refuse a document that is not a file. That is the
# shared *shape* of a console client in this tree, not shared logic, and the only
# way to share it would be a helper that makes one CLI import the other's parser.
# pylint: disable=duplicate-code

from __future__ import annotations

# `import-outside-toplevel`: `flow.material` and `flow.extract` import the
# `docflow` adapters, and `flow/__init__.py` imports `material` — so *any* `flow`
# submodule drags Docling and OpenCV in. Deferring the imports is what keeps
# `--help` and a malformed argv from paying for an OCR engine. The order inside
# `ask` is load-bearing: `flow._bootstrap` is what puts `src/` on `sys.path`.
# pylint: disable=import-outside-toplevel
import argparse
import dataclasses
import json
import pathlib
import sys
from collections.abc import Mapping
from typing import TYPE_CHECKING, Final, NoReturn, Protocol, cast

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from flow.artifacts import Artifacts
    from flow.material import Material

    from docflow.kernels.types import KernelResult

__all__: list[str] = []

#: Where the document's text is substituted into the prompt. A prompt without it
#: never carries the document, and the model then answers the template's own
#: question while the report reads like a reading of the file.
TEXT_PLACEHOLDER: Final[str] = "{text}"

#: What this client reads as text directly. `flow.material.read_material` answers
#: a PDF and an image and reports anything else as `invalid`, so a text file is
#: the one route a caller owns. Suffixes, not a content sniff: the extension is
#: what the operator typed.
TEXT_SUFFIXES: Final[frozenset[str]] = frozenset({".txt", ".md", ".text"})

#: The registry role whose prompt this client runs when `--prompt` is absent. The
#: role names a lane of `my_flow.md` §4.1, and the text lane is the one that reads
#: a transcript — which is what every route above produces.
TEXT_LANE: Final[str] = "extract_texto"

#: The exit codes, as this client reports them (`kernel-cli.md` §5).
EXIT_OK: Final[int] = 0
EXIT_REFUSED: Final[int] = 2
EXIT_PRECONDITION: Final[int] = 3
EXIT_USAGE: Final[int] = 4


class UsageError(ValueError):
    """A malformed invocation: argv, or a file the caller named.

    A `ValueError` deliberately, so a caller that already catches one keeps
    working — the same choice `kernel_cli.main.UsageError` makes.
    """


class PreconditionError(RuntimeError):
    """Something this run needed was not available.

    Neither the caller's fault nor the document's answer: a missing registry is
    the case this exists for, and reporting it as a refusal would tell a caller
    the model had an opinion about the document.
    """


# `too-few-public-methods`: the protocol declares the **one** method a text-lane
# probe calls. §4.1's other half is the vision lane and it belongs to `myflow.py`;
# widening this to satisfy the rule would invite a second caller shape the client
# does not have.
# pylint: disable=too-few-public-methods


class StructuredEngine(Protocol):
    """The one adapter method this client calls.

    Declared here rather than imported from the port so the import stays lazy and
    so a test can answer without a runtime. One method, because one is what a
    text-lane probe needs: §4.1's other half is the vision lane and it belongs to
    `myflow.py`.
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


# `too-few-public-methods`: `Inputs` is the resolved prompt and schema with their
# provenance; its fields are the contract and it has no behaviour to add. The same
# reasoning `flow.artifacts.Artifacts` states for its own bundle.
# pylint: disable=too-few-public-methods


@dataclasses.dataclass(frozen=True, slots=True)
class Inputs:
    """The prompt and the schema one call runs under, and where each came from.

    Attributes:
        prompt: The prompt template, with :data:`TEXT_PLACEHOLDER` still in it.
        prompt_source: Where the prompt came from, for the report.
        schema: The parsed JSON schema the answer must satisfy.
        schema_source: Where the schema came from, for the report.
        registry: The registry's own hash, or ``None`` when no registry was read
            because both inputs came from the caller.

    """

    prompt: str
    prompt_source: str
    schema: dict[str, object]
    schema_source: str
    registry: str | None


# `too-many-instance-attributes` / `too-few-public-methods`: `CallFacts` is the
# call's own report; its fields are the contract, and it has no behaviour beyond
# naming them. The same reasoning `Material` states for its record.
# pylint: disable=too-many-instance-attributes, too-few-public-methods


class CallFacts:
    """What the call itself reported, beside the answer it produced.

    A record rather than a mapping, so this field list is checked where it is
    written instead of at the moment a consumer reads a key nothing ever set. An
    absent number stays ``None``: a refusal before the request left has no prompt
    tokens, and ``0`` would be a measurement nothing took.

    Attributes:
        refusal: The refusal's reason code, or ``None`` when a value came back.
        message: The refusal's message, or ``None``.
        prompt_characters: The prompt's length, as the adapter counted it.
        prompt_tokens: What the runtime evaluated — the number that plateaus when
            the prompt did not fit the window.
        completion_tokens: How many tokens the model spent answering.
        num_ctx: The loaded window, which the adapter reads after the call.
        done_reason: The runtime's own word: ``"stop"``, or ``"length"`` when it
            cut the generation.

    """

    def __init__(  # pylint: disable=too-many-arguments, too-many-positional-arguments
        self,
        *,
        refusal: str | None,
        message: str | None,
        prompt_characters: float | None = None,
        prompt_tokens: float | None = None,
        completion_tokens: float | None = None,
        num_ctx: object = None,
        done_reason: object = None,
    ) -> None:
        self.refusal = refusal
        self.message = message
        self.prompt_characters = prompt_characters
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.num_ctx = num_ctx
        self.done_reason = done_reason

    def as_mapping(self) -> dict[str, object]:
        """The report's `call` object, in one place so both paths agree."""
        return {
            "refusal": self.refusal,
            "message": self.message,
            "prompt_characters": self.prompt_characters,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "num_ctx": self.num_ctx,
            "done_reason": self.done_reason,
        }


def _build_parser() -> _Parser:
    """Build the argument parser: the document and what to ask about it."""
    parser = _Parser(
        description=__doc__.splitlines()[0],
        epilog="exit codes: 0 a value, 2 a typed refusal, "
        "3 a precondition, 4 a malformed invocation",
    )
    parser.add_argument(
        "document",
        type=pathlib.Path,
        help="a text file, a PDF, or an image",
    )
    parser.add_argument(
        "--prompt",
        type=pathlib.Path,
        default=None,
        metavar="FILE",
        help=f"the prompt file, with {TEXT_PLACEHOLDER!r} where the document "
        "goes (default: the registry's text-lane prompt)",
    )
    parser.add_argument(
        "--schema",
        type=pathlib.Path,
        default=None,
        metavar="FILE",
        help="the JSON schema the answer must satisfy (default: the registry's "
        "extraction schema)",
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
    return parser


def _read_text(path: pathlib.Path) -> str:
    """Read a caller's text file, refusing rather than substituting on failure."""
    try:
        return path.read_text(encoding="utf-8")
    except OSError as problem:
        raise UsageError(f"{path}: {problem}") from problem


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


def _load_artifacts() -> Artifacts:
    """The flow's loaded registry artifacts, or a precondition refusal."""
    from flow.artifacts import load_artifacts

    try:
        return load_artifacts()
    except RuntimeError as problem:
        raise PreconditionError(
            "the registry could not be read, and no --prompt/--schema was given: "
            f"{problem}"
        ) from problem


def _resolve(
    prompt_path: pathlib.Path | None, schema_path: pathlib.Path | None
) -> Inputs:
    """The prompt and the schema: the caller's when given, the registry's otherwise.

    The registry is loaded **at most once, and only when something is missing**
    from the command line: two loads could see two states of the same registry,
    and the prompt and the schema would then describe two different runs.
    """
    if prompt_path is not None and schema_path is not None:
        return Inputs(
            prompt=_read_text(prompt_path),
            prompt_source=f"given ({prompt_path})",
            schema=_read_schema(schema_path),
            schema_source=f"given ({schema_path})",
            registry=None,
        )

    artifacts = _load_artifacts()
    signature = artifacts.signature
    loaded_prompt = artifacts.prompts[TEXT_LANE]
    loaded_schema = dict(artifacts.extraction_schema)
    given_prompt = _read_text(prompt_path) if prompt_path is not None else None
    given_schema = _read_schema(schema_path) if schema_path is not None else None
    return Inputs(
        prompt=loaded_prompt if given_prompt is None else given_prompt,
        prompt_source=(
            f"registry ({TEXT_LANE}, {signature[:12]})"
            if given_prompt is None
            else f"given ({prompt_path})"
        ),
        schema=loaded_schema if given_schema is None else given_schema,
        schema_source=(
            f"registry ({signature[:12]})"
            if given_schema is None
            else f"given ({schema_path})"
        ),
        registry=signature,
    )


def _text_material(path: pathlib.Path) -> Material:
    """A text file's material, read directly.

    `# TODO: [MVP]` This route belongs in `flow/material.py` beside the PDF and
    image ones the day a second caller needs it; today it lives here because
    `read_material` answers a text file with `invalid`, and this probe's first
    case is a text file.
    """
    from flow.material import TIER_DEGRADED, TIER_NATIVE, Material

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as problem:
        return Material(
            kind="text",
            tier=TIER_DEGRADED,
            text=None,
            route="",
            pages_read=0,
            pages_total=1,
            images=[],
            notes=[f"could not read the text file: {problem}"],
        )
    return Material(
        kind="text",
        tier=TIER_NATIVE,
        text=text,
        route="direct",
        pages_read=1,
        pages_total=1,
        images=[],
        notes=[],
    )


def _material(path: pathlib.Path) -> Material:
    """The document's material, by the route its own kind needs."""
    if path.suffix.lower() in TEXT_SUFFIXES:
        return _text_material(path)

    from flow.material import read_material

    return read_material(path)


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


def _engine() -> StructuredEngine:
    """The flow's local engine, with its sampling window declared.

    `flow.extract._engine` is reused rather than rebuilt: it pairs the window
    declaration with the engine on purpose, because the adapter reads its options
    from the environment at call time and a caller that built the engine without
    the dial would get the runtime's own default window rather than an error.
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


def _call(
    engine: StructuredEngine, model: str, prompt: str, schema: dict[str, object]
) -> tuple[KernelResult[Mapping[str, object]], CallFacts]:
    """One structured call, with the numbers that expose a prompt cut.

    The prompt's share of `num_ctx` is what a runtime silently drops past, so the
    two counts are recorded wherever they land: a value with no record of the
    window is a number nobody can check.
    """
    attempt = engine.structured(model, prompt, schema)
    measured = attempt.evidence.measurements
    observed = attempt.evidence.observed
    reason = attempt.reason
    return attempt, CallFacts(
        refusal=None if reason is None else reason.code,
        message=None if reason is None else reason.message,
        prompt_characters=_number(measured.get("prompt_characters")),
        prompt_tokens=_number(measured.get("prompt_tokens")),
        completion_tokens=_number(measured.get("completion_tokens")),
        num_ctx=observed.get("num_ctx"),
        done_reason=observed.get("done_reason"),
    )


def _number(value: object) -> float | None:
    """A measurement as a number, or ``None`` when nothing measured it.

    ``0.0`` is a real reading and is kept; a missing key is not a zero.
    """
    return None if value is None else float(cast("float", value))


def _material_report(material: Material) -> dict[str, object]:
    """The route the document took, and what it produced.

    The text itself is not repeated here: it rides in the prompt, and the
    call's own `prompt_characters` already measures it.
    """
    return {
        "kind": material.kind,
        "tier": material.tier,
        "route": material.route,
        "pages_read": material.pages_read,
        "pages_total": material.pages_total,
        "characters": len(material.text or ""),
        "notes": list(material.notes),
    }


def _report(  # pylint: disable=too-many-arguments, too-many-positional-arguments
    document: pathlib.Path,
    material: Material,
    inputs: Inputs,
    model: str,
    *,
    classification: dict[str, object] | None,
    facts: CallFacts,
    answer: dict[str, object] | None,
) -> dict[str, object]:
    """Assemble the one report both paths produce.

    Built in one place so a document that never reached a model and one that was
    answered cannot drift into two shapes: a consumer reads a field's absence
    from its value, never from the report's layout.
    """
    return {
        "document": str(document),
        "material": _material_report(material),
        "classified": classification,
        "prompt": {"source": inputs.prompt_source},
        "schema": {"source": inputs.schema_source},
        "registry": inputs.registry,
        "model": model,
        "call": facts.as_mapping(),
        "answer": answer,
    }


def _without_a_call(
    document: pathlib.Path,
    material: Material,
    inputs: Inputs,
    model: str,
) -> dict[str, object]:
    """The report for a document that produced no text: no model is paid.

    Two codes, and they are different findings (B.9): `ESC_DEGRADED_MATERIAL` is
    *we could not read it* — the flow's own word for §2's degraded read — and
    `blank_page` is *we read it and there was nothing there*, which is K2's word
    (`kernel-cli.md` §5) for a page holding neither text nor image.
    """
    from flow.fields import ESC_DEGRADED_MATERIAL
    from flow.material import TIER_DEGRADED

    refused = ESC_DEGRADED_MATERIAL if material.tier == TIER_DEGRADED else "blank_page"
    return _report(
        document,
        material,
        inputs,
        model,
        classification=None,
        facts=CallFacts(
            refusal=refused,
            message="; ".join(material.notes) or "the document produced no text",
        ),
        answer=None,
    )


def ask(
    document: pathlib.Path,
    inputs: Inputs,
    *,
    model: str,
    engine: StructuredEngine | None = None,
) -> dict[str, object]:
    """Read the document into text, ask the model, and report both.

    Args:
        document: The source file.
        inputs: The resolved prompt and schema, with their provenance.
        model: The model as the runtime names it.
        engine: The K5 adapter, or ``None`` to build the flow's own. Injected so a
            test can answer without a runtime and without a model.

    Returns:
        The report. A refusal is a report with ``answer = None`` and a reason code
        — an answer, never an exception.

    """
    material = _material(document)
    text = material.text or ""
    # `.strip()` and not the truthiness of the string: a document of whitespace
    # is not text, and asking a model about it spends a generation to be told
    # what an empty page already says. `flow.classify` reads the same way —
    # `text.strip()` is what decides whether there is a document at all.
    if not text.strip():
        return _without_a_call(document, material, inputs, model)

    from flow.classify import classify

    decision = classify(text)
    prompt = _substituted(inputs.prompt, text)
    attempt, facts = _call(engine or _engine(), model, prompt, inputs.schema)
    return _report(
        document,
        material,
        inputs,
        model,
        classification={
            "proceeds": decision.proceeds,
            "code": decision.code,
            "reason": decision.reason,
        },
        facts=facts,
        answer=None if attempt.value is None else dict(attempt.value),
    )


def _exit_code(report: dict[str, object]) -> int:
    """`0` when the model produced a value, `2` when it refused with a reason."""
    facts = cast("dict[str, object]", report["call"])
    return EXIT_OK if facts.get("refusal") is None else EXIT_REFUSED


def _announce(report: dict[str, object]) -> None:
    """Print the route and the provenance on stderr, keeping stdout one document.

    A run that reported only the answer would leave *by which route this text was
    produced* and *whether the prompt fitted the window* to be discovered by
    opening a JSON file (B.12).
    """
    material = cast("dict[str, object]", report["material"])
    facts = cast("dict[str, object]", report["call"])

    route = f"{material['tier']}"
    if material["route"]:
        route += f" · {material['route']}"
    pages = f"{material['pages_read']}/{material['pages_total']}"
    print(
        f"route       {route} · {pages} page(s) · "
        f"{material['characters']} character(s)",
        file=sys.stderr,
    )
    classified = report["classified"]
    if isinstance(classified, dict):
        verdict = "receipt-like" if classified["proceeds"] else "NOT A RECEIPT"
        print(f"classify    {verdict} · {classified['reason']}", file=sys.stderr)
    print(f"prompt      {report['prompt']['source']}", file=sys.stderr)
    print(f"schema      {report['schema']['source']}", file=sys.stderr)
    print(f"model       {report['model']}", file=sys.stderr)
    if facts.get("refusal") is None:
        print(
            f"call        {facts['prompt_tokens']} prompt token(s) of "
            f"{facts['num_ctx']} · {facts['completion_tokens']} completion · "
            f"done_reason {facts['done_reason']!r}",
            file=sys.stderr,
        )
    else:
        print(f"refused     {facts['refusal']}: {facts['message']}", file=sys.stderr)
    for note in cast("list[str]", material["notes"]):
        print(f"note        {note}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    """Read one document, ask the model one prompt, print the answer as JSON."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    document: pathlib.Path = args.document
    if not document.is_file():
        parser.error(f"{document} does not exist or is not a file")
    if args.model is not None and not str(args.model).strip():
        parser.error("--model requires a non-empty name")

    try:
        inputs = _resolve(args.prompt, args.schema)
        model = _default_model() if args.model is None else str(args.model).strip()
        report = ask(document, inputs, model=model)
    except UsageError as problem:
        print(f"error: {problem}", file=sys.stderr)
        return EXIT_USAGE
    except PreconditionError as problem:
        print(f"unavailable: {problem}", file=sys.stderr)
        return EXIT_PRECONDITION

    _announce(report)
    print(json.dumps(report, ensure_ascii=False, indent=2 if args.pretty else None))
    return _exit_code(report)


if __name__ == "__main__":
    sys.exit(main())
