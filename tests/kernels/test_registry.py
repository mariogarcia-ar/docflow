"""Tests for K8 - the registry loader and the one registry hash.

One test module per source module, mirroring ``src/docflow``. This one covers
``E03-01`` (``S1-T04``): load, schema-validate, fail fast, ``registry_hash``.

The load-bearing tests are the **fail-fast** ones and the **hash-change** one.
Row 17 of `kernel-cli.md` §11 is the failure they assert against: *a missing asset
defaulted, producing a run that extracts nothing*. An earlier version of a suite
like this asserts that loading works; the invariant here is the opposite - that
loading **stops**, and stops with a code a script can branch on.

Three Pylint relaxations are declared below, each because the rule contradicts what
this suite is for: ``protected-access`` (the private helpers are the units whose
failure modes need attributing), ``duplicate-code`` (a contract test restates the
codes it checks instead of importing them), and ``too-many-lines`` (one test per
acceptance criterion, and splitting would separate each invariant from its
falsification test).
"""

# pylint: disable=protected-access
# The reason-code constants and the manifest/asset helpers are reached directly
# because the acceptance criteria are about *which* code a failure carries and
# *which* asset it names. Testing only through `load_registry` would leave the
# manifest's own failure modes unattributable.

# pylint: disable=duplicate-code
# ``_CODE_ASSET_MISSING`` and ``_CODE_ASSET_INVALID`` are restated here on purpose.
# A contract test must hold its own copy of the closed vocabulary it verifies:
# importing the constants would make the assertion vacuous, and reading the codes
# from the module under test is how a vocabulary drifts unnoticed.

# pylint: disable=too-many-lines
# One test per acceptance criterion of two `M` issues plus one per lint guard.

# pylint: disable=use-implicit-booleaness-not-comparison
# The two sites this covers compare a guard's result to the empty list on purpose.
# ``assert not find_dependency_violations(...)`` would also pass if the guard
# returned ``None``, so a guard broken into returning nothing at all would read as
# *no violations found* - the exact vacuous pass these guards exist to prevent.

# pylint: disable=line-too-long
# Two lines exceed 88 characters in a place `ruff format` cannot split: a long test
# name on its own ``def`` line, and a declaration table whose entries are dict
# literals. `ruff format` owns line length (E501 is ignored for the same reason), so
# the formatter's own output is not a defect.

from __future__ import annotations

import ast
import hashlib
import json
import pathlib
from collections.abc import Iterator
from types import MappingProxyType

import pytest

from docflow.kernels import registry as registry_module
from docflow.kernels.registry import (
    ASSET_FORMAT_JSON,
    ASSET_FORMAT_TEXT,
    MANIFEST_NAME,
    SUPPORTED_ASSET_FORMATS,
    Registry,
    load_registry,
    registry_hash,
)
from docflow.kernels.types import KernelResult

# --- Constants ---------------------------------------------------------------

REGISTRY_PATH: pathlib.Path = pathlib.Path(registry_module.__file__).resolve()
REGISTRY_SOURCE: str = REGISTRY_PATH.read_text(encoding="utf-8")
REGISTRY_TREE: ast.Module = ast.parse(REGISTRY_SOURCE, filename=str(REGISTRY_PATH))

#: The two reason codes row 17 asserts on, restated rather than imported.
CODE_ASSET_MISSING: str = "asset_missing"
CODE_ASSET_INVALID: str = "asset_invalid"

#: The closed set of legal codes for this module.
REGISTRY_REASON_CODES: frozenset[str] = frozenset(
    {CODE_ASSET_MISSING, CODE_ASSET_INVALID}
)

#: The asset keys the tests declare. Deliberately generic: this module must not
#: know a family name, so the tests must not teach it one.
PROMPT_KEY: str = "prompts/one.txt"
SCHEMA_KEY: str = "schemas/one.json"
POLICY_KEY: str = "policies/one.json"

PROMPT_TEXT: str = "extract the total\n"
SCHEMA_BODY: str = '{"title": "one", "properties": {}}\n'
POLICY_BODY: str = '{"threshold": 0.5}\n'

#: Domain vocabulary no kernel identifier may contain (`kernel-cli.md` §14).
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

#: Module roots the registry may import: standard library plus its own layer. K8 is
#: a kernel, so it reaches nothing above itself.
ALLOWED_IMPORT_ROOTS: frozenset[str] = frozenset(
    {"__future__", "collections", "dataclasses", "docflow", "hashlib", "json"}
    | {"pathlib", "types", "typing"}
)

#: Prefixes of ``docflow`` the registry may import from.
ALLOWED_DOCFLOW_IMPORT_PREFIXES: frozenset[str] = frozenset({"docflow.kernels"})

#: Falsy literals that would be a stand-in for a failure if a function returned one.
FALSY_STAND_IN_LITERALS: tuple[str, ...] = (
    "None",
    '""',
    'b""',
    "0",
    "[]",
    "{}",
    "()",
)
#: Lines where an empty collection is the *answer* rather than a stand-in, with
#: the reason each one is legitimate. Declared as data so a new exemption cannot be
#: added by quietly widening a condition: it has to be justified in this table.
#:
#: The distinction the guard is about: ``return []`` meaning *"I looked, and there
#: were none"* is an answer; ``return b""`` or ``return ""`` meaning *"I have no
#: bytes and no string"* is a stand-in for a failure. Only the second is a defect,
#: and the two are told apart by what the function is for.
#:
#: The rule that makes the exemption principled rather than a list of conveniences:
#: every entry here is a **collecting validator** - a function whose declared return
#: is *the findings it has about something*, where an empty list is the good news.
#: ``_load_assets`` follows the same rule but accumulates into a caller-supplied
#: mapping, so it has no ``return`` to exempt.
EMPTY_COLLECTION_RETURNS_THAT_ARE_ANSWERS: dict[str, str] = {
    "_check_declaration": "returns the findings about one declaration; none is good",
    "_undeclared_files": "returns the undeclared keys; none found is the good case",
}

# --- Fixtures and helpers ----------------------------------------------------


def write_manifest(
    root: pathlib.Path, assets: object, name: str = MANIFEST_NAME
) -> pathlib.Path:
    """Write a manifest file whose ``assets`` value is exactly what was given.

    The parameter is the ``assets`` **value**, not the whole document. That
    distinction is load-bearing and was got wrong at first: passing a document and
    wrapping it again wrote ``{"assets": {"assets": ...}}``, so every malformed
    case failed on the outer shape and **none of them reached the check it was
    written to exercise**. The suite stayed green with the manifest validator
    disabled, which is how the defect was found.

    Args:
        root: The registry root.
        assets: The ``assets`` value, written as-is so an invalid shape can be
            exercised.
        name: The manifest's file name.

    Returns:
        The path written.

    """
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        assets if isinstance(assets, str) else json.dumps({"assets": assets}),
        encoding="utf-8",
    )
    return path


def write_asset(root: pathlib.Path, key: str, content: bytes | str) -> pathlib.Path:
    """Write one asset under the root.

    Args:
        root: The registry root.
        key: The asset's root-relative key.
        content: The bytes or text to write.

    Returns:
        The path written.

    """
    path = root / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    return path


@pytest.fixture(name="registry_root")
def registry_root_fixture(tmp_path: pathlib.Path) -> pathlib.Path:
    """Provide a valid two-asset registry that loads successfully.

    Args:
        tmp_path: Pytest's per-test temporary directory.

    Returns:
        A root whose manifest and assets agree.

    """
    root = tmp_path / "registry"
    root.mkdir()
    write_asset(root, PROMPT_KEY, PROMPT_TEXT)
    write_asset(root, SCHEMA_KEY, SCHEMA_BODY)
    write_manifest(
        root,
        [
            {"key": PROMPT_KEY, "format": ASSET_FORMAT_TEXT},
            {"key": SCHEMA_KEY, "format": ASSET_FORMAT_JSON},
        ],
    )
    return root


def loaded(root: pathlib.Path) -> Registry:
    """Load a root and assert it succeeded, returning the registry.

    Args:
        root: The registry root.

    Returns:
        The loaded registry.

    """
    result = load_registry(root)
    assert result.reason is None, f"expected a valid registry, got {result.reason!r}"
    assert result.value is not None
    return result.value


def failure(root: pathlib.Path) -> KernelResult[Registry]:
    """Load a root and assert it failed, returning the failed result.

    Args:
        root: The registry root.

    Returns:
        The failed result.

    """
    result = load_registry(root)
    assert result.value is None, "a failed load must carry no value"
    assert result.reason is not None
    return result


def is_empty_display(node: ast.expr) -> bool:
    """Report whether an expression is an empty literal display.

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
    """Collect lines where a function returns a stand-in rather than an answer.

    Two shapes count as a stand-in, because they are the same defect written two
    ways: the empty **string** and the empty **buffer**, both of which mean *"I
    have no content"* where the caller needs a failure. ``None`` and ``0`` are
    included for the same reason.

    An empty **collection** is deliberately not flagged. Returning ``[]`` from a
    function whose job is to report *which* things were found is an answer - *there
    were none* - and flagging it would force that function to signal the same fact
    some less direct way. The distinction is between a container that reports a set
    of findings and a value that stands in for missing content, and it is stated
    here rather than left to whoever reads the assertion.

    Args:
        tree: The parsed module.

    Returns:
        The line numbers of every ``return`` of an empty string, buffer, ``None``
        or ``0``, ignoring ``True``/``False`` because a boolean answer is a result.

    """
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Return) or node.value is None:
            continue
        value = node.value
        if not isinstance(value, ast.Constant):
            continue
        if isinstance(value.value, bool):
            continue
        if value.value is None or value.value in ("", b"", 0):
            lines.append(node.lineno)
    return lines


def collect_collection_returns(tree: ast.Module) -> list[tuple[str, int]]:
    """Collect ``return <empty collection>`` with the enclosing function's name.

    Reported with the name so the exemption table can be checked against it, and
    so an empty collection returned from a function that is *not* exempted fails.

    Args:
        tree: The parsed module.

    Returns:
        ``(function name, line)`` for every empty collection returned.

    """
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            if (
                isinstance(inner, ast.Return)
                and inner.value is not None
                and is_empty_display(inner.value)
            ):
                found.append((node.name, inner.lineno))
    return found


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

    The allowed surface of a kernel is its own layer and nothing above it, so a
    submodule of an allowed prefix is legal and a sibling package under
    ``docflow`` is not. Checking the *root* (``docflow``) alone would accept
    ``docflow.adapters``, which is the whole defect the guard exists for.

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
        if root != "docflow" or name == "docflow":
            continue
        if not any(
            name == prefix or name.startswith(f"{prefix}.")
            for prefix in ALLOWED_DOCFLOW_IMPORT_PREFIXES
        ):
            offending.append(name)
    return offending


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


# --- Static guards -----------------------------------------------------------


def test_registry_imports_nothing_outside_the_standard_library_and_its_own_layer() -> (
    None
):
    """K8 depends on stdlib plus ``docflow.kernels``, and on nothing above it.

    The check is on the full dotted path, not the root: a root-only check would
    accept ``docflow.adapters`` because its root is ``docflow``.
    """
    imported = collect_imported_modules(REGISTRY_TREE)

    assert find_dependency_violations(imported) == [], (
        f"the registry reached outside its layer: {find_dependency_violations(imported)}"
    )
    assert any(name.split(".")[0] == "docflow" for name in imported), (
        "the registry must consume the frozen boundary types"
    )


def test_the_dependency_guard_is_not_vacuous() -> None:
    """The guard reads what it is given, rather than answering always."""
    tree = ast.parse("from docflow.adapters import docling\nimport json\n")

    assert collect_imported_modules(tree) == ["docflow.adapters", "json"]
    assert find_dependency_violations(collect_imported_modules(tree)) == [
        "docflow.adapters"
    ]

    clean = ast.parse("import json\nfrom docflow.kernels.types import Reason\n")
    assert find_dependency_violations(collect_imported_modules(clean)) == []


def test_no_registry_identifier_contains_a_domain_noun() -> None:
    """K8 holds no document concept: it holds assets, and their names are data."""
    offences = [
        (name, line)
        for name, line in iter_module_identifiers(REGISTRY_TREE)
        if any(token.lower() in name.lower() for token in FORBIDDEN_DOMAIN_VOCABULARY)
    ]

    assert offences == [], f"domain vocabulary in identifiers: {offences}"


def test_no_registry_function_returns_a_falsy_literal_as_a_stand_in() -> None:
    """A failed load carries a ``Reason``; it never returns empty content."""
    assert not collect_falsy_constant_returns(REGISTRY_TREE), (
        "a falsy literal returned from a function is the shape a silent failure "
        "takes (`.github/copilot-instructions.md`, never a silent stand-in)"
    )


def test_an_empty_collection_is_returned_only_where_it_is_an_answer() -> None:
    """An empty collection is allowed only in the functions declared as reporting.

    ``_undeclared_files`` returns the undeclared keys, and *none found* is the
    good outcome; an empty collection returned anywhere else is a stand-in and
    fails here. The exemption is a table rather than a widened condition, so
    adding one means justifying it in the source.
    """
    offenders = [
        (name, line)
        for name, line in collect_collection_returns(REGISTRY_TREE)
        if name not in EMPTY_COLLECTION_RETURNS_THAT_ARE_ANSWERS
    ]

    assert offenders == [], f"unexpected empty-collection returns: {offenders}"
    assert set(EMPTY_COLLECTION_RETURNS_THAT_ARE_ANSWERS) == {
        name for name, _ in collect_collection_returns(REGISTRY_TREE)
    }, "the exemption table must list exactly the functions that return one"
    for function_name, reason in EMPTY_COLLECTION_RETURNS_THAT_ARE_ANSWERS.items():
        assert reason, f"{function_name} needs a stated reason"


# --- E03-01: load ------------------------------------------------------------


def test_load_returns_every_declared_asset(registry_root: pathlib.Path) -> None:
    """A valid root loads whole: every declared asset, none invented."""
    loaded_registry = loaded(registry_root)

    assert sorted(loaded_registry.assets) == sorted([PROMPT_KEY, SCHEMA_KEY])
    assert loaded_registry.assets[PROMPT_KEY].content == PROMPT_TEXT.encode()
    assert loaded_registry.assets[PROMPT_KEY].format == ASSET_FORMAT_TEXT
    assert loaded_registry.assets[SCHEMA_KEY].format == ASSET_FORMAT_JSON


def test_each_asset_carries_the_hash_of_its_own_content(
    registry_root: pathlib.Path,
) -> None:
    """The asset's hash is the hash of its bytes, so a change is detectable."""
    loaded_registry = loaded(registry_root)

    assert (
        loaded_registry.assets[SCHEMA_KEY].sha256
        == hashlib.sha256(SCHEMA_BODY.encode()).hexdigest()
    )


def test_load_reports_what_it_loaded_as_evidence(registry_root: pathlib.Path) -> None:
    """The call always observes something: counts, and the manifest's own hash."""
    result = load_registry(registry_root)

    assert result.evidence.measurements["assets_declared"] == 2.0
    assert result.evidence.measurements["assets_loaded"] == 2.0
    assert (
        result.evidence.terms["manifest_sha256"]
        == hashlib.sha256((registry_root / MANIFEST_NAME).read_bytes()).hexdigest()
    )


def test_an_asset_may_be_the_only_asset_in_its_family(
    tmp_path: pathlib.Path,
) -> None:
    """Nothing requires a family to be non-empty: only declared assets must exist.

    A single-asset registry is valid, because "which families exist" is content
    this module deliberately does not know.
    """
    root = tmp_path / "registry"
    root.mkdir()
    write_asset(root, POLICY_KEY, POLICY_BODY)
    write_manifest(root, [{"key": POLICY_KEY, "format": ASSET_FORMAT_JSON}])

    assert sorted(loaded(root).assets) == [POLICY_KEY]


def test_a_json_asset_may_declare_required_keys(tmp_path: pathlib.Path) -> None:
    """A declared required key is checked at load, and satisfied by the asset."""
    root = tmp_path / "registry"
    root.mkdir()
    write_asset(root, POLICY_KEY, POLICY_BODY)
    write_manifest(
        root,
        [
            {
                "key": POLICY_KEY,
                "format": ASSET_FORMAT_JSON,
                "required_keys": ["threshold"],
            }
        ],
    )

    assert sorted(loaded(root).assets) == [POLICY_KEY]


# --- E03-01: a missing asset is never defaulted (row 17) ---------------------


def test_a_missing_asset_fails_the_load_naming_it(tmp_path: pathlib.Path) -> None:
    """Row 17: exit-3 reason, the missing asset named, nothing substituted.

    This is the failure the issue exists for. A defaulted asset produces a run
    that completes and extracts nothing, which is indistinguishable from a corpus
    with no extractable fields.
    """
    root = tmp_path / "registry-broken"
    root.mkdir()
    write_asset(root, PROMPT_KEY, PROMPT_TEXT)
    write_asset(root, SCHEMA_KEY, SCHEMA_BODY)
    write_manifest(
        root,
        [
            {"key": PROMPT_KEY},
            {"key": SCHEMA_KEY, "format": ASSET_FORMAT_JSON},
            {"key": "schemas/removed.json", "format": ASSET_FORMAT_JSON},
        ],
    )
    (root / "schemas" / "removed.json").unlink(missing_ok=True)

    result = failure(root)

    assert result.reason.code == CODE_ASSET_MISSING
    assert result.evidence.observed["asset_key"] == "schemas/removed.json"
    assert "schemas/removed.json" in result.reason.message


def test_a_missing_asset_never_yields_a_partial_registry(
    tmp_path: pathlib.Path,
) -> None:
    """The assets that *did* load are not handed back either.

    A partially populated registry is the shape the silent failure takes: the
    caller proceeds, the renderer runs, and the missing prompt is simply absent.
    """
    root = tmp_path / "registry"
    root.mkdir()
    write_asset(root, PROMPT_KEY, PROMPT_TEXT)
    write_manifest(
        root,
        [{"key": PROMPT_KEY}, {"key": "prompts/two.txt"}],
    )

    result = failure(root)

    assert result.value is None, "no value at all, not the one asset that loaded"
    assert result.reason.code == CODE_ASSET_MISSING


def test_a_missing_manifest_fails_rather_than_implying_an_empty_registry(
    tmp_path: pathlib.Path,
) -> None:
    """Without a manifest there is no declared set, so the load cannot succeed."""
    root = tmp_path / "registry"
    root.mkdir()
    write_asset(root, PROMPT_KEY, PROMPT_TEXT)

    result = failure(root)

    assert result.reason.code == CODE_ASSET_MISSING
    assert result.evidence.observed["asset_key"] == MANIFEST_NAME


def test_a_missing_asset_is_not_confused_with_an_empty_one(
    tmp_path: pathlib.Path,
) -> None:
    """Absent and empty are different facts, and both fail - with different codes.

    Row 17 is about the absent case; the empty case is the same class of defect
    spelled differently, and collapsing the two would make one of them
    unattributable.
    """
    absent_root = tmp_path / "absent"
    absent_root.mkdir()
    write_manifest(absent_root, [{"key": PROMPT_KEY}])

    empty_root = tmp_path / "empty"
    empty_root.mkdir()
    write_asset(empty_root, PROMPT_KEY, b"")
    write_manifest(empty_root, [{"key": PROMPT_KEY}])

    absent = failure(absent_root)
    empty = failure(empty_root)

    assert absent.reason.code == CODE_ASSET_MISSING
    assert empty.reason.code == CODE_ASSET_INVALID
    assert absent.reason.code != empty.reason.code


# --- E03-01: a malformed asset stops the run ---------------------------------


def test_a_json_asset_that_does_not_parse_is_invalid(tmp_path: pathlib.Path) -> None:
    """A malformed asset stops the run with ``asset_invalid``."""
    root = tmp_path / "registry"
    root.mkdir()
    write_asset(root, SCHEMA_KEY, "{not json")
    write_manifest(root, [{"key": SCHEMA_KEY, "format": ASSET_FORMAT_JSON}])

    result = failure(root)

    assert result.reason.code == CODE_ASSET_INVALID
    assert result.evidence.observed["asset_key"] == SCHEMA_KEY


def test_a_json_asset_that_is_not_an_object_is_invalid(tmp_path: pathlib.Path) -> None:
    """A JSON list is valid JSON and still not an asset of this kind."""
    root = tmp_path / "registry"
    root.mkdir()
    write_asset(root, SCHEMA_KEY, "[1, 2]\n")
    write_manifest(root, [{"key": SCHEMA_KEY, "format": ASSET_FORMAT_JSON}])

    result = failure(root)

    assert result.reason.code == CODE_ASSET_INVALID
    assert "must be a JSON object" in result.reason.message


def test_a_declared_required_key_that_is_absent_is_invalid(
    tmp_path: pathlib.Path,
) -> None:
    """A declared key is a requirement, and a requirement is never defaulted."""
    root = tmp_path / "registry"
    root.mkdir()
    write_asset(root, POLICY_KEY, '{"other": 1}\n')
    write_manifest(
        root,
        [
            {
                "key": POLICY_KEY,
                "format": ASSET_FORMAT_JSON,
                "required_keys": ["threshold"],
            }
        ],
    )

    result = failure(root)

    assert result.reason.code == CODE_ASSET_INVALID
    assert "threshold" in result.reason.message
    assert result.evidence.observed["asset_key"] == POLICY_KEY


def test_a_manifest_that_does_not_parse_stops_the_run(tmp_path: pathlib.Path) -> None:
    """A manifest is an asset of the load path too, and is checked the same way."""
    root = tmp_path / "registry"
    root.mkdir()
    write_manifest(root, "{not json")

    assert failure(root).reason.code == CODE_ASSET_INVALID


@pytest.mark.parametrize(
    "assets",
    [
        "not-a-list",
        [1, 2],
        [{"format": ASSET_FORMAT_TEXT}],
        [{"key": ""}],
        [{"key": PROMPT_KEY}, {"key": PROMPT_KEY}],
        [{"key": PROMPT_KEY, "format": "yaml"}],
        [{"key": "/etc/passwd"}],
        [{"key": "../outside.txt"}],
        [{"key": ".hidden"}],
        [{"key": PROMPT_KEY, "required_keys": [""]}],
        [{"key": PROMPT_KEY, "format": ASSET_FORMAT_TEXT, "required_keys": ["a"]}],
    ],
    ids=[
        "assets-not-a-list",
        "entry-not-an-object",
        "entry-without-key",
        "empty-key",
        "duplicate-key",
        "unsupported-format",
        "absolute-key-escapes-the-root",
        "parent-traversal-escapes-the-root",
        "hidden-key-is-not-an-asset",
        "required-key-without-a-name",
        "required-keys-on-a-non-json-asset",
    ],
)
def test_a_malformed_manifest_stops_the_run(
    tmp_path: pathlib.Path, assets: object
) -> None:
    """Every unusable declaration shape fails, and fails as ``asset_invalid``.

    Each case is one *declaration* problem, written so that nothing but the
    intended check can reject it: the asset file it names exists and is valid
    text, so the declaration itself is the only reason to fail. An earlier version
    of this test passed the whole manifest document and had it wrapped a second
    time, so every case tripped on the outer shape instead of on its own
    declaration - the suite stayed green with the declaration validator disabled.

    Args:
        tmp_path: Pytest's per-test temporary directory.
        assets: The manifest's ``assets`` value, written as-is.

    """
    root = tmp_path / "registry"
    root.mkdir()
    write_asset(root, PROMPT_KEY, PROMPT_TEXT)
    write_manifest(root, assets)

    result = failure(root)

    assert result.reason.code in REGISTRY_REASON_CODES
    assert result.reason.code == CODE_ASSET_INVALID


def test_each_declaration_case_is_rejected_by_its_own_check(
    tmp_path: pathlib.Path,
) -> None:
    """The cases above fail *because of their declaration*, not their wrapper.

    Asserted from the opposite direction: a control registry with a valid
    declaration must load, and a malformed declaration must produce a message only
    its own check can produce. Without this, a suite whose every case failed on a
    doubly-wrapped document would still be green - which is exactly what happened
    before the harness caught it.
    """
    control = tmp_path / "control"
    control.mkdir()
    write_asset(control, PROMPT_KEY, PROMPT_TEXT)
    write_manifest(control, [{"key": PROMPT_KEY}])

    assert load_registry(control).value is not None, (
        "the control must load, otherwise every case below fails for the wrong reason"
    )

    cases = {
        "duplicate-key": (
            [{"key": PROMPT_KEY}, {"key": PROMPT_KEY}],
            "declared twice",
        ),
        "unsupported-format": (
            [{"key": PROMPT_KEY, "format": "yaml"}],
            "unsupported format",
        ),
        "absolute-key": ([{"key": "/etc/passwd"}], "root-relative"),
        "parent-traversal": ([{"key": "../outside.txt"}], "leave the registry root"),
        "parent-traversal-not-first-segment": (
            [{"key": "prompts/../../../etc/passwd"}],
            "leave the registry root",
        ),
        "hidden-key": ([{"key": ".hidden"}], "root-relative"),
        # The default format is text, so an unnamed required key lands on the
        # JSON check first - which is correct precedence (you cannot ask for
        # required keys of an asset that has no structure) and is asserted here as
        # such rather than worked around.
        "required-key-on-a-non-json-asset": (
            [{"key": PROMPT_KEY, "required_keys": [""]}],
            "not JSON",
        ),
        "required-key-without-a-name": (
            [
                {
                    "key": SCHEMA_KEY,
                    "format": ASSET_FORMAT_JSON,
                    "required_keys": [""],
                }
            ],
            "not names",
        ),
        "required-keys-on-a-non-json-asset": (
            [{"key": PROMPT_KEY, "format": ASSET_FORMAT_TEXT, "required_keys": ["a"]}],
            "not JSON",
        ),
    }

    for name, (assets, expected_text) in cases.items():
        root = tmp_path / name
        root.mkdir()
        write_asset(root, PROMPT_KEY, PROMPT_TEXT)
        write_asset(root, SCHEMA_KEY, SCHEMA_BODY)
        write_manifest(root, assets)

        result = failure(root)

        assert result.reason.code == CODE_ASSET_INVALID, name
        assert expected_text in result.reason.message, (
            f"{name} was rejected by something other than its own check"
        )


def test_an_undeclared_asset_is_refused_rather_than_ignored(
    tmp_path: pathlib.Path,
) -> None:
    """An asset outside the manifest does not count toward the hash.

    An asset whose change cannot invalidate anything is the same silent failure
    one layer down (`sad.md` §5.1), so it is refused rather than skipped.
    """
    root = tmp_path / "registry"
    root.mkdir()
    write_asset(root, PROMPT_KEY, PROMPT_TEXT)
    write_asset(root, "prompts/undeclared.txt", "not in the manifest\n")
    write_manifest(root, [{"key": PROMPT_KEY}])

    result = failure(root)

    assert result.reason.code == CODE_ASSET_INVALID
    assert result.evidence.observed["asset_key"] == "prompts/undeclared.txt"


def test_hidden_and_manifest_files_are_not_undeclared_assets(
    tmp_path: pathlib.Path,
) -> None:
    """Editor, OS and VCS debris is not an asset, and the manifest is itself."""
    root = tmp_path / "registry"
    root.mkdir()
    write_asset(root, PROMPT_KEY, PROMPT_TEXT)
    write_manifest(root, [{"key": PROMPT_KEY}])
    write_asset(root, ".DS_Store", b"\x00\x01")
    (root / "prompts" / ".one.txt.swp").write_bytes(b"swap")

    assert sorted(loaded(root).assets) == [PROMPT_KEY]


def test_a_manifest_that_is_not_an_object_stops_the_run(
    tmp_path: pathlib.Path,
) -> None:
    """The manifest itself must be an object with an ``assets`` list.

    Distinct from a manifest that does not *parse*: this one is valid JSON of the
    wrong shape, so it reaches the structural check rather than the decoder.
    """
    for index, body in enumerate(
        ("[]", '"a string"', "42", "null", "{}", '{"assets": {}}')
    ):
        root = tmp_path / f"case-{index}"
        root.mkdir()
        write_manifest(root, body)

        result = failure(root)

        assert result.reason.code == CODE_ASSET_INVALID, body
        assert "assets" in result.reason.message, body


def test_an_undeclared_file_scan_tolerates_a_root_that_is_not_a_directory(
    tmp_path: pathlib.Path,
) -> None:
    """The scanner answers an empty list for a non-directory rather than raising.

    Reached when the manifest check and the asset loads have passed, so it is
    exercised by calling the scanner directly: through ``load_registry`` any root
    that is not a directory fails earlier, on the manifest, and this guard would
    never run.
    """
    as_file = tmp_path / "a-file"
    as_file.write_text("not a directory\n", encoding="utf-8")

    assert registry_module._undeclared_files(as_file, set()) == []
    assert registry_module._undeclared_files(tmp_path / "absent", set()) == []


def test_a_registry_root_that_is_not_a_directory_fails_on_the_manifest(
    tmp_path: pathlib.Path,
) -> None:
    """A path that is not a directory has no manifest, so it fails as missing.

    The undeclared-file scan has to tolerate a non-directory root rather than
    raising, because the manifest check runs first and is the check that reports
    the problem. This asserts the *reason* a caller sees, which is the manifest
    and not a filesystem error escaping the loader.
    """
    missing = tmp_path / "no-such-root"
    as_file = tmp_path / "a-file"
    as_file.write_text("not a registry\n", encoding="utf-8")

    assert failure(missing).reason.code == CODE_ASSET_MISSING
    assert failure(as_file).reason.code == CODE_ASSET_MISSING
    assert failure(missing).evidence.observed["asset_key"] == MANIFEST_NAME


def test_no_default_asset_or_fallback_exists_in_the_load_path() -> None:
    """There is no default asset, no fallback asset and no empty substitution.

    A static guard rather than a behavioural one: the failure this prevents is a
    code path that only runs when something is missing, which a happy-path test
    cannot reach.
    """
    source = REGISTRY_SOURCE

    for forbidden in ("default_asset", "fallback", "DEFAULT_ASSET"):
        assert forbidden not in source, f"the load path must not mention {forbidden!r}"

    # The only asset construction is from bytes that were read, so an asset cannot
    # be fabricated for a missing file.
    constructions = [
        node
        for node in ast.walk(REGISTRY_TREE)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "RegistryAsset"
    ]
    assert len(constructions) == 1, "assets are built in exactly one place"
    keywords = {keyword.arg for keyword in constructions[0].keywords}
    assert "content" in keywords, "the asset's content must come from an argument"
    assert "sha256" in keywords, "the asset's hash must be computed, not defaulted"


def test_the_asset_reader_is_the_only_place_a_file_is_read() -> None:
    """One reader on the load path, so no second path can skip the checks.

    ``_load_asset`` reads the bytes and validates them in the same function; a
    second reader elsewhere would be a path whose contents are never checked.
    """
    readers = [
        node
        for node in ast.walk(REGISTRY_TREE)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "read_bytes"
    ]

    assert len(readers) == 2, (
        "asset bytes are read once for loading and once for the manifest's term"
    )


# --- E03-01: the hash --------------------------------------------------------


def test_the_hash_is_stable_across_two_independent_loads(
    registry_root: pathlib.Path,
) -> None:
    """The same content yields the same hash, however many times it is loaded."""
    first = registry_hash(loaded(registry_root))
    second = registry_hash(loaded(registry_root))

    assert first == second
    assert len(first) == 64
    assert all(character in "0123456789abcdef" for character in first)


def test_changing_one_prompt_changes_the_hash(registry_root: pathlib.Path) -> None:
    """The acceptance criterion of `E03-01`, and the reason the hash exists.

    A prompt edit must show up as a hash change, because the hash is a cache-key
    term: that is what makes a stale ``done`` claim *visible* instead of quietly
    wrong (`sad.md` §5.1).
    """
    before = registry_hash(loaded(registry_root))

    write_asset(registry_root, PROMPT_KEY, "extract the total, and the date\n")
    after = registry_hash(loaded(registry_root))

    assert before != after, "a prompt edit must change the registry hash"


def test_the_hash_does_not_depend_on_the_root_path(tmp_path: pathlib.Path) -> None:
    """Two checkouts of the same content hash the same, wherever they live.

    One directory has the *longer* name on purpose: a hash over paths would still
    differ under a simple truncation, so the lengths must differ for the test to
    be about content rather than about a prefix collision.
    """
    declared = [
        {"key": PROMPT_KEY, "format": ASSET_FORMAT_TEXT},
        {"key": SCHEMA_KEY, "format": ASSET_FORMAT_JSON},
    ]
    roots = [tmp_path / "a", tmp_path / "a-considerably-longer-directory-name"]
    for root in roots:
        root.mkdir()
        write_asset(root, PROMPT_KEY, PROMPT_TEXT)
        write_asset(root, SCHEMA_KEY, SCHEMA_BODY)
        write_manifest(root, declared)

    hashes = [registry_hash(loaded(root)) for root in roots]

    assert len(set(hashes)) == 1, "the hash must not depend on where the root lives"


def test_the_hash_does_not_depend_on_modification_times(
    tmp_path: pathlib.Path,
) -> None:
    """Touching an asset without changing it is not a registry change."""
    declared = [{"key": PROMPT_KEY, "format": ASSET_FORMAT_TEXT}]
    root = tmp_path / "registry"
    root.mkdir()
    asset_path = write_asset(root, PROMPT_KEY, PROMPT_TEXT)
    write_manifest(root, declared)

    before = registry_hash(loaded(root))
    asset_path.touch()
    after = registry_hash(loaded(root))

    assert before == after


def test_the_hash_does_not_depend_on_file_system_order(
    tmp_path: pathlib.Path,
) -> None:
    """Declaring the same assets in a different order is the same registry.

    The encoding is ordered by asset key, so the manifest's own ordering cannot
    change the identity - otherwise reordering a manifest would invalidate a
    corpus.
    """
    forward = tmp_path / "forward"
    reverse = tmp_path / "reverse"
    assets = [(PROMPT_KEY, PROMPT_TEXT), (SCHEMA_KEY, SCHEMA_BODY)]

    for root, order in ((forward, assets), (reverse, list(reversed(assets)))):
        root.mkdir()
        for key, content in assets:
            write_asset(root, key, content)
        write_manifest(root, [{"key": key} for key, _ in order])

    assert registry_hash(loaded(forward)) == registry_hash(loaded(reverse))


def test_registry_hash_orders_by_key_whatever_order_the_mapping_has() -> None:
    """``registry_hash`` sorts for itself, however the ``Registry`` was built.

    This is the test that isolates the hash's own ordering from ``load_registry``'s.
    ``load_registry`` happens to build its mapping already sorted, so a mutation
    that removes the ``sorted()`` inside ``registry_hash`` is invisible through the
    loader: the two orderings are the same one. Constructing the ``Registry``
    directly with a deliberately unsorted mapping is what makes the hash's own
    guarantee observable - and therefore falsifiable.

    The guarantee matters beyond the loader: ``Registry`` is a public type, so a
    caller can build one, and a hash whose identity depended on that caller's
    insertion order would be a hash nobody could reproduce.
    """
    assets = {
        key: registry_module.RegistryAsset(
            key=key,
            content=PROMPT_TEXT.encode(),
            sha256=hashlib.sha256(PROMPT_TEXT.encode()).hexdigest(),
            format=ASSET_FORMAT_TEXT,
        )
        for key in ("zzz/last.txt", "aaa/first.txt", "mmm/middle.txt")
    }

    unsorted = Registry(assets=MappingProxyType(dict(assets)))
    sorted_registry = Registry(
        assets=MappingProxyType({key: assets[key] for key in sorted(assets)})
    )

    # The premise: the two mappings really do iterate differently.
    assert list(unsorted.assets) != list(sorted_registry.assets)
    assert registry_hash(unsorted) == registry_hash(sorted_registry)


def test_the_hash_does_not_depend_on_the_manifest_bytes(
    tmp_path: pathlib.Path,
) -> None:
    """A manifest reformatted without a semantic change is the same registry.

    The manifest *declares* the asset set; it is not itself registry content, so
    its whitespace cannot be part of the identity.
    """
    root = tmp_path / "registry"
    root.mkdir()
    write_asset(root, PROMPT_KEY, PROMPT_TEXT)
    write_manifest(root, [{"key": PROMPT_KEY}])
    before = registry_hash(loaded(root))

    (root / MANIFEST_NAME).write_text(
        json.dumps({"assets": [{"key": PROMPT_KEY}]}, indent=4), encoding="utf-8"
    )
    after = registry_hash(loaded(root))

    assert before == after
    assert load_registry(root).evidence.terms["manifest_sha256"] != "", (
        "the manifest is still observed as evidence, even though it is not content"
    )


def test_the_hash_matches_the_documented_reference_encoding(
    registry_root: pathlib.Path,
) -> None:
    """The encoding is pinned piece by piece, not merely asserted to be stable.

    An earlier version of this suite asserted that two asset keys of adjacent
    lengths could not collide, which is **not falsifiable**: both assets' hashes
    are 64 characters, so the concatenation never shifts whatever the prefixes do
    - the test passed with the length prefixes removed. This one compares against
    an independently written reference, so any change to the encoding shows up as
    a mismatch.
    """
    loaded_registry = loaded(registry_root)

    reference = hashlib.sha256()
    for key in sorted(loaded_registry.assets):
        for piece in (key, loaded_registry.assets[key].sha256):
            encoded = piece.encode("utf-8")
            reference.update(str(len(encoded)).encode("ascii"))
            reference.update(b":")
            reference.update(encoded)

    assert registry_hash(loaded_registry) == reference.hexdigest()


def test_the_hash_covers_the_asset_keys_as_well_as_their_content(
    tmp_path: pathlib.Path,
) -> None:
    """The same bytes under a different asset key is a different registry.

    An implementation that hashed only the assets' content hashes would give
    these two the same identity, and the identity is what the cache key consumes.
    The comparison is one asset against one asset holding identical bytes, so the
    *key* is the only difference between them.

    Note the trap this avoids: two registries holding the same two assets written
    in a different order are the *same* registry, because the encoding sorts by
    key. That is asserted separately by
    :func:`test_the_hash_does_not_depend_on_file_system_order`.
    """
    same_bytes = b"identical content\n"
    left = tmp_path / "left"
    right = tmp_path / "right"
    for root, key in ((left, "a"), (right, "b")):
        root.mkdir()
        write_asset(root, key, same_bytes)
        write_manifest(root, [{"key": key}])

    left_registry = loaded(left)
    right_registry = loaded(right)

    assert left_registry.assets["a"].sha256 == right_registry.assets["b"].sha256
    assert registry_hash(left_registry) != registry_hash(right_registry)


def test_a_removed_asset_changes_the_hash(tmp_path: pathlib.Path) -> None:
    """Removing an asset from the declared set is a registry change too."""
    root = tmp_path / "registry"
    root.mkdir()
    write_asset(root, PROMPT_KEY, PROMPT_TEXT)
    write_asset(root, SCHEMA_KEY, SCHEMA_BODY)
    write_manifest(root, [{"key": PROMPT_KEY}, {"key": SCHEMA_KEY}])
    before = registry_hash(loaded(root))

    # Both the declaration and the file go: undeclaring it alone would leave an
    # undeclared asset behind, which is a different failure (`asset_invalid`).
    write_manifest(root, [{"key": PROMPT_KEY}])
    (root / SCHEMA_KEY).unlink()
    after = registry_hash(loaded(root))

    assert before != after


def test_the_registry_does_not_carry_its_root(registry_root: pathlib.Path) -> None:
    """A stored root would make a path-dependent hash writable by accident.

    The hash must be a function of content, so the type deliberately omits the one
    field that could put a path into it.
    """
    loaded_registry = loaded(registry_root)

    fields = {field.name for field in loaded_registry.__dataclass_fields__.values()}  # type: ignore[attr-defined]

    assert fields == {"assets"}
    assert "root" not in fields
    assert str(registry_root) not in repr(loaded_registry)


def test_supported_formats_are_declared_and_closed() -> None:
    """The format vocabulary is a closed pair, restated rather than imported."""
    assert set(SUPPORTED_ASSET_FORMATS) == {ASSET_FORMAT_JSON, ASSET_FORMAT_TEXT}
    assert MANIFEST_NAME == "manifest.json"
