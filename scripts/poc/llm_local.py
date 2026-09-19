"""Direct probes of the K5 `llm.local` adapter, one method per requirement.

`my_kernel_flow.md` §4 asks for two things of the `llm.local` kernel:

> - models **without** vision: send the text the OCR produced, plus a prompt, to
>   extract fields;
> - models **with** vision: send the appropriate image, plus a prompt, so the model
>   reads the field values off the pixels.

Those are `structured` and `vision`, and both are on `LlmEngine`. B1 and B2 below
call them.

The images are passed as the boundary's `Bytes`, which is what the port declares
(`LlmEngine.vision(..., images: Sequence[Bytes], ...)`). **A path does not work**,
and B4 shows why in the two different ways it fails - one loud, one silent.

Run it with no arguments:

    python scripts/poc/llm_local.py

Every call here is a real generation against a local runtime, so expect a few
seconds per probe. Nothing is sent to a paid provider.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys
from collections.abc import Mapping

import _lib

# `docflow` is only importable once `src/` is on the path; see `pdf.py` for why
# the ordering of these two imports is load-bearing.
_lib.bootstrap()

from docflow.adapters.ollama import OllamaEngine  # noqa: E402 - see the note above
from docflow.kernels.types import Bytes  # noqa: E402 - see the note above

__all__: list[str] = []

#: The text-only model. A small instruct model, so a probe is a couple of seconds
#: rather than a couple of minutes. **`deepseek-r1:1.5b` and not `smollm2:latest`**,
#: and the reason is measured rather than a preference:
#:
#: - **`smollm2` runs away.** On `chicos/22f0e9af-…-p1.txt` (1 589 bytes - *not*
#:   large, so input size is not the trigger) it intermittently enters an unbounded
#:   repetition loop, emitting digits for as long as it is allowed. A batch driver is
#:   **sequential** and the adapter's per-call ceiling is 600 s, so one runaway stalls
#:   the whole run with no output between files - which is what a hang looks like.
#:   Measured: 1 runaway in 5 calls with no token ceiling.
#: - **`deepseek-r1:1.5b` answered every one of 10 consecutive calls on that same
#:   file**, 4.1-10.6 s each (`done_reason: 'stop'`). A repeating generation there is
#:   bounded by the context, and the model stops on its own.
#: - **And it fails LOUDLY where `smollm2` fails silently.** An oversized prompt is
#:   refused with `HTTP 400 exceed_context_size_error` (`n_prompt_tokens` vs `n_ctx`
#:   both named), instead of being dropped past the window's edge with
#:   `done_reason: 'stop'`. That does not retire `prompt_was_cut` below - the silent
#:   cut is a property of the *runtime and the model*, and `smollm2` still has it -
#:   but it does mean the default no longer depends on that detector to be safe.
#:   `deepseek-r1` declares `completion` and `thinking`, so it emits reasoning
#:   tokens; they were measured to stay inside the schema-constrained channel.
TEXT_MODEL: str = "deepseek-r1:1.5b"

#: The vision model. Both are named as the caller names them, which is the whole
#: point of the tag: `qwen2.5vl` is a moving tag, and the digest is the identity.
VISION_MODEL: str = "qwen2.5vl:3b"

#: A field schema, of the shape the flow's `p` (prompt) mode needs. Supplied by the
#: caller, never synthesised here - the schema goes to the runtime's `format` field
#: to constrain generation.
INVOICE_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {"total": {"type": "integer"}, "cuit": {"type": "string"}},
    "required": ["total", "cuit"],
    "additionalProperties": False,
}

#: The prompt for the text path. It carries the OCR text, which is exactly the
#: handoff the flow describes.
TEXT_PROMPT: str = (
    "Extract the total amount and the CUIT from this invoice text.\n\n"
    "KALPA GROUP S.A. C.U.I.T. Nro.: 30-71548265-3 Total: 1500.00"
)

#: The prompt for the vision path - higher level, and about the pixels rather than
#: about a transcription of them.
VISION_PROMPT: str = "Describe the document in this image in one short sentence."

_VISION_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {"description": {"type": "string"}},
    "required": ["description"],
    "additionalProperties": False,
}


def _engine() -> OllamaEngine:
    """Build the K5 adapter.

    Returns:
        The engine, ready to call.

    """
    return OllamaEngine()


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


# --- What the engine has ----------------------------------------------------


def capabilities(engine: OllamaEngine, model: str, expect: str) -> None:
    """Report a model's identity, which is the cache key's *model revision*.

    The digest and not the tag: `qwen2.5vl` moves, and a stored artifact is only
    reproducible against the revision that produced it (`sad.md` §5).

    Args:
        engine: The K5 adapter.
        model: The model as the caller names it.
        expect: The bucket this probe is declared to land in.

    """
    attempt = _lib.run(
        f"llm_local.capabilities[{model}]", engine.capabilities, model, expect=expect
    )
    if attempt.succeeded:
        print(f"         terms={dict(attempt.result.evidence.terms)}")


# --- Requirement 1: text + prompt -> fields ---------------------------------


def extract_from_text(
    engine: OllamaEngine,
    model: str,
    expect: str,
    prompt: str | None = None,
    schema: Mapping[str, object] | None = None,
) -> _lib.Attempt:
    """Ask a text-only model for structured fields out of OCR text.

    Returns the attempt rather than nothing, so a batch caller reuses this call's
    value instead of paying for a second generation.

    A caller with a document of its own passes **both** the prompt and the schema:
    defaulting either to this driver's invoice fixture would answer a question about
    a fixture while reporting on a real document.

    Args:
        engine: The K5 adapter.
        model: The model as the caller names it.
        expect: The bucket this probe is declared to land in.
        prompt: The prompt to send, defaulting to the driver's own fixture text. A
            batch caller passes the text it just extracted from a document, which
            is the handoff `my_kernel_flow.md` §6 describes.
        schema: The schema the generation is constrained by, defaulting to the
            invoice fixture above.

    Returns:
        The attempt, carrying the fields the probe described.

    """
    attempt = _lib.run(
        f"llm_local.structured[{model}]",
        engine.structured,
        model,
        TEXT_PROMPT if prompt is None else prompt,
        INVOICE_SCHEMA if schema is None else schema,
        expect=expect,
    )
    if not attempt.succeeded:
        return attempt

    observed = attempt.result.evidence.observed
    print(f"         value={dict(attempt.result.value)}")
    print(
        f"         done_reason={observed.get('done_reason')!r} "
        f"num_ctx={observed.get('num_ctx')!r} vision={observed.get('vision')!r}"
    )
    report_prompt_window(attempt.result.evidence.measurements)
    return attempt


def report_prompt_window(measurements: Mapping[str, object]) -> None:
    """Print the prompt's sent length and its evaluated length side by side.

    The runtime truncates an oversized prompt and reports nothing: it answers
    `done_reason: 'stop'` with a plausible value, so *whether the cut surfaces at
    all* depends on the window, which is what makes it silent.

    **These two numbers live in `measurements`, not in `observed`.** This function
    read the wrong mapping and returned early on every call, so the disagreement it
    exists to expose was never printed - a check that looks like a check and reports
    nothing.

    The two numbers are printed **raw, with no ratio and no threshold**, because
    neither could be honest here:

    - a ratio is not available, because they do not measure the same thing.
      `prompt_characters` counts the prompt text; `prompt_tokens` counts what the
      engine evaluated, which includes the schema and the chat template. Measured:
      36 characters evaluate 47 tokens, and the vision call's 730 456 characters
      (the base64 image rides in the prompt) evaluate 3 896 - so a
      characters-per-token figure would differ wildly between two runs that were
      both cut normally.
    - a threshold would be a decision against the loaded window (`num_ctx`), and
      inventing one in a bench is the class of error `prd.md` FR-15 forbids in a
      kernel.

    **The signal is the plateau, and it is a comparison across calls.** Measured on
    `smollm2` at `num_ctx=4096`: 6 420 characters evaluate 2 050 tokens, 32 020
    evaluate 2 050, and 128 020 evaluate **the same 2 050** while `done_reason`
    stays `'stop'`. One call cannot be read on its own; two can.

    Args:
        measurements: The call's numeric evidence.

    """
    sent = measurements.get("prompt_characters")
    evaluated = measurements.get("prompt_tokens")
    if sent is None and evaluated is None:
        return
    print(f"         prompt sent={sent} chars, evaluated={evaluated} tokens")


# --- Requirement 2: image + prompt -> fields --------------------------------


def extract_from_image(
    engine: OllamaEngine,
    model: str,
    expect: str,
    prompt: str | None = None,
    schema: Mapping[str, object] | None = None,
    images: list[Bytes] | None = None,
) -> _lib.Attempt:
    """Ask a vision model for structured fields read off the pixels.

    Returns the attempt rather than nothing, so a batch caller reuses this call's
    value instead of paying for a second generation - and a generation against a
    vision model is the most expensive call this bench makes.

    Args:
        engine: The K5 adapter.
        model: The model as the caller names it.
        expect: The bucket this probe is declared to land in.
        prompt: The prompt to send, defaulting to the driver's own fixture text.
        schema: The schema the generation is constrained by, defaulting to the
            fixture's single-description schema.
        images: The images to send, defaulting to the committed case fixture. They
            must be `Bytes` - a path is accepted by the encoder and silently
            encodes the **file name**, which `payload_types` below demonstrates.

    Returns:
        The attempt, carrying the fields the probe described.

    """
    attempt = _lib.run(
        f"llm_local.vision[{model}]",
        engine.vision,
        model,
        VISION_PROMPT if prompt is None else prompt,
        [_image(_lib.CASE_IMAGE)] if images is None else images,
        _VISION_SCHEMA if schema is None else schema,
        expect=expect,
    )
    if not attempt.succeeded:
        return attempt

    observed = attempt.result.evidence.observed
    print(f"         value={dict(attempt.result.value)}")
    print(
        f"         vision={observed.get('vision')!r} "
        f"done_reason={observed.get('done_reason')!r}"
    )
    report_prompt_window(attempt.result.evidence.measurements)
    return attempt


# --- The failure modes ------------------------------------------------------


def warm(engine: OllamaEngine, model: str, expect: str) -> None:
    """Load a model ahead of a real call.

    `warm` must send the **same options** a real call will, or it loads the model
    only for the first real call to reload it - which is the cold start warming
    exists to avoid.

    Args:
        engine: The K5 adapter.
        model: The model as the caller names it.
        expect: The bucket this probe is declared to land in.

    """
    _lib.run(f"llm_local.warm[{model}]", engine.warm, model, expect=expect)


def missing_model(engine: OllamaEngine) -> None:
    """Ask for a model that is not pulled, and confirm the refusal names the remedy.

    `model_not_pulled` and `model_unknown` are different statements, and only the
    adapter knows which it is looking at. Neither substitutes a default - that is
    the failure this layer's own invariant calls the worst it can have.

    Args:
        engine: The K5 adapter.

    """
    attempt = _lib.run(
        "llm_local.structured[absent model]",
        engine.structured,
        "definitely-not-pulled:latest",
        TEXT_PROMPT,
        INVOICE_SCHEMA,
        expect="precondition",
    )
    if not attempt.succeeded:
        reason = attempt.result.reason if attempt.result is not None else None
        print(f"         {str(reason.message)[:110] if reason else '(raised)'}")


def truncation(engine: OllamaEngine) -> None:
    """Provoke a generation cut short and confirm it is never parsed as complete.

    The cut is forced with a tiny `num_predict` - the same `done_reason: 'length'`
    signal an oversized prompt produces, without needing a prompt large enough to
    overflow a 128k window as a committed fixture. A cut that happens to land after
    the last complete field would otherwise parse cleanly, which is how a partial
    answer is mistaken for a whole one.

    Args:
        engine: The K5 adapter.

    """
    os.environ["DOCFLOW_OLLAMA_NUM_PREDICT"] = "8"
    try:
        attempt = _lib.run(
            "llm_local.truncated_output",
            engine.structured,
            TEXT_MODEL,
            TEXT_PROMPT,
            INVOICE_SCHEMA,
            expect="reason",
        )
        if attempt.result is not None and attempt.result.reason is not None:
            print(f"         {str(attempt.result.reason.message)[:150]}")
    finally:
        del os.environ["DOCFLOW_OLLAMA_NUM_PREDICT"]


def payload_types(engine: OllamaEngine) -> None:
    """Show what the vision path accepts, and how three of the four forms fail.

    The port declares `Sequence[Bytes]`, and that is the form that works. The
    adapter's own encoder documents *"a `Bytes` value, or a path, or bytes"* - and a
    path does not work, in two different ways:

    - a **`str` path** raises `TypeError` out of the adapter, which through the CLI
      would be exit `1` (a traceback) rather than a typed refusal;
    - a **`Path` object** is silently accepted, because `bytes(path)` is satisfied
      by the string repr - so the model receives the base64 of *the file name*.

    The second is the dangerous one, and it is the class of failure this project
    exists to catch: no error, a plausible-looking answer, and nothing in the result
    that says the pixels were never sent.

    Args:
        engine: The K5 adapter.

    """
    from docflow.adapters.ollama import _encode_image

    p = _lib.CASE_IMAGE
    for label, value in (
        ("Bytes (the port's type)", _image(p)),
        ("raw bytes", p.read_bytes()),
        ("str path", str(p)),
        ("Path object", p),
    ):
        try:
            encoded = _encode_image(value)
            print(f"      {label:26} accepted, {len(encoded)} base64 chars")
        except Exception as exc:  # the failure mode IS the finding
            print(f"      {label:26} {type(exc).__name__}: {exc}")

    _lib.note(
        "llm_local.payload",
        "Bytes works; a str path raises; a Path silently encodes the FILE NAME",
    )


def oversized_prompt(engine: OllamaEngine, model: str) -> None:
    """Show a prompt the window cannot hold being cut **without a word**.

    The runtime answers `done_reason: 'stop'` and a plausible value, so nothing in
    the result says the prompt was shortened - the only signal is that
    `prompt_tokens` **stops growing** while `prompt_characters` keeps climbing. Both
    numbers are printed for a small prompt and a large one so the plateau is a
    measurement rather than a claim.

    Measured on `smollm2` at `num_ctx=4096`: 6 420 characters evaluate 2 050 tokens,
    and a **128 020-character** prompt evaluates the same 2 050. A batch that hands
    this kernel a whole document's text is therefore reading an answer to a question
    about the document's **beginning**, and nothing returns an error.

    This is the third silent failure K5 has, after the `Path`-that-encodes-a-file-name
    in `payload_types` and the missing `num_ctx` before a load. It is recorded rather
    than fixed: a fix means deciding how to fit a document into a window, and that is
    a Stage 2 question (`S2-T09`'s escalation ladder), not a bench's.

    Args:
        engine: The K5 adapter.
        model: The model as the caller names it.

    """
    for label, repeats in (("small", 1), ("large", 8000)):
        text = f"Extract the total.\n\n{'Total: 1500.00. ' * repeats}"
        attempt = _lib.run(
            f"llm_local.oversized_prompt[{label}]",
            engine.structured,
            model,
            text,
            INVOICE_SCHEMA,
        )
        if attempt.result is None or attempt.result.evidence is None:
            continue
        measured = attempt.result.evidence.measurements
        observed = attempt.result.evidence.observed
        print(
            f"      {label:6} {len(text):>7} chars sent -> "
            f"done_reason={observed.get('done_reason')!r} "
            f"value={dict(attempt.result.value) if attempt.result.value else None}"
        )
        report_prompt_window(measured)

    _lib.note(
        "llm_local.oversized_prompt",
        "a prompt past the window is cut silently: done_reason stays 'stop', and "
        "prompt_tokens plateaus while prompt_characters grows",
    )


# --- The run ----------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Run every `llm_local` probe and tally the result.

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

    print(f"text model   = {TEXT_MODEL}")
    print(f"vision model = {VISION_MODEL}")
    print()

    # Both identities, which is what a stored artifact is reproducible against.
    capabilities(engine, TEXT_MODEL, "ok")
    capabilities(engine, VISION_MODEL, "ok")

    print()
    # The flow's two requirements.
    extract_from_text(engine, TEXT_MODEL, "ok")
    extract_from_image(engine, VISION_MODEL, "ok")

    print()
    # The failure modes, each asserted as an answer rather than a crash.
    warm(engine, TEXT_MODEL, "ok")
    missing_model(engine)
    truncation(_engine())

    print()
    # The silent one: a prompt the window cannot hold, answered anyway.
    oversized_prompt(engine, TEXT_MODEL)

    print()
    # What the vision path accepts.
    payload_types(engine)

    print()
    return _lib.summary()


if __name__ == "__main__":
    sys.exit(main())
