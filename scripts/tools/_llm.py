"""The LLM bench's shared command layer (``SCR-15``).

``llm.py`` runs one input and ``batch_llm.py`` runs a folder tree: two callers of the same methods.
This module holds them, so neither tool owns a second copy of a payload, a flag or a request — the
flags are registered by :func:`build_subcommands` and the methods are reached through
:data:`COMMANDS`, both by name.

It is **not** a tool: it has no ``main``, it prints nothing, and it is never invoked directly. A
method does the work and returns the payload; the caller decides whether that becomes stdout
(:mod:`_cli`'s printers) or a file beside the artifacts. The processor's typed failures are raised,
never caught here — a tool prints them and exits ``1``.

It carries the lab-bench exception of ``subplan-scripts.md`` §3.2 for its own processor: it may
drive ``docflow.llm.primitives``.

``--provider`` and ``--model`` are required on every inference command: a default model is exactly
the silent stand-in this project forbids, and the refusal is a post-parse check
(:func:`_cli.required`) so a guard can tell a stated value from an injected default.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any, Final

import _cli

from docflow import llm as llm_processor
from docflow.llm import LLMGraphState, LLMInput, primitives
from docflow.llm.contracts import Usage
from docflow.llm.primitives import persistence
from docflow.states import StageState
from tests.fakes.engines.fake_provider import FakeProvider

#: One subcommand per method, with the help text both tools print. The batch tool states which of
#: them a corpus run may make; this is the full set the layer knows how to build.
SUBCOMMANDS: tuple[tuple[str, str], ...] = (
    ("call", "One inference."),
    ("graph", "The linear inference chain."),
    ("node", "One node of the inference graph."),
    ("resume", "Re-run the chain under a pinned id."),
    ("models", "The provider's model inventory; no generation."),
    ("tokens", "An offline token count, and the context window."),
    ("status", "Read the durable chain state."),
    ("fake", "Demonstrate the chain with the scripted provider."),
)

#: The inputs the LLM processor takes: the extracted text a task is performed over. ``.md`` is the
#: engine's Markdown, which is text too.
SUFFIXES: Final[tuple[str, ...]] = (".txt", ".md")

#: The asset root the template and schema identifiers resolve against by default. The library has no
#: default for ``metadata["assets_dir"]``; the bench states this one and prints the resolved value.
DEFAULT_ASSETS_DIR: Final[Path] = _cli.FIXTURES_ROOT / "llm"

#: What one method returns: the payload its caller prints, or writes beside the artifacts.
Payload = dict[str, Any]

#: A method as the tools call it: the parsed flags, the parser to refuse through, the input and
#: the directory that input's run writes under.
Command = Callable[[argparse.Namespace, argparse.ArgumentParser, Path, Path], Payload]


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


def _add_inference_arguments(subparser: argparse.ArgumentParser) -> None:
    """Add the required provider, model, task and template flags to a subcommand."""
    subparser.add_argument("--provider", help="Provider name; required.")
    subparser.add_argument("--model", help="Model name; required.")
    subparser.add_argument("--task", help="The task to perform; required.")
    subparser.add_argument("--template", help="Template identifier; required.")
    subparser.add_argument("--schema", help="Schema identifier, or omit for none.")
    _add_decode_options(subparser)


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
        if name in ("call", "graph", "resume", "fake"):
            _add_inference_arguments(parser)
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


def _options(
    args: argparse.Namespace, parser: argparse.ArgumentParser
) -> dict[str, Any]:
    """Build the decoding options from the caller's flags."""
    options = _cli.key_values(args.option, parser, flag="--option")
    if args.context_window is not None:
        options["context_window"] = int(args.context_window)
    return options


def _metadata(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path | None,
) -> dict[str, Any]:
    """Build the metadata an inference request carries, every key stated.

    The run identity is derived from the program's own name (``llm.py``, ``batch_llm.py``), so a
    batch's run id says which tool produced it unless the caller pinned one.
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
    return metadata


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
        document=input_path.read_text(encoding="utf-8"),
        images=[],
        extra_context={},
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


def _call(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> Payload:
    """Run one inference."""
    request = _request(args, parser, input_path, root)
    return _result_payload(llm_processor.process_llm_request(request))


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
    return _result_payload(llm_processor.process_llm_request(request))


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
    return _result_payload(llm_processor.process_llm_request(request))


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
    """Count the input's tokens offline, and read the model's context window."""
    del root
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
    first = llm_processor.process_llm_request(
        _request(
            args, parser, input_path, root, graph=primitives.default_inference_graph()
        )
    )
    second = llm_processor.process_llm_request(
        _request(
            args, parser, input_path, root, graph=primitives.default_inference_graph()
        )
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
    "graph": _graph,
    "node": _node,
    "resume": _resume,
    "models": _models,
    "tokens": _tokens,
    "status": _status,
    "fake": _fake,
}
