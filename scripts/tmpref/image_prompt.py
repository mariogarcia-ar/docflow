"""Scratch probe: send a page image, with a rendered template, as one prompt.

The vision sibling of :mod:`md_prompt`. The template is rendered exactly as it is there — a
template from ``registry/template/`` (or any ``.md``), with the placeholders the library's
composition seam defines: ``<doc>``, ``<extra>``, ``<extra:key>`` and ``<schema>`` — and the answer
is printed and saved the same way. What differs is the input: instead of the document's text, the
call carries the image (or images) ``--image`` names.

The image *is* the document here. ``registry/template/extraction/vision.md`` reads the seven fields
of an Argentine receipt straight from the pixels, and ``registry/template/review/vision.md`` judges
a proposal against that same image; neither carries a ``<doc>``, because there is no text to give.
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

A receipt read straight from its image, on a model that can see, and then reviewed against the same
image — the flow of the bench's examples with the text replaced by the pixels:

    IMG=tests/fixtures/expected-extraction/dbc07b17-2538-4611-9e51-7e161aaf7ba5.jpg
    R=registry

    # what the flow asks, without sending anything: the rendered prompt
    python scripts/tmpref/image_prompt.py --print-prompt \
        --template $R/template/extraction/vision.md --image $IMG

    # 1. the base reading, straight from the image
    python scripts/tmpref/image_prompt.py --provider ollama --model qwen2.5vl:7b --name reading \
        --template $R/template/extraction/vision.md --image $IMG \
        --schema $R/schema/extraction/invoice.schema.json

    # 2. the review of step 1's answer, judged against the same image
    python scripts/tmpref/image_prompt.py --provider ollama --model qwen2.5vl:7b --name review \
        --template $R/template/review/vision.md --image $IMG \
        --schema $R/schema/review/invoice.schema.json \
        --extra proposal=@var/tmp/reading.json \
        --option temperature=0.2 --timeout 300

A call that carries the page text beside the image, the way ``TEXT_PLUS_VLM`` does, states both:

    python scripts/tmpref/image_prompt.py --provider ollama --model qwen2.5vl:7b --name reading \
        --template $R/template/extraction/vision.md --image $IMG \
        --doc tests/fixtures-txt/casos/66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.txt \
        --schema $R/schema/extraction/invoice.schema.json

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
