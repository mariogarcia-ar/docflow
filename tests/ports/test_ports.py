"""Tests for the port interfaces (``E04-01`` / ``S1-T11``).

One test per acceptance criterion of `E04-01`, plus the guards that keep each
criterion from being satisfied vacuously.

The load-bearing test here is ``test_no_port_module_imports_an_adapter``: the
whole reuse claim of the project rests on the dependency arrow pointing down
(`ADR-004`), and that claim is structural rather than stylistic. Every other
assertion in this file is a statement about a signature; that one is a statement
about the import graph, and its failure means the arrow has started pointing up.

Every static guard parses the **real** port sources rather than importing them, so
a mutation that breaks a port's import cannot hide a violation behind a module
that no longer collects.

Two Pylint relaxations are declared, each because the rule contradicts what this
suite is for rather than because the code is sloppy: the fakes deliberately share
a shape and restate names rather than importing them (``duplicate-code``), and one
test per acceptance criterion costs file length (``too-many-lines``).
"""

# pylint: disable=duplicate-code
# The five fakes below deliberately share a shape: each is a minimal stand-in
# whose only job is to satisfy one protocol. Extracting a base class would make
# them satisfy *each other's* protocols too, which is the opposite of what the
# suite asserts — that a port can be satisfied by some fake, with no adapter
# imported.

# pylint: disable=too-many-lines
# One test per acceptance criterion of `E04-01`, plus one falsification per
# static guard. Splitting the file to satisfy a line budget would separate an
# invariant from the test that proves it is not vacuous.

from __future__ import annotations

import ast
import importlib
import inspect
import pathlib
import subprocess
import sys
import typing
from collections.abc import Iterator, Mapping, Sequence

from docflow.kernels.store import Ledger
from docflow.kernels.types import (
    Artifact,
    Box,
    Bytes,
    Evidence,
    KernelResult,
    Reason,
    Token,
)
from docflow.ports import (
    PORT_INTERFACE_NAMES,
    PageStatus,
    PdfSource,
    ReadResult,
)
from docflow.ports._typing import imported_package_paths, is_adapter_import

# --- Constants ---------------------------------------------------------------

#: The five protocols, paired with the module each is declared in. The pairing is
#: what catches a protocol drifting into a module the plan did not name.
PORT_DECLARATIONS: tuple[tuple[str, str], ...] = (
    ("PdfSource", "pdf"),
    ("OcrEngine", "ocr"),
    ("LlmEngine", "llm"),
    ("ArtifactStore", "store"),
    ("Registry", "registry"),
)

#: The modules under ``docflow/ports``, excluding ``__init__``. ``_typing.py``
#: holds the static predicate the isolation guard uses: machinery, not a
#: capability. Named explicitly rather than globbed, so a new module has to be
#: declared here by hand — which is the moment someone notices the set changed.
PORT_MODULES: frozenset[str] = frozenset(
    {"pdf.py", "ocr.py", "llm.py", "store.py", "registry.py", "_typing.py"}
)

#: The modules that declare port interfaces, as opposed to the private machinery
#: ``_typing.py`` carries. A scan for *port methods* must use this set: the guard
#: helpers in ``_typing.py`` are ordinary functions whose return types have nothing
#: to do with the boundary contract.
PORT_INTERFACE_MODULES: frozenset[str] = PORT_MODULES - {"_typing.py"}

#: Domain vocabulary no port identifier may contain (`kernel-cli.md` §10, §14).
FORBIDDEN_DOMAIN_VOCABULARY: tuple[str, ...] = (
    "invoice",
    "cuit",
    "document_type",
    "pipeline",
    "validator",
    "extractor",
    "segmenter",
    "identif",
    "golden",
)

#: Words that would betray a *decision* rather than an observation
#: (`kernel-cli.md` §3, guardrail 2). A port reports; it never grades or routes.
FORBIDDEN_DECISION_VOCABULARY: tuple[str, ...] = (
    "score",
    "verdict",
    "route",
    "decision",
    "usable",
    "quality",
    "grade",
)

#: Parameter names a port must never carry: a fallback in any form
#: (`kernel-cli.md` §8, §14), an engine setting (`ADR-001`), or a secret on a
#: signature instead of in the environment (`kernel-cli.md` §9, K6).
FORBIDDEN_PARAMETER_NAMES: frozenset[str] = frozenset(
    {
        "fallback",
        "default_model",
        "default_provider",
        "default_engine",
        "engine",
        "api_key",
        "apikey",
        "secret",
    }
)


def ports_root() -> pathlib.Path:
    """Return the directory the port package lives in.

    Resolved from the imported package rather than from a relative path, so the
    static guards read the real tree the tests are running against.

    Returns:
        The ``docflow/ports`` directory.

    """
    package = importlib.import_module("docflow.ports")
    assert package.__file__ is not None
    return pathlib.Path(package.__file__).resolve().parent


def port_sources() -> Iterator[tuple[str, str]]:
    """Yield ``(module name, source)`` for each module declared under ``ports``.

    Yields:
        Each port module's file name and its text, so a static guard can parse the
        real tree without importing any of it.

    """
    root = ports_root()
    for module_name in sorted(PORT_MODULES):
        path = root / module_name
        yield module_name, path.read_text(encoding="utf-8")


def interface_sources() -> Iterator[tuple[str, str]]:
    """Yield ``(module name, source)`` for the modules that declare interfaces.

    Separate from ``port_sources`` because the guards that scan *port method
    signatures* must not read ``_typing.py``, whose functions are ordinary helpers
    rather than boundary methods.

    Yields:
        Each interface module's file name and its text.

    """
    for module_name, source in port_sources():
        if module_name in PORT_INTERFACE_MODULES:
            yield module_name, source


def get_ports_package() -> typing.Any:
    """Return the imported ``docflow.ports`` package.

    Returns:
        The package module object.

    """
    return importlib.import_module("docflow.ports")


def port_interfaces() -> Iterator[tuple[str, type]]:
    """Yield ``(name, protocol)`` for the five declared protocols.

    Yields:
        Each protocol's name and its class object, resolved from the package so
        that a protocol removed from ``__init__`` fails here rather than passing.

    """
    package = get_ports_package()
    for name, _module_name in PORT_DECLARATIONS:
        yield name, getattr(package, name)


def iter_methods(protocol: type) -> Iterator[tuple[str, typing.Any]]:
    """Yield every public method a protocol declares.

    Args:
        protocol: The protocol class.

    Yields:
        ``(method name, function)`` for each public callable member.

    """
    for name, member in vars(protocol).items():
        if name.startswith("_") or not callable(member):
            continue
        yield name, member


def signature_of(method: typing.Any) -> inspect.Signature:
    """Return a method's resolved signature.

    Args:
        method: The function object.

    Returns:
        Its ``inspect.Signature``.

    """
    return inspect.signature(method)


# --- Criterion 1: exactly five interfaces ------------------------------------


def test_ports_package_declares_exactly_the_five_frozen_interfaces() -> None:
    """``plans/README.md`` §3 freezes five port names, and this package has five.

    ``RasterImage`` is deliberately absent. K3's raster library is the one engine
    in the inventory that is not a vendor service behind a swap-able boundary
    (`sad.md` §1 lists Docling, pdftotext, Ollama, provider SDKs, filesystem), so
    naming a sixth interface for it would put a boundary where the architecture
    did not ask for one; its operations live in ``docflow/kernels/image.py``.
    """
    assert PORT_INTERFACE_NAMES == (
        "PdfSource",
        "OcrEngine",
        "LlmEngine",
        "ArtifactStore",
        "Registry",
    )
    assert len(PORT_INTERFACE_NAMES) == 5
    assert not hasattr(get_ports_package(), "RasterImage")


def test_every_declared_interface_is_a_runtime_checkable_protocol() -> None:
    """A port that is not a ``Protocol`` cannot be satisfied structurally."""
    for name, protocol in port_interfaces():
        assert getattr(protocol, "_is_protocol", False), f"{name} is not a Protocol"
        assert getattr(protocol, "_is_runtime_protocol", False), (
            f"{name} is not runtime_checkable, so a fake cannot be asserted against it"
        )


def test_each_interface_is_declared_in_the_module_the_contract_names() -> None:
    """A protocol is declared where the plan says, not merely somewhere."""
    for name, module_name in PORT_DECLARATIONS:
        protocol = getattr(get_ports_package(), name)

        assert protocol.__module__ == f"docflow.ports.{module_name}", (
            f"{name} is declared in {protocol.__module__}"
        )


def test_the_ports_package_contains_only_the_interface_modules() -> None:
    """No module was introduced under ``docflow/ports`` beyond the declared set.

    ``tests/ports/test_port_isolation.py`` asserts the same directory listing, but
    from a module that imports nothing — it is the copy that still runs when a
    port cannot be imported. This one is kept because it runs in the same session
    as the protocol assertions, so a reader sees the whole contract in one place.
    """
    expected = PORT_MODULES | {"__init__.py"}
    actual = {path.name for path in ports_root().glob("*.py")}

    assert actual <= expected, f"unexpected modules: {sorted(actual - expected)}"
    assert actual >= PORT_MODULES, f"missing modules: {sorted(PORT_MODULES - actual)}"


# --- Criterion 2: no adapter is importable from a port -----------------------


def test_no_port_module_imports_an_adapter() -> None:
    """The dependency arrow points down: ports never import adapters.

    This is the guard ``plan-01-kernels.md`` §7b names as *"Adapter isolation"*,
    whose breaking condition is *"an adapter is imported from a port; the arrow
    stops pointing down"*. It reads every real module's syntax tree, so it holds
    for a module that cannot be imported as well as for one that can.
    """
    for module_name, source in port_sources():
        offenders = [
            path for path in imported_package_paths(source) if is_adapter_import(path)
        ]

        assert not offenders, (
            f"{module_name} imports {offenders!r} from the adapter package; the "
            "dependency arrow must only point down"
        )


def test_no_port_module_imports_anything_outside_the_lower_layers() -> None:
    """A port imports the standard library, its own package, and ``kernels``.

    Anything else — a domain module, a component, a third-party package — is a
    dependency the caller did not agree to, and a second arrow pointing the wrong
    way is as bad as the first.
    """
    allowed_local_prefixes = ("docflow.kernels", "docflow.ports")

    for module_name, source in port_sources():
        for path in imported_package_paths(source):
            if path.lstrip(".").split(".")[0] != "docflow":
                continue

            assert path.startswith(allowed_local_prefixes), (
                f"{module_name} imports {path!r}, which is neither a boundary type "
                "nor a port"
            )


def test_importing_the_ports_package_does_not_pull_in_an_adapter() -> None:
    """The runtime form of the consumer test, in a fresh interpreter.

    Run in a subprocess so the assertion is about a real import graph rather than
    about the one this session has already built up.
    """
    program = (
        "import sys\n"
        "import docflow.ports\n"
        "print(sorted(n for n in sys.modules if n.startswith('docflow.adapters')))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "[]", (
        f"importing docflow.ports loaded an adapter: {completed.stdout.strip()}"
    )


# --- Criterion 3: a fake adapter satisfies each port -------------------------


class FakePdfSource:
    """A minimal stand-in satisfying ``PdfSource``."""

    def probe(self, path: pathlib.Path) -> KernelResult[Evidence]:
        """Raise: this fake exists to be checked against the protocol, not called."""
        raise NotImplementedError

    def classify(self, path: pathlib.Path, page: int) -> KernelResult[Evidence]:
        """Raise: this fake exists to be checked against the protocol, not called."""
        raise NotImplementedError

    def tokens(
        self, path: pathlib.Path, pages: Sequence[int], dpi: int
    ) -> KernelResult[Sequence[Token]]:
        """Raise: this fake exists to be checked against the protocol, not called."""
        raise NotImplementedError

    def render(
        self, path: pathlib.Path, pages: Sequence[int], dpi: int
    ) -> KernelResult[Bytes]:
        """Raise: this fake exists to be checked against the protocol, not called."""
        raise NotImplementedError

    def split(self, path: pathlib.Path, pages: Sequence[int]) -> KernelResult[Bytes]:
        """Raise: this fake exists to be checked against the protocol, not called."""
        raise NotImplementedError


class FakeOcrEngine:
    """A minimal stand-in satisfying ``OcrEngine``."""

    def capabilities(self) -> KernelResult[Evidence]:
        """Raise: this fake exists to be checked against the protocol, not called."""
        raise NotImplementedError

    def engine_info(self) -> KernelResult[Evidence]:
        """Raise: this fake exists to be checked against the protocol, not called."""
        raise NotImplementedError

    def read(
        self, path: pathlib.Path, pages: Sequence[int], dpi: int, lang: str
    ) -> KernelResult[ReadResult]:
        """Raise: this fake exists to be checked against the protocol, not called."""
        raise NotImplementedError


class FakeLlmEngine:
    """A minimal stand-in satisfying ``LlmEngine``."""

    def capabilities(self, model: str) -> KernelResult[Evidence]:
        """Raise: this fake exists to be checked against the protocol, not called."""
        raise NotImplementedError

    def warm(self, model: str) -> KernelResult[Evidence]:
        """Raise: this fake exists to be checked against the protocol, not called."""
        raise NotImplementedError

    def structured(
        self, model: str, prompt: str, schema: Mapping[str, object]
    ) -> KernelResult[Mapping[str, object]]:
        """Raise: this fake exists to be checked against the protocol, not called."""
        raise NotImplementedError

    def vision(
        self,
        model: str,
        prompt: str,
        images: Sequence[Bytes],
        schema: Mapping[str, object],
    ) -> KernelResult[Mapping[str, object]]:
        """Raise: this fake exists to be checked against the protocol, not called."""
        raise NotImplementedError

    def judge(
        self,
        model: str,
        rubric: str,
        samples: Sequence[Mapping[str, object]],
        produced_by: str,
    ) -> KernelResult[Mapping[str, object]]:
        """Raise: this fake exists to be checked against the protocol, not called."""
        raise NotImplementedError


class FakeArtifactStore:
    """A minimal stand-in satisfying ``ArtifactStore``."""

    def put(
        self, root: pathlib.Path, data: bytes, media_type: str
    ) -> KernelResult[Artifact]:
        """Raise: this fake exists to be checked against the protocol, not called."""
        raise NotImplementedError

    def get(self, root: pathlib.Path, sha256: str) -> KernelResult[bytes]:
        """Raise: this fake exists to be checked against the protocol, not called."""
        raise NotImplementedError

    def verify(self, root: pathlib.Path, sha256: str) -> KernelResult[bool]:
        """Raise: this fake exists to be checked against the protocol, not called."""
        raise NotImplementedError

    def begin(
        self, unit_dir: pathlib.Path, stage: str, cache_key: str | None
    ) -> KernelResult[Ledger]:
        """Raise: this fake exists to be checked against the protocol, not called."""
        raise NotImplementedError

    def commit(
        self,
        unit_dir: pathlib.Path,
        stage: str,
        artifact: Artifact,
        cache_key: str,
    ) -> KernelResult[Ledger]:
        """Raise: this fake exists to be checked against the protocol, not called."""
        raise NotImplementedError

    def fail(
        self,
        unit_dir: pathlib.Path,
        stage: str,
        reason: Reason,
        cache_key: str,
    ) -> KernelResult[Ledger]:
        """Raise: this fake exists to be checked against the protocol, not called."""
        raise NotImplementedError

    def read_ledger(self, unit_dir: pathlib.Path) -> KernelResult[Ledger]:
        """Raise: this fake exists to be checked against the protocol, not called."""
        raise NotImplementedError

    def write_ledger(
        self, unit_dir: pathlib.Path, ledger: Ledger
    ) -> KernelResult[Ledger]:
        """Raise: this fake exists to be checked against the protocol, not called."""
        raise NotImplementedError

    def rebuild_manifest(
        self, out_dir: pathlib.Path
    ) -> KernelResult[Mapping[str, object]]:
        """Raise: this fake exists to be checked against the protocol, not called."""
        raise NotImplementedError


class FakeRegistry:
    """A minimal stand-in satisfying ``Registry``."""

    def validate(self, root: pathlib.Path) -> KernelResult[Evidence]:
        """Raise: this fake exists to be checked against the protocol, not called."""
        raise NotImplementedError

    def hash(self, root: pathlib.Path) -> KernelResult[str]:
        """Raise: this fake exists to be checked against the protocol, not called."""
        raise NotImplementedError

    def show(
        self, root: pathlib.Path, asset: str, key: str
    ) -> KernelResult[Mapping[str, object]]:
        """Raise: this fake exists to be checked against the protocol, not called."""
        raise NotImplementedError

    def list(self, root: pathlib.Path, asset: str) -> KernelResult[Sequence[str]]:
        """Raise: this fake exists to be checked against the protocol, not called."""
        raise NotImplementedError


def test_a_fake_satisfies_each_port_without_importing_an_adapter() -> None:
    """Each protocol is satisfiable by a fake local to the tests.

    This is the consumer test of ``plan-01-kernels.md`` §13 Track 3: Plan 2 must
    be able to satisfy a port with a fake in its own tests without importing an
    adapter. If a port demanded a concrete class, the arrow would be pointing the
    wrong way and this assertion is the first thing that would notice.
    """
    fakes: dict[str, object] = {
        "PdfSource": FakePdfSource(),
        "OcrEngine": FakeOcrEngine(),
        "LlmEngine": FakeLlmEngine(),
        "ArtifactStore": FakeArtifactStore(),
        "Registry": FakeRegistry(),
    }
    protocols = dict(port_interfaces())

    assert set(fakes) == set(PORT_INTERFACE_NAMES)

    for name, fake in fakes.items():
        assert isinstance(fake, protocols[name]), (
            f"{type(fake).__name__} does not satisfy {name}"
        )


def test_a_fake_missing_one_method_does_not_satisfy_the_port() -> None:
    """The satisfaction check is not vacuous: an incomplete fake is rejected.

    Without this, a port could lose a method and every fake would still be
    reported as satisfying it — the assertion above would pass while asserting
    nothing about the interface's shape.
    """

    class IncompletePdfSource:  # pylint: disable=too-few-public-methods
        """A stand-in implementing only ``probe``.

        The Pylint exception is site-specific and stated for a reason: one public
        method is not an oversight here, it *is* the test case. The assertion below
        is that a port with a member missing is not satisfied by a stand-in that has
        only some of it, so a two-method class could not express the failure.
        """

        def probe(self, path: pathlib.Path) -> KernelResult[Evidence]:
            """Raise: this fake exists to be checked against the protocol."""
            raise NotImplementedError

    assert not isinstance(IncompletePdfSource(), PdfSource)


# --- Criterion 4: fully type-hinted, no ``Any`` ------------------------------


def test_every_port_method_is_fully_type_hinted() -> None:
    """Every parameter and every return is annotated, with no untyped member.

    An untyped boundary is not a boundary: a caller cannot know what it agreed to,
    and the annotation is what ``S1-T21``'s flag/port contract test compares a
    command's flags against.
    """
    for name, protocol in port_interfaces():
        for method_name, method in iter_methods(protocol):
            signature = signature_of(method)
            for parameter_name, parameter in signature.parameters.items():
                if parameter_name == "self":
                    continue

                assert parameter.annotation is not inspect.Parameter.empty, (
                    f"{name}.{method_name} parameter {parameter_name!r} is untyped"
                )

            assert signature.return_annotation is not inspect.Signature.empty, (
                f"{name}.{method_name} has no return annotation"
            )


def test_no_port_signature_mentions_any() -> None:
    """``Any`` appears nowhere in a port signature.

    Checked over the parsed source rather than over resolved hints, so it holds
    for every annotation form — including one nested inside a generic that
    ``get_type_hints`` would resolve away.
    """
    for module_name, source in interface_sources():
        tree = ast.parse(source, filename=module_name)
        offenders = [
            node.lineno
            for node in ast.walk(tree)
            if (isinstance(node, ast.Name) and node.id == "Any")
            or (isinstance(node, ast.Attribute) and node.attr == "Any")
        ]

        assert not offenders, f"{module_name} mentions Any at lines {offenders}"


def test_every_port_method_returns_a_kernel_result() -> None:
    """A port can express *"no value, and why"*, so every method returns one.

    A method returning a bare ``str`` has no way to say *"I could not produce
    this"* other than by returning an empty string — precisely the silent stand-in
    the boundary exists to make unrepresentable (``sad.md`` §6).

    Only methods declared **directly on a Protocol** are checked. A supporting
    value type such as ``ReadResult`` carries ordinary methods of its own, and a
    derived property like ``pages_read`` returning a tuple is correct rather than a
    violation.
    """
    for module_name, source in interface_sources():
        tree = ast.parse(source, filename=module_name)
        for class_node in tree.body:
            if not isinstance(class_node, ast.ClassDef):
                continue
            if not any(ast.unparse(base) == "Protocol" for base in class_node.bases):
                continue

            for node in class_node.body:
                if not isinstance(node, ast.FunctionDef) or node.name.startswith("_"):
                    continue

                annotation = ast.unparse(node.returns) if node.returns else ""
                assert annotation.startswith("KernelResult["), (
                    f"{module_name}:{class_node.name}.{node.name} returns "
                    f"{annotation!r}, not a KernelResult"
                )


def test_no_port_parameter_carries_a_default_value() -> None:
    """No port member has a default, so no default can be substituted for it.

    ``E04-01``: *"No concrete engine, model, threshold or default as a port
    member."* A parameter with a default is a default the caller never stated,
    and for a threshold or a model that is a silent fallback in the making.
    """
    for name, protocol in port_interfaces():
        for method_name, method in iter_methods(protocol):
            signature = signature_of(method)
            offenders = [
                parameter_name
                for parameter_name, parameter in signature.parameters.items()
                if parameter.default is not inspect.Parameter.empty
            ]

            assert not offenders, (
                f"{name}.{method_name} carries defaults for {offenders!r}"
            )


# --- Criteria 5 and 6: no domain noun, no decision ---------------------------


def collect_identifiers(source: str) -> list[str]:
    """Collect every identifier a module declares.

    Only names are collected — never docstrings and never comments — so prose in
    this package that legitimately discusses documents cannot produce a false
    failure. This is the same discipline ``tests/kernels/test_types.py`` applies to
    the boundary module.

    Args:
        source: Python source text.

    Returns:
        Each class name, function name, referenced name, attribute name and
        parameter name the source declares.

    """
    tree = ast.parse(source)
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            names.append(node.name)
        elif isinstance(node, ast.Name):
            names.append(node.id)
        elif isinstance(node, ast.Attribute):
            names.append(node.attr)
        elif isinstance(node, ast.arg):
            names.append(node.arg)

    return names


def test_no_port_identifier_contains_a_domain_noun() -> None:
    """No port method, class, parameter or return type names a document concept.

    ``kernel-cli.md`` §10: the presence of a domain noun in a kernel API is the
    signal that the surface has drifted into the domain layer.
    """
    offenders: list[str] = []

    for module_name, source in port_sources():
        for identifier in collect_identifiers(source):
            for forbidden in FORBIDDEN_DOMAIN_VOCABULARY:
                if forbidden.lower() in identifier.lower():
                    offenders.append(f"{module_name}: {identifier!r} ~ {forbidden!r}")

    assert not offenders, f"domain vocabulary in port identifiers: {offenders}"


def test_no_port_identifier_names_a_decision_or_a_grade() -> None:
    """A port reports observations; it never grades, scores or routes.

    ``kernel-cli.md`` §3 guardrail 2 draws the line between an observation and a
    decision; this is that line applied to the port surface. A method named
    ``score`` or a parameter named ``route`` would be a decision the port had
    taken on the caller's behalf.
    """
    offenders: list[str] = []

    for module_name, source in port_sources():
        tree = ast.parse(source, filename=module_name)
        declared: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                declared.append(node.name)
            elif isinstance(node, ast.arg):
                declared.append(node.arg)

        for identifier in declared:
            for forbidden in FORBIDDEN_DECISION_VOCABULARY:
                if forbidden.lower() in identifier.lower():
                    offenders.append(f"{module_name}: {identifier!r} ~ {forbidden!r}")

    assert not offenders, f"decision vocabulary in port identifiers: {offenders}"


def test_the_domain_and_decision_scans_are_not_vacuous() -> None:
    """The scans find identifiers, and they find a *bad* one when one is present.

    A walk that yielded nothing would make both guards above pass trivially, so
    this runs the same walk over a synthetic offender and asserts it is caught. The
    vocabulary lists are asserted non-empty and disjoint for the same reason.
    """
    assert FORBIDDEN_DOMAIN_VOCABULARY
    assert FORBIDDEN_DECISION_VOCABULARY
    assert set(FORBIDDEN_DOMAIN_VOCABULARY).isdisjoint(FORBIDDEN_DECISION_VOCABULARY)

    found: list[str] = []
    for _module_name, source in port_sources():
        found.extend(collect_identifiers(source))
    assert len(found) > 50, "the walk must actually find identifiers"

    synthetic = "def score_document(invoice_id: str) -> None:\n    pass\n"
    caught = [
        identifier
        for identifier in collect_identifiers(synthetic)
        if any(
            forbidden in identifier.lower()
            for forbidden in FORBIDDEN_DOMAIN_VOCABULARY + FORBIDDEN_DECISION_VOCABULARY
        )
    ]
    assert caught == ["score_document", "invoice_id"]


# --- Criterion 7: the arrow points down only ---------------------------------


def test_no_port_method_exposes_a_fallback_or_a_secret() -> None:
    """No port method takes a fallback-shaped parameter, an engine, or a secret.

    Three prohibitions, one check, because they share a shape: a parameter that
    lets a caller route around resolution (``fallback``, ``default_model``), one
    that turns the fixed OCR engine into a setting (``engine``, `ADR-001`), and one
    that puts a credential on a signature instead of in the environment
    (``api_key``, ``kernel-cli.md`` §9, K6).
    """
    for name, protocol in port_interfaces():
        for method_name, method in iter_methods(protocol):
            signature = signature_of(method)
            offenders = sorted(
                parameter_name
                for parameter_name in signature.parameters
                if parameter_name in FORBIDDEN_PARAMETER_NAMES
            )

            assert not offenders, (
                f"{name}.{method_name} takes {offenders!r}, which is a fallback, an "
                "engine setting, or a secret on a signature"
            )


def test_the_forbidden_parameter_list_covers_the_artifact_prohibitions() -> None:
    """The list is the artifact's, not one invented here.

    ``kernel-cli.md`` §8 and §14 forbid ``--fallback`` and ``--default-model``; §9
    (K6) forbids ``--api-key`` and §9 (K4) forbids ``--engine``. A port signature
    is where those flags would have come from, so the prohibition is applied at the
    layer that originates it.
    """
    artifact_mandated = {"fallback", "default_model", "api_key", "engine"}

    assert artifact_mandated <= FORBIDDEN_PARAMETER_NAMES


# --- The supporting OCR types ------------------------------------------------


def test_page_status_distinguishes_read_blank_and_unreadable() -> None:
    """Three statuses, because collapsing them invents text on a blank page.

    *The engine read this page and it held no tokens*, *there was nothing to read*
    and *the engine could not read this page* are three different statements; row 9
    of the silent-failure matrix asserts that a blank page reports ``blank`` rather
    than ``read`` with a token list.
    """
    assert {status.value for status in PageStatus} == {"read", "blank", "unreadable"}
    assert issubclass(PageStatus, str), "the value must serialize as the word itself"


def test_read_result_derives_the_page_accounting_from_the_statuses() -> None:
    """``pages_read`` cannot disagree with what the engine reported.

    Row 11 asserts that ``pages_requested`` and ``pages_read`` differ when a read
    is truncated and that the difference is declared. Deriving the second from the
    per-page statuses is what makes the accounting unable to drift from the
    statuses it is supposed to summarize.
    """
    result = ReadResult(
        pages_requested=(1, 2, 3),
        page_status={1: PageStatus.READ, 2: PageStatus.BLANK},
        tokens=(),
    )

    assert result.pages_read == (1, 2)
    assert result.pages_requested != result.pages_read
    assert "pages_read" not in typing.get_type_hints(ReadResult), (
        "pages_read must stay derived, so it cannot be set to a value that "
        "contradicts page_status"
    )


def test_read_result_carries_no_reading_order() -> None:
    """No order field exists, because imposing one is Stage 2's interpretation.

    A reading order injected at this boundary would be a domain-level decision
    performed by a kernel; ``S2-T07`` is where the Reconstructor makes it.
    """
    field_names = set(typing.get_type_hints(ReadResult))

    assert field_names == {"pages_requested", "page_status", "tokens"}
    assert not any("order" in name or "sort" in name for name in field_names)


def test_the_coordinate_types_are_the_frozen_ones_not_new_ports() -> None:
    """Row 8's coordinate honesty is satisfied through ``Box``, with no new port.

    ``Box`` is the source-coordinate box ``E01-01`` froze, so the crop inverse-map
    requirement needs no second boundary type and no sixth interface.
    """
    assert Box.__module__ == "docflow.kernels.types"
    assert PageStatus.__module__ == "docflow.ports.ocr"
    assert ReadResult.__module__ == "docflow.ports.ocr"


# --- The package exports -----------------------------------------------------


def test_all_is_alphabetically_sorted_and_exports_the_declared_names() -> None:
    """``__all__`` is sorted for the linter; the contract lives in the constant."""
    package = get_ports_package()
    exported: list[str] = list(package.__all__)

    assert exported == sorted(exported), "__all__ must stay alphabetically sorted"
    assert set(exported) == set(PORT_INTERFACE_NAMES) | {"PageStatus", "ReadResult"}
    assert set(PORT_INTERFACE_NAMES).isdisjoint({"PageStatus", "ReadResult"}), (
        "the supporting value types are shapes a port returns, not capabilities a "
        "caller depends on"
    )


def test_every_exported_name_is_defined() -> None:
    """A name in ``__all__`` that does not exist is an import error for a consumer."""
    package = get_ports_package()

    for name in package.__all__:
        assert hasattr(package, name), f"{name} is exported but not defined"
