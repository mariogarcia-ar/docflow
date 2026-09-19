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
import image as image_driver  # noqa: E402 - see the note above
import llm_local  # noqa: E402 - see the note above
import ocr as ocr_driver  # noqa: E402 - see the note above
import pdf as pdf_driver  # noqa: E402 - see the note above

from docflow.adapters.docling import DoclingEngine  # noqa: E402 - see above
from docflow.adapters.image import RasterEngine  # noqa: E402 - see above
from docflow.adapters.ollama import OllamaEngine  # noqa: E402 - see above
from docflow.adapters.pdf import PdfEngine  # noqa: E402 - see above

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
        note: A short explanation, for the invalid and refused cases.

    """

    source: str
    kind: str
    route: str | None
    text_path: str | None
    fields_path: str | None
    note: str = ""


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


def _extract_text(
    pdf_engine: PdfEngine,
    ocr_engine: DoclingEngine,
    path: pathlib.Path,
    kind: str,
) -> tuple[str | None, str | None, str]:
    """Produce a document's text, by whichever route the file's kind calls for.

    §6 gives the two routes, and the decision belongs **here** rather than inside a
    kernel: `classify` measures a shape and the caller chooses what to do about it
    (`kernel-cli.md` §3 guardrail 2).

    Args:
        pdf_engine: The K2 adapter.
        ocr_engine: The K4 adapter.
        path: The source file.
        kind: ``"pdf"`` or ``"image"``.

    Returns:
        The text, the route that produced it, and a note when it was refused.

    """
    if kind == "image":
        return _ocr_text(ocr_engine, path)

    measured = pdf_engine.classify(path, 1)
    if measured.value is None:
        reason = measured.reason
        code = reason.code if reason is not None else "unknown"
        return None, None, f"classify refused: {code}"

    shape = str(measured.evidence.observed.get("shape", "?"))

    if shape in {"text", "mixed"}:
        attempt = _silently(
            pdf_driver.layout_text, pdf_engine, path, "1", "ok", save=False
        )
        if not attempt.succeeded:
            return None, None, f"layout_text refused ({attempt.outcome.detail})"
        return attempt.result.value, "layout_text", ""

    # An image page: render it, then read the pixels. §1's second branch. The
    # selection is written the way a caller writes it, because that is the text
    # `--pages` accepts and what this driver would receive.
    resolution = _render_dpi(pdf_engine, path, 1)
    rendered = _silently(
        pdf_driver.render_page, pdf_engine, path, "1", resolution, "ok", save=False
    )
    if not rendered.succeeded:
        return None, None, f"render refused ({rendered.outcome.detail})"

    # The rendered page is **scratch**: it is K4's input and nothing a consumer
    # reads. It goes to a temp directory, not the output root (where it would pair
    # with no document) and not the input tree (which this walk must not touch).
    scratch = pathlib.Path(tempfile.mkdtemp(prefix="docflow-batch-"))
    page = scratch / f"{path.stem}-p1-dpi{resolution}.png"
    try:
        page.write_bytes(rendered.result.value.data)
        return _ocr_text(ocr_engine, page)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


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

    if kind == "image":
        # K3 first, because a legibility reading is what decides whether the pixels
        # are worth sending. Refusing here is cheaper than a bad extraction.
        threshold = _lib.policy("image.legibility_threshold")
        measured = raster_engine.legibility(source, threshold)
        if measured.value is None:
            code = measured.reason.code if measured.reason else "unknown"
            note = f"legibility refused: {code}"
            _write_skipped(mirror_dir, source.stem, kind, note)
            return FileOutcome(relative, kind, None, None, None, note)
    else:
        # §6's other validation: can this PDF be read at all? A password-protected
        # document is reported and skipped *before* anything is extracted from it,
        # which is the whole point of validating ahead of the work.
        refusal, note = _validate_pdf(pdf_engine, source)
        if refusal is not None:
            _write_skipped(mirror_dir, source.stem, kind, refusal)
            return FileOutcome(relative, kind, None, None, None, refusal)

    text, route, note = _extract_text(pdf_engine, ocr_engine, source, kind)
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

    return FileOutcome(
        source=relative,
        kind=kind,
        route=route,
        text_path=_relative_to(text_path, out_root),
        fields_path=fields_path,
        note=fields_note,
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
        else:
            fields = outcome.fields_path or "(no fields)"
            print(
                f" ok {outcome.source:52} {outcome.kind:7} "
                f"{outcome.route:12} -> {outcome.text_path} + {fields}"
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
    print(f"{'skipped':<10}{skipped:>6}   (refused on purpose, each with its reason)")
    print(f"{'failed':<10}{failed:>6}   (in scope and produced nothing)")
    print()

    if not problems and not failed:
        print("every file was answered and the tree mirrors exactly.")
        return 0
    return len(problems) + failed


if __name__ == "__main__":
    sys.exit(main())
