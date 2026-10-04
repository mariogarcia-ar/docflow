"""The part of the probes in this folder that is not the input's shape.

A probe does one thing: render a template, hand it to a provider through
:mod:`docflow.llm.primitives`, and put the answer where the next step can read it. That is the
same job whether the request carries the text of a document (:mod:`md_prompt`) or the page image
(:mod:`image_prompt`); only the flag that names the input, and the primitive the call resolves to,
differ. Everything that does not differ lives here, so the two probes cannot drift apart in how a
file is read, a schema is parsed, the outputs are named and published, or a typed failure becomes
an exit code.

Nothing here speaks HTTP and nothing here renders a template: the rendering is the library's
:func:`docflow.llm.primitives.composition.process_template`, the call is :mod:`_seam`'s, and the
two files are written with the library's atomic publication. What this module owns is the CLI
surface the two probes share — the flags, the ``@FILE`` extras, the naming rule and the exit
codes.

This module is imported by its siblings, so a probe runs from this folder — that, and importing
:mod:`_seam` first, keeps ``scripts/tmpref`` and ``src/`` on ``sys.path``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Final

import _seam

from docflow.llm import primitives
from docflow.llm.primitives import ProviderResponse
from docflow.llm.primitives.errors import LLMPrimitiveError

#: Where a response lands unless ``--out`` says otherwise. Ignored by git like the rest of ``var/``.
DEFAULT_OUT: Final[Path] = Path("var/tmp")


def read_text(path: str, *, what: str) -> str:
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


def read_schema(path: str) -> dict[str, Any]:
    """Return a schema file's parsed object.

    Args:
        path: The JSON file that renders ``<schema>`` and constrains the answer.

    Returns:
        The decoded schema.

    Raises:
        SystemExit: When the file cannot be read or does not hold a JSON object.
    """
    try:
        schema = json.loads(read_text(path, what="--schema"))
    except json.JSONDecodeError as malformed:
        raise SystemExit(f"--schema {path}: {malformed}") from malformed
    if not isinstance(schema, dict):
        raise SystemExit(f"--schema {path}: expected a JSON object")
    return schema


def extra_context(raw: Sequence[tuple[str, Any]]) -> dict[str, Any]:
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
            read_text(text[1:], what=f"--extra {key}=@")
            if text.startswith("@")
            else text
        )
    return extra


def add_prompt_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the flags that state what is asked, and what the answer is constrained to.

    ``--model`` is stated here rather than beside ``--provider`` in :mod:`_seam` because the
    probe, not the seam, is what insists on it: ``--print-prompt`` renders without naming either,
    and naming a default model is the silent stand-in this project refuses.

    Args:
        parser: The parser to extend.
    """
    parser.add_argument(
        "--template", required=True, help="the Markdown template to render"
    )
    parser.add_argument(
        "--model", help="the model tag to reach (required unless --print-prompt)"
    )
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


def add_output_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the flags that state where the answer lands, and whether it is sent at all.

    Args:
        parser: The parser to extend.
    """
    parser.add_argument(
        "--out",
        default=str(DEFAULT_OUT),
        help="the directory the response is saved in (default: var/tmp)",
    )
    parser.add_argument(
        "--name",
        help="the base name of the two output files, without a suffix (default: "
        "<schema-or-template>[.<input>]); name it to hand the file to a later step",
    )
    parser.add_argument(
        "--print-prompt",
        action="store_true",
        help="print the rendered prompt and send nothing",
    )


def default_name(asset: str, inputs: Sequence[str] = ()) -> str:
    """Return the base name outputs land under when ``--name`` states none.

    The asset names the step the same way the lab bench does — the schema's name when one is
    stated, the template's otherwise — and each input's own name qualifies it, so two inputs read
    through one template do not overwrite each other's answer in the shared default folder.

    Args:
        asset: The schema or template the call was made with.
        inputs: The files the answer is about, in order; each contributes its stem.

    Returns:
        The base name, without a suffix.
    """
    stem = Path(asset).stem.removesuffix(".schema")
    return ".".join([stem, *(Path(path).stem for path in inputs)])


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


def publish(
    args: argparse.Namespace,
    response: ProviderResponse,
    *,
    asset: str,
    inputs: Sequence[str] = (),
) -> list[Path]:
    """Print an answer and save it twice, under ``--name`` or the default name.

    The answer goes to stdout so a pipe keeps working, and the counters a run is judged by go to
    stderr. Every answer is saved twice in ``--out``:

    * ``<name>.json`` is the **answer alone** — the object a later step reads through
      ``@var/tmp/<name>.json``. An answer that is not JSON is saved as ``<name>.txt`` rather than
      called a ``.json`` it is not.
    * ``<name>_full.json`` is the **full response**, the provider's body verbatim apart from the
      key order the library's publications fix.

    Args:
        args: The parsed flags, carrying ``--raw``, ``--out`` and ``--name``.
        response: The answer, in the processor's own terms.
        asset: The schema or template that names the step.
        inputs: The files the answer is about; they qualify the default name.

    Returns:
        The files that were written, the answer first.
    """
    _seam.print_answer(response, raw=args.raw)
    if not args.raw:
        _seam.print_stats(response)
    name = (
        args.name if args.name is not None else default_name(asset, inputs)
    ).removesuffix(".json")
    paths = _save(args.out, name, response)
    for path in paths:
        print(f"saved {path}", file=sys.stderr)
    return paths


def dispatch(
    parser: argparse.ArgumentParser,
    argv: Sequence[str] | None,
    execute: Callable[[argparse.Namespace], int],
) -> int:
    """Parse the command line, refuse a call that states none, then run it.

    ``--provider`` and ``--model`` are required together and only for a call that is sent: a
    guessed provider is the call the seam refuses, and a guessed model is the silent stand-in this
    project forbids, while ``--print-prompt`` sends nothing and names neither.

    Args:
        parser: The probe's parser.
        argv: The command line, defaulting to ``sys.argv[1:]``.
        execute: The probe's own run, which renders and then either prints or sends.

    Returns:
        ``0`` when the prompt was rendered, and when the provider answered; ``1`` when the library
        returned a typed failure; ``2`` when the arguments do not state a call.
    """
    args = parser.parse_args(argv)
    if not args.print_prompt and not args.provider:
        parser.error("--provider is required unless --print-prompt")
    if not args.print_prompt and not args.model:
        parser.error("--model is required unless --print-prompt")
    if args.name is not None and not args.name.strip():
        parser.error("--name states no name")
    try:
        return execute(args)
    except LLMPrimitiveError as failure:
        print(f"{failure.error.type}: {failure.error.message}", file=sys.stderr)
        return 1
