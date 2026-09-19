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

import ast
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
    ("pdf", "layout", ("--pages",)),
    ("pdf", "render", ("--pages", "--dpi", "--save")),
    ("pdf", "split", ("--pages", "--save")),
    ("image", "info", ()),
    ("image", "legibility", ()),
    ("image", "rescale", ("--target-dpi", "--save")),
    ("image", "crop", ("--region", "--save")),
    ("ocr", "capabilities", ()),
    ("ocr", "engine-info", ()),
    ("ocr", "read", ("--pages", "--dpi", "--lang", "--correct")),
    ("ocr", "layout", ("--pages", "--dpi", "--lang", "--tolerance", "--orientation")),
    ("llm.local", "capabilities", ("--model",)),
    ("llm.local", "warm", ("--model",)),
    ("llm.local", "structured", ("--model", "--prompt-file", "--schema-file")),
    ("llm.local", "vision", ("--model", "--prompt-file", "--image", "--schema-file")),
    ("llm.frontier", "capabilities", ("--model",)),
    ("llm.frontier", "warm", ("--model",)),
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

#: Commands whose ``--save`` is satisfied by a buffer, in a kernel that has **no port**
#: to read a return annotation from.
#:
#: One entry, and it is a finding rather than a convenience. `image rescale` returns
#: ``KernelResult[Bytes]`` - `main._apply_save`'s ordinary path, and the same shape
#: `pdf render` takes - so it is savable. But K3 has **no port** at all (`E04-03`'s
#: decision: Pillow sits behind an inner seam in `adapters/image.py`, not behind a
#: sixth protocol), so :func:`_port_method` answers ``None`` and a check that read only
#: annotations would call a working command broken.
#:
#: Declared rather than special-cased, so the entry has to be read by a person the day
#: K3 gains a port - and removing it is then a deliberate act rather than a silent
#: widening.
SAVE_WITHOUT_A_PORT: Final[Mapping[str, str]] = {
    "image rescale": (
        "K3 has no port (E04-03), so there is no return annotation to read; the "
        "adapter returns KernelResult[Bytes] and --save takes the ordinary path"
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

    # And the one whose operation exists on the kernel but **not** on the port:
    # `layout_text` is kernel-only by `E04-02`, because `plans/README.md` §3 freezes
    # `PdfSource`'s five operations and a sixth would re-open `E04-01`'s gate. The
    # adapter exposes it, so the command is reachable while the port stays frozen.
    # Declared rather than discovered, so this check reports *no port method* on
    # purpose instead of silently skipping a flag set nobody compared.
    if (kernel, operation) == ("pdf", "layout"):
        return None

    # And K4's, for the same reason and one more. `layout` is kernel-only by
    # `E04-04` - `OcrEngine`'s three operations are frozen by `plans/README.md` §3 -
    # and it is *also* not the same thing as `layout_text`: a recogniser reports
    # blocks, so the rows are rebuilt from the token boxes rather than read as a
    # grid. Declaring it here keeps the direction check total rather than skipping
    # a flag set nobody compared.
    if (kernel, operation) == ("ocr", "layout"):
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


def test_every_registered_command_appears_in_section_9() -> None:
    """The reverse direction, and the hole that let a command in unsanctioned.

    The other tests measure §9 against the surface: every §9 command dispatches, and
    every §9 flag has a port parameter. Those pass on a surface that carries **extra**
    commands, so `llm.frontier warm` was registered `now` and dispatched while §9
    never mentioned it - the artifact said one thing and the binary did another, and
    every contract test stayed green.

    The measure is the same transcription (`NOW_COMMANDS` + `MVP_COMMANDS`), read in
    the other direction. A command that is registered and in neither list is a command
    the surface offers without the document sanctioning it, which is exactly the drift
    §9's tables exist to prevent.

    `GLOBAL_FLAGS` are the surface's own and are not commands, so they are excluded by
    construction rather than by an exemption table: this walks the *operations*, and a
    flag is never one.
    """
    sanctioned = {(kernel, operation) for kernel, operation, _ in NOW_COMMANDS}
    sanctioned |= set(MVP_COMMANDS)

    unsanctioned = sorted(set(main.registered_operations()) - sanctioned)

    assert unsanctioned == [], (
        "commands registered on the surface that §9 does not sanction: "
        f"{unsanctioned}. Either §9 gains the row or the command leaves the surface: "
        "a bench command nobody documented is a second API growing in the dark."
    )


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


# --- A declared flag must be dispatchable ----------------------------------


def _declared_flags() -> dict[str, set[str]]:
    """Return each registered command and the flags it declares.

    Read from the live table rather than restated, so a command added later is
    covered without editing this file.
    """
    by_operation: dict[str, set[str]] = {}
    for kernel, commands in surface.REGISTERED.items():
        for name, _handler, _positional, flags in commands:
            by_operation[f"{kernel} {name}"] = set(flags)
    return by_operation


def test_every_flag_a_command_declares_is_in_the_allowed_vocabulary() -> None:
    """The falsifier for a **real defect** that shipped once: nine dead commands.

    `kernel-cli.md` §9's per-command tables and §10's **prose** flag list disagree.
    The tables declare ``--target-dpi``, ``--prefix``, ``--asset``, ``--key``,
    ``--image``, ``--max-pixels``, ``--samples-file`` and ``--text-file``; the prose
    list omits all eight, and ``ALLOWED_FLAGS`` was built from the prose list. The
    dispatcher therefore refused each of those commands' **own required flag** as
    unknown, so `image rescale`, `image tile`, `store ls`, `registry show`,
    `registry ls` and all four `llm.*` commands were registered, listed and
    uncallable - the flag-parsing equivalent of the `image legibility` defect this
    suite already pins.

    §9 is the authority: a command that names a flag in its own table is a command
    that must be able to receive it. Asserted as a set difference so the message
    names every offending flag at once.
    """
    allowed = set(main.ALLOWED_FLAGS)
    offenders = sorted(
        f"{operation}: {flag}"
        for operation, flags in _declared_flags().items()
        for flag in flags
        if flag not in allowed
    )

    assert offenders == [], f"flags declared but not dispatchable: {offenders}"


def test_the_dispatcher_binds_a_hyphenated_flag_to_a_keyword_name() -> None:
    """A flag name is hyphenated; a Python keyword is not, so the two must be one name.

    The same defect as above, one layer down, and it was **silent after the
    vocabulary was fixed**: the parser stored ``flag[2:]``, so ``--target-dpi``
    became the key ``"target-dpi"`` while the handler reads ``target_dpi``. The value
    was dropped with no error, and because a rescale with no target must never become
    a default, the caller saw a refusal that blamed *them* for not asking.

    A parameter that is swallowed is indistinguishable from one that was never given,
    which is why this is asserted on the call the handler actually receives rather
    than on the parsed dictionary.
    """
    seen: dict[str, object] = {}

    def handler(**params: object) -> main.Call:
        """Record what the dispatcher bound, and answer with a value."""
        seen.update(params)
        return main.Call(
            result=main.KernelResult(
                value="ok",
                evidence=main.Evidence(
                    terms={"surface": "test"},
                    measurements={"n": 1.0},
                    observed={"note": "test"},
                ),
                reason=None,
            )
        )

    operation = main.Operation(
        "image",
        "rescale",
        handler,
        "file",
        ("--target-dpi", "--max-pixels", "--resolve-only"),
    )
    invocation = main.dispatch(
        [
            "image",
            "rescale",
            "page.png",
            "--target-dpi",
            "200",
            "--max-pixels",
            "4",
            "--resolve-only",
        ],
        table={("image", "rescale"): operation},
    )

    assert invocation.exit_code == main.EXIT_VALUE, invocation.stderr
    assert seen["target_dpi"] == "200", "the hyphenated flag binds to a keyword name"
    assert seen["max_pixels"] == "4"
    assert seen["resolve_only"] is True
    assert "target-dpi" not in seen, "the keyword cannot carry a hyphen"


# --- A command's value must be encodable -----------------------------------


def test_read_describes_its_result_rather_than_returning_it() -> None:
    """`ocr read` must translate its `ReadResult`, not hand it to the encoder.

    This is the falsifier for a **real defect** that shipped once, in the same class
    as the `InverseMap` crash: `ocr read` - a `now` command - returned its port-layer
    `ReadResult` unchanged, and the encoder refuses every type outside the seven
    boundary types. So the command **crashed** with exit ``1`` and *"no envelope
    encoding for ReadResult"* instead of answering, while `--list` still reported K4
    available.

    The assertion is on the **call site inside `read`**, not on the describer's
    existence, and that distinction is the whole test: an earlier draft checked
    `"_described(" in source` and stayed green when `read`'s return was reverted to
    the raw object, because the function *definition* still matched. A test that a
    defined-but-unused helper satisfies proves nothing about the call that matters.
    """
    module = importlib.import_module("docflow.kernel_cli.commands.ocr")
    source = pathlib.Path(module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    read_function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "read"
    )
    # Every call the function makes, by the name it calls.
    called = {
        node.func.id
        for node in ast.walk(read_function)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert "_described" in called, (
        "ocr read must pass its ReadResult through _described(); returning it "
        "verbatim is the exit-1 crash this test exists to catch"
    )
    # The positive control: the helper exists and is callable, so a rename that
    # broke the call above cannot pass by matching nothing.
    assert callable(module._described)  # pylint: disable=protected-access


def test_ocr_layout_scales_the_legacy_tolerance_to_the_requested_dpi() -> None:
    """The legacy's constant is in PDF points, and the flag is a DPI.

    `TOLERANCIA_LINEA = 25.0` could be a constant in the previous system because
    nothing in it read at another resolution. Here `--dpi` is a flag, so the
    tolerance is `25.0 * dpi / 72` — a **conversion**, not a copied number. A
    literal 25.0 at 300 DPI is a fifth of the row height and splits every row.

    This test is the falsifier for that conversion, and it is not vacuous: mutating
    the body to return the bare constant fails it. Measured on
    `casos/66e6e0ea` at 300 DPI, the literal gives 27 rows with 4 paired and the
    conversion gives 23 with 8 — so the defect is visible in the output rather than
    only in a number.
    """
    module = importlib.import_module("docflow.kernel_cli.commands.ocr")

    assert module._tolerance(None, 72) == 25.0, (  # pylint: disable=protected-access
        "at 72 DPI the legacy's points are already the boxes' own units"
    )
    assert module._tolerance(None, 300) == pytest.approx(  # pylint: disable=protected-access
        25.0 * 300 / 72
    ), (
        "the absent --tolerance must convert the legacy's points to the requested "
        "DPI; returning 25.0 there is a fifth of the row height and splits rows"
    )
    # An explicit flag wins, and is passed through unscaled: the caller naming a
    # number means that number in the boxes' own units.
    assert module._tolerance(40, 300) == 40.0  # pylint: disable=protected-access


def test_ocr_layout_reports_the_orientation_it_measured() -> None:
    """The orientation is the tokens' measurement, so it travels in the evidence.

    A caller who forces `--orientation vertical` on a horizontal document should be
    able to see the disagreement from the envelope rather than only from a reading
    that looks wrong.
    """
    module = importlib.import_module("docflow.kernel_cli.commands.ocr")
    source = pathlib.Path(module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    layout_function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "layout"
    )
    called = {
        node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
        for node in ast.walk(layout_function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, (ast.Attribute, ast.Name))
    }

    assert "dominant_orientation" in called, (
        "the absent --orientation must be measured from the tokens, not defaulted: "
        "a default is this surface deciding how a document is laid out"
    )
    assert "_laid_out" in called, (
        "the measurement must reach the evidence even when the caller forced the "
        "orientation, which is the only way a forced-wrong reading is detectable"
    )


# --- A command's value must survive the encoder — exercised, not assumed ----


def test_store_get_encodes_its_bytes_rather_than_handing_them_to_the_encoder(
    tmp_path: pathlib.Path,
) -> None:
    """``store get`` answers rather than crashing on its own buffer.

    The falsifier for a **real defect**, and the third of its kind: the encoder
    carries the seven boundary types, mappings and sequences, and `bytes` is none
    of them. So a handler returning the port's bare ``bytes`` **crashed** with
    exit ``1`` and *"no envelope encoding for bytes"* - `store get` could not
    read back a single artifact it had just stored (`ocr read` and `image crop`
    failed the same way with their own port-layer types).

    This one is asserted **behaviourally** rather than by scanning source, and it
    can be, because `store` needs no engine: a real ``put`` is performed and the
    ``get`` is dispatched through the real encoder. That is strictly stronger
    than the source check above - it fails for *any* reason the value cannot be
    encoded, not only for the one shape a scan looks for.
    """
    source = tmp_path / "blob.bin"
    source.write_bytes(bytes(range(256)) * 4)
    root = tmp_path / "store"

    stored = main.dispatch(
        [
            "store",
            "put",
            str(source),
            "--media-type",
            "application/octet-stream",
            "--root",
            str(root),
        ]
    )
    assert stored.exit_code == main.EXIT_VALUE, stored.stderr
    digest = json.loads(stored.stdout)["value"]["sha256"]

    read = main.dispatch(["store", "get", digest, "--root", str(root)])

    assert read.exit_code == main.EXIT_VALUE, (
        "a buffer must leave as a descriptor; handing the encoder raw bytes is "
        f"the exit-1 crash this test exists to catch: {read.stderr}"
    )
    described = json.loads(read.stdout)["value"]
    assert described["sha256"] == digest, "the descriptor describes what was read"
    assert described["size_bytes"] == source.stat().st_size
    assert "data" not in described, "the bytes themselves stay out of stdout"


# --- A declared ``--save`` must be able to save something -------------------


def _buffer_is_reachable(kernel: str, operation: str) -> bool:
    """Report whether ``--save`` could persist something for this command.

    Three ways a command can satisfy ``--save``, and they are the complete set
    `main._apply_save` implements:

    1. its value **is** a buffer - read either from the port's own return annotation,
       or from :data:`SAVE_WITHOUT_A_PORT` for a kernel that has no port to read;
    2. its value is an ``Evidence`` whose ``observed`` carries a buffer under the key
       the composition root declares in ``surface.BUFFER_KEYS`` (``image crop``);
    3. it declares no ``--save`` at all, in which case the question does not arise.

    The annotation is matched **case-insensitively on the word** rather than on the
    exact type name: K7's ``get`` returns ``KernelResult[bytes]`` while K2's ``render``
    returns ``KernelResult[Bytes]``, and both are a buffer. Requiring one spelling
    would make this check report a working command as broken.

    Args:
        kernel: The kernel's name.
        operation: The operation's name.

    Returns:
        Whether a buffer is reachable.

    """
    if (kernel, operation) in surface.BUFFER_KEYS:
        return True
    if f"{kernel} {operation}" in SAVE_WITHOUT_A_PORT:
        return True

    method = _port_method(kernel, operation)
    if method is None:
        return False

    annotation = inspect.signature(method).return_annotation
    return "bytes" in str(annotation).lower()


def test_every_command_that_declares_save_can_actually_save() -> None:
    """The direction that was missing, and the defect it would have caught.

    The suite already asserts *every flag a command declares is in the allowed
    vocabulary*, and that check is real - it caught nine commands whose own required
    flag the dispatcher refused. But it only asks whether a flag is **dispatchable**,
    never whether it can **do anything**: a flag can be accepted, bound, and then
    refused by the code that consumes it.

    ``image crop --save`` was exactly that. §9 declares ``--save`` on the command, the
    parser accepted it, and `_apply_save` answered *"this one returned Evidence"* -
    exit ``4`` - because the crop's buffer sits inside its observation record rather
    than being its value (`NFR-07`: the bytes and the inverse map travel together).
    Nothing in this suite could see it, because every existing check passes for a
    command whose flag is unreachable.

    Measured against the **declarations**, so a command added later with a save it
    cannot honour is red here rather than discovered from a shell. `llm.frontier
    structured` is the known instance still open: §9's K6 prose promises the raw
    completion is persisted, and no K6 command declares ``--save`` for it to be
    promised by.
    """
    offenders: list[str] = []
    for kernel, operation, flags in NOW_COMMANDS:
        if "--save" not in flags:
            continue
        if not _buffer_is_reachable(kernel, operation):
            offenders.append(f"{kernel} {operation}")

    assert offenders == [], (
        f"commands that declare --save and cannot produce a buffer for it: {offenders}"
    )


def test_the_buffer_key_table_names_a_real_command_and_a_real_key() -> None:
    """A declared buffer key must point at a registered command and a real key.

    Three ways a key goes stale, and each is silent on its own: the command is
    renamed, the key is misspelled, or the key is declared for a command that does not
    have it. The first two make `--save` refuse at run time - answerable, but only by a
    caller who happens to try it - and the third is worse, because a declared key that
    is absent from the answer is a command that looks savable and is not.

    The key is checked against the **live** handler's own observations where the
    command is reachable, so the assertion is on what the command reports rather than
    on a table agreeing with itself.
    """
    registered = main.registered_operations()

    for (kernel, operation), key in surface.BUFFER_KEYS.items():
        assert (kernel, operation) in registered, (
            f"BUFFER_KEYS names {kernel} {operation}, which is not registered"
        )
        assert key, f"{kernel} {operation} declares an empty buffer key"

    # The positive control, and the reason this test is not vacuous: `crop` is the one
    # entry, and it must still be reachable through it.
    assert ("image", "crop") in surface.BUFFER_KEYS, (
        "image crop's buffer is the case this table was introduced for"
    )
    assert _buffer_is_reachable("image", "crop")


# --- The one command whose operation is not on the port ---------------------


def test_pdf_layout_dispatches_and_reaches_the_kernel_only_operation() -> None:
    """``pdf layout`` exposes an operation the frozen port deliberately does not carry.

    `layout_text` returns the reader's own character grid, byte-identical to
    ``pdftotext -layout``, and `E04-02` recorded it as **kernel-only**: putting a sixth
    operation on `PdfSource` would re-open `E04-01`'s gate, since `plans/README.md` §3
    freezes the port's five operations. So the operation existed in the kernel and the
    adapter, the quickstart documented it, and there was **no way to invoke it** - the
    library-only gap this command closes.

    Asserted on the *port*, not just on the surface, because that is the half a fix
    could get wrong in the tempting direction: the command must not have been added by
    growing `PdfSource`.
    """
    assert ("pdf", "layout") in main.registered_operations(), (
        "pdf layout must dispatch; it is `now` in §9"
    )
    assert _port_method("pdf", "layout") is None, (
        "pdf layout is kernel-only by E04-02: a port method would re-open E04-01"
    )

    from docflow.ports import PdfSource  # pylint: disable=import-outside-toplevel

    assert not hasattr(PdfSource, "layout_text"), (
        "the port stays at five operations; the command reaches the adapter instead"
    )


def test_pdf_layout_is_reachable_through_the_adapter_the_command_binds() -> None:
    """The claim *the command can reach it* is measured, not inferred from registration.

    ``_port_method`` returning ``None`` says the *port* has no such method; it does not
    say the command's own engine does. A command bound to an adapter that never gained
    ``layout_text`` would register, dispatch, and fail at the first call - which is the
    registry-says-available-command-crashes shape this surface has already produced
    twice.
    """
    from docflow.adapters.pdf import (  # pylint: disable=import-outside-toplevel
        PdfEngine,
    )

    assert callable(getattr(PdfEngine, "layout_text", None)), (
        "the adapter the command binds must expose layout_text, or `pdf layout` "
        "cannot work however it is registered"
    )


def test_pdf_layout_refuses_a_reordered_selection_as_a_usage_error() -> None:
    """A descending selection is exit ``4``, not exit ``1`` and not a silent sort.

    ``layout_text`` refuses a reordered selection rather than sorting it, because the
    result is the reader's own concatenation and a sort would return a document the
    caller did not ask for. That refusal arrives as a ``ValueError``, and a
    ``ValueError`` reaching `_invoke`'s catch-all is answered as exit ``1`` - *"this
    build is broken"* - about something the caller fixes by retyping the command. The
    command translates it, the same way `image crop` does for a region outside the
    image.

    The check reads the *distinguishing* phrase rather than the exit code alone,
    because `parse_pages` also refuses bad ranges at exit ``4``: a code-only assertion
    cannot tell the kernel's ordering refusal from the parser's own.
    """
    invocation = main.dispatch(
        [
            "pdf",
            "layout",
            "tests/fixtures/matrix/three-invoices.pdf",
            "--pages",
            "2,1",
            "--root",
            "registry",
        ]
    )

    assert invocation.exit_code == main.EXIT_USAGE, (
        "a malformed selection is the caller's text, not a defect in this build: "
        f"got exit {invocation.exit_code}"
    )
    assert "strictly ascending" in invocation.stderr, (
        "the refusal must be the kernel's ordering one, not the parser's range check: "
        + invocation.stderr
    )
    assert invocation.stdout == "", "a usage error emits no envelope"
