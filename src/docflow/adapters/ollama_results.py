"""The boundary results one Ollama call produces, and the refusal's own words.

Split out of `ollama.py` when that module passed Pylint's 1000-line cap, for the same
reason `pdf_stable.py` was split out of `pdf.py`: the code below is a coherent group
that does not touch the transport, and moving it is cheaper than suppressing the rule.

What lives here is the **answer-shaped** end of one call:

- the four constructors that turn measurements and observations into the frozen
  boundary types (`Evidence`, `KernelResult`, `Reason`), which every success, every
  observed answer and every typed refusal goes through;
- the two small readers that decide what a term or a name means;
- :func:`runtime_complaint`, which quotes the runtime when it refuses a request.

That last one earned its place by fixing a misattribution. The adapter used to report
**every** non-200 as `model_unknown`, so the most common failure of all — a prompt too
large for `num_ctx` — was reported as *the model's name is not known*, for a model whose
`capabilities` call had just succeeded. Measured: a 167 035-character prompt against
`num_ctx: 4096` answers HTTP 400 with

    {"error": "{\\"error\\":{\\"code\\":400,\\"message\\":\\"request (38187 tokens)
                exceeds the available context size (4096 tokens)…\\"…}}"}

— the message is **nested twice, with the inner document JSON-encoded as a string**.
Quoting it is what lets a reader see the oversized prompt instead of looking for a
missing model.

Nothing here decides a behaviour: no branch reads an error type, no field selects a
path. The runtime's words are quoted and the adapter's own codes are chosen by the
*status*, so what a caller sees is the runtime's explanation rather than this module's
interpretation of it.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from docflow.kernels.types import Evidence, KernelResult, Reason

__all__: list[str] = [
    "evidence",
    "observed",
    "refused",
    "runtime_complaint",
    "same_model",
    "terms",
]


def same_model(left: str, right: str) -> bool:
    """Report whether two model names denote the same model.

    Tags are ignored: ``qwen2.5`` and ``qwen2.5:latest`` are the same model to the
    runtime, and a self-grading guard that missed that would be defeated by a tag.

    Args:
        left: One model name.
        right: The other.

    Returns:
        ``True`` when the bare names match.

    """
    return left.split(":")[0].strip() == right.split(":")[0].strip()


def terms(model: str, digest: str, adapter_revision: str = "") -> Mapping[str, str]:
    """Report the cache-key terms for one model.

    Args:
        model: The name the caller used.
        digest: The resolved digest.
        adapter_revision: The runtime's build, e.g. ``"ollama 0.31.1"``. Empty
            omits the term, which the paths that fire before the runtime is known
            (a typed refusal) rely on.

    Returns:
        The terms. The **digest** is the model's identity, and the tag is recorded
        beside it so an operator can see which name produced the run.

    """
    reported = {"model": model, "model_revision": digest}
    if adapter_revision:
        reported["adapter_revision"] = adapter_revision

    return MappingProxyType(reported)


def runtime_complaint(response: Any) -> str:
    """Quote what the runtime said about a request it refused.

    **The message is nested twice, measured.** Ollama answers a refused request with
    ``{"error": "<json as a string>"}`` — the inner document carries the code, the
    message and the token counts.

    So the outer object is unpeeled **only far enough to get a readable sentence**, and
    nothing is interpreted: no branch on the error type, no field read to decide a
    behaviour. A caller reading the refusal gets the runtime's own words, which is what
    lets them see *the prompt is too big* instead of a code this adapter invented.

    Args:
        response: The response object.

    Returns:
        The runtime's explanation, or a note that it sent nothing readable. Never an
        empty string: *it explained itself* and *it did not* are different facts.

    """
    text = getattr(response, "text", None)
    if not isinstance(text, str) or not text.strip():
        return "(the runtime sent no readable body)"

    try:
        outer = json.loads(text)
    except ValueError:
        return " ".join(text.split())[:300]

    message = text
    if isinstance(outer, dict) and isinstance(outer.get("error"), str):
        inner = outer["error"]
        try:
            parsed = json.loads(inner)
        except ValueError:
            message = inner
        else:
            nested = parsed.get("error") if isinstance(parsed, dict) else None
            message = (
                str(nested.get("message"))
                if isinstance(nested, dict) and nested.get("message")
                else inner
            )

    return " ".join(str(message).split())[:300]


def evidence(
    reported_terms: Mapping[str, str],
    measurements: Mapping[str, float],
    observed_values: Mapping[str, object],
) -> Evidence:
    """Build an evidence record.

    Args:
        reported_terms: The cache-key terms.
        measurements: The numeric measurements.
        observed_values: The remaining observations.

    Returns:
        The assembled ``Evidence``.

    """
    return Evidence(
        terms=MappingProxyType(dict(reported_terms)),
        measurements=MappingProxyType(dict(measurements)),
        observed=MappingProxyType(dict(observed_values)),
    )


def observed(
    reported_terms: Mapping[str, str],
    measurements: Mapping[str, float],
    observed_values: Mapping[str, object],
) -> KernelResult[Evidence]:
    """Build a successful result whose value is the observation record.

    Args:
        reported_terms: The cache-key terms.
        measurements: The numeric measurements.
        observed_values: The remaining observations.

    Returns:
        A ``KernelResult`` carrying the evidence as its value.

    """
    record = evidence(reported_terms, measurements, observed_values)

    return KernelResult(value=record, evidence=record, reason=None)


def refused(
    code: str,
    message: str,
    reported_terms: Mapping[str, str],
    measurements: Mapping[str, float],
    observed_values: Mapping[str, object],
) -> KernelResult[Any]:
    """Build a failed result that still carries what was observed.

    Args:
        code: The reason code.
        message: The human-readable explanation.
        reported_terms: The cache-key terms.
        measurements: The measurements taken.
        observed_values: The remaining observations.

    Returns:
        A ``KernelResult`` with no value and the evidence attached.

    """
    return KernelResult(
        value=None,
        evidence=evidence(reported_terms, measurements, observed_values),
        reason=Reason(code=code, message=message),
    )
