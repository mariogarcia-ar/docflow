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
with the library's atomic publication. What is left here is this probe's own surface — the flags
that state its input, and the rendering it asks for. The half it shares with its vision sibling
:mod:`image_prompt` — the rest of the flags, the ``@FILE`` extras, the naming of the outputs and
the exit codes — is :mod:`_probe`. There is no ``--system``: the template *is* the instruction,
which is why the seam builds exactly one user message.

``--stream`` is the seam's own switch rather than a second way to reach a provider: the call
carries ``stream=True`` and an observer, so a reasoning model's trace and its answer are echoed to
stderr under a ``[thinking]`` / ``[content]`` header while stdout stays the finished answer. The
body is reassembled from the deltas, so the two files below hold exactly what a waiting call would
have produced.

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

    # 6. the review reads step 2's answer — the bare object, not the daemon's envelope. T2 is a
    #    reasoning model, so it is asked the reasoning variant of the pair: same schema, criteria
    #    instead of rules (registry/README.md, "Instruct and reasoning: one schema, two prompts").
    python scripts/tmpref/md_prompt.py --provider ollama --model deepseek-r1:8b --name review \
        --template $R/template/review/invoice.reasoning.md --doc $DOC \
        --schema $R/schema/review/invoice.schema.json \
        --extra proposal=@var/tmp/reading.json \
        --extra contract=@$R/schema/extraction/invoice.schema.json \
        --option temperature=0.6 --option top_p=0.95 --option repeat_penalty=1.0 \
        --option num_ctx=16384 --option num_predict=4096 --timeout 300

Watching that same review happen, which a saved file cannot show — the deltas go to stderr while
stdout and the two files stay the finished answer:

    python scripts/tmpref/md_prompt.py --provider ollama --model deepseek-r1:8b --stream \
        --name review \
        --template $R/template/review/invoice.reasoning.md --doc $DOC \
        --schema $R/schema/review/invoice.schema.json \
        --extra proposal=@var/tmp/reading.json \
        --extra contract=@$R/schema/extraction/invoice.schema.json

Step 6's review again, on T3, with the thinking channel braked: ``--option think=false`` reaches
the top of the request, the way the library sends it, and ``--timeout`` states the wait.

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

The seam is its sibling :mod:`_seam` and the surface this probe shares with :mod:`image_prompt` is
:mod:`_probe`, so a probe runs from this folder.

A typed failure the library raised — a provider that is not there, a model it does not offer, a
request it refuses — is printed as ``KIND: message`` on stderr and exits ``1``.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

import _probe
import _seam

from docflow.llm.primitives import composition


def build_parser() -> argparse.ArgumentParser:
    """Build the probe's argument parser.

    Returns:
        The parser, with the template and the flags it documents.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    _probe.add_prompt_arguments(parser)
    parser.add_argument("--doc", help="the file whose text renders <doc>")
    _probe.add_output_arguments(parser)
    _seam.add_request_arguments(parser)
    return parser


def _run(args: argparse.Namespace) -> int:
    """Render the prompt, then either print it or send it.

    Args:
        args: The parsed flags.

    Returns:
        ``0`` when the prompt was rendered, and when the provider answered.
    """
    schema = _probe.read_schema(args.schema) if args.schema is not None else None
    prompt = composition.process_template(
        _probe.read_text(args.template, what="--template"),
        document=None if args.doc is None else _probe.read_text(args.doc, what="--doc"),
        extra_context=_probe.extra_context(args.extra),
        schema=schema,
    )
    if args.print_prompt:
        print(prompt)
        return 0

    response = _seam.call(args, prompt, schema)
    _probe.publish(
        args,
        response,
        asset=args.schema if args.schema is not None else args.template,
        inputs=() if args.doc is None else (args.doc,),
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the probe.

    Args:
        argv: The command line, defaulting to ``sys.argv[1:]``.

    Returns:
        ``0`` when the prompt was rendered, and when the provider answered; ``1`` when the
        library returned a typed failure; ``2`` when the arguments do not state a call.
    """
    return _probe.dispatch(build_parser(), argv, _run)


if __name__ == "__main__":
    raise SystemExit(main())
