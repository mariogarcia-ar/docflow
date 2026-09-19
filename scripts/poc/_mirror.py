"""The folder-in / mirrored-tree-out plumbing shared by the batch drivers.

`batch.py` (§6, the whole chain) and `batch_pdf.py` (§1, extraction and export
only) are two pipelines over one idea: a folder goes in, and an output tree that
mirrors its structure comes out. That idea is not either driver's - it is what
`FR-28` and `S3-T06` require of the batch mode - so the parts that implement it
live here rather than being copied.

Why this module exists rather than an import between the two drivers
--------------------------------------------------------------------

`batch_pdf.py` needs the mirror, the skip records and the sorted walk, and it
needs **none** of `batch.py`'s other half: no OCR engine, no local model, no
field extraction. Importing `batch` to reach the helpers would work and is cheap
(the adapters import their libraries lazily), but it would make a PDF-only walk
depend on the code that composes K4 and K5 - so a change to the field extraction
could break a driver that never extracts a field. The dependency would be on the
*file* rather than on the *idea*.

The same rule the drivers themselves follow applies: reusing a **module**, not
re-implementing it. This is the module.

What is *not* here
------------------

The routing decision - which operation a measured page shape calls for. It is one
idea with one owner, and that owner is `pdf.py`, because the shapes it routes are
K2's (`PAGE_SHAPES`). Both batch drivers call it rather than deciding again.

This module imports **standard library only**, for the same reason `_lib.py` does:
a driver imports it before `docflow` is on `sys.path`.
"""

from __future__ import annotations

import contextlib
import io
import json
import pathlib
from collections.abc import Callable, Iterator, Sequence
from typing import Any, Final

__all__: list[str] = [
    "IMAGE_SUFFIXES",
    "PDF_SUFFIXES",
    "directory_problems",
    "kind_of",
    "mirror_directories",
    "relative_to",
    "silently",
    "verify_mirror",
    "verify_mirror_for",
    "walk",
    "write_skipped",
]

#: Suffixes K3 accepts. Anything outside this set and K2's is *not valid* for a
#: batch pipeline, and §6 names that as a third outcome rather than an error.
IMAGE_SUFFIXES: Final[frozenset[str]] = frozenset(
    {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}
)

#: Suffixes K2 accepts.
PDF_SUFFIXES: Final[frozenset[str]] = frozenset({".pdf"})


def kind_of(path: pathlib.Path) -> str:
    """Decide whether a file is a PDF, an image, or neither.

    §6 names the third case explicitly, and it is the one the flow does not say
    what to do about. A batch driver treats it as a **reported outcome** rather
    than a failure: the file gets a mirrored entry naming `unsupported_format`, so
    a consumer sees a document that was considered and skipped rather than one
    that is missing with no explanation.

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


def relative_to(path: pathlib.Path, root: pathlib.Path) -> str:
    """Report a path relative to the walk's root, with forward slashes.

    Args:
        path: The path to report.
        root: The walk's root.

    Returns:
        The relative path as a string.

    """
    return path.relative_to(root).as_posix()


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


def silently(call: Callable[..., Any], *args: object, **kwargs: object) -> Any:
    """Call a driver method with its console output suppressed.

    The drivers print one line per probe plus assorted detail, which is right for a
    console and wrong inside a batch: dozens of probe lines per document would bury
    the one line per file that an operator needs. The outcome is still **recorded**
    in `_lib.OUTCOMES`, so a nested refusal keeps its bucket even though it is not
    printed - and the returned `Attempt` carries the result, so a batch never calls
    the adapter a second time.

    Args:
        call: The driver method to call.
        *args: Its positional arguments.
        **kwargs: Its keyword arguments, e.g. ``save=False``.

    Returns:
        Whatever `call` returned, printing suppressed.

    """
    sink = io.StringIO()
    with contextlib.redirect_stdout(sink):
        return call(*args, **kwargs)


def mirror_directories(root: pathlib.Path, out_root: pathlib.Path) -> int:
    """Create an output directory for every input directory, including empty ones.

    `S3-T06` requires the tree to be *"preserved exactly, including empty
    directories"*, and the first run of `batch.py` proved why it matters: the
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


def write_skipped(
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
    relative path, and **every input directory exists in the output**, including
    the ones that held no file (`S3-T06`).

    This is the whole-tree check, which is what `batch.py` wants: §6 takes any file
    and decides what it is. A driver scoped to one kind of file wants
    `verify_mirror_for` instead.

    Args:
        root: The input root.
        out_root: The output root.

    Returns:
        One message per violation; empty when the mirror is exact.

    """
    problems = directory_problems(root, out_root)

    for source in walk(root):
        relative = pathlib.Path(relative_to(source, root))
        children = list((out_root / relative.parent).glob(f"{relative.stem}.*"))
        if not children:
            problems.append(f"no output for: {relative.as_posix()}")

    return problems


def directory_problems(root: pathlib.Path, out_root: pathlib.Path) -> list[str]:
    """Check that every input directory exists in the output.

    Directories are checked whole even by a scope-limited driver: an input
    directory absent from the output is a real violation regardless of what it held
    (`S3-T06`).

    Args:
        root: The input root.
        out_root: The output root.

    Returns:
        One message per missing directory; empty when every one is present.

    """
    return [
        f"missing directory: {relative_to(directory, root)}/"
        for directory in sorted(path for path in root.rglob("*") if path.is_dir())
        if not (out_root / directory.relative_to(root)).is_dir()
    ]


def verify_mirror_for(
    root: pathlib.Path, out_root: pathlib.Path, sources: Sequence[pathlib.Path]
) -> list[str]:
    """Check the mirror over the files a scope-limited driver was asked to walk.

    `verify_mirror` asserts over *every* file under the root, which is right for
    `batch.py`. A driver named for one kind of file - `batch_pdf.py`, `batch_image.py`
    - was never asked about the others, and reporting a `.md` beside its inputs as a
    violation is how a check stops being read: it blames the run for something no one
    requested.

    Args:
        root: The input root.
        out_root: The output root.
        sources: The files this walk took responsibility for.

    Returns:
        One message per violation; empty when the mirror is exact for this scope.

    """
    problems = directory_problems(root, out_root)

    for source in sources:
        relative = pathlib.Path(relative_to(source, root))
        children = list((out_root / relative.parent).glob(f"{relative.stem}.*"))
        if not children:
            problems.append(f"no output for: {relative.as_posix()}")

    return problems
