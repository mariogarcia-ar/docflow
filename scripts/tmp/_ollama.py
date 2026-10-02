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
import urllib.error
import urllib.request
from typing import Any, Final

#: Where the daemon listens unless ``OLLAMA_BASE_URL`` says otherwise.
DEFAULT_BASE_URL: Final[str] = os.environ.get(
    "OLLAMA_BASE_URL", "http://localhost:11434"
)

#: How long to wait for an answer, in seconds.
DEFAULT_TIMEOUT: Final[float] = 600.0


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


def _fetch(request: urllib.request.Request, timeout: float) -> dict[str, Any]:
    """Send one request and decode its JSON body.

    Args:
        request: The request to send.
        timeout: Seconds to wait for the answer.

    Returns:
        The decoded JSON body.

    Raises:
        SystemExit: When the daemon is unreachable, refuses, or answers with a non-JSON body.
    """
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise SystemExit(
            f"{request.method} {request.full_url} failed: {exc.code} {detail}"
        ) from exc
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        raise SystemExit(f"{request.method} {request.full_url} failed: {exc}") from exc


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
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Send one non-streaming turn and return the daemon's response body.

    Args:
        base_url: The daemon's root URL.
        model: The model tag to reach.
        prompt: The user message.
        system: The system message, when one is stated.
        options: Decoding parameters, passed through as the request's ``options``.
        schema: The schema the answer must satisfy, sent as the request's ``format``.
        timeout: Seconds to wait for the answer.

    Returns:
        The parsed ``POST /api/chat`` body.
    """
    messages: list[dict[str, str]] = []
    if system is not None:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    body: dict[str, Any] = {"model": model, "messages": messages, "stream": False}
    if options:
        body["options"] = options
    if schema is not None:
        body["format"] = dict(schema)
    request = urllib.request.Request(
        f"{base_url}/api/chat",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return _fetch(request, timeout)


def add_connection_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the flags both probes send a call with.

    Args:
        parser: The parser to extend.
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
