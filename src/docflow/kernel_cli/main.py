"""``docflow-kernel`` - the dispatcher, the exit-code contract and the envelope.

`E07-01` / `S1-T20`. This module owns three things and no kernel behaviour:

1. **The process-level encoding of the kernel contract.** A kernel either returns
   a value with evidence, or returns no value and a reason (`sad.md` §6). Exit
   ``0`` is the first, exits ``2`` and ``3`` are the second, split by whether the
   *document* answered or the *call* could not legitimately be made, and exits
   ``4`` and ``1`` are the surface's own failures. That split is what lets a shell
  script tell a diagnosis from a precondition from a broken build
   (`kernel-cli.md` §5).
2. **The ``KernelResult`` JSON envelope**, frozen here (`plans/README.md` §3,
   Plan 1 row). The boundary types deliberately carry no encoder: an encoder next
   to the contract would be a second source of truth, which is why `E01-01` left
   this obligation to this issue.
3. **``--list``**, the honest inventory of the eight kernels.

Why the exit code is derived, not passed
---------------------------------------

A handler returns a `KernelResult`; it never returns an exit code. The code is a
pure function of the result: a value is ``0``, and a missing value is looked up in
:data:`REASON_CODE_EXITS` - the closed vocabulary of `kernel-cli.md` §5. A handler
*chooses a reason*; the surface decides what a reason means to a process.

That is what makes the invariant *"exit 2 is reserved for a typed reason"*
structural rather than a convention. There is no code path that maps an exception
to ``2``: exceptions are caught in exactly one place and become ``1``, and a code
outside the closed set is a defect rather than an expected negative, so it also
becomes ``1``. A `Reason` carrying an unknown code is not a typed reason; it is a
vocabulary breach, and reporting it as ``2`` would collapse *expected negative*
into *broken* in the other direction.

Two readings stated rather than assumed
---------------------------------------

- **``--list`` emits JSON**, not the aligned table `kernel-cli.md` §4 shows. §4's
  transcript illustrates the *content* of the inventory; §6 fixes the *format* -
  "stdout is a single JSON document, in the existing ``KernelResult[T]`` shape" -
  and it is §6 that makes ``docflow-kernel ... | jq`` safe. The four documented
  columns are the value's fields; JSON is how they leave the process.
- **The envelope's ``call_record`` is not a `KernelResult` field.** `E01-01`
  froze that type with three fields, so the fourth key is carried by :class:`Call`
  - what a handler *answered* - and is ``null`` for every kernel except the two
  language-model ones (`kernel-cli.md` §6). :class:`Call` is a surface type, not a
  new kernel-boundary type: nothing below this module exchanges it.

Availability is probed, never declared
-------------------------------------

``--list`` reports whether a kernel can serve a call *now*. The probe checks that
the module the plan assigns to that kernel exists and that the engine's own
precondition holds, so an unimplemented kernel reports ``no`` with the reason
attached - never ``yes``. Reporting an unavailable kernel as available is the one
silent fallback that is most expensive here, because the inventory is what a
person trusts when deciding whether a bench is ready (`plan-01-kernels.md` §6
step 2).

PoC stage
---------

Deliberate shortcuts carry ``# TODO: [MVP]`` markers naming what replaces them.

"""

# pylint: disable=too-many-lines
# The dispatcher, the exit-code contract, the envelope and the inventory live in
# one module because they are one contract: the exit code is a function of the
# result, the result is encoded by the envelope, and the flags are the surface both
# describe. Splitting them would put the vocabulary table and the code that looks
# it up in different files, which is the pairing a reader most needs together.

# pylint: disable=too-many-return-statements
# ``_parse_flags`` and ``dispatch`` are the surface's validation: each check returns
# its own usage message so the reason is attributable to one condition. Collapsing
# them would make the message depend on the order of a boolean expression rather
# than on the check that found the problem - and the check is what the message has
# to name for the exit-4 contract to be worth anything.

# pylint: disable=too-few-public-methods
# ``Probe`` is a one-method protocol by design: it answers one question.

# pylint: disable=unnecessary-ellipsis
# The protocol body is an ellipsis because the method has no implementation here;
# a docstring alone would read as a function that returns None.

from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import json
import os
import pathlib
import shutil
import sys
import traceback
from collections.abc import Callable, Mapping, Sequence
from types import MappingProxyType
from typing import Final, Protocol

from docflow.kernels import store
from docflow.kernels.image import InverseMap
from docflow.kernels.types import (
    Artifact,
    Box,
    Bytes,
    CallRecord,
    Evidence,
    KernelResult,
    Reason,
    Token,
)

__all__: list[str] = [
    "ALLOWED_FLAGS",
    "BOOLEAN_FLAGS",
    "DETERMINISM_CLASSES",
    "EXIT_INTERNAL",
    "EXIT_PRECONDITION",
    "EXIT_REASON",
    "EXIT_USAGE",
    "EXIT_VALUE",
    "FORBIDDEN_FLAGS",
    "GLOBAL_FLAGS",
    "KERNEL_SPECS",
    "REASON_CODE_EXITS",
    "VALUE_FLAGS",
    "Call",
    "Invocation",
    "KernelSpec",
    "Operation",
    "UsageError",
    "dispatch",
    "inventory",
    "main",
    "register",
    "registered_operations",
]

# --- The exit-code contract (`kernel-cli.md` §5) -----------------------------

#: A value was produced: ``value`` and ``evidence`` present, ``reason`` null.
EXIT_VALUE: Final[int] = 0

#: No value, with a typed ``Reason`` - a legitimate, expected outcome. The
#: *document's* answer.
EXIT_REASON: Final[int] = 2

#: The call could not legitimately be made - a missing binary, an unpulled model,
#: an unknown model or provider, an absent or invalid asset, no provider key. The
#: *call's* precondition, not the document's verdict.
EXIT_PRECONDITION: Final[int] = 3

#: Usage error: unknown kernel or operation, bad flag, or an operation that is
#: ``MVP`` and therefore does not dispatch. Emits no ``KernelResult``.
EXIT_USAGE: Final[int] = 4

#: Unexpected internal error. Emits no ``KernelResult``; the traceback goes to
#: stderr. Never ``2``: a bug is not an expected negative.
EXIT_INTERNAL: Final[int] = 1


class UsageError(ValueError):
    """The caller *wrote the invocation* wrongly, and that is exit ``4``.

    `kernel-cli.md` §5 assigns exit ``4`` to how a call was written - *"unknown
    kernel/operation, bad flag, malformed range"* - and reserves exit ``1`` for *"a
    bug"*. A handler that raises a plain ``ValueError`` for a malformed flag value
    lands in the dispatcher's catch-all and reports exit ``1``, which tells a caller
    *"this build is broken"* about something they can fix by retyping the command.
    That is the collapse the exit table exists to prevent, made in the third
    direction: §5 distinguishes ``2``/``3``/``4``/``1``, and a shared exception type
    for the last two erases the distinction between them.

    So the class is the mechanism. A caller error raises **this**; the dispatcher
    catches it before its catch-all and answers exit ``4``. A genuine defect keeps
    raising whatever it likes and stays exit ``1``.

    It subclasses ``ValueError`` deliberately, and that is not a convenience: every
    existing caller and test that expects a ``ValueError`` from a parser keeps
    working, and the previous behaviour was *already* a ``ValueError``. Nothing that
    caught it before stops catching it; what changes is only which exit the
    dispatcher derives.

    The other half of the same rule: an error that is *"the call cannot be made with
    what it has"* rather than *"the invocation is malformed"* is exit ``3``, and it
    is raised as a refusal through ``commands/refusals.py`` - a ``KernelResult`` with
    a typed ``Reason``, not an exception. A missing ``--model`` is that case: the flag
    is legal and its absence is a precondition, not bad grammar.
    """


#: The closed set of ``reason.code`` values and the exit each maps to, transcribed
#: from `kernel-cli.md` §5. Closing it here is what makes *"assert on a code, never
#: a message"* possible: a caller can branch on a code, and a code with no entry is
#: a vocabulary breach rather than a new outcome.
#:
#: The vocabulary itself is owned by the issue that raises each code, not by this
#: table. This table only says what a code *means to a process*.
REASON_CODE_EXITS: Final[Mapping[str, int]] = {
    # The document answered.
    "illegible": EXIT_REASON,
    "insufficient_effective_resolution": EXIT_REASON,
    "blank_page": EXIT_REASON,
    "truncated_output": EXIT_REASON,
    "artifact_missing": EXIT_REASON,
    "evidence_missing": EXIT_REASON,
    "encrypted": EXIT_REASON,
    "unsupported_format": EXIT_REASON,
    # The call could not be made.
    "model_not_pulled": EXIT_PRECONDITION,
    "model_unknown": EXIT_PRECONDITION,
    "provider_unknown": EXIT_PRECONDITION,
    "engine_unavailable": EXIT_PRECONDITION,
    "provider_unavailable": EXIT_PRECONDITION,
    "asset_invalid": EXIT_PRECONDITION,
    "asset_missing": EXIT_PRECONDITION,
    "role_conflict": EXIT_PRECONDITION,
}

#: The three determinism classes (`sad.md` §4). The class decides what a test may
#: assert, which is why ``--list`` reports it next to the kernel.
DETERMINISM_CLASSES: Final[tuple[str, ...]] = (
    "deterministic",
    "sampled",
    "external",
)

# --- The flag surface (`kernel-cli.md` §10) ----------------------------------

#: Flags owned by the dispatcher itself.
GLOBAL_FLAGS: Final[tuple[str, ...]] = ("--format", "--list", "--verbose")

#: Flags that take a value. Operation parameters, plus the two path flags, which
#: are **not** synonyms: ``--out`` is where a run's artifacts go and belongs to K1;
#: ``--root`` is which store or registry a kernel reads and belongs to K7/K8.
#:
#: §10's prose list is **not** the authority for this tuple — the per-command
#: tables in §9 are, and the prose list omits eight flags those tables declare
#: (``--asset``, ``--image``, ``--key``, ``--max-pixels``, ``--prefix``,
#: ``--samples-file``, ``--target-dpi``, ``--text-file``). Copying the prose list
#: left nine registered commands **uncallable**: the dispatcher refused each
#: operation's own required flag as unknown. A test now asserts the two sets agree
#: so the omission cannot come back.
VALUE_FLAGS: Final[tuple[str, ...]] = (
    "--asset",
    "--correct",
    "--dpi",
    "--format",
    "--image",
    "--jobs",
    "--key",
    "--lang",
    "--max-pixels",
    "--media-type",
    "--model",
    "--out",
    "--page",
    "--pages",
    "--prefix",
    "--prompt-file",
    "--region",
    "--repeat",
    "--root",
    "--rubric-file",
    "--samples-file",
    "--save",
    "--schema-file",
    "--slots",
    "--target-dpi",
    "--text-file",
    "--timeout",
)

#: Flags that are present or absent, never given a value.
BOOLEAN_FLAGS: Final[tuple[str, ...]] = (
    "--force",
    "--list",
    "--resolve-only",
    "--verbose",
)

#: Every flag the surface may carry. A flag outside this set is a usage error:
#: *"unknown kernel/operation, bad flag"* is exit ``4`` (`kernel-cli.md` §5), and
#: an unlisted flag is precisely the door a convenience flag would come through.
ALLOWED_FLAGS: Final[tuple[str, ...]] = tuple(
    sorted(set(VALUE_FLAGS) | set(BOOLEAN_FLAGS))
)

#: Flags that must never exist on this surface, as a declared vocabulary rather
#: than a rule someone remembers. Two groups, both fatal to a contract test:
#:
#: - anything naming a document concept (`kernel-cli.md` §10, forbidden vocabulary)
#:   - the presence of one is the signal that the lab surface has drifted into the
#:   domain layer;
#: - the six flags the artifacts forbid outright - the OCR engine is never a
#:   setting (ADR-001), validation is never skippable (ADR-002), secrets never
#:   arrive as a flag, there is no fallback or default model, and verification is
#:   never a request (ADR-006).
#:
#: The dispatcher refuses these itself rather than leaving them to a test, so the
#: refusal is a property of the surface and not of the suite.
FORBIDDEN_FLAGS: Final[tuple[str, ...]] = (
    "--api-key",
    "--cuit",
    "--default-model",
    "--document-type",
    "--engine",
    "--extractor",
    "--fallback",
    "--field",
    "--golden",
    "--invoice",
    "--no-validate",
    "--pipeline",
    "--total",
    "--validator",
    "--verify",
)

_USAGE: Final[str] = (
    "usage: docflow-kernel --list\n"
    "       docflow-kernel <kernel> <operation> [arguments] [flags]\n"
    "\n"
    "kernels: "
    + ", ".join(
        (
            "orchestrator",
            "pdf",
            "image",
            "ocr",
            "llm.local",
            "llm.frontier",
            "store",
            "registry",
        )
    )
    + "\n"
)


# --- The inventory -----------------------------------------------------------


class Probe(Protocol):
    """A question the surface asks a kernel before offering it.

    A callable returning ``None`` when the kernel can serve a call, or the reason
    it cannot. The reason is a fact for a human, never an exit code: an
    unavailable kernel is a precondition, but ``--list`` is a *report*, not a call.
    """

    def __call__(self) -> str | None:
        """Report why the kernel is unavailable, or ``None`` when it is available."""
        ...  # pragma: no cover - a protocol body never executes


@dataclasses.dataclass(frozen=True, slots=True)
class KernelSpec:
    """One row of the eight-kernel inventory.

    Attributes:
        code: The ``K1``…``K8`` identifier the plan's task table and the
            silent-failure matrix both use, so the inventory can be joined to the
            matrix without a name lookup.
        name: The kernel's name on this surface, e.g. ``"llm.local"``.
        determinism: One of :data:`DETERMINISM_CLASSES`. The class decides what a
            test may assert, so it is reported next to the kernel rather than left
            to prose.
        adapter: The engine behind the kernel, as a human-readable description. For
            K1 this is ``"—"``: the orchestrator drives, it does not call out.
        probe: What the surface asks before offering the kernel.

    """

    code: str
    name: str
    determinism: str
    adapter: str
    probe: Probe


def _module_exists(module: str) -> bool:
    """Report whether a dotted module path can be resolved.

    Guards against ``ModuleNotFoundError``, which ``find_spec`` raises when a
    *parent* package is absent - the normal case here, because the adapter package
    does not exist until an adapter lands.

    Args:
        module: The dotted module path to look for.

    Returns:
        True when the module is importable without importing it.

    """
    try:
        return importlib.util.find_spec(module) is not None
    except ModuleNotFoundError:
        return False


def _not_landed(module: str) -> str | None:
    """Report the reason a kernel's module is missing, or ``None`` when it exists.

    The module is the one the plan's task table assigns to the kernel, which is why
    this is a check and not a declaration: an unimplemented kernel must never read
    as available.

    Args:
        module: The dotted module path the plan assigns to the kernel.

    Returns:
        The reason, or ``None``.

    """
    if _module_exists(module):
        return None
    return f"not landed ({module})"


def _binary_absent(binary: str) -> str | None:
    """Report the reason an external binary is missing, or ``None`` when present.

    Args:
        binary: The executable name.

    Returns:
        The reason, or ``None``.

    """
    if shutil.which(binary) is not None:
        return None
    return f"{binary} not on PATH"


def _provider_key_absent() -> str | None:
    """Report the reason no frontier provider key is present, or ``None``.

    Secrets arrive from the environment only - there is no ``--api-key`` flag and
    never will be - so the presence of the SDK's own variable is the precondition
    this probe can check without an adapter.

    Returns:
        The reason, or ``None``.

    """
    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        if _environment_has(name):
            return None
    return "no provider key in the environment"
    # TODO: [MVP] The variable's canonical name belongs to `S3-T12`, which owns
    # `.env.example` and the operational-settings vocabulary. Until then the
    # probe reads the two provider SDKs' own conventions, so it cannot invent a
    # name that a later task would have to contradict.


def _environment_has(name: str) -> bool:
    """Report whether an environment variable is set to a non-empty value.

    Reading the environment is deliberate: a provider key is an *operational*
    setting, and this is one of the two surfaces allowed to read one. Corpus policy
    is registry data and is never read from here (ADR-009).

    Args:
        name: The variable's name.

    Returns:
        True when it is set to something non-empty.

    """
    return bool(os.environ.get(name))


def _probe_orchestrator() -> str | None:
    """Ask whether K1 can serve a call: the orchestrator core must exist."""
    return _not_landed("docflow.kernels.orchestrator")


def _probe_pdf() -> str | None:
    """Ask whether K2 can serve a call: its kernel module and poppler must exist."""
    return _not_landed("docflow.kernels.pdf") or _binary_absent("pdftotext")


def _probe_image() -> str | None:
    """Ask whether K3 can serve a call: its kernel module must exist.

    The raster library behind K3 is `E04-03`'s decision, and `kernel-cli.md` §4
    records it only as ``<raster lib>``. Naming a library here would be this issue
    inventing a choice another issue owns, so the probe checks what is decided and
    stops there.
    """
    return _not_landed("docflow.kernels.image")
    # TODO: [MVP] Add the raster library's precondition once `E04-03` names it.
    # Until then K3 reports unavailable because its kernel module has not landed,
    # which is true and does not depend on the library's name.


def _probe_ocr() -> str | None:
    """Ask whether K4 can serve a call: the Docling adapter must exist.

    The engine is Docling and only Docling (ADR-001), so there is exactly one
    adapter to ask about and no engine to choose.
    """
    return _not_landed("docflow.adapters.docling")


def _probe_llm_local() -> str | None:
    """Ask whether K5 can serve a call: the Ollama adapter must exist."""
    return _not_landed("docflow.adapters.ollama") or _binary_absent("ollama")


def _probe_llm_frontier() -> str | None:
    """Ask whether K6 can serve a call: the provider adapter and a key must exist."""
    return _not_landed("docflow.adapters.frontier") or _provider_key_absent()


def _probe_filesystem() -> str | None:
    """Ask whether a filesystem-backed kernel can serve a call.

    K7 and K8 both read the local filesystem, which is always there, so there is
    nothing to check and the answer is always *available*. The two kernels share
    one probe rather than each writing its own constant ``None``: a single place
    where *"nothing is missing"* is produced is a single place to change if either
    kernel ever grows a precondition.
    """
    return None


#: The eight kernels, in code order. Determinism classes are `sad.md` §4's;
#: the modules are the ones `wbs.md` §3 assigns to each kernel.
KERNEL_SPECS: Final[tuple[KernelSpec, ...]] = (
    KernelSpec("K1", "orchestrator", "deterministic", "—", _probe_orchestrator),
    KernelSpec("K2", "pdf", "deterministic", "pdftotext", _probe_pdf),
    KernelSpec("K3", "image", "deterministic", "raster library", _probe_image),
    KernelSpec("K4", "ocr", "sampled", "docling", _probe_ocr),
    KernelSpec("K5", "llm.local", "sampled", "ollama", _probe_llm_local),
    KernelSpec("K6", "llm.frontier", "external", "provider SDK", _probe_llm_frontier),
    KernelSpec("K7", "store", "deterministic", "filesystem", _probe_filesystem),
    KernelSpec("K8", "registry", "deterministic", "filesystem", _probe_filesystem),
)

#: Kernel name to its spec, for dispatch.
KERNEL_BY_NAME: Final[Mapping[str, KernelSpec]] = {
    spec.name: spec for spec in KERNEL_SPECS
}


def inventory() -> tuple[Mapping[str, object], ...]:
    """Report the eight kernels with determinism class and adapter availability.

    This is the *kernel* level, and deliberately not the *command* level: whether
    an adapter is available and whether an operation on it is implemented are two
    facts (`kernel-cli.md` §4), and conflating them is how an inventory starts
    claiming a capability the bench does not have.

    Returns:
        One row per kernel, in code order, with ``available`` and, when it is
        False, the ``detail`` naming why. ``available`` is exactly
        ``detail is None``: there is no second source of truth for the boolean.

    """
    rows: list[Mapping[str, object]] = []
    for spec in KERNEL_SPECS:
        detail = spec.probe()
        rows.append(
            {
                "kernel": spec.name,
                "code": spec.code,
                "determinism": spec.determinism,
                "adapter": spec.adapter,
                "available": detail is None,
                "detail": detail,
            }
        )
    return tuple(rows)


# --- What a handler answers --------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class Call:
    """What one command answered: a result, and the provider call behind it.

    ``call_record`` is a field here rather than on `KernelResult` because `E01-01`
    froze that type with exactly three fields, and because the record is a fact
    about a *provider call* - it is populated for K5 and K6 only and is ``None``
    for every other kernel (`kernel-cli.md` §6).

    Attributes:
        result: The kernel's outcome, in the two-state shape the boundary fixes.
        call_record: What the provider call cost and which revision answered, or
            None for a kernel that made no provider call.

    """

    result: KernelResult[object]
    call_record: CallRecord | None = None


#: What a registered operation does. It receives the parsed operation parameters
#: and answers with a :class:`Call`; it never sees or returns an exit code.
Handler = Callable[..., Call]


@dataclasses.dataclass(frozen=True, slots=True)
class Operation:
    """One command on the lab surface.

    The declaration is the whole contract: a kernel name, an operation name, and
    either a handler or nothing. ``handler=None`` is how an ``MVP`` command is
    declared - it is listed, it is known, and it exits ``4`` naming itself as not
    yet available rather than running partially (`kernel-cli.md` §9). An operation
    that has not landed and an operation that does not exist must stay
    distinguishable, and this is the field that keeps them so.

    Attributes:
        kernel: The kernel's name, which must match a :class:`KernelSpec`.
        name: The operation's name, e.g. ``"put"``.
        handler: The implementation, or None for an ``MVP`` command.
        positional: The parameter a bare argument binds to, or None when the
            operation takes no argument. ``store put <file>`` is one positional;
            ``store ls`` has none. Declared on the operation rather than guessed by
            the dispatcher, because *which* argument a command takes is a fact
            about the command.
        flags: The flags this command reads, which are the parameters of the port
            method it mirrors. Declared so the `E07-02` contract test can compare
            them against that signature rather than re-deriving them.
        buffer_key: Where this command's buffer sits inside an ``Evidence`` value,
            for a command whose value is not the buffer itself. ``None`` means the
            value carries no embedded buffer. See :func:`_apply_save` for why the
            two ``--save`` shapes are declared rather than discovered.

    """

    kernel: str
    name: str
    handler: Handler | None = None
    positional: str | None = None
    flags: tuple[str, ...] = ()
    buffer_key: str | None = None

    @property
    def is_mvp(self) -> bool:
        """Report whether this operation is declared but not implemented."""
        return self.handler is None


#: The operations the surface can dispatch, keyed by ``(kernel, operation)``.
#: Empty here on purpose: `E07-02` (`S1-T21`) fills it in as each adapter lands,
#: and this issue must not anticipate an adapter that does not exist.
_OPERATIONS: dict[tuple[str, str], Operation] = {}


def register(operation: Operation) -> None:
    """Declare one command on the surface.

    The seam `E07-02` uses. Registration is deliberately unconditional: an
    operation whose kernel module has not landed may still be declared, and it is
    ``--list`` that reports the kernel as unavailable, so the two facts stay
    separate.

    Args:
        operation: The operation to declare. A redeclaration replaces the previous
            one, which is what lets a test inject a handler without unwinding.

    """
    _OPERATIONS[(operation.kernel, operation.name)] = operation


def registered_operations() -> Mapping[tuple[str, str], Operation]:
    """Report every declared operation.

    Returns:
        A copy, so a caller cannot mutate the surface through it.

    """
    return dict(_OPERATIONS)


# --- The envelope ------------------------------------------------------------


def _encode(value: object) -> object:
    """Encode one value for the envelope.

    The seven boundary types are encoded **explicitly**, member by member, rather
    than by introspecting their dataclass fields. Two reasons, and the second is
    the load-bearing one: the envelope's shape is then pinned to the frozen
    contract rather than to whatever fields a type happens to have, and adding a
    field to a boundary type cannot silently change the wire format.

    Args:
        value: The value to encode.

    Returns:
        A JSON-encodable structure.

    Raises:
        TypeError: If the value is none of the encodable shapes. The encoder
            **refuses** rather than falling back to ``str(value)``: a stringified
            object is a stand-in that looks like data, and an envelope that cannot
            be encoded is a defect the caller must see, not a rendering choice.

    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, Bytes):
        return _describe_bytes(value)
    if isinstance(value, Artifact):
        return {
            "sha256": value.sha256,
            "size_bytes": value.size_bytes,
            "media_type": value.media_type,
            "path": value.path,
        }
    if isinstance(value, Evidence):
        return {
            "terms": _mapping(value.terms),
            "measurements": _mapping(value.measurements),
            "observed": _mapping(value.observed),
        }
    if isinstance(value, Reason):
        return {"code": value.code, "message": value.message}
    if isinstance(value, CallRecord):
        return {
            "provider": value.provider,
            "model": value.model,
            "model_revision": value.model_revision,
            "prompt_tokens": value.prompt_tokens,
            "completion_tokens": value.completion_tokens,
            "total_tokens": value.total_tokens,
            "cost_usd": value.cost_usd,
            "latency_ms": value.latency_ms,
            "request_id": value.request_id,
        }
    if isinstance(value, Token):
        return {
            "text": value.text,
            "page": value.page,
            "bbox": _encode(value.bbox),
            "confidence": value.confidence,
            "role": value.role,
        }
    if isinstance(value, Box):
        return {
            "x": value.x,
            "y": value.y,
            "width": value.width,
            "height": value.height,
        }
    if isinstance(value, InverseMap):
        return {
            "offset_x": value.offset_x,
            "offset_y": value.offset_y,
            "scale": value.scale,
        }
    if isinstance(value, Mapping):
        return {str(key): _encode(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_encode(item) for item in value]

    raise TypeError(
        f"no envelope encoding for {type(value).__name__}: the envelope carries "
        "the seven boundary types, mappings and sequences, and nothing else. An "
        "unencodable value is a defect, and rendering it as a string would publish "
        "a stand-in that reads like data."
    )


def _mapping(values: Mapping[str, object]) -> dict[str, object]:
    """Encode a mapping, converting the immutable mapping proxies the boundary uses.

    `E01-01` recorded the obligation this satisfies: ``MappingProxyType`` has no
    default JSON encoder, so a boundary value carrying one cannot leave the process
    until something converts it. That something is here, and it produces plain
    ``dict``s.

    Args:
        values: The mapping to encode.

    Returns:
        A plain mapping with encoded values.

    """
    return {str(key): _encode(item) for key, item in values.items()}


def _describe_bytes(value: Bytes) -> Mapping[str, object]:
    """Describe a buffer without putting it on stdout.

    A 40 MB rendered page inlined as base64 is neither testable nor diffable
    (`kernel-cli.md` §6), so stdout carries the descriptor and the bytes are
    opt-in. The hash is the real hash of the buffer either way, computed here
    rather than taken on trust - which is what makes the descriptor a claim a
    later verification can check.

    Args:
        value: The buffer to describe. ``path`` is None because nothing wrote it:
            the bytes are in memory and nowhere else.

    Returns:
        The descriptor, in the shape `kernel-cli.md` §6 prints.

    """
    return {
        "sha256": hashlib.sha256(value.data).hexdigest(),
        "size_bytes": len(value.data),
        "media_type": value.media_type,
        "path": None,
    }


def _repetitions(raw: object) -> int:
    """Read the ``--repeat`` count.

    ``--repeat`` is the surface's *demonstration* of a determinism class
    (`kernel-cli.md` section 7): run the same command N times and look at the hashes.
    It is deliberately **not** a retry-until-agreement loop, and nothing here compares
    two answers to decide whether to try again - it reports what happened, and the
    caller reads it.

    Args:
        raw: The flag's value, or None when it was not given.

    Returns:
        How many times to call the operation. One when the flag is absent.

    Raises:
        UsageError: If the count is not a positive integer. ``--repeat``'s *value* is
            the caller's text, so `kernel-cli.md` §5's *"bad flag"* applies and the
            exit is ``4``. A count of zero would run nothing and report success, which
            is the one outcome a determinism demonstration must not produce — but it
            is still the caller's argument that is wrong, not this build.

    """
    if raw is None:
        return 1
    try:
        count = int(str(raw))
    except ValueError as exc:
        raise UsageError(f"--repeat must be a positive integer; got {raw!r}") from exc
    if count < 1:
        raise UsageError(
            f"--repeat must be at least 1; got {count}. Running the operation zero "
            "times and reporting success would demonstrate nothing."
        )
    return count


def _call_once(handler: Handler, params: Mapping[str, object]) -> Call:
    """Call an operation once.

    Args:
        handler: The resolved implementation.
        params: The operation's parameters, shared across repetitions so every call is
            the same call by construction rather than by care.

    Returns:
        The answer.

    """
    return handler(**params)


def _envelope(call: Call) -> Mapping[str, object]:
    """Build the four-key envelope from one answer.

    The shape is fixed by `kernel-cli.md` section 6 and is the **surface's** contract,
    not the kernel's: it carries the four keys on every path that emits a
    ``KernelResult``, and the encoder below is what decides how each boundary type is
    rendered.

    Args:
        call: The answer to encode.

    Returns:
        The envelope, with ``value``, ``evidence``, ``reason`` and ``call_record``.

    """
    return {
        "value": _encode(call.result.value),
        "evidence": _encode(call.result.evidence),
        "reason": _encode(call.result.reason),
        "call_record": _encode(call.call_record),
    }


def _envelope_with_repetitions(
    call: Call, calls: Sequence[Call]
) -> Mapping[str, object]:
    """Build the envelope, adding the per-repetition hashes when there are several.

    The extra key appears **only** under ``--repeat``, so the envelope every other
    command emits is untouched - which is what `kernel-cli.md` section 6 fixes, and
    adding a key unconditionally would change it for every caller.

    The reported figure is the hash of the *encoded value*, and where there is none it
    is the hash of the encoded reason: a repetition of a failing call still has an
    answer to compare, and reporting nothing for it would make an all-failing run look
    like a run with no repetitions.

    Args:
        call: The answer to encode, which is the **last** repetition's.
        calls: Every repetition's answer, in order.

    Returns:
        The four-key envelope, plus ``repetitions`` under ``--repeat``.

    """
    envelope = dict(_envelope(call))
    if len(calls) < 2:
        return envelope

    envelope["repetitions"] = [
        hashlib.sha256(
            json.dumps(
                {
                    "value": _encode(repetition.result.value),
                    "reason": _encode(repetition.result.reason),
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        for repetition in calls
    ]
    return envelope


def _envelope(call: Call) -> Mapping[str, object]:
    """Build the four-key envelope from one answer.

    Args:
        call: The answer to encode.

    Returns:
        The envelope, with ``value``, ``evidence``, ``reason`` and ``call_record``.

    """
    return {
        "value": _encode(call.result.value),
        "evidence": _encode(call.result.evidence),
        "reason": _encode(call.result.reason),
        "call_record": _encode(call.call_record),
    }


# --- Exit codes --------------------------------------------------------------


def exit_code_for(result: KernelResult[object]) -> int:
    """Derive the process exit code from a kernel result.

    A value is :data:`EXIT_VALUE`. A missing value is the exit the closed
    vocabulary assigns to its reason code; a code outside that vocabulary is a
    defect rather than an outcome, so it becomes :data:`EXIT_INTERNAL` and never
    :data:`EXIT_REASON`.

    Args:
        result: The kernel's outcome.

    Returns:
        The exit code the process must report.

    """
    if result.value is not None:
        return EXIT_VALUE
    if result.reason is None:  # pragma: no cover - unreachable by construction
        return EXIT_INTERNAL
    return REASON_CODE_EXITS.get(result.reason.code, EXIT_INTERNAL)


# --- Dispatch ----------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class Invocation:
    """Everything one invocation wrote, as a value.

    The dispatcher returns this instead of writing to the streams itself, so the
    contract is testable without capturing file descriptors and so ``main`` is a
    three-line adapter. ``stdout`` is exactively what a pipe would receive, which
    is what makes the "``| jq`` is safe" claim checkable.

    Attributes:
        exit_code: The code the process must report.
        stdout: The text for stdout, exactly as it would be written.
        stderr: The human log for stderr. Never carries anything a script parses.

    """

    exit_code: int
    stdout: str = ""
    stderr: str = ""


def _usage_error(message: str) -> Invocation:
    """Build the exit-``4`` answer: a message and the usage text, no envelope.

    Args:
        message: What was wrong.

    Returns:
        The invocation, with an empty stdout.

    """
    return Invocation(exit_code=EXIT_USAGE, stdout="", stderr=f"{message}\n{_USAGE}")


def _parameter_name(flag: str) -> str:
    """Return the keyword-argument name a flag binds to.

    A flag is spelled with hyphens (``--target-dpi``) and a Python keyword is not,
    so the dispatcher has to translate. It used to strip the dashes only, which
    meant every hyphenated flag was stored under a name no handler reads and was
    **dropped in silence**: ``rescale --target-dpi 200`` arrived with the target
    absent and -- because a missing target must never become a default -- the
    command refused with exit ``2`` as though the caller had not asked. That is a
    parameter being swallowed, which is the same defect class as a flag being
    swallowed, so the translation lives here where the two names are one name.

    Args:
        flag: The flag as written, dashes included.

    Returns:
        The name the handler is called with.

    """
    return flag[2:].replace("-", "_")


def _parse_flags(
    tokens: Sequence[str], positional: str | None = None
) -> tuple[dict[str, object], Invocation | None]:
    """Parse the argument tokens into operation parameters.

    The dispatcher validates the *flag names* and the two it owns; interpreting a
    parameter's value is the operation's business. That split is what keeps the
    surface free of logic: a flag with no port counterpart never gets this far,
    because it is not in :data:`ALLOWED_FLAGS`.

    One positional is allowed, and only when the operation declares it. `E07-02`'s
    commands name their subject as an argument rather than a flag - `store put
    <file>` is `put(bytes, media_type)` in `kernel-cli.md` §9, not `put --file
    <file>`, and the two shapes are not equivalent: a flag is a parameter of the
    call, an argument is which call is being made.

    Args:
        tokens: The tokens after the operation name.
        positional: The parameter name a bare argument binds to, or None when the
            operation takes no argument.

    Returns:
        The parsed parameters, and an exit-``4`` invocation when an argument is
        unusable. Exactly one of the two is meaningful.

    """
    params: dict[str, object] = {}
    index = 0
    while index < len(tokens):
        token = tokens[index]

        if not token.startswith("--"):
            if positional is None or positional in params:
                return params, _usage_error(f"unexpected argument {token!r}")
            params[positional] = token
            index += 1
            continue

        # The name alone, without any `=value`, so the two vocabularies are matched
        # against the *flag* rather than against how it was written. Without this a
        # forbidden flag arriving as `--cuit=1` misses `FORBIDDEN_FLAGS` and is
        # refused as merely unknown - the right refusal and the wrong reason, which
        # `kernel-cli.md` section 14's vocabulary exists to distinguish.
        flag = token.split("=", 1)[0]

        if flag in FORBIDDEN_FLAGS:
            return params, _usage_error(
                f"{flag} does not exist on this surface, and never will: a flag "
                "naming a document concept, an engine, a skippable validation or a "
                "default model is the drift this surface refuses."
            )

        if flag not in ALLOWED_FLAGS:
            return params, _usage_error(f"unknown flag {flag!r}")

        if flag in BOOLEAN_FLAGS:
            params[_parameter_name(flag)] = True
            index += 1
            continue

        if "=" in token:
            # `--flag=value` is a form the surface does not accept, and accepting it
            # silently would make two spellings of every parameter. Refusing keeps one
            # grammar, and the message says which one.
            return params, _usage_error(
                f"{flag} takes its value as a separate argument: write "
                f"{flag} <value>, not {token!r}"
            )

        if index + 1 >= len(tokens):
            return params, _usage_error(f"{flag} requires a value")
        params[_parameter_name(flag)] = tokens[index + 1]
        index += 2

    return params, None


def _resolve_operation(
    kernel: str, name: str, table: Mapping[tuple[str, str], Operation]
) -> Handler | Invocation:
    """Resolve an operation name to the handler that implements it.

    Resolving all the way to the callable is what lets the caller work without an
    assertion that the handler is present: "this operation is not implemented" and
    "this operation does not exist" are both answered here, as invocations, and
    everything past this point holds a handler it can call.

    Args:
        kernel: The kernel name as given.
        name: The operation name as given.
        table: The registered operations.

    Returns:
        The handler to call, or the exit-``4`` answer explaining why there is none.

    """
    operation = table.get((kernel, name))
    if operation is None:
        return _usage_error(f"unknown operation {name!r} for kernel {kernel!r}")
    if operation.handler is None:
        return _usage_error(
            f"{kernel} {name} is not implemented in Stage 1 (kernel-cli.md §9 marks "
            "it `MVP`). It does not dispatch and does not run partially."
        )
    return operation.handler


def dispatch(
    argv: Sequence[str],
    *,
    table: Mapping[tuple[str, str], Operation] | None = None,
) -> Invocation:
    """Run one invocation and return everything it wrote.

    The one place exceptions are caught. Every handler call is wrapped, so a bug
    inside a kernel becomes exit :data:`EXIT_INTERNAL` with a traceback on stderr -
    never :data:`EXIT_REASON`, which would report a broken build as the document's
    answer.

    Args:
        argv: The arguments after the program name.
        table: The operations to dispatch against, or None for the registered
            surface. A test passes its own so that declaring a fixture cannot leak
            into the surface `E07-02` is building.

    Returns:
        The invocation: exit code, stdout and stderr.

    """
    operations = registered_operations() if table is None else table

    if not argv:
        return _usage_error("no kernel given")

    if "--list" in argv:
        if len(argv) > 1:
            return _usage_error("--list takes no other argument")
        return _list_invocation()

    kernel, *rest = argv
    if kernel not in KERNEL_BY_NAME:
        return _usage_error(f"unknown kernel {kernel!r}")

    if not rest:
        return _usage_error(f"no operation given for kernel {kernel!r}")

    name, *flag_tokens = rest
    resolved = _resolve_operation(kernel, name, operations)
    if isinstance(resolved, Invocation):
        return resolved

    operation = operations[(kernel, name)]
    params, bad_flag = _parse_flags(flag_tokens, operation.positional)
    if bad_flag is not None:
        return bad_flag

    # The positional is the call's *identity* - which call is being made - so the
    # dispatcher is the layer that can tell it is missing. It has to be checked
    # here: `_parse_flags` only binds a positional it *sees*, and the handler then
    # raises `TypeError` for an absent required keyword, which surfaced as exit
    # ``1`` with a traceback. Every command with a positional - `image info`,
    # `pdf probe`, `store get` - was affected, and a missing argument is a usage
    # error (exit ``4``), never an internal one.
    if operation.positional is not None and operation.positional not in params:
        return _usage_error(
            f"{kernel} {name} needs the {operation.positional} argument"
        )

    verbose = bool(params.pop("verbose", False))
    save_dir = params.pop("save", None)

    given_format = params.pop("format", "json")
    if given_format != "json":
        return _usage_error(
            f"--format {given_format} is not supported: json is the default and the "
            "only machine format (`kernel-cli.md` §10)"
        )

    return _invoke(
        resolved,
        kernel=kernel,
        operation=name,
        params=params,
        save_dir=save_dir,
        verbose=verbose,
        buffer_key=operation.buffer_key,
    )


def _invoke(  # pylint: disable=too-many-arguments
    handler: Handler,
    *,
    kernel: str,
    operation: str,
    params: Mapping[str, object],
    save_dir: object,
    verbose: bool,
    buffer_key: str | None = None,
) -> Invocation:
    """Call one handler and turn its answer into an invocation.

    The keyword-only parameters are the invocation's *identity*: which kernel and
    operation were named, and which dispatcher flags were given. They are passed
    separately from ``params`` because they are the surface's, not the operation's -
    ``params`` is exactly what the handler is called with.

    The one place exceptions are caught, and the reason exit ``2`` cannot be
    produced by a bug: everything a handler raises arrives here, and here it
    becomes :data:`EXIT_INTERNAL`.

    :class:`UsageError` is the one exception that arrives *before* that, and it
    becomes :data:`EXIT_USAGE`. A malformed invocation is not a defect in this
    build: `kernel-cli.md` §5 gives *"a malformed range"* its own exit, and a
    caller who typed the command can fix it. Catching it first is what keeps the
    two apart; without it every bad flag value was reported as `1`.

    Args:
        handler: The operation's implementation, already resolved.
        kernel: The kernel's name, for the verbose log line.
        operation: The operation's name, for the verbose log line.
        params: The parsed parameters, with the dispatcher's own flags removed.
        save_dir: The ``--save`` directory, or None.
        verbose: Whether ``--verbose`` was given.
        buffer_key: Where the operation's buffer sits inside an ``Evidence`` value,
            or None when its value carries no embedded buffer.

    Returns:
        The invocation.

    """
    try:
        repetitions = _repetitions(params.pop("repeat", None))
        calls = [_call_once(handler, params) for _ in range(repetitions)]
        written = _apply_save(calls[-1], save_dir, buffer_key=buffer_key)
        if isinstance(written, Invocation):
            return written
        envelope = _envelope_with_repetitions(written, calls)
        exit_code = exit_code_for(written.result)
        stdout = json.dumps(envelope, indent=2, sort_keys=False) + "\n"
    except UsageError as exc:
        return _usage_error(str(exc))
    except Exception:  # pylint: disable=broad-except
        return Invocation(
            exit_code=EXIT_INTERNAL,
            stdout="",
            stderr=traceback.format_exc(),
        )

    stderr = ""
    if verbose:
        stderr = f"{kernel} {operation} -> exit {exit_code}\n"
    return Invocation(exit_code=exit_code, stdout=stdout, stderr=stderr)


def _apply_save(
    call: Call, save_dir: object, *, buffer_key: str | None = None
) -> Call | Invocation:
    """Route a buffer through K7 when ``--save`` was given.

    The bytes are written by K7 and not by this module, so the hash in the
    descriptor is the hash of what was actually written - which is the whole point
    of ``--save`` (`E07-01`'s acceptance criteria). A handler that returns no
    buffer while ``--save`` is set is a usage error rather than a silent no-op: the
    caller asked for bytes to be persisted and none exist.

    There are **two** shapes a saved command can answer with, and the difference is
    declared rather than discovered. Most return the buffer itself as their value
    (`pdf render` answers a ``Bytes``). Some return their whole observation record,
    with the buffer *inside* it: K3's `crop` answers the `Evidence` because the bytes
    and the inverse map must travel together (`NFR-07`, matrix row 8). For those the
    operation declares ``buffer_key`` and this function reaches the buffer through it.

    Why the key is declared and not found: a scan for something that looks like bytes
    would take an arbitrary entry from a mapping guaranteed to be free-form. On a
    command carrying two buffers (`image tile`) it would save the wrong one and report
    success - the descriptor would be plausible and the check would pass. A declared
    key makes that either right or a refusal.

    Args:
        call: The handler's answer.
        save_dir: The ``--save`` directory, or None.
        buffer_key: Where the buffer sits inside an ``Evidence`` value, or None when
            the value carries no embedded buffer.

    Returns:
        The answer with its buffer replaced by the stored descriptor, or the
        exit-``4`` invocation when ``--save`` cannot apply.

    """
    if save_dir is None:
        return call

    value = call.result.value
    # A call that produced **no** value is passed through untouched, whatever its
    # reason. `--save` asks where to put the bytes; when there are none the question
    # does not arise, and reporting a usage error here would mask the kernel's typed
    # reason - turning *the document answered `insufficient_effective_resolution`*
    # (exit 2) into *you used `--save` wrongly* (exit 4), which is exactly the
    # conflation the exit table exists to prevent.
    if value is None:
        return call

    if buffer_key is not None:
        return _saved_embedded(call, save_dir, buffer_key)

    if not isinstance(value, Bytes):
        return _usage_error(
            "--save applies to a command that returns bytes; this one returned "
            f"{type(value).__name__}"
        )

    artifact = store.put(pathlib.Path(str(save_dir)), value.data, value.media_type)
    return Call(
        result=KernelResult(
            value=artifact, evidence=call.result.evidence, reason=call.result.reason
        ),
        call_record=call.call_record,
    )


def _saved_embedded(call: Call, save_dir: object, buffer_key: str) -> Call | Invocation:
    """Persist a buffer that sits inside an ``Evidence`` value.

    The declared key is reached for, not searched for, and every way it can fail to
    be a buffer is a refusal naming what was found. Silently skipping the save would
    report success for a dropped request; silently saving *something else* would be
    worse, because the descriptor would be plausible.

    The rebuilt record keeps the property the command guarantees - the value **is**
    the evidence, the same object rather than a copy - with the artifact in the
    buffer's place. So ``observed[buffer_key]`` gains the hash and the stored path
    exactly as `kernel-cli.md` §6 says a saved buffer does, and every other
    observation (``inverse_map`` above all) survives untouched.

    Args:
        call: The handler's answer, whose value must be an ``Evidence``.
        save_dir: The ``--save`` directory.
        buffer_key: The key the operation declares for its buffer.

    Returns:
        The answer with the buffer replaced by the descriptor, or the exit-``4``
        invocation naming why it could not be.

    """
    value = call.result.value
    if not isinstance(value, Evidence):
        return _usage_error(
            f"{buffer_key} is declared as this command's buffer, but its value is "
            f"{type(value).__name__} and not an observation record"
        )

    embedded = value.observed.get(buffer_key)
    if not isinstance(embedded, Bytes):
        return _usage_error(
            f"{buffer_key} is declared as this command's buffer, but "
            f"observed[{buffer_key!r}] holds {type(embedded).__name__}"
        )

    artifact = store.put(
        pathlib.Path(str(save_dir)), embedded.data, embedded.media_type
    )
    rebuilt = Evidence(
        terms=value.terms,
        measurements=value.measurements,
        observed=MappingProxyType({**value.observed, buffer_key: artifact}),
    )
    return Call(
        result=KernelResult(value=rebuilt, evidence=rebuilt, reason=call.result.reason),
        call_record=call.call_record,
    )
    # TODO: [MVP] The arrow here points at `docflow.kernels.store` because `E07-01`
    # is the dispatcher *at the kernel layer*, and its own guard asserts exactly
    # that. Routing this through `ArtifactStore` belongs to `E07-02`
    # (`S1-T21`), whose deliverable is `docflow/kernel_cli/store.py` — the
    # composition root. Until that lands, the adapter exists and nothing calls it;
    # recorded rather than papered over.
    # TODO: [MVP] The `--save` directory doubles as K7's store root, which is
    # `plan-01-kernels.md` §12 open decision #2: whether `--save` needs an explicit
    # `--root`. A default root would make the recorded hash real while the bytes
    # are disposable, so a test could pass over bytes already gone. Deciding it
    # belongs to the issue that owns the store's root, not here.


def _list_invocation() -> Invocation:
    """Build the ``--list`` invocation.

    The inventory is a *value*, so it leaves as a ``KernelResult`` like every other
    answer and the envelope shape is the same on this path as on any other.

    Returns:
        The invocation, exit ``0``.

    """
    rows = inventory()
    result: KernelResult[object] = KernelResult(
        value=list(rows),
        evidence=Evidence(
            terms={"surface": "docflow-kernel"},
            measurements={"kernels": float(len(rows))},
            observed={"available": sum(1 for row in rows if row["available"])},
        ),
        reason=None,
    )
    envelope = _envelope(Call(result=result))
    return Invocation(
        exit_code=EXIT_VALUE,
        stdout=json.dumps(envelope, indent=2) + "\n",
        stderr="",
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run one invocation as a process.

    The only function that touches a stream: everything else returns an
    :class:`Invocation`, which is what makes the contract testable without
    capturing file descriptors.

    Args:
        argv: The arguments after the program name, or None to read ``sys.argv``.

    Returns:
        The process exit code.

    """
    # The surface is registered by the **package's** import, not here. Registering
    # it in this function would make the dispatcher import the composition root, and
    # the composition root imports the dispatcher - a genuine import cycle, which
    # Pylint reports as one. The entry point is `docflow.kernel_cli:main`, so
    # importing the package is what running the command does, and that is where the
    # assembly belongs.
    invocation = dispatch(sys.argv[1:] if argv is None else argv)
    if invocation.stdout:
        sys.stdout.write(invocation.stdout)
    if invocation.stderr:
        sys.stderr.write(invocation.stderr)
    return invocation.exit_code
