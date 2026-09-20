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

import argparse
import atexit
import contextlib
import dataclasses
import hashlib
import io
import json
import pathlib
import time
from collections.abc import Callable, Iterator, Sequence
from typing import Any, Final

__all__: list[str] = [
    "IMAGE_SUFFIXES",
    "JOURNAL_NAME",
    "PDF_SUFFIXES",
    "Resume",
    "add_resume_flag",
    "batch_parser",
    "digest_of",
    "directory_problems",
    "kind_of",
    "mirror_directories",
    "relative_to",
    "report_mirror",
    "signature_of",
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

    The resume journal is **excluded by name**. It is written into an output root,
    and an output root is a legitimate input for a later driver (`batch_llm_local.py`
    reads `batch_pdf.py`'s tree) - so without this exclusion one driver would walk
    its own or another's journal and report it as a document. The `.skipped.json`
    records are deliberately *not* excluded: they are per-document findings, and a
    consumer that walks a tree should see them (the suffix-selecting drivers filter
    them by the suffix their mode reads, which is a statement about their scope
    rather than about this walk).

    Args:
        root: The directory to walk.

    Yields:
        Each file, sorted by its relative path.

    """
    yield from sorted(
        (
            path
            for path in root.rglob("*")
            if path.is_file() and path.name != JOURNAL_NAME
        ),
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


def digest_of(path: pathlib.Path) -> str:
    """Fingerprint a file's bytes, so a re-run can tell it apart from itself.

    The journal is only sound if an **edited input is reprocessed**. A signature over
    the driver's settings catches *the run changed*; this catches *the file changed*,
    and the two are independent - a caller who re-exports a PDF under the same name
    has changed the input without changing any flag.

    Args:
        path: The file to fingerprint.

    Returns:
        A hex digest, or ``""`` when the file could not be read. An empty digest is
        **not a stand-in for content**: `Resume.is_done` treats it as *cannot be
        signed, therefore never skipped*, so an unreadable file is attempted rather
        than assumed unchanged.

    """
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
    except OSError:
        return ""
    return digest.hexdigest()


def signature_of(**parts: object) -> str:
    """Fingerprint the settings a run was made under.

    **The whole safety of skipping rests on this.** A journal keyed only by path
    would report a document as done after a run that used a different model, a
    different page selection or a different target resolution - and the second run's
    output would be a mix of two configurations that nothing distinguishes.

    The parts are canonicalised (`sort_keys`) and hashed, so adding a setting to a
    driver is one keyword and cannot accidentally reorder anything.

    Args:
        **parts: The settings that decide the output, e.g. ``model=``, ``pages=``,
            ``mode=``. Values must be JSON-encodable; a mapping's **content** is
            covered, so changing a schema changes the signature.

    Returns:
        A hex digest.

    """
    canonical = json.dumps(parts, sort_keys=True, default=repr)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


#: The resume journal's filename, inside an output root. Hidden, and excluded from
#: `walk` by name, because a tree this module helped write is a legitimate input to
#: another driver.
JOURNAL_NAME: Final[str] = ".batch_journal.json"


@dataclasses.dataclass(slots=True)
class Resume:
    """The record of what a previous run of the **same** driver already finished.

    Why this exists
    ---------------

    Every driver here documents *"no ledger, no cache key, no `pause`/`resume`"*, and
    that was true: killing a walk over 11k documents (`prd.md`) and starting it again
    re-paid for every document, which on K4 is an ONNX load per file and on K6 is
    money. This is the smallest thing that closes that - **not** K1. It has no stage
    graph, no cache key per stage and no derived manifest; it answers one question,
    *was this file already answered, by this driver, under these settings*.

    What it refuses to do
    ---------------------

    - **A refusal is never recorded.** Only a file that produced its output is
      marked done. Otherwise a transient condition becomes permanent: a K6 run with
      no credential refuses *every* document with `provider_unavailable`, and a
      journal written from it would make a later credentialed run skip the entire
      corpus and report success. The same argument covers a render refused for
      `insufficient_effective_resolution` and a legibility gate that found no
      sidecar. A refusal is retried on the next run, always.
    - **A changed input is not skipped.** The entry carries the file's own digest.
    - **A changed signature is not used at all.** Settings that differ make this a
      different run, so the journal is discarded rather than partially trusted - and
      `stale` says so, because a run that silently ignored its journal would look
      like a run that had nothing to resume.

    Attributes:
        path: The journal file.
        driver: The driver's name, so two drivers pointed at one output root do not
            read each other's entries.
        signature: This run's settings fingerprint.
        entries: The recorded entries, keyed by the input's relative path.
        reused: How many files this run skipped, counted as they are asked about.
        stale: Whether a journal existed and was discarded for a different
            signature.

    """

    path: pathlib.Path
    driver: str
    signature: str
    entries: dict[str, dict[str, Any]] = dataclasses.field(default_factory=dict)
    reused: int = 0
    stale: bool = False
    saving: bool = True
    _unflushed: int = 0
    _opened_at: float = dataclasses.field(default_factory=time.monotonic)

    @classmethod
    def open(
        cls,
        out_root: pathlib.Path,
        driver: str,
        signature: str,
        *,
        redo: bool = False,
    ) -> Resume:
        """Load the journal a previous run of this driver left, if it is usable.

        Args:
            out_root: The output root the run writes into.
            driver: The driver's own name.
            signature: This run's settings fingerprint, from `signature_of`.
            redo: ``True`` to ignore the journal entirely - the caller asked for
                every file again.

        Returns:
            The journal, empty when there was none, when it belonged to another
            driver or another signature, or when `redo` was asked for.

        """
        target = out_root / JOURNAL_NAME
        if redo:
            return cls(target, driver, signature)
        try:
            stored = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # Absent, unreadable or corrupt: no resumption either way, and never a
            # guess about which entries were good. A corrupt journal costs a full
            # re-run, which is the safe direction.
            return cls(target, driver, signature)

        if stored.get("driver") != driver or stored.get("signature") != signature:
            return cls(target, driver, signature, stale=True)

        entries = stored.get("entries")
        if not isinstance(entries, dict):
            return cls(target, driver, signature, stale=True)
        return cls(target, driver, signature, entries=entries)

    def is_done(self, relative: str, digest: str) -> bool:
        """Whether a previous run already answered for this file, unchanged.

        Args:
            relative: The input's path relative to the walk's root.
            digest: The input's own fingerprint, from `digest_of`.

        Returns:
            ``True`` when the entry exists and was recorded against the same bytes.
            An empty digest is never done - an unsignable file is attempted.

        """
        if not digest:
            return False
        entry = self.entries.get(relative)
        if entry is None or entry.get("digest") != digest:
            return False
        self.reused += 1
        return True

    def record(self, relative: str, digest: str, **facts: object) -> None:
        """Mark a file as answered, with the facts that make the entry checkable.

        Args:
            relative: The input's path relative to the walk's root.
            digest: The input's fingerprint. An empty digest records nothing,
                because an entry that cannot be invalidated is worse than no entry.
            **facts: What the driver wants a later reader to see - the artifact it
                wrote, and whatever measurement the entry turns on.

        """
        if not digest:
            return
        self.entries[relative] = {"digest": digest, **facts}
        self._unflushed += 1

    def flush_if_due(self, every: int = 50, seconds: float = 30.0) -> None:
        """Write the journal when enough files **or** enough time have gone by.

        **Both triggers are needed, and the count alone is not enough - that was a
        real defect, found by interrupting a walk of `tests/fixtures/` and finding no
        journal at all.** Two failure modes with different shapes:

        - A count threshold alone is *unreachable on a short walk*. Measured: 20
          images read, `^C`, no journal - because the threshold was 100 and the run
          never got there. The files it finished were lost exactly as they were
          before this journal existed.
        - A time threshold alone is *coarse on a fast walk*. `batch_image.py` measures
          a file in milliseconds, so a few seconds is thousands of entries.

        Together they bound the loss to *whatever happened in the last 30 seconds*,
        which on this corpus is a handful of files rather than the whole run. Writing
        once per file would instead cost O(n) bytes per file - on 11k documents that
        is gigabytes of writing for a bookkeeping file.

        Args:
            every: How many records may accumulate before a write. ``0`` disables the
                count trigger.
            seconds: How long may pass before a write. ``0`` disables the time
                trigger.

        """
        if not self.saving:
            return
        due_count = every > 0 and self._unflushed >= every
        due_time = seconds > 0 and (time.monotonic() - self._opened_at) >= seconds
        if due_count or due_time:
            self.flush()

    def flush(self) -> pathlib.Path | None:
        """Write the journal, atomically enough that a kill cannot truncate it.

        A run that is killed half way leaves a journal covering the files it did
        finish, which is the whole point - so this is called as the walk goes rather
        than once at the end, and the write is a rename so a kill during it leaves
        the previous journal intact instead of a half-written one.

        **A `--no-save` run writes nothing, and this is where that is enforced.** The
        flag means *do not write output*, and a journal is output: a dry run that
        left one would make the next real run skip exactly the files the dry run
        declined to write. Enforcing it in the object - rather than at each of the six
        call sites - is why the callers have no `if` around it, and why `saving` is a
        **field** instead of a parameter: there is one answer per journal, and a
        caller that passed the wrong one at one of two call sites would defeat the
        other.

        Returns:
            The path written, or ``None`` when the run is not saving.

        """
        if not self.saving:
            return None
        payload = {
            "driver": self.driver,
            "signature": self.signature,
            "entries": self.entries,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        staging = self.path.with_name(self.path.name + ".tmp")
        staging.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        staging.replace(self.path)
        self._unflushed = 0
        self._opened_at = time.monotonic()
        return self.path

    def footer(self) -> str:
        """One line describing what this run reused, for the console.

        Returns:
            A sentence. It names the signature mismatch when there was one, because
            a discarded journal otherwise reads identically to an absent one.

        """
        if self.stale:
            return (
                "the previous run used different settings, so nothing was skipped "
                "and the journal has been restarted"
            )
        if not self.reused:
            return "nothing to resume: no entry matched an unchanged input"
        return f"{self.reused} file(s) skipped: already processed by this driver"

    def announce(self) -> None:
        """Print the mismatch when there is one, and a blank line either way.

        A discarded journal has to be announced: a run that silently ignored its own
        previous result looks identical to a run that had nothing to resume, and the
        reader has no way to tell *the settings changed* from *this is a fresh
        corpus*. Six drivers print this line, so it is stated once.

        """
        if self.stale:
            print("the previous run used different settings: nothing will be skipped")
        print()

    @classmethod
    def begin(
        cls,
        out_root: pathlib.Path,
        driver: str,
        *,
        redo: bool,
        saving: bool = True,
        **settings: object,
    ) -> Resume:
        """Open this run's journal, announce it, and arm the exit flush.

        Three steps that always happen together - a caller that opened a journal and
        forgot to mention it was stale would hide the fact from the operator - so they
        are one call rather than three the six drivers must remember to pair.

        **The `atexit` hook is what makes an interrupt cheap.** Measured: a walk of
        `tests/fixtures/` interrupted with `^C` after 20 images left **no journal at
        all**, because the periodic write had not come due - the finished work was lost
        exactly as it was before this existed. Python runs `atexit` handlers when a
        `KeyboardInterrupt` propagates out, so an operator's Ctrl-C now costs only the
        file in flight. It does **not** run on `SIGKILL`, which is what the periodic
        trigger in `flush_if_due` covers: one mechanism per failure mode, and neither
        replaces the other.

        Args:
            out_root: The output root the run writes into.
            driver: The driver's own name.
            redo: ``True`` when the caller asked for every file again.
            saving: Whether this run writes output - ``--no-save`` passes ``False``,
                and then neither the exit hook nor the periodic write touches disk.
            **settings: Everything that decides what this run's output *means*; see
                `signature_of`.

        Returns:
            The journal, ready to ask `is_done` and to `record` into.

        """
        resume = cls.open(out_root, driver, signature_of(**settings), redo=redo)
        resume.saving = saving
        resume.announce()
        if saving:
            atexit.register(resume.flush_at_exit)
        return resume

    def flush_at_exit(self) -> None:
        """Write the journal as the interpreter leaves, never taking exit with it.

        A failure to write a bookkeeping file must not change the process's exit
        status: the run's own answer is already on stdout, and an exception here would
        replace it with a traceback about the journal.

        """
        with contextlib.suppress(OSError):
            self.flush()


def add_resume_flag(parser: argparse.ArgumentParser) -> None:
    """Declare ``--redo`` on a driver's argument parser.

    One grammar, one owner - the same discipline `commands/pages.py::parse_pages`
    imposes on ``--pages``. Six drivers declare this flag; six copies of its name and
    help text is six places for them to drift apart, and a driver whose spelling
    differed would refuse a flag the others accept.

    Args:
        parser: The driver's parser.

    """
    parser.add_argument(
        "--redo",
        action="store_true",
        help="ignore the resume journal and process every file again",
    )


def batch_parser(
    description: str, default_out: pathlib.Path
) -> argparse.ArgumentParser:
    """Build the parser every batch driver shares: an input root, ``--redo``, ``--out``.

    The three flags are the walk itself rather than any kernel's business, and six
    hand-written copies of them is where an option silently diverges - `--out`
    documented in one driver and absent from another is a defect this repo has
    already paid for once (`kernel-cli.sh`'s `--out`). A driver appends its own
    kernel-specific flags to what this returns.

    Args:
        description: The driver's one-line summary.
        default_out: Where this driver writes when ``--out`` is not given.

    Returns:
        The parser, with the shared arguments already declared.

    """
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("input", type=pathlib.Path, help="the folder to walk")
    add_resume_flag(parser)
    parser.add_argument(
        "--out",
        type=pathlib.Path,
        default=None,
        help=f"the output root (default: {default_out})",
    )
    return parser


def report_mirror(
    problems: Sequence[str], walked: int, directories: int, noun: str
) -> None:
    """Print the mirror check's verdict.

    The mirror is the deliverable of every driver here (`FR-28`, `S3-T06`), so all
    six report it the same way: the count of what was walked, the count of
    directories the tree holds even where they are empty, and one line per
    violation. Stated once because the *wording* is part of the contract - a driver
    that printed its violations without a heading would read as a different check.

    Args:
        problems: What the driver's own verification returned; empty when exact.
        walked: How many files the driver was responsible for.
        directories: How many directories the output holds, the root included.
        noun: What those files are called in this driver's scope - ``"image"``,
            ``"PDF"``, ``"document"`` or ``"file"``.

    """
    print()
    print("=== the mirror")
    if not problems:
        print(
            f" ok {walked} {noun}(s) and {directories} director(ies) mirrored "
            "at the same relative paths"
        )
    for problem in problems:
        print(f" !! {problem}")


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
