"""The batch walk: a folder in, a mirrored tree out.

`my_kernel_flow.md` §6, made runnable:

> takes a folder as input; for each file decides whether it is an image / PDF / not
> valid; a PDF gets its text extracted to `.txt` or is exported to an image; an
> image gets OCR and its text saved to `.txt`; with the result, `llm.local` extracts
> the fields; **the input folder structure is mirrored in the output**, so an
> input-vs-output and a run-vs-run comparison is direct.

This **is not K1**. K1 (`kernels/orchestrator.py`) drives a stage graph over units
with a ledger, a cache key per stage and pause/resume; this has none of that and is
not trying to. What it does is compose the adapters the way the flow describes, for
one walk of a folder - which is the piece none of the single-kernel drivers can do,
because each of them proves one adapter in isolation.

Where the pieces come from, since none of this is re-invented here:

- **classification** - `pdf.classify_page`, the same call `pdf.py` probes;
- **text** - `pdf.layout_text` on the adapter (not on the port, `plans/README.md`
  §3), or `ocr.layout_rows` after a render;
- **render** - `pdf.render_page`, the operation that feeds K4;
- **fields** - `llm_local.extract_from_text`, the same call `llm_local.py` probes.

Run it:

    python scripts/poc/orchestrator.py <input-dir> [reivindicar] [--out DIR]
    python scripts/poc/orchestrator.py tests/fixtures/casos --out var/poc/batch

The mirror is the deliverable, so this driver **asserts** it rather than printing
it: every input file must have a counterpart at the same relative path, and every
input directory must exist in the output even when empty (`FR-28`).
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import io
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
# everywhere else.
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
#: pipeline, and §6 names that as a third outcome rather than an error.
IMAGE_SUFFIXES: Final[frozenset[str]] = frozenset(
    {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}
)

#: Suffixes K2 accepts.
PDF_SUFFIXES: Final[frozenset[str]] = frozenset({".pdf"})

#: The resolution a page is rendered at before OCR. 200 DPI is the floor the
#: registry's `diagnosis.min_dpi` declares, so a render below it would hand K4
#: pixels the corpus considers too thin to read.
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

    §6 names the third case explicitly, and it is the one the flow does not say what
    to do about. This driver treats it as a **reported outcome** rather than a
    failure: the file gets a mirrored entry naming `unsupported_format`, so a
    consumer sees a document that was considered and skipped rather than one that is
    missing with no explanation.

    Args:
        path: The file to classify.

    Returns:
        ``"pdf"``, ``"image"``, or ``"invalid"``.

    """
    suffix = path.suffix.lower()
    if suffix in PDF_SUFFIXES:
        return "pdf"
    if suffix in IMAGE_SUFFIXES:
        return "image"
    return "invalid"


def _relative_to(path: pathlib.Path, root: pathlib.Path) -> str:
    """Report a path relative to the walk's root, with forward slashes.

    Args:
        path: The path to report.
        root: The walk's root.

    Returns:
        The relative path as a string.

    """
    return path.relative_to(root).as_posix()


def _silently(
    call: Callable[..., _lib.Attempt], *args: object, **kwargs: object
) -> _lib.Attempt:
    """Call a driver method with its console output suppressed.

    The drivers print one line per probe plus assorted detail, which is right for a
    console and wrong inside a batch: 49 probe lines per document would bury the one
    line per file that an operator needs. The outcome is still **recorded** in
    `_lib.OUTCOMES`, so a nested refusal keeps its bucket even though it is not
    printed - and the returned `Attempt` carries the result, so the batch never
    calls the adapter a second time.

    Args:
        call: The driver method to call.
        *args: Its positional arguments.
        **kwargs: Its keyword arguments, e.g. ``save=False``.

    Returns:
        The attempt the driver returned.

    """
    sink = io.StringIO()
    with contextlib.redirect_stdout(sink):
        return call(*args, **kwargs)


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
            pdf_driver.layout_text, pdf_engine, path, [1], "ok", save=False
        )
        if not attempt.succeeded:
            return None, None, f"layout_text refused ({attempt.outcome.detail})"
        return attempt.result.value, "layout_text", ""

    # An image page: render it, then read the pixels. §1's second branch. The
    # selection is written the way a caller writes it, because that is the text
    # `--pages` accepts and what this driver would receive.
    rendered = _silently(
        pdf_driver.render_page, pdf_engine, path, "1", RENDER_DPI, "ok", save=False
    )
    if not rendered.succeeded:
        return None, None, f"render refused ({rendered.outcome.detail})"

    # The rendered page is **scratch**: it is K4's input and nothing a consumer
    # reads. It goes to a temp directory, not the output root (where it would pair
    # with no document) and not the input tree (which this walk must not touch).
    scratch = pathlib.Path(tempfile.mkdtemp(prefix="docflow-batch-"))
    page = scratch / f"{path.stem}-p1-dpi{RENDER_DPI}.png"
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
    attempt = _silently(
        ocr_driver.layout_rows, ocr_engine, image_path, [1], "ok", save=False
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

    Sorted rather than filesystem order, so two runs of the same tree produce the
    same report and a diff between them means something.

    Args:
        root: The directory to walk.

    Yields:
        Each file, sorted by its relative path.

    """
    yield from sorted(
        (path for path in root.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(root).as_posix(),
    )


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

    `S3-T06` requires the tree to be *"preserved exactly, including empty
    directories"*, and the first run of this driver proved why it matters: the
    mirror check reported `missing directory: vacia/`. An empty directory is not
    noise - it is a statement about the corpus, and a consumer comparing input to
    output has to be able to see that it was walked and held nothing.

    Args:
        root: The input root.
        out_root: The output root.

    Returns:
        How many directories exist in the output, the root included.

    """
    out_root.mkdir(parents=True, exist_ok=True)
    created = 1
    for directory in sorted(path for path in root.rglob("*") if path.is_dir()):
        (out_root / directory.relative_to(root)).mkdir(parents=True, exist_ok=True)
        created += 1
    return created


def _write_skipped(
    mirror_dir: pathlib.Path, stem: str, kind: str, note: str
) -> pathlib.Path:
    """Record a file that was considered and deliberately not processed.

    The alternative is an empty directory entry, which reads as *the file was never
    seen*. A `.skipped.json` naming the reason makes *considered and skipped*
    distinguishable from *missing* - the same distinction the Contract's
    `catalog: unverified / not_run` exists to draw.

    It is deliberately **not** named `<stem>.json`: that name means *these are the
    extracted fields*, and a consumer that globbed for `.json` would read a skip
    record as an empty extraction. A different suffix cannot be mistaken for one.

    Args:
        mirror_dir: The directory the document mirrors into.
        stem: The document's stem.
        kind: ``"pdf"``, ``"image"`` or ``"invalid"``.
        note: Why it was skipped.

    Returns:
        The path written.

    """
    record = {"skipped": True, "kind": kind, "reason": note}
    target = mirror_dir / f"{stem}.skipped.json"
    target.write_text(
        json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return target


def verify_mirror(root: pathlib.Path, out_root: pathlib.Path) -> list[str]:
    """Check that the output tree mirrors the input tree exactly.

    The mirror is the deliverable, so it is asserted rather than eyeballed
    (`FR-28`). Two things are checked: every input file has *something* at its
    relative path - an extracted `.txt`/`.json`, or a `.skipped.json` naming the
    reason - and **every input directory exists in the output**, including the ones
    that held no file (`S3-T06`).

    Args:
        root: The input root.
        out_root: The output root.

    Returns:
        One message per violation; empty when the mirror is exact.

    """
    problems: list[str] = []

    for directory in sorted(path for path in root.rglob("*") if path.is_dir()):
        mirrored = out_root / directory.relative_to(root)
        if not mirrored.is_dir():
            problems.append(f"missing directory: {_relative_to(directory, root)}/")

    for source in walk(root):
        relative = pathlib.Path(_relative_to(source, root))
        children = list((out_root / relative.parent).glob(f"{relative.stem}.*"))
        if not children:
            problems.append(f"no output for: {relative.as_posix()}")

    return problems


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

    refusals = sum(1 for outcome in OUTCOMES if outcome.text_path is None)
    if not problems and not refusals:
        print("every file was processed and the tree mirrors exactly.")
        return 0
    if refusals:
        print(f"{refusals} file(s) produced no text; see the notes above.")
    return len(problems) + refusals


if __name__ == "__main__":
    sys.exit(main())
