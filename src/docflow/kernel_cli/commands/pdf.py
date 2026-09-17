"""K2's commands - `pdf` (`E07-02` / `S1-T21`).

Five `now` commands and two `MVP` ones (`kernel-cli.md` §9). Each `now` command is one
call to `PdfSource`.

`render` is the command matrix row 4 exercises, and it is worth a command of its own
because the adapter refuses to upscale: a 300 DPI request on a 150 DPI scan returns
`insufficient_effective_resolution` instead of a larger file reported as a satisfied
gate (`E04-02`).

The `min_chars` threshold is required and has no default (`ADR-009`, corpus policy).
It is read from the registry through `--root`, so a run without a usable registry
reports the precondition rather than inventing a number.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

from docflow.adapters.pdf import PdfEngine
from docflow.kernel_cli.commands.pages import parse_pages
from docflow.kernel_cli.commands.policy import DEFAULT_ROOT, policy_number
from docflow.kernel_cli.main import Call, Handler
from docflow.kernels.types import Evidence, KernelResult, Reason

__all__: list[str] = []

#: The policy key the engine's threshold comes from.
_MIN_CHARS_KEY: Final[str] = "reader.min_chars"


def _engine(root: str) -> PdfEngine | Reason:
    """Build the K2 adapter, or explain why it cannot be built.

    Args:
        root: The registry root the threshold is read from.

    Returns:
        The adapter, or the typed reason its policy is unusable.

    """
    threshold = policy_number(Path(root), _MIN_CHARS_KEY)
    if threshold.reason is not None:
        return threshold.reason
    value = threshold.value
    if value is None:  # pragma: no cover - reason and value are exclusive
        return threshold.reason  # type: ignore[return-value]
    return PdfEngine(min_chars=int(value))


def _total_pages(engine: PdfEngine, path: Path) -> int:
    """Report how many pages a document has, from the engine's own probe.

    Args:
        engine: The adapter.
        path: The PDF.

    Returns:
        The page count.

    Raises:
        ValueError: If the document cannot be probed, so a page selection cannot be
            validated against it.

    """
    probed = engine.probe(path)
    if probed.reason is not None:
        raise ValueError(probed.reason.message)
    pages = probed.evidence.measurements.get("pages")
    if pages is None:
        raise ValueError(
            "The probe reported no page count, so a page selection cannot be checked "
            "against the document. Refusing rather than assuming a range is valid."
        )
    return int(pages)


def _with_engine(root: str, path: Path, work: Any) -> KernelResult[Any]:
    """Run one operation against a built engine, or report the precondition.

    Args:
        root: The registry root.
        path: The document the operation reads.
        work: A callable taking the engine and the path.

    Returns:
        The operation's result, or the reason its policy was unusable.

    """
    engine = _engine(root)
    if isinstance(engine, Reason):
        return KernelResult(
            value=None,
            evidence=Evidence(
                terms={"registry_root": root},
                measurements={},
                observed={"blocked_by": "policy"},
            ),
            reason=engine,
        )
    return work(engine, path)


def probe(*, file: str, root: str = DEFAULT_ROOT, **_: object) -> Call:
    """Report what the file is, without rendering anything.

    Args:
        file: The PDF to probe.
        root: The registry root the policy comes from.
        **_: Accepted, so an unknown flag reaches the dispatcher.

    Returns:
        The call.

    """
    return Call(
        result=_with_engine(root, Path(file), lambda engine, path: engine.probe(path))
    )


def classify(
    *, file: str, page: object = None, root: str = DEFAULT_ROOT, **_: object
) -> Call:
    """Classify one page as text, image, mixed or blank.

    Args:
        file: The PDF to classify.
        page: The page number, defaulting to the first.
        root: The registry root the policy comes from.
        **_: Accepted, so an unknown flag reaches the dispatcher.

    Returns:
        The call.

    """
    number = 1 if page is None else int(str(page))
    return Call(
        result=_with_engine(
            root, Path(file), lambda engine, path: engine.classify(path, number)
        )
    )


def tokens(
    *,
    file: str,
    pages: object = None,
    dpi: object = None,
    root: str = DEFAULT_ROOT,
    **_: object,
) -> Call:
    """Extract the text layer's positioned tokens for a page range.

    Args:
        file: The PDF to read.
        pages: The page selection.
        dpi: The resolution the boxes are expressed in.
        root: The registry root the policy comes from.
        **_: Accepted, so an unknown flag reaches the dispatcher.

    Returns:
        The call.

    """

    def work(engine: PdfEngine, path: Path) -> KernelResult[Any]:
        """Read the selected pages.

        Args:
            engine: The adapter.
            path: The PDF.

        Returns:
            The tokens.

        """
        chosen = parse_pages(pages, _total_pages(engine, path))
        return engine.tokens(path, chosen, 72 if dpi is None else int(str(dpi)))

    return Call(result=_with_engine(root, Path(file), work))


def render(
    *,
    file: str,
    pages: object = None,
    dpi: object = None,
    root: str = DEFAULT_ROOT,
    **_: object,
) -> Call:
    """Render a page range at a requested resolution, never upscaling.

    Args:
        file: The PDF to render.
        pages: The page selection.
        dpi: The requested resolution.
        root: The registry root the policy comes from.
        **_: Accepted, so an unknown flag reaches the dispatcher.

    Returns:
        The call. A request the source pixels cannot satisfy is a typed reason and
        produces no file at all.

    """

    def work(engine: PdfEngine, path: Path) -> KernelResult[Any]:
        """Render the selected pages.

        Args:
            engine: The adapter.
            path: The PDF.

        Returns:
            The bitmap.

        """
        chosen = parse_pages(pages, _total_pages(engine, path))
        return engine.render(path, chosen, 72 if dpi is None else int(str(dpi)))

    return Call(result=_with_engine(root, Path(file), work))


def split(
    *, file: str, pages: object = None, root: str = DEFAULT_ROOT, **_: object
) -> Call:
    """Cut a page range out of a document as a new one.

    Args:
        file: The PDF to split.
        pages: The page selection.
        root: The registry root the policy comes from.
        **_: Accepted, so an unknown flag reaches the dispatcher.

    Returns:
        The call.

    """

    def work(engine: PdfEngine, path: Path) -> KernelResult[Any]:
        """Cut the selected pages.

        Args:
            engine: The adapter.
            path: The PDF.

        Returns:
            The new document's bytes.

        """
        chosen = parse_pages(pages, _total_pages(engine, path))
        return engine.split(path, chosen)

    return Call(result=_with_engine(root, Path(file), work))


#: What this module declares, as data. Each entry is
#: ``(operation, handler, positional, flags)``: ``handler=None`` is an ``MVP``
#: command, ``positional`` is the argument a bare token binds to, and ``flags`` are
#: the port parameters the command reads. The contract test compares ``flags``
#: against the signature of the port method named in `_PORT_METHOD`.
COMMANDS: Final[tuple[tuple[str, Handler | None, str | None, tuple[str, ...]], ...]] = (
    ("probe", probe, "file", ("--root",)),
    ("classify", classify, "file", ("--page", "--root")),
    ("tokens", tokens, "file", ("--pages", "--dpi", "--root")),
    ("render", render, "file", ("--pages", "--dpi", "--save", "--root")),
    ("split", split, "file", ("--pages", "--save", "--root")),
    ("facts", None, "file", ("--page",)),
    ("images", None, "file", ("--page", "--save")),
)
