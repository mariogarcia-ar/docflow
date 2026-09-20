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
from .hitl import HumanConfirmation, PendingItem, Suggestion  # noqa: E402
from .material import Material  # noqa: E402

__all__: list[str] = [
    "STAGES",
    "STAGE_ARTIFACTS",
    "STAGE_DECIDE",
    "STAGE_DEPENDENCIES",
    "STAGE_EXTRACT",
    "STAGE_HITL",
    "STAGE_READ",
    "WorkTree",
    "document_digest",
    "stage_artifact",
    "work_signature",
]

#: The four stages in the order they run. `my_flow.md` §1 names them; the
#: journal marks how far a run got, one entry per stage. The HITL stage is
#: terminal: it queues the fields the engine could not confirm (§8).
STAGE_READ: Final[str] = "read"
STAGE_EXTRACT: Final[str] = "extract"
STAGE_DECIDE: Final[str] = "decide"
STAGE_HITL: Final[str] = "hitl"
STAGES: Final[tuple[str, ...]] = (STAGE_READ, STAGE_EXTRACT, STAGE_DECIDE, STAGE_HITL)

#: What each stage needs before it can run. A stage's dependencies are its
#: *inputs*: `extract` reads the material, `decide` reads the candidates,
#: `hitl` reads the decisions. Running a stage on demand must first satisfy
#: these, in order.
STAGE_DEPENDENCIES: Final[dict[str, tuple[str, ...]]] = {
    STAGE_READ: (),
    STAGE_EXTRACT: (STAGE_READ,),
    STAGE_DECIDE: (STAGE_EXTRACT,),
    STAGE_HITL: (STAGE_DECIDE,),
}

#: The journal's filename, inside a work root.
JOURNAL_NAME: Final[str] = "journal.json"

#: The intermediate artifact names, one per stage.
MATERIAL_NAME: Final[str] = "material.json"
EXTRACTION_NAME: Final[str] = "extraction.json"
DECISION_NAME: Final[str] = "decision.json"
PENDING_NAME: Final[str] = "pending.json"
RESOLUTION_NAME: Final[str] = "resolution.json"
CONFIRMED_NAME: Final[str] = "confirmed.json"

#: Where the rendered pages live, for the vision lane. A text-only document has
#: no images and therefore no directory.
IMAGES_DIR: Final[str] = "images"

#: The artifact each stage writes, so a caller can name the file to open without
#: repeating the mapping. `hitl` writes its queue and, when there is something to
#: resolve or settle, the files beside it.
STAGE_ARTIFACTS: Final[dict[str, tuple[str, ...]]] = {
    STAGE_READ: (MATERIAL_NAME,),
    STAGE_EXTRACT: (EXTRACTION_NAME,),
    STAGE_DECIDE: (DECISION_NAME,),
    STAGE_HITL: (PENDING_NAME,),
}


def stage_artifact(root: pathlib.Path, stage: str) -> tuple[pathlib.Path, ...]:
    """The files a stage writes, inside a work root.

    Args:
        root: The work root.
        stage: One of the four stage names.

    Returns:
        The artifact paths, in the order the stage writes them. An unknown stage
        yields none rather than a guessed path.

    """
    return tuple(root / name for name in STAGE_ARTIFACTS.get(stage, ()))


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


def _pending_to_dict(item: PendingItem) -> dict[str, object]:
    return {
        "field": item.field,
        "severity": item.severity,
        "decision": item.decision,
        "reason_codes": list(item.reason_codes),
        "winner": (
            _candidate_to_dict(item.winner) if item.winner is not None else None
        ),
        "runner_up": (
            _candidate_to_dict(item.runner_up) if item.runner_up is not None else None
        ),
    }


def _suggestion_to_dict(suggestion: Suggestion) -> dict[str, object]:
    return {
        "field": suggestion.field,
        "suggested_value": suggestion.suggested_value,
        "reason": suggestion.reason,
    }


def _suggestion_from_dict(data: Mapping[str, object]) -> Suggestion:
    return Suggestion(
        field=str(data["field"]),
        suggested_value=(
            None
            if data.get("suggested_value") is None
            else str(data["suggested_value"])
        ),
        reason=str(data.get("reason", "")),
    )


def _resolution_to_dict(suggestions: list[Suggestion], note: str) -> dict[str, object]:
    return {
        "suggestions": [_suggestion_to_dict(s) for s in suggestions],
        "note": note,
    }


def _resolution_from_dict(
    data: Mapping[str, object],
) -> tuple[list[Suggestion], str]:
    raw = data.get("suggestions")
    suggestions: list[Suggestion] = []
    if isinstance(raw, list):
        suggestions = [
            _suggestion_from_dict(entry) for entry in raw if isinstance(entry, Mapping)
        ]
    return suggestions, str(data.get("note", ""))


def _confirmation_to_dict(confirmation: HumanConfirmation) -> dict[str, object]:
    return {
        "field": confirmation.field,
        "value": confirmation.value,
        "note": confirmation.note,
    }


def _confirmation_from_dict(data: Mapping[str, object]) -> HumanConfirmation:
    return HumanConfirmation(
        field=str(data["field"]),
        value=str(data["value"]),
        note=str(data.get("note", "")),
    )


def _encode(payload: object) -> bytes:
    """Serialise an artifact: UTF-8, non-ASCII left as-is, and indented.

    The artifacts are read by people as much as by the next stage — a decision is
    reviewed by opening `decision.json`. Indenting costs bytes and buys a file a
    diff can be read in; one compact line buys neither.
    """
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


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

    def clear_from(self, stage: str) -> None:
        """Mark a stage and every later one as not done, atomically.

        Re-running an intermediate stage invalidates its own artifact and
        everything downstream of it: a fresh `extract` makes the old `decision`
        and `hitl` stale. The artifacts themselves are not deleted — the journal
        simply stops trusting them, so a crash after clearing still resumes
        safely rather than reading half-invalidated state.
        """
        index = STAGES.index(stage)
        for later in STAGES[index:]:
            self._stages[later] = False
        self._write_journal()

    def _mark(self, stage: str) -> None:
        """Record one stage as done and persist the journal atomically."""
        self._stages[stage] = True
        self._write_journal()

    def _write_journal(self) -> None:
        """Persist the stage marks, without changing them."""
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
        _write_atomic(self.root / MATERIAL_NAME, _encode(_material_to_dict(material)))
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
            self.root / EXTRACTION_NAME, _encode(_extraction_to_dict(extraction))
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
        _write_atomic(self.root / DECISION_NAME, _encode(_result_to_dict(result)))
        self._mark(STAGE_DECIDE)

    def load_result(self) -> FieldResult | None:
        """Reconstruct the final result, or ``None`` when absent."""
        path = self.root / DECISION_NAME
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return _result_from_dict(data)

    # --- hitl (§8) -------------------------------------------------------

    def save_pending(self, items: list[PendingItem]) -> None:
        """Write the queue of fields the engine could not confirm, and mark the
        HITL stage done.

        The queue is the deliverable of §8's mechanical half: it is written even
        when the frontier cannot be reached, because *which fields need a human*
        is a fact of the document, not of the frontier's availability.
        """
        _write_atomic(
            self.root / PENDING_NAME,
            _encode({"pending": [_pending_to_dict(i) for i in items]}),
        )
        self._mark(STAGE_HITL)

    def load_pending(self) -> list[PendingItem]:
        """Reconstruct the queue, or an empty list when absent or empty."""
        path = self.root / PENDING_NAME
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        raw = data.get("pending")
        if not isinstance(raw, list):
            return []
        items: list[PendingItem] = []
        for entry in raw:
            if not isinstance(entry, Mapping):
                continue
            winner = entry.get("winner")
            runner_up = entry.get("runner_up")
            items.append(
                PendingItem(
                    field=str(entry["field"]),
                    severity=str(entry["severity"]),
                    decision=str(entry["decision"]),
                    reason_codes=list(entry["reason_codes"]),
                    winner=(
                        _candidate_from_dict(winner)
                        if isinstance(winner, Mapping)
                        else None
                    ),
                    runner_up=(
                        _candidate_from_dict(runner_up)
                        if isinstance(runner_up, Mapping)
                        else None
                    ),
                )
            )
        return items

    def save_resolution(self, suggestions: list[Suggestion], note: str) -> None:
        """Write the frontier's suggestions alongside the queue."""
        _write_atomic(
            self.root / RESOLUTION_NAME,
            _encode(_resolution_to_dict(suggestions, note)),
        )

    def load_resolution(self) -> tuple[list[Suggestion], str]:
        """Reconstruct the suggestions, or an empty list with no note."""
        path = self.root / RESOLUTION_NAME
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return [], ""
        return _resolution_from_dict(data)

    def save_confirmations(self, confirmations: list[HumanConfirmation]) -> None:
        """Write the human's confirmations, the only ground truth (§9).

        These are what a person settled; unlike the engine's stages, they are
        appended, never a resume mark — a confirmation is an input, not a stage
        that produces output.
        """
        _write_atomic(
            self.root / CONFIRMED_NAME,
            _encode(
                {"human_confirmed": [_confirmation_to_dict(c) for c in confirmations]}
            ),
        )

    def load_confirmations(self) -> list[HumanConfirmation]:
        """Reconstruct the confirmations, or an empty list when absent."""
        path = self.root / CONFIRMED_NAME
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        raw = data.get("human_confirmed")
        if not isinstance(raw, list):
            return []
        return [
            _confirmation_from_dict(entry)
            for entry in raw
            if isinstance(entry, Mapping)
        ]

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
