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

More than one document, and why
-------------------------------

One document answers *"can K6 read a page"*; it cannot answer *"is the reading any
good"*, which is the question the field run actually needs answered. A model that
returns two well-formed fields for one clean page is one sample, and the failure this
project exists to catch is precisely the one that arrives as a well-formed answer:
`my_kernel_flow.md` §5 sends a page to a hosted model with no cross-check, so a value
the pixels do not support looks exactly like a value they do.

So the bench reads **every case in** :data:`CASES` - sixteen committed documents, each
chosen for a property the others do not have - and the three-way comparison runs per
document rather than once. The set is deliberately not sixteen invoices: it carries
scans with no text layer at all, an image the corpus labels illegible, a two-page
document, and four documents that are **not** invoices (a blackboard, an ID-card back,
an email body, a quote). Those last four are the negative controls, and they are load
bearing: without them an answer is only checked for *plausibility*, and plausibility is
exactly what a hallucination has.

**Nothing in the corpus is a text/image pair, so the pair is derived per case and
never committed as a pair.** `casos/*.pdf` are born as PDFs and their readings are
produced on demand; two unrelated fixtures would make a disagreement between the three
answers unattributable to the input. K2 therefore produces the text (`layout_text`) and
the pixels (`render`, capped at the page's own measured resolution because the adapter
refuses to upscale) from the **same** page.

Two consequences of reading a table rather than a constant, both deliberate:

- **`judge` is asked once per run, not once per case.** Its samples are this driver's
  fixture transcript, not a per-document `llm.local` output, so repeating the call per
  document would pay N times for the same measurement.
- **The call count is printed before the first call.** Every call here reaches a
  **paid** provider, and which subset is worth paying for is the caller's decision
  (`--case`), not this bench's - the same discipline `prd.md` FR-15 states for a
  threshold.

Run it with no arguments to read every case:

    python scripts/poc/llm_frontier.py

See what would run without calling anything, which still exercises K2's pairing over
every case:

    python scripts/poc/llm_frontier.py --dry-run

Narrow it, or list the table:

    python scripts/poc/llm_frontier.py --list
    python scripts/poc/llm_frontier.py --case negativos/pizarra --case escaneados/scan

To measure the calls for real, export a key and re-run - nothing else changes:

    DOCFLOW_FRONTIER_KEY=... DOCFLOW_FRONTIER_MAX_TOKENS=1024 \\
        python scripts/poc/llm_frontier.py
"""

from __future__ import annotations

import argparse
import dataclasses
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


# --- The cases this bench reads ---------------------------------------------


def _probe_suffix(model: str, label: str) -> str:
    """Compose a probe id's suffix from the model and the document.

    The id is what ties a printed line to a call, and a bench that reads a table of
    documents needs both halves: the model alone repeats sixteen times, and the
    document alone would not say which vendor answered.

    Args:
        model: The model as the caller names it.
        label: The document's name, or the empty string when the caller is probing
            a single fixture rather than a case.

    Returns:
        ``"<model>"``, or ``"<model>|<label>"`` when a label was given.

    """
    return model if label == "" else f"{model}|{label}"


#: The page budget every case must fit inside. **A bench that reads a 300-page
#: document measures the corpus, not the adapter**: the call is the same call, and
#: the only thing a longer document adds is a bill and a wait. Checked by
#: :func:`case_pair` for every case, at run time, so a case that outgrows the budget
#: is caught rather than merely discouraged in prose.
MAX_CASE_PAGES: int = 2


@dataclasses.dataclass(frozen=True, slots=True)
class DocumentCase:
    """One committed document, and what reading it is worth.

    Attributes:
        name: The stable identifier, used in probe ids and by ``--case``.
        source: The committed fixture.
        kind: ``"text"``, ``"scan"`` or ``"image"`` - which of the three input
            shapes the document can supply. A ``"scan"`` has no text layer at all,
            so its text probe is *reported as not probed* rather than sent empty;
            an ``"image"`` has no K2 reading to derive.
        pages: The one-based pages read, in order. For an ``"image"`` it is the
            single frame, and the number is not a PDF page.
        negative: Whether the corpus labels this a document that is **not** an
            invoice. Recorded rather than inferred, because it comes from the
            fixture's own folder (``negativos/``), which is a curated fact - and
            because an answer that fills a field here is the one shape a
            hallucination has, so it is the case a reader must be able to find.
        note: Why the case is in the table.

    """

    name: str
    source: pathlib.Path
    kind: str
    pages: tuple[int, ...]
    negative: bool = False
    note: str = ""


#: Every document this bench reads. One run reads all of them; ``--case`` narrows.
#:
#: **The fixtures are committed and the pages are counted, never generated.** A case
#: that loses its provoking property - a scan that gains a text layer, an image that
#: stops being blurred - would otherwise yield a passing probe that measures nothing,
#: which is the defect `E07-03` records for the matrix fixtures.
#:
#: The character counts and resolutions in the notes were **measured** with K2 on
#: ``2026-09-19``, and they are in the note rather than asserted, because a fixture
#: being replaced should make a reader re-read the note rather than fail a check that
#: was never about the pipeline.
CASES: tuple[DocumentCase, ...] = (
    # --- Holds a text layer, so all three input shapes are available -------------
    DocumentCase(
        name="casos/source",
        source=_lib.SOURCE_PDF,
        kind="text",
        pages=(1,),
        note="the one-page text PDF the single-document probes already read",
    ),
    DocumentCase(
        name="casos/dense",
        source=_lib.FIXTURES / "casos" / "9dfc597f-34c5-41ec-99ae-cf35544c7af8.pdf",
        kind="text",
        pages=(1,),
        note="7 105 characters on one page - the densest text page here",
    ),
    DocumentCase(
        name="casos/third",
        source=_lib.FIXTURES / "casos" / "af9f596b-bab2-4e69-b82a-c61fcdacdcbd.pdf",
        kind="text",
        pages=(1,),
        note="3 159 characters; a third independent invoice page",
    ),
    DocumentCase(
        name="aptos/two-pages",
        source=_lib.FIXTURES
        / "pdf_aptos_layout"
        / "9073693b-f8bf-4f9b-88e0-1008de266c0e.pdf",
        kind="text",
        pages=(1, 2),
        note="the only layout-sound fixture with two pages: 1 300 + 410 chars",
    ),
    DocumentCase(
        name="aptos/dense",
        source=_lib.FIXTURES
        / "pdf_aptos_layout"
        / "5b2e1460-197a-436e-b8cc-df5a99f77a43.pdf",
        kind="text",
        pages=(1,),
        note="7 112 characters; a second dense page from another source",
    ),
    # --- No text layer: the only reading available is the pixels --------------
    DocumentCase(
        name="escaneados/scan",
        source=_lib.SCAN_PDF,
        kind="scan",
        pages=(1,),
        note="120.0 DPI and no text layer; `layout_text` refuses `blank_page`",
    ),
    DocumentCase(
        name="escaneados/lower-dpi",
        source=_lib.FIXTURES
        / "pdf_escaneados"
        / "68623f4b-775d-44cc-8f9c-369d441ef315.pdf",
        kind="scan",
        pages=(1,),
        note="100.07 DPI - the lowest-resolution page here, so the floor caps it",
    ),
    DocumentCase(
        name="escaneados/high-dpi",
        source=_lib.FIXTURES
        / "pdf_escaneados"
        / "bddb529d-11ef-4380-92c3-56bdecf2acc2.pdf",
        kind="scan",
        pages=(1,),
        note="294.35 DPI, the highest-resolution scan, capped down to the floor",
    ),
    # --- A single frame, with no K2 reading to derive ------------------------
    DocumentCase(
        name="casos/image",
        source=_lib.CASE_IMAGE,
        kind="image",
        pages=(1,),
        note="1564x1920; the image the single-document probes already read",
    ),
    DocumentCase(
        name="expected/image",
        source=_lib.FIXTURES
        / "expected-extraction"
        / "0fc44015-8d00-4bf0-bdac-ce41f695d8c6.jpg",
        kind="image",
        pages=(1,),
        note="476x1036; a tightly cropped invoice photo",
    ),
    DocumentCase(
        name="otros/photo",
        source=_lib.FIXTURES / "otros" / "125cbe9f-dda5-4f99-9fb3-407230294e07.jpeg",
        kind="image",
        pages=(1,),
        note="900x1600; a phone photograph, so framing and skew are real",
    ),
    DocumentCase(
        name="blur/image",
        source=_lib.BLUR_IMAGE,
        kind="image",
        pages=(1,),
        note="840x1036 and deliberately blurred - the legibility case",
    ),
    # --- Negative controls, so a plausible answer is not mistaken for a read --
    DocumentCase(
        name="negativos/pizarra",
        source=_lib.FIXTURES / "negativos" / "neg_2026-11_foto_pizarra.jpg",
        kind="image",
        pages=(1,),
        negative=True,
        note="a blackboard: it carries neither a total nor a CUIT",
    ),
    DocumentCase(
        name="negativos/dni",
        source=_lib.FIXTURES / "negativos" / "neg_2026-03_dni_dorso.jpg",
        kind="image",
        pages=(1,),
        negative=True,
        note="the back of an ID card: identifiers, but no total to read",
    ),
    DocumentCase(
        name="negativos/correo",
        source=_lib.FIXTURES / "negativos" / "neg_2026-06_correo_liquidacion.pdf",
        kind="text",
        pages=(1,),
        negative=True,
        note="143 characters of an email body - text, but not an invoice",
    ),
    DocumentCase(
        name="negativos/presupuesto",
        source=_lib.FIXTURES / "negativos" / "neg_2026-09_presupuesto.pdf",
        kind="text",
        pages=(1,),
        negative=True,
        note="113 characters of a quote - the near miss: it does carry an amount",
    ),
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
    label: str = "",
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
        label: Which document this call is about, appended to the probe id. It is
            the last parameter and defaults to the empty string, so the positional
            callers that predate it - `batch_llm_frontier.py` among them - keep
            working unchanged. **Reading a table of documents without this is
            unreadable**: every call would report the same id and a reader could not
            say which document a value belonged to.

    Returns:
        The attempt, carrying the fields the probe described.

    """
    attempt = _lib.run(
        f"llm_frontier.vision[{_probe_suffix(model, label)}]",
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


#: What separates two pages' text inside one prompt. A **marker**, not a silent
#: concatenation: a two-page document joined with nothing would present one run of
#: text whose length no reader can attribute to a page, and the pages here are read
#: as one document on purpose. Naming the join is what keeps *"which page said this"*
#: answerable from the transcript.
PAGE_MARKER: str = "\n\n--- page {page} ---\n\n"


@dataclasses.dataclass(frozen=True, slots=True)
class CaseInputs:
    """One case's three input shapes, as far as the case can supply them.

    **A field being ``None`` is a measurement, and it is reported.** A scan has no
    text layer, so its text probe is *not probed* rather than sent an empty string -
    and an empty prompt would look like a reading that found nothing, which is the
    collapse this project exists to prevent (`Never, at any stage`).

    Attributes:
        case: The case these inputs belong to.
        text: The document's text, or ``None`` when it has none to give.
        text_reason: The code that refused the text, or the empty string.
        image: The pages as `Bytes`, in page order, or ``None`` when no page could
            be rendered.
        image_reason: The code that refused the render, or the empty string.
        dpi: The resolution each page was rendered at.
        note: The one-line description printed for the run.

    """

    case: DocumentCase
    text: str | None
    text_reason: str
    image: tuple[Bytes, ...] | None
    image_reason: str
    dpi: int | None
    note: str

    @property
    def textable(self) -> bool:
        """Whether this document has text to send.

        Returns:
            ``True`` when a text read produced characters.

        """
        return self.text is not None

    @property
    def picturable(self) -> bool:
        """Whether this document has pixels to send.

        Returns:
            ``True`` when at least one page rendered.

        """
        return bool(self.image)


def _joined_text(engine: PdfEngine, case: DocumentCase) -> tuple[str | None, str]:
    """Read every page of a case and join the readings, or report the refusal.

    The join carries :data:`PAGE_MARKER` between pages so a two-page reading stays
    attributable to a page. A single-page case gets no marker, because there is no
    boundary to name.

    Args:
        engine: The K2 adapter.
        case: The case to read.

    Returns:
        The joined text and the empty string, or ``None`` and the code that refused
        the first unreadable page - named together, because a caller that received
        ``None`` alone could not say whether there was no text or no reading.

    """
    parts: list[str] = []
    for page in case.pages:
        reading = engine.layout_text(case.source, [page])
        if reading.value is None:
            code = reading.reason.code if reading.reason else "unknown"
            return None, code
        if len(case.pages) > 1:
            parts.append(PAGE_MARKER.format(page=page))
        parts.append(reading.value)

    return "".join(parts), ""


def _rendered_pages(engine: PdfEngine, case: DocumentCase) -> tuple[list[Bytes], int]:
    """Render every page of a case at the resolution each page can supply.

    Each page is measured on its own, because the cap is per page and a two-page
    document can hold two different resolutions - measured here: page 1 of
    `aptos/two-pages` holds 204.8 DPI and page 2 holds 171.15.

    Args:
        engine: The K2 adapter.
        case: The case to render.

    Returns:
        The pages as `Bytes`, and the resolution of the last page rendered. The
        resolution is returned rather than averaged: an average of two resolutions
        describes neither page, and the per-page value is already in the notes.

    Raises:
        RuntimeError: When a page cannot be rendered. Half a document is not the
            document, and one unrenderable page would make the image probe answer
            about a subset the text probe was not given.

    """
    images: list[Bytes] = []
    resolution = 0
    for page in case.pages:
        resolution = _readable_dpi(engine, case.source, page)
        rendered = engine.render(case.source, [page], resolution)
        if rendered.value is None:
            code = rendered.reason.code if rendered.reason else "unknown"
            raise RuntimeError(
                f"render refused page {page} at {resolution} DPI: {code}"
            )
        images.append(
            Bytes(data=rendered.value.data, media_type=rendered.value.media_type)
        )

    return images, resolution


def case_pair(engine: PdfEngine, case: DocumentCase) -> CaseInputs:
    """Derive one case's text **and** its pixels, so the three probes read one document.

    **A refusal is reported, not raised, and that is the difference from a failure.**
    A scan refusing `blank_page` is what the document *is*, so the text probe is
    marked not-probed and the image probe still runs - which is the whole reason a
    scan is in the table. A render refusing is different in kind: it would leave the
    image probe with nothing while the text probe ran, so it is raised.

    Args:
        engine: The K2 adapter.
        case: The case to derive.

    Returns:
        The case's inputs, with either shape absent and its reason named.

    Raises:
        RuntimeError: When the case asks for more pages than :data:`MAX_CASE_PAGES`,
            or when an image case cannot be read, or when a page cannot be rendered.

    """
    if len(case.pages) > MAX_CASE_PAGES:
        raise RuntimeError(
            f"{case.name} asks for {len(case.pages)} pages; the budget is "
            f"{MAX_CASE_PAGES}. A longer document measures the corpus, not the "
            f"adapter: the call is the same call and the bill is not."
        )

    if case.kind == "image":
        image = _image(case.source)
        return CaseInputs(
            case=case,
            text=None,
            text_reason="not_a_pdf",
            image=(image,),
            image_reason="",
            dpi=None,
            note=f"image {len(image.data)} bytes, no K2 reading to derive",
        )

    text, text_reason = _joined_text(engine, case)
    images, resolution = _rendered_pages(engine, case)

    described = f"{len(images)} page(s) @{resolution} DPI"
    if text is None:
        described = f"no text layer ({text_reason}); {described}"
    else:
        described = f"{len(text)} chars; {described}"

    return CaseInputs(
        case=case,
        text=text,
        text_reason=text_reason,
        image=tuple(images),
        image_reason="",
        dpi=resolution,
        note=described,
    )


def _bytes_total(images: Sequence[Bytes] | None) -> int:
    """Report the total size of a tuple of pages.

    Args:
        images: The pages, or ``None``.

    Returns:
        The total bytes, or ``0`` when there are none.

    """
    return sum(len(image.data) for image in images or ())


def extract_from_text(
    engine: FrontierEngine,
    model: str,
    expect: str,
    prompt: str | None = None,
    schema: Mapping[str, object] | None = None,
    text: str | None = None,
    label: str = "",
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
        label: Which document this call is about, appended to the probe id.

    Returns:
        The attempt, carrying the fields.

    """
    template = TEXT_PROMPT if prompt is None else prompt
    body = template.replace("{text}", "" if text is None else text)

    attempt = _lib.run(
        f"llm_frontier.structured[{_probe_suffix(model, label)}]",
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
    label: str = "",
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
        label: Which document this call is about, appended to the probe id.

    Returns:
        The attempt, carrying the fields.

    """
    template = BOTH_PROMPT if prompt is None else prompt
    body = template.replace("{text}", "" if text is None else text)

    attempt = _lib.run(
        f"llm_frontier.text_and_image[{_probe_suffix(model, label)}]",
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
    label: str = "",
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
        label: Which document this call is about, appended to the probe id.

    Returns:
        The attempt, carrying the assessment.

    """
    attempt = _lib.run(
        f"llm_frontier.judge[{_probe_suffix(model, label)}]",
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


def _selected_cases(names: Sequence[str]) -> tuple[DocumentCase, ...]:
    """Pick the cases to read, refusing a name the table does not carry.

    A refusal rather than a skip: a typo would otherwise run a *subset* of what the
    caller asked for and report it as a complete run, which is the same class of
    error as a probe that silently measures nothing.

    Args:
        names: The ``--case`` values, in order, or an empty sequence for all of them.

    Returns:
        The cases to read.

    Raises:
        KeyError: When a name is not in :data:`CASES`. The message carries the names
            that are, so the caller does not have to run ``--list`` to recover.

    """
    if not names:
        return CASES

    known = {case.name: case for case in CASES}
    chosen: list[DocumentCase] = []
    for name in names:
        case = known.get(name)
        if case is None:
            raise KeyError(
                f"{name!r} is not a case in this bench. It carries "
                f"{sorted(known)}. Refusing rather than skipping: a run over a "
                "subset reported as complete is a measurement that did not happen."
            )
        chosen.append(case)

    return tuple(chosen)


def print_cases(cases: Sequence[DocumentCase]) -> None:
    """Print the case table, so a reader can pick a subset without reading the source.

    Args:
        cases: The cases to describe.

    """
    print(f"{'case':24} {'kind':6} {'pages':6} {'neg':4} {'source'}")
    print("-" * 88)
    for case in cases:
        pages = ",".join(str(page) for page in case.pages)
        print(
            f"{case.name:24} {case.kind:6} {pages:6} "
            f"{'yes' if case.negative else '-':4} {_lib.shown(case.source)}"
        )
        print(f"    {case.note}")


def report_budget(cases: Sequence[DocumentCase], schema: bool) -> None:
    """Print how many paid calls this run is about to make, before it makes them.

    **Every call here reaches a paid provider**, so the count is stated up front
    rather than discovered on a bill. It is an upper bound, not a promise: a document
    that turns out to have no text layer has its text probe *not probed*, and a call
    that refuses at `provider_unavailable` is never sent.

    Args:
        cases: The cases about to be read.
        schema: Whether the field schema loaded. Without it the three-way probes do
            not run at all, so the count drops to the two probes that need no schema.

    """
    textable = sum(1 for case in cases if case.kind == "text")
    printed = 1 + len(cases) + 1  # requirement 1's demo + capabilities + judge
    if schema:
        printed += textable * 2 + len(cases)  # text + both per textable, image per case

    print(
        f"  cases  = {len(cases)} ({textable} with a text layer, "
        f"{sum(1 for case in cases if case.negative)} negative controls)"
    )
    print(f"  calls  = up to {printed} paid frontier calls, stated before the first")
    print(
        "           (`role_conflict` and the two naming probes refuse before the "
        "request\n            is built, so they cost nothing)"
    )


def run_case(
    frontier: FrontierEngine,
    pdf_engine: PdfEngine,
    case: DocumentCase,
    schema: Mapping[str, object],
    expectations: Mapping[str, str],
    *,
    dry: bool,
) -> None:
    """Read one document three ways, and report each in turn.

    Args:
        frontier: The K6 adapter.
        pdf_engine: The K2 adapter, which produces the text and the pixels.
        case: The document to read.
        schema: The field schema the three probes are constrained by.
        expectations: The bucket each input shape is declared to land in, keyed
            ``"text"`` and ``"image"``.
        dry: Whether to derive the inputs and stop before the first paid call.

    """
    label = case.name
    print()
    print(
        f"  === {label}   kind={case.kind}{'   NEGATIVE CONTROL' if case.negative else ''}"
    )
    if case.negative:
        print(f"      note: {case.note}")

    try:
        inputs = case_pair(pdf_engine, case)
    except (RuntimeError, ValueError) as exc:
        _lib.note(f"llm_frontier.pair[{label}]", f"NOT PROBED: {exc}")
        return

    print(f"      source = {_lib.shown(case.source)} page(s) {list(case.pages)}")
    print(
        f"      input  = {inputs.note}   image total {_bytes_total(inputs.image)} bytes"
    )

    if dry:
        _lib.note(f"llm_frontier.{label}", "DRY RUN: inputs derived, no call made")
        return

    # A scan has no text layer, so its text probe is *not probed* - never sent an
    # empty prompt, which would look like a reading that found nothing.
    if inputs.textable:
        print("      -- text only")
        extract_from_text(
            frontier,
            MODEL,
            expectations["text"],
            schema=schema,
            text=inputs.text,
            label=label,
        )
    else:
        _lib.note(
            f"llm_frontier.structured[{label}]",
            f"NOT PROBED: no text layer ({inputs.text_reason}); "
            "the pixels are the only reading this document supports",
        )

    if inputs.picturable:
        print("      -- image only")
        extract_from_image(
            frontier,
            MODEL,
            expectations["image"],
            images=list(inputs.image or ()),
            schema=schema,
            label=label,
        )
    else:
        _lib.note(
            f"llm_frontier.vision[{label}]",
            f"NOT PROBED: no page rendered ({inputs.image_reason})",
        )

    if inputs.textable and inputs.picturable:
        print("      -- text and image together")
        extract_from_text_and_image(
            frontier,
            MODEL,
            expectations["image"],
            schema=schema,
            text=inputs.text,
            images=list(inputs.image or ()),
            label=label,
        )


def main(argv: list[str] | None = None) -> int:
    """Run every `llm_frontier` probe and tally the result.

    Args:
        argv: The command-line arguments, or ``None`` for ``sys.argv``.

    Returns:
        The number of probes that produced a bucket other than the one declared.

    """
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        epilog=(
            "The case names are the --case values; each carries the measurement it "
            "was chosen for. Nothing over two pages is read: a longer document "
            "measures the corpus, not the adapter."
        ),
    )
    parser.add_argument(
        "--out",
        type=pathlib.Path,
        default=_lib.DEFAULT_OUT,
        help="kept for symmetry with the other drivers; this one writes nothing",
    )
    parser.add_argument(
        "--case",
        action="append",
        default=[],
        metavar="NAME",
        help="read only this case; repeatable. Default: every case in the table",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="print the case table and exit, making no call at all",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "derive every case's text and pixels - which exercises K2 over the whole "
            "table - and stop before the first frontier call"
        ),
    )
    args = parser.parse_args(argv)

    _lib.set_out(args.out)
    _lib.reset()

    try:
        cases = _selected_cases(args.case)
    except KeyError as exc:
        print(exc.args[0])
        return 1

    if args.list:
        print(f"the {len(cases)} case(s) this bench reads:")
        print()
        print_cases(cases)
        return 0

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
    expectations = {"text": reachable, "image": picturable}

    capabilities(engine, MODEL, "ok")
    print(f"\n=== requirement 1: image + high-level prompt{vision_note}")
    if args.dry_run:
        _lib.note("llm_frontier.vision[requirement-1]", "DRY RUN: no call made")
    else:
        extract_from_image(engine, MODEL, picturable, images=[_image(_lib.CASE_IMAGE)])

    print()
    print("=== the same fields, asked for three ways, per document")
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

    report_budget(cases, schema is not None)
    if args.dry_run:
        print("  dry run: the pairing below is real, the calls are not")

    if schema is not None:
        print(
            f"  schema = {FIELDS_PATH.relative_to(_lib.ROOT)} "
            f"({len(schema.get('properties', {}))} propert(ies))"
        )
    else:
        print("  schema = ABSENT, so the three-way probes are not run at all")

    # One document per case, read twice: the pair is what makes the three answers
    # comparable. Two unrelated fixtures would make a disagreement
    # unattributable to the input.
    pdf_engine = pdf_driver._engine()
    if schema is not None:
        for case in cases:
            run_case(engine, pdf_engine, case, schema, expectations, dry=args.dry_run)

    print()
    # `judge` grades a **transcript** — the port gives it no `images` parameter — so
    # it is a text call and does not inherit the vision expectation. Asked **once**,
    # not once per case: its samples are this driver's fixture transcript, so
    # repeating it per document would pay N times for one measurement.
    print("=== requirement 2: a transcript graded against a rubric")
    if args.dry_run:
        _lib.note("llm_frontier.judge[fixture-transcript]", "DRY RUN: no call made")
    else:
        judge_local(engine, MODEL, reachable)

    print()
    print("=== the prohibition and the naming rules, which need no credential")
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
