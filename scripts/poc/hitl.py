"""The human-in-the-loop review surface: compare, then decide.

`my_kernel_flow.md` §7, made runnable:

> uses `llm.frontier` to take `llm.local`'s output and assess the quality of the
> extraction; because it leans on the same mirrored structure, it can compare the
> `llm.local` `.json`/`.txt` against `llm.frontier`'s for the same file.

This driver does that, and it is built to be honest about **three limits**, each
measured rather than assumed:

**1. `judge` cannot see the image.** §7's sentence says *"junto con la imagen
original"*, but `FrontierEngine.judge(model, rubric, samples, produced_by, schema)`
takes no `images` parameter - its body builds the prompt from the rubric, a sentence
asking for a JSON object, and `json.dumps(samples)`, and calls `self.structured(...)`,
which passes `images=()`. So `judge` grades a **transcript**, not the page. The
image-carrying comparison is `vision`, and this driver runs both so the difference is
a measurement.

**2. The judge cannot be the same model as the producer.** `role_conflict` is
enforced before any request leaves, because retrying until two samples agree
manufactures the contrast the design depends on (`sad.md` §4, §11 row 15).

**2b. The grade has a shape, and one measurement is why it is passed explicitly.**
`judge` used to carry no schema, so the adapter sent `{"type": "object"}` and nothing
in the request said what a grade looks like. Measured against the local runtime, the
model answered by **echoing the samples back**:

    judge(...) -> {"total": "1789830", "cuit": "20-12345678-9"}

That is a valid object, so it parsed and the call reported a **value** - the grade *is*
the thing being graded, and nothing could fail, because all a parser can check is that the
answer is an object. The frontier path failed loudly (`unsupported_format`, 1138 tokens of
prose); this one could not fail at all. `GRADE_SCHEMA` below is the fix, and it is passed
at the call site on purpose: the schema is the caller's, the port carries it, and the
adapter supplies none - an adapter that invented one would be choosing a policy and
naming the domain noun *grade* in a kernel API.

**3. `src/docflow/components/` does not exist.** `Reviewer` is `S2-T15`, so there is
no queue, no `promote`, and no workflow UI. What this driver can do is the
mechanical part: put the two readings side by side, show where they differ, and
write the comparison to a file the mirror makes findable. The human decision is
still a human decision - what it removes is the need to go looking for the files.

Run it against a tree `batch.py` produced:

    python scripts/poc/batch.py tests/fixtures/casos --out var/poc/batch
    python scripts/poc/hitl.py tests/fixtures/casos --out var/poc/batch
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import io
import json
import os
import pathlib
import sys
from typing import Any, Final

import _lib

# `docflow` is only importable once `src/` is on the path.
_lib.bootstrap()

import batch as batch_driver  # noqa: E402 - see above
import llm_frontier as frontier_driver  # noqa: E402 - see above
import llm_local  # noqa: E402 - see above

from docflow.adapters.frontier import FrontierEngine  # noqa: E402 - see above

__all__: list[str] = []

#: The model in the **governor** role. It must not be the one that produced the
#: samples, or `judge` refuses with `role_conflict`.
GOVERNOR_MODEL: Final[str] = "anthropic:claude-sonnet-4-6"

#: The model that produced the samples, named for the conflict check. It is K5's
#: text model, because that is what `batch.py` extracts with.
PRODUCER_MODEL: Final[str] = f"ollama:{llm_local.TEXT_MODEL}"

#: The grading criteria. It asks for a per-field judgement rather than a score,
#: because an aggregate confidence is exactly what this project refuses: a number
#: that mixes *not checked* with *checked and matching* (`sad.md` §9).
RUBRIC: Final[str] = (
    "You are given an extraction proposed by a local model, as a JSON object. "
    "For each field, state whether the proposed value is plausible for the field's "
    "type and name, and name any field that appears malformed, empty, or invented. "
    "Do not assign an overall score. Report per field."
)

#: The shape a grade must have. **It is passed at the call site on purpose**, and it is
#: imported rather than redeclared: `llm_frontier` already had this schema, two identical
#: copies would drift, and a drifted copy is the failure this repo names repeatedly. The
#: name is re-exported so a reader of this file sees what the call above sends.
#: Measured before the port carried a schema: with no shape in the request, the local
#: runtime echoed the samples back, the echo parsed as an object, and the call reported a
#: *value*. The per-field judgement is also `sad.md` §9's rule - never one aggregate score.
GRADE_SCHEMA: Final[dict[str, object]] = dict(frontier_driver.GRADE_SCHEMA)

#: The name the comparison is written under, beside the document in the mirror.
COMPARISON_NAME: Final[str] = "review.json"

#: The suffix the batch walk uses for a file it considered and deliberately did not
#: process. It is **not** an extraction, and pairing it with one would be reading a
#: skip record as an empty answer - which is the collapse this project refuses.
SKIP_SUFFIX: Final[str] = ".skipped.json"


@dataclasses.dataclass(frozen=True, slots=True)
class Reading:
    """One extracted `.json` found in the mirrored tree.

    Attributes:
        relative: The `.json`'s path relative to the output root.
        fields: What it holds, or ``None`` when it could not be read.

    """

    relative: str
    fields: dict[str, Any] | None


def find_extractions(out_root: pathlib.Path) -> list[Reading]:
    """Collect every extracted `.json` under the output root.

    The mirrored tree is what makes this a two-line walk instead of a join: the
    comparison is keyed by the document's own relative path, which is the property
    `FR-28` exists to provide.

    Args:
        out_root: The root `batch.py` wrote.

    Returns:
        The readings, sorted by relative path.

    """
    readings: list[Reading] = []
    for path in sorted(out_root.rglob("*.json")):
        if path.name in {COMPARISON_NAME, "job.json"}:
            continue
        if path.name.endswith(SKIP_SUFFIX):
            continue
        relative = path.relative_to(out_root).as_posix()
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            readings.append(Reading(relative, None))
            print(f" !! {relative}: unreadable ({type(exc).__name__})")
            continue
        if isinstance(loaded, dict):
            readings.append(Reading(relative, loaded))
    return readings


def compare_trees(out_root: pathlib.Path) -> list[tuple[str, str]]:
    """Report documents that produced text but no fields, and the reverse.

    This is the arithmetic half of §7 and it needs no model: a `.txt` with no
    sibling `.json` is a document whose extraction was refused, and a `.json` with
    no sibling `.txt` is not something `batch.py` can produce. Reported rather than
    inferred, so a missing file is never read as an empty extraction.

    Args:
        out_root: The root to inspect.

    Returns:
        One ``(relative, message)`` pair per asymmetry.

    """
    problems: list[tuple[str, str]] = []
    for text in sorted(out_root.rglob("*.txt")):
        stem = text.with_suffix("")
        if not stem.with_suffix(".json").is_file():
            relative = text.relative_to(out_root).as_posix()
            problems.append((relative, "text without fields"))
    return problems


def _silently(call: Any, *args: Any, **kwargs: Any) -> Any:
    """Call a driver method with its console output suppressed.

    Args:
        call: The driver method to call.
        *args: Its positional arguments.
        **kwargs: Its keyword arguments.

    Returns:
        Whatever the method returned.

    """
    sink = io.StringIO()
    with contextlib.redirect_stdout(sink):
        return call(*args, **kwargs)


def request_vision_read(
    engine: FrontierEngine, image: pathlib.Path, proposed: dict[str, Any]
) -> tuple[dict[str, Any] | None, str]:
    """Ask the frontier model to read the same page, **with the image attached**.

    This is the call §7's sentence actually describes, and it is `vision` rather
    than `judge`: only `vision` carries `images`. The local model's proposal goes
    into the prompt, so the frontier model has both the pixels and the proposal -
    which is what makes the comparison a comparison and not two independent reads.

    Args:
        engine: The K6 adapter.
        image: The page to read.
        proposed: What `llm.local` extracted.

    Returns:
        The frontier model's own fields, and a note when it refused.

    """
    from docflow.kernels.types import Bytes

    suffix = image.suffix.lower().lstrip(".")
    media = "image/jpeg" if suffix in {"jpg", "jpeg"} else f"image/{suffix}"
    attempt = _silently(
        engine.vision,
        GOVERNOR_MODEL,
        (
            "Read this document and return its fields as JSON. A local model "
            "proposed the object below. Report what the image itself supports.\n\n"
            f"Proposal: {json.dumps(proposed, ensure_ascii=False)}"
        ),
        [Bytes(data=image.read_bytes(), media_type=media)],
        {"type": "object"},
    )
    if attempt.value is None:
        code = attempt.reason.code if attempt.reason else "unknown"
        return None, f"vision refused: {code}"
    return dict(attempt.value), ""


def request_judgement(
    engine: FrontierEngine, proposed: dict[str, Any]
) -> tuple[dict[str, Any] | None, str]:
    """Ask the frontier model to grade the proposal against a rubric.

    **Without the image**, because `judge` cannot carry one. This is the limitation
    stated at the top of this module, and running it makes the limitation visible in
    the output rather than leaving it in a docstring.

    Args:
        engine: The K6 adapter.
        proposed: What `llm.local` extracted.

    Returns:
        The grades, and a note when it refused.

    """
    attempt = _silently(
        engine.judge,
        GOVERNOR_MODEL,
        RUBRIC,
        [proposed],
        PRODUCER_MODEL,
        GRADE_SCHEMA,
    )
    if attempt.value is None:
        code = attempt.reason.code if attempt.reason else "unknown"
        return None, f"judge refused: {code}"
    return dict(attempt.value), ""


def divergences(
    proposed: dict[str, Any], authoritative: dict[str, Any] | None
) -> tuple[list[str], str]:
    """List the fields where two readings disagree, and say if none was obtained.

    **Contrast is the only detector of the right-value-in-the-wrong-place class**
    (`prd.md` §2), so this is the part of §7 that carries real weight: a field one
    reading produced and the other did not, or produced differently, is the signal a
    human should look at. The rest of the document is not worth a person's time.

    A **missing** second reading is returned separately from a disagreement. They
    are different statements: *the two readings differ* is a finding about the
    document, while *nobody read it twice* is an absence of evidence - and counting
    the second as the first would make an uncalled check look like a detected
    problem.

    Args:
        proposed: The local model's reading.
        authoritative: The frontier model's reading, or ``None`` when it refused.

    Returns:
        The disagreements, and a note when there was nothing to contrast.

    """
    if authoritative is None:
        return [], "no second reading was obtained, so nothing was contrasted"

    found: list[str] = []
    for key in sorted(set(proposed) | set(authoritative)):
        mine = proposed.get(key)
        theirs = authoritative.get(key)
        if key not in proposed:
            found.append(f"{key}: missing locally, frontier read {theirs!r}")
        elif key not in authoritative:
            found.append(f"{key}: local read {mine!r}, frontier did not report it")
        elif mine != theirs:
            found.append(f"{key}: local {mine!r} vs frontier {theirs!r}")
    return found, ""


def review_one(
    engine: FrontierEngine,
    reading: Reading,
    out_root: pathlib.Path,
    image: pathlib.Path | None,
) -> None:
    """Compare one document's extraction and write the comparison beside it.

    Args:
        engine: The K6 adapter.
        reading: The extraction to review.
        out_root: The output root.
        image: The page to attach, when the mirror has one.

    """
    assert reading.fields is not None, "the caller filtered the unreadable ones"

    vision_fields, vision_note = (None, "no page available to attach")
    if image is not None:
        vision_fields, vision_note = request_vision_read(engine, image, reading.fields)

    grades, judge_note = request_judgement(engine, reading.fields)

    differences, contrast_note = divergences(reading.fields, vision_fields)

    record = {
        "document": reading.relative,
        "local": reading.fields,
        "frontier_vision": vision_fields,
        "frontier_judge": grades,
        "divergences": differences,
        "contrast": contrast_note or "contrasted",
        "notes": {
            "vision": vision_note,
            "judge": judge_note,
            "judge_carries_no_image": (
                "judge grades the transcript only: its signature has no `images` "
                "parameter and it calls structured(images=()), so the comparison "
                "that sees the page is `vision`."
            ),
        },
    }

    target = out_root / pathlib.Path(reading.relative).parent / COMPARISON_NAME
    target.write_text(
        json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    if contrast_note:
        state = f"NOT CONTRASTED ({contrast_note})"
    elif differences:
        state = f"{len(differences)} divergence(s)"
    else:
        state = "agree"

    print(f" .. {reading.relative:52} {state}")
    for line in differences:
        print(f"      - {line}")
    print(f"      vision: {vision_note or 'ok'}   judge: {judge_note or 'ok'}")


def _page_for(reading: Reading, root: pathlib.Path) -> pathlib.Path | None:
    """Find the page the comparison should attach, if one is available.

    The mirror holds the *extraction*, never the page: a `.json` is the answer, and
    the document it came from lives in the **input** tree. So this looks at the
    source path, which is exactly what the mirrored relative path makes possible -
    the property `FR-28` exists to provide.

    Args:
        reading: The extraction being reviewed.
        root: The **input** root, where the source documents live.

    Returns:
        An image path, or ``None`` when no page is available.

    """
    stem = pathlib.Path(reading.relative)
    for suffix in sorted(batch_driver.IMAGE_SUFFIXES):
        candidate = root / stem.parent / f"{stem.stem}{suffix}"
        if candidate.is_file():
            return candidate
    return None


def main(argv: list[str] | None = None) -> int:
    """Compare every extraction in a mirrored tree and write the comparisons.

    Args:
        argv: The command-line arguments, or ``None`` for ``sys.argv``.

    Returns:
        The number of documents that diverged, plus the arithmetic asymmetries.

    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("input", type=pathlib.Path, help="the folder that was walked")
    parser.add_argument(
        "--out",
        type=pathlib.Path,
        default=None,
        help="the output root `batch.py` wrote (default: var/poc/batch)",
    )
    args = parser.parse_args(argv)

    root: pathlib.Path = args.input
    out_root = args.out if args.out is not None else _lib.DEFAULT_OUT / "batch"
    if not out_root.is_dir():
        parser.error(f"{out_root} does not exist; run batch.py first")

    _lib.set_out(out_root)
    _lib.reset()

    print(f"in  = {root}")
    print(f"out = {out_root}")
    print(f"governor = {GOVERNOR_MODEL}   producer = {PRODUCER_MODEL}")
    if not os.environ.get("DOCFLOW_FRONTIER_KEY"):
        print()
        print(
            "DOCFLOW_FRONTIER_KEY is unset, so every comparison below will report\n"
            "a refusal. The mechanical half - finding the files, pairing them, and\n"
            "writing where a human should look - still runs, and that is the half\n"
            "that exists today (`Reviewer` is `S2-T15`, not yet written)."
        )
    print()

    readings = find_extractions(out_root)
    if not readings:
        print("no extractions found; run batch.py first")
        return 0

    engine = FrontierEngine()
    for reading in readings:
        if reading.fields is None:
            continue
        review_one(engine, reading, out_root, _page_for(reading, root))

    print()
    asymmetries = compare_trees(out_root)
    if asymmetries:
        print("documents with text but no fields:")
        for relative, message in asymmetries:
            print(f"  {relative}: {message}")
    else:
        print("every .txt in the tree has a sibling .json")

    print()
    print(f"{'documents':<12}{len(readings):>6}")
    print(f"{'compared':<12}{sum(1 for r in readings if r.fields is not None):>6}")
    print()

    if not asymmetries:
        print("the review files are written; the decision is still a human's.")
        return 0
    return len(asymmetries)


if __name__ == "__main__":
    sys.exit(main())
