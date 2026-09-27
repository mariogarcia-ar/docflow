"""Lab tool for the LLM processor (``SCR-05``).

A thin caller: it parses arguments, builds a real ``LLMInput`` and calls one of
``process_llm_request`` / ``process_llm_node`` or one of its own processor's inventory and
token primitives. ``--provider`` and ``--model`` are required on every inference
subcommand: a default model is exactly the silent stand-in this project forbids.

The ``fake`` subcommand installs the committed scripted provider at the provider seam and
then demonstrates the graph and its resume path twice — with no model reached and no token
spent.

The tool is invoked by path, so the repository root and the ``src/`` layout are put on
``sys.path`` before the library is imported. That bootstrap is bench plumbing: it adds no
behaviour and reaches no engine.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

_TOOLS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _TOOLS_DIR.parents[1]
for _entry in (str(_REPO_ROOT), str(_REPO_ROOT / "src"), str(_TOOLS_DIR)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

import _cli  # noqa: E402  # reason: imported after the path bootstrap above

from docflow import llm as llm_processor  # noqa: E402
from docflow.llm import (  # noqa: E402
    LLMGraphState,
    LLMInput,
    primitives,
)
from docflow.llm.contracts import Usage  # noqa: E402
from docflow.llm.primitives import persistence  # noqa: E402
from docflow.states import StageState  # noqa: E402
from tests.fakes.engines.fake_provider import FakeProvider  # noqa: E402

Handler = Callable[[argparse.Namespace, argparse.ArgumentParser, Path, Path], int]

#: The asset root the template and schema identifiers resolve against by default.
DEFAULT_ASSETS_DIR = _cli.FIXTURES_ROOT / "llm"


def build_parser() -> argparse.ArgumentParser:
    """Build the tool's argument parser.

    Returns:
        The parser, with every documented subcommand registered.
    """
    parser = argparse.ArgumentParser(
        prog="llm.py",
        description="Lab bench for the LLM processor: one inference, or the inventory.",
    )
    _cli.add_common_arguments(parser, identity=True)
    parser.add_argument(
        "--assets-dir",
        default=str(DEFAULT_ASSETS_DIR),
        help="Template and schema root; printed with every run.",
    )
    subparsers = parser.add_subparsers(
        dest="subcommand", required=True, metavar="SUBCOMMAND"
    )

    for name, help_text in (
        ("call", "One inference."),
        ("graph", "The linear inference chain."),
    ):
        scoped = subparsers.add_parser(name, help=help_text)
        _cli.add_input_argument(scoped)
        _add_inference_arguments(scoped)

    node = subparsers.add_parser("node", help="One node of the inference graph.")
    _cli.add_input_argument(node)
    _add_inference_arguments(node)
    node.add_argument("--node", default="node", help="Node identifier.")

    resume = subparsers.add_parser("resume", help="Re-run the chain under a pinned id.")
    _cli.add_input_argument(resume)
    _add_inference_arguments(resume)

    for name, help_text in (
        ("models", "The provider's model inventory; no generation."),
        ("tokens", "An offline token count, and the context window."),
    ):
        scoped = subparsers.add_parser(name, help=help_text)
        _cli.add_input_argument(scoped)
        _add_model_arguments(scoped)

    status = subparsers.add_parser("status", help="Read the durable chain state.")
    _cli.add_input_argument(status)

    fake = subparsers.add_parser(
        "fake", help="Demonstrate the chain with the scripted provider."
    )
    _cli.add_input_argument(fake)
    _add_inference_arguments(fake)
    return parser


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


def _add_decode_options(subparser: argparse.ArgumentParser) -> None:
    """Add the flags that describe the provider call itself.

    They belong to the subcommand, not the tool: they sit where ``--provider`` and
    ``--model`` sit, so the runbook's own spelling works.
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


def main(argv: Sequence[str] | None = None) -> int:
    """Run the tool.

    Args:
        argv: The arguments, defaulting to ``sys.argv[1:]``.

    Returns:
        The process exit code: ``0`` when the run produced a result, ``1`` when the library
        returned a typed failure.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.subcommand == "status" and args.out:
        root = Path(args.out).expanduser().resolve()
        input_path = Path(getattr(args, "input", None) or root).resolve()
    else:
        input_path = _cli.resolve_input(args, parser, text=True)
        root = _cli.output_root("llm", input_path, out=args.out)
    _cli.print_header(
        "llm",
        args.subcommand,
        input_path,
        root,
        extra={"assets_dir": str(Path(args.assets_dir).expanduser())},
    )
    return HANDLERS[args.subcommand](args, parser, input_path, root)


def _require(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    name: str,
    flag: str,
) -> None:
    """Refuse a missing flag by name; no default is substituted for it."""
    if getattr(args, name, None) is None:
        parser.error(f"{args.subcommand} requires {flag}; no default is substituted")


def _options(
    args: argparse.Namespace, parser: argparse.ArgumentParser
) -> dict[str, Any]:
    """Build the decoding options from the caller's flags."""
    options: dict[str, Any] = {}
    for item in args.option or []:
        key, separator, value = item.partition("=")
        if not separator or not key:
            parser.error(f"--option expects KEY=VALUE, got {item!r}")
        options[key] = value
    if args.context_window is not None:
        options["context_window"] = int(args.context_window)
    return options


def _asset_root(args: argparse.Namespace) -> Path:
    """Return the asset root, resolved and ready to record."""
    return Path(args.assets_dir).expanduser().resolve()


def _metadata(
    args: argparse.Namespace, input_path: Path, root: Path | None
) -> dict[str, Any]:
    """Build the metadata an inference request carries, every key stated."""
    document_id, run_id = _cli.identity_for(args, "llm", input_path)
    metadata: dict[str, Any] = {
        "assets_dir": str(_asset_root(args)),
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
    _require(args, parser, "provider", "--provider")
    _require(args, parser, "model", "--model")
    _require(args, parser, "task", "--task")
    _require(args, parser, "template", "--template")
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
        metadata=_metadata(args, input_path, root),
    )


def _result_payload(result: Any) -> dict[str, Any]:
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


def _cmd_call(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> int:
    """Run one inference."""
    request = _request(args, parser, input_path, root)
    result = llm_processor.process_llm_request(request)
    _cli.print_result(_result_payload(result), as_json=args.json)
    return _cli.exit_code_for(result)


def _cmd_graph(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> int:
    """Run the linear inference chain."""
    request = _request(
        args, parser, input_path, root, graph=primitives.default_inference_graph()
    )
    result = llm_processor.process_llm_request(request)
    _cli.print_result(_result_payload(result), as_json=args.json)
    return _cli.exit_code_for(result)


def _cmd_resume(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> int:
    """Re-invoke the chain under a pinned run identity; re-invocation is the resume."""
    _require(args, parser, "run_id", "--run-id")
    request = _request(
        args, parser, input_path, root, graph=primitives.default_inference_graph()
    )
    result = llm_processor.process_llm_request(request)
    _cli.print_result(_result_payload(result), as_json=args.json)
    return _cli.exit_code_for(result)


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


def _cmd_node(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> int:
    """Run one node of the inference graph."""
    del root
    request = _request(args, parser, input_path, None)
    _, run_id = _cli.identity_for(args, "llm", input_path)
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
    _cli.print_result(
        {
            "node_id": node_result.node_id,
            "status": str(node_result.status),
            "request_key": node_result.request_key,
            "result": node_result.result,
            "errors": [asdict(error) for error in node_result.errors],
        },
        as_json=args.json,
    )
    return _cli.exit_code_for(node_result)


def _query(args: argparse.Namespace, parser: argparse.ArgumentParser) -> Any:
    """Build the model query the inventory and token commands ask."""
    _require(args, parser, "provider", "--provider")
    _require(args, parser, "model", "--model")
    options = _options(args, parser)
    return primitives.ModelQuery(
        provider=str(args.provider),
        model=str(args.model),
        base_url=options.get("base_url"),
        api_key=options.get(primitives.API_KEY_OPTION),
        timeout=primitives.request_timeout(options),
    )


def _cmd_models(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> int:
    """Print the provider's model inventory; no generation is performed."""
    del root
    query = _query(args, parser)
    try:
        models = primitives.list_models(query)
        info = primitives.get_model_info(query)
        available = primitives.check_model_available(query)
    except primitives.LLMPrimitiveError as failure:
        return _cli.print_error([failure.error])
    _cli.print_result(
        {
            "input": str(input_path),
            "provider": str(args.provider),
            "model": str(args.model),
            "models": models,
            "model_info": info,
            "available": available,
        },
        as_json=args.json,
    )
    return 0


def _cmd_tokens(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> int:
    """Print an offline token count and the model's context window."""
    del root
    text = input_path.read_text(encoding="utf-8")
    try:
        window = (
            int(args.context_window)
            if args.context_window is not None
            else primitives.get_context_window(_query(args, parser))
        )
    except primitives.LLMPrimitiveError as failure:
        return _cli.print_error([failure.error])
    _cli.print_result(
        {
            "input": str(input_path),
            "tokens": primitives.count_tokens(text),
            "context_window": window,
            "window_source": "caller"
            if args.context_window is not None
            else "provider",
        },
        as_json=args.json,
    )
    return 0


def _cmd_status(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> int:
    """Read and print the durable chain state and the run's last result."""
    del parser, input_path
    state = primitives.load_graph_state(root)
    result = primitives.load_result(root)
    _cli.print_result(
        {
            "run_dir": str(root),
            "state": None if state is None else persistence.state_to_payload(state),
            "final_result": None
            if result is None
            else persistence.result_to_payload(result),
        },
        as_json=args.json,
    )
    return 0


def _install_fake() -> FakeProvider:
    """Install the committed scripted provider at every provider primitive."""
    fake = FakeProvider()
    for name in primitives.PRIMITIVE_NAMES:
        setattr(primitives, name, getattr(fake, name))
    return fake


def _cmd_fake(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> int:
    """Demonstrate the chain and its resume path with no model and no spent token."""
    _require(args, parser, "run_id", "--run-id")
    _install_fake()
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
    _cli.print_result(
        {
            "input": str(input_path),
            "run_id": str(args.run_id),
            "first_run": _result_payload(first),
            "second_run": _result_payload(second),
            "state": None if state is None else persistence.state_to_payload(state),
        },
        as_json=args.json,
    )
    return _cli.exit_code_for(second)


HANDLERS: dict[str, Handler] = {
    "call": _cmd_call,
    "node": _cmd_node,
    "graph": _cmd_graph,
    "resume": _cmd_resume,
    "status": _cmd_status,
    "models": _cmd_models,
    "tokens": _cmd_tokens,
    "fake": _cmd_fake,
}


if __name__ == "__main__":
    raise SystemExit(main())
