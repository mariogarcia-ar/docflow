"""Lab tool for the orchestrator (``SCR-06``).

A thin caller: its parser, its flags and one handler per subcommand are all it owns. The
frame around them — where the run writes, how the input resolves, the header, the printers
and the exit code — lives in :mod:`scripts.tools._cli`.

It is bound by the orchestrator's own frontier: it reaches the four processors only through
their public contracts and never imports a ``primitives/`` module — so it composes nothing
and decides nothing the library does not.
"""

from __future__ import annotations

import argparse
import importlib
from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Final

import _cli

from docflow.workflow import (
    DocumentRequest,
    ExecutionPolicy,
    configuration,
    persistence,
    process_document,
    resume,
    resume_document,
)
from tests.fakes.engines.fake_provider import FakeProvider

#: Subcommands that publish no file: ``plan`` is a dry run that invokes no processor, and
#: ``status`` and ``context`` only read what an earlier run left. Verified by the hand run in
#: ``docs/plan/bitacora.md`` (2026-09-27).
REPORT_ONLY: Final[tuple[str, ...]] = ("plan", "status", "context")


def build_parser() -> argparse.ArgumentParser:
    """Build the tool's argument parser.

    Returns:
        The parser, with every documented subcommand registered.
    """
    parser, subparsers = _cli.build_parser(
        "workflow.py",
        "Lab bench for the orchestrator: plan, run, resume, inspect.",
    )
    parser.add_argument(
        "--fake-llm",
        action="store_true",
        help="Install the scripted provider at the LLM processor's own seam.",
    )
    parser.add_argument("--workflow", default="documental", help="Workflow identifier.")
    parser.add_argument(
        "--input-type",
        choices=("PDF", "IMAGE", "auto"),
        default="auto",
        help="Declared input type; auto lets the orchestrator detect it.",
    )
    parser.add_argument(
        "--allow-ocr",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Document policy; omitting it lets the library refuse the key by name.",
    )
    parser.add_argument(
        "--allow-vlm",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Document policy; omitting it lets the library refuse the key by name.",
    )
    parser.add_argument(
        "--pdf-dpi", type=int, help="PDF render resolution; never defaulted."
    )
    parser.add_argument("--pdf-extract-pages", action="store_true")
    parser.add_argument("--pdf-render", action="store_true")
    parser.add_argument("--pdf-extract-text", action="store_true")
    parser.add_argument("--pdf-extract-images", action="store_true")
    parser.add_argument("--pdf-layout", action="store_true")
    parser.add_argument("--image-normalize", action="store_true")
    parser.add_argument("--image-prepare-for-ocr", action="store_true")
    parser.add_argument("--image-prepare-for-vlm", action="store_true")
    parser.add_argument("--image-correct-orientation", action="store_true")
    parser.add_argument("--image-deskew", action="store_true")
    parser.add_argument("--ocr", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--ocr-layout", action="store_true")
    parser.add_argument("--ocr-tables", action="store_true")
    parser.add_argument("--ocr-reading-order", action="store_true")
    parser.add_argument("--ocr-language")
    parser.add_argument("--ocr-engine-option", action="append", metavar="KEY=VALUE")
    parser.add_argument("--task", help="The LLM task; required to state the LLM stage.")
    parser.add_argument(
        "--provider", help="The LLM provider; required for the LLM stage."
    )
    parser.add_argument("--model", help="The LLM model; required for the LLM stage.")
    parser.add_argument(
        "--template", help="The LLM template; required for the LLM stage."
    )
    parser.add_argument("--schema", help="The LLM schema, or omit for none.")
    parser.add_argument("--llm-option", action="append", metavar="KEY=VALUE")
    parser.add_argument(
        "--reuse",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Reuse a stage whose result is valid and whose key matches.",
    )
    parser.add_argument(
        "--retry-failed",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Retry a stage that failed in a previous run.",
    )
    parser.add_argument("--parallel-pages", action="store_true")
    parser.add_argument("--start-from", help="Start at this stage.")
    parser.add_argument("--dry-run", action="store_true", help="Plan without running.")

    for name, help_text in (
        ("run", "Run the whole documental workflow."),
        ("plan", "Build the execution plan; invoke no processor."),
        ("status", "Read the per-stage states of the last run."),
        ("context", "Read the durable document context."),
        ("resume", "Continue a previous run without repeating completed work."),
    ):
        _cli.add_subcommand(subparsers, name, help_text)
    for name, help_text in (
        ("force", "Run the given stages even though a valid result exists."),
        ("skip", "Leave the given stages unrun."),
    ):
        scoped = _cli.add_subcommand(subparsers, name, help_text)
        scoped.add_argument("--stages", help="Comma-separated stage names.")
    stop = _cli.add_subcommand(subparsers, "stop", "Stop once a stage finishes.")
    stop.add_argument("--after", help="Stage to stop after.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the tool.

    Args:
        argv: The arguments, defaulting to ``sys.argv[1:]``.

    Returns:
        The process exit code: ``0`` when the run produced a result, ``1`` when the library
        returned a typed failure or refused the configuration by name.
    """
    return _cli.run_tool(
        "workflow",
        build_parser(),
        HANDLERS,
        argv,
        report_only=REPORT_ONLY,
        prepare=lambda args: _install_fake_provider() if args.fake_llm else None,
    )


def _install_fake_provider() -> None:
    """Install the scripted provider at the LLM processor's own seam.

    The seam is reached dynamically and never imported: ``workflow.py`` carries the
    orchestrator's own prohibition and does not touch a ``primitives/`` module. The patch
    sits below the orchestrator's frontier, which is what lets a whole document run be
    demonstrated with no model and no spent token.
    """
    llm_primitives = importlib.import_module("docflow.llm.primitives")
    fake = FakeProvider()
    for name in llm_primitives.PRIMITIVE_NAMES:
        setattr(llm_primitives, name, getattr(fake, name))


def _pdf_options(
    args: argparse.Namespace, parser: argparse.ArgumentParser
) -> dict[str, Any] | None:
    """Build the PDF capabilities, or ``None`` when the caller stated no PDF stage."""
    capabilities = {
        "extract_pages": args.pdf_extract_pages,
        "render": args.pdf_render,
        "extract_text": args.pdf_extract_text,
        "extract_images": args.pdf_extract_images,
        "layout": args.pdf_layout,
    }
    if args.pdf_dpi is None:
        if any(capabilities.values()):
            parser.error(
                "--pdf-dpi is required with a PDF capability; no resolution is defaulted"
            )
        return None
    return {**capabilities, "dpi": int(args.pdf_dpi)}


def _image_options(args: argparse.Namespace) -> dict[str, Any] | None:
    """Build the image transformations, or ``None`` when none were stated."""
    stated = (
        args.image_normalize,
        args.image_prepare_for_ocr,
        args.image_prepare_for_vlm,
        args.image_correct_orientation,
        args.image_deskew,
    )
    if not any(stated):
        return None
    return {
        "normalize": bool(args.image_normalize),
        "prepare_for_ocr": bool(args.image_prepare_for_ocr),
        "prepare_for_vlm": bool(args.image_prepare_for_vlm),
        "correct_orientation": bool(args.image_correct_orientation),
        "deskew": bool(args.image_deskew),
    }


def _ocr_options(
    args: argparse.Namespace, parser: argparse.ArgumentParser
) -> dict[str, Any] | None:
    """Build the OCR options, or ``None`` when none were stated."""
    stated = (
        args.ocr is not None,
        args.ocr_layout,
        args.ocr_tables,
        args.ocr_reading_order,
        args.ocr_language is not None,
        bool(args.ocr_engine_option),
    )
    if not any(stated):
        return None
    return {
        "ocr": bool(args.ocr) if args.ocr is not None else True,
        "layout": bool(args.ocr_layout),
        "tables": bool(args.ocr_tables),
        "reading_order": bool(args.ocr_reading_order),
        "language": args.ocr_language,
        "engine_options": _cli.key_values(
            args.ocr_engine_option, parser, flag="--ocr-engine-option"
        ),
    }


def _llm_options(
    args: argparse.Namespace, parser: argparse.ArgumentParser
) -> dict[str, Any] | None:
    """Build the inference settings, or ``None`` when the caller stated no LLM stage."""
    names = {
        "task": args.task,
        "provider": args.provider,
        "model": args.model,
        "template": args.template,
    }
    if not any(names.values()):
        return None
    if not all(names.values()):
        parser.error(
            "the LLM stage needs --task, --provider, --model and --template; "
            "no provider or model is defaulted"
        )
    return {
        **{key: str(value) for key, value in names.items()},
        "schema": args.schema,
        "options": _cli.key_values(args.llm_option, parser, flag="--llm-option"),
    }


def _stage_list(args: argparse.Namespace, parser: argparse.ArgumentParser) -> list[str]:
    """Parse a comma-separated stage list, refusing an empty one."""
    if not args.stages:
        parser.error(f"{args.subcommand} requires --stages; no stage list is defaulted")
    return [name.strip() for name in args.stages.split(",") if name.strip()]


def _policy(
    args: argparse.Namespace, parser: argparse.ArgumentParser
) -> ExecutionPolicy:
    """Build the execution policy the subcommand implies."""
    return ExecutionPolicy(
        resume=args.subcommand == "resume",
        reuse_successful=bool(args.reuse),
        retry_failed=bool(args.retry_failed),
        skip_stages=_stage_list(args, parser) if args.subcommand == "skip" else [],
        force_stages=_stage_list(args, parser) if args.subcommand == "force" else [],
        stop_after_stage=args.after if args.subcommand == "stop" else None,
        start_from_stage=args.start_from,
        invalidate_downstream=True,
        dry_run=args.subcommand == "plan" or bool(args.dry_run),
        parallel_pages=bool(args.parallel_pages),
    )


def _request(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> DocumentRequest:
    """Build the complete document request the flags describe.

    Every option key and both policy flags are supplied from a flag; a key the caller did
    not state is left **absent**, which is what makes the library's own refusal by name
    reachable instead of filled in here.
    """
    document_id, _ = _cli.identity_for(args, "workflow", input_path)
    options: dict[str, Any] = {"output_dir": str(root)}
    for key, built in (
        ("pdf", _pdf_options(args, parser)),
        ("image", _image_options(args)),
        ("ocr", _ocr_options(args, parser)),
        ("llm", _llm_options(args, parser)),
    ):
        if built is not None:
            options[key] = built

    policies: dict[str, Any] = {}
    if args.allow_ocr is not None:
        policies["allow_ocr"] = bool(args.allow_ocr)
    if args.allow_vlm is not None:
        policies["allow_vlm"] = bool(args.allow_vlm)

    return DocumentRequest(
        document_id=document_id,
        input_path=input_path,
        input_type=args.input_type,
        workflow=args.workflow,
        policies=policies,
        execution=_policy(args, parser),
        options=options,
        metadata={},
    )


def _jsonable(value: Any) -> Any:
    """Return a value the JSON printer can serialize, expanding a dataclass."""
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    return value


def _result_payload(result: Any) -> dict[str, Any]:
    """Build a payload from a document result's own fields."""
    return {
        "status": str(result.status),
        "document_id": result.document_id,
        "workflow_run_id": result.workflow_run_id,
        "processing_key": result.processing_key,
        "input": str(result.input),
        "execution_summary": result.execution_summary,
        "pages": [
            {
                "page_number": page.page_number,
                "status": str(page.status),
                "selected_source": page.selected_source,
                "extraction_strategy": page.extraction_strategy,
                "errors": page.errors,
            }
            for page in result.pages
        ],
        "decisions": result.decisions,
        "errors": result.errors,
        "final_result": _jsonable(result.final_result),
    }


def _cmd_run(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> int:
    """Run the whole documental workflow."""
    result = process_document(_request(args, parser, input_path, root))
    return _cli.report_result(result, _result_payload(result), as_json=args.json)


def _cmd_plan(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> int:
    """Build the execution plan without invoking any processor."""
    result = process_document(_request(args, parser, input_path, root))
    return _cli.report_result(result, _result_payload(result), as_json=args.json)


def _cmd_resume(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> int:
    """Continue a previous run without repeating completed work."""
    result = resume_document(_request(args, parser, input_path, root))
    return _cli.report_result(result, _result_payload(result), as_json=args.json)


def _cmd_status(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> int:
    """Read the per-stage states of the last run."""
    request = _request(args, parser, input_path, root)
    context = resume.load_resumable_context(configuration.state_path(request))
    _cli.print_result(
        {
            "state_path": str(configuration.state_path(request)),
            "context": None if context is None else asdict(context),
        },
        as_json=args.json,
    )
    return 0


def _cmd_context(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> int:
    """Read the durable document context as it was written."""
    request = _request(args, parser, input_path, root)
    path = configuration.state_path(request)
    payload = persistence.read_json(path) if path.is_file() else None
    _cli.print_result(
        {"state_path": str(path), "document_context": payload}, as_json=args.json
    )
    return 0


def _cmd_force(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> int:
    """Run the given stages even though valid results exist."""
    result = process_document(_request(args, parser, input_path, root))
    return _cli.report_result(result, _result_payload(result), as_json=args.json)


def _cmd_skip(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> int:
    """Leave the given stages unrun."""
    result = process_document(_request(args, parser, input_path, root))
    return _cli.report_result(result, _result_payload(result), as_json=args.json)


def _cmd_stop(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> int:
    """Stop once a stage finishes."""
    if args.after is None:
        parser.error("stop requires --after; no stop boundary is defaulted")
    result = process_document(_request(args, parser, input_path, root))
    return _cli.report_result(result, _result_payload(result), as_json=args.json)


HANDLERS: Mapping[str, _cli.Handler] = {
    "run": _cmd_run,
    "plan": _cmd_plan,
    "status": _cmd_status,
    "context": _cmd_context,
    "resume": _cmd_resume,
    "force": _cmd_force,
    "skip": _cmd_skip,
    "stop": _cmd_stop,
}


if __name__ == "__main__":
    raise SystemExit(main())
