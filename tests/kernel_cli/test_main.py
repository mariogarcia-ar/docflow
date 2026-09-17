"""Tests for the ``docflow-kernel`` dispatcher and its exit-code contract.

One test module per source module, mirroring ``src/docflow``. This one covers
``E07-01`` (``S1-T20``): dispatch, ``--list``, the five exit codes, the
``KernelResult`` JSON envelope, and ``--save`` routed through K7.

**What this suite is careful about**, because a worse suite would be green and
prove nothing here:

- Every assertion about a code goes through :func:`dispatch`, so it is asserting
  what a *process* would report, not what a helper returned.
- Exits ``4`` and ``1`` are asserted to emit **no** ``KernelResult`` at all - the
  absence is the criterion, and asserting only the code would pass with an
  envelope present.
- The envelope is asserted to be **the same shape on ``0``, ``2`` and ``3``**,
  differing only in the code. That is the claim `kernel-cli.md` §5 makes, and it
  is the one a script's ``jq`` depends on.
- The exit-``2``-is-reserved invariant is proven from both sides: a typed reason
  reaches ``2``, and a defect inside a handler does **not**.

A `RecordingHandler` stands in for a real kernel: `E07-01` delivers the
dispatcher, and `E07-02` fills in the operations. Testing against a real kernel
here would make this suite depend on a module another issue owns.

Two Pylint relaxations are declared below, each because the rule contradicts what
this suite is for: ``duplicate-code`` (a contract test restates the vocabulary it
checks instead of importing it) and ``too-many-lines`` (one test per exit code
plus one per envelope rule).
"""

# pylint: disable=duplicate-code
# ``EXPECTED_REASON_CODE_EXITS``, the flag vocabulary and the kernel rows are
# restated here on purpose. A contract test must hold its own copy of what it
# verifies: importing the constants would make every assertion vacuous, and
# reading them from the module under test is how a vocabulary drifts unnoticed.

# pylint: disable=too-many-lines
# One test per exit code, per envelope key, per inventory row and per flag rule, for
# an issue whose whole deliverable is a contract with many cases. Splitting the file
# would separate each rule from the test that falsifies it.

# pylint: disable=too-few-public-methods
# ``RecordingHandler`` and the unencodable test value are one-purpose stubs: a
# handler with one method, and a type whose only job is to be unencodable.

# pylint: disable=use-implicit-booleaness-not-comparison
# The comparisons this covers ask whether a guard *found* anything, and compare to
# the empty list on purpose: ``not offenders`` would also pass if the guard returned
# ``None``, so a guard broken into returning nothing at all would read as *no
# findings* - the exact vacuous pass these guards exist to prevent.

# pylint: disable=protected-access
# The probe helpers and ``_environment_has`` are reached directly, because their two
# branches cannot both be exercised through ``inventory()``: the workspace's real
# state makes only the *missing* branch reachable, so the *found* branch would never
# run. Exercising them is the point, not a leak of encapsulation - and a probe that
# always reported a reason would otherwise pass every other test in this file.

from __future__ import annotations

import ast
import hashlib
import importlib
import json
import pathlib
from collections.abc import Mapping
from types import MappingProxyType

import pytest

from docflow.kernel_cli import main as entry_point
from docflow.kernel_cli.main import (
    ALLOWED_FLAGS,
    DETERMINISM_CLASSES,
    EXIT_INTERNAL,
    EXIT_PRECONDITION,
    EXIT_REASON,
    EXIT_USAGE,
    EXIT_VALUE,
    FORBIDDEN_FLAGS,
    GLOBAL_FLAGS,
    KERNEL_SPECS,
    REASON_CODE_EXITS,
    Call,
    Invocation,
    KernelSpec,
    Operation,
    dispatch,
    exit_code_for,
    inventory,
)
from docflow.kernels import store
from docflow.kernels.types import (
    Box,
    Bytes,
    CallRecord,
    Evidence,
    KernelResult,
    Reason,
    Token,
)

# --- Constants ---------------------------------------------------------------

#: The dispatcher **module**. Reached by import rather than through the package,
#: because ``docflow.kernel_cli`` re-exports ``main`` as the *function* the
#: ``[project.scripts]`` entry point names - so ``docflow.kernel_cli.main`` is that
#: function and not the module. The shadowing is deliberate: the frozen entry point
#: is ``docflow.kernel_cli:main``, and `E07-02`'s command modules land beside
#: ``main.py`` inside the same package.
cli = importlib.import_module("docflow.kernel_cli.main")

CLI_PATH: pathlib.Path = pathlib.Path(cli.__file__).resolve()
CLI_SOURCE: str = CLI_PATH.read_text(encoding="utf-8")
CLI_TREE: ast.Module = ast.parse(CLI_SOURCE, filename=str(CLI_PATH))

#: The five exit codes and what each means, restated rather than imported. The
#: contract is `kernel-cli.md` §5, and this is the copy the tests assert against.
EXPECTED_EXIT_CODES: Mapping[int, str] = {
    0: "a value was produced",
    2: "no value, with a typed Reason",
    3: "the call could not legitimately be made",
    4: "usage error",
    1: "unexpected internal error",
}

#: The closed ``reason.code`` vocabulary and the exit each maps to, restated.
EXPECTED_REASON_CODE_EXITS: Mapping[str, int] = {
    "illegible": 2,
    "insufficient_effective_resolution": 2,
    "blank_page": 2,
    "truncated_output": 2,
    "artifact_missing": 2,
    "evidence_missing": 2,
    "encrypted": 2,
    "unsupported_format": 2,
    "model_not_pulled": 3,
    "model_unknown": 3,
    "provider_unknown": 3,
    "engine_unavailable": 3,
    "provider_unavailable": 3,
    "asset_invalid": 3,
    "asset_missing": 3,
    "role_conflict": 3,
}

#: The eight kernels, in code order, with their determinism class (`sad.md` §4) and
#: whether the probe can find what it needs in this workspace. K7 and K8 are on the
#: filesystem, which is always there; the other six need a module that has not
#: landed. Asserted as data so an inventory that starts claiming a capability is a
#: red test rather than a quiet untruth.
EXPECTED_KERNEL_ROWS: tuple[tuple[str, str, str], ...] = (
    ("K1", "orchestrator", "deterministic"),
    ("K2", "pdf", "deterministic"),
    ("K3", "image", "deterministic"),
    ("K4", "ocr", "sampled"),
    ("K5", "llm.local", "sampled"),
    ("K6", "llm.frontier", "external"),
    ("K7", "store", "deterministic"),
    ("K8", "registry", "deterministic"),
)

#: Kernels whose probe succeeds without an adapter — the two filesystem ones, plus
#: ``pdf`` and ``image``, whose engines landed with `E04-02` (`S1-T12`) and
#: `E04-03` (`S1-T13`). A kernel is added here only when its module exists *and*
#: its probe genuinely reports ``available``; the test below is what makes the
#: addition deliberate rather than a way to silence a real failure.
ALWAYS_AVAILABLE_KERNELS: frozenset[str] = frozenset(
    {"pdf", "image", "store", "registry"}
)

#: The forbidden flag vocabulary, restated from `kernel-cli.md` §10 and §14. Two
#: groups: document concepts, and the six flags the artifacts forbid outright.
EXPECTED_FORBIDDEN_FLAGS: frozenset[str] = frozenset(
    {
        "--field",
        "--invoice",
        "--cuit",
        "--total",
        "--document-type",
        "--pipeline",
        "--validator",
        "--extractor",
        "--golden",
        "--engine",
        "--no-validate",
        "--api-key",
        "--fallback",
        "--default-model",
        "--verify",
    }
)

#: The envelope's four keys, in the order `kernel-cli.md` §6 prints them.
ENVELOPE_KEYS: tuple[str, ...] = ("value", "evidence", "reason", "call_record")

#: Falsy literals that would be a stand-in for a failure if a function returned one.
FALSY_STAND_IN_LITERALS: tuple[str, ...] = ("None", '""', 'b""', "0")

#: Modules the dispatcher may import. It is a surface: it consumes the boundary
#: types and K7, and reaches no adapter.
ALLOWED_IMPORT_ROOTS: frozenset[str] = frozenset(
    {"__future__", "collections", "dataclasses", "docflow", "hashlib", "importlib"}
    | {"json", "os", "pathlib", "shutil", "sys", "traceback", "typing"}
)

#: Prefixes of ``docflow`` the dispatcher may import from.
ALLOWED_DOCFLOW_IMPORT_PREFIXES: frozenset[str] = frozenset({"docflow.kernels"})

#: Functions whose ``return None`` is an *answer* rather than a stand-in, with the
#: reason each one is legitimate. Declared as data so a new exemption has to be
#: justified in the source rather than added by quietly widening a condition.
#:
#: The distinction: a probe helper answers *"what is missing, if anything"*, so
#: ``None`` means *nothing is missing* - the good case, and a value the caller
#: branches on. A stand-in is different: it is ``None`` (or ``""``/``b""``/``0``)
#: returned **where the caller needs content or a failure**, which is the shape this
#: project refuses.
#:
#: The eight probes are deliberately **not** listed: each one *delegates* to one of
#: these helpers (``_not_landed(...) or _binary_absent(...)``) rather than writing
#: its own bare ``None``, so there is exactly one place per helper where the answer
#: is produced - and K7 and K8 share ``_probe_filesystem`` rather than each writing
#: a constant. The consistency test below enforces that, so a probe that starts
#: returning ``None`` directly has to justify itself here first.
RETURN_NONE_IS_AN_ANSWER: frozenset[str] = frozenset(
    {
        "_binary_absent",
        "_not_landed",
        "_probe_filesystem",
        "_provider_key_absent",
    }
)


# --- Fixtures and helpers ----------------------------------------------------


def make_evidence(**observed: object) -> Evidence:
    """Build a populated :class:`Evidence` for a test answer.

    Args:
        **observed: Extra observables to record.

    Returns:
        The evidence.

    """
    return Evidence(
        terms=MappingProxyType({"surface": "test"}),
        measurements=MappingProxyType({"n": 1.0}),
        observed=MappingProxyType({"note": "test"} | dict(observed)),
    )


def value_call(value: object = "ok") -> Call:
    """Build an answer that carries a value.

    Args:
        value: The value to carry.

    Returns:
        The answer, with a value and no reason.

    """
    return Call(result=KernelResult(value=value, evidence=make_evidence(), reason=None))


def reason_call(code: str) -> Call:
    """Build an answer that carries a typed reason and no value.

    Args:
        code: The reason code, from the closed vocabulary.

    Returns:
        The answer, with no value and the reason.

    """
    return Call(
        result=KernelResult(
            value=None,
            evidence=make_evidence(),
            reason=Reason(code=code, message=f"{code} happened"),
        )
    )


def bytes_call(data: bytes = b"\x89PNG\r\n\x1a\n") -> Call:
    """Build an answer that carries a buffer.

    Args:
        data: The buffer's bytes.

    Returns:
        The answer.

    """
    return value_call(Bytes(data=data, media_type="image/png"))


class RecordingHandler:
    """A handler that answers with a fixed result and records how it was called.

    Stands in for a real kernel: `E07-01` delivers the dispatcher, `E07-02` fills
    in the operations, and a test here must not depend on a module another issue
    owns.
    """

    def __init__(self, call: Call, *, raises: BaseException | None = None) -> None:
        """Store the answer this handler will give.

        Args:
            call: The answer to return.
            raises: An exception to raise instead, for the exit-``1`` path.

        """
        self.call = call
        self.raises = raises
        self.received: list[Mapping[str, object]] = []

    def __call__(self, **params: object) -> Call:
        """Answer, or raise the configured exception.

        Args:
            **params: The parsed parameters the dispatcher passed.

        Returns:
            The configured answer.

        Raises:
            BaseException: The configured exception, when one was given.

        """
        self.received.append(dict(params))
        if self.raises is not None:
            raise self.raises
        return self.call


def surface(*operations: Operation) -> dict[tuple[str, str], Operation]:
    """Build a dispatch table from operations.

    Args:
        *operations: The operations to register.

    Returns:
        The table, keyed the way the dispatcher keys it.

    """
    return {(operation.kernel, operation.name): operation for operation in operations}


def run(argv: list[str], *operations: Operation) -> Invocation:
    """Dispatch an invocation against a private table.

    Passing the table explicitly keeps a test's fixtures out of the module-level
    surface `E07-02` builds, so the two cannot interfere.

    Args:
        argv: The arguments after the program name.
        *operations: The operations to make dispatchable.

    Returns:
        The invocation.

    """
    return dispatch(argv, table=surface(*operations))


def envelope_of(invocation: Invocation) -> Mapping[str, object]:
    """Parse an invocation's stdout as the envelope.

    Args:
        invocation: The invocation to read.

    Returns:
        The parsed envelope.

    """
    parsed = json.loads(invocation.stdout)
    assert isinstance(parsed, Mapping)
    return parsed


# --- E07-01: the package shape ------------------------------------------------


def test_the_deliverable_is_a_package_and_not_a_module_beside_it() -> None:
    """``docflow/kernel_cli/`` holds ``__init__.py`` and ``main.py``.

    The per-kernel modules `E07-02` adds land inside this package, so a
    ``kernel_cli.py`` module of the same name would make that impossible without a
    rename that breaks the entry point.
    """
    package = CLI_PATH.parent

    assert CLI_PATH.name == "main.py"
    assert package.name == "kernel_cli"
    assert (package / "__init__.py").is_file()
    assert not (package.parent / "kernel_cli.py").exists()


def test_the_entry_point_target_resolves() -> None:
    """``docflow.kernel_cli:main`` resolves to a callable, as the script declares."""
    assert callable(entry_point)
    assert entry_point is cli.main, (
        "the package must re-export the dispatcher's own main, not a wrapper"
    )


def test_the_dispatcher_reaches_nothing_above_the_kernel_layer() -> None:
    """It consumes the boundary types and K7, and imports no adapter.

    The check is on the full dotted path, not the root: a root-only check would
    accept ``docflow.adapters`` because its root is ``docflow``.
    """
    imported: list[str] = []
    for node in ast.walk(CLI_TREE):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")

    roots = {name.split(".")[0] for name in imported}
    assert roots <= ALLOWED_IMPORT_ROOTS, f"unexpected imports: {sorted(roots)}"

    for name in (entry for entry in imported if entry.split(".")[0] == "docflow"):
        # The prefix *itself* counts as inside the layer, not only its children:
        # ``from docflow.kernels import store`` imports ``docflow.kernels``, and a
        # children-only check would reject the dispatcher's own dependency.
        assert name == "docflow" or any(
            name == prefix or name.startswith(f"{prefix}.")
            for prefix in ALLOWED_DOCFLOW_IMPORT_PREFIXES
        ), f"the dispatcher reached outside its layer: {name!r}"


def collect_stand_in_returns(tree: ast.Module) -> list[tuple[str, int, str]]:
    """Collect ``return`` statements that hand back a stand-in for content.

    A stand-in is an empty **string** or **buffer** - *"I have no content"* where
    the caller needs content or a failure.

    ``return None`` is judged by *where* it appears, because the same literal is two
    different things depending on the function: in a probe helper it is the answer
    *"nothing is missing"*, and in a content accessor it is a stand-in. The
    distinction cannot be read off the AST alone, so the exemption is the declared
    table :data:`RETURN_NONE_IS_AN_ANSWER`, and a bare ``None`` return from a
    function that is not on it fails here.

    Args:
        tree: The parsed module.

    Returns:
        ``(function name, line, shape)`` for every stand-in return.

    """
    offenders: list[tuple[str, int, str]] = []
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        exempt_none = function.name in RETURN_NONE_IS_AN_ANSWER
        for node in ast.walk(function):
            if not isinstance(node, ast.Return) or node.value is None:
                continue
            value = node.value
            if not isinstance(value, ast.Constant):
                continue
            if isinstance(value.value, bool):
                continue
            if value.value in ("", b""):
                offenders.append((function.name, node.lineno, repr(value.value)))
            elif value.value is None and not exempt_none:
                offenders.append((function.name, node.lineno, "None"))
            elif value.value == 0:
                offenders.append((function.name, node.lineno, "0"))
    return offenders


def test_no_dispatcher_function_returns_a_stand_in_for_content() -> None:
    """No function returns ``""`` or ``b""``, and ``return None`` needs its reason.

    Empty content is a stand-in wherever it appears. ``None`` is two things: an
    answer in a probe helper and a stand-in in a content accessor, so it is allowed
    only in the functions the table declares, each with a stated reason.
    """
    offenders = collect_stand_in_returns(CLI_TREE)

    assert offenders == [], f"stand-in returns: {offenders}"


def test_the_stand_in_exemptions_are_exactly_the_functions_that_need_them() -> None:
    """Every exempted function still returns ``None``, and no other function does.

    This is what keeps the table honest in both directions: an exemption whose
    function was refactored away is stale, and a function that starts returning
    ``None`` without a reason fails the test above. Neither can drift unnoticed.
    """
    returning_none = {
        function.name
        for function in ast.walk(CLI_TREE)
        if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(
            isinstance(node, ast.Return)
            and isinstance(node.value, ast.Constant)
            and node.value.value is None
            for node in ast.walk(function)
        )
    }

    assert returning_none == set(RETURN_NONE_IS_AN_ANSWER), (
        "the exemption table must list exactly the functions that return None"
    )


# --- E07-01: the exit-code contract ------------------------------------------


@pytest.mark.parametrize(("code", "meaning"), sorted(EXPECTED_EXIT_CODES.items()))
def test_every_exit_code_is_declared_with_its_meaning(code: int, meaning: str) -> None:
    """All five codes exist, and each names what it means.

    Args:
        code: The exit code.
        meaning: What it means.

    """
    assert meaning
    assert code in EXPECTED_EXIT_CODES
    assert getattr(cli, f"EXIT_{_NAME_BY_CODE[code]}") == code


#: Module attribute holding each exit code, so the parametrized test can look it up.
_NAME_BY_CODE: Mapping[int, str] = {
    0: "VALUE",
    2: "REASON",
    3: "PRECONDITION",
    4: "USAGE",
    1: "INTERNAL",
}


def test_exit_zero_is_reachable_with_an_envelope() -> None:
    """Exit ``0``: a value was produced, and stdout carries the envelope."""
    handler = RecordingHandler(value_call("a value"))

    invocation = run(["store", "put"], Operation("store", "put", handler))

    assert invocation.exit_code == EXIT_VALUE
    assert invocation.exit_code == 0
    assert envelope_of(invocation)["value"] == "a value"


def test_exit_two_is_reachable_with_a_typed_reason() -> None:
    """Exit ``2``: the document's answer, emitted as an envelope."""
    handler = RecordingHandler(reason_call("blank_page"))

    invocation = run(["pdf", "classify"], Operation("pdf", "classify", handler))

    assert invocation.exit_code == EXIT_REASON
    assert invocation.exit_code == 2
    assert envelope_of(invocation)["value"] is None
    assert envelope_of(invocation)["reason"]["code"] == "blank_page"


def test_exit_three_is_reachable_with_a_precondition_reason() -> None:
    """Exit ``3``: the call's precondition failed, also with an envelope."""
    handler = RecordingHandler(reason_call("model_unknown"))

    invocation = run(["llm.local", "warm"], Operation("llm.local", "warm", handler))

    assert invocation.exit_code == EXIT_PRECONDITION
    assert invocation.exit_code == 3
    assert envelope_of(invocation)["reason"]["code"] == "model_unknown"


def test_exit_four_is_reachable_for_usage() -> None:
    """Exit ``4``: an unknown operation, and **no** envelope at all."""
    invocation = run(["store", "nonsense"])

    assert invocation.exit_code == EXIT_USAGE
    assert invocation.exit_code == 4
    assert invocation.stdout == "", "exit 4 emits no KernelResult"
    assert "unknown operation" in invocation.stderr
    assert "usage:" in invocation.stderr


def test_exit_one_is_reachable_for_an_internal_error() -> None:
    """Exit ``1``: a bug in a handler, and **no** envelope at all."""
    handler = RecordingHandler(value_call(), raises=RuntimeError("boom"))

    invocation = run(["pdf", "probe"], Operation("pdf", "probe", handler))

    assert invocation.exit_code == EXIT_INTERNAL
    assert invocation.exit_code == 1
    assert invocation.stdout == "", "exit 1 emits no KernelResult"
    assert "RuntimeError: boom" in invocation.stderr


def test_exit_two_is_reserved_for_a_typed_reason_and_never_for_a_bug() -> None:
    """The invariant from `plan-01-kernels.md` §7b, proven from both sides.

    *"An unexpected exception is reported as ``2``, collapsing expected negative
    into broken."* A bug arrives at the one place exceptions are caught and becomes
    ``1``; only a ``Reason`` from the port can reach ``2``. Nothing maps an
    exception to ``EXIT_REASON``, so the collapse is unrepresentable rather than
    merely avoided.
    """
    bug = run(
        ["pdf", "probe"],
        Operation("pdf", "probe", RecordingHandler(value_call(), raises=ValueError())),
    )
    expected = run(
        ["pdf", "probe"],
        Operation("pdf", "probe", RecordingHandler(reason_call("blank_page"))),
    )

    assert bug.exit_code == EXIT_INTERNAL
    assert expected.exit_code == EXIT_REASON
    assert bug.exit_code != expected.exit_code

    # And structurally: no handler call can produce EXIT_REASON. The check is on
    # the AST, not on text, because the name legitimately appears in docstrings and
    # in the vocabulary table, and a substring count cannot tell those apart.
    reason_returns = [
        node
        for node in ast.walk(CLI_TREE)
        if isinstance(node, ast.Return)
        and isinstance(node.value, ast.Name)
        and node.value.id == "EXIT_REASON"
    ]
    assert reason_returns == [], (
        "EXIT_REASON must never be *returned*: it is reachable only through the "
        "vocabulary lookup, which is what makes a bug unable to reach it"
    )

    # And the vocabulary lookup is the only mapping from a code to an exit.
    lookup = next(
        node
        for node in ast.walk(CLI_TREE)
        if isinstance(node, ast.FunctionDef) and node.name == "exit_code_for"
    )
    looked_up = [
        node
        for node in ast.walk(lookup)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
    ]
    assert len(looked_up) == 1, "the exit code comes from exactly one lookup"


def test_a_reason_code_outside_the_closed_set_is_a_defect_not_an_outcome() -> None:
    """An unknown code becomes ``1``: a vocabulary breach is not a typed reason.

    Reporting it as ``2`` would tell a caller the document answered, when in fact
    the vocabulary was breached - the same collapse in the other direction. The
    code must come from the closed set to be an expected negative.
    """
    handler = RecordingHandler(reason_call("invented_code"))

    invocation = run(["pdf", "probe"], Operation("pdf", "probe", handler))

    assert invocation.exit_code == EXIT_INTERNAL
    assert invocation.exit_code != EXIT_REASON


@pytest.mark.parametrize(
    ("code", "expected"), sorted(EXPECTED_REASON_CODE_EXITS.items())
)
def test_the_closed_vocabulary_maps_every_code_to_its_documented_exit(
    code: str, expected: int
) -> None:
    """Each code maps to the exit `kernel-cli.md` §5 documents.

    Args:
        code: The reason code.
        expected: The exit it maps to.

    """
    assert REASON_CODE_EXITS[code] == expected


def test_the_closed_vocabulary_is_exactly_what_the_artifact_documents() -> None:
    """No code was added, dropped or re-mapped."""
    assert dict(REASON_CODE_EXITS) == dict(EXPECTED_REASON_CODE_EXITS)
    assert set(REASON_CODE_EXITS.values()) == {EXIT_REASON, EXIT_PRECONDITION}


def test_exit_codes_are_derived_from_the_result_not_passed_by_a_handler() -> None:
    """``exit_code_for`` is a pure function of the result.

    A handler returns a ``KernelResult``; the surface decides what it means to a
    process. That split is what keeps the exit contract in one place.
    """
    assert exit_code_for(value_call().result) == EXIT_VALUE
    assert exit_code_for(reason_call("encrypted").result) == EXIT_REASON
    assert exit_code_for(reason_call("asset_missing").result) == EXIT_PRECONDITION

    # And a handler signature has no exit code to give back.
    handler = RecordingHandler(value_call())
    handler(kernel="ignored")
    assert "exit_code" not in handler.received[0]


# --- E07-01: the envelope ----------------------------------------------------


def test_the_envelope_is_the_same_shape_on_exits_zero_two_and_three() -> None:
    """The machine contract is one JSON document, differing only in the code.

    This is the claim `kernel-cli.md` §5 makes and the one ``| jq`` depends on:
    a script reads the same keys whichever of the three exits it gets.
    """
    envelopes = [
        envelope_of(
            run(
                ["pdf", "probe"],
                Operation("pdf", "probe", RecordingHandler(value_call())),
            )
        ),
        envelope_of(
            run(
                ["pdf", "probe"],
                Operation("pdf", "probe", RecordingHandler(reason_call("blank_page"))),
            )
        ),
        envelope_of(
            run(
                ["pdf", "probe"],
                Operation(
                    "pdf", "probe", RecordingHandler(reason_call("asset_missing"))
                ),
            )
        ),
    ]

    for envelope in envelopes:
        assert tuple(envelope) == ENVELOPE_KEYS, (
            "the same four keys, in the documented order, on every emitting exit"
        )

    assert envelopes[0]["reason"] is None
    assert envelopes[1]["reason"]["code"] == "blank_page"
    assert envelopes[2]["reason"]["code"] == "asset_missing"


def test_the_envelope_carries_call_record_null_for_a_kernel_that_makes_no_call() -> (
    None
):
    """``call_record`` is populated for K5/K6 only; everywhere else it is null."""
    handler = RecordingHandler(value_call())

    envelope = envelope_of(run(["pdf", "probe"], Operation("pdf", "probe", handler)))

    assert envelope["call_record"] is None


def test_the_envelope_carries_a_populated_call_record() -> None:
    """A language-model kernel's answer carries the provider record."""
    record = CallRecord(
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
    handler = RecordingHandler(Call(result=value_call().result, call_record=record))

    envelope = envelope_of(
        run(["llm.local", "warm"], Operation("llm.local", "warm", handler))
    )

    assert envelope["call_record"]["provider"] == "ollama"
    assert envelope["call_record"]["model_revision"] == "sha256:7cdf5a1b", (
        "the digest is the identity, never the tag"
    )


def test_the_envelope_encodes_every_boundary_type_the_cli_can_print() -> None:
    """All seven frozen types survive encoding, member by member.

    The encoder is explicit rather than introspective, so this test is what keeps
    it in step with the contract: a type whose shape changes without the encoder
    changing fails here.
    """
    token = Token(
        text="total",
        page=1,
        bbox=Box(x=10.0, y=20.0, width=30.0, height=8.0),
        confidence=None,
        role="text",
    )
    handler = RecordingHandler(value_call([token]))

    envelope = envelope_of(run(["pdf", "tokens"], Operation("pdf", "tokens", handler)))

    assert envelope["value"][0]["text"] == "total"
    assert envelope["value"][0]["bbox"] == {
        "x": 10.0,
        "y": 20.0,
        "width": 30.0,
        "height": 8.0,
    }
    assert envelope["value"][0]["confidence"] is None, (
        "a missing confidence stays null and is never coerced to 1.0"
    )
    assert set(envelope["evidence"]) == {"terms", "measurements", "observed"}


def test_a_bytes_value_leaves_as_a_descriptor_and_not_as_base64() -> None:
    """A buffer is out of band by default: stdout carries its descriptor.

    A 40 MB page inlined as base64 is neither testable nor diffable, so the
    descriptor carries the hash of the buffer and the bytes stay put.
    """
    data = b"\x89PNG\r\n\x1a\n" * 4
    handler = RecordingHandler(bytes_call(data))

    envelope = envelope_of(run(["pdf", "render"], Operation("pdf", "render", handler)))

    assert envelope["value"]["size_bytes"] == len(data)
    assert envelope["value"]["sha256"] == hashlib.sha256(data).hexdigest()
    assert envelope["value"]["media_type"] == "image/png"
    assert envelope["value"]["path"] is None, "nothing wrote it, so it has no location"
    assert "data" not in envelope["value"]


def test_the_mapping_proxies_the_boundary_uses_survive_encoding() -> None:
    """``MappingProxyType`` has no default JSON encoder, so the encoder converts.

    `E01-01` recorded this obligation and handed it to this issue. An evidence
    record is built from proxies, so without the conversion no envelope could be
    produced at all.
    """
    handler = RecordingHandler(value_call())
    handler.call = Call(
        result=KernelResult(
            value="ok",
            evidence=Evidence(
                terms=MappingProxyType({"a": "1"}),
                measurements=MappingProxyType({"b": 2.0}),
                observed=MappingProxyType({"c": True}),
            ),
            reason=None,
        )
    )

    envelope = envelope_of(run(["pdf", "probe"], Operation("pdf", "probe", handler)))

    assert envelope["evidence"]["terms"] == {"a": "1"}
    assert envelope["evidence"]["measurements"] == {"b": 2.0}
    assert envelope["evidence"]["observed"] == {"c": True}
    assert isinstance(envelope["evidence"]["terms"], dict)


def test_an_unencodable_value_is_refused_rather_than_stringified() -> None:
    """The encoder raises rather than falling back to ``str(value)``.

    A stringified object is a stand-in that reads like data - exactly the shape
    this project refuses. An unencodable value is a defect, and the exit-``1`` path
    is where it surfaces.
    """

    class NotEncodable:
        """A value the envelope has no encoding for."""

    handler = RecordingHandler(value_call(NotEncodable()))

    invocation = run(["pdf", "probe"], Operation("pdf", "probe", handler))

    assert invocation.exit_code == EXIT_INTERNAL
    assert invocation.stdout == ""
    assert "no envelope encoding" in invocation.stderr


def test_stderr_never_carries_anything_a_script_parses() -> None:
    """On a success path stderr is empty unless ``--verbose`` asked for a log.

    That split is what makes ``docflow-kernel ... | jq`` safe: stdout is the one
    document, and stderr is the human log.
    """
    handler = RecordingHandler(value_call())

    quiet = run(["pdf", "probe"], Operation("pdf", "probe", handler))
    loud = run(["pdf", "probe", "--verbose"], Operation("pdf", "probe", handler))

    assert quiet.stderr == ""
    assert json.loads(quiet.stdout)["value"] == "ok"

    assert "exit 0" in loud.stderr
    assert "--verbose" not in loud.stdout, "the flag never reaches the envelope"
    assert json.loads(loud.stdout) == json.loads(quiet.stdout), (
        "verbose changes stderr only: stdout is byte-identical"
    )


# --- E07-01: --list -----------------------------------------------------------


def test_list_reports_the_eight_kernels_in_code_order() -> None:
    """The inventory is the eight kernels, in the plan's code order."""
    rows = inventory()

    assert len(rows) == 8
    assert tuple((row["code"], row["kernel"]) for row in rows) == tuple(
        (code, name) for code, name, _ in EXPECTED_KERNEL_ROWS
    )


@pytest.mark.parametrize(("code", "name", "determinism"), EXPECTED_KERNEL_ROWS)
def test_list_reports_the_determinism_class_of_every_kernel(
    code: str, name: str, determinism: str
) -> None:
    """Each kernel's class is the one `sad.md` §4 assigns it.

    The class decides what a test may assert, which is why it is reported next to
    the kernel rather than left to prose.

    Args:
        code: The kernel identifier.
        name: The kernel name.
        determinism: The determinism class.

    """
    row = next(entry for entry in inventory() if entry["code"] == code)

    assert row["kernel"] == name
    assert row["determinism"] == determinism
    assert determinism in DETERMINISM_CLASSES


def test_list_never_reports_an_unavailable_kernel_as_available() -> None:
    """The honesty requirement of `plan-01-kernels.md` §6 step 2.

    ``available`` is exactly ``detail is None``: there is no second source of
    truth for the boolean, so an unavailable kernel cannot be reported ``yes``.
    An inventory that lies is a silent fallback in the one place it is most
    expensive - the place a person trusts when deciding whether the bench is ready.
    """
    for row in inventory():
        assert row["available"] is (row["detail"] is None), row["kernel"]
        if row["available"]:
            assert row["detail"] is None
        else:
            assert isinstance(row["detail"], str) and row["detail"], row["kernel"]


def test_kernels_whose_engine_is_absent_report_unavailable_with_the_reason() -> None:
    """Every kernel but the ones with a landed engine names what is missing.

    Asserted against the workspace's real state rather than mocked: if an adapter
    lands, this test telling the truth about it is the point. The reason is a fact
    for a human, never an exit code.

    ``ALWAYS_AVAILABLE_KERNELS`` is widened deliberately as engines land — never
    to silence a failure. The assertion below fails on the *fact* of availability
    changing, which is exactly the moment someone should look at the probe.
    """
    for row in inventory():
        name = str(row["kernel"])
        if name in ALWAYS_AVAILABLE_KERNELS:
            assert row["available"] is True, name
        else:
            assert row["available"] is False, (
                f"{name} reports available; either its module landed (then widen "
                "ALWAYS_AVAILABLE_KERNELS deliberately) or the probe is wrong"
            )
            assert "not landed" in str(row["detail"]), name


def test_list_emits_the_inventory_as_an_envelope_on_exit_zero() -> None:
    """``--list`` is an answer like any other, so it leaves as an envelope."""
    invocation = run(["--list"])

    assert invocation.exit_code == EXIT_VALUE
    envelope = envelope_of(invocation)
    assert tuple(envelope) == ENVELOPE_KEYS
    assert len(envelope["value"]) == 8
    assert envelope["evidence"]["measurements"]["kernels"] == 8.0


def test_list_reports_at_the_kernel_level_and_not_the_command_level() -> None:
    """Availability and per-command status are two facts and stay separate.

    ``kernel-cli.md`` §4: an adapter can be available while an operation on it is
    still ``MVP``. Conflating them is how an inventory starts claiming a capability
    the bench does not have.
    """
    invocation = run(["--list"])
    envelope = envelope_of(invocation)

    for row in envelope["value"]:
        assert set(row) == {
            "kernel",
            "code",
            "determinism",
            "adapter",
            "available",
            "detail",
        }
        assert "operations" not in row
        assert "commands" not in row
        assert "status" not in row


def test_specs_are_consistent_with_the_inventory() -> None:
    """Every declared spec appears once, and the lookup table matches the tuple."""
    assert len(KERNEL_SPECS) == 8
    assert all(isinstance(spec, KernelSpec) for spec in KERNEL_SPECS)
    assert {spec.code for spec in KERNEL_SPECS} == {
        code for code, _, _ in EXPECTED_KERNEL_ROWS
    }
    assert dict(cli.KERNEL_BY_NAME) == {spec.name: spec for spec in KERNEL_SPECS}


# --- E07-01: the surface cannot grow the flags it must never have -------------


def test_the_forbidden_flag_vocabulary_is_refused_by_the_dispatcher() -> None:
    """A forbidden flag is refused *as forbidden*, and not merely as unrecognized.

    The dispatcher refuses these itself rather than leaving it to the contract test
    `E07-02` adds, so the refusal is a property of the surface and not of the
    suite. This is the drift `kernel-cli.md` §3 guardrail 1 exists to stop.

    The distinction this asserts is load-bearing, and an earlier version of the test
    missed it: asserting only that the message *contains* the flag name stays green
    even when the forbidden check is deleted, because ``unknown flag '--engine'``
    also contains it - and deleting the whole block left all 79 tests passing. Exit
    ``4`` either way is not the point. If ``--engine`` were ever added to the
    allowed vocabulary, the forbidden check would be the only thing refusing it, so
    a test that cannot see the check disappear cannot protect that.
    """
    handler = RecordingHandler(value_call())
    forbidden_messages = set()

    for flag in sorted(EXPECTED_FORBIDDEN_FLAGS):
        invocation = run(
            ["pdf", "probe", flag, "x"], Operation("pdf", "probe", handler)
        )
        assert invocation.exit_code == EXIT_USAGE, flag
        assert invocation.stdout == "", flag
        assert "does not exist on this surface" in invocation.stderr, (
            f"{flag} must be refused as forbidden, not merely as unrecognized"
        )
        forbidden_messages.add(invocation.stderr)

    # And the refusal is a *different* answer from an unknown flag's, which is what
    # makes the two distinguishable to a caller and to this suite.
    unknown = run(
        ["pdf", "probe", "--invented", "x"], Operation("pdf", "probe", handler)
    )
    assert unknown.exit_code == EXIT_USAGE
    assert "unknown flag" in unknown.stderr
    assert unknown.stderr not in forbidden_messages
    assert "does not exist on this surface" not in unknown.stderr


def test_no_forbidden_flag_appears_in_the_allowed_vocabulary() -> None:
    """The two vocabularies are disjoint, and the module declares all fifteen."""
    assert set(FORBIDDEN_FLAGS) == EXPECTED_FORBIDDEN_FLAGS
    assert set(ALLOWED_FLAGS).isdisjoint(EXPECTED_FORBIDDEN_FLAGS)


def test_an_unknown_flag_is_a_usage_error() -> None:
    """A flag outside the vocabulary does not reach a handler."""
    handler = RecordingHandler(value_call())

    invocation = run(
        ["pdf", "probe", "--invented", "1"], Operation("pdf", "probe", handler)
    )

    assert invocation.exit_code == EXIT_USAGE
    assert handler.received == [], "the handler must never be reached"


def test_out_and_root_are_not_conflated() -> None:
    """``--out`` belongs to K1 and ``--root`` to K7/K8, and both are allowed.

    They are not synonyms: ``--out`` is where a run's artifacts go, ``--root`` is
    which store or registry a kernel reads. A command that needs both is a sign the
    boundary has been crossed, which is what `E07-02`'s contract test notices.
    """
    assert "--out" in ALLOWED_FLAGS
    assert "--root" in ALLOWED_FLAGS

    handler = RecordingHandler(value_call())
    invocation = run(
        ["store", "ls", "--root", "/tmp/r", "--out", "/tmp/o"],
        Operation("store", "ls", handler),
    )

    assert invocation.exit_code == EXIT_VALUE
    assert handler.received[0] == {"root": "/tmp/r", "out": "/tmp/o"}


def test_json_is_the_only_machine_format() -> None:
    """``--format json`` is accepted; anything else is a usage error."""
    handler = RecordingHandler(value_call())

    accepted = run(
        ["pdf", "probe", "--format", "json"], Operation("pdf", "probe", handler)
    )
    refused = run(
        ["pdf", "probe", "--format", "yaml"], Operation("pdf", "probe", handler)
    )

    assert accepted.exit_code == EXIT_VALUE
    assert "--format" not in handler.received[0], "the dispatcher consumes it"

    assert refused.exit_code == EXIT_USAGE
    assert "json" in refused.stderr


def test_a_boolean_flag_takes_no_value_and_a_value_flag_requires_one() -> None:
    """The two vocabularies are handled differently, and both are checked."""
    handler = RecordingHandler(value_call())

    missing = run(["pdf", "probe", "--dpi"], Operation("pdf", "probe", handler))
    assert missing.exit_code == EXIT_USAGE
    assert "requires a value" in missing.stderr

    ok = run(["pdf", "probe", "--dpi", "300"], Operation("pdf", "probe", handler))
    assert ok.exit_code == EXIT_VALUE
    assert handler.received[0] == {"dpi": "300"}


def test_a_bare_argument_is_a_usage_error() -> None:
    """A positional where a flag belongs does not reach a handler."""
    handler = RecordingHandler(value_call())

    invocation = run(["pdf", "probe", "stray"], Operation("pdf", "probe", handler))

    assert invocation.exit_code == EXIT_USAGE
    assert handler.received == []


def test_the_global_flags_are_declared_and_allowed() -> None:
    """``--format``, ``--list`` and ``--verbose`` are the dispatcher's own."""
    assert set(GLOBAL_FLAGS) <= set(ALLOWED_FLAGS)


@pytest.mark.parametrize(
    ("argv", "expected_text"),
    [
        ([], "no kernel given"),
        (["--list", "extra"], "--list takes no other argument"),
        (["nope", "probe"], "unknown kernel"),
        (["pdf"], "no operation given"),
    ],
    ids=[
        "no-arguments",
        "list-with-extra",
        "unknown-kernel",
        "kernel-without-operation",
    ],
)
def test_every_usage_path_exits_four_without_an_envelope(
    argv: list[str], expected_text: str
) -> None:
    """Each way of misusing the surface answers ``4`` and emits no result.

    Args:
        argv: The arguments after the program name.
        expected_text: The phrase the message must carry.

    """
    invocation = run(argv)

    assert invocation.exit_code == EXIT_USAGE
    assert invocation.stdout == ""
    assert expected_text in invocation.stderr
    assert "usage:" in invocation.stderr


# --- E07-01: MVP commands ----------------------------------------------------


def test_an_mvp_operation_exits_four_naming_itself_as_unavailable() -> None:
    """A declared-but-unimplemented command must not run partially.

    An operation that has not landed and one that does not exist must stay
    distinguishable, and each gets its own message: this is what keeps "the surface
    has not drifted" apart from "the operation is not built yet"
    (`kernel-cli.md` §9).
    """
    invocation = run(["pdf", "facts"], Operation("pdf", "facts", handler=None))

    assert invocation.exit_code == EXIT_USAGE
    assert invocation.stdout == ""
    assert "not implemented" in invocation.stderr
    assert "MVP" in invocation.stderr

    unknown = run(["pdf", "invented"])
    assert "unknown operation" in unknown.stderr
    assert unknown.stderr != invocation.stderr


def test_an_operation_is_mvp_exactly_when_it_has_no_handler() -> None:
    """The distinction is one field, and both states are representable."""
    assert Operation("pdf", "facts").is_mvp is True
    assert Operation("pdf", "facts", RecordingHandler(value_call())).is_mvp is False


def test_the_registered_surface_is_empty_until_e07_02_fills_it() -> None:
    """This issue delivers the dispatcher; the operations are `E07-02`'s.

    Asserted so that a future change adding an operation here is deliberate: an
    operation declared before its adapter lands is an operation whose contract
    cannot be checked.
    """
    assert cli.registered_operations() == {}, (
        "E07-01 declares no operation; E07-02 registers them as adapters land"
    )
    invocation = dispatch(["pdf", "probe"])
    assert invocation.exit_code == EXIT_USAGE
    assert "unknown operation" in invocation.stderr


def test_probe_helpers_answer_none_when_nothing_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each probe helper answers ``None`` - *available* - when its precondition holds.

    The workspace's real state makes only the *missing* branch reachable: no
    adapter has landed and poppler may or may not be installed, so the *found*
    branch would otherwise never run. Exercising it here is what makes the helpers
    two-way - a probe that always reported a reason would pass every other test in
    this file.
    """
    monkeypatch.setattr(
        cli, "_module_exists", lambda module: module == "docflow.kernels.pdf"
    )
    assert cli._not_landed("docflow.kernels.pdf") is None
    assert cli._not_landed("docflow.adapters.docling") == (
        "not landed (docflow.adapters.docling)"
    )

    monkeypatch.setattr(cli.shutil, "which", lambda binary: f"/usr/bin/{binary}")
    assert cli._binary_absent("pdftotext") is None

    monkeypatch.setattr(cli.shutil, "which", lambda binary: None)
    assert cli._binary_absent("pdftotext") == "pdftotext not on PATH"

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    assert cli._provider_key_absent() is None

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert cli._provider_key_absent() == "no provider key in the environment"

    assert cli._environment_has("PATH") is True
    assert cli._environment_has("DOCFLOW_NEVER_SET") is False


def test_the_filesystem_probe_answers_available_without_checking_anything() -> None:
    """K7 and K8 read the local filesystem: there is no precondition to fail.

    The shared probe is asserted directly because both kernels point at it, so a
    regression there would make two rows of the inventory wrong at once.
    """
    assert cli._probe_filesystem() is None

    rows = {row["kernel"]: row for row in inventory()}
    assert rows["store"]["available"] is True
    assert rows["registry"]["available"] is True


def test_registering_an_operation_is_visible_and_replaceable() -> None:
    """``register`` is the seam `E07-02` uses, and a redeclaration replaces."""
    first = Operation("pdf", "probe", RecordingHandler(value_call("first")))
    second = Operation("pdf", "probe", RecordingHandler(value_call("second")))

    original = cli.registered_operations()
    try:
        cli.register(first)
        assert cli.registered_operations()[("pdf", "probe")] is first
        cli.register(second)
        assert cli.registered_operations()[("pdf", "probe")] is second
        assert len(cli.registered_operations()) == 1
    finally:
        cli._OPERATIONS.clear()  # pylint: disable=protected-access
        for key, value in original.items():
            cli._OPERATIONS[key] = value  # pylint: disable=protected-access

    assert cli.registered_operations() == original


# --- E07-01: --save routed through K7 ---------------------------------------


def test_save_writes_bytes_through_k7_and_records_the_real_hash(
    tmp_path: pathlib.Path,
) -> None:
    """The hash in the descriptor is the hash of what was actually written.

    ``--save`` routes through K7 rather than writing the file here, so the
    descriptor is K7's answer and not this module's claim (`E07-01`'s acceptance
    criterion).
    """
    data = b"\x89PNG\r\n\x1a\n" * 3
    handler = RecordingHandler(bytes_call(data))

    invocation = run(
        ["pdf", "render", "--save", str(tmp_path)],
        Operation("pdf", "render", handler),
    )

    assert invocation.exit_code == EXIT_VALUE
    envelope = envelope_of(invocation)
    sha256 = hashlib.sha256(data).hexdigest()

    assert envelope["value"]["sha256"] == sha256
    assert envelope["value"]["path"] == f"artifacts/{sha256}"
    assert store.verify(tmp_path, sha256) is True
    assert store.get(tmp_path, sha256) == data


def test_save_without_a_buffer_is_a_usage_error_and_not_a_silent_no_op() -> None:
    """The caller asked for bytes to be persisted and none exist.

    Returning the value unchanged would report success for a request that was
    silently dropped - the shape this project refuses everywhere.
    """
    handler = RecordingHandler(value_call("not bytes"))

    invocation = run(
        ["pdf", "probe", "--save", "/tmp/ignored"],
        Operation("pdf", "probe", handler),
    )

    assert invocation.exit_code == EXIT_USAGE
    assert "--save applies" in invocation.stderr


def test_without_save_the_bytes_stay_out_of_band() -> None:
    """No ``--save`` means no write, and stdout still carries the descriptor."""
    handler = RecordingHandler(bytes_call())

    invocation = run(["pdf", "render"], Operation("pdf", "render", handler))

    assert invocation.exit_code == EXIT_VALUE
    assert envelope_of(invocation)["value"]["path"] is None


def test_every_operation_returns_a_call_and_never_an_exit_code() -> None:
    """The handler contract: a ``Call``, whose result is the only outcome.

    Asserted through the type rather than by reading the code: a handler that
    returned an exit code would have no ``result`` to encode.
    """
    handler = RecordingHandler(value_call())

    assert isinstance(handler(), Call)
    assert isinstance(handler().result, KernelResult)


def test_main_writes_the_invocation_to_the_streams(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``main`` is a thin adapter over ``dispatch``: it touches the streams.

    Everything else returns an :class:`Invocation`, which is what lets the rest of
    this suite assert the contract without capturing file descriptors.
    """
    handler = RecordingHandler(value_call("written"))
    original = cli.registered_operations()
    try:
        cli.register(Operation("pdf", "probe", handler))
        code = cli.main(["pdf", "probe"])
    finally:
        cli._OPERATIONS.clear()  # pylint: disable=protected-access
        for key, value in original.items():
            cli._OPERATIONS[key] = value  # pylint: disable=protected-access

    captured = capsys.readouterr()

    assert code == EXIT_VALUE
    assert json.loads(captured.out)["value"] == "written"
    assert captured.err == ""


def test_main_returns_the_usage_code_and_writes_usage_to_stderr(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A usage path reached through ``main`` behaves the same as through dispatch."""
    code = cli.main(["nope"])

    captured = capsys.readouterr()

    assert code == EXIT_USAGE
    assert captured.out == ""
    assert "usage:" in captured.err
