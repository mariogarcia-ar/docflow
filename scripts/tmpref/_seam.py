"""The provider seam the probes in this folder reach a model through.

Not part of the library and not part of the lab bench (:mod:`scripts.tools`): a scratch module so
the probes under ``scripts/tmpref/`` describe a call once and reach a provider only through
:mod:`docflow.llm.primitives`. Nothing here speaks HTTP — a probe that did would be the thing this
folder exists to replace.

It maps the probe's flags onto the seam's own records: ``--option`` and ``--timeout`` become a
:class:`~docflow.llm.primitives.ProviderCall`'s options, the rendered prompt becomes the messages
:func:`~docflow.llm.primitives.build_messages` builds, the images a probe attaches travel in the
same record, and the provider's answer is read back through
:func:`~docflow.llm.primitives.translate_provider_response`. The wire shape, the top-level request
fields and the answer's translation are therefore the library's decisions, not this folder's —
including what an image becomes on the wire, which is why nothing here encodes one.

``--stream`` is the seam's own switch, not a second transport: the call carries
``stream=True`` and an observer, so the answer is read as it is written and the body the probe
saves is still the one a waiting call would have received.

This module is imported by its siblings, so a probe runs from this folder — that keeps
``scripts/tmpref`` on ``sys.path``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

#: Repository root, derived from this file's own location (``scripts/tmpref/_seam.py``).
REPO_ROOT = Path(__file__).resolve().parents[2]

# The library is the point of this folder, and a probe is invoked by path from a checkout that is
# not necessarily installed, so ``src/`` goes on the path the way the lab bench's bootstrap does
# it (``scripts/tools/_cli.py``). Paths only, never a second copy of the library.
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from docflow.llm import primitives  # noqa: E402  (the bootstrap above must run first)
from docflow.llm.primitives import ProviderResponse, StreamDelta  # noqa: E402


def parse_option(raw: str) -> tuple[str, Any]:
    """Split one ``key=value`` flag value, numbers and booleans included.

    Args:
        raw: The ``key=value`` text as it was written on the command line.

    Returns:
        The key and its value, with ``value`` decoded as JSON when it looks like one and kept as
        text otherwise.

    Raises:
        argparse.ArgumentTypeError: When the text carries no ``=``.
    """
    key, separator, value = raw.partition("=")
    if not separator or not key:
        raise argparse.ArgumentTypeError(f"{raw!r} is not key=value")
    try:
        return key, json.loads(value)
    except json.JSONDecodeError:
        return key, value


def add_request_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the flags a probe states a call with.

    ``--provider`` and ``--model`` are left optional here only so ``--print-prompt`` can render
    without naming them; the probe that sends insists on both. A default provider is the guessed
    call the seam refuses, and a default model is the silent stand-in this project forbids.

    Args:
        parser: The parser to extend.
    """
    parser.add_argument(
        "--provider",
        help="the provider to reach: ollama, openai_compatible, openai or vllm "
        "(required unless --print-prompt)",
    )
    parser.add_argument(
        "--base-url",
        help="the endpoint; the provider's documented default when omitted",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        help="seconds to wait for the answer; the seam's default when omitted",
    )
    parser.add_argument(
        "--option",
        action="append",
        default=[],
        type=parse_option,
        metavar="KEY=VALUE",
        help="a decoding parameter, repeatable (e.g. --option temperature=0.1); the values a "
        "provider reads at the top of the body (Ollama's think, keep_alive) are lifted there by "
        "its own transport",
    )
    parser.add_argument(
        "--raw", action="store_true", help="print the whole response body"
    )
    parser.add_argument(
        "--stream",
        dest="stream",
        action="store_true",
        help="read the answer as it is written: the model's thinking and its answer are echoed "
        "to stderr, so the terminal shows what it is doing while stdout stays the finished "
        "answer. The body is the same either way, so the two files a run writes are unchanged",
    )
    parser.set_defaults(stream=False)


class _Echo:
    """Echo a streaming answer to stderr, under a header per channel.

    A reasoning model writes on two channels — its trace and its answer — and the header is what
    tells them apart on a terminal that receives them interleaved. Nothing is written until a
    channel's first delta arrives, so a call that streams nothing echoes nothing.
    """

    def __init__(self) -> None:
        """Start an echo that has shown no channel yet."""
        self._shown: set[str] = set()

    def __call__(self, delta: StreamDelta) -> None:
        """Write one delta, opening its channel's header the first time it speaks."""
        if delta.channel not in self._shown:
            self._shown.add(delta.channel)
            print(f"\n[{delta.channel}] ", end="", file=sys.stderr, flush=True)
        print(delta.text, end="", file=sys.stderr, flush=True)

    def close(self) -> None:
        """End the line the last delta left open, when any delta was written."""
        if self._shown:
            print(file=sys.stderr)


def _options(args: argparse.Namespace) -> dict[str, Any]:
    """Return the decoding options the flags state.

    ``--timeout`` joins them rather than travelling beside them: the seam reads the wait out of
    the options through :func:`~docflow.llm.primitives.request_timeout`, so one flag and one
    ``--option timeout=…`` cannot disagree.

    Args:
        args: The parsed flags.

    Returns:
        The options, ready for the request.
    """
    options: dict[str, Any] = dict(args.option)
    if args.timeout is not None:
        options["timeout"] = args.timeout
    return options


def call(
    args: argparse.Namespace,
    prompt: str,
    schema: dict[str, Any] | None,
    images: Sequence[str] = (),
) -> ProviderResponse:
    """Send one prompt through the provider seam and return the answer in our terms.

    Args:
        args: The parsed flags, carrying the provider, the model, the endpoint and the options.
        prompt: The rendered prompt, sent with the messages the seam builds.
        schema: The schema the answer must satisfy, or ``None`` for a plain text call. It selects
            the generator and, at the same time, constrains the provider's response format.
        images: The images to attach, in order, or nothing for a call that carries none. The
            generator is resolved from the schema and the images together: a structured call that
            carries images is still the structured one, and its transport attaches them.

    Returns:
        The provider's answer, read in the processor's own terms.

    Raises:
        LLMPrimitiveError: With the kind the seam fixes for an unreachable provider, a missing
            model, a refused request or an answer that is not there.
    """
    provider = str(args.provider)
    options = _options(args)
    # The credential is lifted out of the options rather than left among them: an
    # OpenAI-compatible transport spreads the options into the body, and a key must never be part
    # of the request it authorizes.
    api_key = options.pop(primitives.API_KEY_OPTION, None)
    echo = _Echo() if args.stream else None
    request = primitives.ProviderCall(
        provider=provider,
        base_url=None if args.base_url is None else str(args.base_url),
        api_key=None if api_key is None else str(api_key),
        model=str(args.model),
        messages=primitives.build_messages(prompt),
        images=list(images),
        options=options,
        schema=schema,
        timeout=primitives.request_timeout(options),
        stream=bool(args.stream),
        observer=echo,
    )
    generator = getattr(
        primitives,
        primitives.resolve_generator(
            structured=schema is not None, multimodal=bool(images)
        ),
    )
    try:
        body = generator(request)
    finally:
        if echo is not None:
            echo.close()
    return primitives.translate_provider_response(provider, body)


def print_answer(response: ProviderResponse, *, raw: bool) -> None:
    """Print an answer: the whole body when asked for it, the answer's text otherwise.

    Args:
        response: The answer, in the processor's own terms.
        raw: Whether to print the provider's body verbatim.
    """
    if raw:
        print(json.dumps(response.body, ensure_ascii=False, indent=2))
        return
    print(response.text)


def print_stats(response: ProviderResponse) -> None:
    """Print the counters a run is judged by, to stderr.

    Args:
        response: The answer, in the processor's own terms.
    """
    print(
        json.dumps(
            {
                "model": response.model,
                "finish_reason": response.finish_reason,
                "usage": response.usage,
                "timing": response.timing,
            },
            ensure_ascii=False,
        ),
        file=sys.stderr,
    )
