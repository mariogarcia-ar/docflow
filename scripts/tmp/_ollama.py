"""The transport and CLI plumbing the two Ollama probes in this folder share.

Not part of the library and not part of the lab bench (:mod:`scripts.tools`): a scratch module so
``ollama_direct.py`` and ``ollama_md_prompt.py`` reach the daemon the same way instead of twice.
It is imported by its siblings, so a probe runs from this folder — that keeps ``scripts/tmp`` on
``sys.path``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any, Final

#: Where the daemon listens unless ``OLLAMA_BASE_URL`` says otherwise.
DEFAULT_BASE_URL: Final[str] = os.environ.get(
    "OLLAMA_BASE_URL", "http://localhost:11434"
)

#: How long to wait for an answer, in seconds.
DEFAULT_TIMEOUT: Final[float] = 600.0

#: The values Ollama reads at the *top* of the ``/api/chat`` body rather than as model parameters:
#: ``think`` is a reasoning model's thinking switch, ``keep_alive`` is how long the model stays
#: loaded. Everything else stated as an option is a decoding parameter and stays inside ``options``.
REQUEST_FIELDS: Final[tuple[str, ...]] = ("think", "keep_alive")


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


def _open(request: urllib.request.Request, timeout: float) -> Any:
    """Send one request and return its open response.

    Args:
        request: The request to send.
        timeout: Seconds to wait for the answer.

    Returns:
        The daemon's open response, to be read whole or line by line.

    Raises:
        SystemExit: When the daemon is unreachable or refuses the request.
    """
    try:
        return urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise SystemExit(
            f"{request.method} {request.full_url} failed: {exc.code} {detail}"
        ) from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"{request.method} {request.full_url} failed: {exc}") from exc


def _fetch(request: urllib.request.Request, timeout: float) -> dict[str, Any]:
    """Return the decoded body of one answer read whole.

    Args:
        request: The request to send.
        timeout: Seconds to wait for the answer.

    Returns:
        The decoded JSON body.

    Raises:
        SystemExit: When the daemon is unreachable, refuses, or answers with a non-JSON body.
    """
    with _open(request, timeout) as response:
        try:
            return json.loads(response.read().decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise SystemExit(
                f"{request.method} {request.full_url} failed: {exc}"
            ) from exc


def _stream(request: urllib.request.Request, timeout: float) -> dict[str, Any]:
    """Send a streaming request, echo what the model writes, and return the closing chunk.

    The deltas go to stderr as they arrive — a reasoning model's ``thinking`` under a ``[thinking]``
    header, its answer under ``[answer]`` — so the terminal shows the model working while stdout
    stays the finished answer. The closing chunk carries the counters, and its ``message`` is
    rebuilt from the deltas, so the body this returns is the one a non-streaming call would have
    returned.

    Args:
        request: The request to send.
        timeout: Seconds to wait for the answer.

    Returns:
        The closing chunk, with the accumulated answer in it.

    Raises:
        SystemExit: When the daemon is unreachable, refuses, or sends a malformed chunk.
    """
    text: list[str] = []
    thinking: list[str] = []
    closing: dict[str, Any] = {}
    announced: set[str] = set()
    with _open(request, timeout) as response:
        for line in response:
            if not line.strip():
                continue
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"streaming chunk is not JSON: {exc}") from exc
            message = chunk.get("message") or {}
            for field, sink in (("thinking", thinking), ("content", text)):
                delta = message.get(field)
                if not delta:
                    continue
                if field not in announced:
                    announced.add(field)
                    print(f"\n[{field}] ", end="", file=sys.stderr, flush=True)
                sink.append(delta)
                print(delta, end="", file=sys.stderr, flush=True)
            closing = chunk
    print(file=sys.stderr)
    answer = dict(closing.get("message") or {})
    answer["content"] = "".join(text)
    if thinking:
        answer["thinking"] = "".join(thinking)
    closing["message"] = answer
    return closing


def list_models(base_url: str, timeout: float) -> list[str]:
    """Return the model tags the daemon serves (``GET /api/tags``).

    Args:
        base_url: The daemon's root URL.
        timeout: Seconds to wait for the answer.

    Returns:
        The model names, in the order the daemon listed them.
    """
    body = _fetch(urllib.request.Request(f"{base_url}/api/tags"), timeout)
    return [str(entry["name"]) for entry in body.get("models", [])]


def chat(
    base_url: str,
    model: str,
    prompt: str,
    *,
    system: str | None = None,
    options: dict[str, Any] | None = None,
    schema: dict[str, Any] | None = None,
    stream: bool = False,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Send one turn and return the daemon's response body, streamed or read whole.

    Args:
        base_url: The daemon's root URL.
        model: The model tag to reach.
        prompt: The user message.
        system: The system message, when one is stated.
        options: Decoding parameters, passed through as the request's ``options``; the names in
            :data:`REQUEST_FIELDS` are lifted to the top of the body, where Ollama reads them.
        schema: The schema the answer must satisfy, sent as the request's ``format``.
        stream: Whether to read the answer as it is written. The deltas are echoed to stderr and
            the body returned is the one a non-streaming call would have returned.
        timeout: Seconds to wait for the answer.

    Returns:
        The parsed ``POST /api/chat`` body.
    """
    messages: list[dict[str, str]] = []
    if system is not None:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    params = dict(options or {})
    body: dict[str, Any] = {"model": model, "messages": messages, "stream": stream}
    for name in REQUEST_FIELDS:
        if name in params:
            body[name] = params.pop(name)
    body["options"] = params
    if schema is not None:
        body["format"] = dict(schema)
    request = urllib.request.Request(
        f"{base_url}/api/chat",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return _stream(request, timeout) if stream else _fetch(request, timeout)


def add_connection_arguments(
    parser: argparse.ArgumentParser, *, stream_default: bool = False
) -> None:
    """Add the flags both probes send a call with.

    Args:
        parser: The parser to extend.
        stream_default: Whether the probe reads the answer as it is written unless told otherwise.
            The flag's polarity follows the default, so there is one flag either way: ``--stream``
            when the probe waits by default, ``--no-stream`` when it streams by default.
    """
    parser.add_argument("--system", help="an optional system message")
    parser.add_argument(
        "--base-url", default=DEFAULT_BASE_URL, help="the daemon's root URL"
    )
    parser.add_argument(
        "--timeout", type=float, default=DEFAULT_TIMEOUT, help="seconds to wait"
    )
    parser.add_argument(
        "--option",
        action="append",
        default=[],
        type=parse_option,
        metavar="KEY=VALUE",
        help="a decoding parameter, repeatable (e.g. --option temperature=0.1)",
    )
    parser.add_argument(
        "--raw", action="store_true", help="print the whole response body"
    )
    if stream_default:
        parser.add_argument(
            "--no-stream",
            dest="stream",
            action="store_false",
            help="wait for the whole answer instead of echoing it as it is written",
        )
    else:
        parser.add_argument(
            "--stream",
            dest="stream",
            action="store_true",
            help="read the answer as it is written: the model's thinking and its answer are "
            "echoed to stderr, so the terminal shows what it is doing while stdout stays the "
            "answer",
        )
    parser.set_defaults(stream=stream_default)


def print_answer(body: dict[str, Any], *, raw: bool) -> None:
    """Print an answer: the whole body when asked for it, the message's text otherwise.

    Args:
        body: The parsed response body.
        raw: Whether to print the body verbatim.
    """
    if raw:
        print(json.dumps(body, ensure_ascii=False, indent=2))
        return
    print(body.get("message", {}).get("content", ""))
