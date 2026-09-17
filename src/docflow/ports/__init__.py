"""The five port interfaces: what everything above Stage 1 is allowed to depend on.

A port is the thing a caller depends on instead of a package. That is the whole
mechanism behind `ADR-004`: everything above Stage 1 must be able to run without
Poppler, without Docling, without Ollama and without a provider SDK, and that is
only possible if the thing a caller names is an **interface**.

The dependency arrow points down only
-------------------------------------

```text
docflow/adapters/   (Docling, pdftotext, Pillow, Ollama, a provider SDK)
        |
        v
docflow/ports/      (the five protocols below)
        |
        v
docflow/kernels/types.py
```

An adapter may import a port. A port may import the boundary types. **Nothing
imports an adapter except the composition root.** That is enforced by a static
check over the import graph rather than asserted in prose: see
``docflow.ports._typing`` and the isolation tests beside it.

Exactly five, and why each one
------------------------------

``PdfSource`` · ``OcrEngine`` · ``LlmEngine`` · ``ArtifactStore`` · ``Registry``.
The set is frozen by `plans/README.md` §3 (Plan 1 row) and is what Plan 2 builds
against. Each exists because the thing behind it is a **vendor** or a **store**:
a Poppler binary, a Docling install, a model runtime, a provider SDK, a
filesystem. Two are deliberately not one-per-kernel:

- ``LlmEngine`` covers both K5 and K6. A local model and a hosted one differ in
  determinism class, cost and failure modes (`sad.md` §4) — a difference that
  belongs to the **adapter**, not to the caller. Which of the two answered a call
  is a resolution decision recorded in the evidence and the call record.
- ``ArtifactStore`` and ``Registry`` cover K7 and K8 whole, because each of those
  kernels *is* the capability rather than a wrapper over a vendor.

**K3 `kernel.image` has no port here, and that is deliberate.** A raster library
is the one engine in the inventory that is not a vendor service behind a
swap-able boundary (`sad.md` §1 lists the adapters: Docling, pdftotext, Ollama,
provider SDKs, filesystem). Its operations live in ``docflow/kernels/image.py``
and its engine is that module's own concern, so naming a sixth interface for it
would put a boundary where the architecture did not ask for one.

The supporting value types declared beside these interfaces
-----------------------------------------------------------

``ReadResult`` and ``PageStatus`` are shapes an ``OcrEngine`` returns. They are
declared in ``docflow/ports/ocr.py`` rather than added to
``docflow/kernels/types.py``, which `E01-01` froze: a supporting type carries no
outcome of its own and is not a boundary state — the same standing ``Box`` has in
the frozen module.

What no port may expose
-----------------------

- **No adapter, ever.** A port that imported one would hold the arrow still by
  convention instead of by structure.
- **No decision.** A port reports observations — measurements, statuses, reasons
  for its own failure. It never returns a score, a verdict, or a routing
  outcome; those belong to the domain layer (`kernel-cli.md` §3, guardrail 2).
- **No default engine, model or threshold.** *"A silent fallback to a default
  model is the worst failure this layer can have"* (`kernel-cli.md` §3), and the
  same reasoning covers an engine and a measurement threshold.
- **No domain noun**, in any method name, parameter or return type. Domain
  knowledge arrives as **data** from K8, never as an identifier (`sad.md` §1).
- **No fake shipped as a default implementation.** A fake exists to satisfy a
  port in a test. Shipping one as the fallback implementation would be a silent
  fallback wearing a class name — **Never** (`E04-01` out-of-scope).

The symbols exported here are the public port surface Plan 2 builds against. It
is a reuse surface, not a supported external API: ``# TODO: [RELEASE]``.
"""

from __future__ import annotations

from docflow.ports.llm import LlmEngine
from docflow.ports.ocr import OcrEngine, PageStatus, ReadResult
from docflow.ports.pdf import PdfSource
from docflow.ports.registry import Registry
from docflow.ports.store import ArtifactStore

# Sorted alphabetically to satisfy Ruff's RUF022. As in
# `docflow/kernels/types.py`, the documented grouping lives in a constant rather
# than in the order of this list.
__all__: list[str] = [
    "ArtifactStore",
    "LlmEngine",
    "OcrEngine",
    "PageStatus",
    "PdfSource",
    "ReadResult",
    "Registry",
]

#: The five port interfaces, in the order `sad.md` §1 and `kernel-cli.md` §4 name
#: them. A declaration a consumer can assert against, so a sixth port cannot
#: appear without someone noticing; the supporting value types are deliberately
#: **not** in this tuple, because they are shapes a port returns rather than
#: capabilities a caller depends on.
PORT_INTERFACE_NAMES: tuple[str, ...] = (
    "PdfSource",
    "OcrEngine",
    "LlmEngine",
    "ArtifactStore",
    "Registry",
)
