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
from docflow.kernel_cli.main import Call, Handler, UsageError
from docflow.kernels import ocr as ocr_layout
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
    try:
        outcome = DoclingEngine().read(
            Path(file),
            selected,
            72 if dpi is None else int(str(dpi)),
            _DEFAULT_LANG if lang is None else str(lang),
        )
    except ValueError as exc:
        # The engine refuses a page that does not exist - correctly, because it
        # cannot read a page that is not there. The *caller* named the page, so the
        # surface answers the usage error §5 assigns to a malformed range rather
        # than exit ``1``, which would report their typo as a broken build.
        raise UsageError(str(exc)) from exc
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


def layout(  # pylint: disable=too-many-arguments
    # Six flags, and five of them are `ocr read`'s own: this command is that read
    # with an ordering applied. The sixth, `--orientation`, names the axis. A flag
    # object would hide the set from §9's table, which is what the contract test
    # compares against, so the count is stated rather than reshaped.
    *,
    file: str,
    pages: object = None,
    dpi: object = None,
    lang: object = None,
    tolerance: object = None,
    orientation: object = None,
    **_: object,
) -> Call:
    """Read a selection and return it ordered into rows.

    The OCR counterpart of `pdf layout`, with one difference that is the whole
    reason both exist. `pdf layout` delegates to `pdftotext -layout`, which returns
    the reader's own **character grid** because a text reader has the font metrics.
    A recogniser has none: it reports blocks, so the rows are rebuilt from the
    token boxes here. The result pairs a value with its label — the ticket's
    `ALICUOTA 21,00% | 10196,06` — and it does **not** reproduce column widths,
    because an engine that reports blocks does not measure them.

    `layout` is deliberately **not** on `OcrEngine`: `plans/README.md` §3 freezes
    the port's three operations, so a fourth would re-open `E04-04`'s gate. The
    adapter exposes it, which is why this command can exist without the port
    growing a method, and why :data:`COMMANDS` below declares no port method for it
    — the same arrangement `pdf layout` has with `PdfSource`.

    Args:
        file: The document to read.
        pages: The page selection; absent means the first page only.
        dpi: The resolution the boxes are expressed in.
        lang: The language hint.
        tolerance: How far apart two tokens may sit and still share a row, in the
            boxes' units at `dpi`. Absent means the legacy PoC's 25 PDF points
            converted to `dpi`, which is the reading the previous system produced.
        orientation: `horizontal` or `vertical`; absent means the dominant one the
            tokens' boxes support, which is reported in the evidence either way.
        **_: Accepted, so an unknown flag reaches the dispatcher.

    Returns:
        The call, or a typed refusal when a flag names something this command
        cannot do.

    """
    if orientation is not None and str(orientation) not in ocr_layout.ORIENTATIONS:
        # pylint: disable=duplicate-code
        # The shape is `image crop`'s refusal for an out-of-image region: a typed
        # `Reason` plus the `blocked_by` that says which parameter was missing.
        # Sharing a helper would put two commands' flag vocabularies in one place,
        # which is what makes a surface drift as a set rather than one command at a
        # time - and §9 gives each command its own flags, so the two refusals are
        # about different parameters that happen to be reported the same way.
        return Call(
            result=refusal(
                Reason(
                    code="unsupported_format",
                    message=(
                        f"--orientation must be one of "
                        f"{list(ocr_layout.ORIENTATIONS)}, got {orientation!r}. "
                        "Guessing the intended one would return a reading the "
                        "caller did not ask for."
                    ),
                ),
                blocked_by=_BLOCKED,
            )
        )

    selected = [1] if pages is None else parse_pages(pages)
    resolved_dpi = 72 if dpi is None else int(str(dpi))
    engine = DoclingEngine()

    try:
        if orientation is None:
            # The orientation is the tokens' own measurement, so it is read from
            # them rather than defaulted: a default would be this surface deciding
            # how a document is laid out.
            probe = engine.read(Path(file), selected, resolved_dpi, _lang(lang))
            if probe.reason is not None or probe.value is None:
                return Call(result=probe)
            chosen, counts = ocr_layout.dominant_orientation(probe.value.tokens)
        else:
            chosen, counts = str(orientation), {}

        outcome = engine.layout(
            Path(file),
            selected,
            resolved_dpi,
            _lang(lang),
            line_tolerance=_tolerance(tolerance, resolved_dpi),
            orientation=chosen,
        )
    except ValueError as exc:
        # The engine refuses a page that does not exist, and the kernel refuses a
        # non-positive tolerance. Both are about how the **call was written**, so
        # the surface answers the usage error §5 assigns to a malformed request
        # rather than exit 1, which would report the caller's typo as a broken
        # build. The same translation `pdf layout` makes for a reordered selection.
        raise UsageError(str(exc)) from exc

    if outcome.reason is not None or outcome.value is None:
        return Call(result=outcome)

    return Call(result=_laid_out(outcome, chosen, counts))


def _lang(lang: object) -> str:
    """Resolve the language hint.

    Args:
        lang: The flag's value, or None.

    Returns:
        The hint, defaulting to the recorded constant.

    """
    return _DEFAULT_LANG if lang is None else str(lang)


def _tolerance(tolerance: object, dpi: int) -> float:
    """Resolve the row tolerance, converting the legacy's points when absent.

    The legacy's `TOLERANCIA_LINEA = 25.0` was in PDF points at 72 DPI, and it could
    be a constant there because nothing in that system read at another resolution.
    Here `dpi` is a flag, so the same *meaning* is `25.0 * dpi / 72` — transcribed
    as a conversion rather than copied as a number, because a literal 25.0 at 300 DPI
    would be a fifth of the row height and would split every row.

    Args:
        tolerance: The flag's value, or None.
        dpi: The resolution the boxes are expressed in.

    Returns:
        The tolerance to apply, in the boxes' units.

    """
    if tolerance is None:
        return _LEGACY_LINE_TOLERANCE_POINTS * dpi / _POINTS_PER_INCH
    return float(str(tolerance))


def _laid_out(
    outcome: KernelResult[str], orientation: str, counts: dict[str, float]
) -> KernelResult[object]:
    """Attach the orientation measurement to a successful layout.

    The measurement travels even when `--orientation` was given, because a caller
    that forced `vertical` on a document whose boxes are overwhelmingly horizontal
    should be able to see that from the envelope rather than only from a reading
    that looks wrong.

    Args:
        outcome: The succeeded layout.
        orientation: The orientation that was applied.
        counts: The token counts per orientation, or empty when it was forced.

    Returns:
        The result, whose evidence carries the measurement.

    """
    observed = dict(outcome.evidence.observed)
    observed["orientation_applied"] = orientation
    if counts:
        observed["orientation_measured"] = counts

    return KernelResult(
        value=outcome.value,
        evidence=Evidence(
            terms=MappingProxyType(dict(outcome.evidence.terms)),
            measurements=MappingProxyType(dict(outcome.evidence.measurements)),
            observed=MappingProxyType(observed),
        ),
        reason=None,
    )


#: The legacy PoC's row tolerance, in PDF points at 72 DPI (`markdown_exporter.py`
#: `TOLERANCIA_LINEA`). Converted rather than copied — see :func:`_tolerance`.
_LEGACY_LINE_TOLERANCE_POINTS: Final[float] = 25.0

#: PDF user units per inch, for that conversion.
_POINTS_PER_INCH: Final[float] = 72.0


#: What this module declares, as data. Each entry is
#: ``(operation, handler, positional, flags)``: ``handler=None`` is an ``MVP``
#: command, ``positional`` is the argument a bare token binds to, and ``flags`` are
#: the port parameters the command reads. The contract test compares ``flags``
#: against the signature of the port method named in `_PORT_METHOD`.
COMMANDS: Final[tuple[tuple[str, Handler | None, str | None, tuple[str, ...]], ...]] = (
    ("capabilities", capabilities, "", ()),
    ("engine-info", engine_info, "", ()),
    ("read", read, "file", ("--pages", "--dpi", "--lang", "--correct")),
    (
        "layout",
        layout,
        "file",
        ("--pages", "--dpi", "--lang", "--tolerance", "--orientation"),
    ),
)
