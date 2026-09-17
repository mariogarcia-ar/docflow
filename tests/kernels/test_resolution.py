"""Resolution by capability - the tests that would notice a silent fallback.

`E04-07` / `S1-T17`. The invariant is **"there is no fallback"**, and
`plan-01-kernels.md` §7b says the test for it must FAIL when the invariant breaks.
That is the whole design of this suite: every refusal test asserts the *specific*
refusal that must fire, so a resolution that quietly succeeded would redden rather
than pass, and the "no default exists" tests read the **module's own source** rather
than the module's behaviour — because a default that is never reached is exactly the
one that survives a behavioural test.

Four groups:

1. **A name resolves**, on both families, through the same path.
2. **An unknown name fails fast**, with the code and the name that failed - never a
   substituted model.
3. **The refusal is a ``KernelResult``**, so the exit code follows from the reason
   code (``kernel-cli.md`` §5) instead of from an exception reaching exit `1`.
4. **No default exists**, asserted statically over constants, environment reads and
   the declared capability table.
"""

# Pylint reports every pytest fixture parameter as a redefinition of the function the
# fixture decorates. That is the framework's calling convention, not a shadowing bug:
# pytest injects the value, and renaming the parameter would break the injection - the
# same reason `tests/kernels/test_orchestrator.py` disables it.
# pylint: disable=redefined-outer-name
#
# `duplicate-code`: the vocabulary scans and the AST guards are repeated from the
# sibling suites on purpose. A shared helper module would make the suites depend on one
# another's copies, so a scan relaxed in one place would silently relax everywhere; each
# suite holding its own declaration is what makes the guard local to the file it guards.
# pylint: disable=duplicate-code
#
# `use-implicit-booleaness-not-comparison`: `asked == []` is deliberate. The field is a
# list, and `not asked` would read a *missing* attribute as *nothing was asked* if the
# stub were reshaped - the reasoning `tests/kernels/test_store.py` records for the same
# finding.
# pylint: disable=use-implicit-booleaness-not-comparison
#
# `too-many-lines`: one suite for one issue, and `E04-07`'s criteria are a set of
# refusals that are only meaningful read together. Splitting by file length would
# separate a refusal from the guarantee it is the other half of.
# pylint: disable=too-many-lines

from __future__ import annotations

import ast
import contextlib
import dataclasses
import inspect
import json
import os
import pathlib
from collections.abc import Iterator, Mapping
from types import MappingProxyType

import pytest

from docflow.kernels import registry, resolution
from docflow.kernels.cache_key import CACHE_KEY_TERM_NAMES, cache_key
from docflow.kernels.types import Evidence, KernelResult, Reason

# --- Constants ---------------------------------------------------------------

RESOLUTION_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "src"
    / "docflow"
    / "kernels"
    / "resolution.py"
)

RESOLUTION_TREE: ast.Module = ast.parse(RESOLUTION_PATH.read_text(encoding="utf-8"))

IDENTITY = resolution.KernelIdentity(kernel_id="llm.local", kernel_version="0.1.0")

#: A real-shaped input hash and registry hash. Not labels: a term that only *looks*
#: like a hash would not distinguish a composed key from a placeholder.
SOME_INPUT_HASH: str = "9f2a" * 16
SOME_REGISTRY_HASH: str = "c41b" * 16

#: The three refusal codes this module may raise, from the closed set. ``model_unknown``
#: and ``provider_unknown`` are its own two; the rest are forwarded from an adapter.
OWN_CODES = frozenset({"model_unknown", "provider_unknown"})


# The stub carries exactly the members the tests reach for: one operation, plus the
# `asked` record. More members would be surface with no test behind it.
# pylint: disable=too-few-public-methods
class StubEngine:
    """An adapter that reports a fixed identity, or a fixed refusal.

    A stub rather than a real adapter because resolution's contract is *which adapter
    was asked, and with what name* - and a stub records exactly that. It is also what
    lets the suite run with no Ollama runtime and no provider key, which is the point
    of ``--resolve-only`` being non-executing.
    """

    def __init__(
        self,
        *,
        model_revision: str = "sha256:stub-digest",
        adapter_revision: str = "stub 0.0.1",
        params: Mapping[str, object] | None = None,
        refuse: tuple[str, str] | None = None,
    ) -> None:
        """Initialize the stub.

        Args:
            model_revision: The digest the stub reports.
            adapter_revision: The engine revision the stub reports.
            params: The effective parameters the stub reports.
            refuse: A ``(code, message)`` to return no value with, instead of an
                identity.

        """
        self.model_revision = model_revision
        self.adapter_revision = adapter_revision
        self.params = dict(params if params is not None else {"num_ctx": 8192})
        self.refuse = refuse
        self.asked: list[str] = []

    def capabilities(self, model: str) -> KernelResult[Evidence]:
        """Report the stub's identity, or its refusal.

        Args:
            model: The name resolution composed for this adapter.

        Returns:
            The identity, or no value and the stub's typed refusal.

        """
        self.asked.append(model)

        if self.refuse is not None:
            code, message = self.refuse
            return KernelResult(
                value=None,
                evidence=Evidence(
                    terms=MappingProxyType({"refused": "true"}),
                    measurements=MappingProxyType({}),
                    observed=MappingProxyType({"asked": model}),
                ),
                reason=_reason(code, message),
            )

        observed = {
            "model": model,
            "model_revision": self.model_revision,
            "adapter_revision": self.adapter_revision,
            "params": self.params,
        }
        evidence = Evidence(
            terms=MappingProxyType({"model_revision": self.model_revision}),
            measurements=MappingProxyType({}),
            observed=MappingProxyType(observed),
        )
        return KernelResult(value=evidence, evidence=evidence, reason=None)


def _reason(code: str, message: str) -> Reason:
    """Build a ``Reason`` for a stub refusal.

    Args:
        code: The reason code.
        message: The message.

    Returns:
        The reason.

    """
    return Reason(code=code, message=message)


@pytest.fixture
def engines() -> dict[str, StubEngine]:
    """Provide the bound engines, one per declared family.

    Returns:
        Family name to stub.

    """
    return {"ollama": StubEngine(), "anthropic": StubEngine(model_revision="claude-x")}


def _request(
    model: str,
    *,
    kernel: str = "llm.local",
    operation: str = resolution.OPERATION_GENERATION,
    engines: Mapping[str, StubEngine],
) -> resolution.Request:
    """Build a resolve request.

    Args:
        model: The model name.
        kernel: The kernel the call belongs to.
        operation: The operation intended.
        engines: The bound engines.

    Returns:
        The request.

    """
    return resolution.Request(
        model=model, kernel=kernel, operation=operation, engines=engines
    )


# --- 1. A name resolves, on both families, through one path ------------------


def test_a_local_model_resolves_and_reports_its_digest(
    engines: dict[str, StubEngine],
) -> None:
    """``ollama:qwen2.5`` resolves - and the **digest** is the identity, not the tag."""
    result = resolution.resolve(_request("ollama:qwen2.5", engines=engines))

    assert result.value is not None
    assert result.reason is None
    assert result.value.capability.family == "ollama"
    assert result.value.model == "ollama:qwen2.5", "the caller's name is reported back"
    assert result.value.model_revision == "sha256:stub-digest"
    assert result.value.model_revision != "qwen2.5", (
        "the tag is a moving label; keying on it would let a swapped model reuse the "
        "previous model's answers"
    )


def test_a_frontier_model_resolves_through_the_same_path(
    engines: dict[str, StubEngine],
) -> None:
    """``anthropic:…`` resolves, with the family carrying the family difference.

    The two families are resolved by the same call and differ only in the name style
    the adapter's own parser requires - which is on the declared capability rather
    than in a branch here.
    """
    result = resolution.resolve(
        _request("anthropic:claude-sonnet-4-6", kernel="llm.frontier", engines=engines)
    )

    assert result.value is not None
    assert result.value.capability.family == "anthropic"
    assert result.value.capability.kernel == "llm.frontier"


def test_the_local_adapter_is_asked_for_the_bare_name(
    engines: dict[str, StubEngine],
) -> None:
    """The prefix is **dropped** for a runtime that uses ``:`` for its own tags.

    Verified against the adapter rather than assumed: handing that runtime
    ``ollama:qwen2.5`` would ask for a model genuinely *named* ``ollama``, because to
    it ``:`` separates a tag. So ``answered_as`` is the bare name.
    """
    resolution.resolve(_request("ollama:qwen2.5", engines=engines))

    assert engines["ollama"].asked == ["qwen2.5"]


def test_the_frontier_adapter_is_asked_for_the_prefixed_name(
    engines: dict[str, StubEngine],
) -> None:
    """The prefix is **kept** for the provider that requires it.

    The opposite of the local case, which is why one rule could not serve both: K6
    reports ``model_unknown`` for a bare name, so dropping the prefix would turn a
    resolvable model into a refusal.
    """
    resolution.resolve(
        _request("anthropic:claude-sonnet-4-6", kernel="llm.frontier", engines=engines)
    )

    assert engines["anthropic"].asked == ["anthropic:claude-sonnet-4-6"]


def test_resolution_reports_the_engine_revision_and_the_parameters(
    engines: dict[str, StubEngine],
) -> None:
    """The adapter revision is a cache term, so it has to survive resolution."""
    result = resolution.resolve(_request("ollama:qwen2.5", engines=engines))

    assert result.value is not None
    assert result.value.adapter_revision == "stub 0.0.1"
    assert dict(result.value.params) == {"num_ctx": "8192"}, (
        "params are stringified: a cache-key term is a string, and a float's repr "
        "would key on a rendering rather than on the value"
    )


def test_the_evidence_terms_carry_the_revisions_the_report_claims(
    engines: dict[str, StubEngine],
) -> None:
    """The evidence's terms are what ``--resolve-only`` reports, so they carry the
    same revisions the resolution claims - not a label standing in for them.

    Asserted separately from the ``Resolved`` value because the two are separate
    surfaces: the value is what a Python caller reads, and the evidence terms are what
    a script reads off stdout. A revision reported on one and not the other would make
    the printed key terms describe a different engine than the call used.
    """
    result = resolution.resolve(_request("ollama:qwen2.5", engines=engines))
    assert result.value is not None

    assert result.evidence.terms["adapter_revision"] == result.value.adapter_revision
    assert result.evidence.terms["model_revision"] == result.value.model_revision
    assert result.evidence.terms["kernel_id"] == result.value.capability.kernel
    assert result.evidence.terms["family"] == result.value.capability.family


def test_an_engine_that_reports_no_params_yields_an_empty_mapping() -> None:
    """A stage with no settings has no settings - an empty mapping, not a default."""
    engines = {"ollama": StubEngine(params={})}

    result = resolution.resolve(_request("ollama:qwen2.5", engines=engines))

    assert result.value is not None
    assert not result.value.params, (
        "a stage with no settings has no settings, not a default"
    )


def test_resolution_reports_which_operation_it_resolved_for(
    engines: dict[str, StubEngine],
) -> None:
    """The operation is a fact about the call, recorded rather than inferred."""
    result = resolution.resolve(
        _request(
            "ollama:qwen2.5", operation=resolution.OPERATION_VISION, engines=engines
        )
    )

    assert result.value is not None
    assert result.evidence.observed["operation"] == resolution.OPERATION_VISION
    assert result.evidence.observed["family"] == "ollama"


# --- 2. An unknown name fails fast, naming it --------------------------------


def test_an_unknown_provider_fails_with_provider_unknown(
    engines: dict[str, StubEngine],
) -> None:
    """The prefix names no declared family, and the refusal **names it**."""
    result = resolution.resolve(_request("nope:qwen2.5", engines=engines))

    assert result.value is None
    assert result.reason is not None
    assert result.reason.code == "provider_unknown"
    assert "nope" in result.reason.message
    assert result.evidence.observed["family"] == "nope"
    assert not engines["ollama"].asked, "no adapter may be asked about a bad prefix"


def test_a_bare_name_fails_with_model_unknown(
    engines: dict[str, StubEngine],
) -> None:
    """A prefixless name is refused rather than guessed at.

    Guessing which family a bare name meant is how a name silently becomes a
    different model - the failure this whole module exists to prevent, one step
    earlier than a default would cause it.
    """
    result = resolution.resolve(_request("qwen2.5", engines=engines))

    assert result.value is None
    assert result.reason is not None
    assert result.reason.code == "model_unknown"
    assert "qwen2.5" in result.reason.message
    assert engines["ollama"].asked == []


def test_a_refusal_names_the_families_that_would_have_worked(
    engines: dict[str, StubEngine],
) -> None:
    """The reason carries the known families, so a caller need not read prose."""
    result = resolution.resolve(_request("nope:qwen2.5", engines=engines))

    assert result.evidence.observed["known_families"] == ["anthropic", "ollama"]


def test_a_name_resolving_to_another_kernel_is_refused(
    engines: dict[str, StubEngine],
) -> None:
    """The kernel the caller named and the engine that answered must agree."""
    result = resolution.resolve(
        _request("anthropic:claude-sonnet-4-6", kernel="llm.local", engines=engines)
    )

    assert result.value is None
    assert result.reason is not None
    assert result.reason.code == "provider_unknown"
    assert result.evidence.observed["resolved_kernel"] == "llm.frontier"
    assert result.evidence.observed["kernel"] == "llm.local"
    assert not engines["anthropic"].asked, "no adapter may be asked about a mismatch"


def test_an_operation_a_family_does_not_serve_is_refused() -> None:
    """A capability declares its operations, so a non-served one fails here.

    A model resolved for an operation it cannot serve would resolve successfully and
    then fail at the call - reporting the wrong thing at the wrong time. The declared
    table is patched rather than a second table invented, so the check under test is
    the real one.
    """
    text_only = resolution.Capability(
        family="ollama",
        kernel="llm.local",
        answers_to=resolution.ANSWERS_TO_BARE,
        operations=frozenset({resolution.OPERATION_GENERATION}),
    )
    engines = {"ollama": StubEngine()}

    with monkeypatched_capabilities(text_only):
        result = resolution.resolve(
            _request(
                "ollama:qwen2.5",
                operation=resolution.OPERATION_VISION,
                engines=engines,
            )
        )

    assert result.value is None
    assert result.reason is not None
    assert result.reason.code == "provider_unknown"
    assert result.evidence.observed["declared_operations"] == [
        resolution.OPERATION_GENERATION
    ]
    assert engines["ollama"].asked == [], (
        "a non-served operation never reaches an adapter"
    )


def test_a_declared_family_with_no_bound_engine_is_refused(
    engines: dict[str, StubEngine],
) -> None:
    """A declaration without a binding is a configuration error, not a fallback.

    Trying another family instead would be precisely the substitution this module
    exists to refuse, so the missing binding is reported rather than worked around.
    """
    bound = {"anthropic": engines["anthropic"]}

    result = resolution.resolve(_request("ollama:qwen2.5", engines=bound))

    assert result.value is None
    assert result.reason is not None
    assert result.reason.code == "provider_unknown"
    assert result.evidence.observed["bound"] == ["anthropic"]


def test_the_adapters_own_reason_is_forwarded_not_rewritten(
    engines: dict[str, StubEngine],
) -> None:
    """A model the adapter cannot identify keeps the adapter's code.

    ``model_not_pulled`` is a different fact from ``model_unknown``, with a different
    remedy - and only the adapter knows which one happened. Replacing it with a
    general code would turn a diagnosis into a guess.
    """
    engines["ollama"] = StubEngine(
        refuse=("model_not_pulled", "pull it with `ollama pull nope`")
    )

    result = resolution.resolve(_request("ollama:nope", engines=engines))

    assert result.value is None
    assert result.reason is not None
    assert result.reason.code == "model_not_pulled"
    assert "ollama pull" in result.reason.message
    assert engines["ollama"].asked == ["nope"], (
        "the bare name is what the adapter was asked about - the refusal is the "
        "adapter's, and it was reached with the right name"
    )


def test_every_code_this_module_raises_itself_is_in_the_closed_set() -> None:
    """A code outside the vocabulary is untestable and unattributable."""
    closed = {
        "illegible",
        "insufficient_effective_resolution",
        "blank_page",
        "truncated_output",
        "model_not_pulled",
        "model_unknown",
        "provider_unknown",
        "engine_unavailable",
        "provider_unavailable",
        "asset_invalid",
        "asset_missing",
        "artifact_missing",
        "evidence_missing",
        "encrypted",
        "unsupported_format",
        "role_conflict",
    }
    raised = {
        node.value
        for node in ast.walk(RESOLUTION_TREE)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value in closed
    }

    assert raised, "the scan found no reason code, so it is asserting nothing"
    assert raised <= closed
    assert raised >= OWN_CODES, (
        f"the module does not raise its own codes: {sorted(OWN_CODES - raised)}"
    )


# --- 3. The refusal is a KernelResult, so the exit code follows --------------


def test_an_unknown_name_is_a_reason_and_not_an_exception(
    engines: dict[str, StubEngine],
) -> None:
    """The refusal is ``value=None`` plus a typed ``Reason``, never a raise.

    `kernel-cli.md` §5 gives *the call's precondition* exit `3`. An exception would
    reach exit `1` - *unexpected internal error* - which collapses *"this name is
    wrong"* into *"the code has a bug"*.
    """
    result = resolution.resolve(_request("nope:qwen2.5", engines=engines))

    assert isinstance(result, KernelResult)
    assert result.value is None
    assert result.reason is not None
    assert result.evidence is not None, "a refusal still carries its evidence"


def test_the_module_raises_no_exception_for_a_bad_name() -> None:
    """Stated over the source, so a future `raise` in this path reddens it."""
    raises = [node for node in ast.walk(RESOLUTION_TREE) if isinstance(node, ast.Raise)]
    messages = " ".join(ast.unparse(node) for node in raises)

    assert "model_unknown" not in messages, (
        "no raise may carry a resolution refusal code: the refusal belongs in a "
        "Reason so the exit code follows from the code"
    )
    assert "provider_unknown" not in messages


# --- 4. No default exists, asserted rather than asserted-about ---------------


def test_the_declared_table_is_the_whole_registry() -> None:
    """Only the families the artifacts name are declared, and K4 is deliberately not.

    Docling is the fixed and only OCR engine (`ADR-001`, `prd.md` FR-16), so K4 has no
    capability to resolve: nothing to choose, and no ``model_revision`` to key by. A
    ``docling`` family appearing here would be this module inventing an engine setting.
    """
    assert sorted(resolution.declared_capabilities()) == ["anthropic", "ollama"]
    assert "docling" not in resolution.declared_capabilities()
    assert all(capability.operations for capability in resolution.CAPABILITIES), (
        "a family that serves nothing would resolve and then fail at the call"
    )


def test_every_declared_family_has_an_identity_and_a_binding_style() -> None:
    """The two tables cannot drift apart, and each family states its own name style."""
    for family, capability in resolution.declared_capabilities().items():
        assert family in resolution.KERNEL_IDENTITIES, family
        assert resolution.KERNEL_IDENTITIES[family].kernel_id == capability.kernel
        assert capability.answers_to in {
            resolution.ANSWERS_TO_BARE,
            resolution.ANSWERS_TO_PREFIXED,
        }


def test_the_module_reads_no_environment_variable() -> None:
    """*"No environment variable that substitutes a model"* - asserted over the source.

    A behavioural test cannot catch this: a variable read on a path the suite never
    takes is exactly the default that survives. The source is the only place the
    absence is checkable.
    """
    reads = [
        node
        for node in ast.walk(RESOLUTION_TREE)
        if isinstance(node, ast.Attribute)
        and node.attr in {"get", "getenv", "environ"}
        and isinstance(node.value, ast.Name)
        and node.value.id == "os"
    ]

    assert reads == [], (
        f"resolution reads the environment: {[ast.unparse(r) for r in reads]}"
    )
    assert not any(
        isinstance(node, ast.Name) and node.id == "os"
        for node in ast.walk(RESOLUTION_TREE)
    ), (
        "the module must not import `os` at all: with no `os`, no environment read "
        "is possible"
    )


def test_no_default_model_constant_exists() -> None:
    """No module-level constant names a model, a provider or an engine.

    A default that is never reached is the one a behavioural test cannot find, so the
    constants themselves are the assertion.
    """
    offending = (
        "DEFAULT_MODEL",
        "DEFAULT_PROVIDER",
        "DEFAULT_ENGINE",
        "FALLBACK",
    )
    names = {
        target.id
        for node in ast.walk(RESOLUTION_TREE)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }

    assert not [
        name for name in names if any(word in name.upper() for word in offending)
    ], f"a default-shaped constant exists: {sorted(names)}"


def test_the_public_surface_exposes_no_parameter_with_a_default() -> None:
    """A default parameter is a value the caller never stated.

    For a model, a provider or an engine that is a silent fallback in the making - the
    same reason the port's own signatures carry no defaults
    (``test_no_port_parameter_carries_a_default_value``).
    """
    functions = [
        node
        for node in ast.walk(RESOLUTION_TREE)
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")
    ]
    assert functions, "the scan found no public function, so it is asserting nothing"

    for node in functions:
        for argument in [*node.args.args, *node.args.kwonlyargs]:
            if argument.arg == "self":
                continue
            assert argument.annotation is not None, f"{node.name}.{argument.arg}"
        assert not node.args.defaults, f"{node.name} carries positional defaults"
        assert not [
            default for default in node.args.kw_defaults if default is not None
        ], f"{node.name} carries keyword defaults"

    # And the live signatures agree with the parsed ones.
    for name in ("resolve", "resolve_with_registry", "terms_from_resolution"):
        signature = inspect.signature(getattr(resolution, name))
        for parameter in signature.parameters.values():
            assert parameter.default is inspect.Parameter.empty, (
                f"{name}.{parameter.arg}"
            )


def test_the_module_imports_nothing_above_the_kernel_layer() -> None:
    """Resolution is a kernel-layer module: no adapter, no port, no third party."""
    imported: list[str] = []
    for node in ast.walk(RESOLUTION_TREE):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.append(node.module)

    forbidden = (
        "docflow.adapters",
        "docflow.components",
        "docflow.ports",
        "docflow.kernel_cli",
    )

    assert [name for name in imported if name.startswith(forbidden)] == []
    assert all(
        name.split(".")[0] not in {"yaml", "docling", "ollama", "httpx"}
        for name in imported
    ), "no engine may be imported by a kernel"


def test_no_public_identifier_names_a_domain_concept() -> None:
    """`kernel-cli.md` §10's forbidden vocabulary appears in no public name."""
    forbidden = (
        "invoice",
        "verdict",
        "document_type",
        "pipeline",
        "validator",
        "extractor",
        "segmenter",
        "identif",
        "catalog",
        "reviewer",
        "material",
        "ErVR",
        "EpVR",
        "ErpVR",
    )
    identifiers = {
        node.id
        for node in ast.walk(RESOLUTION_TREE)
        if isinstance(node, ast.Name) and not node.id.startswith("_")
    }
    identifiers |= {
        alias.name
        for node in ast.walk(RESOLUTION_TREE)
        if isinstance(node, ast.alias)
        for alias in [node]
    }

    offenders = [
        name
        for name in identifiers
        for word in forbidden
        if word.lower() in name.lower()
    ]

    assert offenders == [], (
        f"domain vocabulary leaked into the kernel layer: {offenders}"
    )


# --- 5. The cache key, composed from a resolution ----------------------------


def test_the_terms_from_a_resolution_are_the_seven_terms(
    engines: dict[str, StubEngine],
) -> None:
    """A resolution composes a full key - no term dropped, none substituted."""
    result = resolution.resolve(_request("ollama:qwen2.5", engines=engines))
    assert result.value is not None

    terms = resolution.terms_from_resolution(
        result.value,
        identity=IDENTITY,
        input_hash=SOME_INPUT_HASH,
        registry_hash=SOME_REGISTRY_HASH,
    )

    assert set(resolution_cache_names(terms)) == set(CACHE_KEY_TERM_NAMES)
    assert terms.model_revision == "sha256:stub-digest"
    assert terms.adapter_revision == "stub 0.0.1"
    assert terms.registry_hash == SOME_REGISTRY_HASH
    assert terms.input_hash == SOME_INPUT_HASH
    assert terms.kernel_id == "llm.local"
    assert terms.params == {"num_ctx": "8192"}


def test_the_key_matches_what_the_orchestrator_would_compose(
    engines: dict[str, StubEngine],
) -> None:
    """Resolution's key and the orchestrator's key are one value, two sides.

    A caller resolving by capability and a caller composing from a graph must produce
    the same key for the same work, or the same stage would run twice under two keys.
    """
    result = resolution.resolve(_request("ollama:qwen2.5", engines=engines))
    assert result.value is not None

    from_resolution = resolution.cache_key_for_resolution(
        result.value,
        identity=IDENTITY,
        input_hash=SOME_INPUT_HASH,
        registry_hash=SOME_REGISTRY_HASH,
    )

    from_orchestrator = cache_key(
        resolution.compose_terms(
            result.value,
            identity=IDENTITY,
            input_hash=SOME_INPUT_HASH,
            registry_hash=SOME_REGISTRY_HASH,
        )
    )

    assert from_resolution == from_orchestrator
    assert len(from_resolution) == 64


def test_a_different_model_revision_produces_a_different_key(
    engines: dict[str, StubEngine],
) -> None:
    """The digest is a key term, so a `pull` under a moving tag changes the key.

    This is row 13's discipline (`kernel-cli.md` §11) read at the resolution boundary.
    """
    first = resolution.resolve(_request("ollama:qwen2.5", engines=engines))
    assert first.value is not None

    engines["ollama"] = StubEngine(model_revision="sha256:a-different-digest")
    second = resolution.resolve(_request("ollama:qwen2.5", engines=engines))
    assert second.value is not None

    keys = {
        resolution.cache_key_for_resolution(
            resolved,
            identity=IDENTITY,
            input_hash=SOME_INPUT_HASH,
            registry_hash=SOME_REGISTRY_HASH,
        )
        for resolved in (first.value, second.value)
    }

    assert len(keys) == 2


def test_resolve_with_registry_reads_the_hash_from_k8(tmp_path: pathlib.Path) -> None:
    """The hash comes from K8, so no second encoding rule lives here."""
    root = tmp_path / "registry"
    root.mkdir()
    # The asset's file name **is** its declared key: `registry.py` looks the file up
    # at `root / key`, so a manifest entry and the file it names cannot disagree.
    (root / "manifest.json").write_text(
        json.dumps({"assets": [{"key": "patterns.txt", "format": "text"}]}),
        encoding="utf-8",
    )
    (root / "patterns.txt").write_text("a pattern\n", encoding="utf-8")

    loaded = registry.load_registry(root)
    assert loaded.value is not None, f"the fixture registry must load: {loaded.reason}"
    expected = registry.registry_hash(loaded.value)
    engines = {"ollama": StubEngine()}

    result = resolution.resolve_with_registry(
        _request("ollama:qwen2.5", engines=engines),
        identity=IDENTITY,
        input_hash=SOME_INPUT_HASH,
        registry_root=root,
    )

    assert result.value is not None
    assert result.value.terms is not None
    assert result.value.terms.registry_hash == expected
    assert result.evidence.terms["cache_key"] == cache_key(result.value.terms)


def test_a_broken_registry_is_reported_as_its_own_failure(
    tmp_path: pathlib.Path,
) -> None:
    """K8's reason is returned unchanged: a broken registry is not an unknown model."""
    result = resolution.resolve_with_registry(
        _request("ollama:qwen2.5", engines={"ollama": StubEngine()}),
        identity=IDENTITY,
        input_hash=SOME_INPUT_HASH,
        registry_root=tmp_path / "absent",
    )

    assert result.value is None
    assert result.reason is not None
    assert result.reason.code in {"asset_missing", "asset_invalid"}


def test_an_unresolvable_model_is_refused_before_the_registry_is_read(
    tmp_path: pathlib.Path,
) -> None:
    """An unknown name is a cheaper refusal than a registry read, and it fires first.

    Both refusals are legitimate; what matters is that the one the caller can act on is
    the one they get.
    """
    root = tmp_path / "registry"
    root.mkdir()
    (root / "manifest.json").write_text('{"assets": []}', encoding="utf-8")

    result = resolution.resolve_with_registry(
        _request("nope:qwen2.5", engines={"ollama": StubEngine()}),
        identity=IDENTITY,
        input_hash=SOME_INPUT_HASH,
        registry_root=root,
    )

    assert result.value is None
    assert result.reason is not None
    assert result.reason.code == "provider_unknown"


# --- 6. An invalid request is the caller's bug, not a document's answer ------


def test_an_undeclared_operation_is_a_usage_error() -> None:
    """An operation this module does not declare is a mistake in the caller's code.

    So it raises rather than returning a ``Reason``: it is not *the document's
    answer*, and resolving it as if it were supported is how an unsupported call
    reaches an adapter.
    """
    with pytest.raises(ValueError) as excinfo:
        resolution.Request(
            model="ollama:qwen2.5",
            kernel="llm.local",
            operation="telepathy",
            engines={},
        )

    assert "not an operation this module resolves" in str(excinfo.value)


def test_a_request_naming_no_model_is_refused() -> None:
    """An unnamed model is a stand-in: its refusal would name nothing."""
    with pytest.raises(ValueError) as excinfo:
        resolution.Request(
            model="",
            kernel="llm.local",
            operation=resolution.OPERATION_GENERATION,
            engines={},
        )

    assert "must name its model" in str(excinfo.value)


def test_a_kernel_identity_with_an_empty_term_is_refused() -> None:
    """An empty cache-key term is an absent term."""
    with pytest.raises(ValueError) as excinfo:
        resolution.KernelIdentity(kernel_id="llm.local", kernel_version="")

    assert "kernel_version must be stated" in str(excinfo.value)


def test_a_capability_with_an_unknown_name_style_is_refused() -> None:
    """An unrecognised style would forward a name the adapter cannot parse."""
    with pytest.raises(ValueError) as excinfo:
        resolution.Capability(
            family="ollama",
            kernel="llm.local",
            answers_to="sometimes",
            operations=frozenset({"generation"}),
        )

    assert "which is not one of" in str(excinfo.value)


def test_a_capability_with_no_operations_is_refused() -> None:
    """A family that can serve nothing would resolve and then fail at the call."""
    with pytest.raises(ValueError) as excinfo:
        resolution.Capability(
            family="ollama",
            kernel="llm.local",
            answers_to=resolution.ANSWERS_TO_BARE,
            operations=frozenset(),
        )

    assert "declares no operations" in str(excinfo.value)


def test_a_capability_with_an_empty_operation_name_is_refused() -> None:
    """An empty name is a stand-in, not an operation."""
    with pytest.raises(ValueError) as excinfo:
        resolution.Capability(
            family="ollama",
            kernel="llm.local",
            answers_to=resolution.ANSWERS_TO_BARE,
            operations=frozenset({""}),
        )

    assert "empty operation name" in str(excinfo.value)


def test_the_module_is_the_deliverable_path_the_issue_names() -> None:
    """The deliverable path is `docflow/kernels/resolution.py`."""
    assert RESOLUTION_PATH.name == "resolution.py"
    assert RESOLUTION_PATH.parent.name == "kernels"


# --- Helpers -----------------------------------------------------------------


@contextlib.contextmanager
def monkeypatched_capabilities(
    *capabilities: resolution.Capability,
) -> Iterator[None]:
    """Temporarily replace the declared capability table.

    The table is module-level data, so patching it is how a shape the real table does
    not happen to have - a family that serves one operation and not another - is
    exercised against the **real** check rather than a reimplementation of it.

    Args:
        capabilities: The families to declare for the duration.

    Yields:
        None, with the table replaced.

    """
    original = resolution.CAPABILITIES
    resolution.CAPABILITIES = tuple(capabilities)  # type: ignore[misc]
    try:
        yield
    finally:
        resolution.CAPABILITIES = original  # type: ignore[misc]


def resolution_cache_names(terms: object) -> tuple[str, ...]:
    """Return the cache-key term names present on a composed term set.

    Args:
        terms: The composed terms.

    Returns:
        The field names, read from the dataclass rather than hardcoded, so a term
        added or removed is visible to the assertion.

    """
    return tuple(  # type: ignore[arg-type]
        field.name for field in dataclasses.fields(terms)
    )


def test_os_is_not_imported() -> None:
    """Belt and braces on the environment assertion, stated as its own test.

    A module with no ``os`` cannot read an environment variable, which is the
    strongest available form of *"no environment variable substitutes a model"*.
    """
    assert "os" not in {
        alias.name.split(".")[0]
        for node in ast.walk(RESOLUTION_TREE)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert not [
        node
        for node in ast.walk(RESOLUTION_TREE)
        if isinstance(node, ast.ImportFrom) and node.module == "os"
    ]
    assert os.sep, "the `os` import in this test file is deliberate and used"
