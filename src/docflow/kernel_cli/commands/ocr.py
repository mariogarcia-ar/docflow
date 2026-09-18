"""K4's commands - `ocr` (`E07-02` / `S1-T21`).

Three `now` commands, one per `OcrEngine` method. There is **no `--engine` flag** and
there never will be: the engine is Docling and only Docling (ADR-001), and a
per-corpus choice would make the OCR path a matrix of behaviours. The absence is
asserted by the contract test rather than described here.

`read` is matrix rows 9, 10 and 11. Its value is a `ReadResult` carrying per-page
status and the page accounting, and the three rows are three different parts of it: a
blank page must report `blank` rather than `read` with invented tokens; a token whose
confidence is `null` must stay `null` rather than becoming `1.0`; and a page the
engine truncated must show `pages_requested` differing from `pages_read` rather than
reading as a page with no text.

`--correct` is lab-only and maps to `reader.correct` in the registry (`ADR-009`), so
it gates the *corrected* artifact only. Stage 1 declares it and refuses when asked
for, rather than defaulting it to `False`: a default would silently produce the
uncorrected artifact while the caller asked for the corrected one.
"""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType
from typing import Final

from docflow.adapters.docling import DoclingEngine
from docflow.kernel_cli.commands.pages import parse_pages
from docflow.kernel_cli.commands.refusals import refusal
from docflow.kernel_cli.main import Call, Handler
from docflow.kernels.types import Evidence, KernelResult, Reason, Token
from docflow.ports.ocr import ReadResult

#: What each refusal in this module was blocked by. One value for the module,
#: because every refusal here is the same kind of event: a command whose
#: parameters do not name a call this surface can make.
_BLOCKED: Final[str] = "missing_parameter"

__all__: list[str] = []

#: The default language hint. A recorded constant rather than a defaulted parameter:
#: the port requires `lang`, so the surface has to name something, and naming it in
#: one place is what makes it reviewable.
_DEFAULT_LANG: Final[str] = "en"


def capabilities(**_: object) -> Call:
    """Report what this engine can do.

    Args:
        **_: Accepted, so an unknown flag reaches the dispatcher.

    Returns:
        The call.

    """
    return Call(result=DoclingEngine().capabilities())


def engine_info(**_: object) -> Call:
    """Report the engine's identity, which feeds the cache key.

    Args:
        **_: Accepted, so an unknown flag reaches the dispatcher.

    Returns:
        The call.

    """
    return Call(result=DoclingEngine().engine_info())


def read(
    *,
    file: str,
    pages: object = None,
    dpi: object = None,
    lang: object = None,
    correct: object = False,
    **_: object,
) -> Call:
    """Read a page range and return positioned tokens with no reading order.

    Args:
        file: The document to read.
        pages: The page selection; absent means the first page only, because a
            whole-document read with no bound is not what a lab command is for.
        dpi: The resolution the boxes are expressed in.
        lang: The language hint.
        correct: Whether to ask for the corrected artifact.
        **_: Accepted, so an unknown flag reaches the dispatcher.

    Returns:
        The call, or a typed refusal when `--correct` was asked for.

    """
    if correct:
        # TODO: [MVP] `--correct` corresponds to `reader.correct` in
        # `registry/policies/thresholds.yaml` (ADR-009). Reading it needs the registry
        # on this path, and the corrected artifact is a second output the engine does
        # not yet produce. Refusing is the honest answer: defaulting the flag to False
        # would return the uncorrected tokens while the caller asked for corrected
        # ones, and the difference is invisible in the result.
        return Call(
            result=refusal(
                Reason(
                    code="engine_unavailable",
                    message=(
                        "--correct is declared but not implemented in Stage 1: it "
                        "gates the corrected artifact, which needs "
                        "`reader.correct` from the registry (ADR-009) and a second "
                        "output the engine does not produce yet. Refusing rather "
                        "than returning uncorrected tokens as if they were "
                        "corrected."
                    ),
                ),
                blocked_by=_BLOCKED,
            )
        )

    selected = [1] if pages is None else parse_pages(pages)
    outcome = DoclingEngine().read(
        Path(file),
        selected,
        72 if dpi is None else int(str(dpi)),
        _DEFAULT_LANG if lang is None else str(lang),
    )
    if outcome.reason is not None or outcome.value is None:
        return Call(result=outcome)
    return Call(result=_described(outcome))


def _described(outcome: KernelResult[ReadResult]) -> KernelResult[object]:
    """Turn a `ReadResult` into the mapping the envelope can carry.

    The result is a **description** of the read, in the same shape and for the same
    reason `store ledger-read` describes a `Ledger`: the envelope carries the seven
    boundary types, mappings and sequences, and `ReadResult` is a port-layer value
    that is not on that list. `E01-01`'s encoder refuses an unknown type rather than
    stringifying it - which is what keeps a stand-in off the wire - so returning the
    object itself made this command **crash** with exit ``1`` instead of answering.

    The three matrix rows this command answers are all here, and each is a part of
    the mapping rather than a rendering choice:

    - row 9: a blank page keeps ``"blank"`` in ``page_status`` and contributes no
      token, so it cannot read as ``read`` with invented text;
    - row 10: a token's ``confidence`` stays ``null``;
    - row 11: ``pages_requested`` and ``pages_read`` are both reported, so a
      truncated call differs from a page that held no text.

    ``pages_read`` is read from the result's own derived property rather than
    recomputed from the statuses here: a second derivation is a second answer, and
    the two would eventually disagree.

    Args:
        outcome: The succeeded read, whose value is the `ReadResult`.

    Returns:
        The result, whose value is the description.

    """
    result = outcome.value
    assert result is not None, "the caller checked; this is not a second guard"
    return KernelResult(
        value={
            "pages_requested": list(result.pages_requested),
            "pages_read": list(result.pages_read),
            # `PageStatus` is a `str` enum, so the status is the word a person reads
            # and not `PageStatus.READ`. The page numbers become strings because a
            # JSON object's keys are strings: the mapping survives the door rather
            # than being replaced by a list of records.
            "page_status": {
                str(page): status.value for page, status in result.page_status.items()
            },
            "tokens": [_token(token) for token in result.tokens],
        },
        evidence=Evidence(
            terms=MappingProxyType(dict(outcome.evidence.terms)),
            measurements=MappingProxyType(dict(outcome.evidence.measurements)),
            observed=MappingProxyType(dict(outcome.evidence.observed)),
        ),
        reason=None,
    )


def _token(token: Token) -> dict[str, object]:
    """Describe one token as the boundary's own members.

    Written out rather than `dataclasses.asdict` so that a field added to `Token`
    fails this function's next reader rather than silently widening the wire format.

    Args:
        token: The token to describe.

    Returns:
        The token, as the four members the port declares.

    """
    return {
        "text": token.text,
        "page": token.page,
        "bbox": {
            "x": token.bbox.x,
            "y": token.bbox.y,
            "width": token.bbox.width,
            "height": token.bbox.height,
        },
        "confidence": token.confidence,
        "role": token.role,
    }


#: What this module declares, as data. Each entry is
#: ``(operation, handler, positional, flags)``: ``handler=None`` is an ``MVP``
#: command, ``positional`` is the argument a bare token binds to, and ``flags`` are
#: the port parameters the command reads. The contract test compares ``flags``
#: against the signature of the port method named in `_PORT_METHOD`.
COMMANDS: Final[tuple[tuple[str, Handler | None, str | None, tuple[str, ...]], ...]] = (
    ("capabilities", capabilities, "", ()),
    ("engine-info", engine_info, "", ()),
    ("read", read, "file", ("--pages", "--dpi", "--lang", "--correct")),
)
