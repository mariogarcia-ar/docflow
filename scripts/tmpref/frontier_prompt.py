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
templates exist for.

The one-call registry has one extraction and one review rather than one prompt per step, so the
layered registry's step-and-review recipes collapse into the same four commands, each of them in
both media. ``--provider``, ``--model`` and ``--base-url`` are the defaults stated at the top of
this file, and a page needs no other model than that default one — DeepSeek's ``deepseek-flash``
reads the page as well as the text, down to naming the emitter's CUIT off it — so the four
commands below run on the defaults, and ``--model`` is stated only to reach another endpoint
(recipe 9):

    IMG=tests/fixtures/casos/66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.jpg
    DOC=tests/fixtures-txt/casos/66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.txt
    R=registry/llm-frontier

    # 0. hello world: is the key, the endpoint and the model reachable at all? The registry ships a
    #    ping pair for exactly this question — one line in, that line echoed back out, one field in
    #    the answer — so a connection failure shows up for a few hundred tokens instead of after a
    #    4 000-token prompt. The template quotes a document, so it takes text, never a page.
    printf 'hola mundo\n' > /tmp/ping.txt
    python scripts/tmpref/frontier_prompt.py --name ping --doc /tmp/ping.txt --timeout 300 \
        --template $R/template/ping.md --schema $R/schema/ping.schema.json
    #     {"echo":"hola mundo"}, schema: conforms, exit 0

    # 1. what the call asks, without sending anything and without naming a key: the rendered prompt
    #    on stdout, the schema inlined into it, and the pages that would be attached echoed to
    #    stderr, where they cannot corrupt the prompt
    python scripts/tmpref/frontier_prompt.py --print-prompt --image $IMG \
        --template $R/template/extraction/invoice_vision.md \
        --schema $R/schema/extraction/invoice_vision.schema.json

    # 2. the extraction from the page alone — the no-OCR path. The vision template carries no
    #    <doc>, so the pixels are the document, and the answer is checked against the schema here
    #    rather than by the endpoint.
    python scripts/tmpref/frontier_prompt.py --name reading-pixels --image $IMG \
        --template $R/template/extraction/invoice_vision.md \
        --schema $R/schema/extraction/invoice_vision.schema.json

    # 3. the same extraction with the page *beside* its text — the strategy the library calls
    #    TEXT_PLUS_VLM: the text template reads <doc>, the page rides beside it, and the pixels
    #    decide where the OCR garbles. Every step the layered registry asked on its own — the gate,
    #    the header, the breakdown, the line of business and its quantity — is asked in this call.
    python scripts/tmpref/frontier_prompt.py --name reading-page --image $IMG --doc $DOC

    # 4. the extraction over the text alone: the defaults are the text pair, so the document is the
    #    whole command and the model is this file's
    python scripts/tmpref/frontier_prompt.py --name reading --doc $DOC

    # 5. the review of 2's answer, judged against the same page. Only the proposal travels in: the
    #    criteria are written into the review prompt, so this review names no <contract>.
    python scripts/tmpref/frontier_prompt.py --name review-pixels --image $IMG \
        --template $R/template/review/invoice_vision.md \
        --schema $R/schema/review/invoice_vision.schema.json \
        --extra proposal=@var/tmp/reading-pixels.json

    # 6. the review of 3's answer, with the two views the reader had: the reviewer must see at
    #    least what the extractor saw, or a value read off the pixels is flagged as wrong by an
    #    auditor that never saw them
    python scripts/tmpref/frontier_prompt.py --name review-page --image $IMG --doc $DOC \
        --template $R/template/review/invoice.md \
        --schema $R/schema/review/invoice.schema.json \
        --extra proposal=@var/tmp/reading-page.json

    # 7. the same review, watched as it is written: the trace and the answer are echoed to stderr
    #    under a header per channel, while stdout and the two files stay the finished answer
    python scripts/tmpref/frontier_prompt.py --stream --name review-watched --doc $DOC \
        --template $R/template/review/invoice.md \
        --schema $R/schema/review/invoice.schema.json \
        --extra proposal=@var/tmp/reading-page.json

    # 8. the provider's body verbatim — timings, token counts and all — instead of the answer alone
    python scripts/tmpref/frontier_prompt.py --raw --name reading-raw --doc $DOC

    # 9. another endpoint and another model, stated per run: a self-hosted vLLM speaks the same
    #    OpenAI dialect, so the three flags change and nothing else does
    python scripts/tmpref/frontier_prompt.py --name reading-vllm --image $IMG \
        --provider vllm --base-url http://gpu:8000/v1 --model Qwen/Qwen3-VL-8B \
        --option temperature=0 --timeout 300 \
        --template $R/template/extraction/invoice_vision.md \
        --schema $R/schema/extraction/invoice_vision.schema.json

    # 10. an extra stated inline, where the same extra read from a file is what one step's artifact
    #     travels in as: @FILE is the form the recipes above use
    python scripts/tmpref/frontier_prompt.py --name review-inline --doc $DOC \
        --template $R/template/review/invoice.md \
        --schema $R/schema/review/invoice.schema.json \
        --extra 'proposal={"comprobante_valido": "true", "moneda": "ARS"}'

    # 11. where the artifacts land: --out and --name, and the two files a step reads back
    python scripts/tmpref/frontier_prompt.py --name reading --out var/run/frontier --doc $DOC
    #     var/run/frontier/reading.json        the answer alone — @var/run/frontier/reading.json
    #     var/run/frontier/reading_full.json   the provider's body

    # 12. a reasoning model instead of the chat one: the model tag is what selects it, and the
    #     longer wait is stated because a thinking trace spends the answer's own budget
    python scripts/tmpref/frontier_prompt.py --name reading-reasoning --doc $DOC \
        --model a-reasoning-frontier --timeout 600

The layered flow is :mod:`md_prompt`'s eleven commands, one per step. Every one of them is a
command above, one of the two below, or a command with nothing left to state — the flow is one call
here, so a step is a field of that answer rather than a call of its own:

    # 13. the gate — the flow's step 1, which refused a page by stopping the flow there. The gate is
    #     a field of this answer instead, so a page that is not a document comes back **complete**
    #     and schema-valid: `comprobante_valido` is "false", `motivo_rechazo` names why, every data
    #     field from `tipo_comprobante` on is null, and the working notes say what was seen. There is
    #     no early exit, so a refusal costs what a reading costs — the whole prompt is still sent,
    #     and what is saved is the second call the layered flow would have made.
    printf 'Hola Mario:\n\nTe paso el resumen de la reunion de ayer.\n\nSaludos,\nAna\n' > /tmp/a-message.txt
    python scripts/tmpref/frontier_prompt.py --name refused --doc /tmp/a-message.txt --timeout 300
    #     {"comprobante_valido":"false", …}, schema: conforms, exit 0

    # 14. the review run twice, on two models — how the flow used its two reviewers. A reviewer
    #     that is another model, and not the reader that wrote the proposal, audits instead of
    #     agreeing with itself. Here the second reviewer is a flag, not a second prompt: the
    #     criteria are written into the one review template, so both of them read the same one.
    python scripts/tmpref/frontier_prompt.py --name review-auditor-a --doc $DOC \
        --model reviewer-frontier-a --template $R/template/review/invoice.md \
        --schema $R/schema/review/invoice.schema.json \
        --extra proposal=@var/tmp/reading.json

    python scripts/tmpref/frontier_prompt.py --name review-auditor-b --doc $DOC \
        --model reviewer-frontier-b --template $R/template/review/invoice.md \
        --schema $R/schema/review/invoice.schema.json \
        --extra proposal=@var/tmp/reading.json

    # 15. the sampling options the flow stated, sorted by what the dialect does with them.
    #     `temperature` and `top_p` are fields of the OpenAI dialect the endpoint speaks, so they
    #     reach the body and change the answer. The local daemon's own — `num_ctx`, `num_predict`,
    #     `min_p`, `think` — are not translated by the seam: every option is spread into the body as
    #     written, and a hosted endpoint ignores a field its dialect does not define, so stating one
    #     there is silently without effect. `think=false` is lifted to the top of the body by the
    #     local transport alone, so it brakes nothing here — the reasoning is chosen by the model
    #     tag instead (recipe 12).
    python scripts/tmpref/frontier_prompt.py --name reading-sampled --doc $DOC \
        --option temperature=0 --option top_p=0.95 --timeout 300

and what each of the eleven becomes:

* **the ``--print-prompt`` over the gate template** → the ``--print-prompt`` above, over the
  one-call extraction, which asks the gate in the same prompt.
* **the gate, and the base reading it let through** → recipe 13, and the extraction above.
* **the breakdown, the class and the line of business** → the extraction above: one command, one
  answer carrying all of those steps' fields, with ``categoria_gasto`` decided in that same answer
  so it can pick which quantity is in scope. The step that stated ``--extra rubro=Restaurante`` has
  nothing left to state — the caller does not settle the line of business any more.
* **the review, the ``--stream`` twin of that same review, and the two reviews of the breakdown** →
  the review above, recipe 7, and recipe 14. The criteria are in the review template, so there is no
  ``.reasoning.md`` twin to pick between, no ``--extra contract=`` to carry, and no step schema to
  audit against; and the breakdown's own review has no counterpart at all, because there is no
  per-step answer here to audit.
* **the sampling options all four of those carried** → recipe 15.

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

**The key.** Three sources state it, in this order: ``API_KEY`` below, the process environment, and
the repository's ``.env`` — the file git ignores on purpose, and the one a credential belongs in.
The name is provider-scoped (``DEEPSEEK_API_KEY``) rather than the bench's own
``DOCFLOW_LLM_API_KEY``, so one file may hold the credential of every frontier provider this probe
is pointed at. ``API_KEY`` comes first, and is committed empty for that reason: a key pasted into a
tracked file is a plain-text secret in the working tree, so do not ``git add`` it once it holds one.

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
#: sibling; those two names are the only ones the API accepts. ``deepseek-flash`` reads an attached
#: page as well as the text, so ``--image`` needs no model other than this default one.
MODEL: Final[str] = "deepseek-flash"

#: Paste the key here to run locally, or leave it empty and state :data:`API_KEY_ENV` — in the
#: environment or in the repository's ``.env``, the file git ignores on purpose.
API_KEY: Final[str] = ""

#: The name the key is read under when :data:`API_KEY` states none: the process environment
#: first, then ``.env``.
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
    """Return the credential: the one pasted above, or the one a name states.

    The name is read through the bench's own reader, so the process environment is consulted first
    and the repository's ``.env`` second — the file that is git-ignored on purpose, and the one a
    credential belongs in. A blank value states nothing in either, and a name stated nowhere is
    refused rather than filled with a placeholder.

    Returns:
        The key, as text.

    Raises:
        SystemExit: When no source states one. A call with no key, or with a guessed one, is the
            silent stand-in this project refuses.
    """
    key = API_KEY.strip() or (_seam.env_value(API_KEY_ENV) or "")
    if not key:
        raise SystemExit(
            f"no key: paste it into API_KEY at the top of this file, or state {API_KEY_ENV} "
            f"in .env (or in the environment)"
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
