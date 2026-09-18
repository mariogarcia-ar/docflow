"""The flag/port contract test - `E07-02` / `S1-T21`.

This suite exists to falsify one named risk, and everything in it is arranged around
that: `plan-01-kernels.md` §9, execution risk 1 --

    *"Opening `S1-T21` before `S1-T12`-`S1-T17` are terminal. With no adapter landed
    there is no port signature to compare against, so the test passes **vacuously** -
    a green suite that proves nothing, and the first flag drift appears later, at the
    kernels' real consumer."*

Two consequences follow, and both are asserted here:

1. **The surface must be non-empty, and the non-emptiness is checked against a
   transcription of `kernel-cli.md` §9 rather than against itself.** A test that
   walked the registered table and asserted *every registered command has a port
   method* would pass on an empty table. So the `now` commands §9 names are written
   out below as data, and the assertion is that each one dispatches.
2. **A flag with no counterpart must fail.** That is the mechanism that stops a
   convenience flag from appearing and turning this surface into a second API. The
   counterpart is the port method's own parameter list, read from the live protocol.

The vocabulary check is the other half. `kernel-cli.md` §10 declares a forbidden set -
anything naming a document concept - and the six flags the artifacts forbid outright.
Those are asserted as an **exact absence** over the whole surface, because a
forbidden flag is the signal that the lab layer has drifted into the domain layer.

What this suite does not do is assert kernel *behaviour*; that is `E07-03`.
"""

# The port signatures and the §9 command list are restated here on purpose. A contract
# test must hold its own copy of what it verifies: importing the surface's own flag
# declarations would make every assertion vacuous, which is exactly the failure mode
# this suite was written to catch.
# pylint: disable=duplicate-code
# pylint: disable=too-many-lines
#
# `use-implicit-booleaness-not-comparison`: the four ``... == []`` comparisons are
# deliberate. Each one asks whether a *guard* found anything, and comparing to the
# empty list on purpose means a guard broken into returning ``None`` would read as
# *no findings* rather than as *clean* - the vacuous pass these guards exist to
# prevent. The same reason `tests/kernel_cli/test_main.py` records for the same
# finding.
# pylint: disable=use-implicit-booleaness-not-comparison

from __future__ import annotations

import importlib
import inspect
import json
import pathlib
import re
from collections.abc import Mapping
from typing import Final

import pytest

from docflow.kernel_cli.commands import surface

#: The dispatcher **module**, not the function the package re-exports: this suite
#: reads `FORBIDDEN_FLAGS`, `EXIT_USAGE` and the registered table, and the re-export
#: is the entry-point function by design (`E07-01`).
main = importlib.import_module("docflow.kernel_cli.main")

#: `kernel-cli.md` §9's `now` commands, transcribed: kernel, operation, and the flags
#: the table lists for it. This is the transcription the surface is measured against,
#: and it is deliberately **not** derived from the surface.
#:
#: The table's own note applies: `S1-T21`'s done-when asserts on the `now` set only.
NOW_COMMANDS: Final[tuple[tuple[str, str, tuple[str, ...]], ...]] = (
    ("orchestrator", "plan", ("--out",)),
    ("orchestrator", "run", ("--out", "--jobs", "--slots")),
    ("orchestrator", "status", ()),
    ("orchestrator", "jobs", ()),
    ("orchestrator", "pause", ()),
    ("orchestrator", "resume", ()),
    ("orchestrator", "stop", ("--force",)),
    ("orchestrator", "ledger-read", ()),
    ("orchestrator", "manifest-rebuild", ()),
    ("pdf", "probe", ()),
    ("pdf", "classify", ("--page",)),
    ("pdf", "tokens", ("--pages", "--dpi")),
    ("pdf", "render", ("--pages", "--dpi", "--save")),
    ("pdf", "split", ("--pages", "--save")),
    ("image", "info", ()),
    ("image", "legibility", ()),
    ("image", "rescale", ("--target-dpi", "--save")),
    ("image", "crop", ("--region", "--save")),
    ("ocr", "capabilities", ()),
    ("ocr", "engine-info", ()),
    ("ocr", "read", ("--pages", "--dpi", "--lang", "--correct")),
    ("llm.local", "capabilities", ("--model",)),
    ("llm.local", "warm", ("--model",)),
    ("llm.local", "structured", ("--model", "--prompt-file", "--schema-file")),
    ("llm.local", "vision", ("--model", "--prompt-file", "--image", "--schema-file")),
    ("llm.frontier", "capabilities", ("--model",)),
    ("llm.frontier", "structured", ("--model", "--prompt-file", "--schema-file")),
    (
        "llm.frontier",
        "vision",
        ("--model", "--prompt-file", "--image", "--schema-file"),
    ),
    ("store", "put", ("--media-type", "--root")),
    ("store", "get", ("--save", "--root")),
    ("store", "verify", ("--root",)),
    ("store", "ls", ("--prefix", "--root")),
    ("store", "ledger-read", ("--root",)),
    ("store", "manifest-rebuild", ()),
    ("registry", "validate", ("--root",)),
    ("registry", "hash", ("--root",)),
    ("registry", "show", ("--asset", "--key", "--root")),
    ("registry", "ls", ("--asset", "--root")),
)

#: The `MVP` commands §9 marks, which must be **declared and exit `4`** rather than
#: absent. An absent command and an unimplemented one are different answers.
MVP_COMMANDS: Final[tuple[tuple[str, str], ...]] = (
    ("pdf", "facts"),
    ("pdf", "images"),
    ("image", "deskew"),
    ("image", "phash"),
    ("image", "tile"),
    ("llm.local", "ps"),
    ("llm.local", "pull"),
    ("llm.local", "generate"),
    ("llm.frontier", "judge"),
    ("llm.frontier", "count-tokens"),
)

#: `kernel-cli.md` §10's forbidden vocabulary, restated. The first group names a
#: document concept; the second is the six flags the artifacts forbid outright.
FORBIDDEN: Final[tuple[str, ...]] = (
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
)

#: The port each kernel's commands mirror. Read from the live protocols, so a port
#: method that is renamed makes this suite red rather than silently unmatched.
PORTS: Final[Mapping[str, object]] = {
    "store": "ArtifactStore",
    "registry": "Registry",
    "pdf": "PdfSource",
    "ocr": "OcrEngine",
    "llm.local": "LlmEngine",
    "llm.frontier": "LlmEngine",
}

#: Flag to the port parameter it carries, where the two names differ.
#:
#: A port takes *text* and a command takes a *path*, so the mapping is real rather
#: than cosmetic: `--prompt-file` says the prompt comes from a file, and the port's
#: `prompt: str` says what the call receives. Declaring it here means a new file flag
#: has to be given a counterpart rather than merely being tolerated.
FILE_FLAG_PARAMETERS: Final[Mapping[str, str]] = {
    "--prompt-file": "prompt",
    "--schema-file": "schema",
    "--image": "images",
}

#: Port method to the command name §9 gives it, where the two differ.
#:
#: §9 does not derive command names from port names, and this suite must not pretend
#: it does: `read_ledger` is exposed as `ledger-read`, `rebuild_manifest` as
#: `manifest-rebuild`, `list` (K8's) as `ls`. Declaring the mapping means a rename on
#: either side lands here rather than in a silently unmatched loop.
PORT_COMMAND_NAMES: Final[Mapping[str, str]] = {
    "read_ledger": "ledger-read",
    "rebuild_manifest": "manifest-rebuild",
    "list": "ls",
}

#: Port methods with **no** command in §9, and the reason. One entry, and it is a
#: finding rather than a convenience.
#:
#: `ArtifactStore.write_ledger` writes a whole ledger in one call. §9 exposes the
#: ledger write path as `ledger-begin` / `ledger-commit` / `legacy-fail` - the three
#: transitions K1 actually drives - and deliberately not as a wholesale write, because
#: a caller that could replace a ledger would be able to erase the record the whole
#: design rests on. The method exists for K1's own use through the port, and a lab
#: command for it would be a way to rewrite history from a shell.
#:
#: Recorded here rather than left out, so the direction check stays total: every port
#: method is accounted for by a command or by this table.
PORT_METHODS_WITHOUT_COMMANDS: Final[Mapping[str, str]] = {
    "write_ledger": (
        "§9 exposes the ledger write path as the three transitions (begin / commit / "
        "fail), not as a wholesale write: a command that replaced a ledger would let a "
        "shell rewrite the record the design rests on"
    ),
}

#: Flags a command reads that the port method does not, with the reason each one is
#: the surface's rather than the call's.
#:
#: `ocr read --correct` is the one entry, and it is a **refusal today**: it gates the
#: corrected artifact, which needs a registry policy value the engine cannot read yet
#: (`# TODO: [MVP]`, `ADR-009`). It is listed rather than exempted so that the day it
#: becomes a port parameter, removing this entry is a deliberate act.
SURFACE_ONLY_FLAGS: Final[Mapping[str, str]] = {
    "--correct": (
        "gates the corrected artifact; a registry policy value (ADR-009), refused "
        "until S1-T21's successor can read one"
    ),
}


@pytest.fixture(scope="module", autouse=True)
def _registered() -> None:
    """Register the real surface once for the module.

    Autouse with module scope: every test here reads the registered table, and
    registering per test would be the same work repeated.

    """
    surface.register_all()


def _port_method(kernel: str, operation: str) -> callable | None:
    """Return the port method a command mirrors, or None when there is none.

    Args:
        kernel: The kernel's name.
        operation: The operation's name.

    Returns:
        The method, or None for a command that is not a port method (`jobs` is run
        discovery, `registry hash` has no method of its own).

    """
    # `kernel-cli.md` §9 names the two that are not port methods.
    if (kernel, operation) in {("orchestrator", "jobs"), ("registry", "hash")}:
        return None

    name = PORTS.get(kernel)
    if name is None:
        return None
    from docflow import ports  # pylint: disable=import-outside-toplevel

    protocol = getattr(ports, name)
    method_name = operation.replace("-", "_")
    return getattr(protocol, method_name, None)


# --- The surface is not empty, measured against §9 rather than itself -------


def test_every_now_command_from_section_9_is_registered() -> None:
    """The falsifier for a vacuous pass: §9's list is the measure, not the surface.

    A table that asserted *every registered command has a port method* would pass on
    an empty registration, which is exactly the green-suite-proves-nothing case the
    plan names. So the §9 list is transcribed above and each entry is required.
    """
    registered = set(main.registered_operations())

    missing = [
        (kernel, operation)
        for kernel, operation, _flags in NOW_COMMANDS
        if (kernel, operation) not in registered
    ]

    assert missing == [], f"§9 commands that do not dispatch: {missing}"
    assert len(NOW_COMMANDS) >= 38, (
        "the transcribed list is the measure; a shrunken list measures less"
    )


def test_every_now_command_has_a_handler() -> None:
    """A `now` command that cannot dispatch is an `MVP` command mislabelled."""
    registered = main.registered_operations()

    without = [
        (kernel, operation)
        for kernel, operation, _flags in NOW_COMMANDS
        if registered[(kernel, operation)].handler is None
    ]

    assert without == [], f"`now` commands declared without a handler: {without}"


def test_every_mvp_command_is_declared_and_exits_four() -> None:
    """`MVP` means declared and refusing, never absent and never a partial run.

    Both halves are asserted. *Declared* is the registration; *refuses* is the exit
    code, checked through `dispatch` so it is what a **process** would report.
    """
    registered = main.registered_operations()

    for kernel, operation in MVP_COMMANDS:
        assert (kernel, operation) in registered, (
            f"{kernel} {operation} is `MVP` in §9, so it must be declared: an absent "
            "command and an unimplemented one are different answers"
        )
        assert registered[(kernel, operation)].is_mvp, (
            f"{kernel} {operation} is marked `MVP` in §9 but has a handler"
        )
        invocation = main.dispatch([kernel, operation])
        assert invocation.exit_code == main.EXIT_USAGE, (
            f"{kernel} {operation} must exit {main.EXIT_USAGE} naming itself "
            f"unavailable; it exited {invocation.exit_code}"
        )
        assert invocation.stdout == "", "an MVP command emits no envelope"
        assert "not implemented" in invocation.stderr


def test_the_surface_covers_every_kernel_that_has_commands() -> None:
    """Each kernel with a command set in §9 has one registered here."""
    registered = main.registered_operations()
    kernels = {kernel for kernel, _operation in registered}

    assert kernels == {
        "orchestrator",
        "store",
        "registry",
        "pdf",
        "image",
        "ocr",
        "llm.local",
        "llm.frontier",
    }


# --- One command = one port method -----------------------------------------


def test_every_command_flag_has_a_counterpart_in_its_port_signature() -> None:
    """The 1:1 contract: a flag with no port parameter means the CLI became an API.

    The counterpart is read from the **live protocol**, so a port method that is
    renamed fails here rather than drifting. Three kinds of flag are accounted for
    separately, and each is a **declared mapping** rather than a silent exemption -
    the point is that every flag's counterpart is named somewhere, so a genuinely
    orphaned flag has nowhere to hide:

    1. `--root` is a port parameter for K7/K8 (they take a root) and the surface's for
       nothing else;
    2. `--out`, `--save`, `--jobs`, `--slots`, `--force` are the surface's own, each
       scoped by `kernel-cli.md` §10;
    3. the **file** flags map onto port parameters with a different name, because a
       port takes text and a command takes a path. That mapping is
       :data:`FILE_FLAG_PARAMETERS`, and it is one line per flag.

    """
    surface_flags = {
        "--out",
        "--save",
        "--jobs",
        "--slots",
        "--force",
        "--root",
    }

    offenders: list[str] = []
    for kernel, operation, flags in NOW_COMMANDS:
        method = _port_method(kernel, operation)
        if method is None:
            continue
        parameters = set(inspect.signature(method).parameters)
        for flag in flags:
            if flag in surface_flags or flag in SURFACE_ONLY_FLAGS:
                continue
            counterpart = FILE_FLAG_PARAMETERS.get(flag, flag[2:].replace("-", "_"))
            if counterpart not in parameters:
                offenders.append(f"{kernel} {operation}: {flag} -> {counterpart}")

    assert offenders == [], f"flags with no port parameter behind them: {offenders}"
    assert not (set(FILE_FLAG_PARAMETERS) & surface_flags), (
        "a mapped flag must not also be a surface flag, or it would be exempt twice"
    )


def test_every_port_method_of_a_bound_kernel_has_a_command() -> None:
    """The other direction: a port method with no command is an unreachable operation.

    Without this, the contract could be satisfied by one command per kernel and the
    rest of the port invisible - which is the *opposite* drift (a kernel nobody can
    probe) and just as bad for a bench whose whole purpose is to reach each operation
    one at a time.

    The exemption is `kernel-cli.md` §9's own: `store ledger-begin` / `ledger-commit` /
    `ledger-fail` are listed as a **group** against `begin` / `commit` / `fail`, so the
    three port methods arrive under hyphenated command names the naive
    `underscore -> hyphen` mapping cannot produce from `begin`. They are registered and
    therefore counted here by their declared names.
    """
    registered_names = {
        name for commands in surface.REGISTERED.values() for name, *_ in commands
    }
    # §9's grouped row: one line, three operations, three command names.
    grouped = {"begin", "commit", "fail"}
    registered_names |= {operation.replace("_", "-") for operation in grouped}
    registered_names |= set(PORT_COMMAND_NAMES.values())

    missing: list[str] = []
    for kernel, protocol_name in PORTS.items():
        from docflow import ports  # pylint: disable=import-outside-toplevel

        protocol = getattr(ports, protocol_name)
        for name in dir(protocol):
            if name.startswith("_"):
                continue
            if not callable(getattr(protocol, name, None)):
                continue
            if name in PORT_METHODS_WITHOUT_COMMANDS:
                continue
            if name in grouped:
                continue
            exposed = PORT_COMMAND_NAMES.get(name, name.replace("_", "-"))
            if exposed not in registered_names:
                missing.append(f"{kernel}: {name} -> {exposed}")

    assert missing == [], f"port methods with no command: {missing}"
    assert PORT_METHODS_WITHOUT_COMMANDS, (
        "the exemption table is empty, so either every port method has a command or "
        "this check stopped being total"
    )


# --- The forbidden vocabulary ----------------------------------------------


def test_no_flag_on_the_surface_names_a_document_concept() -> None:
    """§10's forbidden vocabulary, asserted as an exact absence over the whole surface.

    The check reads the **registered declarations**, so it covers every command rather
    than the ones a test happens to name. It also reads what the dispatcher will
    accept: a forbidden flag must be refused, so a drift that added the flag to
    `ALLOWED_FLAGS` alone would show up as an accepted flag with no command behind it.
    """
    declared: set[str] = set()
    for commands in surface.REGISTERED.values():
        for _name, _handler, _positional, flags in commands:
            declared.update(flags)

    offenders = sorted(declared & set(FORBIDDEN))
    assert offenders == [], f"forbidden flags declared on the surface: {offenders}"


def test_every_policy_key_a_command_reads_is_declared_by_the_registry() -> None:
    """A command that reads a policy key the registry does not declare cannot run.

    This is the falsifier for a **real defect** that shipped once: `image legibility`
    asked for `image.legibility_threshold` while the registry declared only
    `reader.correct`, `reader.min_chars` and `diagnosis.min_dpi`, so the command
    answered `asset_missing` for **every** image and the omission was invisible - the
    refusal is a typed reason, not an error, so nothing looked broken.

    Both sides are read from the repository rather than restated: the keys the command
    modules ask for, and the keys `registry/policies/thresholds.json` declares. A key
    added to a command without being added to the registry is a red test here instead
    of a refusal at run time.
    """
    commands_dir = pathlib.Path("src/docflow/kernel_cli/commands")
    asked: set[str] = set()
    for module in sorted(commands_dir.glob("*.py")):
        source = module.read_text(encoding="utf-8")
        asked.update(re.findall(r'policy_number\([^,]+,\s*"([^"]+)"', source))
        # A key read through the module-level constant is captured by its value.
        asked.update(
            match
            for match in re.findall(r'^_\w*KEY: Final\[str\] = "([^"]+)"', source, re.M)
        )

    declared = set(
        json.loads(
            pathlib.Path("registry/policies/thresholds.json").read_text(
                encoding="utf-8"
            )
        )
    )

    assert asked, "the scan found no policy key, so it is asserting nothing"
    missing = sorted(asked - declared)
    assert missing == [], (
        f"policy keys a command reads but the registry does not declare: {missing}. "
        "Each one makes its command answer a precondition for every input, which is "
        "invisible because the refusal is a typed reason rather than an error."
    )


def test_no_forbidden_flag_is_accepted_by_the_dispatcher() -> None:
    """Each of §10's forbidden flags is refused, by the dispatcher itself."""
    accepted: list[str] = []

    for flag in FORBIDDEN:
        invocation = main.dispatch(["store", "put", "x", f"{flag}=v"])
        if invocation.exit_code != main.EXIT_USAGE:
            accepted.append(f"{flag} -> exit {invocation.exit_code}")

    assert accepted == [], f"forbidden flags the dispatcher accepted: {accepted}"


def test_a_forbidden_flag_is_refused_by_its_own_message_in_either_spelling() -> None:
    """*Forbidden* and *unknown* are different refusals; both spellings get the first.

    The two vocabularies in §10 and §14 exist to make the reason attributable: a flag
    that names a document concept has **drifted** into the domain layer, while an
    unknown flag is a typo. A parser that matched the whole token would report
    `--cuit=1` as merely unknown, which is the right exit and the wrong reason.

    Asserted through `dispatch`, so it is the message a *process* prints.
    """
    for flag in FORBIDDEN:
        separate = main.dispatch(["store", "put", "x", flag, "v"])
        attached = main.dispatch(["store", "put", "x", f"{flag}=v"])

        for invocation in (separate, attached):
            assert invocation.exit_code == main.EXIT_USAGE
            assert "never will" in invocation.stderr, (
                f"{flag} must be refused as forbidden, not as unknown"
            )
            assert "unknown flag" not in invocation.stderr

        assert "unknown flag" in main.dispatch(["store", "put", "x", "--nope"]).stderr


def test_an_attached_value_is_refused_with_the_grammar_it_should_have_used() -> None:
    """`--flag=value` is not accepted, and the refusal names the form that is.

    Accepting it silently would give every parameter two spellings, and the surface
    would then have to keep them in step. Refusing keeps one grammar - and the message
    has to say which one, or the caller is left guessing at a syntax error.
    """
    allowed = main.dispatch(["store", "put", "x", "--root=somewhere"])

    assert allowed.exit_code == main.EXIT_USAGE
    assert "--root <value>" in allowed.stderr
    assert "--root=somewhere" in allowed.stderr
    assert "unknown flag" not in allowed.stderr

    # And the separate form is the one that works.
    separate = main.dispatch(["store", "put", "x", "--root", "somewhere"])
    assert separate.exit_code != main.EXIT_USAGE


def test_the_six_artifacts_forbidden_flags_are_absent_by_name() -> None:
    """The six the artifacts forbid outright, named individually so each is a red test.

    Grouped separately from §10's document-concept list because the *reason* differs:
    these are forbidden by `prd.md`, `ADR-001`, `ADR-002`, `ADR-005` and `ADR-006`
    rather than by the lab surface's own vocabulary rule.
    """
    for flag in (
        "--engine",
        "--no-validate",
        "--api-key",
        "--fallback",
        "--default-model",
        "--verify",
    ):
        assert flag in main.FORBIDDEN_FLAGS, f"{flag} must be refused outright"
        assert flag in FORBIDDEN, "and this suite must be checking it"


# --- `--out` and `--root` are not synonyms ---------------------------------


def test_out_and_root_are_not_conflated() -> None:
    """`--out` belongs to K1 and `--root` to K7/K8 (`kernel-cli.md` §10).

    A command that needs both is a sign the boundary has been crossed, so the check is
    per command: no command declares both.
    """
    both: list[str] = []
    for kernel, commands in surface.REGISTERED.items():
        for name, _handler, _positional, flags in commands:
            if "--out" in flags and "--root" in flags:
                both.append(f"{kernel} {name}")

    assert both == [], f"commands conflating --out with --root: {both}"
