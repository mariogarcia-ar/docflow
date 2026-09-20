"""Standalone library: process one document and extract fiscal fields via MoE.

This package is a **library**, not a script bundle. It implements the decision
flow of `my_flow.md` on top of the `docflow` adapters, reusing the lessons from
`scripts/poc/` but none of its code:

- routing, classification and material extraction call `PdfEngine`,
  `RasterEngine` and `DoclingEngine` directly, exactly as the probes do;
- extraction and review call `OllamaEngine` and `FrontierEngine` directly;
- every verdict is PASS / FAIL / UNKNOWN, and UNKNOWN never scores, penalises
  or vetoes (`my_flow.md` I10);
- the score belongs to the candidate, and candidates with the same
  `normalized_value` merge before scoring (`my_flow.md` I2).

The public entry point is :func:`flow.run`. `myflow.py` next to this package is
one thin caller of it.
"""

from __future__ import annotations

from .config import DEFAULT_CONFIG, Config
from .fields import FieldResult
from .run import run

__all__: list[str] = ["DEFAULT_CONFIG", "Config", "FieldResult", "run"]
