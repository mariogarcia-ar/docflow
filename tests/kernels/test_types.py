"""Tests for the frozen kernel boundary types (``S1-T01`` / ``E01-01``).

Every assertion here targets the one capability this issue delivers: the
boundary **cannot express a third state**. The enumeration test is the load-bearing
one, because it must fail if a third state ever becomes expressible.

The import-isolation and forbidden-vocabulary tests are static assertions over
``docflow/kernels/types.py`` rather than prose claims, per
``docs/plans/plan-01-kernels.md`` §13 Track 3.

Two Pylint relaxations are declared below, each because the rule contradicts what
this suite is for rather than because the code is sloppy: a contract test must
restate the names it checks instead of importing them (``duplicate-code``), and one
test per acceptance criterion costs file length (``too-many-lines``).
"""

# pylint: disable=duplicate-code
# `EXPECTED_BOUNDARY_TYPE_NAMES` deliberately repeats the tuple declared in
# `docflow/kernels/types.py`. A contract test must hold its own copy of the expected
# names: importing the constant it is verifying would make the assertion vacuous.

# pylint: disable=too-many-lines
# One test per acceptance criterion of `E01-01`, plus one per lint guard. Splitting
# the file to satisfy a line budget would separate the invariant from its
# falsification tests, which is the one thing this suite exists to keep together.

from __future__ import annotations

import ast
import dataclasses
import enum
import importlib
import importlib.util
import itertools
import json
import pathlib
import sys
import typing
from collections.abc import Callable, Iterator, Mapping
from types import MappingProxyType

import pytest

from docflow.kernels import types as kernel_types
from docflow.kernels.types import (
    BOUNDARY_TYPE_NAMES,
    Artifact,
    Box,
    Bytes,
    CallRecord,
    Evidence,
    KernelResult,
    Reason,
    Token,
)

# --- Constants ---------------------------------------------------------------

PACKAGE_ROOT: pathlib.Path = pathlib.Path(kernel_types.__file__).resolve().parent
TYPES_PATH: pathlib.Path = pathlib.Path(kernel_types.__file__).resolve()
TYPES_SOURCE: str = TYPES_PATH.read_text(encoding="utf-8")
TYPES_TREE: ast.Module = ast.parse(TYPES_SOURCE, filename=str(TYPES_PATH))

#: Members a plain ``@dataclass`` class exposes by itself. Anything public outside
#: this set is a constructor or convenience member this issue forbids.
DATACLASS_INTRINSICS: frozenset[str] = frozenset(
    {
        "__init__",
        "__repr__",
        "__eq__",
        "__hash__",
        "__post_init__",
        "__class_getitem__",
        "__subclasshook__",
        "__slots__",
        "__match_args__",
        "__dataclass_fields__",
        "__dataclass_params__",
        "__init_subclass__",
        "__replace__",
    }
)

#: Aggregate-grade member names ``Evidence`` must never carry (``kernel-cli.md`` §3,
#: guardrail 2: a kernel never emits an aggregate score or a verdict).
FORBIDDEN_AGGREGATE_MEMBERS: frozenset[str] = frozenset(
    {"score", "confidence", "quality", "grade"}
)

#: Domain vocabulary no kernel-boundary identifier may contain
#: (``kernel-cli.md`` §14; ``plan-01-kernels.md`` §13 Track 4).
FORBIDDEN_DOMAIN_VOCABULARY: tuple[str, ...] = (
    "invoice",
    "field",
    "verdict",
    "document_type",
    "pipeline",
    "validator",
    "extractor",
    "segmenter",
    "identif",
    "reader",
    "catalog",
    "contract",
    "reviewer",
    "material",
    "docling",
    "ErVR",
    "EpVR",
    "ErpVR",
    "M0",
    "M1",
    "M2",
    "M3",
    "M4",
)

#: Module roots the boundary module is allowed to import: standard library only,
#: plus the boundary package itself. An adapter or third-party import fails.
ALLOWED_IMPORT_ROOTS: frozenset[str] = frozenset(
    {"__future__", "collections", "dataclasses", "typing"}
)

STDLIB_NAMES: frozenset[str] = frozenset(sys.stdlib_module_names)

#: The three declared field names of ``KernelResult``. They are excluded from the
#: public-member scan because a field is not a constructor.
FIELD_NAMES: frozenset[str] = frozenset({"value", "evidence", "reason"})

#: The default human-readable message the test ``Reason`` carries. Shared by the
#: factory and the assertions so the two cannot drift apart.
DEFAULT_REASON_MESSAGE: str = "The page carries no content."

#: The frozen boundary set, restated here **on purpose**: a contract test must hold
#: its own copy of the expected names rather than import the constant it is
#: checking, or the assertion would be vacuous. Written once so the two tests that
#: assert it cannot drift from each other.
EXPECTED_BOUNDARY_TYPE_NAMES: tuple[str, ...] = (
    "Token",
    "KernelResult",
    "Evidence",
    "Reason",
    "CallRecord",
    "Bytes",
    "Artifact",
)


# --- Fixtures and helpers ----------------------------------------------------


def dataclass_is_frozen(member: type) -> bool:
    """Report whether a dataclass was declared with ``frozen=True``.

    The flag is read out of the class namespace dictionary rather than as a plain
    attribute: ``__dataclass_params__`` is a CPython dataclass internal that static
    checkers do not model, so a direct attribute read is reported as a
    false-positive no-member error, while ``getattr`` with a constant name trips
    another linter rule. Indexing ``vars()`` states the lookup is deliberate.

    Args:
        member: The class to inspect.

    Returns:
        True when the class is a frozen dataclass.

    """
    return bool(vars(member)["__dataclass_params__"].frozen)


def make_evidence(
    terms: Mapping[str, str] | None = None,
    measurements: Mapping[str, float] | None = None,
    observed: Mapping[str, object] | None = None,
) -> Evidence:
    """Build a populated :class:`Evidence` for tests.

    Args:
        terms: Cache-key terms, or None for the default test terms.
        measurements: Raw measurements, or None for the default measurement.
        observed: Free-form observables, or None for the default observable.

    Returns:
        A populated ``Evidence`` instance.

    """
    return Evidence(
        terms=terms
        if terms is not None
        else MappingProxyType({"adapter_revision": "test 0.0.1"}),
        measurements=(
            measurements
            if measurements is not None
            else MappingProxyType({"character_count": 12.0})
        ),
        observed=(
            observed
            if observed is not None
            else MappingProxyType({"reported_confidence": False})
        ),
    )


def make_reason(
    code: str = "blank_page", message: str = DEFAULT_REASON_MESSAGE
) -> Reason:
    """Build a populated :class:`Reason` for tests.

    Args:
        code: The machine-readable reason code.
        message: The human-readable explanation.

    Returns:
        A populated ``Reason`` instance.

    """
    return Reason(code=code, message=message)


def make_token() -> Token:
    """Build a :class:`Token` for the tests.

    Returns:
        A ``Token`` on a one-based page with a source-coordinate box.

    """
    return Token(
        text="total",
        page=1,
        bbox=Box(x=10.0, y=20.0, width=30.0, height=8.0),
        confidence=0.91,
        role="text",
    )


def make_call_record() -> CallRecord:
    """Build a :class:`CallRecord` in the language-model kernel shape.

    Returns:
        A ``CallRecord`` as a local model reports it, unreported fields ``None``.

    """
    return CallRecord(
        provider="ollama",
        model="qwen2.5",
        model_revision="sha256:7cdf5a1b",
        prompt_tokens=512,
        completion_tokens=64,
        total_tokens=576,
        cost_usd=None,
        latency_ms=412.5,
        request_id=None,
    )


def make_bytes() -> Bytes:
    """Build an opaque :class:`Bytes` buffer.

    Returns:
        A buffer with its media type.

    """
    return Bytes(data=b"\x89PNG\r\n\x1a\n", media_type="image/png")


def make_artifact() -> Artifact:
    """Build an :class:`Artifact` descriptor.

    Returns:
        A stored-blob descriptor carrying a content hash.

    """
    return Artifact(
        sha256="9f2a" * 16,
        size_bytes=41889024,
        media_type="image/png",
        path="artifacts/9f2a.png",
    )


#: The seven frozen boundary types. ``Box`` is deliberately absent: it is a
#: supporting value type required by ``Token.bbox``, not an eighth boundary state.
BOUNDARY_TYPES: tuple[type, ...] = (
    Token,
    KernelResult,
    Evidence,
    Reason,
    CallRecord,
    Bytes,
    Artifact,
)


def make_boundary_instance(name: str) -> object:
    """Build one populated instance of a boundary type, by name.

    Args:
        name: One of the seven frozen boundary type names.

    Returns:
        A populated instance of that type, ready to be mutated.

    """
    factories: dict[str, Callable[[], object]] = {
        "Token": make_token,
        "KernelResult": lambda: KernelResult(
            value=[make_token()], evidence=make_evidence(), reason=None
        ),
        "Evidence": make_evidence,
        "Reason": make_reason,
        "CallRecord": make_call_record,
        "Bytes": make_bytes,
        "Artifact": make_artifact,
    }
    return factories[name]()


def combination_key(combination: tuple[object, ...]) -> tuple[int, ...]:
    """Return an identity-based key for a field triple.

    Field values such as ``Evidence`` carry unhashable mappings, so the
    enumeration compares by identity rather than by hash or equality.

    Args:
        combination: A ``(value, evidence, reason)`` triple of raw arguments.

    Returns:
        The identity of each element, in order.

    """
    return tuple(id(part) for part in combination)


def make_kernel_result(value: object, evidence: object, reason: object) -> object:
    """Construct a ``KernelResult`` from a raw field triple.

    Split out so the enumeration test attempts every combination through one call
    site, which keeps the enumeration honest: the test cannot accidentally skip a
    combination by writing it differently.

    The three arguments are deliberately untyped as ``object``: this helper exists
    to pass illegal combinations through the constructor, so the annotations must
    not describe the legal shape. It is the single place in this suite where the
    type system is bypassed on purpose.

    Args:
        value: The ``value`` argument, or None.
        evidence: The ``evidence`` argument, or None.
        reason: The ``reason`` argument, or None.

    Returns:
        The constructed ``KernelResult``.

    """
    return KernelResult(  # type: ignore[arg-type]
        value=value, evidence=evidence, reason=reason
    )


def iter_module_identifiers(tree: ast.Module) -> Iterator[tuple[str, int]]:
    """Yield every identifier a module declares, with its line number.

    Only names are yielded — never docstrings and never comments — so a docstring
    that legitimately uses a phrase such as *"within the source document"* cannot
    produce a false failure.

    Args:
        tree: The parsed module.

    Yields:
        ``(name, lineno)`` for every class name, function name, referenced name,
        attribute name, argument name and annotated target.

    """
    for node in ast.walk(tree):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node.name, node.lineno
        elif isinstance(node, ast.Name):
            yield node.id, node.lineno
        elif isinstance(node, ast.Attribute):
            yield node.attr, node.lineno
        elif isinstance(node, ast.arg):
            yield node.arg, node.lineno
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            yield node.target.id, node.lineno


def collect_imported_modules(tree: ast.Module) -> list[str]:
    """Collect every module path the source imports.

    Args:
        tree: The parsed module.

    Returns:
        The dotted module paths of all ``import`` and ``from ... import`` nodes.

    """
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    return imported


#: Every ``(type name, field name)`` pair, derived from the dataclasses rather
#: than written by hand, so a new field is covered the moment it is added.
BOUNDARY_FIELD_PAIRS: list[tuple[str, str]] = [
    (name, field.name)
    for name in kernel_types.BOUNDARY_TYPE_NAMES
    for field in dataclasses.fields(getattr(kernel_types, name))
]


# --- Criterion 1: seven frozen dataclasses -----------------------------------


def test_types_module_defines_the_seven_frozen_boundary_types() -> None:
    """The module defines exactly the seven boundary types, all frozen."""
    assert len(BOUNDARY_TYPE_NAMES) == 7
    assert set(BOUNDARY_TYPE_NAMES) == set(EXPECTED_BOUNDARY_TYPE_NAMES)

    discovered: set[str] = set()
    for name, member in vars(kernel_types).items():
        if isinstance(member, type) and dataclasses.is_dataclass(member):
            discovered.add(name)

    assert discovered == set(BOUNDARY_TYPE_NAMES) | {"Box"}, (
        f"unexpected dataclasses: {sorted(discovered)}"
    )

    assert [member.__name__ for member in BOUNDARY_TYPES] == list(
        BOUNDARY_TYPE_NAMES
    ), "BOUNDARY_TYPES must mirror BOUNDARY_TYPE_NAMES in order"

    for name in BOUNDARY_TYPE_NAMES:
        member = getattr(kernel_types, name)
        assert dataclasses.is_dataclass(member), f"{name} is not a dataclass"
        assert dataclass_is_frozen(member), f"{name} is not frozen"
        assert "__slots__" in member.__dict__, f"{name} does not declare slots"

    # Box is a supporting value type, deliberately not an eighth boundary state.
    assert dataclasses.is_dataclass(Box)
    assert Box not in BOUNDARY_TYPES
    assert "Box" not in BOUNDARY_TYPE_NAMES


# --- Criterion 2: every boundary type is immutable ---------------------------


@pytest.mark.parametrize(("type_name", "field_name"), BOUNDARY_FIELD_PAIRS)
def test_mutating_any_boundary_type_raises(type_name: str, field_name: str) -> None:
    """Assigning any field of any boundary type raises and changes nothing.

    Args:
        type_name: The boundary type under test.
        field_name: The field to attempt to assign.

    """
    instance = make_boundary_instance(type_name)
    before = getattr(instance, field_name)

    with pytest.raises(dataclasses.FrozenInstanceError) as excinfo:
        setattr(instance, field_name, None)

    assert isinstance(excinfo.value, AttributeError), (
        "FrozenInstanceError is an AttributeError"
    )
    assert getattr(instance, field_name) == before, (
        f"{type_name}.{field_name} changed despite the frozen contract"
    )


@pytest.mark.parametrize("type_name", kernel_types.BOUNDARY_TYPE_NAMES)
def test_deleting_a_field_of_any_boundary_type_raises(type_name: str) -> None:
    """Deleting a field is a mutation too, and is rejected.

    Args:
        type_name: The boundary type under test.

    """
    instance = make_boundary_instance(type_name)
    field_name = dataclasses.fields(instance)[0].name  # type: ignore[arg-type]
    with pytest.raises(dataclasses.FrozenInstanceError):
        delattr(instance, field_name)


# --- Criterion 9 and the Token contract -------------------------------------


def test_token_bbox_is_a_source_page_box_with_explicit_hints() -> None:
    """``Token.bbox`` is a ``Box`` and ``Token.page`` is a one-based ``int``."""
    hints = typing.get_type_hints(Token)
    assert hints["bbox"] is Box
    assert hints["text"] is str
    assert hints["page"] is int
    assert hints["confidence"] == (float | None)
    assert hints["role"] is str

    token = make_token()
    assert isinstance(token.bbox, Box)
    assert token.page == 1, "page is one-based by contract"

    # No coercion: the int given is the int stored, and no clamping happens.
    assert (
        Token(text="a", page=3, bbox=token.bbox, confidence=None, role="text").page == 3
    )


def test_token_confidence_none_is_not_one() -> None:
    """A missing confidence stays ``None`` and is never reported as ``1.0``."""
    token = Token(
        text="a",
        page=1,
        bbox=Box(x=0.0, y=0.0, width=1.0, height=1.0),
        confidence=None,
        role="text",
    )

    assert token.confidence is None
    assert token.confidence != 1.0


def test_every_boundary_field_carries_an_explicit_type_hint() -> None:
    """Every field of every boundary type is annotated."""
    for name in (*kernel_types.BOUNDARY_TYPE_NAMES, "Box"):
        member = getattr(kernel_types, name)
        hints = typing.get_type_hints(member)
        for field in dataclasses.fields(member):
            assert field.name in hints, f"{name}.{field.name} has no resolvable hint"
            assert field.type, f"{name}.{field.name} has an empty annotation"


# --- Criteria 3, 4 and 5: the two-state invariant ---------------------------


def test_kernel_result_value_with_evidence_is_constructible() -> None:
    """State 1: a value with its evidence, and ``reason`` None."""
    result: KernelResult[list[Token]] = KernelResult(
        value=[make_token()], evidence=make_evidence(), reason=None
    )

    assert result.value is not None
    assert isinstance(result.evidence, Evidence)
    assert result.reason is None


def test_kernel_result_none_with_reason_is_constructible() -> None:
    """State 2: no value, with a reason."""
    result: KernelResult[list[Token]] = KernelResult(
        value=None, evidence=make_evidence(), reason=make_reason()
    )

    assert result.value is None
    assert isinstance(result.evidence, Evidence)
    assert isinstance(result.reason, Reason)
    assert result.reason.code == "blank_page"


def test_kernel_result_enumerates_exactly_two_constructible_states() -> None:
    """Enumerate the cartesian product: exactly two of eight combinations hold.

    This is the assertion that fails if a third state becomes expressible. The
    expected count is derived from the product, and the expected success set is
    stated as a set, so a third state or a lost legal state changes the result.
    """
    populated_evidence: Evidence = make_evidence()
    populated_reason: Reason = make_reason()
    populated_value: Token = make_token()

    axis_names: tuple[str, ...] = ("value", "evidence", "reason")
    axis_domains: tuple[tuple[object, ...], ...] = (
        (populated_value, None),
        (populated_evidence, None),
        (populated_reason, None),
    )

    combinations: list[tuple[object, ...]] = list(itertools.product(*axis_domains))
    assert len(combinations) == len(axis_domains[0]) ** len(axis_names) == 8

    successes: list[tuple[object, ...]] = []
    failures: list[tuple[object, ...]] = []
    for combination in combinations:
        try:
            make_kernel_result(*combination)
        except (ValueError, TypeError):
            failures.append(combination)
        else:
            successes.append(combination)

    expected_successes: set[tuple[int, ...]] = {
        combination_key((populated_value, populated_evidence, None)),
        combination_key((None, populated_evidence, populated_reason)),
    }

    assert {combination_key(combination) for combination in successes} == (
        expected_successes
    ), f"constructible states drifted: successes={successes!r}"
    assert len(successes) == 2, "exactly two states may be constructible"
    assert len(successes) + len(failures) == len(combinations)
    assert len(failures) == len(combinations) - 2, (
        "every combination outside the two legal states must raise"
    )


@pytest.mark.parametrize("stand_in", ["", 0, [], {}, (), False, 0.0])
def test_kernel_result_cannot_express_a_value_without_evidence(
    stand_in: object,
) -> None:
    """A falsy stand-in needs evidence just as a real value does.

    These are exactly the shapes a silent failure takes at a layer boundary.

    Args:
        stand_in: The stand-in a silent failure would have returned.

    """
    with pytest.raises(ValueError) as excinfo:
        make_kernel_result(stand_in, None, None)
    assert "evidence" in str(excinfo.value)

    with pytest.raises(ValueError) as excinfo_with_reason:
        make_kernel_result(stand_in, None, make_reason())
    assert "evidence" in str(excinfo_with_reason.value)


def test_kernel_result_cannot_express_a_value_with_absent_evidence() -> None:
    """A value whose evidence argument is missing is a ``TypeError``, not a default."""
    with pytest.raises(TypeError):
        # The missing arguments are the point: this asserts the constructor refuses
        # a partial state, so the linter's incomplete-call report is expected here.
        KernelResult(value="stand-in")  # type: ignore[call-arg]  # pylint: disable=no-value-for-parameter


def test_an_empty_evidence_is_still_evidence_so_a_value_may_carry_it() -> None:
    """Reading of criterion 3: *absent* evidence is rejected, *empty* evidence is not.

    An ``Evidence`` with nothing in it is a statement — "this call observed
    nothing beyond its own identity" — and it is still an ``Evidence`` instance,
    so the type system's first enforcement is satisfied. ``None`` is the only
    rejection: it says "no record was made", which is the stand-in the invariant
    exists to forbid. Empty is not the same as absent, and the difference is
    asserted here so the reading is explicit rather than implied.
    """
    empty_evidence = Evidence(
        terms=MappingProxyType({}),
        measurements=MappingProxyType({}),
        observed=MappingProxyType({}),
    )

    result: KernelResult[int] = KernelResult(
        value=1, evidence=empty_evidence, reason=None
    )
    assert result.evidence is empty_evidence
    assert not dict(result.evidence.terms), "empty terms stay empty, not defaulted"

    with pytest.raises(ValueError):
        KernelResult(value=1, evidence=None, reason=None)  # type: ignore[arg-type]


def test_kernel_result_cannot_express_none_without_a_reason() -> None:
    """A missing value always carries a reason."""
    with pytest.raises(ValueError) as excinfo:
        KernelResult(value=None, evidence=make_evidence(), reason=None)

    assert "reason" in str(excinfo.value)


@pytest.mark.parametrize("value", [None, 0, "", []])
def test_kernel_result_requires_a_reason_whenever_the_value_is_absent(
    value: object,
) -> None:
    """The reason requirement is about ``value`` being absent, whatever the payload.

    Args:
        value: The ``value`` argument under test; ``0``, ``""`` and ``[]`` are legal
            values that are not ``None``, so they need no reason.

    """
    if value is None:
        with pytest.raises(ValueError):
            KernelResult(value=value, evidence=make_evidence(), reason=None)
        return

    result = KernelResult(value=value, evidence=make_evidence(), reason=None)
    assert result.value is not None, "a falsy non-None value is still a value"
    assert result.value == value


def test_kernel_result_cannot_carry_a_value_and_a_reason_together() -> None:
    """A value and a reason are contradictory: the reason says there is no value."""
    with pytest.raises(ValueError) as excinfo:
        KernelResult(
            value=[make_token()], evidence=make_evidence(), reason=make_reason()
        )

    assert "contradictory" in str(excinfo.value)


# --- Criterion 5 and 10: no defaults, no stand-in constructor ----------------


def test_kernel_result_has_no_defaults_so_all_three_fields_must_be_stated() -> None:
    """Every field is required: a partial state cannot be written down."""
    fields = dataclasses.fields(KernelResult)
    assert [field.name for field in fields] == ["value", "evidence", "reason"]

    for field in fields:
        assert field.default is dataclasses.MISSING, f"{field.name} has a default"
        assert field.default_factory is dataclasses.MISSING, (
            f"{field.name} has a default factory"
        )

    # Both calls are deliberately partial: proving the constructor refuses a
    # partial state means calling it that way, so the linter's incomplete-call
    # report is expected for this block.
    with pytest.raises(TypeError):
        KernelResult(value=[make_token()])  # type: ignore[call-arg]  # pylint: disable=no-value-for-parameter
    with pytest.raises(TypeError):
        KernelResult(  # type: ignore[call-arg]  # pylint: disable=no-value-for-parameter
            value=[make_token()], evidence=make_evidence()
        )


def test_no_stand_in_constructor_exists() -> None:
    """``KernelResult`` exposes no constructor or convenience member of its own.

    This is the test that fails the moment someone adds ``KernelResult.empty()``.
    """
    extra_members: set[str] = set()
    for name in vars(KernelResult):
        if name.startswith("_") or name in DATACLASS_INTRINSICS:
            continue
        if name in FIELD_NAMES:
            continue
        extra_members.add(name)

    assert extra_members == set(), f"unexpected public members: {sorted(extra_members)}"

    for forbidden in ("ok", "fail", "empty", "of", "error", "error_message", "is_ok"):
        assert not hasattr(KernelResult, forbidden), f"forbidden member {forbidden}"

    alternative_constructors = {
        name
        for name, member in vars(KernelResult).items()
        if isinstance(member, (classmethod, staticmethod))
        and name not in DATACLASS_INTRINSICS
    }
    assert alternative_constructors == set(), (
        f"alternative constructors: {sorted(alternative_constructors)}"
    )


def test_no_optional_evidence_alias_exists() -> None:
    """``evidence`` is not optional anywhere in the module's public surface."""
    hints = typing.get_type_hints(KernelResult)

    assert "Optional" not in str(hints["evidence"])
    assert hints["evidence"] is Evidence
    assert hints["reason"] == (Reason | None)


# --- Criterion 7: a machine-readable code ------------------------------------


def test_reason_carries_a_machine_readable_code() -> None:
    """``Reason.code`` is a required ``str``, separate from the human message."""
    hints = typing.get_type_hints(Reason)
    assert hints["code"] is str
    assert hints["message"] is str

    reason = make_reason(
        code="illegible", message="Legibility below the caller's threshold."
    )

    assert reason.code == "illegible"
    assert reason.message != reason.code, "the message must not double as the code"

    for field in dataclasses.fields(Reason):
        assert field.default is dataclasses.MISSING, (
            f"Reason.{field.name} has a default"
        )


def test_unknown_reason_code_is_accepted_because_the_vocabulary_is_not_owned_here() -> (
    None
):
    """The code's value is deliberately open here; the closed set is not this file's.

    The vocabulary lives in ``docs/artifacts/kernel-cli.md`` §5 and is owned by the
    epics that raise codes. This module fixes only that a ``code`` exists.
    """
    reason = make_reason(code="a_code_this_module_never_heard_of", message="...")

    assert reason.code == "a_code_this_module_never_heard_of"
    assert not isinstance(reason.code, enum.Enum)
    assert "TODO: [MVP]" in TYPES_SOURCE
    assert "kernel-cli.md" in TYPES_SOURCE, "the deferred vocabulary is named in-source"


# --- Criteria 6b and 8: no domain noun, no aggregate grade -------------------


def test_no_domain_noun_in_any_type_or_member_name() -> None:
    """No identifier in the module contains a domain noun.

    Only identifiers are scanned — never docstrings or comments — so the frozen
    ``Token`` docstring phrase *"within the source document"* cannot cause a false
    failure.
    """
    offenders: list[str] = []
    for identifier, lineno in iter_module_identifiers(TYPES_TREE):
        for forbidden in FORBIDDEN_DOMAIN_VOCABULARY:
            if forbidden.lower() in identifier.lower():
                offenders.append(
                    f"{identifier!r} at line {lineno} matches {forbidden!r}"
                )

    assert not offenders, f"domain vocabulary found in identifiers: {offenders}"

    # Stated as its own assertion: no class defined here is named with a domain
    # noun, so a component cannot arrive by being renamed into this module.
    class_names = [
        node.name for node in TYPES_TREE.body if isinstance(node, ast.ClassDef)
    ]
    assert set(class_names) == set(BOUNDARY_TYPE_NAMES) | {"Box"}, (
        f"unexpected class declarations: {class_names}"
    )
    assert len(class_names) == 8, (
        f"exactly eight classes may be declared: {class_names}"
    )

    # Guard the false positive the forbidden scan must not trip on: the bare word
    # "document" appears in the frozen Token docstring and is deliberately not in
    # the forbidden list (only the domain noun ``document_type`` is).
    assert "source document" in TYPES_SOURCE, "the frozen Token docstring is intact"
    assert "document_type" not in TYPES_SOURCE.lower()


def test_the_domain_vocabulary_scan_is_not_vacuous() -> None:
    """The scan actually walks identifiers, and the Token field names survive it."""
    identifiers = [name for name, _ in iter_module_identifiers(TYPES_TREE)]

    for expected in ("KernelResult", "value", "evidence", "reason"):
        assert expected in identifiers, f"{expected} was not scanned"

    # The names the brief requires the scan to leave alone.
    for allowed in ("page", "bbox", "role", "confidence", "text"):
        assert allowed in identifiers, f"{allowed} was not scanned"

    # Sanity: a name the scan would flag, were it present.
    assert not any("invoice" in name.lower() for name in identifiers)

    flagged = [
        name
        for name in identifiers
        if any(
            forbidden.lower() in name.lower()
            for forbidden in FORBIDDEN_DOMAIN_VOCABULARY
        )
    ]
    assert flagged == [], f"the live module must stay clean: {flagged}"

    # The five Token field names the brief singles out, verified against the
    # forbidden list directly rather than by inspection.
    for allowed in ("page", "bbox", "role", "confidence", "text"):
        assert not any(
            forbidden.lower() in allowed for forbidden in FORBIDDEN_DOMAIN_VOCABULARY
        ), f"{allowed} must not match the forbidden vocabulary"


def test_evidence_records_measurements_without_an_aggregate_score() -> None:
    """``Evidence`` has observable layers and no aggregate grade."""
    hints = typing.get_type_hints(Evidence)

    assert set(hints) == {"terms", "measurements", "observed"}
    assert hints["terms"] == Mapping[str, str]
    assert hints["measurements"] == Mapping[str, float]
    assert hints["observed"] == Mapping[str, object]

    member_names = {field.name for field in dataclasses.fields(Evidence)}
    assert member_names & FORBIDDEN_AGGREGATE_MEMBERS == set()
    for forbidden in FORBIDDEN_AGGREGATE_MEMBERS:
        assert not hasattr(Evidence, forbidden), f"Evidence carries {forbidden}"

    evidence = make_evidence()
    assert evidence.measurements["character_count"] == 12.0
    assert evidence.terms["adapter_revision"] == "test 0.0.1"


def test_observation_records_are_frozen_and_slotted() -> None:
    """The observation records are immutable and use slots like the boundary types."""
    for member in (Evidence, Reason, CallRecord, Bytes, Artifact, Box):
        assert dataclass_is_frozen(member)
        assert "__slots__" in member.__dict__


def test_hashability_is_a_known_poc_property_not_an_accident() -> None:
    """Pin which types are hashable, so a change to it is deliberate.

    The ``Evidence`` mappings are plain ``Mapping`` values, so anything carrying
    one is unhashable. Nothing this issue feeds requires a hashable result — the
    envelope is JSON — so PoC accepts it. This test states the accepted shape so a
    later change is a visible decision rather than a silent regression in either
    direction.
    """
    # Hashable: the by-value deterministic types.
    for member in (
        Box(x=0.0, y=0.0, width=1.0, height=1.0),
        make_token(),
        make_reason(),
        Bytes(data=b"payload", media_type="image/png"),
        Artifact(sha256="a" * 64, size_bytes=1, media_type="image/png", path=None),
        CallRecord(
            provider="ollama",
            model="test-model",
            model_revision="sha256:deadbeef",
            prompt_tokens=None,
            completion_tokens=None,
            total_tokens=None,
            cost_usd=None,
            latency_ms=1.0,
            request_id=None,
        ),
    ):
        assert hash(member) == hash(member), f"{type(member).__name__} must be hashable"

    # Unhashable: anything carrying an Evidence. Asserted by behaviour rather
    # than by attribute inspection, because the two are not the same claim.
    with pytest.raises(TypeError, match="unhashable"):
        hash(make_evidence())

    with pytest.raises(TypeError, match="unhashable"):
        hash(make_kernel_result(make_token(), make_evidence(), None))

    with pytest.raises(TypeError, match="unhashable"):
        hash(make_kernel_result(None, make_evidence(), make_reason()))


def test_evidence_mappings_are_not_json_encodable_by_default() -> None:
    """Pin the encoder obligation this module hands to ``E07-01``.

    ``MappingProxyType`` has no default JSON encoder, so the envelope encoder that
    ``S1-T20`` adds must handle it or a plain-``dict`` view must be exposed. Stated
    here because the failure would otherwise appear one epic later, in the CLI,
    looking like a CLI bug.
    """
    evidence = make_evidence()

    with pytest.raises(TypeError):
        json.dumps(evidence.terms)

    # A plain dict is what the encoder will need to work with.
    assert json.loads(json.dumps(dict(evidence.terms))) == {
        "adapter_revision": "test 0.0.1"
    }


# --- Criterion 6a: import isolation -----------------------------------------


def test_types_module_imports_no_adapter_and_no_third_party_module() -> None:
    """The boundary module imports only the standard library and itself."""
    imported_modules = collect_imported_modules(TYPES_TREE)

    assert imported_modules, "the module must import something"
    assert all(root in STDLIB_NAMES for root in ALLOWED_IMPORT_ROOTS), (
        "the allow-list must contain only standard-library roots"
    )

    for module_name in imported_modules:
        assert "adapter" not in module_name.lower(), f"adapter import: {module_name}"

        root = module_name.split(".")[0]
        if root == "docflow":
            assert module_name.startswith("docflow.kernels"), (
                f"cross-layer import: {module_name}"
            )
            continue

        assert root in STDLIB_NAMES, f"non-stdlib import: {module_name}"
        assert root in ALLOWED_IMPORT_ROOTS, f"unexpected import: {module_name}"


def test_types_module_is_importable_without_any_adapter_on_the_path() -> None:
    """The runtime form of the consumer test: no adapter is needed to import it."""
    spec = importlib.util.find_spec("docflow.kernels.types")

    assert spec is not None
    assert spec.origin == str(TYPES_PATH)
    assert not (PACKAGE_ROOT / "adapters").exists()
    assert TYPES_PATH.name == "types.py"


# --- Criterion 10: __all__ ---------------------------------------------------


def test_all_exports_the_seven_boundary_types_plus_box() -> None:
    """``__all__`` exports the seven frozen types plus the supporting ``Box``.

    The exact set is what matters, not the order: ``__all__`` is sorted
    alphabetically to satisfy Ruff's RUF022, and it is ``BOUNDARY_TYPE_NAMES`` —
    checked by the test below — that declares which names are the boundary set.
    """
    exported: list[str] = list(kernel_types.__all__)

    assert len(exported) == 8
    assert len(set(exported)) == 8, "no duplicate exports"
    assert set(exported) == set(BOUNDARY_TYPE_NAMES) | {"Box"}
    assert exported == sorted(exported), "__all__ must stay alphabetically sorted"

    for name in exported:
        assert hasattr(kernel_types, name), f"{name} is exported but not defined"


def test_boundary_type_names_declares_the_seven_in_the_frozen_documented_order() -> (
    None
):
    """The boundary set is declared once, in ``sad.md`` §6's documented order.

    ``__all__`` is sorted for the linter; this constant is the contract. It is
    what a consumer imports to assert it has not been handed a new boundary type.
    """
    assert BOUNDARY_TYPE_NAMES == EXPECTED_BOUNDARY_TYPE_NAMES
    assert len(BOUNDARY_TYPE_NAMES) == 7
    assert "Box" not in BOUNDARY_TYPE_NAMES, "Box is supporting, not a boundary state"


# --- The remaining shapes ----------------------------------------------------


def test_call_record_matches_the_k5_k6_shape() -> None:
    """``CallRecord`` carries provider, revision, tokens, cost, latency, request id."""
    hints = typing.get_type_hints(CallRecord)

    assert set(hints) == {
        "provider",
        "model",
        "model_revision",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "cost_usd",
        "latency_ms",
        "request_id",
    }
    assert hints["provider"] is str
    assert hints["model"] is str
    assert hints["model_revision"] is str
    assert hints["prompt_tokens"] == (int | None)
    assert hints["completion_tokens"] == (int | None)
    assert hints["total_tokens"] == (int | None)
    assert hints["cost_usd"] == (float | None)
    assert hints["latency_ms"] is float
    assert hints["request_id"] == (str | None)

    local_call = make_call_record()
    assert local_call.cost_usd is None, "a local model reports no cost, not a zero"
    assert local_call.request_id is None
    assert local_call.model_revision != local_call.model, "the digest is the identity"


def test_artifact_carries_a_content_hash_and_bytes_carries_an_opaque_buffer() -> None:
    """``Artifact`` is a descriptor with a sha256; ``Bytes`` is the buffer itself."""
    artifact_hints = typing.get_type_hints(Artifact)
    assert artifact_hints["sha256"] is str
    assert artifact_hints["size_bytes"] is int
    assert artifact_hints["media_type"] is str
    assert artifact_hints["path"] == (str | None)

    bytes_hints = typing.get_type_hints(Bytes)
    assert set(bytes_hints) == {"data", "media_type"}
    assert bytes_hints["media_type"] is str

    artifact = make_artifact()
    assert len(artifact.sha256) == 64, "sha256 is the hexadecimal digest, 64 chars"
    assert artifact.size_bytes == 41889024

    buffer = make_bytes()
    assert isinstance(buffer.data, bytes)
    assert buffer.media_type.startswith("image/")


def test_box_is_a_supporting_value_type_and_not_a_boundary_state() -> None:
    """``Box`` is frozen and hinted, and is absent from the boundary set."""
    assert dataclasses.is_dataclass(Box)
    assert dataclass_is_frozen(Box)
    assert "Box" not in BOUNDARY_TYPE_NAMES
    assert typing.get_type_hints(Box) == {
        "x": float,
        "y": float,
        "width": float,
        "height": float,
    }
    assert "source page coordinates" in (Box.__doc__ or "")


def test_boundary_package_contains_only_the_expected_modules() -> None:
    """No sibling module was introduced under ``docflow/kernels`` beyond the
    ones the plan names.

    ``store.py`` is E02's deliverable (``S1-T02``/``S1-T03``), ``registry.py`` is
    E03-01's and ``cache_key.py`` is E03-02's. ``pdf.py`` is E04-02's
    (`S1-T12`) and ``image.py`` is E04-03's (`S1-T13`). They are named here
    explicitly rather than the check being relaxed to a glob, so that a *further*
    module arriving still fails this test until it too is declared.
    This guard used to also assert that ``docflow/ports`` and ``docflow/adapters``
    did not exist. That was a statement about *scheduling* rather than about the
    boundary types, and `E04-01` (`S1-T11`) is the issue whose deliverable creates
    ``docflow/ports/`` — so the assertion would fail the moment the next issue
    landed, which is a test reporting on the calendar instead of on the contract.
    The port/adapter isolation rule is `E04-01`'s own acceptance criterion and is
    asserted by that issue's tests; what belongs *here* is only that this package
    keeps to its declared module set.
    """
    expected = {
        "__init__.py",
        "types.py",
        "store.py",
        "registry.py",
        "cache_key.py",
        "pdf.py",
        "image.py",
        # `pdf_vendor.py` is the seam K2's analysis asks a reader through. It is
        # declared here for the reason the docstring above states: the set is
        # named rather than globbed, so a further module still fails this test
        # until someone declares it. It holds a Protocol and value types and
        # names no vendor — the implementation lives in `docflow/adapters/pdf.py`.
        "pdf_vendor.py",
        # `image_vendor.py` is the same seam for K3. K3 has **no port** — the set
        # is frozen at five and a raster library is not a swap-able vendor boundary
        # — but that is a statement about which engine answers, not about where the
        # library may be imported from. The implementation lives in
        # `docflow/adapters/image.py`.
        "image_vendor.py",
        # `vendor_refusal.py` is the refusal both seams raise. It is a shape, not a
        # boundary type: it carries no outcome of its own, the same standing `Box`
        # has in the frozen module. It lives here because two seams need it and
        # duplicating the constructor made the two diverge in prose only.
        "vendor_refusal.py",
    }
    actual = {path.name for path in PACKAGE_ROOT.glob("*.py")}

    assert actual <= expected, f"unexpected modules: {sorted(actual - expected)}"

    # The boundary types stay in one declared ``__all__``: no sibling re-exports
    # them, so a consumer cannot end up importing a copy from somewhere else.
    for name in expected - {"__init__.py", "types.py"}:
        module = importlib.import_module(f"docflow.kernels.{name[:-3]}")
        assert not hasattr(module, "BOUNDARY_TYPE_NAMES"), (
            f"{name} re-declares the boundary set: it must consume it from "
            "docflow.kernels.types"
        )
