"""Scratch probe: render a Markdown template and send it to a provider as one prompt.

Reads a template from ``registry/template/`` (or any ``.md``), resolves the placeholders the
library's composition seam defines — ``<doc>``, ``<extra>``, ``<extra:key>``, ``<schema>`` — and
posts the result, through :mod:`docflow.llm.primitives`, as the single user message of one
inference. ``--schema`` does both things the seam does with a schema: it renders ``<schema>`` and
it constrains the answer, which the provider's transport sends as the request's response format.

Unlike its predecessor under ``scripts/tmp``, this probe holds no transport of its own: the
rendering is :func:`docflow.llm.primitives.composition.process_template`, the call is
:func:`docflow.llm.primitives.generate_structured` (or ``generate_text``), the answer is read back
through :func:`docflow.llm.primitives.translate_provider_response`, and the two files are written
with the library's atomic publication. What is left here is the CLI's own surface — the flags, the
``@FILE`` extras and the naming of the outputs. One consequence is worth stating: the seam does
not stream, so there is no ``--stream`` here, and no ``--system`` either — the template *is* the
instruction, which is why the seam builds exactly one user message.

Every answer is saved twice in ``var/tmp/``, and the answer itself still goes to stdout, so a pipe
keeps working. ``--print-prompt`` renders without sending and saves nothing.

* ``<name>.json`` is the **answer alone** — the object a later step reads through
  ``@var/tmp/<name>.json``. The seam unwraps one fence around a JSON answer; an answer that is not
  JSON is saved as ``<name>.txt`` rather than called a ``.json`` it is not.
* ``<name>_full.json`` is the **full response**, the provider's body verbatim apart from the key
  order the library's publications fix: the answer plus the timings and token counts a run is
  judged by.

``--name`` pins the base name both files share — that is how one step's answer reaches the next.
With no ``--name`` the files are named after the schema (or the template when no schema is stated)
and the document.

``--provider`` is required and never defaulted: the seam refuses a guessed provider the same way it
refuses a guessed model. ``--timeout`` and every ``--option`` are the seam's own options, so the
wait is read out of them by :func:`docflow.llm.primitives.request_timeout`.

The invoice flow, one command per step, mirroring the lab bench's assets and options — each step
names its output, so the next one reads the answer back through ``@var/tmp/<name>.json``:

    DOC=tests/fixtures-txt/casos/66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.txt
    R=registry

    # what the flow asks, without sending anything: the rendered prompt
    python scripts/tmpref/md_prompt.py --print-prompt \
        --template $R/template/extraction/invoice_deteccion.md --doc $DOC

    # 1. the detection gate: a receipt, or something else?
    python scripts/tmpref/md_prompt.py --provider ollama --model gemma3:12b --name detection \
        --template $R/template/extraction/invoice_deteccion.md --doc $DOC \
        --schema $R/schema/extraction/invoice_detection.schema.json

    # 2. the base reading the rest of the flow refines, and the one the review judges
    python scripts/tmpref/md_prompt.py --provider ollama --model gemma3:12b --name reading \
        --template $R/template/extraction/invoice.md --doc $DOC \
        --schema $R/schema/extraction/invoice.schema.json

    # 3. the breakdown of items and amounts
    python scripts/tmpref/md_prompt.py --provider ollama --model gemma3:12b --name desglose \
        --template $R/template/extraction/invoice_desglose.md --doc $DOC \
        --schema $R/schema/extraction/invoice_desglose.schema.json

    # 4. the receipt class, and 5. the line of business the caller states
    python scripts/tmpref/md_prompt.py --provider ollama --model gemma3:12b --name clasificacion \
        --template $R/template/extraction/invoice_clasificacion.md --doc $DOC \
        --schema $R/schema/extraction/invoice_clasificacion.schema.json

    python scripts/tmpref/md_prompt.py --provider ollama --model gemma3:12b --name rubro \
        --template $R/template/extraction/invoice_rubro.md --doc $DOC \
        --schema $R/schema/extraction/invoice_rubro.schema.json --extra rubro=Restaurante

    # 6. the review reads step 2's answer — the bare object, not the daemon's envelope
    python scripts/tmpref/md_prompt.py --provider ollama --model deepseek-r1:8b --name review \
        --template $R/template/review/invoice.md --doc $DOC \
        --schema $R/schema/review/invoice.schema.json \
        --extra proposal=@var/tmp/reading.json \
        --extra contract=@$R/schema/extraction/invoice.schema.json \
        --option temperature=0.6 --option top_p=0.95 --option repeat_penalty=1.0 \
        --option num_ctx=16384 --option num_predict=4096 --timeout 300

The same review on a reasoning model: ``--option think=false`` reaches the top of the request,
the way the library sends it, and ``--timeout`` states the wait.

    python scripts/tmpref/md_prompt.py --provider ollama --model qwen3.5:9b --name review-qwen \
        --template $R/template/review/invoice.md --doc $DOC \
        --schema $R/schema/review/invoice.schema.json \
        --extra proposal=@var/tmp/reading.json \
        --extra contract=@$R/schema/extraction/invoice.schema.json \
        --option think=false --option temperature=0.2 --option min_p=0.05 \
        --option num_ctx=16384 --timeout 600

The breakdown of step 3 is reviewed the same way, against its own step schema, and both review
models run it:

    python scripts/tmpref/md_prompt.py --provider ollama --model deepseek-r1:8b \
        --name review-desglose \
        --template $R/template/review/invoice_desglose.reasoning.md --doc $DOC \
        --schema $R/schema/review/invoice_desglose.schema.json \
        --extra proposal=@var/tmp/desglose.json \
        --extra contract=@$R/schema/extraction/invoice_desglose.schema.json \
        --option temperature=0.6 --option top_p=0.95 --option repeat_penalty=1.0 \
        --option num_ctx=16384 --option num_predict=4096 --timeout 300

    python scripts/tmpref/md_prompt.py --provider ollama --model qwen3.5:9b \
        --name review-desglose-qwen \
        --template $R/template/review/invoice_desglose.md --doc $DOC \
        --schema $R/schema/review/invoice_desglose.schema.json \
        --extra proposal=@var/tmp/desglose.json \
        --extra contract=@$R/schema/extraction/invoice_desglose.schema.json \
        --option think=false --option temperature=0.2 --option min_p=0.05 \
        --option num_ctx=16384 --timeout 600

The seam is its sibling :mod:`_seam`, so a probe runs from this folder.

A typed failure the library raised — a provider that is not there, a model it does not offer, a
request it refuses — is printed as ``KIND: message`` on stderr and exits ``1``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

import _seam

from docflow.llm import primitives
from docflow.llm.primitives import ProviderResponse, composition
from docflow.llm.primitives.errors import LLMPrimitiveError

#: Where a response lands unless ``--out`` says otherwise. Ignored by git like the rest of ``var/``.
DEFAULT_OUT: Final[Path] = Path("var/tmp")


def _read_text(path: str, *, what: str) -> str:
    """Return a file's text, reported as a usage failure instead of a traceback.

    Args:
        path: The file to read.
        what: The flag the path came from, for the failure message.

    Returns:
        The file's text, as UTF-8.

    Raises:
        SystemExit: When the file cannot be read.
    """
    try:
        return Path(path).expanduser().read_text(encoding="utf-8")
    except OSError as unreadable:
        raise SystemExit(f"{what} {path}: {unreadable}") from unreadable


def _read_schema(path: str) -> dict[str, Any]:
    """Return a schema file's parsed object.

    Args:
        path: The JSON file that renders ``<schema>`` and constrains the answer.

    Returns:
        The decoded schema.

    Raises:
        SystemExit: When the file cannot be read or does not hold a JSON object.
    """
    try:
        schema = json.loads(_read_text(path, what="--schema"))
    except json.JSONDecodeError as malformed:
        raise SystemExit(f"--schema {path}: {malformed}") from malformed
    if not isinstance(schema, dict):
        raise SystemExit(f"--schema {path}: expected a JSON object")
    return schema


def _extra_context(raw: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    """Build the values ``<extra>`` and ``<extra:key>`` resolve against.

    ``--extra KEY=VALUE`` states one inline and ``--extra KEY=@FILE`` reads it from a file, which
    is how one step's answer reaches the next over the shell. A file value is inserted as the text
    it is, so a saved answer needs no re-encoding.

    Args:
        raw: The parsed ``key=value`` pairs, in the order they were written.

    Returns:
        The values, by key.
    """
    extra: dict[str, Any] = {}
    for key, value in raw:
        text = str(value)
        extra[key] = (
            _read_text(text[1:], what=f"--extra {key}=@")
            if text.startswith("@")
            else text
        )
    return extra


def build_parser() -> argparse.ArgumentParser:
    """Build the probe's argument parser.

    Returns:
        The parser, with the template and the flags it documents.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--template", required=True, help="the Markdown template to render"
    )
    parser.add_argument(
        "--model", help="the model tag to reach (required unless --print-prompt)"
    )
    parser.add_argument("--doc", help="the file whose text renders <doc>")
    parser.add_argument(
        "--extra",
        action="append",
        default=[],
        type=_seam.parse_option,
        metavar="KEY=VALUE",
        help="a value for <extra> or <extra:key>, repeatable; @FILE reads it from a file",
    )
    parser.add_argument(
        "--schema",
        help="the JSON file that constrains the answer's format and renders <schema>",
    )
    parser.add_argument(
        "--out",
        default=str(DEFAULT_OUT),
        help="the directory the response is saved in (default: var/tmp)",
    )
    parser.add_argument(
        "--name",
        help="the base name of the two output files, without a suffix (default: "
        "<schema-or-template>[.<document>]); name it to hand the file to a later step",
    )
    _seam.add_request_arguments(parser)
    parser.add_argument(
        "--print-prompt",
        action="store_true",
        help="print the rendered prompt and send nothing",
    )
    return parser


def _default_name(asset: str, doc: str | None) -> str:
    """Return the base name outputs land under when ``--name`` states none.

    The asset names the step the same way the lab bench does — the schema's name when one is
    stated, the template's otherwise — and the document's own name qualifies it, so two documents
    read through one template do not overwrite each other's answer in the shared default folder.

    Args:
        asset: The schema or template the call was made with.
        doc: The document the answer is about, or ``None`` when the call carried none.

    Returns:
        The base name, without a suffix.
    """
    stem = Path(asset).stem.removesuffix(".schema")
    return stem if doc is None else f"{stem}.{Path(doc).stem}"


def _save(out: str, name: str, response: ProviderResponse) -> list[Path]:
    """Save the answer alone and the full response, and return both paths.

    ``<name>.json`` is the answer only — the file a later step reads through
    ``@var/tmp/<name>.json`` — and an answer that is not JSON is saved as ``<name>.txt`` rather
    than called a ``.json`` it is not. ``<name>_full.json`` is the provider's whole response, with
    the timings and token counts a run is judged by; the library's publication sorts its keys, so
    the full file is the body verbatim apart from key order.

    Args:
        out: The directory the files are saved in.
        name: The base name, without a suffix.
        response: The answer, in the processor's own terms.

    Returns:
        The files that were written, the answer first.

    Raises:
        LLMPrimitiveError: With ``INTERNAL_ERROR`` when a file cannot be published.
    """
    directory = Path(out).expanduser()
    try:
        parsed = primitives.parse_json_response(response.text)
    except LLMPrimitiveError:
        answer_path = directory / f"{name}.txt"
        primitives.write_text_atomic(answer_path, response.text + "\n")
    else:
        answer_path = directory / f"{name}.json"
        if isinstance(parsed, dict):
            primitives.write_json_atomic(answer_path, parsed)
        else:
            primitives.write_text_atomic(
                answer_path, json.dumps(parsed, ensure_ascii=False, indent=2) + "\n"
            )
    full_path = directory / f"{name}_full.json"
    primitives.write_json_atomic(full_path, response.body)
    return [answer_path, full_path]


def _run(args: argparse.Namespace) -> int:
    """Render the prompt, then either print it or send it.

    Args:
        args: The parsed flags.

    Returns:
        ``0`` when the prompt was rendered, and when the provider answered.
    """
    schema = _read_schema(args.schema) if args.schema is not None else None
    prompt = composition.process_template(
        _read_text(args.template, what="--template"),
        document=None if args.doc is None else _read_text(args.doc, what="--doc"),
        extra_context=_extra_context(args.extra),
        schema=schema,
    )
    if args.print_prompt:
        print(prompt)
        return 0

    response = _seam.call(args, prompt, schema)
    _seam.print_answer(response, raw=args.raw)
    if not args.raw:
        _seam.print_stats(response)
    asset = args.schema if args.schema is not None else args.template
    name = args.name if args.name is not None else _default_name(asset, args.doc)
    name = name.removesuffix(".json")
    for path in _save(args.out, name, response):
        print(f"saved {path}", file=sys.stderr)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the probe.

    Args:
        argv: The command line, defaulting to ``sys.argv[1:]``.

    Returns:
        ``0`` when the prompt was rendered, and when the provider answered; ``1`` when the
        library returned a typed failure; ``2`` when the arguments do not state a call.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.print_prompt and not args.provider:
        parser.error("--provider is required unless --print-prompt")
    if not args.print_prompt and not args.model:
        parser.error("--model is required unless --print-prompt")
    if args.name is not None and not args.name.strip():
        parser.error("--name states no name")
    try:
        return _run(args)
    except LLMPrimitiveError as failure:
        print(f"{failure.error.type}: {failure.error.message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
