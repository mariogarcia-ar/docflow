"""The `read` and `extract` stage implementations, in their Fase B form.

Fase A ran every stage on a fixed stub. Fase B1 wires the real engine into
`decide` and `hitl`; `read` and `extract` still produce fixed values here,
because the adapters behind them (`material`, the LLM lanes, the registry) are
the Fase B2 plumbing. The values are now the **real contracts** — an
`Extraction` with `FieldCandidate`s, not plain mappings — so the engine and the
queue run end to end over shaped input, while the adapter calls stay deferred.

Two facts worth stating, both deliberate:

- `read` returns a fixed material and is tagged `# TODO: [MVP]`: the real
  read is `material.py`, which needs the `docflow` adapters.
- `extract` builds candidates the way the engine expects (unmerged), plus the
  document-level values the arithmetic validator combines, and is tagged the
  same way: the real extract is `extract.py` with the LLM lanes.
"""

from __future__ import annotations

import dataclasses
import time

from .fields import Extraction, FieldCandidate

__all__: list[str] = [
    "STUB_LATENCY_SECONDS",
    "StageContext",
    "extract_stage",
    "read_stage",
]


@dataclasses.dataclass(frozen=True, slots=True)
class StageContext:
    """What a stage implementation receives, recorded so a test can assert the
    hand-off.

    Attributes:
        document: The document's file name.
        work_root: Where the run writes, or ``None``.

    """

    document: str
    work_root: str | None


#: How long a deferred stage waits before answering, so an interrupt or pause
#: test has a real window to act in. Removed together with the stub.
STUB_LATENCY_SECONDS: float = 0.5


def _simulate_work() -> None:
    """Block briefly, standing in for the real adapter call the stage defers."""
    time.sleep(STUB_LATENCY_SECONDS)


def read_stage(context: StageContext) -> dict[str, object]:
    """Stage `read`: a fixed material, the real contract's shape.

    The value is a plain mapping, not a `Material` — the real read is Fase B2
    (`material.py`), which constructs the adapter's type.  # TODO: [MVP]
    """
    _simulate_work()
    return {
        "kind": "pdf",
        "tier": "texto_nativo",
        "route": "layout_text",
        "pages_read": 1,
        "pages_total": 1,
        "notes": [f"stub read of {context.document}"],
    }


def _candidate(raw: str, producer: str) -> FieldCandidate:
    """One unmerged candidate, the shape the engine merges and scores."""
    return FieldCandidate(
        normalized_value="".join(ch for ch in raw if ch not in "., "),
        raw_value=raw,
        producers=[producer],
        signals=[],
        hard_refutations=[],
    )


def extract_stage(context: StageContext) -> Extraction:
    """Stage `extract`: fixed candidates the engine will actually decide over.

    The values mirror the smoke fixture's shape — a valid CUIT, a total that
    matches the subtotal-plus-IVA combination — so `decide` produces the same
    kinds of verdicts a real document does.  # TODO: [MVP]
    """
    _simulate_work()
    return Extraction(
        candidates={
            "cuit_emisor": [_candidate("20-22087601-3", "regexp")],
            "importe_total_facturado": [_candidate("17.898,30", "extractor_llm_texto")],
        },
        values={
            "subtotal": "15.000,00",
            "iva": "2.898,30",
            "importe_total_facturado": "17.898,30",
        },
        notes=[f"stub extract of {context.document}"],
    )
