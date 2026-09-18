"""K5 and K6's commands - `llm.local` and `llm.frontier` (`E07-02` / `S1-T21`).

One module for the two, because they implement the **same port** with the same five
operations. The only differences are the class bound and the adapter name, and both
are data in :data:`LLM_BACKENDS` rather than a branch.

Four `now` commands each. Rows 12, 13 and 14 of the matrix live here: truncation must
be a typed reason and never a parsed partial; a model swapped under a moving tag must
show up as a digest difference; and the absence / `null` / present distinction must
stay three outcomes.

`call_record` is populated for both, and it is the one thing the envelope carries
that no other kernel's does (`kernel-cli.md` §6). `E04-06` records why it reaches the
envelope through a *property* on the adapter rather than a port member: `E01` froze
`KernelResult` at three fields, and the port must not grow a method.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Final

from docflow.adapters.frontier import FrontierEngine
from docflow.adapters.ollama import OllamaEngine
from docflow.kernel_cli.commands.refusals import missing
from docflow.kernel_cli.main import Call, Handler, UsageError
from docflow.kernels.types import Bytes, KernelResult

__all__: list[str] = []

#: Why `--model` has no default, quoted in the refusal rather than a bare *"required"*.
#: A caller reading it learns the rule, not only that they broke it.
_NO_DEFAULT_MODEL: Final[str] = (
    "a model has to be named, because this surface has no default one "
    "(kernel-cli.md §8 forbids a default model). "
    "A default here would be the surface choosing which model read the document."
)

#: The same for the two file flags the LLM calls take. Neither is synthesized: a
#: default schema would change what every answer means.
_PROMPT_IS_THE_CALLERS: Final[str] = (
    "the prompt is the caller's to supply and is never defaulted."
)
_SCHEMA_IS_THE_CALLERS: Final[str] = (
    "the schema is the caller's to supply and is never defaulted (a synthesized "
    "schema would change what every answer means)."
)

#: Why a vision call needs an image, quoted in the refusal.
_IMAGE_IS_REQUIRED: Final[str] = (
    "a vision call with no image is a text call, and asking a vision endpoint for "
    "one would be a different operation."
)


#: Kernel name to the adapter class that answers for it. Data, not a branch: the two
#: kernels are the same port bound to two different providers, and `E04-07` already
#: established that the *family* is what differs.
LLM_BACKENDS: Final[dict[str, Callable[[], Any]]] = {
    "llm.local": OllamaEngine,
    "llm.frontier": FrontierEngine,
}


def _omitted(value: object, flag: str, because: str) -> KernelResult[Any] | None:
    """Return the refusal for an omitted required flag, or ``None`` when it was given.

    A flag the caller did not supply is *"the call could not legitimately be made"* -
    exit ``3`` - and not a malformed invocation, because the flag itself is legal and
    the command is spelled correctly. That is the same reading `store ls` already
    makes for an absent `--root`, and the two would be one class of error answered two
    ways if this raised instead.

    Args:
        value: The parsed flag, or None when it was not given.
        flag: The flag's name, for the message.
        because: Why the call cannot proceed without it.

    Returns:
        The refusal, or None when the flag was supplied.

    """
    if value is None:
        return missing(f"{flag} is required: {because}")
    return None


def _first_refusal(*candidates: KernelResult[Any] | None) -> Call | None:
    """Return the first refusal among ``candidates``, wrapped in a call, or ``None``.

    The order is the order they are passed, so the refusal a caller sees names the
    flag the command reads *first* rather than whichever check happened to run last.

    Args:
        *candidates: The refusals, in the order they should be reported.

    Returns:
        The call carrying the first refusal, or None when nothing was omitted.

    """
    for candidate in candidates:
        if candidate is not None:
            return Call(result=candidate)
    return None


def _read(path: object) -> str:
    """Read a text file the caller named.

    Args:
        path: The path, already checked to be present by the caller's guard.

    Returns:
        The file's text.

    """
    return Path(str(path)).read_text(encoding="utf-8")


def _schema(path: object) -> dict[str, object]:
    """Read and parse a JSON schema file.

    Args:
        path: The path, already checked to be present.

    Returns:
        The parsed schema.

    Raises:
        UsageError: If the file does not hold a JSON object. The caller wrote the
            file, so a malformed one is theirs to fix - exit ``4``, not ``1``.

    """
    parsed = json.loads(_read(path))
    if not isinstance(parsed, dict):
        raise UsageError(
            f"--schema-file must hold a JSON object at the top level, not "
            f"{type(parsed).__name__}."
        )
    return parsed


def _with_record(engine: Any, result: KernelResult[Any]) -> Call:
    """Attach the provider call's record to the result, when the adapter has one.

    **`call_record` is K6's, not the port's.** `E04-06` recorded the delta: `E01` froze
    `KernelResult` at three fields, so the adapter exposes the record and the raw
    completion as *properties* rather than growing the frozen type or adding a method to
    the port. `K6` is the adapter that has them; `K5` is the port's *other*
    implementation and exposes neither, because an Ollama call has no provider-side
    revision, no token accounting and no cost to report.

    Reading it with `getattr` rather than assuming it is therefore the honest
    construction, and `None` is the accurate answer for K5 rather than a stand-in: the
    envelope's `call_record` key is fixed by `kernel-cli.md` section 6 and is null for
    every kernel that made no provider call - which is exactly what K5 is.

    Args:
        engine: The adapter, which may or may not carry a record.
        result: The kernel's result.

    Returns:
        The call, whose `call_record` is populated for an adapter that has one.

    """
    record = getattr(engine, "last_call_record", None)
    return Call(result=result, call_record=record)


def _capabilities(engine: Any, model: object) -> Call:
    """Answer `capabilities` for one model.

    Args:
        engine: The adapter.
        model: The model name.

    Returns:
        The call, or the typed refusal when no model was named.

    """
    refused = _omitted(model, "--model", _NO_DEFAULT_MODEL)
    if refused is not None:
        return Call(result=refused)
    return _with_record(engine, engine.capabilities(str(model)))


def _structured(engine: Any, model: object, prompt: object, schema: object) -> Call:
    """Answer `structured` for one model.

    Args:
        engine: The adapter.
        model: The model name.
        prompt: The prompt file.
        schema: The schema file.

    Returns:
        The call, or the typed refusal naming the first flag that was omitted.

    """
    refused = _first_refusal(
        _omitted(model, "--model", _NO_DEFAULT_MODEL),
        _omitted(prompt, "--prompt-file", _PROMPT_IS_THE_CALLERS),
        _omitted(schema, "--schema-file", _SCHEMA_IS_THE_CALLERS),
    )
    if refused is not None:
        return refused
    return _with_record(
        engine,
        engine.structured(str(model), _read(prompt), _schema(schema)),
    )


def _vision(
    engine: Any, model: object, prompt: object, images: object, schema: object
) -> Call:
    """Answer `vision` for one model.

    Args:
        engine: The adapter.
        model: The model name.
        prompt: The prompt file.
        images: The image path, or a comma-separated list of them.
        schema: The schema file.

    Returns:
        The call, or the typed refusal naming the first flag that was omitted.

    """
    refused = _first_refusal(
        _omitted(model, "--model", _NO_DEFAULT_MODEL),
        _omitted(images, "--image", _IMAGE_IS_REQUIRED),
        _omitted(prompt, "--prompt-file", _PROMPT_IS_THE_CALLERS),
        _omitted(schema, "--schema-file", _SCHEMA_IS_THE_CALLERS),
    )
    if refused is not None:
        return refused
    loaded = [
        Bytes(data=Path(piece.strip()).read_bytes(), media_type="image/png")
        for piece in str(images).split(",")
        if piece.strip()
    ]
    return _with_record(
        engine,
        engine.vision(str(model), _read(prompt), loaded, _schema(schema)),
    )


def _make(kernel: str) -> dict[str, Handler]:
    """Build the handler set for one LLM kernel.

    Args:
        kernel: The kernel's name, which selects the adapter.

    Returns:
        Operation name to handler.

    """
    build = LLM_BACKENDS[kernel]

    def capabilities(**kwargs: object) -> Call:
        """Report the model's capabilities.

        Args:
            **kwargs: The parsed parameters.

        Returns:
            The call.

        """
        return _capabilities(build(), kwargs.get("model"))

    def warm(**kwargs: object) -> Call:
        """Load the model with the options a real call will use.

        Args:
            **kwargs: The parsed parameters.

        Returns:
            The call, or the typed refusal when no model was named.

        """
        model = kwargs.get("model")
        refused = _omitted(model, "--model", _NO_DEFAULT_MODEL)
        if refused is not None:
            return Call(result=refused)
        engine = build()
        return _with_record(engine, engine.warm(str(model)))

    def structured(**kwargs: object) -> Call:
        """Ask for a structured answer.

        Args:
            **kwargs: The parsed parameters.

        Returns:
            The call.

        """
        return _structured(
            build(),
            kwargs.get("model"),
            kwargs.get("prompt_file"),
            kwargs.get("schema_file"),
        )

    def vision(**kwargs: object) -> Call:
        """Ask for a structured answer about images.

        Args:
            **kwargs: The parsed parameters.

        Returns:
            The call.

        """
        return _vision(
            build(),
            kwargs.get("model"),
            kwargs.get("prompt_file"),
            kwargs.get("image"),
            kwargs.get("schema_file"),
        )

    handlers = {
        "capabilities": capabilities,
        "warm": warm,
        "structured": structured,
        "vision": vision,
    }
    if kernel == "llm.frontier":
        # `judge` is `MVP` for now and exits 4 (kernel-cli.md §9). The handler is
        # deliberately absent rather than a stub: it is the operation matrix row 15
        # waits on, and the row asserts on `role_conflict` the moment it lands.
        handlers["judge"] = None  # type: ignore[assignment]
    else:
        handlers["ps"] = None  # type: ignore[assignment]
        handlers["pull"] = None  # type: ignore[assignment]
        handlers["generate"] = None  # type: ignore[assignment]
    return handlers


#: The two kernels' command sets, as ``(operation, handler, positional, flags)``.
#: Both implement the same port, so their command sets differ only in which `MVP`
#: operations are not yet implemented: `judge` for K6, `ps`/`pull`/`generate` for K5.
_LOCAL: Final[dict[str, Handler | None]] = _make("llm.local")
_FRONTIER: Final[dict[str, Handler | None]] = _make("llm.frontier")

COMMANDS: Final[
    dict[str, tuple[tuple[str, Handler | None, str, tuple[str, ...]], ...]]
] = {
    "llm.local": (
        ("capabilities", _LOCAL["capabilities"], "", ("--model",)),
        ("warm", _LOCAL["warm"], "", ("--model",)),
        (
            "structured",
            _LOCAL["structured"],
            "",
            ("--model", "--prompt-file", "--schema-file"),
        ),
        (
            "vision",
            _LOCAL["vision"],
            "",
            ("--model", "--prompt-file", "--image", "--schema-file"),
        ),
        ("ps", None, "", ("--model",)),
        ("pull", None, "", ("--model",)),
        ("generate", None, "", ("--model", "--prompt-file")),
    ),
    "llm.frontier": (
        ("capabilities", _FRONTIER["capabilities"], "", ("--model",)),
        ("warm", _FRONTIER["warm"], "", ("--model",)),
        (
            "structured",
            _FRONTIER["structured"],
            "",
            ("--model", "--prompt-file", "--schema-file"),
        ),
        (
            "vision",
            _FRONTIER["vision"],
            "",
            ("--model", "--prompt-file", "--image", "--schema-file"),
        ),
        ("judge", None, "", ("--model", "--rubric-file", "--samples-file")),
        ("count-tokens", None, "", ("--model", "--text-file")),
    ),
}
