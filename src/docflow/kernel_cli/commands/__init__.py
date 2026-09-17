"""The composition root for ``docflow-kernel`` - which implementations answer.

`E07-02` / `S1-T21`. This package exists because the dispatcher cannot import an
adapter and the lab surface must still reach real engines. That is `E07-01`'s recorded
dependency, honoured here rather than relaxed there:

- ``docflow/kernel_cli/main.py`` imports ``docflow.kernels`` and nothing above it. Its
  own guard asserts that, and the guard is **right** - the dispatcher lives at the
  kernel layer by design.
- This package imports the adapters, binds each engine to its port, and registers one
  command per port method.

**Nothing above the adapters imports this package, and nothing here is imported by
``docflow``.** The lab surface may change freely; no downstream code may depend on it
(`kernel-cli.md` section 2). ``docflow run`` never invokes it.

One command = one port method
-----------------------------

The surface is a *window onto the ports*, not a second API. Every command maps to
exactly one port method and every flag to one parameter of it.
``tests/kernel_cli/test_commands.py`` compares each command flag set against the port
signature it mirrors and fails on any flag with no counterpart - which is what stops a
convenience flag from appearing and turning this surface into something maintained in
parallel with the library.

Where a command needs something the port does not carry, the answer is a **refusal**,
not an invention. The two modules below that are not commands exist for exactly that
reason.

Module layout
-------------

===========================  =========  ==============================================
Module                       Kernel     Commands
===========================  =========  ==============================================
``orchestrator.py``          K1         plan, run, ledger-read, manifest-rebuild,
                                        status, jobs, pause, resume, stop
``store.py``                 K7         put, get, verify, ledger-read,
                                        manifest-rebuild
``registry.py``              K8         validate, hash, show, ls
``pdf.py``                   K2         probe, classify, tokens, render, split
``image.py``                 K3         info, legibility, rescale, crop
``ocr.py``                   K4         capabilities, engine-info, read
``llm.py``                   K5, K6     capabilities, warm, structured, vision
``descriptor.py``            -          the injected reader for ``read_descriptor``
``policy.py``                -          the registry policy values, read or refused
``surface.py``               all        the one place the surface is assembled
===========================  =========  ==============================================

Two of those are not commands. ``descriptor.py`` and ``policy.py`` hold the two values
that are neither a parameter of a call nor a fact the kernel layer may hold: the
descriptor *format* (a vendor concern, and the kernel layer imports no third party) and
the corpus *thresholds* (`ADR-009`, registry policy with no override). Both are
load-or-refuse, so a command that needs one reports a precondition rather than
inventing a value.

``surface.py`` is imported once, by ``main.main``, and it is the only module here that
calls ``register``. Keeping the assembly in one file is what lets the contract test
walk the whole surface as data.
"""

from __future__ import annotations

__all__: list[str] = []
