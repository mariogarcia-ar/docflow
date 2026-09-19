"""Direct probes of the K6 `llm.frontier` adapter, one method per requirement.

`my_kernel_flow.md` §5 asks for two things of the `llm.frontier` kernel:

> - send the appropriate image with **higher-level** prompts, to extract fields;
> - optionally, send the `llm.local` result **together with** the original image, so
>   it can assess how effective that extraction was.

Those are `vision` and `judge`, and both are implemented. **Neither can be measured
here**, because the workspace has no provider credential - so this driver's job is
different from the others': it reports each gate in the chain, in order, and says
exactly which one stops the call. That is the difference between *"the frontier
circuit is broken"* and *"the frontier circuit is unmeasured"*.

Measured in this workspace (`DOCFLOW_FRONTIER_KEY`, `_HOST` and `_MAX_TOKENS` all
unset):

- `capabilities` **succeeds without a credential** - it describes the adapter's own
  configuration, not the provider's state, and reports
  `revision_is_resolved_on_call: true` rather than inventing a revision it cannot
  read without spending a call;
- every operation that would reach the provider refuses, in a fixed order, each
  naming its own remedy.

One property is worth probing even with no key, because it is enforced **before any
request leaves**: `judge` refuses to grade samples the same model produced. Retrying
to obtain agreement is forbidden (`sad.md` §4), and this is the code that makes it
mechanical rather than a rule in prose.

Run it with no arguments:

    python scripts/poc/llm_frontier.py

To measure the calls for real, export a key and re-run - nothing else changes:

    DOCFLOW_FRONTIER_KEY=... DOCFLOW_FRONTIER_MAX_TOKENS=1024 \\
        python scripts/poc/llm_frontier.py
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys
from collections.abc import Mapping, Sequence

import _lib

# `docflow` is only importable once `src/` is on the path; see `pdf.py` for why
# the ordering of these two imports is load-bearing.
_lib.bootstrap()

from docflow.adapters.frontier import FrontierEngine  # noqa: E402 - see above
from docflow.kernels.types import Bytes  # noqa: E402 - see above

__all__: list[str] = []

#: The model, named as the caller names it: `<provider>:<model>`, with a **colon**.
#: A slash is refused as `model_unknown` - measured, and probed below.
MODEL: str = "anthropic:claude-sonnet-4-6"

#: The environment variables the chain reads, in the order it reads them. Recorded
#: here because *which one is missing* is this driver's whole output on a machine
#: with no credential. Public rather than private because `batch_llm_frontier.py`
#: reports the same chain per run, and a second copy of the list would drift from
#: the one the adapter actually reads.
GATES: tuple[str, ...] = (
    "DOCFLOW_FRONTIER_MAX_TOKENS",
    "DOCFLOW_FRONTIER_KEY",
    "DOCFLOW_FRONTIER_HOST",
)

#: The schema the fixture's generation is constrained by. Public because
#: `batch_llm_frontier.py` uses it as its `vision` mode's default and because
#: `_image`/`_engine` are the same kind of shared helper - a private name imported
#: across modules breaks on a rename in one of them.
FIELD_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {"total": {"type": "integer"}, "cuit": {"type": "string"}},
    "required": ["total", "cuit"],
    "additionalProperties": False,
}

#: The prompt for the high-level read. It names the *shape* of the answer rather
#: than transcribing the page, which is what distinguishes it from K5's prompt.
FIELD_PROMPT: str = (
    "Read this invoice and return its total amount and its CUIT. "
    "Report only what the image supports; do not infer a value you cannot see."
)

#: The `llm.local` output this driver hands to `judge`, verbatim. It is the second
#: half of the flow's sentence - the local model's answer, so the frontier model can
#: compare it against the image.
LOCAL_RESULT: dict[str, object] = {"total": 1500, "cuit": "30-71548265-3"}

RUBRIC: str = (
    "Compare the proposed extraction against the image. For each field, report "
    "whether the value is supported by the pixels, and name any field the proposal "
    "missed."
)


def _engine() -> FrontierEngine:
    """Build the K6 adapter.

    Returns:
        The engine, ready to call.

    """
    return FrontierEngine()


def _image(path: pathlib.Path) -> Bytes:
    """Read an image into the boundary type the port declares.

    Args:
        path: The image to read.

    Returns:
        The bytes with their media type.

    """
    suffix = path.suffix.lower().lstrip(".")
    media = "image/jpeg" if suffix in {"jpg", "jpeg"} else f"image/{suffix}"
    return Bytes(data=path.read_bytes(), media_type=media)


def report_gates() -> bool:
    """Report which environment variables the chain reads, and whether they are set.

    Returns:
        ``True`` when every gate is satisfied and a call can be attempted.

    """
    print("the gate chain, in the order the adapter reads it:")
    ready = True
    for name in GATES:
        present = bool(os.environ.get(name))
        # `HOST` has a documented default address, so it is reported but does not
        # gate; the other two do.
        marker = "set" if present else "unset"
        note = "" if present or name.endswith("HOST") else "  <- blocks the call"
        print(f"  {name:30} {marker}{note}")
        if not present and not name.endswith("HOST"):
            ready = False
    print()
    if not ready:
        print(
            "No credential, so the two requirements are reported as UNMEASURED\n"
            "rather than as working or broken. `capabilities` still answers, and\n"
            "every refusal below names its own remedy.\n"
        )
    return ready


# --- Metric: what the adapter is configured for -----------------------------


def capabilities(engine: FrontierEngine, model: str, expect: str) -> None:
    """Report the adapter's configuration, which needs no credential.

    `revision_is_resolved_on_call: true` is the honest answer rather than a gap: a
    hosted model's revision cannot be read without spending a call, so the flag says
    it is not yet known instead of substituting a plausible string - which is the
    same class of error as keying on a moving tag.

    Args:
        engine: The K6 adapter.
        model: The model as the caller names it.
        expect: The bucket this probe is declared to land in.

    """
    attempt = _lib.run(
        f"llm_frontier.capabilities[{model}]", engine.capabilities, model, expect=expect
    )
    if attempt.succeeded:
        print(f"         observed={dict(attempt.result.evidence.observed)}")


# --- Requirement 1: image + high-level prompt -> fields ---------------------


def extract_from_image(
    engine: FrontierEngine,
    model: str,
    expect: str,
    prompt: str | None = None,
    schema: Mapping[str, object] | None = None,
    images: list[Bytes] | None = None,
) -> _lib.Attempt:
    """Ask the frontier model to read the fields off the image.

    Returns the attempt rather than nothing, so a batch caller reuses this call's
    value instead of paying for a second request - and on this kernel a second
    request is a second **charge**, not just a second wait.

    Args:
        engine: The K6 adapter.
        model: The model as the caller names it.
        expect: The bucket this probe is declared to land in.
        prompt: The prompt to send, defaulting to this driver's fixture one.
        schema: The schema the generation is constrained by, defaulting to the
            fixture's two-field one. A caller with documents of its own must pass
            its own: a fixture schema would answer a question about this bench while
            reporting on real documents.
        images: The images to send, defaulting to the committed case fixture. They
            must be `Bytes` - the encoder accepts a `Path` and silently encodes the
            file name, which `llm_local.payload_types` measures.

    Returns:
        The attempt, carrying the fields the probe described.

    """
    attempt = _lib.run(
        f"llm_frontier.vision[{model}]",
        engine.vision,
        model,
        FIELD_PROMPT if prompt is None else prompt,
        _image(_lib.CASE_IMAGE) if images is None else images,
        FIELD_SCHEMA if schema is None else schema,
        expect=expect,
    )
    if attempt.succeeded:
        print(f"         value={dict(attempt.result.value)}")
    # The raw completion lives on a property rather than on the result: `E01` froze
    # `KernelResult` at three fields, and a port cannot grow a member (that re-opens
    # `E04-01`'s gate). Reported because it is the artifact of record.
    print(f"         call_record={engine.last_call_record}")
    return attempt


# --- Requirement 2: the local result + the image -> an assessment -----------


def judge_local(
    engine: FrontierEngine,
    model: str,
    expect: str,
    samples: Sequence[Mapping[str, object]] | None = None,
    produced_by: str | None = None,
    rubric: str | None = None,
) -> _lib.Attempt:
    """Hand the frontier model the local result *and* the image, and ask it to grade.

    This is the flow's second sentence made callable, and it is the mechanism the
    project's central claim rests on: **contrast** - two independent reads that
    disagree - is the only detector of a silent error. A single confident answer is
    not evidence of correctness.

    **`judge` cannot see the image, and the signature says so.** It takes
    `(model, rubric, samples, produced_by)` and its body builds
    `f"{rubric}\\n\\n" + json.dumps(samples)` before calling `structured`, which passes
    `images=()`. So it grades a **transcript**: the `vision` call above is the one
    that reads pixels. The flow's *"junto con la imagen original"* is therefore
    satisfied by running both, which is what `hitl.py` does and what this driver
    reports rather than papers over.

    Returns the attempt rather than nothing, so a batch caller reuses the
    assessment instead of paying for a second request.

    Args:
        engine: The K6 adapter.
        model: The model as the caller names it.
        expect: The bucket this probe is declared to land in.
        samples: The extractions to grade, defaulting to this driver's fixture. A
            batch caller passes what `llm.local` produced for the document.
        produced_by: The model that produced them, so `role_conflict` is mechanical
            rather than a rule someone has to remember. A batch caller passes the
            model it ran, because grading one's own output is the prohibition.
        rubric: The rubric to grade against, defaulting to this driver's.

    Returns:
        The attempt, carrying the assessment.

    """
    attempt = _lib.run(
        f"llm_frontier.judge[{model}]",
        engine.judge,
        model,
        RUBRIC if rubric is None else rubric,
        [LOCAL_RESULT] if samples is None else list(samples),
        # The local model that produced the samples, so `role_conflict` is
        # mechanical rather than a rule someone has to remember.
        produced_by="ollama:smollm2" if produced_by is None else produced_by,
        expect=expect,
    )
    if attempt.succeeded:
        print(f"         value={dict(attempt.result.value)}")
    return attempt


# --- The prohibition, which is enforced before any request leaves -----------


def role_conflict(engine: FrontierEngine, model: str) -> None:
    """Ask the model to grade its own output, and confirm it refuses.

    Retrying until two samples agree manufactures contrast where none existed
    (`sad.md` §4), and `sad.md` §11 row 15 is the prohibition. The check is
    tag-insensitive, so naming the same model with a different tag still conflicts.

    Args:
        engine: The K6 adapter.
        model: The model, in both roles.

    """
    _lib.run(
        "llm_frontier.judge[self-grading]",
        engine.judge,
        model,
        RUBRIC,
        [LOCAL_RESULT],
        produced_by=model,
        expect="precondition",
    )


def naming_rules(engine: FrontierEngine) -> None:
    """Probe the two ways a model name can be wrong.

    A **slash** instead of a colon is refused as `model_unknown`; an unknown
    **provider** is refused as `provider_unknown`, and the message quotes the one
    provider that is configured. Neither falls back to a default - the names are the
    mechanism that makes *"there is no fallback"* assertable rather than merely
    stated.

    Args:
        engine: The K6 adapter.

    """
    for name, expected in (
        ("anthropic/claude-sonnet-4-6", "precondition"),
        ("nope:gpt-4", "precondition"),
    ):
        _lib.run(
            f"llm_frontier.naming[{name}]",
            engine.structured,
            name,
            FIELD_PROMPT,
            FIELD_SCHEMA,
            expect=expected,
        )


# --- The run ----------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Run every `llm_frontier` probe and tally the result.

    Args:
        argv: The command-line arguments, or ``None`` for ``sys.argv``.

    Returns:
        The number of probes that produced a bucket other than the one declared.

    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--out",
        type=pathlib.Path,
        default=_lib.DEFAULT_OUT,
        help="kept for symmetry with the other drivers; this one writes nothing",
    )
    args = parser.parse_args(argv)

    _lib.set_out(args.out)
    _lib.reset()
    engine = _engine()

    ready = report_gates()

    # The two requirements. Without a credential they are still *probed* - the
    # expected bucket becomes the precondition refusal, which is an answer about
    # this machine rather than a hole in the run.
    reachable = "ok" if ready else "precondition"

    capabilities(engine, MODEL, "ok")
    extract_from_image(engine, MODEL, reachable)

    print()
    judge_local(engine, MODEL, reachable)

    print()
    # Enforced with no key, because it is decided before the request is built.
    role_conflict(engine, MODEL)
    naming_rules(engine)

    print()
    if not ready:
        _lib.note(
            "llm_frontier.requirements",
            "UNMEASURED: both requirements are implemented; no credential to call with",
        )

    print()
    return _lib.summary()


if __name__ == "__main__":
    sys.exit(main())
