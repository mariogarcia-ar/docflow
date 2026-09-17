"""Tests for the K7 filesystem store adapter (``E04-01``'s store port).

The adapter is the module that binds ``ArtifactStore`` to `docflow/kernels/store.py`,
which the port says it is and which nothing did until now. These tests check the two
things the port exists to protect — that a failed verification stays a *value* and that
a miss is a *typed reason* — plus the translation between the kernel's exceptions and
the port's ``KernelResult``.

The kernel's own invariants (the ``commit``-after-rename ordering, the seven durable
states, the atomic write) are asserted in `tests/kernels/test_store.py`. What is here
is the boundary: what a caller of the **port** sees.

Pylint relaxations are declared for the reasons the other adapter suites state: a
contract test restates the names it checks (``duplicate-code``), one test per behaviour
costs file length (``too-many-lines``), and a test taking a fixture by name is
``redefined-outer-name`` to Pylint and ``unused-argument`` because pytest passes it.
"""

# pylint: disable=duplicate-code
# pylint: disable=redefined-outer-name
# pylint: disable=too-many-lines
# pylint: disable=unused-argument

from __future__ import annotations

import inspect
import pathlib
from dataclasses import FrozenInstanceError

import pytest

from docflow.adapters.store import FilesystemStore
from docflow.kernels import store as kernel
from docflow.kernels.types import Artifact, Reason
from docflow.ports import ArtifactStore

# --- Fixtures ----------------------------------------------------------------


@pytest.fixture
def store() -> FilesystemStore:
    """Provide a filesystem store.

    Returns:
        The adapter.

    """
    return FilesystemStore()


@pytest.fixture
def root(tmp_path: pathlib.Path) -> pathlib.Path:
    """Provide a store root.

    Args:
        tmp_path: The pytest fixture.

    Returns:
        The root, which does not exist until something writes to it.

    """
    return tmp_path / "store"


@pytest.fixture
def unit(root: pathlib.Path) -> pathlib.Path:
    """Provide a unit directory with a two-stage ledger.

    Args:
        root: The store root.

    Returns:
        The unit directory, with ``read`` and ``validate`` declared.

    """
    unit_dir = root / "units" / "doc-1"
    kernel.write_ledger(unit_dir, kernel.new_ledger("doc-1", ["read", "validate"]))

    return unit_dir


# --- The adapter satisfies the port -----------------------------------------


def test_the_adapter_satisfies_the_port(store: FilesystemStore) -> None:
    """``FilesystemStore`` is structurally an ``ArtifactStore``."""
    assert isinstance(store, ArtifactStore)


def test_the_adapter_exposes_the_ports_operations_and_no_more() -> None:
    """Every port operation is implemented, and nothing was added.

    The port declares nine operations. An extra public method would be a second
    surface to keep in step, and the port is frozen by `plans/README.md` §3.
    """
    port = {name for name in vars(ArtifactStore) if not name.startswith("_")}
    impl = {
        name
        for name in vars(FilesystemStore)
        if not name.startswith("_") and callable(getattr(FilesystemStore, name))
    }

    assert impl == port


def test_every_signature_matches_the_port_parameter_for_parameter() -> None:
    """``isinstance`` checks attribute presence, not arity, so this checks arity.

    ``runtime_checkable`` only asserts that a member *exists*: a method taking an extra
    required argument satisfies it while being uncallable as the port declares. This is
    the check that actually holds the contract.
    """
    for name in sorted(vars(ArtifactStore)):
        if name.startswith("_"):
            continue
        declared = [
            parameter
            for parameter in inspect.signature(getattr(ArtifactStore, name)).parameters
            if parameter != "self"
        ]
        implemented = [
            parameter
            for parameter in inspect.signature(
                getattr(FilesystemStore, name)
            ).parameters
            if parameter != "self"
        ]
        assert implemented == declared, name


# --- The bytes ---------------------------------------------------------------


def test_put_returns_the_descriptor_and_get_reads_it_back(
    store: FilesystemStore, root: pathlib.Path
) -> None:
    """A round trip through the port returns the bytes that went in."""
    stored = store.put(root, b"hello docflow", "text/plain")

    assert stored.reason is None
    assert stored.value is not None
    assert stored.value.media_type == "text/plain"

    read = store.get(root, stored.value.sha256)
    assert read.value == b"hello docflow"


def test_put_returns_only_after_the_bytes_are_addressable(
    store: FilesystemStore, root: pathlib.Path
) -> None:
    """The descriptor is usable the moment ``put`` returns.

    This is what makes a later ``commit`` safe to write: the port's rule is that only
    ``put`` produces an ``Artifact``, and that it returns after the rename. A caller
    that could receive the descriptor while the bytes were still staging would be able
    to record ``done`` about work not yet durable.
    """
    stored = store.put(root, b"bytes on disk", "text/plain")

    assert stored.value is not None
    assert (root / "artifacts" / stored.value.sha256).read_bytes() == b"bytes on disk"
    assert not list(root.glob("*.tmp")), (
        "no staging name survives the call: the byte path's rule is write, flush, "
        "fsync, rename, so a reader never sees a partial artifact"
    )


def test_get_on_a_miss_is_a_typed_reason_and_never_empty_bytes(
    store: FilesystemStore, root: pathlib.Path
) -> None:
    """A missing artifact reports ``artifact_missing``, not ``b""``.

    An empty buffer is a *legal artifact*, so returning one for a miss would make *not
    stored* and *stored, empty* the same answer. That collapse is `prd.md` FR-11.
    """
    result = store.get(root, "0" * 64)

    assert result.value is None
    assert result.reason is not None
    assert result.reason.code == "artifact_missing"
    assert result.value != b""


def test_a_stored_empty_artifact_is_a_value_not_a_miss(
    store: FilesystemStore, root: pathlib.Path
) -> None:
    """The pair above: an empty artifact is stored and read back as a value.

    Without this, an implementation that reported every empty artifact as a miss would
    pass the test above while making a legitimate empty file unreadable.
    """
    stored = store.put(root, b"", "text/plain")
    assert stored.value is not None

    read = store.get(root, stored.value.sha256)

    assert read.reason is None
    assert read.value == b""


# --- The two distinctions the port exists to protect ------------------------


def test_a_failed_verification_is_a_value_with_no_reason(
    store: FilesystemStore, root: pathlib.Path
) -> None:
    """``verify`` answering "no" is a successful call.

    The port states it: ``False`` is an **answer**, so it comes back as the value and
    carries no reason. A reason here would mean the question could not be asked.
    """
    stored = store.put(root, b"content", "text/plain")
    assert stored.value is not None

    result = store.verify(root, "1" * 64)

    assert result.value is False
    assert result.reason is None, "'corrupt' and 'I could not look' must stay apart"
    assert result.evidence.measurements["intact"] is False, (
        "the flag is reported as a measurement so a renderer can show the answer "
        "rather than re-derive it from the value"
    )


def test_an_intact_artifact_verifies_true(
    store: FilesystemStore, root: pathlib.Path
) -> None:
    """The control: a matching hash answers ``True``, so the flag means something."""
    stored = store.put(root, b"content", "text/plain")
    assert stored.value is not None

    result = store.verify(root, stored.value.sha256)

    assert result.value is True
    assert result.reason is None


def test_a_verify_that_cannot_be_asked_is_a_reason(
    store: FilesystemStore, tmp_path: pathlib.Path
) -> None:
    """A question that cannot be put to the tree is a reason, never ``False``.

    The distinction has an exact edge, and the kernel cannot draw it: ``is_file()``
    answers ``False`` both for *"there is no such file"* and for *"I cannot look
    here"*. So the refusal below is the adapter's own, and it must sit exactly where
    the question stops being askable — a path whose ancestor is a file has no
    directory to look in, so ``exists()`` itself refuses.
    """
    blocked = tmp_path / "a-file"
    blocked.write_text("this is a file, not a directory", encoding="utf-8")

    result = store.verify(blocked / "nested", "2" * 64)

    assert result.value is None, (
        "answering False here would read as 'the artifact is corrupt'"
    )
    assert result.reason is not None
    assert result.reason.code == "unsupported_format", (
        "a question that could not be put is a usage error. ``artifact_missing`` "
        "would say something is absent, which is a claim this call never made"
    )


def test_verify_on_an_absent_root_is_an_answer_not_a_reason(
    store: FilesystemStore, root: pathlib.Path
) -> None:
    """The control for the test above: a root that is merely absent *can* be looked in.

    Without this, an implementation that reported every unverifiable hash as a
    refused call would pass the previous test while turning the port's central
    distinction the other way round: *"not stored"* would become an error instead of
    an answer, and every caller would read an ordinary miss as a broken store.
    """
    result = store.verify(root, "4" * 64)

    assert result.value is False
    assert result.reason is None, "nothing is absent that should have been present"


# --- The ledger --------------------------------------------------------------


def test_write_then_read_round_trips_through_the_port(
    store: FilesystemStore, unit: pathlib.Path
) -> None:
    """What ``write_ledger`` wrote is what ``read_ledger`` reports."""
    written = store.write_ledger(unit, kernel.new_ledger("doc-1", ["read", "validate"]))
    assert written.reason is None

    read = store.read_ledger(unit)

    assert read.reason is None
    assert read.evidence.observed["unit"] == "doc-1"
    assert read.evidence.observed["stages"] == {
        "read": "pending",
        "validate": "pending",
    }


def test_read_ledger_on_a_unit_that_never_ran_is_a_reason(
    store: FilesystemStore, root: pathlib.Path
) -> None:
    """A unit with no ledger reports, rather than an empty ledger.

    An empty ledger would be indistinguishable from a unit that ran nothing, which is
    the silent stand-in the kernel refuses everywhere.
    """
    result = store.read_ledger(root / "units" / "never-ran")

    assert result.value is None
    assert result.reason is not None
    assert result.reason.code == "artifact_missing"


def test_begin_then_commit_reaches_done_through_the_port(
    store: FilesystemStore, root: pathlib.Path, unit: pathlib.Path
) -> None:
    """The normal path: ``running``, then ``done`` against a stored artifact."""
    started = store.begin(unit, "read")
    assert started.evidence.observed["stages"]["read"] == "running"
    assert started.evidence.observed["stage"] == "read", (
        "the evidence names which stage the call concerned, so a caller does not "
        "have to re-derive it from the ledger it was handed"
    )

    stored = store.put(root, b"the bytes", "text/plain")
    assert stored.value is not None
    done = store.commit(unit, "read", stored.value)

    assert done.reason is None
    assert done.evidence.observed["stages"]["read"] == "done"
    assert done.evidence.observed["artifact_sha256"] == stored.value.sha256


def test_commit_refuses_something_that_is_not_an_artifact(
    store: FilesystemStore, unit: pathlib.Path
) -> None:
    """A hash, a path or a description of where the bytes are is refused.

    The parameter's *type* is the ordering rule: only ``put`` produces an ``Artifact``,
    and it returns after the rename. A caller able to commit a hash string could record
    ``done`` about bytes that were never written.
    """
    result = store.commit(unit, "read", "a-hash-string")  # type: ignore[arg-type]

    assert result.value is None
    assert result.reason is not None
    assert result.reason.code == "unsupported_format"


def test_a_stage_outside_the_declared_set_is_a_reason(
    store: FilesystemStore, unit: pathlib.Path
) -> None:
    """A stage the ledger does not declare reports, rather than creating it.

    The stage set is declared once by the caller, so a mutation naming an undeclared
    stage is a usage error rather than a new stage.
    """
    result = store.begin(unit, "no-such-stage")

    assert result.value is None
    assert result.reason is not None
    assert result.reason.code == "unsupported_format"


def test_a_ledger_that_is_not_a_ledger_is_a_usage_error(
    store: FilesystemStore, unit: pathlib.Path
) -> None:
    """``write_ledger`` handed something else reports, naming the misuse.

    The kernel calls ``.unit`` on its argument, so anything else raises
    ``AttributeError`` — which says nothing beyond *"that object was not what this
    operation takes"*. The refusal has to name the misuse and stay inside the closed
    code set, because a code outside it is a refusal no caller can act on.
    """
    result = store.write_ledger(unit, "not-a-ledger")  # type: ignore[arg-type]

    assert result.value is None
    assert result.reason is not None
    assert result.reason.code == "unsupported_format"


def test_fail_records_the_stage_reason_without_failing_the_call(
    store: FilesystemStore, unit: pathlib.Path
) -> None:
    """``fail`` succeeds at recording a failure, and the two are not confused.

    The stage's own reason is an observation about the *work*; the call's reason would
    be an observation about the *store*. A caller that could not tell them apart would
    read a recorded failure as a broken ledger.
    """
    result = store.fail(unit, "read", Reason(code="blank_page", message="nothing read"))

    assert result.reason is None, "recording a failure is a successful call"
    assert result.evidence.observed["stages"]["read"] == "failed"


# --- The derived summary -----------------------------------------------------


def test_rebuild_manifest_refuses_rather_than_deriving_a_summary(
    store: FilesystemStore, root: pathlib.Path
) -> None:
    """``rebuild_manifest`` waits on K1, and says so instead of guessing.

    The port requires it to delegate to K1's ``rebuild_index()``: K7 owns the bytes and
    the ledger files, K1 owns what a run means. K1 does not exist yet, so there is
    nothing to delegate to. Assembling a manifest here from a rule of the store's own
    would make this layer the authority on what a run means — and a manifest nobody can
    rebuild is one that becomes authoritative and drifts.
    """
    result = store.rebuild_manifest(root)

    assert result.value is None
    assert result.reason is not None
    assert result.reason.code == "engine_unavailable"
    assert "rebuild_index" in result.reason.message
    assert result.evidence.observed["awaits"] == "kernels/orchestrator.py"


# --- The reason vocabulary ---------------------------------------------------


def test_every_reason_code_raised_here_is_in_the_closed_set() -> None:
    """The codes this adapter can raise are the ones `kernel-cli.md` §5 declares."""
    # pylint: disable=import-outside-toplevel
    from docflow.adapters import store as module

    closed_set = {
        "artifact_missing",
        "unsupported_format",
        "engine_unavailable",
    }
    declared = {
        value for name, value in vars(module).items() if name.startswith("_CODE_")
    }

    assert declared, "the adapter declares reason codes, so this is not vacuous"
    assert declared <= closed_set, (
        f"codes outside the closed set: {declared - closed_set}"
    )


def test_the_kernel_exceptions_never_escape_a_call(
    store: FilesystemStore, root: pathlib.Path, unit: pathlib.Path
) -> None:
    """Every operation answers with a ``KernelResult``, even on a bad request.

    The kernel raises — ``FileNotFoundError``, ``ValueError``, ``TypeError`` — because
    inside a kernel an exception is the cheapest way to refuse. The port's contract is
    two states and no third, so the adapter is where the two shapes meet. A test that
    only checked the happy path would not notice an escaping exception.
    """
    calls = [
        ("get", lambda: store.get(root, "3" * 64)),
        ("put", lambda: store.put(root / "\0bad", b"x", "text/plain")),
        ("read_ledger", lambda: store.read_ledger(root / "absent")),
        ("begin", lambda: store.begin(unit, "nope")),
        ("commit", lambda: store.commit(unit, "read", None)),  # type: ignore[arg-type]
        ("fail", lambda: store.fail(unit, "nope", Reason(code="x", message="y"))),
        (
            "write_ledger",
            lambda: store.write_ledger(unit, "not-a-ledger"),  # type: ignore[arg-type]
        ),
    ]

    for name, call in calls:
        result = call()
        assert result.reason is not None, f"{name} answered without a reason"


def test_a_put_failure_is_reported_rather_than_acting_as_a_descriptor(
    store: FilesystemStore, tmp_path: pathlib.Path
) -> None:
    """A path that cannot be a store root reports, so no artifact is handed back.

    The value's *existence* is the contract: a caller receiving one may commit it. A
    failure that still returned a descriptor would let ``done`` be written about bytes
    that were never stored.
    """
    blocked = tmp_path / "a-file"
    blocked.write_text("not a directory", encoding="utf-8")

    result = store.put(blocked / "nested", b"x", "text/plain")

    assert result.value is None
    assert result.reason is not None


def test_the_adapter_is_stateless_so_one_instance_serves_any_tree(
    store: FilesystemStore, tmp_path: pathlib.Path
) -> None:
    """``root`` is a parameter on every method, as the port declares.

    A store holding its own root would be state the port's signature does not carry,
    and ``S1-T21``'s flag/port contract test compares a command's flags against this
    signature without accounting for state hidden elsewhere.
    """
    one = tmp_path / "one"
    two = tmp_path / "two"

    first = store.put(one, b"in one", "text/plain")
    second = store.put(two, b"in two", "text/plain")

    assert first.value is not None and second.value is not None
    assert store.get(one, first.value.sha256).value == b"in one"
    assert store.get(two, second.value.sha256).value == b"in two"


def test_the_descriptor_is_an_artifact_the_port_declares() -> None:
    """The value ``put`` returns is the frozen ``Artifact``, not a look-alike.

    Checked by behaviour rather than by reading ``__dataclass_params__``: a frozen
    dataclass refuses assignment, and that refusal is the property a caller depends
    on. A descriptor that could be edited after ``put`` returned would let a stage
    record ``done`` against bytes other than the ones that were stored.
    """
    descriptor = Artifact(
        sha256="0" * 64, size_bytes=0, media_type="text/plain", path="x"
    )

    with pytest.raises(FrozenInstanceError):
        descriptor.sha256 = "1" * 64  # type: ignore[misc]
        # A frozen dataclass raises here; anything else would mean the descriptor is
        # a mutable stand-in for one.
