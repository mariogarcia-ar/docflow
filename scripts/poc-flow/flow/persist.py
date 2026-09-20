"""Persistence and resumption for the flow's four stages.

The flow runs `read → extract → decide`. Without a record of the intermediate
artifacts, a failure anywhere forces a full re-run — and the language-model steps
are the expensive, paid-for ones. This module writes each stage's artifact as it
completes, plus a journal naming the stage it reached, so a second run resumes at
the first unfinished stage.

The design follows `scripts/poc/_mirror.py::Resume`, which this package's
README already cites as the lesson learned:

- **A stage is recorded only when its artifact is written.** A refusal or an
  exception leaves no `done` mark, so a transient failure is retried rather than
  becoming permanent.
- **A changed input re-does the work.** The journal carries the document's own
  sha256 digest.
- **A changed setting discards the journal.** The signature covers the run's
  dials and the artifact content; a different signature is a different run, and
  reusing its stages would mix two configurations nothing distinguishes.
- **Writes are atomic** (write to a temp name, then rename), so a kill mid-write
  leaves the previous artifact intact.

Everything here is the flow's own data model plus the standard library, except
for :class:`~docflow.kernels.types.Bytes`, which ``Material.images`` already
carries — it is imported after the same `ensure_docflow_importable()` call
`material.py` uses, and the serialisation logic itself stays adapter-free.
"""

from __future__ import annotations

# `wrong-import-order` / `wrong-import-position`: `docflow.kernels.types` is
# only importable once `_bootstrap` puts `src/` on `sys.path`, so the import
# must follow `ensure_docflow_importable()`. The order is load-bearing, not
# cosmetic — the same rule `material.py` and `extract.py` document.
# pylint: disable=wrong-import-order, wrong-import-position
import dataclasses
import hashlib
import json
import pathlib
import sys
from collections.abc import Mapping
from typing import Any, Final

from ._bootstrap import ensure_docflow_importable

ensure_docflow_importable()

from docflow.kernels.types import Bytes  # noqa: E402

from .artifacts import Artifacts  # noqa: E402
from .config import Config  # noqa: E402
from .extract import Extraction  # noqa: E402
from .fields import (  # noqa: E402
    EvidenceSignal,
    FieldCandidate,
    FieldDecision,
    FieldResult,
)
from .material import Material  # noqa: E402

__all__: list[str] = [
    "STAGES",
    "STAGE_DECIDE",
    "STAGE_EXTRACT",
    "STAGE_READ",
    "WorkTree",
    "document_digest",
    "work_signature",
]

#: The four stages in the order they run. `my_flow.md` §1 names them; the
#: journal marks how far a run got, one entry per stage.
STAGE_READ: Final[str] = "read"
STAGE_EXTRACT: Final[str] = "extract"
STAGE_DECIDE: Final[str] = "decide"
STAGES: Final[tuple[str, ...]] = (STAGE_READ, STAGE_EXTRACT, STAGE_DECIDE)

#: The journal's filename, inside a work root.
JOURNAL_NAME: Final[str] = "journal.json"

#: The intermediate artifact names, one per stage.
MATERIAL_NAME: Final[str] = "material.json"
EXTRACTION_NAME: Final[str] = "extraction.json"
DECISION_NAME: Final[str] = "decision.json"

#: Where the rendered pages live, for the vision lane. A text-only document has
#: no images and therefore no directory.
IMAGES_DIR: Final[str] = "images"


def document_digest(path: pathlib.Path) -> str:
    """Fingerprint a document's bytes, so an edited input is reprocessed.

    The journal is only sound if a changed input is re-read. An empty digest is
    **never** treated as done: an unsignable file is attempted, not assumed
    unchanged (`_mirror.digest_of`'s rule).
    """
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
    except OSError:
        return ""
    return digest.hexdigest()


def _jsonable(value: object) -> object:
    """Normalise a value for JSON: tuples and frozensets become lists, Paths
    their string form, dataclasses their dict.

    Sets and frozensets are **sorted** before conversion: their iteration order
    depends on hash randomisation, and a signature built from an unsorted set
    would differ between runs and discard the journal every time.
    """
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {key: _jsonable(val) for key, val in dataclasses.asdict(value).items()}
    if isinstance(value, (frozenset, set)):
        return [_jsonable(item) for item in sorted(value, key=repr)]
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, pathlib.Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _jsonable(val) for key, val in value.items()}
    return value


def work_signature(
    config: Config, own_cuits: frozenset[str], artifacts: Artifacts
) -> str:
    """Fingerprint everything a run's output depends on.

    The whole safety of resuming rests on this: a stage keyed only by path would
    be reused after the dials, the own-CUIT list or the prompts changed, and the
    resumed run would mix two configurations nothing distinguishes.
    """
    artifact_digests: dict[str, str] = {}
    for name, prompt in artifacts.prompts.items():
        artifact_digests[f"prompts/{name}"] = hashlib.sha256(
            prompt.encode("utf-8")
        ).hexdigest()
    for name, prompt in artifacts.review_prompts.items():
        artifact_digests[f"prompts_reviews/{name}"] = hashlib.sha256(
            prompt.encode("utf-8")
        ).hexdigest()
    artifact_digests["schema/extraction"] = hashlib.sha256(
        json.dumps(artifacts.extraction_schema, sort_keys=True).encode("utf-8")
    ).hexdigest()
    artifact_digests["schema_review/review"] = hashlib.sha256(
        json.dumps(artifacts.review_schema, sort_keys=True).encode("utf-8")
    ).hexdigest()

    parts = {
        "config": _jsonable(config),
        "own_cuits": sorted(own_cuits),
        "artifacts": artifact_digests,
    }
    canonical = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# --- The data model, to and from JSON ------------------------------------


def _signal_to_dict(signal: EvidenceSignal) -> dict[str, object]:
    return {
        "family": signal.family,
        "result": signal.result,
        "points": signal.points,
        "detail": signal.detail,
        "verified": signal.verified,
    }


def _signal_from_dict(data: Mapping[str, object]) -> EvidenceSignal:
    return EvidenceSignal(
        family=str(data["family"]),
        result=str(data["result"]),
        points=int(data["points"]),
        detail=str(data["detail"]),
        verified=bool(data.get("verified", False)),
    )


def _candidate_to_dict(candidate: FieldCandidate) -> dict[str, object]:
    return {
        "normalized_value": candidate.normalized_value,
        "raw_value": candidate.raw_value,
        "producers": list(candidate.producers),
        "signals": [_signal_to_dict(s) for s in candidate.signals],
        "hard_refutations": list(candidate.hard_refutations),
    }


def _candidate_from_dict(data: Mapping[str, object]) -> FieldCandidate:
    return FieldCandidate(
        normalized_value=str(data["normalized_value"]),
        raw_value=str(data["raw_value"]),
        producers=list(data["producers"]),
        signals=[
            _signal_from_dict(signal)
            for signal in data["signals"]  # type: ignore[arg-type]
        ],
        hard_refutations=list(data["hard_refutations"]),
    )


def _decision_to_dict(decision: FieldDecision) -> dict[str, object]:
    return {
        "field": decision.field,
        "severity": decision.severity,
        "decision": decision.decision,
        "reason_codes": list(decision.reason_codes),
        "winner": (
            _candidate_to_dict(decision.winner) if decision.winner is not None else None
        ),
        "runner_up": (
            _candidate_to_dict(decision.runner_up)
            if decision.runner_up is not None
            else None
        ),
        "score": decision.score,
        "margin": decision.margin,
        "threshold": decision.threshold,
        "strong": list(decision.strong),
        "gate_satisfied": decision.gate_satisfied,
        "notes": list(decision.notes),
    }


def _decision_from_dict(data: Mapping[str, object]) -> FieldDecision:
    winner = data.get("winner")
    runner_up = data.get("runner_up")
    return FieldDecision(
        field=str(data["field"]),
        severity=str(data["severity"]),
        decision=str(data["decision"]),
        reason_codes=list(data["reason_codes"]),
        winner=(_candidate_from_dict(winner) if isinstance(winner, Mapping) else None),
        runner_up=(
            _candidate_from_dict(runner_up) if isinstance(runner_up, Mapping) else None
        ),
        score=int(data["score"]),
        margin=int(data["margin"]),
        threshold=int(data["threshold"]),
        strong=tuple(data["strong"]),  # type: ignore[arg-type]
        gate_satisfied=bool(data["gate_satisfied"]),
        notes=list(data["notes"]),
    )


def _material_to_dict(material: Material) -> dict[str, object]:
    """The material without its image bytes; the images are written as files."""
    return {
        "kind": material.kind,
        "tier": material.tier,
        "text": material.text,
        "route": material.route,
        "pages_read": material.pages_read,
        "pages_total": material.pages_total,
        "image_count": len(material.images),
        "notes": list(material.notes),
    }


def _extraction_to_dict(extraction: Extraction) -> dict[str, object]:
    return {
        "candidates": {
            field: [_candidate_to_dict(c) for c in produced]
            for field, produced in extraction.candidates.items()
        },
        "values": dict(extraction.values),
        "notes": list(extraction.notes),
    }


def _extraction_from_dict(data: Mapping[str, object]) -> Extraction:
    candidates = {
        str(field): [_candidate_from_dict(c) for c in produced]
        for field, produced in data["candidates"].items()  # type: ignore[union-attr]
    }
    values = {  # type: ignore[union-attr]
        str(k): str(v) for k, v in data["values"].items()
    }
    return Extraction(
        candidates=candidates,
        values=values,
        notes=list(data["notes"]),
    )


def _result_to_dict(result: FieldResult) -> dict[str, object]:
    return {
        "decisions": {
            field: _decision_to_dict(decision)
            for field, decision in result.decisions.items()
        },
        "trace": {
            field: [_candidate_to_dict(c) for c in produced]
            for field, produced in result.trace.items()
        },
        "extracted": dict(result.extracted),
        "notes": list(result.notes),
    }


def _result_from_dict(data: Mapping[str, object]) -> FieldResult:
    return FieldResult(
        decisions={
            str(field): _decision_from_dict(decision)
            for field, decision in data["decisions"].items()  # type: ignore[union-attr]
        },
        trace={
            str(field): [_candidate_from_dict(c) for c in produced]
            for field, produced in data["trace"].items()  # type: ignore[union-attr]
        },
        extracted={  # type: ignore[union-attr]
            str(k): str(v) for k, v in data["extracted"].items()
        },
        notes=list(data["notes"]),
    )


def _write_atomic(path: pathlib.Path, payload: bytes) -> None:
    """Write bytes via a temp name then rename, so a kill cannot truncate."""
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(path.name + ".tmp")
    staging.write_bytes(payload)
    staging.replace(path)


class WorkTree:
    """The intermediate artifacts and journal for one document's run.

    A work root holds `material.json`, `images/` (when the document rendered),
    `extraction.json`, `decision.json` and `journal.json`. A second run against
    the same root resumes at the first stage whose artifact is absent.

    Attributes:
        root: The work root directory.
        signature: This run's settings fingerprint.
        digest: The document's own fingerprint.
        stale: Whether a journal existed and was discarded for a different
            signature or digest.

    """

    def __init__(
        self,
        root: pathlib.Path,
        signature: str,
        digest: str,
        *,
        redo: bool = False,
    ) -> None:
        self.root = root
        self.signature = signature
        self.digest = digest
        self._stages: dict[str, bool] = dict.fromkeys(STAGES, False)
        self.stale = False

        journal_path = root / JOURNAL_NAME
        if redo or not digest:
            return
        try:
            stored = json.loads(journal_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if stored.get("signature") != signature or stored.get("digest") != digest:
            self.stale = True
            return
        stages = stored.get("stages")
        if isinstance(stages, Mapping):
            for stage, entry in stages.items():
                if isinstance(entry, Mapping) and entry.get("done") is True:
                    self._stages[stage] = True

    def done(self, stage: str) -> bool:
        """Whether a previous run already produced this stage's artifact."""
        return self._stages.get(stage, False)

    def _mark(self, stage: str) -> None:
        """Record one stage as done and persist the journal atomically."""
        self._stages[stage] = True
        payload = {
            "signature": self.signature,
            "digest": self.digest,
            "stages": {stage: {"done": done} for stage, done in self._stages.items()},
        }
        _write_atomic(
            self.root / JOURNAL_NAME,
            json.dumps(payload, indent=2, sort_keys=True).encode("utf-8"),
        )

    # --- read ------------------------------------------------------------

    def save_material(self, material: Material) -> None:
        """Write the material and its rendered pages, then mark the stage done."""
        _write_atomic(
            self.root / MATERIAL_NAME,
            json.dumps(_material_to_dict(material), ensure_ascii=False).encode("utf-8"),
        )
        if material.images:
            images_dir = self.root / IMAGES_DIR
            for index, image in enumerate(material.images):
                _write_atomic(images_dir / f"page{index}.png", image.data)
        self._mark(STAGE_READ)

    def load_material(self) -> Material | None:
        """Reconstruct the material and its images, or ``None`` when absent."""
        path = self.root / MATERIAL_NAME
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        images: list[Any] = []
        image_count = int(data.get("image_count", 0))
        for index in range(image_count):
            image_path = self.root / IMAGES_DIR / f"page{index}.png"
            if not image_path.is_file():
                return None
            images.append(Bytes(data=image_path.read_bytes(), media_type="image/png"))
        return Material(
            kind=str(data["kind"]),
            tier=str(data["tier"]),
            text=str(data["text"]) if data.get("text") is not None else None,
            route=str(data["route"]),
            pages_read=int(data["pages_read"]),
            pages_total=int(data["pages_total"])
            if data.get("pages_total") is not None
            else None,
            images=images,
            notes=list(data["notes"]),
        )

    # --- extract ---------------------------------------------------------

    def save_extraction(self, extraction: Extraction) -> None:
        """Write the extraction, then mark the stage done."""
        _write_atomic(
            self.root / EXTRACTION_NAME,
            json.dumps(_extraction_to_dict(extraction), ensure_ascii=False).encode(
                "utf-8"
            ),
        )
        self._mark(STAGE_EXTRACT)

    def load_extraction(self) -> Extraction | None:
        """Reconstruct the extraction, or ``None`` when absent."""
        path = self.root / EXTRACTION_NAME
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return _extraction_from_dict(data)

    # --- decide ----------------------------------------------------------

    def save_result(self, result: FieldResult) -> None:
        """Write the final result, then mark the stage done."""
        _write_atomic(
            self.root / DECISION_NAME,
            json.dumps(_result_to_dict(result), ensure_ascii=False).encode("utf-8"),
        )
        self._mark(STAGE_DECIDE)

    def load_result(self) -> FieldResult | None:
        """Reconstruct the final result, or ``None`` when absent."""
        path = self.root / DECISION_NAME
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return _result_from_dict(data)

    def announce(self) -> None:
        """Print the resumption state to **stderr**, once, for the operator.

        stdout is the JSON verdict's surface — a resumption note printed there
        would corrupt it. stderr is for the operator, and that is where this
        goes.
        """
        if self.stale:
            print(
                "previous run used different settings or input: nothing will be "
                "resumed",
                file=sys.stderr,
            )
        resumed = [stage for stage in STAGES if self.done(stage)]
        if resumed:
            print(f"resuming after: {', '.join(resumed)}", file=sys.stderr)
