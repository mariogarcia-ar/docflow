"""A stub HTTP client for the provider seam (``LLM-02``, ``LLM-09``).

The seam resolves its client through :func:`importlib.import_module` at call time — that is what
keeps importing the package free of a client library — so an object installed in ``sys.modules``
*is* the client. That is how the payload shapes, the endpoint defaults and the error mapping are
proven without a socket and without a provider.

The stub models the surface the seam actually uses and nothing more: the three verbs, the
attributes it reads off a response — whole or streamed — and the two exception types its
``except`` clauses name.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any


class StubResponse:
    """What the client hands back: a status, a text, a JSON body and the streamed lines."""

    # pylint: disable=too-few-public-methods
    # Reason: the object exists to model the client's returned handle and nothing else.

    def __init__(
        self, body: Any, status: int = 200, lines: list[str] | None = None
    ) -> None:
        """Record the answer.

        Args:
            body: The parsed body, or the raw text when the body is not JSON.
            status: The HTTP status.
            lines: The lines a streaming request yields, in order.
        """
        self._body = body
        self._lines = [] if lines is None else list(lines)
        self.status_code = status
        self.text = body if isinstance(body, str) else str(body)

    def json(self) -> Any:
        """Return the parsed body, or raise the way a client raises on a non-JSON answer."""
        if isinstance(self._body, str):
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return self._body

    def read(self) -> str:
        """Return the whole answer as text, the way a client does before an error is raised."""
        return self.text

    def iter_lines(self) -> Iterator[str]:
        """Yield the answer's lines, one at a time, as the client yields them."""
        return iter(self._lines)


class StubStream:
    """The context manager a streaming request opens."""

    # pylint: disable=too-few-public-methods
    # Reason: the object exists to model the handle a client's ``stream`` call returns.

    def __init__(self, response: StubResponse) -> None:
        """Record the response the stream will hand back.

        Args:
            response: The response the ``with`` block receives.
        """
        self._response = response

    def __enter__(self) -> StubResponse:
        """Return the response."""
        return self._response

    def __exit__(self, *exc_info: object) -> bool:
        """Return whether the exception is suppressed: it never is."""
        return False


class StubClient:
    """A stand-in for the HTTP client library: records every request, answers what it was told."""

    class TimeoutException(Exception):
        """The client's own timeout type, so the seam's ``except`` clause finds it."""

    class HTTPError(Exception):
        """The client's own transport-error type."""

    def __init__(
        self,
        *,
        body: Any = None,
        status: int = 200,
        raises: Exception | None = None,
        lines: list[str] | None = None,
    ) -> None:
        """Build the stub.

        Args:
            body: The body every response carries.
            status: The status every response carries.
            raises: An exception every request raises, instead of answering.
            lines: The lines every streaming request yields.
        """
        self.body = {"message": {"content": "ok"}} if body is None else body
        self.status = status
        self.raises = raises
        self.lines = [] if lines is None else list(lines)
        self.requests: list[dict[str, Any]] = []

    def post(self, url: str, **kwargs: Any) -> StubResponse:
        """Record a POST and answer it."""
        return self._handle("POST", url, kwargs)

    def get(self, url: str, **kwargs: Any) -> StubResponse:
        """Record a GET and answer it."""
        return self._handle("GET", url, kwargs)

    def stream(self, method: str, url: str, **kwargs: Any) -> StubStream:
        """Record a streaming request and return the context manager it opens."""
        self.requests.append({"method": method, "url": url, **kwargs})
        if self.raises is not None:
            raise self.raises
        return StubStream(StubResponse(self.body, self.status, self.lines))

    def _handle(self, method: str, url: str, kwargs: dict[str, Any]) -> StubResponse:
        self.requests.append({"method": method, "url": url, **kwargs})
        if self.raises is not None:
            raise self.raises
        return StubResponse(self.body, self.status)
