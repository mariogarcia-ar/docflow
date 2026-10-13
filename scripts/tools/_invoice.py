"""The invoice flow's command layer, driving the LLM bench over the registry's invoice steps.

The flow is *data* in the registry: five extraction templates, each with the schema that compiles
its answer's shape, and this module is the one place that knows their names and their order. It is
not a tool — it has no ``main`` and prints nothing (:mod:`scripts.tools.cli_invoice` is the caller)
— and it adds no contract: every step is the bench's own ``call``, reached through
:data:`_llm.COMMANDS` with the task, the template and the schema the step table states.

**One table, two twins.** Each step names the identifier pair the *text* flow reads and the pair
its vision twin reads, and the input's own kind decides which pair is used — the same rule
:mod:`_llm` applies when it decides whether a call carries a document or a page. Naming both pairs
here is what keeps the twins in step: a vision identifier that drifts is a step the flow can no
longer reach, and the test that runs the flow over a page reddens on it.

**Why each step gets its own directory.** A run directory is keyed by the input alone, so five
calls over one document would file five results onto the same ``final_result.json`` and the second
would overwrite the first. Each step therefore writes under ``<root>/<step>/``: ``<step>.json`` is
the answer alone — the object a later step or a review reads back — and ``<step>_full.json`` is the
whole run, exactly the pair :func:`_llm._publish_step_artifacts` files, keyed by the step's name.

**Validity is a step, not a score.** ``detection`` answers whether the paper is a receipt at all,
and its own field says so; :func:`validity` reads that field and nothing else. A step that produced
no answer states ``None``, never a verdict the model did not give.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Final, NamedTuple

import _cli
import _llm

#: What one method returns: the payload its caller prints, or writes beside the artifacts.
Payload = dict[str, Any]

#: A method as the tool calls it: the parsed flags, the parser to refuse through, the input and
#: the directory the run writes under.
Command = _llm.Command

#: The registry the flow's templates and schemas are read from. The identifiers are the committed
#: asset registry's, not the fixture root's, so this is the default and not a fallback.
ASSETS_DIR: Final[Path] = _cli.REPO_ROOT / "registry" / "llm-local"

#: The step that answers whether the paper is a receipt, and the field of its answer that says so.
DETECTION: Final[str] = "detection"
VALIDITY_FIELD: Final[str] = "comprobante_valido"

#: The command that runs every step, in :data:`STEPS` order.
FLOW: Final[str] = "flow"


class Step(NamedTuple):
    """One step of the flow: its identifiers, and the extra keys its template asks for.

    Attributes:
        name: The subcommand's name, and the stem of the two artifacts the step files.
        task: The label recorded in the run; it never reaches the model.
        template: The text template's identifier under the asset root.
        schema: The text schema's identifier, which the answer's shape is compiled from.
        vision_template: The identifier the same step reads a page with.
        vision_schema: The schema that compiles the vision answer's shape.
        requires: The ``<extra:KEY>`` placeholders the template cannot render without.
    """

    name: str
    task: str
    template: str
    schema: str
    vision_template: str
    vision_schema: str
    requires: tuple[str, ...] = ()


#: The flow, in the order it runs: the gate first, then the base reading the reviews judge, then
#: the three readings that refine it. Both identifier pairs of every step are stated, so the vision
#: twin of a step is reachable exactly where its text twin is.
STEPS: Final[tuple[Step, ...]] = (
    Step(
        name=DETECTION,
        task="detection",
        template="extraction/invoice_deteccion",
        schema="extraction/invoice_detection",
        vision_template="extraction/invoice_vision_deteccion",
        vision_schema="extraction/invoice_vision_detection",
    ),
    Step(
        name="extract",
        task="extract",
        template="extraction/invoice",
        schema="extraction/invoice",
        vision_template="extraction/invoice_vision",
        vision_schema="extraction/invoice_vision",
    ),
    Step(
        name="desglose",
        task="desglose",
        template="extraction/invoice_desglose",
        schema="extraction/invoice_desglose",
        vision_template="extraction/invoice_vision_desglose",
        vision_schema="extraction/invoice_vision_desglose",
    ),
    Step(
        name="clasificacion",
        task="clasificacion",
        template="extraction/invoice_clasificacion",
        schema="extraction/invoice_clasificacion",
        vision_template="extraction/invoice_vision_clasificacion",
        vision_schema="extraction/invoice_vision_clasificacion",
    ),
    Step(
        name="rubro",
        task="rubro",
        template="extraction/invoice_rubro",
        schema="extraction/invoice_rubro",
        vision_template="extraction/invoice_vision_rubro",
        vision_schema="extraction/invoice_vision_rubro",
        requires=("rubro",),
    ),
)


def default_assets_dir() -> Path:
    """Return the asset root a run reads its templates from when ``--assets-dir`` is not given.

    ``DOCFLOW_ASSETS_DIR`` states it, so a second registry is reachable without restating the flag
    on every command. A blank value states nothing and keeps the committed local registry the five
    steps' identifiers resolve against.

    Returns:
        The configured root, or the committed local registry.
    """
    stated = _cli.env_value(_llm.ENVIRONMENT_ASSETS)
    return Path(stated) if stated else ASSETS_DIR


def step_assets(step: Step, *, image: bool) -> tuple[str, str]:
    """Return the ``(template, schema)`` identifiers one step is run with.

    Args:
        step: The step.
        image: Whether the input is the page itself, which selects the vision pair.

    Returns:
        The template and the schema identifier, both under the asset root.
    """
    if image:
        return step.vision_template, step.vision_schema
    return step.template, step.schema


def validity(answer: Any) -> bool | None:
    """Return what an answer states about the paper's validity, or ``None`` when it states nothing.

    The field is a string enum in the schema, so it is read as one; an answer that is not an object,
    or one that carries no verdict, has none to read — which is not the same as a verdict of false.

    Args:
        answer: The detection step's parsed answer.

    Returns:
        ``True`` or ``False`` when the answer stated one, ``None`` when it did not.
    """
    if not isinstance(answer, Mapping):
        return None
    stated = answer.get(VALIDITY_FIELD)
    return None if stated is None else str(stated).strip().lower() == "true"


def build_subcommands(subparsers: Any) -> dict[str, argparse.ArgumentParser]:
    """Register one subcommand per step, and the whole flow.

    A step states the flags a ``call`` states — the template, the schema and the task are the
    step's own and are not flags — so it is run the way any other inference is, minus the three
    identifiers the table fixes. ``--rubro`` is registered on the commands that read it, which is
    the same statement :data:`STEPS` carries and not a second copy of it.

    Args:
        subparsers: The group :func:`_cli.build_parser` returned.

    Returns:
        The subcommand parsers by name, for a caller that wants to reach one directly.
    """
    parsers: dict[str, argparse.ArgumentParser] = {}
    for step in STEPS:
        subparser = _cli.add_subcommand(
            subparsers, step.name, f"The {step.name} step of the invoice flow."
        )
        _llm.add_inference_arguments(subparser, identifiers=False)
        _add_required_extras(subparser, (step,))
        parsers[step.name] = subparser
    flow = _cli.add_subcommand(
        subparsers, FLOW, "The whole flow: every step, in the flow's own order."
    )
    _llm.add_inference_arguments(flow, identifiers=False)
    _add_required_extras(flow, STEPS)
    parsers[FLOW] = flow
    return parsers


def validate_flags(
    command: str, args: argparse.Namespace, parser: argparse.ArgumentParser
) -> None:
    """Refuse a missing required flag, once, before the run starts.

    Every command reaches a provider, so ``--provider`` and ``--model`` are required on all of
    them; a command whose template asks for an extra cannot render without it either. Both
    refusals happen before the header, so a run that cannot start never announces itself.

    Args:
        command: The subcommand being run.
        args: The parsed arguments.
        parser: The parser to report the usage error through.
    """
    _cli.required(args, parser, "provider", "--provider")
    _cli.required(args, parser, "model", "--model")
    for key in _required_extras(_commands(command)):
        _cli.required(args, parser, key, f"--{key}")


def _add_required_extras(
    subparser: argparse.ArgumentParser, steps: Iterable[Step]
) -> None:
    """Register one flag per extra key the steps' templates ask for."""
    for key in _required_extras(steps):
        subparser.add_argument(
            f"--{key}",
            help=f"The {key} the step's template is asked about; required.",
        )


def _required_extras(steps: Iterable[Step]) -> tuple[str, ...]:
    """Return the extra keys the steps ask for, in the order they first appear."""
    keys: dict[str, None] = {}
    for step in steps:
        for key in step.requires:
            keys.setdefault(key, None)
    return tuple(keys)


def _commands(command: str) -> tuple[Step, ...]:
    """Return the steps one command runs: the step itself, or every step for the flow."""
    return (
        STEPS
        if command == FLOW
        else tuple(step for step in STEPS if step.name == command)
    )


def _call_arguments(
    args: argparse.Namespace, step: Step, input_path: Path
) -> argparse.Namespace:
    """Return the flags one ``call`` reads, with the step's own identifiers stated.

    The step fixes the task, the template, the schema and the name; everything else the caller
    stated — the provider, the model, the options, the pages — is passed through untouched, so a
    step is tunable exactly as far as a ``call`` is.

    Args:
        args: The parsed flags of the invoice command.
        step: The step being run.
        input_path: The run's input, whose kind selects the text or the vision pair.

    Returns:
        The flags the bench's ``call`` reads.
    """
    template, schema = step_assets(step, image=_llm.is_image(input_path))
    call_args = argparse.Namespace(**vars(args))
    call_args.task = step.task
    call_args.template = template
    call_args.schema = schema
    call_args.name = step.name
    call_args.extra = [
        *(args.extra or []),
        *(f"{key}={getattr(args, key)}" for key in step.requires),
    ]
    return call_args


def _run_step(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
    step: Step,
) -> Payload:
    """Run one step: the bench's own ``call``, filed under the step's own directory."""
    step_root = root / step.name
    step_root.mkdir(parents=True, exist_ok=True)
    return _llm.COMMANDS["call"](
        _call_arguments(args, step, input_path), parser, input_path, step_root
    )


def _step_report(step: Step, payload: Payload, root: Path, input_path: Path) -> Payload:
    """Summarize one finished step: its status, its answer, and where both were filed."""
    answer = root / step.name / f"{step.name}.json"
    return {
        "step": step.name,
        **_identifiers(step, input_path),
        "status": str(payload.get("status")),
        "schema_valid": payload.get("schema_valid"),
        "answer": str(answer) if answer.is_file() else None,
        "record": str(root / step.name / f"{step.name}_full.json"),
        "parsed_response": payload.get("parsed_response"),
    }


def _identifiers(step: Step, input_path: Path) -> Payload:
    """Return the template and the schema one step is run with, as the run's own record of them."""
    template, schema = step_assets(step, image=_llm.is_image(input_path))
    return {"template": template, "schema": schema}


def _flow_status(steps: list[Payload]) -> str:
    """Return the flow's own status: a failure in any step is the flow's failure."""
    failed = any(
        _cli.exit_code_for(report["status"]) == _cli.FAILURE_EXIT for report in steps
    )
    return "FAILED" if failed else "SUCCESS"


def _step_command(step: Step) -> Command:
    """Return the command that runs one step and reports it.

    Args:
        step: The step the command runs.

    Returns:
        One ``call``, with the step's identifiers, and the validity read out of it when the step is
        the one that answers it.
    """

    def command(
        args: argparse.Namespace,
        parser: argparse.ArgumentParser,
        input_path: Path,
        root: Path,
    ) -> Payload:
        payload = _run_step(args, parser, input_path, root, step)
        report: Payload = {
            "step": step.name,
            **_identifiers(step, input_path),
            **payload,
        }
        if step.name == DETECTION:
            report["invoice_valid"] = validity(payload.get("parsed_response"))
        return report

    return command


def _flow(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    input_path: Path,
    root: Path,
) -> Payload:
    """Run every step, in order, and report the flow.

    A step that returns a failed result does not end the run: the flow reports every step it ran,
    and the status it carries is the one a caller's exit code reads.
    """
    reports = [
        _step_report(
            step, _run_step(args, parser, input_path, root, step), root, input_path
        )
        for step in STEPS
    ]
    return {
        "input": str(input_path),
        "steps": reports,
        "status": _flow_status(reports),
        "invoice_valid": validity(
            next(
                (
                    report["parsed_response"]
                    for report in reports
                    if report["step"] == DETECTION
                ),
                None,
            )
        ),
    }


#: The methods by subcommand name. ``cli_invoice.py`` dispatches through this, so a step's
#: behaviour lives in exactly one place.
COMMANDS: dict[str, Command] = {
    **{step.name: _step_command(step) for step in STEPS},
    FLOW: _flow,
}
