"""The frontier batch: a folder of documents and local extractions in, assessments out.

`my_kernel_flow.md` §5, applied to a folder:

> send the appropriate image with **higher-level** prompts, to extract fields;
> optionally, send the `llm.local` result **together with** the original image, so it
> can assess how effective that extraction was.

This is the **contrast** step, and the project's central claim rests on it: two
independent reads that disagree are the only detector of a silent error, and a single
confident answer is not evidence of correctness (`prd.md`, `sad.md` §4). `batch.py`
runs one read and writes fields; `batch_llm_local.py` runs another and writes fields
too; this driver puts the two side by side and asks a **different model** to say
whether the second one is supported by the pixels.

Why a driver of its own
-----------------------

Because contrast is a **comparison between two runs**, and there is nowhere else for
it to happen. `batch.py` produces one read and cannot disagree with itself.
`batch_llm_local.py` produces the other and has no image to check it against.
`hitl.py` contrasts what is *on disk* - it pairs files and reports differences - but
it cannot ask a model to adjudicate them, because that costs a frontier request per
document and a batch is the only shape in which that is affordable or auditable.

**This is not K1.** Like `batch.py`, it composes the adapter for one walk of a folder:
no ledger, no cache key, no `pause`/`resume`. Re-running re-pays for every request.

Why this driver works without a credential, and what it can still do
--------------------------------------------------------------------

This workspace has no `DOCFLOW_FRONTIER_KEY`, so **every request refuses**. That is
not a reason for the driver not to exist, and it is not a reason for it to print
nothing:

- the **pairing** it does - a document, its image, and the fields `llm.local`
  produced for it - is mechanical and needs no provider;
- the **gate chain** is reported per document, so a run says *which* setting is
  missing and *where* it stops, which is the difference between *"the frontier circuit
  is broken"* and *"the frontier circuit is unmeasured"*;
- `role_conflict` is enforced, which is what makes *"retrying to obtain agreement is
  forbidden"* mechanical rather than prose.

So a credential-less run is a **dry run with a real report**: it names every document
it would have assessed, and the one reason none of them were. Export a key and
re-run - nothing else changes.

The two modes, and why `judge` cannot see the image
---------------------------------------------------

| Mode | Operation | What it reads | What it answers |
|---|---|---|---|
| `judge` (default) | `judge` | `llm.local`'s fields | is that extraction supported? |
| `vision` | `vision` | the image | the fields, read at a higher level |

**`judge` never receives the image, and that is measured rather than assumed.**
Introspecting the adapter: `inspect.signature(FrontierEngine.judge)` is
`(model, rubric, samples, produced_by, schema)` - there is **no `images` parameter**,
the body does not contain the name `images`, and it calls `self.structured(...)`,
which takes no images either. So `judge` grades a **transcript**.

The flow's *"junto con la imagen original"* is therefore satisfied by **`vision`**,
which does take `Sequence[Bytes]` and reads pixels. This driver runs `judge` by
default because the flow's sentence is about assessing a previous extraction, and it
records the limitation instead of presenting `judge` as something it is not.
`llm_frontier.py` reports the same finding, and `hitl.py` runs both for the same
reason. A caller who needs the pixels in the comparison wants `--mode vision`.

What this driver reads from disk, and what it will not invent
-------------------------------------------------------------

The fields to assess are **read from a previous run**, not recomputed: recomputing them
would be a third read, and comparing three reads is a different experiment. They come
from `batch_llm_local.py`'s `<stem>.fields.json`, whose `value` key is exactly what
`llm.local` answered. A document with no such file is reported as **not contrasted** -
*"nobody extracted it"* is an absence of evidence, and counting it as a disagreement
would make an uncalled check look like a detected problem (the same distinction
`hitl.py` draws).

The image is looked up in the **input** tree by the relative path the fields file
records, so the mirror does not have to hold a copy of every page.

Run it:

    python scripts/poc/batch_llm_frontier.py <documents-dir> --fields <local-out-dir> \\
        [--out DIR] [--model PROVIDER:MODEL] [--mode judge|vision]

Examples:

    python scripts/poc/batch_llm_frontier.py /tmp/pages --fields /tmp/llm-local-out
    python scripts/poc/batch_llm_frontier.py /tmp/pages --fields /tmp/out --mode vision

To measure for real, export a key and re-run:

    DOCFLOW_FRONTIER_KEY=... DOCFLOW_FRONTIER_MAX_TOKENS=1024 \\
        python scripts/poc/batch_llm_frontier.py /tmp/pages --fields /tmp/out
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import pathlib
import sys
from collections.abc import Mapping

import _lib
import _mirror

# The ordering is load-bearing, exactly as in every other driver here: `_lib` puts
# `src/` on `sys.path`, and `llm_frontier` is imported so this module reuses its
# helpers instead of re-implementing them. `pyproject.toml`'s `pythonpath = ["src"]`
# applies to pytest alone.
_lib.bootstrap()

import llm_frontier as frontier_driver  # noqa: E402 - see the note above
import llm_local  # noqa: E402 - see the note above

from docflow.adapters.frontier import FrontierEngine  # noqa: E402 - see the note above
from docflow.kernels.types import Bytes  # noqa: E402 - see the note above

__all__: list[str] = []

#: The suffix `batch_llm_local.py` writes. Named here rather than guessed, because
#: this driver's whole input is a previous run's output.
FIELDS_SUFFIX: str = ".fields.json"

#: The rubric for the contrast. It asks for a **per-field** verdict rather than a
#: score, because a single confidence number standing in for a per-field verdict is
#: the aggregate the project forbids (`sad.md` §6) - and because a grader told to
#: answer *supported / not supported / missed* cannot hide behind "mostly correct".
RUBRIC: str = (
    "You are given a proposed extraction and nothing else. For each field, say "
    "whether the value is plausible for this kind of document and name any field the "
    "proposal omitted. Do not invent values. Do not give an overall score."
)

#: The prompt for `vision` mode - higher level than K5's, which is the difference §5
#: draws. It names the *shape* of the answer and forbids inference.
VISION_PROMPT: str = (
    "Read this document and return the fields described by the schema. Report only "
    "what the pixels support; do not infer a value you cannot see."
)

#: The `produced_by` passed to `judge` when the fields came from K5. It is the local
#: model's identity, and it is what makes `role_conflict` mechanical: grading samples
#: a *different* model produced is the point of contrast. **Derived from `llm_local`
#: and never spelled out here.** It was a literal `"ollama:smollm2"` while that was
#: the default, which is a second copy of a fact that lives in one place - and this
#: one is load-bearing: a stale name makes the guard compare against the wrong model,
#: so `role_conflict` would stop firing and the prohibition would silently become
#: prose. `hitl.py` derives the same value the same way.
PRODUCER: str = f"ollama:{llm_local.TEXT_MODEL}"


@dataclasses.dataclass(frozen=True, slots=True)
class Assessment:
    """What one document's contrast produced.

    Attributes:
        source: The document's path relative to the input root.
        fields: The local extraction that was assessed, or ``None`` when no previous
            run produced one - which is reported as *not contrasted* rather than as a
            disagreement.
        fields_origin: Where that extraction was read from, relative to the fields
            root, or ``None``.
        verdict: The frontier model's assessment, or ``None`` when the call refused.
        reason: The reason code when the call refused.
        artifact: The written assessment, relative to the output root, or ``None``.
        note: A short explanation, for the cases with no assessment.

    """

    source: str
    fields: Mapping[str, object] | None
    fields_origin: str | None
    verdict: Mapping[str, object] | None
    reason: str
    artifact: str | None
    note: str = ""

    @property
    def contrasted(self) -> bool:
        """Whether a second reading was actually obtained.

        Returns:
            ``True`` when the frontier model answered. A refusal is **not** a
            contrast: nothing compared the two readings, so nothing was learned
            about the document.

        """
        return self.verdict is not None


#: Every assessment of this walk, in order.
OUTCOMES: list[Assessment] = []


def _engine() -> FrontierEngine:
    """Build the K6 adapter.

    Returns:
        The engine, ready to call.

    """
    return frontier_driver._engine()


def gates() -> bool:
    """Report whether a frontier request can be attempted at all.

    Returns:
        ``True`` when every gating variable is set. `HOST` has a documented default
        address and is reported without gating, which is the same reading
        `llm_frontier.py` makes.

    """
    ready = True
    print("the gate chain, in the order the adapter reads it:")
    for name in frontier_driver.GATES:
        present = bool(os.environ.get(name))
        note = "" if present or name.endswith("HOST") else "  <- blocks every call"
        print(f"  {name:30} {'set' if present else 'unset'}{note}")
        if not present and not name.endswith("HOST"):
            ready = False
    if not ready:
        print(
            "\nevery request below will refuse with `provider_unavailable`. The run\n"
            "is still a dry run with a real report: it says which documents it would\n"
            "have assessed, and the one reason it assessed none.\n"
        )
    return ready


def find_fields(
    fields_root: pathlib.Path, relative: pathlib.Path
) -> tuple[Mapping[str, object] | None, str | None]:
    """Read the local extraction a previous run wrote for a document.

    The fields are **read, never recomputed**: recomputing them would be a third read,
    and comparing three reads is a different experiment from the one §5 asks for.

    Args:
        fields_root: The output root `batch_llm_local.py` wrote.
        relative: The document's path relative to the input root.

    Returns:
        The `value` the local model answered and where it was read from, or ``None``
        and ``None`` when no run produced one - an absence of evidence, which the
        caller must not report as a disagreement.

    """
    target = fields_root / relative.parent / f"{relative.stem}{FIELDS_SUFFIX}"
    if not target.is_file():
        return None, None

    try:
        record = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        # A corrupt record is not an extraction. Reported as absent rather than
        # raised, because one bad file must not stop a walk over a corpus.
        return None, None

    value = record.get("value")
    if not isinstance(value, Mapping):
        return None, None
    return value, target.relative_to(fields_root).as_posix()


def image_for(root: pathlib.Path, relative: pathlib.Path) -> pathlib.Path | None:
    """Find the image a document's fields were extracted from.

    Looked up in the **input** tree by the relative path, so the mirror does not have
    to carry a copy of every page. A PDF has no image of its own at this stage - its
    page would be the render `batch_pdf.py` writes - so only a file the image kind
    recognises is returned.

    Args:
        root: The input root.
        relative: The document's path relative to it.

    Returns:
        The image path, or ``None`` when the input is not an image this driver can
        send.

    """
    candidate = root / relative
    if _mirror.kind_of(candidate) == "image":
        return candidate
    return None


def assess(
    engine: FrontierEngine,
    model: str,
    fields: Mapping[str, object],
    image: pathlib.Path | None,
    *,
    mode: str,
    schema: Mapping[str, object],
) -> _lib.Attempt:
    """Ask the frontier model about one document.

    Args:
        engine: The K6 adapter.
        model: The model as the caller names it.
        fields: What `llm.local` answered for this document.
        image: The document's image, or ``None`` when the input has none.
        mode: ``"judge"`` or ``"vision"``.
        schema: The schema, for `vision` mode.

    Returns:
        The attempt, carrying the assessment or the refusal.

    """
    if mode == "vision":
        images = (
            []
            if image is None
            else [Bytes(data=image.read_bytes(), media_type=_media_type(image))]
        )
        return _mirror.silently(
            frontier_driver.extract_from_image,
            engine,
            model,
            "ok",
            VISION_PROMPT,
            schema,
            images,
        )
    return _mirror.silently(
        frontier_driver.judge_local,
        engine,
        model,
        "ok",
        [fields],
        PRODUCER,
        RUBRIC,
        # The shape travels with the rubric: this driver's rubric asks whether each
        # value is plausible for the document type, and the schema it is paired with
        # asks for exactly that per field. Passing the rubric and letting the shape
        # default would be asking one question and constraining another.
        frontier_driver.GRADE_SCHEMA,
    )


def _media_type(path: pathlib.Path) -> str:
    """Report an image's media type from its suffix.

    Args:
        path: The image path.

    Returns:
        The media type.

    """
    suffix = path.suffix.lower().lstrip(".")
    return "image/jpeg" if suffix in {"jpg", "jpeg"} else f"image/{suffix}"


def process_document(
    engine: FrontierEngine,
    source: pathlib.Path,
    root: pathlib.Path,
    fields_root: pathlib.Path,
    out_root: pathlib.Path,
    schema: Mapping[str, object],
    model: str,
    *,
    mode: str,
    save: bool,
) -> Assessment:
    """Pair one document with its local extraction and ask for an assessment.

    Args:
        engine: The K6 adapter.
        source: The document to assess.
        root: The input root.
        fields_root: The output root `batch_llm_local.py` wrote.
        out_root: This run's output root.
        schema: The schema, for `vision` mode.
        model: The model as the caller names it.
        mode: ``"judge"`` or ``"vision"``.
        save: Whether to write the assessment.

    Returns:
        What the contrast produced.

    """
    relative = pathlib.Path(_mirror.relative_to(source, root))
    mirror_dir = out_root / relative.parent
    mirror_dir.mkdir(parents=True, exist_ok=True)

    fields, origin = find_fields(fields_root, relative)
    if mode == "judge" and fields is None:
        # *Nobody extracted it* is an absence of evidence, not a disagreement. It is
        # the same distinction `hitl.py` draws, and counting it as a finding would
        # make an uncalled check look like a detected problem.
        note = f"not contrasted: no {FIELDS_SUFFIX} for it under {fields_root}"
        if save:
            # A record, not silence. Without it the mirrored tree holds nothing for
            # this document and `verify_mirror_for` reports *no output for it* - which
            # blames the walk for a file it looked at and correctly declined to
            # assess. Measured: the first dry run produced nine such violations.
            _mirror.write_skipped(mirror_dir, source.stem, "frontier", note)
        return Assessment(
            source=_mirror.relative_to(source, root),
            fields=None,
            fields_origin=None,
            verdict=None,
            reason="",
            artifact=None,
            note=note,
        )

    attempt = assess(
        engine,
        model,
        fields if fields is not None else {},
        image_for(root, relative),
        mode=mode,
        schema=schema,
    )

    verdict = attempt.result.value if attempt.succeeded else None
    reason = ""
    if not attempt.succeeded and attempt.result is not None:
        underlying = attempt.result.reason
        reason = underlying.code if underlying is not None else "refused"

    assessment = Assessment(
        source=_mirror.relative_to(source, root),
        fields=fields,
        fields_origin=origin,
        verdict=verdict,
        reason=reason,
        artifact=None,
    )
    if save:
        if verdict is None:
            # Paired but not assessed - a refusal. Recorded for the same reason the
            # uncontrasted case is: an empty slot in the mirror reads as *never seen*.
            _mirror.write_skipped(
                mirror_dir,
                source.stem,
                "frontier",
                f"not assessed: reason={reason or 'refused'}",
            )
        else:
            assessment = _write_assessment(
                assessment, mirror_dir, source.stem, out_root
            )
    return assessment


def _write_assessment(
    assessment: Assessment, mirror_dir: pathlib.Path, stem: str, out_root: pathlib.Path
) -> Assessment:
    """Write the contrast beside the document, at the mirrored path.

    Both readings travel together with the model that produced the second one: a
    verdict with no record of what it judged, or of which model judged, is a claim
    nobody can check - and the project's whole thesis is that an unchecked claim is
    the failure mode.

    The model's own value is re-wrapped in `dict()` before serialising, because
    `LlmEngine` answers with a `MappingProxyType` (`kernels/types.py`'s recorded PoC
    property: not JSON-encodable by default). `batch_llm_local.py` documents the same
    conversion and for the same reason.

    Args:
        assessment: What the contrast produced.
        mirror_dir: The directory the document mirrors into.
        stem: The document's stem.
        out_root: The output root, for reporting relative paths.

    Returns:
        The assessment, with its artifact filled in.

    """
    record = {
        "source": assessment.source,
        "local_fields": dict(assessment.fields)
        if assessment.fields is not None
        else None,
        "local_fields_origin": assessment.fields_origin,
        "assessment": dict(assessment.verdict)
        if assessment.verdict is not None
        else None,
        "reason": assessment.reason,
        "note": assessment.note,
    }
    target = mirror_dir / f"{stem}.frontier.json"
    target.write_text(
        json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return dataclasses.replace(
        assessment, artifact=_mirror.relative_to(target, out_root)
    )


def main(argv: list[str] | None = None) -> int:
    """Walk a folder, contrast every document, and verify the mirror.

    Args:
        argv: The command-line arguments, or ``None`` for `sys.argv`.

    Returns:
        The number of problems: mirrored-ness violations, plus the documents that
        were **not contrasted** because nothing compared them - a refusal or a
        missing local extraction. A run that assessed nothing is not a clean run, and
        reporting it as one is how a dry run gets mistaken for a verified corpus.

    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("input", type=pathlib.Path, help="the folder that was walked")
    parser.add_argument(
        "--fields",
        type=pathlib.Path,
        required=True,
        help="the output root `batch_llm_local.py` wrote (required)",
    )
    parser.add_argument(
        "--out",
        type=pathlib.Path,
        default=None,
        help="the output root (default: var/poc/batch_llm_frontier)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help=f"the model as the provider names it (default: {frontier_driver.MODEL!r})",
    )
    parser.add_argument(
        "--schema",
        type=pathlib.Path,
        default=None,
        help="the JSON schema for the vision mode's answer (default: the driver's fixture)",
    )
    parser.add_argument(
        "--mode",
        choices=("judge", "vision"),
        default="judge",
        help="which §5 requirement to run (default: judge)",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="contrast every document without writing the assessment",
    )
    args = parser.parse_args(argv)

    root: pathlib.Path = args.input
    if not root.is_dir():
        parser.error(f"{root} is not a directory")
    if not args.fields.is_dir():
        parser.error(
            f"{args.fields} is not a directory; it is the output root "
            "batch_llm_local.py wrote, and this driver assesses that run"
        )

    schema: Mapping[str, object] = (
        frontier_driver.FIELD_SCHEMA
        if args.schema is None
        else json.loads(args.schema.read_text(encoding="utf-8"))
    )
    model = frontier_driver.MODEL if args.model is None else str(args.model)

    out_root = (
        args.out if args.out is not None else _lib.DEFAULT_OUT / "batch_llm_frontier"
    )
    save = not args.no_save
    _lib.set_out(out_root)
    _lib.reset()

    directories = _mirror.mirror_directories(root, out_root)
    engine = _engine()
    ready = gates()

    print(f"in  = {root}")
    print(f"fields = {args.fields}")
    print(f"out = {out_root}")
    print(f"mode = {args.mode}    model = {model}    save = {save}")
    print()

    files = [path for path in _mirror.walk(root) if _mirror.kind_of(path) != "invalid"]
    for source in files:
        assessment = process_document(
            engine,
            source,
            root,
            args.fields,
            out_root,
            schema,
            model,
            mode=args.mode,
            save=save,
        )
        OUTCOMES.append(assessment)

        if assessment.note.startswith("not contrasted"):
            print(f" .. {assessment.source:44} {assessment.note}")
        elif assessment.contrasted:
            keys = ", ".join(sorted(map(str, assessment.verdict or {})))[:40]
            print(f" ok {assessment.source:44} assessed -> {keys}")
        else:
            print(
                f" -- {assessment.source:44} no assessment (reason={assessment.reason})"
            )

    print()
    print("=== the mirror")
    problems = _mirror.verify_mirror_for(root, out_root, files)
    if not problems:
        print(
            f" ok {len(files)} document(s) and {directories} director(ies) mirrored "
            "at the same relative paths"
        )
    for problem in problems:
        print(f" !! {problem}")

    print()
    contrasted = [item for item in OUTCOMES if item.contrasted]
    missing = [item for item in OUTCOMES if item.note.startswith("not contrasted")]
    refused = [
        item
        for item in OUTCOMES
        if not item.contrasted and not item.note.startswith("not contrasted")
    ]

    print(f"{'documents':<14}{len(files):>6}")
    print(f"{'contrasted':<14}{len(contrasted):>6}")
    print(f"{'no fields':<14}{len(missing):>6}")
    print(f"{'no assessment':<14}{len(refused):>6}")
    print()

    if missing:
        print(
            f"{len(missing)} document(s) had no local extraction to contrast, so "
            "nothing was compared about them."
        )
    if refused:
        codes = sorted({item.reason for item in refused if item.reason})
        print(
            f"{len(refused)} document(s) were paired but not assessed "
            f"({', '.join(codes) or 'refused'})."
        )
    if not ready:
        print(
            "No credential: this was a dry run. The pairing above is real, the\n"
            "assessments are not, and nothing about the corpus has been verified."
        )
    if not problems and not contrasted:
        return len(problems) + len(missing) + len(refused)
    if not problems and not missing and not refused:
        print("every document was contrasted and the tree mirrors exactly.")
        return 0
    return len(problems) + len(missing) + len(refused)


if __name__ == "__main__":
    sys.exit(main())
