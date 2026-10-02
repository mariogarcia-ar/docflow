"""Scratch probe: render a Markdown template and send it to Ollama as one prompt.

Reads a template from ``registry/template/`` (or any ``.md``), resolves the placeholders the
library's composition seam defines — ``<doc>``, ``<extra>``, ``<extra:key>``, ``<schema>`` — and
posts the result as the single user message of a ``POST /api/chat``. ``--schema`` does both
things the seam does with a schema: it renders ``<schema>`` and it constrains the answer, which
is sent as the request's ``format``.

Every answer is saved to ``var/tmp/`` — the raw response body, timings and token counts included
— and the answer itself still goes to stdout, so a pipe keeps working. ``--print-prompt`` renders
without sending and saves nothing.

``--name`` pins the output's name, which is how one step's answer reaches the next. The invoice
flow, one command per step, mirroring the lab bench's assets and options — and every step names
its output so the next one reads it back through ``@var/tmp/<name>.json``:

    DOC=tests/fixtures-txt/casos/66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.txt
    R=registry

    # what the flow asks, without sending anything: the rendered prompt
    python scripts/tmp/ollama_md_prompt.py --print-prompt \
        --template $R/template/extraction/invoice_deteccion.md --doc $DOC

    # 1. the detection gate: a receipt, or something else?
    python scripts/tmp/ollama_md_prompt.py --model gemma3:12b --name detection \
        --template $R/template/extraction/invoice_deteccion.md --doc $DOC \
        --schema $R/schema/extraction/invoice_detection.schema.json

    # 2. the base reading the rest of the flow refines, and the one the review judges
    python scripts/tmp/ollama_md_prompt.py --model gemma3:12b --name reading \
        --template $R/template/extraction/invoice.md --doc $DOC \
        --schema $R/schema/extraction/invoice.schema.json

    # 3. the breakdown of items and amounts
    python scripts/tmp/ollama_md_prompt.py --model gemma3:12b --name desglose \
        --template $R/template/extraction/invoice_desglose.md --doc $DOC \
        --schema $R/schema/extraction/invoice_desglose.schema.json

    # 4. the receipt class, and 5. the line of business the caller states
    python scripts/tmp/ollama_md_prompt.py --model gemma3:12b --name clasificacion \
        --template $R/template/extraction/invoice_clasificacion.md --doc $DOC \
        --schema $R/schema/extraction/invoice_clasificacion.schema.json

    python scripts/tmp/ollama_md_prompt.py --model gemma3:12b --name rubro \
        --template $R/template/extraction/invoice_rubro.md --doc $DOC \
        --schema $R/schema/extraction/invoice_rubro.schema.json --extra rubro=Restaurante

    # 6. the review reads step 2's saved answer and contradicts it field by field
    python scripts/tmp/ollama_md_prompt.py --model deepseek-r1:8b --name review \
        --template $R/template/review/invoice.md --doc $DOC \
        --schema $R/schema/review/invoice.schema.json \
        --extra proposal=@var/tmp/reading.json \
        --extra contract=@$R/schema/extraction/invoice.schema.json \
        --option temperature=0.1 --option top_p=0.95 --option repeat_penalty=1.0 \
        --option presence_penalty=0.0 --option num_ctx=16384 --timeout 600

The same review on a reasoning model: ``--option think=false`` reaches the top of the request,
the way the library sends it, and ``--timeout`` states the wait the lab tool states as an option.

    python scripts/tmp/ollama_md_prompt.py --model qwen3.5:9b --name review-qwen \
        --template $R/template/review/invoice.md --doc $DOC \
        --schema $R/schema/review/invoice.schema.json \
        --extra proposal=@var/tmp/reading.json \
        --extra contract=@$R/schema/extraction/invoice.schema.json \
        --option think=false --option temperature=0.2 --option min_p=0.05 \
        --option num_ctx=16384 --timeout 600

The transport is its sibling :mod:`_ollama`, so a probe runs from this folder.

``--model`` is required: a default model is the silent stand-in this project forbids.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

from _ollama import (
    add_connection_arguments,
    chat,
    parse_option,
    print_answer,
)

#: Where a response lands unless ``--out`` says otherwise. Ignored by git like the rest of ``var/``.
DEFAULT_OUT: Final[Path] = Path("var/tmp")

#: The placeholders a template may carry, in the same grammar the library's composition seam uses:
#: ``<extra:key>`` is matched first so a keyed placeholder never resolves as a bare ``<extra>``
#: plus leftover text.
PLACEHOLDER: Final[re.Pattern[str]] = re.compile(
    r"<extra:(?P<key>[A-Za-z_][A-Za-z0-9_]*)>|<extra>|<doc>|<schema>"
)


def render(
    template: str,
    *,
    document: str | None,
    extra_context: dict[str, Any],
    schema: dict[str, Any] | None,
) -> str:
    """Resolve every placeholder the template carries, in a single pass.

    Text that comes from the request is inserted and never scanned again, so a document that
    prints ``<extra>`` prints it instead of asking for one.

    Args:
        template: The template text, verbatim from the file.
        document: The text ``<doc>`` renders, or ``None`` when none was stated.
        extra_context: The values ``<extra>`` and ``<extra:key>`` render.
        schema: The loaded schema ``<schema>`` renders, or ``None`` when none was stated.

    Returns:
        The template with every placeholder resolved.

    Raises:
        SystemExit: When the template asks for an input the command does not carry. Substituting
            an empty string would send a model a prompt that reads as if the document were empty,
            which is a different question.
    """

    def resolve(match: re.Match[str]) -> str:
        token = match.group(0)
        if token == "<doc>":
            if document is None:
                raise SystemExit(
                    "the template asks for <doc> and --doc states no document"
                )
            return document
        if token == "<extra>":
            return json.dumps(extra_context, ensure_ascii=False)
        if token == "<schema>":
            if schema is None:
                raise SystemExit(
                    "the template asks for <schema> and --schema names no file"
                )
            return json.dumps(schema, ensure_ascii=False)
        key = match.group("key")
        if key not in extra_context:
            raise SystemExit(
                f"the template asks for <extra:{key}> and no --extra states it"
            )
        return str(extra_context[key])

    return PLACEHOLDER.sub(resolve, template)


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
        path: The JSON file that renders ``<schema>``.

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
        type=parse_option,
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
        help="the directory the raw response is saved in (default: var/tmp)",
    )
    parser.add_argument(
        "--name",
        help="the output's name, without the .json suffix (default: "
        "<schema-or-template>[.<document>]); name it to hand the file to a later step",
    )
    add_connection_arguments(parser)
    parser.add_argument(
        "--print-prompt",
        action="store_true",
        help="print the rendered prompt and send nothing",
    )
    return parser


def _default_name(asset: str, doc: str | None) -> str:
    """Return the name a response lands under when ``--name`` states none.

    The asset names the step the same way the lab bench does — the schema's name when one is
    stated, the template's otherwise — and the document's own name qualifies it, so two documents
    read through one template do not overwrite each other's answer in the shared default folder.

    Args:
        asset: The schema or template the call was made with.
        doc: The document the answer is about, or ``None`` when the call carried none.

    Returns:
        The name, without the ``.json`` suffix.
    """
    stem = Path(asset).stem.removesuffix(".schema")
    return stem if doc is None else f"{stem}.{Path(doc).stem}"


def _answer_path(out: str, name: str) -> Path:
    """Return the file a response lands in, with the directory created.

    Args:
        out: The directory the response is saved in.
        name: The name to save under, with or without its ``.json`` suffix.

    Returns:
        The absolute file the response is saved as.
    """
    directory = Path(out).expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    return directory / (name if name.endswith(".json") else f"{name}.json")


def _save(out: str, name: str, body: dict[str, Any]) -> Path:
    """Save the daemon's raw response and return where it landed.

    The body is saved verbatim, timings and token counts included: they are what a run is judged
    by, and re-encoding the answer alone would drop them.

    Args:
        out: The directory the response is saved in.
        name: The name to save under, with or without its ``.json`` suffix.
        body: The parsed response body.

    Returns:
        The file that was written.

    Raises:
        SystemExit: When the file cannot be written.
    """
    path = _answer_path(out, name)
    try:
        path.write_text(
            json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    except OSError as unwritable:
        raise SystemExit(f"--out {out}: {unwritable}") from unwritable
    return path


def main(argv: Sequence[str] | None = None) -> int:
    """Render the template, then either print it or send it.

    Args:
        argv: The command line, defaulting to ``sys.argv[1:]``.

    Returns:
        ``0`` when the prompt was rendered, and when the daemon answered.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.print_prompt and not args.model:
        parser.error("--model is required unless --print-prompt")
    if args.name is not None and not args.name.strip():
        parser.error("--name states no name")
    schema = _read_schema(args.schema) if args.schema is not None else None
    prompt = render(
        _read_text(args.template, what="--template"),
        document=None if args.doc is None else _read_text(args.doc, what="--doc"),
        extra_context=_extra_context(args.extra),
        schema=schema,
    )
    if args.print_prompt:
        print(prompt)
        return 0

    body = chat(
        str(args.base_url).rstrip("/"),
        args.model,
        prompt,
        system=args.system,
        options=dict(args.option),
        schema=schema,
        timeout=args.timeout,
    )
    print_answer(body, raw=args.raw)
    asset = args.schema if args.schema is not None else args.template
    name = args.name if args.name is not None else _default_name(asset, args.doc)
    print(f"saved {_save(args.out, name, body)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
