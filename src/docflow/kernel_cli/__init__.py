"""``docflow-kernel`` - the lab surface over the kernels (`E07-01` / `S1-T20`).

A **package**, deliberately, and never a ``kernel_cli.py`` module beside it: the
per-kernel command modules ``E07-02`` adds land *inside* this package, and a
module of the same name would make that impossible without a rename that breaks
the entry point `pyproject.toml` already fixed.

This package is a harness, not a product. It may change freely, nothing downstream
may depend on it, and ``docflow run`` never invokes it (`kernel-cli.md` §2). It
exists so that each kernel's characteristic silent failure is invocable and
CI-asserted *before* any domain component is built on top of it - the first time a
kernel fails silently inside a component, the failure is attributed to the wrong
layer.

The entry point ``docflow-kernel = "docflow.kernel_cli:main"`` resolves to
:func:`docflow.kernel_cli.main.main`.

"""

from docflow.kernel_cli.main import main

__all__: list[str] = ["main"]
