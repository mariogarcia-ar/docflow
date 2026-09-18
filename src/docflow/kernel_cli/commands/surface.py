"""Register every command of the lab surface (`E07-02` / `S1-T21`).

The one place the surface is assembled. Importing this module declares each kernel's
commands against the dispatcher `E07-01` built, and it is deliberately the **last**
import a caller makes: the dispatcher's own guard asserts it imports nothing above
`docflow.kernels`, so the binding of adapters to commands has to happen outside it.

What is registered, and what is deliberately not
-----------------------------------------------

Every command in `kernel-cli.md` §9 is registered, whether or not it has an
implementation. A command with a handler dispatches; a command whose handler is
``None`` is an ``MVP`` command that exits ``4`` naming itself as unavailable. The
distinction matters because *"not implemented"* and *"does not exist"* are different
answers to a caller, and an unregistered command gives the second one.

This is what makes the acceptance criterion *"every `MVP` command exits `4`"* a fact
rather than an intention: the command is on the surface, it is listed, and it refuses.

One command = one port method
-----------------------------

The mapping is the contract, so it is written out rather than derived. `COMMANDS` in
each module is that mapping as data, and `tests/kernel_cli/test_commands.py` compares
each entry's flags against the port signature it mirrors. Adding a command here
without a port method behind it fails that test - which is the mechanism that keeps
this surface from becoming a second product API (`plan-01-kernels.md` §9, risk 1).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from docflow.kernel_cli.commands import (
    image as image_commands,
)
from docflow.kernel_cli.commands import (
    llm as llm_commands,
)
from docflow.kernel_cli.commands import (
    ocr as ocr_commands,
)
from docflow.kernel_cli.commands import (
    orchestrator as orchestrator_commands,
)
from docflow.kernel_cli.commands import (
    pdf as pdf_commands,
)
from docflow.kernel_cli.commands import (
    registry as registry_commands,
)
from docflow.kernel_cli.commands import (
    store as store_commands,
)
from docflow.kernel_cli.main import Handler, Operation, register

__all__: list[str] = ["REGISTERED", "build", "register_all"]

#: Kernel name to its command set. Each entry is
#: ``(operation, handler, positional, flags)``: a ``None`` handler is an ``MVP``
#: command, ``positional`` is the argument a bare token binds to, and ``flags`` are
#: the port parameters the command reads.
Command = tuple[str, Handler | None, str, tuple[str, ...]]

REGISTERED: dict[str, tuple[Command, ...]] = {
    "orchestrator": orchestrator_commands.COMMANDS,
    "store": store_commands.COMMANDS,
    "registry": registry_commands.COMMANDS,
    "pdf": pdf_commands.COMMANDS,
    "image": image_commands.COMMANDS,
    "ocr": ocr_commands.COMMANDS,
    "llm.local": llm_commands.COMMANDS["llm.local"],
    "llm.frontier": llm_commands.COMMANDS["llm.frontier"],
}

#: ``(kernel, operation)`` to the key where that command's buffer sits **inside** its
#: ``Evidence`` value, for the commands whose buffer is not their value.
#:
#: `image crop` is the whole reason this table exists, and it is not a workaround for
#: one awkward command. Its value *is* its observation record, because the bytes and
#: the inverse map must travel together (`NFR-07`, `kernel-cli.md` §11 row 8) - so the
#: crop's bytes are one level in, under ``observed["image"]``, and `--save` would
#: otherwise refuse a command that plainly has bytes to write.
#:
#: Declared here, in the composition root, because it is a fact about how `--save`
#: reads an answer, and `--save` is the dispatcher's own flag. Each command module
#: keeps owning *what it returns*: `commands/image.py`'s table still says `crop`
#: returns what it returns, and this table says only where to look inside it. That
#: split is why the dispatcher needs no import of a command module - `E07-01`'s guard
#: asserts it has none - and why a second such command does not widen `main`'s
#: surface.
#:
#: The key is **declared** rather than found by searching for something
#: bytes-shaped. A scan would take an arbitrary entry from a mapping whose shape is
#: free-form by contract; on a command carrying two buffers (`image tile`) it would
#: save the wrong one and report success, with a plausible descriptor and a check
#: that passes.
#:
#: An operation absent from this table is a command whose buffer, if it has one, *is*
#: its value (``pdf render``, ``pdf split``, ``store get``, ``image rescale``) or a
#: command with no buffer at all (``image info``, ``ocr read``). The two absences mean
#: different things and are both correct as an absence.
BUFFER_KEYS: Final[Mapping[tuple[str, str], str]] = {
    ("image", "crop"): "image",
}


def build() -> dict[tuple[str, str], Operation]:
    """Build the surface's operation table, without declaring anything.

    **Pure**, and that is what makes it testable: a test can hold the whole surface as
    data without the module-level table of the dispatcher being touched. A
    side-effecting builder would make every test that inspects the surface leak into
    every other test's view of it - which is a real defect this function exists to
    avoid, not a stylistic preference.

    Returns:
        The table, keyed the way the dispatcher keys it.

    """
    table: dict[tuple[str, str], Operation] = {}
    for kernel, commands in REGISTERED.items():
        for name, handler, positional, flags in commands:
            operation = Operation(
                kernel=kernel,
                name=name,
                handler=handler,
                positional=positional or None,
                flags=flags,
                buffer_key=BUFFER_KEYS.get((kernel, name)),
            )
            table[(kernel, name)] = operation
    return table


def register_all() -> None:
    """Declare every command on the dispatcher's surface.

    The side-effecting form, and the only caller is the package's import
    (`docflow/kernel_cli/__init__.py`). Idempotent: registering twice replaces each
    operation with an equivalent one, so a caller cannot double-declare its way into a
    duplicate.

    """
    for operation in build().values():
        register(operation)
