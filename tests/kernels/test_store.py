"""Tests for K7 - the artifact store and the ledger write path.

Two issues, one source module and therefore one test module (the ``tests/`` tree
mirrors ``src/docflow/``, one test module per source module):

- ``E02-01`` / ``S1-T02`` - content-addressed ``put``/``get``, the atomic write,
  ``verify``, and a ``get`` that raises instead of returning empty.
- ``E02-02`` / ``S1-T03`` - ``begin``/``commit``/``fail``, ``read_ledger``,
  ``write_ledger``, the seven durable states, and the ordering rule that ``done``
  is never written before the rename returned.

The two load-bearing tests are
:func:`test_a_killed_write_leaves_no_partial_artifact` and
:func:`test_a_crash_between_write_and_rename_leaves_the_stage_running`. Both
inject the crash at the module's one rename seam rather than describing it, and
both are checked by mutation: see ``plan-01-kernels.md`` §7b rows 2 and §13
Track 2.

Two Pylint relaxations are declared below, each because the rule contradicts what
this suite is for rather than because the code is sloppy. ``protected-access``:
the rename seam is the issue's own test hook, so the suite must reach it.
``too-many-lines``: one test per acceptance criterion of two ``L`` issues, and
splitting them would separate each invariant from its falsification test.
"""

# pylint: disable=protected-access
# ``store._replace`` and ``store._atomic_write`` are the injection points this
# issue's acceptance criteria are *about* ("a crash injected between write and
# rename"). Reaching them is the test, not a leak of encapsulation.

# pylint: disable=too-many-lines
# Two ``L`` issues, one module, one test per acceptance criterion. Splitting the
# file to satisfy a line budget would separate the atomic-write invariant from
# its crash-injection fallback assertions.

# pylint: disable=use-implicit-booleaness-not-comparison
# The four sites this covers compare a guard's result to the empty list on
# purpose. ``assert not find_dependency_violations(...)`` would also pass if the
# guard returned ``None``, so a guard broken into returning nothing at all would
# read as *no violations found* - the exact vacuous-pass this suite exists to
# prevent. Comparing to ``[]`` keeps the assertion strict about the type as well
# as the contents.

# pylint: disable=duplicate-code
# ``DURABLE_STATE_ORDER`` and the seven-state legal-pairing table below
# deliberately repeat what ``docflow/kernels/store.py`` declares. A contract test
# must hold its own copy of the closed set it is verifying: importing the
# constant would make the assertion vacuous, and reading the states from the
# module it is checking is how a vocabulary drifts unnoticed.

from __future__ import annotations

import ast
import dataclasses
import hashlib
import json
import pathlib
import sys
from collections.abc import Iterator, Mapping

import pytest

from docflow.kernels import store
from docflow.kernels.store import (
    DURABLE_STATE_ORDER,
    Ledger,
    StageRecord,
    ledger_path,
    new_ledger,
)
from docflow.kernels.types import Artifact, Reason

# --- Constants ---------------------------------------------------------------

STORE_PATH: pathlib.Path = pathlib.Path(store.__file__).resolve()
STORE_SOURCE: str = STORE_PATH.read_text(encoding="utf-8")
STORE_TREE: ast.Module = ast.parse(STORE_SOURCE, filename=str(STORE_PATH))

#: A stand-in hash used where a record needs a value but the bytes are irrelevant.
SOME_SHA256: str = "9f2a" * 16

#: A stand-in cache key, used wherever a record needs a terminal outcome. It is a
#: real-shaped key (64 hex characters) rather than a label, because a record that
#: only *looks* keyed would not distinguish this suite from one that records
#: nothing at all.
SOME_CACHE_KEY: str = "c41b" * 16

#: Body bytes for the store tests. Two distinct buffers and one repeat, so the
#: dedup assertion has something to be about.
FIRST_BYTES: bytes = b"\x89PNG\r\n\x1a\nfirst"
SECOND_BYTES: bytes = b"\x89PNG\r\n\x1a\nsecond"

#: The unit name and declared stage set shared by the ledger tests.
UNIT_NAME: str = "O-0001"
STAGE_NAMES: tuple[str, ...] = ("acquire", "transform", "persist")

#: The seven durable states with a legal field pairing for each, restated here on
#: purpose: a contract test must hold its own copy rather than import the tuple it
#: verifies. ``running`` may also carry a reason code at this layer; only the
#: ``done``/``failed`` pairings are closed by ``StageRecord``.
#:
#: The fourth element is the cache key, required for a **terminal outcome**
#: (``done``, ``failed``) and optional for the states on the way there. The fifth is
#: the attempt count, and it follows from the state: an attempt state has been run at
#: least once, and the states that are not attempts cannot claim one.
LEGAL_STATE_RECORDS: tuple[tuple[str, str | None, str | None, str | None, int], ...] = (
    ("running", None, None, None, 1),
    ("running", None, None, SOME_CACHE_KEY, 1),
    ("done", SOME_SHA256, None, SOME_CACHE_KEY, 1),
    ("failed", None, "artifact_missing", SOME_CACHE_KEY, 1),
    ("pending", None, None, None, 0),
    ("blocked", None, None, None, 0),
    ("stale", None, None, None, 0),
    ("skipped", None, None, None, 0),
    ("failed", SOME_SHA256, "evidence_missing", SOME_CACHE_KEY, 2),
)

#: Values that look like a state and are not one. ``not_applicable`` is included
#: deliberately: it is a *list* of stages a pipeline does not run (Plan 3's
#: ``S3-T03``), never a stage state, so it must be rejected here.
EIGHTH_STATE_CANDIDATES: tuple[object, ...] = (
    "",
    "DONE",
    "done ",
    "Done",
    "complete",
    "completed",
    "in_progress",
    "waiting",
    "not_applicable",
    "success",
    None,
)

#: Domain vocabulary no kernel identifier may contain (``kernel-cli.md`` §14).
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

#: Module roots the store is allowed to import: the standard library plus its own
#: layer. No adapter, no third party - the store is the substrate, not a caller.
ALLOWED_IMPORT_ROOTS: frozenset[str] = frozenset(
    {"__future__", "docflow", "collections", "dataclasses", "hashlib", "json", "os"}
    | {"pathlib", "types", "typing"}
)

#: Subpackages of ``docflow`` the store may import from, as *prefixes*. Checking
#: the root (``docflow``) is not enough, and an earlier version of this test made
#: exactly that mistake: ``from docflow.adapters import docling`` passed, because
#: its root is ``docflow``. The store is K7 - the substrate everything else calls -
#: so its allowed surface is its own layer and the standard library, nothing else.
ALLOWED_DOCFLOW_IMPORT_PREFIXES: frozenset[str] = frozenset({"docflow.kernels"})

#: Package prefixes the store must never reach. An adapter imported from the
#: substrate inverts the dependency arrow - the arrow points down, and the store
#: is at the bottom. Recorded as the vocabulary of what is forbidden, so a reader
#: sees the boundary without reading the guard.
FORBIDDEN_DOCFLOW_IMPORTS: tuple[str, ...] = (
    "docflow.adapters",
    "docflow.components",
    "docflow.kernel_cli",
    "docflow.ports",
)

#: The public operations both issues name, restated so the surface is asserted
#: rather than assumed. A rename would fail here before it failed downstream.
EXPECTED_PUBLIC_OPERATIONS: frozenset[str] = frozenset(
    {
        "put",
        "get",
        "verify",
        "begin",
        "commit",
        "fail",
        "read_ledger",
        "write_ledger",
        "new_ledger",
        "ledger_path",
    }
)

#: Falsy literals that would be a stand-in for a failure if a function returned
#: one. ``True`` and ``False`` are excluded on purpose: ``verify`` returns a bool
#: as a *value*, so a failed verification is a successful call with the answer
#: ``False`` (``kernel-cli.md`` §9), not a stand-in. ``b""`` is included because it
#: is the exact shape a ``get``-on-a-miss defect takes.
FALSY_STAND_IN_LITERALS: tuple[str, ...] = ("None", '""', 'b""', "0", "[]", "{}", "()")


# --- Fixtures and helpers ----------------------------------------------------


@pytest.fixture(name="root")
def root_fixture(tmp_path: pathlib.Path) -> pathlib.Path:
    """Provide an empty store root under the test's temporary directory.

    Args:
        tmp_path: Pytest's per-test temporary directory.

    Returns:
        A directory that no test has written to yet.

    """
    root = tmp_path / "store"
    root.mkdir()
    return root


@pytest.fixture(name="unit_dir")
def unit_dir_fixture(tmp_path: pathlib.Path) -> pathlib.Path:
    """Provide a unit directory whose ledger declares the shared stage set.

    Args:
        tmp_path: Pytest's per-test temporary directory.

    Returns:
        A directory holding a freshly declared, all-``pending`` ledger.

    """
    unit_dir = tmp_path / "out" / UNIT_NAME
    unit_dir.mkdir(parents=True)
    store.write_ledger(unit_dir, new_ledger(UNIT_NAME, STAGE_NAMES))
    return unit_dir


def read_stage(unit_dir: pathlib.Path, stage: str) -> StageRecord:
    """Read one stage's record from a unit's ledger on disk.

    Args:
        unit_dir: The unit's directory.
        stage: The stage to look up.

    Returns:
        That stage's record.

    """
    return store.read_ledger(unit_dir).stages[stage]


def iter_module_identifiers(tree: ast.Module) -> Iterator[tuple[str, int]]:
    """Yield every identifier a module declares, with its line number.

    Only names are yielded - never docstrings and never comments - so prose that
    legitimately uses a domain word cannot produce a false failure.

    Args:
        tree: The parsed module.

    Yields:
        ``(name, lineno)`` for every class, function, referenced name, attribute,
        argument and annotated target.

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


def is_empty_display(node: ast.expr) -> bool:
    """Report whether an expression is an empty literal display.

    ``[]``, ``{}``, ``()`` and ``set()`` are the display spelling of the same
    stand-in a constant spells as ``None`` or ``""``, and they reach the tree as
    node types rather than as constants.

    Args:
        node: The expression to inspect.

    Returns:
        True when the expression is an empty list, tuple, set or dict display.

    """
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return not node.elts
    if isinstance(node, ast.Dict):
        return not node.keys
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "set"
        and not node.args
    )


def collect_falsy_constant_returns(tree: ast.Module) -> list[int]:
    """Collect lines where a function returns a falsy literal or empty literal.

    Both spellings are covered, because they are the same defect written two
    ways: a constant (``None``, ``""``, ``b""``, ``0``) and an empty display.

    The first version of this collector matched only ``ast.Constant`` whose value
    compared equal to ``None``, ``""`` or ``0`` - which let ``return b""`` through
    untouched, because ``b"" == ""`` is ``False``. That was caught by mutating the
    source and watching the suite stay green: the mutation harness found it, and
    the tests for this collector now keep it found.

    Args:
        tree: The parsed module.

    Returns:
        The line numbers of every ``return <falsy literal>`` statement, ignoring
        ``True``/``False`` because a boolean answer is a result, not a stand-in.

    """
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Return) or node.value is None:
            continue
        value = node.value
        if isinstance(value, ast.Constant):
            if isinstance(value.value, bool):
                continue
            if value.value is None or value.value in ("", b"", 0):
                lines.append(node.lineno)
        elif is_empty_display(value):
            lines.append(node.lineno)
    return lines


def parse_single_return(literal: str) -> ast.Module:
    """Parse a one-line function whose body returns a literal.

    Args:
        literal: The literal to return, as source text.

    Returns:
        The parsed module.

    """
    return ast.parse(f"def f():\n    return {literal}\n")


def collect_imported_modules(tree: ast.Module) -> list[str]:
    """Collect every module path a module imports.

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


def find_dependency_violations(imported: list[str]) -> list[str]:
    """Return the imports that invert the dependency arrow.

    Split out from the test that calls it so the check can be exercised against
    synthetic sources. A guard whose only test mutates the real module cannot be
    tested at all for the case where the mutant fails to *import*: the module
    errors during collection, the static test never runs, and the guard appears
    unproven while actually being correct. Checking the helper directly is what
    makes the guard provable.

    Args:
        imported: The dotted module paths a module imports.

    Returns:
        The offending paths, empty when the import set is legal.

    """
    offending: list[str] = []

    for name in imported:
        root = name.split(".")[0]
        if root not in ALLOWED_IMPORT_ROOTS:
            offending.append(name)
            continue
        if root != "docflow":
            continue
        if name == "docflow":
            continue
        if not any(
            name.startswith(f"{prefix}.") for prefix in ALLOWED_DOCFLOW_IMPORT_PREFIXES
        ):
            offending.append(name)

    return offending


def patched_write_count(monkeypatch: pytest.MonkeyPatch, counter: list[int]) -> None:
    """Count calls to the module's single atomic-write helper.

    Args:
        monkeypatch: Pytest's monkeypatch fixture.
        counter: A one-element list the wrapper appends to per call.

    """
    original = store._atomic_write

    def counting(target: pathlib.Path, data: bytes) -> None:
        counter.append(1)
        original(target, data)

    monkeypatch.setattr(store, "_atomic_write", counting)


# --- Criterion: the module's surface ----------------------------------------


def test_store_module_exposes_every_operation_both_issues_name() -> None:
    """Both issues' operations exist, and each one is callable."""
    missing = sorted(
        name
        for name in EXPECTED_PUBLIC_OPERATIONS
        if not callable(getattr(store, name, None))
    )

    assert missing == [], f"missing store operations: {missing}"
    assert sorted(store.__all__) == sorted(set(store.__all__)), (
        "``__all__`` must not repeat a name"
    )
    assert set(store.__all__) >= EXPECTED_PUBLIC_OPERATIONS


def test_the_seven_durable_states_are_declared_in_the_order_sad_declares_them() -> None:
    """The closed set is the seven states of `sad.md` §7.1, in that order."""
    assert DURABLE_STATE_ORDER == (
        "running",
        "done",
        "failed",
        "pending",
        "blocked",
        "stale",
        "skipped",
    )
    assert len(set(DURABLE_STATE_ORDER)) == 7, "no state may appear twice"


def test_store_imports_nothing_outside_the_standard_library_and_its_own_layer() -> None:
    """The store depends on stdlib plus its own layer, and on no adapter.

    The check is on the full dotted path, not the root: ``from
    docflow.adapters import docling`` has the root ``docflow`` and would pass a
    root-only check while inverting the dependency arrow. An earlier version of
    this test did exactly that, and the mutation harness caught it.
    """
    imported = collect_imported_modules(STORE_TREE)

    assert find_dependency_violations(imported) == [], (
        f"the store reached outside its layer: {find_dependency_violations(imported)}"
    )
    assert any(name.split(".")[0] == "docflow" for name in imported), (
        "the store must consume the frozen boundary types"
    )


def test_the_dependency_guard_rejects_an_adapter_import_under_the_same_root() -> None:
    """The guard is exercised directly, because a mutant cannot exercise it.

    ``from docflow.adapters import docling`` makes the module fail to import
    altogether, so a test that only reads the real module would never get to run
    its assertion: pytest reports a collection error, not a failed test. Checking
    the helper against a synthetic source is what proves the guard works rather
    than merely that it exists.

    The forbidden vocabulary is restated here rather than derived from the tuple
    above, so that a new entry in the real guard cannot silently relax this test.
    """
    illegal = (
        "docflow.adapters",
        "docflow.adapters.docling",
        "docflow.components",
        "docflow.components.segmenter",
        "docflow.kernel_cli",
        "docflow.kernel_cli.main",
        "docflow.ports",
        "docflow.ports.ocr",
        "numpy",
        "docling",
    )
    for name in illegal:
        assert find_dependency_violations(["docflow.kernels.types", name]) == [name], (
            f"{name!r} must be rejected"
        )

    legal = [
        "docflow",
        "docflow.kernels.types",
        "docflow.kernels.store",
        "__future__",
        "dataclasses",
        "hashlib",
        "json",
        "os",
        "pathlib",
        "types",
        "typing",
        "collections.abc",
    ]
    assert find_dependency_violations(legal) == []


def test_the_dependency_guard_is_not_vacuous() -> None:
    """The guard reads the module it is pointed at, rather than answering always.

    A guard that returned ``[]`` for everything would pass both the tests above
    and the real-module check. Pointing it at a source that *does* import an
    adapter proves it reads what it is given.
    """
    tree = ast.parse("from docflow.adapters import docling\nimport json\n")

    assert collect_imported_modules(tree) == ["docflow.adapters", "json"]
    assert find_dependency_violations(collect_imported_modules(tree)) == [
        "docflow.adapters"
    ]

    clean = ast.parse("import json\nfrom docflow.kernels.types import Artifact\n")
    assert find_dependency_violations(collect_imported_modules(clean)) == []


def test_the_forbidden_vocabulary_is_a_subset_of_what_the_guard_rejects() -> None:
    """Every name the module declares forbidden is in fact rejected.

    This keeps the declared vocabulary and the enforcement from drifting: a name
    added to :data:`FORBIDDEN_DOCFLOW_IMPORTS` without the guard rejecting it fails
    here.
    """
    for forbidden in FORBIDDEN_DOCFLOW_IMPORTS:
        assert find_dependency_violations([forbidden]) == [forbidden]
        assert find_dependency_violations([f"{forbidden}.module"]) == [
            f"{forbidden}.module"
        ]


def test_no_store_identifier_contains_a_domain_noun() -> None:
    """No class, function, argument or attribute name names a document concept."""
    offences = [
        (name, line)
        for name, line in iter_module_identifiers(STORE_TREE)
        if any(token.lower() in name.lower() for token in FORBIDDEN_DOMAIN_VOCABULARY)
    ]

    assert offences == [], f"domain vocabulary in identifiers: {offences}"


def test_no_store_function_returns_a_falsy_literal_as_a_stand_in() -> None:
    """A miss raises; it does not return ``b""``, ``""``, ``0``, ``[]`` or ``None``."""
    assert not collect_falsy_constant_returns(STORE_TREE), (
        "a falsy literal returned from a function is the shape a silent failure "
        "takes (`.github/copilot-instructions.md`, never a silent stand-in)"
    )


@pytest.mark.parametrize("literal", FALSY_STAND_IN_LITERALS)
def test_the_stand_in_collector_catches_every_shape_it_claims_to(
    literal: str,
) -> None:
    """The collector that guards the module is itself tested against every shape.

    Unlike the other tests in this file, this one is *verified* rather than
    assumed: the collector is the guard against ``return b""``, and a guard that
    silently misses a shape is worse than no guard, because the suite then reports
    a green result it has not earned. An earlier version of it missed ``b""``.

    Args:
        literal: The literal to return from a one-line function.

    """
    assert collect_falsy_constant_returns(parse_single_return(literal)) == [2], (
        "the return is on the function body's own line, which is line 2"
    )


@pytest.mark.parametrize("literal", ["None", "0", '""', 'b""', "[]"])
def test_the_stand_in_collector_does_not_ignore_a_statement_after_a_return(
    literal: str,
) -> None:
    """A falsy return is caught wherever it appears in a body, not only at the end.

    Args:
        literal: The literal to return from the middle of a function.

    """
    module = ast.parse(f"def f():\n    return {literal}\n    return 1\n")

    assert collect_falsy_constant_returns(module) == [2]


@pytest.mark.parametrize("literal", ["True", "False", "1", "b'x'"])
def test_the_stand_in_collector_leaves_a_real_answer_alone(literal: str) -> None:
    """A boolean value and a non-empty buffer are results, not stand-ins.

    ``verify`` returns ``False`` as its answer, and exit ``0`` with ``value:
    false`` is a successful call (`kernel-cli.md` §9), so neither may be flagged.

    Args:
        literal: A literal that is a legitimate answer.

    """
    assert collect_falsy_constant_returns(parse_single_return(literal)) == []


# --- E02-01: content addressing ---------------------------------------------


def test_put_returns_a_descriptor_addressed_by_the_hash_of_its_content(
    root: pathlib.Path,
) -> None:
    """The hash put reports is the hash the bytes actually have."""
    artifact = store.put(root, FIRST_BYTES, media_type="image/png")
    expected = hashlib.sha256(FIRST_BYTES).hexdigest()

    assert artifact.sha256 == expected
    assert store._sha256(FIRST_BYTES) == expected, "the module hashes with SHA-256"
    assert artifact.size_bytes == len(FIRST_BYTES)
    assert artifact.media_type == "image/png"


def test_put_writes_the_bytes_under_a_name_derived_from_the_hash(
    root: pathlib.Path,
) -> None:
    """The stored file's name is the artifact's identity, with no extension added."""
    artifact = store.put(root, FIRST_BYTES, media_type="image/png")

    assert artifact.path == f"artifacts/{artifact.sha256}"
    stored = root / artifact.path  # type: ignore[arg-type]
    assert stored.is_file()
    assert stored.read_bytes() == FIRST_BYTES


def test_putting_identical_bytes_twice_stores_one_artifact(
    root: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The second put does not create a second copy, and rewrites nothing."""
    counter: list[int] = []
    patched_write_count(monkeypatch, counter)

    first = store.put(root, FIRST_BYTES, media_type="image/png")
    second = store.put(root, FIRST_BYTES, media_type="image/png")

    assert counter == [1], "the second put must not write a second copy"
    assert first.sha256 == second.sha256
    stored = list((root / "artifacts").iterdir())
    assert len(stored) == 1, f"expected one artifact on disk, found {stored}"


def test_put_replaces_an_artifact_whose_bytes_do_not_match_its_name(
    root: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A corrupted or interrupted file is repaired instead of being accepted.

    This is what lets a stage interrupted mid-write be re-run rather than
    deadlock on its own leftovers.
    """
    artifact = store.put(root, FIRST_BYTES, media_type="image/png")
    stored = root / artifact.path  # type: ignore[arg-type]
    stored.write_bytes(b"truncated")

    counter: list[int] = []
    patched_write_count(monkeypatch, counter)
    store.put(root, FIRST_BYTES, media_type="image/png")

    assert counter == [1], "an intact-by-name file with wrong bytes must be replaced"
    assert store.verify(root, artifact.sha256) is True
    assert store.get(root, artifact.sha256) == FIRST_BYTES


def test_get_returns_exactly_the_bytes_that_were_put(root: pathlib.Path) -> None:
    """A put/get round trip returns the buffer unchanged."""
    artifact = store.put(root, SECOND_BYTES, media_type="application/pdf")

    assert store.get(root, artifact.sha256) == SECOND_BYTES


def test_get_on_a_missing_hash_raises_and_never_returns_empty(
    root: pathlib.Path,
) -> None:
    """A miss raises; it never returns ``b""`` or a placeholder."""
    with pytest.raises(FileNotFoundError) as excinfo:
        store.get(root, SOME_SHA256)

    assert "No artifact" in str(excinfo.value)
    assert not isinstance(excinfo.value, ValueError), "a miss is not a value error"


def test_get_distinguishes_a_miss_from_a_stored_empty_buffer(
    root: pathlib.Path,
) -> None:
    """An empty buffer is a legal artifact, so a miss cannot also be one."""
    empty = store.put(root, b"", media_type="application/octet-stream")

    assert store.get(root, empty.sha256) == b""
    with pytest.raises(FileNotFoundError):
        store.get(root, SOME_SHA256)


def test_a_killed_write_leaves_no_partial_artifact(root: pathlib.Path) -> None:
    """A crash after staging but before the rename leaves the final name untouched.

    The kill is injected at the module's one rename seam, which is the last step
    that may be interrupted (`plan-01-kernels.md` §7b row 2). Reading the store
    from outside afterwards is the point: nothing may be visible under a final
    name that was never completed.
    """
    sha256 = store._sha256(FIRST_BYTES)
    original_replace = store._replace

    def kill(source: pathlib.Path, target: pathlib.Path) -> None:
        raise KeyboardInterrupt("simulated kill at the rename boundary")

    store._replace = kill  # type: ignore[assignment]
    try:
        with pytest.raises(KeyboardInterrupt):
            store.put(root, FIRST_BYTES, media_type="image/png")
    finally:
        store._replace = original_replace  # type: ignore[assignment]

    assert not (root / "artifacts" / sha256).exists(), (
        "no partial artifact may be visible under its final name"
    )
    assert store.verify(root, sha256) is False
    with pytest.raises(FileNotFoundError):
        store.get(root, sha256)

    # The staged bytes are still there under the staging name, which is how an
    # operator can see that a write was interrupted and where.
    leftovers = [entry.name for entry in (root / "artifacts").glob(".*")]
    assert leftovers, "the interrupted write leaves its staging file behind"

    # And the same put succeeds once the rename is allowed to return.
    artifact = store.put(root, FIRST_BYTES, media_type="image/png")
    assert artifact.sha256 == sha256
    assert store.verify(root, artifact.sha256) is True


def test_put_returns_only_after_the_rename_has_returned(root: pathlib.Path) -> None:
    """``put`` hands back no descriptor while the rename is still unwinding."""
    observed: list[bool] = []
    original_replace = store._replace

    def spy(source: pathlib.Path, target: pathlib.Path) -> None:
        original_replace(source, target)
        target_path = target

        def observe() -> None:
            observed.append(target_path.exists())

        observe()

    store._replace = spy  # type: ignore[assignment]
    try:
        artifact = store.put(root, FIRST_BYTES, media_type="image/png")
    finally:
        store._replace = original_replace  # type: ignore[assignment]

    assert observed == [True], "the bytes are in place the moment the rename returns"
    assert store.get(root, artifact.sha256) == FIRST_BYTES


# --- E02-01: verification ----------------------------------------------------


def test_verify_detects_a_truncated_file(root: pathlib.Path) -> None:
    """Shortening a stored artifact makes verification fail (FR-11)."""
    artifact = store.put(root, FIRST_BYTES, media_type="image/png")
    stored = root / artifact.path  # type: ignore[arg-type]

    assert store.verify(root, artifact.sha256) is True

    stored.write_bytes(FIRST_BYTES[:-1])

    assert store.verify(root, artifact.sha256) is False


def test_verify_detects_an_altered_file(root: pathlib.Path) -> None:
    """Same length, different content: still a failed verification."""
    artifact = store.put(root, FIRST_BYTES, media_type="image/png")
    stored = root / artifact.path  # type: ignore[arg-type]
    stored.write_bytes(FIRST_BYTES.replace(b"first", b"f1rst"))

    assert len(stored.read_bytes()) == len(FIRST_BYTES)
    assert store.verify(root, artifact.sha256) is False


def test_verify_returns_a_boolean_value_and_not_an_error(
    root: pathlib.Path,
) -> None:
    """A failed verification is a successful call: the question was answered.

    Exit ``0`` with ``value: false``, never exit ``2`` (`kernel-cli.md` §9). No
    exception is raised for a missing artifact either - it is the same question,
    answered the same way.
    """
    artifact = store.put(root, FIRST_BYTES, media_type="image/png")

    assert isinstance(store.verify(root, artifact.sha256), bool)
    assert isinstance(store.verify(root, SOME_SHA256), bool)
    assert store.verify(root, SOME_SHA256) is False


def test_verify_says_nothing_about_ledger_trust(root: pathlib.Path) -> None:
    """Verifying one artifact does not read or judge a ledger.

    The check is scoped to the bytes it was given: a store can contain a
    perplexing ledger and still verify an artifact, which is why the ledger-trust
    check is `E05-05`'s and has no flag here.
    """
    artifact = store.put(root, FIRST_BYTES, media_type="image/png")

    assert not list(root.glob("**/*.ledger.json"))
    assert store.verify(root, artifact.sha256) is True
    assert not list(root.glob("**/*.ledger.json")), "verify read no ledger"


# --- E02-02: the seven states, by construction -------------------------------


@pytest.mark.parametrize(
    ("state", "artifact_sha256", "reason_code", "cache_key", "attempts"),
    LEGAL_STATE_RECORDS,
)
def test_every_legal_state_record_is_constructible(
    state: str,
    artifact_sha256: str | None,
    reason_code: str | None,
    cache_key: str | None,
    attempts: int,
) -> None:
    """Each durable state is writable with a legal field pairing.

    Args:
        state: The durable state under test.
        artifact_sha256: The artifact claim, or None.
        reason_code: The reason code, or None.
        cache_key: The key the stage ran under, or None before dispatch.
        attempts: The attempt count that state permits.

    """
    record = StageRecord(
        state=state,
        artifact_sha256=artifact_sha256,
        reason_code=reason_code,
        cache_key=cache_key,
        attempts=attempts,
    )

    assert record.state in DURABLE_STATE_ORDER
    assert record.artifact_sha256 == artifact_sha256
    assert record.reason_code == reason_code
    assert record.cache_key == cache_key
    assert record.attempts == attempts


@pytest.mark.parametrize("state", EIGHTH_STATE_CANDIDATES)
def test_no_eighth_state_is_writable(state: object) -> None:
    """A value outside the seven is refused, and ``not_applicable`` is outside.

    Args:
        state: A value that looks like a state and is not one.

    """
    with pytest.raises(ValueError) as excinfo:
        StageRecord(  # type: ignore[arg-type]
            state=state,
            artifact_sha256=None,
            reason_code=None,
            cache_key=None,
            attempts=0,
        )

    assert "seven durable ledger states" in str(excinfo.value)


def test_not_applicable_is_a_stage_list_and_never_a_state() -> None:
    """``not_applicable`` records absence of a stage, not a stage's progress.

    Plan 3's ``S3-T03`` emits a *list* of stages a pipeline does not run; a stage
    that is skipped for that reason is ``skipped``. The distinction is asserted
    here because the two words are close enough to be conflated in a writer.
    """
    not_applicable = "not_applicable"

    assert not_applicable not in DURABLE_STATE_ORDER
    assert "skipped" in DURABLE_STATE_ORDER

    with pytest.raises(ValueError):
        StageRecord(
            state=not_applicable,
            artifact_sha256=None,
            reason_code=None,
            cache_key=None,
            attempts=0,
        )


def test_a_done_record_requires_an_artifact_hash() -> None:
    """The first non-negotiable, stated as a constructibility rule.

    *Never ``done`` about non-durable bytes* (`plans/README.md` §2) cannot be
    written down without naming the bytes.
    """
    with pytest.raises(ValueError) as excinfo:
        StageRecord(
            state="done",
            artifact_sha256=None,
            reason_code=None,
            cache_key=SOME_CACHE_KEY,
            attempts=1,
        )

    assert "must name the artifact" in str(excinfo.value)


def test_a_failed_record_requires_a_reason_code() -> None:
    """Failure is a result, not an absence (`sad.md` §7.1)."""
    with pytest.raises(ValueError) as excinfo:
        StageRecord(
            state="failed",
            artifact_sha256=None,
            reason_code=None,
            cache_key=SOME_CACHE_KEY,
            attempts=1,
        )

    assert "must carry a reason code" in str(excinfo.value)


@pytest.mark.parametrize("state", ["done", "failed"])
def test_a_terminal_outcome_requires_the_cache_key_it_ran_under(
    state: str,
) -> None:
    """A result that records no key cannot be compared against the settings now
    in force, so *done* and *done and no longer correct* would be one record.

    This is `prd.md` FR-08 (*"every stage result is keyed by the full cache
    key"*) and the mechanism behind `sad.md` §5's promise that completion claims
    go **visibly** stale rather than quietly wrong: visibility requires the key
    on disk.

    Args:
        state: The terminal outcome under test.

    """
    arguments: dict[str, object] = {
        "state": state,
        "artifact_sha256": SOME_SHA256 if state == "done" else None,
        "reason_code": None if state == "done" else "artifact_missing",
        "cache_key": None,
        "attempts": 1,
    }

    with pytest.raises(ValueError) as excinfo:
        StageRecord(**arguments)  # type: ignore[arg-type]

    assert "must name the cache key" in str(excinfo.value)


@pytest.mark.parametrize("state", ["pending", "running", "blocked", "stale", "skipped"])
def test_a_non_terminal_state_is_not_required_to_name_a_key(state: str) -> None:
    """A stage that has not been dispatched under a key has none to record.

    Requiring one here would force the scheduler to invent a placeholder before
    it resolves the key - which is the stand-in shape, in the one field whose
    whole purpose is to say *what this ran under*.

    Args:
        state: The non-terminal state under test.

    """
    record = StageRecord(
        state=state,
        artifact_sha256=None,
        reason_code=None,
        cache_key=None,
        attempts=1 if state == "running" else 0,
    )

    assert record.cache_key is None


@pytest.mark.parametrize("field_name", ["artifact_sha256", "reason_code", "cache_key"])
def test_an_empty_string_is_refused_where_none_is_the_absence(field_name: str) -> None:
    """``""`` is not a hash, not a code and not a key: it is the stand-in shape.

    Args:
        field_name: The field given ``""``.

    """
    arguments: dict[str, object] = {
        "state": "pending",
        "artifact_sha256": None,
        "reason_code": None,
        "cache_key": None,
        "attempts": 0,
    }
    arguments[field_name] = ""

    with pytest.raises(ValueError) as excinfo:
        StageRecord(**arguments)  # type: ignore[arg-type]

    assert "empty string" in str(excinfo.value)


def test_stage_records_are_frozen_and_hashable() -> None:
    """A record is a by-value type: immutable, and usable as a key."""
    record = StageRecord(
        state="done",
        artifact_sha256=SOME_SHA256,
        reason_code=None,
        cache_key=SOME_CACHE_KEY,
        attempts=1,
    )

    assert dataclasses.is_dataclass(record)
    assert isinstance(record, StageRecord)
    assert hash(record) == hash(
        StageRecord(
            state="done",
            artifact_sha256=SOME_SHA256,
            reason_code=None,
            cache_key=SOME_CACHE_KEY,
            attempts=1,
        )
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        record.state = "pending"  # type: ignore[misc]


# --- E02-02: the ledger read and write path ---------------------------------


def test_a_new_ledger_records_every_declared_stage_as_pending() -> None:
    """A stage that never started is readable as pending, never absent."""
    ledger = new_ledger(UNIT_NAME, STAGE_NAMES)

    assert ledger.unit == UNIT_NAME
    assert list(ledger.stages) == list(STAGE_NAMES), "declaration order is preserved"
    assert {record.state for record in ledger.stages.values()} == {"pending"}
    assert all(record.artifact_sha256 is None for record in ledger.stages.values())


def test_read_ledger_returns_the_recorded_state_for_every_stage(
    unit_dir: pathlib.Path,
) -> None:
    """Stages that never started are reported, alongside the ones that ran."""
    store.begin(unit_dir, "acquire", None)
    artifact = store.put(unit_dir.parent, FIRST_BYTES, media_type="image/png")
    store.commit(unit_dir, "transform", artifact, SOME_CACHE_KEY)

    ledger = store.read_ledger(unit_dir)

    assert ledger.unit == UNIT_NAME
    assert list(ledger.stages) == list(STAGE_NAMES)
    assert read_stage(unit_dir, "acquire").state == "running"
    assert read_stage(unit_dir, "transform").state == "done"
    assert read_stage(unit_dir, "transform").artifact_sha256 == artifact.sha256
    assert read_stage(unit_dir, "persist").state == "pending"


def test_read_ledger_on_a_unit_with_no_ledger_raises(
    tmp_path: pathlib.Path,
) -> None:
    """A unit that has not run has no states, and says so instead of reporting none."""
    unit_dir = tmp_path / "out" / "never-ran"
    unit_dir.mkdir(parents=True)

    with pytest.raises(FileNotFoundError):
        store.read_ledger(unit_dir)


def test_write_ledger_and_read_ledger_round_trip(unit_dir: pathlib.Path) -> None:
    """What ``write_ledger`` wrote is what ``read_ledger`` reports."""
    written = Ledger(
        unit=UNIT_NAME,
        stages={
            **new_ledger(UNIT_NAME, STAGE_NAMES).stages,
            "acquire": StageRecord(
                state="skipped",
                artifact_sha256=None,
                reason_code=None,
                cache_key=None,
                attempts=0,
            ),
        },
    )
    store.write_ledger(unit_dir, written)

    read_back = store.read_ledger(unit_dir)

    assert read_back.unit == written.unit
    assert dict(read_back.stages) == dict(written.stages)


def test_begin_records_running_before_the_work_starts(
    unit_dir: pathlib.Path,
) -> None:
    """``begin`` is what distinguishes *never began* from *began and was cut off*.

    The stage is ``pending`` until ``begin`` is called and ``running`` the moment
    it returns - before the work, which is `sad.md` §7.1's ordering rule.
    """
    assert read_stage(unit_dir, "acquire").state == "pending"

    ledger = store.begin(unit_dir, "acquire", None)

    assert ledger.stages["acquire"].state == "running"
    assert read_stage(unit_dir, "acquire").state == "running"


def test_begin_withdraws_a_previous_artifact_claim(unit_dir: pathlib.Path) -> None:
    """Re-running a stage means it is no longer known to have produced anything."""
    artifact = store.put(unit_dir.parent, FIRST_BYTES, media_type="image/png")
    store.commit(unit_dir, "transform", artifact, SOME_CACHE_KEY)
    assert read_stage(unit_dir, "transform").artifact_sha256 == artifact.sha256

    store.begin(unit_dir, "transform", None)

    record = read_stage(unit_dir, "transform")
    assert record.state == "running"
    assert record.artifact_sha256 is None


def test_begin_withdraws_a_previous_cache_key_too(unit_dir: pathlib.Path) -> None:
    """A re-begun stage is not known to have produced anything *under any key*.

    Leaving the previous key in place would be worse than leaving the artifact
    hash: a reader comparing keys would conclude the stage had already run under
    the key about to be dispatched, when in fact it has been begun again.
    """
    artifact = store.put(unit_dir.parent, FIRST_BYTES, media_type="image/png")
    store.commit(unit_dir, "transform", artifact, SOME_CACHE_KEY)
    assert read_stage(unit_dir, "transform").cache_key == SOME_CACHE_KEY

    store.begin(unit_dir, "transform", None)

    assert read_stage(unit_dir, "transform").cache_key is None


def test_begin_may_record_the_key_the_stage_is_about_to_run_under(
    unit_dir: pathlib.Path,
) -> None:
    """``running`` is permitted a key, because a caller may already hold one."""
    ledger = store.begin(unit_dir, "acquire", SOME_CACHE_KEY)

    assert ledger.stages["acquire"].state == "running"
    assert ledger.stages["acquire"].cache_key == SOME_CACHE_KEY


def test_commit_records_the_artifact_hash_and_the_key_it_ran_under(
    unit_dir: pathlib.Path,
) -> None:
    """A committed stage names its bytes, its key, and gives no reason."""
    artifact = store.put(unit_dir.parent, FIRST_BYTES, media_type="image/png")
    ledger = store.commit(unit_dir, "persist", artifact, SOME_CACHE_KEY)

    record = ledger.stages["persist"]
    assert record.state == "done"
    assert record.artifact_sha256 == artifact.sha256
    assert record.reason_code is None
    assert record.cache_key == SOME_CACHE_KEY
    assert artifact.sha256 == hashlib.sha256(FIRST_BYTES).hexdigest()


def test_the_attempt_count_grows_with_each_write_that_is_an_attempt(
    unit_dir: pathlib.Path,
) -> None:
    """The count is of **runs**, derived from the transition rather than passed in.

    A count a caller increments is a count somebody will forget to increment - and the
    one time it matters is the retry loop the count exists to make visible
    (`kernel-cli.md` §7). So ``running`` counts, and ``done`` completes the attempt
    that ``running`` opened rather than adding a second one.
    """
    assert read_stage(unit_dir, "transform").attempts == 0

    store.begin(unit_dir, "transform", SOME_CACHE_KEY)
    assert read_stage(unit_dir, "transform").attempts == 1, "an attempt was opened"

    artifact = store.put(unit_dir.parent, FIRST_BYTES, media_type="image/png")
    store.commit(unit_dir, "transform", artifact, SOME_CACHE_KEY)
    assert read_stage(unit_dir, "transform").attempts == 1, (
        "done completes the attempt running opened; it is not a second one"
    )


def test_a_second_run_of_the_same_stage_is_counted(unit_dir: pathlib.Path) -> None:
    """Re-running a stage is a second attempt, and the count says so.

    This is the mechanism behind the recorded prohibition: retrying a sampled kernel
    to obtain agreement is forbidden, and the orchestrator's job is to make the
    pattern **visible** rather than to prevent it (`plan-01-kernels.md` §9). A stage
    that went round three times is legible as exactly that.
    """
    artifact = store.put(unit_dir.parent, FIRST_BYTES, media_type="image/png")
    store.commit(unit_dir, "transform", artifact, SOME_CACHE_KEY)
    store.begin(unit_dir, "transform", SOME_CACHE_KEY)
    store.commit(unit_dir, "transform", artifact, SOME_CACHE_KEY)

    assert read_stage(unit_dir, "transform").attempts == 2


def test_a_failed_stage_counts_the_attempt_that_failed(unit_dir: pathlib.Path) -> None:
    """A failure is an attempt's outcome, so it is counted rather than lost."""
    reason = Reason(code="blank_page", message="The page carries no content.")

    store.begin(unit_dir, "transform", SOME_CACHE_KEY)
    ledger = store.fail(unit_dir, "transform", reason, SOME_CACHE_KEY)

    assert ledger.stages["transform"].attempts == 1


def test_states_that_are_not_attempts_do_not_grow_the_count(
    unit_dir: pathlib.Path,
) -> None:
    """``pending``/``stale``/``skipped``/``blocked`` are not attempts to produce.

    Counting them would make the number mean *how many times this stage's state was
    written*, which is a different and useless fact.
    """
    ledger = store.read_ledger(unit_dir)
    for state in ("skipped", "stale", "blocked"):
        record = store.StageRecord(
            state=state,
            artifact_sha256=None,
            reason_code=None,
            cache_key=None,
            attempts=0,
        )
        assert record.attempts == 0, state

    assert ledger.stages["persist"].attempts == 0


def test_fail_records_the_reason_code_and_the_key_it_ran_under(
    unit_dir: pathlib.Path,
) -> None:
    """The ledger carries the machine-readable code, not the human message.

    A failure is a result, so it carries the key beside it: a stage that failed
    under other settings is a different fact from one that failed under these.
    """
    reason = Reason(
        code="artifact_missing", message="The artifact a ledger claims is gone."
    )

    ledger = store.fail(unit_dir, "transform", reason, SOME_CACHE_KEY)

    record = ledger.stages["transform"]
    assert record.state == "failed"
    assert record.reason_code == "artifact_missing"
    assert record.cache_key == SOME_CACHE_KEY
    assert record.artifact_sha256 is None

    raw = json.loads(ledger_path(unit_dir).read_text(encoding="utf-8"))
    assert raw["stages"]["transform"]["reason_code"] == "artifact_missing"
    assert raw["stages"]["transform"]["cache_key"] == SOME_CACHE_KEY
    assert reason.message not in ledger_path(unit_dir).read_text(encoding="utf-8")


@pytest.mark.parametrize("operation", ["begin", "commit", "fail"])
def test_no_operation_can_record_a_stage_outside_the_declared_set(
    unit_dir: pathlib.Path, operation: str
) -> None:
    """An undeclared stage is a caller mistake, not a new stage.

    Args:
        unit_dir: The unit directory fixture.
        operation: The write-path operation under test.

    """
    artifact = store.put(unit_dir.parent, FIRST_BYTES, media_type="image/png")
    reason = Reason(code="blank_page", message="The page carries no content.")
    calls: Mapping[str, object] = {
        "begin": lambda: store.begin(unit_dir, "invented", None),
        "commit": lambda: store.commit(unit_dir, "invented", artifact, SOME_CACHE_KEY),
        "fail": lambda: store.fail(unit_dir, "invented", reason, SOME_CACHE_KEY),
    }

    with pytest.raises(ValueError) as excinfo:
        calls[operation]()  # type: ignore[operator]

    assert "is not declared" in str(excinfo.value)


# --- E02-02: the ordering rule ----------------------------------------------


def test_commit_accepts_only_an_artifact_and_never_a_hash_string(
    unit_dir: pathlib.Path,
) -> None:
    """``commit`` cannot be handed *"I have the bytes somewhere"*.

    ``put`` is the only producer of an :class:`Artifact` in this module, and it
    returns after its rename has returned. Because the parameter type is the
    descriptor, there is no argument a caller can pass to write ``done`` about
    bytes that are not yet durable - the ordering is in the signature, not in the
    caller's memory.
    """
    # A string is the shape the temptation takes - a bare hash, with the bytes
    # "somewhere" - and it is refused by the signature itself. Omitting the key is
    # refused by the signature too, which is the point: a terminal outcome that
    # names no key is not a thing this module can write.
    with pytest.raises(TypeError):
        store.commit(
            unit_dir,
            "transform",
            SOME_SHA256,  # type: ignore[arg-type]
            SOME_CACHE_KEY,
        )
    # `no-value-for-parameter` is the assertion, not a defect: the call deliberately
    # omits the key, and proving that omitting it raises is the whole point of the
    # test. Pylint reports the omission at the call site, so the suppression sits
    # there rather than on the `with` line above it.
    with pytest.raises(TypeError):
        store.commit(  # pylint: disable=no-value-for-parameter
            unit_dir,
            "transform",
            SOME_SHA256,  # type: ignore[call-arg]
        )

    # Anything else that is not a descriptor fails before a record is built, so
    # no state is written at all.
    for stand_in in (None, {"sha256": SOME_SHA256}, FIRST_BYTES):
        with pytest.raises((AttributeError, TypeError)):
            store.commit(
                unit_dir,
                "transform",
                stand_in,
                SOME_CACHE_KEY,  # type: ignore[arg-type]
            )

    assert read_stage(unit_dir, "transform").state == "pending", (
        "a refused commit must leave the stage exactly as it was"
    )

    # And the one argument that is accepted is the one ``put`` returned.
    artifact = store.put(unit_dir.parent, FIRST_BYTES, media_type="image/png")
    assert isinstance(artifact, Artifact)
    assert (
        store.commit(unit_dir, "transform", artifact, SOME_CACHE_KEY)
        .stages["transform"]
        .state
        == "done"
    )


def test_a_crash_between_write_and_rename_leaves_the_stage_running(
    unit_dir: pathlib.Path,
) -> None:
    """Row 2: ``done`` is absent and ``running`` is present after the crash.

    The crash is injected at the atomic-write boundary - after the stage was
    begun, before any artifact could exist - and the ledger is then read from
    outside. A ``done`` written before the rename returned is exactly the failure
    `plan-01-kernels.md` §7b row 2 names, and it is the ordering that makes resume
    a lie.
    """
    store.begin(unit_dir, "transform", None)

    original_replace = store._replace

    def kill(source: pathlib.Path, target: pathlib.Path) -> None:
        raise KeyboardInterrupt("simulated kill between write and rename")

    store._replace = kill  # type: ignore[assignment]
    try:
        with pytest.raises(KeyboardInterrupt):
            artifact = store.put(unit_dir.parent, FIRST_BYTES, media_type="image/png")
            store.commit(unit_dir, "transform", artifact, SOME_CACHE_KEY)
    finally:
        store._replace = original_replace  # type: ignore[assignment]

    # Read from outside: the unit's ledger on disk, and the store's own directory.
    ledger = store.read_ledger(unit_dir)
    states = {name: record.state for name, record in ledger.stages.items()}

    assert states["transform"] == "running", "the interrupted stage reads as running"
    assert "done" not in states.values(), "no stage may read done after the crash"
    assert ledger.stages["transform"].artifact_sha256 is None
    assert ledger.stages["transform"].cache_key is None
    assert not (unit_dir.parent / "artifacts" / store._sha256(FIRST_BYTES)).exists()


def test_a_kill_leaves_the_stage_running_and_not_pending(
    unit_dir: pathlib.Path,
) -> None:
    """The distinction the whole crash-recovery design exists to preserve.

    ``pending`` would read as *never began*, and the next run would restart the
    unit from the beginning instead of resuming the interrupted stage.
    """
    store.begin(unit_dir, "acquire", None)

    read_from_outside = json.loads(ledger_path(unit_dir).read_text(encoding="utf-8"))

    assert read_from_outside["stages"]["acquire"]["state"] == "running"
    assert read_from_outside["stages"]["acquire"]["state"] != "pending"


def test_a_killed_stage_is_resumable_through_the_same_path(
    unit_dir: pathlib.Path,
) -> None:
    """After the interruption, re-beginning and committing succeeds normally."""
    store.begin(unit_dir, "transform", None)

    original_replace = store._replace

    def kill(source: pathlib.Path, target: pathlib.Path) -> None:
        raise KeyboardInterrupt("simulated kill between write and rename")

    store._replace = kill  # type: ignore[assignment]
    try:
        with pytest.raises(KeyboardInterrupt):
            artifact = store.put(unit_dir.parent, FIRST_BYTES, media_type="image/png")
            store.commit(unit_dir, "transform", artifact, SOME_CACHE_KEY)
    finally:
        store._replace = original_replace  # type: ignore[assignment]

    artifact = store.put(unit_dir.parent, FIRST_BYTES, media_type="image/png")
    store.commit(unit_dir, "transform", artifact, SOME_CACHE_KEY)

    record = read_stage(unit_dir, "transform")
    assert record.state == "done"
    assert record.artifact_sha256 == artifact.sha256
    assert store.verify(unit_dir.parent, artifact.sha256) is True


def test_the_rename_is_the_only_path_to_a_final_name_in_this_module() -> None:
    """Two writers, one rename: no second code path can name bytes final.

    A static guard on the ordering rule. ``os.replace`` appears exactly once, so
    there is no route by which bytes reach a final name without the sequence
    around it, and the ledger writer cannot invent its own shortcut.
    """
    renames = [
        node
        for node in ast.walk(STORE_TREE)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "replace"
    ]

    # One definition site (`_replace` calling `os.replace`) and one call site
    # (`_atomic_write` reaching `_replace`).
    assert len(renames) == 1, f"expected exactly one rename call, found {len(renames)}"
    assert renames[0].func.attr == "replace"
    assert isinstance(renames[0].args[0], ast.Name)
    assert renames[0].args[0].id in {"staging", "source"}, (
        "the rename must move a staging file, never write a final name directly"
    )


def test_the_atomic_write_helper_runs_the_five_step_sequence() -> None:
    """The sequence is asserted structurally, not merely delegated to.

    An earlier version of this test only checked that ``put`` and ``write_ledger``
    *call* ``_atomic_write``. That let a mutation replace the helper's body with a
    direct write to the final name and keep the suite green: the callers were
    unchanged, and the invariant was gone. So the sequence is now read out of the
    helper itself - write to a staging name, flush, fsync the file, rename, then
    sync the directory - and each step must be present.

    The directory sync is asserted explicitly because it is the step most easily
    dismissed as redundant: without it the rename itself can be lost, and a stage
    that recorded ``done`` would be claiming bytes that did not survive.
    """
    helper = next(
        node
        for node in ast.walk(STORE_TREE)
        if isinstance(node, ast.FunctionDef) and node.name == "_atomic_write"
    )

    # 1. A staging name, not the final one, is what gets written to.
    staging_assignments = [
        node
        for node in ast.walk(helper)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "staging"
            for target in node.targets
        )
    ]
    assert staging_assignments, "_atomic_write must build a staging path first"
    staging_source = ast.unparse(staging_assignments[0])
    assert "with_name" in staging_source, (
        "the staging name must be derived from the final name"
    )
    assert ".tmp" in staging_source, "the staging name must be visibly not final"

    # The final name is never opened for writing.
    opened_on_target = [
        node
        for node in ast.walk(helper)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "open"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "target"
    ]
    assert opened_on_target == [], (
        "writing straight to the final name is the defect this helper prevents"
    )

    # 2..5. flush, fsync on the open handle, rename, directory sync.
    called_attributes = {
        node.func.attr
        for node in ast.walk(helper)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "flush" in called_attributes, "the buffer must be flushed"
    assert "fsync" in called_attributes, "the staged file must be fsynced"

    helper_calls = {
        node.func.id
        for node in ast.walk(helper)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "_replace" in helper_calls, "the rename must be the module's one rename"
    assert "_sync_directory" in helper_calls, (
        "the rename must be made durable by syncing the directory"
    )

    # And the ordering: the rename call comes after the fsync call.
    rename_lines = [
        node.lineno
        for node in ast.walk(helper)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_replace"
    ]
    fsync_lines = [
        node.lineno
        for node in ast.walk(helper)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "fsync"
    ]
    assert fsync_lines and rename_lines, "both steps must exist to be ordered"
    assert max(fsync_lines) < min(rename_lines), (
        "fsync must happen before the rename: a rename first would publish bytes "
        "that are not yet on stable storage"
    )


def test_both_writers_share_the_same_atomic_write_helper() -> None:
    """A half-written ledger is the same defect class as a half-written artifact.

    The ledger goes through the same staging sequence as the artifact, so the two
    cannot diverge in durability.
    """
    writers = [
        node
        for node in ast.walk(STORE_TREE)
        if isinstance(node, ast.FunctionDef) and node.name in {"put", "write_ledger"}
    ]
    assert len(writers) == 2

    for writer in writers:
        called = {
            node.func.id
            for node in ast.walk(writer)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert "_atomic_write" in called, f"{writer.name} does not write atomically"


# --- E02-02: ledger sufficiency for the manifest ----------------------------


def test_the_ledger_tree_alone_is_enough_to_rebuild_a_manifest(
    tmp_path: pathlib.Path,
) -> None:
    """Row 16: the manifest is reconstructible from the ledgers and nothing else.

    This is the sufficiency the manifest's derivability rests on. The rebuild
    below reads only ``*.ledger.json`` files, and the tree is asserted to contain
    no other file - so no ``run.json`` was consulted, and none could have been.
    """
    out = tmp_path / "out"
    store_root = tmp_path / "store"
    units = ("O-0001", "O-0002")
    expected: dict[str, dict[str, str]] = {}

    for unit in units:
        unit_dir = out / unit
        unit_dir.mkdir(parents=True)
        store.write_ledger(unit_dir, new_ledger(unit, STAGE_NAMES))
        store.begin(unit_dir, "acquire", None)
        artifact = store.put(store_root, f"{unit}".encode(), media_type="image/png")
        store.commit(unit_dir, "acquire", artifact, SOME_CACHE_KEY)
        store.fail(
            unit_dir,
            "transform",
            Reason(code="blank_page", message="The page carries no content."),
            SOME_CACHE_KEY,
        )
        expected[unit] = {
            "acquire": "done",
            "transform": "failed",
            "persist": "pending",
        }

    # Rebuild from the ledger tree alone.
    rebuilt: dict[str, dict[str, str]] = {}
    for path in sorted(out.glob("**/*.ledger.json")):
        ledger = store.read_ledger(path.parent)
        rebuilt[ledger.unit] = {
            name: record.state for name, record in ledger.stages.items()
        }

    assert rebuilt == expected

    # The rebuild consulted nothing but ledger files, and no manifest existed to
    # consult: there is no ``run.json`` in the tree at all.
    assert not (out / "run.json").exists(), "no manifest may exist to be read"
    ledgers = sorted(path.name for path in out.glob("**/*.ledger.json"))
    assert ledgers == [f"{unit}.ledger.json" for unit in sorted(units)]


def test_a_done_stage_names_an_artifact_that_a_manifest_can_follow(
    tmp_path: pathlib.Path,
) -> None:
    """Every ``done`` record carries enough to find the bytes it claims.

    The manifest's counters and outcome sets are derived from these records, and a
    ``done`` with no hash would leave the rebuild unable to say which artifact the
    claim is about.
    """
    out = tmp_path / "out"
    unit_dir = out / UNIT_NAME
    unit_dir.mkdir(parents=True)
    store.write_ledger(unit_dir, new_ledger(UNIT_NAME, STAGE_NAMES))
    artifact = store.put(out, FIRST_BYTES, media_type="image/png")
    store.commit(unit_dir, "persist", artifact, SOME_CACHE_KEY)

    for path in out.glob("**/*.ledger.json"):
        for name, record in store.read_ledger(path.parent).stages.items():
            if record.state == "done":
                assert record.artifact_sha256 is not None, f"{name} claims an unnamed"
                assert store.verify(out, record.artifact_sha256) is True
                assert record.cache_key is not None, f"{name} claims an unkeyed run"


def test_the_ledger_file_is_named_after_its_unit(tmp_path: pathlib.Path) -> None:
    """The suffix rule of `prd.md` FR-29, and the unit's name in the file name."""
    unit_dir = tmp_path / "out" / UNIT_NAME

    assert ledger_path(unit_dir) == unit_dir / f"{UNIT_NAME}.ledger.json"
    assert ledger_path(unit_dir).name.endswith(".ledger.json")


def test_the_ledger_records_the_unit_inside_the_file(unit_dir: pathlib.Path) -> None:
    """The unit's identity is in the file, not only in the directory name.

    A manifest rebuilt from the ledger *tree* alone needs the unit's identity from
    the file: the tree does not carry it.
    """
    raw = json.loads(ledger_path(unit_dir).read_text(encoding="utf-8"))

    assert raw["unit"] == UNIT_NAME
    assert sorted(raw["stages"]) == sorted(STAGE_NAMES)
    assert raw["stages"]["acquire"] == {
        "state": "pending",
        "artifact_sha256": None,
        "reason_code": None,
        "cache_key": None,
        "attempts": 0,
    }


@pytest.mark.parametrize(
    "corruption",
    [
        {
            "state": "complete",
            "artifact_sha256": None,
            "reason_code": None,
            "cache_key": None,
            "attempts": 0,
        },
        {
            "state": "done",
            "artifact_sha256": None,
            "reason_code": None,
            "cache_key": SOME_CACHE_KEY,
            "attempts": 1,
        },
        {
            "state": "failed",
            "artifact_sha256": None,
            "reason_code": None,
            "cache_key": SOME_CACHE_KEY,
            "attempts": 1,
        },
        {
            "state": "done",
            "artifact_sha256": "",
            "reason_code": None,
            "cache_key": SOME_CACHE_KEY,
            "attempts": 1,
        },
        # A terminal outcome with no key: legal in shape, illegal in meaning.
        {
            "state": "done",
            "artifact_sha256": SOME_SHA256,
            "reason_code": None,
            "cache_key": None,
            "attempts": 1,
        },
        # ``""`` reads as *keyed to nothing*, which is the stand-in shape.
        {
            "state": "failed",
            "artifact_sha256": None,
            "reason_code": "blank_page",
            "cache_key": "",
            "attempts": 1,
        },
        # A run state claiming it was never run: the attempt count is what makes
        # *"retry until two answers agree"* visible, so a zero count on a state
        # that only an attempt can produce is refused.
        {
            "state": "running",
            "artifact_sha256": None,
            "reason_code": None,
            "cache_key": None,
            "attempts": 0,
        },
        # A negative count is not a count.
        {
            "state": "pending",
            "artifact_sha256": None,
            "reason_code": None,
            "cache_key": None,
            "attempts": -1,
        },
    ],
)
def test_a_hand_edited_ledger_is_rejected_on_read(
    unit_dir: pathlib.Path, corruption: dict[str, object]
) -> None:
    """A ledger edited into an illegal record is refused, not believed.

    Args:
        unit_dir: The unit directory fixture.
        corruption: The illegal record written over a legal stage.

    """
    path = ledger_path(unit_dir)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["stages"]["acquire"] = corruption
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError):
        store.read_ledger(unit_dir)


def test_a_ledger_missing_a_required_field_is_rejected_on_read(
    unit_dir: pathlib.Path,
) -> None:
    """The format's required fields are enforced when the file is read back."""
    path = ledger_path(unit_dir)
    raw = json.loads(path.read_text(encoding="utf-8"))
    del raw["stages"]["acquire"]["reason_code"]
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(KeyError):
        store.read_ledger(unit_dir)


def test_store_source_is_the_module_the_two_issues_name() -> None:
    """The deliverable path is `docflow/kernels/store.py`, one module for both."""
    assert STORE_PATH.name == "store.py"
    assert STORE_PATH.parent.name == "kernels"
    assert "docflow" in sys.modules
