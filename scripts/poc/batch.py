"""The batch walk: a folder in, a mirrored tree out.

`my_kernel_flow.md` §6, made runnable:

> takes a folder as input; for each file decides whether it is an image / PDF / not
> valid; a PDF gets its text extracted to `.txt` or is exported to an image; an
> image gets OCR and its text saved to `.txt`; with the result, `llm.local` extracts
> the fields; **the input folder structure is mirrored in the output**, so an
> input-vs-output and a run-vs-run comparison is direct.

The flow's §6 reads, in order: classify → validate by kind (legibility for an image,
password/decryptability for a PDF) → produce text → validate the content → extract
fields → mirror. Each of those is a step below, and the ones the flow names that are
**not** here are named as gaps rather than quietly skipped:

- **no password is ever supplied.** K2 opens what opens; a PDF that needs one is
  reported `encrypted` and skipped. That is the honest reading — the flow asks *is it
  protected*, not *decrypt it* — and supplying a password would put a secret in a
  parameter, which `NFR-05` forbids.
- **the content validation is a refusal, not a judgement.** The flow asks whether the
  text *"corresponds to the expected document type"*, and deciding that needs the
  expected type — which is a **later stage's** question, not this driver's. What runs
  here is the one check that needs no expectation: `reader.min_chars` from the
  registry, the same floor K2 uses. A longer check would be this driver inventing a
  rule it cannot ground.

This **is not K1**. K1 (`kernels/orchestrator.py`) drives a stage graph over units
with a ledger, a cache key per stage and pause/resume; this has none of that and is
not trying to. What it does is compose the adapters the way the flow describes, for
one walk of a folder - which is the piece none of the single-kernel drivers can do,
because each of them proves one adapter in isolation.

Where the pieces come from, since none of this is re-invented here:

- **classification** - `_mirror.kind_of`, whose vocabulary `batch_pdf.py` shares;
- **text** - `pdf.layout_text` on the adapter (not on the port, `plans/README.md`
  §3), or `ocr.layout_rows` after a render;
- **render** - `pdf.render_page`, the operation that feeds K4;
- **fields** - `llm_local.extract_from_text`, the same call `llm_local.py` probes.

Run it:

    python scripts/poc/batch.py <input-dir> [--out DIR]
    python scripts/poc/batch.py tests/fixtures/casos --out var/poc/batch

The mirror is the deliverable, so this driver **asserts** it rather than printing
it: every input file must have a counterpart at the same relative path, and every
input directory must exist in the output even when empty (`FR-28`).

Two things this driver does **not** do, and they are the difference between it and
its siblings rather than an omission: it writes **one** `.txt` per document, so a
multi-page PDF is read page 1 only (its `layout_text` call below says `"1"`), and it
writes `llm.local`'s answer as `<stem>.json` - the name `batch.py` has always used,
while `batch_llm_local.py` writes `<stem>.fields.json` so the two trees stay
distinguishable when both are pointed at one folder.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import shutil
import sys
import tempfile
from collections.abc import Callable, Iterator
from typing import Final

import _lib

# `docflow` is only importable once `src/` is on the path.
_lib.bootstrap()

# Importing the sibling drivers is what makes their methods reusable here. They are
# imported as **modules**, not re-implemented: a second copy of `render_page` would
# be a second answer to the same question, which is the drift this repository refuses
# everywhere else. The same rule is why the mirror, the walk and the skip records
# live in `_mirror`: `batch_pdf.py` needs those and none of this driver's OCR or
# model chain, so sharing them through a module keeps each driver's dependencies
# proportional to what it actually does.
import _mirror  # noqa: E402 - see the note above
import decide  # noqa: E402 - see the note above
import image as image_driver  # noqa: E402 - see the note above
import llm_local  # noqa: E402 - see the note above
import ocr as ocr_driver  # noqa: E402 - see the note above
import pdf as pdf_driver  # noqa: E402 - see the note above

from docflow.adapters.docling import DoclingEngine  # noqa: E402 - see above
from docflow.adapters.image import RasterEngine  # noqa: E402 - see above
from docflow.adapters.ollama import OllamaEngine  # noqa: E402 - see above
from docflow.adapters.pdf import PdfEngine  # noqa: E402 - see above
from docflow.kernel_cli.commands.pages import parse_pages  # noqa: E402

__all__: list[str] = []

#: Suffixes K3 accepts. Anything outside this set and K2's is *not valid* for this
#: pipeline, and §6 names that as a third outcome rather than an error. The sets are
#: `_mirror`'s now, because `batch_pdf.py` must agree with this driver about what a
#: PDF is - two definitions would be two answers to *is this file in scope*.
IMAGE_SUFFIXES: Final[frozenset[str]] = _mirror.IMAGE_SUFFIXES

#: Suffixes K2 accepts.
PDF_SUFFIXES: Final[frozenset[str]] = _mirror.PDF_SUFFIXES

#: The resolution a page is rendered at before OCR. **A target, capped by what the
#: page actually holds.** The adapter refuses to upscale (`kernel-cli.md` §11 row 4),
#: and that refusal is correct — an enlarged bitmap is not a more legible one — which
#: makes asking for a fixed number actively harmful here: measured, the committed scan
#: fixture holds **120 DPI**, so `render @200` returns
#: `insufficient_effective_resolution` and produces **no image at all** for exactly the
#: page whose whole reason for being rendered is that it has no text layer.
#:
#: `_render_dpi` reads the registry's floor and takes the smaller of the two, which is
#: what `batch_pdf.py::_export_dpi` does. This driver used to pass `RENDER_DPI`
#: straight through, and the discrepancy surfaced the moment the fixtures were run.
#:
#: TODO: [MVP] `diagnosis.min_dpi` is read through a helper rather than at import
#: time, because a `Final[int]` decided at import cannot call a loader that needs
#: `_lib` to be on the path first. `batch_pdf.py` already read it from the registry;
#: this is the same call.
RENDER_DPI: Final[int] = 200

#: The model that reads the fields. Text-only, because §6's chain hands it text.
FIELD_MODEL: Final[str] = llm_local.TEXT_MODEL


@dataclasses.dataclass(frozen=True, slots=True)
class FileOutcome:
    """What happened to one input file.

    Attributes:
        source: The file's path relative to the input root - also its mirrored
            location in the output.
        kind: ``"pdf"``, ``"image"``, or ``"invalid"``.
        route: Which operation produced the text, e.g. ``"layout_text"`` or
            ``"render+ocr"``, or ``None`` when no text was produced.
        text_path: The written `.txt`, relative to the output root.
        fields_path: The written `.json`, relative to the output root.
        note: A short explanation, for the invalid and refused cases - and for a
            partial reading, where it names what was dropped.
        partial: Whether the document was read **in part**. Declared as a field rather
            than left to a prefix match on the note: it is the fact the summary and
            the exit code turn on, and a consumer should be able to read it without
            parsing prose.

    """

    source: str
    kind: str
    route: str | None
    text_path: str | None
    fields_path: str | None
    note: str = ""
    partial: bool = False


#: Every outcome of this walk, in order.
OUTCOMES: list[FileOutcome] = []


def classify_file(path: pathlib.Path) -> str:
    """Decide whether a file is a PDF, an image, or neither.

    Kept as this driver's name for `_mirror.kind_of`, so a caller that already
    reaches for `batch.classify_file` keeps working while there is one definition of
    what a PDF is.

    Args:
        path: The file to classify.

    Returns:
        ``"pdf"``, ``"image"``, or ``"invalid"``.

    """
    return _mirror.kind_of(path)


def _relative_to(path: pathlib.Path, root: pathlib.Path) -> str:
    """Report a path relative to the walk's root, with forward slashes.

    Args:
        path: The path to report.
        root: The walk's root.

    Returns:
        The relative path as a string.

    """
    return _mirror.relative_to(path, root)


def _silently(
    call: Callable[..., _lib.Attempt], *args: object, **kwargs: object
) -> _lib.Attempt:
    """Call a driver method with its console output suppressed.

    Args:
        call: The driver method to call.
        *args: Its positional arguments.
        **kwargs: Its keyword arguments, e.g. ``save=False``.

    Returns:
        The attempt the driver returned.

    """
    return _mirror.silently(call, *args, **kwargs)


def _render_dpi(engine: PdfEngine, source: pathlib.Path, page: int) -> int:
    """Decide the resolution a page is rendered at, within what its pixels hold.

    §6's render step, with the one adjustment the adapter forces: the registry floor
    is the **target** and the page's own resolution is the **ceiling**. Measured on
    the committed scan fixture: `render @200` is refused
    (`insufficient_effective_resolution`) because the page holds 120 DPI, so a fixed
    request produces no bitmap for the one page that is being rendered *because* it
    has no text.

    Args:
        engine: The K2 adapter.
        source: The PDF being rendered.
        page: One-based page number.

    Returns:
        The floor, or the page's measured resolution when that is lower. An
        unmeasurable page returns the floor unchanged: the render's own refusal is a
        better answer than a number invented here.

    """
    floor = int(_lib.policy("diagnosis.min_dpi"))
    # The **adapter**, not `pdf_driver.effective_dpi`: that driver method exists to
    # print one probe line and returns ``None``, so it cannot hand back the number
    # this decision needs. Reading the adapter here is not a second implementation of
    # anything — it is the same call that driver makes, keeping its result.
    measured = engine.effective_dpi(source, page)
    if measured.value is None or measured.evidence is None:
        return floor

    held = measured.evidence.measurements.get("effective_dpi")
    if held is None:
        return floor

    return max(1, min(floor, int(held)))


def _validate_pdf(
    pdf_engine: PdfEngine, source: pathlib.Path
) -> tuple[str | None, str]:
    """Ask whether a PDF can be read at all, before asking for its text.

    §6's second validation step: *"if it is a PDF, determine whether it is protected
    by a password (and whether it is legible)"*. Both answers come from one `probe`
    call — K2 reports `encrypted` as a field of the document's facts, so there is no
    second reader and no password parameter anywhere.

    **Nothing is decrypted.** A password would have to arrive as an argument, and
    `NFR-05` keeps credentials out of parameters; the flow asks whether the document
    is protected, so *protected, skipped, said so* is the answer rather than an
    attempt this driver is not equipped to make.

    Args:
        pdf_engine: The K2 adapter.
        source: The PDF to inspect.

    Returns:
        A reason when the document cannot be read, or ``None`` when it can — plus a
        short note describing what was measured either way.

    """
    # **K2 answers a protected document with a typed refusal, not a flag.**
    # Measured on a real AES-256 file: `probe` returns `value: None` and
    # `reason.code: 'encrypted'`. So the refusal branch below is what catches it, and
    # the `observed["encrypted"]` check that follows is for the shape K2 *also*
    # documents — a document whose facts resolve while reporting `encrypted: True`.
    #
    # Both are kept because they are different facts: the first is *the file could
    # not be opened*, the second is *it opened and said it is protected*. A guard
    # reading only the second would report a genuinely locked file as readable, which
    # is why the refusal branch comes first and names its own code.
    probed = _silently(pdf_engine.probe, source)
    if probed.value is None:
        reason = probed.reason
        code = reason.code if reason is not None else "unknown"
        if code == "encrypted":
            return (
                "encrypted: the document needs a password, and this driver supplies "
                "none (a password is a credential, and credentials are never "
                "parameters). The flow asks whether a document is protected; "
                "*protected, skipped, said so* is the answer."
            ), ""
        return f"probe refused: {code}", ""

    # The value is an `Evidence`, and its two facts live in **different mappings**:
    # `page_count` is a *measurement*, `encrypted` is an *observation*. Reading them
    # as attributes would find neither and make the guard below silently useless.
    evidence = probed.value
    if evidence.observed.get("encrypted"):
        return (
            "encrypted: the document opened but reports itself as protected, and no "
            "password is supplied (a password is a credential)"
        ), ""

    pages = evidence.measurements.get("page_count")
    if pages == 0:
        return "the document reports no pages", ""

    return None, f"{int(pages)} page(s)" if pages else ""


def _legibility_of(
    raster_engine: RasterEngine, path: pathlib.Path
) -> tuple[str, float | None, float]:
    """Measure an image's sharpness and turn it into the decisor's vocabulary.

    One call, in one place, so the two branches that need it — a file that *is* an
    image, and a page that *rendered* one — cannot disagree about what it means. The
    threshold comes from the registry (`ADR-009`), never from a constant here.

    Args:
        raster_engine: The K3 adapter.
        path: The image to measure.

    Returns:
        The verdict (``"ok"``, ``"illegible"`` or the reason code), the sharpness
        when one was measured, and the threshold it was compared against.

    """
    threshold = float(_lib.policy("image.legibility_threshold"))
    measured = raster_engine.legibility(path, threshold)
    sharpness = (
        measured.evidence.measurements.get("laplacian_variance")
        if measured.evidence is not None
        else None
    )

    if measured.value is not None:
        return "ok", sharpness, threshold

    return (
        (measured.reason.code if measured.reason else "unknown"),
        sharpness,
        threshold,
    )


def _extract_text(
    pdf_engine: PdfEngine,
    ocr_engine: DoclingEngine,
    raster_engine: RasterEngine,
    path: pathlib.Path,
    kind: str,
) -> tuple[str | None, str | None, str]:
    """Produce a document's text, by whichever route the decisor names.

    **The rule lives in `decide`, not here.** This function measures what the
    decision needs, asks for it, and executes the answer — which is the split that
    makes the rule testable without paying for the route, and the reason the
    duplication below is gone.

    It used to hold `if shape in {"text", "mixed"}` — a second copy of the mapping
    `pdf.route_page` owns, and a copy `batch_pdf.py`'s own comment warns against.
    More importantly it held no legibility gate at all on the PDF branch, so a page
    whose pixels were measurably unreadable went to OCR anyway: measured, **9.2 s**
    for an answer of nothing.

    A **PDF is read page by page**, and the pages are concatenated in order. See
    `_extract_pdf_text` for why the decision is taken per page rather than once for
    the document.

    Args:
        pdf_engine: The K2 adapter.
        ocr_engine: The K4 adapter.
        raster_engine: The K3 adapter.
        path: The source file.
        kind: ``"pdf"`` or ``"image"``.

    Returns:
        The text, the route that produced it, and a note when it was refused.

    """
    min_chars = _lib.policy("reader.min_chars")

    if kind == "image":
        # A file that is already pixels. Its shape is not measured because it is not
        # in question: `kind_of` answered it, and asking K2 to classify a JPEG would
        # be a second opinion about a fact `_mirror` already established.
        legibility, sharpness, threshold = _legibility_of(raster_engine, path)
        verdict = decide.decide(
            shape="image",
            text_shapes=pdf_driver.TEXT_SHAPES,
            legibility=legibility,
            sharpness=sharpness,
            threshold=threshold,
            min_chars=min_chars,
        )
        if not verdict.proceeds:
            return None, None, verdict.reason
        return _ocr_text(ocr_engine, path)

    return _extract_pdf_text(pdf_engine, ocr_engine, raster_engine, path)


#: How many pages of one document this version reads.
#:
#: TODO: [MVP] **A proof-of-concept cap, not a policy — and it is declared rather
#: than assumed.** The real answer is not a smaller window: it is to read every page
#: and *chunk* the text so each generation fits `num_ctx`, merging the per-chunk
#: extractions. That is a dependency (a tokenizer, and a merge rule for fields two
#: chunks disagree about), so this version reads the first few pages and **says so in
#: the output**, which is the difference between a documented limit and a silent
#: truncation.
#:
#: The number is measured rather than chosen: three pages of the large fixture are
#: 1 262 characters, against a prompt budget of roughly 8 000 for `num_ctx: 4096`
#: (the whole 59-page document is 167 035 — an oversize prompt is an HTTP 400, not a
#: truncated answer). A larger cap would fit *this* fixture and fail on a denser one,
#: which is why the cap is conservative and the omission is reported per document.
#:
#: TODO: [MVP] A `--max-pages` flag would let a bench compare a capped run against a
#: full one. It is not here because the cap is a *limit* rather than a parameter, and
#: a flag invites treating the limited reading as the document.
MAX_PAGES: Final[int] = 3


#: What one page's text is separated by when the pages are joined. A form feed —
#: what `pdftotext` emits between pages and what a page break has meant in plain text
#: for decades. Deliberately **not** `ocr.SEPARATOR`, which separates *rows*: reusing
#: it would make a page break and a row break the same character.
PAGE_BREAK: Final[str] = "\f"


def _cap_pages(pages: list[int]) -> tuple[list[int], str]:
    """Apply this version's page cap, and report it when it bites.

    **The announcement is the point, not the cap.** A document read in part and
    reported as read is the same failure as a prompt cut by `num_ctx` — the answer
    arrives looking complete, and nothing says what was left out. So a capped read
    returns the pages it will read *and a sentence naming what it dropped*, and that
    sentence travels with the text to the console, the skip record and the exit code.

    Args:
        pages: Every page number the document has, in order.

    Returns:
        The pages to read, and a note that is empty when nothing was dropped.

    """
    if len(pages) <= MAX_PAGES:
        return pages, ""

    return pages[:MAX_PAGES], (
        f"PARTIAL: read the first {MAX_PAGES} of {len(pages)} pages — this version "
        f"caps a document at {MAX_PAGES} (MAX_PAGES); the text below is NOT the "
        "whole document"
    )


def _extract_pdf_text(
    pdf_engine: PdfEngine,
    ocr_engine: DoclingEngine,
    raster_engine: RasterEngine,
    path: pathlib.Path,
) -> tuple[str | None, str | None, str]:
    """Read every page of a PDF, deciding per page, and join what came back.

    **The decision is per page, and that is forced rather than chosen.** A PDF is a
    container whose pages are independent: the 59-page fixture has text pages, image
    pages and `blank` ones in the same file, and the 3-page one mixes both too.
    Reading only page 1 — which this driver used to do — answered a question about
    the document's *first* page and reported it as the document's text. On the large
    fixture that is 1 page of 59, and the fields extracted from it describe a cover.

    The pages are joined in **document order**, separated by a form feed (`\\f`),
    which is what a page break has meant in plain text for decades and what
    `pdftotext` itself emits. A reader that wants page boundaries can split on it
    without a second convention; a reader that does not can ignore it. The separator
    is deliberately **not** something the OCR driver uses: `ocr.SEPARATOR` is the
    *row* separator, and reusing it here would make a page break and a row break the
    same character.

    Pages go aside **individually**. A blank page, an illegible scan or an
    unmeasurable one is skipped with its own reason, and the document still produces
    the text of the pages that could be read — which is `FR-24`'s rule (*failure is
    partial*) applied one stage early. The alternative, refusing the whole document,
    would throw away 58 readable pages because the 59th is blank.

    Args:
        pdf_engine: The K2 adapter.
        ocr_engine: The K4 adapter.
        raster_engine: The K3 adapter.
        path: The PDF to read.

    Returns:
        The joined text, a route summary, and a note when **no** page produced text.
        The route names the operations that ran, e.g. ``"layout_text"`` or
        ``"layout_text+render+ocr"``, so a reader can see which pages took which
        branch without opening the sidecar.

    """
    probed = _silently(pdf_engine.probe, path)
    total: int | None = None
    if probed.value is not None:
        counted = probed.value.measurements.get("page_count")
        total = int(counted) if counted else None

    every = parse_pages(None, total)
    if not every:
        return None, None, "the document reports no pages"

    pages, partial = _cap_pages(every)

    min_chars = _lib.policy("reader.min_chars")
    scratch = pathlib.Path(tempfile.mkdtemp(prefix="docflow-batch-"))
    try:
        texts: list[str] = []
        routes: list[str] = []
        refusals: list[str] = []

        for page in pages:
            text, route, note = _read_page(
                pdf_engine, ocr_engine, raster_engine, path, page, scratch, min_chars
            )
            if text is None:
                refusals.append(f"p{page}: {note}")
                continue
            texts.append(text)
            if route not in routes:
                routes.append(route)

        if not texts:
            return None, None, "; ".join(refusals) or "no page produced text"

        # The cap note and any per-page refusals are joined, never one replacing the
        # other: a document can be both partial *and* have had a page go aside, and a
        # reader needs to know each separately.
        notes = [note for note in (partial, "; ".join(refusals)) if note]
        return _join_pages(texts), "+".join(routes), "; ".join(notes)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


#: What one page's text is separated by when the pages are joined. A form feed —
#: what `pdftotext` emits between pages and what a page break has meant in plain text
#: for decades. Deliberately **not** `ocr.SEPARATOR`, which separates *rows*: reusing
#: it would make a page break and a row break the same character.
PAGE_BREAK: Final[str] = "\f"


def _join_pages(texts: list[str]) -> str:
    """Join per-page readings into one document, with exactly one break between them.

    **The reader already ends every page with a form feed, and that is why this is
    not a plain `PAGE_BREAK.join`.** Measured: `layout_text` on a single page returns
    its text ending in `'\\n\\x0c'` — `pdftotext` terminates each page that way. So
    joining with a separator produced **two** form feeds between pages (6 blocks for a
    3-page document), and a consumer splitting on the page break would have seen an
    empty page between every real one.

    Each page is stripped of its trailing break and the breaks are then inserted once,
    so the invariant is *exactly one break between pages* rather than *at least one*.
    A page whose text is entirely a break contributes nothing and is dropped — which
    is correct: it had no text to contribute.

    Args:
        texts: The per-page readings, in document order.

    Returns:
        The joined text, with one form feed between pages and none at the end.

    """
    cleaned = [text.rstrip(PAGE_BREAK).rstrip() for text in texts]
    return PAGE_BREAK.join(part for part in cleaned if part)


def _read_page(
    pdf_engine: PdfEngine,
    ocr_engine: DoclingEngine,
    raster_engine: RasterEngine,
    path: pathlib.Path,
    page: int,
    scratch: pathlib.Path,
    min_chars: object,
) -> tuple[str | None, str | None, str]:
    """Read one page of a PDF, taking the route the decisor names for it.

    Args:
        pdf_engine: The K2 adapter.
        ocr_engine: The K4 adapter.
        raster_engine: The K3 adapter.
        path: The PDF.
        page: One-based page number.
        scratch: A directory for the rendered page, removed by the caller.
        min_chars: The registry's character floor.

    Returns:
        The page's text, the route that produced it, and a note when the page went
        aside.

    """
    measured = pdf_engine.classify(path, page)
    if measured.value is None and measured.evidence is None:
        reason = measured.reason
        code = reason.code if reason is not None else "unknown"
        return None, None, f"classify refused: {code}"

    # The shape is read from the evidence **whenever a shape was measured**, value or
    # no value: `classify` answers a blank page with `value=None` while still
    # reporting `shape='blank'`, and reading the shape only alongside a value
    # collapses *blank* into *unmeasurable*. That is `pdf.shape_of`'s documented
    # rule, and it is why this reads the evidence rather than the value.
    shape = ""
    if measured.evidence is not None:
        shape = str(measured.evidence.observed.get("shape", ""))

    resolution = _render_dpi(pdf_engine, path, page)

    # The page is rendered **before** the route is chosen, so the legibility reading
    # exists in time to decide whether reading the pixels is worth it. A text page
    # pays a render it does not need — which is the price of asking the question
    # first, and it is milliseconds against the OCR it can save. Rendering only for
    # image shapes would put the shape→pixels mapping back in this function.
    rendered = _silently(
        pdf_driver.render_page,
        pdf_engine,
        path,
        str(page),
        resolution,
        "ok",
        save=False,
    )
    legibility, sharpness, threshold = "", None, None
    image = scratch / f"{path.stem}-p{page}-dpi{resolution}.png"

    if rendered.succeeded:
        image.write_bytes(rendered.result.value.data)
        legibility, sharpness, threshold = _legibility_of(raster_engine, image)

    verdict = decide.decide(
        shape=shape,
        text_shapes=pdf_driver.TEXT_SHAPES,
        legibility=legibility,
        sharpness=sharpness,
        threshold=threshold,
        measured_dpi=resolution,
        min_chars=min_chars,
    )

    if not verdict.proceeds:
        return None, None, verdict.reason

    if verdict.route == decide.TEXT:
        attempt = _silently(
            pdf_driver.layout_text, pdf_engine, path, str(page), "ok", save=False
        )
        if not attempt.succeeded:
            return None, None, f"layout_text refused ({attempt.outcome.detail})"
        return attempt.result.value, "layout_text", ""

    if not rendered.succeeded:
        return None, None, f"render refused ({rendered.outcome.detail})"
    return _ocr_text(ocr_engine, image)


def _ocr_text(
    ocr_engine: DoclingEngine, image_path: pathlib.Path
) -> tuple[str | None, str | None, str]:
    """Read the text off a rendered page, with its layout ordered into rows.

    `ocr.layout` and not `ocr.read`: `read` reports `reading_order: 'not_resolved'`
    by design (`ReadResult`'s own docstring - ordering is Stage 2's work), so it is
    `layout` that satisfies §3's *"preserving the layout as far as possible"*.

    Args:
        ocr_engine: The K4 adapter.
        image_path: The image to read.

    Returns:
        The text, the route, and a note when it was refused.

    """
    # `"1"` and not `[1]`: `layout_rows` takes the selection **as a caller writes
    # it** — the text `--pages` accepts — and expands it itself through
    # `parse_pages`. Handing it a list reached that expansion with a list, which
    # raised `UsageError: page '[1]' is not a number or a range`. This is the same
    # boundary `pdf.py::render_page` and `pdf.py::layout_text` document, and the
    # reason all three take `written: str` rather than `list[int]`.
    attempt = _silently(
        ocr_driver.layout_rows, ocr_engine, image_path, "1", "ok", save=False
    )
    if not attempt.succeeded:
        return None, None, f"ocr refused ({attempt.outcome.detail})"
    return attempt.result.value, "render+ocr", ""


def _extract_fields(text: str) -> tuple[dict[str, object] | None, str]:
    """Ask the local model for the fields, out of the text just extracted.

    This is §6's last step and §4's first requirement: text plus a prompt.

    Args:
        text: The document's text.

    Returns:
        The fields, and a note when the call was refused.

    """
    engine = OllamaEngine()
    prompt = f"Extract the fields from this document's text.\n\n{text}"
    attempt = _silently(llm_local.extract_from_text, engine, FIELD_MODEL, "ok", prompt)
    if not attempt.succeeded:
        return None, f"llm.local did not answer ({attempt.outcome.detail})"
    if attempt.result.value is None:
        return None, "llm.local produced no value"
    return dict(attempt.result.value), ""


def walk(root: pathlib.Path) -> Iterator[pathlib.Path]:
    """Yield every file under `root`, in a stable order.

    Args:
        root: The directory to walk.

    Yields:
        Each file, sorted by its relative path.

    """
    yield from _mirror.walk(root)


def process_file(
    source: pathlib.Path,
    root: pathlib.Path,
    out_root: pathlib.Path,
    pdf_engine: PdfEngine,
    ocr_engine: DoclingEngine,
    raster_engine: RasterEngine,
) -> FileOutcome:
    """Process one file and write its mirrored outputs.

    Args:
        source: The file to process.
        root: The input root.
        out_root: The output root.
        pdf_engine: The K2 adapter.
        ocr_engine: The K4 adapter.
        raster_engine: The K3 adapter.

    Returns:
        What happened.

    """
    relative = _relative_to(source, root)
    kind = classify_file(source)
    mirror_dir = out_root / pathlib.Path(relative).parent
    mirror_dir.mkdir(parents=True, exist_ok=True)

    if kind == "invalid":
        note = f"{source.suffix or '(no suffix)'} is neither a PDF nor an image"
        _write_skipped(mirror_dir, source.stem, kind, note)
        return FileOutcome(relative, kind, None, None, None, note)

    # The legibility gate is **inside `_extract_text`** now, for every kind — not a
    # block here that only an image file reaches. A PDF whose page renders to
    # unreadable pixels needs the same gate as a blurred JPEG, and the two used to
    # disagree: measured, an `illegible` page of the committed scan fixture cost
    # **9.2 s** of OCR on this branch.
    if kind == "pdf":
        # §6's other validation: can this PDF be read at all? A password-protected
        # document is reported and skipped *before* anything is extracted from it,
        # which is the whole point of validating ahead of the work.
        refusal, _note = _validate_pdf(pdf_engine, source)
        if refusal is not None:
            _write_skipped(mirror_dir, source.stem, kind, refusal)
            return FileOutcome(relative, kind, None, None, None, refusal)

    text, route, note = _extract_text(
        pdf_engine, ocr_engine, raster_engine, source, kind
    )
    if text is None:
        _write_skipped(mirror_dir, source.stem, kind, note)
        return FileOutcome(relative, kind, None, None, None, note)

    stem = pathlib.Path(relative).stem
    text_path = mirror_dir / f"{stem}.txt"
    text_path.write_text(text, encoding="utf-8")

    fields, fields_note = _extract_fields(text)
    fields_path = None
    if fields is not None:
        target = mirror_dir / f"{stem}.json"
        target.write_text(
            json.dumps(fields, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        fields_path = _relative_to(target, out_root)

    # **The extraction's note is joined to the reading's, never substituted for it.**
    # The two answer different questions — *did the model produce fields* and *was the
    # text the whole document* — and a document can be partial *and* extracted. The
    # first version of the page cap assigned `fields_note` alone, so a capped run that
    # produced fields reported `ok` with the PARTIAL warning dropped: the truncation
    # this whole change exists to announce would have been silent exactly when the
    # pipeline looked most successful.
    notes = [note for note in (note, fields_note) if note]

    return FileOutcome(
        source=relative,
        kind=kind,
        route=route,
        text_path=_relative_to(text_path, out_root),
        fields_path=fields_path,
        note="; ".join(notes),
        partial=note.startswith("PARTIAL"),
    )


def mirror_directories(root: pathlib.Path, out_root: pathlib.Path) -> int:
    """Create an output directory for every input directory, including empty ones.

    Args:
        root: The input root.
        out_root: The output root.

    Returns:
        How many directories exist in the output, the root included.

    """
    return _mirror.mirror_directories(root, out_root)


def _write_skipped(
    mirror_dir: pathlib.Path, stem: str, kind: str, note: str
) -> pathlib.Path:
    """Record a file that was considered and deliberately not processed.

    Args:
        mirror_dir: The directory the document mirrors into.
        stem: The document's stem.
        kind: ``"pdf"``, ``"image"`` or ``"invalid"``.
        note: Why it was skipped.

    Returns:
        The path written.

    """
    return _mirror.write_skipped(mirror_dir, stem, kind, note)


def verify_mirror(root: pathlib.Path, out_root: pathlib.Path) -> list[str]:
    """Check that the output tree mirrors the input tree exactly.

    Args:
        root: The input root.
        out_root: The output root.

    Returns:
        One message per violation; empty when the mirror is exact.

    """
    return _mirror.verify_mirror(root, out_root)


def main(argv: list[str] | None = None) -> int:
    """Walk a folder, process every file, and verify the mirrored tree.

    Args:
        argv: The command-line arguments, or ``None`` for ``sys.argv``.

    Returns:
        The number of problems: mirrored-ness violations plus file refusals.

    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("input", type=pathlib.Path, help="the folder to walk")
    parser.add_argument(
        "--out",
        type=pathlib.Path,
        default=None,
        help="the output root (default: var/poc/batch)",
    )
    args = parser.parse_args(argv)

    root: pathlib.Path = args.input
    if not root.is_dir():
        parser.error(f"{root} is not a directory")

    out_root = args.out if args.out is not None else _lib.DEFAULT_OUT / "batch"
    _lib.set_out(out_root)
    _lib.reset()

    # The tree first, so a directory that holds no file still exists in the output
    # and the mirror is complete even if the walk finds nothing (`S3-T06`).
    directories = mirror_directories(root, out_root)

    pdf_engine = pdf_driver._engine()
    ocr_engine = ocr_driver._engine()
    raster_engine = image_driver._engine()

    print(f"in  = {root}")
    print(f"out = {out_root}")
    print()

    files = list(walk(root))
    for source in files:
        outcome = process_file(
            source, root, out_root, pdf_engine, ocr_engine, raster_engine
        )
        OUTCOMES.append(outcome)

        if outcome.text_path is None:
            print(f" -- {outcome.source:52} {outcome.kind:7} {outcome.note}")
        elif outcome.fields_path is None:
            # **A `.txt` with no fields is not the same as a `.txt` with fields**, and
            # this used to print the two the same way — `(no fields)` with the note
            # dropped. Measured on the 59-page fixture: 167 035 characters of text,
            # no extraction, and the run reported success because the *text* step had
            # worked. The note is what says why, so it is printed and counted.
            print(
                f" .. {outcome.source:52} {outcome.kind:7} "
                f"{outcome.route or '-':12} -> {outcome.text_path} + NO FIELDS: "
                f"{outcome.note}"
            )
        elif outcome.partial:
            # Text *and* fields, from a document read in part. The `~` is the third
            # state and it exists because the other two would each be a lie: `ok`
            # would not mention the omission, and `..` would hide that an extraction
            # happened.
            print(
                f"  ~ {outcome.source:52} {outcome.kind:7} "
                f"{outcome.route:12} -> {outcome.text_path} + {outcome.fields_path}\n"
                f"      {outcome.note}"
            )
        else:
            print(
                f" ok {outcome.source:52} {outcome.kind:7} "
                f"{outcome.route:12} -> {outcome.text_path} + {outcome.fields_path}"
            )

    print()
    print("=== the mirror")
    problems = verify_mirror(root, out_root)
    if problems:
        for problem in problems:
            print(f" !! {problem}")
    else:
        print(
            f" ok {len(files)} file(s) and {directories} director(ies) mirrored "
            "at the same relative paths"
        )

    print()
    print(f"{'file':<10}{'count':>6}")
    for kind in ("pdf", "image", "invalid"):
        print(f"{kind:<10}{sum(1 for o in OUTCOMES if o.kind == kind):>6}")
    wrote = sum(1 for outcome in OUTCOMES if outcome.fields_path)
    print(f"{'fields':<10}{wrote:>6}")
    print()

    # **Skipped and failed are different answers, and this used to count them
    # together.** A password-protected PDF, an illegible scan and a `.md` file are
    # the flow working — it asked, the document said no, and the output says why. A
    # file that was in scope and produced nothing it should have is the run failing.
    # One number over both made a clean run of unprocessable inputs look broken.
    skipped = sum(1 for outcome in OUTCOMES if outcome.kind == "invalid")
    skipped += sum(
        1
        for outcome in OUTCOMES
        if outcome.text_path is None and outcome.kind != "invalid" and outcome.note
    )
    failed = sum(
        1 for outcome in OUTCOMES if outcome.text_path is None and not outcome.note
    )
    # **A document whose text was produced but whose fields were not is counted too.**
    # It is the failure this driver is most likely to hide: the expensive steps all
    # succeeded, so every other line says `ok`, and the consumer downstream gets an
    # empty answer from a run that reported no problems. The 59-page fixture did
    # exactly that — 167 035 characters read, no fields, exit code 0.
    unextracted = sum(
        1
        for outcome in OUTCOMES
        if outcome.text_path is not None and outcome.fields_path is None
    )
    # **A partial reading is counted, and it is the one this version must not hide.**
    # The cap is a deliberate PoC limit, so a run over long documents *should* report
    # partials — and if they were absent from the tally, the limit would be invisible
    # in the one place a reader looks for the run's verdict.
    partial = sum(1 for outcome in OUTCOMES if outcome.partial)
    print(f"{'skipped':<10}{skipped:>6}   (refused on purpose, each with its reason)")
    print(f"{'failed':<10}{failed:>6}   (in scope and produced nothing)")
    print(
        f"{'no fields':<10}{unextracted:>6}   (text read, but the model produced none)"
    )
    print(
        f"{'partial':<10}{partial:>6}   "
        f"(read in part: MAX_PAGES = {MAX_PAGES}, the rest of the document is NOT read)"
    )
    print()

    if not problems and not failed and not unextracted and not partial:
        print("every file was answered and the tree mirrors exactly.")
        return 0
    return len(problems) + failed + unextracted + partial


if __name__ == "__main__":
    sys.exit(main())
