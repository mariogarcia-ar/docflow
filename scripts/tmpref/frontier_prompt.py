"""Frontier probe: render a template and send it to a hosted frontier model.

The sibling probes read the page itself — :mod:`md_prompt` its text, :mod:`image_prompt` its
pixels — and reach a model that runs on this machine, with no credential to state. This one
reaches a **hosted** model: the provider, the endpoint, the model and the key are stated once, at
the top of this file, and a flag overrides any of them.

The defaults are the one-call registry (``registry/llm-frontier``) and DeepSeek, so the everyday
run states only its input:

    DOC=tests/fixtures-txt/casos/66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.txt

    # what it will send, without sending anything and without naming a key
    python scripts/tmpref/frontier_prompt.py --print-prompt --doc $DOC

    # one extraction over the text — the whole analysis, one call
    python scripts/tmpref/frontier_prompt.py --name reading --doc $DOC

    # the review of that answer: the review template states the criteria, so the proposal is the
    # only extra context it needs
    python scripts/tmpref/frontier_prompt.py --name review --doc $DOC \
        --template registry/llm-frontier/template/review/invoice.md \
        --schema registry/llm-frontier/schema/review/invoice.schema.json \
        --extra proposal=@var/tmp/reading.json

``--doc`` renders ``<doc>`` from a file and ``--image`` attaches a page, repeatable and in the
order written; at least one is required, because a call over neither has nothing to read. The
registry's text templates take the page **beside** the text — the pixels decide where the OCR
garbles — while the ``_vision`` pair takes the page **alone**, which is the no-OCR path those
templates exist for:

    # no OCR: the page is the document, and the vision templates carry no <doc>
    python scripts/tmpref/frontier_prompt.py --name reading-pixels \
        --image tests/fixtures/casos/66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.jpg \
        --template registry/llm-frontier/template/extraction/invoice_vision.md \
        --schema registry/llm-frontier/schema/extraction/invoice_vision.schema.json

**Why the schema travels in the prompt.** The library's OpenAI-compatible transport sends
``response_format: {"type": "json_schema", …}`` whenever a call carries a schema. DeepSeek's
documented JSON mode is ``{"type": "json_object"}``, and ``json_schema`` is not among the response
formats its API documents, so this probe does not depend on it: the schema is rendered **into the
prompt**, the request asks for valid JSON, and the answer is checked against the schema **here** —
every violation printed, and a non-conforming answer exiting ``1``. That is also why ``--template``
and ``--schema`` are a pair: a template judged against another step's schema is answered in the
wrong shape, so both are stated, or neither is and the registry's extraction holds. A provider
whose API does accept ``json_schema`` is reached by the sibling probes, which hand the schema to
the transport instead.

**The key.** Paste it into ``API_KEY`` below to run locally, or leave that empty and export
``DEEPSEEK_API_KEY``. A key pasted into a tracked file is a plain-text secret in the working tree:
the file is committed, the key is not — so do not ``git add`` it once it holds a real one.

``<name>.json`` and ``<name>_full.json`` land under ``--out`` exactly as the siblings' do (see
:mod:`_probe`), and a typed failure is printed as ``KIND: message`` on stderr, exiting ``1``.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

import _probe
import _seam

from docflow.llm import primitives
from docflow.llm.primitives import composition
from docflow.llm.primitives.errors import LLMPrimitiveError

# ---- The connection --------------------------------------------------------------------------
#: The transport to speak: the OpenAI-compatible one, which is what a hosted frontier API offers.
PROVIDER: Final[str] = "openai_compatible"

#: The endpoint. DeepSeek's own; the transport appends ``/chat/completions`` to it.
BASE_URL: Final[str] = "https://api.deepseek.com"

#: The model tag. ``deepseek-flash`` is the current one and ``deepseek-v4-pro`` its heavier
#: sibling. Neither reads an image: for ``--image`` state a multimodal model instead.
MODEL: Final[str] = "deepseek-flash"

#: Paste the key here to run locally, or leave it empty and export :data:`API_KEY_ENV`.
API_KEY: Final[str] = ""

#: The environment variable the key is read from when :data:`API_KEY` states none.
API_KEY_ENV: Final[str] = "DEEPSEEK_API_KEY"

#: What the endpoint is asked for: a JSON object. Not a schema dialect it may not speak — the
#: schema is inlined into the prompt and enforced here instead.
RESPONSE_FORMAT: Final[dict[str, str]] = {"type": "json_object"}

# ---- The defaults ----------------------------------------------------------------------------
#: The one-call registry this probe's assets come from.
REGISTRY: Final[Path] = _seam.REPO_ROOT / "registry" / "llm-frontier"

#: The extraction the probe runs when neither ``--template`` nor ``--schema`` is stated.
DEFAULT_TEMPLATE: Final[Path] = REGISTRY / "template" / "extraction" / "invoice.md"
DEFAULT_SCHEMA: Final[Path] = REGISTRY / "schema" / "extraction" / "invoice.schema.json"

#: The instruction every template in the registry ends on; the inlined schema goes above it.
CLOSING: Final[str] = "Answer with the JSON object only."


def build_parser() -> argparse.ArgumentParser:
    """Build the probe's argument parser.

    Returns:
        The parser, with the registry's extraction and DeepSeek as the stated defaults.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--template",
        help=f"the Markdown template to render (default: {DEFAULT_TEMPLATE})",
    )
    parser.add_argument(
        "--schema",
        help=f"the JSON schema inlined into the prompt and checked afterwards "
        f"(default: {DEFAULT_SCHEMA})",
    )
    parser.add_argument(
        "--model",
        help=f"the model tag to reach (default: {MODEL})",
    )
    parser.add_argument(
        "--extra",
        action="append",
        default=[],
        type=_seam.parse_option,
        metavar="KEY=VALUE",
        help="a value for <extra> or <extra:key>, repeatable; @FILE reads it from a file",
    )
    parser.add_argument("--doc", help="the file whose text renders <doc>")
    parser.add_argument(
        "--image",
        action="append",
        default=[],
        metavar="FILE",
        help="an image to attach, repeatable and in the order written",
    )
    _probe.add_output_arguments(parser)
    _seam.add_request_arguments(parser)
    parser.set_defaults(provider=PROVIDER, model=MODEL, base_url=BASE_URL)
    return parser


def _assets(args: argparse.Namespace) -> tuple[str, str]:
    """Return the template and the schema, refusing a half-stated pair.

    Args:
        args: The parsed flags.

    Returns:
        The template path and the schema path.

    Raises:
        SystemExit: When exactly one of the two is stated.
    """
    if args.template is None and args.schema is None:
        return str(DEFAULT_TEMPLATE), str(DEFAULT_SCHEMA)
    if args.template is None or args.schema is None:
        raise SystemExit(
            "--template and --schema are a pair: state both, or neither for the registry's "
            "extraction"
        )
    return str(args.template), str(args.schema)


def _images(paths: Sequence[str]) -> list[str]:
    """Return the image paths, resolved, refusing one the run could not read.

    The library reads the bytes and raises ``DEPENDENCY_ERROR`` when it cannot, but that happens
    inside the call: checking here as well means a mistyped path is a usage failure rather than a
    traceback, and ``--print-prompt`` cannot describe a call the run could not send.

    Args:
        paths: The ``--image`` values, in the order they were written.

    Returns:
        The resolved paths, in the same order.

    Raises:
        SystemExit: When one of the paths is not a readable file.
    """
    images: list[str] = []
    for path in paths:
        candidate = Path(path).expanduser()
        if not candidate.is_file() or not os.access(candidate, os.R_OK):
            raise SystemExit(f"--image {path}: not a readable file")
        images.append(str(candidate))
    return images


def _api_key() -> str:
    """Return the credential: the one pasted above, or the environment's.

    Returns:
        The key, as text.

    Raises:
        SystemExit: When neither states one. A call with no key, or with a guessed one, is the
            silent stand-in this project refuses.
    """
    key = API_KEY.strip() or os.environ.get(API_KEY_ENV, "").strip()
    if not key:
        raise SystemExit(
            f"no key: paste it into API_KEY at the top of this file, or export {API_KEY_ENV}"
        )
    return key


def _inline_schema(prompt: str, schema: dict[str, Any]) -> str:
    """Return the prompt with the schema it must answer under, stated inside it.

    The endpoint is asked for JSON rather than for this schema, so the schema has to travel in the
    instruction itself. It goes above the template's closing line rather than after it, so the last
    thing read is still the instruction to answer with the object alone.

    Args:
        prompt: The rendered prompt.
        schema: The schema the answer must satisfy.

    Returns:
        The prompt, with the schema stated above its closing instruction.
    """
    block = (
        "THE SCHEMA YOUR ANSWER MUST SATISFY (every field, in this order)\n\n"
        f"{primitives.canonical_json(schema)}\n\n"
    )
    head, closing, tail = prompt.rpartition(CLOSING)
    return (
        f"{head}{block}{closing}{tail}"
        if closing
        else f"{prompt}\n\n{block}{CLOSING}\n"
    )


def _check_answer(text: str, schema: dict[str, Any]) -> int:
    """Check the answer against the schema, printing what it is worth.

    The endpoint was asked for valid JSON and nothing more, so this is where the answer's shape is
    decided — and a violation is reported, never smoothed over.

    Args:
        text: The answer, as the provider returned it.
        schema: The schema the answer was asked to satisfy.

    Returns:
        ``0`` when the answer satisfies the schema, ``1`` when it does not.
    """
    try:
        parsed = primitives.parse_json_response(text)
    except LLMPrimitiveError as failure:
        print(f"not JSON: {failure.error.message}", file=sys.stderr)
        return 1
    violations = primitives.validate_schema(parsed, schema)
    for violation in violations:
        print(f"schema violation: {violation}", file=sys.stderr)
    print(
        "schema: conforms"
        if not violations
        else f"schema: {len(violations)} violation(s)",
        file=sys.stderr,
    )
    return 1 if violations else 0


def _run(args: argparse.Namespace) -> int:
    """Render the prompt with its schema, then either print it or send it.

    Args:
        args: The parsed flags.

    Returns:
        ``0`` when the prompt was rendered and the answer satisfied the schema; ``1`` when the
        answer did not satisfy it.
    """
    template, schema_path = _assets(args)
    schema = _probe.read_schema(schema_path)
    images = _images(args.image)
    if args.doc is None and not images:
        raise SystemExit(
            "state --doc, --image, or both: a call over neither has nothing to read"
        )
    for image in images:
        print(f"image {image}", file=sys.stderr)

    prompt = _inline_schema(
        composition.process_template(
            _probe.read_text(template, what="--template"),
            document=None
            if args.doc is None
            else _probe.read_text(args.doc, what="--doc"),
            extra_context=_probe.extra_context(args.extra),
            schema=schema,
        ),
        schema,
    )
    if args.print_prompt:
        print(prompt)
        return 0

    # The credential and the response format join the options here, where the seam reads them:
    # the transport lifts the key out of the options rather than sending it in the body, and the
    # format is what the endpoint is asked for. The schema is deliberately *not* handed over — see
    # this module's docstring.
    args.option = [
        *args.option,
        ("api_key", _api_key()),
        ("response_format", RESPONSE_FORMAT),
    ]
    # The first image names the call — the pages of one document read as one input — and the text
    # qualifies it when the page carries one too, exactly as :mod:`image_prompt` names its output.
    inputs: tuple[str, ...] = tuple(images[:1])
    if args.doc is not None:
        inputs = (*inputs, args.doc)
    response = _seam.call(args, prompt, None, images=images)
    _probe.publish(args, response, asset=schema_path, inputs=inputs)
    return _check_answer(response.text, schema)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the probe.

    Args:
        argv: The command line, defaulting to ``sys.argv[1:]``.

    Returns:
        ``0`` when the prompt was rendered and the answer satisfied the schema; ``1`` when the
        library returned a typed failure, or the answer did not satisfy the schema; ``2`` when the
        arguments do not state a call.
    """
    return _probe.dispatch(build_parser(), argv, _run)


if __name__ == "__main__":
    raise SystemExit(main())
