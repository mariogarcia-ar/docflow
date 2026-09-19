"""The field-extraction batch: a folder of extracted text in, structured fields out.

`my_kernel_flow.md` §4, applied to a folder:

> models **without** vision: send the text the OCR produced, plus a prompt, to
> extract fields; models **with** vision: send the appropriate image, plus a prompt,
> so the model reads the field values off the pixels.

This is the last step of §6's chain and the first one that **costs a generation per
document**. `batch_ocr.py` and `batch_pdf.py` produce the material this reads: a
`.txt` per document, at a mirrored path. Pointed at one of their output trees, this
driver turns that text into fields.

Why a driver of its own
-----------------------

The field extraction is the step whose answer depends on a **model** rather than on
the corpus, so it is the one worth re-running against a different model, a different
prompt or a different schema - and each of those is an argument to this driver rather
than an edit to a pipeline. It is also the step where a silent failure costs the most:
a generation that was cut, or a prompt that did not fit the window, returns a
plausible object that a consumer cannot tell from a good one.

**This is not K1.** Like `batch.py`, it composes the adapter for one walk of a
folder: no ledger, no cache key, no `pause`/`resume`. Re-running re-does every
generation.

Two modes, because §4 names two requirements
--------------------------------------------

| Mode | Operation | Input | Output at the mirrored path |
|---|---|---|---|
| `structured` (default) | `structured` | a text file | `<stem>.fields.json` |
| `vision` | `vision` | an image | `<stem>.fields.json` |

`vision` sends the **pixels**, so it is the branch for a scan whose OCR text is
untrustworthy - and it must be given `Bytes`, never a path. The encoder accepts a
`Path` and silently base64-encodes the **file name**, which `llm_local.py` measures;
this driver reads the bytes itself, so that mistake is not expressible from here.

The schema and the prompt are the caller's, and there is no default
-----------------------------------------------------------------

Both are required. `my_kernel_flow.md` §4's `p` (prompt) mode is *"the fields I want,
described"*, and a bench's own invoice fixture is not a description of the caller's
documents: defaulting to it would answer a question about a fixture while reporting
on a real document. The schema also goes to the runtime's `format` field, so it
constrains generation rather than merely describing an expectation.

The failure this driver exists to make visible
----------------------------------------------

The runtime **cuts a prompt that does not fit its window and reports nothing**: the
answer arrives with `done_reason: 'stop'` and a plausible value. Measured on
`smollm2` at `num_ctx=4096`: prompts of 34 000, 128 020, 144 020 and 153 000
characters all evaluate exactly **2 050** tokens - and the last two are repetitive
text and random noise, byte-for-byte unrelated, so the number is the window's edge
and not tokenization.

The mechanism is the window's **two halves**, and it is visible in the call's own
evidence: the prompt's share of `num_ctx` is about half (2 048 of 4 096), and
`prompt + completion` lands at ~2 078 - just inside. So a document whose text is long
is answered **from its beginning**, and the only thing that says so is that
`evaluated_tokens` reached the prompt's share while `done_reason` stayed `'stop'`.

That test is per call, which is what makes it worth having: two runs of this driver
detected nothing, one because it looked for a typed refusal (`truncated_output` fires
on `done_reason: 'length'`, which a dropped prompt never produces) and one because it
compared files against each other and a single cut file has no peer to be equal to.

`PROMPT_WINDOW_SHARE` is a **reporting basis, not a policy value**. It names which
files were answered from a truncated prompt and never changes how one is processed;
`ADR-009` governs corpus thresholds and this is not one. At the boundary it cannot
separate *exactly filled its share* from *cut*, and it reports both - a false alarm
on a prompt that fitted exactly is recoverable, a silent cut is not.

What this driver does **not** count
-----------------------------------

The input tokens that arrive from a text file are invisible to it: the file is read
here and passed to the runtime, which is the only layer that tokenises. Ollama's
public API does not expose a tokenizer endpoint, so the adapter can only record the
*output* side (`completion_tokens`) and what the runtime evaluated. Any figure this
driver reported for a document's own length would be a threshold wearing a
measurement's clothes.

TODO: [MVP] A caller that needs to know whether a document will fit the window before
spending a generation must tokenise it - a real dependency, not a constant. Recorded
rather than approximated.

Run it:

    python scripts/poc/batch_llm_local.py <input-dir> --schema FIELDS.json \\
        [--out DIR] [--prompt TEMPLATE] [--model TAG] [--mode structured|vision]

Examples:

    python scripts/poc/batch_llm_local.py var/poc/batch_ocr --schema registry/fields.json
    python scripts/poc/batch_llm_local.py /tmp/pages --mode vision --schema s.json
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import sys
from collections.abc import Mapping

import _lib
import _mirror

# The ordering is load-bearing, exactly as in every other driver here: `_lib` puts
# `src/` on `sys.path`, and `llm_local` is imported so this module reuses its helpers
# instead of re-implementing them. `pyproject.toml`'s `pythonpath = ["src"]` applies
# to pytest alone.
_lib.bootstrap()

import llm_local as llm_driver  # noqa: E402 - see the note above

from docflow.adapters.ollama import OllamaEngine  # noqa: E402 - see the note above
from docflow.kernels.types import Bytes  # noqa: E402 - see the note above

__all__: list[str] = []

#: The default prompt template for the `structured` mode. `{text}` is replaced with
#: the document's own text; the rest is the caller's to override, because the fields
#: a corpus holds are not this driver's to guess.
DEFAULT_PROMPT: str = (
    "Extract the fields described by the schema from this document's text.\n\n{text}"
)

#: The default prompt for the `vision` mode - about the pixels, not a transcription
#: of them, which is the difference §4 draws between the two.
DEFAULT_VISION_PROMPT: str = (
    "Read the fields described by the schema off this document's pixels."
)


#: How much of the context window is available to the prompt. **Measured, not
#: chosen.** Ollama splits `num_ctx` between the prompt and the generation, and the
#: split is what makes a long prompt silent: on `smollm2` at `num_ctx=4096`, a prompt
#: evaluates at most **2 050** tokens, and `prompt + completion` lands at ~2 078 -
#: i.e. the prompt half is `num_ctx / 2` (2 048) and everything past it is dropped
#: without altering `done_reason`.
#:
#: It is a **reporting basis, not a policy value**: it decides which files this
#: driver names as answered from a truncated prompt, and it never changes how a
#: document is processed. `ADR-009` governs corpus thresholds; this is not one.
#:
#: TODO: [MVP] The split is Ollama's and is not in its public API - it was derived by
#: measurement here (four unrelated prompts of 34 000 / 128 020 / 144 020 / 153 000
#: characters all evaluating exactly 2 050 tokens, and the value tracking `num_ctx`).
#: A runtime that reserves a different fraction would make this wrong, so the driver
#: reports the plateau rather than refusing on it.
PROMPT_WINDOW_SHARE: float = 0.5


@dataclasses.dataclass(frozen=True, slots=True)
class Extraction:
    """What one document produced.

    Attributes:
        source: The file's path relative to the input root - also its mirrored
            location in the output.
        sent_characters: The prompt's length, as the runtime reported it.
        evaluated_tokens: What the runtime evaluated. It **plateaus** when the
            prompt did not fit, which is the only signal a cut leaves.
        num_ctx: The loaded context window. The prompt's share of it is the ceiling
            `evaluated_tokens` stops growing at, which is what makes a cut
            detectable from the call's own numbers.
        completion_tokens: How many tokens the model spent answering.
        done_reason: The runtime's own word: ``"stop"`` for an answer it considers
            complete, ``"length"`` when the ceiling or the window cut it.
        value: The fields, or ``None`` when the call refused.
        artifact: The written fields, relative to the output root, or ``None``.
        note: Why nothing was written, when nothing was.

    """

    source: str
    sent_characters: float | None
    evaluated_tokens: float | None
    num_ctx: int | None
    completion_tokens: float | None
    done_reason: str
    value: Mapping[str, object] | None
    artifact: str | None
    note: str = ""

    @property
    def prompt_was_cut(self) -> bool:
        """Whether the prompt hit the window's prompt share.

        A cut leaves **no other trace**: the runtime answers `done_reason: 'stop'`
        with a plausible value, so the only evidence is that the prompt evaluated as
        many tokens as the window allows for a prompt and no more. At the boundary
        the test cannot separate *exactly fits* from *cut*, and it reports both - a
        false alarm on a prompt that filled its share exactly is the recoverable
        error, and a silent cut is not.

        Returns:
            ``True`` when the evaluated count reached the prompt's share of the
            window.

        """
        if self.evaluated_tokens is None or self.num_ctx is None:
            return False
        return self.evaluated_tokens >= self.num_ctx * PROMPT_WINDOW_SHARE


#: Every extraction of this walk, in order.
OUTCOMES: list[Extraction] = []


def _engine() -> OllamaEngine:
    """Build the K5 adapter.

    Returns:
        The engine, ready to call.

    """
    return llm_driver._engine()


def _image_bytes(path: pathlib.Path) -> Bytes:
    """Read an image into the boundary type the port declares.

    The port takes `Sequence[Bytes]`, and this driver reads the bytes rather than
    passing the path: the adapter's encoder **accepts** a `Path` and base64-encodes
    its string form, so a path would send the model the *file name* and return a
    plausible answer built on nothing.

    Args:
        path: The image to read.

    Returns:
        The bytes with their media type.

    """
    return llm_driver._image(path)


def flatten(value: Mapping[str, object]) -> dict[str, object]:
    """Flatten a nested field mapping into dotted keys, for reporting only.

    A model that satisfies a schema structurally can still nest a value where the
    caller expected a scalar - measured, `smollm2` answered a `total: integer` with
    an object. Flattening is what makes that visible as one line per field instead of
    a nested structure a reader has to walk.

    This is **reporting, not coercion**: the value written to disk is the model's own,
    unchanged. Rewriting it would be this driver deciding what the answer meant.

    Args:
        value: The model's answer.

    Returns:
        One entry per leaf, with dotted keys; an empty mapping when there is none.

    """
    flat: dict[str, object] = {}

    def walk(prefix: str, item: object) -> None:
        if isinstance(item, Mapping):
            for key, nested in item.items():
                walk(f"{prefix}.{key}" if prefix else str(key), nested)
        elif isinstance(item, list):
            flat[prefix] = f"[{len(item)} items]"
        else:
            flat[prefix] = item

    walk("", value)
    return flat


def extract(
    engine: OllamaEngine,
    source: pathlib.Path,
    model: str,
    schema: Mapping[str, object],
    prompt_template: str,
    *,
    mode: str,
) -> Extraction:
    """Ask the model for the fields a document holds.

    Args:
        engine: The K5 adapter.
        source: The file to read - text for `structured`, an image for `vision`.
        model: The model as the caller names it.
        schema: The schema the generation is constrained by.
        prompt_template: The prompt, with ``{text}`` replaced for `structured`.
        mode: ``"structured"`` or ``"vision"``.

    Returns:
        What the call produced, including the two numbers that expose a cut.

    """
    relative = source.name
    if mode == "vision":
        attempt = _mirror.silently(
            llm_driver.extract_from_image,
            engine,
            model,
            "ok",
            DEFAULT_VISION_PROMPT,
            schema,
            [_image_bytes(source)],
        )
    else:
        text = source.read_text(encoding="utf-8")
        attempt = _mirror.silently(
            llm_driver.extract_from_text,
            engine,
            model,
            "ok",
            prompt_template.replace("{text}", text),
            schema,
        )

    if not attempt.succeeded or attempt.result is None:
        return Extraction(
            relative,
            None,
            None,
            None,
            None,
            "refused",
            None,
            None,
            attempt.outcome.detail,
        )

    measured = attempt.result.evidence.measurements
    observed = attempt.result.evidence.observed
    window = observed.get("num_ctx")
    return Extraction(
        source=relative,
        sent_characters=measured.get("prompt_characters"),
        evaluated_tokens=measured.get("prompt_tokens"),
        num_ctx=None if window is None else int(str(window)),
        completion_tokens=measured.get("completion_tokens"),
        done_reason=str(observed.get("done_reason")),
        value=attempt.result.value,
        artifact=None,
    )


def write_fields(
    extraction: Extraction, mirror_dir: pathlib.Path, stem: str, out_root: pathlib.Path
) -> Extraction:
    """Write a document's fields beside it, at the mirrored path.

    The file keeps the model's answer **as it came**, with the call's own facts beside
    it: a value with no record of the model, the window or whether it was cut is a
    number nobody can check. It is named `<stem>.fields.json` - `batch.py` already
    uses `<stem>.json` for the same content, and this driver's own prefix keeps the
    two trees distinguishable when both are pointed at one folder.

    **The value is re-wrapped in `dict()` before it is serialised.** `LlmEngine`
    answers with a `MappingProxyType` (`kernels/types.py`'s recorded PoC property:
    its mappings are not JSON-encodable by default), so `json.dumps` refuses the
    mapping the adapter returns. Measured - the first run of this driver died with
    `TypeError: Object of type mappingproxy is not JSON serializable`. The
    conversion is one level of *container*, not a rewrite of the answer: the model's
    own values cross unchanged, and `kernel_cli/main.py::_mapping` does exactly this
    for the same reason. That encoder is private to the surface and is not imported
    here - a bench reaching into the CLI's internals would break on a refactor there,
    and the CLI's job is the envelope, not this driver's record.

    Args:
        extraction: What the call produced.
        mirror_dir: The directory the document mirrors into.
        stem: The document's stem.
        out_root: The output root, for reporting relative paths.

    Returns:
        The extraction, with its artifact filled in.

    """
    record = {
        "source": extraction.source,
        "value": dict(extraction.value) if extraction.value is not None else None,
        "done_reason": extraction.done_reason,
        "sent_characters": extraction.sent_characters,
        "evaluated_tokens": extraction.evaluated_tokens,
        "completion_tokens": extraction.completion_tokens,
    }
    target = mirror_dir / f"{stem}.fields.json"
    target.write_text(
        json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return dataclasses.replace(
        extraction, artifact=_mirror.relative_to(target, out_root)
    )


def cut_by_the_window(extractions: list[Extraction]) -> list[Extraction]:
    """Report the files whose prompt reached the window's prompt share.

    This is `Extraction.prompt_was_cut` applied per document, so the run names **which
    files** were answered from a truncated prompt rather than only that a ceiling
    exists.

    Two earlier attempts at this were wrong in the same direction, and both are worth
    knowing about because they *looked* like detection:

    1. **An exception check.** `truncated_output` fires on `done_reason: 'length'`,
       which a dropped prompt does **not** produce - the runtime still says `'stop'`.
       Measured: it reported no cut file on a corpus containing a 128 071-character
       prompt.
    2. **A cross-file plateau.** Two prompts evaluating the *same* token count while
       differing in size looked like the signal, and it is - but only when the corpus
       happens to contain two files on the plateau. Measured: on a three-file corpus
       with one cut file it named none, because the cut file had no peer to be equal
       to.

    The mechanism is a property of the **call**, not of the run: the prompt's share of
    `num_ctx`. One call is enough, which is why this takes no view of the corpus.

    Args:
        extractions: The run's extractions, in order.

    Returns:
        The extractions whose prompt was cut, in order.

    """
    return [item for item in extractions if item.prompt_was_cut]


def process_file(
    engine: OllamaEngine,
    source: pathlib.Path,
    root: pathlib.Path,
    out_root: pathlib.Path,
    schema: Mapping[str, object],
    prompt_template: str,
    model: str,
    *,
    mode: str,
    save: bool,
) -> Extraction:
    """Extract one document's fields and write them at the mirrored path.

    Args:
        engine: The K5 adapter.
        source: The file to process.
        root: The input root.
        out_root: The output root.
        schema: The schema the generation is constrained by.
        prompt_template: The prompt, with ``{text}`` replaced for `structured`.
        model: The model as the caller names it.
        mode: ``"structured"`` or ``"vision"``.
        save: Whether to write the fields.

    Returns:
        What the document produced.

    """
    relative = _mirror.relative_to(source, root)
    mirror_dir = out_root / pathlib.Path(relative).parent
    mirror_dir.mkdir(parents=True, exist_ok=True)

    extraction = extract(engine, source, model, schema, prompt_template, mode=mode)
    extraction = dataclasses.replace(extraction, source=relative)

    if save:
        if extraction.value is None:
            _mirror.write_skipped(mirror_dir, source.stem, "llm", extraction.note)
        else:
            extraction = write_fields(extraction, mirror_dir, source.stem, out_root)
    return extraction


def main(argv: list[str] | None = None) -> int:
    """Walk a folder of documents, extract every one's fields, and verify the mirror.

    Args:
        argv: The command-line arguments, or ``None`` for `sys.argv`.

    Returns:
        The number of problems: mirrored-ness violations, plus refused documents,
        plus the documents whose prompt was truncated. A truncated run is counted
        because its fields describe only the start of each document, and a caller
        that trusted them would be reading a partial answer.

    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("input", type=pathlib.Path, help="the folder to walk")
    parser.add_argument(
        "--schema",
        type=pathlib.Path,
        required=True,
        help="the JSON schema the generation is constrained by (required)",
    )
    parser.add_argument(
        "--out",
        type=pathlib.Path,
        default=None,
        help="the output root (default: var/poc/batch_llm_local)",
    )
    parser.add_argument(
        "--prompt",
        default=None,
        help=f"the prompt for the structured mode; must contain '{{text}}' "
        f"(default: {DEFAULT_PROMPT.splitlines()[0]!r})",
    )
    parser.add_argument(
        "--model",
        default=None,
        help=f"the model as the runtime names it (default: {llm_driver.TEXT_MODEL!r})",
    )
    parser.add_argument(
        "--mode",
        choices=("structured", "vision"),
        default="structured",
        help="which §4 requirement to run (default: structured)",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="extract every document without writing its fields",
    )
    args = parser.parse_args(argv)

    root: pathlib.Path = args.input
    if not root.is_dir():
        parser.error(f"{root} is not a directory")
    if not args.schema.is_file():
        parser.error(f"{args.schema} is not a file; the schema is required")

    schema: Mapping[str, object] = json.loads(args.schema.read_text(encoding="utf-8"))
    prompt_template = DEFAULT_PROMPT if args.prompt is None else str(args.prompt)
    if args.mode == "structured" and "{text}" not in prompt_template:
        parser.error(
            "--prompt must contain '{text}': without it the document's own text is "
            "never sent, and the model would answer about the prompt alone."
        )

    default_model = (
        llm_driver.TEXT_MODEL if args.mode == "structured" else llm_driver.VISION_MODEL
    )
    model = default_model if args.model is None else str(args.model)

    out_root = (
        args.out if args.out is not None else _lib.DEFAULT_OUT / "batch_llm_local"
    )
    save = not args.no_save
    _lib.set_out(out_root)
    _lib.reset()

    directories = _mirror.mirror_directories(root, out_root)
    engine = _engine()

    wanted = {"image"} if args.mode == "vision" else None
    print(f"in  = {root}")
    print(f"out = {out_root}")
    print(f"mode = {args.mode}    model = {model}    save = {save}")
    print(f"schema = {args.schema} ({len(schema.get('properties', {}))} propert(ies))")
    print()

    files = _walk_for(root, wanted)
    for source in files:
        extraction = process_file(
            engine,
            source,
            root,
            out_root,
            schema,
            prompt_template,
            model,
            mode=args.mode,
            save=save,
        )
        OUTCOMES.append(extraction)

        if extraction.value is None:
            print(f" -- {extraction.source:44} {extraction.note}")
            continue

        flat = flatten(extraction.value)
        shown = "  ".join(f"{key}={value!r}" for key, value in sorted(flat.items())[:4])
        print(
            f" ok {extraction.source:44} done={extraction.done_reason:<6} "
            f"sent={extraction.sent_characters} "
            f"eval={extraction.evaluated_tokens}  {shown}"
        )

    print()
    print("=== the mirror")
    # Only the files this mode reads: the other kind is outside this run's scope, and
    # reporting it as a violation would blame the run for a file it was not given.
    problems = _mirror.verify_mirror_for(root, out_root, files)
    if not problems:
        print(
            f" ok {len(files)} document(s) and {directories} director(ies) mirrored "
            "at the same relative paths"
        )
    for problem in problems:
        print(f" !! {problem}")

    print()
    written = sum(1 for item in OUTCOMES if item.artifact is not None)
    refused = [item for item in OUTCOMES if item.value is None]
    cut = [item for item in OUTCOMES if item.done_reason == "length"]
    truncated = cut_by_the_window(OUTCOMES)
    silent = [item for item in truncated if item.done_reason != "length"]

    print(f"{'documents':<14}{len(OUTCOMES):>6}")
    print(f"{'fields':<14}{written:>6}")
    print(f"{'refused':<14}{len(refused):>6}")
    print(f"{'cut':<14}{len(cut):>6}")
    print(f"{'truncated':<14}{len(silent):>6}")
    print()

    if cut:
        # `done_reason: 'length'` is the adapter's own typed refusal, so these never
        # wrote a value - reported separately from the ones below, which DID write a
        # plausible-looking answer.
        print(
            f"{len(cut)} document(s) were cut by the ceiling or the window; no fields "
            "were written for them."
        )
    if silent:
        # The dangerous half, and the reason this driver counts anything at all: the
        # runtime reported `done_reason: 'stop'` for these, wrote a value, and the
        # value answers a question about the document's beginning only.
        window = silent[0].num_ctx
        print(
            f"{len(silent)} document(s) had their prompt TRUNCATED without a word. "
            f"num_ctx={window}, so the prompt's share is "
            f"{int((window or 0) * PROMPT_WINDOW_SHARE)} tokens; these reached it, and "
            "everything past it was dropped while `done_reason` stayed 'stop':"
        )
        for item in silent:
            print(
                f"  {item.source} ({item.sent_characters} chars -> "
                f"{item.evaluated_tokens} tokens) - its fields describe the start of "
                "the document"
            )
    if refused:
        print(f"{len(refused)} document(s) produced no fields; see the notes above.")
    if not problems and not refused and not truncated:
        print("every document was extracted and the tree mirrors exactly.")
        return 0
    return len(problems) + len(refused) + len(truncated)


def _walk_for(root: pathlib.Path, wanted: set[str] | None) -> list[pathlib.Path]:
    """List the files this mode reads, in a stable order.

    Args:
        root: The input root.
        wanted: The `_mirror.kind_of` categories to keep, or ``None`` for every file
            - the `structured` mode reads text, which `kind_of` classifies as neither
            a PDF nor an image, so it cannot use that vocabulary to select.

    Returns:
        The files to process, sorted.

    """
    if wanted is None:
        return [
            path
            for path in _mirror.walk(root)
            if _mirror.kind_of(path) in {"invalid"} or path.suffix.lower() == ".txt"
        ]
    return [path for path in _mirror.walk(root) if _mirror.kind_of(path) in wanted]


if __name__ == "__main__":
    sys.exit(main())
