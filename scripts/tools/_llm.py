"""The LLM bench's shared command layer (``SCR-15``), reshaped after ``scripts/tmpref``.

``llm.py`` runs one input and ``batch_llm.py`` runs a folder tree: two callers of the same methods.
This module holds them, so neither tool owns a second copy of a payload, a flag or a request — the
flags are registered by :func:`build_subcommands` and the methods are reached through
:data:`COMMANDS`, both by name.

It is **not** a tool: it has no ``main``, it prints nothing, and it is never invoked directly. A
method does the work and returns the payload; the caller decides whether that becomes stdout
(:mod:`_cli`'s printers) or a file beside the artifacts. The processor's typed failures are raised,
never caught here — a tool prints them and exits ``1``.

**What this layer owns, and what it does not.** The call is the library's: the request is a
:class:`~docflow.llm.LLMInput`, the inference is :func:`docflow.llm.process_llm_request`, and the
answer is read out of the result's own ``parsed_response``. What is left here is the CLI's surface
— the flags, the ``@FILE`` extras, the stream switch, and the naming and filing of the two files a
``call`` publishes. Nothing here speaks HTTP, and nothing here re-decides a wire shape the seam
already fixed.

**The input is the document, or the page.** An input that is text (``.txt``, ``.md``) is read into
``document``; an input that is an image is attached as the page and no text is stated, so the same
command drives the text flow and the registry's vision twin of it. ``--image`` attaches pages
*beside* the input — repeatable, one image per page, in the order written — which is what a
multi-page document and the library's ``TEXT_PLUS_VLM`` strategy need. A template that asks for a
``<doc>`` the request does not carry is refused by the library rather than handed the image's
bytes: an empty or garbled document is the silent stand-in the placeholder rule forbids.

**Streaming.** ``--stream`` is the seam's own switch rather than a second way to reach a provider.
The flag joins the request's ``options``; the processor reads that option into
:attr:`~docflow.llm.primitives.ProviderCall.stream` and hands the call the observer below, so a
reasoning model's trace and its answer are echoed to stderr under a ``[thinking]`` / ``[content]``
header while stdout stays the payload. The body the run records is the body a waiting call would
have received — the two files are the same either way — which is why the switch is a control
option and not part of the request key.

**Rendering without sending.** ``prompt`` states the same request ``call`` does and stops before the
provider: the render is the library's own :func:`~docflow.llm.primitives.process_prompt`, over the
same asset root, extras and schema, so what it prints is what a call would have sent. It reports the
prompt's token count and measures it against the window the caller *stated* — never a probe — and it
writes nothing, which is why the tool declares it report-only rather than a call with a switch on it.

It carries the lab-bench exception of ``subplan-scripts.md`` §3.2 for its own processor: it may
drive ``docflow.llm.primitives``.

``--provider`` and ``--model`` are required on every inference command: a default model is exactly
the silent stand-in this project forbids, and the refusal is a post-parse check
(:func:`_cli.required`) so a guard can tell a stated value from an injected default.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, Final

import _cli

from docflow import llm as llm_processor
from docflow.llm import LLMGraphState, LLMInput, LLMResult, primitives
from docflow.llm.contracts import Usage
from docflow.llm.primitives import StreamDelta, persistence
from docflow.states import StageState
from tests.fakes.engines.fake_provider import FakeProvider

#: One subcommand per method, with the help text both tools print. The batch tool states which of
#: them a corpus run may make; this is the full set the layer knows how to build.
SUBCOMMANDS: tuple[tuple[str, str], ...] = (
    ("call", "One inference."),
    ("prompt", "The prompt a call would send; nothing is sent."),
    ("graph", "The linear inference chain."),
    ("node", "One node of the inference graph."),
    ("resume", "Re-run the chain under a pinned id."),
    ("models", "The provider's model inventory; no generation."),
    ("tokens", "An offline token count, and the context window."),
    ("status", "Read the durable chain state."),
    ("fake", "Demonstrate the chain with the scripted provider."),
)

#: The text inputs the LLM processor takes: the extracted document a task is performed over.
#: ``.md`` is the engine's Markdown, which is text too.
SUFFIXES: Final[tuple[str, ...]] = (".txt", ".md")

#: The page images a vision call reads. An input carrying one of these suffixes **is** the
#: document: the call attaches the pixels and states no text, which is how the registry's
#: ``…_vision`` templates — the ones with no ``<doc>`` — are driven.
IMAGE_SUFFIXES: Final[tuple[str, ...]] = (
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".bmp",
)

#: The asset root the template and schema identifiers resolve against by default. The library has no
#: default for ``metadata["assets_dir"]``; the bench states this one and prints the resolved value.
DEFAULT_ASSETS_DIR: Final[Path] = _cli.FIXTURES_ROOT / "llm"

#: The suffixes a step name may carry into ``--name`` and must not keep: the two artifacts append
#: their own, so ``--name reading.json`` and ``--name reading`` have to mean the same step.
NAME_SUFFIXES: Final[tuple[str, ...]] = (".json", ".txt")

#: The ``.env`` names the bench honors, each mapped to the option it sets. Only settings that are
#: **optional** on the command line are here: ``--provider`` and ``--model`` stay required flags, so
#: a configuration file can state an endpoint or a window but cannot quietly become a default model.
#:
#: ``num_ctx`` is Ollama's own key for the model's window, and ``context_window`` is the bench's
#: neutral name for the same statement. Since the second pass of 2026-10-04 the processor forwards
#: ``context_window`` to the provider — the Ollama transport translates it into ``num_ctx`` — so
#: either name resizes the window, and ``context_window`` is the one the overflow check also reads.
#: Stating both differently is a mistake with no upside; ``--context-window`` is the spelling to
#: prefer, and ``--option num_ctx=…`` remains the same thing one layer lower.
#:
#: ``think`` and ``min_p`` are the loop brakes for a reasoning reviewer: ``think=false`` stops the
#: model thinking before it answers, and a small ``min_p`` trims the sampling tail it can wander
#: into. ``think`` is a request field rather than a model parameter, and the Ollama transport lifts
#: it out of ``options`` to where ``/api/chat`` reads it.
#:
#: ``temperature``, ``top_p``, ``repeat_penalty`` and ``presence_penalty`` are sampling parameters
#: a model's card may name (deepseek-r1:8b publishes 0.6 / 0.95 / 1.0 / 0.0); blank leaves the
#: model's own default in charge.
ENVIRONMENT_OPTIONS: Final[tuple[tuple[str, str], ...]] = (
    ("DOCFLOW_LLM_BASE_URL", "base_url"),
    ("DOCFLOW_LLM_API_KEY", "api_key"),
    ("DOCFLOW_LLM_TIMEOUT", "timeout"),
    ("DOCFLOW_LLM_CONTEXT_WINDOW", "context_window"),
    ("DOCFLOW_LLM_NUM_CTX", "num_ctx"),
    ("DOCFLOW_LLM_TEMPERATURE", "temperature"),
    ("DOCFLOW_LLM_MIN_P", "min_p"),
    ("DOCFLOW_LLM_TOP_P", "top_p"),
    ("DOCFLOW_LLM_REPEAT_PENALTY", "repeat_penalty"),
    ("DOCFLOW_LLM_PRESENCE_PENALTY", "presence_penalty"),
    ("DOCFLOW_LLM_SEED", "seed"),
    ("DOCFLOW_LLM_THINK", "think"),
)

#: The asset-root setting, which is a flag default rather than a decoding option.
ENVIRONMENT_ASSETS: Final[str] = "DOCFLOW_ASSETS_DIR"

#: The one option that is a credential: it stays the text it is, so a numeric string is not read as
#: the number it looks like and sent as one.
CREDENTIAL_OPTION: Final[str] = "api_key"

#: What one method returns: the payload its caller prints, or writes beside the artifacts.
Payload = dict[str, Any]

#: A method as the tools call it: the parsed flags, the parser to refuse through, the input and
#: the directory that input's run writes under.
Command = Callable[[argparse.Namespace, argparse.ArgumentParser, Path, Path], Payload]


class _Echo:
    """Echo a streaming answer to stderr, under a header per channel.

    A reasoning model writes on two channels — its trace and its answer — and the header is what
    tells them apart on a terminal that receives them interleaved. Nothing is written until a
    channel's first delta arrives, so a call that streams nothing echoes nothing.
    """

    def __init__(self) -> None:
        """Start an echo that has shown no channel yet."""
        self._shown: set[str] = set()

    def __call__(self, delta: StreamDelta) -> None:
        """Write one delta, opening its channel's header the first time it speaks."""
        if delta.channel not in self._shown:
            self._shown.add(delta.channel)
            print(f"\n[{delta.channel}] ", end="", file=sys.stderr, flush=True)
        print(delta.text, end="", file=sys.stderr, flush=True)

    def close(self) -> None:
        """End the line the last delta left open, when any delta was written."""
        if self._shown:
            print(file=sys.stderr)


@contextmanager
def _watched(args: argparse.Namespace) -> Iterator[_Echo | None]:
    """Watch a streaming answer arrive while the block reaches a provider.

    The observer is built here and closed here, so a call that raises — an interrupt, a typed
    failure from the seam — still ends the line it left open.

    Args:
        args: The parsed flags, carrying the stream switch.

    Yields:
        The observer to hand to the call, or ``None`` when ``--stream`` was not stated.
    """
    echo = _Echo() if args.stream else None
    try:
        yield echo
    finally:
        if echo is not None:
            echo.close()


def _send(request: LLMInput, args: argparse.Namespace) -> LLMResult:
    """Send one request through the processor, echoing the answer while it arrives.

    Args:
        request: The inference to perform.
        args: The parsed flags, carrying the stream switch.

    Returns:
        The processor's result: the answer, its validation outcome, and the run's accounting.
    """
    with _watched(args) as observer:
        return llm_processor.process_llm_request(request, observer=observer)


def _add_decode_options(subparser: argparse.ArgumentParser) -> None:
    """Add the flags that describe the provider call itself.

    They belong to the subcommand, not the tool: they sit where ``--provider`` and ``--model`` sit,
    so the runbook's own spelling works.
    """
    subparser.add_argument(
        "--context-window",
        type=int,
        help="The model's context window, when the caller states one.",
    )
    subparser.add_argument(
        "--option",
        action="append",
        metavar="KEY=VALUE",
        help="A decoding option passed through to the provider; may be repeated.",
    )


def _add_request_arguments(subparser: argparse.ArgumentParser) -> None:
    """Add the flags that state the request the layer builds.

    They are the flags of the *request*, not of a transport: a command that renders and stops
    states the same ones a command that sends does, which is what makes the render trustworthy.
    """
    subparser.add_argument("--provider", help="Provider name; required.")
    subparser.add_argument("--model", help="Model name; required.")
    subparser.add_argument("--task", help="The task to perform; required.")
    subparser.add_argument("--template", help="Template identifier; required.")
    subparser.add_argument("--schema", help="Schema identifier, or omit for none.")
    subparser.add_argument(
        "--extra",
        action="append",
        metavar="KEY=VALUE",
        help=(
            "A value for the template's <extra:KEY> placeholder; may be repeated. "
            "KEY=@FILE reads the value from a file."
        ),
    )
    subparser.add_argument(
        "--image",
        action="append",
        metavar="FILE",
        help=(
            "An image to attach beside the input; may be repeated, in the order written. One "
            "image per page, in reading order. An input that is itself an image needs no flag."
        ),
    )
    subparser.add_argument(
        "--image-tokens",
        type=int,
        help=(
            "What one attached image costs in prompt tokens, when the caller has measured it. "
            "The pre-flight adds it to the text estimate; without it a request carrying images is "
            "reported unmeasured, never as fitting."
        ),
    )
    _add_decode_options(subparser)


def _add_inference_arguments(subparser: argparse.ArgumentParser) -> None:
    """Add the request flags and the stream switch a command that reaches a provider states."""
    _add_request_arguments(subparser)
    subparser.add_argument(
        "--stream",
        action="store_true",
        help=(
            "Read the answer as it is written: the model's thinking and its answer are echoed "
            "to stderr, so the terminal shows what it is doing while stdout stays the payload. "
            "The recorded body is the one a waiting call would have received."
        ),
    )


def _add_model_arguments(subparser: argparse.ArgumentParser) -> None:
    """Add the provider and model flags a model-inventory question needs."""
    subparser.add_argument("--provider", help="Provider name; required.")
    subparser.add_argument("--model", help="Model name; required.")
    _add_decode_options(subparser)


def build_subcommands(
    subparsers: Any,
    *,
    input_argument: bool = True,
    only: Sequence[str] | None = None,
) -> dict[str, argparse.ArgumentParser]:
    """Register every subcommand with the flags that are its own.

    Args:
        subparsers: The group :func:`_cli.build_parser` returned.
        input_argument: Whether a subcommand takes the input positional. ``llm.py`` runs one
            input, so it does; ``batch_llm.py`` takes a folder once and walks it, so it does not.
        only: The commands to register, when a caller offers a subset. A command left out is not
            merely hidden — it is not registered, so naming it is a usage error.

    Returns:
        The subcommand parsers by name, for a tool that wants to reach one directly.
    """
    parsers: dict[str, argparse.ArgumentParser] = {}
    for name, help_text in SUBCOMMANDS:
        if only is not None and name not in only:
            continue
        parser = _cli.add_subcommand(
            subparsers, name, help_text, input_argument=input_argument
        )
        # The stream switch is defaulted on every command, not only where it is registered: the
        # layer reads one attribute whatever the command was, and a question that reaches no
        # provider simply never streams.
        parser.set_defaults(stream=False)
        if name in ("call", "graph", "resume", "fake"):
            _add_inference_arguments(parser)
            if name == "call":
                parser.add_argument(
                    "--name",
                    help=(
                        "The base name of the two step artifacts this call publishes, without a "
                        "suffix (default: the schema's last path component, or the template's "
                        "when no schema is stated). Name it when two steps would otherwise share "
                        "one stem."
                    ),
                )
        elif name == "prompt":
            _add_request_arguments(parser)
        elif name == "node":
            _add_inference_arguments(parser)
            parser.add_argument("--node", default="node", help="Node identifier.")
        elif name in ("models", "tokens"):
            _add_model_arguments(parser)
        parsers[name] = parser
    return parsers


def asset_root(args: argparse.Namespace) -> Path:
    """Return the asset root, resolved and ready to record."""
    return Path(args.assets_dir).expanduser().resolve()


def default_assets_dir() -> Path:
    """Return the asset root a run uses when ``--assets-dir`` is not given.

    ``DOCFLOW_ASSETS_DIR`` states it, which is what makes the real registry usable without
    restating the flag on every command. A blank value states nothing and keeps the fixture root —
    the one the built-in chain's ``simple_extract`` / ``simple`` identifiers resolve against, so
    ``graph``, ``fake`` and ``resume`` still work from a template copied verbatim.

    Returns:
        The configured root, or the bench's own default.
    """
    stated = _cli.env_value(ENVIRONMENT_ASSETS)
    return Path(stated) if stated else DEFAULT_ASSETS_DIR


def config_header() -> dict[str, str]:
    """Return the header entry naming what the configuration file contributed, if anything.

    A run that took settings from a file says so, and names them: the file is not an artifact field,
    so without this line a takeover would be invisible. A value the *process* environment states is
    not listed — the caller typed that one, and it is the narrower statement of the two.

    Returns:
        One header line, or an empty mapping when the file contributed nothing.
    """
    taken = [
        name
        for name in (ENVIRONMENT_ASSETS, *(name for name, _ in ENVIRONMENT_OPTIONS))
        if _from_file(name)
    ]
    if not taken:
        return {}
    return {"config": f"{_cli.env_file()} — {', '.join(taken)}"}


def _from_file(name: str) -> bool:
    """Return whether the run takes ``name`` from the file rather than from the process."""
    return (
        bool(_cli.dotenv().get(name, "").strip())
        and not os.environ.get(name, "").strip()
    )


def _environment_options() -> dict[str, Any]:
    """Return the decoding options the bench's configuration states.

    Returns:
        The options, typed as the configuration spells them.
    """
    options: dict[str, Any] = {}
    for name, key in ENVIRONMENT_OPTIONS:
        value = _cli.env_value(name)
        if value is not None:
            options[key] = (
                value if key == CREDENTIAL_OPTION else _cli.typed_value(value)
            )
    return options


def _options(
    args: argparse.Namespace, parser: argparse.ArgumentParser
) -> dict[str, Any]:
    """Build the decoding options from the caller's flags, over the bench's own configuration.

    A flag wins over the file, because the two statements are not the same size: ``--option
    timeout=60`` is about *this* run and the file is about the bench, and the narrower one has to
    win or an override would need an edit. ``--context-window`` keeps its own flag rather than
    joining the table: it is a processor control, not a passthrough. ``--stream`` joins the options
    the same way, and the processor reads it out of them — one statement, one place.

    Returns:
        The options, ready for the request.
    """
    options = _environment_options()
    options.update(_cli.option_values(args.option, parser, flag="--option"))
    if args.context_window is not None:
        options["context_window"] = int(args.context_window)
    if args.stream:
        options[primitives.STREAM_OPTION] = True
    return options


def _extra_context(
    args: argparse.Namespace, parser: argparse.ArgumentParser
) -> dict[str, Any]:
    """Build the values the template's ``<extra:KEY>`` placeholders resolve against.

    ``--extra KEY=VALUE`` states one inline and ``--extra KEY=@FILE`` reads it from a file, which is
    how one step's answer reaches the next over the shell: the run directory holds the answer, and
    the two commands are joined by that path. The value is inserted as the text it is — a string —
    because ``<extra:KEY>`` renders a string verbatim, so a saved answer needs no re-encoding.

    Args:
        args: The parsed flags.
        parser: The parser to report a usage error through.

    Returns:
        The values, by key.
    """
    extra: dict[str, Any] = {}
    for key, value in _cli.key_values(args.extra, parser, flag="--extra").items():
        text = str(value)
        if not text.startswith("@"):
            extra[key] = text
            continue
        path = Path(text[1:]).expanduser()
        try:
            extra[key] = path.read_text(encoding="utf-8")
        except OSError as unreadable:
            parser.error(f"--extra {key}=@{path}: {unreadable}")
            raise  # unreachable: parser.error exits; kept so the return type is honest
    return extra


def _metadata(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path | None,
) -> dict[str, Any]:
    """Build the metadata an inference request carries, every key stated.

    The run identity is derived from the program's own name (``llm.py``, ``batch_llm.py``), so a
    batch's run id says which tool produced it unless the caller pinned one. ``--image-tokens`` goes
    in as metadata because that is where the library reads a page's cost from — a page measured
    after the call cannot prevent the overflow it caused, so the caller states it beforehand.
    """
    document_id, run_id = _cli.identity_for(args, Path(parser.prog).stem, input_path)
    metadata: dict[str, Any] = {
        "assets_dir": str(asset_root(args)),
        "document_id": document_id,
        "workflow_run_id": run_id,
    }
    if root is not None:
        metadata["output_dir"] = str(root)
    if getattr(args, "run_id", None):
        metadata["run_id"] = str(args.run_id)
    if getattr(args, "image_tokens", None) is not None:
        metadata["image_tokens"] = int(args.image_tokens)
    return metadata


def _is_image(input_path: Path) -> bool:
    """Return whether the input is the page itself rather than its extracted text."""
    return input_path.suffix.lower() in IMAGE_SUFFIXES


def _document(input_path: Path) -> str | None:
    """Return the text the request carries, or ``None`` when the input is the page image.

    A template with no ``<doc>`` renders with no document; one that asks for a document is refused
    by the library rather than handed the image's bytes, which would send a model a prompt that
    reads as if the page were empty — a different question.
    """
    return None if _is_image(input_path) else input_path.read_text(encoding="utf-8")


def _images(
    args: argparse.Namespace, parser: argparse.ArgumentParser, input_path: Path
) -> list[str]:
    """Return the images the call attaches, in the order they are sent.

    An input that is itself an image is the first page; ``--image`` adds the pages beside it, which
    is how a multi-page document is one image per page, in reading order, and how pixels are
    attached to a text input (the strategy the library calls ``TEXT_PLUS_VLM``). A path that
    cannot be read is a usage failure before anything is sent, so a run never describes a call it
    could not make.

    Args:
        args: The parsed flags, carrying ``--image``.
        parser: The parser to refuse an unreadable image through.
        input_path: The run's input.

    Returns:
        The absolute image paths, in the order they are sent.
    """
    images: list[str] = []
    if _is_image(input_path):
        images.append(str(input_path))
    for path in getattr(args, "image", None) or []:
        candidate = Path(str(path)).expanduser()
        if not candidate.is_file():
            parser.error(f"--image {path}: not a readable file")
        images.append(str(candidate.resolve()))
    return images


def _request(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path | None,
    *,
    graph: dict[str, Any] | None = None,
) -> LLMInput:
    """Build the inference request the flags describe."""
    _cli.required(args, parser, "provider", "--provider")
    _cli.required(args, parser, "model", "--model")
    _cli.required(args, parser, "task", "--task")
    _cli.required(args, parser, "template", "--template")
    return LLMInput(
        task=str(args.task),
        provider=str(args.provider),
        model=str(args.model),
        template=str(args.template),
        document=_document(input_path),
        images=_images(args, parser, input_path),
        extra_context=_extra_context(args, parser),
        schema=None if args.schema is None else str(args.schema),
        options=_options(args, parser),
        graph=graph,
        metadata=_metadata(args, parser, input_path, root),
    )


def _result_payload(result: Any) -> Payload:
    """Build a payload from an inference result's own fields."""
    return {
        "run_id": result.run_id,
        "status": str(result.status),
        "provider": result.provider,
        "model": result.model,
        "graph_id": result.graph_id,
        "schema_valid": result.schema_valid,
        "validation_errors": list(result.validation_errors),
        "parsed_response": result.parsed_response,
        "raw_response": result.raw_response,
        "usage": asdict(result.usage),
        "node_actions": result.metadata.get("node_actions"),
        "errors": [asdict(error) for error in result.errors],
        "node_results": {
            node_id: {
                "status": str(node.status),
                "request_key": node.request_key,
                "result": node.result,
                "errors": [asdict(error) for error in node.errors],
            }
            for node_id, node in result.node_results.items()
        },
    }


def _fresh_state(run_id: str) -> LLMGraphState:
    """Return a chain state that has not started, for a single node to run against."""
    return LLMGraphState(
        run_id=run_id,
        graph_id="single_node",
        graph_version="1",
        status=StageState.RUNNING,
        current_nodes=[],
        node_states={},
        node_results={},
        attempts={},
        comparisons={},
        errors=[],
        usage=Usage(
            input_tokens=None,
            output_tokens=None,
            total_tokens=None,
            cached_tokens=None,
            provider_usage={},
            estimated_cost=None,
        ),
        stop_requested=False,
        final_result=None,
    )


def _query(args: argparse.Namespace, parser: argparse.ArgumentParser) -> Any:
    """Build the model query the inventory and token commands ask."""
    _cli.required(args, parser, "provider", "--provider")
    _cli.required(args, parser, "model", "--model")
    options = _options(args, parser)
    return primitives.ModelQuery(
        provider=str(args.provider),
        model=str(args.model),
        base_url=options.get("base_url"),
        api_key=options.get(primitives.API_KEY_OPTION),
        timeout=primitives.request_timeout(options),
    )


def install_fake() -> FakeProvider:
    """Install the committed scripted provider at every provider primitive.

    The demonstration the whole PoC needs: a chain and its resume path with no model served and no
    token spent. It replaces the provider seam and nothing else, so everything above it — the
    request, the graph, the state, the persistence — is the real code under test.
    """
    fake = FakeProvider()
    for name in primitives.PRIMITIVE_NAMES:
        setattr(primitives, name, getattr(fake, name))
    return fake


def _artifact_stem(args: argparse.Namespace) -> str | None:
    """Return the name a call's two step artifacts are keyed by.

    ``--name`` states it, which is how a step keeps the file it reads back distinct from the file
    it writes when two steps share a schema name — the extraction and its review both end in
    ``invoice``. With no ``--name`` the identifier is the schema's last path component, so the
    files say which step produced them; a call that states no schema falls back to its template,
    and one that states neither publishes no step artifact.

    Args:
        args: The parsed flags, carrying ``--name``, ``--schema`` and ``--template``.

    Returns:
        The stem, or ``None`` when the call stated neither a name nor an asset identifier.
    """
    stated = getattr(args, "name", None)
    if stated:
        return str(stated).removesuffix(NAME_SUFFIXES[0]).removesuffix(NAME_SUFFIXES[1])
    identifier = getattr(args, "schema", None) or getattr(args, "template", None)
    return None if not identifier else Path(str(identifier)).name


def _publish_step_artifacts(root: Path, stem: str | None, result: LLMResult) -> None:
    """File a call's answer and the run that produced it, under names the step owns.

    The library names its two artifacts after the run directory alone, so two ``call``s over one
    input — the detection gate and the base reading — land on the same ``final_result.json`` and
    the second overwrites the first. These two carry the step's identifier instead:

    * ``<stem>.json`` is the **answer alone** — the object a later step reads back through
      ``--extra KEY=@<stem>.json``. It is the parsed answer, not the provider's envelope: one fence
      around a JSON answer is unwrapped by the library before it is kept. A call that produced no
      answer — every attempt failed before one could be parsed — writes no answer file rather than
      an empty one, and the typed failure is what ``<stem>_full.json`` holds instead.
    * ``<stem>_full.json`` is the **whole run**: the payload ``final_result.json`` holds, with the
      attempts, the usage and the timings a run is judged by.

    Both are published with the library's atomic writer — a ``.tmp`` sibling, then a rename — so a
    reader never sees half an answer. A file the writer refuses is raised as the library's typed
    ``INTERNAL_ERROR`` and never swallowed here: a run does not claim success whose record is
    missing from disk.

    Only ``call`` publishes these: ``graph``, ``resume`` and ``fake`` run the built-in chain, whose
    descriptor ignores ``--schema``/``--template``, so a step name would be a claim about assets the
    run never loaded.

    Args:
        root: The run's output directory.
        stem: The identifier the step is keyed by, or ``None`` when it stated none.
        result: The inference result whose answer and record are written.
    """
    if stem is None:
        return
    if result.raw_response is not None:
        _publish_answer(root, stem, result.parsed_response)
    primitives.write_json_atomic(
        root / f"{stem}_full.json", persistence.result_to_payload(result)
    )


def _publish_answer(root: Path, stem: str, answer: Any) -> None:
    """Publish one answer alone, as the object a later step reads back.

    The library hands back the answer already parsed, so this writes it rather than re-reading the
    model's text. A mapping goes through the deterministic JSON writer; a bare JSON value has no
    keys to sort and is written as canonical text.

    Args:
        root: The run's output directory.
        stem: The step's identifier, without a suffix.
        answer: The parsed answer.
    """
    if isinstance(answer, dict):
        primitives.write_json_atomic(root / f"{stem}.json", answer)
        return
    primitives.write_text_atomic(
        root / f"{stem}.json", json.dumps(answer, ensure_ascii=False, indent=2) + "\n"
    )


def _prompt(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> Payload:
    """Render the prompt a call would send: nothing is sent and nothing is published.

    The flags are the ones :func:`_call` takes, and they are resolved the same way — the same
    asset root, the same ``<extra:KEY>`` values, the same schema — so what is printed is what
    would have been sent. That is the whole point of the answer's being a *rendered prompt*: it
    is evidence about the call, taken without paying for one.

    The request carries no output directory — there is no run to name one for — and it never reaches
    the processor: no provider is reached and nothing is published. The window it measures against is
    the one ``--context-window`` states, never a probe. The provider and the model are stated because
    every inference command states them; what a render reads them for is exactly that window. The
    images the call would attach are stated too — their paths, never their bytes — because a page
    that would be sent is part of the ask a render is evidence about. The fit is the processor's own
    verdict (:func:`~docflow.llm.primitives.context_verdict`), so a page whose cost nobody stated is
    reported *unmeasured* rather than blessed as fitting.
    """
    del root
    request = _request(args, parser, input_path, None)
    assets = primitives.assets_dir_for(request)
    template = primitives.load_template(request.template, assets)
    schema = primitives.load_schema(request.schema, assets)
    prompt = primitives.process_prompt(request, template, schema)
    window = primitives.stated_context_window(request)
    verdict = primitives.context_verdict(
        prompt.tokens,
        window,
        image_count=len(request.images),
        image_tokens=primitives.image_tokens_for(request),
    )
    return {
        "input": str(input_path),
        "prompt": prompt.text,
        "prompt_tokens": prompt.tokens,
        "truncated": prompt.truncated,
        "context_window": window,
        "overflows": verdict == "exceeds",
        "context_verdict": verdict,
        "images": list(request.images),
    }


def _call(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> Payload:
    """Run one inference, filing its two step-named artifacts beside the run's own."""
    request = _request(args, parser, input_path, root)
    result = _send(request, args)
    _publish_step_artifacts(root, _artifact_stem(args), result)
    return _result_payload(result)


def _graph(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> Payload:
    """Run the linear inference chain."""
    request = _request(
        args, parser, input_path, root, graph=primitives.default_inference_graph()
    )
    return _result_payload(_send(request, args))


def _resume(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> Payload:
    """Re-invoke the chain under a pinned run identity; re-invocation is the resume."""
    _cli.required(args, parser, "run_id", "--run-id")
    request = _request(
        args, parser, input_path, root, graph=primitives.default_inference_graph()
    )
    return _result_payload(_send(request, args))


def _node(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> Payload:
    """Run one node of the inference graph.

    The request carries no output directory on purpose: a single node writes nothing, which is why
    this method publishes no file however it ends.
    """
    del root
    request = _request(args, parser, input_path, None)
    _, run_id = _cli.identity_for(args, Path(parser.prog).stem, input_path)
    with _watched(args) as observer:
        node_result = llm_processor.process_llm_node(
            {
                "node_id": str(args.node),
                "depends_on": [],
                "task": str(args.task),
                "template": str(args.template),
                "schema": args.schema,
                "request": request,
            },
            _fresh_state(run_id),
            observer=observer,
        )
    return {
        "node_id": node_result.node_id,
        "status": str(node_result.status),
        "request_key": node_result.request_key,
        "result": node_result.result,
        "errors": [asdict(error) for error in node_result.errors],
    }


def _models(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> Payload:
    """Read the provider's model inventory; no generation is performed."""
    del root
    query = _query(args, parser)
    return {
        "input": str(input_path),
        "provider": str(args.provider),
        "model": str(args.model),
        "models": primitives.list_models(query),
        "model_info": primitives.get_model_info(query),
        "available": primitives.check_model_available(query),
    }


def _tokens(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> Payload:
    """Count the input's tokens offline, and read the model's context window.

    Text only: a page image has no offline token count. What a page costs is the model's own
    reading, stated by the caller as ``metadata["image_tokens"]`` and weighed by the call's own
    pre-flight — not a count this command can take.
    """
    del root
    if _is_image(input_path):
        parser.error(
            f"tokens: {input_path.name} is a page image and has no offline token count; "
            "state metadata['image_tokens'] on the call to weigh it"
        )
    text = input_path.read_text(encoding="utf-8")
    window = (
        int(args.context_window)
        if args.context_window is not None
        else primitives.get_context_window(_query(args, parser))
    )
    return {
        "input": str(input_path),
        "tokens": primitives.count_tokens(text),
        "context_window": window,
        "window_source": "caller" if args.context_window is not None else "provider",
    }


def _status(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> Payload:
    """Read the durable chain state and the run's last result.

    The question is about a *run*, not about an input: the run directory is the subject, and the
    input is only how that directory was named.
    """
    del args, parser, input_path
    state = primitives.load_graph_state(root)
    result = primitives.load_result(root)
    return {
        "run_dir": str(root),
        "state": None if state is None else persistence.state_to_payload(state),
        "final_result": None
        if result is None
        else persistence.result_to_payload(result),
    }


def _fake(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> Payload:
    """Demonstrate the chain and its resume path with no model and no spent token.

    The status is the second run's — the one that resumed — so the payload answers the question the
    exit code asks without the caller having to know which of the two runs is the answer.
    """
    _cli.required(args, parser, "run_id", "--run-id")
    install_fake()
    first = _send(
        _request(
            args, parser, input_path, root, graph=primitives.default_inference_graph()
        ),
        args,
    )
    second = _send(
        _request(
            args, parser, input_path, root, graph=primitives.default_inference_graph()
        ),
        args,
    )
    state = primitives.load_graph_state(root)
    return {
        "input": str(input_path),
        "run_id": str(args.run_id),
        "status": str(second.status),
        "first_run": _result_payload(first),
        "second_run": _result_payload(second),
        "state": None if state is None else persistence.state_to_payload(state),
    }


#: The methods by subcommand name. Both tools dispatch through this, so a subcommand's behaviour
#: lives in exactly one place.
COMMANDS: dict[str, Command] = {
    "call": _call,
    "prompt": _prompt,
    "graph": _graph,
    "node": _node,
    "resume": _resume,
    "models": _models,
    "tokens": _tokens,
    "status": _status,
    "fake": _fake,
}
