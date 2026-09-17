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
from docflow.kernel_cli.main import Call, Handler
from docflow.kernels.types import Bytes, KernelResult

__all__: list[str] = []

#: Kernel name to the adapter class that answers for it. Data, not a branch: the two
#: kernels are the same port bound to two different providers, and `E04-07` already
#: established that the *family* is what differs.
LLM_BACKENDS: Final[dict[str, Callable[[], Any]]] = {
    "llm.local": OllamaEngine,
    "llm.frontier": FrontierEngine,
}


def _read(path: object, what: str) -> str:
    """Read a text file named by a flag.

    Args:
        path: The path, or None.
        what: The flag name, for the refusal.

    Returns:
        The file's text.

    Raises:
        ValueError: If the flag was not given. The prompt and the schema are the
            caller's to supply and are **never** synthesized here: a default schema
            would change what every answer means.

    """
    if path is None:
        raise ValueError(
            f"{what} is required: a prompt and a schema are the caller's to supply "
            "and are never defaulted (a synthesized schema would change what the "
            "answer means)."
        )
    return Path(str(path)).read_text(encoding="utf-8")


def _schema(path: object) -> dict[str, object]:
    """Read and parse a JSON schema file.

    Args:
        path: The path, or None.

    Returns:
        The parsed schema.

    Raises:
        ValueError: If the flag was not given or the file is not a JSON object.

    """
    parsed = json.loads(_read(path, "--schema-file"))
    if not isinstance(parsed, dict):
        raise ValueError(
            f"--schema-file must hold a JSON object at the top level, not "
            f"{type(parsed).__name__}."
        )
    return parsed


def _with_record(engine: Any, result: KernelResult[Any]) -> Call:
    """Attach the provider call's record to the result.

    Args:
        engine: The adapter, which exposes the last call's record.
        result: The kernel's result.

    Returns:
        The call, whose `call_record` is populated for K5 and K6 only.

    """
    return Call(result=result, call_record=engine.last_call_record)


def _capabilities(engine: Any, model: object) -> Call:
    """Answer `capabilities` for one model.

    Args:
        engine: The adapter.
        model: The model name.

    Returns:
        The call.

    Raises:
        ValueError: If no model was named.

    """
    if model is None:
        raise ValueError(
            "--model is required: a capability question is about a model, and this "
            "surface has no default one (kernel-cli.md §8 forbids a default model)."
        )
    return _with_record(engine, engine.capabilities(str(model)))


def _structured(engine: Any, model: object, prompt: object, schema: object) -> Call:
    """Answer `structured` for one model.

    Args:
        engine: The adapter.
        model: The model name.
        prompt: The prompt file.
        schema: The schema file.

    Returns:
        The call.

    Raises:
        ValueError: If a required flag is missing.

    """
    if model is None:
        raise ValueError("--model is required; there is no default model.")
    return _with_record(
        engine,
        engine.structured(str(model), _read(prompt, "--prompt-file"), _schema(schema)),
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
        The call.

    Raises:
        ValueError: If a required flag is missing.

    """
    if model is None:
        raise ValueError("--model is required; there is no default model.")
    if images is None:
        raise ValueError(
            "--image is required: a vision call with no image is a text call, and "
            "asking a vision endpoint for one would be a different operation."
        )
    loaded = [
        Bytes(data=Path(piece.strip()).read_bytes(), media_type="image/png")
        for piece in str(images).split(",")
        if piece.strip()
    ]
    return _with_record(
        engine,
        engine.vision(
            str(model), _read(prompt, "--prompt-file"), loaded, _schema(schema)
        ),
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
            The call.

        Raises:
            ValueError: If no model was named.

        """
        model = kwargs.get("model")
        if model is None:
            raise ValueError("--model is required; there is no default model.")
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
