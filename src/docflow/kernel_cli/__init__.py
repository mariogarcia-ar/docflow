"""``docflow-kernel`` - the lab surface over the kernels (`E07-01` / `S1-T20`).

A **package**, deliberately, and never a ``kernel_cli.py`` module beside it: the
per-kernel command modules `E07-02` adds land *inside* this package, and a module of
the same name would make that impossible without a rename that breaks the entry point
`pyproject.toml` already fixed.

This package is a harness, not a product. It may change freely, nothing downstream may
depend on it, and ``docflow run`` never invokes it (`kernel-cli.md` section 2). It
exists so that each kernel's characteristic silent failure is invocable and
CI-asserted *before* any domain component is built on top of it - the first time a
kernel fails silently inside a component, the failure is attributed to the wrong layer.

The entry point ``docflow-kernel = "docflow.kernel_cli:main"`` resolves to
:func:`docflow.kernel_cli.main.main`.

Where the surface is registered, and why it is here
---------------------------------------------------

The composition root declares the 48 commands, and the import below is what runs it.
That placement is load-bearing rather than tidy:

- the entry point is ``docflow.kernel_cli:main``, so importing **this package** is what
  running the command does;
- the composition root imports the dispatcher, so registering inside ``main.main``
  would make the dispatcher import the composition root back - a genuine cycle, which
  Pylint reports as one;
- ``dispatch`` itself stays pure, so a test can pass its own table without the real
  surface leaking into its view of the dispatcher.

A caller who wants the surface **without** declaring it imports
``docflow.kernel_cli.commands.surface`` and calls ``build()``, which is pure. Both
forms exist because both are wanted: the CLI needs the table installed, and a test
needs to inspect it without installing anything.
"""

from docflow.kernel_cli.commands import surface
from docflow.kernel_cli.main import main

# The surface is declared at the package's import - see the module docstring for why
# this is the one place that works.
surface.register_all()

__all__: list[str] = ["main", "surface"]
