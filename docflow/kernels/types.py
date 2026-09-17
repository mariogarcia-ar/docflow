"""Kernel boundary types — the one shape every kernel, port and adapter exchanges.

This module is the frozen surface of Stage 1 (`docs/plans/plan-01-kernels.md` §5,
`S1-T01`). It fixes the **in-process** shape only: it decides what can be written
down, never how it is encoded or what a kernel does.

The seven frozen boundary types are ``Token``, ``KernelResult``, ``Evidence``,
``Reason``, ``CallRecord``, ``Bytes`` and ``Artifact``. ``Box`` is a supporting
value type required by ``Token.bbox``; it is not an eighth boundary state and it
carries no outcome of its own.

Determinism classes in the source design
----------------------------------------

The eight kernels fall into three classes (`sad.md` §4), and the classification
touches this module in exactly one place: which observation record a kernel
fills in. Deterministic and sampled kernels report their measurements on
``Evidence``; the two language-model kernels additionally fill in
``CallRecord``. The class itself is never a field — it is the orchestrator's
bookkeeping, not a value a kernel emits.

The invariant: no third state
-----------------------------

``KernelResult`` has exactly **two** constructible states, and nothing else is
expressible through it:

| State | Fields |
|---|---|
| A value, with evidence | ``value`` is not None, ``reason`` is None |
| No value, with a reason | ``value`` is None, ``reason`` is not None |

That is ``prd.md`` FR-06 — *"No third state at any boundary"* — enforced at two
levels: ``evidence`` is a required, non-optional field with no default, and
``__post_init__`` rejects the contradictory combinations. A kernel therefore
cannot return a plausible stand-in — an empty string, a zero, an empty token
list, a default model — and have it read as an answer. Those are the shapes a
silent error takes at a layer boundary, and each one is a decision the caller
must not be able to skip.

Design rules that **never** bend
--------------------------------

Stated as prose because the whole point is that they must not become code:

- **Never a third variant.** No ``"unknown"`` arm, no ``Optional[Evidence]``, no
  ``Union`` with a bare value arm that bypasses evidence.
- **Never a convenience field.** No ``error`` / ``error_message`` /
  ``is_ok`` member that re-encodes the two states in a second place.
- **Never a partial-state constructor.** No ``ok()`` / ``fail()`` / ``empty()``
  classmethod, staticmethod or alternative ``__class_getitem__`` that smuggles a
  stand-in into an otherwise legal state. There are no constructors besides the
  dataclass one, by decision: the only way to build a ``KernelResult`` is to
  state its value, its evidence and its reason explicitly.
- **Never a silent default.** No field on ``KernelResult`` has a default value,
  so a missing argument is a ``TypeError`` and not a substituted empty answer.
- **Never an aggregate grade at this surface.** ``Evidence`` carries raw
  measurements and free-form observables. It carries no ``confidence``,
  no ``score``, no ``quality`` and no ``grade`` — aggregating measurements into
  a verdict is the domain layer's job, and a number that looks like a decision
  at a kernel boundary is a decision in disguise.
- **Never a domain noun.** No type, field or member name contains one, so no
  component can be mistaken for a kernel or vice versa.

PoC stage
---------

The project's lifecycle stage is **PoC**: close the end-to-end flow first, with
pragmatic shortcuts where they buy speed. Each deliberate shortcut taken in this
module carries a ``# TODO: [MVP]`` marker naming what must replace it. Nothing
else is deferred silently.

Two known PoC properties of this module, stated rather than discovered later:

- ``Evidence`` is **not hashable**, so neither is a ``KernelResult`` that carries
  one, because its mappings are plain ``dict``/``MappingProxyType`` values. The
  deterministic-by-value types (``Box``, ``Token``, ``Reason``, ``Bytes``,
  ``Artifact``, ``CallRecord``) are hashable. Nothing consumed by this issue
  requires a hashable result — the envelope is JSON — and this is pinned by a test
  so that a future change is deliberate rather than a surprise.
- The mappings are **not JSON-encodable by default**: ``MappingProxyType`` has no
  default encoder. The envelope encoder that ``E07-01`` (``S1-T20``) adds must
  handle it, or the boundary types must expose a plain-``dict`` view.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from typing import Final, Generic, TypeVar

# Sorted alphabetically to satisfy Ruff's RUF022. The comments that used to
# separate the boundary types from the supporting one are gone from this list on
# purpose: `BOUNDARY_TYPE_NAMES` below is the declaration of which names are the
# frozen boundary set, and a comment is not. `Box` is supporting, not a boundary
# state, and the docstring says so.
__all__: list[str] = [
    "Artifact",
    "Box",
    "Bytes",
    "CallRecord",
    "Evidence",
    "KernelResult",
    "Reason",
    "Token",
]

T = TypeVar("T")

#: The seven frozen kernel-boundary type names, in the order ``__all__`` exports
#: them. A declaration of the boundary set, so a reader can see the contract
#: without reading the whole module.
BOUNDARY_TYPE_NAMES: Final[tuple[str, ...]] = (
    "Token",
    "KernelResult",
    "Evidence",
    "Reason",
    "CallRecord",
    "Bytes",
    "Artifact",
)


@dataclasses.dataclass(frozen=True, slots=True)
class Box:
    """A rectangle in source page coordinates, at the render DPI.

    A supporting value type, not a kernel-boundary state type: it carries no
    outcome, no evidence and no reason of its own. It exists because
    ``Token.bbox`` is part of the frozen ``Token`` contract (`sad.md` §6).

    Coordinates are in **source page coordinates**, never in a local frame, so a
    crop's local box must be mapped back before it leaves K3.

    Attributes:
        x: Left edge, in source page units at the render DPI.
        y: Top edge, in source page units at the render DPI.
        width: Width in source page units, strictly non-negative by convention.
        height: Height in source page units, strictly non-negative by convention.
    """

    x: float
    y: float
    width: float
    height: float
    # TODO: [MVP] The geometry itself is deliberately not validated here. PoC
    # keeps Box a plain record; an MVP should decide whether negative extents are
    # rejected on construction or normalized by the caller that produces them.


@dataclasses.dataclass(frozen=True, slots=True)
class Token:
    """One positioned token as a reader returned it.

    Attributes:
        text: The token's characters, exactly as read, before any correction.
        page: One-based page number within the source document.
        bbox: Bounding box in source page coordinates, at the render DPI.
        confidence: Reader confidence in [0, 1], or None when the reader reports none.
        role: Reader-assigned role, e.g. "text", "table_cell", "header".
    """

    text: str
    page: int
    bbox: Box
    confidence: float | None
    role: str


@dataclasses.dataclass(frozen=True, slots=True)
class Evidence:
    """What a kernel observed on one call.

    Three layers, deliberately separated because they are consumed differently:

    - ``terms`` feed the cache key, so they must be stable and exactly stated.
    - ``measurements`` are the raw numbers a caller may compare against its own
      policy threshold. The threshold is never the kernel's (`kernel-cli.md` §3).
    - ``observed`` is the free-form remainder: booleans, short strings, small
      structures that are facts about this call but fit neither layer above.

    This type is a measurement record. It defines **no** aggregate grade — a
    ``score`` and a ``confidence`` are decisions wearing a number's clothes and
    are forbidden at this surface.

    Attributes:
        terms: Hash, version and parameter terms that feed the cache key.
        measurements: Raw named measurements, e.g. character counts or an
            effective-DPI estimate.
        observed: Free-form observables that are neither cache terms nor
            numeric measurements, e.g. a flag the adapter reported.
    """

    terms: Mapping[str, str]
    measurements: Mapping[str, float]
    observed: Mapping[str, object]
    # TODO: [MVP] Immutability depth stops at the mapping object. The mappings
    # are immutable by convention here, so a caller could still mutate a nested
    # value; an MVP should freeze them (a deep copy into immutable containers, or
    # an explicit normalized constructor) so that `frozen=True` means what it
    # says one level down. Deferred in PoC because every producer is in-process.


@dataclasses.dataclass(frozen=True, slots=True)
class Reason:
    """Why a kernel produced no value.

    ``code`` is the machine-readable member: the CLI's exit-code contract and the
    golden set both assert on it, and a failure path with no code is untestable
    (`kernel-cli.md` §5). ``message`` is for a human reading a log.

    Attributes:
        code: The machine-readable reason code, a stable identifier such as
            "blank_page". Assertions target this member, never the message.
        message: The human-readable explanation, for logs and diagnostics.
    """

    code: str
    message: str
    # TODO: [MVP] The closed set of legal `code` values is NOT defined or
    # validated here. It lives in `kernel-cli.md` §5 and is owned by the epics
    # that raise codes; this issue fixes only that a code exists. Deliberately
    # not an Enum and deliberately not checked against a list, so a boundary type
    # does not silently become the vocabulary's owner.


@dataclasses.dataclass(frozen=True, slots=True)
class CallRecord:
    """What a provider call cost and which revision answered.

    Populated for the language-model kernels only (K5 and K6). The remaining
    kernels record their observations on ``Evidence``.

    ``model_revision`` is the identity, not the tag: a tag such as ``qwen2.5``
    moves, while the digest is what a reproducible run must record.

    Attributes:
        provider: The provider prefix that resolved, e.g. "ollama".
        model: The model name as requested by the caller.
        model_revision: The resolved immutable revision, e.g. a digest. This,
            and never the tag alone, is the model's identity.
        prompt_tokens: Prompt tokens counted or reported, None when unreported.
        completion_tokens: Completion tokens counted or reported, None when
            unreported.
        total_tokens: Total tokens counted or reported, None when unreported.
        cost_usd: Cost in US dollars, None when the provider does not charge or
            does not report it, e.g. a local model.
        latency_ms: Wall-clock latency of the call in milliseconds.
        request_id: The provider's request identifier for support and tracing,
            None when the provider does not return one.
    """

    provider: str
    model: str
    model_revision: str
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    cost_usd: float | None
    latency_ms: float
    request_id: str | None
    # TODO: [MVP] Nothing enforces that a language-model kernel populates this
    # structure: "populated for K5/K6 only" is a producer obligation, not a
    # constructibility rule, and PoC has no such producer yet. An MVP should
    # assert it where the two language-model kernels are built.


@dataclasses.dataclass(frozen=True, slots=True)
class Bytes:
    """An opaque in-memory buffer with the media type describing it.

    Bytes cross a kernel boundary before they exist as a stored file, so this
    type is what K2 and K3 hand back for a rendered or rescaled page.

    Attributes:
        data: The raw buffer, exactly as produced, with no encoding applied.
        media_type: The buffer's media type, e.g. "image/png".
    """

    data: bytes
    media_type: str


@dataclasses.dataclass(frozen=True, slots=True)
class Artifact:
    """A stored blob addressed by its content hash.

    This is the descriptor, not the bytes: the out-of-band form the kernel
    surface emits by default (`kernel-cli.md` §6). ``sha256`` is the real hash of
    what was written, which is what makes a later verification meaningful.

    Attributes:
        sha256: The lowercase hexadecimal SHA-256 digest of the stored content.
        size_bytes: The stored content's length in bytes.
        media_type: The stored content's media type, e.g. "image/png".
        path: The location the artifact was written to, relative to the store
            root, or None when only the descriptor is known.
    """

    sha256: str
    size_bytes: int
    media_type: str
    path: str | None


@dataclasses.dataclass(frozen=True, slots=True)
class KernelResult(Generic[T]):
    """The outcome of one kernel call, always with its evidence.

    Exactly two states are constructible, and they are the only two the system
    recognizes:

    - a value with its evidence (``reason`` is ``None``), and
    - no value, with a reason (``value`` is ``None``).

    Every other combination raises ``ValueError`` from ``__post_init__``. The
    error type is ``ValueError`` and not ``TypeError``: the arguments are of the
    right *type*, they are the wrong *combination*, and the difference matters to
    a caller that catches this deliberately.

    Attributes:
        value: The result, or None when the kernel could not produce one.
        evidence: What was observed — versions, parameters, measurements.
        reason: Why value is None, or None when it is not.

    Raises:
        ValueError: If ``value`` is not None and ``reason`` is not None (a value
            and a reason are contradictory: the reason states why there is no
            value); or if ``value`` is None and ``reason`` is None (a missing
            value must always be explained); or if ``evidence`` is None (every
            call, including a failed one, has something to report).
    """

    value: T | None
    evidence: Evidence
    reason: Reason | None
    # TODO: [MVP] Serialization is deliberately absent. This file fixes the
    # in-process shape only; the JSON envelope (`{"value", "evidence", "reason",
    # "call_record"}`) and its exit-code contract belong to the kernel CLI
    # (`E07-01` / `S1-T20`, `kernel-cli.md` §6). Do not add `to_dict`/`to_json`
    # here — an encoder next to the contract is the second source of truth this
    # module exists to prevent.

    def __post_init__(self) -> None:
        """Reject every state outside the two legal ones.

        Called by the generated ``__init__``, and still reachable on a frozen
        slotted dataclass: the fields are already set, so raising here means no
        illegal instance ever escapes construction.

        Raises:
            ValueError: If ``evidence`` is None, if a value is accompanied by a
                reason, or if a missing value is unaccompanied by one.
        """
        if self.evidence is None:
            raise ValueError(
                "KernelResult requires evidence: a kernel call always observes "
                "something (versions, parameters, measurements). A value without "
                "evidence cannot be distinguished from a stand-in, and a failure "
                "without evidence cannot be diagnosed. Got evidence=None with "
                f"value={self.value!r}."
            )

        if self.value is not None and self.reason is not None:
            raise ValueError(
                "KernelResult cannot carry a value and a reason together: the "
                "reason states why there is no value, so the two are "
                "contradictory. Got value="
                f"{self.value!r} with reason.code={self.reason.code!r}. Return "
                "the value with reason=None, or return value=None with the "
                "reason."
            )

        if self.value is None and self.reason is None:
            raise ValueError(
                "KernelResult requires a reason when value is None: there is no "
                "third state, and a missing value that is not explained is "
                "indistinguishable from a silent failure. Got value=None with "
                "reason=None."
            )
