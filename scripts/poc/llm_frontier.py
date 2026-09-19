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

The same fields, asked for three ways
-------------------------------------

`FIELDS.json` is the pipeline's own field schema - the file `batch_llm_local.py` takes
as `--schema` - so these probes answer about the caller's fields rather than about a
fixture this bench carries. All three are given the **same** document, read twice:

| Probe | Operation | What is sent |
|---|---|---|
| text only | `structured` | the page's text in the prompt |
| image only | `vision` | the page's pixels on the message |
| text and image | `vision` | both, on one call |

**The pair is derived from one committed PDF, never committed as a pair.** Nothing in
the corpus is a text/image pair - `casos/*.pdf` are born as PDFs and their readings are
produced on demand - and two unrelated fixtures would make a disagreement between the
three answers unattributable to the input. So K2 produces the text (`layout_text`) and
the pixels (`render`, capped at the page's own measured resolution because the adapter
refuses to upscale) from the same page.

**"Text and image" is a caller-side composition, and that is forced.** The frozen port
has no combined operation: `vision` is the only method with an `images` parameter, and
`structured` always passes `images=()`. So the text rides in the prompt while the image
rides on the message, in one call. The probe names that limitation rather than hiding
it - a caller who assumed a combined operation existed would be inventing a port member,
which re-opens `E04-01`.

Asking the same fields three ways is the point, not a convenience: the project's claim
is that **contrast** - two independent reads that disagree - is the only detector of a
silent error, and one document read three ways is what makes a difference attributable
to the input rather than to the model or the page.

Run it with no arguments:

    python scripts/poc/llm_frontier.py

To measure the calls for real, export a key and re-run - nothing else changes:

    DOCFLOW_FRONTIER_KEY=... DOCFLOW_FRONTIER_MAX_TOKENS=1024 \\
        python scripts/poc/llm_frontier.py
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from collections.abc import Mapping, Sequence

import _lib

# `docflow` is only importable once `src/` is on the path; see `pdf.py` for why
# the ordering of these two imports is load-bearing.
_lib.bootstrap()

import llm_local  # noqa: E402 - see above
import pdf as pdf_driver  # noqa: E402 - see above

from docflow.adapters.frontier import FrontierEngine  # noqa: E402 - see above
from docflow.adapters.frontier_providers import (  # noqa: E402 - see above
    PROVIDERS,
    provider_named,
)
from docflow.adapters.pdf import PdfEngine  # noqa: E402 - see above
from docflow.kernels.types import Bytes  # noqa: E402 - see above

__all__: list[str] = []


#: The model, named as the caller names it: ``<provider>:<model>``, with a **colon**.
#: A slash is refused as `model_unknown` - measured, and probed below.
#:
#: **A function rather than a constant, because a constant can only name one
#: provider.** It used to be the literal ``anthropic:claude-sonnet-4-6``, which made
#: every probe below refuse with `provider_unavailable` on a machine whose only key
#: was DeepSeek's - the driver was correct and simply asking the wrong vendor. The
#: default is the first **configured** provider in the table, so the run follows the
#: credential that exists rather than one this file happened to hardcode.
#:
#: ``DOCFLOW_FRONTIER_MODEL`` overrides it, and the refusal below is reached when no
#: provider has a key: the driver then reports the gate chain rather than inventing a
#: vendor it cannot call.
ENV_MODEL: str = "DOCFLOW_FRONTIER_MODEL"

#: The model each provider is probed with when nothing overrides it. One entry per
#: provider, because *the model* is a vendor fact: `claude-sonnet-4-6` means nothing
#: to DeepSeek, and a shared default would be a name one of them rejects.
DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-sonnet-4-6",
    "deepseek": "deepseek-v4-pro",
    "openai": "gpt-4o",
}


def default_model() -> str:
    """Report the model this run should call, from the environment.

    Returns:
        The model as a ``provider:model`` name. ``DOCFLOW_FRONTIER_MODEL`` wins;
        otherwise the first provider in the table that has a credential, paired with
        its own default model; otherwise ``anthropic:claude-sonnet-4-6``, which is a
        name that will refuse and say why rather than a call that cannot be made.

    """
    override = os.environ.get(ENV_MODEL)
    if override:
        return override

    for name, provider in PROVIDERS.items():
        if provider.key_variable(os.environ) is not None:
            return f"{name}:{DEFAULT_MODELS.get(name, name)}"

    return "anthropic:claude-sonnet-4-6"


#: The provider the current run targets, derived from :func:`default_model`.
#: Reported in the header so a reader can see which vendor is being asked, because
#: *which provider answered* is the first fact a frontier run has to state.
MODEL: str = default_model()

#: The same name, as the :class:`Provider` it resolved to, or ``None`` when the
#: default names no configured provider.
PROVIDER = provider_named(MODEL.split(":", 1)[0])

#: The environment variables the chain reads, in the order the adapter reads them:
#: the ceiling, then **whichever credential the selected provider accepts**, then the
#: address override. Recorded here because *which one is missing* is this driver's
#: whole output on a machine with no credential. Public rather than private because
#: `batch_llm_frontier.py` reports the same chain per run, and a second copy of the
#: list would drift from the one the adapter actually reads.
#:
#: **The credential names come from the provider, not from a list here.** They used to
#: be the literals `DOCFLOW_FRONTIER_KEY` / `DOCFLOW_FRONTIER_HOST`, which stopped
#: being the whole truth the moment a provider got its own names: the header then
#: reported *unset* for a variable the adapter was happily reading through.
GATES: tuple[str, ...] = ("DOCFLOW_FRONTIER_MAX_TOKENS",) + (
    (
        PROVIDER.env_key,
        # The shared fallback, listed because the provider consults it too. Naming
        # only the specific one would report *unset* for a setup that works.
        "DOCFLOW_FRONTIER_KEY",
        PROVIDER.env_host,
    )
    if PROVIDER
    else ("DOCFLOW_FRONTIER_KEY", "DOCFLOW_FRONTIER_HOST")
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

#: The schema **file** the three input probes below are constrained by. A file
#: rather than a literal, because the fields a corpus holds are the caller's: the
#: pipeline hands them over, `batch_llm_local.py` takes them as `--schema`, and a
#: caller swapping them must not have to edit this bench. It is the same file those
#: runs use, so these probes answer about the caller's fields and not about a fixture
#: this driver happens to carry.
FIELDS_PATH: pathlib.Path = _lib.ROOT / "scripts" / "poc" / "FIELDS.json"

#: The **text** input, with ``{text}`` replaced by the document's own text. It is the
#: same handoff `my_kernel_flow.md` §6 describes: the text a reader produced, plus the
#: fields wanted.
TEXT_PROMPT: str = (
    "Read this document's text and return the fields described by the schema. "
    "Report only what the text supports; do not infer a value you cannot see."
    "\n\n{text}"
)

#: The **both** input. The port has no text-plus-image operation - `vision` is the
#: only method with an `images` parameter, and `structured` always passes `images=()`
#: - so *both* is the caller composing the two onto one call: the text rides in the
#: prompt and the pixels ride on the message. That is a property of the frozen port
#: rather than a shortcut taken here.
#:
#: The prompt asks the model to **say** where the two disagree instead of silently
#: picking one. Two reads of one page are the only detector of a silent error, and
#: collapsing them into one answer here would destroy exactly that.
BOTH_PROMPT: str = (
    "Read this document's text AND its image, and return the fields described by "
    "the schema. Where the text and the image disagree, report the disagreement "
    "rather than choosing one. Do not infer a value neither supports."
    "\n\n{text}"
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

    **Configured is not the same as *every name present*.** The credential names in
    :data:`GATES` are **alternatives**, not a conjunction: a provider's own variable
    or the shared fallback satisfies the same precondition, and requiring both would
    report a working setup as unmeasurable — which is exactly what this function
    used to do the moment a provider got its own name.

    So each name is reported with its state, and the verdict is *at least one
    credential is set*. That is the same reading the adapter takes, and the two have
    to agree or the header is a second opinion about a fact the adapter owns.

    Returns:
        ``True`` when a call can be attempted.

    """
    print("the gate chain, in the order the adapter reads it:")
    for name in GATES:
        present = bool(os.environ.get(name))
        marker = "set" if present else "unset"
        # The ceiling blocks a call, and the host has a documented default. A
        # credential name is *one way* to satisfy the credential, and the verdict
        # below counts them rather than marking each.
        note = ""
        if name == "DOCFLOW_FRONTIER_MAX_TOKENS" and not present:
            note = "  <- blocks the call"
        print(f"  {name:32} {marker}{note}")

    credential = bool(PROVIDER and PROVIDER.key_variable(os.environ))
    ceiling = bool(os.environ.get("DOCFLOW_FRONTIER_MAX_TOKENS"))
    ready = credential and ceiling

    print()
    if not ready:
        missing = (
            "a credential"
            if not credential
            else "the response ceiling (DOCFLOW_FRONTIER_MAX_TOKENS)"
        )
        print(
            f"No {missing}, so the two requirements are reported as UNMEASURED\n"
            "rather than as working or broken. `capabilities` still answers, and\n"
            "every refusal below names its own remedy.\n"
        )
    else:
        print(
            f"Configured: {MODEL} via "
            f"{PROVIDER.key_variable(os.environ) if PROVIDER else '?'}.\n"
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
        # **A list, because the port declares `Sequence[Bytes]`.** This was a bare
        # `Bytes` and it was a real defect: `_generate` iterates the images to build
        # the message, so a single `Bytes` raised `TypeError: 'Bytes' object is not
        # iterable`. It stayed invisible while no credential was configured, because
        # every call refused at `provider_unavailable` **before** anything reached
        # the images - the defect was in the first line that ran once a key existed.
        [_image(_lib.CASE_IMAGE)] if images is None else images,
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


# --- The three input shapes, all of them against the pipeline's FIELDS.json --
#
# *Text*, *image* and *both*, so that the same fields are asked for three ways and
# the three answers can be compared. That comparison is the point rather than a
# convenience: the project's central claim is that **contrast** - two independent
# reads that disagree - is the only detector of a silent error, and three inputs
# drawn from **one** document is what makes a disagreement attributable to the
# input rather than to a different page.
#
# The pair is derived here instead of committed, because nothing in the corpus is a
# text/imagen pair: `casos/*.pdf` are born as PDFs and the readings are produced on
# demand. Deriving both from one committed PDF is what keeps them the *same*
# document - two unrelated fixtures would make the comparison meaningless.


def _fields_schema(path: pathlib.Path) -> Mapping[str, object]:
    """Read the field schema the three probes are constrained by.

    The fields a corpus holds are the caller's, so the schema is read from a file
    rather than written into this bench: `batch_llm_local.py` takes the same file as
    `--schema`, which is what makes these probes answer about the pipeline's fields
    instead of about a fixture this driver carries.

    Args:
        path: The schema file.

    Returns:
        The schema.

    Raises:
        ValueError: When the file is absent or does not hold a JSON object. A
            refusal is right here rather than a default: a missing schema would
            otherwise become a generation constrained by nothing, reported as a
            success.

    """
    if not path.is_file():
        raise ValueError(
            f"{path} is not a file; the schema is required and is never defaulted. "
            "A generation constrained by nothing would be reported as a success."
        )

    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} does not hold a JSON object")

    return loaded


def _readable_dpi(engine: PdfEngine, source: pathlib.Path, page: int) -> int:
    """Decide the resolution a page is rendered at for a model to read.

    The registry's floor is the **target** and the page's own resolved pixels are the
    **ceiling**, exactly as `batch_pdf.py::_export_dpi` does it: the adapter refuses to
    upscale (`kernel-cli.md` §11 row 4), and that refusal is correct - a bigger
    bitmap is not a more legible one. Asking a 149.69-DPI page for 150 yields **no
    image at all**, which is the one outcome a read-the-pixels probe must not have.

    Measured on the committed fixture: `render @120` returns 152 035 bytes, `@150` is
    refused `insufficient_effective_resolution`.

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
    measured = engine.effective_dpi(source, page)
    if measured.value is None or measured.evidence is None:
        return floor

    held = measured.evidence.measurements.get("effective_dpi")
    if held is None:
        return floor

    return max(1, min(floor, int(held)))


def document_pair(
    engine: PdfEngine,
    source: pathlib.Path,
    page: int,
    *,
    dpi: int | None = None,
) -> tuple[str, Bytes]:
    """Derive one page's text **and** its pixels, so the three probes read one document.

    Args:
        engine: The K2 adapter.
        source: The PDF to read.
        page: One-based page number.
        dpi: The resolution to render at. ``None`` measures the page and caps the
            registry's floor by what it holds.

    Returns:
        The page's text as the reader returns it, and the page as `Bytes`.

    Raises:
        RuntimeError: When either reading refuses. The pair *is* the input to all
            three probes, so a half-derived pair would make two of them answer about
            one document and the third about another - which is precisely the
            comparison this driver exists to make valid.

    """
    text = engine.layout_text(source, [page])
    if text.value is None:
        raise RuntimeError(
            f"layout_text refused page {page}: "
            f"{text.reason.code if text.reason else 'unknown'}"
        )

    resolution = _readable_dpi(engine, source, page) if dpi is None else dpi
    rendered = engine.render(source, [page], resolution)
    if rendered.value is None:
        raise RuntimeError(
            f"render refused page {page} at {resolution} DPI: "
            f"{rendered.reason.code if rendered.reason else 'unknown'}"
        )

    print(
        f"         pair  page={page}  text={len(text.value)} chars  "
        f"image={len(rendered.value.data)} bytes @{resolution} DPI"
    )
    return text.value, Bytes(
        data=rendered.value.data, media_type=rendered.value.media_type
    )


def extract_from_text(
    engine: FrontierEngine,
    model: str,
    expect: str,
    prompt: str | None = None,
    schema: Mapping[str, object] | None = None,
    text: str | None = None,
) -> _lib.Attempt:
    """Ask the frontier model for the fields out of **text alone**.

    The text-only branch, and the one K6 is not advertised for: `my_kernel_flow.md`
    §5 sends §4's pixels, so this probe exists to measure what the *hosted* model
    answers when it is given only what the local model was given. Without it, a
    difference between the local and frontier answers could be attributed to the
    model when it is the input that changed.

    Args:
        engine: The K6 adapter.
        model: The model as the caller names it.
        expect: The bucket this probe is declared to land in.
        prompt: The prompt template, with ``{text}`` replaced. Public because a
            caller with documents of its own must pass its own.
        schema: The schema the generation is constrained by, defaulting to the
            fixture's two-field one.
        text: The document's own text, as the reader returned it.

    Returns:
        The attempt, carrying the fields.

    """
    template = TEXT_PROMPT if prompt is None else prompt
    body = template.replace("{text}", "" if text is None else text)

    attempt = _lib.run(
        f"llm_frontier.structured[{model}]",
        engine.structured,
        model,
        body,
        FIELD_SCHEMA if schema is None else schema,
        expect=expect,
    )
    if attempt.succeeded:
        print(f"         value={dict(attempt.result.value)}")
    print(f"         call_record={engine.last_call_record}")
    return attempt


def extract_from_text_and_image(
    engine: FrontierEngine,
    model: str,
    expect: str,
    prompt: str | None = None,
    schema: Mapping[str, object] | None = None,
    text: str | None = None,
    images: list[Bytes] | None = None,
) -> _lib.Attempt:
    """Ask the frontier model for the fields, given the text **and** the pixels.

    **This is a caller-side composition, and that is forced rather than chosen.** The
    port has no text-plus-image operation: `vision` is the only method with an
    `images` parameter and `structured` always passes `images=()`. So the text rides
    in the prompt while the image rides on the message, on one call. Naming the
    limitation here is the point of the probe - a caller who assumed a combined
    operation existed would be inventing a port member, which re-opens `E04-01`.

    It is also the shape the flow's §5 sentence describes: *"send the llm.local result
    together with the original image"*, where the local result stands in for the
    text it read.

    Args:
        engine: The K6 adapter.
        model: The model as the caller names it.
        expect: The bucket this probe is declared to land in.
        prompt: The prompt template, with ``{text}`` replaced.
        schema: The schema the generation is constrained by.
        text: The document's own text, as the reader returned it.
        images: The page as `Bytes`. `Bytes` and never a `Path`, for the reason
            `llm_local.payload_types` measures: the encoder accepts a `Path` and
            base64-encodes the *file name*.

    Returns:
        The attempt, carrying the fields.

    """
    template = BOTH_PROMPT if prompt is None else prompt
    body = template.replace("{text}", "" if text is None else text)

    attempt = _lib.run(
        f"llm_frontier.text_and_image[{model}]",
        engine.vision,
        model,
        body,
        [_image(_lib.CASE_IMAGE)] if images is None else images,
        FIELD_SCHEMA if schema is None else schema,
        expect=expect,
    )
    if attempt.succeeded:
        print(f"         value={dict(attempt.result.value)}")
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
        # mechanical rather than a rule someone has to remember. Read from
        # `llm_local` rather than spelled out: it was the literal
        # `"ollama:smollm2"`, a second copy of a fact that lives in one place, and a
        # stale one would make the guard compare against the wrong model - so the
        # prohibition would quietly stop being enforced.
        produced_by=f"ollama:{llm_local.TEXT_MODEL}"
        if produced_by is None
        else produced_by,
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

    # **A provider without vision makes every picture probe an expected refusal.**
    # `unsupported_format` is the adapter declining a request whose answer would have
    # been plausible and wrong — measured, DeepSeek accepts the image, ignores the
    # pixels and answers `"NO IMAGE"` as a value. Counting that refusal as a probe
    # that failed would report a correct decision as a defect.
    picturable = (
        "ok"
        if (ready and PROVIDER and PROVIDER.supports_vision)
        else ("precondition" if not ready else "reason")
    )
    vision_note = (
        f"   (expected refusal: {PROVIDER.name} has no vision)"
        if picturable != "ok"
        else ""
    )

    capabilities(engine, MODEL, "ok")
    print(f"\n=== requirement 1: image + high-level prompt{vision_note}")
    extract_from_image(engine, MODEL, picturable, images=[_image(_lib.CASE_IMAGE)])

    print()
    print("=== the same fields, asked for three ways")
    # Which vendor is being asked is the first fact a frontier run states, because a
    # model name means nothing without it and the two providers disagree about vision.
    print(f"  model  = {MODEL}")
    print(
        f"  dialect= {PROVIDER.dialect.name if PROVIDER else '?'}"
        f"   vision={PROVIDER.supports_vision if PROVIDER else '?'}"
        f"   pin={PROVIDER.pins_tool_choice if PROVIDER else '?'}"
    )

    # The schema comes from the pipeline's own file, so these probes answer about the
    # caller's fields rather than about a fixture this driver carries.
    try:
        schema = _fields_schema(FIELDS_PATH)
    except ValueError as exc:
        _lib.note("llm_frontier.fields", f"NOT PROBED: {exc}")
        schema = None

    if schema is not None:
        print(
            f"  schema = {FIELDS_PATH.relative_to(_lib.ROOT)} "
            f"({len(schema.get('properties', {}))} propert(ies))"
        )
        # One document, read twice: the pair is what makes the three answers
        # comparable. Two unrelated fixtures would make a disagreement
        # unattributable to the input.
        pdf_engine = pdf_driver._engine()
        source = _lib.SOURCE_PDF
        page = 1
        try:
            text, image = document_pair(pdf_engine, source, page)
        except (RuntimeError, ValueError) as exc:
            _lib.note("llm_frontier.pair", f"NOT PROBED: {exc}")
        else:
            print(f"  source = {source.relative_to(_lib.ROOT)} page {page}")
            print()
            print("  -- text only")
            extract_from_text(engine, MODEL, reachable, schema=schema, text=text)
            print()
            print(f"  -- image only{vision_note}")
            extract_from_image(engine, MODEL, picturable, images=[image], schema=schema)
            print()
            print(f"  -- text and image together{vision_note}")
            # `picturable`, not `reachable`: this probe sends pixels too, so it
            # inherits whatever the image branch expects. Passing `reachable` here
            # was a real slip — it made the *both* probe demand a value from a
            # provider that had just been correctly refused one.
            extract_from_text_and_image(
                engine, MODEL, picturable, schema=schema, text=text, images=[image]
            )

    print()
    # `judge` grades a **transcript** — the port gives it no `images` parameter — so
    # it is a text call and does not inherit the vision expectation.
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
