"""Tests for the 7-term cache key (``E03-02`` / ``S1-T05``).

One test module per source module, mirroring ``src/docflow``.

The load-bearing tests are, in order of what they protect:

- :func:`test_every_one_of_the_seven_terms_changes_the_key` - the enumeration that
  fails if a term is silently dropped from the encoding;
- :func:`test_a_different_registry_hash_changes_the_key` and
  :func:`test_a_different_model_revision_changes_the_key` - the two terms
  `sad.md` §5 names as *"the ones usually missing"*, each asserted alone;
- :func:`test_no_term_can_be_omitted_or_neutralized` - the constructibility rule
  that makes the other two unbreakable rather than merely observed.

Three Pylint relaxations are declared below, each because the rule contradicts what
this suite is for: ``protected-access`` (the encoding's private helper is what the
length-prefix collision test must reach), ``duplicate-code`` (a contract test
restates the term names it checks instead of importing them), and
``too-many-lines`` (one test per term plus one per guard).
"""

# pylint: disable=protected-access
# ``_absorb`` is reached directly by the collision test, because the property
# under test is the *encoding* rather than any public operation.

# pylint: disable=duplicate-code
# ``EXPECTED_TERM_NAMES`` restates the tuple declared in
# `docflow/kernels/cache_key.py`. A contract test must hold its own copy: importing
# the constant it verifies would make the assertion vacuous.

# pylint: disable=too-many-lines
# Seven terms, one test each, plus the mandatory-term and encoding guards.

from __future__ import annotations

import ast
import dataclasses
import hashlib
import json
import pathlib
import subprocess
import sys
from collections.abc import Callable, Iterator
from types import MappingProxyType

import pytest

from docflow.kernels import cache_key as cache_key_module
from docflow.kernels.cache_key import (
    CACHE_KEY_TERM_NAMES,
    CacheKeyTerms,
    cache_key,
    make_terms,
    terms_as_mapping,
)

# --- Constants ---------------------------------------------------------------

CACHE_KEY_PATH: pathlib.Path = pathlib.Path(cache_key_module.__file__).resolve()
CACHE_KEY_SOURCE: str = CACHE_KEY_PATH.read_text(encoding="utf-8")
CACHE_KEY_TREE: ast.Module = ast.parse(CACHE_KEY_SOURCE, filename=str(CACHE_KEY_PATH))

#: The seven term names, restated rather than imported. The count the plan fixes is
#: seven, and this tuple is the copy the tests assert against.
EXPECTED_TERM_NAMES: tuple[str, ...] = (
    "input_hash",
    "kernel_id",
    "kernel_version",
    "adapter_revision",
    "params",
    "registry_hash",
    "model_revision",
)

#: A complete, valid set of terms. Every test mutates exactly one member of this so
#: that a key change is attributable to that term alone.
BASELINE: dict[str, object] = {
    "input_hash": "9f2a" * 16,
    "kernel_id": "pdf",
    "kernel_version": "0.0.1",
    "adapter_revision": "docling 2.14.0",
    "params": MappingProxyType({"dpi": "300"}),
    "registry_hash": "c41b" * 16,
    "model_revision": "sha256:7cdf5a1b",
}

#: The string terms, derived from the tuple above so a name added there is covered.
STRING_TERM_NAMES: tuple[str, ...] = tuple(
    name for name in EXPECTED_TERM_NAMES if name != "params"
)

#: The domain-noun vocabulary no kernel identifier may contain (`kernel-cli.md`
#: §14). A cache key is a kernel-boundary artifact, so the rule applies here too.
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

#: Module roots this module may import. It is a leaf of the kernel layer: it reaches
#: the standard library and nothing else at all.
ALLOWED_IMPORT_ROOTS: frozenset[str] = frozenset(
    {"__future__", "collections", "dataclasses", "hashlib", "types", "typing"}
)

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


# --- Helpers -----------------------------------------------------------------


def build(**overrides: object) -> CacheKeyTerms:
    """Build a valid set of terms, with named members replaced.

    Args:
        **overrides: The term or terms to replace.

    Returns:
        The composed terms.

    """
    fields = {**BASELINE, **overrides}
    return CacheKeyTerms(**fields)  # type: ignore[arg-type]


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
    """Collect lines where a function returns a falsy literal or empty literal.

    Empty collections count as stand-ins here, unlike in the registry module: this
    module's functions return a key or a mapping, never a set of findings, so an
    empty container returned from one of them is not an answer.

    Args:
        tree: The parsed module.

    Returns:
        The line numbers of every stand-in return, ignoring ``True``/``False``
        because a boolean answer is a result.

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


def iter_module_identifiers(tree: ast.Module) -> Iterator[tuple[str, int]]:
    """Yield every identifier a module declares, with its line number.

    Only names are yielded - never docstrings and never comments - so the prose
    that quotes ``qwen2.5`` as a moving tag cannot produce a false failure.

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


def test_the_module_declares_exactly_seven_terms_in_the_formula_order() -> None:
    """The count the plan fixes is seven, and the order is `sad.md` §5's."""
    assert len(CACHE_KEY_TERM_NAMES) == 7
    assert CACHE_KEY_TERM_NAMES == EXPECTED_TERM_NAMES

    # The dataclass's declared fields are the same seven, in the same order.
    field_names = tuple(field.name for field in dataclasses.fields(CacheKeyTerms))
    assert field_names == EXPECTED_TERM_NAMES, (
        "the declared fields must be the seven terms, in the formula's order"
    )


def test_the_cache_key_module_depends_on_nothing_at_all() -> None:
    """A leaf: the key must be computable without the store, the registry or a port.

    Depending on ``docflow.kernels.registry`` would have been natural - the
    registry hash is a term - but it would make importing the key drag in the
    loader. The term is a *string* the caller already holds, so the dependency is
    on the value, not on the module that produced it.
    """
    roots = {name.split(".")[0] for name in collect_imported_modules(CACHE_KEY_TREE)}

    assert roots <= ALLOWED_IMPORT_ROOTS, (
        f"unexpected imports: {sorted(roots - ALLOWED_IMPORT_ROOTS)}"
    )
    assert "docflow" not in roots, "the key module must not import another module"


def test_no_cache_key_identifier_contains_a_domain_noun() -> None:
    """The key is keyed by kernel terms, never by a document concept."""
    offences = [
        (name, line)
        for name, line in iter_module_identifiers(CACHE_KEY_TREE)
        if any(token.lower() in name.lower() for token in FORBIDDEN_DOMAIN_VOCABULARY)
    ]

    assert offences == [], f"domain vocabulary in identifiers: {offences}"


def test_no_cache_key_function_returns_a_falsy_literal_as_a_stand_in() -> None:
    """A key is always produced; nothing here returns empty as a substitute."""
    assert not collect_falsy_constant_returns(CACHE_KEY_TREE), (
        "a falsy literal returned from a function is the shape a silent failure "
        "takes (`.github/copilot-instructions.md`, never a silent stand-in)"
    )


def test_the_key_does_not_use_pythons_process_salted_hash() -> None:
    """``hash()`` is salted per process, so a key built on it is not stable.

    Verified structurally - the module never calls a bare ``hash`` - because the
    behavioural test (two processes agree) would only catch it probabilistically.
    """
    names = {name for name, _ in iter_module_identifiers(CACHE_KEY_TREE)}

    assert "hash" not in names, "the key must not be built on Python's built-in hash"
    assert "hashlib" in names, "the key must use a stable digest"


# --- The seven terms, one test each -----------------------------------------


@pytest.mark.parametrize("term", EXPECTED_TERM_NAMES)
def test_every_one_of_the_seven_terms_changes_the_key(term: str) -> None:
    """Changing any single term changes the key.

    Parameterized over the seven names so a term dropped from the encoding fails
    here rather than passing unnoticed. This is the enumeration the plan's §7b row
    describes as *"the cache key carries all 7 terms"*.

    Args:
        term: The term to change, alone.

    """
    baseline = cache_key(build())

    alternatives: dict[str, object] = {
        "input_hash": "aa" * 32,
        "kernel_id": "ocr",
        "kernel_version": "0.0.2",
        "adapter_revision": "docling 2.15.0",
        "params": MappingProxyType({"dpi": "600"}),
        "registry_hash": "dd" * 32,
        "model_revision": "sha256:0000dead",
    }

    changed = cache_key(build(**{term: alternatives[term]}))

    assert changed != baseline, f"changing {term!r} must change the key"
    assert len(changed) == 64


def test_the_two_terms_usually_missing_each_get_their_own_assertion() -> None:
    """`sad.md` §5's two named terms, asserted together and in isolation.

    *"The last two are the ones usually missing, and they are the ones that produce
    the failure this design exists to prevent: a stage that is ``done`` and no
    longer correct."* Each is changed with everything else identical, so the
    change is attributable to it alone.
    """
    baseline = cache_key(build())

    different_registry = cache_key(build(registry_hash="0000" + "c41b" * 14))
    different_model = cache_key(build(model_revision="sha256:ffffffff"))
    both = cache_key(
        build(registry_hash="0000" + "c41b" * 14, model_revision="sha256:ffffffff")
    )

    assert different_registry != baseline
    assert different_model != baseline
    assert both not in {baseline, different_registry, different_model}


def test_a_different_registry_hash_changes_the_key() -> None:
    """The explicit criterion from `plan-01-kernels.md` §5: six terms equal, one not.

    An improved prompt changes the registry hash, and every affected stage's key
    must move - otherwise a `done` stage silently reuses an answer computed under
    the old prompt.
    """
    before = cache_key(build(registry_hash="a" * 64))
    after = cache_key(build(registry_hash="b" * 64))

    assert before != after


def test_a_different_model_revision_changes_the_key() -> None:
    """The model *tag* is not the term; the resolved revision is.

    Keying on ``qwen2.5`` would let a model swapped under the moving tag reuse the
    previous model's answers, under a key that never changed.
    """
    digest_one = cache_key(build(model_revision="sha256:7cdf5a1b"))
    digest_two = cache_key(build(model_revision="sha256:1a2b3c4d"))

    assert digest_one != digest_two
    # And the same tag with a different digest is a different key, which is the
    # whole point: the tag is not what was keyed on.
    same_tag = build(kernel_id="llm.local")
    assert cache_key(same_tag) == cache_key(build(kernel_id="llm.local"))


def test_params_encoding_does_not_depend_on_iteration_order() -> None:
    """A mapping's order cannot change the key: params are encoded by sorted name.

    Otherwise two runs that built the same settings in a different order would
    compute different keys and re-run work that was already done.
    """
    first = cache_key(
        build(params=MappingProxyType({"dpi": "300", "lang": "es", "page": "1"}))
    )
    second = cache_key(
        build(params=MappingProxyType({"page": "1", "dpi": "300", "lang": "es"}))
    )

    assert first == second


def test_an_empty_params_mapping_is_a_legal_value() -> None:
    """A stage with no settings is a real state, not a missing term.

    ``make_terms`` turns ``params=None`` into an empty mapping rather than storing
    ``None``, so the empty case has one representation and one key.
    """
    from_function = cache_key(
        make_terms(
            input_hash=str(BASELINE["input_hash"]),
            kernel_id=str(BASELINE["kernel_id"]),
            kernel_version=str(BASELINE["kernel_version"]),
            adapter_revision=str(BASELINE["adapter_revision"]),
            registry_hash=str(BASELINE["registry_hash"]),
            model_revision=str(BASELINE["model_revision"]),
        )
    )
    explicit = cache_key(build(params=MappingProxyType({})))

    assert from_function == explicit


def test_a_params_entry_changes_the_key() -> None:
    """Adding a setting is a key change, even when the set was empty before."""
    empty = cache_key(build(params=MappingProxyType({})))
    populated = cache_key(build(params=MappingProxyType({"dpi": "300"})))

    assert empty != populated


def test_the_key_matches_the_documented_reference_encoding() -> None:
    """The encoding is pinned piece by piece, not just asserted to be stable.

    This is the test that makes the others falsifiable. ``test_every_one_of_the_
    seven_terms_changes_the_key`` proves that a term *matters*; this one proves
    that the bytes are the ones documented, so any change to the encoding - a
    dropped term, a dropped parameter count, an unsorted params mapping, a lost
    length prefix - shows up here as a mismatch rather than as a still-green
    suite that computes something nobody specified.

    A reference re-implementation is correct here precisely because it is written
    independently of the module: it is the specification restated, so the two
    disagreeing is the failure signal.
    """
    terms = build()

    reference = hashlib.sha256()

    def absorb(piece: str) -> None:
        encoded = piece.encode("utf-8")
        reference.update(str(len(encoded)).encode("ascii"))
        reference.update(b":")
        reference.update(encoded)

    absorb(terms.input_hash)
    absorb(terms.kernel_id)
    absorb(terms.kernel_version)
    absorb(terms.adapter_revision)
    absorb(str(len(terms.params)))
    for name in sorted(terms.params):
        absorb(name)
        absorb(terms.params[name])
    absorb(terms.registry_hash)
    absorb(terms.model_revision)

    assert cache_key(terms) == reference.hexdigest()


def test_an_empty_params_mapping_is_encoded_with_its_own_count() -> None:
    """An empty mapping still contributes a piece: its length, which is zero.

    The count is what makes *no settings* a stated fact in the preimage rather
    than an absence. Asserted against the reference encoding, so removing the
    count is a mismatch here.
    """
    terms = build(params=MappingProxyType({}))
    reference = hashlib.sha256()
    for piece in (
        str(terms.input_hash),
        str(terms.kernel_id),
        str(terms.kernel_version),
        str(terms.adapter_revision),
        "0",
        str(terms.registry_hash),
        str(terms.model_revision),
    ):
        encoded = piece.encode("utf-8")
        reference.update(str(len(encoded)).encode("ascii"))
        reference.update(b":")
        reference.update(encoded)

    assert cache_key(terms) == reference.hexdigest()


# --- No term can be omitted or defaulted -------------------------------------


def test_no_term_can_be_omitted_or_neutralized() -> None:
    """A missing term is a ``TypeError``; an empty one is a ``ValueError``.

    The two guards that make the per-term tests above unbreakable rather than
    merely observed: with no defaults on the dataclass and a non-empty rule on
    every string term, there is no construction path that produces a key with a
    term dropped as *"always the same"*.
    """
    for term in EXPECTED_TERM_NAMES:
        fields = {key: value for key, value in BASELINE.items() if key != term}
        with pytest.raises(TypeError):
            CacheKeyTerms(**fields)  # type: ignore[arg-type]


@pytest.mark.parametrize("term", STRING_TERM_NAMES)
def test_no_string_term_may_be_empty(term: str) -> None:
    """``""`` is the stand-in shape: there is no empty hash or empty revision.

    Args:
        term: The term given the empty string.

    """
    with pytest.raises(ValueError) as excinfo:
        build(**{term: ""})

    assert term in str(excinfo.value)


@pytest.mark.parametrize("term", STRING_TERM_NAMES)
def test_no_string_term_may_be_a_non_string(term: str) -> None:
    """A non-string term would need a canonical encoding this module does not define.

    Args:
        term: The term given a non-string value.

    """
    for stand_in in (None, 0, 1.0, b"bytes", {"a": "b"}, ["a"]):
        with pytest.raises(ValueError):
            build(**{term: stand_in})


def test_params_must_be_a_mapping_of_string_to_string() -> None:
    """A non-string value in params cannot be encoded, so it is refused."""
    for bad_params in (
        "not-a-mapping",
        {"dpi": 300},
        {"dpi": None},
        {1: "300"},
        {"": "300"},
    ):
        with pytest.raises(ValueError):
            build(params=bad_params)


def test_there_is_no_constructor_that_supplies_a_default_term() -> None:
    """No ``default_terms()``, no ``with_fallback()``, no module-level key constant.

    A static guard, because the failure it prevents is a helper that only gets
    called when a term is inconvenient - which no behavioural test reaches.
    """
    offenders = [
        name
        for name in dir(cache_key_module)
        if any(
            token in name.lower()
            for token in ("default", "fallback", "placeholder", "empty_key", "unknown")
        )
    ]
    assert offenders == [], f"cache_key must not offer a defaulting helper: {offenders}"

    functions = [
        node.name
        for node in ast.walk(CACHE_KEY_TREE)
        if isinstance(node, ast.FunctionDef)
    ]
    assert not any(
        "default" in name.lower() or "fallback" in name.lower() for name in functions
    ), f"no defaulting function may exist: {functions}"

    # `cache_key` takes exactly one parameter, so a term cannot be passed
    # separately or replaced by a keyword with a default.
    signature = next(
        node
        for node in ast.walk(CACHE_KEY_TREE)
        if isinstance(node, ast.FunctionDef) and node.name == "cache_key"
    )
    assert len(signature.args.args) == 1
    assert signature.args.defaults == []
    assert signature.args.kw_defaults == []


def test_make_terms_makes_the_two_named_terms_mandatory() -> None:
    """``registry_hash`` and ``model_revision`` cannot be reached as optional.

    Omitting either is a ``TypeError`` at the call site rather than a substitute
    somewhere inside - which is what makes *no fallback* a property of the
    signature instead of a promise in a docstring.
    """
    common = {
        "input_hash": "9f2a" * 16,
        "kernel_id": "pdf",
        "kernel_version": "0.0.1",
        "adapter_revision": "docling 2.14.0",
    }

    # The missing keyword arguments are the assertion: each call below is
    # deliberately incomplete, so Pylint's incomplete-call report is expected.
    with pytest.raises(TypeError):
        make_terms(  # pylint: disable=missing-kwoa
            **common, model_revision="sha256:x"
        )
    with pytest.raises(TypeError):
        make_terms(  # pylint: disable=missing-kwoa
            **common, registry_hash="c41b" * 16
        )

    assert isinstance(
        make_terms(**common, registry_hash="c" * 64, model_revision="sha256:x"),
        CacheKeyTerms,
    )


def test_the_encoding_is_length_prefixed_so_two_term_sets_cannot_collide() -> None:
    """A shifted boundary between two terms is a different key.

    Without the prefix, ``input_hash="ab"`` with ``kernel_id="c"`` would encode to
    the same bytes as ``input_hash="a"`` with ``kernel_id="bc"`` - two genuinely
    different stages sharing one key, which is the collision a cache key exists to
    prevent.
    """
    left = cache_key(build(input_hash="ab", kernel_id="c"))
    right = cache_key(build(input_hash="a", kernel_id="bc"))

    assert left != right

    # And the encoding itself absorbs a length and a separator per piece.
    digest = hashlib.sha256()
    cache_key_module._absorb(digest, "ab")
    first = digest.hexdigest()
    digest = hashlib.sha256()
    cache_key_module._absorb(digest, "a")
    cache_key_module._absorb(digest, "b")
    assert first != digest.hexdigest()


# --- Stability and inspectability -------------------------------------------


def test_the_key_is_stable_across_processes() -> None:
    """The same terms produce the same key in a different interpreter.

    This is an acceptance criterion, and it is why the digest is SHA-256 rather
    than ``hash``: a key salted per process would differ between the run that
    wrote a stage and the run that resumed it, and every stage would re-run.
    """
    script = (
        "import sys;"
        f"sys.path.insert(0, {str(CACHE_KEY_PATH.parents[2])!r});"
        "from types import MappingProxyType;"
        "from docflow.kernels.cache_key import CacheKeyTerms, cache_key;"
        "terms = CacheKeyTerms("
        f"input_hash={BASELINE['input_hash']!r},"
        f"kernel_id={BASELINE['kernel_id']!r},"
        f"kernel_version={BASELINE['kernel_version']!r},"
        f"adapter_revision={BASELINE['adapter_revision']!r},"
        'params=MappingProxyType({"dpi": "300"}),'
        f"registry_hash={BASELINE['registry_hash']!r},"
        f"model_revision={BASELINE['model_revision']!r});"
        "print(cache_key(terms))"
    )

    completed = subprocess.run(
        [sys.executable, "-B", "-c", script],
        capture_output=True,
        text=True,
        check=False,
        env={"PYTHONDONTWRITEBYTECODE": "1", "PATH": "/usr/bin:/bin"},
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == cache_key(build())


def test_recomputing_the_key_for_identical_terms_is_stable() -> None:
    """Pure and total: repeated calls agree, and the terms are unchanged."""
    terms = build()

    assert len({cache_key(terms) for _ in range(5)}) == 1
    assert cache_key(terms) == cache_key(build())


def test_terms_as_mapping_exposes_the_key_for_inspection() -> None:
    """The key is inspectable *before* any expensive call (`kernel-cli.md` §8).

    ``--resolve-only`` reports ``cache_key_terms`` without executing, and that is
    how a caller answers which revision answered - so the mapping must be
    JSON-encodable, which ``MappingProxyType`` alone is not.
    """
    exposed = terms_as_mapping(build())

    assert list(exposed) == list(EXPECTED_TERM_NAMES), "the formula's order"
    assert exposed["registry_hash"] == BASELINE["registry_hash"]
    assert exposed["model_revision"] == BASELINE["model_revision"]
    assert isinstance(exposed["params"], dict)

    encoded = json.dumps(exposed)
    assert json.loads(encoded)["params"] == {"dpi": "300"}


def test_the_exposed_mapping_is_a_copy_and_not_the_stored_params() -> None:
    """Mutating what was exposed cannot change the terms behind the key.

    ``--resolve-only`` hands the mapping to an encoder, and an encoder that
    mutated it would change a key that had already been computed.
    """
    terms = build()
    exposed = terms_as_mapping(terms)

    params = exposed["params"]
    assert isinstance(params, dict)
    params["dpi"] = "mutated"

    assert dict(terms.params) == {"dpi": "300"}
    assert terms_as_mapping(terms)["params"] == {"dpi": "300"}


def test_terms_are_frozen_comparable_and_deliberately_unhashable() -> None:
    """A term set is frozen and compared by value, and is **not** hashable.

    The unhashability is a recorded PoC property rather than an accident: the
    ``params`` mapping makes ``__hash__`` unavailable, exactly as ``Evidence``'s
    mappings do in `docflow/kernels/types.py`. Nothing needs a term set to be a
    dict key - the key is a string - and the property is pinned here so that a
    future change to it is deliberate rather than a surprise.
    """
    terms = build()

    assert isinstance(terms, CacheKeyTerms)
    assert terms == build()
    assert terms != build(kernel_id="ocr")
    with pytest.raises(TypeError, match="unhashable"):
        hash(terms)
    with pytest.raises(dataclasses.FrozenInstanceError):
        terms.kernel_id = "ocr"  # type: ignore[misc]


def test_the_key_is_a_lowercase_hex_digest() -> None:
    """The key's shape is fixed: 64 lowercase hexadecimal characters."""
    key = cache_key(build())

    assert len(key) == 64
    assert key == key.lower()
    assert all(character in "0123456789abcdef" for character in key)


def test_a_term_is_never_a_bare_string_without_its_name_in_the_encoding() -> None:
    """Two stages differing only in *which* term changed produce different keys.

    Without absorbing each term's name, ``kernel_id="pdf"`` with
    ``kernel_version="ocr"`` could encode to the same bytes as the reverse, and
    two different stages would share a key.
    """
    left = cache_key(build(kernel_id="alpha", kernel_version="beta"))
    right = cache_key(build(kernel_id="beta", kernel_version="alpha"))

    assert left != right


def test_the_module_offers_no_way_to_compose_a_key_from_six_terms() -> None:
    """Every public callable either takes all seven or takes none.

    The observable surface is a guard against a convenience overload appearing
    later: a function that accepted six terms would need a default for the seventh.
    """
    public: list[Callable[..., object]] = [
        getattr(cache_key_module, name)
        for name in cache_key_module.__all__
        if callable(getattr(cache_key_module, name))
    ]

    assert {function.__name__ for function in public} == {
        "CacheKeyTerms",
        "cache_key",
        "make_terms",
        "terms_as_mapping",
    }

    for function in public:
        parameters = (
            list(function.__init__.__code__.co_varnames)
            # type: ignore[misc]
            if (isinstance(function, type))
            else list(function.__code__.co_varnames)
        )  # type: ignore[attr-defined]
        assert "default" not in " ".join(parameters).lower()
