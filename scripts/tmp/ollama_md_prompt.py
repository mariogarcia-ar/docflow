"""Scratch probe: render a Markdown template and send it to Ollama as one prompt.

Reads a template from ``registry/template/`` (or any ``.md``), resolves the placeholders the
library's composition seam defines — ``<doc>``, ``<extra>``, ``<extra:key>``, ``<schema>`` — and
posts the result as the single user message of a ``POST /api/chat``. ``--schema`` does both
things the seam does with a schema: it renders ``<schema>`` and it constrains the answer, which
is sent as the request's ``format``.

    DOC=tests/fixtures-txt/casos/66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.txt

    python scripts/tmp/ollama_md_prompt.py --model gemma3:12b --print-prompt \
        --template registry/template/extraction/invoice_deteccion.md --doc $DOC

    python scripts/tmp/ollama_md_prompt.py --model gemma3:12b \
        --template registry/template/extraction/invoice_deteccion.md --doc $DOC \
        --schema registry/schema/extraction/invoice_detection.schema.json

    python scripts/tmp/ollama_md_prompt.py --model deepseek-r1:8b \
        --template registry/template/review/invoice.md --doc $DOC \
        --extra proposal=@var/run/reading/invoice.json \
        --extra contract=@registry/schema/extraction/invoice.schema.json

The transport is its sibling :mod:`_ollama`, so a probe runs from this folder.

``--model`` is required: a default model is the silent stand-in this project forbids.
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

from _ollama import (
    add_connection_arguments,
    chat,
    parse_option,
    print_answer,
)

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
    add_connection_arguments(parser)
    parser.add_argument(
        "--print-prompt",
        action="store_true",
        help="print the rendered prompt and send nothing",
    )
    return parser


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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
