"""Resolution by capability - which engine answers, and what it will be keyed by.

`E04-07` / `S1-T17`. The layer's most expensive silent failure is a model that
resolves to *something* instead of failing: every value downstream is then produced
by a model nobody chose, nothing in the output says so, and the ledger reports a
successful run. This module exists to make **"there is no fallback"** a fact a test
can reach.

A refusal is a ``KernelResult``, never an exception
---------------------------------------------------

An unknown model is *the call's precondition*, and `kernel-cli.md` §5 gives that its
own exit code (`3`) with its own closed reason codes (``model_unknown``,
``provider_unknown``). A refusal raised as an exception would reach exit `1` instead -
*unexpected internal error* - collapsing **"this name is wrong"** into **"the code has
a bug"**, which is precisely the collapse `kernel-cli.md` §5 exists to prevent. So
every refusal here is a ``KernelResult`` with ``value=None`` and a typed ``Reason``,
the same shape every other kernel returns, and the exit code follows from the reason
code rather than from this module.

Why a capability is declared rather than discovered by trying
-------------------------------------------------------------

Resolution could call each adapter and keep the one that answers. It does not, for two
reasons. ``capabilities`` is not free - on K5 it reads the runtime's catalogue, on K6
the adapter's revision - and resolution is specified to run **executing nothing**,
which is what makes ``--resolve-only`` cheap enough to sit in a test suite
(`kernel-cli.md` §8). And a capability list assembled by trial would put *"which engine
is reachable"* inside the resolution decision, so a transient outage would change which
model is used. That is the failure this module prevents, one layer down.

What "by capability" means here, concretely
-------------------------------------------

The prefix of a name selects a **capability family**, and the family declares which
kernel it belongs to and which operations it serves. The prefix is a **whole** segment
- ``anthropic:claude-sonnet-4-6`` is family ``anthropic`` - matched against the
declared table. A prefix that names no family produces ``provider_unknown`` naming it,
and a name with no prefix at all produces ``model_unknown`` rather than a guess:
**the table is the whole registry**, so *"no fallback"* is a property of the
declaration rather than of a lookup's failure mode.

The two adapters are not shaped alike, and pretending otherwise would be the bug
--------------------------------------------------------------------------------

Measured against the adapters as built, not assumed - this is why one rule could not
cover both:

| Family | ``capabilities`` | The name it answers to |
|---|---|---|
| ``ollama`` (K5) | reads ``/api/tags`` | **bare**: ``qwen2.5``. To that runtime
``:`` is its *tag* separator, so ``ollama:qwen2.5`` asks for a model **genuinely
named** ``ollama`` - verified to match nothing |
| ``anthropic`` (K6) | model required | **prefixed**:
``anthropic:claude-sonnet-4-6``; the adapter reports ``model_unknown`` for a bare
name |

So ``answered_as`` is a field on the family and is read from the adapter's own parsing
rule rather than restated as a rule of this module's invention. A single "strip the
prefix" or "keep the prefix" rule would be wrong for one of the two, and being wrong
here means resolving to a different model than the adapter then asks for.

K4 is deliberately not a family
-------------------------------

Docling is the fixed and only OCR engine and is never a setting (`ADR-001`, `prd.md`
FR-16), so K4 has **no capability to resolve**: there is nothing to choose, and no
``model_revision`` to key by. Its engine identity comes from
``OcrEngine.engine_info()``, which `E04-04` already built. Recording that as a missing
family rather than implementing one is the decision read literally, not a gap.

Deliberately out of scope
-------------------------

- **No execution.** Resolution generates nothing, warms nothing and renders nothing.
  Every call it makes is an adapter's ``capabilities``, which is a metadata read
  (`kernel-cli.md` §8).
- **No ``--fallback``, no ``--default-model``, no environment variable that
  substitutes a model.** **Never** (`kernel-cli.md` §8, §14).
- **No engine setting.** K4 is not a family; there is no engine to name (`ADR-001`).
- **No threshold.** A threshold is the caller's value; resolution never supplies one
  (`prd.md` FR-15).
- **No circuit breaker, no escalation ladder.** *"Sustained unavailability degrades to
  ``unverified``"* is the adapter's typed outcome (`E04-06`); the ladder that consumes
  it is `S2-T09`, Plan 2.
- **No routing across several vendors of one family.** One vendor per family in Stage
  1. `# TODO: [MVP]`.
- **No pipeline, field or document noun.** **Never** (`kernel-cli.md` §10).

PoC stage
---------

The lifecycle stage is **PoC**: close the flow, keep the shortcuts visible. Each
deliberate shortcut carries a marker naming what must replace it.

"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import Final, Protocol

from docflow.kernels import registry as registry_kernel
from docflow.kernels.cache_key import CacheKeyTerms, cache_key
from docflow.kernels.types import Evidence, KernelResult, Reason

__all__: list[str] = [
    "ANSWERS_TO_BARE",
    "ANSWERS_TO_PREFIXED",
    "CAPABILITIES",
    "KERNEL_IDENTITIES",
    "OPERATION_GENERATION",
    "OPERATION_VISION",
    "Capability",
    "KernelIdentity",
    "Request",
    "Resolved",
    "cache_key_for_resolution",
    "compose_terms",
    "declared_capabilities",
    "known_families",
    "resolve",
    "resolve_with_registry",
    "terms_from_resolution",
]

#: A caller asks a capability to serve one of two operations. Two, because the
#: distinction is real: a model either generates from a prompt or reads pixels, and a
#: local model installed without its vision weights serves the first and not the
#: second. Asking for one, rather than inferring it from a family name, is what keeps
#: *"a model that cannot see"* from being discovered at call time.
OPERATION_GENERATION: Final[str] = "generation"
OPERATION_VISION: Final[str] = "vision"

#: A family whose adapter answers to the **bare** model name, with no family prefix.
#: True for a runtime that already uses ``:`` for its own tags.
ANSWERS_TO_BARE: Final[str] = "bare"

#: A family whose adapter answers to the **family-prefixed** name.
ANSWERS_TO_PREFIXED: Final[str] = "prefixed"

#: The name styles a capability may declare.
_NAME_STYLES: Final[frozenset[str]] = frozenset({ANSWERS_TO_BARE, ANSWERS_TO_PREFIXED})

#: A family-prefixed name. The prefix is a **whole** segment, and the shape is the one
#: `docflow/adapters/frontier.py` uses, so a name is split the way the adapter that
#: will receive it splits it.
_FAMILY: Final[re.Pattern[str]] = re.compile(
    r"^(?P<family>[A-Za-z0-9_-]+):(?P<rest>.+)$"
)

#: The operations this module resolves, declared once so the check and the message
#: cannot drift.
_DECLARED_OPERATIONS: Final[frozenset[str]] = frozenset(
    {OPERATION_GENERATION, OPERATION_VISION}
)


@dataclasses.dataclass(frozen=True, slots=True)
class KernelIdentity:
    """A kernel's own identity: the ``kernel id`` and ``kernel version`` key terms.

    Passed in by the caller rather than looked up inside this module, because the
    version must be the identity of the kernel being resolved **for** - a value read
    internally could disagree with the kernel the caller named.

    Attributes:
        kernel_id: The kernel's identity, e.g. ``"llm.local"``.
        kernel_version: The kernel's version. A bug fix must invalidate what the bug
            produced, which is why this term is separate from the identity
            (`sad.md` §5).

    Raises:
        ValueError: If either is the empty string, because a term dropped as *"always
            the same"* produces a correct-looking run that reuses an answer computed
            under different inputs.

    """

    kernel_id: str
    kernel_version: str

    def __post_init__(self) -> None:
        """Refuse an empty identity term.

        Raises:
            ValueError: If ``kernel_id`` or ``kernel_version`` is empty.

        """
        for name, value in (
            ("kernel_id", self.kernel_id),
            ("kernel_version", self.kernel_version),
        ):
            if not value:
                raise ValueError(
                    f"{name} must be stated: an empty cache-key term is an absent "
                    "term, and the key would then be identical for different work."
                )


@dataclasses.dataclass(frozen=True, slots=True)
class Capability:
    """A capability family: which kernel it belongs to, and what it answers to.

    Attributes:
        family: The family name, e.g. ``"ollama"``. Matched as a **whole** prefix
            segment, never as a substring.
        kernel: The kernel this family belongs to, e.g. ``"llm.local"``. A name that
            resolves to another kernel's family is refused rather than served.
        answers_to: :data:`ANSWERS_TO_BARE` or :data:`ANSWERS_TO_PREFIXED` - the name
            style the **adapter's own** parsing rule requires, recorded here rather
            than restated as a rule this module invents.
        operations: The operations this family serves. A request for one it does not
            declare is refused, because a family that resolved and then failed at the
            call would report the wrong thing at the wrong time.

    Raises:
        ValueError: On an empty family or kernel, an unknown ``answers_to``, an empty
            operation set, or an empty operation name.

    """

    family: str
    kernel: str
    answers_to: str
    operations: frozenset[str]

    def __post_init__(self) -> None:
        """Refuse a capability nobody could resolve or route.

        Raises:
            ValueError: On an empty family or kernel, an unrecognised name style, an
                empty operation set, or an empty operation name.

        """
        if not self.family or not self.kernel:
            raise ValueError(
                "A capability's family and kernel must both be stated: a family "
                "nobody can name cannot be resolved."
            )

        if self.answers_to not in _NAME_STYLES:
            raise ValueError(
                f"Capability {self.family!r} declares answers_to={self.answers_to!r}, "
                f"which is not one of {sorted(_NAME_STYLES)}. An unrecognised style "
                "would forward a name the adapter cannot parse, and the refusal would "
                "arrive from the wrong layer."
            )

        if not self.operations:
            raise ValueError(
                f"Capability {self.family!r} declares no operations. A family that can "
                "serve nothing would resolve successfully and then fail at the call."
            )

        if any(not operation for operation in self.operations):
            raise ValueError(
                f"Capability {self.family!r} declares an empty operation name: an "
                "empty name is a stand-in, not an operation."
            )


#: The capability families this deployment declares. **The table is the registry**: a
#: family absent from it cannot resolve, so *"no fallback"* is a property of the
#: declaration rather than of a lookup's failure mode.
#:
#: K4 is deliberately absent - see the module docstring.
CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        family="ollama",
        kernel="llm.local",
        # That runtime uses `:` for its own tags (`qwen2.5:latest`), so the bare name
        # is what it answers to. Measured against the adapter's own matcher rather
        # than assumed: `ollama:qwen2.5` matches nothing in its catalogue.
        answers_to=ANSWERS_TO_BARE,
        operations=frozenset({OPERATION_GENERATION, OPERATION_VISION}),
    ),
    Capability(
        family="anthropic",
        kernel="llm.frontier",
        # The adapter requires the prefix and reports `model_unknown` without it.
        answers_to=ANSWERS_TO_PREFIXED,
        operations=frozenset({OPERATION_GENERATION, OPERATION_VISION}),
    ),
)

#: The kernel identity each family belongs to. Declared so a resolution reports the
#: kernel it serves, and so a mismatch between the family and the caller's stated
#: kernel is detectable rather than silent.
#:
#: TODO: [MVP] The version is a constant because the kernel layer has no version
#: registry in the PoC, and inventing a per-call version would be a value nothing
#: increments. A released package should read it from one declared source.
KERNEL_IDENTITIES: Mapping[str, KernelIdentity] = MappingProxyType(
    {
        "ollama": KernelIdentity(kernel_id="llm.local", kernel_version="0.1.0"),
        "anthropic": KernelIdentity(kernel_id="llm.frontier", kernel_version="0.1.0"),
    }
)


@dataclasses.dataclass(frozen=True, slots=True)
class Resolved:
    """Which capability answered, what it reported, and therefore which key applies.

    Resolution reports *which engine and which revision*; it never reports a result.
    :attr:`terms` is filled in only when the caller supplied an input hash and a
    registry hash, because a cache key needs all seven of its terms or none of them -
    a partially composed key is not a key.

    Attributes:
        capability: The family that was chosen.
        model: The model name as the caller wrote it.
        answered_as: The name forwarded to the adapter, whose shape the adapter's own
            parsing rule decides.
        model_revision: The resolved immutable identity: a digest for a local model, a
            concrete model string for a hosted one. **Never** the tag alone.
        adapter_revision: The engine's revision, e.g. an Ollama build or the provider
            API version.
        params: The effective parameters the call will run under, as strings.
        terms: The seven cache-key terms, or None when the caller supplied none.

    """

    capability: Capability
    model: str
    answered_as: str
    model_revision: str
    adapter_revision: str
    params: Mapping[str, str]
    terms: CacheKeyTerms | None


class _ReportsCapabilities(Protocol):
    """The one adapter member resolution calls, and nothing else.

    A protocol rather than ``LlmEngine``: resolution uses a single operation, and
    naming the whole port would make this module's dependency look larger than it is.
    It is satisfied structurally by K5's and K6's adapters as built.
    """

    # One member is the whole dependency, and it is declared here rather than in a
    # port: this is the consumer's own narrow view of what it needs.
    # pylint: disable=too-few-public-methods
    def capabilities(self, model: str) -> KernelResult[Evidence]:
        """Report the model's identity and parameters, without generating.

        Args:
            model: The model as this module composed the name.

        Returns:
            The model's revision and parameters, or no value and a typed ``Reason``.

        """


@dataclasses.dataclass(frozen=True, slots=True)
class Request:
    """What a caller is asking to resolve, before any engine is consulted.

    The four things that identify the request travel together because they are checked
    together: a name is only meaningful against the kernel and the operation the caller
    intends, and the engine table is what the name has to resolve *to*.

    Attributes:
        model: The model as the caller named it, e.g. ``ollama:qwen2.5``.
        kernel: The kernel the call belongs to, e.g. ``"llm.local"``.
        operation: :data:`OPERATION_GENERATION` or :data:`OPERATION_VISION`.
        engines: Family name to the bound adapter.

    Raises:
        ValueError: On an empty ``model`` or ``kernel``. An unnamed model cannot be
            resolved, and an unnamed kernel cannot be checked against the family.

    """

    model: str
    kernel: str
    operation: str
    engines: Mapping[str, _ReportsCapabilities]

    def __post_init__(self) -> None:
        """Refuse a request that names no model or no kernel.

        Raises:
            ValueError: If ``model`` or ``kernel`` is empty.

        """
        for name, value in (("model", self.model), ("kernel", self.kernel)):
            if not value:
                raise ValueError(
                    f"A resolve request must name its {name}: an empty one is a "
                    "stand-in, and the refusal it produced would name nothing."
                )

        if self.operation not in _DECLARED_OPERATIONS:
            raise ValueError(
                f"{self.operation!r} is not an operation this module resolves. The "
                f"declared operations are {sorted(_DECLARED_OPERATIONS)}; an "
                "undeclared one would otherwise resolve as if it were supported."
            )


def declared_capabilities() -> Mapping[str, Capability]:
    """Return the declared capability families, keyed by family.

    Returns:
        A read-only mapping from family name to :class:`Capability`.

    """
    return MappingProxyType(
        {capability.family: capability for capability in CAPABILITIES}
    )


def resolve(request: Request) -> KernelResult[Resolved]:
    """Resolve a request to a capability, its revision and its parameters.

    Executes nothing beyond an adapter's own ``capabilities`` read, which is a metadata
    call: it generates no tokens and renders nothing (`kernel-cli.md` §8,
    ``--resolve-only``).

    Args:
        request: The model, the kernel, the operation and the bound engines. The
            dataset is one object because the fields are checked against each other -
            a name is only meaningful against the kernel and the operation it is being
            resolved for.

    Returns:
        The resolution, or no value and a typed ``Reason``. The codes, all in the
        closed set (`kernel-cli.md` §5):

        - ``provider_unknown`` - the prefix names no declared family, the resolved
          family belongs to another kernel, the family does not serve the operation, or
          the family has no bound engine.
        - ``model_unknown`` - the name carries no prefix, so no family can be selected.
          A capability is named ``<family>:<model>``; guessing which family a bare name
          meant is how a name silently becomes a different model.
        - the adapter's **own** code when the family resolves but the adapter could not
          report an identity - ``model_not_pulled`` for a local model absent from the
          runtime, ``model_unknown`` for a hosted name the provider does not know,
          ``engine_unavailable`` or ``provider_unavailable`` for an unreachable one.
          Forwarded unchanged: it names the real problem, and replacing a specific fact
          with a general one is how a diagnosis becomes a guess.

    """
    known = declared_capabilities()
    capability = _family_of(request.model, known)
    refusal = _routing_refusal(request, capability, known)
    if refusal is not None:
        return refusal

    if capability is None:
        # Unreachable: `_routing_refusal` refuses every path that leaves it None, and
        # the guard is written rather than asserted so it survives `python -O`.
        raise ValueError(
            f"{request.model!r} passed routing without a capability. That is a defect "
            "in this module rather than a condition a caller can produce."
        )

    engine = request.engines[capability.family]
    answered_as = _answered_name(capability, request.model)
    reported = engine.capabilities(answered_as)
    if reported.value is None:
        # The adapter's own reason, forwarded whole - including its code. It knows
        # whether the model is absent, the runtime is down, or the provider rejected
        # the name, and that distinction is worth more than a code invented here.
        return KernelResult(
            value=None, evidence=reported.evidence, reason=reported.reason
        )

    observed = reported.value.observed
    resolved = Resolved(
        capability=capability,
        model=request.model,
        answered_as=answered_as,
        model_revision=str(observed["model_revision"]),
        adapter_revision=str(observed["adapter_revision"]),
        params=_params_from(observed),
        terms=None,
    )

    identity = KERNEL_IDENTITIES[capability.family]
    return KernelResult(
        value=resolved,
        evidence=Evidence(
            terms=MappingProxyType(
                {
                    "family": capability.family,
                    "kernel_id": identity.kernel_id,
                    "kernel_version": identity.kernel_version,
                    "model_revision": resolved.model_revision,
                    "adapter_revision": resolved.adapter_revision,
                }
            ),
            measurements=reported.value.measurements,
            observed=MappingProxyType(
                {
                    "model": request.model,
                    "answered_as": answered_as,
                    "family": capability.family,
                    "kernel": capability.kernel,
                    "operation": request.operation,
                }
            ),
        ),
        reason=None,
    )


def resolve_with_registry(
    request: Request,
    *,
    identity: KernelIdentity,
    input_hash: str,
    registry_root: Path,
) -> KernelResult[Resolved]:
    """Resolve a request and compose its seven terms, hashing through K8.

    This is the path a real caller takes. The registry hash is a **mandatory** key term
    (`prd.md` FR-08) and cannot be composed without the assets, so the caller hands over
    a registry **root** and K8 decides the hash through
    :func:`docflow.kernels.registry.registry_hash`. A caller that composed its own hash
    would be carrying a second implementation of K8's encoding rule, and the two would
    drift - so it is not offered.

    Args:
        request: The model, the kernel, the operation and the bound engines.
        identity: The kernel's own identity, for the ``kernel_id`` and
            ``kernel_version`` terms. Supplied by the caller because the version must
            be the identity of the kernel being resolved **for**.
        input_hash: The stage's input hash, from the artifact the stage consumes.
        registry_root: The registry root.

    Returns:
        The resolution with its terms composed, or no value and a typed ``Reason``:
        K8's own when the registry cannot be loaded, or the adapter's when the model
        cannot be resolved. The two are never merged - a broken registry and an unknown
        model are different facts with different remedies.

    """
    loaded = registry_kernel.load_registry(registry_root)
    if loaded.value is None:
        return KernelResult(value=None, evidence=loaded.evidence, reason=loaded.reason)

    resolved = resolve(request)
    if resolved.value is None:
        return resolved

    terms = compose_terms(
        resolved.value,
        identity=identity,
        input_hash=input_hash,
        registry_hash=registry_kernel.registry_hash(loaded.value),
    )
    return _with_terms(resolved, terms)


def terms_from_resolution(
    resolution: Resolved,
    *,
    identity: KernelIdentity,
    input_hash: str,
    registry_hash: str,
) -> CacheKeyTerms:
    """Compose the seven terms for an already-resolved capability.

    A caller that already holds a registry hash - because it loaded the registry once
    for a whole run rather than once per stage - uses this instead of
    :func:`resolve_with_registry`.

    Args:
        resolution: The resolution to key.
        identity: The kernel's own identity.
        input_hash: The stage's input hash.
        registry_hash: K8's hash over the registry content.

    Returns:
        The seven terms, ready for :func:`docflow.kernels.cache_key.cache_key`.

    """
    return compose_terms(
        resolution,
        identity=identity,
        input_hash=input_hash,
        registry_hash=registry_hash,
    )


def compose_terms(
    resolution: Resolved,
    *,
    identity: KernelIdentity,
    input_hash: str,
    registry_hash: str,
) -> CacheKeyTerms:
    """Compose the seven cache-key terms from a resolution.

    Args:
        resolution: The resolution to key.
        identity: The kernel's own identity.
        input_hash: The stage's input hash.
        registry_hash: K8's hash over the registry content.

    Returns:
        The seven terms. Every one is present: the four identity terms come from the
        resolution, and the two the caller supplies are required arguments - so a term
        cannot be omitted and no default can stand in for one.

    """
    return CacheKeyTerms(
        input_hash=input_hash,
        kernel_id=identity.kernel_id,
        kernel_version=identity.kernel_version,
        adapter_revision=resolution.adapter_revision,
        params=resolution.params,
        registry_hash=registry_hash,
        model_revision=resolution.model_revision,
    )


def cache_key_for_resolution(
    resolution: Resolved,
    *,
    identity: KernelIdentity,
    input_hash: str,
    registry_hash: str,
) -> str:
    """Return the full cache key for a resolution, as one string.

    Args:
        resolution: The resolution to key.
        identity: The kernel's own identity.
        input_hash: The stage's input hash.
        registry_hash: K8's hash over the registry content.

    Returns:
        The key, as :func:`docflow.kernels.cache_key.cache_key` composed it - the same
        value :func:`docflow.kernels.orchestrator.cache_key_for` composes for a stage,
        reached from the resolution side rather than from the graph side.

    """
    return cache_key(
        compose_terms(
            resolution,
            identity=identity,
            input_hash=input_hash,
            registry_hash=registry_hash,
        )
    )


def known_families() -> Sequence[str]:
    """Return the declared family names, sorted.

    Returns:
        The family names, for a caller building a message that names them.

    """
    return tuple(sorted(declared_capabilities()))


def _family_of(model: str, known: Mapping[str, Capability]) -> Capability | None:
    """Return the capability family a model name names, if it names one.

    Args:
        model: The name as the caller wrote it.
        known: The declared families, keyed by family.

    Returns:
        The family, or None when the name carries no prefix. A bare name is **not**
        guessed at: which family it meant is not derivable from the name, and guessing
        is how a name silently becomes a different model.

    """
    match = _FAMILY.match(model.strip())
    if match is None:
        return None

    return known.get(match.group("family"))


def _routing_refusal(
    request: Request,
    capability: Capability | None,
    known: Mapping[str, Capability],
) -> KernelResult[Resolved] | None:
    """Check every precondition that does not need the adapter, before calling it.

    The order is deliberate - the most specific refusal first, so the message names the
    actual problem rather than the first thing that happened to be checked. Each case
    is rejected by **its own** check, so which one fired is visible in the code as well
    as in the message (`plan-01-kernels.md` §7's dead-branch lesson).

    Args:
        request: The request being resolved.
        capability: The resolved family, or None when no prefix matched a family.
        known: The declared families, keyed by family.

    Returns:
        The refusal, or None when every precondition holds.

    """
    model = request.model
    match = _FAMILY.match(model.strip())
    prefix = match.group("family") if match is not None else None

    if capability is None and prefix is None:
        return _refused(
            "model_unknown",
            (
                f"the model name {model!r} carries no family prefix, and a "
                "prefixless name is not resolved by guessing which family it meant. "
                f"A capability is named `<family>:<model>`, and the declared "
                f"families are {sorted(known)}; no default is substituted."
            ),
            {"model": model, "known_families": sorted(known)},
        )

    if capability is None:
        return _refused(
            "provider_unknown",
            (
                f"the provider prefix {prefix!r} in {model!r} names no declared "
                f"capability. The known families are {sorted(known)}; no fallback "
                "provider is substituted."
            ),
            {"model": model, "known_families": sorted(known), "family": prefix},
        )

    if capability.kernel != request.kernel:
        return _refused(
            "provider_unknown",
            (
                f"{model!r} resolves to capability {capability.family!r}, which "
                f"belongs to kernel {capability.kernel!r}, not {request.kernel!r}. "
                "Serving it here would mean the kernel the caller named and the "
                "engine that answered disagree."
            ),
            {
                "model": model,
                "kernel": request.kernel,
                "resolved_kernel": capability.kernel,
                "family": capability.family,
            },
        )

    if request.operation not in capability.operations:
        return _refused(
            "provider_unknown",
            (
                f"capability {capability.family!r} does not serve "
                f"{request.operation!r}. It declares "
                f"{sorted(capability.operations)}; a model installed without the "
                "weights an operation needs is a different capability, not a "
                "degraded one."
            ),
            {
                "model": model,
                "operation": request.operation,
                "declared_operations": sorted(capability.operations),
            },
        )

    if capability.family not in request.engines:
        return _refused(
            "provider_unknown",
            (
                f"capability {capability.family!r} is declared but no engine is bound "
                f"for it. Bound families: {sorted(request.engines)}. A declaration "
                "without a binding is a configuration error, and resolving it by "
                "trying another family would be the fallback this module refuses."
            ),
            {
                "model": model,
                "family": capability.family,
                "bound": sorted(request.engines),
            },
        )

    return None


def _answered_name(capability: Capability, model: str) -> str:
    """Return the name to hand the adapter, in the style the adapter parses.

    Args:
        capability: The resolved family.
        model: The name the caller wrote.

    Returns:
        The bare model name for a family that answers to one - dropping the caller's
        family prefix, because a runtime that uses ``:`` for its own tags would read
        it as a model name - or the family-prefixed name otherwise.

    """
    match = _FAMILY.match(model.strip())
    bare = match.group("rest") if match is not None else model.strip()

    if capability.answers_to == ANSWERS_TO_BARE:
        return bare

    return f"{capability.family}:{bare}"


def _params_from(observed: Mapping[str, object]) -> Mapping[str, str]:
    """Read the effective parameters out of a resolved observation.

    Args:
        observed: The adapter's observation record.

    Returns:
        The parameters, stringified, because a cache-key term is a string and a silent
        ``repr`` of a float would key on a rendering rather than on the value. A family
        that reports no parameters returns an empty mapping, which is a real state: a
        stage with no settings has no settings.

    """
    raw = observed.get("params")
    if not isinstance(raw, Mapping):
        return MappingProxyType({})

    return MappingProxyType({str(key): str(value) for key, value in raw.items()})


def _with_terms(
    resolved: KernelResult[Resolved], terms: CacheKeyTerms
) -> KernelResult[Resolved]:
    """Attach composed terms to a successful resolution.

    Args:
        resolved: A successful resolution.
        terms: The terms to attach.

    Returns:
        The resolution carrying its terms, with the full key recorded in the evidence's
        terms so ``--resolve-only`` reports both the terms and the key they compose.

    Raises:
        ValueError: If ``resolved`` carries no value, which would mean this helper was
            called on a refusal - a programming error rather than a runtime condition.

    """
    if resolved.value is None:
        raise ValueError(
            "_with_terms requires a successful resolution: a refusal has no value to "
            "attach terms to, and attaching them anyway would produce a result that "
            "looks resolved and is not."
        )

    keyed = dataclasses.replace(resolved.value, terms=terms)

    return KernelResult(
        value=keyed,
        evidence=Evidence(
            terms=MappingProxyType(
                {**dict(resolved.evidence.terms), "cache_key": cache_key(terms)}
            ),
            measurements=resolved.evidence.measurements,
            observed=resolved.evidence.observed,
        ),
        reason=None,
    )


def _refused(
    code: str,
    message: str,
    observed: Mapping[str, object],
) -> KernelResult[Resolved]:
    """Build a typed refusal.

    Args:
        code: The reason code, from the closed set (`kernel-cli.md` §5).
        message: The explanation, naming the name that failed.
        observed: The facts a caller may assert on, so a test never parses prose.

    Returns:
        No value and the typed reason. The exit code follows from the code, so this
        module does not decide what a refusal means to a process.

    """
    return KernelResult(
        value=None,
        evidence=Evidence(
            terms=MappingProxyType({"resolved": "false"}),
            measurements=MappingProxyType({}),
            observed=MappingProxyType(dict(observed)),
        ),
        reason=Reason(code=code, message=message),
    )
