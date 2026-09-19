"""Shared reporting for the direct-to-adapter probes in `scripts/poc/`.

These scripts call the **adapters** directly, by Python, without going through
`docflow-kernel`. That is the point: the lab CLI adds a surface of its own -
swallowed flags, delivery names, exit-code translation - and when a command
misbehaves the CLI cannot say whether the defect is in the adapter or in the
surface above it. A probe that reaches the adapter isolates the layer.

The reporting contract mirrors `scripts/kernel/_lib.sh`, deliberately:

1. **Exit codes are reported, not judged.** A reason is an *answer*, not a
   failure. `illegible` and `blank_page` are what the document is; only an
   unhandled exception is a defect.
2. **The summary comes from the envelope, never from the text.** Messages are
   prose that changes between revisions; `value`, `reason.code` and
   `measurements` are the contract.

Two differences from the shell drivers, both forced rather than chosen:

- **There is no exit code here.** A library call returns a `KernelResult`, so the
  bucket is derived from `reason.code` against the same closed set
  `kernel-cli.md` §5 maps to exits 2 and 3. A raised `ValueError` is the library's
  equivalent of exit 4 and is bucketed as ``usage``.
- **The envelope is never serialised.** `Evidence` carries `MappingProxyType`,
  which `json.dumps` refuses, and encoding the envelope is `S1-T20`'s job - a
  probe that invented its own encoder would be a second source of truth. So the
  reporter *describes* a value and never dumps it.

This module imports **standard library only**, and that is a constraint rather
than a coincidence: it has to be importable before `docflow` is on `sys.path`, so
it cannot import `docflow`. Values are therefore recognised structurally - by the
members they carry - not by `isinstance` against a boundary type.
"""

from __future__ import annotations

import dataclasses
import json
import pathlib
import sys
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Final

__all__: list[str] = [
    "BUCKETS",
    "FIXTURES",
    "OUTCOMES",
    "Outcome",
    "bootstrap",
    "note",
    "policy",
    "reset",
    "run",
    "save_bytes",
    "save_text",
    "set_out",
    "summary",
]

# --- The workspace ----------------------------------------------------------

#: The repository root, derived from this file's own location so a probe works
#: from any working directory.
ROOT: Final[pathlib.Path] = pathlib.Path(__file__).resolve().parents[2]

#: The physical package root. The import is `docflow.…`; this is where it lives.
SRC: Final[pathlib.Path] = ROOT / "src"

#: The corpus policy asset. A threshold is never a constant in a probe: `ADR-009`
#: puts it in the registry with no override, and a hardcoded one here would make
#: the probe disagree with every other caller.
POLICY_ASSET: Final[pathlib.Path] = ROOT / "registry" / "policies" / "thresholds.json"

#: Committed fixtures. Each is named for the failure it provokes.
FIXTURES: Final[pathlib.Path] = ROOT / "tests" / "fixtures"

#: The fixtures the probes name, so eight drivers do not each spell out a path.
TEXT_PDF: Final[pathlib.Path] = (
    FIXTURES / "pdf_aptos_layout" / "242823d2-afd3-4107-a49c-ce382592c6a5.pdf"
)
SCAN_PDF: Final[pathlib.Path] = (
    FIXTURES / "pdf_escaneados" / "3ac5a2ec-d129-47c0-947a-4680c7e25f06.pdf"
)
LARGE_PDF: Final[pathlib.Path] = FIXTURES / "pdf_large" / "MetodoCITRA17-APL.pdf"
BLUR_IMAGE: Final[pathlib.Path] = FIXTURES / "blur" / "image.jpg"
CASE_IMAGE: Final[pathlib.Path] = (
    FIXTURES / "casos" / "66e6e0ea-e910-41f4-9037-13f0309812c1.jpg"
)
SOURCE_PDF: Final[pathlib.Path] = (
    FIXTURES / "casos" / "66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.pdf"
)

#: Where a probe writes bytes and text unless `--out` says otherwise. Under
#: `var/`, which `.gitignore` already covers.
DEFAULT_OUT: Final[pathlib.Path] = ROOT / "var" / "poc"

_OUT: pathlib.Path = DEFAULT_OUT


def bootstrap() -> None:
    """Put `src/` on `sys.path` so `import docflow` resolves.

    Called explicitly by each driver **before** it imports `docflow`, because
    `pyproject.toml`'s `pythonpath = ["src"]` applies to `pytest` and to nothing
    else. Idempotent, so calling it twice is harmless.
    """
    text = str(SRC)
    if text not in sys.path:
        sys.path.insert(0, text)


def set_out(path: pathlib.Path) -> None:
    """Point the probes' output at `path`, creating it if absent.

    Args:
        path: The directory bytes and extracted text are written to.

    """
    global _OUT  # one process-wide root, set once by `main`.
    _OUT = path
    _OUT.mkdir(parents=True, exist_ok=True)


# --- Corpus policy ----------------------------------------------------------


def policy(key: str) -> Any:
    """Read one corpus-policy value out of the registry.

    Load-or-refuse, exactly as `kernel_cli/commands/policy.py` does: a probe whose
    policy has not loaded reports the absence rather than defaulting, because a
    defaulted threshold is this script deciding what *blank* or *illegible* means.

    Args:
        key: The policy key, e.g. ``"reader.min_chars"``.

    Returns:
        The declared value.

    Raises:
        KeyError: If the asset does not declare the key.

    """
    values: Mapping[str, Any] = json.loads(POLICY_ASSET.read_text(encoding="utf-8"))
    if key not in values:
        raise KeyError(
            f"{POLICY_ASSET} declares no {key!r}. It declares "
            f"{sorted(values)}. Refusing rather than defaulting: a threshold that "
            "arrived from nowhere would make this probe disagree with every other "
            "caller while reporting success."
        )
    return values[key]


# --- Buckets ----------------------------------------------------------------

#: What the kernel may answer with: a legitimate, expected outcome. These are the
#: codes `kernel-cli.md` §5 maps to exit `2`.
_ANSWER_CODES: Final[frozenset[str]] = frozenset(
    {
        "artifact_missing",
        "blank_page",
        "encrypted",
        "evidence_missing",
        "illegible",
        "insufficient_effective_resolution",
        "truncated_output",
        "unsupported_format",
    }
)

#: The call could not legitimately be made. These are the codes §5 maps to exit
#: `3`.
_PRECONDITION_CODES: Final[frozenset[str]] = frozenset(
    {
        "asset_invalid",
        "asset_missing",
        "engine_unavailable",
        "model_not_pulled",
        "model_unknown",
        "provider_unavailable",
        "provider_unknown",
        "role_conflict",
    }
)

BUCKETS: Final[tuple[str, ...]] = ("ok", "reason", "precondition", "usage", "defect")

_SYMBOL: Final[Mapping[str, str]] = {
    "ok": " ok ",
    "reason": " .. ",
    "precondition": " -- ",
    "usage": " ?? ",
    "defect": " !! ",
}


def bucket_for(result: Any) -> str:
    """Classify a `KernelResult` into the bucket its reason code belongs to.

    A code outside the closed set is **not** silently bucketed as a reason: it is
    reported as a precondition failure, because a vocabulary breach means this
    probe cannot say what the answer was. The distinction is the same one the
    dispatcher draws when it maps an unknown code to exit `1` rather than `2`.

    Args:
        result: A `KernelResult`.

    Returns:
        One of :data:`BUCKETS`.

    """
    if getattr(result, "value", None) is not None:
        return "ok"

    reason = getattr(result, "reason", None)
    if reason is None:
        return "defect"

    code = str(getattr(reason, "code", ""))
    if code in _ANSWER_CODES:
        return "reason"
    if code in _PRECONDITION_CODES:
        return "precondition"
    return "defect"


# --- Describing a value without serialising it ------------------------------

_TRUNCATE_AT: Final[int] = 96

#: Keys of `Evidence.observed` worth surfacing by default, because each is the
#: measurement a reader of the probe output is looking for.
_HIGHLIGHT_KEYS: Final[tuple[str, ...]] = (
    "shape",
    "reading_order",
    "layout_dropped",
    "page_status",
    "outcome",
    "reason_detail",
)


def _truncate(text: str, limit: int = _TRUNCATE_AT) -> str:
    """Shorten `text` to `limit` characters, marking the cut.

    Args:
        text: The text to shorten.
        limit: The maximum length to keep.

    Returns:
        The text, with a trailing ellipsis when it was cut.

    """
    return text if len(text) <= limit else f"{text[:limit]}…"


def _describe_value(value: Any) -> str:
    """Describe a kernel value in one line, without encoding it.

    Recognises the boundary shapes structurally rather than by `isinstance`: this
    module is importable before `docflow` is, so it cannot import a boundary type.

    Args:
        value: The `KernelResult.value`.

    Returns:
        A short description naming the shape and its size.

    """
    if hasattr(value, "data") and hasattr(value, "media_type"):
        return f"Bytes({value.media_type}, {len(value.data)} bytes)"

    if isinstance(value, str):
        return f"text({len(value)} chars) {_truncate(value.splitlines()[0], 48)!r}"

    if isinstance(value, Mapping):
        return f"mapping(keys={sorted(map(str, value))[:6]})"

    if isinstance(value, Sequence):
        return f"{type(value).__name__}({len(value)} items)"

    return type(value).__name__


def _format_mapping(mapping: Mapping[str, Any]) -> str:
    """Render a mapping as sorted ``key=value`` pairs.

    Args:
        mapping: The mapping to render.

    Returns:
        The rendered pairs, truncated.

    """
    pairs = ", ".join(f"{key}={mapping[key]}" for key in sorted(mapping))
    return _truncate(pairs)


def describe(result: Any) -> str:
    """Summarise a `KernelResult` in one line for a human at a console.

    Args:
        result: The `KernelResult` to summarise.

    Returns:
        The value or the reason code, followed by the measurements.

    """
    reason = getattr(result, "reason", None)
    if reason is None:
        parts = [f"value={_describe_value(getattr(result, 'value', None))}"]
    else:
        parts = [f"reason={getattr(reason, 'code', '?')}"]

    evidence = getattr(result, "evidence", None)
    if evidence is None:
        return "  ".join(parts)

    measurements = getattr(evidence, "measurements", None)
    if measurements:
        parts.append(f"meas[{_format_mapping(measurements)}]")

    observed = getattr(evidence, "observed", None) or {}
    highlights = {key: observed[key] for key in _HIGHLIGHT_KEYS if key in observed}
    if highlights:
        parts.append(f"obs[{_format_mapping(highlights)}]")

    return "  ".join(parts)


# --- Running one probe ------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class Outcome:
    """One probe's result, and whether it was the one expected.

    Attributes:
        probe_id: The probe's stable identifier, e.g. ``"pdf.classify.text"``.
        bucket: One of :data:`BUCKETS`.
        expect: The bucket the probe was declared to produce, or ``None`` when
            the probe is informational and asserts nothing.
        detail: The one-line description printed alongside it.
        verdict: ``"PASS"``, ``"DIVERGENT"``, or ``"-"`` when nothing was
            expected.

    """

    probe_id: str
    bucket: str
    expect: str | None
    detail: str
    verdict: str


#: Every outcome this process produced, in order. A module-level list rather than
#: a class: a bench that runs twelve calls and prints a table does not need an
#: object to hold them.
OUTCOMES: list[Outcome] = []


def reset() -> None:
    """Forget every outcome recorded so far."""
    OUTCOMES.clear()


def _record(probe_id: str, bucket: str, detail: str, expect: str | None) -> Outcome:
    """Print and store one outcome.

    Args:
        probe_id: The probe's stable identifier.
        bucket: The bucket the call landed in.
        detail: The one-line description.
        expect: The declared bucket, or ``None``.

    Returns:
        The recorded outcome.

    """
    if expect is None:
        verdict = "-"
    elif bucket == expect:
        verdict = "PASS"
    else:
        verdict = "DIVERGENT"

    outcome = Outcome(
        probe_id=probe_id, bucket=bucket, expect=expect, detail=detail, verdict=verdict
    )
    OUTCOMES.append(outcome)
    print(f"{_SYMBOL[bucket]} {probe_id:<38} [{verdict:<9}] {detail}")
    return outcome


@dataclasses.dataclass(frozen=True, slots=True)
class Attempt:
    """One probe's outcome together with the result it came from.

    The result travels with the outcome rather than being re-fetched, and that is
    a correctness choice rather than a convenience: a probe that called the
    operation once to report it and again to use its value would run every
    operation **twice**. For K2 that is duplicated work; for K6 it is duplicated
    money, and for a `sampled` kernel it is a second sample that the first
    observation does not describe.

    Attributes:
        outcome: The recorded outcome, as printed and tallied.
        result: The `KernelResult` the outcome describes, or ``None`` when the
            call raised instead of returning one.

    """

    outcome: Outcome
    result: Any | None

    @property
    def succeeded(self) -> bool:
        """Whether the call produced a value.

        Returns:
            ``True`` when the bucket is ``ok``.

        """
        return self.outcome.bucket == "ok"


def note(probe_id: str, detail: str) -> Outcome:
    """Record an informational outcome that asserts nothing.

    Used by a probe that spans several operations and whose worth is the trace it
    prints rather than a single bucket - the routing probe in `pdf.py` is the
    case. It is counted in the tally so the total matches what the console shows,
    and its verdict is ``"-"`` because there is nothing to diverge from.

    Args:
        probe_id: The probe's stable identifier.
        detail: The one-line description.

    Returns:
        The recorded outcome.

    """
    return _record(probe_id, "ok", detail, None)


def run(
    probe_id: str,
    call: Callable[..., Any],
    *args: Any,
    expect: str | None = None,
    **kwargs: Any,
) -> Attempt:
    """Call one adapter operation, record what it answered, and keep the result.

    The `expect` bucket is passed at the call site rather than looked up in a
    distant table, so the expectation and the call it belongs to are read
    together - and a probe whose expectation changes is a one-line edit.

    Args:
        probe_id: The probe's stable identifier.
        call: The adapter method, passed unbound or bound.
        *args: Positional arguments for `call`.
        expect: The bucket this probe is declared to produce.
        **kwargs: Keyword arguments for `call`.

    Returns:
        The outcome and the result it describes.

    """
    try:
        result = call(*args, **kwargs)
    except ValueError as exc:
        # The library's stand-in for exit 4: a request the kernel refuses
        # (`kernel-cli.md` §5, *"malformed range"*). It is a usage answer, not a
        # crash, so it must not be counted as a defect.
        return Attempt(
            _record(probe_id, "usage", f"ValueError: {_truncate(str(exc))}", expect),
            None,
        )
    except Exception as exc:  # a probe reports anything it cannot name
        return Attempt(
            _record(
                probe_id,
                "defect",
                f"{type(exc).__name__}: {_truncate(str(exc))}",
                expect,
            ),
            None,
        )

    return Attempt(
        _record(probe_id, bucket_for(result), describe(result), expect), result
    )


# --- Writing what a probe produced ------------------------------------------


def save_bytes(name: str, data: bytes) -> pathlib.Path:
    """Write a probe's bytes under the output root and report where.

    Args:
        name: The file name, suffix included.
        data: The bytes to write.

    Returns:
        The path written.

    """
    return _write(name, data)


def save_text(name: str, text: str) -> pathlib.Path:
    """Write a probe's extracted text under the output root and report where.

    Args:
        name: The file name, suffix included.
        text: The text to write, UTF-8.

    Returns:
        The path written.

    """
    return _write(name, text)


def _write(name: str, payload: bytes | str) -> pathlib.Path:
    """Write `payload` to `<out>/<name>`, creating the root if absent.

    Args:
        name: The file name.
        payload: The bytes or text to write.

    Returns:
        The path written.

    """
    _OUT.mkdir(parents=True, exist_ok=True)
    path = _OUT / name
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_bytes(payload)
    return path


# --- The summary ------------------------------------------------------------


def summary() -> int:
    """Print the tally and return the number of divergent probes.

    Returns:
        How many probes produced a bucket other than the one declared, which is
        what decides the process exit code.

    """
    print()
    print(f"{'bucket':<14}{'count':>6}")
    for bucket in BUCKETS:
        count = sum(1 for outcome in OUTCOMES if outcome.bucket == bucket)
        print(f"{bucket:<14}{count:>6}")

    divergent = [outcome for outcome in OUTCOMES if outcome.verdict == "DIVERGENT"]
    print()
    if divergent:
        print(f"{len(divergent)} divergent:")
        for outcome in divergent:
            print(
                f"  {outcome.probe_id}: expected {outcome.expect}, got {outcome.bucket}"
            )
    else:
        print("every probe produced the bucket it declared.")

    return len(divergent)
