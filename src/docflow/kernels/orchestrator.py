"""K1 orchestrator core - a stage graph over units, and the manifest it derives.

`E05-01` (`S1-T06`). Five concepts, kept distinct because each answers a different
question:

| Concept | Answers |
|---|---|
| :class:`Stage` | *what* one step is: an operation, its settings, its needs |
| :class:`Graph` | *in what order* the steps may run, resolved once |
| :class:`Unit` | *over what* the graph runs, and its own input |
| the **ledger** | *what happened*, per unit and per stage, written by K7 |
| the **manifest** | *what the ledgers say together*, **derived**, never authoritative |

K1 executes a graph it did not write
------------------------------------

The orchestrator does not interpret a stage. It reads a descriptor, decides what is
ready, hands the stage to an operation **the caller bound**, and records what came
back (`kernel-cli.md` §9: *"K1, which executes graphs it did not write"*). There is
no kernel name, operation name, parameter or field here that is a domain concept,
and there is no import of a kernel or an adapter: the operation table is injected,
which is what lets the same core drive a synthetic three-stage flow in Stage 1 and
a real pipeline graph later without a single change to this file.

**A descriptor that names a pipeline code is refused by its shape**, not by a
vocabulary scan: a stage carries exactly the keys this module declares, and an
unknown key is an error. The domain layer's descriptors arrive at Stage 3 with a
different owner and a different reader.

The manifest is derived, and that is a mechanism rather than a promise
---------------------------------------------------------------------

A manifest that is authoritative drifts, because two writers eventually disagree
and the convenient one wins. So there is exactly one producer:
:func:`rebuild_index` reads the ledger tree and nothing else, and :func:`run` writes
``run.json`` **by calling it**. The two cannot differ, and the byte-identical claim
of `plan-01-kernels.md` §6 step 11 is true by construction rather than by care. K7's
``rebuild_manifest()`` delegates here as well, so both doors return what
``rebuild_index()`` returned (`kernel-cli.md` §9, *one operation, one authority*).

Dispatching is keyed, and a stage that is terminal for its key is not re-run
-------------------------------------------------------------------------

A stage's identity is not its name. It is the seven-term cache key of `sad.md` §5,
and the ledger now records the key each terminal stage ran under (`prd.md` FR-08).
So the question dispatch asks is *"is this stage already terminal **for the key it
would run under now**?"* - never *"has it ever run?"*. The difference is the whole
of idempotency: re-running a `run` skips completed work, while a changed registry
hash or a new upstream artifact makes the same stage new work again.

What this module deliberately does not do
-----------------------------------------

- **No durable-state ordering as an asserted invariant.** ``begin`` is called before
  the work starts, because that is the only honest place to call it - but *proving*
  the ordering survives a kill at the write/rename boundary is `E05-02` (`S1-T07`),
  and the seven-state set is that issue's to fix.
- **No determinism classes.** Whether a missing artifact may be regenerated depends
  on the class of the kernel that produced it; that is `E05-03` (`S1-T08`). This
  module re-runs nothing and regenerates nothing: a terminal stage is left alone.
- **No slots, no barriers, no unit-contained failure.** `E05-04` (`S1-T09`). Dispatch
  here is sequential and in one deterministic order; a unit failing stops nothing
  because nothing is concurrent, and the loop simply moves on.
- **No verification on ledger read.** `E05-05` (`S1-T10`, ADR-006). The read path
  here reports what the ledger records and does not check the bytes, so there is no
  ``--verify``-shaped seam to remove later - the check is added in one place.
- **No forced invalidation.** ``--force`` / ``--stage`` and downstream re-pending are
  `S3-T08` (Plan 3). This module records the key; it does not act on a changed one.
- **No ``--rebuild-index`` flag.** :func:`rebuild_index` is a library call in the
  PoC; the flag stays deferred (`prd.md` §7). `# TODO: [MVP]`.
- **No domain noun.** **Never** (`kernel-cli.md` §10).

PoC stage
---------

The lifecycle stage is **PoC**: close the flow, keep the shortcuts visible. Every
deliberate shortcut below carries a ``# TODO: [MVP]`` or ``# TODO: [RELEASE]``
marker naming what must replace it.

Two recorded decisions, so they are not re-litigated from the code:

- **A stage operation returns an :class:`~docflow.kernels.types.Artifact`.** That is
  not a preference, it is K7's constructibility rule read at the dispatch boundary:
  ``StageRecord`` refuses to construct ``done`` without an artifact hash, so a stage
  whose operation produced no durable bytes cannot be ``done``. The consequence is
  that "what are the durable bytes of this stage" is answered by the caller that
  bound the operation, and K1 never has to guess - which is exactly right, because a
  stage's meaning is not K1's to know.
- **The descriptor loader takes an injected reader.** Parsing YAML is a vendor
  concern with a third-party library behind it, and the kernel layer imports no
  third party (`docflow/kernels/store.py`'s isolation test states the rule for the
  layer). :func:`read_descriptor` therefore takes a
  ``Callable[[Path], Mapping]`` and the composition root supplies the real one.
  ``# TODO: [MVP]``: `E07-02` binds a YAML reader behind a seam, the way K2 and K3
  bind theirs.
"""

# Pylint's line ceiling is exceeded by decision, not by accident: the plan names one
# deliverable path for this module - `docflow/kernels/orchestrator.py` - and `E05-02`,
# `E05-04` and `E05-05` each continue *in this file*, so it is the designated home for
# dispatch, durability, determinism consequence, scheduling and verification. Splitting
# it now would put the five concepts the issue asks to keep distinct into modules whose
# boundary the plan does not define, and would add a sibling module to `E01`'s
# explicitly-named set for no gain a reader can see.
# pylint: disable=too-many-lines

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import Final, Protocol

from docflow.kernels import store
from docflow.kernels.cache_key import cache_key, make_terms
from docflow.kernels.types import Artifact, KernelResult

__all__: list[str] = [
    "CONTROL_NAME",
    "CONTROL_STATES",
    "HOLDING_CONTROLS",
    "MANIFEST_NAME",
    "Control",
    "Descriptor",
    "Graph",
    "KernelTerms",
    "KeyContext",
    "RunReport",
    "Stage",
    "StageCall",
    "StageOperation",
    "Unit",
    "cache_key_for",
    "control_of",
    "descriptor_from_mapping",
    "input_hash_for",
    "is_terminal",
    "read_control",
    "read_descriptor",
    "rebuild_index",
    "run",
    "validate",
    "write_control",
    "write_index",
]

#: The manifest's file name at the run's output root (`prd.md` FR-29). Its *shape and
#: location* are `S3-T07`'s (Plan 3); the mechanism that produces it is this module's
#: (`traceability.md` §7.3 deviation D7).
MANIFEST_NAME: Final[str] = "run.json"

#: How a unit's ledger is discovered under the output root. The suffix is K7's
#: (`prd.md` FR-29); this is the pattern, not a second declaration of the rule, and
#: `test_the_discovery_pattern_agrees_with_the_stores_suffix_rule` holds the two
#: together so they cannot drift.
_LEDGER_GLOB: Final[str] = "**/*.ledger.json"

#: The run's control file, at the output root. It records what an operator has asked
#: of a run, and it is **polled between stages** by :func:`run`.
#:
#: It exists because `FR-02`'s `pause` has to be able to interrupt a run that is
#: already in flight, which means the decision cannot be a parameter passed in at the
#: start. A file is the smallest mechanism that a *separate process* can write and a
#: running orchestrator can read, and it is deliberately the same choice K7 makes for
#: the ledger: the filesystem is the message bus, because it is the one both processes
#: already share.
CONTROL_NAME: Final[str] = "control.json"

#: The control states that hold a run. ``stopped`` is a request the run honours at the
#: same checkpoint ``paused`` uses - the difference between them is the *signal*, not
#: the mechanism: `stop --force` also terminates the process, and this file is what
#: tells a scheduler that had not yet reached a checkpoint that it must not continue.
HOLDING_CONTROLS: Final[frozenset[str]] = frozenset({"paused", "stopped"})

#: The control states an operator may write.
CONTROL_STATES: Final[frozenset[str]] = HOLDING_CONTROLS | {"running"}

#: The run state meaning *every unit is terminal*. The seven durable states describe a
#: **stage**; a run is a third vocabulary, and conflating the two would put a value in
#: ``run.json`` that no ledger may carry.
_RUN_COMPLETE: Final[str] = "complete"

#: The run state meaning at least one unit is unfinished **and** an operator asked the
#: run to hold. Distinct from ``incomplete`` so a report says *paused* rather than
#: *unfinished*, which would be indistinguishable from a crash.
_RUN_HOLDING: Final[str] = "holding"

#: The run state meaning at least one unit is unfinished and nothing asked it to stop.
_RUN_INCOMPLETE: Final[str] = "incomplete"

#: The states that are a *result*, as opposed to a position on the way to one. A
#: terminal stage is not dispatched again **for the key it ran under**. The set is
#: K7's reading of the seven; it is restated here rather than imported because K7
#: does not export it, and the orchestrator needs it for a decision K7 does not take.
_TERMINAL_STATES: Final[frozenset[str]] = frozenset({"done", "failed", "skipped"})

#: The keys a stage entry may carry, and no others. An unknown key is refused, which
#: is how *"a descriptor naming a pipeline code is not a shape this module accepts"*
#: is enforced - structurally, without a vocabulary to keep in step.
_STAGE_KEYS: Final[frozenset[str]] = frozenset(
    {"name", "kernel", "op", "needs", "params"}
)

#: The keys a descriptor may carry, and no others.
_DESCRIPTOR_KEYS: Final[frozenset[str]] = frozenset({"unit", "units", "stages"})


@dataclasses.dataclass(frozen=True, slots=True)
class KernelTerms:
    """The three key terms that describe *which implementation* will answer.

    They are supplied by the caller rather than resolved here, because resolving a
    name to an implementation is a decision about adapters - and K1 knows no adapter
    (`E04-07` / `S1-T17` owns resolution). K1 receives the answer and composes the key.

    Attributes:
        kernel_version: The kernel's own version. A bug fix must invalidate what the
            bug produced, which is why this is separate from the kernel's name.
        adapter_revision: The engine's revision, e.g. a Docling version or an Ollama
            build. The same call on a different engine is a different computation.
        model_revision: The resolved immutable model identity. **Not** a tag: a tag
            moves, so keying on one would let a swapped model reuse the previous
            model's answers.

    """

    kernel_version: str
    adapter_revision: str
    model_revision: str


@dataclasses.dataclass(frozen=True, slots=True)
class KeyContext:
    """Everything outside a stage that its cache key depends on.

    One run-level term and one per-kernel triple. Both are required and neither has a
    default: a key composed from a substituted term is the silent failure the key
    exists to prevent (`sad.md` §5.1).

    Attributes:
        registry_hash: K8's hash over the registry content, as `E03-01` produced it.
        kernels: Kernel name to its :class:`KernelTerms`. Every kernel a graph names
            must be present; a missing entry is a usage error and not a default.

    """

    registry_hash: str
    kernels: Mapping[str, KernelTerms]


@dataclasses.dataclass(frozen=True, slots=True)
class Stage:
    """One step of a graph: a kernel operation, its settings and its needs.

    Attributes:
        name: The stage's name, unique within its graph.
        kernel: The kernel that owns the operation, e.g. ``"store"``. A kernel
            *name*, never a resolved engine: naming an engine here would put
            resolution inside a graph.
        op: The operation within that kernel.
        needs: The stages that must be terminal before this one is dispatched. Empty
            for a stage that consumes the unit's own input.
        params: The stage's own settings, as strings, and they feed the cache key.
            Ordered by name when the key is composed, so iteration order cannot
            change a key.

    Raises:
        ValueError: On an empty name, kernel or operation, or on an empty string in
            ``params`` - each of which is a stand-in rather than a value.

    """

    name: str
    kernel: str
    op: str
    needs: tuple[str, ...]
    params: Mapping[str, str]

    def __post_init__(self) -> None:
        """Refuse a stage whose fields are empty or whose needs name itself.

        Raises:
            ValueError: On an empty string field, a non-string parameter value, or a
                need naming this stage.

        """
        for field_name, value in (("name", self.name), ("kernel", self.kernel)):
            if not value:
                raise ValueError(
                    f"A stage's {field_name} must be stated: an empty one is a "
                    "stand-in, and a graph of unnamed steps cannot be reported."
                )

        if not self.op:
            raise ValueError(
                "A stage's op must be stated: a stage that names no operation is a "
                "step nobody can dispatch."
            )

        if self.name in self.needs:
            raise ValueError(
                f"Stage {self.name!r} declares itself as its own need. A self-edge "
                "cannot become ready, so the only honest answer is to refuse it "
                "rather than leave it pending forever."
            )

        for key, value in self.params.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise TypeError(
                    "A stage's params must be a mapping of string to string: a "
                    "non-string setting cannot enter the cache key, and coercing it "
                    "would key on a rendering rather than on the value."
                )
            if not key:
                raise ValueError(
                    "A param name must be stated: an empty name is a stand-in that "
                    "no key can carry."
                )


@dataclasses.dataclass(frozen=True, slots=True)
class Graph:
    """A set of stages, with the dispatch order resolved once.

    The order is computed here rather than discovered while running, for two
    reasons: a cycle must be refused when the graph is read instead of deadlocking a
    run, and the order must be **deterministic** so two runs of the same graph
    dispatch in the same sequence. Ties are broken by declaration order, so the
    order is a function of the descriptor and not of a set's iteration.

    Attributes:
        stages: The stages, in declaration order.
        order: The stage names in a dispatch order that respects every ``needs``.

    Raises:
        ValueError: If two stages share a name, if a ``needs`` entry names an
            undeclared stage, or if the needs graph contains a cycle.

    """

    stages: tuple[Stage, ...]
    order: tuple[str, ...]

    @property
    def by_name(self) -> Mapping[str, Stage]:
        """Return the stages keyed by name.

        Returns:
            A read-only mapping from stage name to :class:`Stage`.

        """
        return MappingProxyType({stage.name: stage for stage in self.stages})


@dataclasses.dataclass(frozen=True, slots=True)
class Descriptor:
    """A descriptor as read from a file: a name, its units and a stage graph.

    Attributes:
        unit: The descriptor's ``unit`` field. It names the unit **set**, and it is
            also the single unit's name when ``units`` does not enumerate members.
        units: The unit names the graph runs over, in dispatch order. A descriptor
            that omits ``units`` runs over exactly one unit, named after ``unit``.
        graph: The stage graph.

    Raises:
        ValueError: If ``unit`` is empty or if ``units`` is empty, or if a unit name
            is repeated - a repeated unit would have one ledger written twice.

    """

    unit: str
    units: tuple[str, ...]
    graph: Graph

    def __post_init__(self) -> None:
        """Refuse a descriptor with no name or with a repeated unit.

        Raises:
            ValueError: On an empty ``unit`` or ``units``, or on a duplicate name.

        """
        if not self.unit:
            raise ValueError(
                "A descriptor must name its unit set: an unnamed set cannot be "
                "reported, and its members would have no identity to be keyed by."
            )

        if not self.units:
            raise ValueError(
                "A descriptor must cover at least one unit: a run over nothing would "
                "produce a manifest that says nothing while looking finished."
            )

        duplicates = sorted({name for name in self.units if self.units.count(name) > 1})
        if duplicates:
            raise ValueError(
                f"Unit names must be unique within a descriptor; repeated: "
                f"{duplicates}. Two units sharing a name share a ledger, so one "
                "would overwrite the other's record."
            )


@dataclasses.dataclass(frozen=True, slots=True)
class Unit:
    """One unit of work: a name, and the input its first stage consumes.

    The input hash is the caller's. For a synthetic descriptor it is the hash of
    something the caller invented; for a real run it is the source artifact's hash.
    K1 does not derive it, because deriving it would mean knowing what the unit *is*.

    Attributes:
        name: The unit's name. Its directory under the output root and its ledger are
            both named after it (`prd.md` FR-29).
        input_hash: The sha256 the unit's own input has, as the stage with no needs
            will see it.

    """

    name: str
    input_hash: str


@dataclasses.dataclass(frozen=True, slots=True)
class StageCall:
    """What an operation receives when a stage is dispatched.

    Everything an operation needs to do its work and to *report* what it did, and
    nothing about what the stage means. The cache key is on the call because an
    operation's own artifacts usually belong under it.

    Attributes:
        unit: The unit's name.
        unit_dir: The unit's directory, where the ledger lives.
        stage: The stage being dispatched.
        cache_key: The seven-term key the stage runs under, already recorded as
            ``running`` before this call.
        input_hash: The unit's own input hash, or the composed hash of the stage's
            needs. It is the key's first term and it is on the call so an operation
            does not have to recompose it.
        needs: Need name to the artifact hash that need produced. Empty for a stage
            with no needs.

    """

    unit: str
    unit_dir: Path
    stage: Stage
    cache_key: str
    input_hash: str
    needs: Mapping[str, str]


# A Protocol declares members, not methods with bodies; one member is the contract.
# pylint: disable=too-few-public-methods
class StageOperation(Protocol):
    """One kernel operation, bound to its engine by the composition root.

    A protocol rather than a class: the thing behind it is a function the caller
    already has, and wrapping it would be an abstraction with nothing to abstract.
    The return type is the contract - see the module docstring on why an operation
    must produce an :class:`~docflow.kernels.types.Artifact`.

    Its single public member is the contract, not an oversight: a stage is dispatched
    by calling it, and a second member would be a second dispatch path.
    """

    # A Protocol declares an interface; one member *is* the whole interface here.
    # pylint: disable=too-few-public-methods
    def __call__(self, call: StageCall) -> KernelResult[Artifact]:
        """Run one stage.

        Args:
            call: The unit, the stage, the key and the upstream artifacts.

        Returns:
            The artifact this stage durably produced, or no value and the typed
            reason it produced none. A ``KernelResult`` either way: an operation that
            raised would be a bug rather than a result, and the two must stay apart.

        """


@dataclasses.dataclass(frozen=True, slots=True)
class _RunContext:
    """The run-level values every unit's pass needs, gathered so the pass takes one.

    Attributes:
        descriptor: The descriptor being run.
        input_hashes: Unit name to the unit's own input hash.
        operations: The operation table, keyed by ``(kernel, op)``.
        keys: The registry hash and the per-kernel terms.

    """

    descriptor: Descriptor
    input_hashes: Mapping[str, str]
    operations: Mapping[tuple[str, str], StageOperation]
    keys: KeyContext


@dataclasses.dataclass(slots=True)
class _Tally:
    """What one dispatch pass did, accumulated as it goes.

    Mutable and internal: the public :class:`RunReport` is frozen because it is
    returned, and this is only ever handed around inside one call to :func:`run`.

    Attributes:
        dispatched: The ``(unit, stage)`` pairs actually run.
        skipped: The pairs left alone because they were terminal for their key.
        blocked: The pairs that could not run because a need produced no artifact.

    """

    dispatched: list[tuple[str, str]] = dataclasses.field(default_factory=list)
    skipped: list[tuple[str, str]] = dataclasses.field(default_factory=list)
    blocked: list[tuple[str, str]] = dataclasses.field(default_factory=list)
    #: Units and stages this pass did **not** touch because an operator's control asked
    #: the run to hold. Kept apart from ``skipped``, which means *already done for this
    #: key*: conflating them would report held work as complete.
    held: list[str] = dataclasses.field(default_factory=list)


@dataclasses.dataclass(frozen=True, slots=True)
class RunReport:
    """What one dispatch pass did, as opposed to what the run now contains.

    Deliberately not the manifest. The manifest says *what the ledgers say now*; this
    says *what this call changed*, which is the difference a caller needs to report a
    second `run` that correctly did nothing.

    Attributes:
        dispatched: The ``(unit, stage)`` pairs this call actually ran.
        skipped: The ``(unit, stage)`` pairs left alone because they were terminal for
            their key.
        blocked: The ``(unit, stage)`` pairs that could not run because a need did not
            produce an artifact. They are left ``pending`` - see the note below.
        held: The units and ``unit:stage`` checkpoints this pass did not reach because
            an operator's control asked the run to hold. **Not** the same as
            ``skipped``: held work has not been done, and reporting it as skipped would
            read as complete.
        manifest: The manifest as written, which is what :func:`rebuild_index` returns.

    """

    dispatched: tuple[tuple[str, str], ...]
    skipped: tuple[tuple[str, str], ...]
    blocked: tuple[tuple[str, str], ...]
    held: tuple[str, ...]
    manifest: Mapping[str, object]


@dataclasses.dataclass(frozen=True, slots=True)
class Control:
    """What an operator has asked of a run, recorded at the output root.

    Deliberately **two** states plus ``running``, not a full run-state vocabulary. A run
    is otherwise described by its ledgers, and a second place that claimed to know
    whether a run had finished would be a second authority - the drift `sad.md` §3
    splits K7 and K1 to avoid. What a ledger cannot express is *an operator asked this
    to hold*, so that is all this carries.

    The *first* checkpoint is what makes a pause observable: a run reads the control
    before its first stage as well as between stages, so writing ``paused`` after a run
    has begun does not race the run's start.

    Attributes:
        state: ``running``, ``paused`` or ``stopped``.

    Raises:
        ValueError: On a state outside the three. An unrecognised value is refused
            rather than treated as ``running``, because silently resuming a run an
            operator asked to hold is the failure this file is read to prevent.

    """

    state: str

    def __post_init__(self) -> None:
        """Refuse a control state that is not one of the three.

        Raises:
            ValueError: On an unrecognised state.

        """
        if self.state not in CONTROL_STATES:
            raise ValueError(
                f"{self.state!r} is not a control state. The set is "
                f"{sorted(CONTROL_STATES)}; an unrecognised value read as *carry on* "
                "would resume a run somebody asked to hold."
            )

    @property
    def holds(self) -> bool:
        """Report whether this control asks the run to stop dispatching.

        Returns:
            True for ``paused`` and ``stopped``.

        """
        return self.state in HOLDING_CONTROLS


def control_path(out_dir: Path) -> Path:
    """Return the control file for a run.

    Args:
        out_dir: The run's output root.

    Returns:
        ``<out_dir>/control.json``.

    """
    return out_dir / CONTROL_NAME


def read_control(out_dir: Path) -> Control:
    """Read a run's control, defaulting to ``running`` when the file is absent.

    Absent means ``running`` and nothing else: a run that has not been asked to hold is
    a run that carries on. That is the only default in this module, and it is a default
    about *an operator's absence of a request* rather than about a value the system
    would otherwise have to produce - the class of default the artifacts forbid.

    Args:
        out_dir: The run's output root.

    Returns:
        The recorded control, or ``running`` when none is recorded.

    Raises:
        ValueError: If the file carries an unrecognised state, or is not an object with
            a ``state``. A malformed control is refused rather than read as ``running``:
            the file exists because somebody asked for something.

    """
    path = control_path(out_dir)
    if not path.is_file():
        return Control(state="running")

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(
            f"The control file at {path} must hold an object, not "
            f"{type(payload).__name__}: a control that cannot be read is not an "
            "instruction to carry on."
        )
    return Control(state=str(payload.get("state", "")))


def write_control(out_dir: Path, state: str) -> Control:
    """Record what an operator asks of a run, atomically.

    Written through K7's atomic write for the same reason a ledger is: a half-written
    control would be read as a state nobody asked for, and the run would either resume
    against an operator's instruction or hold when none was given.

    Args:
        out_dir: The run's output root, created if it does not exist.
        state: ``running``, ``paused`` or ``stopped``.

    Returns:
        The control as written.

    Raises:
        ValueError: On an unrecognised state.

    """
    control = Control(state=state)
    out_dir.mkdir(parents=True, exist_ok=True)
    # TODO: [MVP] K7 exposes no public atomic-write entry point, so this reaches the
    # private helper. The right fix is a narrow `store.write_json_atomically` that both
    # this and the ledger writer call, and it is not made here because it widens K7's
    # surface - which is `E02`'s and `E07-02`'s to decide, not this issue's.
    store._atomic_write(  # pylint: disable=protected-access
        control_path(out_dir),
        (json.dumps({"state": control.state}, indent=2) + "\n").encode("utf-8"),
    )
    return control


def control_of(out_dir: Path) -> str:
    """Return the control state recorded for a run.

    Args:
        out_dir: The run's output root.

    Returns:
        The state, or ``running`` when none is recorded.

    """
    return read_control(out_dir).state


def is_terminal(state: str) -> bool:
    """Report whether a stage state is a result rather than a position on the way.

    Args:
        state: One of the seven durable states.

    Returns:
        True for ``done``, ``failed`` and ``skipped``.

    """
    return state in _TERMINAL_STATES


def input_hash_for(
    unit: Unit,
    graph: Graph,
    stage_name: str,
    recorded: Mapping[str, store.StageRecord],
) -> str:
    """Compose the first cache-key term for one stage of one unit.

    A stage with no needs consumes the unit's own input. A stage with needs consumes
    what they produced, so its input hash is composed from their artifact hashes -
    sorted by need name and length-prefixed, the same encoding discipline K8's
    registry hash uses, so that no pair of needs can be rearranged into the same
    string.

    Args:
        unit: The unit the stage belongs to.
        graph: The graph, for the stage's declared needs.
        stage_name: The stage whose input hash is wanted.
        recorded: The unit's recorded stage records.

    Returns:
        The hexadecimal sha256 of the stage's input.

    Raises:
        ValueError: If the stage is not declared, or if a need has no artifact hash
            recorded - in which case this stage has no input and must not be
            dispatched, rather than being handed a placeholder.

    """
    stage = graph.by_name.get(stage_name)
    if stage is None:
        raise ValueError(
            f"Stage {stage_name!r} is not declared in this graph, so it has no "
            "input to compose."
        )

    if not stage.needs:
        return unit.input_hash

    parts: list[str] = []
    for need in sorted(stage.needs):
        digest = recorded[need].artifact_sha256
        if digest is None:
            raise ValueError(
                f"Stage {stage_name!r} needs {need!r}, which recorded no artifact. "
                "A stage with a missing input is not dispatched: composing a key "
                "over an absent hash would mean inventing one."
            )
        parts.append(f"{len(need)}:{need}{len(digest)}:{digest}")

    return hashlib.sha256("".join(parts).encode("utf-8")).hexdigest()


def cache_key_for(
    stage: Stage,
    input_hash: str,
    keys: KeyContext,
) -> str:
    """Compose the seven-term cache key a stage would run under now.

    Args:
        stage: The stage about to be dispatched.
        input_hash: Its first term, as :func:`input_hash_for` produced it.
        keys: The registry hash and the per-kernel terms.

    Returns:
        The key, as :func:`docflow.kernels.cache_key.cache_key` composed it.

    Raises:
        ValueError: If the stage's kernel has no terms in ``keys``. A missing entry
            means the key cannot be composed, and a key composed from a defaulted
            term is the failure `sad.md` §5.1 exists to prevent.

    """
    terms = keys.kernels.get(stage.kernel)
    if terms is None:
        raise ValueError(
            f"No key terms are declared for kernel {stage.kernel!r}, which stage "
            f"{stage.name!r} needs. Resolution is the caller's: K1 composes a key "
            "from the terms it is given and has no default to fall back on."
        )

    return cache_key(
        make_terms(
            input_hash=input_hash,
            kernel_id=stage.kernel,
            kernel_version=terms.kernel_version,
            adapter_revision=terms.adapter_revision,
            params=stage.params,
            registry_hash=keys.registry_hash,
            model_revision=terms.model_revision,
        )
    )


def descriptor_from_mapping(payload: Mapping[str, object]) -> Descriptor:
    """Build a descriptor from an already-parsed mapping.

    The shape is enforced here rather than trusted, and *unknown keys are refused*:
    that is what makes "a descriptor naming a pipeline code is not a shape this
    module accepts" a structural fact instead of a promise about what authors will
    write.

    Args:
        payload: The parsed descriptor.

    Returns:
        The descriptor.

    Raises:
        TypeError: If ``payload`` is not a mapping, or if a field has the wrong type.
        ValueError: On an unknown key, a missing required key, or any of the
            consistency rules the value types enforce.

    """
    if not isinstance(payload, Mapping):
        raise TypeError(
            f"A descriptor must parse to a mapping, not {type(payload).__name__}."
        )

    _refuse_unknown_keys(payload, _DESCRIPTOR_KEYS, "descriptor")

    unit = payload.get("unit")
    if not isinstance(unit, str):
        raise TypeError("A descriptor's 'unit' must be a string.")

    raw_units = payload.get("units")
    if raw_units is None:
        units: tuple[str, ...] = (unit,)
    elif isinstance(raw_units, list) and all(
        isinstance(name, str) for name in raw_units
    ):
        units = tuple(raw_units)
    else:
        raise TypeError("A descriptor's 'units' must be a list of strings.")

    raw_stages = payload.get("stages")
    if not isinstance(raw_stages, list):
        raise TypeError("A descriptor's 'stages' must be a list of stage mappings.")

    return Descriptor(
        unit=unit,
        units=units,
        graph=_graph_from_stages(raw_stages),
    )


def read_descriptor(
    path: Path,
    read_mapping: Callable[[Path], Mapping[str, object]],
) -> Descriptor:
    """Read a descriptor through an injected reader.

    The reader is injected because parsing YAML puts a third-party library behind the
    kernel layer, and the kernel layer imports no third party. The composition root
    supplies the real reader; a test supplies a dictionary, which is what makes the
    graph loadable without the format being involved.

    Args:
        path: The descriptor file.
        read_mapping: Reads the file and parses it into a mapping.

    Returns:
        The descriptor.

    Raises:
        TypeError: If the reader returns something that is not a mapping.
        ValueError: Per :func:`descriptor_from_mapping`.
        OSError: If the file cannot be read - raised by the reader, and deliberately
            not swallowed: a descriptor that could not be read is not an empty graph.

    """
    return descriptor_from_mapping(read_mapping(path))


def validate(
    descriptor: Descriptor,
    input_hashes: Mapping[str, str],
    operations: Mapping[tuple[str, str], StageOperation],
    keys: KeyContext,
) -> None:
    """Check that a run could proceed, without writing anything.

    Called by :func:`run` before the first ledger is touched, so a descriptor the
    caller cannot actually execute fails while the output tree is still empty. It is
    public because that is the operation `orchestrator plan` needs
    (`kernel-cli.md` §9): validate only, and dispatch nothing.

    Args:
        descriptor: The descriptor to run.
        input_hashes: Unit name to the unit's own input hash. Every unit the
            descriptor declares must be present.
        operations: The operation table, keyed by ``(kernel, op)``.
        keys: The registry hash and the per-kernel terms.

    Raises:
        ValueError: If a declared unit has no input hash, if a stage names an
            operation the table does not provide, or if a kernel has no key terms.

    """
    missing_units = sorted(set(descriptor.units) - set(input_hashes))
    if missing_units:
        raise ValueError(
            f"No input hash is declared for unit(s) {missing_units}. A unit's input "
            "is the caller's to state: a default would be a input no source ever "
            "produced."
        )

    for stage in descriptor.graph.stages:
        if (stage.kernel, stage.op) not in operations:
            raise ValueError(
                f"Stage {stage.name!r} names operation {stage.kernel}:{stage.op}, "
                "which this deployment provides no operation for. An operation table "
                "that lacks a stage is a configuration error, and guessing one would "
                "be the fallback this layer refuses."
            )

    for kernel in sorted({stage.kernel for stage in descriptor.graph.stages}):
        if kernel not in keys.kernels:
            raise ValueError(
                f"No key terms are declared for kernel {kernel!r}. Every kernel a "
                "graph names must be keyed, or its stages would share a key with "
                "stages they are not the same work as."
            )


def run(
    descriptor: Descriptor,
    out_dir: Path,
    *,
    input_hashes: Mapping[str, str],
    operations: Mapping[tuple[str, str], StageOperation],
    keys: KeyContext,
) -> RunReport:
    """Drive a descriptor's graph over its units, and write the manifest.

    One pass in dispatch order. For each unit and stage: compose the key, leave the
    stage alone if it is already terminal **for that key**, and otherwise record it
    ``running``, hand it to its operation, and record the outcome.

    Running this twice is what idempotency means: the second call finds every stage
    terminal for its own key and dispatches nothing. Reproducing the manifest is not a
    second code path - the manifest is written by calling :func:`rebuild_index`, so
    what is on disk is what the ledgers say, always.

    Args:
        descriptor: The descriptor to run.
        out_dir: The run's output root. Unit directories and the manifest live here.
        input_hashes: Unit name to the unit's own input hash.
        operations: The operation table, keyed by ``(kernel, op)``.
        keys: The registry hash and the per-kernel terms.

    Returns:
        A :class:`RunReport` naming what this call dispatched, skipped and left
        blocked, plus the manifest as written. A run that an operator's control asked
        to hold reports the units and stages it did **not** reach under ``held`` rather
        than pretending they were skipped.

    Raises:
        ValueError: If :func:`validate` refuses the run, or if a stage's key cannot
            be composed.

    """
    validate(descriptor, input_hashes, operations, keys)

    tally = _Tally()
    run_context = _RunContext(
        descriptor=descriptor,
        input_hashes=input_hashes,
        operations=operations,
        keys=keys,
    )

    # The control is read **before the first stage**, not only between them. A run that
    # checked only between units would dispatch a whole unit of stages after an operator
    # asked it to hold, and the pause would look like it had been ignored.
    control = read_control(out_dir)
    for unit_name in descriptor.units:
        if control.holds:
            tally.held.append(unit_name)
            continue
        control = _run_unit(run_context, unit_name, out_dir, tally)

    manifest = write_index(out_dir)

    return RunReport(
        dispatched=tuple(tally.dispatched),
        skipped=tuple(tally.skipped),
        blocked=tuple(tally.blocked),
        held=tuple(tally.held),
        manifest=manifest,
    )


def _run_unit(
    run_context: _RunContext, unit_name: str, out_dir: Path, tally: _Tally
) -> Control:
    """Drive one unit's stages in dispatch order, recording outcomes as it goes.

    The ledger is re-read after each dispatch rather than patched in memory: the
    next stage's input hash and key are composed from what is **on disk**, so a
    composition cannot be built on a value that was never written.

    The control is re-read **before every stage**, which is what makes a pause land at
    a stage boundary rather than a unit boundary: a unit of a real job is many stages,
    and holding only between units would make `pause` indistinguishable from *let the
    whole job finish*.

    Args:
        run_context: The run-level context.
        unit_name: The unit to drive.
        out_dir: The run's output root.
        tally: The accumulator for this pass.

    Returns:
        The control as of the last checkpoint, so the caller knows whether to continue
        with the next unit without re-reading the file.

    """
    graph = run_context.descriptor.graph
    unit = Unit(name=unit_name, input_hash=run_context.input_hashes[unit_name])
    unit_dir = _unit_dir(out_dir, unit_name)
    _ensure_ledger(unit_dir, unit.name, tuple(stage.name for stage in graph.stages))

    control = read_control(out_dir)
    recorded = store.read_ledger(unit_dir).stages
    for stage_name in graph.order:
        if control.holds:
            tally.held.append(f"{unit.name}:{stage_name}")
            return control

        stage = graph.by_name[stage_name]

        upstream = _upstream_hashes(recorded, stage)
        if upstream is None:
            tally.blocked.append((unit.name, stage_name))
            continue

        stage_input = input_hash_for(unit, graph, stage_name, recorded)
        key = cache_key_for(stage, stage_input, run_context.keys)

        if is_terminal(recorded[stage_name].state) and (
            recorded[stage_name].cache_key == key
        ):
            tally.skipped.append((unit.name, stage_name))
            continue

        call = StageCall(
            unit=unit.name,
            unit_dir=unit_dir,
            stage=stage,
            cache_key=key,
            input_hash=stage_input,
            needs=MappingProxyType(dict(upstream)),
        )
        _dispatch(
            run_context.operations[(stage.kernel, stage.op)], unit_dir, call, stage.name
        )
        tally.dispatched.append((unit.name, stage_name))
        recorded = store.read_ledger(unit_dir).stages
        control = read_control(out_dir)

    return control


def rebuild_index(out_dir: Path) -> Mapping[str, object]:
    """Derive the manifest from the ledger tree, and from nothing else.

    The single authority for what a run contains (`kernel-cli.md` §9). It reads every
    ``*.ledger.json`` under ``out_dir``; it does not read the descriptor, the run's
    arguments, or any previously written manifest - a manifest is read only by being
    rebuilt, which is what makes *derived* a fact rather than an intention.

    Args:
        out_dir: The run's output root.

    Returns:
        The manifest, with ``state``, ``totals``, ``stages``, ``outcomes`` and
        ``inflight``.

    """
    ledgers = [
        store.read_ledger(path.parent) for path in sorted(out_dir.glob(_LEDGER_GLOB))
    ]

    stages: dict[str, dict[str, dict[str, object]]] = {}
    totals: dict[str, int] = {"units": len(ledgers), "stages": 0}
    totals.update(dict.fromkeys(store.DURABLE_STATE_ORDER, 0))
    outcomes: dict[str, int] = {}
    attempts: dict[str, dict[str, int]] = {}
    inflight: list[str] = []

    for ledger in ledgers:
        unit_stages: dict[str, dict[str, object]] = {}
        unit_attempts: dict[str, int] = {}
        unfinished = False
        for stage_name, record in ledger.stages.items():
            unit_stages[stage_name] = dict(record.as_mapping())
            totals["stages"] += 1
            totals[record.state] += 1
            if record.reason_code is not None:
                outcomes[record.reason_code] = outcomes.get(record.reason_code, 0) + 1
            if record.attempts:
                unit_attempts[stage_name] = record.attempts
            if not is_terminal(record.state):
                unfinished = True
        stages[ledger.unit] = unit_stages
        if unit_attempts:
            attempts[ledger.unit] = unit_attempts
        if unfinished:
            inflight.append(ledger.unit)

    return {
        "state": _run_state(out_dir, len(ledgers), inflight),
        "control": control_of(out_dir),
        "totals": totals,
        "stages": stages,
        "outcomes": outcomes,
        # A stage whose attempt count exceeds one is the visible trace of a retry. It
        # is reported rather than policed: retrying to obtain agreement is forbidden
        # for a sampled kernel (`kernel-cli.md` §7) and the prohibition is enforceable
        # only if the pattern can be seen (`plan-01-kernels.md` §9).
        "attempts": attempts,
        "inflight": inflight,
    }


def _run_state(out_dir: Path, units: int, inflight: Sequence[str]) -> str:
    """Return the run's state, from its ledgers and its control.

    Three values, and each is distinguishable from the other two: ``complete`` when
    there is at least one ledger and every unit it covers is terminal; ``holding`` when
    work remains **and** an operator asked the run to hold; ``incomplete`` otherwise.

    **A run with no ledgers is never ``complete``.** It has produced nothing - which is
    what a pause taken before the first unit looks like on disk - and reporting *no
    unfinished units* as *finished* would be the same class of error as a `done` claim
    about bytes that do not exist, one level up. That case is exactly what the first
    checkpoint in :func:`run` exists to produce, so it has to read correctly.

    Args:
        out_dir: The run's output root.
        units: How many units have a ledger.
        inflight: The units with at least one non-terminal stage.

    Returns:
        The run state.

    """
    if units == 0:
        return _RUN_HOLDING if read_control(out_dir).holds else _RUN_INCOMPLETE

    if not inflight:
        return _RUN_COMPLETE

    return _RUN_HOLDING if read_control(out_dir).holds else _RUN_INCOMPLETE


def write_index(out_dir: Path) -> Mapping[str, object]:
    """Write the manifest, after deriving it.

    Derive, then write - never the other way round. The file is written with the same
    atomic write K7 uses, because a half-written manifest is the same class of defect
    as a half-written artifact, and it is readable with ``jq`` without the tool
    installed (`NFR-09`, `prd.md` FR-11).

    Args:
        out_dir: The run's output root, created if it does not exist.

    Returns:
        The manifest as written, which is what :func:`rebuild_index` returned.

    """
    manifest = rebuild_index(out_dir)
    # TODO: [MVP] The pretty-printed JSON is the PoC's format. S3-T07 owns the
    # manifest's shape and location, and a committed schema should replace the
    # implicit one this writer produces.
    store._atomic_write(  # pylint: disable=protected-access
        out_dir / MANIFEST_NAME,
        (json.dumps(manifest, indent=2) + "\n").encode("utf-8"),
    )
    return manifest


def _dispatch(
    operation: StageOperation, unit_dir: Path, call: StageCall, stage_name: str
) -> None:
    """Run one stage and record its outcome.

    ``begin`` is called before the operation, which is the only honest place for it -
    the state has to be on disk before the work exists, or a kill leaves the ledger
    unable to say the stage was ever reached. *Proving* that ordering survives a kill
    is `E05-02`'s (`S1-T07`); calling it here is this module's.

    Args:
        operation: The bound operation to call.
        unit_dir: The unit's directory, where the ledger lives.
        call: Everything the operation is given, already composed - including the
            input hash, which is deliberately not recomputed here: recomputing it
            would be a second answer to a question that already had one.
        stage_name: The stage's name, for the refusal below.

    Raises:
        TypeError: If the operation returned neither a value nor a reason, which
            ``KernelResult`` cannot express.

    """
    store.begin(unit_dir, stage_name, call.cache_key)

    result = operation(call)

    if result.value is not None:
        store.commit(unit_dir, stage_name, result.value, call.cache_key)
        return

    reason = result.reason
    if reason is None:
        # A KernelResult cannot express this by construction, so reaching it means the
        # operation built something outside its type. Reporting it as a `failed` stage
        # with a substituted code would be the stand-in this layer refuses; naming it
        # as a bug is the honest answer.
        raise TypeError(
            f"The operation for stage {stage_name!r} returned neither a value nor a "
            "reason. KernelResult cannot express that, so its construction was "
            "bypassed somewhere and the run cannot continue on a guess."
        )

    store.fail(unit_dir, stage_name, reason, call.cache_key)


def _upstream_hashes(
    recorded: Mapping[str, store.StageRecord], stage: Stage
) -> Mapping[str, str] | None:
    """Collect the artifact hashes a stage's needs produced.

    Args:
        recorded: The unit's recorded stage records.
        stage: The stage whose needs are being resolved.

    Returns:
        Need name to artifact hash, or None when a need is terminal but produced no
        artifact, or is not terminal yet. None means *this stage cannot run*, which is
        a different fact from *this stage produced nothing*.

    """
    upstream: dict[str, str] = {}
    for need in stage.needs:
        record = recorded[need]
        if not is_terminal(record.state) or record.artifact_sha256 is None:
            return None
        upstream[need] = record.artifact_sha256
    return upstream


def _unit_dir(out_dir: Path, unit_name: str) -> Path:
    """Return, and create, a unit's directory under the output root.

    Args:
        out_dir: The run's output root.
        unit_name: The unit's name.

    Returns:
        ``<out_dir>/<unit_name>``.

    """
    unit_dir = out_dir / unit_name
    unit_dir.mkdir(parents=True, exist_ok=True)
    return unit_dir


def _ensure_ledger(unit_dir: Path, unit_name: str, stage_names: Sequence[str]) -> None:
    """Declare a unit's stage set, unless it is already declared.

    A unit that has run before keeps its ledger: re-declaring it would erase exactly
    the record the second run is supposed to read.

    Args:
        unit_dir: The unit's directory.
        unit_name: The unit's name, recorded inside the ledger.
        stage_names: The graph's stage names, in declaration order.

    """
    if store.ledger_path(unit_dir).is_file():
        return
    store.write_ledger(unit_dir, store.new_ledger(unit_name, stage_names))


def _graph_from_stages(raw_stages: Sequence[object]) -> Graph:
    """Build a graph from a descriptor's raw stage list.

    Args:
        raw_stages: The parsed stage mappings, in declaration order.

    Returns:
        The graph, with its dispatch order resolved.

    Raises:
        TypeError: If a stage is not a mapping or a field has the wrong type.
        ValueError: Per :class:`Graph`.

    """
    stages = tuple(_stage_from_mapping(raw) for raw in raw_stages)
    return Graph(stages=stages, order=_dispatch_order(stages))


def _stage_from_mapping(raw: object) -> Stage:
    """Build one stage from a parsed mapping.

    Args:
        raw: The parsed stage mapping.

    Returns:
        The stage.

    Raises:
        TypeError: If ``raw`` is not a mapping or a field has the wrong type.
        ValueError: On an unknown key or a missing required one.

    """
    if not isinstance(raw, Mapping):
        raise TypeError(f"Every stage must be a mapping, not {type(raw).__name__}.")

    _refuse_unknown_keys(raw, _STAGE_KEYS, "stage")

    name = raw.get("name")
    kernel = raw.get("kernel")
    op = raw.get("op")
    for field_name, field_value in (("name", name), ("kernel", kernel), ("op", op)):
        if not isinstance(field_value, str):
            raise TypeError(f"A stage's '{field_name}' must be a string.")

    raw_needs = raw.get("needs", [])
    if not isinstance(raw_needs, list) or not all(
        isinstance(need, str) for need in raw_needs
    ):
        raise TypeError("A stage's 'needs' must be a list of stage names.")

    raw_params = raw.get("params", {})
    if not isinstance(raw_params, Mapping) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in raw_params.items()
    ):
        raise TypeError("A stage's 'params' must be a mapping of string to string.")

    return Stage(
        name=name,
        kernel=kernel,
        op=op,
        needs=tuple(raw_needs),
        params=MappingProxyType(dict(raw_params)),
    )


def _refuse_unknown_keys(
    payload: Mapping[str, object], allowed: frozenset[str], where: str
) -> None:
    """Refuse any key outside the declared shape.

    Args:
        payload: The mapping to check.
        allowed: The keys the shape declares.
        where: Which shape, for the message.

    Raises:
        ValueError: If an undeclared key is present.

    """
    unknown = sorted(key for key in payload if key not in allowed)
    if unknown:
        raise ValueError(
            f"Unknown key(s) in the {where}: {unknown}. The accepted shape is "
            f"{sorted(allowed)}, and a key outside it is refused rather than "
            "ignored - a shape that tolerates extra keys cannot tell a descriptor "
            "this module executes from one it does not."
        )


def _dispatch_order(stages: Sequence[Stage]) -> tuple[str, ...]:
    """Resolve a dispatch order that respects every ``needs``.

    Ties are broken by declaration order, so the order is a function of the descriptor
    and not of a set's iteration: two runs of one graph dispatch identically.

    Args:
        stages: The graph's stages, in declaration order.

    Returns:
        The stage names, ordered.

    Raises:
        ValueError: If a need names an undeclared stage, or the needs graph has a
            cycle.

    """
    declared = {stage.name for stage in stages}
    for stage in stages:
        undeclared = sorted(set(stage.needs) - declared)
        if undeclared:
            raise ValueError(
                f"Stage {stage.name!r} needs undeclared stage(s) {undeclared}. A "
                "need that names nothing can never become terminal, so the stage "
                "would stay pending forever with no way to tell why."
            )

    remaining = list(stages)
    ordered: list[str] = []
    satisfied: set[str] = set()

    while remaining:
        ready = [stage for stage in remaining if set(stage.needs) <= satisfied]
        if not ready:
            stuck = sorted(stage.name for stage in remaining)
            raise ValueError(
                f"The needs graph contains a cycle among {stuck}. None of these "
                "stages can ever be dispatched, so the graph is refused when it is "
                "read rather than left to deadlock a run."
            )
        for stage in ready:
            ordered.append(stage.name)
            satisfied.add(stage.name)
        ready_names = {stage.name for stage in ready}
        remaining = [stage for stage in remaining if stage.name not in ready_names]

    return tuple(ordered)
