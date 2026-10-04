"""Scratch probe: send a page image, with a rendered template, as one prompt.

The vision sibling of :mod:`md_prompt`. The template is rendered exactly as it is there — a
template from ``registry/template/`` (or any ``.md``), with the placeholders the library's
composition seam defines: ``<doc>``, ``<extra>``, ``<extra:key>`` and ``<schema>`` — and the answer
is printed and saved the same way. What differs is the input: instead of the document's text, the
call carries the image (or images) ``--image`` names.

The image *is* the document here. Every step of the layered extraction ships a template that reads
the page: ``registry/template/extraction/invoice_vision.md`` reads the seven fields of an Argentine
receipt straight from the pixels and its siblings — ``…_deteccion``, ``…_desglose``,
``…_clasificacion``, ``…_rubro`` — ask the other steps of that same page, while
``registry/template/review/vision.md`` and ``registry/template/review/invoice_vision_desglose.md``
judge a proposal against it. None carries a ``<doc>``, because there is no text to give.
A template that *does* carry one still resolves it: the strategy the library calls
``TEXT_PLUS_VLM`` (``docflow/workflow/llm_input.py``) sends the page text *and* the image in one
call, and ``--doc`` is how this probe states that half.

Like its sibling, this probe holds no transport of its own, which is why the images are not encoded
here: the rendering is :func:`docflow.llm.primitives.composition.process_template`, the call is
:func:`docflow.llm.primitives.generate_multimodal` — or ``generate_structured`` when ``--schema``
names one, which attaches the images all the same — the answer is read back through
:func:`docflow.llm.primitives.translate_provider_response`, and the two files are written with the
library's atomic publication. What is left here is this probe's own surface: the flags that state
its input. The rest is :mod:`_probe`.

``--image`` is repeatable and the order it is written in is the order the images are attached: a
document of several pages is one image per page, in reading order. A path that cannot be read is a
usage failure before anything is sent, so ``--print-prompt`` never describes a call the run could
not make.

``--print-prompt`` renders without sending and saves nothing. The images are part of the question,
so the paths that would be attached are echoed to stderr, where they cannot corrupt the prompt on
stdout. ``--stream``, ``--timeout`` and every ``--option`` are the seam's own switches, exactly as
in :mod:`md_prompt`.

Every answer is saved twice in ``var/tmp/``, and the answer itself still goes to stdout, so a pipe
keeps working:

* ``<name>.json`` is the **answer alone** — the object a later step reads through
  ``@var/tmp/<name>.json``. The seam unwraps one fence around a JSON answer; an answer that is not
  JSON is saved as ``<name>.txt`` rather than called a ``.json`` it is not.
* ``<name>_full.json`` is the **full response**, the provider's body verbatim apart from the key
  order the library's publications fix.

``--name`` pins the base name both files share. With no ``--name`` the files are named after the
schema (or the template when no schema is stated) and the input — the first image's name, with the
text's appended when ``--doc`` states one — so a page read with and without its text does not
overwrite itself.

The invoice flow, one command per step, mirroring the lab bench's assets and options — each step
names its output, so the next one reads the answer back through ``@var/tmp/<name>.json``. Every step
ships a template that reads the page, so the whole flow runs from the image alone, and the receipt is
the one the text flow reads as ``fixtures-txt/casos/<same id>.txt``: the two paths answer about the
same paper.

    IMG=tests/fixtures/casos/66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.jpg
    DOC=tests/fixtures-txt/casos/66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.txt
    R=registry

    # what the flow asks, without sending anything: the rendered prompt
    python scripts/tmpref/image_prompt.py --print-prompt \
        --template $R/template/extraction/invoice_vision.md --image $IMG

    # 1. the base reading, straight from the image. The image is the document, so the template
    #    carries no <doc> and none is stated. The step ships its own schema — the seven fields the
    #    template asks for — and passing it compiles that shape into the decoder's grammar.
    python scripts/tmpref/image_prompt.py --provider ollama --model qwen2.5vl:7b --name reading \
        --template $R/template/extraction/invoice_vision.md --image $IMG \
        --schema $R/schema/extraction/invoice_vision.schema.json

    # 2. the detection gate: is this a receipt at all?
    python scripts/tmpref/image_prompt.py --provider ollama --model qwen2.5vl:7b --name detection \
        --template $R/template/extraction/invoice_vision_deteccion.md --image $IMG \
        --schema $R/schema/extraction/invoice_vision_detection.schema.json

    # 3. the tax breakdown, read from the page: the IVA mechanics and the amounts
    python scripts/tmpref/image_prompt.py --provider ollama --model qwen2.5vl:7b --name desglose \
        --template $R/template/extraction/invoice_vision_desglose.md --image $IMG \
        --schema $R/schema/extraction/invoice_vision_desglose.schema.json

    # 4. the classification judgement, and 5. the line-of-business fields the caller states
    python scripts/tmpref/image_prompt.py --provider ollama --model qwen2.5vl:7b \
        --name clasificacion \
        --template $R/template/extraction/invoice_vision_clasificacion.md --image $IMG \
        --schema $R/schema/extraction/invoice_vision_clasificacion.schema.json

    python scripts/tmpref/image_prompt.py --provider ollama --model qwen2.5vl:7b --name rubro \
        --template $R/template/extraction/invoice_vision_rubro.md --image $IMG \
        --schema $R/schema/extraction/invoice_vision_rubro.schema.json --extra rubro=Restaurante

    # 6. the review of step 1's answer, judged against the same image. review/vision names the
    #    proposal alone, so the schema it is given is what says which fields are judged: the
    #    reviewed step's. A review carries the page as well as the proposal, so the window is
    #    stated — the image is context, and Ollama's default is smaller than the request.
    python scripts/tmpref/image_prompt.py --provider ollama --model qwen2.5vl:7b --name review \
        --template $R/template/review/vision.md --image $IMG \
        --schema $R/schema/review/vision.schema.json \
        --extra proposal=@var/tmp/reading.json \
        --option num_ctx=16384 --option temperature=0.2 --timeout 300

    # 7. the review of step 3's breakdown against the same image — the criteria-bearing reviewer,
    #    which names <contract> and <proposal> the way the text flow's review does
    python scripts/tmpref/image_prompt.py --provider ollama --model qwen2.5vl:7b \
        --name review-desglose \
        --template $R/template/review/invoice_vision_desglose.md --image $IMG \
        --schema $R/schema/review/invoice_vision_desglose.schema.json \
        --extra proposal=@var/tmp/desglose.json \
        --extra contract=@$R/schema/extraction/invoice_vision_desglose.schema.json \
        --option num_ctx=16384 --option temperature=0.2 --timeout 300

A step can also carry the page *beside* its text: the strategy the library calls ``TEXT_PLUS_VLM``
(``docflow/workflow/llm_input.py``) sends the document's text *and* the image in one request, and
``--doc`` is how this probe states that half. The step's template reads its own ``<doc>``, the step's
schema constrains the answer to its fields, and the image rides beside the text as the pixel half of
the evidence:

    # 8. the detection gate, with the page beside its text
    python scripts/tmpref/image_prompt.py --provider ollama --model qwen2.5vl:7b --name detection \
        --template $R/template/extraction/invoice_deteccion.md --image $IMG --doc $DOC \
        --schema $R/schema/extraction/invoice_detection.schema.json

    # 9. the base reading of the page as text, the one the review below judges
    python scripts/tmpref/image_prompt.py --provider ollama --model qwen2.5vl:7b --name reading \
        --template $R/template/extraction/invoice.md --image $IMG --doc $DOC \
        --schema $R/schema/extraction/invoice.schema.json

    # 10. the breakdown of items and amounts
    python scripts/tmpref/image_prompt.py --provider ollama --model qwen2.5vl:7b --name desglose \
        --template $R/template/extraction/invoice_desglose.md --image $IMG --doc $DOC \
        --schema $R/schema/extraction/invoice_desglose.schema.json

    # 11. the receipt class, and 12. the line of business the caller states
    python scripts/tmpref/image_prompt.py --provider ollama --model qwen2.5vl:7b \
        --name clasificacion \
        --template $R/template/extraction/invoice_clasificacion.md --image $IMG --doc $DOC \
        --schema $R/schema/extraction/invoice_clasificacion.schema.json

    python scripts/tmpref/image_prompt.py --provider ollama --model qwen2.5vl:7b --name rubro \
        --template $R/template/extraction/invoice_rubro.md --image $IMG --doc $DOC \
        --schema $R/schema/extraction/invoice_rubro.schema.json --extra rubro=Restaurante

    # 13. step 9's reading is reviewed with the page: review/invoice names <doc>, <extra:proposal>
    #    and <extra:contract>, so the review carries the same three inputs the text flow gives it
    #    and the image joins them. T2 is a reasoning model, so it is asked the reasoning variant of
    #    the pair (registry/README.md, "Instruct and reasoning: one schema, two prompts").
    python scripts/tmpref/image_prompt.py --provider ollama --model deepseek-r1:8b --name review \
        --template $R/template/review/invoice.reasoning.md --image $IMG --doc $DOC \
        --schema $R/schema/review/invoice.schema.json \
        --extra proposal=@var/tmp/reading.json \
        --extra contract=@$R/schema/extraction/invoice.schema.json \
        --option temperature=0.6 --option top_p=0.95 --option repeat_penalty=1.0 \
        --option num_ctx=16384 --option num_predict=4096 --timeout 300

Watching that review happen, which a saved file cannot show — the deltas go to stderr while stdout
and the two files stay the finished answer:

    python scripts/tmpref/image_prompt.py --provider ollama --model deepseek-r1:8b --stream \
        --name review \
        --template $R/template/review/invoice.reasoning.md --image $IMG --doc $DOC \
        --schema $R/schema/review/invoice.schema.json \
        --extra proposal=@var/tmp/reading.json \
        --extra contract=@$R/schema/extraction/invoice.schema.json

Step 13's review again, on T3, with the thinking channel braked: ``--option think=false`` reaches the
top of the request, the way the library sends it, and ``--timeout`` states the wait.

    python scripts/tmpref/image_prompt.py --provider ollama --model qwen3.5:9b --name review-qwen \
        --template $R/template/review/invoice.md --image $IMG --doc $DOC \
        --schema $R/schema/review/invoice.schema.json \
        --extra proposal=@var/tmp/reading.json \
        --extra contract=@$R/schema/extraction/invoice.schema.json \
        --option think=false --option temperature=0.2 --option min_p=0.05 \
        --option num_ctx=16384 --timeout 600

The breakdown of step 10 is reviewed the same way, against its own step schema, and both review
models run it:

    # 14. T2 reads the breakdown, with the page
    python scripts/tmpref/image_prompt.py --provider ollama --model deepseek-r1:8b \
        --name review-desglose \
        --template $R/template/review/invoice_desglose.reasoning.md --image $IMG --doc $DOC \
        --schema $R/schema/review/invoice_desglose.schema.json \
        --extra proposal=@var/tmp/desglose.json \
        --extra contract=@$R/schema/extraction/invoice_desglose.schema.json \
        --option temperature=0.6 --option top_p=0.95 --option repeat_penalty=1.0 \
        --option num_ctx=16384 --option num_predict=4096 --timeout 300

    # 15. and T3, braked, on the instruct template — the same schema, the same three inputs
    python scripts/tmpref/image_prompt.py --provider ollama --model qwen3.5:9b \
        --name review-desglose-qwen \
        --template $R/template/review/invoice_desglose.md --image $IMG --doc $DOC \
        --schema $R/schema/review/invoice_desglose.schema.json \
        --extra proposal=@var/tmp/desglose.json \
        --extra contract=@$R/schema/extraction/invoice_desglose.schema.json \
        --option think=false --option temperature=0.2 --option min_p=0.05 \
        --option num_ctx=16384 --timeout 600

The review template names no field of its own, so it judges whatever proposal it is handed — the
shape the contract declares, with no criteria of its own, which is what `review/general` does on the
text path. The breakdown is reviewed that way, from the pixels alone, by stating the step's own
schema:

    python scripts/tmpref/image_prompt.py --provider ollama --model qwen2.5vl:7b \
        --name review-desglose-pixels \
        --template $R/template/review/vision.md --image $IMG \
        --schema $R/schema/review/invoice_desglose.schema.json \
        --extra proposal=@var/tmp/desglose.json \
        --option temperature=0.2 --timeout 300

The reading's pair exists twice as well, and the two halves are asked the way the text pairs are: the
reasoning template for a model whose trace is left to itself, the instruct one for a model whose
thinking channel is braked — ``--option think=false`` reaches the top of the request, the way the
library sends it. A model that both sees and reasons (``qwen3.5:9b``) runs both:

    python scripts/tmpref/image_prompt.py --provider ollama --model qwen3.5:9b \
        --name reading-reasoning \
        --template $R/template/extraction/invoice_vision.reasoning.md --image $IMG \
        --schema $R/schema/extraction/invoice_vision.schema.json \
        --option temperature=0.6 --option num_ctx=16384 --option num_predict=4096 --timeout 600

    python scripts/tmpref/image_prompt.py --provider ollama --model qwen3.5:9b \
        --name reading-braked \
        --template $R/template/extraction/invoice_vision.md --image $IMG \
        --schema $R/schema/extraction/invoice_vision.schema.json \
        --option think=false --option temperature=0.2 --option min_p=0.05 \
        --option num_ctx=16384 --timeout 600

The seam is its sibling :mod:`_seam` and the surface this probe shares with :mod:`md_prompt` is
:mod:`_probe`, so a probe runs from this folder.

A typed failure the library raised — a provider that is not there, a model it does not offer, a
request it refuses — is printed as ``KIND: message`` on stderr and exits ``1``.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

import _probe
import _seam

from docflow.llm.primitives import composition


def build_parser() -> argparse.ArgumentParser:
    """Build the probe's argument parser.

    Returns:
        The parser, with the image and the flags it documents.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    _probe.add_prompt_arguments(parser)
    parser.add_argument(
        "--image",
        action="append",
        required=True,
        metavar="FILE",
        help="an image to attach, repeatable and in the order written",
    )
    parser.add_argument(
        "--doc",
        help="the file whose text renders <doc> beside the image, when the page also offers text",
    )
    _probe.add_output_arguments(parser)
    _seam.add_request_arguments(parser)
    return parser


def _images(paths: Sequence[str]) -> list[str]:
    """Return the image paths, resolved, refusing one the run could not read.

    The library reads the bytes and raises ``DEPENDENCY_ERROR`` when it cannot, but that happens
    inside the call: checking here as well means a mistyped path is a usage failure rather than a
    traceback, and ``--print-prompt`` cannot describe a call the run would not be able to send.

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


def _run(args: argparse.Namespace) -> int:
    """Render the prompt, then either print it or send it with the images.

    Args:
        args: The parsed flags.

    Returns:
        ``0`` when the prompt was rendered, and when the provider answered.
    """
    schema = _probe.read_schema(args.schema) if args.schema is not None else None
    images = _images(args.image)
    for image in images:
        print(f"image {image}", file=sys.stderr)
    prompt = composition.process_template(
        _probe.read_text(args.template, what="--template"),
        document=None if args.doc is None else _probe.read_text(args.doc, what="--doc"),
        extra_context=_probe.extra_context(args.extra),
        schema=schema,
    )
    if args.print_prompt:
        print(prompt)
        return 0

    # The first image names the call — the pages of one document read as one input — and the text
    # qualifies it when the page carries one too, so a page read with and without its OCR text
    # does not overwrite itself in the shared default folder.
    inputs = (images[0],) if args.doc is None else (images[0], args.doc)
    response = _seam.call(args, prompt, schema, images=images)
    _probe.publish(
        args,
        response,
        asset=args.schema if args.schema is not None else args.template,
        inputs=inputs,
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
